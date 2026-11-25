"""`TC-AGG-35` (issue #907; CT-AGG-14 amended, CT-PKG-24, FR-AGG-22): routing volume moves only
where the delta intends.

Pairs M-STATS, M-REVIEW and M-ORCH with M-AGG. Statistical-validity test plan §3.5, story T10.
F-DEV is replayed twice, once under the old defaults (holistic multiplier frozen at 0.85, every
judged line holistic) and once under the new ones (0.95, FR-PKG-29's default scoring model).

**Oracle: differential.**

1. The only cells whose routing changes are the atomic-by-default ones and the
   unanimous-holistic ones. Unanimity is read from the stored verdicts here, not hard-coded:
   every verdict of the cell carries the same band.
2. The review queue equals the cells with `routing != auto`, in both runs. The queue is the one
   M-REVIEW builds (`open_review(...).build_queue`, a read with `record=False`), with a budget
   that shows every flagged item.
3. Escalation enqueues use the frozen thresholds. The escalation decision (`should_escalate`)
   reads no auto-accept threshold and no multiplier. So the honest form of this oracle is that
   the multiplier moves no escalation: every cell's panel size and its set of judge work units
   are identical across the two runs.

**Plan findings (asserted as preconditions, reported in the PR).**

- *The atomic-by-default arm is empty on F-DEV.* PKG-DEV-PIPE's judged lines, C1 and C2, are
  six-band open lines, and C3 is multiple choice. FR-PKG-29 gives a six-band line that is not an
  `evidence_sum` aspect `holistic`, so "everything holistic" and the new default publish the
  same scoring models here. The precondition asserts this from the catalog. Forcing a line
  atomic would cut its base panel from 3 to 1, which is a judge call set the corpus never
  recorded. Atomic routing is covered at rung 1 by TC-AGG-32. The ENG7 publish of C1a/C1b as
  atomic is TC-PKG-40's subject.
- *"M-STATS low-confidence counts" names no surface.* `aeh.stats` reads no `criterion_score`
  and computes no low-confidence count over cells. TC-AGG-30 made the same finding (#819).
  What follows the routing here is M-AGG's own aggregate stage report and its `agg.routing.*`
  `run_metrics` rows (FR-AGG-23). Both are asserted to equal the stored routing in each run.

**Isolation: rung 3.** The composed pipeline runs over a real store, and every model answer is a
committed recording keyed on its request.

Markers: `integration`.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

from aeh.conf import AGG_KEYS, effective_config
from aeh.pkg import PackageCatalog
from tests.support import pipe_world

pytestmark = pytest.mark.integration

HOLISTIC_ENV = "HARNESS_AGG_HOLISTIC_MULTIPLIER"
ROUTINGS = ("auto", "queued", "provisional", "triage", "reviewed")
#: Big enough that the queue shows every flagged item (asserted via `residual_provisional`).
BUDGET_MINUTES = 600


def _agg_from_environment() -> dict[str, Any]:
    """The `HARNESS_AGG_*` keys as an entry point composes them (environment over file)."""
    return {key: value for key, value in effective_config({}).items() if key in AGG_KEYS}


def _drive(root: Any, monkeypatch: Any, multiplier: str | None) -> dict[str, Any]:
    """One replay; returns what each oracle reads, with the store closed."""
    from aeh.review import open_review

    if multiplier is None:
        monkeypatch.delenv(HOLISTIC_ENV, raising=False)
    else:
        monkeypatch.setenv(HOLISTIC_ENV, multiplier)
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world._run_cfg_overrides = _agg_from_environment  # the entry points' composition
    world.build_run()
    world.start_run()
    try:
        result = pipe_world.drive_composed(world)
        assert result.status == "complete", (result.status, result.pause_reason)
        handle = world.store.cohort(pipe_world.PIPE_COHORT_ID)
        run = dict(handle.query(
            "SELECT package_id, package_version_id FROM run WHERE run_id = :r",
            r=world.run_id)[0])
        catalog = PackageCatalog(world.store.package(run["package_id"]),
                                 package_id=run["package_id"])
        models = {str(c["criterion_id"]): str(c["scoring_model"])
                  for c in catalog.criteria(run["package_version_id"])
                  if c.get("evaluation_mode") == "judged"}
        scores = {(str(r["submission_id"]), str(r["criterion_id"])): dict(r) for r in handle.query(
            "SELECT submission_id, criterion_id, routing, confidence, judge_count "
            "FROM criterion_score WHERE run_id = :r AND COALESCE(judge_count, 0) > 0",
            r=world.run_id)}
        bands: dict[tuple[str, str], list[str]] = {}
        for r in handle.query(
                "SELECT w.submission_id, w.criterion_id, v.band FROM verdict v "
                "JOIN work_unit w ON w.work_id = v.work_id WHERE w.run_id = :r",
                r=world.run_id):
            bands.setdefault((str(r["submission_id"]), str(r["criterion_id"])), []).append(
                str(r["band"]))
        units = Counter(
            (str(r["submission_id"]), str(r["criterion_id"]), str(r["stage"]),
             str(r["origin"]), str(r["judge_id"]))
            for r in handle.query(
                "SELECT submission_id, criterion_id, stage, origin, judge_id FROM work_unit "
                "WHERE run_id = :r", r=world.run_id))
        metrics = {str(r["metric"]): float(r["value"]) for r in world.store.durable().query(
            "SELECT metric, value FROM run_metrics WHERE run_id = :r "
            "AND metric LIKE 'agg.routing.%'", r=world.run_id)}
        report = [t.metrics for t in result.stages
                  if t.stage == "aggregate" and isinstance(t.metrics, dict)]
        knobs = world.resolved.agg_knobs
        run_id = world.run_id
    finally:
        world.store.close()

    review = open_review(root, run_id=run_id)
    queue = review.build_queue(run_id, BUDGET_MINUTES, record=False)
    assert queue.residual_provisional == 0, "precondition: the budget shows every flagged item"
    shown: set[tuple[str, str]] = set()
    for entry in queue.shown:
        for item in getattr(entry, "members", None) or (entry,):
            shown.add((str(item.submission_id), str(item.criterion_id)))
    return {"models": models, "scores": scores, "bands": bands, "units": units,
            "metrics": metrics, "report": report, "queue": shown, "knobs": knobs}


def _routing_follows(run: dict[str, Any], label: str) -> None:
    """Oracles 2 and 4 for one run: the queue is the non-auto cells; the report and run_metrics
    count the stored routing."""
    not_auto = {cell for cell, row in run["scores"].items() if row["routing"] != "auto"}
    assert run["queue"] == not_auto, (
        f"{label}: the review queue {sorted(run['queue'])} is not the cells routed away from "
        f"auto {sorted(not_auto)}")
    stored = Counter(row["routing"] for row in run["scores"].values())
    counts = {name: stored.get(name, 0) for name in ROUTINGS}
    (report,) = run["report"]
    assert report["routing"] == counts, (label, report["routing"], counts)
    assert run["metrics"] == {f"agg.routing.{name}": float(n) for name, n in counts.items()}, (
        label, run["metrics"])


def test_tc_agg_35_only_unanimous_holistic_and_atomic_default_cells_change_routing(
        tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_PROFILE", raising=False)
    for key in AGG_KEYS:
        monkeypatch.delenv(key, raising=False)
    old = _drive(tmp_path / "old", monkeypatch, "0.85")
    new = _drive(tmp_path / "new", monkeypatch, None)

    # The two runs froze the two defaults.
    assert old["knobs"].holistic_multiplier == 0.85
    assert new["knobs"].holistic_multiplier == 0.95, "the new default is FR-AGG-22's 0.95"

    # Precondition (plan finding): on F-DEV every judged line is holistic under both, so the
    # atomic-by-default set is empty and "everything holistic" is the package as published.
    assert old["models"] == new["models"] == {"C1": "holistic", "C2": "holistic"}, (
        old["models"], new["models"])
    atomic_by_default: set[tuple[str, str]] = {
        cell for cell in new["scores"] if new["models"][cell[1]] == "atomic"}
    assert atomic_by_default == set()

    # 1. The changed cells are exactly the unanimous-holistic (and atomic-by-default) ones.
    assert set(old["scores"]) == set(new["scores"]) and len(new["scores"]) == 6
    unanimous_holistic = {cell for cell, bands in new["bands"].items()
                          if new["models"][cell[1]] == "holistic" and len(set(bands)) == 1}
    assert old["bands"] == new["bands"], "the two replays judged differently"
    changed = {cell for cell in new["scores"]
               if old["scores"][cell]["routing"] != new["scores"][cell]["routing"]}
    assert changed == unanimous_holistic | atomic_by_default, (
        f"routing changed on {sorted(changed)}; the delta intends exactly "
        f"{sorted(unanimous_holistic | atomic_by_default)}")
    assert changed, "the differential moved nothing: 0.85 and 0.95 routed alike"
    for cell in unanimous_holistic:
        assert (old["scores"][cell]["routing"], new["scores"][cell]["routing"]) == (
            "queued", "auto"), (cell, old["scores"][cell], new["scores"][cell])
    # Dissenting holistic cells move confidence, never routing.
    for cell in set(new["scores"]) - changed:
        assert old["scores"][cell]["routing"] == new["scores"][cell]["routing"] != "auto", cell

    # 2 and 4. The queue and the counts follow the routing in each run.
    _routing_follows(old, "old defaults")
    _routing_follows(new, "new defaults")
    assert len(new["queue"]) == len(old["queue"]) - len(changed)

    # 3. The multiplier moved no escalation: identical panels and judge units per cell.
    assert {c: r["judge_count"] for c, r in old["scores"].items()} == {
        c: r["judge_count"] for c, r in new["scores"].items()}
    assert old["units"] == new["units"], "escalation enqueued different units"
    assert any(r["judge_count"] > 3 for r in new["scores"].values()), (
        "precondition: some cell escalated, so the comparison covers an enqueue")
