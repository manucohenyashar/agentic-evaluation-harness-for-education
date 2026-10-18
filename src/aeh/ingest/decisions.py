"""The operator's decision on a parked paper, recorded (live-test blocker B8).

Releasing or closing a parked paper used to write only the paper's two status columns, so the
system kept no trace of *what the operator decided*: whose a nameless paper is, which tick of a
doubled mark is meant, which test a wrong-test paper belongs to. And a paper whose student the
identity check (V3) could not match could only be closed — the student then had no grade
unless the sheet was rescanned with the name written more clearly.

This module is the record and the one new decision:

* **every resolution is recorded** — one append-only `quarantine_decision` row: the paper, the
  resolution, the operator's name as the console supplied it, when, the student it was
  assigned to (if any), the identity check's verdict before the decision, and the operator's
  own note (the tick they read, the test it belongs to);
* **`assigned`** — the operator names the student on the class list the paper belongs to. The
  submission's `student_ref` is set to that student and its identity check is recorded as
  passed *by the operator* (the decision row keeps the check's own verdict), so the paper is
  graded under that student. Refused for a student not on the class list, or one who already
  has a paper in the class: the operator's choice may never give one student two papers.

Nothing here decides anything itself: the console calls it with the operator's choice. The
module issues only the declared statements below, keyword-parameterized (FR-STORE-08).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from aeh.store import STATEMENTS, TIER_MIGRATIONS, Migration, Statement, Tier

from .schema import INGEST_STATEMENTS

#: The resolutions a decision row may carry: the two the console always offered, plus the
#: operator's assignment of a nameless or unmatched paper to a student on the list.
QUARANTINE_DECISIONS: tuple[str, ...] = ("matched", "unresolvable", "assigned")


# --- Tier C, migration 35 (B8): the operator's decision, recorded -----------------------------
_INGEST_QUARANTINE_DECISION = Migration(
    version=35,
    name="ingest_quarantine_decision",
    statements=(
        Statement(
            """
            CREATE TABLE quarantine_decision (
                decision_id   TEXT NOT NULL PRIMARY KEY,
                submission_id TEXT NOT NULL REFERENCES submission(submission_id),
                resolution    TEXT NOT NULL
                              CHECK (resolution IN ('matched', 'unresolvable', 'assigned')),
                actor         TEXT NOT NULL,
                student_ref   TEXT,
                prior_identity TEXT,
                note          TEXT,
                decided_at    TEXT NOT NULL
            )
            """
        ),
    ),
)

TIER_MIGRATIONS[Tier.COHORT] = TIER_MIGRATIONS[Tier.COHORT] + (_INGEST_QUARANTINE_DECISION,)


_DECISION_STATEMENTS = {
    "insert_quarantine_decision": Statement(
        "INSERT INTO quarantine_decision (decision_id, submission_id, resolution, actor, "
        "student_ref, prior_identity, note, decided_at) VALUES (:decision_id, "
        ":submission_id, :resolution, :actor, :student_ref, :prior_identity, :note, "
        ":decided_at)"
    ),
    "select_quarantine_decisions": Statement(
        "SELECT decision_id, submission_id, resolution, actor, student_ref, prior_identity, "
        "note, decided_at FROM quarantine_decision ORDER BY decided_at, decision_id"
    ),
    "select_submission_for_decision": Statement(
        "SELECT submission_id, student_ref, v3_identity FROM submission "
        "WHERE submission_id = :submission_id"
    ),
    "select_roster_ref": Statement(
        "SELECT student_ref FROM roster WHERE student_ref = :student_ref"
    ),
    "select_other_paper_of_student": Statement(
        "SELECT submission_id FROM submission WHERE student_ref = :student_ref "
        "AND submission_id != :submission_id"
    ),
    "update_submission_assignment": Statement(
        "UPDATE submission SET student_ref = :student_ref, v3_identity = 'pass' "
        "WHERE submission_id = :submission_id"
    ),
}
INGEST_STATEMENTS.update(_DECISION_STATEMENTS)
STATEMENTS.update(_DECISION_STATEMENTS)


class QuarantineDecisionError(ValueError):
    """A decision the record refuses, in the operator's words; nothing was written."""


