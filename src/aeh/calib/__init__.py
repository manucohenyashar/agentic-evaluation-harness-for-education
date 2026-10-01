"""M-CALIB: rubric calibration, finding and fixing ambiguity in a rubric (design §3.17).

Calibration compares a teacher's grades on a few sample papers with the system's grades under
the current rubric (R0). Each disagreement is triaged into one of three categories: rubric
ambiguity, model failure, or teacher inconsistency. Only rubric ambiguity may lead to an edit.
The teacher is asked a small, capped number of questions, and the answers become rubric
clarifications written through M-PKG; fields locked by the schema lock can never be edited.

A revised rubric (R1) is accepted only after two gates:

- the non-inferiority gate, which dual-scores the class under R0 and R1 and refuses R1 if too
  many papers shift by a full band, against an institution-declared threshold;
- the back-translation gate, where an off-panel model (one not used for scoring) tries to
  reconstruct the rubric's intent.

The approved revision is then pinned.

Several `*_for_test` functions are test seams that this module deliberately exposes.

Files:
    constants.py     triage categories, pipeline stages and the alert knob
    errors.py        the errors this package raises
    discovery.py     discovering disagreements and triaging them
    elicitation.py   the capped questions put to the teacher, and applying the answers
    driver.py        `run_for_assignment`: one calibration run, stage by stage
    off_panel.py     the off-panel checker model: its identity, sessions and providers
    rosters.py       class rosters: each paper's band under R0 and R1
    gates.py         the non-inferiority and back-translation gates, and pinning R1
    dual_scoring.py  planning, authorizing and running a dual-scoring pass
    knobs.py         the knob sweep used to check each knob changes observable behaviour
    fixtures.py      test seams: stores, catalogs and elicitation history over real files
    scenarios.py     test seams: band-shift cohorts, off-panel models, counting providers
    observability.py the metrics and alerts M-CALIB emits, and the failure-mode simulator

Detailed design notes (the full original module description): `docs/code-notes/calib.md`.
"""

from __future__ import annotations

from aeh.pkg import SchemaLockViolation

from .constants import (
    AMBIGUITY_ALERT_TEXT,
    CALIB_AMBIGUITY_ALERT_AFTER,
    CALIB_AMBIGUITY_ALERT_AFTER_ENV,
    DEFAULT_PIPELINE_STAGE,
    EDIT_ELIGIBLE_CATEGORY,
    EXAMPLES_PER_SIDE_BY_SIDE,
    KIND_AMBIGUITY_DISCOVERY,
    LOGGER,
    MODEL_FAILURE,
    PIPELINE_STAGES,
    RUBRIC_AMBIGUITY,
    TEACHER_INCONSISTENCY,
    TRIAGE_CATEGORIES,
)
from .errors import (
    CalibrationError,
    EditNotEligible,
    InsufficientPopulation,
    OffPanelConfigurationError,
    OffPanelUnavailable,
    PhaseDependencyError,
    SideBySideRequired,
    ThresholdNotDeclared,
    TriageCategoryRequired,
)
from .discovery import (
    Disagreement,
    discover,
    DiscoveryReport,
    field_names_of,
    PipelineFinding,
    triage,
    TriageVerdict,
)
from .elicitation import (
    apply_answers,
    CALIB_MAX_QUESTIONS,
    CALIB_MAX_QUESTIONS_ENV,
    edit_touching,
    elicit,
    ElicitationQuestion,
    Finding,
    LOCKED_FIELD_NAMES,
    LockedFieldEdit,
    package_version_predating_schema_lock,
    QUESTION_OPTIONS,
)
from .driver import Assignment, assignment, CalibrationRunOutcome, run_for_assignment
from .off_panel import (
    _BackTranslationSession,
    bind_off_panel_provider,
    CALIB_OFF_PANEL_MODEL,
    CALIB_OFF_PANEL_MODEL_ENV,
    _ConstructionAttempt,
    _OFF_PANEL_SESSIONS,
    OffPanelModelRef,
    unbind_off_panel_provider,
)
from .rosters import (
    CALIB_CLASS_SIZE_CAP,
    CALIB_CLASS_SIZE_CAP_ENV,
    CALIB_STATEMENTS,
    _CLASS_ROSTERS,
    _ClassRoster,
    register_dual_scored_roster,
)
from .gates import (
    back_translate,
    CALIB_NONINFERIORITY_THRESHOLD,
    CALIB_NONINFERIORITY_THRESHOLD_ENV,
    CALIBRATION_SET,
    _clear_institutional_threshold,
    declare_institutional_threshold,
    GateResult,
    non_inferiority,
    pin_revision,
    PinnedRevision,
)
from .dual_scoring import (
    authorize,
    DualScoringPlan,
    PLAN_DEFAULT_CLASS_SIZE,
    PLAN_DEFAULT_CRITERIA_COUNT,
    plan_dual_scoring,
    run_dual_scoring,
)
from .knobs import contrasting_values_for, KNOBS, observable_behaviour_with
from .fixtures import (
    catalog_for_test,
    elicitation_history_for_test,
    findings_fixture,
    _HISTORY_UPDATE_STATEMENTS,
    tier_p_path_for_test,
)
from .scenarios import (
    cohort_with_band_shift,
    counting_provider_for_test,
    model_ref_in_panel,
    model_ref_off_panel,
    _off_panel_model_ref,
    worse_but_low_shift_revision,
    WorseButLowShiftRevision,
)
from .observability import (
    alerts_for_test,
    CalibrationAlert,
    CalibrationMetric,
    metrics_for_test,
    simulate_failure,
)


