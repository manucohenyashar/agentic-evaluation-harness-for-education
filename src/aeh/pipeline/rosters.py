"""Reading a roster file for `aeh cohort` (live-test blocker B3; names since #620, ADR-38).

Students are identified by the name written on their papers (`FR-INGEST-39`); a student ID is
optional and never the only way a student is listed (`FR-INGEST-40`). A roster decides which papers
intake's identity check (V3) accepts, so this reader never guesses: a file it cannot read
unambiguously is refused, naming the line, rather than turned into a different list of students.
Validation of each entry (and the IDs-only refusal both surfaces share) is `aeh.orch.cohorts`'s.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from aeh.orch.cohorts import CohortSetupError, RosterEntry

#: The header that names the name column in a CSV (the roster table's own column).
NAME_COLUMN = "full_name"

#: The header that names the optional student-ID column in a CSV.
REF_COLUMN = "student_ref"


#: First lines that look like a header someone meant to name a column with. Read as a name, the
#: header would become a student, so a one-name-per-line file starting with one of these is refused
#: and pointed at the `full_name` header.
_HEADER_LIKE = frozenset({"id", "ids", "student", "students", "student id", "student_id",
                          "studentid", "ref", "reference", "name", "names", "student name",
                          "full name", NAME_COLUMN, REF_COLUMN})


def read_roster_file(path: str | Path) -> tuple[RosterEntry, ...]:
    """The roster entries in a roster file, in file order.

    Two shapes, and nothing in between:

    * **A CSV whose first row names a `full_name` column**, and optionally a `student_ref`
      column (any positions; other columns are ignored). Fully blank rows are skipped; a row with
      other cells but an empty `full_name` is refused, naming its line, because every student
      needs a name. An empty `student_ref` cell is fine: a ref is generated for that student.
    * **One full name per line.** Blank lines and lines starting with `#` are skipped. A line
      holding a comma is refused (that is a CSV without a `full_name` header), and so is a first
      line that looks like a header (`name`, `student_ref`, ...), which would become a student.

    A CSV naming `student_ref` but no `full_name` is an IDs-only roster and is refused: students
    are identified by name. A UTF-8 byte-order mark (what Excel on Windows writes) and Windows
    line endings are handled.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    header = [cell.strip().lower() for cell in rows[0]] if rows else []
    if NAME_COLUMN in header:
        return _read_csv(path, rows, header)
    if REF_COLUMN in header:
        raise CohortSetupError(
            f"{path}: the roster has a '{REF_COLUMN}' column but no '{NAME_COLUMN}' column — "
            f"an IDs-only roster is refused: every student needs a full name, written as on "
            f"their papers; IDs may stay beside the names. Nothing was written.")
    return _read_name_lines(path, text)


def _read_csv(path: str | Path, rows: list[list[str]], header: list[str]
              ) -> tuple[RosterEntry, ...]:
    name_at = header.index(NAME_COLUMN)
    ref_at = header.index(REF_COLUMN) if REF_COLUMN in header else None
    entries: list[RosterEntry] = []
    for line, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        name = _cell(row, name_at)
        if not name:
            raise CohortSetupError(
                f"{path}: line {line} has no {NAME_COLUMN}; every student needs a full name "
                f"(an ID alone is not enough). Fill it in or delete the row. Nothing was "
                f"written.")
        ref = _cell(row, ref_at) if ref_at is not None else ""
        entries.append(RosterEntry(full_name=name, student_ref=ref or None))
    return tuple(entries)


def _cell(row: list[str], column: int) -> str:
    return row[column].strip() if len(row) > column else ""


def _read_name_lines(path: str | Path, text: str) -> tuple[RosterEntry, ...]:
    entries: list[RosterEntry] = []
    for line, raw in enumerate(text.splitlines(), start=1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if "," in value:
            raise CohortSetupError(
                f"{path}: line {line} has several columns but the file has no '{NAME_COLUMN}' "
                f"header. Add a first row naming the column of full names '{NAME_COLUMN}' (and "
                f"any student IDs '{REF_COLUMN}'), or list one full name per line. Nothing was "
                f"written.")
        if not entries and value.lower() in _HEADER_LIKE:
            raise CohortSetupError(
                f"{path}: line {line} ({value!r}) looks like a header and would become a "
                f"student. Name the column '{NAME_COLUMN}' in a CSV, or delete the line. Nothing "
                f"was written.")
        entries.append(RosterEntry(full_name=value))
    return tuple(entries)
