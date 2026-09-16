"""M-INTEG — the integrity gate: span verification and the six-signal read model.

Design §3.9 (`M-INTEG`), issues #73 (the pure verifier) and #74 (the gate, the
signals, and the routing). R19/ADR-12 put this module OUTSIDE the extractor on
purpose: the code that produced the evidence must never be the code that
certifies it, so this file shares no code path with `aeh.extract` — the span
payload arrives through the injected extraction view, never through an import
(`CT-INTEG-05` pins the structure; the only first-party import here is the
store seam both modules read).

**What the gate does.** One call, `verify(run_id, submission_id, criterion_id)`,
re-derives the whole integrity picture from the ledger and the extraction view
and returns the six design-declared signals (`CT-INTEG-02`): whether every span
the extractor produced matches the document bytes exactly, whether any evidence
survived that check, whether the panel's sufficiency flags are clean, whether a
low-confidence transcription overlaps a cited span, whether the evidence lies
inside a described graphic, and whether a second extraction family disagrees.
Every read that can fail fails CLOSED (`CT-INTEG-03`): a fault yields the
adverse value, never the permissive one.

**The pure half.** `verify_span(doc, span)` is a module-level function of
(document bytes, span) and nothing else — no store read, no model call, no
network (NFR-INTEG-02). It never raises: any malformed input verifies False.
Coordinates are BYTE offsets into the canonical Markdown (CT-INGEST-03), so the
function compares `raw[start:end]` to the span text's UTF-8 encoding — no
normalization, no repair, no clamping (CT-INTEG-01/06: a mid-codepoint or
out-of-bounds span is rejected, not fixed).

**Fail-closed signal semantics** (each read's fault lands on the adverse side):

- span read fault, missing document, or the disabled switch → `spans_verified`
  False and `evidence_present` False;
- empty span set → `evidence_present` False, and `spans_verified` is vacuously
  True ONLY when the criterion does not require a citation (nothing was claimed,
  so nothing failed to match);
- region read fault (or a span read fault, which leaves the cited extents
  unknown) → `ocr_overlap_risk` True AND `described_evidence` True — both are
  routing-candidate values, and an unknown cannot be certified clear;
- panel read fault → `sufficiency_flag` True;
- second-family read fault → `extractor_disagreement` True (measured-and-adverse,
  never None: the second extraction ran, so "not measured" would be a lie);
- no second family at all → `extractor_disagreement` None, distinguishable from
  False by identity, never by truthiness.

**Routing.** Exactly one route fires per verify, in a fixed order, and every
route is a routing REQUEST — the module never writes a score row (FR-INTEG-08;
the whole write surface is the work ledger, the review queue, and the per-cell
rates):

1. verification failed → file a fresh re-extraction request (the ledger's
   attempt count grows in lockstep across the criterion's pending extract
   units, and a unit that has failed `INTEG_RETRY_LIMIT` times quarantines);
   when no evidence survived AND the criterion requires a citation, a review
   row is queued alongside the retry.
2. no evidence on a citation-requiring criterion → the same retry plus the
   review row (kept even though the locked signal semantics make it shadowed
   by route 1 — the fail-closed reading survives a future semantics change).
3. the panel's computed flags name a problem (any member reports the evidence
   insufficient) → the criterion's extract units are retried; on a REPEAT
   insufficiency two escalation score units join the ledger — the widened
   panel the ledger already knows how to express, never an automatic verdict.
4. a low-confidence transcription overlaps a cited span → a review row, so a
   human sees the text the machine was unsure of.
5. evidence lies wholly inside a described graphic → a review row and a review
   unit whose id carries the crop reference (FR-INTEG-05: retained and
   reachable in one action), gated behind `INTEG_DESCRIBED_EVIDENCE_ROUTES`.
Otherwise the criterion's extract units are released as done — verified
evidence needs no further extraction.

**Observability.** Every verify emits all six per-cell rates to the durable
ledger (`CT-INTEG-14`), positionally ordered by `INTEG_RATE_METRICS`, plus an
alert row wherever the span-verification failure rate crosses
`ALERT_SPAN_VERIFICATION_FAILURES`' threshold — a rate that moves only when the
extractor hallucinated, never when the data was the problem (an empty cell has
no verification to fail, and a read fault is a data problem, not a hallucination).
The sufficiency rate reads the consumer-facing flag, conservative default
included (`CT-INTEG-11`).

**The schema step.** Tier D migration 5 widens `run_metrics` with the criterion
dimension the per-cell rates require: the three legacy columns lead unchanged
(so the migration golden's positional fixture rows still fit), the two
dimension columns follow nullable (a legacy aggregate row has no cell), and the
declared primary key makes a re-emitted cell replace its earlier value rather
than stack a second one.

**Configuration** (seam rule 3 — every environment-sensitive value is read at
call time, production value the default): `INTEG_OCR_CONF_FLOOR` (Assumption
0.70; per-transcriber and unvalidated — no consumer may treat it as
calibrated), `INTEG_DESCRIBED_EVIDENCE_ROUTES` (default on),
`INTEG_SPAN_VERIFICATION_DISABLED` (the differential-timing seam the plan's own
oracle names), `INTEG_RETRY_LIMIT` (FR-EXTRACT-08's ladder, 3), and
`INTEG_ALERT_THRESHOLD` (default 0.10; an unreadable value lowers the threshold
to zero, which fires the alert rather than silencing it).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aeh.store import Migration, Statement, Tier, TIER_MIGRATIONS, open_store


# --- the schema step (the per-criterion dimension the rates are emitted under) -------------------

#: Tier D, migration 5: `run_metrics` rebuilt with the submission and criterion
#: dimensions. SQLite cannot add primary-key columns in place, so the rebuild
#: is the create-copy-drop-rename march — the same shape #97's narrative rekey
#: used. The three legacy columns lead **in their original order** on purpose:
#: the migration golden seeds fixture rows positionally by the table's leading
#: columns at every schema version, and one row shape that fits both the old
#: and the new table is what keeps that fixture honest across the rebuild.
#: The dimension columns are `NOT NULL DEFAULT ''` so a writer that omits them
#: (M-ORCH's three-column rate flush, the table's pre-#73 shape) still lands on
#: the declared primary key — with nullable dimensions, SQLite treats NULLs as
#: distinct in a non-INTEGER key, and M-ORCH's `INSERT OR REPLACE` would never
#: conflict with itself: every `progress()` flush would stack a fresh row per
#: metric instead of replacing it. The empty-string cell is the aggregate
#: dimension: the legacy row the golden seeds and every M-ORCH flush live
#: there, deduped by the key; the gate's full-cell upserts carry real
#: dimensions and REPLACE their own cell. The declared primary key is what
#: makes a re-emitted rate REPLACE the cell's earlier value instead of
#: stacking a second row.
_INTEG_DURABLE_005: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE run_metrics_dimensioned (
            run_id        TEXT NOT NULL,
            metric        TEXT NOT NULL,
            value         REAL NOT NULL,
            submission_id TEXT NOT NULL DEFAULT '',
            criterion_id  TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (run_id, metric, submission_id, criterion_id)
        )
        """
    ),
    Statement(
        """
        INSERT INTO run_metrics_dimensioned (run_id, metric, value)
        SELECT run_id, metric, value FROM run_metrics
        """
    ),
    Statement("DROP TABLE run_metrics"),
    Statement("ALTER TABLE run_metrics_dimensioned RENAME TO run_metrics"),
)

TIER_MIGRATIONS[Tier.DURABLE] = TIER_MIGRATIONS[Tier.DURABLE] + (
    Migration(version=5, name="integ_rate_dimensions", statements=_INTEG_DURABLE_005),
)