__all__: tuple[str, ...] = (
    "CALIB_AMBIGUITY_ALERT_AFTER",
    "CALIB_AMBIGUITY_ALERT_AFTER_ENV",
    "CALIB_CLASS_SIZE_CAP",
    "CALIB_CLASS_SIZE_CAP_ENV",
    "CALIB_MAX_QUESTIONS",
    "CALIB_MAX_QUESTIONS_ENV",
    "CALIB_NONINFERIORITY_THRESHOLD",
    "CALIB_NONINFERIORITY_THRESHOLD_ENV",
    "CALIB_OFF_PANEL_MODEL",
    "CALIB_OFF_PANEL_MODEL_ENV",
    "CALIBRATION_SET",
    "CalibrationAlert",
    "CalibrationError",
    "CalibrationMetric",
    "CalibrationRunOutcome",
    "Assignment",
    "DEFAULT_PIPELINE_STAGE",
    "Disagreement",
    "DiscoveryReport",
    "DualScoringPlan",
    "EditNotEligible",
    "ElicitationQuestion",
    "EXAMPLES_PER_SIDE_BY_SIDE",
    "Finding",
    "GateResult",
    "InsufficientPopulation",
    "KIND_AMBIGUITY_DISCOVERY",
    "KNOBS",
    "LockedFieldEdit",
    "MODEL_FAILURE",
    "OffPanelConfigurationError",
    "OffPanelModelRef",
    "OffPanelUnavailable",
    "PIPELINE_STAGES",
    "PinnedRevision",
    "PhaseDependencyError",
    "QUESTION_OPTIONS",
    "RUBRIC_AMBIGUITY",
    "SchemaLockViolation",
    "SideBySideRequired",
    "TEACHER_INCONSISTENCY",
    "ThresholdNotDeclared",
    "TriageCategoryRequired",
    "TriageVerdict",
    "TRIAGE_CATEGORIES",
    "alerts_for_test",
    "apply_answers",
    "assignment",
    "authorize",
    "back_translate",
    "catalog_for_test",
    "cohort_with_band_shift",
    "contrasting_values_for",
    "counting_provider_for_test",
    "declare_institutional_threshold",
    "discover",
    "edit_touching",
    "elicit",
    "elicitation_history_for_test",
    "field_names_of",
    "findings_fixture",
    "metrics_for_test",
    "model_ref_in_panel",
    "model_ref_off_panel",
    "non_inferiority",
    "observable_behaviour_with",
    "package_version_predating_schema_lock",
    "pin_revision",
    "plan_dual_scoring",
    "register_dual_scored_roster",
    "run_dual_scoring",
    "run_for_assignment",
    "simulate_failure",
    "tier_p_path_for_test",
    "triage",
    "worse_but_low_shift_revision",
)
