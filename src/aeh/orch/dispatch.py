"""The dispatch pass: claim a batch, call the model within the run's limits, absorb results."""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any, Sequence

from aeh.prov import BuildChangedError, ProviderUnavailableError, RateLimitedError
from aeh.store import store_metrics

from .constants import _JSON_SEPARATORS, STAGE_DETERMINISTIC, STAGE_EXTRACT, STAGE_SCORE
from .errors import WorkLedgerError
from .statements import ORCH_STATEMENTS
from .settings import (
    BACKPRESSURE_DIVISOR_DEFAULT,
    BACKPRESSURE_DIVISOR_ENV,
    CONCURRENCY_REDUCTION_DEFAULT,
    CONCURRENCY_REDUCTION_ENV,
    DISPATCH_OWNER,
    DISPATCH_WALK_BATCH_DEFAULT,
    DISPATCH_WALK_BATCH_ENV,
    _env_int,
    OOM_DROP_THRESHOLD_DEFAULT,
    OOM_DROP_THRESHOLD_ENV,
)
from .reports import ProgressReport
from .executors import (
    _accrue_completion,
    GovernedProvider,
    _PreparedExecutor,
    StageOutcome,
    TransportStageExecutor,
)


class DispatchMixin:
    """Runs dispatch passes: claims batches and calls the model within the run's limits."""

    # -- the dispatch loop, residency, concurrency and the report (#62) --------------------------

    def progress(self, run_id: str) -> ProgressReport:
        """One dispatch pass over `run_id`, then the run-state report (`FR-ORCH-23`).

        **The two modes.** With a transport bound (`Orchestrator(store, transport=...)`)
        the pass dispatches: the extraction walk sends its assembled `ExtractionRequest`
        through the model-call seam, the deterministic walk completes its ledger
        transition directly (no model call exists for it), one judged batch at the
        governor's effective concurrency runs
        through the model-call seam as assembled `ScoringRequest`s, and the run's
        metrics flush to `run_metrics`
        (`CT-ORCH-20`). With no transport the call is the **report-only surface** — the
        (`CT-ORCH-20`). With no transport the call is the **report-only surface** — the
        console's poll (`CT-CONSOLE-01`'s headless driver needs progress to work with no
        console and no provider): the ledger is read and the report built, and nothing
        is claimed, called or flushed.

        **The pass drives the shared worker surface.** The walks and the judged batch
        claim through `lease()` under `DISPATCH_OWNER` — the dispatch loop is a lease
        holder like any worker, at-least-once and sweepable, so an interrupted pass's
        in-flight units are the sweeper's ordinary reclaim, never a special case. The
        claim pass walks the store's open runs (`#59`'s shape), so a poll nominally for
        `run_id` serves whichever open run the walk reaches first; the single-run store
        every dispatch case runs against makes the distinction invisible, and a
        multi-run operator gets run-id-order service from the walk itself — recorded
        interpretation, reconciled if a case ever pins multi-run dispatch.

        progress() never raises for an expected provider condition: a rate limit or an
        OOM is absorbed into the governor and the report (`RES-11`, `RES-13` —
        "expected, not an error"). A failure that is not one of the taxonomy's two
        transport conditions propagates: an unexpected exception mid-dispatch is a
        defect, and absorbing it would be the silent-failure shape.
        """
        cohort, run_row = self._find_run(run_id)
        state: dict[str, Any] | None = None
        if self._dispatches():
            state = self._dispatch_state(run_row)
            self._dispatch_pass(cohort, run_row, state)
        report = self._progress_report(cohort, run_row, run_id, state)
        if state is not None:
            self._flush_run_metrics(cohort, run_id, state, report)
        return report

    def _concurrency_ceiling(self, run_row: Any) -> int:
        """The concurrency ceiling the run **froze** at creation (`FR-ORCH-21`).

        Read from the run row's frozen `provider_config` — never from the current
        environment (`FR-CONF-07`'s freeze, the same discipline `_run_ceiling` states
        for the cost ceiling: a concurrency ceiling changed mid-run is a ceiling the
        operator never approved). A row whose frozen config carries no readable
        ceiling refuses loudly: a dispatch that guessed a width would be a dispatch
        nobody bounded.
        """
        raw = run_row["provider_config"]
        try:
            cfg = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise WorkLedgerError(
                f"run {run_row['run_id'][:12]} carries malformed provider_config — "
                "the frozen concurrency ceiling cannot be read, and an unreadable "
                "ceiling must halt dispatch loudly rather than guess a width."
            ) from exc
        value = cfg.get("concurrency_ceiling") if isinstance(cfg, dict) else None
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise WorkLedgerError(
                f"run {run_row['run_id'][:12]} froze a concurrency ceiling of "
                f"{value!r} — refused: the ceiling bounds how many model calls run "
                "at once, and a non-positive or non-integer one is not a bound."
            )
        return value

    def _dispatch_state(self, run_row: Any) -> dict[str, Any]:
        """The per-run dispatch state, created lazily and rebuilt-free thereafter.

        Holds the governor's cap (starting at the frozen ceiling, `FR-CONF-07`), the
        residency state (`FR-ORCH-19`), the per-judge OOM counts (`RES-13`), the
        provider counters the metrics flush persists (`CT-ORCH-20`, `CT-PROV-11`) and
        the pass's timing anchors. The OOM drop's skip is NOT here: it reads the run
        row's own panels (`_dropped_judges`) so it survives a restart. Kept per run —
        not per pass — so
        the counters a report reads are the run's own cumulative truth, and the
        governor's reduction survives between passes. An in-memory dict on a module
        whose bookkeeping rule is the ledger (`FR-ORCH-02`) is a deliberate exception:
        these are the OBSERVABILITY accumulators, not the work state — the work lives
        in `work_unit` rows, and a restart re-derives nothing but fresh counters.
        """
        run_id = run_row["run_id"]
        state = self._dispatch_states.get(run_id)
        if state is None:
            state = {
                "cap": self._concurrency_ceiling(run_row),
                "residency": {
                    "resident": None,
                    "swaps": 0,
                    "swap_ms": 0.0,
                    "swap_started": None,
                },
                "oom_counts": {},
                "rate_limited_calls": 0,
                "transport_retries": 0,
                "rate_limit_wait_s": 0.0,
                "tokens_in": 0,
                "tokens_out": 0,
                "cache_tokens": 0,
                "cost": Decimal("0"),
                "resolved_build": None,
                "calls": 0,
                "peak_concurrency": 0,
                "in_flight_calls": 0,
                "reduced_this_pass": False,
                "lock": threading.Lock(),
            }
            self._dispatch_states[run_id] = state
        return state

    def _dispatch_pass(
        self, cohort: Any, run_row: Any, state: dict[str, Any]
    ) -> None:
        """One dispatch pass: the walks, then one judged batch, at the effective cap.

        **The governor** (`FR-ORCH-21`). The pass runs at the state's cap — starting
        at the run's frozen ceiling, never the environment's — reduced once per pass
        on the first rate-limited or OOM call (floor 1; applied the moment the signal
        lands, so the report this pass returns carries the reduced width) and clamped
        while `M-STORE` signals write backpressure (`CT-STORE-06`: a signal to reduce,
        never a fault — sensed per pass, never persisted, so a store that recovers is
        a dispatch that resumes full width).

        **The walks** (`#62`'s interpretation, recorded on the class): scoring gates on
        the extraction transition, so the pass completes extract units — through the
        seam, because extraction IS a model call: the assembled `ExtractionRequest`
        (`M-EXTRACT`'s `assemble_request`) goes over the wire and a transport that
        rate-limits rate-limits it too — bounded by
        `HARNESS_ORCH_DISPATCH_WALK_BATCH`; the deterministic walk completes its units
        directly (deterministic evaluation makes no model call), then the pass claims
        one judged batch of at most the effective cap. Residency shapes the judged
        batch from inside the claim
        walk (`_claim_pass`'s gate) — the pass itself is residency-blind.
        """
        state["reduced_this_pass"] = False
        effective = state["cap"]
        if store_metrics(self._store).get("backpressure_active"):
            effective = max(
                effective
                // _env_int(BACKPRESSURE_DIVISOR_ENV, BACKPRESSURE_DIVISOR_DEFAULT),
                1,
            )
        walk_batch = _env_int(DISPATCH_WALK_BATCH_ENV, DISPATCH_WALK_BATCH_DEFAULT)
        completed_total = 0
        while completed_total < walk_batch:
            batch = list(
                self.lease(
                    DISPATCH_OWNER,
                    STAGE_EXTRACT,
                    min(walk_batch - completed_total, effective),
                )
            )
            if not batch:
                break
            completed = self._run_model_batch(
                cohort, run_row, state, batch, effective
            )
            completed_total += completed
            if completed == 0:
                # The pass made no headway: every claim came back
                # transport-blocked (rate-limited or OOM) and requeued. Claiming
                # again would re-run the same blocked batch until the walk
                # bound — the back-off is the reduction and the NEXT pass.
                break
        # The deterministic walk completes DIRECTLY (`#62`'s assembled-request
        # reconciliation): a deterministic criterion's evaluation makes no model
        # call (`TC-ORCH-10`'s shape — the unit carries a null judge and there is
        # no request schema for it to assemble), so there is nothing to send
        # across the transport and nothing a rate-limited provider could block —
        # the ledger transition IS the stage's dispatch, the way the extraction
        # payload is the owning stage's to persist (#68 onward).
        for unit in self.lease(DISPATCH_OWNER, STAGE_DETERMINISTIC, walk_batch):
            self.complete(unit.work_id)
        judged = list(self.lease(DISPATCH_OWNER, STAGE_SCORE, effective))
        self._run_model_batch(cohort, run_row, state, judged, effective)

    def _assemble_dispatch_payload(self, unit: Any) -> Any:
        """Assemble the closed per-stage request the dispatch sends (`FR-ORCH-20`).

        What crosses the model-call boundary is the ASSEMBLED request, never the
        ledger row: "the module shall dispatch exactly one submission per scoring or
        extraction request" (`FR-ORCH-20`), and the exactly-one form is assertable
        only over the closed schema (`CT-JUDGE-02`). The assembler is the OWNING
        stage's shipped door — `M-JUDGE`'s `ScoringWorker.assemble` for score units,
        `M-EXTRACT`'s `assemble_request` for extract units — invoked with the store
        so the words resolve here (the lease resolved the identity). The imports are
        deferred because the owning modules import this one (the registry's
        contributor graph has `aeh.orch` as an ancestor, not a leaf).

        Deterministic units never reach the seam (no model call exists — the
        deterministic walk completes them directly), so no schema is invented here
        for one: a stage without a request schema reaching this helper is a dispatch
        defect, not a payload to fabricate.
        """
        if unit.stage == STAGE_SCORE:
            from aeh.judge import ScoringWorker

            return ScoringWorker(store=self._store).assemble(unit)
        if unit.stage == STAGE_EXTRACT:
            from aeh.extract import assemble_request

            return assemble_request(unit, store=self._store)
        raise ValueError(
            f"unit {unit.work_id[:12]} carries stage {unit.stage!r}, which makes no "
            f"model call — only extract and score units cross the transport seam; "
            f"deterministic units complete directly"
        )

    # -- #362: the stage-executor seam, cell phases and readiness (FR-ORCH-27/28/29/30) --------

    def _dispatches(self) -> bool:
        """Whether this orchestrator dispatches model work at all.

        `None` on both seams is the report-only surface (the console's poll): it reads the
        ledger and claims nothing, which is why `progress()` must not build a dispatch state
        for it."""
        return self._executor is not None or self._transport is not None

    def _stage_executor(self, state: dict[str, Any]) -> Any:
        """The executor this pass dispatches through — the bound one, or the transport
        adapted to the same protocol so the loop has a single path."""
        if self._executor is not None:
            return _PreparedExecutor(self._executor)
        payloads: dict[str, Any] = {}
        return _PreparedExecutor(
            TransportStageExecutor(self._transport, payloads, state),
            prepare=self._assemble_dispatch_payload,
            payloads=payloads,
        )

    def governed_provider(self, run_id: str, provider: Any = None) -> GovernedProvider:
        """The run's provider with the run's dispatch counters wrapped around it (#596).

        For model calls a composition layer makes outside a dispatch pass, synthesis being
        the one today: ADR-14 and CT-PIPE-06 put EVERY model call through the governed
        provider, so the calls accrue to the same per-run counters a dispatch pass reads and
        persists (`CT-PROV-11`). `provider` defaults to the one this orchestrator was bound
        with. Raises `RunNotFoundError` for an unknown run.

        The counters are the run's in-memory dispatch state: a caller outside a dispatch pass
        persists them with `flush_metrics`. The frozen ceiling is a claim-time check (ADR-33)
        and this wrapper does not re-apply it per call; a post-dispatch caller charges its
        actual cost with `charge_post_dispatch` and asks `post_dispatch_ceiling_reached`
        before each unit of its own work (synthesis: each submission). The check comes
        before a submission, not before each call, so the submission that reaches the
        ceiling can pass it by its own calls; the claim path, which knows its figure in
        advance, never does.
        """
        _cohort, run_row = self._find_run(run_id)
        inner = provider if provider is not None else self._provider
        if inner is None:
            raise ValueError(
                f"governed_provider({run_id!r}) needs a provider: none was passed and this "
                "orchestrator was built without one")
        return GovernedProvider(inner, self._dispatch_state(run_row))

    def _run_model_batch(
        self,
        cohort: Any,
        run_row: Any,
        state: dict[str, Any],
        batch: Sequence[Any],
        effective: int,
    ) -> int:
        """Run one claimed batch through the model-call seam at the effective width.

        Each unit's ASSEMBLED request is built on the calling thread BEFORE the pool
        takes anything — the assembler is the owning stage's shipped door, it reads
        the store (the words resolve here: "the lease resolves the identity, the
        assembler the words"), and the store is not a thread-shared surface — so the
        only thing that runs concurrently is the model call itself. Assembly
        completes for the WHOLE batch before the first submit, and the submits are
        then back-to-back: pipelining assembly into the submission loop would pace
        the ramp at the assembly interval, and Little's law would cap the observed
        in-flight peak at `call_duration / assembly_interval` — a figure set by the
        assembler's speed, not by the governor. With the payloads pre-built, calls
        run on a thread pool bounded by `min(len(batch), effective)` and the pool
        width IS the observable in-flight concurrency the governor's ceiling governs
        (`FR-ORCH-21`; the seam's spy counts the peak — the caller bounds a batch to
        `effective` so the pre-assembly latency is bounded by the same figure). Every
        outcome is classified, never absorbed silently:

        - **Completion** — the real `Completion`: the unit closes (`complete`), and
          the answer's tokens, cost, cache prefix and resolved build accrue to the
          run's counters (`CT-PROV-11`'s shape — M-ORCH reads the provider's
          counters and persists them).
        - **`RateLimitedError`** (`RES-11`) — expected, not an error: the counters
          increment (the parsed `Retry-After` accrues to the honoured wait), the
          unit requeues **without consuming an attempt and without a unit-level
          error** (a rate limit is the provider's condition, not the unit's — §9.11),
          and the governor reduces next pass.
        - **`MemoryError`** (`RES-13`) — the box's condition: the unit requeues the
          same way (the box's condition is not the unit taxonomy's, §9.11), the cap
          reduces, and the OOM ladder's cumulative count may drop the judge from the
          panel.

        Any other exception propagates — an unexpected transport failure is a defect,
        and the units stay leased on the ledger where the sweeper reclaims them.
        Returns the number of units the batch closed — the walk's headway check.
        """
        if not batch:
            return 0
        workers = max(1, min(len(batch), effective))
        reduction = _env_int(CONCURRENCY_REDUCTION_ENV, CONCURRENCY_REDUCTION_DEFAULT)
        requeue_list: list[str] = []
        oomed: dict[str | None, list[str]] = {}
        completed = 0

        executor = self._stage_executor(state)
        governed = GovernedProvider(self._provider, state)
        paused: list[BaseException] = []

        run_unit = executor.execute  # bound first — see `_PreparedExecutor.execute`

        def invoke(unit: Any) -> Any:
            # The executor owns what a unit means; the counters are wrapped around the
            # provider it is handed, so a worker cannot spend calls this run does not count.
            return run_unit(unit, governed)

        # For the transport seam, assembly still completes for the WHOLE batch before the
        # pool exists — a raise here lands with nothing submitted, and the burst that follows
        # reaches the full pool width (the pipelined alternative would never be observed to).
        # A bound executor assembles inside its own worker, where the stage owns the door.
        executor.prepare(batch)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            submitted = [(unit, pool.submit(invoke, unit)) for unit in batch]
            for unit, future in submitted:
                try:
                    answer = future.result()
                except RateLimitedError as error:
                    self._absorb_rate_limit(state, error)
                    requeue_list.append(unit.work_id)
                    continue
                except MemoryError:
                    judge = unit.judge
                    oomed.setdefault(judge, []).append(unit.work_id)
                    requeue_list.append(unit.work_id)
                    continue
                except (ProviderUnavailableError, BuildChangedError) as error:
                    # `FR-ORCH-30` (V-1's pause half): the provider is gone, or answering as
                    # a different build. Neither is the unit's fault, so it requeues with its
                    # attempts untouched — and the RUN pauses (`FR-ORCH-16/17`), because every
                    # other unit is about to meet the same condition. The pass then stops
                    # rather than burning the batch against an outage.
                    requeue_list.append(unit.work_id)
                    paused.append(error)
                    continue
                if isinstance(answer, StageOutcome):
                    if not answer.completed:
                        # The worker struck the unit out inside its own budget. The calls it
                        # made are already on the run's counters; the unit goes back to
                        # pending for a later pass.
                        requeue_list.append(unit.work_id)
                        continue
                else:
                    self._absorb_completion(state, answer)
                # The swap's duration closes on the batch's first successful call
                # — the load rides that call, so the wall time from the boundary
                # to here is the duration the swap cost (`FR-ORCH-19`).
                started = state["residency"]["swap_started"]
                if started is not None:
                    state["residency"]["swap_ms"] += (
                        time.monotonic() - started
                    ) * 1000.0
                    state["residency"]["swap_started"] = None
                self.complete(unit.work_id)
                completed += 1
        if requeue_list:
            self._requeue_units(cohort, run_row["run_id"], requeue_list)
        if paused:
            self.pause(run_row["run_id"], cause=paused[0])
        for judge, ooms in oomed.items():
            self._oom_remedy(cohort, run_row, state, judge, ooms=len(ooms))
        if (requeue_list or oomed) and not state["reduced_this_pass"]:
            # The governor's reduction (`FR-ORCH-21`): once per pass, on the first
            # pass that saw a rate-limited or OOM call — applied NOW, not at the
            # next pass's start, so the report the caller is about to read carries
            # the reduced width (the operator reads the reduction that takes
            # effect, `RES-11`'s observable back-off).
            state["cap"] = max(state["cap"] // reduction, 1)
            state["reduced_this_pass"] = True
        return completed

    def _absorb_completion(self, state: dict[str, Any], answer: Any) -> None:
        """Accrue one successful model answer to the run's counters (`CT-PROV-11`).

        The method stays as the dispatch loop's name for it; the accrual itself is
        `_accrue_completion`, which `GovernedProvider` calls too — one definition, so the two
        seams cannot come to count differently."""
        _accrue_completion(state, answer)

    def _absorb_rate_limit(
        self, state: dict[str, Any], error: RateLimitedError
    ) -> None:
        """Count one rate-limited call and honour its `Retry-After` (`FR-PROV-07`).

        The honouring here is the dispatch's own half of §9.13: the wait the provider
        asked for accrues to the run's counter and the unit defers to a later pass at
        a reduced cap — the back-off is the deferral, not a sleep inside the dispatch
        loop (a loop that sleeps holds its worker hostage to the provider's clock).
        """
        with state["lock"]:
            state["rate_limited_calls"] += 1
            state["transport_retries"] += 1
            match = re.search(
                r"retry-after:\s*([0-9]*\.?[0-9]+)", str(error), re.IGNORECASE
            )
            if match:
                state["rate_limit_wait_s"] += float(match.group(1))

    def _oom_remedy(
        self,
        cohort: Any,
        run_row: Any,
        state: dict[str, Any],
        judge: str | None,
        *,
        ooms: int = 1,
    ) -> None:
        """The OOM ladder for one judge (`RES-13`, §9.11): reduce, retry, drop.

        The cumulative per-judge count is of OOM **calls** — every failed load counts,
        including the several one batch can produce — and the drop lands when the
        count reaches the threshold: the batch's own requeue IS the "retry" the
        ladder's remedy names (the units return to pending and are claimed again at
        the reduced cap before the panel ever shrinks). The drop removes the judge
        from the run's `panel_config` as a **strict subset, never below one judge**
        and records it in the run row — a later validation record cannot claim a
        panel the box could not hold (`CT-PROV-08`: drops, never substitutions). The
        dropped judge's un-run units stay in the ledger, pending, for an operator to
        re-queue under the smaller panel; the claim walk skips them — durably,
        reading the run row's own panels (`_dropped_judges`), so the skip survives a
        restart.
        """
        count = state["oom_counts"].get(judge, 0) + ooms
        state["oom_counts"][judge] = count
        threshold = _env_int(OOM_DROP_THRESHOLD_ENV, OOM_DROP_THRESHOLD_DEFAULT)
        if judge is None or count < threshold:
            return
        arms = self._panel_arms(run_row["panel_config"])
        if judge not in arms or len(arms) <= 1:
            return
        reduced = tuple(arm for arm in arms if arm != judge)
        # The reduced panel is written in `panel_config_json`'s canonical shape —
        # same separators, same sort — built from the arm STRINGS the row already
        # carries (the arms are build ids; the frozen row is the identity source).
        # Every other key the row carries (the decision engine, FR-ORCH-36) is kept: only the
        # arms shrink. Dropping the engine here would mint later units' work ids without it.
        try:
            record = json.loads(run_row["panel_config"])
        except (TypeError, ValueError):
            record = {}
        record = dict(record) if isinstance(record, dict) else {}
        record["arms"] = list(reduced)
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["record_reduced_panel"],
                panel_config=json.dumps(
                    record,
                    separators=_JSON_SEPARATORS,
                    sort_keys=True,
                ),
                run_id=run_row["run_id"],
            )
        # The panel the order cache was derived from no longer exists: every cached
        # order for the run is stale, and a claim that trusted it could hand out a
        # dropped judge's unit past the walk's skip. The skip itself needs no
        # in-memory mark — it reads the run row's OWN panels (frozen minus the
        # just-recorded reduction, `_dropped_judges`), so a fresh Orchestrator over
        # the same store skips the same units after a restart.
        self._invalidate_order_cache(run_row["run_id"])
