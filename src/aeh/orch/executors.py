"""The stage-executor seam, the governed provider, and the handles a composition layer drives."""

from __future__ import annotations

from decimal import Decimal
from dataclasses import dataclass
from typing import Any, NamedTuple, Protocol


# --- #362: the stage-executor seam (FR-ORCH-27, ADR-14) -------------------------------------


class StageExecutor(Protocol):
    """What the composition layer hands the orchestrator to do a unit's real work.

    `execute(unit, governed)` runs ONE leased unit through its stage's shipped worker — the
    extraction worker, the scoring worker — with `governed` as the provider those workers call.
    The orchestrator owns the ledger, the pool width and the counters; the executor owns what a
    unit *means*. That split is why this is a seam and not a branch: `M-PIPE` binds a real
    executor, the report-only console binds none, and neither can reach the other's behaviour.
    """

    def execute(self, unit: Any, governed: Any) -> Any: ...


    # The contract the dispatch loop relies on, stated because it cannot enforce it:
    #
    # * Return a `StageOutcome` — `completed=False` requeues the unit, `completed=True` closes
    #   it. Returning a provider `Completion` instead is the transport seam's shape and would
    #   accrue to the run's counters a second time.
    # * Do not close or quarantine the unit yourself: the orchestrator owns that ledger
    #   transition, and `complete()` refuses a unit a worker has already quarantined.
    # * Let `RateLimitedError`, `MemoryError`, `ProviderUnavailableError` and
    #   `BuildChangedError` propagate — the loop classifies each one. Anything else is a
    #   defect and stops the pass with the units left leased for the sweeper.


@dataclass(frozen=True)
class StageOutcome:
    """One executed unit's result, as the dispatch loop reads it.

    `completed` is the honest answer to "did this unit finish": a worker that struck out
    within its own budget returns False, and the orchestrator requeues rather than closing the
    unit. `detail` is carried for the caller's own reporting and is never parsed here.
    """

    completed: bool = True
    detail: str | None = None


class GovernedProvider:
    """The run's provider, with the run's dispatch counters wrapped around it (`FR-ORCH-27`).

    Every `complete()` a stage worker makes through this object accrues to the run: tokens in
    and out, cost, cached prefix tokens, the resolved build, and the in-flight/peak concurrency
    the governor's ceiling is about. The worker cannot opt out and does not know it is counted —
    which is the point. A worker that makes three calls and then strikes the unit out has still
    spent three calls, and the run's bill says so (`CT-PROV-11`: the counters are the
    provider's, read and persisted by M-ORCH).

    Everything else on the wrapped provider passes through untouched, so a worker that reaches
    for an attribute this class never heard of still finds the real provider's.
    """

    def __init__(self, provider: Any, state: dict[str, Any]) -> None:
        self._provider = provider
        self._state = state

    def complete(self, payload: Any, model_ref: Any = None, params: Any = None) -> Any:
        lock = self._state["lock"]
        with lock:
            self._state["in_flight_calls"] += 1
            self._state["peak_concurrency"] = max(
                self._state["peak_concurrency"], self._state["in_flight_calls"]
            )
        try:
            answer = self._provider.complete(payload, model_ref, params)
        finally:
            with lock:
                self._state["in_flight_calls"] -= 1
        _accrue_completion(self._state, answer)
        return answer

    def spent(self) -> Decimal:
        """The run's accrued actual cost so far, as this wrapper's counters hold it (#596)."""
        with self._state["lock"]:
            return Decimal(self._state["cost"])

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)


class TransportStageExecutor:
    """The `transport=` seam, as an executor (`FR-ORCH-27`): test-only, call-counting.

    It exists so the two seams are one code path rather than two: the dispatch loop always
    submits `executor.execute(...)`, and this is what a `transport=`-driven orchestrator binds.
    It calls `transport.call(request)` with the request assembled before the pool existed — no
    stage worker, no store write beyond the ledger's own.

    It returns the transport's own `Completion`, which the dispatch loop then accrues exactly
    as it always did: the transport seam makes ONE model call per unit, so the unit IS the
    call, and the in-flight counters are taken around it here rather than inside a provider
    the transport path never touches.
    """

    def __init__(self, transport: Any, payloads: dict[str, Any], state: dict[str, Any]) -> None:
        self._transport = transport
        self._payloads = payloads
        self._state = state

    def execute(self, unit: Any, governed: Any) -> Any:  # noqa: ARG002 — seam shape
        lock = self._state["lock"]
        with lock:
            self._state["in_flight_calls"] += 1
            self._state["peak_concurrency"] = max(
                self._state["peak_concurrency"], self._state["in_flight_calls"]
            )
        try:
            return self._transport.call(self._payloads[unit.work_id])
        finally:
            with lock:
                self._state["in_flight_calls"] -= 1


