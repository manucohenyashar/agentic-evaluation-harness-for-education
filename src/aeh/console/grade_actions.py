"""Grade actions: amending a grade, recording the gate outcome, setting the review window."""

from __future__ import annotations

from .records import ControlOutcome, GradeRecord


class GradeActionsMixin:
    """Amends a grade, records the export-gate outcome and sets the review window."""

    def amend_grade(
        self,
        *,
        submission_ref: str,
        criterion_id: str = "",
        new_band: str = "",
        actor: str = "operator",
    ) -> GradeRecord:
        """Amend a grade as §11.8 describes: the delivered grade keeps its `finalized_at` (the
        record of when it was delivered), and the correction is stored as a new revision in the
        append-only history. The old revision stays readable (FR-CONSOLE-21, CT-CONSOLE-15).

        On a store the amendment is M-GRADE's (`GradingService.amend`, #398): the new
        revision is in the ledger, readable by any console, and a refusal raises
        `KeyError` carrying M-GRADE's reason. The in-memory history below is only the
        storeless audit double's."""
        if getattr(self._store, "data_dir", None) is not None:
            outcome = self.perform(
                "amend a finalized grade", submission_ref=submission_ref,
                criterion_id=criterion_id, new_band=new_band, actor=actor)
            if not outcome.dispatched:
                raise KeyError(outcome.detail)
            self._audit.append(
                f"amended_by {actor} (actor as supplied by the form, not an authenticated "
                f"identity): submission {submission_ref}, criterion {criterion_id} to band "
                f"{new_band}; {outcome.detail}"
            )
            current = self.grade_revision(submission_ref=submission_ref)
            if current is None:
                raise KeyError(f"the amendment of {submission_ref!r} left no current grade")
            return current
        delivered = self._grade_ledger.get(submission_ref, [])
        if not delivered:
            raise KeyError(
                f"no finalized grade for {submission_ref!r} to amend; finalize the batch first"
            )
        previous = delivered[-1]
        corrected = GradeRecord(
            finalized_at=previous.finalized_at,
            revision=previous.revision + 1,
            bands=previous.bands + (f"{criterion_id}={new_band}",),
            provisional=previous.provisional,
        )
        self._grade_ledger[submission_ref].append(corrected)
        self.perform(
            "amend a finalized grade",
            submission_ref=submission_ref,
            revision=corrected.revision,
            bands=corrected.bands,
            actor=actor,
        )
        self._audit.append(
            f"amended_by {actor} (actor as supplied by the form, not an authenticated "
            f"identity): submission {submission_ref}, criterion {criterion_id or 'unspecified'} "
            f"to band {new_band or 'unspecified'}; revision {previous.revision} superseded, "
            "not overwritten"
        )
        return corrected

    def record_gate_outcome(self, package_version: str, outcome: str,
                            actor: str | None = None) -> None:
        """Record the export gate's outcome for the package (FR-CONSOLE-23). It is written whether
        the gate passed or refused, because an unrecorded gate cannot be told apart from a skipped
        one (R71)."""
        # Written to the package's own store (#528, design 1.9 §5.1 R16): Tier D's
        # `audit_record` is the wrong home, because M-STATS' `promote` sources unclaimed audit
        # rows. The in-memory copy stays for the storeless console.
        self._gate_outcomes[package_version] = outcome
        catalog = self._gate_catalog(package_version)
        if catalog is not None:
            try:
                catalog.record_export_gate_outcome(package_version, outcome, actor=actor)
            except Exception as error:  # noqa: BLE001 — e.g. a version the package lacks
                # The refusal must still surface as the gate's refusal, never as a raw
                # database error; the audit line says the outcome was not stored.
                self._audit.append(
                    f"provenance gate outcome for {package_version} not stored: "
                    f"{type(error).__name__}")
        self._audit.append(f"provenance gate for {package_version}: {outcome}")

    def set_review_window(self, run_id: str = "r-unaddressed", *, hours: float) -> ControlOutcome:
        """Set the review window: one `grade_policy.review_window_hours` row, plus the console's
        note that finalization for this run is delayed, never withheld (FR-CONSOLE-22). On a real
        store only M-PKG's column is written (#398); the in-memory note is for the storeless test
        double."""
        if getattr(self._store, "data_dir", None) is None:
            self._review_windows[run_id] = hours
        return self.perform(
            "set review window", run_id=run_id, review_window_hours=hours
        )
