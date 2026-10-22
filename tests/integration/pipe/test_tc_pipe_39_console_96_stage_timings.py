"""`TC-PIPE-39` and `TC-CONSOLE-96` (issue #826, FR-CONSOLE-75) — the stage seconds M-PIPE
records, summed across a pause and resume, and the results read's `stage_timings` built from
them; plus the job records' start and finish times.

Console clarity test plan §3.6, story T10.

| Case | Expected |
|---|---|
| PIPE-39 | an injected clock advancing 10 s in extract, 20 s in judge and 5 s in aggregate: `run_metrics` has `stage_seconds.extract = 10`, `judge = 20`, `aggregate = 5`, and no `synth` row (synthesis did not run); after pause and resume with 7 more judge seconds, `judge = 27` |
| CONSOLE-96 (timings) | over the same paused run, the results read's `stage_timings` is exactly "Reading answers" 10, "AI grading" 20, "Combining grades" 5, in run order — the absent synthesis is not listed, never as 0 |
| CONSOLE-96 (jobs) | a drafting job's record and an intake job's record each carry `started_at` and `finished_at` |

**The injected clock.** `run_to_completion(clock=...)` is the seam: its `monotonic()` times
every stage. A `FrozenClock` moves only inside a stage, from the stage's own seam — the first
extract unit, the first score unit of a pass that ran no extract units, and the first aggregate
hook call that aggregated cells — so each stage's span is exactly the seconds the test spent in
it. F-DEV-PIPE's pass layout (pass 1 extract only; pass 2 extract and score; passes 3.. score;
pass 6 the first aggregation) is a precondition the test asserts, so a layout change fails here
with its own message rather than as a wrong figure.

Rung 3: a real store, the real composed pipeline over the committed F-DEV-PIPE recordings, the
real console reads. The job arms serve a real console (the draft job over the recorded F-AUTHOR
corpus, the intake over TC-CONSOLE-77's sample physics world).

Markers. `integration`. Not written ahead: #810 is merged.
"""

from __future__ import annotations

from typing import Any

import pytest

import aeh.pipeline.driver as driver
import aeh.pipeline.executor as executor
from aeh.console import build_console
from aeh.console.screen_reads import results_screen_read
from aeh.orch import Orchestrator
from tests.support import pipe_world
from tests.support.clock import FrozenClock
from tests.support.console_redesign_world import run_draft_job, served_authoring  # noqa: F401
from tests.unit.console.test_tc_console_77_papers_upload_reads import (  # noqa: F401
    _make_class,
    _upload,
    _wait,
    console as intake_console,
)

pytestmark = pytest.mark.integration

#: The leg-1 pass cap: pass 6 is F-DEV-PIPE's first pass that aggregates cells.
LEG1_PASSES = 6


