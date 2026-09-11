"""`TC-GRADE-C09` — finalization happens with or without a teacher, and never waits (§6.11.14).

`CT-GRADE-09` (behaviour): "Assert finalization happens **with or without a
teacher**: automatically on run completion, or at the lapse of the configured
review window. Then the categorical negative — assert there is **no configuration
in which finalization waits indefinitely**, by sweeping the window setting
including absent, zero and extreme values, and asserting every one terminates
(HLD `R60`). Then `finalize_batch` as **one action for the whole class** that
**names its coverage before it is taken**, asserted on the pre-action summary
rather than the post-action state."

The limbs, in the row's order:

- **the two automatic paths** (rung 3, green): a null-window run settles every
  present-input grade on COMPLETION; a windowed run settles at the LAPSE — both
  without any teacher action, any queue item, or any amendment.
- **the termination sweep** (rung 3, green): window ∈ {absent, 0, 1, 10^9} — every
  configuration reaches `final` (HLD `R60`'s no-waiting clause; ADR-3's null
  window means completion is the path, not an indefinite wait).
- **the batch action** (rung 3, green): `finalize_batch` is ONE action for the
  whole class — it settles every current provisional grade and its record echoes
  the PRE-action coverage, the summary named before the settlement, not the
  post-action state. `incomplete` grades are not the batch's population: they are
  the operator's, and the batch leaves them.

Isolation: rung 3 — real store, real package, real service. The socket guard is
autouse; `criterion_score` rows are the vocabulary's disclosed `M-AGG` stand-in;
`backdate_grades` is the disclosed timestamp stand-in for the lapse.
"""

from __future__ import annotations

import pytest

from aeh.pkg import GradePolicy
from aeh.store import open_store
from tests.contract.grade._drive import (
    complete_run,
    current_grades,
    graded_run,
    set_policy,
)
from tests.support.impl import GRADE_MODULE, require
from tests.support.grade_vocabulary import backdate_grades

pytestmark = [pytest.mark.contract]

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)

_ROWS = (
    ("S-ONE", "C1", "B2", 7.0, "auto"),
    ("S-ONE", "C2", "B2", 5.0, "auto"),
)


def test_tc_grade_c09_finalization_happens_on_run_completion_without_a_teacher(
    tmp_data_dir,
):
    """`TC-GRADE-C09`'s completion path (`CT-GRADE-09`, rung 3) — finalization
    happens WITHOUT a teacher: the run completes, and the pass settles every grade
    automatically. No review action, no amendment, no batch call."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-ONE",),
            criteria=_CRITERIA,
            rows=(("S-ONE", "C1", "B2", 7.0, "auto"), ("S-ONE", "C2", "B2", 5.0, "auto")),
        )  # default policy: review_window_hours=None
        complete_run(world.cohort, world.run_id)
        world.service.compute_all(world.run_id)
        (row,) = current_grades(world.cohort, world.run_id)
        assert row["state"] == "final" and row["finalized_at"], (
            f"the completed run left the grade at {row['state']!r} — finalization "
            "happens WITHOUT a teacher, automatically on run completion "
            "(CT-GRADE-09, FR-GRADE-10)"
        )
    finally:
        store.close()


def test_tc_grade_c09_finalization_happens_at_the_window_lapse_without_a_teacher(
    tmp_data_dir,
):
    """`TC-GRADE-C09`'s lapse path (`CT-GRADE-09`, rung 3) — a configured window
    delays only; its edge settles the grade with no teacher action (HLD `R60`)."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-ONE",),
            criteria=_CRITERIA,
            rows=(("S-ONE", "C1", "B2", 7.0, "auto"), ("S-ONE", "C2", "B2", 5.0, "auto")),
            compute=False,
        )
        set_policy(store, world.version, GradePolicy(review_window_hours=48))
        world.service.compute_all(world.run_id)
        (pending,) = current_grades(world.cohort, world.run_id)
        assert pending["state"] == "provisional", (
            f"fixture bug: the windowed grade reads {pending['state']!r} — the "
            "window is open, the grade is issued provisional"
        )
        backdate_grades(world.cohort, _hours_ago(72))
        world.service.compute_all(world.run_id)
        (lapsed,) = current_grades(world.cohort, world.run_id)
        assert lapsed["state"] == "final" and lapsed["finalized_at"], (
            f"the lapsed window did not finalize ({lapsed['state']!r}) — the lapse "
            "of the configured review window is a finalization path without a "
            "teacher (CT-GRADE-09, HLD R60)"
        )
    finally:
        store.close()


