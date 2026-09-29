"""TC-PIPE-09 (FR-PIPE-09; TS-84, #378): the command line recovers before it serves.

| Arm | Oracle |
|---|---|
| (a) | `python -m aeh recover --data-dir D` on a store with one expired lease prints a report with `leases_reclaimed: 1` and exits 0 |
| (b) | `python -m aeh console --data-dir D` (`CONSOLE_PORT=0`) reclaims the lease before the socket accepts: by the time the first `GET /` is answered (200), the dead worker no longer holds the unit |

Disclosed for (b): the plan's oracle reads "the first `GET /` sees the unit `pending`". The console
also resumes the run on a background worker once recovery is done (NFR-CONSOLE-08), so the unit
may already be re-leased — by the console's own worker — by the time the request is checked. The
case therefore asserts the property the ordering is about: the DEAD worker's lease is gone before
the first request is served.

The fetch runs inside `loopback_census`: the guard stays strict for every non-loopback host.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from tests.integration.pipe.test_recover import abandoned_lease  # noqa: F401  (the fixture)
from tests.support.guards import loopback_census
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]


def _env(**extra: str) -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO / "src"), str(REPO)]), **extra}


def test_tc_pipe_09_a_cli_recover_reports_the_reclaimed_lease(abandoned_lease, tmp_data_dir):
    _store, run_id, _unit = abandoned_lease
    done = subprocess.run([sys.executable, "-m", "aeh", "recover", "--data-dir", str(tmp_data_dir)],
                          capture_output=True, text=True, env=_env(), timeout=120)
    assert done.returncode == 0, done.stderr[-1500:]
    report = json.loads(done.stdout)
    assert report["leases_reclaimed"] == 1, report
    assert run_id in report["runs_resumed"], report


def test_tc_pipe_09_b_the_console_reclaims_before_it_accepts(abandoned_lease, tmp_data_dir,
                                                            network_guard):
    _store, _run_id, unit = abandoned_lease
    process = subprocess.Popen(
        [sys.executable, "-m", "aeh", "console", "--data-dir", str(tmp_data_dir)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=_env(CONSOLE_PORT="0", PYTHONUNBUFFERED="1"))
    try:
        deadline = time.monotonic() + 60
        port = None
        while time.monotonic() < deadline and port is None:
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    pytest.fail("the console exited before reporting its port")
                continue
            if "listening on port" in line:
                port = int(line.split("listening on port", 1)[1].split()[0])
        assert port, "the console never reported its port"
        with loopback_census(network_guard) as census,                 urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=30) as response:
            assert response.status == 200
        assert census, "the fetch made no loopback connection"

        with sqlite3.connect(Path(tmp_data_dir) / "cohorts" / f"{ORCH_COHORT_ID}.sqlite") as c:
            owner = c.execute("SELECT status, lease_owner FROM work_unit WHERE work_id = ?",
                              (unit.work_id,)).fetchone()
        assert owner is not None
        assert owner[1] != "worker-dead", (
            f"the dead worker still holds unit {unit.work_id[:12]} after the console answered: "
            f"{owner} — recovery must run before the socket accepts (FR-PIPE-09)")
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
