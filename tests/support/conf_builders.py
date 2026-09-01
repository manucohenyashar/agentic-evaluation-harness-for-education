"""Legal `M-CONF` inputs, so each case shows only what it varies.

Every `TC-CONF-*` case is a negative or a boundary on **one** axis — the profile, the hardware
profile, one model ref, one cost field. Spelling a full valid `cfg` out in each test would bury
that axis in eleven lines of scaffolding, and a reader could not tell which line the case is
actually about.

Not fixtures: `TC-CONF-15` and `TC-CONF-16` are hypothesis property cases, and a function-scoped
fixture inside `@given` is re-used across examples rather than rebuilt, which is exactly the
sharing `HealthCheck.function_scoped_fixture` warns about. Plain builders return a fresh dict
per call from any context.

Design §3.1's Interfaces block is the source for every literal here; the `@sha256:` weights form
matches the one already committed in `tests/unit/prov/test_recorded_fixture_provider.py`.
"""

from __future__ import annotations

from typing import Any

from aeh.conf import CohortRef, ModelRef

# A synthetic cohort, so `FR-CONF-08`'s consent gate (issue #6) is never the reason a case in
# this suite fails. Cases that exercise the gate itself live in TS-04 (issue #8).
SYNTHETIC_COHORT = CohortRef(cohort_id="c-2026-7B-physics", consent_class="synthetic")

EDGE_JUDGE = ModelRef(
    role="judge",
    provider="ollama",
    build_id="/models/llama-3.3-70b.gguf@sha256:aaaa",
    quantization="q4",
)
EDGE_TRANSCRIBER = ModelRef(
    role="transcriber",
    provider="ollama",
    build_id="/models/whisper-large-v3.gguf@sha256:bbbb",
    quantization="q4",
)
EDGE_OFF_PANEL = ModelRef(
    role="off_panel",
    provider="ollama",
    build_id="/models/qwen-2.5-7b.gguf@sha256:cccc",
    quantization="q4",
)

HOSTED_JUDGE = ModelRef(
    role="judge",
    provider="openrouter",
    build_id="meta-llama/llama-3.3-70b-instruct@2024-12-06",
    quantization=None,
)
HOSTED_TRANSCRIBER = ModelRef(
    role="transcriber",
    provider="openrouter",
    build_id="openai/whisper-1@2024-11-02",
    quantization=None,
)

PROMPT_TEMPLATE_V = "conf-v1.0.0"


def default_retention_setting() -> str:
    """A `retention_setting` every hosted config in the suite can carry.

    Read from `aeh.conf` when issue #6 declares the vocabulary (`FR-CONF-12`), with a literal
    fallback until then. Neither the design nor the test plan names the legal values — only
    "unrecognized refuses" — so hard-coding `"zero-retention"` here would silently make it the
    requirement: if #6 lands `"none"` or an enum, **every** hosted test in this suite would go
    red for a reason `FR-CONF-12` does not ask for, not just `TC-CONF-12`.

    Same reasoning `TC-CONF-10` applies to the prefix ceilings: assert the mechanism, not the
    Assumption.
    """
    import aeh.conf

    declared = getattr(aeh.conf, "RETENTION_SETTINGS", None)
    if declared:
        return sorted(declared)[0]
    return "zero-retention"


def edge_cfg(**overrides: Any) -> dict[str, Any]:
    """A resolvable `edge-local` configuration. `**overrides` replaces keys; pop to remove."""
    cfg: dict[str, Any] = {
        "HARNESS_PROFILE": "edge-local",
        "HARNESS_HARDWARE_PROFILE": "unified-large",
        "panel": (EDGE_JUDGE,),
        "transcriber": EDGE_TRANSCRIBER,
        "prompt_template_v": PROMPT_TEMPLATE_V,
    }
    cfg.update(overrides)
    return cfg


