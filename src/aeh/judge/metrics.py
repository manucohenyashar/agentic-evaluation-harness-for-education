"""The decision-engine outcome metrics for a run (how often it answered, fell back, and why)."""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

from aeh.orch import _env_float, _env_int

from .schema import JUDGE_STATEMENTS


# --- decision-engine metrics (FR-JUDGE-36, CT-JUDGE-28) -----------------------------------------

FALLBACK_ALERT_RATE_ENV = "HARNESS_JEV_FALLBACK_ALERT_RATE"


FALLBACK_ALERT_RATE_DEFAULT = 0.50


ALERT_MIN_PRESCREENS_ENV = "HARNESS_JEV_ALERT_MIN_PRESCREENS"


ALERT_MIN_PRESCREENS_DEFAULT = 50


_FALLBACK_OUTCOMES = ("below_gate", "rejected", "malformed")


@dataclass(frozen=True)
class DecisionEngineMetrics:
    """The decision engine's outcome metrics, by their contract names (CT-JUDGE-28).
    `decision_prescreens` counts every pre-screen row, including ineligible ones;
    `decision_fallback_rate` is (below_gate + rejected + malformed) / prescreens. `per_criterion`
    holds the same figures by criterion id."""

    decision_prescreens: int
    decision_accepted: int
    decision_below_gate: int
    decision_ineligible: int
    decision_ineligible_reasons: Mapping[str, int]
    decision_rejected: int
    decision_malformed: int
    decision_accepted_rate: float | None
    decision_fallback_rate: float | None
    decision_latency_p50_ms: float | None
    decision_latency_p95_ms: float | None
    decision_gate_histogram: tuple[int, ...]
    decision_fallback_rate_high: bool
    decision_requests_rejected: bool
    per_criterion: Mapping[str, "DecisionEngineMetrics"] = dataclasses.field(default_factory=dict)


def _percentile(values: list[float], q: float) -> float | None:
    """The `q` percentile of a sample, linearly interpolated between the closest ranks (NumPy's
    default method)."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _metrics_of(rows: list[Any], alert_rate: float, alert_min: int) -> DecisionEngineMetrics:
    count = len(rows)
    by = {name: sum(1 for r in rows if r["outcome"] == name)
          for name in ("accepted", "below_gate", "ineligible", "rejected", "malformed")}
    reasons: dict[str, int] = {}
    for r in rows:
        if r["outcome"] == "ineligible" and r["reason"]:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    fallback = sum(by[name] for name in _FALLBACK_OUTCOMES)
    histogram = [0] * 10
    for r in rows:
        if r["gate_confidence"] is not None:
            histogram[min(9, int(float(r["gate_confidence"]) * 10))] += 1
    latencies = [float(r["latency_ms"]) for r in rows if r["latency_ms"] is not None]
    fallback_rate = fallback / count if count else None
    return DecisionEngineMetrics(
        decision_prescreens=count, decision_accepted=by["accepted"],
        decision_below_gate=by["below_gate"], decision_ineligible=by["ineligible"],
        decision_ineligible_reasons=reasons, decision_rejected=by["rejected"],
        decision_malformed=by["malformed"],
        decision_accepted_rate=by["accepted"] / count if count else None,
        decision_fallback_rate=fallback_rate,
        decision_latency_p50_ms=_percentile(latencies, 0.50),
        decision_latency_p95_ms=_percentile(latencies, 0.95),
        decision_gate_histogram=tuple(histogram),
        decision_fallback_rate_high=bool(fallback_rate is not None and count >= alert_min
                                         and fallback_rate > alert_rate),
        decision_requests_rejected=by["rejected"] > 0,
    )


def decision_engine_metrics(handle: Any, run_id: str) -> DecisionEngineMetrics:
    """The run's decision-engine outcome mix, per criterion and overall, read from the pre-screen
    rows (FR-JUDGE-36). M-STATS reads these figures through this function, never directly."""
    alert_rate = _env_float(FALLBACK_ALERT_RATE_ENV, FALLBACK_ALERT_RATE_DEFAULT, low=0.0, high=1.0)
    alert_min = _env_int(ALERT_MIN_PRESCREENS_ENV, ALERT_MIN_PRESCREENS_DEFAULT)
    rows = list(handle.query(JUDGE_STATEMENTS["select_run_prescreens"], run_id=run_id))
    overall = _metrics_of(rows, alert_rate, alert_min)
    criteria = sorted({r["criterion_id"] for r in rows})
    per = {c: _metrics_of([r for r in rows if r["criterion_id"] == c], alert_rate, alert_min) for c in criteria}
    return dataclasses.replace(overall, per_criterion=per)
