"""The clarified rubric's two gates, the second one run on the first class (FR-CALIB-18).

When the teacher's answers mint a clarified version R1 (`examples.answer_questions`), it is
recorded on the package as pending (Package migration 18) and **back-translation runs at
once** (`open_revision`). R1 does not grade anything yet.

The first class graded with the test afterwards is graded **and delivered under R0** as normal.
The console's start-run (the owner, FR-CONSOLE-90) asks this module to plan the R1 pass beside
that run (`plan_first_class`): the cost is disclosed and authorized before anything is spent
(CT-CALIB-12), and the claim is recorded on the package, so a second class started meanwhile
plans no second pass. When the class run has finished, `finish_first_class` scores the same
papers under R1 — copied, not read again, into a calibration cohort that no class reader opens
(CT-CALIB-18), because a second run in the class's own file would put R1's marks on the student
pages — joins the two passes into the dual-scored roster, and runs the non-inferiority gate
against the declared threshold (CT-CALIB-13: never defaulted).

The decision (`gate_decision`) gives R1 only when both gates passed. Then R1 is published and
becomes the version the next class is graded with; the first class keeps every grade it was
given — nothing in its file is touched. Every other outcome sets R1 aside with the reason the
teacher reads, and the next class runs R0. No path ships R1 with a warning (CT-CALIB-02).

A headless `aeh run` never comes here: M-PIPE does not import M-CALIB (CT-CALIB-01), so it
grades under the version it is given and leaves R1 pending.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from aeh.store import CALIBRATION_COHORT_PREFIX, Statement

from .constants import LOGGER
from .dual_scoring import DualScoringPlan, authorize, plan_dual_scoring, run_dual_scoring
from .errors import CalibrationError
from . import gates
from .gates import _noninferiority_threshold_from_env, back_translate, non_inferiority
from .rosters import CALIB_STATEMENTS, register_dual_scored_roster

#: The run-start outcome's sentence when an R1 pass is planned beside the run (FR-CONSOLE-90).
CHECKING_SENTENCE = ("Your clarified rubric is being checked on this class; this class is "
                     "graded with your original rubric.")

#: The run-start outcome's sentence when R1 is pending but no threshold is declared, so no pass
#: can decide it (CT-CALIB-13). Nothing is spent and R1 stays pending.
WAITING_SENTENCE = ("Your clarified rubric is waiting to be checked: your school has not yet "
                    "set how far marks may move under it. This class is graded with your "
                    "original rubric.")

#: The reasons the teacher reads when R1 is decided (FR-UI-23: no ids, no figures).
LIVE_REASON = ("Your clarified rubric passed both checks on your first class. Your next class "
               "is graded with it; the first class keeps the marks it was given.")
BACK_TRANSLATION_REASON = (
    "Your clarified rubric was set aside: an independent check found an answer that your "
    "original and your clarified rubric would mark differently, so the change could alter what "
    "the test measures. Your next class is graded with your original rubric.")
BACK_TRANSLATION_UNAVAILABLE_REASON = (
    "Your clarified rubric was set aside: the independent check of its wording could not be "
    "run. Your next class is graded with your original rubric.")
NON_INFERIORITY_REASON = (
    "Your clarified rubric was set aside: on your first class it moved more marks than your "
    "school allows. Your next class is graded with your original rubric.")
UNFINISHED_REASON = (
    "Your clarified rubric was set aside: the check on your first class could not finish. Your "
    "next class is graded with your original rubric.")

#: The class-cohort reads this module runs (SEC-15, FR-STORE-08).
FIRST_CLASS_STATEMENTS: dict[str, Statement] = {
    "select_class_roster": Statement(
        "SELECT student_ref, full_name FROM roster WHERE cohort_id = :cohort_id "
        "ORDER BY student_ref"
    ),
    "select_admitted_papers": Statement(
        "SELECT COUNT(*) AS n FROM submission WHERE cohort_id = :cohort_id AND quarantined = 0 "
        "AND ingest_status IN ('ok', 'low_confidence_ocr')"
    ),
    "select_run_status": Statement(
        "SELECT status FROM run WHERE run_id = :run_id"
    ),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


#: The clarified versions whose first-class check is being finished in this process, so a
#: re-armed check (see `plan_first_class`) never runs the R1 pass twice at once.
_FINISHING: set[str] = set()
_FINISHING_GUARD = threading.Lock()


def _declared_threshold(environ: Mapping[str, str] | None) -> float | None:
    """The declared non-inferiority threshold, in the gate's own order after an argument: a
    standing institutional declaration (consumed here, by the comparison it was declared for),
    then the deployment's environment channel. Never defaulted (CT-CALIB-13)."""
    if gates._INSTITUTIONAL_THRESHOLD is not None:
        value = float(gates._INSTITUTIONAL_THRESHOLD)
        gates._clear_institutional_threshold()
        return value
    return _noninferiority_threshold_from_env(environ)


