"""The gate's thresholds and switches, each read from its environment knob at call time."""

from __future__ import annotations

import math
import os


#: The declared defaults (each overridable by its environment variable, above).
_DEFAULT_OCR_FLOOR = 0.70


_DEFAULT_RETRY_LIMIT = 3


_DEFAULT_ALERT_THRESHOLD = 0.10


_OCR_FLOOR_ENV = "INTEG_OCR_CONF_FLOOR"


_DESCRIBED_ROUTES_ENV = "INTEG_DESCRIBED_EVIDENCE_ROUTES"


_DISABLED_ENV = "INTEG_SPAN_VERIFICATION_DISABLED"


_RETRY_LIMIT_ENV = "INTEG_RETRY_LIMIT"


_ALERT_THRESHOLD_ENV = "INTEG_ALERT_THRESHOLD"


# --- env-gated knobs (read at call time, so a test can move them per scenario) --------------------


def _ocr_conf_floor_override() -> float:
    """The configured floor, or `inf` when unparseable — an unreadable floor
    flags every region rather than certifying any (the fail-closed reading)."""
    raw = os.environ.get(_OCR_FLOOR_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_OCR_FLOOR
    try:
        return float(raw)
    except ValueError:
        return math.inf


def _described_routes_enabled() -> bool:
    raw = os.environ.get(_DESCRIBED_ROUTES_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in ("false", "0", "off", "no")


def _verification_disabled() -> bool:
    """Whether the span-verification switch is explicitly set to a truthy value —
    the differential-timing seam the plan's own oracle names.

    A truthy spelling (`1`, `true`, `yes`, `on`) disables; everything else —
    unset, empty, `0`, `false`, `off`, `no`, garbage — leaves verification ON.
    The sibling knob (`_described_routes_enabled`) reads off-spellings as off;
    this is the same convention pointed the other way, so an operator's
    explicit `=false` cannot silently disable verification and route every
    cell to re-extraction."""
    raw = os.environ.get(_DISABLED_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _retry_limit() -> int:
    raw = os.environ.get(_RETRY_LIMIT_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_RETRY_LIMIT
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_RETRY_LIMIT
    return value if value >= 1 else _DEFAULT_RETRY_LIMIT


def _alert_threshold() -> float:
    raw = os.environ.get(_ALERT_THRESHOLD_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_ALERT_THRESHOLD
    try:
        return float(raw)
    except ValueError:
        return 0.0


# --- the gate ---------------------------------------------------------------------------------------


#: `FR-INTEG-11`: how many verified documents one gate instance holds. 64 is a class's worth of
#: submissions — the working set of a single run's pass — and the bound exists because the
#: cache holds whole documents: an unbounded one on a large cohort is a memory leak with a
#: helpful name. Read at call time (seam 3), and refused loudly when it is not a positive
#: integer: a zero or a negative would silently disable the cache the requirement asks for.
INTEG_DOCUMENT_CACHE_ENTRIES: int = 64


INTEG_DOCUMENT_CACHE_ENTRIES_ENV = "HARNESS_INTEG_DOCUMENT_CACHE_ENTRIES"


def _document_cache_entries() -> int:
    """The document cache's bound, read at call time."""
    raw = os.environ.get(INTEG_DOCUMENT_CACHE_ENTRIES_ENV)
    if raw is None or raw.strip() == "":
        return INTEG_DOCUMENT_CACHE_ENTRIES
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(
            f"environment knob {INTEG_DOCUMENT_CACHE_ENTRIES_ENV}={raw!r} is not an integer."
        ) from error
    if value < 1:
        raise ValueError(
            f"environment knob {INTEG_DOCUMENT_CACHE_ENTRIES_ENV}={raw!r} must be at least 1: "
            "a zero or negative bound would disable the cache FR-INTEG-11 requires, silently."
        )
    return value
