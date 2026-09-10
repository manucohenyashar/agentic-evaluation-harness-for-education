"""`FUZZ-05` — the aggregation and policy-application invariants over generated inputs.

Test plan §6.7 (row form), issue #94 (TS-35). Traces to `FR-AGG-01`, `FR-AGG-02`,
`FR-GRADE-02`. Generator: band sets of 2, 4 and 6 bands with arbitrary non-decreasing
point tables **including negatives**; verdict lists of odd length (the production panel
lengths 1/3/5, CT-CONF-02); closed-vocabulary policies. The invariant set, verbatim
from §6.7:

1. aggregated points always equal `points_for_band(median_band)`;
2. totals never exceed the maximum achievable;
3. policy application is order-independent over criteria;
4. no even panel is ever aggregated.

Invariants 1 and 4 are `M-AGG`'s and **landed at #91** (unmarked there); invariants 2
and 3 are `M-GRADE`'s (`FR-GRADE-02`) and are written ahead of **#101** — the halves
are separate tests with separate registry entries, and the marker is per-test (the
`#118`/`#138`/`#139` node-ID precedent) so each half unmarks with its own blocker.

**Fixed seed set**: the suite's hypothesis profiles are `derandomize=True` (conftest,
§4.6's flake policy), so every CI run replays the same example set — the plan's "fixed
seed set" is the derandomized profile, and a failure reproduces by re-running the tier.

**Interface assumed of #91** (declared in `tests/support/agg_vocabulary.py`):
`aggregate(verdicts, criterion, signals)` and the invented `EvenPanelError`.

**Interface assumed of #101** — the design **does** declare the applicator
(detailed-design.md §3.14, CT-GRADE-02):
`apply_policy(scores: Sequence[CriterionScore], policy: GradePolicy) -> GradeComputation`,
pure and deterministic. What the Interfaces block does **not** pin is
`GradeComputation`'s field set, so one field is assumed here and reconciles at #101:
`.total` — the computed figure, a float when the grade stands and `None` when the
policy's gate refuses (the gate's "the computed grade to stand" consequence, read as a
null total rather than an exception — CT-GRADE-15's shape). A different real shape is a
one-edit reconciliation in this file.

Isolation: rung 0 — pure functions and generated values; no store, no model.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aeh.pkg import GateRule, GradePolicy, ScaleRule
from tests.support.agg_vocabulary import (
    AGG_BLOCKER,
    band,
    criterion,
    favourable_signals,
    score,
    verdict,
)
from tests.support.impl import AGG_MODULE, GRADE_MODULE, require
from tests.support.span_strategies import FUZZ_EXAMPLES

_FLOATS = st.floats(width=32, allow_nan=False, allow_infinity=False)


# --- the generator: band sets of 2, 4, 6 bands, non-decreasing points, negatives allowed ----


@st.composite
def _criterion_and_panels(draw, *, odd: bool) -> tuple:
    """A generated criterion (2, 4 or 6 bands, arbitrary non-decreasing point table
    including negatives) plus one verdict list — odd-length for invariant 1, even-length
    for invariant 4's refusal."""
    band_count = draw(st.sampled_from((2, 4, 6)))
    points = tuple(sorted(draw(
        st.lists(_FLOATS, min_size=band_count, max_size=band_count)
    )))
    crit = criterion(
        [band(f"B{i}", i, points[i]) for i in range(band_count)],
        criterion_id="C-FUZZ-05",
    )
    max_ordinal = band_count - 1
    if odd:
        size = 2 * draw(st.integers(min_value=0, max_value=2)) + 1  # 1, 3, 5 — CT-CONF-02
    else:
        size = 2 * draw(st.integers(min_value=1, max_value=3))      # 2, 4, 6
    ordinals = draw(
        st.lists(st.integers(min_value=0, max_value=max_ordinal),
                 min_size=size, max_size=size)
    )
    return crit, points, [verdict(f"B{o}", o) for o in ordinals]


