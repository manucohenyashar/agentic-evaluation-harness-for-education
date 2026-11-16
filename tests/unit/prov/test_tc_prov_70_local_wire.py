"""`TC-PROV-70` — the local server addressed by `served_as` (FR-PROV-47, CT-PROV-33; RSV-30).

Statistical-validity test plan r2 §3.22, story T21 (issue #905); implemented by S28 (#871).
Rung 1: the real `LocalServerProvider` over TC-PROV-18's seam — a programmed transport that
keeps every request and answers as an OpenAI-compatible local server does.

SV-32: the provider sent the weights path (`/models/x.gguf@sha256:...`) as `model`, and no local
server (Ollama, llama.cpp, vLLM) addresses a model by it. ADR-61 splits the two: `served_as` goes
on the wire, `build_id` stays the identity the audit record names (R30).

The programmed server deliberately reports a model name that is **not** `served_as`. If it
echoed the request, a journal that recorded `served_as` instead of what the server said would
be indistinguishable from a correct one.

Mutation (the plan's): the wire field reverted to `build_id` → the body assertions go red.
"""

from __future__ import annotations

import base64
import json

import pytest

from aeh.conf import ModelRef
from aeh.prov import (
    HttpResponse,
    ListCallJournal,
    LocalServerProvider,
    PromptPayload,
    RetryPolicy,
    SamplingParams,
    journal_installed,
)
from aeh.prov.live import IMAGE_FIELD
from tests.support.prov_contract import CountingClock

WEIGHTS = "/models/qwen3-vl-8b-instruct-q4.gguf@sha256:" + "ab" * 32
SERVED_AS = "qwen3-vl:8b-instruct-q4_K_M"
#: What the server says it served: not the requested name, on purpose (see the docstring).
REPORTED = "qwen3-vl:8b-instruct-q4_K_M-server-alias"
REF = ModelRef(role="transcriber", provider="ollama", build_id=WEIGHTS, quantization="q4",
               served_as=SERVED_AS)
PARAMS = SamplingParams(temperature=0.0)
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n-page-one-of-a-scan-").decode("ascii")


class _LocalServer:
    """A programmed OpenAI-compatible local server: keeps every request, answers each with a
    chat completion that reports `REPORTED` as its model."""

    def __init__(self) -> None:
        self.requests: list = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        return HttpResponse(200, {}, json.dumps({
            "id": "chatcmpl-1", "object": "chat.completion", "model": REPORTED,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "Q1: the block slides"}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 9},
        }).encode("utf-8"))

    def bodies(self) -> list[dict]:
        return [json.loads(r.body.decode("utf-8")) for r in self.requests if r.body]


def _provider(server: _LocalServer, **kwargs) -> LocalServerProvider:
    return LocalServerProvider(base_url="http://127.0.0.1:11434/v1", transport=server,
                               clock=CountingClock(), policy=RetryPolicy(3, 1, 120.0), **kwargs)


def _page_payload() -> PromptPayload:
    return PromptPayload(fields=(
        ("instruction", "Transcribe the answer sheet page. Reply with the marked text."),
        ("page_no", "1"),
        (IMAGE_FIELD, PNG),
    ))


def test_tc_prov_70_the_wire_model_is_served_as_never_the_weights_path():
    server = _LocalServer()
    _provider(server).complete(_page_payload(), REF, PARAMS)

    (body,) = server.bodies()
    assert body["model"] == SERVED_AS, (
        f"TC-PROV-70: the local server was addressed by {body['model']!r}, not served_as")
    wire = json.dumps(body)
    assert WEIGHTS not in wire, "TC-PROV-70: the weights path went on the wire"
    assert ".gguf" not in wire and "sha256" not in wire, wire[:200]
    # Sent to the local server's chat endpoint, not a model-path URL.
    assert server.requests[0].url == "http://127.0.0.1:11434/v1/chat/completions"


def test_tc_prov_70_resolved_build_is_the_pinned_build_and_the_journal_keeps_what_served():
    server = _LocalServer()
    sink = ListCallJournal()
    with journal_installed(sink):
        completion = _provider(server).complete(_page_payload(), REF, PARAMS)

    assert completion.resolved_build == WEIGHTS, (
        "TC-PROV-70: resolved_build must be the pinned build_id (R30), not the server's name")
    (record,) = sink.records
    assert record.outcome == "ok"
    assert record.resolved_build == WEIGHTS
    assert record.served_model == REPORTED, (
        f"TC-PROV-70: the journal must carry the server's reported model verbatim, got "
        f"{record.served_model!r}")


def test_tc_prov_70_a_page_image_is_still_an_image_url_part():
    server = _LocalServer()
    _provider(server).complete(_page_payload(), REF, PARAMS)

    (body,) = server.bodies()
    (image,) = [m for m in body["messages"] if m.get("name") == IMAGE_FIELD]
    assert image["content"] == [{"type": "image_url",
                                 "image_url": {"url": "data:image/png;base64," + PNG}}]


@pytest.mark.parametrize("profile, ceiling", [
    ("unified-large", 4),
    ("unified-small", 2),
    ("discrete-gpu", 3),
])
def test_tc_prov_70_max_concurrency_is_the_hardware_profiles_ceiling(monkeypatch, profile,
                                                                     ceiling):
    """The plan's literal values (FR-CONF-06's table), not read back from `HARDWARE_PROFILES`:
    reading them from the same table the code reads would make this check tautological."""
    monkeypatch.delenv("HARNESS_LOCAL_MAX_CONCURRENCY", raising=False)
    monkeypatch.delenv("HARNESS_HARDWARE_PROFILE", raising=False)
    server = _LocalServer()
    assert _provider(server, hardware_profile=profile).capabilities(REF).max_concurrency == ceiling

    # The same ceiling when the profile comes from the environment, as a provider built
    # without an explicit profile reads it.
    monkeypatch.setenv("HARNESS_HARDWARE_PROFILE", profile)
    assert _provider(server).capabilities(REF).max_concurrency == ceiling
    assert server.requests == [], "capabilities() must make no network call (CT-PROV-04)"


def test_tc_prov_70_the_edge_runtime_builds_the_provider_with_the_runs_hardware_profile(
        monkeypatch):
    """The pipeline's edge-local provider declares the run's profile, not the constant 1."""
    from aeh.conf import resolve_run_config
    from aeh.pipeline.runtime import _provider_for
    from tests.support.conf_builders import SYNTHETIC_COHORT, edge_cfg

    monkeypatch.delenv("HARNESS_LOCAL_MAX_CONCURRENCY", raising=False)
    monkeypatch.delenv("HARNESS_HARDWARE_PROFILE", raising=False)
    config = resolve_run_config(edge_cfg(HARNESS_HARDWARE_PROFILE="unified-small"),
                                SYNTHETIC_COHORT)
    provider = _provider_for(config)
    assert provider.capabilities(REF).max_concurrency == 2
