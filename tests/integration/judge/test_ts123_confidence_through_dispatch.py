"""TS-123 (#499): Jev's own confidence, end to end through `ScoringWorker.dispatch` (design 1.8).
Jev test plan §5.8 and §6.11.6.

Every arm answers the decision seat from the real `RecordedFixtureProvider`, holding raw §1.2
documents, so the confidence the gate sees is the one the provider's parser produced. Stubbing a
`Decision` here would skip exactly the rule under test.

| Case | Asserted |
|---|---|
| TC-JUDGE-C22 (rung-2 arm) | Reported band 0.96 with P(sufficient) 0.85 → a decision verdict, `evidence_sufficient`, prescreen gate 0.85, and the same verdict on redelivery from the stored row; P(sufficient) 0.05 → an LLM verdict whose request is engine-off's, prescreen `below_gate` at 0.05 |
| TC-REQ-117 | CT-PROV-19 → M-JUDGE: a Score without Jev's confidence makes one `decide` call, a `malformed` prescreen and an LLM verdict with the engine-off request |
| TC-REQ-118 | CT-PROV-19 → M-STATS: the stored `band_confidence` is Jev's reported value, so the calibration bins place 0.83 and 0.87 in [0.80, 0.85) and [0.85, 0.90), where the probabilities alone would derive 0.20 |
"""

from __future__ import annotations

import json

import pytest

from aeh.judge import ScoringWorker, decision_engine_metrics, decision_request
from aeh.prov import NoulQuestion, RecordedFixtureProvider, ScoreQuestion, decision_request_key
from tests.support.conf_builders import edge_panel
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = pytest.mark.integration


def _ts110():
    from tests.integration.judge import test_ts110_decision_dispatch as m
    return m


class _CountingDecider:
    """The real fixture double, counting `decide` calls."""

    def __init__(self, inner: RecordedFixtureProvider) -> None:
        self.inner = inner
        self.calls = 0

    def decision_capabilities(self, model_ref):  # noqa: ANN001
        return self.inner.decision_capabilities(model_ref)

    def decide(self, request, model_ref):  # noqa: ANN001
        self.calls += 1
        return self.inner.decide(request, model_ref)


def _document(request, *, probs, confidence, p_suff):
    """A raw §1.2 response for `request`. `confidence=...` omits the Score's key."""
    answers = {}
    for q in request.questions:
        if isinstance(q, ScoreQuestion):
            answers[q.key] = {"type": "score", "score": sum(i * p for i, p in enumerate(probs)),
                              "probabilities": {str(i): p for i, p in enumerate(probs)},
                              "legend": {str(i): lvl for i, lvl in enumerate(q.levels)}}
            if confidence is not ...:
                answers[q.key]["confidence"] = confidence
        elif isinstance(q, NoulQuestion) and q.key == "evidence_sufficient":
            answers[q.key] = {"type": "noul", "noul": p_suff}
        else:
            answers[q.key] = {"type": "noul", "noul": 0.9}
    return {"model": "jev-fixture", "answers": answers, "usage": {"input_tokens": 50, "output_tokens": 0}}


def _decider_for(tmp_path, scoring_request, run_config, document) -> _CountingDecider:
    """Records a well-formed twin, then plants `document` behind the double's back, so the
    answer reaching the gate is whatever the double's `decide` makes of the raw body."""
    engine = run_config.decision_engine
    request = decision_request(scoring_request, engine)
    fixture = RecordedFixtureProvider(fixture_dir=tmp_path)
    fixture.record_decision(request, engine.model, _document(request, probs=[.01, .01, .97, .01],
                                                             confidence=0.96, p_suff=0.97))
    path = fixture._path_for(decision_request_key(request, engine.model))
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["response"] = document(request)
    path.write_text(json.dumps(stored), encoding="utf-8")
    return _CountingDecider(fixture)


def _prescreen(store, work_id):
    rows = store.cohort(ORCH_COHORT_ID).query(
        "SELECT outcome, reason, gate_confidence, band_confidence, sufficiency_p FROM decision_prescreen "
        "WHERE work_id = :w", w=work_id)
    assert len(rows) == 1
    return rows[0]


# --- TC-JUDGE-C22 (rung-2 arm) -----------------------------------------------------------------

@pytest.mark.writtenahead
@pytest.mark.parametrize("p_suff, engine, gate", [(0.85, "decision", 0.85), (0.05, "llm", 0.05)],
                         ids=["looser-0.85-accepted", "stricter-0.05-falls-back"])
