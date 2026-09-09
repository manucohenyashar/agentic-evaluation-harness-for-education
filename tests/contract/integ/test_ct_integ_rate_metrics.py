"""`CT-INTEG-14` — the six integrity rates are emitted **per criterion** under
their names, the metric is **dimensioned** so the declared reading is
supportable, and **an alert exists on it**; the reading itself — a span
verification failure rate above a low threshold means the **extractor is
hallucinating spans**, a model or prompt problem, not a data problem — is
**contract** (`TC-INTEG-C14`).

Case of test plan §6.11.9; TS-66 (issue #77). Written ahead of `#74`.

The integration suite (`tests/integration/integ/test_integ_observability.py`)
owns the exact-rate oracle (injected 0.5 read back) and the above/below
threshold alert sweep — over ONE criterion. This case owns what that shape
structurally cannot:

1. **Names and dimensionality as artifact** — the six rates are a declared
   constant (`INTEG_RATE_METRICS`, the #75-reconciled spelling) of six
   DISTINCT strings, the alert constant is a string OUTSIDE the six (it sits
   ON one of them, not among them), and the rates are emitted **per
   criterion rather than aggregated**: two criteria with different injected
   truth in the SAME run must read different values — a single blended row
   fails. #75's single-criterion file cannot see aggregation across criteria.
2. **The reading is contract** — attribution specificity: five criteria in one
   run, each carrying a DIFFERENT problem (hallucination, low-OCR overlap,
   described-region evidence, absent evidence, extractor disagreement), and
   the verification-failure rate moves ONLY on the hallucinating one. A gate
   that lumps a data problem into the span-verification rate makes the
   clause's reading false — an operator would be told the extractor is
   hallucinating when the data was the problem.
3. **The alert is on the rate, not on "something went wrong"** — it fires for
   the hallucinating criterion and for no data-problem criterion, on the same
   run.

**Disclosures register** (nothing new is minted beyond the #75 table):

| Name | Status |
|---|---|
| positional order | the design names the six rates in a fixed order ("span verification failure rate, empty-evidence rate, `ocr_overlap_risk` rate, described-evidence rate, sufficiency-flag rate, extractor disagreement rate"); #75 pinned position 0, and this case — the names artifact case — pins all six positions against that enumeration. A `#74` that lands a different order reds here and reconciles (the spellings themselves stay `#74`'s) |
| per-cell values | each rate row's `value` is that (submission, criterion) cell's own rate — with one unit per cell the values read 0.0/1.0; rate-ness across units is #75's injected-0.5 oracle. An aggregate-across-criteria emission (one blended row) fails the distinct-values limb |
| per-criterion alert rows | the alert is read through the same durable surface as the rates (#75's `read(alert)`), so its rows carry the migration's criterion dimension; the case asserts the alert fired FOR the hallucinating criterion and named NO data-problem criterion, without pinning whether unfired criteria have rows |
| the empty cell's other rates | the absent-evidence cell (no spans) has no verification to fail; whether its failure-rate row is emitted vacuously 0.0 or omitted is C07/CT-INTEG-07 territory — this case drives only that cell's empty-evidence rate |
| sufficiency rate values | pre-Sweep-2 the flag reads its conservative default (CT-INTEG-11); whether the rate counts the default or the final value is the timing reconcile — this case pins the sufficiency rate's per-criterion EMISSION, never its value |
| disagreement drive | `extractor_disagreement` is tri-state; the drive is the minimal one — a second family whose spans differ makes the rate 1.0. The exact comparison `#74` reconciles |
| emission surface | durable `run_metrics` rows (`submission_id`, `criterion_id`, `value` per `run_id, metric`) — the #75-declared migration; a `#74` that keeps the aggregate PK fails the dimensionality limb |
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.contract.integ._doubles import byte_span
from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    CitedRegion,
    ExtractionView,
    PanelFlags,
    Span,
    document_id_for,
    seed_document,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.contract

_SUBMISSION = "SUB-C14"
_MARKDOWN = "The student argues the thesis directly in the opening paragraph.\n"

# The six positions, pinned to the clause's own enumeration order (see the
# positional-order disclosure). The spellings are #74's; the ORDER is the
# design's.
_FAILURE, _EMPTY, _OCR, _DESCRIBED, _SUFFICIENCY, _DISAGREEMENT = range(6)


# --- the reading oracle and its teeth --------------------------------------------------------


def _assert_extractors_are_blamed(rates: dict[str, float], alerts: set,
                                  hallucinating: str) -> None:
    """The reading oracle: the span-verification failure rate is above its
    threshold exactly where the extractor hallucinated — zero on every
    data-problem criterion — and the alert fires exactly there. A rate that
    moves on a data problem makes the clause's declared reading false."""
    assert rates[hallucinating] > 0.0, (
        f"the hallucinating criterion {hallucinating} reads failure rate "
        f"{rates[hallucinating]} — the injected hallucination did not register and "
        "the reading has nothing to stand on"
    )
    for criterion, rate in rates.items():
        if criterion == hallucinating:
            continue
        assert rate == 0.0, (
            f"criterion {criterion} carries no hallucinated span yet its "
            f"verification-failure rate reads {rate} — a data problem was counted as "
            "a span verification failure, and the clause's reading (a rate above the "
            "threshold means the extractor is hallucinating) is false as contract"
        )
    for criterion in alerts:
        assert criterion == hallucinating, (
            f"the verification-failure alert fired for criterion {criterion} — a data "
            "problem was read as extractor hallucination, the exact misreading the "
            "clause forbids"
        )
    assert hallucinating in alerts, (
        f"the failure rate for {hallucinating} is above the threshold and no alert "
        "fired for it — RISK-01's earliest detector is switched off"
    )


