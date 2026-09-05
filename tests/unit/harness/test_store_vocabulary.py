"""Controls for `is_student_name_column`, the rule `TC-STORE-12`'s schema sweep rests on.

Issue #14 (TS-08). Not a `TC-*` case: this is the harness self-test for a support module, in the
same spirit as `SEC-15`'s walker controls in `tests/artifact/test_store_query_surface.py`.

`TC-STORE-12` limb 3 sweeps every column of every Tier D table and asserts none names a student.
That assertion is worth exactly what the rule behind it is worth, and it will run for the first
time against a real schema years from now, when `M-STORE` finally exists. A rule nobody has
watched fire is indistinguishable from a rule with a typo in it.

Both halves are asserted, and the **false-positive** half is the one that matters more. A rule
that flags `criterion_name` reds the build against a correct store on the first ordinary Tier D
table, and the fix somebody reaches for at that point is to delete the assertion — at which
point the leak it guarded (RISK-21: a student name in the one tier purge does not touch) has no
detector at all. An earlier draft of this rule flagged fourteen of the columns below; they are
here because they were measured, not imagined.

Runs in the fast tier and is green today: it asserts about the rule, not about `M-STORE`.
"""

from __future__ import annotations

import pytest

from tests.support.store_vocabulary import (
    NON_STUDENT_NAME_COLUMNS,
    TIER_D_IDENTITY_COLUMN,
    is_student_name_column,
)

#: Columns that *are* a student's name. `FR-STORE-12` names the concept, not the spelling, so a
#: guard matched against the single literal `student_name` is one `full_name` away from useless.
STUDENT_NAME_COLUMNS = (
    "student_name",
    "studentName",
    "studentname",
    "student_full_name",
    "student_first",
    "student_last",
    "pupil_name",
    "pupil_forename",
    "learner_surname",
    "candidate_name",
    "child_name",
    "name",
    "full_name",
    "first_name",
    "last_name",
    "surname",
    "forename",
    "given_name",
    "family_name",
    "preferred_name",
    "legal_name",
    # A weak token immediately before a strong one, and a strong token in medial position.
    # Both survive the strong/weak split that cleared `student_first_seen` and friends — the
    # split must not have bought its false-positive fix with a false negative.
    "student_first_name",
    "student_display_name",
    "student_name_raw",
    "student_name_at_enrolment",
    "pupil_surname_alt",
)


@pytest.mark.parametrize("column", STUDENT_NAME_COLUMNS)
def test_a_student_name_column_is_flagged(column):
    """The true-positive half: every spelling of a name reaching Tier D is a finding."""
    assert is_student_name_column(column), (
        f"{column!r} is a student-name column and the rule missed it. Tier D is permanent and "
        "purge_cohort does not touch it (design §3.3), so a name that lands here outlives every "
        "retention control the system has (RISK-21, FR-STORE-12)."
    )


@pytest.mark.parametrize("column", sorted(NON_STUDENT_NAME_COLUMNS))
def test_a_legitimate_column_is_not_flagged(column):
    """The false-positive half, and the reason this file exists.

    Every entry here was produced by measuring a `*_name` version of the rule against columns a
    real Tier D would plausibly carry — `criterion_stats`, `mcq_item_stats` and `run_metrics`
    are design §3.3's own Tier D tables, so `stat_name` and `metric_name` are not hypothetical.

    The pseudonymous shapes are in this list too. `student_ref` is what `FR-STORE-12` *requires*
    Tier D to carry; a rule that flags the required shape fails the correct implementation.
    """
    assert not is_student_name_column(column), (
        f"{column!r} was flagged as a student name. It is not one, and a rule that reds the "
        "build against a correct store is a rule somebody switches off — after which the leak "
        "it guarded has no detector at all."
    )


def test_the_required_pseudonymous_key_is_never_flagged():
    """Stated separately from the parametrized sweep because it is the clause's own shape.

    `FR-STORE-12`: "Tier D rows shall carry `student_ref`". If this rule flagged it,
    `TC-STORE-12` would fail against the exact implementation the requirement asks for.
    """
    assert not is_student_name_column(TIER_D_IDENTITY_COLUMN)


def test_the_two_halves_do_not_overlap():
    """No column is both a positive and a negative control.

    A contradiction here means one of the two lists is wrong, and the parametrized sweeps above
    would report it as an unfixable failure in whichever direction the rule happened to answer.
    """
    overlap = set(STUDENT_NAME_COLUMNS) & set(NON_STUDENT_NAME_COLUMNS)
    assert not overlap, f"these columns are in both control lists: {sorted(overlap)}"
