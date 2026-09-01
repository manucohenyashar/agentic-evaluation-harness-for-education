"""The `edge-local` hardware profile and what it derives.

Cases: `TC-CONF-06` (`FR-CONF-06`, P1, decision table) and `TC-CONF-10` (`FR-CONF-10`, P2,
boundary), test plan §5.1. Rung 0.

**Which numbers carry design authority, and which do not.** `FR-CONF-10` states the prefix
ceilings — 2,000 for `unified-large`, 1,500 otherwise — as a recorded Assumption, so those are a
real oracle. `FR-CONF-06` names residency policy, concurrency ceiling and quantization target as
things the profile must *derive* but gives **no values** for them; issue #4 chose them. The
committed table below is therefore a golden reference for those three columns: it makes a change
deliberate and reviewable, and it is not evidence that the values are right.

What is asserted behaviourally rather than by literal is the part that matters more:
`resolve_run_config` **derives** from the table rather than hard-coding, proven by injecting a
different table and watching the result follow it. `NFR-CONF-03` and `TC-CONF-14` require exactly
that — residency and quantization as data, never a code path.
"""

from __future__ import annotations

import pytest

from aeh.conf import (
    HARDWARE_PROFILES,
    ConfigurationError,
    HardwarePolicy,
    hardware_policy_for,
    resolve_run_config,
)
from tests.support.conf_builders import SYNTHETIC_COHORT, edge_cfg, hosted_cfg

#: The decision table. `prefix_token_ceiling` is design-stated (`FR-CONF-10`); the other three
#: columns are issue #4's choice, pinned here so changing one is a review event.
_DECLARED_CELLS = {
    "unified-large": HardwarePolicy(
        residency_policy=("judge", "transcriber"),
        concurrency_ceiling=4,
        quantization_target="q4",
        prefix_token_ceiling=2000,
    ),
    "unified-small": HardwarePolicy(
        residency_policy=("judge",),
        concurrency_ceiling=2,
        quantization_target="q4",
        prefix_token_ceiling=1500,
    ),
    "discrete-gpu": HardwarePolicy(
        residency_policy=("judge",),
        concurrency_ceiling=3,
        quantization_target="q4",
        prefix_token_ceiling=1500,
    ),
}


# --- TC-CONF-06 -----------------------------------------------------------------------------


def test_tc_conf_06_the_table_holds_exactly_the_three_profiles_the_design_names():
    """`FR-CONF-06` names `unified-large`, `unified-small` and `discrete-gpu`. Set equality, not
    containment: a fourth profile nobody decided on is as much a defect as a missing one, and
    `HARNESS_HARDWARE_PROFILE` accepting it would bind a run to a policy no requirement covers."""
    assert set(HARDWARE_PROFILES) == {"unified-large", "unified-small", "discrete-gpu"}


@pytest.mark.parametrize("profile", sorted(_DECLARED_CELLS))
def test_tc_conf_06_each_profile_yields_its_declared_policy(profile):
    """TC-CONF-06 — "each profile yields its declared residency policy, concurrency ceiling and
    quantization target". Oracle (§5.1): exact value per cell.

    Read through `hardware_policy_for(config)` rather than out of the table directly, so the case
    covers the route a consumer actually takes: `RunConfig` has no residency field —
    `CT-CONF-C02` pins it at twelve — so `M-ORCH` deciding what may stay resident goes through
    this function.
    """
    config = resolve_run_config(edge_cfg(HARNESS_HARDWARE_PROFILE=profile), SYNTHETIC_COHORT)

    assert hardware_policy_for(config) == _DECLARED_CELLS[profile]
    assert config.hardware_profile == profile


@pytest.mark.parametrize("profile", sorted(_DECLARED_CELLS))
def test_tc_conf_06_the_derived_ceilings_reach_the_run_config(profile):
    """The derivation is only useful if it lands on the value consumers hold. A policy that is
    correct in the table and never projected onto the `RunConfig` fails nothing else here."""
    config = resolve_run_config(edge_cfg(HARNESS_HARDWARE_PROFILE=profile), SYNTHETIC_COHORT)
    declared = _DECLARED_CELLS[profile]

    assert config.concurrency_ceiling == declared.concurrency_ceiling
    assert config.prefix_token_ceiling == declared.prefix_token_ceiling


def test_tc_conf_06_an_absent_hardware_profile_raises_on_edge_local():
    """TC-CONF-06 — "absent raises `ConfigurationError`" (`FR-CONF-06` verbatim). There is no
    fallback profile: guessing one binds a run to a residency policy and a concurrency ceiling
    the operator never chose, on hardware that may not survive it."""
    cfg = edge_cfg()
    cfg.pop("HARNESS_HARDWARE_PROFILE")

    with pytest.raises(ConfigurationError) as caught:
        resolve_run_config(cfg, SYNTHETIC_COHORT)
    assert type(caught.value) is ConfigurationError


