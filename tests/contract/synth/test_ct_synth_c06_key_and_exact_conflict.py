"""`TC-SYNTH-C06` — the narrative key, and the exact conflict it exists for (§6.11.13).

`CT-SYNTH-06`'s data clause at rung 2: `narrative` is keyed
`(run_id, submission_id, level, question_id)` with `question_id NOT NULL`, L2 rows
storing the `'__test__'` sentinel — and the property the key exists for: a
**retried** synthesis unit **conflicts rather than inserting a duplicate**, asserted
by the module's OWN insert statement re-executed against a completed row. SQLite
permits NULLs in the columns of a non-INTEGER primary key, which is precisely the
hole the declared `NOT NULL` closes — so the case asserts the key's shape, the NOT
NULL, and the exact `sqlite3.IntegrityError` a second insert of the same identity
raises.

Relationship to shipped cases: `tests/integration/synth/
test_completeness_and_sentinel.py` (`TC-SYNTH-10`) holds the NOT NULL pragma, the
sentinel, and the retry-absorbs shape through the driver; `tests/security/synth/
test_narrative_tier_r_purge.py` reads the same table at Tier R. This case adds the
exact PRIMARY KEY column order, the exact exception on the module's declared
statement (`SYNTH_STATEMENTS["insert_narrative"]`, not a hand-written twin), and the
no-provider-call absorption — the concrete discharge of `CT-ORCH-04`'s
at-least-once obligation for this worker.

Isolation: rung 2 — real SQLite, `CaptureProvider` at the model boundary.
"""

from __future__ import annotations

import sqlite3

import pytest

from aeh.store import open_store
from tests.support.impl import SYNTH_MODULE, require
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    COHORT_ID,
    FIVE_QUESTION_CRITERIA,
    SYNTH_ISSUE,
    WORKER,
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.contract]

_SUBMISSION = "SYN-001"
_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))

#: ADR-8's key, in declaration order — the case's schema oracle.
KEY_COLUMNS = ("run_id", "submission_id", "level", "question_id")


def _replies() -> list:
    replies = [
        narrative_completion(
            f"Question {q[1:]}: the response states the hypothesis and cites the "
            "worked steps for this question.",
            (f"{q}C1", f"{q}C2"),
        )
        for q in _QUESTIONS
    ]
    replies.append(narrative_completion("Overall: the submission works through each question in turn."))
    return replies


def _seeded_store(tmp_data_dir):
    store = open_store(tmp_data_dir)
    _, run_id, _ = seed_run(store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA)
    seed_scored_submission(store, run_id, _SUBMISSION, complete_questions=set(_QUESTIONS))
    return store, run_id


