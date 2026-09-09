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
import math
import os
from dataclasses import dataclass
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
#: and the new table is what keeps that fixture honest across the rebuild. The
#: dimension columns are nullable because a legacy aggregate row (the golden's)
#: carries no cell; the gate always emits a full cell, so its own rows never
#: rely on the NULL. The declared primary key is what makes a re-emitted rate
#: REPLACE the cell's earlier value instead of stacking a second row.
#:
#: Known limitation, disclosed: the copy carries a legacy row's NULL dimensions
#: forward verbatim, and SQLite treats NULLs as distinct in a non-INTEGER
#: primary key — so two legacy aggregate rows for the same `(run_id, metric)`
#: both survive. No shipped ledger carries such a pair (the table had a
#: two-column key and one writer); if one ever does, the remediation is a
#: documented pre-dedup step in the same change, not a quiet drop.
_INTEG_DURABLE_005: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE run_metrics_dimensioned (
            run_id        TEXT NOT NULL,
            metric        TEXT NOT NULL,
            value         REAL NOT NULL,
            submission_id TEXT,
            criterion_id  TEXT,
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

INTEG_STATEMENTS: dict[str, Statement] = {
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
    """Whether the span-verification switch is set to anything but an explicit
    off value — the differential-timing seam the plan's own oracle names."""
    raw = os.environ.get(_DISABLED_ENV)
    return raw is not None and raw not in ("", "0")


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

    # -- reads ---------------------------------------------------------------------------------------

    def _document_bytes(self, submission_id: str) -> "bytes | None":
        """The submission's canonical document bytes, or None on any fault.

        The row's Markdown column is the canonical text when it carries one;
        otherwise the content-addressed blob named by `content_hash` is. The
        hash is re-verified against the bytes actually read either way — a
        superseded document is a read fault, never a stale acceptance
        (CT-INGEST-02's immutability, from the consumer's side)."""
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
        return raw

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

        Until the cell carries work units AND verdict rows, a panel read
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
        if units > 0 and verdicts == 0:
            return True
        return any(not flag for flag in panel_flags)

    # -- the durable metrics surface (opened lazily, cached per gate) --------------------------------

    def _metrics_target(self) -> Any:
        """The durable handle the per-cell rates are written through.

        The cohort file lives under the store's `cohorts/` directory, so the
        file this handle's own connection has open names the data directory two
        parents up — the same directory `open_store` was given. Opened on the
        first emission and cached: the metrics path must not cost the timed
        verifier a store open per call (the differential's shared base)."""
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

    def verify(self, run_id: str, submission_id: str, criterion_id: str) -> IntegritySignals:
        """Re-derive the six signals for one cell, route on them, emit the rates.

        Every read is fault-injected (a raising view method, a malformed
        payload, a missing document) and every fault lands on the adverse
        value; routing is exactly one route per call; the metrics surface
        always emits. Returns the six fields and nothing else."""
        raw = self._document_bytes(submission_id)
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

        # -- routing: exactly one route per call, in the declared order ------------------------------
        if verified is False:
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
            review_id = f"integ-review-{submission_id}-{criterion_id}"
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
        return IntegritySignals(
            spans_verified=verified,
            evidence_present=present,
            sufficiency_flag=sufficiency,
            ocr_overlap_risk=ocr_risk,
            described_evidence=described,
            extractor_disagreement=disagreement,
        )


__all__ = [
    "ALERT_SPAN_VERIFICATION_FAILURES",
    "INTEG_RATE_METRICS",
    "INTEG_STATEMENTS",
    "IntegrityGate",
    "IntegritySignals",
    "verify_span",
]
