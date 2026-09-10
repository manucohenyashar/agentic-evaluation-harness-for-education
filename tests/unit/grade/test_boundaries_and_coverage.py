"""`TC-GRADE-04`, `TC-GRADE-05`, `TC-GRADE-06` — band resolution, the coverage record,
and boundary risk, as pure seams.

Test plan §5.14; `FR-GRADE-03`, `FR-GRADE-04`, `FR-GRADE-05`. Rung 0: hand-written rows
and hand-computed expectations, no store, no model. Written ahead of **#101**, which
lands `aeh.grade`; the seams these cases call are declared in
`tests/support/grade_vocabulary.py`:

- `apply_policy` — design-declared (§3.14, CT-GRADE-02); `.total` is the declared pin.
- `resolve_grade(scaled_score, boundaries)` — **invented** pure seam for FR-GRADE-03.
  The rule it must follow is not invented, only its name: the shipped `grade_boundary`
  DDL pins it in aeh/pkg.py migration 5 — *floors are INCLUSIVE; the grade with the
  greatest floor <= the scaled score resolves*. A package with no table passes `None`
  (or no rows), and the answer is `None`, never a band.
- `coverage_for(scores, criterion_ids)` — **invented** pure seam for FR-GRADE-04. The
  five counter names are design-declared (CT-GRADE-04); the criterion-id list argument
  is what makes a criterion with **no** row count as missing rather than vanish.
- `boundary_risk(total, provisional_intervals, boundaries)` — **invented** pure seam
  for FR-GRADE-05, with the interval source **injected** exactly as the case requires
  (the full-band-range assumption is design TBD §7.4): the caller hands over the
  plausible movement of each provisional criterion's points, so a narrower source
  (CT-GRADE-19's "tighter estimate") is exercisable without a code change.

TC-GRADE-04's and TC-GRADE-06's grade-resolution limbs are also asserted at the
persisted level (`tests/integration/grade/`), where a wrong resolution would surface in
a real `submission_grade` row; this file pins the exact arithmetic the case table asks
for.

Isolation: rung 0.
"""

from __future__ import annotations

import pytest

from aeh.pkg import GradePolicy
from tests.support.grade_vocabulary import GRADE_BLOCKER, boundary, score
from tests.support.impl import GRADE_MODULE, require

ISSUE = GRADE_BLOCKER


# --- TC-GRADE-04: the band comes from the table, or it does not exist ------------------------


@pytest.mark.parametrize(
    ("scaled_score", "expected"),
    [
        (85.0, "A"),       # greatest floor <= score
        (80.0, "A"),       # exactly on the floor — floors are INCLUSIVE
        (79.5, "B"),       # one notch below the A floor
        (60.0, "B"),       # the B floor itself, same inclusive rule
        (0.0, "C"),        # the lowest floor
    ],
    ids=["above", "exactly-on-floor", "just-below", "b-floor", "lowest-floor"],
)
def test_tc_grade_04_band_resolved_from_the_boundary_table(scaled_score, expected):
    """`TC-GRADE-04` — with a boundary table, the band is the one the table resolves.

    The greatest inclusive floor <= the scaled score wins — the shipped `grade_boundary`
    DDL's own rule, asserted here with hand-picked probes on each side of a floor."""
    resolve_grade = require(GRADE_MODULE, "resolve_grade", issue=ISSUE)

    boundaries = [boundary("A", 80.0), boundary("B", 60.0), boundary("C", 0.0)]

    assert resolve_grade(scaled_score, boundaries) == expected, (
        f"scaled score {scaled_score!r} resolved to "
        f"{resolve_grade(scaled_score, boundaries)!r}, expected {expected!r} — the "
        "greatest inclusive floor <= the score must win (FR-GRADE-03, the shipped "
        "grade_boundary DDL's rule)"
    )


