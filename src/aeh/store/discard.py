"""Removing a cohort that never held student work (the console's "Delete this class").

`SqliteStore.purge_cohort` deletes a cohort's Tier C and R content only after its evidence is
promoted to Tier D (FR-STORE-07, CT-STORE-10). A cohort with no submission and no run — a class
made by mistake, its list typed and nothing else — has nothing to promote, so the purge refused
it forever and the file stayed listed. This removes such a cohort outright and refuses any
other, naming the purge as its way out: evidence is never discarded this way.

A module function, not a Store member: the Store's public surface is the five contract members
(`TC-STORE-C01`); this is store-internal housekeeping over a store it is handed.

The same housekeeping removes **one paper** a teacher read in by mistake (the wrong file, another
class's sheet, the earlier of two scans of one student — FR-CONSOLE-67) and **the class's test
paper** when the wrong one was read (FR-CONSOLE-68). Both are refused once a grading run has
touched the paper (or, for the test paper, any paper in the class): from then on the paper's
marks are part of a run's record, which only the purge removes. Intake never deletes what it
wrote (`CT-INGEST-02`), so these live here, beside the purge that already deletes intake's rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import PurgePreconditionError, ReadOnlyTierError
from .interfaces import Statement, Tier
from .purge import _DISCARD_WORK_COUNTS
from .security import _validated_component


def discard_empty_cohort(store: Any, cohort_id: str) -> None:
    """Remove `cohort_id`'s file if it holds no paper and no run; refuse otherwise (nothing is
    removed). The cohort's cached handle is closed first, as `purge_cohort` does: on Windows an
    open connection is a file that cannot be removed."""
    cohort_id = _validated_component("cohort id", cohort_id)
    if getattr(store, "_read_only", False):
        raise ReadOnlyTierError(
            f"discard_empty_cohort was called on a read-only store for cohort {cohort_id!r}.")
    path = Path(store.cohort_path(cohort_id))
    if not path.exists():
        raise PurgePreconditionError(f"no cohort {cohort_id!r} is stored; nothing was removed.")
    handle = store.cohort(cohort_id)
    held = [what for what, statement in _DISCARD_WORK_COUNTS.items()
            if handle.query(statement)[0][0]]
    if held:
        raise PurgePreconditionError(
            f"cohort {cohort_id!r} holds {' and '.join(held)}, so it is purged only after its "
            "evidence is promoted (purge_cohort); nothing was removed.")
    handles = store._handles  # noqa: SLF001 -- the store package's own housekeeping
    cached = handles.get((Tier.COHORT, cohort_id, False))
    if cached is not None:
        cached._close()  # noqa: SLF001 -- flush queued writes; a failure propagates
        handles.pop((Tier.COHORT, cohort_id, False), None)
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


# --- one paper, or the class's test paper (FR-CONSOLE-67, FR-CONSOLE-68) ----------------------

_PAPER_STATEMENTS: dict[str, Statement] = {
    "select_paper": Statement(
        "SELECT submission_id, student_ref FROM submission WHERE submission_id = :submission_id"
    ),
    # A paper is graded once any run has handed out work for it; its marks hang off those
    # units, so it is no longer removable this way.
    "select_paper_runs": Statement(
        "SELECT DISTINCT run_id FROM work_unit WHERE submission_id = :submission_id "
        "ORDER BY run_id"
    ),
    "select_graded_paper_count": Statement(
        "SELECT COUNT(DISTINCT submission_id) FROM work_unit"
    ),
    "select_ungraded_papers": Statement(
        "SELECT submission_id FROM submission WHERE submission_id NOT IN "
        "(SELECT submission_id FROM work_unit WHERE submission_id IS NOT NULL) "
        "ORDER BY submission_id"
    ),
    "select_paper_documents": Statement(
        "SELECT document_id FROM document WHERE submission_id = :submission_id"
    ),
    "select_test_paper_documents": Statement(
        "SELECT document_id FROM document WHERE kind = 'assessment'"
    ),
    "delete_document_tokens": Statement(
        "DELETE FROM unresolved_token WHERE document_id = :document_id"
    ),
    "delete_document_regions": Statement(
        "DELETE FROM document_region WHERE document_id = :document_id"
    ),
    "delete_child_documents": Statement("DELETE FROM document WHERE parent_doc_id = :document_id"),
    "delete_document": Statement("DELETE FROM document WHERE document_id = :document_id"),
    "delete_paper_proposals": Statement(
        "DELETE FROM assessment_match_proposal WHERE submission_id = :submission_id"
    ),
    "delete_paper_decisions": Statement(
        "DELETE FROM quarantine_decision WHERE submission_id = :submission_id"
    ),
    "delete_paper": Statement("DELETE FROM submission WHERE submission_id = :submission_id"),
    # The cohort breaker counts wrong-test papers against the test paper read; a new test
    # paper starts that count again.
    "delete_cohort_breaker": Statement("DELETE FROM v4_cohort_breaker"),
}


def _class_handle(store: Any, cohort_id: str) -> Any:
    cohort_id = _validated_component("cohort id", cohort_id)
    if getattr(store, "_read_only", False):
        raise ReadOnlyTierError(
            f"a paper was to be removed from a read-only store for cohort {cohort_id!r}.")
    if not Path(store.cohort_path(cohort_id)).exists():
        raise PurgePreconditionError(f"no class {cohort_id!r} is stored; nothing was removed.")
    return store.cohort(cohort_id)


def _documents_of(handle: Any, statement: Statement, **params: Any) -> list[str]:
    return [str(row[0]) for row in handle.query(statement, **params)]


def _delete_documents(tx: Any, documents: list[str]) -> None:
    for document_id in documents:
        tx.execute(_PAPER_STATEMENTS["delete_document_tokens"], document_id=document_id)
        tx.execute(_PAPER_STATEMENTS["delete_document_regions"], document_id=document_id)
        tx.execute(_PAPER_STATEMENTS["delete_child_documents"], document_id=document_id)
        tx.execute(_PAPER_STATEMENTS["delete_document"], document_id=document_id)


def _delete_paper(tx: Any, submission_id: str, documents: list[str]) -> None:
    _delete_documents(tx, documents)
    tx.execute(_PAPER_STATEMENTS["delete_paper_proposals"], submission_id=submission_id)
    tx.execute(_PAPER_STATEMENTS["delete_paper_decisions"], submission_id=submission_id)
    tx.execute(_PAPER_STATEMENTS["delete_paper"], submission_id=submission_id)


def discard_ungraded_paper(store: Any, cohort_id: str, submission_id: str) -> dict[str, Any]:
    """Remove one paper no grading run has touched, with every row intake wrote for it, so the
    same scan (or a better one) can be read in again (FR-CONSOLE-67). Returns the paper's id
    and the student it was filed under. Refused, removing nothing, for a paper that is not in
    the class or that a run has graded — naming the run."""
    handle = _class_handle(store, cohort_id)
    rows = handle.query(_PAPER_STATEMENTS["select_paper"], submission_id=submission_id)
    if not rows:
        raise PurgePreconditionError(
            f"no paper {submission_id!r} is in class {cohort_id!r}; nothing was removed.")
    runs = [str(row[0]) for row in handle.query(_PAPER_STATEMENTS["select_paper_runs"],
                                                submission_id=submission_id)]
    if runs:
        raise PurgePreconditionError(
            f"this paper was already graded (grading run {', '.join(runs)}), so its marks are "
            "part of that run's record and it stays. Correct a mark from the results (change "
            "the grade), or give the paper to the right student; nothing was removed.")
    documents = _documents_of(handle, _PAPER_STATEMENTS["select_paper_documents"],
                              submission_id=submission_id)
    with handle.transaction() as tx:
        _delete_paper(tx, submission_id, documents)
    return {"submission_id": submission_id, "student_ref": rows[0][1]}


def discard_test_paper(store: Any, cohort_id: str, *, with_sheets: bool = False) -> dict[str, Any]:
    """Remove the class's test paper so the right one is read with the next upload, while no
    paper in the class has been graded (FR-CONSOLE-68). With `with_sheets`, every answer sheet
    goes too (none is graded), so each is read again and checked against the right test
    paper. Returns how many test-paper documents and which sheets were removed."""
    handle = _class_handle(store, cohort_id)
    graded = int(handle.query(_PAPER_STATEMENTS["select_graded_paper_count"])[0][0])
    if graded:
        raise PurgePreconditionError(
            f"{graded} paper(s) in this class were already graded against this test paper, so "
            "it stays: the grades depend on it. Make a new class for papers that answer a "
            "different test; nothing was removed.")
    documents = _documents_of(handle, _PAPER_STATEMENTS["select_test_paper_documents"])
    if not documents:
        raise PurgePreconditionError(
            "this class holds no test paper yet; upload it with the answer sheets. Nothing "
            "was removed.")
    sheets: list[str] = []
    if with_sheets:
        sheets = [str(row[0]) for row in handle.query(
            _PAPER_STATEMENTS["select_ungraded_papers"])]
    sheet_documents = {sid: _documents_of(handle, _PAPER_STATEMENTS["select_paper_documents"],
                                          submission_id=sid) for sid in sheets}
    with handle.transaction() as tx:
        for submission_id in sheets:
            _delete_paper(tx, submission_id, sheet_documents[submission_id])
        _delete_documents(tx, documents)
        tx.execute(_PAPER_STATEMENTS["delete_cohort_breaker"])
    return {"test_papers": len(documents), "sheets": sheets}


__all__ = ["discard_empty_cohort", "discard_test_paper", "discard_ungraded_paper"]
