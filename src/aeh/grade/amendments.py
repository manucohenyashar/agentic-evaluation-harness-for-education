"""Manual grade amendments: a new revision plus an audit record, never an edit in place."""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

from .constants import STATE_FINAL, STATE_INCOMPLETE, STATE_PROVISIONAL
from .stored_rows import _amendment_map, _row_value, _with_amendments
from .schema import GRADE_STATEMENTS
from .records import GradeError, GradeRevision


class AmendmentMixin:
    """Applies a teacher's manual amendment as a new grade revision, with an audit record."""

    def current_amendments(self, run_id: str, submission_id: str) -> dict[str, float]:
        """The override map the submission's CURRENT grade revision records (its
        `amendments` JSON), `{}` when it has none or no current grade exists. A caller that
        must not repeat an amendment (a console double-post, #398 / FR-CONSOLE-02) reads it
        first: `amend` itself audits every call, which is right for a human action and
        wrong for a replayed request."""
        run = self._run_row(run_id)
        rows = self._store.cohort(run["cohort_id"]).query(
            GRADE_STATEMENTS["select_current_grade"], run_id=run_id, submission_id=submission_id)
        return _amendment_map(rows[0]["amendments"]) if rows else {}

    def effective_points(self, run_id: str, submission_id: str, criterion_id: str) -> float | None:
        """The points the current grade counts for one criterion: the current revision's
        amendment override when it records one, else the stored score's points, else
        `None`. A console that must not repeat an amendment (#398) compares with this:
        `amend` audits every call, the no-op ones included."""
        recorded = self.current_amendments(run_id, submission_id)
        if criterion_id in recorded:
            return recorded[criterion_id]
        run = self._run_row(run_id)
        for row in self._store.cohort(run["cohort_id"]).query(
                GRADE_STATEMENTS["select_submission_scores"], run_id=run_id,
                submission_id=submission_id):
            if row["criterion_id"] == criterion_id:
                value = _row_value(row, "points")
                return None if value is None else float(value)
        return None

    def amend(
        self,
        run_id: str,
        submission_id: str,
        edits: Mapping[str, float],
        actor: str,
        reason: str,
    ) -> GradeRevision:
        """A manual grade amendment (§3.14's Protocol member): the edits are applied
        over the stored scores as **overrides on this grade only** — this module never
        writes `criterion_score` (`CT-GRADE-14`: that table is M-AGG's alone) — and
        the amended grade lands as revision n+1. The overrides are recorded on the
        grade row itself (`amendments`), which is also what keeps the revision
        recomputable (`FR-GRADE-13` reaching amended revisions): a later pass replays
        the recorded map before comparing content, so an unchanged re-run reproduces
        the amended grade instead of reverting it.

        The settlement follows the state model, not the action: an amendment of a
        grade with all inputs present settles `final` (the teacher just reviewed it),
        preserving the prior revision's `finalized_at`; one whose inputs are still
        missing stays `incomplete` — an edit never launders an absence into a
        deliverable. An edit naming a criterion with no stored score row is refused,
        naming it: recording an edit that applied nowhere would claim a change that
        never happened, and a missing input is the operator routing's to fill.

        **No new revision without a change** (`NFR-GRADE-05`, TC-GRADE-13's no-op
        variant): an edit whose application reproduces the current revision's content
        EXACTLY — re-entering the points a revision already carries — writes no
        revision. The comparison is the compute passes' own change-detection tuple, so
        "changed" means the same thing here as everywhere else in the module. The
        review the call records is still real: a no-op amendment settles the current
        revision `final` in place when the state model pressures it (the teacher
        reviewed it), and the call is appended to the audit trail either way — the
        ledger records content changes, the audit trail records human actions.

        Every amendment call — minting or not — also appends one `audit_record` row to
        Tier D (the durable form of the who/what/when/why record; the `amendments` JSON
        on the grade row stays the revision-local record the recomputation replays):
        one row per call, `decided_by` the actor, `evaluation_mode='judged'` (a
        teacher's decision, never a derivation), the full criterion-level detail
        canonical-JSON in `profile_summary`. The write follows the cohort
        transaction's commit — tiers are separate files, so the two writes cannot share
        one transaction, and an audit row is never written for a revision that failed
        to land."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        surface = self._policy_surface(
            self._store.package(run["package_id"]),
            run["package_id"],
            run["package_version_id"],
        )
        current_row = cohort.query(
            GRADE_STATEMENTS["select_current_grade"], run_id=run_id,
            submission_id=submission_id,
        )
        if not current_row:
            raise GradeError(
                f"submission {submission_id!r} in run {run_id!r} has no grade to amend"
            )
        prior = dict(current_row[0])
        rows = cohort.query(
            GRADE_STATEMENTS["select_submission_scores"], run_id=run_id,
            submission_id=submission_id,
        )
        overrides = {criterion_id: float(points) for criterion_id, points in edits.items()}
        applicable = {
            row["criterion_id"]
            for row in rows
            if _row_value(row, "points") is not None
        }
        refused = sorted(set(overrides) - applicable)
        if refused:
            raise GradeError(
                f"amendment refused for submission {submission_id!r} in run {run_id!r}: "
                f"criterion {', '.join(refused)} has no stored score row to override — "
                "a missing input is filled by the operator routing (rescan), never "
                "edited into place"
            )
        outcome = self._submission_computation(surface, _with_amendments(rows, overrides))
        state = (
            STATE_INCOMPLETE
            if outcome["coverage"].criteria_missing > 0
            else STATE_FINAL
        )
        now_raw = self._clock()
        if self._content_of(outcome) == self._stored_content(prior):
            # The no-op rule (NFR-GRADE-05): the edit's application reproduces the
            # current revision's content exactly, so no revision is minted — the
            # ledger already holds this grade. The only write the call may still
            # make is the settlement the state model commands: a fully scored
            # grade the teacher just reviewed settles `final` IN PLACE (the same
            # in-place arrow the compute passes use, never a mint).
            if (
                outcome["coverage"].criteria_missing == 0
                and prior["state"] == STATE_PROVISIONAL
            ):
                with cohort.transaction() as tx:
                    tx.execute(
                        GRADE_STATEMENTS["settle_current"],
                        run_id=run_id,
                        submission_id=submission_id,
                        state=STATE_FINAL,
                        settled_at=prior["finalized_at"] or now_raw,
                    )
            self._write_amendment_audit(
                run, surface, submission_id, int(prior["revision"]), overrides,
                prior_total=prior["total"], new_total=outcome["total"],
                actor=actor, reason=reason, at=now_raw, outcome="no_content_change",
            )
            return GradeRevision(
                submission_id=submission_id,
                revision=int(prior["revision"]),
                state=STATE_FINAL
                if outcome["coverage"].criteria_missing == 0
                else STATE_INCOMPLETE,
                grade=outcome["grade"],
                total=outcome["total"],
                actor=actor,
                reason=reason,
            )
        revision = int(prior["revision"]) + 1
        settled_at = prior["finalized_at"] or now_raw
        with cohort.transaction() as tx:
            tx.execute(
                GRADE_STATEMENTS["demote_current"],
                run_id=run_id,
                submission_id=submission_id,
                superseded_at=now_raw,
            )
            tx.execute(
                GRADE_STATEMENTS["insert_grade"],
                run_id=run_id,
                submission_id=submission_id,
                revision=revision,
                state=state,
                grade=outcome["grade"],
                total=outcome["total"],
                policy_version=surface["policy_version"],
                answer_key_ref=surface["answer_key_ref"],
                package_version_id=surface["package_version_id"],
                computed_at=now_raw,
                finalized_at=settled_at if state == STATE_FINAL else None,
                criteria_total=outcome["coverage"].criteria_total,
                criteria_auto=outcome["coverage"].criteria_auto,
                criteria_reviewed=outcome["coverage"].criteria_reviewed,
                criteria_provisional=outcome["coverage"].criteria_provisional,
                criteria_missing=outcome["coverage"].criteria_missing,
                boundary_at_risk=1 if outcome["boundary"].at_risk else 0,
                score_low=outcome["boundary"].score_low,
                score_high=outcome["boundary"].score_high,
                missing_criteria=json.dumps(
                    list(outcome["missing"]), sort_keys=True
                ),
                amendments=json.dumps(
                    [
                        {
                            "criterion_id": criterion_id,
                            "points": points,
                            "actor": actor,
                            "reason": reason,
                            "at": now_raw,
                        }
                        for criterion_id, points in sorted(overrides.items())
                    ],
                    sort_keys=True,
                ),
            )
        self._write_amendment_audit(
            run, surface, submission_id, revision, overrides,
            prior_total=prior["total"], new_total=outcome["total"],
            actor=actor, reason=reason, at=now_raw, outcome="revision_minted",
        )
        return GradeRevision(
            submission_id=submission_id,
            revision=revision,
            state=state,
            grade=outcome["grade"],
            total=outcome["total"],
            actor=actor,
            reason=reason,
        )

    def _write_amendment_audit(
        self,
        run: Any,
        surface: dict[str, Any],
        submission_id: str,
        revision: int,
        overrides: Mapping[str, float],
        *,
        prior_total: Any,
        new_total: Any,
        actor: str,
        reason: str,
        at: str,
        outcome: str,
    ) -> None:
        """Append the amendment's one `audit_record` row (TC-GRADE-13 step 4's Tier D
        form, the #106 reconciliation): who (`decided_by`), when (`recorded_at`), and
        the what/why canonical JSON in `profile_summary` — the criterion-level detail,
        the totals before and after, the revision it produced (or stood behind), and
        the content outcome. Appends AFTER the cohort revision commits, in its own
        durable transaction (det.py's audit append is the same-footing precedent)."""
        with self._store.durable().transaction() as tx:
            tx.execute(
                GRADE_STATEMENTS["insert_amendment_audit_record"],
                audit_record_id=uuid.uuid4().hex,
                run_id=run["run_id"],
                recorded_at=at,
                profile_summary=json.dumps(
                    {
                        "event": "grade_amendment",
                        "run_id": run["run_id"],
                        "submission_id": submission_id,
                        "revision": revision,
                        "criteria": [
                            {"criterion_id": criterion_id, "points": points}
                            for criterion_id, points in sorted(overrides.items())
                        ],
                        "from_total": prior_total,
                        "to_total": new_total,
                        "reason": reason,
                        "outcome": outcome,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                submission_id=submission_id,
                decided_by=actor,
                package_version_id=surface["package_version_id"],
                evaluation_mode="judged",
            )
