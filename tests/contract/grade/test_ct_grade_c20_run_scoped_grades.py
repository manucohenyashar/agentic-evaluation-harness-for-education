"""`TC-GRADE-C20` — a run's grades do not move when another run lands (§6.11, `CT-GRADE-20`).

| Input | Expected |
|---|---|
| `compute_all(A)` before and after run B is scored over the same cohort | an equal `SubmissionGrade` set, compared field by field |

**The differential is the oracle, and a single-run fixture cannot produce it.** With one run in
the cohort, a grade read that dropped `run_id` returns exactly the same rows as one that kept
it — the filter is a no-op on a population of one. Every `TC-GRADE` case that stands on a
single run therefore stays green while the filter is missing. The second run is what makes the
predicate observable.

**Why it is `CT-GRADE-20` rather than a performance nicety.** A cohort is graded more than once
over its life — a re-run after a package correction, a second administration, a re-scored
criterion. If any grade read pools runs, the teacher's delivered grades change when somebody
starts an unrelated run, and the change is silent: the new totals are arithmetically correct
for a population nobody asked about.

**Field by field, not by count.** Two runs over one cohort produce the same number of grades,
so a count comparison is satisfied by a read that returned run B's rows for run A. The
comparison is over `(submission_id, revision, state, grade, total, policy_version)` — every
field a teacher or a downstream consumer reads.

**Isolation: rung 3** — two real runs over one real cohort, graded through the shipped door.
"""

from __future__ import annotations

import dataclasses
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
from aeh.grade import SubmissionGrade, open_grade
from aeh.orch import Orchestrator
from aeh.pkg import GradePolicy, PackageCatalog
from aeh.store import open_store
from aeh.store import Statement
from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_run

pytestmark = [pytest.mark.contract, pytest.mark.integration]

SUBMISSIONS = ("S001", "S002", "S003")
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

#: The fields a teacher or a downstream consumer reads. `computed_at` and `finalized_at` are
#: excluded deliberately: they are wall clocks, and a second `compute_all` legitimately
#: re-stamps a settlement.
COMPARED_FIELDS = (
    "run_id", "submission_id", "revision", "state", "grade", "total", "policy_version",
)


#: Written directly rather than through `write_criterion_scores`, which resolves its `run_id`
#: as "the newest run" — a subquery whose tiebreak between two unstarted runs is a uuid
#: comparison. This case needs each run's rows to be *this* run's, so the id is bound.
_INSERT_SCORE = Statement(
    "INSERT OR REPLACE INTO criterion_score (run_id, submission_id, criterion_id, band, "
    "points, routing, state) VALUES (:run_id, :submission_id, :criterion_id, :band, "
    ":points, 'auto', 'final')"
)


def _score_run(store: Any, run_id: str, band: str, points: float) -> None:
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        for submission in SUBMISSIONS:
            tx.execute(
                _INSERT_SCORE,
                run_id=run_id, submission_id=submission, criterion_id=CRITERION,
                band=band, points=points,
            )


def _comparable(grades: Any) -> list[tuple]:
    rows = [
        tuple(getattr(grade, name) for name in COMPARED_FIELDS)
        for grade in grades
    ]
    return sorted(rows)


def _graded(service: Any, run_id: str) -> list[Any]:
    """Grade the run, then read back each submission's `SubmissionGrade`.

    `compute_all` returns a `GradeReport` — the pass's stage-level summary (seam 4), not the
    grades — so the read-back is `compute_one` per submission. That is also the shape the
    clause is about: `compute_one` is the per-submission read a console or an export makes,
    and it is the one that would pool runs if its predicate were missing.
    """
    report = service.compute_all(run_id)
    assert report.run_id == run_id, (
        f"compute_all({run_id!r}) reported run {report.run_id!r}"
    )
    return [service.compute_one(run_id, submission) for submission in SUBMISSIONS]


