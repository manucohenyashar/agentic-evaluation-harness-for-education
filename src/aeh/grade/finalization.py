"""Grade-state coverage counts and the one batch finalization action."""

from __future__ import annotations

from typing import Any

from aeh.pkg import is_composite, PKG_STATEMENTS

from .constants import (
    GRADE_STATES,
    ROUTING_TRIAGE,
    STATE_FINAL,
    STATE_INCOMPLETE,
    STATE_PROVISIONAL,
)
from .stored_rows import _row_value
from .schema import GRADE_STATEMENTS
from .records import CoverageSummary, FinalizationRecord


class FinalizationMixin:
    """Counts grades by state and settles provisional grades in one batch."""

    def coverage(self, run_id: str) -> CoverageSummary:
        """The run's grade counts by state, reported before any batch action (FR-GRADE-09). All
        three states are always present, including zeros; a missing key is not a zero.

        The counts are the class's states AS THEY STAND, not the stored rows alone
        (`CT-SYNTH-05`'s consumer differential reads them before any pass runs): a
        submission's current grade row carries its state, and a submission with no
        current grade row is counted `incomplete` exactly when its stored criterion
        data is missing criteria — `CT-GRADE-08`'s biconditional read from the stored
        side, the operator-rescan state the data holds whether or not a pass has run
        — and is not counted at all otherwise, because an uncomputed, fully-scored
        submission is not yet a grade and coverage never claims a state no grade
        holds."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        return CoverageSummary(
            run_id=run_id, grades_by_state=self._grades_by_state(run, cohort)
        )

    def _grades_by_state(self, run: Any, cohort: Any) -> dict[str, int]:
        """The state counts behind `coverage` and behind every batch action, computed in one place
        so an action reports exactly the coverage the method reports (TC-GRADE-09). Current stored
        grades count by their state; a submission with no current grade but missing inputs counts
        as `incomplete`."""
        counts = {state: 0 for state in GRADE_STATES}
        for row in cohort.query(
            GRADE_STATEMENTS["count_run_grades_by_state"], run_id=run["run_id"]
        ):
            counts[row["state"]] = int(row["n"])
        current_ids = {
            row["submission_id"]
            for row in cohort.query(
                GRADE_STATEMENTS["select_current_grades_for_run"], run_id=run["run_id"]
            )
        }
        package_handle = self._store.package(run["package_id"])
        criteria_ids = [
            row["criterion_id"]
            for row in package_handle.query(
                PKG_STATEMENTS["select_criteria"], v=run["package_version_id"]
            )
            # A composite has no score row of its own (FR-PKG-25): never a missing input.
            if not is_composite(row)
        ]
        for row in cohort.query(
            GRADE_STATEMENTS["select_run_submissions"], cohort_id=run["cohort_id"]
        ):
            submission_id = row["submission_id"]
            if submission_id in current_ids:
                continue
            # Score rows read through the module's tolerant `_row_value`, as the
            # other `select_submission_scores` sites do — and CT-PKG-05's
            # single-reader gate reads any `["points"]` subscript outside `aeh.pkg`
            # as a second band-points mapping, whatever column it is actually
            # touching.
            present = {
                _row_value(score, "criterion_id")
                for score in cohort.query(
                    GRADE_STATEMENTS["select_submission_scores"],
                    run_id=run["run_id"],
                    submission_id=submission_id,
                )
                if _row_value(score, "points") is not None
                and _row_value(score, "routing") != ROUTING_TRIAGE
            }
            if any(cid not in present for cid in criteria_ids):
                counts[STATE_INCOMPLETE] += 1
        return counts

    def has_criterion_scores(self, run_id: str) -> bool:
        """Whether any submission of the run has a criterion score (FR-PIPE-16). A run with none
        has nothing to grade, and recovery leaves it alone. Read-only."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        for row in cohort.query(
            GRADE_STATEMENTS["select_run_submissions"], cohort_id=run["cohort_id"]
        ):
            if cohort.query(
                GRADE_STATEMENTS["select_submission_scores"],
                run_id=run["run_id"],
                submission_id=row["submission_id"],
            ):
                return True
        return False

    def has_ungraded_scores(self, run_id: str) -> bool:
        """Whether some submission of the run has criterion scores but no current grade
        (FR-PIPE-16): the state a process killed right after scoring leaves behind (NFR-PIPE-01).
        `coverage` does not count these. Read-only."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        current_ids = {
            row["submission_id"]
            for row in cohort.query(
                GRADE_STATEMENTS["select_current_grades_for_run"], run_id=run["run_id"]
            )
        }
        for row in cohort.query(
            GRADE_STATEMENTS["select_run_submissions"], cohort_id=run["cohort_id"]
        ):
            submission_id = row["submission_id"]
            if submission_id in current_ids:
                continue
            if cohort.query(
                GRADE_STATEMENTS["select_submission_scores"],
                run_id=run["run_id"],
                submission_id=submission_id,
            ):
                return True
        return False

    def finalize_batch(self, run_id: str, actor: str) -> FinalizationRecord:
        """Finalize the run's grades in one batch (design §3.14): report the coverage first
        (FR-GRADE-09), settle every current provisional grade, and return a record repeating that
        coverage. There is no way to finalize one student at a time (TC-GRADE-09)."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        named = self._grades_by_state(run, cohort)
        settled_at = self._clock()
        with cohort.transaction() as tx:
            current = [
                dict(row)
                for row in cohort.query(
                    GRADE_STATEMENTS["select_current_grades_for_run"], run_id=run_id
                )
                if row["state"] == STATE_PROVISIONAL
            ]
            for row in current:
                tx.execute(
                    GRADE_STATEMENTS["settle_current"],
                    run_id=run_id,
                    submission_id=row["submission_id"],
                    state=STATE_FINAL,
                    settled_at=settled_at,
                )
        # The batch road is the one settlement path the ledger cannot derive (both
        # automatic roads settle in place through the same UPDATE, with no path
        # column to attribute by), so the action records itself: one durable EAV
        # row, the same table every other stage's figures ride (CT-GRADE-18's
        # observability; `record_grade_signals` derives the rest).
        #
        # A finalize that settled nothing (a repeat, a double-click, a second tab) writes
        # nothing (FR-CONSOLE-02, #398): overwriting the figure with 0 would erase the
        # count of the batch that actually settled the run.
        if current:
            with self._store.durable().transaction() as tx:
                tx.execute(
                    GRADE_STATEMENTS["insert_run_metric"],
                    run_id=run_id,
                    metric="finalization_path_batch",
                    value=float(len(current)),
                )
        return FinalizationRecord(
            finalized=len(current),
            coverage=named,
            actor=actor,
            settled_at=settled_at,
        )
