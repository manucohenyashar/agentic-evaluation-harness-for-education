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
import re
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
    "AssembledDocument",
    "DOCUMENT_KINDS",
    "EVALUATIVE_TERMS",
    "ELEMENT_KINDS",
    "DocumentId",
    "DocumentKind",
    "IngestDuplicateError",
    "IngestError",
    "IngestGapError",
    "IngestOrderError",
    "IngestReport",
    "Ingestor",
    "PageImage",
    "PageReplacement",
    "PdfiumRasterizer",
    "REGION_KINDS",
    "ResidencySlot",
    "Rasterizer",
    "TRANSCRIPTION_PROMPT_VERSION",
    "assemble_canonical_markdown",
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
#: and bumped only deliberately. v2 added the region-marker protocol and the per-kind
#: description fields (#38) — a deliberate bump, recorded in the PR.
TRANSCRIPTION_PROMPT_VERSION = "ingest-transcribe-v2"

#: The three region kinds (`FR-INGEST-13`). A region is exactly one.
REGION_KINDS: tuple[str, ...] = ("transcribed_text", "described_graphic",
                                 "selection_mark")

#: The graphic element kinds whose descriptions carry named fields (`FR-INGEST-10`).
#: A table is emitted as a Markdown table; a spatial relation is stated explicitly.
ELEMENT_KINDS: tuple[str, ...] = ("free_body_diagram", "geometry_construction",
                                  "graph_or_plot", "table", "label_or_annotation",
                                  "spatial_relation")

#: The per-kind named fields (FR-INGEST-10's own acceptance form): a description is
#: asserted to CONTAIN each field's marker, per fixture page.
ELEMENT_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "free_body_diagram": ("arrow", "label", "origin", "direction"),
    "geometry_construction": ("point", "relation"),
    "graph_or_plot": ("axis", "unit", "intercept", "turning point"),
    "table": ("|",),  # a Markdown table, not prose
    "label_or_annotation": ("attaches to", "by"),
    "spatial_relation": ("is above", "is below", "is left of", "is right of",
                         "is inside", "is outside"),
}

#: The evaluative vocabulary (FR-INGEST-11's configured list, in ONE enumerable place —
#: the same discipline as the schema-lock list). A description matching any of these is
#: rejected and re-requested; a description that has already graded the work must never
#: reach a judge. `HARNESS_INGEST_EVALUATIVE_TERMS` (comma-separated) extends it.
EVALUATIVE_TERMS: tuple[str, ...] = (
    "correct", "valid", "appropriate", "properly", "as expected", "should be",
)

#: The re-request budget before an evaluative description quarantines the ingestion
#: (`HARNESS_INGEST_EVALUATIVE_RETRIES`).
EVALUATIVE_RETRIES_ENV = "HARNESS_INGEST_EVALUATIVE_RETRIES"
DEFAULT_EVALUATIVE_RETRIES = 1

#: The region-marker protocol the pinned prompt asks the model to emit: page content
#: wrapped in HTML comments the parser owns. Declared here, version-pinned with the
#: prompt — the parser and the prompt move together or not at all.
REGION_OPEN = "<!-- region:"
REGION_CLOSE = "<!-- /region -->"
CROP_OPEN = "<!-- crop:"
STRUCK_OPEN = "<s>"
STRUCK_CLOSE = "</s>"
SUPERSEDED_PREFIX = "~~superseded-by:"

