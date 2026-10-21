"""TS-110 (#463): M-JUDGE's decision-seat dispatch, rung 2. Jev test plan §5 (M-JUDGE).

The world is the shared TS-31 judged run (`tests/support/judge_run.judge_world`): a real store
with all contributors' migrations, a real package with the C4 four-band scale, the real
extraction leg, and leased score units dispatched through `ScoringWorker`. The model boundary
is `RecordedFixtureProvider` for `complete`. `decide` is answered by a programmed double, so
every engine outcome can be produced on demand. F-JEV-DECISIONS covers the same outcomes
through a whole run (`tests/integration/pipe/test_f_jev_decisions_corpus.py`).

| Case | Asserted |
|---|---|
| TC-JUDGE-29 | Engine off in all three wirings (no provider, provider without engine, engine without provider): `decide` never called, no pre-screen row, the LLM payload equal to engine-off |
| TC-JUDGE-36 | An accepted decision whose cited span fails byte verification falls back as `citation_unverified` (one LLM call, no strike); an uncited accept needs no LLM |
| TC-JUDGE-37 | Every fallback outcome sends the LLM the engine-off payload byte for byte; LLM strike semantics unchanged; an exhausted LLM leaves the pre-screen row and no verdict |
| TC-JUDGE-38 | Engine outages propagate as themselves: no LLM call, no row, no verdict, no strike |
| TC-JUDGE-39 | One engine sample per unit, ever: redelivery reuses the stored row; two concurrent dispatches leave one row |
| TC-JUDGE-40 | One pre-screen row per seat unit and outcome, written before the LLM is called; none for other units or engine-off; no `point` column |
| TC-JUDGE-41 | Verdict `scoring_engine` / `engine_build`; a migrated Cohort-27 database reads as `llm`; the CHECK refuses `'jev'` |
| TC-JUDGE-42 | `decision_engine_metrics` over hand-built rows, hand-computed, and the two alerts' boundaries |
| TC-JUDGE-43 | The F-ADV-INJ-DECISION twins: the band stays in the declared set; a single decision verdict never auto-routes; imitation labels add no key; a field-header imitation adds no header outside the fence |
| TC-STORE-27 | Migrations 28 and 29 apply to a Cohort-27 database; the pin is 29; a chain without `aeh.judge` is refused; CLAUDE.md names both |
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import subprocess
import sys
import threading
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest

from aeh.conf import CohortRef, DecisionEngine, ModelRef, resolve_run_config
from aeh.orch import STAGE_SCORE
from aeh.prov import (BuildChangedError, Decision, DecisionCapabilities,
                      DecisionRequestRejectedError, MalformedResponseError, NoulAnswer,
                      ProviderUnavailableError, RateLimitedError, ScoreAnswer, derived_confidence)
from aeh.store import open_store
from tests.support.conf_builders import edge_cfg, edge_panel
from tests.support.extract_vocabulary import sampling_params, verdict_completion
from tests.support.judge_run import judge_world, warm_judged_modules
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = pytest.mark.integration

C4 = (("Beginning", 0.0, "names no force"), ("Developing", 1.0, "names one force"),
      ("Proficient", 2.0, "relates friction to weight"), ("Exemplary", 3.0, "states the condition"))
C4_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "holistic", "band_count": 4},)
JEV_BUILD = "/models/jev-fixture/model.safetensors@sha256:" + "fe" * 32
FIXTURE_CAPS = DecisionCapabilities(32000, 255, 64, None, True)


# --- the world -----------------------------------------------------------------------------------

def _world(tmp_data_dir, make_fixture_provider, *, panel=3, submissions=("S1",)):
    warm_judged_modules()
    store = open_store(tmp_data_dir)
    provider = make_fixture_provider()
    world = judge_world(store, provider, submissions=list(submissions), panel=panel, judge_leg=False,
                        criteria=C4_CRITERIA, bands=C4)
    # The orchestrator hands out one resident model's units per lease (residency ordering); the
    # first lease is the seat's. `_next_arm` completes it to reach the next model's units.
    units = list(world["orchestrator"].lease("w-judge-ts110", STAGE_SCORE, 64))
    assert units and {u.judge for u in units} == {edge_panel(panel)[0].build_id}, (
        "precondition: the first lease is the decision seat's")
    return store, provider, world, units


def _next_arm(world, units):
    """Complete the leased units and lease the next resident model's."""
    for unit in units:
        world["orchestrator"].complete(unit.work_id)
    batch = list(world["orchestrator"].lease("w-judge-ts110", STAGE_SCORE, 64))
    assert batch, "precondition: another arm's units follow the seat's"
    return batch


