"""The store's clocks, and leases timed by a monotonic counter persisted with the wall clock."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .errors import ConfigurationProblem
from .sqlite_store import SqliteStore
from .statements import STATEMENTS


# --- the monotonic lease clock -------------------------------------------------------------------


class Clock(Protocol):
    """Wall time and monotonic time, separately (`FR-STORE-11`).

    Two methods rather than one because the requirement is about the difference between them:
    lease expiry derives from the monotonic counter, and the wall clock is recorded beside it for
    an operator reading the row. A single `now()` cannot express that.

    Declared here rather than imported: `tests/support/clock.py` has the matching `FrozenClock`,
    but that is test support and production code cannot import it. Structural typing means the
    test double satisfies this without either file knowing about the other, which is what
    `CLAUDE.md` seam 2 asks for.
    """

    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class SystemClock:
    """The production `Clock`. UTC, and `time.monotonic` for the counter."""

    __slots__ = ()

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()


@dataclass(frozen=True)
class Lease:
    """A claim with an expiry, expressed in the store's own monotonic ticks.

    `expires_ticks` is what `expired()` compares. `issued_at` is the wall clock at issue and is
    for an operator reading a ledger row -- it is deliberately *not* what expiry is computed
    from, which is the whole of `FR-STORE-11`.
    """

    expires_ticks: float
    issued_ticks: float
    issued_at: datetime
    ttl_seconds: float


class LeaseClock:
    """Lease expiry from a monotonic counter persisted alongside wall clock (`FR-STORE-11`).

    `CT-STORE-14` states the failure this exists to prevent: NTP corrects the host clock
    backwards while a run is resumed, and every expired lease reads as live -- so `M-ORCH`'s
    sweeper reclaims nothing and the work is stranded, or it reclaims twice and the work is
    duplicated. The test plan calls the bug *"a 'simplification' to `datetime.now()`"*.

    **What is persisted is the furthest expiry ever issued**, not the current tick. Persisting
    the current tick is the obvious design and it is wrong: a lease issued at tick 100 with a
    60-second TTL expires at 160, the process runs on to tick 200 and is killed, and a restore
    from 100 reads that lease as live again. Recording 160 at the moment of issue means the
    restored counter is at or past every expiry that was ever issued.

    **So a restart expires every outstanding lease, and that is the correct direction.** There is
    no server process here (§3.3, `NFR-STORE-03`), so a lease outstanding at restart was held by
    a process that is gone. Reclaiming it is recoverable; believing it live is the stranded work
    `CT-STORE-14` names. The conservatism is stated rather than hidden because it is a real
    behaviour a caller can observe.

    The write is **synchronous, through `transaction()`**, not `enqueue_write`. `CT-STORE-02`
    makes the queue asynchronous, and a counter that an uncontrolled kill can lose is a counter
    that restores lower than the leases it was supposed to outlive -- which is the bug, arrived
    at from the other side.
    """

    __slots__ = ("_clock", "_durable", "_margin_s", "_origin", "_persisted_ticks")

    #: The injected clock, so `lease_clock` can tell a repeat call from a conflicting one.

    def __init__(self, store: SqliteStore, clock: Clock | None = None) -> None:
        self._clock = clock if clock is not None else SystemClock()
        self._durable = store.durable()
        self._margin_s = store.limits.lease_restore_margin_s
        restored = self._restore()
        # The margin covers the instant between computing an expiry and committing it: a kill
        # in that window would otherwise restore just short of a lease that had been issued.
        self._persisted_ticks = restored + (self._margin_s if restored else 0.0)
        self._origin = self._clock.monotonic()

    @property
    def clock(self) -> Clock:
        return self._clock

    # -- the counter --------------------------------------------------------------------------

    def ticks(self) -> float:
        """The current monotonic tick: what was persisted, plus this process's own elapsed time.

        Never derived from the wall clock, in either term. Moving the host clock backwards
        changes `now()` and changes nothing here, which is `CT-STORE-14`'s assertion.
        """
        return self._persisted_ticks + (self._clock.monotonic() - self._origin)

    def issue(self, ttl_seconds: float) -> Lease:
        """Issue a lease expiring `ttl_seconds` from now, and persist its expiry first."""
        if ttl_seconds <= 0:
            raise ConfigurationProblem(
                f"a lease TTL must be positive, got {ttl_seconds}. A lease that expires on issue "
                "is a work unit M-ORCH reclaims from itself."
            )
        issued_ticks = self.ticks()
        expires_ticks = issued_ticks + ttl_seconds
        issued_at = self._clock.now()
        # Persisted *before* the lease is returned. A lease handed to a caller and then lost to a
        # kill before its expiry reached the database is the one case that could come back live.
        self._persist(expires_ticks, issued_at)
        return Lease(
            expires_ticks=expires_ticks, issued_ticks=issued_ticks, issued_at=issued_at,
            ttl_seconds=float(ttl_seconds),
        )

    def expired(self, lease: Lease) -> bool:
        """Whether `lease` has expired. The comparison `M-ORCH`'s sweeper trusts."""
        return self.ticks() >= lease.expires_ticks

    # -- persistence ---------------------------------------------------------------------------

    def _restore(self) -> float:
        rows = self._durable.query(STATEMENTS["select_lease_clock"])
        return float(rows[0]["ticks"]) if rows else 0.0

    def _persist(self, ticks: float, wall: datetime) -> None:
        """Raise the persisted high water to `ticks`. **The max is SQL's, not Python's.**

        An earlier form read the stored value, took `max()` in Python and wrote the result. That
        is a TOCTOU, and review measured it: eight threads issuing leases interleave read /
        read / write-high / write-low, the furthest expiry is lost, and forty leases that were
        outstanding at the kill come back reading *live* after the restart — verbatim the
        `CT-STORE-14` failure this class exists to prevent, arrived at through the one operation
        that was supposed to guarantee against it.

        `MAX(excluded.ticks, store_lease_clock.ticks)` inside the upsert makes the comparison and
        the write one statement under one `BEGIN IMMEDIATE`, so the counter cannot go backwards
        however many threads are issuing. The wall clock is *not* maxed: it is the human-readable
        note beside the counter, and the most recent one is the useful one.
        """
        with self._durable.transaction() as tx:
            # Through the registry rather than the module constant, which is the shape
            # `sql_scan` sanctions for an execute path — see `STATEMENTS`. `Tx.execute` is this
            # module's own declared-statement API and delegates to `_run`, so the number of
            # places a statement actually reaches SQLite is still one; the *call* is a second
            # site the walker can see, and it is listed in `KNOWN_EXECUTE_SITES` with this note.
            tx.execute(STATEMENTS["upsert_lease_clock"], ticks=ticks,
                       wall_clock=wall.isoformat())


