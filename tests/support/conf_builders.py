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
        "retention_setting": "zero-retention",
    }
    cfg.update(overrides)
    return cfg
