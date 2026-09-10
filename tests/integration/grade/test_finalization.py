"""`TC-GRADE-09`, `TC-GRADE-10`, `TC-GRADE-11` — finalization is one batch action that
names its coverage first, happens with or without a teacher, and is all a review window
delays.

Test plan §5.14; `FR-GRADE-09`, `FR-GRADE-10`, `FR-GRADE-11`; `CT-GRADE-09`. The state
model (detailed-design.md §3.14) is the spine: `computed(provisional)` moves to `final`
**on window lapse or run completion**, and `finalize_batch` is the optional explicit
path. The review window is ADR-3's `review_window_hours` column on the shipped
`GradePolicy` (aeh/pkg.py), where null means *finalize on run completion* — the
configuration space the sweep walks.

`TC-GRADE-09` (rung 3): a 350-student class is finalized by one action that named its
coverage before it was taken, and the API assertion pins that no per-student
finalization action exists — the service's public names contain exactly one `final`
name, `finalize_batch`, and it takes no submission id. `TC-GRADE-10` (rung 2): the
three automatic scenarios plus the sweep — **no configuration exists in which
finalization waits indefinitely for a teacher action**, asserted over
`review_window_hours` ∈ {None, 0, 1, 24, 720} with both automatic paths armed. `TC-GRADE-11`
(rung 2): mid-window, the provisional grades are complete, visible and exportable — the
window delays finalization only.

**Written ahead of #101** (`M-GRADE`), reached through `open_grade(store)`
(`grade_vocabulary.py`). The design declares `coverage(run_id) -> CoverageSummary` and
`finalize_batch(run_id, actor) -> FinalizationRecord` (§3.14's Interfaces block) but
pins neither record's field set: `grades_by_state`, `finalized` and `coverage` are the
invented names declared in `grade_vocabulary.py`, reconciled at #101. The **automatic**
path has no Protocol member of its own, so it is probed through the service's own
declared pass — a `compute_all` re-invocation once the lapse/completion state has
changed (also declared in `grade_vocabulary.py`). This reading is the case's substance,
not a convenience: a module that finalizes only when a teacher calls something cannot
satisfy `FR-GRADE-10` at all.

**Disclosed stand-ins** (`grade_vocabulary.py`, header): the run-completion UPDATE —
`M-ORCH` is the run row's single writer (#61's control-row write), so the test writes
the `status = 'complete'` state its automatic path reads, exactly the pattern
`test_resume_and_rerun.py` uses; and `backdate_grades` for the lapse. The window is
measured from `computed_at` (the grade's issuance), the timestamp ADR-3's column names.

**Isolation:** rung 3 for `TC-GRADE-09` (real `M-ORCH` run and `M-PKG` package),
rung 2 for `TC-GRADE-10`/`TC-GRADE-11`.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from aeh.pkg import GradePolicy, PackageCatalog
from aeh.store import open_store
from tests.support.grade_vocabulary import (
    GRADE_BLOCKER,
    backdate_grades,
    grade_rows,
    write_criterion_scores,
)
from tests.support.impl import GRADE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration]

ISSUE = GRADE_BLOCKER


def _lapsed_computed_at() -> str:
    """A `computed_at` 25 hours in the past, derived at call time — the lapse cases
    measure the shipped 24-hour window against it, so a fixed date would red the case
    for the wrong reason on any machine whose clock has not reached it."""
    return (
        (datetime.now(timezone.utc) - timedelta(hours=25))
        .replace(microsecond=0)
        .isoformat()
    )

_PACKAGE = "pkg-orch"


def _set_window_policy(store, version, *, hours):
    """Set the run package's grade policy with ADR-3's window (`None` = finalize on
    completion). The version is a draft — `seed_package` leaves it unlocked — so the
    policy is set directly on it."""
    catalog = PackageCatalog(store.package(_PACKAGE), package_id=_PACKAGE)
    catalog.set_grade_policy(
        version, GradePolicy(combination="weighted_sum", review_window_hours=hours)
    )


def _complete_run(cohort, run_id):
    """The disclosed stand-in for #61's control-row write: the run state the automatic
    finalization path reads (`test_resume_and_rerun.py`'s pattern)."""
    with cohort.transaction() as tx:
        tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=run_id)


