"""`TC-CALIB-05` — the cap at its boundary: 5, 6 and 7 elicitation candidates.

Test plan §5.17, `TC-CALIB-05` (FR-CALIB-05, Unit / rung 0, boundary).

The contract suite carries the cap and the ranking against a fixture well over the cap
(`TC-CALIB-C05`: ten findings with known affected counts, asserted exact). What no green
test carried before this file is the **boundary the case names as its input** — an
assessment yielding 5, 6 and 7 candidates:

* **5 — below the cap.** The cap is a truncation, not a target: five candidates cost the
  teacher five questions, and an implementation that pads the session up to
  `CALIB_MAX_QUESTIONS` invents questions for ambiguities it does not have.
* **6 — exactly at the cap.** Nothing is dropped and nothing is padded; the count is the
  knob's own value.
* **7 — one over.** Exactly one candidate is dropped, and *which* one is the ranking's
  decision, not discovery order's: with the cap applied, the order decides which ambiguity
  the teacher never sees, so the dropped one must be the least-affected, not the first.

Each point asserts the exact count **and** the ranked order (the case's stated oracle:
"exact count plus ordering"), because cap and ranking are one mechanism — either alone is
safe, together they decide what gets asked (`CT-CALIB-05`'s own words). The tie at the cut
boundary is pinned too: two candidates tied at the cut line are separated by criterion id,
so which ambiguity goes unseen is deterministic rather than an accident of dict order.
"""

from __future__ import annotations

import pytest

from tests.support.calib_vocabulary import MAX_QUESTIONS
from tests.support.impl import CALIB_MODULE, require

# --- the boundary sweep: 5, 6 and 7 candidates ----------------------------------------------------


@pytest.mark.parametrize(
    "candidate_count, expected_questions",
    [
        (5, 5),  # below the cap: every candidate is asked, none padded in
        (6, 6),  # exactly at the cap: the count is the knob's own value
        (7, 6),  # one over: the cap truncates, and only the least-affected is dropped
    ],
    ids=["below-cap-5", "at-cap-6", "one-over-7"],
)
def test_tc_calib_05_the_cap_truncates_above_the_boundary_and_nowhere_below_it(
    candidate_count, expected_questions
):
    """`TC-CALIB-05` — 5, 6 and 7 candidates yield 5, 6 and 6 questions, in ranked order.

    The counts are asserted exactly at all three points because the two failure modes sit
    on opposite sides of the boundary: an implementation that pads to the cap fails the 5
    row (it asks six questions about five ambiguities — invented questions cost teacher
    time and answer nothing), and an implementation that truncates before ranking or
    returns discovery order fails the ordering rows. `FR-CALIB-05` ranks by how many
    submissions the ambiguity affects; with the cap applied, that ranking decides which
    ambiguities the teacher never sees.
    """
    calib = require(CALIB_MODULE, issue="#138")
    elicit = require(CALIB_MODULE, "elicit", issue="#138")

    # Distinct, known affected counts, deliberately supplied out of discovery order — the
    # same discipline the contract's ranked case uses, so a discovery-order return cannot
    # pass by looking plausible. Ascending input for 5/6/7 makes a discovery-order return
    # maximally different from the ranked one.
    affected = list(range(1, candidate_count + 1))  # [1, 2, ..., n] — ascending input
    findings = calib.findings_fixture(affected_counts=affected)

    questions = elicit(findings)

    assert len(questions) == expected_questions, (
        f"{candidate_count} candidates produced {len(questions)} questions at a cap of "
        f"{MAX_QUESTIONS}; the expected count is {expected_questions}. Below the cap the "
        "cap truncates nothing and pads nothing; above it, exactly the surplus is dropped."
    )

    returned = [question.submissions_affected for question in questions]
    assert returned == sorted(affected, reverse=True)[:expected_questions], (
        f"{candidate_count} candidates came back ordered {returned}; ranked by submissions "
        f"affected they should be {sorted(affected, reverse=True)[:expected_questions]}. "
        "With the cap applied, the order decides which ambiguities the teacher never sees."
    )


