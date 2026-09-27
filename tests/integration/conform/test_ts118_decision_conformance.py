"""TS-118 (#471): conformance and performance for the decision engine. Jev test plan §6.

| Case | Asserted |
|---|---|
| TC-CONFORM-14 | E1: F-JEV through the decision path on both backends' recorded answers: per backend the accepted rate, cross-backend exact/adjacent agreement, the gate histogram and the ineligibility reasons, and a backend-scoped validation record each; no threshold. The live arm (`@live`) needs E2/E7 |
| TC-CONFORM-15 | The LLM-median divergence equals the hand count: 8 of 40 cells |
| PERF-15 | **Live** (`@live`): 200 accepted seats at 16 citation questions, p95 reported against 1,000 ms (cloud) |
| PERF-16 | **Live** (`@live`): base-sweep wall time engine on vs off, inconclusive (not failed) above a 40% fallback rate |
"""

from __future__ import annotations

import os
import time
from decimal import Decimal

import pytest

from aeh.conf import DecisionEngine, ModelRef

pytestmark = pytest.mark.integration

BACKENDS = {
    "openrouter-jev": ("openrouter/typesafe/jev-1.13@2026-09-17", None, "cloud", "cloud-hosted"),
    "openjev": ("/models/openjev-FP8/model.safetensors@sha256:" + "ab" * 32, "fp8", "edge", "edge-local"),
}


def _engine(provider, build, quant):
    return DecisionEngine(model=ModelRef(role="decision", provider=provider, build_id=build, quantization=quant),
                          confidence_threshold=Decimal("0.80"), cite_threshold=Decimal("0.50"),
                          max_citation_questions=16, token_bytes_ratio=3)


@pytest.fixture
def e1_report(tmp_path):
    from aeh import conform
    from aeh.prov import RecordedFixtureProvider
    from tests.support import jev_corpora

    backends = {}
    for name, (build, quant, corpus_backend, profile) in BACKENDS.items():
        engine = _engine(name, build, quant)
        jev_corpora.record_f_jev(tmp_path / name, corpus_backend, engine)
        backends[name] = (RecordedFixtureProvider(fixture_dir=tmp_path / name), engine, profile)
    return conform.run_decision_conformance(backends)


def test_tc_conform_14_the_e1_arm_reports_per_backend(e1_report) -> None:
    from aeh import pkg

    assert set(e1_report.per_backend) == set(BACKENDS)
    for name, figures in e1_report.per_backend.items():
        assert figures["cells"] == 40
        assert figures["decision_accepted_rate"] == pytest.approx(24 / 40)
        assert figures["decision_band_exact_agreement"] == 1.0 and figures["decision_band_adjacent_agreement"] == 1.0
        assert sum(figures["decision_gate_histogram"].values()) == 40
        assert isinstance(figures["decision_ineligible_reasons"], dict)
    profiles = {r.backend_profile for r in e1_report.validation_records}
    assert profiles == {"cloud-hosted", "edge-local"}, "one backend-scoped record each, never merged"
    keys = [k for k in pkg._VALIDATION_ADMINISTRATION_RECORDS if k[-1].startswith("F-JEV@")]
    assert {k[3] for k in keys} >= {"cloud-hosted", "edge-local"}
    assert not hasattr(e1_report, "passed") and not hasattr(e1_report, "blocked"), "no pass/fail (Q-J5)"


