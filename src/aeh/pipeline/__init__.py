"""M-PIPE: drives a run from start to finish by composing the other modules (design §3.19).

M-ORCH owns the work ledger and decides what is ready; M-PIPE supplies the stage doors it calls
(extraction, judging, deterministic scoring) and the hooks that run between stages: the
integrity check once a cell's extraction finishes, and aggregation once its verdicts are in.
When every criterion of a submission is scored, M-PIPE writes the narratives and computes the
grades. It also provides the `aeh` command line and the console's start/resume doors.

M-PIPE issues no SQL of its own and calls no model directly; everything goes through the
owning modules.

Files:
    settings.py         the pass-loop knobs
    results.py          `RunResult`, `StageTrace`, `RecoveryReport`, `CompositionFault`
    executor.py         `ProductionStageExecutor`, the real stage doors M-ORCH calls
    decision_engine.py  run-level decision-engine setup and its outcome summary
    hooks.py            the integrity and aggregation hooks run between stages
    finishing.py        narrative synthesis and grading once a submission is fully scored
    driver.py           `run_to_completion` and `recover`
    runtime.py          opening the store and choosing a run's provider
    background.py       the console's doors: start or resume runs on worker threads, uploads
    cli.py              the `aeh` command line (`main`)
"""

from __future__ import annotations

# Imported for what importing them does: each registers its migrations and statements.
import aeh.agg  # noqa: F401
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401

from aeh.agg import aggregate, should_escalate, write_score
from aeh.extract import ExtractionWorker
from aeh.judge import verdicts_for

from .settings import MAX_PASSES_ENV, PASS_SLEEP_MS_ENV, STALL_PASSES
from .results import CompositionFault, RecoveryReport, RunResult, StageTrace
from .executor import ProductionStageExecutor
from . import decision_engine  # noqa: F401  (imported for its registrations)
from .hooks import _aggregate_hook, _integrity_pre_hook
from . import finishing  # noqa: F401  (imported for its registrations)
from .driver import recover, run_to_completion
from .runtime import _provider_for
from .background import (
    record_upload,
    resume_runs_in_background,
    RunAlreadyStartedError,
    start_run_in_background,
    uploaded_parts,
)
from .cli import EXIT_ERROR, EXIT_OK, EXIT_PAUSED, main
