"""`TC-SYNTH-C05` — incomplete is not failed, in stored data (§6.11.13).

`CT-SYNTH-05`'s two states, asserted so they stay distinguishable: synthesis **does
not run** for a question whose criteria are incomplete (no narrative, and — the
half the completeness gate's honesty turns on — no failure counted, because the
gate skipping is the design working, not an error); a provider failure also leaves
no narrative but records failures. The clause's inference: a consumer finding no
narrative for a question reads **the question is incomplete**, not "synthesis
failed" — and the two states must be distinguishable from stored data, since
collapsing them makes an incomplete question look like a tooling problem and vice
versa.

The stored-data differential this case pins: for the same visual state (no
narrative row for a question), the work_unit rows tell the two worlds apart —
`pending` with no verdicts (incomplete) versus `done` with verdicts (synthesis
failed). That pairing, `(unit status, narrative absence, report.failures)`, is the
projection a consumer reads; the rung-3 consumer differential (`M-GRADE` reading
the same projection) landed with `M-GRADE` (#101).

Relationship to shipped cases: `tests/integration/synth/
test_completeness_and_sentinel.py` (`TC-SYNTH-09`) holds the gate's skip (no
narrative for the incomplete question) on one store; this case adds the FAILED
world beside it and asserts the two absences are distinguishable — the differential
the clause actually names.

Isolation: rung 2 — real SQLite; the failed world's provider is the failure-injection
double the model boundary permits (`ProviderError` on every call).
"""

from __future__ import annotations

import pytest

from aeh.prov import TransportError
from aeh.store import open_store
from tests.support.impl import GRADE_MODULE, SYNTH_MODULE, require
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    COHORT_ID,
    FIVE_QUESTION_CRITERIA,
    SYNTH_ISSUE,
    WORKER,
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.contract]

_SUBMISSION = "SYN-001"
_COMPLETE = tuple(f"Q{q}" for q in range(1, 5))
_INCOMPLETE = "Q5"


