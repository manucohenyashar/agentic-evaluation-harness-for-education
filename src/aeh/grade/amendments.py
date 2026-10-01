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
        """The overrides the submission's current grade revision records (its `amendments` JSON),
        or `{}` when there are none or no current grade. `amend` audits every call, which is right
        for a person's action but wrong for a replayed request, so a caller that must not repeat an
        amendment (a console double-post, FR-CONSOLE-02) checks this first."""
        run = self._run_row(run_id)
        rows = self._store.cohort(run["cohort_id"]).query(
            GRADE_STATEMENTS["select_current_grade"], run_id=run_id, submission_id=submission_id)
        return _amendment_map(rows[0]["amendments"]) if rows else {}

    def effective_points(self, run_id: str, submission_id: str, criterion_id: str) -> float | None:
        """The points the current grade counts for one criterion: the current revision's override
        if it has one, else the stored score's points, else None. A console that must not repeat an
        amendment compares against this, because `amend` audits every call, even ones that change
        nothing."""
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
        """Apply a teacher's manual amendment (design §3.14). The edits are overrides on this grade
        only; M-GRADE never writes the criterion scores themselves, which belong to M-AGG
        (CT-GRADE-14). The amended grade becomes revision n+1.

        More detail: `docs/code-notes/grade.md`, section `amendments.py: AmendmentMixin.amend`.
        """
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
        """Append the amendment's one audit record (TC-GRADE-13): who made it (`decided_by`), when
        (`recorded_at`), and what and why as canonical JSON in `profile_summary` (the
        criterion-level detail, totals before and after, the revision produced, and the outcome).
        It is written after the cohort revision commits, in its own durable transaction."""
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
