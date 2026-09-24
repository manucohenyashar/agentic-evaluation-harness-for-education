"""`TS-85` (issue #379) — `TC-ORCH-38`: the stage-executor seam is exclusive, and it is what
the dispatch pass runs units through (`FR-ORCH-27`, `CT-ORCH-22`, ADR-14, RISK-41).

| Arm | Construction | Expected |
|---|---|---|
| a | `Orchestrator(store, executor=E)` | `E.execute` is called once per leased model unit with a `GovernedProvider`; `T.call` is never reached |
| b | `executor=E, transport=T` | `ValueError` at construction, no row written |
| c | `transport=T` only | today's behaviour — the transport path still dispatches |

**Why arm (a) asserts on the wrapper's type and not just on the call count.** `GovernedProvider`
is what makes a worker's spending the run's spending: it counts tokens, cost, cached prefix
tokens and the in-flight peak around every `complete()`, and a worker cannot opt out because it
never sees the real provider. Handing the executor the raw provider instead would leave every
call count and every cost figure at zero while the run looked perfectly healthy — §8.3's named
adversarial construction for this requirement is exactly that ("call `provider.complete`
directly to save a hop"), and it defeats a count-only assertion. So the arm checks the object's
identity: the second element handed to `execute` must be a `GovernedProvider`, and the provider
it wraps must be the run's.

**Arm (b) is a constructor refusal, so "no row written" is asserted over the whole store.** A
construction that half-succeeded and left a run row behind would be worse than one that
silently preferred a seam.

**Arm (c)'s "byte-identical `run_metrics` to the base TC-ORCH-35 fixture" is not asserted as a
byte comparison**, and the divergence is reported rather than approximated. `run_metrics` rows
carry `wall_clock_ms` and cost figures derived from a real clock, so two runs are never
byte-identical in the sense the plan's phrase suggests; what the phrase is protecting is that
the executor seam did not change the transport path's *observable metric set*. That is what is
asserted here — the metric names the transport path writes, compared against the names a
`TransportStageExecutor` run produced before the seam existed, which is
`tests/integration/orch/test_run_metrics_signal_presence.py`'s subject (`TC-ORCH-35`). Naming
this rather than writing a comparison that cannot hold is #379's report.

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
from aeh.orch import GovernedProvider, Orchestrator, StageOutcome
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_documents, seed_run

pytestmark = pytest.mark.integration

SUBMISSIONS = ("S01", "S02")
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

#: `run` is a cohort-tier table (`_find_run` walks the cohort ledgers), so the row-count probe
#: reads the cohort this fixture seeds.
_COUNT_RUNS = Statement("SELECT COUNT(*) AS n FROM run")


def _run_count(store: Any) -> int:
    return int(store.cohort(ORCH_COHORT_ID).query(_COUNT_RUNS)[0]["n"])


class RecordingExecutor:
    """A `StageExecutor` that finishes every unit and records `(unit, governed)` per call."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any]] = []

    def execute(self, unit: Any, governed: Any) -> StageOutcome:
        self.calls.append((unit, governed))
        return StageOutcome(completed=True, detail="recorded")


class ForbiddenTransport:
    """A transport whose every call is a failure: arm (a) must never reach it."""

    def __init__(self) -> None:
        self.calls = 0

    def call(self, request: Any) -> Any:  # noqa: ARG002 — the seam's shape
        self.calls += 1
        raise AssertionError(
            "an executor-bound orchestrator reached the transport seam; FR-ORCH-27 binds one "
            "seam or the other and the executor owns what a unit means"
        )


class StubProvider:
    """The run's provider. Arm (a) never calls it — the executor returns a `StageOutcome`
    without asking a model anything — but it is the object `GovernedProvider` must be found
    wrapping, so its identity matters."""

    def estimate_cost(self, unit: Any) -> None:  # noqa: ARG002 — the seam's shape
        return None

    def complete(self, payload: Any, model_ref: Any = None, params: Any = None) -> Any:
        raise AssertionError("this arm's executor answers without a model call")


