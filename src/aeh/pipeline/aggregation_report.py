"""The aggregate stage report: what aggregation decided over the whole run (FR-AGG-23, CT-AGG-25).

One end-of-run trace, computed run-wide from the stored rows rather than accumulated pass by
pass, so a resumed run's report covers every cell and a re-aggregated cell counts once. The same
figures go to `run_metrics` as `agg.<name>` rows, through M-ORCH's write path (M-PIPE executes no
SQL, `CT-PIPE-05`; M-ORCH is the table's sole writer, `CT-STORE-03`).
"""

from __future__ import annotations

from typing import Any

from .results import StageTrace

#: The `run_metrics` name prefix for the aggregate stage's figures.
AGG_METRIC_PREFIX = "agg."


def aggregation_report(orch: Any, handle: Any, run_id: str) -> StageTrace:
    """The aggregate stage's report for one run, recorded into `run_metrics` as it is built.

    Its `metrics` carry confidence min / median / max (absent, with a reason, when no cell was
    aggregated — never 0.0), the number of cells each cap fired on, the cell count by routing,
    and the uncited and re-anchored verdict counts. A failure to read or record is reported on
    the trace, never raised: this is observability, and it must not cost the run its result —
    nor vanish silently.
    """
    from aeh.agg import aggregation_stage_figures

    try:
        figures = aggregation_stage_figures(handle.cohort, run_id)
    except Exception as error:  # noqa: BLE001 - reported on the trace, never raised
        return StageTrace("aggregate", detail=(
            f"aggregate stage report not computed: {type(error).__name__}: {error}",))

    metrics: dict[str, Any] = {
        "cells": figures.cells,
        "confidence_min": figures.confidence_min,
        "confidence_median": figures.confidence_median,
        "confidence_max": figures.confidence_max,
        "confidence_absent_reason": figures.confidence_absent_reason,
        "caps_fired": dict(figures.caps_fired),
        "routing": dict(figures.routing),
        "uncited": figures.uncited,
        "reanchored": figures.reanchored,
    }
    detail = [_summary_line(metrics)]
    try:
        orch.record_run_metrics(run_id, run_metric_rows(metrics))
    except Exception as error:  # noqa: BLE001 - reported on the trace, never raised
        detail.append(f"aggregate stage figures not recorded: {type(error).__name__}: {error}")
    return StageTrace("aggregate", detail=tuple(detail), metrics=metrics)


def run_metric_rows(metrics: dict[str, Any]) -> dict[str, float]:
    """The report's figures as `agg.<name>` rows: one per scalar, one per cap
    (`agg.caps_fired.<cap>`) and one per routing (`agg.routing.<routing>`). An absent confidence
    figure writes no row — it stays absent rather than reading as 0."""
    rows: dict[str, float] = {}
    for name in ("cells", "confidence_min", "confidence_median", "confidence_max",
                 "uncited", "reanchored"):
        value = metrics[name]
        if value is not None:
            rows[AGG_METRIC_PREFIX + name] = float(value)
    for group in ("caps_fired", "routing"):
        for key, count in metrics[group].items():
            rows[f"{AGG_METRIC_PREFIX}{group}.{key}"] = float(count)
    return rows


def _summary_line(metrics: dict[str, Any]) -> str:
    if metrics["confidence_min"] is None:
        confidence = f"confidence: absent ({metrics['confidence_absent_reason']})"
    else:
        confidence = (f"confidence min {metrics['confidence_min']:.4g}, "
                      f"median {metrics['confidence_median']:.4g}, "
                      f"max {metrics['confidence_max']:.4g}")
    routing = ", ".join(f"{name} {count}" for name, count in metrics["routing"].items())
    fired = ", ".join(f"{name} {count}" for name, count in metrics["caps_fired"].items() if count)
    return (f"aggregate stage report: {metrics['cells']} cell(s); {confidence}; "
            f"routing: {routing}; caps fired: {fired or 'none'}; "
            f"{metrics['uncited']} uncited verdict(s), {metrics['reanchored']} re-anchored")
