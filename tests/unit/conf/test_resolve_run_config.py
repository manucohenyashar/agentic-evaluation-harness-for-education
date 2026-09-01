"""`M-CONF` resolution — the four cases that decide whether a run has one grader.

Cases: `TC-CONF-01`, `TC-CONF-02`, `TC-CONF-03`, `TC-CONF-07` (test plan §5.1). Rung 0, pure.
Three are P0; `TC-CONF-07` is P1.

These cover `FR-CONF-01/02/03/07`, which issue #4 shipped, so they are **green**. That is the
correct state here and a red one is a defect in the implementation, not a written-ahead case —
the `writtenahead` marker is for `TC-CONF-09/12/16`, whose code belongs to #5 and #6.
"""

from __future__ import annotations

import pytest

from aeh.conf import (
    RUN_CONFIG_FIELDS,
    ConfigurationError,
    ModelRef,
    RunConfig,
    UnresolvedModelRefError,
    resolve_run_config,
)
from tests.support.conf_builders import (
    EDGE_JUDGE,
    EDGE_TRANSCRIBER,
    HOSTED_JUDGE,
    SYNTHETIC_COHORT,
    edge_cfg,
    hosted_cfg,
)

# --- TC-CONF-01 -----------------------------------------------------------------------------

_LEGAL_PROFILES = ["edge-local", "cloud-hosted", "dev-ci"]

#: The four the plan names: absent, `local`, `EDGE-LOCAL`, and the empty string. `_ABSENT` is a
#: sentinel rather than `None`, because "the key is missing" and "the key is present and null"
#: are different configurations and `FR-CONF-01` refuses both.
_ABSENT = object()
_ILLEGAL_PROFILES = [
    pytest.param(_ABSENT, id="absent"),
    pytest.param("local", id="local"),
    pytest.param("EDGE-LOCAL", id="EDGE-LOCAL_wrong_case"),
    pytest.param("", id="empty_string"),
]


@pytest.mark.parametrize("profile", _LEGAL_PROFILES)
def test_tc_conf_01_each_legal_backend_profile_resolves(profile):
    """TC-CONF-01, first half — the three legal values resolve.

    Asserted alongside the negative half below, because "raises for everything" would satisfy
    the negative half on its own and is the failure this pairing exists to catch.
    """
    cfg = edge_cfg() if profile == "edge-local" else hosted_cfg(profile)

    config = resolve_run_config(cfg, SYNTHETIC_COHORT)

    assert isinstance(config, RunConfig)
    assert config.backend_profile == profile


@pytest.mark.parametrize("profile", _ILLEGAL_PROFILES)
def test_tc_conf_01_an_absent_or_unrecognized_profile_raises_and_applies_no_default(profile):
    """TC-CONF-01, second half — the other four raise `ConfigurationError`, no default applied.

    Oracle (§5.1): exact exception type. `type(exc) is ConfigurationError` rather than
    `pytest.raises`'s `isinstance`, because `CT-CONF-08` names four exception types and a
    subclass slipping through would make every "exact exception type" oracle in this module
    unable to tell them apart.

    "No default is applied" is asserted positively: the call must not return at all. A resolver
    that fell back to `edge-local` would still raise for `local`, so only the success path
    discriminates — hence `pytest.fail` if a config comes back.
    """
    cfg = edge_cfg()
    if profile is _ABSENT:
        cfg.pop("HARNESS_PROFILE")
    else:
        cfg["HARNESS_PROFILE"] = profile

    with pytest.raises(ConfigurationError) as caught:
        config = resolve_run_config(cfg, SYNTHETIC_COHORT)
        pytest.fail(f"expected ConfigurationError; a default was applied: {config!r}")

    assert type(caught.value) is ConfigurationError


def test_tc_conf_01_a_wholly_empty_configuration_raises_rather_than_choosing_a_backend():
    """`CT-CONF-11`: "with **no** key set, assert resolution **raises** rather than selecting a
    backend. A silent default here selects a grader by accident." """
    with pytest.raises(ConfigurationError):
        resolve_run_config({}, SYNTHETIC_COHORT)


# --- TC-CONF-02 -----------------------------------------------------------------------------


@pytest.mark.parametrize("field", RUN_CONFIG_FIELDS)
def test_tc_conf_02_assignment_to_any_field_raises_type_error(field):
    """TC-CONF-02, first half — every assignment raises `TypeError` (`FR-CONF-02` verbatim).

    Parametrized over `RUN_CONFIG_FIELDS`, which is derived from the dataclass rather than
    written out, so a field added later is covered without editing this test.

    `TypeError` specifically, not "some exception": a plain `@dataclass(frozen=True)` raises
    `dataclasses.FrozenInstanceError`, which subclasses `AttributeError`. The requirement names
    `TypeError`, and consumers written from the requirement will catch that.
    """
    config = resolve_run_config(edge_cfg(), SYNTHETIC_COHORT)

    with pytest.raises(TypeError):
        setattr(config, field, None)

    # The value did not change on the way to raising.
    assert getattr(config, field) == getattr(
        resolve_run_config(edge_cfg(), SYNTHETIC_COHORT), field
    )


