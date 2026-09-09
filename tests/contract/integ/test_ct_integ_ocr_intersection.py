"""`CT-INTEG-09` — `ocr_overlap_risk` is the **intersection** of low
per-region confidence with the spans a criterion **actually cites** — not a
document-level confidence figure — and a flagged criterion is **not
auto-accepted regardless of panel agreement** (`TC-INTEG-C09`).

Case of test plan §6.11.9; TS-66 (issue #77). Written ahead of `#74` (the
signal half) and `#92` (the `M-AGG` cap half).

The clause's force is in its two discriminating fixtures, and the case leads
with them: a document with LOW confidence in a region **no cited span
touches** must not flag, and a HIGH-confidence document with one
low-confidence **cited** region must flag. A document-level implementation —
the exact bug R24 names — passes the naive test (a low-confidence document
flags, a clean one doesn't) and fails both of these, which is why the pair is
asserted together through one checker with executable teeth. The intersection
is geometric: byte intervals, since regions and spans share the byte-offset
coordinate system (CT-INGEST-03), so the precision cells pin adjacency (empty
intersection, no flag), a one-byte overlap (flag), and a criterion that cites
nothing (nothing to intersect, no flag).

The cap half is rung 3: `aggregate` over a flagged outcome with a fully
sufficient, unanimous panel never routes `auto` — the clause's "regardless of
panel agreement".

**Disclosures register** (nothing new is minted beyond the #75 table):

| Name | Status |
|---|---|
| low confidence | `ocr_conf < ocr_conf_floor`, the gate's configured threshold (FR-INTEG-04's knob, `#75`'s `FLOOR` = 0.70 as the injected literal) — the floor VALUE is not the clause's subject, and a differently configured gate shifts which fixture regions are "low" |
| `ocr_conf=None` regions | deliberately unpinned: a region without a confidence figure (e.g. `described_graphic`, whose routing is CT-INTEG-10's subject) intersecting a cited span is a semantic cell the clause does not settle; #74's landing reconciles |
| adjacency | `[a, b)` and `[b, c)` do not intersect — the pinned False is the clause's own "intersection" read literally, disclosed in case #74's landing disputes half-open geometry |
| empty citation | a criterion citing no spans has an empty intersection, so the signal is False — absence is `evidence_present`'s job (CT-INTEG-07 routes it), not the risk signal's; disclosed as this case's reading |
| cap direction | asserted as `routing != "auto"` on `aggregate`'s reconciled outcome surface (the `#76` precedent); the confidence floor's exact value is M-AGG's |
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.contract.integ._doubles import (
    Criterion,
    OCR_FLOOR,
    byte_span,
    unanimous_panel,
)
from tests.support.impl import AGG_MODULE, INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    CitedRegion,
    ExtractionView,
    PanelFlags,
    document_id_for,
    seed_document,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.contract

_MARKDOWN = "The student argues the thesis directly, then supports it with evidence.\n"
_SUBMISSION = "SUB-C09"
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},)


def _region(needle: str, ocr_conf: float, occurrence: int = 0) -> CitedRegion:
    """A `transcribed_text` region over `needle`, at byte offsets."""
    span = byte_span(_MARKDOWN, needle, occurrence=occurrence)
    return CitedRegion(region_id=f"r-{needle}-{occurrence}",
                       region_kind="transcribed_text",
                       start=span.start, end=span.end, ocr_conf=ocr_conf,
                       crop_ref=None, content_state="present")


#: Two regions, one confidence each — the discriminating pair's geometry.
_LOW_UNCITED = ("supports", 0.40)   # low confidence, never cited below
_LOW_CITED = ("thesis", 0.40)       # low confidence, cited below
_HIGH = ("evidence", 0.95)


# --- the checker and its teeth --------------------------------------------------------------


def _assert_intersection_semantics(risk_when_uncited, risk_when_cited) -> None:
    """The discriminating pair, asserted as a pair: a low-confidence region no
    cited span touches does not flag, and a low-confidence CITED region does.
    A document-level figure cannot pass both — it flags by document state, not
    by intersection."""
    assert risk_when_uncited is False, (
        f"the uncited low-confidence region flagged (risk={risk_when_uncited!r}) — the "
        "signal is the INTERSECTION of low per-region confidence with the spans the "
        "criterion cites, not a document-level confidence figure (R24)"
    )
    assert risk_when_cited is True, (
        f"the cited low-confidence region did not flag (risk={risk_when_cited!r}) — a "
        "document-level implementation passes the clean-document case and silently "
        "certifies evidence read from a low-confidence region"
    )


def test_tc_integ_c09_the_intersection_oracle_has_teeth():
    """`TC-INTEG-C09`'s executable construction — the document-level mutant
    (flags by document state) and the naive mutant (never flags) both go red on
    the pair; only the intersection semantics pass. Runs green now: it asserts
    the oracle's teeth, not the implementation."""
    _assert_intersection_semantics(False, True)          # the faithful pair
    with pytest.raises(AssertionError, match="document-level"):
        _assert_intersection_semantics(True, True)       # flags by document state
    with pytest.raises(AssertionError, match="did not flag"):
        _assert_intersection_semantics(False, False)     # never flags


# --- the discriminating fixtures, through the real gate --------------------------------------


