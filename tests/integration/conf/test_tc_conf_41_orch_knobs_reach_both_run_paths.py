"""TC-CONF-41 (issue #818) — the config file's orchestration knobs reach both run paths.

Console-clarity test plan §3.1 (story T5), FR-CONF-36, CT-CONF-25, pair M-CONSOLE→M-CONF.

A config file with `orch_escalation_budget = 1.0` and `orch_random_arm_rate = 0`, and neither
`HARNESS_ORCH_*` variable in the environment. A fixture run of the four-paper ENG7 class is
started (a) with `aeh run` and (b) with the console's "start run" action. Oracle: the run row's
`provider_config` records 1.0 / 0, the start-up banner says both came from the config file, and
the run completes — it does not pause with "no progress" (the RC-14 symptom: with the 0.30
default, a few-paper run ran out of escalations and stalled).

What carries the oracle here is the run row and the banner. Completion is asserted, but this
fixture world does not reproduce the live stall: with the file's budget set to 0.30 the stand-in
run still completes (checked by hand while writing this suite), because a one-judge panel with
no escalation judges never widens, so the budget is never what holds a cell back.

The two arms are separate worlds: a console start refuses a cohort and package version whose
run has already left `pending`.

The console arm passes no `config=` to "start run", so the action composes the configuration
itself (`compose_run_start_config`) from the file the server was started with. The plan's
mutation — drop the config read in `run_start.py` — leaves the run on the defaults (0.30 / 0.07)
and this arm goes red: the 0.07 random-arm rate needs two escalation seats the one-judge file
does not have, so the start is refused, and no row records 1.0 / 0.

Rung 3: the real `OpenRouterProvider` over a stand-in transport (`tests/support/eng7_sample.py`).
`HARNESS_DECISION_ENGINE=off` is set in the environment because the stand-in has no Jev SDK
leg; it is not an orchestration knob.

Markers. `integration` (rung 3, real store and the operator command path).
"""

from __future__ import annotations

import io
import json
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from aeh.conf import parse_config_document
from aeh.conf.orch_knobs import (
    ESCALATION_BUDGET_ENV_KEY,
    ESCALATION_BUDGET_FILE_KEY,
    RANDOM_ARM_RATE_ENV_KEY,
    RANDOM_ARM_RATE_FILE_KEY,
)
from aeh.store import open_store
from tests.support.eng7_sample import (
    DEV_CI_CONFIG,
    forget_sample_modules,
    ingest_eng7,
    run_rows,
)

pytestmark = pytest.mark.integration

pytest.importorskip("pypdfium2")

BUDGET_LINE = "Second-opinion budget: 100% (from the config file)"
SAMPLE_LINE = "Random extra-grader sample: off (from the config file)"
WORKER_JOIN_SECONDS = 120


def _knob_config(tmp_path: Path) -> Path:
    """The dev-ci config with the two knobs set to exactly 1.0 and 0 in its dev-ci section."""
    text = DEV_CI_CONFIG.read_text(encoding="utf-8")
    text, budget_hits = re.subn(r"(?m)^orch_escalation_budget\s*=.*$",
                                "orch_escalation_budget = 1.0", text)
    text, rate_hits = re.subn(r"(?m)^orch_random_arm_rate\s*=.*$",
                              "orch_random_arm_rate = 0", text)
    assert (budget_hits, rate_hits) == (1, 1), "the dev-ci config no longer carries both keys"
    path = tmp_path / "knobs.dev-ci.toml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def no_knob_env(monkeypatch):
    """No orchestration knob in the environment — the autouse `random_arm_deterministic`
    fixture's rate pin included, or the rate half would pass with the file ignored."""
    for key in (ESCALATION_BUDGET_ENV_KEY, RANDOM_ARM_RATE_ENV_KEY,
                "HARNESS_PROFILE", "HARNESS_FIXTURE_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HARNESS_DECISION_ENGINE", "off")
    yield
    forget_sample_modules()


