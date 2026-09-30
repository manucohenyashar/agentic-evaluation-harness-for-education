"""Timestamps and the content hashes a grade records (policy version, answer key)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from aeh.pkg import GradePolicy


def _now() -> str:
    """The current time in UTC, ISO-8601, in the same format M-DET, M-INGEST and M-ORCH use. The
    service accepts a `clock` callable instead, so a test can control time."""
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(raw: str) -> datetime | None:
    """Parse a stored ISO-8601 timestamp, reading a naive value as UTC. Returns None when the value
    is missing or unparseable; an unstamped grade has no review window to lapse."""
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
    """SHA-256 over canonical JSON (sorted keys, no spaces), so the same content always gives the
    same reference."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def policy_version_of(policy: GradePolicy) -> str:
    """The `policy_version` a grade records: the hash of the effective policy's content, review
    window included. It is a content hash, not a package version id, because a correction copies
    the policy forward under a new version id and the reference must not change with it
    (TC-GRADE-12)."""
    payload = policy.to_dict()
    payload["review_window_hours"] = policy.review_window_hours
    return _content_hash(payload)


def answer_key_ref_of(keys: Iterable[tuple[str, Iterable[str]]]) -> str:
    """The `answer_key_ref` a grade records: the hash of the version's answer keys, as
    `(criterion_id, option ids)` pairs in criterion order. It is a content hash, not a version id,
    so only an actual key correction changes it (TC-GRADE-12)."""
    return _content_hash(
        [[criterion_id, list(key)] for criterion_id, key in sorted(keys)]
    )
