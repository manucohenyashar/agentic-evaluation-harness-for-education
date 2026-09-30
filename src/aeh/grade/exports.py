"""The school-facing export: one feedback PDF per student and a marks CSV."""

from __future__ import annotations

import csv
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from aeh.store import Store

from .constants import STATE_FINAL
from .refs import _content_hash
from .schema import GRADE_STATEMENTS
from .records import GradeArtifacts, GradeError
from .pdf import _safe_filename_part, _write_student_pdf
from .service import GradingService


#: The school-facing export's reference cohort — the content the `TC-REG-03`
#: baselines are recorded against, reproducible from the shipped module alone. Four
#: students, four distinct marks (distinct documents are the point: identical
#: per-student PDFs would mean the export is not reading the student it names), one
#: fixed issuance timestamp. The `cohort_with_mixed_revisions` precedent: a fixture
#: seam on the module because the case names the module as its surface; built
#: through this module's own insert statement, so the rows are exactly the rows the
#: service writes.
_REFERENCE_EXPORT_RUN = "RUN-0001"


_REFERENCE_EXPORT_STAMP = "2026-08-01T09:00:00+00:00"


_REFERENCE_EXPORT_POPULATION: tuple[tuple[str, str, float, str], ...] = (
    ("S-0001", "student-001", 71.0, "B"),
    ("S-0002", "student-002", 64.5, "C"),
    ("S-0003", "student-003", 83.25, "A"),
    ("S-0004", "student-004", 58.0, "D"),
)


def _reference_export_cohort(run_id: str) -> tuple[Store, Any, Path]:
    """The reference cohort's `(store, cohort handle, store root)`, used when the school-facing
    export is called without a store; this is the golden baseline's reproducible world. Any other
    run id without a store is a caller mistake. The caller closes the store and removes the
    directory when done."""
    from aeh.store import open_store

    if run_id != _REFERENCE_EXPORT_RUN:
        raise GradeError(
            f"export_grade_artifacts needs the run's store: none was passed and "
            f"{run_id!r} is not the module's reference run "
            f"({_REFERENCE_EXPORT_RUN!r}, the golden export's reproducible content)"
        )
    root = Path(tempfile.mkdtemp(prefix="aeh-grade-export-ref-"))
    store = open_store(root)
    cohort_id = f"c-ref-{uuid.uuid4().hex[:10]}"
    handle = store.cohort(cohort_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES (:c, 'synthetic', :t)",
            c=cohort_id, t=_REFERENCE_EXPORT_STAMP,
        )
        for submission_id, student_ref, total, grade in _REFERENCE_EXPORT_POPULATION:
            tx.execute(
                "INSERT INTO submission (submission_id, cohort_id, student_ref) "
                "VALUES (:s, :c, :r)",
                s=submission_id, c=cohort_id, r=student_ref,
            )
            tx.execute(
                GRADE_STATEMENTS["insert_grade"],
                run_id=run_id,
                submission_id=submission_id,
                revision=1,
                state=STATE_FINAL,
                grade=grade,
                total=total,
                policy_version=_content_hash(["fixture", "export-reference"]),
                answer_key_ref=_content_hash(["fixture-key", "export"]),
                package_version_id="pkg-reference",
                computed_at=_REFERENCE_EXPORT_STAMP,
                finalized_at=_REFERENCE_EXPORT_STAMP,
                criteria_total=2,
                criteria_auto=2,
                criteria_reviewed=0,
                criteria_provisional=0,
                criteria_missing=0,
                boundary_at_risk=0,
                score_low=None,
                score_high=None,
                missing_criteria="[]",
                amendments="[]",
            )
    return store, handle, root


#: The school-facing marks mapping (`TC-REG-03`'s baseline covers it, order
#: included). The `mark` column is the one the baseline's first comparison lifts
#: out: a moved mark is a defect, not a layout change, and the mapping is the only
#: part of this export the grading owner may accept a diff on.
_MARKS_COLUMNS = (
    "run_id", "revision", "student_ref", "submission_id", "mark", "grade", "state",
)


def export_grade_artifacts(
    run_id: str,
    revision: int,
    dest: Path | str,
    store: Store | None = None,
) -> GradeArtifacts:
    """The school-facing export (FR-GRADE-17, TC-REG-03): one CSV of marks and one PDF per student,
    written into `dest`, from the named revision. Exporting a named revision is what makes the
    amendment trail usable: revision 1's export reproduces the marks as first delivered.

    The marks CSV is `_MARKS_COLUMNS` verbatim; the PDFs are named by student ref,
    one per student the CSV carries, byte-deterministic (see `_student_pdf_bytes`).
    Without a store the export reads the module's reference cohort — the content the
    committed baselines describe; with one, the run's own ledger."""
    owns_reference = store is None
    reference_root: Path | None = None
    if owns_reference:
        store, cohort, reference_root = _reference_export_cohort(run_id)
    else:
        cohort = GradingService(store)._find_run(run_id)[0]
    try:
        rows = [
            dict(row)
            for row in cohort.query(
                GRADE_STATEMENTS["select_run_grades_with_students"],
                run_id=run_id,
                revision=revision,
            )
        ]
    finally:
        if owns_reference:
            # The reference cohort is scaffolding: once the rows are read, the
            # ephemeral ledger is closed and its directory removed — the export's
            # output is the files in `dest`, and a leaked handle per call would be
            # a resource bug the golden case's own reuse would multiply.
            store.close()
            shutil.rmtree(reference_root, ignore_errors=True)
    if not rows:
        raise GradeError(
            f"no grade rows exist for run {run_id!r} at revision {revision} — "
            "there is nothing to export, and an empty export would be a lie"
        )
    directory = Path(dest)
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / f"grade-{_safe_filename_part(run_id)}-rev{revision}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        # LF terminators, not the csv module's platform default: the committed
        # baseline is pinned to LF in the working tree on every platform
        # (.gitattributes' fixtures rule), so the producer must emit the bytes
        # the checkout carries — the marks file is a regression baseline, and a
        # line ending the OS chose would fail every fresh clone.
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(_MARKS_COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    run_id,
                    revision,
                    row["student_ref"],
                    row["submission_id"],
                    "" if row["total"] is None else f"{float(row['total']):.2f}",
                    row["grade"] or "",
                    row["state"],
                ]
            )
    pdf_paths = tuple(
        directory / f"{_safe_filename_part(str(row['student_ref']))}.pdf"
        for row in rows
    )
    for path, row in zip(pdf_paths, rows):
        _write_student_pdf(
            path,
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
    return GradeArtifacts(csv_path=csv_path, pdf_paths=pdf_paths)
