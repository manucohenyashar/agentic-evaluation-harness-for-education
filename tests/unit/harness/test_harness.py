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
    CONF_MODULE,
    FIXTURE_PROVIDER_CLASS,
    IMPLEMENTATION_PACKAGE,
    NotImplementedYet,
    PROVIDER_MODULE,
    WRITTEN_AHEAD_BLOCKERS,
    blocker_is_resolved,
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


def test_guard_blocks_dns_resolution_of_a_remote_host(network_guard):
    """A hostname lookup is already egress, and on the air-gapped tier (§4.5 E5) it is exactly
    what must not happen. Local names still resolve, so nothing that looks up `localhost`
    during setup is broken by the guard."""
    with pytest.raises(NetworkAccessError):
        socket.getaddrinfo("example.invalid", 80)

    assert [a.api for a in network_guard.attempts] == ["socket.getaddrinfo"]
    assert socket.getaddrinfo("localhost", 80)  # allowed: never leaves the host


def test_guard_blocks_udp_which_never_calls_connect(network_guard):
    """UDP needs no `connect()`, so `sendto` is its own egress path."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(NetworkAccessError):
            sock.sendto(b"ping", ("127.0.0.1", 9))
    finally:
        sock.close()

    assert [a.api for a in network_guard.attempts] == ["socket.sendto"]


def test_guard_restores_the_socket_module_on_uninstall():
    original_connect = socket.socket.connect
    original_create = socket.create_connection

    original_getaddrinfo = socket.getaddrinfo

    guard = SocketGuard()
    guard.install()
    assert socket.socket.connect is not original_connect
    guard.uninstall()

    assert socket.socket.connect is original_connect
    assert socket.create_connection is original_create
    assert socket.getaddrinfo is original_getaddrinfo
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


def test_a_transaction_that_raises_leaves_nothing_in_the_write_log(store_spy):
    """`CT-STORE-03`: a work unit's result and its ledger transition are "both present or both
    absent after any crash". A spy that recorded writes from an aborted body would make the
    absent half untestable — a case asserting nothing was committed would pass vacuously."""
    with pytest.raises(RuntimeError):
        with store_spy.cohort("c1").transaction() as tx:
            tx.enqueue_write({"table": "verdict"})
            raise RuntimeError("crash mid-transaction")

    store_spy.assert_no_writes()


def test_blob_spy_is_content_addressed_and_deduplicates_across_handles(store_spy):
    """`CT-STORE-07`: identical bytes yield the same hash and store one copy, and `get`
    resolves any hash `put` returned "for the lifetime of the owning tier" — so a second
    `blobs()` handle sees the same namespace, as the real content-addressed directory does."""
    first = store_spy.blobs().put(b"page raster bytes")
    second = store_spy.blobs().put(b"page raster bytes")

    assert first == second
    assert first.startswith("sha256:")
    assert store_spy.blobs().get(first) == b"page raster bytes"
    # Deduplicated on write (FR-STORE-06): one copy, therefore one write.
    assert len(store_spy.writes) == 1


# --- the fast tier's model boundary ---------------------------------------------------------


def test_fast_tier_binds_the_recorded_fixture_provider(make_fixture_provider, monkeypatch):
    """§4.2: the fast tier's model boundary is `RecordedFixtureProvider` — a shipped
    implementation, not a test fake.

    Exercises the real wiring by standing a minimal `aeh.prov` up in `sys.modules` and
    asserting the factory resolves *that class* and hands it the fixture directory. Asserting
    the two constants instead would be a tautology — they are assigned those literals two
    files away — and this is the only non-`writtenahead` coverage of the Goal's third clause,
    so a tautology here would leave the gate blind to it.
    """
    import sys
    import types

    constructed: dict[str, object] = {}

    class _StubRecordedFixtureProvider:
        def __init__(self, fixture_dir):
            constructed["fixture_dir"] = fixture_dir

    package = types.ModuleType("aeh")
    package.__path__ = []  # type: ignore[attr-defined]
    module = types.ModuleType(PROVIDER_MODULE)
    setattr(module, FIXTURE_PROVIDER_CLASS, _StubRecordedFixtureProvider)

    # setitem, not a plain assignment: monkeypatch restores sys.modules at teardown, so the
    # stub cannot leak into a shuffled neighbour — including the staleness check below, which
    # would otherwise see #18 as landed.
    monkeypatch.setitem(sys.modules, "aeh", package)
    monkeypatch.setitem(sys.modules, PROVIDER_MODULE, module)

    provider = make_fixture_provider()

    assert isinstance(provider, _StubRecordedFixtureProvider)
    assert constructed["fixture_dir"].is_dir()


def test_written_ahead_markers_are_removed_once_their_blocker_lands(repo_root):
    """The `writtenahead` marker excludes a test from `TEST_CMD` (scripts/test.sh), which is
    what lets the Stop-hook gate be green while written-ahead tests are correctly red.

    Nothing else notices when a blocking issue closes, so a P0 case could sit outside the gate
    forever. This assertion is that notice: it fails the moment a blocker resolves and names
    the file whose marker must come off.
    """
    landed = []
    for issue, (kind, target, test_files) in WRITTEN_AHEAD_BLOCKERS.items():
        if blocker_is_resolved(kind, target, repo_root):
            landed.append(f"{issue} ({target}) -> unmark {', '.join(test_files)}")

    assert not landed, (
        "these blockers have landed, so their tests must lose the `writtenahead` marker and "
        "rejoin TEST_CMD — remove the marker, never the test (test plan §8.2):\n  "
        + "\n  ".join(landed)
    )


def _carries_writtenahead_marker(path) -> bool:
    """Whether `path` actually applies `pytest.mark.writtenahead`, at module or test level."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, ast.Attribute)
        and node.attr == "writtenahead"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        for node in ast.walk(tree)
    )


