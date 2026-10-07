"""M-JUDGE: scores one criterion of one submission with a model, in isolation (design §3.10).

A judge sees only a fixed whitelist of fields: the criterion, its declared bands and worked
examples, the question, and the submission's text with the evidence spans already extracted.
Student names are replaced by the pseudonym before anything leaves the process. The reply must
pick one declared band, cite evidence spans that exist byte-for-byte in the stored document,
and give an assessment that points at the evidence rather than free praise or criticism.

Some units can instead be answered by the decision engine (Jev). It gets a request derived
from the same whitelist, and its answer is kept only when its confidence passes the gate;
otherwise the unit falls back to the model judge.

Files:
    schema.py           migrations for the verdict and metrics tables, and the SQL statements
    settings.py         prompt version and the environment knobs (attempts, temperature, seeds)
    errors.py           the errors this package raises
    request.py          `ScoringRequest`: the whitelisted fields and the isolation check
    results.py          `ScoringResult`, the stored verdict, and `verdicts_for`
    prompt.py           rendering the scoring prompt in its fixed field order
    assembly.py         assembling a request from a work unit (`assemble`, pseudonymization)
    replies.py          parsing a judge reply and verifying its cited evidence
    decision_engine.py  the Jev path: eligibility, the request, the confidence gate
    worker.py           `ScoringWorker`, which judges one leased unit and stores the verdict
    metrics.py          the decision-engine outcome metrics for a run

Detailed design notes (the full original module description): `docs/code-notes/judge.md`.
"""

from __future__ import annotations

from aeh.orch import JUDGE_DECISION_TEMPLATE_V, ORCH_MAX_ATTEMPTS, WorkUnit

from .schema import JUDGE_STATEMENTS
from .settings import (
    ASSESSMENT_AMENDED,
    ASSESSMENT_RETRIES_DEFAULT,
    ASSESSMENT_RETRIES_ENV,
    _EXEMPLAR_SEED_DEFAULT,
    EXEMPLAR_SEED_ENV,
    JUDGE_PROMPT_TEMPLATE_V,
    JUDGE_TEMPERATURE,
    MAX_ATTEMPTS_ENV,
    MAX_OUTPUT_TOKENS_ENV,
    TEMPERATURE_ENV,
)
from .errors import CompositeUnitError, IsolationViolation, JudgmentError, ProseAssessmentError
from .request import (
    assert_isolated,
    BandView,
    CriterionView,
    DependencyEvidence,
    ExemplarView,
    QuestionView,
    ScoringRequest,
    SubmissionView,
)
from .results import ScoringResult, StoredVerdict, verdicts_for
from .prompt import PROMPT_FIELD_NAMES, prompt_fields, REPLY_FIELDS
from .assembly import assemble, assemble_prompt, _canonical_document_bytes, _evidence_spans
from .replies import (
    _ASSESSMENT_AMENDMENT_FIELD,
    _prose_only,
    _refuse_unverified_citations,
    _verdict_of,
)
from .decision_engine import (
    Accepted,
    BelowGate,
    decision_eligibility,
    DECISION_ENGINE_INVENTORY,
    DECISION_FIELD_NAMES,
    decision_fields,
    decision_request,
    ELIGIBILITY_REASONS,
    Eligible,
    gate_decision,
    Ineligible,
    is_decision_seat,
    scan_decision_request,
)
from .worker import ScoringWorker
from .metrics import (
    ALERT_MIN_PRESCREENS_DEFAULT,
    ALERT_MIN_PRESCREENS_ENV,
    decision_engine_metrics,
    DecisionEngineMetrics,
    FALLBACK_ALERT_RATE_DEFAULT,
    FALLBACK_ALERT_RATE_ENV,
)


__all__ = [
    "DecisionEngineMetrics",
    "decision_engine_metrics",
    "Accepted",
    "BelowGate",
    "DECISION_ENGINE_INVENTORY",
    "DECISION_FIELD_NAMES",
    "ELIGIBILITY_REASONS",
    "Eligible",
    "Ineligible",
    "JUDGE_DECISION_TEMPLATE_V",
    "decision_eligibility",
    "decision_fields",
    "decision_request",
    "gate_decision",
    "is_decision_seat",
    "scan_decision_request",
    "ASSESSMENT_AMENDED",
    "ASSESSMENT_RETRIES_DEFAULT",
    "ASSESSMENT_RETRIES_ENV",
    "BandView",
    "CriterionView",
    "DependencyEvidence",
    "ExemplarView",
    "IsolationViolation",
    "JUDGE_PROMPT_TEMPLATE_V",
    "JUDGE_STATEMENTS",
    "JudgmentError",
    "CompositeUnitError",
    "PROMPT_FIELD_NAMES",
    "ProseAssessmentError",
    "QuestionView",
    "REPLY_FIELDS",
    "ScoringRequest",
    "ScoringResult",
    "ScoringWorker",
    "StoredVerdict",
    "SubmissionView",
    "WorkUnit",
    "assemble",
    "assemble_prompt",
    "assert_isolated",
    "prompt_fields",
    "verdicts_for",
]
