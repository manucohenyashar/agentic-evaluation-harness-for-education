"""Issue #445: F-JEV-DECISIONS is a committed, replayable corpus.

F-DEV-PIPE is driven with the fixture decision engine on. Every `decide`, and every
fallback and escalation `complete`, must replay from `fixtures/F-JEV-DECISIONS/recordings/`.
Each judged cell must land on the outcome Jev test plan §4.4 declares for it.
`pipe_world.DECISION_OUTCOMES` states those outcomes, and its disclosed divergences are
recorded there.

This is rung 3 for the same reason as F-DEV-PIPE's replay. The corpus claims to be complete
for a real run, and only a real run can check that claim.
"""

from __future__ import annotations

import pytest

from tests.support.pipe_world import DECISION_OUTCOMES, drive_composed, jev_replay_world

pytestmark = pytest.mark.integration

#: §4.4's outcomes as `decision_prescreen` records them: (outcome, reason).
EXPECTED = {
    ("S1", "C1"): ("accepted", None),
    ("S2", "C1"): ("below_gate", "below_threshold"),
    ("S3", "C1"): ("below_gate", "argmax_tie"),
    ("S1", "C2"): ("accepted", None),
    ("S2", "C2"): ("rejected", "rejected"),
    ("S3", "C2"): ("malformed", "malformed"),
}


def test_f_jev_decisions_replays_a_full_engine_on_run_with_every_declared_outcome(tmp_path) -> None:
    assert set(EXPECTED) == set(DECISION_OUTCOMES)
    world = jev_replay_world(tmp_path / "data")
    try:
        world.build_run()
        world.start_run()
        result = drive_composed(world)
        assert result.status == "complete", result.pause_reason
        assert world.provider.misses == [], f"requests with no recording: {world.provider.misses}"

        corpus_id = {sid: world.cohort[i - 1].submission_id for i, sid in world.sid_by_index.items()}
        rows = world.handle.query(
            "SELECT submission_id, criterion_id, outcome, reason, gate_confidence, "
            "cite_probabilities FROM decision_prescreen")
        got = {(corpus_id[r["submission_id"]], r["criterion_id"]): r for r in rows}
        assert {k: (r["outcome"], r["reason"]) for k, r in got.items()} == EXPECTED
        assert got[("S1", "C1")]["gate_confidence"] == pytest.approx(0.92)
        assert got[("S2", "C1")]["gate_confidence"] == pytest.approx(0.62)

        verdicts = {(corpus_id[r["submission_id"]], r["criterion_id"]): r for r in world.handle.query(
            "SELECT w.submission_id, w.criterion_id, v.cited_spans FROM verdict v "
            "JOIN work_unit w ON w.work_id = v.work_id WHERE v.scoring_engine = 'decision'")}
        assert set(verdicts) == {("S1", "C1"), ("S1", "C2")}

        score = next(s for s in result.stages if getattr(s, "metrics", None))
        assert score.metrics["decision_prescreens"] == 6 and score.metrics["decision_accepted"] == 2
    finally:
        world.store.close()


def test_f_jev_synth_replays_tc_e2e_05s_panel_of_one_run(tmp_path) -> None:
    """F-JEV-SYNTH: the engine-on, base-panel-of-one run TC-E2E-05 drives replays with no miss,
    and an accepted decision cell escalates to the panel `{decision, llm, llm}`."""
    from tests.support.pipe_world import jev_synth_replay_world

    world = jev_synth_replay_world(tmp_path / "data")
    try:
        world.build_run()
        world.start_run()
        result = drive_composed(world)
        assert result.status == "complete", result.pause_reason
        assert world.provider.misses == []
        outcomes = {r["outcome"] for r in world.handle.query("SELECT outcome FROM decision_prescreen")}
        assert outcomes == {"accepted"}
        panels = {r["e"] for r in world.handle.query(
            "SELECT group_concat(v.scoring_engine) e FROM verdict v JOIN work_unit w "
            "ON w.work_id = v.work_id GROUP BY w.submission_id, w.criterion_id HAVING count(*) > 1")}
        assert "decision,llm,llm" in panels
        assert world.handle.query("SELECT count(*) n FROM submission_grade")[0]["n"] == 8
    finally:
        world.store.close()
