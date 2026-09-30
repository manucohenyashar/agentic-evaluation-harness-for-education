"""Leasing units in dependency order, heartbeats, the expiry sweep, completion and failure."""

from __future__ import annotations

import time
from collections import deque
from decimal import Decimal
from typing import Any, Sequence

from .constants import STAGE_EXTRACT, STAGE_SCORE
from .work_units import WorkUnit
from .errors import WorkLedgerError
from .statements import ORCH_STATEMENTS
from .settings import BACKEND_EDGE_LOCAL, _env_int, MAX_ATTEMPTS_ENV, ORCH_MAX_ATTEMPTS
from .escalation_policy import _dependency_closure, _known_key
from .reports import SweeperReport, SweepPlan, WorkError, WorkResult


class LeasingMixin:
    """Leases units to workers and records how each one ends."""

    def lease(self, worker_id: str, stage: str, n: int) -> Sequence[WorkUnit]:
        """Claim up to `n` pending units of one stage for `worker_id`. No other worker can claim
        them while the lease lasts.

        More detail: `docs/code-notes/orch.md`, section `leasing.py: LeasingMixin.lease`.
        """
        if n <= 0:
            raise WorkLedgerError(
                f"lease(n={n}) claims a positive number of units; {n} claims nothing, "
                "and a call that claims nothing while appearing to work is the "
                "silent-failure shape."
            )
        claimed = self._claim_pass(worker_id, stage, n)
        if not claimed:
            # **The no-bookkeeping rule applied to leasing** (`FR-ORCH-02`): a caller
            # that created a run and leases — without a separate enumerate step — must
            # not silently receive zero units because the base enumeration had not
            # been run. The fallback enumerates only runs whose ledger holds **no
            # units at all** (`_runs_missing_units`) — a run with rows was enumerated,
            # and an empty claim against it is a true empty (every unit done, in
            # flight, or the run not dispatching), not a bookkeeping gap. Re-
            # enumerating on every drained poll would make the hot path a full
            # enumeration pass late in a 23,000-unit run; the gate keeps it one claim
            # query and one existence probe. A ledger partially populated by a crash
            # mid-enumeration has rows and is `resume()`'s repair, not lease's.
            for open_run in self._runs_missing_units():
                self.enumerate_units(open_run)
            claimed = self._claim_pass(worker_id, stage, n)
        return tuple(self._unit_from_row(row) for row in claimed)

    def _claim_pass(self, worker_id: str, stage: str, n: int) -> list[Any]:
        """One claim pass over every cohort's open runs, taking up to `n` units.

        More detail: `docs/code-notes/orch.md`, section `leasing.py: LeasingMixin._claim_pass`.
        """
        ttl = self._lease_ttl()
        lease_clock_obj = self._lease_clock()
        claimed: list[Any] = []
        for key in self._cohort_keys():
            if len(claimed) >= n:
                break
            cohort = self._store.cohort(key)
            for run_row in cohort.query(ORCH_STATEMENTS["select_open_runs"]):
                if len(claimed) >= n:
                    break
                if run_row["status"] not in ("pending", "running"):
                    continue
                # **The control-row read** (`CT-ORCH-13`): the claim pass is the
                # orchestrator's own schedule's heartbeat, so this is where a control
                # row written while nobody was dispatching is honoured. A pause applied
                # here (a `running` run flips to `paused`) schedules nothing, exactly
                # like a pause sensed at the ceiling; a pause still queued on a
                # `pending` run gates dispatch below — a stop someone asked for is not
                # raced past, and `start` will honour it.
                status_now, queued_pause = self._apply_control_rows(
                    cohort, run_row["run_id"]
                )
                if (
                    status_now not in ("pending", "running")
                    or queued_pause is not None
                ):
                    continue
                # The **frozen ceiling** (`FR-ORCH-15`, `FR-CONF-07`): parsed once per
                # run per pass from the run row's `provider_config` — never from the
                # current environment. None means no ceiling: the seam is never
                # consulted and spend is never accrued for a run that froze no budget.
                ceiling = self._run_ceiling(run_row)
                # The **dropped judges** (`RES-13`): read from the run row itself,
                # once per run per pass — the frozen panel minus the recorded one.
                dropped_judges = self._dropped_judges(run_row)
                cache_key = (run_row["run_id"], stage)
                ordered = self._order_cache.get(cache_key)
                if ordered is None:
                    candidates = cohort.query(
                        ORCH_STATEMENTS["select_run_claimable"],
                        run_id=run_row["run_id"],
                        stage=stage,
                    )
                    if not candidates:
                        continue
                    ordered = deque(
                        self._dispatch_order(run_row, stage, candidates, cohort)
                    )
                    if not ordered:
                        # Every candidate was gated out (Sweep 2 waiting on
                        # extraction). Readiness only grows, but it grows outside
                        # this cache's view, so an empty order is re-derived per
                        # pass — caching it would starve the newly ready.
                        continue
                    self._order_cache[cache_key] = ordered
                # The budget's dispatch gate (`FR-ORCH-14`): read once per run per
                # pass — the observed rate moves only on completions, which happen
                # outside claim passes, so one admission decision covers the pass.
                escalation_admission: frozenset | None = None
                # The **dispatch state** (`#62`): the per-run governor, residency and
                # OOM bookkeeping, created lazily the first time any claim walk —
                # the dispatch pass's or a worker's — reaches the run. The residency
                # gate below is the only in-walk consumer; the dispatch pass's
                # counters and the completion report ride the same dict.
                edge_residency = (
                    stage == STAGE_SCORE
                    and run_row["backend_profile"] == BACKEND_EDGE_LOCAL
                )
                state = self._dispatch_state(run_row)
                residency = state["residency"]
                run_claims = 0
                while ordered and len(claimed) < n:
                    row = ordered.popleft()
                    if (
                        stage == STAGE_SCORE
                        and row["origin"] == "escalation"
                    ):
                        if escalation_admission is None:
                            escalation_admission = (
                                self._escalation_dispatch_admission(
                                    cohort, run_row["run_id"]
                                )
                            )
                        if (row["submission_id"], row["criterion_id"]) not in (
                            escalation_admission
                        ):
                            # Above budget, this pair's escalation is part of the
                            # provisional remainder: the unit stays pending — never
                            # claimed, never dropped — and the cache entry goes so
                            # the NEXT pass re-derives with the current rate. A
                            # deferral the cached order could not revisit would be
                            # a deferral that never lifts.
                            self._order_cache.pop(cache_key, None)
                            continue
                    if row["judge_id"] in dropped_judges:
                        # **A dropped judge's un-run units stay in the ledger**
                        # (`RES-13`): pending, never claimed, never discarded — for
                        # an operator to re-queue under the smaller panel. The skip
                        # reads the run row's OWN panels (frozen minus recorded,
                        # `_dropped_judges`), so it is durable: a fresh
                        # Orchestrator over the same store skips the same units the
                        # recording one did, where an in-memory dropped set would
                        # have re-dispatched them after a restart (#62 review
                        # finding 1). Extract and deterministic rows carry a null
                        # judge, which no drop set contains.
                        continue
                    if edge_residency:
                        # **The residency boundary** (`FR-ORCH-19`). On an edge-local
                        # run the box holds ONE judge model resident, so a score
                        # handout never mixes models. The gate reads the walk's own
                        # judge-major order: crossing into a judge that is not the
                        # resident one is the unload/load boundary, and it is legal
                        # only when the resident's **batch** is finished — no more
                        # dispatchable work this walk (`run_claims == 0`: the ready
                        # order held nothing more for it) and none of its units in
                        # flight. Gated or budget-deferred pending units are not
                        # dispatchable — they are not in this order and may never
                        # become ready without an operator — so they cannot hold a
                        # model resident; a residency held over undispatchable work
                        # starves every other judge behind it (their handouts refuse
                        # empty while the ledger still holds claimable units, the
                        # stall shape). When gated work does become ready, the walk
                        # reaches the resident again and the model reloads — a swap —
                        # to serve it. The FIRST model of a run loads without a
                        # swap: there is nothing to unload yet.
                        resident = residency["resident"]
                        if resident in dropped_judges:
                            # The OOM remedy unloaded this judge (`RES-13`): it is
                            # out of the panel, so the next model loads as an
                            # initial load — the drop already paid the unload.
                            residency["resident"] = None
                            resident = None
                        if row["judge_id"] != resident:
                            if resident is None:
                                residency["resident"] = row["judge_id"]
                            elif (
                                run_claims == 0
                                and not cohort.query(
                                    ORCH_STATEMENTS["select_judge_leased_units"],
                                    run_id=run_row["run_id"],
                                    judge_id=resident,
                                )[0]["n"]
                            ):
                                # A clean boundary: nothing claimed yet this walk
                                # and the resident's work is finished — record the
                                # swap and load the next model in place. The swap's
                                # duration is the wall time to the batch's first
                                # model call (the load rides that call), timed
                                # from here by the dispatch pass.
                                residency["swaps"] += 1
                                residency["swap_started"] = time.monotonic()
                                residency["resident"] = row["judge_id"]
                            else:
                                # Mid-batch crossing (this pass already claimed
                                # the resident's tail) or the resident still holds
                                # open work: the boundary row goes back and the
                                # walk stops — this handout stays single-model,
                                # and the next pass re-derives from the ledger.
                                ordered.appendleft(row)
                                self._order_cache.pop(cache_key, None)
                                break
                    # The **measured figure** (`FR-ORCH-15`, `FR-PROV-12/04`): before
                    # the claim, this unit's cost comes from the provider seam — the
                    # same measured protocol the run is billed against, never an
                    # estimated optimism. Outside the transaction: the seam may be a
                    # real transport, and no egress belongs inside a ledger write.
                    figure: Decimal | None = None
                    if ceiling is not None:
                        figure = self._cost_figure(cohort, row, ceiling)
                    issued = lease_clock_obj.issue(ttl)
                    expires_at = self._wall_expiry(lease_clock_obj.clock, ttl)
                    refused = False
                    at_ceiling = False
                    won = False
                    with cohort.transaction() as tx:
                        if figure is not None:
                            spend = Decimal(
                                tx.execute(
                                    ORCH_STATEMENTS["select_run"],
                                    run_id=row["run_id"],
                                )[0]["cost_spend"]
                                or "0"
                            )
                            if spend + figure > ceiling:
                                # **The crossing dispatch is refused** (strict `>`,
                                # the breaker's and budget's reading): the unit stays
                                # pending — never claimed, never dropped — and the run
                                # pauses **in this transaction**, naming the spend and
                                # the remaining unit count (`FR-ORCH-15`'s operator
                                # surface; `CT-ORCH-12`'s ceiling condition). A pause
                                # that said only THAT it stopped could not be told
                                # from a crash.
                                remaining = tx.execute(
                                    ORCH_STATEMENTS["count_run_pending"],
                                    run_id=row["run_id"],
                                )[0]["n"]
                                tx.execute(
                                    ORCH_STATEMENTS["pause_run_sensed"],
                                    run_id=row["run_id"],
                                    pause_reason=(
                                        f"cost ceiling reached: spend "
                                        f"{spend} of ceiling {ceiling}; next "
                                        f"dispatch would reach {spend + figure}; "
                                        f"{remaining} unit(s) remaining"
                                    ),
                                )
                                refused = True
                        if not refused:
                            tx.execute(
                                ORCH_STATEMENTS["mark_leased"],
                                work_id=row["work_id"],
                                owner=worker_id,
                                expires_ticks=issued.expires_ticks,
                                expires_at=expires_at,
                            )
                            won = int(
                                tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"]
                            )
                            if won and figure is not None:
                                # The accrual rides the **same transaction** as the
                                # claim (`FR-ORCH-15`): spend and the unit's lease
                                # commit together, so no crash between them can
                                # dispatch work the ceiling never saw, and no accrual
                                # can outlive a claim that lost its guard.
                                new_spend = spend + figure
                                tx.execute(
                                    ORCH_STATEMENTS["accrue_run_spend"],
                                    run_id=row["run_id"],
                                    cost_spend=str(new_spend),
                                )
                                if figure > 0 and new_spend >= ceiling:
                                    # Spend now sits **at** the ceiling: the run
                                    # pauses in the same transaction — the dispatch
                                    # that landed it there proceeded (strict `>`), and
                                    # the next BILLED one would cross. A not-billed
                                    # figure (`None` → 0) adds nothing and consumes no
                                    # ceiling — that is how replayed work passes a
                                    # ceiling honestly (`_normalize_figure`) — so a
                                    # zero accrual must not re-fire this arm: a
                                    # resumed ceiling-paused run would otherwise
                                    # re-pause on every replay claim, one operator
                                    # resume per unit, never draining. The refusal
                                    # arm above already covers any future crossing
                                    # dispatch, billed or not.
                                    remaining = tx.execute(
                                        ORCH_STATEMENTS["count_run_pending"],
                                        run_id=row["run_id"],
                                    )[0]["n"]
                                    tx.execute(
                                        ORCH_STATEMENTS["pause_run_sensed"],
                                        run_id=row["run_id"],
                                        pause_reason=(
                                            f"cost ceiling reached: spend "
                                            f"{new_spend} of ceiling {ceiling}; "
                                            f"{remaining} unit(s) remaining"
                                        ),
                                    )
                                    at_ceiling = True
                    if won:
                        claimed.append(row)
                        run_claims += 1
                    if refused or at_ceiling or not won:
                        # The run paused mid-order (sensed ceiling) or the guarded
                        # write lost (stale view): drop the entry wholesale — the next
                        # pass re-derives from the ledger, which now holds the pause.
                        self._order_cache.pop(cache_key, None)
                        break
                if not ordered:
                    # Exhausted: the remaining candidates were all claimed. Drop the
                    # entry so the next pass re-reads — new units (enumeration, the
                    # sweeper's requeue) can only be discovered from the ledger.
                    self._order_cache.pop(cache_key, None)
        return claimed

    def _dispatch_order(
        self, run_row: Any, stage: str, rows: Sequence[Any], cohort: Any
    ) -> list[Any]:
        """One run's candidate units for a stage, in the order they may be handed out.

        More detail: `docs/code-notes/orch.md`, section `leasing.py: LeasingMixin._dispatch_order`.
        """
        if stage not in (STAGE_EXTRACT, STAGE_SCORE):
            return list(rows)
        plan = self._sweep_plan(run_row)
        if stage == STAGE_EXTRACT:
            return sorted(
                rows,
                key=lambda r: (
                    _known_key(plan.extract_positions.get(r["criterion_id"])),
                    r["criterion_id"] or "",
                    r["work_id"],
                ),
            )
        blocked = {
            (r["criterion_id"], r["submission_id"])
            for r in cohort.query(
                ORCH_STATEMENTS["select_not_done_extracts"],
                run_id=run_row["run_id"],
            )
        }
        arms = self._panel_arms(run_row["panel_config"])
        # `FR-ORCH-30`: with an executor bound — a run driven by `M-PIPE` — a score unit also
        # waits for its cell's `integrity_pre` phase, so no panel scores a cell whose
        # extraction the integrity gate has not passed on. ONLY with an executor bound: the
        # report-only path and the `transport=` test path record no phases, and gating them
        # would make every score unit unclaimable forever.
        gated = (
            self._cells_with_integrity_pre(cohort, run_row["run_id"])
            if self._executor is not None
            else None
        )
        ready = [
            r for r in rows
            if self._score_dependencies_done(r, blocked, plan)
            and (gated is None
                 or (str(r["submission_id"]), str(r["criterion_id"])) in gated)
        ]
        return sorted(
            ready,
            key=lambda r: (
                self._judge_key(r["judge_id"], arms),
                _known_key(plan.question_of.get(r["criterion_id"])),
                r["criterion_id"] or "",
                r["work_id"],
            ),
        )

    @staticmethod
    def _score_dependencies_done(
        row: Any, blocked: set[tuple[str, str]], plan: SweepPlan
    ) -> bool:
        """Whether all of one score unit's extraction units are `done` (FR-ORCH-06)."""
        if (row["criterion_id"], row["submission_id"]) in blocked:
            return False
        closure = plan.dependency_closure.get(row["criterion_id"], frozenset())
        return all(
            (dep, row["submission_id"]) not in blocked for dep in closure
        )

    @staticmethod
    def _judge_key(judge_id: str | None, arms: Sequence[str]) -> tuple[int, int | str]:
        """The first sort key of FR-ORCH-07: the judge's position in the run's panel.

        Panel order, not the build id's lexical order — the panel order is the dispatch
        order and the escalation ladder's first arm (`panel_config_json`), and the fixed
        cross-profile key reads the same on every backend (`TC-ORCH-08`'s arm-index
        oracle). A judge outside the panel (later stories' escalation arms) sorts after
        every panel judge, deterministically. A score unit without a judge is a ledger
        this module did not write, and ordering it anywhere would dispatch judgeless
        work to a judge — refused, not absorbed.
        """
        if judge_id is None:
            raise WorkLedgerError(
                "a 'score' unit without a judge reached the dispatch order — the base "
                "enumeration gives every score unit a panel arm, so the row is not this "
                "module's. Order it by hand only after deciding what judgeless scoring "
                "means; the orchestrator refuses to guess."
            )
        # The index compares as the **integer** it is, never stringified: at ten or
        # more arms a lexical compare would order `arm-10` before `arm-2` and break
        # the panel's own ladder. The two branches never compare second elements
        # across the branch boundary — the leading 0/1 decides first — so an
        # in-panel int and an out-of-panel str can never meet in a comparison.
        return (0, arms.index(judge_id)) if judge_id in arms else (1, judge_id)

    def _sweep_plan(self, run_row: Any) -> SweepPlan:
        """The ordering data for the run's package version, computed once.

        Pure functions of the immutable version: the topological order comes from
        `M-PKG` (`FR-PKG-05`, consumed rather than re-derived), the question map from the
        version's criteria, the closure from the version's dependency graph. Cached per
        version on the orchestrator, so a claim pass pays the derivation once per run
        lifetime, never per unit (`NFR-ORCH-01`).
        """
        version = run_row["package_version_id"]
        plan = self._sweep_plans.get(version)
        if plan is None:
            catalog = self._catalog(run_row)
            order = catalog.topological_order(version)
            positions = {criterion_id: i for i, criterion_id in enumerate(order)}
            question_of = {
                c["criterion_id"]: c["question_id"]
                for c in catalog.criteria(version)
            }
            plan = SweepPlan(
                extract_positions=positions,
                question_of=question_of,
                dependency_closure=_dependency_closure(
                    catalog.dependency_graph(version)
                ),
            )
            self._sweep_plans[version] = plan
        return plan

    def heartbeat(self, work_id: str, owner: str | None = None) -> None:
        """Extend a live lease by another TTL while the worker is still working (FR-ORCH-04).

        A slow-but-alive worker must not lose its unit at the original expiry: the
        heartbeat re-issues the lease from **now**, so the expiry moves out by a full
        TTL from the moment of the call. The re-issue goes through `LeaseClock.issue()`
        like every claim, so the persisted counter moves with it and the extension
        survives an uncontrolled kill.

        `owner` names the calling worker and is checked against `lease_owner` — a
        heartbeat naming its worker cannot extend a lease another worker holds, which
        is the double-run `CT-ORCH-04` warns of from the other side. Unnamed
        heartbeats (the assumed test surface) extend whoever holds the lease; passing
        the worker id is the recommended form and the only one a multi-worker ledger
        should rely on.

        Refusals are named, never absorbed: a unit that is not `leased` (the sweeper
        requeued it, another worker completed it), is held by a different named worker,
        or does not exist raises `WorkLedgerError` — and the guard's `changes()` read
        catches the race where the lease was lost **between** the read and the write,
        so a heartbeat cannot succeed without having extended anything.
        """
        ttl = self._lease_ttl()
        lease_clock_obj = self._lease_clock()
        issued = lease_clock_obj.issue(ttl)
        expires_at = self._wall_expiry(lease_clock_obj.clock, ttl)
        cohort, row = self._find_unit(work_id)
        if row["status"] != "leased":
            raise WorkLedgerError(
                f"heartbeat for unit {work_id[:12]} refused: the unit is "
                f"'{row['status']}', not 'leased' — the lease was lost while this "
                "worker held it, and extending a lease that returned to pending would "
                "double-claim work another worker may already hold."
            )
        if owner is not None and row["lease_owner"] != owner:
            raise WorkLedgerError(
                f"heartbeat for unit {work_id[:12]} refused: 'lease_owner' names "
                f"{row['lease_owner']!r}, not {owner!r} — extending another worker's "
                "live lease would let two workers run one unit."
            )
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["extend_lease"],
                work_id=work_id,
                owner=owner,
                expires_ticks=issued.expires_ticks,
                expires_at=expires_at,
            )
            won = int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"])
        if not won:
            raise WorkLedgerError(
                f"heartbeat for unit {work_id[:12]} could not be applied: the lease "
                f"was lost between the read ('{row['status']}') and the write — the "
                "sweeper requeued it or the unit moved underneath this worker. "
                "Re-lease before continuing; a heartbeat that succeeds without "
                "extending anything is the silent no-op this method exists to refuse."
            )

    def sweep_expired_leases(self) -> SweeperReport:
        """Return every expired lease to `pending`, and report what was done.

        The comparison is `ticks >= lease_expires_ticks` on the store's **monotonic
        counter** — the same inequality `LeaseClock.expired()` states — and never the
        wall clock (`FR-STORE-11`): the host clock moving backwards across a restart
        changes nothing the sweeper reads. A leased row carrying no expiry is a ledger
        that cannot be swept honestly, so it raises rather than being skipped or
        treated as expired — both arms of that guess would be silent-failure shapes.

        Requeued units clear their lease columns and keep their `attempts`: the failure
        history belongs to the unit, the lease to the moment. The report is the sweep's
        stage-level detail (`CLAUDE.md` seam 4) — examined, requeued, still held — so a
        sweep over an empty ledger is visible as zero, not as absence.
        """
        lease_clock_obj = self._lease_clock()
        now_ticks = lease_clock_obj.ticks()
        gates: dict[str, str] = {
            "lease_clock": f"monotonic ticks at sweep: {now_ticks:.3f} (FR-STORE-11)",
        }
        examined = 0
        requeued = 0
        requeued_runs: set[str] = set()
        for key in self._cohort_keys():
            cohort = self._store.cohort(key)
            rows = cohort.query(ORCH_STATEMENTS["select_leased_units"])
            run_by_work = {row["work_id"]: row["run_id"] for row in rows}
            expired: list[str] = []
            for row in rows:
                ticks = row["lease_expires_ticks"]
                if ticks is None:
                    raise WorkLedgerError(
                        f"leased unit {row['work_id'][:12]} carries no expiry ticks, "
                        "so the sweeper can neither hold nor reclaim it honestly — "
                        "a lease is written with its expiry or not at all."
                    )
                if now_ticks >= float(ticks):
                    expired.append(row["work_id"])
            if expired:
                with cohort.transaction() as tx:
                    for work_id in expired:
                        tx.execute(
                            ORCH_STATEMENTS["requeue_expired"], work_id=work_id
                        )
                        won = int(
                            tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"]
                        )
                        requeued += won
                        if won:
                            requeued_runs.add(run_by_work[work_id])
            examined += len(rows)
        # A reclaim returns units to `pending` — drop the affected runs' dispatch-order
        # cache entries so the next claim pass sees them (the same visibility rule as
        # `fail`'s requeue, `TC-ORCH-18`).
        for run_id in requeued_runs:
            self._invalidate_order_cache(run_id)
        gates["sweep"] = (
            f"{examined} leased examined, {requeued} requeued, "
            f"{examined - requeued} still held"
        )
        return SweeperReport(
            examined=examined,
            requeued=requeued,
            still_held=examined - requeued,
            gates=gates,
        )

    # -- the failure taxonomy (FR-ORCH-18) ------------------------------------------------------

    def complete(self, work_id: str, result: WorkResult | None = None) -> None:
        """Record that a unit finished: `leased` becomes `done`, and the lease columns are cleared.

        Idempotent (`CT-ORCH-03`): a completion recorded twice leaves one `done` row.
        A completion arriving after the sweeper requeued the unit still lands —
        at-least-once leasing means a reclaim may double-run a unit, and the worker
        that actually finished is recording a real result; the second worker's own
        completion is then the no-op. A completion for a `quarantined` unit is refused
        with a named error: three failures were recorded, and quietly accepting a
        result underneath that record would un-quarantine by side effect — the
        operator surface said what happened, and it must stay true. The guard's
        `changes()` read catches the race where the unit was quarantined **between**
        the read and the write — the silent version of the same refusal. `result` is
        the worker's `WorkResult`; the ledger records the transition, the payload is
        the owning stage's to persist (#68 onward).
        """
        cohort, row = self._find_unit(work_id)
        if row["status"] == "done":
            return
        if row["status"] not in ("leased", "pending"):
            raise WorkLedgerError(
                f"completion for unit {work_id[:12]} refused: the unit is "
                f"'{row['status']}' — a quarantined unit keeps its record until an "
                "operator re-queues it; a result does not arrive underneath it."
            )
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["mark_done"],
                work_id=work_id,
                done_ticks=self._lease_clock().ticks(),
            )
            won = int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"])
        if not won:
            raise WorkLedgerError(
                f"completion for unit {work_id[:12]} could not be recorded: the "
                f"unit's state moved from '{row['status']}' between the read and the "
                "write — a failure report quarantined it mid-flight. The ledger's "
                "record stands; re-read it before reporting again."
            )
        # The last open unit closed — probe the run (`FR-ORCH-25`'s running → complete;
        # the probe is self-guarding and a no-op unless this really was the last).
        self._maybe_complete_run(cohort, row["run_id"])

    def fail(self, work_id: str, error: WorkError | str) -> None:
        """Record one failed attempt: put the unit back in the queue, or quarantine it once it
        reaches the retry limit (FR-ORCH-18).

        More detail: `docs/code-notes/orch.md`, section `leasing.py: LeasingMixin.fail`.
        """
        max_attempts = _env_int(MAX_ATTEMPTS_ENV, ORCH_MAX_ATTEMPTS)
        message = error.message if isinstance(error, WorkError) else str(error)
        cohort, row = self._find_unit(work_id)
        if row["status"] in ("quarantined", "done"):
            return
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["record_failure"],
                work_id=work_id,
                max_attempts=max_attempts,
                last_error=message,
            )
            won = int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"])
        if not won:
            # The unit moved underneath the report (reclaimed, completed, quarantined
            # by a concurrent holder). The ledger's state at write time wins; raising
            # here would fail a run over a unit-level race, which is the one thing
            # this taxonomy refuses to do (NFR-ORCH-03).
            return
        # A won report moved the unit within the claimable set — back to `pending`
        # below the ceiling, out of it at quarantine — so this run's cached dispatch
        # order is stale: the requeued unit must be visible to the very next claim
        # pass, or a requeue the dispatcher cannot see is a unit lost to the run
        # (`TC-ORCH-18`).
        self._invalidate_order_cache(row["run_id"])
        # Quarantine can close a run: a unit at its attempt ceiling leaves the open
        # set (its record stands), and if it was the last open one the run is complete
        # (`FR-ORCH-25`; the probe is self-guarding).
        self._maybe_complete_run(cohort, row["run_id"])

    def _requeue_units(
        self, cohort: Any, run_id: str, work_ids: Sequence[str]
    ) -> None:
        """Put units back to `pending` without counting an attempt or recording an error.

        The transport-condition requeue (rate limit, OOM — `RES-11`, `RES-13`): the
        unit's failure history is not the provider's or the box's to write, and an
        attempt consumed here would quarantine a whole cohort under a sustained 429 —
        the exact failure `RES-11` forbids. One transaction, one guarded write per
        unit (the sweeper's own shape), and the order cache drops so the very next
        claim pass sees the requeued units (`TC-ORCH-18`).
        """
        requeued = 0
        with cohort.transaction() as tx:
            for work_id in work_ids:
                tx.execute(ORCH_STATEMENTS["requeue_expired"], work_id=work_id)
                requeued += int(
                    tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"]
                )
        if requeued:
            self._invalidate_order_cache(run_id)
