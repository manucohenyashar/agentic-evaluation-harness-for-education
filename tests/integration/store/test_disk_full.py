"""Out of disk space: the ledger stays truthful, the queue refuses, the process halts.

Cases `TC-STORE-13` (`FR-STORE-10`, P0) and `RES-01` (§6.8), test plan §5.3 and §6.8.
Issue #15 (TS-09).

Rung 1-2 — real SQLite, injected failure. The plan says "Injected `ENOSPC` during an active
batch"; the injection is a `sqlite3.OperationalError("database or disk is full")` raised from
the module's single execute site at a chosen statement — the same face SQLite shows when the
disk really is full (`_as_disk_full`'s message check exists for exactly that wording), and
the one a CI box can reproduce without filling an actual disk. The real-disk face is test
plan §7.4's accepted residual ("Injected, not induced; not reproducible in CI").

**Written against the declared semantics.** The design sentence "outstanding ledger status
transitions commit, then the process halts" admits two readings; the #13 PR and the module's
decision table declare the safe one, and this case pins it: the interrupted batch is rolled
back **whole** (results and their paired status transitions together — committing the batch's
status-only units after the rollback would manufacture status-without-result states and break
the either-both-or-neither invariant `TC-STORE-08` pins), the queue terminally refuses, and
the process halts via the injectable hook. The ledger stands at its last commit, which is
resumable; the loss is `CT-STORE-05`'s one-batch window, not a new one.
"""

from __future__ import annotations

import sqlite3

import pytest

import aeh.store as store_module
from aeh.store import DiskFullError, store_metrics
from tests.support.store_api import open_store, statement

pytestmark = [pytest.mark.integration]

ISSUE = "#15"

VERDICT_DDL = "CREATE TABLE verdict_tc13 (work_id TEXT NOT NULL PRIMARY KEY, band TEXT NOT NULL)"
VERDICT_INSERT = "INSERT INTO verdict_tc13 (work_id, band) VALUES (:work_id, :band)"
STATUS_INSERT = (
    "INSERT INTO work_unit (work_id, submission_id, stage, status) "
    "VALUES (:work_id, NULL, 'judge', 'done')"
)
VERDICT_READ = "SELECT work_id FROM verdict_tc13 ORDER BY work_id"
STATUS_READ = "SELECT work_id FROM work_unit WHERE status = 'done' ORDER BY work_id"


def _saturate(handle) -> None:
    with handle.transaction() as tx:
        tx.execute(statement(VERDICT_DDL, issue=ISSUE))


def test_tc_store_13_disk_full_rolls_the_batch_whole_breaks_the_queue_and_halts(
    tmp_data_dir, monkeypatch
):
    """`TC-STORE-13` — *"Outstanding ledger status transitions commit, then the process halts;
    no result rows without transitions; the ledger remains resumable."* — written against the
    declared semantics: rollback to the last commit, then halt.

    The halt hook is captured instead of ending the interpreter, which is what makes the
    rest of the assertions possible: the error it receives is `DiskFullError` with the
    original chained, the queue refuses everything afterwards (`CT-STORE-11`: not retryable),
    and the **reopened** file shows whole batches only — no pair split, nothing half-written.
    """
    monkeypatch.setenv("HARNESS_COMMIT_BATCH", "10")
    monkeypatch.setenv("HARNESS_COMMIT_INTERVAL_MS", "60000")
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-tc13")
    original_run = store_module._run
    _saturate(handle)

    halted = []
    monkeypatch.setattr(store_module, "_halt_process_on_disk_full", halted.append)

    state = {"verdicts": 0, "fired": False}

    def full_at_verdict_23(connection, declared, params=None, *, retries=4):
        result = original_run(connection, declared, params, retries=retries)
        if str(declared).startswith("INSERT INTO verdict_tc13"):
            state["verdicts"] += 1
            if state["verdicts"] == 23 and not state["fired"]:
                state["fired"] = True
                raise sqlite3.OperationalError("database or disk is full")
        return result

    monkeypatch.setattr(store_module, "_run", full_at_verdict_23)
    for index in range(40):
        work_id = f"w-{index:03d}"
        handle.enqueue_write(statement(VERDICT_INSERT, issue=ISSUE), work_id=work_id, band="b1")
        handle.enqueue_write(statement(STATUS_INSERT, issue=ISSUE), work_id=work_id)
    deadline = __import__("time").monotonic() + 30
    while not halted and __import__("time").monotonic() < deadline:
        __import__("time").sleep(0.01)
    monkeypatch.undo()

    # The halt: exact type, original chained, and it ran through the module's one hook.
    assert halted, "TC-STORE-13: the process did not halt — FR-STORE-10's halt never ran"
    halt_error = halted[0]
    assert isinstance(halt_error, DiskFullError)
    assert isinstance(halt_error.__cause__, sqlite3.OperationalError)

    # The terminal refusal: not retryable by the caller (CT-STORE-11).
    with pytest.raises(DiskFullError):
        handle.enqueue_write(statement(VERDICT_INSERT, issue=ISSUE), work_id="w-after", band="b1")
    with pytest.raises(DiskFullError):
        with handle.transaction() as tx:
            tx.execute(statement(VERDICT_INSERT, issue=ISSUE), work_id="w-after", band="b1")

    # The failure is visible to observability — on the store whose queue carries it.
    assert store_metrics(store)["write_failures"] >= 1, (
        "TC-STORE-13: the store reports no write failure. The halt that is invisible to "
        "observability is a halt an operator cannot diagnose."
    )

    # The ledger, on the reopened file: whole batches, no split pair, resumable.
    monkeypatch.undo()
    # close() re-raises the first recorded failure — the DiskFullError the queue carries.
    with pytest.raises(DiskFullError):
        store.close()
    reopened = open_store(tmp_data_dir)
    reopened_handle = reopened.cohort("c-tc13")
    verdicts = {row[0] for row in reopened_handle.query(statement(VERDICT_READ, issue=ISSUE))}
    done = {row[0] for row in reopened_handle.query(statement(STATUS_READ, issue=ISSUE))}
    assert verdicts == done, (
        f"TC-STORE-13: the reopened ledger breaks the invariant — verdicts without status "
        f"{sorted(verdicts - done)[:3]}, statuses without verdicts {sorted(done - verdicts)[:3]}. "
        "The batch rolled back whole, or nothing did; the one shape FR-STORE-10 forbids is a "
        "half-written ledger pretending the run can continue."
    )
    assert len(verdicts) in (20, 30), (
        f"TC-STORE-13: {len(verdicts)} pairs landed. The batch that hit the full disk rolls "
        "back whole: whatever was committed before it stays, whatever comes after it never "
        "runs (the queue is broken) — a multiple of the 5-pair batch, never an odd remainder."
    )
    reopened.close()


