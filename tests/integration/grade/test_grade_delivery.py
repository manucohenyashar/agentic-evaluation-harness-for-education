"""`TC-GRADE-01`, `TC-GRADE-08`, and the persisted limb of `TC-GRADE-02` — the grade
service delivers a grade for every submission with zero teacher actions, records which
policy version produced each one, and never withholds a grade over a provisional input.

Test plan §5.14. `TC-GRADE-01` (`FR-GRADE-01`, `NFR-SYS-04`, rung 3): a completed run of
350 submissions — the sizing class the whole system is built around — yields one
`submission_grade` row per submission from a single `compute_all` call, with no
per-student action anywhere in the path. `TC-GRADE-02`'s second oracle limb
(`policy_version` recorded on every grade) is asserted here rather than in the rung-0
file because it is a property of the **persisted** row. `TC-GRADE-08`
(`FR-GRADE-06`, rung 2): a grade with provisional inputs is issued and exportable and
marked `provisional` — the prohibition limb asserts that no population of provisional
inputs, up to and including an all-provisional one, withholds the grade; the state
differential against `incomplete` (CT-GRADE-08: judgment uncertainty is never absence)
is the `TC-GRADE-07` rung-2 half's, in `test_incomplete_and_routing.py`.

**Written ahead of #101** (`M-GRADE`, Phase 1), which lands `aeh.grade`. Reached through
the invented rung-2 constructor `open_grade(store)` (`tests/support/grade_vocabulary.py`,
the `open_review` precedent); the service methods called are §3.14's declared Protocol
members (`compute_all`, `export`).

**Interfaces assumed of #101 and of the landing schema** (all declared in
`grade_vocabulary.py`, reconciled at #101's landing):

| Name | Status |
|---|---|
| `open_grade(store)` | **invented** constructor — see above |
| `svc.compute_all(run_id)` | **declared** (§3.14 Protocol); its return is not pinned and not asserted — the oracle is the ledger's own rows |
| `svc.export(run_id, revision, "csv")` | **declared** member, **assumed call shape** — a run-wide export at a revision; the exact signature reconciles at #101. TC-GRADE-17's golden-file oracle is its own case (not this issue's); here the assertion is only that export succeeds for a provisional grade |
| `submission_grade.policy_version` | **assumed column** (HLD §9.6, not in this repository) — non-null and identical across one batch |
| `criterion_score(submission_id, criterion_id, band, points, state)` | **assumed post-#91 shape** — #101's chain runs through #91, so the columns exist when `open_grade` does |

**Disclosed stand-ins.** `write_criterion_scores` writes the `criterion_score` rows the
production writer (`M-AGG`) alone may write (`CT-AGG`'s Requires row); this is test
scaffolding standing in for it, writing exactly the rows it will write. The run is
seeded through the shipped `seed_run` fixture (real store, real Tier P package, real
cohort ledger); its work units are not enumerated because grading reads the run row's
package version and the criterion scores, not the work ledger.

**Isolation:** rung 3 for `TC-GRADE-01` (real neighbouring modules — `M-ORCH`'s run and
`M-PKG`'s package), rung 2 for the rest (real store, no model).
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support.grade_vocabulary import (
    grade_rows,
    write_criterion_scores,
)
from tests.support.impl import GRADE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#101"

#: The plan's sizing class: 350 submissions, the cohort the grade service must deliver
#: in one call (TC-GRADE-01, and PERF-07's same figure at NFR-GRADE-03).
_SUBMISSIONS = tuple(f"S{i:03d}" for i in range(1, 351))
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)


def _full_cohort_rows(submissions, *, state="auto"):
    """Two fully-scored criteria per submission — no missing input anywhere."""
    return [
        (sid, cid, "B2" if cid == "C1" else "B1", 7.0 if cid == "C1" else 6.0, state)
        for sid in submissions
        for cid in ("C1", "C2")
    ]


def _review_queue_count(cohort) -> int:
    return cohort.query("SELECT COUNT(*) AS n FROM review_queue")[0]["n"]


# --- TC-GRADE-01: one call, every submission, zero teacher actions ---------------------------


def test_tc_grade_01_one_call_grades_the_whole_class_with_zero_teacher_actions(
    tmp_data_dir,
):
    """`TC-GRADE-01` — a completed 350-submission run: `compute_all` persists one
    `submission_grade` row per submission, and the path takes no teacher action at any
    point (the review queue stays empty; the test makes no per-student service call)."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_id, _version = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA
        )
        cohort = store.cohort(ORCH_COHORT_ID)
        write_criterion_scores(cohort, _full_cohort_rows(_SUBMISSIONS))

        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        # The one call. Everything below reads the ledger back — no per-student action
        # is issued by the test, which is the case's second clause.
        svc.compute_all(run_id)

        grades = grade_rows(cohort)
        assert len(grades) == len(_SUBMISSIONS), (
            f"{len(grades)} submission_grade rows for {len(_SUBMISSIONS)} submissions — "
            "the service must deliver a grade for every submission in the run "
            "(TC-GRADE-01, FR-GRADE-01)"
        )
        assert {g["submission_id"] for g in grades} == set(_SUBMISSIONS), (
            "the graded set does not equal the run's submission set — a submission was "
            "skipped or duplicated"
        )
        assert _review_queue_count(cohort) == 0, (
            "grading a fully-judged cohort created review-queue rows — a teacher action "
            "was injected into a path the case requires to be action-free "
            "(TC-GRADE-01: zero teacher actions, NFR-SYS-04)"
        )
    finally:
        store.close()


