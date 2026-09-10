"""`TC-ORCH-C09` — the completion boundary is the LEDGER's, not a snapshot's (§6.11.7).

`CT-ORCH-09`'s two halves, exactly as the plan states them:

1. **The ledger grows during a run**, and completion means "no pending units AND no
   in-flight unit that could spawn an escalation". The clause is driven at the boundary:
   hold one in-flight score unit whose pair escalates, and assert the run is NOT
   reported complete — not by the pending units alone, and not by the in-flight one
   that will widen its own panel. An escalation that lands while everything "looks
   done" must keep the run open.
2. **`ProgressReport` is the sanctioned source**, and a consumer computing progress
   from the initial count is provably wrong: the case builds both — the naive
   consumer's total (the enumeration count, taken before the escalation existed) and
   the report — and compares them against the true final ledger. At the moment every
   BASE unit is done, the naive consumer says "complete" while the ledger holds pending
   escalation units the snapshot never knew about; the differential is the proof.

Relationship to shipped cases, disclosed: `tests/resilience/orch/
test_escalation_and_synthesis_boundaries.py` (RES-06) drives the escalation across a
kill; `tests/integration/orch/test_run_metrics_signal_presence.py` counts concepts the
metrics carry; `tests/integration/orch/test_completion_predicate.py` (TC-ORCH-22)
probes the pending-zero in-flight state for the leasing clause. None asserts the
completion predicate against a mid-run ESCALATION — the boundary this clause owns,
and the one a naive initial-count consumer (the console's or the grader's shape)
gets wrong in exactly the way that ships wrong grades.
"""

from __future__ import annotations

import pytest

from aeh.orch import STAGE_DETERMINISTIC, STAGE_EXTRACT, STAGE_SCORE, Orchestrator
from aeh.store import open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.contract]

_SUBMISSIONS = ("SYN-001", "SYN-002")
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C2", "kind": "mcq"},
)


def _unit_rows(store, run_id):
    return store.cohort(ORCH_COHORT_ID).query(
        "SELECT work_id, stage, submission_id, criterion_id, judge_id, origin, status "
        "FROM work_unit WHERE run_id = :r",
        r=run_id,
    )


def _origin_of(store, work_id):
    return store.cohort(ORCH_COHORT_ID).query(
        "SELECT origin FROM work_unit WHERE work_id = :w", w=work_id
    )[0]["origin"]


def _drive_base_units(orchestrator, store, run_id, *, hold_last_score=True):
    """Complete every extract/deterministic unit, then every base score unit EXCEPT
    one, which is returned in flight (leased, not completed).

    The score half completes by `work_id` at the ledger boundary (`complete()` accepts
    a pending unit — the at-least-once surface), then leases exactly one: the
    edge-local claim pass hands out ONE judge's units per pass, and a unit held in
    flight pins its judge's residency, so a lease loop that holds mid-drive would
    drain nothing else. Completing all but one by work_id and claiming exactly that
    one keeps the fixture's contract — one in-flight unit, everything else done.
    """
    for stage in (STAGE_EXTRACT, STAGE_DETERMINISTIC):
        while True:
            batch = orchestrator.lease("w-c09", stage, 100)
            if not batch:
                break
            for unit in batch:
                orchestrator.complete(unit.work_id)
    score_rows = [
        r for r in _unit_rows(store, run_id)
        if r["stage"] == "score" and r["origin"] == "base"
    ]
    assert score_rows, (
        "the fixture enumerated no base score unit — the boundary below would "
        "assert nothing about the in-flight half of the clause"
    )
    for row in score_rows[1:]:
        orchestrator.complete(row["work_id"])
    if not hold_last_score:
        orchestrator.complete(score_rows[0]["work_id"])
        return None
    (held,) = orchestrator.lease("w-c09", STAGE_SCORE, 1)
    assert held.work_id == score_rows[0]["work_id"], (
        "the lease claimed a unit other than the one left pending — the claim pass "
        "saw candidates the fixture did not expect"
    )
    return held


