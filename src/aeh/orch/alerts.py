"""The run's alerts: their names, thresholds, and when each one fires."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .settings import (
    CACHE_COLLAPSE_FLOOR_DEFAULT,
    CACHE_COLLAPSE_FLOOR_ENV,
    CACHE_COLLAPSE_MIN_HISTORY_DEFAULT,
    CACHE_COLLAPSE_MIN_HISTORY_ENV,
    CACHE_COLLAPSE_SIGMA_DEFAULT,
    CACHE_COLLAPSE_SIGMA_ENV,
    COST_WARNING_FRACTION_DEFAULT,
    COST_WARNING_FRACTION_ENV,
    _env_float,
    _env_int,
    ESCALATION_BUDGET_ENV,
    ORCH_ESCALATION_BUDGET,
)


#: The five names, stable and declared here rather than spelled at each raise site: an
#: operator's runbook keys off them, and a name assembled at the raise is a name that can
#: drift between two branches of the same condition.
ALERT_ESCALATION_RATE = "orch_escalation_rate_above_budget"


ALERT_CRITERION_BREAKER = "orch_criterion_breaker_tripped"


ALERT_COST_NEAR_CEILING = "orch_cost_near_ceiling"


ALERT_CACHE_COLLAPSE = "orch_cache_hit_rate_collapse"


ALERT_RUN_PAUSED = "orch_run_paused"


RUN_ALERT_NAMES: tuple[str, ...] = (
    ALERT_ESCALATION_RATE,
    ALERT_CRITERION_BREAKER,
    ALERT_COST_NEAR_CEILING,
    ALERT_CACHE_COLLAPSE,
    ALERT_RUN_PAUSED,
)


@dataclass(frozen=True)
class RunAlert:
    """One fired alert (`FR-ORCH-32`): its stable `name`, and the `detail` that tells the
    operator which figure fired it.

    `detail` is deliberately not part of equality-by-name usage — `OBS-05`'s oracle is
    about WHICH condition fired, and a test comparing whole objects would break whenever
    a message improved. `str(alert)` is the name, so a fired tuple reads as its names.
    """

    name: str
    detail: str = ""

    def __str__(self) -> str:
        return self.name


def _alert_knobs() -> dict[str, float]:
    """The alert thresholds, read at CALL time (seam 3) and refused rather than clamped:
    a `HARNESS_ORCH_COST_WARNING_FRACTION` of 1.5 would mean "warn only after the ceiling
    is passed", which is not a warning, and a clamp would silently make it 1.0."""
    return {
        "cost_warning_fraction": _env_float(
            COST_WARNING_FRACTION_ENV, COST_WARNING_FRACTION_DEFAULT,
            low=0.0, high=1.0,
        ),
        "cache_sigma": _env_float(
            CACHE_COLLAPSE_SIGMA_ENV, CACHE_COLLAPSE_SIGMA_DEFAULT,
            low=0.0, high=100.0,
        ),
        "cache_floor": _env_float(
            CACHE_COLLAPSE_FLOOR_ENV, CACHE_COLLAPSE_FLOOR_DEFAULT,
            low=0.0, high=1.0,
        ),
        "cache_min_history": float(
            _env_int(CACHE_COLLAPSE_MIN_HISTORY_ENV, CACHE_COLLAPSE_MIN_HISTORY_DEFAULT)
        ),
    }


def _as_float(value: Any, default: float = 0.0) -> float:
    """One figure from a row or mapping, with a declared default. A metric that is absent
    is not a metric that is zero everywhere — but for these five rules the absent reading
    is the quiet one (no spend recorded is no spend alert), which is the safe direction."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mapping_get(row: Any, key: str, default: Any = None) -> Any:
    """One field from whichever row shape the caller holds — `sqlite3.Row`, a mapping, or
    a dataclass-ish object."""
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        value = getattr(row, key, None)
    return default if value is None else value


def paused_milliseconds(control_rows: Any, *, now: str) -> float:
    """How long the run spent paused, from its APPLIED control rows (`FR-ORCH-33`).

    Pairs each `pause` with the next `resume` after it. Two cases decide the shape:

    * **An open pause** — paused and never resumed — is closed at `now`. AC4's second
      pause has no resume, and dropping it would count the time since as working time,
      which is the opposite of what the operator sees.
    * **A repeated pause** with no intervening resume does not restart the interval: the
      run was already stopped, and counting the overlap twice would subtract more than
      the elapsed time and drive the clock negative.
    """
    total = 0.0
    open_since: str | None = None
    for row in (control_rows or ()):
        action = str(_mapping_get(row, "action", "") or "").lower()
        applied_at = _mapping_get(row, "applied_at")
        if not applied_at:
            continue
        if action == "pause":
            if open_since is None:
                open_since = str(applied_at)
        elif action == "resume" and open_since is not None:
            total += max(_millis_between(open_since, str(applied_at)), 0.0)
            open_since = None
    if open_since is not None:
        total += max(_millis_between(open_since, now), 0.0)
    return total


def _provider_config(run_row: Any) -> dict[str, Any]:
    """The run's FROZEN backend snapshot as a mapping, or empty when there is none.

    `run.provider_config` is the run as it was STARTED — the ceiling, the currency, the
    retention setting. Reading current configuration instead would relabel a finished
    run's figures every time an operator polled it."""
    raw = _mapping_get(run_row, "provider_config")
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_utc(timestamp: Any) -> Any:
    """One ledger timestamp as an aware datetime, or `None` when there is no honest one —
    `_elapsed_seconds_since`'s reading, factored out so the two agree about what a naive
    stamp means (UTC) and about an unparseable one (no reading, never a guess)."""
    if not timestamp:
        return None
    try:
        moment = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _millis_between(start: Any, end: Any) -> float:
    """Milliseconds between two stored timestamps, or 0.0 when either is unreadable —
    an unparseable stamp must not make the clock negative."""
    began, ended = _as_utc(start), _as_utc(end)
    if began is None or ended is None:
        return 0.0
    return (ended - began).total_seconds() * 1000.0


