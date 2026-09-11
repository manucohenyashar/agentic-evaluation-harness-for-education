"""`TC-GRADE-C10` — amendment never mutates a delivered grade (§6.11.14).

`CT-GRADE-10` (behaviour): "Assert amendment **never mutates a delivered grade**:
`amend` writes a **new revision**, **retains** the superseded one, **preserves
`finalized_at`**, and records **who changed what, when and why** — four separate
assertions, since preserving the row while overwriting `finalized_at` is the
plausible partial implementation. Assert `(run_id, submission_id, revision)` is
the key and `is_current` marks the live one, with exactly one current revision at
all times. Guards RISK-12 (ADR-9)."

The limbs, in the row's order:

- **the four-field discipline, asserted separately** (rung 3, green): `amend`
  (i) writes revision n+1, (ii) RETAINS the superseded revision — its fields byte-
  unchanged (the delivered grade is never mutated), (iii) PRESERVES
  `finalized_at` — the settlement anchor the prior issuance stamped rides forward
  (stamping `now` instead is the plausible partial implementation), and (iv) both
  records — the revision-local `amendments` JSON and the Tier D `audit_record` row
  — carry who (`decided_by`/`actor`), what (the criterion-level points), when
  (`recorded_at`/`at`) and why (`reason`).
- **the key and the uniqueness invariant** (rung 3, green): every revision reads
  through the `(run_id, submission_id, revision)` key, and exactly ONE revision
  carries `is_current = 1` per (run, submission) at every point — before, between
  and after amendments.
- **the refusal limb**: an edit naming a criterion with no stored score row is
  refused, naming the criterion — an amendment applied nowhere would claim a
  change that never happened, and an absence is the operator routing's to fill,
  never an edit's (the no-imputation rule at the amendment seam).

Isolation: rung 3 — real store, real package, real service, real Tier D ledger.
The socket guard is autouse; `criterion_score` rows are the vocabulary's disclosed
`M-AGG` stand-in.
"""

from __future__ import annotations

import json

import pytest

from aeh.grade import GradeError
from aeh.store import open_store
from tests.contract.grade._drive import (
    current_grades,
    grade_revision,
    graded_run,
    set_boundaries,
)
from tests.support.impl import GRADE_MODULE, require

pytestmark = [pytest.mark.contract]

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)

_ROWS = (
    ("S-ONE", "C1", "B2", 7.0, "auto"),
    ("S-ONE", "C2", "B2", 5.0, "auto"),
)


