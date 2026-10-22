"""TC-JUDGE-47 (#819): the confirmation call, driven through the real `ScoringWorker`.

Traces: FR-JUDGE-39, FR-AGG-20, CT-JUDGE-22 (console-clarity design delta r6: a confident Jev
decision is final only when the seat's LLM judge, `panel[0]`, confirms the same band; otherwise
the judge's verdict is the unit's, `prescreen_outcome='unconfirmed'`, and takes the ordinary
single-LLM path). Source: `docs/design/console_clarity_test_plan.md` §3.2.

| Arm | Asserted |
|---|---|
| (a) | Jev accepts `Proficient`, the judge gives `Proficient`: one verdict, `scoring_engine='decision'`; the stored cell aggregates `final`/`auto` with confidence = the gate; the pre-screen row records `confirmed_by` the seat judge and the band |
| (b) | Jev accepts the top band, the judge gives `Proficient`: one verdict, `scoring_engine='llm'`, `prescreen_outcome='unconfirmed'`; the cell is `provisional_unreviewed` / `one_grader_unsure`, and its aggregate and `should_escalate` decision equal the engine-off single verdict's for the same unit (differential) |
| (c) | The judge call fails terminally: the unit fails as an engine-off LLM unit does (same error type), no verdict row, and the pre-screen row records no confirmation |
| (d) | Knob false: no `complete` call, the journal holds only the `jev_decision` record, and the lone decision verdict aggregates `provisional_unreviewed` (FR-AGG-07) |
| (e) | The confirmation request (payload, ModelRef, SamplingParams) equals the engine-off request for the same unit (CT-JUDGE-22) |
| forged citation | (#814 reviewer note) An above-gate Jev answer citing a span whose bytes are not the document's, with a judge recorded to confirm Jev's band: no decision verdict is produced; the pre-screen row is `below_gate` / `citation_unverified` and the unit's verdict is the LLM fallback's |
| mutation | `_confirm` patched to call the judge and return the decision without checking its band: arm (b)'s oracle goes red |

**Rung.** Rung 3: the TS-31 judged world (`tests/support/judge_run.judge_world`): a real store,
a real package, real extraction, leased score units, and the real `ScoringWorker` with
`HARNESS_JEV_FINAL_ON_ACCEPT` resolved into its run config. `decide` and `complete` are both
answered by `RecordedFixtureProvider` from recordings made in the test. Unlike TC-JUDGE-46, which
composes the decision path in test code, nothing here restates the worker's band comparison or
citation check, so a worker that skipped either one fails these arms.

**INJ-24 caveat** (#814, PR #841). In F-ADV-INJ-DECISION, INJ-24's benign band already is the top
band, so a judge that confirms it legitimately makes the cell final. That is the correct grade,
not a leak. TC-JUDGE-46 asserts only that the band did not move. The forged-citation arm here
checks the worker's own citation refusal with a confirming judge.

Markers. `integration`. Written against shipped code (#806), so not `writtenahead`.
"""

from __future__ import annotations

import dataclasses

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.orch import STAGE_SCORE
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
REFERENCE, TOP = "Proficient", "Exemplary"
ORDINAL = {name: i for i, (name, _p, _d) in enumerate(C4)}


# --- the world -----------------------------------------------------------------------------------

@pytest.fixture
def world(tmp_data_dir, make_fixture_provider):
    warm_judged_modules()
    store = open_store(tmp_data_dir)
    provider = make_fixture_provider()
    built = judge_world(store, provider, submissions=["S1"], panel=3, judge_leg=False,
                        criteria=C4_CRITERIA, bands=C4)
    units = list(built["orchestrator"].lease("w-judge-47", STAGE_SCORE, 64))
    refs = edge_panel(3)
    seat = next(u for u in units if u.judge == refs[0].build_id)
    try:
        yield store, provider, built, seat, refs[0], tmp_data_dir
    finally:
        store.close()


