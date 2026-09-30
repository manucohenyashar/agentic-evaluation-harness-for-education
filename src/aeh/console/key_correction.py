"""Correcting an answer key from the rollup screen, and re-deriving the affected scores."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aeh.grade import GradingService
from aeh.pkg import PackageCatalog
from aeh.det import DeterministicEvaluator


class KeyCorrectionMixin:
    """Corrects an answer key and re-derives the scores it affected."""

    def _correct_answer_key(
        self, cohort_key: str, run_id: str, criterion_id: str, raw_key: Any
    ) -> tuple[str, bool]:
        """Screen S12's answer-key correction on a real store (FR-CONSOLE-30, §3.19). The steps
        belong to M-PKG, M-DET and M-GRADE and are called through their APIs; the console
        reimplements none of them:

        More detail: `docs/code-notes/console.md`, section `key_correction.py: KeyCorrectionMixin._correct_answer_key`.
        """
        key_ids = (
            [str(raw_key)] if isinstance(raw_key, str) else [str(option) for option in raw_key]
        )
        if not key_ids or any(not option for option in key_ids):
            return (
                "an answer key is a non-empty sequence of option ids (FR-PKG-17); "
                "nothing was written",
                False,
            )
        cohort = self._store.cohort(cohort_key)
        run_rows = list(
            cohort.query(
                "SELECT cohort_id, package_id, package_version_id FROM run "
                "WHERE run_id = :run_id",
                run_id=run_id,
            )
        )
        if not run_rows:
            return (
                f"no run named {run_id!r} exists in {cohort_key}; nothing was written",
                False,
            )
        run = run_rows[0]
        from_version = str(run["package_version_id"])
        package_id = str(run["package_id"])
        if not Path(self._store.data_dir, "packages", f"{package_id}.pkg.sqlite").exists():
            return (
                f"no package ledger exists for {package_id!r}; nothing was written",
                False,
            )
        # The grain pre-checks, BEFORE any write — the exact states M-DET's
        # cohort-grain re-derivation would otherwise refuse (or file under the
        # wrong run) only after M-PKG had minted a version, which would be a
        # partially-applied action (CT-CONSOLE-03). A re-derivation is
        # cohort-grain: it re-derives the criterion's scores for the whole
        # cohort and attributes its audit rows to the NEWEST run (latest
        # non-null started_at, then run_id — M-DET's `_newest_run`, "the run
        # whose grades the correction supersedes"). A cohort whose runs name
        # several packages, or a correction naming a run that is not that
        # newest one, refuses here — nothing was written — rather than
        # guessing which run the correction means or leaving one run's grades
        # silently stale. Recomputing every run of a multi-run cohort is a
        # design decision M-DET/M-ORCH own; the console claims nothing beyond
        # the single-run case.
        cohort_runs = list(
            cohort.query(
                "SELECT run_id, package_id, started_at FROM run "
                "WHERE cohort_id = :cohort_id ORDER BY run_id",
                cohort_id=str(run["cohort_id"]),
            )
        )
        cohort_packages = sorted({str(row["package_id"]) for row in cohort_runs})
        if len(cohort_packages) > 1:
            return (
                f"cohort {run['cohort_id']!r}'s runs name several packages "
                f"({cohort_packages}); which one a key correction applies to is a "
                "caller decision the console will not guess at — nothing was written",
                False,
            )
        newest = max(
            cohort_runs, key=lambda row: (row["started_at"] or "", row["run_id"])
        )
        if str(newest["run_id"]) != run_id:
            return (
                f"run {run_id!r} is not the cohort's newest run — the re-derivation's "
                f"audit records attribute to the newest run "
                f"({newest['run_id']}), so a correction naming an older run would "
                "file its trail under a run whose grades it did not supersede; "
                "correct that run instead — nothing was written",
                False,
            )
        catalog = PackageCatalog(self._store.package(package_id), package_id=package_id)
        pinned = {row["criterion_id"]: row for row in catalog.criteria(from_version)}
        if criterion_id not in pinned:
            return (
                f"criterion {criterion_id!r} does not exist in version "
                f"{from_version!r}; nothing was written",
                False,
            )
        if pinned[criterion_id].get("kind") != "mcq":
            return (
                f"criterion {criterion_id!r} is not a multiple-choice criterion: its "
                "scores are panel outputs, not key lookups, so a key correction "
                "re-derives nothing — nothing was written",
                False,
            )
        if pinned[criterion_id]["answer_key"] == tuple(key_ids):
            return (
                f"the key for {criterion_id} already reads {key_ids} against version "
                f"{from_version}; no new version was written",
                False,
            )
        # The mutating sequence, with every stage it completed named in any
        # refusal that fires after it: a failure mid-sequence (the re-derivation
        # refuses, the policy re-run refuses) may have already minted the
        # version, and "refused" that hides a written version is the partial
        # application CT-CONSOLE-03 forbids dressed as a clean refusal.
        progress: list[str] = []
        try:
            new_version = catalog.create_version(from_version)
            progress.append(
                f"package version {new_version} written (parent {from_version})"
            )
            catalog.set_answer_key(new_version, criterion_id, key_ids)
            report = DeterministicEvaluator(self._store).rederive_for_key_change(
                str(run["cohort_id"]), criterion_id, new_version,
                run_id=run_id,
            )
            progress.append(
                f"{report.scores_changed} deterministic score(s) re-derived by "
                f"lookup ({report.scores_unchanged} unchanged), "
                f"{report.audit_records_written} audit record(s) appended, "
                f"{report.panel_units_enqueued} panel judgment(s) enqueued"
            )
            with cohort.transaction() as tx:
                tx.execute(
                    "UPDATE run SET package_version_id = :version WHERE run_id = :run_id",
                    version=new_version,
                    run_id=run_id,
                )
            progress.append(f"run {run_id} re-pointed to the corrected version")
            GradingService(self._store).compute_all(run_id)
            progress.append("the grade policy re-ran over the run")
        except Exception as exc:  # noqa: BLE001 — a refusal is the honest outcome
            if progress:
                return (
                    f"the answer-key correction of {criterion_id} for run {run_id} was "
                    f"refused: {exc}. Completed before the refusal: {'; '.join(progress)} "
                    "— the correction is NOT complete, and the console does not report "
                    "it as done",
                    False,
                )
            return (
                f"the answer-key correction of {criterion_id} for run {run_id} was "
                f"refused: {exc} — nothing was written, and the console does not "
                "report a refused correction as done",
                False,
            )
        return (
            f"answer key for {criterion_id} corrected: package version {new_version} "
            f"written (parent {from_version}); {report.scores_changed} deterministic "
            f"score(s) re-derived by lookup ({report.scores_unchanged} unchanged), "
            f"{report.audit_records_written} audit record(s) appended, "
            f"{report.panel_units_enqueued} panel judgment(s) enqueued — a key "
            "correction re-answers a fixed answer, it does not ask a panel to "
            f"re-judge it; run {run_id} re-pointed to the corrected version and the "
            "grade policy re-ran over it",
            True,
        )
