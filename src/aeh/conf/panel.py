"""The stable hash over the ordered judge panel (`compute_panel_build_ref`)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import hashlib
from collections.abc import Sequence

from .model_ref import ModelRef

if TYPE_CHECKING:
    from .decision_engine import DecisionEngine


# --- panel build ref -----------------------------------------------------------------------

_FIELD_SEP = "\x1f"


_REF_SEP = "\n"


_PANEL_BUILD_REF_PREFIX = "pbr:"


_PANEL_BUILD_REF_LENGTH = 32


def _build_identity(ref: ModelRef) -> str:
    """The canonical identity of one served build, exactly as `compute_panel_build_ref` hashes it.
    Two references with the same identity are the same model whatever they are called, which is why
    the off-panel check (CT-CALIB-08) compares these rather than provider or display names."""
    return f"{ref.provider}{_FIELD_SEP}{ref.build_id}{_FIELD_SEP}{ref.quantization or ''}"


def compute_panel_build_ref(panel: Sequence[ModelRef], decision_engine: "DecisionEngine | None" = None) -> str:
    """A stable hash over the ordered judge panel (FR-CONF-05, CT-CONF-07).

    Canonical encoding, fixed here because it is a primary-key component of every
    `package_validation` row and `TC-CONF-05`'s oracle is an exact value against a committed
    reference hash — changing this formula invalidates every stored key:

        "pbr:" + sha256("\\n".join(f"{provider}\\x1f{build_id}\\x1f{quantization or ''}"))[:32]

    Iteration order is the panel's own and is **never** sorted. `CT-CONF-C07` names sorting as
    the exact regression to catch: two distinct panels would silently merge under one key.

    Issue #5 owns `FR-CONF-05` in full — the documented canonical ordering and the committed
    reference hash. It is computed here because `CT-CONF-C02` pins `RunConfig` to twelve fields,
    so the field cannot be deferred, and #5 depends on #4.
    """
    payload = _REF_SEP.join(_build_identity(ref) for ref in panel)
    if decision_engine is not None:
        # FR-CONF-22: the engine and its frozen values are part of "which grader is this run".
        # Only when present, so an engine-off ref is byte-identical to its pre-delta value.
        payload += _REF_SEP + "decision" + _FIELD_SEP + decision_engine.identity()
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return _PANEL_BUILD_REF_PREFIX + digest[:_PANEL_BUILD_REF_LENGTH]
