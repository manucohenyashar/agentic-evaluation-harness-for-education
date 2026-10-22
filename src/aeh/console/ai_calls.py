"""The AI-call read (FR-CONSOLE-78) and the text the `aeh logs ai-calls` CLI prints (FR-CONSOLE-79).

The journal M-PROV writes (FR-CONSOLE-77) holds one JSON line per model call attempt under
`<data_dir>/logs/ai-calls/`. This module reads those files, nothing else of M-PROV: the
readers and the two vocabularies are its whole import (TC-CONSOLE-36 — the console never
imports provider construction). It adds what a teacher needs to read a record: the kind's
teacher label, the student's name (looked up through the class list, since a record carries
the paper's `submission_id`, never a name) and the question the grading point grades.

One implementation for both surfaces: `GET /api/v1/ai-calls` answers `ai_calls_read`, and
the CLI calls `select_ai_calls` and `summary_line` on a store it opens itself.

A read, never a write: a class or package file is consulted only when it already exists, so
a journal record naming a class that was never created (or was purged) cannot make the read
create its database. CT-CONSOLE-09 as amended: this is a per-call audit view and names
students by design, for `synthetic` and `real` classes alike — no consent filter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aeh.prov import CALL_KINDS, CALL_OUTCOMES, iter_call_records, journal_files

from .settings import ai_calls_page_size
from .spa_reads import _query_page

#: The teacher label for each kind of call (FR-CONSOLE-78). `rubric_setup` and `unlabelled`
#: are not in the FR's list — the journal can still hold them, so they carry a label too.
KIND_LABELS: dict[str, str] = {
    "jev_decision": "Jev decision",
    "ai_judge": "AI judge",
    "page_reading": "Page reading",
    "package_drafting": "Package drafting",
    "rubric_setup": "Rubric setup",
    "answer_extraction": "Answer finding",
    "feedback_writing": "Feedback writing",
    "help_question": "Help question",
    "unlabelled": "Other AI call",
}

#: The kinds the read shows when it is asked for none (FR-UI-35: the AI-calls view opens on
#: the grading calls). `kind=all` asks for every kind.
DEFAULT_KINDS: tuple[str, ...] = ("jev_decision", "ai_judge")
ALL_KINDS = "all"

#: What the CLI prints when nothing matches (exit 0 — an empty answer is not an error).
NO_MATCH = "No AI calls match."

_KNOWN_KINDS: tuple[str, ...] = (*CALL_KINDS, "unlabelled")


@dataclass(frozen=True)
class AiCallFilters:
    """What one read narrows the journal to. A field left None does not narrow."""

    run_id: str | None = None
    cohort_id: str | None = None
    package_id: str | None = None
    kinds: tuple[str, ...] | None = DEFAULT_KINDS
    student: str | None = None
    question_id: str | None = None
    outcomes: tuple[str, ...] | None = None


def _blank_to_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _listed(raw: Any) -> list[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def parse_kinds(raw: Any, default: tuple[str, ...] | None = DEFAULT_KINDS) -> tuple[str, ...] | None:
    """`kind=` as the read takes it: a comma-separated list, `all` for every kind, absent
    for `default`. An unknown kind is refused, never answered with an empty page."""
    parts = _listed(raw)
    if not parts:
        return default
    if ALL_KINDS in parts:
        return None
    unknown = [part for part in parts if part not in _KNOWN_KINDS]
    if unknown:
        raise ValueError(
            f"there is no kind of AI call called {', '.join(unknown)}; the kinds are "
            f"{', '.join(_KNOWN_KINDS)}, or all")
    return tuple(parts)


def parse_outcomes(raw: Any) -> tuple[str, ...] | None:
    """`outcome=` as the read takes it: a comma-separated list, absent for every outcome."""
    parts = _listed(raw)
    if not parts:
        return None
    unknown = [part for part in parts if part not in CALL_OUTCOMES]
    if unknown:
        raise ValueError(
            f"there is no AI call outcome called {', '.join(unknown)}; the outcomes are "
            f"{', '.join(CALL_OUTCOMES)}")
    return tuple(parts)


def filters_from_query(query: Any) -> AiCallFilters:
    """The filters a `GET /api/v1/ai-calls` query string names."""
    query = query or {}
    return AiCallFilters(
        run_id=_blank_to_none(query.get("run_id")),
        cohort_id=_blank_to_none(query.get("cohort_id")),
        package_id=_blank_to_none(query.get("package_id")),
        kinds=parse_kinds(query.get("kind")),
        student=_blank_to_none(query.get("student")),
        question_id=_blank_to_none(query.get("question_id")),
        outcomes=parse_outcomes(query.get("outcome")),
    )


def _folded(text: Any) -> str:
    return " ".join(str(text or "").split()).casefold()


# --- the store lookups: names and questions -------------------------------------------------------


class _Lookups:
    """Read-only, cached lookups against the store: a paper's student and their listed name,
    and a grading point's question. A class or package file that does not exist is never
    opened (opening would create it), and an unreadable one answers nothing — the record is
    still listed, with its ids."""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._students: dict[str, dict[str, tuple[str, str]]] = {}
        self._listed: dict[str, dict[str, str]] = {}
        self._runs: dict[tuple[str, str], tuple[str, str] | None] = {}
        self._questions: dict[tuple[str, str], dict[str, str]] = {}
        self._gates: dict[tuple[str, str], float | None] = {}

    def _existing(self, path_of: str, key: str) -> bool:
        locate = getattr(self._store, path_of, None)
        if not key or not callable(locate):
            return False
        try:
            return Path(locate(key)).is_file()
        except (OSError, ValueError, TypeError):
            return False

    def students_of(self, cohort_id: str) -> dict[str, tuple[str, str]]:
        """`submission_id → (student_ref, name)` for one class. The name is the listed full
        name; the ref is appended only when two students on the list share it, and stands
        alone for a student with no name (FR-UI-22)."""
        if cohort_id in self._students:
            return self._students[cohort_id]
        found: dict[str, tuple[str, str]] = {}
        if self._existing("cohort_path", cohort_id):
            try:
                handle = self._store.cohort(cohort_id)
                names = {str(row["student_ref"]): str(row["full_name"] or "").strip()
                         for row in handle.query("SELECT student_ref, full_name FROM roster")}
                papers = [(str(row["submission_id"]), str(row["student_ref"]))
                          for row in handle.query(
                              "SELECT submission_id, student_ref FROM submission")]
            except Exception:  # noqa: BLE001 — names are a convenience beside the ids
                names, papers = {}, []
            counts: dict[str, int] = {}
            for name in names.values():
                if name:
                    counts[_folded(name)] = counts.get(_folded(name), 0) + 1
            for submission_id, ref in papers:
                name = names.get(ref, "")
                if not name:
                    shown = ref
                elif counts.get(_folded(name), 0) > 1:
                    shown = f"{name} ({ref})"
                else:
                    shown = name
                found[submission_id] = (ref, shown)
            self._listed[cohort_id] = names
        self._students[cohort_id] = found
        return found

    def listed_name(self, cohort_id: str, ref: str) -> str:
        """The student's bare listed name (no ref appended), or empty."""
        self.students_of(cohort_id)
        return self._listed.get(cohort_id, {}).get(ref, "")

    def run_package(self, cohort_id: str, run_id: str) -> tuple[str, str] | None:
        """`(package_id, package_version_id)` the run graded against, or None. Grading calls
        carry no `package_id` of their own (the run's context does not set it), so the read
        takes it from the run row."""
        key = (cohort_id, run_id)
        if key not in self._runs:
            found = None
            if run_id and self._existing("cohort_path", cohort_id):
                try:
                    rows = list(self._store.cohort(cohort_id).query(
                        "SELECT package_id, package_version_id FROM run WHERE run_id = :run_id",
                        run_id=run_id))
                    if rows:
                        found = (str(rows[0]["package_id"]), str(rows[0]["package_version_id"]))
                except Exception:  # noqa: BLE001 — the record's own ids stand
                    found = None
            self._runs[key] = found
        return self._runs[key]

    def questions_of(self, cohort_id: str, run_id: str) -> dict[str, str]:
        """`criterion_id → question_id` for the package version the run graded against."""
        key = (cohort_id, run_id)
        if key in self._questions:
            return self._questions[key]
        found: dict[str, str] = {}
        run = self.run_package(cohort_id, run_id)
        if run is not None and self._existing("package_path", run[0]):
            try:
                found = {
                    str(row["criterion_id"]): str(row["question_id"] or "")
                    for row in self._store.package(run[0]).query(
                        "SELECT criterion_id, question_id FROM criterion "
                        "WHERE package_version_id = :v", v=run[1])
                }
            except Exception:  # noqa: BLE001 — the grading point's id stands in for the question
                found = {}
        self._questions[key] = found
        return found

    def confidence_gate(self, cohort_id: str, run_id: str) -> str | None:
        """The run's decision-confidence threshold (FR-UI-34's "needed above …"), read from
        the engine the run recorded at start (`run.provider_config` →
        `decision_engine.threshold`, per `orch/run_records.py`'s record — the frozen
        canonical value, never a re-resolution against today's settings). `None` when the
        run recorded no engine or an unreadable one: no threshold is invented."""
        key = (cohort_id, run_id)
        if key in self._gates:
            return self._gates[key]
        gate = None
        if run_id and self._existing("cohort_path", cohort_id):
            try:
                rows = list(self._store.cohort(cohort_id).query(
                    "SELECT provider_config FROM run WHERE run_id = :run_id", run_id=run_id))
                recorded = json.loads(str(rows[0]["provider_config"] or "{}"))
                engine = recorded.get("decision_engine")
                if isinstance(engine, Mapping) and engine.get("threshold") is not None:
                    gate = str(engine["threshold"])
            except Exception:  # noqa: BLE001 — a missing gate omits the line, never a 500
                gate = None
        self._gates[key] = gate
        return gate


