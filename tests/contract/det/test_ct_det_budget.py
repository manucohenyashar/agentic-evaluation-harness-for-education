"""`CT-DET-11` — the single-pass budget (`TC-DET-C11`), the perf clause.

Case of test plan §6.11.11; issue #90 (TS-68). Green by design — `M-DET`
shipped via #246/#249.

The clause: all deterministic criteria for a 350-student cohort evaluate in a
**single pass**, under **5 seconds**, with **zero** model calls (`NFR-DET-01`,
`PERF-06`); cost is independent of panel size and of cohort size within an
order of magnitude.

The clause discriminator: the FR-level perf case runs the threshold once; this
case asserts the bound AND the zero AND both independence claims — the zero is
asserted EXACTLY (guard attempt count == 0), which is what makes the bound
credible, and the independence claims are asserted as invariants a consumer
can plan capacity against: byte-identical score rows across panel sizes
1/3/5 (a panel is a judged-run concept; a lookup cannot see it), and
sub-quadratic scaling across a 35 → 350 cohort sweep.

**Fixture discipline**: the fixture build is OUTSIDE every timed section —
the budget is the evaluation's, not the seeding's — and the 350-student world
is seeded in bulk transactions so the contract tier's time budget carries
assertions, not inserts.
"""

from __future__ import annotations

import json
import time

import pytest

from aeh.conf import resolve_run_config
from aeh.det import DeterministicEvaluator
from tests.support.conf_builders import CohortRef, edge_cfg, edge_panel
from tests.support.det_vocabulary import open_det_store, seed_det_package
from tests.support.orch_run import seed_cohort
from aeh.orch import Orchestrator

pytestmark = pytest.mark.contract

from tests.contract.det._doubles import ISSUE  # noqa: F401 — register citation

