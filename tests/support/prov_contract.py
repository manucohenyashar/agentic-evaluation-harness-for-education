"""Shared builders for the `M-PROV` substitutability suite (TS-06, issue #23).

The clause suite of test plan §6.11.2 is **parametrized over
`[RecordedFixtureProvider, LocalServerProvider, OpenRouterProvider]`** and, since the 2026-09-02
re-sync of issue #23, over **construction** as well: each implementation built once with the
`FR-PROV-15` seams supplied and once with them defaulted. Everything the two axes need lives
here, so the clause tests stay a table of assertions rather than a tangle of setup.

The construction axis, and what "defaulted" can mean in a test
--------------------------------------------------------------
`FR-PROV-15` (design v1.5): the real providers take `transport`, `clock`, `retention_answers`
and `on_dispatch` as constructor arguments defaulting to the real ones, behaviour-neutrally —
and `TC-PROV-06` is the only case that can break that promise, because every other `M-PROV`
case builds the provider with doubles. A provider that skips retry, loses a counter, or waits
on a real clock only on its **default** path passes all of them.

One of the four seams cannot be defaulted in any test that dispatches: the defaulted transport
is `_DefaultTransport`, the module's real egress point (`CT-PROV-15`), and dispatching through
it is a network call. So the DEFAULTED variant keeps the transport programmed — the one seam a
test must own — and defaults the rest. The default retention path is *not* excluded by this:
`OpenRouterProvider` with `retention_answers=None` sources its answers over `self._transport`,
so the programmed transport answers the `GET /retention/<build>` and the default path runs for
real.

The DEFAULTED variant deliberately induces its retries with `Retry-After: 0`. The default
clock is `SystemClock`, which sleeps for real, and test plan §4.6 makes TC-ORCH-09 the suite's
one sanctioned sleep; a zero-second honoured wait exercises the clock seam (`sleep` is called,
`rate_limit_wait_s` accumulates) without spending any. Budget exhaustion on the default policy
is exercised with `HARNESS_RETRY_MAX=1` (monkeypatched), so a from_environment policy is read
while nothing sleeps at all.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from decimal import Decimal

from aeh.conf import ModelRef
from aeh.prov import (
    HttpRequest,
    HttpResponse,
    LocalServerProvider,
    OpenRouterProvider,
    RecordedFixtureProvider,
    RetryPolicy,
    SamplingParams,
)

#: The two constructions of the `FR-PROV-15` axis. `INJECTED` supplies every seam as a test
#: double (the shape every other `M-PROV` case builds); `DEFAULTED` defaults everything but
#: the transport, which is the one seam a test cannot default without egress.
INJECTED = "injected"
DEFAULTED = "defaulted"

CONSTRUCTIONS = (INJECTED, DEFAULTED)

#: The three implementations of the implementation axis (§6.11.2's parametrization).
IMPL_IDS = ("fixture", "local", "openrouter")


# --- the programmed transport -------------------------------------------------------------------


@dataclass
class ScriptedTransport:
    """A transport programmed per call: each `complete` consumes one list of attempt outcomes.

    The same shape TS-05's suite uses, rebuilt here rather than imported because the clause
    suite also needs to *answer* requests it did not pre-script — the defaulted OpenRouter
    retention path (`GET /retention/<build>`) and the live-tier differential both ask for a
    `default=` behaviour beside the script. GETs (the retention lookup) are answered from
    `get_default`, which keeps "attempts" meaning model-call attempts only.
    """

    script: list = field(default_factory=list)  # per-call lists of responses / exceptions
    default: object = None                      # answered when a call's script is exhausted
    get_default: object = None                  # answered for non-POST (retention) requests
    #: A clock and a per-attempt provider latency: the transport moves the clock by
    #: `latency_s` on every POST, the way a real backend spends real time. `_dispatch`
    #: measures latency through the clock seam, so a test asserting a measured latency
    #: programs it HERE — the transport is what a latency is a property of.
    clock: object = None
    latency_s: float = 0.0
    calls: int = 0
    attempts: int = 0
    requests: list = field(default_factory=list)

    def send(self, request: HttpRequest):
        self.requests.append(request)
        # The defaulted retention path arrives as a GET; it is not a scripted completion call.
        if request.method != "POST":
            if isinstance(self.get_default, Exception):
                raise self.get_default
            return self.get_default
        if self.clock is not None and self.latency_s:
            self.clock.sleep(self.latency_s)
        self.attempts += 1
        script = self.script[self.calls] if self.calls < len(self.script) else None
        if script is None:
            outcome = self.default
        else:
            outcome = script[min(self.attempts - 1, len(script) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def next_call(self) -> None:
        self.calls += 1
        self.attempts = 0


class CountingClock:
    """Advances fake time and records every wait — the injected half of the clock seam.

    The DEFAULTED construction does not use this class: it gets `SystemClock`, which is the
    point of the axis. This is what INJECTED supplies instead, so `rate_limit_wait_s` stays
    assertable without a real sleep (§4.6).
    """

    def __init__(self) -> None:
        self.now = 0.0
        self.waited: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waited.append(seconds)
        self.now += seconds


# --- the one request every implementation is asked ------------------------------------------------

PANEL_BUILD = "/models/llama-3.3-70b.gguf@sha256:aaaa"
SERVED_BUILD = "llama-3.3-70b@q4"

STUDENT_REF = "ref-007"
#: The submission carries a non-ASCII byte deliberately: CT-PROV-05 forbids unicode
#: renormalization on the wire, and an ASCII-only payload would pass an implementation that
#: normalized anyway.
SUBMISSION = "The block slides because friction is lower than gravity — ünïcode intact."

CRITERION = "States that friction opposes motion."


def payload(payload_cls):
    """The assembled prompt, submission last (`FR-JUDGE-07` / `FR-EXTRACT-04`)."""
    return payload_cls(
        fields=(
            ("system", "You are scoring one criterion."),
            ("student_ref", STUDENT_REF),
            ("criterion", CRITERION),
            ("submission", SUBMISSION),
        )
    )


def params() -> SamplingParams:
    return SamplingParams(temperature=0.0)


def model_ref() -> ModelRef:
    return ModelRef(role="judge", provider="ollama", build_id=PANEL_BUILD, quantization="q4")


def completion(text: str = '{"band": "met"}', **overrides):
    """A fully-populated `Completion` for `record()` — cost is None (CT-PROV-03)."""
    from aeh.prov import Completion

    values = dict(
        text=text,
        tokens_in=1800,
        tokens_out=12,
        latency_ms=430,
        resolved_build=SERVED_BUILD,
        cached_prefix_tokens=1500,
        cost=None,
    )
    values.update(overrides)
    return Completion(**values)


# --- the wire shapes the live implementations speak -------------------------------------------------


def flat_ok(text: str = '{"band": "met"}', build: str = SERVED_BUILD, tokens_in: int = 1800,
            tokens_out: int = 12, cached: int = 1500) -> HttpResponse:
    """The module's own flat response shape: text verbatim, usage beside it, build in `model`."""
    return HttpResponse(200, {}, json.dumps({
        "text": text,
        "model": build,
        "usage": {
            "prompt_tokens": tokens_in,
            "completion_tokens": tokens_out,
            "cached_prefix_tokens": cached,
        },
    }).encode("utf-8"))


