"""M-SYNTH: writes the feedback narrative for each graded submission (design §3.12).

Synthesis runs in two levels. Level 1 (L1) writes one short narrative per question from that
question's verdicts and evidence. Level 2 (L2) writes one narrative for the whole test from the
L1 narratives only. A narrative must never state a score of its own, so every model reply is
checked against the score-claim patterns and flagged when it matches (FR-SYNTH-03). The one
exemption is a paper whose criteria are all deterministic (#523): its narrative is a template
over the scored multiple-choice results with no model call, so no reply exists to check — the
figures it states are the stored scores themselves.

Files:
    schema.py        the `narrative` table migration and the SQL statements this module runs
    settings.py      prompt version, output cap, sample rate and their environment knobs
    score_claims.py  the score-claim patterns and the `has_score_claim` check
    records.py       the request, result and report types
    prompts.py       building the prompt and parsing the model's reply
    mc_narrative.py  template sentences for a multiple-choice-only paper (no model call)
    worker.py        `SynthesisWorker`, which runs both levels for one submission

Detailed design notes (the full original module description): `docs/code-notes/synth.md`.
"""

from __future__ import annotations

from .schema import SYNTH_STATEMENTS
from .settings import (
    LEVEL_L1,
    LEVEL_L2,
    LOGGER,
    MAX_ATTEMPTS_SYNTH_ENV,
    MAX_OUTPUT_TOKENS_ENV,
    SAMPLE_RATE_ENV,
    SCORE_CLAIM_FLAG,
    SYNTH_MAX_OUTPUT_TOKENS,
    SYNTH_PROMPT_TEMPLATE_V,
    SYNTH_SAMPLE_RATE,
    TEST_SENTINEL,
)
from .score_claims import has_score_claim, SYNTH_SCORE_CLAIM_PATTERNS
from .records import (
    CriterionVerdict,
    L1Request,
    L2Request,
    narrative_work_id,
    SynthesisReport,
    SynthesisResult,
)
from .prompts import parse_narrative, prompt_for
from .worker import SynthesisWorker, synthesize


__all__ = [
    "LEVEL_L1",
    "LEVEL_L2",
    "MAX_ATTEMPTS_SYNTH_ENV",
    "MAX_OUTPUT_TOKENS_ENV",
    "SAMPLE_RATE_ENV",
    "SCORE_CLAIM_FLAG",
    "SYNTH_MAX_OUTPUT_TOKENS",
    "SYNTH_PROMPT_TEMPLATE_V",
    "SYNTH_SAMPLE_RATE",
    "SYNTH_SCORE_CLAIM_PATTERNS",
    "SYNTH_STATEMENTS",
    "L1Request",
    "L2Request",
    "CriterionVerdict",
    "SynthesisResult",
    "SynthesisReport",
    "SynthesisWorker",
    "has_score_claim",
    "narrative_work_id",
    "parse_narrative",
    "prompt_for",
    "synthesize",
    "TEST_SENTINEL",
]
