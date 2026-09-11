"""`TC-GRADE-C15` — the error discipline: absence routes, it never crashes and never zeroes (§6.11.14).

`CT-GRADE-15` (error): "Assert a missing criterion score yields `criteria_missing`,
an `incomplete` grade and an operator item — and, explicitly, **never an exception
and never a zero**, sweeping both as forbidden outcomes. Then the timing assertion
that gives the module its no-unrecoverable-failure property: a policy referencing a
criterion that no longer exists is raised at **run start**, not at grading time.
Assert the run refuses to start, so grading is never reached in that state."

The limbs, in the row's order:

- **the missing-input outcomes** (rung 3, green): a submission with one criterion
  absent delivers `criteria_missing == 1`, an `incomplete` state, and an operator
  queue item whose reason names a RESCAN — the operator's action — never a marking
  decision addressed to the teacher. Its total is the fsum of its own present rows
  only.
- **the forbidden-outcome sweep** (rung 3, green): across policy shapes — default,
  gated, weighted — a pass over a missing input (i) raises nothing and (ii)
  substitutes no zero: the missing criterion has NO criterion_score row (a
  substituted zero would BE one, and would zero the missing count), and the
  all-missing shape queues one item per criterion. The no-exception limb is the
  sweep's frame: every `compute_all` call in it simply returns.
- **the run-start refusal** (`[m_orch]`, writtenahead): the timing half. The landed
  run-creation path validates nothing of the kind — a policy naming a ghost
  criterion sails into grading and surfaces (if at all) at computation time — so
  this limb is red-by-design, keyed in `WRITTEN_AHEAD_BLOCKERS` on the disclosed
  surface `aeh.orch:validate_grade_policy` (issue #107), the run-start refusal,
  by the same invented-and-disclosed naming as `aeh.orch:evaluate_alerts`.

Isolation: rung 3 — real store, real package, real service. The socket guard is
autouse; `criterion_score` rows are the vocabulary's disclosed `M-AGG` stand-in.
"""

from __future__ import annotations

import pytest

from aeh.pkg import GradePolicy, GateRule
from aeh.store import open_store
from tests.contract.grade._drive import (
    COHORT,
    current_grades,
    criterion_rows,
    graded_run,
    set_policy,
)
from tests.support.impl import GRADE_MODULE, ORCH_MODULE, require
from tests.support.orch_run import orch_cfg

pytestmark = [pytest.mark.contract]

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C3", "kind": "open", "scoring_model": "atomic"},
)

#: One row per present criterion, one criterion never scored: the missing input.
_ROWS = (
    ("S-MISS", "C1", "B2", 7.0, "auto"),
    ("S-MISS", "C3", "B1", 3.0, "auto"),
    ("S-FULL", "C1", "B2", 7.0, "auto"),
    ("S-FULL", "C2", "B2", 5.0, "auto"),
    ("S-FULL", "C3", "B1", 3.0, "auto"),
)


def _queue_items(cohort, submission_id):
    return cohort.query(
        "SELECT queue_id, criterion_id, reason FROM review_queue "
        "WHERE submission_id = :s",
        s=submission_id,
    )


