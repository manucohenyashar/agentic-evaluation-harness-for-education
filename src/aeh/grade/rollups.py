"""Rollups: by rubric version, with deterministic results separated, and the findings."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable, Sequence

from aeh.pkg import PKG_STATEMENTS
from aeh.store import Store

from .constants import STATE_FINAL
from .refs import _content_hash, _now
from .band_figures import _band_population_is_deterministic, _shannon_entropy
from .schema import GRADE_STATEMENTS
from .records import (
    ClassRollup,
    CriterionBandFigure,
    GradeError,
    RollupBlock,
    RollupFinding,
    SeparatedRollup,
)
from .reporting import _build_rollup
from .service import GradingService


# --- the cohort rollup seam (CT-CALIB-09) -----------------------------------------------------------
#
# `class_rollup` answers by cohort id; the mixed-revision fixture helper registers the
# store it built so the rollup can find it. The registry is keyed by cohort id and
# holds the store's data directory — the same store the helper built, reopened for the
# read.


_MIXED_REVISION_COHORTS: dict[str, Any] = {}


def class_rollup(*, cohort_id: str, store: Store | None = None) -> ClassRollup:
    """A cohort-wide rollup, split by rubric version and labelled with the versions covered
    (CT-CALIB-09, FR-GRADE-15).

    R0-scored and R1-scored results never share one undifferentiated figure: the
    segments separate them, and the annotation names every instrument that
    contributed. The cohort's store is resolved from the registry
    `cohort_with_mixed_revisions` populated, or passed explicitly."""
    if store is None:
        store = _MIXED_REVISION_COHORTS.get(cohort_id)
        if store is None:
            raise GradeError(
                f"no store is registered for cohort {cohort_id!r} — pass store= "
                "explicitly, or build the cohort through cohort_with_mixed_revisions(), "
                "which registers it"
            )
    handle = store.cohort(cohort_id)
    rows = [dict(row) for row in handle.query(
        GRADE_STATEMENTS["select_cohort_current_grades"], cohort_id=cohort_id
    )]
    return _build_rollup(rows)


def cohort_with_mixed_revisions(store: Store | None = None) -> str:
    """Test seam: a cohort whose current grades come from two rubric revisions (`pkg-v1` and
    `pkg-v2`), two runs in one cohort ledger, for CT-CALIB-09. The store is registered under the
    returned cohort id so `class_rollup` finds it. It uses the service's own insert statement, so
    the rows are exactly what the service writes."""
    from aeh.store import open_store

    if store is None:
        store = open_store(Path(tempfile.mkdtemp(prefix="aeh-grade-mixed-")))
    cohort_id = f"c-mixed-{uuid.uuid4().hex[:10]}"
    handle = store.cohort(cohort_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES (:c, 'synthetic', :t)",
            c=cohort_id, t=_now(),
        )
        populations = (
            ("R-MIX-0", "pkg-v1", ("S-MIX-1", "S-MIX-2"), 71.0),
            ("R-MIX-1", "pkg-v2", ("S-MIX-3", "S-MIX-4"), 64.5),
        )
        for run_id, version, submissions, total in populations:
            for index, submission_id in enumerate(submissions):
                tx.execute(
                    "INSERT INTO submission (submission_id, cohort_id, student_ref) "
                    "VALUES (:s, :c, :r)",
                    s=submission_id, c=cohort_id, r=f"ref-{submission_id}",
                )
                tx.execute(
                    GRADE_STATEMENTS["insert_grade"],
                    run_id=run_id,
                    submission_id=submission_id,
                    revision=1,
                    state=STATE_FINAL,
                    grade="B",
                    total=total + index,
                    policy_version=_content_hash(["fixture", version]),
                    answer_key_ref=_content_hash(["fixture-key", version]),
                    package_version_id=version,
                    computed_at=_now(),
                    finalized_at=_now(),
                    criteria_total=2,
                    criteria_auto=2,
                    criteria_reviewed=0,
                    criteria_provisional=0,
                    criteria_missing=0,
                    boundary_at_risk=0,
                    score_low=None,
                    score_high=None,
                    missing_criteria="[]",
                    amendments="[]",
                )
    _MIXED_REVISION_COHORTS[cohort_id] = store
    return cohort_id


# --- the separated rollup, the findings, and the school-facing export (#104) ------------------------
#
# `FR-GRADE-14`/`15`/`16`/`17` — the per-criterion band figures, the rollup's
# deterministic/judged separation, the criteria the system could not apply, and the
# school-facing export. The accessors are module-level seams (the `class_rollup`
# precedent): the cases that pin them take a store handle, not a service, because the
# figures and findings are read-side surfaces a teacher's console consumes without a
# grading pass in the room.


def _judged_band_figure(
    criterion_id: str, bands: Sequence[str], band_order: Sequence[str]
) -> CriterionBandFigure:
    """One judged criterion's band figure, without guessing from band names: the caller already
    knows from the package that the criterion is judged, so this always computes real entropy and
    interior rate."""
    histogram = {band: bands.count(band) for band in sorted(set(bands))}
    order = [str(band) for band in band_order]
    interior = set(order[1:-1]) if len(order) >= 2 else set()
    return CriterionBandFigure(
        criterion_id=criterion_id,
        histogram=histogram,
        entropy=_shannon_entropy(list(histogram.values())),
        interior_rate=(
            sum(1 for band in bands if band in interior) / len(bands)
            if interior
            else None
        ),
    )


def separated_rollup(run_id: str, store: Store) -> SeparatedRollup:
    """The run's rollup with deterministic results in a separate block from judged ones, and no
    combined figure anywhere (FR-GRADE-15, CT-GRADE-12, TC-GRADE-15).

    The blocks are classified by the package's declared `evaluation_mode`
    (`FR-ORCH-35`) — #369 shipped the column, so the shape-based reading this module
    used to make (`kind='mcq'` IS deterministic) is retired: a criterion the package
    declares judged rolls into the judged block whatever its shape. The M-DET
    band vocabulary stays the fallback reading for a score row that no declared
    criterion owns. Each block carries its own submission population and
    its own per-criterion figures (`criterion_band_figures` produces the judged
    figures, the deterministic block carries histograms with the derived figures
    nulled by the block's own kind verdict)."""
    service = GradingService(store)
    cohort, run = service._find_run(run_id)
    version = run["package_version_id"]
    package = store.package(run["package_id"])
    # `FR-ORCH-35`: the block a criterion rolls into follows the mode the package
    # DECLARES, not the criterion's shape. The two used to be the same claim here
    # ("`kind='mcq'` IS `evaluation_mode='deterministic'`"); they are not, and a
    # judged multiple-choice criterion belongs in the judged block.
    declared_mode = {
        row["criterion_id"]: row["evaluation_mode"]
        for row in package.query(PKG_STATEMENTS["select_criteria"], v=version)
    }
    # The declared band order per criterion (ordinal order, the package's own
    # declaration) — the interior rate's input, never re-derived here.
    band_order_by_criterion: dict[str, list[str]] = {}
    for row in package.query(PKG_STATEMENTS["select_bands"], v=version):
        band_order_by_criterion.setdefault(row["criterion_id"], []).append(
            row["band"]
        )

    bands_by_criterion: dict[str, list[str]] = {}
    submissions_by_criterion: dict[str, set[str]] = {}
    for row in cohort.query(
        GRADE_STATEMENTS["select_run_criterion_bands"], run_id=run["run_id"],
        cohort_id=run["cohort_id"],
    ):
        criterion_id = row["criterion_id"]
        bands_by_criterion.setdefault(criterion_id, []).append(row["band"])
        submissions_by_criterion.setdefault(criterion_id, set()).add(
            row["submission_id"]
        )

    def _block(criterion_ids: Iterable[str], *, deterministic: bool) -> RollupBlock:
        population: set[str] = set()
        figures: list[CriterionBandFigure] = []
        for criterion_id in sorted(criterion_ids):
            bands = bands_by_criterion.get(criterion_id, [])
            if not bands:
                continue  # a criterion with no rows carries no figure to separate
            population |= submissions_by_criterion.get(criterion_id, set())
            histogram = {band: bands.count(band) for band in sorted(set(bands))}
            if deterministic:
                figures.append(
                    CriterionBandFigure(
                        criterion_id=criterion_id,
                        histogram=histogram,
                        entropy=None,
                        interior_rate=None,
                    )
                )
                continue
            # The judged block trusts the package's kind verdict — the band
            # vocabulary is the fallback reading for rows no declared criterion
            # owns, never a second guess over a criterion the package declared
            # judged (a judged pass/fail rubric may legitimately name its bands
            # correct/incorrect; its entropy is a real figure, and nulling it
            # here would contradict the null contract's own basis).
            figures.append(
                _judged_band_figure(
                    criterion_id,
                    bands,
                    band_order_by_criterion.get(criterion_id, ()),
                )
            )
        return RollupBlock(submission_count=len(population), criteria=tuple(figures))

    judged_ids: set[str] = set()
    deterministic_ids: set[str] = set()
    for criterion_id in bands_by_criterion:
        mode = declared_mode.get(criterion_id)
        if mode == "deterministic":
            deterministic_ids.add(criterion_id)
        elif mode is not None:
            judged_ids.add(criterion_id)
        elif _band_population_is_deterministic(bands_by_criterion[criterion_id]):
            deterministic_ids.add(criterion_id)
        else:
            judged_ids.add(criterion_id)
    return SeparatedRollup(
        judged=_block(judged_ids, deterministic=False),
        deterministic=_block(deterministic_ids, deterministic=True),
    )


#: The phrase the review budget's exhaustion rides on. `review_queue` has no status
#: column; M-REVIEW's residual names the exhaustion in the reason text, and the
#: match happens here, in Python — a SQL `LIKE` is `TC-STORE-15`/C08's banned search
#: shape, so the read takes the run's queue rows whole and filters on the phrase.
_BUDGET_EXHAUSTED_PHRASE = "budget exhausted"


_BREAKER_FINDING_REASON = (
    "ungradeable_by_panel: the escalation circuit breaker refused a panel for "
    "this criterion (FR-ORCH-13, CT-AGG-07)"
)


_BUDGET_FINDING_REASON = (
    "review budget exhausted: the review queue's residual names this criterion "
    "(FR-REVIEW-04)"
)


def rollup_findings(run_id: str, store: Store) -> tuple[RollupFinding, ...]:
    """The criteria the system could not apply, as findings (FR-GRADE-16, TC-GRADE-16): those the
    escalation breaker marked `ungradeable_by_panel`, and those whose review rows ran out of review
    budget. Each finding counts the affected students; a criterion with both problems is one
    finding counting the union. Sorted by criterion id."""
    service = GradingService(store)
    cohort, run = service._find_run(run_id)
    cohort_id = run["cohort_id"]

    breaker_students: dict[str, set[str]] = {}
    for row in cohort.query(
        GRADE_STATEMENTS["select_ungradeable_by_panel"], run_id=run["run_id"],
        cohort_id=cohort_id,
    ):
        breaker_students.setdefault(row["criterion_id"], set()).add(
            row["submission_id"]
        )

    budget_students: dict[str, set[str]] = {}
    for row in cohort.query(
        GRADE_STATEMENTS["select_run_review_queue"], cohort_id=cohort_id
    ):
        criterion_id = row["criterion_id"]
        if criterion_id is None:
            # A queue row that names no criterion cannot name a finding — the
            # finding's subject is a criterion, by the case's oracle.
            continue
        if _BUDGET_EXHAUSTED_PHRASE not in str(row["reason"] or ""):
            continue
        budget_students.setdefault(criterion_id, set()).add(row["submission_id"])

    findings = []
    for criterion_id in sorted(set(breaker_students) | set(budget_students)):
        students = breaker_students.get(criterion_id, set()) | budget_students.get(
            criterion_id, set()
        )
        reasons = [
            reason
            for flag, reason in (
                (criterion_id in breaker_students, _BREAKER_FINDING_REASON),
                (criterion_id in budget_students, _BUDGET_FINDING_REASON),
            )
            if flag
        ]
        findings.append(
            RollupFinding(
                criterion_id=criterion_id,
                student_count=len(students),
                reason="; ".join(reasons),
            )
        )
    return tuple(findings)