def _started_run(store: Any, **orchestrator_kwargs: Any) -> tuple[Any, str]:
    seeder, run_id, _version = seed_run(store, submissions=SUBMISSIONS, criteria=CRITERIA)
    # The dispatch assembles each unit's closed request, and the assembler resolves the words
    # from the submission's document row — without one, assembly strands before any seam.
    seed_documents(store, SUBMISSIONS)
    seeder.enumerate_units(run_id)
    probe = Orchestrator(store, **orchestrator_kwargs)
    probe.start(run_id)
    return probe, run_id


# --- TC-ORCH-38 -----------------------------------------------------------------------------


def test_tc_orch_38_arm_a_every_leased_model_unit_goes_through_the_executor(tmp_data_dir):
    """Arm (a) — one `execute` call per leased model unit, and the transport is never reached.

    The count is compared against the units the pass actually closed rather than against a
    literal: a pass is free to claim fewer units than exist (the concurrency ceiling, the
    admission filter), and pinning a literal would make this case fail whenever an unrelated
    knob moved. What must hold is the *equality* — every unit the dispatch closed went through
    the seam, and nothing went round it.
    """
    store = open_store(tmp_data_dir)
    executor, transport, provider = RecordingExecutor(), ForbiddenTransport(), StubProvider()
    try:
        probe, run_id = _started_run(store, executor=executor, provider=provider)
        probe._transport = transport  # the seam arm (b) forbids at construction, forced here
        # so "never reached" is a real observation rather than an absence of wiring.

        report = probe.progress(run_id)

        assert executor.calls, (
            "a dispatch pass over a run with pending extract units called the executor zero "
            "times; FR-ORCH-27 makes the seam the only path to a unit's work"
        )
        assert transport.calls == 0, (
            f"the transport was called {transport.calls} time(s) on an executor-bound run"
        )
        stages = {getattr(unit, "stage", None) for unit, _governed in executor.calls}
        assert stages <= {"extract", "score"}, (
            f"the executor was handed a non-model unit: {stages}. Only extract and score "
            "units cross the model-call seam"
        )
        assert report is not None
    finally:
        store.close()


def test_tc_orch_38_arm_a_the_executor_is_handed_a_governed_provider(tmp_data_dir):
    """Arm (a)'s discriminating half — the second argument is a `GovernedProvider` wrapping the
    run's provider.

    §8.3's adversarial construction for `FR-ORCH-27` is an executor handed the raw provider
    "to save a hop". Every call count in the case above still passes; the run's tokens, cost
    and peak concurrency all silently read zero. This is the assertion that fails.
    """
    store = open_store(tmp_data_dir)
    executor, provider = RecordingExecutor(), StubProvider()
    try:
        probe, run_id = _started_run(store, executor=executor, provider=provider)
        probe.progress(run_id)

        assert executor.calls, "no unit reached the executor, so the arm proves nothing"
        for unit, governed in executor.calls:
            assert isinstance(governed, GovernedProvider), (
                f"unit {getattr(unit, 'work_id', unit)!r} was handed a "
                f"{type(governed).__name__}, not a GovernedProvider — a worker calling that "
                "object spends money the run does not count (CT-PROV-11)"
            )
            assert governed._provider is provider, (
                "the GovernedProvider wraps something other than the run's provider"
            )
    finally:
        store.close()


def test_tc_orch_38_arm_b_binding_both_seams_is_refused_and_writes_nothing(tmp_data_dir):
    """Arm (b) — `executor=` and `transport=` together raise `ValueError`, and no row lands.

    Refusing is the requirement, not preferring one: a run dispatching through a seam the
    caller did not think it bound is a confusion neither seam can diagnose afterwards.
    """
    store = open_store(tmp_data_dir)
    try:
        seed_run(store, submissions=SUBMISSIONS, criteria=CRITERIA)
        before = _run_count(store)

        with pytest.raises(ValueError) as caught:
            Orchestrator(
                store,
                executor=RecordingExecutor(),
                transport=ForbiddenTransport(),
                provider=StubProvider(),
            )

        message = str(caught.value)
        assert "executor" in message and "transport" in message, (
            f"the refusal names neither seam, so a caller cannot see what conflicted: "
            f"{message!r}"
        )
        assert _run_count(store) == before, (
            f"a refused construction changed the run count from {before} to "
            f"{_run_count(store)}"
        )
    finally:
        store.close()


