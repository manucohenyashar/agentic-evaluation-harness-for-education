"""TS-116 (#469): composition and the `Requires` pairs, Jev. Jev test plan §6 (M-PIPE), §7 (TC-REQ).

| Case | Asserted |
|---|---|
| TC-PIPE-15 | Engine on: `decision_provider_for` builds the provider once, with the engine model, and every `ScoringWorker` receives it and the `RunConfig`; engine off and injected: never called |
| TC-PIPE-16 | A hedged cloud retention answer, and an OpenJev build mismatch, surface from `run_to_completion` before any lease |
| TC-PIPE-17 | The score stage's summary equals `decision_engine_metrics` value for value |
| TC-PIPE-18 | Engine-on trace lines carry the engine suffix grammar; engine-off lines carry none and equal the fb12d1e baseline |
| TC-REQ-104 | The worker consumes Decisions from the double and from a programmed `JevOpenRouterProvider`, touching only `decide` and `decision_capabilities`, never twice |
| TC-REQ-105 | The worker never resolves configuration itself |
| TC-REQ-106 | Levels come from the real catalog in ordinal order, although the six bands were inserted in reverse |
| TC-REQ-107 | An expired lease redelivers the seat and the pre-screen is reused |
| TC-REQ-108 | `decision_provider_for` on each profile's resolved engine model selects that profile's class |
| TC-REQ-109 | `verdicts_for` output, `scoring_engine` included, feeds `aggregate` unmodified |
| TC-REQ-110 | `judge_signals` reads the outcome mix through `decision_engine_metrics`, never from `decision_prescreen` |
| TC-REQ-111 | M-PIPE builds the provider only through `decision_provider_for` and probes before the first lease |
| TC-REQ-112 | A decide outage pauses the run and the trace carries the metrics verbatim |
| TC-REQ-113 | The flush persists the provider's decision counters by name, unmodified |
| TC-REQ-114 | The conformance E1 arm runs on the double with no network and fails loudly on a miss |
| TC-REQ-115 | The engine-off `panel_build_ref` is the pre-delta value; an engine-on run's differs |
| TC-REQ-116 | Grade inputs from the two engine labellings are equal |
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from tests.support import pipe_world
from tests.support.conf_builders import edge_panel

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


def _ts110():
    from tests.integration.judge import test_ts110_decision_dispatch as m
    return m


def _run(world, **overrides):
    world.build_run()
    world.start_run()
    return pipe_world.drive_composed(world, **overrides)


# --- TC-PIPE-15 / TC-REQ-111 -------------------------------------------------------------------

def test_tc_pipe_15_the_provider_is_built_once_and_handed_to_every_worker(tmp_path, monkeypatch) -> None:
    import aeh.judge as judge
    import aeh.prov as prov
    from aeh.pipeline import run_to_completion

    built, workers = [], []
    original_for = prov.decision_provider_for
    monkeypatch.setattr(prov, "decision_provider_for", lambda ref, **k: built.append(ref) or original_for(ref, **k))
    original_init = judge.ScoringWorker.__init__

    def init(self, *a, **k):
        workers.append((k.get("decision_provider"), k.get("run_config")))
        original_init(self, *a, **k)

    monkeypatch.setattr(judge.ScoringWorker, "__init__", init)
    world = pipe_world.jev_replay_world(tmp_path / "on")
    try:
        world.build_run()
        world.start_run()
        result = run_to_completion(world.store, world.run_id,
                                   provider=prov.RecordedFixtureProvider(fixture_dir=pipe_world.jev_decisions_dir()),
                                   run_config=world.resolved, **pipe_world.corpus_refs())
        assert result.status == "complete"
        assert built == [world.resolved.decision_engine.model]
        seat_workers = [w for w in workers if w[1] is not None]
        assert seat_workers and all(dp is not None and rc is world.resolved for dp, rc in seat_workers)
    finally:
        world.store.close()
    built.clear()
    off = pipe_world.replay_world(tmp_path / "off")
    try:
        _run(off)
        assert built == []
    finally:
        off.store.close()
    injected = pipe_world.jev_replay_world(tmp_path / "inj")
    try:
        _run(injected)  # drive_composed injects the world's own provider as the decision provider
        assert built == []
    finally:
        injected.store.close()


# --- TC-PIPE-16 --------------------------------------------------------------------------------

def test_tc_pipe_16_start_checks_fail_before_any_lease(tmp_path) -> None:
    from aeh.conf import CohortRef, resolve_run_config
    from aeh.pipeline import run_to_completion
    from aeh.prov import BuildChangedError, HttpResponse, JevOpenRouterProvider, OpenJevLocalProvider, RetentionPolicyError
    from tests.support.conf_builders import edge_cfg, hosted_cfg

    world = pipe_world.replay_world(tmp_path / "d")
    try:
        world.build_run()
        world.start_run()
        leased_before = world.handle.query("SELECT count(*) n FROM work_unit WHERE status != 'pending'")[0]["n"]
        replays_before = world.provider.replayed_calls
        cloud = resolve_run_config(hosted_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev",
                                              HARNESS_JEV_BUILD="openrouter/typesafe/jev-1.13@2026-09-17"),
                                   CohortRef(cohort_id=world.cohort_id, consent_class="synthetic"))
        hedged = JevOpenRouterProvider(api_key="k", retention_answers=lambda b: "retention: standard")
        with pytest.raises(RetentionPolicyError):
            run_to_completion(world.store, world.run_id, provider=world.provider, run_config=cloud,
                              decision_provider=hedged, **pipe_world.corpus_refs())

        class _Models:
            def send(self, request):  # noqa: ANN001
                return HttpResponse(200, {}, json.dumps({"data": [{"id": "openjev", "root": "/models/other"}]}).encode())

        edge = resolve_run_config(edge_cfg(panel=world.resolved.panel, HARNESS_DECISION_ENGINE="jev",
                                           HARNESS_JEV_BUILD="/models/openjev-FP8/model.safetensors@sha256:" + "ab" * 32,
                                           HARNESS_JEV_QUANTIZATION="fp8"),
                                  CohortRef(cohort_id=world.cohort_id, consent_class="synthetic"))
        with pytest.raises(BuildChangedError):
            run_to_completion(world.store, world.run_id, provider=world.provider, run_config=edge,
                              decision_provider=OpenJevLocalProvider(transport=_Models()), **pipe_world.corpus_refs())
        leased_after = world.handle.query("SELECT count(*) n FROM work_unit WHERE status != 'pending'")[0]["n"]
        assert leased_after == leased_before and world.provider.replayed_calls == replays_before
    finally:
        world.store.close()


# --- TC-PIPE-17 / TC-PIPE-18 / TC-REQ-112 ------------------------------------------------------

@pytest.fixture(scope="module")
def engine_on(tmp_path_factory):
    world = pipe_world.jev_replay_world(tmp_path_factory.mktemp("ts116-on"))
    result = _run(world)
    yield world, result
    world.store.close()


def test_tc_pipe_17_the_summary_equals_the_metrics(engine_on) -> None:
    from aeh.judge import decision_engine_metrics

    world, result = engine_on
    summary = next(s for s in result.stages if getattr(s, "metrics", None)).metrics
    m = decision_engine_metrics(world.handle, world.run_id)
    for name, value in summary.items():
        expected = getattr(m, name)
        assert value == (dict(expected) if isinstance(value, dict) else expected), name


_SUFFIX = re.compile(r"^\S+/\S+ by \S+: \S+ \[(decision|llm; prescreen=(accepted|below_gate|ineligible|rejected|malformed)|llm)\]$")


def test_tc_pipe_18_trace_suffixes_on_and_none_off(engine_on, tmp_path) -> None:
    world, result = engine_on
    judged = [line for s in result.stages if s.stage == "score" for line in s.detail if " by " in line]
    assert judged and all(_SUFFIX.match(line) for line in judged), [l for l in judged if not _SUFFIX.match(l)][:3]
    seat = world.resolved.panel[0].build_id
    seat_lines = [line for line in judged if f" by {seat}:" in line]
    assert seat_lines and all(line.endswith("[decision]") or "[llm; prescreen=" in line for line in seat_lines), \
        "a seat line always names its engine or its pre-screen outcome, never a bare [llm]"
    assert all(line.endswith("[llm]") for line in judged if f" by {seat}:" not in line)
    golden = json.loads((ROOT / "tests" / "regression" / "baselines" / "jev_engine_off.json").read_text(encoding="utf-8"))
    off = pipe_world.replay_world(tmp_path / "off")
    try:
        off_result = _run(off)
        off_lines = sorted(line for s in off_result.stages for line in s.detail)
        assert not [line for line in off_lines if line.endswith("]")]
        assert off_lines == sorted(line for stage in golden["trace"] for line in stage[4])
    finally:
        off.store.close()


def test_tc_req_112_a_decide_outage_pauses_the_run(tmp_path) -> None:
    from aeh.prov import ProviderUnavailableError

    class _Down:
        def __init__(self, inner):
            self._inner = inner

        def decide(self, request, model_ref):
            raise ProviderUnavailableError("decision engine down")

        def __getattr__(self, name):
            return getattr(self._inner, name)

    world = pipe_world.jev_replay_world(tmp_path / "d")
    try:
        result = _run(world, decision_provider=_Down(world.provider))
        assert result.status == "paused" and "ProviderUnavailableError" in (result.pause_reason or "")
        assert world.handle.query("SELECT count(*) n FROM work_unit WHERE status = 'quarantined'")[0]["n"] == 0
    finally:
        world.store.close()


# --- TC-REQ-104 / 105 / 106 / 107 --------------------------------------------------------------

def test_tc_req_104_the_worker_uses_only_decide_and_capabilities(tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker
    from aeh.prov import HttpResponse, JevOpenRouterProvider

    m = _ts110()
    store, provider, world, units = m._world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = m._seat_unit(units, refs)
        request = m._record_llm(provider, store, unit, refs[0], world)

        class _Answering:
            """Answers each decide body with an accepted decision over its own question keys."""

            def __init__(self):
                self.sends = 0

            def send(self, http):  # noqa: ANN001
                self.sends += 1
                questions = json.loads(http.body)["questions"]
                answers = {}
                for key, q in questions.items():
                    if q["type"] == "score":
                        n = len(q["criteria"])
                        probs = {str(i): (0.94 if i == 2 else round(0.06 / (n - 1), 6)) for i in range(n)}
                        probs["2"] = round(1 - sum(v for k, v in probs.items() if k != "2"), 6)
                        answers[key] = {"type": "score", "score": 2.0, "probabilities": probs,
                                        "legend": {str(i): lvl for i, lvl in enumerate(q["criteria"])},
                                        "confidence": (n * probs["2"] - 1) / (n - 1)}
                    else:
                        answers[key] = {"type": "noul", "noul": 0.97}
                return HttpResponse(200, {}, json.dumps({"model": "typesafe/jev-1.13", "answers": answers,
                                                         "usage": {"input_tokens": 10, "output_tokens": 0}}).encode())

        class _Recorder:
            def __init__(self, inner):
                self._inner = inner
                self.used = []

            def __getattr__(self, name):
                self.used.append(name)
                return getattr(self._inner, name)

        transport = _Answering()
        live = _Recorder(JevOpenRouterProvider(api_key="k", transport=transport))
        result = ScoringWorker(store, provider, refs[0], decision_provider=live,
                               run_config=m._engine_config(tmp_data_dir)).dispatch(request, refs[0])
        assert result.scoring_engine == "decision" and transport.sends == 1
        assert set(live.used) <= {"decide", "decision_capabilities"}
    finally:
        store.close()


def test_tc_req_105_the_worker_never_resolves_configuration(tmp_data_dir, make_fixture_provider, monkeypatch) -> None:
    import aeh.conf as conf
    from aeh.judge import ScoringWorker

    m = _ts110()
    store, provider, world, units = m._world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = m._seat_unit(units, refs)
        request = m._record_llm(provider, store, unit, refs[0], world)
        config = m._engine_config(tmp_data_dir)
        monkeypatch.setattr(conf, "resolve_run_config", lambda *a, **k: pytest.fail("the worker resolved configuration"))
        monkeypatch.setenv("HARNESS_JEV_CONFIDENCE_THRESHOLD", "0.99")
        result = ScoringWorker(store, provider, refs[0], decision_provider=m._Decider(m._accepted),
                               run_config=config).dispatch(request, refs[0])
        assert result.scoring_engine == "decision", "the frozen 0.80 decided, not the environment's 0.99"
    finally:
        store.close()


def test_tc_req_106_levels_follow_ordinals_not_insertion_order(tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker, decision_request

    m = _ts110()
    six = (("absent", 0.0, "a"), ("minimal", 1.0, "b"), ("emerging", 2.0, "c"),
           ("developing", 3.0, "d"), ("secure", 4.0, "e"), ("comprehensive", 5.0, "f"))
    m_bands, m_crit = m.C4, m.C4_CRITERIA
    try:
        m.C4, m.C4_CRITERIA = six, ({**m.C4_CRITERIA[0], "band_count": 6},)
        store, provider, world, units = m._world(tmp_data_dir, make_fixture_provider)
    finally:
        m.C4, m.C4_CRITERIA = m_bands, m_crit
    try:
        package = store.package("pkg-orch")
        rows = [dict(zip(r.keys(), tuple(r))) for r in package.query("SELECT * FROM band WHERE criterion_id = 'C1'")]
        assert len(rows) == 6
        with package.transaction() as tx:
            tx.execute("DELETE FROM band WHERE criterion_id = 'C1'")
            for row in sorted(rows, key=lambda r: -r["ordinal"]):  # reinsert, highest ordinal first
                cols = ", ".join(row)
                tx.execute(f"INSERT INTO band ({cols}) VALUES ({', '.join(':' + c for c in row)})", **row)
        refs = edge_panel(3)
        request = ScoringWorker(store, provider, refs[0]).assemble(m._seat_unit(units, refs))
        levels = decision_request(request, m._engine_config(tmp_data_dir).decision_engine).questions[0].levels
        assert [lvl.split(":")[0] for lvl in levels] == [b for b, _, _ in six]
    finally:
        store.close()


def test_tc_req_107_an_expired_lease_redelivers_and_reuses_the_prescreen(tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker
    from aeh.orch import STAGE_SCORE

    m = _ts110()
    store, provider, world, units = m._world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = m._seat_unit(units, refs)
        request = m._record_llm(provider, store, unit, refs[0], world)
        config = m._engine_config(tmp_data_dir)
        first = m._Decider(m._accepted)
        ScoringWorker(store, provider, refs[0], decision_provider=first, run_config=config).dispatch(request, refs[0])
        world["orchestrator"].fail(unit.work_id, "worker lost before persist")  # the lease is released
        redelivered = [u for u in world["orchestrator"].lease("w-judge-redeliver", STAGE_SCORE, 64)
                       if u.work_id == unit.work_id]
        assert redelivered, "the seat came back"
        again = m._Decider(m._accepted)
        ScoringWorker(store, provider, refs[0], decision_provider=again, run_config=config).dispatch(
            ScoringWorker(store, provider, refs[0]).assemble(redelivered[0]), refs[0])
        assert (first.calls, again.calls) == (1, 0)
    finally:
        store.close()


# --- TC-REQ-108 --------------------------------------------------------------------------------

def test_tc_req_108_the_profile_selects_the_class(tmp_path) -> None:
    from aeh.conf import CohortRef, resolve_run_config
    from aeh.prov import JevOpenRouterProvider, OpenJevLocalProvider, decision_provider_for
    from tests.support.conf_builders import edge_cfg, hosted_cfg

    cohort = CohortRef("c", "synthetic")
    cases = {
        "edge-local": (edge_cfg(HARNESS_DECISION_ENGINE="jev", HARNESS_JEV_QUANTIZATION="fp8",
                                HARNESS_JEV_BUILD="/models/openjev-FP8/model.safetensors@sha256:ab"), OpenJevLocalProvider),
        "cloud-hosted": (hosted_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev",
                                    HARNESS_JEV_BUILD="openrouter/typesafe/jev-1.13@2026-09-17"), JevOpenRouterProvider),
        "dev-ci": (hosted_cfg("dev-ci", HARNESS_DECISION_ENGINE="jev",
                              HARNESS_JEV_BUILD="openrouter/typesafe/jev-1.13@2026-09-17"), JevOpenRouterProvider),
    }
    for profile, (cfg, cls) in cases.items():
        model = resolve_run_config(cfg, cohort).decision_engine.model
        assert type(decision_provider_for(model, **({"api_key": "k"} if cls is JevOpenRouterProvider else {}))) is cls


# --- TC-REQ-109 / 110 --------------------------------------------------------------------------

def test_tc_req_109_verdicts_for_feeds_aggregate_unmodified(engine_on) -> None:
    from aeh.agg import aggregate
    from aeh.judge import verdicts_for
    from tests.support.agg_vocabulary import band, criterion, favourable_signals
    from harness.corpora import dev_pipe

    world, _ = engine_on
    decision_cells = world.handle.query(
        "SELECT DISTINCT w.submission_id, w.criterion_id FROM verdict v JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE v.scoring_engine = 'decision'")
    assert decision_cells
    for cell in decision_cells:
        stored = verdicts_for(world.handle, world.run_id, cell["submission_id"], cell["criterion_id"])
        assert {v.scoring_engine for v in stored} >= {"decision"}
        crit = criterion([band(b.band, b.ordinal, b.points) for b in dev_pipe.BY_ID[cell["criterion_id"]].bands])
        # The whole stored panel, exactly as `verdicts_for` returns it.
        score = aggregate(list(stored), crit, favourable_signals())
        persisted = world.handle.query(
            "SELECT band FROM criterion_score WHERE run_id = :r AND submission_id = :s AND criterion_id = :c",
            r=world.run_id, s=cell["submission_id"], c=cell["criterion_id"])
        assert persisted and score.band == persisted[0]["band"]


def test_tc_req_110_judge_signals_reads_the_mix_through_the_metrics(engine_on, monkeypatch) -> None:
    import aeh.judge as judge
    import aeh.stats as stats

    source = Path(stats.__file__).read_text(encoding="utf-8")
    body = source[source.index("def judge_signals"):]
    body = body[:body.index("\ndef ", 1)]
    assert "FROM decision_prescreen" not in body and "decision_prescreen p" not in body
    calls = []
    original = judge.decision_engine_metrics
    monkeypatch.setattr(judge, "decision_engine_metrics", lambda *a, **k: calls.append(1) or original(*a, **k))
    world, _ = engine_on
    signals = stats.judge_signals(world.handle, world.run_id, durable=world.store.durable())
    assert calls and getattr(signals, "decision_outcomes", None) is not None


# --- TC-REQ-113 / 114 / 115 / 116 --------------------------------------------------------------

def test_tc_req_113_the_flush_persists_counters_unmodified(tmp_path) -> None:
    from tests.integration.orch.test_ts111_orch_agg_grade import test_tc_orch_51_the_flush_writes_decision_counters_and_sums_actual_cost

    test_tc_orch_51_the_flush_writes_decision_counters_and_sums_actual_cost(tmp_path)


def test_tc_req_114_conformance_e1_is_hermetic_and_loud(tmp_path, network_guard) -> None:
    from aeh import conform
    from aeh.conf import DecisionEngine, ModelRef
    from aeh.prov import FixtureMissingError, RecordedFixtureProvider
    from tests.support import jev_corpora

    engine = DecisionEngine(model=ModelRef(role="decision", provider="openjev",
                                           build_id="/models/openjev-FP8/model.safetensors@sha256:" + "ab" * 32,
                                           quantization="fp8"),
                            confidence_threshold=Decimal("0.80"), cite_threshold=Decimal("0.50"),
                            max_citation_questions=16, token_bytes_ratio=3)
    jev_corpora.record_f_jev(tmp_path / "rec", "edge", engine)
    report = conform.run_decision_conformance({"openjev": (RecordedFixtureProvider(fixture_dir=tmp_path / "rec"), engine,
                                                           "edge-local")})
    assert report.per_backend["openjev"]["cells"] == 40
    with pytest.raises(FixtureMissingError):
        conform.run_decision_conformance({"openjev": (RecordedFixtureProvider(fixture_dir=tmp_path / "empty"), engine,
                                                      "edge-local")})
    network_guard.assert_no_network()


def test_tc_req_115_the_engine_off_build_ref_is_the_pre_delta_value(engine_on, tmp_path) -> None:
    from aeh.conf import compute_panel_build_ref

    golden = json.loads((ROOT / "tests" / "regression" / "baselines" / "jev_engine_off.json").read_text(encoding="utf-8"))
    off_summary = json.loads(golden["profile_summary"])
    world, _ = engine_on
    off_ref = compute_panel_build_ref(world.resolved.panel)
    assert off_ref == off_summary["panel_build_ref"]
    assert world.resolved.panel_build_ref != off_ref, "an engine-on run is scoped separately"


def test_tc_req_116_grade_inputs_from_both_labellings_are_equal() -> None:
    from aeh.agg import aggregate
    from tests.support.agg_vocabulary import band, criterion, favourable_signals, verdict

    crit = criterion([band("B", 0, 0.0), band("D", 1, 1.0), band("P", 2, 2.0), band("E", 3, 3.0)])
    scores = []
    for engines in (["llm", "llm", "llm"], ["decision", "llm", "llm"]):
        panel = [verdict(b, o) for b, o in (("P", 2), ("P", 2), ("D", 1))]
        for v, e in zip(panel, engines):
            v.scoring_engine = e
        scores.append(aggregate(panel, crit, favourable_signals()))
    assert (scores[0].band, scores[0].points) == (scores[1].band, scores[1].points)
    assert scores[0] == scores[1]


def test_tc_req_111_the_probe_precedes_the_first_lease(tmp_path, monkeypatch) -> None:
    import aeh.orch as orch
    from aeh.conf import CohortRef, resolve_run_config
    from aeh.pipeline import run_to_completion
    from aeh.prov import ProviderUnavailableError
    from tests.support.conf_builders import edge_cfg

    events = []
    original_lease = orch.Orchestrator.lease
    monkeypatch.setattr(orch.Orchestrator, "lease", lambda self, *a, **k: events.append("lease") or original_lease(self, *a, **k))

    class _Probed:
        def verify_build(self, model_ref):
            events.append("probe")
            return model_ref.build_id

        def decision_capabilities(self, model_ref):
            from aeh.prov import DecisionCapabilities
            return DecisionCapabilities(32000, 255, 64, None, True)

        def decide(self, request, model_ref):
            raise ProviderUnavailableError("stop after the first seat")

    world = pipe_world.replay_world(tmp_path / "d")
    try:
        world.build_run()
        world.start_run()
        events.clear()
        edge = resolve_run_config(edge_cfg(panel=world.resolved.panel, HARNESS_DECISION_ENGINE="jev",
                                           HARNESS_JEV_BUILD="/models/openjev-FP8/model.safetensors@sha256:" + "ab" * 32,
                                           HARNESS_JEV_QUANTIZATION="fp8"),
                                  CohortRef(cohort_id=world.cohort_id, consent_class="synthetic"))
        run_to_completion(world.store, world.run_id, provider=world.provider, run_config=edge,
                          decision_provider=_Probed(), **pipe_world.corpus_refs())
        assert events and events[0] == "probe" and "lease" in events
    finally:
        world.store.close()