class _FailingProvider:
    """The model-boundary failure double: every call raises `TransportError`, the
    transport failure `CT-SYNTH-08`'s ladder retries on."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: object, model_ref: object, params: object) -> object:
        self.calls += 1
        raise TransportError("synthesis transport down (injected)")


def _clean(question: str) -> str:
    return (
        f"Question {question[1:]}: the response states the hypothesis and cites "
        "the worked steps for this question."
    )


def _replies() -> list:
    replies = [
        narrative_completion(_clean(question), (f"{question}C1", f"{question}C2"))
        for question in _COMPLETE
    ]
    replies.append(narrative_completion("Overall: the submission works through each question in turn."))
    return replies


def _unit_status(store, run_id: str, question: str) -> str:
    rows = store.cohort(COHORT_ID).query(
        "SELECT DISTINCT status FROM work_unit WHERE run_id = :r AND "
        "submission_id = :s AND stage = 'score' AND criterion_id LIKE :q",
        r=run_id, s=_SUBMISSION, q=f"{question}C%",
    )
    return {row["status"] for row in rows}.pop() if rows else "<none>"


def _narrative_questions(store, run_id: str) -> set[str]:
    rows = store.cohort(COHORT_ID).query(
        "SELECT question_id FROM narrative WHERE run_id = :r AND submission_id = :s "
        "AND level = 'l1_question'",
        r=run_id, s=_SUBMISSION,
    )
    return {row["question_id"] for row in rows}


def test_tc_synth_c05_incomplete_and_failed_are_distinguishable_in_stored_data(
    tmp_data_dir,
):
    """`TC-SYNTH-C05` (P1) — two worlds, both with a missing narrative for at least
    one question, distinguishable from stored data alone: the incomplete world's
    missing question sits on `pending` units with the report at zero failures; the
    failed world's questions sit on `done` units with failures counted. Collapsing
    the two states is the failure the clause names."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)

    # --- world 1: Q5 incomplete (pending units, no verdicts) ------------------------
    store = open_store(tmp_data_dir / "incomplete")
    try:
        _, run_id, _ = seed_run(
            store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA
        )
        seed_scored_submission(
            store, run_id, _SUBMISSION,
            complete_questions=set(_COMPLETE),
        )
        provider = CaptureProvider(_replies())
        report = Worker(store, provider, synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )

        assert _narrative_questions(store, run_id) == set(_COMPLETE), (
            "the incomplete question must have no narrative — synthesis does not "
            "run for it (FR-SYNTH-06), so no narrative describes a partial result "
            "as though it were whole"
        )
        assert report.failures == 0, (
            f"{report.failures} failures recorded for the incomplete world — the "
            "gate's skip is the design working, and counting it as a failure makes "
            "an incomplete question look like a tooling problem (CT-SYNTH-05)"
        )
        assert report.synthesis_failure_rate == 0.0
        assert _unit_status(store, run_id, _INCOMPLETE) == "pending", (
            "the incomplete question's score units must still read `pending` — that "
            "is the stored surface the 'no narrative' inference reads"
        )
        assert _unit_status(store, run_id, "Q1") == "done"
        incomplete_world = {
            "narratives": _narrative_questions(store, run_id),
            "failures": report.failures,
            "q5_unit_status": _unit_status(store, run_id, _INCOMPLETE),
            "q1_unit_status": _unit_status(store, run_id, "Q1"),
        }
    finally:
        store.close()

    # --- world 2: everything judged, synthesis fails on every question --------------
    store = open_store(tmp_data_dir / "failed")
    try:
        _, run_id, _ = seed_run(
            store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA
        )
        seed_scored_submission(store, run_id, _SUBMISSION, complete_questions=set(_COMPLETE))
        failing = _FailingProvider()
        report = Worker(store, failing, synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )

        assert _narrative_questions(store, run_id) == set(), (
            "the failed world stored narrative rows — a provider failure leaves no "
            "narrative (CT-SYNTH-08); rows here would make the two worlds "
            "indistinguishable the other way"
        )
        assert report.failures > 0, (
            f"{report.failures} failures in the failed world — a provider outage "
            "must be VISIBLE in the report's failure count, or the operator cannot "
            "tell a failed synthesis from an incomplete question (CT-SYNTH-05)"
        )
        assert failing.calls > 0, (
            "precondition: the failing provider was never called — the failed world "
            "was not exercised"
        )
        for question in _COMPLETE:
            assert _unit_status(store, run_id, question) == "done", (
                f"{question}'s units must read `done` in the failed world — the "
                "unit status is the other half of the differential"
            )
        failed_world = {
            "narratives": _narrative_questions(store, run_id),
            "failures": report.failures,
            "q5_unit_status": _unit_status(store, run_id, _INCOMPLETE),
            "q1_unit_status": _unit_status(store, run_id, "Q1"),
        }

        # The differential itself: the same observable absence (no narrative for a
        # question) over different stored states — distinguishable from data alone.
        assert incomplete_world["narratives"] != failed_world["narratives"], (
            "the two worlds must differ in which questions hold narratives, or the "
            "differential below is vacuous"
        )
        assert incomplete_world["failures"] == 0 < failed_world["failures"], (
            "the failure counts must separate the worlds: gate-skip 0, outage > 0 "
            "(CT-SYNTH-05's 'the two states are distinguishable')"
        )
        assert incomplete_world["q5_unit_status"] == "pending", (
            "in the incomplete world the missing narrative's units are pending; "
            "in the failed world the missing narratives sit on done units — a "
            "consumer reading no narrative for a `pending` question infers "
            "incompleteness, never a synthesis outage"
        )
        assert failed_world["q1_unit_status"] == "done", (
            "in the failed world the missing narrative's question is DONE — the "
            "same 'no narrative' finding means the opposite thing at `done` units"
        )
    finally:
        store.close()


def test_tc_synth_c05_the_consumer_reads_incompleteness_not_failure(tmp_data_dir):
    """`TC-SYNTH-C05` (P1, rung 3 consumer differential) — `M-GRADE` reads the stored
    projection the green half pins: a question with no narrative and `pending` units
    is INCOMPLETE (its grade state says so). Collapsing the two states — an
    incomplete question surfaced as a synthesis outage, or an outage withheld as
    incompleteness — turns this red. (The failed world's consumer leg — the outage
    still computing and finalizing — is `TC-SYNTH-C08`'s consumer test, not this
    one's; this test drives only the incomplete world.)

    Landed with `M-GRADE` (#101): `coverage(run_id)` reads the class's states as
    they stand — a submission with no current grade row and missing criteria
    counts `incomplete` (`CT-GRADE-08`'s biconditional read from the stored side).
    The surface is `GradingService.coverage(run_id) -> CoverageSummary` with
    `.grades_by_state` (disclosed in `tests/support/grade_vocabulary.py`).
    """
    open_grade = require(GRADE_MODULE, "open_grade", issue="#101")
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)

    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(
            store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA
        )
        seed_scored_submission(
            store, run_id, _SUBMISSION, complete_questions=set(_COMPLETE)
        )
        Worker(store, CaptureProvider(_replies()), synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )

        service = open_grade(store)
        coverage = service.coverage(run_id)
        incomplete = coverage.grades_by_state.get("incomplete", 0)
        assert incomplete >= 1, (
            f"coverage reports {coverage.grades_by_state} with no incomplete state — "
            "the consumer collapsed the two worlds: a question with no narrative on "
            "pending units is incomplete, not missing-without-cause (CT-SYNTH-05)"
        )
    finally:
        store.close()
