"""M-CONSOLE: the teacher and operator console (design §3.19, HLD §11).

The console is a read view over the stores plus a fixed set of control actions. It renders
thirteen screens (setup, upload, run monitor, quarantine, review queue, blind sample, rollup,
student view, export gate and others) as plain HTML, served on the loopback interface only.
It owns no pipeline state: every write is one of the enumerated control actions, and each
action writes through the module that owns the data (M-SETUP, M-GRADE, M-REVIEW, M-PKG,
M-PIPE). A screen whose read fails says so instead of showing an empty result. Everything the
console does can also be driven headlessly from code (`ConsoleApp`, `run_pipeline_for_test`).

Files:
    settings.py         bind address, port, budgets and knobs
    routes.py           the screens and their routes
    vocabulary.py       control actions, write fields, states and the fixed wording
    queries.py          the read queries the screens run
    errors.py           the errors this package raises
    html.py             small HTML building blocks and the stylesheet
    provenance.py       the provenance line under a grade
    setup_prompts.py    the setup steps rendered as skippable prompts
    records.py          rendered pages, outcomes, queue items and reports
    write_rows.py       the rows each control action writes
    surfaces.py         module-level renderers: catalog, preflight, calibration, agreement
    grade_rendering.py  a grade with its coverage, boundary risk and figures
    review_rendering.py the review queue's markup
    blind_flow.py       the blind-sample flow as the console serves it
    uploads.py          the upload handler
    app_reads.py        the app's store reads
    screens.py          rendering a route: the screen dispatcher and common parts
    setup_screens.py    the setup screens (inventory, answer keys)
    run_screens.py      the upload, run monitor and quarantine screens
    results_screens.py  the rollup, student, key-correction and export-gate screens
    queues.py           the review and quarantine queues
    controls.py         the control actions and their row writes
    effects.py          what each domain-effect action does
    key_correction.py   correcting an answer key and re-deriving scores
    views.py            progress, telemetry, validation record, scores and grade reads
    grade_actions.py    amending a grade, the gate outcome and the review window
    app.py              `ConsoleApp`, the console as a headless object
    server.py           the HTTP server and its request handler
    run_planning.py     building a console and planning runs
    queue_renderers.py  the review queue rendered at module level
    driver.py           `run_pipeline_for_test`, the headless end-to-end driver

Detailed design notes (the full original module description): `docs/code-notes/console.md`.
"""

from __future__ import annotations

# Imported for what importing them does: each registers its migrations and statements.
import aeh.agg  # noqa: E402,F401
import aeh.det  # noqa: E402,F401
import aeh.extract  # noqa: E402,F401
import aeh.grade  # noqa: E402,F401
import aeh.ingest  # noqa: E402,F401
import aeh.integ  # noqa: E402,F401
import aeh.judge  # noqa: E402,F401
import aeh.orch  # noqa: E402,F401
import aeh.pkg  # noqa: E402,F401
import aeh.synth  # noqa: E402,F401

from aeh.review import BLIND_SAMPLE_RANGE, REVIEW_DEFAULT_BANDS

