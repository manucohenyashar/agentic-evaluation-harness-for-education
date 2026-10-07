"""The run's results as the two surfaces read them (#631, FR-CONSOLE-44).

The console's results views and the `aeh results show | export` subcommands answer the
same questions about a run — its per-student grade records and its class rollup. This
module is the one implementation both call, so the two surfaces cannot drift: the
console's JSON reads and the CLI's printed JSON are built from the same records, and
TC-CONSOLE-57 compares them record for record against the stored ledger.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from .schema import GRADE_STATEMENTS
from .service import GradingService


def run_grade_records(store: Any, run_id: str) -> list[dict[str, Any]]:
    """The run's per-student records: the CURRENT revision's grade, total, state and the
    five coverage counters — the columns the vocabulary calls `GRADE_KEYS +
    COVERAGE_KEYS`, and the same mapping the school-facing export reads its coverage
    from. Ordered by submission id.

    Raises `GradeError` for a run no cohort ledger of this store holds."""
    cohort, _row = GradingService(store)._find_run(run_id)  # fail-closed on a missing run
    return [
        dict(row)
        for row in cohort.query(
            GRADE_STATEMENTS["select_run_current_grade_records"], run_id=run_id
        )
    ]


def run_class_view(store: Any, run_id: str) -> dict[str, Any]:
    """The class view: the run's rollup (`ClassRollup` — M-GRADE's version-split
    segments) as JSON-ready plain data. Raises `GradeError` for a missing run."""
    return {"rollup": _rollup_json(GradingService(store).rollup(run_id))}


def run_results(store: Any, run_id: str) -> dict[str, Any]:
    """Both views at once — what `aeh results show` prints as JSON. Raises `GradeError`
    for a missing run."""
    students = run_grade_records(store, run_id)
    rollup = GradingService(store).rollup(run_id)
    return {"students": students, "rollup": _rollup_json(rollup)}


def _rollup_json(rollup: Any) -> Any:
    """A `ClassRollup` as JSON-ready plain data (`dataclasses.asdict` recurses into the
    frozen `RollupSegment`s)."""
    return dataclasses.asdict(rollup)
