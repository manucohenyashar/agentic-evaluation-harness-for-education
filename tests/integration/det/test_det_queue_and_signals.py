"""The `M-DET` review-queue exclusion and scanning-signal cases: a deterministic
criterion never enters the teacher review queue (`TC-DET-04`), and an elevated
unresolved count alerts as a SCANNING problem — never item difficulty (`TC-DET-14`).
Test plan §5.11; issue #88.

**Isolation: rung 2/3** — real store, real package, real cohort ledger. TC-DET-04's
plan rung is 3 (real neighbouring modules): `M-REVIEW` — the queue's writer — has not
landed, so the queue is built directly in the DDL's row shape (the disclosed bypass
discipline `tests/support/orch_run.py` records) and the case asserts what the design
fixes about det's side of the boundary: the queue det found is the queue det left, and
det's routing vocabulary has no path into it.
"""

from __future__ import annotations

import pytest

from aeh.det import DeterministicEvaluator
from tests.support.det_vocabulary import (
    DET_COHORT_ID,
    open_det_store,
    seed_det_world,
    seed_selection_answers,
)

pytestmark = pytest.mark.integration

ISSUE = "#88"


# --- TC-DET-04 ------------------------------------------------------------------------------


def test_tc_det_04_deterministic_criteria_never_enter_the_review_queue(tmp_data_dir):
    """`TC-DET-04` (`FR-DET-06`) — a cohort with three deterministic criteria and a
    built review queue: ZERO deterministic criteria in the queue, asserted by querying
    the queue rows directly.

    The queue holds two judged entries when det runs (seeded directly — `M-REVIEW`'s
    writer has not landed; the disclosure is in the module docstring). After the cohort
    pass the queue is byte-identical: no row names M1/M2/M3, no row was added, and no
    score row for a deterministic criterion carries a `queued` routing — the one
    vocabulary value that would be a queue admission by another name (`CT-DET-04`)."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=("S01", "S02", "S03"),
            criteria=[
                {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
                {"criterion_id": "M2", "question_id": "Q2", "key": ("B",)},
                {"criterion_id": "M3", "question_id": "Q3", "key": ("B",)},
            ],
        )
        seed_selection_answers(
            store,
            cohort_id,
            [
                {"submission_id": "S01", "selection": "B"},
                {"submission_id": "S02", "selection": "C"},
                {"submission_id": "S03", "content_state": "present",
                 "selection_state": "ambiguous"},
            ],
        )
        # The built review queue: two judged entries awaiting a teacher — judged
        # criteria only, as M-REVIEW's admission would write them.
        cohort = store.cohort(cohort_id)
        with cohort.transaction() as tx:
            tx.execute(
                "INSERT INTO review_queue (queue_id, submission_id, criterion_id, "
                "reason) VALUES ('q-1', 'S01', 'C-judged-1', 'low_confidence')"
            )
            tx.execute(
                "INSERT INTO review_queue (queue_id, submission_id, criterion_id, "
                "reason) VALUES ('q-2', 'S02', 'C-judged-2', 'escalation')"
            )
        queue_before = cohort.query(
            "SELECT queue_id, submission_id, criterion_id, reason FROM review_queue "
            "ORDER BY queue_id"
        )

        report = DeterministicEvaluator(store).evaluate_cohort(run_id)
        assert report.criteria == 3 and report.evaluations == 9

        queue_after = cohort.query(
            "SELECT queue_id, submission_id, criterion_id, reason FROM review_queue "
            "ORDER BY queue_id"
        )
        assert [tuple(row) for row in queue_after] == [
            tuple(row) for row in queue_before
        ], (
            "the review queue changed during a deterministic pass — a deterministic "
            "criterion was admitted to the teacher's queue (FR-DET-06)"
        )
        assert all(
            row["criterion_id"] not in {"M1", "M2", "M3"} for row in queue_after
        ), (
            "a deterministic criterion appears in the review queue — the teacher "
            "would be billed minutes for arithmetic"
        )
        # The routing vocabulary is the boundary made visible: no score row for a
        # deterministic criterion carries 'queued' (or anything outside auto/triage).
        routings = cohort.query(
            "SELECT DISTINCT routing FROM criterion_score WHERE criterion_id IN "
            "('M1', 'M2', 'M3')"
        )
        assert {row["routing"] for row in routings} <= {"auto", "triage"}, (
            "a deterministic score row routed outside auto/triage — the 'queued' "
            "leak path CT-DET-04 names"
        )
    finally:
        store.close()


# --- TC-DET-14 ------------------------------------------------------------------------------


def test_tc_det_14_elevated_unresolved_count_alerts_as_a_scanning_problem(
    tmp_data_dir, monkeypatch
):
    """`TC-DET-14` (`FR-DET-07`) — a cohort with an elevated unresolved count on one
    question: per-question correct rate, blank count, unresolved count and most-chosen
    distractor are emitted, the unresolved-count alert fires, and the alert is labelled
    a **scanning** problem — never item difficulty.

    Hand count (20 submissions, one question `M1`, key B): 10 x B, 2 x C, 1 x A,
    1 blank, 6 ambiguous -> n = 20, correct = 10, correct_rate = 0.5, blank_count = 1,
    unresolved_count = 6, unresolved_rate = 0.3, most_chosen_distractor = C (2 > A's 1).
    The second question `M2` (everyone B) carries zero unresolved and must NOT alert —
    the alert is per question, not per cohort."""
    store = open_det_store(tmp_data_dir)
    try:
        submissions = tuple(f"S{i:02d}" for i in range(1, 21))
        run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=submissions,
            criteria=[
                {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
                {"criterion_id": "M2", "question_id": "Q2", "key": ("B",)},
            ],
        )
        from tests.support.det_vocabulary import seed_answer_region, seed_head_document

        m1_answers = (
            [{"submission_id": s, "selection": "B"} for s in submissions[:10]]
            + [{"submission_id": s, "selection": "C"} for s in submissions[10:12]]
            + [{"submission_id": submissions[12], "selection": "A"}]
            + [{"submission_id": submissions[13], "content_state": "blank"}]
            + [
                {"submission_id": s, "content_state": "present",
                 "selection_state": "ambiguous"}
                for s in submissions[14:]
            ]
        )
        for spec in m1_answers:
            s = spec["submission_id"]
            document_id = seed_head_document(store, cohort_id, s)
            seed_answer_region(store, cohort_id, document_id, "Q1",
                               content_state=spec.get("content_state", "present"),
                               selection_state=spec.get("selection_state"),
                               selection=spec.get("selection"))
            seed_answer_region(store, cohort_id, document_id, "Q2", selection="B")

        report = DeterministicEvaluator(store).evaluate_cohort(run_id)

        summaries = {s.criterion_id: s for s in report.summaries}
        m1 = summaries["M1"]
        assert (m1.n, m1.correct) == (20, 10)
        assert m1.correct_rate == pytest.approx(0.5)
        assert (m1.blank_count, m1.unresolved_count) == (1, 6)
        assert m1.most_chosen_distractor == "C"
        m2 = summaries["M2"]
        assert m2.unresolved_count == 0

        # The alert fired for exactly the elevated question, with the exact signal.
        assert len(report.alerts) == 1, (
            f"expected exactly one scanning alert, got {report.alerts!r} — the alert "
            "is per question (M2's clean count must not alert)"
        )
        alert = report.alerts[0]
        assert alert["criterion_id"] == "M1"
        assert alert["question_id"] == "Q1"
        assert alert["unresolved_count"] == 6
        assert alert["unresolved_rate"] == pytest.approx(0.3)
        assert alert["threshold"] == report.unresolved_alert_rate
        assert alert["kind"] == "scanning_problem", (
            "the alert is not labelled a scanning problem — an elevated unresolved "
            "count read as anything else misroutes the operator's response"
        )
        assert alert["reads_as"] == "rescan_queue_never_item_difficulty"
        # The label assertion's negative: no alert FIELD offers an item-difficulty
        # reading — the signal's label keys name the scanning kind and the rescan
        # queue, and nothing else (the only "difficulty" in the payload is the
        # never_item_difficulty negation itself).
        assert not any("difficulty" in key for key in alert)
        assert set(alert) >= {
            "criterion_id", "question_id", "n", "unresolved_count",
            "unresolved_rate", "threshold", "kind", "reads_as",
        }

        # The knob is env-gated (`CLAUDE.md` seam 3): a higher threshold silences the
        # alert; a lower one fires it; the report records the rate that applied.
        monkeypatch.setenv("HARNESS_DET_UNRESOLVED_ALERT_RATE", "0.5")
        quiet = DeterministicEvaluator(store).evaluate_cohort(run_id)
        assert quiet.alerts == ()
        assert quiet.unresolved_alert_rate == pytest.approx(0.5)
        monkeypatch.setenv("HARNESS_DET_UNRESOLVED_ALERT_RATE", "0.1")
        loud = DeterministicEvaluator(store).evaluate_cohort(run_id)
        assert [a["criterion_id"] for a in loud.alerts] == ["M1"]
        assert loud.unresolved_alert_rate == pytest.approx(0.1)
        # A garbage value falls back to the default — the knob must not stop grading.
        monkeypatch.setenv("HARNESS_DET_UNRESOLVED_ALERT_RATE", "not-a-number")
        fallback = DeterministicEvaluator(store).evaluate_cohort(run_id)
        assert fallback.unresolved_alert_rate == pytest.approx(0.05)
        assert len(fallback.alerts) == 1
    finally:
        store.close()
