"""TS-107 (#460): `OpenJevLocalProvider`. Jev test plan §5 (M-PROV), §6.

| Case | Asserted |
|---|---|
| TC-PROV-27 | The exact loopback wire request; a non-loopback or look-alike host refused at construction; `localhost` and `::1` accepted; only `HARNESS_OPENJEV_ALLOW_REMOTE` admits a remote host |
| RES-23 | A real loopback stub shim killed mid-run: `TransportError` retries, then `ProviderUnavailableError` (the run's pause is M-ORCH's); the census shows only loopback connects |
| SEC-20 | Egress census: the edge provider against a real loopback stub connects only to 127.0.0.1; the cloud provider's requests all target the configured OpenRouter host. Measured at the provider (the only egress point, CT-PROV-15); the whole-run census is SEC-22 / RES-22 in TS-117 |
| TC-PROV-37 | **Live** (`@live`, E7): the same request against a running OpenJev shim, and the vLLM build probe |
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from aeh.conf import ConfigurationError, ModelRef
from aeh.prov import (HttpResponse, JevOpenRouterProvider, OpenJevLocalProvider,
                      ProviderUnavailableError, TransportError)
from tests.support import jev_corpora
from tests.support.clock import FrozenClock
from tests.support.guards import loopback_census

OJ_REF = ModelRef(role="decision", provider="openjev",
                  build_id="/models/openjev-FP8/model.safetensors@sha256:" + "ab" * 32,
                  quantization="fp8")
JEV_REF = ModelRef(role="decision", provider="openrouter-jev",
                   build_id="openrouter/typesafe/jev-1.13@2026-09-01", quantization=None)
GOOD = {**next(b for b in jev_corpora.wire_bodies() if b["id"] == "edge-well-formed-reported")["body"]}


class _Transport:
    def __init__(self, body: dict) -> None:
        self.body = body
        self.requests = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        return HttpResponse(200, {}, json.dumps(self.body).encode())


# --- TC-PROV-27 --------------------------------------------------------------------------------

def test_tc_prov_27_the_loopback_wire_and_the_host_rule(monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_OPENJEV_BASE_URL", raising=False)
    monkeypatch.delenv("HARNESS_OPENJEV_ALLOW_REMOTE", raising=False)
    transport = _Transport(GOOD)
    OpenJevLocalProvider(transport=transport, clock=FrozenClock()).decide(jev_corpora.wire_request(), OJ_REF)
    sent = transport.requests[0]
    assert (sent.method, sent.url) == ("POST", "http://127.0.0.1:3000/v1/systemone")
    document = json.loads(sent.body)
    assert set(document) == {"model", "state", "questions"} and document["model"] == "openjev"
    for base in ("http://10.0.0.5:3000", "http://127.0.0.1.example.com:3000"):
        with pytest.raises(ConfigurationError):
            OpenJevLocalProvider(base_url=base)
    OpenJevLocalProvider(base_url="http://localhost:3000")
    OpenJevLocalProvider(base_url="http://[::1]:3000")
    monkeypatch.setenv("HARNESS_OPENJEV_ALLOW_REMOTE", "true")
    OpenJevLocalProvider(base_url="http://10.0.0.5:3000")


# --- a real loopback stub shim -----------------------------------------------------------------

class _Shim:
    """A stub OpenJev shim on 127.0.0.1, answering `/v1/systemone` with a valid body."""

    def __init__(self) -> None:
        body = json.dumps({**GOOD, "model": "openjev"}).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # noqa: ANN002
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def kill(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def test_res_23_a_killed_loopback_shim_retries_then_is_unavailable(network_guard, monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    shim = _Shim()
    try:
        with loopback_census(network_guard) as census:
            provider = OpenJevLocalProvider(base_url=shim.base_url, clock=FrozenClock(), timeout_s=5.0)
            provider.decide(jev_corpora.wire_request(), OJ_REF)
            before = len(census)
            shim.kill()
            with pytest.raises(ProviderUnavailableError) as caught:
                provider.decide(jev_corpora.wire_request(), OJ_REF)
        assert isinstance(caught.value.__cause__, TransportError)
        attempts_after_kill = [a for a in census[before:] if a.api == "socket.connect"]
        assert len(attempts_after_kill) == 3, (
            f"HARNESS_RETRY_MAX=3: three connection attempts after the kill, got {len(attempts_after_kill)}")
        assert census, "the census recorded the provider's connections"
        hosts = {a.address[0] for a in census if isinstance(a.address, tuple)}
        assert hosts <= {"127.0.0.1", "::1"}, f"non-loopback connect targets: {hosts}"
        assert network_guard.attempts == [], "nothing was refused: every target was loopback"
    finally:
        if shim.thread.is_alive():
            shim.kill()


# --- SEC-20 ------------------------------------------------------------------------------------

def test_sec_20_edge_decisions_connect_only_to_loopback(network_guard) -> None:
    shim = _Shim()
    try:
        with loopback_census(network_guard) as census:
            provider = OpenJevLocalProvider(base_url=shim.base_url, clock=FrozenClock(), timeout_s=5.0)
            for _ in range(3):
                provider.decide(jev_corpora.wire_request(), OJ_REF)
        hosts = {a.address[0] for a in census if isinstance(a.address, tuple)}
        assert hosts and hosts <= {"127.0.0.1", "::1"}
        assert network_guard.attempts == []
    finally:
        shim.kill()


def test_sec_20_cloud_decisions_target_only_the_configured_openrouter_host() -> None:
    body = {**GOOD, "model": "typesafe/jev-1.13"}
    transport = _Transport(body)
    provider = JevOpenRouterProvider(api_key="k", transport=transport, clock=FrozenClock())
    for _ in range(3):
        provider.decide(jev_corpora.wire_request(), JEV_REF)
    assert {urlsplit(r.url).hostname for r in transport.requests} == {"openrouter.ai"}


# --- TC-PROV-37 (live) -------------------------------------------------------------------------

@pytest.mark.live
def test_tc_prov_37_live_openjev_shim_and_build_probe() -> None:
    if not os.environ.get("HARNESS_OPENJEV_LIVE_BUILD"):
        pytest.skip("TC-PROV-37 runs on E7: set HARNESS_OPENJEV_LIVE_BUILD to the served "
                    "weights build and serve the OpenJev shim on HARNESS_OPENJEV_BASE_URL")
    ref = ModelRef(role="decision", provider="openjev", build_id=os.environ["HARNESS_OPENJEV_LIVE_BUILD"],
                   quantization=os.environ.get("HARNESS_OPENJEV_LIVE_QUANTIZATION", "fp8"))
    provider = OpenJevLocalProvider()
    assert provider.verify_build(ref)
    decision = provider.decide(jev_corpora.wire_request(), ref)
    assert set(decision.answers) == {"topic", "band", "evidence_sufficient", "cite_a"}
    from aeh.prov import DecisionRequestRejectedError, HttpRequest, _DefaultTransport, _decision_status_error

    base = os.environ.get("HARNESS_OPENJEV_BASE_URL", "http://127.0.0.1:3000").rstrip("/")
    invalid = {"model": "openjev", "state": "x", "questions": {
        "band": {"type": "score", "instructions": "x", "criteria": list("abcdefghijk")}}}
    response = _DefaultTransport(30.0).send(HttpRequest(
        "POST", f"{base}/v1/systemone", {"Content-Type": "application/json"}, json.dumps(invalid).encode()))
    assert isinstance(_decision_status_error(response, "x"), DecisionRequestRejectedError)
