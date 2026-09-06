"""`CT-STORE-11` and `CT-STORE-12` — the named errors, and the migration discipline.

Cases `TC-STORE-C11` and `TC-STORE-C12` (P0), test plan §6.11.3. Issue #17 (TS-60).

Rung 2. C11 is one case per named error, each asserting the exact type, non-retryability,
and the state left behind — with `SQLITE_BUSY` asserted never to surface. C12 asserts the
migration discipline and the caller's right to an exact schema after a successful open.

`Written ahead of implementation: yes` is stale; green by design.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time

import pytest

import aeh.store as store_module
from aeh.store import (
    DiskFullError,
    InsecureLocationError,
    PurgePreconditionError,
    SchemaTooNewError,
    open_store,
)
from tests.support.store_api import statement

pytestmark = pytest.mark.contract

ISSUE = "#17"


def test_tc_store_c11_purge_precondition_refuses_and_deletes_nothing(tmp_data_dir):
    """C11, `PurgePreconditionError`: exact type, and the state left behind is *nothing
    deleted* — the byte-level half is TC-STORE-11's; here the state assertion is the file's
    identity."""
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-c11")
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES ('c-c11', 'consented', '2026-01-01')", issue=ISSUE))
    path = store.cohort_path("c-c11")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(PurgePreconditionError):
        store.purge_cohort("c-c11")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, (
        "TC-STORE-C11: the precondition refusal touched the cohort file. The clause's state "
        "assertion for this error is 'nothing deleted', and a byte change is a deletion the "
        "report did not claim."
    )
    store.close()


def test_tc_store_c11_insecure_location_refuses_the_start(tmp_data_dir, monkeypatch):
    """C11, `InsecureLocationError`: exact type, refuses to start, and nothing exists
    afterwards — the state-left-behind is the absent directory."""
    monkeypatch.setattr(
        store_module, "_insecure_location_reason", lambda path, **kw: "synthetic refusal")
    fresh = tmp_data_dir / "refused"
    with pytest.raises(InsecureLocationError):
        open_store(fresh)
    assert not fresh.exists()


def test_tc_store_c11_schema_too_new_refuses_with_no_partial_read(tmp_data_dir):
    """C11, `SchemaTooNewError`: exact type; the state left behind is an unmodified file —
    the 'no partial read' half of the clause."""
    store = open_store(tmp_data_dir)
    store.durable()
    store.close()
    path = store.durable_path()
    with sqlite3.connect(path) as raw:
        raw.execute("INSERT INTO schema_version (version, name, applied_at) VALUES (99, 'future', 't')")
        raw.commit()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    reopened = open_store(tmp_data_dir)
    with pytest.raises(SchemaTooNewError):
        reopened.durable()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    reopened.close()


def test_tc_store_c11_disk_full_breaks_the_queue_and_is_not_retryable(tmp_data_dir, monkeypatch):
    """C11, `DiskFullError`: exact type; the state left behind is the last committed batch
    (the declared semantics); and the caller cannot retry — the queue refuses, which is what
    'not retryable by the caller' means for an error whose production effect is a halt."""
    monkeypatch.setenv("HARNESS_COMMIT_BATCH", "10")
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-c11b")
    with handle.transaction() as tx:
        tx.execute(statement(
            "CREATE TABLE c11_rows (n INTEGER)", issue=ISSUE))
    original_run = store_module._run
    halted = []
    monkeypatch.setattr(store_module, "_halt_process_on_disk_full", halted.append)

    def full(connection, declared, params=None, *, retries=4):
        result = original_run(connection, declared, params, retries=retries)
        if str(declared).startswith("INSERT INTO c11_rows") and halted:
            raise sqlite3.OperationalError("database or disk is full")
        return result

    # First row commits fine; the second is made to fail as disk-full.
    state = {"n": 0}

    def full_on_second(connection, declared, params=None, *, retries=4):
        result = original_run(connection, declared, params, retries=retries)
        if str(declared).startswith("INSERT INTO c11_rows"):
            state["n"] += 1
            if state["n"] == 2:
                raise sqlite3.OperationalError("database or disk is full")
        return result

    monkeypatch.setattr(store_module, "_run", full_on_second)
    handle.enqueue_write(statement("INSERT INTO c11_rows VALUES (1)", issue=ISSUE))
    deadline = __import__("time").monotonic() + 30
    while state["n"] < 1 and __import__("time").monotonic() < deadline:
        __import__("time").sleep(0.01)
    handle.enqueue_write(statement("INSERT INTO c11_rows VALUES (2)", issue=ISSUE))
    deadline = __import__("time").monotonic() + 30
    while not halted and __import__("time").monotonic() < deadline:
        __import__("time").sleep(0.01)
    monkeypatch.undo()
    assert halted and isinstance(halted[0], DiskFullError)
    with pytest.raises(DiskFullError):
        handle.enqueue_write(statement("INSERT INTO c11_rows VALUES (3)", issue=ISSUE))
    with pytest.raises(DiskFullError):
        store.close()
    store._handles.clear()  # the broken queue is spent; drop it for the reopen below
    reopened = open_store(tmp_data_dir)
    rows = reopened.cohort("c-c11b").query(statement(
        "SELECT n FROM c11_rows ORDER BY n", issue=ISSUE))
    assert [r[0] for r in rows] == [1], (
        f"TC-STORE-C11: the ledger after the halt holds {rows}; the declared state is the "
        "last committed batch — the failed batch rolled back whole, nothing half-written."
    )
    reopened.close()


def test_tc_store_c11_sqlite_busy_never_surfaces(tmp_data_dir):
    """C11's last limb: *'assert SQLITE_BUSY is retried internally and never surfaces.'*
    A competing process holds the write lock; the store's own write must still land — the
    bounded internal retry absorbed the busy, and no `OperationalError` containing 'busy' or
    'locked' reaches the caller."""
    import subprocess
    import sys
    import textwrap

    data_dir = tmp_data_dir / "busy"
    store = open_store(data_dir)
    handle = store.cohort("c-busy")
    with handle.transaction() as tx:
        tx.execute(statement("CREATE TABLE busy_rows (n INTEGER)", issue=ISSUE))
    store.close()

    # An external process holds a write transaction on the file for ~2 seconds.
    holder = textwrap.dedent(
        """
        import sqlite3, sys, time
        c = sqlite3.connect(sys.argv[1], isolation_level=None)
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO busy_rows VALUES (999)")
        time.sleep(2.0)
        c.execute("ROLLBACK")
        """
    )
    process = subprocess.Popen(
        [sys.executable, "-c", holder, str(store.cohort_path("c-busy"))])
    time.sleep(0.4)  # the holder has the lock now
    try:
        contender = open_store(data_dir)
        contender_handle = contender.cohort("c-busy")
        contender_handle.enqueue_write(statement(
            "INSERT INTO busy_rows VALUES (1)", issue=ISSUE))
        contender_handle.enqueue_write(statement(
            "INSERT INTO busy_rows VALUES (2)", issue=ISSUE))
        deadline = __import__("time").monotonic() + 60
        while True:
            rows = contender_handle.query(statement(
                "SELECT COUNT(*) FROM busy_rows WHERE n IN (1, 2)", issue=ISSUE))[0][0]
            if rows == 2 or __import__("time").monotonic() > deadline:
                break
            __import__("time").sleep(0.1)
        assert rows == 2, "TC-STORE-C11: the store's write never landed past the busy lock."
        surfaced = [
            str(f) for f in contender_handle._queue.failures  # noqa: SLF001
            if "busy" in str(f).lower() or "locked" in str(f).lower()
        ]
        assert not surfaced, (
            f"TC-STORE-C11: SQLITE_BUSY surfaced to the caller: {surfaced}. The clause says "
            "the retry is internal and the error never surfaces — a caller that sees 'busy' "
            "will build a retry loop the contract says it does not need."
        )
        contender.close()
    finally:
        process.wait(timeout=30)
    store.close()


def test_tc_store_c12_after_a_successful_open_the_schema_matches_the_binary(tmp_data_dir):
    """`TC-STORE-C12` — *'after a successful open, assert the schema matches the binary
    exactly.'* Oracle: **schema differential** — the tables the binary's migrations declare
    are exactly the tables the file carries, per tier; extra or missing tables are the
    degradation the clause refuses."""
    from aeh.store import TIER_MIGRATIONS, Tier

    store = open_store(tmp_data_dir)
    handles = {
        Tier.PACKAGE: store.package("s-c12"),
        Tier.COHORT: store.cohort("s-c12"),
        Tier.DURABLE: store.durable(),
    }
    for tier, handle in handles.items():
        expected_tables = set()
        for migration in TIER_MIGRATIONS[tier]:
            for stmt in migration.statements:
                text = str(stmt)
                if "CREATE TABLE " not in text:
                    continue  # a future index or view migration is not a table
                between = text.split("CREATE TABLE ", 1)[1]
                expected_tables.add(between.split("(", 1)[0].strip())
        expected_tables.add("schema_version")  # created by _migrate, not a migration row
        found = {
            row[0] for row in handle.query(statement(
                "SELECT name FROM sqlite_master WHERE type = 'table'", issue=ISSUE))
            if not row[0].startswith("sqlite_")
        }
        assert found == expected_tables, (
            f"TC-STORE-C12: {tier}'s schema drifted after a successful open — extra: "
            f"{sorted(found - expected_tables)}, missing: {sorted(expected_tables - found)}. "
            "CT-STORE-12 gives the caller an exact-schema right; 'opens and mostly matches' "
            "is the degradation the clause refuses."
        )
    store.close()
