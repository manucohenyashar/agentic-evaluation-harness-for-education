"""An uncontrolled kill mid-batch: every reopen recovers to the last committed batch.

Cases `TC-STORE-18` (`NFR-STORE-02`, P0, twenty repetitions) and `RES-03`, test plan §5.3
and §6.8. Issue #15 (TS-09).

Rung 2 — a real process is killed hard while a real writer thread is mid-commit, because the
promise is about what a reopen finds after an uncontrolled death: "recover to the last
committed batch with no corruption", at most one batch window lost. A `BaseException` inside
the process is the controlled shape `TC-STORE-08` walks; this case is the uncontrolled one —
`TerminateProcess` on Windows (`proc.kill()`), the same class of death as `SIGKILL`.

`Written ahead of implementation: yes` is stale — the queue landed with #11; the case runs
green by design.

The kill offsets are drawn from the suite's seeded `Random` (§4.6: per-test seeded, never a
module-global), so a failure in one repetition reproduces from `DEFAULT_SEED` alone.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from aeh.store import Statement, open_store

pytestmark = [pytest.mark.integration]

ISSUE = "#15"

REPO_SRC = Path(__file__).resolve().parents[3] / "src"

#: The child: enqueue `PAIRS` verdict+status pairs with frequent small batches, and stay
#: alive until killed. The parent kills it at a randomized offset mid-write. The child speaks
#: to `aeh.store` directly — it is a process under death sentence, not a test.
PAIRS = 240
CHILD = textwrap.dedent(
    """
    import os, sys, time
    from pathlib import Path
    sys.path.insert(0, os.environ["AEH_SRC"])
    from aeh.store import Statement, open_store
    # TC-STORE-25: the migration chains concatenate at import time, so a fresh process
    # imports every contributing module before the first open (#234) — the open site
    # refuses the truncated chain otherwise. `aeh.extract` owns Cohort's last migration.
    import aeh.det, aeh.extract, aeh.ingest, aeh.orch, aeh.pkg  # noqa: E401

    store = open_store(sys.argv[1])
    handle = store.cohort("c-kill")
    with handle.transaction() as tx:
        tx.execute(Statement(
            "CREATE TABLE verdict_kill "
            "(work_id TEXT NOT NULL PRIMARY KEY, band TEXT NOT NULL)"))
    verdict = Statement(
        "INSERT INTO verdict_kill (work_id, band) VALUES (:work_id, :band)")
    status = Statement(
        "INSERT INTO work_unit (work_id, submission_id, stage, status) "
        "VALUES (:work_id, NULL, 'judge', 'done')")
    Path(os.environ["READY"]).write_text("ready")
    for index in range(PAIRS):
        wid = "w-%04d" % index
        handle.enqueue_write(verdict, work_id=wid, band="b1")
        handle.enqueue_write(status, work_id=wid)
        time.sleep(0.002)
    time.sleep(60)  # alive until the parent kills it
    """
)

VERDICT_READ = "SELECT work_id FROM verdict_kill ORDER BY work_id"
STATUS_READ = (
    "SELECT work_unit.work_id FROM work_unit "
    "WHERE status = 'done' ORDER BY work_unit.work_id"
)


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["AEH_SRC"] = str(REPO_SRC)
    env["HARNESS_COMMIT_BATCH"] = "10"
    # Interval high: commits are batch-size-triggered only. A short interval would let a
    # child stall (sleep oversleep, GC) commit a *partial* batch — an even one breaks the
    # whole-batch assertion, an odd one the invariant itself, against a correct store.
    env["HARNESS_COMMIT_INTERVAL_MS"] = "60000"
    env["READY"] = ""  # replaced per repetition; see the test body
    return env


def test_tc_store_18_res_03_twenty_kills_every_reopen_recovers_to_a_whole_batch(
    tmp_data_dir, seeded_random, tmp_path_factory
):
    """`TC-STORE-18` — *"`SIGKILL` mid-batch, twenty repetitions at randomized offsets: every
    reopen recovers cleanly; at most one batch window of results lost; no corruption in any
    tier."* `RES-03` is the same run phrased as the promise.

    Oracle, per repetition: the reopen **opens** (no corruption), every `work_id` on the
    reopened file carries both its verdict and its `done` status or neither, and the committed
    pair count is a multiple of the 5-pair batch — the loss is a batch window, never a pair
    and never a torn page."""
    child = tmp_path_factory.mktemp("kill_child") / "kill_child.py"
    child.write_text(f"PAIRS = {PAIRS}\n" + CHILD, encoding="utf-8")
    repetitions = 20
    committed_counts = []
    for repetition in range(repetitions):
        data_dir = tmp_data_dir / f"rep-{repetition:02d}"
        data_dir.mkdir()
        env = _child_env()
        env["READY"] = str(data_dir / "ready")
        process = subprocess.Popen(
            [sys.executable, str(child), str(data_dir)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for the child to be mid-write before drawing the kill offset: an offset
        # measured from spawn would mostly land in interpreter startup, killing a process
        # that had not written anything — a repetition that asserts nothing.
        ready = data_dir / "ready"
        deadline = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), f"rep {repetition}: the child never reached its write loop"
        offset = seeded_random.uniform(0.005, 0.35)
        time.sleep(offset)
        process.kill()  # TerminateProcess on Windows — the SIGKILL class of death
        process.wait(timeout=30)

        # The reopen is the oracle: it opens or the tier is corrupt.
        store = open_store(data_dir)
        handle = store.cohort("c-kill")
        verdicts = {row[0] for row in handle.query(statement_read(VERDICT_READ))}
        done = {row[0] for row in handle.query(statement_read(STATUS_READ))}
        assert verdicts == done, (
            f"TC-STORE-18 (rep {repetition}, killed at {offset:.2f}s): the invariant broke "
            f"across the kill — verdicts without status {sorted(verdicts - done)[:3]}, "
            f"statuses without verdicts {sorted(done - verdicts)[:3]}. An uncontrolled kill "
            "recovered to a torn state, which is the corruption NFR-STORE-02 promises never "
            "happens."
        )
        assert len(verdicts) % 5 == 0, (
            f"TC-STORE-18 (rep {repetition}): {len(verdicts)} pairs survived a batch size of "
            "10 statements (5 pairs). The loss is a batch window — whole batches only."
        )
        committed_counts.append(len(verdicts))
        store.close()

    assert len(set(committed_counts)) >= 3, (
        f"TC-STORE-18: all 20 kills landed on {set(committed_counts)} — the offsets never "
        "reached a mid-write state, so the repetition asserts nothing. Widen the offset "
        "window or slow the writer."
    )


def statement_read(sql: str) -> Statement:
    return Statement(sql)

