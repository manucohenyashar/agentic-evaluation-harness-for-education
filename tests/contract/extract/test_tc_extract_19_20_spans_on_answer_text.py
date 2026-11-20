"""TC-EXTRACT-19 and TC-EXTRACT-20 (#895), plus the extractor half of TC-INTEG-23's spy.

Traces: FR-EXTRACT-14, CT-EXTRACT-18; the pair M-EXTRACT -> CT-INTEG-19 (FR-INTEG-13's relocation,
scoped by region, ADR-63). Source: `docs/design/statistical_validity_test_plan.md` §3.3, §3.2,
story T2. Surface under test: `aeh.extract.spans.parse_spans(..., region=, roster_name=,
student_ref=)`, `unit_region`, and `ExtractionWorker.process`, all landed with #873 (PR #931), so
nothing here is written ahead.

| Case | Asserted |
|---|---|
| TC-EXTRACT-19 | Every live ENG7 extractor reply of the 2026-11-13 walk (64 calls, four passes of sixteen units) replayed verbatim through the real worker on the live canonical documents. Every STORED span: its bytes are exactly the reply's quote, contain no `<!--` / `-->`, lie inside one region's answer text and inside the unit's question's answer text (`verify_span` too). Every refused reply is pinned by name, and its cause is checked independently: some quote does not occur exactly once in the unit's answer text. A pass that stored nothing fails |
| TC-EXTRACT-20 | Model-offset path: a reply 5 bytes early (inside the opening marker) with the right quote is relocated onto the answer text, through `parse_spans` and through the worker; with the quote twice in the answer, the reply is refused and nothing is stored. Property (Hypothesis): any span `parse_spans` returns satisfies `canonical[start:end] == text.encode()`, carries the quote it was given, and lies on answer text clear of markers |
| TC-INTEG-23 (extractor arm) | A spy on `aeh.extract.spans.relocate_span` sees, on every call from the extractor's primary AND second-family passes, a region holding the unit's question's answer text and no other question's. Sensitivity arm: with the unit's question scope dropped, a Q3 quote on a C2 unit IS stored at Q3 |

**Departures.**
- *PS9.* The plan replays ENG7 E7-001..004 AND PS9 S9-001..006. No live or recorded extractor
  reply over the PS9 sample documents exists (both live walks graded ENG7 only; the repo's
  extractor recordings are synthetic dev corpora), and recordings are never hand-written. The
  PS9 half of TC-EXTRACT-19 is a named gap, not a census over zero spans.
- *Rendered-view path.* FR-EXTRACT-14 leaves open whether offsets come from the model or are mapped
  from a rendered view. #873 found they come from the model; no rendered-view mapping exists. The
  plan's property `canonical[start:end] == text.encode()` is applied to the path that exists
  (every span `parse_spans` stores), and the plan's §7a still needs the line recording the absent
  arm (owner: `/create-test-plan`).

Isolation: TC-EXTRACT-19 is rung 3 data (live replies, live documents) on a rung 1 transport
(`RecordedFixtureProvider`, real store, real worker). TC-EXTRACT-20 and the spy arm read the real
ENG7 canonical documents M-INGEST wrote (`tests/support/citation_world.eng7_canonical`); replies
there are built from the document's own bytes, never recordings of a live model.
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import aeh.extract.spans as spans_module
import aeh.extract.worker as worker_module
from aeh.extract.spans import parse_spans, unit_region
from aeh.integ import relocate_span, verify_span
from aeh.store import open_store
from tests.support.citation_world import byte_span, eng7_canonical
from tests.support.extraction_replay import (
    CRITERION_QUESTIONS, answer_bodies, live_documents, live_passes, live_students,
    question_body, replay_pass)

pytestmark = pytest.mark.contract

_MARKERS = (b"<!--", b"-->")


def _quotes(reply: str) -> list[str]:
    return [span["text"] for span in json.loads(reply)["spans"]]


def _on_answer_text(doc: bytes, start: int, end: int) -> bool:
    return any(s <= start and end <= e for s, e in answer_bodies(doc))


# --- TC-EXTRACT-19: the live replay census ----------------------------------------------------

#: The replies the census expects refused, per pass, by (student, criterion). Each cause is
#: re-checked below from the bytes; these are the model's quotes that are not in the unit's
#: answer text exactly once:
#: - E7-001/C1b (A, pass 1): `"steps a\n lights"`, a space the document does not hold;
#: - E7-003/C1b (every pass): `"He lights it every night."` is the student's Q2 answer, quoted
#:   for a Q1 criterion (ADR-63: another question's words are not this unit's evidence);
#: - E7-001/C3 (B, pass 2): `"the steps\na little"`, a line break the document does not hold.
_REFUSED = {
    ("A", 0): {("E7-001", "C1b"), ("E7-003", "C1b")},
    ("A", 1): {("E7-003", "C1b")},
    ("B", 0): {("E7-003", "C1b")},
    ("B", 1): {("E7-003", "C1b"), ("E7-001", "C3")},
}


@pytest.mark.parametrize("run, index", sorted(_REFUSED), ids=[f"run{r}-pass{i + 1}"
                                                              for r, i in sorted(_REFUSED)])
def test_tc_extract_19_live_eng7_replies_store_spans_on_answer_text_only(
        run, index, tmp_data_dir, make_fixture_provider):
    """TC-EXTRACT-19: replay one pass of the live walk through the real worker and census every
    stored span against the exact predicates."""
    documents = live_documents(run)
    students = live_students(run)
    replies = live_passes(run)[index]
    assert len(replies) == 16, "fixture bug: a pass is the 4 students x 4 extracted criteria"
    store = open_store(tmp_data_dir)
    try:
        stored = replay_pass(store, make_fixture_provider(), documents, replies)
    finally:
        store.close()

    refused, stored_spans = set(), 0
    for (submission_id, criterion_id), reply in sorted(replies.items()):
        doc = documents[submission_id].encode("utf-8")
        who = (students[submission_id], criterion_id)
        quotes = _quotes(reply)
        q_start, q_end = question_body(doc, CRITERION_QUESTIONS[criterion_id])
        spans = stored[(submission_id, criterion_id)]
        if spans is None:
            refused.add(who)
            assert quotes, f"{who}: an empty reply must store an empty span set, not refuse"
            in_answer = doc[q_start:q_end]
            assert any(in_answer.count(q.encode("utf-8")) != 1 for q in quotes), (
                f"{who}: refused, yet every quote occurs exactly once in the unit's answer text")
            continue
        assert len(spans) == len(quotes), f"{who}: stored {spans!r} for {quotes!r}"
        for span, quote in zip(spans, quotes):
            start, end = span["start"], span["end"]
            body = doc[start:end]
            assert body == quote.encode("utf-8"), (who, span, quote)
            assert verify_span(doc, span), (who, span)
            assert not any(marker in body for marker in _MARKERS), (who, span)
            assert _on_answer_text(doc, start, end), (who, span)
            assert q_start <= start and end <= q_end, (
                f"{who}: {span!r} is not in {CRITERION_QUESTIONS[criterion_id]}'s answer text "
                f"[{q_start}:{q_end}]")
            stored_spans += 1
    assert refused == _REFUSED[(run, index)]
    assert stored_spans >= 8, f"the census stored only {stored_spans} spans: it would be vacuous"


def test_tc_extract_19_the_live_offsets_are_wrong_so_the_census_exercises_relocation():
    """TC-EXTRACT-19's precondition: the live model's offsets do not address its quotes (it
    cannot count bytes), so a census that passes is not passing on offsets taken as given."""
    misplaced = total = 0
    for run in ("A", "B"):
        documents = live_documents(run)
        for replies in live_passes(run):
            for (submission_id, _criterion), reply in replies.items():
                doc = documents[submission_id].encode("utf-8")
                for span in json.loads(reply)["spans"]:
                    total += 1
                    misplaced += doc[span["start"]:span["end"]] != span["text"].encode("utf-8")
    assert total == 44 and misplaced >= 40, (total, misplaced)


# --- TC-EXTRACT-20: the model-offset path -------------------------------------------------------

def _first_line(doc: bytes, question_id: str) -> dict:
    """`{start, end, text}` over the first non-blank line of the question's answer text."""
    start, end = question_body(doc, question_id)
    body = doc[start:end]
    lead = len(body) - len(body.lstrip())
    line = body[lead:].split(b"\n", 1)[0].rstrip()
    assert line and doc.count(line) == 1, "fixture bug: the answer's first line must be unique"
    return {"start": start + lead, "end": start + lead + len(line), "text": line.decode("utf-8")}


