"""TC-ORCH-61, TC-ORCH-62 (#819): no escalation for a Jev-final cell; every other cell escalates
exactly as it does with the engine off.

Traces: FR-ORCH-45, CT-AGG-24, FR-AGG-08, FR-ORCH-10, FR-ORCH-14, CT-ORCH-15. Source:
`docs/design/console_clarity_test_plan.md` §3.2 (story T6).

| Case | Asserted |
|---|---|
| TC-ORCH-61 | Base panel of one, two escalation judges, budget 1.0, knob on. X = (S2, C1), an accepted decision the seat judge confirms; Y = (S2, C2), a below-gate cell whose LLM verdict is interior. X: one unit, no `enqueue_escalation` call, so no escalation unit and no budget, stored `final`/`auto` at the gate. Y: escalated 1 → 3. Random arm at rate 1.0 (on the edge-band Jev-final cell (S3, C1)): it still gets its two random-arm units and no escalation (CT-ORCH-15), and is re-aggregated by the panel rule: three agreeing → `final` with the panel's confidence (0.85), not the gate; one disagreeing → not final, `graders_disagree` (see the divergences) |
| TC-ORCH-62 | Differential. The same F-DEV-PIPE run is driven with the engine off and with the engine on. On the engine-on run every recorded `decide` is below the gate, and (S1, C1) passes the gate but fails citation verification. Per cell the two runs match on: the `should_escalate` decisions and reasons, the `enqueue_escalation` reports (judges added in order, depth, budget figures), the score units (judge, origin), the verdict depth, and the stored band/points/state/routing/judge count/confidence/reason. Arms: (a) the ladder: mid-scale (S2, C1) goes 1 → 3 distinct models and is scored at the median band; (b) the three-model panel: every C2 cell starts at three; (c) its spread persists and it widens to five; (d) a confident edge-band single LLM verdict (S3, C1) is not escalated and stays `provisional_unreviewed` / `one_grader_unsure`. Mutation: `enqueue_escalation` skips every cell whose seat ran the engine, and the differential goes red on (a) and (c) |

**Rung.** Rung 3: the composed pipeline (`aeh.pipeline.run_to_completion`) over a real store and
F-DEV-PIPE, with every model answer a recording keyed on its exact request
(`tests/support/jev_final_pipe.py`, capture mode). The engine-off run is TC-ORCH-62's oracle. No
expected escalation is hand-written; the arm checks only pin which cells exercise which rule.

**Disclosed divergences.**
- F-DEV-PIPE's two judged criteria are both holistic (its only atomic criterion is the MCQ,
  which M-DET scores), so the plan's atomic/holistic pair is mapped onto the two ladder shapes
  the orchestrator has. The base panel size, not the scoring model, sets where a cell starts.
  With a base panel of one, every judged cell starts at one judge and widens to three: arms (a)
  and (d). With the three-model panel, every judged cell starts at three and widens to five:
  arms (b) and (c). Each shape is run as its own differential.
- TC-ORCH-61's split-panel arm: the plan expects `provisional_unreviewed`, but the unchanged
  three-judge rule stores a 2-1 panel `final` / `queued` (a holistic panel never clears the 0.90
  bar). The case asserts the shipped panel rule's outcome and the plan's reason code,
  `graders_disagree`. The random-arm case uses an edge-band cell, because an interior band always
  widens under the ordinary rule.
- The citation failure is induced at the worker's citation check for one cell's pre-screen only
  (`forge_citation_on`). F-DEV-PIPE's evidence spans are the document's own bytes, so an
  in-corpus forged span would also fail the engine-off LLM verdicts, and the differential would
  then compare two broken runs.
- `should_escalate` is observed through the aggregate hook's loop variable, because the score
  carries no submission id.

Markers. `integration`. Written against shipped code (#806), so not `writtenahead`.
"""

from __future__ import annotations

import statistics

import pytest

from harness.corpora import dev_pipe
from tests.support.jev_final_pipe import (ACCEPTED, BELOW_GATE, cells, drive, every_cell,
                                          forge_citation_on, new_world)

pytestmark = pytest.mark.integration

FORGED = ("S1", "C1")
X, Y = ("S2", "C1"), ("S2", "C2")


def _engine_on_outcomes():
    outcomes = every_cell(BELOW_GATE)
    outcomes[FORGED] = dict(ACCEPTED)
    return outcomes