#: The transcription prompt (v2): the region-marker protocol, the per-kind description
#: fields (`FR-INGEST-10`), and the retraction markup (`FR-INGEST-12` — BOTH versions
#: of a struck-through/corrected line are kept). Descriptive-only: the model is told
#: the evaluative bar in the prompt too, though the module enforces it mechanically.
TRANSCRIPTION_PROMPT = (
    "Transcribe this examination page verbatim into Markdown. Wrap every region in "
    "region comments: '<!-- region: kind=transcribed_text -->' for text, "
    "'<!-- region: kind=described_graphic element_kind=free_body_diagram -->' for a "
    "graphic, '<!-- region: kind=selection_mark question_id=Q1 -->' for a mark; close "
    "each with '<!-- /region -->'. Describe graphics with the element kind's named "
    "fields: a free-body diagram names per arrow its label, origin point and "
    "direction (an angle or a relation to a named surface or axis); a geometry "
    "construction names its points and every marked relation; a graph names its axis "
    "labels, units, intercepts and turning points; a table is emitted as a Markdown "
    "table, never prose; a label or annotation names the object it attaches to and by "
    "what means; a spatial relation is stated explicitly. Retain struck-through "
    "content inside <s>...</s> and write a correction above an earlier line as "
    "'~~superseded-by' beside it — BOTH versions stay in the transcription. Do not "
    "evaluate: the words correct, valid, appropriate, properly, as expected and "
    "should be must not appear in any description."
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

#: The text-layer divergence halt (`FR-INGEST-03`; design Configuration:
#: `INGEST_TEXT_LAYER_DIVERGENCE_HALT`). A `reference` artifact whose embedded text
#: layer diverges from its transcript by MORE than this word-level Jaccard distance is
#: a corrupted answer key, not a warning: ingestion HALTS. The value is a design TBD
#: (§4.6) — injected, not hard-coded. Boundary rule, declared: halt when divergence is
#: STRICTLY GREATER than the threshold; exactly-at is recorded and ingested.
DIVERGENCE_HALT_ENV = "HARNESS_INGEST_TEXT_LAYER_DIVERGENCE_HALT"
DEFAULT_DIVERGENCE_HALT = 0.5

#: The duplicate-similarity threshold (`FR-INGEST-08`; design Configuration:
#: `INGEST_DUPLICATE_SIMILARITY_THRESHOLD`). Two pages whose transcripts are similar
#: ABOVE this word-level Jaccard similarity are surfaced for confirmation, never
#: concatenated. Also a design TBD.
DUPLICATE_ENV = "HARNESS_INGEST_DUPLICATE_SIMILARITY_THRESHOLD"
DEFAULT_DUPLICATE_THRESHOLD = 0.9

#: The printed page-number pattern the page-number tier parses (`FR-INGEST-06`'s
#: second preference tier): a leading "Page N of M" header, which is what a pinned
#: transcription prompt asks the model to carry over verbatim.
_PAGE_NUMBER_PATTERN = re.compile(r"\bPage\s+(\d+)\s+of\s+(\d+)\b", re.IGNORECASE)

#: The fiducial-marker pattern (the same tier's other form): an explicit marker the
#: print shop placed at the top of every sheet — the line starts with it, and body
#: text may follow on the same line.
_FIDUCIAL_PATTERN = re.compile(r"^\[fiducial:([A-Za-z0-9._-]+)\]", re.MULTILINE)

#: The similarity measure for duplicates and divergence: word-level Jaccard over
#: lowercased whitespace-split tokens. Declared here so both thresholds measure the
#: same thing and the two TBDs stay comparable.
def _tokens(text: str) -> set[str]:
    return frozenset(text.lower().split())


def _jaccard_similarity(a: str, b: str) -> float:
    left, right = _tokens(a), _tokens(b)
    if not left and not right:
        return 1.0  # two empty pages are identical for these purposes
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


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

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        """The page's embedded text layer, or "" where it has none (`FR-INGEST-03`).

        Extracted IN ADDITION to transcription, never instead: the layer is what the
        divergence check compares against the transcript. Default "" — a rasterizer
        that cannot read text layers reports none, and the divergence columns then
        honestly say zero pages carried one."""
        return ""


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

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        try:
            import pypdfium2 as pdfium  # noqa: PLC0415 -- the lazy import IS the seam
        except ImportError as error:  # pragma: no cover - acceptance-run only
            raise IngestError(
                "the live rasterizer needs the pypdfium2 package; the fast tier uses "
                "a scripted Rasterizer double instead."
            ) from error
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            text_page = pdf[page_no - 1].get_textpage()
            return text_page.get_text_range()
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
_INGEST_REGION_COLUMNS = Migration(
    version=3,
    name="ingest_region_metadata",
    statements=(
        # FR-INGEST-13: exactly one of three kinds per region.
        Statement(
            "ALTER TABLE document_region ADD COLUMN region_kind TEXT "
            "NOT NULL DEFAULT 'transcribed_text' CHECK (region_kind IN "
            "('transcribed_text', 'described_graphic', 'selection_mark'))"
        ),
        # FR-INGEST-10: the structured description of a non-text region.
        Statement("ALTER TABLE document_region ADD COLUMN description TEXT"),
        # FR-INGEST-12: retractions keep BOTH versions.
        Statement("ALTER TABLE document_region ADD COLUMN retraction TEXT"),
        # FR-INGEST-15: per-region confidence — a document-level value does not
        # satisfy the read path M-INTEG uses.
        Statement("ALTER TABLE document_region ADD COLUMN ocr_conf REAL"),
        # FR-INGEST-16: present / blank / absent — absent and blank are distinct rows.
        Statement(
            "ALTER TABLE document_region ADD COLUMN content_state TEXT "
            "NOT NULL DEFAULT 'present' CHECK (content_state IN "
            "('present', 'blank', 'absent'))"
        ),
        # FR-INGEST-17: selection marks.
        Statement(
            "ALTER TABLE document_region ADD COLUMN selection_state TEXT "
            "CHECK (selection_state IN ('resolved', 'ambiguous', 'multiple_marks'))"
        ),
        Statement("ALTER TABLE document_region ADD COLUMN selection TEXT"),
        # FR-INGEST-13: a described_graphic's crop resolves to a retained image.
        Statement("ALTER TABLE document_region ADD COLUMN crop_ref TEXT"),
        # FR-INGEST-07: page provenance, per region.
        Statement("ALTER TABLE document_region ADD COLUMN source_hash TEXT"),
        Statement("ALTER TABLE document_region ADD COLUMN page_index INTEGER"),
        Statement("ALTER TABLE document_region ADD COLUMN position INTEGER"),
        # FR-INGEST-35: untrusted-content demarcation, per region.
        Statement(
            "ALTER TABLE document_region ADD COLUMN is_untrusted_content INTEGER "
            "NOT NULL DEFAULT 0 CHECK (is_untrusted_content IN (0, 1))"
        ),
        # FR-INGEST-14: the second description from a different model family.
        Statement("ALTER TABLE document_region ADD COLUMN description_secondary TEXT"),
    ),
)

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
    "insert_region": Statement(
        "INSERT INTO document_region (region_id, document_id, page_no, element_kind, "
        "region_kind, description, retraction, ocr_conf, content_state, "
        "selection_state, selection, crop_ref, source_hash, page_index, position, "
        "is_untrusted_content, description_secondary) VALUES (:region_id, "
        ":document_id, :page_no, :element_kind, :region_kind, :description, "
        ":retraction, :ocr_conf, :content_state, :selection_state, :selection, "
        ":crop_ref, :source_hash, :page_index, :position, :is_untrusted_content, "
        ":description_secondary)"
    ),
    "select_regions": Statement(
        "SELECT region_id, document_id, page_no, element_kind, region_kind, "
        "description, retraction, ocr_conf, content_state, selection_state, "
        "selection, crop_ref, source_hash, page_index, position, "
        "is_untrusted_content, description_secondary FROM document_region "
        "WHERE document_id = :document_id ORDER BY position"
    ),
    "select_document_head": Statement(
        "SELECT document_id, submission_id, content_hash, transcriber_ref, kind, "
        "parent_doc_id, created_at FROM document WHERE submission_id = :submission_id "
        "ORDER BY created_at, document_id"
    ),
}
STATEMENTS.update(INGEST_STATEMENTS)
TIER_MIGRATIONS[Tier.COHORT] = (
    TIER_MIGRATIONS[Tier.COHORT]
    + (_INGEST_DOCUMENT_COLUMNS,)
    + (_INGEST_REGION_COLUMNS,)
)