def test_tc_grade_c10_amendment_writes_new_retains_old_preserves_finalized_at(
    tmp_data_dir,
):
    """`TC-GRADE-C10` (`CT-GRADE-10`, rung 3) — the four-field discipline, as
    separate assertions on one amendment chain: the new revision, the retained
    superseded one, the preserved settlement anchor, and the who/what/when/why
    record on both surfaces."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-ONE",), criteria=_CRITERIA, rows=_ROWS,
            compute=False,
        )
        set_boundaries(store, world.version, (("B", 10.0), ("A", 85.0)))
        world.service.compute_all(world.run_id)
        run_id = world.run_id
        first = {
            row["submission_id"]: row
            for row in current_grades(world.cohort, run_id)
        }["S-ONE"]
        assert first["revision"] == 1, "fixture bug: the first issuance is revision 1"

        # Amendment 1: the delivered revision 1 is provisional; the edit mints 2.
        revision_two = world.service.amend(
            run_id, "S-ONE", {"C1": 10.0}, actor="teacher-1", reason="band move",
        )
        assert revision_two.revision == 2, (
            f"amend produced revision {revision_two.revision!r} — an amendment "
            "writes a NEW revision, never mutating the delivered one (CT-GRADE-10)"
        )

        # Assertions 1+2: the superseded revision is RETAINED, byte-unchanged —
        # every field the issuance stamped still reads exactly what it read.
        superseded = grade_revision(world.cohort, run_id, "S-ONE", 1)
        assert (
            superseded["total"], superseded["grade"], superseded["state"],
            superseded["computed_at"], superseded["finalized_at"],
            superseded["amendments"],
        ) == (
            first["total"], first["grade"], first["state"],
            first["computed_at"], first["finalized_at"], first["amendments"],
        ), (
            f"revision 1 changed after the amendment ({superseded!r} vs "
            f"{first!r}) — the superseded grade is retained, never mutated "
            "(CT-GRADE-10, RISK-12)"
        )
        assert int(superseded["is_current"]) == 0, (
            "revision 1 still marks is_current after the amendment — exactly one "
            "current revision at all times (CT-GRADE-10)"
        )

        # Assertion 3: the settlement anchor. Revision 2 settles final with a FRESH
        # anchor (revision 1 was never settled); amendment 2 must PRESERVE it —
        # stamping the amend call's clock over the anchor is the partial
        # implementation the row-form guards against.
        rev_two_row = grade_revision(world.cohort, run_id, "S-ONE", 2)
        assert rev_two_row["state"] == "final" and rev_two_row["finalized_at"], (
            "the amended grade did not settle final (CT-GRADE-10: the teacher just "
            "reviewed it)"
        )
        anchor = rev_two_row["finalized_at"]
        revision_three = world.service.amend(
            run_id, "S-ONE", {"C2": 3.0}, actor="teacher-2", reason="recheck",
        )
        assert revision_three.revision == 3, (
            "amendment 2 did not mint revision 3 (CT-GRADE-10)"
        )
        rev_three_row = grade_revision(world.cohort, run_id, "S-ONE", 3)
        assert rev_three_row["finalized_at"] == anchor, (
            f"revision 3's finalized_at is {rev_three_row['finalized_at']!r}, not "
            f"the preserved anchor {anchor!r} — preserving the row while "
            "overwriting finalized_at is the plausible partial implementation "
            "(CT-GRADE-10's separate finalized_at assertion)"
        )
    finally:
        store.close()


def test_tc_grade_c10_the_key_and_exactly_one_current_revision(tmp_data_dir):
    """`TC-GRADE-C10`'s key and uniqueness limbs (`CT-GRADE-10`, rung 3) — every
    revision reads through the `(run_id, submission_id, revision)` key, and exactly
    one revision per (run, submission) marks `is_current` at every observed point:
    at issuance, after the first amendment, and after the second."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(store, submissions=("S-ONE",), criteria=_CRITERIA, rows=_ROWS)
        run_id = world.run_id

        def current_revisions():
            return world.cohort.query(
                "SELECT revision FROM submission_grade "
                "WHERE run_id = :r AND submission_id = :s AND is_current = 1",
                r=run_id, s="S-ONE",
            )

        assert [r["revision"] for r in current_revisions()] == [1], (
            "fixture bug: the issued grade does not mark revision 1 current"
        )
        world.service.amend(
            run_id, "S-ONE", {"C1": 9.0}, actor="teacher-1", reason="review",
        )
        assert [r["revision"] for r in current_revisions()] == [2], (
            "after amendment 1 the live revision is not exactly [2] — exactly one "
            "current revision at all times (CT-GRADE-10's uniqueness invariant)"
        )
        world.service.amend(
            run_id, "S-ONE", {"C2": 2.0}, actor="teacher-2", reason="recheck",
        )
        assert [r["revision"] for r in current_revisions()] == [3], (
            "after the second amendment the live revision is not exactly [3] "
            "(CT-GRADE-10's uniqueness invariant)"
        )
        # The key: every revision reads through (run_id, submission_id, revision),
        # and the retained ones stay addressable with their own figures. The
        # amendment's edits are ABSOLUTE overrides of the named criteria over the
        # STORED scores (the revision-local record the recomputation replays —
        # FR-GRADE-13's exactness), so revision 2 is C1@9 + C2@5 and revision 3 is
        # C1@7 + C2@2: each revision's total replays from its own recorded map.
        for revision, expected_total in ((1, 12.0), (2, 14.0), (3, 9.0)):
            row = grade_revision(world.cohort, run_id, "S-ONE", revision)
            assert row is not None and float(row["total"]) == expected_total, (
                f"revision {revision} is not addressable through the "
                f"(run_id, submission_id, revision) key ({row!r}) — the key is "
                "(run_id, submission_id, revision), and superseded revisions stay "
                "addressable behind it (CT-GRADE-10)"
            )
    finally:
        store.close()


