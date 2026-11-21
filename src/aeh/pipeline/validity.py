"""The administration's promotion and the run trace's `validity` stage (FR-PIPE-20/21, ADR-57).

`promote_administration` is the one production caller of `ValidationStats.promote`. It runs when
a run's blind draw CLOSES — the console calls it after Finish and after Skip (once M-REVIEW has
returned), and `recover` calls it for a draw the review window closed — and never from batch
finalization or "Approve all grades": finalization runs on completion, before any teacher marks,
and FR-STATS-33's idempotency would then discard the marks made later.

The draw state is checked here rather than trusted to the caller, so "never while the draw is
open" (CT-PIPE-16) is structural: a call on an open or undrawn draw promotes nothing. A call
after the administration is recorded promotes nothing either, so each administration's promote
runs exactly once however many closes report in.

M-REVIEW never calls M-STATS (M-STATS already depends on M-REVIEW); this module, the composition
root above both, reads one and drives the other. No SQL here (CT-PIPE-05).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .results import StageTrace

#: The trace stage's name (FR-PIPE-20).
VALIDITY_STAGE = "validity"

#: What closed the draw, as `promote_administration` is told: the teacher's Finish or Skip, the
#: review window's lapse, or `recover` finding a closed draw with no record.
PROMOTION_TRIGGERS: tuple[str, ...] = ("finish", "skip", "window_lapse", "recover")

#: The draw states in which an administration is promoted (FR-REVIEW-30).
_CLOSED_DRAW_STATES = frozenset({"finished", "skipped", "closed_by_window"})

#: The validity stage's states (FR-PIPE-20, FR-CONSOLE-80's vocabulary).
VALIDITY_NOT_OFFERED_YET = "not_offered_yet"
VALIDITY_IN_PROGRESS = "in_progress"
VALIDITY_SKIPPED = "skipped"
VALIDITY_RECORDED = "recorded"


@dataclass(frozen=True)
class AdministrationPromotion:
    """What `promote_administration` did. `promoted` is True only when this call ran `promote`;
    `reason` says why it did not otherwise; `update` is the administration's record (the one this
    call wrote, or the one already stored), and `stage` the run's `validity` trace after it."""

    run_id: str
    trigger: str
    draw_state: str
    promoted: bool
    reason: str
    update: Any
    stage: StageTrace


def _run_handle(store: Any, run_id: str) -> Any:
    from aeh.orch import Orchestrator

    return Orchestrator(store).run_handle(run_id)


def _review_for(store: Any, handle: Any, clock: Any = None) -> Any:
    """M-REVIEW's service over the run, with the run's package catalog so a lapse that writes
    the drafted seats as labels maps their bands on the package's scale (the console's shape)."""
    from aeh.pkg import PackageCatalog
    from aeh.review import review_service_over

    catalog = None
    try:
        catalog = PackageCatalog(store.package(handle.package_id), package_id=handle.package_id)
        catalog.criteria(handle.package_version_id)
    except Exception:  # noqa: BLE001 — an unreadable package keeps the default scale
        catalog = None
    return review_service_over(store, cohort_ids=[handle.cohort_id], run_id=handle.run_id,
                               catalog=catalog, actor="teacher", clock=clock)


def _stored_record(store: Any, handle: Any) -> Any:
    from aeh.stats import administration_record

    return administration_record(store, package_version_id=handle.package_version_id,
                                 cohort_id=handle.cohort_id)


def promote_administration(store: Any, run_id: str, trigger: str, *,
                           clock: Any = None) -> AdministrationPromotion:
    """Promote the run's administration when its draw has closed (FR-PIPE-21, CT-PIPE-16).

    Calls `ValidationStats.promote(cohort_id, package_version=…)` for the run's cohort and frozen
    package version, with the draw's absence reason and unmarked count (FR-STATS-33), exactly
    once per administration: an open or undrawn draw, or an administration already recorded,
    promotes nothing and says why. Raises `ValueError` for a trigger outside
    `PROMOTION_TRIGGERS`; an unknown run raises M-ORCH's `RunNotFoundError`. `clock` is the
    review window's clock (ISO-8601 instants, M-REVIEW's seam), so a recovery under an injected
    clock settles a lapse on the same clock it settles grades on."""
    if trigger not in PROMOTION_TRIGGERS:
        raise ValueError(
            f"promote_administration got trigger={trigger!r}; an administration is promoted "
            f"when its draw closes, by one of {list(PROMOTION_TRIGGERS)}"
        )
    handle = _run_handle(store, run_id)
    from aeh.store import is_calibration_cohort

    if is_calibration_cohort(handle.cohort_id):
        # FR-CALIB-17 / CT-CALIB-18 (#886): a test's marked examples are never an
        # administration — they produce no labels and no agreement (D5) — so nothing is read
        # and nothing is promoted, whatever the trigger.
        return AdministrationPromotion(
            run_id=run_id, trigger=trigger, draw_state="not_offered_yet", promoted=False,
            reason="the run grades a test's marked examples, which are never promoted",
            update=None, stage=StageTrace("validity", detail=(
                "calibration cohort: the marked examples are never promoted (CT-CALIB-18)",)))
    review = _review_for(store, handle, clock)
    draw = review.draw_record(run_id)
    existing = _stored_record(store, handle)

    def _result(promoted: bool, reason: str, update: Any) -> AdministrationPromotion:
        return AdministrationPromotion(
            run_id=run_id, trigger=trigger, draw_state=draw.state, promoted=promoted,
            reason=reason, update=update,
            stage=validity_stage(store, run_id, handle=handle, review=review))

    if draw.state not in _CLOSED_DRAW_STATES:
        return _result(False, f"the blind sample is {draw.state}: an administration is "
                              "promoted only when its draw closes", existing)
    if existing is not None:
        return _result(False, "this administration is already recorded", existing)

    from aeh.stats import open_stats

    stats = open_stats(store.data_dir, cohort_id=handle.cohort_id)
    update = stats.promote(
        handle.cohort_id, package_version=handle.package_version_id, run_id=run_id,
        absence_reason=draw.absence_reason, unmarked_count=int(draw.unmarked_count or 0))
    return _result(True, f"promoted on {trigger}", update)


