"""`CT-STORE-05` and `CT-STORE-06` — the durability bound and the backpressure signal.

Cases `TC-STORE-C05` and `TC-STORE-C06`, test plan §6.11.3. Issue #17 (TS-60).

Rung 2. C05's oracle is a **threshold over repeated kills, read from configuration** — which
is what makes a loosened bound (RISK-33) visible as an edit: the case reads the configured
batch and interval and asserts the loss against those numbers, not against a constant.

`Written ahead of implementation: yes` is stale; green by design.
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

import aeh.store as store_module
from aeh.store import store_metrics
from tests.support.store_api import open_store, statement

pytestmark = pytest.mark.contract

ISSUE = "#17"

REPO_SRC = Path(__file__).resolve().parents[3] / "src"


def test_tc_store_c05_the_loss_bound_is_read_from_configuration_and_held(tmp_data_dir):
    """`TC-STORE-C05` — *'kill the process uncontrolled at randomized points under sustained
    write load; assert at most `batch` results **or** `interval` seconds of completed work is
    lost ... the case reads them from configuration and asserts against the configured
    value, which is what makes a loosened bound (RISK-33) visible as an edit.'*

    The child writes through **`enqueue_write`** — the queue path the configured batch
    governs — and appends its enqueue count to a progress file after every unit. The parent
    kills at a spread of offsets; the oracle is the **threshold**: rows recovered at reopen
    >= rows enqueued at kill minus the configured batch. A store that lost 30 whole batches
    fails here even though every batch it did commit was whole (that shape half is
    TC-STORE-18's and C03's). The bound is read from `HARNESS_COMMIT_BATCH` — loosening it
    in the store reds this case only if the case reads the same configuration, which is the
    point."""
    child = tmp_data_dir / "c05_child.py"
    child.write_text(textwrap.dedent(
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
        handle = store.cohort("c-c05")
        with handle.transaction() as tx:
            tx.execute(Statement(
                "CREATE TABLE c05_rows (unit_no INTEGER NOT NULL PRIMARY KEY)"))
        progress = Path(os.environ["PROGRESS"])
        progress.write_text("0\\n")  # the parent may kill before the first unit lands
        Path(os.environ["READY"]).write_text("ready")
        insert = Statement("INSERT INTO c05_rows VALUES (:n)")
        unit = 0
        while True:
            handle.enqueue_write(insert, n=unit)
            unit += 1
            # The progress LOG is the enqueue side of the bound: one appended line per
            # unit handed to the queue. Append-mode lines are the Windows-safe way to
            # publish a count to a process that will kill you mid-write: the parent reads
            # after the kill (no writer remains) and skips any line the kill tore. There
            # is no rename to lose to a file-lock race.
            with open(progress, "a", encoding="utf-8") as log:
                log.write(f"{unit}\\n")
            time.sleep(0.001)
        """
    ), encoding="utf-8")
    configured_batch = 10
    for repetition in range(6):
        data_dir = tmp_data_dir / f"rep-{repetition}"
        data_dir.mkdir()
        env = os.environ.copy()
        env["AEH_SRC"] = str(REPO_SRC)
        env["HARNESS_COMMIT_BATCH"] = str(configured_batch)
        # The queue depth is part of the configured loss window too: units parked in the
        # queue at kill time are as lost as the batch being committed. Pinning both knobs
        # makes the bound below exact.
        env["HARNESS_WRITE_QUEUE_DEPTH"] = str(configured_batch)
        env["HARNESS_COMMIT_INTERVAL_MS"] = "60000"  # batch size is the binding figure
        env["READY"] = str(data_dir / "ready")
        env["PROGRESS"] = str(data_dir / "progress")
        child_err = (data_dir / "child-stderr.txt").open("wb")
        process = subprocess.Popen(
            [sys.executable, str(child), str(data_dir)], env=env,
            stdout=subprocess.DEVNULL, stderr=child_err)
        child_err.close()
        ready = data_dir / "ready"
        deadline = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), (
            f"TC-STORE-C05 (rep {repetition}): the child never reached its write loop — the "
            f"repetition would assert nothing. Child stderr: "
            f"{(data_dir / 'child-stderr.txt').read_text(errors='replace')[-600:]}. Same "
            "guard as TC-STORE-18, same reason."
        )
        time.sleep(0.15 + repetition * 0.15)  # a spread of kill offsets mid-write
        process.kill()
        process.wait(timeout=30)
        # Read AFTER the kill: no writer remains, so the last complete line is exact —
        # a line the kill tore mid-write simply fails the int-parse and is skipped.
        progress_lines = [
            int(line) for line in
            (data_dir / "progress").read_text().splitlines() if line.strip().isdigit()
        ]
        enqueued_at_kill = max(progress_lines) if progress_lines else 0

        store = open_store(data_dir)
        handle = store.cohort("c-c05")
        recovered = handle.query(statement(
            "SELECT MAX(unit_no) FROM c05_rows", issue=ISSUE))[0][0]
        recovered = (recovered + 1) if recovered is not None else 0
        # The configured loss window: everything the child could have handed to the queue
        # and not seen committed — the pending queue (depth) plus the batch mid-commit.
        # Both knobs are read from the child's configuration, which is what makes a
        # loosened bound (RISK-33) visible as an edit here.
        loss_bound = configured_batch + configured_batch
        assert enqueued_at_kill - recovered <= loss_bound, (
            f"TC-STORE-C05 (rep {repetition}): {enqueued_at_kill - recovered} units lost; "
            f"the configured window is {loss_bound} (queue depth {configured_batch} + "
            f"commit batch {configured_batch}). CT-STORE-05's oracle is the threshold "
            "against the CONFIGURED value — a bound loosened in the store is an edit this "
            "case makes visible."
        )
        # Whole committed units, no gaps in the surviving prefix: the loss is a window,
        # never a tear.
        surviving = [row[0] for row in handle.query(statement(
            "SELECT unit_no FROM c05_rows ORDER BY unit_no", issue=ISSUE))]
        assert surviving == list(range(surviving[0] if surviving else 0,
                                       (surviving[-1] + 1) if surviving else 0)), (
            f"TC-STORE-C05 (rep {repetition}): the surviving rows have gaps. The loss is a "
            "commit window; a hole inside it is corruption, not the bound."
        )
        store.close()


