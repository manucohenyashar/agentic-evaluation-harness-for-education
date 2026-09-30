"""`SqliteTierHandle`: one tier's database, with `query`, `enqueue_write` and `transaction`."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, ContextManager, Sequence

from .errors import ReadOnlyTierError
from .student_names import _refuse_tier_d_schema, _reject_tier_d_student_name_insert
from .interfaces import Row, Statement, Tier, WriteUnit
from .connection import _connect, _counting_lock_waits, _refuse_write, _run, TierOpened
from .limits import StoreLimits
from .transaction import Tx
from .write_queue import WriteQueue


class SqliteTierHandle:
    """One tier's database, offering `query`, `enqueue_write` and `transaction`, and nothing else.

    The member list is `CT-STORE-01`'s and it is closed on purpose: `FUZZ-07`'s docstring records
    an earlier draft that reached for `handle.has_result()` and `handle.status()`, which would
    have added two members to a protocol the design deliberately shuts. Anything a caller needs
    is a declared statement through `query`.
    """

    __slots__ = (
        "_connection", "_extra_readers", "_limits", "_local", "_lock_waits", "_opened",
        "_owner_thread", "_path", "_queue", "_read_only", "_retries", "_write_connection",
    )

    def __init__(self, connection: sqlite3.Connection, opened: TierOpened, *,
                 path: Path, limits: StoreLimits | None = None,
                 retries: int | None = None) -> None:
        self._connection = connection
        self._opened = opened
        self._read_only = opened.read_only
        self._path = path
        limits = limits if limits is not None else StoreLimits()
        if retries is not None:
            limits = replace(limits, retries=retries)
        self._limits = limits
        self._retries = limits.retries
        self._write_connection: sqlite3.Connection | None = None
        # One read connection per thread. `CT-STORE-04` promises concurrent readers never block
        # the writer, and sqlite3 refuses a connection used off its creating thread at all --
        # `ProgrammingError`, before SQLite is even reached. Passing `check_same_thread=False` and
        # sharing one connection would silence that check and put every reader behind the GIL and
        # behind each other's cursors, which is "readers block readers" wearing the right answer's
        # clothes. Under WAL a per-thread connection holds no lock the writer needs, which is the
        # property the requirement is actually about.
        self._local = threading.local()
        self._extra_readers: list[sqlite3.Connection] = []
        self._owner_thread = threading.get_ident()
        # No queue on a read-only handle, and no lazy one either. `FR-STORE-13` opens a Tier P
        # database to inspect a package *before* it is trusted, so the write path must be absent
        # rather than merely unused -- a queue that existed and refused later is a queue that
        # could open a connection and move the file's mtime while refusing.
        #
        # The tier write guard exists only on Tier D (`FR-STORE-12`: reject a student-name
        # insert) -- the other tiers have no guard, because the requirement is about the one
        # tier that is permanent and pseudonymized, not about SQL in general.
        guard = None if opened.tier is not Tier.DURABLE else _reject_tier_d_student_name_insert
        # This tier's SQLITE_BUSY-retry counter. `query` and the `WriteQueue` both hand it to
        # `_run`, and `_metrics` reports it, so a run that had to wait on a lock — the figure
        # `#118`'s export seam asserts stays zero while a concurrent analytical export reads —
        # is counted here once, wherever on the handle it happened.
        self._lock_waits: dict[str, int] = {"lock_waits": 0}
        self._queue: WriteQueue | None = (
            None if self._read_only
            else WriteQueue(self._open_write_connection, limits,
                            tier_name=opened.tier.value, guard=guard,
                            lock_waits=self._lock_waits)
        )

    # -- the read connections ------------------------------------------------------------------

    def _read_connection(self) -> sqlite3.Connection:
        """This thread's read connection, opened on first use.

        The connection `_open_tier` built is this handle's own and stays the one the constructing
        thread uses -- it is the one migrations ran on and the one `TierOpened` describes. Every
        other thread gets its own, recorded in `_extra_readers` so `close()` can reach it: a
        connection nothing closes is, on Windows, a file `purge_cohort` cannot delete.
        """
        existing = getattr(self._local, "connection", None)
        if existing is not None:
            return existing
        connection = _connect(
            self._path, read_only=self._read_only,
            busy_timeout_ms=self._limits.busy_timeout_ms, retries=self._limits.retries,
            # Used by exactly one thread -- the one this branch just created it for -- so the
            # WAL argument above is untouched. The flag is off because `close()` runs on a
            # *different* thread, and with the check on it raised `ProgrammingError` there,
            # aborting the loop and leaving every later reader and the handle's own connection
            # open: precisely the locked file this list exists to prevent.
            check_same_thread=False,
        )
        self._local.connection = connection
        self._extra_readers.append(connection)
        return connection

    # -- the write connection ----------------------------------------------------------------

    def _open_write_connection(self) -> sqlite3.Connection:
        """The write connection, opened on the first write and kept while the handle is open.

        **Separate from the read connection, and that is `CT-STORE-04`.** Under WAL a reader
        holds no lock a writer needs, so two connections is what makes "concurrent readers never
        block the writer" a property of the database rather than of a mutex this module happens
        to release often enough.

        `check_same_thread=False` because two threads legitimately use it -- the drain thread for
        batches, the caller's thread for a `transaction()` body -- and `WriteQueue._write_lock`
        is what keeps them from doing so at once. The flag disables sqlite3's own thread check;
        it does not make the connection safe on its own, and the lock is not decoration.

        `journal_mode` is not set here: WAL lives in the file header, `_open_tier` wrote it, and
        this connection inherits it. `foreign_keys` is the opposite -- per connection, never
        persisted -- so `_connect` setting it is exactly what `FR-STORE-14` needs, since this is
        the connection that actually issues every write `CT-STORE-13` promises will fail.
        """
        if self._write_connection is None:
            self._write_connection = _connect(
                self._path, read_only=False, busy_timeout_ms=self._limits.busy_timeout_ms,
                retries=self._limits.retries, check_same_thread=False,
            )
            if self._opened.tier is Tier.DURABLE:
                # Schema DDL refused at the SQLite layer (see `_refuse_tier_d_schema`): the
                # name guard reads statements, but a CREATE TABLE through a transaction()
                # body would create the very name-bearing column the guard's schema sweep
                # is trusted to have excluded -- and fill it with a no-column-list INSERT
                # the guard cannot see. On the durable tier, schema belongs to migrations.
                self._write_connection.set_authorizer(_refuse_tier_d_schema)
        return self._write_connection

    def _refuse_read_only(self, door: str) -> None:
        if self._read_only:
            raise ReadOnlyTierError(
                f"{door} was called on a read-only handle for {self._path.name}. FR-STORE-13 "
                "opens a Tier P database read-only so an imported package can be inspected "
                "before it is trusted, and a write through that handle would alter the file "
                "whose provenance is the question."
            )

    @property
    def _open_report(self) -> TierOpened:
        """What opening this database did. Read-only; see `TierOpened`.

        Private, per `CT-STORE-01`: the handle's public surface is `query`,
        `enqueue_write`, `transaction` — and nothing else. The open report is
        observability, and `store_metrics` reads it through the private name, the same
        discipline that renamed `close` to `_close` in #12 (TC-STORE-C01 is the case that
        holds the line)."""
        return self._opened

    def query(self, statement: Statement, **params: Any) -> Sequence[Row]:
        """Run a declared read and return its rows.

        **No order is promised** (`CT-STORE-18`): rows come back in whatever order SQLite
        produces, and a caller needing an order states it in the statement. Nothing here sorts,
        because a module that sorted would make every caller's unstated assumption work until the
        day it did not.

        **A write through here is refused**, and that is not tidiness. The connection is in
        autocommit, so before this guard `query(Statement("INSERT ..."))` wrote and committed
        synchronously — review used exactly that to seed every fixture it needed.
        `CT-STORE-02` makes writing *asynchronous*, through `enqueue_write`; a synchronous write
        channel wearing the name `query` is the contract violation that clause exists to prevent.
        Today it is the only write path there is, so every caller written before #11 lands would
        be written against it. `TC-STORE-C01` says the closed member list matters *"because it is
        the door through which every other clause here gets bypassed"* — this is that door, one
        level below the member list.

        The test is the statement's first keyword. Reads are `SELECT`, `WITH`, `VALUES`,
        `EXPLAIN` and `PRAGMA` — `PRAGMA` because schema introspection is how a caller inspects an
        imported package (`FR-STORE-13`) and how `TC-STATS-C18` sweeps Tier D for a name column.
        It is a keyword check and not a parser: it stops a caller reaching for the wrong method,
        which is the only thing that needs stopping, because every caller is in-process trusted
        code and there is no untrusted path into a statement.
        """
        declared = statement if isinstance(statement, Statement) else Statement(statement)
        _refuse_write(declared)
        with _counting_lock_waits(self._lock_waits):
            return _run(self._connection_for_this_thread(), declared, params,
                        retries=self._retries).fetchall()

    def _connection_for_this_thread(self) -> sqlite3.Connection:
        """The handle's main connection on the thread that opened it, or a private connection on
        any other thread.

        Compared by thread identity rather than by trying the connection and catching
        `ProgrammingError`: a probe would be a second `execute()` in this module, and
        `KNOWN_EXECUTE_SITES` in `tests/artifact/test_store_query_surface.py` is an exact set for
        the good reason that every site is somewhere a statement reaches SQLite.
        """
        if threading.get_ident() == self._owner_thread:
            return self._connection
        return self._read_connection()

    def enqueue_write(self, unit: WriteUnit | Statement | str, /, **params: Any) -> None:
        """Queue one write and return at once; the write happens later (CT-STORE-02).

        Returns before the row is durable, and that is the clause design 3.3 calls "the single
        most load-bearing clause in this contract and the easiest to get wrong". A caller that
        must observe its own write reads through `transaction()` or waits for the commit batch;
        nothing here waits on its behalf.

        **Two accepted forms, because the design and the suite disagree.** 3.3's Interfaces block
        types the parameter `WriteUnit`; every merged case calls
        `enqueue_write(statement, **params)`. Both work: a `WriteUnit` is used as given, and a
        statement plus keywords is packed into one. Supporting only the declared form would break
        four merged files including a P0; supporting only the convenience form would drop the
        signature the design states. The gap is reported against the design rather than resolved
        by picking a side.

        Blocks at the configured depth (`FR-STORE-05`) -- see `WriteQueue.enqueue`.

        **The Tier D guard rejects before queueing** (`FR-STORE-12`): an insert naming a
        student-name column raises `StudentNameInTierDError` from this call, synchronously.
        The asynchrony above is about durability, not about accepting writes that must never
        land.
        """
        self._refuse_read_only("enqueue_write")
        if isinstance(unit, WriteUnit):
            if params:
                raise TypeError(
                    "enqueue_write got both a WriteUnit and keyword parameters. The unit already "
                    "carries its params; passing both leaves it ambiguous which wins."
                )
            queued = unit
        else:
            declared = unit if isinstance(unit, Statement) else Statement(unit)
            queued = WriteUnit(statement=declared, params=params)
        assert self._queue is not None  # guaranteed by _refuse_read_only above
        self._queue.enqueue(queued)

    def transaction(self) -> ContextManager[Tx]:
        """Run the whole body as one atomic, synchronous transaction within this tier
        (CT-STORE-03).

        Within **one tier handle**. Cross-tier atomicity is deliberately not provided, and a
        caller needing a row in Tier C and a row in Tier D together does not get it from here --
        `CT-STORE-03` says so, and two databases cannot be committed atomically without a
        transaction manager this design rejects along with the server process.
        """
        self._refuse_read_only("transaction")
        assert self._queue is not None  # guaranteed by _refuse_read_only above
        return self._queue.transaction()

    @property
    def _metrics(self) -> dict[str, Any]:
        """This tier's share of the store's signals (CT-STORE-17). `store_metrics` reads this
        private method; it is not part of the handle's public surface (CT-STORE-01)."""
        queue = self._queue
        return {
            "write_queue_depth": 0 if queue is None else queue.depth,
            "batch_commit_latency_ms": 0.0 if queue is None else queue.last_commit_latency_ms,
            "backpressure_active": False if queue is None else queue.backpressure_active,
            "queue_depth_sustained": False if queue is None else queue.sustained_over_threshold(),
            "write_failures": 0 if queue is None else len(queue.failures),
            "database_file_bytes": self._path.stat().st_size if self._path.exists() else 0,
            "lock_waits": self._lock_waits["lock_waits"],
        }

    def _close(self) -> None:
        """Flush the write queue, then close both connections.

        **Private, and `CT-STORE-01` is why.** Design §3.3 fixes the `TierHandle` surface at
        `query`, `enqueue_write` and `transaction` — *"and nothing else"* — and `TC-STORE-15`
        asserts that over the concrete class rather than the Protocol, precisely because a fourth
        public method is where an off-protocol search arrives. #10 shipped this as `close()`,
        which made the handle a four-member object; the written-ahead case caught it the moment
        `blobs()` let the case run. Lifecycle belongs to `Store.close()`, which is the only
        caller and is where `TC-STORE-16`'s `require_attr(store, "close")` looks for it.

        The queue closes **first**: it is still holding rows bound for the write connection, and
        closing that connection out from under a batch mid-flight is how a clean shutdown starts
        losing the writes an uncontrolled kill was supposed to be the only thing that loses.
        """
        if self._queue is not None:
            try:
                self._queue.close()
            finally:
                if self._write_connection is not None:
                    self._write_connection.close()
                    self._write_connection = None
        # Every one of them, even if one raises. A loop that stopped at the first failure would
        # leave the rest open while reporting the problem, which on Windows is a file
        # `purge_cohort` cannot delete -- the failure this list exists to prevent, reached by the
        # cleanup rather than by the absence of one.
        for reader in self._extra_readers:
            try:
                reader.close()
            except sqlite3.Error:
                pass
        self._extra_readers.clear()
        self._connection.close()
