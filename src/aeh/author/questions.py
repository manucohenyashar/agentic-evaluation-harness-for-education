"""The draft's missing pieces, asked as plain questions (FR-AUTHOR-31/32, CT-AUTHOR-27).

A gap's engineering `reason` stays on the record for the audit trail; what the teacher
meets is derived here, from the item id and the draft as it stands *now*: a `question`
(one plain sentence ending in `?`), an `answer_hint` (the form of the answer, in words)
and an `answer_kind` — `text`, `whole_number`, or `yes_no` — with integer
`answer_min`/`answer_max` limits (characters for `text`, the value for `whole_number`).

Everything is a pure function of `(item id, spec)`, never stored: the test's total (the
`<max>` of every grade question) moves when a question's points are answered, so a field
frozen at draft time would go stale (TC-AUTHOR-47). The same derivation feeds the draft
read and the server-side answer check, so the hint and the check always agree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

#: The answer kinds a teacher field may carry.
TEXT = "text"
WHOLE_NUMBER = "whole_number"
YES_NO = "yes_no"

#: The approver's name, in characters (FR-AUTHOR-32).
APPROVER_MAX_CHARS = 80
#: A question's points, as the teacher may state them (FR-AUTHOR-32).
POINTS_MIN, POINTS_MAX = 1, 100

#: The two-grade table a bare passing score builds (FR-AUTHOR-32, Q2).
PASS_GRADE = "pass"
LOWEST_GRADE = "not yet"

#: Grade names that are, by their own words, the bottom of a table.
_FAILING_NAMES = frozenset({"not yet", "fail", "failed", "u", "ungraded"})

_SENTINEL_PREFIX = "<<PLACEHOLDER:"
_WHOLE = re.compile(r"^\d+$")


@dataclass(frozen=True)
class GapQuestion:
    """The teacher's side of one gap: what is asked, the form of the answer, and its limits.
    `waiting_on` names the gaps that must be answered first (a grade question waits for a
    missing question's points, since the test's total is not known until then)."""

    question: str
    answer_hint: str
    answer_kind: str
    answer_min: int | None = None
    answer_max: int | None = None
    waiting_on: tuple[str, ...] = ()

    def as_fields(self) -> dict[str, Any]:
        """The fields the console serves beside the gap."""
        return {
            "question": self.question,
            "answer_hint": self.answer_hint,
            "answer_kind": self.answer_kind,
            "answer_min": self.answer_min,
            "answer_max": self.answer_max,
            "waiting_on": list(self.waiting_on),
        }


# --- the draft's arithmetic -----------------------------------------------------------------------


def _is_sentinel(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(_SENTINEL_PREFIX)


def _questions(spec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = spec.get("question")
    if not isinstance(raw, list):
        return []
    return [block for block in raw if isinstance(block, Mapping)]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def missing_points(spec: Mapping[str, Any]) -> tuple[str, ...]:
    """The `points <qid>` gaps the draft still has: questions stating no points."""
    return tuple(f"points {block.get('id')}" for block in _questions(spec)
                 if _number(block.get("points")) is None)


def paper_total(spec: Mapping[str, Any]) -> int | None:
    """The test's total — the sum of its questions' points — or `None` while any question's
    points are missing (or the draft has no questions)."""
    blocks = _questions(spec)
    if not blocks or missing_points(spec):
        return None
    return int(sum(_number(block.get("points")) or 0 for block in blocks))


def grades_low_to_high(grades: Mapping[str, Any]) -> list[str]:
    """The grade names, lowest first. Documents usually list grades top-down (A, B, … not
    yet), so that is the default reading. The stated floors override it: two or more read
    the direction off their order; a single stated 0 marks its grade as the lowest; a
    single stated positive floor at one end of the table is not the lowest grade."""
    names = [str(name) for name in grades]
    known = [(index, floor) for index, name in enumerate(names)
             if (floor := _number(grades.get(name))) is not None]
    ascending = False
    if len(known) >= 2:
        ascending = known[0][1] < known[-1][1]
    elif len(known) == 1 and len(names) > 1:
        index, floor = known[0]
        ascending = index == 0 if floor == 0 else index == len(names) - 1
    elif not known and len(names) > 1:
        # Nothing stated: a failing grade's own name says which end is the bottom.
        ascending = names[0].strip().lower() in _FAILING_NAMES \
            and names[-1].strip().lower() not in _FAILING_NAMES
    return names if ascending else list(reversed(names))


def lowest_grade(grades: Mapping[str, Any]) -> str | None:
    """The lowest grade's name — the one never asked: its floor is always 0. A table of one
    grade has no lowest-below-the-rest, so `None` (its floor is asked, never filled)."""
    ranked = grades_low_to_high(grades)
    return ranked[0] if len(ranked) >= 2 else None


def _question_label(qid: str | None) -> str:
    """"question 2" for `Q2`; the id itself when it is not of that shape."""
    text = str(qid or "").strip()
    if len(text) > 1 and text[0] in "Qq" and text[1:].isdigit():
        return f"question {text[1:]}"
    return f"question {text}" if text else "this question"


# --- the questions ---------------------------------------------------------------------------------


def gap_question(item_id: str, spec: Mapping[str, Any],
                 owner_qid: str | None = None) -> GapQuestion:
    """The plain question, hint and answer kind for the gap `item_id` in the draft `spec`.
    `owner_qid` names the question a shared field id (`key`, `model_answer`) stands in."""
    item_id = str(item_id).strip()
    head, _sep, rest = item_id.partition(" ")
    if item_id == "approved_by":
        return GapQuestion(
            question="Who is approving this test? Type your name.",
            answer_hint=f"Your name, from 1 to {APPROVER_MAX_CHARS} characters.",
            answer_kind=TEXT, answer_min=1, answer_max=APPROVER_MAX_CHARS)
    if item_id == "grades":
        return _passing_score_question(spec)
    if head == "grades" and rest:
        return _grade_floor_question(rest, spec)
    if head == "points" and rest:
        label = _question_label(rest)
        return GapQuestion(
            question=f"How many points is {label} worth?",
            answer_hint=f"A whole number from {POINTS_MIN} to {POINTS_MAX}.",
            answer_kind=WHOLE_NUMBER, answer_min=POINTS_MIN, answer_max=POINTS_MAX)
    qid = rest or owner_qid
    label = _question_label(qid)
    if head == "type":
        return GapQuestion(
            question=f"Is {label} multiple choice?",
            answer_hint="Yes or no.",
            answer_kind=YES_NO)
    if head == "options":
        return _text_question(
            f"What are the answer choices for {label}?",
            "Each choice as its letter and its words, separated by semicolons, for "
            "example: A: a complete loop; B: a broken loop.")
    if head == "text":
        return _text_question(f"What does {label} say?",
                              "The question's words, as printed on the paper.")
    if head == "key":
        return _text_question(
            f"Which choice is the correct answer to {label}?",
            "The letter of the correct choice, for example C. Separate several letters "
            "with commas.")
    if head == "model_answer":
        return _text_question(f"What is the expected answer to {label}?",
                              "The answer you would give full marks to, in your own words.")
    if head == "criterion":
        return _text_question(
            f"How should {label} be marked?",
            "Each score level as its name, what the work looks like and its points, worst "
            "first, separated by semicolons, for example: absent: no evidence (0 points); "
            "present: the evidence is there (2 points).")
    return _text_question(f"What should go in this part of {label}?"
                          if qid else "What should go in this part of the test?",
                          "Type the missing part in your own words.")


def _text_question(question: str, hint: str) -> GapQuestion:
    return GapQuestion(question=question, answer_hint=hint, answer_kind=TEXT, answer_min=1)


def _passing_score_question(spec: Mapping[str, Any]) -> GapQuestion:
    total = paper_total(spec)
    question = "What is the passing score for this test?"
    if total is None:
        return _waiting(question, spec)
    return GapQuestion(
        question=question,
        answer_hint=(f"A whole number from 1 to {total}. A student with this score or more "
                     "passes."),
        answer_kind=WHOLE_NUMBER, answer_min=1, answer_max=total)


def _grade_floor_question(name: str, spec: Mapping[str, Any]) -> GapQuestion:
    question = f"What is the lowest total score that earns '{name}'?"
    total = paper_total(spec)
    if total is None:
        return _waiting(question, spec)
    lo, _below, above = _grade_bounds(name, spec)
    # The range served is the range the check accepts: under a stated grade above, the
    # floor stays below that grade's (FR-UI-36: one definition for format and check).
    hi = min(total, int(above[1]) - 1) if above is not None else total
    return GapQuestion(
        question=question,
        answer_hint=(f"A whole number from {lo} to {hi}. The test is out of {total} "
                     "points."),
        answer_kind=WHOLE_NUMBER, answer_min=lo, answer_max=hi)


def _waiting(question: str, spec: Mapping[str, Any]) -> GapQuestion:
    waiting = missing_points(spec)
    labels = ", ".join(_question_label(item.partition(" ")[2]) for item in waiting)
    return GapQuestion(
        question=question,
        answer_hint=(f"A whole number. First say how many points {labels} "
                     f"{'is' if len(waiting) == 1 else 'are'} worth, so the test's total "
                     "is known."),
        answer_kind=WHOLE_NUMBER, answer_min=1, waiting_on=waiting)


def _grade_bounds(name: str, spec: Mapping[str, Any]) -> \
        tuple[int, tuple[str, float] | None, tuple[str, float] | None]:
    """`(lo, below, above)` for the grade `name`: `lo` is one more than the nearest stated
    floor below it (the lowest grade counts as 0), or 1; `below`/`above` are the nearest
    stated neighbours as `(name, floor)`, for the order refusal."""
    grades = spec.get("grades")
    if not isinstance(grades, Mapping) or name not in grades:
        return 1, None, None
    ranked = grades_low_to_high(grades)
    lowest = lowest_grade(grades)
    position = ranked.index(name)

    def floor_of(grade: str) -> float | None:
        stated = _number(grades.get(grade))
        if stated is None and grade == lowest:
            return 0.0
        return stated

    below = next(((grade, floor) for grade in reversed(ranked[:position])
                  if (floor := floor_of(grade)) is not None), None)
    above = next(((grade, floor) for grade in ranked[position + 1:]
                  if (floor := floor_of(grade)) is not None), None)
    if below is not None:
        lo = int(below[1]) + 1
    else:
        lo = 0 if name == lowest else 1  # a draft that still asks the lowest grade
    return lo, below, above


# --- the answer check (CT-AUTHOR-27) ----------------------------------------------------------------


def check_gap_answer(item_id: str, raw: Any, spec: Mapping[str, Any],
                     owner_qid: str | None = None) -> str | None:
    """The server's check on one answer: `None` when it fits the gap's kind and range, or
    the sentence the teacher is refused with — the gap's own `answer_hint`, or, for a grade
    floor that breaks the table's order, the order sentence (FR-AUTHOR-32)."""
    asked = gap_question(item_id, spec, owner_qid)
    text = "" if raw is None else str(raw).strip()
    if asked.waiting_on:
        return asked.answer_hint
    if asked.answer_kind == TEXT:
        if not text or (asked.answer_max is not None and len(text) > asked.answer_max):
            return asked.answer_hint
        return None
    if asked.answer_kind == YES_NO:
        # The review walk's own type words stay accepted (the terminal walk and older
        # scripted answers speak them); the teacher is offered yes or no.
        accepted = ("yes", "no", "mcq", "open", "mixed")
        return None if text.lower().strip('"') in accepted else asked.answer_hint
    if not _WHOLE.match(text):
        return asked.answer_hint
    value = int(text)
    head, _sep, name = str(item_id).strip().partition(" ")
    if head == "grades" and name:
        return _check_grade_floor(name, value, spec, asked)
    if asked.answer_min is not None and value < asked.answer_min:
        return asked.answer_hint
    if asked.answer_max is not None and value > asked.answer_max:
        return asked.answer_hint
    return None


def _check_grade_floor(name: str, value: int, spec: Mapping[str, Any],
                       asked: GapQuestion) -> str | None:
    """A grade floor: outside 1..total is refused with the hint; inside it, a floor that does
    not rise strictly above the grade below (or stay under the grade above) is refused with
    the order sentence."""
    total = paper_total(spec)
    lo, below, above = _grade_bounds(name, spec)
    if value < min(lo, 1) or (total is not None and value > total):
        return asked.answer_hint
    hi = asked.answer_max
    if below is not None and value < lo:
        below_name, below_floor = below
        return (f"'{name}' must need more points than '{below_name}' "
                f"({_shown(below_floor)}). Please enter a number from {lo} to {hi}.")
    if above is not None and hi is not None and value > hi:
        above_name, above_floor = above
        return (f"'{name}' must need fewer points than '{above_name}' "
                f"({_shown(above_floor)}). Please enter a number from {lo} to {hi}.")
    return None


def _shown(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def two_grade_table(passing: int) -> list[tuple[str, int]]:
    """The table a bare passing score builds: `pass` = the answer, `not yet` = 0."""
    return [(PASS_GRADE, passing), (LOWEST_GRADE, 0)]
