"""`RES-18` (issue #147, TS-54) — process restart after an uncontrolled kill: RPO ≤ 5 s of
completed work, RTO ≤ 1 minute to resume. This is the E1 measurement. The E4 confirmation runs during
`PERF-10` (`docs/perf/PERF-10-release-gate.md`).

Test plan §6.8: *"RES-18 | NFR-SYS-02 | Process restart after an uncontrolled kill | Whole pipeline
| RPO ≤ 5 s of completed work; RTO ≤ 1 minute to resume | Measured on E1 and confirmed once on E4
during `PERF-10`"*. `NFR-SYS-02` adds: *"with no duplicated and no lost units"*.

**What this adds over the existing kill cases.** `TC-STORE-18`/`RES-03` kill a process writing raw
batches and check the reopen finds a whole batch. `TC-ORCH-04` checks that resume duplicates and
loses nothing, but models the kill as a store close and reopen inside one process. Neither measures
the two numbers `NFR-SYS-02` states, and neither kills a process that is working through a run's
ledger. This case does both, with real processes:

1. **The worker.** A child process opens the store, leases units from a started run, completes them
   one at a time, and prints `done <work_id> <time>` after each `complete()` returns. Each printed
   unit is completed work as the worker knows it.
2. **The kill.** Once the worker has been completing units for `KILL_AFTER_S` seconds (three RPO
   windows), the parent kills it with `TerminateProcess` on Windows (`proc.kill()`), the same class
   of death as `SIGKILL`, and notes the time. The worker is paced (`WORKER_PAUSE_S` between units),
   so the run is still mid-ledger at the kill. The kill waits on elapsed time, not a count, so the
   reported work spans more than one RPO window, and a loss older than 5 s is possible and so
   detectable. The span is asserted before RPO is judged. At present `complete()` commits in its own
   transaction, so zero loss is the expected result. The check exists to catch a batched commit path
   that would lose more.
3. **The restart.** A second child opens the same store, calls `Orchestrator.resume()` with no
   arguments (`FR-ORCH-02`), then `sweep_expired_leases()`, and leases its first unit. The sweep is
   part of the restart, not extra help: `resume()` re-enumerates but reclaims no leases, and the
   units the killed worker held stay leased until the sweeper runs. A fresh orchestrator's restored
   `LeaseClock` sits past every expiry ever issued, so the sweep reclaims them all. This is the same
   recovery sequence `TC-E2E-02`'s kill variants use. Without it, the leased units never finish.
   The time from process start to that first lease is the **RTO**. It includes interpreter start and imports, because a restart does too.
4. **RPO, from the ledger.** Read before the restart touches it: every unit the worker reported
   done more than `RPO_S` seconds before the kill must be `done`. A reported unit that is not done
   is lost work, and it is allowed only inside the last `RPO_S` seconds.
5. **No duplicated, no lost units.** The restarted worker drains the run. No unit already `done`
   in the ledger at restart is leased again, and at the end every enumerated unit is `done`.

Markers: `integration` and `slow` (two child processes, seconds of work). Environment E1. The number
is not evidence about E4, which is why `PERF-10` confirms it there.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from aeh.store import open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run
from tests.support.store_api import statement

pytestmark = [pytest.mark.integration, pytest.mark.slow]

ISSUE = "#147"
ENVIRONMENT = "E1"
REPO_ROOT = Path(__file__).resolve().parents[2]

#: `NFR-SYS-02`: at most 5 seconds of completed work lost.
RPO_S = 5.0
#: `NFR-SYS-02`: a run resumes within one minute of process restart.
RTO_S = 60.0
#: Seconds of completions before the kill: three RPO windows, so an old loss is detectable.
KILL_AFTER_S = 3 * RPO_S
#: The worker's pause between units, so 1,500 units outlast the kill with room to spare.
WORKER_PAUSE_S = float(os.environ.get("HARNESS_RES_18_WORKER_PAUSE_S", "0.01"))
SUBMISSIONS = tuple(f"S{i:03d}" for i in range(1, 61))
CRITERIA = tuple(
    [{"criterion_id": f"C{i:02d}", "kind": "open", "scoring_model": "holistic"} for i in range(1, 7)]
    + [{"criterion_id": "MCQ", "kind": "mcq", "scoring_model": "deterministic"}]
)

_IMPORTS = (
    "import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge\n"
    "import aeh.orch, aeh.pkg, aeh.review, aeh.synth\n"
)

_WORKER = _IMPORTS + textwrap.dedent("""
    import sys, time
    from aeh.orch import Orchestrator
    from aeh.store import open_store
    store = open_store(sys.argv[1])
    orchestrator = Orchestrator(store)
    print("ready", flush=True)
    while True:
        leased = False
        for stage in ("deterministic", "extract", "score"):
            for unit in orchestrator.lease("w-before-kill", stage, 8):
                leased = True
                orchestrator.complete(unit.work_id)
                print(f"done {unit.work_id} {time.time():.6f}", flush=True)
                time.sleep(float(sys.argv[2]))
        if not leased:
            time.sleep(0.05)
""")

_RESTARTED = _IMPORTS + textwrap.dedent("""
    import sys, time
    from aeh.orch import Orchestrator
    from aeh.store import open_store
    store = open_store(sys.argv[1])
    orchestrator = Orchestrator(store)
    orchestrator.resume()
    orchestrator.sweep_expired_leases()
    first = None
    while first is None:
        for stage in ("deterministic", "extract", "score"):
            batch = orchestrator.lease("w-after-restart", stage, 1)
            if batch:
                first = batch
                break
    print(f"resumed {time.time():.6f}", flush=True)
    pending = list(first)
    while pending:
        for unit in pending:
            print(f"leased {unit.work_id}", flush=True)
            orchestrator.complete(unit.work_id)
        pending = []
        for stage in ("deterministic", "extract", "score"):
            pending.extend(orchestrator.lease("w-after-restart", stage, 64))
    print("drained", flush=True)
    store.close()