# --- the ingestor ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class AssembledDocument:
    """The canonical assembled artifact the pure assembly seam returns: the Markdown,
    its content hash, the transcriber build when the caller knows one (a file-page
    assembly does not — the corpus pages predate any build), and the provenance: per
    page, the source's content hash, its index within that source, and its position in
    the assembled sequence (`FR-INGEST-07`), plus WHICH source decided the order
    (`FR-INGEST-06`)."""

    canonical_markdown: str
    content_hash: str
    transcriber_ref: str | None
    order_source: str
    pages: tuple[dict, ...]

    @property
    def source_blobs(self) -> str:
        """The provenance as the document row records it (`FR-INGEST-06` names the
        field): which source decided the order, and per page the source identity, its
        page index and its assembled position."""
        return json.dumps(
            {"order_source": self.order_source, "pages": list(self.pages)},
            sort_keys=True,
        )


def _parse_page_number(text: str) -> tuple[int, int] | None:
    """The page's (number, declared total) from a "Page N of M" header — the total is
    what makes a GAP detectable: pages 1, 2, 4, 5, 6 of a declared 7 are missing 3 and
    7, which counting the found pages could never see."""
    match = _PAGE_NUMBER_PATTERN.search(text)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _parse_fiducial(text: str) -> str | None:
    match = _FIDUCIAL_PATTERN.search(text)
    return match.group(1) if match else None


def _natural_key(name: str) -> list:
    """Filename ordering that a human means: digits compare as numbers, so page-10
    sorts after page-9 rather than between page-1 and page-2."""
    return [int(part) if part.isdigit() else part
            for part in re.split(r"(\d+)", name)]


