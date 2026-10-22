"""The Jev-final pipeline world (#819): F-DEV-PIPE driven through `run_to_completion` with the
decision engine on or off, FR-AGG-20's knob set, and every escalation observed per cell.

`PipeWorld` in **capture** mode. F-JEV-DECISIONS was recorded with the knob off, so it holds no
confirming-judge call (FR-JUDGE-39), and a strict replay would miss. `CaptureProvider` replays
what the fixture directory holds and otherwise records the reply the corpus declares for the
cell (`DECISION_OUTCOMES`-style outcomes for `decide`, the panel ordinal for `complete`), then
replays it. Every model answer is therefore a recording keyed on the exact request, and nothing
is invented beyond the corpus's own declarations plus the per-test `outcomes` and
`band_overrides` stated here.

Observation is read-only: `should_escalate` and `Orchestrator.enqueue_escalation` are wrapped
to record their answers and pass them through unchanged.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from tests.support.pipe_world import PipeWorld, drive_composed

#: A judged cell, keyed by the corpus submission id (`S1`..`S3`) and the criterion.
Cell = tuple[str, str]

BELOW_GATE = {"kind": "below_gate", "gate": 0.62, "cite": {}}
ACCEPTED = {"kind": "accepted", "gate": 0.95, "cite": {}}
JUDGED = ("C1", "C2")
CORPUS_IDS = ("S1", "S2", "S3")


def every_cell(outcome: dict[str, Any]) -> dict[Cell, dict[str, Any]]:
    return {(sid, cid): dict(outcome) for sid in CORPUS_IDS for cid in JUDGED}


class JevFinalPipeWorld(PipeWorld):
    """`PipeWorld` with the knob, the base panel size and the judges' bands under test control.

    - `knob`: `HARNESS_JEV_FINAL_ON_ACCEPT` as the run resolves it.
    - `agreeing`: every arm answers the cell's reference band (the reference world's shape), so
      a seat judge confirms a decision placed on that band. Off: F-DEV-PIPE's own disagreeing
      panel (`PANEL_ORDINALS`, `ESCALATION_ORDINALS`).
    - `band_overrides`: `{(corpus id, criterion, judge build id): band}` for single arms.
    - With a base panel of one, the ladder's two extension arms are `escalation-arm-2/3` (the
      next arms after the panel), so those are the world's escalation judges.
    """

    def __init__(self, data_dir: Any, fixture_dir: Any, *, engine: bool, panel_size: int,
                 knob: bool = True, outcomes: dict[Cell, dict[str, Any]] | None = None,
                 agreeing: bool = False, band_overrides: dict[tuple[str, str, str], str] | None = None,
                 monkeypatch: Any = None) -> None:
        self.jev_final_on_accept = knob
        self.agreeing = agreeing
        self.band_overrides = dict(band_overrides or {})
        super().__init__(data_dir, fixture_dir, decision_engine=engine, panel_size=panel_size,
                         monkeypatch=monkeypatch)
        if outcomes is not None:
            self.decision_outcomes = outcomes
        if panel_size == 1:
            self.escalation_refs = {arm: self._judge_ref(arm)
                                    for arm in ("escalation-arm-2", "escalation-arm-3")}

    def corpus_id(self, sid: str) -> str:
        return self.cohort[self.index_by_sid[sid] - 1].submission_id

    def _judge_band(self, sid: str, cid: str, judge: str | None = None) -> str:
        override = self.band_overrides.get((self.corpus_id(sid), cid, str(judge)))
        if override is not None:
            return override
        if self.agreeing:
            return self.cohort[self.index_by_sid[sid] - 1].bands[cid]
        return super()._judge_band(sid, cid, judge)

    def escalation_judge_refs(self) -> dict[str, Any]:
        from tests.support.pipe_world import _corpus_ref

        return {arm: _corpus_ref("judge", arm) for arm in self.escalation_refs}


def new_world(root: Path, **kwargs: Any) -> JevFinalPipeWorld:
    for sub in ("packages", "cohorts", "blobs"):
        (root / "data" / sub).mkdir(parents=True, exist_ok=True)
    (root / "recordings").mkdir(parents=True, exist_ok=True)
    return JevFinalPipeWorld(root / "data", root / "recordings", **kwargs)


@dataclass
class Observed:
    """What the aggregate hook asked and M-ORCH answered, per cell, in call order."""

    should_escalate: dict[Cell, list[tuple[bool, tuple[str, ...]]]] = field(default_factory=dict)
    enqueued: dict[Cell, list[tuple[Any, ...]]] = field(default_factory=dict)


def drive(world: JevFinalPipeWorld, *,
          enqueue_filter: Callable[[Any, Any, tuple[str, ...]], bool] | None = None,
          **overrides: Any) -> tuple[Any, Observed]:
    """Build, start and drive the run to its end. `enqueue_filter(orch, tx, key)` returning False
    makes `enqueue_escalation` enqueue nothing for that cell (the mutation arms only)."""
    import aeh.pipeline.hooks as hooks
    from aeh.orch import Orchestrator

    observed = Observed()
    by_store_id = {s: world.corpus_id(s) for s in world.index_by_sid}
    real_should, real_enqueue = hooks.should_escalate, Orchestrator.enqueue_escalation

    def should_escalate(**kwargs: Any) -> Any:
        decision = real_should(**kwargs)
        # The hook's loop variable names the cell; the score itself carries no submission id.
        cell = sys._getframe(1).f_locals["cell"]
        key = (by_store_id[cell.submission_id], cell.criterion_id)
        observed.should_escalate.setdefault(key, []).append(
            (bool(decision.escalate), tuple(decision.reasons)))
        return decision

    def enqueue_escalation(self: Any, tx: Any, key: Any, judges: Any = None, **kwargs: Any) -> Any:
        key = tuple(str(k) for k in key)
        if enqueue_filter is not None and not enqueue_filter(self, tx, key):
            return ()
        reports = real_enqueue(self, tx, key, judges, **kwargs)
        cell = (by_store_id[key[1]], key[2])
        for report in reports:
            observed.enqueued.setdefault(cell, []).append(
                (report.decision, tuple(report.added_judges), report.judge_count,
                 report.units_inserted, round(float(report.escalation_rate), 9),
                 float(report.escalation_budget)))
        return reports

    hooks.should_escalate = should_escalate
    Orchestrator.enqueue_escalation = enqueue_escalation
    try:
        world.build_run()
        world.start_run()
        overrides.setdefault("judge_refs", world.escalation_judge_refs())
        result = drive_composed(world, **overrides)
    finally:
        hooks.should_escalate = real_should
        Orchestrator.enqueue_escalation = real_enqueue
    return result, observed


def cells(world: JevFinalPipeWorld) -> dict[Cell, dict[str, Any]]:
    """Per judged cell: its score units, verdict depth, stored score and pre-screen row."""
    from aeh.agg import stored_not_final_reason

    handle = world.handle
    out: dict[Cell, dict[str, Any]] = {}
    for row in handle.query(
            "SELECT * FROM criterion_score WHERE run_id = :r AND criterion_id IN ('C1', 'C2')",
            r=world.run_id):
        out[(world.corpus_id(str(row["submission_id"])), str(row["criterion_id"]))] = {
            "score": (row["band"], row["points"], row["state"], row["routing"],
                      row["judge_count"], round(float(row["confidence"]), 9),
                      stored_not_final_reason(row)),
            "units": [], "depth": 0, "prescreen": None, "engines": [], "ordinals": [],
            "judges": []}
    for row in handle.query(
            "SELECT submission_id, criterion_id, judge_id, origin, status FROM work_unit "
            "WHERE run_id = :r AND stage = 'score' ORDER BY judge_id", r=world.run_id):
        key = (world.corpus_id(str(row["submission_id"])), str(row["criterion_id"]))
        out[key]["units"].append((row["judge_id"], row["origin"], row["status"]))
    for row in handle.query(
            "SELECT w.submission_id, w.criterion_id, w.judge_id, v.scoring_engine, v.band_ordinal "
            "FROM verdict v "
            "JOIN work_unit w ON w.work_id = v.work_id WHERE w.run_id = :r ORDER BY w.judge_id",
            r=world.run_id):
        key = (world.corpus_id(str(row["submission_id"])), str(row["criterion_id"]))
        out[key]["depth"] += 1
        out[key]["engines"].append(row["scoring_engine"])
        out[key]["ordinals"].append(int(row["band_ordinal"]))
        out[key]["judges"].append(row["judge_id"])
    for row in handle.query(
            "SELECT submission_id, criterion_id, outcome, reason, gate_confidence "
            "FROM decision_prescreen WHERE run_id = :r", r=world.run_id):
        key = (world.corpus_id(str(row["submission_id"])), str(row["criterion_id"]))
        out[key]["prescreen"] = (row["outcome"], row["reason"], row["gate_confidence"])
    return out


def forge_citation_on(world: JevFinalPipeWorld, cell: Cell) -> Callable[[], None]:
    """Make the decision seat's citation check refuse `cell` (an above-gate answer whose cited
    bytes are not the document's). Only the pre-screen's call is refused: the LLM verdicts'
    own citation checks run untouched. Returns the undo."""
    import aeh.judge.worker as worker
    from aeh.prov import MalformedResponseError

    real = worker._refuse_unverified_citations
    corpus_id, criterion_id = cell
    submission_id = next(s for s, c in ((s, world.corpus_id(s)) for s in world.index_by_sid)
                         if c == corpus_id)

    def refuse(cited: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        if (sys._getframe(1).f_code.co_name == "_prescreen"
                and request.criterion.criterion_id == criterion_id
                and getattr(request.submission, "submission_id", None) == submission_id):
            raise MalformedResponseError("forged citation: the cited bytes are not the document's")
        return real(cited, request, *args, **kwargs)

    worker._refuse_unverified_citations = refuse

    def undo() -> None:
        worker._refuse_unverified_citations = real

    return undo


__all__ = ["ACCEPTED", "BELOW_GATE", "Cell", "JevFinalPipeWorld", "Observed", "cells", "drive",
           "every_cell", "forge_citation_on", "new_world"]