""")


def _child(script: str, data_dir: Path, *args: str) -> subprocess.Popen:
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)]))
    # stderr goes to a file: a pipe nobody drains can fill and block the child.
    stderr = open(data_dir.parent / f"res18-{len(args)}-{time.time_ns()}.err", "w+")
    return subprocess.Popen([sys.executable, "-c", script, str(data_dir), *args],
                            stdout=subprocess.PIPE, stderr=stderr, text=True, env=env)


def _stderr(proc: subprocess.Popen) -> str:
    proc.stderr.seek(0)
    return proc.stderr.read()[-800:]


def _read_lines(proc: subprocess.Popen, sink: list[str]) -> threading.Thread:
    def pump():
        for line in proc.stdout:
            sink.append(line.strip())
    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    return thread


def _statuses(data_dir: Path, run_id: str) -> dict[str, str]:
    store = open_store(data_dir)
    try:
        rows = store.cohort(ORCH_COHORT_ID).query(statement(
            "SELECT work_id, status FROM work_unit WHERE run_id = :r", issue=ISSUE), r=run_id)
        return {row["work_id"]: row["status"] for row in rows}
    finally:
        store.close()


def test_res_18_a_killed_worker_loses_under_five_seconds_of_work_and_resumes_within_a_minute(
    tmp_data_dir, network_guard
):
    """`RES-18` on E1: kill a worker mid-run, restart, and measure RPO and RTO against
    `NFR-SYS-02`, with no duplicated and no lost units after the drain."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _version = seed_run(store, submissions=SUBMISSIONS, criteria=CRITERIA)
        enumerated = orchestrator.enumerate_units(run_id).units_enumerated
        assert orchestrator.start(run_id) == "running"
    finally:
        store.close()
    worker_lines: list[str] = []
    worker = _child(_WORKER, tmp_data_dir, str(WORKER_PAUSE_S))
    _read_lines(worker, worker_lines)
    deadline = time.time() + 120
    first_done = None
    while first_done is None or time.time() - first_done < KILL_AFTER_S:
        if first_done is None and any(line.startswith("done ") for line in worker_lines):
            first_done = time.time()
        if worker.poll() is not None or time.time() > deadline:
            pytest.fail(f"fixture: the worker stopped before {KILL_AFTER_S:.0f}s of completions: "
                        f"{_stderr(worker)!r}")
        time.sleep(0.01)
    worker.kill()
    killed_at = time.time()
    worker.wait(timeout=30)
    assert worker.returncode is not None

    reported = {}
    for line in list(worker_lines):
        if line.startswith("done "):
            _, work_id, stamp = line.split()
            reported[work_id] = float(stamp)
    at_restart = _statuses(tmp_data_dir, run_id)
    span = max(reported.values()) - min(reported.values()) if reported else 0.0
    assert span > RPO_S and len(reported) < enumerated, (
        f"fixture: the reported work spans {span:.2f}s over {len(reported)} of {enumerated} units. "
        f"RPO is only measurable when completions span more than {RPO_S:.0f}s and the run is "
        f"still mid-ledger at the kill"
    )

    restarted_lines: list[str] = []
    restart_started = time.time()
    restarted = _child(_RESTARTED, tmp_data_dir)
    pump = _read_lines(restarted, restarted_lines)
    try:
        restarted.wait(timeout=600)
    finally:
        if restarted.poll() is None:
            restarted.kill()
    pump.join(timeout=10)
    resumed = [float(line.split()[1]) for line in restarted_lines if line.startswith("resumed ")]
    releases = [line.split()[1] for line in restarted_lines if line.startswith("leased ")]
    final = _statuses(tmp_data_dir, run_id)

    rto = resumed[0] - restart_started if resumed else None
    lost = {w: t for w, t in reported.items() if at_restart.get(w) != "done"}
    oldest_lost = killed_at - min(lost.values()) if lost else 0.0
    already_done = {w for w, s in at_restart.items() if s == "done"}
    report = (
        f"RES-18 on {ENVIRONMENT} (not evidence about E4): {len(reported)} units reported done "
        f"before the kill, {len(already_done)} done in the ledger at restart, {len(lost)} reported "
        f"but not committed (oldest {oldest_lost:.2f}s before the kill); RTO "
        f"{'none' if rto is None else f'{rto:.2f}s'}; {len(releases)} units leased after restart; "
        f"final {sum(s == 'done' for s in final.values())}/{enumerated} done"
    )
    print(report)

    assert "drained" in restarted_lines, (
        f"the restarted worker did not drain the run: {_stderr(restarted)!r}. {report}"
    )
    problems = []
    if rto is None or rto > RTO_S:
        problems.append(f"the run did not resume within {RTO_S:.0f}s of process restart")
    if oldest_lost > RPO_S:
        problems.append(f"completed work reported {oldest_lost:.2f}s before the kill was lost; "
                        f"NFR-SYS-02 allows at most {RPO_S:.0f}s")
    duplicated = sorted(already_done & set(releases))
    if duplicated:
        problems.append(f"{len(duplicated)} unit(s) already done at restart were leased again "
                        f"(first {duplicated[:3]}): duplicated work")
    if len(releases) != len(set(releases)):
        problems.append("the restarted worker leased a unit twice")
    not_done = sorted(w for w, s in final.items() if s != "done")
    if not_done or len(final) != enumerated:
        problems.append(f"{len(not_done)} of {enumerated} units are not done after the drain "
                        f"(first {not_done[:3]}): lost work")
    assert not problems, "\n".join(problems) + f"\n{report}"
