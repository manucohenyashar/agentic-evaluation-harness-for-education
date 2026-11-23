"""The built review queue, served (FR-CONSOLE-91, CT-CONSOLE-58; #868).

`GET /api/v1/review-queue?run_id=…&budget_minutes=…` answers `ReviewService.build_queue(run_id,
budget_minutes, record=False)` as the teacher reads it: the header numbers exactly as the
service computed them, then the shown entries in the service's own presentation order — groups
first, then items by rank (FR-REVIEW-05). The console ranks nothing: each entry's `rank_score`
is the service's expected value, served so the order can be checked, never re-sorted here.

Each entry carries what the teacher decides with: the student's full name, the question and the
rubric line, the proposed level and each grader's level by name, why it is flagged in words
(FR-REVIEW-03's inputs, never a confidence figure, §10), the feedback sentence for the line,
the quotes the graders cited, the service's time estimate, the line's levels and the score's
`revision` for the stale check (CT-REVIEW-15). A group carries its size, a pattern sentence,
three sample members and the `group_signature` the group action posts back — which records each
member's revision as shown, so an answer changed since is refused by name (FR-CONSOLE-92).

The blind draw's seats and the random arm's cells never reach the build (M-REVIEW holds them
out before counting); the deterministic criteria never reach the queue at all (FR-REVIEW-06).
"""

from __future__ import annotations

import base64
import json
from typing import Any

from aeh.review import REVIEW_DEFAULT_BUDGET_MINUTES

#: FR-CONSOLE-91: the minutes a teacher may give the queue, inclusive.
REVIEW_BUDGET_RANGE: tuple[int, int] = (1, 480)

#: FR-REVIEW-03's ranking inputs in the teacher's words (FR-CONSOLE-91), keyed by M-REVIEW's
#: `FLAG_REASONS` codes.
WHY_FLAGGED_WORDS: dict[str, str] = {
    "panel_disagreement": "panel disagreement",
    "near_grade_boundary": "near a grade boundary",
    "reading_uncertain": "reading uncertain",
    "often_changed": "this line is often changed",
}

#: How many of a group's members are shown side by side (FR-UI-47).
GROUP_SAMPLE_SIZE = 3

#: One cell's grader verdicts, in M-JUDGE's `work_id` order (the student detail's statement).
_CELL_VERDICTS_SQL = (
    "SELECT v.work_id, v.judge_id, v.band, v.cited_spans FROM verdict v "
    "JOIN work_unit w ON w.work_id = v.work_id "
    "WHERE w.run_id = :run_id AND w.submission_id = :submission_id "
    "AND w.criterion_id = :criterion_id ORDER BY v.work_id"
)

#: The run's per-question feedback sentences (M-SYNTH's L1 narratives), with the score-claim
#: flag M-SYNTH wrote beside each (a flagged one is withheld, CT-SYNTH-01/03).
_LINE_NARRATIVES_SQL = (
    "SELECT submission_id, question_id, text, score_claim_flag FROM narrative "
    "WHERE run_id = :run_id AND level = 'l1_question'"
)


def budget_minutes_of(query: Any) -> int:
    """The request's minute budget: `REVIEW_DEFAULT_BUDGET_MINUTES` when absent, else a whole
    number in `REVIEW_BUDGET_RANGE`; anything else is refused with the range named (a 400)."""
    raw = query.get("budget_minutes") if hasattr(query, "get") else None
    if raw is None or str(raw).strip() == "":
        return int(REVIEW_DEFAULT_BUDGET_MINUTES)
    low, high = REVIEW_BUDGET_RANGE
    try:
        value = int(str(raw).strip())
    except ValueError:
        value = None
    if value is None or not low <= value <= high:
        raise ValueError(
            f"The review time must be a whole number of minutes from {low} to {high} "
            f"({low}…{high}); {str(raw).strip()!r} is not."
        )
    return value


def encode_group_signature(group: Any) -> str:
    """The token a group action posts back: the rubric line, the five-part signature
    (CT-REVIEW-20) and each member as shown with its revision. Opaque to the teacher."""
    signature = dict(getattr(group, "signature", {}) or {})
    document = {
        "c": str(group.criterion_id),
        "s": {str(key): signature[key] for key in sorted(signature)},
        "m": [[str(member.submission_id), int(member.version)] for member in group.members],
    }
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_group_signature(token: str) -> dict[str, Any]:
    """The group a token names: `criterion_id`, `signature` and `members` as
    `[(submission_id, revision), …]`. A token this console did not issue is refused."""
    try:
        padded = str(token) + "=" * (-len(str(token)) % 4)
        document = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        return {
            "criterion_id": str(document["c"]),
            "signature": dict(document["s"]),
            "members": [(str(sub), int(rev)) for sub, rev in document["m"]],
        }
    except Exception as exc:  # noqa: BLE001 — any malformed token is the same refusal
        raise ValueError("that group is not one the review queue showed") from exc


