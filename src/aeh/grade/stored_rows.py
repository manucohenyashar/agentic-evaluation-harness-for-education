"""Reading stored score rows, with a grade's amendment overrides applied in memory."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping


def _row_value(row: Any, field: str) -> Any:
    """A tolerant read of one field off a stored score row — agg.py's `_row_value`
    idiom, mirrored here because the criterion-score rows this module reads arrive
    in every storage face (`sqlite3.Row`, `dict`, attribute carrier) and the
    accessor is whichever the row answers to. A missing field reads as `None`
    ("not recorded"), which is exactly how a quarantined extraction leaves the
    ledger."""
    if isinstance(row, dict):
        return row.get(field)
    if hasattr(row, "keys"):
        try:
            return row[field] if field in row.keys() else None
        except (IndexError, KeyError):
            return None
    return getattr(row, field, None)


def _amendment_map(amendments_raw: Any) -> dict[str, float]:
    """The override map one grade row's `amendments` JSON records — the exact map
    `amend()` applied, read back so a recomputation can replay it (`FR-GRADE-13`'s
    exactness reaches amended revisions too: the amendment lives only on the grade
    row — `CT-GRADE-14` forbids writing `criterion_score` — so a pass that recomputed
    from the stored scores alone would "revert" every amendment; replaying the
    recorded map first is what makes an unchanged re-run write nothing). An absent
    or empty column reads as no amendments."""
    if not amendments_raw:
        return {}
    entries = json.loads(amendments_raw)
    return {
        entry["criterion_id"]: float(_row_value(entry, "points"))
        for entry in entries
    }


def _with_amendments(rows: Iterable[Any], overrides: Mapping[str, float]) -> list[Any]:
    """The stored score rows with amendment overrides applied in memory — snapshots,
    never ledger writes (`CT-GRADE-14`). An override lands only where the criterion
    has a stored row carrying points; `amend()` refuses an edit that would apply
    nowhere, and an override against a `NULL`-points row is a no-op here exactly as
    the computation treats such a row."""
    adjusted = []
    for row in rows:
        override = overrides.get(row["criterion_id"])
        if override is not None and _row_value(row, "points") is not None:
            snapshot = dict(row)
            snapshot.update(points=override)
            adjusted.append(snapshot)
        else:
            adjusted.append(row)
    return adjusted
