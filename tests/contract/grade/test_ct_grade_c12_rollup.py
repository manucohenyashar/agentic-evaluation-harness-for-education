"""`TC-GRADE-C12` — the rollup separates deterministic from judged, and findings name their reach (§6.11.14).

`CT-GRADE-12` (behaviour): "Assert `ClassRollup` reports deterministic results in a
block **separate** from judged criteria, with **no combined figure across the
two**. Then assert it **surfaces as findings** the criteria marked
`ungradeable_by_panel` and those that exhausted the review budget, **naming
affected student counts**."

The limbs, in the row's order:

- **the separated blocks** (rung 3, green): the shipped record the clause names is
  `aeh.grade.SeparatedRollup` (the module's landed form of the row's `ClassRollup`
  shape — FR-GRADE-15/CT-GRADE-12 name it directly), and its SHAPE is the refusal:
  exactly the two block fields, judged and deterministic, and nowhere else for a
  combined figure to live. Each block carries its OWN population and its OWN
  per-criterion figures; the two criterion sets are disjoint and their union is
  every scored criterion — none lost, none shared. The blocks also keep their own
  figure conventions (the judged figures real, the deterministic derived figures
  nulled), which is WHY nothing composes across them.
- **the findings** (rung 3, green): `rollup_findings` surfaces exactly the criteria
  the system could not apply — the escalation breaker's `ungradeable_by_panel`
  marks, and the review budget's exhausted residuals — as ONE finding per
  criterion, naming the count of AFFECTED students, not the class: two of three
  affected reads 2, never the cohort's size. A criterion both breaker-marked and
  budget-exhausted is ONE finding whose count is the union, and a criterion the
  system applied cleanly earns no finding at all.

Isolation: rung 3 — real store, real package, real run. The socket guard is
autouse; `criterion_score` rows are the vocabulary's disclosed `M-AGG` stand-in
(`_drive.write_state_row` for the breaker's `ungradeable_by_panel` state, which no
derived routing pairing carries), and the budget-exhausted `review_queue` row is
the disclosed stand-in for `M-REVIEW`'s residual — the queue has no status column,
the exhaustion rides the reason text (the shipped read's own disclosure).
"""

from __future__ import annotations

import dataclasses

import pytest

from aeh.grade import (
    RollupBlock,
    SeparatedRollup,
    rollup_findings,
    separated_rollup,
)
from aeh.store import open_store
from tests.contract.grade._drive import write_state_row, graded_run
from tests.support.impl import GRADE_MODULE, require

pytestmark = [pytest.mark.contract]