@pytest.mark.parametrize(
    "boundaries",
    [None, []],
    ids=["no-table", "empty-table"],
)
def test_tc_grade_04_grade_is_null_without_a_boundary_table(boundaries):
    """`TC-GRADE-04` — a package that declares no boundary table leaves `grade` null.

    Never an invented band: an absent input stays visibly absent (the NoValidationData
    honesty rule #101's own technical notes cite)."""
    resolve_grade = require(GRADE_MODULE, "resolve_grade", issue=ISSUE)

    resolved = resolve_grade(85.0, boundaries)

    assert resolved is None, (
        f"without a boundary table the resolution returned {resolved!r} — grade must "
        "be left null rather than invented (FR-GRADE-03, CT-GRADE-05's second clause)"
    )


# --- TC-GRADE-05: the coverage record sums, and matches the hand count -----------------------


@pytest.mark.parametrize(
    ("criterion_ids", "rows", "expected"),
    [
        # Every criterion auto-accepted.
        (
            ("C1", "C2", "C3", "C4", "C5"),
            [(f"C{i}", 10.0, "auto") for i in range(1, 6)],
            (5, 5, 0, 0, 0),
        ),
        # The TC-GRADE-07 shape in miniature: 3 auto, 2 reviewed, 1 provisional, and
        # C7 absent (its extraction quarantined) — counted missing, never dropped.
        (
            ("C1", "C2", "C3", "C4", "C5", "C6", "C7"),
            [("C1", 10.0, "auto"), ("C2", 9.0, "auto"), ("C3", 8.0, "auto"),
             ("C4", 7.0, "reviewed"), ("C5", 6.0, "reviewed"),
             ("C6", 5.0, "provisional")],
            (7, 3, 2, 1, 1),
        ),
        # Nothing scored at all: everything is missing, nothing is invented.
        (("C1", "C2", "C3", "C4"), [], (4, 0, 0, 0, 4)),
        # A submission with no criteria: the record exists and reads all zeros.
        ((), [], (0, 0, 0, 0, 0)),
    ],
    ids=["all-auto", "mixed-with-one-missing", "all-missing", "no-criteria"],
)
def test_tc_grade_05_coverage_record_matches_the_hand_count(criterion_ids, rows, expected):
    """`TC-GRADE-05` — the five counters match the hand count, and sum to the total.

    Hand-counted across the coverage space; the sum invariant
    (`criteria_auto + criteria_reviewed + criteria_provisional + criteria_missing ==
    criteria_total`) holds in every case because missing is counted from the criterion
    list, never from the rows alone."""
    coverage_for = require(GRADE_MODULE, "coverage_for", issue=ISSUE)

    scores = [score(cid, pts, routing=routing) for cid, pts, routing in rows]

    coverage = coverage_for(scores, list(criterion_ids))

    actual = (
        coverage.criteria_total,
        coverage.criteria_auto,
        coverage.criteria_reviewed,
        coverage.criteria_provisional,
        coverage.criteria_missing,
    )
    assert actual == expected, (
        f"coverage {actual} does not match the hand count {expected} for "
        f"{len(rows)} rows over {len(criterion_ids)} criteria (FR-GRADE-04)"
    )
    assert (
        coverage.criteria_auto
        + coverage.criteria_reviewed
        + coverage.criteria_provisional
        + coverage.criteria_missing
        == coverage.criteria_total
    ), "the coverage counters do not sum to the total — a class is being dropped or doubled"


# --- TC-GRADE-06: boundary risk, with the interval source injected ---------------------------

#: A boundary table with a band edge above and below the probe totals:
#: total 52.0 sits in band B (floor 40.0); band A starts at 60.0.
_PROBE_BOUNDARIES = [boundary("A", 60.0), boundary("B", 40.0), boundary("C", 0.0)]
_PROBE_TOTAL = 52.0


