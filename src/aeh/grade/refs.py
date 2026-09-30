"""Timestamps and the content hashes a grade records (policy version, answer key)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from aeh.pkg import GradePolicy


def _now() -> str:
    """The wall clock, UTC ISO-8601 — the same form det/ingest/orch record, so every
    timestamp in the store reads the same way. Injectable: the service accepts a
    `clock` callable, so a deterministic driver can drive time; the shipped review
    window is measured against this module's issued timestamps by real wall-clock
    comparison (`backdate_grades`' stand-in writes real-clock timestamps)."""
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(raw: str) -> datetime | None:
    """Parse a stored ISO-8601 timestamp; naive values are read as UTC (a timestamp
    this module wrote is always aware, but a hand-written row should not crash the
    pass). None when the value is absent or unparseable — an unstamped grade has no
    window to lapse."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _content_hash(payload: Any) -> str:
    """A content ref: SHA-256 over canonical JSON (sorted keys, no spacing) — the
    same serialization discipline set_grade_policy stores with, so the ref is stable
    across processes and byte-identical for identical content."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def policy_version_of(policy: GradePolicy) -> str:
    """The `policy_version` ref a grade records: the hash of the effective policy's
    canonical content, review window included. A content hash, never a package version
    id — the copy-forward correction flow (aeh/pkg.py `create_version`) changes the
    version id while carrying the policy unchanged, and the ref must not move with it
    (`TC-GRADE-12`: only the policy change may move `policy_version`)."""
    payload = policy.to_dict()
    payload["review_window_hours"] = policy.review_window_hours
    return _content_hash(payload)


def answer_key_ref_of(keys: Iterable[tuple[str, Iterable[str]]]) -> str:
    """The `answer_key_ref` ref a grade records: the hash of the version's key
    content — `(criterion_id, key option ids)` pairs, ordered by criterion id. A
    content hash, never a version id: a revision produced under a copied-forward key
    must record the same ref as the revision before it (`TC-GRADE-12`'s third limb),
    and only a key CORRECTION may move it."""
    return _content_hash(
        [[criterion_id, list(key)] for criterion_id, key in sorted(keys)]
    )
