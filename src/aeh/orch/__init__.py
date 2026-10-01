"""M-ORCH: the run orchestrator and its work ledger (design §3.7).

A run grades one cohort against one package version with one frozen configuration. When a run
is created, M-ORCH enumerates its work units (an extraction unit per cell, then one scoring unit
per judge) into the ledger in the cohort's database. Each unit is identified by a content hash
of its inputs, so enumerating twice inserts nothing new.

Workers lease units, heartbeat while they work, and report completion or failure. Expired
leases are swept back to pending, and failed units are retried up to a limit and then
quarantined. The dispatch loop hands units out in dependency order within the run's frozen
concurrency and cost ceilings. Escalation widens a cell's judge panel, under a run-wide budget
and a per-criterion circuit breaker. Runs move through a declared state machine (pending,
running, paused, complete), and every pause records its reason.

Files:
    constants.py        stage names and fixed ledger values
    work_units.py       `WorkUnit`, its provenance, and `compute_work_id`
    errors.py           the errors this package raises
    schema.py           the cohort-tier migrations M-ORCH contributes
    statements.py       the SQL statements M-ORCH runs
    settings.py         leases, attempts, budgets, breakers and other knobs
    run_records.py      the run's frozen panel and engine records, and the run-start audit record
    alerts.py           the run alerts and when they fire
    escalation_policy.py  escalation plans, the random arm, the breaker and budget admission
    reports.py          the reports M-ORCH returns (progress, enumeration, escalation, sweeps)
    package_checks.py   checks on a package version before a run uses it
    executors.py        the stage-executor seam, the governed provider and run handles
    run_lifecycle.py    creating, starting, pausing, resuming and completing runs
    costs.py            cost estimates and the cost ceiling
    enumeration.py      enumerating a run's work units and tracing their provenance
    leasing.py          leasing, heartbeats, the expiry sweep, completion and failure
    escalation.py       enqueuing escalations and replacement arms
    dispatch.py         the dispatch pass and the model-call batch
    composition.py      the cell phases and ready cells the composition layer (M-PIPE) reads
    reporting.py        progress reports, alerts and the run metrics
    orchestrator.py     `Orchestrator`

Detailed design notes (the full original module description): `docs/code-notes/orch.md`.
"""

from __future__ import annotations

from typing import Any
# Imported for what importing them does: each registers its migrations and statements.
import aeh.ingest  # noqa: F401 — the admission read's schema dependency

from aeh.store import store_metrics

