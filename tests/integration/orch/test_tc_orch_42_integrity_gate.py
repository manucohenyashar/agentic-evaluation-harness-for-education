"""`TS-85` (issue #379) — `TC-ORCH-42`: the `integrity_pre` gate applies **only** with an
executor bound (`FR-ORCH-30`, RISK-46).

| Arm | Orchestrator | Expected |
|---|---|---|
| A | `executor=E` | the score unit is not claimable; after `mark_cell_phase(...,'integrity_pre',…)` it is |
| B | neither (report-only) | the score unit **is** claimable, with no phase row |
| C | `transport=T` | the score unit **is** claimable, with no phase row |

**Arms B and C are the regression arms, and the failure they guard is silent.** If the gate
were applied unconditionally, no score unit would ever be claimable on the report-only or
`transport=` paths — because neither path records a phase, so the gate's precondition could
never be met. The base M-ORCH suites would not go red: they would go **empty**, and "nothing
was leased" is a legal result everywhere it is asserted. RISK-46 rates that High for exactly
that reason, and these two arms are its only cover.

**Why `lease()` and not `progress()`.** The plan's expected column says "not leased by
`progress()`". Taken literally that makes arms B and C vacuous: with no executor bound
`progress()` is the report-only surface and dispatches nothing at all (`_dispatches` is
`executor is not None or transport is not None`), so "the score unit is leased" could not be
observed through it however the gate behaved — the arm would pass against the very defect it
exists to catch. `lease(worker, 'score', n)` is the claim surface the gate actually filters
(`_score_ready_rows`, `orch.py:4277`), it is observable identically under all three
configurations, and it is what a `progress()` dispatch pass calls underneath. Arm A asserts
through **both**, so the plan's stated surface is still pinned where it is meaningful.

**Isolation: rung 2** — real store, real Tier P package, real cohort ledger.
"""

from __future__ import annotations

from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.orch import Orchestrator, StageOutcome
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

SUBMISSION = "S01"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

_FINISH_EXTRACTS = Statement(
    "UPDATE work_unit SET status = 'done' WHERE run_id = :run_id AND stage = 'extract'"
)
_COUNT_PHASES = Statement(
    "SELECT COUNT(*) AS n FROM cell_phase WHERE run_id = :run_id"
)


class RecordingExecutor:
    """A `StageExecutor` that finishes every unit and remembers what it was handed."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def execute(self, unit: Any, governed: Any) -> StageOutcome:
        self.calls.append((unit, governed))
        return StageOutcome(completed=True, detail="recorded")


class UnusedProvider:
    """The provider an executor-bound orchestrator requires (`orch.py:2876` refuses one
    without). These arms assert on the claim, which happens before any model call, so a call
    reaching here means the test drifted off its own subject."""

    def estimate_cost(self, unit: Any) -> None:  # noqa: ARG002 — the seam's shape
        return None  # "not billed", as `RetentionConfirmingProvider` answers

    def complete(self, payload: Any, model_ref: Any = None, params: Any = None) -> Any:
        raise AssertionError(
            "TC-ORCH-42 asserts on what is claimable, not on what a model answers"
        )


class CountingTransport:
    """The `transport=` seam, counting calls — the arm-C orchestrator's model-call door."""

    def __init__(self) -> None:
        self.calls = 0

    def call(self, request: Any) -> Any:  # noqa: ARG002 — the seam's shape
        self.calls += 1
        raise AssertionError(
            "arm C claims units but must not need a model answer to prove it — the "
            "assertion is on the lease, and reaching the transport means the test drifted"
        )


def _gate_world(tmp_data_dir, **orchestrator_kwargs: Any):
    """A run whose extraction is terminal and whose one score unit is pending, with **no**
    `integrity_pre` phase — the precondition every arm shares."""
    store = open_store(tmp_data_dir)
    seeder, run_id, _version = seed_run(
        store, submissions=(SUBMISSION,), criteria=CRITERIA,
    )
    seeder.enumerate_units(run_id)
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        tx.execute(_FINISH_EXTRACTS, run_id=run_id)
    probe = Orchestrator(store, **orchestrator_kwargs)
    return store, probe, run_id


def _phase_rows(store: Any, run_id: str) -> int:
    return int(
        store.cohort(ORCH_COHORT_ID).query(_COUNT_PHASES, run_id=run_id)[0]["n"]
    )


