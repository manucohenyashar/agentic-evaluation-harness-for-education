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

**The emission surface is the durable `run_metrics` table** — the table the landed
modules already write through — read through `store.durable()`, not the cohort handle
(review finding: the table lives in the durable tier; a cohort-scoped reader could
never see it). The landed schema is `(run_id, metric, value)` with PK
`(run_id, metric)`, which structurally cannot hold a per-criterion rate, so the
per-criterion rows (`submission_id`, `criterion_id` columns) are the part of the
surface `#74` lands with a migration — recorded in the interface table in
`tests/support/integ_vocabulary.py`; a `#74` that keeps the aggregate PK fails the
dimensionality case below rather than the reader drifting.

Interface assumed of `#74` (reconcile at landing; full table in
`tests/support/integ_vocabulary.py`):

| Name | Status |
|---|---|
| `aeh.integ.INTEG_RATE_METRICS` | **invented-and-used-together constant**: the design names the six rates but not their spellings; the tuple is required by name so the case fails loudly if the names move, and reconciles at #74's landing |
| `aeh.integ.ALERT_SPAN_VERIFICATION_FAILURES` | **invented spelling** of CT-INTEG-14's declared alert, named after the store's own precedent (`ALERT_FREE_DISK`, `DECLARED_ALERTS` — the name is interface, not log text) |
| emission surface | durable `run_metrics` rows, one per (metric, submission, criterion), value per row — see above |
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
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration]

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
    """A real run over four units; `hallucinated_units` of them carry forged spans.

    Everything lives under the caller's directory — two scenarios in one test get two
    directories, because a second `seed_run` over the same store would collide with
    the first scenario's cohort row (review finding).
    """
    store = open_store(tmp_data_dir)
    orch, run_id, _version = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
    handle = store.cohort(ORCH_COHORT_ID)
    IntegrityGate, rate_metrics, alert = require(
        INTEG_MODULE, "IntegrityGate", "INTEG_RATE_METRICS",
        "ALERT_SPAN_VERIFICATION_FAILURES", issue="#74",
    )
    gates = []
    for i, submission in enumerate(_SUBMISSIONS):
        doc = Doc(markdown=_MARKDOWN)
        seed_document(handle, document_id_for(submission), submission, doc.markdown,
                      ORCH_COHORT_ID)
        view = ExtractionView(
            spans=_unit_spans(doc, hallucinated=i < hallucinated_units),
            panel=PanelFlags((True, True, True)),
        )
        gates.append((submission, IntegrityGate(handle, store.blobs(), view,
                                                ocr_conf_floor=0.70)))
    orch.enumerate_units(run_id)
    return store, run_id, gate_metric_reader(store, run_id), gates


def gate_metric_reader(store, run_id: str):
    """The read side of the emission surface: one metric's durable rows for this run.

    Reads through the **durable** handle (where `run_metrics` lives) and filters by
    `run_id`, so two scenarios in one test cannot see each other's rows. The reader
    names `submission_id` / `criterion_id` / `value` — the per-criterion shape CT-INTEG-14
    requires and `#74`'s migration adds (see module docstring).
    """
    durable = store.durable()

    def read(metric_name: str) -> list[dict]:
        return durable.query(
            "SELECT submission_id, criterion_id, value FROM run_metrics "
            "WHERE run_id = :r AND metric = :n ORDER BY submission_id",
            r=run_id,
            n=metric_name,
        )

    return read


def test_tc_integ_14_verification_failure_rate_matches_the_injected_rate(tmp_data_dir):
    """`TC-INTEG-14`'s exact-rate oracle — two of four units hallucinating: the emitted
    span-verification failure rate reads 0.5."""
    store, run_id, read, gates = _scenario(tmp_data_dir, hallucinated_units=2)
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
    store, run_id, read, gates = _scenario(tmp_data_dir, hallucinated_units=2)
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
    earliest detector RISK-01 has, asserted in both directions. The two scenarios run
    in separate directories and each read filters by its own run id, so the clean run
    cannot inherit the dirty run's rows (review finding)."""
    # Above threshold:
    store, run_id, read, gates = _scenario(
        tmp_data_dir / "above", hallucinated_units=2
    )
    alert = require(INTEG_MODULE, "ALERT_SPAN_VERIFICATION_FAILURES", issue="#74")
    for submission, gate in gates:
        gate.verify(run_id, submission, "C1")
    fired = read(alert)
    assert fired, "a 0.5 verification-failure rate did not fire the alert"
    store.close()

    # Below threshold (no hallucinations at all):
    clean_store, clean_run, clean_read, clean_gates = _scenario(
        tmp_data_dir / "below", hallucinated_units=0
    )
    for submission, gate in clean_gates:
        gate.verify(clean_run, submission, "C1")
    assert not clean_read(alert), (
        "the verification-failure alert fired on a run with zero failures — an alert "
        "that cries wolf on the happy path is RISK-01's detector switched off"
    )
    clean_store.close()


