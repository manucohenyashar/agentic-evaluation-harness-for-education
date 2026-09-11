"""`TC-GRADE-C02` — `apply_policy` is pure, deterministic, model-free arithmetic (§6.11.14).

`CT-GRADE-02` (surface): "`apply_policy` is a pure function over the score values and
the policy — deterministic, no model call, no state." The clause's claim is that grade
computation is *arithmetic, not a model property*, and arithmetic can be enumerated:
the case sweeps the closed rule vocabulary — weighted sum (bare and weighted), best-k
(including ties), drop-lowest, the gate (met, refused, and refused by ABSENCE — a
criterion with no row refuses the gate: absence is not a zero), scale, and all three
rounding modes — against hand-computed expected values, including the cases a
floating-point implementation gets wrong: rounding at exactly .5 (HALF-UP, not
Python's half-even `round`), the gate met exactly on its minimum, and accumulation
order across many criteria (`math.fsum`'s exactly-rounded sum is order-independent,
so the same figures read the same total in every order).

The no-model-call limb is asserted with the session's socket guard: the sweep runs
entirely inside the guard, and `assert_no_network()` confirms not even an egress
attempt was made — a model call in the grade path is the failure the clause exists
to forbid (`CT-PROV-15`'s single-egress-point rule at the grade seam).

Isolation: rung 0 — pure functions over value objects, no store, no model.
"""

from __future__ import annotations

import math
import random
from types import SimpleNamespace

import pytest

from aeh.grade import apply_policy
from aeh.pkg import GradePolicy, GateRule, default_grade_policy
from tests.support.grade_vocabulary import score
from tests.support.impl import GRADE_MODULE, require

pytestmark = [pytest.mark.contract]


def test_tc_grade_c02_the_closed_rule_vocabulary_matches_hand_computed_values():
    """`TC-GRADE-C02` (`CT-GRADE-02`, rung 0) — every vocabulary member against a
    hand-computed value. Each expected figure is written as the arithmetic the
    policy names, so a computation that drifts from arithmetic — a model call, a
    hidden transform, a rounding shortcut — fails against the exact number."""
    require(GRADE_MODULE, "apply_policy", issue="#101")
    base = [score("C1", 7.0), score("C2", 2.0), score("C3", 3.0)]
    cases = [
        # weighted sum, bare: the default policy is the plain sum of points.
        ("bare weighted sum", default_grade_policy(),
         [score("C1", 7.0), score("C2", 2.0), score("C3", 3.0)], 12.0),
        # weighted sum with weights: the unweighted criteria default to 1.0.
        ("weighted sum", GradePolicy(weights=(("C1", 2.0),)),
         [score("C1", 7.0), score("C2", 2.0), score("C3", 3.0)], 19.0),
        # best-k-of-n: the k greatest figures count; ties break by criterion id,
        # so the selected SET is deterministic.
        ("best k of n", GradePolicy(combination="best_k_of_n", k=2),
         [score("C1", 7.0), score("C2", 2.0), score("C3", 3.0)], 10.0),
        ("best k of n over ties", GradePolicy(combination="best_k_of_n", k=1),
         [score("C1", 5.0), score("C2", 5.0), score("C3", 5.0)], 5.0),
        # drop-lowest-n: the n lowest figures are dropped before summing.
        ("drop lowest", GradePolicy(combination="drop_lowest_n", drop=1),
         [score("C1", 7.0), score("C2", 2.0), score("C3", 3.0)], 10.0),
        ("drop two", GradePolicy(combination="drop_lowest_n", drop=2),
         [score("C1", 7.0), score("C2", 2.0), score("C3", 3.0)], 7.0),
        # scale: the combined total multiplied, after combination.
        ("scaled", GradePolicy(scale=SimpleNamespace(factor=1.5)),
         [score("C1", 7.0), score("C2", 2.0), score("C3", 3.0)], 18.0),
        # rounding at exactly .5: HALF-UP, not Python's half-even round().
        ("half-up rounding", GradePolicy(rounding="nearest", decimals=0),
         [score("C1", 1.2), score("C2", 1.3)], 3.0),
        ("round up", GradePolicy(rounding="up", decimals=0),
         [score("C1", 1.2), score("C2", 0.9)], 3.0),
        ("round down", GradePolicy(rounding="down", decimals=0),
         [score("C1", 1.2), score("C2", 1.7)], 2.0),
        ("decimals 2, half-up at the quantum",
         GradePolicy(rounding="nearest", decimals=2),
         [score("C1", 1.004), score("C2", 0.001)], 1.01),
    ]
    for label, policy, scores, expected in cases:
        computation = apply_policy(scores, policy)
        assert computation.total == expected, (
            f"{label}: total {computation.total!r} != hand-computed {expected!r} — "
            "the rule vocabulary must execute exactly its declared arithmetic "
            "(CT-GRADE-02: arithmetic, not a model property)"
        )

    # The gate limbs: met exactly on the minimum, refused below it, and refused by
    # ABSENCE — a criterion with no row refuses the gate; absence is not a zero.
    met = apply_policy(
        [score("C1", 5.0), score("C2", 2.0)],
        GradePolicy(gate=GateRule(criterion_id="C1", minimum=5.0)),
    )
    assert met.gate_met and met.total == 7.0, (
        "a gate met exactly on its minimum refused — the minimum is inclusive "
        f"(gate_met={met.gate_met}, total={met.total!r}; CT-GRADE-02's exact-boundary)"
    )
    refused = apply_policy(
        [score("C1", 2.0), score("C2", 7.0)],
        GradePolicy(gate=GateRule(criterion_id="C1", minimum=5.0)),
    )
    assert refused.total is None and not refused.gate_met, (
        "a refused gate yielded total "
        f"{refused.total!r} (gate_met={refused.gate_met}) — the refusal is a None "
        "total, never an exception and never the ungated sum (CT-GRADE-02)"
    )
    absent = apply_policy(
        [score("C3", 7.0)],
        GradePolicy(gate=GateRule(criterion_id="C1", minimum=0.0)),
    )
    assert absent.total is None and not absent.gate_met, (
        "a gate on an absent criterion passed — absence is not a zero; a missing "
        "gate input refuses rather than contributing a substituted 0 "
        f"(total={absent.total!r}, CT-GRADE-02 with CT-GRADE-07)"
    )

    # The breaker-refused surface: the criterion's own figure still counts, and the
    # result names it — the presentation the consumer differential (CT-AGG-C07's
    # m_grade param) stands on.
    refused_panel = apply_policy(
        [
            score("C1", 7.0),
            SimpleNamespace(criterion_id="C2", band="B3", ordinal=1, points=4.0,
                            routing="provisional", state="ungradeable_by_panel"),
        ],
        default_grade_policy(),
    )
    assert refused_panel.total == 11.0, (
        f"the breaker-refused figure was not counted ({refused_panel.total!r}) — "
        "CT-ORCH-16 leaves it scored (CT-GRADE-02's panel_refused limb)"
    )
    assert refused_panel.panel_refused == ("C2",), (
        f"panel_refused is {refused_panel.panel_refused!r} — the result must name the "
        "breaker-refused criteria (CT-AGG-07's surface obligation)"
    )