def _config(data_dir, knob: bool | None):
    """The engine-on run config with FR-AGG-20's knob, or the engine-off config (`knob=None`)."""
    if knob is None:
        cfg = edge_cfg(panel=edge_panel(3))
    else:
        cfg = edge_cfg(panel=edge_panel(3), HARNESS_DECISION_ENGINE="jev",
                       HARNESS_DECISION_PROVIDER="fixture", HARNESS_JEV_BUILD=JEV_BUILD,
                       HARNESS_JEV_QUANTIZATION="bf16", HARNESS_FIXTURE_DIR=str(data_dir),
                       HARNESS_JEV_FINAL_ON_ACCEPT="true" if knob else "false")
    return resolve_run_config(cfg, CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"))


class _Spy:
    """The recorded provider behind both doors, recording each `complete` call's arguments."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def complete(self, payload, model_ref, params):  # noqa: ANN001
        self.calls.append((payload, model_ref, params))
        return self.inner.complete(payload, model_ref, params)

    def decide(self, request, model_ref):  # noqa: ANN001
        return self.inner.decide(request, model_ref)

    def decision_capabilities(self, model_ref):  # noqa: ANN001
        return self.inner.decision_capabilities(model_ref)


def _assemble(store, provider, judge, unit):
    from aeh.judge import ScoringWorker

    return ScoringWorker(store, provider, judge).assemble(unit)


def _record_judge(provider, request, judge, band, spans):
    """The seat judge's recorded answer, keyed on the engine-off payload (CT-JUDGE-22)."""
    from aeh.judge import prompt_fields

    provider.record(prompt_fields(request), judge, sampling_params(),
                    verdict_completion(band, 0.7, build_id=judge.build_id, cited_spans=spans))


def _record_jev(provider, request, run_config, band, *, cite=0.95):
    """Jev's recorded answer: mass 0.97 on `band`, sufficiency 0.97, every span cited at `cite`."""
    from aeh.judge import decision_request
    from tests.support import jev_corpora

    engine = run_config.decision_engine
    decision = decision_request(request, engine)
    probs = [0.01] * len(C4)
    probs[ORDINAL[band]] = 0.97
    labels = [q.key[len("cite_"):] for q in decision.questions if q.key.startswith("cite_")]
    provider.record_decision(decision, engine.model, jev_corpora.answer_document(
        decision, {"band_probabilities": probs, "sufficiency": 0.97,
                   "cites": {label: cite for label in labels}}, "fixture"))


def _worker(store, spy, judge, run_config):
    from aeh.judge import ScoringWorker

    return ScoringWorker(store, spy, judge, decision_provider=spy, run_config=run_config)


def _prescreen(store, work_id):
    rows = store.cohort(ORCH_COHORT_ID).query(
        "SELECT * FROM decision_prescreen WHERE work_id = :w", w=work_id)
    return [dict(zip(r.keys(), tuple(r))) for r in rows]


def _criterion():
    from tests.support.agg_vocabulary import band, criterion

    return criterion([band(name, i, points) for i, (name, points, _d) in enumerate(C4)],
                     scoring_model="holistic", criterion_id="C1")


def _stored_cell(store, built, unit):
    from aeh.judge import verdicts_for

    return verdicts_for(store.cohort(ORCH_COHORT_ID), built["run_id"], unit.submission_id, "C1")


def _aggregate(verdicts, knob=True):
    from aeh.agg import aggregate
    from tests.support.agg_vocabulary import favourable_signals

    return aggregate(verdicts, _criterion(), favourable_signals(), jev_final_on_accept=knob)


def _escalation(score):
    from aeh.agg import should_escalate
    from tests.support.agg_vocabulary import criterion_history, expected_distribution

    decision = should_escalate(score=score, criterion=_criterion(), history=criterion_history(),
                               baseline=expected_distribution())
    return (bool(decision.escalate), tuple(getattr(decision, "reasons", ()) or ()))


def _score_fields(score):
    from aeh.agg import stored_not_final_reason

    return (score.band, score.state, score.routing, round(float(score.confidence), 9),
            score.judge_count, stored_not_final_reason(score))


# --- (a) confirmed -------------------------------------------------------------------------------

def test_tc_judge_47_a_a_confirming_judge_makes_the_decision_final_at_the_gate(world) -> None:
    from aeh.judge import prescreen_confirmation

    store, provider, built, seat, judge, data_dir = world
    config = _config(data_dir, True)
    request = _assemble(store, provider, judge, seat)
    _record_jev(provider, request, config, REFERENCE)
    _record_judge(provider, request, judge, REFERENCE, built["spans"][seat.submission_id])
    spy = _Spy(provider)
    worker = _worker(store, spy, judge, config)
    result = worker.dispatch(request, judge)
    assert result.scoring_engine == "decision" and result.band == REFERENCE
    assert len(spy.calls) == 1, "exactly one confirmation call"
    worker.persist(seat, result)

    (row,) = _prescreen(store, seat.work_id)
    assert row["outcome"] == "accepted"
    assert prescreen_confirmation(row["reason"]) == ("confirmed_by", judge.build_id, REFERENCE)
    verdicts = _stored_cell(store, built, seat)
    assert [v.scoring_engine for v in verdicts] == ["decision"]
    score = _aggregate(verdicts)
    assert (score.state, score.routing) == ("final", "auto")
    assert score.confidence == pytest.approx(float(row["gate_confidence"]))
    assert float(row["gate_confidence"]) > float(config.decision_engine.confidence_threshold)


# --- (b) unconfirmed -----------------------------------------------------------------------------

def _arm_b(world, worker_factory=_worker):
    """Jev confident on the top band, the judge on the reference band. Returns what (b) asserts
    on, plus the engine-off twin computed from the same unit and recordings."""
    from aeh.judge import StoredVerdict, prescreen_confirmation

    store, provider, built, seat, judge, data_dir = world
    config = _config(data_dir, True)
    request = _assemble(store, provider, judge, seat)
    _record_jev(provider, request, config, TOP)
    _record_judge(provider, request, judge, REFERENCE, built["spans"][seat.submission_id])
    spy = _Spy(provider)
    worker = worker_factory(store, spy, judge, config)
    result = worker.dispatch(request, judge)
    off = _worker(store, _Spy(provider), judge, _config(data_dir, None)).dispatch(request, judge)
    worker.persist(seat, result)
    (row,) = _prescreen(store, seat.work_id)
    off_verdict = StoredVerdict(work_id=seat.work_id, judge_id=judge.build_id, band=off.band,
                                band_ordinal=off.band_ordinal, cited_spans=tuple(off.cited_spans),
                                evidence_sufficient=off.evidence_sufficient, uncited=off.uncited)
    return (result, prescreen_confirmation(row["reason"]), _stored_cell(store, built, seat),
            off_verdict, judge)


def _assert_arm_b(result, confirmation, verdicts, off_verdict, judge) -> None:
    assert (result.scoring_engine, result.prescreen_outcome, result.band) == (
        "llm", "unconfirmed", REFERENCE)
    assert confirmation == ("unconfirmed_by", judge.build_id, REFERENCE)
    assert [(v.scoring_engine, v.band) for v in verdicts] == [("llm", REFERENCE)]
    score = _aggregate(verdicts)
    assert (score.state, score.routing) == ("provisional_unreviewed", "provisional")
    off_score = _aggregate((off_verdict,))
    # Differential: the unconfirmed cell IS an engine-off single verdict, escalation included.
    assert _score_fields(score) == _score_fields(off_score)
    assert _score_fields(score)[-1] == "one_grader_unsure"
    assert _escalation(score) == _escalation(off_score)


def test_tc_judge_47_b_a_disagreeing_judge_makes_the_unit_an_ordinary_llm_verdict(world) -> None:
    _assert_arm_b(*_arm_b(world))


def test_tc_judge_47_mutation_returning_the_decision_unchecked_turns_b_red(world, monkeypatch) -> None:
    """The plan's mutation: `_confirm` still calls the judge but returns the decision without
    comparing bands. Arm (b)'s oracle must reject the result."""
    from aeh.judge import ScoringWorker

    def unchecked(self, request, judge, decision):  # noqa: ANN001
        if self._jev_final_on_accept(request):
            self._dispatch_llm(request, judge)
        return decision

    monkeypatch.setattr(ScoringWorker, "_confirm", unchecked)
    with pytest.raises(AssertionError):
        _assert_arm_b(*_arm_b(world))


# --- (c) the judge fails terminally --------------------------------------------------------------

def test_tc_judge_47_c_a_failed_confirmation_fails_the_unit_and_writes_no_decision(
        world, monkeypatch) -> None:
    from aeh.judge import prescreen_confirmation

    monkeypatch.setenv("HARNESS_JUDGE_MAX_ATTEMPTS", "2")
    store, provider, built, seat, judge, data_dir = world
    config = _config(data_dir, True)
    request = _assemble(store, provider, judge, seat)
    _record_jev(provider, request, config, REFERENCE)  # no judge recording: every attempt misses
    with pytest.raises(Exception) as off_error:
        _worker(store, _Spy(provider), judge, _config(data_dir, None)).dispatch(request, judge)
    with pytest.raises(Exception) as on_error:
        _worker(store, _Spy(provider), judge, config).dispatch(request, judge)
    assert type(on_error.value) is type(off_error.value), "fails as an LLM-path unit does"
    assert store.cohort(ORCH_COHORT_ID).query("SELECT count(*) n FROM verdict")[0]["n"] == 0
    (row,) = _prescreen(store, seat.work_id)
    assert row["outcome"] == "accepted" and prescreen_confirmation(row["reason"]) is None


# --- (d) knob false ------------------------------------------------------------------------------

def test_tc_judge_47_d_knob_false_makes_no_confirmation_call_and_the_decision_stays_provisional(
        world) -> None:
    import aeh.prov

    store, provider, built, seat, judge, data_dir = world
    config = _config(data_dir, False)
    assert config.jev_final_on_accept is False
    request = _assemble(store, provider, judge, seat)
    _record_jev(provider, request, config, REFERENCE)
    _record_judge(provider, request, judge, REFERENCE, built["spans"][seat.submission_id])
    spy = _Spy(provider)
    worker = _worker(store, spy, judge, config)
    records: list = []
    previous = aeh.prov.install_call_journal(records.append)
    try:
        result = worker.dispatch(request, judge)
    finally:
        aeh.prov.install_call_journal(previous)
    assert spy.calls == [] and result.scoring_engine == "decision"
    kinds = [r["kind"] if isinstance(r, dict) else getattr(r, "kind") for r in records]
    assert kinds == ["jev_decision"], kinds
    worker.persist(seat, result)
    score = _aggregate(_stored_cell(store, built, seat), knob=False)
    assert (score.state, score.routing) == ("provisional_unreviewed", "provisional")


# --- (e) byte-identical request ------------------------------------------------------------------

def test_tc_judge_47_e_the_confirmation_request_is_the_engine_off_request(world) -> None:
    store, provider, built, seat, judge, data_dir = world
    config = _config(data_dir, True)
    request = _assemble(store, provider, judge, seat)
    _record_jev(provider, request, config, REFERENCE)
    _record_judge(provider, request, judge, REFERENCE, built["spans"][seat.submission_id])
    off_spy, on_spy = _Spy(provider), _Spy(provider)
    _worker(store, off_spy, judge, _config(data_dir, None)).dispatch(request, judge)
    _worker(store, on_spy, judge, config).dispatch(request, judge)
    assert len(off_spy.calls) == len(on_spy.calls) == 1
    assert on_spy.calls[0] == off_spy.calls[0], "payload, ModelRef and SamplingParams are engine-off's"


# --- forged citation -----------------------------------------------------------------------------

def test_tc_judge_47_forged_citation_with_a_confirming_judge_is_never_a_decision_verdict(world) -> None:
    """#814's reviewer note: an above-gate Jev answer citing span `a` with bytes the document
    never carried, plus a judge recorded to confirm Jev's band. The worker's own citation check
    must refuse it before any confirmation: no decision verdict, nothing final."""
    store, provider, built, seat, judge, data_dir = world
    config = _config(data_dir, True)
    request = _assemble(store, provider, judge, seat)
    first = dict(request.evidence[0])
    first["text"] = first["text"] + " (forged)"
    forged = dataclasses.replace(request, evidence=(first,) + tuple(request.evidence[1:]))
    _record_jev(provider, forged, config, REFERENCE)
    _record_judge(provider, forged, judge, REFERENCE, built["spans"][seat.submission_id])
    spy = _Spy(provider)
    worker = _worker(store, spy, judge, config)
    result = worker.dispatch(forged, judge)
    assert result.scoring_engine == "llm" and result.prescreen_outcome == "below_gate"
    assert len(spy.calls) == 1, "one LLM call: the fallback, not a confirmation"
    (row,) = _prescreen(store, seat.work_id)
    assert (row["outcome"], row["reason"]) == ("below_gate", "citation_unverified")
    worker.persist(seat, result)
    verdicts = _stored_cell(store, built, seat)
    assert [v.scoring_engine for v in verdicts] == ["llm"]
    score = _aggregate(verdicts)
    assert (score.state, score.routing) != ("final", "auto")
