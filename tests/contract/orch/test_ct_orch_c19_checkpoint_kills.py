"""`TC-ORCH-C19` — the process may be killed at every checkpoint boundary, and
`resume()` still completes the run with no duplicated and no lost work (§6.11.7).

`CT-ORCH-19`'s grant: killing the process is a legitimate operation, so the case
exercises it as one — a kill at EACH checkpoint boundary the ledger's write paths
name:

- **mid-enumeration-commit** — the `insert_work_unit` batch (a kill inside the
  enumeration's own insert transaction);
- **mid-lease** — the claim pass's `mark_leased`, on its second occurrence so one
  lease COMMITS and the kill dies holding the second: the committed-lease-outstanding
  shape the sweeper owns across the boundary;
- **mid-complete** — the at-least-once completion's `mark_done`, with one completion
  committed and the next killed mid-transaction;
- **mid-escalation** — `insert_escalation_request` inside the caller's transaction
  (the enqueue's atomicity unit: request row, breaker evaluation and unit plan die
  together);
- **mid-breaker-evaluation** — the trip's `insert_breaker` write.

After each kill the recovery is the shipped model, not a simulation: store close +
reopen (the state an uncontrolled kill leaves — committed rows persist, the killed
transaction's writes are gone), a fresh `Orchestrator`, `sweep_expired_leases()`,
`resume()`, then the SAME step sequence replayed — every step idempotent on the
ledger (`INSERT OR IGNORE` enumeration, the enqueue's idempotence gate, the
completion's guarded `mark_done`), which is precisely the property the clause
claims. The oracle is the differential against an uninterrupted reference run of
the same seed: the final unit projection identical, every unit `done`, and no new
rows in ANY cohort table — nothing duplicated, nothing lost — plus a second resume
as the safe no-op.

Relationship to shipped cases, disclosed: `tests/resilience/orch/test_resume.py`
(RES-04/RES-05, #58) kills BETWEEN transactions — leases outstanding, between
sweeps — and owns the no-argument-resume mechanics this case reuses. What that file
does not do is kill INSIDE a checkpoint's transaction (its kills land between
statements, where the ledger is trivially consistent); the mid-commit boundaries
here are the ones only a rollback-producing kill reaches. The escalation and
breaker checkpoints ride the shipped escalation/breaker surfaces (#60/#66's) the
way the plan's boundary list names them.

Isolation: rung 2 — real store, real package, real cohort ledger, real
`Orchestrator`; the breaker and the budget are evaluable with no model call
(`NFR-ORCH-04`), so no provider double is needed. The kill is the
`KillCohortHandle` double (a `BaseException` mid-transaction — the store's own
rollback signal), not a store stand-in: every write lands or rolls back in real
SQLite.
"""

from __future__ import annotations

import pytest

from aeh.orch import STAGE_EXTRACT, Orchestrator
from aeh.store import open_store
from tests.contract.orch._doubles import (
    KillError,
    install_kill,
    table_row_counts,
    unit_projection,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.contract]

_RUN_ID = "run-c19-checkpoints"

_SUBMISSIONS = ("SYN-001", "SYN-002", "SYN-003", "SYN-004")

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
     "band_count": 2},
    {"criterion_id": "C2", "kind": "mcq"},
)

#: The checkpoint kills: (SQL marker, occurrence, leases the restart must requeue).
#: Occurrence 2 on `mark_leased`/`mark_done` leaves ONE committed write outstanding
#: (the first execution commits, the second dies mid-transaction) — the differential
#: must absorb both the outstanding-lease shape and the rolled-back shape. The
#: breaker's knobs (window minimum 4, rate 0.5) put the trip on the drive's third
#: escalation enqueue, so the breaker checkpoint is reached inside the ordinary flow.
_KILL_CASES = (
    pytest.param("INSERT OR IGNORE INTO work_unit", 1, 0,
                 id="TC-ORCH-C19-mid-enumeration-commit"),
    pytest.param("SET status = 'leased'", 2, 1,
                 id="TC-ORCH-C19-mid-lease"),
    pytest.param("SET status = 'done'", 2, 0,
                 id="TC-ORCH-C19-mid-complete"),
    pytest.param("INSERT OR IGNORE INTO escalation_request", 1, 0,
                 id="TC-ORCH-C19-mid-escalation"),
    pytest.param("INSERT OR IGNORE INTO circuit_breaker", 1, 0,
                 id="TC-ORCH-C19-mid-breaker-evaluation"),
)


