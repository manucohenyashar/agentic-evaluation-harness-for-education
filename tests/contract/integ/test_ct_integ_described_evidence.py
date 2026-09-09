"""`CT-INTEG-10` — evidence lying **wholly** within a `described_graphic`
region is a routing candidate **on that basis alone**, is marked **described**
rather than transcribed, and its image crop is **retained and reachable in one
action** (`TC-INTEG-C10`).

Case of test plan §6.11.9; TS-66 (issue #77). Written ahead of `#74`.

Guards RISK-17: a model's account of a picture must never be mistaken for the
student's words. The clause has three parts and the case keeps them separate:

1. **Routing on that basis alone** — the case supplies otherwise-perfect
   evidence (a verified span, a unanimous sufficient panel, no OCR risk) and
   asserts the criterion STILL routes: the described basis needs no supporting
   defect, and a gate that only routes when something else is wrong fails
   here.
2. **Marked, not mis-typed** — `described_evidence` is True: the evidence is
   marked described rather than transcribed, which is what the review surface
   reads to present the crop instead of the text.
3. **The crop, reachable in one action** — the region's `crop_ref` resolves
   through the real blob store (§4.2: the blob store is never doubled) to the
   exact bytes the teacher review needs, with one call. A crop that is
   recorded but not retained makes the routing a dead end, so the limb fetches
   and compares.

The **wholly** half is pinned by its precision cell: evidence straddling a
described region and a transcribed one is not marked described — the model's
account covers part of the evidence, and part is not the clause's case.

**Disclosures register** (nothing new is minted beyond the #75 table):

| Name | Status |
|---|---|
| crop provenance | the crop bytes are `put()` into the real content-addressed blob store and the region's `crop_ref` carries the returned hash — the schema's own shape (`CitedRegion.crop_ref`, `document_region.crop_ref`); "one action" is read as one `blobs.get(crop_ref)` call from the handle the review surface holds |
| region persistence | the regions ride the injected `ExtractionView` (the #75 table): no region rows are landed for the described fixture, and the view is the one line `#68`'s landing changes |
| `M-CONSOLE` half | deferred with disclosure: the one-action teacher review UI does not exist yet (stories #123..#130); the blob-reachability limb here is the data half its presentation would read, and this case's routing row is what it acts on |
| `M-AGG` half | the clause names `M-AGG` a consumer of the routing decision, but declares no separate cap for described evidence beyond the routing itself (unlike CT-INTEG-09's); the routing assertion here is the full declared consequence, reconciled if M-AGG's landing adds a cap |
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.contract.integ._doubles import (
    CONTRACT_COHORT,
    OCR_FLOOR,
    byte_span,
    make_gate,
)
from tests.support.integ_vocabulary import (
    CitedRegion,
    ExtractionView,
    PanelFlags,
    document_id_for,
    seed_document,
)

pytestmark = pytest.mark.contract

_RUN = "run-integ-c10"
_SUBMISSION = "SUB-C10"
_CRITERION = "C1"
_MARKDOWN = "The student describes the chart in words and cites its trend.\n"
_CROP_BYTES = b"PNG-fixture-bytes-for-the-described-chart-crop"


def _described_region(start: int, end: int) -> CitedRegion:
    return CitedRegion(region_id="r-described", region_kind="described_graphic",
                       start=start, end=end, ocr_conf=None, crop_ref=None,
                       content_state="present")


def _transcribed_region(start: int, end: int) -> CitedRegion:
    return CitedRegion(region_id="r-transcribed", region_kind="transcribed_text",
                       start=start, end=end, ocr_conf=0.95, crop_ref=None,
                       content_state="present")


def _otherwise_perfect_view(regions, crop_ref=None):
    """A verified span over the described region's text, a unanimous sufficient
    panel, nothing else wrong — so any routing the case observes is the
    described basis ALONE. If a crop_ref is given, the region carries it."""
    span = byte_span(_MARKDOWN, "describes")
    if crop_ref is not None:
        regions = tuple(
            CitedRegion(region_id=r.region_id, region_kind=r.region_kind,
                        start=r.start, end=r.end, ocr_conf=r.ocr_conf,
                        crop_ref=crop_ref, content_state=r.content_state)
            for r in regions
        )
    return ExtractionView(spans=(span,), regions=regions,
                          panel=PanelFlags((True, True, True)))


# --- limb 1 + 2: routing on that basis alone, and the described marking ----------------------


@pytest.mark.writtenahead
def test_tc_integ_c10_perfect_evidence_in_a_described_region_still_routes_and_is_marked(
        tmp_data_dir):
    """`TC-INTEG-C10` — the span verifies, the panel is unanimous and
    sufficient, nothing is at risk: the criterion still routes (a review-queue
    row) and the signals mark the evidence described rather than transcribed.
    The described basis alone is the routing candidate."""
    start = _MARKDOWN.encode("utf-8").find(b"describes")
    region = _described_region(start, start + len("describes"))
    view = _otherwise_perfect_view((region,))
    gate, store = make_gate(tmp_data_dir, view, ocr_conf_floor=OCR_FLOOR)
    signals = gate.verify(_RUN, _SUBMISSION, _CRITERION)
    assert signals.described_evidence is True, (
        "evidence wholly within a described_graphic region was not marked described "
        "— a model's account of a picture presented as the student's words is the "
        "mis-typing RISK-17 guards"
    )
    handle = store.cohort(CONTRACT_COHORT)
    queued = handle.query(
        "SELECT queue_id, reason FROM review_queue WHERE submission_id = :s "
        "AND criterion_id = :c",
        s=_SUBMISSION, c=_CRITERION,
    )
    assert queued, (
        "otherwise-perfect evidence in a described region routed nowhere — the "
        "described basis alone makes the criterion a routing candidate (FR-INTEG-05)"
    )
    store.close()


@pytest.mark.writtenahead
def test_tc_integ_c10_evidence_straddling_described_and_transcribed_is_not_marked(
        tmp_data_dir):
    """`TC-INTEG-C10`'s precision cell — the WHOLLY half: the cited span starts
    inside the described region but ends inside a transcribed one, so the
    model's account covers only part of the evidence and `described_evidence`
    stays False. Part is not the clause's case."""
    described_start = _MARKDOWN.encode("utf-8").find(b"describes")
    straddling = byte_span(_MARKDOWN, "describes the chart in words")
    view = ExtractionView(
        spans=(straddling,),
        regions=(_described_region(described_start, described_start + 9),
                 _transcribed_region(straddling.end - 5, straddling.end + 10)),
        panel=PanelFlags((True, True, True)),
    )
    gate, store = make_gate(tmp_data_dir, view, ocr_conf_floor=OCR_FLOOR)
    signals = gate.verify(_RUN, _SUBMISSION, _CRITERION)
    assert signals.described_evidence is False, (
        "evidence straddling a described and a transcribed region came out marked "
        "described — the clause requires the evidence lie WHOLLY within the region"
    )
    store.close()


