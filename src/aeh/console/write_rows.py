"""The rows a control action writes: one per declared effect, with named defaults."""

from __future__ import annotations

from typing import Any, Callable

from .vocabulary import CONSOLE_WRITE_FIELDS
from .html import _now


# --- the control-action payload table -------------------------------------------------------------------


def _rows_for(action: str, params: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The rows `action` writes: one per declared effect, each carrying only the fields
    §11.8 declares for it. Values come from `params` where the caller supplied them, and
    are honest placeholders where a bare call did not — the sweep drives all fifteen
    bare, and the field contract is what the payloads are assertable against."""
    by_action: dict[str, list[str]] = {}
    for dotted in CONSOLE_WRITE_FIELDS[action]:
        table, field = dotted.split(".", 1)
        by_action.setdefault(table, []).append(field)
    rows: list[tuple[str, dict[str, Any]]] = []
    for table, fields in by_action.items():
        payload: dict[str, Any] = {field: _field_value(action, field, params) for field in fields}
        rows.append((table, payload))
    return rows


_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "run_id": ("run_id", "id"),
    "status": ("status", "state"),
    "new_band": ("new_band", "band"),
    "answer_key": ("answer_key", "key"),
}


_NAMED_DEFAULTS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "question_id": lambda p: p.get("question_id", "q-1"),
    "prompt_text": lambda p: p.get("prompt_text", "as read back from the package"),
    "order": lambda p: p.get("order", 1),
    "band": lambda p: p.get("band", p.get("new_band", "as read back")),
    "new_band": lambda p: p.get("new_band", p.get("band", "as read back")),
    "descriptor": lambda p: p.get("descriptor", "as read back from the rubric"),
    "rule": lambda p: p.get("rule", "as read back from the policy"),
    "cut": lambda p: p.get("cut", p.get("grade_cut", "as read back")),
    "text": lambda p: p.get("text", "as read back from the rubric"),
    "decomposable": lambda p: p.get("decomposable", False),
    "review_window_hours": lambda p: p.get("review_window_hours", p.get("hours", 48.0)),
    "ingest_status": lambda p: p.get("ingest_status", "incomplete"),
    "quarantined": lambda p: p.get("quarantined", 0),
    "action": lambda p: p.get("action", "as requested"),
    "acted_at": lambda p: p.get("acted_at") or _now(),
    "label_type": lambda p: p.get("label_type", "blind"),
    "answer_key": lambda p: p.get("answer_key", p.get("key", "as supplied")),
    "finalized_at": lambda p: p.get("finalized_at") or _now(),
    "revision": lambda p: p.get("revision", 1),
    "bands": lambda p: p.get("bands", ()),
    "actor": lambda p: p.get("actor", "operator"),
    "provenance": lambda p: p.get("provenance", "approved at export"),
    "contains_real_student_text": lambda p: p.get("contains_real_student_text", False),
    "path": lambda p: p.get("path", "package-export.zip"),
    "purged_at": lambda p: p.get("purged_at") or _now(),
    "run_id": lambda p: p.get("run_id", "r-unaddressed"),
}


def _field_value(action: str, field: str, params: dict[str, Any]) -> Any:
    for alias in _FIELD_ALIASES.get(field, (field,)):
        if params.get(alias) is not None:
            return params[alias]
    if field == "status":
        return params.get("state", "paused" if action == "pause/resume" else "requested")
    if field in _NAMED_DEFAULTS:
        return _NAMED_DEFAULTS[field](params)
    return params.get(field, f"{action}:{field}")