def evaluate_alerts(
    *,
    run_row: Any = None,
    metrics: Any = None,
    breaker_rows: Any = (),
    budget_state: Any = None,
    cache_history: Any = (),
) -> tuple[RunAlert, ...]:
    """`FR-ORCH-32`: the run's fired alerts, as a pure function of already-read state.

    Pure on purpose. Every input is a value the caller has already gathered, so the rules
    can be exercised one condition at a time without a store, a clock or a model call —
    `TC-ORCH-36`'s isolation rung — and so the operator surface and a test see the same
    function rather than two spellings of the same thresholds.

    `OBS-05`'s oracle is that each condition fires its OWN alert and not another's, so the
    five rules below are independent by construction: no rule reads another's input, and
    none of them short-circuits the rest.
    """
    knobs = _alert_knobs()
    fired: list[RunAlert] = []

    rate = _as_float(_mapping_get(metrics, "escalation_rate"), -1.0)
    if rate < 0:
        rate = _as_float(_mapping_get(budget_state, "escalation_rate"), -1.0)
    budget = _env_float(
        ESCALATION_BUDGET_ENV, ORCH_ESCALATION_BUDGET, low=0.0, high=1.0
    )
    if rate > budget:
        # ABOVE the budget, never at it: the budget is the allowance, and a run that
        # spends exactly its allowance has not overrun it. The budget is the same
        # call-time knob the admission sites read — an alert that fires at 0.30 while
        # the dispatcher admits to 1.0 is noise on a compliant run, and one that stays
        # silent to 0.30 while the dispatcher refuses at 0.10 hides a real overrun.
        fired.append(RunAlert(
            ALERT_ESCALATION_RATE,
            f"escalation rate {rate:.4f} is above the {budget} budget",
        ))

    tripped = [row for row in (breaker_rows or ()) if row is not None]
    if tripped:
        names = ", ".join(
            str(_mapping_get(row, "criterion_id", "")) for row in tripped
        )
        fired.append(RunAlert(
            ALERT_CRITERION_BREAKER,
            f"criterion breaker tripped: {names}" if names else "criterion breaker tripped",
        ))

    ceiling = _as_float(_mapping_get(budget_state, "ceiling"))
    if not ceiling:
        # The run's FROZEN declared ceiling, never `cost_estimate`: the estimate is what
        # the run is expected to cost, the ceiling is what it may not exceed, and reading
        # one as the other makes this alert fire on a different quantity's data.
        ceiling = _as_float(_provider_config(run_row).get("cost_ceiling"))
    spend = _as_float(_mapping_get(budget_state, "spend"))
    if not spend:
        spend = _as_float(_mapping_get(run_row, "cost_spend"))
    if ceiling > 0 and spend >= knobs["cost_warning_fraction"] * ceiling:
        fired.append(RunAlert(
            ALERT_COST_NEAR_CEILING,
            f"spend {spend} is at or past "
            f"{knobs['cost_warning_fraction']:.2f} of the {ceiling} ceiling",
        ))

    history = [
        _as_float(value, -1.0) for value in (cache_history or ())
    ]
    history = [value for value in history if value >= 0]
    current = _as_float(_mapping_get(metrics, "cache_hit_rate"), -1.0)
    if current >= 0 and len(history) >= int(knobs["cache_min_history"]):
        mean = sum(history) / len(history)
        variance = sum((value - mean) ** 2 for value in history) / len(history)
        deviation = variance ** 0.5
        breach = mean - knobs["cache_sigma"] * deviation
        # BOTH guards: statistically unusual against the baseline history, AND absolutely
        # low. A steady history has no deviation, which would otherwise make any dip at
        # all a three-sigma event.
        # FR-ORCH-32 (amended, design 1.9 §3.11, Q-D3): and the history was ABOVE the floor.
        # A history already below it is a standing condition, not a collapse.
        if current < breach and current < knobs["cache_floor"] and mean > knobs["cache_floor"]:
            fired.append(RunAlert(
                ALERT_CACHE_COLLAPSE,
                f"cache hit rate {current:.3f} is below both the history's "
                f"{knobs['cache_sigma']}-sigma break ({breach:.3f}) and the "
                f"{knobs['cache_floor']} floor",
            ))

    # `status` is the run row's own lifecycle column and the authority on whether the run
    # is paused (`CHECK (status IN ('pending','running','paused','complete','failed'))`).
    # `pause_reason` is kept as a second signal, not the primary one: it says WHY, and a
    # pause recorded without a reason is still a pause.
    status_text = str(_mapping_get(run_row, "status", "") or "").lower()
    pause_reason = _mapping_get(run_row, "pause_reason")
    paused_flag = _mapping_get(budget_state, "paused")
    if status_text == "paused" or pause_reason or bool(paused_flag):
        reason = str(pause_reason or "") or "no reason recorded"
        fired.append(RunAlert(ALERT_RUN_PAUSED, f"run is paused: {reason}"))

    return tuple(fired)
