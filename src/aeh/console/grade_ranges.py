"""Boundary fields on the results and student reads (FR-CONSOLE-94, CT-CONSOLE-59; #869).

Per student, M-GRADE's `boundary_at_risk`, `score_low` and `score_high` (FR-GRADE-05) exactly as
the current `submission_grade` row stores them — read, never recomputed here, so a stored row
that says something the console would not have computed is served as it says it. When the run's
test declares a boundary table, the grade letters at each end of the range (`grade_low`,
`grade_high`) ride beside them, resolved through M-PKG's own boundary lookup; without one the two
keys are absent, not null.

Per run, `boundary_risk_count` counts the students whose unreviewed lines could move their grade.
While a blind draw is open the drawn students' own fields are held back (`held_back.TOTAL_KEYS`),
so they are left out of the count too: a count beside the visible at-risk students would
otherwise say which hidden students are at risk (the #909 class-figure leak).
"""

from __future__ import annotations

from typing import Any

#: The per-student keys this module adds (and `held_back` hides for a drawn student).
BOUNDARY_KEYS: tuple[str, ...] = (
    "boundary_at_risk", "score_low", "score_high", "grade_low", "grade_high",
)


def _boundary_lookup(app: Any, run_row: Any) -> tuple[Any, str] | None:
    """The run's package catalog and version when the version declares a boundary table, else
    None (no table: no grade letters)."""
    run_id = str(run_row["run_id"])
    version = str(run_row["package_version_id"] or "")
    try:
        catalog = app._run_catalog(run_id)
        if catalog is None or not version or not catalog.boundaries(version):
            return None
    except Exception:  # noqa: BLE001 — an unreadable package declares no table to read
        return None
    return catalog, version


def has_boundary_table(app: Any, run_row: Any) -> bool:
    """Whether the run's test declares a boundary table (so grade letters exist at all)."""
    return _boundary_lookup(app, run_row) is not None


def _letter(lookup: tuple[Any, str], score: Any) -> str | None:
    if score is None:
        return None
    catalog, version = lookup
    return catalog.boundary_for(version, float(score))


def boundary_fields(app: Any, run_row: Any) -> dict[str, dict[str, Any]]:
    """Each student's boundary fields for the run, by submission, from the stored grade rows."""
    from aeh.grade import run_grade_boundaries

    try:
        stored = run_grade_boundaries(app._store, str(run_row["run_id"]))
    except Exception:  # noqa: BLE001 — a run with no grade ledger has no boundary fields
        return {}
    lookup = _boundary_lookup(app, run_row)
    fields: dict[str, dict[str, Any]] = {}
    for submission_id, row in stored.items():
        entry = dict(row)
        if lookup is not None:
            entry["grade_low"] = _letter(lookup, row["score_low"])
            entry["grade_high"] = _letter(lookup, row["score_high"])
        fields[submission_id] = entry
    return fields


def boundary_risk_count(app: Any, run_id: str, fields: dict[str, dict[str, Any]]) -> int:
    """How many students' unreviewed lines could move their grade, leaving out the students
    whose fields an open blind draw holds back."""
    from .held_back import drawn_lines

    try:
        drawn = drawn_lines(app, run_id)
    except Exception:  # noqa: BLE001 — a draw that cannot be read hides nobody
        drawn = None
    hidden = drawn.submissions if drawn is not None else set()
    return sum(1 for submission_id, entry in fields.items()
               if int(entry.get("boundary_at_risk") or 0) and submission_id not in hidden)
