"""`TC-SYNTH-C08` — exact attempt budgets, and nothing here fails a grade (§6.11.13).

`CT-SYNTH-08`'s error clause at rung 2: transport and parse failures retry, a
score-claiming narrative is re-requested **once** then flagged — with **exact
attempt counts**, not "retries" — and the clause's most consequential sentence
asserted directly: **nothing here fails a grade**. A synthesis outage that withheld
grades would trip RISK-11, where the system stops being the thing it is for.

The exact-count halves this case holds (the shipped siblings hold the ladder's
stored state, not the budgets):

- transport: `HARNESS_SYNTH_MAX_ATTEMPTS=3`, a provider that fails twice then
  answers → the narrative stores on attempt 3, the whole run is 7 calls, zero
  failures — the strike budget is per narrative, shared by both failure classes.
- parse: a non-JSON reply burns one strike exactly like a transport failure (the
  same budget line in `_call`), and the case pins the equality.
- exhaustion: a question that fails its whole budget is isolated — `failures == 1`,
  the other questions and the L2 still compose, and the failed question is the only
  count in the rate.

The grade-completion half (total synthesis failure, `M-GRADE` still computes and
finalizes) landed with `M-GRADE` (#101): `open_grade` ships, and the batch
finalizes through the outage.

Isolation: rung 2 — real SQLite; the flaky and failing providers are the
failure-injection doubles the model boundary permits.
"""

from __future__ import annotations

import pytest

from aeh.prov import TransportError
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
_BUDGET = 3  # HARNESS_SYNTH_MAX_ATTEMPTS for every test in this file

_ATTEMPT_BUDGET = "HARNESS_SYNTH_MAX_ATTEMPTS"


def _clean(question: str) -> str:
    return (
        f"Question {question[1:]}: the response states the hypothesis and cites "
        "the worked steps for this question."
    )


def _clean_reply(question: str):
    return narrative_completion(_clean(question), (f"{question}C1", f"{question}C2"))


def _unparsable_reply() -> object:
    """A Completion whose text is NOT the JSON envelope the parser reads — the model
    answered with bare prose, which is exactly what a parse strike is for (`#97`'s
    reply contract: a non-JSON `text` raises `ValueError` in `parse_narrative`)."""
    from decimal import Decimal

    from aeh.prov import Completion

    return Completion(
        text="this is not json at all",
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
        resolved_build="synth-build-ts37",
        cached_prefix_tokens=0,
        cost=Decimal("0"),
    )


class _FlakyProvider:
    """A transport that fails the first `fail_first` calls with `TransportError`,
    then serves the canned replies in order — the strike budget's discriminator.

    A provider that failed per-question (rather than per-call) could not
    distinguish a shared budget from a per-narrative one; call counting is what
    makes the exact-count assertion bite."""

    def __init__(self, fail_first: int, replies: list) -> None:
        self._fail_first = fail_first
        self._replies = list(replies)
        self.calls = 0

    def complete(self, prompt: object, model_ref: object, params: object) -> object:
        self.calls += 1
        if self.calls <= self._fail_first:
            raise TransportError(f"injected transport failure #{self.calls}")
        if not self._replies:
            raise AssertionError(
                "FlakyProvider ran dry: more model calls than the fixture canned — "
                "disclose the extra call, do not paper over it"
            )
        return self._replies.pop(0)


class _AlwaysFailingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: object, model_ref: object, params: object) -> object:
        self.calls += 1
        raise TransportError("synthesis transport down (injected)")


def _seeded_store(tmp_data_dir, *, complete=_QUESTIONS):
    store = open_store(tmp_data_dir)
    _, run_id, _ = seed_run(store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA)
    seeded = seed_scored_submission(
        store, run_id, _SUBMISSION, complete_questions=set(complete)
    )
    # The grade legs read M-AGG's stored output, not the verdicts this fixture
    # seeds (CT-GRADE-14: the grade never touches the verdict table). Aggregation
    # is the fixture's upstream premise — a synthesis outage leaves in place the
    # scores aggregation already wrote — so the declared stand-in
    # (`write_criterion_scores`, the grade vocabulary's disclosed seeding helper,
    # the one this file's c08 docstring names) states the rows aggregation would
    # have written: one auto row per criterion of a complete question, at the
    # panel's band. An incomplete question keeps its absence — the criteria_missing
    # the grade reads, never a zero.
    write_criterion_scores(
        store.cohort(COHORT_ID),
        [
            (_SUBMISSION, criterion_id, "high", 6.0, "auto")
            for question, criteria in seeded.items()
            if question in complete
            for criterion_id in criteria
        ],
    )
    return store, run_id


