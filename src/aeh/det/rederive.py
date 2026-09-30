"""Re-deriving a criterion's scores after its answer key is corrected."""

from __future__ import annotations

from typing import Any

from aeh.pkg import PackageCatalog

from .errors import DeterministicError
from .kernel import DetOutcome
from .schema import DET_STATEMENTS
from .records import RederiveChange, RederiveReport
from .ledger import _newest_run


class KeyCorrectionMixin:
    """Re-derives one criterion's scores for a cohort under a corrected answer key."""

    # -- the key-correction path and the read API (FR-DET-08 / FR-DET-07) ----

    def rederive_for_key_change(
        self, cohort_id: str, criterion_id: str, new_version: str,
        *, run_id: str | None = None,
    ) -> RederiveReport:
        """Re-derive one criterion's scores for one cohort under a corrected
        answer key (`FR-DET-08`, `CT-DET-07`). A correction is a new package
        version (`FR-PKG-18`); this reads the criterion, its options and its
        points from THAT version, re-runs the same §7.8 kernel over every
        submission's stored selection read — a lookup, not a re-judgement —
        and upserts only the rows whose value actually moves. No panel work,
        no review-queue row, no model call: `panel_units_enqueued` is a
        declared zero, and the audit records appended for the changed rows
        name `new_version` in their `answer_key_ref`, which is what makes a
        correction answerable years later while the untouched rows' audit
        trail still resolves each old grade to its old key.

        Idempotent (`CT-DET-07`, the M-ORCH redelivery constraint): against
        an unchanged key every re-derived value equals the stored one, so the
        change set is empty, nothing is written, and a second pass reports
        zeros across the board.

        The appended audit rows carry the cohort's NEWEST run as their
        `run_id` (latest non-null `started_at`, then run_id — the run whose
        grades the correction supersedes); which KEY version produced each
        grade travels in `answer_key_ref`, so the attribution stays exact
        even when the run named several versions.
        """
        runs = self._cohort_runs(cohort_id)
        if not runs:
            return RederiveReport(
                cohort_id=cohort_id,
                criterion_id=criterion_id,
                question_id=None,
                new_version=new_version,
                from_versions=(),
                submissions_examined=0,
                scores_changed=0,
                scores_unchanged=0,
                audit_records_written=0,
                panel_units_enqueued=0,
                changes=(),
            )
        package_ids = sorted({row["package_id"] for row in runs})
        if len(package_ids) > 1:
            raise DeterministicError(
                f"cohort {cohort_id!r}'s runs name several packages "
                f"({package_ids}); which one a key correction applies to is a "
                "caller decision this module will not guess at."
            )
        package_id = package_ids[0]
        from_versions = tuple(sorted({row["package_version_id"] for row in runs}))
        package_handle = self._store.package(package_id)
        criterion = self._criterion(package_handle, new_version, criterion_id)
        option_set = (
            tuple(
                row["option_id"]
                for row in package_handle.query(
                    DET_STATEMENTS["select_options"],
                    v=new_version,
                    criterion_id=criterion_id,
                )
            )
            or None
        )
        catalog = PackageCatalog(package_handle, package_id=package_id)
        catalog.criteria(new_version)  # pins the cache to the corrected version
        cohort_handle = self._store.cohort(cohort_id)
        submissions = [
            row["submission_id"]
            for row in cohort_handle.query(
                DET_STATEMENTS["select_cohort_submissions"], cohort_id=cohort_id
            )
        ]
        # FR-DET-11: only the named run's rows are re-derived — a correction for run B never
        # touches run A's scores. Unnamed, the target is the cohort's newest run, the run the
        # audit rows were already attributed to.
        if run_id is None:
            target_run = _newest_run(runs)
        else:
            named = [row for row in runs if row["run_id"] == run_id]
            if not named:
                raise DeterministicError(
                    f"run {run_id!r} is not a run of cohort {cohort_id!r}; a key "
                    "correction re-derives only a named run of the cohort (FR-DET-11)."
                )
            target_run = named[0]
        existing = {
            row["submission_id"]: row
            for row in cohort_handle.query(
                DET_STATEMENTS["select_criterion_scores"],
                run_id=target_run["run_id"], criterion_id=criterion_id,
            )
        }
        changed: list[tuple[str, dict[str, Any], DetOutcome, float | None]] = []
        report_changes: list[RederiveChange] = []
        unchanged = 0
        for submission_id in submissions:
            outcome, points = self._score_one(
                cohort_handle,
                package_handle,
                new_version,
                criterion,
                submission_id,
                option_set=option_set,
                catalog=catalog,
            )
            current = existing.get(submission_id)
            same = current is not None and (
                current["band"] == outcome.band
                and current["prev_points"] == points
                and current["state"] == outcome.state
                and current["routing"] == outcome.routing
            )
            if same:
                unchanged += 1
                continue
            changed.append((submission_id, criterion, outcome, points))
            report_changes.append(
                RederiveChange(
                    submission_id=submission_id,
                    old_band=current["band"] if current is not None else None,
                    new_band=outcome.band,
                    old_points=current["prev_points"] if current is not None else None,
                    new_points=points,
                )
            )
        if changed:
            with cohort_handle.transaction() as tx:
                for submission_id, criterion_row, outcome, points in changed:
                    tx.execute(
                        DET_STATEMENTS["upsert_rederived_score"],
                        run_id=target_run["run_id"],
                        submission_id=submission_id,
                        criterion_id=criterion_row["criterion_id"],
                        band=outcome.band,
                        points=points,
                        judge_count=0,
                        agreement=None,
                        state=outcome.state,
                        routing=outcome.routing,
                    )
            audit_records_written = self._append_audit_records(
                target_run, new_version, changed
            )
        else:
            audit_records_written = 0
        return RederiveReport(
            cohort_id=cohort_id,
            criterion_id=criterion_id,
            question_id=criterion["question_id"],
            new_version=new_version,
            from_versions=from_versions,
            submissions_examined=len(submissions),
            scores_changed=len(changed),
            scores_unchanged=unchanged,
            audit_records_written=audit_records_written,
            panel_units_enqueued=0,
            changes=tuple(report_changes),
        )