def test_res_01_no_result_row_without_its_status_transition(tmp_data_dir, monkeypatch):
    """`RES-01` — the same injection, asserted purely as the invariant over the reopened
    ledger, phrased the way §6.8 states it: no result row without its status transition, the
    process halted, the ledger resumable. The resumability half is constructive: a fresh
    store over the same directory opens, migrates, and accepts a new write for a *new* unit
    once the queue is closed — the ledger a resumed M-ORCH reads is not corrupt."""
    monkeypatch.setenv("HARNESS_COMMIT_BATCH", "4")
    monkeypatch.setenv("HARNESS_COMMIT_INTERVAL_MS", "60000")
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-res01")
    original_run = store_module._run
    _saturate(handle)
    halted = []
    monkeypatch.setattr(store_module, "_halt_process_on_disk_full", halted.append)

    state = {"statements": 0}

    def full_mid_batch(connection, declared, params=None, *, retries=4):
        result = original_run(connection, declared, params, retries=retries)
        if str(declared).startswith("INSERT INTO verdict_tc13"):
            state["statements"] += 1
            if state["statements"] == 7 and not halted:
                raise sqlite3.OperationalError("database or disk is full")
        return result

    monkeypatch.setattr(store_module, "_run", full_mid_batch)
    for index in range(12):
        work_id = f"w-{index:03d}"
        handle.enqueue_write(statement(VERDICT_INSERT, issue=ISSUE), work_id=work_id, band="b1")
        handle.enqueue_write(statement(STATUS_INSERT, issue=ISSUE), work_id=work_id)
    import time

    deadline = time.monotonic() + 30
    while not halted and time.monotonic() < deadline:
        time.sleep(0.01)
    monkeypatch.undo()
    assert halted, "RES-01: the halt never ran"
    with pytest.raises(DiskFullError):
        store.close()  # close() re-raises the queue's recorded failure

    reopened = open_store(tmp_data_dir)
    reopened_handle = reopened.cohort("c-res01")
    verdicts = {row[0] for row in reopened_handle.query(statement(VERDICT_READ, issue=ISSUE))}
    done = {row[0] for row in reopened_handle.query(statement(STATUS_READ, issue=ISSUE))}
    assert verdicts == done, "RES-01: a result row survived without its status transition"
    # Resumable: the reopened store accepts work for a unit the failed batch never touched.
    reopened_handle.enqueue_write(
        statement(VERDICT_INSERT, issue=ISSUE), work_id="w-resumed", band="b1")
    reopened_handle.enqueue_write(
        statement(STATUS_INSERT, issue=ISSUE), work_id="w-resumed")
    deadline = time.monotonic() + 30
    while int(store_metrics(reopened)["write_queue_depth"]) > 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    rows = reopened_handle.query(statement(VERDICT_READ, issue=ISSUE))
    assert "w-resumed" in {row[0] for row in rows}, (
        "RES-01: the reopened store refused a fresh write. The ledger is resumable, or the "
        "halt bought nothing."
    )
    reopened.close()
