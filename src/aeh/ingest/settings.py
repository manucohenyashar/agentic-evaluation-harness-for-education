"""Document kinds, limits and thresholds, each read from its environment knob at call time."""

from __future__ import annotations

import math
import logging
import os

from .errors import IngestError


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
#: description fields (#38); v3 added the per-region confidence, content-state and
#: unresolved-token attributes (#39); v4 added the verbatim header carry-over the
#: V3/V4 gates parse (#41) — each a deliberate bump, recorded in the PR.
TRANSCRIPTION_PROMPT_VERSION = "ingest-transcribe-v4"


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
#: reach a judge.
#:
#: Matching is PREFIX-based with an optional "in-" negation prefix, decided from
#: RISK-17's own motivating example: "the arrow is correctly labelled" is the failure
#: the requirement exists for, so "correct" must match "correctly", "incorrect" and
#: "correction" — a word that STARTS with the term (optionally negated) carries the
#: same judgement. `HARNESS_INGEST_EVALUATIVE_TERMS` (comma-separated) adds configured
#: synonyms at call time (design Configuration: `INGEST_EVALUATIVE_TERMS`).
EVALUATIVE_TERMS: tuple[str, ...] = (
    "correct", "valid", "appropriate", "properly", "as expected", "should be",
)


#: The morphology the matcher folds in: the negation prefix and the suffixes a
#: judgement word wears.
EVALUATIVE_MATCH_ENV = "HARNESS_INGEST_EVALUATIVE_TERMS"


def _configured_evaluative_terms() -> tuple[str, ...]:
    """The evaluative words to refuse: the built-in list plus any synonyms from the environment,
    read at call time, so a school can add its own words without a code change."""
    raw = os.environ.get(EVALUATIVE_MATCH_ENV)
    if not raw:
        return EVALUATIVE_TERMS
    synonyms = tuple(term.strip().lower() for term in raw.split(",")
                     if term.strip())
    return EVALUATIVE_TERMS + synonyms


#: The five legal ingest statuses (`FR-INGEST-29`). Quarantine is three of them:
#: `unreadable` (V0), `incomplete` (V1/V2), `unmatched_assessment` (V4/#41) — and a
#: quarantined submission NEVER reaches the teacher review queue (FR-INGEST-30).
INGEST_STATUSES: tuple[str, ...] = (
    "ok", "low_confidence_ocr", "unreadable", "incomplete", "unmatched_assessment",
)


#: The blank-page tolerance (V0: the fraction of a document's pages that may be
#: blank or near-blank before the artifact quarantines; `HARNESS_INGEST_BLANK_TOLERANCE`).
BLANK_TOLERANCE_ENV = "HARNESS_INGEST_BLANK_TOLERANCE"


DEFAULT_BLANK_TOLERANCE = 0.2


#: The V0 resolution floor (an artifact rasterized below it quarantines;
#: `HARNESS_INGEST_RESOLUTION_FLOOR`). The design denominates the floor in DPI;
#: what the module can measure is the raster's linear extent in px, so the value
#: is enforced as a px floor — `_check_rasters` carries the interpretation.
RESOLUTION_FLOOR_ENV = "HARNESS_INGEST_RESOLUTION_FLOOR"


DEFAULT_RESOLUTION_FLOOR = 150


#: The transcription attempts before a page quarantines (`NFR-INGEST-02`: fail the
#: unit, never the run — the cohort's remaining submissions continue).
TRANSCRIPTION_ATTEMPTS_ENV = "HARNESS_INGEST_TRANSCRIPTION_ATTEMPTS"


DEFAULT_TRANSCRIPTION_ATTEMPTS = 3


#: The re-request budget before an evaluative description quarantines the ingestion
#: (`HARNESS_INGEST_EVALUATIVE_RETRIES`).
EVALUATIVE_RETRIES_ENV = "HARNESS_INGEST_EVALUATIVE_RETRIES"


DEFAULT_EVALUATIVE_RETRIES = 1


#: Module observability (`CLAUDE.md` seam 4).
LOGGER = logging.getLogger("aeh.ingest")


#: The pinned rasterization DPI (`FR-INGEST-02`: "the profile's pinned DPI"). The
#: profile owns the value; the knob exists so a slower test box can lower it without a
#: code change. Default is the acceptance run's figure.
DPI_ENV = "HARNESS_INGEST_DPI"


DEFAULT_DPI = 200


#: Whether the full-page rasters persist into the blob store alongside the
#: crops (`FR-STORE-06` names page rasters among the stored blobs; issue
#: #226). The production default is ON — retention follows the crop precedent,
#: kept until the cohort's Tier C purge (`NFR-INGEST-04`, PII) — and this knob
#: is the environment-sensitive bound (seam 3, read at call time): a
#: capacity-constrained box can turn full-page retention off while
#: `FR-INGEST-13`'s retained crops still flow. The skip is recorded honestly
#: in the provenance (a null `raster_hash`), never silently.
RETAIN_PAGE_RASTERS_ENV = "HARNESS_INGEST_RETAIN_PAGE_RASTERS"