def _seed_scored_run(store, submissions, *, hours):
    """Store with a seeded run, a window policy, and every submission fully scored."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    criteria = (
        {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
        {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
    )
    _orchestrator, run_id, version = seed_run(
        store, submissions=submissions, criteria=criteria
    )
    _set_window_policy(store, version, hours=hours)
    cohort = store.cohort(ORCH_COHORT_ID)
    write_criterion_scores(
        cohort,
        [
            (sid, "C1", "B2", 7.0, "auto")
            for sid in submissions
        ]
        + [
            (sid, "C2", "B1", 6.0, "auto")
            for sid in submissions
        ],
    )
    return run_id, cohort


def _states(grades):
    return {g["submission_id"]: g["state"] for g in grades if g["is_current"]}


# --- TC-GRADE-09: one batch action for the whole class, coverage named first -----------------


def test_tc_grade_09_one_batch_action_finalizes_the_class_and_names_its_coverage(
    tmp_data_dir,
):
    """`TC-GRADE-09` — a 350-student class: `coverage` names the class's state before
    the action, `finalize_batch` takes the whole class in one call, its record names the
    coverage it was given, and every grade is final afterwards."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        submissions = tuple(f"S{i:03d}" for i in range(1, 351))
        run_id, cohort = _seed_scored_run(store, submissions, hours=None)

        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        svc.compute_all(run_id)

        # The coverage is named BEFORE the action is taken — this call precedes
        # finalize_batch structurally, and its counts are the hand-computed class state.
        summary = svc.coverage(run_id)
        named = summary.grades_by_state
        assert named.get("provisional") == 350 and named.get("final") == 0, (
            f"the coverage named before the action reads {named!r} — a fully-judged "
            "unfinalized class is 350 provisional and 0 final (TC-GRADE-09, exact "
            "behaviour)"
        )

        record = svc.finalize_batch(run_id, "operator-a")

        assert record.finalized == 350, (
            f"the batch action finalized {record.finalized!r} grades, expected 350 — "
            "one action covers the whole class (TC-GRADE-09, FR-GRADE-09)"
        )
        assert record.coverage == summary.grades_by_state, (
            f"the record's coverage {record.coverage!r} is not the coverage named "
            f"before the action {summary.grades_by_state!r} — the action must do what "
            "it named (FR-GRADE-09: names its coverage before it is taken)"
        )
        states = set(_states(grade_rows(cohort)).values())
        assert states == {"final"}, (
            f"after the batch action the current grades read {states!r} — the whole "
            "class must be final (TC-GRADE-09)"
        )
    finally:
        store.close()


def test_tc_grade_09_no_per_student_finalization_action_exists_in_the_api(tmp_data_dir):
    """`TC-GRADE-09`'s API assertion — the service exposes exactly one finalization
    action and it is batch-shaped: no other public name contains `final`, and
    `finalize_batch` takes no submission id.

    (`compute_one` and `amend` take submission ids by design — they are not finalization
    actions; the case's clause binds finalization.)"""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        run_id, _cohort = _seed_scored_run(store, ("S-API-1",), hours=None)
        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)

        final_names = {
            name for name in dir(type(svc)) if "final" in name.lower()
        }
        assert final_names == {"finalize_batch"}, (
            f"the service exposes finalization name(s) {sorted(final_names)} — a "
            "per-student finalization action (`finalize_one`, a finalizing `amend`) "
            "would appear here and violates FR-GRADE-09's API clause"
        )
        parameters = inspect.signature(type(svc).finalize_batch).parameters
        assert "submission_id" not in parameters, (
            "finalize_batch takes a submission_id — the one finalization action must "
            "be batch-shaped (TC-GRADE-09: no per-student action exists in the API)"
        )
    finally:
        store.close()


