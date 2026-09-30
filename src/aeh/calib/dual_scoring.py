"""Dual scoring: disclosing the cost of a pass, authorizing it, and running it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .errors import CalibrationError
from .rosters import (
    CALIB_CLASS_SIZE_CAP_ENV,
    _CLASS_ROSTERS,
    _class_size_cap,
    _EXECUTED_PASSES,
    _next_timestamp,
)


# --- the dual-scoring budget (NFR-CALIB-03, CT-CALIB-12) ---------------------------------------------
#
# Dual scoring costs "one additional full-class scoring pass and shall be budgeted as such".
# A cost discovered afterwards was never budgeted — it was incurred — so the pass is planned,
# disclosed, authorized, and only then run: the ordering is the contract.


@dataclass
class DualScoringPlan:
    """The disclosed cost of one dual-scoring pass (`NFR-CALIB-03`, `CT-CALIB-12`).

    ``disclosed_at`` is set at plan time, ``authorized_at`` only by `authorize`, and
    ``executed_at`` only by `run_dual_scoring` — the observed order is the contract, and
    the plan's event fields are the record of it. ``estimated_calls`` is exactly one
    full-class pass: every submission, under R₁, on every criterion. ``scores`` is what
    the pass bought — one row per submission, one band per criterion, as the provider
    returned them — so what was paid for is inspectable next to what it cost. The gate
    does not read this raw pass: the caller joins it with R₀'s accumulated bands and
    registers the roster the gate consumes."""

    cohort_id: str
    r0: str
    r1: str
    provider: Any
    class_size: int
    criteria_count: int
    estimated_calls: int
    disclosed_at: datetime
    notes: tuple[str, ...] = ()
    authorized_at: datetime | None = None
    executed_at: datetime | None = None
    scores: tuple[tuple[Any, ...], ...] = ()


#: The declared example class a plan falls back to for a cohort the module has no roster
#: for — §6.5's example class, on a single-criterion rubric (the shape the calibration
#: fixture publishes). Disclosed in the plan's notes, never silent: an estimated cost
#: built on an unstated assumption is a budget that lies. Production registers the cohort
#: first and plans against its true shape.
PLAN_DEFAULT_CLASS_SIZE: int = 100


PLAN_DEFAULT_CRITERIA_COUNT: int = 1


def plan_dual_scoring(cohort_id: str, r0: str, r1: str, provider: Any) -> DualScoringPlan:
    """Disclose what one additional full-class dual-scoring pass will cost, **before**
    the operator authorizes it (`NFR-CALIB-03`, `CT-CALIB-12`).

    Plans against the registered roster's shape; for an unregistered cohort, against the
    declared example class, with the assumption in the plan's notes (see the module
    docstring). The plan makes **no** provider calls — the cost is estimated from the
    class's shape, and nothing is spent before `authorize` records the operator's
    approval."""
    roster = _CLASS_ROSTERS.get(cohort_id)
    if roster is None:
        class_size = PLAN_DEFAULT_CLASS_SIZE
        criteria_count = PLAN_DEFAULT_CRITERIA_COUNT
        notes = (
            f"cohort {cohort_id!r} is not registered with the module: planned against the "
            f"declared example class ({PLAN_DEFAULT_CLASS_SIZE} submissions on "
            f"{PLAN_DEFAULT_CRITERIA_COUNT} criterion), so the estimate is a floor — "
            "register the cohort to budget its true shape",
        )
    else:
        class_size = roster.class_size
        criteria_count = len(roster.criteria)
        notes = (
            f"planned against the registered roster for {cohort_id!r}: {class_size} "
            f"submissions on {criteria_count} criteria",
        )
    return DualScoringPlan(
        cohort_id=cohort_id,
        r0=r0,
        r1=r1,
        provider=provider,
        class_size=class_size,
        criteria_count=criteria_count,
        estimated_calls=class_size * criteria_count,
        disclosed_at=_next_timestamp(),
        notes=notes,
    )


def authorize(plan: DualScoringPlan) -> datetime:
    """Record the operator's authorization of the disclosed cost (`CT-CALIB-12`).

    The recorded timestamp is strictly after the disclosure's, so the observed order —
    disclose, then authorize, then run — is what distinguishes a budgeted cost from a
    reported one."""
    if plan.authorized_at is not None:
        raise CalibrationError(
            "this plan is already authorized: a budgeted cost is authorized once"
        )
    plan.authorized_at = _next_timestamp()
    return plan.authorized_at


def run_dual_scoring(plan: DualScoringPlan) -> DualScoringPlan:
    """Run the authorized pass: exactly the disclosed number of calls, through the
    injected provider (`NFR-CALIB-03`; seam 2 — the provider is the only egress point).

    One call per (submission, criterion) pair across the full class — the pass whose
    cost was disclosed and authorized — and the provider's bands land on the plan's
    ``scores`` (seam 4: what was paid for sits next to what it cost). An unauthorized
    plan is refused (a cost nobody approved was never budgeted), a re-run is refused
    (a budgeted cost is incurred once, and a second pass would double the invoice the
    operator approved), and an over-cap class is refused (the deployment's cap names
    itself)."""
    if plan.authorized_at is None:
        raise CalibrationError(
            "the pass was never authorized: run_dual_scoring runs only after authorize "
            "records the operator's approval (NFR-CALIB-03, CT-CALIB-12)"
        )
    if plan.executed_at is not None:
        raise CalibrationError(
            "this plan has already run: a budgeted cost is incurred once, and a second "
            "pass would double the invoice the operator approved"
        )
    cap = _class_size_cap()
    if cap is not None and plan.class_size > cap:
        raise CalibrationError(
            f"the plan covers {plan.class_size} submissions and the deployment's "
            f"{CALIB_CLASS_SIZE_CAP_ENV} is {cap}: the pass covers the full class or "
            "refuses, never a subset"
        )
    plan.scores = tuple(
        tuple(plan.provider.score(paper, criterion) for criterion in range(plan.criteria_count))
        for paper in range(plan.class_size)
    )
    plan.executed_at = _next_timestamp()
    # `FR-CALIB-15` builds the roster's R₁ half from "the bands `run_dual_scoring` returned",
    # and `register_dual_scored_roster` is handed a revision name rather than the plan object
    # — so the executed pass is remembered here, under the two things the caller names it by.
    _EXECUTED_PASSES[(plan.cohort_id, plan.r1)] = plan
    return plan
