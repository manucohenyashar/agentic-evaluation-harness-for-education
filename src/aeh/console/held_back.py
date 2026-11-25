"""Drawn marks held back from the teacher's view while the blind draw is open (FR-CONSOLE-89,
CT-CONSOLE-56; r2 D6, ADR-62; #882).

While a run's draw is `open`, every teacher-facing read replaces, for each drawn (submission,
criterion), what the system said about that line — its level, points, reason, cited quotes,
graders' verdicts and feedback — with `hidden_until_blind = true`. For a student with any drawn
line, the student's total, grade letter and range are replaced the same way, because *total −
visible lines* would otherwise give the drawn line's points away. A question holding a drawn
line hides its points for that student, for the same reason. Records about a drawn cell (an AI
call, a review-queue item) are left out of the lists that carry them.

Class-level figures (the per-question distribution, counts, the class mean) are computed before
this pass and exclude nothing. Exports are not teacher-facing reads in this sense and carry
every total (R60): they never pass through here.

The pass is applied to the read's finished document, so the reads keep computing exactly what
they computed before; it reads only the draw (M-REVIEW's), never a score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .blind_actions import DRAW_OPEN, settle_draw
from .html import _row_get

#: The marker a held-back field's owner carries (FR-CONSOLE-89).
HIDDEN_KEY = "hidden_until_blind"

#: FR-UI-42's sentence for a held-back line, on the pages the console renders itself.
HELD_BACK_SENTENCE = "Hidden until you mark your sample or skip it."

#: What a line says that comes from grading: replaced on a drawn line.
LINE_KEYS: frozenset[str] = frozenset({
    "band", "criterion_band", "stored_band", "proposed_band", "system_band", "new_band",
    "from_band", "to_band", "score_level", "points", "awarded_points", "points_awarded",
    "new_points", "reason", "state_reason", "rationale", "flag", "routing", "cited", "quotes",
    "cited_quotes", "evidence", "graders", "panel", "verdicts", "feedback", "narrative",
    "why_flagged", "text", "not_final_reason", "confidence",
    # The whole-grade sample's line level (FR-CONSOLE-93): a drawn line's level, held back
    # like its band (#878).
    "level",
})

#: A student's figures that *total − visible lines* would reveal a drawn line through.
TOTAL_KEYS: frozenset[str] = frozenset({
    "total", "grade", "grade_letter", "total_points", "range", "total_range", "grade_range",
    "plausible_range", "boundary_risk",
    # FR-CONSOLE-94 (#869): M-GRADE's stored range and the grade letters at its ends.
    "boundary_at_risk", "score_low", "score_high", "grade_low", "grade_high",
})

#: A question's points (and its feedback), hidden for a student when the question holds a
#: drawn line.
QUESTION_KEYS: frozenset[str] = frozenset({
    "points_awarded", "points", "not_final_reason", "text", "narrative", "feedback",
})


@dataclass
class DrawnLines:
    """One run's open draw: the drawn cells, the students they belong to (by submission and by
    roster ref), and the questions those cells sit in per submission."""

    run_id: str
    cells: frozenset[tuple[str, str]]
    refs: dict[str, str] = field(default_factory=dict)  # student_ref -> submission_id
    line_question: dict[str, str] = field(default_factory=dict)  # criterion -> question

    @property
    def submissions(self) -> frozenset[str]:
        return frozenset(submission for submission, _criterion in self.cells)

    def drawn_questions(self, submission_id: str) -> set[str]:
        return {self.line_question[criterion] for sub, criterion in self.cells
                if sub == submission_id and criterion in self.line_question}


def drawn_lines(app: Any, run_id: str) -> DrawnLines | None:
    """The run's drawn lines while its draw is open, else None. Reading the draw settles a
    lapsed window (and promotes it); it never opens a draw."""
    if not run_id:
        return None
    try:
        service, state = settle_draw(app, run_id)
    except Exception:  # noqa: BLE001 — an unreadable draw holds nothing back
        return None
    if service is None or state != DRAW_OPEN:
        return None
    try:
        cells = frozenset((str(item.submission_id), str(item.criterion_id))
                          for item in service.blind_draw_items(run_id))
        row = app._run_row(run_id)
    except Exception:  # noqa: BLE001 — an unreadable draw holds nothing back
        return None
    if not cells:
        return None
    refs: dict[str, str] = {}
    if row is not None:
        try:
            refs = {str(r["student_ref"]): str(r["submission_id"])
                    for r in app._store.cohort(str(row["cohort_id"])).query(
                        "SELECT submission_id, student_ref FROM submission")}
        except Exception:  # noqa: BLE001 — a ref-keyed document then matches by submission
            refs = {}
    return DrawnLines(run_id=run_id, cells=cells, refs=refs)


def drawn_cells_of_submission(app: Any, submission_id: str) -> set[tuple[str, str]]:
    """The drawn cells of one submission across the runs that graded it, while each run's
    draw is open (the legacy student page names a submission, not a run)."""
    if not submission_id or getattr(app._store, "data_dir", None) is None:
        return set()
    try:
        rows = app._read_cohort_files(
            "SELECT DISTINCT run_id FROM criterion_score WHERE submission_id = :submission_id",
            [], submission_id=submission_id)
    except Exception:  # noqa: BLE001 — a submission with no scores holds nothing back
        return set()
    cells: set[tuple[str, str]] = set()
    for row in rows:
        lines = drawn_lines(app, str(_row_get(row, "run_id")))
        if lines is not None:
            cells |= {cell for cell in lines.cells if cell[0] == submission_id}
    return cells


def _run_ids(payload: Any, found: set[str]) -> set[str]:
    if isinstance(payload, dict):
        value = payload.get("run_id")
        if isinstance(value, str) and value:
            found.add(value)
        for child in payload.values():
            _run_ids(child, found)
    elif isinstance(payload, list):
        for child in payload:
            _run_ids(child, found)
    return found


def _line_questions(payload: Any, found: dict[str, str]) -> dict[str, str]:
    """criterion -> question, from the document itself (every line row names its question)."""
    if isinstance(payload, dict):
        criterion, question = payload.get("criterion_id"), payload.get("question_id")
        if isinstance(criterion, str) and isinstance(question, str) and question:
            found.setdefault(criterion, question)
        for child in payload.values():
            _line_questions(child, found)
    elif isinstance(payload, list):
        for child in payload:
            _line_questions(child, found)
    return found


def _blank(value: Any) -> Any:
    if isinstance(value, list):
        return []
    if isinstance(value, dict):
        return {}
    return None


def _hide(node: dict[str, Any], keys: Iterable[str]) -> None:
    """Blank each of `keys` the node carries and mark it; a node carrying none is untouched."""
    present = [key for key in keys if key in node]
    for key in present:
        node[key] = _blank(node[key])
    if present:
        node[HIDDEN_KEY] = True


class _Pass:
    """One document's pass over the drawn lines of every run it names."""

    def __init__(self, draws: dict[str, DrawnLines]) -> None:
        self.draws = draws
        self.dropped = 0

    def _submission(self, node: dict[str, Any], run: DrawnLines | None,
                    inherited: str | None) -> str | None:
        if run is None:
            return None
        submission = node.get("submission_id")
        if isinstance(submission, str) and submission:
            return submission
        ref = node.get("student_ref")
        if isinstance(ref, str) and ref in run.refs:
            return run.refs[ref]
        return inherited

    def is_drawn_cell(self, node: Any, run: DrawnLines | None, submission: str | None) -> bool:
        if run is None or not isinstance(node, dict):
            return False
        criterion = node.get("criterion_id")
        sub = self._submission(node, run, submission)
        return isinstance(criterion, str) and (sub, criterion) in run.cells

    def walk(self, node: Any, run: DrawnLines | None, submission: str | None) -> None:
        if isinstance(node, list):
            for child in node:
                self.walk(child, run, submission)
            return
        if not isinstance(node, dict):
            return
        named = node.get("run_id")
        if isinstance(named, str) and named:
            run = self.draws.get(named)
            submission = None
        if run is not None:
            own = self._submission(node, run, None)
            submission = self._submission(node, run, submission)
            if submission in run.submissions:
                criterion = node.get("criterion_id")
                question = node.get("question_id")
                if isinstance(criterion, str):
                    if (submission, criterion) in run.cells:
                        _hide(node, LINE_KEYS)
                elif isinstance(question, str) and question in run.drawn_questions(submission):
                    _hide(node, QUESTION_KEYS)
                elif "text" in node and (
                        not isinstance(question, str)
                        or question not in set(run.line_question.values())):
                    # Feedback on no question the lines name (the whole paper's, `__test__`)
                    # speaks for every line, drawn ones too.
                    _hide(node, ("text", "narrative", "feedback"))
                if own == submission:
                    _hide(node, TOTAL_KEYS)
        for child in node.values():
            self.walk(child, run, submission)


