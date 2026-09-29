"""FUZZ-08 (FR-ORCH-29, FR-PIPE-04, FR-INTEG-10, CT-INTEG-16; TS-99 #393): the composition hooks
keep their invariants under any interleaving of passes, spurious verifies and recoveries.

A Hypothesis state machine over one real F-DEV-PIPE run (3 submissions × 2 judged criteria plus an
MCQ; the plan's 2 × 2 is the smallest shape, this corpus is the one with recordings). Rules:
- **pass**: one `run_to_completion(..., max_passes=1)` pass — units become terminal, hooks run,
  escalations add score units, exactly as production does it;
- **spurious verify**: the real `IntegrityGate.verify` on a random scored cell, outside any hook;
- **recover**: `recover(store)`;
- **quarantine**: once per example, S1's C1 base-panel unit of one judge is struck until M-ORCH
  quarantines it (the plan's "a unit becomes terminal ... quarantined"). S1's C1 cell is unanimous
  and never escalated, so the quarantine takes FR-PIPE-05's two-verdict fallback, which needs no
  recording the corpus lacks.
Invariants after every step:
1. no cell's `aggregated.units_consumed` exceeds its terminal score units;
2. `criterion_score` has at most one row per cell;
3. escalation units per cell are at most 2 per escalation request;
4. a spurious verify changes no extract unit's `attempts`.
At teardown, driven to completion: every cell whose score units are all terminal has
`aggregated.units_consumed` equal to that count.

Disclosed: invariant 4 can only bite where a spurious verify has something to bump — an
insufficient cell's pending unit. F-DEV-PIPE has no insufficiency, so here the invariant is a
guard against a verify that writes at all; the bump-on-insufficiency path is TC-INTEG-C16's.

Each example builds a fresh world (about a second), so the case is marked `slow` in addition to
`property`: the default profile's 50 examples run in the property tier, not the fast gate.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

import aeh.pipeline as pipeline
from aeh.integ import IntegrityGate, StoreExtractionView
from aeh.orch import Orchestrator
from aeh.pkg import PackageCatalog
from tests.support import pipe_world

pytestmark = [pytest.mark.property, pytest.mark.slow]


class CompositionMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name) / "w"
        self._mp = pytest.MonkeyPatch()
        self.world = pipe_world.replay_world(self.root, monkeypatch=self._mp)
        self.world.build_run()
        self.world.start_run()

    def _rows(self, sql, *params):
        with sqlite3.connect(self.root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite") as c:
            c.row_factory = sqlite3.Row
            return c.execute(sql, params).fetchall()

    def _drive(self, max_passes):
        return pipeline.run_to_completion(
            self.world.store, self.world.run_id, provider=self.world.provider,
            run_config=self.world.resolved, max_passes=max_passes, **pipe_world.corpus_refs())

    @rule()
    def one_pass(self):
        self._drive(1)

    @rule(pick=st.integers(min_value=0, max_value=10))
    def spurious_verify(self, pick):
        cells = self._rows("SELECT DISTINCT submission_id, criterion_id FROM work_unit WHERE "
                           "run_id = ? AND stage = 'extract' AND status IN ('done', 'quarantined')",
                           self.world.run_id)
        if not cells:
            return
        cell = cells[pick % len(cells)]
        before = self._attempts()
        handle = Orchestrator(self.world.store).run_handle(self.world.run_id)
        catalog = PackageCatalog(self.world.store.package(handle.package_id),
                                 package_id=handle.package_id)
        gate = IntegrityGate(handle.cohort, self.world.store.blobs(), StoreExtractionView(
            handle.cohort, catalog, handle.package_version_id, self.world.run_id))
        gate.verify(self.world.run_id, cell["submission_id"], cell["criterion_id"])
        assert self._attempts() == before, (
            f"a spurious verify of {tuple(cell)} changed extract attempts (CT-INTEG-16)")

    @rule()
    def quarantine(self):
        if getattr(self, "_quarantined", False):
            return
        target = self._rows(
            "SELECT w.work_id FROM work_unit w JOIN document d ON d.submission_id = w.submission_id "
            "JOIN document_region r ON r.document_id = d.document_id WHERE w.run_id = ? "
            "AND w.stage = 'score' AND w.criterion_id = 'C1' AND w.origin != 'escalation' "
            "AND w.status = 'pending' AND r.content LIKE '%I did not get to th%' LIMIT 1",
            self.world.run_id)
        if not target:
            return
        orch = Orchestrator(self.world.store)
        for _ in range(10):
            orch.fail(target[0]["work_id"], "fuzz: struck")
            if orch.unit_status(target[0]["work_id"]) == "quarantined":
                break
        self._quarantined = orch.unit_status(target[0]["work_id"]) == "quarantined"

    @rule()
    def recover(self):
        pipeline.recover(self.world.store)

    def _attempts(self):
        return sorted(tuple(r) for r in self._rows(
            "SELECT work_id, attempts FROM work_unit WHERE run_id = ? AND stage = 'extract'",
            self.world.run_id))

    @invariant()
    def consumed_never_exceeds_terminal(self):
        for row in self._rows(
                "SELECT p.submission_id, p.criterion_id, p.units_consumed, "
                "(SELECT COUNT(*) FROM work_unit w WHERE w.run_id = p.run_id AND w.stage = 'score' "
                " AND w.submission_id = p.submission_id AND w.criterion_id = p.criterion_id "
                " AND w.status IN ('done', 'quarantined')) AS terminal "
                "FROM cell_phase p WHERE p.run_id = ? AND p.phase = 'aggregated'", self.world.run_id):
            assert row["units_consumed"] <= row["terminal"], dict(row)

    @invariant()
    def at_most_one_score_per_cell(self):
        assert self._rows("SELECT submission_id, criterion_id FROM criterion_score WHERE run_id = ? "
                          "GROUP BY 1, 2 HAVING COUNT(*) > 1", self.world.run_id) == []

    @invariant()
    def escalation_units_are_bounded(self):
        for row in self._rows(
                "SELECT w.submission_id, w.criterion_id, COUNT(*) AS n, "
                "(SELECT COUNT(*) FROM escalation_request q WHERE q.run_id = w.run_id AND "
                " q.submission_id = w.submission_id AND q.criterion_id = w.criterion_id) AS requests "
                "FROM work_unit w WHERE w.run_id = ? AND w.origin = 'escalation' GROUP BY 1, 2",
                self.world.run_id):
            assert row["n"] <= 2 * max(1, row["requests"]), dict(row)

    def teardown(self):
        try:
            result = self._drive(None)
            assert result.status == "complete", (result.status, result.pause_reason)
            for row in self._rows(
                    "SELECT w.submission_id, w.criterion_id, COUNT(*) AS terminal, "
                    "(SELECT units_consumed FROM cell_phase p WHERE p.run_id = w.run_id AND "
                    " p.submission_id = w.submission_id AND p.criterion_id = w.criterion_id AND "
                    " p.phase = 'aggregated') AS consumed "
                    "FROM work_unit w WHERE w.run_id = ? AND w.stage = 'score' GROUP BY 1, 2",
                    self.world.run_id):
                assert row["consumed"] == row["terminal"], dict(row)
        finally:
            self.world.store.close()
            self._mp.undo()
            self._tmp.cleanup()


CompositionMachine.TestCase.settings = settings(deadline=None, stateful_step_count=8,
                                                max_examples=settings().max_examples)
test_fuzz_08_composition_state_machine = CompositionMachine.TestCase