# --- the declared statements (FR-STORE-08: one literal each, keyword parameters) ------------------

#: Tier C, migration 25 (#363, `FR-INTEG-10`/`FR-INTEG-12`): the reads the gate makes on
#: every cell, and the column its idempotence record lives in.
#:
#: `read_document` filters `document` by `submission_id` and no migration had ever indexed that
#: column, so every `verify` scanned the table; the gate runs per cell, so the scan is per cell.
#: The index carries `document_id` as its second column because the read orders by it — the
#: seek and the order come from one structure rather than a scan plus a sort.
#:
#: `document_region.document_id` is an unindexed foreign-key child column, and
#: `StoreExtractionView.regions` reads it once per cell, so without the second index the view
#: this story publishes would add a full scan of `document_region` per cell to a module held to
#: 1% of run wall clock (`NFR-INTEG-01`). `position` rides along because the read orders by it.
#:
#: `panel_state` is `FR-INTEG-10`'s idempotence record. The requirement's words put it in
#: `cell_phase.units_consumed`, but that column is `INTEGER NOT NULL` and `ready_cells` parses
#: EVERY phase's value with `int()` — a panel state is a join of `work_id`s, so storing it
#: there made a shipped reader raise on the gate's own row. It gets its own TEXT column and
#: `units_consumed` keeps the meaning `FR-ORCH-28` gives it. Disclosed on the issue.
#:
#: `count_units` and `max_retry_attempts` are already served by `idx_wu_cell` (#362), which is
#: why this migration indexes `document` and `document_region` rather than `work_unit`.
_INTEG_READ_INDEXES: tuple[Statement, ...] = (
    Statement(
        "CREATE INDEX idx_document_submission ON document (submission_id, document_id)"
    ),
    Statement(
        "CREATE INDEX idx_document_region_doc ON document_region (document_id, position)"
    ),
    Statement("ALTER TABLE cell_phase ADD COLUMN panel_state TEXT"),
)

TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (
        Migration(version=25, name="integ_gate_reads_and_panel_state",
                  statements=_INTEG_READ_INDEXES),
    ), key=lambda m: m.version
))


INTEG_STATEMENTS: dict[str, Statement] = {
    # --- #363 (FR-INTEG-09): `StoreExtractionView`'s five reads ------------------------------
    "read_cell_evidence": Statement(
        "SELECT e.payload FROM evidence e JOIN work_unit w ON w.work_id = e.work_id "
        "WHERE w.submission_id = :submission_id AND w.criterion_id = :criterion_id "
        "AND w.stage = 'extract' ORDER BY e.work_id"
    ),
    "read_cell_evidence_in_run": Statement(
        "SELECT e.payload FROM evidence e JOIN work_unit w ON w.work_id = e.work_id "
        "WHERE w.run_id = :run_id AND w.submission_id = :submission_id "
        "AND w.criterion_id = :criterion_id AND w.stage = 'extract' ORDER BY e.work_id"
    ),
    "read_document_for_regions": Statement(
        "SELECT document_id, markdown FROM document WHERE submission_id = :submission_id "
        "ORDER BY document_id LIMIT 1"
    ),
    "read_document_regions": Statement(
        "SELECT region_id, document_id, element_kind, region_kind, description, "
        "retraction, content, ocr_conf, content_state, selection_state, selection, "
        "crop_ref, "
        "position FROM document_region WHERE document_id = :document_id ORDER BY position"
    ),
    "read_panel_sufficiency": Statement(
        "SELECT v.evidence_sufficient FROM verdict v "
        "JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.submission_id = :submission_id AND w.criterion_id = :criterion_id "
        "AND w.stage = 'score' ORDER BY v.work_id"
    ),
    "read_panel_sufficiency_in_run": Statement(
        "SELECT v.evidence_sufficient FROM verdict v "
        "JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.run_id = :run_id AND w.submission_id = :submission_id "
        "AND w.criterion_id = :criterion_id AND w.stage = 'score' ORDER BY v.work_id"
    ),
    # --- #363 (FR-INTEG-10): the idempotence key, and the phase it lives in -------------------
    "read_cell_panel_state": Statement(
        "SELECT work_id FROM work_unit WHERE run_id = :run_id "
        "AND submission_id = :submission_id AND criterion_id = :criterion_id "
        "AND stage IN ('extract', 'score') AND status IN ('done', 'quarantined') "
        "ORDER BY work_id"
    ),
    "read_integrity_post": Statement(
        "SELECT panel_state FROM cell_phase WHERE run_id = :run_id "
        "AND submission_id = :submission_id AND criterion_id = :criterion_id "
        "AND phase = 'integrity_post'"
    ),
    "write_integrity_post": Statement(
        "INSERT INTO cell_phase (run_id, submission_id, criterion_id, phase, "
        "units_consumed, panel_state, recorded_at) VALUES (:run_id, :submission_id, "
        ":criterion_id, 'integrity_post', :units_consumed, :panel_state, :recorded_at) "
        "ON CONFLICT (run_id, submission_id, criterion_id, phase) DO UPDATE SET "
        "units_consumed = excluded.units_consumed, "
        "panel_state = excluded.panel_state, recorded_at = excluded.recorded_at"
    ),
    "database_list": Statement("PRAGMA database_list"),
    "read_document": Statement(
        "SELECT document_id, markdown, content_hash FROM document "
        "WHERE submission_id = :submission_id ORDER BY document_id LIMIT 1"
    ),
    "count_units": Statement(
        "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :run_id AND "
        "submission_id = :submission_id AND criterion_id = :criterion_id"
    ),
    "count_verdicts": Statement(
        "SELECT COUNT(*) AS n FROM verdict WHERE work_id IN (SELECT work_id FROM "
        "work_unit WHERE run_id = :run_id AND submission_id = :submission_id AND "
        "criterion_id = :criterion_id)"
    ),
    "max_retry_attempts": Statement(
        "SELECT MAX(attempts) AS n FROM work_unit WHERE run_id = :run_id AND "
        "submission_id = :submission_id AND criterion_id = :criterion_id AND "
        "stage = 'extract' AND status IN ('pending', 'leased')"
    ),
    # The gate's own ledger entry for the cell — the routing request's ride. On a
    # failure route it is filed pending and the bump grows it with the criterion's
    # enumerated units; on the released path it is filed done, so a verified
    # criterion leaves no live extraction request behind.
    "insert_unit": Statement(
        "INSERT OR IGNORE INTO work_unit (work_id, run_id, submission_id, criterion_id, "
        "stage, status, attempts, origin) VALUES (:work_id, :run_id, :submission_id, "
        ":criterion_id, :stage, :status, :attempts, 'base')"
    ),
    # The retry: every PENDING OR LEASED extract unit for the cell moves in
    # lockstep — enumerated and gate-owned alike — and a unit at the ceiling
    # quarantines instead of retrying forever (FR-EXTRACT-08's ladder). Done and
    # quarantined units are outside the clause, so a completed unit survives a
    # failed verification untouched and the ladder stops at the quarantine.
    "bump_retries": Statement(
        "UPDATE work_unit SET status = CASE WHEN attempts + 1 >= :max_attempts THEN "
        "'quarantined' ELSE 'pending' END, attempts = attempts + 1 WHERE run_id = :run_id "
        "AND submission_id = :submission_id AND criterion_id = :criterion_id AND "
        "stage = 'extract' AND status IN ('pending', 'leased')"
    ),
    "mark_extract_done": Statement(
        "UPDATE work_unit SET status = 'done' WHERE run_id = :run_id AND "
        "submission_id = :submission_id AND criterion_id = :criterion_id AND "
        "stage = 'extract' AND status IN ('pending', 'leased')"
    ),
    "enqueue_review": Statement(
        "INSERT OR IGNORE INTO review_queue (queue_id, submission_id, criterion_id, "
        "reason) VALUES (:queue_id, :submission_id, :criterion_id, :reason)"
    ),
    # The described-evidence review unit: its id carries the crop reference, so the
    # teacher-review surface can resolve the image in one action (FR-INTEG-05).
    "insert_review_unit": Statement(
        "INSERT OR IGNORE INTO work_unit (work_id, run_id, submission_id, criterion_id, "
        "stage, status, attempts, origin) VALUES (:work_id, :run_id, :submission_id, "
        ":criterion_id, 'review', 'pending', 0, 'base')"
    ),
    # The repeat-insufficiency escalation: a widened panel the ledger expresses as
    # score units nobody has answered yet — a human queue and a verdict are mutually
    # exclusive outcomes of the same signal, and this module writes no verdict.
    "insert_escalation_unit": Statement(
        "INSERT OR IGNORE INTO work_unit (work_id, run_id, submission_id, criterion_id, "
        "stage, status, attempts, origin) VALUES (:work_id, :run_id, :submission_id, "
        ":criterion_id, 'score', 'pending', 0, 'escalation')"
    ),
    # The six per-cell rates, latest value wins; the alert rides the same
    # dimensioned surface so a fired alert names the cell it accuses.
    "upsert_metric": Statement(
        "INSERT OR REPLACE INTO run_metrics (run_id, metric, value, submission_id, "
        "criterion_id) VALUES (:run_id, :metric, :value, :submission_id, :criterion_id)"
    ),
    "upsert_alert": Statement(
        "INSERT OR REPLACE INTO run_metrics (run_id, metric, value, submission_id, "
        "criterion_id) VALUES (:run_id, :metric, :value, :submission_id, :criterion_id)"
    ),
}


