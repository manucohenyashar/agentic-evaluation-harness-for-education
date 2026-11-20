"""TC-REG-23 (#895): SV-11's second cause pinned. E7-002/C1a's extracted span never starts inside
the region comment.

Traces: FR-EXTRACT-14 (-> TC-EXTRACT-19, TC-INTEG-22). Source:
`docs/design/statistical_validity_test_plan.md` §3.17.

**SV-11, second cause.** In the 2026-11-13 Run A, the extractor replied for E7-002 / C1a with
`{"start":606,"end":641,"text":"Tomas lights the lamp every evening."}`. The offsets are 23 bytes
early. `parse_spans` discarded the quote and took the text from the offsets, so the stored span
was `untrusted_content=1 -->Tomas lights`, starting inside Q1's region header.

Data: `tests/regression/data/sv11_live_extractions.json`, the verbatim live reply (Run A's first
extraction call for that unit) and the live canonical document it addressed. Nothing is edited.

Isolation: rung 1 on a real store (`tests/support/extraction_replay.py`): the live document
seeded as the submission's canonical bytes, the live reply recorded under the unit's request key,
the real `ExtractionWorker`, and the stored `evidence` row read back.
"""

from __future__ import annotations

import json

import pytest

from aeh.store import open_store
from tests.support.extraction_replay import (
    LIVE_EXTRACTIONS, live_documents, live_students, question_body, replay_pass)

pytestmark = pytest.mark.contract

_QUOTE = "Tomas lights the lamp every evening."


def _live_e7_002_c1a() -> tuple[str, str, str]:
    """(submission_id, canonical markdown, reply text) of Run A's first E7-002/C1a call."""
    students = live_students("A")
    (submission_id,) = [sid for sid, name in students.items() if name == "E7-002"]
    reply = next(call["response"] for call in LIVE_EXTRACTIONS["runs"]["A"]["calls"]
                 if call["submission_id"] == submission_id and call["criterion_id"] == "C1a")
    return submission_id, live_documents("A")[submission_id], reply


def _header_extents(doc: bytes) -> list[tuple[int, int]]:
    """Every region comment's byte extent (`<!-- region: ... -->` and `<!-- /region -->`)."""
    extents, at = [], doc.find(b"<!--")
    while at >= 0:
        end = doc.find(b"-->", at) + len(b"-->")
        extents.append((at, end))
        at = doc.find(b"<!--", end)
    return extents


def test_tc_reg_23_e7_002_c1a_extracted_span_never_starts_inside_the_region_comment(
        tmp_data_dir, make_fixture_provider):
    """TC-REG-23: the live reply, replayed through the real worker, stores the span on Q1's answer
    text, at the quote's bytes, never starting inside a region comment."""
    submission_id, markdown, reply = _live_e7_002_c1a()
    doc = markdown.encode("utf-8")
    (raw,) = json.loads(reply)["spans"]
    # The live failure, re-established from the data: the reply's own offsets start in Q1's
    # region header, and what they address is the walk's stored span.
    assert (raw["start"], raw["end"], raw["text"]) == (606, 641, _QUOTE)
    assert any(s <= raw["start"] < e for s, e in _header_extents(doc))
    assert doc[606:641].decode("utf-8").startswith("untrusted_content=1 -->Tomas lights")

    store = open_store(tmp_data_dir)
    try:
        stored = replay_pass(store, make_fixture_provider(), {submission_id: markdown},
                             {(submission_id, "C1a"): reply})
    finally:
        store.close()

    (span,) = stored[(submission_id, "C1a")]
    q_start, q_end = question_body(doc, "Q1")
    assert span["text"] == _QUOTE and doc[span["start"]:span["end"]] == _QUOTE.encode()
    assert not any(s <= span["start"] < e for s, e in _header_extents(doc)), span
    assert q_start <= span["start"] and span["end"] <= q_end, (span, q_start, q_end)
    assert span["start"] == q_start, "the quote opens E7-002's Q1 answer"