# --- TC-GRADE-10: finalization happens with or without a teacher -----------------------------


def test_tc_grade_10_without_a_window_finalization_occurs_on_run_completion(
    tmp_data_dir,
):
    """`TC-GRADE-10`, scenario 1 — no review window: the grades are provisional while
    the run runs, and final on the service's first pass after the run completes."""
    store = open_store(tmp_data_dir)
    try:
        submissions = ("S-W1", "S-W2", "S-W3")
        run_id, cohort = _seed_scored_run(store, submissions, hours=None)
        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        svc.compute_all(run_id)
        assert set(_states(grade_rows(cohort)).values()) == {"provisional"}, (
            "grades issued on an incomplete run must read provisional — finalization "
            "on completion has nothing to complete yet (TC-GRADE-10 scenario 1)"
        )

        _complete_run(cohort, run_id)
        svc.compute_all(run_id)  # the service's own pass, not a teacher action

        assert set(_states(grade_rows(cohort)).values()) == {"final"}, (
            "the run is complete and the grades are still not final — with no window, "
            "finalization occurs on run completion (TC-GRADE-10 scenario 1, "
            "FR-GRADE-10, ADR-3: null window means finalize on completion)"
        )
    finally:
        store.close()


def test_tc_grade_10_a_lapsed_window_finalizes_without_a_teacher(tmp_data_dir):
    """`TC-GRADE-10`, scenario 2 — a 24-hour window that lapses: provisional at
    issuance, final once the window has lapsed, with the run still incomplete and no
    teacher action anywhere."""
    store = open_store(tmp_data_dir)
    try:
        submissions = ("S-W4", "S-W5")
        run_id, cohort = _seed_scored_run(store, submissions, hours=24)
        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        svc.compute_all(run_id)
        assert set(_states(grade_rows(cohort)).values()) == {"provisional"}

        # The lapse: computed_at moves 25 hours back — past the 24-hour window — by
        # the disclosed stand-in (`grade_vocabulary.py` header). The run stays
        # incomplete: the lapse path, not the completion path, must fire.
        backdate_grades(cohort, _lapsed_computed_at())
        svc.compute_all(run_id)  # the service's own pass, not a teacher action

        assert set(_states(grade_rows(cohort)).values()) == {"final"}, (
            "the 24-hour window lapsed 25 hours ago and the grades are still not "
            "final — finalization occurs at the lapse of the window (TC-GRADE-10 "
            "scenario 2, FR-GRADE-10)"
        )
    finally:
        store.close()


def test_tc_grade_10_an_open_window_leaves_finalization_pending(tmp_data_dir):
    """`TC-GRADE-10`, scenario 3 — a window still open: finalization is pending. The
    service's own pass must not finalize early — that is the discriminating half of the
    window's meaning."""
    store = open_store(tmp_data_dir)
    try:
        submissions = ("S-W6",)
        run_id, cohort = _seed_scored_run(store, submissions, hours=24)
        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        svc.compute_all(run_id)
        svc.compute_all(run_id)  # a second pass with nothing elapsed

        assert set(_states(grade_rows(cohort)).values()) == {"provisional"}, (
            "the review window is still open and the grades did not stay provisional "
            "— finalization is pending until the window lapses or the run completes "
            "(TC-GRADE-10 scenario 3, FR-GRADE-10)"
        )
    finally:
        store.close()


