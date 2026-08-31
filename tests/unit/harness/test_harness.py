"""Self-tests for the harness this issue delivers.

Not `TC-*`-traced: these cover the parts of TS-00's Goal that sit underneath the three test
cases — "the socket guard fails a test on any unexpected connect, the store spy and injected
`Clock`/seeded `Random` are in place, and `RecordedFixtureProvider` is bound in the fast
tier".

They exist because shipping the socket guard untested would leave the one component every
"and no model call is made" assertion in the plan rests on (§8.1) unverified. Unlike the
three `TC-*` cases in this issue, this file tests code that exists now, so it is **green**.
"""

from __future__ import annotations

import socket
from datetime import timedelta

import pytest

from tests.support.clock import EPOCH, Clock, FrozenClock
from tests.support.guards import NetworkAccessError, SocketGuard
from tests.support.impl import (
    FIXTURE_PROVIDER_CLASS,
    NotImplementedYet,
    PROVIDER_MODULE,
    require,
)
from tests.support.store_spy import StoreSpy

# --- the socket guard ----------------------------------------------------------------------


def test_guard_blocks_create_connection_and_records_the_attempt(network_guard):
    with pytest.raises(NetworkAccessError):
        socket.create_connection(("example.invalid", 443), timeout=0.01)

    assert len(network_guard.attempts) == 1
    assert network_guard.attempts[0].api == "socket.create_connection"


def test_guard_blocks_socket_connect_and_records_the_attempt(network_guard):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkAccessError):
            sock.connect(("example.invalid", 443))
    finally:
        sock.close()

    assert [a.api for a in network_guard.attempts] == ["socket.connect"]


def test_assert_no_network_catches_an_attempt_the_caller_swallowed(network_guard):
    """The reason the guard records as well as raises.

    A provider that reached the network inside a `try/except Exception` would satisfy an
    exception-only assertion while having made the call. `TC-PROV-13`'s oracle is "exact
    exception **plus** socket guard" for exactly this reason.
    """
    try:
        socket.create_connection(("example.invalid", 443), timeout=0.01)
    except Exception:  # noqa: BLE001 — deliberately swallowing, as the bug would
        pass

    with pytest.raises(AssertionError, match="expected no network activity"):
        network_guard.assert_no_network()


def test_assert_no_network_passes_when_nothing_connected(network_guard):
    network_guard.assert_no_network()


@pytest.mark.live
def test_guard_stands_down_for_the_live_tier(network_guard):
    """The nightly E2/E3 cases exist to make real calls (§4.5), so the guard is not installed
    for them. Asserted rather than assumed: a guard that stayed on would make the live tier
    silently unrunnable."""
    assert network_guard is None
    assert socket.create_connection is not None  # the real function, unpatched


def test_guard_restores_the_socket_module_on_uninstall():
    original_connect = socket.socket.connect
    original_create = socket.create_connection

    guard = SocketGuard()
    guard.install()
    assert socket.socket.connect is not original_connect
    guard.uninstall()

    assert socket.socket.connect is original_connect
    assert socket.create_connection is original_create
    assert guard.installed is False


# --- the injected clock --------------------------------------------------------------------


def test_frozen_clock_does_not_move_on_its_own(frozen_clock):
    assert isinstance(frozen_clock, Clock)
    assert frozen_clock.now() == frozen_clock.now() == EPOCH
    assert frozen_clock.monotonic() == frozen_clock.monotonic()


def test_advance_moves_wall_clock_and_monotonic_together(frozen_clock):
    frozen_clock.advance(90)
    assert frozen_clock.now() == EPOCH + timedelta(seconds=90)
    assert frozen_clock.monotonic() == 90


