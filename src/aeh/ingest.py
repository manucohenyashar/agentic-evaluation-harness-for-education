"""`M-INGEST` — the sole gateway from PDF to canonical Markdown (design §3.5).

This file lands **#36**: the gateway core — rasterize every page at the profile's
pinned DPI, transcribe each page with exactly ONE VLM call through `M-PROV`, and emit
one immutable content-hashed Markdown `document` row per logical document. A correction
(`revise_document`) creates a NEW row with `parent_doc_id` set; `document.markdown` is
never updated. The validation ladder (V0-V4, #40/#41), assembly order (#37), region
metadata (#38/#39) and the adversarial-input safety (#42) land on this foundation.

It owns **no judgment**: descriptions are descriptive only (`FR-INGEST-11`'s bar lands
with #38), and every model call goes through `M-PROV` — this module assembles payloads
and never reaches an endpoint itself.

The four seams (`CLAUDE.md`):
1. **Headless driver** — `Ingestor.ingest_document` is the pipeline entry point; nothing
   here needs a console.
2. **Deterministic transport** — the VLM is `M-PROV`'s `InferenceProvider` (the fast
   tier's `RecordedFixtureProvider`); the rasterizer is a `Rasterizer` seam with a
   scripted double for tests and a lazy-imported `pypdfium2` implementation for the
   acceptance run.
3. **Env-gated knobs** — `HARNESS_INGEST_DPI` (the pinned rasterization DPI) and
   `HARNESS_INGEST_MAX_TOKENS_PER_PAGE`; production values are the defaults.
4. **Stage-level observability** — `IngestReport` carries per-gate columns (populated by
   #40/#41) and the ingest surface logs page counts, hashes and the transcriber build.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

from aeh.conf import ModelRef
from aeh.prov import Completion, InferenceProvider, PromptPayload, SamplingParams
from aeh.store import (
    Migration,
    STATEMENTS,
    Statement,
    Tier,
    TIER_MIGRATIONS,
)

__all__ = [
    "DOCUMENT_KINDS",
    "DocumentId",
    "DocumentKind",
    "IngestError",
    "IngestReport",
    "Ingestor",
    "PageImage",
    "PageReplacement",
    "PdfiumRasterizer",
    "ResidencySlot",
    "Rasterizer",
    "TRANSCRIPTION_PROMPT_VERSION",
]

#: A canonical document's id: an opaque string this module mints.
DocumentId = str

#: The four artifact kinds (`FR-INGEST-02`). There is no fifth kind and no per-kind
#: extraction path: every page of every kind goes through the same rasterize-and-
#: transcribe pipeline.
DocumentKind = str
DOCUMENT_KINDS: tuple[str, ...] = ("assessment", "reference", "rubric", "submission")

#: The transcription prompt's version (`NFR-INGEST-05`): a prompt change alters every
#: subsequent transcript, so the version is pinned here, recorded on every document row,
#: and bumped only deliberately.
TRANSCRIPTION_PROMPT_VERSION = "ingest-transcribe-v1"

#: The transcription prompt. Deliberately descriptive-only (`FR-INGEST-11`'s bar lands
#: with #38); this template transcribes what is on the page.
TRANSCRIPTION_PROMPT = (
    "Transcribe this examination page verbatim into Markdown. Describe every graphic, "
    "diagram, table and mark exactly as it appears. Do not evaluate, correct or "
    "complete the work: transcribe what is there and nothing else."
)

#: Module observability (`CLAUDE.md` seam 4).
LOGGER = logging.getLogger("aeh.ingest")

#: The pinned rasterization DPI (`FR-INGEST-02`: "the profile's pinned DPI"). The
#: profile owns the value; the knob exists so a slower test box can lower it without a
#: code change. Default is the acceptance run's figure.
DPI_ENV = "HARNESS_INGEST_DPI"
DEFAULT_DPI = 200

#: The per-page transcription token ceiling (`NFR-INGEST-05`'s sibling knob: a page
#: that transcribes past the ceiling is a finding for the ladder, not a bigger budget).
MAX_TOKENS_ENV = "HARNESS_INGEST_MAX_TOKENS_PER_PAGE"
DEFAULT_MAX_TOKENS = 4096


class IngestError(Exception):
    """An ingestion failure that is a caller or data error, not a gate outcome.

    Gate failures (V0-V4) are routing decisions recorded on the submission — never
    exceptions. This error is for the module's own refused operations: an unknown
    document kind, a document that does not exist, a build that changed mid-document.
    """


def _configured_dpi() -> int:
    raw = os.environ.get(DPI_ENV)
    if not raw:
        return DEFAULT_DPI
    try:
        value = int(raw)
    except ValueError as error:
        raise IngestError(f"{DPI_ENV}={raw!r} is not an integer.") from error
    if value < 72:
        raise IngestError(f"{DPI_ENV}={value} is below the 72 DPI floor.")
    return value


def _configured_max_tokens() -> int:
    raw = os.environ.get(MAX_TOKENS_ENV)
    if not raw:
        return DEFAULT_MAX_TOKENS
    try:
        return int(raw)
    except ValueError as error:
        raise IngestError(f"{MAX_TOKENS_ENV}={raw!r} is not an integer.") from error


# --- the rasterizer seam -------------------------------------------------------------------------


@dataclass(frozen=True)
class PageImage:
    """One rasterized page: the image bytes (PNG), its 1-based index in the source
    file, and its pixel dimensions."""

    page_no: int
    png: bytes
    width_px: int
    height_px: int


class Rasterizer:
    """The PDF-to-page-image seam (`CLAUDE.md` seam 2): the one place a PDF is decoded.

    `FR-INGEST-01` makes this module the sole gateway — the seam exists so the rasterizer
    is a dependency like the model boundary, with a deterministic double for tests and a
    real implementation for the acceptance run."""

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> Sequence[PageImage]:
        """Render every page of `pdf_bytes` at `dpi`. Page numbers are 1-based."""
        raise NotImplementedError


class PdfiumRasterizer(Rasterizer):
    """The live rasterizer, over `pypdfium2`. Imported LAZILY: the fast tier never
    needs the dependency, and an acceptance-run box installs it explicitly."""

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> Sequence[PageImage]:
        try:
            import pypdfium2 as pdfium  # noqa: PLC0415 -- the lazy import IS the seam
        except ImportError as error:  # pragma: no cover - acceptance-run only
            raise IngestError(
                "the live rasterizer needs the pypdfium2 package; the fast tier uses "
                "a scripted Rasterizer double instead. Install it for the acceptance "
                "run."
            ) from error
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            scale = dpi / 72.0
            pages = []
            for index in range(len(pdf)):
                page = pdf[index]
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()
                import io

                buffer = io.BytesIO()
                pil_image.save(buffer, format="PNG")
                pages.append(PageImage(
                    page_no=index + 1, png=buffer.getvalue(),
                    width_px=pil_image.width, height_px=pil_image.height,
                ))
            return pages
        finally:
            pdf.close()


# --- the residency slot --------------------------------------------------------------------------


class ResidencySlot:
    """The VLM's model-residency slot.

    `HardwarePolicy.residency_policy` (`M-CONF`) names the roles permitted resident
    concurrently. For the `unified-small` and `discrete-gpu` profiles the transcriber
    and the judge cannot coexist in memory: the transcriber's slot is then EXCLUSIVE,
    and a judge acquiring it waits until ingestion releases it — which is the
    acceptance criterion's "ingestion completes and the model unloads before the first
    judge loads", as a primitive the orchestrator (`M-ORCH`) acquires on both sides.

    A slot whose policy admits both roles concurrently (shared-memory profiles where
    the design allows coexistence) admits them: `acquire` is then a no-op guard, and
    the slot exists so the call sites do not change when a profile tightens.
    """

    def __init__(self, *, exclusive: bool) -> None:
        self._exclusive = exclusive
        self._holder: str | None = None
        if exclusive:
            import threading

            self._lock = threading.Lock()
            self._released = threading.Condition(self._lock)

    @classmethod
    def for_policy(cls, policy_roles: Sequence[str], *,
                   judge_role: str = "judge",
                   transcriber_role: str = "transcriber") -> "ResidencySlot":
        """The slot the given `HardwarePolicy.residency_policy` implies: exclusive when
        the policy does not admit the judge and the transcriber concurrently."""
        roles = tuple(policy_roles)
        exclusive = not (judge_role in roles and transcriber_role in roles)
        return cls(exclusive=exclusive)

    def acquire(self, role: str = "transcriber") -> None:
        if not self._exclusive:
            return
        self._lock.acquire()
        try:
            while self._holder is not None:
                self._released.wait()
            self._holder = role
        finally:
            self._lock.release()

    def release(self, role: str = "transcriber") -> None:
        if not self._exclusive:
            return
        with self._lock:
            if self._holder != role:
                raise IngestError(
                    f"releasing the residency slot for {role!r} but {self._holder!r} "
                    "holds it — the acquire/release pairs are unbalanced."
                )
            self._holder = None
            self._released.notify_all()


# --- the Tier C migration this module contributes -------------------------------------------------
#
# The minimal `document` table (store 001) carried three columns and a NOT NULL
# submission. M-INGEST owns the canonical artifact, so its migration rebuilds the table
# with the canonical-Markdown columns and a NULLABLE submission (a setup artifact —
# assessment, reference, rubric — has no submission; `ingest_document` takes none).
# `transcriber_ref` and `markdown` are NOT NULL: a document without its transcript or
# its transcriber build is unrepresentable (`FR-INGEST-04`). Legacy rows migrated from
# 001 carry the empty string in the new columns — they predate transcription, and a
# CHECK that rejected them would make every pre-existing file unopenable; the data-layer
# guard refuses an empty ref on every row this module writes.

_INGEST_DOCUMENT_COLUMNS = Migration(
    version=2,
    name="ingest_document_core",
    statements=(
        # The children of document come along: document_region (this module's region
        # metadata, #38) and evidence (M-EXTRACT's, whose document_id FK would dangle
        # across the swap). Each is saved, dropped, and restored against the rebuilt
        # table with its original shape.
        Statement(
            """
            CREATE TABLE document_region_saved (
                region_id    TEXT    NOT NULL PRIMARY KEY,
                document_id  TEXT    NOT NULL,
                page_no      INTEGER NOT NULL,
                element_kind TEXT    NOT NULL
            )
            """
        ),
        Statement(
            "INSERT INTO document_region_saved (region_id, document_id, page_no, "
            "element_kind) SELECT region_id, document_id, page_no, element_kind "
            "FROM document_region"
        ),
        Statement(
            """
            CREATE TABLE evidence_saved (
                evidence_id TEXT NOT NULL PRIMARY KEY,
                work_id     TEXT NOT NULL,
                document_id TEXT
            )
            """
        ),
        Statement(
            "INSERT INTO evidence_saved (evidence_id, work_id, document_id) "
            "SELECT evidence_id, work_id, document_id FROM evidence"
        ),
        Statement("DROP TABLE evidence"),
        Statement("DROP TABLE document_region"),
        Statement(
            """
            CREATE TABLE document_new (
                document_id            TEXT    NOT NULL PRIMARY KEY,
                submission_id          TEXT    REFERENCES submission(submission_id),
                content_hash           TEXT    NOT NULL,
                markdown               TEXT    NOT NULL DEFAULT '',
                transcriber_ref        TEXT    NOT NULL DEFAULT '',
                prompt_template_version TEXT   NOT NULL DEFAULT '',
                kind                   TEXT    NOT NULL DEFAULT 'submission'
                    CHECK (kind IN ('assessment', 'reference', 'rubric', 'submission')),
                parent_doc_id          TEXT    REFERENCES document(document_id),
                source_blobs           TEXT,
                pages_with_text_layer  INTEGER,
                text_layer_divergence  REAL,
                created_at             TEXT
            )
            """
        ),
        Statement(
            "INSERT INTO document_new (document_id, submission_id, content_hash) "
            "SELECT document_id, submission_id, content_hash FROM document"
        ),
        Statement("DROP TABLE document"),
        Statement("ALTER TABLE document_new RENAME TO document"),
        Statement(
            """
            CREATE TABLE document_region (
                region_id    TEXT    NOT NULL PRIMARY KEY,
                document_id  TEXT    NOT NULL REFERENCES document(document_id),
                page_no      INTEGER NOT NULL CHECK (page_no >= 1),
                element_kind TEXT    NOT NULL
            )
            """
        ),
        Statement(
            "INSERT INTO document_region (region_id, document_id, page_no, "
            "element_kind) SELECT region_id, document_id, page_no, element_kind "
            "FROM document_region_saved"
        ),
        Statement("DROP TABLE document_region_saved"),
        Statement(
            """
            CREATE TABLE evidence (
                evidence_id TEXT NOT NULL PRIMARY KEY,
                work_id     TEXT NOT NULL REFERENCES work_unit(work_id),
                document_id TEXT REFERENCES document(document_id)
            )
            """
        ),
        Statement(
            "INSERT INTO evidence (evidence_id, work_id, document_id) "
            "SELECT evidence_id, work_id, document_id FROM evidence_saved"
        ),
        Statement("DROP TABLE evidence_saved"),
    ),
)

# The runtime statements only: migration DDL is versioned data in TIER_MIGRATIONS and
# deliberately stays out of the sanctioned runtime registry (the store's documented
# rule) — a DROP TABLE must never be a "declared" runtime statement.
INGEST_STATEMENTS: dict[str, Statement] = {
    "insert_document": Statement(
        "INSERT INTO document (document_id, submission_id, content_hash, markdown, "
        "transcriber_ref, prompt_template_version, kind, parent_doc_id, source_blobs, "
        "pages_with_text_layer, text_layer_divergence, created_at) VALUES (:document_id, "
        ":submission_id, :content_hash, :markdown, :transcriber_ref, "
        ":prompt_template_version, :kind, :parent_doc_id, :source_blobs, "
        ":pages_with_text_layer, :text_layer_divergence, :created_at)"
    ),
    "select_document": Statement(
        "SELECT document_id, submission_id, content_hash, markdown, transcriber_ref, "
        "prompt_template_version, kind, parent_doc_id, source_blobs, "
        "pages_with_text_layer, text_layer_divergence, created_at FROM document "
        "WHERE document_id = :document_id"
    ),
    "select_document_head": Statement(
        "SELECT document_id, submission_id, content_hash, transcriber_ref, kind, "
        "parent_doc_id, created_at FROM document WHERE submission_id = :submission_id "
        "ORDER BY created_at, document_id"
    ),
}
STATEMENTS.update(INGEST_STATEMENTS)
TIER_MIGRATIONS[Tier.COHORT] = (
    TIER_MIGRATIONS[Tier.COHORT] + (_INGEST_DOCUMENT_COLUMNS,)
)


# --- the ingestor ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class PageReplacement:
    """One replacement page for `revise_document` (`FR-INGEST-05`): the source blob
    holding the rescan, and the 1-based page it replaces."""

    blob_hash: str
    page_no: int


@dataclass
class IngestReport:
    """What one submission ingestion did (`CLAUDE.md` seam 4). The gate columns are
    per-gate by design (`FR-INGEST-29`, R13) — a bare status on top of five unrecorded
    gates is the silent-failure trap. #36 populates the identity and document fields;
    the V0-V4 gates fill in with #40/#41."""

    submission_id: str
    document_id: DocumentId
    gates: dict[str, str] = field(default_factory=dict)
    ingest_status: str = "ok"
    detail: dict = field(default_factory=dict)
    v4_signals: dict = field(default_factory=dict)


