"""`TC-SYNTH-C09` — the call budget is bounded, and off the grade's critical path (§6.11.13).

`CT-SYNTH-09`'s perf clause, the two halves that are assertable without a 350-student
load:

- **Bounded** — every synthesis call's sampling parameters carry
  `max_tokens=SYNTH_MAX_OUTPUT_TOKENS` (512) at temperature 0.0, the call budget
  `NFR-SYNTH-02` bounds; the env knob `HARNESS_SYNTH_MAX_OUTPUT_TOKENS` overrides at
  call time (the third seam), and the constructor's `max_output_tokens` wins over
  both — the knob exists so a slower test box can adjust without a code change, and
  the case proves the override is read at call time, not frozen at import.
- **The load arithmetic the threshold is derived from**: ~2,100 calls per
  350-student run across L1 and L2 is 6 calls per submission (5 L1 + 1 L2) — the
  case re-derives the per-submission shape on a real 5-question drive and asserts
  the multiplication the threshold states. Roughly 9% of model calls is the
  panel's comparison figure, not an assertion this case can make without the
  cohort's other stages.

The critical-path half (grades finalize while synthesis is still outstanding) is
written ahead of `M-GRADE` and registered in `WRITTEN_AHEAD_BLOCKERS` under
`"#100 grade consumers (C05/C08/C09)"`.

Relationship to shipped cases: `tests/integration/synth/
test_synthesis_observability.py` (`TC-SYNTH-12`) pins `model_calls == 6` on the
clean shape; this case re-derives that arithmetic as the THRESHOLD's derivation
(the clause's number, not the report's) and adds the parameter bound the sibling
does not read.

Isolation: rung 2 — real SQLite; a params-capturing `CaptureProvider` subclass at
the model boundary (the only double).
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.grade_vocabulary import write_criterion_scores
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
_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))
_TOKENS_ENV = "HARNESS_SYNTH_MAX_OUTPUT_TOKENS"


class _ParamsCapture(CaptureProvider):
    """The capture provider with the sampling parameters recorded — the bound is a
    claim about the params, which the base double does not retain."""

    def __init__(self, replies: list) -> None:
        super().__init__(replies)
        self.params: list[object] = []

    def complete(self, prompt: object, model_ref: object, params: object) -> object:
        self.params.append(params)
        return super().complete(prompt, model_ref, params)


def _clean_reply(question: str):
    return narrative_completion(
        f"Question {question[1:]}: the response states the hypothesis and cites "
        "the worked steps for this question.",
        (f"{question}C1", f"{question}C2"),
    )


def _replies() -> list:
    replies = [_clean_reply(q) for q in _QUESTIONS]
    replies.append(narrative_completion("Overall: the submission works through each question in turn."))
    return replies


def _seeded_store(tmp_data_dir, submissions=(_SUBMISSION,)):
    """One run over all named submissions (`seed_run` seeds its cohort once per
    store, so the second submission rides the same run), each scored — the runs map
    gives the drive a per-submission handle."""
    store = open_store(tmp_data_dir)
    _, run_id, _ = seed_run(
        store, submissions=submissions, criteria=FIVE_QUESTION_CRITERIA
    )
    for submission_id in submissions:
        seeded = seed_scored_submission(
            store, run_id, submission_id, complete_questions=set(_QUESTIONS)
        )
        # The grade legs read M-AGG's stored output, not the verdicts this fixture
        # seeds (CT-GRADE-14: the grade never touches the verdict table), and the
        # critical-path premise is that aggregation's scores survive a synthesis
        # outage — so the grade vocabulary's disclosed stand-in
        # (`write_criterion_scores`) states the rows aggregation would have
        # written: one auto row per criterion, at the panel's band.
        write_criterion_scores(
            store.cohort(COHORT_ID),
            [
                (submission_id, criterion_id, "high", 6.0, "auto")
                for criteria in seeded.values()
                for criterion_id in criteria
            ],
        )
    runs = {submission_id: run_id for submission_id in submissions}
    return store, runs


def test_tc_synth_c09_every_call_is_bounded_by_the_output_cap(tmp_data_dir, monkeypatch):
    """`TC-SYNTH-C09` (P1) — every synthesis call ships `max_tokens` at the
    production default (512), the env knob overrides at call time, and the
    constructor's explicit cap wins over the env: the bound is real on the wire,
    not a constant next to the call."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    production_cap = require(
        SYNTH_MODULE, "SYNTH_MAX_OUTPUT_TOKENS", issue=SYNTH_ISSUE
    )

    store, runs = _seeded_store(
        tmp_data_dir, submissions=("SYN-001", "SYN-002", "SYN-003")
    )
    try:
        provider = _ParamsCapture(_replies())
        Worker(store, provider, synth_ref()).synthesize_submission(
            runs["SYN-001"], _SUBMISSION
        )
        assert provider.params and len(provider.params) == 6, (
            f"{len(provider.params)} calls captured — the parameter claims below "
            "need the full two-level drive"
        )
        for call, params in enumerate(provider.params, start=1):
            assert params.max_tokens == production_cap, (
                f"call {call} shipped max_tokens={params.max_tokens!r} — the call "
                "budget is bounded by SYNTH_MAX_OUTPUT_TOKENS (CT-SYNTH-09); an "
                "unbounded narrative reply is the cost and latency leak the cap "
                "exists to prevent"
            )
            assert params.temperature == 0.0, (
                "synthesis runs at temperature 0.0 — the reproducible-prose "
                "non-promise (CT-SYNTH-14) is read at this setting"
            )

        # The knob overrides at call time — a fresh submission's drive, since the
        # first submission's narratives would absorb at the read and never call.
        monkeypatch.setenv(_TOKENS_ENV, "64")
        overridden = _ParamsCapture(_replies())
        Worker(store, overridden, synth_ref()).synthesize_submission(
            runs["SYN-002"], "SYN-002"
        )
        assert overridden.params, (
            "the second drive made no call — the knob claim needs a fresh "
            "submission to compose"
        )
        for params in overridden.params:
            assert params.max_tokens == 64, (
                f"the knob drive shipped max_tokens={params.max_tokens!r} — "
                "HARNESS_SYNTH_MAX_OUTPUT_TOKENS must override the production "
                "default at call time (the third seam)"
            )

        # The constructor's explicit cap wins over BOTH the default and the knob —
        # the caller that names a cap gets that cap.
        constructed = _ParamsCapture(_replies())
        Worker(store, constructed, synth_ref(), max_output_tokens=32).synthesize_submission(
            runs["SYN-003"], "SYN-003"
        )
        assert constructed.params, (
            "the constructor drive made no call — the cap- precedence claim needs "
            "a fresh submission to compose"
        )
        assert all(params.max_tokens == 32 for params in constructed.params), (
            f"the constructor-capped drive shipped "
            f"{[params.max_tokens for params in constructed.params]} with the knob "
            "at 64 — an explicit constructor max_output_tokens must win over both "
            "the production default and the env knob (CT-SYNTH-09), or the knob's "
            "override is not a seam but a trap"
        )
    finally:
        store.close()


