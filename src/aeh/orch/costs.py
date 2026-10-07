"""Cost estimates, the billed figure per unit, and the frozen cost ceiling."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from .constants import STAGE_SCORE
from .errors import WorkLedgerError
from .statements import ORCH_STATEMENTS
from .settings import DECISION_TOKENS_PER_SEAT_DEFAULT, DECISION_TOKENS_PER_SEAT_ENV, _env_int
from .alerts import _mapping_get


class CostsMixin:
    """Estimates a run's cost and enforces its frozen cost ceiling."""

    # -- the cost seam (FR-ORCH-15) --------------------------------------------------------------

    def _run_ceiling(self, run_row: Any) -> Decimal | None:
        """The cost ceiling the run froze when it was created, or None.

        Read from the run row's frozen `provider_config` — never from the current
        environment (`FR-CONF-07`'s freeze: a ceiling changed mid-run would let spend
        outpace the number the operator approved). Malformed JSON or a non-numeric
        ceiling is a named `WorkLedgerError`, not a guessed absence: a ceiling the
        orchestrator cannot read must stop scheduling loudly, never silently uncap the
        run.
        """
        raw = run_row["provider_config"]
        try:
            cfg = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise WorkLedgerError(
                f"run {run_row['run_id'][:12]} carries malformed provider_config — "
                "the frozen ceiling cannot be read, and an unreadable ceiling must "
                "halt scheduling loudly rather than silently uncap the run."
            ) from exc
        value = cfg.get("cost_ceiling") if isinstance(cfg, dict) else None
        if value is None:
            return None
        try:
            ceiling = Decimal(str(value))
        except InvalidOperation as exc:
            raise WorkLedgerError(
                f"run {run_row['run_id'][:12]} froze a non-numeric cost ceiling "
                f"{value!r} — refused: the ceiling is the boundary spend may not "
                "cross, and an unparseable boundary is not a boundary."
            ) from exc
        if ceiling < 0:
            raise WorkLedgerError(
                f"run {run_row['run_id'][:12]} froze a negative cost ceiling "
                f"{ceiling} — refused: a negative boundary would pause the run on "
                "its first measured unit, which is a misconfiguration, not a spend."
            )
        return ceiling

    def _normalize_figure(self, answer: Any, run_id: str) -> Decimal | None:
        """Turn one provider cost answer into the Decimal the ledger adds up, or None if the call
        is not billed.

        The seam's declared protocol: `estimate_cost(unit) -> Decimal | CostEstimate`. A
        bare `Decimal` is the figure; a `CostEstimate`-shaped answer contributes its
        `.cost`. None means *not billed* (`CT-PROV-03`: a zero would read as a measured
        price — not-billed adds nothing to the accrual and consumes no ceiling, which is
        how replayed work passes a ceiling honestly). A negative figure is refused: it
        would move spend *away* from the ceiling.
        """
        figure = getattr(answer, "cost", answer)
        if figure is None:
            return None
        if not isinstance(figure, Decimal):
            figure = Decimal(str(figure))
        if figure < 0:
            raise WorkLedgerError(
                f"provider estimated a negative cost ({figure}) for a unit of run "
                f"{run_id[:12]} — refused: a negative figure would make spend move "
                "away from the ceiling, which is a ceiling that never trips."
            )
        return figure

    def _cost_figure(self, cohort: Any, unit_row: Any, ceiling: Decimal) -> Decimal:
        """The cost one unit will add to its run's spend, computed before it is dispatched.

        Consults the injected provider seam — **the measured protocol**, never an
        estimated optimism (`FR-PROV-12/04`: the ceiling is enforced from the same
        figures the run is billed against). A run frozen with a ceiling but dispatched
        without a seam raises: a ceiling checked against nothing is the exact shape the
        seam exists to prevent, and halting scheduling honestly is the stated behaviour.
        """
        if self._provider is None:
            raise WorkLedgerError(
                f"run {unit_row['run_id'][:12]} froze a cost ceiling ({ceiling}) but "
                "this orchestrator holds no provider seam to measure units against — "
                "a ceiling checked against nothing is not enforcement. Construct the "
                "Orchestrator with provider=... (estimate_cost) or clear the ceiling."
            )
        figure = self._normalize_figure(
            self._provider.estimate_cost(self._unit_from_row(unit_row)),
            unit_row["run_id"],
        )
        llm = Decimal("0") if figure is None else figure
        # FR-ORCH-41 / CT-ORCH-31 (#522, ADR-33): a decision-seat claim also accrues the
        # per-seat decision figure — the conservative 100%-fallback charge FR-ORCH-37's
        # estimate uses — so a cloud decision engine cannot carry a run past its ceiling.
        # Engine off, or no decision provider bound: nothing is added (NFR-SYS-14).
        return llm + self._decision_seat_figure(cohort, unit_row)

    def _decision_seat_figure(self, cohort: Any, unit_row: Any) -> Decimal:
        """The decision-engine cost charged when `unit_row` is claimed. Zero when the unit is not a
        decision seat (a score unit judged by the run's first arm, in a run that froze a decision
        engine), when no decision provider is bound, or when the engine is not billed."""
        if self._decision_provider is None:
            return Decimal("0")
        if _mapping_get(unit_row, "stage") != STAGE_SCORE:
            return Decimal("0")
        run_row = self._run_row_in(cohort, unit_row["run_id"])
        try:
            record = json.loads(_mapping_get(run_row, "panel_config") or "{}")
        except (TypeError, ValueError):
            return Decimal("0")
        arms = record.get("arms") or []
        if not record.get("decision_engine") or not arms:
            return Decimal("0")
        if _mapping_get(unit_row, "judge_id") != arms[0]:
            return Decimal("0")
        return self._decision_per_seat_cost(1)

    def _run_cost_estimate(self, cohort: Any, run_id: str) -> Decimal | None:
        """The run's estimated cost: the sum of its units' estimates (FR-ORCH-15).

        None when there is no seam (no figure is displayed — a fabricated zero would
        read as a measured price) or nothing is enumerated yet (an empty run's estimate
        is absent, not zero).
        """
        if self._provider is None:
            return None
        rows = cohort.query(
            ORCH_STATEMENTS["select_run_units_for_estimate"], run_id=run_id
        )
        if not rows:
            return None
        total = Decimal("0")
        for unit_row in rows:
            figure = self._normalize_figure(
                self._provider.estimate_cost(self._unit_from_row(unit_row)),
                run_id,
            )
            if figure is not None:
                total += figure
        return total + self._decision_cost_estimate(cohort, run_id, rows)

    def _decision_cost_estimate(self, cohort: Any, run_id: str, rows: Any) -> Decimal:
        """The extra estimated cost of the decision engine (FR-ORCH-37): one decision call per
        decision seat, added on top of the normal model estimate for every arm. This assumes every
        decision falls back to the models, so the ceiling is never optimistic.

        A seat is a score unit judged by the run's first arm when the run froze a decision engine.
        Each call is priced by the decision provider's `estimate_cost` over
        `HARNESS_ORCH_DECISION_TOKENS_PER_SEAT` input tokens (output is free). Zero with no
        decision provider or engine, or when the engine is not billed."""
        if self._decision_provider is None:
            return Decimal("0")
        run_row = self._run_row_in(cohort, run_id)
        try:
            record = json.loads(_mapping_get(run_row, "panel_config") or "{}")
        except (TypeError, ValueError):
            return Decimal("0")
        return self._decision_cost_from_record(record, rows)

    def _decision_cost_from_record(self, record: Any, rows: Any) -> Decimal:
        """The decision-engine figure for the panel record `record` over the unit rows
        `rows` — the arithmetic of `_decision_cost_estimate` without the run-row read, so
        the pre-start estimate (`_plan_cost_estimate`, FR-CONSOLE-43) prices the SAME seat
        rule the started run's estimate does. Zero with no decision provider, a malformed
        record, no engine on the record, no arms, or no seats."""
        if self._decision_provider is None:
            return Decimal("0")
        if not isinstance(record, dict):
            return Decimal("0")
        arms = record.get("arms") or []
        if not record.get("decision_engine") or not arms:
            return Decimal("0")
        seats = sum(1 for row in rows
                    if row["stage"] == STAGE_SCORE and row["judge_id"] == arms[0])
        if not seats:
            return Decimal("0")
        return self._decision_per_seat_cost(seats)

    def _plan_cost_estimate(
        self, planned_params: list[dict[str, Any]], *, panel_record: dict[str, Any],
    ) -> Decimal | None:
        """The pre-start figure for a run's PLANNED units (FR-CONSOLE-43's preview): the
        same sum `_run_cost_estimate` computes over the ledger's rows, priced over the
        plan `_planned_units` returned instead — one pricing arithmetic, two row sources.

        The run does not exist yet, so nothing is read from a run row and nothing is
        written. None when no provider seam is bound or the plan is empty (the started
        run's estimate would be absent in both cases, not zero). The decision figure is
        `panel_record`'s seats over the same planned rows — the per-seat cost of every
        first-arm score unit the plan holds."""
        if self._provider is None:
            return None
        if not planned_params:
            return None
        total = Decimal("0")
        run_id = str(planned_params[0].get("run_id") or "")
        for params in planned_params:
            unit = self._unit_from_row({**params, "attempt": 0})
            figure = self._normalize_figure(self._provider.estimate_cost(unit), run_id)
            if figure is not None:
                total += figure
        return total + self._decision_cost_from_record(panel_record, planned_params)

    def _decision_per_seat_cost(self, seats: int) -> Decimal:
        """The decision provider's `estimate_cost` for `seats` calls of
        `HARNESS_ORCH_DECISION_TOKENS_PER_SEAT` input tokens each (output is free); zero when the
        engine is not billed. Used for both the start estimate (FR-ORCH-37) and the charge at claim
        time (FR-ORCH-41)."""
        from aeh.prov import CallPlan

        tokens = _env_int(DECISION_TOKENS_PER_SEAT_ENV, DECISION_TOKENS_PER_SEAT_DEFAULT)
        estimate = self._decision_provider.estimate_cost(CallPlan(seats, tokens, 0))
        cost = getattr(estimate, "cost", None)
        return Decimal("0") if cost is None else Decimal(cost)

    def charge_post_dispatch(self, run_id: str, cost: Decimal) -> None:
        """Add the actual cost of a model call made after dispatch to the run's spend (#596).

        Synthesis runs after the last claim, so no claim-time figure ever charged it
        (`FR-ORCH-15`, ADR-33); it is charged its measured cost instead. A run that froze no
        ceiling accrues nothing, exactly as the claim path does.
        """
        cohort, run_row = self._find_run(run_id)
        if self._run_ceiling(run_row) is None or not cost:
            return
        with cohort.transaction() as tx:
            spend = Decimal(
                tx.execute(ORCH_STATEMENTS["select_run"], run_id=run_id)[0]["cost_spend"] or "0")
            tx.execute(ORCH_STATEMENTS["accrue_run_spend"], run_id=run_id,
                       cost_spend=str(spend + Decimal(cost)))

    def post_dispatch_ceiling_reached(self, run_id: str) -> str | None:
        """The reason a model call after dispatch must not be made, or None if it may (#596).

        The claim path's strict reading: spend AT the ceiling stops further spend. Returns the
        reason text for the caller's trace, naming the spend and the ceiling.
        """
        _cohort, run_row = self._find_run(run_id)
        ceiling = self._run_ceiling(run_row)
        if ceiling is None:
            return None
        spend = Decimal(_mapping_get(run_row, "cost_spend") or "0")
        if spend >= ceiling:
            return f"cost ceiling reached: spend {spend} of ceiling {ceiling}"
        return None
