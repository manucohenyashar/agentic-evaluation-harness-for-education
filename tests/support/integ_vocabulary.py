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
| `aeh.integ.IntegrityGate(handle, blobs, extraction_view, ocr_conf_floor=...)` | **constructor invented** — the Protocol declares no construction. The arguments are the design's own dependency set: M-STORE (the cohort handle documents, regions and work units are read through), the blob store (CT-INTEG-10's crop reachability), and the extraction side below; the floor is FR-INTEG-04's configured threshold. The signature reconciles at `#74`'s landing |
| `aeh.integ.IntegritySignals` | design-declared dataclass (§3.9): exactly six fields, `extractor_disagreement` tri-state |
| `IntegrityGate.verify(run_id, submission_id, criterion_id)` | design-declared (§3.9 Protocol), returns `IntegritySignals` |
| `aeh.integ.ALERT_SPAN_VERIFICATION_FAILURES` | **invented name**: CT-INTEG-14 declares the *alert* ("a span verification failure rate above a low threshold means the extractor is hallucinating spans") but not its spelling; the store's precedent (`ALERT_FREE_DISK`, `DECLARED_ALERTS`) makes the name part of the interface, so the case requires the constant and reconciles the string at `#74`'s landing |
| `aeh.integ.INTEG_RATE_METRICS` | **invented spelling** of CT-INTEG-14's six per-criterion rates — the design names the rates but not their metric strings; the tuple is required by name so the case fails loudly if the names move |
| `run_metrics` carries per-criterion rows | **assumed `#74` migration**: the landed durable table is `(run_id, metric, value)` with PK `(run_id, metric)`, which structurally cannot hold a per-criterion rate; CT-INTEG-14's "emitted per criterion" requires the dimension. TC-INTEG-14 reads `submission_id`, `criterion_id`, `value` for a `(run_id, metric)` through the **durable** handle and asserts the dimension set — a `#74` that emits elsewhere (or keeps the aggregate PK) fails the case rather than the reader |
| `INTEG_SPAN_VERIFICATION_DISABLED` (env) | **invented knob** for TC-INTEG-11's differential (the plan's own oracle measures "against a run with verification disabled", which requires a disable switch; seam rule 3 makes it env-gated). PERF-06 (TS-53) needs the same switch |
| spans' persistence | none of the landed modules store spans (grep: no `span` table or column anywhere in `src/aeh`). `ExtractionView` injects them as data at the one place design §3.9's *Requires* row says M-EXTRACT is read; `#68`'s landing replaces the injected payload with the real surface and the view is the single line that changes |

**Coordinate system**: spans and region extents are **byte offsets** into
`document.markdown` (CT-INGEST-03: "the coordinate system every later stage uses";
NFR-INTEG-02: "a pure function of (document bytes, span)") — the property strategies
and the boundary table both draw and assert in bytes.

Seeding helpers write **real rows through a real cohort handle** (§4.2: SQLite and the
blob store are never doubled), into the schema the landed migrations carry. Importing
this module imports `aeh.ingest`, which is what registers the `markdown` /
`transcriber_ref` columns into the cohort-tier migration set (review finding: without
that import the migration is never registered and `document.markdown` does not exist).
`seed_document` also ensures the `cohort` and `submission` rows the document's foreign
keys reference exist — idempotently, so a file that seeds documents without a full
`seed_run` still satisfies the enforced FK. Verdict rows are seeded directly with a
`sufficiency` flag carried by `ExtractionView` instead, because the `verdict` table has
no `evidence_sufficient` column until M-JUDGE lands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import aeh.ingest  # noqa: F401  # registers the document-markdown cohort migrations

#: The created-at stamp the seed helpers write, matching `tests.support.orch_run`'s
#: package stamp convention so the two seeders produce interchangeable rows.
_SEED_STAMP = "2026-01-01T00:00:00+00:00"


@dataclass(frozen=True)
class Span:
    """The span shape CT-EXTRACT-01 declares: BYTE offsets into `document.markdown`.

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
    geometric and needs both halves. Extents are byte offsets, like spans: the
    intersection only means anything if both sides share the coordinate system.
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


def seed_document(
    handle: Any, document_id: str, submission_id: str, markdown: str, cohort_id: str
) -> str:
    """Insert one canonical document, ensuring its foreign keys' parents exist.

    The `cohort` and `submission` rows are inserted idempotently (`INSERT OR IGNORE`)
    so a file that seeds documents without a full `seed_run` satisfies the enforced FK,
    and a file that runs after `seed_run` does not collide with its rows. The content
    hash covers the Markdown bytes.
    """
    import hashlib

    with handle.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES (:c, 'synthetic', :ts)",
            c=cohort_id,
            ts=_SEED_STAMP,
        )
        tx.execute(
            "INSERT OR IGNORE INTO submission (submission_id, cohort_id, student_ref) "
            "VALUES (:s, :c, :r)",
            s=submission_id,
            c=cohort_id,
            r=f"ref-{submission_id}",
        )
        tx.execute(
            "INSERT INTO document (document_id, submission_id, content_hash, markdown, "
            "transcriber_ref) VALUES (:d, :s, :h, :m, 'vlm@sha256:test')",
            d=document_id,
            s=submission_id,
            h=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            m=markdown,
        )
    return document_id


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


def document_id_for(submission_id: str) -> str:
    """The deterministic document id the seeding convention uses for a submission."""
    return f"doc-{submission_id}"
