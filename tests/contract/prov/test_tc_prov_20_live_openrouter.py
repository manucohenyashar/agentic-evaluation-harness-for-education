"""TC-PROV-20 — the clause suite against live OpenRouter on E2, nightly.

Case: `TC-PROV-20` (`NFR-PROV-01`, `FR-PROV-11`, P1, **nightly**, Integration-live, rung 2,
test plan §5.2 and §6.11.2). Issue #23 (TS-06).

The OpenRouter half of the nightly replay: the same clause caller the fast tier runs, against
the real hosted backend — and the one place the suite **observes real 429 behaviour** rather
than programming it. Synthetic corpora only (FR-CONFORM-02): the payload below is the
synthetic scoring payload, never real student work.

Which clause halves run here, and which cannot
----------------------------------------------
Implemented against the live backend: the run-start retention gate and its ordering
(`CT-PROV-13`), the Completion shape and its cost nullability (`CT-PROV-03`), the wire
byte-identity of the dispatched payload (`CT-PROV-05`) and one-call-one-dispatch
(`CT-PROV-01`) — captured through a recording proxy around the module's real transport —
plus the fixture replay differential and the 429 observation. What *cannot* run here: the
failure-injection rows (429/5xx/timeout decision tables, `CT-PROV-06`/`-07`'s negative
cells) — a real backend cannot be programmed to fail on schedule, which is why those rows
live in the fast tier over the seam and why this file observes rather than provokes.

The run-start gate is part of the case, not scaffolding: a `cloud-hosted` run does not start
until zero-retention is confirmed for every panel member (FR-PROV-14, `CT-PROV-13`), so
**every dispatching test in this file clears the gate first**. Fail-closed is the gate
working — an unconfigured nightly fails naming the gate, it does not dispatch.

Environment: E2. Like `TC-PROV-19`, this case has **never been executed** — there is no
OpenRouter credential in this repository. It is written against the design's interface so
whoever stands E2 up inherits the assertion. Marked `live`, `slow` and `integration`; the
fast tier never selects it.
"""

from __future__ import annotations

import dataclasses
import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from aeh.conf import ModelRef
from aeh.prov import (
    ProviderError,
    PromptPayload,
    SamplingParams,
)
from tests.support.prov_contract import payload as contract_payload

pytestmark = [pytest.mark.live, pytest.mark.slow, pytest.mark.integration]

ISSUE = "#23"

#: The 429 observation load. Deliberately small: the case *observes* real 429 behaviour, it
#: does not manufacture it — asserting that a 429 occurred would make the nightly flaky by
#: construction. Env-gated per seam 3.
PROBES = int(os.environ.get("HARNESS_LIVE_429_PROBES", "6"))
PROBE_CONCURRENCY = int(os.environ.get("HARNESS_LIVE_429_CONCURRENCY", "2"))


def _live_provider(transport=None):
    from aeh.prov import OpenRouterProvider

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        pytest.fail(
            "TC-PROV-20 runs on E2 against live OpenRouter; set OPENROUTER_API_KEY. "
            "Skipping would let the nightly tier report green without ever comparing the "
            "real backend to the double the whole fast tier runs on (RISK-37)."
        )
    confirmed = os.environ.get("HARNESS_LIVE_RETENTION_CONFIRMED", "")
    confirmed_builds = {b.strip() for b in confirmed.split(",") if b.strip()}
    # The retention source is the nightly operator's declaration (FR-PROV-15's seam). An
    # undeclared confirmation is fail-closed: the gate refuses, nothing dispatches, and the
    # failure below says exactly that rather than working around the gate.
    return OpenRouterProvider(api_key=api_key, transport=transport,
                              retention_answers=lambda build: (
                                  "yes" if "*" in confirmed_builds
                                  or build in confirmed_builds else "unknown"))


def _live_model_ref() -> ModelRef:
    return ModelRef(
        role="judge",
        provider="openrouter",
        build_id=os.environ.get("HARNESS_LIVE_BUILD_ID", "openai/gpt-4o-mini"),
        quantization=None,
    )