def test_tc_grade_c10_the_amendment_records_who_what_when_and_why(tmp_data_dir):
    """`TC-GRADE-C10`'s record limb (`CT-GRADE-10`, rung 3) — the amendment records
    who changed what, when and why: the grade row's `amendments` JSON carries the
    actor, the points, the timestamp and the reason per edit; Tier D appends one
    `audit_record` row per call with `decided_by`, `recorded_at` and the canonical
    what/why detail."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(store, submissions=("S-ONE",), criteria=_CRITERIA, rows=_ROWS)
        run_id = world.run_id
        revision_two = world.service.amend(
            run_id, "S-ONE", {"C1": 10.0}, actor="teacher-1", reason="band move",
        )
        assert revision_two.actor == "teacher-1" and revision_two.reason == "band move", (
            "the returned revision lost its actor or reason (CT-GRADE-10)"
        )
        # The grade row's revision-local record: actor, points, at — per edit.
        amendments = json.loads(
            grade_revision(world.cohort, run_id, "S-ONE", 2)["amendments"]
        )
        assert [(a["criterion_id"], a["points"], a["actor"], a["reason"]) for a in
                amendments] == [("C1", 10.0, "teacher-1", "band move")], (
            f"the grade row records {amendments!r} — the override record must name "
            "who changed what, when and why (CT-GRADE-10)"
        )
        assert amendments[0]["at"], (
            f"the grade row's amendment record carries no timestamp "
            f"({amendments[0]!r}) — the 'when' of who/what/when/why rides the "
            "revision-local record too (CT-GRADE-10)"
        )
        # Tier D: one appended audit row, the durable who/what/when/why form.
        audits = [
            dict(row)
            for row in store.durable().query(
                "SELECT * FROM audit_record WHERE submission_id = :s", s="S-ONE"
            )
        ]
        assert len(audits) == 1, (
            f"the amendment appended {len(audits)} audit rows — one row per call "
            "(CT-GRADE-10's Tier D record)"
        )
        audit = audits[0]
        assert audit["decided_by"] == "teacher-1" and audit["recorded_at"], (
            f"the audit row reads ({audit.get('decided_by')!r}, "
            f"{audit.get('recorded_at')!r}) — who and when (CT-GRADE-10, ADR-9)"
        )
        assert audit["evaluation_mode"] == "judged", (
            f"the audit row reads evaluation_mode {audit['evaluation_mode']!r} — a "
            "teacher's decision is judged, never a derivation (CT-GRADE-10)"
        )
        detail = json.loads(audit["profile_summary"])
        assert detail["event"] == "grade_amendment" and detail["reason"] == "band move", (
            f"the audit detail names {detail!r} — what and why ride the record"
        )
        assert detail["criteria"] == [{"criterion_id": "C1", "points": 10.0}], (
            f"the audit detail's criteria read {detail['criteria']!r} — the edit's "
            "criterion-level detail (CT-GRADE-10: who changed WHAT)"
        )
        assert detail["from_total"] == 12.0 and detail["to_total"] == 15.0, (
            f"the audit detail carries totals {detail['from_total']!r} -> "
            f"{detail['to_total']!r} — before and after (CT-GRADE-10)"
        )
    finally:
        store.close()


def test_tc_grade_c10_an_edit_naming_an_absent_score_is_refused(tmp_data_dir):
    """`TC-GRADE-C10`'s refusal limb (`CT-GRADE-10`, rung 3) — an edit naming a
    criterion with no stored score row is REFUSED, naming it: recording an edit
    that applied nowhere would claim a change that never happened, and a missing
    input is the operator routing's to fill, never an edit's."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-ONE",),
            criteria=_CRITERIA,
            rows=(("S-ONE", "C1", "B2", 7.0, "auto"),),
        )  # S-ONE's C2 never scored
        with pytest.raises(GradeError) as refused:
            world.service.amend(
                world.run_id, "S-ONE", {"C2": 4.0}, actor="teacher-1", reason="edit",
            )
        assert "C2" in str(refused.value), (
            f"the refusal named nothing ({refused.value!r}) — it must name the "
            "criterion that has no stored score row (CT-GRADE-10)"
        )
        # And the refusal wrote nothing: still revision 1, unamended.
        row = grade_revision(world.cohort, world.run_id, "S-ONE", 1)
        assert json.loads(row["amendments"]) == [], (
            "a refused amendment left an amendments record (CT-GRADE-10)"
        )
        assert float(row["total"]) == 7.0, (
            "the refused edit changed the delivered grade (CT-GRADE-10, RISK-12)"
        )
    finally:
        store.close()