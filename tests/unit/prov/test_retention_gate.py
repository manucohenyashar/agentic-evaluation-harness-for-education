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
disclosures. So this file asserts that **any one** unconfirmed model fails the whole check,
that an **ambiguous or absent** answer counts as unconfirmed (fail-closed), and that **no
dispatch precedes** the check.

And, first of all, that the gate can *pass*. A file of nothing but `pytest.raises` is satisfied
by a `verify_retention` that is a bare `raise` statement — a provider that confirms nothing,
ever, and could never start a cloud run at all. A reviewer's stub demonstrated exactly that
against an earlier draft: six green tests, zero requirement asserted. The all-confirmed control
is what makes every `raises` below mean something.

Scope note, because the ID matters for the RTM
-----------------------------------------------
The fail-closed parametrization reproduces `TC-PROV-17`'s input list, and **`TC-PROV-17` is not
this story's** — §8.2 assigns it, with `TC-PROV-16`, to `TS-05` (issue #22). It is here because
`SEC-03`'s oracle is worth nothing without it: "raises when unconfirmed" is only a defense if
"unconfirmed" includes the ambiguous answer. `TS-05` owns the case ID and the fuller treatment
(a retention check against the live provider API's actual response shapes); this file claims
neither, and the PR says so, so the RTM is not told `TC-PROV-17` is covered here.

Interface expectations this test places on #21
-----------------------------------------------
| Name | Status in the design |
|---|---|
| `OpenRouterProvider` | defined, design §3.2 Interfaces |
| `verify_retention(model_refs) -> RetentionReport` | defined, design §3.2 Interfaces |
| `RetentionPolicyError` | defined, `FR-PROV-14` |
| `RetentionReport.all_confirmed` / `.confirmed` / `.unconfirmed` | **not specified** — the design names the type and never its fields. `TC-PROV-16` is "two of three", so the report must say *which*, not just whether |
| `OpenRouterProvider(retention_answers=...)` | **not in the design** — the seam by which a test programs the provider API's answers. §4.2 offers no double for a retention response |
| `OpenRouterProvider(on_dispatch=...)` | **not in the design** — the recorder the call-order assertion reads. `CT-PROV-13`'s "before the first dispatch" is unassertable without one |
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


def test_sec_03_a_fully_confirmed_panel_passes_the_gate(network_guard):
    """The control every `raises` in this file depends on: the gate can be *passed*.

    Without it, a `verify_retention` consisting of a single `raise RetentionPolicyError` — a
    provider that confirms nothing, ever — satisfies every other test here. That was
    demonstrated against an earlier draft of this file: six green tests, and an implementation
    that could never start a `cloud-hosted` run.

    Two further assertions ride along, both from `CT-PROV-01`:

    - the report says **which** models were confirmed, not merely that all were. `TC-PROV-16`
      is "two of three", and an operator told only "failed" cannot act on it;
    - `verify_retention` makes **no model call**. It is one of the three synchronous operations
      the clause says do not dispatch, and a retention check implemented as a trial completion
      would send a payload to the provider it is still deciding about.
    """
    ModelRef = require(CONF_MODULE, "ModelRef", issue=ISSUE)
    OpenRouterProvider = require(PROVIDER_MODULE, "OpenRouterProvider", issue=ISSUE)

    panel = _panel(ModelRef)
    dispatched: list[object] = []
    provider = OpenRouterProvider(
        retention_answers={ref.build_id: True for ref in panel},
        on_dispatch=dispatched.append,
    )

    report = provider.verify_retention(panel)

    assert report.all_confirmed
    assert set(report.confirmed) == set(panel)
    assert tuple(report.unconfirmed) == ()
    assert dispatched == [], (
        "verify_retention dispatched a payload. CT-PROV-01: capabilities, estimate_cost and "
        "verify_retention make no model call — a retention check implemented as a trial "
        "completion sends student work to the provider it has not yet cleared."
    )
    network_guard.assert_no_network()


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
    """SEC-03's fail-closed half: an answer that is not a confirmation is a refusal.

    This is what separates a real gate from a plausible one. An implementation reading the
    provider's response with `bool(answer)` treats `"unknown"` as confirmation, and one using
    `answer is not False` treats `None` the same way. Both look correct in review and both send
    student work to a provider that never promised to delete it — so `SEC-03`'s expected
    defense ("`RetentionPolicyError`; the run does not start") is only worth asserting if
    *unconfirmed* covers these.

    **This is not `TC-PROV-17`.** That case belongs to `TS-05` (issue #22), which owns it
    together with `TC-PROV-16` and will assert it against the live provider API's actual
    response shapes. The assertion here is `SEC-03`'s own precondition, not a second suite for
    `FR-PROV-14` — see the module docstring's scope note.
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
