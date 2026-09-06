"""The grade policy as a structured object from a closed vocabulary (`M-PKG`).

Cases `TC-PKG-14`, `TC-PKG-15` (`FR-PKG-14`, `FR-PKG-15`), test plan §5.4. Issue #30
(paired with #33/TS-12).

Rung 0 — pure: the vocabulary lives in `GradePolicy.__post_init__`, so a policy
containing a free-text formula, an executable expression or a lambda-shaped string
cannot become an object at all — the strongest form of the refusal, and the one a unit
test can exercise without a database. The storage and read-back halves of the same
requirements are TC-PKG-19's integration cases.

`Written ahead of implementation: yes` is stale — the policy surface landed with #30;
these cases run green by design.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from aeh.pkg import (
    COMBINATION_RULES,
    GateRule,
    GradePolicy,
    GradePolicyError,
    ROUNDING_MODES,
    ScaleRule,
    default_grade_policy,
)

ISSUE = "#30"


# -- TC-PKG-14: closed vocabulary in, everything else refused ------------------------------------


def test_tc_pkg_14_every_closed_vocabulary_member_constructs():
    """`TC-PKG-14` happy half — a policy from the vocabulary constructs: each
    combination rule, plus the gate/scale/rounding members alongside it. The boundary
    table member is `grade_boundary` rows (`FR-PKG-16`), asserted in the integration
    cases — deliberately not a field here, so the rule has one canonical
    representation."""
    weighted = GradePolicy(combination="weighted_sum",
                           weights=(("CRIT-1", 2.0), ("CRIT-2", 1.0)))
    best_k = GradePolicy(combination="best_k_of_n", k=3)
    drop = GradePolicy(combination="drop_lowest_n", drop=1)
    dressed = GradePolicy(
        combination="weighted_sum", weights=(("CRIT-1", 1.0),),
        gate=GateRule("CRIT-1", 1.0), scale=ScaleRule(1.25),
        rounding="nearest", decimals=0,
    )
    for policy in (weighted, best_k, drop, dressed, default_grade_policy()):
        assert policy.combination in COMBINATION_RULES
    assert default_grade_policy() == GradePolicy()


@pytest.mark.parametrize("formula", [
    "score * 0.8 + 5",                       # a free-text formula
    "__import__('os').system('rm -rf /')",   # an executable expression
    "lambda scores: sum(scores)",            # a lambda-shaped string
])
def test_tc_pkg_14_a_formula_cannot_become_a_policy_object(formula):
    """`TC-PKG-14` refusal half — *'one containing a free-text formula; then one
    containing an executable expression; then one containing a lambda-shaped string'*.
    Oracle: exact exception type — `GradePolicyError`, at CONSTRUCTION: the vocabulary
    is closed (`FR-PKG-14`'s ADR — an executable formula in a package is an
    arbitrary-code surface and an un-auditable grade)."""
    with pytest.raises(GradePolicyError):
        GradePolicy(combination=formula)


def test_tc_pkg_14_a_parameter_no_rule_executes_is_refused():
    """`TC-PKG-14`'s vocabulary discipline — a field belonging to a rule that is not
    selected is a latent formula: the object would carry a parameter nothing executes,
    and the next reader would have to guess. Only the selected combination's parameters
    may be present."""
    with pytest.raises(GradePolicyError):
        GradePolicy(combination="weighted_sum", weights=(("C", 1.0),), k=3)
    with pytest.raises(GradePolicyError):
        GradePolicy(combination="weighted_sum", weights=(("C", 1.0),), drop=1)
    with pytest.raises(GradePolicyError):
        GradePolicy(combination="best_k_of_n", k=2, weights=(("C", 1.0),))
    with pytest.raises(GradePolicyError):
        GradePolicy(combination="drop_lowest_n", drop=1, k=2)
    with pytest.raises(GradePolicyError):
        GradePolicy(combination="weighted_sum", weights=(("C", 0.0),))
    with pytest.raises(GradePolicyError):
        GradePolicy(combination="weighted_sum", weights=(("C", -1.0),))
    with pytest.raises(GradePolicyError):
        GradePolicy(combination="best_k_of_n", k=0)
    with pytest.raises(GradePolicyError):
        GradePolicy(combination="drop_lowest_n", drop=0)
    with pytest.raises(GradePolicyError):
        GradePolicy(rounding="nearest")  # decimals missing: a half-declared rule
    with pytest.raises(GradePolicyError):
        GradePolicy(decimals=2)  # decimals without a rounding mode
    with pytest.raises(GradePolicyError):
        GradePolicy(combination="weighted_sum", weights=(("C", 1.0),),
                    rounding="truncate", decimals=0)
    with pytest.raises(GradePolicyError):
        GradePolicy(combination="weighted_sum", weights=(("C", 1.0),),
                    gate=GateRule("", 1.0))
    with pytest.raises(GradePolicyError):
        GradePolicy(combination="weighted_sum", weights=(("C", 1.0),),
                    gate=GateRule("C", -1.0))
    with pytest.raises(GradePolicyError):
        GradePolicy(combination="weighted_sum", weights=(("C", 1.0),),
                    scale=ScaleRule(0.0))


# -- TC-PKG-15: plain_language is generated, never independent input -----------------------------


def _sample_policy() -> GradePolicy:
    return GradePolicy(
        combination="weighted_sum", weights=(("CRIT-1", 2.0), ("MCQ-1", 1.0)),
        gate=GateRule("MCQ-1", 1.0), scale=ScaleRule(1.25),
        rounding="nearest", decimals=0, review_window_hours=24,
    )


def test_tc_pkg_15_plain_language_is_generated_from_the_object():
    """`TC-PKG-15` — *'plain_language is generated from the object'* — every clause of
    the wording names a field's rule, and the default policy's wording is the
    FR-SETUP-12 default read aloud."""
    wording = _sample_policy().plain_language
    assert "Weighted sum" in wording and "CRIT-1 x2" in wording
    assert "Gate: MCQ-1" in wording
    assert "scaled by 1.25" in wording
    assert "Rounded" in wording
    assert "Review window: 24 hour(s)" in wording
    default = default_grade_policy().plain_language
    assert "Sum of criterion points" in default
    assert "Finalizes on run completion." in default
    dropped = GradePolicy(combination="drop_lowest_n", drop=2).plain_language
    assert "lowest 2" in dropped
    best = GradePolicy(combination="best_k_of_n", k=3).plain_language
    assert "Best 3" in best
    null_window = GradePolicy(review_window_hours=None).plain_language
    assert "Finalizes on run completion." in null_window


def test_tc_pkg_15_regeneration_is_byte_stable_and_survives_the_stored_form():
    """`TC-PKG-15` — *'regenerating from the same object is byte-stable'* — twice from
    the object, and again from the object rebuilt through its stored (JSON) form: the
    approved wording is a pure function of the executed policy."""
    policy = _sample_policy()
    assert policy.plain_language == policy.plain_language
    # The stored form is the JSON plus the window's own column (ADR-3) — rebuild exactly
    # the way `grade_policy()` reads it back:
    stored = json.loads(json.dumps(policy.to_dict()))
    rebuilt = GradePolicy.from_dict(
        {**stored, "review_window_hours": policy.review_window_hours})
    assert rebuilt == policy
    assert rebuilt.plain_language == policy.plain_language


def test_tc_pkg_15_independent_wording_cannot_enter_through_any_api():
    """`TC-PKG-15` — *'supplying it as independent input is not possible through any
    API'* — three doors, all closed: not a constructor field, not assignable (frozen),
    and not part of the stored form (so no second, diverging copy exists anywhere)."""
    with pytest.raises(TypeError):
        GradePolicy(plain_language="An A is excellent.")  # type: ignore[call-arg]
    with pytest.raises(dataclasses.FrozenInstanceError):
        _sample_policy().plain_language = "An A is excellent."
    assert "plain_language" not in _sample_policy().to_dict()
