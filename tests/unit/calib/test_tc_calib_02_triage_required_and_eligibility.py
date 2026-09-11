"""`TC-CALIB-02` — triage refuses to proceed without a category, and the set stays closed.

Test plan §5.17, `TC-CALIB-02` (FR-CALIB-02, Unit / rung 0).

The contract suite carries the refusal (`TC-CALIB-C04`: `triage()` raises
`TriageCategoryRequired` for a `category=None` disagreement, and the three-category
eligibility sweep). What no green test carried before this file is the rest of what the plan
case names, and what #139's carry-forward comment flagged:

* **the two refusals are different exceptions for different mistakes** — a *blank* category
  (the disagreement arrived still uncategorized) is a calibration-domain failure and raises
  `TriageCategoryRequired` (a `CalibrationError`); an *out-of-set* category is a caller defect
  and raises a plain `ValueError`. A catch-all that made both `CalibrationError` would let a
  caller's typo be handled like a missing judgement; a test asserting the domain error only
  would let the closed set open silently.
* **the verdict value is unconstructible without a category** — `triage()`'s refusal is one
  door; `TriageVerdict` itself refusing to exist without a category is the structural half, and
  the one that survives a caller constructing the value directly (design §3.17 tells consumers
  to construct literals rather than doubles).
* **`aeh.calib.TRIAGE_CATEGORIES` is pinned to the vocabulary fixture** — the register gap #119
  left behind: nothing green tied the module's set to `tests/support/calib_vocabulary.py`'s,
  so a fourth category added to the module would open the eligibility sweep's domain without
  anything going red.
* **`rubric_ambiguity` arrives with `proposed_edit` None even at triage** — eligibility is not
  authorship: the edit is generated from the teacher's answer during elicitation (#138), and a
  model-authored edit at triage is the fitting CT-CALIB-05 exists to prevent, one step early.
"""

from __future__ import annotations

import pytest

from tests.support.impl import CALIB_MODULE, require
from tests.support import calib_vocabulary


# --- the required category, twice over ------------------------------------------------------------


def test_tc_calib_02_a_blank_category_and_an_out_of_set_category_are_different_refusals():
    """Blank → `TriageCategoryRequired` (a `CalibrationError`); out-of-set → plain `ValueError`.

    The distinction is the case, asserted at **both** boundaries. At `triage()` the blank shape
    is the one a discovery-produced disagreement arrives in (`category=None`); at the
    constructor it is every falsy spelling, because a `TriageVerdict` that exists with an empty
    category has defaulted into some path by existing.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(
        CALIB_MODULE, "triage", "TriageVerdict", "Disagreement",
        "TriageCategoryRequired", "EditNotEligible",
        issue="#140",
    )

    # At the triage boundary: uncategorized, and the refusal is domain-typed.
    uncategorized = calib.Disagreement(criterion_id="c1", category=None)
    with pytest.raises(calib.TriageCategoryRequired) as exc:
        calib.triage(uncategorized)
    assert isinstance(exc.value, calib.CalibrationError), (
        "a blank category raised an exception outside the calibration hierarchy; every "
        "refusal on this path is a CalibrationError so the gate handlers catch it "
        "(TC-CALIB-11 of #139's carry-forward names the same shape for the gates)"
    )

    # At the value's own constructor: unconstructible without a category — the structural
    # half, which survives a caller building the value directly rather than through triage().
    for blank in (None, "", "   "):
        with pytest.raises(calib.TriageCategoryRequired):
            calib.TriageVerdict(criterion_id="c1", category=blank)

    # The out-of-set shape is a *caller defect*, and the exception says so: a plain
    # ValueError, deliberately NOT a CalibrationError — one is "the finding arrived
    # uncategorized", the other is "the caller named a category that does not exist".
    for bad in ("accuracy_defect", "extraction_defect"):
        with pytest.raises(ValueError) as value_exc:
            calib.triage(
                calib.Disagreement(criterion_id="c1", category=bad)
            )
        assert not isinstance(value_exc.value, calib.CalibrationError), (
            f"an out-of-set category {bad!r} raised a CalibrationError; the closed-set "
            "refusal is a programming error (ValueError) and the blank-category refusal is "
            "the domain error — conflating them lets a caller's typo be handled like a "
            "missing triage"
        )
        with pytest.raises(ValueError):
            calib.TriageVerdict(criterion_id="c1", category=bad)


def test_tc_calib_02_the_module_s_categories_are_the_vocabulary_fixtures():
    """The #119 register's one-assertion add: `aeh.calib.TRIAGE_CATEGORIES` equals the fixture's.

    `TC-CALIB-C04`'s eligibility sweep parametrizes over the **fixture's** set, so a fourth
    category added to `aeh.calib` alone would open a path the sweep never saw — the domain
    sweep would stay green over the old three. Pinning module to fixture here makes the drift
    a red test instead of an open category.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "TRIAGE_CATEGORIES", issue="#140")

    assert calib.TRIAGE_CATEGORIES == calib_vocabulary.TRIAGE_CATEGORIES, (
        f"aeh.calib.TRIAGE_CATEGORIES is {sorted(calib.TRIAGE_CATEGORIES)}; the vocabulary "
        f"fixture carries {sorted(calib_vocabulary.TRIAGE_CATEGORIES)}. CT-CALIB-04's set is "
        "closed, and the fixture is what the contract sweep is written against — a category "
        "added on one side only is drift, not a feature."
    )
    assert isinstance(calib.TRIAGE_CATEGORIES, frozenset), (
        "the closed set arrived as a mutable collection; a set that can be .add()ed is not "
        "closed (CT-CALIB-04)"
    )


