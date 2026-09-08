"""`TC-INTEG-14` — the six integrity rates are emitted **per criterion** under their
declared names, and the verification-failure alert fires above its threshold.

Test plan §5.9 (P0, `FR-INTEG-01` + `FR-INTEG-03`, Observability / rung 2). Written
ahead of `#74` (test plan §8.2): every case fails only through `NotImplementedYet`
naming `#74`.

**The oracle is the exact rate against the injected rate**: four units, two carrying
hallucinated spans — the verification-failure rate must read 0.5, not "some failures
happened" and not an aggregate boolean. The dimensionality half is CT-INTEG-14's own
clause ("emitted per criterion rather than aggregated"): every one of the six metrics
must carry per-criterion rows, because the *reading* the design declares — a
verification-failure rate above a low threshold means the **extractor** is
hallucinating, a model or prompt problem, not a data problem — is only supportable
when the rate is dimensioned per criterion and the alert sits on it (RISK-01's
earliest detector).

Interface assumed of `#74` (reconcile at landing; full table in
`tests/support/integ_vocabulary.py`):

| Name | Status |
|---|---|
| `aeh.integ.INTEG_RATE_METRICS` | **invented-and-used-together constant**: the design names the six rates but not their spellings; the tuple is required by name so the case fails loudly if the names move, and reconciles at #74's landing |
| `aeh.integ.ALERT_SPAN_VERIFICATION_FAILURES` | **invented spelling** of CT-INTEG-14's declared alert, named after the store's own precedent (`ALERT_FREE_DISK`, `DECLARED_ALERTS` — the name is interface, not log text) |
| emission surface | rows in the store's `run_metrics` table, one per (metric, submission, criterion), value per row — the table the landed modules already emit through |
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.impl import INTEG_MODULE, require
from tests.support.integ_vocabulary import (
    Doc,
    ExtractionView,
    PanelFlags,
    Span,
    document_id_for,
    seed_document,
)
from tests.support.orch_run import seed_run

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

_COHORT = "c-2026-7B-integ"
_SUBMISSIONS = tuple(f"SUB-{300 + i}" for i in range(4))
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},)

_MARKDOWN = "The passage names three causes and one effect in plain prose.\n"

#: The injected hallucination rate: two of the four units carry spans that are not in
#: the document. The oracle is this number, read back from the emitted rate.
INJECTED_FAILURE_RATE = 0.5


def _unit_spans(doc: Doc, hallucinated: bool) -> tuple[Span, ...]:
    start = doc.markdown.index("causes")
    real = Span(start, start + len("causes"), "causes")
    forged = Span(0, 5, "blurb")  # not in the document
    return (forged,) if hallucinated else (real,)


def _scenario(tmp_data_dir, hallucinated_units: int):
    """A real run over four units; `hallucinated_units` of them carry forged spans."""
    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
    handle = store.cohort(_COHORT)
    IntegrityGate, rate_metrics, alert = require(
        INTEG_MODULE, "IntegrityGate", "INTEG_RATE_METRICS",
        "ALERT_SPAN_VERIFICATION_FAILURES", issue="#74",
    )
    gates = []
    for i, submission in enumerate(_SUBMISSIONS):
        doc = Doc(markdown=_MARKDOWN)
        seed_document(handle, document_id_for(submission), submission, doc.markdown)
        view = ExtractionView(
            spans=_unit_spans(doc, hallucinated=2 * i < hallucinated_units),
            panel=PanelFlags((True, True, True)),
        )
        gates.append((submission, IntegrityGate(handle, store.blobs(), view,
                                                ocr_conf_floor=0.70)))
    orch.enumerate_units(run_id)
    return store, handle, run_id, gate_metric_reader(handle), gates


def gate_metric_reader(handle):
    """The read side of the emission surface: metric rows for this run."""
    def read(metric_name: str) -> list[dict]:
        return handle.query(
            "SELECT submission_id, criterion_id, value FROM run_metrics WHERE "
            "name = :n ORDER BY submission_id",
            n=metric_name,
        )
    return read


def test_tc_integ_14_verification_failure_rate_matches_the_injected_rate(tmp_data_dir):
    """`TC-INTEG-14`'s exact-rate oracle — two of four units hallucinating: the emitted
    span-verification failure rate reads 0.5."""
    store, handle, run_id, read, gates = _scenario(
        tmp_data_dir, hallucinated_units=2
    )
    for submission, gate in gates:
        gate.verify(run_id, submission, "C1")
    rate_metrics = require(INTEG_MODULE, "INTEG_RATE_METRICS", issue="#74")
    # The tuple's contract: element 0 is the span-verification failure rate — the
    # metric RISK-01's alert sits on. Positional, spelled here so a reorder of the
    # constant fails loudly here rather than silently re-pointing the oracle.
    failure = read(rate_metrics[0])
    assert failure, "no span-verification failure rate was emitted"
    observed = sum(row["value"] for row in failure) / len(failure)
    assert observed == pytest.approx(INJECTED_FAILURE_RATE), (
        f"emitted verification-failure rate {observed} against injected "
        f"{INJECTED_FAILURE_RATE} — the rate is the detector RISK-01 leans on, and a "
        "rate that drifts from the injected truth is a silent detector"
    )
    store.close()


def test_tc_integ_14_all_six_rates_are_emitted_per_criterion(tmp_data_dir):
    """`TC-INTEG-14`'s dimensionality half (CT-INTEG-14) — all six rates emitted under
    their names, one row per (submission, criterion), not aggregated: the reading 'the
    extractor is hallucinating' is only supportable when the rate is dimensioned."""
    store, handle, run_id, read, gates = _scenario(
        tmp_data_dir, hallucinated_units=2
    )
    for submission, gate in gates:
        gate.verify(run_id, submission, "C1")
    rate_metrics = require(INTEG_MODULE, "INTEG_RATE_METRICS", issue="#74")
    assert len(rate_metrics) == 6, (
        f"{len(rate_metrics)} rate metrics declared — CT-INTEG-14 names exactly six"
    )
    for name in rate_metrics:
        rows = read(name)
        assert rows, f"{name}: no rows emitted"
        dimensions = {(row["submission_id"], row["criterion_id"]) for row in rows}
        assert dimensions == {
            (s, "C1") for s in _SUBMISSIONS
        }, f"{name}: rows are {sorted(dimensions)} — the rates must be per criterion"
    store.close()


def test_tc_integ_14_alert_fires_above_threshold_and_not_below(tmp_data_dir):
    """`TC-INTEG-14`'s alert — the verification-failure alert fires when the rate is
    above its threshold (the injected 0.5) and does not fire on a clean run: the
    earliest detector RISK-01 has, asserted in both directions."""
    # Above threshold:
    store, handle, run_id, read, gates = _scenario(
        tmp_data_dir, hallucinated_units=2
    )
    alert = require(INTEG_MODULE, "ALERT_SPAN_VERIFICATION_FAILURES", issue="#74")
    for submission, gate in gates:
        gate.verify(run_id, submission, "C1")
    fired = read(alert)
    assert fired, "a 0.5 verification-failure rate did not fire the alert"
    store.close()

    # Below threshold (no hallucinations at all):
    clean_store, clean_handle, clean_run, clean_read, clean_gates = _scenario(
        tmp_data_dir, hallucinated_units=0
    )
    for submission, gate in clean_gates:
        gate.verify(clean_run, submission, "C1")
    assert not clean_read(alert), (
        "the verification-failure alert fired on a run with zero failures — an alert "
        "that cries wolf on the happy path is RISK-01's detector switched off"
    )
    clean_store.close()
