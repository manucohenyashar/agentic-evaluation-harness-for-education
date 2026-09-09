"""`TC-ORCH-36` (`FR-ORCH-15`, `FR-ORCH-17`, `OBS-05`; observability / rung 1,
P1) — synthetic breaches of each alert condition: escalation rate above budget,
a tripped criterion breaker, cost within 10% of ceiling, `cache_hit_rate`
collapse, and any pause (**written ahead of the alert surface**).

`OBS-05`'s oracle: **each alert fires on its own condition and does not fire on
the others**. So each test breaches exactly one condition against a healthy
background and asserts the fired set is exactly one alert; and a fully healthy
run fires nothing. The alert's exact NAME is the writer's to land — the
assertion counts and isolates the fired set and records the names it saw, so a
name that differs from any guess here still fails the *truth* only if the
firing is wrong (the `TC-ORCH-23` name-agnostic precedent; the names land
beside the M-ORCH observability story and reconcile in one line).

**Interface this file assumes** (the invented-and-used-together precedent of
`aeh.synth:synthesize` and `ALERT_SPAN_VERIFICATION_FAILURES` — the design's
M-ORCH Observability section declares the five conditions but pins no function
carrying them):

| Name | Status |
|---|---|
| `aeh.orch:evaluate_alerts` | **invented name** for the surface that turns run state into fired alerts — the five conditions are design text; the owning story may ship another name or a push-based surface, reconciled in one line here and in the registry |
| signature | keyword-only scalars, one per condition, so each breach is injectable independently: `evaluate_alerts(*, escalation_rate, breaker_tripped, cost, cost_ceiling, cache_hit_rate, paused)` returning a tuple of fired-alert identifiers |
| thresholds | design-pinned where the design pins them: escalation budget 0.30 (`ORCH_ESCALATION_BUDGET`), "cost within 10% of ceiling" verbatim; `cache_hit_rate` collapse has no pinned number — a clearly-collapsed 0.0 against a healthy 0.9 background needs no threshold to be exercised |

Isolation: rung 1 — in-memory fakes only, pure function, no store, no model
call, no clock. The suite's socket guard is active and nothing here could
reach it.
"""

from __future__ import annotations

import pytest

from tests.support.impl import ORCH_MODULE, require

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#66"

#: Design-pinned configuration (detailed-design.md, M-ORCH Configuration).
ESCALATION_BUDGET = 0.30


def _healthy(**overrides):
    """The healthy background every single-condition breach modifies: escalation
    rate well under budget, no breaker, cost far from the ceiling, cache hit
    rate where NFR-JUDGE-01 wants it, run running."""
    state = dict(
        escalation_rate=0.05,
        breaker_tripped=False,
        cost=5.0,
        cost_ceiling=100.0,
        cache_hit_rate=0.9,
        paused=False,
    )
    state.update(overrides)
    return state


def _fired(**state) -> tuple:
    alerts = require(ORCH_MODULE, "evaluate_alerts", issue=ISSUE)
    return tuple(alerts(**state))


def test_tc_orch_36_healthy_run_fires_no_alert():
    """The control: no condition breached, nothing fires. Without it, an
    evaluate_alerts that fires unconditionally passes every single-breach
    case that only checks membership."""
    fired = _fired(**_healthy())
    assert not fired, (
        f"a healthy run fired {fired} — an alert that fires on health trains "
        "the operator to ignore the channel (OBS-05: each fires on ITS OWN "
        "condition)"
    )


def test_tc_orch_36_escalation_rate_above_budget_fires_alone():
    """Run-wide escalation rate above `ORCH_ESCALATION_BUDGET` (0.30): exactly
    one alert, and it is not any other condition's (FR-ORCH-14's overrun
    visibility — scrutiny is admitted, never silently reduced)."""
    fired = _fired(**_healthy(escalation_rate=0.31))
    assert len(fired) == 1, (
        f"escalation rate above budget fired {fired} — exactly the breached "
        "condition's alert should fire (OBS-05: does not fire on the others)"
    )


