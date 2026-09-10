"""`TC-GRADE-07` — no missing or unreviewed criterion is ever substituted for.

Test plan §5.14's full block form; `FR-GRADE-06`, `FR-GRADE-07`, `FR-GRADE-08`;
RISK-03 and RISK-11 (both Critical). The case's isolation column splits it: **rung 0
for `apply_policy`** (this file) and **rung 2 for the persisted grade** — the
incomplete state naming its missing input and the operator-queue routing,
`tests/integration/grade/test_incomplete_and_routing.py`. The plan's automatable line
names this file for the unit half; the persisted half lives beside the other rung-2
grade cases, where its store fixture already exists.

The fixture is the plan's: 15 criteria, of which 11 are auto-accepted, 2 reviewed,
1 provisional and 1 **missing** — its extraction quarantined, so it has no
`criterion_score` row at all. A missing criterion is an absent row, never a state and
never a value; that is the input side of the no-imputation rule (FR-GRADE-08).

Step 5's oracle is the **artifact assertion**: the prohibition is on the *existence of
a substitution path*, not merely on its not firing in this fixture. The scan below
tokenizes the landed module's source (identifiers only — prose is excluded, so a
docstring saying "no cohort mean" cannot green the case) and refuses the declared
vocabulary of substitution techniques. Its honest limit, recorded rather than papered
over: a substitution implemented under an innocent name evades the scan, which is why
the behavioural half — exact coverage, the incomplete state, the operator routing, and
the purely-provisional-is-not-incomplete differential — is asserted alongside it.

Isolation: rung 0 — pure functions over hand-counted rows.
"""

from __future__ import annotations

import io
import inspect
import tokenize

import pytest

from aeh.pkg import GradePolicy
from tests.support.grade_vocabulary import GRADE_BLOCKER, score
from tests.support.impl import GRADE_MODULE, require

ISSUE = GRADE_BLOCKER

#: The plan's fixture: 15 criteria, 11 auto / 2 reviewed / 1 provisional / 1 missing.
_ALL_CRITERIA = tuple(f"C{i}" for i in range(1, 16))
_PRESENT_ROWS = (
    [(f"C{i}", 6.0, "auto") for i in range(1, 12)]      # C1..C11 auto-accepted
    + [("C12", 7.0, "reviewed"), ("C13", 8.0, "reviewed")]
    + [("C14", 5.0, "provisional")]
)                                                        # C15 missing: no row at all
_HAND_TOTAL = 11 * 6.0 + 7.0 + 8.0 + 5.0                 # 86.0, the 14 present criteria

#: The declared substitution vocabulary the artifact assertion refuses. Identifiers
#: only: the tokenize pass excludes comments and docstrings, so the module documenting
#: its own prohibition cannot satisfy the scan by mentioning it.
_SUBSTITUTION_IDENTIFIERS = frozenset(
    {
        "cohort_mean", "cohortmean", "class_mean",
        "impute", "imputed", "imputing", "imputation_fill",
        "zero_fill", "zerofill", "default_zero",
        "backfill", "forward_fill", "locf", "carry_forward",
        "default_partial_credit", "partial_credit_default",
        "fill_missing", "substitute_missing", "substituted_value",
        "nearest_neighbor", "nearest_neighbour",
    }
)


def _module_identifiers(module) -> set[str]:
    """Every NAME token in the module's source — the identifiers the implementation
    actually contains, with its prose stripped."""
    source = inspect.getsource(module)
    return {
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.NAME
    }


# --- steps 1-2: the grade is computed from the present criteria; the coverage is exact -------


