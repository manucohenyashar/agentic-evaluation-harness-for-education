"""M-CONFORM: checks that different model backends grade the same fixtures the same way (design §3.18).

A pinned, versioned set of fixture submissions is run through each configured backend. The
suite compares the backends dimension by dimension (score distribution, agreement, confidence,
evidence integrity, self-agreement) and classifies each divergence as blocking or
informational; there is deliberately no single headline number. It also detects a silent
build substitution by the provider, runs the adversarial corpora, and measures how the
decision engine holds up on its own fixture set and against prompt-injection twins.

Files:
    constants.py   the fixed vocabulary: corpus names, dimensions, classifications, alert names
    errors.py      the errors this package raises
    bands.py       the declared band scales and the substitution's one-step band shift
    fixtures.py    loading and verifying the pinned fixture set
    suite.py       `ConformanceSuite`: ingests each fixture and runs every backend over the set
    reports.py     the result and report types
    divergence.py  the recorded replay and the per-dimension divergence between two backends
    backends.py    backend builds and transports (recorded or live), and record promotion
    alerts.py      build-substitution detection and the alerts a report fires
    adversarial.py the adversarial tier
    decision.py    decision-engine conformance on the F-JEV fixtures
    injection.py   decision-engine robustness to prompt-injection twin pairs

Detailed design notes (the full original module description): `docs/code-notes/conform.md`.
"""

from __future__ import annotations

from .constants import (
    AGREEMENT_DIMENSION,
    ALERT_BUILD_SUBSTITUTION_DETECTED,
    ALERT_DIVERGENCE_GATE_CROSSED,
    CLASSIFICATION_BLOCKING,
    CLASSIFICATION_INFORMATIONAL,
    CLASSIFICATION_UNAVAILABLE,
    CONFIDENCE_DIMENSION,
    CONFORMANCE_ALERT_SURFACE,
    CONFORMANCE_BUDGET_SECONDS,
    CORPUS_NAME,
    DEFAULT_PIN_LABEL,
    DIVERGENCE_DIMENSIONS,
    EVIDENCE_INTEGRITY_DIMENSION,
    EXPECTED_CLASSIFICATION,
    FIXTURE_ROOT_ENV,
    GATE_DIMENSIONS,
    INFORMATIONAL_DIMENSIONS,
    INGEST_COHORT,
    LIVE_BACKENDS_ENV,
    LIVE_GATE_DIMENSION,
    MIN_SELF_AGREEMENT_REPEATS,
    OBSERVABILITY_FIELDS,
    PER_BACKEND_FIGURES_FIELD,
    PIPELINE_STAGES,
    RECORDED_FIXTURE_DISPATCH,
    REQUESTED_BUILDS_FIELD,
    RESOLVED_BUILDS_FIELD,
    SCORE_DISTRIBUTION_DIMENSION,
    SELF_AGREEMENT_DIMENSION,
    SELF_AGREEMENT_FIELD,
    SELF_AGREEMENT_REPEATS_FIELD,
    TEXT_SHORTCUT_STAGE,
    TRANSCRIPTION_DISPATCH_FIELD,
    UNAVAILABLE_GATE_DIMENSION,
    UNSTUBBABLE_STAGE,
    VLM_STAGE,
)
from .errors import ConformanceError, ConsentRefused, MergeRefused, StaleFixtureError
from . import bands  # noqa: F401  (imported for its registrations)
from .fixtures import FixtureSet, FixtureSubmission, load_fixture_set
from .reports import (
    AdversarialTierReport,
    BackendResult,
    BuildSubstitutionFinding,
    ConformanceAlert,
    ConformanceReport,
    DistributionReport,
    DivergenceReport,
    UnitOutcome,
    ValidationRecord,
)
from .divergence import (
    classify_divergence,
    DIVERGENCE_TOLERANCE_ENV,
    ESCALATION_THRESHOLD_ENV,
    induced_divergence,
    INDUCED_DIVERGENCE_ENV,
    silent_build_substitution,
)
from .backends import recorded_provider_for_fixture_set
from .alerts import detect_build_substitution, evaluate_conformance_alerts
from .adversarial import run_adversarial_tier
from .suite import build_conformance_suite, ConformanceSuite, IngestOutcome
from .decision import (
    DECISION_GATE_BIN,
    DECISION_REPORT_KEYS,
    DecisionCell,
    DecisionConformanceReport,
    F_JEV_CORPUS,
    load_f_jev_cells,
    run_decision_conformance,
)
from .injection import (
    decision_build_recommendation,
    DECISION_INJECTION_KEYS,
    DEFAULT_INJECTION_MARGIN,
    F_ADV_INJ_CORPUS,
    F_ADV_INJ_DECISION_CORPUS,
    INJECTION_DIRECTIONS,
    injection_flip_rate,
    INJECTION_MARGIN_ENV,
    _injection_pairs_from,
    injection_robust,
    InjectionPair,
    InjectionRobustnessReport,
    load_decision_injection_pairs,
    NOT_RECOMMENDED,
    run_injection_robustness,
)