def test_tc_integ_c14_the_reading_oracle_has_teeth():
    """`TC-INTEG-C14`'s executable construction — the lumper (a data problem
    counted into the failure rate), the misattributing alert, and the silent
    alert all go red. Runs green now: it asserts the oracle's teeth, not the
    implementation."""
    _assert_extractors_are_blamed({"M-HALLUC": 1.0, "D-OCR": 0.0},
                                  {"M-HALLUC"}, "M-HALLUC")     # faithful
    with pytest.raises(AssertionError, match="counted as a span verification failure"):
        _assert_extractors_are_blamed({"M-HALLUC": 1.0, "D-OCR": 1.0},
                                      {"M-HALLUC"}, "M-HALLUC")  # the lumper
    with pytest.raises(AssertionError, match="misreading"):
        _assert_extractors_are_blamed({"M-HALLUC": 1.0, "D-OCR": 0.0},
                                      {"D-OCR"}, "M-HALLUC")     # misattributed alert
    with pytest.raises(AssertionError, match="earliest detector"):
        _assert_extractors_are_blamed({"M-HALLUC": 1.0, "D-OCR": 0.0},
                                      set(), "M-HALLUC")          # silent alert


# --- the harness -----------------------------------------------------------------------------


def _view_for(problem: str) -> ExtractionView:
    """One criterion's extraction side, carrying exactly one problem."""
    span = byte_span(_MARKDOWN, "thesis")
    spans: tuple[Span, ...]
    regions: tuple[CitedRegion, ...] = ()
    second = None
    if problem == "clean":
        spans = (span,)
    elif problem == "hallucinated":
        spans = (Span(0, 5, "blurb"),)  # not in the document
    elif problem == "ocr":
        spans = (span,)
        regions = (CitedRegion(region_id="r-c14-ocr", region_kind="transcribed_text",
                               start=span.start, end=span.end, ocr_conf=0.40,
                               crop_ref=None, content_state="present"),)
    elif problem == "described":
        spans = (span,)
        regions = (CitedRegion(region_id="r-c14-desc", region_kind="described_graphic",
                               start=span.start, end=span.end, ocr_conf=None,
                               crop_ref=None, content_state="present"),)
    elif problem == "empty":
        spans = ()
    elif problem == "disagreement":
        spans = (span,)
        second = (byte_span(_MARKDOWN, "argues"),)
    else:
        raise AssertionError(f"unknown problem {problem!r}")
    return ExtractionView(spans=spans, second_family_spans=second, regions=regions,
                          panel=PanelFlags((True, True, True)))