def gate_decision(back_translation: str, non_inferiority_outcome: str) -> str:
    """The decision table over {back-translation} × {non-inferiority}: `live` only when both
    passed; every other cell — a failure, or a gate that did not run — is `set_aside`
    (CT-CALIB-02: no cell ships R1 with a warning)."""
    return "live" if (back_translation, non_inferiority_outcome) == ("pass", "pass") \
        else "set_aside"


def _catalog(store: Any, package_version_id: str) -> Any:
    from aeh.orch import default_package_id_for
    from aeh.pkg import PackageCatalog

    package_id = default_package_id_for(package_version_id)
    return PackageCatalog(store.package(package_id), package_id=package_id,
                          blobs=store.blobs())


def rubric_text(catalog: Any, package_version_id: str) -> str:
    """A version's rubric as the off-panel checker reads it: each criterion, then each band
    with its descriptor."""
    lines: list[str] = []
    for criterion in catalog.criteria(package_version_id):
        lines.append(f"Criterion {criterion['criterion_id']}:")
        for band in catalog.bands(str(criterion["criterion_id"])):
            lines.append(f"  {band.get('band')}: {band.get('descriptor') or ''}")
    return "\n".join(lines)


# --- at R1's creation: back-translation -----------------------------------------------------


@dataclass(frozen=True)
class RevisionOpened:
    """R1 recorded as pending, with back-translation's outcome and what the gate said."""

    r0: str
    r1: str
    back_translation: str
    notes: tuple[str, ...] = ()


def open_revision(store: Any, r0: str, r1: str, *, off_panel: Any = None) -> RevisionOpened:
    """Run back-translation on a freshly minted R1, and record R1 on the package as pending its
    first-class check (FR-CALIB-18). A gate that cannot run — no off-panel checker declared, one
    sharing a build with the panel, an unreadable answer — is a failure: it ends at R0 like any
    other (CT-CALIB-02)."""
    catalog = _catalog(store, r0)
    try:
        result = back_translate(rubric_text(catalog, r0), rubric_text(catalog, r1),
                                off_panel=off_panel)
        outcome = "pass" if result.outcome == "pass" else "fail"
        notes = tuple(result.notes)
    except Exception as error:  # noqa: BLE001 - every failure ends at R0 (CT-CALIB-02)
        outcome = "fail"
        notes = (f"unavailable: {type(error).__name__}: {error}",)
    catalog.open_calibration_revision(r1, base=r0, back_translation=outcome,
                                      note=" ".join(notes), created_at=_now())
    LOGGER.info("clarified version %s of %s: back-translation %s", r1, r0, outcome)
    return RevisionOpened(r0=r0, r1=r1, back_translation=outcome, notes=notes)


def pending_revision(store: Any, r0: str) -> dict | None:
    """The newest clarified version of `r0` still pending its first-class check, or None."""
    rows = [row for row in _catalog(store, r0).calibration_revisions(r0)
            if row["state"] == "pending"]
    return rows[-1] if rows else None