def test_tc_synth_c08_transport_failures_retry_within_the_exact_budget(
    tmp_data_dir, monkeypatch
):
    """`TC-SYNTH-C08` (P0) — two injected transport failures on the first question's
    call, budget 3: the narrative stores on the third attempt and the run's call
    count is exact — 2 (failed attempts) + 6 (the five first-try questions plus Q1's
    third attempt) + ... = 2 + 5 L1 + 1 L2 = 8 — with zero failures. A budget that
    silently retried twice or gave up after one strike changes this count."""
    monkeypatch.setenv(_ATTEMPT_BUDGET, str(_BUDGET))
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    store, run_id = _seeded_store(tmp_data_dir)
    try:
        replies = [_clean_reply(q) for q in _QUESTIONS]
        replies.append(narrative_completion("Overall: the submission works through each question in turn."))
        provider = _FlakyProvider(fail_first=2, replies=replies)
        report = Worker(store, provider, synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )
        assert provider.calls == 8, (
            f"{provider.calls} provider calls — the exact arithmetic is 2 injected "
            "failures + Q1's third attempt + the other 4 questions + 1 L2 = 8; a "
            "different count means the retry budget is not per-narrative or the "
            "failure did not retry"
        )
        assert report.model_calls == 8, (
            "the report's model_calls must equal the provider's actual calls — the "
            "counter is the fourth seam's surface and drifts from the truth at "
            "everyone's peril"
        )
        assert report.failures == 0, (
            f"{report.failures} failures — the narrative stored on the third "
            "attempt, so nothing failed"
        )
        stored = [
            dict(row)
            for row in store.cohort(COHORT_ID).query(
                "SELECT question_id, text FROM narrative WHERE run_id = :r AND "
                "level = 'l1_question'",
                r=run_id,
            )
        ]
        q1 = [row for row in stored if row["question_id"] == "Q1"]
        assert len(q1) == 1 and _clean("Q1") in q1[0]["text"], (
            "the retried question must hold exactly its third-attempt narrative — "
            "one row, the clean replacement, no duplicate per attempt"
        )
    finally:
        store.close()


def test_tc_synth_c08_parse_failures_share_the_transport_budget(
    tmp_data_dir, monkeypatch
):
    """`TC-SYNTH-C08` (P0) — a reply that is not JSON is the same class of strike as
    a transport failure: one budget, both failure modes. The first question's first
    reply is garbage, its second is clean; the run is 7 calls and the narrative
    stores."""
    monkeypatch.setenv(_ATTEMPT_BUDGET, str(_BUDGET))
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    store, run_id = _seeded_store(tmp_data_dir)
    try:
        # The parse strike must be a reply the parser cannot read — a Completion
        # whose text is bare prose, not a well-formed envelope with odd prose in it.
        replies = [_unparsable_reply()] + [_clean_reply(q) for q in _QUESTIONS]
        replies.append(narrative_completion("Overall: the submission works through each question in turn."))
        provider = _FlakyProvider(fail_first=0, replies=replies)
        # _FlakyProvider serves replies in order; a parse failure CONSUMES a reply
        # (the model answered) but not a canned slot beyond it, so the feed below
        # is exact: Q1 gets the garbage Completion then its clean reply, the rest
        # get theirs, and the L2 closes the run.
        report = Worker(store, provider, synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )
        assert provider.calls == 7, (
            f"{provider.calls} calls — 2 for Q1 (one parse strike, one clean) + 4 "
            "other questions + 1 L2 = 7; a parse failure must strike the same "
            "budget as a transport failure, not a separate one"
        )
        assert report.model_calls == 7, (
            "the report's counter must include the parse strike like any other call"
        )
        assert report.failures == 0
        stored = [
            dict(row)
            for row in store.cohort(COHORT_ID).query(
                "SELECT text FROM narrative WHERE run_id = :r AND level = "
                "'l1_question' AND question_id = 'Q1'",
                r=run_id,
            )
        ]
        assert len(stored) == 1 and "not json" not in stored[0]["text"], (
            "the unparsable reply must not store — the strike is consumed and the "
            "clean replacement is the row"
        )
    finally:
        store.close()


