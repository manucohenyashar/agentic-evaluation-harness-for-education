"""`RecordedFixtureProvider` — the hermetic model boundary.

Cases: `TC-PROV-13`, `TC-PROV-14` (test plan §5.2), both `FR-PROV-10`, both P0, rung 1.

Why these two are P0 for the *whole* plan rather than just for `M-PROV`: §4.2 says almost
every fast-tier case runs against this provider, so if it can reach the network, or if it can
answer a changed prompt from a stale recording, then the fast tier stays green while
describing a system that does not exist (RISK-37).

**Written ahead of implementation** (issue #18, S-PROV-01). Expected to fail with
`NotImplementedYet` until it lands. Remove the `writtenahead` marker — not the test — when
#18 closes.

Interface expectations this test places on #18, listed in full so they are visible rather
than buried — a signature mismatch surfaces as a `TypeError`, not as `require()`'s clean
`NotImplementedYet`, so #18 should reconcile these deliberately:

| Name | Status in the design |
|---|---|
| `ModelRef(role, provider, build_id, quantization)` from `aeh.conf` | defined, design §3.1 |
| `Completion(text, tokens_in, tokens_out, latency_ms, resolved_build, cached_prefix_tokens, cost)` | defined, design §3.2 |
| `provider.complete(prompt, model_ref, params)` | defined, design §3.2 |
| `PromptPayload(fields=...)` | **named but not specified** — the field structure is chosen here |
| `SamplingParams(temperature=...)` | **named but not specified** |
| `RecordedFixtureProvider(fixture_dir=...)` | class named in design §3.2; the constructor argument is chosen here, from `HARNESS_FIXTURE_DIR` |
| `provider.record(prompt, model_ref, params, completion)` | **not in the design at all** |

`record()` is the one genuinely invented name. `FR-PROV-10` fixes the lookup ("keyed by a
hash of the fully-assembled request") and §4.4 says `F-RECORDED` is "regenerated nightly", so
a recording path must exist — but nothing names it. Raised as a finding on the PR.
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



# Each entry mutates the *recorded* request in one way and must produce a fixture miss.
# The set is chosen to discriminate the key implementations that pass a naive version of
# this case: a key that lowercases, one that collapses whitespace, one that ignores the
# model ref, one that ignores sampling params. FR-PROV-10 says "a hash of the
# fully-assembled request", and each of these is part of that request.
_KEY_MUTATIONS = [
    # (id, criterion text, build_id, temperature)
    ("one_byte_punctuation", "States that friction opposes motion!", None, None),
    ("whitespace_only", "States that friction  opposes motion.", None, None),
    ("case_only", "states that friction opposes motion.", None, None),
    ("model_build", None, "/models/llama-3.3-70b.gguf@sha256:bbbb", None),
    ("sampling_params", None, None, 0.7),
]


@pytest.mark.parametrize(
    "mutation", [m[0] for m in _KEY_MUTATIONS], ids=[m[0] for m in _KEY_MUTATIONS]
)
def test_tc_prov_14_any_change_to_the_assembled_request_invalidates_the_fixture_key(
    make_fixture_provider, mutation
):
    """TC-PROV-14 — the same logical request, changed in one respect, produces a different
    fixture key and raises `FixtureMissingError`.

    §4.2 states the property this protects: *"any change to prompt assembly changes the key
    and fails loudly instead of silently returning a stale answer."* Without it, a prompt
    change silently reuses an old recording and the whole fast tier keeps passing while
    describing a system that no longer exists.

    The five mutations are the discriminating set. A single punctuation byte alone is not
    enough: it survives whitespace collapsing and lowercasing, so a key that normalizes the
    prompt — or one that omits `model_ref` or `SamplingParams` entirely — passes a
    one-byte-only version of this case while violating `FR-PROV-10`'s "fully-assembled
    request". Each mutation below turns exactly one of those implementations red.

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

    _, text, build_id, temperature = next(m for m in _KEY_MUTATIONS if m[0] == mutation)

    baseline_text = "States that friction opposes motion."
    baseline_ref = _judge_ref(ModelRef)
    baseline_params = SamplingParams(temperature=0.0)

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
        _payload(PromptPayload, baseline_text), baseline_ref, baseline_params, recorded
    )

    # Sanity: the recorded request itself still resolves, so a miss below is caused by the
    # mutation and not by recording being broken.
    assert (
        fixture_provider.complete(
            _payload(PromptPayload, baseline_text), baseline_ref, baseline_params
        )
        == recorded
    )

    mutated_ref = (
        ModelRef(
            role=baseline_ref.role,
            provider=baseline_ref.provider,
            build_id=build_id,
            quantization=baseline_ref.quantization,
        )
        if build_id is not None
        else baseline_ref
    )
    mutated_params = (
        SamplingParams(temperature=temperature)
        if temperature is not None
        else baseline_params
    )
    mutated_payload = _payload(PromptPayload, text if text is not None else baseline_text)

    with pytest.raises(FixtureMissingError):
        fixture_provider.complete(mutated_payload, mutated_ref, mutated_params)
