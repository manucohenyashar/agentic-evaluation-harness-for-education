"""TS-115 (#468): the downstream decision-engine clauses. Jev test plan §6.11.4.

| Case | Clause | Asserted |
|---|---|---|
| TC-ORCH-C29 | data | The ladder never re-adds an arm, and over TC-E2E-05's run (F-JEV-SYNTH) no cell holds two units naming one judge |
| TC-ORCH-C30 | behaviour | Engine-off `panel_config` / persisted `provider_config` equal the fb12d1e goldens |
| TC-AGG-C22 | error | Two decision verdicts fault the aggregation (`PanelCorrelationError`), never a quiet dedupe (rung 0; ADV-16 carries rung 3 in TS-117) |
| TC-AGG-C23 | behaviour | Metamorphic over random panels: the engine label never changes `aggregate` or `should_escalate` |
| TC-GRADE-C21 | behaviour | `grade.py` never reads the engine; an engine-on and an engine-off run grade alike |
| TC-STATS-C24 | data | Every figure per engine partition, unpooled; below-minimum partitions and bins report `insufficient_data`, never a number |
| TC-PIPE-C08 | observe | The score stage carries the decision summary under CT-JUDGE-28's names |
| TC-PIPE-C09 | behaviour | An engine-off run constructs no decision provider |
| TC-CONFORM-C15 | observe | The decision conformance report names the four figures for every backend |
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from pathlib import Path

import pytest
from tests.support.source_tree import module_source

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]


# --- TC-ORCH-C29 / C30 -------------------------------------------------------------------------

@pytest.mark.integration
def test_tc_orch_c29_no_cell_ever_holds_two_units_for_one_judge(tmp_path) -> None:
    from aeh.orch import _extension_arms
    from tests.support import pipe_world

    assert _extension_arms(("A",), ("A",)) == ("escalation-arm-2", "escalation-arm-3")
    world = pipe_world.jev_synth_replay_world(tmp_path / "d")
    try:
        world.build_run()
        world.start_run()
        pipe_world.drive_composed(world)
        duplicates = world.handle.query(
            "SELECT submission_id, criterion_id, judge_id, count(*) n FROM work_unit WHERE stage = 'score' "
            "GROUP BY 1, 2, 3 HAVING count(*) > 1")
        assert duplicates == []
        widened = world.handle.query(
            "SELECT count(DISTINCT judge_id) n FROM work_unit WHERE stage = 'score' GROUP BY submission_id, criterion_id")
        assert max(r["n"] for r in widened) == 3, "the panel of one widened to three distinct arms"
    finally:
        world.store.close()


def test_tc_orch_c30_engine_off_serialization_is_unchanged() -> None:
    from aeh.conf import CohortRef
    from tests.regression.jev_engine_off_capture import _serialization, serialization_configs

    golden = json.loads((ROOT / "tests" / "regression" / "baselines" / "jev_engine_off.json").read_text(
        encoding="utf-8"))["serialization"]
    for name, cfg in serialization_configs().items():
        now = _serialization(cfg, CohortRef(cohort_id="coh-dev-pipe", consent_class="synthetic"))
        assert (now["panel_config_json"], now["persisted"]) == (golden[name]["panel_config_json"], golden[name]["persisted"])


# --- TC-AGG-C22 / C23 --------------------------------------------------------------------------

def _crit():
    from tests.support.agg_vocabulary import band, criterion

    return criterion([band("B", 0, 0.0), band("D", 1, 1.0), band("P", 2, 2.0), band("E", 3, 3.0)])


def _v(name, ordinal, engine, **kw):
    from tests.support.agg_vocabulary import verdict

    v = verdict(name, ordinal, **kw)
    v.scoring_engine = engine
    return v


def test_tc_agg_c22_two_decision_verdicts_fault_the_aggregation() -> None:
    """Adversarial construction: a silent dedupe of the second decision verdict would aggregate a
    quietly shrunk panel here instead of raising."""
    from aeh.agg import PanelCorrelationError, aggregate
    from tests.support.agg_vocabulary import favourable_signals

    with pytest.raises(PanelCorrelationError):
        aggregate([_v("P", 2, "decision"), _v("P", 2, "decision"), _v("D", 1, "llm")], _crit(), favourable_signals())
    with pytest.raises(PanelCorrelationError):
        aggregate([_v("E", 3, "llm"), _v("P", 2, "decision"), _v("E", 3, "decision")], _crit(), favourable_signals())


try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
except ImportError:  # pragma: no cover
    given = None

if given is not None:
    @pytest.mark.property
    @settings(max_examples=150, deadline=None)
    @given(st.sampled_from([1, 3, 5]).flatmap(lambda n: st.lists(st.integers(0, 3), min_size=n, max_size=n)),
           st.booleans(), st.sampled_from(["atomic", "holistic"]))
    def test_tc_agg_c23_the_engine_label_never_changes_aggregation(ordinals, cited, model) -> None:
        from aeh.agg import aggregate, should_escalate
        from tests.support.agg_vocabulary import (band, criterion, criterion_history, expected_distribution,
                                                  favourable_signals)

        crit = criterion([band("B", 0, 0.0), band("D", 1, 1.0), band("P", 2, 2.0), band("E", 3, 3.0)],
                         scoring_model=model)
        llm = [_v("BDPE"[o], o, "llm", cited=cited) for o in ordinals]
        labelled = [_v("BDPE"[o], o, "decision" if i == 0 else "llm", cited=cited) for i, o in enumerate(ordinals)]
        a, b = aggregate(llm, crit, favourable_signals()), aggregate(labelled, crit, favourable_signals())
        assert a == b
        assert should_escalate(a, crit, criterion_history(), expected_distribution()) == \
            should_escalate(b, crit, criterion_history(), expected_distribution())


# --- TC-GRADE-C21 ------------------------------------------------------------------------------

def test_tc_grade_c21_grade_never_reads_the_engine() -> None:
    source = module_source("grade", ROOT / "src" / "aeh")
    assert not [t for t in ("scoring_engine", "decision_prescreen", "decision_engine") if t in source]


@pytest.mark.integration
def test_tc_grade_c21_engine_on_and_off_runs_grade_alike(tmp_path) -> None:
    """Adversarial construction: a "decision-scored criteria count as provisional" branch in the
    grade computation makes these two runs' grades differ."""
    from tests.integration.orch.test_ts111_orch_agg_grade import test_tc_grade_26_engine_on_and_engine_off_runs_grade_alike

    test_tc_grade_26_engine_on_and_engine_off_runs_grade_alike(tmp_path)


