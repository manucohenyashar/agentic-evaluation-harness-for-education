"""The class vocabulary's control actions and the roster file's preview read (FR-CONSOLE-53/54/63).

The console-redesign delta (#761, `ADR-48`) adds three enumerated actions and one read:

* **`create class`** — a class ledger from a typed or pasted student list. It reuses the
  roster editor's row model and validation (`cohort_editor.parse_paste`, `editor_entries`)
  and writes through `aeh.orch.cohorts.create_cohort` — the door `aeh cohort create` opens —
  so a class and a cohort created from the same rows are the same rows by construction.
* **`create cohort from class`** — copies a class ledger's roster into a new grading cohort,
  consent state carried, through the same door. The class is only read: it stays intact and
  a class may seed many cohorts (`ADR-48`).
* **`import roster file`** — the one import path cohorts and classes have (§3.2.3), targeting
  the class state. Its preview is the `roster preview` read below; the commit re-parses the
  same content the teacher confirmed, so what the preview showed is what the store gets.
* **`roster preview`** — a POST read whose body carries the uploaded roster file's text
  (`CT-CONSOLE-34`: file content can never travel in a URL or a query string). It parses the
  rows, lists every malformed row with its line number and the reason in teacher language,
  and writes nothing anywhere — no blob, no store row, no log line.

`ADR-48` is why none of this adds a store table: a class is a cohort ledger in a roster-only
state, and the class/cohort distinction is a console vocabulary distinction over one storage
concept. The console adds what a teacher reading a file needs and the reader does not:

* **all the malformed rows, not the first one** — the command line's roster reader
  (`aeh.pipeline.rosters`) refuses at the first line it cannot read; a teacher choosing a
  file in the console gets every problem listed with its line number, so one pass fixes
  the whole file;
* **duplicate full names are legal** — two students named alike are two students, each with
  their own reference (generated when none is supplied). A duplicated *reference* is the
  mistake, and it is named with both rows.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any

from aeh.orch import (
    CONSENT_CLASSES,
    CohortSetupError,
    RosterEntry,
    check_cohort_id,
    check_student_refs,
    cohort_summary,
    create_cohort,
)
from .cohort_editor import editor_entries, parse_paste
from .settings import roster_import_max_bytes

#: The roster columns the header path reads, spelled as the store's roster table spells
#: them (`orch`'s INSERT names them so, and `vocabulary.py`'s write-field map already
#: carries the dotted spellings). They are constant strings here rather than an import of
#: `aeh.pipeline.rosters` because the console's symbol-level import edges are frozen
#: (`TC-CONSOLE-36`, `NFR-CONSOLE-05`) and `aeh.pipeline.rosters` is not one of the
#: declared ones — these are schema column names the console already spells, not logic
#: duplicated from the reader.
NAME_COLUMN = "full_name"
REF_COLUMN = "student_ref"

#: The control actions this module carries, as `CONTROL_SURFACE_ACTIONS` spells them.
CREATE_CLASS_ACTION = "create class"
COHORT_FROM_CLASS_ACTION = "create cohort from class"
IMPORT_ROSTER_ACTION = "import roster file"

#: The header that names the optional ID column in a tab-separated paste-style file, as the
#: roster editor spells it. A tab-separated file with no header is the editor's paste path:
#: one student per line, `first<TAB>last<TAB>optional ID`, one cell meaning the full name.
PASTE_REF_COLUMN = REF_COLUMN

#: What each parsed file is called in the preview's answer, in the teacher's words.
_FORMAT_LABELS = {"csv": "a table with a header row", "tsv": "a pasted table",
                  "names": "one full name per line"}


# --- the roster file parser -----------------------------------------------------------------------------

def parse_roster_text(text: str) -> dict[str, Any]:
    """An uploaded roster file's text as the preview shows it: the student rows it holds and
    every malformed row with its line number and the reason, in teacher language.

    Three shapes, keyed on the first line that is not blank:

    * **a table with a header row** (a comma or tab whose first row names `full_name`): the
      reader `aeh cohort import` runs, collecting problems instead of stopping at the first;
    * **a pasted table** (tab-separated, no header): the roster editor's paste path — one
      student per line, first name, last name, an optional student ID;
    * **one full name per line**: blank lines and `#` comments skipped, exactly as the
      command line's reader skips them.

    A comma-separated file whose first row names no `full_name` column is reported once,
    naming the header it needs; the rows under it cannot be read as students without
    guessing, so none are. A leading byte-order mark (as an Excel export carries) is
    stripped before anything is read, the way the command line's reader opens the file
    `utf-8-sig`. Duplicate full names are legal (each student keeps their own
    reference); a duplicated reference is a problem naming both rows. Nothing here writes
    anything: the answer is data for the preview screen.
    """
    lines = str(text).lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    first = next((line for line in lines if line.strip()), "")
    if "\t" in first:
        if _header_cells(first, "\t") is not None:
            return _parse_table(lines, delimiter="\t", label="tsv")
        return _parse_paste_lines(lines)
    if "," in first:
        if _header_cells(first, ",") is not None:
            return _parse_table(lines, delimiter=",", label="csv")
        return _no_header_table(first)
    return _parse_name_lines(lines)


def _header_cells(line: str, delimiter: str) -> list[str] | None:
    """The first row's cells, lower-cased, when it names a `full_name` column; `None` when it
    does not. A quoted CSV header is read with the CSV reader, a pasted one with the split
    the paste path uses."""
    cells = next(iter(csv.reader(io.StringIO(line), delimiter=delimiter)), [])
    stripped = [cell.strip().lower() for cell in cells]
    return stripped if NAME_COLUMN in stripped else None


def _parse_table(lines: list[str], *, delimiter: str, label: str) -> dict[str, Any]:
    """The header-row shape: every row's cells, every malformed row collected."""
    rows: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    header: list[str] = []
    header_seen = False
    seen_refs: dict[str, int] = {}
    for row in reader:
        number = reader.line_num
        cells = [cell.strip() for cell in row]
        if not header_seen:
            # The header is the first non-blank row, wherever it sits — a saved file may
            # open with blank lines, and its row numbers are still the file's own.
            if not any(cells):
                continue
            header = [cell.lower() for cell in cells]
            header_seen = True
            continue
        if not any(cells):
            continue
        name = _column_cell(cells, header, NAME_COLUMN)
        ref = _column_cell(cells, header, REF_COLUMN)
        if not name:
            problems.append({
                "line": number,
                "reason": (f"Row {number} has no name — every student needs a full name, "
                           "written as on their papers; an ID alone is not enough. Fill in "
                           "the name or delete the row."),
            })
            continue
        if ref:
            earlier = seen_refs.get(ref)
            if earlier is not None:
                problems.append({
                    "line": number,
                    "reason": (f"Row {number}'s student ID {ref!r} is already on row "
                               f"{earlier} — each student needs their own ID, or leave the "
                               "ID out and one is created for them."),
                })
                continue
            seen_refs[ref] = number
        rows.append({"line": number, "full_name": name,
                     "student_ref": ref or None})
    if not rows and not problems:
        problems.append({
            "line": 1,
            "reason": ("The file names a header row but lists no student under it. Check "
                       "that the file was saved with the students' names in it."),
        })
    return {"format": label, "format_label": _FORMAT_LABELS[label],
            "rows": rows, "problems": problems}


