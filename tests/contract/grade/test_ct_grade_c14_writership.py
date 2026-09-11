"""`TC-GRADE-C14` — sole writership, a closed write set, and an append-only audit (§6.11.14).

`CT-GRADE-14` (state): "Assert sole writership of `submission_grade` and
`criterion_stats`, plus the **append-only** `audit_record` per criterion at
finalization — asserting append-only by attempting an update and confirming
refusal, since an audit record that can be edited is not an audit record. Then the
prohibition: **never writes `criterion_score`, `verdict` or `narrative`**, under a
rung-3 write audit."

The limbs, in the row's order:

- **the sole writership** (rung 3, green): under a write audit over the whole
  service path — the grading pass, the amendment, the batch finalization — every
  `submission_grade` write is attributed to `aeh.grade`, and the write SET is
  closed: `{submission_grade, review_queue}` on the cohort tier, `{audit_record,
  run_metrics}` on the durable one. The row's `criterion_stats` figures are reads
  in the shipped design (`criterion_band_figures`/`separated_rollup` compute over
  the stored scores), so their writership limb is the closed set's read: the
  audited window writes no figure table at all, because figures are derived, never
  stored beside their inputs.
- **the prohibition** (rung 3, green): no write to `criterion_score`, `verdict` or
  `narrative` by ANYONE in the audited window — M-GRADE's aggregation inputs are
  `M-AGG`'s alone to write (CT-AGG's Requires row), the verdicts are the judges'
  and the narratives the synthesizer's, and a grading pass that touched them would
  be a second writer on three other modules' ledgers at once.
- **the append-only audit** (rung 3, green): a real amendment appends the
  per-criterion record, and an UPDATE and a DELETE against `audit_record` are
  refused — attempted, not assumed — while the row they targeted survives. An
  audit record that can be edited is not an audit record.

Isolation: rung 3 — real store, real service, real Tier D ledger; the write audit
is `tests/contract/orch/_doubles.install_audit` (the TC-ORCH-C17 precedent),
installed after the fixture's disclosed seeding so the log holds only what the
grading path wrote. The socket guard is autouse; the append-only refusal is the
landed `enforce_ledger_append_only` discipline (#103) read through this clause's
own frame.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from aeh.store import open_store
from tests.contract.grade._drive import current_grades, graded_run
from tests.contract.orch._doubles import install_audit
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

#: M-GRADE's declared write set, per tier — the closed set the audit reads back.
_COHORT_TABLES = {"submission_grade", "review_queue"}
_DURABLE_TABLES = {"audit_record", "run_metrics"}
_PROHIBITED = ("criterion_score", "verdict", "narrative")


def _writers(audit, table):
    """The modules that wrote one table inside the audited window."""
    return {record.module for record in audit.writes if record.table == table}


def _tables(audit):
    """Every table written inside the audited window."""
    return {record.table for record in audit.writes}


def test_tc_grade_c14_the_grade_ledger_has_exactly_one_writer(tmp_data_dir):
    """`TC-GRADE-C14` (`CT-GRADE-14`, rung 3) — under the write audit, every
    `submission_grade` write across the pass, the amendment and the batch
    finalization is `aeh.grade`'s. A second writer on the grade ledger is the
    delivered-revision defect the whole amendment contract exists to fence."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-ONE",),
            criteria=_CRITERIA,
            rows=(
                ("S-ONE", "C1", "B2", 7.0, "auto"),
                ("S-ONE", "C2", "B2", 5.0, "auto"),
            ),
            compute=False,
        )
        # The audit installs AFTER the fixture's disclosed seeding and BEFORE the
        # first production statement — the log holds only what the grading path
        # wrote (the TC-ORCH-17 precedent's own order).
        cohort_audit, durable_audit = install_audit(store, "c-2026-7B-orch")
        world.service.compute_all(world.run_id)
        world.service.amend(
            world.run_id, "S-ONE", {"C1": 10.0}, actor="teacher-1", reason="band move",
        )
        world.service.finalize_batch(world.run_id, actor="operator-7")

        grade_writers = _writers(cohort_audit, "submission_grade")
        assert grade_writers == {"aeh.grade"}, (
            f"the grade ledger was written by {sorted(grade_writers)} — "
            "`submission_grade` has exactly one writer (CT-GRADE-14's sole "
            "writership); a second writer on the delivered-revision table is the "
            "tampering surface the clause fences"
        )
        assert any(record.table == "submission_grade" for record in cohort_audit.writes), (
            "the audit recorded no grade-ledger write at all — the drive never "
            "graded, so the sole-writer claim would be vacuous (CT-GRADE-14)"
        )
    finally:
        store.close()