def test_tc_judge_c22_the_sufficiency_gate_is_p_through_dispatch(p_suff, engine, gate, tmp_data_dir,
                                                                 make_fixture_provider, tmp_path) -> None:
    """Design 1.8: `c_s` is P(sufficient) itself. Arm (i) accepts where 1.6's `|2·0.85 − 1| =
    0.70` fell back; arm (ii) falls back where `|2·0.05 − 1| = 0.90` accepted a verdict with
    `evidence_sufficient = False`. A gate or prescreen writer that recomputes `|2p − 1|` turns
    either arm red."""
    m = _ts110()
    store, provider, world, units = m._world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = m._seat_unit(units, refs)
        request = m._record_llm(provider, store, unit, refs[0], world)
        config = m._engine_config(tmp_data_dir)
        decider = _decider_for(tmp_path, request, config, lambda r: _document(
            r, probs=[.01, .01, .97, .01], confidence=0.96, p_suff=p_suff))
        off, on = m._LLMSpy(provider), m._LLMSpy(provider)
        result = ScoringWorker(store, on, refs[0], decision_provider=decider,
                               run_config=config).dispatch(request, refs[0])
        assert decider.calls == 1
        assert result.scoring_engine == engine
        row = _prescreen(store, unit.work_id)
        assert row["gate_confidence"] == pytest.approx(gate, abs=1e-9)
        assert row["sufficiency_p"] == pytest.approx(p_suff, abs=1e-9)
        if engine == "decision":
            assert row["outcome"] == "accepted" and result.evidence_sufficient is True
            assert on.calls == []
            # Redelivery (CT-ORCH-04) rebuilds the Decision from the stored prescreen row and
            # must reach the same verdict: a rebuild that recomputes `|2p − 1|` (0.70 here)
            # would turn the redelivered unit into an LLM verdict.
            again = ScoringWorker(store, on, refs[0], decision_provider=decider,
                                  run_config=config).dispatch(request, refs[0])
            assert decider.calls == 1, "the stored sample is reused, never re-asked"
            assert again.scoring_engine == "decision" and on.calls == []
        else:
            assert row["outcome"] == "below_gate"
            ScoringWorker(store, off, refs[0], run_config=m._off_config()).dispatch(request, refs[0])
            assert on.calls[0][0] == off.calls[0][0], "the fallback request is engine-off's, byte for byte"
    finally:
        store.close()


# --- TC-REQ-117 ----------------------------------------------------------------------------------

@pytest.mark.writtenahead
def test_tc_req_117_a_score_without_jev_confidence_falls_back_after_one_decide(
        tmp_data_dir, make_fixture_provider, tmp_path) -> None:
    """CT-PROV-19 → M-JUDGE (design 1.8). The judge relies on the provider refusing a Jev answer
    it would otherwise have to guess a confidence for: one `decide`, a `malformed` prescreen, and
    the seat's verdict from the unchanged LLM path. 1.6 derived 0.96 here and accepted."""
    m = _ts110()
    store, provider, world, units = m._world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = m._seat_unit(units, refs)
        request = m._record_llm(provider, store, unit, refs[0], world)
        config = m._engine_config(tmp_data_dir)
        decider = _decider_for(tmp_path, request, config, lambda r: _document(
            r, probs=[.01, .01, .97, .01], confidence=..., p_suff=0.97))
        on, off = m._LLMSpy(provider), m._LLMSpy(provider)
        result = ScoringWorker(store, on, refs[0], decision_provider=decider,
                               run_config=config).dispatch(request, refs[0])
        assert decider.calls == 1, "the engine is sampled once, never re-asked"
        assert result.scoring_engine == "llm"
        row = _prescreen(store, unit.work_id)
        assert row["outcome"] == "malformed"
        assert (row["gate_confidence"], row["band_confidence"]) == (None, None)
        ScoringWorker(store, off, refs[0], run_config=m._off_config()).dispatch(request, refs[0])
        assert on.calls[0][0] == off.calls[0][0]
        metrics = decision_engine_metrics(store.cohort(ORCH_COHORT_ID), world["run_id"])
        assert metrics.decision_malformed == 1
    finally:
        store.close()


# --- TC-REQ-118 ----------------------------------------------------------------------------------

def test_tc_req_118_calibration_bins_read_jevs_reported_band_confidence(
        tmp_data_dir, make_fixture_provider, tmp_path) -> None:
    """CT-PROV-19 → M-STATS (design 1.8). Probabilities `[.30, .30, .40, 0]` would derive
    (4·0.40 − 1)/3 = 0.20, below any gate; Jev reports 0.83 and 0.87, both accepted. The stored
    `band_confidence` must be the reported value, and `decision_gate_calibration` bins it as
    such. Green on 1.6 code, which already preferred a reported value: it pins that no consumer
    re-derives."""
    from aeh.stats import decision_gate_calibration

    m = _ts110()
    store, provider, world, units = m._world(tmp_data_dir, make_fixture_provider, submissions=("S1", "S2"))
    try:
        refs = edge_panel(3)
        seats = [u for u in units if u.judge == refs[0].build_id]
        assert len(seats) == 2, "precondition: one decision seat per submission"
        config = m._engine_config(tmp_data_dir)
        stored = []
        for seat, reported in zip(seats, (0.83, 0.87)):
            request = m._record_llm(provider, store, seat, refs[0], world)
            decider = _decider_for(tmp_path / seat.work_id, request, config, lambda r, c=reported: _document(
                r, probs=[.30, .30, .40, 0.0], confidence=c, p_suff=0.97))
            result = ScoringWorker(store, provider, refs[0], decision_provider=decider,
                                   run_config=config).dispatch(request, refs[0])
            assert result.scoring_engine == "decision"
            row = _prescreen(store, seat.work_id)
            assert row["band_confidence"] == pytest.approx(reported, abs=1e-9)
            stored.append(row["band_confidence"])
        report = decision_gate_calibration([(c, 2, 2) for c in stored], threshold=0.80)
        by_low = {round(b.low, 2): b.n for b in report.bins}
        assert by_low.get(0.80) == 1 and by_low.get(0.85) == 1
    finally:
        store.close()