# --- TC-GRADE-02's persisted limb: the policy version is on every row ------------------------


def test_tc_grade_02_policy_version_is_recorded_on_every_persisted_grade(tmp_data_dir):
    """`TC-GRADE-02`'s second oracle limb — every persisted grade records which policy
    version produced it.

    Asserted at rung 2 because it is a property of the row, not of the pure
    computation; `which policy version` changes over revisions is `TC-GRADE-12`'s limb
    (`test_recompute_on_correction.py`)."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        submissions = _SUBMISSIONS[:5]
        _orchestrator, run_id, _version = seed_run(
            store, submissions=submissions, criteria=_CRITERIA
        )
        cohort = store.cohort(ORCH_COHORT_ID)
        write_criterion_scores(cohort, _full_cohort_rows(submissions))

        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        open_grade(store).compute_all(run_id)

        grades = grade_rows(cohort)
        assert len(grades) == len(submissions)
        unversioned = [g["submission_id"] for g in grades if not g["policy_version"]]
        assert not unversioned, (
            f"grades for {unversioned} carry no policy_version — every grade must "
            "record which policy version produced it (TC-GRADE-02, FR-GRADE-02)"
        )
        assert len({g["policy_version"] for g in grades}) == 1, (
            "one compute_all batch produced grades under differing policy_version "
            "values — a batch is graded under exactly one policy version, so a split "
            "means the version is being read from the wrong place"
        )
    finally:
        store.close()


# --- TC-GRADE-08: provisional inputs issue, and never withhold -------------------------------


def test_tc_grade_08_a_provisional_input_issues_and_exports_a_provisional_grade(
    tmp_data_dir,
):
    """`TC-GRADE-08` — a grade over mixed auto and provisional inputs is issued, marked
    `provisional`, exact in its total, and exportable.

    The prohibition limb's first half: a provisional input is a scored input — the grade
    stands on it, at its exact value, and the export does not withhold it."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        submissions = ("S-P01",)
        _orchestrator, run_id, _version = seed_run(
            store, submissions=submissions, criteria=_CRITERIA
        )
        cohort = store.cohort(ORCH_COHORT_ID)
        write_criterion_scores(
            cohort,
            [
                ("S-P01", "C1", "B2", 8.0, "auto"),
                ("S-P01", "C2", "B1", 6.0, "provisional"),
            ],
        )

        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        svc.compute_all(run_id)

        grades = grade_rows(cohort)
        assert len(grades) == 1, (
            "a grade over a provisional input was not issued — no code path may "
            "withhold a grade on account of a provisional input (TC-GRADE-08, "
            "FR-GRADE-06)"
        )
        row = grades[0]
        assert row["state"] == "provisional", (
            f"the grade's state is {row['state']!r}, expected 'provisional' — the "
            "provisional input must be visible on the grade, not laundered into a "
            "settled-looking state (TC-GRADE-08)"
        )
        assert row["total"] == pytest.approx(14.0, abs=1e-9), (
            f"the total over 8.0 + 6.0 is {row['total']!r}, expected 14.0 — the "
            "provisional input's points must enter the total at face value "
            "(exact value, TC-GRADE-08)"
        )
        exported = svc.export(run_id, row["revision"], "csv")
        assert exported, (
            "the export of a provisional grade came back empty — the grade must be "
            "exportable throughout, provisional included (TC-GRADE-08, FR-GRADE-06)"
        )
    finally:
        store.close()


def test_tc_grade_08_an_all_provisional_population_still_issues_a_grade(tmp_data_dir):
    """`TC-GRADE-08`'s prohibition limb, second half — the limit case: every input
    provisional, and the grade still issues.

    A grade that waits for settlement anywhere in the pipeline would withhold here
    forever; `provisional` is a marking, not a refusal (the window delays finalization,
    not issuance — `FR-GRADE-11`)."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        submissions = ("S-P02",)
        _orchestrator, run_id, _version = seed_run(
            store, submissions=submissions, criteria=_CRITERIA
        )
        cohort = store.cohort(ORCH_COHORT_ID)
        write_criterion_scores(
            cohort,
            [
                ("S-P02", "C1", "B1", 5.0, "provisional"),
                ("S-P02", "C2", "B1", 4.0, "provisional"),
            ],
        )

        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        open_grade(store).compute_all(run_id)

        grades = grade_rows(cohort)
        assert len(grades) == 1, (
            "an all-provisional population issued no grade — judgment uncertainty "
            "withholds nothing (TC-GRADE-08's prohibition limb; `incomplete` is "
            "caused exclusively by ingestion failure, CT-GRADE-08)"
        )
        assert grades[0]["state"] != "incomplete", (
            "an all-provisional population was marked `incomplete` — judgment "
            "uncertainty is never absence (CT-GRADE-08); the state differential's "
            "exact form is TC-GRADE-07's rung-2 half"
        )
        assert grades[0]["total"] == pytest.approx(9.0, abs=1e-9), (
            f"the total over 5.0 + 4.0 is {grades[0]['total']!r}, expected 9.0 — "
            "provisional points enter at face value (exact value, TC-GRADE-08)"
        )
    finally:
        store.close()