def lease_clock(store: SqliteStore, clock: Clock | None = None) -> LeaseClock:  # noqa: D401
    """The store's monotonic lease clock (`FR-STORE-11`, `CT-STORE-14`).

    `clock` is the injection point (`CLAUDE.md` seam 2, test plan §4.2): a `FrozenClock` whose
    wall time can be moved backwards while its monotonic counter is not is the only way to assert
    `CT-STORE-14`, and a module that reached for `time.monotonic()` directly could not be told to.

    Not a `Store` member: §3.3 closes that protocol at five, and `TC-STORE-C01` calls the closed
    list "the door through which every other clause here gets bypassed". Design §3.3 names no
    accessor for the lease clock at all, which is reported as a gap — see
    `tests/support/store_api.py`.

    **One clock per store, cached.** Constructing a second one is not a cheap repeat of the
    first: the restore deliberately starts the counter *past* the furthest expiry ever issued,
    so a fresh instance in a live process reads every outstanding lease as expired — review
    measured a one-hour lease held by a live clock reading expired through a clock built one
    line later. That is the other half of `CT-STORE-14`'s sentence, "it reclaims twice and the
    work is duplicated". Reading as an accessor by analogy with `store_metrics` is exactly why
    it has to behave like one.

    Passing a *different* `clock` to a store that already has one raises rather than silently
    ignoring it: the second caller would otherwise believe it had injected a clock and be
    reading a counter driven by the first.
    """
    existing = store.lease_clock_instance
    if existing is not None:
        if clock is not None and clock is not existing.clock:
            raise ConfigurationProblem(
                "this store already has a lease clock, driven by a different Clock. A second "
                "instance would restore its counter past every outstanding lease and reclaim "
                "work that is genuinely held (CT-STORE-14). Pass the clock on the first call, "
                "or open a separate store."
            )
        return existing
    created = LeaseClock(store, clock)
    store.attach_lease_clock(created)
    return created