class _StageClock:
    """Advances an injected `FrozenClock` once per stage per leg, from inside the stage."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.clock = FrozenClock()
        self.budget: dict[str, float] = {}
        #: Aggregate-hook calls so far: the hook runs once at the end of every pass.
        self.passes = 0
        #: The stages whose units ran in the current pass.
        self.pass_stages: set[str] = set()
        self.layout: list[set[str]] = []
        real_execute = executor.ProductionStageExecutor._execute
        real_hook = driver._aggregate_hook
        owner = self

        def _execute(self: Any, unit: Any, governed: Any) -> Any:
            stage = str(unit.stage)
            owner.pass_stages.add(stage)
            if stage == "extract":
                owner._spend("extract")
            elif stage == "score" and "extract" not in owner.pass_stages:
                # Only in a pass that runs no extract unit: extract's span that pass would
                # otherwise absorb the judge seconds.
                owner._spend("judge")
            return real_execute(self, unit, governed)

        def _hook(*args: Any, **kwargs: Any) -> Any:
            trace = real_hook(*args, **kwargs)
            if trace.units:
                owner._spend("aggregate")
            owner.passes += 1
            owner.layout.append(owner.pass_stages)
            owner.pass_stages = set()
            return trace

        monkeypatch.setattr(executor.ProductionStageExecutor, "_execute", _execute)
        monkeypatch.setattr(driver, "_aggregate_hook", _hook)

    def _spend(self, stage: str) -> None:
        seconds = self.budget.pop(stage, 0.0)
        if seconds:
            self.clock.advance(seconds)

    def leg(self, **budget: float) -> None:
        self.budget = dict(budget)


def _stage_seconds(store: Any, run_id: str) -> dict[str, float]:
    rows = store.durable().query(
        "SELECT metric, value FROM run_metrics WHERE run_id = :r AND metric LIKE "
        "'stage_seconds.%' AND submission_id = '' AND criterion_id = '' AND judge_id = ''",
        r=run_id)
    return {str(row["metric"]): float(row["value"]) for row in rows}


def _leg_one(tmp_path, monkeypatch) -> tuple[Any, _StageClock]:
    """Drive F-DEV-PIPE for six passes with 10 / 20 / 5 seconds spent, then pause it."""
    monkeypatch.delenv("HARNESS_PROFILE", raising=False)
    timer = _StageClock(monkeypatch)
    world = pipe_world.replay_world(tmp_path / "w", monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    timer.leg(extract=10.0, judge=20.0, aggregate=5.0)
    result = pipe_world.drive_composed(world, clock=timer.clock, max_passes=LEG1_PASSES)
    # Preconditions: the run is mid-flight, and every budget was spent in its stage.
    assert result.status == "running", f"leg 1 did not stop mid-run: {result.status}"
    assert timer.budget == {}, (
        f"F-DEV-PIPE's pass layout changed, a stage budget went unspent: {timer.budget} "
        f"(passes: {timer.layout})")
    assert timer.layout[0] == {"extract"}, timer.layout
    Orchestrator(world.store).pause(world.run_id, "TC-PIPE-39: paused between legs")
    return world, timer


def test_tc_pipe_39_stage_seconds_are_recorded_and_summed_across_a_resume(
        tmp_path, monkeypatch) -> None:
    world, timer = _leg_one(tmp_path, monkeypatch)
    try:
        assert _stage_seconds(world.store, world.run_id) == {
            "stage_seconds.extract": 10.0,
            "stage_seconds.judge": 20.0,
            "stage_seconds.aggregate": 5.0,
        }, "leg 1: the stage seconds are not the clock's, or synthesis wrote a row it never ran"

        orch = Orchestrator(world.store)
        orch.resume(world.run_id)
        timer.leg(judge=7.0)
        result = pipe_world.drive_composed(world, clock=timer.clock)
        assert result.status == "complete", result.status
        assert timer.budget == {}, f"the resumed leg spent no judge seconds: {timer.layout}"
        seconds = _stage_seconds(world.store, world.run_id)
        assert seconds["stage_seconds.judge"] == 27.0, seconds
        assert seconds["stage_seconds.extract"] == 10.0, seconds
        assert seconds["stage_seconds.aggregate"] == 5.0, seconds
    finally:
        world.store.close()


def test_tc_console_96_results_read_lists_the_timed_stages_in_run_order(
        tmp_path, monkeypatch) -> None:
    world, _timer = _leg_one(tmp_path, monkeypatch)
    try:
        doc = results_screen_read(None, build_console(store=world.store),
                                  {"run_id": world.run_id})
        timings = doc["stage_timings"]
        # The read swallows an unreadable table as no timings: an empty list proves nothing.
        assert timings, "the results read carries no stage timings at all"
        assert [(t["label"], t["seconds"]) for t in timings] == [
            ("Reading answers", 10.0), ("AI grading", 20.0), ("Combining grades", 5.0)]
        assert [t["stage"] for t in timings] == ["extract", "judge", "aggregate"]
        assert all(t["stage"] != "synth" and t["label"] != "Writing feedback"
                   for t in timings), "a stage that did not run is listed"
    finally:
        world.store.close()


def test_tc_console_96_a_drafting_job_records_its_start_and_finish(served_authoring) -> None:  # noqa: F811
    _server, port, _store, _data_dir = served_authoring
    _answer, record = run_draft_job(port, "AF-02")
    assert record["state"] == "succeeded", record
    assert record["started_at"], record
    assert record["finished_at"], record
    assert str(record["finished_at"]) >= str(record["started_at"]), record


def test_tc_console_96_an_intake_job_records_its_start_and_finish(intake_console) -> None:  # noqa: F811
    port = intake_console["port"]
    _make_class(port, intake_console["roster"])
    status, answer = _upload(port, intake_console["paper"], cohort_id="ps9-class",
                             package_version=intake_console["version"], kind="assessment",
                             filename="01-test-paper.pdf")
    assert status == 200 and answer["dispatched"] is True, answer
    record = _wait(port, answer["job_id"])
    assert record["kind"] == "paper_intake", record
    assert record["state"] == "succeeded", record
    assert record["started_at"], record
    assert record["finished_at"], record
    assert str(record["finished_at"]) >= str(record["started_at"]), record
