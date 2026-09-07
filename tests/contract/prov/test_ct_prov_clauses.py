"""The `CT-PROV` clause suite (§6.11.2), parametrized over implementations and construction.

Case: `TC-PROV-06` (`NFR-PROV-01`, P0, Contract, rung 0-3, test plan §5.2 and §6.11.2).
Issue #23 (TS-06). C01-C14 and the provider half of C16 are implemented here; the two block
clauses are placed as follows:

- **`TC-PROV-C15`** (sole egress, safety property): the case lives in
  `tests/contract/prov/test_sole_egress.py` (issue #25) — cardinality one over the
  egress-capable import set, the adversarial construction, and the runtime half (step 2)
  with a stack-attributed egress guard over the journey that exists. The walker itself is
  `tests/support/import_graph.py`; `tests/artifact/test_import_graph.py` holds `TC-PROV-05`'s
  tree-level assertions (zero violations outside `M-PROV`). The §6.2 full journey under the
  runtime guard lands with `M-ORCH`.
- **`TC-PROV-C16`** (identical inputs are not promised identical text): the block-form case
  lives in `tests/contract/prov/test_nonpromise_determinism.py` (issue #25) — the
  golden-file tier assertion (step 5) and the consumer-sweep placement (steps 2-4, which
  need `M-JUDGE`, `M-EXTRACT` and `M-CONFORM`, none of which exist yet). The provider half
  (step 1) — a provider whose byte-identical requests draw textually different responses,
  with no caching or deduplication anywhere in this module — is
  `test_tc_prov_c16_...` below; the sweep becomes the consuming stories' obligation
  the moment they land.

**The two parametrization axes.** §6.11.2: the whole suite runs against
`[RecordedFixtureProvider, LocalServerProvider, OpenRouterProvider]` — the first in the fast
tier, the two live ones nightly over real servers (`TC-PROV-19`/`-20`). Here they all run
over a programmed transport, which is what `FR-PROV-15`'s seam is for. Since issue #23's
2026-09-02 re-sync there is a second axis — each implementation built once with the seams
**supplied** and once **defaulted** — because this is the only case that can break what
`FR-PROV-15` promises: *behaviour identical whether injected or defaulted*. A provider that
skips retry, loses a counter, or waits on a real clock only on its **default** path passes
every other `M-PROV` case, because every other case builds it with doubles. The transport
stays programmed on the defaulted axis (a defaulted transport is the real network — see
`tests/support/prov_contract.py` for what the axis means seam by seam); the default
retention path is not exempted — `OpenRouterProvider` with no `retention_answers` sources
its answers over the programmed transport, so the default path runs for real.

**What is parametrized over the live implementations only, and why that is not a waiver.**
The dispatch-machinery clauses C07 (per-error retryability, counters included) and C09's
counter monotonicity and C11's counter half exist to hold the *retry loop and its
accounting* to the clause — machinery the fixture provider definitionally lacks: it is
replay, not dispatch, and has no loop, no wait and no counters. Their parametrization spans
`[local, openrouter]` × `[injected, defaulted]` for the same reason the suite spans three
implementations: the defaulted axis is where a default-path-only defect hides. `TC-PROV-C02`'s
prohibition is on *waiving a case a backend must pass*; a case whose subject the backend
cannot have is not waived, it does not apply. `C02`'s own source sweep stays honest about
the difference: the banned strings are deselects and expected failures, not scope.

`TC-PROV-C02`'s rule is enforced on this file itself: no case waives a backend, and the
only per-implementation branches in the file are the distinctions `CT-PROV-03` itself
declares (cost nullability per hosting, the fixture's replay path standing in for a wire).
The differential is structural — every applicable test is one function over the
parametrization, so an implementation-specific behaviour can only show up as a red cell,
never as a green bypass.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import logging
import os
import sys
import threading
import time
import tracemalloc
from decimal import Decimal

import pytest

import aeh.prov as prov_module
from aeh.prov import (
    BuildChangedError,
    BuildWatch,
    CallPlan,
    Capabilities,
    FixtureMissingError,
    HttpResponse,
    MalformedResponseError,
    PromptPayload,
    ProviderUnavailableError,
    RateLimitedError,
    RetryPolicy,
    TransportError,
    request_key,
)
from tests.support.guards import recording_write_audit
from tests.support.prov_contract import (
    CONSTRUCTIONS,
    CREDENTIAL_SENTINEL,
    DEFAULTED,
    EXPECTED_OR_COST,
    IMPL_IDS,
    INJECTED,
    CountingClock,
    ScriptedTransport,
    SUBMISSION,
    completion,
    flat_ok,
    make_openrouter_with_sentinel,
    make_provider,
    model_ref,
    params,
    payload,
)
from tests.support.roster import build_roster, roster_name_patterns

pytestmark = pytest.mark.contract

#: Every clause of §6.11.2 this suite owns a case for, in order. The completeness assertion
#: below reads this list, so a clause dropped in an edit fails here by name rather than
#: silently narrowing the suite. (C15 is a whole-tree case rather than a parametrized cell;
#: its home is `tests/contract/prov/test_sole_egress.py` — see the module docstring, which
#: is part of the scanned source.)
CLAUSE_IDS = tuple(f"TC-PROV-C{i:02d}" for i in range(1, 15)) + ("TC-PROV-C16",)

LIVE_IMPLS = ("local", "openrouter")


# --- the parametrization -------------------------------------------------------------------------


@pytest.fixture(params=IMPL_IDS, ids=IMPL_IDS)
def impl(request):
    return request.param


@pytest.fixture(params=CONSTRUCTIONS, ids=CONSTRUCTIONS)
def construction(request):
    return request.param


@pytest.fixture(params=LIVE_IMPLS, ids=LIVE_IMPLS)
def live_impl(request):
    return request.param


def _success_provider(impl, construction, tmp_path, *, text='{"band": "met"}',
                      build="llama-3.3-70b@q4", tokens_in=1800, tokens_out=12, cached=1500,
                      clock=None):
    """A provider scripted for successful completions, with its transport handed back.

    The scripted success is also the transport's `default`, so any further `complete` the
    caller makes succeeds without re-scripting. The fixture implementation is recorded first
    — `record()` is the caller's own action (the nightly regeneration path), never a branch
    the caller takes per implementation.
    """
    success = flat_ok(text=text, build=build, tokens_in=tokens_in,
                      tokens_out=tokens_out, cached=cached)
    transport = ScriptedTransport(script=[[success]], default=success,
                                  # The defaulted OpenRouter retention path GETs its answer
                                  # over this transport; an explicit confirmation is what a
                                  # cleared panel looks like (fail-closed otherwise).
                                  get_default=HttpResponse(200, {}, b"yes"))
    provider = make_provider(
        impl, construction, transport, fixture_dir=tmp_path / "fixtures", clock=clock,
    )
    if impl == "fixture":
        provider.record(payload(PromptPayload), model_ref(), params(),
                        completion(text=text, resolved_build=build, tokens_in=tokens_in,
                                   tokens_out=tokens_out, cached_prefix_tokens=cached))
    return provider, transport


# --- TC-PROV-C01 — surface: synchronous, one call one model call, no threads (P0) -----------------


def test_tc_prov_c01_the_surface_is_synchronous_one_call_one_dispatch_no_threads(
    impl, construction, tmp_path
):
    """`CT-PROV-01`: `complete` is synchronous and blocking; one call is one model call;
    `capabilities`/`estimate_cost`/`verify_retention` make no model call; the module starts
    no thread and owns no queue — concurrency is the caller's.

    Oracle: call counter and thread census. An internal batching or worker-pool
    "optimization" would break the caller's ownership of concurrency — and with it
    `M-JUDGE`'s isolation between scoring contexts.
    """
    provider, transport = _success_provider(impl, construction, tmp_path)

    assert not inspect.iscoroutinefunction(provider.complete), (
        f"TC-PROV-C01 ({impl}/{construction}): complete is a coroutine. The interface is "
        "synchronous and blocking (CT-PROV-01) — a caller that awaits is a caller that "
        "changed per backend."
    )

    threads_before = threading.active_count()
    provider.complete(payload(PromptPayload), model_ref(), params())
    if impl != "fixture":
        assert transport.attempts == 1, (
            f"TC-PROV-C01 ({impl}/{construction}): one complete() made {transport.attempts} "
            "model calls. One call is one model call — no batching, no coalescing, no "
            "speculative second sample."
        )
    # The fixture implementation dispatches by replay and touches no transport — its
    # "one call is one model call" is the single file read TC-PROV-13 counts.

    # The three non-dispatching operations, under the same counter. The POST count is what
    # "no model call" means here: the defaulted OpenRouter retention path sources its answers
    # over HTTP (a GET), which is a lookup, not a model call.
    posts_before = sum(1 for r in transport.requests if r.method == "POST")
    provider.capabilities(model_ref())
    provider.estimate_cost(CallPlan(calls=3, tokens_in_per_call=100, tokens_out_per_call=10))
    provider.verify_retention([model_ref()])
    posts_after = sum(1 for r in transport.requests if r.method == "POST")
    assert posts_after == posts_before, (
        f"TC-PROV-C01 ({impl}/{construction}): capabilities/estimate_cost/verify_retention "
        "dispatched a model call. CT-PROV-01: they make none — a retention check or an "
        "estimate that reaches the provider has already sent work to it."
    )

    for _ in range(5):
        provider.complete(payload(PromptPayload), model_ref(), params())
    assert threading.active_count() == threads_before, (
        f"TC-PROV-C01 ({impl}/{construction}): the module started a thread. Concurrency is "
        "the caller's (CT-PROV-01); an internal pool takes it away silently and breaks "
        "M-JUDGE's isolation between scoring contexts with it."
    )


# --- TC-PROV-C02 — behaviour: the parametrization itself, asserted (P0) ----------------------------


def test_tc_prov_c02_no_case_waives_a_backend_and_every_clause_case_is_present():
    """`CT-PROV-C02`: the entire suite runs against all three implementations from one
    caller, and no case needs an implementation-specific branch — *a test that skips on a
    backend is a contract violation and fails the case.*

    Two artifact assertions over this module's own source:

    1. **No per-backend waiver.** No deselect, no expected failure, no conditional bypass:
       the parametrization is structural, every applicable cell runs, and an implementation
       that cannot pass a case reds it.
    2. **Completeness.** Every clause case this suite owns appears in the source, so a
       clause dropped in an edit fails here by name. (C15 and C16's blocked halves are
       placed verbatim in the module docstring, which this scan covers.)
    """
    source = inspect.getsource(sys.modules[__name__])
    # The builders are part of the suite's per-backend behaviour too: a conditional bypass
    # could hide in a helper as easily as in a test body.
    source += inspect.getsource(sys.modules["tests.support.prov_contract"])
    # Assembled by concatenation so this assertion's own literals cannot match themselves.
    banned = ("pytest.mark." + "skip", "pytest.mark." + "xfail",
              "pytest." + "skip(", "pytest." + "xfail(", "skip" + "if(")
    for pattern in banned:
        assert pattern not in source, (
            f"TC-PROV-C02: this suite contains {banned!r}. A case waived per backend is the "
            "contract violation the clause exists to fail — the differential IS the case."
        )
    for clause_id in CLAUSE_IDS:
        assert clause_id in source, (
            f"TC-PROV-C02: {clause_id} has no case in the clause suite. The §6.11.2 "
            "parametrization is the plan's defence against RISK-37 — narrowing it silently "
            "is how the fast tier stops describing the system that exists."
        )


def test_tc_prov_c02_the_same_caller_probe_answers_equivalently_on_every_backend(
    impl, construction, tmp_path
):
    """`CT-PROV-C02`'s differential half: one caller probe — all four interface operations,
    written once — produces equivalent answers on every implementation, with only the
    nullability `CT-PROV-03` sanctions differing."""
    provider, _ = _success_provider(impl, construction, tmp_path)
    ref = model_ref()
    got = provider.complete(payload(PromptPayload), ref, params())
    caps = provider.capabilities(ref)
    estimate = provider.estimate_cost(
        CallPlan(calls=1, tokens_in_per_call=100, tokens_out_per_call=10))
    retention = provider.verify_retention([ref])

    assert got.text == '{"band": "met"}' and got.tokens_in == 1800 and got.tokens_out == 12, (
        f"TC-PROV-C02 ({impl}/{construction}): the caller probe's completion diverged. The "
        "same caller must answer equivalently with only the provider instance differing."
    )
    assert all(hasattr(caps, f) for f in (
        "supports_seed", "supports_prefix_cache", "max_concurrency",
        "deterministic_at_temperature_zero", "cost_per_token",
    ))
    assert estimate.tokens_in == 100 and estimate.tokens_out == 10
    assert retention.all_confirmed, (
        f"TC-PROV-C02 ({impl}/{construction}): the same caller's retention check did not "
        "clear the panel. Substitutability is FR-PROV-03's whole promise — a caller written "
        "against one implementation must run unchanged on the others."
    )


# --- TC-PROV-C03 — data: the Completion's distinctions (P0) -----------------------------------------


def test_tc_prov_c03_cost_is_null_exactly_where_the_clause_says_and_never_measured_zero(
    impl, construction, tmp_path
):
    """`CT-PROV-03`: *`cost` is the only nullable field, and null only on `edge-local` and
    fixture.* The per-field presence/type sweep is `TC-PROV-01`'s; the distinction the clause
    insists on is this case's: a cloud completion carries a real Decimal — not null, and not
    `Decimal("0")`, because *not measured* and *measured zero* are different facts and
    `M-ORCH`'s ceiling cannot tell them apart once they share a representation."""
    provider, _ = _success_provider(impl, construction, tmp_path)
    got = provider.complete(payload(PromptPayload), model_ref(), params())

    if impl == "openrouter":
        assert isinstance(got.cost, Decimal) and got.cost > 0, (
            f"TC-PROV-C03 ({impl}/{construction}): cloud-hosted cost is {got.cost!r}. "
            "CT-PROV-03 puts null on edge-local and fixture only; a Decimal('0') on a cloud "
            "call is a defect and not a saving."
        )
    else:
        assert got.cost is None, (
            f"TC-PROV-C03 ({impl}/{construction}): cost must be null on {impl} — nothing "
            "was billed, so nothing was measured (CT-PROV-03)."
        )

    assert got.text == '{"band": "met"}', (
        "TC-PROV-C03: text was transformed. It is returned verbatim and unparsed — this "
        "module has no opinion about what a judge said."
    )