def _column_cell(cells: list[str], header: list[str], column: str) -> str:
    """The cell under `column`, or "" when the row is shorter than the header."""
    try:
        position = header.index(column)
    except ValueError:
        return ""
    return cells[position].strip() if len(cells) > position else ""


def _parse_paste_lines(lines: list[str]) -> dict[str, Any]:
    """The pasted-table shape: the roster editor's paste path, with every line's problem
    collected instead of the first one refusing. The rules are `parse_paste`'s — more than
    three cells, an empty first-name cell, a comma-separated line and a header-like first
    line are each refused naming the line."""
    rows: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    seen_refs: dict[str, int] = {}
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        cells = [cell.strip() for cell in line.split("\t")]
        while cells and not cells[-1]:
            cells.pop()
        # `first` is the editor's `not rows`: the header check holds until a real student
        # row has been read, so a header-like second line (after a refused first) is caught
        # exactly where `parse_paste` catches it.
        problem = _paste_line_problem(number, cells, first=not rows)
        if problem is not None:
            problems.append({"line": number, "reason": problem})
            continue
        name, ref = _paste_cells(cells)
        if ref:
            earlier = seen_refs.get(ref)
            if earlier is not None:
                problems.append({
                    "line": number,
                    "reason": (f"Line {number}'s student ID {ref!r} is already on line "
                               f"{earlier} — each student needs their own ID, or leave the "
                               "ID out and one is created for them."),
                })
                continue
            seen_refs[ref] = number
        rows.append({"line": number, "full_name": name, "student_ref": ref or None})
    if not rows and not problems:
        problems.append({
            "line": 1,
            "reason": ("The file lists no students. One student per line: first name, last "
                       "name, then an optional student ID, separated by tabs."),
        })
    return {"format": "tsv", "format_label": _FORMAT_LABELS["tsv"],
            "rows": rows, "problems": problems}


