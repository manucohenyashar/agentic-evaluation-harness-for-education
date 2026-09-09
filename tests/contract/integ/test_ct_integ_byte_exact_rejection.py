"""`CT-INTEG-06` — a byte-inexact or out-of-bounds span is **discarded**, the
unit retried, and nothing scores on a span this module rejected
(`TC-INTEG-C06`).

Case of test plan §6.11.9; TS-66 (issue #77). Written ahead of `#73` (the
`verify_span` half) and `#74` (the gate/routing half).

The clause has three moving parts, and the case keeps each under its own
limb. The rejection families are the clause's own two: quoted text that does
not match the source **bytes** exactly, and offsets that fall outside the
canonical Markdown — asserted against `verify_span` at rung 0, with the
mid-codepoint slicing bait included because a codepoint-slicing or clamping
implementation *repairs* the span instead of rejecting it. The discard is the
gate limb: a rejected span leaves no `done` extract unit, no evidence row, and
a re-extraction request whose attempts grew; repeated failure ends in
`quarantined`, never in scoring. The safety property — **nothing scores on a
span this module rejected** — is the checker below, and it has executable
teeth now: a repairing gate (truncate the text until it matches, clamp the
offsets into bounds) or a scoring-anyway gate goes red on it before `#73`
lands a single line.

The retry/quarantine **ladder's** full state machine is `TC-INTEG-02`'s
integration suite (`tests/integration/integ/test_integ_retry_and_quarantine.py`,
the #75 vocabulary: pending-with-grown-attempts, `quarantined`, no pending
past the ceiling); this case pins the clause, not the ladder — it reuses that
suite's ledger oracle so the two cannot drift.

**Disclosures register** (nothing new is minted beyond the #75 table):

| Name | Status |
|---|---|
| rejection families | the clause's two (`text mismatch`, `out of bounds`) plus the mid-codepoint slicing bait — the exhaustive boundary set is `TC-INTEG-C01`'s table and is not duplicated here |
| partial rejection | one accepted span alongside a rejected one: the case pins `spans_verified=False` and the retry (the unit's extraction is suspect — the extractor hallucinated once), and deliberately does NOT pin `evidence_present` (the clause says the span is discarded, not what remains); flagged for #74's reconcile |
| ladder shape | `RETRY_LIMIT` = 3 (FR-EXTRACT-08, as the #75 suite declares it); the quarantine statuses and attempt counts are the ledger's, read exactly as the #75 file reads them |
| checker | test-side oracle over (signals, ledger state); the mutants are `SimpleNamespace`/in-memory shapes, not implementations, so the teeth run at rung 0 |
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    Doc,
    ExtractionView,
    PanelFlags,
    Span,
    document_id_for,
    seed_document,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run
from tests.support.span_strategies import expected_verify

pytestmark = pytest.mark.contract

_SUBMISSION = "SUB-C06"
_CRITERION = "C1"
_SUBMISSIONS = (_SUBMISSION,)
_CRITERIA = ({"criterion_id": _CRITERION, "kind": "open", "scoring_model": "holistic"},)
_MARKDOWN = "The student argues the thesis directly in the opening paragraph.\n"

#: FR-EXTRACT-08's ladder, as the #75 suite declares it: three failures quarantine.
RETRY_LIMIT = 3


def _doc() -> Doc:
    return Doc(markdown=_MARKDOWN)


def _good_span(doc: Doc) -> Span:
    start = doc.markdown.encode("utf-8").find(b"thesis")
    return Span(start, start + len("thesis"), "thesis")


# --- limb 1: the clause's two rejection families, at rung 0 ---------------------------------


def _rejection_cases() -> list[tuple[str, Span]]:
    """The clause's two families on one document. Byte anatomy: ASCII-only, so
    byte and codepoint offsets coincide here — the bait below is what a
    clamping or repairing implementation accepts, not a multibyte trap (that
    one is C01's)."""
    doc = _doc()
    n = len(doc.markdown.encode("utf-8"))
    start = doc.markdown.index("thesis")
    end = start + len("thesis")
    return [
        # text mismatch, same offsets, same length: one character swapped
        ("quoted text does not match the source bytes",
         Span(start, end, "theses")),
        # offsets fall outside the canonical Markdown: end past the document
        ("end offset falls outside the canonical Markdown", Span(n - 2, n + 1, ".\n")),
        # offsets fall outside: start before the document
        ("start offset falls outside the canonical Markdown", Span(-1, 3, "The")),
        # the repair bait: clamping the end to n yields exactly ".\n" — a repairing
        # implementation accepts what the clause rejects
        ("out-of-bounds end clamps to a matching slice", Span(n - 2, n + 1, ".\n")),
    ]


@pytest.mark.writtenahead
@pytest.mark.parametrize("name, span",
                         _rejection_cases(),
                         ids=[name for name, _ in _rejection_cases()])
def test_tc_integ_c06_every_rejection_family_verifies_false(name, span):
    """`TC-INTEG-C06` — each family the clause names verifies False, and the
    shared byte-exact invariant agrees: no repair, no truncation, no clamping."""
    verify_span = require(INTEG_MODULE, "verify_span", issue="#73")
    doc = _doc()
    verdict = verify_span(doc, span)
    assert verdict is False, (
        f"{name}: verify_span returned {verdict!r} — the clause requires the span "
        "REJECTED, not repaired into a matching one (CT-INTEG-06)"
    )
    assert verdict is expected_verify(doc, span), (
        f"{name}: the clause verdict and the shared byte-exact invariant disagree"
    )


# --- the checker: nothing scores on a span this module rejected ------------------------------


def _assert_rejected_span_never_scores(signals, *, retries, quarantined,
                                       score_rows) -> None:
    """The safety-property oracle: a rejected span (a) did not verify, (b) left
    a route — a retry or the quarantine, not silence — and (c) produced no
    score. `retries`/`quarantined`/`score_rows` are the ledger's reads."""
    assert signals.spans_verified is False, (
        "a span this module rejected came out spans_verified — a repairing gate "
        "(truncated text, clamped offsets) presenting a rejection as a verification"
    )
    assert retries or quarantined, (
        "a rejected span routed nowhere — no re-extraction request and no quarantine; "
        "the unit proceeded on evidence the module rejected (FR-INTEG-02)"
    )
    assert not score_rows, (
        "a criterion_score row exists for a span this module rejected — nothing "
        "scores on unverified evidence, the clause's final sentence (CT-INTEG-06)"
    )


def test_tc_integ_c06_the_no_scoring_oracle_has_teeth():
    """`TC-INTEG-C06`'s executable construction — the oracle goes red on the
    repairing gate, the silent gate, and the scoring-anyway gate, and accepts
    the faithful outcome. Runs green now: it asserts the oracle's teeth, not
    the implementation."""
    from types import SimpleNamespace

    faithful = SimpleNamespace(spans_verified=False, evidence_present=False,
                               sufficiency_flag=False, ocr_overlap_risk=False,
                               described_evidence=False, extractor_disagreement=None)
    _assert_rejected_span_never_scores(
        faithful, retries=[{"work_id": "w", "attempts": 1}], quarantined=[],
        score_rows=[])

    repaired = SimpleNamespace(spans_verified=True, evidence_present=True,
                               sufficiency_flag=False, ocr_overlap_risk=False,
                               described_evidence=False, extractor_disagreement=None)
    with pytest.raises(AssertionError, match="repairing gate"):
        _assert_rejected_span_never_scores(
            repaired, retries=[], quarantined=[], score_rows=[])

    with pytest.raises(AssertionError, match="routed nowhere"):
        _assert_rejected_span_never_scores(
            faithful, retries=[], quarantined=[], score_rows=[])

    with pytest.raises(AssertionError, match="nothing\\s+scores|criterion_score row"):
        _assert_rejected_span_never_scores(
            faithful, retries=[{"work_id": "w", "attempts": 1}], quarantined=[],
            score_rows=[{"criterion_id": _CRITERION, "band": "B0"}])


# --- limb 2: the discard and the ladder, over the real ledger --------------------------------


def _units(handle, run_id: str, stage: str) -> list[dict]:
    return handle.query(
        "SELECT work_id, status, attempts FROM work_unit WHERE run_id = :r AND "
        "submission_id = :s AND criterion_id = :c AND stage = :st ORDER BY work_id",
        r=run_id, s=_SUBMISSION, c=_CRITERION, st=stage,
    )


def _evidence_rows(handle, run_id: str) -> list[dict]:
    return handle.query(
        "SELECT * FROM evidence WHERE work_id IN (SELECT work_id FROM work_unit "
        "WHERE run_id = :r AND submission_id = :s AND criterion_id = :c)",
        r=run_id, s=_SUBMISSION, c=_CRITERION,
    )


def _score_rows(handle, run_id: str) -> list[dict]:
    return handle.query(
        "SELECT * FROM criterion_score WHERE submission_id = :s AND criterion_id = :c",
        s=_SUBMISSION, c=_CRITERION,
    )


def _scenario(tmp_data_dir, spans) -> tuple:
    """A real run, the document, and a view whose span payload carries the
    rejection family under test (the #75 scenario shape, contract cohort)."""
    from tests.contract.integ._doubles import OCR_FLOOR

    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(store, submissions=_SUBMISSIONS,
                                      criteria=_CRITERIA)
    handle = store.cohort(ORCH_COHORT_ID)
    doc = _doc()
    seed_document(handle, document_id_for(_SUBMISSION), _SUBMISSION, doc.markdown,
                  ORCH_COHORT_ID)
    orch.enumerate_units(run_id)
    payload: list[Span] = list(spans)
    view = ExtractionView(spans=payload, panel=PanelFlags((True, True, True)))
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    gate = IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=OCR_FLOOR)
    return store, handle, run_id, doc, payload, gate


