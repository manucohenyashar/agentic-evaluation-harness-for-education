"""M-STATS: the statistics that say whether the system's grades can be trusted (design §3.16).

Every figure here is computed only from admissible labels: blind labels, given by a teacher who
had not seen the system's output, and never from deterministic (multiple-choice) results. The
headline figure is chance-corrected agreement (Cohen's kappa, quadratic-weighted kappa and
ordinal Krippendorff's alpha) with an honest interval for the sample size; below a minimum
sample size no headline is given.

Around it sit the checks the design calls for: the six-step Minimum Viable Validation Protocol
(position bias, self-agreement, cross-validation, compression), per-judge signals, per-engine
agreement for the decision engine, compression, surface-proxy and drift checks, routing-policy
validity, and the validation record that accumulates across administrations.

Files:
    settings.py      thresholds, tolerances, evidence weights and their knobs
    admissibility.py which labels may count, and why the others were excluded
    agreement.py     the chance-corrected agreement figure
    schema.py        the SQL statements
    mvvp.py          the Minimum Viable Validation Protocol and its results
    measurements.py  measuring position bias and self-agreement by re-running judges
    judge_signals.py per-judge signals and their violation alert
    engines.py       agreement per engine partition and the decision gate's calibration
    records.py       the reports the checks return
    comparisons.py   compression, surface proxies, routing-policy validity, drift, alerts
    promotion.py     recording an administration into the validation record
    history.py       override history, disagreement rates, narrative quality, counters
    exports.py       the long-horizon and analytical exports
    revisions.py     per-criterion figures across rubric revisions
    service.py       `ValidationStats`, `build_stats` and `open_stats`

Detailed design notes (the full original module description): `docs/code-notes/stats.md`.
"""

from __future__ import annotations

from aeh.pkg import NoValidationData

from .settings import (
    BLIND_SAMPLE_SKIPPED_ALERT,
    DRIFT_SAMPLE_RANGE,
    NO_NEW_VALIDATION_EVIDENCE,
    OPERATIONAL_EVIDENCE_ORDER,
    OPERATIONAL_EVIDENCE_WEIGHTS,
    REVIEW_OVERRIDE_MIN_N_DEFAULT,
    REVIEW_OVERRIDE_MIN_N_ENV,
    ROUTING_POLICY_ARM_SOURCES,
    ROUTING_POLICY_ARMS,
    ROUTING_POLICY_DISCRIMINATING_VERDICT,
    ROUTING_POLICY_FAILING_VERDICT,
    ROUTING_POLICY_NO_DATA_VERDICT,
    SCORING_MODELS,
    STATS_BLIND_SKIP_ALERT_AFTER,
    STATS_DRIFT_TOLERANCE,
    STATS_MIN_N_FOR_HEADLINE,
    STATS_ROUTING_POLICY_TOLERANCE,
    STATS_SUBGROUP_ANALYSIS_ENABLED,
    STATS_SURFACE_PROXY_CORRELATION_THRESHOLD,
    SURFACE_FEATURES,
    SURFACE_PROXY_ALERT,
)
from .admissibility import (
    BACKEND_NOT_RECORDED,
    exclusion_reasons,
    _is_admissible,
    SAW_SYSTEM_OUTPUT_NULL_IS_INADMISSIBLE,
    SAW_SYSTEM_OUTPUT_UNRECORDED,
)
from .agreement import agreement, AgreementFigure
from .schema import STATS_STATEMENTS
from .mvvp import (
    CompressionOutcome,
    CrossValidationOutcome,
    latest_mvvp,
    MVVP_REPLICATION_RUNS,
    MVVP_RERUN_DIMENSIONS,
    MVVP_SELF_AGREEMENT_PAIRING_THRESHOLD,
    MVVP_STEP_REQUIREMENTS,
    MVVPReport,
    MVVPStep,
    PositionBiasResult,
    ReplicationResult,
    run_mvvp,
    SelfAgreementPairing,
)
from .measurements import (
    measure_position_bias,
    measure_self_agreement,
    SELF_AGREEMENT_MINIMUM_RUNS,
)
from .judge_signals import (
    JUDGE_SIGNAL_FIELDS,
    judge_signals,
    JUDGE_VIOLATION_ALERT,
    JudgeSignals,
    STATS_VIOLATION_CONCENTRATION,
    STATS_VIOLATION_CONCENTRATION_ENV,
    STATS_VIOLATION_MINIMUM,
    STATS_VIOLATION_MINIMUM_ENV,
)
from .engines import (
    agreement_by_engine,
    CALIBRATION_MIN_LABELS,
    CALIBRATION_MIN_LABELS_ENV,
    CalibrationBin,
    decision_engine_noninferior,
    decision_gate_calibration,
    ENGINE_MIN_LABELS,
    ENGINE_MIN_LABELS_ENV,
    engine_partition,
    ENGINE_PARTITIONS,
    EngineAgreement,
    GateCalibrationReport,
    INSUFFICIENT_DATA,
    NONINFERIORITY_DELTA,
    NONINFERIORITY_DELTA_ENV,
)
from .records import (
    BandShape,
    CompressionReport,
    CriterionDisagreement,
    CriterionFigure,
    CriterionOverrideHistory,
    DriftReport,
    NarrativeQualityReport,
    OperationalSignal,
    ProxyReport,
    RoutingArm,
    RoutingPolicyReport,
    StatsAlert,
    ValidationAggregate,
    ValidationUpdate,
)
from .comparisons import (
    alerts,
    compression_check,
    drift_check,
    routing_policy_validity,
    surface_proxies,
)
from .promotion import aggregate, promote, _record_noninferiority_verdicts
from .history import (
    criterion_disagreement_rate,
    criterion_override_history,
    narrative_quality,
    observability_counters,
    operational_signal,
    stored_disagreement_rates,
    stored_override_histories,
)
from .exports import (
    analytical_export,
    long_horizon_export,
    LONG_HORIZON_RECORD_FIELDS,
    LONG_HORIZON_SCHEMA_VERSION,
    UNCLAIMED_ADMINISTRATION,
)
from .revisions import cohort_with_mixed_revisions, criterion_figures, describe_revision_gate
from .service import build_stats, open_stats, ValidationStats


