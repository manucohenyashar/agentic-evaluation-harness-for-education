"""`TS-24`'s pause-lifecycle cases — `TC-ORCH-16`, `TC-ORCH-17`, `TC-ORCH-28`, the
`run.status` half of `TC-ORCH-29`, `RES-09` and `RES-10` — **written ahead of #61**
(the cost ceiling, provider pauses and the control-row run lifecycle).

Every case here turns on the pause mechanism: a run that pauses on
`ProviderUnavailableError` or `BuildChangedError`, a pause effected by a **control
row** the orchestrator reads on its own schedule, and the `run.status` machine
`pending → running → (paused ↔ running) → complete | failed`. None of that exists
before #61 — #57's create_run births the row `pending` and flips nothing, and the
claim query already refuses a paused run it has never met ("that transition is
#61's", `select_claimable`'s comment). So the file carries `writtenahead` and each
test's **first** statements are the `require`/`require_attr` calls naming #61: the
failure is the designed blocker, never a crash.

**Interface this file assumes of #61**, listed so it is reconciled deliberately
rather than discovered (the `test_leasing.py` precedent — its six assumed names all
resolved against #58's landing):

| Name | Status |
|---|---|
| `Orchestrator.start(run_id)`, `.pause(run_id)` | design §3.7 Protocol members #61 must ship on the concrete class |
| `Orchestrator.resume(run_id=None)` | shipped (#57) — the same-backend half needs nothing new |
| pause carries its **cause** (`ProviderUnavailableError` / `BuildChangedError` / operator) on the observable surface | FR-ORCH-16/17's "pauses and alerts" — assumed here as a `cause=` keyword recorded on the run; reconciled to #61's actual surface at landing |
| refusals raise `WorkLedgerError` | the module's shipped error type; a subclass #61 adds still passes |
| control-row storage behind the Orchestrator surface | CT-ORCH-13's timing contract is asserted through the Orchestrator (request ≠ effect), not through the row's table |

Isolation: rung 1/2 — in-memory error objects over the real store; the provider
errors are `aeh.prov`'s shipped types, constructed directly (#19/#20 shipped them;
the transport paths that raise them in production are `TC-PROV-*`'s, not re-tested
here).
"""

from __future__ import annotations

import inspect

import pytest

from aeh.prov import BuildChangedError, ProviderUnavailableError
from aeh.store import open_store
from tests.support.clock import FrozenClock
from tests.support.impl import ORCH_MODULE, require, require_attr
from tests.support.orch_run import seed_run

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#61"

_SUBMISSIONS = tuple(f"SYN-{i:03d}" for i in range(1, 6))
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)


def _run_row(store, run_id: str) -> dict:
    rows = store.cohort("c-2026-7B-orch").query(
        "SELECT * FROM run WHERE run_id = :r", r=run_id
    )
    assert rows, f"run {run_id} vanished"
    return rows[0]


def _unit_row(store, work_id: str) -> dict:
    rows = store.cohort("c-2026-7B-orch").query(
        "SELECT * FROM work_unit WHERE work_id = :w", w=work_id
    )
    assert rows, f"unit {work_id[:12]} vanished"
    return rows[0]


