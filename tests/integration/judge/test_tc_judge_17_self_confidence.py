"""`TC-JUDGE-17` — the judge's self-confidence is persisted verbatim and consumed
without authority (`FR-JUDGE-13`, `R22`; issue #83 (TS-31)).

Two halves, per the case table:

- **persistence**: the reply's `self_confidence` number travels verbatim — through the
  dispatch (the `ScoringResult` field) and onto the verdict row — for a HIGH (0.95) and
  a LOW (0.05) self-assessment. The value is the judge's own report, not a re-derivation
  and not a clamp;
- **consumption**: at the escalation boundary, self-confidence is ONE weighted input
  and NEVER a trigger: swept across both extremes and the interior (the judge-tier
  figures included), the decision does not move when every observable signal is
  favourable; but the same sweep WITH the uncited mark escalates at EVERY confidence —
  the judge's confidence does not buy back a missing citation — and the fired reasons
  name the observable, never the confidence (`R22`: self-confidence is not
  authoritative, so it is never a reason).

The routing half drives the shipped `should_escalate` at the judge boundary: the
`self_confidence` values fed in are the same numbers the persistence half proved ride
the verdict row. (The escalation policy's own case sweep is TC-AGG-09's; this file
pins the judge-tier handoff.)

Isolation: rung 2 for the persistence half (real store, real extraction leg, replies
through `RecordedFixtureProvider`), rung 0 for the routing half (pure policy, no
store). No model, no network.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.agg_vocabulary import (
    band as agg_band,
    criterion as agg_criterion,
    criterion_history,
    escalation_score,
    expected_distribution,
)
from tests.support.conf_builders import EDGE_JUDGE
from tests.support.extract_vocabulary import JUDGE_ISSUE
from tests.support.impl import AGG_MODULE, JUDGE_MODULE, require
from tests.support.judge_run import (
    CONTROL_BAND,
    judge_world,
    reply_text,
    verdict_rows,
    warm_judged_modules,
)

pytestmark = [pytest.mark.integration]

#: The two submissions answer identically except for the self-confidence figure: a
#: HIGH and a LOW self-assessment, both uncited (the citation gate passes vacuously,
#: so the confidence is the only varying figure end to end).
SUBMISSIONS = ("s-17-high", "s-17-low")
HIGH_CONFIDENCE = 0.95
LOW_CONFIDENCE = 0.05

#: The sweep the consumption half varies — both extremes, the interior, and the two
#: figures the persistence half proved land on the row.
CONFIDENCE_SWEEP = (0.0, LOW_CONFIDENCE, 0.5, HIGH_CONFIDENCE, 1.0)

#: The one judge of the world's panel — replies are addressed by its build id.
JUDGE_BUILD = EDGE_JUDGE.build_id

#: The calm criterion the routing sweep reads: four declared bands, the score parked on
#: the TOP band (ordinal 3 of 4) — an edge, not an interior position, so the only limb
#: that can fire across the sweep is the uncited mark (TC-AGG-09's baseline shape).
_CALM_CRITERION = agg_criterion(
    (
        agg_band("B0", 0, 0.0),
        agg_band("B1", 1, 1.0),
        agg_band("B2", 2, 3.0),
        agg_band("B3", 3, 6.0),
    )
)


def _reply_for(submission_id: str, _judge_build: str):
    """Both replies uncited, carrying the submission's own confidence figure — the
    only varying value between the two units."""
    confidence = HIGH_CONFIDENCE if submission_id == SUBMISSIONS[0] else LOW_CONFIDENCE
    return reply_text(CONTROL_BAND, confidence, build_id=JUDGE_BUILD, cited_spans=None)


def _world(tmp_data_dir, make_fixture_provider):
    warm_judged_modules()
    store = open_store(tmp_data_dir / "data")
    provider = make_fixture_provider()
    world = judge_world(
        store,
        provider,
        submissions=SUBMISSIONS,
        panel=1,
        reply_for=_reply_for,
    )
    return store, world


def _escalation_kwargs(confidence: float, *, uncited: bool) -> dict:
    """One `should_escalate` call at the judge boundary: every observable signal at
    its favourable reading — the score parked on the top band AND on the baseline's
    mean, so no distributional anomaly fires either — and the given self-confidence,
    the only figure varied (besides the mark, on the fired side)."""
    return dict(
        score=escalation_score(self_confidence=confidence, uncited=uncited),
        criterion=_CALM_CRITERION,
        history=criterion_history(),
        baseline=expected_distribution(mean=3.0, std=0.5),
    )


# --- persistence: the figure travels verbatim --------------------------------------------------------


def test_tc_judge_17_a_the_self_confidence_figure_travels_verbatim_to_the_row(
    tmp_data_dir, make_fixture_provider
):
    """The reply's `self_confidence` is persisted EXACTLY — a HIGH and a LOW
    self-assessment land on their rows un-derived and un-clamped, and the two rows
    differ ONLY in that figure, proving it came from the reply and not from the
    pipeline."""
    store, world = _world(tmp_data_dir, make_fixture_provider)
    assert not world["failures"], (
        f"both replies dispatch: {world['failures']!r}"
    )
    ScoringResult = require(JUDGE_MODULE, "ScoringResult", issue=JUDGE_ISSUE)
    for submission_id, confidence in (
        (SUBMISSIONS[0], HIGH_CONFIDENCE),
        (SUBMISSIONS[1], LOW_CONFIDENCE),
    ):
        result = world["results"][(submission_id, JUDGE_BUILD)]
        assert isinstance(result, ScoringResult), (
            f"precondition: the dispatch returned the shipped result: {result!r}"
        )
        assert result.self_confidence == confidence, (
            f"the dispatch carries the reply's own figure {confidence}, got "
            f"{result.self_confidence!r} (FR-JUDGE-13: persisted, not re-derived)"
        )
        unit = world["score_units"][(submission_id, JUDGE_BUILD)]
        row = verdict_rows(store, unit.work_id)[0]
        assert row["self_confidence"] == confidence, (
            f"the row carries the reply's own figure {confidence}, got "
            f"{row['self_confidence']!r}"
        )
        assert row["band"] == CONTROL_BAND


# --- consumption: confidence without authority at the escalation boundary ----------------------------


def test_tc_judge_17_b_self_confidence_never_triggers_and_never_gates_the_fire():
    """At the escalation boundary: over the confidence sweep, with every observable
    signal favourable, the decision does not move (`R22` — self-confidence is never
    the sole trigger); with the uncited mark set, EVERY figure escalates and the
    reasons name the observable, never the confidence — the judge's own confidence
    cannot buy back a missing citation."""
    should_escalate = require(AGG_MODULE, "should_escalate", issue="#93")
    calm = [
        should_escalate(**_escalation_kwargs(c, uncited=False))
        for c in CONFIDENCE_SWEEP
    ]
    assert all(d == calm[0] for d in calm), (
        f"self-confidence alone moved the escalation decision over the sweep "
        f"{CONFIDENCE_SWEEP}: {calm!r} — it is never the sole trigger (FR-JUDGE-13, "
        f"R22)"
    )
    fired = [
        should_escalate(**_escalation_kwargs(c, uncited=True))
        for c in CONFIDENCE_SWEEP
    ]
    for confidence, decision in zip(CONFIDENCE_SWEEP, fired):
        assert decision.escalate is True, (
            f"the uncited mark did not fire at self-confidence {confidence} "
            f"({decision!r}) — the judge's own confidence cannot buy back a missing "
            f"citation (FR-JUDGE-13, R22)"
        )
        assert decision.reasons == ("uncited verdict",), (
            f"the fired reasons name the observable, never the confidence: "
            f"{decision.reasons!r} at confidence {confidence}"
        )
        assert not any("confidence" in reason.lower() for reason in decision.reasons), (
            f"a reason names the judge's confidence — R22 forbids it: "
            f"{decision.reasons!r}"
        )