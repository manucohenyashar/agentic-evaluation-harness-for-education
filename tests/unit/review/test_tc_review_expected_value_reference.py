"""`TC-REVIEW-02` and `-03` — the hand-computed expected-value reference and boundary proximity.

Test plan §5.15, `TC-REVIEW-02` and `TC-REVIEW-03`.

`TC-REVIEW-02`'s oracle line: *"Hand-computed reference"* — `expected_value` is
`(P(error) x impact) / est_seconds` and the reference below is computed **in the test** from
`FR-REVIEW-03`'s declared formula with the shipped defaults (all signal weights 1.0, integrity
cap 3, no-data override rate 0.5, boundary half-width 10.0), not read back from the module. A
reference computed by calling the module is not a reference: the point is that two independent
derivations of one number must agree.

`TC-REVIEW-03`'s oracle line: *"Exact comparison"* — two rows identical but for
`grade_boundary_delta` 0 vs 10 produce EVs in an exact 2:1 ratio at the declared half-width of
10, and the nearer-boundary item ranks first. No shipped test varies `grade_boundary_delta` (the
contract suite varies the four error signals, the self-confidence prohibition and the
EV-per-second ratio), so the impact limbs are genuinely new here.
"""

from __future__ import annotations

import dataclasses

import pytest

from tests.support import broken_review_fixtures as broken
from tests.support.impl import REVIEW_MODULE, require


# --- the reference, transcribed from FR-REVIEW-03 -------------------------------------------------


def _p_error(row) -> float:
    """`P(error)` with the shipped default weights: the four signals sum, integrity capped at 3."""
    override = row.historical_override_rate
    if override is None:
        override = 0.5
    return (
        row.panel_spread
        + min(row.adverse_integrity_signals, 3) / 3
        + row.transcription_overlap
        + override
    )


def _impact(row) -> float:
    """Impact with the shipped half-width 10: criterion weight, discounted by boundary distance."""
    return row.criterion_weight * 1.0 / (1.0 + abs(row.grade_boundary_delta) / 10.0)


def _expected_value(row) -> float:
    """`EV = (P(error) x impact) / est_seconds` — the formula the test plan states."""
    return _p_error(row) * _impact(row) / row.est_seconds


# --- TC-REVIEW-02 — the hand-computed reference ---------------------------------------------------


