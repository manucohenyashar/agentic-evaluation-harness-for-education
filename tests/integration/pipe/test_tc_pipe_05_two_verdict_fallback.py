"""TC-PIPE-05 (FR-PIPE-05; gap-fix test plan §5, re-specified by TS-128 / closeout T6).

| Arm | Oracle |
|---|---|
| fallback | A 3-arm cell whose one arm quarantines after its strikes leaves 2 verdicts: `aggregate` is called with `fallback=True`, the stored row is `judge_count = 1`, `state = 'provisional_unreviewed'`, and no row anywhere in the run has `judge_count = 2` |
| variant | The same arm fails once and its re-request succeeds: 3 verdicts, `fallback=False`, `judge_count = 3` |

Re-specified: the plan row says `state = 'provisional'`; the state vocabulary is
`provisional_unreviewed` (closeout design T6).

Fixture: F-DEV-PIPE replay. The cell is S1's C1 (ordinal 0, unanimous, never escalated), so the
two-verdict path is FR-PIPE-05's and not FR-PIPE-18's widened-panel replacement. The arm is the
first panel judge (`...@sha256:aaaa`); its reply is replaced with an illegal verdict, which
M-JUDGE strikes (the F-TAXONOMY `ProviderError("500")` of the plan has the same effect at the
ledger: a strike per attempt, quarantine at the ceiling).
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest

import aeh.pipeline as pipeline
from tests.support import pipe_world

pytestmark = pytest.mark.integration

ARM = "/models/llama-3.3-70b.gguf@sha256:aaaa"
S1_C1_EVIDENCE = "I did not get to th"


def _is_target(prompt, model_ref) -> bool:
    fields = dict(prompt.fields)
    return (model_ref.build_id == ARM and "criterion_id: C1" in str(fields.get("criterion"))
            and S1_C1_EVIDENCE in str(fields.get("submission")))


def _drive(root: Path, monkeypatch, failures: int | None):
    """Drive F-DEV-PIPE with the target arm answering illegally `failures` times (None: always)."""
    calls: list[tuple[str, int, bool]] = []
    written: list[tuple[str, str, int]] = []
    real_aggregate, real_write = pipeline.aggregate, pipeline.write_score

    def write_score(tx, run_id, submission_id, score, signals):
        written.append((submission_id, str(score.criterion_id), int(score.judge_count)))
        return real_write(tx, run_id, submission_id, score, signals)

    monkeypatch.setattr(pipeline, "write_score", write_score)

    def spy(verdicts, criterion, signals, **kwargs):
        calls.append((str(criterion.criterion_id), len(verdicts), bool(kwargs.get("fallback"))))
        return real_aggregate(verdicts, criterion, signals, **kwargs)

    monkeypatch.setattr(pipeline, "aggregate", spy)
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    inner = world.provider.complete
    struck = {"n": 0}

    def complete(prompt, model_ref, params):
        if _is_target(prompt, model_ref) and (failures is None or struck["n"] < failures):
            struck["n"] += 1
            return dataclasses.replace(inner(prompt, model_ref, params), text="not a verdict")
        return inner(prompt, model_ref, params)

    world.provider.complete = complete
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    with sqlite3.connect(root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite") as c:
        c.row_factory = sqlite3.Row
        units = c.execute("SELECT submission_id, status FROM work_unit WHERE stage = 'score' "
                          "AND criterion_id = 'C1' AND judge_id = ?", (ARM,)).fetchall()
        scores = {(r["submission_id"], r["criterion_id"]): dict(r) for r in c.execute(
            "SELECT * FROM criterion_score WHERE run_id = ?", (world.run_id,))}
    # S1 is the corpus's absent-C1 submission (ordinal 0): the target cell's owner.
    (s1,) = {sid for (sid, cid), row in scores.items() if cid == "C1" and row["band"] == "absent"}
    return result, struck["n"], units, scores, calls, written, s1


def test_tc_pipe_05_two_verdicts_after_a_quarantine_fall_back_to_one(tmp_path, monkeypatch):
    result, struck, units, scores, calls, written, s1 = _drive(tmp_path / "w", monkeypatch, failures=None)
    quarantined = [u["submission_id"] for u in units if u["status"] == "quarantined"]
    assert quarantined == [s1] and struck >= 2, f"fixture: quarantined {quarantined} after {struck} strikes"
    cell = (quarantined[0], "C1")
    assert ("C1", 2, True) in calls, f"aggregate was not called with fallback=True over 2 verdicts: {calls}"
    row = scores[cell]
    assert (row["judge_count"], row["state"]) == (1, "provisional_unreviewed"), (
        f"cell {cell}: {row} (FR-PIPE-05: the base single-judge band, provisional)")
    assert not [k for k, r in scores.items() if r["judge_count"] == 2], (
        "a judge_count = 2 row exists: an even panel was aggregated as one")
    assert result.status == "complete" and result.pause_reason is None, result.pause_reason


def test_tc_pipe_05_variant_a_successful_re_request_keeps_the_full_panel(tmp_path, monkeypatch):
    result, struck, units, scores, calls, written, s1 = _drive(tmp_path / "w", monkeypatch, failures=1)
    assert struck == 1 and not [u for u in units if u["status"] == "quarantined"], (struck, units)
    assert ("C1", 2, True) not in calls, f"a fallback aggregation ran with no quarantine: {calls}"
    target = [n for sid, cid, n in written if (sid, cid) == (s1, "C1")]
    assert target == [3], f"S1's C1 cell was written with judge counts {target}, not once over 3"
    assert scores[(s1, "C1")]["judge_count"] == 3, scores[(s1, "C1")]
    assert result.status == "complete" and result.pause_reason is None, result.pause_reason
