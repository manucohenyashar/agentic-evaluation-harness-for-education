"""`TC-GRADE-C07` — nothing is ever substituted for a missing or unreviewed criterion (§6.11.14).

`CT-GRADE-07` (behaviour, §4.7 safety property): the grade is computed **only** from
criterion scores that actually exist for that submission — "no imputation of any kind:
no cohort mean, no default partial credit, no imputation by any other route." Guards
RISK-03 and RISK-11 through `FR-GRADE-08` / HLD `R26`; consumers `M-STATS`, `M-CONSOLE`.

The four steps the plan's block form pins, and where each lives here:

1. **no imputation, over `apply_policy` as a pure function** (rung 0) — the missing
   criterion's position holds *no value*, not a substituted one. The oracle that
   catches every substituted route at once is the marginal differential:
   total(with the criterion at v) − total(without it) == v, for the swept v. A
   substituted constant k shifts the no-input total by k, so the differential reads
   v−k — red for a cohort mean, a default partial credit, any route. The exactly-0
   substitution is invisible in a sum, so the coverage naming below catches it.
   The route's most fair-sounding shape — the cohort-mean filler — is EXECUTED as
   its own case beneath step 1 (the inversion idiom), not merely described.
2. **the consumer's right: every points figure traces to a stored row** (rung 3) —
   a delivered total must decompose exactly into the submission's OWN
   `criterion_score` rows. This is the adversarial construction's detector: the
   fixture seeds a cohort whose C2 mean over scored submissions is non-zero, then
   asserts the unreviewed submission's total == fsum of its own rows — the
   fair-sounding substitution ("so the class rollup is comparable and no student is
   disadvantaged by an unreviewed item") would add that mean and break the equality.
   It is the point at which a grade stops being a claim about one student's work.
3. **the four missing-shape sweep** (rung 3) — never scored, quarantined upstream
   (a row whose points is NULL — the extraction ran and delivered no figure),
   unreviewed provisional, `ungradeable_by_panel`. The first two contribute
   nothing and are named missing; the last two contribute their OWN stored figure
   and are counted provisional — the realistic bug treats one of the four
   differently (drops the breaker-refused figure, substitutes for the provisional
   one, or invents points for the quarantined row).
4. **the delivered artifact is incomplete and says so** (rung 4) — the export
   renders `incomplete`, the missing count and the named criteria, joining
   `CT-GRADE-04`'s coverage record, rather than a complete-looking mark.

Isolation: rung 0 for step 1 (pure seams, no store); rung 3 for steps 2-3 (real
store, real package, the real grading service); rung 4 for step 4 (the export
artifact). The socket guard is autouse. The `criterion_score` rows are written by
the vocabulary's disclosed `M-AGG` stand-in (`tests/support/grade_vocabulary.py`)
plus `_drive.write_state_row`'s escape hatch for the NULL-points and
breaker-refused shapes the derived pairing cannot express.
"""

from __future__ import annotations

import csv
import json
import math

import pytest

from aeh.grade import apply_policy, coverage_for
from aeh.pkg import default_grade_policy
from aeh.store import open_store
from tests.contract.grade._drive import (
    current_grades,
    criterion_rows,
    graded_run,
    write_state_row,
)
from tests.support.grade_vocabulary import score
from tests.support.impl import GRADE_MODULE, require

pytestmark = [pytest.mark.contract]

#: The sweep's fixture shape: three criteria so "missing one" is a partial sum, not
#: a degenerate all-or-nothing. C1 and C3 are fully scored for every submission; C2
#: is the criterion whose absence the sweep exercises.
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C3", "kind": "open", "scoring_model": "atomic"},
)

#: The scored figures every present C1/C3 carries — the baseline constants.
_P_C1 = 7.0
_P_C3 = 3.0
_PRESENT_SUM = math.fsum((_P_C1, _P_C3))

_BASE_ROWS = (
    ("S-A", "C1", "B2", _P_C1, "auto"),
    ("S-A", "C2", "B1", 2.0, "auto"),
    ("S-A", "C3", "B1", _P_C3, "auto"),
    ("S-B", "C1", "B2", _P_C1, "auto"),
    ("S-B", "C3", "B1", _P_C3, "auto"),
    # S-B's C2 never scored — the row's absence is the input side.
)


# --- Step 1: apply_policy substitutes nothing for a missing criterion -------------------------


