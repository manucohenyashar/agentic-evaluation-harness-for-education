"""The `M-DET` cohort-pass cases against the real store: the score row's judged-free
shape (`TC-DET-02`), the blank/unresolved separation (`TC-DET-05`), the item statistics
(`TC-DET-06`), the label-mode separation and the shared statistics filter (`TC-DET-08`),
and the audit record's deterministic shape (`TC-DET-10`). Test plan §5.11; issue #88.

Every figure asserted here is **hand-computed in the case docstring** from the seeded
answer table — the oracle is the number, not the code's own output.

**Isolation: rung 2/3** — real store, real Tier P package, real cohort ledger, real
Tier D statistics; the run row is `M-ORCH`'s own writer (`seed_det_world`).

**Disclosed rung deviation on TC-DET-06**: the plan marks it Unit / rung 0, but the
shipped surface of `FR-DET-07` is the cohort pass plus the `item_stats` read API — no
pure summary function exists to call at rung 0. The oracle is unchanged (the
hand-computed reference); the case runs it one rung up, and the deviation is recorded
here rather than silently downgraded.
"""

from __future__ import annotations

import json

import pytest

from aeh.det import DETERMINISTIC_EXCLUSION, DET_STATEMENTS, DeterministicEvaluator
from tests.support.det_vocabulary import (
    DET_COHORT_ID,
    open_det_store,
    seed_det_world,
    seed_selection_answers,
)

pytestmark = pytest.mark.integration

ISSUE = "#88"


def _evaluator(store):
    return DeterministicEvaluator(store)


def _durable_query(store, sql, **params):
    return store.durable().query(sql, **params)


def _cohort_query(store, cohort_id, sql, **params):
    return store.cohort(cohort_id).query(sql, **params)


# --- TC-DET-02 ------------------------------------------------------------------------------