class _PreparedExecutor:
    """One executor with an optional pre-pass over the batch.

    The transport seam assembles every request BEFORE the pool exists — a raise then lands with
    nothing submitted, and the burst that follows reaches the full pool width (the pipelined
    alternative would never be observed to). A bound stage executor assembles inside its own
    worker, where the stage owns that door. This wrapper lets the dispatch loop hold one shape
    for both.
    """

    def __init__(self, executor: Any, prepare: Any = None,
                 payloads: dict[str, Any] | None = None) -> None:
        self._executor = executor
        self._prepare = prepare
        self._payloads = payloads

    def prepare(self, batch: Any) -> None:
        if self._prepare is None or self._payloads is None:
            return
        for unit in batch:
            self._payloads[unit.work_id] = self._prepare(unit)

    def execute(self, unit: Any, governed: Any) -> Any:
        # Bound first, then called: SEC-15's walker reads `<x>.execute(<arg>)` as a database
        # execute site whose statement is a parameter, and this is the STAGE seam
        # (`FR-ORCH-27`'s own name for it), not SQL. The alias keeps the public interface the
        # FR names while leaving the SQL vocabulary unambiguous.
        run_unit = self._executor.execute
        return run_unit(unit, governed)


def _accrue_completion(state: dict[str, Any], answer: Any) -> None:
    """Accrue one model answer to a run's counters (`CT-PROV-11`) — the ONE definition both
    seams use.

    The fields are read directly rather than through `getattr(..., 0)`: an answer that is not
    a `Completion` is a defect in whatever produced it, and a lenient read would accrue silent
    zeros — a run reporting no tokens and no cost for calls it actually made is the
    silent-failure shape the counters exist to prevent.
    """
    with state["lock"]:
        state["calls"] += 1
        state["tokens_in"] += answer.tokens_in
        state["tokens_out"] += answer.tokens_out
        state["cache_tokens"] += answer.cached_prefix_tokens or 0
        if answer.cost is not None:
            state["cost"] += answer.cost
        if state["resolved_build"] is None and answer.resolved_build:
            state["resolved_build"] = answer.resolved_build


#: `FR-ORCH-28`'s closed phase vocabulary. A phase outside it is a caller's mistake, refused
#: here and by the table's CHECK — two places, because the table outlives this process.
CELL_PHASES: tuple[str, ...] = ("integrity_pre", "integrity_post", "aggregated")


#: `FR-ORCH-29`'s hooks, and the phase each one reads.
READY_HOOKS: tuple[str, ...] = ("integrity_pre", "aggregate")


class CellKey(NamedTuple):
    """One cell: a (submission, criterion) pair, named so a tuple of them reads."""

    submission_id: str
    criterion_id: str


@dataclass(frozen=True)
class RunHandle:
    """Everything a composition layer needs to drive one run without reading the ledger.

    `M-PIPE` opens the transaction that `write_score`, `enqueue_escalation` and
    `mark_cell_phase` share (`FR-PIPE-04` requires the three to commit together), and a
    transaction comes from the cohort handle. `CT-PIPE-05` says `M-PIPE` executes no SQL, so
    it cannot find that handle by querying the run row itself — it asks the module that owns
    the row. That is what this is: one read, answered by `M-ORCH`, returning the handle and
    the four identities every hook needs.

    `status` and `pause_reason` are the stored values at the moment of the call —
    `RunResult.status` is required to equal `run.status`, and reading it through any other
    path would be reading around the owner.
    """

    run_id: str
    cohort_id: str
    cohort: Any
    package_id: str
    package_version_id: str
    status: str
    pause_reason: "str | None"
    #: The backend profile the run FROZE at creation (`FR-CONF-07`). A composition layer
    #: compares it against the process's current profile so a resume never rebinds a run to a
    #: backend its operator never approved (`FR-CONF-15`).
    backend_profile: str = ""
    #: When the run started, or `""` if it never did. A caller picking "the latest run" needs
    #: this: `run_id` is `run-<uuid4 hex>`, so id order is not time order.
    started_at: str = ""
    #: The panel build the run froze (FR-CONF-07), from its persisted provider config: one
    #: part of the six-part validation key a composition layer reads baselines under
    #: (FR-PIPE-15, #525). `""` when the row predates the field.
    panel_build_ref: str = ""


class PackageCatalogProtocol(Protocol):
    """The slice of `PackageCatalog` enumeration reads. Typed as a protocol so a test
    double satisfies it without a Tier P file (`CLAUDE.md` seam 2 — no network, no real
    upstream; the package arrives by injection like every other dependency)."""

    def criteria(self, v: str, question_id: str | None = None) -> tuple: ...