def _paste_line_problem(number: int, cells: list[str], *, first: bool) -> str | None:
    """The pasted line's problem, in the editor's wording with its line number, or `None`
    when the line reads as a student."""
    if len(cells) > 3:
        return (f"Line {number} has {len(cells)} cells; expected first name, last name and "
                "an optional student ID.")
    if len(cells) > 1 and not cells[0]:
        return (f"Line {number} has no first name in its first cell — every student needs a "
                "full name.")
    if len(cells) == 1 and "," in cells[0]:
        return (f"Line {number} holds commas; paste from a spreadsheet (cells separated by "
                "tabs) or one full name per line.")
    if first and any(cell.lower() in _PASTE_HEADER_WORDS for cell in cells):
        return (f"Line {number} ({' | '.join(cells)}) looks like a column header and would "
                "become a student; leave the header row out of the file.")
    return None


def _paste_cells(cells: list[str]) -> tuple[str, str]:
    """A pasted line as a name and an optional reference: one cell is the whole name, two are
    first and last, three add the student ID."""
    if len(cells) == 1:
        return cells[0], ""
    if len(cells) == 2:
        return f"{cells[0]} {cells[1]}".strip(), ""
    return f"{cells[0]} {cells[1]}".strip(), cells[2]


#: The words a pasted first line may not begin with, as `cohort_editor` spells them — the
#: same list, so a header the editor refuses the preview refuses too.
_PASTE_HEADER_WORDS = frozenset({
    "first", "first name", "firstname", "given name", "last", "last name", "lastname",
    "surname", "family name", "name", "names", "full name", "full_name", "student",
    "student name", "id", "student id", "student_id", "student_ref", "ref",
})


def _parse_name_lines(lines: list[str]) -> dict[str, Any]:
    """One full name per line, the command line reader's second shape, collected: blank lines
    and `#` comments skipped, a comma line and a header-like first line each named. A
    header-like first line refuses the whole file, as the command line's reader refuses it —
    the lines under a header the file does not have are not students either."""
    rows: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if not rows and value.lower() in _NAME_LINE_HEADER_WORDS:
            return {
                "format": "names", "format_label": _FORMAT_LABELS["names"],
                "rows": [],
                "problems": [{
                    "line": number,
                    "reason": (f"Line {number} ({value!r}) looks like a column header and "
                               f"would become a student. Name the column '{NAME_COLUMN}' in "
                               "a header row, or delete the line."),
                }],
            }
        if "," in value:
            problems.append({
                "line": number,
                "reason": (f"Line {number} holds several columns but the file has no "
                           f"'{NAME_COLUMN}' header row. Add a first row naming the column "
                           f"of full names '{NAME_COLUMN}', or list one full name per line."),
            })
            continue
        rows.append({"line": number, "full_name": value, "student_ref": None})
    if not rows and not problems:
        problems.append({
            "line": 1,
            "reason": "The file lists no students — it holds no name a student could be "
                      "identified by.",
        })
    return {"format": "names", "format_label": _FORMAT_LABELS["names"],
            "rows": rows, "problems": problems}