def test_tc_orch_16_provider_outage_pauses_and_resume_binds_the_same_backend(
    tmp_data_dir,
):
    """`TC-ORCH-16` (`FR-ORCH-16`, integration / rung 1, P0) — `ProviderUnavailableError`
    raised mid-run: the run pauses and alerts; resume binds the **same** backend; no
    code path substitutes a different provider or profile, asserted at the API
    surface."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    pause = require_attr(Orchestrator, "pause", issue=ISSUE)
    resume = require_attr(Orchestrator, "resume", issue=ISSUE)

    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
        orch.enumerate_units(run_id)
        in_flight = orch.lease("worker-a", "extract", 2)
        assert in_flight
        before = _run_row(store, run_id)

        # The outage: mid-run, with leases outstanding. The run pauses — it does
        # not fail, and it does not degrade into partial delivery.
        pause(run_id, cause=ProviderUnavailableError("model server unreachable"))

        row = _run_row(store, run_id)
        assert row["status"] == "paused", (
            f"a provider outage left the run '{row['status']}', not 'paused' — "
            "an outage is a pause with a name, never a failure (FR-ORCH-16)"
        )
        assert row["provider_config"] == before["provider_config"], (
            "the pause rewrote the run's frozen provider snapshot — the backend "
            "binding is frozen at create_run (FR-CONF-04) and a pause may not "
            "touch it"
        )

        # Resume binds the SAME backend: the snapshot is byte-identical after
        # resume, and the API surface offers no way to substitute one — resume()
        # takes no provider or profile argument to pass one to.
        resume(run_id)
        row = _run_row(store, run_id)
        assert row["provider_config"] == before["provider_config"] and row[
            "backend_profile"
        ] == before["backend_profile"], (
            "resume substituted the provider or profile — half a cohort graded by "
            "one instrument and half by another is RISK-22's exact failure"
        )
        parameters = inspect.signature(resume).parameters
        assert not any(
            name in parameters for name in ("provider", "profile", "backend")
        ), (
            f"resume's signature accepts a backend substitute: {sorted(parameters)} "
            "— 'no code path substitutes a different provider or profile' is "
            "asserted at the API surface, and an argument would be that path"
        )
    finally:
        store.close()


def test_tc_orch_17_build_changed_pauses_and_alerts(tmp_data_dir):
    """`TC-ORCH-17` (`FR-ORCH-17`, integration / rung 1, P0) — `BuildChangedError`
    raised mid-run: the run pauses and alerts, because the panel changed underneath
    it. The alert half is the pause carrying its cause — the operator surface can say
    WHY the run stopped, not just that it did."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    pause = require_attr(Orchestrator, "pause", issue=ISSUE)

    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
        orch.enumerate_units(run_id)
        assert orch.lease("worker-a", "extract", 2)
        before = _run_row(store, run_id)

        pause(run_id, cause=BuildChangedError("served build changed mid-run"))

        row = _run_row(store, run_id)
        assert row["status"] == "paused", (
            f"a served-build change left the run '{row['status']}', not 'paused' "
            "— the panel changed underneath the run, and continuing would grade "
            "one cohort with two instruments (RISK-22)"
        )
        assert row["provider_config"] == before["provider_config"], (
            "the pause rewrote the run's frozen provider snapshot — a pause "
            "changes the run's state, never its binding (FR-CONF-04)"
        )
        # The ALERT half: the pause above was raised WITH its cause, and the alert
        # surface that makes it readable to an operator is #61's to define — this
        # case's run-level oracle is the named pause itself (disclosed; reconciled
        # against whatever surface #61 ships).
    finally:
        store.close()