def test_tc_prov_c03_resolved_build_is_what_answered_never_what_was_requested(
    impl, construction, tmp_path
):
    """`CT-PROV-03`'s differential on `resolved_build`: in a substitution fixture the field
    is asserted **unequal** to the requested ref — the assertion that catches the field
    silently echoing the request (RISK-22)."""
    provider, _ = _success_provider(impl, construction, tmp_path, build="served-not-requested")
    got = provider.complete(payload(PromptPayload), model_ref(), params())
    assert got.resolved_build == "served-not-requested", (
        f"TC-PROV-C03 ({impl}/{construction}): resolved_build neither reported the served "
        "build nor kept the request's — the field must say what actually answered."
    )
    assert got.resolved_build != model_ref().build_id


def test_tc_prov_c03_a_reported_cost_is_believed_verbatim_and_an_unparseable_one_is_taxonomy(
    live_impl, tmp_path
):
    """`CT-PROV-03`'s cost distinctions, wire-reported side: a backend that bills and
    reports what it billed is **believed verbatim** — not re-derived from the declared
    rates, which would discard the measured fact for an estimate of it — and a
    `usage.cost` that will not parse is a structurally broken response
    (`MalformedResponseError`), not a silent None. The unbilled implementation gets the
    mirror-image assertion: a reported cost is *nullified*, because CT-PROV-03 puts null
    on edge-local regardless of what the wire says."""
    reported = flat_ok(tokens_in=1800, tokens_out=12)
    body = json.loads(reported.body.decode("utf-8"))
    body["usage"]["cost"] = "0.0042"  # ≠ the derived 0.001824, so belief is discriminating
    transport = ScriptedTransport(script=[[HttpResponse(200, {}, json.dumps(body).encode())]])
    if live_impl == "openrouter":
        provider = make_openrouter_with_sentinel(transport, clock=CountingClock())
    else:
        provider = make_provider(live_impl, INJECTED, transport, clock=CountingClock())
    got = provider.complete(payload(PromptPayload), model_ref(), params())

    if live_impl == "openrouter":
        assert got.cost == Decimal("0.0042"), (
            f"TC-PROV-C03 ({live_impl}): a reported cost of 0.0042 came back as "
            f"{got.cost!r}. The wire's measured figure is believed verbatim — re-deriving "
            "it from the declared rates replaces the measurement with an estimate of "
            "itself (CT-PROV-03: cost is the measured fact beside the usage)."
        )
    else:
        assert got.cost is None, (
            f"TC-PROV-C03 ({live_impl}): a cost reported by an edge-local backend must be "
            "nullified — CT-PROV-03 puts null on edge-local; nothing was billed, so a "
            "wire cost is not a measured price of anything."
        )

    broken = flat_ok()
    body = json.loads(broken.body.decode("utf-8"))
    body["usage"]["cost"] = "not-a-number"
    transport.script.append([HttpResponse(200, {}, json.dumps(body).encode())])
    transport.next_call()
    with pytest.raises(MalformedResponseError):
        provider.complete(payload(PromptPayload), model_ref(), params())


