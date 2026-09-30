"""The console's bind address, port and time budgets, and the knobs read at call time."""

from __future__ import annotations

import os

from aeh.review import REVIEW_BLIND_RESERVE_MINUTES


# --- the declared knobs (design §3.19, Configuration line) -------------------------------------------
#
# Production values are the defaults; `CONSOLE_PORT` has no declared default and stays None
# (the suite asserts only that the knob exists — asserting a value would assert a guess).

CONSOLE_BIND = "127.0.0.1"


CONSOLE_PORT: int | None = None


CONSOLE_POLL_INTERVAL_MS = 3000


#: The bind an adversarial operator reaches for; the refusal must not be defeatable by it.
ROUTABLE_BIND = "0.0.0.0"


#: The upload walk's chunk size, env-gated (seam 3): a slower box shrinks it without a code
#: change, and the 1-second handler budget holds either way because the walk never touches the
#: declared size as a whole.
_UPLOAD_CHUNK_DEFAULT = 4 * 1024 * 1024


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(f"environment knob {name}={raw!r} is not an integer.") from error


def upload_chunk_bytes() -> int:
    """The chunk size the upload walk uses this call (knob read at call time)."""
    return max(1, _env_int("HARNESS_CONSOLE_UPLOAD_CHUNK_BYTES", _UPLOAD_CHUNK_DEFAULT))


#: The blind reservation the queue makes when the store carries no `review_budget` row:
#: `M-REVIEW`'s declared default (`CT-REVIEW-02`), not a number this module recomputes.
#: Env-gated (seam 3) and read at call time, like every knob here.
def blind_reserve_minutes() -> int:
    """The blind-reservation default this console run uses (knob read at call time)."""
    return max(0, _env_int("HARNESS_CONSOLE_BLIND_RESERVE_MINUTES", REVIEW_BLIND_RESERVE_MINUTES))


#: The headless driver's deterministic batch size: how many synthetic submissions
#: `finalize_batch` settles when no store is attached. A knob, so a slower box can
#: shrink it and a load test can grow it without a code change.
def headless_batch_size() -> int:
    """The submission count the headless driver settles per finalized batch."""
    return max(1, _env_int("HARNESS_CONSOLE_HEADLESS_BATCH", 12))


#: Budgets the console declares (§6.11.19): the handler budget for uploads, the two page
#: budgets for the screens the rollup story owns, the load they are sized for, and the
#: memory bound an upload must stay under (a ratio, not an absolute, with a floor so a
#: shrunk probe cannot blow the ratio on incidental allocations).
HANDLER_BUDGET_SECONDS = 1.0


REVIEW_QUEUE_BUDGET_SECONDS = 2.0


ROLLUP_BUDGET_SECONDS = 3.0


REFERENCE_COHORT_SIZE = 350


UPLOAD_RSS_RATIO_CEILING = 0.25


MEMORY_FLOOR_BYTES = 8 * 1024 * 1024


# --- the four observability metrics (design §3.19, Observability line) --------------------------------

RENDER_TIME_METRIC = "page_render_time"


CONTROL_ACTION_METRIC = "control_actions_by_type"


SKIP_RATE_METRIC = "skip_rate_per_setup_step"


REVIEW_BUDGET_METRIC = "review_budget_requested_vs_used"


OBSERVABILITY_METRICS = frozenset(
    {RENDER_TIME_METRIC, CONTROL_ACTION_METRIC, SKIP_RATE_METRIC, REVIEW_BUDGET_METRIC}
)