def test_tc_calib_05_the_seventh_candidate_dropped_at_the_cap_is_the_least_affected():
    """At 7 candidates the one the teacher never sees is the least-affected — by rank.

    The cap decides that one ambiguity goes unseen; the ranking decides *which*. An
    implementation that drops discovery's last candidate instead of the least-affected one
    satisfies "at most six" while hiding the ambiguity that matters more — the exact harm
    the ranking exists to prevent, invisible in the count alone.
    """
    calib = require(CALIB_MODULE, issue="#138")
    elicit = require(CALIB_MODULE, "elicit", issue="#138")

    # Seven candidates, out of discovery order, with a known least-affected candidate.
    affected = [9, 30, 4, 21, 15, 2, 27]  # the 2 is the one that must be dropped
    findings = calib.findings_fixture(affected_counts=affected)

    questions = elicit(findings)

    assert len(questions) == MAX_QUESTIONS, (
        f"the cap returned {len(questions)} questions over seven candidates; "
        f"CALIB_MAX_QUESTIONS is {MAX_QUESTIONS}"
    )
    asked_criteria = {question.criterion_id for question in questions}
    least_affected = calib.findings_fixture(affected_counts=affected)[5].criterion_id
    assert least_affected not in asked_criteria, (
        f"the least-affected candidate ({least_affected}, 2 submissions) survived the cap "
        "while a more-affected one was dropped — the ranking, not discovery order, decides "
        "which ambiguity the teacher never sees (FR-CALIB-05)"
    )
    all_criteria = {finding.criterion_id for finding in findings}
    assert asked_criteria == all_criteria - {least_affected}, (
        "the cap dropped a candidate other than the least-affected one"
    )


def test_tc_calib_05_a_tie_at_the_cut_boundary_is_broken_by_criterion_id():
    """Two candidates tied at the cut line: the smaller criterion id is the one kept.

    A tie at positions 6 and 7 decides which of two equally-affected ambiguities the
    teacher never sees. `elicit` breaks ties by criterion id for determinism — asserted
    here at the boundary where the decision actually bites, because below the cap a tie
    only permutes the questions and above it the counts differ anyway.
    """
    calib = require(CALIB_MODULE, issue="#138")
    elicit = require(CALIB_MODULE, "elicit", issue="#138")

    # Five candidates with distinct high counts, then two tied exactly at the cut line:
    # positions 6 and 7 are the tied pair, and the cap keeps exactly one of them — the
    # tie-break, not dict order, picks which.
    findings = (
        calib.findings_fixture(affected_counts=[40, 31, 27, 22, 18])
        + (
            calib.Finding(
                criterion_id="CRIT-099",
                category="rubric_ambiguity",
                submissions_affected=12,
                examples=("response A", "response B"),
            ),
            calib.Finding(
                criterion_id="CRIT-008",
                category="rubric_ambiguity",
                submissions_affected=12,
                examples=("response A", "response B"),
            ),
        )
    )

    questions = elicit(findings)

    assert len(questions) == MAX_QUESTIONS
    kept_criteria = [question.criterion_id for question in questions]
    assert "CRIT-008" in kept_criteria, (
        f"the tie at the cut line was not broken by criterion id: kept {kept_criteria}. "
        "CRIT-008 and CRIT-099 both affect 12 submissions and only one survives the cap; "
        "the deterministic tie-break keeps the smaller id, so which ambiguity goes unseen "
        "is not an accident of sorting stability."
    )
    assert "CRIT-099" not in kept_criteria, (
        f"both tied candidates survived the cap: kept {kept_criteria}. Only one of the "
        "12-submission pair belongs in the asked set — an implementation that keeps both "
        "must have dropped a more-affected candidate to make room"
    )
    more_affected = "CRIT-005"  # the fixture's 18-submission candidate, ranked 6th
    assert more_affected in kept_criteria, (
        f"the more-affected candidate ({more_affected}, 18 submissions) was dropped while "
        "the tied pair was being resolved — the cap cut by discovery order, not by rank"
    )