# --- the construction axis -------------------------------------------------------------------------


def make_provider(impl: str, construction: str, transport: ScriptedTransport,
                  fixture_dir=None, *, clock=None, rng=None, policy: RetryPolicy | None = None,
                  on_dispatch=None, build_watch=None):
    """Build one implementation under one construction of the `FR-PROV-15` axis.

    `fixture` has no seams to vary (`RecordedFixtureProvider` takes only `fixture_dir`), so
    both constructions of that axis produce the same object — the differential across
    construction is defined for the two live implementations, which is where `FR-PROV-15`
    places it.
    """
    if impl == "fixture":
        return RecordedFixtureProvider(fixture_dir=fixture_dir)
    if impl == "local":
        if construction == INJECTED:
            return LocalServerProvider(
                base_url="http://local/v1", transport=transport,
                clock=clock if clock is not None else CountingClock(),
                rng=rng if rng is not None else random.Random(20260907),
                policy=policy, build_watch=build_watch,
            )
        return LocalServerProvider(base_url="http://local/v1", transport=transport)
    if impl == "openrouter":
        if construction == INJECTED:
            return OpenRouterProvider(
                base_url="http://or/v1", api_key="sentinel-api-key-not-a-credential",
                transport=transport,
                clock=clock if clock is not None else CountingClock(),
                rng=rng if rng is not None else random.Random(20260907),
                policy=policy, build_watch=build_watch,
                retention_answers=lambda build: "yes",
                on_dispatch=on_dispatch,
            )
        # retention_answers stays None on purpose: the default path sources its answers over
        # the injected transport, which serves the GET from `default`.
        return OpenRouterProvider(
            base_url="http://or/v1", api_key="sentinel-api-key-not-a-credential",
            transport=transport,
        )
    raise ValueError(f"unknown implementation {impl!r}")


# --- the credential sentinel ------------------------------------------------------------------------

#: CT-PROV-13: no credential appears in any log line, exception message or returned value.
#: The value below is what every sentinel sweep in the suite looks for. It is carried by the
#: OpenRouter provider under `api_key=`, so a leak means the key reached a surface the clause
#: forbids.
CREDENTIAL_SENTINEL = "sk-sentinel-credential-never-log-me-3f9a"


def make_openrouter_with_sentinel(transport, **seams):
    """An OpenRouterProvider carrying the credential sentinel on its real seam."""
    return OpenRouterProvider(
        base_url="http://or/v1", api_key=CREDENTIAL_SENTINEL,
        transport=transport, **seams,
    )


# --- cost figures (CT-PROV-03) -----------------------------------------------------------------------

#: OpenRouter's declared per-token rates, from the module's own capabilities. A cloud
#: `Completion.cost` is derived from measured usage at these rates; `0` is not among the
#: expected values, because *not measured* and *measured zero* are different facts.
EXPECTED_OR_COST = Decimal("1800") * Decimal("0.000001") + Decimal("12") * Decimal("0.000002")