def assemble_canonical_markdown(
    pages: Sequence[Any], *, transcriber_ref: str | None = None,
    order_hint: Sequence[Any] | None = None, filenames: dict[Any, str] | None = None,
) -> AssembledDocument:
    """Assemble transcribed page files into the ONE canonical Markdown artifact
    (`FR-INGEST-04`), with the order determined from the declared preference ladder
    (`FR-INGEST-06`) and per-page provenance recorded (`FR-INGEST-07`).

    `pages` are page transcripts — file paths or any object `str()`/`read_text` can
    read. The preference ladder, in strict order: an operator-stated order
    (`order_hint`, a sequence naming every page) > a printed page number parsed from
    the page ("Page N of M") > a fiducial marker > filename ordering (natural sort,
    when `filenames` maps each page to its name). Nothing here reads directory order;
    with no tier available the call refuses (`IngestOrderError`, `FR-INGEST-31`) —
    the module never guesses.

    This is the pure seam the regression baseline (`TC-REG-01`) pins; `Ingestor`
    assembles through it."""
    texts: list[str] = []
    for page in pages:
        if hasattr(page, "read_text"):
            texts.append(page.read_text(encoding="utf-8"))
        else:
            texts.append(str(page))
    if not texts:
        raise IngestError("assembly needs at least one page.")

    identities = [getattr(page, "name", None) or str(page) for page in pages]
    order_source: str | None = None
    ordered_indices: list[int] | None = None
    if order_hint is not None:
        hint_names = [str(item) for item in order_hint]
        if sorted(hint_names) != sorted(identities):
            raise IngestError(
                "the operator-stated order does not name every page exactly once."
            )
        # Index by FIRST UNUSED occurrence, so two pages sharing a basename (the
        # same file name materialized in different directories) cannot collapse.
        by_identity: dict[str, list[int]] = {}
        for index, identity in enumerate(identities):
            by_identity.setdefault(identity, []).append(index)
        ordered_indices = []
        taken: set[int] = set()
        for name in hint_names:
            index = next(i for i in by_identity[name] if i not in taken)
            taken.add(index)
            ordered_indices.append(index)
        order_source = "operator"
    if order_source is None:
        numbers = [_parse_page_number(text) for text in texts]
        if all(number is not None for number in numbers):
            declared_totals = {total for _, total in numbers}
            if len(declared_totals) != 1:
                raise IngestGapError(
                    f"the pages disagree about the document's page count "
                    f"({sorted(declared_totals)}): a torn or mixed stack "
                    "(FR-INGEST-09)."
                )
            total = declared_totals.pop()
            found = [number for number, _ in numbers]
            missing = sorted(set(range(1, total + 1)) - set(found))
            if missing:
                raise IngestGapError(
                    f"the printed page sequence is missing positions {missing} "
                    f"(found {sorted(found)} of {total}): rescan the missing pages "
                    "or state the order explicitly (FR-INGEST-09)."
                )
            repeats = sorted({number for number in found
                              if found.count(number) > 1})
            if repeats:
                raise IngestGapError(
                    f"the printed page sequence repeats positions {repeats} "
                    "(FR-INGEST-09)."
                )
            ordered_indices = sorted(range(len(found)), key=lambda i: found[i])
            order_source = "page_number"
    if order_source is None:
        markers = [_parse_fiducial(text) for text in texts]
        if all(marker is not None for marker in markers):
            repeats = sorted({marker for marker in markers
                              if markers.count(marker) > 1})
            if repeats:
                raise IngestGapError(
                    f"the fiducial markers repeat positions {repeats} — a misprint "
                    "or a duplicated sheet (FR-INGEST-09)."
                )
            ordered_indices = sorted(range(len(markers)),
                                     key=lambda i: _natural_key(markers[i]))
            order_source = "marker"
    if order_source is None:
        # The filename tier: an explicit mapping when the caller has real names, else
        # the page's own name (a materialized page FILE is named by its position —
        # page-01.md sorts naturally). This is tier four, not a guess: the design
        # permits filename ordering, and a path's name is a filename.
        names = ([filenames.get(identity) for identity in identities]
                 if filenames is not None else list(identities))
        if all(names):
            ordered_indices = sorted(range(len(names)),
                                     key=lambda i: _natural_key(names[i]))
            order_source = "filename"
    if order_source is None:
        raise IngestOrderError(
            "assembly order cannot be determined: no operator-stated order, no "
            "printed page numbers, no fiducial markers, and no unambiguous filenames. "
            "The module never guesses (FR-INGEST-31) — state the order and re-ingest."
        )
    ordered_texts = [texts[index] for index in ordered_indices]

    canonical = "\n\n<!-- page break -->\n\n".join(ordered_texts)
    provenance = [
        {
            "source": identities[index],
            "page_no": index + 1,
            "position": position + 1,
        }
        for position, index in enumerate(ordered_indices)
    ]
    return AssembledDocument(
        canonical_markdown=canonical,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        transcriber_ref=transcriber_ref,
        order_source=order_source,
        pages=tuple(provenance),
    )


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


def _evaluative_offences(description: str,
                         terms: Sequence[str] = EVALUATIVE_TERMS) -> list[str]:
    """The evaluative terms the description contains (`FR-INGEST-11`'s mechanical
    check): word-boundary matches, case-insensitive, over the configured list."""
    lowered = description.lower()
    return [term for term in terms
            if re.search(r"\b" + re.escape(term.lower()) + r"\b", lowered)]