__all__ = [
    "SAW_SYSTEM_OUTPUT_NULL_IS_INADMISSIBLE",
    "SAW_SYSTEM_OUTPUT_UNRECORDED",
    "exclusion_reasons",
    "JUDGE_SIGNAL_FIELDS",
    "JUDGE_VIOLATION_ALERT",
    "JudgeSignals",
    "STATS_VIOLATION_CONCENTRATION",
    "STATS_VIOLATION_CONCENTRATION_ENV",
    "STATS_VIOLATION_MINIMUM",
    "STATS_VIOLATION_MINIMUM_ENV",
    "judge_signals",
    "AgreementFigure",
    "BandShape",
    "BLIND_SAMPLE_SKIPPED_ALERT",
    "CompressionOutcome",
    "CompressionReport",
    "CriterionFigure",
    "CriterionOverrideHistory",
    "CrossValidationOutcome",
    "DRIFT_SAMPLE_RANGE",
    "DriftReport",
    "MVVPReport",
    "MVVPStep",
    "NarrativeQualityReport",
    "NO_NEW_VALIDATION_EVIDENCE",
    "NoValidationData",
    "OperationalSignal",
    "OPERATIONAL_EVIDENCE_ORDER",
    "OPERATIONAL_EVIDENCE_WEIGHTS",
    "PositionBiasResult",
    "ProxyReport",
    "ROUTING_POLICY_ARM_SOURCES",
    "ROUTING_POLICY_ARMS",
    "ROUTING_POLICY_DISCRIMINATING_VERDICT",
    "ROUTING_POLICY_FAILING_VERDICT",
    "ROUTING_POLICY_NO_DATA_VERDICT",
    "ReplicationResult",
    "SCORING_MODELS",
    "SURFACE_FEATURES",
    "SURFACE_PROXY_ALERT",
    "SelfAgreementPairing",
    "STATS_BLIND_SKIP_ALERT_AFTER",
    "STATS_MIN_N_FOR_HEADLINE",
    "STATS_STATEMENTS",
    "STATS_SUBGROUP_ANALYSIS_ENABLED",
    "STATS_SURFACE_PROXY_CORRELATION_THRESHOLD",
    "STATS_ROUTING_POLICY_TOLERANCE",
    "STATS_DRIFT_TOLERANCE",
    "StatsAlert",
    "RoutingArm",
    "RoutingPolicyReport",
    "ValidationAggregate",
    "ValidationStats",
    "ValidationUpdate",
    "aggregate",
    "agreement",
    "alerts",
    "LONG_HORIZON_RECORD_FIELDS",
    "LONG_HORIZON_SCHEMA_VERSION",
    "analytical_export",
    "build_stats",
    "cohort_with_mixed_revisions",
    "compression_check",
    "criterion_figures",
    "criterion_override_history",
    "criterion_disagreement_rate",
    "CriterionDisagreement",
    "stored_disagreement_rates",
    "stored_override_histories",
    "REVIEW_OVERRIDE_MIN_N_ENV",
    "describe_revision_gate",
    "drift_check",
    "latest_mvvp",
    "long_horizon_export",
    "narrative_quality",
    "observability_counters",
    "open_stats",
    "operational_signal",
    "promote",
    "routing_policy_validity",
    "SELF_AGREEMENT_MINIMUM_RUNS",
    "measure_position_bias",
    "measure_self_agreement",
    "run_mvvp",
    "surface_proxies",
]
