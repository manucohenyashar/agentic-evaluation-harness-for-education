"""TC-CONF-46 (issue #907; CT-CONF-26, FR-CONF-38, FR-AGG-21): both run paths freeze the same
aggregation values.

Pair M-CONSOLE→M-CONF. Statistical-validity test plan §3.9, story T10. One config file sets
`agg_holistic_multiplier = 0.9` in its profile section, and no `HARNESS_AGG_*` variable is in the
environment. A fixture run of the four-paper ENG7 class is started (a) with `aeh run` and (b)
with the console's "start run" action. Oracle: each run row's frozen `run_config` records 0.9,
the other three `agg_*` keys at their defaults, and M-ORCH's run handle (what every aggregation
pass is given, FR-AGG-21) reads 0.9 back.

Since #865 the four values live only in `run_config`. `provider_config` stays byte-identical
(NFR-SYS-14), which is why the run row is read here, not through `eng7_sample.run_rows`.

The console arm passes no `config=` to "start run". The action composes the configuration
itself from the file the server was started with. If that file read is dropped, the row records
the 0.95 default and this arm goes red. The two arms are separate worlds, because a console
start refuses a cohort and version whose run has already left `pending`.

Rung 3: the real `OpenRouterProvider` over a stand-in transport (`tests/support/eng7_sample.py`),
real store, operator command path. `HARNESS_DECISION_ENGINE=off` because the stand-in has no
Jev SDK leg.

Markers: `integration`.
"""

from __future__ import annotations

import io
import json
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from aeh.conf import AGG_KEYS, parse_config_document
from aeh.store import open_store
from tests.support.eng7_sample import DEV_CI_CONFIG, ENG7_COHORT, forget_sample_modules, ingest_eng7

pytestmark = pytest.mark.integration

pytest.importorskip("pypdfium2")

WORKER_JOIN_SECONDS = 120
#: What both run rows must freeze: the file's 0.9, the other three at M-AGG's defaults.
FROZEN = {"agg_auto_threshold_atomic": 0.80, "agg_auto_threshold_holistic": 0.90,
          "agg_uncited_multiplier": 0.80, "agg_holistic_multiplier": 0.9}


def _knob_config(tmp_path: Path) -> Path:
    """The dev-ci config with `agg_holistic_multiplier = 0.9` in its dev-ci profile section."""
    text = DEV_CI_CONFIG.read_text(encoding="utf-8")
    assert "agg_holistic_multiplier" not in text, "the shipped dev-ci config now sets the key"
    text, hits = re.subn(r"(?m)^(orch_random_arm_rate\s*=.*)$",
                         r"\1\nagg_holistic_multiplier = 0.9", text)
    assert hits == 1, "the dev-ci profile section no longer carries orch_random_arm_rate"
    path = tmp_path / "agg.dev-ci.toml"
    path.write_text(text, encoding="utf-8")
    parsed = parse_config_document(text, "toml")
    assert parsed["profiles"]["dev-ci"]["agg_holistic_multiplier"] == 0.9
    return path


@pytest.fixture
def no_agg_env(monkeypatch):
    """No aggregation knob in the environment, so the file is the only source of 0.9."""
    for key in (*AGG_KEYS, "HARNESS_PROFILE", "HARNESS_FIXTURE_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HARNESS_DECISION_ENGINE", "off")
    yield
    forget_sample_modules()


def _assert_frozen(data_dir: str | Path) -> None:
    from aeh.orch import Orchestrator

    store = open_store(data_dir)
    try:
        rows = [dict(r) for r in store.cohort(ENG7_COHORT).query(
            "SELECT run_id, status, run_config FROM run")]
        assert len(rows) == 1, f"expected exactly one run row, got {rows!r}"
        (row,) = rows
        recorded = json.loads(row["run_config"])["provider_config"]
        assert {key: recorded.get(key) for key in FROZEN} == FROZEN, recorded
        knobs = Orchestrator(store).run_handle(row["run_id"]).agg_knobs
    finally:
        store.close()
    assert knobs.holistic_multiplier == 0.9, f"the run handle hands aggregate {knobs}"
    assert row["status"] == "complete", row["status"]


def test_tc_conf_46_a_aeh_run_freezes_the_file_multiplier(
        tmp_data_dir, tmp_path, monkeypatch, capsys, no_agg_env):
    """TC-CONF-46(a): `aeh run` with the knob file and no knob environment."""
    from aeh.pipeline import cli

    config = _knob_config(tmp_path)
    world = ingest_eng7(tmp_data_dir, tmp_path, monkeypatch, config)
    capsys.readouterr()
    code = cli.main(["run", "--data-dir", world.data_dir, "--cohort", world.cohort_id,
                     "--package-version", world.package_version, "--config", str(config)])
    _, err = capsys.readouterr()
    assert code == 0, (code, err)
    _assert_frozen(world.data_dir)


def test_tc_conf_46_b_console_start_run_freezes_the_file_multiplier(
        tmp_data_dir, tmp_path, monkeypatch, no_agg_env):
    """TC-CONF-46(b): the console's "start run", composing the configuration itself from the
    file the server was started with."""
    from aeh.console import serve_console

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
        outcome = app.perform("start run", cohort_id=world.cohort_id,
                              package_version=world.package_version)
        run_ids = list(app._run_threads)
        assert len(run_ids) == 1, f"start run started {run_ids}: {outcome!r}"
        thread = app._run_threads[run_ids[0]]
        thread.join(WORKER_JOIN_SECONDS)
        assert not thread.is_alive(), "the console's run worker did not finish"
    finally:
        if server is not None:
            server.terminate()
        store.close()
    _assert_frozen(world.data_dir)
