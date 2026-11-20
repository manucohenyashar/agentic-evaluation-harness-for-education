"""`TC-CONF-45` (issue #896, FR-CONF-38, CT-CONF-26) — precedence and domain of the four
aggregation knobs, and their Settings rows.

Statistical-validity test plan §3.5 (story T3). For each of `agg_auto_threshold_atomic`,
`agg_auto_threshold_holistic`, `agg_uncited_multiplier` and `agg_holistic_multiplier`:

- environment `0.7` with file `0.9` → 0.7, source "environment";
- file only → 0.9, "config file";
- neither → M-AGG's declared default, "default";
- `1.0` accepted; `0`, `1.0001`, `-0.1` and `"abc"` refused — each refusal names the key that
  supplied the value and the domain "(0, 1]" (asserted for the environment name and for the file
  key separately);
- Settings lists each with its value and source.

The configuration is composed the way every entry point composes it — `effective_config(file,
environ)`, environment over file — and read through `resolve_agg_knob_sources` (the Settings
reader) and `resolve_run_config` (what a run freezes). Settings is the console's own `config`
read (`console.config_read`), over a file and a patched environment.

**Isolation: rung 0** (pure resolution) and **rung 1** for the Settings read (the console's
read function, no server). The served Settings page itself is not driven here.
**Written ahead of implementation: no** — #865 (PR #928).

Markers. None (fast tier).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from aeh.conf import (
    AGG_FILE_KEYS,
    AGG_KEYS,
    CohortRef,
    ConfigurationError,
    effective_config,
    resolve_agg_knob_sources,
    resolve_run_config,
)
from aeh.console.config_read import config_read
from tests.support.conf_builders import edge_cfg

#: `(file key, environment name, M-AGG default)` — FR-AGG-22's 0.95 holistic multiplier.
KNOBS = tuple(zip(AGG_FILE_KEYS, AGG_KEYS, (0.80, 0.90, 0.80, 0.95)))
IDS = [file_key for file_key, _env, _default in KNOBS]
#: The `RunConfig.agg_knobs` attribute each key freezes into.
ATTRIBUTE = dict(zip(AGG_FILE_KEYS, ("auto_threshold_atomic", "auto_threshold_holistic",
                                     "uncited_multiplier", "holistic_multiplier")))
SYNTHETIC = CohortRef(cohort_id="cohort-tc-conf-45", consent_class="synthetic")


def _sources(file_cfg: dict, environ: dict) -> dict:
    composed = effective_config(file_cfg, environ)
    return {knob.key: (knob.value, knob.source) for knob in resolve_agg_knob_sources(composed)}


def _frozen(file_cfg: dict, environ: dict):
    return resolve_run_config(effective_config(edge_cfg(**file_cfg), environ), SYNTHETIC).agg_knobs


def test_tc_conf_45_the_four_keys_are_exactly_these():
    assert AGG_FILE_KEYS == ("agg_auto_threshold_atomic", "agg_auto_threshold_holistic",
                             "agg_uncited_multiplier", "agg_holistic_multiplier")
    assert AGG_KEYS == tuple(f"HARNESS_{key.upper()}" for key in AGG_FILE_KEYS)


@pytest.mark.parametrize("file_key, env_key, default", KNOBS, ids=IDS)
def test_tc_conf_45_environment_over_file_over_default(file_key, env_key, default):
    assert _sources({file_key: 0.9}, {env_key: "0.7"})[file_key] == (0.7, "environment")
    assert _sources({file_key: 0.9}, {})[file_key] == (0.9, "config file")
    assert _sources({}, {})[file_key] == (default, "default")
    # The other three keys are untouched by this one's settings.
    for other, _env, other_default in KNOBS:
        if other != file_key:
            assert _sources({file_key: 0.9}, {env_key: "0.7"})[other] == (
                other_default, "default"), other

    # What a run freezes follows the same order.
    assert getattr(_frozen({file_key: 0.9}, {env_key: "0.7"}), ATTRIBUTE[file_key]) == 0.7
    assert getattr(_frozen({file_key: 0.9}, {}), ATTRIBUTE[file_key]) == 0.9
    assert getattr(_frozen({}, {}), ATTRIBUTE[file_key]) == default


@pytest.mark.parametrize("file_key, env_key, _default", KNOBS, ids=IDS)
def test_tc_conf_45_one_is_inside_the_domain(file_key, env_key, _default):
    assert _sources({}, {env_key: "1.0"})[file_key] == (1.0, "environment")
    assert _sources({file_key: 1.0}, {})[file_key] == (1.0, "config file")


@pytest.mark.parametrize("file_key, env_key, _default", KNOBS, ids=IDS)
@pytest.mark.parametrize("bad", ["0", "1.0001", "-0.1", "abc"])
@pytest.mark.parametrize("via", ["environment", "config file"])
def test_tc_conf_45_out_of_domain_values_are_refused_naming_key_and_domain(
        file_key, env_key, _default, bad, via):
    if via == "environment":
        file_cfg, environ, named = {}, {env_key: bad}, env_key
    else:
        value = bad if bad == "abc" else float(bad)
        file_cfg, environ, named = {file_key: value}, {}, file_key
    with pytest.raises(ConfigurationError) as refused:
        _sources(file_cfg, environ)
    message = str(refused.value)
    assert named in message, f"the refusal does not name {named}: {message!r}"
    assert "(0, 1]" in message, f"the refusal does not name the domain: {message!r}"
    # The run path refuses it the same way: a run never starts on an out-of-domain knob.
    with pytest.raises(ConfigurationError, match=named):
        _frozen(file_cfg, environ)


def test_tc_conf_45_settings_lists_each_knob_with_its_value_and_source(monkeypatch):
    for key in AGG_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("HARNESS_PROFILE", raising=False)
    monkeypatch.setenv("HARNESS_AGG_AUTO_THRESHOLD_ATOMIC", "0.7")
    file_cfg = edge_cfg(agg_auto_threshold_atomic=0.9, agg_auto_threshold_holistic=0.85)
    app = SimpleNamespace(run_config=None, file_config=file_cfg)

    rows = {row["field"]: row for row in config_read(None, app, None)["settings"]}

    expected = {
        "agg_auto_threshold_atomic": "0.7 (from the environment)",
        "agg_auto_threshold_holistic": "0.85 (from the config file)",
        "agg_uncited_multiplier": "0.8 (the default)",
        "agg_holistic_multiplier": "0.95 (the default)",
    }
    assert {key: rows[key]["value"] for key in expected if key in rows} == expected, (
        {key: rows.get(key) for key in expected})
    for key in expected:
        assert rows[key]["label"] and key not in rows[key]["label"], rows[key]