def same_signature(group: Any, wanted: dict[str, Any]) -> bool:
    """Whether a built group is the one a decoded token names (its line and signature)."""
    if str(group.criterion_id) != wanted["criterion_id"]:
        return False
    signature = dict(getattr(group, "signature", {}) or {})
    return json.loads(json.dumps(
        {str(key): signature[key] for key in sorted(signature)}, default=str)) == wanted[
        "signature"]


class _RunContext:
    """What every entry of one run's queue is worded with, read once per request."""

    def __init__(self, app: Any, run_row: Any, run_id: str) -> None:
        from .screen_reads import _declared_scales, _grading_point_labels, _roster_names

        self.run_id = run_id
        self.handle = None
        self.names: dict[str, str | None] = {}
        self.refs: dict[str, str] = {}
        self.question_of: dict[str, str] = {}
        self.scales: dict[str, list[tuple[str, Any]]] = {}
        self.narratives: dict[tuple[str, str], str] = {}
        self.graders: dict[str, str] = {}
        if run_row is None:
            return
        self.handle = app._store.cohort(str(run_row["cohort_id"]))
        self.names = _roster_names(self.handle)
        try:
            self.refs = {str(row["submission_id"]): str(row["student_ref"])
                         for row in self.handle.query(
                             "SELECT submission_id, student_ref FROM submission")}
        except Exception:  # noqa: BLE001 — an entry then names its paper alone
            self.refs = {}
        self.question_of = _grading_point_labels(app, run_row)
        self.scales = _declared_scales(app, run_row)
        try:
            for row in self.handle.query(_LINE_NARRATIVES_SQL, run_id=run_id):
                if row["score_claim_flag"]:
                    continue
                self.narratives[(str(row["submission_id"]), str(row["question_id"]))] = str(
                    row["text"] or "")
        except Exception:  # noqa: BLE001 — a ledger without narratives shows none
            self.narratives = {}
        # FR-CONSOLE-89: while the blind draw is open, a question's feedback for a student is
        # hidden when any of that student's drawn lines sits in the question — an entry for
        # another line of the same question must not carry it.
        try:
            from .held_back import drawn_lines

            drawn = drawn_lines(app, run_id)
        except Exception:  # noqa: BLE001 — an unreadable draw holds nothing back
            drawn = None
        if drawn is not None:
            for submission_id, criterion_id in drawn.cells:
                question = self.question_of.get(criterion_id, criterion_id)
                self.narratives.pop((submission_id, question), None)

    def full_name(self, submission_id: str) -> str | None:
        ref = self.refs.get(submission_id)
        return self.names.get(ref) if ref is not None else None

    def grader(self, judge_id: str) -> str:
        label = self.graders.get(judge_id)
        if label is None:
            label = f"Grader {len(self.graders) + 1}"
            self.graders[judge_id] = label
        return label

    def panel_and_quotes(self, submission_id: str, criterion_id: str
                         ) -> tuple[list[dict[str, str]], list[str]]:
        """Each grader's level by name, and the quotes they cited (deduplicated, in order)."""
        panel: list[dict[str, str]] = []
        quotes: list[str] = []
        if self.handle is None:
            return panel, quotes
        try:
            rows = self.handle.query(_CELL_VERDICTS_SQL, run_id=self.run_id,
                                     submission_id=submission_id, criterion_id=criterion_id)
        except Exception:  # noqa: BLE001 — a cell without verdicts shows the proposal alone
            return panel, quotes
        for row in rows:
            panel.append({"grader": self.grader(str(row["judge_id"])), "band": str(row["band"])})
            try:
                spans = json.loads(str(row["cited_spans"] or "[]"))
            except ValueError:
                spans = []
            for span in spans if isinstance(spans, list) else []:
                text = str(span.get("text") or "").strip() if isinstance(span, dict) else ""
                if text and text not in quotes:
                    quotes.append(text)
        return panel, quotes

    def levels(self, item: Any) -> list[str]:
        declared = [name for name, _points in self.scales.get(str(item.criterion_id), [])]
        return declared or [str(band) for band in (item.band_options or ())]


