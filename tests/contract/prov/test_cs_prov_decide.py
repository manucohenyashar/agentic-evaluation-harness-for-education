"""TS-112 (#465): the CS-PROV-DECIDE clause suite. Jev test plan §6.11.1, CT-PROV-17…25.

Each clause runs against all three decision implementations, so the double is held to the
contract the live providers keep (§4.9): `JevOpenRouterProvider` and `OpenJevLocalProvider`
over a programmed transport, and `RecordedFixtureProvider` over recorded documents and
declared errors. The safety-property clauses (C21, C22, C25) carry the adversarial
constructions the plan names.

| Case | Clause | Asserted |
|---|---|---|
| TC-PROV-C17 | surface | `decide` is synchronous and returns a `Decision`; one call is one send; capabilities, estimate and verify_retention send nothing |
| TC-PROV-C18 | data | TC-PROV-25's malformed shapes refused by all three; a malformed stored answer is refused by the double, not replayed |
| TC-PROV-C19 | behaviour | TC-PROV-24's confidence rows on all three |
| TC-PROV-C20 | error | TC-PROV-28's status table on all three (the double through declared errors); a failed call counts no decision |
| TC-PROV-C21 | behaviour | No engine substitution: a raising `decide` never reaches any `complete`; a parsed Decision is never re-requested |
| TC-PROV-C22 | behaviour | Local stays local; cloud never floats; `allow_fallbacks: false` in every body |
| TC-PROV-C23 | behaviour | A fixture miss never reaches the network |
| TC-PROV-C24 | observe | The five counter names, exactly |
| TC-PROV-C25 | security | The decision model sits under the retention gate (rung 1; rung 3 is TC-PIPE-16) |
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from decimal import Decimal

import pytest

from aeh.conf import ConfigurationError, ModelRef
from aeh.prov import (CallPlan, Decision, DecisionCounters, DecisionRequestRejectedError, FixtureMissingError,
                      HttpResponse, JevOpenRouterProvider, MalformedResponseError, NoulQuestion,
                      OpenJevLocalProvider, ProviderUnavailableError, RecordedFixtureProvider,
                      RetentionPolicyError, RunCountersTracker, ScoreQuestion, DecisionRequest)
from tests.support import jev_corpora
from tests.support.clock import FrozenClock

pytestmark = pytest.mark.contract

JEV_REF = ModelRef(role="decision", provider="openrouter-jev",
                   build_id="openrouter/typesafe/jev-1.13@2026-09-17", quantization=None)
OJ_REF = ModelRef(role="decision", provider="openjev",
                  build_id="/models/openjev-FP8/model.safetensors@sha256:" + "ab" * 32, quantization="fp8")
FX_REF = ModelRef(role="decision", provider="fixture",
                  build_id="/models/jev-fixture/model.safetensors@sha256:" + "cd" * 32, quantization="bf16")
WIRE = {b["id"]: b for b in jev_corpora.wire_bodies()}
IMPLEMENTATIONS = ["openrouter-jev", "openjev", "fixture"]


class _Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        return self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]


def _ok(body):
    return HttpResponse(200, {}, json.dumps(body).encode())


def _wire_kind(name):
    return "cloud" if name == "openrouter-jev" else "edge"


def _live(name, transport, counters=None):
    if name == "openrouter-jev":
        return JevOpenRouterProvider(api_key="k", transport=transport, clock=FrozenClock(), counters=counters), JEV_REF
    return OpenJevLocalProvider(transport=transport, clock=FrozenClock(), counters=counters), OJ_REF


def _decide_body(name, body, request, tmp_path):
    """One `decide` over `body` through implementation `name`; returns (decision, sends)."""
    if name == "fixture":
        fixture = RecordedFixtureProvider(fixture_dir=tmp_path)
        fixture.record_decision(request, FX_REF, {k: v for k, v in body.items() if k != "usage"} | {
            "usage": {"input_tokens": 1, "output_tokens": 0}})
        return fixture.decide(request, FX_REF), 0
    transport = _Transport(_ok(body))
    provider, ref = _live(name, transport)
    return provider.decide(request, ref), len(transport.requests)


# --- TC-PROV-C17 -------------------------------------------------------------------------------

@pytest.mark.parametrize("name", IMPLEMENTATIONS)
def test_tc_prov_c17_surface(name, tmp_path) -> None:
    body = WIRE[f"{_wire_kind(name)}-well-formed-derived"]["body"]
    decision, sends = _decide_body(name, body, jev_corpora.wire_request(), tmp_path)
    assert isinstance(decision, Decision)
    if name != "fixture":
        assert sends == 1
        transport = _Transport(_ok(body))
        provider, ref = _live(name, transport)
        provider.decision_capabilities(ref)
        provider.estimate_cost(CallPlan(1, 100, 0))
        if name == "openjev":
            provider.verify_retention([ref])
        assert transport.requests == [], "capabilities, estimate and retention probe nothing"
    cls = {"openrouter-jev": JevOpenRouterProvider, "openjev": OpenJevLocalProvider, "fixture": RecordedFixtureProvider}[name]
    assert not inspect.iscoroutinefunction(cls.decide)


# --- TC-PROV-C18 -------------------------------------------------------------------------------

_MALFORMED = [b for b in jev_corpora.wire_bodies() if b["expect"]["outcome"] == "malformed"]


@pytest.mark.parametrize("name", IMPLEMENTATIONS)
@pytest.mark.parametrize("entry", _MALFORMED, ids=[b["id"] for b in _MALFORMED])
def test_tc_prov_c18_malformed_shapes_refused_by_every_implementation(name, entry, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    request = jev_corpora.wire_request(entry["request"])
    body = {**entry["body"], "usage": {"input_tokens": 1, "output_tokens": 0}}
    if name == "fixture":
        fixture = RecordedFixtureProvider(fixture_dir=tmp_path)
        good = WIRE["edge-well-formed-derived"]["body"] if entry["request"] == "canonical" else None
        if good is None:
            pytest.skip("the two-level row has no well-formed twin to record first")
        fixture.record_decision(request, FX_REF, good)
        path = fixture._path_for(__import__("aeh.prov", fromlist=["x"]).decision_request_key(request, FX_REF))
        document = json.loads(path.read_text(encoding="utf-8"))
        document["response"] = body  # a malformed answer stored behind the double's back
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(MalformedResponseError):
            fixture.decide(request, FX_REF)
        return
    transport = _Transport(_ok(body))
    provider, ref = _live(name, transport)
    with pytest.raises(MalformedResponseError):
        provider.decide(request, ref)
    assert len(transport.requests) == 3


@pytest.mark.parametrize("name", IMPLEMENTATIONS)
def test_tc_prov_c18_the_accept_row_is_returned_as_sent(name, tmp_path) -> None:
    body = {**WIRE["cloud-accept-sum-1-0009"]["body"], "usage": {"input_tokens": 1, "output_tokens": 0}}
    decision, _ = _decide_body(name, body, jev_corpora.wire_request(), tmp_path)
    assert sum(decision.answers["band"].probabilities) == pytest.approx(1.0009, abs=1e-12), "never renormalised"


# --- TC-PROV-C19 -------------------------------------------------------------------------------

@pytest.mark.parametrize("name", IMPLEMENTATIONS)
def test_tc_prov_c19_confidence_on_every_implementation(name, tmp_path) -> None:
    request = DecisionRequest(state="s", questions=(ScoreQuestion("band", "x", ("B", "D", "P", "E")),
                                                    NoulQuestion("ok", "x")))
    base = {"model": "typesafe/jev-1.13", "usage": {"input_tokens": 1, "output_tokens": 0}}
    score = {"type": "score", "score": 1.0, "probabilities": {"0": 0.05, "1": 0.90, "2": 0.05, "3": 0.0},
             "legend": {"0": "B", "1": "D", "2": "P", "3": "E"}}
    for i, (noul_p, expected_noul) in enumerate(((0.95, 0.90), (0.5, 0.0), (0.05, 0.90))):
        body = {**base, "answers": {"band": score, "ok": {"type": "noul", "noul": noul_p}}}
        decision, _ = _decide_body(name, body, request, tmp_path / f"n{i}")
        assert decision.answers["band"].confidence == pytest.approx(2.6 / 3, abs=1e-9)  # (4·0.90−1)/3
        assert decision.answers["band"].confidence_source == "derived"
        assert decision.answers["ok"].confidence == pytest.approx(expected_noul, abs=1e-9)  # |2p−1|
        assert decision.answers["ok"].confidence is not None
    choice_request = DecisionRequest(state="s", questions=(__import__("aeh.prov", fromlist=["x"]).ChoiceQuestion(
        "topic", "x", (("billing", None), ("technical", None))),))
    choice_body = {**base, "answers": {"topic": {"type": "choice", "choice": "billing",
                                                  "probabilities": {"billing": 0.88, "technical": 0.12}}}}
    choice, _ = _decide_body(name, choice_body, choice_request, tmp_path / "c")
    assert choice.answers["topic"].confidence == pytest.approx(0.76, abs=1e-9)  # (2·0.88 − 1)/1
    reported = {**base, "answers": {"band": {**score, "confidence": 0.81}, "ok": {"type": "noul", "noul": 0.9}}}
    decision, _ = _decide_body(name, reported, request, tmp_path / "r")
    assert (decision.answers["band"].confidence, decision.answers["band"].confidence_source) == (0.81, "reported")


# --- TC-PROV-C20 -------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["openrouter-jev", "openjev"])
@pytest.mark.parametrize("status", [400, 422])
def test_tc_prov_c20_a_rejection_message_is_bounded_and_state_free(name, status) -> None:
    entry = WIRE[f"{_wire_kind(name)}-status-{status}-echo"]
    provider, ref = _live(name, _Transport(HttpResponse(status, {}, json.dumps(entry["body"]).encode())))
    request = DecisionRequest(state=f"### submission\n{entry['expect']['sentinel']}",
                              questions=jev_corpora.wire_request().questions)
    with pytest.raises(DecisionRequestRejectedError) as caught:
        provider.decide(request, ref)
    assert str(status) in str(caught.value) and entry["expect"]["sentinel"] not in str(caught.value)


@pytest.mark.parametrize("name", IMPLEMENTATIONS)
@pytest.mark.parametrize("status, error, sends", [
    (400, DecisionRequestRejectedError, 1), (422, DecisionRequestRejectedError, 1),
    (401, ConfigurationError, 1), (403, ConfigurationError, 1), (402, ProviderUnavailableError, 1),
    (500, ProviderUnavailableError, 3), (524, ProviderUnavailableError, 3), (529, ProviderUnavailableError, 3),
    (429, ProviderUnavailableError, 3), ("exception", ProviderUnavailableError, 3)])
def test_tc_prov_c20_the_error_table_on_every_implementation(name, status, error, sends, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    request = jev_corpora.wire_request()
    counters = RunCountersTracker()
    if name == "fixture":
        fixture = RecordedFixtureProvider(fixture_dir=tmp_path)
        fixture.record_decision(request, FX_REF, error=(error.__name__, f"HTTP {status}"))
        with pytest.raises(error):
            fixture.decide(request, FX_REF)
        return
    if status == "exception":
        class _Raising(_Transport):
            def send(self, r):
                self.requests.append(r)
                from aeh.prov import TransportError
                raise TransportError("connection reset")
        transport = _Raising()
    else:
        body = WIRE[f"{_wire_kind(name)}-status-{status}"]["body"]
        headers = {"Retry-After": "0"} if status == 429 else {}
        transport = _Transport(HttpResponse(status, headers, json.dumps(body).encode()))
    provider, ref = _live(name, transport, counters)
    with pytest.raises(error) as caught:
        provider.decide(request, ref)
    assert len(transport.requests) == sends
    assert "k" != str(caught.value) and "Bearer" not in str(caught.value)
    assert counters.decision_snapshot().decision_calls == 0, "a failed call is never accounted as a Decision"


# --- TC-PROV-C21 (safety property) -------------------------------------------------------------

@pytest.mark.parametrize("name", ["openrouter-jev", "openjev"])
@pytest.mark.parametrize("status", [422, 402, 500])
def test_tc_prov_c21_a_raising_decide_never_reaches_an_llm(name, status, monkeypatch) -> None:
    """Adversarial construction (plan §6.11.1): an `except ProviderUnavailableError: return
    self._llm_fallback(...)` inside `decide` would put a `complete` call on this spy."""
    import aeh.prov as prov

    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    completes = []
    for cls in (prov.RecordedFixtureProvider, prov.OpenRouterProvider, prov.LocalServerProvider):
        original = cls.complete
        monkeypatch.setattr(cls, "complete", lambda self, *a, _o=original, **k: completes.append(1) or _o(self, *a, **k))
    body = WIRE[f"{_wire_kind(name)}-status-{status}"]["body"]
    provider, ref = _live(name, _Transport(HttpResponse(status, {}, json.dumps(body).encode())))
    with pytest.raises(Exception):
        provider.decide(jev_corpora.wire_request(), ref)
    assert completes == []
    good = _Transport(_ok(WIRE[f"{_wire_kind(name)}-well-formed-derived"]["body"]))
    provider, ref = _live(name, good)
    provider.decide(jev_corpora.wire_request(), ref)
    assert len(good.requests) == 1, "a parsed Decision is never re-requested"


# --- TC-PROV-C22 (safety property) -------------------------------------------------------------

def test_tc_prov_c22_local_stays_local_and_cloud_never_floats(monkeypatch) -> None:
    """Adversarial constructions: a `host.startswith("127.")` loopback check admits
    `127.0.0.1.example.com` (the table goes red); an env-defaulted `allow_fallbacks` shows in
    the captured bodies."""
    monkeypatch.delenv("HARNESS_OPENJEV_ALLOW_REMOTE", raising=False)
    for base in ("http://10.0.0.5:3000", "http://127.0.0.1.example.com:3000", "http://127.1.2.3.nip.io:3000"):
        with pytest.raises(ConfigurationError):
            OpenJevLocalProvider(base_url=base)
    for base in ("http://127.0.0.1:3000", "http://localhost:3000", "http://[::1]:3000"):
        OpenJevLocalProvider(base_url=base)
    floating = dataclasses.replace(JEV_REF, build_id="~typesafe/jev-latest")
    idle = _Transport(_ok(WIRE["cloud-well-formed-derived"]["body"]))
    with pytest.raises(ConfigurationError):
        JevOpenRouterProvider(api_key="k", transport=idle).decide(jev_corpora.wire_request(), floating)
    assert idle.requests == []
    transport = _Transport(_ok(WIRE["cloud-well-formed-derived"]["body"]))
    provider = JevOpenRouterProvider(api_key="k", transport=transport, clock=FrozenClock())
    for _ in range(3):
        provider.decide(jev_corpora.wire_request(), JEV_REF)
    assert all(json.loads(r.body)["provider"]["allow_fallbacks"] is False for r in transport.requests)


# --- TC-PROV-C23 -------------------------------------------------------------------------------

def test_tc_prov_c23_a_fixture_miss_never_reaches_the_network(tmp_path, network_guard) -> None:
    fixture = RecordedFixtureProvider(fixture_dir=tmp_path)
    with pytest.raises(FixtureMissingError):
        fixture.decide(jev_corpora.wire_request(), FX_REF)
    network_guard.assert_no_network()


# --- TC-PROV-C24 -------------------------------------------------------------------------------

def test_tc_prov_c24_the_counter_names() -> None:
    names = {f.name for f in dataclasses.fields(DecisionCounters)}
    assert names == {"decision_calls", "decision_tokens_in", "decision_transport_retries",
                     "decision_rate_limited_calls", "decision_actual_cost"}
    snapshot = RunCountersTracker().decision_snapshot()
    assert isinstance(snapshot, DecisionCounters)
    assert {name: getattr(snapshot, name) for name in names} == {
        "decision_calls": 0, "decision_tokens_in": 0, "decision_transport_retries": 0,
        "decision_rate_limited_calls": 0, "decision_actual_cost": Decimal(0)}
    # `actual_cost` including `decision_actual_cost` is asserted at the flush: TC-ORCH-51.


# --- TC-PROV-C25 (safety property) -------------------------------------------------------------

def test_tc_prov_c25_the_decision_model_is_under_the_retention_gate() -> None:
    """Rung 1 here. At rung 2, TC-ORCH-53's unconfirmed arm (TS-111) refuses a cloud start whose
    decision model is unconfirmed, which is the arm the adversarial construction (a retention set
    built from `cfg.panel` only) turns red."""
    transport = _Transport(_ok(WIRE["cloud-well-formed-derived"]["body"]))
    provider = JevOpenRouterProvider(api_key="k", transport=transport, clock=FrozenClock(),
                                     retention_answers=lambda build: "retention: standard")
    with pytest.raises(RetentionPolicyError):
        provider.verify_retention([JEV_REF])
    with pytest.raises(RetentionPolicyError):
        provider.decide(jev_corpora.wire_request(), JEV_REF)
    assert transport.requests == []