def test_tc_grade_c14_the_write_set_is_closed_and_touches_no_prohibited_table(
    tmp_data_dir,
):
    """`TC-GRADE-C14`'s write-set and prohibition limbs (rung 3) — the audited
    window's write set is closed at the declared tables, and NO ONE writes
    `criterion_score`, `verdict` or `narrative` in it: the aggregation inputs are
    M-AGG's alone, the verdicts the judges', the narratives the synthesizer's. A
    grading pass that touched them would be a second writer on three other
    modules' ledgers at once. The figures' writership rides here too: the shipped
    `criterion_stats` surfaces are reads, so the window writes no figure table —
    computed over the stored scores, never stored beside them."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    separated_rollup = require(GRADE_MODULE, "separated_rollup", issue="#104")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-ONE",),
            criteria=(
                {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
                {"criterion_id": "C2", "kind": "mcq", "scoring_model": "atomic"},
            ),
            rows=(
                ("S-ONE", "C1", "B2", 7.0, "auto"),
                ("S-ONE", "C2", "correct", 4.0, "auto"),
            ),
            compute=False,
        )
        cohort_audit, durable_audit = install_audit(store, "c-2026-7B-orch")
        world.service.compute_all(world.run_id)
        world.service.amend(
            world.run_id, "S-ONE", {"C1": 10.0}, actor="teacher-1", reason="band move",
        )
        world.service.finalize_batch(world.run_id, actor="operator-7")
        # Read-only members ride the same window: the rollup and the export are
        # reads over the stored rows, so they add no table to the set.
        world.service.rollup(world.run_id)
        separated_rollup(world.run_id, store)
        world.service.export(world.run_id, 1, "csv")

        assert _tables(cohort_audit) <= _COHORT_TABLES, (
            f"the grading path wrote cohort tables "
            f"{sorted(_tables(cohort_audit) - _COHORT_TABLES)!r} outside its "
            "declared set — M-GRADE's write set is closed (CT-GRADE-14's "
            "writership clause)"
        )
        assert _tables(durable_audit) <= _DURABLE_TABLES, (
            f"the grading path wrote durable tables "
            f"{sorted(_tables(durable_audit) - _DURABLE_TABLES)!r} outside its "
            "declared set (CT-GRADE-14)"
        )
        # The prohibition, per table: nobody — not a production module, not the
        # test scaffolding — wrote one in the audited window.
        for table in _PROHIBITED:
            writers = _writers(cohort_audit, table)
            assert writers == set(), (
                f"`{table}` was written by {sorted(writers)!r} inside the audited "
                "grading window — M-GRADE never writes the aggregation inputs, "
                "the verdicts or the narratives (CT-GRADE-14's prohibition)"
            )
        # Non-vacuousness: the audit covered a real pass — the prohibition is over
        # a window in which the grade ledger WAS written.
        assert _writers(cohort_audit, "submission_grade") == {"aeh.grade"}, (
            "the audited window never wrote the grade ledger — a prohibition over "
            "an empty window proves nothing (CT-GRADE-14)"
        )
        assert _writers(durable_audit, "audit_record") == {"aeh.grade"}, (
            f"audit_record was written by "
            f"{sorted(_writers(durable_audit, 'audit_record'))!r} — the audit table "
            "has exactly one writer too (CT-GRADE-14)"
        )
    finally:
        store.close()


def test_tc_grade_c14_an_attempted_edit_of_the_audit_record_is_refused(tmp_data_dir):
    """`TC-GRADE-C14`'s append-only limb (rung 3) — the amendment's audit record is
    real (it names the criterion it records), and an UPDATE and a DELETE against it
    are REFUSED — attempted, not assumed, because an audit record that can be
    edited is not an audit record. The refusal leaves the trail standing."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    require(GRADE_MODULE, "enforce_ledger_append_only", issue="#103")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-ONE",),
            criteria=_CRITERIA,
            rows=(("S-ONE", "C1", "B2", 7.0, "auto"), ("S-ONE", "C2", "B2", 5.0, "auto")),
        )
        world.service.amend(
            world.run_id, "S-ONE", {"C1": 10.0}, actor="teacher-1", reason="band move",
        )
        durable = store.durable()
        rows = durable.query(
            "SELECT profile_summary, decided_by FROM audit_record "
            "WHERE submission_id = :s", s="S-ONE",
        )
        assert len(rows) == 1 and rows[0]["decided_by"] == "teacher-1", (
            "fixture bug: the amendment's audit record did not land (CT-GRADE-14)"
        )
        detail = json.loads(rows[0]["profile_summary"])
        assert [entry["criterion_id"] for entry in detail["criteria"]] == ["C1"], (
            f"the audit record's detail names {detail['criteria']!r} — the "
            "append-only record is per criterion, the trail a dispute reads "
            "(CT-GRADE-14's per-criterion clause)"
        )

        # The tamper verbs, attempted: both refused by the owning module's own
        # enforcement, and the refusal leaves the record standing.
        with durable.transaction() as tx:
            with pytest.raises(sqlite3.IntegrityError, match="append-only") as refused:
                tx.execute(
                    "UPDATE audit_record SET decided_by = 'someone-else' "
                    "WHERE submission_id = :s", s="S-ONE",
                )
        assert "append-only" in str(refused.value).lower(), (
            f"the refusal read {refused.value!r} — a tamper attempt must be "
            "readable as tampering from the error alone (CT-GRADE-14)"
        )
        with durable.transaction() as tx:
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                tx.execute("DELETE FROM audit_record WHERE submission_id = :s", s="S-ONE")
        after = durable.query(
            "SELECT COUNT(*) AS n FROM audit_record WHERE submission_id = :s", s="S-ONE"
        )
        assert after[0]["n"] == 1, (
            "the audit trail vanished when the tamper attempt was refused — a "
            "refusal that deletes is not a refusal (CT-GRADE-14)"
        )
    finally:
        store.close()