_CRITERIA = (
    {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
    {"criterion_id": "M2", "question_id": "Q2", "key": ("B",)},
)


def _seed_world(store, submissions, *, panel_size: int | None = None) -> str:
    """A cohort + package + run, with every submission answering B on both
    questions (so the pass is 2 × len(submissions) correct evaluations).
    Bulk-written: one transaction for the documents, one for the regions."""
    cohort_id = f"c-{len(submissions)}-p{panel_size or 0}"
    seed_cohort(store, submissions, cohort_id)
    version = seed_det_package(store, _CRITERIA)
    if panel_size is None:
        resolved = resolve_run_config(
            edge_cfg(), CohortRef(cohort_id=cohort_id, consent_class="synthetic")
        )
    else:
        resolved = resolve_run_config(
            edge_cfg(panel=edge_panel(panel_size)),
            CohortRef(cohort_id=cohort_id, consent_class="synthetic"),
        )
    run_id = Orchestrator(store).create_run(cohort_id, version, resolved)

    cohort = store.cohort(cohort_id)
    with cohort.transaction() as tx:
        for s in submissions:
            tx.execute(
                "INSERT INTO document (document_id, submission_id, "
                "content_hash, created_at) VALUES (:d, :s, :h, "
                "'2026-01-01T00:00:00+00:00')",
                d=f"doc-{s}", s=s, h=f"hash-{s}",
            )
    with cohort.transaction() as tx:
        for s in submissions:
            for q in ("Q1", "Q2"):
                tx.execute(
                    "INSERT INTO document_region (region_id, document_id, "
                    "page_no, element_kind, region_kind, retraction, "
                    "content_state, selection_state, selection, position) "
                    "VALUES (:r, :d, 1, :q, 'selection_mark', NULL, "
                    "'present', 'resolved', 'B', 0)",
                    r=f"reg-{s}-{q}", d=f"doc-{s}", q=q,
                )
    return run_id


def _score_bytes(store, cohort_id) -> bytes:
    rows = store.cohort(cohort_id).query(
        "SELECT submission_id, criterion_id, band, points, state, routing "
        "FROM criterion_score ORDER BY submission_id, criterion_id"
    )
    return json.dumps(
        [list(row) for row in rows], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def test_tc_det_c11_350_students_single_pass_under_five_seconds(
        tmp_data_dir, network_guard):
    """`TC-DET-C11` (the threshold) — a 350-student cohort, both criteria
    deterministic: ONE `evaluate_cohort` call evaluates all 700 in under 5
    seconds, the score rows land exactly once per (submission, criterion) —
    the single pass, observable as an exact population with no duplicates —
    and the guard's attempt count is EXACTLY zero."""
    store = open_det_store(tmp_data_dir)
    try:
        submissions = tuple(f"S{i:03d}" for i in range(1, 351))
        run_id = _seed_world(store, submissions)

        evaluator = DeterministicEvaluator(store)
        start = time.perf_counter()
        report = evaluator.evaluate_cohort(run_id)
        elapsed = time.perf_counter() - start

        assert (report.submissions, report.criteria) == (350, 2)
        assert report.evaluations == 700, (
            f"TC-DET-C11: {report.evaluations} evaluations — the pass did "
            "not cover the stated load once each."
        )
        assert report.evaluations == report.correct == 700
        assert elapsed < 5.0, (
            f"TC-DET-C11: the 350-student pass took {elapsed:.2f}s — the "
            "5-second bound (PERF-06) is blown. Loosening the bound in this "
            "case is RISK-33; calibrate the environment instead."
        )
        # The single pass, from the store: exactly 700 rows, one per pair.
        n_rows = store.cohort(report.cohort_id).query(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT submission_id || ':' || "
            "criterion_id) AS pairs FROM criterion_score"
        )[0]
        assert n_rows["n"] == 700 and n_rows["pairs"] == 700
        # The zero, exact: the bound is credible because nothing called out.
        assert network_guard.attempts == [], (
            f"TC-DET-C11: {len(network_guard.attempts)} connection attempt(s) "
            "in a deterministic pass — the budget's zero-model-call claim "
            "failed."
        )
        network_guard.assert_no_network()
    finally:
        store.close()


def test_tc_det_c11_cost_is_independent_of_panel_size(tmp_data_dir,
                                                      network_guard):
    """`TC-DET-C11` (panel independence) — the same 20-student cohort
    evaluated under panel sizes 1, 3 and 5: the score rows are BYTE-identical
    across the three runs and each pass makes zero model calls. A panel is a
    judged-run concept; a lookup cannot see it — that IS the cost
    independence the clause states, and the byte differential is what a
    consumer planning capacity against it relies on."""
    results = []
    for panel_size in (1, 3, 5):
        store = open_det_store(tmp_data_dir / f"p{panel_size}")
        try:
            submissions = tuple(f"S{i:02d}" for i in range(1, 21))
            run_id = _seed_world(store, submissions, panel_size=panel_size)
            report = DeterministicEvaluator(store).evaluate_cohort(run_id)
            assert report.evaluations == 40
            results.append((panel_size, _score_bytes(store, report.cohort_id)))
        finally:
            store.close()
    assert len(results) == 3
    assert results[0][1] == results[1][1] == results[2][1], (
        "TC-DET-C11: deterministic score rows differ across panel sizes — "
        "the pass is not panel-independent."
    )
    assert network_guard.attempts == []


def test_tc_det_c11_cost_scales_within_an_order_of_magnitude(tmp_data_dir):
    """`TC-DET-C11` (cohort independence) — 35 and 350 students, the two ends
    of an order of magnitude: the large pass's wall time stays under 40× the
    small's (linear is 10×; the headroom above that is machine noise on a
    sub-100ms baseline, not permission to go quadratic — O(n²) costs ~100×
    here and fails), and BOTH stay under the clause's 5-second bound. Per
    evaluation, the two runs cost the same order — the property a consumer
    plans capacity against."""
    timings = {}
    for size in (35, 350):
        store = open_det_store(tmp_data_dir / f"n{size}")
        try:
            submissions = tuple(f"S{i:03d}" for i in range(1, size + 1))
            run_id = _seed_world(store, submissions)
            evaluator = DeterministicEvaluator(store)
            start = time.perf_counter()
            report = evaluator.evaluate_cohort(run_id)
            elapsed = time.perf_counter() - start
            assert report.evaluations == size * 2
            timings[size] = elapsed
        finally:
            store.close()
    assert timings[350] < 5.0 and timings[35] < 5.0, (
        f"TC-DET-C11: a bound blew at the edges: {timings}."
    )
    assert timings[350] <= 40.0 * max(timings[35], 1e-4), (
        f"TC-DET-C11: 35 students took {timings[35]:.3f}s but 350 took "
        f"{timings[350]:.3f}s — more than 40× for 10× the cohort; the cost "
        "curve left the order of magnitude."
    )