# --- the read ---------------------------------------------------------------------------------------


def _confidence_block(record: dict[str, Any], lookups: _Lookups) -> dict[str, Any] | None:
    """A Jev decision's confidence line, as the read serves it (FR-UI-34): the gate's own
    value — the lesser of the band answer's confidence and the sufficiency answer's, the
    rule `gate_decision` applies — beside the threshold the run recorded at start. `None`
    when the response holds no such answers: no number is invented."""
    if str(record.get("kind") or "") != "jev_decision":
        return None
    response = record.get("response")
    if not isinstance(response, Mapping):
        return None
    values: list[float] = []
    for key in ("band", "evidence_sufficient"):
        answer = response.get(key)
        if isinstance(answer, Mapping) and isinstance(answer.get("confidence"), (int, float)):
            values.append(float(answer["confidence"]))
    if not values:
        return None
    cohort_id = str(record.get("cohort_id") or "")
    run_id = str(record.get("run_id") or "")
    return {
        "value": min(values),
        "threshold": lookups.confidence_gate(cohort_id, run_id),
    }


def _item(record: dict[str, Any], lookups: _Lookups) -> dict[str, Any]:
    """One journal record as the read answers it: the journal's own fields, plus the kind's
    teacher label, the student and the question."""
    cohort_id = str(record.get("cohort_id") or "")
    submission_id = str(record.get("submission_id") or "")
    criterion_id = str(record.get("criterion_id") or "")
    run_id = str(record.get("run_id") or "")
    student_ref = student_name = None
    if cohort_id and submission_id:
        student = lookups.students_of(cohort_id).get(submission_id)
        if student is not None:
            student_ref, student_name = student
    question = None
    if criterion_id:
        question = (lookups.questions_of(cohort_id, run_id).get(criterion_id)
                    if cohort_id and run_id else None) or criterion_id
    kind = str(record.get("kind") or "unlabelled")
    package_id = record.get("package_id")
    if not package_id and cohort_id and run_id:
        run = lookups.run_package(cohort_id, run_id)
        package_id = run[0] if run is not None else None
    return {
        "call_id": record.get("call_id"),
        "attempt": record.get("attempt"),
        "at": record.get("at"),
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, KIND_LABELS["unlabelled"]),
        "cohort_id": record.get("cohort_id"),
        "run_id": record.get("run_id"),
        "work_id": record.get("work_id"),
        "submission_id": record.get("submission_id"),
        "student_ref": student_ref,
        "student_name": student_name,
        "criterion_id": record.get("criterion_id"),
        "question": question,
        "package_id": package_id,
        "model": record.get("model"),
        "resolved_build": record.get("resolved_build"),
        "outcome": record.get("outcome"),
        "error": record.get("error"),
        "latency_ms": record.get("latency_ms"),
        "tokens_in": record.get("tokens_in"),
        "tokens_out": record.get("tokens_out"),
        "cost": record.get("cost"),
        "request": record.get("request"),
        "response": record.get("response"),
        # FR-UI-34: the confidence line's numbers, for a Jev decision only.
        "confidence": _confidence_block(record, lookups),
    }


