"""`DeterministicEvaluator`: scores one criterion for one submission, or a whole cohort."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterable
from typing import Any

from aeh.pkg import PackageCatalog
from aeh.store import Store

from .constants import (
    BAND_CORRECT,
    BAND_INCORRECT,
    BAND_UNRESOLVED,
    DECIDED_BY_SYSTEM,
    EVALUATION_MODE_DETERMINISTIC,
    REASON_BLANK,
    STATE_UNRESOLVED_SELECTION,
    unresolved_alert_rate,
)
from .errors import (
    MalformedAnswerKey,
    NotDeterministicCriterion,
    UnknownCohort,
    UnknownCriterion,
    UnknownRun,
)
from .kernel import _decode_answer_key, DetOutcome, evaluate
from .schema import DET_STATEMENTS
from .records import CriterionScore, CriterionSummary, DeterministicReport, SelectionRead
from .ledger import _cohort_keys_on_filesystem, _declared_mode, _now
from .selection_reads import SelectionReadingMixin
from .rederive import KeyCorrectionMixin
from .item_stats import ItemStatisticsMixin


class DeterministicEvaluator(SelectionReadingMixin, KeyCorrectionMixin, ItemStatisticsMixin):
    """Scores deterministic criteria by comparing the student's selection with the answer key
    (design §3.11). No model, no panel, no interpretation, and nothing that costs the teacher
    review time (FR-DET-06)."""

    def __init__(
        self,
        store: Store,
        *,
        cohort_keys_for: Callable[[Any], tuple[str, ...]] | None = None,
    ) -> None:
        self._store = store
        self._cohort_keys_for = cohort_keys_for or _cohort_keys_on_filesystem

    # -- one criterion, one submission ----------------------------------------------------------

    def evaluate(
        self, run_id: str, submission_id: str, criterion_id: str
    ) -> CriterionScore:
        """Score one deterministic criterion for one submission by exact answer-key lookup
        (FR-DET-01), and write its score row (FR-DET-02).

        Safe to repeat: the write is an upsert, so re-running the same (submission, criterion)
        changes nothing, which at-least-once leasing needs. It writes no verdict row, no
        review-queue row and no panel work; the score row is all it touches."""
        run = self._run_row(run_id)
        cohort_handle = self._store.cohort(run["cohort_id"])
        package_handle = self._store.package(run["package_id"])
        catalog = self._catalog(run)
        criterion = self._criterion(
            package_handle, run["package_version_id"], criterion_id
        )
        outcome, points = self._score_one(
            cohort_handle, package_handle, run["package_version_id"], criterion,
            submission_id, catalog=catalog,
        )
        with cohort_handle.transaction() as tx:
            tx.execute(
                DET_STATEMENTS["upsert_det_criterion_score"],
                run_id=run_id,
                submission_id=submission_id,
                criterion_id=criterion_id,
                band=outcome.band,
                points=points,
                judge_count=0,
                agreement=None,
                state=outcome.state,
                routing=outcome.routing,
            )
        self._append_audit_records(
            run, run["package_version_id"], [(submission_id, criterion, outcome, points)]
        )
        return CriterionScore(
            run_id=run_id,
            submission_id=submission_id,
            criterion_id=criterion_id,
            question_id=criterion["question_id"],
            band=outcome.band,
            state=outcome.state,
            routing=outcome.routing,
            points=points,
            judge_count=0,
            agreement=None,
            credit=outcome.credit,
            reason=outcome.reason,
            selection_read=outcome.selection_read,
        )

    # -- the cohort pass -------------------------------------------------------------------------

    def evaluate_cohort(self, run_id: str) -> DeterministicReport:
        """Score every deterministic criterion for every submission of the run in one pass
        (NFR-DET-01), with no model calls: score rows in one Tier C transaction, item statistics in
        one Tier D transaction, and per-question summaries and scanning alerts in the returned
        report.

        An unresolved rate above `HARNESS_DET_UNRESOLVED_ALERT_RATE` raises a scanning alert (a
        rescan is needed); it is never read as item difficulty."""
        run = self._run_row(run_id)
        cohort_handle = self._store.cohort(run["cohort_id"])
        package_handle = self._store.package(run["package_id"])
        catalog = self._catalog(run)
        version = run["package_version_id"]
        criteria = [
            dict(row)
            for row in package_handle.query(DET_STATEMENTS["select_mcq_criteria"], v=version)
        ]
        for criterion in criteria:
            criterion["answer_key"] = _decode_answer_key(
                criterion["answer_key"], criterion["criterion_id"]
            )
            criterion["multi_select"] = bool(criterion["multi_select"])
        option_sets = {
            criterion["criterion_id"]: tuple(
                row["option_id"]
                for row in package_handle.query(
                    DET_STATEMENTS["select_options"],
                    v=version,
                    criterion_id=criterion["criterion_id"],
                )
            )
            for criterion in criteria
        }
        submissions = [
            row["submission_id"]
            for row in cohort_handle.query(
                DET_STATEMENTS["select_cohort_submissions"], cohort_id=run["cohort_id"]
            )
        ]
        alert_rate = unresolved_alert_rate()
        tallies: dict[str, dict[str, Any]] = {}
        scored: list[tuple[str, dict[str, Any], DetOutcome, float | None]] = []
        for submission_id in submissions:
            reads = self._selection_reads(cohort_handle, submission_id)
            for criterion in criteria:
                outcome, points = self._score_one(
                    cohort_handle, package_handle, version, criterion, submission_id,
                    option_set=option_sets[criterion["criterion_id"]] or None,
                    catalog=catalog,
                    read=reads.get(
                        criterion["question_id"], SelectionRead("absent", None, None)
                    ),
                )
                scored.append((submission_id, criterion, outcome, points))
                tally = tallies.setdefault(
                    criterion["criterion_id"],
                    {
                        "criterion_id": criterion["criterion_id"],
                        "question_id": criterion["question_id"],
                        "key": tuple(criterion["answer_key"]),
                        "n": 0,
                        "correct": 0,
                        "incorrect": 0,
                        "blank": 0,
                        "unresolved": 0,
                        "chosen": {},
                        "options": option_sets[criterion["criterion_id"]],
                    },
                )
                tally["n"] += 1
                if outcome.band == BAND_CORRECT:
                    tally["correct"] += 1
                elif outcome.band == BAND_INCORRECT:
                    tally["incorrect"] += 1
                if outcome.reason == REASON_BLANK:
                    tally["blank"] += 1
                if outcome.state == STATE_UNRESOLVED_SELECTION:
                    tally["unresolved"] += 1
                if outcome.selection_read:
                    for option_id in outcome.selection_read:
                        tally["chosen"][option_id] = (
                            tally["chosen"].get(option_id, 0) + 1
                        )
        with cohort_handle.transaction() as tx:
            for submission_id, criterion, outcome, points in scored:
                tx.execute(
                    DET_STATEMENTS["upsert_det_criterion_score"],
                    run_id=run_id,
                    submission_id=submission_id,
                    criterion_id=criterion["criterion_id"],
                    band=outcome.band,
                    points=points,
                    judge_count=0,
                    agreement=None,
                    state=outcome.state,
                    routing=outcome.routing,
                )
        self._write_item_statistics(tallies, version)
        audit_records_written = self._append_audit_records(
            run, version, scored
        )
        summaries: list[CriterionSummary] = []
        alerts: list[dict[str, Any]] = []
        for criterion in criteria:
            tally = tallies.get(criterion["criterion_id"])
            if tally is None:
                # A criterion over an empty cohort: nothing to summarize, and
                # an empty summary row would read as a 0.0 correct rate — say
                # nothing instead of summarizing nothing.
                continue
            n = tally["n"]
            summary = CriterionSummary(
                criterion_id=tally["criterion_id"],
                question_id=tally["question_id"],
                n=n,
                correct=tally["correct"],
                correct_rate=(tally["correct"] / n) if n else 0.0,
                blank_count=tally["blank"],
                unresolved_count=tally["unresolved"],
                unresolved_rate=(tally["unresolved"] / n) if n else 0.0,
                most_chosen_distractor=self._most_chosen_distractor(
                    tally["chosen"], tally["key"]
                ),
            )
            summaries.append(summary)
            if n and summary.unresolved_rate > alert_rate:
                alerts.append(
                    {
                        "criterion_id": summary.criterion_id,
                        "question_id": summary.question_id,
                        "n": n,
                        "unresolved_count": summary.unresolved_count,
                        "unresolved_rate": summary.unresolved_rate,
                        "threshold": alert_rate,
                        "kind": "scanning_problem",
                        "reads_as": "rescan_queue_never_item_difficulty",
                    }
                )
        return DeterministicReport(
            run_id=run_id,
            cohort_id=run["cohort_id"],
            package_version_id=version,
            submissions=len(submissions),
            criteria=len(criteria),
            evaluations=len(scored),
            correct=sum(t["correct"] for t in tallies.values()),
            incorrect=sum(t["incorrect"] for t in tallies.values()),
            blank=sum(t["blank"] for t in tallies.values()),
            unresolved=sum(t["unresolved"] for t in tallies.values()),
            unresolved_alert_rate=alert_rate,
            audit_records_written=audit_records_written,
            summaries=tuple(summaries),
            alerts=tuple(alerts),
        )

    # -- private helpers -------------------------------------------------------------------------

    def _run_row(self, run_id: str) -> Any:
        """The run's ledger row, found by walking the cohort files the same way the orchestrator
        does. A run lives in its cohort's Tier C file; there is no separate index of run ids
        (FR-ORCH-02)."""
        for key in self._cohort_keys_for(self._store):
            rows = self._store.cohort(key).query(
                DET_STATEMENTS["select_det_run"], run_id=run_id
            )
            if rows:
                return rows[0]
        raise UnknownRun(
            f"no run row named {run_id!r} exists in any cohort ledger; an "
            "explicit run_id that resolves to nothing is a caller error."
        )

    def _cohort_runs(self, cohort_id: str) -> list[Any]:
        """The cohort's run rows, which `rederive_for_key_change` and `item_stats` use to find
        package versions and ids. A cohort id with no ledger file on disk is refused before the
        tier handle is opened, because `store.cohort` would create the missing file."""
        if cohort_id not in self._cohort_keys_for(self._store):
            raise UnknownCohort(
                f"no cohort ledger named {cohort_id!r} exists on the store's "
                "cohort tier; an explicit cohort_id that resolves to nothing is "
                "a caller error."
            )
        cohort_handle = self._store.cohort(cohort_id)
        return list(
            cohort_handle.query(
                DET_STATEMENTS["select_cohort_runs"], cohort_id=cohort_id
            )
        )

    def _append_audit_records(
        self,
        run: Any,
        version: str,
        entries: Iterable[tuple[str, dict[str, Any], DetOutcome, float | None]],
    ) -> int:
        """Append one audit record per scored (submission, criterion) that carries points, in one
        Tier D transaction (FR-DET-10, CT-DET-09). Returns how many were written.

        Each record has `evaluation_mode='deterministic'`, NULL `panel_config` and
        `prompt_template_v` (so no statistic mistakes it for panel scoring), and a non-null
        `answer_key_ref` and `selection_read`. Unresolved rows are skipped: they have no grade and
        no points, and their audit is the score row's state and routing. The trail is append-only;
        it records grading events."""
        written = 0
        durable_handle = self._store.durable()
        with durable_handle.transaction() as tx:
            for submission_id, criterion, outcome, points in entries:
                if outcome.band == BAND_UNRESOLVED:
                    continue
                tx.execute(
                    DET_STATEMENTS["insert_det_audit_record"],
                    audit_record_id=uuid.uuid4().hex,
                    run_id=run["run_id"],
                    recorded_at=_now(),
                    profile_summary=json.dumps(
                        {
                            "band": outcome.band,
                            "reason": outcome.reason,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    submission_id=submission_id,
                    criterion_id=criterion["criterion_id"],
                    final_points=points,
                    decided_by=DECIDED_BY_SYSTEM,
                    package_version_id=version,
                    evaluation_mode=EVALUATION_MODE_DETERMINISTIC,
                    panel_config=None,
                    prompt_template_v=None,
                    answer_key_ref=(
                        f"{version}:"
                        f"{json.dumps(list(criterion['answer_key']))}"
                    ),
                    selection_read=json.dumps(list(outcome.selection_read or ())),
                )
                written += 1
        return written

    def _criterion(
        self, package_handle: Any, version: str, criterion_id: str
    ) -> dict[str, Any]:
        """The criterion row for exactly the package version the run names, never the file's latest
        version, so a key correction (which creates a new version) cannot silently change a run
        already in progress."""
        rows = package_handle.query(
            DET_STATEMENTS["select_criterion"], v=version, criterion_id=criterion_id
        )
        if not rows:
            raise UnknownCriterion(
                f"no criterion {criterion_id!r} in package version {version!r}."
            )
        criterion = dict(rows[0])
        criterion["answer_key"] = _decode_answer_key(
            criterion["answer_key"], criterion_id
        )
        criterion["multi_select"] = bool(criterion["multi_select"])
        return criterion

    def _score_one(
        self,
        cohort_handle: Any,
        package_handle: Any,
        version: str,
        criterion: dict[str, Any],
        submission_id: str,
        option_set: tuple[str, ...] | None = None,
        *,
        catalog: PackageCatalog,
        read: SelectionRead | None = None,
    ) -> tuple[DetOutcome, float | None]:
        """Read the answer, run the scoring rule and work out the points. Returns the outcome and
        the points to store (None for an unresolved row).

        `option_set`, `catalog` and `read` can be passed in, so the cohort pass reads each
        criterion's options once, holds one pinned catalog, and reads each submission's regions
        once (NFR-DET-01)."""
        if _declared_mode(criterion) != "deterministic":
            # FR-ORCH-08: a criterion the package does not declare deterministic
            # reaching the deterministic evaluator is an admission failure upstream,
            # never a score. FR-ORCH-35: the test is the DECLARED mode, not `kind` —
            # the same predicate the deterministic population is selected by, so the
            # selector and the guard cannot disagree about who belongs here.
            raise NotDeterministicCriterion(
                f"criterion {criterion['criterion_id']!r} is declared "
                f"{_declared_mode(criterion)!r}; only criteria the package declares "
                "deterministic score by lookup."
            )
        key = tuple(criterion["answer_key"])
        if not key:
            raise MalformedAnswerKey(
                f"criterion {criterion['criterion_id']!r} carries no answer key; "
                "FR-SETUP-03 makes this a publication-time failure that a "
                "published package cannot produce."
            )
        if read is None:
            read = self._selection_read(
                cohort_handle, submission_id, criterion["question_id"]
            )
        if option_set is None:
            option_rows = package_handle.query(
                DET_STATEMENTS["select_options"],
                v=version,
                criterion_id=criterion["criterion_id"],
            )
            option_set = tuple(row["option_id"] for row in option_rows) or None
        outcome = evaluate(
            content_state=read.content_state,
            selection_state=read.selection_state,
            selection=read.selection,
            key=key,
            multi_select=bool(criterion["multi_select"]),
            partial_credit=criterion["partial_credit"],
            option_set=option_set,
        )
        return outcome, self._points(catalog, criterion["criterion_id"], outcome)

    def _catalog(self, run: Any) -> PackageCatalog:
        """M-PKG's catalog for the run's package file, pinned to the version the run names. Points
        come from its `points_for_band`, the one place bands map to points (TC-PKG-C05), so M-DET
        keeps no second mapping that could drift."""
        catalog = PackageCatalog(
            self._store.package(run["package_id"]),
            package_id=run["package_id"],
        )
        catalog.criteria(run["package_version_id"])  # pins the cache
        return catalog

    def _points(
        self,
        catalog: PackageCatalog,
        criterion_id: str,
        outcome: DetOutcome,
    ) -> float | None:
        """The points for a score row. An unresolved row was never scored, so its points are None,
        not zero (CT-DET-03). A scored row uses the criterion's declared band points through
        M-PKG's `points_for_band` (TC-PKG-C05); a `per_option` fraction scales the correct band's
        points (see docs/code-notes/det.md). A criterion missing a declared band raises M-PKG's own
        `PackageError`, because the two-band declaration is M-PKG's rule (FR-SETUP-13)."""
        if outcome.band == BAND_UNRESOLVED:
            return None
        if outcome.credit in (0.0, 1.0):
            return catalog.points_for_band(criterion_id, outcome.band)
        return outcome.credit * catalog.points_for_band(criterion_id, BAND_CORRECT)
