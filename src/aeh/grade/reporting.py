"""The service's rollup and export methods, and the rollup segmentation they share."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from .constants import export_dir
from .schema import GRADE_STATEMENTS
from .records import ClassRollup, GradeError, RollupSegment
from .pdf import _safe_filename_part, _write_student_pdf


def _build_rollup(rows: Iterable[Mapping[str, Any]]) -> ClassRollup:
    """Segment current grade rows by the rubric version that produced them, and
    annotate the versions covered (`CT-CALIB-09`): figures from R0 and R1 never share
    one unannotated figure — they are separated AND annotated, the strictest reading
    of the clause the case admits either way."""
    by_version: dict[str, list[float]] = {}
    for row in rows:
        version = row["package_version_id"] or ""
        by_version.setdefault(version, [])
        if row["total"] is not None:
            by_version[version].append(float(row["total"]))
    segments = tuple(
        RollupSegment(
            rubric_version=version,
            submission_count=len(totals),
            mean_total=(math.fsum(totals) / len(totals)) if totals else None,
        )
        for version, totals in sorted(by_version.items())
    )
    versions = ", ".join(segment.rubric_version or "(unversioned)" for segment in segments)
    annotation = (
        "rubric revision(s) covered: " + versions
        + (
            " — figures are not comparable across rubric revisions (CT-CALIB-09)"
            if len(segments) > 1
            else ""
        )
    )
    return ClassRollup(segments=segments, revision_annotation=annotation)


class ReportingMixin:
    """The run's rollup and grade export."""

    def rollup(self, run_id: str) -> ClassRollup:
        """The run's rollup, segmented by rubric version (§3.14's Protocol member).
        A run normally reads one segment; the segmentation exists so a rollup that
        somehow spans versions can never present one undifferentiated figure
        (`CT-CALIB-09`, RISK-06) — the cohort-wide form is the module-level
        `class_rollup`."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        rows = [
            dict(row)
            for row in cohort.query(
                GRADE_STATEMENTS["select_run_current_for_rollup"], run_id=run_id
            )
        ]
        return _build_rollup(rows)

    def export(self, run_id: str, revision: int, fmt: str = "csv") -> Path:
        """Export a run's grades at a revision (§3.14's Protocol member, `CT-GRADE-16`).

        `fmt="csv"` is this module's declared record mapping: one row per graded
        submission, the full record (state, grade, total, provenance, coverage,
        boundary risk) as columns. `fmt="pdf"` is the per-student feedback set
        (`FR-GRADE-17`): one PDF per graded student, written into a per-export
        subdirectory of the export dir and returned as that directory — the Protocol
        declares one `Path`, and the format's honest unit is the set, so the returned
        path is the set's container and the files are named by student ref inside it.
        The school-facing mapping that pairs the marks CSV with this PDF set is
        `export_grade_artifacts` (`TC-REG-03`'s producer). Any other format is a
        `GradeError` — the declared error for a format the module does not own."""
        if fmt not in ("csv", "pdf"):
            raise GradeError(
                f"export format {fmt!r} is not one of this module's formats "
                "(csv, pdf); the school-facing pair — one CSV of marks and one PDF "
                "per student from a named revision — is export_grade_artifacts "
                "(TC-REG-03, FR-GRADE-17)."
            )
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        if fmt == "csv":
            rows = [
                dict(row)
                for row in cohort.query(
                    GRADE_STATEMENTS["select_run_grades"], run_id=run_id, revision=revision
                )
            ]
            directory = export_dir()
            directory.mkdir(parents=True, exist_ok=True)
            safe_run_id = _safe_filename_part(run_id)
            path = directory / f"grade-{safe_run_id}-rev{revision}.csv"
            columns = [
                "run_id", "submission_id", "revision", "state", "grade", "total",
                "policy_version", "answer_key_ref", "computed_at",
                "criteria_total", "criteria_auto", "criteria_reviewed",
                "criteria_provisional", "criteria_missing",
                "boundary_at_risk", "score_low", "score_high", "missing_criteria",
            ]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow({"run_id": run_id, **row})
            return path
        # The per-student PDF set (FR-GRADE-17): one document per graded student at
        # the named revision, deterministic bytes, in a directory named for the
        # export — the same move the CSV's revision-bearing filename makes.
        rows = [
            dict(row)
            for row in cohort.query(
                GRADE_STATEMENTS["select_run_grades_with_students"],
                run_id=run_id,
                revision=revision,
            )
        ]
        if not rows:
            raise GradeError(
                f"no grade rows exist for run {run_id!r} at revision {revision} — "
                "there is nothing to export, and an empty export would be a lie"
            )
        directory = export_dir() / f"grade-{_safe_filename_part(run_id)}-rev{revision}"
        directory.mkdir(parents=True, exist_ok=True)
        for row in rows:
            _write_student_pdf(
                directory / f"{_safe_filename_part(str(row['student_ref']))}.pdf",
                run_id=run_id,
                revision=revision,
                student_ref=str(row["student_ref"]),
                total=row["total"],
                grade=row["grade"],
                state=row["state"],
                coverage=(
                    int(row["criteria_total"]),
                    int(row["criteria_auto"]),
                    int(row["criteria_reviewed"]),
                    int(row["criteria_provisional"]),
                    int(row["criteria_missing"]),
                ),
                missing=tuple(json.loads(row["missing_criteria"] or "[]")),
            )
        return directory