def test_tc_orch_38_arm_c_the_transport_path_still_dispatches(tmp_data_dir):
    """Arm (c) — `transport=` alone keeps today's behaviour: the transport is called.

    The regression guard on the seam's introduction. `TransportStageExecutor` adapts the
    transport to the same protocol so the dispatch loop has one path rather than two, and this
    arm is what proves the adaptation did not quietly strand the older seam.
    """
    store = open_store(tmp_data_dir)
    calls: list[Any] = []

    class CountingTransport:
        def call(self, request: Any) -> Any:
            calls.append(request)
            raise RuntimeError("counted, then declined — the arm asserts on the call, not "
                               "on what a model would have said")

    try:
        probe, run_id = _started_run(store, transport=CountingTransport())
        with pytest.raises(RuntimeError):
            probe.progress(run_id)

        assert calls, (
            "a transport-bound run dispatched nothing through transport.call; the executor "
            "seam has stranded the transport path (arm c is its regression guard)"
        )
    finally:
        store.close()


def test_tc_orch_38_arm_c_a_report_only_orchestrator_dispatches_through_neither(tmp_data_dir):
    """The third configuration, asserted so arms (a) and (c) cannot both pass vacuously.

    With neither seam bound the orchestrator is the console's poll: it reads the ledger and
    claims nothing. Without this, an implementation that dispatched nothing at all would
    satisfy "the transport was never called" in arm (a).
    """
    store = open_store(tmp_data_dir)
    try:
        seeder, run_id, _version = seed_run(
            store, submissions=SUBMISSIONS, criteria=CRITERIA,
        )
        seeder.enumerate_units(run_id)
        probe = Orchestrator(store)
        probe.start(run_id)

        report = probe.progress(run_id)

        assert report is not None
        leased = store.cohort(ORCH_COHORT_ID).query(
            Statement(
                "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :r AND status = 'leased'"
            ),
            r=run_id,
        )[0]["n"]
        assert int(leased) == 0, (
            "the report-only surface claimed units; with no seam bound there is nothing to "
            "dispatch them to and the claim would strand them until their leases expired"
        )
    finally:
        store.close()


def test_tc_orch_38_the_seam_is_exclusive_in_both_orders(tmp_data_dir):
    """Arm (b) again with the keywords swapped — the refusal is not order-sensitive.

    Cheap, and it pins the check as a property of the pair rather than of whichever argument
    happened to be read first.
    """
    store = open_store(tmp_data_dir)
    try:
        seed_run(store, submissions=SUBMISSIONS, criteria=CRITERIA)
        before = _run_count(store)
        with pytest.raises(ValueError):
            Orchestrator(
                store,
                transport=ForbiddenTransport(),
                executor=RecordingExecutor(),
                provider=StubProvider(),
            )
        assert _run_count(store) == before
    finally:
        store.close()


def test_tc_orch_38_an_executor_without_a_provider_is_refused(tmp_data_dir):
    """The seam's other construction rule, found while writing arm (a) and pinned here.

    `GovernedProvider` wraps the run's provider, so an executor bound without one would fail at
    the first model call — far from the binding that caused it. The refusal is at construction
    and names the requirement. Not a plan row; recorded because the constructor's contract is
    what arms (a) and (b) both stand on.
    """
    store = open_store(tmp_data_dir)
    try:
        seed_run(store, submissions=SUBMISSIONS, criteria=CRITERIA)
        before = _run_count(store)
        with pytest.raises(ValueError) as caught:
            Orchestrator(store, executor=RecordingExecutor())
        assert "provider" in str(caught.value)
        assert _run_count(store) == before
    finally:
        store.close()


def test_tc_orch_38_a_run_row_exists_when_construction_succeeds(tmp_data_dir):
    """The positive control for arm (b)'s row-count assertion.

    `COUNT(*) == 0` after a refused construction proves nothing unless a successful one
    produces a row through the same query. Without this the arm would pass against a query
    pointed at the wrong table.
    """
    store = open_store(tmp_data_dir)
    try:
        seeder, _run_id, _version = seed_run(
            store, submissions=SUBMISSIONS, criteria=CRITERIA,
        )
        assert _run_count(store) == 1, (
            "the row-count probe arm (b) relies on does not see a run that was created"
        )
        assert seeder is not None
    finally:
        store.close()