from .constants import (
    EXTRACTOR_VERSION,
    SCORING_MODEL_BASE_DEPTH,
    STAGE_DETERMINISTIC,
    STAGE_EXTRACT,
    STAGE_SCORE,
    SWEEP1_ADMITTED_INGEST_STATUSES,
)
from .work_units import compute_work_id, UnitProvenance, WORK_ID_INPUTS, WorkUnit
from .errors import (
    BrokenLineageError,
    CellPhaseError,
    EscalationPlanError,
    EvenEscalationPlanError,
    RunNotFoundError,
    RunStateError,
    WorkLedgerError,
)
from . import schema  # noqa: F401  (imported for its registrations)
from .statements import ORCH_STATEMENTS
from .settings import (
    BACKEND_EDGE_LOCAL,
    BACKPRESSURE_DIVISOR_DEFAULT,
    BACKPRESSURE_DIVISOR_ENV,
    CACHE_COLLAPSE_FLOOR_DEFAULT,
    CACHE_COLLAPSE_FLOOR_ENV,
    CACHE_COLLAPSE_MIN_HISTORY_DEFAULT,
    CACHE_COLLAPSE_MIN_HISTORY_ENV,
    CACHE_COLLAPSE_SIGMA_DEFAULT,
    CACHE_COLLAPSE_SIGMA_ENV,
    CONCURRENCY_REDUCTION_DEFAULT,
    CONCURRENCY_REDUCTION_ENV,
    COST_WARNING_FRACTION_DEFAULT,
    COST_WARNING_FRACTION_ENV,
    CRITERION_BREAKER_MIN_N_ENV,
    CRITERION_BREAKER_RATE_ENV,
    DECISION_TOKENS_PER_SEAT_DEFAULT,
    DECISION_TOKENS_PER_SEAT_ENV,
    DISPATCH_OWNER,
    DISPATCH_WALK_BATCH_DEFAULT,
    DISPATCH_WALK_BATCH_ENV,
    ENUM_COMMIT_BATCH_DEFAULT,
    ENUM_COMMIT_BATCH_ENV,
    _env_float,
    _env_int,
    ESCALATION_BUDGET_ENV,
    JUDGE_DECISION_TEMPLATE_V,
    LEASE_SECONDS_ENV,
    MAX_ATTEMPTS_ENV,
    OOM_DROP_THRESHOLD_DEFAULT,
    OOM_DROP_THRESHOLD_ENV,
    ORCH_CRITERION_BREAKER_MIN_N,
    ORCH_CRITERION_BREAKER_RATE,
    ORCH_ESCALATION_BUDGET,
    ORCH_LEASE_SECONDS,
    ORCH_MAX_ATTEMPTS,
    ORCH_RANDOM_ARM_RATE,
    RANDOM_ARM_RATE_ENV,
)
from .run_records import (
    decision_engine_record,
    default_package_id_for,
    panel_config_json,
    record_run_start,
)
from .alerts import (
    ALERT_CACHE_COLLAPSE,
    ALERT_COST_NEAR_CEILING,
    ALERT_CRITERION_BREAKER,
    ALERT_ESCALATION_RATE,
    ALERT_RUN_PAUSED,
    evaluate_alerts,
    paused_milliseconds,
    RUN_ALERT_NAMES,
    RunAlert,
)
from .escalation_policy import (
    AdmissionPlan,
    admit_escalations,
    criterion_breaker_tripped,
    ESCALATION_ARM_PREFIX,
    escalation_plan,
    _extension_arms,
    _judge_id_of,
    random_arm_selection,
    run_random_arm_seed,
    validate_escalation_plan,
)
from .reports import (
    BreakerTrip,
    DECISION_ADMITTED,
    DECISION_HALTED_BY_BREAKER,
    EnumerationReport,
    EscalationBudgetState,
    EscalationReport,
    estimated_completion_seconds,
    PROGRESS_EXTRA_FIELDS,
    ProgressReport,
    REPLACEMENT_ALREADY_REQUESTED,
    REPLACEMENT_INSERTED,
    REPLACEMENT_NOT_APPLICABLE,
    REPLACEMENT_REFUSED,
    ReplacementArmReport,
    SweeperReport,
    SweepPlan,
    WorkError,
    WorkResult,
)
from .package_checks import _cohort_keys_on_filesystem, validate_grade_policy
from .executors import (
    CELL_PHASES,
    CellKey,
    GovernedProvider,
    PackageCatalogProtocol,
    READY_HOOKS,
    RunHandle,
    StageExecutor,
    StageOutcome,
    TransportStageExecutor,
)
from .run_lifecycle import RunLifecycleMixin
from .costs import CostsMixin
from .enumeration import EnumerationMixin
from .leasing import LeasingMixin
from .escalation import EscalationMixin
from .dispatch import DispatchMixin
from .composition import CompositionMixin
from .reporting import ReportingMixin
from .orchestrator import Orchestrator



# `#118`'s export seam reads the headless driver as `aeh.orch.run_pipeline_for_test` —
# the *run pipeline* operation from the orchestrator's namespace, which is how the
# stats vocabulary documents the seam and how `CT-STATS-C17` resolves it. The
# implementation lives in `aeh.console`, which imports `aeh.orch` at module top-level;
# a top-level import the other way round would be a cycle. PEP 562's module-level
# `__getattr__` forwards the one name lazily — the import happens at first access, when
# both modules are fully initialized — and every other missing name still raises
# `AttributeError` exactly as before, so no new module surface is implied.
def __getattr__(name: str) -> Any:
    if name == "run_pipeline_for_test":
        from aeh import console

        return console.run_pipeline_for_test
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