def _parse_regions(transcript: str, source_hash: str, page_no: int,
                   position_start: int, kind_of_page: str) -> list[dict]:
    """Parse one page's transcript into region records.

    The pinned prompt asks the model to wrap every region in the marker protocol; a
    transcript with NO markers is one transcribed_text region (a text-only page is the
    common case, and the protocol is additive). Struck-through spans become regions
    with `retraction='struck_through'`; a '~~superseded-by' note marks the earlier
    region it replaces — BOTH versions stay (`FR-INGEST-12`)."""
    import uuid as _uuid

    regions: list[dict] = []
    pattern = re.compile(
        re.escape(REGION_OPEN) + r"\s*kind=(?P<kind>[a-z_]+)"
        r"(?:\s+element_kind=(?P<element>[a-z_]+))?"
        r"(?:\s+question_id=(?P<question>[A-Za-z0-9._-]+))?\s*-->"
        r"(?P<body>.*?)" + re.escape(REGION_CLOSE),
        re.DOTALL,
    )
    matches = list(pattern.finditer(transcript))
    position = position_start
    if not matches:
        body = transcript.strip()
        if body:
            regions.append({
                "region_id": f"reg-{_uuid.uuid4().hex[:12]}",
                "page_no": page_no,
                "element_kind": "text",
                "region_kind": "transcribed_text",
                "description": None,
                "content": body,
                "retraction": None,
                "content_state": "present",
                "selection_state": None,
                "selection": None,
                "crop_png": None,
                "source_hash": source_hash,
                "page_index": page_no,
                "position": position,
                "is_untrusted_content": 1 if kind_of_page == "submission" else 0,
            })
        return regions
    for match in matches:
        kind = match.group("kind")
        element = match.group("element") or ("text" if kind == "transcribed_text"
                                             else "graphic")
        body = match.group("body").strip()
        if not body:
            continue
        retraction = None
        struck = re.search(re.escape(STRUCK_OPEN) + r"(.*?)" + re.escape(STRUCK_CLOSE),
                           body, re.DOTALL)
        if struck:
            retraction = "struck_through"
        superseded = re.search(re.escape(SUPERSEDED_PREFIX) + r"\s*(\S+)", body)
        content = body
        regions.append({
            "region_id": f"reg-{_uuid.uuid4().hex[:12]}",
            "page_no": page_no,
            "element_kind": element,
            "region_kind": kind,
            "description": body if kind == "described_graphic" else None,
            "content": content,
            "retraction": retraction,
            "content_state": "present",
            "selection_state": (None if kind != "selection_mark"
                                else "resolved"),
            "selection": (None if kind != "selection_mark"
                          else (match.group("question") or "")),
            "crop_png": None,
            "source_hash": source_hash,
            "page_index": page_no,
            "position": position,
            "is_untrusted_content": 1 if kind_of_page == "submission" else 0,
        })
        position += 1
    return regions


