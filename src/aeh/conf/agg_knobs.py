"""The four aggregation constants as per-run knobs (FR-CONF-38, FR-AGG-21, CT-CONF-26).

`agg_auto_threshold_atomic`, `agg_auto_threshold_holistic`, `agg_uncited_multiplier` and
`agg_holistic_multiplier` are plain profile keys, each overridden by its `HARNESS_AGG_*`
environment variable — not `HARNESS_KEYS` members, so that tuple stays six (`TC-CONF-C11`). The
value in force is, in order: the environment variable, then the config file key, then M-AGG's
declared constant (`aeh.agg.settings`). Every value lies in (0, 1]; anything else is refused at
start, naming the key that supplied it and the domain. The cap table stays code-declared (§10 Q3).

The resolved four are frozen into `RunConfig.agg_knobs`, recorded on the run row and read back on
resume, so a run aggregates every cell with the values it started with (FR-AGG-21). `AggKnobs`
carries the attribute names `aggregate`'s `config` argument reads, so the frozen value is passed
to it as is (CT-AGG-01: `aggregate` reads nothing else). It has no `caps` attribute on purpose.

Pure: the environment enters only through `effective_config`'s snapshot (`NFR-CONF-01`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import ConfigurationError
from .orch_knobs import KNOB_SOURCE_CONFIG_FILE, KNOB_SOURCE_DEFAULT, KNOB_SOURCE_ENVIRONMENT

#: The config file's plain keys, in the order Settings lists them.
AUTO_THRESHOLD_ATOMIC_FILE_KEY = "agg_auto_threshold_atomic"
AUTO_THRESHOLD_HOLISTIC_FILE_KEY = "agg_auto_threshold_holistic"
UNCITED_MULTIPLIER_FILE_KEY = "agg_uncited_multiplier"
HOLISTIC_MULTIPLIER_FILE_KEY = "agg_holistic_multiplier"
AGG_FILE_KEYS: tuple[str, ...] = (
    AUTO_THRESHOLD_ATOMIC_FILE_KEY,
    AUTO_THRESHOLD_HOLISTIC_FILE_KEY,
    UNCITED_MULTIPLIER_FILE_KEY,
    HOLISTIC_MULTIPLIER_FILE_KEY,
)

#: The environment names, one per file key (`HARNESS_` + the key, upper-cased).
AGG_KEYS: tuple[str, ...] = tuple(f"HARNESS_{key.upper()}" for key in AGG_FILE_KEYS)

#: The domain every knob is checked against, as the refusal names it.
AGG_KNOB_DOMAIN = "(0, 1]"

#: The `AggKnobs` attribute each file key fills — the names `aggregate`'s `config` reads.
_ATTRIBUTE_OF = {
    AUTO_THRESHOLD_ATOMIC_FILE_KEY: "auto_threshold_atomic",
    AUTO_THRESHOLD_HOLISTIC_FILE_KEY: "auto_threshold_holistic",
    UNCITED_MULTIPLIER_FILE_KEY: "uncited_multiplier",
    HOLISTIC_MULTIPLIER_FILE_KEY: "holistic_multiplier",
}

#: The teacher-facing name of each knob (Settings). No keys, no requirement ids (FR-UI-23).
AGG_KNOB_LABELS = {
    AUTO_THRESHOLD_ATOMIC_FILE_KEY: "Auto-accept bar, atomic criteria",
    AUTO_THRESHOLD_HOLISTIC_FILE_KEY: "Auto-accept bar, holistic criteria",
    UNCITED_MULTIPLIER_FILE_KEY: "Confidence factor when a grader cites no evidence",
    HOLISTIC_MULTIPLIER_FILE_KEY: "Confidence factor for holistic criteria",
}


@dataclass(frozen=True)
class AggKnobs:
    """The four aggregation constants one run uses, frozen at its start (FR-AGG-21)."""

    auto_threshold_atomic: float
    auto_threshold_holistic: float
    uncited_multiplier: float
    holistic_multiplier: float

    def __post_init__(self) -> None:
        for file_key, attribute in _ATTRIBUTE_OF.items():
            object.__setattr__(self, attribute, _in_domain(getattr(self, attribute), file_key))

    def to_record(self) -> dict[str, float]:
        """The four values under their file-key names, as the run row records them."""
        return {key: getattr(self, attribute) for key, attribute in _ATTRIBUTE_OF.items()}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "AggKnobs | None":
        """The frozen four from a recorded mapping, or `None` when the record carries none (a row
        written before FR-AGG-21). A partial or out-of-domain record is refused, never filled
        from today's defaults: a resumed run must aggregate with what it froze."""
        present = [key for key in AGG_FILE_KEYS if record.get(key) is not None]
        if not present:
            return None
        missing = [key for key in AGG_FILE_KEYS if key not in present]
        if missing:
            raise ConfigurationError(
                f"the run's recorded aggregation settings are incomplete: {', '.join(missing)} "
                "missing.")
        return cls(**{attribute: record[key] for key, attribute in _ATTRIBUTE_OF.items()})


