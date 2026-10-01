"""TS-111 (#464): orchestration, aggregation and grade guards. Jev test plan §5 (M-ORCH, M-AGG,
M-GRADE).

| Case | Asserted |
|---|---|
| TC-ORCH-49 | `panel_config_json` with an engine carries exactly the seven-key `decision_engine` object with the canonical threshold; work ids for no engine, 0.80 and 0.85 are pairwise distinct and stable |
| TC-ORCH-50 | The start estimate adds one decision call per seat (10 × 1500 × 0.042e-6 = 0.00063) to the unchanged LLM estimate; a ceiling between the two refuses the start and changes nothing |
| TC-ORCH-51 | The `run_metrics` flush writes the five `decision_*` names with TC-PROV-34's values, and `actual_cost` is the sum of both surfaces (CT-PROV-24; the fix ships here) |
| TC-ORCH-52 | Escalation additions: (A) 1→3 adds arms 2 and 3; (A,B,C) 3→5 adds arms 4 and 5; A never reappears; a random arm shares A's work id |
| TC-ORCH-53 | Engine-on cloud start records the engine in `provider_config` with `retention_verified` including the Jev build; an unconfirmed decision model refuses the run with no row |
| TC-AGG-25 | Two decision verdicts in one panel raise `PanelCorrelationError` (not retryable); every other engine mix aggregates |
| TC-AGG-26 | Metamorphic: relabelling the first verdict `decision` changes neither `CriterionScore` nor `should_escalate`, over 12 fixtures |
| TC-GRADE-26 | Grades from an engine-on run equal an engine-off run's over identical scores; `grade.py` never reads the engine |
"""

from __future__ import annotations

import dataclasses
import itertools
import json
from decimal import Decimal
from pathlib import Path

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.orch import (JUDGE_DECISION_TEMPLATE_V, STAGE_SCORE, Orchestrator, _extension_arms,
                      compute_work_id, panel_config_json)
from tests.support.conf_builders import edge_panel, hosted_cfg
from tests.support.source_tree import module_source

JEV_BUILD = "openrouter/typesafe/jev-1.13@2026-09-17"


def _cloud_engine_config(ceiling: str = "12.50", panel=None, **extra):
    from aeh.conf import ModelRef

    panel = panel or tuple(ModelRef(role="judge", provider="openrouter", build_id=f"openrouter/judge-{i}@2026-01-01",
                                    quantization=None) for i in range(3))
    return resolve_run_config(
        hosted_cfg("cloud-hosted", panel=panel, HARNESS_COST_CEILING=ceiling, HARNESS_DECISION_ENGINE="jev",
                   HARNESS_JEV_BUILD=JEV_BUILD, **extra),
        CohortRef(cohort_id="c-2026-7B-orch", consent_class="synthetic"))


# --- TC-ORCH-49 --------------------------------------------------------------------------------

def test_tc_orch_49_the_engine_joins_the_work_identity() -> None:
    config = _cloud_engine_config()
    at_80 = config.decision_engine
    at_85 = dataclasses.replace(at_80, confidence_threshold=Decimal("0.85"))
    record = json.loads(panel_config_json(config.panel, decision_engine=at_80))
    engine = record["decision_engine"]
    assert set(engine) == {"provider", "build", "threshold", "cite_threshold", "max_citation_questions",
                           "token_bytes_ratio", "template"}
    assert engine["threshold"] == "0.8" and engine["template"] == JUDGE_DECISION_TEMPLATE_V
    assert json.loads(panel_config_json(config.panel, decision_engine=dataclasses.replace(
        at_80, confidence_threshold=Decimal("0.80"))))["decision_engine"]["threshold"] == "0.8"

    def work_id(engine_value):
        return compute_work_id(run_id="R1", stage=STAGE_SCORE, submission_id="S1", criterion_id="C1",
                               judge_id=config.panel[0].build_id, package_version_id="PV1",
                               panel_config=panel_config_json(config.panel, decision_engine=engine_value),
                               prompt_template_version="judge-prompt/2", extractor_version="x")

    ids = [work_id(None), work_id(at_80), work_id(at_85)]
    assert len(set(ids)) == 3 and work_id(at_80) == ids[1]


# --- TC-ORCH-52 --------------------------------------------------------------------------------

