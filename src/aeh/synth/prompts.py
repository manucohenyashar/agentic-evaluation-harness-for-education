"""Building the synthesis prompt and parsing the model's reply."""

from __future__ import annotations

import json

from aeh.prov import PromptPayload

from .settings import LEVEL_L1, LEVEL_L2, LOGGER, SYNTH_PROMPT_TEMPLATE_V
from .records import L1Request, L2Request


# --- the fixed prompts (FR-SYNTH-01, CT-PROV-05's order contract) ---------------------------------

_DIRECTIVE_L1 = (
    "You write the per-question feedback narrative for one student's submission. "
    "Read the question's criterion verdicts and the evidence below; compose prose "
    "that states what the student's own work shows, anchored to the criteria and "
    "paraphrasing the evidence. State no mark, no score, no band and no overall "
    "quality verdict: the narrative never grades. Reply as JSON with a 'narrative' "
    "text and a 'citations' list of the criterion ids the narrative anchors to."
)


_DIRECTIVE_L2 = (
    "You write the whole-test narrative for one student's submission, from the "
    "per-question narratives below and nothing else. Compose prose that draws the "
    "threads of those narratives together. State no mark, no score, no band and no "
    "overall quality verdict: the narrative never grades. Reply as JSON with a "
    "'narrative' text and a 'citations' list of criterion ids if any are named."
)


def prompt_for(request: L1Request | L2Request) -> PromptPayload:
    """The rendered prompt, in a fixed field order — the payload the provider boundary
    hashes. The level is visible in the fields: an L1 request carries its question's
    criteria, verdicts and evidence; an L2 request carries ONLY the syntheses, because
    that is all the type can hold."""
    if isinstance(request, L1Request):
        verdict_lines = "\n".join(
            f"criterion={v.criterion_id} judge={v.judge_id} band={v.band}"
            for v in request.verdicts
        )
        return PromptPayload(
            fields=(
                ("directive", _DIRECTIVE_L1),
                ("prompt_template_v", SYNTH_PROMPT_TEMPLATE_V),
                ("level", LEVEL_L1),
                ("question", request.question_id),
                ("criteria", ", ".join(request.criterion_ids)),
                ("verdicts", verdict_lines or "(no verdicts)"),
                ("evidence", "\n\n".join(request.evidence) or "(no evidence spans)"),
                ("submission", request.submission_id),
            )
        )
    if isinstance(request, L2Request):
        return PromptPayload(
            fields=(
                ("directive", _DIRECTIVE_L2),
                ("prompt_template_v", SYNTH_PROMPT_TEMPLATE_V),
                ("level", LEVEL_L2),
                ("syntheses", "\n\n".join(request.syntheses)),
                ("submission", request.submission_id),
            )
        )
    raise TypeError(
        f"prompt_for renders an L1Request or an L2Request, got {type(request).__name__}"
    )


# --- reply parsing (FR-SYNTH-04) ------------------------------------------------------------------


def parse_narrative(text: str) -> tuple[str, tuple[str, ...]]:
    """Parse the synthesis reply into `(narrative text, citations)`.

    The reply is a JSON object whose `narrative` is the prose and whose `citations`
    list the criterion ids the narrative anchors to (`FR-SYNTH-04`). A reply that is
    not that shape raises `ValueError` — one strike, never a half-parsed narrative."""
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as error:
        raise ValueError(f"synthesis reply is not JSON: {error}") from None
    if not isinstance(payload, dict) or "narrative" not in payload:
        raise ValueError("synthesis reply carries no 'narrative' member")
    narrative = payload["narrative"]
    if not isinstance(narrative, str) or not narrative.strip():
        raise ValueError("synthesis reply 'narrative' is not non-empty text")
    citations = payload.get("citations", ())
    if not isinstance(citations, (list, tuple)) or not all(
        isinstance(entry, str) for entry in citations
    ):
        raise ValueError("synthesis reply 'citations' must be a list of criterion ids")
    return narrative, tuple(citations)


# --- the reads ------------------------------------------------------------------------------------


def _payload_span_texts(payload: bytes) -> tuple[str, ...]:
    """The evidence texts a persisted span payload decodes to.

    The payload is `M-EXTRACT`'s evidence record (a JSON object of byte-offset spans
    into the canonical document); the span texts are what the L1 request reads.
    A payload that will not decode is logged and skipped — the narrative still anchors
    by citation, and `CT-SYNTH-08` says nothing here fails a grade."""
    try:
        record = json.loads(bytes(payload).decode("utf-8"))
        spans = record["spans"]
        return tuple(str(span["text"]) for span in spans if span.get("text"))
    except (KeyError, TypeError, ValueError) as error:
        LOGGER.error("evidence payload did not decode (%s) — spans skipped", error)
        return ()
