"""The fixture vocabulary TS-28's M-INTEG cases share (issue #75).

Everything here is **test-side data or a declared seam**, not a double of M-INTEG itself:
§4.2 permits doubles only at the model boundary, and the two boundaries M-INTEG sits on —
the extractor's span payload and the panel's sufficiency flags — are exactly the surfaces
`#68` (M-EXTRACT) and `#78`/#79 (M-JUDGE) have not landed yet. `ExtractionView` is the
single place that reconciliation happens.

**The interface the TS-28 files assume of `#73`/`#74`**, listed so it is reconciled
deliberately rather than discovered (the TS-24 precedent):

| Name | Status |
|---|---|
| `aeh.integ.verify_span(doc, span) -> bool` | **invented as a module-level function**: design §3.9 declares it as an `IntegrityGate` *method*, but TC-INTEG-01/09 and FUZZ-03 are rung 0 — a pure function over (document bytes, span), no store, no construction. The `#65` `aeh.synth:synthesize` precedent: the minimal entry point the pure cases can call; the method and the function reconcile at `#73`'s landing |
| `aeh.integ.IntegrityGate(store, blobs, extraction_view)` | **constructor invented** — the Protocol declares no construction. The three arguments are the design's own dependency set: M-STORE (the cohort handle documents, regions and work units are read through), the blob store (CT-INTEG-10's crop reachability), and the extraction side below. The signature reconciles at `#74`'s landing |
| `aeh.integ.IntegritySignals` | design-declared dataclass (§3.9): exactly six fields, `extractor_disagreement` tri-state |
| `IntegrityGate.verify(run_id, submission_id, criterion_id)` | design-declared (§3.9 Protocol), returns `IntegritySignals` |
| `aeh.integ.ALERT_SPAN_VERIFICATION_FAILURES` | **invented name**: CT-INTEG-14 declares the *alert* ("a span verification failure rate above a low threshold means the extractor is hallucinating spans") but not its spelling; the store's precedent (`ALERT_FREE_DISK`, `DECLARED_ALERTS`) makes the name part of the interface, so the case requires the constant and reconciles the string at `#74`'s landing |
| `INTEG_SPAN_VERIFICATION_DISABLED` (env) | **invented knob** for TC-INTEG-11's differential (the plan's own oracle measures "against a run with verification disabled", which requires a disable switch; seam rule 3 makes it env-gated). PERF-06 (TS-53) needs the same switch |
| spans' persistence | none of the landed modules store spans (grep: no `span` table or column anywhere in `src/aeh`). `ExtractionView` injects them as data at the one place design §3.9's *Requires* row says M-EXTRACT is read; `#68`'s landing replaces the injected payload with the real surface and the helper below is the single line that changes |

Seeding helpers write **real rows through a real cohort handle** (§4.2: SQLite and the blob
store are never doubled), into the schema the landed migrations carry: `document` with
`markdown` (`M-INGEST`'s ALTERs), `document_region` with `region_kind`/`ocr_conf`/
`content_state`/`crop_ref`, `work_unit` with `run_id`/`criterion_id`/`attempts`/`origin`
(M-ORCH's ALTERs). Verdict rows are seeded directly with a `sufficiency` flag carried by
`ExtractionView` instead, because the `verdict` table has no `evidence_sufficient` column
until M-JUDGE lands.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class Span:
    """The span shape CT-EXTRACT-01 declares: byte offsets into `document.markdown`.

    A test-side record until `#68` lands the extractor's payload; `verify_span` is
    duck-typed over `.start` / `.end` / `.text`, which is the whole declared surface.
    """

    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Doc:
    """The document half of `verify_span(doc, span)`: immutable canonical Markdown.

    CT-INGEST-02/03: the artifact is immutable and spans address `document.markdown`
    byte offsets forever; a rung-0 case hands the function the bytes and nothing else.
    """

    markdown: str


@dataclass(frozen=True)
class CitedRegion:
    """A region a span may overlap, with the fields CT-INGEST-04 declares.

    Mirrors the `document_region` row the M-INGEST migrations carry (`region_kind`,
    `ocr_conf`, `crop_ref`, `content_state`) plus the region's extent in the canonical
    Markdown — the token-cluster positions `#39` landed — because FR-INTEG-04's
    intersection ("low confidence with the spans a criterion actually cites") is
    geometric and needs both halves.
    """

    region_id: str
    region_kind: str  # transcribed_text | described_graphic | selection_mark
    start: int
    end: int
    ocr_conf: float | None = None
    crop_ref: str | None = None
    content_state: str = "present"


@dataclass(frozen=True)
class PanelFlags:
    """The panel half of FR-INTEG-07: one flag per judge verdict (CT-JUDGE-06)."""

    evidence_sufficient: tuple[bool, ...] = (True, True, True)


class ExtractionView:
    """The read model standing in for M-EXTRACT and M-JUDGE (see module docstring).

    Four methods, one per read the six signal computations consume, so TC-INTEG-08 can
    inject an exception into each computation *separately* — the fail-closed oracle
    needs the fault points, and a monolithic double would fuse two signals into one
    fault. Subclass (or pass lambdas) to make one read raise while the rest succeed.
    """

    def __init__(
        self,
        spans: Sequence[Span] = (),
        second_family_spans: Sequence[Span] | None = None,
        regions: Sequence[CitedRegion] = (),
        panel: PanelFlags = PanelFlags(),
        evidence_type_requires_citation: bool = True,
    ) -> None:
        self._spans = tuple(spans)
        self._second_family = (
            None if second_family_spans is None else tuple(second_family_spans)
        )
        self._regions = tuple(regions)
        self._panel = panel
        self._requires_citation = evidence_type_requires_citation

    # -- the four fault-injectable reads ------------------------------------------------
    def spans(self, submission_id: str, criterion_id: str) -> tuple[Span, ...]:
        """The extraction unit's spans for this criterion (no judge dimension, CT-EXTRACT-03)."""
        return self._spans

    def second_family_spans(
        self, submission_id: str, criterion_id: str
    ) -> tuple[Span, ...] | None:
        """The second-family span set, or `None` when no second extraction ran (FR-INTEG-06)."""
        return self._second_family

    def regions(self, document_id: str) -> tuple[CitedRegion, ...]:
        """The document's regions with per-region `ocr_conf` (FR-INGEST-15)."""
        return self._regions

    def panel_sufficiency(self, submission_id: str, criterion_id: str) -> PanelFlags:
        """Per-judge `evidence_sufficient` (CT-JUDGE-06; FR-INTEG-07's input)."""
        return self._panel

    def criterion_requires_citation(self, criterion_id: str) -> bool:
        """Whether the criterion's `evidence_type` requires a citation (FR-INTEG-03's input)."""
        return self._requires_citation


