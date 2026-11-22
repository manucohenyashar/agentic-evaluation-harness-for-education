"""The agreement shown (FR-CONSOLE-80, FR-CONSOLE-84, CT-CONSOLE-55, #881).

`GET /api/v1/results/validity?run_id=…` answers how closely the marking matched the teacher's
own blind marks for one run: the administration's state, each judged criterion's stored
figure with its n and whether it is `too_few` to rely on, the differences by student name, and
the test's earlier record under a separate `prior_record` key — never in the current position
(FR-CONSOLE-24), and atomic and holistic never merged (FR-CONSOLE-10): every figure is one
criterion's, carrying its scoring model.

`GET /api/v1/packages/record?package_version_id=…` answers a test version's cumulative record
(FR-STATS-35) in teacher labels: the version's name (FR-CONSOLE-74) and class names.

Both read figures M-STATS stored when an administration was promoted (NFR-STATS-07); neither
computes a statistic. The validity read settles the draw first (`settle_draw`, which promotes a
draw the review window closed), and never opens one.
"""

from __future__ import annotations

from typing import Any

from .blind_actions import settle_draw
from .screen_reads import (
    _bound_run_id,
    _declared_scales,
    _grading_point_labels,
    _roster_names,
)
from .version_labels import read_version_label, teacher_date

#: The direction of a difference, from the points of the two levels (FR-CONSOLE-80).
MORE_CREDIT = "more_credit"
LESS_CREDIT = "less_credit"

NO_RUN_DETAIL = "The agreement read names no test run. Choose a test run first."
UNKNOWN_RUN_DETAIL = "That test run is not in this console's records."
NO_VERSION_DETAIL = "The record read names no test version. Choose the test again."


def _labelled(views: list[dict[str, Any]], labels: dict[str, str]) -> list[dict[str, Any]]:
    """M-STATS' figure views, each with its grading point's teacher label beside the id."""
    return [{**view, "label": labels.get(str(view["criterion_id"]), str(view["criterion_id"]))}
            for view in views]


def _prior_record(app: Any, run_row: Any, labels: dict[str, str]) -> dict[str, Any] | None:
    """The test version's record before this class's administration, labelled with its classes,
    population and backend; None when no earlier class took this version."""
    from aeh.stats import package_record, record_figure_views

    record = package_record(app._store, str(run_row["package_version_id"]),
                            before_cohort_id=str(run_row["cohort_id"]))
    if not record.administrations:
        return None
    classes = [item.cohort_id for item in record.administrations]
    backends = sorted({item.backend_profile for item in record.administrations
                       if item.backend_profile})
    count = len(classes)
    return {
        "label": "Earlier classes that took this test",
        "classes": classes,
        "population": (f"{count} earlier {'class' if count == 1 else 'classes'}: "
                       + ", ".join(classes)),
        "backend": ", ".join(backends) or None,
        "blind_labels": record.blind_labels,
        "min_n_for_headline": record.min_n_for_headline,
        "criteria": _labelled(record_figure_views(record), labels),
    }


def _compared(app: Any, run_row: Any, labels: dict[str, str]) -> list[dict[str, Any]]:
    """Every blind mark paired with the system's level (FR-UI-41's comparison), matched or
    not, by the student's name; `direction` is None where the levels agree. A mark the system
    has no level for is not paired, so it is absent here rather than shown as agreeing."""
    from aeh.stats import administration_pairs

    cohort_id, run_id = str(run_row["cohort_id"]), str(run_row["run_id"])
    pairs = administration_pairs(app._store, cohort_id=cohort_id, run_id=run_id)
    scales = _declared_scales(app, run_row)
    try:
        names = _roster_names(app._store.cohort(cohort_id))
    except Exception:  # noqa: BLE001 — a difference names the student's ref alone
        names = {}
    entries = []
    for pair in pairs:
        points = dict(scales.get(pair.criterion_id, ()))
        system, teacher = points.get(pair.system_band), points.get(pair.teacher_band)
        direction = None
        if system is not None and teacher is not None and system != teacher:
            direction = LESS_CREDIT if float(system) < float(teacher) else MORE_CREDIT
        entries.append({
            "student": names.get(pair.student_ref) or pair.student_ref,
            "student_ref": pair.student_ref,
            "criterion_id": pair.criterion_id,
            "question": labels.get(pair.criterion_id, pair.criterion_id),
            "teacher_band": pair.teacher_band,
            "system_band": pair.system_band,
            "direction": direction,
        })
    entries.sort(key=lambda item: (str(item["question"]), str(item["student"]).casefold()))
    return entries


