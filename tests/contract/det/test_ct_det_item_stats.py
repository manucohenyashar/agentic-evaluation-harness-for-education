"""`CT-DET-08` — the item-statistics read API (`TC-DET-C08`).

Case of test plan §6.11.11; issue #90 (TS-68). Green by design — `M-DET`
shipped via #246/#249.

The clause: `item_stats` returns `mcq_item_stats` (per-option chosen counts,
key flag) and `mcq_item_summary` (n, correct rate, **blank count and
unresolved count as separate figures**) per cohort (`FR-DET-07`). The
separation is contract: unresolved is a **scanning** problem and must never be
read as item difficulty — a merged figure makes a scanner fault look like a
hard question, which is the one reading that leads to changing the question
instead of fixing the scanner.

The clause discriminator: the FR-level case hand-checks the figures from one
pass; this case asserts the separation STRUCTURALLY, so a later merge into a
single "not answered" figure FAILS rather than quietly reading wrong —
- the summary's field set and the schema's column set carry `blank_count` and
  `unresolved_count` as TWO names, and no merged name exists at either layer
  (the API is the dataclass; the store is the DDL);
- the read-back figures match a hand-built fixture EXACTLY, per option, per
  figure — including a zero-chosen distractor and the key flag;
- the two figures carry their own names at BOTH layers — the exact field set
  and column set leave no shared "not answered" alias to conflate them by
  (the scanning-alert reading of the elevated figure is `TC-DET-C13`'s case).
"""

from __future__ import annotations

import dataclasses

import pytest

from aeh.det import DeterministicEvaluator
from tests.support.det_vocabulary import (
    open_det_store,
    seed_det_world,
    seed_selection_answers,
)

pytestmark = pytest.mark.contract

from tests.contract.det._doubles import ISSUE  # noqa: F401 — register citation


def test_tc_det_c08_the_separation_is_structural():
    """`TC-DET-C08` (the structural half) — blank and unresolved travel as
    separate figures at BOTH layers the consumer reads: the API's field sets
    and the schema's column sets. A merged "not answered" figure cannot
    appear without renaming a field or a column, and neither layer offers an
    alias to conflate them by — the field names are disjoint and neither
    contains the other or any merged superset name."""
    from aeh.det import ItemOptionCount, ItemStatsEntry

    summary_fields = {f.name for f in dataclasses.fields(ItemStatsEntry)}
    assert {"blank_count", "unresolved_count"} <= summary_fields, (
        f"TC-DET-C08: the summary API lost a figure: {sorted(summary_fields)}."
    )
    for merged in ("not_answered", "missing_count", "unanswered_count",
                   "blank_or_unresolved"):
        assert merged not in summary_fields, (
            f"TC-DET-C08: the summary API carries {merged!r} — the two "
            "figures were merged at the API layer."
        )
    option_fields = {f.name for f in dataclasses.fields(ItemOptionCount)}
    assert option_fields == {"criterion_id", "option", "chosen", "is_key"}, (
        f"TC-DET-C08: the per-option API is {sorted(option_fields)} — the "
        "chosen counts and the key flag moved."
    )

    # The schema layer: the DDL's own columns are two, separately named.
    from aeh.store import TIER_MIGRATIONS, Tier

    durable_columns = {
        column
        for migration in TIER_MIGRATIONS[Tier.DURABLE]
        for statement in migration.statements
        if "ADD COLUMN" in str(statement)
        for column in [str(statement).split("ADD COLUMN")[1].split()[0]]
    }
    assert {"blank_count", "unresolved_count"} <= durable_columns, (
        f"TC-DET-C08: the durable DDL lost a column: {sorted(durable_columns)}."
    )
    assert not (durable_columns & {"not_answered", "unanswered_count"})


def test_tc_det_c08_exact_counts_against_a_hand_built_fixture(tmp_data_dir):
    """`TC-DET-C08` (rung 2, the fixture) — seven submissions, one question
    keyed to B: three B (correct), one A, one C, one blank, one ambiguous.
    Hand counts: n = 7, correct = 3, correct_rate = 3/7, blank_count = 1,
    unresolved_count = 1; per-option chosen: A = 1, B = 3, C = 1, D = 0; the
    key flag sits on B alone; the most-chosen distractor breaks the A/C count
    tie lexicographically to A. The figures read back EXACTLY, and the
    identity correct + incorrect + unresolved = n holds with the blank INSIDE
    the incorrect band — a blank is a zero, not an unreadable scan."""
    store = open_det_store(tmp_data_dir)
    try:
        submissions = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
        run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=submissions,
            criteria=[{"criterion_id": "M1", "question_id": "Q1",
                       "key": ("B",)}],
        )
        seed_selection_answers(
            store, cohort_id,
            [
                {"submission_id": "S1", "selection": "B"},
                {"submission_id": "S2", "selection": "B"},
                {"submission_id": "S3", "selection": "B"},
                {"submission_id": "S4", "selection": "A"},
                {"submission_id": "S5", "selection": "C"},
                {"submission_id": "S6", "content_state": "blank"},
                {"submission_id": "S7", "content_state": "present",
                 "selection_state": "ambiguous"},
            ],
        )
        report = DeterministicEvaluator(store).evaluate_cohort(run_id)
        stats = DeterministicEvaluator(store).item_stats(cohort_id)
        assert stats.package_version_id is not None
        assert len(stats.items) == 1
        entry = stats.items[0]
        assert entry.criterion_id == "M1"
        assert entry.n == 7
        assert entry.correct_rate == pytest.approx(3 / 7)
        # THE separation, exact: one blank (a legitimate zero), one
        # unresolved (a scanning problem). A merged figure would report 2 of
        # something and lose which reading each count carries.
        assert entry.blank_count == 1
        assert entry.unresolved_count == 1

        by_option = {o.option: o for o in entry.options}
        assert set(by_option) == {"A", "B", "C", "D"}
        assert by_option["B"].chosen == 3 and by_option["B"].is_key is True
        assert by_option["A"].chosen == 1 and by_option["A"].is_key is False
        assert by_option["C"].chosen == 1 and by_option["C"].is_key is False
        assert by_option["D"].chosen == 0 and by_option["D"].is_key is False

        # The identity the summary is built on: correct + incorrect +
        # unresolved = n, with the blank inside the incorrect band — the
        # blank is IN the denominator as a zero, never as an unreadable scan.
        summary = report.summaries[0]
        assert summary.correct == 3
        assert summary.blank_count == 1 and summary.unresolved_count == 1
        assert summary.correct + report.incorrect + report.unresolved == \
            summary.n

        # The distractor is the highest-count non-key option, ties broken
        # lexicographically — A and C both have 1, so A.
        assert summary.most_chosen_distractor == "A"
        assert report.unresolved == 1
    finally:
        store.close()
