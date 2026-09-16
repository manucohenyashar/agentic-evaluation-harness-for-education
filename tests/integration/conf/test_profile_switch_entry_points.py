"""`TS-103` (issue #397) — switching harness profiles by environment variable, at the entry points.

Gap-fix test plan §5.9, the rung-3 half:

- `TC-CONF-21`, **in-process console variant** (`FR-CONF-14`, `FR-CONSOLE-36`): a console started
  under `HARNESS_PROFILE=dev-ci` re-reads the environment at action time — switched to
  `cloud-hosted`, "start run" is refused (`CT-CONSOLE-27`) and no run row is created.
- `TC-CONF-22` (`FR-CONF-15`): run RA paused under `edge-local`, the environment switched to
  `cloud-hosted`, `recover(store)` — RA stays paused naming both profiles, is not rebound and none
  of its units lease; RB's expired lease is reclaimed and RB alone resumes; `recover` does not
  raise. Variant: switched back to `edge-local`, RA resumes.
- `TC-CONF-23` (`FR-CONF-16`): `python -m aeh run` prints `profile_summary()` and the source of
  `HARNESS_PROFILE` (`environment` / `config file`), with no credential in the output.

**Written ahead of implementation: yes.** #352 landed the `M-CONF` helpers; the entry points that
must call them do not exist yet. Each case is `writtenahead` and keyed in
`WRITTEN_AHEAD_BLOCKERS` to the story that makes it runnable — `aeh.pipeline:recover`/`main`
(#365) and the served console (#366) — rather than to #352, which is already closed by the time
these run.

**Interface assumed**, from design delta §3.1 (`M-PIPE`) and §3.10 (`M-CONSOLE`):

| Name | Source |
|---|---|
| `aeh.pipeline.recover(store, *, clock=None) -> RecoveryReport` with `runs_resumed`, `leases_reclaimed` | §3.1 Interfaces |
| `aeh.pipeline.main(argv) -> int`; `run --data-dir D --cohort C --package-version V [--config FILE]` | §3.1, FR-PIPE-08 |
| `--config FILE` parsed by extension (TOML here) | FR-CONF-13 |
| `POST /actions/start-run` routed to `perform("start run", **form)` | FR-CONSOLE-33 (slug form as TC-CONSOLE-43's `finalize-batch`) |
| `run.pause_reason` column | shipped (`aeh.orch`) |

The `TC-CONF-23` oracle is the banner, not the run: the fixture world cannot complete a dev-ci run
end to end here, so the exit code is not asserted — only that the start-up block is printed.
"""

from __future__ import annotations

import http.client
import urllib.parse
from pathlib import Path

import pytest

from aeh.store import open_store
from tests.support.clock import FrozenClock
from tests.support.conf_builders import SENTINEL_CREDENTIAL, seed_credentials
from tests.support.impl import CONSOLE_MODULE, NotImplementedYet, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package
from tests.support.profile_switching import (
    clear_profile_environment,
    f_profiles,
    f_profiles_toml,
    leased_units,
    run_row,
    seed_switched_runs,
)

pytestmark = pytest.mark.integration

PIPELINE_MODULE = "aeh.pipeline"
REPO_ROOT = Path(__file__).resolve().parents[3]
RECOVER_ISSUE = "#365"
CONSOLE_ISSUE = "#366"


# --- TC-CONF-22 — a switch never rebinds a resumed run ------------------------------------------


