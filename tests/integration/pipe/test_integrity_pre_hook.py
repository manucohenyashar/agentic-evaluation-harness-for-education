"""`TS-83` (issue #377) — `TC-PIPE-03`: `integrity_pre` runs exactly once, when a cell's
extraction is terminal (`FR-PIPE-03`, gap-fix test plan §5 / §6).

| Arm | Cell state | Expected |
|---|---|---|
| (a) | both extract units `done` | 1 `verify` call, and a `cell_phase` row `integrity_pre` |
| (b) | one `done`, one `pending` | 0 calls, no row |
| (c) | one `done`, one `quarantined` | 1 call — quarantined is **terminal** |
| (d) | (a) driven for a second pass | still 1 call in total |

**The requirement.** `FR-PIPE-03`: when every `extract` unit of a cell is terminal and the cell
has no `integrity_pre` phase, call `IntegrityGate.verify` once and record the phase
(`FR-ORCH-28`). The phase row is what makes the hook resume-safe — arm (d) is the one that
matters most in practice, because a composer that re-ran the gate on every pass would pay for
the work again on every crash recovery and could route a cell twice.

**The oracle is an exact call count**, not "verify was called". Arm (c) and arm (b) differ only
in the state of one unit, and an implementation that treated `quarantined` as non-terminal gives
0 where 1 is required — a difference no existence check can see. The spy wraps
`IntegrityGate.verify` and records `(run_id, submission_id, criterion_id)` per call, so the
count is per cell rather than global.

**Terminal, and why `quarantined` counts.** A quarantined unit will never produce evidence. If
the gate waited for it the cell would hang forever, so the requirement says terminal, not
successful — and arm (c) is what stops an implementation from reading it as "done".

**The world:** see this directory's `conftest.py`. F-DEV-PIPE does not exist; the arms are set up
by driving this world's own extract units to the states each arm names.

**Written ahead of implementation: yes** — `aeh.pipeline` is #364's.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.impl import PIPE_MODULE, require

pytestmark = pytest.mark.integration

ISSUE = "#364"

PHASE_INTEGRITY_PRE = "integrity_pre"


class _VerifySpy:
    """Counts `IntegrityGate.verify` per cell, and forwards to the real gate.

    Forwarding rather than stubbing is deliberate: the run must still behave, because arm (d)
    drives a second pass and a stubbed gate would change what the second pass sees.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, run_id: str, submission_id: str, criterion_id: str, *args: Any,
                 **kwargs: Any) -> Any:
        self.calls.append((run_id, submission_id, criterion_id))
        return self._inner(run_id, submission_id, criterion_id, *args, **kwargs)

    def for_cell(self, submission_id: str, criterion_id: str) -> int:
        return sum(
            1 for _run, sid, cid in self.calls
            if (sid, cid) == (submission_id, criterion_id)
        )


@pytest.fixture
def verify_spy(monkeypatch):
    """Wrap `IntegrityGate.verify` for the whole test, before any world is built.

    Patched on the class rather than on an instance: `M-PIPE` constructs its own gate
    (`FR-PIPE-10`), so there is no instance for a test to reach into.
    """
    from aeh.integ import IntegrityGate

    original = IntegrityGate.verify
    spy = _VerifySpy(original)

    def _patched(gate: Any, run_id: str, submission_id: str, criterion_id: str,
                 *args: Any, **kwargs: Any) -> Any:
        spy.calls.append((run_id, submission_id, criterion_id))
        return original(gate, run_id, submission_id, criterion_id, *args, **kwargs)

    monkeypatch.setattr(IntegrityGate, "verify", _patched)
    return spy


def _cell_phases(world: Any, submission_id: str, criterion_id: str) -> set[str]:
    """The phases recorded for one cell, read off `cell_phase` (FR-ORCH-28)."""
    from aeh.store import Statement

    rows = world.handle.query(
        Statement(
            "SELECT phase FROM cell_phase WHERE run_id = :run_id "
            "AND submission_id = :submission_id AND criterion_id = :criterion_id"
        ),
        run_id=world.run_id, submission_id=submission_id, criterion_id=criterion_id,
    )
    return {str(row["phase"]) for row in rows}


def _first_judged_cell(world: Any) -> tuple[str, str]:
    return world.admitted_ids()[0], world.open_ids[0]


