"""`TS-103` (issue #397) — `CT-CONF-15` and `CT-CONF-16`, the profile-switch clauses.

Gap-fix test plan §6:

- `TC-CONF-C15` (`CT-CONF-15`): `TC-CONF-21` rows 2, 4 and 7 through **each** entry point —
  `main(["run", ...])`, `main(["recover", ...])`, `serve_console` — with a spy on
  `effective_config`. Each resolves through it and yields the environment-selected values.
  **Breaks if** an entry point merges `{**snapshot, **cfg}` (the file wins) or reads
  `HARNESS_PROFILE` from `cfg` before composing. Adversarial construction: keep the console's
  `cfg`-only read — the `serve_console` arm of row 2 goes red.
- `TC-CONF-C16` (`CT-CONF-16`): `TC-CONF-22`'s world. **Breaks if** `recover` rebinds the paused
  run to the environment's profile, or raises and abandons the other runs.

**Written ahead of implementation: yes.** One function per entry point, so each arm is keyed to
the story that builds it: `main` (#365) and the served console (#366).

**How "exactly once per resolution" is read, arm by arm.**

* `serve_console` — one resolution at start, so exactly one call.
* `recover` — `recover(store, *, clock=None)` takes no configuration, so it must compose from
  the environment itself, and `main(["recover", ...])` may compose again for its banner
  (FR-CONF-16). The design fixes neither count, so the arm asserts at least one call and that
  **every** call carries the environment's values. `recover` is driven exactly as FR-PIPE-09
  specifies it — `--data-dir` only, no `--config`.
* `run` — `run` composes the `--config` file and then calls `recover` (FR-PIPE-08), whose inner
  resolution sees no file. Every call must carry the environment's keys; the calls that were
  **given the file** must also carry the file-derived values (row 2's section ceiling, row 7's
  file profile). And because a `main` could compose for the banner and then resolve the raw file,
  the arm also spies `resolve_run_config` — what was *used* — and requires every resolution to
  run under the environment-selected profile.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping

import pytest

from aeh.store import open_store
from tests.support.clock import FrozenClock
from tests.support.impl import CONSOLE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package
from tests.support.profile_switching import (
    clear_profile_environment,
    f_profiles,
    f_profiles_toml,
    leased_units,
    run_row,
    seed_switched_runs,
    spy_conf,
)

pytestmark = pytest.mark.contract

PIPELINE_MODULE = "aeh.pipeline"

#: `TC-CONF-21` rows 2, 4 and 7: (environment, file top-level keys, values expected of a
#: resolution that was given the file, effective profile).
ROWS = {
    "row-2": (
        {"HARNESS_PROFILE": "cloud-hosted"},
        {"HARNESS_PROFILE": "edge-local"},
        {"HARNESS_PROFILE": "cloud-hosted", "HARNESS_COST_CEILING": 50},
        "cloud-hosted",
    ),
    "row-4": (
        {"HARNESS_PROFILE": "cloud-hosted", "HARNESS_COST_CEILING": "80"},
        {"HARNESS_PROFILE": "edge-local"},
        {"HARNESS_PROFILE": "cloud-hosted", "HARNESS_COST_CEILING": "80"},
        "cloud-hosted",
    ),
    "row-7": (
        {"CONSOLE_BIND": "0.0.0.0"},
        {"HARNESS_PROFILE": "edge-local", "CONSOLE_BIND": "127.0.0.1"},
        {"HARNESS_PROFILE": "edge-local", "CONSOLE_BIND": "0.0.0.0"},
        "edge-local",
    ),
}


def _apply_environment(monkeypatch, environment):
    clear_profile_environment(monkeypatch)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)


def _given_a_file(args, kwargs):
    cfg = kwargs.get("cfg", args[0] if args else None)
    return isinstance(cfg, Mapping) and "profiles" in cfg


def _assert_every_call_carries(calls, expected, arm, *, only_file_calls=False):
    checked = [
        result for args, kwargs, result in calls
        if not only_file_calls or _given_a_file(args, kwargs)
    ]
    assert checked, (
        f"{arm} never resolved its configuration through effective_config"
        + (" with the config file" if only_file_calls else "")
    )
    for composed in checked:
        for key, value in expected.items():
            assert composed.get(key) == value, (
                f"{arm} composed {key}={composed.get(key)!r}, expected {value!r} — the "
                f"environment did not win (CT-CONF-15)"
            )


def _write_config(tmp_path, file_extras):
    head = [f'{key} = "{value}"' for key, value in file_extras.items()]
    path = tmp_path / "harness.toml"
    path.write_text("\n".join(head) + "\n" + f_profiles_toml(None), encoding="utf-8")
    return path


@pytest.mark.writtenahead
@pytest.mark.parametrize("row", sorted(ROWS))
def test_tc_conf_c15_run_resolves_through_effective_config_with_the_environment_winning(
    tmp_data_dir, tmp_path, monkeypatch, row
):
    """`TC-CONF-C15`, the `main(["run", ...])` arm — composed values and the profile used."""
    environment, file_extras, from_file, profile = ROWS[row]
    _apply_environment(monkeypatch, environment)
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, ("SYN-001",))
        version = seed_package(
            store, ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},),
            package_id="pkg-c15",
        )
    finally:
        store.close()
    config_file = _write_config(tmp_path, file_extras)

    main = require(PIPELINE_MODULE, "main", issue="#365")
    pipeline = importlib.import_module(PIPELINE_MODULE)
    composed = spy_conf(monkeypatch, "effective_config", pipeline)
    resolved = spy_conf(monkeypatch, "resolve_run_config", pipeline)
    main([
        "run", "--data-dir", str(tmp_data_dir), "--cohort", ORCH_COHORT_ID,
        "--package-version", version, "--config", str(config_file),
    ])

    _assert_every_call_carries(composed, environment, "main(['run', ...])")
    _assert_every_call_carries(composed, from_file, "main(['run', ...])", only_file_calls=True)
    assert resolved, "main(['run', ...]) never resolved a RunConfig"
    for _, _, config in resolved:
        assert config.backend_profile == profile, (
            f"run resolved its RunConfig under {config.backend_profile!r}, not the "
            f"environment-selected {profile!r}: it composed one dict and used another"
        )


@pytest.mark.writtenahead
@pytest.mark.parametrize("row", sorted(ROWS))
def test_tc_conf_c15_recover_resolves_through_effective_config_from_the_environment(
    tmp_data_dir, monkeypatch, row
):
    """`TC-CONF-C15`, the `main(["recover", ...])` arm, invoked as FR-PIPE-09 specifies it."""
    environment, _file_extras, _from_file, _profile = ROWS[row]
    _apply_environment(monkeypatch, environment)
    open_store(tmp_data_dir).close()

    main = require(PIPELINE_MODULE, "main", issue="#365")
    composed = spy_conf(
        monkeypatch, "effective_config", importlib.import_module(PIPELINE_MODULE)
    )
    main(["recover", "--data-dir", str(tmp_data_dir)])
    _assert_every_call_carries(composed, environment, "main(['recover', ...])")


@pytest.mark.parametrize("row", sorted(ROWS))
def test_tc_conf_c15_serve_console_resolves_through_effective_config_exactly_once(
    tmp_data_dir, monkeypatch, row
):
    """`TC-CONF-C15`, the `serve_console` arm. Rows 2 and 4 resolve `cloud-hosted` and row 7 a
    routable bind, so every row refuses to start — the refusal is required, and it can only come
    from the composed values, which are the oracle."""
    environment, file_extras, from_file, _profile = ROWS[row]
    _apply_environment(monkeypatch, environment)
    serve_console, ConsoleBindRefused = require(
        CONSOLE_MODULE, "serve_console", "ConsoleBindRefused", issue="#366"
    )
    composed = spy_conf(monkeypatch, "effective_config", importlib.import_module(CONSOLE_MODULE))
    store = open_store(tmp_data_dir)
    try:
        try:
            leaked = serve_console(store=store, cfg=f_profiles(None, **file_extras))
        except ConsoleBindRefused:
            pass
        else:
            leaked.terminate()
            pytest.fail(f"{row}: serve_console started on a refused resolution")
        assert len(composed) == 1, (
            f"serve_console resolved its configuration {len(composed)} times"
        )
        _assert_every_call_carries(composed, from_file, "serve_console")
    finally:
        store.close()


@pytest.mark.writtenahead
def test_tc_conf_c16_recover_never_rebinds_a_run_to_the_switched_profile(
    tmp_data_dir, monkeypatch
):
    """`TC-CONF-C16` — over `TC-CONF-22`'s world, whose RA carries a queued resume request a
    profile-blind `recover` would honour: `recover` returns (never raises), RA stays paused with
    both profiles named, keeps its persisted backend, and RB is still recovered."""
    clear_profile_environment(monkeypatch)
    clock = FrozenClock()
    store = open_store(tmp_data_dir)
    try:
        world = seed_switched_runs(store, clock)
        cohort, ra, rb = world["cohort_id"], world["ra"], world["rb"]

        recover = require(PIPELINE_MODULE, "recover", issue="#365")
        monkeypatch.setenv("HARNESS_PROFILE", "cloud-hosted")
        try:
            report = recover(store, clock=clock)
        except Exception as raised:  # noqa: BLE001 — raising at all is the clause broken
            pytest.fail(f"recover raised on a profile mismatch and abandoned RB: {raised!r}")

        ra_after = run_row(store, cohort, ra)
        for column in ("backend_profile", "provider_config", "panel_config"):
            assert ra_after[column] == world["ra_row"][column], f"recover rebound RA's {column}"
        assert ra_after["status"] == "paused", "recover resumed RA on the switched profile"
        reason = ra_after["pause_reason"] or ""
        assert "'edge-local'" in reason and "'cloud-hosted'" in reason, (
            f"RA's pause reason does not name both profiles (CT-CONF-16): {reason!r}"
        )
        assert ra not in report.runs_resumed
        assert leased_units(store, cohort, ra) == []
        assert rb in report.runs_resumed, "the mismatch abandoned the other run"
    finally:
        store.close()