def revision_status(store: Any, r0: str) -> dict | None:
    """The newest clarified version of `r0` as the teacher reads it: its state (`pending`,
    `live`, `set_aside`) and, once decided, the reason. None when there is none."""
    catalog = _catalog(store, r0)
    rows = catalog.calibration_revisions(r0)
    if not rows:
        # Once R1 went live it is the version the teacher's screens name: its own record.
        own = catalog.calibration_revision(r0)
        if own is None or own["state"] != "live":
            return None
        rows = [own]
    row = rows[-1]
    return {"state": str(row["state"]), "reason": str(row["reason"] or ""),
            "checking_on_a_class": bool(row["first_class_run_id"])}


# --- on the first class: plan, then finish -----------------------------------------------------


@dataclass
class FirstClassPlan:
    """The R1 pass planned beside one class's run. ``planned`` is False when R1 is pending but
    no threshold is declared: nothing was claimed or authorized, and ``sentence`` says so.
    ``dual`` is the disclosed and authorized pass (None when back-translation already failed,
    so no pass is bought for a decision already made)."""

    r0: str
    r1: str
    cohort_id: str
    run_id: str
    back_translation: str
    planned: bool
    sentence: str
    threshold: float | None = None
    dual: DualScoringPlan | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


def plan_first_class(store: Any, *, cohort_id: str, r0: str, run_id: str,
                     environ: Mapping[str, str] | None = None) -> FirstClassPlan | None:
    """Plan and authorize the R1 pass beside the class run `run_id`, when `r0` has a clarified
    version pending (FR-CONSOLE-90). None when there is nothing to plan: no R1 pending, or
    another class's run already carries its pass."""
    revision = pending_revision(store, r0)
    if revision is None:
        return None
    r1 = str(revision["revision_version_id"])
    back_translation = str(revision["back_translation"])
    catalog = _catalog(store, r0)
    if revision["first_class_run_id"]:
        claimed = _rearm(store, catalog, revision, environ)
        if claimed is not None or revision_still_claimed(store, catalog, r1):
            return claimed
    threshold = _declared_threshold(environ)
    if back_translation == "pass" and threshold is None:
        return FirstClassPlan(r0=r0, r1=r1, cohort_id=cohort_id, run_id=run_id,
                              back_translation=back_translation, planned=False,
                              sentence=WAITING_SENTENCE,
                              notes=("no non-inferiority threshold is declared (CT-CALIB-13): "
                                     "no pass planned, R1 stays pending",))
    if not catalog.plan_calibration_revision(r1, cohort_id=cohort_id, run_id=run_id,
                                             planned_at=_now()):
        return None
    dual = None
    if back_translation == "pass":
        dual = _authorized_pass(store, catalog, cohort_id, r0, r1)
    LOGGER.info("R1 %s of %s: first-class pass planned beside run %s of %s", r1, r0, run_id,
                cohort_id)
    return FirstClassPlan(r0=r0, r1=r1, cohort_id=cohort_id, run_id=run_id,
                          back_translation=back_translation, planned=True,
                          sentence=CHECKING_SENTENCE, threshold=threshold, dual=dual)


def _run_status(store: Any, cohort_id: str, run_id: str) -> str | None:
    try:
        rows = store.cohort(cohort_id).query(FIRST_CLASS_STATEMENTS["select_run_status"],
                                             run_id=run_id)
    except Exception:  # noqa: BLE001 - an unreadable class is a run that is not there
        return None
    return str(rows[0]["status"]) if rows else None


def revision_still_claimed(store: Any, catalog: Any, r1: str) -> bool:
    """Whether R1's claim is still held (after `_rearm` may have released it)."""
    row = catalog.calibration_revision(r1)
    return bool(row and row["state"] == "pending" and row["first_class_run_id"])


