"""The teacher's marked examples as a reference set for model changes (FR-CALIB-19, #889).

When the graders change — a panel member, a model build, a quantization or the prompt template
(FR-STATS-19's triggers) — a test's marked examples are graded again in their calibration
cohort, and a **consistency report** says, per criterion, on how many examples the system's
level moved since the previous grading. It is a consistency check of the graders against
themselves, never a claim about accuracy: the examples are a dozen papers the teacher chose,
and the system's levels are compared with its own earlier levels, not with the teacher's
(CT-CALIB-03 — no rate, percentage or agreement figure).

`reference_set_due` is the trigger check: nothing changed since the last grading of the
examples, nothing is due, and nothing is re-graded. `regrade_reference_set` re-grades through
the composition root's driver (as `grade_examples` does: the consent gate, R31 and the run cost
ceiling apply) and writes the report through M-PKG as a `graders_record` row (migration 15),
ran or refused.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from .constants import LOGGER
from .examples import (
    EXAMPLES_STATEMENTS,
    calibration_cohort_id,
    example_runs,
    examples_of,
    refuse_remote_real_work,
)

#: The report's label: a consistency check (FR-CALIB-19), in the teacher's words.
CONSISTENCY_LABEL = "Consistency check"

#: What the report says it is. No "accuracy" in its text (FR-CALIB-19).
CONSISTENCY_SENTENCE = (
    "The marking models changed, so your marked examples were marked again. This checks "
    "whether the marking stayed consistent with itself; it compares the system with its own "
    "earlier marks, not with yours."
)

#: FR-STATS-19's four triggers: the dimensions whose change re-grades the examples.
REFERENCE_DIMENSIONS: tuple[str, ...] = (
    "panel_member", "model_build", "quantization", "prompt_template_version",
)


def _rows(store: Any, cohort_id: str, name: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in store.cohort(cohort_id).query(EXAMPLES_STATEMENTS[name],
                                                                **params)]


def run_configuration(store: Any, cohort_id: str, run_id: str) -> dict[str, Any]:
    """The grader configuration (`aeh.stats.grader_configuration`) a calibration run was frozen
    to, from its run row."""
    from aeh.stats import grader_configuration

    rows = _rows(store, cohort_id, "select_run_frozen_config", run_id=run_id)
    if not rows:
        return {}
    return grader_configuration(rows[0])


def _complete_runs(store: Any, package_version_id: str) -> list[str]:
    return [run_id for run_id, status in example_runs(store, package_version_id)
            if status == "complete"]


def reference_set_due(store: Any, package_version_id: str,
                      configuration: Mapping[str, Any]) -> tuple[str, ...]:
    """The FR-STATS-19 dimensions on which `configuration` differs from the configuration the
    version's examples were last graded under, or `()`: no graded examples, or no change,
    means no re-grade."""
    runs = _complete_runs(store, package_version_id)
    if not runs or not examples_of(store, package_version_id):
        return ()
    previous = run_configuration(store, calibration_cohort_id(package_version_id), runs[-1])
    if not previous:
        return ()
    return tuple(dimension for dimension in REFERENCE_DIMENSIONS
                 if _normal(previous.get(dimension)) != _normal(configuration.get(dimension)))


def _normal(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return tuple(sorted(str(item) for item in value))
    return value


def _bands(store: Any, cohort_id: str, run_id: str,
           submissions: set[str]) -> dict[tuple[str, str], str]:
    return {(str(row["submission_id"]), str(row["criterion_id"])): str(row["band"])
            for row in _rows(store, cohort_id, "select_run_scores", run_id=run_id)
            if str(row["submission_id"]) in submissions}


def moved_counts(store: Any, package_version_id: str, previous_run: str,
                 run_id: str) -> dict[str, dict[str, int]]:
    """Per criterion: on how many examples the system's level moved between two gradings
    (`moved`), out of the examples graded on that criterion both times (`examples`)."""
    cohort_id = calibration_cohort_id(package_version_id)
    submissions = {example.submission_id for example in examples_of(store, package_version_id)}
    before = _bands(store, cohort_id, previous_run, submissions)
    after = _bands(store, cohort_id, run_id, submissions)
    report: dict[str, dict[str, int]] = {}
    for key in sorted(set(before) & set(after)):
        entry = report.setdefault(key[1], {"moved": 0, "examples": 0})
        entry["examples"] += 1
        if before[key] != after[key]:
            entry["moved"] += 1
    return report


@dataclass(frozen=True)
class ReferenceRegrade:
    """One re-grade of a version's marked examples (FR-CALIB-19): whether it ran, the record it
    was filed under, the two runs compared, and per criterion the moved counts."""

    package_version_id: str
    trigger: str
    ran: bool
    record_id: str
    run_id: str | None = None
    previous_run_id: str | None = None
    criteria: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    refusal: str | None = None


def regrade_reference_set(
    store: Any,
    package_version_id: str,
    *,
    config: Mapping[str, Any],
    trigger: str,
    configuration: Mapping[str, Any],
    provider: Any = None,
    **drive_keywords: Any,
) -> ReferenceRegrade:
    """Grade the version's marked examples again after a model change and write the
    consistency report (FR-CALIB-19). Refused, and recorded as refused, when the examples were
    never graded, when remote work is not `synthetic` (R31), or when the run does not complete
    (the run cost ceiling stops it, or a stage fails)."""
    from aeh import pkg as _pkg
    from aeh.orch import cohort_summary
    from aeh.pipeline import drive_run

    def _refused(reason: str, previous: str | None = None) -> ReferenceRegrade:
        record_id = _pkg.record_graders_event(
            store.data_dir, package_version_id=package_version_id, kind="reference_set",
            trigger=trigger, configuration=configuration, outcome="refused",
            detail={"label": CONSISTENCY_LABEL, "refusal": reason,
                    "previous_run_id": previous})
        LOGGER.info("reference-set re-grade of %s refused: %s", package_version_id, reason)
        return ReferenceRegrade(package_version_id, trigger, False, record_id,
                                previous_run_id=previous, refusal=reason)

    cohort_id = calibration_cohort_id(package_version_id)
    runs = _complete_runs(store, package_version_id)
    if not runs:
        return _refused("the marked examples were never graded")
    previous = runs[-1]
    try:
        summary = cohort_summary(store, cohort_id)
        refuse_remote_real_work(config, str(summary.consent_class if summary else "real"))
        result = drive_run(store, cohort_id=cohort_id, package_version_id=package_version_id,
                           config=config, provider=provider, **drive_keywords)
    except Exception as error:  # noqa: BLE001 — the refusal is the recorded outcome
        return _refused(str(error), previous)
    if str(result.status) != "complete":
        return _refused(f"the re-grade stopped ({result.status})", previous)
    criteria = moved_counts(store, package_version_id, previous, str(result.run_id))
    record_id = _pkg.record_graders_event(
        store.data_dir, package_version_id=package_version_id, kind="reference_set",
        trigger=trigger, configuration=configuration, outcome="ran",
        detail={"label": CONSISTENCY_LABEL, "sentence": CONSISTENCY_SENTENCE,
                "previous_run_id": previous, "run_id": str(result.run_id),
                "criteria": criteria})
    LOGGER.info("re-graded %s's marked examples on %s: %s", package_version_id, trigger,
                json.dumps(criteria, sort_keys=True))
    return ReferenceRegrade(package_version_id, trigger, True, record_id,
                            run_id=str(result.run_id), previous_run_id=previous,
                            criteria=criteria)


def consistency_report(store: Any, package_version_id: str | None = None
                       ) -> dict[str, Any] | None:
    """The newest consistency report (FR-CALIB-19), of one version or of any: its label, when,
    the trigger, and per criterion the moved counts — or the refusal. None when the examples
    were never re-graded."""
    from aeh.pkg import graders_records

    records = graders_records(store, kind="reference_set",
                              package_version_id=package_version_id)
    if not records:
        return None
    record = records[0]
    detail = record["detail"]
    return {
        "label": CONSISTENCY_LABEL,
        "sentence": CONSISTENCY_SENTENCE,
        "package_version_id": record["package_version_id"],
        "recorded_at": record["recorded_at"],
        "trigger": record["trigger"],
        "outcome": record["outcome"],
        "criteria": dict(detail.get("criteria") or {}),
        "refusal": detail.get("refusal"),
    }


__all__ = [
    "CONSISTENCY_LABEL",
    "CONSISTENCY_SENTENCE",
    "REFERENCE_DIMENSIONS",
    "ReferenceRegrade",
    "consistency_report",
    "moved_counts",
    "reference_set_due",
    "regrade_reference_set",
    "run_configuration",
]