def test_tc_grade_c02_deterministic_order_independent_pure_and_model_free(
    network_guard,
):
    """`TC-GRADE-C02` (`CT-GRADE-02`, rung 0) — the purity clauses: the same inputs
    give the same output (determinism), the inputs in any order give the same total
    (`math.fsum`'s exactly-rounded accumulation — order-independent where naive
    floating-point addition is not), the inputs are not mutated (purity), and the
    whole path makes no network call (no model call; the guard blocks and this
    asserts nothing even attempted one)."""
    require(GRADE_MODULE, "apply_policy", issue="#101")
    policy = GradePolicy(weights=(("C1", 2.0), ("C2", 0.5)),
                         rounding="nearest", decimals=3)

    # Twenty criteria, weights and point values with fractional bits — the
    # accumulation-order sweep's material.
    ids = [f"C{i:02d}" for i in range(1, 21)]
    values = {cid: 0.1 * (i % 7) + i * 0.37 for i, cid in enumerate(ids, start=1)}
    weights = {cid: 1.0 + (i % 5) * 0.25 for i, cid in enumerate(ids, start=1)}
    scores = [
        score(cid, values[cid])
        for cid in ids
    ]

    def compute(order):
        weighted = GradePolicy(
            weights=tuple((cid, weights[cid]) for cid in ids),
            rounding="nearest", decimals=3,
        )
        return apply_policy([score(cid, values[cid]) for cid in order], weighted)

    # Determinism: the same order twice, identical figure.
    first = compute(ids)
    second = compute(ids)
    assert first.total == second.total, (
        f"the same inputs produced {first.total!r} and {second.total!r} — grade "
        "computation must be deterministic (CT-GRADE-02)"
    )
    # Accumulation order: three shuffled orders, one total — fsum's contract.
    orders = list(ids)
    for seed in (7, 11, 13):
        shuffled = list(ids)
        random.Random(seed).shuffle(shuffled)
        assert compute(shuffled).total == first.total, (
            f"order {seed} produced a different total — the sum must be "
            "order-independent (math.fsum's exactly-rounded accumulation; the "
            "naive float sum is not, which is the bug this limb exists to catch)"
        )
    # The accumulation-order limb's teeth, made exact: a magnitude-spread fixture
    # where NAIVE left-to-right addition is order-dependent — after the 1e16 term
    # the unit contributions vanish below the ulp, so big-first reads 1e16 while
    # smalls-first reads 1e16+2. `math.fsum` is exactly rounded, so every order
    # reads the exact sum; a naive accumulation fails this differential.
    wide = [score("C-big", 1e16), score("C-a", 1.0), score("C-b", 1.0)]
    wide_totals = {
        apply_policy(list(order), default_grade_policy()).total
        for order in (wide, list(reversed(wide)), [wide[1], wide[2], wide[0]])
    }
    assert wide_totals == {1e16 + 2.0}, (
        f"the wide-magnitude orders read {sorted(wide_totals)!r} — the total must be "
        "the exactly-rounded sum in every order (math.fsum; CT-GRADE-02's "
        "accumulation-order clause, TC-GRADE-21's permutation limb)"
    )
    # Purity: the input list is not mutated by the call.
    before = [(s.criterion_id, s.points) for s in scores]
    apply_policy(scores, policy)
    assert [(s.criterion_id, s.points) for s in scores] == before, (
        "apply_policy mutated its input score list — the pure applicator reads, it "
        "never writes (CT-GRADE-02's purity clause)"
    )
    # The no-model-call limb: nothing tried to leave the machine.
    network_guard.assert_no_network()