DEFAULT_RETAIN_PAGE_RASTERS = True


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


#: The V4 gate's three-valued outcome vocabulary (`FR-INGEST-25`), plus `not_run` for
#: the submissions V4 never evaluated: no transcript (V0/V1 quarantined first) or no
#: package bound to the ingestion. The ladder writes exactly these values — anything
#: else in the column is a bug, so the set is the data-layer guard's vocabulary too.
V4_MATCH_OUTCOMES: tuple[str, ...] = ("match", "uncertain", "mismatch", "not_run")


#: The gate columns' not-reached sentinel (#222, the F4 probe): a gate the ladder
#: never reached records `not_reached`, never the initialized `'pass'` — the
#: final gate write records EVERY column, so an initialized `'pass'` would sit on
#: top of a gate that never ran and naive per-gate pass counts over raw rows
#: would overcount. The sentinel is data, not absence: counting passes over raw
#: rows then equals counting over construction-known reachability. V4 keeps its
#: own `not_run` (`V4_MATCH_OUTCOMES`, FR-INGEST-25's shipped vocabulary); the
#: gate columns carry no CHECK, so the sentinel needs no migration.
GATE_NOT_REACHED = "not_reached"


#: The V4 cohort circuit breaker's rate threshold (`FR-INGEST-28`; design
#: Configuration: `INGEST_V4_COHORT_BREAKER_RATE`, the design's 20% assumption). The
#: combined `mismatch`-plus-`uncertain` rate across the cohort AT OR ABOVE this trips
#: the breaker — TC-INGEST-28 pins the boundary as "at or above 20%", so the
#: comparison is `>=`, declared here rather than left to the implementation.
V4_BREAKER_RATE_ENV = "HARNESS_INGEST_V4_COHORT_BREAKER_RATE"


DEFAULT_V4_BREAKER_RATE = 0.20


#: The breaker's minimum cohort size (`FR-INGEST-28`'s assumption: "minimum 20
#: submissions"). Below it the rate is noise, not signal — one wrong paper in a
#: five-submission cohort is 20% and must not halt the cohort. Also `>=` (TC-INGEST-28:
#: "at or above the 20-submission minimum").
V4_BREAKER_MIN_ENV = "HARNESS_INGEST_V4_COHORT_BREAKER_MIN"


DEFAULT_V4_BREAKER_MIN = 20


#: The deterministic semantic floor (`FR-INGEST-25`'s aggregate semantic
#: correspondence; ADR-7): the mean word-level Jaccard overlap between the
#: submission's answer content and the assessment artifact's question text AT OR
#: ABOVE which the semantic signal reads `match`. Below it, `mismatch`. The
#: discrimination of a lexical measure is exactly what ADR-7 calls unmeasured — the
#: value is a declared default behind this knob, to be calibrated by FR-CONFORM-03's
#: known-wrong-paper fixtures, and TC tests inject it rather than trust the default
#: (the same discipline as the divergence and duplicate thresholds).
V4_SEMANTIC_FLOOR_ENV = "HARNESS_INGEST_V4_SEMANTIC_FLOOR"


DEFAULT_V4_SEMANTIC_FLOOR = 0.10


#: The OCR confidence floor (`low_confidence_ocr`'s threshold; #221). Design §3.9
#: records the floor as an assumption — "the OCR confidence floor of 0.70",
#: measured on real scans and per-transcriber — so it is a knob, not a constant
#: (`CLAUDE.md` seam 3). A stored region whose `ocr_conf` is STRICTLY BELOW the
#: floor flags its submission `low_confidence_ocr` (FR-INGEST-29's state model:
#: available, flagged for impact routing — never quarantined; CT-INGEST-11
#: admits it to scoring). Exactly-at is not low, mirroring the divergence
#: halt's declared boundary rule. It is also the no-evidence value: a region
#: the transcript left with no reading confidence at all records the floor
#: itself (see `_backfill_region_conf`), which does not by itself fire.
#: M-INTEG's impact routing reads the same 0.70 assumption through its own
#: `HARNESS_INTEG_OCR_CONF_FLOOR` knob (design §3.9/CT-INTEG-09) — two knobs
#: for one assumption, so the consumer halves (#74/#75) can calibrate
#: independently; cross-check them when one moves.
OCR_CONF_FLOOR_ENV = "HARNESS_INGEST_OCR_CONF_FLOOR"


DEFAULT_OCR_CONF_FLOOR = 0.70


# --- adversarial-input safety (#42, FR-INGEST-33/34) ----------------------------------------------
#
# Design Configuration (§3.5) names the knobs `INGEST_STRIP_ACTIVE_CONTENT`,
# `INGEST_MAX_PAGES_PER_DOC`, `INGEST_MAX_DECOMPRESSED_BYTES`,
# `INGEST_MAX_IMAGE_PIXELS` and `INGEST_MAX_FILE_SECONDS`; the repo's convention
# prefixes the design's configuration names with `HARNESS_` (the same mapping that
# turned design `INGEST_DPI` into `HARNESS_INGEST_DPI`). The embedded-object ceiling
# the plan names only as "an embedded-object ceiling" is
# `HARNESS_INGEST_MAX_EMBEDDED_OBJECTS`.

