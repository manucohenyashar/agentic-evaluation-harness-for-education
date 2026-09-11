"""`TC-GRADE-C01` — every submission is graded automatically, and no setting gates it (§6.11.14).

`CT-GRADE-01` (behaviour): "every submission in the run receives a `submission_grade`
row automatically — no per-student teacher action at any point." Two sentences, two
limbs, and the plan is explicit that the second is the unusual one:

- the **count equality**: one current grade per submission in the run — *including
  the quarantined and the incomplete*, the populations a cautious implementation
  silently skips. A silently-skipped population fails the equality, not an
  exception;
- the **negative, asserted over configuration**: a design requiring per-student
  confirmation is a defect, not a configuration choice (HLD `R56`, RISK-11). So the
  case sweeps the policy vocabulary's settings — the gate rule, both selection
  rules, and the review window including absent, zero and long — and asserts every
  one still delivers a grade row for **every** submission, the incomplete ones
  included. A configuration that withheld a row would make the sweep red.

The sibling unit file `tests/unit/grade/test_apply_policy_purity.py` carries the
rung-0 half of the same clause; this case is the persisted, whole-cohort form.

Isolation: rung 3 (real store, real package, real service). The socket guard is
autouse, so the one `compute_all` call is asserted model-free by construction. The
`criterion_score` rows are the vocabulary's disclosed `M-AGG` stand-in.
"""

from __future__ import annotations

import pytest

from aeh.pkg import GradePolicy, GateRule, default_grade_policy
from aeh.store import open_store
from tests.contract.grade._drive import current_grades, graded_run
from tests.support.impl import GRADE_MODULE, require

pytestmark = [pytest.mark.contract]

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)

_SUBMISSIONS = ("S-FULL", "S-MISS", "S-NONE")

#: S-FULL is fully scored; S-MISS has C1 only (C2 never scored); S-NONE has nothing.
#: The quarantined shape is `S-NONE`'s sibling at the row level — a submission whose
#: extraction never delivered a figure is indistinguishable, at grading time, from
#: one never submitted for scoring; both are covered here as the never-scored shape.
_ROWS = (
    ("S-FULL", "C1", "B2", 7.0, "auto"),
    ("S-FULL", "C2", "B1", 2.0, "auto"),
    ("S-MISS", "C1", "B2", 7.0, "auto"),
)


def test_tc_grade_c01_one_call_grades_every_submission_including_the_incomplete(
    tmp_data_dir,
):
    """`TC-GRADE-C01` (`CT-GRADE-01`, rung 3) — the count equality: one
    `compute_all` call persists a current `submission_grade` row for every
    submission in the run, the fully-scored, the partially-missing and the
    all-missing alike. The incomplete population is where a cautious implementation
    skips students, so the assertion reads the WHOLE run's submissions and requires
    the delivered set to equal it — no exception raised, no row omitted, no
    per-student action anywhere in the path."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA, rows=_ROWS
        )
        grades = current_grades(world.cohort, world.run_id)
        delivered = {row["submission_id"] for row in grades}
        assert len(grades) == len(_SUBMISSIONS) and delivered == set(_SUBMISSIONS), (
            f"{len(grades)} grade rows delivered for {len(_SUBMISSIONS)} submissions "
            f"(missing: {set(_SUBMISSIONS) - delivered}, extra: "
            f"{delivered - set(_SUBMISSIONS)}) — every submission in the run gets a "
            "grade automatically, including the quarantined and incomplete ones "
            "(CT-GRADE-01, FR-GRADE-01; a silently-skipped population is RISK-11)"
        )
        # The incomplete populations are graded, and graded honestly: their state
        # names the absence rather than omitting the student.
        by_id = {row["submission_id"]: row for row in grades}
        assert by_id["S-FULL"]["state"] == "provisional", (
            "fixture bug: the fully-scored submission did not deliver a settled-shape "
            "grade — the run is open, so the state is provisional"
        )
        assert by_id["S-MISS"]["state"] == "incomplete", (
            f"S-MISS graded {by_id['S-MISS']['state']!r} — a submission with a "
            "missing input is graded incomplete, not skipped (CT-GRADE-01: the "
            "incomplete population is graded too)"
        )
        assert by_id["S-NONE"]["state"] == "incomplete", (
            f"S-NONE graded {by_id['S-NONE']['state']!r} — an all-missing submission "
            "still gets its grade row automatically (CT-GRADE-01)"
        )
    finally:
        store.close()


@pytest.mark.parametrize(
    "label, policy",
    [
        pytest.param("default_window_null", default_grade_policy(), id="default"),
        pytest.param(
            "gate_met",
            GradePolicy(gate=GateRule(criterion_id="C1", minimum=1.0)),
            id="gate-met",
        ),
        pytest.param(
            "gate_refused",
            GradePolicy(gate=GateRule(criterion_id="C2", minimum=5.0)),
            id="gate-refused",
        ),
        pytest.param(
            "weighted", GradePolicy(weights=(("C1", 2.0), ("C2", 1.0))), id="weighted"
        ),
        pytest.param(
            "best_k", GradePolicy(combination="best_k_of_n", k=1), id="best-k-of-n"
        ),
        pytest.param(
            "drop_lowest", GradePolicy(combination="drop_lowest_n", drop=1),
            id="drop-lowest-n",
        ),
        pytest.param(
            "window_zero", GradePolicy(review_window_hours=0), id="window-0"
        ),
        pytest.param(
            "window_long", GradePolicy(review_window_hours=24 * 30), id="window-30d"
        ),
    ],
)
def test_tc_grade_c01_no_configuration_introduces_a_per_student_gate(
    tmp_data_dir, label, policy
):
    """`TC-GRADE-C01`'s second sentence (`CT-GRADE-01`, rung 2-3) — the negative,
    swept over the closed policy vocabulary: no setting — a gate rule (met or
    refused), either selection rule, the review window absent, zero or long —
    introduces a per-student gate. Every configuration still delivers one grade row
    per submission; a refusal (the gate, a missing input) shapes the ROW's figures
    or state, it never withholds the row, because a design that waits for a teacher
    is a defect the sweep exists to catch (HLD `R56`, RISK-11)."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA, rows=_ROWS,
            compute=False,  # the policy must be installed before the one pass
        )
        from tests.contract.grade._drive import set_policy

        set_policy(store, world.version, policy)
        world.service.compute_all(world.run_id)

        grades = current_grades(world.cohort, world.run_id)
        delivered = {row["submission_id"] for row in grades}
        assert len(grades) == len(_SUBMISSIONS) and delivered == set(_SUBMISSIONS), (
            f"configuration {label!r} delivered {len(grades)} grade rows for "
            f"{len(_SUBMISSIONS)} submissions — a setting that withholds a grade row "
            "is the per-student gate the clause names a defect (CT-GRADE-01, R56)"
        )
    finally:
        store.close()