# --- TC-PIPE-03 ----------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_pipe_03_a_terminal_cell_is_verified_once_and_records_its_phase(
    make_pipe_world, verify_spy
):
    """Arm (a) — every extract unit terminal: exactly one `verify`, and the phase row exists."""
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()
    submission_id, criterion_id = _first_judged_cell(world)

    run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    assert verify_spy.for_cell(submission_id, criterion_id) >= 1, (
        f"the gate never ran on cell ({submission_id}, {criterion_id}) although its extraction "
        "is terminal (FR-PIPE-03)"
    )
    assert PHASE_INTEGRITY_PRE in _cell_phases(world, submission_id, criterion_id), (
        f"no {PHASE_INTEGRITY_PRE!r} phase recorded for ({submission_id}, {criterion_id}); "
        "without it the hook re-runs on every pass and is not resume-safe (FR-ORCH-28)"
    )


@pytest.mark.writtenahead
def test_tc_pipe_03_a_cell_with_a_pending_extract_unit_is_not_verified(
    make_pipe_world, verify_spy
):
    """Arm (b) — one unit still `pending`: 0 calls for that cell, and no phase row.

    The cell is held non-terminal by driving the run with a bound that stops before extraction
    drains, so one unit of the cell is genuinely still pending rather than made so by hand.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()
    submission_id, criterion_id = _first_judged_cell(world)

    run_to_completion(
        world.store, world.run_id, provider=world.provider,
        run_config=world.resolved, max_passes=1, max_units=1,
    )

    units = [
        u for u in world.orchestrator.enumerate_units(world.run_id)
        if (u.submission_id, u.criterion_id) == (submission_id, criterion_id)
    ]
    pending = [u for u in units if getattr(u, "state", None) == "pending"]
    assert pending, (
        "arm (b)'s precondition could not be established: the bounded pass drained this cell's "
        "extraction, so no unit is pending and the assertion below would pass vacuously. "
        "#364 must expose a bound that stops mid-cell (`max_units` is this case's interface "
        "assumption) or this arm needs a different lever — a skip here would hide that."
    )
    assert verify_spy.for_cell(submission_id, criterion_id) == 0, (
        f"the gate ran on ({submission_id}, {criterion_id}) while {len(pending)} of its extract "
        "unit(s) were still pending; FR-PIPE-03 waits for every unit to be terminal"
    )
    assert PHASE_INTEGRITY_PRE not in _cell_phases(world, submission_id, criterion_id), (
        "a phase was recorded for a cell the gate has not run on"
    )


@pytest.mark.writtenahead
def test_tc_pipe_03_a_quarantined_extract_unit_is_terminal(make_pipe_world, verify_spy):
    """Arm (c) — `quarantined` is terminal, so the cell is verified.

    An implementation reading "terminal" as "done" gives 0 here and passes arms (a), (b) and
    (d) — and in production the cell would wait forever on a unit that will never produce
    evidence.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world(quarantine_indices=(1,))
    submission_id, criterion_id = _first_judged_cell(world)

    run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    units = world.orchestrator.enumerate_units(world.run_id)
    quarantined = [u for u in units if getattr(u, "state", None) == "quarantined"]
    assert quarantined, (
        "arm (c)'s precondition could not be established: no extract unit quarantined, so "
        "'quarantined is terminal' is not exercised and this arm would pass vacuously. The "
        "specified world (F-DEV-PIPE) is absent; #364 must confirm how a quarantined extract "
        "unit is produced here."
    )
    cell = (quarantined[0].submission_id, quarantined[0].criterion_id)
    assert verify_spy.for_cell(*cell) >= 1, (
        f"the gate never ran on {cell}, whose extraction ended quarantined. Quarantined is "
        "TERMINAL (FR-PIPE-03): a cell waiting on it waits forever"
    )


@pytest.mark.writtenahead
def test_tc_pipe_03_a_second_pass_does_not_verify_the_cell_again(make_pipe_world, verify_spy):
    """Arm (d) — driving the completed run a second time leaves the count unchanged.

    The phase row is the guard. A composer that re-ran the gate whenever a cell's extraction
    looked terminal would pay for the work again on every recovery — and `CT-ORCH-24` says the
    phase is written idempotently for exactly this reason.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()
    submission_id, criterion_id = _first_judged_cell(world)

    run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )
    after_first = verify_spy.for_cell(submission_id, criterion_id)
    assert after_first >= 1, "precondition: the first pass never verified the cell"

    run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    assert verify_spy.for_cell(submission_id, criterion_id) == after_first, (
        f"a second drive re-verified ({submission_id}, {criterion_id}): "
        f"{after_first} call(s) became {verify_spy.for_cell(submission_id, criterion_id)}. The "
        f"{PHASE_INTEGRITY_PRE!r} phase exists so the hook runs once"
    )