def _rearm(store: Any, catalog: Any, revision: dict,
           environ: Mapping[str, str] | None) -> FirstClassPlan | None:
    """A claim whose check nobody is finishing — the console stopped between the class run's
    start and the decision. A claimed class run that completed gets its check back (a plan
    for THAT run, with no sentence for the class being started now); one that paused or
    failed, or is gone, releases the claim so this class can carry the pass. A run still
    going, or a check being finished in this process, is left alone."""
    r1 = str(revision["revision_version_id"])
    cohort_id = str(revision["first_class_cohort_id"] or "")
    run_id = str(revision["first_class_run_id"])
    with _FINISHING_GUARD:
        if r1 in _FINISHING:
            return None
    status = _run_status(store, cohort_id, run_id) if cohort_id else None
    if status in ("pending", "running"):
        return None
    if status != "complete":
        catalog.unplan_calibration_revision(r1, run_id=run_id)
        return None
    back_translation = str(revision["back_translation"])
    threshold = revision["threshold"]
    if threshold is None:
        threshold = _declared_threshold(environ)
    if back_translation == "pass" and threshold is None:
        return None
    dual = None
    if back_translation == "pass":
        dual = _authorized_pass(store, catalog, cohort_id, str(revision["base_version_id"]), r1)
    LOGGER.info("R1 %s: re-armed the first-class check on completed run %s", r1, run_id)
    return FirstClassPlan(r0=str(revision["base_version_id"]), r1=r1, cohort_id=cohort_id,
                          run_id=run_id, back_translation=back_translation, planned=True,
                          sentence="", threshold=threshold, dual=dual,
                          notes=("re-armed: the claimed class run completed with no decision "
                                 "recorded",))


def _authorized_pass(store: Any, catalog: Any, cohort_id: str, r0: str, r1: str) -> Any:
    """Disclose and authorize the R1 pass on the class's admitted papers × criteria."""
    papers = int(store.cohort(cohort_id).query(
        FIRST_CLASS_STATEMENTS["select_admitted_papers"], cohort_id=cohort_id)[0]["n"])
    criteria = len(catalog.criteria(r0))
    dual = plan_dual_scoring(cohort_id, r0, r1, None, class_size=max(papers, 1),
                             criteria_count=max(criteria, 1))
    authorize(dual)
    return dual


def shadow_cohort_id(r1: str, cohort_id: str) -> str:
    """The calibration cohort the R1 pass over one class runs in."""
    digest = hashlib.sha256(f"{r1}|{cohort_id}".encode("utf-8")).hexdigest()[:24]
    return f"{CALIBRATION_COHORT_PREFIX}{digest}"


class _StoredPass:
    """The R1 pass's bands as `run_dual_scoring` reads them: one per (paper, criterion) index,
    from the calibration run that scored them (the provider calls were that run's)."""

    def __init__(self, bands: tuple[tuple[str, ...], ...]) -> None:
        self._bands = bands

    def score(self, paper: int, criterion: int) -> str:
        return self._bands[paper][criterion]


@dataclass(frozen=True)
class FirstClassOutcome:
    """How the first class decided R1: the state it ended in, both gate outcomes, the reason
    the teacher reads, and what each step did (seam 4)."""

    r0: str
    r1: str
    state: str
    back_translation: str
    non_inferiority: str | None
    reason: str
    shadow_cohort_id: str | None = None
    shadow_run_id: str | None = None
    shifted_papers: int | None = None
    class_size: int | None = None
    notes: tuple[str, ...] = ()


