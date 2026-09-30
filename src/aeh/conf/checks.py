"""The checks shared by `RunConfig` and its resolution: pinned builds, cost-bearing profiles, retention."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from .vocabulary import BuildForm
from .errors import ConfigurationError, UnresolvedModelRefError
from .model_ref import ModelRef, WEIGHTS_SUFFIXES


#: Keys whose value is safe to echo in an exception message. Everything else is named by key
#: only — `NFR-CONF-02` forbids a credential reaching any message this module emits, and the
#: cheapest way to guarantee that is to never interpolate a value that is not on this list.
_ECHOABLE_KEYS = frozenset(
    {
        "HARNESS_PROFILE",
        "HARNESS_HARDWARE_PROFILE",
        "HARNESS_COST_CURRENCY",
        "HARNESS_CONCURRENCY",
        "HARNESS_ALLOW_REMOTE_REAL_WORK",
    }
)


# --- resolution ----------------------------------------------------------------------------

#: A `MappingProxyType` for the same reason `HARDWARE_PROFILES` is one: `resolve_run_config`
#: reads it, so a mutable copy would make resolution a function of process state. Mutating it
#: between two calls would change which build form each backend requires -- and `TC-CONF-C05`,
#: which perturbs only the *environment*, could not see it. Found by `TC-CONF-13`'s
#: immutable-globals assertion.
_REQUIRED_BUILD_FORM: Mapping[str, BuildForm] = MappingProxyType({
    "edge-local": "edge-weights",
    "cloud-hosted": "provider-pinned",
    "dev-ci": "provider-pinned",
})


_COST_BEARING_PROFILES = frozenset({"cloud-hosted", "dev-ci"})


def _echo(key: str, value: Any) -> str:
    """Render a value for an exception message, or hide it. See `_ECHOABLE_KEYS`."""
    return repr(value) if key in _ECHOABLE_KEYS else "<not shown>"


def _check_resolved(ref: ModelRef, what: str, backend_profile: str) -> None:
    """`FR-CONF-03` plus the per-backend half of `CT-CONF-03`.

    `is_resolved()` answers "is this *a* resolved build". The backend then decides *which* form
    counts: a provider-pinned slug is a perfectly resolved identity and still wrong on
    `edge-local`, where nothing but a weights path can name what ran.
    """
    form = ref.build_form()
    if form is None:
        # The position, never the value. `NFR-CONF-02` forbids a credential reaching any
        # message this module emits, and a `build_id` is caller data that can carry one in a
        # query string. The caller holds the config, so `panel[2]` locates the ref exactly.
        raise UnresolvedModelRefError(
            f"{what} is not a resolved build identity. Expected a weights path plus "
            f"quantization plus hash, or a provider-pinned slug (FR-CONF-03). The offending "
            f"value is not echoed here; read it from the config at {what}."
        )
    expected = _REQUIRED_BUILD_FORM[backend_profile]
    if form != expected:
        # Name the discriminator in the message. The commonest way to hit this is a weights
        # path whose extension is not in WEIGHTS_SUFFIXES — it reads as provider-pinned, and
        # "requires an edge-weights build" alone would send the reader hunting for a missing
        # hash they in fact supplied.
        raise UnresolvedModelRefError(
            f"{what} is a {form} build, but backend_profile {backend_profile!r} requires a "
            f"{expected} build (CT-CONF-03). The two forms are told apart by WEIGHTS_SUFFIXES "
            f"{WEIGHTS_SUFFIXES}: a path outside that list is read as a provider-pinned slug. "
            f"The build_id is not echoed here (NFR-CONF-02); read it from the config at {what}."
        )


def _positive_int(raw: Any, key: str, default: int) -> int:
    """Parse an optional integer knob, refusing anything that is not one.

    A knob that silently ignores a value it cannot parse is worse than one with no default:
    the operator believes they set it. `TC-CONF-15` additionally requires the refusal to be a
    declared type rather than a `ValueError` escaping `int()`.
    """
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise ConfigurationError(f"{key} must be a positive integer, got {type(raw).__name__}.")
    try:
        value = int(str(raw).strip())
    except ValueError:
        raise ConfigurationError(f"{key} must be a positive integer.") from None
    if value < 1:
        raise ConfigurationError(f"{key} must be at least 1, got {value}.")
    return value


# --- retention (FR-CONF-12, R4/R31) ----------------------------------------------------------

#: The recognized values for `cloud-hosted` retention routing. Two, because `TC-CONF-12` needs a
#: recognized value and an unrecognized one to differ, and because the design requires the
#: setting be *recorded* and refuses it *unset* — it does not mandate zero retention, which is
#: the operator's policy call. An unrecognized value is refused rather than passed through: the
#: cost of accepting a near-miss is a run proceeding in the belief that retention is off.
RETENTION_SETTINGS: tuple[str, ...] = ("provider-default", "zero-retention")
