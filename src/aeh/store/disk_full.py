"""Recognizing an out-of-space failure, and halting the process when it happens."""

from __future__ import annotations

import errno
import os
import sqlite3
import sys

from .settings import DISK_FULL_EXIT_CODE
from .errors import DiskFullError


def _halt_process_on_disk_full(error: BaseException) -> None:
    """The halt `FR-STORE-10` demands: end the process, now, from wherever the writer is.

    `os._exit` rather than `sys.exit`: it does not unwind, does not run `atexit` handlers and
    does not wait for other threads — which is the point. A run that keeps closing handles
    and flushing queues on its way down is a run *continuing with partial writes*, and the
    requirement names that as the thing not to do. SQLite is crash-safe by design; the
    process is not obliged to be graceful about dying. One line reaches stderr first,
    because a halt with no trace is a halt the operator cannot diagnose from the transcript.

    Module-level so a test can monkeypatch exactly one name and capture the error instead of
    ending the interpreter. Never returns in production; if an injected replacement does
    return, the queue's terminal-broken state takes over and every later write raises
    `DiskFullError`.
    """
    print(f"aeh.store: halting on disk full: {error}", file=sys.stderr)
    os._exit(DISK_FULL_EXIT_CODE)  # pragma: no cover - ends the interpreter by design


def _halt_if_disk_full(error: BaseException) -> None:
    """Purge's door of `FR-STORE-10`'s sequence — classify, halt, raise the classified error.

    Purge has no queue state to record, so its door is the classification plus the halt
    hook, and the hook's (test-only) return is answered by raising the `DiskFullError`.
    Returns for anything that is not out-of-space, so the caller re-raises the original
    unchanged. Content a purge deleted before a disk-full failure stays deleted; re-running
    the purge completes its `VACUUM` — the precondition gates still hold and the tables are
    already empty.
    """
    failure = _as_disk_full(error)
    if failure is not None:
        _halt_process_on_disk_full(failure)  # never returns in production
        raise failure


def _as_disk_full(error: BaseException, *, include_os_errors: bool = True) -> DiskFullError | None:
    """Is this the out-of-space condition `FR-STORE-10` is about — and if so, the error.

    Two signatures, because the same condition arrives wearing two faces: SQLite's
    `SQLITE_FULL` (`OperationalError: database or disk is full`) when the *database* layer
    runs out — which on a dedicated data disk is the disk, not the database, since this
    module sets no `max_page_count` — and the OS's `OSError(ENOSPC)` when the filesystem
    itself refuses before SQLite is even reached (a `VACUUM` writing a temp copy can land
    there, as can the WAL). Anything else is not disk-full and must not be classified as
    one: a mis-classified error halts a process that could have kept going, and "halts the
    process" is not an outcome to hand to a loose string match. The message check is
    SQLite's own wording, not a guess at it.

    `include_os_errors=False` is the **transaction body's** setting, and it is not a
    technicality: a `transaction()` body runs arbitrary caller code, so a raw
    `OSError(ENOSPC)` raised there can be the caller's *own* file export failing on an
    unrelated path. Classifying that as the store's disk-full would halt the run for
    somebody else's I/O. The body door therefore classifies only the store's own
    `sqlite3` errors; the batch, commit and purge doors — whose failures are always this
    module's I/O — keep `OSError(ENOSPC)` in scope.

    Declared residual faces: out-of-space that surfaces as `SQLITE_CANTOPEN` ("unable to
    open database file") or a generic `disk I/O error` is **not** classified, because
    neither message is unique to exhaustion — the same codes fire for a wrong path or
    permissions, and a mis-classified halt is exactly the loose string match this helper
    refuses to be.

    The returned error carries the decision-table wording and the original chained as its
    cause. The door that saw the failure owns the state to record (the queue's failure
    list and broken flag; purge has none) and then runs the halt hook — which is why this
    helper only builds the error and never halts on its own.
    """
    if isinstance(error, sqlite3.Error):
        if isinstance(error, sqlite3.OperationalError) and "database or disk is full" in str(
            error
        ).lower():
            failure = DiskFullError(
                f"the write failed for want of disk space and the process halts "
                f"(FR-STORE-10): {error}. The interrupted work was rolled back whole, so "
                f"no result row is present without its ledger transition, and the ledger "
                f"stands at its last commit, which is resumable (CT-STORE-05's window, "
                f"not a new loss)."
            )
            failure.__cause__ = error
            return failure
        return None
    if include_os_errors and isinstance(error, OSError) and error.errno == errno.ENOSPC:
        failure = DiskFullError(
            f"the write failed for want of disk space and the process halts (FR-STORE-10): "
            f"{error}. The interrupted work was rolled back whole, so no result row is "
            f"present without its ledger transition, and the ledger stands at its last "
            f"commit, which is resumable (CT-STORE-05's window, not a new loss)."
        )
        failure.__cause__ = error
        return failure
    return None