def _engine_config(tmp_data_dir, panel=3, **overrides):
    cfg = edge_cfg(panel=edge_panel(panel), HARNESS_DECISION_ENGINE="jev", HARNESS_DECISION_PROVIDER="fixture",
                   HARNESS_JEV_BUILD=JEV_BUILD, HARNESS_JEV_QUANTIZATION="bf16",
                   HARNESS_FIXTURE_DIR=str(tmp_data_dir))
    cfg.update(overrides)
    return resolve_run_config(cfg, CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"))


def _off_config(panel=3):
    return resolve_run_config(edge_cfg(panel=edge_panel(panel)),
                              CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"))


def _decision(probs, *, reported=None, p_suff=0.97, cites=None, n_spans=0):
    confidence = reported if reported is not None else derived_confidence(probs)
    answers = {"band": ScoreAnswer(sum(i * p for i, p in enumerate(probs)), tuple(probs), confidence,
                                   "reported"),
               "evidence_sufficient": NoulAnswer(p_suff, p_suff, "reported")}
    cites = cites if cites is not None else [0.9] * n_spans
    for i, c in enumerate(cites):
        answers[f"cite_{'abcdefghijklmnopqrstuvwxyz'[i]}"] = NoulAnswer(c, c, "reported")
    return Decision(MappingProxyType(answers), 120, 0, 250, "typesafe/jev-1.13", None)


class _Decider:
    """The programmed decision double: `answer(request)` returns a `Decision` or raises."""

    def __init__(self, answer, caps=FIXTURE_CAPS, barrier: threading.Barrier | None = None):
        self.answer = answer
        self.caps = caps
        self.barrier = barrier
        self.calls = 0

    def decision_capabilities(self, model_ref):  # noqa: ANN001
        return self.caps

    def decide(self, request, model_ref):  # noqa: ANN001
        self.calls += 1
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        return self.answer(request)


class _LLMSpy:
    """Wraps the fixture provider's `complete`, recording each call; `on_call` runs first."""

    def __init__(self, inner, on_call=None):
        self.inner = inner
        self.on_call = on_call
        self.calls = []

    def complete(self, payload, model_ref, params):  # noqa: ANN001
        if self.on_call is not None:
            self.on_call()
        self.calls.append((payload, model_ref, params))
        return self.inner.complete(payload, model_ref, params)


def _accepted(request):
    spans = len([q for q in request.questions if q.key.startswith("cite_")])
    return _decision([.02, .02, .94, .02], n_spans=spans)


def _seat_unit(units, panel_refs):
    return next(u for u in units if u.judge == panel_refs[0].build_id)


def _record_llm(provider, store, unit, ref, world, band="Proficient"):
    from aeh.judge import ScoringWorker, prompt_fields

    request = ScoringWorker(store, provider, ref).assemble(unit)
    provider.record(prompt_fields(request), ref, sampling_params(),
                    verdict_completion(band, 0.7, build_id=ref.build_id,
                                       cited_spans=world["spans"][unit.submission_id]))
    return request


def _prescreen_rows(store, work_id=None):
    sql = "SELECT * FROM decision_prescreen" + (" WHERE work_id = :w" if work_id else "")
    rows = store.cohort(ORCH_COHORT_ID).query(sql, **({"w": work_id} if work_id else {}))
    return [dict(zip(r.keys(), tuple(r))) for r in rows]


def _attempts(store, work_id) -> int:
    return int(store.cohort(ORCH_COHORT_ID).query(
        "SELECT attempts FROM work_unit WHERE work_id = :w", w=work_id)[0]["attempts"])


# --- TC-JUDGE-29 -------------------------------------------------------------------------------

def test_tc_judge_29_engine_off_in_every_wiring_is_todays_path(tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = _seat_unit(units, refs)
        request = _record_llm(provider, store, unit, refs[0], world)
        payloads = []
        for decision_provider, run_config in ((None, _off_config()),
                                              (_Decider(_accepted), _off_config()),
                                              (None, _engine_config(tmp_data_dir))):
            spy = _LLMSpy(provider)
            result = ScoringWorker(store, spy, refs[0], decision_provider=decision_provider,
                                   run_config=run_config).dispatch(request, refs[0])
            assert result.scoring_engine == "llm" and result.prescreen_outcome is None
            if decision_provider is not None:
                assert decision_provider.calls == 0
            payloads.append(spy.calls[0][0])
        assert payloads[0] == payloads[1] == payloads[2]
        assert _prescreen_rows(store) == []
    finally:
        store.close()


# --- TC-JUDGE-36 -------------------------------------------------------------------------------

def test_tc_judge_36_an_unverifiable_citation_falls_back_without_a_strike(tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = _seat_unit(units, refs)
        request = _record_llm(provider, store, unit, refs[0], world)
        tampered_span = dict(request.evidence[0], text=request.evidence[0]["text"] + " (edited)")
        tampered = dataclasses.replace(request, evidence=(tampered_span,) + tuple(request.evidence[1:]))
        from aeh.judge import prompt_fields

        provider.record(prompt_fields(tampered), refs[0], sampling_params(),
                        verdict_completion("Proficient", 0.7, build_id=refs[0].build_id,
                                           cited_spans=world["spans"][unit.submission_id]))
        spy = _LLMSpy(provider)
        decider = _Decider(lambda r: _decision([.02, .02, .94, .02], cites=[0.9] + [0.1] * (len(tampered.evidence) - 1)))
        before = _attempts(store, unit.work_id)
        result = ScoringWorker(store, spy, refs[0], decision_provider=decider,
                               run_config=_engine_config(tmp_data_dir)).dispatch(tampered, refs[0])
        assert result.scoring_engine == "llm" and result.prescreen_outcome == "below_gate"
        assert len(spy.calls) == 1 and _attempts(store, unit.work_id) == before
        assert [r["reason"] for r in _prescreen_rows(store, unit.work_id)] == ["citation_unverified"]
    finally:
        store.close()


def test_tc_judge_36_an_uncited_accept_needs_no_llm(tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = _seat_unit(units, refs)
        request = ScoringWorker(store, provider, refs[0]).assemble(unit)
        spy = _LLMSpy(provider)
        decider = _Decider(lambda r: _decision([.02, .02, .94, .02], cites=[0.1] * len(request.evidence)))
        result = ScoringWorker(store, spy, refs[0], decision_provider=decider,
                               run_config=_engine_config(tmp_data_dir)).dispatch(request, refs[0])
        assert result.scoring_engine == "decision" and result.uncited is True and spy.calls == []
    finally:
        store.close()


# --- TC-JUDGE-37 -------------------------------------------------------------------------------

def _raise(error):
    def answer(request):  # noqa: ANN001
        raise error
    return answer


FALLBACKS = {
    "ineligible": (lambda r: _accepted(r), DecisionCapabilities(10, 255, 64, None, True), "ineligible"),
    "below_threshold": (lambda r: _decision([.05, .05, .85, .05], reported=0.62, n_spans=len(
        [q for q in r.questions if q.key.startswith("cite_")])), FIXTURE_CAPS, "below_gate"),
    "argmax_tie": (lambda r: _decision([.5, .5, 0, 0], reported=0.9, n_spans=len(
        [q for q in r.questions if q.key.startswith("cite_")])), FIXTURE_CAPS, "below_gate"),
    "rejected": (_raise(DecisionRequestRejectedError("HTTP 422")), FIXTURE_CAPS, "rejected"),
    "malformed": (_raise(MalformedResponseError("bad legend")), FIXTURE_CAPS, "malformed"),
}


@pytest.mark.parametrize("name", list(FALLBACKS))
def test_tc_judge_37_every_fallback_is_the_engine_off_request_byte_for_byte(
        name, tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = _seat_unit(units, refs)
        request = _record_llm(provider, store, unit, refs[0], world)
        off_spy = _LLMSpy(provider)
        off = ScoringWorker(store, off_spy, refs[0], run_config=_off_config()).dispatch(request, refs[0])
        answer, caps, outcome = FALLBACKS[name]
        on_spy = _LLMSpy(provider)
        on = ScoringWorker(store, on_spy, refs[0], decision_provider=_Decider(answer, caps=caps),
                           run_config=_engine_config(tmp_data_dir)).dispatch(request, refs[0])
        assert len(on_spy.calls) == 1
        assert on_spy.calls[0] == off_spy.calls[0], "payload, ModelRef and SamplingParams are engine-off's"
        assert on.scoring_engine == "llm" and on.prescreen_outcome == outcome
        assert (on.band, on.band_ordinal, on.cited_spans) == (off.band, off.band_ordinal, off.cited_spans)
    finally:
        store.close()


def test_tc_judge_37_an_exhausted_llm_keeps_the_row_and_writes_no_verdict(
        tmp_data_dir, make_fixture_provider, monkeypatch) -> None:
    from aeh.judge import JudgmentError, ScoringWorker

    monkeypatch.setenv("HARNESS_JUDGE_MAX_ATTEMPTS", "2")
    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = _seat_unit(units, refs)
        request = ScoringWorker(store, provider, refs[0]).assemble(unit)  # no LLM recording: every call misses
        worker = ScoringWorker(store, provider, refs[0], decision_provider=_Decider(FALLBACKS["rejected"][0]),
                               run_config=_engine_config(tmp_data_dir))
        with pytest.raises((JudgmentError, Exception)):
            worker.dispatch(request, refs[0])
        assert [r["outcome"] for r in _prescreen_rows(store, unit.work_id)] == ["rejected"]
        assert store.cohort(ORCH_COHORT_ID).query("SELECT count(*) n FROM verdict")[0]["n"] == 0
    finally:
        store.close()


# --- TC-JUDGE-38 -------------------------------------------------------------------------------

@pytest.mark.parametrize("error", [RateLimitedError("429"), ProviderUnavailableError("down"),
                                   BuildChangedError("build moved")], ids=lambda e: type(e).__name__)
def test_tc_judge_38_an_outage_propagates_as_itself(error, tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = _seat_unit(units, refs)
        request = _record_llm(provider, store, unit, refs[0], world)
        spy = _LLMSpy(provider)
        before = _attempts(store, unit.work_id)
        with pytest.raises(type(error)):
            ScoringWorker(store, spy, refs[0], decision_provider=_Decider(_raise(error)),
                          run_config=_engine_config(tmp_data_dir)).dispatch(request, refs[0])
        assert spy.calls == [] and _prescreen_rows(store) == []
        assert store.cohort(ORCH_COHORT_ID).query("SELECT count(*) n FROM verdict")[0]["n"] == 0
        assert _attempts(store, unit.work_id) == before
    finally:
        store.close()


# --- TC-JUDGE-39 -------------------------------------------------------------------------------

def test_tc_judge_39_redelivery_reuses_the_stored_sample(tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = _seat_unit(units, refs)
        request = _record_llm(provider, store, unit, refs[0], world)
        config = _engine_config(tmp_data_dir)
        first_decider = _Decider(_accepted)
        first = ScoringWorker(store, provider, refs[0], decision_provider=first_decider,
                              run_config=config).dispatch(request, refs[0])
        assert first.scoring_engine == "decision" and first_decider.calls == 1
        # A crash before persist, then redelivery to a fresh worker.
        again_decider = _Decider(_accepted)
        worker = ScoringWorker(store, provider, refs[0], decision_provider=again_decider, run_config=config)
        second = worker.dispatch(request, refs[0])
        assert again_decider.calls == 0
        assert dataclasses.replace(second, attempts=first.attempts) == first
        worker.persist(unit, second)
        assert store.cohort(ORCH_COHORT_ID).query(
            "SELECT count(*) n FROM verdict WHERE work_id = :w", w=unit.work_id)[0]["n"] == 1
    finally:
        store.close()


def test_tc_judge_39_a_stored_below_gate_row_goes_straight_to_the_llm(tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = _seat_unit(units, refs)
        request = _record_llm(provider, store, unit, refs[0], world)
        config = _engine_config(tmp_data_dir)
        ScoringWorker(store, provider, refs[0], decision_provider=_Decider(FALLBACKS["below_threshold"][0]),
                      run_config=config).dispatch(request, refs[0])
        decider, spy = _Decider(_accepted), _LLMSpy(provider)
        ScoringWorker(store, spy, refs[0], decision_provider=decider, run_config=config).dispatch(request, refs[0])
        assert decider.calls == 0 and len(spy.calls) == 1
    finally:
        store.close()


def test_tc_judge_39_two_concurrent_dispatches_leave_one_row(tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = _seat_unit(units, refs)
        request = _record_llm(provider, store, unit, refs[0], world)
        config = _engine_config(tmp_data_dir)
        barrier = threading.Barrier(2)
        results, errors = [], []

        def run():
            try:
                results.append(ScoringWorker(store, provider, refs[0], decision_provider=_Decider(_accepted, barrier=barrier),
                                             run_config=config).dispatch(request, refs[0]))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert errors == [] and len(results) == 2
        assert len(_prescreen_rows(store, unit.work_id)) == 1
    finally:
        store.close()


# --- TC-JUDGE-40 -------------------------------------------------------------------------------

@pytest.mark.parametrize("outcome", ["accepted", "below_gate", "ineligible", "rejected", "malformed"])
def test_tc_judge_40_one_row_per_seat_unit_written_before_the_llm(outcome, tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = _seat_unit(units, refs)
        request = _record_llm(provider, store, unit, refs[0], world)
        answers = {
            "accepted": (_accepted, FIXTURE_CAPS, {}),
            "below_gate": (FALLBACKS["below_threshold"][0], FIXTURE_CAPS, {}),
            "ineligible": (_accepted, FIXTURE_CAPS, {"HARNESS_JEV_MAX_CITATION_QUESTIONS": "1"}),
            "rejected": (FALLBACKS["rejected"][0], FIXTURE_CAPS, {}),
            "malformed": (FALLBACKS["malformed"][0], FIXTURE_CAPS, {}),
        }
        answer, caps, overrides = answers[outcome]
        if outcome == "ineligible":
            assert len(request.evidence) > 1, "precondition: more spans than the one-citation engine allows"
        spy = _LLMSpy(provider, on_call=lambda: _check_row_exists(store, unit.work_id))
        ScoringWorker(store, spy, refs[0], decision_provider=_Decider(answer, caps=caps),
                      run_config=_engine_config(tmp_data_dir, **overrides)).dispatch(request, refs[0])
        rows = _prescreen_rows(store, unit.work_id)
        assert len(rows) == 1 and rows[0]["outcome"] == outcome
        row = rows[0]
        assert row["threshold"] == pytest.approx(0.8)
        if outcome in ("accepted", "below_gate"):
            assert None not in (row["gate_confidence"], row["band_confidence"], row["sufficiency_p"], row["argmax_band"])
            probs = json.loads(row["band_probabilities"])
            assert isinstance(probs, list) and len(probs) == 4
            assert isinstance(json.loads(row["cite_probabilities"]), dict)
        else:
            assert (row["gate_confidence"], row["band_confidence"], row["sufficiency_p"], row["argmax_band"]) == (None,) * 4
            assert row["reason"]
        assert row.get("cost") is None
        columns = [r[1] for r in store.cohort(ORCH_COHORT_ID).query("PRAGMA table_info(decision_prescreen)")]
        assert not [c for c in columns if "point" in c]
    finally:
        store.close()


def _check_row_exists(store, work_id):
    assert _prescreen_rows(store, work_id), "the LLM was called before the pre-screen row existed"


def test_tc_judge_40_non_seat_and_engine_off_units_write_no_row(tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        seat = _seat_unit(units, refs)
        seat_request = _record_llm(provider, store, seat, refs[0], world)
        decider = _Decider(_accepted)
        ScoringWorker(store, provider, refs[0], decision_provider=decider,
                      run_config=_off_config()).dispatch(seat_request, refs[0])
        other = _next_arm(world, units)[0]
        ref = next(r for r in refs if r.build_id == other.judge)
        assert ref.build_id != refs[0].build_id
        request = _record_llm(provider, store, other, ref, world)
        ScoringWorker(store, provider, ref, decision_provider=decider,
                      run_config=_engine_config(tmp_data_dir)).dispatch(request, ref)
        assert decider.calls == 0 and _prescreen_rows(store) == []
    finally:
        store.close()


# --- TC-JUDGE-41 -------------------------------------------------------------------------------

def test_tc_judge_41_verdict_engine_columns(tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker, verdicts_for

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        config = _engine_config(tmp_data_dir)
        seat = _seat_unit(units, refs)
        seat_request = _record_llm(provider, store, seat, refs[0], world)
        worker = ScoringWorker(store, provider, refs[0], decision_provider=_Decider(_accepted), run_config=config)
        worker.persist(seat, worker.dispatch(seat_request, refs[0]))
        other = _next_arm(world, units)[0]
        ref = next(r for r in refs if r.build_id == other.judge)
        other_request = _record_llm(provider, store, other, ref, world)
        worker2 = ScoringWorker(store, provider, ref, decision_provider=_Decider(_accepted), run_config=config)
        worker2.persist(other, worker2.dispatch(other_request, ref))
        rows = {r["work_id"]: (r["scoring_engine"], r["engine_build"]) for r in store.cohort(ORCH_COHORT_ID).query(
            "SELECT work_id, scoring_engine, engine_build FROM verdict")}
        assert rows[seat.work_id] == ("decision", "typesafe/jev-1.13")
        assert rows[other.work_id][0] == "llm" and rows[other.work_id][1]
        with pytest.raises(sqlite3.IntegrityError):
            with store.cohort(ORCH_COHORT_ID).transaction() as tx:
                tx.execute("UPDATE verdict SET scoring_engine = 'jev' WHERE work_id = :w", w=seat.work_id)
        assert verdicts_for(store.cohort(ORCH_COHORT_ID), world["run_id"], seat.submission_id, "C1")
    finally:
        store.close()


def test_tc_judge_41_a_migrated_pre_delta_verdict_reads_as_llm(tmp_path) -> None:
    from aeh.store import Tier, TIER_MIGRATIONS
    from tests.support.jev_corpora import cohort_27_database

    db = cohort_27_database(tmp_path / "cohort.db")
    con = sqlite3.connect(db)
    try:
        for migration in sorted((m for m in TIER_MIGRATIONS[Tier.COHORT] if m.version > 27), key=lambda m: m.version):
            for statement in migration.statements:
                con.execute(str(statement))
        con.commit()
        assert con.execute("SELECT count(*) FROM verdict WHERE scoring_engine IS NULL").fetchone()[0] >= 1
    finally:
        con.close()
    from aeh.judge import StoredVerdict  # a NULL engine is read as the LLM path
    assert "scoring_engine" in {f.name for f in dataclasses.fields(StoredVerdict)}


# --- TC-JUDGE-42 -------------------------------------------------------------------------------

def _seed_prescreens(store, run_id, rows):
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        for i, (outcome, reason, latency) in enumerate(rows):
            tx.execute(
                "INSERT INTO decision_prescreen (work_id, run_id, submission_id, criterion_id, engine_build, "
                "outcome, reason, threshold, latency_ms) VALUES (:w, :r, :s, 'C1', 'b', :o, :re, 0.8, :l)",
                w=f"{run_id}-w{i}", r=run_id, s=f"S{i}", o=outcome, re=reason, l=latency)


def test_tc_judge_42_metrics_hand_computed(tmp_data_dir, make_fixture_provider) -> None:
    """C1: 10 rows: 6 accepted, 2 below_gate, 1 rejected, 1 ineligible(context); latencies 100…1000.
    accepted_rate 6/10 = 0.6; fallback (2 + 1 + 0)/10 = 0.3. p50 by linear interpolation between
    closest ranks: (500 + 600)/2 = 550; p95: rank 0.95·9 = 8.55 → 900 + 0.55·100 = 955."""
    from aeh.judge import decision_engine_metrics

    store, provider, world, units = _world(tmp_data_dir, make_fixture_provider)
    try:
        outcomes = ["accepted"] * 6 + ["below_gate"] * 2 + ["rejected", "ineligible"]
        reasons = [None] * 6 + ["below_threshold"] * 2 + ["rejected", "context"]
        _seed_prescreens(store, "R-C1", [(o, r, 100 * (i + 1)) for i, (o, r) in enumerate(zip(outcomes, reasons))])
        m = decision_engine_metrics(store.cohort(ORCH_COHORT_ID), "R-C1")
        assert (m.decision_prescreens, m.decision_accepted, m.decision_below_gate, m.decision_rejected,
                m.decision_malformed, m.decision_ineligible) == (10, 6, 2, 1, 0, 1)
        assert dict(m.decision_ineligible_reasons) == {"context": 1}
        assert m.decision_accepted_rate == pytest.approx(0.6) and m.decision_fallback_rate == pytest.approx(0.3)
        assert m.decision_latency_p50_ms == pytest.approx(550) and m.decision_latency_p95_ms == pytest.approx(955)
        assert m.decision_requests_rejected is True
        for run, n, fallbacks, fires in (("R-52", 50, 26, True), ("R-49", 49, 26, False), ("R-100", 100, 50, False)):
            _seed_prescreens(store, run, [("below_gate" if i < fallbacks else "accepted",
                                           "below_threshold" if i < fallbacks else None, 100) for i in range(n)])
            assert decision_engine_metrics(store.cohort(ORCH_COHORT_ID), run).decision_fallback_rate_high is fires, run
            assert decision_engine_metrics(store.cohort(ORCH_COHORT_ID), run).decision_requests_rejected is False
    finally:
        store.close()


# --- TC-JUDGE-43 -------------------------------------------------------------------------------

def test_tc_judge_43_decision_path_injection_twins(tmp_path) -> None:
    from aeh.agg import aggregate
    from aeh.judge import Accepted, gate_decision
    from aeh.prov import RecordedFixtureProvider
    from tests.support import jev_corpora
    from tests.support.agg_vocabulary import band, criterion, favourable_signals, verdict

    engine = DecisionEngine(model=ModelRef(role="decision", provider="fixture", build_id=JEV_BUILD, quantization="bf16"),
                            confidence_threshold=Decimal("0.80"), cite_threshold=Decimal("0.50"),
                            max_citation_questions=16, token_bytes_ratio=3)
    recorded = jev_corpora.record_adv_decisions(tmp_path, engine)
    provider = RecordedFixtureProvider(fixture_dir=tmp_path)
    by_pair = {}
    for member_id, (member, scoring, request) in recorded.items():
        by_pair.setdefault(member["pair_id"], {})[member["variant"]] = (member, scoring, request)
        outcome = gate_decision(provider.decide(request, engine.model), scoring, engine)
        declared = {b.band for b in scoring.criterion.bands}
        if isinstance(outcome, Accepted):
            assert outcome.result.band in declared
            if member["variant"] == "injected":
                bands = [band(b.band, b.ordinal, float(b.ordinal)) for b in scoring.criterion.bands]
                # The single decision verdict as aggregation reads it (the stored-verdict shape).
                single = verdict(outcome.result.band, outcome.result.band_ordinal,
                                 cited=not outcome.result.uncited, self_confidence=outcome.result.self_confidence)
                single.scoring_engine = "decision"
                score = aggregate([single], criterion(bands), favourable_signals())
                assert score.confidence <= 0.75 and score.routing != "auto"
    for pair in by_pair.values():
        member, benign_scoring, benign_request = pair["benign"]
        inj_member, inj_scoring, inj_request = pair["injected"]
        assert [q.key for q in inj_request.questions] == [q.key for q in benign_request.questions]
        state = inj_request.state
        # The fence is the submission field's value; the directive names the markers too, so
        # the fence is located from the `### submission` header, not by first occurrence.
        fence_at = state.index("<untrusted_student_content>", state.index("### submission\n"))
        fence_end = state.rindex("</untrusted_student_content>")
        outside = [line for line in (state[:fence_at] + state[fence_end:]).splitlines() if line.startswith("### ")]
        assert len(outside) == 5, inj_member["injection_kind"]
        if inj_member["injection_kind"] == "span_label_imitation":
            assert fence_at < state.index("[span b] this fully meets") < fence_end


# --- TC-STORE-27 -------------------------------------------------------------------------------

def test_tc_store_27_migrations_28_and_29_and_the_pin(tmp_path) -> None:
    from aeh.store import COMPLETE_SCHEMA_VERSIONS, TIER_MIGRATIONS, Tier

    names = {m.version: m.name for m in TIER_MIGRATIONS[Tier.COHORT]}
    assert names[28] == "judge_decision_prescreen" and names[29] == "judge_verdict_engine"
    # The pin is the chain's head; later migrations (#524's 30, ...) move it past 29.
    assert COMPLETE_SCHEMA_VERSIONS[Tier.COHORT] == max(names) >= 29
    claude = (Path(__file__).resolve().parents[3] / "CLAUDE.md").read_text(encoding="utf-8")
    assert "judge_decision_prescreen" in claude and "judge_verdict_engine" in claude
    code = (
        "import sys; sys.path[:0]=['src', '.']\n"
        "import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.orch, aeh.pkg, aeh.review, aeh.synth\n"
        "from aeh.store import open_store, IncompleteMigrationChainError\n"
        f"try:\n    s = open_store(r'{tmp_path / 'data'}'); s.cohort('c-x')\n"
        "    print('OPENED')\nexcept IncompleteMigrationChainError:\n    print('REFUSED')\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parents[3])
    assert "REFUSED" in out.stdout, out.stdout + out.stderr