@pytest.fixture
def two_runs(tmp_data_dir):
    """Run A scored over the cohort, and run B created but not yet scored."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_a, version = seed_run(
            store, submissions=SUBMISSIONS, criteria=CRITERIA,
        )
        PackageCatalog(
            store.package("pkg-orch"), package_id="pkg-orch"
        ).set_grade_policy(
            version, GradePolicy(combination="weighted_sum", weights=((CRITERION, 1.0),))
        )
        run_b = Orchestrator(store).create_run(ORCH_COHORT_ID, version, orch_cfg())
        _score_run(store, run_a, "B3", 6.0)
        yield store, run_a, run_b
    finally:
        store.close()


# --- TC-GRADE-C20 --------------------------------------------------------------------------------


def test_tc_grade_c20_a_runs_grades_are_unchanged_when_another_run_is_scored(two_runs):
    """`compute_all(A)` returns the same grades before and after run B lands.

    The differential. Run B is scored with **different** points, so a read that pooled the two
    runs would produce a different total for every submission rather than merely a different
    row count — the failure is arithmetic, not structural, which is why the comparison is on
    values.
    """
    store, run_a, run_b = two_runs
    service = open_grade(store)

    before = _comparable(_graded(service, run_a))
    assert before, "run A produced no grades, so the differential compares two empty sets"

    # Run B scores the same cells differently. If any grade read drops run_id, A's totals move.
    _score_run(store, run_b, "B1", 1.0)
    _graded(open_grade(store), run_b)

    after = _comparable(_graded(open_grade(store), run_a))

    assert after == before, (
        "run A's grades moved when run B was scored.\n"
        f"  before: {before}\n"
        f"  after:  {after}\n"
        "A cohort is graded more than once over its life; if a grade read pools runs, the "
        "teacher's delivered grades change when somebody starts an unrelated run — and the "
        "new totals are arithmetically correct for a population nobody asked about "
        "(CT-GRADE-20)"
    )


def test_tc_grade_c20_each_grade_names_its_own_run(two_runs):
    """Every `SubmissionGrade` carries `run_id`, and it is the run that was graded.

    The structural half. Without it the differential above could hold for a read that returned
    one run's rows to both callers — identical, and wrong for one of them.
    """
    store, run_a, run_b = two_runs
    service = open_grade(store)

    grades_a = _graded(service, run_a)
    assert {grade.run_id for grade in grades_a} == {run_a}, (
        f"run A's grades name runs {sorted({g.run_id for g in grades_a})}, not {run_a!r}"
    )

    _score_run(store, run_b, "B1", 1.0)
    grades_b = _graded(open_grade(store), run_b)
    assert {grade.run_id for grade in grades_b} == {run_b}, (
        f"run B's grades name runs {sorted({g.run_id for g in grades_b})}, not {run_b!r}"
    )


def test_tc_grade_c20_the_two_runs_really_do_differ(two_runs):
    """The fixture's own precondition: B's scores produce different totals from A's.

    Without this the differential is vacuous — two runs scored identically stay equal under
    any implementation, filtered or not, and the case would pass over the defect it exists
    for.
    """
    store, run_a, run_b = two_runs
    service = open_grade(store)
    totals_a = {g.submission_id: g.total for g in _graded(service, run_a)}

    _score_run(store, run_b, "B1", 1.0)
    totals_b = {
        g.submission_id: g.total for g in _graded(open_grade(store), run_b)
    }

    assert totals_a and totals_b
    assert totals_a != totals_b, (
        f"both runs total the same: {totals_a}. The differential can then be satisfied by a "
        "read that pools them, and this case would pass over the defect it exists for"
    )


def test_tc_grade_c20_submission_grade_declares_its_run(two_runs):
    """`SubmissionGrade` carries a `run_id` field at all.

    A type-level guard on the cases above: a grade shape without the field could not be
    run-scoped by any reader, and every value assertion would be comparing something else.
    """
    fields = {field.name for field in dataclasses.fields(SubmissionGrade)}
    assert "run_id" in fields, (
        f"SubmissionGrade carries {sorted(fields)} — no run_id, so a grade cannot name the "
        "run that produced it (CT-GRADE-20)"
    )