def test_tc_orch_52_the_escalation_ladder_never_re_adds_the_seat() -> None:
    assert _extension_arms(("A",), ("A",)) == ("escalation-arm-2", "escalation-arm-3")
    assert _extension_arms(("A", "B", "C"), ("A", "B", "C")) == ("escalation-arm-4", "escalation-arm-5")
    assert "A" not in _extension_arms(("A",), ("A",)) + _extension_arms(("A", "B", "C"), ("A", "B", "C"))
    # A random-arm widening of (A) is A's own unit: `compute_work_id` takes no origin input, so
    # the arm cannot mint a second unit for A (and TC-JUDGE-30 shows origin never makes a seat).
    import inspect

    assert "origin" not in inspect.signature(compute_work_id).parameters


# --- TC-AGG-25 / TC-AGG-26 ---------------------------------------------------------------------

def _labelled(verdicts, engines):
    out = []
    for v, e in zip(verdicts, engines):
        v = dataclasses.replace(v) if dataclasses.is_dataclass(v) else type(v)(**vars(v))
        v.scoring_engine = e
        out.append(v)
    return out


def test_tc_agg_25_two_decision_verdicts_are_one_correlated_opinion() -> None:
    from aeh.agg import PanelCorrelationError, aggregate
    from aeh.prov import ProviderUnavailableError, RateLimitedError, TransportError
    from tests.support.agg_vocabulary import band, criterion, favourable_signals, verdict

    crit = criterion([band("B", 0, 0.0), band("D", 1, 1.0), band("P", 2, 2.0), band("E", 3, 3.0)])
    three = [verdict("P", 2), verdict("P", 2), verdict("D", 1)]
    aggregate(_labelled(three[:1], ["decision"]), crit, favourable_signals())
    aggregate(_labelled(three, ["decision", "llm", "llm"]), crit, favourable_signals())
    aggregate(_labelled(three, ["llm", "llm", "llm"]), crit, favourable_signals())
    with pytest.raises(PanelCorrelationError) as caught:
        aggregate(_labelled(three, ["decision", "decision", "llm"]), crit, favourable_signals())
    assert not isinstance(caught.value, (TransportError, RateLimitedError, ProviderUnavailableError))


def _agg_fixtures():
    from tests.support.agg_vocabulary import band, criterion, favourable_signals, verdict

    four = [band("B", 0, 0.0), band("D", 1, 1.0), band("P", 2, 2.0), band("E", 3, 3.0)]
    patterns = [(2, 2, 2), (1, 2, 3), (0, 0, 3)]
    signals = [favourable_signals(), dataclasses.replace(favourable_signals()) if dataclasses.is_dataclass(
        favourable_signals()) else type(favourable_signals())(**{**vars(favourable_signals()), "spans_verified": False})]
    out = []
    # 3 band patterns × 2 signal sets × cited/uncited = 12, alternating atomic and holistic, so
    # every pattern meets both signal sets (the split panels included).
    for i, (pattern, sig, cited) in enumerate(itertools.product(patterns, signals, (True, False))):
        verdicts = [verdict("BDPE"[o], o, cited=cited) for o in pattern]
        out.append((verdicts, criterion(four, scoring_model=("atomic", "holistic")[i % 2]), sig))
    return out


def test_tc_agg_26_the_engine_label_changes_nothing_downstream() -> None:
    from aeh.agg import aggregate, should_escalate
    from tests.support.agg_vocabulary import criterion_history, expected_distribution

    fixtures = _agg_fixtures()
    assert len(fixtures) == 12
    history, baseline = criterion_history(), expected_distribution()
    for verdicts, crit, sig in fixtures:
        llm = aggregate(_labelled(verdicts, ["llm"] * 3), crit, sig)
        decision = aggregate(_labelled(verdicts, ["decision", "llm", "llm"]), crit, sig)
        assert llm == decision
        assert should_escalate(llm, crit, history, baseline) == should_escalate(decision, crit, history, baseline)


# --- TC-GRADE-26 -------------------------------------------------------------------------------

def test_tc_grade_26_grade_never_reads_the_engine_statically() -> None:
    source = module_source("grade", Path(__file__).resolve().parents[3] / "src" / "aeh")
    for token in ("scoring_engine", "decision_prescreen", "decision_engine"):
        assert token not in source, f"grade.py reads {token}"


