"""TC-CONF-40 (issue #818) — the two orchestration knobs resolve environment > config file >
default, and an out-of-range or non-numeric value is refused, never clamped.

Console-clarity test plan §3.1 (story T5), FR-CONF-36, CT-CONF-25. A decision table over
{env set / unset} × {file key set / unset}, run for each knob:

| Row | Environment | File | Expected |
|---|---|---|---|
| (a) | 0.5 | 1.0 | 0.5, "environment" |
| (b) | unset | 1.0 | 1.0, "config file" |
| (c) | unset | unset | 0.30 (budget) / 0.07 (rate), "default" |
| (d) | unset | 1.5 | refused, naming the key and "[0, 1]" |
| (e) | unset | "abc" | refused |
| (f) | unset | rate 0 | 0, "config file" (boundary: a falsy zero must not fall to the default) |
| (g) | unset | budget 1.0 | 1.0, "config file" (boundary) |

The composition goes through `effective_config(file, environ=...)`, the path every entry point
uses, with an explicit environment mapping: that exercises the `ORCH_KEYS` lift and keeps the
autouse `random_arm_deterministic` pin (which sets the real process environment) out of the
table. The file is a multi-profile document with the keys in its `dev-ci` section, as the
shipped files carry them. Rung 0.

Markers. `contract` (CT-CONF-25's clause suite).
"""

from __future__ import annotations

import pytest

from aeh.conf import ConfigurationError, effective_config, resolve_orch_knobs
from aeh.conf.orch_knobs import (
    ESCALATION_BUDGET_ENV_KEY,
    ESCALATION_BUDGET_FILE_KEY,
    RANDOM_ARM_RATE_ENV_KEY,
    RANDOM_ARM_RATE_FILE_KEY,
)

pytestmark = pytest.mark.contract

# (env name, file key, the attribute pair on OrchKnobs, the code default)
KNOBS = {
    "budget": (ESCALATION_BUDGET_ENV_KEY, ESCALATION_BUDGET_FILE_KEY,
               ("escalation_budget", "escalation_budget_source"), 0.30),
    "rate": (RANDOM_ARM_RATE_ENV_KEY, RANDOM_ARM_RATE_FILE_KEY,
             ("random_arm_rate", "random_arm_rate_source"), 0.07),
}
OTHER = {"budget": "rate", "rate": "budget"}


def _file(**section):
    return {"HARNESS_PROFILE": "dev-ci", "profiles": {"dev-ci": {"HARNESS_COST_CEILING": 5,
                                                                  **section}}}


def _resolve(file_cfg, environ):
    return resolve_orch_knobs(effective_config(file_cfg, environ=environ))


def _pair(knobs, name):
    value_attr, source_attr = KNOBS[name][2]
    return getattr(knobs, value_attr), getattr(knobs, source_attr)


@pytest.mark.parametrize("knob", sorted(KNOBS))
def test_tc_conf_40_a_environment_wins_over_the_file(knob):
    env_key, file_key, _attrs, default = KNOBS[knob]
    knobs = _resolve(_file(**{file_key: 1.0}), {env_key: "0.5"})
    assert _pair(knobs, knob) == (0.5, "environment")
    # The other knob, set nowhere, is untouched by this one's precedence.
    assert _pair(knobs, OTHER[knob]) == (KNOBS[OTHER[knob]][3], "default")


@pytest.mark.parametrize("knob", sorted(KNOBS))
def test_tc_conf_40_b_the_file_wins_over_the_default(knob):
    _env_key, file_key, _attrs, _default = KNOBS[knob]
    knobs = _resolve(_file(**{file_key: 1.0}), {})
    assert _pair(knobs, knob) == (1.0, "config file")


def test_tc_conf_40_c_neither_set_gives_the_defaults():
    knobs = _resolve(_file(), {})
    assert _pair(knobs, "budget") == (0.30, "default")
    assert _pair(knobs, "rate") == (0.07, "default")


@pytest.mark.parametrize("knob", sorted(KNOBS))
def test_tc_conf_40_d_out_of_range_is_refused_naming_key_and_range(knob):
    _env_key, file_key, _attrs, _default = KNOBS[knob]
    with pytest.raises(ConfigurationError) as refused:
        _resolve(_file(**{file_key: 1.5}), {})
    message = str(refused.value)
    assert message == f"{file_key} must be a number in [0, 1]; it is refused, not clamped.", (
        message)


@pytest.mark.parametrize("knob", sorted(KNOBS))
def test_tc_conf_40_e_a_non_number_is_refused(knob):
    _env_key, file_key, _attrs, _default = KNOBS[knob]
    with pytest.raises(ConfigurationError) as refused:
        _resolve(_file(**{file_key: "abc"}), {})
    assert file_key in str(refused.value) and "[0, 1]" in str(refused.value)


def test_tc_conf_40_f_a_zero_rate_in_the_file_is_zero_not_the_default():
    knobs = _resolve(_file(**{RANDOM_ARM_RATE_FILE_KEY: 0}), {})
    assert _pair(knobs, "rate") == (0, "config file")


def test_tc_conf_40_g_a_budget_of_one_in_the_file_is_one():
    knobs = _resolve(_file(**{ESCALATION_BUDGET_FILE_KEY: 1.0}), {})
    assert _pair(knobs, "budget") == (1.0, "config file")