def _sweep(tmp_data_dir, problems: dict[str, str]) -> tuple:
    """One run, one submission, one criterion per problem; every cell verified.
    Returns (store, read, rate_metrics, alert) — `read` is the durable metric
    reader #75's review finding prescribed."""
    store = open_store(tmp_data_dir)
    criteria = tuple({"criterion_id": c, "kind": "open", "scoring_model": "holistic"}
                     for c in problems)
    orch, run_id, _version = seed_run(store, submissions=(_SUBMISSION,),
                                      criteria=criteria)
    handle = store.cohort(ORCH_COHORT_ID)
    seed_document(handle, document_id_for(_SUBMISSION), _SUBMISSION, _MARKDOWN,
                  ORCH_COHORT_ID)
    orch.enumerate_units(run_id)
    gate_cls, rate_metrics, alert = require(
        INTEG_MODULE, "IntegrityGate", "INTEG_RATE_METRICS",
        "ALERT_SPAN_VERIFICATION_FAILURES", issue="#74",
    )
    for criterion, problem in problems.items():
        gate_cls(handle, store.blobs(), _view_for(problem), ocr_conf_floor=0.70).verify(
            run_id, _SUBMISSION, criterion)
    durable = store.durable()

    def read(metric_name: str) -> list[dict]:
        return durable.query(
            "SELECT submission_id, criterion_id, value FROM run_metrics "
            "WHERE run_id = :r AND metric = :n",
            r=run_id, n=metric_name,
        )

    return store, read, rate_metrics, alert


# --- the artifact: names, distinctness, and the alert's place --------------------------------


@pytest.mark.writtenahead
def test_tc_integ_c14_the_six_rate_names_and_the_alert_are_declared_interface():
    """`TC-INTEG-C14`'s artifact limb — the six rates exist as a declared
    constant of six DISTINCT strings (the clause names exactly six), and the
    alert constant is a string OUTSIDE the six: it sits on one of them, it is
    not itself a rate. The spellings are #74's to reconcile; the SHAPES are
    this case's."""
    rate_metrics, alert = require(INTEG_MODULE, "INTEG_RATE_METRICS",
                                  "ALERT_SPAN_VERIFICATION_FAILURES", issue="#74")
    assert isinstance(rate_metrics, tuple), (
        "the six rates must be one declared constant — per-criterion emission "
        "cannot be reconciled against six loose names"
    )
    assert len(rate_metrics) == 6, (
        f"{len(rate_metrics)} rate metrics declared — CT-INTEG-14 names exactly six"
    )
    assert len(set(rate_metrics)) == 6, (
        "duplicate names among the six rates — two design rates collapse into one "
        "metric and the per-problem attribution below cannot be read"
    )
    assert all(isinstance(name, str) and name for name in rate_metrics), (
        "a rate metric name is empty or not a string"
    )
    assert isinstance(alert, str) and alert, "the alert constant is not a name"
    assert alert not in rate_metrics, (
        "the alert constant is among the six rate names — an alert sits ON a rate, "
        "it is not itself one of the six"
    )


# --- dimensionality: per criterion, not aggregated --------------------------------------------