def test_tc_grade_c07_step1_the_pure_seam_imputes_nothing_for_a_missing_criterion():
    """`TC-GRADE-C07` step 1 (`CT-GRADE-07`, rung 0) — for a score set with a missing
    criterion, `apply_policy`'s output contains **no value in that position** rather
    than a substituted one. The marginal differential enumerates the clause's three
    named routes (and every unnamed one): a substituted constant k makes the
    differential read v−k for every v, so a cohort mean, a default partial credit or
    any other constant substitution turns this red."""
    require(GRADE_MODULE, "apply_policy", issue="#101")
    require(GRADE_MODULE, "coverage_for", issue="#101")
    policy = default_grade_policy()
    present = [score("C1", _P_C1), score("C3", _P_C3)]
    absent = apply_policy(present, policy)

    # The no-imputation baseline: the absent criterion contributes nothing at all.
    assert absent.total == _PRESENT_SUM, (
        f"the missing criterion's position contributed {absent.total - _PRESENT_SUM} "
        "points — a substituted value where the clause requires absence "
        "(CT-GRADE-07: no cohort mean, no default partial credit, no route)"
    )
    # The marginal differential over the sweep values: exactly the criterion's own
    # contribution, for every value — the substitution detector.
    for value in (0.5, _P_C1, 12.0):
        filled = apply_policy([*present, score("C2", value)], policy)
        assert filled.total - absent.total == value, (
            f"adding a criterion scored {value} moved the total by "
            f"{filled.total - absent.total} — the missing position held a substituted "
            f"value (the differential must read {value} exactly; CT-GRADE-07)"
        )
    # And the coverage seam names the absence rather than papering over it: the
    # zero-substitution route (a substituted 0.0 is invisible in the sum) cannot
    # survive this naming, which the rung-3/4 steps assert at the artifact level.
    coverage = coverage_for(present, ("C1", "C2", "C3"))
    assert coverage.criteria_missing == 1, (
        f"the absent criterion counted {coverage.criteria_missing} missing — the "
        "coverage record must name the absence (CT-GRADE-07 joined with FR-GRADE-04)"
    )


def test_tc_grade_c07_the_mean_imputation_adversary_fails_the_step1_oracles():
    """`TC-GRADE-C07` step 1's executed adversary (`CT-GRADE-07`, rung 0) — the
    fair-sounding substitution, executed rather than described: a wrapper over
    `apply_policy` that fills every declared-but-missing criterion with the cohort
    mean — *so the class rollup is comparable and no student is disadvantaged by an
    unreviewed item*, exactly the route the clause refuses. Under it the mark passes
    the looks-complete check while FAILING both discriminators of the step above:
    the marginal differential reads v−k, and the coverage naming is defeated by the
    pre-fill. The inversion idiom (`CT-AGG-05`'s weighted construction, `CT-DET-03`'s
    collapse mutant): the mutant passes the functional check and fails the
    discriminating oracle the clause case pins — which is why the clause exists."""
    require(GRADE_MODULE, "apply_policy", issue="#101")
    require(GRADE_MODULE, "coverage_for", issue="#101")
    policy = default_grade_policy()
    present = [score("C1", _P_C1), score("C3", _P_C3)]
    declared = ("C1", "C2", "C3")
    # The cohort mean step 2's fixture constructs — non-zero, so the substitution
    # moves the total and the demonstration is not vacuous.
    cohort_mean = 2.0

    def imputing(scores, criterion_ids):
        """The mutant: fill every declared-but-missing criterion with the cohort
        mean BEFORE the policy reads the score set — the pre-fill is what defeats
        the coverage naming, which is the realistic implementation shape."""
        scored = {item.criterion_id for item in scores}
        filled = [*scores, *(
            score(criterion_id, cohort_mean)
            for criterion_id in criterion_ids if criterion_id not in scored
        )]
        return apply_policy(filled, policy)

    # The looks-complete check the imputation PASSES: the imputed mark's total
    # equals the full declared set's sum — nothing about it reads incomplete.
    imputed_absent = imputing(present, declared)
    assert imputed_absent.total == _PRESENT_SUM + cohort_mean, (
        "fixture bug: the mean-imputing construction did not substitute the mean "
        "— it cannot demonstrate the catch"
    )
    filled_coverage = coverage_for(
        [*present, score("C2", cohort_mean)], declared
    )
    assert filled_coverage.criteria_missing == 0, (
        "fixture bug: the pre-filled score set still names a criterion missing — "
        "the construction does not model the paper-over"
    )

    # Discriminator 1 — the no-imputation baseline FAILS under the mutant: the
    # absent criterion contributed exactly the mean.
    assert imputed_absent.total != _PRESENT_SUM, (
        "fixture bug: the imputed total coincided with the no-imputation baseline"
    )

    # Discriminator 2 — the marginal differential FAILS under the mutant: with the
    # mean k pre-filled, total(with v) − total(without) reads v−k for every v.
    for value in (0.5, _P_C1, 12.0):
        imputed_filled = imputing([*present, score("C2", value)], declared)
        differential = imputed_filled.total - imputed_absent.total
        assert differential == value - cohort_mean and differential != value, (
            f"fixture bug: at v={value} the imputer's differential read "
            f"{differential!r} — the construction does not model the v−k defect"
        )

    # The real module passes BOTH discriminators the mutant fails — the pair is
    # what makes the oracle discriminating rather than universally red.
    real_absent = apply_policy(present, policy)
    assert real_absent.total == _PRESENT_SUM, (
        "the real module's no-imputation baseline moved — the sweep's red below "
        "would not be attributable to the imputation"
    )
    real_filled = apply_policy([*present, score("C2", 0.5)], policy)
    assert real_filled.total - real_absent.total == 0.5, (
        "the real module's marginal differential moved — the oracle the mutant "
        "fails is no longer the shipped behaviour"
    )
    assert coverage_for(present, declared).criteria_missing == 1, (
        "the real module's coverage stopped naming the absence — the naming the "
        "pre-fill defeats is the shipped behaviour"
    )