def validity_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """`GET /api/v1/results/validity` (FR-CONSOLE-80): `state` ∈ {not_offered_yet,
    in_progress, skipped, recorded}; on `recorded`, each judged criterion's stored figure and
    the differences; and the earlier record under `prior_record`, never in the current
    position. Before the draw closes there are no criteria and no differences."""
    from aeh.pipeline import validity_stage
    from aeh.stats import (
        STATS_MIN_N_FOR_HEADLINE,
        administration_figure_views,
        administration_record,
    )

    run_id = str(query.get("run_id") or "") or _bound_run_id(console)
    if not run_id:
        raise ValueError(NO_RUN_DETAIL)
    run_row = app._run_row(run_id)
    if run_row is None:
        raise ValueError(UNKNOWN_RUN_DETAIL)
    try:
        settle_draw(app, run_id)
    except Exception:  # noqa: BLE001 — the state below still reads what is recorded
        pass
    stage = validity_stage(app._store, run_id)
    state = str(stage.metrics.get("state") or "")
    minimum = int(STATS_MIN_N_FOR_HEADLINE)
    labels = _grading_point_labels(app, run_row)
    payload: dict[str, Any] = {
        "run_id": run_id,
        "state": state,
        "min_n_for_headline": minimum,
        "criteria": [],
        "disagreements": [],
        "compared": [],
        "prior_record": _prior_record(app, run_row, labels),
    }
    if state != "recorded":
        return payload
    record = administration_record(app._store,
                                   package_version_id=str(run_row["package_version_id"]),
                                   cohort_id=str(run_row["cohort_id"]))
    payload["criteria"] = _labelled(
        administration_figure_views(record, minimum=minimum) if record is not None else [],
        labels)
    compared = _compared(app, run_row, labels)
    payload["compared"] = compared
    payload["disagreements"] = [entry for entry in compared
                                if entry["system_band"] != entry["teacher_band"]]
    return payload


def package_record_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """`GET /api/v1/packages/record` (FR-CONSOLE-84): the version's record (FR-STATS-35) with
    its teacher label and class names. An unknown version is refused in teacher words."""
    del console
    from aeh.stats import package_record, record_figure_views

    version_id = str(query.get("package_version_id") or "").strip()
    if not version_id:
        raise ValueError(NO_VERSION_DETAIL)
    version = read_version_label(app._store, version_id)
    record = package_record(app._store, version_id)
    labels = _grading_point_labels(
        app, {"package_id": version.package_id, "package_version_id": version_id})
    administrations = []
    for item in record.administrations:
        entry: dict[str, Any] = {
            "date": teacher_date(item.recorded_at),
            "class_name": item.cohort_id,
            "backend": item.backend_profile,
            "panel_build_ref": item.panel_build_ref,
        }
        if item.absence_reason:
            entry["absence_reason"] = item.absence_reason
        else:
            entry["blind_count"] = item.blind_count
        if item.unmarked_count:
            entry["unmarked_count"] = item.unmarked_count
        administrations.append(entry)
    return {
        "package_version_id": version_id,
        "version_label": version.text(),
        "blind_labels": record.blind_labels,
        "min_n_for_headline": record.min_n_for_headline,
        "too_few": record.blind_labels < record.min_n_for_headline,
        "criteria": _labelled(record_figure_views(record), labels),
        "administrations": administrations,
    }


__all__ = ["LESS_CREDIT", "MORE_CREDIT", "package_record_read", "validity_read"]
