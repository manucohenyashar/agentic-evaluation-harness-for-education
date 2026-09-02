"""A `cloud-hosted` run does not start unless zero-retention is confirmed for every judge.

Case: `SEC-03` (`FR-PROV-14`, `NFR-SYS-03`, **P0**, test plan §6.5). Issue #24 (TS-07).

| Field | Value |
|---|---|
| Trust boundary | machine to remote provider |
| Threat | information disclosure |
| Probe | start a `cloud-hosted` run where one panel model cannot confirm zero-retention |
| Expected defense | `RetentionPolicyError`; the run does not start |

`FR-PROV-14`: *"For `cloud-hosted`, the module shall verify at run start that the configured
zero-retention routing is in force for every model in the panel, and shall raise
`RetentionPolicyError` when it cannot be confirmed for any one of them."* `CT-PROV-13` adds the
ordering that makes it a defense rather than a report: confirmation happens **before the first
dispatch**, or the run did not start. Confirming afterwards is the plausible bug, and it
discloses exactly as much as not confirming at all.

**Written ahead of implementation** (issue #21, which owns `FR-PROV-14` and
`OpenRouterProvider`). Expected to fail with `NotImplementedYet` until it lands. Remove the
`writtenahead` marker — not the test — when #21 closes.

The registry keys this file on `aeh.prov:OpenRouterProvider`, a name design §3.2's Interfaces
block spells out verbatim — so the blocker is forced rather than guessed, and `cloud-hosted`
retention is meaningless without the implementation that talks to the cloud.

What is asserted beyond the exception type
-------------------------------------------
An exception-only assertion passes against an implementation that checks retention *after*
dispatching, and against one that confirms two of three models and reports success. Both are
disclosures. So this file asserts three things the row form does not spell out but
`FR-PROV-14`, `TC-PROV-16` and `TC-PROV-17` do: that **any one** unconfirmed model fails the
whole check, that an **ambiguous or absent** answer counts as unconfirmed (fail-closed), and
that **no dispatch precedes** the check.
"""

from __future__ import annotations

import pytest

from tests.support.impl import PROVIDER_MODULE, require

pytestmark = pytest.mark.writtenahead

CONF_MODULE = "aeh.conf"
ISSUE = "#21"


def _panel(model_ref_cls, size: int = 3):
    """A `cloud-hosted` panel of provider-pinned judge builds (design §3.1: pinned slug)."""
    return tuple(
        model_ref_cls(
            role="judge",
            provider="openrouter",
            build_id=f"openrouter/judge-{index}@2024-12-06",
            quantization=None,
        )
        for index in range(1, size + 1)
    )


def test_sec_03_one_unconfirmed_panel_model_stops_the_run(network_guard):
    """SEC-03 — retention confirmed for two of three; the run does not start.

    Oracle: exact exception type. `TC-PROV-16` states the input precisely — *"a `cloud-hosted`
    run start where retention is confirmed for two of three panel models"* — and the expected
    result is that **any one** unconfirmed model fails the whole check.

    Two of three rather than zero of three, deliberately. An implementation that confirmed the
    first model and returned, or that required *all* models to fail before raising, passes a
    none-confirmed version of this case and discloses a cohort's work to the one provider that
    never confirmed anything.
    """
    ModelRef = require(CONF_MODULE, "ModelRef", issue=ISSUE)
    OpenRouterProvider, RetentionPolicyError = require(
        PROVIDER_MODULE, "OpenRouterProvider", "RetentionPolicyError", issue=ISSUE
    )

    panel = _panel(ModelRef)
    provider = OpenRouterProvider(
        retention_answers={
            panel[0].build_id: True,
            panel[1].build_id: True,
            panel[2].build_id: False,
        }
    )

    with pytest.raises(RetentionPolicyError):
        provider.verify_retention(panel)

    network_guard.assert_no_network()


@pytest.mark.parametrize(
    "answer",
    [None, "unknown", "", "maybe"],
    ids=["absent", "ambiguous-word", "empty", "hedged"],
)
def test_sec_03_an_ambiguous_or_absent_answer_is_unconfirmed(answer, network_guard):
    """`TC-PROV-17` — the fail-closed half. An answer that is not a confirmation is a refusal.

    *"A retention check where the provider API returns an ambiguous or absent answer ... treated
    as unconfirmed, so `RetentionPolicyError`; fail-closed."*

    This is the case that separates a real gate from a plausible one. An implementation reading
    the provider's response with `bool(answer)` treats `"unknown"` as confirmation, and one
    using `answer is not False` treats `None` the same way. Both look correct in review and
    both send student work to a provider that never promised to delete it.
    """
    ModelRef = require(CONF_MODULE, "ModelRef", issue=ISSUE)
    OpenRouterProvider, RetentionPolicyError = require(
        PROVIDER_MODULE, "OpenRouterProvider", "RetentionPolicyError", issue=ISSUE
    )

    panel = _panel(ModelRef, size=1)
    provider = OpenRouterProvider(retention_answers={panel[0].build_id: answer})

    with pytest.raises(RetentionPolicyError):
        provider.verify_retention(panel)

    network_guard.assert_no_network()


def test_sec_03_no_payload_is_dispatched_before_retention_is_confirmed(network_guard):
    """`CT-PROV-13`'s ordering assertion, which the exception type alone cannot make.

    *"For `cloud-hosted`, `verify_retention` has confirmed zero-retention routing for every
    panel member **before the first dispatch**, or the run did not start."*

    Confirming after the first call is the plausible bug — it passes every exception-type
    assertion above, reports the failure accurately, and has already sent one cohort's work to
    an unconfirmed provider by the time it does. The oracle here is therefore a **call-order
    invariant**: the provider's own record of what it did, with `verify_retention` strictly
    before any `complete`.
    """
    ModelRef = require(CONF_MODULE, "ModelRef", issue=ISSUE)
    OpenRouterProvider, RetentionPolicyError = require(
        PROVIDER_MODULE, "OpenRouterProvider", "RetentionPolicyError", issue=ISSUE
    )
    PromptPayload, SamplingParams = require(
        PROVIDER_MODULE, "PromptPayload", "SamplingParams", issue=ISSUE
    )

    panel = _panel(ModelRef)
    dispatched: list[object] = []
    provider = OpenRouterProvider(
        retention_answers={ref.build_id: (ref is not panel[2]) for ref in panel},
        on_dispatch=dispatched.append,
    )

    with pytest.raises(RetentionPolicyError):
        provider.verify_retention(panel)

    assert dispatched == [], (
        "a payload was dispatched before zero-retention was confirmed for every panel member "
        "(CT-PROV-13). The work has already left the machine; raising afterwards reports the "
        "disclosure, it does not prevent it."
    )

    # And the gate holds on the ordinary path too: a caller that ignores the failure and calls
    # `complete` anyway must still not reach the provider.
    payload = PromptPayload(fields=(("system", "score this"), ("submission", "an answer")))
    with pytest.raises(RetentionPolicyError):
        provider.complete(payload, panel[0], SamplingParams(temperature=0.0))

    assert dispatched == []
    network_guard.assert_no_network()
