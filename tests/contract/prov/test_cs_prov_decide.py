"""TS-112 (#465): the CS-PROV-DECIDE clause suite. Jev test plan §6.11.1, CT-PROV-17…25.

Each clause runs against all three decision implementations, so the double is held to the
contract the live providers keep (§4.9): `JevOpenRouterProvider` and `OpenJevLocalProvider`
over a programmed transport, and `RecordedFixtureProvider` over recorded documents and
declared errors. The safety-property clauses (C21, C22, C25) carry the adversarial
constructions the plan names.

| Case | Clause | Asserted |
|---|---|---|
| TC-PROV-C17 | surface | `decide` is synchronous and returns a `Decision`; one call is one send; capabilities, estimate and verify_retention send nothing |
| TC-PROV-C18 | data | TC-PROV-25's malformed shapes refused by all three; a malformed stored answer is refused by the double, not replayed; *(extended, design 1.8)* every returned answer carries a confidence in [0, 1], never `None`, and a Noul's equals its `p` |
| TC-PROV-C19 | behaviour | *(Re-specified, design 1.8, TS-123 #499.)* TC-PROV-24's Jev-rule rows on all three: no Jev-build implementation derives a confidence or keeps `|2p−1|` for a Noul |
| TC-PROV-C20 | error | TC-PROV-28's status table on all three (the double through declared errors); a failed call counts no decision; *(1.8)* a missing Jev confidence is refused after exactly one send |
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
from tests.unit.prov.test_ts105_decision_surface import (_CHOICE, _NOUL, _choice_doc, _decide_via, _noul_doc,
                                                         _score_doc, _score_request)

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
    body = WIRE[f"{_wire_kind(name)}-well-formed-reported"]["body"]
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
        good = WIRE["edge-well-formed-reported"]["body"] if entry["request"] == "canonical" else None
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


@pytest.mark.writtenahead
@pytest.mark.parametrize("name", IMPLEMENTATIONS)
def test_tc_prov_c18_every_answer_carries_a_confidence_and_a_noul_its_value(name, tmp_path) -> None:
    """Extended for design 1.8: on every implementation, each answer in F-JEV-WIRE's
    well-formed body carries a float confidence in [0, 1] (never `None`), and every
    `NoulAnswer.confidence == p_true` (1.6 gave the Nouls `|2p − 1|`: 0.88 and 0.76 here)."""
    body = {**WIRE[f"{_wire_kind(name)}-well-formed-reported"]["body"], "usage": {"input_tokens": 1, "output_tokens": 0}}
    decision, _ = _decide_body(name, body, jev_corpora.wire_request(), tmp_path)
    for key, answer in decision.answers.items():
        assert isinstance(answer.confidence, float) and 0.0 <= answer.confidence <= 1.0, key
        if hasattr(answer, "p_true"):
            assert answer.confidence == answer.p_true, key


# --- TC-PROV-C19 -------------------------------------------------------------------------------

@pytest.mark.writtenahead
@pytest.mark.parametrize("name", IMPLEMENTATIONS)
def test_tc_prov_c19_the_confidence_is_the_engines_on_every_implementation(name, tmp_path, monkeypatch) -> None:
    """Safety-shaped (RISK-83). Design 1.8, CT-PROV-19 v2.0: every Jev-build implementation
    refuses a Choice or Score answer without Jev's confidence (row a would return 0.8667 under a
    derived fallback) and gives a Noul its own value as confidence (row e would return 0.90
    under `|2p − 1|`).

    Adversarial construction (plan §6.11.6): restore `_confidence`'s "use the derived value when
    `confidence` is absent" branch "for robustness against OpenRouter omitting it". The
    missing-confidence arms go red on all three implementations, while every gate case whose
    fixtures carry a confidence stays green."""
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    for label, document, request in (("a", _score_doc(), _score_request()), ("f", _choice_doc(), _CHOICE)):
        with pytest.raises(MalformedResponseError):
            _decide_via(name, document, request, tmp_path / label)
    for p in (0.95, 0.5, 0.05):
        answer = _decide_via(name, _noul_doc(p), _NOUL, tmp_path / f"n{p}")[0].answers["ok"]
        assert (answer.confidence, answer.confidence_source) == (p, "reported")
    reported = _decide_via(name, _score_doc(confidence=0.81), _score_request(), tmp_path / "b")[0]
    assert (reported.answers["band"].confidence, reported.answers["band"].confidence_source) == (0.81, "reported")


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


@pytest.mark.writtenahead
@pytest.mark.parametrize("name", ["openrouter-jev", "openjev"])
def test_tc_prov_c20_a_missing_jev_confidence_is_refused_after_one_send(name, tmp_path, monkeypatch) -> None:
    """Design 1.8 (CT-PROV-20 amended): a Jev Choice/Score answer without `confidence` surfaces
    as `MalformedResponseError` after exactly one send, with the retry budget untouched. Every
    other malformed row keeps the budget of three (TC-PROV-C18 above), so a change that routes
    this case through the retry loop (three billed sends) goes red here, and so does one that
    stops retrying the others."""
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    sent: list[int] = []
    with pytest.raises(MalformedResponseError):
        _decide_via(name, _score_doc(), _score_request(), tmp_path, sent=sent)
    assert sent == [1]


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
    good = _Transport(_ok(WIRE[f"{_wire_kind(name)}-well-formed-reported"]["body"]))
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
    idle = _Transport(_ok(WIRE["cloud-well-formed-reported"]["body"]))
    with pytest.raises(ConfigurationError):
        JevOpenRouterProvider(api_key="k", transport=idle).decide(jev_corpora.wire_request(), floating)
    assert idle.requests == []
    transport = _Transport(_ok(WIRE["cloud-well-formed-reported"]["body"]))
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
    transport = _Transport(_ok(WIRE["cloud-well-formed-reported"]["body"]))
    provider = JevOpenRouterProvider(api_key="k", transport=transport, clock=FrozenClock(),
                                     retention_answers=lambda build: "retention: standard")
    with pytest.raises(RetentionPolicyError):
        provider.verify_retention([JEV_REF])
    with pytest.raises(RetentionPolicyError):
        provider.decide(jev_corpora.wire_request(), JEV_REF)
    assert transport.requests == []