# --- TC-STATS-C24 ------------------------------------------------------------------------------

def test_tc_stats_c24_per_engine_figures_unpooled_and_honest_below_minimum() -> None:
    from aeh.stats import agreement_by_engine, decision_gate_calibration
    from tests.support import jev_corpora

    v1 = [label for label in jev_corpora.stats_labels() if label.package_version == "1"]
    by_engine = agreement_by_engine(v1, jev_corpora.partition_of)
    assert set(by_engine) == {"decision", "llm_fallback", "llm_engine_off"}
    alphas = [by_engine[p].ordinal_alpha for p in ("decision", "llm_fallback", "llm_engine_off")]
    assert None not in alphas and len(set(alphas)) == 3, "three partitions, three figures: not pooled"
    v2 = agreement_by_engine(jev_corpora.stats_labels("D59"), jev_corpora.partition_of)
    assert v2["decision"].insufficient_data and v2["decision"].ordinal_alpha is None
    records = [(l.band_confidence, l.system_band, l.teacher_band) for l in jev_corpora.stats_labels("D60")]
    bins = decision_gate_calibration(records).bins
    assert bins[1].insufficient_data and bins[1].exact_agreement is None and bins[1].n == 19


# --- TC-PIPE-C08 / C09 -------------------------------------------------------------------------

@pytest.mark.integration
def test_tc_pipe_c08_the_score_stage_carries_the_decision_summary(tmp_path) -> None:
    from tests.support import pipe_world

    world = pipe_world.jev_replay_world(tmp_path / "d")
    try:
        world.build_run()
        world.start_run()
        result = pipe_world.drive_composed(world)
        summary = next(s for s in result.stages if s.stage == "score" and getattr(s, "metrics", None))
        assert set(summary.metrics) == {
            "decision_prescreens", "decision_accepted", "decision_below_gate", "decision_ineligible",
            "decision_ineligible_reasons", "decision_rejected", "decision_malformed", "decision_accepted_rate",
            "decision_fallback_rate", "decision_latency_p50_ms", "decision_latency_p95_ms",
            "decision_fallback_rate_high", "decision_requests_rejected"}
    finally:
        world.store.close()


@pytest.mark.integration
def test_tc_pipe_c09_an_engine_off_run_constructs_no_decision_provider(tmp_path, monkeypatch) -> None:
    import aeh.prov as prov
    from tests.support import pipe_world

    constructed = []
    original = prov.decision_provider_for
    monkeypatch.setattr(prov, "decision_provider_for", lambda *a, **k: constructed.append(a) or original(*a, **k))
    world = pipe_world.replay_world(tmp_path / "d")
    try:
        world.build_run()
        world.start_run()
        result = pipe_world.drive_composed(world)
        assert result.status == "complete" and constructed == []
        assert not [s for s in result.stages if getattr(s, "metrics", None)]
    finally:
        world.store.close()


# --- TC-CONFORM-C15 ----------------------------------------------------------------------------

def test_tc_conform_c15_the_report_names_the_four_figures(tmp_path) -> None:
    from aeh import conform
    from aeh.conf import DecisionEngine, ModelRef
    from aeh.prov import RecordedFixtureProvider
    from tests.support import jev_corpora

    def engine(provider, build, quant):
        return DecisionEngine(model=ModelRef(role="decision", provider=provider, build_id=build, quantization=quant),
                              confidence_threshold=Decimal("0.80"), cite_threshold=Decimal("0.50"),
                              max_citation_questions=16, token_bytes_ratio=3)

    backends = {}
    for name, build, quant, corpus_backend, profile in (
            ("openrouter-jev", "openrouter/typesafe/jev-1.13@2026-09-17", None, "cloud", "cloud-hosted"),
            ("openjev", "/models/openjev-FP8/model.safetensors@sha256:" + "ab" * 32, "fp8", "edge", "edge-local")):
        e = engine(name, build, quant)
        jev_corpora.record_f_jev(tmp_path / name, corpus_backend, e)
        backends[name] = (RecordedFixtureProvider(fixture_dir=tmp_path / name), e, profile)
    report = conform.run_decision_conformance(backends)
    for figures in report.per_backend.values():
        assert set(conform.DECISION_REPORT_KEYS) <= set(figures)
    assert set(conform.DECISION_REPORT_KEYS) == {"decision_accepted_rate", "decision_band_exact_agreement",
                                                 "decision_band_adjacent_agreement", "decision_llm_median_divergence"}
