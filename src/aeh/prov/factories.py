"""Choosing the provider a model reference names, for completions and for decisions."""

from __future__ import annotations

from typing import Any

from aeh.conf import ConfigurationError, ModelRef

from .errors import ProviderUnavailableError
from .interface import InferenceProvider
from .live import _LOCAL_SERVER_PROVIDER_NAMES, LocalServerProvider, OpenRouterProvider
from .decision_base import DecisionProvider, _UNSHIPPED_DECISION_PROVIDERS
from .jev_openrouter import JevOpenRouterProvider
from .openjev_local import OpenJevLocalProvider, OpenJevSmallLocalProvider
from .fixtures import RecordedFixtureProvider


def provider_for(model_ref: ModelRef, **seams: Any) -> "InferenceProvider":
    """The live transport a model ref's declared provider name selects (`FR-PROV-11`).

    A consumer asks for the transport **by ref** and names no backend itself: the
    name → implementation mapping is M-PROV's, so a module outside `M-PROV` never carries
    a backend-specific constant (`TC-PROV-05`'s scan reads the tree for exactly that).
    Unknown names refuse — an unserved backend is a configuration error, never a silent
    fall-back to a transport the caller did not ask for.
    """
    name = str(getattr(model_ref, "provider", "") or "")
    if name in _LOCAL_SERVER_PROVIDER_NAMES:
        return LocalServerProvider(**seams)
    if name == "openrouter":
        return OpenRouterProvider(**seams)
    raise ProviderUnavailableError(f"no shipped live transport for provider {name!r}")


def decision_provider_for(model_ref: ModelRef, **seams: Any) -> "DecisionProvider":
    """The only construction path for a decision provider (FR-PROV-26), by `ModelRef.provider`.
    Unknown names raise `ConfigurationError`; nothing is substituted."""
    name = str(getattr(model_ref, "provider", "") or "")
    if name == "fixture":
        return RecordedFixtureProvider(**seams)
    if name == "openrouter-jev":
        return JevOpenRouterProvider(**seams)
    if name == "openjev":
        return OpenJevLocalProvider(**seams)
    if name == "openjev-small":
        return OpenJevSmallLocalProvider(**seams)
    if name in _UNSHIPPED_DECISION_PROVIDERS:
        raise ConfigurationError(
            f"decision provider {name!r} is designed but not shipped yet: "
            f"{_UNSHIPPED_DECISION_PROVIDERS[name]}.")
    raise ConfigurationError(
        f"no decision provider is named {name!r}; the decision providers are "
        f"{sorted(['fixture', 'openrouter-jev', 'openjev', 'openjev-small', *_UNSHIPPED_DECISION_PROVIDERS])} (FR-PROV-26).")
