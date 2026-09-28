"""TS-127 (#538): M-PROV's shipped seams and counters, and the three #507 paths.

Test plan 1.7 §5.1. These write down behaviour that already ships, so they land green:
- TC-PROV-55 (FR-PROV-15): the constructor seams are behaviour-neutral, `on_dispatch` fires
  once per model call, and backoff is measured on the injected clock.
- TC-PROV-56 (FR-PROV-12 amended): the six counters are not a partition.
- TC-PROV-57/58/59 (#507, FR-PROV-41/43): a malformed key refused as `ConfigurationError`,
  408 retried, and the per-attempt `decision_provider_unreported` flag.
"""

from __future__ import annotations

import json
import time

import pytest

from aeh.conf import ConfigurationError, ModelRef
from aeh.prov import (HttpResponse, JevOpenRouterProvider, OpenRouterProvider, PromptPayload,
                      RunCountersTracker, SamplingParams)
from tests.support import jev_corpora
from tests.support.clock import FrozenClock



JEV_REF = ModelRef(role="decision", provider="openrouter-jev",
                   build_id="openrouter/typesafe/jev-1.13@2026-09-17", quantization="bf16")
WIRE = {b["id"]: b for b in jev_corpora.wire_bodies()}


class _Transport:
    """Programmed responses per send (the last repeats)."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.requests = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        outcome = self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _CountingClock:
    """Fake time: every wait is recorded and advances it, so backoff costs no real time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waited: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waited.append(seconds)
        self.now += seconds


def _completion(tokens_in: int = 100, cached: int = 0) -> HttpResponse:
    return HttpResponse(200, {}, json.dumps({
        "text": '{"band": "met"}', "model": "b1",
        "usage": {"prompt_tokens": tokens_in, "completion_tokens": 10,
                  "cached_prefix_tokens": cached},
    }).encode("utf-8"))


def _throttled() -> HttpResponse:
    return HttpResponse(429, {"Retry-After": "2"}, b"slow down")


def _payload() -> PromptPayload:
    return PromptPayload(fields=(("student_ref", "ref-007"), ("rubric", "States friction."),
                                 ("submission", "Friction pushes back.")))


def _ref() -> ModelRef:
    return ModelRef(role="judge", provider="openrouter", build_id="b1", quantization="q8")


@pytest.fixture(autouse=True)
def _retry_budget(monkeypatch):
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    for name in ("HARNESS_JEV_OPENROUTER_URL", "HARNESS_JEV_OPENROUTER_PROVIDER"):
        monkeypatch.delenv(name, raising=False)


# --- TC-PROV-55 (FR-PROV-15) ----------------------------------------------------------------------


def test_tc_prov_55_injected_seams_are_behaviour_neutral_and_on_dispatch_fires_per_call():
    """(a) Two builds over the same programmed 429→200 responses give the same completion and
    counters, whether or not `on_dispatch` is given. (b) `on_dispatch` fires once per model
    call (1 for a call answered 429 then 200). (c) Backoff waits land on the injected clock, not real time."""
    dispatched: list = []
    results = []
    for observer in (None, dispatched.append):
        clock = _CountingClock()
        provider = OpenRouterProvider(api_key="k", base_url="http://or/v1",
                                      transport=_Transport(_throttled(), _completion()),
                                      clock=clock, retention_answers=lambda build: "yes",
                                      on_dispatch=observer)
        started = time.monotonic()
        completion = provider.complete(_payload(), _ref(), SamplingParams(temperature=0.0))
        results.append((completion.text, provider.counters, clock.waited))
        assert time.monotonic() - started < 1.0, "backoff slept in real time, not on the injected clock"
    assert results[0] == results[1], (
        f"supplying on_dispatch changed the outcome: {results[0]!r} vs {results[1]!r} (FR-PROV-15: "
        "the seams are behaviour-neutral)"
    )
    # FR-PROV-15: "once per dispatched model call" — the call, not each attempt of it.
    assert len(dispatched) == 1, f"on_dispatch fired {len(dispatched)} times for one call (429 then 200); expected 1"
    assert results[0][2], "a 429 with Retry-After recorded no wait on the injected clock"


