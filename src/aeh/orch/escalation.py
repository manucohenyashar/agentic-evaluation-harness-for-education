"""Enqueuing escalations and replacement arms, and the escalation budget's state."""

from __future__ import annotations

import json
import warnings
from typing import Any, Callable, Sequence

from .constants import STAGE_SCORE
from .errors import EscalationPlanError, WorkLedgerError
from .statements import ORCH_STATEMENTS
from .settings import (
    CRITERION_BREAKER_MIN_N_ENV,
    CRITERION_BREAKER_RATE_ENV,
    _env_float,
    _env_int,
    ESCALATION_BUDGET_ENV,
    ORCH_CRITERION_BREAKER_MIN_N,
    ORCH_CRITERION_BREAKER_RATE,
    ORCH_ESCALATION_BUDGET,
)
from .escalation_policy import (
    admit_escalations,
    criterion_breaker_tripped,
    escalation_plan,
    _extension_arms,
    _judge_id_of,
)
from .reports import (
    BreakerTrip,
    _content_id,
    _CONTENT_ID_KIND_BREAKER,
    _CONTENT_ID_KIND_REPLACEMENT,
    _CONTENT_ID_KIND_REQUEST,
    DECISION_ADMITTED,
    DECISION_HALTED_BY_BREAKER,
    EscalationBudgetState,
    EscalationReport,
    REPLACEMENT_ALREADY_REQUESTED,
    REPLACEMENT_INSERTED,
    REPLACEMENT_NOT_APPLICABLE,
    REPLACEMENT_REFUSED,
    ReplacementArmReport,
)


