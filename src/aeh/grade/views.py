"""The per-criterion view of one submission's grade (FR-GRADE-22): composites as one line."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from .constants import ROUTING_TRIAGE
from .records import CriterionLine
from .schema import GRADE_STATEMENTS
from .stored_rows import _amendment_map, _row_value, _with_amendments


def _awarded_points(rows: Iterable[Any]) -> dict[str, float]:
    """Each criterion's awarded points from its stored score row — the same rows the grade
    computation counts: a row with points, outside triage."""
    return {
        str(_row_value(row, "criterion_id")): float(points)
        for row in rows
        if (points := _row_value(row, "points")) is not None
        and _row_value(row, "routing") != ROUTING_TRIAGE
    }


def _composite_line(
    criterion_id: str, aspects: tuple[str, ...], awarded: Mapping[str, float],
    maxima: Mapping[str, float | None],
) -> CriterionLine:
    """A composite's one line: the sum of its aspects' awarded points over the sum of their
    maxima (FR-PKG-25). Any unscored aspect leaves the sum unknown, never partial."""
    scored = all(aspect in awarded for aspect in aspects)
    aspect_maxima = [maxima.get(aspect) for aspect in aspects]
    return CriterionLine(
        criterion_id=criterion_id,
        awarded=math.fsum(awarded[a] for a in aspects) if scored and aspects else None,
        max_points=(
            math.fsum(m for m in aspect_maxima if m is not None)
            if all(m is not None for m in aspect_maxima)
            else None
        ),
        aspects=aspects,
    )


class CriterionViewMixin:
    """The per-criterion view the console and the reports read."""

    def criterion_lines(self, run_id: str, submission_id: str) -> tuple[CriterionLine, ...]:
        """One submission's per-criterion view, one line per presented criterion, sorted by
        criterion id (FR-GRADE-22). A composite is presented as one line — the sum of its
        aspects' awarded points over the sum of their maxima — and its aspects appear beneath
        it (`aspects`), not as lines of their own; each aspect keeps its own score row, audit
        record and review path. The current grade's amendments apply, as in the total.
        Read-only."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        surface = self._policy_surface(
            self._store.package(run["package_id"]),
            run["package_id"],
            run["package_version_id"],
        )
        rows = cohort.query(
            GRADE_STATEMENTS["select_submission_scores"], run_id=run_id,
            submission_id=submission_id,
        )
        current = cohort.query(
            GRADE_STATEMENTS["select_current_grade"], run_id=run_id,
            submission_id=submission_id,
        )
        overrides = _amendment_map(current[0]["amendments"]) if current else {}
        awarded = _awarded_points(_with_amendments(rows, overrides) if overrides else rows)
        maxima: Mapping[str, float | None] = surface["max_points"]
        composites: Mapping[str, tuple[str, ...]] = surface["composites"]
        folded = {aspect for aspects in composites.values() for aspect in aspects}
        lines = [
            CriterionLine(
                criterion_id=criterion_id,
                awarded=awarded.get(criterion_id),
                max_points=maxima.get(criterion_id),
            )
            for criterion_id in surface["criteria_ids"]
            if criterion_id not in folded
        ]
        lines.extend(
            _composite_line(criterion_id, aspects, awarded, maxima)
            for criterion_id, aspects in composites.items()
        )
        return tuple(sorted(lines, key=lambda line: line.criterion_id))
