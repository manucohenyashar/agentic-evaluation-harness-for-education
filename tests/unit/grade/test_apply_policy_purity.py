"""`TC-GRADE-19` — `apply_policy` is pure and deterministic; no model call anywhere in
grade computation.

Test plan §5.14; `NFR-GRADE-01` ("apply_policy pure no model call", design §3.14's
*Pure. Deterministic. Unit-testable, not a model property*); Artifact assertion / 0;
P0. The three limbs:

1. **Determinism** — identical inputs give an identical `GradeComputation` (frozen
   dataclass equality on a double call), swept across the closed rule vocabulary:
   the plain sum, weighted sum, best-k, drop-lowest, the gate's met and refused
   verdicts, scale and half-up rounding. A drift in any rule reorders work, reads the
   clock, or seeds a draw — determinism is the property that catches all three.
2. **Purity of the inputs** — the call consumes the score population without mutating
   it: the same list is intact afterwards (the `score()` stand-ins are mutable
   namespaces, so a mutating applicator would show), and the result is a fresh frozen
   record, never an alias of an input row.
3. **No model call, asserted with the socket guard** — the autouse `SocketGuard`
   records every connection attempt across the whole file; `assert_no_network()` is
   called after the pure-seam sweeps. A grading computation that phoned a judge would
   pass every value assertion and fail here — the guard is the oracle for the
   *anywhere*, not just for `apply_policy` itself.

The structural complement (a grade module that kept a transport parameter would have a
model call *available* even if none fired) is pinned too: the module's public surface
carries no transport/provider/model-call seam — the deterministic transport is
`M-ORCH`'s, and `CT-PROV-15` keeps it the only egress point.

Cross-referenced, not duplicated: the rules' hand-computed values are `TC-GRADE-02`'s
and `TC-GRADE-03`'s (`test_policy_rules.py`), the coverage/boundary/band seams are
`TC-GRADE-04..06`'s (`test_boundaries_and_coverage.py`), the order-independence and
bounds invariants are `TC-GRADE-21`'s property (`tests/property/
test_tc_grade_21_apply_policy_invariants.py`). This file pins none of those values —
only the purity contract that no other case owns.

**Isolation: rung 0** — the module-level pure seams only; no store, no doubles.
"""

from __future__ import annotations

import pytest

from aeh.grade import apply_policy
from aeh.pkg import GateRule, GradePolicy, ScaleRule
from tests.support.grade_vocabulary import score

ISSUE = "#106"


def _population():
    """Two auto-settled scores — the minimal population every rule can consume."""
    return [score("C1", 7.0, band="B2"), score("C2", 6.0)]


def _rule_policies():
    """One policy per closed-vocabulary member, the same set TC-GRADE-02 sweeps —
    determinism is asserted over the whole vocabulary, not one happy path."""
    return [
        GradePolicy(combination="weighted_sum"),
        GradePolicy(combination="weighted_sum",
                    weights=(("C1", 2.0), ("C2", 1.0))),
        GradePolicy(combination="best_k_of_n", k=1),
        GradePolicy(combination="drop_lowest_n", drop=1),
        GradePolicy(combination="weighted_sum",
                    gate=GateRule(criterion_id="C1", minimum=7.0)),
        GradePolicy(combination="weighted_sum",
                    gate=GateRule(criterion_id="C1", minimum=8.0)),
        GradePolicy(combination="weighted_sum", scale=ScaleRule(factor=0.5)),
        GradePolicy(combination="weighted_sum", rounding="nearest", decimals=0),
    ]


def test_tc_grade_19_apply_policy_is_deterministic_across_the_rule_vocabulary(
    network_guard,
):
    """`TC-GRADE-19`, limb 1 — the same (population, policy) pair gives the same
    `GradeComputation`, member by member of the closed rule vocabulary."""
    for policy in _rule_policies():
        first = apply_policy(_population(), policy)
        second = apply_policy(_population(), policy)
        assert first == second, (
            f"{policy.combination!r} returned different outcomes for identical "
            f"inputs ({first!r} then {second!r}) — NFR-GRADE-01's determinism "
            "contract is broken; a rule that reads the clock, seeds a draw or "
            "reorders a set drifts here and only here"
        )
    network_guard.assert_no_network()


def test_tc_grade_19_apply_policy_consumes_its_inputs_without_mutation(network_guard):
    """`TC-GRADE-19`, limb 2 — the score population is intact after the call, and the
    result is a fresh frozen record, not an alias of an input row."""
    population = _population()
    snapshot = [(s.criterion_id, s.points, s.band, s.routing) for s in population]

    first = apply_policy(population, GradePolicy(combination="weighted_sum"))
    after = [(s.criterion_id, s.points, s.band, s.routing) for s in population]

    assert after == snapshot, (
        "apply_policy mutated its input population — a pure applicator consumes the "
        "scores read-only (NFR-GRADE-01); a mutation would poison the caller's next "
        "recomputation and break NFR-GRADE-02's exact recomputability"
    )
    assert first == apply_policy(population, GradePolicy(combination="weighted_sum")), (
        "the second call over the same list disagreed with the first — the input was "
        "changed by being consumed"
    )
    assert type(first).__name__ == "GradeComputation" and first.total == 13.0, (
        f"the result is {first!r} — expected a fresh GradeComputation with total 13.0 "
        "(the plain sum; the values are TC-GRADE-02's, not re-pinned here)"
    )
    network_guard.assert_no_network()


def test_tc_grade_19_the_grade_module_carries_no_model_call_seam(network_guard):
    """`TC-GRADE-19`, the *anywhere* limb — the grade computation's pure seams all run
    clean under the socket guard, and the module's public surface carries no transport
    or provider seam a model call could ride: the deterministic transport is M-ORCH's
    (`CT-PROV-15`), and a second egress point in the grading module would be an
    unauditable one."""
    import aeh.grade as grade_module

    from tests.support.impl import GRADE_MODULE, require

    # Every pure seam the computation composes runs under the guard, back to back.
    apply_policy, resolve_grade, boundary_risk = require(
        GRADE_MODULE, "apply_policy", "resolve_grade", "boundary_risk", issue=ISSUE
    )
    apply_policy(_population(), GradePolicy(combination="weighted_sum"))
    resolve_grade(13.0, None)
    boundary_risk(13.0, [(0.0, 2.0)], None)
    network_guard.assert_no_network()

    forbidden = ("transport", "provider", "model", "judge", "client", "llm")
    public = [
        name for name in dir(grade_module)
        if not name.startswith("_")
    ]
    offenders = [
        name for name in public
        if any(token in name.lower() for token in forbidden)
    ]
    assert not offenders, (
        f"aeh.grade exposes model-call surfaces {offenders!r} — the grading module's "
        "computation is pure (NFR-GRADE-01) and the transport is M-ORCH's alone "
        "(CT-PROV-15); a seam here is a model call waiting for a caller"
    )