def _student_matches(item: dict[str, Any], wanted: str, lookups: _Lookups) -> bool:
    """`student=` matches the listed full name (case and spacing aside), or the ref itself
    — so a name two students share selects both, and the ref picks one."""
    ref = item["student_ref"]
    if ref is None:
        return False
    if wanted == ref:
        return True
    return _folded(lookups.listed_name(str(item["cohort_id"]), ref)) == _folded(wanted)


def _question_matches(item: dict[str, Any], wanted: str) -> bool:
    return _folded(item["question"]) == _folded(wanted) or item["criterion_id"] == wanted


def _matches_ids(record: dict[str, Any], filters: AiCallFilters) -> bool:
    if filters.run_id and record.get("run_id") != filters.run_id:
        return False
    if filters.cohort_id and record.get("cohort_id") != filters.cohort_id:
        return False
    if filters.kinds is not None and str(record.get("kind") or "unlabelled") not in filters.kinds:
        return False
    if filters.outcomes is not None and record.get("outcome") not in filters.outcomes:
        return False
    return True


def matching_calls(store: Any, data_dir: Any, filters: AiCallFilters,
                   ) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], dict[str, int]]:
    """Every journal record the filters keep, newest first, each as `(raw record, item)`,
    and what the read did: how many files and records it read."""
    stats = {"files_read": 0, "records_read": 0}
    if data_dir is None:
        return [], stats
    folder: tuple[str, ...] = ()
    if filters.cohort_id and "/" not in filters.cohort_id and "\\" not in filters.cohort_id \
            and not filters.cohort_id.startswith((".", "_")):
        folder = (filters.cohort_id,)
    stats["files_read"] = len(journal_files(data_dir, *folder))
    lookups = _Lookups(store)
    kept: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for record in iter_call_records(data_dir, *folder):
        stats["records_read"] += 1
        if not _matches_ids(record, filters):
            continue
        item = _item(record, lookups)
        if filters.package_id and item["package_id"] != filters.package_id:
            continue
        if filters.student and not _student_matches(item, filters.student, lookups):
            continue
        if filters.question_id and not _question_matches(item, filters.question_id):
            continue
        kept.append((record, item))
    kept.sort(key=lambda pair: (str(pair[1]["at"] or ""), str(pair[1]["call_id"] or ""),
                                int(pair[1]["attempt"] or 0)), reverse=True)
    return kept, stats


