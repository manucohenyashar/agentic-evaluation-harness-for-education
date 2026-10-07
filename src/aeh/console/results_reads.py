"""The results views' reads (FR-CONSOLE-44, #631): the class rollup, the per-student
records, and the school-facing export's bytes — each through the door the `aeh results`
subcommands call, so the console's views and the CLI's output are one implementation."""

from __future__ import annotations

import tempfile
from typing import Any

from aeh.grade import GradeError, export_grade_artifacts, run_class_view, run_grade_records


def _run_id_of(query: Any, read: str) -> str:
    run_id = str(query.get("run_id") or "")
    if not run_id:
        raise ValueError(f"{read} names no run")
    return run_id


def results_class_read(app: Any, query: Any) -> dict[str, Any]:
    """The class view: the run's rollup (`{"rollup": ...}`), through `run_class_view` —
    the same JSON `aeh results show` prints. Raises `ValueError` for a missing run id and
    for a run no ledger holds (the caller's mistake, the same refusal the export read
    answers with)."""
    try:
        return run_class_view(app._store, _run_id_of(query, "results class"))
    except GradeError as refusal:
        raise ValueError(str(refusal)) from refusal


def results_student_read(app: Any, query: Any) -> dict[str, Any]:
    """The per-student view: the run's grade records (`{"students": [...]}`), through
    `run_grade_records` — the records the CLI's `aeh results show` prints and the ledger
    holds. Raises `ValueError` for a missing run id and for a missing run, the same
    refusal the export read answers with."""
    try:
        return {"students": run_grade_records(app._store, _run_id_of(query, "results student"))}
    except GradeError as refusal:
        raise ValueError(str(refusal)) from refusal


def results_export_read(app: Any, query: Any) -> Any:
    """The school-facing export's bytes (TC-CONSOLE-57): the named revision's marks CSV,
    or one student's PDF (`student_ref`, named as the export names its PDFs — the
    `student_ref` identity column's safe form). The bytes are produced by
    `export_grade_artifacts` — the CLI export's own producer — written into a temporary
    directory and read back, so the console serves the same bytes a CLI export writes,
    and writes nothing durable of its own.

    Raises `ValueError` naming the gap for a missing run id, an unknown format, a
    revision that is not a number, a PDF with no student named, or a student the export
    produced no PDF for; `GradeError` for a run or revision with no grade rows."""
    run_id = _run_id_of(query, "results export")
    fmt = str(query.get("format") or "").strip().lower()
    if fmt not in ("csv", "pdf"):
        raise ValueError(f"results export format {fmt!r} is neither 'csv' nor 'pdf'")
    raw_revision = str(query.get("revision") or "1")
    try:
        revision = int(raw_revision)
    except ValueError as exc:
        raise ValueError(f"results export revision {raw_revision!r} is not a number") from exc
    student_ref = str(query.get("student_ref") or "")
    if fmt == "pdf" and not student_ref:
        raise ValueError("a PDF export names its student (student_ref)")

    with tempfile.TemporaryDirectory(prefix="aeh-console-export-") as tmp:
        try:
            artifacts = export_grade_artifacts(run_id, revision, tmp, store=app._store)
        except GradeError as refusal:
            # A missing run or revision is a refusal, not a crash (FR-CONSOLE-44's
            # revision semantics are the CLI's).
            raise ValueError(str(refusal)) from refusal
        if fmt == "csv":
            path = artifacts.csv_path
        else:
            path = next((p for p in artifacts.pdf_paths if p.stem == student_ref), None)
            if path is None:
                raise ValueError(
                    f"the export produced no PDF for student {student_ref!r} of run "
                    f"{run_id!r} at revision {revision}"
                )
        with open(path, "rb") as f:
            body = f.read()

    from .api import FileAnswer

    content_type = "text/csv; charset=utf-8" if fmt == "csv" else "application/pdf"
    return FileAnswer(body, content_type)