def _five_early(span: dict) -> dict:
    return dict(span, start=span["start"] - 5, end=span["end"] - 5)


def test_tc_extract_20_five_bytes_early_inside_the_marker_is_relocated_onto_the_answer(
        tmp_data_dir, make_fixture_provider):
    """TC-EXTRACT-20, model-offset path: the reply's offsets are 5 bytes early (they start inside
    the opening marker) and its quote is right: the span is stored at the quote's bytes in Q2's
    answer, through `parse_spans` and through the real worker."""
    markdown = eng7_canonical()
    doc = markdown.encode("utf-8")
    answer = _first_line(doc, "Q2")
    early = _five_early(answer)
    assert b"-->" in doc[early["start"]:answer["start"]], (
        "precondition: the early offsets start inside the opening marker",
        doc[early["start"] - 10:answer["start"]])
    assert not _on_answer_text(doc, early["start"], early["end"])
    reply = json.dumps({"spans": [early]})
    (span,) = parse_spans(reply, doc, region=unit_region(doc, "Q2"))
    assert (span.start, span.end, span.text) == (answer["start"], answer["end"], answer["text"])

    store = open_store(tmp_data_dir)
    try:
        stored = replay_pass(store, make_fixture_provider(), {"sub-e7-001": markdown},
                             {("sub-e7-001", "C2"): reply})
    finally:
        store.close()
    assert stored[("sub-e7-001", "C2")] == [dict(answer, region_kind="transcribed_text")]


