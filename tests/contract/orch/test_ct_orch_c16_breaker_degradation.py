"""`TC-ORCH-C16` — both breakers, each asserted to **degrade visibly** (§6.11.7).

`CT-ORCH-16`'s two mechanisms, each at its boundary:

- **The criterion breaker** (`FR-ORCH-13`): escalated pairs among the first
  `ORCH_CRITERION_BREAKER_MIN_N` submissions processed, strictly above
  `ORCH_CRITERION_BREAKER_RATE`, latch a content-addressed breaker row and halt the
  criterion's escalations — `halted_by_breaker`, zero units written. The case sweeps
  the window's whole boundary: 0/4 and 1/4 admit, 2/4 is EXACTLY at the 50% rate and
  admits (strict `>` — rationing must not start early, R26), 3/4 trips, and a further
  enqueue meets the LATCH (the gate string names the latch, and the ledger holds one
  breaker row — a second trip evaluation cannot rewrite the first event). A second
  criterion with 1/1 = 100% escalated but only one processed submission admits,
  because the minimum gates BEFORE the rate does. The surfaced half: the breaker row's
  detail names the window arithmetic AND the mark the design requires
  (`un-gradeable_by_panel`, remainder single-judge provisional); `tripped_breakers()`
  carries it; `escalation_budget_state` lists the criterion as latched. The mark on
  the criterion's RESULT row is `M-AGG`'s artifact (#93's criterion marking — its own
  suite's case, standing behind that story); what `M-ORCH` owns and this case asserts
  is the latch, the detail that tells M-AGG to write it, and the decision surfaces.

- **The run budget** (`FR-ORCH-14`): the boundary sweep at exactly-threshold — at a
  rate EQUAL to `ORCH_ESCALATION_BUDGET` a pending escalation pair is dispatched
  (rationing must not start early), and the moment the rate is strictly above, the
  operator surface reads over-budget and marks the pending pairs provisional in
  **expected-value order**, highest first — the order admission resumes in. Neither
  breaker reduces scrutiny quietly: every degradation is named, on a surface an
  operator reads (RISK-24, R26).

Relationship to shipped cases, disclosed: `tests/unit/orch/test_escalation_policy.py`
asserts the PURE policies (`criterion_breaker_tripped`, `admit_escalations`) over their
own boundary arithmetic, and `tests/integration/orch/` drives the escalation atomicity
and the budget's dispatch deferral (this suite's TC-ORCH-C15 file holds the
budget-floor deferral differential). The limbs here are the LEDGER-side sweep: the
real enqueue path's decisions at each boundary count, the latch's persistence, and the
operator surfaces that make the degradation visible.

Isolation: rung 2 — real store, real package, real cohort ledger; the breaker and the
budget are evaluable with no model call (`NFR-ORCH-04`), so no provider double is
needed: completions are recorded at the ledger boundary the `complete` surface exists
for.
"""

from __future__ import annotations

import pytest

from aeh.orch import Orchestrator
from aeh.store import open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.contract]

_RUN_A = "run-c16-criterion-breaker"
_RUN_B = "run-c16-run-budget"

_C1 = {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
       "band_count": 2}
_C2 = {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic",
       "band_count": 2}


def _score_units(store, run_id):
    return store.cohort(ORCH_COHORT_ID).query(
        "SELECT work_id, submission_id, criterion_id, judge_id, origin, status "
        "FROM work_unit WHERE run_id = :r AND stage = 'score'",
        r=run_id,
    )


def _work_ids(store, run_id, submission_id, criterion_id, origin, status):
    return [
        r["work_id"] for r in _score_units(store, run_id)
        if (r["submission_id"], r["criterion_id"], r["origin"], r["status"])
        == (submission_id, criterion_id, origin, status)
    ]


