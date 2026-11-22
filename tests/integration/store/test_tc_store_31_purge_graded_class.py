"""TC-STORE-31 (Validity T7, issue #900): purging a graded class (FR-STORE-22, CT-STORE-20), and
TC-REVIEW-108's purge arm: purging a class removes its blind drafts.

Source: `docs/design/statistical_validity_test_plan.md` §3.10 and §3.7.

| Partition | Expected |
|---|---|
| Finish, promoted | `purge_cohort` passes on "every administration recorded"; drafts, draw, seats, scores, run, papers and the class row gone |
| Skip, promoted | passes the same way |
| Draw open (one seat drafted) | refused with exactly "Finish or skip the blind sample for <class>, then delete the class."; nothing deleted |
| Draw closed (Finish), not yet promoted | refused; nothing deleted (the precondition itself) |
| TC-EXTRACT-14 | its blocker re-keyed off `aeh.stats:promote_cohort`, its marker gone (verified, #880 did it) |

**Departure from the plan, disclosed.** The plan reads "drafts, labels and the cohort file are
gone". As shipped (#880, PR #935), and per FR-STORE-07, the purge keeps the cohort **file**,
emptied and still migrated, and the Tier D **labels** stay: they are the promoted evidence the
package's validity record is computed from. Only the cohort-tier rows go, drafts among them.
These cases assert that reading explicitly: the file exists, every swept table is empty, and
the label count in Tier D is unchanged.

**"The class name, not its id."** The cohort table has no name column. `purge_cohort` names the
class by its cohort id, which is what the console lists a class under
(`purge_refusal_next_step`'s docstring), so the expected sentence carries the cohort id.

**Mutation (the plan's "precondition reverted → red").** Reverting the administration route
(`_administrations_recorded` returning False) turns both pass arms red: a real promotion stamps
no `audit_record` with a cohort, so the three CT-STORE-10 gates alone refuse the class.

**Isolation: rung 3.** A real store, the shipped draw and promotion, `network_guard`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aeh.store import PurgePreconditionError
from aeh.store.purge import ADMINISTRATIONS_RECORDED
from tests.support.graded_class import (
    PAPERS,
    SWEPT,
    cohort_counts,
    cohort_file,
    graded_class,
    purge,
    run_status,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]


def _sentence(class_name: str) -> str:
    return f"Finish or skip the blind sample for {class_name}, then delete the class."


def _assert_purged_but_file_and_labels_kept(world, administration, labels_before) -> None:
    path = cohort_file(world, administration.cohort_id)
    assert path.exists(), "the cohort file was deleted; FR-STORE-07 keeps it, emptied"
    counts = cohort_counts(world, administration.cohort_id)
    assert counts == {table: 0 for table in SWEPT}, f"rows survived the purge: {counts}"
    assert len(world.labels(administration)) == labels_before, (
        "the purge touched Tier D's labels, the promoted evidence")


def test_tc_store_31_a_finished_and_promoted_class_purges(tmp_path, network_guard):
    world, administration = graded_class(tmp_path / "w", "c-finish")
    try:
        assert run_status(world, administration) not in ("running", "paused"), (
            "fixture: a run still grading would refuse on its own")
        world.finish(administration)
        assert world.promote(administration, "finish").promoted
        labels = len(world.labels(administration))
        assert labels == PAPERS, f"fixture: Finish wrote {labels} labels, not {PAPERS}"
        before = cohort_counts(world, administration.cohort_id)
        assert before["blind_draft"] == PAPERS and before["blind_draw"] == 1, before

        report = purge(world, administration.cohort_id)

        assert report.preconditions_verified == (ADMINISTRATIONS_RECORDED,), report
        assert report.rows_deleted_by_table.get("blind_draft") == PAPERS, (
            report.rows_deleted_by_table)
        _assert_purged_but_file_and_labels_kept(world, administration, labels)
        network_guard.assert_no_network()
    finally:
        world.close()


def test_tc_store_31_a_skipped_and_promoted_class_purges(tmp_path, network_guard):
    world, administration = graded_class(tmp_path / "w", "c-skip", drafted=1)
    try:
        world.skip(administration)
        outcome = world.promote(administration, "skip")
        assert outcome.promoted, outcome.reason
        (record,) = world.package_validation(administration)
        assert record["absence_reason"] == "skipped", record

        report = purge(world, administration.cohort_id)

        assert report.preconditions_verified == (ADMINISTRATIONS_RECORDED,), report
        _assert_purged_but_file_and_labels_kept(world, administration, 0)
        network_guard.assert_no_network()
    finally:
        world.close()


def test_tc_store_31_an_open_draw_refuses_with_the_teachers_sentence(tmp_path, network_guard):
    world, administration = graded_class(tmp_path / "w", "c-open", drafted=1)
    try:
        path = cohort_file(world, administration.cohort_id)
        before = cohort_counts(world, administration.cohort_id)
        assert before["blind_draft"] == 1, before

        with pytest.raises(PurgePreconditionError) as refused:
            purge(world, administration.cohort_id)

        expected = _sentence(administration.cohort_id)
        assert str(refused.value) == expected
        assert refused.value.next_step == expected
        # The open draw refuses before Tier D is read: no gate is named.
        assert (refused.value.unmet_gates, refused.value.detail) == ((), ""), refused.value.detail
        assert path.exists()
        assert cohort_counts(world, administration.cohort_id) == before, "the refusal deleted"
        network_guard.assert_no_network()
    finally:
        world.close()


def test_tc_store_31_an_open_draw_refuses_even_when_tier_d_holds_the_record(
        tmp_path, network_guard):
    """The open draw is checked first, whatever Tier D holds: the drafts are in flight. Seeded
    by inserting the administration's record directly (a disclosed stand-in for a record left by
    an earlier closed draw of the same version), which alone would pass the administration
    route."""
    import sqlite3
    from contextlib import closing

    world, administration = graded_class(tmp_path / "w", "c-open-recorded", drafted=1)
    try:
        with closing(sqlite3.connect(world.root / "durable.sqlite")) as connection, connection:
            connection.execute(
                "INSERT INTO package_validation (package_version_id, cohort_id, recorded_at, "
                "cohorts_used, operational_count, blind_count, n, weakest_per_population, "
                "surface_proxy_flags) VALUES (?, ?, '2026-01-01T00:00:00Z', 1, 0, 0, 0, "
                "'{}', '[]')",
                (administration.package_version_id, administration.cohort_id))
        before = cohort_counts(world, administration.cohort_id)

        with pytest.raises(PurgePreconditionError) as refused:
            purge(world, administration.cohort_id)

        assert str(refused.value) == _sentence(administration.cohort_id)
        assert cohort_counts(world, administration.cohort_id) == before, "the refusal deleted"
        network_guard.assert_no_network()
    finally:
        world.close()


def test_tc_store_31_a_closed_draw_not_yet_promoted_is_refused(tmp_path, network_guard):
    """The precondition itself: Finish closed the draw, but no administration record exists, so
    nothing says the class's evidence reached Tier D."""
    world, administration = graded_class(tmp_path / "w", "c-unpromoted")
    try:
        world.finish(administration)
        assert world.package_validation(administration) == []
        before = cohort_counts(world, administration.cohort_id)

        with pytest.raises(PurgePreconditionError) as refused:
            purge(world, administration.cohort_id)

        assert refused.value.next_step == _sentence(administration.cohort_id)
        assert refused.value.unmet_gates, "the refusal names no unmet gate"
        assert cohort_counts(world, administration.cohort_id) == before, "the refusal deleted"
        network_guard.assert_no_network()
    finally:
        world.close()


