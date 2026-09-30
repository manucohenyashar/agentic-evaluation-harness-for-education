"""The knobs of the run loop: how many passes, how long to wait between them."""

from __future__ import annotations

import os


#: Seam 3. Both are read at CALL time and validated before the first pass, because a malformed
#: knob discovered on pass three has already written rows.
MAX_PASSES_ENV = "HARNESS_PIPE_MAX_PASSES"


PASS_SLEEP_MS_ENV = "HARNESS_PIPE_PASS_SLEEP_MS"


#: How many consecutive passes may make no headway before the loop gives up.
#:
#: One is too few. A pass in which every unit came back `RateLimitedError` requeues them all
#: (`FR-ORCH-30`), so `done`, `pending` and `in_flight` are unchanged and the next pass looks
#: identical — and `RES-11`'s back-off IS the next pass. Breaking on the first repeat would
#: abandon a rate-limited run as `running` with work outstanding, which `FR-PIPE-01` forbids.
#: Three bounds the retry without turning a genuinely stuck run into a spin.
STALL_PASSES = 3


# --- the knobs ------------------------------------------------------------------------------


def _int_knob(name: str, default: int | None, *, minimum: int) -> int | None:
    """Read one `HARNESS_PIPE_*` integer knob at call time. An invalid value raises before anything
    is written."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as error:
        raise ValueError(
            f"{name}={raw!r} is not an integer. The knob is read at call time and validated "
            f"before the first dispatch pass, so a malformed value never half-drives a run."
        ) from error
    if value < minimum:
        raise ValueError(f"{name}={value} is below the minimum of {minimum}.")
    return value