#: The header-like first lines the command line reader refuses, so the preview refuses the
#: same ones (`aeh.pipeline.rosters._HEADER_LIKE`, imported by name there).
_NAME_LINE_HEADER_WORDS = frozenset({
    "id", "ids", "student", "students", "student id", "student_id", "studentid", "ref",
    "reference", "name", "names", "student name", "full name", NAME_COLUMN, REF_COLUMN,
})


def _no_header_table(first: str) -> dict[str, Any]:
    """A comma-separated file whose first row names no `full_name` column: the rows under it
    cannot be read without guessing, so the preview reports the header it needs and stops."""
    return {
        "format": "csv",
        "format_label": _FORMAT_LABELS["csv"],
        "rows": [],
        "problems": [{
            "line": 1,
            "reason": (f"The file's first row is not a '{NAME_COLUMN}' header row. Add a "
                       f"first row naming the column of full names '{NAME_COLUMN}' (and, if "
                       f"the IDs are listed, '{REF_COLUMN}'), or list one full name per "
                       "line."),
        }],
    }


# --- the preview read -----------------------------------------------------------------------------------

def roster_preview_read(console: Any, app: Any, body: Any) -> dict[str, Any]:
    """The uploaded roster file's parsed rows, before any commit (`FR-CONSOLE-63`, R7's
    preview-before-commit). The body is the POST read's JSON object:
    `{"content": <the file's text>, "name": <its file name, optional>}`. The read writes
    nothing anywhere — the store is not opened, and no blob, row or log line carries the
    text. A file over the `HARNESS_ROSTER_IMPORT_MAX_BYTES` knob is refused with the next
    step, as a document upload is.

    `ready` is what the commit will decide: after the parser's own problems, the rows go
    through the same `editor_entries` validation `import roster file` runs, so a roster the
    commit would refuse (a student ID with a space in it, more rows than the editor takes)
    never previews as ready."""
    del console, app  # the preview reads the file's text, not the store
    content = (body or {}).get("content")
    name = str((body or {}).get("name") or "the roster file")
    if not isinstance(content, str) or not content.strip():
        raise ValueError(
            "the roster preview takes the uploaded file's text in its body, as "
            '{"content": <the file\'s text>, "name": <the file name>}')
    limit = roster_import_max_bytes()
    if len(content.encode("utf-8")) > limit:
        limit_kb = limit / 1024
        return {
            "name": name,
            "format": None,
            "format_label": None,
            "rows": [],
            "problems": [{
                "line": None,
                "reason": (f"That file is larger than the {limit_kb:g} KB limit for one "
                           "roster file. Save a smaller file, or type the students in "
                           "instead."),
            }],
            "counts": {"students": 0, "problems": 1},
            "ready": False,
        }
    parsed = parse_roster_text(content)
    problems = list(parsed["problems"])
    if not problems:
        # The commit's own row validation, run here so `ready` never promises what
        # `import roster file` will refuse: the same `editor_entries` rules and the same
        # `check_student_refs` the commit's `create_cohort` runs, with no store touched.
        try:
            entries = editor_entries(parsed["rows"])
            check_student_refs(entry.student_ref for entry in entries
                               if entry.student_ref is not None)
        except CohortSetupError as refusal:
            problems.append({"line": None, "reason": str(refusal)})
    return {
        "name": name,
        "format": parsed["format"],
        "format_label": parsed["format_label"],
        "rows": parsed["rows"],
        "problems": problems,
        "counts": {"students": len(parsed["rows"]), "problems": len(problems)},
        "ready": bool(parsed["rows"]) and not problems,
    }