def _item_entry(context: _RunContext, service: Any, item: Any) -> dict[str, Any]:
    submission_id, criterion_id = str(item.submission_id), str(item.criterion_id)
    question = context.question_of.get(criterion_id, criterion_id)
    panel, quotes = context.panel_and_quotes(submission_id, criterion_id)
    narrative = context.narratives.get((submission_id, question)) or item.narrative or None
    return {
        "kind": "item",
        "submission_id": submission_id,
        "criterion_id": criterion_id,
        "student_ref": context.refs.get(submission_id),
        "full_name": context.full_name(submission_id),
        "question_label": question,
        "criterion_label": criterion_id,
        "proposed_band": item.proposed_band,
        "panel": panel,
        "why_flagged": [WHY_FLAGGED_WORDS[code] for code in service.flag_reasons(item)],
        "narrative": narrative,
        "quotes": quotes,
        "est_seconds": float(item.est_seconds),
        "levels": context.levels(item),
        "revision": int(item.version),
        "rank_score": float(item.expected_value),
    }


def _pattern_sentence(group: Any, size: int) -> str:
    """The pattern a group's members share, in words (FR-CONSOLE-91): the five-part signature
    (CT-REVIEW-20) read as the teacher would describe the answers."""
    signature = dict(getattr(group, "signature", {}) or {})
    said = [f"All {size} were marked {group.proposed_band}"]
    said.append("the quoted evidence was found on the paper"
                if signature.get("spans_verified") else
                "the quoted evidence could not be checked on the paper")
    if signature.get("evidence_present") in (0, False):
        said.append("no evidence was found for this line")
    if signature.get("sufficiency_flag"):
        said.append("the evidence may not be enough to judge")
    if signature.get("ocr_overlap_risk"):
        said.append("the handwriting reading is uncertain")
    return "; ".join(said) + "."


def _group_entry(context: _RunContext, service: Any, group: Any) -> dict[str, Any]:
    members = list(group.members)
    criterion_id = str(group.criterion_id)
    question = context.question_of.get(criterion_id, criterion_id)
    reasons: list[str] = []
    for member in members:
        for code in service.flag_reasons(member):
            words = WHY_FLAGGED_WORDS[code]
            if words not in reasons:
                reasons.append(words)
    return {
        "kind": "group",
        "group_signature": encode_group_signature(group),
        "size": len(members),
        "criterion_id": criterion_id,
        "question_label": question,
        "criterion_label": criterion_id,
        "proposed_band": group.proposed_band,
        "pattern": _pattern_sentence(group, len(members)),
        "sample": [_item_entry(context, service, member)
                   for member in members[:GROUP_SAMPLE_SIZE]],
        "members": [
            {"submission_id": str(member.submission_id), "criterion_id": criterion_id,
             "full_name": context.full_name(str(member.submission_id)),
             "revision": int(member.version)}
            for member in members
        ],
        "why_flagged": [words for words in WHY_FLAGGED_WORDS.values() if words in reasons],
        "est_seconds": float(group.est_seconds),
        "levels": context.levels(members[0]) if members else [],
        "rank_score": float(group.expected_value),
    }


def built_queue_document(app: Any, run_row: Any, run_id: str, service: Any,
                         budget_minutes: int) -> dict[str, Any]:
    """FR-CONSOLE-91's document over one `build_queue(record=False)`: the header numbers and the
    shown entries, in the service's order."""
    built = service.build_queue(run_id, budget_minutes, record=False)
    context = _RunContext(app, run_row, run_id)
    entries = [
        _group_entry(context, service, entry) if getattr(entry, "members", None) is not None
        else _item_entry(context, service, entry)
        for entry in built.shown
    ]
    return {
        "budget_minutes": int(built.budget_minutes),
        "default_budget_minutes": int(REVIEW_DEFAULT_BUDGET_MINUTES),
        "budget_range": list(REVIEW_BUDGET_RANGE),
        "reserved_for_blind_minutes": int(built.reserved_for_blind_minutes),
        "flagged_total": int(built.flagged_total),
        "shown_total": int(built.shown_total),
        "residual_provisional": int(built.residual_provisional),
        "entries": entries,
    }


def student_name(app: Any, run_id: str, submission_id: str) -> str:
    """The student's full name for an outcome sentence; "this student" when the roster does
    not name them (an outcome never names a paper by its id, FR-UI-23)."""
    try:
        name = _RunContext(app, app._run_row(run_id), run_id).full_name(submission_id)
    except Exception:  # noqa: BLE001 — a sentence without the name still says what happened
        name = None
    return name or "this student"
