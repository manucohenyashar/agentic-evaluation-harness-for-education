"""`TC-SYNTH-09` and `TC-SYNTH-10` — the completeness gate and the sentinel-keyed
uniqueness (`M-SYNTH`, TS-37, P0, integration, rung 2).

- `TC-SYNTH-09` (`FR-SYNTH-06`): synthesis does not run for a submission whose criteria
  are still incomplete for that question, so no narrative describes a partial result as
  though it were whole. The incompleteness is seeded at BOTH surfaces a gate could read
  (`score` unit `pending` AND no verdict rows — see
  `seed_scored_submission`), so the case is honest whichever one `#97`'s gate reads.
- `TC-SYNTH-10` (`FR-SYNTH-07`, ADR-8): `narrative.question_id` is `NOT NULL`, with the
  `'__test__'` sentinel stored for L2 rows, so the declared primary key actually
  enforces uniqueness and a retried synthesis unit **conflicts rather than inserting a
  duplicate**. The schema half asserts the live SQLite DDL (`PRAGMA table_info`), not a
  constant in the source — a `NOT NULL` the migration forgot is exactly the hole the
  declared-PK argument depends on.

Written ahead of `#97` (test plan §8.2): fails only through `NotImplementedYet` naming
`#97`, or — once the module lands — through the assertion itself (the schema probe
fails on the missing `question_id` column until `#97`'s migration runs).

Isolation: rung 2 — real SQLite in `tmp_data_dir`, real cohort/package/run rows; the
capture provider is the one permitted double. The `CaptureProvider.runs-dry` guard is
load-bearing for TC-SYNTH-09: if the gate fails to gate, the worker makes a sixth call
(the incomplete question's L1) and the provider's assertion — not a silent extra
narrative — is what turns red.

Interface assumed of `#97` (disclosed in `tests/support/synth_vocabulary.py`, reconcile
at landing): `SynthesisWorker(store, provider, model_ref)` with
`.synthesize_submission(run_id, submission_id) -> SynthesisReport`; the `narrative`
table after `#97`'s migration carries `run_id`, `level`, `question_id`, `text`, read
name-agnostically as row dicts; a retried `synthesize_submission` for the same
(submission, level, question) absorbs into the existing rows (ADR-8's conflict, whether
by refusal, no-op, or an explicit conflict the caller sees).
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.impl import SYNTH_MODULE, require
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    COHORT_ID,
    FIVE_QUESTION_CRITERIA,
    LEVEL_L2,
    SYNTH_ISSUE,
    TEST_SENTINEL,
    WORKER,
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.integration]

_SUBMISSION = "SYN-001"
_QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))


def _canned(count: int) -> CaptureProvider:
    """`count` L1 replies plus the one L2 reply, in the disclosed call order."""
    replies = [
        narrative_completion(
            f"Question {q[1:]}: the response states the hypothesis and cites the "
            f"worked steps for this question.",
            (f"{q}C1", f"{q}C2"),
        )
        for q in _QUESTIONS
    ] + [narrative_completion("Overall: the submission works through each complete question in turn.")]
    return CaptureProvider(replies[: count + 1])


def _narrative_rows(store, run_id: str) -> "list[dict]":
    # `store.cohort(...).query()` yields `sqlite3.Row`, which has no `.get` — convert
    # so the name-agnostic reads below run against plain dicts.
    return [
        dict(row)
        for row in store.cohort(COHORT_ID).query(
            "SELECT * FROM narrative WHERE run_id = :r AND submission_id = :s",
            r=run_id,
            s=_SUBMISSION,
        )
    ]


def test_tc_synth_09_incomplete_question_gets_no_narrative(tmp_data_dir):
    """`TC-SYNTH-09` (P0) — Q5's criteria are still incomplete: no L1 narrative for
    Q5, and nothing describes the partial result as though it were whole."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)

    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA)
        seed_scored_submission(
            store, run_id, _SUBMISSION,
            complete_questions=set(_QUESTIONS) - {"Q5"},
        )

        provider = _canned(count=4)  # four complete questions' L1 replies + the L2 one
        worker = Worker(store, provider, synth_ref())
        worker.synthesize_submission(run_id, _SUBMISSION)

        rows = _narrative_rows(store, run_id)
        partial = [row for row in rows if row.get("question_id") == "Q5"]
        assert not partial, (
            f"{len(partial)} narrative row(s) exist for Q5 whose criteria are still "
            "incomplete — FR-SYNTH-06: synthesis does not run for that question, "
            "because a narrative describing a partial result as though it were whole "
            "is feedback about work the student has not finished"
        )
        l1_questions = {
            row.get("question_id")
            for row in rows
            if row.get("level") != LEVEL_L2
        }
        assert l1_questions == {"Q1", "Q2", "Q3", "Q4"}, (
            f"L1 narratives exist for {sorted(l1_questions)} — the gate must skip "
            "exactly the incomplete question and run for the complete ones (a gate "
            "that skips nothing fails the first assertion; a gate that skips "
            "everything fails this one)"
        )
        assert provider.calls == 5, (
            f"{provider.calls} model calls with one question incomplete — four L1 "
            "calls plus the L2 call; a sixth call is the gate not gating, and the "
            "provider's runs-dry guard would already have named it"
        )
        assert any(row.get("level") == LEVEL_L2 for row in rows), (
            "no L2 narrative at all — the gate is per-question: the complete "
            "questions' syntheses still compose the test-level narrative (CT-SYNTH-05: "
            "a consumer infers incompleteness from the MISSING question's narrative)"
        )
    finally:
        store.close()