def _pending_work_ids(store, run_id, origin=None):
    sql = (
        "SELECT work_id, origin FROM work_unit "
        "WHERE run_id = :r AND status = 'pending' ORDER BY work_id"
    )
    rows = store.cohort(ORCH_COHORT_ID).query(sql, r=run_id)
    if origin is not None:
        rows = [r for r in rows if r["origin"] == origin]
    return [r["work_id"] for r in rows]


def _drive(orch, store, run_id, *, probe=None):
    """One replayable pass of the run's step sequence.

    Every step is idempotent on the ledger — enumeration `INSERT OR IGNORE`s,
    `start()` asked of the ledger (it refuses a non-`pending` run), the enqueue
    carries the idempotence gate, the completion's `mark_done` guards on
    `leased`/`pending` — so the SAME sequence replays unchanged after a kill and
    lands the uninterrupted run's final state.
    That replayability is the property under test, not a fixture convenience: a
    recovery that needed a DIFFERENT sequence than the killed run would be a
    recovery the operator cannot script.
    """
    orch.enumerate_units(run_id)
    # start() refuses a run that is not 'pending' (FR-ORCH-25's machine), so the
    # replay asks the ledger: a run the kill never got to start is started; a run
    # already 'running' across the boundary is left as the boundary left it.
    row = store.cohort(ORCH_COHORT_ID).query(
        "SELECT status FROM run WHERE run_id = :r", r=run_id
    )
    if row and row[0]["status"] == "pending":
        orch.start(run_id)
    if probe == "lease":
        # The mid-lease kill's driver: two claims, two transactions — the first
        # commits, the second dies inside its own.
        batch = orch.lease("w-c19", STAGE_EXTRACT, 2)
        assert len(batch) == 2, (
            "the kill fixture leased fewer than two extract units — the "
            "committed-lease-outstanding shape would not exist"
        )
    for work_id in _pending_work_ids(store, run_id):
        orch.complete(work_id)
    for submission_id in _SUBMISSIONS:
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            orch.enqueue_escalation(tx, (submission_id, "C1"))
    for work_id in _pending_work_ids(store, run_id, origin="escalation"):
        orch.complete(work_id)


def _baseline(tmp_data_dir):
    """The uninterrupted reference run: same seed, own data dir, same steps."""
    store = open_store(tmp_data_dir / "baseline")
    try:
        orch, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA, run_id=_RUN_ID,
        )
        _drive(orch, store, run_id, probe=None)
        projection = unit_projection(store, ORCH_COHORT_ID, run_id)
        counts = table_row_counts(store, ORCH_COHORT_ID)
    finally:
        store.close()
    assert set(projection.values()) == {"done"}, (
        f"the baseline run finished with statuses {set(projection.values())} — "
        "the differential would compare against a broken reference"
    )
    assert projection, "the baseline run produced no units"
    return projection, counts


