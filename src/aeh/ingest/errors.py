"""The errors M-INGEST raises for caller and data errors (gate outcomes are not errors)."""

from __future__ import annotations


class IngestError(Exception):
    """An ingestion failure caused by the caller or the data, not a gate outcome.

    Gate failures (V0-V4) are routing decisions recorded on the submission — never
    exceptions. This error is for the module's own refused operations: an unknown
    document kind, a document that does not exist, a build that changed mid-document.
    """


class IngestOrderError(IngestError):
    """The page order could not be determined (FR-INGEST-31): no order given by the operator, no
    printed page numbers, no fiducial markers, and no unambiguous file names.

    The module NEVER guesses — a wrongly-ordered submission is graded confidently
    against the wrong questions. The caller routes this to the operator, who re-ingests
    with an explicit order."""


class IngestGapError(IngestError):
    """The printed page sequence has gaps (FR-INGEST-09). The missing page numbers are named, so
    the operator knows exactly what to rescan."""


class IngestDuplicateError(IngestError):
    """Two pages' transcripts are more similar than the configured threshold (FR-INGEST-08). They
    are shown for confirmation and never joined, because assembling a page twice would count a
    student's answer twice. The operator resolves the named pairs and re-ingests."""


class IngestCohortBreakerTripped(IngestError):
    """The V4 cohort breaker has tripped (FR-INGEST-28): too many of the cohort's papers look like
    a different assessment, so ingestion stops and run start stays withheld until a person clears
    it. Raised before any file is read or model called. This is the one gate outcome that is an
    exception, because it stops the whole cohort, not one submission."""


class IngestSanitizeError(IngestError):
    """A source PDF was refused during sanitization (FR-INGEST-33, FR-INGEST-34, NFR-INGEST-08): it
    has active content that cannot be removed, crossed a resource limit, or could not be parsed.
    For a submission, the ladder records a V0 quarantine; for a setup document, the teacher sees
    the error (FR-INGEST-32). Any exception inside the sanitizer is wrapped in this type, so every
    failure ends in refusal."""


class IngestTranscriptionError(IngestError):
    """A page's transcription failed on every allowed attempt (NFR-INGEST-02), so the page has no
    transcript. The submission is quarantined, never the run, and the rest of the cohort continues.
    It carries the log of attempts. A sanitizer refusal never reaches this path; it is raised
    before any model call and is not retried (FR-INGEST-33)."""

    def __init__(self, message: str, attempts: list[dict] | None = None):
        super().__init__(message)
        #: The per-attempt strike log: page, attempt number, error — and
        #: `outcome: recovered` on the strike a later attempt survived.
        self.attempts: list[dict] = list(attempts or [])