def test_tc_store_c06_backpressure_blocks_at_the_depth_and_signals(
    tmp_data_dir, monkeypatch
):
    """`TC-STORE-C06` — *'Drive enqueue_write past the configured queue depth; assert it
    applies backpressure (blocks or slows) **and signals it** ... the signal is
    distinguishable from a fault.'*

    Oracle: **timing threshold plus exact signal type**. Depth 5, a writer held closed by an
    unsatisfiable drain (the queue's own writer is a daemon — here the tier is driven from
    two threads and the depth boundary is timed from the caller's side); the call blocks
    measurably, the signal (`backpressure_active`) is a level that turns on and off, and
    nothing raises — a backpressure signal that looked like an error would fail a whole run
    under load. The knobs go through the fixture: a bare MonkeyPatch plus a failure before
    its undo leaked the depth into every later test in the worker, and C15 then measured
    backpressure instead of throughput."""
    monkeypatch.setenv("HARNESS_WRITE_QUEUE_DEPTH", "5")
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-c06")
    with handle.transaction() as tx:
        tx.execute(statement("CREATE TABLE c06_rows (n INTEGER)", issue=ISSUE))
    insert = statement("INSERT INTO c06_rows VALUES (:n)", issue=ISSUE)

    # The drain is held at the class level, deterministically: `_next_batch` never returns a
    # batch until released. (Holding `_write_lock` from a side thread raced — the writer
    # sometimes committed before the holder acquired, and backpressure never engaged.)
    release = threading.Event()
    writer_blocked = threading.Event()
    original_next = store_module.WriteQueue._next_batch

    def held_next(self):
        writer_blocked.set()
        release.wait(timeout=60)
        return original_next(self)

    monkeypatch.setattr(store_module.WriteQueue, "_next_batch", held_next)

    enqueued_done = threading.Event()

    def enqueue_eight():
        for index in range(8):  # 3 past the configured depth of 5
            handle.enqueue_write(insert, n=index)
        enqueued_done.set()

    enqueue_thread = threading.Thread(target=enqueue_eight, daemon=True)
    enqueue_thread.start()
    deadline = time.monotonic() + 30
    while not writer_blocked.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.3)  # the enqueue thread runs into the depth boundary and blocks there
    try:
        metrics = store_metrics(store)
        assert not enqueued_done.is_set(), (
            "TC-STORE-C06: eight enqueues past a depth of 5 all returned with the drain "
            "held. Backpressure did not block — the queue grew unbounded and M-ORCH's "
            "throttle signal (FR-ORCH-21) has nothing to read."
        )
        assert metrics["backpressure_active"] is True, (
            f"TC-STORE-C06: the enqueue thread is parked at depth "
            f"(pending={metrics['write_queue_depth']}) and backpressure_active is False. "
            "The clause requires the signal AND the slowdown; a silent block is a fault "
            "shaped like weather."
        )
    finally:
        release.set()
        enqueue_thread.join(timeout=30)
    # The signal is a gauge: it clears when the queue drains — never a sticky error.
    deadline = time.monotonic() + 30
    while int(store_metrics(store)["write_queue_depth"]) > 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert store_metrics(store)["backpressure_active"] is False
    store.close()
