"""`TC-CONSOLE-98` (issue #826, CT-CONSOLE-54) — the by-question roll-up, as a property over
random band assignments on the ENG7 rubric.

Console clarity test plan §3.7 and §4.3, story T10.

**Property.** For every generated student: Σ `questions.points_awarded == total_points`;
0 ≤ `points_awarded` ≤ `points_max` per question; and Q1 == C1a + C1b (the C1 evidence
checklist counted once, through its aspects — never with a figure of its own added).

**The rubric.** The question shape (`_question_shape`: questions in paper order with their
points, each scored line's question, composites excluded) and each line's declared levels
(`_declared_scales`) are the console's own reads over the shipped ENG7 spec built once into a
module-scoped tmp store — so a shape that listed the composite, or a level table the roll-up
disagreed with, fails here. The generated part is pure: a band per scored line, each cell's
state and routing, and whether the student's grade is final, fed to `student_questions` and
`totals` exactly as the results read feeds them. The build is a rung-3 fixture; the property
itself is rung 0.

Hypothesis, 200 examples, `deadline=None` (the suite's FUZZ convention).

Markers. `property`. Not written ahead: #811 is merged.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aeh.console import build_console
from aeh.console.question_results import student_questions, totals
from aeh.console.screen_reads import _declared_scales, _question_shape
from aeh.store import open_store
from tests.support.clarity_world import ENG7_QUESTIONS, build_eng7_package

pytestmark = pytest.mark.property

EXAMPLES = 200


def _eng7_rubric(directory: Any) -> tuple[list[dict], dict[str, str], dict[str, list]]:
    store = open_store(directory)
    try:
        package_id, version = build_eng7_package(store)
        app = build_console(store=store)
        run_row = {"package_id": package_id, "package_version_id": version}
        scales = _declared_scales(app, run_row)
        questions, line_question = _question_shape(app, run_row, scales)
        return questions, line_question, scales
    finally:
        store.close()


@pytest.fixture(scope="module")
def eng7(tmp_path_factory):
    questions, line_question, scales = _eng7_rubric(tmp_path_factory.mktemp("eng7") / "data")
    # Preconditions: the shape the property ranges over is ENG7's.
    assert [(q["question_id"], q["points_max"]) for q in questions] == [
        (q, float(points)) for q, (_lines, points) in ENG7_QUESTIONS.items()], questions
    assert line_question == {"C1a": "Q1", "C1b": "Q1", "C2": "Q2", "C3": "Q3"}, line_question
    for line in line_question:
        assert scales.get(line), f"no declared levels for {line}: {scales}"
    return questions, line_question, scales


_CELL_STATES = st.sampled_from([
    ("final", "auto"), ("final", "reviewed"), ("provisional_unreviewed", "auto"),
    ("provisional_unreviewed", "queued"), ("final", "queued")])


def test_tc_console_98_rollup_property_over_the_eng7_rubric(eng7) -> None:
    questions, line_question, scales = eng7
    levels = {line: [float(p) for _name, p in scales[line] if p is not None]
              for line in line_question}

    @settings(max_examples=EXAMPLES, deadline=None)
    @given(
        bands=st.fixed_dictionaries({line: st.sampled_from(levels[line])
                                     for line in sorted(line_question)}),
        states=st.fixed_dictionaries({line: _CELL_STATES for line in sorted(line_question)}),
        grade_final=st.booleans(),
    )
    def check(bands: dict[str, float], states: dict[str, tuple[str, str]],
              grade_final: bool) -> None:
        cells = {line: {"points": bands[line], "state": states[line][0],
                        "routing": states[line][1], "not_final_reason": None}
                 for line in line_question}
        rolled = student_questions(questions, line_question, cells, grade_final=grade_final)
        total_points, total_max = totals(rolled)
        assert [q["question_id"] for q in rolled] == [q["question_id"] for q in questions]
        assert total_points == sum(q["points_awarded"] for q in rolled)
        assert total_points == sum(bands.values())
        assert total_max == 8.0
        for question in rolled:
            assert 0 <= question["points_awarded"] <= question["points_max"], question
        assert rolled[0]["points_awarded"] == bands["C1a"] + bands["C1b"]

    check()
