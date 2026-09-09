"""`TC-GRADE-21` — the `apply_policy` invariants over generated populations.

Test plan §5.14 (row form): generated criterion-score sets and closed-vocabulary
policies; `apply_policy` never exceeds the maximum achievable total, never returns a
negative total unless the band table declares negative points, and is order-independent
over criteria. Oracle: invariant. P0. Traces to `FR-GRADE-02`. Written ahead of
**#101**, which lands `aeh.grade`; the applicator is design-declared
(detailed-design.md §3.14, CT-GRADE-02:
`apply_policy(scores, policy) -> GradeComputation`), and `.total` is the one field read
here — the declared pin FUZZ-05's policy half also declares (a float when the grade
stands, `None` when the policy's gate refuses).

Relationship to `FUZZ-05` (§6.7, issue #94), disclosed: FUZZ-05's policy half already
asserts the cap and order-independence invariants over the same generated space, and
TC-GRADE-21's row restates both as its own named case — the overlap is the plan's, not
this suite's invention. What TC-GRADE-21 adds is the **negative-total limb**: over
populations whose band tables declare no negative points, no standing total may ever be
negative. The limb's generator makes the provenance explicit — every generated score's
points are an entry of a generated non-decreasing band table whose every point is >= 0 —
so "the band table declares no negative points" is literally true of the fixture, not an
implicit assumption. The limb's permission side (a negative total is *acceptable* when a
band table *does* declare negatives) is a possibility, not an invariant: no generated
population can guarantee a negative total, so asserting one would over-constrain the
implementation, and the suite asserts only the prohibition the plan states.

**Fixed seed set**: the suite's hypothesis profile is `derandomize=True` (conftest,
§4.6's flake policy) — every run replays the same example set, and a failure reproduces
by re-running the tier.

Isolation: rung 0 — pure functions and generated values; no store, no model.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aeh.pkg import GateRule, GradePolicy, ScaleRule
from tests.support.grade_vocabulary import score
from tests.support.impl import GRADE_MODULE, require
from tests.support.span_strategies import FUZZ_EXAMPLES

pytestmark = pytest.mark.writtenahead

ISSUE = "#101"

_CRITERION_IDS = ("C0", "C1", "C2", "C3", "C4", "C5")

_COMBINATIONS = ("weighted_sum", "best_k_of_n", "drop_lowest_n")
_ROUNDING = ("nearest", "up", "down")

#: Strategy bounds must be exactly representable at the strategy's width — hypothesis
#: refuses e.g. 2**24 + 1 as a float32 bound (InvalidArgument), so every float32 bound
#: here is an integer below 2**24, and no bound is derived by arithmetic from a drawn
#: value (a drawn float32 plus 1.0 is generally not float32-representable).
#: min_value=0.0 is the negative limb's load-bearing bound: every band point >= 0.
_BAND_POINTS = st.floats(min_value=0.0, max_value=1000.0, width=32,
                         allow_nan=False, allow_infinity=False)


@st.composite
def _population_and_policy(draw) -> tuple:
    """A generated criterion-score population plus a closed-vocabulary policy.

    Each criterion contributes a generated band table — non-decreasing, 2 to 6 bands,
    every point >= 0 (the table declares **no negative points**) — and its score is an
    entry of that table (the band M-AGG's median rule would map), so the score is
    necessarily <= the table's ceiling, which is the criterion's maximum."""
    n = draw(st.integers(min_value=2, max_value=6))
    ids = _CRITERION_IDS[:n]

    scores = []
    maxima = {}
    for cid in ids:
        band_count = draw(st.integers(min_value=2, max_value=6))
        table = sorted(draw(st.lists(_BAND_POINTS,
                                     min_size=band_count, max_size=band_count)))
        ordinal = draw(st.integers(min_value=0, max_value=band_count - 1))
        scores.append(score(cid, table[ordinal], band=f"B{ordinal}", ordinal=ordinal))
        maxima[cid] = table[-1]

    combination = draw(st.sampled_from(_COMBINATIONS))
    policy_kw: dict = {"combination": combination}
    if combination == "weighted_sum":
        # The weighted member of the closed vocabulary, exercised for real: positive
        # weights per criterion (FR-PKG-14's validation refuses zero or negative) —
        # a positive weight cannot move the total below zero.
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
        # The factor stays positive: a scale cannot make a non-negative total negative.
        policy_kw["scale"] = ScaleRule(factor=draw(
            st.floats(min_value=0.1, max_value=3.0,
                      allow_nan=False, allow_infinity=False)))
    if draw(st.booleans()):
        policy_kw["rounding"] = draw(st.sampled_from(_ROUNDING))
        policy_kw["decimals"] = draw(st.integers(min_value=0, max_value=2))

    return scores, maxima, GradePolicy(**policy_kw)


@pytest.mark.writtenahead
@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(_population_and_policy(), st.data())
def test_tc_grade_21_totals_never_exceed_the_maximum_go_negative_or_depend_on_order(
    case, data
):
    """`TC-GRADE-21` — over generated populations from non-negative band tables, a
    standing total never exceeds the all-maxima total, never goes negative, and is
    invariant under reordering the criteria."""
    apply_policy = require(GRADE_MODULE, "apply_policy", issue=ISSUE)
    scores, maxima, policy = case

    shuffled = list(scores)
    data.draw(st.permutations(shuffled))

    # The declared pin: `.total` on the returned computation (module docstring). Read
    # directly — an absent field fails loudly here rather than passing vacuously.
    total = apply_policy(scores, policy).total
    reshuffled_total = apply_policy(shuffled, policy).total

    if total is None:
        # The gate refused this population; a refusal is order-independent too — the
        # other order must refuse identically, never produce a grade.
        assert reshuffled_total is None, (
            f"the same scores in a different order produced a total {reshuffled_total!r} "
            f"where the first order refused — policy application is order-independent "
            "over criteria (TC-GRADE-21, FR-GRADE-02)"
        )
        return

    # --- order-independence (invariant 3) ----------------------------------------------------
    assert reshuffled_total == pytest.approx(total, rel=1e-9, abs=1e-9), (
        f"total {total!r} became {reshuffled_total!r} when the same criteria arrived in "
        "a different order — policy application is order-independent over criteria "
        "(TC-GRADE-21, FR-GRADE-02); a larger gap is an order-dependent formula, not "
        "float noise"
    )

    # --- the negative-total limb (TC-GRADE-21's addition) ------------------------------------
    # Every generated band point is >= 0, so every aggregated score is >= 0, and no
    # member of the closed vocabulary — positive weights, positive scale, a best-k or
    # drop-lowest selection over non-negative entries, or any rounding of a
    # non-negative figure — can drive a standing total below zero. (IEEE sums and
    # products of non-negative floats are non-negative, and rounding a non-negative
    # figure downward lands on 0.0 at worst, so a correct implementation satisfies this
    # exactly, without tolerance.)
    assert total >= 0, (
        f"total {total!r} is negative although every band table in the population "
        "declares no negative points — a negative total is legitimate only when a band "
        "table declares negative points (TC-GRADE-21's negative limb, FR-GRADE-02)"
    )

    # --- the cap (invariant 2) ---------------------------------------------------------------
    # The maximum achievable under this policy is the policy applied to the all-maxima
    # population: every score at its band table's ceiling, so no rule in the closed
    # vocabulary can score any population above it.
    maximum_scores = [score(cid, value) for cid, value in maxima.items()]
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
        "achieves (TC-GRADE-21, FR-GRADE-02)"
    )