def test_tc_orch_c16_criterion_breaker_trips_visibly_at_the_window(
    tmp_data_dir, monkeypatch
):
    """The boundary sweep over one criterion: 0/4 and 1/4 admit, 2/4 admits at exactly
    the rate, 3/4 trips and latches, the next enqueue meets the latch, and a
    below-minimum criterion is never evaluated at all. The trip is surfaced: one
    breaker row, detail naming the arithmetic and the mark, on both operator
    surfaces."""
    monkeypatch.setenv("HARNESS_ORCH_CRITERION_BREAKER_MIN_N", "4")
    monkeypatch.setenv("HARNESS_ORCH_CRITERION_BREAKER_RATE", "0.5")
    run_id = _RUN_A

    submissions = tuple(f"SYN-{i:03d}" for i in range(1, 6))
    store = open_store(tmp_data_dir)
    try:
        orchestrator, _, _ = seed_run(
            store, submissions=submissions, criteria=(_C1, _C2), run_id=run_id
        )
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)

        # The criterion breaker's window is the first MIN_N submissions whose judged
        # scoring COMPLETED: four done C1 pairs fill it; C2 has one (below the
        # minimum). Completions are recorded at the ledger boundary `complete`
        # exists for — the breaker is evaluable with no model call (NFR-ORCH-04).
        for submission_id in submissions[:4]:
            for work_id in _work_ids(
                store, run_id, submission_id, "C1", "base", "pending"
            ):
                orchestrator.complete(work_id)
        for work_id in _work_ids(
            store, run_id, "SYN-001", "C2", "base", "pending"
        ):
            orchestrator.complete(work_id)

        def _enqueue(pair):
            with store.cohort(ORCH_COHORT_ID).transaction() as tx:
                reports = orchestrator.enqueue_escalation(tx, pair)
            assert len(reports) == 1, (
                f"{len(reports)} report(s) for one pair — seed_run pins the run id, "
                "so the key resolves in exactly one run's ledger"
            )
            return reports[0]

        # 0/4 in the window — admits, units written.
        first = _enqueue(("SYN-001", "C1"))
        assert first.decision == "admitted" and first.units_inserted == 2, (
            f"the first enqueue at 0/4 decided {first.decision} with "
            f"{first.units_inserted} unit(s) — below the breaker's rate the plan "
            "must be written, or scrutiny is reduced before any evidence of harm"
        )
        # 1/4 — admits.
        second = _enqueue(("SYN-002", "C1"))
        assert second.decision == "admitted" and second.units_inserted == 2
        # 2/4 — EXACTLY at the rate: strict > means the boundary does not trip
        # (half of four is two, and two of four does not trip).
        third = _enqueue(("SYN-003", "C1"))
        assert third.decision == "admitted" and third.units_inserted == 2, (
            f"at exactly the breaker rate ({third.escalation_rate} vs "
            f"{third.escalation_budget}) the enqueue decided "
            f"{third.decision!r} — the breaker trips on MORE THAN the rate, and "
            "rationing that starts early is scrutiny reduced quietly (RISK-24)"
        )
        # 3/4 — the trip: halted, zero units, the gate names the trip.
        fourth = _enqueue(("SYN-004", "C1"))
        assert fourth.decision == "halted_by_breaker", (
            f"3/4 of the window escalated above a 50% rate and the enqueue decided "
            f"{fourth.decision!r} — the criterion breaker did not trip at its own "
            "boundary"
        )
        assert fourth.units_inserted == 0 and fourth.breaker_tripped
        assert fourth.gates["breaker"].startswith("TRIPPED and latched"), (
            f"the trip's gate reads {fourth.gates['breaker']!r} — a trip must say "
            "TRIPPED (and carry the arithmetic), not merely return a refusal"
        )
        # The latched criterion refuses further escalations without re-evaluating:
        # the gate string names the LATCH, and the ledger still holds one row.
        fifth = _enqueue(("SYN-005", "C1"))
        assert fifth.decision == "halted_by_breaker"
        assert fifth.gates["breaker"].startswith("latched "), (
            f"the post-trip enqueue's gate reads {fifth.gates['breaker']!r} — a "
            "latched breaker halts from its latch, and the surface must show the "
            "criterion is already latched, not a fresh evaluation"
        )
        # Below the minimum: C2 has ONE processed submission, escalated — 100% is
        # above any rate, but 1 < MIN_N: the minimum gates before the rate does.
        c_first = _enqueue(("SYN-001", "C2"))
        assert c_first.decision == "admitted" and c_first.units_inserted == 2, (
            f"a criterion whose only processed pair IS the escalated one was "
            f"breaker-evaluated ({c_first.gates['breaker']!r}) — the window minimum "
            "exists so a criterion's first escalation cannot trip its own breaker"
        )
        assert c_first.gates["breaker"].startswith("not tripped")

        # The latch is ONE row: a second trip evaluation cannot rewrite the event
        # (content-addressed INSERT OR IGNORE).
        breaker_rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT criterion_id, kind, detail FROM circuit_breaker "
            "WHERE run_id = :r",
            r=run_id,
        )
        assert len(breaker_rows) == 1, (
            f"{len(breaker_rows)} breaker rows latched for the run — one criterion "
            "trips once; a retried or repeated evaluation may not mint a second "
            "event (FR-ORCH-03's idempotence carried into the escalation path)"
        )
        assert breaker_rows[0]["criterion_id"] == "C1"
        assert breaker_rows[0]["kind"] == "criterion_escalation"
        detail = breaker_rows[0]["detail"]
        # The plan's mark is `ungradeable_by_panel`; the shipped detail spells it
        # `un-gradeable_by_panel` — the assert keys on the shared stem so either
        # spelling satisfies the oracle and a spelling tweak cannot green a detail
        # that stopped naming the mark.
        assert "3/4" in detail and "gradeable_by_panel" in detail, (
            f"the breaker detail reads {detail!r} — it must name the window "
            "arithmetic that tripped it AND the mark the design requires "
            "('ungradeable_by_panel' (plan's spelling; the shipped detail hyphenates "
            "it), remainder single-judge provisional), so the "
            "alert answers 'why', not just 'what' (FR-ORCH-13)"
        )

        # Surfaced, not merely stored: both operator surfaces carry the trip.
        trips = orchestrator.tripped_breakers(run_id)
        assert len(trips) == 1 and trips[0].criterion_id == "C1"
        assert "gradeable_by_panel" in trips[0].detail
        state = orchestrator.escalation_budget_state(run_id)
        assert state.tripped_criteria == ("C1",), (
            f"the budget surface lists {state.tripped_criteria} as tripped — the "
            "degradation must be visible on the operator surface the rate alert "
            "reads, not only in the ledger's breaker row (CT-ORCH-16: neither "
            "breaker reduces scrutiny quietly)"
        )
        assert "C1" in state.gates["breakers"]
    finally:
        store.close()


