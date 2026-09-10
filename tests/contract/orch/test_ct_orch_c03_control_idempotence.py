"""`TC-ORCH-C03` — control-surface idempotence under double-click (§6.11.7): every
lifecycle request applied twice leaves the run exactly where the first application put
it (`CT-ORCH-03`'s ledger idempotence; `CT-ORCH-13`'s request ≠ effect).

The double-click is a real operator event: the console polls, an operator refreshes, a
supervisor retried the request — and the control row is the durable record of each
request, so "applied twice" shows up as exactly one MORE `run_control` row per repeated
request (marked applied), and **nothing else moves**: the run's status, the unit
projection, and every result table hold still. The one growth the sweep forgives is
`run_control` — the queue itself — and the sweep pins even that: a repeated no-arg
`resume()` writes nothing (it only reads and applies), and a refused request writes
nothing at all.

Relationship to shipped cases, disclosed: `tests/integration/orch/test_pause_lifecycle.py`
(TC-ORCH-16/17/28/29) drives each transition ONCE and asserts the effect; the resume
differential (`tests/resilience/orch/test_resume.py`, RES-04/05/09) kills and redrives.
Neither presses a second click — the C03 limb. The no-arg signature half is the
acceptance form of FR-ORCH-02: resume requires no bookkeeping beyond the ledger, so
`resume()` must be callable with no argument at all.
"""

from __future__ import annotations

import inspect

import pytest

from aeh.orch import Orchestrator, RunStateError
from aeh.store import open_store
from tests.contract.orch._doubles import table_row_counts, unit_projection
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.contract]

_SUBMISSIONS = ("SYN-001", "SYN-002")
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C2", "kind": "mcq"},
)


def test_tc_orch_c03_resume_is_callable_with_no_arguments():
    """FR-ORCH-02's acceptance form, at the API surface: `resume` takes no required
    argument — discovery is the ledger's job, never the operator's."""
    signature = inspect.signature(Orchestrator.resume)
    required = [
        name
        for name, param in signature.parameters.items()
        if param.default is inspect.Parameter.empty and name not in ("self", "cls")
    ]
    assert not required, (
        f"Orchestrator.resume requires {required} — resume-without-args (FR-ORCH-02) "
        "means the ledger is the only bookkeeping; a required argument is a place for "
        "an operator to be wrong under time pressure"
    )


def _manual_completion_drive(store, orchestrator, run_id):
    """Drive every unit to `done` without a transport: lease each stage and complete.

    The completion of the LAST open unit flips the run row to `complete`
    (`_maybe_complete_run` fires on the won lifecycle write), so this returns with a
    terminal run and no model call anywhere — the deterministic criterion's units need
    no provider and the judged units are completed by hand at the ledger boundary the
    `complete(work_id, result)` surface exists for.
    """
    completed: list[str] = []
    for stage in ("extract", "score", "deterministic"):
        while True:
            units = orchestrator.lease("w-c03", stage, 8)
            if not units:
                break
            for unit in units:
                orchestrator.complete(unit.work_id)
                completed.append(unit.work_id)
    return completed


