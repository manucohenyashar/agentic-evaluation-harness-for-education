"""`TS-83` (issue #377) — `TC-PIPE-02`: no unit is `done` without its payload row
(`FR-PIPE-02`, gap-fix test plan §5 / §6).

| Case | Expected |
|---|---|
| `TC-PIPE-02` | For each stage pair `(extract → evidence, score → verdict, deterministic → criterion_score)`, the count of `done` units with no payload row for the same `(run, submission, criterion[, judge])` is **zero**. The faulted unit is not `done` — it is `pending` with `attempts = 1`, or quarantined after the strike ladder |

**The requirement this pins.** `FR-PIPE-02` replaces "the answer-discarding path": every leased
unit is executed by the owning stage door, and no unit reaches `done` without the stage's payload
row existing in the same cohort. The failure it exists to prevent is the worst kind — a run that
reports `complete` with every unit `done` and nothing actually scored, because the composer
marked units done without asking the worker to do anything.

**The oracle is an invariant, not an example.** The three counts are swept across the whole run
rather than checked on the faulted cell, so a driver that loses a payload row *anywhere* fails —
including on cells the fault never touched. The no-fault arm asserts the same three counts are
zero on a clean run, which is what stops the invariant from passing vacuously because the query
was wrong.

**The fault, and where it goes.** A wrapping provider raises `RuntimeError("after-call")` *after*
the recorded response is returned, on the second score call for one cell. That is the injury the
requirement is about: the model call succeeded and was paid for, and the process died between the
answer and the row. A fault before the call would prove nothing — nothing was at risk yet.

**The world:** see this directory's `conftest.py`. F-DEV-PIPE does not exist; the specified
submission `S2`/criterion `C1` are addressed positionally against this world's own admitted ids.

**Written ahead of implementation: yes** — `aeh.pipeline` is #364's.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.impl import PIPE_MODULE, require

pytestmark = pytest.mark.integration

ISSUE = "#364"


class _FaultAfterCall:
    """Wraps the world's provider and raises **after** the recorded response is returned.

    `nth` counts matching calls; the fault fires once, on the nth. Everything else is forwarded
    untouched, so the run is the real run with one injury in it.
    """

    def __init__(self, inner: Any, *, nth: int = 2) -> None:
        self._inner = inner
        self._nth = nth
        self.calls = 0
        self.fired = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def complete(self, *args: Any, **kwargs: Any) -> Any:
        answer = self._inner.complete(*args, **kwargs)
        self.calls += 1
        if self.calls == self._nth and not self.fired:
            self.fired = True
            raise RuntimeError("after-call")
        return answer


#: The three payload reads, one per stage pair. Declared `Statement`s with keyword parameters,
#: the same discipline `SEC-15` holds `src/` to — a test that hand-assembled SQL here would be
#: modelling a shape the design forbids.
_PAYLOAD_SQL = {
    "evidence": "SELECT submission_id, criterion_id FROM evidence WHERE run_id = :run_id",
    "verdict": (
        "SELECT submission_id, criterion_id, judge_id FROM verdict WHERE run_id = :run_id"
    ),
    "criterion_score": (
        "SELECT submission_id, criterion_id FROM criterion_score WHERE run_id = :run_id"
    ),
}


def _payload_rows(world: Any, which: str) -> list[dict[str, Any]]:
    from aeh.store import Statement

    return [
        dict(row)
        for row in world.handle.query(Statement(_PAYLOAD_SQL[which]), run_id=world.run_id)
    ]


def _orphan_counts(world: Any) -> dict[str, int]:
    """`done` units with no payload row, per stage pair — the three figures that must be zero.

    Counted through `M-ORCH`'s own unit enumeration and the cohort's stored rows, so the query
    is about what the system recorded rather than about what the driver believes it did.
    """
    from aeh.orch import STAGE_DETERMINISTIC, STAGE_EXTRACT, STAGE_SCORE

    units = world.orchestrator.enumerate_units(world.run_id)
    done = [u for u in units if getattr(u, "state", None) == "done"]

    evidence = {
        (row["submission_id"], row["criterion_id"]) for row in _payload_rows(world, "evidence")
    }
    verdicts = {
        (row["submission_id"], row["criterion_id"], row["judge_id"])
        for row in _payload_rows(world, "verdict")
    }
    scores = {
        (row["submission_id"], row["criterion_id"])
        for row in _payload_rows(world, "criterion_score")
    }

    counts = {"extract": 0, "score": 0, "deterministic": 0}
    for unit in done:
        stage = getattr(unit, "stage", None)
        cell = (unit.submission_id, unit.criterion_id)
        if stage == STAGE_EXTRACT and cell not in evidence:
            counts["extract"] += 1
        elif stage == STAGE_SCORE and (
            unit.submission_id, unit.criterion_id, getattr(unit, "judge_id", None)
        ) not in verdicts:
            counts["score"] += 1
        elif stage == STAGE_DETERMINISTIC and cell not in scores:
            counts["deterministic"] += 1
    return counts


# --- TC-PIPE-02 ----------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_pipe_02_a_clean_run_leaves_no_done_unit_without_its_payload(make_pipe_world):
    """`TC-PIPE-02`, no-fault arm — the invariant holds on an uninjured run.

    This arm is what stops the fault arm from passing vacuously: if the three queries were
    wrong, they would report zero here too, and a reader could not tell a working invariant
    from one that never looks at anything. So this arm also asserts the run actually produced
    payload rows.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()

    result = run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )
    assert result.status == "complete", f"precondition: the clean run ended {result.status!r}"

    counts = _orphan_counts(world)
    assert counts == {"extract": 0, "score": 0, "deterministic": 0}, (
        f"done units with no payload row on a clean run: {counts}. FR-PIPE-02: no unit is done "
        "without the stage's payload row in the same cohort"
    )
    assert _payload_rows(world, "evidence"), (
        "the invariant reported zero orphans but the run wrote no evidence rows at all — the "
        "query is looking at nothing, so the zero means nothing"
    )