def test_tc_review_108_purging_a_class_removes_its_blind_drafts(tmp_path, network_guard):
    """R1's drafts are a judgement about a student's paper and die with the class. Finish keeps
    the drafts (only Skip discards them), so a finished, promoted class is the one that still
    holds drafts at purge time."""
    world, administration = graded_class(tmp_path / "w", "c-drafts", drafted=3)
    try:
        world.finish(administration)
        assert world.promote(administration, "finish").promoted
        assert cohort_counts(world, administration.cohort_id)["blind_draft"] == 3

        purge(world, administration.cohort_id)

        counts = cohort_counts(world, administration.cohort_id)
        assert (counts["blind_draft"], counts["blind_draw_seat"], counts["blind_draw"]) == (
            0, 0, 0), counts
        network_guard.assert_no_network()
    finally:
        world.close()


def test_tc_store_31_tc_extract_14_is_rekeyed_and_unmarked():
    """TC-EXTRACT-14's blocker left `aeh.stats:promote_cohort` (a surface that never shipped) for
    `aeh.pipeline:promote_administration`, which ships, so the entry resolved and left with the
    case's `writtenahead` marker (#880). Checked, not redone."""
    from tests.support.impl import WRITTEN_AHEAD_BLOCKERS

    case = "tests/security/extract/test_extract_pii_purge.py"
    for key, (_kind, target, tests) in WRITTEN_AHEAD_BLOCKERS.items():
        assert "promote_cohort" not in target, f"{key} still blocks on promote_cohort"
        assert not [t for t in tests if case in t], f"{key} still holds TC-EXTRACT-14"
    tree = ast.parse((REPO_ROOT / case).read_text(encoding="utf-8"))
    markers = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "writtenahead" not in markers, "TC-EXTRACT-14 still carries writtenahead"
    import aeh.pipeline

    assert callable(aeh.pipeline.promote_administration)