def select_ai_calls(store: Any, data_dir: Any, filters: AiCallFilters, *, page: int = 1,
                    page_size: int | None = None) -> dict[str, Any]:
    """One page of the AI-call read: the items, newest first, and the paging and the
    observability beside them (what was read, how many matched)."""
    size = page_size if page_size is not None else ai_calls_page_size()
    kept, stats = matching_calls(store, data_dir, filters)
    start = (page - 1) * size
    items = [item for _record, item in kept[start:start + size]]
    return {
        "items": items,
        "page": page,
        "page_size": size,
        "total": len(kept),
        "more": start + size < len(kept),
        "filters": {
            "run_id": filters.run_id,
            "cohort_id": filters.cohort_id,
            "package_id": filters.package_id,
            "kind": list(filters.kinds) if filters.kinds is not None else ALL_KINDS,
            "student": filters.student,
            "question_id": filters.question_id,
            "outcome": list(filters.outcomes) if filters.outcomes is not None else None,
        },
        "projected": {**stats, "matched": len(kept)},
    }


def ai_calls_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """`GET /api/v1/ai-calls` (FR-CONSOLE-78): journal records newest first, 50 per page,
    filtered by `run_id`, `cohort_id`, `package_id`, `kind` (comma-separated; the grading
    calls when absent, every kind for `all`), `student` (a name), `question_id` and
    `outcome`; `page` from 1."""
    del console
    filters = filters_from_query(query)
    page = _query_page(query)
    store = getattr(app, "_store", None)
    return select_ai_calls(store, getattr(store, "data_dir", None), filters, page=page)


def with_verbatim_calls(shown: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """`shown` (the answer after the teacher-text boundary) with each item's `request` and
    `response` put back exactly as the journal holds them: the boundary tidies display text,
    and these two are the record of what the AI was asked and answered (FR-CONSOLE-78)."""
    for shown_item, raw_item in zip(shown.get("items") or [], raw.get("items") or []):
        shown_item["request"] = raw_item["request"]
        shown_item["response"] = raw_item["response"]
    return shown


# --- the CLI's text (FR-CONSOLE-79) ---------------------------------------------------------------


def _shown(value: Any) -> str:
    return "-" if value is None or value == "" else str(value)


def summary_line(item: dict[str, Any]) -> str:
    """One call on one line: time, kind, student, question, model, duration, cost, outcome."""
    duration = item["latency_ms"]
    return "  ".join((
        _shown(item["at"]),
        item["kind_label"],
        _shown(item["student_name"]),
        _shown(item["question"]),
        _shown(item["model"]),
        f"{duration} ms" if duration is not None else "-",
        f"cost {item['cost']}" if item["cost"] not in (None, "") else "cost -",
        _shown(item["outcome"]),
    ))


def _verbatim(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, ensure_ascii=False)


def full_text(item: dict[str, Any]) -> str:
    """A call's summary line with what the AI was asked and what it answered under it."""
    lines = [summary_line(item), "  What the AI was asked:"]
    lines.extend("    " + line for line in _verbatim(item["request"]).splitlines() or [""])
    lines.append("  What it answered:")
    lines.extend("    " + line for line in _verbatim(item["response"]).splitlines() or [""])
    if item["error"]:
        lines.append(f"  Error: {item['error']}")
    return "\n".join(lines)


__all__ = [
    "ALL_KINDS",
    "AiCallFilters",
    "DEFAULT_KINDS",
    "KIND_LABELS",
    "NO_MATCH",
    "ai_calls_read",
    "filters_from_query",
    "full_text",
    "matching_calls",
    "parse_kinds",
    "parse_outcomes",
    "select_ai_calls",
    "summary_line",
    "with_verbatim_calls",
]
