"""The two property cases over `M-CONF`.

Cases: `TC-CONF-15` (`FR-CONF-01`, `FR-CONF-06`, P1 — green) and `TC-CONF-16` (`FR-CONF-02`,
`NFR-CONF-04`, P0 — **written ahead**, issue #6), test plan §5.1. Rung 0, Property level.

This is the first story in the plan carrying Property-level cases, so it is where `hypothesis`
enters `requirements-dev.txt`; profiles `ci` and `nightly` are registered in `tests/conftest.py`
per §4.7's command table. §4.6 pins reproducibility, so the profiles are derandomized outside the
nightly fuzz campaign — a property case that fails only on some seeds is a P1 flake by §4.6, not
an interesting result.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

import aeh.conf
from aeh.conf import (
    BACKEND_PROFILES,
    RUN_CONFIG_FIELDS,
    BackendMismatchError,
    ConfigurationError,
    ConsentGateError,
    HardwarePolicy,
    ModelRef,
    RunConfig,
    UnresolvedModelRefError,
    resolve_run_config,
)
from tests.support.conf_builders import SYNTHETIC_COHORT, edge_cfg, hosted_cfg
from tests.support.impl import require_attr

pytestmark = pytest.mark.property

#: `CT-CONF-08`'s taxonomy, named as a tuple rather than caught as their common base. Catching
#: `RunConfigError` would let a fifth sibling added later pass this case silently, and the whole
#: point of the invariant is that the set is closed.
DECLARED_ERRORS = (
    ConfigurationError,
    UnresolvedModelRefError,
    BackendMismatchError,
    ConsentGateError,
)


# --- strategies -----------------------------------------------------------------------------

#: Build ids spanning both resolved forms and the ways each can be wrong. Every string here is
#: shape-valid (non-empty, no whitespace issues that `ModelRef.__post_init__` rejects), so
#: generation never raises — a strategy that threw would report as an error in the strategy and
#: assert nothing about `resolve_run_config`.
_BUILD_IDS = [
    "/models/llama-3.3-70b.gguf@sha256:aaaa",  # resolved, edge-weights
    "/models/qwen.safetensors@sha256:beef",  # resolved, edge-weights
    "/models/llama-3.3-70b.gguf",  # no weights hash
    "/models/llama:latest.gguf@sha256:aaaa",  # floating tag
    "meta-llama/llama-3.3-70b-instruct@2024-12-06",  # resolved, provider-pinned
    "meta-llama/llama-3.3-70b-instruct",  # bare slug
    "llama3.3:latest@2024-12-06",  # floating tag
    "Llama-3.3-70B",  # friendly name
    "x@sha256:",  # truncated pin
]

model_refs = st.builds(
    ModelRef,
    role=st.sampled_from(["judge", "transcriber", "extractor", "off_panel"]),
    provider=st.sampled_from(["ollama", "vllm-mlx", "openrouter", "fixture"]),
    build_id=st.sampled_from(_BUILD_IDS),
    quantization=st.sampled_from([None, "q4", "q8"]),
)

hardware_policies = st.builds(
    HardwarePolicy,
    residency_policy=st.lists(st.sampled_from(["judge", "transcriber"]), max_size=2).map(tuple),
    concurrency_ceiling=st.integers(min_value=1, max_value=64),
    quantization_target=st.sampled_from(["q4", "q8"]),
    prefix_token_ceiling=st.integers(min_value=1, max_value=8192),
)

#: Awkward strings, chosen rather than generated. `st.text()` would be the obvious move and is
#: the wrong one twice over: it loads hypothesis's unicode tables, which trips
#: `HealthCheck.too_slow` on a cold cache (found by running this suite with `.hypothesis`
#: cleared), and random codepoints are far less likely to find a config bug than the specific
#: shapes an operator actually types — a wrong case, a stray space, a near-miss value.
_AWKWARD_STRINGS = [
    "",
    " ",
    "local",
    "EDGE-LOCAL",
    " edge-local ",
    "edge_local",
    "edge-local\n",
    "cloud",
    "usd",
    "$",
    "0x10",
    "1e3",
    "NaN",
    "None",
    "null",
    "-0",
    "２",  # a full-width digit: int() accepts it, a human reading the config would not
]

#: Deliberately hostile: wrong types, wrong cases, boundary numbers, and the empty string, which
#: `FR-CONF-01` treats as a value rather than as absence.
_JUNK = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-5, max_value=5),
    st.floats(allow_nan=True, allow_infinity=True),
    st.sampled_from(_AWKWARD_STRINGS),
    st.sampled_from(["local", "EDGE-LOCAL", "edge-local", "cloud-hosted", "dev-ci", "USD"]),
    st.lists(st.integers(), max_size=2),
    st.dictionaries(st.sampled_from(["a", "b", "unified-large"]), st.integers(), max_size=2),
    st.decimals(allow_nan=True, allow_infinity=True, places=2),
)

_VALUE_BY_KEY = {
    "HARNESS_PROFILE": st.one_of(st.sampled_from(list(BACKEND_PROFILES)), _JUNK),
    "HARNESS_HARDWARE_PROFILE": st.one_of(
        st.sampled_from(["unified-large", "unified-small", "discrete-gpu"]), _JUNK
    ),
    "HARNESS_COST_CEILING": st.one_of(
        st.sampled_from(["0", "12.50", "-1", Decimal("0"), Decimal("3")]), _JUNK
    ),
    "HARNESS_COST_CURRENCY": st.one_of(st.sampled_from(["USD", "EUR"]), _JUNK),
    "HARNESS_CONCURRENCY": st.one_of(st.sampled_from(["1", "4", "0", "-2", 4]), _JUNK),
    "HARNESS_ALLOW_REMOTE_REAL_WORK": st.one_of(
        st.sampled_from(["true", "false", True, False]), _JUNK
    ),
    "panel": st.one_of(st.lists(model_refs, max_size=6).map(tuple), _JUNK),
    "transcriber": st.one_of(model_refs, _JUNK),
    "off_panel_checker": st.one_of(model_refs, _JUNK),
    "prompt_template_v": st.one_of(st.sampled_from(["v1", "conf-v1.0.0"]), _JUNK),
    "retention_setting": st.one_of(st.sampled_from(["zero-retention"]), _JUNK),
    "hardware_profiles": st.one_of(
        st.dictionaries(
            st.sampled_from(["unified-large", "unified-small", "discrete-gpu"]),
            hardware_policies,
            max_size=3,
        ),
        _JUNK,
    ),
}


#: Bases for the perturbation mode below. One per backend, each fully resolvable.
_VALID_BASES = [
    edge_cfg(),
    edge_cfg(HARNESS_HARDWARE_PROFILE="unified-small"),
    edge_cfg(HARNESS_HARDWARE_PROFILE="discrete-gpu", HARNESS_CONCURRENCY="2"),
    hosted_cfg("cloud-hosted"),
    hosted_cfg("dev-ci"),
]


@st.composite
def arbitrary_cfg(draw):
    """A configuration mapping, drawn in one of two modes.

    **Why two.** A purely random subset of keys almost never resolves — `HARNESS_PROFILE`,
    `panel`, `transcriber` and `prompt_template_v` all have to be simultaneously valid, and the
    refs have to be in the right form for the backend. Measured on the first version of this
    strategy, essentially every example was rejected in the first few lines of the function, so
    the invariant was only ever asserted over the *shallow* rejection path. A defect in cost
    parsing — the deepest branch, and the one handling the most caller-supplied types — was
    unreachable, and a mutation that made `Decimal` conversion raise an undeclared
    `AttributeError` went undetected.

    So half the draws start from a resolvable base and perturb **one** key, which is how an
    example gets deep enough to matter. `TC-CONF-15`'s invariant is about what escapes
    `resolve_run_config`, and most of what can escape it lives past the early guards.

    Subsets rather than always-all-keys in the first mode, because absence and a null value are
    different configurations and `FR-CONF-01` refuses both.
    """
    if draw(st.booleans()):
        keys = draw(st.lists(st.sampled_from(sorted(_VALUE_BY_KEY)), unique=True, max_size=12))
        return {key: draw(_VALUE_BY_KEY[key]) for key in keys}

    cfg = dict(draw(st.sampled_from(_VALID_BASES)))
    key = draw(st.sampled_from(sorted(_VALUE_BY_KEY)))
    if draw(st.booleans()):
        cfg.pop(key, None)
    else:
        cfg[key] = draw(_VALUE_BY_KEY[key])
    return cfg


# --- TC-CONF-15 -----------------------------------------------------------------------------


@given(cfg=arbitrary_cfg())
def test_tc_conf_15_resolution_returns_a_frozen_config_or_raises_a_declared_error(cfg):
    """TC-CONF-15 — the invariant: `resolve_run_config` either returns a frozen `RunConfig` or
    raises one of the four declared exception types; never any other exception, and never a
    partially built config.

    Oracle (§5.1): invariant. Not weakened to a type check — the issue says so explicitly.

    All three clauses are asserted, because each fails differently:

    * **never any other exception.** A `TypeError` from an unguarded `min()`, a `KeyError` from a
      missing config key, an `InvalidOperation` from `Decimal("abc")` — every one of these is a
      configuration problem reaching the caller wearing the wrong name, and `CT-CONF-08` promises
      a closed taxonomy that `M-ORCH` and `M-CONSOLE` can branch on.
    * **frozen.** Asserted by attempting an assignment, not by reading `__dataclass_params__`:
      `FR-CONF-02` names the behaviour, and `dataclasses.FrozenInstanceError` is an
      `AttributeError` rather than the `TypeError` the requirement specifies.
    * **never a partially built config.** Every field present, and both of `CT-CONF-02`'s iffs
      holding — a returned object with `backend_profile='cloud-hosted'` and no cost ceiling is
      "partially built" in the only sense that harms a consumer.
    """
    try:
        config = resolve_run_config(cfg, SYNTHETIC_COHORT)
    except DECLARED_ERRORS:
        return
    except Exception as exc:  # noqa: BLE001 — the assertion IS that this branch is unreachable
        raise AssertionError(
            f"undeclared {type(exc).__name__} escaped resolve_run_config: {exc}. "
            f"CT-CONF-08 names exactly four error types. cfg={cfg!r}"
        ) from exc

    assert isinstance(config, RunConfig)

    for field in RUN_CONFIG_FIELDS:
        assert hasattr(config, field), f"{field} missing — partially built config"

    with pytest.raises(TypeError):
        config.backend_profile = "dev-ci"

    edge = config.backend_profile == "edge-local"
    assert edge == (config.hardware_profile is not None)
    hosted = config.backend_profile in ("cloud-hosted", "dev-ci")
    assert hosted == (config.cost_ceiling is not None)
    assert hosted == (config.cost_currency is not None)
    assert len(config.panel) in (1, 3, 5)


@given(cfg=arbitrary_cfg())
def test_tc_conf_15_a_refused_resolution_writes_nothing_and_touches_no_socket(
    cfg, store_spy, network_guard
):
    """`CT-CONF-08`'s other half: all four errors are raised "before the `run` row is written …
    none leaves partial state — a failed resolution leaves nothing to clean up."

    Over generated input rather than the handful of hand-written negatives, because the
    interesting case is the failure that happens *late* — after a config is half assembled — and
    a fixed list of inputs is exactly the wrong tool for finding which failure that is.
    """
    try:
        resolve_run_config(cfg, SYNTHETIC_COHORT)
    except DECLARED_ERRORS:
        pass

    store_spy.assert_no_writes()
    network_guard.assert_no_network()


# --- TC-CONF-16 -----------------------------------------------------------------------------

_VALID_CFGS = st.sampled_from(
    [
        edge_cfg(),
        edge_cfg(HARNESS_HARDWARE_PROFILE="unified-small"),
        edge_cfg(HARNESS_HARDWARE_PROFILE="discrete-gpu", HARNESS_CONCURRENCY="1"),
        hosted_cfg("cloud-hosted"),
        hosted_cfg("cloud-hosted", HARNESS_COST_CEILING="0"),
        hosted_cfg("dev-ci"),
    ]
)


@given(cfg=_VALID_CFGS)
def test_tc_conf_16_rehydrating_a_persisted_config_reproduces_it_byte_identically(cfg):
    """TC-CONF-16 — round-trip invariant: `rehydrate_run_config(persist(c))` equals `c`
    byte-identically (`NFR-CONF-04`).

    Written ahead of its implementation and now green: issue #6 landed `rehydrate_run_config`
    and `to_persisted_dict`, so the `writtenahead` marker came off. The case is unchanged.

    Why P0: `NFR-CONF-04` exists so "resume cannot silently change the grader" (RISK-22). A run
    killed overnight and resumed at 3am must rebind to the panel that graded the first half of
    the cohort, or half the class is scored by one panel and half by another with nothing in the
    record saying so.

    The interface this case assumed — `to_persisted_dict()` produces the persisted form and
    `rehydrate_run_config` accepts it — is what #6 shipped. Design §3.1 types the parameter as
    `RunRow`; #6 made that the persisted mapping itself, so `_persist` below stayed a one-liner.
    """
    require_attr(RunConfig, "to_persisted_dict", issue="#6")
    rehydrate = require_attr(aeh.conf, "rehydrate_run_config", issue="#6")

    config = resolve_run_config(cfg, SYNTHETIC_COHORT)

    restored = rehydrate(_persist(config))

    # Field-for-field first: it names which field drifted when this fails.
    for field in RUN_CONFIG_FIELDS:
        assert getattr(restored, field) == getattr(config, field), f"{field} changed on resume"
    assert restored == config
    # "byte-identically" as the plan words it — the serialized forms match, not merely the
    # objects. A rehydrate that normalized a Decimal or reordered the panel would pass equality
    # on a type that compared loosely and still write a different row on the next save.
    assert _persist(restored) == _persist(config)


def _persist(config: RunConfig) -> object:
    """The persisted form, isolated so #6 can correct the assumption in one place."""
    return config.to_persisted_dict()
