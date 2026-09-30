"""`Ingestor`: the gateway, over one cohort's handle, the blob store and the provider."""

from __future__ import annotations

import base64
import os
from typing import Any, Sequence

from aeh.conf import ModelRef
from aeh.prov import Completion, InferenceProvider, PromptPayload, SamplingParams

from .settings import (
    _configured_max_tokens,
    DEFAULT_EVALUATIVE_RETRIES,
    DEFAULT_TRANSCRIPTION_ATTEMPTS,
    DocumentId,
    EVALUATIVE_RETRIES_ENV,
    LOGGER,
    TRANSCRIPTION_ATTEMPTS_ENV,
    TRANSCRIPTION_PROMPT_VERSION,
)
from .markup import TRANSCRIPTION_PROMPT
from .descriptions import _second_description_min_similarity
from .errors import IngestError, IngestTranscriptionError
from .rasterizer import PageImage, Rasterizer
from .sanitizer import PdfSanitizer
from .residency import ResidencySlot
from .schema import INGEST_STATEMENTS
from .documents import DocumentIngestionMixin
from .source_checks import SourceChecksMixin
from .revision import RevisionMixin
from .clusters import TokenClustersMixin
from .submissions import SubmissionIngestionMixin
from .assessment_match import AssessmentMatchMixin
from .aggregates import RunAggregatesMixin