def _risk_for(tmp_data_dir, spans, regions) -> bool:
    """One gate over a seeded run (the sibling convention: the gate reads real
    ledger state, not an empty store), returning the `ocr_overlap_risk` the
    cited spans produce against `regions`. `spans` carries `Span`s, `regions`
    carries `CitedRegion`s — the gate's two declared inputs."""
    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(store, submissions=(_SUBMISSION,),
                                      criteria=_CRITERIA)
    handle = store.cohort(ORCH_COHORT_ID)
    seed_document(handle, document_id_for(_SUBMISSION), _SUBMISSION, _MARKDOWN,
                  ORCH_COHORT_ID)
    orch.enumerate_units(run_id)
    view = ExtractionView(spans=spans, regions=regions,
                          panel=PanelFlags((True, True, True)))
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    gate = IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=OCR_FLOOR)
    try:
        return gate.verify(run_id, _SUBMISSION, _CRITERIA[0]["criterion_id"]).ocr_overlap_risk
    finally:
        store.close()


@pytest.mark.writtenahead
def test_tc_integ_c09_low_confidence_uncited_does_not_flag_and_cited_does(
        tmp_data_dir):
    """`TC-INTEG-C09` — the clause's two discriminating fixtures, through the
    real gate. Fixture A: a low-confidence region no cited span touches — the
    signal stays False. Fixture B: a high-confidence document whose one
    low-confidence region IS cited — the signal is True. The pair together is
    what a document-level implementation cannot pass."""
    cited = byte_span(_MARKDOWN, "thesis")
    uncited_low = _region(*_LOW_UNCITED)
    cited_low = _region(*_LOW_CITED)
    high = _region(*_HIGH)

    # Fixture A: the document carries real low confidence — just not under the span.
    _assert_intersection_semantics(
        _risk_for(tmp_data_dir / "uncited", (cited,), (uncited_low, high)),
        # Fixture B: the same document, but the low-confidence region is the cited one.
        _risk_for(tmp_data_dir / "cited", (cited,), (cited_low, high)),
    )


@pytest.mark.writtenahead
@pytest.mark.parametrize("name, region_start, expect_flag", [
    # cited "thesis" is [23, 29); a region beginning exactly at 29 is ADJACENT —
    # [a,b) and [b,c) do not intersect — so the signal stays False.
    ("adjacent: the span ends where the low region begins", 29, False),
    # the same region slid one byte left overlaps [28, 29) — a one-byte
    # intersection flags.
    ("one byte inside the low region", 28, True),
], ids=["adjacent", "one-byte-overlap"])
def test_tc_integ_c09_the_intersection_is_geometric_in_bytes(
        tmp_data_dir, name, region_start, expect_flag):
    """`TC-INTEG-C09`'s precision cells — the intersection is the byte
    intervals': adjacency ([a,b) vs [b,c)) is an empty intersection and does
    not flag; a one-byte overlap does. A fuzzy or codepoint-based overlap
    breaks at least one cell."""
    cited = byte_span(_MARKDOWN, "thesis")
    assert (cited.start, cited.end) == (23, 29), (
        "the precision cells are written against the fixture's byte anatomy; the "
        "fixture changed and the region offsets below must be re-derived"
    )
    low = CitedRegion(region_id="r-adjacent", region_kind="transcribed_text",
                      start=region_start, end=region_start + 16, ocr_conf=0.40,
                      crop_ref=None, content_state="present")
    assert _risk_for(tmp_data_dir / name.split(":")[0].replace(" ", "-"),
                     (cited,), (low,)) is expect_flag


@pytest.mark.writtenahead
def test_tc_integ_c09_a_criterion_that_cites_nothing_has_no_intersection(
        tmp_data_dir):
    """`TC-INTEG-C09` — the empty-citation cell, disclosed: low-confidence
    regions exist, the criterion cites no spans, the intersection is empty and
    the signal is False. Absence is `evidence_present`'s job (CT-INTEG-07
    routes it) — the risk signal is about overlap with what was actually
    cited."""
    low = _region(*_LOW_CITED)
    high = _region(*_HIGH)
    assert _risk_for(tmp_data_dir / "empty-citation", (), (low, high)) is False


# --- the cap, at rung 3 ---------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_integ_c09_a_flagged_criterion_is_not_auto_accepted_against_unanimity():
    """`TC-INTEG-C09`'s cap half — `aggregate` over a flagged outcome and a
    fully sufficient, unanimous panel: the routing is never `auto`. The clause
    says the flagged criterion is not auto-accepted REGARDLESS of panel
    agreement, and unanimity is the strongest agreement there is."""
    IntegritySignals = require(INTEG_MODULE, "IntegritySignals", issue="#74")
    aggregate = require(AGG_MODULE, "aggregate", issue="#92")
    flagged = IntegritySignals(
        spans_verified=True, evidence_present=True, sufficiency_flag=False,
        ocr_overlap_risk=True, described_evidence=False,
        extractor_disagreement=None,
    )
    outcome = aggregate(unanimous_panel("B2"), Criterion("C1"), flagged)
    routing = getattr(outcome, "routing", None)
    assert routing != "auto", (
        f"M-AGG auto-accepted a flagged criterion against a unanimous panel "
        f"(routing={routing!r}) — the cap CT-INTEG-09 names is not enforced by the "
        "consumer (R24)"
    )