@pytest.mark.parametrize("hours", [None, 0, 1, 24, 720])
def test_tc_grade_10_no_configuration_waits_indefinitely_for_a_teacher(
    tmp_data_dir, hours
):
    """`TC-GRADE-10`'s sweep — for every window configuration the shipped vocabulary
    admits as realistic (None, 0, 1, 24 and 720 hours), once the run is complete and
    the window has lapsed, the service's own pass finalizes every grade.

    Both automatic paths are armed at once, so the assertion is the union the case
    demands: **no configuration exists** in which finalization waits indefinitely for a
    teacher action. A configuration that could wait forever (a window that never
    lapses, a completion that never fires) fails here."""
    store = open_store(tmp_data_dir)
    try:
        submissions = ("S-W7", "S-W8")
        run_id, cohort = _seed_scored_run(store, submissions, hours=hours)
        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        svc.compute_all(run_id)

        # Arm both automatic paths: the run completes and the window lapses.
        _complete_run(cohort, run_id)
        backdate_grades(cohort, _lapsed_computed_at())
        svc.compute_all(run_id)  # the service's own pass, not a teacher action

        assert set(_states(grade_rows(cohort)).values()) == {"final"}, (
            f"window configuration review_window_hours={hours!r} left grades unfinalized "
            "after completion and lapse — a configuration in which finalization waits "
            "indefinitely for a teacher action is prohibited (TC-GRADE-10's sweep, "
            "FR-GRADE-10, CT-GRADE-09)"
        )
    finally:
        store.close()


# --- TC-GRADE-11: mid-window, the grade is complete, visible and exportable ------------------


def test_tc_grade_11_mid_window_the_provisional_grade_is_complete_visible_exportable(
    tmp_data_dir,
):
    """`TC-GRADE-11` — with a configured window still open, the provisional grade
    carries its full record (exact total, exact coverage, the timestamp the window is
    measured from), is the current visible revision, and exports. The window delays
    finalization only — nothing about the provisional state withholds content."""
    store = open_store(tmp_data_dir)
    try:
        submissions = ("S-M1",)
        run_id, cohort = _seed_scored_run(store, submissions, hours=24)
        # Make the coverage non-trivial: one auto-accepted, one provisional input.
        # The provisional class lives on `routing` (CT-AGG-06), and the aggregation
        # `state` follows it — `provisional` routing pairs with
        # `provisional_unreviewed` (the vocabulary's disclosed derivation). The
        # writtenahead draft set `state = 'provisional'` directly, conflating the
        # two columns; the schema's CHECK (FR-AGG-11) refuses that literal, so the
        # reconciliation at #101 moves the class to the column that owns it.
        with cohort.transaction() as tx:
            tx.execute(
                "UPDATE criterion_score SET points = :p, routing = :r, state = :s "
                "WHERE submission_id = :sid AND criterion_id = 'C2'",
                p=6.0, r="provisional", s="provisional_unreviewed", sid="S-M1",
            )
        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        svc.compute_all(run_id)

        grades = grade_rows(cohort)
        assert len(grades) == 1
        row = grades[0]
        assert row["state"] == "provisional", (
            "mid-window the grade must read provisional (finalization pending) — "
            "TC-GRADE-11's precondition"
        )
        # Complete: the exact value and the full coverage record are on the row.
        assert row["total"] == pytest.approx(13.0, abs=1e-9), (
            f"the mid-window total is {row['total']!r}, expected 13.0 — the window "
            "delays finalization only, never completeness (FR-GRADE-11)"
        )
        coverage = (
            row["criteria_total"], row["criteria_auto"], row["criteria_reviewed"],
            row["criteria_provisional"], row["criteria_missing"],
        )
        assert coverage == (2, 1, 0, 1, 0), (
            f"the mid-window coverage record reads {coverage}, expected "
            "(2, 1, 0, 1, 0) — the grade is complete throughout the window "
            "(FR-GRADE-11, FR-GRADE-04)"
        )
        assert row["computed_at"], (
            "the mid-window grade carries no computed_at — the timestamp the window "
            "is measured from must be on the grade (ADR-3's issuance timestamp)"
        )
        # Visible: it is the current revision.
        assert row["is_current"], (
            "the mid-window grade is not the current revision — provisional grades "
            "are visible throughout the window (FR-GRADE-11)"
        )
        # Exportable: the export succeeds mid-window.
        exported = svc.export(run_id, row["revision"], "csv")
        assert exported is not None and str(exported) != "", (
            "the mid-window export produced nothing — provisional grades are "
            "exportable throughout the window (TC-GRADE-11, FR-GRADE-11, CT-GRADE-06)"
        )
    finally:
        store.close()