@pytest.mark.writtenahead
def test_tc_integ_c06_a_rejected_span_is_discarded_and_the_unit_retried(tmp_data_dir):
    """`TC-INTEG-C06` — the hallucinated span goes through the gate: it did not
    verify, it left no `done` extract unit and no evidence row behind, and the
    ledger carries a re-extraction request whose attempts grew — the discard is
    a state, not a log line."""
    store, handle, run_id, doc, payload, gate = _scenario(
        tmp_data_dir, [Span(0, 6, "quorum")])
    signals = gate.verify(run_id, _SUBMISSION, _CRITERION)
    extracted = _units(handle, run_id, "extract")
    _assert_rejected_span_never_scores(
        signals,
        retries=[u for u in extracted if u["status"] == "pending"
                 and u["attempts"] >= 1],
        quarantined=[u for u in extracted if u["status"] == "quarantined"],
        score_rows=_score_rows(handle, run_id),
    )
    assert not [u for u in extracted if u["status"] == "done"], (
        "a completed extract unit survives a failed verification — the span was "
        "discarded, and with it the unit's claim to be done"
    )
    assert not _evidence_rows(handle, run_id), (
        "evidence rows survive the discard — the rejected span persisted as evidence"
    )
    store.close()


@pytest.mark.writtenahead
def test_tc_integ_c06_repeated_rejection_quarantines_and_nothing_scores(tmp_data_dir):
    """`TC-INTEG-C06` — the ladder's ceiling: `RETRY_LIMIT` rejections end in
    `quarantined` with no live retry left and no score unit completed —
    proceeding to scoring on unverified evidence is the outcome the clause
    exists to make impossible."""
    store, handle, run_id, doc, payload, gate = _scenario(
        tmp_data_dir, [Span(0, 6, "quorum")])
    for _attempt in range(RETRY_LIMIT):
        gate.verify(run_id, _SUBMISSION, _CRITERION)
    extracted = _units(handle, run_id, "extract")
    assert [u for u in extracted if u["status"] == "quarantined"], (
        f"{RETRY_LIMIT} verification failures left statuses "
        f"{[u['status'] for u in extracted]} — the repeated failure must quarantine"
    )
    assert not [u for u in extracted if u["status"] == "pending"], (
        "a quarantined criterion still has a live re-extraction request — the ladder "
        "stops at the quarantine, it does not loop"
    )
    assert not _score_rows(handle, run_id), (
        "a score row was written for a criterion whose extraction never verified"
    )
    done_scores = handle.query(
        "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :r AND submission_id = :s "
        "AND criterion_id = :c AND stage = 'score' AND status = 'done'",
        r=run_id, s=_SUBMISSION, c=_CRITERION,
    )
    assert done_scores[0]["n"] == 0, (
        "score units completed for a criterion whose extraction never verified — "
        "nothing scores on a span this module rejected (CT-INTEG-06)"
    )
    store.close()


@pytest.mark.writtenahead
def test_tc_integ_c06_one_rejected_span_retries_the_whole_unit(tmp_data_dir):
    """`TC-INTEG-C06` — partial rejection: a verified span alongside a
    hallucinated one. The unit still retries (the extractor hallucinated once;
    its other output is suspect) and `spans_verified` is False. Deliberately
    unpinned, disclosed: `evidence_present` — the clause discards the span, and
    says nothing about what remains; #74's landing reconciles."""
    store, handle, run_id, doc, payload, gate = _scenario(
        tmp_data_dir, [Span(0, 6, "quorum")])
    payload.append(_good_span(doc))
    signals = gate.verify(run_id, _SUBMISSION, _CRITERION)
    assert signals.spans_verified is False, (
        "one hallucinated span among verified ones came out spans_verified — the "
        "unit's extraction did not verify, whatever remains"
    )
    extracted = _units(handle, run_id, "extract")
    assert [u for u in extracted if u["status"] == "pending" and u["attempts"] >= 1], (
        "a rejected span among accepted ones routed nothing — the clause retries the "
        "unit, not just the span"
    )
    assert not _score_rows(handle, run_id), (
        "a score row was written on a unit containing a rejected span"
    )
    store.close()
