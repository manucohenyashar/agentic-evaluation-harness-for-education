"""Recognizing an out-of-space failure, and halting the process when it happens."""

from __future__ import annotations

import errno
import os
import sqlite3
import sys

from .settings import DISK_FULL_EXIT_CODE
from .errors import DiskFullError


def _halt_process_on_disk_full(error: BaseException) -> None:
    """End the process immediately after a disk-full write failure, from whichever thread hit it
    (FR-STORE-10).

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
    """Used by purge: if the error is running out of disk space, halt the process and raise the
    classified error (FR-STORE-10).

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
    """If this error means the disk is full (FR-STORE-10), the `DiskFullError` to raise; otherwise
    None.

    More detail: `docs/code-notes/store.md`, section `disk_full.py: _as_disk_full`.
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