def test_tc_grade_c09_no_window_configuration_waits_indefinitely(tmp_data_dir):
    """`TC-GRADE-C09`'s categorical negative (`CT-GRADE-09`, rung 3) — swept across
    the window setting including absent, zero and extreme values, EVERY
    configuration terminates: on a completed run, the pass settles every grade no
    matter what the window says. There is no configuration in which finalization
    waits indefinitely (HLD `R60`; FR-GRADE-10's no-teacher-action clause)."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-ONE",),
            criteria=_CRITERIA,
            rows=(("S-ONE", "C1", "B2", 7.0, "auto"), ("S-ONE", "C2", "B2", 5.0, "auto")),
            compute=False,
        )
        complete_run(world.cohort, world.run_id)  # the run completes up front
        for window in (None, 0, 1, 10**9):
            set_policy(store, world.version, GradePolicy(review_window_hours=window))
            world.service.compute_all(world.run_id)
            (row,) = current_grades(world.cohort, world.run_id)
            assert row["state"] == "final" and row["finalized_at"], (
                f"window {window!r}: the grade waits at {row['state']!r} — NO "
                "configuration in which finalization waits indefinitely; every "
                "window setting terminates (CT-GRADE-09's categorical negative, "
                "HLD R60)"
            )
    finally:
        store.close()


def test_tc_grade_c09_finalize_batch_is_one_action_naming_its_coverage(
    tmp_data_dir,
):
    """`TC-GRADE-C09`'s batch limb (`CT-GRADE-09`, rung 3) — `finalize_batch` is ONE
    action for the whole class: it names its coverage BEFORE the settlement (the
    record echoes the pre-action summary, not the post-action state), settles every
    current provisional grade, and leaves the incomplete ones — they are the
    operator's, not the batch's."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-FULL", "S-GONE"),
            criteria=_CRITERIA,
            rows=(
                ("S-FULL", "C1", "B2", 7.0, "auto"),
                ("S-FULL", "C2", "B2", 5.0, "auto"),
                ("S-GONE", "C1", "B2", 7.0, "auto"),
                # S-GONE's C2 never scored — the incomplete class.
            ),
        )
        # The PRE-action summary, named before the action is taken.
        pre = world.service.coverage(world.run_id)
        pre_counts = dict(pre.grades_by_state)
        assert pre_counts["provisional"] == 1 and pre_counts["incomplete"] == 1, (
            f"fixture bug: the pre-action coverage is {pre_counts!r} — one "
            "provisional and one incomplete"
        )

        record = world.service.finalize_batch(world.run_id, actor="operator-7")

        assert dict(record.coverage) == pre_counts, (
            f"the record echoes {dict(record.coverage)!r}, but the coverage named "
            f"before the action was {pre_counts!r} — the batch must name its "
            "coverage BEFORE it is taken (CT-GRADE-09's pre-action artifact)"
        )
        assert record.finalized == 1, (
            f"the batch settled {record.finalized} grades — exactly the current "
            "provisional class, one action for the whole class (CT-GRADE-09)"
        )
        assert record.actor == "operator-7" and record.settled_at, (
            "the record lost its actor or timestamp (CT-GRADE-09's record)"
        )
        # Post-action: the provisional settled; the incomplete is NOT the batch's.
        grades = {
            row["submission_id"]: row
            for row in current_grades(world.cohort, world.run_id)
        }
        assert grades["S-FULL"]["state"] == "final" and grades["S-FULL"]["finalized_at"], (
            "the batch did not settle the provisional grade (CT-GRADE-09)"
        )
        assert grades["S-GONE"]["state"] == "incomplete" and grades["S-GONE"]["finalized_at"] is None, (
            f"the batch stamped the incomplete grade ({grades['S-GONE']['state']!r}) "
            "— an incomplete grade is a missing input awaiting an operator, never a "
            "batch deliverable (CT-GRADE-09 with CT-GRADE-08)"
        )
    finally:
        store.close()


def _hours_ago(hours: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()