@pytest.mark.integration
def test_tc_grade_26_engine_on_and_engine_off_runs_grade_alike(tmp_path) -> None:
    from tests.support.pipe_world import drive_composed, jev_replay_world, replay_world

    def grades(world):
        world.build_run()
        world.start_run()
        drive_composed(world)
        corpus = {sid: world.cohort[i - 1].submission_id for i, sid in world.sid_by_index.items()}
        scores = sorted((corpus[r["submission_id"]], r["criterion_id"], r["band"]) for r in world.handle.query(
            "SELECT submission_id, criterion_id, band FROM criterion_score"))
        rows = []
        for r in world.handle.query("SELECT * FROM submission_grade"):
            row = {k: r[k] for k in r.keys() if k not in ("run_id",) and not k.endswith("_at")}
            row["submission_id"] = corpus[row["submission_id"]]
            rows.append(json.dumps(row, sort_keys=True, default=str))
        rows.sort()
        engines = {r["scoring_engine"] for r in world.handle.query("SELECT scoring_engine FROM verdict")}
        world.store.close()
        return scores, rows, engines

    off_scores, off_grades, off_engines = grades(replay_world(tmp_path / "off"))
    on_scores, on_grades, on_engines = grades(jev_replay_world(tmp_path / "on"))
    assert "decision" in on_engines and off_engines == {"llm"}
    assert on_scores == off_scores, "precondition: identical criterion scores"
    assert on_grades == off_grades


# --- TC-ORCH-50 / TC-ORCH-53 (rung 2) ----------------------------------------------------------

class _Seam:
    """The LLM seam: confirms retention; every unit estimates at 0.01."""

    def verify_retention(self, refs):
        from aeh.prov import RetentionReport
        return RetentionReport(confirmed=tuple(refs), unconfirmed=())

    def estimate_cost(self, unit):
        return Decimal("0.01")


