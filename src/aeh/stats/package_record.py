"""The package record, and one administration's label pairs (FR-STATS-35, FR-CONSOLE-80, #881).

`package_record(store, package_version_id)` is a test version's cumulative record across the
classes that took it: the blind labels collected, per-criterion agreement once n reaches
`STATS_MIN_N_FOR_HEADLINE` (else `too_few` with n), and each administration's date, class,
backend, panel build and `blind_count` or `absence_reason`. A new package version has its own
record: every read here is keyed on the version.

Reads stored figures only (NFR-STATS-07): the pooled figure per criterion is the one `promote`
stored as `cumulative` when the latest contributing administration was recorded
(`administration.cumulative_figures`), so no read recomputes a coefficient or re-reads labels.

`administration_pairs` is the validity read's disagreement source: the administration's
admissible blind labels (the module's one filter, NFR-STATS-04) that carry both bands. Listing
them is not a figure; it computes nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import settings as _settings
from .admissibility import _is_admissible, _row_mapping, _StoredLabel, _system_side
from .administration import INSUFFICIENT_DATA
from .schema import STATS_STATEMENTS


@dataclass(frozen=True)
class RecordAdministration:
    """One class's administration of the version: when it was recorded, the class, the backend
    and panel build it was graded on (None when neither the record nor the class's run says),
    and what it collected — `blind_count`, or the `absence_reason` it collected nothing for."""

    cohort_id: str
    recorded_at: str
    backend_profile: str | None
    panel_build_ref: str | None
    blind_count: int
    absence_reason: str | None
    unmarked_count: int


@dataclass(frozen=True)
class RecordCriterion:
    """One criterion's agreement over the record, scoped by backend and panel build. Below the
    headline minimum `too_few` is true and the figures are withheld (None); `n` always shows."""

    criterion_id: str
    scoring_model: str
    backend_profile: str
    panel_build_ref: str
    n: int
    too_few: bool
    matched: int | None
    kappa: float | None
    qwk: float | None
    reason: str | None
    administrations: int


@dataclass(frozen=True)
class PackageRecord:
    """A package version's record (FR-STATS-35). Empty for a version no class has completed."""

    package_version_id: str
    blind_labels: int
    min_n_for_headline: int
    criteria: tuple[RecordCriterion, ...]
    administrations: tuple[RecordAdministration, ...]


@dataclass(frozen=True)
class LabelPair:
    """One admissible blind label with both bands: whose answer, which criterion, what the
    system gave and what the teacher gave."""

    student_ref: str
    criterion_id: str
    system_band: str
    teacher_band: str


def _extra(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        extra = json.loads(row.get("figures") or "{}")
    except (TypeError, ValueError):
        return {}
    return extra if isinstance(extra, dict) else {}


def _run_key_parts_of(store: Any, cohort_id: str, package_version_id: str
                      ) -> tuple[str | None, str | None]:
    """The backend and panel build of the class's newest run of the version, from its own
    file; (None, None) when the class's file is gone (a purged class) or names no such run."""
    data_dir = getattr(store, "data_dir", None)
    if not cohort_id or data_dir is None or not Path(
            data_dir, "cohorts", f"{cohort_id}.sqlite").exists():
        return None, None
    try:
        rows = store.cohort(cohort_id).query(STATS_STATEMENTS["select_version_runs"],
                                             package_version_id=package_version_id)
    except Exception:  # noqa: BLE001 — an unreadable class file says nothing about its run
        return None, None
    for row in rows:
        try:
            config = json.loads(row["provider_config"] or "{}")
        except (TypeError, ValueError):
            config = {}
        panel = str(config.get("panel_build_ref") or "") if isinstance(config, dict) else ""
        return (str(row["backend_profile"] or "") or None), (panel or None)
    return None, None


def package_record(store: Any, package_version_id: str, *,
                   before_cohort_id: str | None = None) -> PackageRecord:
    """The version's record across its administrations (FR-STATS-35).

    With `before_cohort_id`, the record as it stood before that class's administration: the
    administrations recorded ahead of it (every other one when it is not recorded yet), and
    each criterion's figure as the latest of those stored it. This is the validity read's
    prior record, which is never this administration's own evidence (FR-CONSOLE-24)."""
    minimum = int(_settings.STATS_MIN_N_FOR_HEADLINE)
    handle = store.durable()
    records = [_row_mapping(row) for row in handle.query(
        STATS_STATEMENTS["select_version_promotion_records"],
        package_version_id=package_version_id)]
    if before_cohort_id is not None:
        position = next((index for index, row in enumerate(records)
                         if str(row["cohort_id"]) == before_cohort_id), None)
        records = (records[:position] if position is not None
                   else [row for row in records if str(row["cohort_id"]) != before_cohort_id])
    order = {str(row["cohort_id"]): index for index, row in enumerate(records)}
    rows = [_row_mapping(row) for row in handle.query(
        STATS_STATEMENTS["select_version_criterion_stats"],
        package_version_id=package_version_id)]
    rows = [row for row in rows if str(row.get("cohort_id") or "") in order]

    key_parts: dict[str, tuple[str | None, str | None]] = {}
    for row in rows:
        key_parts.setdefault(str(row["cohort_id"]),
                             (str(row["backend_profile"]), str(row["panel_build_ref"])))
    administrations = []
    for record in records:
        cohort_id = str(record["cohort_id"])
        backend, panel = key_parts.get(cohort_id) or _run_key_parts_of(
            store, cohort_id, package_version_id)
        administrations.append(RecordAdministration(
            cohort_id=cohort_id,
            recorded_at=str(record.get("recorded_at") or ""),
            backend_profile=backend,
            panel_build_ref=panel,
            blind_count=int(record.get("blind_count") or 0),
            absence_reason=record.get("absence_reason"),
            unmarked_count=int(record.get("unmarked_count") or 0),
        ))

    by_key: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        key = (str(row["criterion_id"]), str(row["backend_profile"]),
               str(row["panel_build_ref"]))
        by_key.setdefault(key, []).append(row)
    criteria = []
    for (criterion, backend, panel), group in sorted(by_key.items()):
        group.sort(key=lambda row: order[str(row["cohort_id"])])
        latest = group[-1]
        stored = _extra(latest).get("cumulative")
        if isinstance(stored, dict):
            n = int(stored.get("n") or 0)
            pooled = stored
        elif len(group) == 1:
            # A record written before the cumulative figure was stored: its own figure is
            # the whole record for a key it alone contributes to.
            n = int(latest.get("n") or 0)
            pooled = {"matched": latest.get("matched"), "kappa": latest.get("kappa"),
                      "qwk": latest.get("qwk"), "reason": latest.get("reason"),
                      "administrations": 1}
        else:
            n = sum(int(row.get("n") or 0) for row in group)
            pooled = {"matched": None, "kappa": None, "qwk": None,
                      "reason": INSUFFICIENT_DATA, "administrations": len(group)}
        too_few = n < minimum
        criteria.append(RecordCriterion(
            criterion_id=criterion,
            scoring_model=latest.get("scoring_model") or "",
            backend_profile=backend,
            panel_build_ref=panel,
            n=n,
            too_few=too_few,
            matched=None if too_few or pooled.get("matched") is None
            else int(pooled["matched"]),
            kappa=None if too_few else pooled.get("kappa"),
            qwk=None if too_few else pooled.get("qwk"),
            reason=pooled.get("reason"),
            administrations=int(pooled.get("administrations") or len(group)),
        ))
    return PackageRecord(
        package_version_id=package_version_id,
        blind_labels=sum(item.blind_count for item in administrations),
        min_n_for_headline=minimum,
        criteria=tuple(criteria),
        administrations=tuple(administrations),
    )


def administration_pairs(store: Any, *, cohort_id: str,
                         run_id: str | None = None) -> tuple[LabelPair, ...]:
    """The administration's admissible blind labels that carry both bands, in label order:
    the class's labels (the canonical cohort read), narrowed to `run_id` when given."""
    rows = store.durable().query(STATS_STATEMENTS["select_labels"], cohort_id=cohort_id)
    pairs = []
    for row in rows:
        mapping = _row_mapping(row)
        if run_id is not None and str(mapping.get("run_id") or "") != run_id:
            continue
        label = _StoredLabel(mapping)
        system, teacher = _system_side(label), getattr(label, "teacher_band", None)
        if not _is_admissible(label) or system is None or teacher is None:
            continue
        pairs.append(LabelPair(
            student_ref=str(mapping.get("student_ref") or ""),
            criterion_id=str(label.criterion_id),
            system_band=str(system),
            teacher_band=str(teacher),
        ))
    return tuple(pairs)


def _view(criterion_id: str, scoring_model: str, *, n: int, minimum: int, matched: Any,
          kappa: Any, qwk: Any, reason: Any) -> dict[str, Any]:
    view: dict[str, Any] = {
        "criterion_id": criterion_id,
        "scoring_model": scoring_model,
        "matched": matched,
        "n": n,
        "kappa": kappa,
        "min_n_for_headline": minimum,
        "too_few": n < minimum,
        "reason": reason,
    }
    if qwk is not None:
        view["qwk"] = qwk
    return view


def administration_figure_views(update: Any, *, minimum: int | None = None
                                ) -> list[dict[str, Any]]:
    """One administration's stored per-criterion figures as the console serves them
    (FR-CONSOLE-80): each judged criterion's scoring model, matched, n, kappa (and qwk only
    where stored, a three-or-more-band line), the headline minimum and `too_few`. Each view is
    one criterion's, so atomic and holistic never pool (FR-CONSOLE-10); a deterministic line
    has no admissible label, so it has no figure and never appears (R53). The figures are
    passed through, never recomputed: a consumer outside M-STATS names no figure field, and
    nothing here branches on the scoring model's value (CT-AGG-09)."""
    limit = int(_settings.STATS_MIN_N_FOR_HEADLINE if minimum is None else minimum)
    figures = dict(getattr(update, "criterion_figures", None) or {})
    return [
        _view(criterion, figure.get("scoring_model") or "", n=int(figure.get("n") or 0),
              minimum=limit, matched=figure.get("matched"), kappa=figure.get("kappa"),
              qwk=figure.get("qwk"), reason=figure.get("reason"))
        for criterion, figure in sorted(figures.items())
    ]


def record_figure_views(record: PackageRecord) -> list[dict[str, Any]]:
    """A package record's per-criterion figures as the console serves them (FR-CONSOLE-84):
    the same view as `administration_figure_views`, with the figures withheld below the
    minimum, and each scoped by its `backend` and `panel_build_ref`."""
    views = []
    for item in record.criteria:
        view = _view(item.criterion_id, item.scoring_model, n=item.n,
                     minimum=record.min_n_for_headline, matched=item.matched,
                     kappa=item.kappa, qwk=item.qwk, reason=item.reason)
        view["backend"] = item.backend_profile
        view["panel_build_ref"] = item.panel_build_ref
        views.append(view)
    return views


__all__: Sequence[str] = (
    "LabelPair",
    "PackageRecord",
    "RecordAdministration",
    "RecordCriterion",
    "administration_figure_views",
    "administration_pairs",
    "package_record",
    "record_figure_views",
)
