"""`TC-AGG-34` (issue #896, FR-AGG-23, CT-AGG-25; pair M-AGG → CT-JUDGE-32) — the aggregate
stage report.

Statistical-validity test plan §3.5 (story T3). On the F-DEV replay with one relocated citation
seeded:

- the aggregate stage reports confidence min, median and max, per-cap fire counts, counts by
  routing, the uncited count, and `reanchored = 1`;
- `run_metrics` holds the same figures as `agg.<name>` rows;
- a relocated span counts as cited, not uncited;
- an empty run (0 cells) reports counts of 0 and min/median/max as absent with a reason, never
  0.0.

**The seeded relocation.** F-DEV-PIPE replayed from its committed recordings, with one judge
reply altered on its way back from the recording (the RES-20 wrapper pattern, not a new
recording): its first cited span keeps its quoted words, and its offsets are shifted by
`SHIFT` bytes. The quote no longer verifies at those offsets, so M-JUDGE re-anchors it to the
words' unique occurrence (FR-JUDGE-40, FR-INTEG-13) and stores the verdict `reanchored = 1`.
Because the relocation lands on the original offsets, nothing downstream of the stored spans
changes, and the rest of the replay still hits its recordings.

**The oracle** is the stored rows, read independently here (`criterion_score`, `verdict`), and a
reference replay with no seeding: the seeded run's uncited count equals the reference's (the
relocated verdict did not become uncited), and its re-anchored count is the reference's + 1.

**The empty run** is a created, enumerated and started run that was never driven, reported by
M-PIPE's own `aggregation_report` (the function `run_to_completion` calls at the end of every
drive) — a drive of it would first aggregate cells.

**Isolation: rung 3** — the composed pipeline over a real store, every model answer a committed
recording keyed on its request. **Written ahead of implementation: no** — #865 (PR #928).

Markers. `integration`.
"""

from __future__ import annotations

import dataclasses
import json
import statistics
from typing import Any

import pytest

from aeh.orch import Orchestrator
from aeh.pipeline.aggregation_report import aggregation_report
from tests.support import pipe_world

pytestmark = pytest.mark.integration

#: How far the seeded span's offsets are moved off its words.
SHIFT = 3
CAPS = ("spans_verified", "evidence_present", "sufficiency_flag", "ocr_overlap_risk",
        "described_evidence", "extractor_disagreement")
ROUTINGS = ("auto", "queued", "provisional", "triage", "reviewed")