def _assert_recorded_and_complete(rows: list[dict]) -> None:
    assert len(rows) == 1, f"expected exactly one run row, got {rows!r}"
    row = rows[0]
    recorded = json.loads(row["provider_config"] or "{}")
    assert recorded.get(ESCALATION_BUDGET_FILE_KEY) == 1.0, (
        f"the run row recorded budget {recorded.get(ESCALATION_BUDGET_FILE_KEY)!r}, not the "
        f"file's 1.0: {recorded!r}")
    assert RANDOM_ARM_RATE_FILE_KEY in recorded and recorded[RANDOM_ARM_RATE_FILE_KEY] == 0, (
        f"the run row recorded rate {recorded.get(RANDOM_ARM_RATE_FILE_KEY)!r}, not the "
        f"file's 0: {recorded!r}")
    # And M-ORCH's per-run read (the one its escalation admission, random-arm enumeration and
    # budget alert all go through) answers the recorded values for this run, with no env set.
    from aeh.orch import settings as orch_settings

    assert orch_settings._run_knob(
        row, orch_settings.ESCALATION_BUDGET_ENV, ESCALATION_BUDGET_FILE_KEY,
        orch_settings.ORCH_ESCALATION_BUDGET) == 1.0
    assert orch_settings._run_knob(
        row, orch_settings.RANDOM_ARM_RATE_ENV, RANDOM_ARM_RATE_FILE_KEY,
        orch_settings.ORCH_RANDOM_ARM_RATE) == 0.0
    assert "no progress" not in (row["pause_reason"] or ""), row["pause_reason"]
    assert row["status"] == "complete", (
        f"the four-paper run did not complete: status {row['status']!r}, "
        f"pause reason {row['pause_reason']!r}")


def test_tc_conf_41_a_aeh_run_records_the_file_knobs_and_completes(
        tmp_data_dir, tmp_path, monkeypatch, capsys, no_knob_env):
    """TC-CONF-41(a) — `aeh run` with the knob file and no knob environment."""
    from aeh.pipeline import cli

    config = _knob_config(tmp_path)
    world = ingest_eng7(tmp_data_dir, tmp_path, monkeypatch, config)
    capsys.readouterr()
    code = cli.main(["run", "--data-dir", world.data_dir, "--cohort", world.cohort_id,
                     "--package-version", world.package_version, "--config", str(config)])
    printed, err = capsys.readouterr()

    assert world.fake.refused == [], f"a seat's name went out as a model: {world.fake.refused}"
    banner = printed.splitlines()
    assert BUDGET_LINE in banner and SAMPLE_LINE in banner, printed[:2000]
    assert "no progress" not in printed + err
    assert code == 0, (code, err)
    _assert_recorded_and_complete(run_rows(world.data_dir))


def test_tc_conf_41_b_console_start_run_records_the_file_knobs_and_completes(
        tmp_data_dir, tmp_path, monkeypatch, no_knob_env):
    """TC-CONF-41(b) — the console's "start run", composing the configuration itself from the
    file the server was started with."""
    from aeh.console import serve_console
    from aeh.console.run_start import run_start_preview_read

    config = _knob_config(tmp_path)
    world = ingest_eng7(tmp_data_dir, tmp_path, monkeypatch, config)
    monkeypatch.setenv("CONSOLE_PORT", "0")
    file_cfg = parse_config_document(config.read_text(encoding="utf-8"), "toml")

    store = open_store(tmp_data_dir)
    server = None
    try:
        with redirect_stdout(io.StringIO()):
            server = serve_console(store=store, cfg=file_cfg, config_path=str(config))
        app = server.app
        preview = run_start_preview_read(app, {
            "cohort_id": world.cohort_id, "package_version": world.package_version,
            "profile": "dev-ci"})
        banner = preview["banner"].splitlines()
        assert BUDGET_LINE in banner and SAMPLE_LINE in banner, preview["banner"]

        outcome = app.perform("start run", cohort_id=world.cohort_id,
                              package_version=world.package_version)
        rows = run_rows(world.data_dir)
        assert len(rows) == 1, f"start run created no run: {outcome!r}"
        thread = app._run_threads[rows[0]["run_id"]]
        thread.join(WORKER_JOIN_SECONDS)
        assert not thread.is_alive(), "the console's run worker did not finish"
    finally:
        if server is not None:
            server.terminate()
        store.close()

    assert world.fake.refused == [], f"a seat's name went out as a model: {world.fake.refused}"
    _assert_recorded_and_complete(run_rows(world.data_dir))
