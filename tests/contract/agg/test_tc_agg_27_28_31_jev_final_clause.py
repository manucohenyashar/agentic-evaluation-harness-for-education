"""TC-AGG-27, TC-AGG-28, TC-AGG-31 (#814): the Jev-final clause, rung 0.

Traces: FR-AGG-20 (amends FR-AGG-07, narrows FR-AGG-19), CT-AGG-23, CT-AGG-24, CT-JUDGE-07.
Source: docs/design/console_clarity_test_plan.md §3.2; design docs/design/console_clarity_design_delta.md
FR-AGG-20 / ADR-50.

| Case | Asserted |
|---|---|
| TC-AGG-27 | The decision table: (a) one `decision` verdict, knob default → `final`/`auto` + the note; (b) one `llm` verdict → `provisional_unreviewed`/`one_grader_unsure`; (c) knob off → FR-AGG-07 unchanged; (d) 3 agreeing (1 decision + 2 llm) → engine-blind, equal to the all-llm panel; (e) two decision verdicts → `PanelCorrelationError`; (f) breaker → `ungradeable_by_panel`/`graders_refused` |
| TC-AGG-28 | Row (a)'s confidence is the gate (0.91), not the verdict's `self_confidence`; row (b) keeps the prior (≤ 0.75); property: any gate g in (0.80, 1] is recorded as g |
| TC-AGG-31 | The five aggregate-reachable not-final codes, one seeded cell each; a routed-`auto` cell carries none. (`more_graders_unavailable` is set by the pipeline, not `aggregate`: its rung-3 limb is `tests/unit/pipe/test_tc_agg_31_seatless_reason.py`) |

**Interface assumed** (written ahead of #806; the design names the knob and the codes, not the
Python surface):
- `aggregate(..., jev_final_on_accept: bool = True)` — keyword-only, like `breaker_tripped`.
  `aggregate` reads no environment (CT-AGG-01), so the caller passes the frozen RunConfig value.
- the decision verdict carries its gate as `gate_confidence` (the `decision_prescreen` column).
- `CriterionScore.not_final_reason: str | None`, `None` on a routed-`auto` cell.

"Final" is read as routing `auto`: a queued three-judge cell is stored `state='final'`,
`routing='queued'`, and FR-AGG-20 gives queued cells a reason too.

**Markers.** Every case is `writtenahead` on #806. The seeds keep `self_confidence` (0.95) apart
from the gate (0.91), so an implementation that records the wrong figure fails here.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from tests.support.agg_vocabulary import band, criterion, favourable_signals, signals, verdict
from tests.support.impl import NotImplementedYet

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

BLOCKER = "#806"
GATE = 0.91
SELF_CONFIDENCE = 0.95
JEV_NOTE = "decided by the decision engine above its confidence threshold"
REASONS = frozenset({"one_grader_unsure", "graders_disagree", "evidence_not_found",
                     "quote_not_verified", "more_graders_unavailable", "graders_refused"})


def _crit(model: str = "atomic"):
    return criterion([band("B", 0, 0.0), band("D", 1, 1.0), band("P", 2, 2.0), band("E", 3, 3.0)],
                     scoring_model=model)


def _v(name: str, ordinal: int, engine: str, *, gate: float | None = GATE,
       self_confidence: float = SELF_CONFIDENCE):
    """A stored verdict as `aggregate` reads it, plus the FR-AGG-20 fields."""
    v = verdict(name, ordinal, self_confidence=self_confidence)
    v.scoring_engine = engine
    v.gate_confidence = gate
    return v


def _aggregate(verdicts, crit=None, sig=None, *, knob: bool | None = None, **kw):
    """`aggregate` with the FR-AGG-20 knob; refuses clearly while #806 has not landed."""
    from aeh.agg import aggregate

    if "jev_final_on_accept" not in inspect.signature(aggregate).parameters:
        raise NotImplementedYet(
            f"aggregate has no `jev_final_on_accept` keyword yet (blocked on {BLOCKER}): "
            "FR-AGG-20's knob, written ahead of its implementation (test plan §8.2).")
    if knob is not None:
        kw["jev_final_on_accept"] = knob
    return aggregate(verdicts, crit or _crit(), sig or favourable_signals(), **kw)


def _reason(score):
    if "not_final_reason" not in {f.name for f in dataclasses.fields(score)}:
        raise NotImplementedYet(
            f"CriterionScore has no `not_final_reason` yet (blocked on {BLOCKER}): FR-AGG-20's "
            "closed reason set, written ahead of its implementation (test plan §8.2).")
    return score.not_final_reason


# --- TC-AGG-27: the decision table -------------------------------------------------------------

def test_tc_agg_27_a_lone_accepted_decision_is_final_by_default() -> None:
    """Row (a). No knob passed: the default is `true` (FR-AGG-20)."""
    score = _aggregate([_v("P", 2, "decision")])
    assert (score.state, score.routing) == ("final", "auto")
    assert any(JEV_NOTE in note for note in score.notes), score.notes
    assert _reason(score) is None


def test_tc_agg_27_b_a_lone_llm_verdict_stays_provisional_one_grader_unsure() -> None:
    """Row (b). The llm verdict carries a high gate figure too, so a rule keyed on the verdict
    count alone, or on a gate figure regardless of engine, turns this red (the plan's CT-AGG-24
    mutation)."""
    score = _aggregate([_v("P", 2, "llm", gate=0.99)], knob=True)
    assert (score.state, score.routing) == ("provisional_unreviewed", "provisional")
    assert _reason(score) == "one_grader_unsure"
    assert not any(JEV_NOTE in note for note in score.notes)


