"""The results workbook export: the run's marks as an `.xlsx` workbook (FR-CONSOLE-58).

`openpyxl` writes the workbook (ADR-49, the supply-chain suite's fifth runtime entry),
and it is lazy-imported HERE, inside the call path that needs it — the fast tier never
loads it, exactly like the PDF and image libraries (`NFR-SYS-06`, `TC-INGEST-01`).

The workbook is the marks CSV's rows in workbook form — the same statement, the same
columns, the same mark formatting as `export_grade_artifacts` — so the two exports
cannot disagree about what the run's grades are. RS-15's risk is a workbook that lies
about the run, in the two directions a spreadsheet can lie: rows silently truncated
(there is no row cap anywhere in this module), and formulas standing where values
should be (any text beginning with `=` is forced back to a string cell, so a student
reference or a name can never arrive as a formula). A run with zero graded papers is
not refused the way the CSV export refuses it: the workbook exports its headings and
carries the teacher note in the sheet, because an empty workbook that says so is
honest, and a refused export is one the teacher cannot file.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aeh.store import Store

from .exports import _MARKS_COLUMNS
from .records import GradeError
from .schema import GRADE_STATEMENTS
from .service import GradingService


#: The media type an `.xlsx` answer carries.
WORKBOOK_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


#: The teacher sentence a zero-graded run's workbook carries (RS-15's boundary): the
#: headings only, and why. Teacher language — no module names, no status codes.
EMPTY_RUN_NOTE = (
    "No graded papers are in this run at this revision yet, so the sheet carries "
    "the headings only; every student's mark appears here once grading settles."
)


@dataclass(frozen=True)
class WorkbookExport:
    """What one workbook export did, beside the bytes: the row count the sheet carries
    (so a caller can compare it with the store's own count), the columns, whether the
    zero-graded note was written, and the statements the export read through — the
    stage-level trace the result carries rather than a bare success."""

    body: bytes
    content_type: str
    run_id: str
    revision: int
    rows_written: int
    columns: tuple[str, ...]
    empty_note: bool
    queries: tuple[str, ...]


def grade_workbook_bytes(run_id: str, revision: int, *, store: Store) -> WorkbookExport:
    """The run's marks at the named revision as workbook bytes.

    The rows are `select_run_grades_with_students`' — the same rows the marks CSV
    carries, in the same order, so the two exports answer the run identically and the
    read-back oracle can compare the sheet against the store's digest row for row.
    A run the store does not hold is still `GradeError` (the caller's mistake); a run
    that simply has no graded papers yet exports its headings and the teacher note.
    """
    from openpyxl import Workbook  # lazy: the fast tier never loads openpyxl (NFR-SYS-06)

    cohort = GradingService(store)._find_run(run_id)[0]  # noqa: SLF001 — the export's own door
    rows = [
        dict(row)
        for row in cohort.query(
            GRADE_STATEMENTS["select_run_grades_with_students"],
            run_id=run_id,
            revision=revision,
        )
    ]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Results"
    sheet.append(list(_MARKS_COLUMNS))
    for row in rows:
        sheet.append(_row_cells(row, run_id=run_id, revision=revision))
    if not rows:
        # RS-15's boundary: headers only, and the note beside them — never an empty
        # sheet that reads as a lost run, never a truncated one that reads as complete.
        sheet.append([EMPTY_RUN_NOTE])
    _force_text_cells(sheet)
    return WorkbookExport(
        body=_deterministic_zip(workbook),
        content_type=WORKBOOK_CONTENT_TYPE,
        run_id=run_id,
        revision=revision,
        rows_written=len(rows),
        columns=tuple(_MARKS_COLUMNS),
        empty_note=not rows,
        queries=("select_grade_run", "select_run_grades_with_students"),
    )


def _row_cells(row: dict[str, Any], *, run_id: str, revision: int) -> list[Any]:
    """One grade row's cells, in `_MARKS_COLUMNS` order, values not formulas.

    The mark is a number (two decimals, as the CSV formats it) and the revision an
    integer; the text columns are written as they stand — the values-not-formulas
    guarantee is enforced on the sheet itself by `_force_text_cells`, so a stored text
    that begins with `=` (a student reference, a name) cannot arrive as a formula."""
    return [
        run_id,
        revision,
        row["student_ref"],
        row["submission_id"],
        None if row["total"] is None else round(float(row["total"]), 2),
        row["grade"] or "",
        row["state"],
        row["full_name"] or "",
    ]


def _force_text_cells(sheet: Any) -> None:
    """Every string cell whose text begins with `=` is re-typed as a string.

    This is the whole of the values-not-formulas guarantee: a run's stored rows are
    values, and no stored text — a student reference, a full name, a state — may reach
    the sheet as a formula the spreadsheet computes on open. openpyxl inferred a
    formula (data type `f`) from the leading `=` at assignment; forcing the type back
    to `s` keeps the value verbatim, and the read-back round-trips it unchanged. The
    pass runs over exactly the cells the sheet carries, so nothing outside the
    export's own content is touched."""
    for row in sheet.iter_rows():
        for cell in row:
            if cell.data_type == "f" and isinstance(cell.value, str):
                cell.data_type = "s"


def export_grade_workbook(
    run_id: str,
    revision: int,
    dest: Path | str,
    *,
    store: Store,
) -> WorkbookExport:
    """The bytes form written into `dest` as the `.xlsx` file — the door a CLI or a
    caller that wants the file uses; the console read takes `grade_workbook_bytes`."""
    export = grade_workbook_bytes(run_id, revision, store=store)
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(export.body)
    return export


#: The fixed instant the workbook's document properties carry. openpyxl stamps
#: `dcterms:created` at construction and re-stamps `dcterms:modified` at save, on the
#: wall clock, inside `docProps/core.xml` — the two volatile fields in an otherwise
#: content-only file — and the save-time re-stamp cannot be pinned through the
#: properties object at all, so the archive rebuild rewrites both values in place.
_FIXED_CORE_TIMESTAMP = "2000-01-01T00:00:00Z"

_CORE_TIMESTAMP = re.compile(
    r"(<dcterms:(?:created|modified)\b[^>]*>)[^<]*(</dcterms:(?:created|modified)>)"
)


def _deterministic_zip(workbook: Any) -> bytes:
    """The workbook's bytes, byte-stable for the same store state.

    The volatile fields are all moments of the export. openpyxl stamps the document
    properties (`dcterms:created`/`dcterms:modified` in `docProps/core.xml`) with the
    wall clock — `modified` unconditionally at save time, after any pinning through the
    properties object — and saves through `zipfile`, whose entries carry the saving
    moment too. So the archive is rebuilt entry by entry with the epoch timestamp, and
    the one content-bearing entry that leaks the clock (`docProps/core.xml`) has both
    timestamps rewritten to a fixed instant on the way through. Entry order and
    compression come from openpyxl's own write and are unchanged, and the creator
    string is openpyxl's constant, not a volatile field."""
    buffer = io.BytesIO()
    workbook.save(buffer)
    entries: list[tuple[str, bytes, int]] = []
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive:
        for info in archive.infolist():
            data = archive.read(info.filename)
            if info.filename == "docProps/core.xml":
                data = _CORE_TIMESTAMP.sub(
                    r"\g<1>" + _FIXED_CORE_TIMESTAMP + r"\g<2>",
                    data.decode("utf-8"),
                ).encode("utf-8")
            entries.append((info.filename, data, info.compress_type))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for name, data, compress_type in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = compress_type
            target.writestr(info, data)
    return out.getvalue()
