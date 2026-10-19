"""The teacher's corrections to a class and its papers (FR-CONSOLE-64..68).

Each is an enumerated control action (`CT-CONSOLE-30`) whose effect belongs to another module,
so this file only reads the teacher's choice out of the request, calls the owning door and
says what happened in the teacher's words:

* **rename student** / **remove student** — M-ORCH's `rename_on_roster` / `remove_from_roster`
  (the class list is the base Tier C schema the orchestrator writes, as `add students` does);
* **move paper to student** — M-INGEST's `reassign_paper`, through M-PIPE's re-export (the
  console's declared dependencies stop at M-PIPE for intake, `TC-CONSOLE-36`);
* **remove paper** / **replace test paper** — M-STORE's housekeeping, `discard_ungraded_paper`
  and `discard_test_paper`, beside the empty-class discard the class delete already uses
  (intake never deletes what it wrote, `CT-INGEST-02`).

A refusal writes nothing and is returned as `(detail, False)`, which the SPA shows as refused.
A repeated request is safe by the doors' own rules: renaming to the current name, or moving a
paper to the student who has it, writes nothing; removing what is gone is refused, naming it
(`FR-CONSOLE-02`).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping

from aeh.orch import CohortSetupError, check_cohort_id, remove_from_roster, rename_on_roster
from aeh.store import (
    PurgePreconditionError,
    ReadOnlyTierError,
    discard_test_paper,
    discard_ungraded_paper,
)


RENAME_STUDENT_ACTION = "rename student"
REMOVE_STUDENT_ACTION = "remove student"
MOVE_PAPER_ACTION = "move paper to student"
REMOVE_PAPER_ACTION = "remove paper"
REPLACE_TEST_PAPER_ACTION = "replace test paper"

CORRECTION_ACTIONS: tuple[str, ...] = (
    RENAME_STUDENT_ACTION,
    REMOVE_STUDENT_ACTION,
    MOVE_PAPER_ACTION,
    REMOVE_PAPER_ACTION,
    REPLACE_TEST_PAPER_ACTION,
)


def _class_handle(store: Any, params: Mapping[str, Any]) -> tuple[str, Any]:
    """The named class's id and ledger handle. Opens no file that is not already there, so a
    mistyped class creates nothing."""
    cohort_id = check_cohort_id(params.get("cohort_id"))
    data_dir = getattr(store, "data_dir", None)
    if data_dir is None or not Path(data_dir, "cohorts", f"{cohort_id}.sqlite").exists():
        raise CohortSetupError(f"no class {cohort_id!r} exists. Nothing was written.")
    return cohort_id, store.cohort(cohort_id)


def _refused(action: str, error: Exception) -> tuple[str, bool]:
    if isinstance(error, sqlite3.DatabaseError):
        return (f"{action} refused: the class's file could not be read "
                f"({type(error).__name__}: {error}). Nothing was written.", False)
    return f"{action} refused: {error}", False


def _listed_name(store: Any, cohort_id: str, student_ref: str) -> str:
    """The student as the teacher knows them: their listed name; the ref only when the list
    holds none (or the class cannot be read)."""
    try:
        rows = store.cohort(cohort_id).query(
            "SELECT full_name FROM roster WHERE student_ref = :ref", ref=student_ref)
    except Exception:  # noqa: BLE001 — the ref stands in for an unreadable name
        rows = []
    return (str(rows[0]["full_name"] or "") if rows else "") or student_ref


def rename_student_effect(store: Any, params: Mapping[str, Any]) -> tuple[str, bool]:
    try:
        cohort_id = check_cohort_id(params.get("cohort_id"))
        student_ref = str(params.get("student_ref") or "")
        before = _listed_name(store, cohort_id, student_ref)
        rename_on_roster(store, cohort_id, student_ref, params.get("full_name"))
    except (CohortSetupError, sqlite3.DatabaseError) as error:
        return _refused(RENAME_STUDENT_ACTION, error)
    return (f"{before} is now listed as {_listed_name(store, cohort_id, student_ref)}; "
            "their papers stay theirs", True)


def remove_student_effect(store: Any, params: Mapping[str, Any]) -> tuple[str, bool]:
    try:
        cohort_id = check_cohort_id(params.get("cohort_id"))
        student_ref = str(params.get("student_ref") or "")
        name = _listed_name(store, cohort_id, student_ref)
        summary = remove_from_roster(store, cohort_id, student_ref)
    except (CohortSetupError, sqlite3.DatabaseError) as error:
        return _refused(REMOVE_STUDENT_ACTION, error)
    return (f"{name} was taken off the list of class {cohort_id}, which now lists "
            f"{summary.roster_size} student(s)", True)


def move_paper_effect(store: Any, params: Mapping[str, Any]) -> tuple[str, bool]:
    from aeh.pipeline import move_paper_to_student

    submission_id = str(params.get("submission_id") or "")
    student_ref = str(params.get("student_ref") or "").strip()
    try:
        cohort_id, handle = _class_handle(store, params)
        decision = move_paper_to_student(
            handle, submission_id, student_ref, actor=str(params.get("actor") or "operator"),
            note=params.get("note"))
    except (CohortSetupError, ValueError, sqlite3.DatabaseError) as error:
        return _refused(MOVE_PAPER_ACTION, error)
    name = _listed_name(store, cohort_id, student_ref)
    if decision is None:
        return f"this paper is already {name}'s; nothing was changed", True
    return (f"this paper now belongs to {name}; its marks moved with it, and the change "
            "is recorded", True)


def remove_paper_effect(store: Any, params: Mapping[str, Any]) -> tuple[str, bool]:
    submission_id = str(params.get("submission_id") or "")
    try:
        cohort_id, _handle = _class_handle(store, params)
        removed = discard_ungraded_paper(store, cohort_id, submission_id)
    except (CohortSetupError, PurgePreconditionError, ReadOnlyTierError,
            sqlite3.DatabaseError) as error:
        return _refused(REMOVE_PAPER_ACTION, error)
    whose = removed.get("student_ref")
    whose_text = "" if whose in (None, "", "unknown") else \
        f" ({_listed_name(store, cohort_id, str(whose))}'s)"
    return (f"the paper{whose_text} was removed from class {cohort_id}; its scan can be "
            "uploaded and read again", True)


def replace_test_paper_effect(store: Any, params: Mapping[str, Any]) -> tuple[str, bool]:
    with_sheets = str(params.get("with_sheets", "")).lower() in ("1", "true", "yes", "on")
    try:
        cohort_id, _handle = _class_handle(store, params)
        removed = discard_test_paper(store, cohort_id, with_sheets=with_sheets)
    except (CohortSetupError, PurgePreconditionError, ReadOnlyTierError,
            sqlite3.DatabaseError) as error:
        return _refused(REPLACE_TEST_PAPER_ACTION, error)
    sheets = removed.get("sheets") or []
    tail = (f" and {len(sheets)} answer sheet(s) were removed so they are read again"
            if sheets else "")
    return (f"the test paper of class {cohort_id} was removed{tail}; upload the right test "
            "paper with the answer sheets", True)


CORRECTION_EFFECTS = {
    RENAME_STUDENT_ACTION: rename_student_effect,
    REMOVE_STUDENT_ACTION: remove_student_effect,
    MOVE_PAPER_ACTION: move_paper_effect,
    REMOVE_PAPER_ACTION: remove_paper_effect,
    REPLACE_TEST_PAPER_ACTION: replace_test_paper_effect,
}


__all__ = ["CORRECTION_ACTIONS", "CORRECTION_EFFECTS"]
