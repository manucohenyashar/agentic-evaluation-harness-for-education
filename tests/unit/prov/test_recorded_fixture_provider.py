"""`RecordedFixtureProvider` — the hermetic model boundary.

Cases: `TC-PROV-13`, `TC-PROV-14` (test plan §5.2), both `FR-PROV-10`, both P0, rung 1.

Why these two are P0 for the *whole* plan rather than just for `M-PROV`: §4.2 says almost
every fast-tier case runs against this provider, so if it can reach the network, or if it can
answer a changed prompt from a stale recording, then the fast tier stays green while
describing a system that does not exist (RISK-37).

**Written ahead of implementation** (issue #18, S-PROV-01). Expected to fail with
`NotImplementedYet` until it lands. Remove the `writtenahead` marker — not the test — when
#18 closes.

Interface expectations this test places on #18, so they are visible rather than buried:
`ModelRef` from `aeh.conf` (design §3.1) and `PromptPayload`, `SamplingParams`, `Completion`,
`FixtureMissingError`, `RecordedFixtureProvider` from `aeh.prov` (design §3.2). One name is
*not* in the design: a `record(...)` method for putting a response into the fixture set.
`FR-PROV-10` fixes the lookup ("keyed by a hash of the fully-assembled request") and §4.4
says `F-RECORDED` is "regenerated nightly", so a recording path must exist — but the design
never names it. Raised as a finding on the PR; renaming it is a one-line change here.
"""

from __future__ import annotations

import pytest

from tests.support.impl import PROVIDER_MODULE, require

pytestmark = pytest.mark.writtenahead

CONF_MODULE = "aeh.conf"
ISSUE = "#18"


def _judge_ref(model_ref_cls):
    """A resolved `edge-local` judge build (design §3.1: path + quantization + hash)."""
    return model_ref_cls(
        role="judge",
        provider="ollama",
        build_id="/models/llama-3.3-70b.gguf@sha256:aaaa",
        quantization="q4",
    )


def _payload(payload_cls, criterion_text: str):
    """An assembled prompt. The submission goes last, per `FR-JUDGE-07` / `FR-EXTRACT-04`."""
    return payload_cls(
        fields=(
            ("system", "You are scoring one criterion."),
            ("criterion", criterion_text),
            ("submission", "The block slides because friction is lower than gravity."),
        )
    )


def test_tc_prov_13_known_request_returns_fixture_unknown_raises_and_never_connects(
    make_fixture_provider, network_guard
):
    """TC-PROV-13 — a request whose hash is in the fixture set returns the stored response;
    one that is not raises `FixtureMissingError`, with **no network call attempted**.

    Oracle (§5.2): exact exception **plus socket guard**. Both halves are asserted — the
    guard check is not decoration. A provider that tried to reach the network and swallowed
    the failure would satisfy the exception assertion on its own, and that is precisely the
    bug this case exists to catch.
    """
    fixture_provider = make_fixture_provider()
    ModelRef = require(CONF_MODULE, "ModelRef", issue=ISSUE)
    PromptPayload, SamplingParams, Completion, FixtureMissingError = require(
        PROVIDER_MODULE,
        "PromptPayload",
        "SamplingParams",
        "Completion",
        "FixtureMissingError",
        issue=ISSUE,
    )

    model_ref = _judge_ref(ModelRef)
    params = SamplingParams(temperature=0.0)
    known = _payload(PromptPayload, "States that friction opposes motion.")
    unknown = _payload(PromptPayload, "States that momentum is conserved.")

    recorded = Completion(
        text='{"band": "met"}',
        tokens_in=1800,
        tokens_out=12,
        latency_ms=430,
        resolved_build="llama-3.3-70b@q4",
        cached_prefix_tokens=1500,
        cost=None,  # null on fixture and edge-local — CT-PROV-03
    )
    fixture_provider.record(known, model_ref, params, recorded)

    # The known request resolves to exactly the stored response.
    got = fixture_provider.complete(known, model_ref, params)
    assert got == recorded

    # The unknown one raises rather than falling through to a network call.
    with pytest.raises(FixtureMissingError):
        fixture_provider.complete(unknown, model_ref, params)

    # The second half of the oracle: nothing tried to open a socket, in either call.
    network_guard.assert_no_network()


def test_tc_prov_14_one_byte_change_invalidates_the_fixture_key(make_fixture_provider):
    """TC-PROV-14 — the same logical request with **one byte** changed in the assembled
    prompt produces a different fixture key and raises `FixtureMissingError`.

    This is the property that makes the whole fast tier trustworthy: §4.2 — "any change to
    prompt assembly changes the key and fails loudly instead of silently returning a stale
    answer". A provider keyed on anything coarser than the assembled bytes (the model ref, a
    logical request id, a normalized prompt) passes TC-PROV-13 and fails here.

    Oracle (§5.2): exact exception.
    """
    fixture_provider = make_fixture_provider()
    ModelRef = require(CONF_MODULE, "ModelRef", issue=ISSUE)
    PromptPayload, SamplingParams, Completion, FixtureMissingError = require(
        PROVIDER_MODULE,
        "PromptPayload",
        "SamplingParams",
        "Completion",
        "FixtureMissingError",
        issue=ISSUE,
    )

    model_ref = _judge_ref(ModelRef)
    params = SamplingParams(temperature=0.0)

    original_text = "States that friction opposes motion."
    # Exactly one byte differs: the final period becomes an exclamation mark. Same length,
    # same words, same field order — nothing a normalizing key would notice.
    one_byte_changed = original_text[:-1] + "!"
    assert len(one_byte_changed) == len(original_text)
    assert sum(a != b for a, b in zip(original_text, one_byte_changed)) == 1

    recorded = Completion(
        text='{"band": "met"}',
        tokens_in=1800,
        tokens_out=12,
        latency_ms=430,
        resolved_build="llama-3.3-70b@q4",
        cached_prefix_tokens=1500,
        cost=None,
    )
    fixture_provider.record(
        _payload(PromptPayload, original_text), model_ref, params, recorded
    )

    # Sanity: the recorded request itself still resolves, so a failure below is about the
    # changed byte and not about recording being broken.
    assert fixture_provider.complete(
        _payload(PromptPayload, original_text), model_ref, params
    ) == recorded

    with pytest.raises(FixtureMissingError):
        fixture_provider.complete(
            _payload(PromptPayload, one_byte_changed), model_ref, params
        )