# --- the eligibility rule, at the value level -----------------------------------------------------


def test_tc_calib_02_a_rubric_ambiguity_verdict_is_edit_eligible_and_edit_free():
    """`rubric_ambiguity` may produce an edit — and carries none at triage.

    The eligibility flag is derived from the category inside the value (`edit_eligible`), never
    set by a caller; the edit itself is generated from the teacher's answer during elicitation
    (#138). A triage step that pre-authored the edit it is eligible *for* would be the model
    fitting the rubric while waiting for the teacher's answer — the exact inversion of
    CT-CALIB-05's options-first rule.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "triage", "TriageVerdict", issue="#140")

    verdict = calib.triage(
        calib.Disagreement(criterion_id="c1", category="rubric_ambiguity")
    )
    assert verdict.edit_eligible is True
    assert verdict.category == "rubric_ambiguity"
    assert verdict.proposed_edit is None, (
        f"triage pre-authored a proposed edit ({verdict.proposed_edit!r}) on the one "
        "category eligible to carry one. Eligibility is permission to *elicit* an edit, not "
        "authorship of one — the edit is generated from the teacher's answer (#138, "
        "CT-CALIB-05), and a proposed edit at triage is a fit that skipped the question."
    )
    assert verdict.fitted is False

    # The derived form: constructed directly, the value agrees with itself — the flag is the
    # category's, not a field a caller could set to True alongside a different category.
    direct = calib.TriageVerdict(criterion_id="c1", category="rubric_ambiguity")
    assert direct.edit_eligible is True and direct.proposed_edit is None


def test_tc_calib_02_an_edit_on_a_non_eligible_category_is_refused_at_construction():
    """`EditNotEligible` — a `teacher_inconsistency` or `model_failure` verdict carrying a
    proposed edit does not exist, and the refusal is a `CalibrationError`.

    This is the prohibition assertion (plan §5.17's oracle for `TC-CALIB-02`): the rule is
    structural — the constructor refuses — rather than a flag a caller could set or a
    downstream check that might be skipped. Asserted through `triage()`'s output type and
    directly, because the constructor is the load-bearing half.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "TriageVerdict", "EditNotEligible", issue="#140")

    for category in ("teacher_inconsistency", "model_failure"):
        with pytest.raises(calib.EditNotEligible) as exc:
            calib.TriageVerdict(
                criterion_id="c1",
                category=category,
                proposed_edit="descriptor: 'well-organized' -> 'logically ordered'",
            )
        assert isinstance(exc.value, calib.CalibrationError), (
            f"{category}: the edit-eligibility refusal raised outside the calibration "
            "hierarchy; the gate handlers key on CalibrationError"
        )
        # And the empty-string edit does not sneak past the None check: "not None" is the
        # rule, so any proposed edit value on a non-eligible category is refused.
        with pytest.raises(calib.EditNotEligible):
            calib.TriageVerdict(criterion_id="c1", category=category, proposed_edit="")