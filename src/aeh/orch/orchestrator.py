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
    """Manages a grading run's work: creates the run, creates its work units, leases them to
    workers, widens judge panels, and moves the run through its states (§3.7).

    More detail: `docs/code-notes/orch.md`, section `orchestrator.py: Orchestrator`.
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
        """Clear the cached dispatch order for one run (NFR-ORCH-01).

        Any write that changes the claimable set — enumeration, a failure requeue, a
        sweeper reclaim — can falsify a cached order; the next claim pass re-reads
        instead of trusting it.
        """
        for key in [k for k in self._order_cache if k[0] == run_id]:
            del self._order_cache[key]

    # -- the lease (FR-ORCH-04) -----------------------------------------------------------------

    def _lease_clock(self) -> LeaseClock:
        """The store's always-increasing lease counter, driven by this orchestrator's clock.

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
        """The lease length in seconds, read from the environment each call."""
        return _env_int(LEASE_SECONDS_ENV, ORCH_LEASE_SECONDS)

    def _wall_expiry(self, clock: Any, ttl_seconds: int) -> str:
        """The lease expiry as a wall-clock time, for an operator reading the row.

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
        """Turn a claimed ledger row into the `WorkUnit` handed to a worker.

        The claim select carries `student_ref` (the identity the assembler needs) and
        aliases `attempts AS attempt` to the type's field; it also carries the roster
        display name as `student_name` (#593): the boundary at `M-JUDGE` replaces the
        name with the ref in every text field of the request, and it can only do that
        when the lease hands it one — the pre-#620 selects' rows read nameless and
        carry None. `submission_text` is still None: the ledger holds no text, and
        its resolution is assembly's act (`M-EXTRACT`), not the lease's. The
        name-agnostic row reads keep the helper honest across the selects that feed
        it (the estimate select deliberately projects no name: the cost seam never
        assembles a request).
        """
        keys = set(row.keys())
        return WorkUnit(
            work_id=row["work_id"],
            run_id=row["run_id"],
            stage=row["stage"],
            student_ref=row["student_ref"] if "student_ref" in keys else "",
            student_name=row["student_name"] if "student_name" in keys else None,
            submission_id=row["submission_id"],
            criterion_id=row["criterion_id"],
            submission_text=None,
            judge=row["judge_id"],
            attempt=int(row["attempt"] if "attempt" in keys else row["attempts"]),
        )

    def _find_unit(self, work_id: str) -> tuple[Any, Any]:
        """`(cohort handle, ledger row)` for one work unit, found by searching the cohort files.

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
        """The store's cohort file keys, sorted; `resume()` with no arguments searches these. Every
        file is opened; a cohort with no open runs costs one query."""
        return tuple(sorted(self._cohort_keys_for(self._store)))

    def _catalog(self, row: Any) -> PackageCatalogProtocol:
        """The package catalog for the run's version, opened on its Tier P database. `aeh.pkg` is
        imported here rather than at the top of the file, because importing it adds its migrations
        to the Tier P registry and each module manages its own import order.

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
        """The run's ledger row, found by searching the cohort files.

        There is deliberately no index of run ids outside the ledger: the run row lives
        in its cohort's Tier C file (§9.6 puts run state beside cohort state), and a
        side index would be exactly the bookkeeping FR-ORCH-02 forbids. Cohort counts
        are small; a scan is a handful of indexed queries.
        """
        return self._find_run(run_id)[1]

    def _find_run(self, run_id: str) -> tuple[Any, Any]:
        """`(cohort handle, run row)` for one run. The lifecycle methods need both, and finding the
        handle again from the row would repeat the search."""
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
        """The panel's judge ids in order, from the run's `panel_config`."""
        arms = json.loads(panel_config).get("arms")
        if not isinstance(arms, list) or not all(isinstance(a, str) for a in arms):
            raise WorkLedgerError(
                f"run row carries panel_config {panel_config!r}, which is not the "
                "canonical {\"arms\": [...]} form this module writes (panel_config_json)."
            )
        return tuple(arms)

    def _dropped_judges(self, run_row: Any) -> frozenset[str]:
        """The judges removed from this run's panel after running out of memory (RES-13): the
        judges in the frozen `provider_config` snapshot minus those in the current `panel_config`.

        Because this is read from the run row, a new Orchestrator after a restart skips the same
        units the old one did (#62). The dropped judges' unfinished units stay pending for an
        operator to re-queue. Escalation judges were never in either panel, so they never appear
        here. If the frozen panel cannot be read, nothing is skipped."""
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
        """One unit's ledger status, or `""` if there is no such unit.

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
        """The cohort's declared identity, in the form M-CONF needs (FR-CONF-08, ADR-5).

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
        """Every run in the store, optionally filtered by status, in ledger order.

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
        """Every submission enumerated for `run_id`, in enumeration order, including submissions
        whose criteria are all deterministic, and never another run's (FR-ORCH-42, CT-ORCH-32,
        #523). Read-only. Raises `RunNotFoundError` for an unknown run."""
        cohort, _run_row = self._find_run(run_id)
        return tuple(str(row["submission_id"]) for row in cohort.query(
            ORCH_STATEMENTS["select_run_enumerated_submissions"], run_id=run_id))

    def _run_row_in(self, cohort: Any, run_id: str) -> Any:
        """The run's row, from a cohort handle the caller already has.

        Distinct from `_run_row(run_id)`, which WALKS the cohort files to find which one
        owns the run. Both flush and report already know the cohort, so re-walking would
        open every cohort file to answer a question the caller had answered."""
        rows = cohort.query(ORCH_STATEMENTS["select_run"], run_id=run_id)
        return rows[0] if rows else None

    def _wall_now(self) -> str:
        """The current wall-clock time this orchestrator writes and measures with (FR-ORCH-44)."""
        if self._wall_clock is None:
            return _now()
        return self._wall_clock().isoformat()
