"""M-INGEST: the only way from a scanned PDF to text the rest of the system reads (design §3.5).

Each source PDF is first sanitized: active content is stripped and size limits (pages,
decompressed bytes, image pixels, embedded objects, wall-clock time) are enforced. Pages are
rasterized and transcribed by a vision model into region-marked Markdown. The pages are put in
printed order and assembled into one canonical document, which is stored and never edited in
place; a correction writes a new revision.

A submission then passes a validation ladder (V0 to V4): resolution and blank-page checks,
page order and gaps, duplicates, and finally a match against the assessment it claims to be.
Text that came from the student is wrapped in untrusted-content markers so no later prompt can
mistake it for instructions. Nothing outside this package imports a PDF or image library.

Files:
    settings.py      document kinds, limits and thresholds, each with its environment knob
    markup.py        the region and untrusted-content markers, and the transcription prompt
    descriptions.py  second descriptions of graphics and their comparison
    errors.py        the errors this package raises
    rasterizer.py    turning a PDF page into an image (`PdfiumRasterizer`)
    sanitizer.py     neutralizing and bounding a source PDF (`PypdfSanitizer`)
    residency.py     the vision model's residency slot
    schema.py        migrations and the SQL statements
    uploads.py       recording uploaded scan parts
    assembly.py      assembling page transcripts into one canonical Markdown document
    records.py       reports, clusters, replacements and run aggregates
    regions.py       parsing a page transcript into regions, and marking untrusted text
    documents.py     ingesting one document: sanitize, rasterize, transcribe, store
    source_checks.py the per-source checks: sanitization, raster limits, deadlines
    revision.py      applying a correction as a new document revision
    clusters.py      cohort-wide unresolved tokens and their resolution
    submissions.py   ingesting one submission through the validation ladder
    assessment_match.py  V4: does the paper match the assessment it claims to be?
    aggregates.py    the cohort's run-level ingestion signals
    ingestor.py      `Ingestor`, the gateway itself

Detailed design notes (the full original module description): `docs/code-notes/ingest.md`.
"""

from __future__ import annotations

import time