def test_tc_extract_20_the_quote_twice_in_the_answer_is_refused_never_stored_in_the_marker(
        tmp_data_dir, make_fixture_provider):
    """TC-EXTRACT-20, model-offset path: the same early reply over a document whose Q2 answer holds
    the quote twice (the real canonical document, the answer's first line repeated before the
    region's close). No unique occurrence: the reply is refused, and no evidence row is stored."""
    original = eng7_canonical().encode("utf-8")
    answer = _first_line(original, "Q2")
    _q_start, q_end = question_body(original, "Q2")
    doc = original[:q_end] + b" " + answer["text"].encode("utf-8") + original[q_end:]
    q_start, q_end = question_body(doc, "Q2")
    assert doc[q_start:q_end].count(answer["text"].encode("utf-8")) == 2
    reply = json.dumps({"spans": [_five_early(answer)]})
    with pytest.raises(ValueError, match="FR-EXTRACT-14"):
        parse_spans(reply, doc, region=unit_region(doc, "Q2"))

    store = open_store(tmp_data_dir)
    try:
        stored = replay_pass(store, make_fixture_provider(), {"sub-e7-001": doc.decode("utf-8")},
                             {("sub-e7-001", "C2"): reply})
    finally:
        store.close()
    assert stored[("sub-e7-001", "C2")] is None


@st.composite
def _replies(draw, doc: bytes):
    """One reply span over `doc`: its quote drawn from an answer text (the model quoting what it
    saw), from anywhere in the document (markup included), or invented; its offsets drawn anywhere
    in and around the document, or on the quote's true bytes."""
    text = doc.decode("utf-8")
    source = draw(st.sampled_from(["answer", "anywhere", "invented"]))
    if source == "invented":
        quote = draw(st.text(min_size=1, max_size=30))
    else:
        if source == "answer":
            low, high = draw(st.sampled_from(answer_bodies(doc)))
            low_c, high_c = len(doc[:low].decode()), len(doc[:high].decode())
        else:
            low_c, high_c = 0, len(text)
        i = draw(st.integers(low_c, max(low_c, high_c - 1)))
        j = draw(st.integers(i, min(high_c, i + 60)))
        quote = text[i:j]
    if draw(st.booleans()) and quote and quote.encode() in doc:
        start = doc.index(quote.encode()) + draw(st.integers(-8, 8))
    else:
        start = draw(st.integers(-4, len(doc) + 4))
    end = start + draw(st.integers(-2, len(quote.encode()) + 4))
    return {"start": start, "end": end, "text": quote}


@pytest.mark.property
@settings(max_examples=300, deadline=None)
@given(data=st.data(), question=st.sampled_from(["Q1", "Q2", "Q3", None]))
def test_tc_extract_20_property_every_stored_span_is_the_canonical_bytes_of_its_quote(
        data, question):
    """TC-EXTRACT-20's property, on the offset path that exists: whatever the reply, a span
    `parse_spans` returns has `canonical[start:end] == text.encode()`, its text is the quote it
    was given, and it lies on one region's answer text clear of every marker."""
    doc = eng7_canonical().encode("utf-8")
    raw = data.draw(_replies(doc))
    region = unit_region(doc, question) if question else None
    try:
        result = parse_spans(json.dumps({"spans": [raw]}), doc, region=region)
    except ValueError:
        return
    (span,) = result
    assert doc[span.start:span.end] == span.text.encode("utf-8")
    if raw["text"]:  # an empty quote is no quote: the span keeps its own offsets (#873)
        assert span.text == raw["text"], (raw, span)
    else:
        assert (span.start, span.end) == (raw["start"], raw["end"]), (raw, span)
    assert _on_answer_text(doc, span.start, span.end), (raw, span)
    assert not any(m in doc[span.start:span.end] for m in _MARKERS), (raw, span)
    if question and (span.start, span.end) != (raw["start"], raw["end"]):
        # A relocation stays inside the unit's region (its question's answer text, plus any
        # untagged region ingest attributes to the question in force, e.g. the next heading),
        # and never reaches another question's tagged answer text.
        assert any(r.start <= span.start and span.end <= r.end for r in region), (raw, span)
        for other in {"Q1", "Q2", "Q3"} - {question}:
            o_start, o_end = question_body(doc, other)
            assert span.end <= o_start or span.start >= o_end, (raw, span, other)


