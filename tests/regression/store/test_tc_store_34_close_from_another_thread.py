"""TC-STORE-34 (issue #890, a defect found while building the live validity check): a cohort
handle whose own connection was opened on one thread is closed from another.

The console serves each request on a fresh thread, so the thread that first touches a class's
ledger (a run worker, an earlier request) is never the one that later asks to purge it. The
handle's own read connection — the one `_open_tier` builds on the constructing thread — was
opened with sqlite3's same-thread check on, so closing it from the purge's thread raised
`ProgrammingError`: "SQLite objects created in a thread can only be used in that same thread".
Every console `purge cohort` after a run was refused with that message, and the connection
stayed open on the file.

Rung 2: a real store on a real file, two real threads. FR-STORE-07 (purge), CT-STORE-10.
"""

from __future__ import annotations

import sqlite3
import threading

from tests.support.store_api import open_store


def _close_on_another_thread(store) -> list[BaseException]:
    errors: list[BaseException] = []

    def close() -> None:
        try:
            store.close()
        except BaseException as error:  # noqa: BLE001 — reported to the asserting thread
            errors.append(error)

    worker = threading.Thread(target=close)
    worker.start()
    worker.join(30)
    assert not worker.is_alive(), "store.close() did not return on the other thread"
    return errors


def test_tc_store_34_a_handle_opened_on_one_thread_closes_on_another(tmp_data_dir):
    """The handle opened (and read) on this thread; the close runs on another. It must close
    every connection without raising, leaving the ledger file free to be swept and deleted."""
    store = open_store(tmp_data_dir)
    handle = store.cohort("class-a")
    path = tmp_data_dir / "cohorts" / "class-a.sqlite"
    assert path.exists(), "fixture: the cohort ledger was not created"
    # A read on the constructing thread: the handle's own connection is the one in use.
    from aeh.store import Statement

    handle.query(Statement("SELECT COUNT(*) AS n FROM sqlite_master"))

    errors = _close_on_another_thread(store)
    assert not errors, (
        f"closing the store from another thread raised {errors[0]!r}; the console's purge runs "
        "on a request thread that never owns the handle, so every purge after a run is refused")
    # Nothing holds the file: an exclusive lock succeeds, and on Windows the file deletes.
    connection = sqlite3.connect(path)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        connection.execute("ROLLBACK")
    finally:
        connection.close()
    path.unlink()
