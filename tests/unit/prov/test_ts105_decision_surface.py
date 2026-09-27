"""TS-105 (#458): the M-PROV decision surface. Jev test plan §5 (M-PROV) and §6.

| Case | Asserted |
|---|---|
| TC-PROV-23 | `DecisionRequest` refuses each malformed shape by naming its rule, accepts each edge that is allowed, and `decide` is synchronous |
| TC-PROV-24 | Confidence: reported when present, else `(n·peak−1)/(n−1)`, and `|2p−1|` for a Noul, hand-computed |
| TC-PROV-25 | F-JEV-WIRE's malformed bodies: 3 transport calls, then `MalformedResponseError`, never renormalized; the 1.0009 body is accepted exactly as sent |
| TC-PROV-30 | Fixture `decide` replays exactly, misses on one changed byte or on reordered questions with no socket touched, is not satisfied by a completion fixture, and raises a declared error by type |
| TC-PROV-31 | `decision_provider_for` maps the three decision names and refuses everything else, the LLM provider names included |
| TC-PROV-32 | Declared capabilities per implementation, and the OpenJev max-model-len knob |
| TC-PROV-34 | Decision counters across OK, a 500 retry and a 429 retry, kept apart from the LLM counters in both directions. The `actual_cost` sum of both surfaces is M-ORCH's flush and is asserted by TC-ORCH-51 (TS-111) |
| TC-PROV-35 | One judge-built request through both live providers and the fixture double gives equal answers |
| TC-PROV-47 | A billed response whose `usage.cost` is NaN, infinite or negative is malformed (regression, added to the plan with this file) |
| FUZZ-11 | The parser, and a provider decoding raw (possibly truncated) bytes, return a validated `Decision` or raise `MalformedResponseError`, nothing else, over Score, Choice and Noul answers |
| PERF-14 | The provider overhead per `decide` stays under 5 ms at p95 (20 questions, an 8,000-token state) |

Written against the design's interface as shipped in #440–#442. The CT-PROV-24 counter names
are the design's.
"""

from __future__ import annotations

import inspect
import json
import time
from decimal import Decimal
from pathlib import Path

import pytest

from aeh.conf import ConfigurationError, DecisionEngine, ModelRef
from aeh.prov import (ChoiceQuestion, Completion, DecisionRequest, DecisionRequestError,
                      DecisionRequestRejectedError, FixtureMissingError, HttpResponse,
                      JevOpenRouterProvider, MalformedResponseError, NoulQuestion,
                      OpenJevLocalProvider, PromptPayload, RecordedFixtureProvider, RetryPolicy,
                      RunCountersTracker, SamplingParams, ScoreQuestion, decision_provider_for,
                      decision_request_key, parse_decision)
from tests.support import jev_corpora
from tests.support.clock import FrozenClock
from tests.support.guards import SocketGuard

JEV_REF = ModelRef(role="decision", provider="openrouter-jev",
                   build_id="openrouter/typesafe/jev-1.13@2026-09-17", quantization=None)
OJ_REF = ModelRef(role="decision", provider="openjev",
                  build_id="/models/openjev-FP8/model.safetensors@sha256:" + "ab" * 32,
                  quantization="fp8")
FX_REF = ModelRef(role="decision", provider="fixture",
                  build_id="/models/jev-fixture/model.safetensors@sha256:" + "cd" * 32,
                  quantization="bf16")


def _req(questions, state: str = "### criterion\nx\n\n### submission\ny") -> DecisionRequest:
    return DecisionRequest(state=state, questions=tuple(questions))


