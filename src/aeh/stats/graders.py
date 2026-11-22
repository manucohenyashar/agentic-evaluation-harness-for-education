"""The graders themselves measured (FR-STATS-36, FR-CONSOLE-88, #889).

Two halves, both about the graders rather than one class:

- **The MVVP schedule (FR-STATS-36).** `run_mvvp` runs at package approval and whenever one of
  FR-STATS-19's trigger dimensions changes — panel member, model build, quantization, prompt
  template — and when a decision engine is swapped in or out (`decision_engine`, the fifth
  dimension this schedule watches; the MVVP's own result id keeps digesting FR-STATS-19's four).
  The run is gated by the run cost ceiling: over it, the MVVP is refused and the refusal is
  recorded. Ran or refused, the outcome is one `graders_record` row written through M-PKG
  (CT-STATS-15), carrying the configuration it measured, so the next trigger check compares
  against it and an unchanged configuration runs nothing.
- **The graders' figures (FR-CONSOLE-88).** `graders_figures` reads, from the latest stored
  promotion record, each judged criterion's per-engine agreement (FR-STATS-26), the decision
  gate's calibration bins (FR-STATS-27) and the non-inferiority status (NFR-STATS-06), each
  `insufficient_data` below its minimum (60 per partition, 20 per bin). It reads stored
  figures and never recomputes one (NFR-STATS-07).

Measuring Jev never changes Jev's role (ADR-50): nothing here switches an engine or the
Jev-final setting (CT-CONF-14).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Sequence

from .engines import (
    CALIBRATION_MIN_LABELS,
    CALIBRATION_MIN_LABELS_ENV,
    ENGINE_MIN_LABELS,
    ENGINE_MIN_LABELS_ENV,
    ENGINE_PARTITIONS,
    INSUFFICIENT_DATA,
)
from .mvvp import MVVP_RERUN_DIMENSIONS, MVVPReport
from .schema import STATS_STATEMENTS
from .settings import _env_int

#: The dimensions whose change makes the MVVP (and the reference set's re-grade) due:
#: FR-STATS-19's four, and the decision engine (FR-STATS-36: "swapping in a decision engine
#: counts").
GRADER_DIMENSIONS: tuple[str, ...] = MVVP_RERUN_DIMENSIONS + ("decision_engine",)

#: The trigger an approval records (FR-STATS-36).
PACKAGE_APPROVAL_TRIGGER = "package_approval"

#: Seam 3: the live-tier cost the schedule expects one MVVP to spend, in the run's currency,
#: compared against the run cost ceiling before it runs. The production default is 0 because
#: the MVVP as scheduled reads stored labels and makes no model call of its own; a deployment
#: that wires the live measurements in sets its budget here (delta §10 Q9 is still open).
MVVP_ESTIMATED_COST_ENV = "HARNESS_MVVP_ESTIMATED_COST"
MVVP_ESTIMATED_COST_DEFAULT = Decimal("0")


def _model_key(ref: Any) -> str:
    if not isinstance(ref, Mapping):
        return ""
    return f"{ref.get('provider') or ''}/{ref.get('build_id') or ''}"


def grader_configuration(persisted: Mapping[str, Any]) -> dict[str, Any]:
    """The grader configuration a run was frozen to, as the five trigger dimensions.

    `persisted` is `RunConfig.to_persisted_dict()`'s shape — the `panel_config` and
    `provider_config` a run row stores (JSON strings or mappings both read). `panel_member`
    is the sorted judges; `model_build` every build that grades (judges, transcriber,
    off-panel checker, decision engine); `quantization` their distinct labels;
    `prompt_template_version` the panel's template; `decision_engine` the engine's build or
    `off`."""
    def _mapping(value: Any) -> Mapping[str, Any]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                return {}
        return value if isinstance(value, Mapping) else {}

    panel_config = _mapping(persisted.get("panel_config"))
    provider_config = _mapping(persisted.get("provider_config"))
    panel = [ref for ref in panel_config.get("panel") or () if isinstance(ref, Mapping)]
    engine = _mapping(provider_config.get("decision_engine"))
    engine_model = _mapping(engine.get("model"))
    builds = list(panel) + [_mapping(panel_config.get(key))
                            for key in ("transcriber", "off_panel_checker")]
    if engine_model:
        builds.append(engine_model)
    builds = [ref for ref in builds if ref]
    quantizations = sorted({str(ref.get("quantization")) for ref in builds
                            if ref.get("quantization")})
    return {
        "panel_member": sorted(_model_key(ref) for ref in panel),
        "model_build": ",".join(sorted({_model_key(ref) for ref in builds})) or None,
        "quantization": ",".join(quantizations) or None,
        "prompt_template_version": (str(panel_config["prompt_template_v"])
                                    if panel_config.get("prompt_template_v") else None),
        "decision_engine": _model_key(engine_model) if engine_model else "off",
    }


def changed_dimensions(previous: Mapping[str, Any] | None,
                       current: Mapping[str, Any]) -> tuple[str, ...]:
    """The trigger dimensions whose value differs between two configurations, in
    `GRADER_DIMENSIONS` order. A missing or empty previous configuration has no baseline to
    differ from, so every dimension counts as changed."""
    if not previous:
        return GRADER_DIMENSIONS
    return tuple(dimension for dimension in GRADER_DIMENSIONS
                 if _normal(previous.get(dimension)) != _normal(current.get(dimension)))


def _normal(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return tuple(sorted(str(item) for item in value))
    return value


def mvvp_due(store: Any, package_version_id: str,
             configuration: Mapping[str, Any]) -> tuple[str, ...]:
    """The dimensions that changed since the version's last recorded MVVP (ran or refused),
    or `()` when nothing changed — no trigger, no run. A version never measured is due on
    every dimension."""
    latest = latest_mvvp_record(store, package_version_id)
    return changed_dimensions(None if latest is None else latest["configuration"],
                              configuration)


@dataclass(frozen=True)
class ScheduledMvvp:
    """One scheduled MVVP's outcome (FR-STATS-36): whether it ran, the trigger, the record id
    it was filed under, the report when it ran, and the refusal when it did not."""

    package_version_id: str
    trigger: str
    ran: bool
    record_id: str
    report: MVVPReport | None = None
    refusal: str | None = None
    estimated_cost: Decimal | None = None
    cost_ceiling: Decimal | None = None


def _estimated_cost(environ: Mapping[str, str] | None) -> Decimal:
    raw = (environ if environ is not None else os.environ).get(MVVP_ESTIMATED_COST_ENV)
    if raw is None or not str(raw).strip():
        return MVVP_ESTIMATED_COST_DEFAULT
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        raise ValueError(f"{MVVP_ESTIMATED_COST_ENV} is not a decimal number: {raw!r}") from None
    if not value.is_finite() or value < 0:
        raise ValueError(f"{MVVP_ESTIMATED_COST_ENV} must be a finite, non-negative number")
    return value


def _plain(value: Any) -> Any:
    """A report value as JSON-ready data: dataclasses as mappings, instants as ISO text."""
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and value != value:  # NaN is no JSON value
        return None
    return value


def mvvp_summary(report: MVVPReport) -> dict[str, Any]:
    """The report as the record stores it: the result id, when, and each of the six steps'
    own outcome under its requirement — never one pass/fail (CT-STATS-07)."""
    return {
        "result_id": report.result_id,
        "measured_at": report.measured_at.isoformat(),
        "judges_in_scope": list(report.judges_in_scope),
        "steps": {str(number): {"requirement": step.requirement,
                                "outcome": _plain(step.outcome)}
                  for number, step in sorted(report.steps.items())},
    }


def schedule_mvvp(
    store: Any,
    *,
    package_version_id: str,
    trigger: str,
    configuration: Mapping[str, Any],
    cost_ceiling: Decimal | None = None,
    environ: Mapping[str, str] | None = None,
    measured_self_agreement: Mapping[str, Any] | None = None,
    measured_position_bias: Mapping[str, Any] | None = None,
    runner: Callable[..., MVVPReport] | None = None,
) -> ScheduledMvvp:
    """Run the MVVP once for a package version on a trigger (FR-STATS-36), or refuse it.

    The cost gate comes first: when the expected live cost (`HARNESS_MVVP_ESTIMATED_COST`)
    exceeds the run cost ceiling, nothing runs and the refusal is recorded. Otherwise
    `run_mvvp` runs over the store's admissible labels under `configuration`'s FR-STATS-19
    dimensions, with any live measurements the caller made (`measured_self_agreement`,
    `measured_position_bias`, measured on the live tier or replayed from its recorded twin);
    a step with no measurement reports its declared not-measured reason. `runner` is the seam a
    test spies on (defaults to `run_mvvp`). Either way one `graders_record` row is written
    through M-PKG."""
    from aeh import pkg as _pkg

    from .mvvp import run_mvvp
    from .service import open_stats

    estimate = _estimated_cost(environ)
    data_dir = store.data_dir
    if cost_ceiling is not None and estimate > cost_ceiling:
        refusal = (f"the MVVP's expected cost {estimate} is over the run cost ceiling "
                   f"{cost_ceiling}")
        record_id = _pkg.record_graders_event(
            data_dir, package_version_id=package_version_id, kind="mvvp", trigger=trigger,
            configuration=configuration, outcome="refused",
            detail={"refusal": refusal, "estimated_cost": str(estimate),
                    "cost_ceiling": str(cost_ceiling)})
        return ScheduledMvvp(package_version_id, trigger, False, record_id, refusal=refusal,
                             estimated_cost=estimate, cost_ceiling=cost_ceiling)
    stats = open_stats(data_dir)
    report = (runner or run_mvvp)(
        stats, None,
        configuration={dimension: configuration.get(dimension)
                       for dimension in MVVP_RERUN_DIMENSIONS},
        measured_self_agreement=measured_self_agreement,
        measured_position_bias=measured_position_bias)
    detail = mvvp_summary(report)
    detail["estimated_cost"] = str(estimate)
    detail["cost_ceiling"] = None if cost_ceiling is None else str(cost_ceiling)
    record_id = _pkg.record_graders_event(
        data_dir, package_version_id=package_version_id, kind="mvvp", trigger=trigger,
        configuration=configuration, outcome="ran", detail=detail)
    return ScheduledMvvp(package_version_id, trigger, True, record_id, report=report,
                         estimated_cost=estimate, cost_ceiling=cost_ceiling)


# --- the graders' figures, as System status reads them (FR-CONSOLE-88) -------------------------


def _engine_view(stored: Mapping[str, Any], minimum: int) -> dict[str, Any]:
    """One partition's stored figure, withheld below the minimum whatever was stored."""
    n = int(stored.get("n") or 0)
    alpha = stored.get("ordinal_alpha")
    if n < minimum or alpha is None:
        return {"n": n, "ordinal_alpha": None, "status": INSUFFICIENT_DATA}
    return {"n": n, "ordinal_alpha": float(alpha), "status": "measured"}


