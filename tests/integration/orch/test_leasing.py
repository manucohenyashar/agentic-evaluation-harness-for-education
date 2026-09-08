"""`TC-ORCH-05` and `TC-ORCH-09` — the lease is a claim with an owner and an expiry, and
an abandoned lease returns to `pending` after `ORCH_LEASE_SECONDS` and not before.

- `TC-ORCH-05` (`FR-ORCH-04`, integration / rung 2, concurrency): two workers claim the
  same unit — exactly one wins; the unit carries an owner and an expiry; the sweeper
  returns the abandoned lease (a worker that never heartbeats) to `pending` after
  `ORCH_LEASE_SECONDS` and not before. Oracle: **exact value with an injected clock**
  (`tests/support/clock.py`'s `FrozenClock` — §4.2's seam for lease expiry; §4.6 forbids
  sleep as synchronization, and this is the case it exists for).
- `TC-ORCH-09` (`FR-ORCH-04`, integration / rung 2, **slow**): a **real elapsed** lease
  expiry, not a frozen clock — the single case in the plan permitted to wait on wall-clock
  time (§4.6), confirming the injected-clock cases are not hiding a real-time bug. Oracle:
  exact value.

**Written ahead of #58** (leasing, heartbeats, the expiry sweeper and the failure
taxonomy), keyed on `aeh.orch:ORCH_LEASE_SECONDS` — the knob the design's Configuration
section names (detailed-design §3.7), which appears in no Interfaces block and could not
exist before the sweeper that reads it. **Landed with #58**; the assumed surface was
reconciled as follows, all disclosed on the PR:

- `lease`, `heartbeat`, `sweep_expired_leases` and the `clock=` constructor seam shipped
  exactly as assumed here.
- The lease surface **self-heals the enumeration**: this module leases without a separate
  `enumerate_units` step, and a claim pass that finds nothing triggers the idempotent
  base enumeration (`FR-ORCH-02`'s no-bookkeeping rule applied to leasing) before
  claiming again.
- The name-agnostic row scan reads `tuple(row)` rather than `row.values()` — the store's
  query returns `sqlite3.Row`, which iterates its values; the assertion's semantics are
  unchanged.

**Interface this case assumes of #58**, listed so it is reconciled deliberately rather
than discovered (the `record_run_start` precedent):

| Name | Status |
|---|---|
| `Orchestrator.lease(worker_id, stage, n)` | design §3.7 Interfaces — a Protocol member #58 must ship on the concrete class |
| `Orchestrator.heartbeat(work_id)` | **assumed here** — FR-ORCH-04's own word; not in the Interfaces block |
| `Orchestrator.sweep_expired_leases()` | **assumed here** — "a sweeper shall return units whose lease has expired to pending" names the function, not the method |
| `Orchestrator(store, clock=...)` | **assumed here** — clock.py: "The seam every time-dependent module takes as a constructor argument" |
| `HARNESS_ORCH_LEASE_SECONDS` | **assumed here** — the env gate over `ORCH_LEASE_SECONDS` (CLAUDE.md seam 3), used by TC-ORCH-09 only |
| `work_unit` columns carrying the owner and the expiry | FR-ORCH-04's nouns; asserted name-agnostically (some column holds the owner id, some holds an expiry past the lease time) |
"""

from __future__ import annotations

import os

import pytest

from aeh.store import open_store
from tests.support.clock import FrozenClock
from tests.support.impl import ORCH_MODULE, require
from tests.support.orch_run import seed_run

pytestmark = pytest.mark.integration

ISSUE = "#58"

_SUBMISSIONS = ("SYN-001", "SYN-002", "SYN-003")
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)


def _leased_units(store, run_id: str) -> list[dict]:
    return store.cohort("c-2026-7B-orch").query(
        "SELECT * FROM work_unit WHERE run_id = :r AND status = 'leased'",
        r=run_id,
    )


