"""Per-criterion extraction metrics for a run."""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Sequence

from .schema import EXTRACT_STATEMENTS


def _percentile(values: Sequence[float], q: float) -> float | None:
    """The `q` percentile of a sample, linearly interpolated between the closest ranks (NumPy's
    default method). Returns None for an empty sample: a percentile of nothing is missing, not
    zero."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    rank = q * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (rank - low) * (ordered[high] - ordered[low])


@dataclasses.dataclass(frozen=True)
class ExtractionMetrics:
    """One run's extraction signals, per criterion (FR-EXTRACT-12, CT-EXTRACT-17).

    Every field is a mapping keyed by criterion id, and the names are the contract's. Values
    are read from stored rows alone — no re-extraction, no provider call:

    * `spans_per_unit` — the count histogram (span count → units), the distribution rather
      than a mean, because a mean of 2 hides "half the units found nothing".
    * `empty_result_rate` — evidence rows carrying no span, over the criterion's evidence
      rows. A unit that never wrote evidence (quarantined, or failed past its budget) is in
      neither half: this is a signal about what extraction RETURNED, and the ledger's own
      status is where a failed unit is counted.
    * `second_family_disagreement_rate` — units whose second-family span set differs from the
      primary's, over the units that RAN a second family; `None` where none ran, because a
      zero there would claim agreement nobody measured (`FR-EXTRACT-07`, `CT-EXTRACT-10`). A
      second family that FAILED recorded an empty span set, so it reads as disagreement —
      `M-INTEG`'s own fail-closed doctrine for the same signal (a faulted read is adverse,
      never absent), which a run whose second family was down reads as a high rate.
    * `extraction_latency_p50_ms` / `extraction_latency_p95_ms` — the successful attempts'
      wall times (`FR-EXTRACT-13`), `None` for a criterion whose rows predate the column.
    """

    spans_per_unit: dict[str, dict[int, int]]
    empty_result_rate: dict[str, float]
    second_family_disagreement_rate: dict[str, float | None]
    extraction_latency_p50_ms: dict[str, float | None]
    extraction_latency_p95_ms: dict[str, float | None]


def _span_key(spans: Any) -> frozenset:
    """A set of spans as a comparable key, the same comparison M-INTEG makes for extractor
    disagreement. It is a set rather than a tuple because span order alone is not a disagreement.
    """
    prints = []
    for span in spans or ():
        if isinstance(span, dict):
            prints.append((span.get("start"), span.get("end"), span.get("text")))
        else:
            prints.append(span)
    return frozenset(prints)


def extraction_metrics(handle: Any, run_id: str) -> ExtractionMetrics:
    """Compute one run's extraction metrics, per criterion (FR-EXTRACT-12).

    Reads the run's stored `evidence` rows through the cohort handle — the payload this
    module wrote (`{"spans": [...], "second_family": {...}}`) and the latency column — and
    nothing else: the figures are reconstructible from the database by anyone, which is what
    makes them answerable months later.
    """
    rows = handle.query(EXTRACT_STATEMENTS["select_run_evidence"], run_id=run_id)
    spans_per_unit: dict[str, dict[int, int]] = {}
    empty: dict[str, float] = {}
    disagreement: dict[str, float | None] = {}
    p50: dict[str, float | None] = {}
    p95: dict[str, float | None] = {}
    counts: dict[str, list[int]] = {}
    second_total: dict[str, int] = {}
    second_differing: dict[str, int] = {}
    latencies: dict[str, list[float]] = {}
    for row in rows:
        criterion_id = str(row["criterion_id"])
        payload = row["payload"]
        record: dict[str, Any] = {}
        if payload is not None:
            try:
                record = json.loads(
                    payload.decode("utf-8") if isinstance(payload, (bytes, bytearray))
                    else payload
                )
            except (ValueError, AttributeError):
                record = {}
        spans = record.get("spans") or []
        counts.setdefault(criterion_id, []).append(len(spans))
        second = record.get("second_family")
        if isinstance(second, dict) and "spans" in second:
            second_total[criterion_id] = second_total.get(criterion_id, 0) + 1
            if _span_key(second.get("spans")) != _span_key(spans):
                second_differing[criterion_id] = second_differing.get(criterion_id, 0) + 1
        if row["latency_ms"] is not None:
            latencies.setdefault(criterion_id, []).append(float(row["latency_ms"]))
    for criterion_id, per_unit in counts.items():
        histogram: dict[int, int] = {}
        for count in per_unit:
            histogram[count] = histogram.get(count, 0) + 1
        spans_per_unit[criterion_id] = dict(sorted(histogram.items()))
        empty[criterion_id] = sum(1 for count in per_unit if count == 0) / len(per_unit)
        ran = second_total.get(criterion_id, 0)
        disagreement[criterion_id] = (
            None if not ran else second_differing.get(criterion_id, 0) / ran
        )
        sample = latencies.get(criterion_id, [])
        p50[criterion_id] = _percentile(sample, 0.50)
        p95[criterion_id] = _percentile(sample, 0.95)
    return ExtractionMetrics(
        spans_per_unit=spans_per_unit,
        empty_result_rate=empty,
        second_family_disagreement_rate=disagreement,
        extraction_latency_p50_ms=p50,
        extraction_latency_p95_ms=p95,
    )
