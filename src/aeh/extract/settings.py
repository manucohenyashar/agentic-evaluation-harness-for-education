"""The prompt version, the optional second-family extractor, and their knobs."""

from __future__ import annotations

import os
from typing import Any

from aeh.conf import ModelRef


# --- vocabulary ----------------------------------------------------------------------------------

#: The pinned extraction-prompt template version (`NFR-EXTRACT-03`). The run's
#: `prompt_template_v` configuration carries it into `compute_work_id`'s hash at the
#: orchestration boundary — a caller that configures the run with this constant (as
#: the contract suite does) gets the automatic invalidation of dependent extract
#: units on a template change, no cleanup job (`TC-EXTRACT-13`); this module only
#: pins the value and renders by it. Bumped `extract-prompt/1` → `extract-prompt/2` by
#: #81's escape fix below (the constant's own contract: the render changed in the same
#: change — transcripts carrying a raw marker now render the well-formed escape, so
#: dependent extract units invalidate and re-extract rather than compare stale bytes).
EXTRACTION_PROMPT_TEMPLATE_VERSION = "extract-prompt/2"


# --- the second family (FR-EXTRACT-07) ------------------------------------------------------------

#: The second-family model: the DIFFERENT-family model a flagged criterion's second
#: extraction runs on (`FR-EXTRACT-07`). `ModelRef` carries no `family` field, so the
#: family is the build/provider pair (`tests/support/extract_vocabulary.py`'s
#: disclosed reading) — this default differs from the primary extractor's on BOTH,
#: and the worker refuses a second ref whose pair repeats the primary's (a second
#: call to the same build is not a second opinion). The role is still the
#: extractor's (`NFR-EXTRACT-01` — both extractions run on the one small-model role,
#: no judge involved).
#:
#: The provider is deliberately the deterministic transport and not a real backend's
#: name: which backend answers is `M-PROV`'s to know (`TC-PROV-05`'s seam — a module
#: outside it and `M-CONF` may not carry a backend constant), so a deployment that
#: runs flagged criteria names ITS second family through
#: `HARNESS_EXTRACT_SECOND_FAMILY_MODEL` or the `second_family_model=` constructor
#: keyword. An unconfigured
#: deployment's second pass misses loudly (the transport's own contract — an
#: unrecorded request never answers), and the miss is recorded as that family's
#: error in the payload, never silently passed off as a second opinion. The register
#: itself (`Q-12`) arrives the same way — `high_risk_criteria=` — because its
#: contents are operator policy, never a constant of this module.
second_family_model = ModelRef(
    role="extractor",
    provider="fixture",
    build_id="/models/llama3.3-8b.gguf@sha256:ffff",
    quantization="q4",
)


#: Deployment knobs, read at **call** time (the four-seams rule). A one-model box
#: sets `HARNESS_EXTRACT_SECOND_FAMILY=0` and flagged criteria extract once — the
#: degradation is said in the result's notes, never silent — and
#: `HARNESS_EXTRACT_SECOND_FAMILY_MODEL` (as `provider|build_id`) overrides which
#: second family the default constructor builds. Production default: the pass ON,
#: this module's `second_family_model`.
SECOND_FAMILY_ENV = "HARNESS_EXTRACT_SECOND_FAMILY"


SECOND_FAMILY_MODEL_ENV = "HARNESS_EXTRACT_SECOND_FAMILY_MODEL"


def _env_bool(name: str, default: bool) -> bool:
    """A boolean knob, read at call time: absent means the default, a known word
    means its truth, anything else is REFUSED (`_env_int`'s discipline — a knob that
    guesses is a lie the deployment cannot see)."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    lowered = raw.strip().lower()
    if lowered in ("0", "false", "off", "no"):
        return False
    if lowered in ("1", "true", "on", "yes"):
        return True
    raise ValueError(
        f"{name}={raw!r} is not a boolean — refused, not guessed"
    )


def _second_family_ref(explicit: Any) -> Any:
    """The effective second-family `ModelRef`: the caller's when given, else the
    env override, else this module's default — read at call time, so a deployment
    adjusts without a code change."""
    if explicit is not None:
        return explicit
    raw = os.environ.get(SECOND_FAMILY_MODEL_ENV)
    if raw is None or not raw.strip():
        return second_family_model
    provider, sep, build_id = raw.strip().partition("|")
    if not sep or not provider.strip() or not build_id.strip():
        raise ValueError(
            f"{SECOND_FAMILY_MODEL_ENV}={raw!r} must be 'provider|build_id' — "
            f"refused, not guessed"
        )
    return ModelRef(
        role="extractor",
        provider=provider.strip(),
        build_id=build_id.strip(),
        quantization="q4",
    )


#: FR-SETUP-09's evidence type when a criterion declares none (the design's own example,
#: detailed-design §3.8). A published package carries one per judged criterion.
DEFAULT_EVIDENCE_TYPE = "textual_span"
