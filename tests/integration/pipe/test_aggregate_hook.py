"""`TS-83` (issue #377) — `TC-PIPE-04`: aggregation hook order, and one transaction for score +
escalation + phase (`FR-PIPE-04`, gap-fix test plan §5 / §6).

| Expected | |
|---|---|
| order | `verify → verdicts_for → aggregate → write_score → should_escalate → enqueue_escalation → mark_cell_phase('aggregated', units_consumed=3)` |
| second pass | after the escalation's two extra verdicts land, the same cell aggregates again with `units_consumed=5` |
| rows | exactly one `criterion_score` row for the cell; the escalation units enqueued exactly once |
| atomicity | `write_score` raising `sqlite3.IntegrityError` → no `criterion_score` row, no escalation units, no `aggregated` phase; the run pauses with `pause_reason` starting `composition fault: IntegrityError` |
| no-escalation | a cell whose `should_escalate` is false → no `enqueue_escalation` call, phase recorded with `units_consumed=3` |

**Why the order is the requirement and not an implementation detail.** `FR-PIPE-04` numbers the
five steps, and each ordering mistake is a real defect with a quiet symptom: aggregating before
the post-panel `verify` scores a cell whose sufficiency signals were never captured; calling
`should_escalate` before `write_score` decides on a score that is not yet stored; recording the
phase before the escalation enqueues leaves a cell that looks aggregated with no widening
queued. A test that asserted only "these were all called" catches none of them.

**The atomicity arm is the one that earns the file.** Step 4 is explicitly *one* cohort
transaction — `write_score`, `should_escalate` and `enqueue_escalation` together. If they are not,
a failure between them leaves a score with no escalation, or escalation units for a score that
was rolled back. Injecting `sqlite3.IntegrityError` into `write_score` and asserting **all three**
absences is what distinguishes one transaction from three that usually succeed.

**`units_consumed` is the resume guard.** `FR-ORCH-29` re-offers a cell whose terminal score-unit
count exceeds the recorded `aggregated_units`, which is what makes the escalation's second
aggregation happen exactly once rather than on every pass.

**The world:** see this directory's `conftest.py`. F-DEV-PIPE does not exist — in particular its
"criterion `C2`'s recorded panel is `(2,4,4)`" precondition is not reproducible here, so the
escalating cell is *discovered* from the world's own aggregation rather than named, and the
no-escalation arm takes a cell that did not escalate. `units_consumed=3` is this world's panel
size, which `conftest` pins at 3.

**Written ahead of implementation: yes** — `aeh.pipeline` is #364's.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from tests.support.impl import PIPE_MODULE, require

pytestmark = pytest.mark.integration

ISSUE = "#364"

#: `FR-PIPE-04`'s five steps, as the call names a spy sees them.
EXPECTED_ORDER = (
    "verify", "verdicts_for", "aggregate", "write_score", "should_escalate",
    "enqueue_escalation", "mark_cell_phase",
)

PHASE_AGGREGATED = "aggregated"


class _OrderSpy:
    """Records the order of the hook calls `FR-PIPE-04` names, forwarding each to the real one."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def wrap(self, monkeypatch: Any, module: Any, name: str) -> None:
        original = getattr(module, name)
        recorder = self.calls

        def _patched(*args: Any, **kwargs: Any) -> Any:
            recorder.append(name)
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, _patched)

    def wrap_method(self, monkeypatch: Any, owner: type, name: str) -> None:
        original = getattr(owner, name)
        recorder = self.calls

        def _patched(self_: Any, *args: Any, **kwargs: Any) -> Any:
            recorder.append(name)
            return original(self_, *args, **kwargs)

        monkeypatch.setattr(owner, name, _patched)

    def order(self) -> tuple[str, ...]:
        """The first occurrence of each recorded name, in order — the sequence the plan pins."""
        seen: list[str] = []
        for name in self.calls:
            if name not in seen:
                seen.append(name)
        return tuple(seen)


