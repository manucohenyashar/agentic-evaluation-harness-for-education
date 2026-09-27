"""TS-119 (#472): engine measurement: per-engine signals, agreement, calibration, non-inferiority.
Jev test plan §5 (M-STATS).

| Case | Asserted |
|---|---|
| TC-STATS-32 | Signals per `(criterion, judge, scoring_engine)`: uncited rate 2/6 for decision, 1/4 for llm; the outcome mix is `decision_engine_metrics`' |
| TC-STATS-33 | Agreement per partition over admissible labels only, equal to the hand-computed alpha (docstring) |
| TC-STATS-34 | The calibration bins: 25 labels at 0.80 exact with Wilson [0.6087, 0.9114]; 19 labels insufficient |
| TC-STATS-35 | Non-inferiority: 0.70 vs 0.74 → True (0.70 ≥ 0.69); 0.68 → False; 59 labels → `insufficient_data` |
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_tc_stats_32_signals_per_engine(tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import decision_engine_metrics
    from aeh.stats import judge_signals
    from tests.integration.judge.test_ts110_decision_dispatch import _world
    from tests.support.orch_run import ORCH_COHORT_ID

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        handle = store.cohort(ORCH_COHORT_ID)
        rows = ([("decision", True)] * 2 + [("decision", False)] * 4 + [("llm", True)] + [("llm", False)] * 3)
        with handle.transaction() as tx:
            for i, (engine, uncited) in enumerate(rows):
                tx.execute("INSERT INTO work_unit (work_id, submission_id, stage, status, run_id, criterion_id, attempts, "
                           "judge_id) VALUES (:w, 'S1', 'score', 'done', :r, 'C1', 0, 'A')",
                           w=f"sig-{i}", r=world["run_id"])
                tx.execute("INSERT INTO verdict (verdict_id, work_id, judge_id, band, band_ordinal, self_confidence, "
                           "cited_spans, evidence_sufficient, uncited, evidence_assessment, latency_ms, scoring_engine, "
                           "engine_build) VALUES (:v, :w, 'A', 'Proficient', 2, 0.9, '[]', 1, :u, 'x', 100, :e, 'b')",
                           v=f"sig-{i}", w=f"sig-{i}", u=int(uncited), e=engine)
        signals = judge_signals(handle, world["run_id"], durable=store.durable())
        assert signals.by_engine[("C1", "A", "decision")]["uncited_verdict_rate"] == pytest.approx(2 / 6)
        assert signals.by_engine[("C1", "A", "llm")]["uncited_verdict_rate"] == pytest.approx(1 / 4)
        assert signals.by_engine[("C1", "A", "decision")]["verdicts"] == 6
        assert signals.decision_outcomes is None, "no pre-screens yet: no outcome mix, never zeros"
        with handle.transaction() as tx:
            for i, outcome in enumerate(["accepted", "accepted", "below_gate", "rejected"]):
                tx.execute("INSERT INTO decision_prescreen (work_id, run_id, submission_id, criterion_id, engine_build, "
                           "outcome, reason, threshold, latency_ms) VALUES (:w, :r, 'S1', 'C1', 'b', :o, :re, 0.8, 100)",
                           w=f"sig-{i}", r=world["run_id"], o=outcome, re=None if outcome == "accepted" else outcome)
        signals = judge_signals(handle, world["run_id"], durable=store.durable())
        metrics = decision_engine_metrics(handle, world["run_id"])
        mix = signals.decision_outcomes
        assert mix["decision_prescreens"] == metrics.decision_prescreens == 4
        assert (mix["decision_accepted"], mix["decision_below_gate"], mix["decision_rejected"]) == (
            metrics.decision_accepted, metrics.decision_below_gate, metrics.decision_rejected) == (2, 1, 1)
    finally:
        store.close()


def test_tc_stats_33_agreement_per_partition_is_hand_computed() -> None:
    """Hand computation in `aeh.agg`'s declared ordinal convention (issue #91): D_o = mean |gap|
    / (K − 1); D_e = Σ_{a≠b} |a − b| / (K − 1) / (K(K − 1)); alpha = 1 − D_o / D_e. Bands 1..4 map
    to ordinals 0..3, so K = 4 and D_e = 20 / 3 / 12 = 5/9.

    - decision (60 admissible; the 5 planted operational labels excluded): gaps are CAL25's
      4×1 + 1×2 and CAL19's 3×1, so Σ = 9, D_o = 9/60/3 = 0.05, alpha = 1 − 0.05·9/5 = 0.91.
    - llm_fallback: 15 gaps of 1, so D_o = 15/180 = 1/12 and alpha = 1 − 0.15 = 0.85.
    - llm_engine_off: 20 gaps from i%3 == 2, plus 6 from i%10 == 9 (two cells overlap as gap
      2), so Σ = 26, D_o = 26/180 and alpha = 1 − 0.26 = 0.74."""
    from aeh.stats import agreement_by_engine
    from tests.support import jev_corpora

    v1 = [label for label in jev_corpora.stats_labels() if label.package_version == "1"]
    result = agreement_by_engine(v1, jev_corpora.partition_of)
    assert {p: result[p].n for p in result} == {"decision": 60, "llm_fallback": 60, "llm_engine_off": 60}
    assert result["decision"].ordinal_alpha == pytest.approx(0.91, abs=1e-9)
    assert result["llm_fallback"].ordinal_alpha == pytest.approx(0.85, abs=1e-9)
    assert result["llm_engine_off"].ordinal_alpha == pytest.approx(0.74, abs=1e-9)


def test_tc_stats_34_calibration_bins() -> None:
    """Wilson 95% for 20/25: p = 0.8, z = 1.96; centre (0.8 + 1.9208/25)/(1 + 3.8416/25) and half
    1.96·sqrt(0.8·0.2/25 + 3.8416/2500)/(1 + 3.8416/25) give [0.6087, 0.9114]."""
    from aeh.stats import decision_gate_calibration
    from tests.support import jev_corpora

    records = [(l.band_confidence, l.system_band, l.teacher_band) for l in jev_corpora.stats_labels("D60")]
    report = decision_gate_calibration(records, threshold=0.80)
    first, second = report.bins[0], report.bins[1]
    assert (first.low, first.n, first.exact_agreement) == (0.80, 25, pytest.approx(0.80))
    assert first.interval_low == pytest.approx(0.6087, abs=1e-4) and first.interval_high == pytest.approx(0.9114, abs=1e-4)
    assert second.n == 19 and second.insufficient_data and second.exact_agreement is None


def test_tc_stats_35_non_inferiority_verdicts() -> None:
    from aeh.stats import EngineAgreement, INSUFFICIENT_DATA, decision_engine_noninferior

    def agreement(decision_alpha, decision_n=60):
        return {"decision": EngineAgreement("decision", decision_n, None if decision_n < 60 else decision_alpha,
                                            decision_n < 60),
                "llm_engine_off": EngineAgreement("llm_engine_off", 60, 0.74, False)}

    assert decision_engine_noninferior(agreement(0.70)) is True
    assert decision_engine_noninferior(agreement(0.68)) is False
    assert decision_engine_noninferior(agreement(0.70, decision_n=59)) == INSUFFICIENT_DATA
    # The 60-label minimum itself, through the real partitioning over F-STATS-JEV: 59 labels
    # (D59) are insufficient, 60 (D60) are not.
    from aeh.stats import agreement_by_engine
    from tests.support import jev_corpora

    real = {**agreement_by_engine(jev_corpora.stats_labels("D59"), jev_corpora.partition_of)}
    assert real["decision"].n == 59 and real["decision"].insufficient_data
    real["llm_engine_off"] = EngineAgreement("llm_engine_off", 60, 0.74, False)
    assert decision_engine_noninferior(real) == INSUFFICIENT_DATA
    sixty = agreement_by_engine(jev_corpora.stats_labels("D60"), jev_corpora.partition_of)
    assert sixty["decision"].n == 60 and not sixty["decision"].insufficient_data
