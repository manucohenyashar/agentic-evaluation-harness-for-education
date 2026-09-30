"""`Orchestrator`: creates runs, enumerates and leases their work, and reports progress."""

from __future__ import annotations

import json
from collections import deque
from datetime import timedelta
from typing import Any, Sequence

from aeh.store import LeaseClock, lease_clock

from .constants import EXTRACTOR_VERSION
from .work_units import compute_work_id, WorkUnit
from .errors import RunNotFoundError, WorkLedgerError
from .statements import ORCH_STATEMENTS
from .settings import _env_int, LEASE_SECONDS_ENV, _now, ORCH_LEASE_SECONDS
from .run_records import default_package_id_for
from .reports import SweepPlan
from .package_checks import _cohort_keys_on_filesystem
from .executors import PackageCatalogProtocol, RunHandle
from .run_lifecycle import RunLifecycleMixin
from .costs import CostsMixin
from .enumeration import EnumerationMixin
from .leasing import LeasingMixin
from .escalation import EscalationMixin
from .dispatch import DispatchMixin
from .composition import CompositionMixin
from .reporting import ReportingMixin


class Orchestrator(RunLifecycleMixin, CostsMixin, EnumerationMixin, LeasingMixin, EscalationMixin, DispatchMixin, CompositionMixin, ReportingMixin):
    """The ledger slice of §3.7's Orchestrator: create a run, enumerate its units,
    resume, lease them under the two-sweep plan, and widen panels — escalation
    (`enqueue_escalation`), the random arm, the criterion breakers and the run-wide
    escalation budget are #60's. **#61 lands the run lifecycle** (`FR-ORCH-25`):
    `start(run_id)` is the `pending → running` edge and displays the run's estimated
    cost before any dispatch (`FR-ORCH-15`); `pause(run_id, cause=...)` writes the
    control row and applies it through the read pass the claim loop shares — a
    `ProviderUnavailableError` (`FR-ORCH-16`), a `BuildChangedError` (`FR-ORCH-17`) or
    an operator request pause a run without substituting anything; the cost ceiling the
    run froze is enforced from the provider seam's measured figures inside every claim
    transaction, and a crossing dispatch pauses the run naming spend and remaining
    (`CT-ORCH-12`'s four pause conditions — the fourth being the sensed ceiling).
    Pauses touch lifecycle columns only, so a resume re-binds to the frozen backend
    structurally: there is no substitution code path to suppress. Control rows written
    while the orchestrator was not dispatching queue in `run_control` and are honoured
    at the next read (`CT-ORCH-13`). Dispatch isolation and `ProgressReport` are #62's,
    below. `resume` takes no arguments from its first commit.

    **Recorded interpretations (#62) — dispatch, residency, concurrency, progress.**
    The dispatch loop's model-call seam takes the stage's ASSEMBLED closed request —
    `ScoringRequest` via `M-JUDGE`'s `ScoringWorker.assemble`, `ExtractionRequest`
    via `M-EXTRACT`'s `assemble_request` (`FR-ORCH-20`'s own wording: "exactly one
    submission per scoring or extraction request" — what is dispatched is the
    request, and its exactly-one form is assertable only over the closed type,
    `CT-JUDGE-02`). The loop's classification, batching and residency are untouched
    by the payload's shape; deterministic units cross nothing (their evaluation
    makes no model call), so the deterministic walk completes directly. Residency
    batches **judge models only**:
    `residency_policy` lists the roles permitted resident, and the units this loop
    dispatches are score units whose `judge_id` names a model — the transcriber's
    residency is the transcription stage's, not yet this module's. A judge's
    **batch** is its dispatchable work: the units the ready order hands out for it,
    plus the ones in flight; a gated or budget-deferred pending unit is not
    dispatchable (it may never become ready without an operator) and cannot hold a
    model resident — a residency held over undispatchable work starves every judge
    behind it — and when gated work becomes ready the model reloads to serve it. A
    residency swap's
    duration is the wall time of the first model call after the swap — the load rides
    that call; a swap whose first call is still to come records the count and adds the
    duration when the load is actually paid. The dispatch loop's extract walk sends
    the assembled `ExtractionRequest` (extraction IS a model call — `FR-ORCH-20`
    covers extraction requests); the deterministic walk is the ledger transition
    itself, completed with no transport (a deterministic criterion's evaluation makes
    no model call): completing the transition is what unlocks the judged batch, and
    the walks are bounded per pass by `HARNESS_ORCH_DISPATCH_WALK_BATCH`. The
    concurrency governor's cap is per run, starts at the run's frozen
    `concurrency_ceiling` (never the environment's — `FR-CONF-07`'s freeze), divides
    once per pass on any rate-limited/OOM call (floor 1) and is clamped per pass while
    M-STORE signals write backpressure (`CT-STORE-06`: a signal to reduce, never a
    fault — the clamp is sensed at the pass's start and does not persist). The report's
    `concurrency` is the cap the NEXT pass will run at (post-clamp, post-reduction) —
    the operator reads the reduction that takes effect. The OOM remedy requeues the
    judge's in-flight units without consuming attempts (the box's condition is not the
    unit taxonomy's, §9.11), halves the cap, and at the drop threshold removes the
    judge from the run's `panel_config` as a strict subset (never below one judge) —
    its un-run units stay in the ledger for an operator to re-queue under a smaller
    panel, never silently discarded. The completion predicate on the report is
    **ledger-derived, not run-status-derived** (`FR-ORCH-12`): nothing pending and no
    in-flight scoring judgment — a score unit in flight can still disagree with its
    panel and spawn an escalation. The report's estimate feeds
    `estimated_completion_seconds` with the ledger's own totals. `progress()` with no
    transport dispatches nothing: it is the report-only surface (the console's poll).

    **Recorded interpretations (#61).** The ceiling comparison is strict `>` per
    dispatch (a dispatch landing exactly at the ceiling proceeds; the run pauses once
    spend sits at the ceiling) — the breaker's and budget's reading of an "at or above"
    boundary; the at-ceiling sense fires only when the claim actually moved spend (a
    not-billed figure adds nothing and consumes no ceiling, so replayed work drains
    past an at-ceiling pause without re-pausing it). The estimate displayed at start is
    the sum of the units' seam figures. Every pause and resume — operator, sensed, or
    explicit `resume(run_id)` — is written as a `run_control` row and effected through
    the control-read pass (request ≠ effect, `CT-ORCH-13`); a resume supersedes the
    pauses queued before it (latest control intent wins, bounded by request time), and
    a queued pause on a `pending` run is honoured at `start` (the machine's declared
    edges have no `pending → paused` from mid-flight); a queued pause on a `running`
    run applies at the next claim pass; an operator's pause stays sticky across a
    no-argument `resume` (a stop outranks a scheduler's restart). Run-level `complete`
    is probed after every won lifecycle write and fires only for a `running` run with
    at least one unit and none open (quarantined units are not open — their record
    stands).

    The store is injected (`CLAUDE.md` seam 2). Nothing here opens a network connection
    or contacts a judge: enumeration is a pure function of the ledger, the package
    catalog and the roster, over an injected store, and every escalation decision is
    pure policy over ledger state (`NFR-ORCH-04`). The provider seam is injected the
    same way and consulted only for cost figures — no dispatch, retry or pause decision
    ever asks the provider what to do.
    """

    def __init__(
        self,
        store: Any,
        *,
        package_id_for: Any = default_package_id_for,
        cohort_keys_for: Any = None,
        clock: Any = None,
        provider: Any = None,
        transport: Any = None,
        executor: Any = None,
        decision_provider: Any = None,
        wall_clock: Any = None,
    ) -> None:
        self._store = store
        #: FR-ORCH-44 (design 1.9 §3.9, #513): every wall-time read of this orchestrator
        #: (run start/complete, control rows, cell phases, the run wall-clock figure) goes
        #: through this callable returning an aware `datetime`. Defaults to real UTC; the
        #: lease clock is separate (`clock`).
        self._wall_clock = wall_clock
        #: Jev design delta FR-ORCH-40: the decision provider whose `verify_retention` covers
        #: the decision model at a `cloud-hosted` run start. Optional; see
        #: `_verify_retention_at_start`.
        self._decision_provider = decision_provider
        self._package_id_for = package_id_for
        #: The cost seam (`FR-ORCH-15`): the object the orchestrator consults for a
        #: unit's cost figure. Declared protocol: `estimate_cost(unit) -> Decimal |
        #: CostEstimate` — a `Decimal` is the figure; a `CostEstimate`-shaped answer
        #: contributes its `.cost` (None = not billed, which adds nothing to the
        #: accrual — replay is not billed and must not consume ceiling). Optional: a
        #: run whose frozen config carries no ceiling never consults it, and the
        #: estimate-at-start is simply not displayed when no seam was injected — a
        #: fabricated zero would read as a measured price (`CT-PROV-03`'s principle).
        #: A run that DID freeze a ceiling but is dispatched without a seam is refused
        #: at the claim pass, loudly: a ceiling checked against nothing is the
        #: estimated-optimism shape the seam exists to prevent.
        self._provider = provider
        #: The model-call transport seam (`FR-ORCH-19/21`, CLAUDE.md seam 2 — built the
        #: moment the dependency exists). Declared protocol: `call(request) ->
        #: Completion` (the real shipped type, `aeh.prov.Completion`) or a raise of the
        #: real taxonomy error (`RateLimitedError`, `MemoryError`) — the dispatch loop
        #: classifies by type and nothing else. `request` is the stage's ASSEMBLED
        #: closed request (`FR-ORCH-20`: the dispatch sends "exactly one submission per
        #: scoring or extraction request", never the ledger row — the assembler is the
        #: owning stage's shipped door, and `FR-JUDGE-02`'s exactly-one form is
        #: assertable only over the closed type). No default implementation: a
        #: fabricated in-process "provider" would be a network-shaped dependency
        #: smuggled past the seam. None means this orchestrator does not dispatch
        #: model work: `progress()` is then the report-only surface (the console's
        #: poll), which reads the ledger and claims nothing.
        self._transport = transport
        #: #362 (`FR-ORCH-27`, ADR-14): the stage-executor seam. `M-PIPE` binds one and the
        #: units do their real work through the shipped stage workers; `transport=` stays the
        #: test-only call-counting shape, adapted to the same protocol by
        #: `TransportStageExecutor` so the dispatch loop has one path rather than two.
        #: Binding both is refused rather than silently preferring one — a run dispatching
        #: through a seam the caller did not think it bound is a confusion neither seam can
        #: diagnose afterwards.
        if executor is not None and transport is not None:
            raise ValueError(
                "bind an executor OR a transport, not both (FR-ORCH-27): the executor runs "
                "units through their stage workers and the transport is the test-only "
                "call-counting seam, so a run holding both would dispatch through one of "
                "them for reasons no caller stated."
            )
        if executor is not None and provider is None:
            raise ValueError(
                "an executor was bound with no provider (FR-ORCH-27): the stage workers it "
                "runs make their model calls through the GovernedProvider wrapped around the "
                "run's provider, so a run without one would fail at the first call, far from "
                "the binding that caused it."
            )
        self._executor = executor
        #: Maps the store to its cohort tier keys, for the run discovery `resume()` does
        #: with no arguments. Default: the `cohorts/` directory under the store's data
        #: dir — the ledger's own files are the bookkeeping, which is the whole point of
        #: `FR-ORCH-02`. Injectable so a double-backed test can pin discovery.
        self._cohort_keys_for = cohort_keys_for or _cohort_keys_on_filesystem
        #: The injected clock, driving the store's monotonic lease counter (`FR-STORE-11`).
        #: None means the production clock (`aeh.store.SystemClock`). Passed through to
        #: `lease_clock()` on first use and cached — one lease clock per store, the
        #: store's own rule, and lazy so an orchestrator that only enumerates never
        #: claims the store's clock slot from one that leases.
        self._clock = clock
        self._lease_clock_obj: LeaseClock | None = None
        #: Package catalogs held open per (package_id, package_version_id) — the claim
        #: pass reads the catalog on every dispatch, and `NFR-PKG-05`'s per-run cache is
        #: per instance, so one live catalog per version is what makes the hot path one
        #: indexed query instead of a version load.
        self._catalogs: dict[tuple[str, str], Any] = {}
        #: The two sweeps' derived ordering data, per package version (`_sweep_plan`).
        #: The package is immutable for the run, so the plan is computed once and reused
        #: for the run's lifetime — the topological positions and the dependency closure
        #: are pure functions of the version.
        self._sweep_plans: dict[str, SweepPlan] = {}
        #: The dispatch order of one (run, stage), drained front to back across claim
        #: passes (`_claim_pass`). Keyed `(run_id, stage)`; an entry holds only the
        #: still-unclaimed ready candidates. Rebuilt on exhaustion, on a lost claim
        #: guard, on a requeue (failure or sweeper reclaim), and on re-enumeration —
        #: the invalidation set `_claim_pass` states.
        self._order_cache: dict[tuple[str, str], deque[Any]] = {}
        #: Per-run dispatch state (`_dispatch_state`): the concurrency governor's cap,
        #: the residency batch's state, the OOM ladder's counts and the run-metrics
        #: accumulators. Keyed by run_id, rebuilt from the ledger when absent — the
        #: ledger is the bookkeeping (`FR-ORCH-02`); this holds only what the ledger
        #: cannot say (the seam's in-memory counters); the dropped judges are ledger
        #: state, not this dict's (`_dropped_judges`).
        self._dispatch_states: dict[str, dict[str, Any]] = {}

    def _invalidate_order_cache(self, run_id: str) -> None:
        """Drop the dispatch-order cache entries for one run (`NFR-ORCH-01`).

        Any write that changes the claimable set — enumeration, a failure requeue, a
        sweeper reclaim — can falsify a cached order; the next claim pass re-reads
        instead of trusting it.
        """
        for key in [k for k in self._order_cache if k[0] == run_id]:
            del self._order_cache[key]

    # -- the lease (FR-ORCH-04) -----------------------------------------------------------------

    def _lease_clock(self) -> LeaseClock:
        """The store's monotonic lease counter, built on this orchestrator's clock.

        Lazily, and cached: `lease_clock()` allows one instance per store, and the first
        caller's clock is the store's clock for its lifetime — a second orchestrator
        injecting a different clock is refused by the store rather than silently ignored,
        which is `CT-STORE-14`'s other half (a second counter would restore past every
        outstanding lease and reclaim work that is genuinely held).
        """
        if self._lease_clock_obj is None:
            self._lease_clock_obj = lease_clock(self._store, self._clock)
        return self._lease_clock_obj

    def _lease_ttl(self) -> int:
        """The lease TTL in seconds, read from the environment at **call** time."""
        return _env_int(LEASE_SECONDS_ENV, ORCH_LEASE_SECONDS)

    def _wall_expiry(self, clock: Any, ttl_seconds: int) -> str:
        """The expiry rendered on the wall clock, for the operator reading the row.

        Recorded beside the ticks, never compared (`LeaseClock`'s own split, `FR-STORE-11`):
        a wall-clock expiry would read every lease live after the host clock moved
        backwards, which is `CT-STORE-14`'s named failure. The comparison input is and
        stays `lease_expires_ticks`.
        """
        # FR-ORCH-44: the wall expiry is a wall-time read, so an injected wall clock stamps it.
        now = self._wall_clock() if self._wall_clock is not None else clock.now()
        return (now + timedelta(seconds=ttl_seconds)).isoformat()

    # -- internals ------------------------------------------------------------------------------

    def _unit(
        self,
        row: Any,
        stage: str,
        submission: Any,
        criterion: Any,
        judge_id: str | None,
        origin: str = "base",
    ) -> tuple[str, dict[str, Any]]:
        """One computed unit: its `work_id` and its insert parameters.

        Kept beside `compute_work_id`'s call so the nine inputs' provenance is one
        glance: run and package from the run row, prompt template version from the
        frozen config, extractor version from the module constant, judge from the arm.

        `origin` names the unit's provenance — `'base'`, `'escalation'` or
        `'random_arm'` (`FR-ORCH-09/11`). It is deliberately **not** a `work_id` input:
        the id addresses the work (run, stage, submission, criterion, judge, versions,
        panel), and the origin says why that work exists. A base unit and a random-arm
        unit for the same (submission, criterion, judge) are the SAME work — one row,
        one lease, one verdict — and the origin column keeps the base row's provenance
        while the arm's extra judges carry the arm's mark. Consumers requiring the
        separation (`CT-ORCH-15`) read the arm's own units, never re-derive them.
        """
        work_id = compute_work_id(
            run_id=row["run_id"],
            stage=stage,
            submission_id=submission["submission_id"],
            criterion_id=criterion["criterion_id"],
            judge_id=judge_id,
            package_version_id=row["package_version_id"],
            panel_config=row["panel_config"],
            prompt_template_version=row["prompt_template_v"],
            extractor_version=EXTRACTOR_VERSION,
        )
        params = {
            "work_id": work_id,
            "submission_id": submission["submission_id"],
            "stage": stage,
            "run_id": row["run_id"],
            "criterion_id": criterion["criterion_id"],
            "judge_id": judge_id,
            "origin": origin,
        }
        return work_id, params

    def _unit_from_row(self, row: Any) -> WorkUnit:
        """The `WorkUnit` a claimed ledger row becomes when handed to a worker.

        The claim select carries `student_ref` (the identity the assembler needs) and
        aliases `attempts AS attempt` to the type's field; `student_name` and
        `submission_text` are `None` — the ledger holds neither, and their resolution
        is assembly's act (`M-EXTRACT`), not the lease's. The name-agnostic row reads
        keep the helper honest across the two selects that feed it.
        """
        keys = set(row.keys())
        return WorkUnit(
            work_id=row["work_id"],
            run_id=row["run_id"],
            stage=row["stage"],
            student_ref=row["student_ref"] if "student_ref" in keys else "",
            student_name=None,
            submission_id=row["submission_id"],
            criterion_id=row["criterion_id"],
            submission_text=None,
            judge=row["judge_id"],
            attempt=int(row["attempt"] if "attempt" in keys else row["attempts"]),
        )

    def _find_unit(self, work_id: str) -> tuple[Any, Any]:
        """(cohort handle, ledger row) for one work unit, by walking the cohort files.

        The same no-side-index discipline as `_run_row`: the ledger is its own
        directory, and a side index of work ids would be exactly the bookkeeping
        `FR-ORCH-02` forbids. A work id that resolves nowhere is a caller error worth
        naming — the same posture as `RunNotFoundError`.
        """
        for key in self._cohort_keys():
            cohort = self._store.cohort(key)
            rows = cohort.query(
                ORCH_STATEMENTS["select_work_unit_row"], work_id=work_id
            )
            if rows:
                return cohort, rows[0]
        raise WorkLedgerError(
            f"no work unit named {work_id[:12]}… exists in any cohort ledger. The id "
            "is the ledger's own content address; one that resolves to nothing was "
            "never enumerated (or names a run this store does not hold)."
        )

    def _cohort_keys(self) -> tuple[str, ...]:
        """The store's cohort tier keys, in sorted order — the discovery surface resume's
        no-argument form walks. Every key's file is opened and read; a cohort with no
        open runs costs one query."""
        return tuple(sorted(self._cohort_keys_for(self._store)))

    def _catalog(self, row: Any) -> PackageCatalogProtocol:
        """The package catalog for the run's version, opened on the version's Tier P
        database. Imported here, not at module top: `aeh.pkg` appends its own migrations
        to the Tier P registry on import, and the import order of the owning modules is
        each module's own concern — `test_migrations.py` imports them explicitly for the
        same reason.

        One catalog instance is held open per (package_id, package_version_id): the
        catalog's own cache is per instance (`NFR-PKG-05`), and the claim pass reads the
        version on every dispatch, so a fresh instance per read would reload the version
        per claim — the per-instance cache is the point of holding it open.
        """
        key = (row["package_id"], row["package_version_id"])
        catalog = self._catalogs.get(key)
        if catalog is None:
            from aeh.pkg import PackageCatalog

            catalog = PackageCatalog(
                self._store.package(row["package_id"]),
                package_id=row["package_id"],
            )
            self._catalogs[key] = catalog
        return catalog

    def _run_row(self, run_id: str) -> Any:
        """The run's ledger row, found by walking the cohort files.

        There is deliberately no index of run ids outside the ledger: the run row lives
        in its cohort's Tier C file (§9.6 puts run state beside cohort state), and a
        side index would be exactly the bookkeeping FR-ORCH-02 forbids. Cohort counts
        are small; a scan is a handful of indexed queries.
        """
        return self._find_run(run_id)[1]

    def _find_run(self, run_id: str) -> tuple[Any, Any]:
        """(cohort handle, run row) for one run — the lifecycle writers need both, and
        re-walking the cohorts to turn the row back into its handle would be the same
        scan twice. Same no-side-index rule as `_run_row`, which is this minus the
        handle."""
        for key in self._cohort_keys():
            cohort = self._store.cohort(key)
            rows = cohort.query(ORCH_STATEMENTS["select_run"], run_id=run_id)
            if rows:
                return cohort, rows[0]
        raise RunNotFoundError(
            f"no run row named {run_id!r} exists in any cohort ledger. resume() with "
            "no arguments finds its own runs; an explicit run_id that resolves to "
            "nothing is a caller error worth naming."
        )

    def _panel_arms(self, panel_config: str) -> tuple[str, ...]:
        """The panel's ordered judge ids, from the run row's canonical `panel_config`."""
        arms = json.loads(panel_config).get("arms")
        if not isinstance(arms, list) or not all(isinstance(a, str) for a in arms):
            raise WorkLedgerError(
                f"run row carries panel_config {panel_config!r}, which is not the "
                "canonical {\"arms\": [...]} form this module writes (panel_config_json)."
            )
        return tuple(arms)

    def _dropped_judges(self, run_row: Any) -> frozenset[str]:
        """The judges the OOM ladder dropped from this run's panel (`RES-13`), read
        from the run row itself: the arms the FROZEN `provider_config` snapshot named
        minus the arms the run's `panel_config` names now. The drop is durable in the
        run row — the remedy rewrote `panel_config` down to the smaller panel — so the
        skip this set drives survives a restart, where the in-memory dispatch state
        does not (#62 review: a fresh Orchestrator over the same store must skip the
        same units the recording one skipped; the dropped judges' un-run units stay
        pending for an operator to re-queue under the smaller panel). A judge the
        frozen panel never carried is not a drop: derived escalation arms
        (`escalation-arm-<k>`, `_extension_arms`) and explicitly-passed escalation
        judges are outside both panels, so they are never in this set. An unreadable
        frozen panel skips nothing — stranding units on an unreadable snapshot is the
        conservative side, and `_concurrency_ceiling` refuses malformed configs
        loudly beside this."""
        try:
            frozen = json.loads(run_row["provider_config"]).get("panel")
            current = set(self._panel_arms(run_row["panel_config"]))
        except (TypeError, ValueError, WorkLedgerError):
            return frozenset()
        if not isinstance(frozen, list):
            return frozenset()
        return frozenset(
            arm for arm in frozen if isinstance(arm, str) and arm not in current
        )

    def unit_status(self, work_id: str) -> str:
        """One unit's ledger status, or `""` if the ledger has no such unit.

        A stage executor needs it to tell "the worker did the work" from "the worker struck
        the unit out and the ledger already closed it". `complete()` refuses the second case
        and the refusal would surface as a composition fault, pausing a run over a single
        unparseable reply — so the executor asks first.
        """
        for key in self._cohort_keys():
            rows = self._store.cohort(key).query(
                ORCH_STATEMENTS["select_unit_status"], work_id=work_id)
            if rows:
                return str(rows[0]["status"])
        return ""

    def cohort_ref(self, cohort_id: str) -> "CohortRef":
        """The cohort's declared identity, as `M-CONF` wants it (`FR-CONF-08`, `ADR-5`).

        `CohortRef`'s `consent_class` defaults to `'real'`, deliberately: an undeclared cohort
        must fail closed against a remote backend. That makes the stored value something a
        caller has to READ rather than omit, and a composition layer cannot read it itself
        (`CT-PIPE-05`). So the owner answers, as it does for `run_handle`.

        An unknown cohort returns the fail-closed default rather than raising: the consent gate
        is the right place for that refusal, and it states the reason better than this would.
        """
        from aeh.conf import CohortRef

        for key in self._cohort_keys():
            rows = self._store.cohort(key).query(
                ORCH_STATEMENTS["select_cohort_row"], cohort_id=cohort_id)
            if rows:
                declared = str(rows[0]["consent_class"] or "real")
                return CohortRef(cohort_id=cohort_id, consent_class=declared)
        return CohortRef(cohort_id=cohort_id)

    def runs(self, statuses: Sequence[str] | None = None) -> tuple[RunHandle, ...]:
        """Every run the store holds, optionally filtered by status, in ledger order.

        `recover` (`FR-PIPE-07`) needs the runs that are COMPLETE but not fully graded, and
        `resume`'s discovery deliberately sees only open ones. A composition layer cannot walk
        the cohorts itself (`CT-PIPE-05`), so the owner answers — the same reasoning as
        `run_handle`, widened from one run to all of them.
        """
        wanted = None if statuses is None else {str(s) for s in statuses}
        found: list[RunHandle] = []
        for key in self._cohort_keys():
            cohort = self._store.cohort(key)
            for row in cohort.query(ORCH_STATEMENTS["select_all_runs"]):
                status = str(row["status"])
                if wanted is not None and status not in wanted:
                    continue
                found.append(RunHandle(
                    run_id=str(row["run_id"]),
                    cohort_id=str(row["cohort_id"]),
                    cohort=cohort,
                    package_id=str(row["package_id"]),
                    package_version_id=str(row["package_version_id"]),
                    status=status,
                    pause_reason=row["pause_reason"],
                    backend_profile=str(row["backend_profile"] or ""),
                    started_at=str(row["started_at"] or ""),
                ))
        return tuple(found)

    def submissions(self, run_id: str) -> tuple[str, ...]:
        """FR-ORCH-42 / CT-ORCH-32 (#523): every submission `run_id` enumerated, in
        enumeration order, whatever its criteria's evaluation modes — deterministic-only
        submissions included — and never another run's. Read-only. Raises
        `RunNotFoundError` for an unknown run."""
        cohort, _run_row = self._find_run(run_id)
        return tuple(str(row["submission_id"]) for row in cohort.query(
            ORCH_STATEMENTS["select_run_enumerated_submissions"], run_id=run_id))

    def _run_row_in(self, cohort: Any, run_id: str) -> Any:
        """The run's row from a cohort handle the caller already holds.

        Distinct from `_run_row(run_id)`, which WALKS the cohort files to find which one
        owns the run. Both flush and report already know the cohort, so re-walking would
        open every cohort file to answer a question the caller had answered."""
        rows = cohort.query(ORCH_STATEMENTS["select_run"], run_id=run_id)
        return rows[0] if rows else None

    def _wall_now(self) -> str:
        """The wall time this orchestrator writes and measures with (FR-ORCH-44)."""
        if self._wall_clock is None:
            return _now()
        return self._wall_clock().isoformat()
