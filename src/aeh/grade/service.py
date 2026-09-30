"""`GradingService`: computes every grade of a run in one pass and stores it."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from aeh.pkg import PKG_STATEMENTS, PackageCatalog, points_for_band
from aeh.store import Store

from .constants import (
    _GRADE_RUN_STORES,
    _PROVISIONAL_ROUTINGS,
    _RESCAN_DIRECTIVE,
    ROUTING_TRIAGE,
    STATE_FINAL,
    STATE_INCOMPLETE,
    STATE_PROVISIONAL,
    STATUS_COMPLETE,
)
from .refs import answer_key_ref_of, _content_hash, _now, _parse_timestamp, policy_version_of
from .policy import (
    apply_policy,
    boundary_risk,
    BoundaryRisk,
    Coverage,
    coverage_for,
    CriterionInput,
    resolve_grade,
)
from .stored_rows import _amendment_map, _row_value, _with_amendments
from .schema import GRADE_STATEMENTS
from .records import GradeError, GradeReport, SubmissionGrade
from .finalization import FinalizationMixin
from .amendments import AmendmentMixin
from .reporting import ReportingMixin


class GradingService(FinalizationMixin, AmendmentMixin, ReportingMixin):
    """The grading service (design §3.14): compute, finalize, amend, roll up and export grades. It
    is the only writer of `submission_grade`, and never writes criterion scores, verdicts or
    narratives (CT-GRADE-14).

    The service reads the run's package version from the run row and resolves policy,
    boundaries, criteria and answer keys through M-PKG's shipped API — the policy is
    always found (`grade_policy()` answers the default, `FR-SETUP-12`), never invented.
    """

    def __init__(self, store: Store, *, clock: Callable[[], str] | None = None) -> None:
        self._store = store
        self._clock = clock or _now

    # -- reads ------------------------------------------------------------------

    def _cohort_keys(self) -> tuple[str, ...]:
        """The store's cohort ids, sorted: one ledger file per cohort under `<data_dir>/cohorts/`,
        the same discovery the orchestrator uses. There is no separate index of run ids."""
        data_dir = getattr(self._store, "data_dir", None)
        if data_dir is None:
            raise GradeError(
                "this store exposes no `data_dir`, so the run's cohort ledger cannot "
                "be discovered; pass a store laid out per §3.3"
            )
        return tuple(
            path.stem for path in Path(data_dir, "cohorts").glob("*.sqlite")
        )

    def _find_run(self, run_id: str) -> tuple[Any, Any]:
        """`(cohort handle, run row)` for one run; the writers need both. The run row lives in its
        cohort's Tier C file (FR-ORCH-02)."""
        for key in self._cohort_keys():
            cohort = self._store.cohort(key)
            rows = cohort.query(GRADE_STATEMENTS["select_grade_run"], run_id=run_id)
            if rows:
                return cohort, rows[0]
        raise GradeError(
            f"no run row named {run_id!r} exists in any cohort ledger of this store"
        )

    def _run_row(self, run_id: str) -> Any:
        """The run row, or a refusal naming the run: a missing run is a caller mistake, not an
        empty batch. It also registers the store under the run id, which is how
        `record_grade_signals` and `evaluate_grade_alerts` find it later."""
        row = self._find_run(run_id)[1]
        _GRADE_RUN_STORES[run_id] = self._store
        return row

    def _policy_surface(
        self, package_handle: Any, package_id: str, version: str
    ) -> dict[str, Any]:
        """Everything the package contributes to a grading pass: the effective policy and its hash,
        the boundary table, the list of criteria, the answer-key hash, and each criterion's band
        range (the cautious range source for `boundary_risk`)."""
        catalog = PackageCatalog(package_handle, package_id=package_id)
        policy = catalog.grade_policy(version)
        boundaries = [
            (row["grade"], float(row["scaled_floor"]))
            for row in package_handle.query(PKG_STATEMENTS["select_boundaries"], v=version)
        ]
        criteria_rows = list(
            package_handle.query(PKG_STATEMENTS["select_criteria"], v=version)
        )
        criteria_ids = [row["criterion_id"] for row in criteria_rows]
        keys = [
            (row["criterion_id"], json.loads(row["answer_key"]))
            for row in package_handle.query(
                GRADE_STATEMENTS["select_version_answer_keys"], v=version
            )
        ]
        # Each criterion's declared band range — mapped through the single
        # canonical band→points reader (CT-PKG-05) over the version-scoped rows,
        # never by reading the band table's column here.
        bands_by_criterion: dict[str, list[dict]] = {}
        for row in package_handle.query(PKG_STATEMENTS["select_bands"], v=version):
            bands_by_criterion.setdefault(row["criterion_id"], []).append(dict(row))
        band_spans: dict[str, tuple[float, float]] = {}
        for criterion_id, rows in bands_by_criterion.items():
            spans = [float(points_for_band(rows, band["band"])) for band in rows]
            band_spans[criterion_id] = (min(spans), max(spans))
        return {
            "policy": policy,
            "policy_version": policy_version_of(policy),
            "boundaries": boundaries,
            "criteria_ids": criteria_ids,
            "answer_key_ref": answer_key_ref_of(keys),
            "band_spans": band_spans,
            "package_version_id": version,
        }

    # -- the computation ---------------------------------------------------------

    def _submission_computation(
        self, surface: dict[str, Any], rows: Iterable[Any]
    ) -> dict[str, Any]:
        """Compute one submission's grade from its stored criterion scores: coverage, the policy,
        the band and the boundary risk. Recomputation replays this; the stored scores plus the
        policy version reproduce the grade exactly (FR-GRADE-13)."""
        inputs = [
            CriterionInput(
                criterion_id=row["criterion_id"],
                band=row["band"],
                points=float(points),
                routing=row["routing"],
                state=row["state"],
            )
            for row in rows
            if (points := _row_value(row, "points")) is not None
            and row["routing"] != ROUTING_TRIAGE
        ]
        criteria_ids = surface["criteria_ids"]
        coverage = coverage_for(inputs, criteria_ids)
        present = {item.criterion_id: item.points for item in inputs}
        missing = tuple(cid for cid in criteria_ids if cid not in present)
        computation = apply_policy(inputs, surface["policy"])
        total = computation.total
        if total is None:
            # The gate refused: the row exists, the figure does not — NULL total and
            # NULL grade, never an exception and never the ungated sum.
            return {
                "total": None,
                "grade": None,
                "coverage": coverage,
                "boundary": BoundaryRisk(at_risk=False, score_low=None, score_high=None),
                "missing": missing,
            }
        # The provisional criteria's movement intervals, in the SAME space the total
        # lives in: a criterion's possible band movement is a raw-points spread, but
        # the total has been multiplied by its weight (weighted_sum) and the policy's
        # scale factor by the time `boundary_risk` compares it to the boundary
        # floors — so the offset crosses the same transforms the score did. Two
        # disclosed slops, both in the honest direction for a proximity flag: the
        # interval is taken before the final rounding step (its endpoints can sit up
        # to half a rounding quantum from an exactly-roundable total), and for the
        # selection rules (`best_k_of_n`/`drop_lowest_n`) the movement is assumed not
        # to cross the selection cut — a band move that changed the selected SET is
        # a different combination, not this criterion's interval.
        policy = surface["policy"]
        factor = policy.scale.factor if policy.scale is not None else 1.0
        weights = (
            {cid: w for cid, w in (policy.weights or ())}
            if policy.combination == "weighted_sum"
            else {}
        )
        intervals = []
        for item in inputs:
            if item.routing in _PROVISIONAL_ROUTINGS:
                span = surface["band_spans"].get(item.criterion_id)
                if span is None:
                    # No declared band range to move within: the honest interval is
                    # "no knowledge of movement", not a invented full range.
                    intervals.append((0.0, 0.0))
                else:
                    current = present[item.criterion_id]
                    coefficient = weights.get(item.criterion_id, 1.0) * factor
                    intervals.append(
                        (
                            (span[0] - current) * coefficient,
                            (span[1] - current) * coefficient,
                        )
                    )
        risk = boundary_risk(total, intervals, surface["boundaries"])
        grade = resolve_grade(total, surface["boundaries"])
        return {
            "total": total,
            "grade": grade,
            "coverage": coverage,
            "boundary": risk,
            "missing": missing,
        }

    @staticmethod
    def _content_of(computed: dict[str, Any]) -> tuple:
        """The content a revision stores, used to detect change (NFR-GRADE-05). It excludes state,
        provenance and timestamps, so a re-run under a copied-forward version writes nothing
        (TC-GRADE-12)."""
        return (
            computed["grade"],
            computed["total"],
            computed["coverage"].as_tuple(),
            bool(computed["boundary"].at_risk),
            computed["boundary"].score_low,
            computed["boundary"].score_high,
            json.dumps(list(computed["missing"]), sort_keys=True),
        )

    @staticmethod
    def _settlement_state(
        current: Mapping[str, Any] | None,
        *,
        run_complete: bool,
        window_hours: int | None,
        issued_at: datetime,
        now: datetime,
        fresh_issuance: bool = False,
        input_missing: bool = False,
    ) -> str:
        """The state a grade has after this pass: `incomplete` while an input is missing (it waits
        for an operator, not a window); otherwise `final` when the run completed or the review
        window lapsed, else `provisional` (FR-GRADE-10, ADR-3).

        `input_missing` is THIS pass's verdict — the computed outcome's
        `criteria_missing`, which the caller owns. The prior revision's counters are
        deliberately not read here: a submission whose rescan filled its missing
        inputs must lift out of `incomplete` on the recomputation, and a
        prior-revision check would pin it there forever, contradicting FR-GRADE-07's
        biconditional (`incomplete` only when `criteria_missing > 0` — the same row
        cannot carry `criteria_missing=0` and the state).

        The window is measured from the grade's own issuance: an unchanged grade
        (`fresh_issuance=False`) anchors on its current revision's `computed_at`, so
        a lapsed window settles it in place; a NEW revision — a recomputation or an
        amendment, a grade the teacher has not seen before — anchors on the moment
        this pass issues it and earns a fresh window (`fresh_issuance=True`). A
        correction arriving after the old window lapsed therefore re-opens review
        for the corrected content rather than minting it pre-settled."""
        if input_missing:
            return STATE_INCOMPLETE
        computed_raw = "" if fresh_issuance else (current or {}).get("computed_at") or ""
        issued = _parse_timestamp(computed_raw) or issued_at
        if run_complete:
            return STATE_FINAL
        if window_hours is not None and issued + timedelta(hours=window_hours) <= now:
            return STATE_FINAL
        return STATE_PROVISIONAL

    # -- the passes ---------------------------------------------------------------

    def compute_all(self, run_id: str) -> GradeReport:
        """Grade every submission in the run's cohort in one pass, with no per-student action
        anywhere (FR-GRADE-01, NFR-SYS-04). A review-queue row is added only where an input is
        missing (TC-GRADE-07).

        One pass = one batch: reads first, then a single write transaction, so a
        350-submission class is one transaction (`NFR-GRADE-03`'s sizing class).
        Settlement rides the same pass (`FR-GRADE-10`): grades still provisional when
        the run completed or their window lapsed are settled in place, never minted
        as new revisions."""
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        surface = self._policy_surface(
            self._store.package(run["package_id"]),
            run["package_id"],
            run["package_version_id"],
        )
        policy = surface["policy"]
        submissions = [
            row["submission_id"]
            for row in cohort.query(
                GRADE_STATEMENTS["select_run_submissions"], cohort_id=run["cohort_id"]
            )
        ]
        currents = {
            row["submission_id"]: dict(row)
            for row in cohort.query(
                GRADE_STATEMENTS["select_current_grades_for_run"], run_id=run_id
            )
        }
        now_raw = self._clock()
        now = _parse_timestamp(now_raw) or datetime.now(timezone.utc)
        run_complete = run["status"] == STATUS_COMPLETE
        window_hours = policy.review_window_hours

        inserts: list[dict[str, Any]] = []
        demotions: list[str] = []
        settlements: list[tuple[str, str]] = []
        queue_rows: list[tuple[str, str, str]] = []
        unqueue_rows: list[tuple[str, str]] = []
        computed = 0
        for submission_id in submissions:
            rows = cohort.query(
                GRADE_STATEMENTS["select_submission_scores"], run_id=run_id,
                submission_id=submission_id,
            )
            current = currents.get(submission_id)
            # A prior amendment lives only on the grade row (`CT-GRADE-14`), so the
            # recomputation replays the recorded overrides before comparing content —
            # an unchanged re-run of an amended submission reproduces the AMENDED
            # content and writes nothing, rather than minting a revert.
            overrides = _amendment_map(current["amendments"]) if current is not None else {}
            outcome = self._submission_computation(
                surface, _with_amendments(rows, overrides) if overrides else rows
            )
            computed += 1
            unchanged = (
                current is not None
                and self._content_of(outcome) == self._stored_content(current)
            )
            state = self._settlement_state(
                current,
                run_complete=run_complete,
                window_hours=window_hours,
                issued_at=now,
                now=now,
                fresh_issuance=not unchanged,
                input_missing=outcome["coverage"].criteria_missing > 0,
            )
            if outcome["coverage"].criteria_missing > 0:
                for cid in outcome["missing"]:
                    queue_rows.append((submission_id, cid, _RESCAN_DIRECTIVE))
            else:
                # No absence any more: any operator routing this submission earned in
                # an earlier pass is stale, and the pass retires it.
                unqueue_rows.append((submission_id,))
            if unchanged:
                if current["state"] == STATE_PROVISIONAL and state == STATE_FINAL:
                    settlements.append((submission_id, now_raw))
                continue
            revision = 1
            if current is not None:
                demotions.append(submission_id)
                revision = int(current["revision"]) + 1
            settled = state == STATE_FINAL
            inserts.append(
                {
                    "run_id": run_id,
                    "submission_id": submission_id,
                    "revision": revision,
                    "state": state,
                    "grade": outcome["grade"],
                    "total": outcome["total"],
                    "policy_version": surface["policy_version"],
                    "answer_key_ref": surface["answer_key_ref"],
                    "package_version_id": surface["package_version_id"],
                    "computed_at": now_raw,
                    "finalized_at": now_raw if settled else None,
                    "criteria_total": outcome["coverage"].criteria_total,
                    "criteria_auto": outcome["coverage"].criteria_auto,
                    "criteria_reviewed": outcome["coverage"].criteria_reviewed,
                    "criteria_provisional": outcome["coverage"].criteria_provisional,
                    "criteria_missing": outcome["coverage"].criteria_missing,
                    "boundary_at_risk": 1 if outcome["boundary"].at_risk else 0,
                    "score_low": outcome["boundary"].score_low,
                    "score_high": outcome["boundary"].score_high,
                    "missing_criteria": json.dumps(
                        list(outcome["missing"]), sort_keys=True
                    ),
                    # A recomputation carries the prior revision's amendment record
                    # forward: the overrides still govern this revision's content,
                    # so the audit trail — and the next pass's replay — must name
                    # them (a dropped record would make the next re-run a revert).
                    "amendments": (current["amendments"] or "[]")
                    if current is not None
                    else "[]",
                }
            )

        with cohort.transaction() as tx:
            for submission_id in demotions:
                tx.execute(
                    GRADE_STATEMENTS["demote_current"],
                    run_id=run_id,
                    submission_id=submission_id,
                    superseded_at=now_raw,
                )
            for row in inserts:
                tx.execute(GRADE_STATEMENTS["insert_grade"], **row)
            for submission_id, settled_at in settlements:
                tx.execute(
                    GRADE_STATEMENTS["settle_current"],
                    run_id=run_id,
                    submission_id=submission_id,
                    state=STATE_FINAL,
                    settled_at=settled_at,
                )
            for submission_id, criterion_id, reason in queue_rows:
                tx.execute(
                    GRADE_STATEMENTS["insert_review_row"],
                    queue_id=(
                        "q-" + _content_hash([run_id, submission_id, criterion_id])[:24]
                    ),
                    run_id=run_id,
                    submission_id=submission_id,
                    criterion_id=criterion_id,
                    reason=reason,
                )
            for (submission_id,) in unqueue_rows:
                tx.execute(
                    GRADE_STATEMENTS["delete_review_rows"],
                    submission_id=submission_id,
                    run_id=run_id,
                )

        return GradeReport(
            run_id=run_id,
            policy_version=surface["policy_version"],
            submitted=len(submissions),
            computed=computed,
            grades_by_state=self._grades_by_state(run, cohort),
        )

    def compute_one(self, run_id: str, submission_id: str) -> SubmissionGrade:
        """Grade one submission with the same computation as the batch pass (design §3.14). It
        exists for corrections and re-grades; the batch pass never goes through it (FR-GRADE-01).
        """
        run = self._run_row(run_id)
        cohort = self._store.cohort(run["cohort_id"])
        surface = self._policy_surface(
            self._store.package(run["package_id"]),
            run["package_id"],
            run["package_version_id"],
        )
        self._grade_one(cohort, surface, run, submission_id)
        row = cohort.query(
            GRADE_STATEMENTS["select_current_grade"], run_id=run_id,
            submission_id=submission_id,
        )
        if not row:
            raise GradeError(
                f"submission {submission_id!r} in run {run_id!r} has no grade row — "
                "the pass did not deliver one"
            )
        return self._as_submission_grade(run_id, submission_id, row[0])

    def _grade_one(self, cohort: Any, surface: dict[str, Any], run: Any,
                   submission_id: str) -> None:
        """The write half of grading one submission, shared by `compute_one` and `amend`: compute,
        compare, insert or settle, and queue missing inputs. Stored amendments are applied first,
        so an unchanged re-run of an amended submission writes nothing."""
        rows = cohort.query(
            GRADE_STATEMENTS["select_submission_scores"], run_id=run["run_id"],
            submission_id=submission_id,
        )
        current_row = cohort.query(
            GRADE_STATEMENTS["select_current_grade"], run_id=run["run_id"],
            submission_id=submission_id,
        )
        current = dict(current_row[0]) if current_row else None
        overrides = _amendment_map(current["amendments"]) if current is not None else {}
        outcome = self._submission_computation(
            surface, _with_amendments(rows, overrides) if overrides else rows
        )
        now_raw = self._clock()
        now = _parse_timestamp(now_raw) or datetime.now(timezone.utc)
        unchanged = (
            current is not None
            and self._content_of(outcome) == self._stored_content(current)
        )
        state = self._settlement_state(
            current,
            run_complete=run["status"] == STATUS_COMPLETE,
            window_hours=surface["policy"].review_window_hours,
            issued_at=now,
            now=now,
            fresh_issuance=not unchanged,
            input_missing=outcome["coverage"].criteria_missing > 0,
        )
        if unchanged:
            if current["state"] == STATE_PROVISIONAL and state == STATE_FINAL:
                with cohort.transaction() as tx:
                    tx.execute(
                        GRADE_STATEMENTS["settle_current"],
                        run_id=run["run_id"],
                        submission_id=submission_id,
                        state=STATE_FINAL,
                        settled_at=now_raw,
                    )
            return
        queue_writes: list[tuple[str, str, str]] = []
        if outcome["coverage"].criteria_missing > 0:
            for cid in outcome["missing"]:
                queue_writes.append(
                    (
                        "q-"
                        + _content_hash([run["run_id"], submission_id, cid])[:24],
                        submission_id,
                        cid,
                    )
                )
        revision = 1
        if current is not None:
            revision = int(current["revision"]) + 1
        settled = state == STATE_FINAL
        with cohort.transaction() as tx:
            if current is not None:
                tx.execute(
                    GRADE_STATEMENTS["demote_current"],
                    run_id=run["run_id"],
                    submission_id=submission_id,
                    superseded_at=now_raw,
                )
            tx.execute(
                GRADE_STATEMENTS["insert_grade"],
                run_id=run["run_id"],
                submission_id=submission_id,
                revision=revision,
                state=state,
                grade=outcome["grade"],
                total=outcome["total"],
                policy_version=surface["policy_version"],
                answer_key_ref=surface["answer_key_ref"],
                package_version_id=surface["package_version_id"],
                computed_at=now_raw,
                finalized_at=now_raw if settled else None,
                criteria_total=outcome["coverage"].criteria_total,
                criteria_auto=outcome["coverage"].criteria_auto,
                criteria_reviewed=outcome["coverage"].criteria_reviewed,
                criteria_provisional=outcome["coverage"].criteria_provisional,
                criteria_missing=outcome["coverage"].criteria_missing,
                boundary_at_risk=1 if outcome["boundary"].at_risk else 0,
                score_low=outcome["boundary"].score_low,
                score_high=outcome["boundary"].score_high,
                missing_criteria=json.dumps(list(outcome["missing"]), sort_keys=True),
                # The recomputation carries the prior revision's amendment record
                # forward (see the batch pass): the overrides still govern this
                # revision's content, so the next pass's replay must see them.
                amendments=(current["amendments"] or "[]")
                if current is not None
                else "[]",
            )
            if queue_writes:
                for queue_id, queued_submission, criterion_id in queue_writes:
                    tx.execute(
                        GRADE_STATEMENTS["insert_review_row"],
                        queue_id=queue_id,
                        run_id=run_id,
                        submission_id=queued_submission,
                        criterion_id=criterion_id,
                        reason=_RESCAN_DIRECTIVE,
                    )
            else:
                tx.execute(
                    GRADE_STATEMENTS["delete_review_rows"],
                    submission_id=submission_id,
                    run_id=run_id,
                )

    # -- helpers -------------------------------------------------------------------

    @staticmethod
    def _stored_content(current: Mapping[str, Any]) -> tuple:
        """The content fields read back from a stored grade row, for comparison with `_content_of`
        (NFR-GRADE-05)."""
        return (
            current["grade"],
            current["total"],
            (
                int(current["criteria_total"]),
                int(current["criteria_auto"]),
                int(current["criteria_reviewed"]),
                int(current["criteria_provisional"]),
                int(current["criteria_missing"]),
            ),
            bool(current["boundary_at_risk"]),
            current["score_low"],
            current["score_high"],
            json.dumps(
                sorted(json.loads(current["missing_criteria"] or "[]")),
                sort_keys=True,
            ),
        )

    @staticmethod
    def _as_submission_grade(run_id: str, submission_id: str, row: Any) -> SubmissionGrade:
        missing = tuple(json.loads(row["missing_criteria"] or "[]"))
        return SubmissionGrade(
            run_id=run_id,
            submission_id=submission_id,
            revision=int(row["revision"]),
            state=row["state"],
            grade=row["grade"],
            total=row["total"],
            policy_version=row["policy_version"],
            answer_key_ref=row["answer_key_ref"],
            computed_at=row["computed_at"],
            finalized_at=row["finalized_at"],
            coverage=Coverage(
                criteria_total=int(row["criteria_total"]),
                criteria_auto=int(row["criteria_auto"]),
                criteria_reviewed=int(row["criteria_reviewed"]),
                criteria_provisional=int(row["criteria_provisional"]),
                criteria_missing=int(row["criteria_missing"]),
            ),
            boundary=BoundaryRisk(
                at_risk=bool(row["boundary_at_risk"]),
                score_low=row["score_low"],
                score_high=row["score_high"],
            ),
            missing=missing,
        )


def open_grade(store: Store, *, clock: Callable[[], str] | None = None) -> GradingService:
    """Open the grading service over a store."""
    return GradingService(store, clock=clock)
