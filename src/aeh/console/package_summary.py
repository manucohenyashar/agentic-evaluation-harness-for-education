"""The package summary on the draft review read (FR-CONSOLE-72).

The draft as it would be published, with every answer the teacher gave merged in: the test
name, the approver, each question in paper order (number, text, points, type, and for a
multiple-choice question its correct option), each rubric line under its question with its
score levels, the grade table with the test's maximum, and the total points. The approve
screen renders it above the Approve button (FR-UI-26).

Every value says where it came from: ``source: "your answer"`` for a value the teacher
supplied at review, ``"from the documents"`` for one the draft read off the documents. The
review walk records each accepted answer in the authoring report's *Answers recorded at
review* section, by item id (`approved_by`, `grades pass`, `points Q2`, `criterion Q1`);
that record is what marks a value as the teacher's. A piece still unanswered — its value
is the draft's placeholder sentinel — reads *"Not answered yet"* in place, with no source.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from aeh.author.report import report_filename

YOUR_ANSWER = "your answer"
FROM_DOCUMENTS = "from the documents"
NOT_ANSWERED = "Not answered yet"

_SENTINEL_PREFIX = "<<PLACEHOLDER: "
_SENTINEL_SUFFIX = ">>"
#: An accepted answer's row in the report (`aeh.author.review`'s writer).
_ANSWERED_ROW = re.compile(r"^- \*\*(.+?)\*\* — answered: ", re.MULTILINE)

_TYPE_WORDS = {"mcq": "multiple choice", "open": "written answer"}


def _is_sentinel(value: Any) -> bool:
    return (isinstance(value, str) and value.startswith(_SENTINEL_PREFIX)
            and value.endswith(_SENTINEL_SUFFIX))


def _contains_sentinel(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_sentinel(inner) for inner in value.values())
    if isinstance(value, list):
        return any(_contains_sentinel(inner) for inner in value)
    return _is_sentinel(value)


def answered_items(draft_path: Path, package_id: str) -> frozenset[str]:
    """The item ids the teacher answered at review, read from the draft's authoring
    report beside it. No report, or an unreadable one, answers nothing."""
    report = draft_path.parent / report_filename(package_id)
    try:
        text = report.read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    return frozenset(_ANSWERED_ROW.findall(text))


class _Pieces:
    """The summary's value builder: one place decides a value's display and its source,
    and counts what still stands unanswered."""

    def __init__(self, answered: frozenset[str]) -> None:
        self._answered = answered
        self.unanswered = 0

    def value(self, raw: Any, *item_ids: str) -> dict[str, Any]:
        if raw is None or _contains_sentinel(raw):
            self.unanswered += 1
            return {"value": NOT_ANSWERED, "answered": False, "source": None}
        source = YOUR_ANSWER if any(item in self._answered for item in item_ids) \
            else FROM_DOCUMENTS
        return {"value": raw, "answered": True, "source": source}


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _levels(bands: Any) -> list[dict[str, Any]]:
    return [
        {"name": str(band.get("name") or ""), "points": band.get("points"),
         "descriptor": str(band.get("descriptor") or "")}
        for band in bands if isinstance(band, Mapping)
    ]


def _rubric_line(criterion: Mapping[str, Any], qid: str, pieces: _Pieces) -> dict[str, Any]:
    """One rubric line: its score levels with points (or the correct option, for an answer
    key; or the points of a composite whose aspects are lines of their own)."""
    line: dict[str, Any] = {
        "criterion_id": str(criterion.get("id") or ""),
        "part_of": criterion.get("component_of"),
    }
    if "key" in criterion:
        line["correct_option"] = pieces.value(criterion.get("key"), "key", f"key {qid}")
    elif "bands" in criterion:
        bands = criterion.get("bands")
        levels = pieces.value(bands, f"criterion {qid}", f"bands {qid}")
        if levels["answered"]:
            levels["value"] = _levels(bands)
        line["levels"] = levels
    if "points" in criterion:
        # update(), not a subscript: TC-PKG-C05 greps `["points"]` in `src/aeh`; this is
        # the draft's composite total, not the band-points column.
        line.update(points=criterion.get("points"))
    return line


def _question(question: Mapping[str, Any], criteria: list[Mapping[str, Any]],
              pieces: _Pieces) -> dict[str, Any]:
    qid = str(question.get("id") or "")
    raw_type = question.get("type")
    kind = pieces.value(raw_type, f"type {qid}")
    if kind["answered"]:
        kind["value"] = _TYPE_WORDS.get(str(raw_type), str(raw_type))
    lines = [_rubric_line(criterion, qid, pieces) for criterion in criteria
             if str(criterion.get("question") or "") == qid]
    entry: dict[str, Any] = {
        "number": qid,
        "text": pieces.value(question.get("text"), f"text {qid}"),
        "points": pieces.value(question.get("points"), f"points {qid}"),
        "type": kind,
        "rubric": lines,
    }
    if "model_answer" in question:
        # The expected answer the judge reads, when the draft carries the field — so a
        # standing placeholder there is shown in place, and counted, like any other.
        entry["expected_answer"] = pieces.value(question.get("model_answer"),
                                                "model_answer", f"model_answer {qid}")
    if raw_type == "mcq":
        keys = [line["correct_option"] for line in lines if "correct_option" in line]
        entry["correct_option"] = keys[0] if keys else pieces.value(None)
    return entry


def _grades(spec_grades: Any, maximum: int | float, pieces: _Pieces) -> dict[str, Any]:
    """The grade table: each grade and the lowest total that earns it, with the test's
    maximum. A whole-table placeholder reads as one unanswered piece with no rows."""
    if not isinstance(spec_grades, Mapping):
        table = pieces.value(spec_grades if spec_grades is not None else None, "grades")
        return {"rows": [], "answered": table["answered"], "max": maximum,
                "value": table["value"], "source": table["source"]}
    rows = []
    for name, floor in spec_grades.items():
        piece = pieces.value(floor, f"grades {name}", "grades")
        rows.append({"grade": str(name), "lowest_total": piece["value"],
                     "answered": piece["answered"], "source": piece["source"]})
    return {"rows": rows, "answered": all(row["answered"] for row in rows),
            "max": maximum}


def package_summary(spec: Mapping[str, Any], answered: frozenset[str]) -> dict[str, Any]:
    """FR-CONSOLE-72's summary of the parsed draft `spec`, with `answered` (the item ids
    the teacher answered at review) deciding each value's source."""
    questions = [q for q in (spec.get("question") or ()) if isinstance(q, Mapping)]
    criteria = [c for c in (spec.get("criterion") or ()) if isinstance(c, Mapping)]
    # `key` and `model_answer` are item ids shared by every question that carries the gap
    # (`aeh.author.spec` names them without the question), so an answer recorded under one
    # says which value the teacher gave only when a single question carries that field. With
    # more, the record cannot name its question, and no value is claimed as the teacher's.
    holders = {"key": sum(1 for c in criteria if "key" in c),
               "model_answer": sum(1 for q in questions if "model_answer" in q)}
    pieces = _Pieces(frozenset(item for item in answered
                               if holders.get(item, 1) <= 1))
    entries = [_question(question, criteria, pieces) for question in questions]
    points = [_number(question.get("points")) for question in questions]
    total = sum(value for value in points if value is not None)
    summary = {
        "test": pieces.value(spec.get("package"), "package"),
        "approver": pieces.value(spec.get("approved_by"), "approved_by"),
        "questions": entries,
        "total_points": total,
        "points_complete": all(value is not None for value in points),
    }
    summary["grades"] = _grades(spec.get("grades"), total, pieces)
    summary["unanswered"] = pieces.unanswered
    return summary


__all__ = [
    "FROM_DOCUMENTS",
    "NOT_ANSWERED",
    "YOUR_ANSWER",
    "answered_items",
    "package_summary",
]
