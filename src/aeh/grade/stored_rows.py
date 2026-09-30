"""Reading stored score rows, with a grade's amendment overrides applied in memory."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping


def _row_value(row: Any, field: str) -> Any:
    """Read one field of a stored score row, whatever its shape (`sqlite3.Row`, dict, or an object
    with attributes). A missing field reads as None, meaning "not recorded"."""
    if isinstance(row, dict):
        return row.get(field)
    if hasattr(row, "keys"):
        try:
            return row[field] if field in row.keys() else None
        except (IndexError, KeyError):
            return None
    return getattr(row, field, None)


def _amendment_map(amendments_raw: Any) -> dict[str, float]:
    """The overrides one grade row's `amendments` JSON records, exactly as `amend()` applied them,
    so a recomputation can apply them again (FR-GRADE-13). Amendments live only on the grade row,
    so recomputing from stored scores alone would undo them. A missing or empty column means no
    amendments."""
    if not amendments_raw:
        return {}
    entries = json.loads(amendments_raw)
    return {
        entry["criterion_id"]: float(_row_value(entry, "points"))
        for entry in entries
    }


def _with_amendments(rows: Iterable[Any], overrides: Mapping[str, float]) -> list[Any]:
    """The stored score rows with the amendment overrides applied in memory; nothing is written
    (CT-GRADE-14). An override applies only where the criterion has a stored row with points."""
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
