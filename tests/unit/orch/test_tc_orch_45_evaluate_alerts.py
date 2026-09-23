"""`TS-85` (issue #379) — `TC-ORCH-45`: `evaluate_alerts`' boundary table (`FR-ORCH-32`,
gap-fix test plan §5 / §6).

Defaults the table is written against: `HARNESS_ORCH_COST_WARNING_FRACTION=0.9`,
`…CACHE_COLLAPSE_SIGMA=3.0`, `…FLOOR=0.5`, `…MIN_HISTORY=3`.

| Row | Input | Expected alerts |
|---|---|---|
| 1 | spend 89.99, ceiling 100 | none |
| 2 | spend 90.00, ceiling 100 | `orch_cost_near_ceiling` |
| 3 | one breaker row `tripped=1` | `orch_criterion_breaker_tripped` |
| 4 | escalation rate above the budget by 0.001 / exactly at it | alert / no alert |
| 5 | `run.status='paused'` | `orch_run_paused` |
| 6 | cache history `[0.8, 0.8]` (2 runs), current 0.1 | none (below min history) |
| 7 | history `[0.8, 0.82, 0.78]`, current 0.1 | `orch_cache_hit_rate_collapse` |
| 8 | history `[0.4, 0.4, 0.4]`, current 0.39 | **contested — see below** |
| 9 | all conditions at once | the five names, exactly, as a set |
| 10 | `COST_WARNING_FRACTION` `"1.5"` / `"x"` | raises at call time |

**Rung 0, and that is the whole point of the requirement.** `FR-ORCH-32` makes the alert rules a
*pure function of already-read state* precisely so every condition can be exercised one at a
time without a store, a clock or a model call. A test that needed a run to check a threshold
would be testing the caller, not the rule.

**The boundaries are asserted as boundaries.** Rows 1/2 and 4a/4b are pairs a hundredth apart:
the cost rule must fire at the fraction and not below it, and the escalation rule must fire
*above* the budget and not *at* it — a run that spends exactly its allowance has not overrun it.
These are the two rows an implementation using the wrong comparison operator gets wrong while
passing everything else, which is why each is a pair rather than a single value.

**Row 9 is asserted as an exact set**, not as containment. `OBS-05`'s oracle is that each
condition fires its own alert *and not another's*; a subset check would pass for a rule that
fired a sixth alert nobody declared, and a containment check would pass for one that fired the
same alert five times.

**Row 8 is NOT asserted here, deliberately.** The plan flags it as design question **Q-D3** and
pins one reading: the collapse alert "only fires when the current rate is below both the σ bound
and 0.5 **and** the history mean was above the floor". The shipped `evaluate_alerts` disagrees —
with history `[0.4, 0.4, 0.4]` and a current rate of 0.39 it **fires**
`orch_cache_hit_rate_collapse`, because σ over a flat history is 0 and any lower value clears the
σ bound, with nothing suppressing it for a history whose mean (0.40) was already below the 0.5
floor. Asserting either way would silently arbitrate an open design question in a test, so this
file asserts neither and #379 reports the divergence for a human to settle. Whichever way Q-D3
goes, this row becomes a one-line addition here.

The nine remaining rows were each probed against the shipped function before being written, and
all nine match the plan.
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.orch import (
    ALERT_CACHE_COLLAPSE,
    ALERT_COST_NEAR_CEILING,
    ALERT_CRITERION_BREAKER,
    ALERT_ESCALATION_RATE,
    ALERT_RUN_PAUSED,
    CACHE_COLLAPSE_FLOOR_ENV,
    CACHE_COLLAPSE_MIN_HISTORY_ENV,
    CACHE_COLLAPSE_SIGMA_ENV,
    COST_WARNING_FRACTION_ENV,
    ESCALATION_BUDGET_ENV,
    ORCH_ESCALATION_BUDGET,
    WorkLedgerError,
    evaluate_alerts,
)

#: The defaults the plan's table is written against, pinned per test so a deployment's
#: environment cannot move a boundary this case asserts.
TABLE_DEFAULTS = {
    COST_WARNING_FRACTION_ENV: "0.9",
    CACHE_COLLAPSE_SIGMA_ENV: "3.0",
    CACHE_COLLAPSE_FLOOR_ENV: "0.5",
    CACHE_COLLAPSE_MIN_HISTORY_ENV: "3",
}


@pytest.fixture(autouse=True)
def _table_defaults(monkeypatch):
    """Every knob the table names, set to the table's value.

    Pinned rather than assumed: these are call-time env knobs (seam 3), so a box that exported
    one would silently move the boundary rows 1/2 and 6/7 exist to pin.
    """
    for name, value in TABLE_DEFAULTS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(ESCALATION_BUDGET_ENV, raising=False)


def _names(**kwargs: Any) -> list[str]:
    return sorted(alert.name for alert in evaluate_alerts(**kwargs))


# --- rows 1 and 2: the cost boundary -------------------------------------------------------


@pytest.mark.parametrize(
    ("spend", "expected"),
    [(89.99, []), (90.00, [ALERT_COST_NEAR_CEILING])],
    ids=["row1-below-the-fraction", "row2-at-the-fraction"],
)
def test_tc_orch_45_cost_near_ceiling_fires_at_the_fraction_and_not_below(spend, expected):
    """Rows 1-2 — 89.99 and 90.00 against a ceiling of 100 at fraction 0.9.

    A hundredth apart on purpose: this is the pair that separates `>=` from `>`, and an
    implementation with the wrong one passes every other row in the table.
    """
    assert _names(budget_state={"spend": spend, "ceiling": 100.0}) == expected


# --- row 3: the breaker --------------------------------------------------------------------


def test_tc_orch_45_a_tripped_breaker_row_fires_its_own_alert():
    """Row 3 — one breaker row fires the breaker alert and nothing else."""
    assert _names(breaker_rows=({"criterion_id": "C1", "tripped": 1},)) == [
        ALERT_CRITERION_BREAKER
    ]


# --- row 4: the escalation budget ----------------------------------------------------------


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (ORCH_ESCALATION_BUDGET + 0.001, [ALERT_ESCALATION_RATE]),
        (ORCH_ESCALATION_BUDGET, []),
    ],
    ids=["row4a-above-the-budget", "row4b-exactly-at-the-budget"],
)
def test_tc_orch_45_escalation_fires_above_the_budget_and_not_at_it(rate, expected):
    """Row 4 — above the budget by 0.001 fires; exactly at the budget does not.

    The budget is the allowance, so a run that spends exactly its allowance has not overrun
    it. Expressed against `ORCH_ESCALATION_BUDGET` rather than the literal 0.3 so the pair
    stays a boundary if the declared budget moves.
    """
    assert _names(metrics={"escalation_rate": rate}) == expected


# --- row 5: the paused run -----------------------------------------------------------------


def test_tc_orch_45_a_paused_run_fires_its_own_alert():
    """Row 5 — `run.status='paused'`."""
    assert _names(run_row={"status": "paused"}) == [ALERT_RUN_PAUSED]


# --- rows 6 and 7: the cache-collapse minimum history --------------------------------------


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        ((0.8, 0.8), []),
        ((0.8, 0.82, 0.78), [ALERT_CACHE_COLLAPSE]),
    ],
    ids=["row6-two-runs-below-min-history", "row7-three-runs-at-min-history"],
)
def test_tc_orch_45_cache_collapse_needs_the_minimum_history(history, expected):
    """Rows 6-7 — the same collapsed current rate (0.1), two runs of history then three.

    The pair is the point: with too little history there is no σ worth computing, so the rule
    must stay silent rather than fire on a mean of two. An implementation that ignored
    `MIN_HISTORY` fires on both and passes neither row's partner.
    """
    assert _names(metrics={"cache_hit_rate": 0.1}, cache_history=history) == expected


# --- row 9: every condition at once --------------------------------------------------------


def test_tc_orch_45_all_five_conditions_fire_exactly_their_own_alerts():
    """Row 9 — every condition true at once gives the five names, exactly, as a set.

    Exact equality, not containment: `OBS-05` says each condition fires its OWN alert and not
    another's, so a sixth name, a missing one, or a duplicate are all failures here.
    """
    fired = _names(
        run_row={"status": "paused"},
        metrics={"escalation_rate": 0.5, "cache_hit_rate": 0.1},
        breaker_rows=({"criterion_id": "C1", "tripped": 1},),
        budget_state={"spend": 95.0, "ceiling": 100.0},
        cache_history=(0.8, 0.82, 0.78),
    )
    assert fired == sorted(
        [
            ALERT_CACHE_COLLAPSE,
            ALERT_COST_NEAR_CEILING,
            ALERT_CRITERION_BREAKER,
            ALERT_ESCALATION_RATE,
            ALERT_RUN_PAUSED,
        ]
    ), f"the five conditions fired {fired}"


# --- row 10: the knob is validated at call time ---------------------------------------------


@pytest.mark.parametrize("value", ["1.5", "x"], ids=["out-of-range", "not-a-number"])
def test_tc_orch_45_an_invalid_cost_fraction_is_refused_at_call_time(value, monkeypatch):
    """Row 10 — a refusal, not a clamp, and at CALL time.

    A fraction of 1.5 means "warn only after the ceiling is passed", which is not a warning; a
    clamp would silently make it 1.0 and the operator would never learn their setting was
    impossible. The refusal must also name the knob, or it cannot be acted on.
    """
    monkeypatch.setenv(COST_WARNING_FRACTION_ENV, value)
    with pytest.raises(WorkLedgerError) as caught:
        evaluate_alerts(budget_state={"spend": 1.0, "ceiling": 100.0})
    assert COST_WARNING_FRACTION_ENV in str(caught.value), (
        f"the refusal does not name the knob: {caught.value!r}"
    )