# --- TC-PROV-C04 — data: capabilities are declared, not discovered (P1) -----------------------------


def test_tc_prov_c04_capabilities_answer_with_the_transport_blocked_and_stay_stable(
    impl, construction, tmp_path, network_guard
):
    """`CT-PROV-04`: `Capabilities` is declared, not discovered — it answers with the
    transport hard-blocked (the autouse guard is up through this whole test) and is stable
    for the life of the run. `deterministic_at_temperature_zero` is a **claim**: the case
    asserts the type carries exactly the five declared fields and no measurement beside
    them — `M-STATS` measuring a disagreement is that module's finding, not an error here."""
    provider, transport = _success_provider(impl, construction, tmp_path)

    caps_start = provider.capabilities(model_ref())
    for _ in range(3):
        provider.complete(payload(PromptPayload), model_ref(), params())
    caps_end = provider.capabilities(model_ref())

    assert caps_start == caps_end, (
        f"TC-PROV-C04 ({impl}/{construction}): capabilities changed across a run. They are "
        "declared once and stable for the life of the run — a capabilities() that re-reads "
        "the world per call is discovery, and CT-PROV-04 forbids it."
    )
    assert [f.name for f in dataclasses.fields(Capabilities)] == [
        "supports_seed", "supports_prefix_cache", "max_concurrency",
        "deterministic_at_temperature_zero", "cost_per_token",
    ], (
        "TC-PROV-C04: Capabilities carries a field the design does not declare. The claim "
        "is the contract — a measured field beside it would dress discovery up as "
        "declaration."
    )
    assert isinstance(caps_start.deterministic_at_temperature_zero, bool)
    # The transport was touched only by the three completes — the capabilities() calls added
    # no dispatch of their own. (The fixture path touches no transport at all, so its count
    # is zero and stays zero: the delta is the assertion, not the absolute.)
    posts = sum(1 for r in transport.requests if r.method == "POST")
    provider.capabilities(model_ref())
    posts_after = sum(1 for r in transport.requests if r.method == "POST")
    assert posts_after == posts, (
        f"TC-PROV-C04 ({impl}/{construction}): capabilities() dispatched. Declared, not "
        "discovered (CT-PROV-04) — the transport spy is the oracle: a discovery call "
        "would appear here as a POST the caller did not make."
    )


# --- TC-PROV-C05 — behaviour: byte identity between caller and wire (P0) ----------------------------


def _wire_fields(transport, index: int):
    """The payload as it reached the wire, decoded back out of the dispatched body."""
    body = json.loads(transport.requests[index].body.decode("utf-8"))
    return body["prompt"]["fields"]


def test_tc_prov_c05_the_payload_on_the_wire_is_the_callers_byte_for_byte(
    impl, construction, tmp_path
):
    """`CT-PROV-05`: capture the assembled payload at the caller and on the wire; assert
    **byte identity**. The mutations that would pass a looser check are each covered by
    driving two different payloads through the same caller: a field added, keys reordered,
    whitespace normalized, a template applied, unicode renormalized — the wire must mirror
    the caller *both* times, so any implementation-side convergence between them fails.

    The submission carries `ünïcode` deliberately: code points surviving the wire intact is
    what M-JUDGE's byte-identical prefix rests on (RISK-23).

    The fixture implementation dispatches by replay, so its "wire" is the request stored in
    the recording — read back out of the fixture file and held to the same identity.
    """
    caller = payload(PromptPayload)

    if impl == "fixture":
        provider, _ = _success_provider(impl, construction, tmp_path)
        provider.complete(caller, model_ref(), params())
        stored = json.loads(next((tmp_path / "fixtures").glob("*.json")).read_text("utf-8"))
        assert stored["request"]["fields"] == [list(p) for p in caller.fields], (
            "TC-PROV-C05 (fixture): the recording's request is not the caller's payload, "
            "byte for byte. The replay path must dispatch exactly what was assembled."
        )
        return

    provider, transport = _success_provider(impl, construction, tmp_path)
    provider.complete(caller, model_ref(), params())
    assert _wire_fields(transport, 0) == [list(p) for p in caller.fields], (
        f"TC-PROV-C05 ({impl}/{construction}): the wire payload is not the caller's. A "
        "field added, reordered, normalized, templated or unicode-renormalized on the wire "
        "breaks the byte-identical prefix M-JUDGE depends on — a fivefold slowdown with no "
        "error (RISK-23)."
    )

    # The mutation sweep, as a differential: a second, deliberately different payload must
    # reach the wire just as exactly. An implementation that normalized or templated would
    # converge the two — which is the violation, and it cannot hide from the comparison.
    second = PromptPayload(fields=(
        ("student_ref", "ref-008"),
        ("submission", "  padded  differently  — ünïcode two. "),
    ))
    provider.complete(second, model_ref(), params())
    assert _wire_fields(transport, 1) == [list(p) for p in second.fields], (
        f"TC-PROV-C05 ({impl}/{construction}): a second payload did not reach the wire "
        "byte-identically. Normalization, templating or reordering is CT-PROV-05's "
        "violation whichever payload it touches."
    )


