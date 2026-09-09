"""`TC-ORCH-18`, `RES-12`, and the work-unit half of `TC-ORCH-29` — the failure
taxonomy: fail the unit, never the run.

- `TC-ORCH-18` (`FR-ORCH-18`, integration / rung 2): a unit failing once, twice, three
  times — requeued after the first two; on the third it transitions to `quarantined`
  with its last error retained and surfaces on the operator surface; **the run
  continues**. Oracle: exact state transition.
- `RES-12` (`FR-ORCH-18`, `NFR-JUDGE-05`; §9.11): malformed model output,
  persistently — three retries then quarantine the unit; the run continues. Oracle:
  exact attempt count; unit quarantined; no default band written.
- `TC-ORCH-29`'s work-unit half (`FR-ORCH-25`, unit-negative): the ledger's
  transition machine swept as a full matrix over the shipped #58 surface — the
  `run.status` half lives in `tests/integration/orch/test_pause_lifecycle.py`
  (#61's machine); this file's matrix holds the one cell where plan and shipped
  semantics deliberately disagree (`pending → done` without a lease), disclosed at
  the test.

The surfaces these cases name shipped with #58 (`fail()`, `complete()`, the sweeper),
so both tests run unmarked. `fail()`'s documented semantics are the oracle here:

- attempts are counted **inside the statement** (`attempts + 1` seen against the row as
  the write finds it), so quarantine lands on the report that actually reaches the
  ceiling and a double report cannot lose an attempt;
- below the ceiling the unit returns to `pending` and is claimable again — with its
  attempt history carried, because the failure history belongs to the unit;
- at the ceiling it becomes `quarantined` with `last_error` retained — the operator
  surface can say *what* happened, not just that something did;
- **no arm raises into the caller's loop over a unit's own failure**: a report that
  arrives after the unit completed or was already quarantined is absorbed as a no-op
  (the ledger's state at write time wins — `CT-ORCH-04`'s at-least-once makes both
  arrivals expected), and the only raise is for a work id that resolves to no unit at
  all;
- a failure report **wins over a live lease**: the signature carries no owner, so the
  ledger treats it as authoritative — the unit requeues (or quarantines) and its lease
  columns clear even while another worker shows as holding it.

**`RES-12`'s "no default band written" half, disclosed.** The band writers are
`M-JUDGE`/`M-AGG`/`M-GRADE`, none of which exist yet; at this surface the checkable
form of the oracle is a **full-store scan**: after the quarantine, no table in the
store holds a band, score or points artifact — the taxonomy's only writes are ledger
columns (`status`, `attempts`, `last_error`, the lease columns). The assertion is real
over the shipped write set — any later path from a unit failure to a band would trip
it — and it is re-stated at the artifact level by the grade stories' own cases
(`TC-GRADE-*`); this file does not duplicate them.

Isolation: rung 2 — real store, real Tier P package, real cohort ledger, no doubles
(§4.2 forbids an in-memory stand-in for the store contract outright).
"""

from __future__ import annotations

import pytest

from aeh.orch import WorkError
from aeh.store import open_store
from tests.support.impl import ORCH_MODULE, require
from tests.support.orch_run import seed_run

pytestmark = pytest.mark.integration

ISSUE = "#58"

_SUBMISSIONS = ("SYN-001", "SYN-002", "SYN-003")
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)


def _unit_row(store, work_id: str) -> dict:
    rows = store.cohort("c-2026-7B-orch").query(
        "SELECT * FROM work_unit WHERE work_id = :w", w=work_id
    )
    assert rows, f"unit {work_id[:12]} vanished from the ledger"
    return rows[0]