def _gate_cleared_provider(transport=None):
    """The provider, **after** the run-start gate has confirmed the panel member.

    Every dispatching test goes through here — a `cloud-hosted` run does not start
    unconfirmed (FR-PROV-14, `CT-PROV-13`), and the nightly is not exempt from its own
    clause. On an unconfigured nightly this is where every test below stops: the gate
    refuses, nothing has been dispatched, and the failure names the missing declaration.
    """
    from aeh.prov import RetentionPolicyError

    provider = _live_provider(transport)
    ref = _live_model_ref()
    try:
        report = provider.require_retention([ref])
    except RetentionPolicyError as error:
        pytest.fail(
            "TC-PROV-20: the run-start gate refused — zero-retention is not confirmed for "
            f"{ref.build_id!r} ({error}). Declare it with HARNESS_LIVE_RETENTION_CONFIRMED. "
            "Nothing was dispatched; a cloud-hosted run does not start unconfirmed."
        )
    assert report.all_confirmed
    return provider


def test_tc_prov_20_the_gate_holds_before_anything_dispatches():
    """TC-PROV-20, run-start half: zero-retention is confirmed for the panel member before
    the first dispatch, or the run does not start. On an unconfigured nightly this is the
    failure that fires — the gate refusing is the defense working, and the nightly stays
    red until an operator declares the confirmation."""
    provider = _live_provider()
    ref = _live_model_ref()
    try:
        report = provider.verify_retention([ref])
    except ProviderError as error:
        pytest.fail(
            "TC-PROV-20: the run-start gate refused — zero-retention is not confirmed for "
            f"{ref.build_id!r} ({error}). Declare it with HARNESS_LIVE_RETENTION_CONFIRMED. "
            "Nothing was dispatched; a cloud-hosted run does not start unconfirmed."
        )
    assert report.all_confirmed


def test_tc_prov_20_the_clause_caller_runs_unchanged_against_live_openrouter():
    """TC-PROV-20 — the same caller, the real backend: a fully-populated `Completion` with
    a non-null cost (CT-PROV-03 puts null on edge-local and fixture only), a **measured**
    latency, and a reported resolved build (`FR-PROV-04`)."""
    provider = _gate_cleared_provider()
    ref = _live_model_ref()
    params_ = SamplingParams(temperature=0.0)
    payload = contract_payload(PromptPayload)

    got = provider.complete(payload, ref, params_)
    for field_name in ("text", "tokens_in", "tokens_out", "latency_ms", "resolved_build",
                       "cached_prefix_tokens"):
        value = getattr(got, field_name)
        assert value is not None, (
            f"TC-PROV-20: Completion.{field_name} is None from the live backend. The real "
            "backend must populate every field the double populates (CT-PROV-03) — a "
            "difference here is RISK-37's drift, and the fast tier has been describing a "
            "system that does not exist."
        )
    from decimal import Decimal

    assert isinstance(got.cost, Decimal) and got.cost > 0, (
        "TC-PROV-20: cloud-hosted cost is not a positive Decimal. CT-PROV-03: null on "
        "edge-local and fixture only — on cloud, not-measured and measured-zero are both "
        "defects."
    )
    assert got.latency_ms > 0, (
        "TC-PROV-20: a real model call reported zero latency. Latency is measured through "
        "the clock seam (FR-PROV-01) — a constant 0 here is the fast tier's double "
        "describing a server that answers instantly."
    )

    caps = provider.capabilities(ref)
    assert caps.max_concurrency >= 1