_CRITERIA = (
    {"criterion_id": "C-J", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C-M", "kind": "mcq", "scoring_model": "atomic"},
)

#: S-C carries no judged row (its extraction never delivered one) but sits in the
#: deterministic population: the two blocks' populations are their own.
_ROWS = (
    ("S-A", "C-J", "B1", 7.0, "auto"),
    ("S-B", "C-J", "B1", 7.0, "auto"),
    ("S-A", "C-M", "correct", 4.0, "auto"),
    ("S-B", "C-M", "correct", 4.0, "auto"),
    ("S-C", "C-M", "incorrect", 1.0, "auto"),
)


def test_tc_grade_c12_deterministic_results_are_a_block_apart_with_no_combined_figure(
    tmp_data_dir,
):
    """`TC-GRADE-C12` (`CT-GRADE-12`, rung 3) — the record's shape is the refusal:
    exactly two blocks, judged and deterministic, each with its own population and
    its own per-criterion figures; the criterion sets are disjoint and cover every
    scored criterion; and the blocks keep their own figure conventions, so no
    figure spans them."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-A", "S-B", "S-C"), criteria=_CRITERIA, rows=_ROWS
        )
        rollup = separated_rollup(world.run_id, store)

        # The shape IS the refusal: exactly two block fields, and no third field —
        # no combined figure, no pooled population, nowhere for one to live.
        assert [field.name for field in dataclasses.fields(SeparatedRollup)] == [
            "judged", "deterministic",
        ], (
            "the rollup record does not carry exactly the two separated blocks — "
            "a combined figure across judged and deterministic results is not "
            "comparable, and the record's shape is the clause's refusal "
            "(CT-GRADE-12's no-combined-figure clause)"
        )
        assert [field.name for field in dataclasses.fields(RollupBlock)] == [
            "submission_count", "criteria",
        ], (
            "a block carries more than its own population and its own per-criterion "
            "figures — a cross-block figure has no home on a separated block "
            "(CT-GRADE-12)"
        )

        # Each block is its own population over its own criteria: the judged block
        # holds C-J alone over the two submissions that scored it; the
        # deterministic block holds C-M alone over all three.
        judged, deterministic = rollup.judged, rollup.deterministic
        assert [figure.criterion_id for figure in judged.criteria] == ["C-J"], (
            f"the judged block's criteria read "
            f"{[f.criterion_id for f in judged.criteria]!r} — judged results live "
            "in their own block, alone (CT-GRADE-12)"
        )
        assert [figure.criterion_id for figure in deterministic.criteria] == ["C-M"], (
            f"the deterministic block's criteria read "
            f"{[f.criterion_id for f in deterministic.criteria]!r} — deterministic "
            "results live in their own block, never beside a judged figure "
            "(CT-GRADE-12)"
        )
        assert judged.submission_count == 2, (
            f"the judged block's population reads {judged.submission_count} — the "
            "blocks carry their OWN populations (S-C never scored the judged "
            "criterion), not one shared denominator (CT-GRADE-12)"
        )
        assert deterministic.submission_count == 3, (
            f"the deterministic block's population reads "
            f"{deterministic.submission_count} — its own population, its own "
            "denominator (CT-GRADE-12)"
        )

        # Disjoint and exhaustive: no criterion is listed in both blocks, and no
        # scored criterion is lost between them.
        judged_ids = {figure.criterion_id for figure in judged.criteria}
        deterministic_ids = {figure.criterion_id for figure in deterministic.criteria}
        assert judged_ids.isdisjoint(deterministic_ids), (
            f"a criterion appears in both blocks ({sorted(judged_ids & deterministic_ids)!r}) "
            "— a figure shared across the blocks IS a combined figure (CT-GRADE-12)"
        )
        assert judged_ids | deterministic_ids == {"C-J", "C-M"}, (
            f"the blocks cover {sorted(judged_ids | deterministic_ids)!r} — every "
            "scored criterion lands in exactly one block (CT-GRADE-12)"
        )

        # The figure conventions differ by block — the reason no figure composes
        # across them: the judged figure's entropy is real, the deterministic one
        # is withheld (a zero would read as no variation, a different claim from
        # not applying).
        (judged_figure,) = judged.criteria
        (deterministic_figure,) = deterministic.criteria
        assert judged_figure.entropy is not None, (
            "the judged block nulled its derived figures — the judged convention "
            "is real figures (CT-GRADE-12 with CT-GRADE-13)"
        )
        assert deterministic_figure.entropy is None, (
            "the deterministic block computed a derived figure — its own kind "
            "verdict nulls entropy and interior rate, the convention that keeps "
            "the blocks incomposable (CT-GRADE-12 with CT-GRADE-13)"
        )
        # Each block's histogram reads its own criterion's bands, and nothing else's.
        assert dict(judged_figure.histogram) == {"B1": 2}, (
            f"the judged histogram reads {judged_figure.histogram!r} — the block "
            "counts its own criterion's bands (CT-GRADE-12)"
        )
        assert dict(deterministic_figure.histogram) == {
            "correct": 2, "incorrect": 1,
        }, (
            f"the deterministic histogram reads {deterministic_figure.histogram!r} "
            "— its own criterion's real counts (CT-GRADE-12)"
        )
    finally:
        store.close()


def test_tc_grade_c12_findings_name_the_criteria_and_their_reach(tmp_data_dir):
    """`TC-GRADE-C12`'s findings limb (`CT-GRADE-12` with FR-GRADE-16, rung 3) — the
    rollup surfaces as findings the criteria marked `ungradeable_by_panel` and those
    whose review budget was exhausted, each naming the count of AFFECTED students:
    two of a three-student cohort reads 2, never 3. A criterion carrying both marks
    is ONE finding whose count is the union; a criterion the system applied earns no
    finding."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        criteria = (
            {"criterion_id": "C-BREAK", "kind": "open", "scoring_model": "atomic"},
            {"criterion_id": "C-BUDGET", "kind": "open", "scoring_model": "atomic"},
            {"criterion_id": "C-CLEAN", "kind": "open", "scoring_model": "atomic"},
            {"criterion_id": "C-UNION", "kind": "open", "scoring_model": "atomic"},
        )
        rows = [
            ("S-A", "C-CLEAN", "B1", 6.0, "auto"),
            ("S-B", "C-CLEAN", "B1", 6.0, "auto"),
            ("S-C", "C-CLEAN", "B2", 4.0, "auto"),
        ]
        world = graded_run(
            store, submissions=("S-A", "S-B", "S-C"), criteria=criteria,
            rows=rows, compute=False,
        )
        cohort = world.cohort
        # The breaker's mark: two of the three submissions carry
        # `ungradeable_by_panel` on C-BREAK (the escalation circuit breaker's
        # refusal — `_drive.write_state_row`, the state no derived pairing writes).
        for submission_id in ("S-A", "S-B"):
            write_state_row(
                cohort, submission_id, "C-BREAK", "B1", 5.0,
                "provisional", "ungradeable_by_panel",
            )
        # C-UNION's breaker side: one submission (S-A) — the union with its budget
        # side (S-B below) is the finding the union limb pins.
        write_state_row(
            cohort, "S-A", "C-UNION", "B1", 5.0,
            "provisional", "ungradeable_by_panel",
        )
        # The budget's residual: the review queue's exhausted rows name C-BUDGET
        # for two students, C-UNION for one (the disclosed stand-in for M-REVIEW's
        # residual — the exhaustion rides the reason text).
        _seed_exhausted(cohort, "S-A", "C-BUDGET")
        _seed_exhausted(cohort, "S-C", "C-BUDGET")
        _seed_exhausted(cohort, "S-B", "C-UNION")
        # Fixture gate: the marks are on the ledger exactly as intended.
        marked = cohort.query(
            "SELECT submission_id, criterion_id, state FROM criterion_score "
            "WHERE state = 'ungradeable_by_panel' ORDER BY submission_id"
        )
        assert [(r["submission_id"], r["criterion_id"]) for r in marked] == [
            ("S-A", "C-BREAK"), ("S-A", "C-UNION"), ("S-B", "C-BREAK"),
        ], "fixture bug: the breaker rows did not land as seeded"

        findings = {finding.criterion_id: finding for finding in
                    rollup_findings(world.run_id, store)}

        # The clean criterion earns NO finding — the findings name what the system
        # could not apply, nothing else.
        assert "C-CLEAN" not in findings, (
            f"the clean criterion surfaced as a finding ({findings!r}) — findings "
            "name the criteria the system could NOT apply (CT-GRADE-12)"
        )
        # The breaker's finding: the criterion, its affected students, what happened.
        breaker = findings["C-BREAK"]
        assert breaker.student_count == 2, (
            f"C-BREAK's finding names {breaker.student_count} students — the count "
            "is the AFFECTED submissions (S-A and S-B), not the class of three "
            "(CT-GRADE-12: naming affected student counts)"
        )
        assert "ungradeable_by_panel" in breaker.reason, (
            f"C-BREAK's finding reads {breaker.reason!r} — the reason names the "
            "breaker mark (CT-GRADE-12)"
        )
        budget = findings["C-BUDGET"]
        assert budget.student_count == 2, (
            f"C-BUDGET's finding reads {budget.student_count} students — again the "
            "affected two, not the class (CT-GRADE-12)"
        )
        assert "budget exhausted" in budget.reason, (
            f"C-BUDGET's finding reads {budget.reason!r} — the reason names the "
            "exhausted review budget (CT-GRADE-12)"
        )
        # The union: one criterion both breaker-marked and budget-exhausted is ONE
        # finding, its count the union of the affected students, its reason both.
        union = findings["C-UNION"]
        assert union.student_count == 2, (
            f"C-UNION's finding counts {union.student_count} — breaker-marked and "
            "budget-exhausted is ONE finding whose count is the UNION of the "
            "affected students, not the sum of the marks (CT-GRADE-12)"
        )
        assert "ungradeable_by_panel" in union.reason and "budget exhausted" in union.reason, (
            f"C-UNION's finding reads {union.reason!r} — both causes ride the one "
            "finding (CT-GRADE-12)"
        )
    finally:
        store.close()


def _seed_exhausted(cohort, submission_id, criterion_id):
    """One review_queue row whose reason carries the budget exhaustion — the
    disclosed stand-in for M-REVIEW's residual (`FR-REVIEW-04`): the shipped read
    matches the phrase in Python because the queue has no status column."""
    with cohort.transaction() as tx:
        tx.execute(
            "INSERT OR REPLACE INTO review_queue "
            "(queue_id, submission_id, criterion_id, reason) "
            "VALUES (:q, :s, :c, :r)",
            q=f"q-c12-{submission_id}-{criterion_id}",
            s=submission_id, c=criterion_id,
            r="review budget exhausted for this criterion (FR-REVIEW-04 residual)",
        )
