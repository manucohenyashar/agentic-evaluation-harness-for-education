"""`TS-88` (issue #382) — `TC-GRADE-25`: grading run A reads only run A's scores
(`FR-GRADE-18`, `CT-GRADE-20`).

Gap-fix test plan §5 (P0, rung 3, two-run isolation + static):

    F-DEV-PIPE-TWO-RUN: run A bands `(1,1,1)`, run B `(3,3,3)` on the same pairs;
    `compute_all(A)`; then B completes; `compute_all(A)` again; `rollup_findings(A)`. Expected:
    A's totals are identical before and after B lands; A's findings contain no B-derived item; a
    source scan shows every `criterion_score` query in `grade.py` has a `run_id` predicate.

**The world, disclosed.** F-DEV-PIPE-TWO-RUN is the composed pipeline's fixture (`run_to_completion`,
#364), which does not exist yet. The property this case owns is M-GRADE's read, not the pipeline's
production of the rows, so both runs' `criterion_score` rows are written directly in #359's
run-scoped shape — the `tests/support/grade_vocabulary.py` stand-in precedent — over a real package
with a grade policy and two real runs of one cohort. Run A's three criteria sit at low bands, run B's
at high bands; every B row is also marked `ungradeable_by_panel`, so a leaked read would change A's
totals **and** raise a breaker finding for A.

**Written ahead of implementation: yes** — keyed on #359, which rebuilds `criterion_score` onto the
run key and scopes every `grade.py` read. The static arm is separate so its red names the unscoped
queries.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.orch import Orchestrator
from aeh.pkg import GradePolicy, PackageCatalog
from aeh.store import open_store
from tests.support.conf_builders import edge_cfg, edge_panel
from tests.support.impl import GRADE_MODULE, NotImplementedYet, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run
from tests.support.run_scoped import run_scoped_migration

pytestmark = pytest.mark.integration

ISSUE = "#359"
REPO_ROOT = Path(__file__).resolve().parents[3]
SUBMISSIONS = ("S1", "S2", "S3")
CRITERIA = ("C1", "C2", "C3")

#: (band, points) per run: A low, B high.
A_SCORE = ("B1", 1.0)
B_SCORE = ("B3", 6.0)


def _write_scores(store, run_id, band, points, *, state="final", routing="auto"):
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        for submission in SUBMISSIONS:
            for criterion in CRITERIA:
                tx.execute(
                    "INSERT INTO criterion_score (run_id, submission_id, criterion_id, band, "
                    "modal_band, band_spread, points, judge_count, agreement, routing, state) "
                    "VALUES (:r, :s, :c, :b, :b, 0, :p, 3, 1.0, :ro, :st)",
                    r=run_id, s=submission, c=criterion, b=band, p=points, ro=routing, st=state,
                )


def _current_grades(store, run_id):
    return {
        row["submission_id"]: (row["total"], row["grade"], row["criteria_total"],
                               row["criteria_auto"], row["score_low"], row["score_high"])
        for row in store.cohort(ORCH_COHORT_ID).query(
            "SELECT * FROM submission_grade WHERE run_id = :r AND is_current = 1", r=run_id)
    }


def test_tc_grade_25_recomputing_run_a_after_run_b_lands_returns_a_unchanged(tmp_data_dir):
    """`TC-GRADE-25` — A's totals identical before and after B's scores land; A's rollup carries
    no B-derived finding."""
    open_grade, rollup_findings = require(GRADE_MODULE, "open_grade", "rollup_findings",
                                          issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        _orch, run_a, version = seed_run(
            store, submissions=SUBMISSIONS,
            criteria=tuple({"criterion_id": c, "kind": "open", "scoring_model": "atomic"}
                           for c in CRITERIA),
        )
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        catalog.set_grade_policy(version, GradePolicy(combination="weighted_sum"))
        run_b = Orchestrator(store).create_run(
            ORCH_COHORT_ID, version,
            resolve_run_config(edge_cfg(panel=edge_panel(3)),
                               CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic")),
        )

        if run_scoped_migration() is None:
            raise NotImplementedYet(
                f"criterion_score is not run-scoped yet — no agg_run_scoped_score migration "
                f"(blocked on {ISSUE})"
            )
        _write_scores(store, run_a, *A_SCORE)
        service = open_grade(store)
        service.compute_all(run_a)
        before = _current_grades(store, run_a)
        assert set(before) == set(SUBMISSIONS), f"precondition: A graded {sorted(before)}"

        _write_scores(store, run_b, *B_SCORE, state="ungradeable_by_panel", routing="reviewed")
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=run_b)

        service.compute_all(run_a)
        after = _current_grades(store, run_a)
        assert after == before, (
            f"run A's grades moved after run B's scores landed:\nbefore={before}\nafter={after}"
        )
        findings = tuple(rollup_findings(run_a, store))
        assert findings == (), (
            f"run A has no breaker marks or exhausted budget of its own, yet its rollup carries "
            f"{findings} — run B's ungradeable_by_panel rows leaked"
        )
    finally:
        store.close()


def _unscoped_criterion_score_queries(source: str) -> list[str]:
    tree = ast.parse(source)
    offending = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = " ".join(node.value.split())
            upper = text.upper()
            touches_scores = any(
                shape in upper for shape in
                ("FROM CRITERION_SCORE", "JOIN CRITERION_SCORE", "UPDATE CRITERION_SCORE")
            )
            if touches_scores and "RUN_ID" not in upper:
                offending.append(text[:120])
    return offending


def test_tc_grade_25_static_every_criterion_score_query_in_grade_has_a_run_predicate():
    """`TC-GRADE-25`, static arm — no `criterion_score` read in `grade.py` without `run_id`."""
    source = (REPO_ROOT / "src" / "aeh" / "grade.py").read_text(encoding="utf-8")
    offending = _unscoped_criterion_score_queries(source)
    assert source.count("criterion_score") > 0
    assert offending == [], (
        "criterion_score queries in grade.py without a run_id predicate (CT-AGG-20):\n  "
        + "\n  ".join(offending)
    )
