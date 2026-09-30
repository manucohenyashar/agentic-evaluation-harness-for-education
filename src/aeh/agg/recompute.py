"""Recomputing a stored score's confidence from the stored row alone."""

from __future__ import annotations

from typing import Any

from .settings import AGG_CAP_TABLE
from .rows import (
    _AGG_FAVOURABLE,
    _RECORDED_SIGNAL_FIELDS,
    _row_value,
    _signal_adverse,
    _WRITTEN_SIGNAL_FIELDS,
)
from .aggregate import _band_position_prior


def recompute_confidence(row: Any, criterion: Any, *, config: Any = None) -> float | None:
    """Recompute a stored score's confidence from the stored row alone (NFR-AGG-04).

    More detail: `docs/code-notes/agg.md`, section `recompute.py: recompute_confidence`.
    """
    caps = getattr(config, "caps", None) if config is not None else None
    cap_table = dict(AGG_CAP_TABLE) if caps is None else dict(caps)

    judge_count = _row_value(row, "judge_count")
    if judge_count is None:
        return None
    judge_count = int(judge_count)
    # The HLD §9.6 constraint is also the re-derivation's: 0 or odd. A
    # deterministic row (judge_count 0) has no confidence to re-derive; an even
    # panel is a failed write, not a figure.
    if judge_count <= 0 or judge_count % 2 == 0:
        return None

    base = _row_value(row, "confidence_base")
    if base is None and judge_count >= 3:
        # Legacy rows predate the base column: the stored agreement is the
        # criterion-declared alpha reading, exact wherever the panel reached
        # the declared top band (the two readings coincide there — and for any
        # panel whose spread never leaves the declared scale's top band).
        base = _row_value(row, "agreement")
    if base is None and judge_count == 1:
        ordinal = _row_value(row, "ordinal")
        if ordinal is not None:
            base = _band_position_prior(int(ordinal), int(criterion.band_count))
    if base is None:
        return None

    confidence = float(base)
    fields = _RECORDED_SIGNAL_FIELDS
    if _row_value(row, "caps_fired") is not None:
        fields = fields + _WRITTEN_SIGNAL_FIELDS
    for field in fields:
        if not _signal_adverse(_row_value(row, field), _AGG_FAVOURABLE[field]):
            continue
        # The same conditional cap the aggregator applied (§3.12): the row's
        # `evidence_present` caps only where the criterion requires evidence,
        # read fail-closed when the criterion does not declare the flag.
        if field == "evidence_present" and not getattr(
            criterion, "evidence_required", True
        ):
            continue
        cap = cap_table.get(field)
        if cap is not None:
            confidence = min(confidence, float(cap))
    return confidence