# --- TC-PROV-C06 — behaviour: a parsed response is never re-requested (P0) --------------------------

_ODD_BUT_VALID = ("", "I refuse to answer that question.", '{"band": "not-the-band-we-want"}')


@pytest.mark.parametrize("text", _ODD_BUT_VALID, ids=["empty", "refusal", "disliked"])
def test_tc_prov_c06_a_parsed_response_is_never_re_requested(
    impl, construction, tmp_path, text
):
    """`CT-PROV-06`: retry **only** on transport failure, timeout, 429, 5xx, or structural
    parse failure. The decisive negative: a response that parsed successfully is never
    re-requested — the call count is exactly 1 across semantically odd but structurally
    valid answers. One judgment, one sample (RISK-02): a disliked verdict is not a failure.

    The surface half — no parameter, flag or code path can enable resampling — is
    `TC-PROV-10` step 2's artifact assertion
    (`tests/unit/prov/test_ts05_provider_contract.py`), which sweeps the whole module; it is
    referenced here rather than duplicated.
    """
    provider, transport = _success_provider(impl, construction, tmp_path, text=text)
    got = provider.complete(payload(PromptPayload), model_ref(), params())
    if impl != "fixture":
        assert transport.attempts == 1, (
            f"TC-PROV-C06 ({impl}/{construction}, {text!r}): {transport.attempts} attempts "
            "for a response that parsed. Re-sampling a judgment is a silent independence "
            "violation — the retry loop must not know what a good answer looks like."
        )
    assert got.text == text, (
        f"TC-PROV-C06 ({impl}/{construction}): the parsed answer was replaced. One "
        "judgment, one sample — the caller gets the answer that was sampled, liked or not."
    )


# --- TC-PROV-C07 — error: one case per named error, with its retryability (P0) -----------------------
#
# `CT-PROV-07`'s per-error assertions, one test per named error so a failure report names
# the clause case directly. Every live-implementation case runs under BOTH constructions —
# the defaulted variants are what catch a provider that retries, waits or counts only when
# its seams are injected (the defect class FR-PROV-15 exists to expose). `FixtureMissingError`
# is the fixture's own error (`CT-PROV-10`) and has its own case.
#
# §4.6 (no real sleep) on the defaulted axis: the default clock is the real `SystemClock`,
# so the defaulted cases either honour `Retry-After: 0` (a zero-second wait — the clock seam
# is exercised, nothing is spent) or run under `HARNESS_BACKOFF_BASE_MS=1`, the seam-3 knob
# the module ships for exactly this.


def test_tc_prov_c07_transport_error_is_retried_internally_then_surfaced_chained(
    live_impl, construction, tmp_path, monkeypatch
):
    """`TransportError` — retryable, and the retry is *behavioural*: budget 2, first
    attempt fails at the transport, second succeeds — the caller sees a completion, and
    the retry is visible in the counters. A second script proves the surfaced shape when
    the budget exhausts: `ProviderUnavailableError` with the transport error as its cause
    — the siblings keep every exact-type oracle discriminating (RISK-34)."""
    if construction == DEFAULTED:
        # The defaulted policy is read from the environment once at construction — which is
        # precisely the seam-3 reading this axis exists to exercise. Base 1 keeps §4.6's
        # no-real-sleep rule intact on the real SystemClock.
        monkeypatch.setenv("HARNESS_RETRY_MAX", "2")
        monkeypatch.setenv("HARNESS_BACKOFF_BASE_MS", "1")
    clock = CountingClock()
    transport = ScriptedTransport(script=[[TransportError("connection reset"), flat_ok()]],
                                  default=flat_ok())
    provider = make_provider(
        live_impl, construction, transport, fixture_dir=tmp_path / "fixtures",
        clock=clock if construction == INJECTED else None,
        policy=RetryPolicy(2, 1, 120.0) if construction == INJECTED else None,
    )
    got = provider.complete(payload(PromptPayload), model_ref(), params())
    assert transport.attempts == 2, (
        f"TC-PROV-C07 ({live_impl}/{construction}): {transport.attempts} attempts for a "
        "transport failure inside a budget of 2. The transport error is retried "
        "internally before it can surface (CT-PROV-07) — a caller never sees it on the "
        "first failure."
    )
    assert provider.counters.transport_retries == 1
    assert got.text == '{"band": "met"}'
    if construction == INJECTED:
        assert len(clock.waited) == 1  # the backoff between the two attempts

    transport.next_call()
    transport.script.append([TransportError("connection reset"),
                             TransportError("connection reset")])
    with pytest.raises(ProviderUnavailableError) as raised:
        provider.complete(payload(PromptPayload), model_ref(), params())
    assert isinstance(raised.value.__cause__, TransportError), (
        f"TC-PROV-C07 ({live_impl}/{construction}): the surfaced error lost its cause. The "
        "budget-exhaustion error carries the transport error it exhausted the budget on — "
        "a caller diagnosing a flaky link reads the chain, not the summary."
    )
    assert TransportError.retryable is True
    assert ProviderUnavailableError.retryable is False


def test_tc_prov_c07_rate_limited_error_is_retried_with_a_wait_and_counted(
    live_impl, construction, tmp_path, monkeypatch
):
    """`RateLimitedError` — HTTP 429, retryable *with a wait*, and the wait lands in the
    run counters under both constructions. The behavioural half: budget 2, first attempt
    answered 429, second succeeds — the caller sees a completion, and both the throttle
    and the retry are in the counters. `Retry-After: 0` keeps §4.6's no-real-sleep rule
    intact on the defaulted axis while still exercising the clock seam."""
    if construction == DEFAULTED:
        monkeypatch.setenv("HARNESS_RETRY_MAX", "2")
        monkeypatch.setenv("HARNESS_BACKOFF_BASE_MS", "1")
    clock = CountingClock()
    transport = ScriptedTransport(
        script=[[HttpResponse(429, {"Retry-After": "0"}, b""), flat_ok()]],
        default=flat_ok())
    provider = make_provider(
        live_impl, construction, transport, fixture_dir=tmp_path / "fixtures",
        clock=clock if construction == INJECTED else None,
        policy=RetryPolicy(2, 250, 120.0) if construction == INJECTED else None,
    )
    got = provider.complete(payload(PromptPayload), model_ref(), params())
    assert transport.attempts == 2, (
        f"TC-PROV-C07 ({live_impl}/{construction}): a 429 was not retried internally. "
        "RateLimitedError is retryable with a wait (CT-PROV-07) — the caller must not "
        "see it while the budget holds."
    )
    assert got.text == '{"band": "met"}'

    counters = provider.counters
    assert counters.rate_limited_calls == 1, (
        f"TC-PROV-C07 ({live_impl}/{construction}): a throttled call did not land in "
        "rate_limited_calls. The counter's consumer is an alert on its share of dispatch — "
        "a lost count is a lost alarm (CT-PROV-09/CT-PROV-11)."
    )
    assert counters.rate_limit_wait_s == 0.0
    assert counters.transport_retries == 1
    if construction == INJECTED:
        assert clock.waited == [0.0]

    # And past the budget it surfaces chained: the taxonomy shape the caller catches.
    transport.next_call()
    transport.script.append([HttpResponse(429, {"Retry-After": "0"}, b""),
                             HttpResponse(429, {"Retry-After": "0"}, b"")])
    with pytest.raises(ProviderUnavailableError) as raised:
        provider.complete(payload(PromptPayload), model_ref(), params())
    assert isinstance(raised.value.__cause__, RateLimitedError)
    assert RateLimitedError.retryable is True