@pytest.mark.writtenahead
def test_tc_pipe_02_a_fault_after_the_model_call_leaves_the_unit_not_done(make_pipe_world):
    """`TC-PIPE-02`, fault arm — the faulted unit is not `done`, and the invariant still holds.

    The provider answers, then raises. A composer that marked the unit done on the strength of
    the model call having succeeded leaves a `done` unit with no verdict row, which is exactly
    the count this case sweeps.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()
    faulting = _FaultAfterCall(world.provider, nth=2)

    run_to_completion(
        world.store, world.run_id, provider=faulting, run_config=world.resolved,
    )

    assert faulting.fired, (
        "the injected fault never fired, so this case asserted nothing about a faulted unit"
    )
    counts = _orphan_counts(world)
    assert counts == {"extract": 0, "score": 0, "deterministic": 0}, (
        f"a fault after the model call left done units with no payload row: {counts}. The unit "
        "must stay pending (attempts = 1) or quarantine through the strike ladder — never done"
    )


@pytest.mark.writtenahead
def test_tc_pipe_02_the_faulted_unit_is_pending_or_quarantined(make_pipe_world):
    """`TC-PIPE-02` — the faulted unit's own state: `pending` with `attempts = 1`, or
    quarantined after the strike ladder. `CT-PIPE-02` is satisfied by the pair holding a
    quarantined unit."""
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()
    faulting = _FaultAfterCall(world.provider, nth=2)

    run_to_completion(
        world.store, world.run_id, provider=faulting, run_config=world.resolved,
    )
    assert faulting.fired, "precondition: the fault never fired"

    units = world.orchestrator.enumerate_units(world.run_id)
    disturbed = [
        u for u in units
        if getattr(u, "state", None) in ("pending", "quarantined")
        and getattr(u, "attempts", 0) >= 1
    ]
    assert disturbed, (
        "after a fault after the model call, no unit is pending-with-an-attempt or "
        f"quarantined: {sorted({getattr(u, 'state', None) for u in units})}. The faulted unit "
        "was marked done, or its attempt was never recorded"
    )
