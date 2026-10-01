"""The grade policy, grade boundaries, answer keys and options, as stored on a version."""

from __future__ import annotations

import dataclasses
import json
import math
from typing import Sequence

from .vocabulary import PackageVersionId
from .errors import GradePolicyError, PackageError
from .grade_policy import default_grade_policy, GradePolicy, points_for_band
from .statements import PKG_STATEMENTS


class PolicyAndKeysMixin:
    """The grade policy, boundaries, answer keys and options of a version."""

    def points_for_band(self, criterion_id: str, band: str) -> float:
        """The points for a band; points never decrease as ordinals rise (FR-PKG-06).

        The per-criterion face of the module-level `points_for_band` — the single
        canonical mapping (`CT-PKG-05`): one definition, in M-PKG, and every
        consumer (`M-AGG`'s post-aggregation mapping at #91 included) routes
        through it (`NFR-AGG-02`)."""
        try:
            return points_for_band(self.bands(criterion_id), band)
        except PackageError as error:
            raise PackageError(
                f"criterion {criterion_id!r} declares no band {band!r}."
            ) from error

    # -- grade policy, boundaries, answer keys, elicitation history (#30) --------------------

    def set_grade_policy(self, v: PackageVersionId, policy: GradePolicy) -> None:
        """Store the grade policy (FR-PKG-14). Only a `GradePolicy` object is accepted: a string
        (such as a formula or an expression) is refused here, because an executable formula in a
        package would be a code-execution risk and a grade nobody can audit. The plain-language
        wording is generated on read (FR-PKG-15)."""
        if not isinstance(policy, GradePolicy):
            raise GradePolicyError(
                f"the grade policy must be a GradePolicy object drawn from the closed "
                f"rule vocabulary (FR-PKG-14); got {type(policy).__name__}. A "
                "free-text formula or an executable expression is refused — it is an "
                "arbitrary-code surface and an un-auditable grade."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "grade_policy.set")
            tx.execute(PKG_STATEMENTS["delete_policy"], v=v)
            tx.execute(PKG_STATEMENTS["insert_policy"], v=v,
                       policy=json.dumps(policy.to_dict(), sort_keys=True),
                       review_window_hours=policy.review_window_hours)
        self._invalidate()

    def set_review_window(self, v: PackageVersionId, hours: int | None) -> bool:
        """Set the review window (`grade_policy.review_window_hours`) on version `v` (FR-PKG-19,
        ADR-3); the console's "set review window" action. Returns whether anything changed.

        It goes through `set_grade_policy`, so it is under the same lock: ADR-3 puts the
        window inside the §6.2 lock, version-pinned with the rest of the policy, so a
        published version refuses (`PublishedVersionImmutableError`) and the sanctioned
        vehicle is a new version. `hours` is validated by `GradePolicy` (a non-negative
        int, or `None` for finalize-on-completion). Setting the stored value again writes
        nothing (`FR-CONSOLE-02`: a repeated post changes the ledger once)."""
        current = self.grade_policy(v)
        if current.review_window_hours == hours and self.grade_policy_declared(v):
            return False
        self.set_grade_policy(v, dataclasses.replace(current, review_window_hours=hours))
        return True

    def grade_policy(self, v: PackageVersionId) -> GradePolicy:
        """The version's grade policy (FR-PKG-14), parsed from the stored JSON and checked again
        against the allowed rules. `review_window_hours` comes from its own column (ADR-3); None
        means grades finalize when the run completes (FR-PKG-19). A version with no stored policy
        gets the default (FR-SETUP-12)."""
        rows = self._handle.query(PKG_STATEMENTS["select_policy"], v=v)
        if not rows:
            return default_grade_policy()
        try:
            data = json.loads(rows[0]["policy"])
        except (TypeError, ValueError) as error:
            # A row that is not even JSON — a formula stored by hand — is exactly the
            # FR-PKG-14 refusal, not a raw JSONDecodeError from the read path.
            raise GradePolicyError(
                f"the stored grade policy for version {v!r} is not a structured "
                f"object from the closed rule vocabulary (FR-PKG-14): {error}"
            ) from error
        data["review_window_hours"] = rows[0]["review_window_hours"]
        return GradePolicy.from_dict(data)

    def grade_policy_declared(self, v: PackageVersionId) -> bool:
        """Whether a grade-policy row is actually stored for the version. `grade_policy()` cannot
        tell, because it returns the default when there is none (FR-SETUP-12)."""
        return bool(self._handle.query(PKG_STATEMENTS["select_policy"], v=v))

    def set_boundaries(
        self, v: PackageVersionId, boundaries: Sequence[tuple[str, float]]
    ) -> None:
        """Set the version's grade boundary table (FR-PKG-16), the one place grade boundaries are
        defined. Each pair is `(grade, scaled_floor)`, and floors are inclusive: a score gets the
        grade with the highest floor at or below it. An empty sequence clears the table; with no
        rows, there are no boundaries (CT-PKG-10)."""
        grades = [grade for grade, _ in boundaries]
        floors = [float(floor) for _, floor in boundaries]
        if any(not grade for grade in grades):
            raise GradePolicyError(
                "a boundary table names each grade (FR-PKG-16) — an empty label "
                "resolves to nothing."
            )
        if len(set(grades)) != len(grades):
            raise GradePolicyError(
                f"duplicate grade labels {grades} — one label, one cut "
                "(FR-PKG-16's single canonical representation)."
            )
        if any(not math.isfinite(floor) for floor in floors):
            raise GradePolicyError(
                "boundary floors are finite scaled scores (FR-PKG-16)."
            )
        if len(set(floors)) != len(floors):
            raise GradePolicyError(
                f"duplicate scaled floors {floors} — two grades sharing one cut is "
                "an ambiguous resolution (FR-PKG-16)."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "grade_boundary.set")
            tx.execute(PKG_STATEMENTS["delete_boundaries"], v=v)
            for grade, floor in boundaries:
                tx.execute(PKG_STATEMENTS["insert_boundary"], v=v,
                           grade=grade, scaled_floor=float(floor))
        self._invalidate()

    def boundary_for(self, v: PackageVersionId, scaled_score: float) -> str | None:
        """The grade for a scaled score: the grade with the highest floor at or below the score
        (FR-PKG-16, CT-PKG-10). A score below every floor, or a version with no boundary table,
        gets None; no boundary is invented."""
        resolved: str | None = None
        for row in self._handle.query(PKG_STATEMENTS["select_boundaries"], v=v):
            if float(row["scaled_floor"]) <= scaled_score:
                resolved = row["grade"]
            else:
                break
        return resolved

    def distance_to_nearest_boundary(
        self, v: PackageVersionId, scaled_score: float
    ) -> float | None:
        """How far a scaled score is from the nearest grade boundary, used by M-REVIEW's ranking
        (FR-PKG-16). Exactly 0.0 on a boundary; None when the version has no boundary table
        (CT-PKG-10)."""
        rows = self._handle.query(PKG_STATEMENTS["select_boundaries"], v=v)
        if not rows:
            return None
        return min(abs(float(row["scaled_floor"]) - scaled_score) for row in rows)

    def set_answer_key(
        self, v: PackageVersionId, criterion_id: str, key: Sequence[str]
    ) -> None:
        """Set a multiple-choice criterion's answer key (FR-PKG-17, ADR-1): the acceptable option
        ids, one for single-select or several for multi-select. `criterion.answer_key` is the only
        place the key lives; options carry no correctness column, so a corrected key can never
        disagree with another copy. Refused on a published version: a correction is a new version
        (FR-PKG-18), which copies the old key and changes it there, so each grade's
        `answer_key_ref` points to exactly the key that produced it."""
        ids = [str(option) for option in key]
        if not ids or any(not option for option in ids):
            raise PackageError(
                "an answer key is a non-empty sequence of option ids (FR-PKG-17); an "
                "empty or blank key would grade every submission wrong identically."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.answer_key")
            if criterion_id not in {row["criterion_id"] for row in tx.execute(
                    PKG_STATEMENTS["select_criteria"], v=v)}:
                raise PackageError(
                    f"criterion {criterion_id!r} does not exist in version {v!r}."
                )
            tx.execute(PKG_STATEMENTS["update_criterion_answer_key"],
                       v=v, criterion_id=criterion_id, value=json.dumps(ids))
        self._invalidate()

    def answer_key(self, criterion_id: str) -> tuple[str, ...]:
        """The criterion's answer key from the newest version in the lineage, the one a grade
        produced now records (FR-PKG-17, CT-PKG-08). Earlier versions keep their own keys. An empty
        tuple when no key is set."""
        rows = self._handle.query(PKG_STATEMENTS["select_answer_key_latest"],
                                  criterion_id=criterion_id)
        if not rows or rows[0]["answer_key"] is None:
            return ()
        try:
            return tuple(json.loads(rows[0]["answer_key"]))
        except (TypeError, ValueError) as error:
            raise PackageError(
                f"criterion {criterion_id!r} holds a malformed answer key: {error}"
            ) from error

    def set_mcq_options(
        self, v: PackageVersionId, criterion_id: str,
        options: Sequence[tuple[str, str]],
    ) -> None:
        """Set the criterion's options as `(option_id, label)` pairs (FR-PKG-17). There is
        deliberately no correctness column: the key lives only on `criterion.answer_key` (ADR-1).
        Drafts only."""
        ids = [option_id for option_id, _ in options]
        if any(not option_id for option_id in ids):
            raise PackageError("an mcq option carries a non-empty option_id.")
        if len(set(ids)) != len(ids):
            raise PackageError(f"duplicate option ids {ids} — options are distinct.")
        with self._handle.transaction() as tx:
            self._guard(tx, v, "mcq_option.set")
            if criterion_id not in {row["criterion_id"] for row in tx.execute(
                    PKG_STATEMENTS["select_criteria"], v=v)}:
                raise PackageError(
                    f"criterion {criterion_id!r} does not exist in version {v!r}."
                )
            tx.execute(PKG_STATEMENTS["delete_mcq_options"], v=v,
                       criterion_id=criterion_id)
            for option_id, label in options:
                tx.execute(PKG_STATEMENTS["insert_mcq_option"], v=v,
                           criterion_id=criterion_id, option_id=option_id,
                           label=label)
        self._invalidate()

    def mcq_options(self, v: PackageVersionId, criterion_id: str) -> tuple:
        """The criterion's options as `(option_id, label)` pairs, for display (FR-PKG-17). Which is
        correct is not here; read the answer key."""
        rows = self._handle.query(PKG_STATEMENTS["select_mcq_options"], v=v,
                                  criterion_id=criterion_id)
        return tuple((row["option_id"], row["label"]) for row in rows)

    def set_default_grade_policy(self, v: PackageVersionId,
                                 policy: GradePolicy) -> bool:
        """Write the default grade policy only if the version has none, so a policy the teacher
        declared is never overwritten (FR-SETUP-12). Returns whether a row was written. The checks
        run before the transaction, because the publish path's audit (CT-SETUP-02) allows exactly
        one lock-related statement inside it."""
        if not isinstance(policy, GradePolicy):
            raise GradePolicyError(
                f"the grade policy must be a GradePolicy object drawn from the closed "
                f"rule vocabulary (FR-PKG-14); got {type(policy).__name__}."
            )
        if self.grade_policy_declared(v):
            return False
        self._refuse_mutation(v)
        with self._handle.transaction() as tx:
            tx.execute(PKG_STATEMENTS["delete_policy"], v=v)
            tx.execute(PKG_STATEMENTS["insert_policy"], v=v,
                       policy=json.dumps(policy.to_dict(), sort_keys=True),
                       review_window_hours=policy.review_window_hours)
        self._invalidate()
        return True