@pytest.fixture
def order_spy(monkeypatch):
    """Wrap every hook `FR-PIPE-04` names, before any world is built."""
    import aeh.agg
    import aeh.judge
    from aeh.integ import IntegrityGate
    from aeh.orch import Orchestrator

    spy = _OrderSpy()
    spy.wrap_method(monkeypatch, IntegrityGate, "verify")
    spy.wrap(monkeypatch, aeh.judge, "verdicts_for")
    spy.wrap(monkeypatch, aeh.agg, "aggregate")
    spy.wrap(monkeypatch, aeh.agg, "write_score")
    spy.wrap(monkeypatch, aeh.agg, "should_escalate")
    spy.wrap_method(monkeypatch, Orchestrator, "enqueue_escalation")
    spy.wrap_method(monkeypatch, Orchestrator, "mark_cell_phase")
    return spy


def _scores(world: Any, submission_id: str, criterion_id: str) -> list[dict[str, Any]]:
    from aeh.store import Statement

    return [
        dict(row) for row in world.handle.query(
            Statement(
                "SELECT run_id, submission_id, criterion_id, judge_count, state "
                "FROM criterion_score WHERE run_id = :run_id "
                "AND submission_id = :submission_id AND criterion_id = :criterion_id"
            ),
            run_id=world.run_id, submission_id=submission_id, criterion_id=criterion_id,
        )
    ]


def _phases(world: Any, submission_id: str, criterion_id: str) -> dict[str, Any]:
    from aeh.store import Statement

    return {
        str(row["phase"]): row["units_consumed"]
        for row in world.handle.query(
            Statement(
                "SELECT phase, units_consumed FROM cell_phase WHERE run_id = :run_id "
                "AND submission_id = :submission_id AND criterion_id = :criterion_id"
            ),
            run_id=world.run_id, submission_id=submission_id, criterion_id=criterion_id,
        )
    }


def _escalated_cell(world: Any) -> tuple[str, str] | None:
    """A cell that actually escalated in this run, discovered rather than named.

    F-DEV-PIPE's `(2,4,4)` panel is not reproducible here, so the arm that needs an escalating
    cell finds one instead of assuming which criterion it is.
    """
    from aeh.store import Statement

    rows = world.handle.query(
        Statement(
            "SELECT DISTINCT submission_id, criterion_id FROM work_unit "
            "WHERE run_id = :run_id AND stage = 'score' AND judge_id LIKE 'escalation-%'"
        ),
        run_id=world.run_id,
    )
    return (str(rows[0]["submission_id"]), str(rows[0]["criterion_id"])) if rows else None


# --- TC-PIPE-04 ----------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_pipe_04_the_hooks_run_in_the_order_fr_pipe_04_numbers(make_pipe_world, order_spy):
    """The five steps, in order. Each wrong order is a real defect with a quiet symptom — see
    the module docstring — so the oracle is the exact sequence, not the set."""
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()

    run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    order = order_spy.order()
    expected = tuple(name for name in EXPECTED_ORDER if name in order)
    assert order == expected, (
        f"the composition called its hooks in this order: {order}\n"
        f"FR-PIPE-04 numbers them: {EXPECTED_ORDER}\n"
        "Aggregating before the post-panel verify scores a cell whose sufficiency signals were "
        "never captured; deciding escalation before write_score decides on an unstored score"
    )


@pytest.mark.writtenahead
def test_tc_pipe_04_one_score_row_and_a_recorded_phase_per_cell(make_pipe_world):
    """Exactly one `criterion_score` row for the cell, and an `aggregated` phase carrying the
    unit count consumed. Two rows would mean the cell was aggregated twice without the phase
    guard noticing."""
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()
    submission_id, criterion_id = world.admitted_ids()[0], world.open_ids[0]

    run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    rows = _scores(world, submission_id, criterion_id)
    assert len(rows) == 1, (
        f"cell ({submission_id}, {criterion_id}) carries {len(rows)} criterion_score rows; "
        "FR-AGG-15 upserts one per (run, submission, criterion)"
    )
    phases = _phases(world, submission_id, criterion_id)
    assert PHASE_AGGREGATED in phases, (
        f"no {PHASE_AGGREGATED!r} phase for ({submission_id}, {criterion_id}): {phases}. "
        "Without it FR-ORCH-29 re-offers the cell on every pass"
    )
    assert phases[PHASE_AGGREGATED] == 3, (
        f"the phase records units_consumed={phases[PHASE_AGGREGATED]}; this world's panel is "
        "three judges, so a first aggregation consumes three score units"
    )


