"""`TC-CONSOLE-97` and `TC-CONSOLE-101` (issue #826; FR-CONSOLE-76, CT-CONSOLE-54, FR-UI-33) —
the results read's roll-up of rubric lines into questions over the Jev-final seed, and
"Approve all grades" settling the questions as well as the grades.

Console clarity test plan §3.7, story T10.

| Case | Expected |
|---|---|
| 97 | ENG7 student A (C1a 1, C1b 1, C2 2 of 3, C3 2 of 3): `questions` = Q1 2/2, Q2 2/3, Q3 2/3; `total_points` 6, `total_max` 8, `grade` "pass". Student B (C1a 1, C1b 0): Q1 1/2. The C1 evidence checklist is counted once, through its aspects. **Regression entry** (the teacher's report: results by rubric line, no question totals) |
| 101 | a student with two `provisional_unreviewed` questions; the batch is finalized: every question `final`, no `not_final_reason`, `not_final_questions` 0. With an open review window the finalize is the deferral and the questions stay not final |

**The seed.** `tests/support/clarity_world.py:seed_jev_final` always seeds two students (A and
B). For 101 the variant kinds make C1a and C1b accepted decision verdicts (Jev-final, so Q1 is
final) and C2 and C3 single LLM verdicts, so each student has exactly two
`provisional_unreviewed` questions (Q2, Q3) — the case's "one student", held for both. Grades
are computed by M-GRADE's own `compute_all` (no `submission_grade` row, no student in the read).

Rung 3: a real store, the shipped ENG7 build, the shipped aggregator and grading service, the
console's own actions and read.

Markers. `integration`. Not written ahead: #811 is merged.
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.console import build_console
from aeh.console.screen_reads import results_screen_read
from aeh.store import open_store
from tests.support.clarity_world import (ENG7_SPEC, ENG7_TOTAL_MAX, EXPECTED_ROLLUP, STUDENT_A, STUDENT_B,
                                         STUDENTS, score_rows, seed_jev_final)

pytestmark = pytest.mark.integration

#: Two questions per student left `provisional_unreviewed` (Q2, Q3); Q1 Jev-final.
TWO_PROVISIONAL = {"C1a": "decision_accepted", "C1b": "decision_accepted",
                   "C2": "llm_single", "C3": "llm_single"}


@pytest.fixture
def seeded(tmp_path):
    def make(*, review_window_hours: int | None = None, **kwargs: Any):
        from aeh.grade import open_grade

        store = open_store(tmp_path / "data")
        opened.append(store)
        if review_window_hours is not None:
            # The window is part of the published version (FR-PKG-19; a published version is
            # immutable, FR-PKG-01): the shipped ENG7 spec, built with the window declared.
            from aeh.pipeline.packages import build_package, read_package_spec

            spec = dict(read_package_spec(ENG7_SPEC), review_window_hours=review_window_hours)
            built = build_package(store, spec)
            kwargs["package"] = (built.package_id, built.package_version)
        seed = seed_jev_final(store, **kwargs)
        report = open_grade(store).compute_all(seed.run_id)
        assert report.computed == len(STUDENTS), report
        return store, seed, build_console(store=store)

    opened: list[Any] = []
    try:
        yield make
    finally:
        for store in opened:
            store.close()


def _students(console: Any, seed: Any) -> dict[str, dict[str, Any]]:
    doc = results_screen_read(None, console, {"run_id": seed.run_id})
    by_name = {str(s["full_name"]): s for s in doc["students"]}
    assert sorted(by_name) == sorted(STUDENTS), "the read does not carry both seeded students"
    for student in by_name.values():
        assert [q["question_id"] for q in student["questions"]] == ["Q1", "Q2", "Q3"], student
    return by_name


def test_tc_console_97_criteria_roll_up_into_questions_with_total_and_grade(seeded) -> None:
    store, seed, console = seeded()
    students = _students(console, seed)
    for name, (questions, total, grade) in EXPECTED_ROLLUP.items():
        student = students[name]
        got = [(q["question_id"], q["points_awarded"], q["points_max"])
               for q in student["questions"]]
        assert got == [(q, float(a), float(m)) for q, a, m in questions], (name, got)
        assert student["total_points"] == float(total), (name, student["total_points"])
        assert student["total_max"] == float(ENG7_TOTAL_MAX), (name, student["total_max"])
        assert student["grade"] == grade, (name, student["grade"])
    # The plan's literal values, independently of the seed module's table.
    a = {q["question_id"]: (q["points_awarded"], q["points_max"])
         for q in students[STUDENT_A]["questions"]}
    assert a == {"Q1": (2.0, 2.0), "Q2": (2.0, 3.0), "Q3": (2.0, 3.0)}
    assert (students[STUDENT_A]["total_points"], students[STUDENT_A]["total_max"],
            students[STUDENT_A]["grade"]) == (6.0, 8.0, "pass")
    q1_b = students[STUDENT_B]["questions"][0]
    assert (q1_b["points_awarded"], q1_b["points_max"]) == (1.0, 2.0)
    # The composite is counted once: Q1 is its two aspects' stored points, nothing more.
    rows = score_rows(store, seed)
    assert all((name, "C1") not in rows for name in STUDENTS), (
        "precondition: the C1 evidence checklist has no score row of its own (FR-PKG-25)")
    for name in STUDENTS:
        aspects = float(rows[(name, "C1a")]["points"]) + float(rows[(name, "C1b")]["points"])
        assert students[name]["questions"][0]["points_awarded"] == aspects, name


def _not_final(student: dict[str, Any]) -> list[tuple[str, str, Any]]:
    return [(q["question_id"], q["state"], q["not_final_reason"])
            for q in student["questions"] if q["state"] != "final"]


def test_tc_console_101_approve_all_settles_every_question(seeded) -> None:
    _store, seed, console = seeded(kinds=TWO_PROVISIONAL)
    before = results_screen_read(None, console, {"run_id": seed.run_id})
    for student in _students(console, seed).values():
        assert _not_final(student) == [("Q2", "not_final", "one_grader_unsure"),
                                       ("Q3", "not_final", "one_grader_unsure")], student
    assert before["not_final_questions"] == 4, "precondition: two open questions per student"

    outcome = console.perform("finalize batch", run_id=seed.run_id, actor="Dana Teacher")
    assert outcome.dispatched, outcome.detail

    after = results_screen_read(None, console, {"run_id": seed.run_id})
    for name, student in _students(console, seed).items():
        assert student["state"] == "final", (name, student["state"])
        for question in student["questions"]:
            assert question["state"] == "final", (name, question)
            assert question["not_final_reason"] is None, (name, question)
    assert after["not_final_questions"] == 0


def test_tc_console_101_an_open_review_window_defers_and_questions_stay_open(seeded) -> None:
    _store, seed, console = seeded(kinds=TWO_PROVISIONAL, review_window_hours=48)

    outcome = console.perform("finalize batch", run_id=seed.run_id, actor="Dana Teacher")
    assert not outcome.dispatched, f"the finalize was not deferred: {outcome.detail}"
    assert "review window" in outcome.detail, outcome.detail

    after = results_screen_read(None, console, {"run_id": seed.run_id})
    for name, student in _students(console, seed).items():
        assert student["state"] != "final", (name, student["state"])
        assert [q for q, state, _reason in _not_final(student)] == ["Q2", "Q3"], (name, student)
    assert after["not_final_questions"] == 4
