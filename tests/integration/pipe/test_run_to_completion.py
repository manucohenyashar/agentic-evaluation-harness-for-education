"""`TS-83` (issue #377) — `TC-PIPE-01` and `TC-PIPE-13`: `run_to_completion` drives a run to
`complete` and reports every stage, and a composition fault pauses rather than lying
(`FR-PIPE-01`, gap-fix test plan §5 / §6).

| Case | Expected |
|---|---|
| `TC-PIPE-01` | `RunResult.status == "complete"` and equals the stored `run.status`; `pause_reason is None`; `stages` holds exactly one entry per stage executed, in order of first execution: `extract`, `integrity_pre`, `deterministic`, `score`, `aggregate`, `synthesize`, `grade`; every `detail` non-empty; `grades_computed = 3` |
| `TC-PIPE-13` | A hook raising `KeyError('C9')` from `verdicts_for` leaves the run `paused` with `pause_reason == "composition fault: KeyError: 'C9'"`; the `aggregate` stage `detail` names the cell; `run_to_completion` **returns** rather than raising; the exception is never swallowed into a `complete` status |

**Why these two share a file.** Both are `FR-PIPE-01` — the same requirement's success and
failure arms. The plan names `tests/integration/pipe/test_run_to_completion.py` for `TC-PIPE-01`
and no path for `TC-PIPE-13`; keeping the pair together is what makes the second one's oracle
legible, because "never swallowed into a `complete` status" is only meaningful next to the case
that pins what `complete` looks like.

**OBS-14**, the plan's observability row for exactly these two cases: every `detail` tuple is
non-empty and no element equals `"ok"`, `"success"`, `"done"` or `""`. A bare status on top of a
stage that did nothing is the top silent-failure trap (CLAUDE.md seam 4), so it is asserted here
rather than assumed.

**The world, and what does not transfer:** see this directory's `conftest.py`. F-DEV-PIPE does
not exist; counts are derived from the run's own ledger. `grades_computed = 3` *does* transfer —
it counts submissions, and this world has three.

**Written ahead of implementation: yes** — `aeh.pipeline` is #364's. Every body probes it first.
"""

from __future__ import annotations

import pytest

from tests.support.impl import PIPE_MODULE, require
from tests.integration.pipe.conftest import PIPE_SUBMISSIONS, extract_units

pytestmark = pytest.mark.integration

ISSUE = "#364"

#: The stage trace `FR-PIPE-01` specifies, in order of first execution.
EXPECTED_STAGE_ORDER = (
    "extract", "integrity_pre", "deterministic", "score", "aggregate", "synthesize", "grade",
)

#: Details that say nothing. OBS-14 names these four exactly.
EMPTY_DETAILS = ("ok", "success", "done", "")


def _stored_run(world):
    """The run's own row — the thing `RunResult.status` must equal rather than narrate past.

    Read through `M-ORCH`'s declared statement, not a string assembled here: `CT-PIPE-05` says
    `M-PIPE` executes no SQL, and a test that hand-wrote one would be modelling a shape the
    design forbids.
    """
    from aeh.orch import ORCH_STATEMENTS

    rows = world.handle.query(ORCH_STATEMENTS["select_run"], run_id=world.run_id)
    assert rows, f"the run row for {world.run_id!r} vanished"
    return dict(rows[0])


# --- TC-PIPE-01 ----------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_pipe_01_run_to_completion_drives_the_run_to_complete(make_pipe_world):
    """`TC-PIPE-01` — the composed run reaches `complete`, and the result agrees with the
    store rather than reporting its own opinion of what happened."""
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()

    result = run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    stored = _stored_run(world)
    assert result.status == "complete", (
        f"the composed run ended {result.status!r}; FR-PIPE-01 drives until M-ORCH's completion "
        f"predicate holds or the run is paused. pause_reason={result.pause_reason!r}"
    )
    assert result.status == stored["status"], (
        f"RunResult.status is {result.status!r} but the stored run row says "
        f"{stored['status']!r} — the result must equal the store, not narrate past it"
    )
    assert result.pause_reason is None, (
        f"a complete run carries a pause reason: {result.pause_reason!r}"
    )
    assert result.grades_computed == PIPE_SUBMISSIONS, (
        f"{result.grades_computed} grades computed for {PIPE_SUBMISSIONS} submissions"
    )


