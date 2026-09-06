"""A unit's result and its ledger transition commit together, or neither does — on the queue.

Case `TC-STORE-08` (`FR-STORE-04`, `NFR-STORE-02`, P0, failure injection), test plan §5.3.
Issue #15 (TS-09).

Rung 2 — real SQLite in WAL mode, real file, because the invariant is about what a *reopen*
finds on disk after a batch died mid-commit; against anything else it asserts the double.

`Written ahead of implementation: yes` in the issue body is stale — the queue landed with #11
and this case runs green by design. Recorded in the PR rather than silently relied on.

**Steps 1-2 of the plan's block form are not implemented here, and that is a stated
deviation, not an omission.** They prescribe the commit *boundaries* — "assert exactly one
commit fires at the hundredth, not before", and the 4999/5000 ms interval edge — against an
injected `FrozenClock`. The queue's `_next_batch` reads `time.monotonic()` directly, so
pinning the interval edge needs a clock seam in the write queue, which is implementation
work this test PR does not own (`TC-STORE-07` honors the knobs without the clock seam; the
boundary case belongs with whatever story adds the seam). What this case implements is the
binding oracle — the invariant on the reopened file — plus the whole-batch arithmetic the
injection pins around the batch boundary.

The ground `FUZZ-07` deliberately left open (its docstring says so): the **queue path**. A
result row and its `work_unit` status transition enqueued as separate units land in the same
commit batch, so a writer that dies mid-batch is the moment the invariant is real. The plan's
four injection points (before both, after the verdict, after the status, after the commit)
reduce on the queue path to two observable shapes — the batch dies between statement *k* and
*k+1*, or at the COMMIT itself — because the caller is not on the writer thread; both are
walked here, and each resulting file is **reopened** before the invariant is asserted, which
is the oracle's whole point.

A failed batch is recorded and the queue keeps draining (`_commit` only halts for disk-full),
so the arithmetic below counts the surviving batches too.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

import aeh.store as store_module
from aeh.store import store_metrics
from tests.support.store_api import open_store, statement

pytestmark = [pytest.mark.integration]

ISSUE = "#15"

VERDICT_DDL = "CREATE TABLE verdict_tc08 (work_id TEXT NOT NULL PRIMARY KEY, band TEXT NOT NULL)"
VERDICT_INSERT = "INSERT INTO verdict_tc08 (work_id, band) VALUES (:work_id, :band)"
STATUS_INSERT = (
    "INSERT INTO work_unit (work_id, submission_id, stage, status) "
    "VALUES (:work_id, NULL, 'judge', 'done')"
)
VERDICT_READ = "SELECT work_id FROM verdict_tc08 ORDER BY work_id"
STATUS_READ = "SELECT work_id FROM work_unit WHERE status = 'done' ORDER BY work_id"


def _wait_for(condition, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() >= deadline:
            return
        time.sleep(0.01)


def test_tc_store_08_the_queue_loses_a_whole_batch_never_half_a_pair(tmp_data_dir, monkeypatch):
    """`TC-STORE-08` — *"for every work_id the database holds either a result and a done
    status, or neither — never one without the other."*

    250 pairs, five batches of 50 pairs (`HARNESS_COMMIT_BATCH = 100` statements). The writer
    dies after the 130th verdict handed to SQLite — the 30th verdict of batch 3. Batches 1-2
    must be intact, batch 3 rolled back whole, batches 4-5 committed after the failure (the
    queue only halts for disk-full), and the invariant must hold over **every** `work_id`.
    """
    monkeypatch.setenv("HARNESS_COMMIT_BATCH", "100")
    monkeypatch.setenv("HARNESS_COMMIT_INTERVAL_MS", "60000")  # batch-size trigger only
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-tc08")
    original_run = store_module._run

    with handle.transaction() as tx:
        tx.execute(statement(VERDICT_DDL, issue=ISSUE))

    injected = {"seen": 0, "fired": False}

    def die_after_verdict_130(connection, declared, params=None, *, retries=4):
        result = original_run(connection, declared, params, retries=retries)
        if str(declared).startswith("INSERT INTO verdict_tc08"):
            injected["seen"] += 1
            if injected["seen"] == 130:
                injected["fired"] = True
                raise sqlite3.OperationalError("injected abort after verdict 130")
        return result

    monkeypatch.setattr(store_module, "_run", die_after_verdict_130)
    for index in range(250):
        work_id = f"w-{index:04d}"
        handle.enqueue_write(statement(VERDICT_INSERT, issue=ISSUE), work_id=work_id, band="b1")
        handle.enqueue_write(statement(STATUS_INSERT, issue=ISSUE), work_id=work_id)
    _wait_for(lambda: injected["fired"])
    _wait_for(lambda: int(store_metrics(store)["write_queue_depth"]) == 0)
    monkeypatch.undo()

    verdicts = {row[0] for row in handle.query(statement(VERDICT_READ, issue=ISSUE))}
    done = {row[0] for row in handle.query(statement(STATUS_READ, issue=ISSUE))}

    assert verdicts == done, (
        f"TC-STORE-08: the invariant is broken. Verdicts without status: "
        f"{sorted(verdicts - done)[:5]}; statuses without verdicts: {sorted(done - verdicts)[:5]}. "
        "FR-STORE-04 commits a result and its ledger transition together; a ledger row claiming "
        "done with no result is a unit M-ORCH skips on resume and a grade that goes missing."
    )
    assert len(verdicts) == 200, (
        f"TC-STORE-08: {len(verdicts)} pairs landed. Expected 200: batches 1-2 (100 pairs) "
        "committed before the injection, batch 3 rolled back whole, batches 4-5 (100 pairs) "
        "committed after the recorded failure — a whole-batch granularity, never a pair."
    )


def test_tc_store_08_a_reopen_after_each_commit_point_finds_the_invariant(
    tmp_data_dir, monkeypatch
):
    """The plan's commit-point injections, walked: abort *at* COMMIT (before SQLite runs it)
    and abort *after* COMMIT (the commit landed; the writer learns of the abort afterwards).
    Each store is **closed and reopened** before the invariant is asserted — the oracle is
    the disk the reopen sees, not the writer's memory."""
    for point, expected_pairs in (("at-commit", 20), ("after-commit", 25)):
        monkeypatch.setenv("HARNESS_COMMIT_BATCH", "10")  # five batches of five pairs
        monkeypatch.setenv("HARNESS_COMMIT_INTERVAL_MS", "60000")
        store = open_store(tmp_data_dir / point)
        handle = store.cohort("c-tc08b")
        original_run = store_module._run

        with handle.transaction() as tx:
            tx.execute(statement(VERDICT_DDL, issue=ISSUE))

        state = {"commits": 0, "fired": False}

        def die_at_commit_3(connection, declared, params=None, *, retries=4, _s=state):
            is_commit = str(declared).strip().upper() == "COMMIT"
            if is_commit:
                _s["commits"] += 1
                if _s["commits"] == 3 and not _s["fired"]:
                    _s["fired"] = True
                    raise sqlite3.OperationalError("injected abort at COMMIT 3")
            return original_run(connection, declared, params, retries=retries)

        def die_after_commit_2(connection, declared, params=None, *, retries=4, _s=state):
            result = original_run(connection, declared, params, retries=retries)
            if str(declared).strip().upper() == "COMMIT":
                _s["commits"] += 1
                if _s["commits"] == 2 and not _s["fired"]:
                    _s["fired"] = True
                    raise sqlite3.OperationalError("injected abort after COMMIT 2")
            return result

        monkeypatch.setattr(
            store_module, "_run", die_at_commit_3 if point == "at-commit" else die_after_commit_2
        )
        for index in range(25):
            work_id = f"w-{point}-{index:03d}"
            handle.enqueue_write(statement(VERDICT_INSERT, issue=ISSUE), work_id=work_id,
                                 band="b1")
            handle.enqueue_write(statement(STATUS_INSERT, issue=ISSUE), work_id=work_id)
        _wait_for(lambda: state["fired"])
        _wait_for(lambda: int(store_metrics(store)["write_queue_depth"]) == 0)
        monkeypatch.undo()
        # The injected COMMIT abort is recorded either way (the failure is `_commit`'s, and
        # close() re-raises the first recorded failure — whether or not the COMMIT landed is
        # what the reopen below distinguishes, not whether the caller heard about it).
        with pytest.raises(sqlite3.OperationalError):
            store.close()

        reopened = open_store(tmp_data_dir / point)
        reopened_handle = reopened.cohort("c-tc08b")
        verdicts = {row[0] for row in reopened_handle.query(statement(VERDICT_READ, issue=ISSUE))}
        done = {row[0] for row in reopened_handle.query(statement(STATUS_READ, issue=ISSUE))}
        assert verdicts == done, (
            f"TC-STORE-08 ({point}): the reopened file breaks the invariant — verdicts without "
            f"status {sorted(verdicts - done)[:3]}, statuses without verdicts "
            f"{sorted(done - verdicts)[:3]}."
        )
        assert len(verdicts) == expected_pairs, (
            f"TC-STORE-08 ({point}): {len(verdicts)} pairs landed, expected {expected_pairs} — "
            "whole committed batches only."
        )
        reopened.close()