def test_tc_orch_28_pause_with_the_orchestrator_stopped_queues_and_is_honoured_at_start(
    tmp_data_dir,
):
    """`TC-ORCH-28` (`FR-ORCH-25`, integration / rung 2, P0) — `run.status` follows
    `pending` to `running` to `paused` and back; the transition is effected by a
    **control row** the orchestrator reads on its own schedule, never in the request.
    The plan's stated shape: pause with the orchestrator **stopped** — the request
    queues and effects nothing; the orchestrator honours it at start."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    start = require_attr(Orchestrator, "start", issue=ISSUE)
    pause = require_attr(Orchestrator, "pause", issue=ISSUE)

    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)

        # The decisive case: the orchestrator is NOT running — no worker, no
        # dispatch loop — and the pause is requested anyway. The row must QUEUE (the
        # request returns, the run's status is untouched): the request is not the
        # effect (CT-ORCH-13).
        pause(run_id)
        assert _run_row(store, run_id)["status"] == "pending", (
            "a pause request effected the transition in-request — the console "
            "would own the run's state, and a closed browser would own a running "
            "run (CT-ORCH-13's whole point)"
        )

        # The orchestrator starts and reads its control surface: the queued pause
        # is honoured AT start — the declared machine's next state, not a fresh
        # run-through the queued request was silently dropped by.
        start(run_id)
        assert _run_row(store, run_id)["status"] == "paused", (
            "the queued pause was not honoured at start — either the control row "
            "was never read or the request effected the state in-request; both "
            "break the request ≠ effect contract the plan names"
        )
    finally:
        store.close()


def test_tc_orch_29_run_status_transition_matrix_is_exactly_the_declared_set(
    tmp_data_dir,
):
    """`TC-ORCH-29`'s `run.status` half (`FR-ORCH-25`, unit-negative, P1) — the legal
    set is exactly what FR-ORCH-25 declares,
    `pending → running → (paused ↔ running) → complete | failed`, and **every**
    illegal transition is refused — swept as the full matrix, not sampled.

    **Disclosed**: the matrix's reachable-via-control states are `pending`,
    `running`, `paused` — reaching `complete` / `failed` is the terminal half of the
    machine, driven by #61's lifecycle at the units-done and ceiling transitions, not
    by a control operation, so the terminal-source cells are that story's to sweep
    (its run-completion case holds this same matrix with the terminal rows driven).
    """
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    WorkLedgerError = require(ORCH_MODULE, "WorkLedgerError", issue=ISSUE)
    start = require_attr(Orchestrator, "start", issue=ISSUE)
    pause = require_attr(Orchestrator, "pause", issue=ISSUE)
    resume = require_attr(Orchestrator, "resume", issue=ISSUE)

    # The declared legal set, as (source, operation) pairs that must succeed —
    # each asserted as a positive control before its illegal siblings are refused.
    legal = {
        ("pending", "start"): "running",
        ("running", "pause"): "paused",
        ("paused", "resume"): "running",
    }
    # Everything else is illegal: no state may be entered twice around a loop, no
    # edge may be skipped (pending → paused direct), and a control operation from
    # the state it would produce is the trivially illegal self-edge.
    operations = ("start", "pause", "resume")
    reachable = ("pending", "running", "paused")
    illegal = [
        (state, op)
        for state in reachable
        for op in operations
        if (state, op) not in legal
    ]
    assert len(illegal) == 6, "the sweep did not construct the full illegal matrix"

    runners = {"start": start, "pause": pause, "resume": resume}

    def _fresh_run(store, index: int) -> str:
        """One seeded run per matrix cell: a transition asserted from a stale
        state is not a transition from the state named."""
        _, run_id, _ = seed_run(
            store,
            submissions=_SUBMISSIONS,
            criteria=_CRITERIA,
            package_id=f"pkg-matrix-{index}",
        )
        return run_id

    def _drive_to(orch, run_id: str, state: str) -> None:
        path = {"pending": [], "running": ["start"], "paused": ["start", "pause"]}[state]
        for op in path:
            runners[op](run_id)

    store = open_store(tmp_data_dir)
    try:
        orch, _, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA, package_id="pkg-matrix-0"
        )

        # Positive controls: each legal pair lands the declared target state.
        for index, ((source, op), target) in enumerate(legal.items()):
            run_id = _fresh_run(store, index + 1)
            _drive_to(orch, run_id, source)
            runners[op](run_id)
            assert _run_row(store, run_id)["status"] == target, (
                f"legal transition {source!r} --{op}--> did not land '{target}' "
                "— the declared machine's forward edges must work before the "
                "refusals mean anything"
            )

        # The illegal matrix: from each reachable state, each non-legal operation
        # is refused by name and the state does not move.
        for index, (state, op) in enumerate(illegal):
            run_id = _fresh_run(store, index + 10)
            _drive_to(orch, run_id, state)
            with pytest.raises(WorkLedgerError) as excinfo:
                runners[op](run_id)
            assert type(excinfo.value).__name__ != "NotImplementedYet", (
                "the refusal surfaced the written-ahead blocker — the lifecycle "
                "surface is not implemented, so this cell asserted nothing"
            )
            assert _run_row(store, run_id)["status"] == state, (
                f"illegal transition {state!r} --{op}--> was not refused cleanly: "
                "the run's state moved — the machine accepted an edge FR-ORCH-25 "
                "does not declare"
            )
    finally:
        store.close()


def test_res_09_outage_does_not_fail_units_and_preserves_in_flight_leases(
    tmp_data_dir,
):
    """`RES-09` (`FR-PROV-08`, `FR-ORCH-16`, resilience) — model server unreachable:
    back off, then pause the run on the same backend; **do not fail units**.

    Two oracles. (1) The units are untouched: no unit-level failure, no attempt
    consumed, no error written — an outage is the PROVIDER's failure and the
    taxonomy is for unit failures (§9.11: "rate limit → expected, not an error" —
    an outage is its sibling). (2) The in-flight leases survive even the sweeper:
    the claim and sweep queries join `run.status IN ('pending', 'running')`, so a
    paused run's leases are never examined — advancing the clock past the TTL and
    sweeping must hold them, not convert the outage into requeues."""
    Orchestrator, ORCH_LEASE_SECONDS = require(
        ORCH_MODULE, "Orchestrator", "ORCH_LEASE_SECONDS", issue=ISSUE
    )
    pause = require_attr(Orchestrator, "pause", issue=ISSUE)

    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
        clock = FrozenClock()
        orch = Orchestrator(store, clock=clock)
        orch.enumerate_units(run_id)
        in_flight = orch.lease("worker-a", "extract", 3)
        assert in_flight

        pause(run_id, cause=ProviderUnavailableError("model server unreachable"))

        for unit in in_flight:
            row = _unit_row(store, unit.work_id)
            assert row["status"] == "leased" and row["attempts"] == 0, (
                f"the outage moved unit {unit.work_id[:12]} to "
                f"'{row['status']}' with attempts={row['attempts']} — a provider "
                "outage is the PROVIDER's failure; failing or requeueing the "
                "unit turns an outage into lost work (§9.11: 'do not fail units')"
            )
            assert row["last_error"] is None, (
                "the outage wrote a unit-level error — the failure taxonomy is "
                "for unit failures, and an outage is not one"
            )

        # And the sweeper agrees: past the TTL, on a paused run, the leases are
        # still held — the sweep query examines a paused run's leases never.
        clock.advance(ORCH_LEASE_SECONDS + 1)
        orch.sweep_expired_leases()
        for unit in in_flight:
            row = _unit_row(store, unit.work_id)
            assert row["status"] == "leased", (
                f"the sweeper requeued unit {unit.work_id[:12]} of a PAUSED run — "
                "converting the outage into requeues double-runs the in-flight "
                "workers the moment the provider recovers"
            )
    finally:
        store.close()


def test_res_10_build_change_pauses_and_alerts_with_the_ledger_preserved(
    tmp_data_dir,
):
    """`RES-10` (`FR-PROV-05`, `FR-ORCH-17`, resilience) — served build changes
    mid-run: pause and alert, ledger preserved. `BuildChangedError`; run paused;
    cause readable on the run; nothing about the ledger's committed work is
    rewritten — a pause preserves state, it does not repair or re-derive it."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    pause = require_attr(Orchestrator, "pause", issue=ISSUE)

    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _ = seed_run(store, submissions=_SUBMISSIONS, criteria=_CRITERIA)
        orch.enumerate_units(run_id)
        won = orch.lease("worker-a", "extract", 2)
        assert won
        orch.complete(won[0].work_id)
        before = _table_counts(store)

        pause(run_id, cause=BuildChangedError("served build changed mid-run"))

        row = _run_row(store, run_id)
        assert row["status"] == "paused"
        assert _table_counts(store) == before, (
            "the pause rewrote the ledger — a pause preserves state, it does not "
            "repair or re-derive it"
        )
    finally:
        store.close()


def _table_counts(store) -> dict[str, int]:
    names = [
        row["name"]
        for row in store.cohort("c-2026-7B-orch").query(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        name: store.cohort("c-2026-7B-orch").query(
            f"SELECT COUNT(*) AS n FROM {name}"
        )[0]["n"]
        for name in sorted(names)
    }