def test_tc_grade_07_coverage_record_is_exact_for_the_fifteen_criterion_fixture():
    """`TC-GRADE-07` step 2 — the coverage record reads exactly 15 / 11 / 2 / 1 / 1.

    The missing criterion is counted from the criterion list (it has no row), and the
    four populated classes sum to the total."""
    coverage_for = require(GRADE_MODULE, "coverage_for", issue=ISSUE)

    scores = [score(cid, pts, routing=routing) for cid, pts, routing in _PRESENT_ROWS]

    coverage = coverage_for(scores, list(_ALL_CRITERIA))

    actual = (
        coverage.criteria_total,
        coverage.criteria_auto,
        coverage.criteria_reviewed,
        coverage.criteria_provisional,
        coverage.criteria_missing,
    )
    assert actual == (15, 11, 2, 1, 1), (
        f"coverage {actual} does not read 15 / 11 / 2 / 1 / 1 — the quarantined "
        "criterion's absence must surface as criteria_missing, never as a smaller "
        "total (FR-GRADE-04, RISK-03)"
    )


def test_tc_grade_07_the_computation_uses_the_present_criteria_and_only_them():
    """`TC-GRADE-07` step 1 — the grade is computed from the 14 present criteria and
    equals their hand-computed sum.

    Never an exception, never a zero (CT-GRADE-15's shape at the pure level): the
    missing input is the coverage record's problem, not a crash or a silent 0 in the
    sum."""
    apply_policy = require(GRADE_MODULE, "apply_policy", issue=ISSUE)

    policy = GradePolicy(combination="weighted_sum")
    scores = [score(cid, pts, routing=routing) for cid, pts, routing in _PRESENT_ROWS]

    total = apply_policy(scores, policy).total

    assert total is not None, (
        "the grade did not stand over the 14 present criteria — no gate is configured, "
        "so a refusal here is the computation treating a missing *neighbour* as its "
        "own missing input (CT-GRADE-15)"
    )
    assert total == pytest.approx(_HAND_TOTAL, abs=1e-9), (
        f"the total is {total!r}, hand-computed {_HAND_TOTAL!r} — a discrepancy is a "
        "substituted value (a zero, a mean, a partial credit) standing in for the "
        "missing C15 inside the sum (FR-GRADE-08, RISK-11)"
    )


# --- step 5: the artifact assertion — no substitution path exists in the module --------------


def test_tc_grade_07_no_substitution_identifier_exists_anywhere_in_the_module():
    """`TC-GRADE-07` step 5 — the prohibition is on the existence of a substitution
    path, not merely on its not firing here.

    The whole module source is scanned (`apply_policy` and the grading service with
    it): no cohort mean, no default partial credit, no zero-fill, no
    last-observation-carried-forward, no imputation — under any of the declared names.
    The scan proves its own reach by finding `apply_policy` in the identifiers; a scan
    that saw nothing would be vacuous, not green."""
    grade_module = require(GRADE_MODULE, issue=ISSUE)

    identifiers = _module_identifiers(grade_module)

    assert "apply_policy" in identifiers, (
        "the scan saw no apply_policy in the module source — it is not scanning what "
        "it claims to, and its green means nothing"
    )
    found = identifiers & _SUBSTITUTION_IDENTIFIERS
    assert not found, (
        f"the grading module carries substitution identifier(s) {sorted(found)} — "
        "a cohort mean, a default partial credit, a zero-fill, a "
        "last-observation-carried-forward or any imputation is prohibited outright "
        "(FR-GRADE-08, CT-GRADE-07, RISK-03/RISK-11); the prohibition is on the "
        "existence of the path, not on its firing in a fixture"
    )


# --- step 6 and the variants: coverage tracks every shape of absence -------------------------