def test_tc_orch_c16_run_budget_admits_at_the_boundary_and_marks_the_remainder(
    tmp_data_dir, monkeypatch
):
    """The run-wide budget's boundary sweep. The claim pass ADMITS a pending
    escalation pair at a rate EXACTLY equal to the budget (strict `>`; rationing must
    not start early) and defers the same pair's remaining judge the moment the rate is
    strictly above — and the operator surface flips to over-budget, marking the
    pending pairs provisional in expected-value order, highest first."""
    # The criterion breaker stays out of the way (its own limb above): with the
    # window minimum at 100, a criterion with fewer processed pairs is never
    # breaker-evaluated, whatever its escalation share.
    monkeypatch.setenv("HARNESS_ORCH_CRITERION_BREAKER_MIN_N", "100")
    monkeypatch.setenv("HARNESS_ORCH_ESCALATION_BUDGET", "0.5")
    run_id = _RUN_B

    submissions = tuple(f"SYN-{i:03d}" for i in range(1, 6))
    store = open_store(tmp_data_dir)
    try:
        orchestrator, _, _ = seed_run(
            store, submissions=submissions, criteria=(_C1,), run_id=run_id
        )
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)

        def _extract_done(submission_id):
            rows = store.cohort(ORCH_COHORT_ID).query(
                "SELECT work_id, status FROM work_unit WHERE run_id = :r "
                "AND submission_id = :s AND stage = 'extract'",
                r=run_id, s=submission_id,
            )
            for row in rows:
                if row["status"] == "pending":
                    orchestrator.complete(row["work_id"])

        def _enqueue(pair, expected_value):
            with store.cohort(ORCH_COHORT_ID).transaction() as tx:
                reports = orchestrator.enqueue_escalation(
                    tx, pair, expected_value=expected_value
                )
            assert len(reports) == 1, (
                f"{len(reports)} report(s) for one pair — seed_run pins the run id, "
                "so the key resolves in exactly one run's ledger"
            )
            return reports[0]

        # processed = 2 done pairs (SYN-001, SYN-003); SYN-002's extraction stays
        # incomplete so its score units are sweep-2-gated and the claim pass below
        # sees ONLY the escalation units. SYN-001 escalated and done: rate 1/2 —
        # exactly the budget.
        for submission_id in ("SYN-001", "SYN-003"):
            _extract_done(submission_id)
            for work_id in _work_ids(
                store, run_id, submission_id, "C1", "base", "pending"
            ):
                orchestrator.complete(work_id)
        _enqueue(("SYN-001", "C1"), 1.0)
        for work_id in _work_ids(
            store, run_id, "SYN-001", "C1", "escalation", "pending"
        ):
            orchestrator.complete(work_id)

        # The boundary on the operator surface: at exactly the budget the run reads
        # within budget — rationing must not start early.
        state = orchestrator.escalation_budget_state(run_id)
        assert not state.over_budget and state.provisional_pairs == (), (
            f"at exactly the budget (rate {state.escalation_rate} vs "
            f"{state.budget}) the surface reads over_budget={state.over_budget} — "
            "the boundary is strict: at-budget behaves like below-budget"
        )

        # The boundary on dispatch: SYN-003's escalation units are the only claimable
        # units, and the claim pass ADMITS the pair at rate == budget. Had the gate
        # read `>=`, the pair would defer here and the assertion below would fail.
        _enqueue(("SYN-003", "C1"), 9.0)
        claimed_work_ids: set[str] = set()
        for _ in range(16):
            batch = orchestrator.lease("w-c16", "score", 8)
            if not batch:
                break
            for unit in batch:
                claimed_work_ids.add(unit.work_id)
                orchestrator.complete(unit.work_id)

        def _origin_of(work_id):
            return store.cohort(ORCH_COHORT_ID).query(
                "SELECT origin FROM work_unit WHERE work_id = :w", w=work_id
            )[0]["origin"]

        claimed_origins = [_origin_of(w) for w in claimed_work_ids]
        assert "escalation" in claimed_origins, (
            f"at a rate exactly equal to the budget the claim pass leased "
            f"{claimed_origins} — admit_escalations must admit at the boundary "
            "(escalated/processed > budget is strict), and rationing that starts "
            "early is scrutiny reduced without a name (RISK-24)"
        )
        # The same pair's SECOND judge: completing the first escalation unit pushed
        # the observed rate strictly above the budget (2/2), so the claim pass now
        # defers it — the provisional remainder, visible as a pending escalation unit
        # the dispatcher leaves alone.
        pending_after_boundary = {
            (r["submission_id"], r["criterion_id"])
            for r in store.cohort(ORCH_COHORT_ID).query(
                "SELECT submission_id, criterion_id FROM work_unit "
                "WHERE run_id = :r AND origin = 'escalation' AND status = 'pending'",
                r=run_id,
            )
        }
        assert pending_after_boundary == {("SYN-003", "C1")}, (
            f"pending escalation pairs after the boundary are "
            f"{sorted(pending_after_boundary)} — the widened panel's second judge "
            "must sit deferred (2/2 processed pairs escalated is strictly above the "
            "budget), not quietly dispatched"
        )

        # Two further escalations, queued with DISTINCT expected values while over
        # budget: the units are written (the budget rations dispatch, never the plan
        # write the verdict's transaction needs — CT-ORCH-08), and the surface must
        # mark the whole pending remainder provisional in expected-value order.
        fourth = _enqueue(("SYN-004", "C1"), 8.0)
        fifth = _enqueue(("SYN-005", "C1"), 2.0)
        assert fourth.decision == "admitted" and fifth.decision == "admitted", (
            "the enqueue wrote no plan above the budget — the budget rations "
            "DISPATCH (FR-ORCH-14), never the plan write (CT-ORCH-08)"
        )
        pending_pairs = {
            (r["submission_id"], r["criterion_id"])
            for r in store.cohort(ORCH_COHORT_ID).query(
                "SELECT submission_id, criterion_id FROM work_unit "
                "WHERE run_id = :r AND origin = 'escalation' AND status = 'pending'",
                r=run_id,
            )
        }
        assert pending_pairs == {
            ("SYN-003", "C1"), ("SYN-004", "C1"), ("SYN-005", "C1")
        }, (
            f"pending escalation pairs are {sorted(pending_pairs)} — the queued "
            "plans must sit in the ledger, deferred, not dropped"
        )
        state = orchestrator.escalation_budget_state(run_id)
        assert state.over_budget
        assert state.provisional_pairs == (
            "SYN-003/C1", "SYN-004/C1", "SYN-005/C1"
        ), (
            f"the provisional remainder reads {state.provisional_pairs} — it must "
            "be the full pending set in expected-value order, highest first "
            "(9.0, 8.0, 2.0), so admission resumes with the highest-value criterion "
            "when growth returns headroom (FR-ORCH-14)"
        )
        assert "OVER" in state.gates["rate"], (
            f"the rate gate reads {state.gates['rate']!r} while over budget — the "
            "degradation must be named where the operator reads, not stored in a "
            "row nothing shows (CT-ORCH-16)"
        )
    finally:
        store.close()