def test_tc_synth_10_sentinel_keyed_uniqueness_and_the_live_not_null(tmp_data_dir):
    """`TC-SYNTH-10` (P0) — the live schema declares `narrative.question_id` NOT NULL;
    L2 rows carry the `'__test__'` sentinel; a retried synthesis unit conflicts rather
    than inserting a duplicate."""
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)

    store = open_store(tmp_data_dir)
    try:
        # --- the live schema half: the DDL itself declares the column NOT NULL -----
        columns = store.cohort(COHORT_ID).query("PRAGMA table_info(narrative)")
        by_name = {row["name"]: row for row in columns}
        assert "question_id" in by_name, (
            f"narrative has no question_id column (live columns: {sorted(by_name)}) — "
            "FR-SYNTH-07: the sentinel-keyed primary key is what makes a retried "
            "synthesis unit conflict rather than duplicate"
        )
        assert by_name["question_id"]["notnull"] == 1, (
            "the live narrative schema does NOT declare question_id NOT NULL — "
            "FR-SYNTH-07 is a DDL fact: without the constraint the primary key does "
            "not enforce uniqueness and the retry inserts a duplicate"
        )

        _, run_id, _ = seed_run(store, submissions=(_SUBMISSION,), criteria=FIVE_QUESTION_CRITERIA)
        seed_scored_submission(store, run_id, _SUBMISSION, complete_questions=set(_QUESTIONS))

        worker = Worker(store, _canned(count=5), synth_ref())
        worker.synthesize_submission(run_id, _SUBMISSION)

        # --- the sentinel: L2 rows carry '__test__' in the NOT NULL column ---------
        rows = _narrative_rows(store, run_id)
        l2_rows = [row for row in rows if row.get("level") == LEVEL_L2]
        assert len(l2_rows) == 1, (
            f"{len(l2_rows)} L2 narrative rows — one test-level synthesis per "
            "submission (CT-SYNTH-06: keyed (run_id, submission_id, level, "
            "question_id))"
        )
        assert l2_rows[0].get("question_id") == TEST_SENTINEL, (
            f"L2 row stores question_id={l2_rows[0].get('question_id')!r}, expected "
            f"{TEST_SENTINEL!r} — ADR-8: without the sentinel the NOT NULL column has "
            "nothing to hold on an L2 row, and the declared key stops enforcing "
            "uniqueness exactly where the retry can duplicate"
        )
        assert all(row.get("question_id") for row in rows), (
            "a narrative row stores an empty question_id — the column is NOT NULL for "
            "every row, L1 and L2 alike"
        )

        # --- the retry: same identity again, conflicts rather than duplicating -----
        retried = Worker(store, _canned(count=5), synth_ref())
        try:
            retried.synthesize_submission(run_id, _SUBMISSION)
        except Exception:
            pass  # the conflict may surface as an explicit refusal (ADR-8) — either
            # form must leave the row count unchanged, which is the oracle below.

        after = _narrative_rows(store, run_id)
        assert len(after) == len(rows), (
            f"the retried synthesis unit grew the narrative table {len(rows)} -> "
            f"{len(after)} — ADR-8: at-least-once dispatch (CT-ORCH-04) means the "
            "worker runs twice on the same unit, and the keyed uniqueness must "
            "conflict the second write, not store a coin flip over which narrative "
            "ships"
        )
        assert len([row for row in after if row.get("level") == LEVEL_L2]) == 1, (
            "the retry inserted a second L2 row — the duplicate is ADR-8's named "
            "failure for exactly this unit"
        )
    finally:
        store.close()