def test_tc_prov_20_the_wire_carries_the_payload_byte_for_byte(tmp_path):
    """TC-PROV-20, `CT-PROV-05` live half: the payload on the real wire is the caller's,
    byte for byte, and one `complete` is one dispatch (`CT-PROV-01`) — the two checks most
    likely to catch a real backend's SDK-shaped divergence, captured through a recording
    proxy around the module's own real transport."""
    from aeh.prov import _DefaultTransport  # the module's sole egress point (CT-PROV-15)

    class _Recording:
        """Forwards to the real transport, keeping the wire the provider dispatched."""

        def __init__(self):
            self._inner = _DefaultTransport()
            self.requests = []
            self.attempts = 0

        def send(self, request):
            self.requests.append(request)
            self.attempts += 1
            return self._inner.send(request)

    recording = _Recording()
    provider = _gate_cleared_provider(transport=recording)
    ref = _live_model_ref()
    caller = contract_payload(PromptPayload)
    provider.complete(caller, ref, SamplingParams(temperature=0.0))

    assert recording.attempts == 1, (
        f"TC-PROV-20: one complete() made {recording.attempts} dispatches against the real "
        "backend. One call is one model call (CT-PROV-01) — the nightly is where a "
        "batching or SDK-retry layer would show itself."
    )
    posts = [r for r in recording.requests if r.method == "POST"]
    assert len(posts) == 1
    wire = json.loads(posts[0].body.decode("utf-8"))["prompt"]["fields"]
    assert wire == [list(p) for p in caller.fields], (
        "TC-PROV-20: the payload on the real wire is not the caller's. Byte identity "
        "survives the real backend or the fast tier's prefix guarantee means nothing "
        "(CT-PROV-05, RISK-23)."
    )


def test_tc_prov_20_the_live_answer_replays_identically_through_the_fixture(tmp_path):
    """TC-PROV-20's differential: the live completion, cost nulled per the regeneration
    rule, records into the fixture set and replays byte-identically."""
    provider = _gate_cleared_provider()
    ref = _live_model_ref()
    params_ = SamplingParams(temperature=0.0)
    payload = contract_payload(PromptPayload)

    live = provider.complete(payload, ref, params_)

    from aeh.prov import RecordedFixtureProvider

    fixtures = RecordedFixtureProvider(fixture_dir=tmp_path / "fixtures")
    fixtures.record(payload, ref, params_, dataclasses.replace(live, cost=None))
    replayed = fixtures.complete(payload, ref, params_)
    assert replayed == dataclasses.replace(live, cost=None), (
        "TC-PROV-20: the recorded live answer does not replay identically. The double must "
        "return exactly what the real backend answered — any difference is RISK-37's drift."
    )


def test_tc_prov_20_real_429s_are_observed_classified_and_counted():
    """TC-PROV-20's 429 half: a small concurrent batch against the live backend; every
    outcome is either a valid `Completion` or the taxonomy, and if a 429 was observed the
    counters say so. Asserting that a 429 *occurred* would manufacture flakiness — the case
    observes, it does not provoke (the programmed 429s live in the fast tier, TC-PROV-11)."""
    provider = _gate_cleared_provider()
    ref = _live_model_ref()
    params_ = SamplingParams(temperature=0.0)
    payload = contract_payload(PromptPayload)

    def _probe(_index: int):
        try:
            return ("ok", provider.complete(payload, ref, params_))
        except ProviderError as error:
            return ("error", error)

    with ThreadPoolExecutor(max_workers=PROBE_CONCURRENCY) as pool:
        outcomes = list(pool.map(_probe, range(PROBES)))

    completions = [value for kind, value in outcomes if kind == "ok"]
    errors = [value for kind, value in outcomes if kind == "error"]
    assert completions or errors, "TC-PROV-20: the observation batch produced no outcomes."

    counters = provider.counters
    if any("429" in str(error) for error in errors):
        assert counters.rate_limited_calls >= 1, (
            "TC-PROV-20: a 429 was observed but rate_limited_calls did not move. The "
            "counter is the alert on throttling's share of dispatch — a real 429 that "
            "goes uncounted is a silenced alarm."
        )
    # Whatever happened, the counters stayed consistent with the observed traffic.
    assert counters.tokens_in >= sum(c.tokens_in for c in completions) - len(completions), (
        "TC-PROV-20: the counters do not reflect the observed completions. Usage "
        "accumulates per answered call (CT-PROV-11)."
    )