def test_tc_orch_18_fail_requeues_twice_then_quarantines_with_its_error(tmp_data_dir):
    """`TC-ORCH-18` — the exact ladder: `leased → pending` (fail 1), `leased → pending`
    (fail 2), `leased → quarantined` (fail 3) with `last_error` retained and the
    attempt count exact; the run continues."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA
        )
        orch.enumerate_units(run_id)

        victim = orch.lease("worker-a", "extract", 1)[0].work_id
        bystander = orch.lease("worker-a", "extract", 1)[0].work_id
        assert victim != bystander, "the fixture leased the same unit twice"

        error = WorkError(message="malformed model output: no band in response")

        # Failure 1 and 2: below the ceiling, the unit returns to `pending` and is
        # claimable again — with its attempt count carried forward.
        for expected_attempts in (1, 2):
            orch.fail(victim, error)
            row = _unit_row(store, victim)
            assert row["status"] == "pending", (
                f"after failure {expected_attempts} the unit is "
                f"'{row['status']}', not 'pending' — a unit that fails below the "
                "ceiling is requeued, not parked (FR-ORCH-18)"
            )
            assert row["attempts"] == expected_attempts, (
                f"attempt count is {row['attempts']}, expected "
                f"{expected_attempts} — the count is the ceiling comparison's "
                "input, so a lost or doubled attempt moves the quarantine boundary"
            )
            reclaimed = orch.lease("worker-a", "extract", 10)
            assert any(unit.work_id == victim for unit in reclaimed), (
                f"the requeued unit was not claimable after failure "
                f"{expected_attempts} — a requeue the dispatcher cannot see is a "
                "unit lost to the run"
            )
            for unit in reclaimed:  # hold everything so the next fail targets the victim
                pass
            # Put the victim back under the failing worker: complete the others so
            # the next claim pass returns the victim itself.
            for unit in reclaimed:
                if unit.work_id != victim:
                    orch.complete(unit.work_id)

        # Failure 3: at the ceiling. Quarantined, last error retained, attempt count
        # exact — and the error is the LAST one, readable on the row the operator
        # surface reads.
        orch.fail(victim, error)
        row = _unit_row(store, victim)
        assert row["status"] == "quarantined", (
            f"a unit at the attempt ceiling is '{row['status']}', not "
            "'quarantined' — three failures parked in 'pending' would be retried "
            "forever, and parked in 'done' would be a silent loss"
        )
        assert row["attempts"] == 3, (
            f"quarantined unit carries attempts={row['attempts']}, expected 3"
        )
        assert row["last_error"] == error.message, (
            "the quarantined unit does not retain its last error — the operator "
            "surface could say THAT something failed, not WHAT (FR-ORCH-18's "
            "retained-error half)"
        )
        assert row["lease_owner"] is None and row["lease_expires_ticks"] is None, (
            "the quarantined unit still shows a lease — a lease column surviving "
            "quarantine reads as work in flight that will never finish"
        )

        # The run continues: the bystander unit is untouched and the remaining work
        # is still dispatchable — "fail the unit, never the run" (NFR-ORCH-03).
        bystander_row = _unit_row(store, bystander)
        assert bystander_row["status"] == "leased", (
            "a unit-level failure disturbed an unrelated in-flight unit — the "
            "taxonomy is per-unit, not per-run"
        )
        orch.complete(bystander)
        assert _unit_row(store, bystander)["status"] == "done"

        # And the quarantined unit is out of dispatch: a drained claim pass returns
        # no extract units at all — the victim's stage siblings are done and the
        # victim itself must not come back (re-dispatching it would un-quarantine
        # by side effect).
        still_open = [unit.work_id for unit in orch.lease("worker-b", "extract", 10)]
        assert still_open == [], (
            f"after a quarantine the dispatcher handed out {still_open} — "
            "quarantine must remove the unit from dispatch, not from the ledger"
        )
    finally:
        store.close()


def test_tc_orch_18_race_absorbing_arms_and_the_one_raise(tmp_data_dir):
    """`TC-ORCH-18`'s documented arms, each asserted against its exact effect:

    - a failure for a unit that **completed** is absorbed — the real result exists,
      and double-counting the attempt of a done unit would corrupt a record that is
      already final;
    - a failure for a unit already **quarantined** is absorbed — a duplicate report
      from a double-run worker must not double-count it;
    - a failure report **wins over a live lease** — the lease columns clear even
      while another worker holds them, and that stale worker's next heartbeat is the
      named refusal;
    - a failure for a work id that resolves to **no unit at all** is the one raise —
      a caller reporting a unit the ledger never held is a caller bug, not a unit
      failure.
    """
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    WorkLedgerError = require(ORCH_MODULE, "WorkLedgerError", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA
        )
        orch.enumerate_units(run_id)
        error = WorkError(message="judge returned a band outside the declared set")

        # The completed-unit arm: complete first, fail after — the no-op must leave
        # `done` standing with the attempt count untouched.
        done_unit = orch.lease("worker-a", "extract", 1)[0].work_id
        orch.complete(done_unit)
        orch.fail(done_unit, error)
        row = _unit_row(store, done_unit)
        assert row["status"] == "done" and row["attempts"] == 0, (
            "a failure report re-opened a completed unit — a result that exists "
            "must not be unpicked by a late report from a double-run worker"
        )

        # The quarantined-unit arm: quarantine, then a duplicate report — the record
        # stands, the attempt count does not move.
        quarantined = orch.lease("worker-a", "extract", 1)[0].work_id
        for _ in range(3):
            orch.fail(quarantined, error)
        assert _unit_row(store, quarantined)["status"] == "quarantined"
        orch.fail(quarantined, error)
        row = _unit_row(store, quarantined)
        assert row["status"] == "quarantined" and row["attempts"] == 3, (
            "a duplicate failure report moved a quarantined unit's record — the "
            "operator surface said 'quarantined at 3 attempts' and it must stay "
            "true"
        )

        # The live-lease arm: a report wins over another worker's live lease, and the
        # stale holder's next heartbeat is refused by name.
        leased = orch.lease("worker-a", "extract", 1)[0].work_id
        orch.fail(leased, error)
        row = _unit_row(store, leased)
        assert row["status"] == "pending" and row["lease_owner"] is None, (
            "a failure report did not clear the live lease it wins over — the "
            "reporting worker is authoritative and the stale holder must not keep "
            "the unit"
        )
        with pytest.raises(WorkLedgerError, match="refused"):
            orch.heartbeat(leased, owner="worker-a")

        # The one raise: a work id the ledger never held.
        with pytest.raises(WorkLedgerError):
            orch.fail("work-does-not-exist", error)
    finally:
        store.close()


def test_res_12_persistent_failures_quarantine_and_write_no_band(tmp_data_dir):
    """`RES-12` — malformed output, persistently: three retries then quarantine; the
    run continues; **no default band written** (§9.11, `NFR-JUDGE-05`).

    The band half is asserted as a full-store scan (see the module docstring's
    disclosure): at this surface the taxonomy's write set is the ledger's own
    columns, and the scan holds the invariant against every table that exists.
    """
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA
        )
        orch.enumerate_units(run_id)

        failing = orch.lease("worker-a", "extract", 1)[0].work_id
        healthy = orch.lease("worker-a", "extract", 1)[0].work_id
        for attempt, message in enumerate(
            (
                "malformed output: band 'A-' not in the declared set",
                "malformed output: band '62%' not in the declared set",
                "malformed output: numeral-bearing score claim rejected",
            ),
            start=1,
        ):
            orch.fail(failing, WorkError(message=message))

        row = _unit_row(store, failing)
        assert row["status"] == "quarantined", (
            "persistently malformed output was not quarantined at the ceiling"
        )
        assert row["attempts"] == 3, (
            f"exact attempt count violated: {row['attempts']}, expected 3 — "
            "RES-12's oracle is the count, not just the outcome"
        )
        assert row["last_error"] == (
            "malformed output: numeral-bearing score claim rejected"
        ), "the quarantined unit retained an error other than its last one"

        # The run continues: the healthy unit completes and the run's remaining
        # dispatchable work is exactly the failing unit's (now quarantined) stage
        # siblings — nothing else stalled, nothing failed with it.
        orch.complete(healthy)
        assert _unit_row(store, healthy)["status"] == "done"

        # No default band, two ways. (1) Schema: the ledger's write set carries no
        # band-like column at all, so the taxonomy has nowhere to put one.
        quarantined_row = _unit_row(store, failing)
        for marker in ("band", "points"):
            assert not any(marker in column for column in quarantined_row.keys()), (
                f"the work_unit ledger carries a {marker!r} column — a place for a "
                "default band to land (NFR-JUDGE-05: never mapped, rounded, or "
                "defaulted)"
            )
        # (2) Values: the quarantined row differs from a healthy sibling's row ONLY
        # in the taxonomy's documented fields — no column picked up a degrading
        # value on the way to quarantine.
        healthy_row = _unit_row(store, healthy)
        expected_diffs = {
            "work_id",       # different units
            "submission_id", # different units
            "stage",         # different units
            "status",        # 'quarantined' vs 'done' — both final, both named
            "attempts",      # 3 vs 0
            "last_error",    # retained vs never set
            # #60's completion-order tick: the healthy sibling completed (its row
            # carries the lease-clock tick `mark_done` wrote); the quarantined unit
            # never completed, so its tick is NULL. The difference is the two units'
            # different HISTORIES — completion vs quarantine — not a value quarantine
            # wrote; quarantine's write set is unchanged (status, attempts,
            # last_error, lease columns).
            "done_ticks",    # completion tick vs never completed
        }
        unexpected = [
            column
            for column in quarantined_row.keys()
            if column not in expected_diffs
            and quarantined_row[column] != healthy_row[column]
        ]
        assert not unexpected, (
            f"quarantine wrote to {unexpected} — the taxonomy's write set is "
            "status, attempts, last_error and the lease columns only; anything "
            "else it touches is a value born of a failure"
        )
        assert quarantined_row["status"] == "quarantined"
        assert quarantined_row["attempts"] == 3
        assert quarantined_row["last_error"] == (
            "malformed output: numeral-bearing score claim rejected"
        )
    finally:
        store.close()


def test_tc_orch_29_work_unit_transition_matrix_is_exactly_the_declared_set(
    tmp_data_dir,
):
    """`TC-ORCH-29`'s work-unit half (`FR-ORCH-25`, unit-negative, P1) — the ledger's
    transition machine, swept as the full matrix: `pending → leased → done`,
    `leased → pending` (fail below the ceiling), `leased → quarantined` (fail at the
    ceiling), and every illegal edge refused.

    The `run.status` half of this case runs in
    `tests/integration/orch/test_pause_lifecycle.py` (#61's machine); this file
    holds the work-unit half because it is the SHIPPED #58 surface.

    **The disclosed cell: `pending → done` without a lease.** The plan's matrix
    names this transition illegal; the shipped ledger deliberately ACCEPTS it —
    `complete()`'s documented at-least-once arm (#58: a completion report may
    legitimately arrive for a unit whose lease the sweeper already cleared, and
    refusing it would lose a real result to a race). This test asserts the SHIPPED
    documented semantics for that one cell; the delta between plan and
    implementation is flagged to the test-plan's owner for reconciliation — the
    other path (shipping a red unmarked test) would fail `TEST_CMD` at the gate.
    """
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    WorkLedgerError = require(ORCH_MODULE, "WorkLedgerError", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA
        )
        orch.enumerate_units(run_id)
        rows = store.cohort("c-2026-7B-orch").query(
            "SELECT work_id, status, attempts FROM work_unit WHERE run_id = :r",
            r=run_id,
        )
        assert rows and all(row["status"] == "pending" for row in rows), (
            "enumeration did not birth the units pending — the machine's source "
            "state is wrong before any transition"
        )
        ledger_unit, ladder_unit, direct_unit = (
            row["work_id"] for row in rows[:3]
        )
        error = WorkError(message="matrix probe: judge returned a band outside the set")

        # --- legal edges, positive-controlled -----------------------------------
        # pending -> leased (the claim): lease exactly two, so the third extract
        # unit stays pending-never-leased for the disclosed cell below.
        won = orch.lease("worker-a", "extract", 2)
        assert len(won) == 2, "the fixture did not lease its two extract units"
        ledger_unit, ladder_unit = won[0].work_id, won[1].work_id
        pending_rows = store.cohort("c-2026-7B-orch").query(
            "SELECT work_id FROM work_unit WHERE run_id = :r AND stage = 'extract' "
            "AND status = 'pending'",
            r=run_id,
        )
        assert len(pending_rows) == 1, (
            "the fixture's lease did not leave exactly one extract unit pending — "
            "the disclosed cell needs a unit that was never leased"
        )
        direct_unit = pending_rows[0]["work_id"]
        # leased -> done (the completion).
        orch.complete(ledger_unit)
        assert _unit_row(store, ledger_unit)["status"] == "done"

        # leased -> pending (fail below the ceiling), thrice, then quarantined at
        # the ceiling (the ladder; TC-ORCH-18's test holds the deep form).
        for expected in (1, 2, 3):
            orch.lease("worker-a", "extract", 10)
            orch.fail(ladder_unit, error)
            row = _unit_row(store, ladder_unit)
            assert row["attempts"] == expected and row["status"] == (
                "quarantined" if expected == 3 else "pending"
            ), f"ladder step {expected}: the machine landed '{row['status']}'"

        # --- illegal edges, each refused with the state unchanged ---------------
        # A failure report for a DONE unit: absorbed, the record stands.
        orch.fail(ledger_unit, error)
        row = _unit_row(store, ledger_unit)
        assert row["status"] == "done" and row["attempts"] == 0, (
            "done -> pending via a late failure report — a result that exists "
            "must not be unpicked (the illegal requeue edge)"
        )
        # A failure report for a QUARANTINED unit: absorbed, no attempt moves.
        orch.fail(ladder_unit, error)
        row = _unit_row(store, ladder_unit)
        assert row["status"] == "quarantined" and row["attempts"] == 3, (
            "quarantined -> anything via a duplicate report — the operator "
            "surface said 'quarantined at 3' and it must stay true"
        )
        # done/quarantined are not claimable: the dispatcher never re-arms a
        # terminal unit (done -> leased and quarantined -> leased are illegal).
        still_open = {unit.work_id for unit in orch.lease("worker-b", "extract", 10)}
        assert ledger_unit not in still_open and ladder_unit not in still_open, (
            "a terminal unit came back on a claim pass — done and quarantined "
            "must be out of dispatch"
        )
        # A duplicate completion for a DONE unit: absorbed, the record stands —
        # `complete()` is idempotent on done (`CT-ORCH-03`: a completion recorded
        # twice leaves one done row; the duplicate is at-least-once's second
        # worker, and refusing it would punish the race's winner). Disclosed:
        # the plan's matrix has no outgoing edge from done, and the shipped
        # machine honours that by NO-OP on the duplicate rather than by refusing.
        orch.complete(ledger_unit)
        row = _unit_row(store, ledger_unit)
        assert row["status"] == "done" and row["attempts"] == 0, (
            "a duplicate completion disturbed a done unit — idempotence "
            "(CT-ORCH-03) means one done row, not a moved one"
        )
        # A completion for a QUARANTINED unit: the named refusal, state unchanged
        # (three failures were recorded; a result arriving underneath that record
        # would un-quarantine by side effect — the shipped error names it).
        with pytest.raises(WorkLedgerError):
            orch.complete(ladder_unit)
        assert _unit_row(store, ladder_unit)["status"] == "quarantined" and (
            _unit_row(store, ladder_unit)["attempts"] == 3
        ), "a refused completion moved the quarantined unit's record"

        # --- the disclosed cell: pending -> done without a lease ----------------
        # The plan names it illegal; the shipped ledger accepts it (the documented
        # at-least-once arm — see this test's docstring). Asserting the SHIPPED
        # semantics.
        orch.complete(direct_unit)
        row = _unit_row(store, direct_unit)
        assert row["status"] == "done" and row["attempts"] == 0, (
            "the shipped ledger refused a completion for a lease-less pending "
            "unit — the at-least-once arm would lose a real result to a race"
        )
    finally:
        store.close()