@pytest.mark.writtenahead
def test_tc_pipe_01_the_trace_holds_one_entry_per_stage_in_execution_order(make_pipe_world):
    """`TC-PIPE-01` — exactly one entry per stage executed, in order of first execution.

    Both halves bite: a driver that traced a stage twice, and one that ran the stages in a
    different order (scoring before the integrity gate, say), each fail here while every
    status assertion above still passes.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()

    result = run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    names = [entry.stage for entry in result.stages]
    assert names == list(EXPECTED_STAGE_ORDER), (
        f"the stage trace reads {names}; FR-PIPE-01 specifies exactly one entry per stage "
        f"executed, in order of first execution: {list(EXPECTED_STAGE_ORDER)}"
    )


@pytest.mark.writtenahead
def test_tc_pipe_01_the_extract_entry_agrees_with_the_ledger(make_pipe_world):
    """`TC-PIPE-01` — `units`, `done` and `quarantined` for the `extract` stage.

    The plan's figures are F-DEV-PIPE's (`units = 6`). This world is wider, so the numbers come
    off the ledger: every enumerated extract unit is done, none quarantined, and the trace
    reports those same figures. A driver that marked units done without doing the work, or a
    trace that reported a count it did not measure, fails this.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()
    expected_units = len(extract_units(world))
    assert expected_units > 0, "precondition: the run enumerated no extract units"

    result = run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    entry = next(e for e in result.stages if e.stage == "extract")
    assert (entry.units, entry.done, entry.quarantined) == (expected_units, expected_units, 0), (
        f"the extract entry reports units={entry.units}, done={entry.done}, "
        f"quarantined={entry.quarantined}; the ledger enumerated {expected_units} units and "
        "none of this world's submissions quarantine"
    )


@pytest.mark.writtenahead
def test_tc_pipe_01_obs_14_no_stage_detail_is_a_bare_status(make_pipe_world):
    """`OBS-14` — every `detail` is non-empty and none of them is a bare status word.

    Seam 4: `status=success` sitting on top of an empty result is the top silent-failure trap,
    so the trace says what each stage *did*, not merely that it ran.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()

    result = run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    offenders = {
        entry.stage: entry.detail
        for entry in result.stages
        if not entry.detail
        or any(str(item).strip().lower() in EMPTY_DETAILS for item in entry.detail)
    }
    assert offenders == {}, (
        f"these stages reported a bare status instead of what they did: {offenders}. OBS-14: "
        f"no detail element may be one of {EMPTY_DETAILS} and none may be empty"
    )


# --- TC-PIPE-01 variants -------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_pipe_01_an_unknown_run_id_raises_before_any_write(make_pipe_world):
    """Variant — a run id that does not exist raises before any write.

    The world is built so the store is real and its row counts are meaningful; the id handed to
    the driver is one nothing created.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()
    before = _stored_run(world)

    with pytest.raises(Exception):
        run_to_completion(
            world.store, "run-does-not-exist",
            provider=world.provider, run_config=world.resolved,
        )

    assert _stored_run(world) == before, (
        "driving an unknown run id changed the real run's row — the refusal must land before "
        "anything is written"
    )


@pytest.mark.writtenahead
def test_tc_pipe_01_a_paused_run_returns_paused_and_writes_nothing(make_pipe_world):
    """Variant — a run already paused by operator request returns `status="paused"` and nothing
    is written. The oracle is the run row, unchanged across the call."""
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()
    world.orchestrator.pause(world.run_id, cause="operator request")
    before = _stored_run(world)

    result = run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    assert result.status == "paused", (
        f"a run paused by the operator was driven anyway and ended {result.status!r}"
    )
    assert _stored_run(world) == before, (
        "driving a paused run changed its row; a paused run is not resumed by being driven"
    )