def _run(root, *, engine, panel_size, enqueue_filter=None, **world_kwargs):
    world = new_world(root, engine=engine, panel_size=panel_size, **world_kwargs)
    undo = forge_citation_on(world, FORGED) if engine else (lambda: None)
    try:
        result, observed = drive(world, enqueue_filter=enqueue_filter)
        assert result.status == "complete", result.pause_reason
        return cells(world), observed
    finally:
        undo()
        world.store.close()


def _differential(on, on_seen, off, off_seen) -> dict:
    """Every cell's mismatches between the engine-on and engine-off runs."""
    diff = {}
    for cell in sorted(set(on) | set(off)):
        a, b = on.get(cell, {}), off.get(cell, {})
        fields = {name: (a.get(name), b.get(name))
                  for name in ("units", "depth", "score", "judges", "ordinals")
                  if a.get(name) != b.get(name)}
        for name, seen_a, seen_b in (("should_escalate", on_seen.should_escalate, off_seen.should_escalate),
                                     ("enqueued", on_seen.enqueued, off_seen.enqueued)):
            if seen_a.get(cell) != seen_b.get(cell):
                fields[name] = (seen_a.get(cell), seen_b.get(cell))
        if fields:
            diff[cell] = fields
    return diff


def _skip_engine_seats(orch, tx, key):
    """The plan's mutation: enqueue nothing for a cell whose seat ran the engine."""
    run_id, submission_id, criterion_id = key
    rows = list(tx.execute("SELECT count(*) n FROM decision_prescreen WHERE run_id = :r AND "
                           "submission_id = :s AND criterion_id = :c",
                           r=run_id, s=submission_id, c=criterion_id))
    return int(rows[0]["n"]) == 0


def _assert_engine_ran_below_gate(on) -> None:
    for cell, row in on.items():
        assert row["prescreen"] is not None and row["prescreen"][0] == "below_gate", (cell, row)
        assert set(row["engines"]) == {"llm"}, (cell, row["engines"])
    assert on[FORGED]["prescreen"][:2] == ("below_gate", "citation_unverified")


# --- TC-ORCH-62 ----------------------------------------------------------------------------------

def test_tc_orch_62_the_one_to_three_ladder_is_unchanged_by_the_engine(tmp_path) -> None:
    off, off_seen = _run(tmp_path / "off", engine=False, panel_size=1)
    on, on_seen = _run(tmp_path / "on", engine=True, panel_size=1, outcomes=_engine_on_outcomes())
    _assert_engine_ran_below_gate(on)
    assert _differential(on, on_seen, off, off_seen) == {}

    # (a) mid-scale: 1 -> 3, each a distinct model, scored at the median band.
    a = on[X]
    assert on_seen.should_escalate[X][0][0] is True
    assert len(a["units"]) == 3 and len({j for j, _o, _s in a["units"]}) == 3, a["units"]
    assert a["score"][4] == 3
    assert a["score"][0] == dev_pipe.band_at("C1", int(statistics.median(a["ordinals"])))
    # (d) a confident single LLM verdict at a scale edge, cited, no adverse signal.
    d = on[("S3", "C1")]
    assert [escalate for escalate, _r in on_seen.should_escalate[("S3", "C1")]] == [False]
    assert len(d["units"]) == 1 and ("S3", "C1") not in on_seen.enqueued
    assert d["score"][2:5] == ("provisional_unreviewed", "provisional", 1)
    assert d["score"][6] == "one_grader_unsure"

    mutated, mutated_seen = _run(tmp_path / "mutated", engine=True, panel_size=1,
                                 outcomes=_engine_on_outcomes(), enqueue_filter=_skip_engine_seats)
    red = _differential(mutated, mutated_seen, off, off_seen)
    assert X in red, f"the mutation did not turn arm (a) red: {sorted(red)}"


