"""The whole-grade sample, served (FR-CONSOLE-93, CT-REVIEW-11; #869).

`GET /api/v1/results/whole-grade-sample?run_id=…` serves `ReviewService.whole_grade_sample(run_id)`
as the students would receive it. M-REVIEW chooses *which* students — 10 to 15 whose every line
the system accepted on its own (no reviewed criterion, so the sample measures the system and not
the review) — and each drawn student is then served from the same stored sources as the student
read: name, total, grade letter (only when the test declares a boundary table), per-question
points with the level of each line, and the narrative. Fewer than the range are drawn, and the
document says so, when too few grades were accepted on their own.

The service is seeded per run, so every read of the sample, and the answer to it, is the same
draw: the students the teacher confirms are the ones they were shown.

`whole-grade confirm` and `whole-grade skip` each record one `audit_record` row through M-REVIEW
and write no label: the sample is a check, never evidence (FR-REVIEW-14).
"""

from __future__ import annotations

import hashlib
from typing import Any

#: CT-REVIEW-11's population, in the teacher's words (FR-CONSOLE-93), verbatim.
POPULATION_NOTE = (
    "drawn from the answers the system accepted on its own, not the ones you reviewed"
)

#: What each action answers, in the teacher's words.
CONFIRMED_REPLY = "Recorded: these look like grades you would have given."
SKIPPED_REPLY = (
    "Skipped. Nobody has read a whole paper's result end to end; the grades are delivered "
    "either way."
)


def _seed(run_id: str) -> int:
    """The run's draw seed: stable across requests and processes, different per run."""
    return int.from_bytes(hashlib.sha256(f"whole-grade:{run_id}".encode()).digest()[:8], "big")


def sample_service(app: Any, run_id: str) -> Any:
    """M-REVIEW over the console's own store for this run, seeded for the whole-grade draw, or
    None when there is no store to read (the write-audit double)."""
    keys = app._cohort_keys()
    if not keys:
        return None
    from aeh.review import review_service_over

    try:
        catalog = app._run_catalog(run_id)
    except Exception:  # noqa: BLE001 — an unreadable package keeps the default scale
        catalog = None
    try:
        return review_service_over(app._store, cohort_ids=list(keys), run_id=run_id,
                                   catalog=catalog, actor="teacher", seed=_seed(run_id))
    except Exception:  # noqa: BLE001 — a run the service cannot open has no sample
        return None


def drawn_submissions(app: Any, run_id: str) -> tuple[Any, tuple[str, ...]]:
    """The service and the drawn submissions, in draw order (empty when nothing can be drawn)."""
    service = sample_service(app, run_id)
    if service is None:
        return None, ()
    return service, tuple(str(grade.submission_id)
                          for grade in service.whole_grade_sample(run_id))


def _short_sample_note(drawn: int) -> str | None:
    """The sentence a sample below the range carries (FR-CONSOLE-93)."""
    from aeh.review import WHOLE_GRADE_SAMPLE_RANGE

    low, high = WHOLE_GRADE_SAMPLE_RANGE
    if drawn >= low:
        return None
    if drawn == 0:
        return ("No student's grade was accepted by the system on its own, so there is no "
                "whole-grade sample for this test.")
    one = drawn == 1
    return (f"Only {drawn} student{'' if one else 's'}' grade{' was' if one else 's were'} "
            f"accepted by the system on its own, so the sample has {drawn} instead of "
            f"{low} to {high}.")


def _student(detail: dict[str, Any], letters: bool) -> dict[str, Any]:
    """One drawn student as they would receive the result: each question with its points and
    the level of each of its lines, the total, the grade (with a boundary table only) and the
    narrative."""
    lines: dict[str, list[dict[str, Any]]] = {}
    for line in detail.get("criteria") or []:
        lines.setdefault(str(line.get("question_id")), []).append({
            "criterion_id": line["criterion_id"],
            "label": line["label"],
            "level": line["criterion_band"],
        })
    student = {
        "submission_id": detail["submission_id"],
        "student_ref": detail.get("student_ref"),
        "full_name": detail.get("full_name"),
        "total": detail.get("total"),
        "total_points": detail.get("total_points"),
        "total_max": detail.get("total_max"),
        "questions": [
            {**question, "lines": lines.get(str(question["question_id"]), [])}
            for question in detail.get("questions") or []
        ],
        "narrative": detail.get("narrative") or [],
    }
    if letters:
        student["grade"] = detail.get("grade")
    return student


def whole_grade_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The run's whole-grade sample document. Refuses a read that names no run (a 400)."""
    from .grade_ranges import has_boundary_table
    from .screen_reads import _run_row_of, student_detail_read

    run_row = _run_row_of(console, app, query)
    if run_row is None:
        raise ValueError("the whole-grade sample names no run")
    run_id = str(run_row["run_id"])
    _service, drawn = drawn_submissions(app, run_id)
    letters = has_boundary_table(app, run_row)
    students = [
        _student(student_detail_read(console, app, {"run_id": run_id, "submission_id": sub}),
                 letters)
        for sub in drawn
    ]
    return {
        "run_id": run_id,
        "population_note": POPULATION_NOTE,
        "drawn_count": len(students),
        "short_sample_note": _short_sample_note(len(students)),
        "students": students,
    }


def whole_grade_effect(app: Any, action: str, params: dict[str, Any]
                       ) -> tuple[tuple[Any, ...], str, bool, bool]:
    """`whole-grade confirm` / `whole-grade skip`: one audit row through M-REVIEW, no label.
    Returns (rows written, detail, dispatched, refused)."""
    decision = "confirmed" if action == "whole-grade confirm" else "skipped"
    run_id = str(params.get("run_id") or "")
    if not run_id:
        return (), "The answer names no test run, so nothing was recorded.", False, True
    service, drawn = drawn_submissions(app, run_id)
    if service is None:
        return ((), "This test's grades could not be opened, so nothing was recorded.",
                False, True)
    if not drawn:
        return ((), "There is no whole-grade sample for this test, so nothing was recorded.",
                False, True)
    try:
        audit_record_id, wrote = service.record_whole_grade_check(run_id, decision, drawn)
    except Exception:  # noqa: BLE001 — a refusal is the honest outcome
        return (), "Your answer could not be recorded; nothing was written.", False, True
    if not wrote:
        # A repeat (double-click, back-navigation): the answer stands as first recorded.
        return (), "Your answer was already recorded; nothing changed.", False, False
    reply = CONFIRMED_REPLY if decision == "confirmed" else SKIPPED_REPLY
    return (audit_record_id,), reply, True, False
