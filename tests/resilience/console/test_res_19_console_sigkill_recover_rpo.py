"""`RES-19` (issue #393, TS-99) — SIGKILL the `python -m aeh console` process mid-run, restart
it, and `recover` resumes the run to `complete` with §4.3's projected tables equal to an
uninterrupted run's, losing at most RPO = 5 s of completed work (NFR-CONSOLE-08, ADR-17,
FR-PIPE-09).

Gap-fix test plan §6.8 (resilience, rung 3). `TC-PIPE-09` (b) holds the ordering clause — the
console reclaims a dead worker's lease before the socket accepts — and `TC-PIPE-11` holds
recovery's equality clause for an in-process kill; this case holds both for the console process
itself, over the console's own door (`POST /api/v1/actions/start-run`, CT-PIPE-14).

**Realized deltas, disclosed.**

* *The kill.* On Windows `proc.kill()` is `TerminateProcess` — the honest SIGKILL equivalent
  on this platform (the RES-18 precedent), a process dying mid-write with no cleanup chance.
* *"3 s after start run" is realized as 3 s of dispatch after the first observed unit
  completion.* Worker start-up latency varies by host (1-17 s on this one), so a POST-relative
  timer would kill before any work had started on a slow box and prove nothing. Anchoring to
  the first completion makes the kill land mid-dispatch on every host; the run must still be
  `running` with units both done and not done at that moment, asserted. That assertion is also
  what a low `HARNESS_RES_19_SUBMISSIONS` or a very fast host breaks — a run small enough to
  finish inside the 3 s window fails the case there, spuriously; the 1000 default is what
  keeps the window mid-dispatch.
* *The RPO bound is asserted in its zero-loss form.* The completions observed before the kill
  span only `HARNESS_RES_19_KILL_AFTER_S` (default 3 s) < RPO, and the completed-id set is
  read from the sqlite file after the kill (the file survives TerminateProcess), so it
  includes the last instants before the death. "Every completion the test observed survives
  the kill" is therefore stronger than "at most 5 s of completed work was lost" — stronger
  for what it observes, not airtight: a completion lost AND re-done by the recovery would
  satisfy the id-set check, and it is the §4.3 projection equality against the control run
  that covers that shape. The multi-window old-loss measurement that the literal bound names
  is RES-18's, over the worker boundary rather than the console's.
* *The world.* The console door cannot supply the corpus's judged-drive keywords (CT-PIPE-14),
  so this is the console-world MCQ run frozen under the F-PROFILES dev-ci profile — the
  corpus-keyed kill differential is TC-PIPE-11's, in-process. The §4.3 tables compared are
  `criterion_score`, current `submission_grade`, the narratives' (submission, level, question)
  set and `review_queue` membership; this world has no extract units, so evidence/verdicts are
  empty on both sides.

The restarted console resumes the run with `resume_runs_in_background` against the run's own
frozen configuration (`compose_restart_config`, FR-CONF-15) re-resolved through the `--config`
TOML the child is started with.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from aeh.conf import effective_config, parse_config_document
from aeh.pipeline.background import start_run_in_background
from aeh.store import open_store
from tests.support.console_world import seed_scored_run
from tests.support.guards import loopback_census
from tests.support.profile_switching import f_profiles_toml

pytestmark = [pytest.mark.integration, pytest.mark.slow]

REPO_ROOT = Path(__file__).resolve().parents[3]

COHORT_ID = "c-res19"
RUN_ID = "run-res19"
PACKAGE_ID = "pkg-res19"

#: RPO bound the plan row states: at most 5 s of completed work may be lost to the kill.
RPO_S = 5.0

SUBMISSIONS = int(os.environ.get("HARNESS_RES_19_SUBMISSIONS", "1000"))
KILL_AFTER_S = float(os.environ.get("HARNESS_RES_19_KILL_AFTER_S", "3.0"))
RESTART_WAIT_S = float(os.environ.get("HARNESS_RES_19_RESTART_WAIT_S", "300"))


def _projection(data_dir: Path) -> dict[str, list]:
    """§4.3's projected tables for the run, by content, over the cohort's own database."""
    with sqlite3.connect(data_dir / "cohorts" / f"{COHORT_ID}.sqlite") as c:
        return {
            "scores": sorted(c.execute(
                "SELECT submission_id, criterion_id, band, points, judge_count, state "
                "FROM criterion_score WHERE run_id = ?", (RUN_ID,)).fetchall()),
            "grades": sorted(c.execute(
                "SELECT submission_id, grade, total, state FROM submission_grade "
                "WHERE run_id = ? AND is_current = 1", (RUN_ID,)).fetchall()),
            "narratives": sorted(c.execute(
                "SELECT DISTINCT submission_id, level, question_id FROM narrative").fetchall()),
            "review_queue": sorted(c.execute(
                "SELECT submission_id, criterion_id FROM review_queue "
                "WHERE run_id = ?", (RUN_ID,)).fetchall()),
        }


def _snapshot(data_dir: Path) -> tuple[int, int, str]:
    with sqlite3.connect(data_dir / "cohorts" / f"{COHORT_ID}.sqlite") as c:
        done, total = c.execute(
            "SELECT SUM(status = 'done'), COUNT(*) FROM work_unit WHERE run_id = ?",
            (RUN_ID,)).fetchone()
        row = c.execute("SELECT status FROM run WHERE run_id = ?", (RUN_ID,)).fetchone()
    return int(done or 0), int(total or 0), (str(row[0]) if row else "missing")


def _done_ids(data_dir: Path) -> set[str]:
    with sqlite3.connect(data_dir / "cohorts" / f"{COHORT_ID}.sqlite") as c:
        return {row[0] for row in c.execute(
            "SELECT work_id FROM work_unit WHERE run_id = ? AND status = 'done'", (RUN_ID,))}


def _grades_settled(data_dir: Path) -> bool:
    """The driver flips the run to `complete` BEFORE synthesis and grading finish, so a poll
    that stops at the status alone cuts the tail; wait for the grades to settle to `final`."""
    with sqlite3.connect(data_dir / "cohorts" / f"{COHORT_ID}.sqlite") as c:
        states = [row[0] for row in c.execute(
            "SELECT state FROM submission_grade WHERE run_id = ? AND is_current = 1", (RUN_ID,))]
    return bool(states) and all(state == "final" for state in states)


def _child_env(fixture_dir: Path) -> dict[str, str]:
    base = {key: value for key, value in os.environ.items()
            if not key.startswith("HARNESS_") and not key.startswith("CONSOLE_")}
    return {
        **base,
        "PYTHONPATH": os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)]),
        "HARNESS_PROFILE": "dev-ci",
        "HARNESS_FIXTURE_DIR": str(fixture_dir),
        "CONSOLE_PORT": "0",
        # A lease the dying process held must be reclaimable by the restart's sweep.
        "HARNESS_ORCH_LEASE_SECONDS": "1",
        "PYTHONUNBUFFERED": "1",
    }


def _spawn_console(data_dir: Path, toml_path: Path, env: dict[str, str],
                   tag: str) -> tuple[subprocess.Popen, int]:
    lines: list[str] = []
    stderr_file = (data_dir / f"{tag}.stderr").open("w+")
    process = subprocess.Popen(
        [sys.executable, "-m", "aeh", "console", "--data-dir", str(data_dir),
         "--config", str(toml_path)],
        stdout=subprocess.PIPE, stderr=stderr_file, text=True, env=env)

    def _pump() -> None:
        for line in process.stdout:
            lines.append(line.rstrip())

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()
    deadline = time.monotonic() + 90
    port = None
    while port is None:
        if process.poll() is not None:
            stderr_file.seek(0)
            pytest.fail(f"the {tag} console died at startup: {lines} / {stderr_file.read()[-800:]}")
        if time.monotonic() > deadline:
            pytest.fail(f"the {tag} console never announced a port: {lines}")
        match = re.search(r"console listening on port (\d+)", "\n".join(lines))
        if match:
            port = int(match.group(1))
        time.sleep(0.1)
    # The child's own stderr handle was dup'd at spawn; closing this copy does not affect it,
    # and the startup-diagnostics reads above are done.
    stderr_file.close()
    return process, port


def _post_start_run(port: int) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/actions/start-run",
        data=json.dumps({"run_id": RUN_ID}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _wait_for(predicate, timeout: float, message: str, poll_s: float = 0.5):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(poll_s)
    pytest.fail(f"{message} (last observation: {last!r}, waited {timeout}s)")


def test_res_19_console_sigkill_then_recover_rpo(tmp_path, monkeypatch, network_guard):
    monkeypatch.setenv("HARNESS_PROFILE", "dev-ci")
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(fixture_dir))
    toml_text = f_profiles_toml(top_level_profile="dev-ci")
    toml_path = tmp_path / "profiles.toml"
    toml_path.write_text(toml_text, encoding="utf-8")
    effective = effective_config(parse_config_document(toml_text, "toml"))

    # --- arm 1: the uninterrupted control, driven in-process through the same door ----------
    control_dir = tmp_path / "control"
    control_store = open_store(control_dir)
    try:
        seeded = seed_scored_run(
            control_store, cohort_id=COHORT_ID, run_id=RUN_ID, package_id=PACKAGE_ID,
            submissions=SUBMISSIONS, enumerate_units=True, config=effective)
        _run_id, thread = start_run_in_background(
            control_store, cohort_id=COHORT_ID,
            package_version_id=seeded.package_version_id, config=effective, run_id=RUN_ID)
        thread.join(timeout=RESTART_WAIT_S)
        assert not thread.is_alive(), "the control drive never finished"
    finally:
        control_store.close()
    done, total, status = _snapshot(control_dir)
    assert status == "complete" and done == total, f"control arm: {status} {done}/{total}"
    control = _projection(control_dir)

    # --- arm 2: the console killed mid-run, restarted, recovered ---------------------------
    killed_dir = tmp_path / "killed"
    killed_store = open_store(killed_dir)
    try:
        seed_scored_run(
            killed_store, cohort_id=COHORT_ID, run_id=RUN_ID, package_id=PACKAGE_ID,
            submissions=SUBMISSIONS, enumerate_units=True, config=effective)
    finally:
        killed_store.close()

    child_env = _child_env(fixture_dir)
    process, port = _spawn_console(killed_dir, toml_path, child_env, "first")
    try:
        with loopback_census(network_guard):
            outcome = _post_start_run(port)
        assert outcome.get("dispatched") is True, (
            f"RES-19: the console door did not dispatch the run: {outcome}"
        )

        # The kill lands KILL_AFTER_S of dispatch after the first observed completion.
        first_done_time = None
        deadline = time.monotonic() + RESTART_WAIT_S
        while time.monotonic() < deadline:
            done, total, status = _snapshot(killed_dir)
            if done:
                first_done_time = time.monotonic()
                break
            if process.poll() is not None:
                pytest.fail(f"the console died before any unit completed: {done}/{total}")
            time.sleep(0.2)
        assert first_done_time is not None, "no unit ever completed after the start-run POST"

        while time.monotonic() < first_done_time + KILL_AFTER_S:
            time.sleep(0.1)
            done, total, status = _snapshot(killed_dir)
        assert status == "running", (
            f"RES-19: the run must still be mid-flight at the kill (got {status!r})")
        assert 0 < done < total, (
            f"RES-19: the kill did not land mid-dispatch: {done}/{total} done")
    finally:
        process.kill()  # TerminateProcess on Windows: the honest SIGKILL equivalent
        process.wait(timeout=30)

    # The completed-id set is read AFTER the kill, not before: the store is sqlite and
    # survives TerminateProcess, so completions landing in the last instants before the
    # death — exactly the ones an RPO bound cares about most — sit inside the zero-loss set.
    pre_kill_ids = _done_ids(killed_dir)

    # The restart: recover runs before the socket accepts (FR-PIPE-09), the queued resume
    # picks the run up against its own frozen configuration, and it drives to complete.
    process, port = _spawn_console(killed_dir, toml_path, child_env, "second")
    try:
        _wait_for(
            lambda: _snapshot(killed_dir)[2] == "complete" and _grades_settled(killed_dir),
            RESTART_WAIT_S, "the restarted console never drove the run to a settled complete")
        done, total, status = _snapshot(killed_dir)
        assert done == total, f"RES-19: the recovered run did not finish: {done}/{total}"

        # RPO, zero-loss form: every completion observed before the kill survives it. The
        # observed completions span KILL_AFTER_S < RPO_S, so this bounds the loss at zero
        # where the plan's bound allows RPO_S.
        final_ids = _done_ids(killed_dir)
        lost = pre_kill_ids - final_ids
        assert not lost, (
            f"RES-19: {len(lost)} completed unit(s) observed within {KILL_AFTER_S}s of the "
            f"kill did not survive the restart — RPO {RPO_S}s of completed work was exceeded"
        )

        killed = _projection(killed_dir)
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()

    assert killed == control, (
        "RES-19: the recovered run's §4.3 projection differs from the uninterrupted run's "
        f"(NFR-PIPE-01): {[(k, len(control[k]), len(killed[k]))
                           for k in control if control[k] != killed[k]]}"
    )