def test_tc_orch_05_one_worker_wins_the_claim_and_the_abandoned_lease_requeues(
    tmp_data_dir,
):
    """`TC-ORCH-05` — claim exclusivity, owner+expiry recorded, and the sweeper returns
    an abandoned lease to `pending` after `ORCH_LEASE_SECONDS` and not before, under an
    injected clock."""
    Orchestrator, ORCH_LEASE_SECONDS = require(
        ORCH_MODULE, "Orchestrator", "ORCH_LEASE_SECONDS", issue=ISSUE
    )
    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
        clock = FrozenClock()
        orch = Orchestrator(store, clock=clock)

        # Worker A claims every extract unit; worker B claims the same stage immediately
        # after. Exactly one worker wins each claim: B's lease returns none of the units
        # A holds.
        won_by_a = orch.lease("worker-a", "extract", 10)
        assert won_by_a, "no unit was handed to the first worker"
        won_by_b = orch.lease("worker-b", "extract", 10)
        ids_a = {unit.work_id for unit in won_by_a}
        ids_b = {unit.work_id for unit in won_by_b}
        assert not ids_a & ids_b, (
            f"both workers hold {ids_a & ids_b} — a unit claimed twice at once is a "
            "result that can be written twice (FR-ORCH-04's exclusivity half)"
        )

        # The unit carries an owner and an expiry: asserted name-agnostically over the
        # row (see the module docstring's interface table) — some column holds the owner
        # id, some holds an expiry after the lease moment.
        leased = _leased_units(store, run_id)
        assert {row["work_id"] for row in leased} == ids_a, (
            "the ledger does not hold the claimed units as leased"
        )
        for row in leased:
            assert "worker-a" in tuple(row), (
                f"leased unit {row['work_id'][:12]} records no owner — an abandoned "
                "lease that cannot name its worker is unauditable"
            )
            expiries = [
                value for value in tuple(row)
                if isinstance(value, str) and "T" in value and ":" in value
            ]
            assert expiries, (
                f"leased unit {row['work_id'][:12]} records no expiry — without one the "
                "sweeper cannot distinguish an abandoned lease from live work"
            )

        # Worker A never heartbeats: the lease is abandoned. Before the knob's value has
        # elapsed the sweeper must NOT requeue — a lease reclaimed early double-runs a
        # worker that was merely slow.
        clock.advance(ORCH_LEASE_SECONDS - 1)
        orch.sweep_expired_leases()
        assert {row["work_id"] for row in _leased_units(store, run_id)} == ids_a, (
            f"the sweeper requeued a lease with {ORCH_LEASE_SECONDS - 1}s of lease "
            "left — 'after ORCH_LEASE_SECONDS and not before' is the exact oracle"
        )

        # One second later the lease is exactly expired: the sweeper returns it to
        # pending, and the unit is claimable again — by the other worker.
        clock.advance(1)
        orch.sweep_expired_leases()
        assert _leased_units(store, run_id) == [], (
            "an expired lease was not returned to pending — the run would stall on a "
            "worker that died mid-unit"
        )
        reclaimed_by_b = orch.lease("worker-b", "extract", 10)
        assert {unit.work_id for unit in reclaimed_by_b} == ids_a, (
            "the requeued units were not claimable by the next worker"
        )
    finally:
        store.close()


def test_tc_orch_05_heartbeat_extends_the_lease(tmp_data_dir):
    """`TC-ORCH-05`'s heartbeat half — a worker that IS heartbeating does not lose its
    lease when the original expiry passes."""
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
        held = won[0].work_id

        # Half the lease elapses; the worker heartbeats. The expiry must move out.
        clock.advance(ORCH_LEASE_SECONDS / 2)
        orch.heartbeat(held)

        # Past the ORIGINAL expiry, but within the extended one.
        clock.advance(ORCH_LEASE_SECONDS / 2 + 1)
        orch.sweep_expired_leases()
        leased = {row["work_id"] for row in _leased_units(store, run_id)}
        assert held in leased, (
            "a heartbeating worker lost its lease at the original expiry — the "
            "heartbeat did not extend it, and a slow-but-alive worker would be "
            "double-run (CT-ORCH-04's at-least-once is for dead workers, not live ones)"
        )
    finally:
        store.close()


@pytest.mark.slow
def test_tc_orch_09_a_real_elapsed_lease_expiry_requeues(tmp_data_dir, monkeypatch):
    """`TC-ORCH-09` — a **real** elapsed expiry, on wall-clock time: the one sanctioned
    sleep in the suite (§4.6). Confirms the injected-clock cases are not hiding a
    real-time bug — a monotonic-vs-wall mix-up or a unit mismatch between the clock the
    lease writes and the clock the sweeper reads passes every frozen-clock case."""
    Orchestrator, ORCH_LEASE_SECONDS = require(
        ORCH_MODULE, "Orchestrator", "ORCH_LEASE_SECONDS", issue=ISSUE
    )
    lease_seconds = int(os.environ.get("HARNESS_ORCH_LEASE_SECONDS", "2"))
    assert lease_seconds <= 5, (
        "the real-time case must run against a knob-shortened lease, not the 300s "
        "production value"
    )
    monkeypatch.setenv("HARNESS_ORCH_LEASE_SECONDS", str(lease_seconds))
    # Re-read after the knob: the constant is the production default; the ORCHESTRATOR
    # reads the environment at call time (seam 3), so the knob below is what governs.
    del ORCH_LEASE_SECONDS

    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
        orch = Orchestrator(store)  # the real clock — that is the point of this case

        won = orch.lease("worker-a", "extract", 10)
        assert won

        import time

        time.sleep(lease_seconds - 1)
        orch.sweep_expired_leases()
        assert _leased_units(store, run_id), (
            "the sweeper requeued a lease that had NOT yet expired in real time"
        )

        time.sleep(lease_seconds)  # the sanctioned sleep: past the real expiry
        orch.sweep_expired_leases()
        assert _leased_units(store, run_id) == [], (
            "a lease that expired in real elapsed time was not requeued — the "
            "injected-clock cases are hiding a real-time bug"
        )
    finally:
        store.close()
