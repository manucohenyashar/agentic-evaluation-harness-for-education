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


#: Seam 3: the token budget one model call is priced at before it is dispatched, so a run with a
#: cost ceiling (`dev-ci`, `cloud-hosted`) can check a unit against it (`FR-ORCH-15`). The
#: defaults lean high on purpose: a judge on a reasoning model spends a few hundred output
#: tokens thinking before it answers, and an optimistic estimate is a ceiling that trips late.
#: What a claim adds to the run's spend IS this estimate, priced at the provider's declared
#: per-token rates (`M-ORCH` charges at claim time; only synthesis is charged its measured cost,
#: #596). So the ceiling bounds estimated spend: at OpenRouter's placeholder rates one unit is
#: 0.007, well above what a small model really costs, and the ceiling trips early, never late.
UNIT_TOKENS_IN_ENV = "HARNESS_PIPE_UNIT_TOKENS_IN"


UNIT_TOKENS_IN_DEFAULT = 4000


UNIT_TOKENS_OUT_ENV = "HARNESS_PIPE_UNIT_TOKENS_OUT"


UNIT_TOKENS_OUT_DEFAULT = 1500


# --- the reading job (FR-CONSOLE-97) --------------------------------------------------------

#: The most one reading job may spend between its start (or a Resume) and its pause. Unset, the
#: run cost ceiling the profile resolves (`cost_ceiling`) applies; a profile with no ceiling
#: reads uncapped. Read at each check, so a raised limit takes effect at once.
READ_COST_CEILING_ENV = "HARNESS_READ_COST_CEILING"


#: Seam 3: the token budget one page read is priced at for the Papers confirmation's estimate
#: (pages x the transcriber's per-page `estimate_cost`). A page image plus the reading
#: instruction is a couple of thousand input tokens; a page's transcript rarely more than one.
READ_TOKENS_IN_PER_PAGE_ENV = "HARNESS_READ_TOKENS_IN_PER_PAGE"


READ_TOKENS_IN_PER_PAGE_DEFAULT = 2000


READ_TOKENS_OUT_PER_PAGE_ENV = "HARNESS_READ_TOKENS_OUT_PER_PAGE"


READ_TOKENS_OUT_PER_PAGE_DEFAULT = 1000


def _decimal_knob(name: str) -> "Decimal | None":
    """Read one non-negative decimal knob at call time; unset or blank is `None`. An invalid
    value raises naming the knob, before anything is sent."""
    from decimal import Decimal, InvalidOperation

    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as error:
        raise ValueError(f"{name}={raw!r} is not a number.") from error
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name}={raw!r} must be a number of zero or more.")
    return value
