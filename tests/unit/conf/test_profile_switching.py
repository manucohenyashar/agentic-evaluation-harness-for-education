"""`TS-103` (issue #397) — switching harness profiles by environment variable, the rung-0 half.

Gap-fix test plan §5.9:

- `TC-CONF-20` (`FR-CONF-13`): `select_profile_config(F-PROFILES, p)` yields the shared keys plus
  exactly `p`'s section, `HARNESS_PROFILE == p`; an unknown profile raises naming it and the
  sections present; a file with no `profiles` table comes back unchanged; the function is pure.
- `TC-CONF-21` (`FR-CONF-14`): `effective_config(F-PROFILES, environ=E)` over the seven-row
  matrix, then `resolve_run_config`; and a conflicting `os.environ` has no effect once `environ`
  is passed.

**Written ahead of implementation: yes** (issue #397), but #352 landed the `M-CONF` functions
first, so these cases are green. The console variant of `TC-CONF-21` and the rung-3 cases need
#366 and #365 and live in `tests/integration/conf/test_profile_switch_entry_points.py`.
"""

from __future__ import annotations

import copy

import pytest

from aeh.conf import (
    ConfigurationError,
    effective_config,
    resolve_run_config,
    select_profile_config,
)
from tests.support.conf_builders import SYNTHETIC_COHORT, default_retention_setting
from tests.support.profile_switching import (
    PROFILE_NAMES,
    SHARED_TEMPLATE,
    clear_profile_environment,
    f_profiles,
)


# --- TC-CONF-20 — one section per profile, nothing from another -------------------------------


@pytest.mark.parametrize("profile", PROFILE_NAMES)
def test_tc_conf_20_each_profile_yields_shared_keys_plus_exactly_its_section(profile):
    """`TC-CONF-20` — exact dict equality: shared keys, that section's keys, `HARNESS_PROFILE`,
    and no key that only another section declares (for example no `retention_setting` under
    `edge-local`)."""
    file_cfg = f_profiles()
    section = file_cfg["profiles"][profile]

    selected = select_profile_config(file_cfg, profile)

    assert selected == {
        "prompt_template_v": SHARED_TEMPLATE,
        **section,
        "HARNESS_PROFILE": profile,
    }
    others = {
        key
        for name, other in file_cfg["profiles"].items()
        if name != profile
        for key in other
    } - set(section)
    assert not others & set(selected), f"{profile} leaked {sorted(others & set(selected))}"
    assert "profiles" not in selected


def test_tc_conf_20_an_unknown_profile_names_itself_and_the_sections_present():
    """`TC-CONF-20` — `gpu-farm` raises `ConfigurationError` naming `gpu-farm` and all three
    sections, so the operator sees both what they asked for and what exists."""
    with pytest.raises(ConfigurationError) as refusal:
        select_profile_config(f_profiles(), "gpu-farm")
    message = str(refusal.value)
    assert "gpu-farm" in message
    for name in PROFILE_NAMES:
        assert name in message, f"the refusal does not name the present section {name!r}"


def test_tc_conf_20_a_single_profile_file_is_returned_unchanged():
    """`TC-CONF-20` — a file with no `profiles` table keeps working: equal output, and no
    `HARNESS_PROFILE` is invented or overwritten."""
    single = {"HARNESS_PROFILE": "dev-ci", "prompt_template_v": SHARED_TEMPLATE, "x": 1}
    assert select_profile_config(single, "cloud-hosted") == single
    assert select_profile_config(single, "dev-ci") == single


def test_tc_conf_20_selection_is_pure():
    """`TC-CONF-20` — same inputs, equal output; the input (including its nested sections) is
    not mutated, and the result shares no mutable section with it."""
    file_cfg = f_profiles()
    before = copy.deepcopy(file_cfg)

    first = select_profile_config(file_cfg, "cloud-hosted")
    second = select_profile_config(file_cfg, "cloud-hosted")

    assert first == second
    assert file_cfg == before, "select_profile_config mutated its input"
    first["HARNESS_COST_CEILING"] = 999
    assert file_cfg == before, "the result aliases the input's section"


# --- TC-CONF-21 — the environment wins, over the matrix ------------------------------------------


def _resolve(composed):
    return resolve_run_config(composed, SYNTHETIC_COHORT)


