"""TS-114 (#467): CT-JUDGE v2.0, the decision-engine clauses. Jev test plan §6.11.3.

The per-requirement cases these clauses reuse live in TS-109 (rung 0) and TS-110 (rung 2). This
suite adds what each clause itself names: the census, the consumer sweep, the whole-run
checks over F-JEV-DECISIONS / F-JEV-SYNTH, and the adversarial constructions.

| Case | Clause | Asserted |
|---|---|---|
| TC-JUDGE-C05 | data | A decision `ScoringResult` exposes the reply fields in `REPLY_FIELDS` order, and its only free text is the flagged inventory |
| TC-JUDGE-C07 | behaviour | Decision confidence is only the 0.25-weighted concern term: 0.99 vs 0.81 changes neither escalation nor reasons, and aggregation takes no gate input |
| TC-JUDGE-C12 | state | Write census: the decision seat's dispatch and persist write only `verdict` and `decision_prescreen` |
| TC-JUDGE-C17 | behaviour (non-promise) | Two decide fixture sets answering byte-identical requests differently: both runs complete, and no consumer keys on the decision request hash |
| TC-JUDGE-C21 | behaviour | Whole-run seat census: at most one decision verdict per cell, and every one is `panel[0]`'s |
| TC-JUDGE-C22 | behaviour | Strict `>` gate; the fallback payload is engine-off's |
| TC-JUDGE-C23 | data | Band is the argmax, not `score`; cited spans are the request's own objects; inventory flag present |
| TC-JUDGE-C24 | data | Every verdict names its engine; `verdicts_for` exposes it; NULL reads `llm` |
| TC-JUDGE-C25 | error | Outage propagates without a strike; every confidence outcome ends in an LLM verdict, never a quarantine |
| TC-JUDGE-C26 | behaviour | Redelivery never calls `decide` again, for any outcome |
| TC-JUDGE-C27 | security | Every captured decision request in a whole engine-on run carries no student bytes in any question string, and its keys depend on span count only (the scan itself runs inside dispatch before every `decide`: TC-JUDGE-32) |
| TC-JUDGE-C28 | observe | `decision_engine_metrics`' names are exactly CT-JUDGE-28's |
| TC-JUDGE-C29 | perf | Per seat over F-JEV-DECISIONS: at most one `decide`, at most one LLM call (no strikes in the corpus) |
| TC-JUDGE-C30 | security | No prompt-assembling path reads `evidence_assessment`; no payload in an engine-on run carries `band probabilities:` |
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
from pathlib import Path

import pytest

from aeh.judge import (DECISION_ENGINE_INVENTORY, REPLY_FIELDS, Accepted, BelowGate, decision_engine_metrics,
                       gate_decision)
from tests.support.conf_builders import edge_panel

pytestmark = pytest.mark.contract
SRC = Path(__file__).resolve().parents[3] / "src" / "aeh"


def _ts109():
    from tests.unit.judge import test_ts109_decision_logic as m
    return m


def _ts110():
    from tests.integration.judge import test_ts110_decision_dispatch as m
    return m


# --- TC-JUDGE-C05 / C23 ------------------------------------------------------------------------

def test_tc_judge_c05_the_decision_result_keeps_the_reply_shape() -> None:
    from aeh.judge import _verdict_of
    from aeh.prov import MalformedResponseError

    m = _ts109()
    request = m._request(3)
    result = gate_decision(m._decision([.02, .02, .94, .02]), request, m._engine()).result
    reply = {name: getattr(result, name) for name in REPLY_FIELDS}  # every reply field, contract order
    assert list(reply) == list(REPLY_FIELDS) and None not in (reply["band"], reply["self_confidence"])
    assert result.evidence_assessment.startswith("engine: ") and DECISION_ENGINE_INVENTORY in result.integrity_flags
    # The LLM arm is unchanged: a reply whose fields arrive out of order is refused.
    ordered = {"cited_spans": [], "evidence_assessment": "x", "evidence_sufficient": True,
               "band": "Proficient", "self_confidence": 0.7}
    reordered = {k: ordered[k] for k in ("band", "cited_spans", "evidence_assessment", "evidence_sufficient",
                                         "self_confidence")}
    with pytest.raises(MalformedResponseError):
        _verdict_of(json.dumps(reordered), request)


def test_tc_judge_c23_argmax_band_and_the_requests_own_spans() -> None:
    m = _ts109()
    request = m._request(3)
    exemplary = gate_decision(m._decision([.45, 0, 0, .55], reported=0.9, p_suff=0.99, score=1.65), request, m._engine())
    assert isinstance(exemplary, Accepted) and exemplary.result.band_ordinal == 3, "argmax, not round(score)"
    result = gate_decision(m._decision([.02, .02, .94, .02]), request, m._engine()).result
    assert all(any(span is own for own in request.evidence) for span in result.cited_spans), \
        "cited spans are the request's own objects, not rebuilt"


# --- TC-JUDGE-C07 ------------------------------------------------------------------------------

def test_tc_judge_c07_decision_confidence_is_only_the_weighted_concern() -> None:
    import inspect

    from aeh.agg import AGG_ESCALATION_SELF_CONFIDENCE_WEIGHT, aggregate, should_escalate
    from tests.support.agg_vocabulary import (band, criterion, criterion_history, expected_distribution,
                                              favourable_signals, verdict)

    from types import SimpleNamespace

    # An edge band (no interior-band signal), favourable signals, no history and a baseline centred
    # on the band leave the confidence term as the only concern: WEIGHT × (1 − self_confidence),
    # 0.25 × 0.01 = 0.0025 at 0.99 and 0.25 × 0.19 = 0.0475 at 0.81 (0.045 apart).
    assert AGG_ESCALATION_SELF_CONFIDENCE_WEIGHT == 0.25
    crit = criterion([band("B", 0, 0.0), band("D", 1, 1.0), band("P", 2, 2.0), band("E", 3, 3.0)])
    history, baseline = criterion_history(), expected_distribution(mean=3.0, std=0.5)

    def escalation(confidence, threshold):
        # The score as `should_escalate` reads it: an edge band (ordinal 3 of 4), no other field.
        score = SimpleNamespace(ordinal=3, band_count=4, self_confidence=confidence)
        return should_escalate(score, crit, history, baseline, config=SimpleNamespace(escalation_threshold=threshold))

    # Between the two concerns only the 0.81 score crosses; above both, neither.
    assert escalation(0.81, 0.03).escalate and not escalation(0.99, 0.03).escalate
    assert not escalation(0.81, 0.05).escalate
    assert escalation(0.81, 0.03).reasons == (), "confidence shapes the concern, never a reason"
    # The engine label carries no extra weight: decision- and LLM-labelled twins aggregate alike.
    for confidence in (0.99, 0.81):
        twins = []
        for engine in ("decision", "llm"):
            v = verdict("E", 3, self_confidence=confidence)
            v.scoring_engine = engine
            twins.append(aggregate([v], crit, favourable_signals()))
        assert twins[0] == twins[1]
    for fn in (aggregate, should_escalate):
        params = set(inspect.signature(fn).parameters)
        assert not params & {"gate", "decision", "prescreen", "decision_engine"}, fn.__name__


# --- TC-JUDGE-C12 ------------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize("outcome", ["below_threshold", "accepted"])
def test_tc_judge_c12_the_seat_writes_only_verdict_and_prescreen(outcome, tmp_data_dir, make_fixture_provider, monkeypatch) -> None:
    from aeh.judge import ScoringWorker

    m = _ts110()
    store, provider, world, units = m._world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = m._seat_unit(units, refs)
        request = m._record_llm(provider, store, unit, refs[0], world)
        handle = store.cohort(m.ORCH_COHORT_ID)

        def counts():
            tables = [r["name"] for r in handle.query("SELECT name FROM sqlite_master WHERE type = 'table'")]
            return {t: handle.query(f"SELECT count(*) n FROM \"{t}\"")[0]["n"] for t in tables}

        before = counts()
        answer = m._accepted if outcome == "accepted" else m.FALLBACKS["below_threshold"][0]
        worker = ScoringWorker(store, provider, refs[0], decision_provider=m._Decider(answer),
                               run_config=m._engine_config(tmp_data_dir))
        worker.persist(unit, worker.dispatch(request, refs[0]))
        changed = {t for t, n in counts().items() if n != before.get(t)}
        assert changed <= {"verdict", "decision_prescreen", "run_metrics"}, changed
        assert {"verdict", "decision_prescreen"} <= changed
    finally:
        store.close()


# --- TC-JUDGE-C17 (non-promise) ----------------------------------------------------------------

@pytest.mark.integration
def test_tc_judge_c17_no_consumer_assumes_the_engine_is_deterministic(tmp_path) -> None:
    from aeh.prov import decision_request_key
    from tests.support import pipe_world

    # Static: nothing outside M-PROV keys, caches or compares by the decision request hash.
    for path in SRC.glob("*.py"):
        if path.name != "prov.py":
            assert "decision_request_key" not in path.read_text(encoding="utf-8"), path.name
    # Set 2: the same recordings, with C1/S2's below-gate answer replaced by an accepted one.
    set_two = tmp_path / "set-two"
    shutil.copytree(pipe_world.jev_decisions_dir(), set_two)
    changed = 0
    for path in set_two.glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        band = (doc.get("response") or {}).get("answers", {}).get("band")
        if band and band.get("confidence") == 0.62:
            band["confidence"] = 0.95
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            changed += 1
    assert changed == 1
    outcomes = []
    for name, recordings in (("one", pipe_world.jev_decisions_dir()), ("two", set_two)):
        world = pipe_world.replay_world(tmp_path / name, recordings=recordings, decision_engine=True)
        world.build_run()
        world.start_run()
        result = pipe_world.drive_composed(world)
        assert result.status == "complete", name
        outcomes.append(sorted(r["outcome"] for r in world.handle.query("SELECT outcome FROM decision_prescreen")))
        world.store.close()
    assert outcomes[0] != outcomes[1], "the two sets really answered differently"


# --- TC-JUDGE-C21 ------------------------------------------------------------------------------

_SEAT_CENSUS = ("SELECT w.run_id, w.submission_id, w.criterion_id FROM verdict v JOIN work_unit w ON "
                "w.work_id = v.work_id WHERE v.scoring_engine = 'decision' GROUP BY 1, 2, 3 HAVING count(*) > 1")


@pytest.mark.integration
@pytest.mark.parametrize("corpus", ["decisions", "synth"])
def test_tc_judge_c21_at_most_one_decision_verdict_per_cell_on_the_first_arm(corpus, tmp_path) -> None:
    from tests.support import pipe_world

    world = (pipe_world.jev_replay_world if corpus == "decisions" else pipe_world.jev_synth_replay_world)(tmp_path / "d")
    try:
        world.build_run()
        world.start_run()
        pipe_world.drive_composed(world)
        assert world.handle.query(_SEAT_CENSUS) == []
        judges = {r["judge"] for r in world.handle.query("SELECT judge_id AS judge FROM verdict WHERE scoring_engine = 'decision'")}
        assert judges == {world.resolved.panel[0].build_id}
    finally:
        world.store.close()


# --- TC-JUDGE-C22 / C25 / C26 ------------------------------------------------------------------

def test_tc_judge_c22_the_gate_is_strict() -> None:
    m = _ts109()
    at = gate_decision(m._decision([.05, .05, .85, .05], reported=0.80, p_suff=0.995), m._request(), m._engine())
    assert isinstance(at, BelowGate) and at.reason == "below_threshold"


@pytest.mark.integration
def test_tc_judge_c22_the_fallback_payload_is_engine_offs(tmp_data_dir, make_fixture_provider) -> None:
    """Adversarial construction: a `prescreen_hint` field appended at `prompt_fields` time on
    fallback would make the two payloads differ."""
    from aeh.judge import ScoringWorker

    m = _ts110()
    store, provider, world, units = m._world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = m._seat_unit(units, refs)
        request = m._record_llm(provider, store, unit, refs[0], world)
        off, on = m._LLMSpy(provider), m._LLMSpy(provider)
        ScoringWorker(store, off, refs[0], run_config=m._off_config()).dispatch(request, refs[0])
        ScoringWorker(store, on, refs[0], decision_provider=m._Decider(m.FALLBACKS["argmax_tie"][0]),
                      run_config=m._engine_config(tmp_data_dir)).dispatch(request, refs[0])
        assert on.calls[0][0] == off.calls[0][0]
        assert [name for name, _ in on.calls[0][0].fields] == [name for name, _ in off.calls[0][0].fields]
    finally:
        store.close()


@pytest.mark.integration
@pytest.mark.parametrize("name", ["below_threshold", "argmax_tie", "rejected", "malformed"])
def test_tc_judge_c25_every_confidence_outcome_ends_in_an_llm_verdict(name, tmp_data_dir, make_fixture_provider) -> None:
    """The inverse arm; the outage arm (same class out, no LLM call, no strike) is TC-JUDGE-38."""
    from aeh.judge import ScoringWorker

    m = _ts110()
    store, provider, world, units = m._world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = m._seat_unit(units, refs)
        request = m._record_llm(provider, store, unit, refs[0], world)
        worker = ScoringWorker(store, provider, refs[0], decision_provider=m._Decider(m.FALLBACKS[name][0]),
                               run_config=m._engine_config(tmp_data_dir))
        result = worker.dispatch(request, refs[0])
        worker.persist(unit, result)
        assert result.scoring_engine == "llm"
        assert store.cohort(m.ORCH_COHORT_ID).query(
            "SELECT status FROM work_unit WHERE work_id = :w", w=unit.work_id)[0]["status"] != "quarantined"
    finally:
        store.close()


@pytest.mark.integration
@pytest.mark.parametrize("name", ["below_threshold", "rejected", "malformed", "ineligible", "accepted"])
def test_tc_judge_c26_redelivery_never_samples_the_engine_again(name, tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker

    m = _ts110()
    store, provider, world, units = m._world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = m._seat_unit(units, refs)
        request = m._record_llm(provider, store, unit, refs[0], world)
        answer, caps = (m._accepted, m.FIXTURE_CAPS) if name == "accepted" else m.FALLBACKS[name][:2]
        config = m._engine_config(tmp_data_dir)
        ScoringWorker(store, provider, refs[0], decision_provider=m._Decider(answer, caps=caps),
                      run_config=config).dispatch(request, refs[0])
        again = m._Decider(m._accepted)
        ScoringWorker(store, provider, refs[0], decision_provider=again, run_config=config).dispatch(request, refs[0])
        assert again.calls == 0
    finally:
        store.close()


# --- TC-JUDGE-C24 ------------------------------------------------------------------------------

@pytest.mark.integration
def test_tc_judge_c24_every_verdict_names_its_engine(tmp_data_dir, make_fixture_provider) -> None:
    from aeh.judge import ScoringWorker, verdicts_for

    m = _ts110()
    store, provider, world, units = m._world(tmp_data_dir, make_fixture_provider)
    try:
        refs = edge_panel(3)
        unit = m._seat_unit(units, refs)
        request = m._record_llm(provider, store, unit, refs[0], world)
        worker = ScoringWorker(store, provider, refs[0], run_config=m._off_config())
        worker.persist(unit, worker.dispatch(request, refs[0]))
        handle = store.cohort(m.ORCH_COHORT_ID)
        (stored,) = verdicts_for(handle, world["run_id"], unit.submission_id, "C1")
        assert stored.scoring_engine == "llm"
        with handle.transaction() as tx:
            tx.execute("UPDATE verdict SET scoring_engine = NULL WHERE work_id = :w", w=unit.work_id)
        (legacy,) = verdicts_for(handle, world["run_id"], unit.submission_id, "C1")
        assert legacy.scoring_engine == "llm", "a pre-delta NULL reads as the LLM path, never decision"
    finally:
        store.close()


# --- TC-JUDGE-C27 / C29 / C30 (whole engine-on run) --------------------------------------------

class _Capturing:
    def __init__(self, inner):
        self._inner = inner
        self.requests = []
        self.payloads = []

    def decide(self, request, model_ref):
        self.requests.append(request)
        return self._inner.decide(request, model_ref)

    def complete(self, payload, model_ref, params):
        self.payloads.append((payload, model_ref))
        return self._inner.complete(payload, model_ref, params)

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.fixture(scope="module")
def engine_on_run(tmp_path_factory):
    from tests.support import pipe_world

    world = pipe_world.jev_replay_world(tmp_path_factory.mktemp("c27"))
    capture = _Capturing(world.provider)
    world.provider = capture
    world.build_run()
    world.start_run()
    result = pipe_world.drive_composed(world, decision_provider=capture)
    yield world, capture, result
    world.store.close()


@pytest.mark.integration
def test_tc_judge_c27_every_decision_request_is_isolated_and_scanned(engine_on_run) -> None:
    world, capture, _ = engine_on_run
    assert capture.requests, "the run pre-screened its seats"
    by_spans = {}
    for request in capture.requests:
        cites = [q.key for q in request.questions if q.key.startswith("cite_")]
        keys = [q.key for q in request.questions]
        assert keys == ["band", "evidence_sufficient", *cites]
        by_spans.setdefault(len(cites), set()).add(tuple(keys))
        # The student's bytes: every line of the fenced submission (spans and prose alike).
        fenced = request.state.split("### submission\n", 1)[1]
        student_lines = [line.strip() for line in fenced.splitlines()
                         if len(line.strip()) >= 20 and "untrusted_student_content" not in line]
        assert student_lines
        strings = [q.instructions for q in request.questions]
        strings += [lvl for q in request.questions for lvl in getattr(q, "levels", ())]
        strings += [getattr(q, "when_true", None) or "" for q in request.questions]
        strings += [getattr(q, "when_false", None) or "" for q in request.questions]
        for line in student_lines:
            probe = line[:20]
            assert all(probe not in text for text in strings), f"student bytes {probe!r} in a question string"
    assert all(len(v) == 1 for v in by_spans.values()), "keys are a function of span count only"


@pytest.mark.integration
def test_tc_judge_c29_one_decide_and_at_most_one_llm_call_per_seat(engine_on_run) -> None:
    world, capture, _ = engine_on_run
    seat = world.resolved.panel[0].build_id
    per_cell = {}
    for request in capture.requests:
        key = re.search(r"criterion_id:\s*(\S+)", request.state).group(1), re.search(
            r"Page\s+\d+\s+of\s+\d+\s+-\s+(\S+)", request.state).group(1)
        per_cell[key] = per_cell.get(key, 0) + 1
    assert per_cell and max(per_cell.values()) == 1
    seat_calls = {}
    for payload, ref in capture.payloads:
        if getattr(ref, "build_id", None) == seat and getattr(ref, "role", "") == "judge":
            fields = dict(payload.fields)
            key = (re.search(r"criterion_id:\s*(\S+)", fields.get("criterion", "")).group(1),
                   re.search(r"Page\s+\d+\s+of\s+\d+\s+-\s+(\S+)", fields.get("submission", "")).group(1))
            seat_calls[key] = seat_calls.get(key, 0) + 1
    assert seat_calls and max(seat_calls.values()) == 1


@pytest.mark.integration
def test_tc_judge_c30_no_prompt_carries_the_inventory(engine_on_run) -> None:
    for module in ("extract.py", "synth.py", "ingest.py"):
        assert "evidence_assessment" not in (SRC / module).read_text(encoding="utf-8"), module
    judge_source = (SRC / "judge.py").read_text(encoding="utf-8")
    for fn in ("def prompt_fields", "def decision_fields"):
        body = judge_source[judge_source.index(fn):]
        body = body[:body.index("\ndef ", 1)]
        assert "evidence_assessment" not in body, fn
    world, capture, _ = engine_on_run
    for payload, _ref in capture.payloads:
        assert all("band probabilities:" not in str(value) for _, value in payload.fields)
    assert all("band probabilities:" not in r.state for r in capture.requests)


# --- TC-JUDGE-C28 ------------------------------------------------------------------------------

def test_tc_judge_c28_the_metric_names_are_the_contracts() -> None:
    from aeh.judge import DecisionEngineMetrics

    names = {f.name for f in dataclasses.fields(DecisionEngineMetrics)} - {"per_criterion", "decision_gate_histogram"}
    assert names == {"decision_prescreens", "decision_accepted", "decision_below_gate", "decision_ineligible",
                     "decision_ineligible_reasons", "decision_rejected", "decision_malformed",
                     "decision_accepted_rate", "decision_fallback_rate", "decision_latency_p50_ms",
                     "decision_latency_p95_ms", "decision_fallback_rate_high", "decision_requests_rejected"}
