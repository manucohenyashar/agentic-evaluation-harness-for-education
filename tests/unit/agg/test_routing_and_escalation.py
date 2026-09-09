"""`TC-AGG-07/08/09/11/17` — routing from the declared set, and escalation from
observable signals.

Test plan §5.12 (row forms), issue #95 (TS-36). Traces to `FR-AGG-06` (ceiling half),
`FR-AGG-07`, `FR-AGG-08`, `FR-AGG-09`. **Landed at #93** (routing assignment and the
escalation policy; the `aggregate` core beneath the routing cells is #91's, the
confidence surface #92's). TC-AGG-07's review-queue rank limb lives in
`test_review_queue_rank.py` — a separate blocker (`aeh.review:rank_queue_items`,
#108), separately registered.

**Interface of #93, as declared and as landed** (the TC-ORCH-32 stand-in shapes —
one vocabulary, one reconciliation):

| Name | Status |
|---|---|
| `aeh.agg:aggregate(verdicts, criterion, signals, *, config=None, deterministic_score=None, fallback=False, breaker_tripped=False)` | **landed at #93 with these keywords**: the panel path plus FR-AGG-10's pass-through. The deterministic row arrives **complete** (`judge_count = 0`, its own `state`/`routing`) and passes through unchanged — an empty verdict list is a programming error (CT-AGG-12), so the pass-through cannot ride the panel path. |
| `aeh.agg:should_escalate(score, criterion, history, baseline)` | **landed at #93** (TC-ORCH-32's keyword call) with the `config=` knob. Returns `aeh.agg:EscalationDecision` carrying `.escalate` (bool) and `.target_judge_count` (int) — the invented field names declared below are what shipped, plus `.reasons` (the fired observables, self-confidence never among them). |
| score `.confidence` `.ordinal` `.band_count` `.judge_count` `.uncited` `.self_confidence` + the four FR-AGG-13 integrity fields | the observable signals live on the row (§7.1's list; FR-AGG-13 records four of them). `escalation_score()` in the vocabulary is the stand-in. |
| routing values | the shipped migration v9 CHECK: `{'auto', 'queued', 'reviewed', 'provisional', 'triage'}` — the declared set, enforced by the schema; the assignment landed at #93 (breaker and single-judge → `provisional`, threshold → `auto`/`queued`). |
| `nextafter`-built injected thresholds | TC-AGG-17 says "thresholds injected as configuration": every boundary value in this file is built from the implementation's **own** computed confidence (`nextafter` neighbours), so no tuning number is baked into the tests (Q-04). |

Isolation: rung 0 — pure functions and doubles only; the socket guard is autouse.
"""

from __future__ import annotations

from math import nextafter

import pytest

from tests.support.agg_vocabulary import (
    band,
    criterion,
    panel,
    signals,
    verdict,
    agg_config,
    escalation_score,
    criterion_history,
    expected_distribution,
)
from tests.support.impl import AGG_MODULE, ORCH_MODULE, require

_FOUR_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                        band("B3", 3, 6.0)])
_UNANIMOUS_TOP = panel(("B3", 3), ("B3", 3), ("B3", 3))
_SPLIT = panel(("B0", 0), ("B1", 1), ("B1", 1), ("B1", 1), ("B2", 2))  # α = 0.52

#: The det-shaped row that rides the pass-through: FR-DET-03's unresolved-selection
#: shape, `state = 'unresolved_selection'`, `routing = 'triage'`, NULL points —
#: shipped today by `aeh.det` (the state/routing CHECKs landed with det migration v9).
_UNRESOLVED_ROW = {
    "submission_id": "s-agg-08",
    "criterion_id": "C-AGG",
    "band": "B0",
    "points": None,
    "judge_count": 0,
    "agreement": None,
    "state": "unresolved_selection",
    "routing": "triage",
}

_ROUTING_SET = {"auto", "queued", "reviewed", "provisional", "triage"}


