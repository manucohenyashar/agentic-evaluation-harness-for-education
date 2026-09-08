"""TS-28's rung-0 signal cases — `TC-INTEG-04` (OCR boundary), `TC-INTEG-05`
(described evidence), `TC-INTEG-06` (extractor disagreement), `TC-INTEG-08`
(fail-closed fault injection).

Written ahead of `#74` (test plan §8.2): every case fails only through
`NotImplementedYet` naming `#74` and turns green when `aeh.integ` lands the gate.

**Interface assumed of `#74`, reconciled at landing** (the full table lives in
`tests/support/integ_vocabulary.py`):

| Assumption | Reading |
|---|---|
| `IntegrityGate(handle, blobs, view, *, ocr_conf_floor)` | constructor invented — the Protocol declares none. `handle` is the cohort handle (documents, regions and the work ledger are real store rows, §4.2: never doubled); `blobs` the store's blob half for CT-INTEG-10's crop reachability; `view` the `ExtractionView` standing in for `#68`/`#78`'s unlanded span and panel surfaces. `ocr_conf_floor` is the `INTEG_OCR_CONF_FLOOR` configuration the design names (§7.4: a value is injected, never a literal in production code — Q-04) |
| `verify(run_id, submission_id, criterion_id) -> IntegritySignals` | design-declared (§3.9) |
| disagreement rule | byte-exact span-set equality — the module's own standard is byte-exactness with no normalization (CT-INTEG-01); overlapping spans that are not byte-identical are not the same evidence, so they disagree. `None` only when no second extraction ran (CT-INTEG-02) |
| described trigger | *wholly within* a `described_graphic` region (CT-INTEG-10's words); the spanning case pins the boundary — partial overlap does not set `described_evidence` |
| fail-closed mapping (CT-INTEG-03's four conservative words, applied to six signals) | span read fails → `spans_verified=False`; no spans read → `evidence_present=False`; regions read fails → `ocr_overlap_risk=True` **and** `described_evidence=True`; panel read fails → `sufficiency_flag=True`; second-family read fails → `extractor_disagreement=True`, **not** `None` — the second extraction *ran*, so `None` ("not measured", CT-INTEG-02) is contractually wrong, and True is the adverse reading |

Each fault case asserts only the signal(s) its injected fault feeds — a failing regions
read says nothing about whether the span read succeeded — and asserts them **exactly**:
the conservative value, never the permissive one (NFR-INTEG-03).
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    CitedRegion,
    Doc,
    ExtractionView,
    PanelFlags,
    Span,
    document_id_for,
    seed_document,
)

pytestmark = pytest.mark.writtenahead

#: TC-INTEG-04's declared boundary value — `INTEG_OCR_CONF_FLOOR` as the case's input
#: names it. Injected per Q-04, never read from production code as a literal.
FLOOR = 0.70

_RUN = "run-integ-2026-7B"
_COHORT = "c-2026-7B-integ"

_MARKDOWN = (
    "The mitochondrion is the powerhouse of the cell.\n"
    "A described figure follows in the source document.\n"
)


def _gate(tmp_data_dir, view, *, ocr_conf_floor: float = FLOOR):
    """A real gate over a real store; the extraction side injected (`#68` unlanded)."""
    IntegrityGate, IntegritySignals = require(
        INTEG_MODULE, "IntegrityGate", "IntegritySignals", issue="#74"
    )
    store = open_store(tmp_data_dir)
    handle = store.cohort(_COHORT)
    return IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=ocr_conf_floor), IntegritySignals


def _seed_document(tmp_data_dir, submission_id: str = "SUB-001") -> Doc:
    doc = Doc(markdown=_MARKDOWN)
    # The document row needs a store to live in; the gate opens its own over the same
    # directory, so seed through a throwaway handle first.
    store = open_store(tmp_data_dir)
    seed_document(store.cohort(_COHORT), document_id_for(submission_id), submission_id, doc.markdown, _COHORT)
    store.close()
    return doc


def _criterion_spans(doc: Doc) -> tuple[Span, ...]:
    start = doc.markdown.index("mitochondrion")
    return (Span(start, start + len("mitochondrion"), "mitochondrion"),)


# --- TC-INTEG-04: the OCR-confidence floor is an intersection, not a figure ----------------

def test_tc_integ_04_ocr_overlap_boundary_at_0_69_0_70_0_71(tmp_data_dir):
    """`TC-INTEG-04` (P0) — regions overlapping a cited span at `ocr_conf` 0.69, 0.70
    and 0.71 against a floor of 0.70: flagged **at and below** the floor, clear above.
    The boundary is the requirement, not a neighbourhood."""
    doc = _seed_document(tmp_data_dir)
    spans = _criterion_spans(doc)
    for conf, expected in ((0.69, True), (0.70, True), (0.71, False)):
        view = ExtractionView(
            spans=spans,
            regions=(CitedRegion("r-low", "transcribed_text", spans[0].start,
                                 spans[0].end, ocr_conf=conf),),
        )
        gate, _ = _gate(tmp_data_dir, view)
        signals = gate.verify(_RUN, "SUB-001", "C1")
        assert signals.ocr_overlap_risk is expected, (
            f"ocr_conf={conf}: expected ocr_overlap_risk={expected} — the floor of "
            f"{FLOOR} flags at and below, clears above (FR-INTEG-04)"
        )


def test_tc_integ_04_low_confidence_not_overlapping_a_cited_span_does_not_flag(tmp_data_dir):
    """`TC-INTEG-04`'s discriminating fixture (CT-INTEG-09) — a low-confidence region
    **no cited span touches** must not flag: the intersection is the requirement, and a
    document-level confidence figure passes a naive test and fails this one."""
    doc = _seed_document(tmp_data_dir)
    spans = _criterion_spans(doc)
    # The cited span's own region is healthy; a distant low-confidence region is not cited.
    cited = CitedRegion("r-cited", "transcribed_text", spans[0].start, spans[0].end,
                        ocr_conf=0.95)
    distant = CitedRegion("r-distant", "transcribed_text", 0, 10, ocr_conf=0.10)
    gate, _ = _gate(tmp_data_dir, ExtractionView(spans=spans, regions=(cited, distant)))
    signals = gate.verify(_RUN, "SUB-001", "C1")
    assert signals.ocr_overlap_risk is False, (
        "a low-confidence region the criterion never cites must not flag — this is the "
        "fixture a document-level implementation fails (CT-INTEG-09)"
    )


def test_tc_integ_04_high_confidence_document_with_low_confidence_cited_region_flags(tmp_data_dir):
    """`TC-INTEG-04`'s second discriminating fixture (CT-INTEG-09) — a healthy document
    with exactly one low-confidence *cited* region must flag."""
    doc = _seed_document(tmp_data_dir)
    spans = _criterion_spans(doc)
    cited_low = CitedRegion("r-cited", "transcribed_text", spans[0].start, spans[0].end,
                            ocr_conf=0.40)
    healthy = CitedRegion("r-healthy", "transcribed_text", 0, spans[0].start, ocr_conf=0.99)
    gate, _ = _gate(tmp_data_dir, ExtractionView(spans=spans, regions=(cited_low, healthy)))
    signals = gate.verify(_RUN, "SUB-001", "C1")
    assert signals.ocr_overlap_risk is True


def test_tc_integ_04_flagged_criterion_cannot_auto_accept_by_construction(tmp_data_dir):
    """`TC-INTEG-04`'s closing clause — *a flagged criterion is not auto-accepted
    regardless of panel agreement* — is M-AGG's cap, but it holds structurally only if
    this module cannot write the value the cap protects: asserted here by the gate
    returning signals and nothing else (the full write-set prohibition is
    `test_integ_write_set.py`'s case, TC-INTEG-10)."""
    doc = _seed_document(tmp_data_dir)
    spans = _criterion_spans(doc)
    flagged = CitedRegion("r-low", "transcribed_text", spans[0].start, spans[0].end,
                          ocr_conf=0.69)
    gate, IntegritySignals = _gate(
        tmp_data_dir, ExtractionView(spans=spans, regions=(flagged,),
                                     panel=PanelFlags((True, True, True)))
    )
    signals = gate.verify(_RUN, "SUB-001", "C1")
    assert isinstance(signals, IntegritySignals)
    assert signals.ocr_overlap_risk is True
    assert signals == IntegritySignals(
        spans_verified=True, evidence_present=True, sufficiency_flag=False,
        ocr_overlap_risk=True, described_evidence=False, extractor_disagreement=None,
    ), "unanimous agreement on a flagged criterion: the signals say what happened and "
    "nothing in them is a verdict — the cap lives downstream, and the module's whole "
    "output here is six fields (CT-INTEG-04)"


# --- TC-INTEG-05: described evidence routes on that basis alone ----------------------------

def test_tc_integ_05_wholly_described_evidence_is_described_and_its_crop_reachable(tmp_data_dir):
    """`TC-INTEG-05` (P0) — evidence lying wholly inside a `described_graphic` region is
    a routing candidate on that basis alone, marked described rather than transcribed,
    and its image crop is retained and reachable in one action (CT-INTEG-10)."""
    doc = _seed_document(tmp_data_dir)
    start = doc.markdown.index("A described figure")
    end = doc.markdown.index("follows") + len("follows")
    spans = (Span(start, end, doc.markdown[start:end]),)
    crop_bytes = b"png-bytes-for-the-described-region"
    gate_holder = {}
    store = open_store(tmp_data_dir)
    handle = store.cohort(_COHORT)
    seed_document(handle, document_id_for("SUB-001"), "SUB-001", doc.markdown, _COHORT)
    crop_ref = store.blobs().put(crop_bytes)
    IntegrityGate, _ = require(INTEG_MODULE, "IntegrityGate", "IntegritySignals", issue="#74")
    view = ExtractionView(
        spans=spans,
        regions=(CitedRegion("r-desc", "described_graphic", start, end,
                             ocr_conf=0.98, crop_ref=crop_ref),),
    )
    gate_holder["gate"] = IntegrityGate(handle, store.blobs(), view, ocr_conf_floor=FLOOR)
    signals = gate_holder["gate"].verify(_RUN, "SUB-001", "C1")
    assert signals.described_evidence is True, (
        "verified, sufficient, unanimous evidence wholly inside a described_graphic "
        "region is a routing candidate on that basis alone (RISK-17: a model's account "
        "of a picture is never the student's words)"
    )
    # The crop: retained and reachable in one action from the signal's region.
    assert store.blobs().get(crop_ref) == crop_bytes, (
        "the described region's crop must resolve to its retained bytes in one action — "
        "the teacher-review path FR-INTEG-05 promises"
    )
    store.close()


def test_tc_integ_05_evidence_spanning_described_and_transcribed_is_not_described(tmp_data_dir):
    """`TC-INTEG-05`'s spanning case — the plan demands the declared behaviour be
    asserted explicitly. The declared trigger is *wholly within* (CT-INTEG-10), so
    evidence straddling a described and a transcribed region is not described evidence:
    the model's account and the student's words are in the same quote, and neither
    label may silently swallow the other. This test pins `False` so the boundary is a
    decision `#74` makes, not an accident."""
    doc = _seed_document(tmp_data_dir)
    described_start = doc.markdown.index("A described figure")
    # One span reaching from the described region back into the transcribed sentence.
    start = doc.markdown.index("mitochondrion")
    spans = (Span(start, described_start + 20, doc.markdown[start:described_start + 20]),)
    view = ExtractionView(
        spans=spans,
        regions=(
            CitedRegion("r-trans", "transcribed_text", start, described_start, ocr_conf=0.99),
            CitedRegion("r-desc", "described_graphic", described_start,
                        len(doc.markdown), ocr_conf=0.98, crop_ref="b-crop"),
        ),
    )
    gate, _ = _gate(tmp_data_dir, view)
    signals = gate.verify(_RUN, "SUB-001", "C1")
    assert signals.described_evidence is False, (
        "evidence spanning both a described and a transcribed region is not wholly "
        "within either — the declared trigger is 'wholly within' (CT-INTEG-10)"
    )


# --- TC-INTEG-06: the three-valued disagreement signal -------------------------------------

def _two_family_gate(tmp_data_dir, spans, second_family):
    doc = _seed_document(tmp_data_dir)
    view = ExtractionView(spans=spans, second_family_spans=second_family,
                          panel=PanelFlags((True, True, True)))
    return _gate(tmp_data_dir, view)


def test_tc_integ_06_identical_second_family_agrees(tmp_data_dir):
    """`TC-INTEG-06` — two span sets from different model families, identical:
    `extractor_disagreement` is `False` — measured, and in agreement."""
    doc = _seed_document(tmp_data_dir)
    spans = _criterion_spans(doc)
    gate, _ = _two_family_gate(tmp_data_dir, spans, spans)
    signals = gate.verify(_RUN, "SUB-001", "C1")
    assert signals.extractor_disagreement is False


def test_tc_integ_06_overlapping_but_not_identical_disagrees(tmp_data_dir):
    """`TC-INTEG-06` — overlapping span sets: disagreement, because the declared
    comparison is byte-exact equality of the sets (the module's own no-normalization
    standard); a fuzzy 'close enough' here would be the same leniency CT-INTEG-01
    forbids in verification itself."""
    doc = _seed_document(tmp_data_dir)
    spans = _criterion_spans(doc)
    start = spans[0].start
    wider = (Span(start, start + len("mitochondrion is") , doc.markdown[start:start + len("mitochondrion is")]),)
    gate, _ = _two_family_gate(tmp_data_dir, spans, wider)
    signals = gate.verify(_RUN, "SUB-001", "C1")
    assert signals.extractor_disagreement is True


def test_tc_integ_06_disjoint_sets_disagree(tmp_data_dir):
    """`TC-INTEG-06` — disjoint span sets: disagreement."""
    doc = _seed_document(tmp_data_dir)
    spans = _criterion_spans(doc)
    other_start = doc.markdown.index("described")
    other = (Span(other_start, other_start + 9, "described"),)
    gate, _ = _two_family_gate(tmp_data_dir, spans, other)
    signals = gate.verify(_RUN, "SUB-001", "C1")
    assert signals.extractor_disagreement is True


def test_tc_integ_06_no_second_extraction_is_none_and_never_false(tmp_data_dir):
    """`TC-INTEG-06`'s three-valued distinction — `None` when no second extraction ran,
    and it must remain distinguishable from `False` ('measured, and agreed'): identity
    assertions, not truthiness, because `None == False` is False but `not None` and
    `not False` are the same, and a consumer collapsing them treats 'not measured' as
    'no disagreement' — exactly what CT-INTEG-02 declares wrong."""
    doc = _seed_document(tmp_data_dir)
    spans = _criterion_spans(doc)
    gate, _ = _two_family_gate(tmp_data_dir, spans, None)
    signals = gate.verify(_RUN, "SUB-001", "C1")
    assert signals.extractor_disagreement is None
    assert not (signals.extractor_disagreement is False)
    assert signals.extractor_disagreement != 0  # not falsy-numeric either


# --- TC-INTEG-08: every signal fails closed -------------------------------------------------

class _RaisingView(ExtractionView):
    """A view where one named read raises — TC-INTEG-08's injection point."""

    def __init__(self, fault: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._fault = fault

    def spans(self, submission_id, criterion_id):
        if self._fault == "spans":
            raise RuntimeError("injected: span read failed")
        return super().spans(submission_id, criterion_id)

    def regions(self, document_id):
        if self._fault == "regions":
            raise RuntimeError("injected: region read failed")
        return super().regions(document_id)

    def panel_sufficiency(self, submission_id, criterion_id):
        if self._fault == "panel":
            raise RuntimeError("injected: panel read failed")
        return super().panel_sufficiency(submission_id, criterion_id)

    def second_family_spans(self, submission_id, criterion_id):
        if self._fault == "second-family":
            raise RuntimeError("injected: second-family read failed")
        return super().second_family_spans(submission_id, criterion_id)


def _fault_gate(tmp_data_dir, fault: str, **view_kwargs):
    doc = _seed_document(tmp_data_dir)
    view = _RaisingView(fault, **view_kwargs)
    return _gate(tmp_data_dir, view)


def test_tc_integ_08_span_read_failure_yields_unverified_and_absent(tmp_data_dir):
    """`TC-INTEG-08` — the span computation cannot read its input: `spans_verified`
    False ('unverified') and `evidence_present` False ('absent'), never the permissive
    defaults."""
    gate, _ = _fault_gate(tmp_data_dir, "spans")
    signals = gate.verify(_RUN, "SUB-001", "C1")
    assert signals.spans_verified is False
    assert signals.evidence_present is False


def test_tc_integ_08_region_read_failure_yields_at_risk_and_described(tmp_data_dir):
    """`TC-INTEG-08` — the region computation cannot read its input: the confidence
    intersection fails to 'at-risk' and the described check fails to the routing-
    candidate value, both adverse (CT-INTEG-03: unverified, absent, insufficient,
    at-risk)."""
    doc = _seed_document(tmp_data_dir)
    gate, _ = _fault_gate(tmp_data_dir, "regions", spans=_criterion_spans(doc))
    signals = gate.verify(_RUN, "SUB-001", "C1")
    assert signals.ocr_overlap_risk is True
    assert signals.described_evidence is True


def test_tc_integ_08_panel_read_failure_yields_insufficient(tmp_data_dir):
    """`TC-INTEG-08` — the sufficiency computation cannot read the panel: flagged
    insufficient ('insufficient'), the conservative default CT-INTEG-11 also names for
    an unscored unit."""
    doc = _seed_document(tmp_data_dir)
    gate, _ = _fault_gate(tmp_data_dir, "panel", spans=_criterion_spans(doc))
    signals = gate.verify(_RUN, "SUB-001", "C1")
    assert signals.sufficiency_flag is True


def test_tc_integ_08_second_family_read_failure_yields_disagreement_not_none(tmp_data_dir):
    """`TC-INTEG-08` — the comparison computation cannot read the second family: the
    conservative value is `True` (adverse), **not** `None`. `None` means 'no second
    extraction ran' (CT-INTEG-02); here it ran and the reading failed, so 'not
    measured' would be a lie the confidence computation would consume as agreement."""
    doc = _seed_document(tmp_data_dir)
    gate, _ = _fault_gate(tmp_data_dir, "second-family", spans=_criterion_spans(doc),
                          second_family_spans=())
    signals = gate.verify(_RUN, "SUB-001", "C1")
    assert signals.extractor_disagreement is True
    assert signals.extractor_disagreement is not None