@pytest.mark.parametrize(
    ("intervals", "expected"),
    [
        # Full band range reaches past the A floor: at risk, range stated.
        ([(0.0, 10.0)], (True, 52.0, 62.0)),
        # Full band range stays inside B: not at risk, range withheld.
        ([(0.0, 5.0)], (False, None, None)),
        # Exactly on the boundary: the A floor itself is inside the range, and landing
        # on it resolves to A (floors inclusive) — at risk.
        ([(0.0, 8.0)], (True, 52.0, 60.0)),
        # Downward: the range reaches below the B floor into C — at risk too.
        ([(-14.0, 2.0)], (True, 38.0, 54.0)),
        # Two provisional criteria: their intervals sum before testing the edge.
        ([(0.0, 4.0), (0.0, 5.0)], (True, 52.0, 61.0)),
    ],
    ids=["crosses-up", "stays-inside", "exactly-on-boundary", "crosses-down", "two-criteria"],
)
def test_tc_grade_06_boundary_at_risk_with_injected_intervals(intervals, expected):
    """`TC-GRADE-06` — `boundary_at_risk` fires exactly when the injected interval
    could move the student across a boundary, and `score_low`/`score_high` are
    populated when (and only when) it does.

    The interval source is the case's injected seam: these offsets stand in for the
    full declared band range (the conservative assumption, CT-GRADE-19) and a narrower
    source is exercised by the de-risk case below."""
    boundary_risk = require(GRADE_MODULE, "boundary_risk", issue=ISSUE)

    risk = boundary_risk(_PROBE_TOTAL, intervals, _PROBE_BOUNDARIES)

    actual = (risk.at_risk, risk.score_low, risk.score_high)
    assert actual == expected, (
        f"boundary risk {actual} for intervals {intervals} does not match the "
        f"hand-computed {expected} — the flagged/not-flagged line is whether any "
        "boundary floor lies inside the achievable range (FR-GRADE-05)"
    )


def test_tc_grade_06_a_tighter_injected_interval_clears_the_flag():
    """`TC-GRADE-06` — the interval source is injected, so the same submission is at
    risk under the full band range and not at risk under a narrower one.

    This is what makes the TBD (§7.4) testable rather than hard-coded: the
    conservative full-range assumption over-flags (CT-GRADE-19 says so, and does not
    promise better), and a tighter source must be able to say so without a code
    change."""
    boundary_risk = require(GRADE_MODULE, "boundary_risk", issue=ISSUE)

    full_band_range = boundary_risk(_PROBE_TOTAL, [(0.0, 10.0)], _PROBE_BOUNDARIES)
    tighter_source = boundary_risk(_PROBE_TOTAL, [(0.0, 5.0)], _PROBE_BOUNDARIES)

    assert full_band_range.at_risk is True
    assert tighter_source.at_risk is False, (
        "a narrower interval source still flags the student — the interval source is "
        "injected, and a source that cannot clear the flag is not a source (test plan "
        "TC-GRADE-06, design TBD §7.4)"
    )


def test_tc_grade_06_the_total_is_always_inside_the_reported_range():
    """`TC-GRADE-06`'s invariant limb — each criterion's current points sit inside its
    own plausible range, so the computed total must always lie inside
    `[score_low, score_high]` when the range is stated.

    A range that excludes the current total is not the range of achievable outcomes;
    it would make `boundary_at_risk` uninterpretable for the consumer (CT-GRADE-05)."""
    apply_policy = require(GRADE_MODULE, "apply_policy", issue=ISSUE)
    boundary_risk = require(GRADE_MODULE, "boundary_risk", issue=ISSUE)

    # Settled criteria plus one provisional, over a plain-sum policy: the total
    # includes the provisional criterion's current points.
    policy = GradePolicy(combination="weighted_sum")
    scores = [
        score("C1", 30.0, routing="auto"),
        score("C2", 22.0, routing="auto"),
        score("C3", 4.0, routing="provisional"),
    ]
    total = apply_policy(scores, policy).total

    risk = boundary_risk(total, [(-3.5, 6.0)], _PROBE_BOUNDARIES)

    assert total == pytest.approx(56.0, abs=1e-9)
    if risk.at_risk:
        assert risk.score_low <= total <= risk.score_high, (
            f"the stated range [{risk.score_low!r}, {risk.score_high!r}] does not "
            f"contain the current total {total!r} — score_low/score_high must bracket "
            "every achievable outcome, and the current total is one of them "
            "(CT-GRADE-05)"
        )