#: The lists whose items are records about one cell: a drawn cell's record is left out.
_CELL_RECORD_LISTS: tuple[str, ...] = ("shown", "items", "entries")


def _is_drawn_record(item: Any, run: DrawnLines | None, draws: dict[str, DrawnLines]) -> bool:
    """A record about a drawn cell, or about a drawn student's whole paper (a feedback call
    names the submission and no criterion): the record names its own run, else its list's."""
    if not isinstance(item, dict):
        return False
    named = item.get("run_id")
    if isinstance(named, str) and named:
        run = draws.get(named)
    if run is None:
        return False
    submission = item.get("submission_id")
    if not (isinstance(submission, str) and submission):
        ref = item.get("student_ref")
        submission = run.refs.get(ref) if isinstance(ref, str) else None
    if submission not in run.submissions:
        return False
    criterion = item.get("criterion_id")
    return not criterion or (submission, criterion) in run.cells


def _drop_drawn_records(node: Any, pass_: _Pass, run: DrawnLines | None) -> None:
    if isinstance(node, list):
        for child in node:
            _drop_drawn_records(child, pass_, run)
        return
    if not isinstance(node, dict):
        return
    named = node.get("run_id")
    if isinstance(named, str) and named:
        run = pass_.draws.get(named)
    for key in _CELL_RECORD_LISTS:
        items = node.get(key)
        if isinstance(items, list):
            kept = [item for item in items if not _is_drawn_record(item, run, pass_.draws)]
            pass_.dropped += len(items) - len(kept)
            node[key] = kept
    for child in node.values():
        _drop_drawn_records(child, pass_, run)


def hold_back(app: Any, payload: Any, *, run_id: str | None = None,
              drop_records: bool = False) -> Any:
    """Apply FR-CONSOLE-89 to a read's document, in place, and return it. `run_id` is the run
    the request named (a document that names no run of its own is held to it); every run the
    document names is checked for an open draw. `drop_records` leaves a drawn cell's records
    out of the cell-record lists (the review queue, the AI-call log)."""
    if not isinstance(payload, (dict, list)):
        return payload
    names = _run_ids(payload, set())
    if run_id:
        names.add(run_id)
    draws = {name: lines for name in sorted(names)
             if (lines := drawn_lines(app, name)) is not None}
    if not draws:
        return payload
    questions = _line_questions(payload, {})
    for lines in draws.values():
        lines.line_question = dict(questions)
    pass_ = _Pass(draws)
    root_run = draws.get(run_id or "")
    if drop_records:
        _drop_drawn_records(payload, pass_, root_run)
        if pass_.dropped and isinstance(payload, dict) and isinstance(payload.get("total"), int):
            payload["total"] = max(0, payload["total"] - pass_.dropped)
    pass_.walk(payload, root_run, None)
    return payload
