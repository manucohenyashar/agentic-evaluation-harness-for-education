"""`TC-ORCH-04` — resume after an uncontrolled kill duplicates nothing and loses
nothing, cross-referenced as `RES-04` and `RES-05` (RISK-09, P0, integration against
real modules / rung 3).

Kill-and-restart at each checkpoint boundary; after each restart `resume()` is called
**with no arguments**; the full result set is compared against a clean uninterrupted
run of the same seed (the differential oracle), plus a uniqueness invariant on the
unit identity — no `work_id` has two result rows and none is missing.

**What "kill" means here, disclosed.** There is no subprocess to SIGKILL at this
rung in this harness. The kill-and-restart is modeled the way the shipped store
models the event: the process boundary is a **store close + reopen** over the same
data directory — the exact state an uncontrolled kill leaves behind (committed rows
persist; uncommitted batched writes are the durability bound `CT-STORE-05` already
covers elsewhere) — and the new process constructs a fresh `Orchestrator` over the
reopened store. A restart also expires every outstanding lease by the store's stated
conservatism (`LeaseClock`'s persisted high-water, `CT-STORE-14`), so the sweeper's
requeue is exercised across the boundary — the plan's declared variant *"a resume
after the lease sweeper has already requeued some units"*.

**The checkpoint boundaries, as far as this slice ships them.** The two-sweep plan is
#59's; dispatch is `lease` (shipped, #58); escalation units are #60's and synthesis
units are `M-SYNTH`'s (#97). The boundaries this file holds work across are the real
boundaries of the shipped ledger — mid-Sweep-1 with leases outstanding (`RES-04`),
between Sweep 1 and Sweep 2 (`RES-05`), and mid-Sweep-2 with units leased and
abandoned — and the resume mechanics every boundary shares: no-argument discovery,
skip-every-done, no duplication, the safe no-op, the re-run row-count invariant
(`FR-ORCH-02/03`). The escalation and synthesis checkpoints are killed inside their
own stories' resilience files; this file does not guess at their shapes.

**The differential's two sides.** `work_id` hashes `run_id`, so two runs of the same
seed do not share ids — the comparison is over the unit identity the enumeration
defines, `(submission_id, stage, criterion_id, judge_id, origin)`, projected to final
status. The uniqueness invariant rides the same projection: the ledger must hold
exactly one row per identity, which is what "no `work_id` has two result rows" means
at this surface (the ledger IS the result set; payload persistence is the owning
stages', #68/#78/#97).

Isolation: rung 3 — real store, real Tier P package, real cohort ledger, real
`Orchestrator`, no doubles (§4.2 forbids an in-memory stand-in for the store
contract outright).
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.impl import ORCH_MODULE, require
from tests.support.orch_run import seed_run

pytestmark = pytest.mark.integration

ISSUE = "#58"

_SUBMISSIONS = tuple(f"SYN-{i:03d}" for i in range(1, 9))
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "mcq", "scoring_model": "deterministic"},
)

_STAGES = ("extract", "score", "deterministic")


def _snapshot(store, run_id: str) -> dict[tuple, str]:
    """The run's final state as `{unit identity: status}` — the differential's shape.

    The projection is the enumeration's own unit identity; the uniqueness invariant
    is `len(rows) == len(projection)` at the call site.
    """
    rows = store.cohort("c-2026-7B-orch").query(
        "SELECT submission_id, stage, criterion_id, judge_id, origin, status "
        "FROM work_unit WHERE run_id = :r",
        r=run_id,
    )
    projection = {
        (r["submission_id"], r["stage"], r["criterion_id"], r["judge_id"], r["origin"]): r[
            "status"
        ]
        for r in rows
    }
    assert len(projection) == len(rows), (
        f"{len(rows) - len(projection)} result rows share a unit identity — the "
        "uniqueness invariant on work_id is violated (RISK-09's duplicated-work "
        "half, caught at the identity the enumeration defines)"
    )
    return projection


def _drive_to_completion(orch, run_id: str) -> None:
    """A clean worker loop: lease every stage, complete everything."""
    orch.enumerate_units(run_id)
    while True:
        batch = []
        for stage in _STAGES:
            batch.extend(orch.lease("worker-clean", stage, 100))
        if not batch:
            return
        for unit in batch:
            orch.complete(unit.work_id)


def _baseline(tmp_data_dir) -> dict[tuple, str]:
    """The clean uninterrupted run: same seed, own data dir, driven to completion."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    store = open_store(tmp_data_dir / "baseline")
    try:
        orch, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
        _drive_to_completion(orch, run_id)
        snapshot = _snapshot(store, run_id)
    finally:
        store.close()
    assert snapshot, "the baseline run produced no units"
    assert set(snapshot.values()) == {"done"}, (
        "the baseline run did not complete — the differential would compare "
        "against a broken reference"
    )
    return snapshot