def hosted_cfg(profile: str = "cloud-hosted", **overrides: Any) -> dict[str, Any]:
    """A resolvable `cloud-hosted` (or `dev-ci`) configuration."""
    cfg: dict[str, Any] = {
        "HARNESS_PROFILE": profile,
        "HARNESS_COST_CEILING": "12.50",
        "HARNESS_COST_CURRENCY": "USD",
        "panel": (HOSTED_JUDGE,),
        "transcriber": HOSTED_TRANSCRIBER,
        "prompt_template_v": PROMPT_TEMPLATE_V,
        "retention_setting": default_retention_setting(),
    }
    cfg.update(overrides)
    return cfg


# --- a three-judge panel ---------------------------------------------------------------------

#: A second and third judge, so a case can use a panel that is not length 1.
#:
#: `edge_cfg()` and `hosted_cfg()` default to **one** judge, and that is a blind spot rather than
#: a convenience: an implementation returning `panel[:1]` — from `profile_summary()`, from a
#: validation loop — is indistinguishable from a correct one when the panel has a single member.
#: Any case about "every panel build" or "every reachable ref" should reach for these.
EDGE_JUDGE_2 = ModelRef(
    role="judge",
    provider="ollama",
    build_id="/models/qwen-2.5-72b.gguf@sha256:dddd",
    quantization="q4",
)
EDGE_JUDGE_3 = ModelRef(
    role="judge",
    provider="vllm-mlx",
    build_id="/models/mistral-large.gguf@sha256:eeee",
    quantization="q8",
)
EDGE_PANEL_3 = (EDGE_JUDGE, EDGE_JUDGE_2, EDGE_JUDGE_3)

HOSTED_JUDGE_2 = ModelRef(
    role="judge",
    provider="openrouter",
    build_id="qwen/qwen-2.5-72b-instruct@2024-09-19",
    quantization=None,
)
HOSTED_JUDGE_3 = ModelRef(
    role="judge",
    provider="openrouter",
    build_id="mistralai/mistral-large@2024-11-18",
    quantization=None,
)
HOSTED_PANEL_3 = (HOSTED_JUDGE, HOSTED_JUDGE_2, HOSTED_JUDGE_3)


# --- credential sentinels --------------------------------------------------------------------

#: The exact value `TC-CONF-11`'s preconditions name.
SENTINEL_CREDENTIAL = "sk-or-v1-SENTINEL-0123456789abcdef"

#: A second sentinel carrying regex metacharacters — `TC-CONF-11`'s stated variant, "a credential
#: containing regex metacharacters does not break the scan". A scanner that compiles the sentinel
#: as a pattern rather than searching for it literally fails here and nowhere else.
SENTINEL_WITH_METACHARACTERS = r"sk-or-v1-SEN(TIN[EL]).*+?^$|\{2}"

#: Every variable the design names as credential-bearing, plus the shapes a careless operator
#: reaches for. `FR-CONF-11` names `OPENROUTER_API_KEY`; the rest are "every other
#: credential-bearing variable" from the same preconditions.
CREDENTIAL_ENV_VARS = (
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "HF_TOKEN",
    "HARNESS_API_KEY",
)


def seed_credentials(monkeypatch, sentinel: str = SENTINEL_CREDENTIAL) -> str:
    """Put `sentinel` in every credential-bearing environment variable. Returns it.

    **Why this is not enough on its own, and every caller also injects into `cfg`.**
    `TC-CONF-11`'s precondition says "an environment snapshot carrying the sentinel credential in
    `OPENROUTER_API_KEY`" — but `environment_snapshot()` lifts only the six `HARNESS_*` keys, so a
    credential seeded here never reaches `cfg`, never reaches the module, and a scan of the
    module's surfaces would find nothing **whatever the module did**. That is a vacuous pass: the
    test would stay green against an implementation that copied the key straight into
    `to_persisted_dict()`.

    So the environment half proves the module does not *reach out* for a credential, and the
    `cfg` half proves it does not *pass one through*. Both are needed and neither is sufficient.
    """
    for var in CREDENTIAL_ENV_VARS:
        monkeypatch.setenv(var, sentinel)
    return sentinel
