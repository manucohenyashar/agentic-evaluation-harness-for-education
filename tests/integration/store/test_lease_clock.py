"""Lease expiry derives from a monotonic counter a backwards wall clock cannot fool.

Cases `TC-STORE-14` (`FR-STORE-11`, P0, unit / boundary) and `RES-14` (§6.8), test plan
§5.3 and §6.8. Issue #15 (TS-09).

Rung 0 for the clock halves, rung 2 for the persistence half — all with the injected clock
the plan names ("exact value with an injected clock"). `FrozenClock` moves only when the test
moves it, and carries both halves the requirement needs: a monotonic term the backwards jump
cannot touch, and a wall clock the test can set arbitrarily — the very pair `FR-STORE-11`
exists to keep apart. (An earlier draft also asserted the double's own separation contract as
a standalone case; it was deleted as coverage-inflating — the double has its own harness
self-test, and the case's oracle is the lease arithmetic below, not the clock's.)

`Written ahead of implementation: yes` is stale — the lease clock landed with #12; the case
runs green by design. `TC-STORE-14` is the paired case #12's own DoD deferred to this issue
(recorded in PR #181's review as A1).

The persistence round-trip half runs at rung 2 (a real Tier D file) because "the persisted
monotonic counter" is a claim about what a *reopened* store restores, and restoring from
memory asserts nothing.
"""

from __future__ import annotations

import pytest

from aeh.store import LeaseClock, open_store
from tests.support.clock import EPOCH, FrozenClock

pytestmark = [pytest.mark.integration]

ISSUE = "#15"


def test_tc_store_14_expiry_is_exact_from_the_persisted_counter_across_a_restart(
    tmp_data_dir,
):
    """The persistence half, at rung 2: issue a 60-second lease, close, reopen with the wall
    clock moved backwards ten minutes, and read the restored counter. The restored tick is
    the persisted high-water plus the restore margin (`HARNESS_LEASE_RESTORE_MARGIN_S`, 1 s
    by default) — at or past every expiry ever issued, which is the property that makes every
    outstanding lease read expired on resume."""
    import datetime

    clock = FrozenClock(start=EPOCH)
    store = open_store(tmp_data_dir)
    lease_clock = LeaseClock(store, clock=clock)
    lease = lease_clock.issue(ttl_seconds=60.0)
    assert lease.expires_ticks == 60.0, (
        f"TC-STORE-14: expiry is {lease.expires_ticks}, expected exactly 60.0 — 'exact value "
        "with an injected clock' is the oracle, and a lease that expires anywhere other than "
        "issued+TTL hides the arithmetic the sweeper trusts."
    )

    # The process 'dies' here: the store is closed and the clock is replaced by one whose
    # wall clock has jumped backwards ten minutes while the monotonic term kept its value.
    store.close()
    clock.set_wall_clock(EPOCH - datetime.timedelta(minutes=10))
    clock.advance(0.5)

    reopened = open_store(tmp_data_dir)
    restored = LeaseClock(reopened, clock=clock)
    assert restored.ticks() >= lease.expires_ticks, (
        f"TC-STORE-14: the restored counter is {restored.ticks()}, below the outstanding "
        "lease's expiry (60.0). A clock that restores below a lease it was supposed to "
        "outlive reads the lease as live — CT-STORE-14's stranded-work failure, arrived at "
        "through the restart the margin exists to cover."
    )
    assert restored.expired(lease) is True, (
        "TC-STORE-14: an expired lease reads live after a backwards wall-clock jump across a "
        "restart. FR-STORE-11's whole sentence is this negation."
    )
    # A further lease is issued from the restored counter, and persists its higher expiry.
    second = restored.issue(ttl_seconds=10.0)
    assert second.expires_ticks > lease.expires_ticks
    reopened.close()

    third = LeaseClock(open_store(tmp_data_dir), clock=clock)
    assert third.ticks() >= second.expires_ticks, (
        "TC-STORE-14: the second restore lost the furthest expiry ever issued. Persisting "
        "the current tick instead of the high-water is the exact bug the class docstring "
        "records."
    )
    assert third.expired(lease) and third.expired(second)


def test_res_14_the_sweeper_trusts_expiry_across_the_jump(tmp_data_dir):
    """`RES-14` — the injected failure is the wall-clock jump; the promised behavior is that
    an expired lease never appears live. Phrased as the sweeper's decision: for every lease
    issued before the jump, `expired()` agrees with the monotonic arithmetic after it — and
    never with the wall clock."""
    import datetime

    clock = FrozenClock(start=EPOCH)
    store = open_store(tmp_data_dir)
    lease_clock = LeaseClock(store, clock=clock)
    leases = [lease_clock.issue(ttl_seconds=float(ttl)) for ttl in (5, 50, 500)]
    clock.advance(60)  # two of the three have expired, by monotonic arithmetic
    assert lease_clock.expired(leases[0]) and lease_clock.expired(leases[1])
    assert not lease_clock.expired(leases[2])

    clock.set_wall_clock(EPOCH - datetime.timedelta(minutes=10))  # the injected failure
    assert lease_clock.expired(leases[0]), "RES-14: the jump revived an expired lease"
    assert lease_clock.expired(leases[1])
    assert not lease_clock.expired(leases[2]), (
        "RES-14: the jump *expired* a live lease. The direction matters too: a counter that "
        "follows the wall clock strands work in both directions."
    )
    store.close()
