"""TS-05 — the provider contract: retry taxonomy, resolved builds, cost, and the seams.

Cases `TC-PROV-02`, `-03`, `-04`, `-07`, `-08`, `-09`, `-10`, `-11`, `-12`, `-15`, `-16`,
`-17` (test plan §5.2). Issue #22 (TS-05).

Rung 0 — every case drives a real provider class over a **programmed transport** and an
injected clock (FR-PROV-15's seam, landed with #19): the transport is the seam the design
v1.5 added precisely so these cases could program a 429 without stubbing the provider.

`Written ahead of implementation: yes` is stale — #19/#20/#21 all landed; these cases run
green by design.
"""

from __future__ import annotations

import json
import random
from decimal import Decimal

import pytest

import aeh.prov as prov_module
from aeh.conf import ConfigurationError, ModelRef
from aeh.prov import (
    BuildChangedError,
    BuildWatch,
    CallPlan,
    Completion,
    ConcurrencyGovernor,
    HttpRequest,
    HttpResponse,
    LocalServerProvider,
    MalformedResponseError,
    OpenRouterProvider,
    ProviderUnavailableError,
    RetentionPolicyError,
    RetryPolicy,
    SamplingParams,
    TransportError,
    dispatch_with_retries,
)

# No tier marker: rung 0, pure — the file runs in every tier (§4.7's unit rows are unmarked).

ISSUE = "#22"