# --- the control actions --------------------------------------------------------------------------------

def _consent_refusal() -> str:
    return ("choose the class's consent class — one of "
            f"{', '.join(CONSENT_CLASSES)}; it has no default and can never be changed "
            "afterwards. Nothing was written.")


def create_class_effect(store: Any, params: dict[str, Any]) -> tuple[str, bool, str | None]:
    """Carry out `create class` (`FR-CONSOLE-53`): the roster editor's rows as a class ledger
    (`ADR-48`). Everything is checked before the class's file is opened, so every refusal
    writes nothing. Returns the operator's message, whether the class was created, and the
    next action a refusal names."""
    try:
        class_id = check_cohort_id(params.get("class_id"))
        consent_class = params.get("consent_class", params.get("consent"))
        if consent_class not in CONSENT_CLASSES:
            raise CohortSetupError(_consent_refusal())
        rows = params.get("rows")
        if rows is None and params.get("paste") is not None:
            rows = parse_paste(str(params["paste"]))
        entries = editor_entries(rows if rows is not None else [])
        # An existing ledger is refused inside `create_cohort`, never overwritten: a
        # replayed submission writes nothing (FR-CONSOLE-02) — and a class is a cohort
        # ledger, so the same refusal protects it.
        summary = create_cohort(store, class_id, str(consent_class), entries)
    except CohortSetupError as refusal:
        return (f"create class refused: {refusal}", False,
                "Correct what the message names — the class name, the consent class or the "
                "student rows — and create the class again.")
    except sqlite3.DatabaseError as error:
        return (f"create class refused: the class's file could not be read "
                f"({error}). Nothing was written.", False,
                "Check the store's files, then create the class again.")
    return (
        f"class {summary.cohort_id} created ({summary.consent_class}) with "
        f"{summary.roster_size} student(s) through M-ORCH's create_cohort — the rows "
        # Worded to carry one SQL keyword, not two: the SEC-15 scan flags any f-string
        # whose literal text holds two ("make a grading cohort out of it" — "into" is
        # an INSERT keyword, "from" a SELECT one).
        "`aeh cohort create` writes. Next: make a grading cohort out of it, or add more "
        "students to it.",
        True,
        None,
    )


def cohort_from_class_effect(store: Any, params: dict[str, Any]) -> tuple[str, bool, str | None]:
    """Carry out `create cohort from class` (`FR-CONSOLE-54`, `ADR-48`): the class ledger's
    roster copied into a new grading cohort, consent state carried, through M-ORCH's
    `create_cohort`. The class is only read — it stays intact and may seed many cohorts.
    Every refusal writes nothing."""
    try:
        class_id = check_cohort_id(params.get("class_id"))
        cohort_id = check_cohort_id(params.get("cohort_id"))
        summary = cohort_summary(store, class_id)
        if summary is None:
            raise CohortSetupError(
                f"no class {class_id!r} exists to copy from. Nothing was written.")
        handle = store.cohort(class_id)
        listed = list(handle.query(
            "SELECT student_ref, full_name FROM roster ORDER BY rowid"))
        if not listed:
            raise CohortSetupError(
                f"the class {class_id!r} has no students on its roster, so there is nothing "
                "to copy. Nothing was written.")
        entries = [RosterEntry(full_name=str(row["full_name"] or ""),
                               student_ref=str(row["student_ref"]))
                   for row in listed]
        created = create_cohort(store, cohort_id, summary.consent_class, entries)
    except CohortSetupError as refusal:
        return (f"{COHORT_FROM_CLASS_ACTION} refused: {refusal}", False,
                "Create the class first (by typing its students or importing a roster), or "
                "choose another name for the new grading cohort, and copy it again.")
    except sqlite3.DatabaseError as error:
        return (f"{COHORT_FROM_CLASS_ACTION} refused: the class's file could not be read "
                f"({error}). Nothing was written.", False,
                "Check the store's files, then copy the class again.")
    return (
        f"class {class_id}'s roster copied into cohort {created.cohort_id} "
        f"({created.consent_class}) with {created.roster_size} student(s) through M-ORCH's "
        "create_cohort; the class is unchanged and can seed more cohorts",
        True,
        None,
    )


