"""TC-REG-29 (#905): SV-32 pinned. No request body `LocalServerProvider` builds carries `.gguf`
or `sha256:`.

Traces: FR-PROV-47, CT-PROV-33 (→ TC-PROV-70). Source:
`docs/design/statistical_validity_test_plan.md` §3.22 / §3.25.

**SV-32.** The local provider sent the pinned weights path (`/models/x.gguf@sha256:...`) as the
request's `model`; no local server addresses a model by it, so the offline profile had never run.
S28 (#871) sends `served_as` instead (ADR-61). This pins the absence across every weights form
`M-CONF` accepts, both call shapes (text and page image), and every request the transport saw —
not only the first POST — so a fallback that put the path anywhere in the body (a `user` field, a
header-like key, a retry) is caught.

The payloads themselves are free of `.gguf` and `sha256:`, so an absence here is the provider's
and not the test data's.

Isolation: rung 1, a programmed transport (TC-PROV-18's seam); no network.
"""

from __future__ import annotations

import base64
import json

import pytest

from aeh.conf import WEIGHTS_SUFFIXES, ModelRef
from aeh.prov import HttpResponse, LocalServerProvider, PromptPayload, RetryPolicy, SamplingParams
from aeh.prov.live import IMAGE_FIELD
from tests.support.prov_contract import CountingClock

_FORBIDDEN = (".gguf", "sha256:")
_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n-a-scanned-page-").decode("ascii")


class _Server:
    """Answers 503 first (so the retry path builds a second body), then a completion."""

    def __init__(self) -> None:
        self.requests: list = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        if len(self.requests) == 1:
            return HttpResponse(503, {}, b'{"error": {"message": "loading model"}}')
        return HttpResponse(200, {}, json.dumps({
            "model": "served-name",
            "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }).encode("utf-8"))


def _refs() -> list[ModelRef]:
    """One local ref per weights suffix M-CONF knows, across the four local provider names."""
    providers = ("local", "local-server", "ollama", "vllm-mlx")
    return [
        ModelRef(role="judge", provider=providers[i % len(providers)],
                 build_id=f"/models/qwen3-30b-a3b{suffix}@sha256:{'c' * 64}",
                 quantization="q4", served_as=f"qwen3:30b-{i}")
        for i, suffix in enumerate(WEIGHTS_SUFFIXES)
    ]


_PAYLOADS = {
    "text": PromptPayload(fields=(("directive", "Score one criterion."),
                                  ("submission", "The block slides because friction is low."))),
    "page": PromptPayload(fields=(("instruction", "Transcribe the page."), ("page_no", "1"),
                                  (IMAGE_FIELD, _PNG))),
}


def test_tc_reg_29_the_payloads_are_clean_so_the_absence_is_the_providers():
    for payload in _PAYLOADS.values():
        assert not any(bad in value for _, value in payload.fields for bad in _FORBIDDEN)
    assert ".gguf" in WEIGHTS_SUFFIXES, "the census must include the SV-32 form itself"


@pytest.mark.parametrize("shape", sorted(_PAYLOADS))
@pytest.mark.parametrize("ref", _refs(), ids=lambda r: r.build_id.split("@")[0].rsplit(".", 1)[-1])
def test_tc_reg_29_no_local_request_body_carries_a_weights_path_or_hash(ref, shape):
    server = _Server()
    provider = LocalServerProvider(base_url="http://127.0.0.1:8080/v1", transport=server,
                                   clock=CountingClock(), policy=RetryPolicy(3, 1, 120.0))
    provider.complete(_PAYLOADS[shape], ref, SamplingParams(temperature=0.0))

    assert len(server.requests) == 2, "precondition: the retry built a second request"
    for request in server.requests:
        text = request.body.decode("utf-8") if request.body else ""
        for bad in _FORBIDDEN:
            assert bad not in text, (
                f"TC-REG-29 (SV-32): a LocalServerProvider request body carries {bad!r}: "
                f"{text[:160]}")
        assert not any(bad in request.url for bad in _FORBIDDEN), request.url
        assert json.loads(text)["model"] == ref.served_as
