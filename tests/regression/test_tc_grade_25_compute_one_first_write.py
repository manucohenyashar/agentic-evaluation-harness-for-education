"""`TC-GRADE-25` — `compute_one` grades a submission that has no grade row yet (FR-GRADE-07).

| Input | Expected |
|---|---|
| (a) `compute_one(run, S001)` with every criterion scored, no prior `compute_all` | one `provisional` grade row (the review window is open), revision 1 |
| (b) `compute_one(run, S002)` with one criterion unscored | one `incomplete` grade row and a review-queue row naming that criterion, under this run |

**Regression.** `_grade_one` — the write half of `compute_one` — named an
unbound `run_id` on both of its queue writes, so every first write through the per-student door
raised `NameError`. It stayed hidden because every earlier case calls `compute_all` first: the
batch pass writes the rows, and `compute_one` then finds an unchanged grade and returns before
reaching the queue writes. Each arm here calls `compute_one` on a submission with no row, so
each queue branch (insert, and delete) is executed.

**Isolation: rung 3** — a real seeded run over a real cohort, graded through the shipped door.
"""

from __future__ import annotations

from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.grade import open_grade
from aeh.pkg import GradePolicy, PackageCatalog
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration]

SUBMISSIONS = ("S001", "S002")
CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)

_INSERT_SCORE = Statement(
    "INSERT OR REPLACE INTO criterion_score (run_id, submission_id, criterion_id, band, "
    "points, routing, state) VALUES (:run_id, :submission_id, :criterion_id, 'B3', "
    "3.0, 'auto', 'final')"
)
_GRADE_ROWS = Statement(
    "SELECT state, revision FROM submission_grade WHERE run_id = :run_id "
    "AND submission_id = :submission_id"
)
_QUEUE_ROWS = Statement(
    "SELECT run_id, criterion_id FROM review_queue WHERE submission_id = :submission_id"
)


@pytest.fixture
def seeded(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        _, run_id, version = seed_run(store, submissions=SUBMISSIONS, criteria=CRITERIA)
        PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch").set_grade_policy(
            version,
            GradePolicy(combination="weighted_sum", weights=(("C1", 1.0), ("C2", 1.0))),
        )
        scored = (("S001", "C1"), ("S001", "C2"), ("S002", "C1"))
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            for submission, criterion in scored:
                tx.execute(
                    _INSERT_SCORE, run_id=run_id, submission_id=submission,
                    criterion_id=criterion,
                )
        yield store, run_id
    finally:
        store.close()


def _rows(store: Any, statement: Statement, **params: Any) -> list[tuple]:
    return [tuple(row) for row in store.cohort(ORCH_COHORT_ID).query(statement, **params)]


def test_tc_grade_25a_compute_one_writes_a_complete_grade_without_a_batch_pass(seeded):
    store, run_id = seeded
    grade = open_grade(store).compute_one(run_id, "S001")
    assert grade.run_id == run_id and grade.submission_id == "S001"
    assert _rows(store, _GRADE_ROWS, run_id=run_id, submission_id="S001") == [("provisional", 1)]
    assert _rows(store, _QUEUE_ROWS, submission_id="S001") == []


def test_tc_grade_25b_compute_one_queues_the_missing_criterion_under_this_run(seeded):
    store, run_id = seeded
    open_grade(store).compute_one(run_id, "S002")
    assert _rows(store, _GRADE_ROWS, run_id=run_id, submission_id="S002") == [("incomplete", 1)]
    assert _rows(store, _QUEUE_ROWS, submission_id="S002") == [(run_id, "C2")]