# --- Step 2: every delivered figure traces to the submission's own stored rows ----------------


def test_tc_grade_c07_step2_delivered_totals_decompose_into_stored_criterion_scores(
    tmp_data_dir,
):
    """`TC-GRADE-C07` step 2 (`CT-GRADE-07`, rung 3) — the consumer's right in its
    strongest form: every points figure in a delivered grade resolves to a stored
    `criterion_score` row of that submission. The adversarial construction is in the
    fixture, disclosed here: the cohort's C2 mean over scored submissions is 2.0
    (non-zero, so a mean substitution moves the total), and the fair-sounding
    justification — *so the class rollup is comparable and no student is
    disadvantaged by an unreviewed item* — is exactly the route the clause refuses."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-A", "S-B"), criteria=_CRITERIA, rows=_BASE_ROWS
        )
        cohort = world.cohort

        # Fixture sanity gates: the construction is adversarial only if the mean is
        # real and non-zero, and only if the service actually delivered both grades.
        c2_rows = cohort.query(
            "SELECT submission_id, points FROM criterion_score WHERE criterion_id = 'C2'"
        )
        c2_mean = math.fsum(row["points"] for row in c2_rows) / len(c2_rows)
        assert c2_rows and c2_mean == 2.0, (
            f"fixture bug: the C2 cohort mean is {c2_mean!r} over {len(c2_rows)} rows "
            "— the adversarial construction needs a non-zero mean so a substitution "
            "moves the total"
        )
        by_id = {row["submission_id"]: row for row in current_grades(cohort, world.run_id)}
        assert set(by_id) == {"S-A", "S-B"}, (
            "fixture bug: the run did not deliver a grade per submission"
        )

        for submission_id, expected_total in (("S-A", 12.0), ("S-B", _PRESENT_SUM)):
            own = criterion_rows(cohort, submission_id)
            own_points = math.fsum(
                row["points"] for row in own if row["points"] is not None
            )
            row = by_id[submission_id]
            assert row["total"] == expected_total == own_points, (
                f"{submission_id}'s delivered total {row['total']!r} does not decompose "
                f"into its own stored criterion scores (fsum = {own_points!r}, expected "
                f"{expected_total!r}) — a figure derived from anything other than this "
                "submission's own rows is an imputation (CT-GRADE-07: every points "
                "figure traces to an actual criterion score)"
            )
        # The unreviewed submission says so, it does not borrow: the state and the
        # named absence are what make the smaller total honest.
        sb = by_id["S-B"]
        assert sb["state"] == "incomplete", (
            f"S-B's grade reads {sb['state']!r} — a submission with a missing input "
            "is incomplete, not silently complete (CT-GRADE-07 step 4's delivered form)"
        )
        assert json.loads(sb["missing_criteria"]) == ["C2"], (
            f"S-B's missing_criteria is {sb['missing_criteria']!r} — the delivered "
            "artifact must name the input it lacks (CT-GRADE-07 joined with CT-GRADE-08)"
        )
    finally:
        store.close()


# --- Step 3: the four missing shapes, and none is substituted for -----------------------------


def test_tc_grade_c07_step3_none_of_the_four_missing_shapes_yields_a_substituted_value(
    tmp_data_dir,
):
    """`TC-GRADE-C07` step 3 (`CT-GRADE-07`, rung 3) — the ways a criterion can be
    missing, swept, because the realistic bug treats one of the four differently:
    never scored (no row at all), quarantined upstream (a row whose points is NULL —
    the extraction ran and delivered no figure; the triage routing is the
    ingestion-failure population), unreviewed provisional (a row whose figure is the
    teacher-unconfirmed current points), and `ungradeable_by_panel` (the breaker
    refused a panel; `CT-ORCH-16` leaves the single-judge figure scored). The first
    two contribute nothing and are named missing; the last two contribute their OWN
    stored figure — dropping the breaker-refused figure would be a substitution by
    omission, substituting the provisional figure would be an imputation, and both
    are the same clause's violation."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-NEVER", "S-QUAR", "S-PROV", "S-REFUSED"),
            criteria=_CRITERIA,
            rows=[
                ("S-NEVER", "C1", "B2", _P_C1, "auto"),
                ("S-NEVER", "C3", "B1", _P_C3, "auto"),
                ("S-QUAR", "C1", "B2", _P_C1, "auto"),
                ("S-QUAR", "C3", "B1", _P_C3, "auto"),
                ("S-PROV", "C1", "B2", _P_C1, "auto"),
                ("S-PROV", "C2", "B3", 5.0, "provisional"),
                ("S-PROV", "C3", "B1", _P_C3, "auto"),
                ("S-REFUSED", "C1", "B2", _P_C1, "auto"),
                ("S-REFUSED", "C3", "B1", _P_C3, "auto"),
            ],
            compute=False,  # the special rows below must exist before the one pass
        )
        cohort = world.cohort
        # The two shapes the derived vocabulary cannot write: the disclosed escape
        # hatch (module docstring). Quarantined: the row exists, the figure is NULL,
        # routed triage — the ingestion-failure population the coverage seam counts
        # missing. Breaker-refused: the single-judge figure stands, routed
        # provisional (CT-AGG-C07's finding), state ungradeable_by_panel.
        write_state_row(
            cohort, "S-QUAR", "C2", "B0", None, "triage", "unresolved_selection"
        )
        write_state_row(
            cohort, "S-REFUSED", "C2", "B3", 4.0, "provisional", "ungradeable_by_panel"
        )
        world.service.compute_all(world.run_id)

        by_id = {row["submission_id"]: row for row in current_grades(cohort, world.run_id)}
        assert set(by_id) == {"S-NEVER", "S-QUAR", "S-PROV", "S-REFUSED"}, (
            "fixture bug: a submission was skipped — the sweep needs all four shapes "
            "delivered (TC-GRADE-C01's count equality is its own case)"
        )

        def missing_of(submission_id: str) -> list[str]:
            return json.loads(by_id[submission_id]["missing_criteria"] or "[]")

        # Shape 1 — never scored: contributes nothing, named missing, no substitute.
        never = by_id["S-NEVER"]
        assert never["total"] == _PRESENT_SUM, (
            f"the never-scored shape delivered total {never['total']!r} — a figure "
            "above the present rows' fsum is a substitution (CT-GRADE-07)"
        )
        assert never["state"] == "incomplete" and missing_of("S-NEVER") == ["C2"], (
            "the never-scored shape did not arrive as incomplete naming C2 — the "
            "absence must be named, not filled"
        )

        # Shape 2 — quarantined upstream: the row exists, the figure does not. Same
        # contract as never scored: nothing substituted, absence named.
        quar = by_id["S-QUAR"]
        assert quar["total"] == _PRESENT_SUM, (
            f"the quarantined shape delivered total {quar['total']!r} — a NULL-points "
            "row contributed, which is the default-partial-credit route in disguise "
            "(CT-GRADE-07)"
        )
        assert quar["state"] == "incomplete" and missing_of("S-QUAR") == ["C2"], (
            "the quarantined shape was not named missing — an unusable figure is an "
            "absence (the ingestion-failure population counts missing, CT-GRADE-07's "
            "sweep)"
        )

        # Shape 3 — unreviewed provisional: the row's OWN figure, exactly. Not
        # replaced by a reviewed value, not withheld, and judgment uncertainty is
        # never absence (CT-GRADE-08's own case carries the state differential).
        prov = by_id["S-PROV"]
        assert prov["total"] == math.fsum((_P_C1, 5.0, _P_C3)), (
            f"the unreviewed-provisional shape delivered total {prov['total']!r} — "
            "the provisional row must contribute its own stored figure and nothing "
            "else (a substituted figure is the clause's core violation)"
        )
        assert prov["state"] == "provisional" and missing_of("S-PROV") == [], (
            f"the provisional-input grade read {prov['state']!r} with missing "
            f"{missing_of('S-PROV')!r} — judgment uncertainty is never absence "
            "(CT-GRADE-08's biconditional, load-bearing for this sweep too)"
        )

        # Shape 4 — ungradeable_by_panel: the breaker refused a panel, but the
        # single-judge figure is scored (CT-ORCH-16's promise). It contributes its
        # own stored figure; dropping it would disadvantage the student by exactly
        # the figure — substitution by omission.
        refused = by_id["S-REFUSED"]
        assert refused["total"] == math.fsum((_P_C1, 4.0, _P_C3)), (
            f"the breaker-refused shape delivered total {refused['total']!r} — the "
            "ungradeable_by_panel row must contribute its own stored figure "
            "(CT-ORCH-16 leaves it scored); a dropped figure is substitution by "
            "omission, a replaced one is substitution outright"
        )
        assert refused["criteria_provisional"] == 1 and refused["criteria_missing"] == 0, (
            "the breaker-refused row was not counted provisional — the breaker's mark "
            "must not silently convert a scored figure into a missing one "
            "(CT-GRADE-07's sweep, CT-AGG-07's consumer obligation)"
        )
        assert missing_of("S-REFUSED") == [], (
            "the breaker-refused row was named missing despite its scored figure — "
            "the mark must not be dropped (CT-GRADE-07's sweep)"
        )
    finally:
        store.close()