def test_tc_orch_c03_double_click_on_a_running_run_moves_nothing_else(tmp_data_dir):
    """The running-run double-click: pause×2, resume×2, no-arg resume()×2, then the
    refused start. Every pair may add its `run_control` row — and nothing else."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA
        )
        orchestrator.enumerate_units(run_id)
        assert orchestrator.start(run_id) == "running"
        baseline_projection = unit_projection(store, ORCH_COHORT_ID, run_id)
        baseline_counts = table_row_counts(store, ORCH_COHORT_ID)

        # pause ×2 — the first lands (running → paused), the second is recorded as
        # satisfied; neither touches a unit.
        assert orchestrator.pause(run_id) == "paused"
        assert orchestrator.pause(run_id, cause="operator double-click") == "paused"
        after_pauses = table_row_counts(store, ORCH_COHORT_ID)
        assert unit_projection(store, ORCH_COHORT_ID, run_id) == baseline_projection
        growth = {
            t: after_pauses[t] - baseline_counts[t]
            for t in after_pauses
            if after_pauses[t] != baseline_counts[t]
        }
        assert set(growth) == {"run_control"}, (
            f"two pauses on a running run grew {growth} — only the control queue may "
            "record a repeated request; any other table moving means a pause re-ran "
            "work or rewrote state the first application already fixed"
        )
        assert growth["run_control"] == 2, (
            f"two pause requests wrote {growth.get('run_control')} control rows — each "
            "request is its own durable record (CT-ORCH-13), exactly one per click"
        )

        # resume ×2 (explicit) — the first effects paused → running; the second is a
        # vacuous request on a running run, recorded and marked applied.
        orchestrator.resume(run_id)
        orchestrator.resume(run_id)
        assert unit_projection(store, ORCH_COHORT_ID, run_id) == baseline_projection
        after_resumes = table_row_counts(store, ORCH_COHORT_ID)
        growth = {
            t: after_resumes[t] - after_pauses[t]
            for t in after_resumes
            if after_resumes[t] != after_pauses[t]
        }
        assert set(growth) == {"run_control"}, (
            f"two explicit resumes grew {growth} — a re-enumeration double-click may "
            "record requests, never mint rows elsewhere (the re-enumeration itself is "
            "INSERT OR IGNORE: the unit projection above is the proof)"
        )
        assert growth["run_control"] == 2

        # resume() ×2, no-arg — reads and applies only; WRITES NOTHING.
        orchestrator.resume()
        orchestrator.resume()
        after_noarg = table_row_counts(store, ORCH_COHORT_ID)
        assert after_noarg == after_resumes, (
            "the no-argument resume changed the ledger — it must discover from the "
            "ledger and apply unapplied control rows only; a write here is a second, "
            "undisclosed request channel (FR-ORCH-02)"
        )
        assert unit_projection(store, ORCH_COHORT_ID, run_id) == baseline_projection

        # start on a running run — refused by the state machine, no rows, no flip.
        with pytest.raises(RunStateError):
            orchestrator.start(run_id)
        assert table_row_counts(store, ORCH_COHORT_ID) == after_noarg, (
            "a refused start wrote rows — a refusal must be a refusal, not a rewrite"
        )
        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT status FROM run WHERE run_id = :r", r=run_id
        )
        assert rows[0]["status"] == "running"
    finally:
        store.close()


def test_tc_orch_c03_double_click_on_a_completed_run_is_inert(tmp_data_dir):
    """The terminal double-click: pause refuses, start refuses, no-arg resume skips the
    run, a repeated `complete` on a done unit is the silent no-op CT-ORCH-03 names —
    and none of it adds a row or un-completes the run."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA
        )
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)
        done_units = _manual_completion_drive(store, orchestrator, run_id)
        assert done_units, "the drive completed no units — the sweep would be vacuous"
        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT status FROM run WHERE run_id = :r", r=run_id
        )
        assert rows[0]["status"] == "complete", (
            "the fixture's last completion should flip the run to complete "
            "(_maybe_complete_run fires on the won lifecycle write)"
        )
        baseline_projection = unit_projection(store, ORCH_COHORT_ID, run_id)
        baseline_counts = table_row_counts(store, ORCH_COHORT_ID)

        with pytest.raises(RunStateError):
            orchestrator.pause(run_id)
        with pytest.raises(RunStateError):
            orchestrator.start(run_id)

        # The no-arg discovery must SKIP the terminal run — neither crash on it nor
        # resurrect it.
        orchestrator.resume()

        # A repeated completion of an already-done unit: the ledger says done, the
        # second record is the no-op the double-run worker relies on.
        for work_id in done_units:
            orchestrator.complete(work_id)

        # An explicit resume on a terminal run is not even recorded (the guard reads
        # the state first) — the count below pins that too.
        orchestrator.resume(run_id)

        assert table_row_counts(store, ORCH_COHORT_ID) == baseline_counts, (
            "a double-click on a completed run changed the ledger — a terminal run "
            "keeps its record (CT-ORCH-13's 'a pause is not a rewrite of history'), "
            "and a repeated completion must leave one done row, not grow the ledger"
        )
        assert unit_projection(store, ORCH_COHORT_ID, run_id) == baseline_projection
        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT status FROM run WHERE run_id = :r", r=run_id
        )
        assert rows[0]["status"] == "complete"
    finally:
        store.close()