def test_tc_orch_c09_in_flight_unit_that_escalates_keeps_the_run_incomplete(
    tmp_data_dir,
):
    """The completion boundary: with one base score unit held in flight and its pair
    escalated, the run is NOT complete — the escalation units are pending and the
    in-flight unit could still be the one that spawned them."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA
        )
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)
        held = _drive_base_units(orchestrator, store, run_id)

        # The predicate's IN-FLIGHT conjunct, isolated: nothing is pending (every
        # enumerated unit is done but the one), yet the unit is in flight and will
        # spawn an escalation. A report that only counts pending rows says complete
        # right here — the probe must be taken BEFORE the escalation's pending rows
        # exist, or the not-complete verdict below is overdetermined by them.
        held_probe = orchestrator.progress(run_id)
        assert held_probe.pending == 0, (
            "fixture bug: units other than the held one are pending — the "
            "in-flight conjunct below would not be isolated"
        )
        assert not held_probe.complete, (
            "the run reported complete with zero pending units and one IN-FLIGHT "
            "unit that will escalate — the in-flight half of CT-ORCH-09's "
            "completion predicate is not read from the ledger"
        )

        # The escalation lands while the unit is IN FLIGHT — exactly the dispatch
        # loop's move when a verdict outside the band arrives (shipped surface,
        # caller's transaction: FR-ORCH-09).
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            orchestrator.enqueue_escalation(
                tx, (held.submission_id, held.criterion_id)
            )

        report = orchestrator.progress(run_id)
        assert not report.complete, (
            "the run reported complete with an in-flight unit whose pair just "
            "escalated — completion means no pending unit AND no in-flight unit that "
            "could spawn an escalation (CT-ORCH-09); a report that only counts "
            "pending units would hand the console a 'done' run that is still widening "
            "a panel"
        )
        assert report.in_flight >= 1, (
            "the report shows no in-flight unit while the fixture holds one leased — "
            "the in-flight half of the completion predicate is not read from the "
            "ledger"
        )
        assert report.pending >= 1, (
            "the escalation's units are not visible as pending — the widened panel's "
            "work exists in the ledger and the report must count it"
        )
    finally:
        store.close()


def test_tc_orch_c09_initial_count_consumer_is_provably_wrong(tmp_data_dir, monkeypatch):
    """The consumer differential: a consumer that took its totals at enumeration time
    (the initial count) declares the run complete the moment every BASE unit is done —
    `ProgressReport`, reading the current ledger, disagrees, and the final ledger
    proves the report right and the snapshot wrong."""
    # The run-wide escalation budget is TC-ORCH-C16's subject; here it would defer
    # the widened panel's second judge mid-drain (rate 1/2 over the 0.30 default) and
    # hold the run open for budget reasons the completion boundary does not name.
    monkeypatch.setenv("HARNESS_ORCH_ESCALATION_BUDGET", "1.0")
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA
        )
        initial_report = orchestrator.enumerate_units(run_id)
        naive_total = len(initial_report_work_ids := initial_report.work_ids)
        assert naive_total == len(set(initial_report_work_ids))
        orchestrator.start(run_id)
        held = _drive_base_units(orchestrator, store, run_id)

        # The escalation — taken AFTER the naive snapshot, the way a real run grows.
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            orchestrator.enqueue_escalation(tx, (held.submission_id, held.criterion_id))
        orchestrator.complete(held.work_id)

        # The naive consumer's moment: every unit it knows about is done.
        rows_now = _unit_rows(store, run_id)
        statuses = {r["work_id"]: r["status"] for r in rows_now}
        base_rows = [r for r in rows_now if r["origin"] == "base"]
        assert all(r["status"] == "done" for r in base_rows)
        naive_verdict = all(
            statuses.get(work_id) == "done" for work_id in initial_report_work_ids
        )

        report = orchestrator.progress(run_id)
        assert not report.complete, (
            "the report agreed with the naive consumer at the moment the naive "
            "consumer's snapshot ran out — the differential must catch the growth "
            "here, or the case proves nothing"
        )
        assert report.pending > 0
        assert naive_verdict, (
            "fixture bug: the naive consumer's arithmetic must conclude 'complete' at "
            "this point for the differential below to be a contradiction"
        )
        assert len(rows_now) > naive_total, (
            "the ledger had not grown past the naive snapshot at the differential "
            "moment — without growth the contradiction above asserts nothing"
        )

        # The true final count: the ledger's own rows, escalated panel included.
        final_rows = _unit_rows(store, run_id)
        assert len(final_rows) > naive_total, (
            "the ledger did not grow during the run — without growth the naive "
            "consumer would be right and the case would be asserting a tautology"
        )

        # Drive the escalation's units to done — the report must now agree with the
        # ledger, and its sanctioned counts must reconcile to the true final count.
        while True:
            batch = orchestrator.lease("w-c09", STAGE_SCORE, 100)
            if not batch:
                break
            for unit in batch:
                orchestrator.complete(unit.work_id)
        final_report = orchestrator.progress(run_id)
        assert final_report.complete
        assert final_report.pending == 0
        assert final_report.done == len(final_rows), (
            f"the sanctioned report counts {final_report.done} done units against a "
            f"ledger of {len(final_rows)} rows — ProgressReport must be computed from "
            "the ledger's CURRENT contents, not from a state snapshot or a cached "
            "count (CT-ORCH-09: the ledger grows during a run)"
        )
    finally:
        store.close()