#: Whether the sanitizer STRIPS the active constructs it finds (`FR-INGEST-33`).
#: Declared reading: this knob toggles strip versus REFUSE, never sanitize versus
#: process — set it to false and any detected active construct quarantines the
#: artifact, because processing unsanitized active content is the one outcome the
#: requirement exists to prevent.
STRIP_ACTIVE_CONTENT_ENV = "HARNESS_INGEST_STRIP_ACTIVE_CONTENT"


DEFAULT_STRIP_ACTIVE_CONTENT = True


#: The page ceiling per logical document (`FR-INGEST-34`), checked from the
#: sanitizer's structural read BEFORE any rasterization allocates.
MAX_PAGES_ENV = "HARNESS_INGEST_MAX_PAGES_PER_DOC"


DEFAULT_MAX_PAGES = 200


#: The total decompressed-byte ceiling per source file (`FR-INGEST-34`). The
#: sanitizer measures streams in bounded chunks and aborts the walk the moment the
#: running total crosses this — a decompression bomb quarantines WITHOUT full
#: decompression, which is the requirement's own acceptance form.
MAX_DECOMPRESSED_BYTES_ENV = "HARNESS_INGEST_MAX_DECOMPRESSED_BYTES"


DEFAULT_MAX_DECOMPRESSED_BYTES = 512 * 1024 * 1024


#: The pixel ceiling (`FR-INGEST-34`), enforced twice: against the DECLARED
#: dimensions of embedded images (from their dictionaries, before anything decodes
#: them — a 60000×60000 image is refused at ~3.6 GP before the renderer can
#: allocate it) and against the actual raster dimensions after rendering (a
#: belt-and-braces on the same bound).
MAX_IMAGE_PIXELS_ENV = "HARNESS_INGEST_MAX_IMAGE_PIXELS"


DEFAULT_MAX_IMAGE_PIXELS = 64_000_000


#: The per-file processing wall-clock ceiling in seconds (`FR-INGEST-34`). Checked
#: at the sanitizer's object boundaries and at per-page decode boundaries — a
#: boundary-cut ceiling, declared: a native decode cannot be preempted mid-flight,
#: only refused between flights.
MAX_FILE_SECONDS_ENV = "HARNESS_INGEST_MAX_FILE_SECONDS"


DEFAULT_MAX_FILE_SECONDS = 60.0


#: The embedded-object ceiling (`FR-INGEST-34`'s "embedded-object count"): the
#: sanitizer's graph walk counts the objects it visits and refuses the artifact
#: once the count crosses this, before allocating for the rest.
MAX_EMBEDDED_OBJECTS_ENV = "HARNESS_INGEST_MAX_EMBEDDED_OBJECTS"


DEFAULT_MAX_EMBEDDED_OBJECTS = 50_000


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


def _configured_resolution_floor() -> int:
    """The V0 resolution floor, read from its knob at call time; the default is the profile's 150.
    A floor below 1 would disable the gate, so it is refused."""
    raw = os.environ.get(RESOLUTION_FLOOR_ENV)
    if not raw:
        return DEFAULT_RESOLUTION_FLOOR
    try:
        floor = int(raw)
    except ValueError as error:
        raise IngestError(
            f"{RESOLUTION_FLOOR_ENV}={raw!r} is not an integer.") from error
    if floor < 1:
        raise IngestError(
            f"{RESOLUTION_FLOOR_ENV}={floor} is below 1 — a floor under 1 px "
            "would silently disable the resolution gate (FR-INGEST-21).")
    return floor


def _ocr_conf_floor() -> float:
    """The OCR confidence floor, read from its knob at call time; the default is the design's 0.70
    assumption. A value outside 0..1 would disable the check or flag every submission, so it is
    refused."""
    raw = os.environ.get(OCR_CONF_FLOOR_ENV)
    if not raw:
        return DEFAULT_OCR_CONF_FLOOR
    try:
        floor = float(raw)
    except ValueError as error:
        raise IngestError(
            f"{OCR_CONF_FLOOR_ENV}={raw!r} is not a number.") from error
    if not 0.0 <= floor <= 1.0 or not math.isfinite(floor):
        raise IngestError(
            f"{OCR_CONF_FLOOR_ENV}={raw!r} is outside the 0..1 confidence "
            "range.") from None
    return floor


def _configured_max_tokens() -> int:
    raw = os.environ.get(MAX_TOKENS_ENV)
    if not raw:
        return DEFAULT_MAX_TOKENS
    try:
        return int(raw)
    except ValueError as error:
        raise IngestError(f"{MAX_TOKENS_ENV}={raw!r} is not an integer.") from error