def _bin_view(stored: Mapping[str, Any], minimum: int) -> dict[str, Any]:
    n = int(stored.get("n") or 0)
    view = {"low": stored.get("low"), "high": stored.get("high"), "n": n}
    if n < minimum or stored.get("exact_agreement") is None:
        return {**view, "exact_agreement": None, "adjacent_agreement": None,
                "status": INSUFFICIENT_DATA}
    return {**view, "exact_agreement": stored.get("exact_agreement"),
            "adjacent_agreement": stored.get("adjacent_agreement"), "status": "measured"}


def _noninferiority_view(stored: Any, by_engine: Mapping[str, Mapping[str, Any]]) -> str:
    """`true`, `false` or `insufficient_data`: the stored verdict, never a verdict over a
    partition the minimum now withholds."""
    if any(by_engine.get(name, {}).get("status") != "measured"
           for name in ("decision", "llm_engine_off")):
        return INSUFFICIENT_DATA
    return str(stored) if stored in ("true", "false") else INSUFFICIENT_DATA


def graders_figures(store: Any, package_version_id: str | None = None) -> dict[str, Any]:
    """The engine measurements from the latest promotion record (FR-CONSOLE-88): of the named
    version, else of any version. Each judged criterion's per-engine agreement (every partition
    reported, `insufficient_data` below `HARNESS_STATS_ENGINE_MIN_LABELS`, 60), the gate's
    calibration bins (`insufficient_data` below `HARNESS_STATS_CALIBRATION_MIN_LABELS`, 20),
    the gate threshold and the non-inferiority status; the record's compression check; and
    `decision_answers`, the most blind answers any criterion holds on decision-engine cells —
    the evidence the Jev block counts toward the minimum. Read-only; no figure recomputed."""
    from .promotion import administration_record

    engine_minimum = _env_int(ENGINE_MIN_LABELS_ENV, ENGINE_MIN_LABELS)
    bin_minimum = _env_int(CALIBRATION_MIN_LABELS_ENV, CALIBRATION_MIN_LABELS)
    handle = store.durable()
    if package_version_id:
        rows = handle.query(STATS_STATEMENTS["select_latest_promotion_for_version"],
                            package_version_id=package_version_id)
    else:
        rows = handle.query(STATS_STATEMENTS["select_latest_promotion"])
    empty: dict[str, Any] = {
        "package_version_id": package_version_id or None, "cohort_id": None,
        "recorded_at": None, "min_per_engine": engine_minimum, "min_per_bin": bin_minimum,
        "criteria": [], "decision_answers": 0, "noninferiority": INSUFFICIENT_DATA,
        "compression": None,
    }
    if not rows:
        return empty
    latest = dict(rows[0])
    record = administration_record(store, package_version_id=str(latest["package_version_id"]),
                                   cohort_id=str(latest["cohort_id"]))
    if record is None:
        return empty
    criteria = []
    for criterion, figure in sorted(dict(record.criterion_figures).items()):
        stored_engines = dict(figure.get("per_engine") or {})
        by_engine = {name: _engine_view(dict(stored_engines.get(name) or {}), engine_minimum)
                     for name in ENGINE_PARTITIONS}
        criteria.append({
            "criterion_id": criterion,
            "per_engine": by_engine,
            "gate_bins": [_bin_view(dict(item), bin_minimum)
                          for item in figure.get("gate_bins") or ()],
            "gate_threshold": figure.get("gate_threshold"),
            "noninferiority": _noninferiority_view(figure.get("noninferiority"), by_engine),
        })
    verdicts = {item["noninferiority"] for item in criteria}
    overall = ("false" if "false" in verdicts else
               "true" if verdicts == {"true"} else INSUFFICIENT_DATA)
    return {
        **empty,
        "package_version_id": str(latest["package_version_id"]),
        "cohort_id": str(latest["cohort_id"]),
        "recorded_at": latest.get("recorded_at"),
        "criteria": criteria,
        "decision_answers": max((item["per_engine"]["decision"]["n"] for item in criteria),
                                default=0),
        "noninferiority": overall,
        "compression": record.compression,
    }


def latest_mvvp_record(store: Any, package_version_id: str | None = None
                       ) -> dict[str, Any] | None:
    """The newest scheduled MVVP's record (FR-STATS-36's "results go to System status"), of one
    version or of any, ran or refused; None when none was scheduled."""
    from aeh.pkg import graders_records

    records = graders_records(store, kind="mvvp", package_version_id=package_version_id)
    return records[0] if records else None


__all__: Sequence[str] = (
    "GRADER_DIMENSIONS",
    "MVVP_ESTIMATED_COST_ENV",
    "PACKAGE_APPROVAL_TRIGGER",
    "ScheduledMvvp",
    "changed_dimensions",
    "grader_configuration",
    "graders_figures",
    "latest_mvvp_record",
    "mvvp_due",
    "mvvp_summary",
    "schedule_mvvp",
)
