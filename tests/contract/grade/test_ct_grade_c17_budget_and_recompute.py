"""`TC-GRADE-C17` — the stated load's budget, the zero exact, and the recompute right (§6.11.14).

`CT-GRADE-17` (perf): "Threshold at the stated load: grading and rollup for 350
submissions under **30 seconds** with **zero** model calls — the zero asserted
exactly, since it is what makes the consumer's right credible. Then that right:
**consumers may recompute on demand**, asserted at rung 3 by recomputing on a
request path and confirming the budget holds."

The limbs, in the row's order:

- **the threshold, the zero exact** (rung 3, green): the design's 350-student
  class — one `compute_all` pass plus the rollup, wall clock under the plan's
  30 s — with the zero asserted EXACTLY: the socket guard's attempt record is
  empty, not merely unchecked. The zero is what makes the consumer's right
  credible, so a count equality against the guard's own log is the honest form,
  and the measured pass proves it did the work (an exact population, no
  silently-skipped submission coming in under budget and measuring nothing).
- **the recompute right, the budget holds** (rung 3, green): the consumer's right
  is `compute_one` — the one per-student entry point the Protocol declares — and
  the case exercises it on a request path: 25 on-demand recomputes sampled across
  the class, riding the same measured window. Each returns the batch pass's own
  figures for that submission (the recompute is the same arithmetic — the right
  would be worthless if the request path delivered different figures), and the
  window INCLUDING the recomputes stays under the budget: the right is free
  enough to use, and the zero still holds exactly.

The bare threshold at the stated load is landed at rung 2 as TC-GRADE-20
(`tests/integration/grade/test_perf_grade_scale.py`); this contract case carries
its row's discriminators — the exact zero and the recompute right — which the
perf case does not measure.

Isolation: rung 3 — real store, real package lineage, the orchestrator's own run
creation. The fixture build sits OUTSIDE every timed section (the budget is the
grading module's, not the seeding's) and the `criterion_score` rows are the
vocabulary's disclosed `M-AGG` stand-in. The socket guard is autouse and taken
explicitly for the exact-zero assertions.
"""

from __future__ import annotations

import time

import pytest

from aeh.pkg import GradePolicy, PackageCatalog
from aeh.store import open_store
from tests.support.grade_vocabulary import grade_rows, write_criterion_scores
from tests.support.impl import GRADE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.contract]

_PACKAGE = "pkg-orch"

#: The design's 350-student class — the same uniform fixture shape TC-GRADE-20 pins.
_SUBMISSIONS = tuple(f"S{i:03d}" for i in range(1, 351))

#: `NFR-GRADE-03` / `PERF-07` / `CT-GRADE-17`: grading plus rollup under 30 s.
BUDGET_S = 30.0

#: The request-path sample: every 14th submission — 25 recomputes spread across
#: the class, a realistic consumer burst, deterministic so a failure reproduces.
_RECOMPUTE_SAMPLE = _SUBMISSIONS[::14]


def _seed_scored_run(store):
    """The 350-student run, every submission fully scored under a windowless policy.
    Untimed: fixture production, not the measured quantity (see the module docstring)."""
    require(GRADE_MODULE, "open_grade", issue="#101")
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


def _current_figures(cohort):
    """The current revision's figures keyed by submission, read from the ledger."""
    return {
        row["submission_id"]: (row["grade"], row["total"])
        for row in grade_rows(cohort) if row["is_current"]
    }