def check_assignment(handle: Any, submission_id: str, student_ref: str) -> None:
    """Refuse an assignment that would grade a paper under nobody or give a student two
    papers. A look only: nothing is written."""
    if not student_ref:
        raise QuarantineDecisionError(
            "choose the student this paper belongs to. Nothing was written.")
    if not list(handle.query(INGEST_STATEMENTS["select_roster_ref"], student_ref=student_ref)):
        raise QuarantineDecisionError(
            f"{student_ref!r} is not on this class's list. Add the student to the class "
            "first, then assign the paper. Nothing was written.")
    others = list(handle.query(INGEST_STATEMENTS["select_other_paper_of_student"],
                               student_ref=student_ref, submission_id=submission_id))
    if others:
        raise QuarantineDecisionError(
            f"{student_ref!r} already has a paper in this class "
            f"({others[0]['submission_id']}); one student cannot be graded on two papers. "
            "Close one of them instead. Nothing was written.")


def record_quarantine_decision(
    handle: Any,
    submission_id: str,
    *,
    resolution: str,
    actor: str,
    student_ref: str | None = None,
    note: str | None = None,
    tx: Any = None,
) -> str:
    """Record one decision on a parked paper and, for `assigned`, give the paper to the named
    student. Runs inside the caller's transaction when `tx` is given (the console's status
    write and this record land together), else opens its own. Returns the decision id."""
    if resolution not in QUARANTINE_DECISIONS:
        raise QuarantineDecisionError(
            f"{resolution!r} is not one of {', '.join(QUARANTINE_DECISIONS)}. "
            "Nothing was written.")
    rows = list(handle.query(INGEST_STATEMENTS["select_submission_for_decision"],
                             submission_id=submission_id))
    if not rows:
        raise QuarantineDecisionError(
            f"no paper {submission_id!r} is in this class. Nothing was written.")
    prior_identity = rows[0]["v3_identity"]
    clean_note = (str(note).strip() or None) if note is not None else None
    recorded = [d for d in quarantine_decisions(handle) if d["submission_id"] == submission_id]
    if recorded and (recorded[-1]["resolution"], recorded[-1]["student_ref"],
                     recorded[-1]["note"]) == (resolution, student_ref, clean_note):
        # The same decision posted again (a double-click, a retried request, a back
        # navigation) records nothing new: FR-CONSOLE-02, every action is idempotent.
        return str(recorded[-1]["decision_id"])
    if resolution == "assigned":
        check_assignment(handle, submission_id, str(student_ref or ""))
    decision_id = f"qd-{uuid.uuid4().hex[:12]}"

    def write(target: Any) -> None:
        if resolution == "assigned":
            target.execute(INGEST_STATEMENTS["update_submission_assignment"],
                           student_ref=student_ref, submission_id=submission_id)
        target.execute(
            INGEST_STATEMENTS["insert_quarantine_decision"],
            decision_id=decision_id, submission_id=submission_id, resolution=resolution,
            actor=str(actor or "operator"), student_ref=student_ref,
            prior_identity=None if prior_identity is None else str(prior_identity),
            note=clean_note,
            decided_at=datetime.now(timezone.utc).isoformat())

    if tx is not None:
        write(tx)
    else:
        with handle.transaction() as own:
            write(own)
    return decision_id


def quarantine_decisions(handle: Any) -> list[dict[str, Any]]:
    """Every recorded decision in the cohort, oldest first — the audit trail the parked page
    shows beside each paper."""
    return [dict(row) for row in handle.query(INGEST_STATEMENTS["select_quarantine_decisions"])]


__all__ = [
    "QUARANTINE_DECISIONS",
    "QuarantineDecisionError",
    "check_assignment",
    "quarantine_decisions",
    "record_quarantine_decision",
]