def test_tc_conform_14_agreement_counts_only_cells_both_accepted(tmp_path) -> None:
    """A discriminating arm: the edge backend's answer is moved one band up on JEV-01..JEV-12
    and made a tie (below the gate) on JEV-13..JEV-16. Hand count over the cloud-accepted cells:
    of the 24, 4 are no longer accepted on edge and drop out; of the 20 left, those among
    JEV-01..12 that the cloud accepted now differ by exactly one band."""
    from aeh import conform
    from aeh.prov import RecordedFixtureProvider
    from tests.support import jev_corpora

    backends = {}
    cloud_build, cloud_quant, _, cloud_profile = BACKENDS["openrouter-jev"]
    cloud = _engine("openrouter-jev", cloud_build, cloud_quant)
    jev_corpora.record_f_jev(tmp_path / "cloud", "cloud", cloud)
    backends["openrouter-jev"] = (RecordedFixtureProvider(fixture_dir=tmp_path / "cloud"), cloud, cloud_profile)
    edge_build, edge_quant, _, edge_profile = BACKENDS["openjev"]
    edge = _engine("openjev", edge_build, edge_quant)
    provider = RecordedFixtureProvider(fixture_dir=tmp_path / "edge")
    moved, tied = set(), set()
    from aeh.judge import decision_request
    for cell_id, (cell, scoring) in jev_corpora.f_jev_requests().items():
        figures = dict(cell["answers"]["edge"])
        probs = list(figures["band_probabilities"])
        index = int(cell_id.split("-")[1])
        if index <= 12 and cell["reference_ordinal"] < len(probs) - 1:
            top = probs.index(max(probs))
            probs[top], probs[top + 1] = probs[top + 1], probs[top]
            moved.add(cell_id)
        elif 13 <= index <= 16:
            top = probs.index(max(probs))
            other = top + 1 if top + 1 < len(probs) else top - 1
            half = (probs[top] + probs[other]) / 2
            probs[top] = probs[other] = half
            tied.add(cell_id)
        figures["band_probabilities"] = probs
        request = decision_request(scoring, edge)
        provider.record_decision(request, edge.model, jev_corpora.answer_document(request, figures, "openjev"))
    backends["openjev"] = (provider, edge, edge_profile)
    report = conform.run_decision_conformance(backends)
    cloud_figures = report.per_backend["openrouter-jev"]
    assert 0 < cloud_figures["decision_band_exact_agreement"] < 1.0
    assert cloud_figures["decision_band_adjacent_agreement"] == 1.0, "a one-band move is adjacent"
    assert report.per_backend["openjev"]["decision_accepted_rate"] < cloud_figures["decision_accepted_rate"]


def test_tc_conform_15_divergence_equals_the_hand_count(e1_report) -> None:
    """Hand count: the engine's argmax is the reference band on every cell except the four
    adversarial ones (JEV-37..40, top band); the recorded LLM median differs from the reference
    on JEV-08/16/24/32/40. Divergent: JEV-08, 16, 24, 32, 37, 38, 39, 40, so 8 of 40."""
    for figures in e1_report.per_backend.values():
        assert figures["decision_llm_median_divergence"] == pytest.approx(8 / 40)


@pytest.mark.live
def test_tc_conform_14_live_arm() -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("the live arm runs on E2 with OPENROUTER_API_KEY (and E7 for OpenJev)")
    from aeh import conform
    from aeh.prov import JevOpenRouterProvider

    build, quant, _, profile = BACKENDS["openrouter-jev"]
    provider = JevOpenRouterProvider(retention_answers=lambda b: "zero-retention")
    report = conform.run_decision_conformance({"openrouter-jev": (provider, _engine("openrouter-jev", build, quant),
                                                                  profile)})
    assert set(conform.DECISION_REPORT_KEYS) <= set(report.per_backend["openrouter-jev"])


@pytest.mark.live
def test_perf_15_decision_seat_latency_reported() -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("PERF-15 runs on E2 against live Jev")
    from aeh.judge import decision_request
    from aeh.prov import JevOpenRouterProvider
    from tools.e4_openjev_small.run_gate import sixteen_span_units

    build, quant, _, _ = BACKENDS["openrouter-jev"]
    engine = _engine("openrouter-jev", build, quant)
    provider = JevOpenRouterProvider(retention_answers=lambda b: "zero-retention")
    samples = []
    for unit in sixteen_span_units(int(os.environ.get("PERF_15_UNITS", "200"))):
        started = time.perf_counter()
        provider.decide(decision_request(unit, engine), engine.model)
        samples.append(time.perf_counter() - started)
    samples.sort()
    p95 = samples[max(0, int(0.95 * len(samples)) - 1)]
    print(f"PERF-15 cloud p95 = {p95 * 1000:.0f} ms (target 1000 ms; reported, not gating)")


@pytest.mark.live
def test_perf_16_base_sweep_reported_or_inconclusive() -> None:
    pytest.skip("PERF-16 is a manual E2/E7 measurement over F-JEV-PERF (350 x 6): engine on vs off, "
                "reported, and inconclusive rather than failed above a 40% fallback rate")
