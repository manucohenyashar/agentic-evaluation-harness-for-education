"""The teacher's corrections to whose a paper is (FR-CONSOLE-66, FR-INGEST-41).

Intake can file a paper under the wrong student in ways no check catches, and before these doors
the teacher had no way back:

* **a paper under the wrong student** — the name on the sheet matched a different student on
  the list (two similar names, a borrowed sheet). B8's assignment moves only a *parked* paper;
  `reassign_paper` moves a matched one, under the same rules: the student is on the class list
  and has no other paper, so one student is never graded on two papers. The paper's grades are
  keyed on the paper, so a paper already graded moves with its grades. Every move is recorded
  in the decision trail (`quarantine_decision`, resolution `assigned`) with the student it came
  from in the note.
* **a second paper for one student** — a rescan, or two sheets bearing one name. Intake skips a
  scan only when its bytes were read before, so a sharper rescan is read in as a new paper and
  the identity check matches the same student; graded beside the first, the student would be
  graded twice. `park_second_paper` parks it (FR-INGEST-41) under the student it matched, for
  the teacher to keep one of the two. The intake command calls it after each sheet — the
  ladder itself stays a pure reading of one paper (`CT-INGEST-12`: a re-read gives the same
  verdict), because "already has a paper" is a fact about the class, not about the sheet.

Removing a paper, or the class's test paper, is M-STORE's (`aeh.store.discard_ungraded_paper`,
`discard_test_paper`): intake never deletes or rewrites a document it wrote (`CT-INGEST-02`).

Nothing here decides anything: callers pass the teacher's choice. Every refusal names the reason
and writes nothing. The module issues only the declared statements below, keyword-parameterized
(FR-STORE-08).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from aeh.store import STATEMENTS, Statement

from . import decisions as _decisions  # noqa: F401 - registers the decision statements
from .identity import V3_ALREADY_HAS_PAPER, V3_PASS
from .schema import INGEST_STATEMENTS


_CORRECTION_STATEMENTS = {
    "select_paper_for_correction": Statement(
        "SELECT submission_id, student_ref, v3_identity, quarantined, ingest_status "
        "FROM submission WHERE submission_id = :submission_id"
    ),
    # The diagnosis (`ingest_status`) stays the ladder's own (TC-INGEST-29: one writer of the
    # status vocabulary); the park is the flag plus the identity outcome, which M-ORCH's
    # identity triage withholds from every stage (`IDENTITY_TRIAGE_V3_OUTCOMES`).
    "park_second_paper": Statement(
        "UPDATE submission SET v3_identity = :identity, quarantined = 1 "
        "WHERE submission_id = :submission_id"
    ),
}
INGEST_STATEMENTS.update(_CORRECTION_STATEMENTS)
STATEMENTS.update(_CORRECTION_STATEMENTS)


class PaperCorrectionError(ValueError):
    """A correction refused, in the teacher's words; nothing was written."""


def _paper(handle: Any, submission_id: str) -> dict[str, Any]:
    rows = list(handle.query(INGEST_STATEMENTS["select_paper_for_correction"],
                             submission_id=submission_id))
    if not rows:
        raise PaperCorrectionError(
            f"no paper {submission_id!r} is in this class. Nothing was written.")
    return dict(rows[0])


def reassign_paper(handle: Any, submission_id: str, student_ref: str, *, actor: str,
                   note: str | None = None) -> str | None:
    """Give a paper the identity check matched to the wrong student to the right one. Returns
    the decision id, or None when the paper is already that student's (nothing written).

    A parked paper whose student was never matched goes through B8's `assigned` decision
    instead (`record_quarantine_decision`) — this door is for a paper that *was* matched."""
    paper = _paper(handle, submission_id)
    target = str(student_ref or "").strip()
    if not target:
        raise PaperCorrectionError("choose the student this paper belongs to. Nothing was written.")
    if str(paper["v3_identity"] or V3_PASS) != V3_PASS:
        raise PaperCorrectionError(
            "this paper was never matched to a student: give it to its student from the "
            "Parked screen. Nothing was written.")
    current = str(paper["student_ref"] or "")
    if current == target:
        return None
    if not list(handle.query(INGEST_STATEMENTS["select_roster_ref"], student_ref=target)):
        raise PaperCorrectionError(
            "that student is not on this class's list. Add the student to the class first, "
            "then move the paper. Nothing was written.")
    others = list(handle.query(INGEST_STATEMENTS["select_other_paper_of_student"],
                               student_ref=target, submission_id=submission_id))
    if others:
        named = list(handle.query(INGEST_STATEMENTS["select_roster_name"],
                                  student_ref=target))
        who = (str(named[0]["full_name"] or "") if named else "") or target
        raise PaperCorrectionError(
            f"{who} already has a paper in this class; one student cannot be graded on two "
            "papers. Move or remove that paper first. Nothing was written.")
    clean_note = str(note).strip() if note is not None else ""
    moved = f"moved from {current}" + (f": {clean_note}" if clean_note else "")
    decision_id = f"qd-{uuid.uuid4().hex[:12]}"
    with handle.transaction() as tx:
        tx.execute(INGEST_STATEMENTS["update_submission_assignment"],
                   student_ref=target, submission_id=submission_id)
        tx.execute(
            INGEST_STATEMENTS["insert_quarantine_decision"],
            decision_id=decision_id, submission_id=submission_id, resolution="assigned",
            actor=str(actor or "operator"), student_ref=target, prior_identity=V3_PASS,
            note=moved, decided_at=datetime.now(timezone.utc).isoformat())
    return decision_id


def park_second_paper(handle: Any, submission_id: str) -> str | None:
    """Park a just-read paper whose student already has a paper in the class (FR-INGEST-41).
    Returns the earlier paper's id when it parked this one, else None (nothing written): a
    paper that is not matched, or whose student has no other paper, is left as read."""
    paper = _paper(handle, submission_id)
    if str(paper["v3_identity"] or "") != V3_PASS or paper["quarantined"]:
        return None
    earlier = list(handle.query(INGEST_STATEMENTS["select_other_paper_of_student"],
                                student_ref=paper["student_ref"], submission_id=submission_id))
    if not earlier:
        return None
    with handle.transaction() as tx:
        tx.execute(INGEST_STATEMENTS["park_second_paper"], submission_id=submission_id,
                   identity=V3_ALREADY_HAS_PAPER)
    return str(earlier[0]["submission_id"])


__all__ = [
    "PaperCorrectionError",
    "park_second_paper",
    "reassign_paper",
]