def test_tc_prov_c07_malformed_response_retries_to_the_budget_then_surfaces_as_itself(
    live_impl, construction, tmp_path, monkeypatch
):
    """`MalformedResponseError` — retryable up to the retry budget; past it the *unit*
    quarantines and the run continues, so it surfaces **as itself**, not as an availability
    error: the provider was reachable and answering nonsense (CT-PROV-07's per-error state
    assertion)."""
    if construction == DEFAULTED:
        monkeypatch.setenv("HARNESS_BACKOFF_BASE_MS", "1")
    # The response body fails structural parsing — the *parse* step raises, which is what
    # makes it retryable (a transport that raised the error itself would be a different,
    # non-retried path). A 200 with an unparseable body is the decision table's row.
    transport = ScriptedTransport(
        script=[[HttpResponse(200, {}, b"not json at all") for _ in range(3)]])
    provider = make_provider(
        live_impl, construction, transport, fixture_dir=tmp_path / "fixtures",
        clock=CountingClock() if construction == INJECTED else None,
        policy=RetryPolicy(3, 1, 120.0) if construction == INJECTED else None,
    )
    with pytest.raises(MalformedResponseError) as raised:
        provider.complete(payload(PromptPayload), model_ref(), params())
    assert transport.attempts == 3, (
        f"TC-PROV-C07 ({live_impl}/{construction}): {transport.attempts} attempts for a "
        "malformed response. It is retryable up to the budget (CT-PROV-07), and the budget "
        "is HARNESS_RETRY_MAX=3 — first attempt included."
    )
    assert MalformedResponseError.retryable is True


def test_tc_prov_c07_provider_unavailable_after_budget_and_nothing_consumed(
    live_impl, construction, tmp_path, monkeypatch
):
    """`ProviderUnavailableError` — repeated 5xx beyond the budget; terminal for the run,
    never retried, and the failed calls consume nothing: no usage is accumulated for a call
    that never returned an answer."""
    if construction == DEFAULTED:
        monkeypatch.setenv("HARNESS_BACKOFF_BASE_MS", "1")
    transport = ScriptedTransport(
        script=[[HttpResponse(500, {}, b"boom") for _ in range(3)]])
    provider = make_provider(
        live_impl, construction, transport, fixture_dir=tmp_path / "fixtures",
        clock=CountingClock() if construction == INJECTED else None,
        policy=RetryPolicy(3, 1, 120.0) if construction == INJECTED else None,
    )
    with pytest.raises(ProviderUnavailableError):
        provider.complete(payload(PromptPayload), model_ref(), params())
    assert transport.attempts == 3
    assert ProviderUnavailableError.retryable is False
    counters = provider.counters
    assert counters.tokens_in == 0 and counters.tokens_out == 0, (
        f"TC-PROV-C07 ({live_impl}/{construction}): a failed run consumed tokens. The state "
        "left behind is nothing written, only tokens actually consumed — usage from a call "
        "that never answered would corrupt M-ORCH's ceiling arithmetic."
    )


def test_tc_prov_c07_build_changed_raises_and_is_never_retried(
    live_impl, construction, tmp_path
):
    """`BuildChangedError` — a mid-run build change is terminal and explicitly **not**
    retried (FR-PROV-05): a retry landing on the original build would hide the panel change.
    The defaulted variant exercises the default `BuildWatch` through the provider's own
    run-start record."""
    watch = BuildWatch()
    watch.record("ollama:" + model_ref().build_id, "b1")
    transport = ScriptedTransport(script=[[flat_ok(build="b2")]])
    if construction == INJECTED:
        provider = make_provider(live_impl, construction, transport,
                                 fixture_dir=tmp_path / "fixtures", clock=CountingClock(),
                                 build_watch=watch)
    else:
        provider = make_provider(live_impl, construction, transport,
                                 fixture_dir=tmp_path / "fixtures")
        provider.record_run_build("ollama:" + model_ref().build_id, "b1")
    with pytest.raises(BuildChangedError) as raised:
        provider.complete(payload(PromptPayload), model_ref(), params())
    assert transport.attempts == 1, (
        f"TC-PROV-C07 ({live_impl}/{construction}): a build change was retried. The error "
        "is terminal and not retried — a retry on the original build hides the change."
    )
    assert BuildChangedError.retryable is False
    assert "b2" in str(raised.value) and "b1" in str(raised.value)


def test_tc_prov_c07_fixture_missing_error_is_terminal_and_never_falls_through(tmp_path):
    """`FixtureMissingError` — an unknown request raises rather than falling through to the
    network; the state left behind is a recording directory with nothing new in it. The
    fall-through the clause forbids is asserted positively by the socket guard."""
    transport = ScriptedTransport()  # a transport the fixture path must never touch
    provider = make_provider("fixture", INJECTED, transport,
                             fixture_dir=tmp_path / "fixtures")
    provider.record(payload(PromptPayload), model_ref(), params(), completion())
    before = sorted(p.name for p in (tmp_path / "fixtures").iterdir())

    unknown = PromptPayload(fields=(*payload(PromptPayload).fields[:-1],
                                    ("submission", "a different submission")))
    with pytest.raises(FixtureMissingError) as raised:
        provider.complete(unknown, model_ref(), params())
    assert FixtureMissingError.retryable is False
    assert sorted(p.name for p in (tmp_path / "fixtures").iterdir()) == before, (
        "TC-PROV-C07: a fixture miss wrote to the recording directory. The state left "
        "behind is nothing — a miss records nothing and answers nothing."
    )


# --- TC-PROV-C08 — behaviour: no substitution on any code path (P0) ---------------------------------