@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(_criterion_and_panels(odd=True))
def test_fuzz_05_aggregated_points_equal_points_for_band_of_the_median_band(case):
    """`FUZZ-05` invariants 1 and 4, aggregation half (`FR-AGG-01`, `FR-AGG-02`) — over
    generated band sets and odd verdict lists, the score's points equal the median
    band's table entry exactly (a lookup, not a computation), and no even panel is ever
    aggregated: every even list is refused, never rounded."""
    aggregate = require(AGG_MODULE, "aggregate", issue=AGG_BLOCKER)

    crit, points, verdicts = case

    result = aggregate(verdicts, crit, favourable_signals())

    median_ordinal = sorted(v.ordinal for v in verdicts)[len(verdicts) // 2]
    assert result.band == f"B{median_ordinal}", (
        f"aggregated band {result.band!r} for medians of ordinals "
        f"{sorted(v.ordinal for v in verdicts)} — the median band ordinal (FR-AGG-01)"
    )
    assert result.points == points[median_ordinal], (
        f"points {result.points!r} do not equal points_for_band(median_band) = "
        f"{points[median_ordinal]!r} — the aggregate is mapped from the median band "
        "exactly once, never averaged from per-judge points (FR-AGG-02); exact "
        "equality is the oracle because a mapping is a lookup"
    )


@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(_criterion_and_panels(odd=False))
def test_fuzz_05_no_even_panel_is_ever_aggregated(case):
    """`FUZZ-05` invariant 4's refusal limb (`FR-AGG-03`) — even-length verdict lists of
    every generated shape are refused outright, over the whole generated space."""
    aggregate = require(AGG_MODULE, "aggregate", issue=AGG_BLOCKER)
    even_panel_error = require(AGG_MODULE, "EvenPanelError", issue=AGG_BLOCKER)
    crit, _points, verdicts = case

    with pytest.raises(even_panel_error):
        aggregate(verdicts, crit, favourable_signals())


# --- the policy-application half: M-GRADE's invariants 2 and 3 --------------------------------

_CRITERION_IDS = ("C0", "C1", "C2", "C3", "C4", "C5")

_COMBINATIONS = ("weighted_sum", "best_k_of_n", "drop_lowest_n")
_ROUNDING = ("nearest", "up", "down")

#: Strategy bounds must be exactly representable at the strategy's width — hypothesis
#: refuses e.g. 2**24 + 1 as a float32 bound (InvalidArgument), so every float32 bound
#: here is an integer below 2**24, and no bound is derived by arithmetic from a drawn
#: value (a drawn float32 plus 1.0 is generally not float32-representable).
_SCORE_VALUES = st.floats(min_value=0.0, max_value=1000.0, width=32,
                          allow_nan=False, allow_infinity=False)


@st.composite
def _scores_and_policy(draw) -> tuple:
    """Generated criterion scores (each ≤ its criterion's maximum, both realizable as a
    non-decreasing band table ending at the maximum) and a closed-vocabulary policy."""
    n = draw(st.integers(min_value=2, max_value=6))
    ids = _CRITERION_IDS[:n]
    maxima = draw(st.lists(_SCORE_VALUES, min_size=n, max_size=n))
    deltas = draw(st.lists(_SCORE_VALUES, min_size=n, max_size=n))
    scores = [score(ids[i], "B1", 1, maxima[i] - deltas[i]) for i in range(n)]

    combination = draw(st.sampled_from(_COMBINATIONS))
    policy_kw: dict = {"combination": combination}
    if combination == "weighted_sum":
        # The weighted member of the closed vocabulary, exercised for real: positive
        # weights per criterion (FR-PKG-14's validation refuses zero or negative).
        weights = draw(st.lists(
            st.floats(min_value=0.1, max_value=10.0,
                      allow_nan=False, allow_infinity=False),
            min_size=n, max_size=n))
        policy_kw["weights"] = tuple(zip(ids, weights))
    elif combination == "best_k_of_n":
        policy_kw["k"] = draw(st.integers(min_value=1, max_value=n))
    else:  # drop_lowest_n
        policy_kw["drop"] = draw(st.integers(min_value=1, max_value=n - 1))

    if draw(st.booleans()):
        gated = draw(st.sampled_from(ids))
        # A minimum above the gated criterion's maximum is drawn deliberately: it
        # exercises the gate-unmet limb (the grade does not stand).
        policy_kw["gate"] = GateRule(
            criterion_id=gated,
            minimum=draw(st.floats(min_value=0.0, max_value=1001.0, width=32,
                                   allow_nan=False, allow_infinity=False)),
        )
    if draw(st.booleans()):
        # width 64: 0.1 has no exact float32 representation, so the 32-bit strategy
        # refuses the bound outright (InvalidArgument) — the factor is a plain float.
        policy_kw["scale"] = ScaleRule(factor=draw(
            st.floats(min_value=0.1, max_value=3.0,
                      allow_nan=False, allow_infinity=False)))
    if draw(st.booleans()):
        policy_kw["rounding"] = draw(st.sampled_from(_ROUNDING))
        policy_kw["decimals"] = draw(st.integers(min_value=0, max_value=2))

    return scores, dict(zip(ids, maxima)), GradePolicy(**policy_kw)


@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(_scores_and_policy(), st.data())
def test_fuzz_05_policy_application_is_order_independent_and_totals_never_exceed_the_maximum(
    case, data
):
    """`FUZZ-05` invariants 2 and 3, policy half (`FR-GRADE-02`) — applying the policy to
    the same criteria in a different order gives the same total (order-independence over
    criteria), and no total ever exceeds the policy applied to the all-maxima
    population, which is the maximum achievable under that policy."""
    apply_policy = require(GRADE_MODULE, "apply_policy", issue="#101")
    scores, maxima, policy = case

    shuffled = list(scores)
    data.draw(st.permutations(shuffled))

    # The declared pin: `.total` on the returned computation (module docstring). Read
    # directly — an absent field fails loudly here rather than passing vacuously.
    total = apply_policy(scores, policy).total
    reshuffled_total = apply_policy(shuffled, policy).total

    if total is None:
        # The gate did not stand for this population; a refusal is order-independent
        # too — the other order must refuse identically, never produce a grade.
        assert reshuffled_total is None, (
            f"the same scores in a different order produced a total {reshuffled_total!r} "
            f"where the first order refused — policy application is order-independent "
            "over criteria (FR-GRADE-02, FUZZ-05 invariant 3)"
        )
        return

    assert reshuffled_total == pytest.approx(total, rel=1e-9, abs=1e-9), (
        f"total {total!r} became {reshuffled_total!r} when the same criteria arrived in "
        "a different order — policy application is order-independent over criteria "
        "(FR-GRADE-02, FUZZ-05 invariant 3); a larger gap is an order-dependent formula, "
        "not float noise"
    )

    # The maximum achievable under this policy is the policy applied to the all-maxima
    # population: every score is at its criterion's ceiling, so no rule in the closed
    # vocabulary can score any population above it.
    maximum_scores = [score(cid, "B1", 1, value) for cid, value in maxima.items()]
    maximum_total = apply_policy(maximum_scores, policy).total
    assert maximum_total is not None, (
        "the all-maxima population did not stand under a gate the score population "
        "stood — a gate that excludes the maximum achievable makes the cap vacuous "
        "(declared gate semantics, reconciles at #101)"
    )
    # Plain-tolerance comparison: `pytest.approx` supports only ==/!= — a `<=` against
    # it raises TypeError, which would condemn a correct implementation.
    assert maximum_total - total > -1e-9, (
        f"total {total!r} exceeds the maximum achievable {maximum_total!r} — no policy "
        "application may score a population above what its all-maxima population "
        "achieves (FR-GRADE-02, FUZZ-05 invariant 2)"
    )