def test_tc_grade_c15_the_missing_input_yields_incomplete_and_an_operator_rescan_item(
    tmp_data_dir,
):
    """`TC-GRADE-C15` (`CT-GRADE-15`, rung 3) — a missing criterion score yields the
    missing count, the `incomplete` state, and an OPERATOR item whose reason is a
    rescan directive, never a teacher marking decision; the complete twin in the
    same run stays untouched."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-MISS", "S-FULL"), criteria=_CRITERIA, rows=_ROWS
        )
        cohort = world.cohort
        grades = {
            row["submission_id"]: row
            for row in current_grades(world.cohort, world.run_id)
        }
        miss = grades["S-MISS"]
        assert int(miss["criteria_missing"]) == 1, (
            f"the missing criterion scored {miss['criteria_missing']!r} in the "
            "coverage — criteria_missing must count the absent input (CT-GRADE-15)"
        )
        assert miss["state"] == "incomplete", (
            f"the missing-input grade reads {miss['state']!r} — absence yields the "
            "incomplete state (CT-GRADE-15)"
        )
        assert miss["missing_criteria"] == '["C2"]', (
            f"the grade names {miss['missing_criteria']!r} missing — the record "
            "names the specific missing input, not a count alone (CT-GRADE-15)"
        )
        assert float(miss["total"]) == 10.0, (
            f"the total is {miss['total']!r}, not the fsum of the present rows — "
            "the absent criterion contributes nothing, substituted or otherwise "
            "(CT-GRADE-15 with CT-GRADE-07)"
        )

        items = _queue_items(cohort, "S-MISS")
        assert len(items) == 1 and items[0]["criterion_id"] == "C2", (
            f"the operator queue holds {[(i['criterion_id'], i['reason']) for i in items]!r} "
            "— exactly one item, for the missing criterion (CT-GRADE-15)"
        )
        reason = str(items[0]["reason"]).lower()
        assert "rescan" in reason, (
            f"the operator item reads {items[0]['reason']!r} — the routing names a "
            "RESCAN of the document, the operator's action (CT-GRADE-15)"
        )
        assert "mark" not in reason and "regrade" not in reason, (
            f"the operator item reads {items[0]['reason']!r} — an absence is an "
            "ingestion failure routed to the operator, never a marking decision "
            "addressed to the teacher (CT-GRADE-08's owner boundary)"
        )
        # The differential: the fully-scored twin in the same run earned no queue
        # item and no incomplete state — the discipline is per-submission.
        full = grades["S-FULL"]
        assert full["state"] != "incomplete" and _queue_items(cohort, "S-FULL") == [], (
            "the fully-scored twin was swept into the missing-input discipline — "
            "the incomplete state and the operator item belong to the submission "
            "whose input is absent, no one else (CT-GRADE-15's differential)"
        )
    finally:
        store.close()


def test_tc_grade_c15_the_pass_never_raises_and_never_substitutes_a_zero(
    tmp_data_dir,
):
    """`TC-GRADE-C15`'s forbidden-outcome sweep (`CT-GRADE-15`, rung 3) — across
    policy shapes, a pass over a missing input (i) raises nothing: every
    `compute_all` call here simply returns, and the sweep's frame would fail the
    case if one raised; (ii) substitutes no zero: the absent criterion has NO
    criterion_score row — a substituted zero would be exactly that row — and the
    missing count stays at one. The all-missing shape queues one item per
    criterion: no absence is collapsed into another's item."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-MISS", "S-NONE"),
            criteria=_CRITERIA,
            rows=(
                ("S-MISS", "C1", "B2", 7.0, "auto"),
                ("S-MISS", "C3", "B1", 3.0, "auto"),
            ),
            compute=False,  # the policy shape is installed before each pass
        )
        shapes = [
            ("default policy", GradePolicy()),
            ("gate on the missing criterion", GradePolicy(
                gate=GateRule(criterion_id="C2", minimum=0.0),
            )),
            ("weighted", GradePolicy(weights=(("C1", 2.0), ("C3", 1.0)))),
            ("best k of n", GradePolicy(combination="best_k_of_n", k=2)),
        ]
        for label, policy in shapes:
            set_policy(store, world.version, policy)
            world.service.compute_all(world.run_id)  # must raise nothing
            row = {
                item["submission_id"]: item
                for item in current_grades(world.cohort, world.run_id)
            }["S-MISS"]
            assert int(row["criteria_missing"]) == 1 and row["state"] == "incomplete", (
                f"{label}: the missing input read "
                f"({row['criteria_missing']!r}, {row['state']!r}) — absence "
                "counts and reads incomplete under every policy shape "
                "(CT-GRADE-15's sweep)"
            )
            ghost = criterion_rows(world.cohort, "S-MISS")
            assert all(item["criterion_id"] != "C2" for item in ghost), (
                f"{label}: a criterion_score row exists for the absent criterion "
                f"({[item['criterion_id'] for item in ghost]!r}) — a substituted "
                "zero would be exactly that row; absence is never scored "
                "(CT-GRADE-15's no-zero clause)"
            )
            items = _queue_items(world.cohort, "S-MISS")
            assert [i["criterion_id"] for i in items] == ["C2"], (
                f"{label}: the operator queue holds "
                f"{[i['criterion_id'] for i in items]!r} — the absent criterion "
                "earns its operator item (CT-GRADE-15)"
            )

        # The all-missing shape: no present criterion at all — one item per
        # criterion, all three counted missing, and still no exception.
        none_row = {
            item["submission_id"]: item
            for item in current_grades(world.cohort, world.run_id)
        }["S-NONE"]
        assert int(none_row["criteria_missing"]) == 3 and none_row["state"] == "incomplete", (
            f"the all-missing shape read ({none_row['criteria_missing']!r}, "
            f"{none_row['state']!r}) — every absent criterion counts, and the "
            "grade is still issued as incomplete, not crashed out of (CT-GRADE-15)"
        )
        assert [i["criterion_id"] for i in _queue_items(world.cohort, "S-NONE")] == [
            "C1", "C2", "C3"
        ], (
            "the all-missing shape queued fewer items than absent criteria — no "
            "absence collapses into another's item (CT-GRADE-15)"
        )
    finally:
        store.close()