def test_tc_store_03_the_dimensioned_run_metrics_key_dedupes_every_writer(
        tmp_data_dir):
    """Review regression behind migration 5 (Durable v5, `#73`/`#74`) — the rebuilt
    `run_metrics` primary key dedupes BOTH writers.

    M-ORCH's declared rate flush names three columns; the gate's upserts name five.
    With `NULL`-able dimensions the two NULLs in M-ORCH's row are DISTINCT in a
    non-INTEGER primary key, so `INSERT OR REPLACE` never conflicts with itself and
    every `progress()` flush would stack a fresh row per metric — unbounded
    duplication on the table CT-STORE-03 gives M-ORCH sole writership of. The
    migration's dimension columns are therefore `NOT NULL DEFAULT ''`: the
    three-column flush lands on the `('', '')` aggregate cell and replaces in place,
    the gate's full-cell emissions carry real dimensions and replace their own cell,
    and neither writer's re-flush can stack a second row.
    """
    store = open_store(tmp_data_dir)
    durable = store.durable()
    # M-ORCH's declared statement shape (orch.py's `insert_run_metric`): three
    # columns, the dimensions omitted. Two identical flushes — one row.
    with durable.transaction() as tx:
        for value in (0.5, 1.5):
            tx.execute(
                "INSERT OR REPLACE INTO run_metrics (run_id, metric, value) "
                "VALUES (:run_id, :metric, :value)",
                run_id="run-dedup", metric="sweep_units", value=value,
            )
    rows = durable.query(
        "SELECT value FROM run_metrics WHERE run_id = :r AND metric = :n",
        r="run-dedup", n="sweep_units",
    )
    assert len(rows) == 1 and rows[0]["value"] == 1.5, (
        f"M-ORCH's three-column flush stacked {len(rows)} rows — the dimensioned "
        "primary key does not dedupe a writer that omits the dimensions, and every "
        "progress() pass would append (CT-STORE-03: one REPLACE per metric)"
    )

    # The gate's full-cell emission over a real run: two verifies emit the same
    # cell twice — one dimensioned row, distinct from the `('', '')` cell above.
    orch, run_id, _version = seed_run(
        store, submissions=("SUB-900",), criteria=_CRITERIA
    )
    handle = store.cohort(ORCH_COHORT_ID)
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    doc = Doc(markdown=_MARKDOWN)
    seed_document(handle, document_id_for("SUB-900"), "SUB-900", doc.markdown,
                  ORCH_COHORT_ID)
    start = doc.markdown.index("causes")
    gate = IntegrityGate(
        handle, store.blobs(),
        ExtractionView(spans=(Span(start, start + len("causes"), "causes"),),
                       panel=PanelFlags((True, True, True))),
        ocr_conf_floor=0.70,
    )
    rate_metrics = require(INTEG_MODULE, "INTEG_RATE_METRICS", issue="#74")
    for _ in range(2):
        gate.verify(run_id, "SUB-900", "C1")
    emitted = durable.query(
        "SELECT submission_id, criterion_id, value FROM run_metrics "
        "WHERE run_id = :r AND metric = :n",
        r=run_id, n=rate_metrics[0],
    )
    assert len(emitted) == 1, (
        f"two gate emissions stacked {len(emitted)} rows for one cell — the "
        "dimensioned primary key must REPLACE the cell's earlier value (CT-INTEG-14)"
    )
    assert emitted[0]["submission_id"] == "SUB-900", (
        "the gate's full-cell rate lost its dimensions — the aggregate '' cell the "
        "M-ORCH flush writes and the gate's dimensioned cell are distinct rows"
    )
    store.close()