def test_tc_review_02_expected_value_matches_the_hand_computed_reference():
    """One hand-written row and the exact number it must produce.

    Written explicitly rather than drawn from `flagged_population`, because that fixture varies
    every field per index and the point here is arithmetic a reader can check by eye:

        P   = 0.2 + 1/3 + 0.1 + 0.1  = 0.7333...
        imp = 0.2 / (1 + 5/10)       = 0.2 / 1.5
        EV  = P x imp / 60           ~= 0.00162963

    Asserted against the in-test formula, not a tolerance band: a tolerance wide enough to
    survive a wrong formula is wide enough to hide one.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    row = broken.ScoreRow(
        score_id="ref-0",
        submission_id="ref-sub",
        panel_spread=0.2,
        adverse_integrity_signals=1,
        transcription_overlap=0.1,
        historical_override_rate=0.1,
        criterion_weight=0.2,
        grade_boundary_delta=5.0,
        est_seconds=60,
    )
    service = build_review(scores=[row])

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    item = queue.shown[0]

    reference = _expected_value(row)
    assert reference > 0, "the hand-computed reference is 0, so this case asserts nothing"
    assert item.expected_value == pytest.approx(reference), (
        f"the queue's expected_value {item.expected_value!r} is not the hand-computed reference "
        f"{reference!r}. FR-REVIEW-03: expected_value is (P(error) x impact) / est_seconds — a "
        "module ranking by its own arithmetic is not ranking by the declared formula."
    )


def test_tc_review_02_the_impact_inputs_move_expected_value_by_the_exact_ratios():
    """Each of the impact/divisor limbs, at the exact ratio the formula predicts.

    The four error signals are swept direction-wise by `CT-REVIEW-C03`; these are the three
    limbs no shipped test varies — criterion_weight, grade_boundary_delta and the est_seconds
    divisor. Every pair is identical except the one input, so the declared formula pins the
    ratio exactly: doubling the weight doubles EV, delta 0 vs 10 at half-width 10 halves the
    impact term (2:1), and halving the estimate doubles EV. The ratios are asserted on the
    queue's own `expected_value` figures — a rank direction alone would also be satisfied by
    a module that got both numbers wrong, which is the gap a self-referential ratio leaves.

    The rows carry distinct `criterion_id`s because the Phase-1 grouping signature includes
    the criterion: two rows identical on every signature component collapse into one
    `ReviewGroup`, which carries no per-item expected value to compare.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")

    # One explicit row per pair — `flagged_population` varies every field per index, so a
    # population row as base would drag six other inputs into the ratio.
    base = broken.ScoreRow(
        score_id="base",
        submission_id="base-sub",
        panel_spread=0.2,
        adverse_integrity_signals=1,
        transcription_overlap=0.1,
        historical_override_rate=0.1,
        criterion_weight=0.2,
        grade_boundary_delta=5.0,
        est_seconds=60,
    )

    pairs = [
        (
            "criterion_weight",
            base,
            dataclasses.replace(base, score_id="heavy", criterion_id="C-02", criterion_weight=0.4),
        ),
        (
            "grade_boundary_delta",
            dataclasses.replace(base, score_id="delta-10", criterion_id="C-03", grade_boundary_delta=10.0),
            dataclasses.replace(base, score_id="delta-0", criterion_id="C-04", grade_boundary_delta=0.0),
        ),
        (
            "est_seconds",
            dataclasses.replace(base, score_id="est-60", criterion_id="C-05"),
            dataclasses.replace(base, score_id="quick", criterion_id="C-06", est_seconds=30),
        ),
    ]

    rows = [row for _name, slower, faster in pairs for row in (slower, faster)]
    service = build_review(scores=rows)
    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    values = {item.score_id: item.expected_value for item in items_of(queue)}

    for name, slower, faster in pairs:
        assert {slower.score_id, faster.score_id} <= set(values), (
            f"the {name} pair did not both appear as items in the queue, so the ratio "
            "cannot be compared"
        )
        assert values[faster.score_id] == pytest.approx(2.0 * values[slower.score_id]), (
            f"{name}: the declared formula predicts an exact 2:1 ratio but the queue's own "
            f"expected values give {values[faster.score_id]!r} vs {values[slower.score_id]!r}. "
            "TC-REVIEW-02: each input moves expected_value by the arithmetic FR-REVIEW-03 "
            "declares, not merely in some direction."
        )


def test_tc_review_02_a_missing_override_rate_enters_as_the_declared_no_data_rate():
    """`historical_override_rate=None` enters the formula as 0.5, not 0 and not an absence.

    The no-data limb fails in both directions: a module treating None as 0 ranks the least-known
    criterion as the cleanest in the queue, and one treating it as missing and dropping the term
    rewards ignorance with a lower P(error). The assertion is the exact arithmetic consequence:
    the override component of P contributes exactly 0.5 on the no-data row.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")

    no_data = broken.ScoreRow(
        score_id="nodata-0", submission_id="nodata-sub", historical_override_rate=None
    )
    service = build_review(scores=[no_data])

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    item = queue.shown[0]

    assert _p_error(no_data) == pytest.approx(no_data.panel_spread + 0.5), (
        f"the no-data row's P(error) is {_p_error(no_data)!r}, so the missing override rate did "
        "not enter as the declared 0.5. FR-REVIEW-03: no data is not a clean record."
    )
    assert item.expected_value == pytest.approx(_expected_value(no_data)), (
        f"the queue's expected_value {item.expected_value!r} is not the no-data reference "
        f"{_expected_value(no_data)!r}. FR-REVIEW-03 substitutes the declared rate for the "
        "missing measurement; a module that dropped the term or used 0.0 ranks the criterion it "
        "knows least about as the one least likely to be wrong."
    )


# --- TC-REVIEW-03 — boundary proximity, exactly ---------------------------------------------------


def test_tc_review_03_the_item_nearer_the_boundary_ranks_higher_by_the_exact_ratio():
    """*"Two items identical but for boundary proximity — the nearer ranks higher. Exact
    comparison."*

    Delta 0 vs delta 10 at the declared half-width 10 gives impacts 1.0 vs 0.5 and so EVs in an
    exact 2:1. Every other input is identical by construction, and the ratio is asserted on the
    queue's own `expected_value` figures — a rank order alone would also be satisfied by a
    module that got both numbers wrong.

    The rows carry distinct `criterion_id`s because the Phase-1 grouping signature includes the
    criterion: two rows identical on every signature component collapse into one `ReviewGroup`,
    and this case is about the ranking of two *items* (grouping at scale is TC-REVIEW-08's own
    case).
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")

    near = broken.ScoreRow(
        score_id="near-boundary", submission_id="sub-near",
        criterion_id="C-01", grade_boundary_delta=0.0,
    )
    far = broken.ScoreRow(
        score_id="far-boundary", submission_id="sub-far",
        criterion_id="C-02", grade_boundary_delta=10.0,
    )
    service = build_review(scores=[far, near])

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    values = {item.score_id: item.expected_value for item in items_of(queue)}

    assert {"near-boundary", "far-boundary"} <= set(values), (
        "both rows did not appear as items in the queue, so boundary proximity cannot be compared"
    )
    assert values["near-boundary"] == pytest.approx(2.0 * values["far-boundary"]), (
        f"the near-boundary EV {values['near-boundary']!r} is not exactly twice the far-boundary "
        f"EV {values['far-boundary']!r}. TC-REVIEW-03 at the declared half-width 10: delta 0 vs "
        "delta 10 is impact 1.0 vs 0.5 — an exact 2:1, not a preference."
    )
    ids = [item.score_id for item in items_of(queue)]
    assert ids.index("near-boundary") < ids.index("far-boundary"), (
        f"the queue ranked the far-boundary item first: {ids}. TC-REVIEW-03: the item nearer a "
        "grade boundary ranks higher — a wrong band there moves a reported grade, which is why "
        "proximity buys priority."
    )


