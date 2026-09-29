"""TC-REG-12 (#596): synthesis spend is persisted and charged against the run's frozen ceiling.

Synthesis runs after the last dispatch pass. Routing its calls through the governed provider
(TC-PIPE-C06) counts them in memory; these cases pin the two halves that make the count matter:
(a) the counters reach `run_metrics`, and (b) the measured cost is charged to the run's ceiling
spend, and synthesis stops, without blocking grading, once the ceiling is reached.
"""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from aeh.orch import Orchestrator
from tests.support import pipe_world

pytestmark = pytest.mark.integration


def _world(root: Path, monkeypatch):
    monkeypatch.setenv("HARNESS_PIPE_MAX_PASSES", "300")
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    return world


def _db(root: Path) -> Path:
    return root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite"


def test_tc_reg_12_a_synthesis_tokens_reach_run_metrics(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    seen: dict[str, int] = {"all": 0, "synthesizer": 0}
    inner = world.provider.complete

    def counted(prompt, ref, params):
        answer = inner(prompt, ref, params)
        seen["all"] += int(answer.tokens_out)
        if getattr(ref, "role", "") == "synthesizer":
            seen["synthesizer"] += int(answer.tokens_out)
        return answer

    world.provider.complete = counted
    try:
        assert pipe_world.drive_composed(world).status == "complete"
    finally:
        world.store.close()
    assert seen["synthesizer"] > 0, "fixture: synthesis returned no tokens"
    with sqlite3.connect(root / "durable.sqlite") as c:  # run_metrics is Tier D's
        stored = c.execute("SELECT value FROM run_metrics WHERE run_id = ? AND metric = 'tokens_out'",
                           (world.run_id,)).fetchone()
    assert stored is not None and float(stored[0]) == float(seen["all"]), (
        f"run_metrics tokens_out {stored} vs {seen['all']} returned, of which "
        f"{seen['synthesizer']} were synthesis")


def test_tc_reg_12_b_charge_and_ceiling_on_a_completed_run(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        assert pipe_world.drive_composed(world).status == "complete"
        orch = Orchestrator(world.store)
        with sqlite3.connect(_db(root)) as c:
            cfg = json.loads(c.execute("SELECT provider_config FROM run WHERE run_id = ?",
                                       (world.run_id,)).fetchone()[0])
        assert orch.post_dispatch_ceiling_reached(world.run_id) is None  # no ceiling frozen
        orch.charge_post_dispatch(world.run_id, Decimal("0.5"))  # no ceiling: nothing accrues
        with sqlite3.connect(_db(root)) as c:
            cfg["cost_ceiling"] = "1.0"
            c.execute("UPDATE run SET provider_config = ?, cost_spend = '0' WHERE run_id = ?",
                      (json.dumps(cfg), world.run_id))
        orch.charge_post_dispatch(world.run_id, Decimal("0.6"))
        below = orch.post_dispatch_ceiling_reached(world.run_id)
        orch.charge_post_dispatch(world.run_id, Decimal("0.4"))
        at = orch.post_dispatch_ceiling_reached(world.run_id)
    finally:
        world.store.close()
    with sqlite3.connect(_db(root)) as c:
        spend = c.execute("SELECT cost_spend FROM run WHERE run_id = ?", (world.run_id,)).fetchone()[0]
    assert Decimal(spend) == Decimal("1.0"), spend
    assert below is None, below
    assert at is not None and "cost ceiling reached" in at and "1.0" in at, at


def test_tc_reg_12_c_synthesis_stops_at_the_ceiling_and_grading_still_runs(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    charged: list[Decimal] = []
    offered: list[str] = []
    real_charge = Orchestrator.charge_post_dispatch

    def reached(self, run_id):
        return "cost ceiling reached: spend 1 of ceiling 1" if offered else None

    def charge(self, run_id, cost):
        offered.append(run_id)
        charged.append(Decimal(cost))
        return real_charge(self, run_id, cost)

    monkeypatch.setattr(Orchestrator, "post_dispatch_ceiling_reached", reached)
    monkeypatch.setattr(Orchestrator, "charge_post_dispatch", charge)
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    synth = [s for s in result.stages if s.stage == "synthesize"]
    assert len(charged) == 1, f"synthesis ran {len(charged)} submission(s) past the ceiling"
    assert synth and any("synthesis stopped before" in d for d in synth[0].detail), synth
    assert result.status == "complete" and result.grades_computed > 0, result