# --- Step 4: the delivered artifact is incomplete and says so ---------------------------------


def test_tc_grade_c07_step4_the_delivered_artifact_says_it_is_incomplete(
    tmp_data_dir, monkeypatch
):
    """`TC-GRADE-C07` step 4 (`CT-GRADE-07`, rung 4) — the delivered artifact is
    *incomplete and says so* rather than complete and quietly wrong, joining
    `CT-GRADE-04`'s coverage record: the export renders the state, the missing
    count, and the named criteria for the submission with the missing input."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    export_dir = tmp_path_exports(monkeypatch, tmp_data_dir)
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-A", "S-B"), criteria=_CRITERIA, rows=_BASE_ROWS
        )
        path = world.service.export(world.run_id, 1, "csv")
        assert path.parent == export_dir and path.exists(), (
            f"the export landed at {path!r}, not under the configured export dir"
        )
        with path.open(newline="", encoding="utf-8") as handle:
            rows = {row["submission_id"]: row for row in csv.DictReader(handle)}
        assert set(rows) == {"S-A", "S-B"}, (
            "fixture bug: the export does not carry one row per graded submission"
        )
        incomplete = rows["S-B"]
        assert incomplete["state"] == "incomplete", (
            f"the export renders S-B as {incomplete['state']!r} — an artifact that "
            "does not say it is incomplete is a complete-looking mark quietly wrong "
            "(CT-GRADE-07 step 4)"
        )
        assert incomplete["criteria_missing"] == "1", (
            f"the export renders criteria_missing {incomplete['criteria_missing']!r} — "
            "the coverage record must ride the artifact (CT-GRADE-04's join)"
        )
        assert json.loads(incomplete["missing_criteria"]) == ["C2"], (
            f"the export renders missing_criteria {incomplete['missing_criteria']!r} — "
            "the artifact must name the input it lacks"
        )
        assert float(incomplete["total"]) == _PRESENT_SUM, (
            f"the export renders total {incomplete['total']!r} — the partial sum of "
            "the submission's own rows, never an imputed full mark (CT-GRADE-07)"
        )
    finally:
        store.close()


def tmp_path_exports(monkeypatch: pytest.MonkeyPatch, tmp_data_dir) -> Any:
    """Point the export knob at a per-test directory under the session tmp — the
    Windows-only seam discipline: `tmp_path` sits under `gettempdir()`, never under
    the repository, and `export_dir()` reads the knob at call time."""
    target = tmp_data_dir.parent / "grade-exports"
    monkeypatch.setenv("HARNESS_GRADE_EXPORT_DIR", str(target))
    return target
