"""TS-106 (#459): `JevOpenRouterProvider`. Jev test plan §5 (M-PROV).

| Case | Asserted |
|---|---|
| TC-PROV-26 | *(Re-specified, design 1.8, TS-124 #500.)* The exact wire request through the TypeSafe SDK: `POST …/api/v1/systemone`, auth, body keys, the unversioned model slug, the provider routing object and the per-type `criteria` encoding. A floating alias is refused with zero transport calls. The alpha URL is now refused at construction (TC-PROV-48) |
| TC-PROV-28 | FR-PROV-23's status table, for both live providers: retried classes, 429 with `Retry-After`, rejections carrying a bounded, state-free excerpt, credential and credit statuses. No message holds the API key |
| TC-PROV-29 | Served-build identity: OpenRouter's `model` change raises `BuildChangedError` without a retry; OpenJev's vLLM probe runs at run start and every N calls, and a changed served path raises |
| TC-PROV-33 | The retention gate: confirm, hedge, unreachable; a failed gate refuses `decide` with zero transport calls; OpenJev on loopback is confirmed |
| TC-PROV-36 | *(Re-specified, design 1.8.)* **Live** (`@live`, E2, needs `OPENROUTER_API_KEY`), the `cloud-hosted` release gate: through the SDK on `/api/v1/systemone`, Choice/Score carry `confidence` (Q-J18), `usage.cost` is read from the raw body, the served `provider` is in the pinned order, a request pinned to a non-existent upstream is **refused** (Q-44), and an invalid 11-level Score through a raw call is rejected |
"""

from __future__ import annotations

import json
import os

import pytest

from aeh.conf import ConfigurationError, ModelRef
from aeh.prov import (BuildChangedError, ChoiceQuestion, DecisionRequest,
                      DecisionRequestRejectedError, HttpResponse, JevOpenRouterProvider,
                      NoulQuestion, OpenJevLocalProvider, ProviderUnavailableError,
                      RateLimitedError, RetentionPolicyError, ScoreQuestion, TransportError)
from tests.support import jev_corpora
from tests.support.clock import FrozenClock

API_KEY = "sk-or-TEST-SENTINEL-KEY-0001"
JEV_REF = ModelRef(role="decision", provider="openrouter-jev",
                   build_id="openrouter/typesafe/jev-1.13@2026-09-01", quantization=None)
OJ_REF = ModelRef(role="decision", provider="openjev",
                  build_id="/models/openjev-FP8/model.safetensors@sha256:" + "ab" * 32,
                  quantization="fp8")
WIRE = {b["id"]: b for b in jev_corpora.wire_bodies()}


class _Transport:
    """Programmed responses per call (the last repeats); `raise_error` raises instead."""

    def __init__(self, *responses, raise_error: Exception | None = None, routes=None) -> None:
        self.responses = list(responses)
        self.raise_error = raise_error
        self.routes = routes or {}
        self.requests = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        for suffix, handler in self.routes.items():
            if request.url.endswith(suffix):
                return handler(request)
        if self.raise_error is not None:
            raise self.raise_error
        return self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]


def _ok(body: dict) -> HttpResponse:
    return HttpResponse(200, {}, json.dumps(body).encode("utf-8"))


def _good_body(model: str = "typesafe/jev-1.13") -> dict:
    return {**WIRE["cloud-well-formed-reported"]["body"], "model": model}


def _request() -> DecisionRequest:
    return DecisionRequest(state="### criterion\nx\n\n### submission\ny", questions=(
        ChoiceQuestion("topic", "Which concept?", (("friction", "static friction"), ("normal", None))),
        ScoreQuestion("band", "Which band?", ("B", "D", "P", "E")),
        NoulQuestion("plain", "Is it plain?"),
        NoulQuestion("framed", "Is it framed?", when_true="yes it is", when_false="no it is not"),
    ))


# --- TC-PROV-26 --------------------------------------------------------------------------------