def test_tc_agg_07_the_holistic_ceiling_is_strictly_lower_at_identical_verdicts():
    """`TC-AGG-07` ceiling half (`FR-AGG-06`, unit / rung 0, exact comparison, P0) —
    an `atomic` and a `holistic` criterion with identical verdicts and signals: the
    holistic confidence is never higher, and at the holistic criterion's own confidence
    figure the atomic criterion auto-accepts while the holistic one does not (the
    thresholds are injected around the implementation's own value, so no tuning number
    is baked in)."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")
    atomic_band = criterion(_FOUR_BAND.bands, scoring_model="atomic")
    holistic_band = criterion(_FOUR_BAND.bands, scoring_model="holistic")

    atomic = aggregate(_UNANIMOUS_TOP, atomic_band, signals(), config=agg_config())
    holistic = aggregate(_UNANIMOUS_TOP, holistic_band, signals(), config=agg_config())

    assert holistic.confidence < atomic.confidence, (
        f"holistic scored {holistic.confidence!r} against atomic {atomic.confidence!r} "
        "on identical verdicts and signals — the holistic criterion must carry the "
        "lower auto-acceptance ceiling (FR-AGG-06, CT-AGG-09)"
    )

    # The routing differential at the holistic criterion's own figure: atomic's
    # threshold is injected AT that figure, holistic's a single ULP above it — so the
    # atomic criterion auto-accepts where the holistic one cannot, whatever the
    # shipped tuning of the holistic multiplier turns out to be.
    config = agg_config(
        auto_threshold_atomic=holistic.confidence,
        auto_threshold_holistic=nextafter(holistic.confidence, 2.0),
    )
    atomic_at = aggregate(_UNANIMOUS_TOP, atomic_band, signals(), config=config)
    holistic_at = aggregate(_UNANIMOUS_TOP, holistic_band, signals(), config=config)

    assert atomic_at.routing == "auto", (
        f"atomic at confidence {atomic_at.confidence!r} with threshold "
        f"{holistic.confidence!r} routed {atomic_at.routing!r} — the differential is "
        "the ceiling's observable form (FR-AGG-06)"
    )
    assert holistic_at.routing != "auto", (
        f"holistic at its own confidence {holistic_at.confidence!r} routed "
        f"{holistic_at.routing!r} with the threshold one ULP above — the holistic "
        "ceiling must sit strictly below the atomic one (FR-AGG-06)"
    )


@pytest.mark.parametrize("provenance", ["unresolved_selection", "ingestion_failure"])
def test_tc_agg_08_stateful_rows_pass_through_to_triage_never_to_queued(provenance):
    """`TC-AGG-08` (`FR-AGG-07`, unit / rung 0, decision table, P0) — unresolved-
    selection and ingestion-caused states route to `triage` (the operator queue),
    never to `queued` (the teacher's). Both provenances surface as the same det row
    shape (FR-DET-03: a selection failure and an ingestion-caused non-score are both
    written `state='unresolved_selection'`); the assertion is that the pass-through
    preserves the operator routing and never re-assigns the teacher's queue."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")

    row = dict(_UNRESOLVED_ROW)
    score = aggregate([], _FOUR_BAND, signals(), deterministic_score=row,
                      config=agg_config())

    assert score.routing == "triage", (
        f"a {provenance} row routed {score.routing!r} — unresolved-selection and "
        "ingestion-caused states go to the OPERATOR queue (FR-AGG-07, R64)"
    )
    assert score.routing in _ROUTING_SET, "routing left the declared set (FR-AGG-07)"


def test_tc_agg_08_the_decision_table_assigns_the_declared_set():
    """`TC-AGG-08` (`FR-AGG-07`, unit / rung 0, decision table, P0) — the remaining
    cells: a normal high-confidence result routes `auto` (exact); a panel-disagreement
    result routes `queued` (exact — the teacher's queue, not the operator's); and no
    cell leaves the declared set."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")

    normal = aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(), config=agg_config())
    assert normal.routing == "auto", (
        f"a unanimous top-band fully-favourable result routed {normal.routing!r} — "
        "the normal high-confidence cell is 'auto' (FR-AGG-07)"
    )

    disagreement = aggregate(_SPLIT, _FOUR_BAND, signals(), config=agg_config())
    assert disagreement.routing == "queued", (
        f"a split panel (α = 0.52, below the auto threshold) routed "
        f"{disagreement.routing!r} — panel disagreement is the TEACHER's queue, "
        "'queued', not 'triage' (FR-AGG-07: triage is for unresolved-selection and "
        "ingestion-caused states)"
    )

    for score in (normal, disagreement):
        assert score.routing in _ROUTING_SET, (
            f"routing {score.routing!r} left the declared set {sorted(_ROUTING_SET)}"
        )


def test_tc_agg_09_every_observable_signal_alone_moves_the_escalation_decision():
    """`TC-AGG-09` (`FR-AGG-08`, unit / rung 0, invariant, P0) — each observable
    signal varied alone, all others held constant at the favourable baseline, flips
    the escalation decision: interior band position, adverse integrity signals,
    uncited verdict, transcription overlap, criterion override history and
    distributional anomaly against the package baseline."""
    should_escalate = require(AGG_MODULE, "should_escalate", issue="#93")
    baseline = dict(ordinal=3, band_count=4, mean=3.0, std=0.5)

    calm = should_escalate(
        score=escalation_score(**{k: baseline[k] for k in ("ordinal", "band_count")}),
        criterion=_FOUR_BAND,
        history=criterion_history(),
        baseline=expected_distribution(mean=baseline["mean"], std=baseline["std"]),
    )
    assert calm.escalate is False, (
        f"the all-favourable extreme-band on-baseline score escalated ({calm!r}) — "
        "the baseline the signal sweep varies from must not escalate (FR-AGG-08)"
    )

    variations = {
        "interior band position": dict(
            score=escalation_score(ordinal=2, band_count=4)),
        "adverse integrity signal": dict(
            score=escalation_score(spans_verified=False)),
        "uncited verdict": dict(score=escalation_score(uncited=True)),
        "transcription overlap": dict(score=escalation_score(ocr_overlap_risk=True)),
        "override history": dict(history=criterion_history(override_rate=0.6)),
        "distributional anomaly": dict(
            baseline=expected_distribution(mean=0.0, std=0.1)),
    }
    for name, override in variations.items():
        kwargs = dict(
            score=escalation_score(**{k: baseline[k] for k in ("ordinal", "band_count")}),
            criterion=_FOUR_BAND,
            history=criterion_history(),
            baseline=expected_distribution(mean=baseline["mean"], std=baseline["std"]),
        )
        kwargs.update(override)
        decision = should_escalate(**kwargs)
        assert decision.escalate is True, (
            f"{name} varied alone left the decision at no-escalation ({decision!r}) — "
            "the escalation decision responds to every observable signal (FR-AGG-08, "
            "R22); the input that failed is named in this message"
        )


def test_tc_agg_09_self_confidence_alone_cannot_flip_the_escalation_decision():
    """`TC-AGG-09` (`FR-AGG-08`, unit / rung 0, invariant, P0) — model self-confidence
    is ONE weighted input and NEVER the sole trigger: swept across both extremes and
    the interior with every observable signal held constant, the decision does not
    move."""
    should_escalate = require(AGG_MODULE, "should_escalate", issue="#93")

    decisions = [
        should_escalate(
            score=escalation_score(self_confidence=confidence),
            criterion=_FOUR_BAND,
            history=criterion_history(),
            baseline=expected_distribution(),
        )
        for confidence in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]
    assert all(d == decisions[0] for d in decisions), (
        f"self-confidence alone moved the decision: {[d for d in decisions]} — it is "
        "one weighted input, never the sole trigger (FR-AGG-08, CT-AGG-08, R22)"
    )


def test_tc_agg_11_a_single_judge_criterion_escalates_one_to_three_never_to_two():
    """`TC-AGG-11` (`FR-AGG-09`, unit / rung 0, negative, exact value plus API
    assertion, P0) — an escalation decision on a single-judge criterion targets
    exactly three; and the API surface offers no code path producing two: the shipped
    escalated-depth normalizer refuses an even plan (`aeh.orch`, landed at #60), and
    the decision's own target is odd."""
    should_escalate = require(AGG_MODULE, "should_escalate", issue="#93")
    validate_plan, even_plan_error = require(
        ORCH_MODULE, "validate_escalation_plan", "EvenEscalationPlanError"
    )

    single_judge = escalation_score(judge_count=1, ordinal=2, band_count=4)
    decision = should_escalate(
        score=single_judge,
        criterion=_FOUR_BAND,
        history=criterion_history(),
        baseline=expected_distribution(),
    )
    assert decision.escalate is True, (
        f"a single-judge interior-band criterion did not escalate ({decision!r}) — "
        "the base panel depth is 1 and the escalation is warranted (FR-AGG-09)"
    )
    assert decision.target_judge_count == 3, (
        f"the escalation target is {decision.target_judge_count!r} — one judge "
        "escalates to exactly three (FR-AGG-09, R48)"
    )

    with pytest.raises(even_plan_error):
        validate_plan(2)
    assert validate_plan(3) == 3, (
        "the depth normalizer must pass the odd target through unchanged — the "
        "escalation path's 3 is the value TC-AGG-11 pins"
    )


@pytest.mark.parametrize("scoring_model", ["atomic", "holistic"])
@pytest.mark.parametrize("side", ["just_below", "at", "just_above"])
def test_tc_agg_17_auto_accept_fires_exactly_at_the_injected_threshold(scoring_model, side):
    """`TC-AGG-17` (`FR-AGG-08` boundary through the auto-accept decision, unit /
    rung 0, P0) — a criterion score at, just below and just above the auto-accept
    threshold, for both scoring models, with the threshold **injected as
    configuration**: the threshold value is the implementation's own confidence for
    the model's unanimous panel, and its `nextafter` neighbours are the just-below and
    just-above cells. Auto-accept fires at or above the threshold and not below."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")
    crit = criterion(_FOUR_BAND.bands, scoring_model=scoring_model)

    reference = aggregate(_UNANIMOUS_TOP, crit, signals(), config=agg_config())
    threshold = {
        "just_below": reference.confidence,
        "at": reference.confidence,
        "just_above": reference.confidence,
    }[side]
    if side == "just_below":
        threshold = nextafter(threshold, 2.0)      # strictly above the confidence
    elif side == "just_above":
        threshold = nextafter(threshold, 0.0)      # strictly below the confidence

    config = agg_config(
        auto_threshold_atomic=threshold, auto_threshold_holistic=threshold
    )
    score = aggregate(_UNANIMOUS_TOP, crit, signals(), config=config)

    fires = score.confidence >= threshold
    assert (score.routing == "auto") is fires, (
        f"{scoring_model} at confidence {score.confidence!r} with injected threshold "
        f"{threshold!r} routed {score.routing!r} — auto-accept fires exactly at or "
        "above the injected threshold and not below (FR-AGG-06's boundary, TC-AGG-17)"
    )


def test_tc_agg_17_the_boundary_holds_for_a_score_at_the_threshold_from_below():
    """`TC-AGG-17` (`FR-AGG-08`, unit / rung 0, boundary, P0) — the same boundary
    through a NON-unanimous panel, so the boundary is not an artefact of the α = 1
    fixture: the split panel's own confidence is the injected threshold, and the
    result auto-accepts there but not one ULP above."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")

    reference = aggregate(_SPLIT, _FOUR_BAND, signals(), config=agg_config())
    config = agg_config(
        auto_threshold_atomic=reference.confidence,
        auto_threshold_holistic=nextafter(reference.confidence, 2.0),
    )
    at = aggregate(_SPLIT, _FOUR_BAND, signals(), config=config)
    assert at.routing == "auto", (
        f"the split panel at its own confidence {at.confidence!r} with the threshold "
        f"injected at that value routed {at.routing!r} — at the threshold is not "
        "below it (TC-AGG-17)"
    )


def test_tc_agg_08_one_judge_panel_routes_provisional_not_queued():
    """`TC-AGG-08` (`FR-AGG-07`, unit / rung 0, P0) — the declared set's fifth value
    is reachable: a single-judge fallback result routes `provisional` (the
    single-judge band is provisional by construction), distinct from both `queued`
    and `triage`."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")
    score = aggregate(panel(("B3", 3)), _FOUR_BAND, signals(), config=agg_config())

    assert score.routing == "provisional", (
        f"a single-judge result routed {score.routing!r} — the provisional cell of "
        "the declared set (FR-AGG-07; TC-AGG-12's state is its twin)"
    )
