"""What one administration's promotion computes per criterion (FR-STATS-32, #879).

`promote` records an administration; this module is the arithmetic it records. Every figure is
per criterion and carries its scoring model, so an atomic line and a holistic line are never
pooled (FR-STATS-03), and a figure that cannot be computed carries the reason instead of a number:

- `kappa` over the paired blind labels, and `qwk` only for an ordinal line of three or more
  declared bands (a two-band line's QWK is its kappa wearing another name);
- `reason = 'too_few_labels'` below two pairs (FR-STATS-31's wording), `'insufficient_data'`
  when a coefficient is 0/0 over a unanimous population;
- per-engine agreement (FR-STATS-26), the decision gate's calibration bins (FR-STATS-27) and the
  non-inferiority verdict (FR-STATS-29), each `insufficient_data` below its minimum;
- the confusion counts, so a reader that pools administrations sums stored counts rather than
  re-reading labels (NFR-STATS-07).

The in-memory and durable promotes both call `criterion_figures`, so the two paths give the same
figures (TC-STATS-42); only the engine context differs, and with none every engine figure reads
`insufficient_data`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .admissibility import _system_side
from .agreement import _band_ordinals, _corrected_statistics
from .engines import (
    INSUFFICIENT_DATA,
    agreement_by_engine,
    decision_engine_noninferior,
    decision_gate_calibration,
)

#: The absent-figure reasons a record may carry (FR-PIPE-20). `skipped` and `none_marked` are an
#: administration's; `too_few_labels` and `insufficient_data` are a figure's.
TOO_FEW_LABELS = "too_few_labels"

#: The decision gate's threshold when no accepted pre-screen row records its own.
_DEFAULT_GATE_THRESHOLD = 0.80


@dataclass(frozen=True)
class EngineContext:
    """How a labelled cell is placed for the engine figures: its engine partition, and, for a cell
    the decision engine answered, the accepted verdict's `(band_confidence, threshold)`. Both
    return None when the store cannot say (an in-memory population has no cells)."""

    partition_of: Callable[[Any], str | None]
    confidence_of: Callable[[Any], tuple[float, float] | None]


NO_ENGINE_CONTEXT = EngineContext(partition_of=lambda _label: None,
                                  confidence_of=lambda _label: None)


def _criterion_of(label: Any) -> str:
    return str(getattr(label, "criterion_id", "") or "")


def _ordinal_pairs(
    paired: Sequence[tuple[Any, Any]], bands: Sequence[str], declared_count: int,
) -> tuple[list[tuple[int, int]], int]:
    """Each pair on the criterion's declared scale when every band is a declared one, else on the
    scale `agreement` infers; and the band count, never below the declared one."""
    if bands and all(str(a) in bands and str(b) in bands for a, b in paired):
        index = {name: position for position, name in enumerate(bands)}
        return ([(index[str(a)], index[str(b)]) for a, b in paired],
                max(len(bands), declared_count))
    ordinals, inferred = _band_ordinals(paired)
    return ordinals, max(declared_count, len(bands), inferred)


def _confusion(ordinals: Sequence[tuple[int, int]], band_count: int) -> list[list[int]]:
    """Rows are the system's band, columns the teacher's, both in ordinal order."""
    matrix = [[0] * band_count for _ in range(band_count)]
    for system, teacher in ordinals:
        matrix[system][teacher] += 1
    return matrix


def _engine_figures(labels: Sequence[Any], context: EngineContext,
                    bands: Sequence[str], declared_count: int) -> dict[str, Any]:
    """Per-engine agreement, the gate's calibration bins and the non-inferiority verdict over one
    criterion's admissible labels, each `insufficient_data` below its minimum."""
    by_engine = agreement_by_engine(labels, context.partition_of)
    records: list[tuple[float, int, int]] = []
    threshold = _DEFAULT_GATE_THRESHOLD
    for label in labels:
        if context.partition_of(label) != "decision":
            continue
        accepted = context.confidence_of(label)
        system, teacher = _system_side(label), getattr(label, "teacher_band", None)
        if accepted is None or system is None or teacher is None:
            continue
        (pair,), _count = _ordinal_pairs([(system, teacher)], bands, declared_count)
        records.append((float(accepted[0]), pair[0], pair[1]))
        threshold = float(accepted[1])
    calibration = decision_gate_calibration(records, threshold=threshold)
    verdict = decision_engine_noninferior(by_engine)
    return {
        "per_engine": {
            name: {"n": figure.n, "ordinal_alpha": figure.ordinal_alpha,
                   "status": INSUFFICIENT_DATA if figure.insufficient_data else "measured"}
            for name, figure in sorted(by_engine.items())
        },
        "gate_bins": [
            {"low": item.low, "high": item.high, "n": item.n,
             "exact_agreement": item.exact_agreement,
             "adjacent_agreement": item.adjacent_agreement,
             "status": INSUFFICIENT_DATA if item.insufficient_data else "measured"}
            for item in calibration.bins
        ],
        "gate_threshold": calibration.threshold,
        "noninferiority": (verdict if isinstance(verdict, str)
                           else ("true" if verdict else "false")),
    }


