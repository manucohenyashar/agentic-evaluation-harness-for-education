"""TC-INTEG-20…23 (#894): quote-anchored relocation and the region-marker boundary.

Traces: FR-INTEG-13 (r2, D7), FR-INTEG-14, CT-INTEG-19 (amended), CT-INTEG-20; RSV-02, RSV-03.
Source: `docs/design/statistical_validity_test_plan.md` §3.2, story T1. Surface under test:
`aeh.integ.relocate_span(doc, span, region=None)` and `clear_of_region_markup`, both landed with
#863 (PR #918), so nothing here is written ahead.

| Case | Asserted |
|---|---|
| TC-INTEG-20 | `relocate_span`'s partitions, exact values: empty text, 0 / 1 / 2 occurrences, at byte 0, ending at the last byte, multi-byte text (byte offsets, not characters), and the near-misses a loose matcher would accept (curly vs straight quotes, NFD vs NFC, double vs single space, trailing space, case) all `None` |
| TC-INTEG-21 | Pure, model-free, zero-cost: 1,000 calls with the model and store surfaces blocked and the socket guard on return identical results; Hypothesis: a non-`None` result verifies and carries the quoted text |
| TC-INTEG-22 | On ENG7's real canonical document, both the acceptance path (`verify_span` + `clear_of_region_markup`) and the relocation path refuse any span that includes a marker byte, at the exact marker-edge bytes; the live E7-002/C1a span (Run A, copied in as data) is refused; a span spanning Q1's end and Q2's start is refused. Each row is also run through the citation gate `_refuse_unverified_citations` |
| TC-INTEG-23 | Cross-region (D7): a Q2 judge quoting a phrase unique to Q3's answer: `relocate_span(region=Q2)` is `None`, `region=None` finds it in Q3; through the real worker the reply is refused (no verdict row), and a spy sees a non-`None` region on every relocation the worker makes. Sensitivity arm: the worker's region dropped, the same reply IS credited (`reanchored = 1`) |

**TC-INTEG-23 departs from the plan text in one clause.** The plan says the refused span leaves
"the verdict stored uncited". FR-JUDGE-40 says a span that neither verifies nor relocates is
"refused exactly as today", and today a refused citation refuses the whole reply
(`MalformedResponseError`, struck within the budget, never persisted: FR-JUDGE-17/30). This case
follows the design: the reply is refused and no verdict row exists. The plan's "verdict stored
uncited" wording is the error.

**Not here: the extractor half of TC-INTEG-23's spy.** M-EXTRACT does not call `relocate_span`
until FR-EXTRACT-14 lands (#873). A spy asserting "every call from the extractor passes a region"
would pass on zero calls, so it is left to TC-EXTRACT-20 (#895), which covers
M-EXTRACT→CT-INTEG-19 once #873 lands.

Isolation: rung 0 for TC-INTEG-20/21/22 (pure functions over bytes; the citation-gate rows read
the document through a patched `_canonical_document_bytes`, the TC-REG-11 precedent). TC-INTEG-23's
worker arm is rung 1 on a real store (`tests/support/citation_world.py`). Documents are the real
ENG7 canonical documents M-INGEST wrote, never hand-written markup.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

import aeh.integ
import aeh.prov
import aeh.store
from aeh.integ import Span, answer_regions, clear_of_region_markup, relocate_span, verify_span
from tests.contract.integ._doubles import block_module_surfaces
from tests.support.citation_world import byte_span, citation_world, eng7_canonical, region_body

pytestmark = pytest.mark.contract

LIVE = json.loads((Path(__file__).resolve().parents[2] / "regression" / "data"
                   / "sv11_live_citations.json").read_text(encoding="utf-8"))


def _off(span: dict, by: int = 3) -> dict:
    """The span with its offsets shifted (a model that mis-counted bytes), its text unchanged."""
    return dict(span, start=span["start"] + by, end=span["end"] + by)


# --- TC-INTEG-20: the partitions --------------------------------------------------------------

_MB = "Notes: the keeper said café — שלום to the fisherman."
_PARTITIONS = [
    # (row, document, quoted text, expected (start, end) or None)
    ("empty text", b"the lamp burns", "", None),
    ("zero occurrences", b"the lamp burns", "the light", None),
    ("one occurrence", b"he climbs the steps and lights the lamp", "lights the lamp",
     (24, 39)),
    ("two occurrences", b"the lamp, the lamp", "the lamp", None),
    ("two overlapping occurrences", b"aaa", "aa", None),
    ("one occurrence at byte 0", b"Tomas keeps the light", "Tomas", (0, 5)),
    ("one occurrence ending at the last byte", b"he keeps the light", "the light", (9, 18)),
    ("multi-byte text, byte offsets", _MB.encode("utf-8"), "café — שלום",
     (len("Notes: the keeper said ".encode("utf-8")),
      len("Notes: the keeper said café — שלום".encode("utf-8")))),
    ("curly quotes against straight", b'he said "so" twice', "“so”", None),
    ("straight quotes against curly", "he said “so” twice".encode("utf-8"), '"so"', None),
    ("NFD against NFC", unicodedata.normalize("NFC", "a café here").encode("utf-8"),
     unicodedata.normalize("NFD", "café"), None),
    ("NFC against NFD", unicodedata.normalize("NFD", "a café here").encode("utf-8"),
     unicodedata.normalize("NFC", "café"), None),
    ("double space against single", b"the safe channel", "the safe  channel", None),
    ("trailing space the document lacks", b"lights the lamp.", "the lamp ", None),
    ("different case", b"Tomas lights the lamp", "tomas lights", None),
]


@pytest.mark.parametrize("row, doc, text, expected", _PARTITIONS, ids=[p[0] for p in _PARTITIONS])
def test_tc_integ_20_relocate_span_partitions(row, doc, text, expected):
    """TC-INTEG-20: exact return values for spans whose offsets do not verify."""
    # Offsets past the document's end: they can never verify, whatever the text.
    span = {"start": len(doc), "end": len(doc) + len(text.encode("utf-8")), "text": text}
    if text:
        assert not verify_span(doc, span), "precondition: the span's own offsets must not verify"
    result = relocate_span(doc, span)
    if expected is None:
        assert result is None, f"{row}: relocated to {result!r}"
        return
    assert result == Span(start=expected[0], end=expected[1], text=text), row
    assert doc[result.start:result.end] == text.encode("utf-8")


def test_tc_integ_20_multibyte_offsets_are_bytes_not_characters():
    """TC-INTEG-20's multi-byte row, its discriminating half: the character index differs from
    the byte index, and the result is the byte index."""
    doc = _MB.encode("utf-8")
    result = relocate_span(doc, {"start": 0, "end": 0, "text": "שלום"})
    char_index = _MB.index("שלום")
    assert result is not None and result.start == doc.index("שלום".encode("utf-8"))
    assert result.start != char_index, "fixture bug: the row must separate bytes from characters"


# --- TC-INTEG-21: pure, model-free, zero-cost --------------------------------------------------

def test_tc_integ_21_a_thousand_calls_touch_no_model_and_no_store(network_guard, monkeypatch):
    """TC-INTEG-21: 1,000 calls with every public callable of `aeh.prov` and `aeh.store`
    replaced by a raiser (and no store open) make no provider call and no store access, and
    return identical results."""
    doc = eng7_canonical().encode("utf-8")  # read before the blocks: the ingest opens a store
    block_module_surfaces(monkeypatch, aeh.prov)
    block_module_surfaces(monkeypatch, aeh.store)
    quote = _off(byte_span(doc, "A small fishing boat came out of the dark"))
    region = answer_regions(doc, "Q2")
    first = relocate_span(doc, quote, region)
    assert first is not None and doc[first.start:first.end] == quote["text"].encode()
    results = {relocate_span(doc, quote, region) for _ in range(1000)}
    assert results == {first}
    network_guard.assert_no_network()


@pytest.mark.property
@given(data=st.data(), doc_text=st.text(max_size=200), with_region=st.booleans())
def test_tc_integ_21_any_relocation_verifies_and_keeps_the_quote(data, doc_text, with_region):
    """TC-INTEG-21's property: whatever the document and quote, a non-`None` result verifies
    and its text is the quote. The quote is drawn half the time from the document itself, so the
    property is exercised on hits, not only on misses."""
    doc = doc_text.encode("utf-8")
    if doc_text and data.draw(st.booleans()):
        i = data.draw(st.integers(0, len(doc_text) - 1))
        j = data.draw(st.integers(i + 1, len(doc_text)))
        text = doc_text[i:j]
    else:
        text = data.draw(st.text(max_size=20))
    region = None
    if with_region:
        low = data.draw(st.integers(0, len(doc)))
        region = Span(start=low, end=data.draw(st.integers(low, len(doc))), text="")
    result = relocate_span(doc, {"start": 0, "end": 0, "text": text}, region)
    if result is not None:
        assert verify_span(doc, result)
        assert result.text == text
        if region is not None:
            assert region.start <= result.start and result.end <= region.end


# --- TC-INTEG-22: no span crosses region markup ----------------------------------------------

def _gate(monkeypatch, doc: bytes, span: dict, question_id: str | None):
    """The citation gate over `doc` for one span: the accepted spans, or the refusal."""
    from types import SimpleNamespace

    import aeh.judge.replies as replies

    monkeypatch.setattr(replies, "_canonical_document_bytes", lambda store, sid: doc)
    request = SimpleNamespace(submission=SimpleNamespace(submission_id="S", student_ref="r-x"),
                              evidence=(), dependency_evidence=())
    return replies._refuse_unverified_citations((span,), request, None, None,
                                                question_id=question_id)


def span_unique(doc: bytes, text: str) -> bool:
    return doc.count(text.encode("utf-8")) == 1


def _q2_edges(doc: bytes) -> tuple[int, int]:
    return region_body(doc, "Q2")


def _rows(doc: bytes) -> list[tuple[str, dict, bool]]:
    """(row, span, accepted) at the exact marker-edge bytes of the Q2 answer region."""
    start, end = _q2_edges(doc)
    assert doc[end:end + 4] == b"<!--" and doc[start - 3:start] == b"-->"

    def at(s: int, e: int) -> dict:
        return {"start": s, "end": e, "text": doc[s:e].decode("utf-8")}

    q1_start, q1_end = region_body(doc, "Q1")
    return [
        ("ends at the byte before <!--", at(end - 20, end), True),
        ("ends one byte into <!--", at(end - 20, end + 1), False),
        ("starts at the byte after -->", at(start, start + 20), True),
        ("starts one byte before -->'s end", at(start - 1, start + 20), False),
        ("covers Q1's end and Q2's start", at(q1_end - 10, start + 10), False),
    ]


def _row_ids() -> list[str]:
    return ["ends at the byte before <!--", "ends one byte into <!--",
            "starts at the byte after -->", "starts one byte before -->'s end",
            "covers Q1's end and Q2's start"]


@pytest.mark.parametrize("index", range(5), ids=_row_ids())
def test_tc_integ_22_marker_edges_on_both_paths(index, monkeypatch):
    """TC-INTEG-22: each marker-edge row on the acceptance path (`verify_span` holds for every
    row, so `clear_of_region_markup` alone decides), on the relocation path (the span's own text
    re-anchored: a marker-crossing occurrence is `None`), and through the citation gate."""
    from aeh.prov import MalformedResponseError

    doc = eng7_canonical().encode("utf-8")
    row, span, accepted = _rows(doc)[index]
    assert verify_span(doc, span), "precondition: every row's text is the document's own bytes"
    assert clear_of_region_markup(doc, span) is accepted, row
    relocated = relocate_span(doc, dict(span, start=0, end=0))
    if accepted:
        assert relocated == Span(span["start"], span["end"], span["text"]), (row, relocated)
    else:
        assert span_unique(doc, span["text"]), "fixture bug: uniqueness alone would relocate it"
        assert relocated is None, (row, relocated)
    if accepted:
        assert _gate(monkeypatch, doc, span, "Q2") == ((span,), False)
    else:
        with pytest.raises(MalformedResponseError):
            _gate(monkeypatch, doc, span, None)  # whole-document scope: the widest relocation


def test_tc_integ_22_the_live_e7_002_c1a_span_is_refused(monkeypatch):
    """TC-INTEG-22's live row: Run A's first extracted span for E7-002/C1a starts inside the
    region header (`untrusted_content=1 -->Tomas lights`). Its bytes are the document's own, so
    `verify_span` alone accepted it; the marker rule refuses it on both paths."""
    from aeh.prov import MalformedResponseError

    live = LIVE["run_a_e7_002"]
    doc = live["document"].encode("utf-8")
    span = {k: live["c1a_extracted_span"][k] for k in ("start", "end", "text")}
    assert span["text"].startswith("untrusted_content=1 -->Tomas lights")
    assert verify_span(doc, span), "precondition: the live span is the document's own bytes"
    assert clear_of_region_markup(doc, span) is False
    assert relocate_span(doc, span) is None
    assert relocate_span(doc, dict(span, start=0, end=0)) is None
    with pytest.raises(MalformedResponseError):
        _gate(monkeypatch, doc, span, "Q1")
    with pytest.raises(MalformedResponseError):
        _gate(monkeypatch, doc, span, None)


def test_tc_integ_22_a_unique_occurrence_over_marker_bytes_does_not_relocate():
    """TC-INTEG-22: a quote whose only occurrence includes marker bytes is `None`, though it is
    unique in the document (so the uniqueness rule alone would relocate it)."""
    doc = eng7_canonical().encode("utf-8")
    text = "is_untrusted_content=1 -->\nWhy does Tomas keep"
    assert doc.count(text.encode()) == 1, "fixture bug: the quote must be unique"
    assert relocate_span(doc, {"start": 0, "end": 0, "text": text}) is None
    clean = "Why does Tomas keep"
    assert doc.count(clean.encode()) == 1
    assert relocate_span(doc, {"start": 0, "end": 0, "text": clean}) is not None, (
        "control: the same words without the marker bytes relocate")


# --- TC-INTEG-23: cross-region relocation (D7) -----------------------------------------------

_Q3_ONLY = "a little taller than before"


def test_tc_integ_23_a_quote_from_another_questions_answer_is_not_found_in_this_region():
    """TC-INTEG-23, pure half: the phrase occurs once in the document, inside Q3's answer."""
    doc = eng7_canonical().encode("utf-8")
    occurrence = byte_span(doc, _Q3_ONLY)
    q3_start, q3_end = region_body(doc, "Q3")
    assert doc.count(_Q3_ONLY.encode()) == 1 and q3_start <= occurrence["start"] < q3_end
    quote = _off(occurrence, by=-40)
    q2_start, q2_end = region_body(doc, "Q2")
    assert relocate_span(doc, quote, region=answer_regions(doc, "Q2")) is None
    assert relocate_span(doc, quote, region=Span(q2_start, q2_end, "")) is None
    assert relocate_span(doc, quote, region=None) == Span(
        occurrence["start"], occurrence["end"], _Q3_ONLY)


