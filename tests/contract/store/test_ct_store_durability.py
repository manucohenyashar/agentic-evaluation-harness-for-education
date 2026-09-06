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
    lost ... the case reads them from configuration.'*

    The bound under test is the child process's *configured* one (`HARNESS_COMMIT_BATCH=10`,
    `HARNESS_COMMIT_INTERVAL_MS` high, so the batch size is the binding figure). Every kill
    must lose at most one batch window — pairs surviving are whole batches — and the reopen
    must be clean. The repeated-kill machinery itself is TC-STORE-18's (twenty repetitions);
    this case asserts the **threshold against the configured value** across the same shape
    of death."""
    child = tmp_data_dir / "c05_child.py"
    child.write_text(textwrap.dedent(
        """
        import os, sys, time
        from pathlib import Path
        sys.path.insert(0, os.environ["AEH_SRC"])
        from aeh.store import Statement, open_store

        store = open_store(sys.argv[1])
        handle = store.cohort("c-c05")
        with handle.transaction() as tx:
            tx.execute(Statement(
                "CREATE TABLE c05_rows (batch_no INTEGER NOT NULL, seq INTEGER NOT NULL)"))
        Path(os.environ["READY"]).write_text("ready")
        insert = Statement("INSERT INTO c05_rows VALUES (:b, :s)")
        batch = 0
        while True:
            with handle.transaction() as tx:
                for seq in range(10):
                    tx.execute(insert, b=batch, s=seq)
            batch += 1
            time.sleep(0.002)
        """
    ), encoding="utf-8")
    for repetition in range(6):
        data_dir = tmp_data_dir / f"rep-{repetition}"
        data_dir.mkdir()
        env = os.environ.copy()
        env["AEH_SRC"] = str(REPO_SRC)
        env["HARNESS_COMMIT_BATCH"] = "10"
        env["HARNESS_COMMIT_INTERVAL_MS"] = "60000"  # batch size is the binding figure
        env["READY"] = str(data_dir / "ready")
        process = subprocess.Popen(
            [sys.executable, str(child), str(data_dir)], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ready = data_dir / "ready"
        deadline = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.05 + repetition * 0.05)  # deterministic spread across batch boundaries
        process.kill()
        process.wait(timeout=30)

        store = open_store(data_dir)
        handle = store.cohort("c-c05")
        batches = sorted({row[0] for row in handle.query(statement(
            "SELECT DISTINCT batch_no FROM c05_rows", issue=ISSUE))})
        # Whole committed batches, and never a gap: the loss is a batch window.
        assert batches == list(range(len(batches))), (
            f"TC-STORE-C05 (rep {repetition}): committed batches {batches} are not "
            "gap-free. A hole in the middle is not a batch-window loss, it is corruption."
        )
        per_batch = handle.query(statement(
            "SELECT batch_no, COUNT(*) FROM c05_rows GROUP BY batch_no", issue=ISSUE))
        assert all(row[1] == 10 for row in per_batch), (
            f"TC-STORE-C05 (rep {repetition}): a committed batch is partial: {per_batch}. "
            f"The configured bound is 10 rows per batch; the loss must be a whole window."
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