@pytest.mark.writtenahead
def test_tc_integ_c14_rates_are_per_criterion_not_aggregated(tmp_data_dir):
    """`TC-INTEG-C14`'s dimensionality limb — two criteria in the SAME run with
    different injected truth (one hallucinating, one clean): the failure rate
    reads 1.0 for the one and 0.0 for the other, and all six rates carry rows
    for BOTH criteria. One blended aggregate row cannot satisfy both readings;
    #75's single-criterion file structurally cannot see this mutant."""
    store, read, rate_metrics, alert = _sweep(
        tmp_data_dir, {"C1": "hallucinated", "C2": "clean"})
    try:
        values = {(row["criterion_id"]): row["value"] for row in read(rate_metrics[_FAILURE])}
        assert values["C1"] == pytest.approx(1.0), (
            f"the hallucinating criterion's failure rate reads {values['C1']} — the "
            "per-cell value must be that criterion's own rate"
        )
        assert values["C2"] == pytest.approx(0.0), (
            "the clean criterion's failure rate moved — aggregation across criteria "
            "blends the hallucination into every criterion's reading"
        )
        for position in range(6):
            rows = read(rate_metrics[position])
            dims = {row["criterion_id"] for row in rows}
            assert {"C1", "C2"} <= dims, (
                f"{rate_metrics[position]}: rows for {sorted(dims)} — the rates must "
                "be emitted per criterion rather than aggregated"
            )
        fired = {row["criterion_id"] for row in read(alert)}
        assert "C1" in fired, (
            "the hallucinating criterion's rate is above the threshold and the alert "
            "did not fire for it"
        )
        assert not (fired & {"C2"}), (
            "the alert fired for the clean criterion — an undimensioned alert is a "
            "false accusation waiting to happen"
        )
    finally:
        store.close()


# --- the reading is contract: attribution specificity -----------------------------------------


@pytest.mark.writtenahead
def test_tc_integ_c14_a_data_problem_is_never_a_span_verification_failure(
        tmp_data_dir):
    """`TC-INTEG-C14`'s reading limb — five criteria, five different problems,
    one run: the verification-failure rate moves ONLY on the hallucinating
    criterion; the OCR, described-evidence, empty-evidence and disagreement
    rates each move only on their own cell; and the alert fires for the
    hallucination alone. 'Not a data problem' is contract, asserted in both
    directions."""
    store, read, rate_metrics, alert = _sweep(
        tmp_data_dir,
        {"C1": "hallucinated", "C2": "ocr", "C3": "described", "C4": "empty",
         "C5": "disagreement"},
    )
    try:
        def by_criterion(position: int) -> dict:
            return {row["criterion_id"]: row["value"] for row in read(rate_metrics[position])}

        failure = by_criterion(_FAILURE)
        # The reading, hallucination-side: the rate is high exactly there.
        # C4's failure rate is unpinned (no spans — see the disclosure).
        _assert_extractors_are_blamed(
            {c: failure[c] for c in ("C1", "C2", "C3", "C5")},
            {row["criterion_id"] for row in read(alert)} & {"C1", "C2", "C3", "C5"},
            "C1",
        )
        # ...and in the other direction: the hallucination must not move the
        # data-signal rates either, or the operator reading THOSE rates is
        # misled about where the problem is.
        for position, name in ((_OCR, "ocr_overlap_risk"),
                               (_DESCRIBED, "described-evidence"),
                               (_DISAGREEMENT, "extractor-disagreement")):
            rates = by_criterion(position)
            assert rates.get("C1", 0.0) == pytest.approx(0.0), (
                f"the hallucinating criterion's {name} rate reads {rates.get('C1')} — "
                "a span problem was counted into a data-signal rate, the mirror "
                "misattribution"
            )
        # Each data problem moves exactly its own rate.
        assert by_criterion(_OCR)["C2"] == pytest.approx(1.0)
        assert by_criterion(_DESCRIBED)["C3"] == pytest.approx(1.0)
        assert by_criterion(_EMPTY)["C4"] == pytest.approx(1.0)
        assert by_criterion(_DISAGREEMENT)["C5"] == pytest.approx(1.0)
    finally:
        store.close()