def test_tc_conf_02_the_config_is_complete_before_anything_is_written(store_spy, network_guard):
    """TC-CONF-02, second half — "the object is constructed before any `run` row write".

    **Rung caveat, stated rather than silently downgraded.** The plan's oracle is a call-order
    assertion over write ordering between `M-CONF` and the writer of the `run` row. That writer
    is `M-ORCH`, which does not exist yet, so the two-actor ordering assertion is a rung-3 case
    and is not achievable here.

    What *is* achievable at rung 0, and is the load-bearing half: a complete `RunConfig` exists
    after a call that made **zero** writes of any kind (`CT-CONF-09`), so any later `run` row
    write is necessarily after it. Asserted with the `StoreSpy` write-audit hook TS-00 built for
    this, plus the socket guard — a resolver that reached out to fetch a profile would satisfy
    the write assertion while breaking `CT-CONF-01`.
    """
    config = resolve_run_config(edge_cfg(), SYNTHETIC_COHORT)

    store_spy.assert_no_writes()
    network_guard.assert_no_network()

    # "Complete" asserted by name, not by truthiness: a field left as `None` that should carry a
    # value is exactly the partially-built config `TC-CONF-15`'s invariant forbids.
    for field in RUN_CONFIG_FIELDS:
        assert hasattr(config, field), f"{field} missing from the returned config"
    assert config.panel and config.transcriber and config.panel_build_ref


# --- TC-CONF-03 -----------------------------------------------------------------------------

_FRIENDLY_NAME = ModelRef("judge", "openrouter", "Llama 3.3 70B", None)
_EDGE_NO_HASH = ModelRef("judge", "ollama", "/models/llama-3.3-70b.gguf", "q4")
_BARE_SLUG = ModelRef("judge", "openrouter", "meta-llama/llama-3.3-70b-instruct", None)

#: The five inputs `TC-CONF-03` names, plus the pair that crosses a resolved ref against the
#: wrong backend. Columns: the ref, what `is_resolved()` must say, the backend to resolve under,
#: and whether resolution must succeed.
_REF_CASES = [
    pytest.param(_FRIENDLY_NAME, False, "cloud-hosted", False, id="friendly_name"),
    pytest.param(_EDGE_NO_HASH, False, "edge-local", False, id="gguf_path_no_weights_hash"),
    pytest.param(EDGE_JUDGE, True, "edge-local", True, id="path_plus_hash_plus_quantization"),
    pytest.param(_BARE_SLUG, False, "cloud-hosted", False, id="bare_slug_on_cloud_hosted"),
    pytest.param(HOSTED_JUDGE, True, "cloud-hosted", True, id="provider_pinned_slug"),
    # The crossing pair. Both refs ARE resolved build identities, and both are refused because
    # the backend requires the other form (`CT-CONF-C03`). This is the pair that separates the
    # two questions the case's wording runs together.
    pytest.param(HOSTED_JUDGE, True, "edge-local", False, id="pinned_slug_on_edge_local"),
    pytest.param(EDGE_JUDGE, True, "cloud-hosted", False, id="weights_path_on_cloud_hosted"),
]


@pytest.mark.parametrize("ref,is_resolved,backend,resolves", _REF_CASES)
def test_tc_conf_03_unresolved_refs_are_refused_and_is_resolved_agrees(
    ref, is_resolved, backend, resolves
):
    """TC-CONF-03 — a `model_ref` that is not a resolved build identity raises
    `UnresolvedModelRefError`, and `is_resolved()` agrees with the outcome in every case.

    **The case's wording runs two questions together, and this test asserts both columns rather
    than picking one.** `is_resolved()` takes no backend argument (design §3.1 Interfaces), so it
    can only answer *"is this a resolved build identity"* — by form. `CT-CONF-C03` then adds
    *"per backend what resolution means"*: a weights path for `edge-local`, a pinned slug
    otherwise. The last two rows are where those differ — a perfectly resolved provider-pinned
    slug that `edge-local` must still refuse.

    If "agrees with the outcome" was meant as strict biconditional agreement, those two rows are
    where it surfaces, which is why they are here rather than left to a reader's assumption.

    Oracle (§5.1): exact exception type.
    """
    assert ref.is_resolved() is is_resolved

    cfg = edge_cfg(panel=(ref,)) if backend == "edge-local" else hosted_cfg(backend, panel=(ref,))

    if resolves:
        config = resolve_run_config(cfg, SYNTHETIC_COHORT)
        assert config.panel == (ref,)
        return

    with pytest.raises(UnresolvedModelRefError) as caught:
        resolve_run_config(cfg, SYNTHETIC_COHORT)
    assert type(caught.value) is UnresolvedModelRefError