from .settings import (
    BLANK_TOLERANCE_ENV,
    DEFAULT_BLANK_TOLERANCE,
    DEFAULT_DIVERGENCE_HALT,
    DEFAULT_DPI,
    DEFAULT_DUPLICATE_THRESHOLD,
    DEFAULT_EVALUATIVE_RETRIES,
    DEFAULT_MAX_DECOMPRESSED_BYTES,
    DEFAULT_MAX_EMBEDDED_OBJECTS,
    DEFAULT_MAX_FILE_SECONDS,
    DEFAULT_MAX_IMAGE_PIXELS,
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_OCR_CONF_FLOOR,
    DEFAULT_RESOLUTION_FLOOR,
    DEFAULT_RETAIN_PAGE_RASTERS,
    DEFAULT_STRIP_ACTIVE_CONTENT,
    DEFAULT_TRANSCRIPTION_ATTEMPTS,
    DEFAULT_V4_BREAKER_MIN,
    DEFAULT_V4_BREAKER_RATE,
    DEFAULT_V4_SEMANTIC_FLOOR,
    DIVERGENCE_HALT_ENV,
    DOCUMENT_KINDS,
    DocumentId,
    DocumentKind,
    DPI_ENV,
    DUPLICATE_ENV,
    ELEMENT_KINDS,
    ELEMENT_REQUIRED_FIELDS,
    EVALUATIVE_MATCH_ENV,
    EVALUATIVE_RETRIES_ENV,
    EVALUATIVE_TERMS,
    GATE_NOT_REACHED,
    INGEST_STATUSES,
    LOGGER,
    MAX_DECOMPRESSED_BYTES_ENV,
    MAX_EMBEDDED_OBJECTS_ENV,
    MAX_FILE_SECONDS_ENV,
    MAX_IMAGE_PIXELS_ENV,
    MAX_PAGES_ENV,
    MAX_TOKENS_ENV,
    OCR_CONF_FLOOR_ENV,
    REGION_KINDS,
    RESOLUTION_FLOOR_ENV,
    RETAIN_PAGE_RASTERS_ENV,
    STRIP_ACTIVE_CONTENT_ENV,
    TRANSCRIPTION_ATTEMPTS_ENV,
    TRANSCRIPTION_PROMPT_VERSION,
    V4_BREAKER_MIN_ENV,
    V4_BREAKER_RATE_ENV,
    V4_MATCH_OUTCOMES,
    V4_SEMANTIC_FLOOR_ENV,
)
from .markup import (
    REGION_CLOSE,
    REGION_OPEN,
    STRUCK_CLOSE,
    STRUCK_OPEN,
    SUPERSEDED_PREFIX,
    TRANSCRIPTION_PROMPT,
    UNTRUSTED_CLOSE,
    UNTRUSTED_OPEN,
)
from .descriptions import (
    DEFAULT_SECOND_DESCRIPTION_MIN_SIMILARITY,
    description_disagreement,
    description_integrity_signals,
    DescriptionIntegritySignal,
    load_bearing_facts,
    SECOND_DESCRIPTION_MIN_SIMILARITY_ENV,
    second_description_pass,
    SECOND_DESCRIPTION_PROMPT,
    SECOND_DESCRIPTION_PROMPT_VERSION,
)
from .errors import (
    IngestCohortBreakerTripped,
    IngestDuplicateError,
    IngestError,
    IngestGapError,
    IngestOrderError,
    IngestSanitizeError,
    IngestTranscriptionError,
)
from .rasterizer import PageImage, PdfiumRasterizer, Rasterizer
from .sanitizer import PdfSanitizer, PypdfSanitizer, SanitizeResult
from .residency import ResidencySlot
from .schema import INGEST_STATEMENTS
from .uploads import record_upload_part, upload_parts_in_order
from .assembly import assemble_canonical_markdown, AssembledDocument
from .records import (
    ClusterResolution,
    GATE_COLUMNS_BY_GATE,
    GATE_FAIL_VALUES,
    GATE_PASS_VALUES,
    IngestReport,
    PageReplacement,
    RunAggregates,
    TokenCluster,
)
from .regions import _evaluative_offences, _fence_untrusted_content, _mark_untrusted_content
from .documents import DocumentIngestionMixin
from .source_checks import SourceChecksMixin
from .revision import RevisionMixin
from .clusters import TokenClustersMixin
from .submissions import SubmissionIngestionMixin
from .assessment_match import AssessmentMatchMixin
from .aggregates import RunAggregatesMixin
from .ingestor import Ingestor


__all__ = [
    "AssembledDocument",
    "DOCUMENT_KINDS",
    "EVALUATIVE_TERMS",
    "ELEMENT_KINDS",
    "DocumentId",
    "DocumentKind",
    "IngestCohortBreakerTripped",
    "IngestDuplicateError",
    "IngestError",
    "IngestSanitizeError",
    "IngestTranscriptionError",
    "IngestGapError",
    "IngestOrderError",
    "IngestReport",
    "RunAggregates",
    "GATE_NOT_REACHED",
    "GATE_PASS_VALUES",
    "GATE_FAIL_VALUES",
    "GATE_COLUMNS_BY_GATE",
    "V4_MATCH_OUTCOMES",
    "INGEST_STATUSES",
    "Ingestor",
    "TokenCluster",
    "PageImage",
    "PageReplacement",
    "PdfSanitizer",
    "PdfiumRasterizer",
    "PypdfSanitizer",
    "REGION_KINDS",
    "ResidencySlot",
    "Rasterizer",
    "SanitizeResult",
    "TRANSCRIPTION_PROMPT_VERSION",
    "assemble_canonical_markdown",
]