@pytest.mark.writtenahead
def test_tc_prov_26_the_exact_wire_request(monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_JEV_OPENROUTER_URL", raising=False)
    request = _request()
    body = {"model": "typesafe/jev-1.13", "usage": {"input_tokens": 1, "output_tokens": 0}, "answers": {
        "topic": {"type": "choice", "choice": "friction", "probabilities": {"friction": 0.9, "normal": 0.1},
                  "confidence": 0.8},
        "band": {"type": "score", "score": 2.0, "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0, "3": 0.0},
                 "legend": {"0": "B", "1": "D", "2": "P", "3": "E"}, "confidence": 1.0},
        "plain": {"type": "noul", "noul": 0.9}, "framed": {"type": "noul", "noul": 0.2}}}
    transport = _Transport(_ok(body))
    provider = JevOpenRouterProvider(api_key=API_KEY, transport=transport, clock=FrozenClock(),
                                     session_id="R1")
    provider.decide(request, JEV_REF)
    sent = transport.requests[0]
    headers = {str(k).lower(): str(v) for k, v in dict(sent.headers).items()}
    assert (sent.method, sent.url) == ("POST", "https://openrouter.ai/api/v1/systemone")
    assert headers.get("x-typesafe-sdk", "").startswith("typesafe-sdk/0.7.2"), "sent through the TypeSafe SDK"
    assert headers["authorization"] == f"Bearer {API_KEY}"
    document = json.loads(sent.body)
    assert set(document) == {"model", "state", "questions", "provider", "session_id"}
    assert document["model"] == "typesafe/jev-1.13" and document["session_id"] == "R1"
    routing = document["provider"]
    assert set(routing) == {"order", "allow_fallbacks", "data_collection", "zdr"}
    assert (routing["allow_fallbacks"], routing["data_collection"], routing["zdr"]) == (False, "deny", True)
    assert isinstance(routing["order"], list) and routing["order"]
    questions = document["questions"]
    assert questions["topic"]["criteria"] == {"friction": "static friction", "normal": None}
    assert questions["band"]["criteria"] == ["B", "D", "P", "E"]
    assert "criteria" not in questions["plain"]
    assert questions["framed"]["criteria"] == {"true": "yes it is", "false": "no it is not"}
    floating = ModelRef(role="decision", provider="openrouter-jev", build_id="~typesafe/jev-latest",
                        quantization=None)
    idle = _Transport(_ok(body))
    with pytest.raises(ConfigurationError):
        JevOpenRouterProvider(api_key=API_KEY, transport=idle, clock=FrozenClock()).decide(request, floating)
    assert idle.requests == []
    # Design 1.8 (ADR-28): the endpoint is the SDK's. The knob no longer moves it to the alpha
    # Decisions API; that URL is refused at construction (TC-PROV-48).


# --- TC-PROV-28 --------------------------------------------------------------------------------

def _provider(kind: str, transport, clock):
    if kind == "cloud":
        return JevOpenRouterProvider(api_key=API_KEY, transport=transport, clock=clock), JEV_REF
    return OpenJevLocalProvider(transport=transport, clock=clock), OJ_REF


@pytest.mark.parametrize("kind", ["cloud", "edge"])
@pytest.mark.parametrize("status", ["exception", 500, 524, 529])
def test_tc_prov_28_retried_classes_exhaust_to_unavailable(kind, status, monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    if status == "exception":
        transport = _Transport(raise_error=TransportError("connection reset"))
    else:
        transport = _Transport(HttpResponse(status, {}, json.dumps(WIRE[f"{kind}-status-{status}"]["body"]).encode()))
    provider, ref = _provider(kind, transport, FrozenClock())
    with pytest.raises(ProviderUnavailableError) as caught:
        provider.decide(jev_corpora.wire_request(), ref)
    assert len(transport.requests) == 3
    assert isinstance(caught.value.__cause__, TransportError)
    assert API_KEY not in str(caught.value)


@pytest.mark.parametrize("kind", ["cloud", "edge"])
def test_tc_prov_28_429_honours_retry_after_then_surfaces_rate_limiting(kind, monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    entry = WIRE[f"{kind}-status-429"]
    transport = _Transport(HttpResponse(429, {"Retry-After": "2"}, json.dumps(entry["body"]).encode()))
    clock = FrozenClock()
    provider, ref = _provider(kind, transport, clock)
    with pytest.raises(ProviderUnavailableError) as caught:
        provider.decide(jev_corpora.wire_request(), ref)
    # Every 429 is honoured with its full Retry-After (2.0 s each on the frozen clock).
    assert len(transport.requests) == 3 and clock.monotonic() == pytest.approx(2.0 * 3)
    assert isinstance(caught.value.__cause__, RateLimitedError)


@pytest.mark.parametrize("kind", ["cloud", "edge"])
@pytest.mark.parametrize("status", [400, 422])
def test_tc_prov_28_rejection_is_one_call_with_a_bounded_state_free_excerpt(kind, status) -> None:
    entry = WIRE[f"{kind}-status-{status}-echo"]
    raw = json.dumps(entry["body"]).encode()
    transport = _Transport(HttpResponse(status, {}, raw))
    provider, ref = _provider(kind, transport, FrozenClock())
    state_request = DecisionRequest(state=f"### submission\n{entry['expect']['sentinel']}",
                                    questions=jev_corpora.wire_request().questions)
    with pytest.raises(DecisionRequestRejectedError) as caught:
        provider.decide(state_request, ref)
    message = str(caught.value)
    assert len(transport.requests) == 1
    assert str(status) in message
    assert entry["expect"]["sentinel"] not in message
    assert len(message.encode()) <= 512 + 200, "the excerpt is bounded (≤ 512 body bytes plus the framing)"
    assert API_KEY not in message


@pytest.mark.parametrize("kind", ["cloud", "edge"])
@pytest.mark.parametrize("status, error", [(401, ConfigurationError), (403, ConfigurationError),
                                           (402, ProviderUnavailableError)])
def test_tc_prov_28_credential_and_credit_statuses_are_one_call(kind, status, error) -> None:
    transport = _Transport(HttpResponse(status, {}, json.dumps(WIRE[f"{kind}-status-{status}"]["body"]).encode()))
    provider, ref = _provider(kind, transport, FrozenClock())
    with pytest.raises(error) as caught:
        provider.decide(jev_corpora.wire_request(), ref)
    assert len(transport.requests) == 1
    assert API_KEY not in str(caught.value)


# --- TC-PROV-29 --------------------------------------------------------------------------------

def test_tc_prov_29_openrouter_build_change_is_terminal_without_retry(monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    transport = _Transport(_ok(_good_body("typesafe/jev-1.13")), _ok(_good_body("typesafe/jev-1.14")))
    provider = JevOpenRouterProvider(api_key=API_KEY, transport=transport, clock=FrozenClock())
    assert provider.decide(jev_corpora.wire_request(), JEV_REF).resolved_build == "typesafe/jev-1.13"
    with pytest.raises(BuildChangedError):
        provider.decide(jev_corpora.wire_request(), JEV_REF)
    assert len(transport.requests) == 2, "the changed build is not retried"


def test_tc_prov_29_openjev_probes_at_start_and_every_n_calls(monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_OPENJEV_BUILD_PROBE_EVERY", "3")
    served = {"root": "/models/openjev-FP8"}
    probes = []

    def models(request):  # noqa: ANN001
        probes.append(len(decides))
        return _ok({"data": [{"id": "openjev", "root": served["root"]}]})

    decides = []

    def systemone(request):  # noqa: ANN001
        decides.append(request)
        return _ok({**_good_body(), "model": "openjev"})

    transport = _Transport(routes={"/models": models, "/v1/systemone": systemone})
    provider = OpenJevLocalProvider(transport=transport, clock=FrozenClock())
    provider.verify_build(OJ_REF)
    for _ in range(6):
        provider.decide(jev_corpora.wire_request(), OJ_REF)
    assert probes == [0, 3], "run start, then after call 3"
    provider.decide(jev_corpora.wire_request(), OJ_REF)
    assert probes == [0, 3, 6], "and after call 6"
    served["root"] = "/models/openjev-Q4"
    for _ in range(2):
        provider.decide(jev_corpora.wire_request(), OJ_REF)
    with pytest.raises(BuildChangedError):
        provider.decide(jev_corpora.wire_request(), OJ_REF)


# --- TC-PROV-33 --------------------------------------------------------------------------------

def test_tc_prov_33_the_retention_gate_is_fail_closed() -> None:
    confirmed = JevOpenRouterProvider(api_key=API_KEY, retention_answers=lambda build: "zero-retention")
    report = confirmed.verify_retention([JEV_REF])
    assert report.confirmed == (JEV_REF,) and report.unconfirmed == ()
    def unreachable(build):
        raise TransportError("retention source unreachable")

    # A hedge, no source at all, and a source that cannot be reached: each is unconfirmed,
    # and each arms `decide`'s refusal.
    for answers in (lambda build: "retention: standard", None, unreachable):
        transport = _Transport(_ok(_good_body()))
        provider = JevOpenRouterProvider(api_key=API_KEY, transport=transport, clock=FrozenClock(),
                                         retention_answers=answers)
        with pytest.raises(RetentionPolicyError):
            provider.verify_retention([JEV_REF])
        with pytest.raises(RetentionPolicyError):
            provider.decide(jev_corpora.wire_request(), JEV_REF)
        assert transport.requests == []
    local = OpenJevLocalProvider().verify_retention([OJ_REF])
    assert local.confirmed == (OJ_REF,)


# --- TC-PROV-36 (live) -------------------------------------------------------------------------

@pytest.mark.live
def test_tc_prov_36_live_jev_on_openrouter() -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("TC-PROV-36 needs OPENROUTER_API_KEY with Jev access (E2)")
    from aeh.prov import HttpRequest, _DefaultTransport, _decision_status_error

    provider = JevOpenRouterProvider(retention_answers=lambda build: "zero-retention")
    provider.verify_retention([JEV_REF])
    request = DecisionRequest(state="### criterion\nExplains why the crate stays at rest.\n\n"
                                    "### submission\nFriction balances the component of weight along the ramp.",
                              questions=(
        ChoiceQuestion("concept", "Which concept does the answer use?",
                       (("friction", "static friction"), ("normal", "normal force"), ("weight", None))),
        ScoreQuestion("band", "Which band does the work meet?", ("Beginning", "Developing", "Proficient", "Exemplary")),
        NoulQuestion("evidence_sufficient", "Is the evidence enough to place the work in a band?"),
        NoulQuestion("cite_a", "Does the submission's sentence support the band?")))
    decision = provider.decide(request, JEV_REF)
    assert set(decision.answers) == {"concept", "band", "evidence_sufficient", "cite_a"}
    assert decision.resolved_build and "jev" in decision.resolved_build
    # (a) Q-J18: Jev's own confidence arrives on Choice and Score (a missing one is refused, so
    # reaching here proves it); (b) the raw body's cost reaches the Decision.
    assert decision.answers["band"].confidence_source == "reported"
    assert decision.answers["concept"].confidence_source == "reported"
    # With the list price set to zero a derived cost would be 0, so a positive cost can only
    # come from the raw body's `usage.cost`, which the SDK model drops.
    os.environ["HARNESS_JEV_COST_PER_MTOK_IN"] = "0"
    try:
        priced = JevOpenRouterProvider(retention_answers=lambda build: "zero-retention").decide(request, JEV_REF)
    finally:
        del os.environ["HARNESS_JEV_COST_PER_MTOK_IN"]
    assert priced.cost is not None and priced.cost > 0, "usage.cost is read from the raw body"
    # (d) Q-44, the preference probe, sent raw so nothing in the harness can turn a served answer
    # into a pass: pinned to an upstream that does not exist, with allow_fallbacks false, the
    # endpoint must REFUSE with a 4xx. A 200 means it ignores the routing preferences, and a 5xx
    # proves nothing; either blocks `cloud-hosted` release on this path.
    probe = {"model": "typesafe/jev-1.13", "state": "x", "questions": {"ok": {"type": "noul", "instructions": "x"}},
             "provider": {"order": ["no-such-upstream"], "allow_fallbacks": False, "data_collection": "deny",
                          "zdr": True}}
    refused = _DefaultTransport(30.0).send(HttpRequest(
        "POST", "https://openrouter.ai/api/v1/systemone",
        {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"},
        json.dumps(probe).encode()))
    assert 400 <= refused.status < 500, f"the routing preferences were not honoured: HTTP {refused.status}"
    invalid = {"model": "typesafe/jev-1.13", "state": "x", "questions": {
        "band": {"type": "score", "instructions": "x", "criteria": list("abcdefghijk")}}}
    response = _DefaultTransport(30.0).send(HttpRequest(
        "POST", "https://openrouter.ai/api/v1/systemone",
        {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"},
        json.dumps(invalid).encode()))
    assert response.status in (400, 422)
    assert isinstance(_decision_status_error(response, invalid["state"]), DecisionRequestRejectedError)
    capture = os.environ.get("HARNESS_JEV_WIRE_CAPTURE_DIR")
    if capture:  # the body refreshes F-JEV-WIRE's live comparison (schema diff -> review)
        from pathlib import Path

        Path(capture).mkdir(parents=True, exist_ok=True)
        (Path(capture) / "tc_prov_36_valid.json").write_text(json.dumps(
            {"answers": {k: str(v) for k, v in decision.answers.items()}, "resolved_build": decision.resolved_build},
            indent=1), encoding="utf-8")