def test_tc_orch_36_tripped_criterion_breaker_fires_alone():
    """A criterion tripping the breaker (FR-ORCH-13: over half of the first 20
    escalated): exactly one alert."""
    fired = _fired(**_healthy(breaker_tripped=True))
    assert len(fired) == 1, (
        f"a tripped criterion breaker fired {fired} — the breaker halts a "
        "criterion's panel escalation and the operator must hear exactly "
        "that, alone"
    )


def test_tc_orch_36_cost_within_10pct_of_ceiling_fires_alone():
    """Cost within 10% of the ceiling (FR-ORCH-15's boundary warning, before
    the pause at the ceiling): exactly one alert."""
    fired = _fired(**_healthy(cost=95.0, cost_ceiling=100.0))
    assert len(fired) == 1, (
        f"cost at 95% of the ceiling fired {fired} — the near-ceiling warning "
        "is FR-ORCH-15's early form; the operator must hear it alone"
    )


def test_tc_orch_36_cache_hit_rate_collapse_fires_alone():
    """`cache_hit_rate` collapse (RISK-23's only detection path: the symptom is
    a fivefold slowdown with no error — OBS-04 pairs the metric with this
    alert): exactly one alert."""
    fired = _fired(**_healthy(cache_hit_rate=0.0))
    assert len(fired) == 1, (
        f"a collapsed cache_hit_rate fired {fired} — prefix-cache collapse is "
        "silent everywhere else (nothing errors, throughput just dies), so "
        "its alert must fire alone and clearly"
    )


def test_tc_orch_36_any_pause_fires_alone():
    """A run paused for any reason (FR-ORCH-16/17: provider outage, build
    change, ceiling): exactly one alert."""
    fired = _fired(**_healthy(paused=True))
    assert len(fired) == 1, (
        f"a paused run fired {fired} — the plan's fifth condition is 'a run "
        "paused for any reason'; it must fire alone"
    )


def test_tc_orch_36_just_outside_the_thresholds_fires_nothing():
    """The negative boundary, where the design pins a number: escalation just
    UNDER the 0.30 budget and cost just under the 10%-of-ceiling warning band
    fire nothing. Without it, any threshold in (healthy, breached] passes the
    single-breach cases — a mis-calibrated threshold that cries wolf at 6% or
    stays silent until the pause would land identically here."""
    fired_rate = _fired(**_healthy(escalation_rate=0.29))
    assert not fired_rate, (
        f"escalation rate 0.29, just under the pinned 0.30 budget, fired "
        f"{fired_rate} — the budget is ORCH_ESCALATION_BUDGET and the alert "
        "fires ABOVE it, not at or under it"
    )
    fired_cost = _fired(**_healthy(cost=85.0, cost_ceiling=100.0))
    assert not fired_cost, (
        f"cost at 85% of the ceiling fired {fired_cost} — the design's "
        "warning band is 'within 10% of ceiling'; 15% out is healthy headroom "
        "and an alert there trains the operator to ignore the channel"
    )


def test_tc_orch_36_the_five_conditions_fire_distinct_alerts():
    """OBS-05's second clause, enforced: the fired sets across all five
    breaches are pairwise DISJOINT. Exactly-one-per-breach is satisfiable by
    one universal alert fired for every condition — the operator then cannot
    tell WHICH condition fired, and every runbook response is a guess."""
    breaches = {
        "escalation_rate": _healthy(escalation_rate=0.31),
        "breaker": _healthy(breaker_tripped=True),
        "cost": _healthy(cost=95.0, cost_ceiling=100.0),
        "cache_hit_rate": _healthy(cache_hit_rate=0.0),
        "pause": _healthy(paused=True),
    }
    fired_sets = {label: set(_fired(**state)) for label, state in breaches.items()}
    labels = list(fired_sets)
    for i, first in enumerate(labels):
        for second in labels[i + 1:]:
            assert fired_sets[first].isdisjoint(fired_sets[second]), (
                f"the {first!r} and {second!r} breaches fired overlapping "
                f"alert(s) {sorted(fired_sets[first] & fired_sets[second])} "
                f"(all sets: { {k: sorted(v) for k, v in fired_sets.items()} }) "
                "— each condition's alert must be identifiable as ITS "
                "condition's (OBS-05: fires on its own condition and not on "
                "the others)"
            )
