"""TS-124 (#500): `JevOpenRouterProvider` through the TypeSafe SDK (design 1.8, §3.12).
Jev test plan §5.8. Written ahead of #498.

Every case drives the provider with its real `TypeSafeClient` (the SDK is installed in the dev
tier, `requirements-dev.txt`) and the **programmed `Transport`**, which after #498 is reached
through the SDK's `httpx2` transport adapter. The SDK is never stubbed: stubbing it is what would
hide RISK-85/86/87. The SDK stamps every request with `X-TypeSafe-SDK: typesafe-sdk/<version>`,
so each case asserts that header. That makes the cases discriminating: on the stdlib client of
1.6 they fail on it, and once #498 routes the provider through the SDK they pass.

| Case | Asserted |
|---|---|
| TC-PROV-48 | The wire through the SDK: `POST https://openrouter.ai/api/v1/systemone`, the OpenRouter key, the exact body keys and routing object; `TYPESAFE_*` env changes nothing; the alpha URL is refused at construction and a floating alias at decide, both with 0 sends; no model listing |
| TC-PROV-49 | One send per attempt of our loop: no `X-TypeSafe-Retry-Count` header; `Retry-After` honoured by our clock; the budget exhausts to `ProviderUnavailableError` |
| TC-PROV-50 | `cost`, `model` and `provider` are read from the raw body (the SDK model drops `usage.cost`); NaN/negative cost and a legend mismatch are still refused |
| TC-PROV-51 | The SDK error mapping, a validation error first: every raised type is `aeh.prov`'s, and no exception in the chain carries the key or the echoed state |
| TC-PROV-54 | The per-call routing check: an off-list upstream raises `RetentionPolicyError` after one send; an absent `provider` counts `decision_provider_unreported`. The M-JUDGE arm is `tests/integration/judge/test_ts124_routing_refusal.py` |
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from aeh.conf import ConfigurationError, ModelRef
from aeh.prov import (DecisionRequestRejectedError, HttpResponse, JevOpenRouterProvider, MalformedResponseError,
                      ProviderUnavailableError, RateLimitedError, RetentionPolicyError, RunCountersTracker,
                      TransportError)
from harness.corpora.jev import STATE_SENTINEL
from tests.support import jev_corpora
from tests.support.clock import FrozenClock
from tests.unit.prov.test_ts106_jev_openrouter import _request as _mixed_request

API_KEY = "sk-or-SENTINEL-0048"
JEV_REF = ModelRef(role="decision", provider="openrouter-jev",
                   build_id="openrouter/typesafe/jev-1.13@2026-09-01", quantization=None)
SYSTEMONE = "https://openrouter.ai/api/v1/systemone"
SDK_HEADER, RETRY_HEADER = "x-typesafe-sdk", "x-typesafe-retry-count"
WIRE = {b["id"]: b for b in jev_corpora.wire_bodies()}


class _Transport:
    """Programmed responses per send (the last repeats); `raise_error` raises instead."""

    def __init__(self, *responses, raise_error: Exception | None = None) -> None:
        self.responses = list(responses)
        self.raise_error = raise_error
        self.requests = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        if self.raise_error is not None:
            raise self.raise_error
        return self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]


def _ok(body: dict) -> HttpResponse:
    return HttpResponse(200, {}, json.dumps(body).encode("utf-8"))


def _headers(request) -> dict[str, str]:  # noqa: ANN001
    return {str(k).lower(): str(v) for k, v in dict(request.headers).items()}


def _body(request) -> dict:  # noqa: ANN001
    return json.loads(bytes(request.body).decode("utf-8"))


def _assert_sdk_path(transport: _Transport) -> None:
    """Every captured request came through the TypeSafe SDK, one send per attempt."""
    assert transport.requests, "the provider sent nothing"
    for sent in transport.requests:
        headers = _headers(sent)
        assert headers.get(SDK_HEADER, "").startswith("typesafe-sdk/0.7.2"), (
            f"not sent through the TypeSafe SDK: {sorted(headers)}")
        assert RETRY_HEADER not in headers, "the SDK retried inside one of our attempts"


def _good_body(**overrides) -> dict:
    body = {**WIRE["cloud-well-formed-reported"]["body"], "model": "typesafe/jev-1.13"}
    body.update(overrides)
    return body


def _provider(transport, clock=None, counters=None, **kw) -> JevOpenRouterProvider:
    return JevOpenRouterProvider(api_key=API_KEY, transport=transport, clock=clock or FrozenClock(),
                                 counters=counters, **kw)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("HARNESS_JEV_OPENROUTER_URL", "HARNESS_JEV_OPENROUTER_PROVIDER", "TYPESAFE_API_KEY",
                 "TYPESAFE_BASE_URL", "TYPESAFE_DEFAULT_MODEL", "TYPESAFE_LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")


# --- TC-PROV-48 ----------------------------------------------------------------------------------

def _mixed_body() -> dict:
    return {"model": "typesafe/jev-1.13", "usage": {"input_tokens": 1, "output_tokens": 0}, "answers": {
        "topic": {"type": "choice", "choice": "friction", "probabilities": {"friction": 0.9, "normal": 0.1},
                  "confidence": 0.8},
        "band": {"type": "score", "score": 2.0, "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0, "3": 0.0},
                 "legend": {"0": "B", "1": "D", "2": "P", "3": "E"}, "confidence": 1.0},
        "plain": {"type": "noul", "noul": 0.9}, "framed": {"type": "noul", "noul": 0.2}}}


@pytest.mark.writtenahead
def test_tc_prov_48_the_wire_through_the_sdk(monkeypatch) -> None:
    transport = _Transport(_ok(_mixed_body()))
    _provider(transport, session_id="R1").decide(_mixed_request(), JEV_REF)
    _assert_sdk_path(transport)
    sent = transport.requests[0]
    assert (sent.method, sent.url) == ("POST", SYSTEMONE)
    assert _headers(sent)["authorization"] == f"Bearer {API_KEY}"
    document = _body(sent)
    assert set(document) == {"model", "state", "questions", "provider", "session_id"}
    assert document["model"] == "typesafe/jev-1.13" and document["session_id"] == "R1"
    assert document["provider"] == {"order": ["typesafe"], "allow_fallbacks": False,
                                    "data_collection": "deny", "zdr": True}
    questions = document["questions"]
    assert questions["topic"]["criteria"] == {"friction": "static friction", "normal": None}
    assert questions["band"]["criteria"] == ["B", "D", "P", "E"]
    assert "criteria" not in questions["plain"]
    assert questions["framed"]["criteria"] == {"true": "yes it is", "false": "no it is not"}

    # The SDK reads TYPESAFE_API_KEY / _BASE_URL / _DEFAULT_MODEL when an argument is omitted.
    # The provider passes every one explicitly, so the environment changes nothing (RISK-89).
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-OTHER-KEY")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai.example")
    monkeypatch.setenv("TYPESAFE_DEFAULT_MODEL", "jev-latest")
    again = _Transport(_ok(_mixed_body()))
    _provider(again, session_id="R1").decide(_mixed_request(), JEV_REF)
    second = again.requests[0]
    assert (second.method, second.url, _headers(second), bytes(second.body)) == (
        sent.method, sent.url, _headers(sent), bytes(sent.body)), "the TYPESAFE_* environment moved the request"

    floating = ModelRef(role="decision", provider="openrouter-jev", build_id="~typesafe/jev-latest", quantization=None)
    idle = _Transport(_ok(_mixed_body()))
    with pytest.raises(ConfigurationError):
        _provider(idle).decide(_mixed_request(), floating)
    assert idle.requests == []
    # The knob still moves the endpoint (seam 3), to any base whose path ends in /v1/systemone.
    monkeypatch.setenv("HARNESS_JEV_OPENROUTER_URL", "https://or-proxy.example/api/v1/systemone")
    proxied = _Transport(_ok(_mixed_body()))
    _provider(proxied).decide(_mixed_request(), JEV_REF)
    assert proxied.requests[0].url == "https://or-proxy.example/api/v1/systemone"
    monkeypatch.setenv("HARNESS_JEV_OPENROUTER_URL", "https://openrouter.ai/api/alpha/decisions")
    refused = _Transport(_ok(_mixed_body()))
    with pytest.raises(ConfigurationError):
        _provider(refused)
    assert refused.requests == []
    assert all(r.method == "POST" and not r.url.endswith("/v1/models")
               for r in transport.requests + again.requests + proxied.requests), "the SDK's model listing is never called"


# --- TC-PROV-49 ----------------------------------------------------------------------------------

@pytest.mark.writtenahead
def test_tc_prov_49_one_send_per_attempt_and_our_loop_owns_retries() -> None:
    good = _ok(_good_body())
    one = _Transport(good)
    _provider(one).decide(jev_corpora.wire_request(), JEV_REF)
    assert len(one.requests) == 1
    _assert_sdk_path(one)

    counters = RunCountersTracker()
    flapping = _Transport(HttpResponse(500, {}, b"{}"), HttpResponse(500, {}, b"{}"), good)
    _provider(flapping, counters=counters).decide(jev_corpora.wire_request(), JEV_REF)
    assert len(flapping.requests) == 3
    _assert_sdk_path(flapping)
    assert counters.decision_snapshot().decision_transport_retries == 2

    clock = FrozenClock()
    limited = _Transport(HttpResponse(429, {"Retry-After": "2"}, b"{}"), good)
    _provider(limited, clock=clock).decide(jev_corpora.wire_request(), JEV_REF)
    assert len(limited.requests) == 2 and clock.monotonic() == pytest.approx(2.0)
    _assert_sdk_path(limited)

    down = _Transport(HttpResponse(500, {}, b"{}"))
    with pytest.raises(ProviderUnavailableError) as caught:
        _provider(down).decide(jev_corpora.wire_request(), JEV_REF)
    assert len(down.requests) == 3 and isinstance(caught.value.__cause__, TransportError)
    _assert_sdk_path(down)


# --- TC-PROV-50 ----------------------------------------------------------------------------------

@pytest.mark.writtenahead
def test_tc_prov_50_values_are_read_from_the_raw_body(monkeypatch) -> None:
    # At 1 USD per million input tokens the derived cost of 1,200 tokens is 0.0012, so only the
    # raw body's 0.0000504 can produce the asserted value (the SDK model drops `usage.cost`).
    monkeypatch.setenv("HARNESS_JEV_COST_PER_MTOK_IN", "1")
    body = _good_body(usage={"input_tokens": 1200, "output_tokens": 0, "cost": 0.0000504},
                      provider="typesafe", id="gen-1")
    counters = RunCountersTracker()
    transport = _Transport(_ok(body))
    decision = _provider(transport, counters=counters).decide(jev_corpora.wire_request(), JEV_REF)
    _assert_sdk_path(transport)
    assert decision.cost == Decimal("0.0000504"), "usage.cost comes from the raw body; the SDK model drops it"
    assert decision.resolved_build == "typesafe/jev-1.13"
    assert counters.decision_snapshot().decision_actual_cost == Decimal("0.0000504")
    for cost in ("NaN", -1):
        bad = _Transport(_ok(_good_body(usage={"input_tokens": 1, "output_tokens": 0, "cost": cost})))
        with pytest.raises(MalformedResponseError):
            _provider(bad).decide(jev_corpora.wire_request(), JEV_REF)
    legend = json.loads(json.dumps(_good_body()))
    legend["answers"]["band"]["legend"]["1"] = "Emerging"
    mismatch = _Transport(_ok(legend))
    with pytest.raises(MalformedResponseError):
        _provider(mismatch).decide(jev_corpora.wire_request(), JEV_REF)
    _assert_sdk_path(mismatch)


# --- TC-PROV-51 ----------------------------------------------------------------------------------

def _chain(error: BaseException):
    seen = []
    while error is not None and error not in seen:
        seen.append(error)
        error = error.__cause__ or error.__context__
    return seen


def _no_confidence() -> HttpResponse:
    body = json.loads(json.dumps(_good_body()))
    del body["answers"]["band"]["confidence"]
    return _ok(body)


def _sum_098() -> HttpResponse:
    body = json.loads(json.dumps(_good_body()))
    body["answers"]["band"]["probabilities"] = {"0": 0.02, "1": 0.08, "2": 0.71, "3": 0.17}
    return _ok(body)


def _echo(status: int) -> HttpResponse:
    return HttpResponse(status, {}, json.dumps(WIRE[f"cloud-status-{status}-echo"]["body"]).encode())


def _status(status: int) -> HttpResponse:
    return HttpResponse(status, {}, json.dumps({"error": {"code": status, "message": "nope"}}).encode())


def _echo_request():
    """The request whose state the 400/422 bodies echo: FR-PROV-23 forbids request bytes in the
    error, so the sentinel must be in the request for its absence to mean anything."""
    from aeh.prov import DecisionRequest

    return DecisionRequest(state=f"### submission\n{STATE_SENTINEL}", questions=jev_corpora.wire_request().questions)


_TABLE = [
    ("missing-confidence", lambda: _Transport(_no_confidence()), MalformedResponseError, 1),
    ("sum-0.98", lambda: _Transport(_sum_098()), MalformedResponseError, 3),
    ("400", lambda: _Transport(_echo(400)), DecisionRequestRejectedError, 1),
    ("422", lambda: _Transport(_echo(422)), DecisionRequestRejectedError, 1),
    ("401", lambda: _Transport(_status(401)), ConfigurationError, 1),
    ("403", lambda: _Transport(_status(403)), ConfigurationError, 1),
    ("402", lambda: _Transport(_status(402)), ProviderUnavailableError, 1),
    ("418", lambda: _Transport(_status(418)), ProviderUnavailableError, 1),
    # Green on 1.6 too: the transport's own failure never reaches a status mapping, and must keep
    # surfacing as unavailability once the SDK adapter sits between the loop and the transport.
    pytest.param("connection", lambda: _Transport(raise_error=TransportError("connection refused")),
                 ProviderUnavailableError, 3, id="connection"),
    pytest.param("timeout", lambda: _Transport(raise_error=TransportError("read timed out")),
                 ProviderUnavailableError, 3, id="timeout"),
]
_TABLE = [row if type(row) is not tuple else pytest.param(*row, id=row[0], marks=pytest.mark.writtenahead)
          for row in _TABLE]


@pytest.mark.parametrize("row, make, error, sends", _TABLE)
def test_tc_prov_51_every_sdk_failure_maps_to_a_harness_error(row, make, error, sends) -> None:
    """FR-PROV-41. A validation error is mapped before its status (it carries HTTP 200); an
    unmapped status (418) is unavailability, never a leaked SDK type. For every row the raised
    type is `aeh.prov`'s and no exception in the chain carries the key or the echoed state."""
    transport = make()
    request = _echo_request() if row in ("400", "422") else jev_corpora.wire_request()
    with pytest.raises(error) as caught:
        _provider(transport).decide(request, JEV_REF)
    assert len(transport.requests) == sends, f"row {row}"
    if row not in ("connection", "timeout"):
        _assert_sdk_path(transport)
    assert type(caught.value).__module__ in ("aeh.prov", "aeh.conf"), type(caught.value)
    for link in _chain(caught.value):
        for text in (str(link), repr(link)):
            assert API_KEY not in text and STATE_SENTINEL not in text, f"row {row}: {type(link).__name__}"
    if isinstance(caught.value, DecisionRequestRejectedError):
        assert row in str(caught.value), "the rejection names its status"
        body = json.dumps(WIRE[f"cloud-status-{row}-echo"]["body"])
        assert len(str(caught.value).encode()) < len(body.encode()), "at most 512 body bytes, never the whole body"


