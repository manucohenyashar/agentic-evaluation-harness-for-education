"""The Q&A assistant's model (FR-CONF-30, CT-CONF-22): resolved with the rest of the run's
configuration and frozen with it.

The assistant answers teachers' questions from the manuals (`M-HELP`). It is **not** a grader:
its ref never enters `panel_build_ref` or the `ProfileSummary`, and the consent gate does not
treat it as dispatching student work, because no student work reaches it (FR-CONF-31).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .checks import _check_resolved
from .errors import ConfigurationError
from .model_ref import ModelRef

#: The knob that picks the assistant's model on the cloud profiles. `edge-local` has none: there,
#: the assistant is the first grading judge already loaded on the machine.
QA_MODEL_KEY = "HARNESS_QA_MODEL"


#: The profiles where `QA_MODEL_KEY` is read. Its value is an OpenRouter build string.
QA_KNOB_PROFILES: frozenset[str] = frozenset({"cloud-hosted", "dev-ci"})


QA_MODEL_PROVIDER = "openrouter"


#: The role a knob-named assistant ref carries. `ModelRef`'s role vocabulary has no assistant
#: role, and the default (`panel[0]`) is a judge ref, so both arms carry the same role.
QA_MODEL_ROLE = "judge"


def resolve_qa_model(cfg: Mapping[str, Any], backend_profile: str, panel: tuple[ModelRef, ...]) -> ModelRef:
    """The assistant's model for a run on `backend_profile` (FR-CONF-30).

    On the cloud profiles: `HARNESS_QA_MODEL` when set, refused unless it is a pinned build (no
    floating tag), else `panel[0]`. On `edge-local`: always `panel[0]`; the knob is ignored, not
    refused, because an exported cloud setting must not make a local run impossible to start
    (the same rule `_resolve_cost` follows for inapplicable keys).
    """
    if backend_profile not in QA_KNOB_PROFILES:
        return panel[0]
    raw = cfg.get(QA_MODEL_KEY)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return panel[0]
    if not isinstance(raw, str):
        raise ConfigurationError(
            f"{QA_MODEL_KEY} must be an OpenRouter build string, got {type(raw).__name__}.")
    ref = ModelRef(role=QA_MODEL_ROLE, provider=QA_MODEL_PROVIDER, build_id=raw.strip(), quantization=None)
    _check_resolved(ref, QA_MODEL_KEY, backend_profile)
    return ref