@dataclass(frozen=True)
class ResolvedAggKnob:
    """One knob's value and where it came from, for Settings (FR-CONF-38)."""

    key: str
    label: str
    value: float
    source: str

    def text(self) -> str:
        """The value and its source in teacher words, e.g. *"0.95 (the default)"*."""
        return f"{_number_text(self.value)} ({_source_words(self.source)})"


def _number_text(value: float) -> str:
    return f"{Decimal(str(value)).normalize():f}"


def _source_words(source: str) -> str:
    if source == KNOB_SOURCE_ENVIRONMENT:
        return "from the environment"
    if source == KNOB_SOURCE_CONFIG_FILE:
        return "from the config file"
    return "the default"


def _in_domain(raw: Any, key: str) -> float:
    """A number in (0, 1], or a refusal naming the key and the domain. Never clamped."""
    refusal = f"{key} must be a number in {AGG_KNOB_DOMAIN}; it is refused, not clamped."
    if isinstance(raw, bool):
        raise ConfigurationError(refusal)
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        raise ConfigurationError(refusal) from None
    if not value.is_finite() or value <= 0 or value > 1:
        raise ConfigurationError(refusal)
    return float(value)


def _defaults() -> dict[str, float]:
    """M-AGG's declared constants — the code defaults. Imported here, not at module load, so
    M-CONF's import graph stays its own."""
    from aeh.agg.settings import (
        AGG_AUTO_THRESHOLD_ATOMIC,
        AGG_AUTO_THRESHOLD_HOLISTIC,
        AGG_HOLISTIC_MULTIPLIER,
        AGG_UNCITED_MULTIPLIER,
    )

    return {
        AUTO_THRESHOLD_ATOMIC_FILE_KEY: AGG_AUTO_THRESHOLD_ATOMIC,
        AUTO_THRESHOLD_HOLISTIC_FILE_KEY: AGG_AUTO_THRESHOLD_HOLISTIC,
        UNCITED_MULTIPLIER_FILE_KEY: AGG_UNCITED_MULTIPLIER,
        HOLISTIC_MULTIPLIER_FILE_KEY: AGG_HOLISTIC_MULTIPLIER,
    }


def resolve_agg_knob_sources(cfg: Mapping[str, Any] | None) -> tuple[ResolvedAggKnob, ...]:
    """Each of the four knobs with its value and source, environment > config file > default.
    A value that is not a number, or lies outside (0, 1], is refused naming the key that
    supplied it (`ConfigurationError`)."""
    composed: Mapping[str, Any] = cfg if isinstance(cfg, Mapping) else {}
    defaults = _defaults()
    resolved: list[ResolvedAggKnob] = []
    for file_key, env_key in zip(AGG_FILE_KEYS, AGG_KEYS):
        value, source = defaults[file_key], KNOB_SOURCE_DEFAULT
        for key, candidate_source in ((env_key, KNOB_SOURCE_ENVIRONMENT),
                                      (file_key, KNOB_SOURCE_CONFIG_FILE)):
            raw = composed.get(key)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                continue
            value, source = _in_domain(raw, key), candidate_source
            break
        resolved.append(ResolvedAggKnob(file_key, AGG_KNOB_LABELS[file_key], value, source))
    return tuple(resolved)


def resolve_agg_knobs(cfg: Mapping[str, Any] | None) -> AggKnobs:
    """The four values a run freezes (FR-CONF-38): environment > config file > default."""
    by_key = {knob.key: knob.value for knob in resolve_agg_knob_sources(cfg)}
    return AggKnobs(**{attribute: by_key[key] for key, attribute in _ATTRIBUTE_OF.items()})