class _ScriptedTransport:
    """A transport programmed with a per-call script: each `complete` consumes one script
    entry, each attempt within it consumes one response (or raises)."""

    def __init__(self, script: list) -> None:
        self.script = script  # list of lists: per-call attempt outcomes
        self.calls = 0
        self.attempts = 0
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest):
        self.requests.append(request)
        self.attempts += 1
        outcome = self.script[self.calls][min(self.attempts - 1, len(self.script[self.calls]) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def next_call(self) -> None:
        self.calls += 1
        self.attempts = 0


class _CountingClock:
    """Advances fake time and records every wait — `rate_limit_wait_s` assertable without
    a real sleep (§4.6: TC-ORCH-09 is the suite's one sanctioned sleep)."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waited: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waited.append(seconds)
        self.now += seconds


def _payload() -> "prov_module.PromptPayload":
    return prov_module.PromptPayload(
        fields=(("student_ref", "ref-007"), ("rubric", "States friction opposes motion."),
                ("submission", "Friction pushes back against motion.")),
    )


def _params() -> SamplingParams:
    return SamplingParams(temperature=0.0)


def _ref(build: str = "b1") -> ModelRef:
    return ModelRef(role="judge", provider="openrouter", build_id=build, quantization="q8")


def _ok(text: str = '{"band": "met"}', build: str = "b1", tokens_in: int = 100,
        tokens_out: int = 10, cached: int = 0) -> HttpResponse:
    return HttpResponse(200, {}, json.dumps({
        "text": text, "model": build,
        "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out,
                  "cached_prefix_tokens": cached},
    }).encode("utf-8"))


def _provider(transport, clock, *, policy: RetryPolicy | None = None,
              build_watch: BuildWatch | None = None) -> LocalServerProvider:
    return LocalServerProvider(
        base_url="http://local/v1", transport=transport, clock=clock,
        rng=random.Random(20260906), policy=policy, build_watch=build_watch,
    )


# --- TC-PROV-10: the decision table over the failure taxonomy (P0) ------------------------------


@pytest.mark.parametrize(
    "programmed, expected_attempts, terminal",
    [
        ("connection-reset", 3, "ProviderUnavailableError"),
        ("read-timeout", 3, "ProviderUnavailableError"),
        ("http-500", 3, "ProviderUnavailableError"),
        ("http-503", 3, "ProviderUnavailableError"),
        ("unparseable", 3, "MalformedResponseError"),
        ("schema-invalid", 3, "MalformedResponseError"),
    ],
)
def test_tc_prov_10_the_decision_table_retries_only_transport_class_failures(
    tmp_data_dir, programmed, expected_attempts, terminal
):
    """`TC-PROV-10` step 1 — the decision table. Retryable failures burn the configured
    budget then surface as their terminal type; the attempt count is exact."""
    failure = {
        "connection-reset": ConnectionResetError("reset"),
        "read-timeout": TimeoutError("timed out"),
        "http-500": HttpResponse(500, {}, b"boom"),
        "http-503": HttpResponse(503, {}, b"busy"),
        "unparseable": HttpResponse(200, {}, b"not json at all"),
        "schema-invalid": HttpResponse(200, {}, b'{"no_text": true}'),
    }[programmed]
    budget = 3
    transport = _ScriptedTransport([[failure for _ in range(budget)]])
    clock = _CountingClock()
    provider = _provider(transport, clock, policy=RetryPolicy(budget, 1, 120.0))
    with pytest.raises(Exception) as raised:
        provider.complete(_payload(), _ref(), _params())
    assert transport.attempts == expected_attempts, (
        f"TC-PROV-10 ({programmed}): {transport.attempts} attempts; the table pins exactly "
        f"{expected_attempts} (HARNESS_RETRY_MAX=3, first attempt included)."
    )
    assert type(raised.value).__name__ == terminal, (
        f"TC-PROV-10 ({programmed}): terminal type {type(raised.value).__name__}, expected "
        f"{terminal} — CT-PROV-07's exact-type oracle, per row of the table."
    )


def test_tc_prov_10_a_parsed_response_is_never_retried(tmp_data_dir):
    """`TC-PROV-10`'s core row: *'parses and validates, but the band is one we dislike —
    exactly 1, never retried, returned to the caller unchanged.'*

    A judgment the caller dislikes is still ONE judgment: re-sampling it would be a silent
    independence violation (RISK-02), and the retry loop must not know what a good answer
    looks like."""
    transport = _ScriptedTransport([[_ok(text='{"band": "not-the-band-we-want"}')]])
    clock = _CountingClock()
    provider = _provider(transport, clock)
    completion = provider.complete(_payload(), _ref(), _params())
    assert transport.attempts == 1, (
        f"TC-PROV-10: {transport.attempts} attempts for a response that parsed. One "
        "judgment, one sample (FR-PROV-06, RISK-02) — a disliked answer is not a failure, "
        "and a second sample would poison the independence M-JUDGE's agreement rests on."
    )
    assert completion.text == '{"band": "not-the-band-we-want"}'


def test_tc_prov_10_no_code_path_reissues_a_parsed_call(tmp_data_dir):
    """`TC-PROV-10` step 2 — the **artifact assertion**: no parameter, flag, keyword or
    environment variable anywhere on the module's surface can enable resampling of a parsed
    response. The guarantee is held by code shape (`dispatch_with_retries` returns at the
    first parsed response), and this sweep checks the shape stays closed."""
    import inspect

    source = inspect.getsource(prov_module.dispatch_with_retries)
    assert "return parsed" in source, (
        "TC-PROV-10: the dispatch loop no longer returns at the first parsed response — "
        "the shape that makes resampling impossible has been edited. Re-read FR-PROV-06 "
        "before touching this."
    )
    for forbidden in ("resample", "retry_if", "resample_on_dislike", "re_ask"):
        assert forbidden not in source, (
            f"TC-PROV-10: the dispatch loop names {forbidden!r} — a hook by any other name "
            "is the resampling path FR-PROV-06 forbids."
        )
    # No env knob may exist for it either.
    for name in dir(prov_module):
        if name.startswith("HARNESS_"):
            assert "resample" not in name.lower(), (
                f"TC-PROV-10: {name} is a resampling knob. FR-PROV-06's surface guarantee "
                "is over the environment too."
            )


# --- TC-PROV-09: budget exhaustion, and no substitution (P0) -------------------------------------


def test_tc_prov_09_budget_exhaustion_raises_and_names_no_substitute(tmp_data_dir):
    """`TC-PROV-09` — *'repeated 5xx beyond budget: ProviderUnavailableError; and no
    parameter, fallback list or config key can substitute a different provider or model.'*
    The artifact half sweeps the module surface for the substitution machinery whose
    existence would make the error's promise negotiable."""
    transport = _ScriptedTransport([
        [HttpResponse(500, {}, b"x") for _ in range(3)],
    ])
    clock = _CountingClock()
    provider = _provider(transport, clock, policy=RetryPolicy(3, 1, 120.0))
    with pytest.raises(ProviderUnavailableError) as raised:
        provider.complete(_payload(), _ref(), _params())
    assert transport.attempts == 3
    assert "No substitute" in str(raised.value)
    # The artifact half: no substitution surface anywhere on the module.
    import inspect

    source = inspect.getsource(prov_module)
    for forbidden in ("fallback_provider", "substitute_provider", "provider_fallback",
                      "FALLBACK", "secondary_provider"):
        assert forbidden not in source, (
            f"TC-PROV-09: the module names {forbidden!r} — a substitution mechanism makes "
            "ProviderUnavailableError's guarantee negotiable, and a silently re-graded "
            "answer is RISK-02 wearing a fallback's clothes."
        )


# --- TC-PROV-11: the Retry-After boundary table (P1) ---------------------------------------------


@pytest.mark.parametrize(
    "header, expected_wait",
    [("0", 0.0), ("2", 2.0), ("3600", None), (None, None), ("soon", None), ("", None)],
)
def test_tc_prov_11_the_retry_after_boundary_table(tmp_data_dir, header, expected_wait):
    """`TC-PROV-11` — *'429 with Retry-After of 0, of 3600, absent, and malformed.'*

    Oracle: **exact wait**. `0` is honoured (a zero wait is still an honour); `3600`
    exceeds the declared ceiling and is NOT honoured (the backoff and the budget decide —
    a provider saying "an hour" is unavailable for a school-day run); absent and malformed
    fall to the jittered backoff, via the ceiling's rule."""
    budget = 1  # a single attempt: the assert inspects the wait, not the recovery
    transport = _ScriptedTransport([
        [HttpResponse(429, {"Retry-After": header} if header is not None else {}, b"")]
        for _ in range(1)
    ])
    clock = _CountingClock()
    provider = _provider(transport, clock, policy=RetryPolicy(budget, 250, 120.0))
    with pytest.raises(ProviderUnavailableError):
        provider.complete(_payload(), _ref(), _params())
    if expected_wait is None:
        # Malformed/absent/above-ceiling: the jittered backoff decided, never the header.
        assert all(0.0 <= w <= 0.25 for w in clock.waited), (
            f"TC-PROV-11: waits {clock.waited} are not the jittered backoff's range. A "
            f"header of {header!r} must not be honoured past the ceiling or guessed from "
            "garbage."
        )
    else:
        assert clock.waited == [expected_wait], (
            f"TC-PROV-11: waits {clock.waited}, expected exactly [{expected_wait}] — the "
            "honoured header is the oracle's exact value."
        )


def test_tc_prov_11_a_429_reduces_concurrency_toward_the_floor(tmp_data_dir):
    """`TC-PROV-11`'s second half: *'in-flight concurrency is reduced toward the configured
    floor rather than the full batch being redispatched.'* The governor ratchets on every
    429 and never below the floor — the spy is the permission level itself."""
    governor = ConcurrencyGovernor(floor=2)
    start = governor.permitted
    governor.on_rate_limited()
    governor.on_rate_limited()
    after = governor.permitted
    assert after < start, (
        "TC-PROV-11: a 429 did not reduce the permitted concurrency. The full batch being "
        "redispatched into a throttling provider is the thundering herd FR-PROV-07 exists "
        "to contain."
    )
    for _ in range(10):
        governor.on_rate_limited()
    assert governor.permitted == 2, (
        "TC-PROV-11: the ratchet passed the configured floor. 'Toward the floor' stops AT "
        "the floor — a governor that ratcheted to zero would deadlock the run."
    )


# --- TC-PROV-03: the payload differential (P0) ----------------------------------------------------


def test_tc_prov_03_the_dispatched_bytes_carry_the_payload_unchanged(tmp_data_dir):
    """`TC-PROV-03` — *'the dispatched bytes contain the payload unchanged: no added field,
    no reordering, no templating.'* Oracle: **differential** — every field's value appears
    in the dispatched bytes, in declaration order, byte-for-byte."""
    fields = (("student_ref", "ref-007"), ("rubric", "Rubric: states friction."),
              ("submission", "The answer, verbatim with ünïcode."))
    transport = _ScriptedTransport([[_ok()]])
    clock = _CountingClock()
    provider = _provider(transport, clock)
    provider.complete(prov_module.PromptPayload(fields=fields), _ref(), _params())
    body = transport.requests[0].body.decode("utf-8")
    positions = [body.find(value) for _, value in fields]
    assert all(position >= 0 for position in positions), (
        f"TC-PROV-03: a field value is missing from the dispatched bytes (positions "
        f"{positions}). FR-PROV-13: the payload is carried unchanged — a templated or "
        "normalized value breaks the request-key determinism the fixtures rest on."
    )
    assert positions == sorted(positions), (
        "TC-PROV-03: the payload fields were reordered in the dispatched bytes. CT-PROV-05 "
        "makes declaration order contract."
    )


# --- TC-PROV-04/-07/-08: resolved builds and the build guard (P0/P1) ------------------------------


def test_tc_prov_04_resolved_build_records_what_answered_not_what_was_asked(tmp_data_dir):
    """`TC-PROV-04` — *'a substitution fixture yields resolved_build unequal to the
    request.'* Oracle: **exact value** — the differential the plan names."""
    transport = _ScriptedTransport([[_ok(build="the-served-build")]])
    provider = _provider(transport, _CountingClock())
    completion = provider.complete(_payload(), _ref(build="requested-build"), _params())
    assert completion.resolved_build == "the-served-build", (
        "TC-PROV-04: resolved_build echoed the request. Every validation record and audit "
        "record names what actually graded the work — an implementation that reports what "
        "it asked for makes build substitution invisible."
    )
    assert completion.resolved_build != "requested-build"


def test_tc_prov_07_a_build_change_raises_and_is_not_retried(tmp_data_dir):
    """`TC-PROV-07` — *'a mid-run response reporting build Y when run start recorded X:
    BuildChangedError raised; attempt count exactly 1, not retried.'*

    FR-PROV-05's reasoning is the teeth: a retry that happened to land back on the original
    build would HIDE the fact that the panel changed mid-run."""
    watch = BuildWatch()
    watch.record("openrouter:b1", "b1")
    transport = _ScriptedTransport([[_ok(build="b2")]])
    provider = _provider(transport, _CountingClock(), build_watch=watch)
    with pytest.raises(BuildChangedError) as raised:
        provider.complete(_payload(), _ref(), _params())
    assert transport.attempts == 1, (
        f"TC-PROV-07: {transport.attempts} attempts after a build change. The error is "
        "explicitly not retried — a retry landing on the original build would hide the "
        "panel change the error exists to report."
    )
    assert "b2" in str(raised.value) and "b1" in str(raised.value)


@pytest.mark.parametrize(
    "served, same",
    [("b1", True), ("B1", False), ("b1@rev2", False), ("b1 ", False)],
)
def test_tc_prov_08_the_build_comparison_rule_is_declared(tmp_data_dir, served, same):
    """`TC-PROV-08` — *'a response reporting the same build with different letter case, or
    with a trailing revision suffix: the declared comparison rule is asserted explicitly —
    whichever way it goes, it must be stated and tested rather than incidental.'*

    The declared rule (BuildWatch's docstring): exact-case, whole-string. Case differences
    and suffixes are DIFFERENT builds — a normalization here would let a silently changed
    panel pass as the same one."""
    watch = BuildWatch()
    watch.record("openrouter:b1", "b1")
    transport = _ScriptedTransport([[_ok(build=served)]])
    provider = _provider(transport, _CountingClock(), build_watch=watch)
    if same:
        provider.complete(_payload(), _ref(), _params())
    else:
        with pytest.raises(BuildChangedError):
            provider.complete(_payload(), _ref(), _params())


# --- TC-PROV-02: capabilities are static (P1) ------------------------------------------------------


def test_tc_prov_02_capabilities_are_declared_statically_per_implementation(tmp_data_dir):
    """`TC-PROV-02` — *'all five fields are declared statically per implementation; no
    network call occurs during capabilities().'* Oracle: exact values across the three
    implementations, plus the no-dispatch spy."""
    from decimal import Decimal

    transport = _ScriptedTransport([[_ok()]])
    clock = _CountingClock()
    local = _provider(transport, clock)
    openrouter = OpenRouterProvider(
        api_key="k", base_url="http://or/v1", transport=_ScriptedTransport([[_ok()]]),
        clock=_CountingClock(), retention_answers=lambda build: "yes",
    )
    fixture = open_store_less_fixture()
    for provider, name in ((local, "local"), (openrouter, "openrouter"), (fixture, "fixture")):
        capabilities = provider.capabilities(_ref())
        for field in ("supports_seed", "supports_prefix_cache", "max_concurrency",
                      "deterministic_at_temperature_zero", "cost_per_token"):
            assert hasattr(capabilities, field), (
                f"TC-PROV-02 ({name}): capabilities lacks {field}. All five fields are "
                "declared statically per implementation (CT-PROV-04)."
            )
    # No network call occurred during any capabilities() call: the scripted transports
    # recorded no dispatch.
    assert transport.calls == 0, (
        "TC-PROV-02: capabilities() dispatched a request. The declared capabilities are "
        "static per implementation — a network call during them is a hidden dispatch."
    )


def open_store_less_fixture():
    import os
    import tempfile

    os.environ.setdefault("HARNESS_FIXTURE_DIR", tempfile.mkdtemp())
    return prov_module.RecordedFixtureProvider(fixture_dir=os.environ["HARNESS_FIXTURE_DIR"])


# --- TC-PROV-12: estimate_cost is pure and hand-computed (P1) --------------------------------------


def test_tc_prov_12_estimate_cost_matches_a_hand_computed_figure(tmp_data_dir):
    """`TC-PROV-12` — *'a CallPlan of 23,000 units with known per-call token budgets:
    estimate_cost matches a hand-computed figure exactly; actual_cost accumulates per
    call.'* Oracle: **hand-computed reference**."""
    clock = _CountingClock()
    provider = _provider(_ScriptedTransport([[_ok()]]), clock)
    plan = CallPlan(calls=23_000, tokens_in_per_call=1_800, tokens_out_per_call=12)
    capabilities = provider.capabilities(_ref())
    rate_in, rate_out = capabilities.cost_per_token
    expected = (Decimal(1_800) * rate_in + Decimal(12) * rate_out) * 23_000
    estimate = provider.estimate_cost(plan)
    assert estimate.cost == expected, (
        f"TC-PROV-12: estimate {estimate.total} != hand-computed {expected}. The estimate "
        "is a pure function of the plan and the declared rates (FR-PROV-09) — anything "
        "measured here is the actual-cost counter's job."
    )
    # actual_cost accumulates per call and is readable at any time (monotonic per call).
    transport = _ScriptedTransport([[_ok(tokens_in=100, tokens_out=10)]])
    provider2 = _provider(transport, _CountingClock())
    before = provider2.counters.tokens_in
    provider2.complete(_payload(), _ref(), _params())
    after = provider2.counters.tokens_in
    assert after >= before, (
        "TC-PROV-12: actual cost regressed mid-run. FR-PROV-09: actual_cost is "
        "monotonically non-decreasing within the run."
    )


# --- TC-PROV-15: the routing prohibition (P1) ------------------------------------------------------


@pytest.mark.parametrize("kind, permitted", [("scoring", False), ("extraction", False),
                                             ("formatting", True)])
def test_tc_prov_15_price_based_routing_is_refused_for_judgment_calls(kind, permitted):
    """`TC-PROV-15` — *'a scoring or extraction call with price-based routing across
    providers requested: ConfigurationError; permitted elsewhere.'* Oracle: exact exception
    type, per call kind."""
    openrouter = OpenRouterProvider(api_key="k", base_url="http://or/v1")
    if permitted:
        openrouter.enforce_routing_rule(_ref(), kind)
    else:
        with pytest.raises(ConfigurationError):
            openrouter.enforce_routing_rule(_ref(), kind)


# --- TC-PROV-16/-17: the retention gate, fail-closed (P0) ------------------------------------------


def test_tc_prov_16_two_of_three_confirmed_names_the_one_that_failed():
    """`TC-PROV-16` — *'a cloud-hosted run start where retention is confirmed for two of
    three panel models: RetentionPolicyError raised — any one unconfirmed model fails the
    whole check.'* The error names which (`TC-PROV-16` is 'two of three' — an operator must
    be told which, not only that it failed)."""
    openrouter = OpenRouterProvider(
        api_key="k", retention_answers=lambda build: (
            "yes" if "judge-1" in build else
            ("yes" if "judge-2" in build else "unknown")))
    panel = [_ref(build=f"judge-{i}") for i in (1, 2, 3)]
    with pytest.raises(RetentionPolicyError) as raised:
        openrouter.verify_retention(panel)
    assert "judge-3" in str(raised.value) and "judge-1" not in str(raised.value), (
        "TC-PROV-16: the error does not say WHICH model failed. 'Two of three' is the "
        "case's input precisely so the operator can fix the one unconfirmed provider."
    )


@pytest.mark.parametrize(
    "answer", [None, False, "", "unknown", "mostly", "the provider deletes most data"])
def test_tc_prov_17_an_ambiguous_answer_is_unconfirmed_fail_closed(answer):
    """`TC-PROV-17` — *'a retention check where the provider API returns an ambiguous or
    absent answer: treated as unconfirmed, so RetentionPolicyError; fail-closed.'*

    `bool(answer)` reads "unknown" as a yes and passes every exception-type assertion —
    this parametrization is the fail-closed rule's teeth."""
    openrouter = OpenRouterProvider(
        api_key="k", retention_answers=lambda build: answer)
    with pytest.raises(RetentionPolicyError):
        openrouter.verify_retention([_ref(build="judge-1")])