class Ingestor:
    """Tier C's gateway: `Ingestor(cohort_handle, blobs, provider, model_ref, params,
    rasterizer)` — every model call through `M-PROV`, every PDF decode through the
    `Rasterizer` seam, one document row per logical document."""

    def __init__(
        self, handle: Any, blobs: Any, provider: InferenceProvider,
        model_ref: ModelRef, params: SamplingParams, rasterizer: Rasterizer,
        *, residency: ResidencySlot | None = None,
    ) -> None:
        self._handle = handle
        self._blobs = blobs
        self._provider = provider
        self._model_ref = model_ref
        self._params = params
        self._rasterizer = rasterizer
        self._residency = residency

    # -- the gateway -----------------------------------------------------------------------------

    def ingest_document(
        self, blobs: Sequence[str], kind: DocumentKind,
        order_hint: Sequence[str] | None = None,
        package_version: str | None = None,
        submission_id: str | None = None,
    ) -> DocumentId:
        """Ingest one logical document: rasterize every page of every source PDF, run
        exactly ONE VLM transcription call per page, and emit exactly ONE immutable
        Markdown `document` row (`FR-INGEST-02`, `FR-INGEST-04`).

        `blobs` are content hashes in the blob store, in assembly order (the caller's
        sequence is the order #36 honors; the declared preference machinery lands with
        #37). `kind` is one of the four artifact kinds — there is no per-kind
        alternative path: the pipeline below is the only one. Returns the new
        `DocumentId`."""
        if kind not in DOCUMENT_KINDS:
            raise IngestError(
                f"document kind {kind!r} is not one of {DOCUMENT_KINDS}. There are "
                "exactly four artifact kinds and one pipeline."
            )
        if not blobs:
            raise IngestError("ingest_document needs at least one source blob.")
        document_id = f"doc-{uuid.uuid4().hex[:12]}"
        markdown_parts: list[str] = []
        transcriber_ref: str | None = None
        page_images: list[PageImage] = []
        dpi = _configured_dpi()
        if self._residency is not None:
            self._residency.acquire("transcriber")
        try:
            for blob_hash in blobs:
                pdf_bytes = self._blobs.get(blob_hash)
                pages = self._rasterizer.rasterize(pdf_bytes, dpi)
                if not pages:
                    raise IngestError(
                        f"source blob {blob_hash} rasterized to zero pages — a PDF "
                        "with no pages is a V0 finding once the ladder lands; the "
                        "gateway refuses it now."
                    )
                page_images.extend(pages)
                for page in pages:
                    completion = self._transcribe_page(page, blob_hash)
                    if (transcriber_ref is not None
                            and completion.resolved_build != transcriber_ref):
                        raise IngestError(
                            f"the transcriber build changed mid-document: "
                            f"{transcriber_ref!r} answered earlier pages, "
                            f"{completion.resolved_build!r} answered page "
                            f"{page.page_no}. One document, one transcriber build — "
                            "re-run the ingestion on one build."
                        )
                    transcriber_ref = completion.resolved_build
                    markdown_parts.append(completion.text)
        finally:
            if self._residency is not None:
                self._residency.release("transcriber")
        markdown = self._assemble(markdown_parts)
        content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        with self._handle.transaction() as tx:
            tx.execute(INGEST_STATEMENTS["insert_document"],
                       document_id=document_id, submission_id=submission_id,
                       content_hash=content_hash, markdown=markdown,
                       transcriber_ref=transcriber_ref,
                       prompt_template_version=TRANSCRIPTION_PROMPT_VERSION,
                       kind=kind, parent_doc_id=None,
                       source_blobs=json.dumps(list(blobs)),
                       pages_with_text_layer=None, text_layer_divergence=None,
                       created_at=self._now())
        LOGGER.info(
            "ingested document %s kind=%s pages=%d content_hash=%s transcriber=%s",
            document_id, kind, len(page_images), content_hash[:12], transcriber_ref,
        )
        return document_id

    def revise_document(
        self, document_id: DocumentId, replacement_pages: Sequence[PageReplacement],
    ) -> DocumentId:
        """Apply a correction (`FR-INGEST-05`): re-transcribe the replaced pages and
        emit a NEW document row with `parent_doc_id` set and a new `content_hash`. The
        original row is never touched — `revise_document` returns an id DIFFERENT from
        the one passed in, always."""
        rows = self._handle.query(INGEST_STATEMENTS["select_document"],
                                  document_id=document_id)
        if not rows:
            raise IngestError(f"document {document_id!r} does not exist.")
        row = rows[0]
        source_blobs = json.loads(row["source_blobs"] or "[]")
        replacements = {replacement.page_no: replacement.blob_hash
                        for replacement in replacement_pages}
        if not replacements:
            raise IngestError("revise_document needs at least one replacement page.")
        markdown_parts: list[str] = []
        transcriber_ref: str | None = None
        dpi = _configured_dpi()
        if self._residency is not None:
            self._residency.acquire("transcriber")
        try:
            for blob_hash in source_blobs:
                pdf_bytes = self._blobs.get(blob_hash)
                for page in self._rasterizer.rasterize(pdf_bytes, dpi):
                    replacement = replacements.pop(page.page_no, None)
                    if replacement is not None:
                        # A rescan is a one-page PDF holding the replacement page:
                        # rasterize it and transcribe THAT, with its own provenance.
                        rescan = self._rasterizer.rasterize(
                            self._blobs.get(replacement), dpi)
                        if len(rescan) != 1:
                            raise IngestError(
                                f"the replacement for page {page.page_no} rasterized "
                                f"to {len(rescan)} pages; a replacement page is one "
                                "page."
                            )
                        page = PageImage(page_no=page.page_no, png=rescan[0].png,
                                         width_px=rescan[0].width_px,
                                         height_px=rescan[0].height_px)
                    completion = self._transcribe_page(page, blob_hash)
                    if (transcriber_ref is not None
                            and completion.resolved_build != transcriber_ref):
                        raise IngestError(
                            f"the transcriber build changed mid-revision: "
                            f"{transcriber_ref!r} answered earlier pages, "
                            f"{completion.resolved_build!r} answered this one. One "
                            "document, one transcriber build — re-run the revision "
                            "on one build."
                        )
                    transcriber_ref = completion.resolved_build
                    markdown_parts.append(completion.text)
            if replacements:
                raise IngestError(
                    f"replacement pages {sorted(replacements)} do not exist in "
                    f"document {document_id!r} ({len(source_blobs)} source file(s))."
                )
        finally:
            if self._residency is not None:
                self._residency.release("transcriber")
        new_id = f"doc-{uuid.uuid4().hex[:12]}"
        markdown = self._assemble(markdown_parts)
        content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        with self._handle.transaction() as tx:
            tx.execute(INGEST_STATEMENTS["insert_document"],
                       document_id=new_id, submission_id=row["submission_id"],
                       content_hash=content_hash, markdown=markdown,
                       transcriber_ref=transcriber_ref,
                       prompt_template_version=TRANSCRIPTION_PROMPT_VERSION,
                       kind=row["kind"], parent_doc_id=document_id,
                       source_blobs=row["source_blobs"],
                       pages_with_text_layer=None, text_layer_divergence=None,
                       created_at=self._now())
        LOGGER.info(
            "revised document %s into %s pages_replaced=%d content_hash=%s",
            document_id, new_id, len(replacement_pages), content_hash[:12],
        )
        return new_id

    def ingest_submission(
        self, blobs: Sequence[str], cohort_id: str,
        package_version: str,
    ) -> IngestReport:
        """Ingest one submission through the validation ladder. #36 lands the gateway
        half (transcription and the document row); the V0-V4 gates fill `gates`,
        `ingest_status`, `detail` and `v4_signals` with #40/#41 — the report shape
        exists now so callers compile against the real surface."""
        document_id = self.ingest_document(
            blobs, kind="submission",
            package_version=package_version,
        )
        return IngestReport(
            submission_id=f"pending-{cohort_id}", document_id=document_id,
            gates={"v0": "deferred", "v1": "deferred", "v2": "deferred",
                   "v3": "deferred", "v4": "deferred"},
            ingest_status="ok",
            detail={"note": "the validation ladder lands with #40/#41"},
            v4_signals={},
        )

    # -- the transcription step ------------------------------------------------------------------

    def _transcribe_page(self, page: PageImage, source_hash: str) -> Completion:
        """Exactly ONE VLM call for one page (`FR-INGEST-02`): the payload carries the
        page raster and the pinned transcription prompt; `M-PROV` answers."""
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
        return self._provider.complete(payload, self._model_ref, params)

    @staticmethod
    def _assemble(parts: Sequence[str]) -> str:
        """Assemble page transcripts into the canonical Markdown: pages joined by a
        fixed separator, in the given order. (The declared preference machinery —
        operator order, printed numbers, fiducials — lands with #37; #36's order is the
        caller's sequence, which the tests pin as never being directory order.)"""
        return "\n\n<!-- page break -->\n\n".join(parts)

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
