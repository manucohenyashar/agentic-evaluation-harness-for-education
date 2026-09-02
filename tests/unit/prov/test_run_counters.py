"""The six run counters, against a hand-counted reference.

Case: `TC-PROV-18` (`FR-PROV-12`, P1, Observability, rung 1, test plan §5.2). Issue #24
(TS-07).

`FR-PROV-12`: *"The module shall count and expose `transport_retries`, `rate_limited_calls`,
`rate_limit_wait_s`, `tokens_in`, `tokens_out`, and `cache_hit_rate` for persistence into
`run_metrics`."* `CT-PROV-14` makes the **names** contract, not merely the values, and says why:
`cache_hit_rate` is consumed as an alert signal, and HLD §9.7 is explicit that a drop below the
run's historical band is a build failure rather than a curiosity — the symptom of losing prefix
ordering is a fivefold slowdown with **no error raised** (RISK-23). Rename the counter and
RISK-23 loses its only detector.

**Written ahead of implementation** (issue #20, which owns `FR-PROV-12`). Expected to fail with
`NotImplementedYet` until it lands. Remove the `writtenahead` marker — not the test — when #20
closes.

Why #20 and not #19
--------------------
The counters cannot be exercised without the retry loop that produces the retries (#19), so both
must have landed. The registry's discriminating question is *which single blocker, resolved,
means this test can run* — and #20 is the answer, because `transport_retries` cannot be
implemented before there is a retry to count. #19 therefore lands first by construction, and
keying on #19 would fire while the counters were still months away.

Interface expectations this test places on #19 and #20
-------------------------------------------------------
Every name below is now **in the design**. Four of them were not when this file was written; they
were raised as findings in PR #161 and answered by detailed design v1.5 / test plan v1.3, so the
table records where each is fixed rather than what this file assumed.

| Name | Status in the design |
|---|---|
| `transport_retries`, `rate_limited_calls`, `rate_limit_wait_s`, `tokens_in`, `tokens_out`, `cache_hit_rate` | defined, `FR-PROV-12` verbatim; `CT-PROV-14` makes them contract |
| `RecordedFixtureProvider`, `LocalServerProvider` | defined, design §3.2 |
| `counters()` on the provider, returning `RunCounters` | **defined in v1.5** — `FR-PROV-12` and `CT-PROV-11`. Previously the design named the six counters and never the surface exposing them |
| A programmable transport seam (`transport=`) | **defined in v1.5** — `FR-PROV-15`, and plan §4.2 now splits its network-failure row accordingly. See the note below |
| An injected clock (`clock=`) | **defined in v1.5** — `FR-PROV-15`. Plan §4.2's clock row had listed `backoff` since v1.0; only §3.2 was silent |

Two **semantic** expectations. Both were open when this file was written and both are now pinned
by `FR-PROV-12`, so a correct implementation can no longer disagree with them:

| Assumption | Why it is the reading taken here | Where it is settled |
|---|---|---|
| A 429-provoked retry increments `transport_retries` **as well as** `rate_limited_calls` | `FR-PROV-06` classifies 429 as one of the retryable transport-class failures, so every attempt beyond the first is a transport retry; `rate_limited_calls` then answers a different question — *how many calls were throttled* — rather than partitioning the same total | `FR-PROV-12` (v1.5): *"the six are not a partition"*. The design's own alert on `rate_limited_calls` as a **share of dispatch** decided it — a share needs a per-call throttle count, not a slice of the retry total. The partitioning reading would have given 15 here rather than 35 |
| `cache_hit_rate` is token-weighted: `cached_prefix_tokens / tokens_in` | `NFR-JUDGE-01` and `TC-JUDGE-21` both state it against token counts (about 1,500 of roughly 1,800), and `TC-PROV-C14` requires a rate in `[0,1]` | `FR-PROV-12` (v1.5) states the formula and that it is *"a rate in `[0,1]`, never a count"* |

Why the double is a transport and not a provider
--------------------------------------------------
`TC-PROV-18`'s precondition is a 200-call synthetic run with programmed 429s and retries.
Programming a 429 means reaching inside the provider, and §4.2's doubles table used to offer only
*"stub provider raising the taxonomy"* — which cannot serve, because a stub *provider* replaces
the very code that does the counting. The counters live in the real provider; only its transport
may be doubled. Plan v1.3 splits that row in two for exactly this reason, and `FR-PROV-15` is the
seam.

The `require_attr` call for `counters` still comes **first** in the test body: until #20 lands,
this fails naming the requirement's own surface rather than a constructor argument.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from tests.support.impl import PROVIDER_MODULE, require, require_attr

pytestmark = pytest.mark.writtenahead

CONF_MODULE = "aeh.conf"
ISSUE = "#20"

#: `FR-PROV-12`, verbatim and in order. `CT-PROV-14` makes this list contract.
COUNTER_NAMES = (
    "transport_retries",
    "rate_limited_calls",
    "rate_limit_wait_s",
    "tokens_in",
    "tokens_out",
    "cache_hit_rate",
)

# --- the hand-computed reference (the oracle §5.2 names) ----------------------------------------
#
# A 200-call synthetic run. Every figure below is chosen so the expected counter value is
# arithmetic a reader can check in their head, which is what "hand-computed reference" means:
# a reference produced by the same code path it is checking proves only that the code agrees
# with itself.

CALLS = 200

#: 20 calls are answered 429 once each, then succeed. Each carries `Retry-After: 2`.
RATE_LIMITED_CALLS = 20
RETRY_AFTER_S = 2

#: 15 further calls fail at the transport once each, then succeed.
TRANSPORT_FAILED_CALLS = 15

#: Every attempt beyond the first is a retry, whatever provoked it: 20 + 15.
EXPECTED_TRANSPORT_RETRIES = RATE_LIMITED_CALLS + TRANSPORT_FAILED_CALLS
EXPECTED_RATE_LIMIT_WAIT_S = RATE_LIMITED_CALLS * RETRY_AFTER_S  # 40

#: Per successful call. 1,500 of the 1,800 input tokens are the invariant prefix — HLD §8.4's
#: figures, and the ones `TC-JUDGE-21` uses.
TOKENS_IN_PER_CALL = 1_800
TOKENS_OUT_PER_CALL = 12
CACHED_PREFIX_TOKENS_PER_CALL = 1_500

EXPECTED_TOKENS_IN = CALLS * TOKENS_IN_PER_CALL  # 360,000
EXPECTED_TOKENS_OUT = CALLS * TOKENS_OUT_PER_CALL  # 2,400
EXPECTED_CACHE_HIT_RATE = CACHED_PREFIX_TOKENS_PER_CALL / TOKENS_IN_PER_CALL  # 0.8333…


def _counter_mapping(provider) -> Mapping[str, float]:
    """The six counters as a mapping, whatever container #20 chooses to return them in.

    Normalizes the *container* and nothing else: the assertions below still demand all six
    names and their exact values, so this concedes nothing `CT-PROV-14` asserts. A method, a
    property, a mapping and a value object are all reasonable choices for #20 to make, and a
    test that fixed one of them would fail against a correct implementation over a detail the
    design never specified.
    """
    accessor = require_attr(type(provider), "counters", issue=ISSUE)
    value = accessor(provider) if callable(accessor) else getattr(provider, "counters")
    if isinstance(value, Mapping):
        return value
    return {name: getattr(value, name) for name in COUNTER_NAMES if hasattr(value, name)}


def test_tc_prov_18_the_six_run_counters_match_a_hand_counted_reference(
    network_guard, frozen_clock
):
    """TC-PROV-18 — 200 calls, 20 programmed 429s and 15 transport failures, counted by hand.

    Oracle (§5.2): *hand-computed reference*. Every expectation is a module constant above,
    derived by arithmetic a reader can check, never by re-running the implementation.

    Three assertions, and the first two are as important as the third:

    1. **The names.** All six are present under exactly the `FR-PROV-12` spellings.
       `CT-PROV-14` makes this contract because `cache_hit_rate` is RISK-23's only detector.
    2. **`cache_hit_rate` is a rate.** `TC-PROV-C14` says it explicitly — *"the value is a hit
       rate in `[0,1]`, not a count"*. A counter that silently became a count would keep the
       name, keep passing a presence check, and make every historical-band alert meaningless.
    3. **The values**, against the reference.
    """
    ModelRef = require(CONF_MODULE, "ModelRef", issue=ISSUE)
    LocalServerProvider, PromptPayload, SamplingParams = require(
        PROVIDER_MODULE,
        "LocalServerProvider",
        "PromptPayload",
        "SamplingParams",
        issue=ISSUE,
    )

    transport = _ProgrammedTransport(
        rate_limited=RATE_LIMITED_CALLS,
        retry_after_s=RETRY_AFTER_S,
        transport_failures=TRANSPORT_FAILED_CALLS,
        tokens_in=TOKENS_IN_PER_CALL,
        tokens_out=TOKENS_OUT_PER_CALL,
        cached_prefix_tokens=CACHED_PREFIX_TOKENS_PER_CALL,
    )
    # The clock is injected, not slept through. Honouring `Retry-After: 2` twenty times is 40
    # seconds of real time; §4.6 makes TC-ORCH-09 the one sanctioned sleep in this suite, and a
    # 40-second unit test is how a fast tier stops being run. If #19 waits on a real clock
    # instead, `rate_limit_wait_s` is either a 40-second test or a fabricated number.
    provider = LocalServerProvider(transport=transport, clock=frozen_clock)  # FR-PROV-15
    # Fails here, naming #20, until FR-PROV-12 lands — before any invented seam is touched.
    _counter_mapping(provider)

    model_ref = ModelRef(
        role="judge",
        provider="ollama",
        build_id="/models/llama-3.3-70b.gguf@sha256:aaaa",
        quantization="q4",
    )
    params = SamplingParams(temperature=0.0)
    for index in range(CALLS):
        payload = PromptPayload(
            fields=(
                ("system", "You are scoring one criterion."),
                ("criterion", "States that friction opposes motion."),
                ("submission", f"answer {index}"),
            )
        )
        provider.complete(payload, model_ref, params)

    counters = _counter_mapping(provider)

    assert set(COUNTER_NAMES) <= set(counters), (
        "FR-PROV-12 names these six counters and CT-PROV-14 makes the names contract — "
        "cache_hit_rate is RISK-23's only detector. Missing: "
        f"{sorted(set(COUNTER_NAMES) - set(counters))}"
    )

    assert 0.0 <= counters["cache_hit_rate"] <= 1.0, (
        "cache_hit_rate is a rate in [0,1], not a count (TC-PROV-C14). A count under this name "
        f"makes every historical-band alert meaningless. Got {counters['cache_hit_rate']!r}"
    )

    # See the module docstring's semantic-assumptions table: this reading counts a 429-provoked
    # retry in both counters. A #20 that partitions them instead reports 15 and is not wrong.
    assert counters["transport_retries"] == EXPECTED_TRANSPORT_RETRIES
    assert counters["rate_limited_calls"] == RATE_LIMITED_CALLS
    assert counters["rate_limit_wait_s"] == pytest.approx(EXPECTED_RATE_LIMIT_WAIT_S)
    assert counters["tokens_in"] == EXPECTED_TOKENS_IN
    assert counters["tokens_out"] == EXPECTED_TOKENS_OUT
    assert counters["cache_hit_rate"] == pytest.approx(EXPECTED_CACHE_HIT_RATE, rel=1e-3)

    # Rung 1: the transport is a fake, so nothing may reach a socket even here.
    network_guard.assert_no_network()


class _ProgrammedTransport:
    """A transport that produces 429s and connection failures on a fixed schedule.

    Deterministic rather than random: §4.6 requires a reproducible suite, and a hand-computed
    reference is only checkable against a schedule a reader can follow. The first
    `rate_limited` calls are answered 429-then-success; the next `transport_failures` calls are
    answered failure-then-success; the rest succeed first time.

    The seam is `FR-PROV-15`'s `transport=`, added by design v1.5 in answer to this file's own
    PR finding. `Transport.send(request) -> TransportResponse` and the `status`/`headers`/`body`
    shape below are §3.2's; the *schedule* is this test's.
    """

    def __init__(
        self,
        *,
        rate_limited: int,
        retry_after_s: int,
        transport_failures: int,
        tokens_in: int,
        tokens_out: int,
        cached_prefix_tokens: int,
    ) -> None:
        self.rate_limited = rate_limited
        self.retry_after_s = retry_after_s
        self.transport_failures = transport_failures
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cached_prefix_tokens = cached_prefix_tokens
        self.calls = 0
        self.attempts = 0

    def send(self, request):  # noqa: ANN001 — TransportRequest's fields are #19's
        """One transport attempt. Raises the programmed failure, or returns a response body."""
        self.attempts += 1
        index = self.calls
        first_attempt_for_this_call = not getattr(self, "_retried", False)

        if index < self.rate_limited and first_attempt_for_this_call:
            self._retried = True
            return _Response(status=429, headers={"Retry-After": str(self.retry_after_s)})
        if (
            self.rate_limited <= index < self.rate_limited + self.transport_failures
            and first_attempt_for_this_call
        ):
            self._retried = True
            raise ConnectionResetError("programmed transport failure")

        self._retried = False
        self.calls += 1
        return _Response(
            status=200,
            body={
                "text": '{"band": "met"}',
                "usage": {
                    "prompt_tokens": self.tokens_in,
                    "completion_tokens": self.tokens_out,
                    "cached_prefix_tokens": self.cached_prefix_tokens,
                },
                "model": "llama-3.3-70b@q4",
            },
        )


class _Response:
    """The minimum a transport hands back — design §3.2's `TransportResponse` (`FR-PROV-15`)."""

    def __init__(self, *, status: int, body: dict | None = None, headers: dict | None = None):
        self.status = status
        self.body = body or {}
        self.headers = headers or {}