@pytest.mark.parametrize("unknown", ["unified-medium", "UNIFIED-LARGE", "", "cpu-only"])
def test_tc_conf_06_an_unrecognized_hardware_profile_raises(unknown):
    """The other half of the decision table's negative column. `UNIFIED-LARGE` is here for the
    same reason `EDGE-LOCAL` is in `TC-CONF-01`: a case-insensitive match would quietly accept a
    value the design does not define."""
    with pytest.raises(ConfigurationError):
        resolve_run_config(edge_cfg(HARNESS_HARDWARE_PROFILE=unknown), SYNTHETIC_COHORT)


def test_tc_conf_06_a_hosted_profile_carries_no_hardware_profile():
    """`CT-CONF-02`'s iff, other direction: `hardware_profile` is non-null **iff** the backend is
    `edge-local`. Residency policy is meaningless on a hosted backend — nothing is resident."""
    for profile in ("cloud-hosted", "dev-ci"):
        config = resolve_run_config(hosted_cfg(profile), SYNTHETIC_COHORT)
        assert config.hardware_profile is None
        assert hardware_policy_for(config) is None


def test_tc_conf_06_residency_and_quantization_are_data_the_resolver_reads_not_values_it_knows():
    """`NFR-CONF-03` / `TC-CONF-14`: "residency and quantization appear only as data".

    The literal assertions above cannot tell a table lookup from a hard-coded branch — both
    produce `4` for `unified-large`. This one can: inject a table whose cells are nothing like
    the defaults and assert the result follows it. A resolver carrying its own copy of the
    numbers, or a `sys.platform` branch, stays on the defaults and fails here.
    """
    injected = {
        "unified-large": HardwarePolicy(
            residency_policy=("judge", "transcriber", "extractor"),
            concurrency_ceiling=11,
            quantization_target="q8",
            prefix_token_ceiling=3333,
        )
    }

    config = resolve_run_config(
        edge_cfg(HARNESS_HARDWARE_PROFILE="unified-large", hardware_profiles=injected),
        SYNTHETIC_COHORT,
    )

    assert config.concurrency_ceiling == 11
    assert config.prefix_token_ceiling == 3333
    assert hardware_policy_for(config, injected).residency_policy == (
        "judge",
        "transcriber",
        "extractor",
    )
    assert hardware_policy_for(config, injected).quantization_target == "q8"
    # And the injection did not leak into the shipped table.
    assert HARDWARE_PROFILES["unified-large"] == _DECLARED_CELLS["unified-large"]


# --- TC-CONF-10 -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "profile,expected",
    [("unified-large", 2000), ("unified-small", 1500), ("discrete-gpu", 1500)],
)
def test_tc_conf_10_the_prefix_token_ceiling_is_2000_on_unified_large_and_1500_otherwise(
    profile, expected
):
    """TC-CONF-10 — `FR-CONF-10`'s recorded Assumption, and the only column of the hardware table
    the design puts a number on. `M-SETUP` budgets Stage A's prefix against this, so a wrong
    value here does not fail loudly — it silently changes what fits in the cached prefix."""
    config = resolve_run_config(edge_cfg(HARNESS_HARDWARE_PROFILE=profile), SYNTHETIC_COHORT)

    assert config.prefix_token_ceiling == expected


@pytest.mark.parametrize("injected_ceiling", [1, 1499, 1500, 2001, 8192])
def test_tc_conf_10_the_ceiling_is_read_from_injected_configuration_not_asserted_as_a_literal(
    injected_ceiling,
):
    """TC-CONF-10's actual oracle (§5.1): *"read from injected configuration rather than asserted
    as a literal (Q-04)"* — exact value against injected config.

    The point of Q-04 is that 1,500/2,000 is an Assumption the HLD never assigned per profile, so
    a suite that hard-codes them cements a guess. This case asserts the *mechanism* instead: the
    number a deployment supplies is the number the run uses. It stays green when the Assumption
    is revised, which is exactly what a case built on an open question should do.
    """
    injected = {
        "unified-large": HardwarePolicy(
            residency_policy=("judge",),
            concurrency_ceiling=4,
            quantization_target="q4",
            prefix_token_ceiling=injected_ceiling,
        )
    }

    config = resolve_run_config(
        edge_cfg(HARNESS_HARDWARE_PROFILE="unified-large", hardware_profiles=injected),
        SYNTHETIC_COHORT,
    )

    assert config.prefix_token_ceiling == injected_ceiling