def criterion_figures(
    admissible: Sequence[Any],
    *,
    band_counts: Mapping[str, int],
    band_names: Mapping[str, Sequence[str]],
    scoring_models: Mapping[str, str],
    context: EngineContext = NO_ENGINE_CONTEXT,
) -> dict[str, dict[str, Any]]:
    """Each criterion's figures over the administration's admissible labels, keyed by criterion.

    Only criteria with admissible labels appear: a deterministic line has no admissible label
    (R53), so it is absent rather than reported as a zero."""
    by_criterion: dict[str, list[Any]] = {}
    for label in admissible:
        by_criterion.setdefault(_criterion_of(label), []).append(label)
    figures: dict[str, dict[str, Any]] = {}
    for criterion in sorted(by_criterion):
        labels = by_criterion[criterion]
        bands = tuple(str(name) for name in band_names.get(criterion, ()) or ())
        declared = int(band_counts.get(criterion) or 0)
        paired = [
            (system, teacher)
            for system, teacher in ((_system_side(label), getattr(label, "teacher_band", None))
                                    for label in labels)
            if system is not None and teacher is not None
        ]
        kappa = qwk = None
        reason: str | None = None
        confusion: list[list[int]] = []
        band_count = max(declared, len(bands))
        matched = sum(1 for system, teacher in paired if str(system) == str(teacher))
        if paired:
            # The confusion counts ride every paired line, one pair included, so a cumulative
            # figure (`cumulative_figures`) pools every pair the record holds.
            ordinals, band_count = _ordinal_pairs(paired, bands, declared)
            confusion = _confusion(ordinals, band_count)
        if len(paired) < 2:
            reason = TOO_FEW_LABELS
        else:
            kappa, weighted, _alpha, _po, _pe = _corrected_statistics(ordinals, band_count)
            qwk = weighted if band_count >= 3 else None
            if kappa is None:
                reason = INSUFFICIENT_DATA
        figures[criterion] = {
            "criterion_id": criterion,
            "scoring_model": scoring_models.get(criterion) or "",
            "n": len(labels),
            "paired": len(paired),
            "matched": matched,
            "kappa": kappa,
            "qwk": qwk,
            "band_count": band_count,
            "bands": list(bands),
            "reason": reason,
            "confusion": confusion,
            **_engine_figures(labels, context, bands, declared),
        }
    return figures


def _stored_extra(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        extra = json.loads(row.get("figures") or "{}")
    except (TypeError, ValueError):
        return {}
    return extra if isinstance(extra, dict) else {}


def _summed(matrices: Sequence[Sequence[Sequence[int]]]) -> list[list[int]]:
    """The cell-wise sum of confusion matrices, each padded to the largest band count (the
    declared scale is the same for one package version, so positions line up)."""
    size = max((len(matrix) for matrix in matrices), default=0)
    total = [[0] * size for _ in range(size)]
    for matrix in matrices:
        for i, row in enumerate(matrix):
            for j, count in enumerate(row):
                total[i][j] += int(count)
    return total


def cumulative_figures(
    figures: Mapping[str, Mapping[str, Any]],
    prior_rows: Sequence[Mapping[str, Any]],
    *,
    backend_profile: str,
    panel_build_ref: str,
) -> dict[str, dict[str, Any]]:
    """Each criterion's figure over the package version's whole record so far (FR-STATS-35):
    this administration's labels pooled with every earlier administration's stored ones on the
    same criterion, backend and panel build, from their stored confusion counts.

    Computed here, when an administration is promoted, and stored beside its own figures, so
    the package record and the validity read's prior record read a stored figure and never
    recompute one (NFR-STATS-07). Atomic and holistic never pool: a criterion has one scoring
    model in a version. `administrations` counts the records pooled."""
    cumulative: dict[str, dict[str, Any]] = {}
    for criterion, figure in sorted(figures.items()):
        earlier = [
            row for row in prior_rows
            if str(row.get("criterion_id")) == criterion
            and str(row.get("backend_profile") or "") == backend_profile
            and str(row.get("panel_build_ref") or "") == panel_build_ref
        ]
        extras = [_stored_extra(row) for row in earlier]
        matrices = [figure.get("confusion") or []] + [extra.get("confusion") or []
                                                      for extra in extras]
        confusion = _summed([matrix for matrix in matrices if matrix])
        band_count = max([len(confusion), int(figure.get("band_count") or 0)]
                         + [int(extra.get("band_count") or 0) for extra in extras])
        ordinals = [(i, j) for i, row in enumerate(confusion)
                    for j, count in enumerate(row) for _ in range(count)]
        kappa = qwk = None
        reason: str | None = None
        if len(ordinals) < 2:
            reason = TOO_FEW_LABELS
        else:
            kappa, weighted, _alpha, _po, _pe = _corrected_statistics(ordinals, band_count)
            qwk = weighted if band_count >= 3 else None
            if kappa is None:
                reason = INSUFFICIENT_DATA
        cumulative[criterion] = {
            "n": int(figure.get("n") or 0) + sum(int(row.get("n") or 0) for row in earlier),
            "paired": len(ordinals),
            "matched": sum(confusion[i][i] for i in range(len(confusion))),
            "kappa": kappa,
            "qwk": qwk,
            "reason": reason,
            "administrations": 1 + len(earlier),
        }
    return cumulative


#: The keys of a criterion's figures that ride the stored row's `figures` JSON (the rest have
#: columns of their own). `cumulative` is the version's pooled figure as of this administration
#: (`cumulative_figures`).
STORED_JSON_KEYS: tuple[str, ...] = (
    "paired", "band_count", "bands", "confusion", "per_engine", "gate_bins",
    "gate_threshold", "noninferiority", "cumulative",
)
