"""TC-AGG-29, TC-AGG-30 (#819): review, grading and stats read the Jev-final route.

Traces: CT-AGG-24, FR-AGG-20 (pairs M-REVIEW→M-AGG, M-GRADE→M-AGG, M-STATS→M-AGG). Source:
`docs/design/console_clarity_test_plan.md` §3.2 (story T6).

| Case | Asserted |
|---|---|
| TC-AGG-29 | Over the Jev-final seed (`tests/support/clarity_world.py`), the review queue built by `aeh.review.open_review` holds exactly C1b, C2 and C3 for each student. The Jev-final C1a is absent. C1b's stored reason is `one_grader_unsure`. Differential control: the same seed aggregated with the knob off puts C1a back in the queue |
| TC-AGG-30 | A seed variant where every line is an accepted decision: `compute_all` grades each student with all four criteria `auto`, none provisional, and no boundary risk. Its knob-off twin has all four provisional and the boundary at risk |

**Plan findings (not asserted; reported in the PR).**
- TC-AGG-30's "M-STATS low-confidence counts" names a surface that does not exist. `aeh.stats`
  never reads `criterion_score`, and no low-confidence count is computed over cells.
- `export_gate_outcome` (`aeh.pkg.exchange`) is the provenance gate's last recorded outcome for
  a package version. It never reads a cell, so "does not block on Jev-final cells" holds
  vacuously, and asserting it would test nothing.
- A grade's `state` (`provisional`/`final`) is set by run completion or the review window
  (FR-GRADE-10), not by cell routes. "Final with no provisional flag" is therefore asserted
  through the grade's coverage counters (`criteria_provisional`, `boundary_at_risk`), the
  fields the cell route actually drives.

**Rung.** Rung 3: a real store, the shipped ENG7 package build, `create_run`, the shipped
`aggregate`/`write_score`, and the real review and grading services reading the stored rows.

Markers. `integration`. Written against shipped code (#806), so not `writtenahead`.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.clarity_world import (STUDENTS, score_rows, seed_jev_final)

pytestmark = pytest.mark.integration

ALL_DECISION = {line: "decision_accepted" for line in ("C1a", "C1b", "C2", "C3")}


def _queue_cells(data_dir, seed) -> dict[str, set[str]]:
    """student -> the criterion ids the review queue shows for that student."""
    from aeh.review import open_review

    service = open_review(data_dir, run_id=seed.run_id)
    queue = service.build_queue(seed.run_id, 600, record=False)
    by_submission = {sub: name for name, sub in seed.submissions.items()}
    shown: dict[str, set[str]] = {name: set() for name in STUDENTS}
    for entry in queue.shown:
        for item in getattr(entry, "members", None) or (entry,):
            shown[by_submission[item.submission_id]].add(item.criterion_id)
    assert queue.residual_provisional == 0, "precondition: the budget shows every flagged item"
    return shown


def _seeded(data_dir, **kwargs):
    store = open_store(data_dir)
    try:
        seed = seed_jev_final(store, **kwargs)
        rows = score_rows(store, seed)
    finally:
        store.close()
    return seed, rows


def test_tc_agg_29_review_does_not_requeue_a_jev_final_cell(tmp_path) -> None:
    from aeh.agg import stored_not_final_reason

    data_dir = tmp_path / "on"
    seed, rows = _seeded(data_dir)
    assert {(rows[(s, "C1a")]["state"], rows[(s, "C1a")]["routing"]) for s in STUDENTS} == {
        ("final", "auto")}, "precondition: C1a is Jev-final"
    shown = _queue_cells(data_dir, seed)
    assert shown == {name: {"C1b", "C2", "C3"} for name in STUDENTS}, shown
    for name in STUDENTS:
        assert stored_not_final_reason(rows[(name, "C1b")]) == "one_grader_unsure"

    # The control: with FR-AGG-20 off, the same cell is a provisional single verdict and is queued.
    off_dir = tmp_path / "off"
    off_seed, _ = _seeded(off_dir, jev_final_on_accept=False)
    assert _queue_cells(off_dir, off_seed) == {name: {"C1a", "C1b", "C2", "C3"} for name in STUDENTS}


def _grades(data_dir, **kwargs) -> dict[str, dict]:
    from aeh.grade import open_grade

    store = open_store(data_dir)
    try:
        seed = seed_jev_final(store, kinds=ALL_DECISION, **kwargs)
        report = open_grade(store).compute_all(seed.run_id)
        assert report.computed == len(STUDENTS)
        out = {}
        for name, sub in seed.submissions.items():
            (row,) = store.cohort(seed.cohort_id).query(
                "SELECT * FROM submission_grade WHERE submission_id = :s AND superseded_at IS NULL",
                s=sub)
            out[name] = dict(row)
        return out
    finally:
        store.close()


def test_tc_agg_30_an_all_jev_final_student_is_graded_with_nothing_provisional(tmp_path) -> None:
    on = _grades(tmp_path / "on", jev_final_on_accept=True)
    off = _grades(tmp_path / "off", jev_final_on_accept=False)
    fields = ("criteria_total", "criteria_auto", "criteria_provisional", "criteria_missing",
              "boundary_at_risk")
    for name in STUDENTS:
        assert tuple(on[name][f] for f in fields) == (4, 4, 0, 0, 0), (name, on[name])
        # The knob-off twin: the same verdicts are four provisional single-judge cells.
        assert tuple(off[name][f] for f in fields) == (4, 0, 4, 0, 1), (name, off[name])
        assert (on[name]["grade"], on[name]["total"]) == (off[name]["grade"], off[name]["total"])