def test_tc_review_03_boundary_proximity_outranks_a_higher_error_probability():
    """The differential limb: proximity can beat a *higher* P(error).

    A module folding proximity in as a flat bonus and one ignoring it entirely both pass a
    same-P comparison, so the construction separates them. The far row carries the visibly
    higher error probability (spread 0.9 vs 0.5, P 1.0 vs 0.6) and still loses, because delta 20
    puts it two half-widths out: impact 0.2/3 vs 0.2/1. Hand-checked — near EV 0.6x0.2/60=0.002
    against far EV 1.0x(0.2/3)/60~=0.00111 — so the fixture itself is the reference the queue is
    held to.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")

    near = broken.ScoreRow(
        score_id="near", submission_id="sub-near",
        criterion_id="C-01", panel_spread=0.5, grade_boundary_delta=0.0,
    )
    far = broken.ScoreRow(
        score_id="far", submission_id="sub-far",
        criterion_id="C-02", panel_spread=0.9, grade_boundary_delta=20.0,
    )

    assert _expected_value(near) > _expected_value(far), (
        "the fixture no longer discriminates: the hand reference puts the higher-error row "
        "first, so proximity is not what the queue would be demonstrating"
    )

    service = build_review(scores=[far, near])
    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    ids = [item.score_id for item in items_of(queue)]
    assert ids.index("near") < ids.index("far"), (
        f"the queue ranked the higher-error far-boundary row first: {ids}. TC-REVIEW-03: "
        "proximity to a grade boundary is a declared ranking input, not a tie-breaker — an item "
        "two half-widths out with the higher P(error) still loses to one sitting on the line."
    )


# --- helpers --------------------------------------------------------------------------------------


def items_of(queue):
    """The queue's shown entries that are items, not groups.

    The rows in this file share no signature (distinct criteria, or single-row builds), so every
    entry is an item — but a group collapsing the fixture would otherwise surface as an
    AttributeError on `score_id`, far from the assertion that explains why. Groups at scale are
    TC-REVIEW-08's own case; this filter keeps the failure here legible.
    """
    entries = list(queue.shown)
    grouped = [entry for entry in entries if not hasattr(entry, "score_id")]
    if grouped:
        raise AssertionError(
            f"{len(grouped)} shown entries are groups, not items, so the per-item expected-value "
            "comparison cannot run: TC-REVIEW-03 needs two distinct signatures. Distinct "
            "criterion_id/band/flags per row is the fixture fix, not a looser assertion."
        )
    return entries