@pytest.mark.writtenahead
def test_tc_pipe_01_max_passes_one_stops_after_one_pass(make_pipe_world):
    """Variant — `max_passes=1` returns the stored non-terminal status, and the trace covers
    only that pass, so there is no `grade` entry."""
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()

    result = run_to_completion(
        world.store, world.run_id, provider=world.provider,
        run_config=world.resolved, max_passes=1,
    )

    assert result.status == _stored_run(world)["status"]
    assert result.status != "complete", (
        "one pass completed the whole run, so the bound asserted nothing"
    )
    assert [e.stage for e in result.stages].count("grade") == 0, (
        f"the single-pass trace carries a grade entry: {[e.stage for e in result.stages]}. "
        "Grading happens on completion (FR-PIPE-06), which one pass did not reach"
    )


# --- TC-PIPE-13 ----------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_pipe_13_a_composition_fault_pauses_the_run_and_names_itself(make_pipe_world,
                                                                        monkeypatch):
    """`TC-PIPE-13` — a hook raising `KeyError('C9')` from `verdicts_for` pauses the run with an
    exact reason, and `run_to_completion` returns rather than raising.

    The fault is injected at the **module boundary the composer calls**, not inside the
    composer: `FR-PIPE-04` step 2 reads the cell's verdicts through `judge.verdicts_for`, so
    patching that is patching a stage door, which is what a composition fault actually is.

    Three things are asserted and each catches a different wrong implementation: a driver that
    let the exception escape (the `raises` that is absent), one that swallowed it and reported
    `complete` (the status), and one that paused with a reason nobody can act on (the string).
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    import aeh.judge

    def _faulting_verdicts_for(*args, **kwargs):
        raise KeyError("C9")

    monkeypatch.setattr(aeh.judge, "verdicts_for", _faulting_verdicts_for)
    world = make_pipe_world()

    result = run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    stored = _stored_run(world)
    assert result.status == "paused", (
        f"a composition fault left the run {result.status!r}. It must pause — and it must never "
        "be swallowed into a complete status, which is the failure this case exists for"
    )
    assert stored["status"] == "paused", (
        f"the result says paused but the stored run row says {stored['status']!r}"
    )
    assert result.pause_reason == "composition fault: KeyError: 'C9'", (
        f"pause_reason is {result.pause_reason!r}; FR-PIPE-01 pins "
        '"composition fault: KeyError: \'C9\'" so an operator reads the cause, not a category'
    )
    assert stored["pause_reason"] == result.pause_reason


@pytest.mark.writtenahead
def test_tc_pipe_13_the_aggregate_stage_detail_names_the_cell(make_pipe_world, monkeypatch):
    """`TC-PIPE-13` — the `aggregate` entry's `detail` names the cell the fault happened on.

    A pause reason says *what* broke; the trace says *where*. Without this a run pauses with a
    KeyError and an operator has no cell to look at (seam 4).
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    import aeh.judge

    monkeypatch.setattr(
        aeh.judge, "verdicts_for",
        lambda *a, **k: (_ for _ in ()).throw(KeyError("C9")),
    )
    world = make_pipe_world()
    first_submission = world.admitted_ids()[0]

    result = run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    entry = next((e for e in result.stages if e.stage == "aggregate"), None)
    assert entry is not None, (
        f"the run paused inside aggregation but the trace has no aggregate entry: "
        f"{[e.stage for e in result.stages]}"
    )
    rendered = " ".join(str(item) for item in entry.detail)
    assert first_submission in rendered or any(
        cid in rendered for cid in world.open_ids
    ), (
        f"the aggregate detail names no cell: {entry.detail!r}. It must identify the cell the "
        "composition fault happened on"
    )