#: The six per-criterion rates, in the design's declared order (§3.9):
#: span verification failure, empty evidence, low-confidence overlap, described
#: evidence, sufficiency flag, extractor disagreement. Position 0 is the rate
#: the alert sits on.
INTEG_RATE_METRICS = (
    "integ-span-verification-failure-rate",
    "integ-empty-evidence-rate",
    "integ-ocr-overlap-rate",
    "integ-described-evidence-rate",
    "integ-sufficiency-flag-rate",
    "integ-extractor-disagreement-rate",
)

#: The alert CT-INTEG-14 declares: a span-verification failure rate above a low
#: threshold means the extractor is hallucinating spans — a model or prompt
#: problem, not a data problem. A string OUTSIDE the six rates (it sits ON one).
ALERT_SPAN_VERIFICATION_FAILURES = "integ-span-verification-failure-alert"

#: The declared defaults (each overridable by its environment variable, above).
_DEFAULT_OCR_FLOOR = 0.70
_DEFAULT_RETRY_LIMIT = 3
_DEFAULT_ALERT_THRESHOLD = 0.10

_OCR_FLOOR_ENV = "INTEG_OCR_CONF_FLOOR"
_DESCRIBED_ROUTES_ENV = "INTEG_DESCRIBED_EVIDENCE_ROUTES"
_DISABLED_ENV = "INTEG_SPAN_VERIFICATION_DISABLED"
_RETRY_LIMIT_ENV = "INTEG_RETRY_LIMIT"
_ALERT_THRESHOLD_ENV = "INTEG_ALERT_THRESHOLD"


# --- env-gated knobs (read at call time, so a test can move them per scenario) --------------------