@pytest.mark.writtenahead
def test_tc_conf_22_recover_leaves_the_switched_run_paused_and_recovers_the_other(
    tmp_data_dir, monkeypatch
):
    """`TC-CONF-22` — exact state after `recover` under a switched environment."""
    clear_profile_environment(monkeypatch)
    clock = FrozenClock()
    store = open_store(tmp_data_dir)
    try:
        world = seed_switched_runs(store, clock)
        cohort, ra, rb = world["cohort_id"], world["ra"], world["rb"]
        assert run_row(store, cohort, ra)["status"] == "paused"
        assert world["rb_leased"], "the fixture claimed no RB unit to expire"

        recover = require(PIPELINE_MODULE, "recover", issue=RECOVER_ISSUE)
        monkeypatch.setenv("HARNESS_PROFILE", "cloud-hosted")
        report = recover(store, clock=clock)  # must not raise

        ra_after = run_row(store, cohort, ra)
        assert ra_after["status"] == "paused", "recover resumed RA on a different profile"
        reason = ra_after["pause_reason"] or ""
        assert "'edge-local'" in reason and "'cloud-hosted'" in reason, (
            f"RA's pause reason does not name both profiles: {reason!r}"
        )
        assert ra_after["backend_profile"] == world["ra_row"]["backend_profile"] == "edge-local"
        assert ra_after["provider_config"] == world["ra_row"]["provider_config"], (
            "recover rebound RA's persisted provider_config"
        )
        assert ra_after["panel_config"] == world["ra_row"]["panel_config"]
        assert leased_units(store, cohort, ra) == [], "an RA unit was leased after the switch"

        assert tuple(report.runs_resumed) == (rb,), (
            f"runs_resumed should hold RB only, got {report.runs_resumed!r}"
        )
        assert report.leases_reclaimed == len(world["rb_leased"])
        assert leased_units(store, cohort, rb) == [], "RB's expired lease was not reclaimed"
        assert run_row(store, cohort, rb)["status"] == "running"
    finally:
        store.close()


@pytest.mark.writtenahead
def test_tc_conf_22_variant_the_matching_profile_resumes_the_run(tmp_data_dir, monkeypatch):
    """`TC-CONF-22` variant — the refusal is the mismatch, not the run: the same world recovered
    with the environment on `edge-local` (RA's own profile) resumes RA, unchanged.

    Run as its own world rather than after a refused `recover`: what a refused recover does with
    RA's queued resume request is not specified, and this variant is about the profile check."""
    clear_profile_environment(monkeypatch)
    clock = FrozenClock()
    store = open_store(tmp_data_dir)
    try:
        world = seed_switched_runs(store, clock)
        cohort, ra = world["cohort_id"], world["ra"]

        recover = require(PIPELINE_MODULE, "recover", issue=RECOVER_ISSUE)
        monkeypatch.setenv("HARNESS_PROFILE", "edge-local")
        report = recover(store, clock=clock)

        assert ra in report.runs_resumed, (
            f"with the environment on RA's own profile RA did not resume: {report.runs_resumed!r}"
        )
        ra_after = run_row(store, cohort, ra)
        assert ra_after["status"] == "running"
        assert ra_after["provider_config"] == world["ra_row"]["provider_config"]
    finally:
        store.close()


# --- TC-CONF-23 — the start-up banner names the profile and where it came from -----------------


def _seed_cli_world(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, ("SYN-001",))
        version = seed_package(
            store, ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},),
            package_id="pkg-profile-cli",
        )
    finally:
        store.close()
    return version


@pytest.mark.writtenahead
@pytest.mark.parametrize(
    ("environment_profile", "file_profile", "expected_source"),
    [("dev-ci", "edge-local", "environment"), (None, "dev-ci", "config file")],
    ids=["a-environment", "b-config-file"],
)
def test_tc_conf_23_run_prints_the_profile_summary_and_its_source(
    tmp_data_dir, tmp_path, monkeypatch, capsys, environment_profile, file_profile,
    expected_source,
):
    """`TC-CONF-23` — exact source line, every `profile_summary()` field, and a negative scan for
    the sentinel credential seeded into every credential-bearing variable."""
    from aeh.conf import CohortRef, effective_config, parse_config_document, resolve_run_config

    clear_profile_environment(monkeypatch)
    sentinel = seed_credentials(monkeypatch)
    version = _seed_cli_world(tmp_data_dir)
    # The sentinel goes in the file as well as the environment: `environment_snapshot` lifts only
    # the `HARNESS_*` keys, so an environment-only sentinel could never reach the output whatever
    # `main` printed (the `seed_credentials` docstring's vacuous-pass warning).
    document = f'OPENROUTER_API_KEY = "{sentinel}"\n' + f_profiles_toml(file_profile)
    config_file = tmp_path / "harness.toml"
    config_file.write_text(document, encoding="utf-8")
    environ = {}
    if environment_profile is not None:
        monkeypatch.setenv("HARNESS_PROFILE", environment_profile)
        environ["HARNESS_PROFILE"] = environment_profile

    main = require(PIPELINE_MODULE, "main", issue=RECOVER_ISSUE)
    main([
        "run", "--data-dir", str(tmp_data_dir), "--cohort", ORCH_COHORT_ID,
        "--package-version", version, "--config", str(config_file),
    ])
    captured = capsys.readouterr()
    output = captured.out + captured.err

    expected = resolve_run_config(
        effective_config(parse_config_document(document, "toml"), environ),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    ).profile_summary()
    assert f"HARNESS_PROFILE source: {expected_source}" in output, output
    assert expected.backend_profile == (environment_profile or file_profile)
    assert expected.backend_profile in output
    assert expected.panel_build_ref in output, "the banner omits the panel build identity"
    for ref in expected.panel:
        assert ref.build_id in output, f"the banner omits panel build {ref.build_id!r}"
    assert expected.transcriber.build_id in output
    for quantization in expected.quantization:
        assert quantization in output, f"the banner omits quantization {quantization!r}"
    assert sentinel not in output and SENTINEL_CREDENTIAL not in output, (
        "a credential value reached the start-up output (NFR-CONF-02)"
    )


