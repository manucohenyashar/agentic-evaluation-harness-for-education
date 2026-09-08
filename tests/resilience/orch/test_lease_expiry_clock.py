"""`RES-15` — a worker stops heartbeating: the lease expires and the unit returns to
`pending` — exact transition at the lease boundary and not before, across a clock
perturbed backwards.

This is the #58 carry-forward the pairing story disclosed: no `M-ORCH`
clock-perturbation case existed, and the natural shape for the injected-clock expiry
cases is exactly this — perturb the injected clock, assert the expiry behavior. The
boundary itself (advance `ORCH_LEASE_SECONDS - 1` → held; one more second → requeued)
is `TC-ORCH-05`'s oracle and is **not** re-asserted here beyond what the perturbation
needs as its control; what this file adds is the wall-clock dimension `FR-STORE-11`
exists for:

- the sweeper's comparison is the store's persisted **monotonic** counter, never the
  wall clock — so a wall clock moved backwards while a lease is live changes nothing
  the sweeper reads;
- a lease **issued after** the wall clock moved backwards still expires on the
  monotonic boundary — a wall-clock sweeper would read its recorded expiry as far in
  the future and strand the work (`CT-STORE-14`'s named failure, arrived at from the
  other side);
- the requeue clears the lease columns and keeps the attempts — the failure history
  belongs to the unit, the lease to the moment.

Isolation: rung 2/3 — real store, real `Orchestrator`, injected `FrozenClock`
(test plan §4.2's seam for lease expiry; §4.6 forbids sleep as synchronization, and
the clock seam is what makes this case possible without it).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from aeh.store import open_store
from tests.support.clock import EPOCH, FrozenClock
from tests.support.impl import ORCH_MODULE, require
from tests.support.orch_run import seed_run

pytestmark = pytest.mark.integration

ISSUE = "#58"

_SUBMISSIONS = tuple(f"SYN-{i:03d}" for i in range(1, 6))
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)


def _rows(store, run_id: str, status: str) -> list:
    return store.cohort("c-2026-7B-orch").query(
        "SELECT * FROM work_unit WHERE run_id = :r AND status = :s",
        r=run_id,
        s=status,
    )


def test_res_15_live_lease_survives_a_backwards_wall_clock(tmp_data_dir):
    """A live lease, then the wall clock jumps backwards past the expiry: the sweeper
    holds the lease — the monotonic counter governs, and nothing about the wall clock
    can reclaim work that is genuinely held."""
    Orchestrator, ORCH_LEASE_SECONDS = require(
        ORCH_MODULE, "Orchestrator", "ORCH_LEASE_SECONDS", issue=ISSUE
    )
    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
        clock = FrozenClock()
        orch = Orchestrator(store, clock=clock)

        won = orch.lease("worker-a", "extract", 10)
        assert won
        held = {unit.work_id for unit in won}

        # Short of the boundary AND with the wall clock thrown an hour backwards:
        # the lease must survive both.
        clock.advance(ORCH_LEASE_SECONDS - 1)
        clock.set_wall_clock(EPOCH - timedelta(hours=1))
        orch.sweep_expired_leases()
        assert {row["work_id"] for row in _rows(store, run_id, "leased")} == held, (
            "a backwards wall clock (or an early sweep) reclaimed a live lease — "
            "a slow-but-alive worker would be double-run, which is the failure "
            "FR-STORE-11's monotonic counter exists to prevent"
        )
    finally:
        store.close()


def test_res_15_expiry_lands_on_the_monotonic_boundary_with_the_clock_in_the_past(
    tmp_data_dir,
):
    """At the monotonic boundary the lease expires even though the wall clock is
    still in the past — a sweeper reading wall-clock expiries would strand the unit
    (its recorded expiry is an hour away); the requeue clears the lease columns and
    keeps the attempts."""
    Orchestrator, ORCH_LEASE_SECONDS = require(
        ORCH_MODULE, "Orchestrator", "ORCH_LEASE_SECONDS", issue=ISSUE
    )
    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
        clock = FrozenClock()
        orch = Orchestrator(store, clock=clock)

        won = orch.lease("worker-a", "extract", 10)
        held = {unit.work_id for unit in won}

        clock.advance(ORCH_LEASE_SECONDS - 1)
        clock.set_wall_clock(EPOCH - timedelta(hours=1))
        clock.advance(1)  # exactly the boundary; wall clock still an hour in the past
        orch.sweep_expired_leases()

        assert _rows(store, run_id, "leased") == [], (
            "an expired lease was still held after the boundary passed — with the "
            "wall clock in the past, only the monotonic comparison can requeue it"
        )
        requeued = {
            row["work_id"]: row
            for row in _rows(store, run_id, "pending")
            if row["stage"] == "extract"
        }
        assert set(requeued) == held, (
            "the sweeper did not return the expired leases to pending with the "
            "wall clock held in the past — the comparison reads the wall clock, "
            "which is CT-STORE-14's named failure"
        )
        for work_id, row in requeued.items():
            assert row["attempts"] == 0, (
                f"unit {work_id[:12]}: a lease expiry consumed an attempt — the "
                "attempt counter is FR-ORCH-18's ceiling input, not the lease's"
            )
            assert (
                row["lease_owner"] is None
                and row["lease_expires_ticks"] is None
                and row["lease_expires_at"] is None
            ), (
                f"unit {work_id[:12]}: the requeue left a lease column set — a "
                "stale lease on a pending unit makes the next claim's exclusivity "
                "unprovable"
            )
    finally:
        store.close()


def test_res_15_lease_issued_after_the_backwards_jump_still_expires(tmp_data_dir):
    """A lease issued **after** the wall clock moved backwards records a wall expiry
    an hour before its predecessor's — and still expires on the monotonic boundary.
    This is the discrimination a wall-clock sweeper cannot pass: its comparison
    would read the recorded expiry as the future and strand the work."""
    Orchestrator, ORCH_LEASE_SECONDS = require(
        ORCH_MODULE, "Orchestrator", "ORCH_LEASE_SECONDS", issue=ISSUE
    )
    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
        clock = FrozenClock()
        orch = Orchestrator(store, clock=clock)

        first = orch.lease("worker-a", "extract", 2)
        assert first
        first_expiry = _rows(store, run_id, "leased")[0]["lease_expires_at"]

        # The NTP correction: wall time jumps backwards an hour; monotonic untouched.
        clock.set_wall_clock(EPOCH - timedelta(hours=1))
        clock.advance(1)

        second = orch.lease("worker-b", "extract", 2)
        assert second, (
            "the fixture's second worker leased nothing — the discrimination needs "
            "a lease ISSUED after the perturbation"
        )
        rows = {row["work_id"]: row for row in _rows(store, run_id, "leased")}
        second_expiry = rows[second[0].work_id]["lease_expires_at"]
        assert second_expiry < first_expiry, (
            "a lease issued after the backwards jump did not record the perturbed "
            "wall time — the fixture does not exercise the discrimination this "
            "case exists for"
        )

        # Monotonic crosses the second lease's boundary; the wall clock still says
        # an hour before the FIRST lease's expiry. The sweeper must requeue on the
        # ticks — a wall-clock comparison reads both expiries as future and holds
        # dead leases live.
        clock.advance(ORCH_LEASE_SECONDS)
        orch.sweep_expired_leases()
        assert _rows(store, run_id, "leased") == [], (
            "a lease whose wall expiry reads as future but whose monotonic expiry "
            "passed was not requeued — the sweeper compares the wall clock, and "
            "the backwards jump stranded the work (CT-STORE-14)"
        )
        extract_pending = {
            row["work_id"]
            for row in _rows(store, run_id, "pending")
            if row["stage"] == "extract"
        }
        assert {u.work_id for u in first} | {u.work_id for u in second} <= (
            extract_pending
        ), "the requeued extract units are not back in pending after the sweep"
    finally:
        store.close()