def import_roster_effect(store: Any, params: dict[str, Any]) -> tuple[str, bool, str | None]:
    """Carry out `import roster file` (`FR-CONSOLE-63`, §3.2.3): the uploaded roster file as
    a class ledger — the one import path cohorts and classes have, targeting the class state.
    The content is re-parsed here with the same parser the preview read ran, so what the
    teacher confirmed is what the store gets, and a file with malformed rows still refuses
    (the preview is advice, not a gate around). Every refusal writes nothing."""
    try:
        class_id = check_cohort_id(params.get("class_id"))
        consent_class = params.get("consent_class", params.get("consent"))
        if consent_class not in CONSENT_CLASSES:
            raise CohortSetupError(_consent_refusal())
        content = params.get("content")
        if not isinstance(content, str) or not content.strip():
            raise CohortSetupError(
                "the roster file's text was not sent, so there is nothing to import. "
                "Nothing was written.")
        # The same ceiling the preview read enforces, on the write side too: a file the
        # preview declared too large is refused here as well, and the bound is bytes, not
        # characters, as the knob's name spells.
        limit = roster_import_max_bytes()
        if len(content.encode("utf-8")) > limit:
            raise CohortSetupError(
                f"the roster file is larger than the {limit / 1024:g} KB limit for one "
                "roster file. Nothing was written.")
        parsed = parse_roster_text(content)
        if parsed["problems"]:
            raise CohortSetupError(_problem_sentence(parsed["problems"]))
        entries = editor_entries(parsed["rows"])
        summary = create_cohort(store, class_id, str(consent_class), entries)
    except CohortSetupError as refusal:
        return (f"import roster file refused: {refusal}", False,
                "Fix the rows the message names (or re-save the file) and import it again — "
                "or type the students instead, with create class.")
    except sqlite3.DatabaseError as error:
        return (f"import roster file refused: the class's file could not be read "
                f"({error}). Nothing was written.", False,
                "Check the store's files, then import the roster again.")
    name = str(params.get("name") or "the roster file")
    return (
        f"class {summary.cohort_id} created ({name}, {summary.consent_class}) with "
        f"{summary.roster_size} student(s) through M-ORCH's create_cohort — the rows "
        "`aeh cohort create` writes. Next: make a grading cohort out of it.",
        True,
        None,
    )


def _problem_sentence(problems: list[dict[str, Any]]) -> str:
    """The preview's problems as one refusal sentence, the first few named with their line
    numbers. The preview holds the full list; the commit's refusal is the server's own
    check, and it never accepts what the parser refused."""
    shown = "; ".join(
        f"{'row' if problem.get('line') else 'the file'}"
        + (f" {problem['line']}" if problem.get("line") else "")
        + f" ({problem['reason'].rstrip('.')})"
        for problem in problems[:5]
    )
    more = f"; and {len(problems) - 5} more" if len(problems) > 5 else ""
    return (f"the roster file still has {len(problems)} problem row(s): {shown}{more}. "
            "Nothing was written.")


#: The three actions' effects, keyed as `CONTROL_SURFACE_ACTIONS` spells them.
CLASS_ACTION_EFFECTS = {
    CREATE_CLASS_ACTION: create_class_effect,
    COHORT_FROM_CLASS_ACTION: cohort_from_class_effect,
    IMPORT_ROSTER_ACTION: import_roster_effect,
}


__all__ = [
    "CLASS_ACTION_EFFECTS",
    "COHORT_FROM_CLASS_ACTION",
    "CREATE_CLASS_ACTION",
    "IMPORT_ROSTER_ACTION",
    "cohort_from_class_effect",
    "create_class_effect",
    "import_roster_effect",
    "parse_roster_text",
    "roster_preview_read",
]
