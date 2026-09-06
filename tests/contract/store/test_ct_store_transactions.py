"""`CT-STORE-03` and `CT-STORE-04` — transaction atomicity, and the single writer.

Cases `TC-STORE-C03` and `TC-STORE-C04` (P0), test plan §6.11.3. Issue #17 (TS-60).

Rung 2. Where TS-09's cases walk the queue's failure paths at depth, these assert the
contract's two promises a caller may hold: a `transaction()` body is both-present-or-both-
absent after any crash, and no reader ever observes a partial transaction — plus the clause's
own negatives (no cross-tier atomicity; no ordering promise across callers).

`Written ahead of implementation: yes` is stale; green by design.
"""

from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from aeh.store import Statement, store_metrics
from tests.support.store_api import open_store, statement

pytestmark = pytest.mark.contract

ISSUE = "#17"


def test_tc_store_c03_a_killed_body_leaves_both_rows_or_neither(tmp_data_dir):
    """`TC-STORE-C03` — *"'Write a work unit's result and its ledger transition inside one
    transaction(), kill the process mid-body, reopen, assert both present or both absent.'"*

    The kill is an injected `BaseException` from the body — the in-process face of the
    uncontrolled kill the clause is written for (`NFR-STORE-02` calls that loss
    'uncontrolled'); the process-kill face is `TC-STORE-18`'s and `TC-STORE-C05`'s ground.
    The reopened file is the oracle."""
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-c03")
    with handle.transaction() as tx:
        tx.execute(statement(
            "CREATE TABLE c03_results (work_id TEXT PRIMARY KEY, band TEXT)", issue=ISSUE))

    class _Kill(BaseException):
        pass

    with pytest.raises(_Kill):
        with handle.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO c03_results VALUES ('w-1', 'b1')", issue=ISSUE))
            tx.execute(statement(
                "INSERT INTO work_unit (work_id, submission_id, stage, status) "
                "VALUES ('w-1', NULL, 'judge', 'done')", issue=ISSUE))
            raise _Kill("uncontrolled kill mid-body")
    store.close()

    reopened = open_store(tmp_data_dir)
    reopened_handle = reopened.cohort("c-c03")
    results = reopened_handle.query(statement(
        "SELECT work_id FROM c03_results", issue=ISSUE))
    statuses = reopened_handle.query(statement(
        "SELECT work_id FROM work_unit WHERE status = 'done'", issue=ISSUE))
    assert not results and not statuses, (
        f"TC-STORE-C03: a killed body left rows behind — results {results}, statuses "
        f"{statuses}. CT-STORE-03's promise is both present or both absent after any crash; "
        "a half transaction is the unit M-ORCH skips and the grade that goes missing."
    )
    reopened.close()


def test_tc_store_c03_cross_tier_atomicity_is_refused_not_split(tmp_data_dir):
    """`TC-STORE-C03`'s negative, which is contract: *'assert cross-tier atomicity is not
    provided, by attempting a transaction spanning two tier handles and asserting it is
    refused rather than silently splitting.'* A caller relying on a guarantee nobody made is
    the bug; the store's job is to make the attempt visibly fail."""
    store = open_store(tmp_data_dir)
    cohort = store.cohort("c-c03x")
    durable = store.durable()
    with cohort.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES ('c-c03x', 'consented', '2026-01-01')", issue=ISSUE))
    from aeh.store import CrossTierTransactionError

    with pytest.raises(CrossTierTransactionError) as attempted:
        with cohort.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO cohort (cohort_id, consent_class, created_at) "
                "VALUES ('c-c03x-2', 'consented', '2026-01-01')", issue=ISSUE))
            with durable.transaction() as second:
                second.execute(statement(
                    "INSERT INTO run_metrics (run_id, metric, value) "
                    "VALUES ('r', 'cross-tier', 1.0)", issue=ISSUE))
    # The refusal is loud (CrossTierTransactionError), and the outer body rolled back —
    # behaving as the plain one-tier transaction it is.
    rows = cohort.query(statement(
        "SELECT COUNT(*) FROM cohort WHERE cohort_id = 'c-c03x-2'", issue=ISSUE))
    assert rows[0][0] == 0, (
        "TC-STORE-C03: the cohort row committed despite the nested cross-tier attempt "
        "failing. The refusal is loud, and the outer body rolled back — the caller is "
        "told, not silently split."
    )
    store.close()


