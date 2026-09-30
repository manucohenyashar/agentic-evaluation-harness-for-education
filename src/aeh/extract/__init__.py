"""M-EXTRACT: finds the evidence spans for one criterion in one submission (design §3.8).

A model reads the submission's canonical document and returns the passages that bear on a
criterion. Each passage is stored as a byte-offset span into the document, so later stages
(the integrity gate, the judges) can check that the text really is there. Extraction never
sees any judge's verdict; its output is the same whichever judges run later.

Files:
    schema.py    migrations for the evidence table, and the SQL statements
    settings.py  prompt version, the second-family extractor option and its knobs
    records.py   the request, span and result types
    assembly.py  building an extraction request from a work unit, and reading the document
    prompt.py    rendering the extraction prompt
    spans.py     turning the model's reply into spans, checked against the document
    worker.py    `ExtractionWorker`, which processes one leased unit
    metrics.py   per-criterion extraction metrics for a run
"""

from __future__ import annotations

from aeh.ingest import INGEST_STATEMENTS

from .schema import EXTRACT_STATEMENTS
from .settings import (
    DEFAULT_EVIDENCE_TYPE,
    EXTRACTION_PROMPT_TEMPLATE_VERSION,
    SECOND_FAMILY_ENV,
    second_family_model,
    SECOND_FAMILY_MODEL_ENV,
)
from .records import (
    Criterion,
    DependencyEvidence,
    ExtractionRequest,
    ExtractionResult,
    ExtractionSpan,
    Question,
    SubmissionRef,
)
from .assembly import assemble_request, document_bytes
from .prompt import PROMPT_FIELD_NAMES, prompt_fields
from .spans import parse_spans
from .worker import ExtractionWorker
from .metrics import extraction_metrics, ExtractionMetrics


__all__ = [
    "ExtractionMetrics",
    "extraction_metrics",
    "EXTRACTION_PROMPT_TEMPLATE_VERSION",
    "EXTRACT_STATEMENTS",
    "Criterion",
    "DependencyEvidence",
    "ExtractionRequest",
    "ExtractionResult",
    "ExtractionSpan",
    "ExtractionWorker",
    "PROMPT_FIELD_NAMES",
    "Question",
    "SubmissionRef",
    "assemble_request",
    "parse_spans",
    "prompt_fields",
    "second_family_model",
]