def _cloud_run(tmp_data_dir, config, decision_provider, n=10):
    from aeh.store import open_store
    from tests.support.orch_run import seed_cohort, seed_package
    import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.pkg, aeh.review, aeh.synth  # noqa: F401,E401

    store = open_store(tmp_data_dir)
    cohort = seed_cohort(store, [f"S{i}" for i in range(n)])
    version = seed_package(store, [{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"}])
    orch = Orchestrator(store, provider=_Seam(), decision_provider=decision_provider)
    return store, orch, cohort, version


@pytest.mark.integration
def test_tc_orch_50_decision_calls_join_the_start_estimate(tmp_data_dir) -> None:
    from aeh.conf import ConfigurationError
    from aeh.prov import JevOpenRouterProvider

    decider = JevOpenRouterProvider(api_key="k", retention_answers=lambda b: "zero-retention")
    config = _cloud_engine_config()
    store, orch, cohort, version = _cloud_run(tmp_data_dir, config, decider)
    try:
        run_id = orch.create_run(cohort, version, config)
        orch.enumerate_units(run_id)
        handle = store.cohort(cohort)
        rows = handle.query("SELECT * FROM work_unit WHERE run_id = :r", r=run_id)
        seats = [r for r in rows if r["stage"] == STAGE_SCORE and r["judge_id"] == config.panel[0].build_id]
        assert len(seats) == 10
        e_llm = Decimal("0.01") * len(rows)
        assert orch._decision_cost_estimate(handle, run_id, rows) == Decimal("0.00063")  # 10 x 1500 x 0.042e-6
        assert orch._run_cost_estimate(handle, run_id) == e_llm + Decimal("0.00063")
    finally:
        store.close()
    # A ceiling between E_llm and E_llm + E_dec refuses the start and changes nothing.
    tight = _cloud_engine_config(ceiling=str(e_llm + Decimal("0.0003")))
    store, orch, cohort, version = _cloud_run(tmp_data_dir / "tight", tight, decider)
    try:
        run_id = orch.create_run(cohort, version, tight)
        orch.enumerate_units(run_id)
        with pytest.raises(ConfigurationError):
            orch.start(run_id)
        status = store.cohort(cohort).query("SELECT status FROM run WHERE run_id = :r", r=run_id)[0]["status"]
        leased = store.cohort(cohort).query("SELECT count(*) n FROM work_unit WHERE status != 'pending'")[0]["n"]
        assert status == "pending" and leased == 0
    finally:
        store.close()


@pytest.mark.integration
def test_tc_orch_53_engine_on_start_records_and_verifies_the_decision_model(tmp_data_dir) -> None:
    from aeh.prov import JevOpenRouterProvider, RetentionPolicyError

    config = _cloud_engine_config()
    confirmed = JevOpenRouterProvider(api_key="k", retention_answers=lambda b: "zero-retention")
    store, orch, cohort, version = _cloud_run(tmp_data_dir, config, confirmed)
    try:
        run_id = orch.create_run(cohort, version, config)
        provider_config = json.loads(store.cohort(cohort).query(
            "SELECT provider_config FROM run WHERE run_id = :r", r=run_id)[0]["provider_config"])
        engine = provider_config["decision_engine"]
        assert engine["provider"] == "openrouter-jev" and engine["build"] == JEV_BUILD
        assert engine["template"] == JUDGE_DECISION_TEMPLATE_V
        assert (engine["threshold"], engine["cite_threshold"], engine["max_citation_questions"],
                engine["token_bytes_ratio"]) == ("0.8", "0.5", 16, 3)
        assert JEV_BUILD in provider_config["retention_verified"]
    finally:
        store.close()
    hedged = JevOpenRouterProvider(api_key="k", retention_answers=lambda b: "retention: standard")
    store, orch, cohort, version = _cloud_run(tmp_data_dir / "hedged", config, hedged)
    try:
        with pytest.raises(RetentionPolicyError):
            orch.create_run(cohort, version, config)
        assert store.cohort(cohort).query("SELECT count(*) n FROM run")[0]["n"] == 0
    finally:
        store.close()


# --- TC-ORCH-51 --------------------------------------------------------------------------------

class _CountingDecisions:
    """The replay double plus the CT-PROV-24 counters TC-PROV-34 hand-summed."""

    def __init__(self, inner, **extra):
        from aeh.prov import RunCountersTracker

        self._inner = inner
        # From a fresh snapshot, so a counter added to `DecisionCounters` (design 1.8's
        # `decision_provider_unreported`) needs no change here.
        self.decision_counters = dataclasses.replace(
            RunCountersTracker().decision_snapshot(), decision_calls=3, decision_tokens_in=3600,
            decision_transport_retries=2, decision_rate_limited_calls=1,
            decision_actual_cost=Decimal("0.0001512"), **extra)

    def complete(self, prompt, model_ref, params):
        """The first two LLM answers are billed at 0.01 each (the fixture's own cost is null)."""
        completion = self._inner.complete(prompt, model_ref, params)
        self.billed = getattr(self, "billed", 0)
        if self.billed < 2:
            self.billed += 1
            return dataclasses.replace(completion, cost=Decimal("0.01"))
        return completion

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.mark.integration
def test_tc_orch_51_the_flush_writes_decision_counters_and_sums_actual_cost(tmp_path) -> None:
    from tests.support.pipe_world import drive_composed, jev_replay_world

    world = jev_replay_world(tmp_path / "data")
    try:
        world.build_run()
        world.start_run()
        counting = _CountingDecisions(world.provider)
        world.provider = counting
        drive_composed(world, decision_provider=counting)
        metrics = {r["metric"]: r["value"] for r in world.store.durable().query(
            "SELECT metric, value FROM run_metrics WHERE run_id = :r", r=world.run_id)}
        assert (metrics["decision_calls"], metrics["decision_tokens_in"], metrics["decision_transport_retries"],
                metrics["decision_rate_limited_calls"]) == (3, 3600, 2, 1)
        assert metrics["decision_actual_cost"] == pytest.approx(0.0001512)
        # Two billed LLM answers (0.01 each) plus the decision spend: 0.02 + 0.0001512 (CT-PROV-24).
        assert metrics["actual_cost"] == pytest.approx(0.0201512), "actual_cost sums both surfaces"
    finally:
        world.store.close()


@pytest.mark.integration
def test_tc_orch_51_the_flush_writes_decision_provider_unreported(tmp_path) -> None:
    """Design 1.8 (FR-PROV-43, CT-PROV-24 amended): with a decision provider bound, the flush
    writes `decision_provider_unreported` beside the other decision counters. Engine-off output
    is unchanged because nothing is bound there (TC-REG-08 holds only `decision_prescreen_rows`)."""
    from tests.support.pipe_world import drive_composed, jev_replay_world

    world = jev_replay_world(tmp_path / "data")
    try:
        world.build_run()
        world.start_run()
        counting = _CountingDecisions(world.provider, decision_provider_unreported=2)
        world.provider = counting
        drive_composed(world, decision_provider=counting)
        metrics = {r["metric"]: r["value"] for r in world.store.durable().query(
            "SELECT metric, value FROM run_metrics WHERE run_id = :r", r=world.run_id)}
        assert metrics.get("decision_provider_unreported") == 2
    finally:
        world.store.close()
