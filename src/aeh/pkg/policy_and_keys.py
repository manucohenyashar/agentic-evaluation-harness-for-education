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
        """The band→points mapping, monotone in ordinal (`FR-PKG-06`'s guarantee).

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
        """Store the executed policy (`FR-PKG-14`). Only a `GradePolicy` instance is
        accepted — a string (a free-text formula, an executable expression, a
        lambda-shaped string) is refused HERE rather than stored and interpreted later,
        because an executable formula in a package is an arbitrary-code surface and an
        un-auditable grade. `plain_language` needs no storage: it is generated from the
        object on read (`FR-PKG-15`)."""
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
        """Set `grade_policy.review_window_hours` on version `v` (`FR-PKG-19`, ADR-3; the
        console's "set review window" door, #398 / test plan Q-22). Returns whether
        anything changed.

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
        """The executed policy as a structured object (`FR-PKG-14`): parsed from the
        stored JSON and RE-VALIDATED against the closed vocabulary, so a hand-edited row
        holding a formula refuses on read too. `review_window_hours` comes from its
        column (ADR-3) — null means finalize on run completion (`FR-PKG-19`), never wait
        indefinitely. A version with no stored policy answers the default
        (`FR-SETUP-12`) — M-GRADE always finds a policy and never has to invent one."""
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
        """Whether a grade-policy ROW is stored for the version (`#53`): the
        distinction `grade_policy()` cannot make, since it answers the default
        when no row exists — `FR-SETUP-12`'s recording obligation needs to know
        whether the default was ever written down."""
        return bool(self._handle.query(PKG_STATEMENTS["select_policy"], v=v))

    def set_boundaries(
        self, v: PackageVersionId, boundaries: Sequence[tuple[str, float]]
    ) -> None:
        """Declare the version's grade boundary table (`FR-PKG-16`) — the SINGLE
        canonical representation of the grade resolution rule; the policy object carries
        no copy of it. Each pair is (grade, scaled_floor). Floors are INCLUSIVE:
        `boundary_for` resolves a scaled score to the grade with the greatest floor
        <= the score. An empty sequence clears the table (a draft's no-boundary-table
        state); CT-PKG-10's null-equivalent is the ABSENCE of rows, and callers handle
        that rather than inventing boundaries."""
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
        """`FR-PKG-16`/`CT-PKG-10`: the grade for a scaled score — a PURE lookup over
        `grade_boundary`, the single canonical representation. Floors are INCLUSIVE
        (the declared rule): the grade with the greatest floor <= the score. A score
        below the lowest floor has no grade, and a version with NO boundary table
        answers None — never an invented boundary."""
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
        """`FR-PKG-16`: how far a scaled score sits from the nearest cut — M-REVIEW's
        boundary-proximity ranking signal. Exactly 0.0 ON a cut. None where the version
        declares no boundary table (`CT-PKG-10`) — the caller handles it; no invented
        distance."""
        rows = self._handle.query(PKG_STATEMENTS["select_boundaries"], v=v)
        if not rows:
            return None
        return min(abs(float(row["scaled_floor"]) - scaled_score) for row in rows)

    def set_answer_key(
        self, v: PackageVersionId, criterion_id: str, key: Sequence[str]
    ) -> None:
        """Declare the multiple-choice key (`FR-PKG-17`, ADR-1):
        `criterion.answer_key` is the SINGLE canonical representation — `mcq_option`
        carries no correctness column, so a corrected key cannot leave two disagreeing
        sources. The key is the sequence of acceptable option ids (one for
        single-select, several for multi-select). Refused on a published version: a key
        CORRECTION is a new version (`FR-PKG-18`) — create_version(parent, ...) copies
        the prior key into the child, the correction lands there, and
        `audit_record.answer_key_ref` resolves to exactly the key that produced a given
        grade."""
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
        """`FR-PKG-17`/`CT-PKG-08`: the criterion's key, from the version currently at
        the top of the lineage — the one a grade produced NOW pins by
        `answer_key_ref`. A prior version's key stays exactly where it was (read it
        version-pinned via `criteria(parent_v)`), which is what makes `FR-PKG-18`'s
        resolution exact. No key declared yet answers the empty tuple."""
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
        """Declare the criterion's options as (option_id, label) pairs (`FR-PKG-17`).
        Deliberately NO correctness column exists on `mcq_option` (ADR-1): the key
        lives once, on `criterion.answer_key`. Drafts only — the triggers refuse
        published versions."""
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
        """The criterion's declared options, as (option_id, label) pairs — the display
        half of `FR-PKG-17`. Correctness is NOT here (ADR-1): read the key."""
        rows = self._handle.query(PKG_STATEMENTS["select_mcq_options"], v=v,
                                  criterion_id=criterion_id)
        return tuple((row["option_id"], row["label"]) for row in rows)

    def set_default_grade_policy(self, v: PackageVersionId,
                                 policy: GradePolicy) -> bool:
        """Write the default policy row ONLY where no policy exists — the
        publish-path twin of `record_default_step` (`FR-SETUP-12`): a policy the
        teacher declared is never overwritten by the default. Returns whether a
        row was written. The guards run BEFORE the transaction, for the same
        reason `record_default_step`'s do: this write sits on the publish path's
        happy tail, and CT-SETUP-02 audits that path to exactly ONE lock-carrying
        statement — an in-transaction guard would put a second package_version
        statement (the guard's SELECT) in the audited window."""
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
