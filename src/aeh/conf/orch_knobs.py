"""The two orchestration knobs a config file may set (FR-CONF-36, CT-CONF-25).

`orch_escalation_budget` (the share of results that may get a second opinion) and
`orch_random_arm_rate` (the random extra-grader sample) are plain profile keys — not `HARNESS_*`
names, so `HARNESS_KEYS` stays six (`TC-CONF-C11`). The value in force is, in order: the
environment variable, then the config file key, then the code default (0.30, 0.07). The two
surfaces have different names, so `effective_config`'s environment-wins merge cannot order them;
`resolve_orch_knobs` does, over the composed configuration, exactly as
`_resolve_confidence_threshold` does for the decision gate.

Pure: the environment enters only through `effective_config`'s snapshot (`NFR-CONF-01`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import ConfigurationError

#: The environment names (`M-ORCH`'s call-time knobs) and the config file's plain keys.
ESCALATION_BUDGET_ENV_KEY = "HARNESS_ORCH_ESCALATION_BUDGET"
RANDOM_ARM_RATE_ENV_KEY = "HARNESS_ORCH_RANDOM_ARM_RATE"
ESCALATION_BUDGET_FILE_KEY = "orch_escalation_budget"
RANDOM_ARM_RATE_FILE_KEY = "orch_random_arm_rate"

#: The code defaults (design §3.7 Configuration; `M-ORCH`'s `ORCH_ESCALATION_BUDGET` and
#: `ORCH_RANDOM_ARM_RATE` are these same numbers, read from here).
DEFAULT_ESCALATION_BUDGET = 0.30
DEFAULT_RANDOM_ARM_RATE = 0.07

#: Where a resolved value came from. The first two are the words `profile_source` uses.
KNOB_SOURCE_ENVIRONMENT = "environment"
KNOB_SOURCE_CONFIG_FILE = "config file"
KNOB_SOURCE_DEFAULT = "default"

#: The environment keys `effective_config` lifts so the composed configuration carries them.
ORCH_KEYS: tuple[str, ...] = (ESCALATION_BUDGET_ENV_KEY, RANDOM_ARM_RATE_ENV_KEY)


@dataclass(frozen=True)
class OrchKnobs:
    """The two resolved values and where each came from (`"environment"`, `"config file"` or
    `"default"`)."""

    escalation_budget: float
    escalation_budget_source: str
    random_arm_rate: float
    random_arm_rate_source: str

    def to_record(self) -> dict[str, float]:
        """The values as the run row's `provider_config` records them (`create_run`)."""
        return {
            ESCALATION_BUDGET_FILE_KEY: self.escalation_budget,
            RANDOM_ARM_RATE_FILE_KEY: self.random_arm_rate,
        }

    def budget_text(self) -> str:
        """The budget and its source in teacher words, e.g. *"100% (from the config file)"*."""
        return (f"{_percent(self.escalation_budget)} "
                f"({_source_words(self.escalation_budget_source)})")

    def sample_text(self) -> str:
        """The random-arm rate and its source in teacher words, e.g.
        *"off (from the config file)"*."""
        return f"{_percent(self.random_arm_rate)} ({_source_words(self.random_arm_rate_source)})"

    def banner_lines(self) -> tuple[str, str]:
        """The two start-up lines (FR-CONF-36), e.g.
        *"Second-opinion budget: 100% (from the config file)"*."""
        return (
            f"{BUDGET_LABEL}: {self.budget_text()}",
            f"{SAMPLE_LABEL}: {self.sample_text()}",
        )


#: The teacher-facing names of the two knobs (banner and Settings).
BUDGET_LABEL = "Second-opinion budget"
SAMPLE_LABEL = "Random extra-grader sample"


def _percent(value: float) -> str:
    """0 reads as "off"; anything else as a whole or decimal percentage."""
    if value == 0:
        return "off"
    percent = Decimal(str(value)) * 100
    return f"{percent.normalize():f}%"


def _source_words(source: str) -> str:
    if source == KNOB_SOURCE_ENVIRONMENT:
        return "from the environment"
    if source == KNOB_SOURCE_CONFIG_FILE:
        return "from the config file"
    return "the default"


def _unit_interval(raw: Any, key: str) -> float:
    """A number in [0, 1], or a refusal naming the key and the range. Never clamped."""
    refusal = f"{key} must be a number in [0, 1]; it is refused, not clamped."
    if isinstance(raw, bool):
        raise ConfigurationError(refusal)
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        raise ConfigurationError(refusal) from None
    if not value.is_finite() or value < 0 or value > 1:
        raise ConfigurationError(refusal)
    return float(value)


def _resolve_knob(cfg: Mapping[str, Any], env_key: str, file_key: str,
                  default: float) -> tuple[float, str]:
    for key, source in ((env_key, KNOB_SOURCE_ENVIRONMENT),
                        (file_key, KNOB_SOURCE_CONFIG_FILE)):
        raw = cfg.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        return _unit_interval(raw, key), source
    return default, KNOB_SOURCE_DEFAULT


def resolve_orch_knobs(cfg: Mapping[str, Any] | None) -> OrchKnobs:
    """Resolve both knobs from a composed configuration (`effective_config`'s output, or a
    profile section of a file): environment > config file > default. A value that is not a
    number, or lies outside [0, 1], is refused naming its key (`ConfigurationError`), never
    clamped."""
    composed: Mapping[str, Any] = cfg if isinstance(cfg, Mapping) else {}
    budget, budget_source = _resolve_knob(
        composed, ESCALATION_BUDGET_ENV_KEY, ESCALATION_BUDGET_FILE_KEY,
        DEFAULT_ESCALATION_BUDGET)
    rate, rate_source = _resolve_knob(
        composed, RANDOM_ARM_RATE_ENV_KEY, RANDOM_ARM_RATE_FILE_KEY, DEFAULT_RANDOM_ARM_RATE)
    return OrchKnobs(budget, budget_source, rate, rate_source)