# --- seeding: real rows through a real cohort handle -------------------------------------


def seed_document(handle: Any, document_id: str, submission_id: str, markdown: str) -> str:
    """Insert one canonical document with its content hash over the Markdown."""
    import hashlib

    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO document (document_id, submission_id, content_hash, markdown, "
            "transcriber_ref) VALUES (:d, :s, :h, :m, 'vlm@sha256:test')",
            d=document_id,
            s=submission_id,
            h=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            m=markdown,
        )
    return document_id


def seed_region(handle: Any, document_id: str, region: CitedRegion) -> None:
    """Insert one `document_region` row with the fields CT-INGEST-04 declares."""
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO document_region (region_id, document_id, page_no, element_kind, "
            "region_kind, ocr_conf, content_state, crop_ref) "
            "VALUES (:r, :d, 1, :k, :k, :c, :st, :crop)",
            r=region.region_id,
            d=document_id,
            k=region.region_kind,
            c=region.ocr_conf,
            st=region.content_state,
            crop=region.crop_ref,
        )


def seed_work_unit(
    handle: Any,
    work_id: str,
    run_id: str,
    submission_id: str,
    criterion_id: str,
    stage: str,
    status: str = "done",
    attempts: int = 0,
) -> None:
    """Insert one ledger unit with the columns M-ORCH's migrations add."""
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO work_unit (work_id, submission_id, stage, status, run_id, "
            "criterion_id, attempts) VALUES (:w, :s, :st, :su, :r, :c, :a)",
            w=work_id,
            s=submission_id,
            st=stage,
            su=status,
            r=run_id,
            c=criterion_id,
            a=attempts,
        )


def seed_verdict(
    handle: Any,
    verdict_id: str,
    work_id: str,
    judge_id: str,
    band: str,
) -> None:
    """Insert one verdict row (the `verdict` table has band but no sufficiency column
    until M-JUDGE lands; the panel flag rides `ExtractionView.panel_sufficiency`)."""
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO verdict (verdict_id, work_id, judge_id, band) "
            "VALUES (:v, :w, :j, :b)",
            v=verdict_id,
            w=work_id,
            j=judge_id,
            b=band,
        )


def spans_payload(spans: Sequence[Span]) -> str:
    """The JSON payload the extractor's span set rides until `#68` lands its surface.

    One serialization, spelled once, so a test asserting on stored bytes and a test
    asserting on `ExtractionView` data cannot drift apart.
    """
    return json.dumps(
        [{"start": s.start, "end": s.end, "text": s.text} for s in spans]
    )


def metric_rows(handle: Any, run_id: str, name: str) -> list[dict]:
    """Read one metric's rows from `run_metrics` for a run, per criterion.

    CT-INTEG-14's rates are emitted **per criterion**; the dimension the rows carry is
    part of what the case asserts, so the reader returns whole rows rather than values.
    """
    return handle.query(
        "SELECT * FROM run_metrics WHERE run_id = :r AND name = :n ORDER BY 1",
        r=run_id,
        n=name,
    )


def document_id_for(submission_id: str) -> str:
    """The deterministic document id the seeding convention uses for a submission."""
    return f"doc-{submission_id}"


def cited_regions_for(markdown: str, spans: Sequence[Span], region_id: str,
                      region_kind: str = "transcribed_text",
                      ocr_conf: float | None = None,
                      crop_ref: str | None = None) -> tuple[CitedRegion, ...]:
    """Regions covering exactly the cited spans' extents in the Markdown.

    The common fixture: a region per span, so "the region overlaps the cited span"
    holds by construction and a case varies only the confidence or the kind.
    """
    return tuple(
        CitedRegion(
            region_id=f"{region_id}-{i}",
            region_kind=region_kind,
            start=s.start,
            end=s.end,
            ocr_conf=ocr_conf,
            crop_ref=crop_ref,
        )
        for i, s in enumerate(spans)
    )
