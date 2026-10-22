"""Results by question (FR-CONSOLE-76, CT-CONSOLE-54, FR-UI-33): the pure roll-up the results
read serves beside its per-criterion rows.

A question's points are the sum of the stored points of its scored rubric lines. A composite
(an evidence checklist, FR-PKG-24) has no score row of its own (FR-PKG-25): its points ARE its
aspects' rows, so summing a question's score rows counts the composite exactly once and never
adds its aspects again.

**The finalize question the design left open (FR-UI-33).** `finalize_batch` settles the
`submission_grade` rows only; M-GRADE never writes criterion scores (CT-GRADE-14), so after
"Approve all grades" the per-line `criterion_score` rows keep the state the aggregation gave
them. A question's displayed state is therefore derived here: it is `final` when the student's
grade is final, or when every one of its lines is settled (a reviewed line is — the review
decision writes `routing='reviewed', state='final'`). A question is `final` exactly when it
carries no `not_final_reason`.

Every function here is pure: the read passes in what it took from the store.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

#: A question's displayed states: settled, waiting for the teacher, or not graded at all.
QUESTION_FINAL = "final"
QUESTION_NOT_FINAL = "not_final"
QUESTION_NOT_GRADED = "not_graded"

#: FR-AGG-20's closed set of not-final reason codes (M-AGG's `NOT_FINAL_REASONS`), spelled
#: here because the console's import edges are frozen (TC-CONSOLE-36).
NOT_FINAL_REASON_CODES: tuple[str, ...] = (
    "one_grader_unsure", "graders_disagree", "evidence_not_found", "quote_not_verified",
    "more_graders_unavailable", "graders_refused",
)
#: Stored state reasons that predate FR-AGG-20, and the code each reads as (M-AGG's own map).
_LEGACY_STATE_REASONS = {"even_panel_after_quarantine": "more_graders_unavailable"}


def is_settled(state: Any, routing: Any) -> bool:
    """A cell is settled when it is `final` and not waiting in the teacher's queue."""
    return state == "final" and routing != "queued"


def cell_not_final_reason(state: Any, routing: Any, *, judge_count: Any, caps_fired: Any,
                          state_reason: Any = None) -> str | None:
    """FR-AGG-20's code for why a stored cell is not settled; `None` for a settled one.

    A mirror of `aeh.agg.not_final_reason_for` (which the console may not import,
    TC-CONSOLE-36), with the same precedence: a recorded reason, the breaker, the evidence
    and citation caps, then one grader or a panel that disagreed."""
    if is_settled(state, routing):
        return None
    if state_reason in NOT_FINAL_REASON_CODES:
        return str(state_reason)
    if state_reason in _LEGACY_STATE_REASONS:
        return _LEGACY_STATE_REASONS[state_reason]
    if state == "ungradeable_by_panel":
        return "graders_refused"
    caps = caps_fired
    if isinstance(caps, str):
        try:
            caps = json.loads(caps)
        except ValueError:
            caps = ()
    caps = tuple(caps or ())
    if "evidence_present" in caps:
        return "evidence_not_found"
    if "spans_verified" in caps:
        return "quote_not_verified"
    if judge_count is not None and int(judge_count) == 1:
        return "one_grader_unsure"
    if judge_count is not None and int(judge_count) == 0:
        return None
    return "graders_disagree"


def student_questions(
    questions: Sequence[Mapping[str, Any]],
    line_question: Mapping[str, str],
    cells: Mapping[str, Mapping[str, Any]],
    *,
    grade_final: bool,
) -> list[dict[str, Any]]:
    """One student's `questions`, in paper order.

    `questions` are `{question_id, label, points_max}` in paper order; `line_question` maps
    every scored (non-composite) rubric line to its question; `cells` maps a line to the
    student's cell `{points, state, routing, not_final_reason}` (`points` the effective
    figure — amended if the teacher amended it — or `None` when no figure arrived)."""
    out: list[dict[str, Any]] = []
    for question in questions:
        question_id = str(question["question_id"])
        lines = [line for line, owner in line_question.items() if owner == question_id]
        figures = [cells.get(line, {}).get("points") for line in lines]
        if not lines or any(figure is None for figure in figures):
            # A line with no figure leaves the question ungraded: a partial sum would read as
            # a low mark rather than a missing one.
            out.append(_question(question, None, QUESTION_NOT_GRADED, None))
            continue
        awarded = float(sum(float(figure) for figure in figures))
        unsettled = [] if grade_final else [
            line for line in sorted(lines)
            if not is_settled(cells[line].get("state"), cells[line].get("routing"))]
        if not unsettled:
            out.append(_question(question, awarded, QUESTION_FINAL, None))
            continue
        # The first unsettled line's code, in criterion order. A line with no code to name
        # (an unsettled deterministic row) still leaves the question not final.
        reason = next((cells[line].get("not_final_reason") for line in unsettled
                       if cells[line].get("not_final_reason")), None)
        out.append(_question(question, awarded, QUESTION_NOT_FINAL, reason))
    return out


def _question(question: Mapping[str, Any], awarded: float | None, state: str,
              reason: str | None) -> dict[str, Any]:
    return {
        "question_id": str(question["question_id"]),
        "label": str(question["label"]),
        "points_awarded": awarded,
        "points_max": float(question["points_max"]),
        "state": state,
        "not_final_reason": reason,
    }


def totals(questions: Sequence[Mapping[str, Any]]) -> tuple[float | None, float]:
    """`(total_points, total_max)`: the sum of the questions' points, or `None` when any
    question is ungraded (a missing input stays visibly missing), beside the test's maximum."""
    total_max = float(sum(float(q["points_max"]) for q in questions))
    awarded = [q["points_awarded"] for q in questions]
    if not awarded or any(points is None for points in awarded):
        return None, total_max
    return float(sum(float(points) for points in awarded)), total_max


def question_stats(questions: Sequence[Mapping[str, Any]],
                   students: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The run's `question_stats`, in paper order: over the students whose question is graded,
    the mean points, how many got full marks and how many got none. A question no student
    has a graded answer for has `graded` 0 and a null mean — never 0."""
    by_question: dict[str, list[float]] = {str(q["question_id"]): [] for q in questions}
    for student in students:
        for entry in student.get("questions", ()):
            points = entry.get("points_awarded")
            if points is not None and entry["question_id"] in by_question:
                by_question[entry["question_id"]].append(float(points))
    stats = []
    for question in questions:
        question_id = str(question["question_id"])
        points_max = float(question["points_max"])
        marks = by_question[question_id]
        stats.append({
            "question_id": question_id,
            "label": str(question["label"]),
            "points_max": points_max,
            "mean_points": (sum(marks) / len(marks)) if marks else None,
            "full_marks": sum(1 for mark in marks if mark == points_max),
            "zero_marks": sum(1 for mark in marks if mark == 0),
            "graded": len(marks),
        })
    return stats


def not_final_count(students: Iterable[Mapping[str, Any]]) -> int:
    """The answers still waiting for the teacher — the number behind the Results banner
    (FR-UI-33): every student's questions whose state is not final."""
    return sum(1 for student in students for entry in student.get("questions", ())
               if entry.get("state") == QUESTION_NOT_FINAL)


__all__ = [
    "NOT_FINAL_REASON_CODES", "QUESTION_FINAL", "QUESTION_NOT_FINAL", "QUESTION_NOT_GRADED",
    "cell_not_final_reason", "is_settled", "not_final_count", "question_stats",
    "student_questions", "totals",
]