def test_tc_prov_c08_an_unavailable_panel_member_is_never_substituted(
    live_impl, construction, tmp_path, monkeypatch
):
    """`CT-PROV-08`: induce `ProviderUnavailableError` on one panel member and assert no
    substitution occurs on any code path — no other model answers, no degraded mode, no
    cached response. Every request the exhausted budget made went to the same model; nothing
    was dispatched after the raise. The artifact half (no fallback knob anywhere on the
    module surface) is `TC-PROV-09`'s module-wide sweep, referenced rather than duplicated."""
    if construction == DEFAULTED:
        monkeypatch.setenv("HARNESS_RETRY_MAX", "1")
        monkeypatch.setenv("HARNESS_BACKOFF_BASE_MS", "1")
    transport = ScriptedTransport(
        script=[[HttpResponse(500, {}, b"boom") for _ in range(3)]],
        default=HttpResponse(500, {}, b"boom"))
    provider = make_provider(
        live_impl, construction, transport, fixture_dir=tmp_path / "fixtures",
        clock=CountingClock() if construction == INJECTED else None,
        policy=RetryPolicy(3, 1, 120.0) if construction == INJECTED else None,
    )
    ref = model_ref()
    with pytest.raises(ProviderUnavailableError):
        provider.complete(payload(PromptPayload), ref, params())

    requested_builds = {json.loads(r.body.decode("utf-8"))["model"] for r in transport.requests}
    assert requested_builds == {ref.build_id}, (
        f"TC-PROV-C08 ({live_impl}/{construction}): requests reached other builds "
        f"({sorted(requested_builds)}) while the panel member was unavailable. A fallback "
        "that answers with a different instrument silently re-grades the work (HLD R1)."
    )

    # And the refusal holds for the caller's next units too: every subsequent dispatch goes
    # to the same panel member and fails the same way. Nothing answered in its place, and
    # nothing answered from a cache.
    for _ in range(2):
        transport.next_call()
        with pytest.raises(ProviderUnavailableError):
            provider.complete(payload(PromptPayload), ref, params())
    requested_builds = {json.loads(r.body.decode("utf-8"))["model"] for r in transport.requests}
    assert requested_builds == {ref.build_id}


# --- TC-PROV-C09 — behaviour: estimate_cost is pure; actuals monotonic and always readable (P1) -----


def test_tc_prov_c09_estimate_cost_is_pure_never_dispatches_and_matches_the_declared_rates(
    impl, construction, tmp_path
):
    """`CT-PROV-09`: `estimate_cost(plan)` is a pure function of the plan and the declared
    per-token costs, and never dispatches — same plan, same answer, transport blocked (the
    autouse guard is up). The exact values come from each implementation's own declared
    rates, which is what makes the differential a differential: one caller, three declared
    price sheets, three exact figures."""
    provider, transport = _success_provider(impl, construction, tmp_path)
    plan = CallPlan(calls=23_000, tokens_in_per_call=1_800, tokens_out_per_call=12)

    first = provider.estimate_cost(plan)
    second = provider.estimate_cost(plan)
    assert first == second, (
        f"TC-PROV-C09 ({impl}/{construction}): the same plan produced different estimates. "
        "The estimate is a pure function of the plan and the declared rates — anything "
        "measured here is the counters' job (FR-PROV-09)."
    )
    assert first.tokens_in == 23_000 * 1_800 and first.tokens_out == 23_000 * 12
    if impl == "openrouter":
        assert first.cost == EXPECTED_OR_COST * 23_000, (
            f"TC-PROV-C09 ({impl}/{construction}): estimate {first.cost} != the declared "
            "rates applied to the plan. The figure is hand-checkable: (1800 × 0.000001 + "
            "12 × 0.000002) × 23000."
        )
    elif impl == "local":
        assert first.cost == Decimal("0"), (
            "TC-PROV-C09: the edge-local implementation declares zero rates, so its "
            "estimate is zero — computed from the declared rates, not hardcoded."
        )
    else:
        assert first.cost is None, (
            "TC-PROV-C09: the fixture is not billed, and an absent price is None — a "
            "computed 0 would read as a measured price of nothing (CT-PROV-03's logic, one "
            "level up)."
        )
    assert transport.requests == [], (
        f"TC-PROV-C09 ({impl}/{construction}): estimate_cost dispatched "
        f"{len(transport.requests)} request(s). It is a pure function of the plan and the "
        "declared rates and never dispatches (CT-PROV-09) — an implementation that "
        "resolves its rates per call is discovering at call time, which CT-PROV-04 "
        "forbids besides."
    )


def test_tc_prov_c09_actual_cost_counters_are_monotonic_and_readable_at_any_time(
    live_impl, construction, tmp_path, monkeypatch
):
    """`CT-PROV-09`'s running-actuals half: read the counters at many points through a run —
    after successes, mid-flight, and after a failed call — and assert the figures are
    non-decreasing and always readable. A cost figure that resets or decreases breaks
    `M-ORCH`'s ceiling enforcement (RISK-25)."""
    provider, transport = _success_provider(live_impl, construction, tmp_path)
    if construction == DEFAULTED:
        # One failed call joins the batch; the default policy needs its budget and its
        # backoff base from the env seams, which is the defaulted-policy reading this axis
        # exists to exercise (and what keeps §4.6's no-real-sleep rule intact).
        monkeypatch.setenv("HARNESS_RETRY_MAX", "1")
        monkeypatch.setenv("HARNESS_BACKOFF_BASE_MS", "1")
    ref = model_ref()
    readings = []
    for _ in range(3):
        provider.complete(payload(PromptPayload), ref, params())
        readings.append(provider.counters)
    # A failed call joins the SAME provider: read the counters straight after it.
    transport.next_call()
    transport.script.append([HttpResponse(500, {}, b"boom")])
    try:
        provider.complete(payload(PromptPayload), ref, params())
    except ProviderUnavailableError:
        pass
    readings.append(provider.counters)
    transport.next_call()
    provider.complete(payload(PromptPayload), ref, params())
    readings.append(provider.counters)

    tokens = [r.tokens_in for r in readings]
    assert tokens == sorted(tokens), (
        f"TC-PROV-C09 ({live_impl}/{construction}): token counters were not non-decreasing "
        f"across reads ({tokens}). A figure that resets or decreases mid-run breaks the "
        "ceiling check RISK-25 warns about. The failed call legitimately leaves the figure "
        "unchanged — readable, and not lower."
    )
    assert tokens[-1] == 4 * 1800, (
        f"TC-PROV-C09 ({live_impl}/{construction}): the final count {tokens[-1]} does not "
        "match four answered calls. Usage accumulates per call and only for calls that "
        "answered."
    )


# --- TC-PROV-C10 — behaviour: hermeticity with the socket layer genuinely open (P0) -----------------


def test_tc_prov_c10_an_unknown_request_misses_with_the_socket_layer_open(network_guard,
                                                                          tmp_path):
    """`CT-PROV-10`: an unknown request raises `FixtureMissingError` rather than falling
    through to the network — asserted with **the socket layer left open**, so a fall-through
    would actually succeed if the code had one. This is stronger than asserting under the
    guard (TC-PROV-13 does that): the guard is uninstalled for the call, the network is
    genuinely reachable, and the provider still cannot reach it — because there is no code
    path from replay to a socket, which is what makes "no live call in CI" a fact rather
    than a hope."""
    from aeh.prov import RecordedFixtureProvider

    provider = RecordedFixtureProvider(fixture_dir=tmp_path / "fixtures")
    provider.record(payload(PromptPayload), model_ref(), params(), completion())
    unknown = PromptPayload(fields=(*payload(PromptPayload).fields[:-1],
                                    ("submission", "a request that was never recorded")))

    network_guard.uninstall()
    try:
        with pytest.raises(FixtureMissingError):
            provider.complete(unknown, model_ref(), params())
    finally:
        network_guard.install()
    assert network_guard.installed


# --- TC-PROV-C11 — state: writes nothing; counters accumulate in memory (P1) ------------------------


