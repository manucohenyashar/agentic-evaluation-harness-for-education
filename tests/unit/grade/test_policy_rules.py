"""`TC-GRADE-02` and `TC-GRADE-03` — the closed rule vocabulary, applied and asserted.

Test plan §5.14; `FR-GRADE-02`. Rung 0: pure functions over hand-computed values, no
store, no model. The policy objects are **shipped** code (`aeh.pkg.GradePolicy`, the
closed vocabulary FR-PKG-14 validates at construction); the applicator is written ahead
of **#101** — design §3.14 declares `apply_policy(scores, policy) -> GradeComputation`
(CT-GRADE-02) and `GradeComputation`'s field set is not pinned, so `.total` is read
directly, the same declared pin FUZZ-05's policy half uses (a float when the grade
stands, `None` when the policy's gate refuses — never an exception).

TC-GRADE-02 exercises each closed-vocabulary rule against a hand-computed expectation.
TC-GRADE-03 pins the boundary readings the case says must not stay implicit, and finds
two that the design does leave implicit (both disclosed on the #105 PR):

- **Rounding at exactly .5**: `ROUNDING_MODES` declares `nearest` without saying
  half-up or half-even. Pinned here to **half-up** — 2.5 -> 3.0 and 3.5 -> 4.0, the pair
  that discriminates half-up from half-even (half-even gives 2.0 and 4.0). An
  implementer reaching for Python's `round()` (half-even) fails this case visibly rather
  than shipping a silent school-hostile convention.
- **A gate exactly at its threshold**: `GateRule`'s own docstring says the criterion
  "must reach `minimum`" — pinned here as **inclusive** (a score of exactly the minimum
  stands). The design never says inclusive vs exclusive; the pinned reading reconciles
  at #101.
- **Best-k ties**: with tied points at the cut, any tie-break order picks one of two
  equal scores, so the total is invariant — asserted as exactness under permutation
  rather than as an order, with the observation recorded here.

`policy_version` recorded on every grade is TC-GRADE-02's second oracle limb and is
asserted where a grade is actually persisted, at rung 2
(`tests/integration/grade/test_grade_delivery.py`); this file is the hand-computed
reference the case names.

Isolation: rung 0.
"""

from __future__ import annotations

import pytest

from aeh.pkg import GateRule, GradePolicy, ScaleRule
from tests.support.grade_vocabulary import GRADE_BLOCKER, score
from tests.support.impl import GRADE_MODULE, require

ISSUE = GRADE_BLOCKER


# --- TC-GRADE-02: every closed-vocabulary rule, hand-computed -------------------------------


@pytest.mark.parametrize(
    ("policy", "points_by_criterion", "expected"),
    [
        # Weighted sum, weights declared: 10 x 2.0 + 8 x 1.0 = 28.0.
        (
            GradePolicy(combination="weighted_sum",
                        weights=(("C1", 2.0), ("C2", 1.0))),
            {"C1": 10.0, "C2": 8.0},
            28.0,
        ),
        # Weighted sum, no weights = the plain sum: 10 + 8 + 7 = 25.0.
        (
            GradePolicy(combination="weighted_sum"),
            {"C1": 10.0, "C2": 8.0, "C3": 7.0},
            25.0,
        ),
        # Best-k-of-n, k=2 of 3: the two highest, 10 + 8 = 18.0 — 7 is excluded, not
        # averaged in.
        (
            GradePolicy(combination="best_k_of_n", k=2),
            {"C1": 10.0, "C2": 8.0, "C3": 7.0},
            18.0,
        ),
        # Drop-lowest-n, drop=1 of 3: 10 + 8 = 18.0 — the lowest is dropped before
        # summing, not scored as zero.
        (
            GradePolicy(combination="drop_lowest_n", drop=1),
            {"C1": 10.0, "C2": 8.0, "C3": 7.0},
            18.0,
        ),
        # The gate met: the total stands. C1 = 6.0 reaches the minimum of 6.0.
        (
            GradePolicy(combination="weighted_sum", gate=GateRule("C1", 6.0)),
            {"C1": 6.0, "C2": 8.0},
            14.0,
        ),
        # The gate unmet: the grade does not stand — a None total, never an exception
        # and never the ungated sum (the declared pin, FUZZ-05's docstring).
        (
            GradePolicy(combination="weighted_sum", gate=GateRule("C1", 6.0)),
            {"C1": 5.5, "C2": 8.0},
            None,
        ),
        # Scale: the raw total 25.0 multiplied by 2.0.
        (
            GradePolicy(combination="weighted_sum", scale=ScaleRule(factor=2.0)),
            {"C1": 10.0, "C2": 8.0, "C3": 7.0},
            50.0,
        ),
        # Rounding, each mode at decimals=0, on raw totals no half-rule can confuse:
        # nearest rounds 2.4 down; up rounds 2.1 up to the integer; down rounds 2.9
        # down. None of 2.4 / 2.1 / 2.9 is a .5 value, so the exactly-.5 rule the next
        # case owns cannot interfere with any of these three.
        (
            GradePolicy(combination="weighted_sum", rounding="nearest", decimals=0),
            {"C1": 1.4, "C2": 1.0},
            2.0,
        ),
        (
            GradePolicy(combination="weighted_sum", rounding="up", decimals=0),
            {"C1": 1.1, "C2": 1.0},
            3.0,
        ),
        (
            GradePolicy(combination="weighted_sum", rounding="down", decimals=0),
            {"C1": 1.9, "C2": 1.0},
            2.0,
        ),
    ],
    ids=[
        "weighted_sum-with-weights",
        "weighted_sum-plain-sum",
        "best_k_of_n",
        "drop_lowest_n",
        "gate-met",
        "gate-unmet",
        "scale",
        "rounding-nearest",
        "rounding-up",
        "rounding-down",
    ],
)
def test_tc_grade_02_each_closed_vocabulary_rule_matches_its_hand_computed_value(
    policy, points_by_criterion, expected
):
    """`TC-GRADE-02` — every member of the closed rule vocabulary produces the
    hand-computed total, exactly."""
    apply_policy = require(GRADE_MODULE, "apply_policy", issue=ISSUE)

    scores = [score(cid, pts) for cid, pts in points_by_criterion.items()]

    computation = apply_policy(scores, policy)

    total = computation.total  # the declared pin: see the module docstring
    if expected is None:
        assert total is None, (
            f"the gate refused this population and the computation still returned "
            f"{total!r} — a gate refusal is a None total, never a computed figure "
            "(FR-GRADE-02's optional gate, CT-GRADE-02)"
        )
    else:
        assert total == pytest.approx(expected, abs=1e-9), (
            f"the {policy.combination} rule returned {total!r} where the hand-computed "
            f"value is {expected!r} — the declared rule was not the rule applied "
            "(FR-GRADE-02)"
        )