def test_tc_det_02_scored_deterministic_criterion_carries_no_judged_trace(
    tmp_data_dir, network_guard
):
    """`TC-DET-02` (`FR-DET-02`) — a scored deterministic criterion carries
    `judge_count = 0`, `agreement IS NULL`, and NO `verdict` rows exist for it: a
    consumer computing over verdicts finds none, and must not read that as missing
    data (`CT-DET-02`)."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=("S01", "S02"),
            criteria=[
                {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
            ],
        )
        seed_selection_answers(
            store,
            cohort_id,
            [
                {"submission_id": "S01", "selection": "B"},
                {"submission_id": "S02", "selection": "C"},
            ],
        )
        evaluator = _evaluator(store)

        score = evaluator.evaluate(run_id, "S01", "M1")
        assert score.judge_count == 0, (
            "a deterministic score reported a judge count — no judge exists on this "
            "path, and a non-zero count would let a consumer read it as panel-scored"
        )
        assert score.agreement is None

        row = _cohort_query(
            store, cohort_id,
            "SELECT judge_count, agreement, band, points FROM criterion_score "
            "WHERE submission_id = :s AND criterion_id = 'M1'",
            s="S01",
        )[0]
        assert row["judge_count"] == 0
        assert row["agreement"] is None, (
            "the stored score row carries an agreement figure — deterministic rows "
            "have no panel to agree with (RISK-07's mechanism)"
        )
        assert row["band"] == "correct"

        # The row-absence half, by join: no verdict row exists whose work unit belongs
        # to the deterministic criterion.
        verdicts = _cohort_query(
            store, cohort_id,
            "SELECT COUNT(*) AS n FROM verdict WHERE work_id IN "
            "(SELECT work_id FROM work_unit WHERE criterion_id = 'M1')",
        )[0]["n"]
        assert verdicts == 0, (
            f"{verdicts} verdict rows exist for a deterministic criterion — a panel "
            "scored what the design says is pure lookup (CT-DET-02)"
        )
        network_guard.assert_no_network()
    finally:
        store.close()


# --- TC-DET-05 ------------------------------------------------------------------------------


def test_tc_det_05_blank_and_unresolved_counts_are_separate_figures(tmp_data_dir):
    """`TC-DET-05` (`FR-DET-03`, `FR-DET-04`) — a cohort mixing blank, ambiguous and
    absent regions: `blank_count` and `unresolved_count` are SEPARATE figures, each
    matching its hand count; conflating them in either direction is detectable.

    Hand count over the twelve submissions (single-select `M1`, key B):
    - S01..S04 resolved B          -> 4 correct
    - S05, S06  resolved C         -> 2 band-incorrect (wrong answers)
    - S07, S08  blank              -> 2 band-incorrect AND blank_count = 2
    - S09, S10  ambiguous          -> unresolved
    - S11      multiple marks      -> unresolved
    - S12      no document at all  -> absent, unresolved
    So: n = 12, correct = 4, incorrect band = 4, blank_count = 2, unresolved_count = 4,
    correct_rate = 4/12 = 1/3, and the identity correct + incorrect + unresolved = 12
    holds with blanks INSIDE the incorrect band — the two zeros are different zeros.
    """
    store = open_det_store(tmp_data_dir)
    try:
        _run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=tuple(f"S{i:02d}" for i in range(1, 13)),
            criteria=[
                {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
            ],
        )
        seed_selection_answers(
            store,
            cohort_id,
            [
                *[{"submission_id": f"S{i:02d}", "selection": "B"} for i in range(1, 5)],
                *[{"submission_id": f"S{i:02d}", "selection": "C"} for i in (5, 6)],
                *[{"submission_id": f"S{i:02d}", "content_state": "blank"}
                  for i in (7, 8)],
                *[{"submission_id": f"S{i:02d}", "content_state": "present",
                   "selection_state": "ambiguous"} for i in (9, 10)],
                {"submission_id": "S11",
                 "regions": [{"content_state": "present"},
                             {"content_state": "present"}]},
                {"submission_id": "S12", "omit_document": True},
            ],
        )
        report = _evaluator(store).evaluate_cohort(_run_id)

        summary = report.summaries[0]
        assert summary.blank_count == 2, (
            "blank_count must count ONLY genuinely empty answers (S07, S08) — a "
            "conflated figure here reads scanning failures as student zeros"
        )
        assert summary.unresolved_count == 4, (
            "unresolved_count must count ONLY unreadable reads (S09-S12: two "
            "ambiguous, one multiple-marks, one absent) — a conflated figure here "
            "hides a scanner problem as item difficulty"
        )
        assert summary.blank_count != summary.unresolved_count
        assert (summary.n, summary.correct) == (12, 4)
        assert summary.correct_rate == pytest.approx(1 / 3)
        # The stored row carries the same two figures in separate columns — the
        # separation is schema, not presentation (det migration `det_item_statistic_columns`).
        stored = _durable_query(
            store,
            "SELECT n, correct_rate, blank_count, unresolved_count "
            "FROM mcq_item_summary WHERE criterion_id = 'M1'",
        )
        assert len(stored) == 1
        assert stored[0]["blank_count"] == 2
        assert stored[0]["unresolved_count"] == 4
        # The band-level identity from the score rows: 4 correct + 4 incorrect (2
        # wrong, 2 blank) + 4 unresolved = 12.
        bands = _cohort_query(
            store, cohort_id,
            "SELECT band, COUNT(*) AS n FROM criterion_score "
            "WHERE criterion_id = 'M1' GROUP BY band",
        )
        by_band = {row["band"]: row["n"] for row in bands}
        assert by_band == {"correct": 4, "incorrect": 4, "unresolved": 4}
        assert sum(by_band.values()) == 12
        # And the two zeros are different rows: a blank scores final/auto with points;
        # an unresolved row carries no score at all.
        blank_row = _cohort_query(
            store, cohort_id,
            "SELECT band, points, state, routing FROM criterion_score "
            "WHERE criterion_id = 'M1' AND submission_id = 'S07'",
        )[0]
        assert (blank_row["band"], blank_row["points"],
                blank_row["state"], blank_row["routing"]) == (
            "incorrect", 0.0, "final", "auto",
        )
        unresolved_row = _cohort_query(
            store, cohort_id,
            "SELECT band, points, state, routing FROM criterion_score "
            "WHERE criterion_id = 'M1' AND submission_id = 'S09'",
        )[0]
        assert (unresolved_row["band"], unresolved_row["points"],
                unresolved_row["state"], unresolved_row["routing"]) == (
            "unresolved", None, "unresolved_selection", "triage",
        )
    finally:
        store.close()


# --- TC-DET-06 ------------------------------------------------------------------------------


def test_tc_det_06_item_stats_and_summary_match_the_hand_computed_reference(
    tmp_data_dir,
):
    """`TC-DET-06` (`FR-DET-07`) — one question's statistics against the hand-computed
    reference (ten submissions, key B, options A-D):

    - chosen counts: A = 1 (S07), B = 4 (S01-S04, the key), C = 3 (S05, S06, S08),
      D = 0 (declared, never chosen — still reported, is_key 0);
    - is_key: B only;
    - summary: n = 10, correct_rate = 4/10 = 0.4, blank_count = 1 (S09),
      unresolved_count = 1 (S10, ambiguous);
    - most_chosen_distractor: C (count 3 — the highest non-key count).

    Level note: the plan marks this Unit / rung 0; the shipped surface of FR-DET-07 is
    the cohort pass and the `item_stats` read API, so the case runs at rung 2 with the
    oracle unchanged (see the module docstring)."""
    store = open_det_store(tmp_data_dir)
    try:
        _run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=tuple(f"S{i:02d}" for i in range(1, 11)),
            criteria=[
                {"criterion_id": "M1", "question_id": "Q1",
                 "options": ("A", "B", "C", "D"), "key": ("B",)},
            ],
        )
        seed_selection_answers(
            store,
            cohort_id,
            [
                *[{"submission_id": f"S{i:02d}", "selection": "B"} for i in range(1, 5)],
                {"submission_id": "S05", "selection": "C"},
                {"submission_id": "S06", "selection": "C"},
                {"submission_id": "S07", "selection": "A"},
                {"submission_id": "S08", "selection": "C"},
                {"submission_id": "S09", "content_state": "blank"},
                {"submission_id": "S10", "content_state": "present",
                 "selection_state": "ambiguous"},
            ],
        )
        evaluator = _evaluator(store)
        evaluator.evaluate_cohort(_run_id)

        report = evaluator.item_stats(cohort_id)
        assert report.cohort_id == cohort_id
        assert report.package_version_id is not None
        assert len(report.items) == 1
        entry = report.items[0]
        assert (entry.n, entry.correct_rate) == (10, pytest.approx(0.4))
        assert entry.blank_count == 1
        assert entry.unresolved_count == 1
        counts = {opt.option: (opt.chosen, opt.is_key) for opt in entry.options}
        assert counts == {
            "A": (1, False),
            "B": (4, True),
            "C": (3, False),
            "D": (0, False),
        }, (
            f"per-option counts drifted from the hand count: {counts} — the rollup "
            "must be per-option chosen counts with the denormalized key flag"
        )

        # The same figures on the cohort pass's own report, and the distractor named.
        cohort_report = evaluator.evaluate_cohort(_run_id)  # redelivery is idempotent
        summary = cohort_report.summaries[0]
        assert summary.most_chosen_distractor == "C"
        assert (summary.n, summary.correct) == (10, 4)
        assert (summary.blank_count, summary.unresolved_count) == (1, 1)
        # Idempotent redelivery: the stored figures did not double.
        stored = _durable_query(
            store,
            "SELECT chosen FROM mcq_item_stats WHERE criterion_id = 'M1' "
            "AND option = 'B'",
        )
        assert stored[0]["chosen"] == 4
    finally:
        store.close()


# --- TC-DET-08 ------------------------------------------------------------------------------


def test_tc_det_08_label_mode_carries_the_separation_and_the_filter_enforces_it(
    tmp_data_dir,
):
    """`TC-DET-08` (`FR-DET-09`) — a label store holding both judged and deterministic
    labels: `label.evaluation_mode` carries the distinction, and the shared statistics
    filter (`DETERMINISTIC_EXCLUSION`, composed into `select_agreement_labels`) excludes
    deterministic results from the agreement figure.

    Scope note (disclosed): the κ / α / grader-quality consumers land with `M-STATS`;
    the shipped surface this case pins is the ONE filter definition and the canonical
    agreement-figure query it composes — exactly what `NFR-DET-03` requires to exist
    before those consumers land. The exclusion is enforceable from the data: flipping a
    label's mode is what moves it, not a naming convention."""
    store = open_det_store(tmp_data_dir)
    try:
        _run_id, version, cohort_id = seed_det_world(
            store,
            submissions=("S01", "S02"),
            criteria=[
                {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
            ],
        )
        # Four blind labels: two judged (the default the column ships with, and an
        # explicit one), two deterministic — as an `M-REVIEW`-style labeler over a
        # deterministic result would write them (CT-DET-06: det owns the column, not
        # the row; the rows here are seeded directly, disclosed).
        durable = store.durable()
        labels = [
            ("L1", "judged", None),          # default-mode judged row
            ("L2", "judged", "judged"),      # explicit judged
            ("L3", "deterministic", "deterministic"),
            ("L4", "deterministic", "deterministic"),
        ]
        with durable.transaction() as tx:
            for label_id, _mode, evaluation_mode in labels:
                if evaluation_mode is None:
                    # The DEFAULT-the-column-carries row: the mode omitted, so the
                    # insert exercises the column's own 'judged' default.
                    tx.execute(
                        "INSERT INTO label (label_id, run_id, student_ref, "
                        "criterion_id, label_type, band) VALUES (:l, :r, NULL, "
                        "'M1', 'blind', 'correct')",
                        l=label_id,
                        r=_run_id,
                    )
                else:
                    tx.execute(
                        "INSERT INTO label (label_id, run_id, student_ref, "
                        "criterion_id, label_type, band, evaluation_mode) VALUES "
                        "(:l, :r, NULL, 'M1', 'blind', 'correct', :mode)",
                        l=label_id,
                        r=_run_id,
                        mode=evaluation_mode,
                    )

        # The column carries the distinction from the data.
        modes = {
            row["label_id"]: row["evaluation_mode"]
            for row in _durable_query(
                store, "SELECT label_id, evaluation_mode FROM label ORDER BY label_id"
            )
        }
        assert modes == {"L1": "judged", "L2": "judged",
                         "L3": "deterministic", "L4": "deterministic"}

        # The canonical agreement-figure query admits only the judged rows.
        admitted = [
            row["label_id"]
            for row in _durable_query(
                store, DET_STATEMENTS["select_agreement_labels"]
            )
        ]
        assert admitted == ["L1", "L2"], (
            f"the agreement query admitted {admitted} — a deterministic result "
            "reached an agreement figure (RISK-07)"
        )

        # Composition, not re-spelling: a consumer query built from the imported
        # constant excludes exactly the same rows — the sanctioned reuse path
        # (NFR-DET-03: one definition, composed per consumer).
        composed = (
            "SELECT label_id FROM label WHERE label_type = 'blind' AND "
            + DETERMINISTIC_EXCLUSION
            + " ORDER BY label_id"
        )
        assert [
            row["label_id"]
            for row in _durable_query(store, composed)
        ] == admitted

        # And the exclusion is from the DATA: flip L2's mode and it drops out — no
        # naming convention, no consumer-side override.
        with durable.transaction() as tx:
            tx.execute(
                "UPDATE label SET evaluation_mode = 'deterministic' "
                "WHERE label_id = 'L2'",
            )
        assert [
            row["label_id"]
            for row in _durable_query(
                store, DET_STATEMENTS["select_agreement_labels"]
            )
        ] == ["L1"]
    finally:
        store.close()


# --- TC-DET-10 ------------------------------------------------------------------------------


def test_tc_det_10_audit_record_carries_the_deterministic_shape(tmp_data_dir):
    """`TC-DET-10` (`FR-DET-10`) — a completed deterministic evaluation's audit record:
    `evaluation_mode = 'deterministic'`, null `panel_config`, null `prompt_template_v`,
    non-null `answer_key_ref` and non-null `selection_read` — exact values, including
    the ref's `<version>:<key>` shape.

    Seeded cohort (key B): S01 resolved B (scored), S02 resolved C (scored), S03 blank
    (scored, the legitimate zero, `selection_read` = `[]`), S04 ambiguous (unresolved —
    writes NO audit record: no grade, no points, nothing `final_points NOT NULL` could
    carry; its audit is the score row's own state/routing pair — det.py's disclosed
    interpretation of the §9.7 column set)."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, version, cohort_id = seed_det_world(
            store,
            submissions=("S01", "S02", "S03", "S04"),
            criteria=[
                {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
            ],
        )
        seed_selection_answers(
            store,
            cohort_id,
            [
                {"submission_id": "S01", "selection": "B"},
                {"submission_id": "S02", "selection": "C"},
                {"submission_id": "S03", "content_state": "blank"},
                {"submission_id": "S04", "content_state": "present",
                 "selection_state": "ambiguous"},
            ],
        )
        report = _evaluator(store).evaluate_cohort(run_id)
        assert report.audit_records_written == 3, (
            "three scored rows must append exactly three audit records; the "
            "unresolved row writes none (no grade exists for it)"
        )

        rows = {
            row["submission_id"]: row
            for row in _durable_query(
                store,
                "SELECT submission_id, evaluation_mode, panel_config, "
                "prompt_template_v, answer_key_ref, selection_read, final_points, "
                "decided_by, package_version_id, profile_summary FROM audit_record "
                "WHERE criterion_id = 'M1'",
            )
        }
        assert set(rows) == {"S01", "S02", "S03"}
        for submission_id in ("S01", "S02", "S03"):
            row = rows[submission_id]
            assert row["evaluation_mode"] == "deterministic", (
                "a deterministic grade's audit record must carry the mode explicitly "
                "— the column's DEFAULT 'judged' would misclassify it"
            )
            assert row["panel_config"] is None, (
                "a populated panel_config would make the row look panel-scored to "
                "every statistic downstream"
            )
            assert row["prompt_template_v"] is None
            assert row["answer_key_ref"] is not None
            assert row["selection_read"] is not None
            assert row["decided_by"] == "system"
            assert row["package_version_id"] == version
        # The ref resolves to exactly the key that produced the grade (ADR-1).
        assert rows["S01"]["answer_key_ref"] == f"{version}:{json.dumps(['B'])}"
        assert json.loads(rows["S01"]["answer_key_ref"].split(":", 1)[1]) == ["B"]
        # The read is recorded: what was read, per submission.
        assert json.loads(rows["S01"]["selection_read"]) == ["B"]
        assert json.loads(rows["S02"]["selection_read"]) == ["C"]
        assert json.loads(rows["S03"]["selection_read"]) == [], (
            "a blank answer was READ — as an empty answer — and its selection_read "
            "is the empty list, never a null that would look like an unread row"
        )
        assert rows["S01"]["final_points"] == pytest.approx(1.0)
        assert rows["S02"]["final_points"] == pytest.approx(0.0)
        assert rows["S03"]["final_points"] == pytest.approx(0.0)
        # The unresolved row's audit is its own state/routing pair — no record, no
        # points, nothing the NOT NULL column could honestly carry.
        unresolved = _cohort_query(
            store, cohort_id,
            "SELECT state, routing, points FROM criterion_score "
            "WHERE submission_id = 'S04' AND criterion_id = 'M1'",
        )[0]
        assert (unresolved["state"], unresolved["routing"],
                unresolved["points"]) == ("unresolved_selection", "triage", None)
    finally:
        store.close()