from .settings import (
    blind_reserve_minutes,
    CONSOLE_BIND,
    CONSOLE_POLL_INTERVAL_MS,
    CONSOLE_PORT,
    CONTROL_ACTION_METRIC,
    HANDLER_BUDGET_SECONDS,
    headless_batch_size,
    MEMORY_FLOOR_BYTES,
    OBSERVABILITY_METRICS,
    REFERENCE_COHORT_SIZE,
    RENDER_TIME_METRIC,
    REVIEW_BUDGET_METRIC,
    REVIEW_QUEUE_BUDGET_SECONDS,
    ROLLUP_BUDGET_SECONDS,
    ROUTABLE_BIND,
    SKIP_RATE_METRIC,
    upload_chunk_bytes,
    UPLOAD_RSS_RATIO_CEILING,
)
from .routes import (
    AUDIT_ROUTES,
    BLOCKING_SCREENS,
    CLOUD_HOSTED_PROFILE,
    LOOPBACK_ADDRESSES,
    OPERATOR_ROUTES,
    OPERATOR_SCREENS,
    REPLAY_ROUTES,
    SCREENS,
    SETUP_STEP_SCREENS,
    TEACHER_ROUTES,
)
from .vocabulary import (
    CALIBRATION_ARRIVES_IN,
    CONSOLE_WRITE_FIELDS,
    CONTROL_SURFACE_ACTIONS,
    NO_NEW_VALIDATION_EVIDENCE,
    NO_VALIDATION_FOR_POPULATION,
    OPTIONAL_SETUP_STEPS,
    PRE_LOCK_ACTIONS,
    QUARANTINE_STATES,
    REVIEW_BANDS,
    STANDING_AGREEMENT_FIGURE,
)
from . import queries  # noqa: F401  (imported for its registrations)
from .errors import ConsoleBindRefused, ConsoleReadError, ProvenanceRefused
from .html import n_value
from .provenance import GRADE_PROVENANCE
from .setup_prompts import render_setup_step
from .records import (
    CalibrationRender,
    ControlOutcome,
    ExportOutcome,
    GradeRecord,
    PipelineOutcome,
    PreflightView,
    ProgressReport,
    QuarantineItem,
    QueueContents,
    QueueView,
    RenderedPage,
    ReviewQueueItem,
    RunPlan,
    ScorePresentation,
    TouchpointRender,
    UploadOutcome,
    ValidationRecord,
)
from . import write_rows  # noqa: F401  (imported for its registrations)
from .surfaces import (
    amend_finalized_grade,
    export_package,
    MVP_ABSENT_TOUCHPOINT,
    render_agreement_block,
    render_calibration_surface,
    render_conformance_surface,
    render_discovery,
    render_gate_result,
    render_package_catalog,
    render_preflight,
    render_rollup,
    render_submission_text,
    TEACHER_TOUCHPOINT_ROUTES,
    TOO_FEW_QUALIFIER,
    touchpoint_surface,
)
from .grade_rendering import render_grade_coverage
from . import review_rendering  # noqa: F401  (imported for its registrations)
from .blind_flow import blind_flow, blind_flow_requests, BlindFlowRequest, BlindFlowView
from .uploads import _chunk_ref, upload_scans
from .app_reads import StoreReadsMixin
from .screens import ScreenRenderingMixin
from .setup_screens import SetupScreensMixin
from .run_screens import RunScreensMixin
from .results_screens import ResultsScreensMixin
from .queues import QueuesMixin
from .controls import ControlActionsMixin
from .effects import DomainEffectsMixin
from .key_correction import KeyCorrectionMixin
from .views import ReadViewsMixin
from .grade_actions import GradeActionsMixin
from .app import ConsoleApp
from .server import (
    _ConsoleRequestHandler,
    ConsoleServer,
    CONTROL_ACTION_SLUGS,
    serve_console,
    start_console,
)
from .run_planning import build_console, retry_run, start_run
from .queue_renderers import render_review_queue, review_queue_header
from .driver import run_pipeline_for_test


__all__ = [
    "TOO_FEW_QUALIFIER",
    "BLIND_SAMPLE_RANGE",
    "CONSOLE_BIND",
    "CONSOLE_PORT",
    "CONSOLE_POLL_INTERVAL_MS",
    "BlindFlowRequest",
    "BlindFlowView",
    "CalibrationRender",
    "ConsoleApp",
    "ConsoleBindRefused",
    "ControlOutcome",
    "ExportOutcome",
    "PipelineOutcome",
    "PreflightView",
    "ProvenanceRefused",
    "REVIEW_DEFAULT_BANDS",
    "RenderedPage",
    "RunPlan",
    "TouchpointRender",
    "UploadOutcome",
    "amend_finalized_grade",
    "blind_flow",
    "blind_flow_requests",
    "build_console",
    "export_package",
    "render_agreement_block",
    "render_calibration_surface",
    "render_conformance_surface",
    "render_discovery",
    "render_gate_result",
    "render_grade_coverage",
    "render_package_catalog",
    "render_preflight",
    "render_review_queue",
    "render_rollup",
    "render_setup_step",
    "render_submission_text",
    "review_queue_header",
    "retry_run",
    "run_pipeline_for_test",
    "serve_console",
    "start_console",
    "touchpoint_surface",
    "upload_scans",
]
