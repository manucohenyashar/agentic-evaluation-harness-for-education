"""Synthesis settings: the prompt version, the output cap, the sample rate and their knobs."""

from __future__ import annotations

import logging
import os


LOGGER = logging.getLogger("aeh.synth")


# --- configuration (CT-SYNTH-11, the four seams) --------------------------------------------------

#: The pinned synthesis prompt template version (`CT-SYNTH-11`: pinned, a `work_id`
#: input — the run row's `prompt_template_v` carries it into the orchestration hash;
#: this module pins the value and renders by it).
SYNTH_PROMPT_TEMPLATE_V = "synth-prompt/1"


#: The output cap per synthesis call (`CT-SYNTH-09`: the call budget is bounded by
#: `SYNTH_MAX_OUTPUT_TOKENS`). The production default; `HARNESS_SYNTH_MAX_OUTPUT_TOKENS`
#: overrides at call time.
SYNTH_MAX_OUTPUT_TOKENS = 512


#: The quality-sample fraction (`NFR-SYNTH-01`: measured on a sample every
#: administration). `HARNESS_SYNTH_SAMPLE_RATE` overrides at call time.
SYNTH_SAMPLE_RATE = 0.25


MAX_ATTEMPTS_SYNTH_ENV = "HARNESS_SYNTH_MAX_ATTEMPTS"


MAX_OUTPUT_TOKENS_ENV = "HARNESS_SYNTH_MAX_OUTPUT_TOKENS"


SAMPLE_RATE_ENV = "HARNESS_SYNTH_SAMPLE_RATE"


LEVEL_L1 = "l1_question"


LEVEL_L2 = "l2_test"


TEST_SENTINEL = "__test__"


SCORE_CLAIM_FLAG = "score_claim_flag"


def _env_float(name: str, default: float) -> float:
    """Read a float knob at call time. An unset knob gives the default; a value that does not parse
    is refused rather than guessed."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not a number — refused, not guessed") from None
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name}={raw!r} is not a fraction of the stored rows — refused")
    return value
