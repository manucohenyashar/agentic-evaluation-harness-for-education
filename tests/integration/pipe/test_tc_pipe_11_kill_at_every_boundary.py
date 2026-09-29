"""TC-PIPE-11 (NFR-PIPE-01; TS-83 #377, TS-84 #378): a run killed at any hook boundary recovers to
the uninterrupted run's result.

For each boundary *k* a `SystemExit` is raised once at *k* (a `BaseException`, so nothing in the
composition layer catches it, the way a kill is not caught). The store is closed, and a FRESH
`Store` runs `recover` then `run_to_completion`. The projected tables must equal an uninterrupted
run's, with no duplicate escalation units.

| Boundary | Where the exit is raised |
|---|---|
| extract | after the first extraction worker returns |
| integrity_pre | after the first `integrity_pre` pass committed its phases |
| score-written | after `write_score`, before the phase commits (inside the transaction) |
| phase-committed | after the first aggregate pass committed |
| escalation | after `enqueue_escalation`, inside the transaction |
| synthesis | after the first submission's synthesis |
| grading | on the second submission's grade computation (one of three done) |

Projection (the plan's §4.3 tables, by content, since the pinned mint gives both worlds the same
submission ids): `criterion_score` (band, points, judge_count, state), current `submission_grade`
(grade, total, state), the narratives' (submission, level, question) set, and escalation units per
cell. Leases held at the kill are expired with `HARNESS_ORCH_LEASE_SECONDS=1` and a 1.2 s wait,
so `recover` reclaims them as it would after a real kill.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

import aeh.pipeline as pipeline
from aeh.grade import GradingService
from aeh.orch import LEASE_SECONDS_ENV, Orchestrator
from aeh.store import open_store
from aeh.synth import SynthesisWorker
from tests.support import pipe_world

pytestmark = pytest.mark.integration


def _projection(root: Path, run_id: str) -> dict:
    with sqlite3.connect(root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite") as c:
        return {
            "scores": sorted(c.execute(
                "SELECT submission_id, criterion_id, band, points, judge_count, state FROM criterion_score "
                "WHERE run_id = ?", (run_id,)).fetchall()),
            "grades": sorted(c.execute(
                "SELECT submission_id, grade, total, state FROM submission_grade WHERE run_id = ? "
                "AND is_current = 1", (run_id,)).fetchall()),
            "narratives": sorted(c.execute(
                "SELECT DISTINCT submission_id, level, question_id FROM narrative").fetchall()),
            "escalations": sorted(c.execute(
                "SELECT submission_id, criterion_id, COUNT(*) FROM work_unit WHERE run_id = ? "
                "AND origin = 'escalation' GROUP BY 1, 2", (run_id,)).fetchall()),
        }


def _once(monkeypatch, owner, name, *, after=True, when=lambda n, result: True):
    """Raise SystemExit once at `owner.name`: after it returns (or on the call)."""
    real = getattr(owner, name)
    state = {"n": 0, "fired": False}

    def wrapped(*args, **kwargs):
        state["n"] += 1
        if not after and not state["fired"] and when(state["n"], None):
            state["fired"] = True
            raise SystemExit(f"killed at {name}")
        result = real(*args, **kwargs)
        if after and not state["fired"] and when(state["n"], result):
            state["fired"] = True
            raise SystemExit(f"killed after {name}")
        return result

    monkeypatch.setattr(owner, name, wrapped)
    return state


BOUNDARIES = {
    "extract": lambda m: _once(m, pipeline.ExtractionWorker, "process"),
    "integrity_pre": lambda m: _once(m, pipeline, "_integrity_pre_hook",
                                     when=lambda n, r: bool(r and r.units)),
    "score-written": lambda m: _once(m, pipeline, "write_score"),
    "phase-committed": lambda m: _once(m, pipeline, "_aggregate_hook",
                                       when=lambda n, r: bool(r and r.units)),
    "escalation": lambda m: _once(m, Orchestrator, "enqueue_escalation"),
    "synthesis": lambda m: _once(m, SynthesisWorker, "synthesize_submission"),
    "grading": lambda m: _once(m, GradingService, "_submission_computation", after=False,
                               when=lambda n, r: n == 2),
}


@pytest.fixture(scope="module")
def uninterrupted(tmp_path_factory):
    root = tmp_path_factory.mktemp("ts83-11-clean") / "w"
    mp = pytest.MonkeyPatch()
    try:
        world = pipe_world.replay_world(root, monkeypatch=mp)
        world.build_run()
        world.start_run()
        try:
            assert pipe_world.drive_composed(world).status == "complete"
        finally:
            world.store.close()
        return _projection(root, world.run_id)
    finally:
        mp.undo()


@pytest.mark.parametrize("boundary", list(BOUNDARIES))
def test_tc_pipe_11_a_kill_at_each_boundary_recovers_to_the_same_result(
        tmp_path, monkeypatch, uninterrupted, boundary):
    monkeypatch.setenv(LEASE_SECONDS_ENV, "1")
    root = tmp_path / "w"
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    with monkeypatch.context() as kill:
        state = BOUNDARIES[boundary](kill)
        try:
            with pytest.raises(SystemExit):
                pipe_world.drive_composed(world)
        finally:
            world.store.close()
    assert state["fired"], f"fixture: the {boundary} boundary was never reached"
    time.sleep(1.2)  # every lease held at the kill is now expired

    store = open_store(root)
    try:
        pipeline.recover(store)
        provider = pipe_world.StrictReplayProvider(pipe_world.recordings_dir())
        result = pipeline.run_to_completion(store, world.run_id, provider=provider,
                                            run_config=world.resolved, **pipe_world.corpus_refs())
    finally:
        store.close()
    assert result.status == "complete", f"{boundary}: {result.status} / {result.pause_reason}"
    assert _projection(root, world.run_id) == uninterrupted, (
        f"killed at {boundary}, the recovered run differs from the uninterrupted one (NFR-PIPE-01)")