def test_tc_store_c04_readers_never_see_a_partial_transaction(tmp_data_dir):
    """`TC-STORE-C04` — *"drive concurrent writers and readers, assert no reader ever observes
    a partially applied transaction and no reader blocks the writer."*

    A writer commits N rows per transaction; readers hammer the table throughout. Any reader
    seeing a count that is neither 0 nor a multiple of N has seen a partial transaction —
    the state `CT-STORE-04` makes unobservable."""
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-c04")
    with handle.transaction() as tx:
        tx.execute(statement(
            "CREATE TABLE c04_rows (batch_no INTEGER NOT NULL, seq INTEGER NOT NULL)",
            issue=ISSUE))
    stop = threading.Event()
    violations: list[int] = []

    def reader():
        connection = sqlite3.connect(f"file:{handle._path}?mode=ro", uri=True)  # noqa: SLF001
        try:
            while not stop.is_set():
                count = connection.execute("SELECT COUNT(*) FROM c04_rows").fetchone()[0]
                if count % 10 != 0:
                    violations.append(count)
        finally:
            connection.close()

    readers = [threading.Thread(target=reader, daemon=True) for _ in range(3)]
    for thread in readers:
        thread.start()
    try:
        for batch in range(20):
            with handle.transaction() as tx:
                for seq in range(10):
                    tx.execute(statement(
                        "INSERT INTO c04_rows VALUES (:b, :s)", issue=ISSUE),
                        b=batch, s=seq)
    finally:
        stop.set()
        for thread in readers:
            thread.join(timeout=10)
    assert not violations, (
        f"TC-STORE-C04: readers observed partial-transaction counts {violations[:5]}. The "
        "single writer plus WAL is what makes partial transactions unobservable; a reader "
        "seeing one is the clause failing at the database level, not in a mutex."
    )
    store.close()


def test_tc_store_c04_no_order_is_promised_across_callers(tmp_data_dir):
    """`TC-STORE-C04`'s non-promise: *'write ordering across different enqueue_write calls
    from different callers is not guaranteed except within one transaction().'* The case
    does not assert an order — it asserts the sanctioned escape: a caller needing an order
    states it in the statement, and that order is what comes back."""
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-c04b")
    with handle.transaction() as tx:
        tx.execute(statement(
            "CREATE TABLE c04b_rows (thread_no INTEGER NOT NULL, seq INTEGER NOT NULL)",
            issue=ISSUE))
    insert = statement("INSERT INTO c04b_rows VALUES (:t, :s)", issue=ISSUE)

    def writer(thread_no: int) -> None:
        for seq in range(20):
            handle.enqueue_write(insert, t=thread_no, s=seq)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    deadline = time.monotonic() + 30
    while int(store_metrics(store)["write_queue_depth"]) > 0 and time.monotonic() < deadline:
        time.sleep(0.01)

    total = handle.query(statement("SELECT COUNT(*) FROM c04b_rows", issue=ISSUE))[0][0]
    assert total == 60, "TC-STORE-C04: rows lost across concurrent enqueuers."
    # The sanctioned escape: the caller states the order, and it holds.
    stated = handle.query(statement(
        "SELECT thread_no, seq FROM c04b_rows ORDER BY thread_no, seq", issue=ISSUE))
    assert [(r[0], r[1]) for r in stated] == sorted((r[0], r[1]) for r in stated)
    per_thread_ok = all(
        [r[1] for r in stated if r[0] == n] == list(range(20)) for n in range(3)
    )
    assert per_thread_ok, (
        "TC-STORE-C04: a single caller's enqueue order was not preserved within that "
        "caller. The clause declines ordering ACROSS callers, not a single caller's own "
        "FIFO — TC-STORE-03 pins that half and this case keeps it."
    )
    store.close()
