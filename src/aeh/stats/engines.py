"""Agreement per engine partition, the decision gate's calibration, and non-inferiority."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .settings import _env_float, _env_int
from .admissibility import _is_admissible, _system_side
from .agreement import _band_ordinals, _distance_coefficient
from .schema import STATS_STATEMENTS


# --- engine measurement (Jev design delta FR-STATS-26/27, NFR-STATS-06) -------------------------
#
# "Better grading" is a claim to measure. These read the same admissible blind labels every
# figure here uses (`_is_admissible`, CT-STATS-01) and partition them by the engine that
# produced the labelled cell's verdict. A partition below its minimum reports
# `insufficient_data`, never a number (CT-STATS-03, CT-STATS-24).

ENGINE_PARTITIONS: tuple[str, ...] = ("decision", "llm_fallback", "llm_engine_off")


ENGINE_MIN_LABELS_ENV = "HARNESS_STATS_ENGINE_MIN_LABELS"


ENGINE_MIN_LABELS = 60


CALIBRATION_MIN_LABELS_ENV = "HARNESS_STATS_CALIBRATION_MIN_LABELS"


CALIBRATION_MIN_LABELS = 20


NONINFERIORITY_DELTA_ENV = "HARNESS_STATS_NONINFERIORITY_DELTA"


NONINFERIORITY_DELTA = 0.05


INSUFFICIENT_DATA = "insufficient_data"


_WILSON_Z = 1.96


def engine_partition(handle: Any, run_id: str, student_ref: str, criterion_id: str) -> str | None:
    """Which engine partition one labelled cell belongs to: `decision`, `llm_fallback` or
    `llm_engine_off`, or None when the student has no submission in the run's cohort (FR-STATS-26).
    """
    rows = handle.query(STATS_STATEMENTS["select_submission_for_ref"], student_ref=student_ref)
    if not rows:
        return None
    evidence = handle.query(STATS_STATEMENTS["select_cell_engine_evidence"], run_id=run_id,
                            submission_id=rows[0]["submission_id"], criterion_id=criterion_id)[0]
    if int(evidence["decision_n"] or 0):
        return "decision"
    if int(evidence["prescreen_n"] or 0):
        return "llm_fallback"
    return "llm_engine_off"


@dataclass(frozen=True)
class EngineAgreement:
    """One engine partition's blind-label agreement. `ordinal_alpha` is None whenever
    `insufficient_data` is true, because below the minimum a number would be read as a finding."""

    partition: str
    n: int
    ordinal_alpha: float | None
    insufficient_data: bool


def agreement_by_engine(labels: Iterable[Any], partition_of: Callable[[Any], str | None], *,
                        minimum: int | None = None) -> dict[str, EngineAgreement]:
    """Ordinal alpha for each engine partition, over admissible labels only (FR-STATS-26).
    `partition_of(label)` names a label's partition; a label it maps to None, or an inadmissible
    label, counts in no partition. Every partition is reported, empty ones as insufficient data."""
    floor = minimum if minimum is not None else _env_int(ENGINE_MIN_LABELS_ENV, ENGINE_MIN_LABELS)
    pairs: dict[str, list[tuple[Any, Any]]] = {name: [] for name in ENGINE_PARTITIONS}
    for label in labels:
        if not _is_admissible(label):
            continue
        partition = partition_of(label)
        if partition not in pairs:
            continue
        system, teacher = _system_side(label), getattr(label, "teacher_band", None)
        if system is None or teacher is None:
            continue
        pairs[partition].append((system, teacher))
    out: dict[str, EngineAgreement] = {}
    for name, population in pairs.items():
        n = len(population)
        if n < floor:
            out[name] = EngineAgreement(name, n, None, True)
            continue
        ordinals, band_count = _band_ordinals(population)
        out[name] = EngineAgreement(name, n, _distance_coefficient(ordinals, band_count), False)
    return out


def _wilson(successes: int, n: int) -> tuple[float, float]:
    """The 95% Wilson score interval."""
    p = successes / n
    z2 = _WILSON_Z * _WILSON_Z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = _WILSON_Z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return centre - half, centre + half


@dataclass(frozen=True)
class CalibrationBin:
    low: float
    high: float
    n: int
    exact_agreement: float | None
    adjacent_agreement: float | None
    interval_low: float | None
    interval_high: float | None
    insufficient_data: bool


@dataclass(frozen=True)
class GateCalibrationReport:
    """Accepted decision-engine verdicts grouped by band confidence above the gate (FR-STATS-27).
    """

    threshold: float
    bins: tuple[CalibrationBin, ...]


def decision_gate_calibration(records: Iterable[tuple[float, int, int]], *, threshold: float = 0.80,
                              bin_width: float = 0.05, minimum: int | None = None) -> GateCalibrationReport:
    """How well the decision engine's confidence matches reality (FR-STATS-27). Pure. `records` are
    `(band_confidence, system_ordinal, teacher_ordinal)` for accepted verdicts with an admissible
    blind label. Bins of `bin_width` run from the threshold to 1.0; each reports exact and
    within-one-band agreement, with a 95% Wilson interval on exact agreement. A bin with fewer than
    `minimum` labels (default 20) reports insufficient data and no number (CT-STATS-03)."""
    floor = minimum if minimum is not None else _env_int(CALIBRATION_MIN_LABELS_ENV, CALIBRATION_MIN_LABELS)
    edges: list[float] = []
    edge = threshold
    while edge < 1.0 - 1e-12:
        edges.append(round(edge, 10))
        edge += bin_width
    grouped: dict[int, list[tuple[int, int]]] = {i: [] for i in range(len(edges))}
    for confidence, system, teacher in records:
        if confidence <= threshold:
            continue
        index = min(int((confidence - threshold) / bin_width + 1e-9), len(edges) - 1)
        grouped[index].append((int(system), int(teacher)))
    bins = []
    for i, low in enumerate(edges):
        population = grouped[i]
        n = len(population)
        high = min(1.0, round(low + bin_width, 10))
        if n < floor:
            bins.append(CalibrationBin(low, high, n, None, None, None, None, True))
            continue
        exact = sum(1 for a, b in population if a == b)
        adjacent = sum(1 for a, b in population if abs(a - b) <= 1)
        lo, hi = _wilson(exact, n)
        bins.append(CalibrationBin(low, high, n, exact / n, adjacent / n, lo, hi, False))
    return GateCalibrationReport(threshold, tuple(bins))


def decision_engine_noninferior(by_engine: Mapping[str, EngineAgreement], *,
                                delta: float | None = None) -> bool | str:
    """Whether the decision engine is no worse than the LLM baseline (NFR-STATS-06): True when its
    alpha is at least the baseline's alpha minus delta (default 0.05), False otherwise, and
    `insufficient_data` when either group is too small. The baseline is `llm_engine_off` only;
    including `llm_fallback` would mix in the cells the engine found hard. The system never
    switches engines because of this (CT-CONF-14)."""
    margin = delta if delta is not None else _env_float(NONINFERIORITY_DELTA_ENV, NONINFERIORITY_DELTA)
    decision = by_engine.get("decision")
    baseline = by_engine.get("llm_engine_off")
    if (decision is None or baseline is None or decision.insufficient_data
            or baseline.insufficient_data or decision.ordinal_alpha is None
            or baseline.ordinal_alpha is None):
        return INSUFFICIENT_DATA
    return decision.ordinal_alpha >= baseline.ordinal_alpha - margin