def test_tc_prov_c11_a_batch_of_calls_writes_nothing(impl, construction, tmp_path):
    """`CT-PROV-11`'s write half: the module writes nothing — a write-audit over a batch
    of calls expects an empty log. Parametrized over **all three implementations**: the
    fixture's replay path only reads, so a double that quietly wrote (an access log, a
    cache entry) would otherwise pass every cell in the suite while violating the clause
    in the fast tier's own model boundary. The negative half (the module never persists
    the counters itself) is the same empty log: a persist would appear in it as a write."""
    provider, _ = _success_provider(impl, construction, tmp_path)
    with recording_write_audit() as attempts:
        for _ in range(3):
            provider.complete(payload(PromptPayload), model_ref(), params())
    assert attempts == [], (
        f"TC-PROV-C11 ({impl}/{construction}): the module wrote to disk: "
        f"{[(a.api, str(a.target)) for a in attempts]}. CT-PROV-11: writes nothing "
        "directly — persistence into run_metrics is M-ORCH's commit, not this module's "
        "write, and that is what keeps run_metrics single-writer (CT-ORCH-17)."
    )


def test_tc_prov_c11_the_counters_accumulate_in_memory_and_are_read_by_the_caller(
    live_impl, construction, tmp_path
):
    """`CT-PROV-11`'s counter half: the six counters accumulate **in memory** and are read
    by the caller. Live implementations only — the fixture is replay, has no dispatch
    loop, and therefore has nothing to count (see the module docstring's scope note)."""
    provider, _ = _success_provider(live_impl, construction, tmp_path)
    for _ in range(3):
        provider.complete(payload(PromptPayload), model_ref(), params())
    counters = provider.counters
    assert counters.tokens_in == 3 * 1800 and counters.tokens_out == 3 * 12, (
        f"TC-PROV-C11 ({live_impl}/{construction}): the counters do not reflect the batch. "
        "They accumulate in memory and are read by M-ORCH (CT-PROV-11) — the accessor is "
        "the only surface."
    )


# --- TC-PROV-C12 — perf: module overhead and the allocation of the prefix (P1) -----------------------

#: The per-call overhead budget, above the provider's own latency, measured against an
#: instant (null) transport. Env-gated per seam 3: the production figure is 5 ms (CT-PROV-12),
#: and a slower box adjusts the knob rather than the code.
OVERHEAD_BUDGET_MS = float(os.environ.get("HARNESS_PROV_OVERHEAD_BUDGET_MS", "5"))


def test_tc_prov_c12_module_overhead_stays_under_the_declared_budget_per_call(
    impl, construction, tmp_path
):
    """`CT-PROV-12`'s threshold: under 5 ms of module overhead per call, measured against a
    null transport at the stated environment. RISK-33: a loosened bound must edit this
    number in review — the knob changes the *environment's* budget, never the clause's."""
    provider, _ = _success_provider(impl, construction, tmp_path)
    ref = model_ref()
    calls = 50
    start = time.perf_counter()
    for _ in range(calls):
        provider.complete(payload(PromptPayload), ref, params())
    per_call_ms = (time.perf_counter() - start) * 1000.0 / calls
    assert per_call_ms < OVERHEAD_BUDGET_MS, (
        f"TC-PROV-C12 ({impl}/{construction}): {per_call_ms:.2f} ms of module overhead per "
        f"call against a {OVERHEAD_BUDGET_MS} ms budget. The clause names 5 ms against the "
        "provider's own latency; a loosened bound is an edit to the clause in review "
        "(RISK-33), not a number a slow box quietly redefines."
    )


def test_tc_prov_c12_the_request_key_materializes_no_copy_of_the_prefix():
    """`CT-PROV-12`'s allocation half: the request key streams into the hasher — no buffer
    holding the assembled request is ever materialized (NFR-PROV-02), so an observed
    `cache_hit_rate` reflects the caller's prompt ordering, not this module's allocation
    behaviour. Oracle (§6.11.2): an **allocation differential across prefix sizes** — the
    growth in traced peak between a small and a large prefix must be ONE encode copy of
    the size difference. A materializing implementation (a buffer holding the assembled
    request, plus its framed copies) grows by several copies of the difference and fails
    the differential, which a single-size bound cannot discriminate."""
    small = PromptPayload(fields=(("system", "score"), ("submission", "x" * 4_000)))
    large = PromptPayload(fields=(("system", "score"), ("submission", "x" * 50_000)))

    def _traced_peak(prompt: PromptPayload) -> int:
        tracemalloc.start()
        base = tracemalloc.get_traced_memory()[1]
        request_key(prompt, model_ref(), params())
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        return peak - base

    size_difference = len(large.fields[1][1].encode("utf-8")) \
        - len(small.fields[1][1].encode("utf-8"))
    delta_difference = _traced_peak(large) - _traced_peak(small)
    assert delta_difference <= size_difference + (size_difference // 2) + 8_192, (
        f"TC-PROV-C12: growing the prefix by {size_difference} bytes grew the request "
        f"key's allocation by {delta_difference} bytes. The key streams into the hasher "
        "(NFR-PROV-02) — the growth is the one copy str.encode must make. A materialized "
        "buffer of the assembled request grows by several copies of the difference, and "
        "the observed cache_hit_rate starts reporting this module's allocations instead "
        "of the caller's ordering."
    )


# --- TC-PROV-C13 — security: credentials, names, and the run-start gate (P0) ------------------------


def test_tc_prov_c13_the_wire_carries_the_ref_and_no_roster_name(
    impl, construction, tmp_path
):
    """`CT-PROV-13`'s body rule: request bodies carry `student_ref` and never a student
    name (NFR-PROV-04). The scan is against the **full** roster, not only the payload's own
    student — a bug that leaks someone else's name into a request is the worse disclosure,
    since it crosses students. The provider's obligation is the negative one: it adds
    nothing, so the wire is the caller's payload and the scan finds no name in it."""
    roster = build_roster(size=2)
    patterns = roster_name_patterns(roster)
    named = PromptPayload(fields=(
        ("system", "You are scoring one criterion."),
        ("student_ref", roster[0].student_ref),
        ("criterion", "States that friction opposes motion."),
        ("submission", "Answer text, pseudonymous by construction."),
    ))

    if impl == "fixture":
        # The fixture's "wire" is the request its recording stores; record the named
        # payload directly (record() is the caller's action, not a dispatch).
        from aeh.prov import RecordedFixtureProvider

        provider = RecordedFixtureProvider(fixture_dir=tmp_path / "fixtures")
        provider.record(named, model_ref(), params(), completion())
        wire = json.dumps(json.loads(
            next((tmp_path / "fixtures").glob("*.json")).read_text("utf-8"))["request"])
    else:
        provider, transport = _success_provider(impl, construction, tmp_path)
        provider.complete(named, model_ref(), params())
        wire = transport.requests[0].body.decode("utf-8")

    assert roster[0].student_ref in wire, (
        f"TC-PROV-C13 ({impl}/{construction}): the dispatched body carries no student_ref. "
        "NFR-PROV-04: bodies carry the pseudonym — a payload with neither ref nor name is "
        "not pseudonymized, it is unidentified."
    )
    for student in roster:
        for name in student.names:
            assert name not in wire, (
                f"TC-PROV-C13 ({impl}/{construction}): {name!r} reached the wire. Request "
                "bodies carry student_ref only and never a student name (CT-PROV-13, "
                "NFR-PROV-04) — the name may exist only outside the payload, held by "
                "whoever owns the roster."
            )