def test_every_writtenahead_test_file_is_registered_as_blocked(repo_root):
    """The registry must be **complete**, not merely correct about what is in it.

    `WRITTEN_AHEAD_BLOCKERS` fires when a blocker lands — but nothing noticed a marked test that
    was never registered, and that test would sit outside `TEST_CMD` permanently. Which is the
    precise failure the registry exists to prevent, arriving through the one door it did not
    watch.
    """
    registered = {
        path.split("::")[0]
        for _, _, files in WRITTEN_AHEAD_BLOCKERS.values()
        for path in files
    }

    # Detected by AST, not by grepping for the name. Every file in this suite *discusses* the
    # marker in a docstring, and this file names it in a comment — a substring match flagged
    # both, including itself. An `Attribute` node cannot appear in prose.
    marked = {
        str(path.relative_to(repo_root)).replace("\\", "/")
        for path in (repo_root / "tests").rglob("test_*.py")
        if _carries_writtenahead_marker(path)
    }

    assert marked <= registered, (
        "these files carry `writtenahead` but no entry in WRITTEN_AHEAD_BLOCKERS, so nothing "
        "will ever tell anyone to unmark them:\n  " + "\n  ".join(sorted(marked - registered))
    )


def test_every_registered_blocker_names_a_file_that_exists(repo_root):
    """A registry entry pointing at a renamed or deleted file is a gate that fires and then
    names nothing actionable — indistinguishable, to whoever reads the failure, from a
    false alarm they should ignore."""
    missing = [
        path
        for _, _, files in WRITTEN_AHEAD_BLOCKERS.values()
        for path in files
        if not (repo_root / path.split("::")[0]).exists()
    ]

    assert not missing, "WRITTEN_AHEAD_BLOCKERS names files that do not exist: " + ", ".join(missing)


def test_blocker_is_resolved_detects_a_symbol_landing_inside_an_existing_module(repo_root):
    """The `symbol` kind, which is what a module split across several stories needs.

    `aeh.conf` has existed since #4, so a `module`-kind blocker on it would read as resolved
    while `RunConfig.profile_summary` (#5) and `rehydrate_run_config` (#6) are still absent —
    and their cases would be told to leave `writtenahead` months early.
    """
    assert blocker_is_resolved("symbol", f"{CONF_MODULE}:resolve_run_config", repo_root) is True
    assert blocker_is_resolved("symbol", f"{CONF_MODULE}:RunConfig.__post_init__", repo_root) is True
    assert blocker_is_resolved("symbol", f"{CONF_MODULE}:not_a_real_name", repo_root) is False
    assert blocker_is_resolved("symbol", f"{CONF_MODULE}:RunConfig.not_a_method", repo_root) is False
    assert blocker_is_resolved("symbol", "aeh.does_not_exist:anything", repo_root) is False


def test_blocker_is_resolved_refuses_an_unknown_kind(repo_root):
    """A `kind` with no branch must raise, not read as unresolved.

    Reading it as unresolved is the silent direction: the gate would never fire, and the case
    it guards would sit outside `TEST_CMD` forever — the exact failure the registry exists to
    prevent."""
    with pytest.raises(ValueError, match="unknown written-ahead blocker kind"):
        blocker_is_resolved("commit", "abc123", repo_root)


def test_require_reports_a_missing_implementation_as_a_stated_failure():
    """The mechanism that keeps written-ahead tests red *for the right reason*: a clear
    "does not exist yet" failure naming the blocking issue, rather than a collection error
    that asserts nothing (see `tests/support/impl.py`).

    The target is a module that will **never** land, as in the `symbol` case above. This
    assertion was written against `aeh.prov` while it was still absent, and #18 landing it
    turned the self-test red — a stand-in for "does not exist" cannot be a module somebody is
    on their way to writing.
    """
    absent = f"{IMPLEMENTATION_PACKAGE}.does_not_exist"
    with pytest.raises(NotImplementedYet, match=r"does not exist yet \(blocked on #18\)"):
        require(absent, "RecordedFixtureProvider", issue="#18")


def test_require_does_not_mask_a_real_import_error_inside_an_existing_module():
    """A `ModuleNotFoundError` raised from *inside* a module that does exist is a defect, not
    a not-yet-implemented marker, and must surface as itself."""
    with pytest.raises(ModuleNotFoundError):
        require("tests.support.broken_import_fixture", issue="#18")