def test_tc_grade_07_the_provisional_criterion_also_missing_drains_into_missing():
    """`TC-GRADE-07` step 6 — recompute with the provisional criterion also missing:
    its row is gone, coverage drains it from provisional into missing, and the total
    drops by exactly its points — the recomputation followed the absence, it did not
    substitute for it."""
    coverage_for = require(GRADE_MODULE, "coverage_for", issue=ISSUE)
    apply_policy = require(GRADE_MODULE, "apply_policy", issue=ISSUE)

    rows_without_c14 = [row for row in _PRESENT_ROWS if row[0] != "C14"]
    scores = [
        score(cid, pts, routing=routing) for cid, pts, routing in rows_without_c14
    ]

    coverage = coverage_for(scores, list(_ALL_CRITERIA))
    total = apply_policy(scores, GradePolicy(combination="weighted_sum")).total

    actual = (
        coverage.criteria_total,
        coverage.criteria_auto,
        coverage.criteria_reviewed,
        coverage.criteria_provisional,
        coverage.criteria_missing,
    )
    assert actual == (15, 11, 2, 0, 2), (
        f"coverage {actual} with the provisional criterion also missing — the "
        "provisional class must drain into criteria_missing, never into a smaller "
        "total or a substituted value (TC-GRADE-07 step 6, FR-GRADE-07)"
    )
    assert total == pytest.approx(_HAND_TOTAL - 5.0, abs=1e-9), (
        f"the recomputed total is {total!r}, expected {_HAND_TOTAL - 5.0!r} — C14's "
        "points must leave the sum exactly, with nothing standing in for them "
        "(FR-GRADE-08: no imputation on recompute)"
    )


def test_tc_grade_07_all_fifteen_missing_counts_fifteen_missing():
    """`TC-GRADE-07`'s variants line, its extreme — with every criterion's extraction
    quarantined, the coverage reads 15 total, 15 missing, nothing else.

    (Step 6 proper — the provisional criterion also missing, coverage draining
    `provisional` into `missing` — is the case above; this is the variants line's
    "all 15 criteria missing" taken whole.)"""
    coverage_for = require(GRADE_MODULE, "coverage_for", issue=ISSUE)

    coverage = coverage_for([], list(_ALL_CRITERIA))

    actual = (
        coverage.criteria_total,
        coverage.criteria_auto,
        coverage.criteria_reviewed,
        coverage.criteria_provisional,
        coverage.criteria_missing,
    )
    assert actual == (15, 0, 0, 0, 15), (
        f"coverage {actual} for an all-missing submission — every class must drain "
        "into criteria_missing, which is the one state the system refuses to paper "
        "over (FR-GRADE-07)"
    )


def test_tc_grade_07_zero_missing_three_provisional_is_a_deliverable_computation():
    """`TC-GRADE-07` variants 2 and 3 — zero missing but three provisional: the
    coverage shows no absence at all, and the computation stands over it.

    `incomplete` is caused exclusively by ingestion failure, never by judgment
    uncertainty (CT-GRADE-08). The state half of that assertion — the persisted grade
    reads `provisional`, not `incomplete` — is the rung-2 half of this case
    (`test_incomplete_and_routing.py`); at rung 0 the input side is pinned here: zero
    missing, and a computed total that stands, so nothing downstream has a missing
    input to excuse."""
    apply_policy = require(GRADE_MODULE, "apply_policy", issue=ISSUE)
    coverage_for = require(GRADE_MODULE, "coverage_for", issue=ISSUE)

    rows = [("C1", 4.0, "provisional"), ("C2", 3.5, "provisional"),
            ("C3", 4.5, "provisional")]
    scores = [score(cid, pts, routing=routing) for cid, pts, routing in rows]

    coverage = coverage_for(scores, ["C1", "C2", "C3"])
    total = apply_policy(scores, GradePolicy(combination="weighted_sum")).total

    assert (
        coverage.criteria_total,
        coverage.criteria_auto,
        coverage.criteria_reviewed,
        coverage.criteria_provisional,
        coverage.criteria_missing,
    ) == (3, 0, 0, 3, 0), (
        "three provisional criteria with none missing must read 3 / 0 / 0 / 3 / 0 — "
        "judgment uncertainty is not absence (FR-GRADE-06)"
    )
    assert total == pytest.approx(12.0, abs=1e-9), (
        f"the computation over three provisional criteria returned {total!r} — the "
        "provisional inputs are scored inputs, and the total must stand over them "
        "(FR-GRADE-06: no path by which a provisional input withholds a grade)"
    )
