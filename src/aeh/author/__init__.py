"""M-AUTHOR: the package-authoring workflow (design delta §3.1, `docs/design/package_authoring_design_delta.md`).

A teacher's PDFs in; a draft package spec (`<package>.package.draft.toml`) and an authoring
report (`<package>.authoring-report.md`) out — best-effort, with every field the documents
do not determine left as a named `<<PLACEHOLDER: ...>>` sentinel for the review walk. No
store, no published version: the draft's lifecycle is files only (ADR-43), and `aeh package
build --spec` is the downstream consumer.

The workflow runs headless from code (seam 1), makes every model call through `M-PROV`
(seam 2), reads its environment knobs per invocation (seam 3:
`HARNESS_AUTHOR_ATTEMPTS`, `HARNESS_AUTHOR_TIMEOUT_S`, `HARNESS_AUTHOR_TRANSCRIBE`,
`HARNESS_AUTHOR_DOC_MAX_BYTES`), and surfaces what each step did next to the status — in
the report and in `DraftResult` (seam 4).

Story: #690 (TS-155). Review is #696's; the CLI registration is #695's; the console census
is #700's; retry/recreate/answer carry-over landed with #697 (`carryover.py`); document
intake — the one normalization step into `NormalizedDocument` — landed with #754
(`intake.py`).
"""

from __future__ import annotations

from aeh.conf import ConfigurationError, ModelRef  # re-exports the chain vocabulary
from aeh.prov import InferenceProvider

from .errors import AuthoringInputError, DocumentRefusedError, OverwriteRefusedError
from .extraction import AUTHOR_TRANSCRIBE_TEMPLATE_V, AuthoringDocument, PageText, \
    TRANSCRIBE_MIN_TEXT_LAYER_CHARS
from .grades import AUTHOR_GRADES_TEMPLATE_V
from .intake import check_document, document_text, log_intake, normalize_document, \
    normalize_documents, normalized_from_authoring
from .inventory import AUTHOR_INVENTORY_TEMPLATE_V
from .rubric import AUTHOR_RUBRIC_TEMPLATE_V
from .service import PROMPT_VERSIONS, AuthoringService, authoring_service
from .settings import (
    ATTEMPTS_ENV,
    DEFAULT_ATTEMPTS,
    DEFAULT_DOC_MAX_BYTES,
    DEFAULT_TIMEOUT_S,
    DEFAULT_TRANSCRIBE,
    DOC_MAX_BYTES_ENV,
    TIMEOUT_ENV,
    TRANSCRIBE_ENV,
    AuthoringSettings,
)
from .types import (
    Block,
    BlockKind,
    DraftResult,
    IntakeStats,
    IntakeWarning,
    IntakeWarningCode,
    ItemStatus,
    NormalizedDocument,
    ReviewAnswer,
    ReviewResult,
    SourceFormat,
    StepId,
    StepOutcome,
)
from .validation import DraftIssue, validate_draft

__all__ = [
    # the §3.1 surface (the names the tests construct through)
    "AuthoringService",
    "authoring_service",
    "validate_draft",
    "DraftResult",
    "ReviewResult",
    "ReviewAnswer",
    "DraftIssue",
    "StepOutcome",
    "ItemStatus",
    "AuthoringSettings",
    # the §3.1 data-structure aliases
    "StepId",
    # the module's own errors
    "AuthoringInputError",
    "OverwriteRefusedError",
    # the intake tier (FR-AUTHOR-24…28, #754): the representation and the step that
    # produces it
    "NormalizedDocument",
    "Block",
    "IntakeWarning",
    "IntakeStats",
    "SourceFormat",
    "BlockKind",
    "IntakeWarningCode",
    "DocumentRefusedError",
    "normalize_document",
    "normalize_documents",
    "check_document",
    "document_text",
    "normalized_from_authoring",
    "log_intake",
    # the knob vocabulary (seam 3)
    "ATTEMPTS_ENV",
    "TIMEOUT_ENV",
    "TRANSCRIBE_ENV",
    "DOC_MAX_BYTES_ENV",
    "DEFAULT_ATTEMPTS",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_TRANSCRIBE",
    "DEFAULT_DOC_MAX_BYTES",
    # the versioned prompts (FR-AUTHOR-20) — a bump invalidates the affected recordings
    "AUTHOR_INVENTORY_TEMPLATE_V",
    "AUTHOR_RUBRIC_TEMPLATE_V",
    "AUTHOR_GRADES_TEMPLATE_V",
    "AUTHOR_TRANSCRIBE_TEMPLATE_V",
    "TRANSCRIBE_MIN_TEXT_LAYER_CHARS",
    "PROMPT_VERSIONS",
    # the extraction records (the report's Documents section speaks in these)
    "AuthoringDocument",
    "PageText",
    # the chain vocabulary, re-exported for callers assembling a service
    "ModelRef",
    "InferenceProvider",
    "ConfigurationError",
]