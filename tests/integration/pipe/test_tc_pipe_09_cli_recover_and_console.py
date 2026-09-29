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

The lease row is read twice: at the port announcement, and after the first `GET /` is
answered. A console that served while recovering concurrently can still slip past both reads
if recovery wins the race; the plan's oracle cannot observe that ordering from outside.

The fetch runs inside `loopback_census`: the guard stays strict for every non-loopback host.
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import subprocess
import sys
import threading
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


def _lease_owner(data_dir, work_id: str):
    with sqlite3.connect(Path(data_dir) / "cohorts" / f"{ORCH_COHORT_ID}.sqlite") as c:
        row = c.execute("SELECT lease_owner FROM work_unit WHERE work_id = ?", (work_id,)).fetchone()
    assert row is not None, f"unit {work_id[:12]} is missing"
    return row[0]


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
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(x) for x in process.stdout], daemon=True).start()
    try:
        deadline = time.monotonic() + 60
        port = None
        while port is None:
            try:
                line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                pytest.fail("the console never reported its port")
            if "listening on port" in line:
                port = int(line.split("listening on port", 1)[1].split()[0])
        # Read at the announcement, before any request: the socket accepts from here on.
        at_announce = _lease_owner(tmp_data_dir, unit.work_id)
        assert at_announce != "worker-dead", (
            f"the dead worker still held unit {unit.work_id[:12]} when the port was announced")
        with loopback_census(network_guard) as census,                 urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=30) as response:
            assert response.status == 200
        assert census, "the fetch made no loopback connection"

        owner = _lease_owner(tmp_data_dir, unit.work_id)
        assert owner != "worker-dead", (
            f"the dead worker still holds unit {unit.work_id[:12]} after the console answered: "
            f"{owner} — recovery must run before the socket accepts (FR-PIPE-09)")
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