def _ocr_conf_floor_override() -> float:
    """The configured floor, or `inf` when unparseable — an unreadable floor
    flags every region rather than certifying any (the fail-closed reading)."""
    raw = os.environ.get(_OCR_FLOOR_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_OCR_FLOOR
    try:
        return float(raw)
    except ValueError:
        return math.inf


def _described_routes_enabled() -> bool:
    raw = os.environ.get(_DESCRIBED_ROUTES_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in ("false", "0", "off", "no")


def _verification_disabled() -> bool:
    """Whether the span-verification switch is explicitly set to a truthy value —
    the differential-timing seam the plan's own oracle names.

    A truthy spelling (`1`, `true`, `yes`, `on`) disables; everything else —
    unset, empty, `0`, `false`, `off`, `no`, garbage — leaves verification ON.
    The sibling knob (`_described_routes_enabled`) reads off-spellings as off;
    this is the same convention pointed the other way, so an operator's
    explicit `=false` cannot silently disable verification and route every
    cell to re-extraction."""
    raw = os.environ.get(_DISABLED_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _retry_limit() -> int:
    raw = os.environ.get(_RETRY_LIMIT_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_RETRY_LIMIT
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_RETRY_LIMIT
    return value if value >= 1 else _DEFAULT_RETRY_LIMIT


def _alert_threshold() -> float:
    raw = os.environ.get(_ALERT_THRESHOLD_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_ALERT_THRESHOLD
    try:
        return float(raw)
    except ValueError:
        return 0.0


# --- the duck-typed reads (a fault is a value: None means "could not read") -----------------------

#: The sentinel a gate read returns when the view itself faulted — distinct from
#: `None`, which for the second family means "no second extraction ran", a
#: measured absence the tri-state must preserve.
_FAULT = object()


def _document_raw_bytes(doc: Any) -> "bytes | None":
    """The document's canonical bytes, from whatever the caller handed over.

    A plain `str` IS the Markdown; bytes/bytearray are taken as-is; anything
    with a `.markdown` attribute (or a mapping under the `"markdown"` key)
    contributes that value's bytes. Anything else — including a read that
    raises — is a fault: `None`, and the caller treats the document as unread.
    """
    try:
        if isinstance(doc, (bytes, bytearray)):
            return bytes(doc)
        if isinstance(doc, str):
            return doc.encode("utf-8")
        markdown = getattr(doc, "markdown", None)
        if markdown is None and isinstance(doc, dict):
            markdown = doc.get("markdown")
        if isinstance(markdown, (bytes, bytearray)):
            return bytes(markdown)
        if isinstance(markdown, str):
            return markdown.encode("utf-8")
    except Exception:
        return None
    return None


def _span_item(span: Any) -> "tuple[int, int, bytes] | None":
    """One span as `(start, end, text_bytes)`, or None when malformed."""
    try:
        if isinstance(span, dict):
            start = span.get("start")
            end = span.get("end")
            text = span.get("text")
        else:
            start = getattr(span, "start", None)
            end = getattr(span, "end", None)
            text = getattr(span, "text", None)
        if not isinstance(start, int) or not isinstance(end, int):
            return None
        if isinstance(text, str):
            return (start, end, text.encode("utf-8"))
        if isinstance(text, (bytes, bytearray)):
            return (start, end, bytes(text))
    except Exception:
        return None
    return None


def _span_items(spans: Any) -> "list[tuple[int, int, bytes]] | None":
    """A span sequence as items, or None on any malformation (a fault)."""
    if isinstance(spans, (str, bytes, bytearray)):
        return None
    try:
        candidate = tuple(spans)
    except Exception:
        return None
    items: "list[tuple[int, int, bytes]]" = []
    for span in candidate:
        item = _span_item(span)
        if item is None:
            return None
        items.append(item)
    return items


def _region_items(regions: Any) -> "tuple[tuple[Any, int, int, Any, Any], ...] | None":
    """Regions as `(region_kind, start, end, ocr_conf, crop_ref)`, or None."""
    if isinstance(regions, (str, bytes, bytearray)):
        return None
    try:
        candidate = tuple(regions)
    except Exception:
        return None
    items: "list[tuple[Any, int, int, Any, Any]]" = []
    for region in candidate:
        if isinstance(region, dict):
            kind = region.get("region_kind")
            start = region.get("start")
            end = region.get("end")
            conf = region.get("ocr_conf")
            crop = region.get("crop_ref")
        else:
            kind = getattr(region, "region_kind", None)
            start = getattr(region, "start", None)
            end = getattr(region, "end", None)
            conf = getattr(region, "ocr_conf", None)
            crop = getattr(region, "crop_ref", None)
        if not isinstance(start, int) or not isinstance(end, int):
            return None
        items.append((kind, start, end, conf, crop))
    return tuple(items)


# --- the pure verifier (TC-INTEG-01/09, FUZZ-03, CT-INTEG-01) --------------------------------------


def verify_span(doc: Any, span: Any) -> bool:
    """Whether `span`'s bytes appear verbatim in `doc`'s canonical bytes.

    Pure, deterministic, zero-cost: a function of the document BYTES handed to
    it and the span's byte offsets — no store, no model, no network, and it
    never raises (a malformed document or span verifies False, NFR-INTEG-03's
    fail-closed reading applied to a pure function). The verdict is exactly the
    shared invariant: `0 <= start <= end <= len(raw)` AND
    `raw[start:end] == text.encode("utf-8")` — so a zero-length span at any
    in-bounds offset verifies, a span ending one byte past the document does
    not, and a boundary landing mid-codepoint is rejected rather than repaired.
    """
    try:
        raw = _document_raw_bytes(doc)
        if raw is None:
            return False
        item = _span_item(span)
        if item is None:
            return False
        start, end, text_bytes = item
        if start < 0 or end < start or end > len(raw):
            return False
        return raw[start:end] == text_bytes
    except Exception:
        return False


# --- the per-verify derivations (each read's fault lands on the adverse value) ---------------------


def _verification_outcome(
    raw: "bytes | None",
    span_items: "list[tuple[int, int, bytes]] | None",
    citation: bool,
) -> "tuple[bool, bool]":
    """`(spans_verified, evidence_present)` for this verify's span read.

    The disabled switch, a faulted span read, or an unreadable document all
    report `(False, False)` — nothing was verified, so no evidence can be
    claimed present (fail-closed, CT-INTEG-03). An EMPTY span set is the one
    measured absence: `evidence_present` is False, and `spans_verified` is
    vacuously True only when the criterion demands no citation (nothing was
    claimed, so nothing failed to match). With spans in hand, the verdict is
    the shared invariant over every span and evidence is present the moment
    ONE span passed."""
    if _verification_disabled():
        return (False, False)
    if raw is None or span_items is None:
        return (False, False)
    if not span_items:
        return (not citation, False)
    verdicts = [
        0 <= start <= end <= len(raw) and raw[start:end] == text_bytes
        for start, end, text_bytes in span_items
    ]
    return (all(verdicts), any(verdicts))


def _region_signals(
    region_items: "tuple[tuple[Any, int, int, Any, Any], ...] | None",
    span_items: "list[tuple[int, int, bytes]] | None",
    floor: float,
) -> "tuple[bool, bool, Any]":
    """`(ocr_overlap_risk, described_evidence, crop_ref)` for this verify.

    A faulted region read — or a span read that left the cited extents
    unknown — flags both routing-candidate values and carries no crop: an
    unknown overlap cannot be certified clear and an unknown placement cannot
    be certified outside a described graphic (CT-INTEG-03's fail-closed
    reading). With both reads healthy: an at-risk transcription is a region
    whose recorded confidence sits AT OR BELOW the floor and whose extent
    overlaps a cited span (half-open, so merely touching extents do not
    overlap); described evidence is a cited span lying WHOLLY inside one
    described-graphic region — geometric, regardless of whether the span
    verified."""
    if region_items is None or span_items is None:
        return (True, True, None)
    ocr_risk = False
    described = False
    crop_ref: Any = None
    for kind, r_start, r_end, conf, crop in region_items:
        if (
            conf is not None
            and conf <= floor
            and any(
                r_start < s_end and s_start < r_end
                for s_start, s_end, _ in span_items
            )
        ):
            ocr_risk = True
        if kind == "described_graphic" and not described:
            if any(
                r_start <= s_start and s_end <= r_end
                for s_start, s_end, _ in span_items
            ):
                described = True
                crop_ref = crop
    return (ocr_risk, described, crop_ref)


def _disagreement_verdict(
    second: Any,
    span_items: "list[tuple[int, int, bytes]] | None",
) -> "bool | None":
    """The extractor-disagreement tri-state for this verify.

    `None` only when no second family was configured — distinguishable from
    False by identity, never by truthiness. A faulted read or a malformed
    second payload reports True (measured-and-adverse: the second extraction
    ran, so "not measured" would be a lie); a healthy read reports whether the
    two families produced different span sets, fingerprinted by
    (start, end, text bytes) so the comparison is over the bytes themselves."""
    if second is _FAULT:
        return True
    if second is None:
        return None
    second_items = _span_items(second)
    if span_items is None or second_items is None:
        return True
    first_prints = {(start, end, text) for start, end, text in span_items}
    second_prints = {(start, end, text) for start, end, text in second_items}
    return first_prints != second_prints


def _computed_insufficient(panel_flags: "tuple[bool, ...] | None") -> bool:
    """The panel's COMPUTED insufficiency — the routing input, never the
    reported flag: any member reporting the evidence insufficient. A faulted
    panel read is insufficient (fail-closed)."""
    if panel_flags is None:
        return True
    return any(not flag for flag in panel_flags)


def _failure_rate(
    raw: "bytes | None",
    span_items: "list[tuple[int, int, bytes]] | None",
    verified: bool,
) -> float:
    """The cell's span-verification failure rate (1.0 or 0.0).

    A rate that moves only when the extractor hallucinated: 1.0 when spans
    were READ — the document resolved and at least one span arrived — and
    verification still failed. An empty cell had no verification to fail, and
    a read fault is a data problem, not a hallucination; neither moves it."""
    if raw is not None and span_items and not verified:
        return 1.0
    return 0.0


# --- the returned signal surface (CT-INTEG-02: six fields, by set equality) ------------------------


@dataclass(frozen=True)
class IntegritySignals:
    """The six signals, and nothing else (FR-INTEG-01; CT-INTEG-04's output half).

    `extractor_disagreement` is tri-state: `None` when no second extraction ran,
    `True`/`False` when one ran and disagreed/agreed — a consumer collapsing
    `None` into `False` reads "not measured" as "measured, and fine"."""

    spans_verified: bool
    evidence_present: bool
    sufficiency_flag: bool
    ocr_overlap_risk: bool
    described_evidence: bool
    extractor_disagreement: "bool | None"


# --- the gate ---------------------------------------------------------------------------------------


#: `FR-INTEG-11`: how many verified documents one gate instance holds. 64 is a class's worth of
#: submissions — the working set of a single run's pass — and the bound exists because the
#: cache holds whole documents: an unbounded one on a large cohort is a memory leak with a
#: helpful name. Read at call time (seam 3), and refused loudly when it is not a positive
#: integer: a zero or a negative would silently disable the cache the requirement asks for.
INTEG_DOCUMENT_CACHE_ENTRIES: int = 64
INTEG_DOCUMENT_CACHE_ENTRIES_ENV = "HARNESS_INTEG_DOCUMENT_CACHE_ENTRIES"


def _document_cache_entries() -> int:
    """The document cache's bound, read at call time."""
    raw = os.environ.get(INTEG_DOCUMENT_CACHE_ENTRIES_ENV)
    if raw is None or raw.strip() == "":
        return INTEG_DOCUMENT_CACHE_ENTRIES
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(
            f"environment knob {INTEG_DOCUMENT_CACHE_ENTRIES_ENV}={raw!r} is not an integer."
        ) from error
    if value < 1:
        raise ValueError(
            f"environment knob {INTEG_DOCUMENT_CACHE_ENTRIES_ENV}={raw!r} must be at least 1: "
            "a zero or negative bound would disable the cache FR-INTEG-11 requires, silently."
        )
    return value


class StoreExtractionView:
    """The extraction view the gate reads in production (`FR-INTEG-09`).

    `M-INTEG` publishes it because the five reads ARE this module's declared *Requires*
    surface (`CT-INTEG-17`): `spans`, `second_family_spans`, `regions`, `panel_sufficiency` and
    `criterion_requires_citation`. A test double that implements the same five is a double of
    THIS, which is what keeps the doubles honest.

    Constructed as `StoreExtractionView(handle, catalog, package_version_id)`: the cohort
    handle the evidence and regions live on, the package catalog the criterion's citation
    requirement is declared in, and the version that declaration belongs to.

    **Every read raises on a fault** — it never substitutes an empty result. That is the whole
    contract: the gate's fail-closed routing reads an exception as "adverse and unknown", and a
    view that returned `[]` for a faulted evidence read would tell it "measured, and there is
    nothing", which is the one lie the gate cannot detect (`NFR-INTEG-03`).
    """

    def __init__(self, handle: Any, catalog: Any, package_version_id: str,
                 run_id: str = "") -> None:
        self._handle = handle
        self._catalog = catalog
        self._package_version_id = package_version_id
        self._run_id = run_id

    def _cell_query(self, key: str, submission_id: str, criterion_id: str) -> list:
        """One cell read, scoped to this view's run when it has one."""
        if self._run_id:
            return list(self._handle.query(
                INTEG_STATEMENTS[f"{key}_in_run"], run_id=self._run_id,
                submission_id=submission_id, criterion_id=criterion_id,
            ))
        return list(self._handle.query(
            INTEG_STATEMENTS[key],
            submission_id=submission_id, criterion_id=criterion_id,
        ))

    def _payloads(self, submission_id: str, criterion_id: str) -> list:
        """Every extraction payload the cell carries, in `work_id` order.

        A cell that was re-extracted has more than one, and the last is the current
        one — reading only the first would hand the gate the rejected extraction
        forever, which quarantines a cell whose re-extraction actually succeeded.
        """
        payloads = []
        for row in self._cell_query("read_cell_evidence", submission_id, criterion_id):
            payload = row["payload"]
            if payload is None:
                continue
            if isinstance(payload, (bytes, bytearray)):
                payload = bytes(payload).decode("utf-8")
            payloads.append(json.loads(payload))
        return payloads

    def _payload(self, submission_id: str, criterion_id: str) -> dict:
        """The cell's CURRENT extraction payload — the last one written."""
        payloads = self._payloads(submission_id, criterion_id)
        return payloads[-1] if payloads else {}

    def spans(self, submission_id: str, criterion_id: str) -> list:
        """The cell's extracted spans, as `M-EXTRACT` wrote them.

        Every payload's spans, not just the current one's: a span the gate has already
        verified stays verified, and a re-extraction that dropped it should not make the
        cell read as though the evidence had never been found."""
        spans: list = []
        for payload in self._payloads(submission_id, criterion_id):
            spans.extend(payload.get("spans") or ())
        return spans

    def second_family_spans(self, submission_id: str, criterion_id: str) -> "list | None":
        """The second family's spans, or `None` where no second family ran — `None` is
        "not measured" and the gate reads it as such, never as agreement."""
        second = self._payload(submission_id, criterion_id).get("second_family")
        if not isinstance(second, dict) or "spans" not in second:
            return None
        return list(second.get("spans") or ())

    def regions(self, document_id: str) -> list:
        """The document's stored regions, in position order, each carrying its extent.

        The gate asks by its own `doc-<submission_id>` spelling; the store's document ids
        are minted (`doc-<uuid12>`), so the request resolves through the submission foreign
        key. `document_region` stores no byte extents, so each region's is located by
        finding its stored content in the canonical Markdown — in BYTES, the units
        `verify_span` compares in — with a cursor advancing in row order, so a document
        that repeats a region's content addresses successive occurrences rather than
        collapsing them onto the first.

        A region whose content the canonical text no longer carries takes a zero-length
        extent at the cursor: present and measured, overlapping nothing. It is not dropped,
        because a dropped region is indistinguishable from a document that never had one.
        """
        submission_id = (
            document_id[len("doc-"):] if document_id.startswith("doc-") else document_id
        )
        docs = self._handle.query(
            INTEG_STATEMENTS["read_document_for_regions"], submission_id=submission_id
        )
        if not docs:
            return []
        markdown = docs[0]["markdown"] or ""
        raw = markdown.encode("utf-8") if isinstance(markdown, str) else bytes(markdown)
        items: list = []
        cursor = 0
        for row in self._handle.query(
            INTEG_STATEMENTS["read_document_regions"], document_id=docs[0]["document_id"]
        ):
            region = dict(row)
            content = region.get("content") or ""
            needle = content.encode("utf-8") if isinstance(content, str) else bytes(content)
            start = raw.find(needle, cursor) if needle else cursor
            if start < 0:
                start = cursor
                needle = b""
            region["start"] = start
            region["end"] = start + len(needle)
            cursor = max(cursor, start)
            items.append(region)
        return items

    def panel_sufficiency(self, submission_id: str, criterion_id: str) -> tuple:
        """Each landed verdict's `evidence_sufficient` answer for the cell, in `work_id`
        order — the panel's own flags, never a computed substitute."""
        return tuple(
            None if row["evidence_sufficient"] is None else bool(row["evidence_sufficient"])
            for row in self._cell_query(
                "read_panel_sufficiency", submission_id, criterion_id
            )
        )

    def criterion_requires_citation(self, criterion_id: str) -> bool:
        """Whether the criterion's declaration requires cited evidence (`M-PKG`'s own
        reading, read through the catalog rather than re-derived here)."""
        for row in self._catalog.criteria(self._package_version_id):
            row_id = row["criterion_id"] if isinstance(row, dict) else row.get("criterion_id")
            if str(row_id) == str(criterion_id):
                value = (row.get("evidence_type") if isinstance(row, dict)
                         else getattr(row, "evidence_type", None))
                # Fail closed on NULL as well as on absence. `evidence_type` is nullable
                # TEXT with no CHECK and one writer (`M-PKG`'s read-back), so NULL means
                # "not declared", not "declared as needing nothing" — and reading it as the
                # latter releases a zero-span cell as verified, which is the outcome
                # `FR-INTEG-03` exists to prevent.
                return value is None or str(value) != "none"
        return True  # fail-closed: an undeclared criterion is read as requiring citation


class IntegrityGate:
    """The verification-and-routing half of M-INTEG (design §3.9's Protocol).

    `handle` is the cohort handle documents and the work ledger are read
    through; `blobs` the content-addressed store a superseded document and a
    described region's crop resolve through; `extraction_view` the injected
    read model standing in for the extractor and the panel. `ocr_conf_floor`
    overrides the `INTEG_OCR_CONF_FLOOR` configuration; None (the default)
    reads the environment, whose own default is the declared Assumption.
    """

    def __init__(self, handle: Any, blobs: Any, extraction_view: Any,
                 ocr_conf_floor: "float | None" = None) -> None:
        self._handle = handle
        self._blobs = blobs
        self._view = extraction_view
        self._floor_override = ocr_conf_floor
        self._durable_store: Any = None
        self._durable: Any = None
        #: `FR-INTEG-11`: the canonical document bytes, cached per (run, content_hash) for
        #: this gate instance. The gate runs per CELL and a submission has many cells, so the
        #: uncached path re-read and re-hashed the same document once per criterion — the
        #: measurable part of the gate's share of run wall clock (`NFR-INTEG-01`, GAP-24).
        #: The content-hash re-verification runs once per entry, on the way in: a cached entry
        #: is one whose hash has already been checked against its own bytes.
        self._document_cache: "OrderedDict[tuple[str, str], bytes]" = OrderedDict()
        #: The cells this gate instance has already routed, with the panel state it routed on
        #: (`FR-INTEG-10`). Read from `cell_phase` when this instance has not seen the cell.
        self._routed_state: dict[tuple[str, str, str], str] = {}

    # -- reads ---------------------------------------------------------------------------------------

    def _document_bytes(self, submission_id: str, run_id: str = "") -> "bytes | None":
        """The submission's canonical document bytes, or None on any fault.

        The row's Markdown column is the canonical text when it carries one;
        otherwise the content-addressed blob named by `content_hash` is. The
        hash is re-verified against the bytes actually read either way — a
        superseded document is a read fault, never a stale acceptance
        (CT-INGEST-02's immutability, from the consumer's side).

        Cached per `(run, content_hash)` within this gate instance (`FR-INTEG-11`): the
        document row is still read to learn the hash — that read is what notices a superseded
        document — but the BYTES and their verification are paid once. The cache is an LRU
        bounded by `HARNESS_INTEG_DOCUMENT_CACHE_ENTRIES` (default 64), read at call time."""
        try:
            rows = self._handle.query(
                INTEG_STATEMENTS["read_document"], submission_id=submission_id
            )
        except Exception:
            return None
        if not rows:
            return None
        row = rows[0]
        markdown = row["markdown"]
        stored_hash = row["content_hash"]
        if isinstance(stored_hash, str) and stored_hash:
            cached = self._document_cache.get((run_id, stored_hash))
            if cached is not None:
                # Already read, already hash-verified against these very bytes. Re-verifying
                # would re-answer a question whose answer cannot have changed: the hash IS the
                # identity, so a different document is a different key.
                self._document_cache.move_to_end((run_id, stored_hash))
                return cached
        raw: "bytes | None" = None
        if isinstance(markdown, str) and markdown:
            raw = markdown.encode("utf-8")
        elif isinstance(stored_hash, str) and stored_hash:
            try:
                data = self._blobs.get(stored_hash)
            except Exception:
                return None
            if isinstance(data, (bytes, bytearray)):
                raw = bytes(data)
        if not isinstance(raw, bytes):
            return None
        if not isinstance(stored_hash, str) or hashlib.sha256(raw).hexdigest() != stored_hash:
            return None
        self._cache_document(run_id, stored_hash, raw)
        return raw

    def _cache_document(self, run_id: str, content_hash: str, raw: bytes) -> None:
        """Hold one verified document, evicting the least recently used past the bound."""
        limit = _document_cache_entries()
        cache = self._document_cache
        cache[(run_id, content_hash)] = raw
        cache.move_to_end((run_id, content_hash))
        while len(cache) > limit:
            cache.popitem(last=False)

    def _spans(self, submission_id: str, criterion_id: str) -> "list[tuple[int, int, bytes]] | None":
        """The extraction's spans for the cell, or None when the read faults."""
        try:
            return _span_items(self._view.spans(submission_id, criterion_id))
        except Exception:
            return None

    def _regions(self, document_id: str) -> "tuple[tuple[Any, int, int, Any, Any], ...] | None":
        try:
            return _region_items(self._view.regions(document_id))
        except Exception:
            return None

    def _panel_flags(self, submission_id: str, criterion_id: str) -> "tuple[bool, ...] | None":
        """Per-judge sufficiency flags, or None when the read faults or the
        answer is not a sequence of plain booleans."""
        try:
            panel = self._view.panel_sufficiency(submission_id, criterion_id)
            flags = getattr(panel, "evidence_sufficient", None)
            if flags is None and isinstance(panel, (tuple, list)):
                flags = panel
            if isinstance(flags, (tuple, list)) and flags and all(
                isinstance(flag, bool) for flag in flags
            ):
                return tuple(flags)
        except Exception:
            return None
        return None

    def _requires_citation(self, criterion_id: str) -> bool:
        """Whether the criterion's evidence type requires a citation — True on
        any fault, the routing-conservative reading (FR-INTEG-03)."""
        try:
            value = self._view.criterion_requires_citation(criterion_id)
        except Exception:
            return True
        return value if isinstance(value, bool) else True

    def _second_family(self, submission_id: str, criterion_id: str) -> Any:
        try:
            return self._view.second_family_spans(submission_id, criterion_id)
        except Exception:
            return _FAULT

    def _max_pending_attempts(
        self, run_id: str, submission_id: str, criterion_id: str,
    ) -> "int | None":
        """The highest attempt count among the cell's live extract units, read
        BEFORE this verify's bump — the repeat detector behind route 3's
        escalation half. A read fault returns None, which suppresses the
        escalation rather than firing it (the escalation is a widening, not a
        safety action; its trigger must be measured, not assumed)."""
        try:
            rows = self._handle.query(
                INTEG_STATEMENTS["max_retry_attempts"],
                run_id=run_id,
                submission_id=submission_id,
                criterion_id=criterion_id,
            )
        except Exception:
            return None
        if not rows:
            return None
        value = rows[0]["n"]
        return None if value is None else int(value)

    def _sufficiency_flag(
        self,
        run_id: str,
        submission_id: str,
        criterion_id: str,
        panel_flags: "tuple[bool, ...] | None",
    ) -> bool:
        """The REPORTED sufficiency flag: conservative while the cell is
        unjudged, computed once verdicts exist.

        Until the cell carries BOTH work units and verdict rows, a panel read
        cannot be believed either way — the flags describe judges who have not
        answered — so the flag reports True (the adverse value the consumer
        must act on). A faulted panel read is True outright. Once verdicts
        exist, the computed reading — any member reporting the evidence
        insufficient — is the answer (`CT-INTEG-11`)."""
        if panel_flags is None:
            return True
        try:
            unit_rows = self._handle.query(
                INTEG_STATEMENTS["count_units"],
                run_id=run_id,
                submission_id=submission_id,
                criterion_id=criterion_id,
            )
            verdict_rows = self._handle.query(
                INTEG_STATEMENTS["count_verdicts"],
                run_id=run_id,
                submission_id=submission_id,
                criterion_id=criterion_id,
            )
        except Exception:
            return True
        units = int(unit_rows[0]["n"]) if unit_rows else 0
        verdicts = int(verdict_rows[0]["n"]) if verdict_rows else 0
        if units == 0 or verdicts == 0:
            return True
        return any(not flag for flag in panel_flags)

    # -- the durable metrics surface (opened lazily, cached per gate) --------------------------------

    def _metrics_target(self) -> Any:
        """The durable handle the per-cell rates are written through.

        The cohort file lives under the store's `cohorts/` directory, so the
        file this handle's own connection has open names the data directory two
        parents up — the same directory `open_store` was given. Opened on the
        first emission and cached: the metrics path must not cost the timed
        verifier a store open per call (the differential's shared base).

        Deliberate reading, disclosed: a fault on this surface (no main
        database file reachable from the handle, a refused durable open, a
        failing metrics transaction) RAISES out of `verify()` after the
        routing writes have committed — the caller gets an exception, not six
        signals. That is fail-closed by exception rather than by value: nothing
        downstream can read the missing rates as a clean bill of health, and
        the review's alternative — swallowing the fault to return signals —
        would emit nothing while reporting success, the silent-failure shape
        the four seams exist to prevent. TC-INTEG-08's fault model covers the
        six SIGNAL reads; the metrics write surface failing is an environment
        fault the run's error path owns."""
        if self._durable is None:
            rows = self._handle.query(INTEG_STATEMENTS["database_list"])
            main_file = ""
            for row in rows:
                if row["name"] == "main":
                    main_file = row["file"]
                    break
            if not main_file:
                raise RuntimeError(
                    "IntegrityGate could not locate its cohort database file — the durable "
                    "rate surface is unreachable from a handle with no main database file"
                )
            self._durable_store = open_store(Path(main_file).parent.parent)
            self._durable = self._durable_store.durable()
        return self._durable

    def _emit_metrics(
        self,
        run_id: str,
        submission_id: str,
        criterion_id: str,
        *,
        present: bool,
        ocr_risk: bool,
        described: bool,
        sufficiency: bool,
        disagreement: "bool | None",
        failure_value: float,
    ) -> None:
        """Emit all six per-cell rates for this cell — latest value wins.

        The keys below are the SIGNAL names, zipped positionally against
        `INTEG_RATE_METRICS`: declared write set and emission order in one
        literal, so a seventh signal or a reordered tuple fails the write-set
        case rather than sliding past it. Every verify emits all six, whatever
        the routing did (`CT-INTEG-14`'s per-criterion emission). The alert
        rides the same cell only where the failure rate crosses the
        threshold — a fired alert names the cell it accuses."""
        values = {
            "spans_verified": failure_value,
            "evidence_present": 0.0 if present else 1.0,
            "ocr_overlap_risk": 1.0 if ocr_risk else 0.0,
            "described_evidence": 1.0 if described else 0.0,
            "sufficiency_flag": 1.0 if sufficiency else 0.0,
            "extractor_disagreement": 1.0 if disagreement is True else 0.0,
        }
        durable = self._metrics_target()
        with durable.transaction() as tx:
            for signal_name, metric_name in zip(values, INTEG_RATE_METRICS):
                tx.execute(
                    INTEG_STATEMENTS["upsert_metric"],
                    run_id=run_id,
                    metric=metric_name,
                    value=values[signal_name],
                    submission_id=submission_id,
                    criterion_id=criterion_id,
                )
            if failure_value > _alert_threshold():
                tx.execute(
                    INTEG_STATEMENTS["upsert_alert"],
                    run_id=run_id,
                    metric=ALERT_SPAN_VERIFICATION_FAILURES,
                    value=failure_value,
                    submission_id=submission_id,
                    criterion_id=criterion_id,
                )

    # -- routing writes ------------------------------------------------------------------------------

    def _own_unit_id(self, run_id: str, submission_id: str, criterion_id: str) -> str:
        return f"integ-unit-{run_id}-{submission_id}-{criterion_id}"

    def _bump_retries(self, run_id: str, submission_id: str, criterion_id: str) -> None:
        with self._handle.transaction() as tx:
            tx.execute(
                INTEG_STATEMENTS["bump_retries"],
                run_id=run_id,
                submission_id=submission_id,
                criterion_id=criterion_id,
                max_attempts=_retry_limit(),
            )

    def _enqueue_review(self, submission_id: str, criterion_id: str, reason: str) -> None:
        queue_id = f"integ-{reason}-{submission_id}-{criterion_id}"
        with self._handle.transaction() as tx:
            tx.execute(
                INTEG_STATEMENTS["enqueue_review"],
                queue_id=queue_id,
                submission_id=submission_id,
                criterion_id=criterion_id,
                reason=reason,
            )

    # -- the verify ----------------------------------------------------------------------------------

    def _panel_state(
        self, run_id: str, submission_id: str, criterion_id: str
    ) -> str | None:
        """The cell's panel state (`FR-INTEG-10`): its terminal extract and score `work_id`s.

        A string rather than a count, because the question is "has the evidence MOVED", and
        two units finishing while two others were requeued is not the same panel. A faulted
        read returns `None` — a sentinel, not a reserved string, because any string is a
        panel state some cell's `work_id`s could join to — so a gate that cannot see the
        ledger burns its retry rather than silently deciding it already had."""
        try:
            rows = self._handle.query(
                INTEG_STATEMENTS["read_cell_panel_state"],
                run_id=run_id, submission_id=submission_id, criterion_id=criterion_id,
            )
        except Exception:
            return None
        return ",".join(str(row["work_id"]) for row in rows)

    def _already_routed(
        self, run_id: str, submission_id: str, criterion_id: str, panel_state: str | None
    ) -> bool:
        """Whether this cell was already routed on exactly this panel state."""
        if panel_state is None:
            return False
        key = (run_id, submission_id, criterion_id)
        seen = self._routed_state.get(key)
        if seen is None:
            try:
                rows = self._handle.query(
                    INTEG_STATEMENTS["read_integrity_post"],
                    run_id=run_id, submission_id=submission_id, criterion_id=criterion_id,
                )
            except Exception:
                return False
            if not rows:
                return False
            seen = "" if rows[0]["panel_state"] is None else str(rows[0]["panel_state"])
            self._routed_state[key] = seen
        # A cell with no terminal units yet has the EMPTY panel state, and two calls over that
        # same emptiness are still the same call: comparing truthiness rather than equality
        # would make the commonest case — a cell routed before any unit finished — dedupe
        # never, which is exactly the retry-burning FR-INTEG-10 is about.
        return seen == panel_state

    def _record_routed(
        self, run_id: str, submission_id: str, criterion_id: str, panel_state: str | None
    ) -> None:
        """Record the panel state this cell was routed on, in `cell_phase`.

        Best-effort, deliberately: a gate that cannot write the phase keeps the record in
        memory for this instance and re-routes after a restart. Re-routing costs a retry;
        refusing to have routed would lose the route itself."""
        if panel_state is None:
            return
        self._routed_state[(run_id, submission_id, criterion_id)] = panel_state
        try:
            with self._handle.transaction() as tx:
                tx.execute(
                    INTEG_STATEMENTS["write_integrity_post"],
                    run_id=run_id, submission_id=submission_id, criterion_id=criterion_id,
                    # The count is what `FR-ORCH-28` declares the column to mean, and what
                    # `ready_cells` parses; the identity rides its own TEXT column.
                    units_consumed=len([w for w in panel_state.split(",") if w]),
                    panel_state=panel_state,
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                )
        except Exception:
            # The in-memory record still stands for this instance; a gate that could not
            # write the phase is not a gate that should refuse to have routed.
            return

    def verify(self, run_id: str, submission_id: str, criterion_id: str) -> IntegritySignals:
        """Re-derive the six signals for one cell, route on them, emit the rates.

        Every read is fault-injected (a raising view method, a malformed
        payload, a missing document) and every fault lands on the adverse
        value; routing is exactly one route per call; the metrics surface
        always emits. Returns the six fields and nothing else."""
        raw = self._document_bytes(submission_id, run_id)
        span_items = self._spans(submission_id, criterion_id)
        citation = self._requires_citation(criterion_id)

        verified, present = _verification_outcome(
            raw, span_items, citation,
        )

        region_items = self._regions(f"doc-{submission_id}")
        floor = (
            float(self._floor_override)
            if self._floor_override is not None
            else _ocr_conf_floor_override()
        )
        ocr_risk, described, crop_ref = _region_signals(
            region_items, span_items, floor,
        )

        panel_flags = self._panel_flags(submission_id, criterion_id)
        sufficiency = self._sufficiency_flag(
            run_id, submission_id, criterion_id, panel_flags,
        )
        disagreement = _disagreement_verdict(
            self._second_family(submission_id, criterion_id), span_items,
        )

        # -- idempotence (`FR-INTEG-10`) ------------------------------------------------------
        # A repeat call on an UNCHANGED panel state routes nothing: no unit, no queue row, no
        # metric, and — the case that bit — no `bump_retries`, which increments on every call
        # and would otherwise burn a retry the cell never used. The key is the cell's terminal
        # extract and score `work_id`s, recorded in `cell_phase`'s `integrity_post` row
        # (`FR-ORCH-28`), so the answer survives the process that computed it: a composition
        # layer that verifies, restarts, and verifies again must not re-route either.
        #
        # A CHANGED panel state may route again, which is the point of keying on state rather
        # than on a boolean: an escalation's verdicts landing is exactly the new evidence the
        # gate should look at.
        #
        # The check is asked HERE, at the first write, rather than at the top of `verify`: a
        # call that routes nothing must not pay for two reads it has no use for
        # (`NFR-INTEG-01`'s 1% budget is measured over exactly those calls).
        panel_state = self._panel_state(run_id, submission_id, criterion_id)
        repeat = self._already_routed(run_id, submission_id, criterion_id, panel_state)

        # -- routing: exactly one route per call, in the declared order ------------------------------
        # The repeat is the FIRST arm, and the one that routes nothing: suppressing the whole
        # chain rather than only the bump is what the clause asks for. Suppressing only the
        # bump was tried and measured — the sufficiency arm's repeat half reads the bumped
        # `attempts` back and inserts two escalation units, so a bare repeat still wrote two
        # `work_unit` rows against a clause whose words are "writes no additional `work_unit`,
        # `review_queue` or `run_metrics` row".
        if repeat:
            pass
        elif verified is False:
            with self._handle.transaction() as tx:
                tx.execute(
                    INTEG_STATEMENTS["insert_unit"],
                    work_id=self._own_unit_id(run_id, submission_id, criterion_id),
                    run_id=run_id,
                    submission_id=submission_id,
                    criterion_id=criterion_id,
                    stage="extract",
                    status="pending",
                    attempts=0,
                )
            self._bump_retries(run_id, submission_id, criterion_id)
            if present is False and citation:
                self._enqueue_review(submission_id, criterion_id, "empty-evidence")
        elif present is False and citation:
            # Shadowed under the locked signal semantics (an empty or faulted
            # span read already verified False); kept so the fail-closed route
            # survives any future relaxation of the verification signal.
            with self._handle.transaction() as tx:
                tx.execute(
                    INTEG_STATEMENTS["insert_unit"],
                    work_id=self._own_unit_id(run_id, submission_id, criterion_id),
                    run_id=run_id,
                    submission_id=submission_id,
                    criterion_id=criterion_id,
                    stage="extract",
                    status="pending",
                    attempts=0,
                )
            self._bump_retries(run_id, submission_id, criterion_id)
            self._enqueue_review(submission_id, criterion_id, "empty-evidence")
        elif sufficiency_input := _computed_insufficient(panel_flags):
            with self._handle.transaction() as tx:
                tx.execute(
                    INTEG_STATEMENTS["insert_unit"],
                    work_id=self._own_unit_id(run_id, submission_id, criterion_id),
                    run_id=run_id,
                    submission_id=submission_id,
                    criterion_id=criterion_id,
                    stage="extract",
                    status="pending",
                    attempts=0,
                )
            pre_attempts = self._max_pending_attempts(run_id, submission_id, criterion_id)
            self._bump_retries(run_id, submission_id, criterion_id)
            if pre_attempts is not None and pre_attempts >= 1:
                # The repeat half: widen the criterion's score units — the
                # escalation shape the ledger already knows how to express.
                with self._handle.transaction() as tx:
                    for ordinal in ("a", "b"):
                        tx.execute(
                            INTEG_STATEMENTS["insert_escalation_unit"],
                            work_id=(
                                f"integ-escalate-{run_id}-{submission_id}-"
                                f"{criterion_id}-{ordinal}"
                            ),
                            run_id=run_id,
                            submission_id=submission_id,
                            criterion_id=criterion_id,
                        )
        elif ocr_risk:
            self._enqueue_review(submission_id, criterion_id, "ocr-overlap-risk")
        elif described and _described_routes_enabled():
            review_id = f"integ-review-{run_id}-{submission_id}-{criterion_id}"
            if crop_ref:
                review_id = f"{review_id}-{crop_ref}"
            with self._handle.transaction() as tx:
                tx.execute(
                    INTEG_STATEMENTS["insert_review_unit"],
                    work_id=review_id,
                    run_id=run_id,
                    submission_id=submission_id,
                    criterion_id=criterion_id,
                )
            self._enqueue_review(submission_id, criterion_id, "described-evidence")
        else:
            with self._handle.transaction() as tx:
                tx.execute(
                    INTEG_STATEMENTS["insert_unit"],
                    work_id=self._own_unit_id(run_id, submission_id, criterion_id),
                    run_id=run_id,
                    submission_id=submission_id,
                    criterion_id=criterion_id,
                    stage="extract",
                    status="done",
                    attempts=0,
                )
                tx.execute(
                    INTEG_STATEMENTS["mark_extract_done"],
                    run_id=run_id,
                    submission_id=submission_id,
                    criterion_id=criterion_id,
                )

        # -- observability: the six per-cell rates, latest value wins --------------------------------
        failure_value = _failure_rate(raw, span_items, verified)
        self._emit_metrics(
            run_id, submission_id, criterion_id,
            present=present, ocr_risk=ocr_risk, described=described,
            sufficiency=sufficiency, disagreement=disagreement,
            failure_value=failure_value,
        )
        # The cell routed on this panel state; a repeat call with the same state will not
        # (`FR-INTEG-10`). Recorded AFTER the routing, so a route that raised is not recorded
        # as having happened, and only when this call was the one that routed.
        if not repeat:
            self._record_routed(run_id, submission_id, criterion_id, panel_state)
        return IntegritySignals(
            spans_verified=verified,
            evidence_present=present,
            sufficiency_flag=sufficiency,
            ocr_overlap_risk=ocr_risk,
            described_evidence=described,
            extractor_disagreement=disagreement,
        )

    def verify_span(self, doc: Any, span: Any) -> bool:
        """The Protocol's second member (design §3.9's `IntegrityGate`), the
        pure verifier as a method of the gate that holds the store seams.

        A pure delegation to the module-level `verify_span`: the rung-0 cases
        (TC-INTEG-01/09, FUZZ-03) call the function because they have no gate to
        construct, and a consumer holding the Protocol calls the method — one
        computation, two spellings, neither carrying state the other lacks. The
        method adds nothing around the call (no floor, no view, no ledger): a
        span verdict is a function of the bytes and the span alone, and a gate
        that enriched it would be a second verifier."""
        return verify_span(doc, span)


__all__ = [
    "ALERT_SPAN_VERIFICATION_FAILURES",
    "INTEG_RATE_METRICS",
    "INTEG_STATEMENTS",
    "IntegrityGate",
    "IntegritySignals",
    "verify_span",
]