def _table_row_counts(store) -> dict[str, int]:
    """Row counts for every table in the cohort ledger — the re-run invariant's
    'no new rows in ANY table' half, not merely the work units'."""
    names = [
        row["name"]
        for row in store.cohort("c-2026-7B-orch").query(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        name: store.cohort("c-2026-7B-orch").query(
            f"SELECT COUNT(*) AS n FROM {name}"
        )[0]["n"]
        for name in sorted(names)
    }


@pytest.mark.parametrize(
    ("boundary", "expected_requeued"),
    [
        # Two leases die outstanding (one of the three completed pre-kill).
        pytest.param("res04-mid-sweep1-leases-outstanding", 2, id="RES-04"),
        # Between sweeps nothing is in flight: the sweep across the boundary is a
        # safe no-op, and resume() finds the committed state exactly as it was.
        pytest.param("res05-between-sweeps", 0, id="RES-05"),
        pytest.param("mid-sweep2-units-leased", 4, id="mid-sweep2"),
    ],
)
def test_tc_orch_04_resume_after_kill_matches_the_clean_baseline(
    tmp_data_dir, boundary, expected_requeued
):
    """`TC-ORCH-04`/`RES-04`/`RES-05` — kill at the boundary, restart, resume() with
    no arguments, and the result set is identical to the clean-run baseline: nothing
    duplicated, nothing lost, the second resume a safe no-op, the re-run inserting
    no rows."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    baseline = _baseline(tmp_data_dir)
    data_dir = tmp_data_dir / boundary

    store = open_store(data_dir)
    orch, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
    orch.enumerate_units(run_id)

    if boundary == "res04-mid-sweep1-leases-outstanding":
        # Mid-Sweep-1, leases outstanding: one unit completes before the kill, two
        # die holding leases.
        won = orch.lease("worker-a", "extract", 3)
        assert len(won) == 3, "the kill fixture did not lease mid-Sweep-1"
        orch.complete(won[0].work_id)
    elif boundary == "res05-between-sweeps":
        # Between Sweep 1 and Sweep 2: every extraction unit done, no scoring unit
        # leased.
        for stage in ("extract", "deterministic"):
            batch = orch.lease("worker-a", stage, 100)
            assert batch
            for unit in batch:
                orch.complete(unit.work_id)
    else:  # mid-sweep2-units-leased
        extract = orch.lease("worker-a", "extract", 100)
        assert extract
        for unit in extract:
            orch.complete(unit.work_id)
        scoring = orch.lease("worker-a", "score", 4)
        assert scoring, "the kill fixture leased no scoring unit mid-Sweep-2"

    # --- the kill: process boundary = close + reopen; a fresh orchestrator ---
    store.close()
    store = open_store(data_dir)
    try:
        restarted = Orchestrator(store)

        # The restart expires every outstanding lease (the persisted high-water
        # sits at or past every issued expiry — CT-STORE-14's conservatism); the
        # sweeper returns them to pending. This is the plan's declared variant: a
        # resume after the sweeper has already requeued units — and where nothing
        # was outstanding (RES-05), the sweep is the safe no-op.
        report = restarted.sweep_expired_leases()
        assert report.requeued == expected_requeued, (
            f"boundary {boundary}: the restart's sweeper requeued "
            f"{report.requeued} leases, expected {expected_requeued} — a killed "
            "worker's leases must not read as live across the boundary, and a "
            "boundary holding nothing must requeue nothing"
        )

        # resume() with NO arguments — the requirement, not ergonomics.
        restarted.resume()

        # Drive the resumed run to completion exactly as the baseline was.
        while True:
            batch = []
            for stage in _STAGES:
                batch.extend(restarted.lease("worker-resume", stage, 100))
            if not batch:
                break
            for unit in batch:
                restarted.complete(unit.work_id)

        final = _snapshot(store, run_id)
        assert set(final) == set(baseline), (
            f"boundary {boundary}: the resumed run's result set differs from the "
            "clean-run baseline — "
            f"missing={sorted(set(baseline) - set(final))[:3]} "
            f"extra={sorted(set(final) - set(baseline))[:3]} "
            "(NFR-ORCH-02: no duplicated and no lost work)"
        )
        assert set(final.values()) == {"done"}, (
            f"boundary {boundary}: units left in {set(final.values()) - {'done'}} "
            "after the resumed run completed — work was lost, not duplicated"
        )

        # Step 4 of the block form: resume() again when nothing is wrong — the safe
        # no-op (CT-ORCH-03's half this case carries).
        before = _snapshot(store, run_id)
        restarted.resume()
        assert _snapshot(store, run_id) == before, (
            f"boundary {boundary}: a resume invoked when nothing is wrong mutated "
            "the result set"
        )

        # Step 5: re-run the completed run end to end — no new rows in ANY table
        # (FR-ORCH-03's row-count invariant).
        before_counts = _table_row_counts(store)
        restarted.resume()
        assert _table_row_counts(store) == before_counts, (
            f"boundary {boundary}: re-running the completed run inserted rows"
        )
    finally:
        store.close()