@pytest.mark.parametrize(
    ("marker", "occurrence", "expected_requeued"), _KILL_CASES
)
def test_tc_orch_c19_kill_at_the_checkpoint_then_resume_matches_the_baseline(
    tmp_data_dir, monkeypatch, marker, occurrence, expected_requeued
):
    """Kill inside the checkpoint's transaction, restart, sweep, resume, replay —
    the final ledger is the uninterrupted run's, byte for row count, with nothing
    duplicated and nothing lost."""
    # The breaker (window minimum 4 = the cohort's whole roster, rate 0.5) trips on
    # the drive's THIRD escalation enqueue, so the mid-breaker kill fires inside a
    # REAL trip. The window minimum is pinned to the roster size deliberately: the
    # window is `first N by completion tick`, and with N < roster its membership
    # would ride the ticks the completions land on — different across a restart —
    # so a smaller window could trip the killed run's replay at a DIFFERENT enqueue
    # than the baseline's and the differential would compare two different routing
    # states. With N = the roster, the window is every submission whatever order the
    # ticks land in, the trip point is the 3rd enqueue in both the baseline and the
    # replay, and the mid-breaker kill fires inside the ordinary flow. The budget
    # stays at 1.0 — it is C16's subject and would defer the widened panels
    # mid-redrive for reasons this clause does not name.
    monkeypatch.setenv("HARNESS_ORCH_CRITERION_BREAKER_MIN_N", "4")
    monkeypatch.setenv("HARNESS_ORCH_CRITERION_BREAKER_RATE", "0.5")
    monkeypatch.setenv("HARNESS_ORCH_ESCALATION_BUDGET", "1.0")

    baseline_projection, baseline_counts = _baseline(tmp_data_dir)

    data_dir = tmp_data_dir / f"kill-{marker.split()[-1]}-{occurrence}"
    store = open_store(data_dir)
    try:
        orch, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA, run_id=_RUN_ID,
        )
        handle = install_kill(store, ORCH_COHORT_ID, marker, occurrence)
        with pytest.raises(KillError):
            _drive(
                orch, store, run_id,
                probe="lease" if marker == "SET status = 'leased'" else None,
            )
        assert handle.killed, (
            f"the drive completed without the kill firing on {marker!r} — the "
            "checkpoint boundary was never reached, and the differential below "
            "would assert nothing about it"
        )
    finally:
        store.close()

    # --- the restart: the process boundary is close + reopen; a fresh
    # orchestrator; the sweeper requeues what the kill left outstanding. ---
    store = open_store(data_dir)
    try:
        restarted = Orchestrator(store)
        report = restarted.sweep_expired_leases()
        assert report.requeued == expected_requeued, (
            f"[{marker!r} x{occurrence}] the restart's sweeper requeued "
            f"{report.requeued} lease(s), expected {expected_requeued} — a kill "
            "inside a claim transaction must leave exactly the committed leases "
            "outstanding, and a boundary that committed none must requeue none"
        )

        # resume() with NO arguments — the requirement, not ergonomics.
        restarted.resume()

        # The same step sequence, replayed onto the recovered ledger.
        _drive(restarted, store, run_id, probe=None)
        final_report = restarted.progress(run_id)
        assert final_report.complete, (
            f"[{marker!r} x{occurrence}] the resumed run reports open work "
            f"(pending={final_report.pending}, in_flight={final_report.in_flight}) "
            "— resume() did not complete the run the kill interrupted"
        )

        final = unit_projection(store, ORCH_COHORT_ID, run_id)
        assert set(final) == set(baseline_projection), (
            f"[{marker!r} x{occurrence}] the resumed run's result set differs from "
            f"the clean baseline — missing="
            f"{sorted(set(baseline_projection) - set(final))[:3]} extra="
            f"{sorted(set(final) - set(baseline_projection))[:3]} "
            "(CT-ORCH-19: no duplicated and no lost work)"
        )
        assert set(final.values()) == {"done"}, (
            f"[{marker!r} x{occurrence}] units left in "
            f"{set(final.values()) - {'done'}} after the resumed run completed — "
            "work was lost, not duplicated"
        )
        assert table_row_counts(store, ORCH_COHORT_ID) == baseline_counts, (
            f"[{marker!r} x{occurrence}] the resumed run's ledger differs from the "
            "clean baseline's table counts — a checkpoint kill duplicated or lost "
            "rows outside the unit set"
        )

        # Resume again when nothing is wrong: the safe no-op.
        before = table_row_counts(store, ORCH_COHORT_ID)
        restarted.resume()
        assert table_row_counts(store, ORCH_COHORT_ID) == before, (
            f"[{marker!r} x{occurrence}] a resume invoked when nothing is wrong "
            "inserted rows — the recovery is not idempotent (FR-ORCH-03)"
        )
    finally:
        store.close()