def test_wall_clock_can_jump_backwards_while_monotonic_does_not(frozen_clock):
    """`FR-STORE-11`: lease expiry derives from a monotonic counter "so that a clock moving
    backwards on resume cannot make an expired lease appear live". The clock has to be able
    to express that scenario or the requirement cannot be tested at all."""
    frozen_clock.advance(300)
    monotonic_before = frozen_clock.monotonic()

    frozen_clock.set_wall_clock(EPOCH - timedelta(hours=1))

    assert frozen_clock.now() < EPOCH
    assert frozen_clock.monotonic() == monotonic_before


def test_advance_refuses_to_run_time_backwards(frozen_clock):
    with pytest.raises(ValueError, match="set_wall_clock"):
        frozen_clock.advance(-1)


# --- seeded randomness ---------------------------------------------------------------------


def test_seeded_random_is_reproducible_and_not_the_global(seeded_random):
    import random as global_random

    from tests.conftest import DEFAULT_SEED

    assert seeded_random is not global_random
    twin = global_random.Random(DEFAULT_SEED)
    assert [seeded_random.random() for _ in range(5)] == [twin.random() for _ in range(5)]


# --- the store spy -------------------------------------------------------------------------


def test_store_spy_records_writes_per_tier(store_spy):
    store_spy.cohort("c1").enqueue_write({"table": "work_unit"})
    store_spy.durable().enqueue_write({"table": "audit_record"})

    assert len(store_spy.writes) == 2
    assert [w.tier for w in store_spy.writes] == ["cohort:c1", "durable"]


def test_store_spy_flags_writes_made_inside_a_transaction(store_spy):
    """`CT-STORE-03` scopes atomicity to one `transaction()` body, so a case asserting a
    result and its ledger transition committed together needs to see the grouping."""
    handle = store_spy.cohort("c1")
    with handle.transaction() as tx:
        tx.enqueue_write({"table": "verdict"})
        tx.enqueue_write({"table": "work_unit", "status": "done"})

    assert [w.in_transaction for w in store_spy.writes] == [True, True]


def test_assert_no_writes_is_the_oracle_for_the_writes_nothing_clauses(store_spy):
    store_spy.assert_no_writes()  # nothing written yet

    store_spy.package("p1").enqueue_write({"table": "criterion"})
    with pytest.raises(AssertionError, match="expected zero writes"):
        store_spy.assert_no_writes()


def test_blob_spy_is_content_addressed_and_deduplicates(store_spy):
    """`CT-STORE-07`: identical bytes yield the same hash and store one copy."""
    blobs = store_spy.blobs()
    first = blobs.put(b"page raster bytes")
    second = blobs.put(b"page raster bytes")

    assert first == second
    assert first.startswith("sha256:")
    assert blobs.get(first) == b"page raster bytes"


# --- the fast tier's model boundary ---------------------------------------------------------


def test_fast_tier_binds_the_recorded_fixture_provider():
    """§4.2: the fast tier's model boundary is `RecordedFixtureProvider` — a shipped
    implementation, not a test fake. Asserting the *binding* keeps the wiring honest before
    the class itself exists (issue #18)."""
    assert FIXTURE_PROVIDER_CLASS == "RecordedFixtureProvider"
    assert PROVIDER_MODULE.endswith(".prov")


def test_require_reports_a_missing_implementation_as_a_stated_failure():
    """The mechanism that keeps written-ahead tests red *for the right reason*: a clear
    "does not exist yet" failure naming the blocking issue, rather than a collection error
    that asserts nothing (see `tests/support/impl.py`)."""
    with pytest.raises(NotImplementedYet, match=r"does not exist yet \(blocked on #18\)"):
        require(PROVIDER_MODULE, "RecordedFixtureProvider", issue="#18")


def test_require_does_not_mask_a_real_import_error_inside_an_existing_module():
    """A `ModuleNotFoundError` raised from *inside* a module that does exist is a defect, not
    a not-yet-implemented marker, and must surface as itself."""
    with pytest.raises(ModuleNotFoundError):
        require("tests.support.broken_import_fixture", issue="#18")
