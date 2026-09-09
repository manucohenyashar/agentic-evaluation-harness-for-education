"""`CT-DET-04` — never admitted to the teacher review queue (`TC-DET-C04`).

Case of test plan §6.11.11; issue #90 (TS-68). Green by design — `M-DET`
shipped via #246/#249.

The clause: a deterministic criterion is **never** admitted to the teacher
review queue, on any path (`FR-DET-06`, HLD `R54`); unresolved selections go
to the **operator** queue as a scanning problem. A teacher's minutes are for
judgment, not for scanner triage.

The clause discriminator: the FR-level case (TS-33's) builds a queue, runs one
pass, and diffs it; this case asserts REACHABILITY — the property over every
path, not one observed run. Every routing state a deterministic score can hold
(`auto` for scored rows, `triage` for unresolved) is produced and swept, and
none of them may name the teacher queue: `review_queue` is untouched by every
pass, no row exists for a deterministic criterion under ANY routing, and the
`routing` vocabulary of the written rows is closed at `auto`/`triage` — the
`queued` value would be a queue admission by another name. The operator half:
unresolved rows route to `triage` and the report's alert names the rescan
queue, so the scanning problem lands where scanners are fixed.

**Disclosed rung-3 half**: the plan's oracle is a query-level reachability
assertion over `M-REVIEW`'s actual admission query. `M-REVIEW` is not shipped
yet (#108 is four stories out; the TS-33 integration track recorded the same
deviation), so the reachability is asserted over the surfaces that exist and
that the admission query must read — the `routing` vocabulary and the
`review_queue` table — and the live-query assertion lands with `M-REVIEW`.
"""

from __future__ import annotations

import pytest

from aeh.det import DeterministicEvaluator
from tests.support.det_vocabulary import (
    open_det_store,
    seed_det_world,
    seed_selection_answers,
)

pytestmark = pytest.mark.contract

from tests.contract.det._doubles import ISSUE  # noqa: F401 — register citation


def _seed_mixed_cohort(store):
    """A cohort that produces every routing state a deterministic score can
    hold: scored-correct and scored-incorrect rows route `auto`; ambiguous,
    multiple-marks and absent reads route `triage`. Returns
    `(run_id, cohort_id)`."""
    run_id, _version, cohort_id = seed_det_world(
        store,
        submissions=(
            "S-hit", "S-miss", "S-ambiguous", "S-multi", "S-absent",
        ),
        criteria=[
            {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
            {"criterion_id": "M2", "question_id": "Q2", "key": ("B",)},
        ],
    )
    seed_selection_answers(
        store, cohort_id,
        [
            {"submission_id": "S-hit", "selection": "B"},
            {"submission_id": "S-miss", "selection": "C"},
            {"submission_id": "S-ambiguous", "content_state": "present",
             "selection_state": "ambiguous"},
            {"submission_id": "S-multi", "regions": [
                {"content_state": "present", "selection_state": None},
                {"content_state": "present", "selection_state": None},
            ]},
            {"submission_id": "S-absent", "omit_document": True},
        ],
    )
    return run_id, cohort_id


def test_tc_det_c04_no_routing_state_reaches_the_teacher_queue(tmp_data_dir):
    """`TC-DET-C04` (swept over every routing state) — a pass over a cohort
    that produces BOTH routing states a deterministic score can hold: every
    written row's routing is inside the closed `auto`/`triage` vocabulary
    (never `queued`), the `review_queue` table is byte-identical before and
    after, and NO row anywhere in the score table names a deterministic
    criterion while carrying a queue-shaped state or routing. A deterministic
    criterion cannot reach the teacher's queue because the vocabulary of the
    rows this module writes has no path there."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, cohort_id = _seed_mixed_cohort(store)
        cohort = store.cohort(cohort_id)
        queue_before = cohort.query(
            "SELECT queue_id, submission_id, criterion_id, reason FROM "
            "review_queue ORDER BY queue_id"
        )

        report = DeterministicEvaluator(store).evaluate_cohort(run_id)
        assert report.criteria == 2 and report.evaluations == 10

        rows = list(cohort.query(
            "SELECT submission_id, criterion_id, band, state, routing FROM "
            "criterion_score"
        ))
        assert len(rows) == 10
        # Every routing state the module can produce, observed in the sweep:
        routings = {row["routing"] for row in rows}
        assert routings == {"auto", "triage"}, (
            f"TC-DET-C04: routing vocabulary observed was {sorted(routings)} "
            "— the sweep did not produce both states; the reachability claim "
            "would be vacuous."
        )
        # The closed vocabulary: no third value anywhere — `queued` would be
        # a teacher-queue admission by another name.
        assert routings <= {"auto", "triage"}
        # And no state/routing pair names the teacher's queue for a
        # deterministic criterion, under ANY routing the module writes.
        queue_shaped = cohort.query(
            "SELECT submission_id, criterion_id FROM criterion_score WHERE "
            "routing = 'queued' OR state = 'provisional_unreviewed'"
        )
        assert list(queue_shaped) == [], (
            f"TC-DET-C04: queue-shaped rows for deterministic criteria: "
            f"{[dict(r) for r in queue_shaped]}."
        )

        queue_after = cohort.query(
            "SELECT queue_id, submission_id, criterion_id, reason FROM "
            "review_queue ORDER BY queue_id"
        )
        assert [tuple(r) for r in queue_after] == \
            [tuple(r) for r in queue_before], (
                "TC-DET-C04: the review queue changed during a deterministic "
                "pass — an admission path exists."
            )
    finally:
        store.close()


def test_tc_det_c04_unresolved_goes_to_the_operator_as_a_scanning_problem(
        tmp_data_dir):
    """`TC-DET-C04` (the operator half) — unresolved selections route to
    `triage`, the operator's queue, as a SCANNING problem: every unresolved
    row carries `routing = 'triage'`, the report's alert for an elevated
    unresolved count names the rescan queue and never an item-difficulty
    reading, and no unresolved row asked the teacher queue for anything. The
    two queues stay disjoint by column."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, cohort_id = _seed_mixed_cohort(store)
        report = DeterministicEvaluator(store).evaluate_cohort(run_id)
        # Hand count: Q1 — ambiguous, multi-mark and absent are unreadable (3);
        # Q2 — the batch helper seeds Q1 only, so every submission's Q2 read is
        # absent (5). 3 + 5 = 8 unresolved across the 10 evaluations.
        assert report.unresolved == 8, (
            f"TC-DET-C04: {report.unresolved} unresolved across 5 submissions "
            "x 2 criteria — the operator population is missing."
        )

        cohort = store.cohort(cohort_id)
        unresolved = list(cohort.query(
            "SELECT submission_id, criterion_id, state, routing, points FROM "
            "criterion_score WHERE state = 'unresolved_selection'"
        ))
        assert len(unresolved) == 8
        for row in unresolved:
            assert row["routing"] == "triage", (
                f"TC-DET-C04: {row['submission_id']}/{row['criterion_id']} "
                f"routed {row['routing']!r} — the scanning problem did not "
                "land in the operator's queue."
            )
            assert row["points"] is None

        # The alert language is operator-facing: kind names the scanner, the
        # disposition names the rescan queue, and nothing offers a
        # difficulty reading to hang a teacher-minute on.
        scanning = [a for a in report.alerts if a["kind"] == "scanning_problem"]
        assert scanning, (
            "TC-DET-C04: no scanning alert fired for the unresolved "
            "population — the operator was not told."
        )
        for alert in scanning:
            assert alert["reads_as"] == "rescan_queue_never_item_difficulty"
            assert not any("difficulty" in key for key in alert)
    finally:
        store.close()