def test_tc_conf_21_row_1_no_environment_uses_the_files_profile():
    composed = effective_config(f_profiles("edge-local"), environ={})
    assert composed["HARNESS_PROFILE"] == "edge-local"
    assert composed["HARNESS_HARDWARE_PROFILE"] == "unified-small"
    assert "retention_setting" not in composed
    assert _resolve(composed).backend_profile == "edge-local"


def test_tc_conf_21_row_2_the_environment_profile_beats_the_files():
    composed = effective_config(
        f_profiles("edge-local"), environ={"HARNESS_PROFILE": "cloud-hosted"}
    )
    assert composed["HARNESS_PROFILE"] == "cloud-hosted"
    assert "HARNESS_HARDWARE_PROFILE" not in composed, "the edge section leaked into cloud"
    resolved = _resolve(composed)
    assert resolved.backend_profile == "cloud-hosted"
    assert resolved.retention_setting == default_retention_setting()
    assert (resolved.cost_ceiling, resolved.cost_currency) == (50, "EUR")


def test_tc_conf_21_row_3_the_environment_selects_when_the_file_names_none():
    composed = effective_config(f_profiles(None), environ={"HARNESS_PROFILE": "dev-ci"})
    assert composed["HARNESS_PROFILE"] == "dev-ci"
    resolved = _resolve(composed)
    assert resolved.backend_profile == "dev-ci"
    assert (resolved.cost_ceiling, resolved.cost_currency) == (5, "USD")


def test_tc_conf_21_row_4_an_environment_key_beats_the_selected_section():
    composed = effective_config(
        f_profiles("edge-local"),
        environ={"HARNESS_PROFILE": "cloud-hosted", "HARNESS_COST_CEILING": "80"},
    )
    resolved = _resolve(composed)
    assert resolved.backend_profile == "cloud-hosted"
    assert resolved.cost_ceiling == 80, "the section's 50 beat the environment's 80"
    assert resolved.cost_currency == "EUR"


def test_tc_conf_21_row_5_no_profile_anywhere_refuses_with_no_default():
    with pytest.raises(ConfigurationError) as refusal:
        _resolve(effective_config(f_profiles(None), environ={}))
    assert "HARNESS_PROFILE" in str(refusal.value)


def test_tc_conf_21_row_6_the_match_is_exact_and_the_environment_is_not_dropped():
    """A mis-cased environment value must raise — falling back to the file's `edge-local` would
    be the environment silently ignored."""
    with pytest.raises(ConfigurationError) as refusal:
        _resolve(
            effective_config(f_profiles("edge-local"), environ={"HARNESS_PROFILE": "EDGE-LOCAL"})
        )
    assert "EDGE-LOCAL" in str(refusal.value)


def test_tc_conf_21_row_7_the_environment_bind_beats_the_files():
    composed = effective_config(
        f_profiles("edge-local", CONSOLE_BIND="127.0.0.1"), environ={"CONSOLE_BIND": "0.0.0.0"}
    )
    assert composed["CONSOLE_BIND"] == "0.0.0.0"
    assert composed["HARNESS_PROFILE"] == "edge-local"


def test_tc_conf_21_a_passed_environ_ignores_a_conflicting_os_environ(monkeypatch):
    """`resolve_run_config` still reads no `os.environ`, and `effective_config(environ=E)` reads
    `E` only: a conflicting process environment changes nothing."""
    clear_profile_environment(monkeypatch)
    monkeypatch.setenv("HARNESS_PROFILE", "dev-ci")
    monkeypatch.setenv("HARNESS_COST_CEILING", "1")
    monkeypatch.setenv("CONSOLE_BIND", "0.0.0.0")

    composed = effective_config(
        f_profiles("edge-local"), environ={"HARNESS_PROFILE": "cloud-hosted"}
    )
    assert composed["HARNESS_PROFILE"] == "cloud-hosted"
    assert "CONSOLE_BIND" not in composed
    resolved = _resolve(composed)
    assert resolved.backend_profile == "cloud-hosted"
    assert resolved.cost_ceiling == 50

    # And resolution of an already-composed dict never consults the process environment.
    assert _resolve(effective_config(f_profiles("edge-local"), environ={})).backend_profile == (
        "edge-local"
    )
