"""Regression cases for the first real OpenRouter call (TC-PROV-60..63).

The first call made through `OpenRouterProvider` against the real service failed with
*"the response carries neither a choices list nor a text field"*, while a hand-made request with
the same key and model succeeded. Four defects, each with no prior `TC-*` coverage, so each gets
its regression case here (CLAUDE.md, "Test authorship"):

- TC-PROV-60 (FR-PROV-13, CT-PROV-05): the body was `{"prompt": {"fields": [...]}}`, which no
  chat-completions server accepts. It is now one `user` message per field, the value verbatim,
  the field name in the message's `name`, and the page image as an image part.
- TC-PROV-61 (FR-PROV-11, FR-PROV-04): OpenRouter was sent the whole pinned build id
  (`openrouter/qwen/qwen3-30b-a3b@2026-06-01`). It is now sent the plain slug it knows.
- TC-PROV-62 (FR-PROV-06): a refused request (4xx other than 429) fell through to parsing, so
  the backend's own explanation was lost. A run-wide refusal (401, 402, 404) now raises
  `ProviderUnavailableError` after one send, so the run pauses; any other refusal is that
  unit's `MalformedResponseError`. Both name the status and the backend's message, with
  student text withheld.
- TC-PROV-63 (FR-PROV-06): a reasoning model that spends its output allowance thinking answers
  `content: null`. The error now names the finish reason; the reasoning is never taken as the
  answer and never echoed.

The response bodies below are shaped on what OpenRouter really returned for
`qwen/qwen3-30b-a3b` on 2026-10-02.
"""

from __future__ import annotations

import base64
import json

import pytest

from aeh.conf import ModelRef
from aeh.prov import (
    HttpResponse,
    LocalServerProvider,
    MalformedResponseError,
    OpenRouterProvider,
    PromptPayload,
    ProviderUnavailableError,
    RetryPolicy,
    SamplingParams,
)
from aeh.prov.live import IMAGE_FIELD, _fields_from_wire
from tests.support.prov_contract import CountingClock

OPENROUTER_REF = ModelRef(role="judge", provider="openrouter",
                          build_id="openrouter/qwen/qwen3-30b-a3b@2026-06-01", quantization=None)
LOCAL_REF = ModelRef(role="judge", provider="local",
                     build_id="/models/qwen3-30b-a3b-q4.gguf@sha256:" + "a" * 64, quantization="q4")
PARAMS = SamplingParams(temperature=0.0)
STUDENT_TEXT = "The block slides because friction is lower than gravity, ünïcode intact."
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n-not-a-real-image-").decode("ascii")


class _Transport:
    """Programmed responses, one per send (the last repeats); keeps every request."""

    def __init__(self, *responses: HttpResponse) -> None:
        self.responses = list(responses)
        self.requests: list = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        return self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]

    def bodies(self) -> list[dict]:
        return [json.loads(r.body.decode("utf-8")) for r in self.requests if r.method == "POST"]


def _openrouter_ok(content: object = '{"band": "met"}', **message_extra: object) -> HttpResponse:
    """An OpenRouter chat completion, as the real service shapes it."""
    return HttpResponse(200, {}, json.dumps({
        "id": "gen-1", "object": "chat.completion", "model": "qwen/qwen3-30b-a3b",
        "provider": "DeepInfra",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content, **message_extra}}],
        "usage": {"prompt_tokens": 14, "completion_tokens": 20, "cost": 0.00001168},
    }).encode("utf-8"))


def _openrouter(transport: _Transport) -> OpenRouterProvider:
    return OpenRouterProvider(base_url="https://openrouter.test/api/v1", api_key="sk-or-TEST",
                              transport=transport, clock=CountingClock(),
                              policy=RetryPolicy(3, 1, 120.0))


def _local(transport: _Transport) -> LocalServerProvider:
    return LocalServerProvider(base_url="http://127.0.0.1:8080/v1", transport=transport,
                               clock=CountingClock(), policy=RetryPolicy(3, 1, 120.0))


def _payload(*extra: tuple[str, str]) -> PromptPayload:
    return PromptPayload(fields=(
        ("directive", "Score one criterion. Reply with JSON."),
        ("criterion", "criterion_id: C1\ncriterion_text: names both forces"),
        *extra,
        ("submission", STUDENT_TEXT),
    ))


# --- TC-PROV-60 -------------------------------------------------------------------------------


@pytest.mark.parametrize("build", [_openrouter, _local], ids=["openrouter", "local"])
def test_tc_prov_60_the_body_is_chat_messages_one_per_field_in_order(build):
    transport = _Transport(_openrouter_ok())
    caller = _payload(("page_no", "1"))
    ref = OPENROUTER_REF if build is _openrouter else LOCAL_REF
    build(transport).complete(caller, ref, PARAMS)

    (body,) = transport.bodies()
    assert "prompt" not in body, "TC-PROV-60: the old `prompt.fields` body is still sent"
    assert [m["role"] for m in body["messages"]] == ["user"] * len(caller.fields)
    assert [m["name"] for m in body["messages"]] == [name for name, _ in caller.fields]
    # Each value verbatim: no label, template or whitespace change around it (CT-PROV-05).
    assert [m["content"] for m in body["messages"]] == [value for _, value in caller.fields]
    assert _fields_from_wire(body) == [list(f) for f in caller.fields]