class _RelocationSpy:
    def __init__(self, real):
        self.real = real
        self.regions: list = []

    def __call__(self, doc, span, region=None):
        self.regions.append(region)
        return self.real(doc, span, region)


def _q3_quote_reply(doc: bytes) -> dict:
    return {"cited_spans": [_off(byte_span(doc, _Q3_ONLY), by=-40)],
            "evidence_assessment": "The cited span shows the change in Tomas.",
            "evidence_sufficient": True, "band": "full", "self_confidence": 0.9}


def test_tc_integ_23_the_judge_worker_refuses_a_quote_from_q3_on_a_q2_unit(
        tmp_data_dir, make_fixture_provider, monkeypatch):
    """TC-INTEG-23, worker half: the Q2 unit's reply quotes Q3's words. The real worker scopes
    relocation to Q2's answer region, so the citation is refused, the reply with it (no verdict
    row: FR-JUDGE-40 "refused exactly as today"), and every relocation call carried a region."""
    import aeh.judge.replies as replies
    from aeh.judge import JudgmentError
    from aeh.store import open_store

    spy = _RelocationSpy(relocate_span)
    monkeypatch.setattr(replies, "relocate_span", spy)
    store = open_store(tmp_data_dir)
    try:
        world = citation_world(store, make_fixture_provider())
        with pytest.raises(JudgmentError, match="re-anchor"):
            world.judge_and_store(_q3_quote_reply(world.doc))
        assert world.verdict_rows() == []
    finally:
        store.close()
    assert spy.regions, "the worker never attempted a relocation: the case would be vacuous"
    assert all(region is not None for region in spy.regions), spy.regions
    # The region the worker passes holds Q2's answer and nothing of Q3's answer. (It may also hold
    # an untagged region following Q2's, such as the next page heading: ingest attributes
    # those to the question in force.)
    q2, q3 = region_body(world.doc, "Q2"), region_body(world.doc, "Q3")
    for region in spy.regions:
        extents = [(r.start, r.end) for r in region]
        assert q2 in extents, extents
        assert all(end <= q3[0] or start >= q3[1] for start, end in extents), extents


def test_tc_integ_23_sensitivity_with_the_region_dropped_the_q3_quote_is_credited(
        tmp_data_dir, make_fixture_provider, monkeypatch):
    """TC-INTEG-23's mutation, run as a sensitivity arm: the judge worker drops the unit's
    question (so no region reaches the gate). The same reply is then credited from Q3's answer,
    stored cited with `reanchored = 1`. This is what the refusal above prevents."""
    from aeh.judge import ScoringWorker
    from aeh.store import open_store

    monkeypatch.setattr(ScoringWorker, "_question_id_of", lambda self, request: None)
    store = open_store(tmp_data_dir)
    try:
        world = citation_world(store, make_fixture_provider())
        row = world.judge_and_store(_q3_quote_reply(world.doc))
    finally:
        store.close()
    occurrence = byte_span(world.doc, _Q3_ONLY)
    assert row["cited_spans"] == [occurrence] and row["reanchored"] == 1 and row["uncited"] == 0