def test_tc_conf_03_every_reachable_ref_is_checked_not_just_the_panel():
    """`CT-CONF-03` says *every* `ModelRef` reachable from a `RunConfig`. A check that stopped at
    the panel would let an unresolved transcriber through — and the transcriber is what turns a
    scanned page into the text every judge then scores."""
    for position, cfg in (
        ("transcriber", edge_cfg(transcriber=ModelRef("transcriber", "ollama", "whisper", None))),
        ("off_panel_checker", edge_cfg(off_panel_checker=ModelRef("off_panel", "ollama", "qwen", None))),
    ):
        with pytest.raises(UnresolvedModelRefError, match=position):
            resolve_run_config(cfg, SYNTHETIC_COHORT)


# --- TC-CONF-07 -----------------------------------------------------------------------------


@pytest.mark.parametrize("profile", ["cloud-hosted", "dev-ci"])
@pytest.mark.parametrize("missing", ["HARNESS_COST_CEILING", "HARNESS_COST_CURRENCY"])
def test_tc_conf_07_a_hosted_profile_without_a_cost_ceiling_or_currency_is_refused(
    profile, missing
):
    """TC-CONF-07 — `FR-CONF-07`: both are required, on both hosted profiles.

    Crossed over profile as well as over field, because `dev-ci` is the one people assume is
    exempt: it is the CI backend, it looks internal, and it spends real money.
    """
    cfg = hosted_cfg(profile)
    cfg.pop(missing)

    with pytest.raises(ConfigurationError) as caught:
        resolve_run_config(cfg, SYNTHETIC_COHORT)
    assert type(caught.value) is ConfigurationError


@pytest.mark.parametrize("profile", ["cloud-hosted", "dev-ci"])
def test_tc_conf_07_a_zero_ceiling_is_accepted_as_a_spend_nothing_ceiling(profile):
    """TC-CONF-07 — "zero is accepted as a legitimate spend-nothing ceiling".

    The boundary that catches a truthiness check: `Decimal("0")` is falsy, so `if not ceiling:
    raise` passes every other row of this case and refuses the one configuration an operator
    reaches for when they want a dry run that cannot bill.
    """
    from decimal import Decimal

    config = resolve_run_config(hosted_cfg(profile, HARNESS_COST_CEILING="0"), SYNTHETIC_COHORT)

    assert config.cost_ceiling == Decimal("0")
    assert config.cost_ceiling is not None  # the distinction a falsy check erases


@pytest.mark.parametrize("profile", ["cloud-hosted", "dev-ci"])
@pytest.mark.parametrize("ceiling", ["-1", "-0.01"])
def test_tc_conf_07_a_negative_ceiling_is_refused(profile, ceiling):
    """TC-CONF-07 — "negative refuses". Paired with the zero case above: a `>= 0` check and a
    `> 0` check differ on exactly one value, and that value is the previous test."""
    with pytest.raises(ConfigurationError):
        resolve_run_config(hosted_cfg(profile, HARNESS_COST_CEILING=ceiling), SYNTHETIC_COHORT)


@pytest.mark.parametrize("profile", ["cloud-hosted", "dev-ci"])
def test_tc_conf_07_both_present_resolves_and_is_recorded_on_the_config(profile):
    """TC-CONF-07 — "both present" resolves, and the values reach the `RunConfig` rather than
    being validated and dropped."""
    from decimal import Decimal

    config = resolve_run_config(
        hosted_cfg(profile, HARNESS_COST_CEILING="7.25", HARNESS_COST_CURRENCY="EUR"),
        SYNTHETIC_COHORT,
    )

    assert config.cost_ceiling == Decimal("7.25")
    assert config.cost_currency == "EUR"


def test_tc_conf_07_an_edge_local_config_carries_no_cost_fields():
    """`CT-CONF-02`'s iff, the direction `TC-CONF-07` does not state: `cost_ceiling` and
    `cost_currency` are non-null **iff** the backend is hosted. Only asserting "required when
    hosted" lets a stray non-null through on `edge-local`, where there is no spend to cap."""
    config = resolve_run_config(edge_cfg(), SYNTHETIC_COHORT)

    assert config.cost_ceiling is None
    assert config.cost_currency is None
