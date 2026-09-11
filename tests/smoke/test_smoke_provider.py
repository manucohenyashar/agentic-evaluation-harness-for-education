"""The smoke suite (TS-50, issue #143) — the model boundary answers and gates.

`TC-SMOKE-05` (`FR-PROV-01`, `FR-PROV-02`) — the bound provider answers one trivial
completion and reports capabilities; fails if the provider is unreachable or capabilities
are undeclared. `TC-SMOKE-06` (`FR-PROV-14`) — on `cloud-hosted`, zero-retention routing is
confirmed for every panel model; fails if any model is unconfirmed.

Both drive the **shipped** provider implementations, not doubles: `RecordedFixtureProvider`
is the fast tier's whole model story (`CT-PROV-10`), and `OpenRouterProvider` is the hosted
implementation whose run-start gate the case is about. The socket guard (TS-00) is active —
autouse from `tests/conftest.py` — and each case also asserts no connection was attempted,
because a provider that failed *by trying the network* would satisfy an exception-only
oracle while doing the one thing the deterministic transport exists to forbid.

The `cloud-hosted` panel is `HOSTED_PANEL_3` (three OpenRouter builds): retention must be
confirmed for **every** panel model, and a single-member panel cannot distinguish "every"
from "the first" (`conf_builders`' blind-spot note).

`Written ahead of implementation: yes` is stale — `M-PROV` landed with #17-#21; the cases
run green by design.
"""

from __future__ import annotations

import pytest

from aeh.conf import ModelRef
from aeh.prov import (
    Capabilities,
    Completion,
    FixtureMissingError,
    OpenRouterProvider,
    PromptPayload,
    RetentionPolicyError,
    SamplingParams,
)
from tests.support.conf_builders import (
    EDGE_JUDGE,
    HOSTED_PANEL_3,
    SENTINEL_CREDENTIAL,
)

_JUDGE_BUILD = EDGE_JUDGE.build_id


def _prompt() -> PromptPayload:
    return PromptPayload(
        fields=(
            ("system", "You are scoring one criterion."),
            ("submission", "The block slides because friction is lower than gravity."),
        )
    )


def test_tc_smoke_05_bound_provider_answers_and_declares_capabilities(
    make_fixture_provider, network_guard
):
    """`TC-SMOKE-05` — the bound provider answers one trivial completion and reports
    capabilities.

    Oracle: **exact replay plus full declaration**. One `Completion` is recorded, the same
    fully-assembled request returns it byte-equal (`Completion` is the whole accounting, so
    a replay that dropped `resolved_build` or fudged the token counts is caught by
    equality), an unknown request raises `FixtureMissingError` rather than reaching for a
    socket — "unreachable" at the deterministic transport is a loud miss, not a retry — and
    `capabilities()` returns every field declared (`FR-PROV-02`): seed support, prefix-cache
    support, a positive concurrency ceiling, the temperature-zero determinism **claim**, and
    a `cost_per_token` of `None` (nothing is billed, and a declared zero would read as a
    measured price of nothing). `assert_no_network` closes the loop on both halves.
    """
    provider = make_fixture_provider()
    params = SamplingParams(temperature=0.0)
    prompt = _prompt()
    recorded = Completion(
        text="met",
        tokens_in=1800,
        tokens_out=1,
        latency_ms=430,
        resolved_build=_JUDGE_BUILD,
        cached_prefix_tokens=1500,
        cost=None,  # null on fixture — CT-PROV-03
    )
    provider.record(prompt, EDGE_JUDGE, params, recorded)

    answered = provider.complete(prompt, EDGE_JUDGE, params)
    assert answered == recorded, (
        "TC-SMOKE-05: the fixture provider did not replay the recorded completion "
        "byte-for-byte. The deterministic transport is the fast tier's model story; a "
        "replay that mutates the answer invalidates every tier above it."
    )
    with pytest.raises(FixtureMissingError):
        provider.complete(
            PromptPayload(fields=(("submission", "a request no recording covers"),)),
            EDGE_JUDGE,
            params,
        )

    capabilities = provider.capabilities(EDGE_JUDGE)
    assert isinstance(capabilities, Capabilities)
    assert capabilities.supports_seed is True
    assert capabilities.supports_prefix_cache is True
    assert capabilities.max_concurrency >= 1
    assert capabilities.deterministic_at_temperature_zero is True
    assert capabilities.cost_per_token is None, (
        "TC-SMOKE-05: capabilities came back with a per-token cost on the fixture "
        "provider. Fixture replay is not billed (CT-PROV-03); a declared price here "
        "contradicts the clause every consumer above tests against."
    )
    network_guard.assert_no_network()


def test_tc_smoke_06_zero_retention_confirmed_for_every_panel_model():
    """`TC-SMOKE-06` — on `cloud-hosted`, zero-retention routing is confirmed for every
    panel model.

    Oracle: **exact report, then the fail-closed refusal**. On the confirmation path,
    `verify_retention` returns `RetentionReport(confirmed=<all three>, unconfirmed=())` —
    the panel members themselves, in panel order (`FR-PROV-03`: the report is contract, so
    every implementation answers in the same shape). On the refusal path — one hedged answer
    ("mostly" reads as *unknown*, and this gate exists because `bool(answer)` reads unknown
    as yes) — the run-start gate raises `RetentionPolicyError` naming the unconfirmed models
    **and nothing has been dispatched**; the refusal also arms the provider, so a caller
    that ignored the exception still cannot reach `complete()` (`CT-PROV-13`'s ordering).
    The retention answers come through the `retention_answers` seam (`FR-PROV-15`), so no
    transport is ever touched — the socket guard stays untripped by construction.
    """
    confirmed_provider = OpenRouterProvider(
        base_url="http://fixture.invalid",
        api_key=SENTINEL_CREDENTIAL,
        retention_answers=lambda build_id: "zero-retention",
    )
    report = confirmed_provider.verify_retention(HOSTED_PANEL_3)
    assert report.confirmed == HOSTED_PANEL_3, (
        f"TC-SMOKE-06: zero-retention confirmed for {report.confirmed} of the panel. "
        "FR-PROV-14: every panel model, in panel order — a report that drops a member "
        "understates what must hold before the first dispatch."
    )
    assert report.unconfirmed == ()

    gated_provider = OpenRouterProvider(
        base_url="http://fixture.invalid",
        api_key=SENTINEL_CREDENTIAL,
        retention_answers=lambda build_id: "mostly",
    )
    with pytest.raises(RetentionPolicyError) as raised:
        gated_provider.verify_retention(HOSTED_PANEL_3)
    for member in HOSTED_PANEL_3:
        assert member.build_id in str(raised.value), (
            f"TC-SMOKE-06: the refusal does not name {member.build_id}. FR-PROV-14's "
            "refusal names the unconfirmed models — an operator cannot route around a "
            "gate that will not say which member it refused."
        )
    with pytest.raises(RetentionPolicyError):
        gated_provider.complete(_prompt(), HOSTED_PANEL_3[0], SamplingParams(temperature=0.0))