class EscalationMixin:
    """Adds judges to a cell's panel, within the run-wide escalation budget and the per-criterion
    breaker."""

    # -- escalation, the breakers and the budget (FR-ORCH-09/10/13/14, FR-ORCH-26) --------------

    def enqueue_escalation(
        self,
        tx: Any,
        criterion_score_key: Sequence[str],
        judges: Sequence[str] | None = None,
        *,
        expected_value: float | None = None,
    ) -> tuple[EscalationReport, ...]:
        """Add judges to one (submission, criterion) panel: the escalation M-AGG requests when a
        verdict falls outside its band (FR-ORCH-09/10, §7.1, CT-ORCH-08).

        More detail: `docs/code-notes/orch.md`, section `escalation.py: EscalationMixin.enqueue_escalation`.
        """
        key = tuple(str(part) for part in criterion_score_key)
        if len(key) == 3:
            run_id, submission_id, criterion_id = key
            if not list(tx.execute(
                ORCH_STATEMENTS["select_run_pair_panel"],
                run_id=run_id, submission_id=submission_id, criterion_id=criterion_id,
            )):
                raise EscalationPlanError(
                    f"run {run_id!r}'s ledger holds no score panel for "
                    f"({submission_id!r}, {criterion_id!r}): an escalation widens a panel "
                    "that exists — enumerate the run first (a criterion with no units has "
                    "no band to widen)."
                )
        elif len(key) == 2:
            # CT-ORCH-26 / FR-ORCH-34 (amended): the two-element key is deprecated, and says so.
            warnings.warn(
                "enqueue_escalation's (submission_id, criterion_id) key is deprecated; pass "
                "(run_id, submission_id, criterion_id) (FR-ORCH-34, CT-ORCH-26)",
                DeprecationWarning, stacklevel=2)
            submission_id, criterion_id = key
            holding = list(tx.execute(
                ORCH_STATEMENTS["select_pair_runs"],
                submission_id=submission_id,
                criterion_id=criterion_id,
            ))
            pair_runs = [r["run_id"] for r in holding if r["is_open"]]
            if not holding:
                raise EscalationPlanError(
                    f"no run's ledger holds a score panel for "
                    f"({submission_id!r}, {criterion_id!r}): an escalation widens a panel "
                    "that exists — enumerate the run first (a criterion with no units has "
                    "no band to widen)."
                )
            if len(pair_runs) != 1:
                raise WorkLedgerError(
                    f"the deprecated (submission_id, criterion_id) escalation key "
                    f"({submission_id!r}, {criterion_id!r}) is ambiguous: {len(pair_runs)} "
                    f"open runs hold the pair ({', '.join(pair_runs)}) — name the run with "
                    "the (run_id, submission_id, criterion_id) key (FR-ORCH-34)."
                )
            (run_id,) = pair_runs
        else:
            raise EscalationPlanError(
                f"criterion_score_key must be the (run_id, submission_id, criterion_id) "
                f"triple, got {key!r} — the key names the escalation's target the way the "
                "criterion_score table does (CT-ORCH-08, FR-ORCH-34)."
            )
        return (
            self._enqueue_escalation_locked(
                tx,
                self._run_row(run_id),
                submission_id=submission_id,
                criterion_id=criterion_id,
                judges=judges,
                expected_value=expected_value,
            ),
        )

    def enqueue_replacement_arm(
        self, tx: Any, criterion_score_key: Sequence[str],
    ) -> ReplacementArmReport:
        """Add one replacement judge to a panel that quarantine left with an even number of judges
        (FR-ORCH-43, CT-ORCH-33, #524, ADR-34).

        Inserts, in the caller's transaction, one further escalation arm (the next arm the
        pair does not carry, `_extension_arms` — never re-adding one, FR-ORCH-39) so the
        panel returns to odd. **One replacement per cell** (ADR-34): the request row is
        content-addressed on the pair, so a repeat inserts nothing and reports
        `already_requested`, and a replacement that is itself quarantined leaves the cell to
        the caller's `ungradeable_by_panel` path rather than starting a chain (the escalation
        rate counts cells, so a chain would never meet the budget). Refused, with nothing written, when the criterion's
        breaker has latched or the run's observed escalation rate is above
        `ORCH_ESCALATION_BUDGET` (FR-ORCH-13/14): a replacement is an escalation and is
        rationed like one. The key is the `(run_id, submission_id, criterion_id)` triple."""
        key = tuple(str(part) for part in criterion_score_key)
        if len(key) != 3:
            raise EscalationPlanError(
                f"enqueue_replacement_arm takes the (run_id, submission_id, criterion_id) "
                f"triple, got {key!r}")
        run_id, submission_id, criterion_id = key
        row = self._run_row(run_id)
        pair = dict(run_id=run_id, submission_id=submission_id, criterion_id=criterion_id)
        prior = tuple(r["judge_id"] for r in tx.execute(
            ORCH_STATEMENTS["select_pair_score_judges"], **pair))
        if not prior:
            raise EscalationPlanError(
                f"run {run_id!r}'s ledger holds no score panel for "
                f"({submission_id!r}, {criterion_id!r}): nothing to replace")
        quarantined = int(tx.execute(
            ORCH_STATEMENTS["select_pair_quarantined_score_units"], **pair)[0]["n"])
        gates: dict[str, str] = {"panel": f"{len(prior)} arm(s), {quarantined} quarantined"}

        def report(decision: str, reason: str, arm: str | None = None) -> ReplacementArmReport:
            return ReplacementArmReport(run_id, submission_id, criterion_id, decision, arm,
                                        reason, quarantined, gates)

        if quarantined == 0:
            return report(REPLACEMENT_NOT_APPLICABLE,
                          "no quarantined score unit: this even panel is not quarantine's")
        request_id = _content_id(_CONTENT_ID_KIND_REPLACEMENT, run_id, submission_id,
                                 criterion_id)
        if int(tx.execute(ORCH_STATEMENTS["select_request_exists"],
                          request_id=request_id)[0]["n"]):
            gates["idempotence"] = "this cell already had its replacement arm"
            return report(REPLACEMENT_ALREADY_REQUESTED,
                          "this cell already had its one replacement arm (ADR-34)")
        latch = tx.execute(
            ORCH_STATEMENTS["select_breaker"], run_id=run_id, criterion_id=criterion_id)
        if latch:
            gates["breaker"] = f"latched {latch[0]['tripped_at']}"
            return report(REPLACEMENT_REFUSED,
                          f"criterion breaker latched for {criterion_id} (FR-ORCH-13)")
        budget = _env_float(ESCALATION_BUDGET_ENV, ORCH_ESCALATION_BUDGET, low=0.0, high=1.0)
        processed, escalated, rate = self._escalation_rate(tx.execute, run_id)
        gates["budget"] = f"observed rate {rate:.4f} ({escalated}/{processed}) vs {budget}"
        if rate > budget:
            return report(REPLACEMENT_REFUSED,
                          f"escalation budget exhausted: observed rate {rate:.4f} above "
                          f"{budget} (FR-ORCH-14)")
        (arm,) = _extension_arms(self._panel_arms(row["panel_config"]), prior, count=1)
        detail = json.dumps({"replacement_after_quarantined": quarantined, "arm": arm},
                            sort_keys=True)
        tx.execute(
            ORCH_STATEMENTS["insert_escalation_request"], request_id=request_id,
            expected_value=None, requested_at=self._wall_now(), detail=detail, **pair)
        inserted = self._insert_escalation_units(tx, row, submission_id, criterion_id, (arm,))
        tx.execute(ORCH_STATEMENTS["admit_request"], request_id=request_id,
                   admitted_at=self._wall_now(), detail=detail)
        if inserted:
            self._invalidate_order_cache(run_id)
        gates["insert"] = f"{arm} ({inserted} unit(s) inserted into the caller's transaction)"
        return report(REPLACEMENT_INSERTED, "panel returned to odd", arm)

    def _enqueue_escalation_locked(
        self,
        tx: Any,
        row: Any,
        *,
        submission_id: str,
        criterion_id: str,
        judges: Sequence[str] | None,
        expected_value: float | None,
    ) -> EscalationReport:
        """The escalation decision, made inside the caller's transaction.

        Every read and write goes through `tx` — the caller's (`CT-ORCH-08`) or this
        method's own — so the decision is one consistent step against the ledger: the
        budget's counts, the breaker's window and the request row see the same state,
        and `FR-ORCH-09`'s same-transaction guarantee is a parameter, not a promise.
        """
        run_id = row["run_id"]
        arms = self._panel_arms(row["panel_config"])
        budget = _env_float(
            ESCALATION_BUDGET_ENV, ORCH_ESCALATION_BUDGET, low=0.0, high=1.0
        )
        breaker_rate = _env_float(
            CRITERION_BREAKER_RATE_ENV, ORCH_CRITERION_BREAKER_RATE, low=0.0, high=1.0
        )
        breaker_min_n = _env_int(CRITERION_BREAKER_MIN_N_ENV, ORCH_CRITERION_BREAKER_MIN_N)
        gates: dict[str, str] = {}

        # 1. The pair's prior panel — the score units the ledger enumerates for it,
        #    any origin, any status. The plan is validated BEFORE anything else: a
        #    caller asking for a non-widening or even-count escalation has broken the
        #    contract, and the refusal must be loud whatever the routing state is.
        prior = tuple(
            r["judge_id"] for r in tx.execute(
                ORCH_STATEMENTS["select_pair_score_judges"],
                run_id=run_id,
                submission_id=submission_id,
                criterion_id=criterion_id,
            )
        )
        named = None if judges is None else tuple(_judge_id_of(j) for j in judges)
        # A cell whose quarantine a replacement arm answered (FR-ORCH-43, #524) carries the
        # quarantined unit beside the arm that replaced it: an even unit count over an odd live
        # panel. It is already escalated (the replacement is escalation-origin), so this is
        # step 2's no-op; step 1's parity check would misread the replaced unit as corruption.
        # A caller naming judges still goes through the plan's validation below.
        replacement_id = _content_id(_CONTENT_ID_KIND_REPLACEMENT, run_id, submission_id,
                                     criterion_id)
        if named is None and int(tx.execute(ORCH_STATEMENTS["select_request_exists"],
                                            request_id=replacement_id)[0]["n"]):
            live = len(prior) - int(tx.execute(
                ORCH_STATEMENTS["select_pair_quarantined_score_units"], run_id=run_id,
                submission_id=submission_id, criterion_id=criterion_id)[0]["n"])
            gates["plan"] = (
                f"{len(prior)} units, a quarantine answered by a replacement (FR-ORCH-43): the "
                f"live panel is {live}; no further widening")
            gates["idempotence"] = "the replaced panel stands"
            processed, escalated, rate = self._escalation_rate(tx.execute, run_id)
            return self._escalation_report(
                tx, row, submission_id, criterion_id, DECISION_ADMITTED,
                prior_judges=prior, added_judges=(), judge_count=live,
                units_inserted=0, expected_value=expected_value,
                escalation_rate=rate, processed_results=processed,
                escalated_results=escalated, budget=budget,
                breaker_tripped=False, gates=gates,
            )
        target = escalation_plan(prior, add_judges=named, panel_arms=arms)
        additions = target[len(prior):]
        gates["plan"] = (
            f"{len(prior)} -> {len(target)} judges (+{', '.join(additions)})"
        )

        # 2. Idempotence: the pair is already escalated — a no-op that reports the
        #    panel it finds. The widened panel exists; that is what `admitted` means.
        if int(tx.execute(
            ORCH_STATEMENTS["select_pair_escalated"],
            run_id=run_id,
            submission_id=submission_id,
            criterion_id=criterion_id,
        )[0]["n"]):
            gates["idempotence"] = (
                "pair already carries escalation-origin units; widened panel stands"
            )
            processed, escalated, rate = self._escalation_rate(tx.execute, run_id)
            return self._escalation_report(
                tx, row, submission_id, criterion_id, DECISION_ADMITTED,
                prior_judges=prior, added_judges=(), judge_count=len(prior),
                units_inserted=0, expected_value=expected_value,
                escalation_rate=rate, processed_results=processed,
                escalated_results=escalated, budget=budget,
                breaker_tripped=False, gates=gates,
            )

        # 3. The criterion breaker (`FR-ORCH-13`): latch first, then the window.
        latch = tx.execute(
            ORCH_STATEMENTS["select_breaker"], run_id=run_id, criterion_id=criterion_id
        )
        if latch:
            gates["breaker"] = f"latched {latch[0]['tripped_at']}: {latch[0]['detail']}"
            processed, escalated, rate = self._escalation_rate(tx.execute, run_id)
            return self._escalation_report(
                tx, row, submission_id, criterion_id, DECISION_HALTED_BY_BREAKER,
                prior_judges=prior, added_judges=(), judge_count=len(prior),
                units_inserted=0, expected_value=expected_value,
                escalation_rate=rate, processed_results=processed,
                escalated_results=escalated, budget=budget,
                breaker_tripped=True, gates=gates,
            )
        window = tx.execute(
            ORCH_STATEMENTS["select_criterion_window"],
            run_id=run_id, criterion_id=criterion_id, n=breaker_min_n,
        )
        window_ids = {r["submission_id"] for r in window}
        escalated_ids = {
            r["submission_id"] for r in tx.execute(
                ORCH_STATEMENTS["select_criterion_escalated"],
                run_id=run_id, criterion_id=criterion_id,
            )
        }
        escalated_in_window = len(window_ids & escalated_ids)
        if criterion_breaker_tripped(
            escalated_in_window,
            len(window_ids),
            rate=breaker_rate,
            min_n=breaker_min_n,
        ):
            detail = (
                f"{escalated_in_window}/{len(window_ids)} of the first "
                f"{breaker_min_n} submissions processed escalated, above "
                f"{breaker_rate:.0%}: escalation halts for {criterion_id} — "
                "un-gradeable_by_panel, remainder single-judge provisional"
            )
            tx.execute(
                ORCH_STATEMENTS["insert_breaker"],
                breaker_id=_content_id(
                    _CONTENT_ID_KIND_BREAKER, run_id, criterion_id
                ),
                run_id=run_id,
                criterion_id=criterion_id,
                tripped_at=self._wall_now(),
                detail=detail,
            )
            gates["breaker"] = f"TRIPPED and latched: {detail}"
            processed, escalated, rate = self._escalation_rate(tx.execute, run_id)
            return self._escalation_report(
                tx, row, submission_id, criterion_id, DECISION_HALTED_BY_BREAKER,
                prior_judges=prior, added_judges=(), judge_count=len(prior),
                units_inserted=0, expected_value=expected_value,
                escalation_rate=rate, processed_results=processed,
                escalated_results=escalated, budget=budget,
                breaker_tripped=True, gates=gates,
            )
        gates["breaker"] = (
            f"not tripped ({escalated_in_window}/{len(window_ids)} in the window "
            f"of {breaker_min_n})"
        )

        # 4. The request row (the record the dispatch-time admission reads its EV
        #    from) and the units — written UNCONDITIONALLY: the budget rations
        #    dispatch, not the plan write (`FR-ORCH-14` at the claim pass, not here;
        #    see the method docstring's step 4). Content-addressed: a retried
        #    enqueue lands on the same rows and changes nothing.
        request_id = _content_id(
            _CONTENT_ID_KIND_REQUEST, run_id, submission_id, criterion_id
        )
        detail = json.dumps(
            {"judges": list(named) if named is not None else None},
            sort_keys=True,
        )
        tx.execute(
            ORCH_STATEMENTS["insert_escalation_request"],
            request_id=request_id,
            run_id=run_id,
            submission_id=submission_id,
            criterion_id=criterion_id,
            expected_value=expected_value,
            requested_at=self._wall_now(),
            detail=detail,
        )
        gates["request_row"] = (
            f"{request_id[:12]}… recorded at {expected_value!r} expected value"
        )
        inserted = self._insert_escalation_units(
            tx, row, submission_id, criterion_id, additions
        )
        tx.execute(
            ORCH_STATEMENTS["admit_request"],
            request_id=request_id,
            admitted_at=self._wall_now(),
            detail=detail,
        )
        gates["admission"] = (
            f"units written: {len(prior)} -> {len(target)} judges, {inserted} "
            "unit(s) inserted into the caller's transaction; dispatch admits them "
            "while the observed rate is at or under the budget"
        )
        if inserted:
            self._invalidate_order_cache(run_id)

        # 5. The observed rate, reported (the budget's numbers beside the decision —
        #    the decision itself is the claim pass's, through `admit_escalations`).
        processed, escalated, rate = self._escalation_rate(tx.execute, run_id)
        gates["budget"] = (
            f"observed rate {rate:.4f} ({escalated}/{processed} processed pairs "
            f"escalated) vs budget {budget}: dispatch admits pending escalation "
            "units while at or under, defers the remainder provisional above"
        )
        queue_depth = int(tx.execute(
            ORCH_STATEMENTS["select_queue_depth"], run_id=run_id
        )[0]["n"])
        gates["queue"] = f"{queue_depth} request(s) without written units"
        return self._escalation_report(
            tx, row, submission_id, criterion_id,
            DECISION_ADMITTED,
            prior_judges=prior,
            added_judges=additions,
            judge_count=len(target),
            units_inserted=inserted,
            expected_value=expected_value,
            escalation_rate=rate,
            processed_results=processed,
            escalated_results=escalated,
            budget=budget,
            breaker_tripped=False,
            gates=gates,
        )

    def _insert_escalation_units(
        self,
        tx: Any,
        row: Any,
        submission_id: str,
        criterion_id: str,
        additions: Sequence[str],
    ) -> int:
        """Insert the new units for one widened panel, with `origin='escalation'` (FR-ORCH-09).

        The additions are the plan's — derived by the caller from the pair's CURRENT
        panel in this same transaction, with the caller's named judges when it named
        any, so what was validated and reported is exactly what lands. Units are
        `INSERT OR IGNORE`d on the content address enumeration computes, so a pair
        widened by another path — the random arm draws the same (run, submission,
        criterion) — inserts nothing rather than scoring one judge twice.
        """
        inserted = 0
        for judge in additions:
            _, params = self._unit(
                row,
                STAGE_SCORE,
                {"submission_id": submission_id},
                {"criterion_id": criterion_id},
                judge,
                origin="escalation",
            )
            tx.execute(ORCH_STATEMENTS["insert_work_unit"], **params)
            # `OR IGNORE` cannot report what it did (the enumerate pass's note): the
            # count comes from the ledger, read in the same transaction.
            inserted += int(
                tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"]
            )
        return inserted

    def _escalation_dispatch_admission(self, cohort: Any, run_id: str) -> frozenset:
        """The (submission, criterion) pairs whose pending escalation units may be dispatched this
        pass (FR-ORCH-14).

        `admit_escalations` IS the decision — the claim pass is the production caller
        the pure policy owes its honesty to: the candidates are the run's pending
        escalation pairs with their recorded expected values (`FR-ORCH-14` admits in
        expected-value order), the counts are the ledger's observed (done-based) pair
        aggregates, the budget the env knob read at call time. The result is stable
        within a claim pass — completions happen outside it — so the pass reads it
        once per run and the gate itself is a set lookup per candidate. An
        over-budget pass defers every pending escalation pair (the provisional
        remainder `FR-ORCH-14` marks, EV-ordered in `escalation_budget_state`'s
        surface); the deferral lifts when growth returns headroom, and the cache drop
        at the defer site is what makes the next pass re-derive rather than serve a
        stale order.
        """
        budget = _env_float(
            ESCALATION_BUDGET_ENV, ORCH_ESCALATION_BUDGET, low=0.0, high=1.0
        )
        processed, escalated, _rate = self._escalation_rate(cohort.query, run_id)
        candidates = [
            ((r["submission_id"], r["criterion_id"]), r["expected_value"])
            for r in cohort.query(
                ORCH_STATEMENTS["select_pending_escalation_pairs"], run_id=run_id
            )
        ]
        plan = admit_escalations(
            candidates, escalated=escalated, processed=processed, budget=budget
        )
        return frozenset(plan.admitted)

    def _escalation_rate(
        self, read: Callable[..., Sequence[Any]], run_id: str
    ) -> tuple[int, int, float]:
        """`(processed pairs, escalated pairs, rate)` for one run. Both counts always come from the
        ledger (FR-ORCH-14, FR-ORCH-02).

        `read` is a bound reader — a transaction's `execute` (reads are legal inside a
        transaction; the read-modify-write every ledger transition is) or a cohort
        handle's `query` for the read-only surfaces. One helper, both doors, so the
        rate an enqueue decides on and the rate the operator surface shows are computed
        by the same lines.
        """
        processed = int(read(
            ORCH_STATEMENTS["select_processed_results"], run_id=run_id
        )[0]["n"])
        escalated = int(read(
            ORCH_STATEMENTS["select_escalated_results"], run_id=run_id
        )[0]["n"])
        rate = (escalated / processed) if processed else 0.0
        return processed, escalated, rate

    def _escalation_report(
        self,
        tx: Any,
        row: Any,
        submission_id: str,
        criterion_id: str,
        decision: str,
        *,
        prior_judges: tuple[str, ...],
        added_judges: tuple[str, ...],
        judge_count: int,
        units_inserted: int,
        expected_value: float | None,
        escalation_rate: float,
        processed_results: int,
        escalated_results: int,
        budget: float,
        breaker_tripped: bool,
        gates: dict[str, str],
    ) -> EscalationReport:
        """Build the escalation report, reading the queue depth in the same transaction."""
        queue_depth = int(tx.execute(
            ORCH_STATEMENTS["select_queue_depth"], run_id=row["run_id"]
        )[0]["n"])
        return EscalationReport(
            run_id=row["run_id"],
            submission_id=submission_id,
            criterion_id=criterion_id,
            decision=decision,
            prior_judges=prior_judges,
            added_judges=added_judges,
            judge_count=judge_count,
            units_inserted=units_inserted,
            expected_value=expected_value,
            escalation_rate=escalation_rate,
            escalation_budget=budget,
            queue_depth=queue_depth,
            breaker_tripped=breaker_tripped,
            gates=gates,
        )

    def escalation_budget_state(self, run_id: str) -> EscalationBudgetState:
        """The run-wide escalation budget's state; the "rate above budget" alert reads this
        (FR-ORCH-14, CT-ORCH-16).

        Every number is read from the ledger at call time: the rate is recomputed, the
        queue depth counted, the tripped criteria listed — no cached counters, because
        `FR-ORCH-02` allows no bookkeeping beyond the ledger and an alert computed from
        stale counters is a silent degradation, the exact shape `CT-ORCH-16` forbids.
        """
        row = self._run_row(run_id)
        cohort = self._store.cohort(row["cohort_id"])
        budget = _env_float(
            ESCALATION_BUDGET_ENV, ORCH_ESCALATION_BUDGET, low=0.0, high=1.0
        )
        processed, escalated, rate = self._escalation_rate(cohort.query, run_id)
        queue_depth = int(cohort.query(
            ORCH_STATEMENTS["select_queue_depth"], run_id=run_id
        )[0]["n"])
        tripped = tuple(
            r["criterion_id"] for r in cohort.query(
                ORCH_STATEMENTS["select_run_breakers"], run_id=run_id
            )
        )
        over = rate > budget
        # The admission split, computed by the SAME lines the claim pass decides with
        # (`admit_escalations` — one policy, both doors): the pending escalation
        # pairs with their recorded expected values, so the provisional remainder is
        # marked here exactly as the gate defers it there.
        pending_pairs = cohort.query(
            ORCH_STATEMENTS["select_pending_escalation_pairs"], run_id=run_id
        )
        plan = admit_escalations(
            [
                ((r["submission_id"], r["criterion_id"]), r["expected_value"])
                for r in pending_pairs
            ],
            escalated=escalated,
            processed=processed,
            budget=budget,
        )
        provisional = tuple(
            f"{pair[0]}/{pair[1]}" for pair in plan.provisional
        )
        return EscalationBudgetState(
            run_id=run_id,
            processed_results=processed,
            escalated_results=escalated,
            escalation_rate=rate,
            budget=budget,
            over_budget=over,
            queued_requests=queue_depth,
            tripped_criteria=tripped,
            provisional_pairs=provisional,
            gates={
                "rate": (
                    f"{escalated}/{processed} processed pairs escalated "
                    f"({rate:.4f}) vs budget {budget} — "
                    + ("OVER: dispatch defers pending escalation pairs, remainder "
                       "provisional until growth returns headroom"
                       if over else "within budget")
                ),
                "provisional": (
                    f"{len(provisional)} pending escalation pair(s) marked "
                    f"provisional (EV order): {', '.join(provisional)}"
                    if provisional
                    else "no pending escalation pairs deferred"
                ),
                "queue": f"{queue_depth} request(s) without written units",
                "breakers": (
                    f"{len(tripped)} criterion breaker(s) latched: "
                    f"{', '.join(tripped)}" if tripped else "none latched"
                ),
            },
        )

    def tripped_breakers(self, run_id: str) -> tuple[BreakerTrip, ...]:
        """The run's tripped criterion breakers, ordered by criterion (FR-ORCH-13). The alert reads
        these rows, and each includes the counts that tripped it, so the alert can say why, not
        just what."""
        row = self._run_row(run_id)
        cohort = self._store.cohort(row["cohort_id"])
        return tuple(
            BreakerTrip(
                run_id=run_id,
                criterion_id=r["criterion_id"],
                kind=r["kind"],
                tripped_at=r["tripped_at"],
                detail=r["detail"],
            )
            for r in cohort.query(
                ORCH_STATEMENTS["select_run_breakers"], run_id=run_id
            )
        )