def test_tc_synth_c08_an_exhausted_budget_fails_one_question_in_isolation(
    tmp_data_dir, monkeypatch
):
    """`TC-SYNTH-C08` (P0, the isolation half) — every attempt for every question
    fails: `failures` counts exactly the driver's compositions (5), the other
    questions store nothing, and the failure lands in the report rather than
    raising out of the driver — the operator-visible surface `CT-SYNTH-08`'s
    nothing-here-fails-a-grade sentence is read through."""
    monkeypatch.setenv(_ATTEMPT_BUDGET, str(_BUDGET))
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    store, run_id = _seeded_store(tmp_data_dir)
    try:
        provider = _AlwaysFailingProvider()
        report = Worker(store, provider, synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )
        # 5 questions × 3 attempts = 15; the L2 gate never runs (no L1 rows), so
        # the L2 failure is not counted separately — the driver counts one failure
        # per question composition.
        assert provider.calls == 5 * _BUDGET, (
            f"{provider.calls} calls — each of the 5 compositions spends the exact "
            "3-strike budget; a different count means a composition was skipped or "
            "the budget is not per narrative"
        )
        assert report.failures == 5, (
            f"{report.failures} failures — one per question composition, exactly"
        )
        assert report.synthesis_failure_rate == 1.0, (
            "a total outage reports rate 1.0 — the number the operator alerts on"
        )
        rows = store.cohort(COHORT_ID).query(
            "SELECT COUNT(*) AS n FROM narrative WHERE run_id = :r", r=run_id
        )
        assert rows[0]["n"] == 0, (
            f"{rows[0]['n']} narrative rows survived a total outage — no narrative "
            "describes work synthesis never composed"
        )
        assert report.model_calls == 5 * _BUDGET, (
            "the report's counter must include every retried strike, not just the "
            "first attempts"
        )
    finally:
        store.close()


def test_tc_synth_c08_total_synthesis_failure_fails_no_grade(
    tmp_data_dir, monkeypatch
):
    """`TC-SYNTH-C08` (P0, rung 3 consumer completion) — the clause's most
    consequential sentence, asserted directly: drive TOTAL synthesis failure, then
    `M-GRADE` still computes and finalizes the batch without a narrative. A missing
    narrative is a missing narrative; a synthesis outage that withheld grades is
    RISK-11.

    Landed with `M-GRADE` (#101): the service surface is the shipped
    `GradingService.compute_all / finalize_batch(run_id, actor) -> FinalizationRecord`
    (disclosed in `tests/support/grade_vocabulary.py`); criterion scores are seeded
    with the vocabulary's disclosed `write_criterion_scores` stand-in.
    """
    monkeypatch.setenv(_ATTEMPT_BUDGET, str(_BUDGET))
    open_grade = require(GRADE_MODULE, "open_grade", issue="#101")
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)

    store, run_id = _seeded_store(tmp_data_dir)
    try:
        provider = _AlwaysFailingProvider()
        report = Worker(store, provider, synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )
        assert report.failures == 5 and report.narratives == 0, (
            "precondition: the synthesis outage was total — a grade that survives "
            "it proves nothing if some narrative existed"
        )

        service = open_grade(store)
        service.compute_all(run_id)
        record = service.finalize_batch(run_id, actor="c08-test")
        assert record.finalized >= 1, (
            f"the batch finalized {record.finalized} grades through a total "
            "synthesis outage — nothing here fails a grade (CT-SYNTH-08): a "
            "narrative is feedback, a grade is the deliverable, and withholding "
            "the second for the first's absence is RISK-11"
        )
    finally:
        store.close()
