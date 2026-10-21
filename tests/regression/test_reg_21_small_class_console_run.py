"""TC-REG-21 (issue #818) — T0a: the four-student console run completes with the shipped config
and no environment.

Console-clarity test plan §3.12 (→ TC-CONF-41). The live teacher test's first symptom: the
console's run of the four-paper ENG7 class, started under the shipped
`docs/live-tests/config/live-test.dev-ci.toml`, needed two `$env:HARNESS_ORCH_…` lines before it
would finish. This thin case starts that run through the console's "start run" with the shipped
file **verbatim** and neither `HARNESS_ORCH_*` variable set, and asserts the run completes
and recorded the file's 1.0 / 0, so the original symptom stays pinned.

`HARNESS_DECISION_ENGINE=off` is set because the stand-in transport has no Jev SDK leg
(`tests/support/eng7_sample.py`); it is not an orchestration knob.

Markers. `integration` (rung 3: real store, the console action, the real provider over a
stand-in transport).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

from aeh.conf import parse_config_document
from aeh.conf.orch_knobs import (
    ESCALATION_BUDGET_ENV_KEY,
    ESCALATION_BUDGET_FILE_KEY,
    RANDOM_ARM_RATE_ENV_KEY,
    RANDOM_ARM_RATE_FILE_KEY,
)
from aeh.store import open_store
from tests.support.eng7_sample import DEV_CI_CONFIG, forget_sample_modules, ingest_eng7, run_rows

pytestmark = pytest.mark.integration

pytest.importorskip("pypdfium2")


def test_tc_reg_21_the_four_student_console_run_completes_with_the_shipped_config(
        tmp_data_dir, tmp_path, monkeypatch):
    from aeh.console import serve_console

    for key in (ESCALATION_BUDGET_ENV_KEY, RANDOM_ARM_RATE_ENV_KEY,
                "HARNESS_PROFILE", "HARNESS_FIXTURE_DIR"):
        monkeypatch.delenv(key, raising=False)  # the autouse rate pin included
    monkeypatch.setenv("HARNESS_DECISION_ENGINE", "off")
    monkeypatch.setenv("CONSOLE_PORT", "0")
    try:
        world = ingest_eng7(tmp_data_dir, tmp_path, monkeypatch, DEV_CI_CONFIG)
        file_cfg = parse_config_document(DEV_CI_CONFIG.read_text(encoding="utf-8"), "toml")
        store = open_store(tmp_data_dir)
        server = None
        try:
            with redirect_stdout(io.StringIO()):
                server = serve_console(store=store, cfg=file_cfg, config_path=str(DEV_CI_CONFIG))
            outcome = server.app.perform("start run", cohort_id=world.cohort_id,
                                         package_version=world.package_version)
            rows = run_rows(world.data_dir)
            assert len(rows) == 1, f"start run created no run: {outcome!r}"
            thread = server.app._run_threads[rows[0]["run_id"]]
            thread.join(120)
            assert not thread.is_alive(), "the console's run worker did not finish"
        finally:
            if server is not None:
                server.terminate()
            store.close()
    finally:
        forget_sample_modules()

    (row,) = run_rows(world.data_dir)
    assert row["status"] == "complete", (row["status"], row["pause_reason"])
    assert "no progress" not in (row["pause_reason"] or "")
    recorded = json.loads(row["provider_config"] or "{}")
    assert (recorded.get(ESCALATION_BUDGET_FILE_KEY), recorded.get(RANDOM_ARM_RATE_FILE_KEY)) == (
        1.0, 0), recorded