class _RelocateOneCitation:
    """Shifts the offsets of the first cited span in the first citing judge reply."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.seeded: dict[str, Any] | None = None

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        completion = self._inner.complete(prompt, model_ref, params)
        if self.seeded is not None or getattr(model_ref, "role", None) != "judge":
            return completion
        try:
            reply = json.loads(completion.text)
        except ValueError:
            return completion
        spans = reply.get("cited_spans") if isinstance(reply, dict) else None
        if not spans or not spans[0].get("text"):
            return completion
        original = dict(spans[0])
        spans[0] = {**original, "start": original["start"] + SHIFT,
                    "end": original["end"] + SHIFT}
        self.seeded = original
        return dataclasses.replace(completion, text=json.dumps(reply))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _drive(root: Any, monkeypatch: Any, *, seed: bool):
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    wrapper = _RelocateOneCitation(world.provider) if seed else None
    if wrapper is not None:
        world.provider = wrapper
    result = pipe_world.drive_composed(world)
    assert result.status == "complete", (result.status, result.pause_reason)
    return world, result, wrapper


def _report(result: Any) -> Any:
    """The end-of-run report: the one `aggregate` trace carrying figures (the per-pass
    `aggregate` traces carry per-cell detail and no metrics)."""
    traces = [trace for trace in result.stages
              if trace.stage == "aggregate" and isinstance(trace.metrics, dict)]
    assert len(traces) == 1, [(trace.stage, trace.metrics) for trace in result.stages]
    return traces[0]


def _verdict_counts(world: Any) -> tuple[int, int]:
    row = world.store.cohort(pipe_world.PIPE_COHORT_ID).query(
        "SELECT SUM(v.uncited = 1) AS uncited, SUM(v.reanchored = 1) AS reanchored "
        "FROM verdict v JOIN work_unit w ON w.work_id = v.work_id WHERE w.run_id = :r",
        r=world.run_id)[0]
    return int(row["uncited"] or 0), int(row["reanchored"] or 0)


def _run_metrics(store: Any, run_id: str) -> dict[str, float]:
    rows = store.durable().query(
        "SELECT metric, value FROM run_metrics WHERE run_id = :r AND metric LIKE 'agg.%'",
        r=run_id)
    return {str(r["metric"]): float(r["value"]) for r in rows}


def test_tc_agg_34_the_stage_report_on_a_replay_with_one_relocated_citation(
        tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_PROFILE", raising=False)
    reference, _ref_result, _ = _drive(tmp_path / "reference", monkeypatch, seed=False)
    try:
        ref_uncited, ref_reanchored = _verdict_counts(reference)
    finally:
        reference.store.close()

    world, result, wrapper = _drive(tmp_path / "seeded", monkeypatch, seed=True)
    try:
        assert wrapper.seeded is not None, "fixture: no citing judge reply was seeded"
        handle = world.store.cohort(pipe_world.PIPE_COHORT_ID)
        rows = handle.query(
            "SELECT confidence, routing, caps_fired FROM criterion_score "
            "WHERE run_id = :r AND COALESCE(judge_count, 0) > 0", r=world.run_id)
        confidences = sorted(float(r["confidence"]) for r in rows)
        routing = {name: sum(1 for r in rows if r["routing"] == name) for name in ROUTINGS}
        caps = {name: sum(1 for r in rows if name in json.loads(r["caps_fired"] or "[]"))
                for name in CAPS}
        uncited, reanchored = _verdict_counts(world)
        relocated = handle.query(
            "SELECT v.uncited, v.cited_spans FROM verdict v JOIN work_unit w "
            "ON w.work_id = v.work_id WHERE w.run_id = :r AND v.reanchored = 1",
            r=world.run_id)
        metrics_rows = _run_metrics(world.store, world.run_id)
    finally:
        world.store.close()

    # The seeding took: exactly one verdict re-anchored, and it is cited.
    assert (ref_reanchored, reanchored) == (0, 1), (ref_reanchored, reanchored)
    assert len(relocated) == 1 and int(relocated[0]["uncited"]) == 0, relocated
    stored = json.loads(relocated[0]["cited_spans"] or "[]")
    assert any(span.get("start") == wrapper.seeded["start"] for span in stored), (
        f"the relocated span was not stored at its words' offsets: {stored} vs {wrapper.seeded}")
    assert uncited == ref_uncited, (
        f"a relocated span counted as uncited: {uncited} uncited vs {ref_uncited} unseeded")

    report = _report(result)
    m = report.metrics
    assert m["cells"] == len(rows) == 6, (m["cells"], len(rows))
    assert (m["confidence_min"], m["confidence_median"], m["confidence_max"]) == (
        pytest.approx(confidences[0]), pytest.approx(statistics.median(confidences)),
        pytest.approx(confidences[-1])), (m, confidences)
    assert m["confidence_absent_reason"] is None
    assert m["caps_fired"] == caps, (m["caps_fired"], caps)
    assert m["routing"] == routing, (m["routing"], routing)
    assert sum(m["routing"].values()) == m["cells"]
    assert (m["uncited"], m["reanchored"]) == (uncited, 1), m

    # run_metrics carries the same figures as `agg.<name>` rows.
    expected_rows = {
        "agg.cells": float(m["cells"]),
        "agg.confidence_min": m["confidence_min"],
        "agg.confidence_median": m["confidence_median"],
        "agg.confidence_max": m["confidence_max"],
        "agg.uncited": float(m["uncited"]),
        "agg.reanchored": 1.0,
        **{f"agg.caps_fired.{name}": float(count) for name, count in caps.items()},
        **{f"agg.routing.{name}": float(count) for name, count in routing.items()},
    }
    assert metrics_rows == pytest.approx(expected_rows), (metrics_rows, expected_rows)


def test_tc_agg_34_an_empty_run_reports_zero_counts_and_absent_confidence(
        tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_PROFILE", raising=False)
    world = pipe_world.replay_world(tmp_path / "empty", monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    try:
        orchestrator = Orchestrator(world.store)
        trace = aggregation_report(orchestrator, orchestrator.run_handle(world.run_id),
                                   world.run_id)
        metrics_rows = _run_metrics(world.store, world.run_id)
    finally:
        world.store.close()

    m = trace.metrics
    assert trace.stage == "aggregate" and m is not None, trace
    assert m["cells"] == 0
    for name in ("confidence_min", "confidence_median", "confidence_max"):
        assert m[name] is None, f"{name} = {m[name]!r}: an unmeasured figure must be absent"
    assert isinstance(m["confidence_absent_reason"], str) and m["confidence_absent_reason"].strip()
    assert m["routing"] == {name: 0 for name in ROUTINGS}, m["routing"]
    assert m["caps_fired"] == {name: 0 for name in CAPS}, m["caps_fired"]
    assert (m["uncited"], m["reanchored"]) == (0, 0)
    assert "absent" in trace.detail[0], trace.detail

    assert metrics_rows.get("agg.cells") == 0.0, metrics_rows
    absent = [name for name in metrics_rows if name.startswith("agg.confidence")]
    assert absent == [], f"absent figures were written as rows: {absent}"