# --- TC-GRADE-03: the boundaries the plan refuses to leave implicit --------------------------


@pytest.mark.parametrize(
    ("points_by_criterion", "expected"),
    [
        # 1.5 + 1.0 = 2.5: half-up rounds to 3.0. Half-even would give 2.0.
        ({"C1": 1.5, "C2": 1.0}, 3.0),
        # 1.5 + 2.0 = 3.5: half-up rounds to 4.0. Together the pair pins half-up —
        # half-even agrees on only one of the two.
        ({"C1": 1.5, "C2": 2.0}, 4.0),
    ],
    ids=["half-up-below", "half-up-above"],
)
def test_tc_grade_03_rounding_at_exactly_point_five_is_half_up(
    points_by_criterion, expected
):
    """`TC-GRADE-03` — `nearest` at exactly .5 rounds half-up, in both directions.

    The design declares `nearest` but not its .5 rule; this pin is the finding, and
    either limb failing names the convention the implementer actually shipped."""
    apply_policy = require(GRADE_MODULE, "apply_policy", issue=ISSUE)

    policy = GradePolicy(combination="weighted_sum", rounding="nearest", decimals=0)
    scores = [score(cid, pts) for cid, pts in points_by_criterion.items()]

    total = apply_policy(scores, policy).total

    assert total == pytest.approx(expected, abs=1e-9), (
        f"nearest at exactly .5 returned {total!r}, expected {expected!r} — half-up is "
        "the pinned reading (test plan TC-GRADE-03: rounding at exactly .5 must not "
        "stay implicit); half-even agrees with half-up on the above limb (4.0 is even) "
        "and would return 2.0 for the below limb (2.5 → 2.0), so the below limb is "
        "the discriminator between the two conventions"
    )


def test_tc_grade_03_a_gate_exactly_at_its_threshold_is_inclusive():
    """`TC-GRADE-03` — a gate whose criterion scores exactly the minimum stands.

    `GateRule`'s docstring says "must reach `minimum`", which reads inclusive; the case
    forbids leaving it implicit, so the boundary score is asserted to stand and one
    notch below to refuse."""
    apply_policy = require(GRADE_MODULE, "apply_policy", issue=ISSUE)

    policy = GradePolicy(combination="weighted_sum", gate=GateRule("C1", 6.0))

    at_threshold = apply_policy([score("C1", 6.0), score("C2", 8.0)], policy).total
    below_threshold = apply_policy([score("C1", 5.5), score("C2", 8.0)], policy).total

    assert at_threshold == pytest.approx(14.0, abs=1e-9), (
        f"a criterion scoring exactly the gate minimum produced {at_threshold!r} — the "
        "pinned reading is inclusive (reach = >=), so the grade stands at 14.0 "
        "(TC-GRADE-03: a gate exactly at its threshold is not left implicit)"
    )
    assert below_threshold is None, (
        f"below the minimum the computation returned {below_threshold!r} — the gate "
        "must refuse below its threshold (the inclusive reading's other limb)"
    )


@pytest.mark.parametrize(
    "points_in_order",
    [
        {"C1": 5.0, "C2": 5.0, "C3": 1.0},
        {"C1": 5.0, "C2": 1.0, "C3": 5.0},
        {"C1": 1.0, "C2": 5.0, "C3": 5.0},
    ],
    ids=["order-a", "order-b", "order-c"],
)
def test_tc_grade_03_best_k_ties_total_invariantly_across_orders(points_in_order):
    """`TC-GRADE-03` — best-k with several scores tied at the cut: the total is exact
    and identical under every arrival order.

    With tied points any tie-break order picks one of two equal scores, so no order can
    change the total — the assertion is exactness under permutation. (The design leaves
    tie-break order implicit; under this vocabulary member the implicitness is
    unobservable at the total, which is recorded here as the case's finding.)"""
    apply_policy = require(GRADE_MODULE, "apply_policy", issue=ISSUE)

    policy = GradePolicy(combination="best_k_of_n", k=2)
    scores = [score(cid, pts) for cid, pts in points_in_order.items()]

    total = apply_policy(scores, policy).total

    assert total == pytest.approx(10.0, abs=1e-9), (
        f"best-2-of-3 over tied scores {points_in_order} returned {total!r} — the two "
        "tied 5.0 scores are the best k either way, so the total is 10.0 in every "
        "order (TC-GRADE-03: several scores tie)"
    )
