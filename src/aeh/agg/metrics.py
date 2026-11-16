"""Per-criterion aggregation signals for a run, read from stored rows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .schema import AGG_STATEMENTS
from .settings import AGG_CAP_TABLE


@dataclass(frozen=True)
class AggregationSignals:
    """One run's aggregation signals, per criterion (FR-AGG-17, CT-AGG-15).

    Every field is a mapping keyed by criterion id:

    * `band_histogram` — band → count, the distribution the moderation meeting reads.
    * `band_spread_distribution` — spread → count; a panel's disagreement, not its average.
    * `agreement_distribution` — the stored ordinal α values, as value → count.
    * `escalation_rate` — the share of the criterion's PANELS that were widened: submissions
      carrying an escalation-origin unit over submissions the run judged for the criterion. A
      widening writes two units (1→3, 3→5), so units would count each widening twice.
    * `auto_accept_rate` — rows routed `auto` over the criterion's rows.
    * `caps_fired` — cap name → count, per criterion, from the `caps_fired` list
      `write_score` stored: the per-cap dimensionality `CT-AGG-15` asks for, never one total.
    """

    band_histogram: dict[str, dict[str, int]]
    band_spread_distribution: dict[str, dict[int, int]]
    agreement_distribution: dict[str, dict[float, int]]
    escalation_rate: dict[str, float]
    auto_accept_rate: dict[str, float]
    caps_fired: dict[str, dict[str, int]]


def aggregation_signals(handle: Any, run_id: str) -> AggregationSignals:
    """Compute one run's aggregation signals from the stored score rows only (FR-AGG-17).

    The score rows carry the bands, spreads, α values, routings and fired caps; the work
    ledger carries the widenings (`origin='escalation'`). A second run of the same cohort
    contributes nothing: every read names the run (`CT-AGG-20`).
    """
    bands: dict[str, dict[str, int]] = {}
    spreads: dict[str, dict[int, int]] = {}
    agreements: dict[str, dict[float, int]] = {}
    caps: dict[str, dict[str, int]] = {}
    auto: dict[str, int] = {}
    rows_seen: dict[str, int] = {}
    for row in handle.query(AGG_STATEMENTS["select_run_scores"], run_id=run_id):
        criterion_id = str(row["criterion_id"])
        rows_seen[criterion_id] = rows_seen.get(criterion_id, 0) + 1
        band_counts = bands.setdefault(criterion_id, {})
        band_name = str(row["band"])
        band_counts[band_name] = band_counts.get(band_name, 0) + 1
        spread_counts = spreads.setdefault(criterion_id, {})
        spread = int(row["band_spread"] or 0)
        spread_counts[spread] = spread_counts.get(spread, 0) + 1
        if row["agreement"] is not None:
            alpha_counts = agreements.setdefault(criterion_id, {})
            alpha = float(row["agreement"])
            alpha_counts[alpha] = alpha_counts.get(alpha, 0) + 1
        else:
            agreements.setdefault(criterion_id, {})
        if row["routing"] == "auto":
            auto[criterion_id] = auto.get(criterion_id, 0) + 1
        fired = caps.setdefault(criterion_id, {})
        raw = row["caps_fired"]
        if raw:
            try:
                names = json.loads(raw)
            except ValueError:
                names = []
            for name in names or ():
                fired[str(name)] = fired.get(str(name), 0) + 1

    judged_panels: dict[str, int] = {}
    escalated_panels: dict[str, int] = {}
    for row in handle.query(AGG_STATEMENTS["select_run_judged_panels"], run_id=run_id):
        judged_panels[str(row["criterion_id"])] = int(row["n"])
    for row in handle.query(AGG_STATEMENTS["select_run_escalated_panels"], run_id=run_id):
        escalated_panels[str(row["criterion_id"])] = int(row["n"])

    escalation_rate: dict[str, float] = {}
    auto_rate: dict[str, float] = {}
    for criterion_id, seen in rows_seen.items():
        # The denominator is the criterion's judged panels where the ledger has them, and its
        # score rows otherwise — the same population either way for a run whose panels each
        # produced a row (a hand-seeded world without a ledger reads the rows).
        denominator = judged_panels.get(criterion_id) or seen
        escalation_rate[criterion_id] = escalated_panels.get(criterion_id, 0) / denominator
        auto_rate[criterion_id] = auto.get(criterion_id, 0) / seen
    return AggregationSignals(
        band_histogram=bands,
        band_spread_distribution=spreads,
        agreement_distribution=agreements,
        escalation_rate=escalation_rate,
        auto_accept_rate=auto_rate,
        caps_fired=caps,
    )


# --- FR-AGG-23 / CT-AGG-25: the aggregate stage report --------------------------------------------

#: Every routing value a `criterion_score` row can carry (the store's CHECK), so the report
#: names each one — a routing nobody reached reads 0, not missing.
ROUTINGS: tuple[str, ...] = ("auto", "queued", "provisional", "triage", "reviewed")

#: Why min / median / max are absent on a run with no aggregated cell: absent, never 0.0.
NO_CONFIDENCE_REASON = "no cell has been aggregated yet, so there is no confidence to report"


@dataclass(frozen=True)
class AggregationStageFigures:
    """What the aggregate stage decided over a whole run, from its stored score rows (FR-AGG-23).

    `confidence_min` / `_median` / `_max` are `None` — with `confidence_absent_reason` saying
    why — when no aggregated row carries a confidence; never 0.0 (a figure nobody measured is not
    a low one). `caps_fired` names every declared cap, with the number of cells where it fired;
    `routing` names every routing value, with its cell count.
    """

    cells: int
    confidence_min: float | None
    confidence_median: float | None
    confidence_max: float | None
    confidence_absent_reason: str | None
    caps_fired: dict[str, int]
    routing: dict[str, int]


def aggregation_stage_figures(handle: Any, run_id: str) -> AggregationStageFigures:
    """The run's aggregate-stage figures, computed run-wide from the stored score rows the
    aggregation wrote (FR-AGG-23, CT-AGG-25) — so a resumed run's report covers every cell, and a
    re-aggregated cell counts once. Every read names the run (`CT-AGG-20`)."""

    confidences: list[float] = []
    caps: dict[str, int] = {name: 0 for name in AGG_CAP_TABLE}
    routing: dict[str, int] = {name: 0 for name in ROUTINGS}
    cells = 0
    for row in handle.query(AGG_STATEMENTS["select_run_aggregated_scores"], run_id=run_id):
        cells += 1
        if row["confidence"] is not None:
            confidences.append(float(row["confidence"]))
        name = str(row["routing"])
        routing[name] = routing.get(name, 0) + 1
        raw = row["caps_fired"]
        if raw:
            try:
                fired = json.loads(raw)
            except ValueError:
                fired = []
            for cap in fired or ():
                caps[str(cap)] = caps.get(str(cap), 0) + 1
    if not confidences:
        return AggregationStageFigures(cells, None, None, None, NO_CONFIDENCE_REASON, caps, routing)
    ordered = sorted(confidences)
    middle = len(ordered) // 2
    median = (ordered[middle] if len(ordered) % 2
              else (ordered[middle - 1] + ordered[middle]) / 2)
    return AggregationStageFigures(cells, ordered[0], median, ordered[-1], None, caps, routing)