# --- TC-PROV-56 (FR-PROV-12 amended) --------------------------------------------------------------


def test_tc_prov_56_the_counters_are_not_a_partition():
    """429, 429, then 200 on one call, then 200 on a second: `transport_retries` counts both
    retried attempts, `rate_limited_calls` counts the one call that was throttled, and
    `cache_hit_rate` is token-weighted over the run."""
    provider = OpenRouterProvider(
        api_key="k", base_url="http://or/v1",
        transport=_Transport(_throttled(), _throttled(), _completion(1000, 400), _completion(500, 0)),
        clock=_CountingClock(), retention_answers=lambda build: "yes")
    provider.complete(_payload(), _ref(), SamplingParams(temperature=0.0))
    provider.complete(_payload(), _ref(), SamplingParams(temperature=0.0))
    counters = provider.counters
    assert counters.transport_retries == 2, counters
    assert counters.rate_limited_calls == 1, (
        f"rate_limited_calls is {counters.rate_limited_calls}: it counts CALLS throttled at "
        "least once, not throttled attempts"
    )
    assert counters.cache_hit_rate == pytest.approx(400 / 1500), counters


# --- TC-PROV-57 / 58 / 59 (#507) ------------------------------------------------------------------


def _jev(transport, **kw) -> JevOpenRouterProvider:
    return JevOpenRouterProvider(api_key=kw.pop("api_key", "sk-or-TEST"), transport=transport,
                                 clock=FrozenClock(), **kw)


def _good() -> HttpResponse:
    body = {**WIRE["cloud-well-formed-reported"]["body"], "model": "typesafe/jev-1.13",
            "provider": "TypeSafe"}
    return HttpResponse(200, {}, json.dumps(body).encode("utf-8"))


def _unreported() -> HttpResponse:
    body = {k: v for k, v in WIRE["cloud-well-formed-reported"]["body"].items() if k != "provider"}
    body["model"] = "typesafe/jev-1.13"
    return HttpResponse(200, {}, json.dumps(body).encode("utf-8"))


@pytest.mark.parametrize("key", ["sk or with space", "   "])
def test_tc_prov_57_a_malformed_key_is_a_configuration_error_with_no_send(key):
    transport = _Transport(_good())
    with pytest.raises(ConfigurationError) as caught:
        _jev(transport, api_key=key).decide(jev_corpora.wire_request(), JEV_REF)
    assert not any(type(link).__module__.startswith("typesafe_sdk")
                   for link in (caught.value, caught.value.__cause__, caught.value.__context__)
                   if link is not None), "an SDK exception type reached the caller"
    assert transport.requests == [], f"{len(transport.requests)} send(s) with a malformed key"


def test_tc_prov_58_a_408_is_retried():
    transport = _Transport(HttpResponse(408, {}, b"request timeout"), _good())
    counters = RunCountersTracker()
    decision = _jev(transport, counters=counters).decide(jev_corpora.wire_request(), JEV_REF)
    assert decision is not None
    assert len(transport.requests) == 2, f"{len(transport.requests)} sends; 408 must be retried once"
    assert counters.decision_snapshot().decision_transport_retries == 1


@pytest.mark.parametrize("first, second, expected", [
    ("unavailable_unreported", "good", 0),
    ("unreported", None, 1),
])
def test_tc_prov_59_the_unreported_flag_is_per_attempt(first, second, expected):
    """A failed attempt whose body lacked `provider` does not count; a served answer that
    lacked it does."""
    responses = {
        "unavailable_unreported": HttpResponse(503, {}, b'{"error": {"message": "busy"}}'),
        "good": _good(),
        "unreported": _unreported(),
    }
    programmed = [responses[first]] + ([responses[second]] if second else [])
    counters = RunCountersTracker()
    _jev(_Transport(*programmed), counters=counters).decide(jev_corpora.wire_request(), JEV_REF)
    assert counters.decision_snapshot().decision_provider_unreported == expected
