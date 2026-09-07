"""Substitutability — the same caller, the same payload, three implementations.

Case: `TC-PROV-01` (`FR-PROV-01`, P0, Contract, rung 0-2, test plan §5.2). Issue #23 (TS-06).

`FR-PROV-01`: *"`complete(prompt, model_ref, params) -> Completion` returning generated text,
token usage, latency, and provider metadata, for all three implementations."* The issue's Goal
is the shape this file asserts: **the same caller runs unchanged against all three provider
implementations with only `RunConfig` differing.** At this layer the `RunConfig` difference is
the provider instance itself; the caller below is one function, written once, that no
implementation can branch.

Oracle (§5.2): **artifact assertion on the returned shape** — one assertion per field, for
presence and type, on every implementation. A field that is populated on one backend and
`None` on another passes an implementation-specific suite and breaks exactly the caller this
requirement protects: `M-JUDGE` reading `cached_prefix_tokens` off a fixture replay cannot
also handle a cloud `None` without a branch, and a branch here is where RISK-37's drift
becomes visible to consumers.

The live implementations run over a **programmed transport** (rung 0): `FR-PROV-15`'s seam is
what makes a LocalServerProvider drivable without a server, and `TC-PROV-19`/`-20` are the
nightly halves that repeat the assertion against real ones.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aeh.prov import PromptPayload
from tests.support.prov_contract import (
    CONSTRUCTIONS,
    IMPL_IDS,
    CountingClock,
    ScriptedTransport,
    completion,
    flat_ok,
    make_provider,
    model_ref,
    params,
    payload,
)

pytestmark = pytest.mark.contract

#: The six `CT-PROV-03` fields every implementation must populate, and the type each must be.
#: `cost` is asserted separately, because where it may be null is the clause's whole point.
REQUIRED_FIELDS = (
    ("text", str),
    ("tokens_in", int),
    ("tokens_out", int),
    ("latency_ms", int),
    ("resolved_build", str),
    ("cached_prefix_tokens", int),
)

#: `cost`'s nullability per implementation, straight from `CT-PROV-03`: *"Only `cost` is
#: nullable (null on `edge-local` and fixture)."* The fixture replays a recorded backend, the
#: local server is `edge-local` — both null. OpenRouter is `cloud-hosted`: a null there is the
#: clause violation, and a `Decimal("0")` would be too — *not measured* and *measured zero*
#: are different facts.
COST_EXPECTATION = {
    "fixture": None,
    "local": None,
    "openrouter": "decimal-nonzero",
}


@pytest.fixture(params=IMPL_IDS)
def impl(request):
    return request.param


@pytest.fixture(params=CONSTRUCTIONS)
def construction(request):
    return request.param


def _provider_for(impl, construction, tmp_path, *, build=None):
    """A provider of the given implementation and construction, scripted for one success."""
    transport = ScriptedTransport(script=[[flat_ok(build=build) if build else flat_ok()]])
    provider = make_provider(
        impl, construction, transport,
        fixture_dir=tmp_path / "fixtures", clock=CountingClock(),
    )
    if impl == "fixture":
        provider.record(payload(PromptPayload), model_ref(), params(),
                        completion(resolved_build=build) if build else completion())
    return provider, transport


def test_tc_prov_01_same_payload_through_all_three_returns_a_fully_typed_completion(
    impl, construction, tmp_path
):
    """TC-PROV-01 — the same `PromptPayload` through all three implementations: each returns
    a `Completion` with text, `tokens_in`, `tokens_out`, `latency_ms`, `resolved_build` and
    `cached_prefix_tokens` populated and correctly typed.

    One caller, no per-implementation branch — the body below is written once and takes only
    the provider instance. The construction axis rides along: `FR-PROV-15` promises the two
    constructions behave identically, and a shape difference between them would surface here
    as a type failure on one variant.
    """
    provider, _ = _provider_for(impl, construction, tmp_path)
    got = provider.complete(payload(PromptPayload), model_ref(), params())

    for field_name, expected_type in REQUIRED_FIELDS:
        value = getattr(got, field_name)
        assert value is not None, (
            f"TC-PROV-01 ({impl}/{construction}): Completion.{field_name} is None. Every "
            f"implementation populates all six non-nullable fields (CT-PROV-03); a caller "
            f"reading this field off a fixture replay cannot also handle a null from another "
            f"backend without a branch — which is the substitutability FR-PROV-01 exists for."
        )
        assert type(value) is expected_type, (
            f"TC-PROV-01 ({impl}/{construction}): Completion.{field_name} is "
            f"{type(value).__name__} ({value!r}), expected {expected_type.__name__}."
        )
    assert got.text == '{"band": "met"}', (
        "TC-PROV-01: text is not verbatim. CT-PROV-03: text is returned verbatim and "
        "unparsed — this module has no opinion about what a judge said."
    )

    expected_cost = COST_EXPECTATION[impl]
    if expected_cost is None:
        assert got.cost is None, (
            f"TC-PROV-01 ({impl}/{construction}): cost must be null on fixture and "
            f"edge-local (CT-PROV-03) — nothing was billed, so nothing was measured, and a "
            f"Decimal('0') would read as a measured price of nothing."
        )
    else:
        assert isinstance(got.cost, Decimal) and got.cost > 0, (
            f"TC-PROV-01 ({impl}/{construction}): cost must be a non-null, non-zero Decimal "
            f"on cloud-hosted (CT-PROV-03: null only on edge-local and fixture). Got "
            f"{got.cost!r} — *not measured* and *measured zero* are different facts, and "
            f"M-ORCH's ceiling cannot tell them apart once they share a representation."
        )


def test_tc_prov_01_resolved_build_reports_what_answered_on_every_implementation(
    impl, construction, tmp_path
):
    """TC-PROV-01's metadata half: `resolved_build` is what actually answered, never what was
    requested (`FR-PROV-04`) — on every implementation, under both constructions."""
    provider, _ = _provider_for(impl, construction, tmp_path, build="the-served-build")
    got = provider.complete(payload(PromptPayload), model_ref(), params())
    assert got.resolved_build == "the-served-build", (
        f"TC-PROV-01 ({impl}/{construction}): resolved_build echoed the request instead of "
        "reporting what answered. Every validation record names the instrument that graded "
        "the work; an echo makes build substitution invisible (RISK-22)."
    )
    assert got.resolved_build != model_ref().build_id