def test_tc_prov_c13_the_credential_reaches_no_log_exception_or_return_value(
    live_impl, construction, tmp_path, caplog, monkeypatch
):
    """`CT-PROV-13`'s credential rule: a distinctive credential value appears in no log
    line, no exception message and no returned value. The key is carried by the provider on
    its real seam, then a success and a forced failure are driven past every surface that
    could echo it. Student work gets the same sweep: no payload field value reaches a log
    line either (CT-PROV-13 names both)."""
    if construction == DEFAULTED:
        # The forced failure is retried by the default policy; base 1 keeps §4.6's
        # no-real-sleep rule intact on the real SystemClock this construction supplies.
        monkeypatch.setenv("HARNESS_RETRY_MAX", "1")
        monkeypatch.setenv("HARNESS_BACKOFF_BASE_MS", "1")
    transport = ScriptedTransport(script=[[flat_ok()]], default=HttpResponse(500, {}, b"boom"))
    provider = make_openrouter_with_sentinel(
        transport, clock=CountingClock() if construction == INJECTED else None,
        policy=RetryPolicy(1, 1, 120.0) if construction == INJECTED else None,
    )

    with caplog.at_level(logging.DEBUG, logger="aeh.prov"):
        got = provider.complete(payload(PromptPayload), model_ref(), params())
        transport.next_call()
        try:
            provider.complete(payload(PromptPayload), model_ref(), params())
        except ProviderUnavailableError as error:
            failure_text = str(error)
        else:
            failure_text = ""

    surfaces = failure_text + json.dumps({k: str(v) for k, v in vars(got).items()})
    for record in caplog.records:
        surfaces += record.getMessage() + json.dumps(
            {k: str(v) for k, v in record.__dict__.items() if k not in ("message", "msg")}
        )
    assert CREDENTIAL_SENTINEL not in surfaces, (
        f"TC-PROV-C13 ({live_impl}/{construction}): the credential value leaked to a log "
        "line, an exception message or a returned value. CT-PROV-13 forbids all three — "
        "a reviewer may audit egress by reading one module, and a leaked key ends that."
    )
    assert SUBMISSION not in surfaces, (
        f"TC-PROV-C13 ({live_impl}/{construction}): student work reached a log line. "
        "Per-call logs name metadata only — payload values are student work and never "
        "reach a log line (CT-PROV-13)."
    )


# --- TC-PROV-C14 — observe: the per-call DEBUG fields and the counter names (P1) --------------------

DEBUG_FIELDS = ("model_ref", "resolved_build", "latency_ms", "tokens_in", "tokens_out",
                "retry_count")
COUNTER_NAMES = ("transport_retries", "rate_limited_calls", "rate_limit_wait_s",
                 "tokens_in", "tokens_out", "cache_hit_rate")


def test_tc_prov_c14_the_per_call_debug_line_names_its_fields(impl, construction, tmp_path,
                                                              caplog):
    """`CT-PROV-14`: per call at DEBUG — model_ref, resolved build, latency, tokens, retry
    count — on **every** implementation, under both constructions. The fields are contract
    by name because the per-call trace is what an operator reconciles against a run when
    something looks wrong; a line that exists on one backend and not another is a trace
    that lies by omission."""
    provider, _ = _success_provider(impl, construction, tmp_path)
    with caplog.at_level(logging.DEBUG, logger="aeh.prov"):
        provider.complete(payload(PromptPayload), model_ref(), params())

    debug_records = [r for r in caplog.records
                     if r.name == "aeh.prov" and r.levelno == logging.DEBUG]
    assert debug_records, (
        f"TC-PROV-C14 ({impl}/{construction}): no DEBUG record was emitted for a provider "
        "call. The per-call trace is contract (CT-PROV-14) — on every implementation, so a "
        "run's trace does not go dark when the panel member changes."
    )
    emitted = debug_records[-1].__dict__
    missing = [f for f in DEBUG_FIELDS if f not in emitted]
    assert not missing, (
        f"TC-PROV-C14 ({impl}/{construction}): the per-call DEBUG line is missing "
        f"{missing}. The fields are contract by name (CT-PROV-14) — an operator "
        "reconciles a run against them."
    )


def test_tc_prov_c14_the_run_counters_are_emitted_under_their_contract_names(
    live_impl, construction, tmp_path
):
    """`CT-PROV-14`'s per-run half: the six counters are exposed under exactly the
    `FR-PROV-12` names, and `cache_hit_rate` is a rate in [0, 1] — not a count. The name is
    contract because `cache_hit_rate` is RISK-23's only detector: HLD §9.7 treats a drop
    below the historical band as a build failure with no error, and a renamed counter is a
    silenced alarm."""
    provider, _ = _success_provider(live_impl, construction, tmp_path)
    provider.complete(payload(PromptPayload), model_ref(), params())
    counters = provider.counters
    for name in COUNTER_NAMES:
        assert hasattr(counters, name), (
            f"TC-PROV-C14 ({live_impl}/{construction}): counter {name!r} is missing. The "
            "names are contract (FR-PROV-12, CT-PROV-14) — a rename silences RISK-23's "
            "only detector."
        )
    assert 0.0 <= counters.cache_hit_rate <= 1.0, (
        f"TC-PROV-C14 ({live_impl}/{construction}): cache_hit_rate is {counters.cache_hit_rate!r} "
        "— a rate in [0,1], not a count. A count under this name makes every historical-band "
        "alert meaningless."
    )


# --- TC-PROV-C16 — non-promise: no consumer depends on textual reproducibility (P0) ------------------


def test_tc_prov_c16_the_provider_half_varying_text_no_caching_no_dedup(
    live_impl, construction, tmp_path
):
    """`CT-PROV-16`, provider half: byte-identical requests draw textually different
    responses, every one of them a valid `Completion` — and the third identical request
    still dispatches, because no code path caches or dedupes on response text.

    This is the freedom the non-promise protects: today, at temperature 0, text usually IS
    reproducible, and a consumer that quietly depends on it passes every test until a GPU,
    a driver or a SQLite version changes — then fails far from the change. The consumer
    sweep (steps 2-5: `M-JUDGE`, `M-EXTRACT`, `M-CONFORM`) lands with those modules; the
    docstring at the top of this file records the placement."""
    texts = ['{"band": "met"}', '{"band":  "met"}  ', '{"rationale": "same band, other words"}']
    transport = ScriptedTransport(
        script=[[flat_ok(text=text)] for text in texts], default=flat_ok())
    provider = make_provider(
        live_impl, construction, transport, fixture_dir=tmp_path / "fixtures",
        clock=CountingClock() if construction == INJECTED else None,
    )
    ref = model_ref()
    got = []
    dispatched_attempts = 0
    for index in range(len(texts)):
        if index:
            transport.next_call()
        got.append(provider.complete(payload(PromptPayload), ref, params()))
        dispatched_attempts += transport.attempts

    assert {c.text for c in got} == set(texts), (
        f"TC-PROV-C16 ({live_impl}/{construction}): the varying texts did not all come "
        "back verbatim. Textual variation is the unpromised dimension — the provider must "
        "pass it through untouched in both directions."
    )
    assert dispatched_attempts == len(texts), (
        f"TC-PROV-C16 ({live_impl}/{construction}): {dispatched_attempts} attempts for "
        f"{len(texts)} identical requests. No code path caches or dedupes on response text "
        "(CT-PROV-16) — a cache keyed on the unpromised dimension would serve a stale "
        "answer when the backend's wording changed."
    )