def test_tc_orch_62_the_three_model_panel_widens_to_five_unchanged_by_the_engine(tmp_path) -> None:
    off, off_seen = _run(tmp_path / "off", engine=False, panel_size=3)
    on, on_seen = _run(tmp_path / "on", engine=True, panel_size=3, outcomes=_engine_on_outcomes())
    _assert_engine_ran_below_gate(on)
    assert _differential(on, on_seen, off, off_seen) == {}

    c2 = {cell: row for cell, row in on.items() if cell[1] == "C2"}
    for cell, row in c2.items():
        # (b) starts at three base judges; (c) the spread persists, so it widens to five.
        assert sum(1 for _j, origin, _s in row["units"] if origin == "base") == 3, (cell, row)
        assert len(row["units"]) == 5 and row["score"][4] == 5, (cell, row)
        assert on_seen.enqueued[cell][0][1:4] == (("escalation-arm-4", "escalation-arm-5"), 5, 2)

    mutated, mutated_seen = _run(tmp_path / "mutated", engine=True, panel_size=3,
                                 outcomes=_engine_on_outcomes(), enqueue_filter=_skip_engine_seats)
    red = _differential(mutated, mutated_seen, off, off_seen)
    assert set(c2) <= set(red), f"the mutation did not turn arm (c) red: {sorted(red)}"


# --- TC-ORCH-61 ----------------------------------------------------------------------------------

#: The random-arm case's Jev-final cell sits at a scale edge (`comprehensive`, the top band).
#: An interior band always widens under the ordinary panel rule ("interior band position"), so
#: an edge cell lets the case read the panel rule's own outcome for three verdicts.
XR = ("S3", "C1")


def _orch_61_outcomes(cell=X):
    outcomes = every_cell(BELOW_GATE)
    outcomes[cell] = dict(ACCEPTED)
    return outcomes


def test_tc_orch_61_a_jev_final_cell_is_not_escalated_and_consumes_no_budget(tmp_path) -> None:
    on, seen = _run(tmp_path / "w", engine=True, panel_size=1, agreeing=True,
                    outcomes=_orch_61_outcomes())
    x, y = on[X], on[Y]
    assert x["prescreen"][0] == "accepted" and x["engines"] == ["decision"]
    assert (x["score"][2], x["score"][3], x["score"][4]) == ("final", "auto", 1)
    assert x["score"][5] == pytest.approx(ACCEPTED["gate"])
    assert x["units"] == [(x["units"][0][0], "base", "done")], "X: no escalation unit"
    assert X not in seen.enqueued, "X: no escalation admitted, so no budget consumed"
    # Y escalates on the ordinary path.
    assert y["prescreen"][0] == "below_gate"
    assert seen.enqueued[Y][0][0] == "admitted" and len(y["units"]) == 3


@pytest.mark.parametrize("disagree", [False, True], ids=["three_agree", "one_disagrees"])
def test_tc_orch_61_the_random_arm_still_samples_a_jev_final_cell(tmp_path, monkeypatch,
                                                                  disagree) -> None:
    from aeh.conf.orch_knobs import RANDOM_ARM_RATE_ENV_KEY

    world = new_world(tmp_path / "w", engine=True, panel_size=1, agreeing=True,
                      outcomes=_orch_61_outcomes(XR))
    assert world.cohort[2].bands["C1"] == "comprehensive", "precondition: XR is at the top edge"
    if disagree:
        # One random-arm judge gives the neighbouring band on XR.
        world.band_overrides = {(*XR, "escalation-arm-3"): "secure"}
    monkeypatch.setenv(RANDOM_ARM_RATE_ENV_KEY, "1.0")
    try:
        result, seen = drive(world)
        assert result.status == "complete", result.pause_reason
        x = cells(world)[XR]
    finally:
        world.store.close()
    origins = sorted(origin for _j, origin, _s in x["units"])
    assert origins == ["base", "random_arm", "random_arm"], x["units"]
    assert XR not in seen.enqueued, "the random arm is not an escalation (CT-ORCH-15)"
    assert x["engines"].count("decision") == 1 and x["depth"] == 3
    state, routing, count, confidence, reason = (x["score"][2], x["score"][3], x["score"][4],
                                                 x["score"][5], x["score"][6])
    assert count == 3
    # The ordinary three-judge rule: C1 scores holistically here, and a holistic panel tops out at
    # 1.0 x 0.85, below the 0.90 bar, so even a unanimous panel is routed `queued`. Neither arm is
    # Jev-final any more, and the confidence is the panel's, never the gate.
    assert routing == "queued" and confidence < ACCEPTED["gate"], x["score"]
    if disagree:
        # Plan finding: the plan expects `provisional_unreviewed` here, but the unchanged panel
        # rule stores a 2-1 panel `final` / `queued`. The not-final reason is the plan's.
        assert (state, reason) == ("final", "graders_disagree"), x["score"]
        assert confidence < 0.85, "a split panel's agreement lowers the panel confidence"
    else:
        assert state == "final" and confidence == pytest.approx(0.85), x["score"]