# --- TC-ORCH-42 -----------------------------------------------------------------------------


def test_tc_orch_42_arm_a_an_executor_bound_run_gates_scoring_on_the_phase(tmp_data_dir):
    """Arm A — with `executor=E`, the score unit is unclaimable until the phase is recorded.

    Both halves are needed. The first alone would pass against an orchestrator that never
    claimed a score unit for any reason at all; the second is what proves the phase row is the
    thing that unblocked it.
    """
    executor = RecordingExecutor()
    store, probe, run_id = _gate_world(
        tmp_data_dir, executor=executor, provider=UnusedProvider(),
    )
    try:
        assert _phase_rows(store, run_id) == 0, "the precondition is a cell with no phase row"

        before = probe.lease("w-gate", "score", 5)
        assert before == (), (
            f"an executor-bound run leased {len(before)} score unit(s) for a cell whose "
            "integrity_pre phase is not recorded; FR-ORCH-30 says no panel scores a cell the "
            "integrity gate has not passed on"
        )

        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            probe.mark_cell_phase(tx, run_id, SUBMISSION, CRITERION, "integrity_pre", 1)

        after = probe.lease("w-gate", "score", 5)
        assert len(after) == 1, (
            "recording integrity_pre must make the cell's score unit claimable; it is still "
            "withheld, so the gate is keyed on something other than the phase row"
        )
        assert after[0].submission_id == SUBMISSION
    finally:
        store.close()


def test_tc_orch_42_arm_a_the_gate_also_holds_through_progress(tmp_data_dir):
    """Arm A through the plan's stated surface: `progress()` dispatches no score unit either.

    The executor is the witness. A dispatch pass that reached the score unit would hand it to
    `execute`, so an empty `calls` list is a direct reading of "the gate held", not an
    inference from a lease count.
    """
    executor = RecordingExecutor()
    store, probe, run_id = _gate_world(
        tmp_data_dir, executor=executor, provider=UnusedProvider(),
    )
    try:
        probe.start(run_id)
        probe.progress(run_id)

        scored = [
            unit for unit, _governed in executor.calls
            if getattr(unit, "stage", None) == "score"
        ]
        assert scored == [], (
            f"progress() dispatched {len(scored)} score unit(s) through the executor although "
            "the cell carries no integrity_pre phase (FR-ORCH-30)"
        )
    finally:
        store.close()


def test_tc_orch_42_arm_b_a_report_only_run_claims_the_score_unit_ungated(tmp_data_dir):
    """Arm B — RISK-46's regression arm. No executor: the score unit is claimable, no phase row.

    An unconditional gate makes this return `()`, and **every** base M-ORCH suite that asserts
    on leased score units would then pass over an empty set rather than fail. The phase-row
    count is asserted at zero so the claim cannot be explained by a phase appearing from
    somewhere.
    """
    store, probe, run_id = _gate_world(tmp_data_dir)
    try:
        claimed = probe.lease("w-report", "score", 5)

        assert len(claimed) == 1, (
            "a report-only orchestrator leased no score unit; the integrity_pre gate is being "
            "applied with no executor bound, and since this path records no phase the unit "
            "would never become claimable (RISK-46)"
        )
        assert _phase_rows(store, run_id) == 0, (
            "the claim was explained by a phase row, not by the gate being inapplicable"
        )
    finally:
        store.close()


def test_tc_orch_42_arm_c_a_transport_run_claims_the_score_unit_ungated(tmp_data_dir):
    """Arm C — `transport=T`: same as B. The transport is never called; the lease is the claim.

    `transport=` is the seam the base governor suites (`TC-ORCH-24`, `TC-ORCH-33`) dispatch
    through, so this arm is the one that keeps those suites non-vacuous.
    """
    transport = CountingTransport()
    store, probe, run_id = _gate_world(tmp_data_dir, transport=transport)
    try:
        claimed = probe.lease("w-transport", "score", 5)

        assert len(claimed) == 1, (
            "a transport-driven orchestrator leased no score unit although the cell carries no "
            "integrity_pre phase; the transport path records no phases, so gating it strands "
            "every score unit forever (RISK-46)"
        )
        assert _phase_rows(store, run_id) == 0
        assert transport.calls == 0, "leasing must not reach the model-call seam"
    finally:
        store.close()
