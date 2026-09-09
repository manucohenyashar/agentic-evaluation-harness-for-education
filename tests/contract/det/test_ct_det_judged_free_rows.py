"""`CT-DET-02` — the judged-free score row (`TC-DET-C02`).

Case of test plan §6.11.11; issue #90 (TS-68). Green by design — `M-DET`
shipped via #246/#249.

The clause: a deterministic `criterion_score` carries `judge_count = 0`,
`agreement = NULL`, and produces **no** `verdict` rows; a consumer computing
over verdicts will find none, and **must not read that as missing data**.

The clause discriminator: the FR-level case asserts the columns on one scored
criterion; this case sweeps EVERY row of a mixed cohort pass, asserts the
verdict table is empty under a write audit, and then asserts the
null-versus-absent distinction the clause's second sentence exists for —
"no verdicts because deterministic" (score rows present, `judge_count = 0` on
every one) is READABLE from the data as complete work, and is distinguishable
from "no verdicts because something failed" (no score rows at all). Collapsed,
deterministic criteria show as incomplete forever.

**Disclosed rung-3 half**: the plan's rung-3 sweep names `M-AGG` and
`M-STATS`. Neither module is shipped yet (only conf/pkg/setup/store/ingest/
orch/det/prov exist), so the sweep is asserted at the data level those
consumers will read — the distinction the columns carry — and the live-module
differential lands with the modules (κ/α consumers land with M-STATS, per the
TS-33 disclosure this suite reconciles with).
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


def test_tc_det_c02_every_row_judge_free_and_no_verdict_rows(tmp_data_dir):
    """`TC-DET-C02` (rung 2, swept) — a two-criterion cohort pass: EVERY
    deterministic `criterion_score` row carries `judge_count = 0` and
    `agreement IS NULL`, and the `verdict` table holds ZERO rows after the
    pass — asserted over the whole table, not per criterion, so a verdict
    written from any path fails the case."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=("S01", "S02", "S03", "S04"),
            criteria=[
                {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
                {"criterion_id": "M2", "question_id": "Q2", "key": ("B",)},
            ],
        )
        seed_selection_answers(
            store, cohort_id,
            [
                {"submission_id": "S01", "selection": "B"},
                {"submission_id": "S02", "selection": "C"},
                {"submission_id": "S03", "content_state": "blank"},
                {"submission_id": "S04", "content_state": "present",
                 "selection_state": "ambiguous"},
            ],
        )
        report = DeterministicEvaluator(store).evaluate_cohort(run_id)
        assert report.criteria == 2 and report.evaluations == 8

        cohort = store.cohort(cohort_id)
        rows = list(cohort.query(
            "SELECT submission_id, criterion_id, judge_count, agreement, band "
            "FROM criterion_score"
        ))
        assert len(rows) == 8, (
            f"TC-DET-C02: {len(rows)} score rows for 4 submissions x 2 "
            "criteria — the sweep is not over the full population."
        )
        for row in rows:
            assert row["judge_count"] == 0, (
                f"TC-DET-C02: {row['criterion_id']}/{row['submission_id']} "
                f"carries judge_count {row['judge_count']} — a judged trace "
                "on a deterministic row."
            )
            assert row["agreement"] is None, (
                f"TC-DET-C02: {row['criterion_id']}/{row['submission_id']} "
                f"carries agreement {row['agreement']!r} — a panel figure on "
                "a row no panel produced."
            )
        verdicts = cohort.query("SELECT COUNT(*) AS n FROM verdict")
        assert verdicts[0]["n"] == 0, (
            f"TC-DET-C02: {verdicts[0]['n']} verdict rows after a "
            "deterministic pass — the module produced panel output."
        )
    finally:
        store.close()


def test_tc_det_c02_no_verdicts_is_readable_as_complete_not_missing(
        tmp_data_dir):
    """`TC-DET-C02` (the consumer instruction) — computing over verdicts finds
    none for a fully-evaluated deterministic criterion, and the data must let
    a consumer tell that apart from a criterion whose scores never landed.
    The distinction the columns carry: the deterministic criterion's score
    rows are PRESENT and COMPLETE (one per submission, `judge_count = 0` on
    every row — work finished, no panel by design), while a criterion whose
    evaluation never happened has NO rows. Presence-with-zero-judges versus
    absence is the null-versus-absent line; asserted as a sweep over both
    shapes in one store."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=("S01", "S02", "S03"),
            criteria=[
                {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
                {"criterion_id": "M2", "question_id": "Q2", "key": ("B",)},
            ],
        )
        seed_selection_answers(
            store, cohort_id,
            [
                {"submission_id": "S01", "selection": "B"},
                {"submission_id": "S02", "selection": "C"},
                {"submission_id": "S03", "selection": "B"},
            ],
        )
        DeterministicEvaluator(store).evaluate_cohort(run_id)

        cohort = store.cohort(cohort_id)
        scored = cohort.query(
            "SELECT criterion_id, COUNT(*) AS n, SUM(judge_count) AS judged, "
            "SUM(CASE WHEN agreement IS NULL THEN 1 ELSE 0 END) AS null_agr "
            "FROM criterion_score GROUP BY criterion_id ORDER BY criterion_id"
        )
        by_criterion = {row["criterion_id"]: dict(row) for row in scored}

        # "No verdicts because deterministic": rows PRESENT, complete, and
        # judge-free — a consumer reading this shape has the criterion's full
        # result and no verdict to compute over. Not missing data.
        for criterion_id in ("M1", "M2"):
            shape = by_criterion.get(criterion_id)
            assert shape is not None, (
                f"TC-DET-C02: {criterion_id} has no score rows — the "
                "deterministic-complete shape is indistinguishable from a "
                "failed run, which is the collapse this case exists to catch."
            )
            assert shape["n"] == 3, (
                f"TC-DET-C02: {criterion_id} holds {shape['n']} rows for 3 "
                "submissions — an incomplete population cannot be told apart "
                "from missing data."
            )
            assert shape["judged"] == 0 and shape["null_agr"] == 3

        # "No verdicts because something failed": a criterion id with NO rows
        # at all — the only absence shape the data offers. The two shapes are
        # disjoint by row presence, so the consumer differential holds.
        assert "C-never-evaluated" not in by_criterion
        assert set(by_criterion) == {"M1", "M2"}
    finally:
        store.close()