@pytest.mark.writtenahead
def test_tc_pipe_04_an_escalated_cell_aggregates_again_with_five_units(make_pipe_world):
    """After the escalation's two extra verdicts land, the cell aggregates a second time with
    `units_consumed=5` — and the escalation units were enqueued exactly once."""
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()

    run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    cell = _escalated_cell(world)
    assert cell is not None, (
        "no cell escalated in this run, so the second-aggregation arm asserted nothing. "
        "F-DEV-PIPE pins an escalating criterion by its recorded (2,4,4) panel; that corpus "
        "does not exist here (see conftest), so #364 must confirm how this arm gets its cell"
    )
    phases = _phases(world, *cell)
    assert phases.get(PHASE_AGGREGATED) == 5, (
        f"cell {cell} escalated but its aggregated phase records "
        f"units_consumed={phases.get(PHASE_AGGREGATED)!r}; after two escalation verdicts land "
        "the second aggregation consumes five score units (FR-ORCH-29)"
    )
    assert len(_scores(world, *cell)) == 1, (
        f"cell {cell} aggregated twice and left {len(_scores(world, *cell))} score rows; the "
        "second aggregation upserts the first (FR-AGG-15)"
    )


@pytest.mark.writtenahead
def test_tc_pipe_04_a_failing_write_score_leaves_no_score_no_escalation_and_no_phase(
    make_pipe_world, monkeypatch
):
    """Atomicity — step 4 is **one** cohort transaction.

    `write_score` raises `sqlite3.IntegrityError`. All three absences are asserted together:
    an implementation running the three steps in separate transactions leaves at least one of
    them behind, and that is precisely the state this arm exists to make impossible.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    import aeh.agg

    def _failing_write_score(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.IntegrityError("injected: write_score")

    monkeypatch.setattr(aeh.agg, "write_score", _failing_write_score)
    world = make_pipe_world()

    result = run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    submission_id, criterion_id = world.admitted_ids()[0], world.open_ids[0]
    assert _scores(world, submission_id, criterion_id) == [], (
        "write_score raised, but a criterion_score row survived — the write was not rolled back"
    )
    assert PHASE_AGGREGATED not in _phases(world, submission_id, criterion_id), (
        "write_score raised, but the cell is marked aggregated — the phase committed outside "
        "the transaction that failed, so a resume will never retry this cell"
    )
    assert _escalated_cell(world) is None, (
        "write_score raised, but escalation units were enqueued — the escalation committed "
        "separately from the score it was decided on (FR-PIPE-04 step 4: ONE transaction)"
    )
    assert str(result.pause_reason or "").startswith("composition fault: IntegrityError"), (
        f"pause_reason is {result.pause_reason!r}; the plan pins a reason starting "
        '"composition fault: IntegrityError"'
    )


@pytest.mark.writtenahead
def test_tc_pipe_04_a_cell_that_does_not_escalate_enqueues_nothing(make_pipe_world, order_spy):
    """A cell whose `should_escalate` is false records its phase with `units_consumed=3` and
    never calls `enqueue_escalation` for that cell."""
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()

    run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    escalated = _escalated_cell(world)
    quiet = [
        (sid, cid)
        for sid in world.admitted_ids() for cid in world.open_ids
        if (sid, cid) != escalated and _phases(world, sid, cid)
    ]
    assert quiet, "every judged cell escalated, so this arm asserted nothing"
    for sid, cid in quiet:
        assert _phases(world, sid, cid).get(PHASE_AGGREGATED) == 3, (
            f"non-escalating cell ({sid}, {cid}) records "
            f"units_consumed={_phases(world, sid, cid).get(PHASE_AGGREGATED)!r}; a cell that "
            "did not widen consumed its three panel verdicts and no more"
        )
