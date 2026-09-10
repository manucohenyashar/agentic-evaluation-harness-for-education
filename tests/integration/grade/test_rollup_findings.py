"""`TC-GRADE-16` — the rollup surfaces the criteria the system could not apply, naming
the affected student counts.

Test plan §5.14; `FR-GRADE-16` ("The module shall surface as rollup findings the
criteria the escalation circuit breaker marked `ungradeable_by_panel` and the criteria
that exhausted the review budget, naming the affected student counts"); Integration / 3;
exact value; P1.

**Written ahead of implementation** (test plan §8.2). The shipped rollup carries no
findings, and `review_queue` has no budget/residual surface (`store.py`'s Tier D DDL:
`review_queue` is a queue, `criterion_stats` carries no breaker or budget figure).
`#104` — *"Class rollup, criterion statistics, rubric findings and export"*, whose
third acceptance criterion is this clause — lands the findings, so this file carries
`@pytest.mark.writtenahead` and its registry entry names the symbol below.

**The invented-and-disclosed key** (the `evaluate_alerts` / `export_grade_artifacts`
precedent): `aeh.grade:rollup_findings`. The name is absent from both design documents
(checked: zero occurrences); the assumed signature — `rollup_findings(run_id, store) ->
sequence of findings` — reconciles at #104's landing like every other reserved name.

**The two findings, exact** (the case's oracle: *"Both surface as rollup findings
naming the affected student counts"*):

- the breaker finding: one criterion (`C1`) whose criterion-score rows carry state
  `ungradeable_by_panel` — the escalation circuit breaker's mark (`FR-ORCH-13`,
  `CT-ORCH-16`); the finding names `C1` and the count of students it touched (2 here);
- the budget finding: one criterion (`C2`) whose review queue rows exhausted the review
  budget — the residual `FR-REVIEW-04` leaves behind; the finding names `C2` and its
  student count (1 here). (`M-REVIEW`'s budget residual is its own surface; the finding
  reads it, it does not compute it — the fixture writes the exhausted rows disclosedly.)

**Disclosed stand-ins** (`grade_vocabulary.py`, header): `write_criterion_scores`
standing in for `M-AGG` — the breaker-marked rows are written by a direct INSERT
disclosed in the helper, because the stand-in's routing ladder deliberately refuses to
seed `ungradeable_by_panel` (a settled row only the breaker may mark, CT-AGG-07); the
review-budget rows stand in for `M-REVIEW`'s residual surface, which is landing in
parallel (#109).

**Isolation:** rung 2 — real store, real package lineage, real grade ledger.
"""

from __future__ import annotations

import pytest

from aeh.pkg import GradePolicy, PackageCatalog
from aeh.store import open_store
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.impl import GRADE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [
    pytest.mark.integration,
    # Red by design until #104 lands the rollup findings this case pins
    # (WRITTEN_AHEAD_BLOCKERS: "#104 rollup findings" -> `aeh.grade:rollup_findings`).
    pytest.mark.writtenahead,
]

ISSUE = "#104"

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C3", "kind": "open", "scoring_model": "atomic"},
)

_SUBMISSIONS = ("S-F1", "S-F2", "S-F3", "S-F4")


def _seed_run_with_findings(store):
    """A run where C1 is breaker-marked for two students (S-F1, S-F2 — every submission
    gets the mark, the count is of AFFECTED students, not marks) and C2's review budget
    is exhausted for one (S-F3); C3 scores clean for everyone, so the findings cannot
    be satisfied by naming every criterion."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    _orchestrator, run_id, version = seed_run(
        store, submissions=_SUBMISSIONS, criteria=_CRITERIA
    )
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    catalog.set_grade_policy(version, GradePolicy(combination="weighted_sum"))
    cohort = store.cohort(ORCH_COHORT_ID)

    # C3 settled for all four (the ordinary stand-in path).
    write_criterion_scores(
        cohort, [(sid, "C3", "B2", 7.0, "auto") for sid in _SUBMISSIONS]
    )
    # C1 breaker-marked for two, and settled normally for the other two: the finding's
    # count is the affected half, not the class.
    write_criterion_scores(
        cohort,
        [("S-F3", "C1", "B2", 7.0, "auto"), ("S-F4", "C1", "B2", 7.0, "auto")],
    )
    with cohort.transaction() as tx:
        for submission_id in ("S-F1", "S-F2"):
            tx.execute(
                "INSERT OR REPLACE INTO criterion_score "
                "(submission_id, criterion_id, band, points, routing, state) "
                "VALUES (:s, 'C1', 'B2', 5.0, 'reviewed', 'ungradeable_by_panel')",
                s=submission_id,
            )
        # C2's review budget exhausted for S-F3: the queue row stands in for the
        # exhausted-residual surface M-REVIEW owns (#109, disclosed above). The shipped
        # review_queue is (queue_id, submission_id, criterion_id, reason) — no status
        # column — so the exhaustion rides the reason text.
        tx.execute(
            "INSERT INTO review_queue (queue_id, submission_id, criterion_id, reason) "
            "VALUES (:q, :s, :c, 'review budget exhausted')",
            q=f"q-{run_id}-C2-S-F3",
            s="S-F3",
            c="C2",
        )
    return run_id


def test_tc_grade_16_both_findings_name_their_affected_student_counts(tmp_data_dir):
    """`TC-GRADE-16` — the breaker finding names `C1` with 2 affected students; the
    budget finding names `C2` with 1; nothing else reads as a finding. The count is
    the exact-value oracle: a finding that names a criterion but not its reach would
    leave the teacher guessing how many students it swallowed."""
    rollup_findings = require(GRADE_MODULE, "rollup_findings", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        run_id = _seed_run_with_findings(store)

        findings = rollup_findings(run_id, store)
        assert findings, (
            "the run's rollup carries no findings — the breaker mark and the "
            "exhausted budget must surface to the teacher, not stay inside the "
            "ledger (FR-GRADE-16)"
        )

        by_criterion = {}
        for finding in findings:
            criterion_id = getattr(finding, "criterion_id", None)
            assert criterion_id is not None, (
                f"a finding without a criterion id: {finding!r} — the finding names "
                "the criterion it concerns"
            )
            by_criterion[criterion_id] = finding

        assert set(by_criterion) == {"C1", "C2"}, (
            f"the findings name {sorted(by_criterion)} — exactly the breaker-marked "
            "and the budget-exhausted criteria; C3 (settled for everyone) must not "
            "appear, or every finding would drown in ordinary rows"
        )

        breaker = by_criterion["C1"]
        assert int(getattr(breaker, "student_count", -1)) == 2, (
            f"the breaker finding counts {getattr(breaker, 'student_count', None)!r} "
            "students, expected 2 (S-F1 and S-F2 carry the ungradeable_by_panel mark; "
            "S-F3 and S-F4 settled normally) — the exact-value oracle"
        )
        assert "ungradeable_by_panel" in str(getattr(breaker, "reason", "")), (
            f"the breaker finding does not say what it is ({getattr(breaker, 'reason', None)!r}) "
            "— the panel-refusal must be readable from the finding, not inferred from "
            "a bare criterion name"
        )
        budget = by_criterion["C2"]
        assert int(getattr(budget, "student_count", -1)) == 1, (
            f"the budget finding counts {getattr(budget, 'student_count', None)!r} "
            "students, expected 1 (S-F3's exhausted queue row) — the exact-value "
            "oracle"
        )
    finally:
        store.close()