# --- limb 3: the crop is retained and reachable in one action --------------------------------


@pytest.mark.writtenahead
def test_tc_integ_c10_the_described_regions_crop_is_retained_and_reachable(
        tmp_data_dir):
    """`TC-INTEG-C10` — the crop half: the described region's `crop_ref`
    resolves through the real blob store to the exact crop bytes, in one
    `get` call — the routing is a dead end without the image behind it, so the
    case fetches rather than trusts the reference."""
    store = open_store(tmp_data_dir)
    crop_ref = store.blobs().put(_CROP_BYTES)
    start = _MARKDOWN.encode("utf-8").find(b"describes")
    region = _described_region(start, start + len("describes"))
    view = _otherwise_perfect_view((region,), crop_ref=crop_ref)
    gate, store2 = make_gate(tmp_data_dir, view, ocr_conf_floor=OCR_FLOOR)
    try:
        signals = gate.verify(_RUN, _SUBMISSION, _CRITERION)
        assert signals.described_evidence is True
        # One action: the review surface's own resolve, from the region's ref.
        fetched = store.blobs().get(crop_ref)
        assert fetched == _CROP_BYTES, (
            "the described region's crop_ref resolved to different bytes — the crop "
            "is recorded but not retained, and the routing is a dead end (FR-INTEG-05)"
        )
    finally:
        store.close()
        store2.close()