# --- TC-CONF-21, in-process console variant — the console re-reads the environment per action --


@pytest.mark.writtenahead
def test_tc_conf_21_console_rereads_the_environment_when_start_run_is_requested(
    tmp_data_dir, monkeypatch, network_guard
):
    """`TC-CONF-21` console variant — started under `dev-ci`, the environment switched to
    `cloud-hosted`, POST "start run": refused under `CT-CONSOLE-27`, with no run row created."""
    clear_profile_environment(monkeypatch)
    version = _seed_cli_world(tmp_data_dir)
    store = open_store(tmp_data_dir)
    server = None
    try:
        monkeypatch.setenv("HARNESS_PROFILE", "dev-ci")
        monkeypatch.setenv("CONSOLE_PORT", "0")
        # `serve_console` already exists; the served HTTP console does not. Fail fast naming
        # #366 rather than on a connect timeout against today's non-accepting socket. The
        # signal is `_CHILD_SCRIPT`'s deletion — `FR-CONSOLE-33` names it in those words, and
        # it is the child-process console the in-process server replaces. (This guard read the
        # packaged stylesheet until #358 shipped that file; a path that now exists cannot
        # discriminate.)
        if "_CHILD_SCRIPT" in (REPO_ROOT / "src" / "aeh" / "console.py").read_text(
            encoding="utf-8"
        ):
            raise NotImplementedYet(
                f"the console still serves through the child-process script — the in-process "
                f"ThreadingHTTPServer is blocked on {CONSOLE_ISSUE}"
            )
        serve_console = require(CONSOLE_MODULE, "serve_console", issue=CONSOLE_ISSUE)
        server = serve_console(store=store, cfg=f_profiles(None))
        host, port = server.socket.getsockname()[:2]
        runs_before = store.cohort(ORCH_COHORT_ID).query("SELECT run_id FROM run")

        monkeypatch.setenv("HARNESS_PROFILE", "cloud-hosted")
        body = urllib.parse.urlencode(
            {"cohort_id": ORCH_COHORT_ID, "package_version": version}
        )
        # The autouse socket guard blocks loopback too; stood down only around this one
        # request to the console's own port (the TC-CONSOLE-34 precedent).
        network_guard.uninstall()
        connection = http.client.HTTPConnection(host, port, timeout=10)
        try:
            connection.request(
                "POST", "/actions/start-run", body=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response = connection.getresponse()
            status, text = response.status, response.read().decode("utf-8", "replace")
        finally:
            connection.close()
            network_guard.install()

        # No HTTP status is asserted (Q-25): a refusal page is `dispatched=False` plus refusal
        # text (FR-CONSOLE-34). The run row count is the oracle; the text names the profile.
        assert "cloud-hosted" in text, (
            f"start run answered {status} without naming the resolved cloud-hosted profile: the "
            f"console kept the profile it read at start-up"
        )
        runs_after = store.cohort(ORCH_COHORT_ID).query("SELECT run_id FROM run")
        assert [dict(r) for r in runs_after] == [dict(r) for r in runs_before], (
            "a run row was created on a cloud-hosted resolution"
        )
    finally:
        if server is not None:
            server.terminate()
        store.close()