def _score_under_r1(store: Any, plan: FirstClassPlan, config: Mapping[str, Any],
                    drive_keywords: Mapping[str, Any]) -> tuple[str, str, Any]:
    """Score the class's papers under R1 in the calibration cohort; returns (cohort, run id,
    the non-inferiority gate's result)."""
    from aeh.orch import RosterEntry, cohort_summary, create_cohort
    from aeh.pipeline import copy_read_papers, drive_run

    if plan.dual is None:
        raise CalibrationError("no dual-scoring pass was planned for this class")
    shadow = shadow_cohort_id(plan.r1, plan.cohort_id)
    if cohort_summary(store, shadow) is None:
        summary = cohort_summary(store, plan.cohort_id)
        if summary is None:
            raise CalibrationError(f"class {plan.cohort_id!r} is not stored")
        entries = [RosterEntry(full_name=str(row["full_name"] or row["student_ref"]),
                               student_ref=str(row["student_ref"]))
                   for row in store.cohort(plan.cohort_id).query(
                       FIRST_CLASS_STATEMENTS["select_class_roster"], cohort_id=plan.cohort_id)]
        create_cohort(store, shadow, summary.consent_class, entries, purpose="calibration")
        copy_read_papers(store, source_cohort_id=plan.cohort_id, target_cohort_id=shadow)
    result = drive_run(store, cohort_id=shadow, package_version_id=plan.r1,
                       config=dict(config), **dict(drive_keywords))
    if str(result.status) != "complete":
        raise CalibrationError(f"the R1 pass ended {result.status!r}, not complete")
    r1_bands = {
        (str(row["submission_id"]), str(row["criterion_id"])): str(row["band"])
        for row in store.cohort(shadow).query(
            CALIB_STATEMENTS["select_run_criterion_scores"], run_id=result.run_id)
    }
    r0_cells = {
        (str(row["submission_id"]), str(row["criterion_id"]))
        for row in store.cohort(plan.cohort_id).query(
            CALIB_STATEMENTS["select_run_criterion_scores"], run_id=plan.run_id)
    }
    papers = sorted({paper for paper, _criterion in r0_cells})
    criteria = sorted({criterion for _paper, criterion in r0_cells})
    missing = [cell for cell in r0_cells if cell not in r1_bands]
    if missing:
        raise CalibrationError(f"the R1 pass left {len(missing)} cell(s) the R0 run scored "
                               "unscored: the gate scores the full class or refuses")
    # The plan disclosed the class's shape at start (its admitted papers); the R0 run is what
    # was actually scored — a paper withheld but scored on a deterministic criterion, or one
    # added mid-run, moves it. The pass is then disclosed and authorized again on the shape
    # it actually covers, with the change named in its notes, before anything is joined.
    if (len(papers), len(criteria)) != (plan.dual.class_size, plan.dual.criteria_count):
        before = (plan.dual.class_size, plan.dual.criteria_count)
        plan.dual = plan_dual_scoring(plan.cohort_id, plan.r0, plan.r1, None,
                                      class_size=len(papers), criteria_count=len(criteria))
        plan.dual.notes = plan.dual.notes + (
            f"re-disclosed: planned on {before[0]} × {before[1]} at start, the class run "
            f"scored {len(papers)} × {len(criteria)}",)
        authorize(plan.dual)
    plan.dual.provider = _StoredPass(tuple(
        tuple(r1_bands[(paper, criterion)] for criterion in criteria) for paper in papers))
    run_dual_scoring(plan.dual)
    register_dual_scored_roster(plan.cohort_id, r0_version=plan.r0, r1_version=plan.r1,
                                store=store)
    gate = non_inferiority(plan.r0, plan.r1, plan.cohort_id, threshold=plan.threshold)
    return shadow, str(result.run_id), gate


def finish_first_class(store: Any, plan: FirstClassPlan, *, config: Mapping[str, Any],
                       approved_by: str | None = None,
                       **drive_keywords: Any) -> FirstClassOutcome | None:
    """After the class run `plan.run_id` has ended: run the R1 pass and non-inferiority, decide,
    and record the decision on the package (FR-CALIB-18). Publishes R1 on pass/pass, so the next
    class is graded with it; the first class's own file is never written. Returns None — R1
    left pending and the claim released for the next class — when the class run did not
    complete, since there is then no class to compare against."""
    with _FINISHING_GUARD:
        if plan.r1 in _FINISHING:
            return None
        _FINISHING.add(plan.r1)
    try:
        return _finish(store, plan, config=config, approved_by=approved_by,
                       drive_keywords=drive_keywords)
    finally:
        with _FINISHING_GUARD:
            _FINISHING.discard(plan.r1)


