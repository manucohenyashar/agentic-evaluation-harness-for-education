"""The errors M-INGEST raises for caller and data errors (gate outcomes are not errors)."""

from __future__ import annotations


class IngestError(Exception):
    """An ingestion failure that is a caller or data error, not a gate outcome.

    Gate failures (V0-V4) are routing decisions recorded on the submission — never
    exceptions. This error is for the module's own refused operations: an unknown
    document kind, a document that does not exist, a build that changed mid-document.
    """


class IngestOrderError(IngestError):
    """Assembly order could not be determined (`FR-INGEST-31`): no operator-stated
    order, no printed page numbers, no fiducial markers, no unambiguous filenames.

    The module NEVER guesses — a wrongly-ordered submission is graded confidently
    against the wrong questions. The caller routes this to the operator, who re-ingests
    with an explicit order."""


class IngestGapError(IngestError):
    """A gap in the printed page sequence (`FR-INGEST-09`): the missing positions are
    NAMED, so the operator knows exactly which pages to rescan rather than that
    "something is missing"."""


class IngestDuplicateError(IngestError):
    """Two pages whose TRANSCRIPTS are similar above the configured threshold
    (`FR-INGEST-08`): surfaced for confirmation, NEVER concatenated — a duplicated page
    silently assembled twice would double-count a student's answer. The pairs are
    named; the operator resolves and re-ingests. (The FR's disjunction — page-image OR
    transcript similarity — is satisfied by the transcript channel; the image-
    similarity channel is a deliberate deferral to the acceptance run.)"""


class IngestCohortBreakerTripped(IngestError):
    """The V4 cohort circuit breaker is tripped (`FR-INGEST-28`): the cohort's
    combined `mismatch`-plus-`uncertain` rate reached the configured threshold over at
    least the configured minimum, ingestion HALTS, and run start stays withheld until
    a human clears the breaker. Raised before any blob read or model call — a cohort
    ingesting the wrong assessment's package must not keep paying for transcription
    while the finding waits. This is the one gate outcome that IS an exception: it
    halts the cohort, not the submission (NFR-INGEST-02's unit-level quarantine is
    recorded on the row; this is cohort-level and refuses the work)."""


class IngestSanitizeError(IngestError):
    """A sanitization refusal (`FR-INGEST-33`/`FR-INGEST-34`/`NFR-INGEST-08`): the
    source carries active content that cannot be removed, crossed a resource
    ceiling, or could not be parsed for sanitization at all — and the artifact is
    therefore refused, never processed. In the submission path the ladder catches
    this and records the V0 quarantine; in the setup-artifact path it propagates to
    the uploading teacher (`FR-INGEST-32`). Any exception raised inside the
    sanitizer — declared or not — is wrapped into this type, so every failure mode
    resolves to refusal rather than to processing."""


class IngestTranscriptionError(IngestError):
    """A page's transcription failed on every attempt of the strike limit
    (`NFR-INGEST-02`, #220): the model channel never produced a reading, so the
    page has NO transcript — the unit fails, never the run. Carries the
    per-attempt log (the strike count is observable, CLAUDE.md seam 4); the
    submission path catches it and records an honest quarantine with the gate
    columns marked, and the cohort's remaining submissions continue. A
    sanitizer refusal never reaches this path — that refusal is raised before
    any model call and keeps its own no-retry semantics (`FR-INGEST-33`, #42)."""

    def __init__(self, message: str, attempts: list[dict] | None = None):
        super().__init__(message)
        #: The per-attempt strike log: page, attempt number, error — and
        #: `outcome: recovered` on the strike a later attempt survived.
        self.attempts: list[dict] = list(attempts or [])
