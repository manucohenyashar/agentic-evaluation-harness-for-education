"""`TC-AUTHOR-44..48` (issue #825, FR-AUTHOR-31, FR-AUTHOR-32, CT-AUTHOR-27; RC-11) — the
draft's missing pieces are plain questions with typed, ranged answers, and the range is
enforced by the check, not only displayed.

Console clarity test plan §3.5, story T9.

| Case | Expected |
|---|---|
| 44 | AF-23 (pass named, no boundary) asks the approver and `grades pass` with the exact questions and the hint "A whole number from 1 to 8. The test is out of 8 points."; AF-22 (no grade table) asks "What is the passing score for this test?" with its hint; "not yet" is never asked (floor 0, filled in); the engineering `reason` stays on the gap and never in a teacher field |
| 45 | `grades pass` (1..8): 1 and 8 accepted; 0, 9, 6.5, "six", "", -1 refused with exactly the gap's hint; the draft file byte-identical after a refusal |
| 46 | A / B / not yet with B = 4: A = 4 refused with the order sentence, A = 5 accepted, the served `lo` is 5 |
| 47 | Q2's points missing: the grade question waits on "How many points is question 2 worth?" (1..100); after 3 the hint reads "from 1 to 8", after 5 "from 1 to 10" |
| 48 | the approver: "" and 81 characters refused, 1 and 80 accepted |

**The draft.** AF-22/AF-23 carry no recorded drafting replies yet (`fixtures/F-AUTHOR/README.md`:
captured from the live ENG7 walk, never fabricated), so the draft here is the shipped
assembler's (`aeh.author.spec.assemble` + `render_draft`) over the ENG7 inventory and rubric
copied from the shipped spec — the drafter's own last, deterministic step, with only the
model's outputs stood in (`tests.support.clarity_world.eng7_assembly`). Answers go through
the shipped review walk (`run_review`) and the shipped structured edit — the doors the
console's answer action drives.

**One definition (the issue's evaluation strategy).** Each refusal is compared against the
gap's own `answer_hint`, and the hint is checked against the gap's own `answer_min`/
`answer_max`, so a hint and a check that drift apart fail here.

**Isolation: rung 1.** **Written ahead of implementation: no** (#809 landed).

Markers. None: the fast tier.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from aeh.author import ReviewAnswer, apply_structured_edit, check_gap_answer, gap_question, \
    run_review
from tests.support.clarity_world import AUTHOR_CORPUS, ENG7_TOTAL_MAX, eng7_assembly, \
    write_eng7_draft

AF22_GRADES: dict[str, float | None] = {}
AF23_GRADES: dict[str, float | None] = {"pass": None, "not yet": None}

APPROVER_Q = "Who is approving this test? Type your name."
PASS_FLOOR_Q = "What is the lowest total score that earns 'pass'?"
PASS_FLOOR_HINT = "A whole number from 1 to 8. The test is out of 8 points."
PASSING_SCORE_Q = "What is the passing score for this test?"
PASSING_SCORE_HINT = "A whole number from 1 to 8. A student with this score or more passes."


def _spec(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _teacher_fields(gap) -> tuple[str, str]:
    return gap.question, gap.answer_hint


# --- TC-AUTHOR-44 ---------------------------------------------------------------------------


def test_tc_author_44_the_fixed_questions_af23_af22_and_never_not_yet() -> None:
    af23 = {gap.item_id: gap for gap in eng7_assembly(AF23_GRADES).gaps}
    assert sorted(af23) == ["approved_by", "grades pass"], (
        f"AF-23 must ask the approver and the pass floor only, asked {sorted(af23)}")
    assert af23["approved_by"].question == APPROVER_Q
    assert af23["grades pass"].question == PASS_FLOOR_Q
    assert af23["grades pass"].answer_hint == PASS_FLOOR_HINT
    assert af23["grades pass"].answer_kind == "whole_number"

    assembly = eng7_assembly(AF23_GRADES)
    assert assembly.spec["grades"]["not yet"] == 0, "not yet's floor is 0, filled in"
    assert not any("not yet" in gap.item_id for gap in assembly.gaps), (
        "'not yet' is the lowest grade: its floor is never asked")

    af22 = {gap.item_id: gap for gap in eng7_assembly(AF22_GRADES).gaps}
    assert sorted(af22) == ["approved_by", "grades"]
    assert af22["grades"].question == PASSING_SCORE_Q
    assert af22["grades"].answer_hint == PASSING_SCORE_HINT

    # The stand-in drafts ask exactly what the fixtures declare (beside the approver).
    for af, asked in (("AF-23", af23), ("AF-22", af22)):
        expected = tomllib.loads(
            (AUTHOR_CORPUS / af / "expected.toml").read_text(encoding="utf-8"))
        assert sorted(asked) == sorted(["approved_by", *expected["placeholders"]]), af

    for gap in [*af23.values(), *af22.values()]:
        assert gap.reason, f"{gap.item_id}: the engineering reason is gone from the record"
        for field in _teacher_fields(gap):
            assert gap.reason not in field, (
                f"{gap.item_id}: the engineering reason is served in a teacher field")
            assert "FR-" not in field and "never invented" not in field, (
                f"{gap.item_id}: {field!r} carries engineering words")


# --- TC-AUTHOR-45 ---------------------------------------------------------------------------


@pytest.mark.parametrize("answer, accepted", [
    ("0", False), ("1", True), ("8", True), ("9", False), ("6.5", False),
    ("six", False), ("", False), ("-1", False),
])
def test_tc_author_45_pass_floor_range_is_enforced_with_exactly_the_hint(
        tmp_path: Path, answer: str, accepted: bool) -> None:
    draft = write_eng7_draft(tmp_path, AF23_GRADES)
    spec = _spec(draft)
    asked = gap_question("grades pass", spec)
    # One definition: the hint states the very limits the check enforces.
    assert (asked.answer_min, asked.answer_max) == (1, ENG7_TOTAL_MAX)
    assert asked.answer_hint == (f"A whole number from {asked.answer_min} to "
                                 f"{asked.answer_max}. The test is out of 8 points.")

    refusal = check_gap_answer("grades pass", answer, spec)
    before = draft.read_bytes()
    run_review(draft, [ReviewAnswer(item_id="grades pass", value=answer)])

    if accepted:
        assert refusal is None, f"{answer!r} is inside 1..8 but was refused: {refusal!r}"
        assert _spec(draft)["grades"]["pass"] == int(answer), (
            f"the accepted {answer!r} did not land in the draft")
    else:
        assert refusal == asked.answer_hint, (
            f"{answer!r} must be refused with exactly the gap's hint, got {refusal!r}")
        assert draft.read_bytes() == before, (
            f"the refused answer {answer!r} changed the draft file")


# --- TC-AUTHOR-46 ---------------------------------------------------------------------------


def test_tc_author_46_floors_must_rise_above_the_grade_below(tmp_path: Path) -> None:
    draft = write_eng7_draft(tmp_path, {"A": None, "B": 4, "not yet": None})
    spec = _spec(draft)
    assert spec["grades"]["not yet"] == 0

    asked = gap_question("grades A", spec)
    assert asked.answer_min == 5, "the floor's lo is derived: one above B's 4"
    assert asked.answer_max == ENG7_TOTAL_MAX
    assert check_gap_answer("grades A", "4", spec) == (
        "'A' must need more points than 'B' (4). Please enter a number from 5 to 8.")
    assert check_gap_answer("grades A", "5", spec) is None

    before = draft.read_bytes()
    run_review(draft, [ReviewAnswer(item_id="grades A", value="4")])
    assert draft.read_bytes() == before, "the out-of-order floor changed the draft"
    run_review(draft, [ReviewAnswer(item_id="grades A", value="5")])
    assert _spec(draft)["grades"]["A"] == 5


# --- TC-AUTHOR-47 ---------------------------------------------------------------------------


def test_tc_author_47_the_grade_question_waits_for_points_and_its_max_follows_them(
        tmp_path: Path) -> None:
    draft = write_eng7_draft(tmp_path, AF23_GRADES, points={"Q2": None})
    spec = _spec(draft)

    waiting = gap_question("grades pass", spec)
    assert waiting.waiting_on == ("points Q2",), "the grade question is offered too early"
    assert check_gap_answer("grades pass", "6", spec) is not None, (
        "a grade floor was accepted before the test's total is known")

    points = gap_question("points Q2", spec)
    assert points.question == "How many points is question 2 worth?"
    assert (points.answer_min, points.answer_max) == (1, 100)
    for value, ok in (("0", False), ("1", True), ("100", True), ("101", False)):
        assert (check_gap_answer("points Q2", value, spec) is None) is ok, value

    for q2, total in ((3, 8), (5, 10)):
        apply_structured_edit(draft, "edit question",
                              params={"item_id": "Q2", "field": "points", "value": q2})
        asked = gap_question("grades pass", _spec(draft))
        assert asked.waiting_on == ()
        assert asked.answer_hint == (
            f"A whole number from 1 to {total}. The test is out of {total} points."), (
            f"after Q2 = {q2} the hint reads {asked.answer_hint!r}")
        assert asked.answer_max == total


# --- TC-AUTHOR-48 ---------------------------------------------------------------------------


@pytest.mark.parametrize("name, accepted", [
    ("", False), ("D" * 81, False), ("D", True), ("D" * 80, True),
], ids=["empty", "81-chars", "1-char", "80-chars"])
def test_tc_author_48_the_approver_name_is_1_to_80_characters(
        tmp_path: Path, name: str, accepted: bool) -> None:
    draft = write_eng7_draft(tmp_path, AF23_GRADES)
    spec = _spec(draft)
    asked = gap_question("approved_by", spec)
    assert (asked.answer_kind, asked.answer_min, asked.answer_max) == ("text", 1, 80)

    refusal = check_gap_answer("approved_by", name, spec)
    before = draft.read_bytes()
    run_review(draft, [ReviewAnswer(item_id="approved_by", value=name)])
    if accepted:
        assert refusal is None
        assert _spec(draft)["approved_by"] == name
    else:
        assert refusal == asked.answer_hint == "Your name, from 1 to 80 characters."
        assert draft.read_bytes() == before