def test_tc_agg_27_c_knob_off_restores_fr_agg_07() -> None:
    """Row (c). The code is not pinned by the plan for this row; it must exist and be in the set."""
    score = _aggregate([_v("P", 2, "decision")], knob=False)
    assert (score.state, score.routing) == ("provisional_unreviewed", "provisional")
    assert score.confidence <= 0.75
    assert _reason(score) in REASONS


def test_tc_agg_27_d_a_three_judge_panel_stays_engine_blind() -> None:
    """Row (d). One decision + two llm verdicts aggregate exactly as three llm verdicts: the
    gate figure does not leak into a panel's confidence (CT-AGG-23 amended)."""
    mixed = _aggregate([_v("P", 2, "decision"), _v("P", 2, "llm", gate=None), _v("P", 2, "llm", gate=None)],
                       knob=True)
    blind = _aggregate([_v("P", 2, "llm", gate=None) for _ in range(3)], knob=True)
    assert mixed == blind
    assert (mixed.state, mixed.routing, mixed.judge_count) == ("final", "auto", 3)
    assert not any(JEV_NOTE in note for note in mixed.notes)


def test_tc_agg_27_e_two_decision_verdicts_still_fault() -> None:
    """Row (e). The Jev delta's two-decision refusal is unchanged, knob on or off."""
    from aeh.agg import PanelCorrelationError

    for knob in (True, False):
        with pytest.raises(PanelCorrelationError):
            _aggregate([_v("P", 2, "decision"), _v("P", 2, "decision"), _v("D", 1, "llm")], knob=knob)


def test_tc_agg_27_f_the_breaker_takes_precedence_over_jev_final() -> None:
    """Row (f). A lone accepted decision on a breaker-tripped criterion is not final."""
    score = _aggregate([_v("P", 2, "decision")], knob=True, breaker_tripped=True)
    assert (score.state, score.routing) == ("ungradeable_by_panel", "provisional")
    assert _reason(score) == "graders_refused"


# --- TC-AGG-28: confidence matches route -------------------------------------------------------

def test_tc_agg_28_a_the_recorded_confidence_is_the_gate() -> None:
    from aeh.agg.settings import AGG_AUTO_THRESHOLD_ATOMIC

    score = _aggregate([_v("P", 2, "decision")])
    assert score.confidence == GATE != SELF_CONFIDENCE
    assert score.confidence > AGG_AUTO_THRESHOLD_ATOMIC


def test_tc_agg_28_b_an_llm_verdict_keeps_the_single_judge_prior() -> None:
    """Band E is the scale's edge, so the prior is exactly its 0.75 ceiling; the verdict's gate
    figure (0.99) and self-confidence (0.95) are both ignored."""
    score = _aggregate([_v("E", 3, "llm", gate=0.99)], knob=True)
    assert score.confidence == pytest.approx(0.75)
    assert score.confidence <= 0.75


try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
except ImportError:  # pragma: no cover
    given = None

if given is not None:
    @pytest.mark.property
    @settings(max_examples=150, deadline=None)
    @given(st.floats(min_value=0.80, max_value=1.0, exclude_min=True, allow_nan=False),
           st.integers(0, 3))
    def test_tc_agg_28_property_any_accepted_gate_is_the_recorded_confidence(gate, ordinal) -> None:
        """Atomic, cited, favourable signals: no multiplier or cap applies, so equality is exact.
        `self_confidence` is held at 0.5 so it can never coincide with the gate."""
        score = _aggregate([_v("BDPE"[ordinal], ordinal, "decision", gate=gate, self_confidence=0.5)])
        assert score.confidence == gate
        assert (score.state, score.routing) == ("final", "auto")


# --- TC-AGG-31: every not-final code reachable -------------------------------------------------

def _unanimous(sig):
    return _aggregate([_v("P", 2, "llm", gate=None) for _ in range(3)], sig=sig, knob=True)


@pytest.mark.parametrize("code, build", [
    ("one_grader_unsure", lambda: _aggregate([_v("P", 2, "llm", gate=None)], knob=True)),
    ("graders_disagree", lambda: _aggregate(
        [_v("B", 0, "llm", gate=None), _v("D", 1, "llm", gate=None), _v("E", 3, "llm", gate=None)], knob=True)),
    ("evidence_not_found", lambda: _unanimous(signals(evidence_present=False))),
    ("quote_not_verified", lambda: _unanimous(signals(spans_verified=False))),
    ("graders_refused", lambda: _aggregate([_v("P", 2, "llm", gate=None)], knob=True, breaker_tripped=True)),
], ids=lambda x: x if isinstance(x, str) else "")
def test_tc_agg_31_each_not_final_code_is_reachable(code, build) -> None:
    score = build()
    # Precondition: the seed really is not final (a three-judge seed must have been queued).
    assert score.routing != "auto", (code, score.confidence, score.routing)
    if score.judge_count == 3:
        assert score.routing == "queued", (code, score.routing)
    assert _reason(score) == code


def test_tc_agg_31_a_final_cell_carries_no_code() -> None:
    jev_final = _aggregate([_v("P", 2, "decision")])
    panel_final = _unanimous(favourable_signals())
    for score in (jev_final, panel_final):
        assert score.routing == "auto"
        assert _reason(score) is None
