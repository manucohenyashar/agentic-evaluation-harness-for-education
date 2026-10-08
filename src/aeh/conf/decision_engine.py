"""`DecisionEngine`: the decision engine a run is frozen to, with its defaults and bounds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from .errors import ConfigurationError
from .frozen import _typeerror_on_mutation
from .model_ref import ModelRef, _ref_from_dict, _ref_to_dict, _require_model_ref
from .panel import _build_identity, _FIELD_SEP


# --- the renderable grader identity (FR-CONF-09) --------------------------------------------

#: What `quantization` says when the run cannot state one. A hosted `ModelRef` carries
#: `quantization=None` because the provider owns it — but `profile_summary()` is rendered on
#: **every view showing a grade** (`FR-CONSOLE-09`, `CT-CONSOLE-10`), and an empty cell there
#: reads as "unknown" rather than "not applicable". Those are different claims to a teacher
#: asking what graded their student, so the summary says which one it means.
#:
#: **A constraint this places on rehydration, honoured:** `rehydrate_run_config` must not reconstruct
#: `ModelRef.quantization` out of a `ProfileSummary`: on a hosted run `None` would come back as
#: `"provider-managed"`, and `NFR-CONF-04`'s byte-identical round-trip would break. The summary
#: is a rendering of the config, never a source for rebuilding it. It also never reaches
#: `panel_build_ref`, which encodes `ref.quantization or ''` directly.
PROVIDER_MANAGED = "provider-managed"


# --- the decision engine (Jev design delta §3.2, FR-CONF-17…26) -----------------------------------

#: `HARNESS_DECISION_ENGINE`'s domain (FR-CONF-18). Closed: anything else is refused.
DECISION_ENGINES: tuple[str, ...] = ("jev", "off")


#: FR-CONF-29 / CT-CONF-19 v2.2 (ADR-37): what an unset `HARNESS_DECISION_ENGINE` resolves to.
#: A function of the declared profile, never of the hardware. The cloud profiles bind
#: `openrouter-jev` and need no local model; `edge-local` would need a co-resident decision model
#: whose residency the operator must check (FR-CONF-28), so it stays off until asked for.
DEFAULT_DECISION_ENGINE_BY_PROFILE: Mapping[str, str] = MappingProxyType({
    "edge-local": "off",
    "cloud-hosted": "jev",
    "dev-ci": "jev",
})


def decision_engine_setting(cfg: Mapping[str, Any], backend_profile: str) -> Any:
    """The `HARNESS_DECISION_ENGINE` value in force for `cfg`: the explicit setting, or the
    profile's default when the key is absent (FR-CONF-29). Only absence takes the default; an
    explicit empty or unknown value comes back as is for the caller to refuse. Shared by the
    resolver and the resume comparison so the two never disagree about an unset key."""
    raw = cfg.get("HARNESS_DECISION_ENGINE")
    return DEFAULT_DECISION_ENGINE_BY_PROFILE[backend_profile] if raw is None else raw


#: FR-CONF-19: the decision provider each backend binds, first entry the default.
DECISION_PROVIDERS_BY_PROFILE: Mapping[str, tuple[str, ...]] = MappingProxyType({
    # FR-CONF-27: `openjev-small` is opt-in, never the default and never substituted.
    "edge-local": ("openjev", "openjev-small"),
    "cloud-hosted": ("openrouter-jev",),
    "dev-ci": ("openrouter-jev",),
})


#: The hermetic double, accepted on any profile only under the test tier (HARNESS_FIXTURE_DIR).
FIXTURE_DECISION_PROVIDER = "fixture"


#: The profiles whose decision provider is the remote hosted Jev build through the TypeSafe SDK
#: path (FR-PROV-16) — the profiles the live acceptance drives (`FR-CONFORM-17`, #618). Derived
#: from `DECISION_PROVIDERS_BY_PROFILE` so a new binding needs no second edit.
HOSTED_JEV_PROFILES: frozenset[str] = frozenset(
    profile for profile, providers in DECISION_PROVIDERS_BY_PROFILE.items()
    if "openrouter-jev" in providers
)


DECISION_PLACEMENTS: tuple[str, ...] = ("shared", "cpu")


#: FR-CONF-21 defaults. The threshold default is per provider (design 1.7.1): OpenJevSmall's
#: probabilities are uncalibrated entailment, so it starts stricter. An explicit value wins.
#: Strings, not `Decimal`s: resolution reads only immutable module state (TC-CONF-13).
DEFAULT_CONFIDENCE_THRESHOLD = "0.80"


PROVIDER_DEFAULT_THRESHOLDS: Mapping[str, str] = MappingProxyType({"openjev-small": "0.85"})


#: FR-CONF-32: the threshold's two configuration surfaces. The environment knob beats the config
#: file key, which beats the provider default. The file key is a flat key in the profile's section
#: (`[profiles.<name>]`); the file has no separate engine table.
CONFIDENCE_THRESHOLD_ENV_KEY = "HARNESS_JEV_CONFIDENCE_THRESHOLD"


CONFIDENCE_THRESHOLD_FILE_KEY = "decision_confidence_threshold"


#: The threshold's domain, [0.50, 1.00) (FR-CONF-21/32).
CONFIDENCE_THRESHOLD_LOW = "0.50"


CONFIDENCE_THRESHOLD_HIGH = "1.00"


DEFAULT_CITE_THRESHOLD = "0.50"


DEFAULT_MAX_CITATION_QUESTIONS = 16


DEFAULT_TOKEN_BYTES_RATIO = 3


def _decimal_knob(raw: Any, key: str, default: Decimal, low: Decimal, high: Decimal,
                  *, high_inclusive: bool, low_inclusive: bool = True) -> Decimal:
    """Read a decimal setting that is fixed when the configuration is resolved. A value outside its
    range is refused, never clamped."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    if isinstance(raw, bool):
        raise ConfigurationError(f"{key} must be a decimal number, got a boolean.")
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        raise ConfigurationError(f"{key} must be a decimal number, got {raw!r}.") from None
    if not value.is_finite():
        raise ConfigurationError(f"{key} must be a finite decimal number, got {raw!r}.")
    below = value < low if low_inclusive else value <= low
    above = value > high if high_inclusive else value >= high
    if below or above:
        lo, hi = ("[" if low_inclusive else "("), ("]" if high_inclusive else ")")
        raise ConfigurationError(f"{key} must lie in {lo}{low}, {high}{hi}, got {raw!r}; it is refused, not clamped.")
    return value