def _finish(store: Any, plan: FirstClassPlan, *, config: Mapping[str, Any],
            approved_by: str | None, drive_keywords: Mapping[str, Any]
            ) -> FirstClassOutcome | None:
    catalog = _catalog(store, plan.r0)
    rows = store.cohort(plan.cohort_id).query(FIRST_CLASS_STATEMENTS["select_run_status"],
                                              run_id=plan.run_id)
    if not rows or str(rows[0]["status"]) != "complete":
        catalog.unplan_calibration_revision(plan.r1, run_id=plan.run_id)
        LOGGER.info("R1 %s stays pending: class run %s did not complete", plan.r1, plan.run_id)
        return None

    shadow = shadow_run = None
    shifted = class_size = None
    notes: list[str] = []
    if plan.back_translation != "pass":
        ni = "not_run"
        revision = catalog.calibration_revision(plan.r1) or {}
        reason = (BACK_TRANSLATION_UNAVAILABLE_REASON
                  if str(revision.get("back_translation_note") or "").startswith("unavailable")
                  else BACK_TRANSLATION_REASON)
        notes.append("back-translation failed at R1's creation: no R1 pass bought")
    else:
        try:
            shadow, shadow_run, gate = _score_under_r1(store, plan, config, drive_keywords)
            ni = "pass" if gate.outcome == "pass" else "fail"
            shifted, class_size = gate.shifted_papers, gate.class_size
            notes.extend(gate.notes)
            reason = LIVE_REASON if ni == "pass" else NON_INFERIORITY_REASON
        except Exception as error:  # noqa: BLE001 - every failure ends at R0 (CT-CALIB-02)
            ni = "not_run"
            reason = UNFINISHED_REASON
            notes.append(f"the R1 pass did not finish: {type(error).__name__}: {error}")
            LOGGER.warning("R1 %s: first-class pass did not finish: %s", plan.r1, error)

    state = gate_decision(plan.back_translation, ni)
    approver = None
    if state == "live":
        approver = approved_by or catalog.published_by(plan.r0) or "teacher"
        try:
            catalog.publish(plan.r1, approver)
        except Exception as error:  # noqa: BLE001 - an unpublishable R1 is set aside
            state, reason, approver = "set_aside", UNFINISHED_REASON, None
            notes.append(f"publishing R1 was refused: {type(error).__name__}: {error}")
    catalog.settle_calibration_revision(
        plan.r1, state=state, non_inferiority=ni, reason=reason, decided_at=_now(),
        shifted_papers=shifted, class_size=class_size, threshold=plan.threshold,
        approved_by=approver)
    LOGGER.info("R1 %s of %s decided on class %s: %s (back-translation %s, "
                "non-inferiority %s)", plan.r1, plan.r0, plan.cohort_id, state,
                plan.back_translation, ni)
    return FirstClassOutcome(r0=plan.r0, r1=plan.r1, state=state,
                             back_translation=plan.back_translation, non_inferiority=ni,
                             reason=reason, shadow_cohort_id=shadow, shadow_run_id=shadow_run,
                             shifted_papers=shifted, class_size=class_size, notes=tuple(notes))


__all__ = [
    "BACK_TRANSLATION_REASON",
    "BACK_TRANSLATION_UNAVAILABLE_REASON",
    "CHECKING_SENTENCE",
    "FIRST_CLASS_STATEMENTS",
    "FirstClassOutcome",
    "FirstClassPlan",
    "LIVE_REASON",
    "NON_INFERIORITY_REASON",
    "RevisionOpened",
    "UNFINISHED_REASON",
    "WAITING_SENTENCE",
    "finish_first_class",
    "gate_decision",
    "open_revision",
    "pending_revision",
    "plan_first_class",
    "revision_status",
    "rubric_text",
    "shadow_cohort_id",
]
