"""The off-panel checker: a model outside the scoring panel, its sessions and providers."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from .errors import OffPanelConfigurationError


#: The off-panel checker this deployment names — declared as None because the vocabulary
#: pins the knob and the deployment sets it, as ``provider/build_id[/quantization]``.
#: `back_translate` reads it when the caller passes no explicit checker (the env channel
#: outranks the constant, the way the threshold's channel does); nothing declared is the
#: enumerated unavailable mode — the gate never invents an adversary. The construction
#: transport a run actually uses is bound per build in `_OFF_PANEL_SESSIONS` (the
#: recorded-transport form); a build with no bound session is *unavailable*, never invented.
CALIB_OFF_PANEL_MODEL: str | None = None


CALIB_OFF_PANEL_MODEL_ENV: str = "HARNESS_CALIB_OFF_PANEL_MODEL"


def _off_panel_model_declared(
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """The deployment's declared off-panel checker, read from its knob at call time.

    The env channel outranks the constant, the way the threshold's channel does; a
    blank value is unset. None means the deployment declared no checker, and the gate
    refuses with the refusal that names the knob rather than inventing a checker."""
    source = os.environ if environ is None else environ
    raw = source.get(CALIB_OFF_PANEL_MODEL_ENV)
    if raw is not None and raw.strip():
        return raw.strip()
    return CALIB_OFF_PANEL_MODEL


def _off_panel_model_ref_from_declared(declared: str) -> OffPanelModelRef:
    """The `OffPanelModelRef` a declared checker string names: `provider/build_id`, optionally
    followed by `/quantization`. An unreadable string is refused, naming the knob, so a
    misconfiguration is rejected rather than silently weakening the check (NFR-CALIB-04)."""
    parts = declared.split("/")
    if len(parts) == 2 and all(parts):
        return OffPanelModelRef(provider=parts[0], build_id=parts[1])
    if len(parts) == 3 and all(parts):
        return OffPanelModelRef(provider=parts[0], build_id=parts[1], quantization=parts[2])
    raise OffPanelConfigurationError(
        f"the declared off-panel checker {declared!r} is not one this module can name: "
        f"declare it as provider/build_id[/quantization] (in {CALIB_OFF_PANEL_MODEL_ENV} "
        "or CALIB_OFF_PANEL_MODEL)"
    )


# --- the gates' registries and value types (the recorded-transport form, CT-PROV-10) ----------------


def _build_key(provider: str, build_id: str, quantization: str | None) -> str:
    """A build's identity, encoded exactly as M-CONF's `compute_panel_build_ref` hashes it
    (provider, build id, quantization or empty). M-CALIB does not import M-CONF for this, so the
    encoding is repeated here; M-CONF remains the owner of the formula."""
    return f"{provider}\x1f{build_id}\x1f{quantization or ''}"


@dataclass(frozen=True)
class OffPanelModelRef:
    """A pinned identity for the off-panel checker, shaped like M-CONF's `ModelRef` (design §3.1)
    but kept local so the gates accept any provider, build and quantization without importing
    M-CONF.

    Identity is the **served build** — provider, build id, quantization — not the
    label, which is what makes the shared-build refusal (`CT-CALIB-08`,
    `NFR-CALIB-04`) key on the thing that actually runs."""

    provider: str
    build_id: str
    quantization: str | None = None

    @property
    def build_key(self) -> str:
        return _build_key(self.provider, self.build_id, self.quantization)


@dataclass(frozen=True)
class _ConstructionAttempt:
    """One attempt by the off-panel model: the angle tried and what it produced.

    ``response`` is the constructed student response, or None when the angle failed to
    construct one — a failed attempt is a result, not an error (§6.6: the model tries
    several angles; the pass case's note holds that absence of evidence is not evidence
    of preservation)."""

    angle: str
    response: str | None
    divergence_note: str | None = None


@dataclass(frozen=True)
class _BackTranslationSession:
    """The recorded attempts of one off-panel build to construct a response that R0 and R1 would
    score differently (CT-PROV-10).

    Wiring binds the session for the off-panel build the same way discovery's bands are
    injected, so the gate needs no network and no real upstream, and the provider stays
    the only egress point (`CT-PROV-15`)."""

    attempts: tuple[_ConstructionAttempt, ...]

    @property
    def constructed(self) -> _ConstructionAttempt | None:
        """The first attempt that produced such a response, or None."""
        for attempt in self.attempts:
            if attempt.response is not None:
                return attempt
        return None


#: The panel's served builds — what `model_ref_in_panel` registers and `back_translate`
#: checks off-panel membership against.
_PANEL_BUILDS: set[str] = set()


#: Each off-panel build's bound construction session, by build key.
_OFF_PANEL_SESSIONS: dict[str, _BackTranslationSession] = {}


#: #536 (CT-PROV-08): an `InferenceProvider` bound for an off-panel build. The gate asks it
#: through `complete()`; a bound recorded session is served through the same call.
_OFF_PANEL_PROVIDERS: dict[str, Any] = {}


#: The angles a construction probes when the checker is a live provider (a recorded session
#: carries its own).
_BACK_TRANSLATION_ANGLES: tuple[str, ...] = (
    "probing the top band's boundary",
    "probing the bottom band's boundary",
    "a response the clarified descriptor reads differently",
)


class _RecordedSessionProvider:
    """Serves a recorded session as an `InferenceProvider` (CT-PROV-10): each `complete()` returns
    one angle's recorded attempt as JSON, so the gate always calls `complete()`, recorded or live.
    """

    def __init__(self, session: "_BackTranslationSession") -> None:
        self._by_angle = {attempt.angle: attempt for attempt in session.attempts}
        self.angles = tuple(attempt.angle for attempt in session.attempts)

    def complete(self, payload: Any, model_ref: Any, sampling: Any) -> Any:
        angle = dict(payload.fields).get("angle", "")
        attempt = self._by_angle.get(angle)
        text = json.dumps({"response": getattr(attempt, "response", None),
                           "divergence_note": getattr(attempt, "divergence_note", None)})
        return SimpleNamespace(text=text)


def unbind_off_panel_provider(ref: "OffPanelModelRef") -> None:
    """Remove the provider bound for this build, so a binding does not outlive the caller that made
    it."""
    _OFF_PANEL_PROVIDERS.pop(ref.build_key, None)


def bind_off_panel_provider(ref: "OffPanelModelRef", provider: Any) -> None:
    """Bind the provider the back-translation gate uses for this build (CT-PROV-08). The provider
    remains the only egress point (CT-PROV-15)."""
    _OFF_PANEL_PROVIDERS[ref.build_key] = provider