@pytest.mark.writtenahead
def test_tc_prov_51_a_bare_sdk_error_is_unavailability_with_its_cause(monkeypatch) -> None:
    import typesafe_sdk
    from typesafe_sdk import TypeSafeError

    def boom(self, *args, **kwargs):  # noqa: ANN001
        raise TypeSafeError("SDK internal failure")

    monkeypatch.setattr(typesafe_sdk.TypeSafeClient, "system_one", boom)
    with pytest.raises(ProviderUnavailableError) as caught:
        _provider(_Transport(_ok(_good_body()))).decide(jev_corpora.wire_request(), JEV_REF)
    assert any(isinstance(link, TypeSafeError) for link in _chain(caught.value)), "the SDK error is chained"
    assert type(caught.value).__module__ == "aeh.prov"


# --- TC-PROV-54 ----------------------------------------------------------------------------------

@pytest.mark.writtenahead
def test_tc_prov_54_the_per_call_routing_check() -> None:
    listed = _Transport(_ok(_good_body(provider="typesafe")))
    _provider(listed).decide(jev_corpora.wire_request(), JEV_REF)
    _assert_sdk_path(listed)
    counters = RunCountersTracker()
    off_list = _Transport(_ok(_good_body(provider="OtherHost")))
    with pytest.raises(RetentionPolicyError):
        _provider(off_list, counters=counters).decide(jev_corpora.wire_request(), JEV_REF)
    assert len(off_list.requests) == 1, "terminal, never retried"
    assert counters.decision_snapshot().decision_calls == 0, "no success is counted"
    unreported = RunCountersTracker()
    body = _good_body()
    body.pop("provider", None)
    _provider(_Transport(_ok(body)), counters=unreported).decide(jev_corpora.wire_request(), JEV_REF)
    assert getattr(unreported.decision_snapshot(), "decision_provider_unreported", None) == 1