def _bounded_int(raw: Any, key: str, default: int, low: int, high: int) -> int:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    if isinstance(raw, bool):
        raise ConfigurationError(f"{key} must be an integer, got a boolean.")
    try:
        value = int(str(raw).strip())
    except ValueError:
        raise ConfigurationError(f"{key} must be an integer, got {raw!r}.") from None
    if not low <= value <= high:
        raise ConfigurationError(f"{key} must lie in {low}…{high}, got {value}; it is refused, not clamped.")
    return value


def _canonical_decimal(value: Decimal) -> str:
    """One spelling per number, so `0.8`, `0.80` and `Decimal("0.800")` give the same work identity
    (FR-CONF-22): trailing zeros removed, never scientific notation."""
    text = format(value.normalize(), "f")
    return text


@_typeerror_on_mutation
@dataclass(frozen=True)
class DecisionEngine:
    """The decision engine a run is frozen to (FR-CONF-17): the model and the four values that
    decide which verdict counts. All are fixed when the configuration is resolved and never re-read
    (CT-CONF-18)."""

    model: ModelRef
    confidence_threshold: Decimal
    cite_threshold: Decimal
    max_citation_questions: int
    token_bytes_ratio: int

    def __post_init__(self) -> None:
        _require_model_ref(self.model, "decision_engine.model", "decision")
        _decimal_knob(self.confidence_threshold, "confidence_threshold", Decimal(DEFAULT_CONFIDENCE_THRESHOLD),
                      Decimal(CONFIDENCE_THRESHOLD_LOW), Decimal(CONFIDENCE_THRESHOLD_HIGH), high_inclusive=False)
        _decimal_knob(self.cite_threshold, "cite_threshold", Decimal(DEFAULT_CITE_THRESHOLD),
                      Decimal("0"), Decimal("1"), high_inclusive=False, low_inclusive=False)
        for name, value in (("confidence_threshold", self.confidence_threshold),
                            ("cite_threshold", self.cite_threshold)):
            if not isinstance(value, Decimal):
                raise ConfigurationError(f"DecisionEngine.{name} must be a Decimal.")
        _bounded_int(self.max_citation_questions, "max_citation_questions", 16, 1, 26)
        _bounded_int(self.token_bytes_ratio, "token_bytes_ratio", 3, 1, 8)
        for name in ("max_citation_questions", "token_bytes_ratio"):
            if isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), int):
                raise ConfigurationError(f"DecisionEngine.{name} must be an integer.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": _ref_to_dict(self.model),
            "confidence_threshold": _canonical_decimal(self.confidence_threshold),
            "cite_threshold": _canonical_decimal(self.cite_threshold),
            "max_citation_questions": self.max_citation_questions,
            "token_bytes_ratio": self.token_bytes_ratio,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "DecisionEngine":
        if not isinstance(raw, Mapping):
            raise ConfigurationError("persisted decision_engine must be a mapping.")
        try:
            return cls(
                model=_ref_from_dict(raw.get("model"), "decision_engine.model"),
                confidence_threshold=Decimal(str(raw["confidence_threshold"])),
                cite_threshold=Decimal(str(raw["cite_threshold"])),
                max_citation_questions=raw["max_citation_questions"],
                token_bytes_ratio=raw["token_bytes_ratio"],
            )
        except (KeyError, InvalidOperation) as exc:
            raise ConfigurationError(f"persisted decision_engine is incomplete or malformed: {exc}") from None

    def identity(self) -> str:
        """The encoding of this engine that `compute_panel_build_ref` includes in its hash
        (FR-CONF-22)."""
        return _FIELD_SEP.join((_build_identity(self.model), _canonical_decimal(self.confidence_threshold),
                                _canonical_decimal(self.cite_threshold), str(self.max_citation_questions),
                                str(self.token_bytes_ratio)))
