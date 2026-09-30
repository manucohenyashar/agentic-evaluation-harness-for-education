"""Edge hardware profiles, and the policy (concurrency, token ceiling) each one implies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .errors import ConfigurationError
from .frozen import _typeerror_on_mutation
from .decision_engine import DECISION_PLACEMENTS
from .run_config import RunConfig


@_typeerror_on_mutation
@dataclass(frozen=True)
class HardwarePolicy:
    """The settings an `edge-local` hardware profile implies (FR-CONF-06).

    Data, never a code path: `NFR-CONF-03` and `TC-CONF-14` both forbid a `sys.platform` branch
    or a platform-conditional import, so residency and quantization exist only as values in
    `HARDWARE_PROFILES`.

    `residency_policy` is the set of roles permitted resident concurrently. It has no home on
    `RunConfig` — `CT-CONF-C02` asserts **exact set equality** over that type's 12 fields — so a
    consumer reads it from the table via `hardware_policy_for`.
    """

    residency_policy: tuple[str, ...]
    concurrency_ceiling: int
    quantization_target: str
    prefix_token_ceiling: int
    #: Jev design delta FR-CONF-23 (as amended): which decision providers may run on this
    #: hardware, and where — `"shared"` (co-resident with the judge) or `"cpu"` (system RAM, so
    #: the judge keeps the accelerator). A provider absent here is refused on this profile.
    #: Defaulted empty so a caller-supplied policy that predates the field admits no engine.
    #: `compare=False`: not one of FR-CONF-06's policy cells, and a mapping would make the frozen
    #: dataclass unhashable.
    decision_coresident: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}), compare=False)

    def __post_init__(self) -> None:
        """Check field types. The caller supplies this through `cfg["hardware_profiles"]`, and a
        string where a number belongs would otherwise escape `resolve_run_config` as a bare
        `TypeError`, which TC-CONF-15 forbids."""
        if not isinstance(self.residency_policy, tuple) or not all(
            isinstance(role, str) and role for role in self.residency_policy
        ):
            raise ConfigurationError(
                "HardwarePolicy.residency_policy must be a tuple of non-empty role names."
            )
        for name in ("concurrency_ceiling", "prefix_token_ceiling"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ConfigurationError(
                    f"HardwarePolicy.{name} must be an integer of at least 1, got "
                    f"{type(value).__name__}."
                )
        if not isinstance(self.quantization_target, str) or not self.quantization_target.strip():
            raise ConfigurationError(
                "HardwarePolicy.quantization_target must be a non-empty string."
            )
        if not isinstance(self.decision_coresident, Mapping) or any(
            not isinstance(k, str) or v not in DECISION_PLACEMENTS
            for k, v in self.decision_coresident.items()
        ):
            raise ConfigurationError(
                f"HardwarePolicy.decision_coresident must map provider names to one of "
                f"{DECISION_PLACEMENTS}."
            )
        object.__setattr__(self, "decision_coresident", MappingProxyType(dict(self.decision_coresident)))


# --- the hardware table --------------------------------------------------------------------

#: `FR-CONF-06`'s derivation, as data. Public because `TC-CONF-06`'s oracle is "exact value per
#: cell" and `RunConfig` carries no residency field to read it from. Override per-run through
#: `cfg["hardware_profiles"]` (`CLAUDE.md` code convention 3: the production value is the
#: default, the knob exists so another environment need not edit code).
#:
#: Prefix ceilings are design §3.1's recorded Assumption — the HLD gives "on the order of 1,500
#: to 2,000" without a per-profile assignment. Issue #5 owns `FR-CONF-10` and the env-gated knob.
#: A `MappingProxyType`, not a `dict`: it is exported *and* read as `resolve_run_config`'s
#: default table, so a mutable one would make resolution a function of process state —
#: `HARDWARE_PROFILES["unified-large"] = ...` between two calls would return two different
#: `RunConfig`s for identical inputs, which is exactly what `CT-CONF-05` and `NFR-CONF-01`
#: forbid. `TC-CONF-C05` perturbs the *environment* and would not catch it.
HARDWARE_PROFILES: Mapping[str, HardwarePolicy] = MappingProxyType({
    "unified-large": HardwarePolicy(
        residency_policy=("judge", "transcriber"),
        concurrency_ceiling=4,
        quantization_target="q4",
        prefix_token_ceiling=2000,
        # FR-CONF-28 (Assumption, pending NFR-SYS-16): per-engine placement. A provider absent
        # from a profile's map is refused, and the refusal names what the map admits.
        decision_coresident=MappingProxyType({"openjev": "shared", "openjev-small": "shared"}),
    ),
    "unified-small": HardwarePolicy(
        residency_policy=("judge",),
        concurrency_ceiling=2,
        quantization_target="q4",
        prefix_token_ceiling=1500,
        decision_coresident=MappingProxyType({"openjev-small": "shared"}),
    ),
    "discrete-gpu": HardwarePolicy(
        residency_policy=("judge",),
        concurrency_ceiling=3,
        quantization_target="q4",
        prefix_token_ceiling=1500,
        # HLD §8.1's one model in VRAM holds: the decision model runs from system RAM.
        decision_coresident=MappingProxyType({"openjev-small": "cpu"}),
    ),
})


#: Used only when `backend_profile` is `cloud-hosted` or `dev-ci`, where no `hardware_profile`
#: exists to derive from and `HARNESS_CONCURRENCY` was not supplied. A default is safe here:
#: `CT-CONF-11` forbids a silent default that *selects a backend*, which only `HARNESS_PROFILE`
#: does.
DEFAULT_HOSTED_CONCURRENCY = 8


DEFAULT_HOSTED_PREFIX_TOKEN_CEILING = 1500


def hardware_policy_for(
    config: RunConfig,
    table: Mapping[str, HardwarePolicy] = HARDWARE_PROFILES,
) -> HardwarePolicy | None:
    """The declared hardware policy behind a resolved configuration, or None for a hosted backend.

    Declared, not effective, and the distinction is load-bearing: `TC-CONF-06`'s oracle is
    "exact value per cell", so this must return the table's row unchanged. The *effective*
    concurrency for a run is `RunConfig.concurrency_ceiling`, which `HARNESS_CONCURRENCY` may
    have lowered but can never raise (see `_resolve_concurrency`).

    **Pass the same `table` the config was resolved against.** `RunConfig` carries no reference
    to it — `CT-CONF-C02` pins the field set at twelve — so a config resolved with a
    `cfg["hardware_profiles"]` override and read back through the default table gets a row that
    was never applied, or `None` for a profile name the default table has never heard of.
    `config.concurrency_ceiling <= policy.concurrency_ceiling` holds when, and only when, the
    two tables agree.

    Reads the table; takes no argument that could rebind the run.
    """
    if config.hardware_profile is None:
        return None
    return table.get(config.hardware_profile)
