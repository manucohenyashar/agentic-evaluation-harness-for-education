"""TC-REG-11 (#593): a citation of a pseudonymized span still verifies, and a forged one does not.

Assembly replaces a roster name with the unit's `student_ref` in every evidence span's text and
keeps the span's offsets, which index the stored document. A judge or the decision engine then
cites that span back. The citation-grounding gate must accept the pseudonymized text at the
stored offsets when it knows the unit's name, or every span that carried a name would fail
verification once names reach the unit. It must keep refusing anything else.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aeh import judge
from aeh.prov import MalformedResponseError

NAME = "Zelda Quartermaine"
REF = "P-0001"
RAW = f"Weight acts down. Signed, {NAME}. Again, {NAME}.".encode("utf-8")
CLEAN = RAW.decode("utf-8").replace(NAME, REF)


def _request():
    return SimpleNamespace(submission=SimpleNamespace(submission_id="S1", student_ref=REF))


def _span(text: str, start: int = 0, end: int = len(RAW)) -> dict:
    return {"start": start, "end": end, "text": text, "region_kind": "transcribed_text"}


def _gate(text: str, name=NAME, **offsets) -> None:
    judge._refuse_unverified_citations((_span(text, **offsets),), _request(), None, name)


@pytest.fixture(autouse=True)
def _stored_document(monkeypatch):
    monkeypatch.setattr(judge, "_canonical_document_bytes", lambda store, submission_id: RAW)


def test_tc_reg_11_a_pseudonymized_span_verifies_at_its_stored_offsets():
    _gate(CLEAN)


def test_tc_reg_11_the_documents_own_bytes_still_verify():
    _gate(RAW.decode("utf-8"))


@pytest.mark.parametrize("text, name", [
    (f"Weight acts down. Signed, {REF}. Again, P-0002.", NAME),  # two different replacements
    (f"Weight acts up. Signed, {REF}. Again, {REF}.", NAME),     # another byte changed
    (f"Weight acts down. Signed, {REF}.", NAME),                 # shorter than the offsets hold
    (CLEAN, "Zelda"),                                            # not this unit's name
    (CLEAN, None),                                               # no name known: strict bytes only
])
def test_tc_reg_11_anything_else_is_refused(text, name):
    with pytest.raises(MalformedResponseError):
        _gate(text, name=name)


def test_tc_reg_11_the_worker_remembers_the_name_it_assembled(monkeypatch):
    request = SimpleNamespace(work_id="w-1")
    monkeypatch.setattr(judge, "assemble", lambda unit, store=None: request)
    worker = judge.ScoringWorker.__new__(judge.ScoringWorker)
    worker._store = None
    assert worker.assemble(SimpleNamespace(work_id="w-1", student_name=NAME)) is request
    assert worker._roster_name_of(request) == NAME
    assert worker._roster_name_of(SimpleNamespace(work_id="w-2")) is None
