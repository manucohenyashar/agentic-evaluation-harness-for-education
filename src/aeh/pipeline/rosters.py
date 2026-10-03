"""Reading a roster file for `aeh cohort` (live-test blocker B3).

A roster decides which papers intake's identity check (V3) accepts, so this reader never guesses:
a file it cannot read unambiguously is refused, naming the line, rather than turned into a
different list of students. Validation of each reference is `aeh.orch.cohorts`'s.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from aeh.orch.cohorts import CohortSetupError

#: The header that names the reference column in a CSV.
REF_COLUMN = "student_ref"


#: First lines that look like a header someone meant to name the column with. Read as a
#: reference, the header would become a student, so a single-column file starting with one of
#: these is refused and pointed at `student_ref`.
_HEADER_LIKE = frozenset({"id", "ids", "student", "students", "student id", "student_id",
                          "studentid", "ref", "reference", "name", "names", "student name"})


def read_roster_file(path: str | Path) -> tuple[str, ...]:
    """The student references in a roster file, in file order.

    Two shapes, and nothing in between:

    * **One reference per line.** Blank lines and lines starting with `#` are skipped. A line
      holding a comma is refused (that is a CSV without a `student_ref` header), and so is a
      first line that looks like a header (`id`, `name`, ...), which would become a student.
    * **A CSV whose first row names a `student_ref` column** (any position; other columns, such
      as names, are ignored). Fully blank rows are skipped; a row with other cells but an empty
      `student_ref` is refused, naming its line, because skipping it would drop a student.

    A UTF-8 byte-order mark (what Excel on Windows writes) and Windows line endings are handled.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    header = [cell.strip().lower() for cell in rows[0]] if rows else []
    if REF_COLUMN in header:
        column = header.index(REF_COLUMN)
        refs: list[str] = []
        for line, row in enumerate(rows[1:], start=2):
            if not any(cell.strip() for cell in row):
                continue
            value = row[column].strip() if len(row) > column else ""
            if not value:
                raise CohortSetupError(
                    f"{path}: line {line} has no {REF_COLUMN}; fill it in or delete the row. "
                    f"Nothing was written.")
            refs.append(value)
        return tuple(refs)
    refs = []
    for line, raw in enumerate(text.splitlines(), start=1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if "," in value:
            raise CohortSetupError(
                f"{path}: line {line} has several columns but the file has no '{REF_COLUMN}' "
                f"header. Add a first row naming the column of student IDs '{REF_COLUMN}', or "
                f"list one ID per line. Nothing was written.")
        if not refs and value.lower() in _HEADER_LIKE:
            raise CohortSetupError(
                f"{path}: line {line} ({value!r}) looks like a header and would become a "
                f"student. Name the column '{REF_COLUMN}', or delete the line. Nothing was "
                f"written.")
        refs.append(value)
    return tuple(refs)