def test_tc_prov_60_the_page_image_is_an_image_part_carrying_the_same_bytes():
    transport = _Transport(_openrouter_ok())
    caller = _payload((IMAGE_FIELD, PNG))
    _openrouter(transport).complete(caller, OPENROUTER_REF, PARAMS)

    (body,) = transport.bodies()
    (image,) = [m for m in body["messages"] if m["name"] == IMAGE_FIELD]
    assert image["content"] == [{"type": "image_url",
                                 "image_url": {"url": "data:image/png;base64," + PNG}}]
    assert _fields_from_wire(body) == [list(f) for f in caller.fields], (
        "TC-PROV-60: the image did not round-trip; the payload on the wire is not the caller's")


# --- TC-PROV-61 -------------------------------------------------------------------------------


def test_tc_prov_61_openrouter_is_sent_the_plain_slug_and_reports_what_served():
    transport = _Transport(_openrouter_ok())
    completion = _openrouter(transport).complete(_payload(), OPENROUTER_REF, PARAMS)

    (body,) = transport.bodies()
    assert body["model"] == "qwen/qwen3-30b-a3b"
    assert completion.resolved_build == "qwen/qwen3-30b-a3b"  # FR-PROV-04: as reported
    assert completion.cost is not None and str(completion.cost) == "0.00001168"


def test_tc_prov_61_a_local_server_is_still_sent_the_pinned_build_id():
    transport = _Transport(_openrouter_ok())
    _local(transport).complete(_payload(), LOCAL_REF, PARAMS)
    (body,) = transport.bodies()
    assert body["model"] == LOCAL_REF.build_id


# --- TC-PROV-62 -------------------------------------------------------------------------------


def _refusal(status: int, message: str) -> HttpResponse:
    return HttpResponse(status, {}, json.dumps(
        {"error": {"message": message, "code": status}}).encode("utf-8"))


@pytest.mark.parametrize("status, message, hint", [
    (401, "No auth credentials found", "OPENROUTER_API_KEY"),
    (402, "Insufficient credits", "insufficient credit"),
    (404, "No endpoints found for qwen/x", "not found"),
])
def test_tc_prov_62_a_run_wide_refusal_pauses_after_one_send(status, message, hint):
    """A refused key, an empty account or an unknown model refuses every unit alike, so the
    run pauses (dispatch reads `ProviderUnavailableError` as a pause, FR-ORCH-30)."""
    transport = _Transport(_refusal(status, message))
    with pytest.raises(ProviderUnavailableError) as caught:
        _openrouter(transport).complete(_payload(), OPENROUTER_REF, PARAMS)
    text = str(caught.value)
    assert f"HTTP {status}" in text and message in text and hint in text, text
    assert len(transport.requests) == 1, "TC-PROV-62: a run-wide refusal must not be retried"


@pytest.mark.parametrize("status, message", [
    (400, "This endpoint's maximum context length is 40960 tokens"),
    (403, "Input was flagged by moderation"),
    (413, "Payload too large"),
    (422, "Unprocessable request"),
])
def test_tc_prov_62_a_refusal_of_one_request_is_that_units_error_never_a_pause(status, message):
    """A refusal that belongs to one request (too long, flagged) must not pause the run: a
    paused run requeues the unit with its attempts untouched, meets the same refusal on resume,
    and one paper blocks the cohort. It is the unit's `MalformedResponseError`, retried within
    the budget, so the unit is struck and quarantines while the run goes on."""
    transport = _Transport(_refusal(status, message))
    with pytest.raises(MalformedResponseError) as caught:
        _openrouter(transport).complete(_payload(), OPENROUTER_REF, PARAMS)
    assert not isinstance(caught.value, ProviderUnavailableError)
    text = str(caught.value)
    assert f"HTTP {status}" in text and message in text, text
    assert len(transport.requests) == 3, "TC-PROV-62: the retry budget (3) bounds the sends"


def test_tc_prov_62_a_refusal_that_echoes_student_text_is_withheld():
    echo = f"bad request near: {STUDENT_TEXT[:40]}"
    transport = _Transport(_refusal(401, echo))
    with pytest.raises(ProviderUnavailableError) as caught:
        _openrouter(transport).complete(_payload(), OPENROUTER_REF, PARAMS)
    assert STUDENT_TEXT[:20] not in str(caught.value)
    assert "(body withheld)" in str(caught.value)


def test_tc_prov_62_a_408_is_retried():
    transport = _Transport(HttpResponse(408, {}, b"request timeout"), _openrouter_ok())
    completion = _openrouter(transport).complete(_payload(), OPENROUTER_REF, PARAMS)
    assert completion.text == '{"band": "met"}'
    assert len(transport.requests) == 2


def test_tc_prov_62_a_200_carrying_an_error_object_names_it():
    transport = _Transport(HttpResponse(200, {}, json.dumps(
        {"error": {"message": "upstream provider error", "code": 502}}).encode("utf-8")))
    with pytest.raises(MalformedResponseError) as caught:
        _openrouter(transport).complete(_payload(), OPENROUTER_REF, PARAMS)
    assert "upstream provider error" in str(caught.value)


# --- TC-PROV-63 -------------------------------------------------------------------------------


def test_tc_prov_63_a_reasoning_model_that_ran_out_of_output_says_so():
    thinking = "Okay, the user said reply with the word ready. So I need to just say"
    reply = json.loads(_openrouter_ok(content=None, reasoning=thinking).body)
    reply["choices"][0]["finish_reason"] = "length"
    transport = _Transport(HttpResponse(200, {}, json.dumps(reply).encode("utf-8")))
    with pytest.raises(MalformedResponseError) as caught:
        _openrouter(transport).complete(_payload(), OPENROUTER_REF, PARAMS)
    text = str(caught.value)
    assert "finish_reason='length'" in text and "reasoning" in text and "output cap" in text
    assert thinking not in text, "TC-PROV-63: the model's reasoning was echoed into an error"
