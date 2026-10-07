"""The roster editor: create a cohort and load its roster from names (FR-CONSOLE-42, FR-INGEST-40).

The console writes nothing of its own here. It turns the editor's rows (first name, last name, an
optional student ID) into roster entries and hands them to `aeh.orch.cohorts.create_cohort` — the
function `aeh cohort create` calls — so the two surfaces write the same rows for the same students
by construction, and refuse the same rosters with the same requirement.

What the console adds is what a teacher typing into a grid needs and a file reader does not:

* **row-numbered refusals** — an empty name is refused naming the editor's row, before any file
  is opened, so a refused roster writes nothing (no partial cohort);
* **paste tolerance** — a block pasted from a spreadsheet or a list (one student per line,
  tab-separated cells) is split into rows here, server-side: the SPA holds no business rule
  (`M-UI`), so how a paste becomes students is decided once, in Python.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from aeh.orch import (
    CONSENT_CLASSES,
    NAME_REQUIREMENT,
    CohortSetupError,
    RosterEntry,
    add_to_roster,
    check_cohort_id,
    create_cohort,
)

#: The control action the editor writes through (`CONTROL_SURFACE_ACTIONS`).
CREATE_COHORT_ACTION = "create cohort"

#: The statement the editor shows beside the ID column (FR-CONSOLE-42: "a visible statement that
#: the ID is optional"). Served by the API so the SPA renders it verbatim rather than restating it.
STUDENT_ID_OPTIONAL = (
    "Student ID is optional. Students are identified by the name written on their papers; "
    "add an ID only if your school uses one, and never instead of a name.")

#: What each consent class means, in the words `aeh cohort create --consent` uses (ADR-5).
CONSENT_CLASS_MEANINGS: dict[str, str] = {
    "synthetic": "made-up practice work",
    "consented": "the students or their guardians agreed",
    "real": "real student work without that agreement",
}

#: The cells of one pasted line, in order. The ID cell may be absent.
PASTE_COLUMNS = ("first_name", "last_name", "student_ref")

#: Cells that name a column rather than a student; a pasted first line holding one is a header.
_HEADER_WORDS = frozenset({
    "first", "first name", "firstname", "given name", "last", "last name", "lastname",
    "surname", "family name", "name", "names", "full name", "full_name", "student",
    "student name", "id", "student id", "student_id", "student_ref", "ref",
})

#: The most rows one editor submission may carry; a larger paste is a mistake, not a class.
MAX_EDITOR_ROWS = 2000


def roster_editor_payload() -> dict[str, Any]:
    """The editor's fixed copy and choices, as the API's `roster editor` read answers them."""
    return {
        "action": CREATE_COHORT_ACTION,
        "columns": [
            {"field": "first_name", "label": "First name", "required": True},
            {"field": "last_name", "label": "Last name", "required": True},
            {"field": "student_ref", "label": "Student ID (optional)", "required": False},
        ],
        "student_id_optional": STUDENT_ID_OPTIONAL,
        "name_requirement": NAME_REQUIREMENT,
        "consent_classes": [
            {"value": value, "meaning": CONSENT_CLASS_MEANINGS.get(value, value)}
            for value in CONSENT_CLASSES
        ],
        "consent_default": None,
        "paste": ("One student per line. Cells separated by tabs (as copied from a spreadsheet): "
                  "first name, last name, then an optional student ID. A line with one cell is "
                  "read as the full name."),
    }


def parse_paste(text: str) -> list[dict[str, str]]:
    """A pasted block as editor rows: one per non-blank line, tab-separated cells.

    One cell is the whole name (`"Amara Okafor"`); two are first and last name; three add the
    student ID. Anything this reader cannot split unambiguously is refused naming its line (as
    the teacher sees it, blank lines counted) rather than turned into a different student: more
    than three cells, an empty first-name cell, a comma-separated line (the ID would land
    inside the name — the CLI's line reader refuses it too), and a first line that is a header.
    """
    rows: list[dict[str, str]] = []
    lines = str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        cells = [cell.strip() for cell in line.split("\t")]
        while cells and not cells[-1]:
            cells.pop()
        _check_pasted_line(number, cells, first=not rows)
        if len(cells) == 1:
            rows.append({"full_name": cells[0]})
        else:
            rows.append(dict(zip(PASTE_COLUMNS, cells)))
    return rows


def _check_pasted_line(number: int, cells: list[str], *, first: bool) -> None:
    if len(cells) > len(PASTE_COLUMNS):
        raise CohortSetupError(
            f"pasted line {number} has {len(cells)} cells; expected first name, last name and "
            "an optional student ID. Nothing was written.")
    if len(cells) > 1 and not cells[0]:
        raise CohortSetupError(
            f"pasted line {number} has no first name in its first cell — {NAME_REQUIREMENT}. "
            "Nothing was written.")
    if len(cells) == 1 and "," in cells[0]:
        raise CohortSetupError(
            f"pasted line {number} holds commas; paste from a spreadsheet (cells separated by "
            "tabs) or one full name per line. Nothing was written.")
    if first and any(cell.lower() in _HEADER_WORDS for cell in cells):
        raise CohortSetupError(
            f"pasted line {number} ({' | '.join(cells)}) looks like a column header and would "
            "become a student; leave the header row out of the paste. Nothing was written.")


def editor_entries(rows: Any) -> list[RosterEntry]:
    """The editor's rows as roster entries, or `CohortSetupError` naming the requirement and,
    for a single nameless row among named ones, the row (1-based, as the editor numbers them)."""
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise CohortSetupError(
            "the roster must be a list of rows, each with a first and last name and an "
            "optional student ID. Nothing was written.")
    if len(rows) > MAX_EDITOR_ROWS:
        raise CohortSetupError(
            f"the roster has {len(rows)} rows; at most {MAX_EDITOR_ROWS} are accepted at once. "
            "Nothing was written.")
    # A wholly blank row (the grid's trailing empty line) is skipped, as the CLI's CSV reader
    # skips one; rows keep the numbers the editor shows.
    numbered = [(number, RosterEntry(full_name=_full_name(row), student_ref=_ref(row)))
                for number, row in enumerate(rows, start=1)
                if any(str(value or "").strip() for value in row.values())]
    entries = [entry for _number, entry in numbered]
    nameless = [number for number, entry in numbered if not entry.full_name]
    if entries and len(nameless) == len(entries):
        raise CohortSetupError(
            f"the roster lists student IDs only and no names — {NAME_REQUIREMENT}. Nothing was "
            "written.")
    if nameless:
        shown = ", ".join(str(number) for number in nameless[:10])
        raise CohortSetupError(
            f"row {shown} has no name — {NAME_REQUIREMENT}. Fill in the name or delete the "
            f"row. Nothing was written." if len(nameless) == 1 else
            f"rows {shown} have no name — {NAME_REQUIREMENT}. Fill in the names or delete the "
            f"rows. Nothing was written.")
    return entries


def _full_name(row: Mapping[str, Any]) -> str:
    """`first last`, the way the CLI's file spells the same student's `full_name`; a row that
    already carries `full_name` (a one-cell pasted line) is taken as written."""
    whole = row.get("full_name")
    if whole is not None and str(whole).strip():
        return str(whole).strip()
    parts = (str(row.get(key) or "").strip() for key in ("first_name", "last_name"))
    return " ".join(part for part in parts if part)


def _ref(row: Mapping[str, Any]) -> str | None:
    ref = row.get("student_ref")
    return None if ref is None or not str(ref).strip() else str(ref).strip()


def create_cohort_effect(store: Any, params: Mapping[str, Any]) -> tuple[str, bool]:
    """Carry out `create cohort` on a real store: everything is checked before the cohort's file
    is opened, so every refusal writes nothing. Returns the operator's message and whether the
    cohort was created."""
    try:
        cohort_id = check_cohort_id(params.get("cohort_id"))
        consent_class = params.get("consent_class", params.get("consent"))
        if consent_class not in CONSENT_CLASSES:
            raise CohortSetupError(
                f"choose the cohort's consent class — one of {', '.join(CONSENT_CLASSES)}; it "
                "has no default and can never be changed afterwards. Nothing was written.")
        rows = params.get("rows")
        if rows is None and params.get("paste") is not None:
            rows = parse_paste(str(params["paste"]))
        entries = editor_entries(rows if rows is not None else [])
        # An existing cohort is refused inside `create_cohort`, never overwritten: a replayed
        # submission writes nothing (FR-CONSOLE-02).
        summary = create_cohort(store, cohort_id, str(consent_class), entries)
    except CohortSetupError as refusal:
        return f"create cohort refused: {refusal}", False
    except sqlite3.DatabaseError as error:
        # An unreadable existing cohort file: the store's own refusal, reported, never a 500.
        return (f"create cohort refused: the cohort's file could not be read "
                f"({type(error).__name__}: {error}). Nothing was written.", False)
    return (
        f"cohort {summary.cohort_id} created ({summary.consent_class}) with "
        f"{summary.roster_size} student(s) through M-ORCH's create_cohort — the rows "
        "`aeh cohort create` writes",
        True,
    )


def add_students_effect(store: Any, params: Mapping[str, Any]) -> tuple[str, bool]:
    """Carry out `add students` on a real store: the roster editor loading late students into an
    existing cohort, through M-ORCH's `add_to_roster` — the door `aeh cohort add-students` opens.
    Everything is checked before the cohort's file is written, so a refusal adds nobody."""
    try:
        cohort_id = check_cohort_id(params.get("cohort_id"))
        rows = params.get("rows")
        if rows is None and params.get("paste") is not None:
            rows = parse_paste(str(params["paste"]))
        entries = editor_entries(rows if rows is not None else [])
        # `add_to_roster` refuses an unknown cohort and a reference already on the roster, naming
        # it, so a replayed submission writes nothing (FR-CONSOLE-02).
        summary = add_to_roster(store, cohort_id, entries)
    except CohortSetupError as refusal:
        return f"add students refused: {refusal}", False
    except sqlite3.DatabaseError as error:
        return (f"add students refused: the cohort's file could not be read "
                f"({type(error).__name__}: {error}). Nothing was written.", False)
    return (
        f"cohort {summary.cohort_id}'s roster extended to {summary.roster_size} student(s) "
        "through M-ORCH's add_to_roster — the rows `aeh cohort add-students` writes",
        True,
    )


__all__ = [
    "CREATE_COHORT_ACTION",
    "STUDENT_ID_OPTIONAL",
    "add_students_effect",
    "create_cohort_effect",
    "editor_entries",
    "parse_paste",
    "roster_editor_payload",
]
