"""`TC-CONSOLE-99` and `TC-CONSOLE-100` (issue #826, FR-CONSOLE-76) — the ENG7 grade boundaries
the results read's `grade` comes from, and the per-question class statistics.

Console clarity test plan §3.7, story T10.

| Case | Expected |
|---|---|
| 99 | ENG7 totals 0, 5, 6 and 8 grade "not yet", "not yet", "pass", "pass" |
| 100 | 4 students on Q2 at 3, 2, 2 and 0: `mean_points` 1.75, `full_marks` 1, `zero_marks` 1, `graded` 4, `points_max` 3; a question with no graded answer: `graded` 0 and a null mean (not 0) |

**99's oracle.** FR-CONSOLE-76's `grade` is the stored submission grade M-GRADE resolved (the
read does not look it up on the points sum). So the boundary arm is M-GRADE's own
`resolve_grade` over the boundaries the shipped ENG7 spec declares — read from the file, not
restated here — applied to the total the console's roll-up (`student_questions` → `totals`)
gives for a student whose lines sum to that total.

**100's label-formatter arm is not implemented here.** FR-UI-31's label ("1.8 / 3 (58%)", the
six rounding rows of the plan's table) is an SPA formatter owned by M-UI (#822, open, and not in
#826's `Depends on:`); no formatter exists yet and the repo has no TypeScript unit runner. The
label is asserted through the SPA by TC-UI-31. Disclosed on the PR.

Rung 0: pure functions and the shipped spec file; no store.

Markers. None (fast tier). Not written ahead: #811 is merged.
"""

from __future__ import annotations

import tomllib

import pytest

from aeh.console.question_results import question_stats, student_questions, totals
from aeh.grade.policy import resolve_grade
from tests.support.clarity_world import ENG7_SPEC

#: ENG7's shape as the read passes it: Q1 is the C1 checklist's two aspects (FR-PKG-25).
QUESTIONS = [{"question_id": "Q1", "label": "Q1", "points_max": 2},
             {"question_id": "Q2", "label": "Q2", "points_max": 3},
             {"question_id": "Q3", "label": "Q3", "points_max": 3}]
LINE_QUESTION = {"C1a": "Q1", "C1b": "Q1", "C2": "Q2", "C3": "Q3"}

#: A student's line points for each total the case names.
LINES_FOR_TOTAL = {
    0: {"C1a": 0, "C1b": 0, "C2": 0, "C3": 0},
    5: {"C1a": 1, "C1b": 0, "C2": 2, "C3": 2},
    6: {"C1a": 1, "C1b": 1, "C2": 2, "C3": 2},
    8: {"C1a": 1, "C1b": 1, "C2": 3, "C3": 3},
}


def _eng7_boundaries() -> list[tuple[str, float]]:
    with ENG7_SPEC.open("rb") as handle:
        grades = tomllib.load(handle)["grades"]
    return [(str(name), float(floor)) for name, floor in grades.items()]


def _cells(points: dict[str, int]) -> dict[str, dict]:
    return {line: {"points": float(p), "state": "final", "routing": "auto",
                   "not_final_reason": None} for line, p in points.items()}


@pytest.mark.parametrize(("total", "expected"), [
    (0, "not yet"), (5, "not yet"), (6, "pass"), (8, "pass")])
def test_tc_console_99_eng7_grade_boundaries(total: int, expected: str) -> None:
    questions = student_questions(QUESTIONS, LINE_QUESTION, _cells(LINES_FOR_TOTAL[total]),
                                  grade_final=True)
    total_points, total_max = totals(questions)
    assert (total_points, total_max) == (float(total), 8.0)
    assert resolve_grade(total_points, _eng7_boundaries()) == expected


def _student(q2: float | None) -> dict:
    return {"questions": [
        {"question_id": "Q1", "points_awarded": 1.0},
        {"question_id": "Q2", "points_awarded": q2},
        # Q3 is ungraded for everyone: the "no graded answer" arm.
        {"question_id": "Q3", "points_awarded": None},
    ]}


def test_tc_console_100_question_stats_over_four_students() -> None:
    stats = {s["question_id"]: s for s in question_stats(
        QUESTIONS, [_student(3), _student(2), _student(2), _student(0)])}
    q2 = stats["Q2"]
    assert (q2["mean_points"], q2["full_marks"], q2["zero_marks"], q2["graded"],
            q2["points_max"]) == (1.75, 1, 1, 4, 3.0), q2
    assert [s["question_id"] for s in question_stats(QUESTIONS, [])] == ["Q1", "Q2", "Q3"]


def test_tc_console_100_a_question_with_no_graded_answer_has_a_null_mean() -> None:
    stats = {s["question_id"]: s for s in question_stats(
        QUESTIONS, [_student(3), _student(None)])}
    assert stats["Q3"]["graded"] == 0
    assert stats["Q3"]["mean_points"] is None, "an ungraded question's mean must be null, not 0"
    assert (stats["Q3"]["full_marks"], stats["Q3"]["zero_marks"]) == (0, 0)
    # A student with no figure on Q2 is not counted as a zero.
    assert (stats["Q2"]["graded"], stats["Q2"]["mean_points"]) == (1, 3.0)
