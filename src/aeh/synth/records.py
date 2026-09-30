"""The data passed into and out of synthesis: requests, results and the per-call report."""

from __future__ import annotations

import re
from dataclasses import dataclass


#: The naming-convention fallback for a criterion with no `question_id` on its package
#: row: the fixtures' `Q1C1` spelling groups by the leading `Q<n>`.
_QUESTION_CONVENTION = re.compile(r"\A(Q\d+)C")


def _question_of_criterion(question_id: str, criterion_id: str) -> str:
    """The question a criterion belongs to: the package's own mapping when it carries
    one, the naming convention otherwise, and nothing when neither does."""
    if question_id:
        return question_id
    matched = _QUESTION_CONVENTION.match(criterion_id)
    return matched.group(1) if matched else ""


def narrative_work_id(run_id: str, submission_id: str, level: str, question_id: str) -> str:
    """The deterministic work identity of one narrative row — the id a retried unit
    re-derives, so the conflict-on-duplicate is observable in the id itself."""
    return f"nar:{run_id}:{submission_id}:{level}:{question_id}"


# --- the request and result types (FR-SYNTH-01/02/05, NFR-SYNTH-03) -------------------------------


@dataclass(frozen=True)
class CriterionVerdict:
    """One criterion's verdict as an L1 request carries it — the judge's band, and
    nothing numeric: there is no score field to carry a per-judge number through."""

    criterion_id: str
    judge_id: str
    band: str


@dataclass(frozen=True)
class L1Request:
    """The per-question request: ONE question's criteria, verdicts and evidence for
    ONE submission (`FR-SYNTH-01`, `FR-SYNTH-05` — exactly one `submission_id`)."""

    run_id: str
    submission_id: str
    question_id: str
    criterion_ids: tuple[str, ...]
    verdicts: tuple[CriterionVerdict, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class L2Request:
    """The test-level request: the L1 syntheses and NOTHING else (`NFR-SYNTH-03`).

    The boundary is the type itself — there is no field here that could carry a raw
    verdict (`CT-SYNTH-02`'s construction probe proves a smuggled one is refused), so
    the small model composing the test-level narrative cannot be handed the panel's
    verdicts no matter what a later change tries.
    """

    run_id: str
    submission_id: str
    syntheses: tuple[str, ...]


@dataclass(frozen=True)
class SynthesisResult:
    """One synthesized narrative — `{work_id, question_id, text}` at L1 and
    `{work_id, text}` at L2 (`CT-SYNTH-01`: the `question_id` is simply absent at L2).
    No numeric field exists to write a score into."""

    work_id: str
    question_id: str | None
    text: str


@dataclass(frozen=True)
class SynthesisReport:
    """The per-call report — the fourth seam's surface (`CT-SYNTH-12`).

    `model_calls` counts the provider calls actually made (retries included);
    `narratives` and `failures` are the failure rate's stored and failed counts;
    `rejected_score_claims` counts the model outputs the score-claim check rejected
    (re-requested, and terminal-flagged when the claim repeated), and
    `score_claim_rejection_rate` reads that count over the outputs actually parsed —
    `sample` is the quality sample drawn for `M-STATS` with `sample_size` attached;
    the two citation rates are `None` exactly when the sample is empty.
    """

    model_calls: int
    narratives: int
    failures: int
    rejected_score_claims: int
    synthesis_failure_rate: float
    score_claim_rejection_rate: float
    mean_narrative_length: float
    sample: tuple[str, ...]
    sample_size: int
    citation_validity_rate: float | None
    hallucinated_claim_rate: float | None