def test_tc_synth_c09_the_call_arithmetic_matches_the_stated_load(tmp_data_dir):
    """`TC-SYNTH-C09` (P1) — the threshold's derivation, on a real drive: 5 complete
    questions → exactly 5 L1 calls + 1 L2 call, and 350 × 6 = 2,100, the load the
    clause states. The level split is read off the captured prompts."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    level_l1, level_l2 = require(
        SYNTH_MODULE, "LEVEL_L1", "LEVEL_L2", issue=SYNTH_ISSUE
    )

    store, runs = _seeded_store(tmp_data_dir)
    try:
        provider = _ParamsCapture(_replies())
        report = Worker(store, provider, synth_ref()).synthesize_submission(
            runs[_SUBMISSION], _SUBMISSION
        )
        assert report.model_calls == 6 == len(provider.params), (
            f"{report.model_calls} reported / {len(provider.params)} observed — the "
            "per-submission call count the threshold is built from is exact"
        )
        levels = [dict(p.fields).get("level") for p in provider.prompts]
        assert levels.count(level_l1) == 5 and levels.count(level_l2) == 1, (
            f"{levels} — the load is 5 L1 + 1 L2 per submission; a second L2 call "
            "or a missing question breaks the 2,100-per-350 arithmetic"
        )
        per_run = 350 * (levels.count(level_l1) + levels.count(level_l2))
        assert per_run == 2100, (
            f"{per_run} calls per 350-student run — the clause's stated load is "
            "~2,100 across L1 and L2; the arithmetic must still hold after any "
            "change to the per-submission shape"
        )
    finally:
        store.close()


def test_tc_synth_c09_grades_finalize_while_synthesis_is_outstanding(tmp_data_dir):
    """`TC-SYNTH-C09` (P1, rung 3 critical-path assertion) — grades finalize while
    synthesis is still outstanding: the scored units are all done, no narrative
    exists, and `M-GRADE` finalizes anyway. This is the assertion that stays true
    only if nobody makes finalization wait for narratives.

    Landed with `M-GRADE` (#101): finalization is the shipped
    `GradingService.finalize_batch(run_id, actor) -> FinalizationRecord`.
    """
    open_grade = require(GRADE_MODULE, "open_grade", issue="#101")

    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(
            store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA
        )
        # Scored and judged — and synthesis deliberately never runs: the narratives
        # are outstanding, which is the scheduling state consumers plan against.
        # The grade reads M-AGG's stored output (CT-GRADE-14), and the premise is
        # that aggregation's scores survive the outstanding synthesis — so the
        # disclosed `write_criterion_scores` stand-in states those rows.
        seeded = seed_scored_submission(
            store, run_id, _SUBMISSION, complete_questions=set(_QUESTIONS)
        )
        write_criterion_scores(
            store.cohort(COHORT_ID),
            [
                (_SUBMISSION, criterion_id, "high", 6.0, "auto")
                for criteria in seeded.values()
                for criterion_id in criteria
            ],
        )
        rows = store.cohort("c-2026-7B-orch").query(
            "SELECT COUNT(*) AS n FROM narrative WHERE run_id = :r", r=run_id
        )
        assert rows[0]["n"] == 0, (
            "precondition: synthesis never ran — the grades below must finalize "
            "against an empty narrative table"
        )

        service = open_grade(store)
        service.compute_all(run_id)
        record = service.finalize_batch(run_id, actor="c09-test")
        assert record.finalized >= 1, (
            f"finalization finalized {record.finalized} grades while synthesis was "
            "outstanding — synthesis is OFF the critical path for grade delivery "
            "(CT-SYNTH-09): if finalization waited for narratives, every delivery "
            "would wait on the slowest stage in the system"
        )
    finally:
        store.close()