# --- TC-INTEG-23, the extractor arm -------------------------------------------------------------

class _RelocationSpy:
    def __init__(self, real):
        self.real = real
        self.calls: list = []

    def __call__(self, doc, span, region=None):
        self.calls.append((doc, region))
        return self.real(doc, span, region)


def _early_replies(markdown: str, criterion: str) -> dict:
    """Each ENG7 student's unit for `criterion`, answering with its question's first answer line,
    5 bytes early: every reply needs a relocation, so the spy cannot pass on zero calls."""
    doc = markdown.encode("utf-8")
    span = _first_line(doc, CRITERION_QUESTIONS[criterion])
    return json.dumps({"spans": [_five_early(span)]})


@pytest.mark.parametrize("criterion", ["C1a", "C2", "C3"])
def test_tc_integ_23_every_extractor_relocation_is_scoped_to_the_units_question(
        criterion, tmp_data_dir, make_fixture_provider, monkeypatch):
    """TC-INTEG-23, extractor arm: on every relocation from the primary AND the second-family
    pass, the region the extractor passes holds the unit's question's answer text and nothing of
    the other questions' answer text."""
    spy = _RelocationSpy(relocate_span)
    monkeypatch.setattr(spans_module, "relocate_span", spy)
    students = ("E7-001", "E7-002", "E7-003")  # E7-004 leaves answers blank
    documents = {f"sub-{name.lower()}": eng7_canonical(name) for name in students}
    replies = {(sub, criterion): _early_replies(md, criterion) for sub, md in documents.items()}
    store = open_store(tmp_data_dir)
    try:
        stored = replay_pass(store, make_fixture_provider(), documents, replies,
                             high_risk=(criterion,))
    finally:
        store.close()
    assert all(spans for spans in stored.values()), stored
    assert len(spy.calls) == 2 * len(replies), (
        f"expected one relocation per primary and per second-family pass, saw {len(spy.calls)}")
    question = CRITERION_QUESTIONS[criterion]
    for doc, region in spy.calls:
        assert region is not None
        extents = [(r.start, r.end) for r in region]
        assert question_body(doc, question) in extents, (question, extents)
        for other in {"Q1", "Q2", "Q3"} - {question}:
            o_start, o_end = question_body(doc, other)
            assert all(end <= o_start or start >= o_end for start, end in extents), (
                f"{criterion}'s region overlaps {other}'s answer text: {extents}")


_Q3_ONLY = "a little taller than before"


@pytest.mark.parametrize("scoped", [True, False], ids=["unit-scope", "scope-dropped"])
def test_tc_integ_23_sensitivity_a_q3_quote_on_a_c2_unit_needs_the_scope_to_be_refused(
        scoped, tmp_data_dir, make_fixture_provider, monkeypatch):
    """TC-INTEG-23's mutation, run as a sensitivity arm: a C2 (Q2) unit's reply quotes words that
    occur once in the document, in Q3's answer. Scoped to the unit's question it is refused; with
    the worker's question lookup dropped (a question-less scope: every answer text) the same
    reply is stored at Q3. The scope is what refuses it."""
    if not scoped:
        monkeypatch.setattr(worker_module, "unit_question_id", lambda *args: "")
    markdown = eng7_canonical()
    doc = markdown.encode("utf-8")
    occurrence = byte_span(doc, _Q3_ONLY)
    q3_start, q3_end = question_body(doc, "Q3")
    assert doc.count(_Q3_ONLY.encode()) == 1 and q3_start <= occurrence["start"] < q3_end
    reply = json.dumps({"spans": [dict(occurrence, start=occurrence["start"] - 40,
                                       end=occurrence["end"] - 40)]})
    store = open_store(tmp_data_dir)
    try:
        stored = replay_pass(store, make_fixture_provider(), {"sub-e7-001": markdown},
                             {("sub-e7-001", "C2"): reply})
    finally:
        store.close()
    if scoped:
        assert stored[("sub-e7-001", "C2")] is None
    else:
        assert stored[("sub-e7-001", "C2")] == [dict(occurrence, region_kind="transcribed_text")]
