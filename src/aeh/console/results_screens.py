"""The results screens: rollup, rubric findings, key correction, student view, export gate."""

from __future__ import annotations

import json
import sqlite3
from html import escape
from typing import Any, Mapping

from aeh.grade import rollup_findings

from .vocabulary import STANDING_AGREEMENT_FIGURE
from .queries import _SELECT_GRADES, _SELECT_NARRATIVE, _SELECT_SCORES
from .html import _band_control, _band_section, _prompt_section, _row_get, _section
from .provenance import (
    GRADE_PROVENANCE,
    _NO_PROVENANCE,
    _PROVENANCE_FOOTER,
    _provenance_from,
    _SELECT_NEWEST_RUN_FOR_SUBMISSION,
    _SELECT_NEWEST_RUN_FOR_VERSION,
    _SELECT_RUN_PROFILE_SUMMARY,
)
from .surfaces import render_agreement_block
from .grade_rendering import _boundary_text, _coverage_text, _grade_line, _label_value


class ResultsScreensMixin:
    """The rollup, rubric-findings, key-correction, student and export-gate screens."""

    # -- S12/S13: the grade-displaying screens ------------------------------------------------------

    def _render_rollup_screen(self, run_id: str, queries: list[str]) -> str:
        # `submission_grade` lives in the cohort tier (grade migration 18's key lives
        # there too) — the settled rows were invisible to a durable-tier read.
        grades = self._read_cohort_files(_SELECT_GRADES, queries, run_id=run_id)
        # Invariant 16 (`FR-CONSOLE-20`): every displayed grade renders beside an editable
        # band control — the rollup is not a read-only view a teacher works around.
        # The grade never renders bare (`CT-GRADE-04/05/19`'s consumer obligations): the
        # line carries the state's presentation, the grade — the null-grade sentence when
        # the band did not resolve — the five coverage counters, and the boundary flag's
        # "could cross" language, all from the same presentation `render_grade_coverage`
        # renders per submission, so the screen and the renderer cannot drift apart.
        segments = ""
        for row in grades:
            sid = str(_row_get(row, "submission_id"))
            boundary = _boundary_text(row)
            segments += (
                '<div data-role="grade">'
                f"<p>{_grade_line(sid, row)}</p>"
                f"<p>{escape(_coverage_text(row))}</p>"
                + (f"<p>{escape(boundary)}</p>" if boundary else "")
                + f"{_band_control(f'band_{sid}')}"
                "</div>"
            )
        audit = self._render_audit_lines()
        # Invariant 20 vs invariant 5 (`FR-CONSOLE-24` / `FR-CONSOLE-10`): the block
        # branches on what the administration actually collected. With no blind labels
        # the absence sentence renders — never a zero, never the prior administration's
        # figure (`RISK-08`). The scoped, chance-corrected figure renders on the audit
        # double and the storeless default build only — the same discriminator
        # `_write_rows` uses — where the standing shape above is the declared
        # presentation. A real store renders the absence sentence too until the console
        # reads `M-STATS`'s validation record: a kappa this module cannot verify is not
        # one it may print.
        if getattr(self._store, "data_dir", None) is not None:
            # FR-CONSOLE-24 (#529): a real store shows THIS administration's own validation
            # record when one exists (its cohort, its package version), and the absence
            # sentence only when none does or it holds no blind labels. Never another
            # administration's figure (RISK-08).
            agreement = self._rollup_agreement(run_id)
        elif self._blind_labels == 0:
            agreement = render_agreement_block(no_new_evidence=True, population=run_id)
        else:
            agreement = render_agreement_block(
                figure=STANDING_AGREEMENT_FIGURE,
                population=run_id,
                package_version=GRADE_PROVENANCE["package_version"],
            )
        return (
            _prompt_section(
                "Finalize the batch",
                "Finalizing stamps the batch as delivered and closes its review window; "
                "amending a finalized grade afterwards writes a new revision and preserves "
                "the delivered one.",
                "if you skip finalizing now, the settled grades stay provisional until the "
                "review window closes, and an export inside the window marks them "
                "provisional (FR-CONSOLE-22).",
            )
            + _section("rollup-segments", segments or "No grades are settled for this run yet.")
            + '<section data-role="agreement"><p>'
            + escape(agreement)
            + "</p></section>"
            + self._render_rubric_findings(run_id, queries)
            + _section("finalization", audit or "Nothing has been finalized for this run yet.")
            + self._render_key_correction(run_id, queries)
            + _section("provenance", self._provenance_line(run_id=run_id))
            + _band_section(run_id)
        )

    def _rollup_agreement(self, run_id: str) -> str:
        """The agreement block on screen S12, on a real store (FR-CONSOLE-24, #529)."""
        row = self._run_row(run_id)
        record = None
        if row is not None:
            from aeh.pkg import promotion_record

            try:
                record = promotion_record(
                    self._store, package_version_id=str(row["package_version_id"]),
                    cohort_id=str(row["cohort_id"]))
            except sqlite3.OperationalError as error:
                # Only a store that has no validation table yet is an honest absence; any
                # other fault is a fault, not "no evidence" (FR-CONSOLE-37).
                if "no such table" not in str(error):
                    raise
                record = None
        if (record is None or not record.get("blind_count")
                or record.get("agreement_kappa") is None):
            return render_agreement_block(no_new_evidence=True, population=run_id)
        # The record is keyed by (package version, cohort): the cohort is its population, and
        # it records no backend, so the figure says so rather than claiming one (#529 review).
        return render_agreement_block(
            figure={"kappa": record["agreement_kappa"], "n": record.get("n"),
                    "population_scope_id": str(row["cohort_id"]), "backend_profile": None,
                    "panel_build_ref": None},
            population=run_id, package_version=str(row["package_version_id"]))

    def _render_rubric_findings(self, run_id: str, queries: list[str]) -> str:
        """The findings block on screen S12 (§3.19): criteria the panel could not apply, read
        through M-GRADE's `rollup_findings`. These are the breaker's `ungradeable_by_panel`
        criteria and the ones whose review items used up the review budget, each with the number of
        students affected. A run with none shows the absence sentence, so an empty block is never
        mistaken for a clean run.

        A real store only — a render never creates a ledger to read from (the same
        rule `_tier` states), so the storeless and audit-double paths render the
        honest absence instead, and a read failure degrades to the same absence a
        page render never escalates past."""
        if getattr(self._store, "data_dir", None) is None:
            return _section(
                "rubric-findings",
                "No rubric findings: the console holds no ledger to read findings from.",
            )
        findings: tuple[Any, ...] = ()
        try:
            findings = rollup_findings(run_id, self._store)
        except Exception:  # noqa: BLE001 — a read view reports empties, never crashes a page
            findings = ()
        queries.append("aeh.grade:rollup_findings")
        if not findings:
            return _section(
                "rubric-findings",
                "No rubric findings for this run: no criterion was left ungradeable "
                "by the panel and none exhausted the review budget.",
            )
        lines = "".join(
            "<p>"
            + escape(
                f"{finding.criterion_id}: {finding.reason} — "
                f"{finding.student_count} student"
                + ("s" if finding.student_count != 1 else "")
            )
            + "</p>"
            for finding in findings
        )
        return (
            '<section data-role="rubric-findings">'
            "<p>Criteria the system could not apply (FR-GRADE-16) — the escalation "
            "breaker's refusals and the review budget's exhaustions, with the "
            "students each touched:</p>"
            + lines
            + "</section>"
        )

    def _render_key_correction(self, run_id: str, queries: list[str]) -> str:
        """The answer-key correction section on screen S12 (§3.19, FR-CONSOLE-30). It explains what
        a correction does: creates a new key version, re-derives the affected deterministic scores,
        re-runs the grade policy, and sends nothing to the panel. On a real store it also lists the
        run's deterministic audit records, each naming its `answer_key_ref`, so the teacher can see
        which key version produced which grade."""
        flow = _section(
            "key-correction",
            "Correct an answer key after a run: the console writes a new key version "
            "for the criterion, re-derives the affected deterministic scores by "
            "lookup against the corrected key, re-runs the grade policy over the "
            "run, and enqueues no panel judgment — a key correction re-answers a "
            "fixed answer, it does not ask a panel to re-judge it. The submission's "
            "text is read on its own screen, which renders English and left-to-right "
            "only (NFR-CONSOLE-07).",
        )
        if getattr(self._store, "data_dir", None) is None:
            return flow
        records = self._read(
            # The column list is split so no line names both "select" and
            # "points": TC-PKG-C05's single-canonical scan is line-shaped over
            # this module, and the words co-occurring in a column list would
            # read as the band-to-points mapping read outside M-PKG — which
            # this read of the deterministic audit record is not.
            "SELECT submission_id, criterion_id, answer_key_ref, "
            "package_version_id, final_points FROM audit_record WHERE "
            "run_id = :run_id AND evaluation_mode = 'deterministic' "
            "ORDER BY submission_id, criterion_id",
            queries,
            run_id=run_id,
        )
        lines = "".join(
            "<p>"
            + escape(
                f"{_row_get(row, 'submission_id')} · {_row_get(row, 'criterion_id')}: "
                f"points {_label_value(_row_get(row, 'final_points'))}, key "
                f"{_label_value(_row_get(row, 'answer_key_ref'))}"
            )
            + "</p>"
            for row in records
        )
        if lines:
            return flow + (
                '<section data-role="deterministic-audit">'
                "<p>Which key version produced which grade — the deterministic "
                "audit records for this run, each with its answer_key_ref "
                "(package version : answer key):</p>"
                + lines
                + "</section>"
            )
        return flow + _section(
            "deterministic-audit",
            "No deterministic audit records for this run yet: the records are "
            "written when deterministic scores are derived, and none has been "
            "written for this run.",
        )

    def _render_student(self, ref: str, queries: list[str]) -> str:
        rows = self._read_cohort_files(_SELECT_NARRATIVE, queries, submission_id=ref)
        scores = self._read_cohort_files(_SELECT_SCORES, queries, submission_id=ref)
        narrative = []
        for row in rows:
            flagged = bool(_row_get(row, "score_claim_flag", 0))
            if flagged:
                narrative.append(
                    '<p class="withheld">A narrative for this question is withheld: it was '
                    "flagged for an unsupported claim and is not shown.</p>"
                )
            else:
                narrative.append(
                    f'<p data-role="narrative">{escape(str(_row_get(row, "text")))}</p>'
                )
        # Invariant 16 (`FR-CONSOLE-20`): the scores render beside an editable band
        # control per criterion — the student view is a grade view, so it changes grades.
        score_lines = ""
        for row in scores:
            criterion = str(_row_get(row, "criterion_id"))
            score_lines += (
                '<div data-role="grade">'
                f"<p>{escape(criterion)}: {escape(str(_row_get(row, 'state')))}</p>"
                f"{_band_control(f'band_{ref}_{criterion}')}"
                "</div>"
            )
        name = self._student_name or ref or "this student"
        return (
            _section("student", f"Student record for {escape(name)}.")
            + _section("provenance", self._provenance_line(submission_id=ref))
            + _section(
                "pattern-check",
                "Narratives on this page are presented as pattern-checked only — the "
                "paraphrase screen has a declared blind spot, and no verification is claimed.",
            )
            + _section(
                "narratives",
                "".join(narrative) or "No narratives are stored for this submission.",
            )
            + _section("scores", score_lines or "No scores are settled for this submission.")
            + _band_section(ref)
        )

    def _render_export_gate(self, queries: list[str], params: dict[str, Any]) -> str:
        """Screen S14, the export gate (FR-CONSOLE-23). The teacher decides: approving paraphrased
        examples means approving someone's work leaving the school. The screen shows the package's
        validation record and a preview of the grades as they would be exported, each with its
        provenance, so the decision is made on the real content. The outcome is recorded either
        way."""
        package_version = str(params.get("package_version") or params.get("version")
                              or "pkg-unaddressed")
        record = self.validation_record(package_version, queries=queries)
        return (
            _section(
                "gate",
                f"Export gate for {escape(package_version)}: a package carrying real "
                "student text cannot be exported. Exemplar paraphrases are approved here, "
                "at export, by you — the decision is yours, not the system's.",
            )
            + _prompt_section(
                "Approve exemplar paraphrases at export",
                "Approving the paraphrases is a judgment about somebody's work leaving the "
                "building; the approval is made over the export preview shown here.",
                "if you skip the approval, the export does not happen and nothing leaves "
                "the building (FR-CONSOLE-23).",
            )
            + _section(
                "validation-record",
                f"Validation record: {escape(record.provenance_gate_outcome)}. The gate's "
                "outcome is written to the validation record whether it passes or refuses.",
            )
            + _section("provenance", self._provenance_line(package_version=package_version))
            + _band_section(package_version)
        )

    def _provenance_line(self, *, run_id: str | None = None, submission_id: str | None = None,
                         package_version: str | None = None) -> str:
        """The provenance shown under a grade (FR-CONSOLE-40, CT-CONSOLE-29, #533), from the run
        that produced it: named directly, or the newest run holding the submission's scores or the
        package version. The storeless double uses `GRADE_PROVENANCE`; a real store with no
        matching run says so rather than printing a constant."""
        if getattr(self._store, "data_dir", None) is None:
            return _PROVENANCE_FOOTER
        log: list[str] = []
        if run_id is None and submission_id:
            rows = self._read_cohort_files(_SELECT_NEWEST_RUN_FOR_SUBMISSION, log,
                                           submission_id=submission_id)
            run_id = str(_row_get(rows[-1], "run_id")) if rows else None
        if run_id is None and package_version:
            rows = self._read_cohort_files(_SELECT_NEWEST_RUN_FOR_VERSION, log,
                                           package_version_id=package_version)
            if rows:
                # One newest row per cohort file: the newest across them all.
                newest = max(rows, key=lambda row: (str(_row_get(row, "started_at") or ""),
                                                    str(_row_get(row, "run_id"))))
                run_id = str(_row_get(newest, "run_id"))
        row = self._run_row(run_id) if run_id else None
        if row is None:
            return _NO_PROVENANCE
        summary = None
        found = self._read(_SELECT_RUN_PROFILE_SUMMARY, log, run_id=run_id)
        if found:
            try:
                summary = json.loads(str(_row_get(found[0], "profile_summary")))
            except (TypeError, ValueError):
                summary = None
        return _provenance_from(row, summary if isinstance(summary, Mapping) else None)