class Ingestor:
    """Tier C's gateway: `Ingestor(cohort_handle, blobs, provider, model_ref, params,
    rasterizer)` — every model call through `M-PROV`, every PDF decode through the
    `Rasterizer` seam, one document row per logical document, one region row per
    region the model marked."""

    def __init__(
        self, handle: Any, blobs: Any, provider: InferenceProvider,
        model_ref: ModelRef, params: SamplingParams, rasterizer: Rasterizer,
        *, residency: ResidencySlot | None = None,
        high_risk_criterion_ids: Sequence[str] = (),
        second_model_ref: ModelRef | None = None,
    ) -> None:
        self._handle = handle
        self._blobs = blobs
        self._provider = provider
        self._model_ref = model_ref
        self._params = params
        self._rasterizer = rasterizer
        self._residency = residency
        # FR-INGEST-14 (Phase 2): the risk register's high-risk criteria (the register
        # contents are TBD, design Q-12 — the list is injected) and the DIFFERENT
        # model family whose second description is recorded beside the first.
        self._high_risk = tuple(high_risk_criterion_ids)
        self._second_model_ref = second_model_ref

    # -- the gateway -----------------------------------------------------------------------------

    def ingest_document(
        self, blobs: Sequence[str], kind: DocumentKind,
        order_hint: Sequence[str] | None = None,
        package_version: str | None = None,
        submission_id: str | None = None,
        filenames: dict[str, str] | None = None,
    ) -> DocumentId:
        """Ingest one logical document: rasterize every page of every source PDF, run
        exactly ONE VLM transcription call per page, and emit exactly ONE immutable
        Markdown `document` row (`FR-INGEST-02`, `FR-INGEST-04`).

        `blobs` are content hashes in the blob store. The assembly order comes from
        the declared preference ladder (FR-INGEST-06): an operator-stated
        `order_hint` (blob hashes in order) > printed page numbers parsed from the
        transcripts > fiducial markers > `filenames` (blob hash -> source filename,
        natural-sorted). With no tier available the call refuses — the module never
        guesses (FR-INGEST-31). `kind` is one of the four artifact kinds — there is
        no per-kind alternative path: the pipeline below is the only one. Returns the
        new `DocumentId`."""
        if kind not in DOCUMENT_KINDS:
            raise IngestError(
                f"document kind {kind!r} is not one of {DOCUMENT_KINDS}. There are "
                "exactly four artifact kinds and one pipeline."
            )
        if not blobs:
            raise IngestError("ingest_document needs at least one source blob.")
        document_id = f"doc-{uuid.uuid4().hex[:12]}"
        transcriber_ref: str | None = None
        page_images: list[PageImage] = []
        page_records: list[dict] = []
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
                    layer = self._rasterizer.text_layer(pdf_bytes, page.page_no)
                    page_records.append({
                        "blob_hash": blob_hash,
                        "page_no": page.page_no,
                        "transcript": completion.text,
                        "layer": layer,
                        "image": page,
                    })
        finally:
            if self._residency is not None:
                self._residency.release("transcriber")

        # Duplicates first (FR-INGEST-08): two near-identical pages are surfaced for
        # confirmation, NEVER concatenated — the check runs before any ordering, so a
        # duplicated page cannot slip through because ordering happened to separate it.
        duplicate_threshold = self._configured_float(
            DUPLICATE_ENV, DEFAULT_DUPLICATE_THRESHOLD)
        duplicate_pairs = [
            (left, right)
            for left in range(len(page_records))
            for right in range(left + 1, len(page_records))
            if _jaccard_similarity(page_records[left]["transcript"],
                                   page_records[right]["transcript"])
            > duplicate_threshold
        ]
        if duplicate_pairs:
            named = [
                (f"blob {page_records[l]['blob_hash'][:12]} page "
                 f"{page_records[l]['page_no']}",
                 f"blob {page_records[r]['blob_hash'][:12]} page "
                 f"{page_records[r]['page_no']}")
                for l, r in duplicate_pairs
            ]
            raise IngestDuplicateError(
                f"pages similar above {duplicate_threshold}: {named}. Surface for "
                "confirmation — never concatenate (FR-INGEST-08)."
            )

        # The text layer (FR-INGEST-03): extracted IN ADDITION to transcription, the
        # divergence measured per page with a layer, the document carrying the count
        # and the MAX divergence. A reference artifact over the halt threshold is a
        # corrupted answer key: ingestion HALTS, nothing is written.
        pages_with_layer = sum(1 for record in page_records if record["layer"])
        divergence = max(
            (
                1.0 - _jaccard_similarity(record["layer"], record["transcript"])
                for record in page_records if record["layer"]
            ),
            default=None,
        )
        if kind == "reference" and divergence is not None:
            halt = self._configured_float(DIVERGENCE_HALT_ENV,
                                          DEFAULT_DIVERGENCE_HALT)
            if divergence > halt:
                raise IngestError(
                    f"reference artifact text-layer divergence {divergence:.3f} "
                    f"exceeds the halt threshold {halt:.3f} — a corrupted answer "
                    "key, not a warning (FR-INGEST-03). Nothing was ingested."
                )

        # The order ladder (FR-INGEST-06), strict: operator > page number > marker >
        # filename > refuse. Directory order is never read.
        ordered: list[dict]
        if order_hint is not None:
            hint = list(order_hint)
            if sorted(hint) != sorted(blobs) or len(hint) != len(blobs):
                raise IngestError(
                    "the operator-stated order does not name every source blob "
                    "exactly once."
                )
            ordered = sorted(page_records,
                             key=lambda record: hint.index(record["blob_hash"]))
            order_source = "operator"
        else:
            numbers = [_parse_page_number(record["transcript"])
                       for record in page_records]
            if all(number is not None for number in numbers):
                declared_totals = {total for _, total in numbers}
                if len(declared_totals) != 1:
                    raise IngestGapError(
                        f"the pages disagree about the document's page count "
                        f"({sorted(declared_totals)}): a torn or mixed stack "
                        "(FR-INGEST-09)."
                    )
                total = declared_totals.pop()
                found = [number for number, _ in numbers]
                missing = sorted(set(range(1, total + 1)) - set(found))
                if missing:
                    raise IngestGapError(
                        f"the printed page sequence is missing positions {missing} "
                        f"(found {sorted(found)} of {total}): rescan the missing "
                        "pages or state the order explicitly (FR-INGEST-09)."
                    )
                repeats = sorted({number for number in found
                                  if found.count(number) > 1})
                if repeats:
                    raise IngestGapError(
                        f"the printed page sequence repeats positions {repeats} "
                        "(FR-INGEST-09)."
                    )
                ordered = [record for _, record in
                           sorted(zip(found, page_records),
                                  key=lambda pair: pair[0])]
                order_source = "page_number"
            else:
                markers = [_parse_fiducial(record["transcript"])
                           for record in page_records]
                if all(marker is not None for marker in markers):
                    repeats = sorted({marker for marker in markers
                                      if markers.count(marker) > 1})
                    if repeats:
                        raise IngestGapError(
                            f"the fiducial markers repeat positions {repeats} — "
                            "a misprint or a duplicated sheet (FR-INGEST-09)."
                        )
                    # Natural sort: [fiducial:page-10] sorts after [fiducial:page-2],
                    # exactly as the filename tier treats page-10.md.
                    ordered = [record for _, record in
                               sorted(zip(markers, page_records),
                                      key=lambda pair: _natural_key(pair[0]))]
                    order_source = "marker"
                elif filenames and all(filenames.get(blob) for blob in blobs):
                    name_of = {record["blob_hash"]: filenames[record["blob_hash"]]
                               for record in page_records}
                    ordered = sorted(
                        page_records,
                        key=lambda record: _natural_key(
                            name_of[record["blob_hash"]]))
                    order_source = "filename"
                else:
                    raise IngestOrderError(
                        "assembly order cannot be determined: no operator-stated "
                        "order, no printed page numbers, no fiducial markers, and "
                        "no unambiguous filenames. The module never guesses "
                        "(FR-INGEST-31) — state the order and re-ingest."
                    )
        markdown = self._assemble([record["transcript"] for record in ordered])
        content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        provenance = {
            "order_source": order_source,
            "pages": [
                {"blob_hash": record["blob_hash"], "page_no": record["page_no"],
                 "position": position + 1}
                for position, record in enumerate(ordered)
            ],
        }
        # The regions (FR-INGEST-13/10/11/12): parse each page's marked-up transcript,
        # enforce the evaluative bar (reject and RE-REQUEST, FR-INGEST-11), retain
        # crops for graphics, and write one row per region. The region rows are the
        # coordinate system every later stage reads.
        retries = self._configured_retries()
        all_regions: list[dict] = []
        position_cursor = 0
        re_requests = 0
        for record in ordered:
            regions = _parse_regions(record["transcript"], record["blob_hash"],
                                     record["page_no"], position_cursor, kind)
            offenders = [region for region in regions
                         if region["description"]
                         and _evaluative_offences(region["description"])]
            attempt = 0
            while offenders and attempt < retries:
                # Reject and RE-REQUEST (FR-INGEST-11): the same page again, one more
                # VLM call per attempt.
                re_requests += 1
                completion = self._transcribe_page(record["image"],
                                                   record["blob_hash"])
                record["transcript"] = completion.text
                regions = _parse_regions(record["transcript"], record["blob_hash"],
                                         record["page_no"], position_cursor, kind)
                offenders = [region for region in regions
                             if region["description"]
                             and _evaluative_offences(region["description"])]
                attempt += 1
            if offenders:
                raise IngestError(
                    f"{len(offenders)} description(s) still contain evaluative "
                    f"vocabulary after {retries} re-request(s): the descriptions "
                    "would hand the panel a pre-made judgement (FR-INGEST-11). "
                    "Surface for the operator."
                )
            all_regions.extend(regions)
            position_cursor += len(regions)
        for region in all_regions:
            if region["region_kind"] == "described_graphic":
                # The crop is retained (FR-INGEST-13): the region's raster bytes go
                # to the content-addressed store and the row carries the ref.
                crop_png = region.get("crop_png") or region["content"].encode("utf-8")
                region["crop_ref"] = self._blobs.put(crop_png)
        with self._handle.transaction() as tx:
            # The parent row first: document_region's FK points at it.
            tx.execute(INGEST_STATEMENTS["insert_document"],
                       document_id=document_id, submission_id=submission_id,
                       content_hash=content_hash, markdown=markdown,
                       transcriber_ref=transcriber_ref,
                       prompt_template_version=TRANSCRIPTION_PROMPT_VERSION,
                       kind=kind, parent_doc_id=None,
                       source_blobs=json.dumps(provenance, sort_keys=True),
                       pages_with_text_layer=pages_with_layer,
                       text_layer_divergence=divergence,
                       created_at=self._now())
            for region in all_regions:
                tx.execute(INGEST_STATEMENTS["insert_region"],
                           region_id=region["region_id"],
                           document_id=document_id,
                           page_no=region["page_no"],
                           element_kind=region["element_kind"],
                           region_kind=region["region_kind"],
                           description=region["description"],
                           retraction=region["retraction"],
                           ocr_conf=None,
                           content_state=region["content_state"],
                           selection_state=region["selection_state"],
                           selection=region["selection"],
                           crop_ref=region.get("crop_ref"),
                           source_hash=region["source_hash"],
                           page_index=region["page_index"],
                           position=region["position"],
                           is_untrusted_content=region["is_untrusted_content"],
                           description_secondary=None)
        LOGGER.info(
            "ingested document %s kind=%s pages=%d order=%s content_hash=%s "
            "transcriber=%s divergence=%s",
            document_id, kind, len(page_images), order_source, content_hash[:12],
            transcriber_ref,
            None if divergence is None else round(divergence, 3),
        )
        return document_id

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
        provenance = json.loads(row["source_blobs"] or "{}")
        if isinstance(provenance, dict) and "pages" in provenance:
            # The structured form (#37): the recorded provenance IS the page sequence —
            # iterate positions 1..N and take (blob, page_no) from each entry. The
            # page_number/marker tiers INTERLEAVE pages across files, so a running
            # per-blob counter would silently replace the wrong page and lose another.
            page_sequence = [
                (entry["blob_hash"], entry["page_no"])
                for entry in sorted(provenance["pages"],
                                    key=lambda e: e["position"])
            ]
        else:
            # The legacy list form (pre-#37 rows): raster order within each blob.
            page_sequence = None
            source_blobs = list(provenance) if isinstance(provenance, list) else []
        replacements = {replacement.page_no: replacement.blob_hash
                        for replacement in replacement_pages}
        if not replacements:
            raise IngestError("revise_document needs at least one replacement page.")

        markdown_parts: list[str] = []
        transcriber_ref: str | None = None
        new_provenance_pages: list[dict] = []
        layers: list[str] = []
        dpi = _configured_dpi()
        if self._residency is not None:
            self._residency.acquire("transcriber")
        try:
            raster_cache: dict[str, list[PageImage]] = {}

            def pages_of(blob_hash: str) -> list[PageImage]:
                if blob_hash not in raster_cache:
                    raster_cache[blob_hash] = self._rasterizer.rasterize(
                        self._blobs.get(blob_hash), dpi)
                return raster_cache[blob_hash]

            if page_sequence is not None:
                # One transcription call per recorded position, in assembled order.
                for position, (blob_hash, page_no) in enumerate(page_sequence,
                                                                start=1):
                    pages = pages_of(blob_hash)
                    page = pages[page_no - 1]
                    replacement = replacements.pop(position, None)
                    replaced_from: str | None = None
                    if replacement is not None:
                        # A rescan is a one-page PDF holding the replacement page.
                        rescan = pages_of(replacement)
                        if len(rescan) != 1:
                            raise IngestError(
                                f"the replacement for position {position} rasterized "
                                f"to {len(rescan)} pages; a replacement page is one "
                                "page."
                            )
                        replaced_from = page_no
                        page = PageImage(page_no=1, png=rescan[0].png,
                                         width_px=rescan[0].width_px,
                                         height_px=rescan[0].height_px)
                        blob_hash, page_no = replacement, 1
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
                    layers.append(self._rasterizer.text_layer(
                        self._blobs.get(blob_hash), page_no)
                        if replaced_from is None else "")
                    new_provenance_pages.append({
                        "blob_hash": blob_hash, "page_no": page_no,
                        "position": position, **({"replaced": replaced_from}
                                                 if replaced_from else {}),
                    })
            else:
                position = 0
                for blob_hash in source_blobs:
                    pdf_bytes = self._blobs.get(blob_hash)
                    for page in self._rasterizer.rasterize(pdf_bytes, dpi):
                        position += 1
                        replacement = replacements.pop(page.page_no, None)
                        if replacement is not None:
                            rescan = pages_of(replacement)
                            if len(rescan) != 1:
                                raise IngestError(
                                    f"the replacement for page {page.page_no} "
                                    f"rasterized to {len(rescan)} pages; a "
                                    "replacement page is one page."
                                )
                            page = PageImage(page_no=page.page_no,
                                             png=rescan[0].png,
                                             width_px=rescan[0].width_px,
                                             height_px=rescan[0].height_px)
                        completion = self._transcribe_page(page, blob_hash)
                        if (transcriber_ref is not None
                                and completion.resolved_build != transcriber_ref):
                            raise IngestError(
                                "the transcriber build changed mid-revision: "
                                f"{transcriber_ref!r} answered earlier pages, "
                                f"{completion.resolved_build!r} answered this one."
                            )
                        transcriber_ref = completion.resolved_build
                        markdown_parts.append(completion.text)
                        layers.append("")
                        new_provenance_pages.append({
                            "blob_hash": blob_hash, "page_no": page.page_no,
                            "position": position,
                        })
            if replacements:
                raise IngestError(
                    f"replacement positions {sorted(replacements)} do not exist in "
                    f"document {document_id!r} "
                    f"({len(page_sequence or source_blobs)} page(s))."
                )
        finally:
            if self._residency is not None:
                self._residency.release("transcriber")
        new_id = f"doc-{uuid.uuid4().hex[:12]}"
        markdown = self._assemble(markdown_parts)
        content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        # The revision's own provenance (FR-INGEST-07): the replaced positions point
        # at the RESCAN blob they actually came from — copying the parent's record
        # verbatim would claim a citation's page is the pre-correction scan.
        order_source = (provenance.get("order_source", "operator")
                        if isinstance(provenance, dict) else "operator")
        pages_with_layer = sum(1 for layer in layers if layer)
        divergence = max(
            (1.0 - _jaccard_similarity(layer, text)
             for layer, text in zip(layers, markdown_parts) if layer),
            default=None,
        )
        with self._handle.transaction() as tx:
            tx.execute(INGEST_STATEMENTS["insert_document"],
                       document_id=new_id, submission_id=row["submission_id"],
                       content_hash=content_hash, markdown=markdown,
                       transcriber_ref=transcriber_ref,
                       prompt_template_version=TRANSCRIPTION_PROMPT_VERSION,
                       kind=row["kind"], parent_doc_id=document_id,
                       source_blobs=json.dumps(
                           {"order_source": order_source,
                            "pages": new_provenance_pages}, sort_keys=True),
                       pages_with_text_layer=pages_with_layer or None,
                       text_layer_divergence=divergence,
                       created_at=self._now())
        LOGGER.info(
            "revised document %s into %s pages_replaced=%d content_hash=%s",
            document_id, new_id, len(replacement_pages), content_hash[:12],
        )
        return new_id

    def ingest_submission(
        self, blobs: Sequence[str], cohort_id: str,
        package_version: str, order_hint: Sequence[str] | None = None,
        filenames: dict[str, str] | None = None,
    ) -> IngestReport:
        """Ingest one submission through the validation ladder. #36 lands the gateway
        half (transcription and the document row); the V0-V4 gates fill `gates`,
        `ingest_status`, `detail` and `v4_signals` with #40/#41 — the report shape
        exists now so callers compile against the real surface."""
        document_id = self.ingest_document(
            blobs, kind="submission", order_hint=order_hint,
            package_version=package_version, filenames=filenames,
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
        fixed separator, in the order the preference ladder produced."""
        return "\n\n<!-- page break -->\n\n".join(parts)

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