@pytest.mark.writtenahead
def test_tc_grade_c15_a_policy_referencing_a_missing_criterion_is_refused_at_run_start(
    tmp_data_dir,
):
    """`TC-GRADE-C15`'s timing limb (`CT-GRADE-15`, rung 3, `[m_orch]`) — a policy
    referencing a criterion that no longer exists is refused at RUN START, not at
    grading time: the run refuses to start, so grading is never reached in that
    state.

    Writtenahead on the disclosed `aeh.orch:validate_grade_policy` (#107): the
    landed run-creation path validates nothing of the kind, so the surface is
    named-and-waited (the `aeh.orch:evaluate_alerts` naming precedent). When an
    orch story lands it, this test loses the marker and becomes the standing
    assertion that the ghost-criterion policy dies at run start."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    validate_grade_policy = require(
        ORCH_MODULE, "validate_grade_policy", issue="#107"
    )
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-ONE",), criteria=_CRITERIA, rows=(
                ("S-ONE", "C1", "B2", 7.0, "auto"),
            ),
            compute=False,
        )
        # Fixture gate: under the VALID policy the pipeline reaches grading — one
        # grade row, revision 1. The post-refusal assertions below are only
        # meaningful against a fixture that demonstrably grades when not refused;
        # without this gate they would pass on a fixture that cannot grade at all.
        set_policy(store, world.version, GradePolicy())
        world.service.compute_all(world.run_id)
        assert len(current_grades(world.cohort, world.run_id)) == 1, (
            "fixture bug: the run did not grade under its valid policy — the "
            "post-refusal assertions would be vacuous"
        )

        # The ghost policy: weights naming a criterion the version never declared,
        # installed through the real M-SETUP path the operator would use.
        ghost_policy = GradePolicy(weights=(("C-GONE", 1.0),))
        set_policy(store, world.version, ghost_policy)

        # The refusal's shape, on the disclosed surface: the error names the
        # criterion that no longer exists, or the operator cannot fix the package.
        with pytest.raises(Exception) as refused:
            validate_grade_policy(world.version, ghost_policy)
        assert "C-GONE" in str(refused.value), (
            f"the run-start refusal named nothing ({refused.value!r}) — the error "
            "must name the criterion that no longer exists, or the operator cannot "
            "fix the package (CT-GRADE-15's timing clause)"
        )

        # The refusal is terminal AT RUN START: a new run created against the
        # ghost-policy version through the real run-creation path never starts,
        # so grading is never reached in that state.
        with pytest.raises(Exception) as start_refused:
            world.orchestrator.create_run(
                COHORT, world.version, orch_cfg("edge-local")
            )
        # (the refusal's message shape is pinned on the direct surface call
        # above; here the assertion is the refusal itself)
        # No run came to be: the run table still holds exactly the original run —
        # the refusal prevented the run row, not merely the grading.
        runs = world.cohort.query(
            "SELECT run_id FROM run WHERE package_version_id = :v ORDER BY run_id",
            v=world.version,
        )
        assert [row["run_id"] for row in runs] == [world.run_id], (
            f"a run row exists for the refused start ({[row['run_id'] for row in runs]!r}) "
            "— the run must refuse to START, so grading is never reached in that "
            "state (CT-GRADE-15's timing clause)"
        )
        # And the original run's ledger is untouched: the ghost policy installed
        # after its valid pass must not have triggered any re-grade.
        ledger = current_grades(world.cohort, world.run_id)
        assert len(ledger) == 1 and ledger[0]["revision"] == 1, (
            "the refused policy produced a new revision on the original run — "
            "the refusal must leave grading unreached (CT-GRADE-15)"
        )
    finally:
        store.close()