"""`WriteQueue`: the single writer thread, with batched commits and backpressure."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from .errors import (
    CrossTierTransactionError,
    DiskFullError,
    WriteQueueClosed,
    WriteThroughQueryError,
)
from .disk_full import _as_disk_full, _halt_process_on_disk_full
from .interfaces import _OPEN_TX_TIERS, Statement, WriteUnit
from .connection import _BEGIN, _COMMIT, _counting_lock_waits, _ROLLBACK, _run
from .limits import StoreLimits
from .transaction import Tx


class WriteQueue:
    """The single writer: one queue and one thread, committing in batches and making callers wait
    when the queue is full.

    More detail: `docs/code-notes/store.md`, section `write_queue.py: WriteQueue`.
    """

    __slots__ = (
        "_broken", "_condition", "_connect_write", "_failures", "_guard", "_halt", "_holder",
        "_last_latency_ms", "_limits", "_lock_waits", "_over_since", "_pending", "_queue",
        "_stamps", "_stopping", "_thread", "_tier_name", "_write_lock",
    )

    def __init__(self, connect_write: Any, limits: StoreLimits, *,
                 tier_name: str = "",
                 guard: Callable[[Statement], None] | None = None,
                 halt: Callable[[BaseException], None] | None = None,
                 lock_waits: dict[str, int] | None = None) -> None:
        self._connect_write = connect_write
        self._tier_name = tier_name
        self._limits = limits
        # The owning handle's SQLITE_BUSY-retry counter (`#118`'s lock-waits figure): the
        # counting windows over `_commit` and `transaction()` install it as this thread's
        # sink, so a batch's waits and a body statement's waits land in the same number the
        # handle's metrics report.
        self._lock_waits = lock_waits
        # The tier write guard (Tier D's student-name check) or `None` for a tier without
        # one. Applied at both doors: `enqueue` before queueing, `transaction` via the `Tx`
        # it hands out. See `_reject_tier_d_student_name_insert`.
        self._guard = guard
        # The disk-full halt (`FR-STORE-10`). The injected hook, or `None` to use the
        # module-level default — resolved at CALL time, not here, because a default bound
        # at construction would freeze the real `os._exit` into every queue built before a
        # test patched the module attribute, and the whole point of the indirection is that
        # a test monkeypatches exactly one name; see `DiskFullError`.
        self._halt = halt
        self._queue: deque[WriteUnit] = deque()
        self._stamps: deque[float] = deque()
        self._condition = threading.Condition()
        self._write_lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._last_latency_ms = 0.0
        self._over_since: float | None = None
        self._failures: list[BaseException] = []
        # Set once, by the disk-full path: the queue is terminally broken and refuses
        # further writes with the `DiskFullError` that broke it (`CT-STORE-11`: not
        # retryable by the caller). In production the halt hook never returns; this is what
        # an injected (test) hook that does return observes, and what a caller on another
        # thread hits the instant the writer classified the failure.
        self._broken: DiskFullError | None = None
        # Rows enqueued and not yet durable -- queued *or* in flight. One counter rather than
        # two terms; see `depth`.
        self._pending = 0
        # Whether *this* thread is inside a `transaction()` body on this queue. See `enqueue`.
        self._holder = threading.local()

    # -- what the metrics read -----------------------------------------------------------------

    @property
    def depth(self) -> int:
        """Rows queued but not yet durable, whether waiting or being committed.

        "Not yet durable" rather than "still on the deque", and the difference is what a caller
        waiting for its writes depends on: `CT-STORE-02` makes `enqueue_write` asynchronous and
        nothing else says when the row arrives, so polling this to zero is the only way to wait.
        Counting the deque alone reports zero the instant the last batch is *popped*, while it is
        still inside `COMMIT`, and the caller reads back one commit short. Measured before this
        was a single counter: `TC-STORE-03` landed 225 of 250 rows -- in order, nothing lost,
        the drain simply believing it had finished a batch early.

        **One counter, not two terms added together.** An earlier form was
        `len(self._queue) + self._in_flight`, incremented after the pops; review found the gap
        between the last `popleft` and the `+=` still reads zero for a batch that is in neither
        place. Narrower than a whole `COMMIT`, and not tripped in nine attempts -- but a window
        the docstring claimed was closed. A single `int` read is atomic in CPython and has no
        such gap.

        No lock, deliberately. The merged `_drain` polls this in a tight loop with no sleep, and
        a poll contending with the writer for the writer's own lock on every iteration would be
        the reader blocking the writer, in the one place this module exists to prevent it.
        """
        return self._pending

    @property
    def backpressure_active(self) -> bool:
        """Whether the queue is at or above its configured depth, so writers are made to wait
        (FR-STORE-05).

        At, not above. The requirement says "when the pending write queue exceeds a configured
        depth" and `TC-STORE-07` reads that boundary as inclusive -- `N-1` clear, `N` raised. A
        signal that first appeared at `N+1` would let the queue reach the bound
        `NFR-STORE-02`'s durability window is computed from before saying anything.
        """
        return self.depth >= self._limits.write_queue_depth

    @property
    def last_commit_latency_ms(self) -> float:
        return self._last_latency_ms

    @property
    def failures(self) -> tuple[BaseException, ...]:
        return tuple(self._failures)

    def sustained_over_threshold(self) -> bool:
        """Whether the queue has been full long enough to raise the alert, not just the signal."""
        since = self._over_since
        if since is None:
            return False
        return (time.monotonic() - since) * 1000.0 >= self._limits.queue_depth_sustain_ms

    # -- the caller side -----------------------------------------------------------------------

    def enqueue(self, unit: WriteUnit) -> None:
        """Add a row, waiting while the queue is at or above its configured depth.

        Blocking is one of the two behaviours `FR-STORE-05` sanctions, and it is the one that
        cannot lie: a caller that is blocked has demonstrably reduced its dispatch rate, whereas
        "slowing" is a promise about a duration nobody can hold. `CT-STORE-06` tells `M-ORCH` to
        read it as a throttle signal rather than a fault, which is why this raises nothing while
        the store is open.

        The writer thread is started **before** the wait, not after. Starting it afterwards
        deadlocks the first caller the moment the depth is reached: nothing would be draining
        the queue it is waiting on.
        """
        if self._broken is not None:
            # CT-STORE-11: DiskFullError is not retryable. A write queued after the halt
            # would either land on a disk that is still full or half-land on one that is not,
            # and both are the process continuing past the failure FR-STORE-10 halts on.
            raise self._broken
        if self._guard is not None:
            # Fail before the writer thread exists for a unit it must never write: the
            # Tier D name guard's rejection is of the insert itself.
            self._guard(unit.statement)
        if getattr(self._holder, "in_transaction", False):
            # F2: this thread is inside a `transaction()` body, so it holds `_write_lock` -- the
            # same lock the drain thread needs to commit anything. Waiting for backpressure to
            # clear would wait for a drain that cannot start, and the process hangs with no
            # timeout and no diagnostic.
            #
            # `CT-STORE-04` is the reason this is a raise rather than a docstring note: "write
            # ordering across different `enqueue_write` calls ... is not guaranteed **except
            # within one `transaction()`**" reads, naturally, as contemplating enqueues inside a
            # transaction body. It cannot mean that here -- an enqueued row is committed by the
            # *writer*, in its own transaction, so it could not be part of the caller's one even
            # if the lock allowed it. Saying so is better than deadlocking at depth 1,000 in an
            # M-ORCH bulk path.
            raise WriteThroughQueryError(
                "enqueue_write was called inside a transaction() body on the same tier. The "
                "queue commits in its own transaction, so the row could not join this one; and "
                "the body holds the write lock the queue's writer needs, so at the configured "
                "depth this call would block forever on a drain that cannot start. Write it "
                "with tx.execute() to be part of this transaction, or enqueue it after the "
                "body exits."
            )
        self._ensure_writer()
        with self._condition:
            while self._pending >= self._limits.write_queue_depth and not self._stopping:
                self._condition.notify_all()
                self._condition.wait(timeout=self._limits.writer_poll_ms / 1000)
            if self._stopping:
                raise WriteQueueClosed(
                    "the store closed while this write was waiting on backpressure; the row was "
                    "not queued and has not been written"
                )
            if self._broken is not None:
                # Re-checked after the wait, not only before: `_disk_full_failure` wakes
                # waiters before halting, so the wake-up that ends this wait can be the
                # disk-full one. Appending past it would hand the caller a normal return
                # from a row the queue will never write.
                raise self._broken
            self._queue.append(unit)
            self._stamps.append(time.monotonic())
            self._pending += 1
            self._note_depth_locked()
            self._condition.notify_all()

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        """Run the whole body as one atomic, synchronous transaction within one tier (CT-STORE-03).

        `BEGIN IMMEDIATE` rather than a deferred begin: the write lock is already held, so taking
        the database's write lock at the same moment keeps the two in step and means a competing
        process fails at the `BEGIN` -- where `_run`'s bounded `SQLITE_BUSY` retry can see it --
        rather than partway through the body.

        Rollback on **`BaseException`**, not `Exception`. `FUZZ-07` injects its abort as a custom
        exception and a `KeyboardInterrupt` mid-transaction is exactly the "uncontrolled kill"
        `NFR-STORE-02` is about; catching only `Exception` would leave a transaction open on the
        connection for the next caller to inherit.
        """
        if self._broken is not None:
            # CT-STORE-11: the disk-full halt is terminal and not retryable.
            raise self._broken
        if self._stopping:
            # Without this a transaction on a closed store reopens the write connection and
            # commits, so `close()` refuses one write door and holds the other open.
            raise WriteQueueClosed(
                "transaction() was called on a closed store. Reopening the write connection "
                "here would commit to a tier whose handle has already been released."
            )
        counts = getattr(_OPEN_TX_TIERS, "tiers", None) or {}
        open_tiers = {tier for tier, depth in counts.items() if depth > 0}
        if open_tiers and open_tiers != {self._tier_name}:
            # CT-STORE-03's negative, made loud: a second tier's transaction nested inside
            # a first tier's open one. Without this the nested transaction commits
            # independently and the caller believes in an atomicity nobody provided.
            raise CrossTierTransactionError(
                f"transaction() was opened on tier(s) {sorted(open_tiers)} while tier "
                f"{self._tier_name!r} already holds an open transaction on this thread. "
                "CT-STORE-03 provides no cross-tier atomicity — the nested transaction "
                "would commit independently, and a caller believing both sides committed "
                "together is silently split. Run the tiers' transactions sequentially."
            )
        with self._write_lock, _counting_lock_waits(self._lock_waits):
            # The lock-wait window covers the whole transaction — BEGIN, every `Tx`
            # statement the body runs on this thread, COMMIT and the rollback paths —
            # so a body's waits land in the same counter the handle's metrics report.
            try:
                # The door's entry is this module's own I/O — on first write it creates
                # the `-wal`/`-shm` siblings — so out-of-space here classifies like every
                # other door: without this, a full disk at BEGIN surfaced as a
                # retryable-looking `OperationalError` from a process that kept going.
                connection = self._connect_write()
                _run(connection, _BEGIN, retries=self._limits.retries)
            except BaseException as error:
                failure = self._disk_full_failure(error)
                if failure is not None:
                    raise failure
                raise
            self._holder.in_transaction = True
            counts = dict(getattr(_OPEN_TX_TIERS, "tiers", None) or {})
            counts[self._tier_name] = counts.get(self._tier_name, 0) + 1
            _OPEN_TX_TIERS.tiers = counts
            try:
                yield Tx(connection, self._limits.retries, guard=self._guard)
            except BaseException as error:
                self._holder.in_transaction = False
                counts = dict(getattr(_OPEN_TX_TIERS, "tiers", None) or {})
                counts[self._tier_name] = counts.get(self._tier_name, 0) - 1
                _OPEN_TX_TIERS.tiers = counts
                try:
                    _run(connection, _ROLLBACK, retries=self._limits.retries)
                except sqlite3.Error:
                    pass  # the transaction is already gone; the caller's exception is the news
                # A body statement can hit the out-of-space condition as surely as a batch
                # can, and `FR-STORE-10` names no door exemption: classify here too, so a
                # disk-full transaction halts instead of surfacing a retryable-looking
                # `OperationalError` from a process that kept going. The body runs caller
                # code, so a raw OSError from *its own* I/O is not the store's disk-full —
                # only the store's sqlite errors classify here.
                failure = self._disk_full_failure(error, include_os_errors=False)
                if failure is not None:
                    raise failure
                raise
            self._holder.in_transaction = False
            counts = dict(getattr(_OPEN_TX_TIERS, "tiers", None) or {})
            counts[self._tier_name] = counts.get(self._tier_name, 0) - 1
            _OPEN_TX_TIERS.tiers = counts
            try:
                _run(connection, _COMMIT, retries=self._limits.retries)
            except sqlite3.OperationalError as error:
                # The body wrote; the commit failed. Roll back what could not be made
                # durable, then let the disk-full path decide: classify, halt, or re-raise
                # the original for anything that is not out-of-space.
                try:
                    _run(connection, _ROLLBACK, retries=self._limits.retries)
                except sqlite3.Error:
                    pass
                failure = self._disk_full_failure(error)
                if failure is not None:
                    raise failure
                raise

    def _disk_full_failure(self, error: BaseException, *,
                           include_os_errors: bool = True) -> DiskFullError | None:
        """If the error means the disk is full, record `DiskFullError`, stop the queue and halt the
        process.

        The queue door of `FR-STORE-10`'s sequence — shared with `purge_cohort`, whose door
        has no queue state to record and calls `_as_disk_full` plus the halt hook directly.
        The caller has already rolled the interrupted work back **whole** — results and
        their paired ledger transitions together, which is what keeps `CT-STORE-03`'s
        either-both-or-neither invariant true through the failure — so what the ledger
        carries at the halt is its last committed state: no result row without its
        transition, every in-flight unit still pending, and a resume that re-dispatches
        exactly what was lost. That is the bounded loss `CT-STORE-05` names (at most one
        commit window), not a new one.

        The stronger reading of the requirement — committing the batch's `work_unit`-only
        units after the rollback — is rejected deliberately: with the results rolled back,
        committing their status transitions would manufacture status-without-result states,
        and telling the paired from the unpaired would need this module to read parameter
        values, which is schema meaning it does not own. Recorded in the file docstring's
        decision table; `TC-STORE-13` is written against this declared semantics.

        Returns `None` for anything that is not out-of-space, so the caller re-raises the
        original unchanged. Returns the `DiskFullError` only when the halt hook returned —
        which happens only under an injected (test) hook; the production hook ends the
        process and this never returns.
        """
        failure = _as_disk_full(error, include_os_errors=include_os_errors)
        if failure is None:
            return None
        self._failures.append(failure)
        self._broken = failure
        with self._condition:
            # Wake anything blocked on backpressure: the queue is done, and a caller waiting
            # to enqueue must hit the broken state rather than wait out a drain that will
            # never come.
            self._condition.notify_all()
        halt = self._halt if self._halt is not None else _halt_process_on_disk_full
        halt(failure)  # never returns in production; see `DiskFullError`
        return failure

    # -- the writer side -----------------------------------------------------------------------

    def _ensure_writer(self) -> None:
        with self._condition:
            if self._thread is not None or self._stopping:
                return
            thread = threading.Thread(
                target=self._drain_forever, name="aeh-store-writer", daemon=True
            )
            # Started **inside** the lock, and published only once started. Publishing first and
            # starting after left a window in which `close()` read the attribute and called
            # `join()` on a thread that had not begun: `RuntimeError: cannot join thread before
            # it is started`. A shutdown racing a first `enqueue_write` is the ordinary shape of
            # a cancelled run, not an exotic one.
            thread.start()
            self._thread = thread

    def _note_depth_locked(self) -> None:
        """Track how long the queue has been at or above its threshold. Call while holding
        `_condition`."""
        if self._pending >= self._limits.write_queue_depth:
            if self._over_since is None:
                self._over_since = time.monotonic()
        else:
            self._over_since = None

    def _next_batch(self) -> list[WriteUnit] | None:
        """The next batch to commit, or `None` once the queue is stopped and empty.

        `FR-STORE-04`'s "at most 100 results or 5 seconds, whichever comes first" is two
        conditions on one queue, and both are checked here so one place decides. The age is the
        age of the **oldest** pending row, which is what makes the interval a durability bound:
        `NFR-STORE-02` promises at most one commit window of results is lost, and a window
        measured from the newest row would never close under steady load.
        """
        poll = self._limits.writer_poll_ms / 1000
        with self._condition:
            while True:
                if self._queue:
                    oldest_age_ms = (time.monotonic() - self._stamps[0]) * 1000.0
                    due = (
                        len(self._queue) >= self._limits.commit_batch
                        or oldest_age_ms >= self._limits.commit_interval_ms
                        or self._stopping
                    )
                    if due:
                        take = min(len(self._queue), self._limits.commit_batch)
                        batch = [self._queue.popleft() for _ in range(take)]
                        for _ in range(take):
                            self._stamps.popleft()
                        # `_pending` is untouched here: these rows are still not durable, only
                        # somewhere else. It drops in `_commit`'s `finally`, which is what keeps
                        # `depth` from dipping through the gap between the deque and the COMMIT.
                        self._note_depth_locked()
                        # Wake anyone blocked on backpressure: the depth just dropped.
                        self._condition.notify_all()
                        return batch
                elif self._stopping:
                    return None
                self._condition.wait(timeout=poll)

    def _drain_forever(self) -> None:
        while True:
            if self._broken is not None:
                # The halt hook returned (an injected, test-only hook) or broke the queue
                # from another thread: stop draining. FR-STORE-10's point is that the
                # process never continues with partial writes, and a drain that committed
                # the *next* batch after classifying a disk-full failure would be doing
                # exactly that.
                return
            batch = self._next_batch()
            if batch is None:
                return
            self._commit(batch)

    def _commit(self, batch: list[WriteUnit]) -> None:
        """Commit one batch in one transaction, measuring how long it took.

        A failure is **recorded, not swallowed**. The rows are already off the queue, so a writer
        that logged and moved on would let `write_queue_depth` reach zero with the rows gone -- a
        drain reporting success against data that was never written, which is the silent-failure
        trap `CLAUDE.md` seam 4 names. `close()` re-raises the first one and `store_metrics`
        counts them.

        A **disk-full** failure is the one kind that does more than record: the batch was
        rolled back whole in the `with` block below, and `_disk_full_failure` then records
        `DiskFullError`, makes the queue terminally refuse, and halts the process
        (`FR-STORE-10`). In production the halt never returns, so the `finally` bookkeeping
        after it does not run — the depth counter and the latency are left wherever the
        failure found them, which costs a dead process nothing. Under an injected (test)
        hook the bookkeeping completes and the drain loop stops on the broken state.
        """
        started = time.perf_counter()
        try:
            # The lock-wait window covers the whole batch: BEGIN through COMMIT, and the
            # rollback paths — a wait that postponed the commit is the wait the figure is for.
            with _counting_lock_waits(self._lock_waits), self._write_lock:
                connection = self._connect_write()
                _run(connection, _BEGIN, retries=self._limits.retries)
                try:
                    for unit in batch:
                        _run(connection, unit.statement, unit.params,
                             retries=self._limits.retries)
                except BaseException:
                    try:
                        _run(connection, _ROLLBACK, retries=self._limits.retries)
                    except sqlite3.Error:
                        pass
                    raise
                try:
                    _run(connection, _COMMIT, retries=self._limits.retries)
                except BaseException:
                    # A failed COMMIT can leave the transaction open (SQLITE_BUSY keeps it;
                    # a Python-level abort never ran it at all) — without this rollback the
                    # next batch's BEGIN fails with "cannot start a transaction within a
                    # transaction" and every batch after the first failure is lost. The
                    # transaction() path has always rolled back on COMMIT failure; the batch
                    # path gets the same courtesy. TS-08's commit-point injection found it.
                    try:
                        _run(connection, _ROLLBACK, retries=self._limits.retries)
                    except sqlite3.Error:
                        pass
                    raise
        except BaseException as error:  # noqa: BLE001 -- recorded; see the docstring
            failure = self._disk_full_failure(error)
            if failure is None:
                self._failures.append(error)
        finally:
            # Measured even on failure: a batch that took four seconds to fail is the number an
            # operator needs, and `NFR-STORE-02`'s window is about elapsed time, not success.
            self._last_latency_ms = (time.perf_counter() - started) * 1000.0
            with self._condition:
                self._pending -= len(batch)
                self._note_depth_locked()
                self._condition.notify_all()

    # -- lifecycle ------------------------------------------------------------------------------

    def close(self, *, timeout_s: float = 30.0) -> None:
        """Flush what is queued, stop the thread, then raise the first write failure.

        Flush rather than discard: `close()` is the controlled shutdown, and the bounded loss
        `NFR-STORE-02` permits is the loss to an *uncontrolled* kill. Dropping queued rows on a
        clean close would make the two indistinguishable.
        """
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout_s)
        if self._failures:
            raise self._failures[0]
