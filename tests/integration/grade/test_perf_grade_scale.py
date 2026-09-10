"""`TC-GRADE-20` — grading and rollup for the full class at the design's scale.

Test plan §5.14; `NFR-GRADE-03` / `PERF-07` ("grading and rollup ... single pass ...
350 submissions ... < 30 s, zero model calls"); Performance / 2; metric threshold; P1.

`PERF-07` pins the measured quantity: **one grading pass plus the rollup**, timed as a
single combined numerator on a real store. The fixture is the design's 350-student
class — the same uniform shape `TC-GRADE-09`'s batch-finalization case runs — seeded
fully scored before the clock starts (seeding writes `criterion_score` rows directly,
the disclosed `M-AGG` stand-in; it is fixture production, not the measured quantity,
and timing it would measure the stand-in, not the module).

Zero model calls is asserted, not assumed: the orchestrator behind the run is
report-only (`seed_run`'s default `transport=None` — there is no transport to make a
call with), the autouse socket guard is active, and the guard's own record is
explicitly asserted empty at the end — a grading module that phoned a judge would
finish fast and fail here.

Threshold: the plan's 30 s, never weakened.

Isolation: rung 2 — real store, real package lineage, real grade ledger.
"""

from __future__ import annotations

import time

import pytest

from aeh.pkg import GradePolicy, PackageCatalog
from aeh.store import open_store
from tests.support.grade_vocabulary import (
    GRADE_BLOCKER,
    grade_rows,
    write_criterion_scores,
)
from tests.support.impl import GRADE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration]

ISSUE = GRADE_BLOCKER

_PACKAGE = "pkg-orch"

#: The design's 350-student class — the same uniform fixture shape TC-GRADE-09 pins.
_SUBMISSIONS = tuple(f"S{i:03d}" for i in range(1, 351))

#: `NFR-GRADE-03` / `PERF-07`: grading plus rollup for 350 submissions, under 30 s.
BUDGET_S = 30.0


def _seed_scored_run(store):
    """The 350-student run, every submission fully scored under a windowless policy.
    Untimed: fixture production, not the measured quantity (see the module docstring)."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    criteria = (
        {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
        {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
    )
    _orchestrator, run_id, version = seed_run(
        store, submissions=_SUBMISSIONS, criteria=criteria
    )
    catalog = PackageCatalog(store.package(_PACKAGE), package_id=_PACKAGE)
    catalog.set_grade_policy(version, GradePolicy(combination="weighted_sum"))
    cohort = store.cohort(ORCH_COHORT_ID)
    write_criterion_scores(
        cohort,
        [(sid, "C1", "B2", 7.0, "auto") for sid in _SUBMISSIONS]
        + [(sid, "C2", "B1", 6.0, "auto") for sid in _SUBMISSIONS],
    )
    return run_id, cohort


def test_tc_grade_20_grading_and_rollup_for_350_submissions_under_30s(
    tmp_data_dir, network_guard
):
    """`TC-GRADE-20` — one `compute_all` pass plus the rollup over 350 fully-scored
    submissions, wall clock under `PERF-07`'s 30 s budget, and not one model call."""
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort = _seed_scored_run(store)
        svc = require(GRADE_MODULE, "open_grade", issue=ISSUE)(store)

        t0 = time.perf_counter()
        report = svc.compute_all(run_id)
        rollup = svc.rollup(run_id)
        elapsed = time.perf_counter() - t0

        # The measured pass did the work: every submission of the 350-student class
        # got its grade, and the pass says so itself. A pass that skipped submissions
        # would come in under budget and measure nothing.
        assert report.computed == 350, (
            f"the graded pass reports computed={report.computed!r}, expected 350 — "
            "the budget's input is the full class, and a smaller n measures nothing "
            "(PERF-07: 350 submissions)"
        )
        rows = grade_rows(cohort)
        assert len(rows) == 350 and all(row["is_current"] for row in rows), (
            f"the ledger holds {len(rows)} rows after the pass — one revision per "
            "submission of the 350-student class (fixture drift)"
        )
        assert rollup is not None, (
            "the rollup returned nothing — it is the second half of the measured pair"
        )

        assert elapsed < BUDGET_S, (
            f"grading + rollup took {elapsed:.2f}s over 350 submissions, over "
            f"PERF-07's {BUDGET_S:.0f}s budget — at the design's scale grading must "
            "never be the wait the school feels (NFR-GRADE-03, TC-GRADE-20)"
        )

        # Zero model calls: the guard's record is the honest check — the socket guard
        # was active for the whole pass, and nothing tried to leave the box.
        network_guard.assert_no_network()
    finally:
        store.close()