def test_tc_grade_c17_grading_and_rollup_at_the_stated_load_under_budget(
    tmp_data_dir, network_guard
):
    """`TC-GRADE-C17` (`CT-GRADE-17`, rung 3) — the threshold at the stated load:
    grading plus rollup for the 350-student class under the plan's 30 s, and the
    zero asserted EXACTLY — the guard's attempt log is empty, not merely unchecked."""
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort = _seed_scored_run(store)
        svc = require(GRADE_MODULE, "open_grade", issue="#101")(store)

        start = time.perf_counter()
        report = svc.compute_all(run_id)
        rollup = svc.rollup(run_id)
        elapsed = time.perf_counter() - start

        # The measured pass did the stated load: every submission of the
        # 350-student class got its grade, and the pass says so itself.
        assert report.computed == 350, (
            f"the graded pass reports computed={report.computed!r}, expected 350 — "
            "the budget's input is the full class, and a smaller n measures "
            "nothing (CT-GRADE-17: 350 submissions)"
        )
        rows = grade_rows(cohort)
        assert len(rows) == 350 and all(row["is_current"] for row in rows), (
            f"the ledger holds {len(rows)} rows after the pass — one revision per "
            "submission of the 350-student class (fixture drift)"
        )
        assert rollup is not None, (
            "the rollup returned nothing — it is the second half of the measured "
            "pair (CT-GRADE-17)"
        )

        assert elapsed < BUDGET_S, (
            f"grading + rollup took {elapsed:.2f}s over 350 submissions, over the "
            f"{BUDGET_S:.0f}s budget — at the design's scale grading must never be "
            "the wait the school feels. Loosening the bound in this case is "
            "RISK-33; calibrate the environment instead (CT-GRADE-17)."
        )
        # The zero, EXACT: the consumer's right is credible because nothing called
        # out — the guard's own attempt log is the check, and it is empty.
        assert network_guard.attempts == [], (
            f"{len(network_guard.attempts)} connection attempt(s) in a grading "
            "pass — the budget's zero-model-call claim failed (CT-GRADE-17)"
        )
        network_guard.assert_no_network()
    finally:
        store.close()


def test_tc_grade_c17_a_recompute_on_a_request_path_keeps_the_budget(
    tmp_data_dir, network_guard
):
    """`TC-GRADE-C17`'s recompute limb (`CT-GRADE-17`, rung 3) — consumers may
    recompute on demand: 25 request-path `compute_one` calls sampled across the
    350-student class ride the same measured window, each returning the batch
    pass's own figures for that submission, and the window INCLUDING the
    recomputes stays under the budget. A right that blew the budget, or returned
    different figures from the batch arithmetic, would not be a right."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort = _seed_scored_run(store)
        svc = require(GRADE_MODULE, "open_grade", issue="#101")(store)

        start = time.perf_counter()
        report = svc.compute_all(run_id)
        rollup = svc.rollup(run_id)
        batch_figures = _current_figures(cohort)
        recomputed = [
            (sid, svc.compute_one(run_id, sid)) for sid in _RECOMPUTE_SAMPLE
        ]
        elapsed = time.perf_counter() - start

        # Non-vacuousness: the window is the stated load, and the right was
        # actually exercised over real requests.
        assert report.computed == 350, (
            f"the graded pass reports computed={report.computed!r}, expected 350 — "
            "the budget's input is the full class (CT-GRADE-17)"
        )
        assert rollup is not None, "the rollup returned nothing (CT-GRADE-17)"
        assert len(recomputed) == 25, (
            f"{len(recomputed)} recomputes ran, expected 25 — the request-path "
            "burst the clause measures (fixture drift)"
        )

        # The right is real: every on-demand recompute returns the batch pass's
        # OWN figures for that submission — the same arithmetic on the request
        # path, not a different or deferred answer.
        for sid, grade in recomputed:
            expected = batch_figures.get(sid)
            assert expected is not None, (
                f"fixture bug: no batch figures for {sid!r} (CT-GRADE-17)"
            )
            assert (grade.grade, grade.total) == expected, (
                f"the on-demand recompute of {sid!r} returned "
                f"({grade.grade!r}, {grade.total!r}) against the batch pass's "
                f"{expected!r} — the recompute must be the same arithmetic the "
                "batch ran, or the consumer's right is a different grade "
                "(CT-GRADE-17's recompute right)"
            )

        # The budget holds WITH the recomputes riding the window — the right is
        # affordable at the stated load.
        assert elapsed < BUDGET_S, (
            f"pass + rollup + 25 request-path recomputes took {elapsed:.2f}s over "
            f"350 submissions, over the {BUDGET_S:.0f}s budget — recomputing on "
            "demand must not be the wait the school feels. Loosening the bound "
            "here is RISK-33; calibrate the environment instead (CT-GRADE-17)"
        )
        # The zero, still exact: the recomputes made no call either.
        assert network_guard.attempts == [], (
            f"{len(network_guard.attempts)} connection attempt(s) across the pass "
            "and the request-path recomputes — the zero holds on the recompute "
            "path too, or the consumer's right is not local (CT-GRADE-17)"
        )
        network_guard.assert_no_network()
    finally:
        store.close()