class Ingestor(DocumentIngestionMixin, SourceChecksMixin, RevisionMixin, TokenClustersMixin, SubmissionIngestionMixin, AssessmentMatchMixin, RunAggregatesMixin):
    """Tier C's gateway: `Ingestor(cohort_handle, blobs, provider, model_ref, params,
    rasterizer)` — every model call through `M-PROV`, every PDF decode through the
    `Rasterizer` seam, one document row per logical document, one region row per
    region the model marked."""

    def __init__(
        self, handle: Any, blobs: Any, provider: InferenceProvider,
        model_ref: ModelRef, params: SamplingParams, rasterizer: Rasterizer,
        *, sanitizer: PdfSanitizer,
        residency: ResidencySlot | None = None,
        high_risk_criterion_ids: Sequence[str] = (),
        second_model_ref: ModelRef | None = None,
        package_catalog: Any | None = None,
        package_version: str | None = None,
    ) -> None:
        self._handle = handle
        # FR-INGEST-36's option source, bindable once at construction so an operator surface
        # that resolves many clusters names the package once; `resolve_cluster` still takes the
        # pair per call, and the call's own wins.
        self._package_catalog = package_catalog
        self._package_version = package_version
        self._blobs = blobs
        self._provider = provider
        self._model_ref = model_ref
        self._params = params
        self._rasterizer = rasterizer
        # FR-INGEST-33: there is no configuration that skips sanitization — the
        # argument is required, so a gateway cannot be built that rasterizes a
        # source it did not name a neutralizer for. (The fast tier passes a
        # scripted double, exactly as it does for the rasterizer and the
        # provider; the acceptance run passes PypdfSanitizer().)
        if not isinstance(sanitizer, PdfSanitizer):
            raise IngestError(
                "the gateway needs a PdfSanitizer (FR-INGEST-33): every source "
                "PDF is neutralized and bounded BEFORE any page is rasterized, "
                "and no default can silently stand in for that decision. Pass "
                "PypdfSanitizer() in production, a scripted double in tests.")
        self._sanitizer = sanitizer
        self._residency = residency
        # FR-INGEST-14 (Phase 2, #233): the register's contents are operator policy
        # (Q-12), so the high-risk list is injected. A list without a second model would
        # be a register nobody acts on, and a second model of the SAME family (the
        # build/provider pair, `aeh.extract`'s disclosed reading — `ModelRef` has no
        # family field) is not a second opinion: both refuse at construction.
        high_risk = tuple(str(item) for item in high_risk_criterion_ids)
        if high_risk and second_model_ref is None:
            raise IngestError(
                "high_risk_criterion_ids were given without a second_model_ref: the "
                "FR-INGEST-14 second description needs a different-family model, and a "
                "register with nobody to act on it would read as a pass that happened.")
        if second_model_ref is not None and (
                (second_model_ref.provider, second_model_ref.build_id)
                == (model_ref.provider, model_ref.build_id)):
            raise IngestError(
                "second_model_ref repeats the transcriber's provider and build: a second "
                "call to the same build is not a second description (FR-INGEST-14).")
        if high_risk:
            # A malformed floor is a configuration mistake: refused here, not later
            # as a quarantine that would blame the scan.
            _second_description_min_similarity()
        self._high_risk: tuple[str, ...] = high_risk
        self._second_model_ref: ModelRef | None = second_model_ref
        # The cohort whose file this handle opens — the clustering's scope is the
        # cohort, and one cohort file IS one cohort.
        self._cohort_id = "this-cohort"

    @staticmethod
    def _configured_retries() -> int:
        raw = os.environ.get(EVALUATIVE_RETRIES_ENV)
        if not raw:
            return DEFAULT_EVALUATIVE_RETRIES
        try:
            return int(raw)
        except ValueError as error:
            raise IngestError(
                f"{EVALUATIVE_RETRIES_ENV}={raw!r} is not an integer.") from error

    @staticmethod
    def _configured_transcription_attempts() -> int:
        """The strike limit for one page's transcription (`NFR-INGEST-02`, #220),
        read AT CALL TIME so a slower test box can tune it without a code change
        (CLAUDE.md seam 3). At least one attempt: zero would quarantine a page
        the model was never asked to read."""
        raw = os.environ.get(TRANSCRIPTION_ATTEMPTS_ENV)
        if not raw:
            return DEFAULT_TRANSCRIPTION_ATTEMPTS
        try:
            attempts = int(raw)
        except ValueError as error:
            raise IngestError(
                f"{TRANSCRIPTION_ATTEMPTS_ENV}={raw!r} is not an integer."
            ) from error
        if attempts < 1:
            raise IngestError(
                f"{TRANSCRIPTION_ATTEMPTS_ENV}={attempts} is below 1 — a page is "
                "attempted at least once before it strikes out.")
        return attempts

    @staticmethod
    def _configured_float(env: str, default: float) -> float:
        raw = os.environ.get(env)
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError as error:
            raise IngestError(f"{env}={raw!r} is not a number.") from error
        if not 0.0 <= value <= 1.0:
            raise IngestError(f"{env}={value} is outside 0.0..1.0.")
        return value

    @staticmethod
    def _configured_bool(env: str, default: bool) -> bool:
        raw = os.environ.get(env)
        if not raw:
            return default
        lowered = raw.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        raise IngestError(f"{env}={raw!r} is not a boolean.")

    @staticmethod
    def _configured_seconds(env: str, default: float) -> float:
        """A wall-clock ceiling: any positive number of seconds (the 0.0..1.0
        validation of `_configured_float` is a similarity-threshold rule, not a
        duration one)."""
        raw = os.environ.get(env)
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError as error:
            raise IngestError(f"{env}={raw!r} is not a number.") from error
        if value <= 0:
            raise IngestError(
                f"{env}={value} is not a positive wall-clock ceiling.")
        return value

    def read_document(self, document_id: DocumentId) -> str:
        """The document's canonical Markdown, as stored (`FR-INGEST-01`'s immutable
        row) — the read surface for a module that works FROM the ingest store:
        `M-SETUP`'s proposal reads the assessment here (`CT-SETUP-11`: setup reads
        documents through `M-INGEST`, not around it).

        Read-only by construction — no write path exists on this surface, and the
        canonical text is what the V0-V3 ladder left in the row (#40), so what a
        reader gets is exactly what was validated."""
        rows = self._handle.query(INGEST_STATEMENTS["select_document"],
                                  document_id=document_id)
        if not rows:
            raise IngestError(f"document {document_id!r} does not exist.")
        return str(rows[0]["markdown"])

    @staticmethod
    def _configured_int(env: str, default: int) -> int:
        """An integer knob read at call time; a malformed value refuses loudly rather
        than silently meaning the default — a mis-set breaker minimum is exactly the
        phantom bug the knob convention exists to avoid."""
        raw = os.environ.get(env)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except ValueError as error:
            raise IngestError(
                f"environment knob {env}={raw!r} is not an integer.") from error

    # -- the transcription step ------------------------------------------------------------------

    def _transcribe_page(self, page: PageImage, source_hash: str,
                         attempt_log: list | None = None) -> Completion:
        """One VLM call for one page (`FR-INGEST-02`), retried to the strike
        limit (`NFR-INGEST-02`, #220): a model outage strikes and is re-asked
        up to `HARNESS_INGEST_TRANSCRIPTION_ATTEMPTS` times (read at call
        time); exhausting the limit raises `IngestTranscriptionError` — the
        caller quarantines the unit, never the run. The payload carries the
        page raster and the pinned transcription prompt; `M-PROV` answers.
        Each strike (and a recovery) is appended to `attempt_log` when given —
        the strike count is observable in the result's stage detail, not just
        internal (CLAUDE.md seam 4)."""
        payload = PromptPayload(fields=(
            ("instruction", TRANSCRIPTION_PROMPT),
            ("prompt_template_version", TRANSCRIPTION_PROMPT_VERSION),
            ("source_blob_hash", source_hash),
            ("page_no", str(page.page_no)),
            ("image_png_base64", base64.b64encode(page.png).decode("ascii")),
            ("image_width_px", str(page.width_px)),
            ("image_height_px", str(page.height_px)),
        ))
        params = SamplingParams(
            temperature=0.0, max_tokens=_configured_max_tokens())
        attempts = self._configured_transcription_attempts()
        strikes: list[dict] = []
        for attempt in range(1, attempts + 1):
            try:
                completion = self._provider.complete(payload, self._model_ref,
                                                     params)
            except Exception as error:  # noqa: BLE001 -- any model-channel
                # failure is a strike (NFR-INGEST-08's fail-closed reading):
                # the channel never produced a reading, whatever the cause.
                strikes.append({
                    "page_no": page.page_no, "blob_hash": source_hash[:12],
                    "attempt": attempt, "error": f"{type(error).__name__}: "
                                                 f"{error}"})
                LOGGER.warning(
                    "transcription attempt %d/%d failed for page %d of %s: %s",
                    attempt, attempts, page.page_no, source_hash[:12], error)
                continue
            if strikes and attempt_log is not None:
                attempt_log.extend(
                    [{**strike,
                      **({"outcome": "recovered"}
                         if strike is strikes[-1] else {})}
                     for strike in strikes])
            return completion
        if attempt_log is not None:
            attempt_log.extend(strikes)
        raise IngestTranscriptionError(
            f"page {page.page_no} of source {source_hash[:12]} failed "
            f"transcription on all {attempts} attempt(s); last error: "
            f"{strikes[-1]['error']}. The page has no transcript — the "
            "submission quarantines, the cohort continues (NFR-INGEST-02).",
            attempts=strikes,
        ) from None

    @staticmethod
    def _assemble(parts: Sequence[str]) -> str:
        """Assemble page transcripts into the canonical Markdown: pages joined by a
        fixed separator, in the order the preference ladder produced."""
        return "\n\n<!-- page break -->\n\n".join(parts)

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