def _absent_figures(update: Any) -> list[dict[str, str]]:
    """Each absent figure of a record with its reason (FR-PIPE-20): the administration's own
    absence (`skipped`, `none_marked`), then per criterion an absent kappa (`too_few_labels`,
    `insufficient_data`) and each engine figure below its minimum (`insufficient_data`)."""
    absent: list[dict[str, str]] = []
    if update.absence_reason:
        absent.append({"figure": "agreement", "criterion_id": "",
                       "reason": str(update.absence_reason)})
    for criterion, figure in sorted(dict(update.criterion_figures).items()):
        if figure.get("reason"):
            absent.append({"figure": "kappa", "criterion_id": criterion,
                           "reason": str(figure["reason"])})
        for engine, measured in sorted(dict(figure.get("per_engine") or {}).items()):
            if measured.get("status") == "insufficient_data":
                absent.append({"figure": f"agreement:{engine}", "criterion_id": criterion,
                               "reason": "insufficient_data"})
        if any(item.get("status") == "insufficient_data"
               for item in figure.get("gate_bins") or ()):
            absent.append({"figure": "gate_calibration", "criterion_id": criterion,
                           "reason": "insufficient_data"})
        if figure.get("noninferiority") == "insufficient_data":
            absent.append({"figure": "noninferiority", "criterion_id": criterion,
                           "reason": "insufficient_data"})
    return absent


def validity_stage(store: Any, run_id: str, *, handle: Any = None,
                   review: Any = None, clock: Any = None) -> StageTrace:
    """The run's `validity` trace stage (FR-PIPE-20, CT-PIPE-15): the draw state and, once the
    administration is recorded, the labels claimed, the figures per criterion and each absent
    figure's reason. Before the draw is offered it reads `not_offered_yet`; while the draw is
    open, or closed but not yet promoted, `in_progress`; after a skip `skipped`; once promoted
    `recorded`. It never promotes: reading the trace is not a draw close."""
    handle = handle if handle is not None else _run_handle(store, run_id)
    review = review if review is not None else _review_for(store, handle, clock)
    draw = review.draw_record(run_id)
    record = (_stored_record(store, handle) if draw.state in _CLOSED_DRAW_STATES else None)
    metrics: dict[str, Any] = {"draw_state": draw.state}
    if draw.state == "not_drawn":
        metrics["state"] = VALIDITY_NOT_OFFERED_YET
        return StageTrace(VALIDITY_STAGE, detail=(
            "validity: the blind sample has not been offered yet, so there is no agreement "
            "evidence for this run",), metrics=metrics)
    if record is None:
        metrics["state"] = VALIDITY_IN_PROGRESS
        detail = ("validity: the blind sample is open; the administration is recorded when it "
                  "is finished, skipped or closed by the review window"
                  if draw.state == "open" else
                  f"validity: the blind sample is {draw.state} and the administration is not "
                  "recorded yet")
        return StageTrace(VALIDITY_STAGE, detail=(detail,), metrics=metrics)
    from aeh.stats.administration import STORED_JSON_KEYS

    # Each criterion's headline figures as M-STATS recorded them, copied through wholesale
    # minus the engine measurements and confusion counts (those ride `absent` or stay in the
    # record): M-PIPE names no figure field, so it cannot branch on one (CT-AGG-09).
    omitted = set(STORED_JSON_KEYS) | {"criterion_id", "reason"}
    figures = {
        criterion: {key: value for key, value in figure.items() if key not in omitted}
        for criterion, figure in sorted(dict(record.criterion_figures).items())
    }
    absent = _absent_figures(record)
    skipped = record.absence_reason == "skipped"
    metrics.update({
        "state": VALIDITY_SKIPPED if skipped else VALIDITY_RECORDED,
        "labels_claimed": int(record.blind_count),
        "unmarked_count": int(record.unmarked_count),
        "absence_reason": record.absence_reason,
        "figures": figures,
        "absent": absent,
    })
    detail = [
        f"validity: {record.blind_count} blind label(s) claimed, figures for "
        f"{len(figures)} criterion(s), {record.unmarked_count} seat(s) unmarked",
    ]
    detail.extend(
        f"validity: {item['figure']}{' for ' + item['criterion_id'] if item['criterion_id'] else ''}"
        f" absent: {item['reason']}"
        for item in absent
    )
    return StageTrace(VALIDITY_STAGE, units=int(record.blind_count), done=len(figures),
                      detail=tuple(detail), metrics=metrics)
