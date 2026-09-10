"""`TC-GRADE-23` — the grade ledger is append-only: an in-place mutation of a
`submission_grade` row is refused, and the audit table admits no update or delete.

Test plan §5.14; `FR-GRADE-12` ("it shall not mutate the delivered revision"); design
§3.14's security paragraph ("Writes the append-only `audit_record`", *Tampering* with a
delivered grade is the threat the clause answers) and the security census's own words
(§4.1: *"append-only discipline on `audit_record` **enforced by the owning module**"* —
M-GRADE is `audit_record`'s writer per `CT-GRADE-14`); Integration / 2, negative; exact
exception; P0.

**Written ahead of implementation** (test plan §8.2). The refusal has no shipped
mechanism: today's store admits a raw `UPDATE submission_grade` through the cohort
handle — settlement's in-place state write is the ONLY legal mutation (provisional→
final), and nothing at the database refuses an edit of a delivered revision's content,
or an `UPDATE`/`DELETE` against `audit_record`. `#103` — the finalization/amendment
story whose acceptance criterion is *"the delivered revision is not mutated"* and whose
design owns the append-only discipline (detailed-design.md line *"append-only
discipline on `audit_record` enforced by the owning module"*) — lands the enforcement
(the `aeh.pkg` migration-`pkg_version_lineage` precedent: `BEFORE UPDATE`/`BEFORE
DELETE` triggers that `RAISE(ABORT)`), so this file carries `@pytest.mark.writtenahead`
and its registry entry names the symbol below.

**The invented-and-disclosed key** (the `evaluate_alerts` / `export_grade_artifacts`
precedent — a name no design document declares, that the test calls and #103's landing
reconciles): `aeh.grade:enforce_ledger_append_only`. M-GRADE owns both surfaces the
case pins (`CT-GRADE-14`: sole writer of `submission_grade`, writer of the append-only
`audit_record`), so the enforcement seam is grade-owned; the name is absent from both
design documents (checked: zero occurrences). If #103 ships the discipline as bare
triggers with no function, the require is a one-line rename to whatever surface the
triggers ride — the refusals asserted below do not move.

Oracle: exact exception — the `aeh/pkg.py` immutability-trigger precedent
(`test_grade_policy_and_keys.py`): the refusal is the trigger's `RAISE(ABORT)` read
back as `sqlite3.IntegrityError` carrying the `append-only` message. Pinned as the
exact type and the message token, so a bare constraint failure or a silent no-op
cannot pass for the refusal.

**Disclosed stand-ins** (`grade_vocabulary.py`, header): `write_criterion_scores`
standing in for `M-AGG`; the run-completion UPDATE (`M-ORCH` is the run row's single
writer).

**Isolation:** rung 2 — real store, real grade ledger, real Tier D audit table.
"""

from __future__ import annotations

import sqlite3

import pytest

from aeh.store import open_store
from tests.support.grade_vocabulary import GRADE_BLOCKER, write_criterion_scores
from tests.support.impl import GRADE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [
    pytest.mark.integration,
    # Red by design until #103 lands the append-only enforcement this case pins
    # (WRITTEN_AHEAD_BLOCKERS: "#103 append-only enforcement" ->
    # `aeh.grade:enforce_ledger_append_only`).
    pytest.mark.writtenahead,
]

ISSUE = "#103"

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)


def _seed_final_run(store):
    """One graded, settled submission — a delivered revision worth tampering with."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    _orchestrator, run_id, version = seed_run(
        store, submissions=("S-L1",), criteria=_CRITERIA
    )
    cohort = store.cohort("c-2026-7B-orch")
    write_criterion_scores(
        cohort,
        [("S-L1", "C1", "B2", 7.0, "auto"), ("S-L1", "C2", "B1", 6.0, "auto")],
    )
    svc = require(GRADE_MODULE, "open_grade", issue=ISSUE)(store)
    svc.compute_all(run_id)
    return run_id, cohort, svc


def test_tc_grade_23_a_delivered_revision_refuses_an_in_place_update(tmp_data_dir):
    """`TC-GRADE-23` — the in-place UPDATE is refused, exactly: `sqlite3.IntegrityError`
    (the trigger's RAISE(ABORT), the `aeh/pkg.py` immutability precedent), its message
    naming the append-only discipline. A silent accepted UPDATE would let a delivered
    grade be rewritten with no new revision, no superseded row, and no audit trail —
    FR-GRADE-12's whole amendment contract bypassed in one statement."""
    require(GRADE_MODULE, "enforce_ledger_append_only", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort, _svc = _seed_final_run(store)

        with cohort.transaction() as tx:
            with pytest.raises(sqlite3.IntegrityError, match="append-only") as refused:
                tx.execute(
                    "UPDATE submission_grade SET total = 99.0 "
                    "WHERE run_id = :r AND submission_id = :s",
                    r=run_id, s="S-L1",
                )
        assert "append-only" in str(refused.value).lower(), (
            "the refusal's message does not name the discipline — a tamper attempt "
            "must be readable as tampering from the error alone (the aeh/pkg.py "
            "immutability-trigger precedent)"
        )
    finally:
        store.close()


def test_tc_grade_23_the_audit_table_admits_no_update_or_delete(tmp_data_dir):
    """`TC-GRADE-23` — the audit table's half: no UPDATE and no DELETE reach
    `audit_record`, by the same append-only discipline ("audit records are never
    updated or deleted" — M-STORE's census promise, enforced by the owning module)."""
    require(GRADE_MODULE, "enforce_ledger_append_only", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        run_id, _cohort, svc = _seed_final_run(store)

        # A grade dispute is answered from the audit trail; a forged or expunged
        # record defeats the dispute path (the census's Tampering row). Both tamper
        # verbs are refused at the table, whatever row is targeted.
        durable = store.durable()
        with durable.transaction() as tx:
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                tx.execute(
                    "UPDATE audit_record SET recorded_at = '2026-01-01T00:00:00+00:00'"
                )
        with durable.transaction() as tx:
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                tx.execute("DELETE FROM audit_record WHERE run_id = :r", r=run_id)

        # The refusal is not silent erasure: whatever rows existed still do.
        rows = durable.query(
            "SELECT COUNT(*) AS n FROM audit_record WHERE run_id = :r", r=run_id
        )
        assert rows, (
            "the audit trail vanished when the tamper attempt was refused — a refusal "
            "that deletes is not a refusal"
        )
    finally:
        store.close()