def test_tc_synth_c06_the_narrative_table_is_keyed_as_declared(tmp_data_dir):
    """`TC-SYNTH-C06` (P0, schema half) — the declared key holds as a PRIMARY KEY on
    exactly `(run_id, submission_id, level, question_id)`, with `question_id NOT
    NULL` closing SQLite's NULL-in-PK hole, and the L2 sentinel stored."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    store, run_id = _seeded_store(tmp_data_dir)
    try:
        Worker(store, CaptureProvider(_replies()), synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )

        columns = store.cohort(COHORT_ID).query("PRAGMA table_info(narrative)")
        info = {row["name"]: dict(row) for row in columns}
        assert set(info) == {
            "narrative_id", "submission_id", "criterion_id", "run_id", "level",
            "question_id", "text", "citations", "score_claim_flag",
        }, (
            f"narrative carries {sorted(info)} — the migration's declared column set "
            "(a silently added column is a second, undeclared key surface)"
        )
        key_rows = sorted(
            (column for column in info.values() if column["pk"] > 0),
            key=lambda column: column["pk"],
        )
        primary_key = tuple(column["name"] for column in key_rows)
        assert primary_key == KEY_COLUMNS, (
            f"narrative's PRIMARY KEY is {primary_key} — ADR-8's "
            f"{KEY_COLUMNS} is what makes a retried unit conflict rather than "
            "duplicate (CT-ORCH-04's obligation, discharged for this worker)"
        )
        assert info["question_id"]["notnull"] == 1, (
            "question_id must be NOT NULL — SQLite permits NULLs in the columns of "
            "a non-INTEGER primary key, which is exactly the hole the declared "
            "constraint closes (an L1 row without a question would collide with "
            "nothing and duplicate freely)"
        )

        l2_rows = store.cohort(COHORT_ID).query(
            "SELECT question_id FROM narrative WHERE run_id = :r AND "
            "submission_id = :s AND level = 'l2_test'",
            r=run_id, s=_SUBMISSION,
        )
        assert [row["question_id"] for row in l2_rows] == ["__test__"], (
            "the L2 row stores the '__test__' sentinel as its question_id — the "
            "sentinel is what lets an L2 row take part in the same key"
        )
    finally:
        store.close()


def test_tc_synth_c06_a_duplicate_identity_conflicts_exactly(tmp_data_dir):
    """`TC-SYNTH-C06` (P0, conflict half) — re-inserting a completed narrative's
    identity through the module's OWN statement raises the exact
    `sqlite3.IntegrityError`: the declared key conflicts a concurrent duplicate
    rather than storing two."""
    store, run_id = _seeded_store(tmp_data_dir)
    try:
        Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
        Worker(store, CaptureProvider(_replies()), synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )
        SynthStatements = require(SYNTH_MODULE, "SYNTH_STATEMENTS", issue=SYNTH_ISSUE)

        before = store.cohort(COHORT_ID).query(
            "SELECT COUNT(*) AS n FROM narrative WHERE run_id = :r", r=run_id
        )[0]["n"]
        assert before == 6, "precondition: the completed run's six narrative rows"

        duplicate = dict(
            narrative_id=f"nar:{run_id}:{_SUBMISSION}:l1_question:Q1",
            run_id=run_id,
            submission_id=_SUBMISSION,
            level="l1_question",
            question_id="Q1",
            text="a concurrent duplicate's prose",
            citations="[]",
            score_claim_flag=0,
        )
        with pytest.raises(sqlite3.IntegrityError) as conflict:
            with store.cohort(COHORT_ID).transaction() as tx:
                tx.execute(SynthStatements["insert_narrative"], **duplicate)
        assert "UNIQUE" in str(conflict.value) or "PRIMARY KEY" in str(conflict.value), (
            f"the second insert failed with {conflict.value!r} — the duplicate must "
            "be refused by the declared key itself, not by an application-side check "
            "a second writer could bypass"
        )

        after = store.cohort(COHORT_ID).query(
            "SELECT COUNT(*) AS n FROM narrative WHERE run_id = :r", r=run_id
        )[0]["n"]
        assert after == before, (
            f"{after} rows after the refused insert — the conflict stored nothing"
        )
    finally:
        store.close()


def test_tc_synth_c06_a_retried_unit_absorbs_without_a_provider_call(tmp_data_dir):
    """`TC-SYNTH-C06` (P0, idempotency half) — re-running the completed driver
    absorbs every narrative identity: no provider call is made, no row appears, and
    the report still describes the stored six. This is `CT-ORCH-04`'s
    at-least-once safety, discharged for the synthesis worker."""
    store, run_id = _seeded_store(tmp_data_dir)
    try:
        Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
        first = Worker(store, CaptureProvider(_replies()), synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )
        assert first.narratives == 6, "precondition: the first drive stored six rows"

        # The retried driver gets a provider that fails the test if it is EVER
        # called — the stored narratives must absorb the retry at the read, not at
        # a second round of model calls.
        retried = Worker(store, CaptureProvider([]), synth_ref()).synthesize_submission(
            run_id, _SUBMISSION
        )
        assert retried.model_calls == 0, (
            f"the retry made {retried.model_calls} model calls — a stored narrative "
            "identity absorbs its retry at the read (CT-ORCH-04), and re-composing "
            "narratives that already exist would spend the model twice for the same "
            "row"
        )
        assert retried.narratives == 6, (
            f"the retry reports {retried.narratives} narratives — the stored rows "
            "stand; the retry must not have erased or re-counted them"
        )
        assert retried.failures == 0, (
            "the retry must not convert the absorption into a failure — the "
            "narratives are present and were found"
        )
    finally:
        store.close()