def _keys(n: int) -> list[str]:
    """`n` distinct keys matching `[a-z][a-z_]{0,31}` (digits are not allowed)."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    return [f"q{letters[i // 26]}{letters[i % 26]}" for i in range(n)]


class _Transport:
    """Answers each send from a programmed list of `HttpResponse`s (the last one repeats)."""

    def __init__(self, *responses: HttpResponse) -> None:
        self.responses = list(responses)
        self.requests = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.responses) - 1)
        return self.responses[index]


def _ok(body: dict, headers: dict | None = None) -> HttpResponse:
    return HttpResponse(200, headers or {}, json.dumps(body).encode("utf-8"))


# --- TC-PROV-23 --------------------------------------------------------------------------------

@pytest.mark.parametrize("label, build, rule", [
    ("a", lambda: _req([NoulQuestion("band", "x"), NoulQuestion("band", "y")]), "repeats"),
    ("b", lambda: _req([NoulQuestion("cite_1", "x")]), "must match"),
    ("c", lambda: _req([NoulQuestion("Band", "x")]), "must match"),
    ("d", lambda: _req([NoulQuestion("a" * 33, "x")]), "must match"),
    ("e", lambda: _req([ChoiceQuestion("topic", "x", (("a", None),))]), "options"),
    ("f", lambda: _req([ChoiceQuestion("topic", "x", tuple((f"o{c}", None) for c in _keys(256)))]), "options"),
    ("g", lambda: _req([ScoreQuestion("band", "x", ("only",))]), "levels"),
    ("h", lambda: _req([ScoreQuestion("band", "x", tuple("abcdefghijk"))]), "levels"),
    ("i", lambda: _req([NoulQuestion("q", "x")], state=""), "state"),
    ("j", lambda: _req([NoulQuestion(k, "x") for k in _keys(65)]), "64"),
])
def test_tc_prov_23_decision_request_refuses_each_rule(label, build, rule) -> None:
    with pytest.raises(DecisionRequestError) as caught:
        build()
    assert rule in str(caught.value), f"row ({label}) must name its rule: {caught.value}"


def test_tc_prov_23_accept_rows_and_per_backend_option_caps() -> None:
    _req([ScoreQuestion("band", "x", ("a", "b"))])
    _req([ScoreQuestion("band", "x", tuple("abcdefghij"))])
    _req([NoulQuestion("cite_z", "x"), NoulQuestion("a" * 32, "y")])
    _req([NoulQuestion(k, "x") for k in _keys(64)])
    or_caps = JevOpenRouterProvider(api_key="k").decision_capabilities(JEV_REF)
    oj_caps = OpenJevLocalProvider().decision_capabilities(OJ_REF)
    choice = lambda n: _req([ChoiceQuestion("topic", "x", tuple((f"o{c}", None) for c in _keys(n)))])  # noqa: E731
    choice(255).validate_for(or_caps)
    choice(52).validate_for(oj_caps)
    with pytest.raises(DecisionRequestError) as caught:
        choice(53).validate_for(oj_caps)
    assert "option" in str(caught.value)
    for cls in (JevOpenRouterProvider, OpenJevLocalProvider, RecordedFixtureProvider):
        assert not inspect.iscoroutinefunction(cls.decide), f"{cls.__name__}.decide must be synchronous"


# --- TC-PROV-24 --------------------------------------------------------------------------------

def _score_request(levels=("B", "D", "P", "E")):
    return _req([ScoreQuestion("band", "x", tuple(levels))])


def _score_answer(probs, **extra):
    return {"answers": {"band": {"type": "score", "score": sum(i * p for i, p in enumerate(probs)),
                                 "probabilities": {str(i): p for i, p in enumerate(probs)},
                                 "legend": {str(i): l for i, l in enumerate(("B", "D", "P", "E"))},
                                 **extra}}}


def test_tc_prov_24_confidence_is_reported_else_derived_by_hand() -> None:
    probs = (0.05, 0.90, 0.05, 0.0)
    derived = parse_decision(_score_answer(probs), _score_request(), fallback_build="x").answers["band"]
    # (4 * 0.90 - 1) / 3 = 2.6 / 3 = 0.866666...
    assert derived.confidence == pytest.approx(2.6 / 3, abs=1e-9)
    assert derived.confidence_source == "derived"
    assert isinstance(derived.probabilities, tuple) and derived.probabilities[1] == 0.90
    reported = parse_decision(_score_answer(probs, confidence=0.81), _score_request(),
                              fallback_build="x").answers["band"]
    assert (reported.confidence, reported.confidence_source) == (0.81, "reported")
    noul = _req([NoulQuestion("ok", "x")])
    for p, expected in ((0.95, 0.90), (0.5, 0.0), (0.05, 0.90)):  # |2p - 1|
        answer = parse_decision({"answers": {"ok": {"type": "noul", "noul": p}}}, noul,
                                fallback_build="x").answers["ok"]
        # A Noul has no reported confidence on the wire, so its answer carries no source
        # field: `|2p - 1|` is the only value it can hold (CT-PROV-27).
        assert answer.confidence == pytest.approx(expected, abs=1e-9)
    choice = _req([ChoiceQuestion("topic", "x", (("billing", None), ("technical", None)))])
    answer = parse_decision({"answers": {"topic": {"type": "choice", "choice": "billing",
                                                   "probabilities": {"billing": 0.88, "technical": 0.12}}}},
                            choice, fallback_build="x").answers["topic"]
    # (2 * 0.88 - 1) / 1 = 0.76
    assert answer.confidence == pytest.approx(0.76, abs=1e-9) and answer.confidence_source == "derived"
    with pytest.raises(MalformedResponseError):
        parse_decision(_score_answer(probs, confidence=1.2), _score_request(), fallback_build="x")


# --- TC-PROV-25 --------------------------------------------------------------------------------

_MALFORMED = [b for b in jev_corpora.wire_bodies() if b["expect"]["outcome"] == "malformed"]


@pytest.mark.parametrize("entry", _MALFORMED, ids=[b["id"] for b in _MALFORMED])
def test_tc_prov_25_malformed_body_is_retried_then_refused(entry, monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    transport = _Transport(_ok(entry["body"]))
    provider = JevOpenRouterProvider(api_key="k", transport=transport, clock=FrozenClock())
    with pytest.raises(MalformedResponseError):
        provider.decide(jev_corpora.wire_request(entry["request"]), JEV_REF)
    assert len(transport.requests) == 3


def test_tc_prov_25_sum_within_tolerance_is_returned_exactly_as_sent(monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    entry = next(b for b in jev_corpora.wire_bodies() if b["id"] == "cloud-accept-sum-1-0009")
    transport = _Transport(_ok(entry["body"]))
    provider = JevOpenRouterProvider(api_key="k", transport=transport, clock=FrozenClock())
    decision = provider.decide(jev_corpora.wire_request(), JEV_REF)
    assert len(transport.requests) == 1
    assert sum(decision.answers["band"].probabilities) == pytest.approx(1.0009, abs=1e-12)


# --- TC-PROV-30 --------------------------------------------------------------------------------

def _decision_body(request: DecisionRequest) -> dict:
    answers = {}
    for q in request.questions:
        if isinstance(q, ScoreQuestion):
            n = len(q.levels)
            answers[q.key] = {"type": "score", "score": 1.0, "probabilities": {str(i): (1.0 if i == 1 else 0.0) for i in range(n)},
                              "legend": {str(i): l for i, l in enumerate(q.levels)}}
        else:
            answers[q.key] = {"type": "noul", "noul": 0.9}
    return {"model": "jev-fixture", "answers": answers, "usage": {"input_tokens": 10, "output_tokens": 0}}


def test_tc_prov_30_fixture_decide_replays_exactly_and_misses_loudly(tmp_path) -> None:
    provider = RecordedFixtureProvider(fixture_dir=tmp_path)
    request = _req([ScoreQuestion("band", "x", ("a", "b", "c")), NoulQuestion("evidence_sufficient", "y")])
    body = _decision_body(request)
    provider.record_decision(request, FX_REF, body)
    assert provider.decide(request, FX_REF) == parse_decision(body, request, fallback_build=FX_REF.build_id)
    guard = SocketGuard()
    guard.install()
    try:
        for changed in (_req(request.questions, state=request.state + "!"),
                        _req(tuple(reversed(request.questions)), state=request.state)):
            with pytest.raises(FixtureMissingError):
                provider.decide(changed, FX_REF)
    finally:
        guard.uninstall()
    assert guard.attempts == []
    # A completion fixture never answers `decide`, even filed under the decision key: the
    # document's scheme and stored request are checked, not only its filename.
    other = RecordedFixtureProvider(fixture_dir=tmp_path / "completion")
    key = other.record(PromptPayload(fields=(("state", request.state),)), FX_REF, SamplingParams(temperature=0.0),
                       Completion(text="{}", tokens_in=1, tokens_out=1, latency_ms=0,
                                  resolved_build=FX_REF.build_id, cached_prefix_tokens=0, cost=None))
    planted = other._path_for(decision_request_key(request, FX_REF))
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(other._path_for(key).read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(FixtureMissingError):
        other.decide(request, FX_REF)
    rejected = _req([NoulQuestion("ok", "x")], state="rejected state")
    provider.record_decision(rejected, FX_REF, error=("DecisionRequestRejectedError", "HTTP 422"))
    with pytest.raises(DecisionRequestRejectedError):
        provider.decide(rejected, FX_REF)


# --- TC-PROV-31 --------------------------------------------------------------------------------

def test_tc_prov_31_decision_provider_for_maps_decision_names_only(tmp_path) -> None:
    def ref(name: str) -> ModelRef:
        return ModelRef(role="decision", provider=name, build_id="b", quantization=None) if name else \
            type("Ref", (), {"provider": ""})()

    assert type(decision_provider_for(ref("openrouter-jev"), api_key="k")) is JevOpenRouterProvider
    assert type(decision_provider_for(ref("openjev"))) is OpenJevLocalProvider
    assert type(decision_provider_for(ref("fixture"), fixture_dir=tmp_path)) is RecordedFixtureProvider
    for name in ("openrouter", "local", ""):
        with pytest.raises(ConfigurationError):
            decision_provider_for(ref(name))


# --- TC-PROV-32 --------------------------------------------------------------------------------

def test_tc_prov_32_declared_capabilities_and_the_model_len_knob(monkeypatch) -> None:
    c = JevOpenRouterProvider(api_key="k").decision_capabilities(JEV_REF)
    assert (c.max_context_tokens, c.max_choice_options, c.max_questions, c.deterministic) == (32000, 255, 64, True)
    assert c.cost_per_input_token == Decimal("0.042") / Decimal(1_000_000)
    oj = OpenJevLocalProvider()
    o = oj.decision_capabilities(OJ_REF)
    assert (o.max_context_tokens, o.max_choice_options, o.max_questions, o.cost_per_input_token,
            o.deterministic) == (16384, 52, 64, None, True)
    monkeypatch.setenv("HARNESS_OPENJEV_MAX_MODEL_LEN", "8192")
    assert oj.decision_capabilities(OJ_REF).max_context_tokens == 8192
    monkeypatch.setenv("HARNESS_OPENJEV_MAX_MODEL_LEN", "32000")
    assert oj.decision_capabilities(OJ_REF).max_context_tokens == 16384
    monkeypatch.setenv("HARNESS_OPENJEV_MAX_MODEL_LEN", "x")
    with pytest.raises(ConfigurationError):
        oj.decision_capabilities(OJ_REF)


# --- TC-PROV-34 --------------------------------------------------------------------------------

def test_tc_prov_34_decision_counters_are_their_own(monkeypatch) -> None:
    """Hand-summed: three decide calls; tokens_in 1200 each = 3600; transport retries 2 (the
    500 on call 2 and the 429 on call 3); rate-limited calls 1 (call 3); decision cost
    3 × 0.0000504 = 0.0001512 (usage.cost as the vendor reports it). The LLM `transport_retries`
    stays 0: a decision retry never moves the LLM counters TC-PROV-18 pins. The run's
    `actual_cost` (0.02 of LLM spend plus this) is summed by M-ORCH, not here."""
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    request = jev_corpora.wire_request()
    good = next(b for b in jev_corpora.wire_bodies() if b["id"] == "cloud-well-formed-derived")["body"]
    body = {**good, "usage": {"input_tokens": 1200, "output_tokens": 0, "cost": 0.0000504}}
    transport = _Transport(
        _ok(body),
        HttpResponse(500, {}, b"{}"), _ok(body),
        HttpResponse(429, {"Retry-After": "1"}, b"{}"), _ok(body))
    counters = RunCountersTracker()
    provider = JevOpenRouterProvider(api_key="k", transport=transport, clock=FrozenClock(), counters=counters)
    for _ in range(3):
        provider.decide(request, JEV_REF)
    snap = counters.decision_snapshot()
    assert (snap.decision_calls, snap.decision_tokens_in, snap.decision_transport_retries,
            snap.decision_rate_limited_calls) == (3, 3600, 2, 1)
    assert snap.decision_actual_cost == Decimal("0.0001512")
    assert counters.snapshot().transport_retries == 0
    # And the other direction: LLM traffic on the shared tracker (two completions, one of them
    # retried) moves no decision counter.
    counters.on_retry()
    counters.on_usage(100, 10, 0)
    counters.on_usage(100, 10, 0)
    assert counters.decision_snapshot() == snap


# --- TC-PROV-35 --------------------------------------------------------------------------------

def test_tc_prov_35_one_request_three_implementations_equal_answers(tmp_path) -> None:
    from aeh.judge import decision_request

    cell, scoring = next(iter(jev_corpora.f_jev_requests().values()))
    engine = DecisionEngine(model=FX_REF, confidence_threshold=Decimal("0.80"),
                            cite_threshold=Decimal("0.50"), max_citation_questions=16,
                            token_bytes_ratio=3)
    request = decision_request(scoring, engine)
    body = jev_corpora.answer_document(request, cell["answers"]["cloud"], "typesafe/jev-1.13-20260917")
    via_or = JevOpenRouterProvider(api_key="k", transport=_Transport(_ok(body)), clock=FrozenClock()).decide(request, JEV_REF)
    via_oj = OpenJevLocalProvider(transport=_Transport(_ok(body)), clock=FrozenClock()).decide(request, OJ_REF)
    fixture = RecordedFixtureProvider(fixture_dir=tmp_path)
    fixture.record_decision(request, FX_REF, body)
    via_fx = fixture.decide(request, FX_REF)
    assert via_or.answers == via_oj.answers == via_fx.answers
    assert (via_or.tokens_in, via_or.tokens_out) == (via_oj.tokens_in, via_oj.tokens_out) == (
        via_fx.tokens_in, via_fx.tokens_out)


# --- FUZZ-11 -----------------------------------------------------------------------------------

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
except ImportError:  # pragma: no cover
    given = None


if given is not None:
    _json = st.recursive(
        st.none() | st.booleans() | st.integers(-5, 5) | st.floats(allow_nan=True) | st.text(max_size=6),
        lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=6), inner, max_size=4),
        max_leaves=12)

    @pytest.mark.property
    @settings(max_examples=300, deadline=None)
    @given(st.one_of(
        _json,
        st.builds(lambda p: _score_answer(p), st.lists(
            st.floats(-1, 2) | st.just(float("nan")) | st.just(float("inf")), min_size=4, max_size=4)),
        st.builds(lambda s: {"answers": {"band": s}}, _json),
    ))
    def test_fuzz_11_the_parser_validates_or_refuses_nothing_else(document) -> None:
        request = _score_request()
        try:
            decision = parse_decision(document, request, fallback_build="x")
        except MalformedResponseError:
            return
        answer = decision.answers["band"]
        assert set(decision.answers) == {"band"}
        assert len(answer.probabilities) == 4
        assert abs(sum(answer.probabilities) - 1.0) <= 0.001
        assert all(0.0 <= p <= 1.0 for p in answer.probabilities)


    _MIXED = DecisionRequest(state="s", questions=(
        ChoiceQuestion("topic", "x", (("friction", None), ("normal", None))),
        ScoreQuestion("band", "x", ("B", "D", "P", "E")),
        NoulQuestion("ok", "x")))
    _GOOD = json.dumps({"model": "typesafe/jev-1.13", "usage": {"input_tokens": 3, "output_tokens": 0}, "answers": {
        "topic": {"type": "choice", "choice": "friction", "probabilities": {"friction": 0.7, "normal": 0.3}},
        "band": {"type": "score", "score": 2.0, "probabilities": {"0": 0.1, "1": 0.1, "2": 0.7, "3": 0.1},
                 "legend": {"0": "B", "1": "D", "2": "P", "3": "E"}},
        "ok": {"type": "noul", "noul": 0.8}}}).encode()

    @pytest.mark.property
    @settings(max_examples=200, deadline=None)
    @given(st.one_of(
        st.integers(0, len(_GOOD)).map(lambda n: _GOOD[:n]),
        st.binary(max_size=64),
        st.tuples(st.integers(0, len(_GOOD) - 1), st.integers(0, 255)).map(
            lambda t: _GOOD[:t[0]] + bytes([t[1]]) + _GOOD[t[0] + 1:]),
    ))
    def test_fuzz_11_raw_bytes_through_a_provider_validate_or_refuse(raw) -> None:
        provider = JevOpenRouterProvider(api_key="k", transport=_Transport(HttpResponse(200, {}, raw)),
                                         clock=FrozenClock(), policy=RetryPolicy(max_attempts=1))
        try:
            decision = provider.decide(_MIXED, JEV_REF)
        except MalformedResponseError:
            return
        assert set(decision.answers) == {"topic", "band", "ok"}
        assert abs(sum(decision.answers["band"].probabilities) - 1.0) <= 0.001
        assert abs(sum(decision.answers["topic"].probabilities.values()) - 1.0) <= 0.001
        assert 0.0 <= decision.answers["ok"].p_true <= 1.0


# --- TC-PROV-47 (regression) -------------------------------------------------------------------

@pytest.mark.parametrize("cost", ["NaN", "Infinity", -1, "-0.0001"])
def test_tc_prov_47_a_non_finite_or_negative_cost_is_malformed(cost, monkeypatch) -> None:
    """Found in review of TS-105: `usage.cost` of NaN, ±Infinity or a negative number was
    accepted as `Decision.cost` and would poison `decision_actual_cost` and the ceiling."""
    monkeypatch.setenv("HARNESS_RETRY_MAX", "1")
    good = next(b for b in jev_corpora.wire_bodies() if b["id"] == "cloud-well-formed-derived")["body"]
    body = {**good, "usage": {"input_tokens": 10, "output_tokens": 0, "cost": cost}}
    provider = JevOpenRouterProvider(api_key="k", transport=_Transport(_ok(body)), clock=FrozenClock())
    with pytest.raises(MalformedResponseError):
        provider.decide(jev_corpora.wire_request(), JEV_REF)


# --- PERF-14 -----------------------------------------------------------------------------------

@pytest.mark.slow
def test_perf_14_provider_overhead_under_5ms_at_p95() -> None:
    """1,000 `decide` calls, 20 questions, an ~8,000-token state (~24 kB at 3 bytes per token),
    zero-latency transport: the harness's own per-call overhead has a p95 under 5 ms."""
    questions = [ScoreQuestion("band", "x", ("a", "b", "c", "d"))] + [NoulQuestion(k, "x") for k in _keys(19)]
    request = _req(questions, state="### submission\n" + "the crate rests on the ramp. " * 830)
    body = {"model": "typesafe/jev-1.13-20260917", "answers": {
        q.key: ({"type": "score", "score": 1.0, "probabilities": {"0": 0.0, "1": 1.0, "2": 0.0, "3": 0.0},
                 "legend": {"0": "a", "1": "b", "2": "c", "3": "d"}} if isinstance(q, ScoreQuestion)
                else {"type": "noul", "noul": 0.9}) for q in questions},
        "usage": {"input_tokens": 8000, "output_tokens": 0}}
    response = _ok(body)
    provider = JevOpenRouterProvider(api_key="k", transport=_Transport(response), clock=FrozenClock())
    samples = []
    for _ in range(1000):
        start = time.perf_counter()
        provider.decide(request, JEV_REF)
        samples.append(time.perf_counter() - start)
    samples.sort()
    assert samples[949] < 0.005, f"p95 overhead {samples[949] * 1000:.2f} ms"
