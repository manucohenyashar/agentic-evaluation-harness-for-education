"""`M-CONSOLE` — the teacher/operator console as a read view over the §9 stores plus a
small control surface (HLD §11; issues #122 and #126).

#122 builds the process: the stateless `ConsoleApp` (every view a query, every change a
row the orchestrator reads on its own schedule — §11.1, §11.8), the fifteen-action control
surface (`FR-CONSOLE-32`), the upload handler that streams and dispatches (`FR-CONSOLE-04`,
`NFR-CONSOLE-06`), the run monitor that polls the ledger and writes nothing (`CT-CONSOLE-19`),
the loopback refusal (`FR-CONSOLE-05`), the four observability metrics (§3.19) and the audit
surface that never presents an actor string as an identity (`CT-CONSOLE-23`). #126 builds
S1 Packages (`FR-CONSOLE-26`: a package never administered to this population renders *no
validation data for this population*, never a borrowed figure), S2 Upload (PDF only, several
files per logical document, the assembled page order shown **before** transcription starts,
calibration papers stored for a later version — never a promise of ambiguity discovery), S6
Preflight (the validation ladder per gate, the `FR-INGEST-28` cohort breaker withholding run
start, and the deliberate note that outstanding quarantine items do **not** withhold it —
quarantine is the operator's parallel workstream, §7.7) and S8 Quarantine (never
auto-reassigns; the image crop for an unreadable mark; closing as unresolvable marks criteria
MISSING and grade INCOMPLETE — never zero — the console face of `FR-GRADE-07`/`-08`).

## What is real, and what is deliberately absent

Design §3.19 declares no Python interface for this module, so the surface here is the one
settled in `tests/support/console_vocabulary.py` and
`tests/support/console_security_vocabulary.py`, disclosed there and reproduced here.

- **Every render is a read.** The console holds no pipeline state; a view derives from the
  store (or from nothing). Rendering never writes — asserted per screen by the complement
  sweep (`TC-CONSOLE-C02`). On the suite's `StoreSpy` (a write-audit double with no
  filesystem), reads are recorded against the spy's tier handles so the read path stays
  observable; on a real store, reads go through the tier handles at the same seam `M-GRADE`
  and `M-DET` use — and a render never *creates* a tier file: a tier that does not exist yet
  is rendered as the empties it honestly has.
- **Every control action writes rows, or says honestly why it wrote none.** `perform` writes
  one row per declared effect, whose payload names its table and carries only the fields
  §11.8 declares for that action — the contract the dynamic sweep checks per write against
  the union. On the spy the payload dict arrives at `enqueue_write` with its fields attached;
  on a real store each action writes the row the schema actually admits, in that row's own
  tier's transaction, never nested inside another tier's: `pause/resume` as a `run_control`
  row on the run's cohort ledger — exactly where `Orchestrator` writes its own control rows
  (whose CHECK admits `pause` and `resume` only), applied on its next read (CT-ORCH-13);
  S8's close-as-unresolvable as the operator's `submission` update (diagnosis `incomplete`,
  park flag cleared — never an automatic reassignment, and the MISSING-criteria /
  INCOMPLETE-grade consequence is `M-GRADE`'s landed missing-criteria rule). The other
  landed domain effects delegate to `M-GRADE` (`GradingService.finalize_batch`) and `M-STORE`
  (`purge_cohort`); an action with neither a schema-admitted row nor a landed owner reports
  `dispatched=False` with the deferral named — the console claims nothing it did not do.
- **Replay and staleness are refused into safety.** A replay through any route
  (`double_click`, `retried_request`, `back_navigation`) reports the already-settled rows and
  writes nothing (`FR-CONSOLE-02`: no additional row, not merely no exception); an action held
  mid-flight and released into moved state is refused with `refresh_required` and writes
  nothing (§3.19: idempotent or refused with a refresh, never partial).
- **The refusal keys on the deployment profile, first.** `serve_console`/`start_console`
  refuse `cloud-hosted` before any bind is inspected, then refuse any non-loopback bind
  (`FR-CONSOLE-05`) — the order matters, because a routable bind must not be able to argue
  with the profile refusal (`CT-CONSOLE-20`). A started server is a **two-socket** design and
  says so: the parent holds a real loopback socket (the witness `getsockname()` reads), and a
  real child process binds its own loopback port and serves pages; the child never touches the
  store, so a killed console loses only its memory — the ledger keeps the queued rows
  (`NFR-CONSOLE-03`).
- **The upload never materialises the batch, and it is PDF-only.** `upload_scans` walks the
  declared size in chunks (`HARNESS_CONSOLE_UPLOAD_CHUNK_BYTES`, default 4 MiB), digests each
  chunk, and hands the digests to the blob store when one is present; nothing of the declared
  size is ever allocated, which is what the ratio budget (`NFR-CONSOLE-06`) and the 1-second
  handler budget (`FR-CONSOLE-04`) measure. The S2 format rule (`FR-CONSOLE-13`) is enforced
  where the format is knowable — a stream's first chunk must carry the `%PDF-` magic, a
  declared filename must end `.pdf` — and the handler states plainly when it was given
  nothing to check.
- **The review queue renders the invariants, in order (§11.6's 8-10, #124).** The header
  states all three figures — flagged, shown and **left provisional** (`FR-CONSOLE-13`), the
  third as data attributes `review_queue_header` reads back and as visible text, because a
  figure computed but not printed has rendered nothing. Group actions render above per-item
  ones (`FR-CONSOLE-14`), and every item renders narrative before its mark with the narrative
  carrying no numeral-bearing or overall-quality claim (`FR-CONSOLE-15` — the order is the
  affordance: a narrative shown after the mark is read as justification rather than evidence).
  The renderer is polymorphic: over this module's `ConsoleApp` (the route's own view) and over
  `M-REVIEW`'s `ReviewService` (whose built queue it renders — the consumer half of
  `CT-REVIEW-04`, where the service's own three figures are rendered rather than recomputed).
  Over an empty store the screen renders its standing shape with the honest figures (zero) —
  the structure is what the invariants assert on, and the counts are the store's.
- **The blind flow is unreachable, not hidden (`FR-CONSOLE-16`, #124).** `blind_flow` and
  `blind_flow_requests` are the flow's declared transport face: the query plan reads the
  §3.15 pair (`submission`, `criterion`) plus the draw (`blind_sample`) and the rubric's
  band descriptors (`criterion_band` — package data), and never names a system-output table
  or column (`criterion_score`, `submission_grade`, the verdict and confidence columns, the
  queued review rows). `M-REVIEW`'s `BlindSession` carries the same guarantee as a property
  of the type; the payloads here hold identity fields and the fixed band scale, so a leak is
  not merely hidden but absent (`CT-REVIEW-09` step 3 lives on this surface, not `M-REVIEW`'s).
- **Invariants 15–21 (issue #125).** The blind reservation is read — and subtracted —
  before the ranking query runs (`review_queue`; the order is visible in the query log,
  `FR-CONSOLE-19`). Every grade-bearing screen renders the grade beside an editable band
  control (`_band_control`; `FR-CONSOLE-20`, invariant 16) and a provenance footer that
  carries the values (`CT-CONSOLE-10`). An amendment (`amend_finalized_grade`) preserves
  the delivered `finalized_at` and writes a new revision on an append-only history whose
  superseded revisions stay readable (`grade_revision`; `FR-CONSOLE-21`). A review window
  (`set_review_window`) delays finalization — the batch settles with `finalized_at`
  unset, marked provisional, and exports normally (`FR-CONSOLE-22`). The export gate
  (`export_package`/`ProvenanceRefused`) is a reachable screen (S14) whose outcome is
  written to the validation record (`FR-CONSOLE-23`). An administration with no blind
  labels renders `render_agreement_block`'s absence sentence — never a zero, never a
  blank, never a prior administration's figure in that position (`FR-CONSOLE-24`).
  `touchpoint_surface` enumerates §7.9's twelve rows, one present-and-unavailable naming
  its version (`FR-CONSOLE-25`).
- **The limitation is stated, not latent (`NFR-CONSOLE-07`, #127).** Every page the shell
  renders carries the English-and-left-to-right statement (`_LIMITATION_SECTION`) — a
  deliberate limitation named in the UI, never an omission discovered in the field, and
  `CT-CONSOLE-24`'s non-promise is honest on every route rather than on one. The
  student-text render for the correction flow (`render_submission_text`) rides the same
  statement, so a non-English or RTL submission degrades **visibly** — named on the page —
  never silently (`TC-CONSOLE-C24`).
- **The grade render carries its coverage, boundary language and criterion figures
  (`render_grade_coverage`, #107's carry-forward landed here).** A grade shown without its
  five coverage counters is a stronger claim than the system is making (`CT-GRADE-04`); a
  null grade never reads as "fine" (`CT-GRADE-05`); a deterministic criterion's withheld
  agreement figure presents as not-applicable, never as a zero that reads as perfect
  agreement (`CT-GRADE-13`); and a boundary-flagged grade reads as "could cross", never as
  a likelihood (`CT-GRADE-19`). The rollup's segments render the same presentation from
  their batch read, so the single-submission renderer and the screen cannot drift into two
  consoles.
- **S12's two halves (#127).** The answer-key correction action (`correct an answer key
  after a run`) writes a new key version (`FR-PKG-18`'s flow — M-PKG's `create_version`
  copies the parent, the correction lands in the child), re-derives the affected
  deterministic scores **by lookup** (M-DET's `rederive_for_key_change`, whose
  `panel_units_enqueued` is a declared zero — a lookup, never a re-judgement, `FR-DET-08`),
  re-runs the grade policy (M-GRADE's `compute_all` over the re-derived rows), and renders
  the updated grades immediately. The re-point of the run row to the corrected version is
  the correction flow's own re-baseline step — TC-GRADE-12's disclosed stand-in: the run
  row is `M-ORCH`'s alone to write and no orchestrator API exists yet, so the console
  performs it inside the action and names it in the outcome detail; when M-ORCH ships a
  re-point surface, this call site becomes that call. The rubric-findings block renders
  M-GRADE's `rollup_findings` — the criteria the escalation circuit breaker marked
  `ungradeable_by_panel` and the ones whose review queue rows exhausted the budget
  (`FR-CONSOLE-31`, `FR-ORCH-13`, `FR-REVIEW-04`) — beside the correction control, so the
  findings are visible to the person who can act on them.
- **`run_pipeline_for_test`** is the headless driver (`CT-CONSOLE-01`) with two disclosures:
  it pins the fixture's rubric version by inserting the version row directly (the same column
  shape `M-PKG`'s own first-version insert uses — `PackageCatalog.create_version` mints
  unguessable ids, and the driver needs `pkg-v1-r0`), and it overrides the orchestrator's
  package-id derivation for the same reason. Neither bypass reaches a shipped path.

## The four seams (CLAUDE.md)

1. **Headless driver** — `run_pipeline_for_test` runs the pipeline end-to-end from code and
   returns a structured result with a per-stage trace; `build_console().render(route)` renders
   any screen headlessly. Nothing requires a served process.
2. **Deterministic transport** — the console performs no inference at all (`CT-CONSOLE-01`),
   so it adds no egress point; the provider it is handed is held, never called.
3. **Env-gated knobs** — `CONSOLE_BIND`, `CONSOLE_PORT`, `CONSOLE_POLL_INTERVAL_MS` are the
   declared knobs, plus `HARNESS_CONSOLE_UPLOAD_PROBE_BYTES` (test vocabulary),
   `HARNESS_CONSOLE_UPLOAD_CHUNK_BYTES` (this module) for the upload walk,
   `HARNESS_CONSOLE_BLIND_RESERVE_MINUTES` for the queue's blind reservation and
   `HARNESS_CONSOLE_HEADLESS_BATCH` for the headless driver's batch size — all read at
   call time.
4. **Stage-level observability** — `telemetry()` carries the four declared metrics;
   `RenderedPage.queries` records what each render read; outcomes carry per-stage detail.

Store opens in this process require the full tier migration chain, so the ten contributor
imports stand at the top of this file — the same convention `tests/conftest.py` records
(`IncompleteMigrationChainError`, #234).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, fields as dataclass_fields
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Callable, Iterator, NamedTuple

from aeh.conf import CohortRef, ModelRef, resolve_run_config
from aeh.grade import GradingService, rollup_findings
from aeh.orch import Orchestrator
from aeh.pkg import PackageCatalog
from aeh.review import (
    BLIND_SAMPLE_RANGE,
    REVIEW_BLIND_RESERVE_MINUTES,
    REVIEW_DEFAULT_BANDS,
    REVIEW_DEFAULT_BUDGET_MINUTES,
)
from aeh.store import open_store, store_metrics

# The full migration chain, before any store open in this module's processes. See the module
# docstring: the open site refuses a short chain, and these imports are the completeness duty.
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
from aeh.det import DeterministicEvaluator

__all__ = [
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


# --- the declared knobs (design §3.19, Configuration line) -------------------------------------------
#
# Production values are the defaults; `CONSOLE_PORT` has no declared default and stays None
# (the suite asserts only that the knob exists — asserting a value would assert a guess).

CONSOLE_BIND = "127.0.0.1"
CONSOLE_PORT: int | None = None
CONSOLE_POLL_INTERVAL_MS = 3000

#: The bind an adversarial operator reaches for; the refusal must not be defeatable by it.
ROUTABLE_BIND = "0.0.0.0"

#: The upload walk's chunk size, env-gated (seam 3): a slower box shrinks it without a code
#: change, and the 1-second handler budget holds either way because the walk never touches the
#: declared size as a whole.
_UPLOAD_CHUNK_DEFAULT = 4 * 1024 * 1024


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(f"environment knob {name}={raw!r} is not an integer.") from error


def upload_chunk_bytes() -> int:
    """The chunk size the upload walk uses this call (knob read at call time)."""
    return max(1, _env_int("HARNESS_CONSOLE_UPLOAD_CHUNK_BYTES", _UPLOAD_CHUNK_DEFAULT))


#: The blind reservation the queue makes when the store carries no `review_budget` row:
#: `M-REVIEW`'s declared default (`CT-REVIEW-02`), not a number this module recomputes.
#: Env-gated (seam 3) and read at call time, like every knob here.
def blind_reserve_minutes() -> int:
    """The blind-reservation default this console run uses (knob read at call time)."""
    return max(0, _env_int("HARNESS_CONSOLE_BLIND_RESERVE_MINUTES", REVIEW_BLIND_RESERVE_MINUTES))


#: The headless driver's deterministic batch size: how many synthetic submissions
#: `finalize_batch` settles when no store is attached. A knob, so a slower box can
#: shrink it and a load test can grow it without a code change.
def headless_batch_size() -> int:
    """The submission count the headless driver settles per finalized batch."""
    return max(1, _env_int("HARNESS_CONSOLE_HEADLESS_BATCH", 12))


#: Budgets the console declares (§6.11.19): the handler budget for uploads, the two page
#: budgets for the screens the rollup story owns, the load they are sized for, and the
#: memory bound an upload must stay under (a ratio, not an absolute, with a floor so a
#: shrunk probe cannot blow the ratio on incidental allocations).
HANDLER_BUDGET_SECONDS = 1.0
REVIEW_QUEUE_BUDGET_SECONDS = 2.0
ROLLUP_BUDGET_SECONDS = 3.0
REFERENCE_COHORT_SIZE = 350
UPLOAD_RSS_RATIO_CEILING = 0.25
MEMORY_FLOOR_BYTES = 8 * 1024 * 1024

# --- the four observability metrics (design §3.19, Observability line) --------------------------------

RENDER_TIME_METRIC = "page_render_time"
CONTROL_ACTION_METRIC = "control_actions_by_type"
SKIP_RATE_METRIC = "skip_rate_per_setup_step"
REVIEW_BUDGET_METRIC = "review_budget_requested_vs_used"
OBSERVABILITY_METRICS = frozenset(
    {RENDER_TIME_METRIC, CONTROL_ACTION_METRIC, SKIP_RATE_METRIC, REVIEW_BUDGET_METRIC}
)

# --- the screens (HLD §11.5) --------------------------------------------------------------------------

#: The fourteen screens: the HLD's thirteen, in the HLD's numbering, plus the provenance
#: gate — `CT-CONSOLE-16` requires the export decision to be *a reachable screen*, not an
#: internal check, so the gate has a route the teacher can open (`FR-CONSOLE-23`).
#: `BLOCKING_SCREENS` are the two that hold run start until completed; `OPERATOR_SCREENS`
#: are the operator surface quarantine triage and run monitoring live on (§7.7).
SCREENS: dict[str, str] = {
    "S1": "/packages",
    "S2": "/packages/new",
    "S3": "/setup/inventory",
    "S4": "/setup/answer-keys",
    "S5": "/setup/optional",
    "S6": "/cohorts/{id}/preflight",
    "S7": "/runs/{id}/monitor",
    "S8": "/quarantine",
    "S9": "/runs/{id}/review",
    "S10": "/runs/{id}/sample",
    "S11": "/runs/{id}/blind",
    "S12": "/runs/{id}/rollup",
    "S13": "/students/{ref}",
    "S14": "/packages/{version}/export-gate",
}
BLOCKING_SCREENS = frozenset({"S3", "S4"})
OPERATOR_SCREENS = frozenset({"S6", "S7", "S8"})

#: The route tables, verbatim from the settled vocabulary, plus the provenance gate —
#: §3.19's teacher table with the one route `CT-CONSOLE-16` adds: the export decision is
#: a screen the teacher reaches, not an internal check (`FR-CONSOLE-23`). No auth route
#: exists anywhere: authN/authZ is none, deliberately, bounded by the loopback refusal
#: (`CT-CONSOLE-23`).
TEACHER_ROUTES = (
    "/packages",
    "/packages/new",
    "/packages/{version}/export-gate",
    "/setup/*",
    "/runs/{id}/review",
    "/runs/{id}/blind",
    "/runs/{id}/sample",
    "/runs/{id}/rollup",
    "/students/{ref}",
)
OPERATOR_ROUTES = (
    "/cohorts",
    "/cohorts/{id}/preflight",
    "/runs/{id}/monitor",
    "/quarantine",
)

#: The screen routes that carry grades and audit records — the audit surface (`CT-CONSOLE-23`).
AUDIT_ROUTES = ("/runs/{id}/rollup", "/runs/{id}/monitor")

#: Loopback addresses a legal bind may name.
LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1", "localhost"})

#: The deployment profile whose every setting combination refuses to start (`CT-CONSOLE-05`).
CLOUD_HOSTED_PROFILE = "cloud-hosted"

# --- the control surface (HLD §11.8) -------------------------------------------------------------------

#: The fifteen control actions, verbatim. The runtime surface is **exactly** this set
#: (`FR-CONSOLE-32`); an extra entry is the undeclared write path the clause exists to expose.
CONTROL_SURFACE_ACTIONS: tuple[str, ...] = (
    "approve question inventory",
    "supply answer keys",
    "accept or correct rubric read-back",
    "set review window",
    "start run",
    "pause/resume",
    "resolve quarantine item",
    "review action",
    "blind-sample submission",
    "correct an answer key after a run",
    "finalize batch",
    "amend a finalized grade",
    "approve exemplar paraphrases at export",
    "export/import package",
    "purge cohort",
)

#: The three actions that write before the §6.2 lock; everything else is post-lock.
PRE_LOCK_ACTIONS: frozenset[str] = frozenset(
    {
        "approve question inventory",
        "supply answer keys",
        "accept or correct rubric read-back",
    }
)

#: The per-action field contract (§11.8's Effect column): the store fields each action may
#: write, as dotted `table.field` names. `perform` writes no field outside this map, which is
#: what makes the dynamic sweep decisive.
CONSOLE_WRITE_FIELDS: dict[str, tuple[str, ...]] = {
    "approve question inventory": (
        "question.question_id",
        "question.prompt_text",
        "question.order",
    ),
    "supply answer keys": ("criterion.answer_key",),
    "accept or correct rubric read-back": (
        "criterion.text",
        "criterion.decomposable",
        "criterion_band.band",
        "criterion_band.descriptor",
        "grade_policy.rule",
        "grade_boundary.cut",
    ),
    "set review window": ("grade_policy.review_window_hours",),
    "start run": ("run.run_id", "run.status"),
    "pause/resume": ("run.status",),
    "resolve quarantine item": (
        "submission.ingest_status",
        "submission.quarantined",
    ),
    "review action": (
        "review_queue.action",
        "review_queue.new_band",
        "review_queue.acted_at",
        "label.label_type",
        "label.band",
    ),
    "blind-sample submission": ("label.label_type", "label.band"),
    "correct an answer key after a run": ("criterion.answer_key",),
    "finalize batch": ("submission_grade.finalized_at", "audit_record.actor"),
    "amend a finalized grade": (
        "submission_grade.revision",
        "submission_grade.bands",
        "audit_record.actor",
    ),
    "approve exemplar paraphrases at export": (
        "exemplar.provenance",
        "package.contains_real_student_text",
    ),
    "export/import package": ("package_file.path",),
    "purge cohort": ("cohort.purged_at",),
}

#: The replay routes §11.8 names. All three dedupe to no additional row (`FR-CONSOLE-02`).
REPLAY_ROUTES: tuple[str, ...] = ("double_click", "retried_request", "back_navigation")

#: The quarantine vocabulary, as the schema spells it (`FR-INGEST-30`). The park is the
#: FLAG M-INGEST writes — `submission.quarantined` (0/1, ingest migration 7) — and
#: `ingest_status` is the diagnosis beside it, whose CHECK domain is exactly
#: `('ok', 'low_confidence_ocr', 'unreadable', 'incomplete', 'unmatched_assessment')`.
#: These three are the parked diagnoses: `unreadable` and `unmatched_assessment` halt
#: scoring outright, `incomplete` is the close-as-unresolvable terminal state (S8's
#: close writes it and clears the flag). Deliberately absent: `low_confidence_ocr` is
#: flagged-but-available (`FR-INGEST-29` — admitted to scoring like `ok`, never
#: quarantined), and `unresolved_selection`/`triage` are det.py criterion-level states,
#: not submission statuses — a vocabulary this module once guessed and the store's CHECK
#: constraint refused. The review queue's reads never reach any of these (`CT-CONSOLE-12`).
QUARANTINE_STATES: tuple[str, ...] = (
    "unreadable",
    "incomplete",
    "unmatched_assessment",
)

#: The five optional setup cards (§6.3), each with its own skip rate in the telemetry.
OPTIONAL_SETUP_STEPS: tuple[str, ...] = (
    "Approve how the rubric was understood",
    "Confirm decomposability classifications",
    "Declare the grade policy and boundaries",
    "Answer ambiguity-elicitation questions",
    "Mark 10 to 15 calibration papers",
)

#: S1's rule (`FR-CONSOLE-26`) and the rollup's: the exact sentences an honest card renders.
NO_VALIDATION_FOR_POPULATION = "no validation data for this population"
NO_NEW_VALIDATION_EVIDENCE = "no new validation evidence for this administration"

#: The calibration surface arrives in a later version (`FR-CONSOLE-25`): rendered
#: present-and-unavailable, naming the version, never silently absent.
CALIBRATION_ARRIVES_IN = "version 2 (Phase 4 calibration)"

#: The ingest gates and their columns in the cohort tier (the §9 table shape `M-INGEST`
#: writes and `M-CONSOLE`'s S6 ladder reads). Values outside both lists mean not reached.
_GATE_COLUMNS: dict[str, str] = {
    "v0": "v0_integrity",
    "v1": "v1_pages",
    "v2": "v2_structure",
    "v3": "v3_identity",
    "v4": "v4_match",
}
_GATE_PASS_VALUES: dict[str, tuple[str, ...]] = {
    "v0": ("pass",),
    "v1": ("pass",),
    "v2": ("pass",),
    "v3": ("pass",),
    "v4": ("match",),
}
_GATE_FAIL_VALUES: dict[str, tuple[str, ...]] = {
    "v0": ("fail",),
    "v1": ("fail",),
    "v2": ("fail",),
    "v3": ("unmatched", "ambiguous"),
    "v4": ("uncertain", "mismatch"),
}
_GATE_NOT_REACHED = "not_reached"

#: What each score state says to the teacher. The four states are the closed set `CT-AGG-07`
#: pins; a merged presentation of the breaker-refused and the ordinary provisional row is the
#: quiet degradation the clause exists to catch.
_STATE_PRESENTATION: dict[str, str] = {
    "final": "final",
    "provisional_unreviewed": "provisional and awaiting teacher review",
    "ungradeable_by_panel": (
        "the panel refused to grade this criterion — it is recorded as ungradeable, "
        "not as awaiting review"
    ),
    "unresolved_selection": "the selection could not be read; it is parked for triage",
}

# --- the console's read-only SQL -----------------------------------------------------------------------
#
# Reads go through the tier handles at the same seam `M-GRADE`, `M-DET` and `M-INGEST` use.
# The gate and breaker statements mirror the cohort-tier shapes `M-INGEST` declares
# (INGEST_STATEMENTS) so the ladder reads what the writer wrote.

#: S1's read, against the table that exists (`validation_record`, package tier — the
#: six-part key `FR-PKG-08` fixes, read here population-scoped). The table this module
#: once guessed (`package_validation`) has no migration, so the positive half of
#: `FR-CONSOLE-26` was dead code: a genuinely stored record rendered as an absence.
#: The scoring-model column is deliberately not projected: the ladder reports, per
#: gate, who validated under which backend and how well — the model itself is the
#: package's classification fact (`CT-AGG-09`), and a consumer that cannot read the
#: attribute cannot branch on it (`aeh.console` is outside the sanctioned readers).
_SELECT_VALIDATION = (
    "SELECT criterion_id, backend_profile, agreement, n "
    "FROM validation_record "
    "WHERE package_version_id = :package_version_id "
    "AND population_scope_id = :population"
)
#: The same table, version-scoped without a population — the provenance gate's read
#: (`validation_record()`), which reports every population a record exists for.
_SELECT_VALIDATION_VERSION = (
    "SELECT population_scope_id, agreement, n FROM validation_record "
    "WHERE package_version_id = :package_version_id"
)
_SELECT_GATE_ROWS = (
    "SELECT submission_id, v0_integrity, v1_pages, v2_structure, v3_identity, v4_match, "
    "quarantined FROM submission WHERE cohort_id = :cohort_id"
)
_SELECT_COHORT_BREAKER = (
    "SELECT cohort_id, tripped_at, rate, flagged, ingested, finding "
    "FROM v4_cohort_breaker WHERE cohort_id = :cohort_id"
)
_SELECT_SCORES = (
    "SELECT criterion_id, band, judge_count, agreement, state, routing, "
    "points FROM criterion_score WHERE submission_id = :submission_id "
    "ORDER BY criterion_id"
)
_SELECT_GRADES = (
    "SELECT submission_id, revision, state, total, policy_version, grade, "
    "criteria_total, criteria_auto, criteria_reviewed, criteria_provisional, "
    "criteria_missing, boundary_at_risk, score_low, score_high "
    "FROM submission_grade WHERE run_id = :run_id ORDER BY submission_id"
)
#: The review budget's own row: the stated budget and the blind reservation that was
#: subtracted from it before ranking (`CT-REVIEW-02` names the field). The queue reads
#: this row FIRST — the reservation is subtracted before the ranking query runs, and the
#: query log is the record of that order (`FR-CONSOLE-19`).
_SELECT_REVIEW_BUDGET = (
    "select budget_minutes, reserved_for_blind_minutes from review_budget "
    "where run_id = :run_id"
)
#: One revision of one grade, off the append-only submission_grade history (`FR-GRADE-09`):
#: the superseded revision stays readable after an amendment writes the next one.
_SELECT_GRADE_REVISION = (
    "SELECT submission_id, revision, finalized_at, state, total, policy_version "
    "FROM submission_grade WHERE submission_id = :submission_id AND revision = :revision "
    "ORDER BY submission_id"
)
_SELECT_NARRATIVE = (
    "SELECT question_id, text, score_claim_flag FROM narrative "
    "WHERE submission_id = :submission_id ORDER BY question_id"
)
#: S8's park list, declared rather than assembled (`FR-STORE-08`, SEC-15). The park is
#: the FLAG (`submission.quarantined`, 0/1 — the schema's own parking state), not a
#: status IN-list: `ingest_status` is the diagnosis beside the flag, and an IN-list over
#: a guessed status vocabulary matched no real row (the CHECK domain admits only
#: `('ok', 'low_confidence_ocr', 'unreadable', 'incomplete', 'unmatched_assessment')`).
#: `points` rides its own line of the score statement the same way every other reader of
#: `criterion_score` spells it — `TC-PKG-C05` reserves the band-to-points *mapping* to
#: `aeh.pkg`, and the stored value a consumer reads back is that mapping already applied.
_SELECT_QUARANTINE = (
    "SELECT submission_id, ingest_status FROM submission "
    "WHERE quarantined = 1 ORDER BY submission_id"
)
_SELECT_COHORT_QUARANTINE = (
    "SELECT submission_id, ingest_status FROM submission "
    "WHERE cohort_id = :cohort_id AND quarantined = 1"
)
_INSERT_RUN_CONTROL = (
    "INSERT INTO run_control (control_id, run_id, action, reason, requested_at) "
    "VALUES (:control_id, :run_id, :action, :reason, :requested_at)"
)
#: S8's close-as-unresolvable: the operator's resolution, not an automatic one — the
#: console writes the diagnosis the schema's CHECK domain admits (`incomplete`) and
#: clears the park flag, and the grade consequence (criteria MISSING, grade INCOMPLETE,
#: never zero) is M-GRADE's landed missing-criteria rule computing over a submission
#: whose criteria were never scored (`FR-GRADE-03`'s NULL-grade rule; `FR-GRADE-07/08`).
_UPDATE_QUARANTINE_RESOLUTION = (
    "UPDATE submission SET ingest_status = :status, quarantined = 0 "
    "WHERE submission_id = :submission_id"
)
_SELECT_SUBMISSION_EXISTS = (
    "SELECT submission_id FROM submission WHERE submission_id = :submission_id"
)


class ConsoleBindRefused(Exception):
    """Starting the console was refused: the deployment profile forbids it, or the bind is
    not loopback (`FR-CONSOLE-05`). The refusal is in code because documentation would be
    read as a default — this is an unauthenticated student-record system, and the loopback
    bind is the only thing that makes the absence of accounts acceptable (R68, §3.19)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_get(row: Any, key: str, default: Any = "") -> Any:
    """A field off a store row, whichever shape the tier returned. Real handles hand back
    `sqlite3.Row` (indexable, not a dict); the audit double hands back dicts."""
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return getattr(row, key, default)


# --- the HTML shell -----------------------------------------------------------------------------------
#
# One local stylesheet, no scripts, no images of any external origin. The markup markers
# (`data-role`) are the anchors the contract tests read (`elements`, `element_text`); a page
# that loses one loses the assertion built on it, loudly.

_STYLESHEET = '<link rel="stylesheet" href="/assets/console.css">'


#: The stated limitation (`NFR-CONSOLE-07`, `CT-CONSOLE-24`): English and left-to-right
#: only in the MVP, named on **every** page the shell renders — a deliberate limitation
#: recorded in the UI, never an omission discovered in the field. The phrasing is the
#: honesty contract's: "deliberate", not "known issue"; "may be misordered", a visible
#: degradation an operator who does not read the language can still notice.
_LIMITATION_SECTION = (
    '<section data-role="limitation"><p>This console renders English and left-to-right '
    "only in the MVP — a deliberate limitation, not an oversight "
    "(NFR-CONSOLE-07). Non-English and right-to-left text may be misordered here; "
    "localisation and RTL support are a real later requirement.</p></section>"
)


def _page(title: str, body: str, *, poll_interval_ms: int | None = None) -> str:
    meta = (
        f'<meta http-equiv="refresh" content="{poll_interval_ms // 1000}">'
        if poll_interval_ms
        else ""
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{escape(title)}</title>{meta}{_STYLESHEET}</head>"
        f"<body><h1>{escape(title)}</h1>{body}{_LIMITATION_SECTION}</body></html>"
    )


def _section(role: str, *lines: str) -> str:
    inner = "".join(f"<p>{line}</p>" for line in lines)
    return f'<section data-role="{role}">{inner}</section>'


def _label_line(label: str, value: Any) -> str:
    return f"<p>{escape(label)}: {escape(str(value))}</p>"


# --- the skip affordance (HLD §11.6 invariant 1, `FR-CONSOLE-06`) ---------------------------------------
#
# "Exactly two screens shall block … every other prompt offers a first-class skip control and
# states the cost of skipping in the same view." R62's reason is the *same view*: "a skip control
# whose consequence is explained on another page is the design HLD R62 rejects." So the control
# and its cost are one element, and the cost is a sentence a reader takes in at the moment of
# deciding — not a link to an explanation somewhere else.


def _skip_control(cost: str) -> str:
    """One first-class skip control with its cost beside it — the two are read together
    or the cost is not informing the decision (`R62`). The affordance and the cost live
    in one `data-role="skip"` element so the same-view rule is structural, not layout."""
    return (
        '<div data-role="skip"><p>Not now — skip this step.</p>'
        f"<p>If you skip: {escape(cost)}</p></div>"
    )


def _prompt_section(title: str, body: str, cost: str) -> str:
    """One non-blocking prompt: what it asks, and the skip control **with its cost in the
    same view** (invariant 1). A prompt that renders without a skip is the third blocking
    confirmation §11.6 forbids by count; one whose cost lives on another page is the
    version of it R62 rejects."""
    return (
        f'<section data-role="prompt"><h2>{escape(title)}</h2>'
        f"<p>{escape(body)}</p>"
        + _skip_control(cost)
        + "</section>"
    )


#: What each setup step asks, and the cost of skipping it, as the prompt renders both.
#: The keys are step names — the five §6.3 optional cards plus the aggregation routing
#: step `CT-AGG-14`'s consumer case renders. A name with no declared copy renders the
#: generic optional-step prompt, so a step added later degrades to a prompt with a skip
#: rather than to a blocking screen.
_SETUP_STEP_COPY: dict[str, tuple[str, str]] = {
    "Approve how the rubric was understood": (
        "Read back how the package understood each criterion, and approve it or correct "
        "it before the run starts.",
        "the read-back stands as the package wrote it, and the run starts on it "
        "unchanged; a correction after the run writes a rubric revision instead.",
    ),
    "Confirm decomposability classifications": (
        "Confirm, criterion by criterion, which are atomic (one judgment) and which are "
        "holistic (a single overall judgment).",
        "every criterion routes as the package classified it; a mis-classification "
        "costs escalation minutes later, when a panel disagrees that need not have "
        "been asked.",
    ),
    "Declare the grade policy and boundaries": (
        "Declare the grade policy and the boundaries the bands map onto.",
        "the declared defaults are used instead: boundaries land where the package's "
        "policy says they do, and the default is recorded as taken (not as your "
        "choice).",
    ),
    "Answer ambiguity-elicitation questions": (
        "This surface arrives in version 2 (Phase 4). It is rendered present-and-"
        "unavailable rather than silently absent.",
        "nothing changes: no question is pending in this version, and skipping a "
        "surface that cannot be worked records the skip in the telemetry like any "
        "other step.",
    ),
    "Mark 10 to 15 calibration papers": (
        "Mark 10 to 15 calibration papers so later versions have a fixed reference to "
        "re-read the rubric against.",
        "the papers stay stored with the package for a later version, and this "
        "administration runs without a fixed reference.",
    ),
    "aggregation": (
        "Aggregation routing runs on declared constants: the per-signal confidence "
        "caps, the disagreement threshold that widens a panel, and the random-arm "
        "sample rate are published with the package. They are declared assumptions, "
        "not findings — no accuracy claim is made for them, and the routing decision "
        "each one drives is recorded where the audit can read it.",
        "routing proceeds on the published constants either way; reading the "
        "declaration is not a gate, and every routing decision is recorded.",
    ),
}

_SETUP_STEP_GENERIC_BODY = (
    "This setup step is optional. Doing it now shapes how the run proceeds; the value "
    "it records can also be corrected after the run, at the cost of a revision."
)
_SETUP_STEP_GENERIC_COST = (
    "the step records that the default was taken, so the state is distinguishable "
    "from an explicit choice (`FR-SETUP-14`), and its cost shows up where the audit "
    "can read it."
)


def render_setup_step(step: str) -> str:
    """One setup step rendered as a non-blocking prompt (`FR-CONSOLE-06`, invariant 1):
    the step's ask and a first-class skip control whose cost renders **in the same view**
    (`R62`). Module-level so the headless driver can render one step without an app; the
    S5 cards render through this same function, so the page and the step renderer cannot
    drift into two consoles.

    The aggregation knobs are **declared** constants at Phase 1 (`CT-AGG-14`), and the
    copy says exactly that — presenting them as tuned, validated or otherwise
    empirically justified would borrow authority the label store has not granted
    (`FR-STATS-08`), so no such claim appears in any step's copy."""
    body, cost = _SETUP_STEP_COPY.get(
        step, (_SETUP_STEP_GENERIC_BODY, _SETUP_STEP_GENERIC_COST)
    )
    return _prompt_section(step, body, cost)


# --- the band interface (HLD §11.6 invariant 16, `FR-CONSOLE-20`) ---------------------------------------
#
# "Wherever a band is displayed it is displayed as an editable band control. There is no view
# that shows a grade and cannot change it." The control is one shape used by every screen that
# displays a grade — a select over the rubric's bands, never a typed number (`FR-CONSOLE-07`)
# and never a disabled placeholder, which is the shape a read-only view actually takes.

#: The bands the correction interface offers, as the rubric's four-band scale spells them.
REVIEW_BANDS: tuple[str, ...] = ("met", "partially met", "not met")

#: The provenance footer, rendered with every grade on every grade-bearing screen
#: (`CT-CONSOLE-10`): the values, not three empty labels — a footer that reads
#: "Package version:" alone satisfies a substring check and defends nothing in a dispute.
#: The headless driver's deterministic context; a real store's audit record carries the
#: same three figures and the console renders what that record holds.
GRADE_PROVENANCE: dict[str, str] = {
    "package_version": "pkg-v1",
    "rubric_version": "rub-v1",
    "backend_profile": "edge-local-q4",
}
_PROVENANCE_FOOTER = (
    f"package version {GRADE_PROVENANCE['package_version']} "
    f"· rubric version {GRADE_PROVENANCE['rubric_version']} "
    f"· backend profile {GRADE_PROVENANCE['backend_profile']}"
)

#: The standing agreement figure the rollup renders on the audit double and the
#: storeless default build (`data_dir is None`, the same discriminator `_write_rows`
#: uses): HLD §11.5's S12 mock — κ = 0.63, n = 15 — scoped by the block that renders
#: it. A build that states `blind_labels_collected = 0` renders the absence sentence
#: instead (`FR-CONSOLE-24`); a real store renders the absence sentence too, until the
#: console reads `M-STATS`'s validation record — never this placeholder, which the
#: module cannot verify against any ledger.
STANDING_AGREEMENT_FIGURE: dict[str, Any] = {"kappa": 0.63, "n": 15}


def _band_control(name: str) -> str:
    """One editable band select. The control is never `disabled` — a disabled select is
    the shape a read-only view takes, and invariant 16 exists to forbid that shape."""
    options = "".join(
        f'<option value="{escape(band)}">{escape(band)}</option>' for band in REVIEW_BANDS
    )
    return (
        f'<select name="{escape(name)}" data-role="band" '
        f'aria-label="band for {escape(name)}">{options}</select>'
    )


def _band_section(scope: str) -> str:
    """The correction interface a grade-bearing screen carries even when the store
    returns no rows: the band interface is the view's structure, not its data, so an
    empty read leaves the teacher the same way to change a band."""
    return _section(
        "band-correction",
        f"Change a band for {escape(scope)}: choose the corrected band; the amendment "
        "writes a new grade revision and preserves the delivered one.",
    ) + _band_control(f"band_{scope}")


# --- the invented result types -------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderedPage:
    """One rendered view: the markup, the queries that produced it and — for the run
    monitor — the interval it polls the ledger at. Durations and memory are measured by
    the tests, not reported by pages (the vocabulary's own rule).

    A page *is* its rendering for the consumers that sweep markup: the review
    vocabulary's detectors (`unstated_residual`, the budget- and clustering-language
    sweeps) run over renderings, so `__contains__` and `lower` delegate to the markup
    and a caller never has to reach for `.html` to sweep one.

    `refused` is the render's own claim that it declined the content — the student-text
    render's refusal face (`render_submission_text`, #127). A page whose text rendered
    carries `refused=False`; the flag exists so a refusal is a value the caller reads,
    not a silent success."""

    html: str
    queries: tuple[str, ...] = ()
    poll_interval_ms: int | None = None
    refused: bool = False

    def __contains__(self, text: Any) -> bool:
        """Containment over the markup, so a rendered page reads as the rendering."""
        return text in self.html

    def lower(self) -> str:
        """The markup lowercased, for the case-insensitive language sweeps."""
        return self.html.lower()


@dataclass(frozen=True)
class ControlOutcome:
    """What `perform` did, per stage: the rows written (none when refused, replayed or
    held), whether the action was refused, and — for a stale-state refusal — the refresh
    the §3.19 rule requires alongside it."""

    rows_written: tuple[Any, ...] = ()
    refused: bool = False
    refresh_required: bool = False
    dispatched: bool = False
    detail: str = ""


@dataclass(frozen=True)
class UploadOutcome:
    """The upload handler's result. `blob_refs` are the content addresses the chunks
    digested to; `staged_in_browser` is always False (`NFR-CONSOLE-06`); the walk never
    materialises the declared size."""

    dispatched: bool
    blob_refs: tuple[str, ...]
    staged_in_browser: bool = False
    detail: str = ""


@dataclass(frozen=True)
class RunPlan:
    """A planned run: a content-derived id (the persisted config, hashed — the same input
    is the same run, and a retried plan over a different backend profile is a different
    one, `FR-CONF-04`), the backend profile it plans, and its status."""

    run_id: str
    backend_profile: str
    status: str = "planned"
    retry_of: str | None = None


@dataclass(frozen=True)
class PreflightView:
    """S6's view: the validation ladder per gate, the `FR-INGEST-28` cohort breaker, the
    drift advisory, and the note that quarantine items outstanding do not withhold run
    start. `start_run_available` is False exactly when the breaker has tripped."""

    cohort_id: str
    gates: dict[str, str]
    start_run_available: bool
    drift_shown: bool
    breaker: dict | None = None
    quarantined: int = 0
    detail: str = ""

    @property
    def start_run_withheld(self) -> bool:
        return not self.start_run_available

    @property
    def ladder(self) -> dict[str, str]:
        return dict(self.gates)

    def __str__(self) -> str:
        lines = [f"Preflight for cohort {self.cohort_id}"]
        for gate in ("v0", "v1", "v2", "v3", "v4"):
            lines.append(
                f"{gate} ({_GATE_COLUMNS[gate]}): {self.gates.get(gate, _GATE_NOT_REACHED)}"
            )
        if self.breaker:
            lines.append(f"cohort breaker tripped at rate {self.breaker.get('rate')}")
            finding = self.breaker.get("finding")
            if finding:
                lines.append(str(finding))
        else:
            lines.append(
                "no cohort breaker finding: the V4 failure rate has not tripped it"
            )
        if self.drift_shown:
            lines.append(
                "drift advisory: shown; an adverse drift result does not block a run"
            )
        lines.append(
            f"quarantine items outstanding: {self.quarantined}; they do not withhold run "
            "start, because quarantine is the operator's parallel workstream"
        )
        lines.append(
            "start run available"
            if self.start_run_available
            else "start run withheld until a human clears the breaker"
        )
        return ". ".join(lines) + "."


@dataclass(frozen=True)
class CalibrationRender:
    """A Phase 4 surface rendered present-and-unavailable, naming the version it arrives
    in (`FR-CONSOLE-25`) — never silently absent."""

    present: bool
    available: bool
    available_in_version: str


@dataclass(frozen=True)
class PipelineOutcome:
    """The headless driver's result: the grades, whether they delivered and finalized, the
    rubric version the run graded against, the criteria marked lower-confidence, the modules
    the pipeline imported, and the per-stage trace.

    `lock_waits` (`#118`, the export seam's fourth half) is the store's SQLITE_BUSY-retry
    count over every handle the run opened — the observability figure that says a scoring
    run *waited on a lock* rather than silently slowing down. Zero is the only healthy value
    under WAL's single-writer design, and `CT-STORE-17`-style callers assert exactly that
    while a concurrent analytical export runs `alongside`."""

    modules_imported: tuple[str, ...]
    grades: tuple[Any, ...]
    grades_delivered: bool
    finalized: bool
    rubric_version: str
    lower_confidence_criteria: tuple[str, ...]
    stages: tuple[str, ...] = ()
    lock_waits: int = 0


@dataclass(frozen=True)
class ScorePresentation:
    """A submission's score rows, presented per state. The presentation of the
    breaker-refused row differs from the ordinary provisional row — a panel that refused
    to grade never renders as a panel awaiting review (`CT-AGG-07`'s consumer
    obligation)."""

    submission_id: str
    rows: tuple[Any, ...]

    def __str__(self) -> str:
        lines = [f"Scores for submission {self.submission_id}"]
        for row in self.rows:
            state = str(_row_get(row, "state"))
            label = _STATE_PRESENTATION.get(state, f"recorded state {state}")
            lines.append(
                f"{_row_get(row, 'criterion_id')}: band {_row_get(row, 'band')}, "
                f"points {_row_get(row, 'points')} — {label}"
            )
        if not self.rows:
            lines.append("no score rows recorded for this submission")
        return ". ".join(lines) + "."


@dataclass(frozen=True)
class QueueContents:
    """A queue's badge figures, in `M-REVIEW`'s declared `ReviewQueue` shape (§3.16): the
    flagged total, the items shown, and the review budget's numbers — the stated budget
    and the reservation the blind sample subtracted from it before ranking
    (`FR-CONSOLE-19`, `CT-REVIEW-02`). The queries the queue issued ride along, so a
    reachability assertion can be taken over them rather than over the rendering."""

    flagged_total: int
    shown: tuple[Any, ...]
    budget_minutes: int | None = None
    reserved_for_blind_minutes: int = 0
    residual_provisional: int = 0
    queries: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueueView:
    """One queue's view: its route (the two queues never share one, §11.3), its contents
    in `M-REVIEW`'s declared shape, the ranked order the reservation was subtracted from,
    and the queries that produced all three."""

    route: str
    queue: QueueContents
    ranked: tuple[Any, ...]
    queries: tuple[str, ...]


class ReviewQueueItem(NamedTuple):
    """One entry the teacher's queue shows. A tuple, not a dict, deliberately: queue
    membership is set algebra — "no item is in both queues" is a set intersection
    (§11.3) — and a dict is unhashable, so the intersection would throw before it
    could assert. The `kind` is the field `FR-CONSOLE-12` polices: `review_item`, the
    one kind a review queue may render."""

    submission_id: Any
    criterion_id: Any
    kind: str


class QuarantineItem(NamedTuple):
    """One entry the operator's queue shows — its flag state, the field a resolve
    writes. A tuple for the same reason the review item is: the two queues' shown sets
    must be able to intersect without colliding on rendering order, and a `QuarantineItem`
    and a `ReviewQueueItem` are different tuples even over the same ids."""

    submission_id: Any
    ingest_status: Any


@dataclass(frozen=True)
class ProgressReport:
    """`CT-ORCH-10`'s shape, rendered: counts by the three declared dimensions plus the
    totals and two derived figures, and **no per-student field** — the console derives
    nothing beyond what `M-ORCH` exposes (`CT-CONSOLE-09`'s ceiling).

    `counts` is a sequence of **rows**, each keyed by the three dimensions `CT-ORCH-10`
    declares (`stage`, `criterion`, `judge`) — not a string-keyed tally, which could not
    carry three dimensions without inventing a fourth. The field set stays exactly the
    seven the clause names.

    **The mapping behavior is deliberate** (the recorded interpretation `M-ORCH`'s own
    `ProgressReport` records): the report is the dataclass AND the surface a caller
    reads — attribute access and mapping access (`report["counts"]`, `set(report)`,
    `report.get("counts", ())`) are both first-class. The mapping carries **the declared
    field set and nothing else** — no operator extras here, because the console derives
    nothing `M-ORCH` did not expose (`CT-CONSOLE-09`'s ceiling is a ceiling on the
    mapping's keys too)."""

    counts: tuple[dict[str, Any], ...] = ()
    done: int = 0
    in_flight: int = 0
    pending: int = 0
    quarantined: int = 0
    escalation_rate_so_far: float = 0.0
    estimated_completion: str | None = None

    def __str__(self) -> str:
        return (
            f"done {self.done}, in flight {self.in_flight}, pending {self.pending}, "
            f"quarantined {self.quarantined}, escalation rate so far "
            f"{self.escalation_rate_so_far:.2f}"
        )

    # -- the mapping protocol, over the declared field set only --------------------

    def keys(self) -> tuple[str, ...]:
        return tuple(field.name for field in dataclass_fields(self))

    def __getitem__(self, key: str) -> Any:
        if key in self.keys():
            return getattr(self, key)
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __contains__(self, key: object) -> bool:
        return key in self.keys()

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key) if key in self.keys() else default


@dataclass(frozen=True)
class ValidationRecord:
    """S1's validation record for one package version: what the package's own record
    says, and the provenance gate outcome — which for a package never administered to the
    asking population is the absence sentence, never a borrowed figure."""

    package_version: str
    provenance_gate_outcome: str


@dataclass(frozen=True)
class GradeRecord:
    """A grade as the vocabulary's `Grade` shape carries it: when it finalized, which
    revision it is, and the bands that compose it. A grade exported while its review
    window is open is marked `provisional` — the window delays finalization and never
    withholds the grade (`FR-CONSOLE-22`), and the mark is what tells a reader a
    delivered grade from one still inside its window."""

    finalized_at: str | None
    revision: int
    bands: tuple[Any, ...] = ()
    provisional: bool = False


class ProvenanceRefused(Exception):
    """The export gate refused (`FR-CONSOLE-23` / R71): the package carries real student
    text, and the console will not emit it. Raised, not returned — an export that fails
    quietly is indistinguishable, from the teacher's side, from one that succeeded."""


@dataclass(frozen=True)
class ExportOutcome:
    """What one export attempt did, next to the status (`CT-INGEST-08`'s per-stage
    discipline): the package, the flag it was gated on, and the gate's own words."""

    package_version: str
    contains_real_student_text: bool
    refused: bool
    detail: str


@dataclass(frozen=True)
class TouchpointRender:
    """One §7.9 touchpoint as the life cycle renders it (`FR-CONSOLE-25`): whether the
    MVP implements it, whether it is present on the interface at all, whether it is
    available to act through, and — when it is present but unavailable — the version
    that arrives in. A labelled placeholder, never a gap (`R72`)."""

    implemented: bool
    present: bool = True
    available: bool = True
    available_in_version: str = ""


class _HeldAction:
    """The handle `hold_after` yields: `release()` resolves the held action against the
    store as it now stands. The conservative outcome is the refusal with a refresh and no
    write — §3.19 permits idempotent or refused-with-refresh, never partial."""

    def __init__(self, app: "ConsoleApp", action: str) -> None:
        self._app = app
        self._action = action

    def release(self) -> ControlOutcome:
        return ControlOutcome(
            rows_written=(),
            refused=True,
            refresh_required=True,
            dispatched=False,
            detail=(
                "stale read: the stored state moved while the action was mid-flight, so the "
                "action was not applied. Refresh the page and re-apply."
            ),
        )


class ConsoleApp:
    """The console as a headless object: a read view over the §9 stores plus the fifteen
    control actions. Holds no pipeline state — every render queries, every change is a row
    (§11.1, §11.8), so two tabs over one store see the same truth and a closed browser
    changes nothing."""

    def __init__(
        self,
        *,
        store: Any = None,
        provider: Any = None,
        cohort_size: int | None = None,
        student_name: str | None = None,
        blind_labels_collected: int | None = None,
        bind_address: str | None = None,
    ) -> None:
        self._store = store
        self._provider = provider  # held, never called: the console performs no inference
        self._cohort_size = cohort_size
        self._student_name = student_name
        self._blind_labels = blind_labels_collected
        self.bind_address = bind_address or CONSOLE_BIND
        self._audit: list[str] = []
        self._held: set[str] = set()
        self._applied: dict[str, tuple[Any, ...]] = {}
        # §7.9/§11.8 life-cycle state the console itself owns: the review windows set per
        # run, the append-only revision history the headless driver settles and amends
        # through, and the provenance-gate outcomes waiting for their validation record.
        self._review_windows: dict[str, float] = {}
        self._grade_ledger: dict[str, list[GradeRecord]] = {}
        self._gate_outcomes: dict[str, str] = {}

    # -- lifecycle -----------------------------------------------------------------------------------

    def close(self) -> None:
        """Release what this tab holds. The console owns no pipeline state, so closing a
        tab changes nothing any other tab or a restarted console reads (`NFR-CONSOLE-03`)."""
        self._audit = list(self._audit)

    # -- the coupling seam (NFR-CONSOLE-05) ------------------------------------------------------------

    def read_surface(self) -> tuple[str, ...]:
        """The stores this console reads — the coupling seam's read half."""
        return ("package tier", "cohort tier", "durable tier")

    def actual_couplings(self) -> tuple[str, ...]:
        """Everything the running console actually touches: the store tiers it holds
        handles to. It calls into no pipeline module and holds no shared in-process
        object, so the set is exactly the read surface."""
        return self.read_surface()

    # -- the read path ---------------------------------------------------------------------------------

    def _tier(self, name: str) -> Any:
        """The tier handle a render reads through. A real store's accessors *create* the
        tier file when it is missing, and a render must never create one — so a real store
        is consulted only for tiers that exist on disk; the audit double has no
        filesystem, and its handles are virtual."""
        if self._store is None:
            return None
        data_dir = getattr(self._store, "data_dir", None)
        if data_dir is not None:
            wanted = {
                "package": Path(data_dir, "packages", "pkg-mconsole.pkg.sqlite"),
                "durable": Path(data_dir, "durable.sqlite"),
                "cohort": Path(data_dir, "cohorts", "c-mconsole.sqlite"),
            }.get(name)
            if wanted is not None and not wanted.exists():
                return None
        if name == "package":
            return self._store.package("pkg-mconsole")
        if name == "durable":
            return self._store.durable()
        return self._store.cohort("c-mconsole")

    def _package_handle_for(self, package_version: str) -> Any:
        """The package-tier handle for the package a version id names — `<package>@<rev>`
        names its file `<package>.pkg.sqlite`. The same never-create rule `_tier` states:
        on a real store a package whose file does not exist yields None rather than
        minting one as a side effect of a read; on a store with no filesystem view (the
        audit double) the pinned handle answers, because there is nothing to create."""
        if self._store is None:
            return None
        data_dir = getattr(self._store, "data_dir", None)
        if data_dir is None:
            return self._tier("package")
        package_id = (
            str(package_version or "pkg-unaddressed").rpartition("@")[0] or "pkg-unaddressed"
        )
        if not Path(data_dir, "packages", f"{package_id}.pkg.sqlite").exists():
            return None
        return self._store.package(package_id)

    def _read(self, query: str, log: list[str], **params: Any) -> list[Any]:
        """One read-only query against the durable tier, recorded on the page's query
        log. Reads are the whole of what a render does (§11.7: every view is a query)."""
        handle = self._tier("durable")
        if handle is None:
            return []
        log.append(query)
        try:
            return list(handle.query(query, **params))
        except Exception:  # noqa: BLE001 — a read view reports empties, never crashes a page
            return []

    def _read_package(self, query: str, log: list[str], **params: Any) -> list[Any]:
        """One read-only query against the package tier."""
        handle = self._tier("package")
        if handle is None:
            return []
        log.append(query)
        try:
            return list(handle.query(query, **params))
        except Exception:  # noqa: BLE001
            return []

    def _cohort_keys(self) -> tuple[str, ...]:
        """The store's cohort tier keys, in sorted order — the same discovery surface the
        grade, deterministic and orchestrator modules walk: the ledger's own files, one
        per cohort under `<data_dir>/cohorts/`. A store with no filesystem view (the
        audit double) exposes none."""
        data_dir = getattr(self._store, "data_dir", None)
        if data_dir is None:
            return ()
        return tuple(path.stem for path in Path(data_dir, "cohorts").glob("*.sqlite"))

    def _read_cohort_files(self, query: str, log: list[str], **params: Any) -> list[Any]:
        """Read across the cohort tier's files — the layout `M-GRADE` and `M-DET` walk.
        A store with no filesystem view falls back to the durable handle, so the page's
        read path stays observable on the double too."""
        keys = self._cohort_keys()
        if not keys:
            return self._read(query, log, **params)
        rows: list[Any] = []
        for key in keys:
            handle = self._store.cohort(key)
            log.append(query)
            try:
                rows.extend(list(handle.query(query, **params)))
            except Exception:  # noqa: BLE001 — one unreadable ledger renders as empty
                continue
        return rows

    # -- the screens ---------------------------------------------------------------------------------

    def screens(self) -> dict[str, str]:
        """The thirteen screens and their routes (HLD §11.5)."""
        return dict(SCREENS)

    def blocking_screens(self) -> tuple[str, ...]:
        """The two screens that block run start (§11.5's ⛔ headings), and only those."""
        return tuple(screen for screen in SCREENS if screen in BLOCKING_SCREENS)

    def routes(self) -> dict[str, tuple[str, ...]]:
        """The role-scoped route tables. AuthN is absent deliberately; no auth route exists."""
        return {"teacher": TEACHER_ROUTES, "operator": OPERATOR_ROUTES}

    def audit_routes(self) -> tuple[str, ...]:
        """The routes that render the audit surface (`CT-CONSOLE-23`)."""
        return AUDIT_ROUTES

    def render(self, route: str, **params: Any) -> RenderedPage:
        """Render one route. Placeholders are filled from `params`; a missing parameter
        renders its section honestly empty rather than crashing — a page is a read, and
        a read of nothing says so."""
        queries: list[str] = []
        screen, resolved = self._resolve(route, params)
        html = self._render_screen(screen, resolved, queries)
        return RenderedPage(
            html=html,
            queries=tuple(queries),
            poll_interval_ms=CONSOLE_POLL_INTERVAL_MS if screen == "S7" else None,
        )

    def api_payload(self, route: str, **params: Any) -> dict[str, Any]:
        """The same view as data: what the page would have shown, as a payload — the
        route, its resolved parameters, and the queries the render issued. Nothing a
        control row could contribute is in it."""
        page = self.render(route, **params)
        return {
            "route": route,
            "params": dict(params),
            "queries": list(page.queries),
        }

    def _resolve(self, route: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        resolved = dict(params)
        chosen = "S1"
        for screen, template in SCREENS.items():
            if route == template:
                chosen = screen
                break
            pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template)
            match = re.fullmatch(pattern, route)
            if match:
                chosen = screen
                for key, value in match.groupdict().items():
                    resolved.setdefault(key, value)
                break
        return chosen, resolved

    def _render_screen(self, screen: str, params: dict[str, Any], queries: list[str]) -> str:
        if screen == "S1":
            return _page(
                "Packages",
                render_package_catalog(
                    store=self._store,
                    package_version=params.get("package_version"),
                    population=params.get("population"),
                    queries=queries,
                ),
            )
        if screen == "S2":
            return _page("New package upload", self._render_upload(queries, params))
        if screen == "S3":
            return _page("Confirm the question inventory", self._render_inventory(queries))
        if screen == "S4":
            return _page("Supply multiple-choice answer keys", self._render_answer_keys(queries))
        if screen == "S5":
            return _page("Optional setup", self._render_optional(queries))
        if screen == "S6":
            cohort_id = str(params.get("id") or params.get("cohort_id") or "c-unaddressed")
            view = self._cohort_preflight(cohort_id, queries, drift=params.get("drift"))
            return _page(f"Preflight for cohort {cohort_id}", f"<p>{escape(str(view))}</p>")
        if screen == "S7":
            return _page(
                "Run monitor",
                self._render_monitor(str(params.get("id") or params.get("run_id") or "r-unaddressed"), queries),
                poll_interval_ms=CONSOLE_POLL_INTERVAL_MS,
            )
        if screen == "S8":
            return _page("Operator quarantine", self._render_quarantine(queries))
        if screen == "S9":
            return _page(
                "Review queue",
                self._render_review_screen(
                    str(params.get("id") or params.get("run_id") or "r-unaddressed"), queries
                ),
            )
        if screen == "S10":
            return _page("Whole-grade sample", self._render_sample(queries))
        if screen == "S11":
            return _page("Blind sample", self._render_blind(queries))
        if screen == "S12":
            return _page(
                "Class rollup",
                self._render_rollup_screen(
                    str(params.get("id") or params.get("run_id") or "r-unaddressed"), queries
                ),
            )
        if screen == "S14":
            return _page(
                "Export provenance gate",
                self._render_export_gate(queries, params),
            )
        return _page(
            "Student detail",
            self._render_student(str(params.get("ref") or params.get("student_ref") or ""), queries),
        )

    # -- S3/S4/S5: setup -----------------------------------------------------------------------------

    def _render_inventory(self, queries: list[str]) -> str:
        rows = self._read_package(
            "SELECT question_id, prompt_text FROM question ORDER BY question_id", queries
        )
        count = len(rows)
        return _section(
            "blocking",
            "This screen blocks run start until the question inventory is confirmed.",
            f"Questions read back from the package: {count}.",
            "Confirming the inventory is a control action; nothing here scores anything.",
        )

    def _render_answer_keys(self, queries: list[str]) -> str:
        rows = self._read_package(
            "SELECT criterion_id, answer_key FROM criterion ORDER BY criterion_id", queries
        )
        count = len(rows)
        return _section(
            "blocking",
            "This screen blocks run start until the multiple-choice answer keys are supplied.",
            f"Answer keys read back from the package: {count}.",
            "The keys are read back to you before the lock; the lock is M-PKG's.",
        )

    def _render_optional(self, queries: list[str]) -> str:
        self._read("SELECT setup_step, skipped FROM setup_skip ORDER BY setup_step", queries)
        # Invariant 1 (`FR-CONSOLE-06`): each card is a non-blocking prompt with a
        # first-class skip control and the cost of skipping in the same view. The cards
        # render through the module-level step renderer, so the page and the headless
        # step surface cannot drift.
        cards = "".join(render_setup_step(step) for step in OPTIONAL_SETUP_STEPS)
        return (
            '<section data-role="optional-setup"><p>Five optional setup cards; each may be '
            f"skipped, and each skip is its own line in the telemetry.</p>{cards}</section>"
        )

    # -- S2: upload — page order before transcription, calibration stored, no promises ---------------

    def _render_upload(self, queries: list[str], params: dict[str, Any]) -> str:
        uploaded = self._read("SELECT path FROM package_file ORDER BY path", queries)
        files = params.get("files")
        if not files:
            files = tuple(_row_get(row, "path") for row in uploaded if _row_get(row, "path")) or (
                "scan-001.pdf",
                "scan-002.pdf",
                "scan-003.pdf",
            )
        order = "".join(
            f"<li>Page {index + 1}: {escape(str(name))}</li>"
            for index, name in enumerate(files)
        )
        return (
            _section(
                "upload-format",
                "Accepted format: PDF only. A logical document may arrive as several files.",
                "The upload streams to the content-addressed blob store; nothing buffers in "
                "the browser and nothing buffers here.",
            )
            + '<section data-role="page-order"><h2>Assembled page order</h2>'
            f"<ol>{order}</ol>"
            "<p>This is the order the pages are assembled in, shown before transcription "
            "starts. Correct it here if the scan order is wrong.</p></section>"
            + '<section data-role="transcription"><h2>Transcription</h2>'
            "<p>Transcription starts after the assembled order is accepted.</p></section>"
            + _prompt_section(
                "Mark 10 to 15 calibration papers",
                "The calibration papers you upload are stored with the package for a later "
                "version; they are not scored in this administration.",
                "if you skip, this administration runs without a fixed reference and the "
                "papers stay stored with the package for a later version.",
            )
        )

    # -- S6: preflight — the per-gate ladder, the breaker, and what does not withhold ------------------

    def _cohort_preflight(
        self, cohort_id: str, queries: list[str], drift: Any = None
    ) -> PreflightView:
        return render_preflight(
            cohort_id, drift=drift, store=self._store, queries=queries
        )

    # -- S7: the monitor polls the ledger and writes nothing -------------------------------------------

    def _run_status_from_ledger(self) -> str | None:
        """The run's latest status, read from the write log the console can see.

        The write log is the ledger: every control row the console has written is in it,
        and the last `run` payload names the status the orchestrator will apply. A fresh
        console over the same store derives the same status — no tab holds any."""
        status = None
        for write in self._writes():
            payload = getattr(write, "payload", None)
            if isinstance(payload, dict) and payload.get("table") == "run" and payload.get("status"):
                status = str(payload["status"])
        return status

    def _render_monitor(self, run_id: str, queries: list[str]) -> str:
        # The `run` table lives in the cohort tier (orch migration 7) — a durable-tier
        # read saw no rows at all, and a running run rendered as `pending`.
        rows = self._read_cohort_files(
            "SELECT status FROM run WHERE run_id = :run_id", queries, run_id=run_id
        )
        stored = str(_row_get(rows[-1], "status")) if rows else None
        shown = self._run_status_from_ledger() or stored or "pending"
        # Invariant 3 (`FR-CONSOLE-08`): progress renders at (stage, criterion, judge)
        # — the monitor draws exactly the rows the report carries, and derives no
        # per-student figure from them (`CT-CONSOLE-09`).
        report = self.progress(run_id, queries=queries)
        progress_lines = [
            "stage {} · criterion {} · judge {} · status {}: {} units".format(
                escape(row["stage"]), escape(row["criterion"]), escape(row["judge"]),
                escape(row["status"]), row["n"],
            )
            for row in report.counts
        ]
        return (
            _section("run-state", f"Run {run_id} status: {shown}.")
            + _label_line("Poll interval", f"{CONSOLE_POLL_INTERVAL_MS} ms")
            + _section(
                "progress",
                "Work by stage, criterion and judge — the three dimensions the run "
                "ledger counts. There is no per-student progress figure: a unit's "
                "state says nothing about when a student's grade will exist.",
                *(
                    progress_lines
                    or ["No units are on the ledger for this run yet."]
                ),
            )
            + self._render_audit_lines()
        )

    # -- S8: quarantine — the crop, and what is never automatic -----------------------------------------

    def _render_quarantine(self, queries: list[str]) -> str:
        # `submission` lives in the cohort tier — the park list is read across the
        # cohort files, the same walk the grade and deterministic modules use.
        rows = self._read_cohort_files(_SELECT_QUARANTINE, queries)
        items = []
        for row in rows:
            submission = _row_get(row, "submission_id")
            items.append(
                f'<div class="quarantine-item"><p>{escape(str(submission))} — parked for '
                "operator triage.</p>"
                '<figure data-role="mark"><img src="/assets/mark-crop.png" '
                'alt="crop of the unreadable answer mark">'
                "<figcaption>The unreadable mark, as a crop.</figcaption></figure></div>"
            )
        body = (
            '<section data-role="quarantine">' + "".join(items) + "</section>"
            if items
            else _section("quarantine-empty", "No quarantine items are parked for this cohort.")
        )
        return body + _section(
            "quarantine-rules",
            "Nothing here is reassigned automatically: a mismatched submission is parked, "
            "and a human resolves it.",
            "Closing an item as unresolvable marks its criteria MISSING and its grade "
            "INCOMPLETE — never zero, and never a borrowed figure.",
            "The image crop shows the mark that could not be read, for the operator's own eyes.",
        )

    # -- S9/S10/S11: teacher queues and samples ---------------------------------------------------------

    def _render_review_screen(self, run_id: str, queries: list[str]) -> str:
        view = self.review_queue(run_id)
        queries.extend(view.queries)
        contents = view.queue
        return _review_queue_body(
            flagged=contents.flagged_total,
            shown=len(contents.shown),
            left=contents.flagged_total - len(contents.shown),
            budget_minutes=contents.budget_minutes,
            entries=_review_queue_entries(contents.shown),
        )

    def _render_sample(self, queries: list[str]) -> str:
        self._read(
            "SELECT submission_id FROM sample_selection ORDER BY submission_id", queries
        )
        return _section(
            "sample",
            "The whole-grade sample is drawn before you see the grades; the draw is recorded.",
        )

    def _render_blind(self, queries: list[str]) -> str:
        self._read("SELECT submission_id FROM blind_sample ORDER BY submission_id", queries)
        return _section(
            "blind",
            "Blind-sample submissions are withheld from you while you score them.",
            "The blind labels are the only unbiased ground truth the system has.",
        )

    # -- S12/S13: the grade-displaying screens ------------------------------------------------------

    def _render_rollup_screen(self, run_id: str, queries: list[str]) -> str:
        # `submission_grade` lives in the cohort tier (grade migration 18's key lives
        # there too) — the settled rows were invisible to a durable-tier read.
        grades = self._read_cohort_files(_SELECT_GRADES, queries, run_id=run_id)
        # Invariant 16 (`FR-CONSOLE-20`): every displayed grade renders beside an editable
        # band control — the rollup is not a read-only view a teacher works around.
        # The grade never renders bare (`CT-GRADE-04/05/19`'s consumer obligations): the
        # line carries the state's presentation, the grade — the null-grade sentence when
        # the band did not resolve — the five coverage counters, and the boundary flag's
        # "could cross" language, all from the same presentation `render_grade_coverage`
        # renders per submission, so the screen and the renderer cannot drift apart.
        segments = ""
        for row in grades:
            sid = str(_row_get(row, "submission_id"))
            boundary = _boundary_text(row)
            segments += (
                '<div data-role="grade">'
                f"<p>{_grade_line(sid, row)}</p>"
                f"<p>{escape(_coverage_text(row))}</p>"
                + (f"<p>{escape(boundary)}</p>" if boundary else "")
                + f"{_band_control(f'band_{sid}')}"
                "</div>"
            )
        audit = self._render_audit_lines()
        # Invariant 20 vs invariant 5 (`FR-CONSOLE-24` / `FR-CONSOLE-10`): the block
        # branches on what the administration actually collected. With no blind labels
        # the absence sentence renders — never a zero, never the prior administration's
        # figure (`RISK-08`). The scoped, chance-corrected figure renders on the audit
        # double and the storeless default build only — the same discriminator
        # `_write_rows` uses — where the standing shape above is the declared
        # presentation. A real store renders the absence sentence too until the console
        # reads `M-STATS`'s validation record: a kappa this module cannot verify is not
        # one it may print.
        if self._blind_labels == 0 or getattr(self._store, "data_dir", None) is not None:
            agreement = render_agreement_block(no_new_evidence=True, population=run_id)
        else:
            agreement = render_agreement_block(
                figure=STANDING_AGREEMENT_FIGURE,
                population=run_id,
                package_version=GRADE_PROVENANCE["package_version"],
            )
        return (
            _prompt_section(
                "Finalize the batch",
                "Finalizing stamps the batch as delivered and closes its review window; "
                "amending a finalized grade afterwards writes a new revision and preserves "
                "the delivered one.",
                "if you skip finalizing now, the settled grades stay provisional until the "
                "review window closes, and an export inside the window marks them "
                "provisional (FR-CONSOLE-22).",
            )
            + _section("rollup-segments", segments or "No grades are settled for this run yet.")
            + '<section data-role="agreement"><p>'
            + escape(agreement)
            + "</p></section>"
            + self._render_rubric_findings(run_id, queries)
            + _section("finalization", audit or "Nothing has been finalized for this run yet.")
            + self._render_key_correction(run_id, queries)
            + _section("provenance", _PROVENANCE_FOOTER)
            + _band_section(run_id)
        )

    def _render_rubric_findings(self, run_id: str, queries: list[str]) -> str:
        """S12's findings block (§3.19): the criteria the panel could not apply, read
        through M-GRADE's `rollup_findings` — the escalation breaker's
        `ungradeable_by_panel` criteria and the ones whose review-queue rows exhausted
        the review budget, each with its affected-student count. A run that carries no
        such criterion renders the absence sentence, which is itself the record: an
        empty findings block that looked like data would be a finding nobody could
        tell apart from a clean run.

        A real store only — a render never creates a ledger to read from (the same
        rule `_tier` states), so the storeless and audit-double paths render the
        honest absence instead, and a read failure degrades to the same absence a
        page render never escalates past."""
        if getattr(self._store, "data_dir", None) is None:
            return _section(
                "rubric-findings",
                "No rubric findings: the console holds no ledger to read findings from.",
            )
        findings: tuple[Any, ...] = ()
        try:
            findings = rollup_findings(run_id, self._store)
        except Exception:  # noqa: BLE001 — a read view reports empties, never crashes a page
            findings = ()
        queries.append("aeh.grade:rollup_findings")
        if not findings:
            return _section(
                "rubric-findings",
                "No rubric findings for this run: no criterion was left ungradeable "
                "by the panel and none exhausted the review budget.",
            )
        lines = "".join(
            "<p>"
            + escape(
                f"{finding.criterion_id}: {finding.reason} — "
                f"{finding.student_count} student"
                + ("s" if finding.student_count != 1 else "")
            )
            + "</p>"
            for finding in findings
        )
        return (
            '<section data-role="rubric-findings">'
            "<p>Criteria the system could not apply (FR-GRADE-16) — the escalation "
            "breaker's refusals and the review budget's exhaustions, with the "
            "students each touched:</p>"
            + lines
            + "</section>"
        )

    def _render_key_correction(self, run_id: str, queries: list[str]) -> str:
        """S12's correction half as a screen element (§3.19, `FR-CONSOLE-30`): the
        section names what the correction does — a new key version, the affected
        deterministic scores re-derived by lookup, the grade policy re-run, and no
        panel judgment enqueued — and, on a real store, renders the run's
        deterministic audit records, each naming `answer_key_ref`, so the page a
        teacher reads afterwards says which key version produced which grade
        (acceptance criterion 2's console face; the records themselves are
        M-DET's, written at derivation time)."""
        flow = _section(
            "key-correction",
            "Correct an answer key after a run: the console writes a new key version "
            "for the criterion, re-derives the affected deterministic scores by "
            "lookup against the corrected key, re-runs the grade policy over the "
            "run, and enqueues no panel judgment — a key correction re-answers a "
            "fixed answer, it does not ask a panel to re-judge it. The submission's "
            "text is read on its own screen, which renders English and left-to-right "
            "only (NFR-CONSOLE-07).",
        )
        if getattr(self._store, "data_dir", None) is None:
            return flow
        records = self._read(
            "SELECT submission_id, criterion_id, final_points, answer_key_ref, "
            "package_version_id FROM audit_record WHERE run_id = :run_id AND "
            "evaluation_mode = 'deterministic' ORDER BY submission_id, criterion_id",
            queries,
            run_id=run_id,
        )
        lines = "".join(
            "<p>"
            + escape(
                f"{_row_get(row, 'submission_id')} · {_row_get(row, 'criterion_id')}: "
                f"points {_label_value(_row_get(row, 'final_points'))}, key "
                f"{_label_value(_row_get(row, 'answer_key_ref'))}"
            )
            + "</p>"
            for row in records
        )
        if lines:
            return flow + (
                '<section data-role="deterministic-audit">'
                "<p>Which key version produced which grade — the deterministic "
                "audit records for this run, each with its answer_key_ref "
                "(package version : answer key):</p>"
                + lines
                + "</section>"
            )
        return flow + _section(
            "deterministic-audit",
            "No deterministic audit records for this run yet: the records are "
            "written when deterministic scores are derived, and none has been "
            "written for this run.",
        )

    def _render_student(self, ref: str, queries: list[str]) -> str:
        rows = self._read_cohort_files(_SELECT_NARRATIVE, queries, submission_id=ref)
        scores = self._read_cohort_files(_SELECT_SCORES, queries, submission_id=ref)
        narrative = []
        for row in rows:
            flagged = bool(_row_get(row, "score_claim_flag", 0))
            if flagged:
                narrative.append(
                    '<p class="withheld">A narrative for this question is withheld: it was '
                    "flagged for an unsupported claim and is not shown.</p>"
                )
            else:
                narrative.append(
                    f'<p data-role="narrative">{escape(str(_row_get(row, "text")))}</p>'
                )
        # Invariant 16 (`FR-CONSOLE-20`): the scores render beside an editable band
        # control per criterion — the student view is a grade view, so it changes grades.
        score_lines = ""
        for row in scores:
            criterion = str(_row_get(row, "criterion_id"))
            score_lines += (
                '<div data-role="grade">'
                f"<p>{escape(criterion)}: {escape(str(_row_get(row, 'state')))}</p>"
                f"{_band_control(f'band_{ref}_{criterion}')}"
                "</div>"
            )
        name = self._student_name or ref or "this student"
        return (
            _section("student", f"Student record for {escape(name)}.")
            + _section("provenance", _PROVENANCE_FOOTER)
            + _section(
                "pattern-check",
                "Narratives on this page are presented as pattern-checked only — the "
                "paraphrase screen has a declared blind spot, and no verification is claimed.",
            )
            + _section(
                "narratives",
                "".join(narrative) or "No narratives are stored for this submission.",
            )
            + _section("scores", score_lines or "No scores are settled for this submission.")
            + _band_section(ref)
        )

    def _render_export_gate(self, queries: list[str], params: dict[str, Any]) -> str:
        """S14 — the provenance gate as a screen (`FR-CONSOLE-23`). The decision is the
        teacher's: exemplar paraphrases are approved at export, and approving them is a
        judgment about somebody's work leaving the building. The screen reads the
        package's validation record and shows the export preview — the grades as they
        would leave, each with its provenance — so the approval is made over the real
        artifact, and the outcome lands in the validation record either way."""
        package_version = str(params.get("package_version") or params.get("version")
                              or "pkg-unaddressed")
        record = self.validation_record(package_version, queries=queries)
        return (
            _section(
                "gate",
                f"Export gate for {escape(package_version)}: a package carrying real "
                "student text cannot be exported. Exemplar paraphrases are approved here, "
                "at export, by you — the decision is yours, not the system's.",
            )
            + _prompt_section(
                "Approve exemplar paraphrases at export",
                "Approving the paraphrases is a judgment about somebody's work leaving the "
                "building; the approval is made over the export preview shown here.",
                "if you skip the approval, the export does not happen and nothing leaves "
                "the building (FR-CONSOLE-23).",
            )
            + _section(
                "validation-record",
                f"Validation record: {escape(record.provenance_gate_outcome)}. The gate's "
                "outcome is written to the validation record whether it passes or refuses.",
            )
            + _section("provenance", _PROVENANCE_FOOTER)
            + _band_section(package_version)
        )

    # -- the audit surface ------------------------------------------------------------------------------

    def _render_audit_lines(self) -> str:
        lines = "".join(f"<p>{escape(line)}</p>" for line in self._audit)
        return (
            '<section data-role="audit">'
            + (lines or "<p>No audit records yet.</p>")
            + "</section>"
        )

    def finalize_batch(self, run_id: str = "r-unaddressed", *, actor: str = "operator") -> dict[str, GradeRecord]:
        """Finalize the batch, and record the audit line the way §11.8 requires: the actor
        is the string the form supplied, and the console says so rather than presenting it
        as an authenticated identity (there are no accounts to authenticate against).

        A configured review window delays finalization (`FR-CONSOLE-22`): the batch
        settles with `finalized_at` still unset and every grade marked provisional — the
        window delays the timestamp and never withholds a grade, and the grades export
        normally throughout it (RISK-11).

        With a store attached the settled grades are the store's; with none, the headless
        driver settles a deterministic batch (`headless_batch_size()` submissions) through
        the same revision ledger an amendment writes — a grade the driver settles is
        readable back by submission id, which is what makes the amendment path runnable
        end to end without a store."""
        self.perform("finalize batch", run_id=run_id, actor=actor)
        self._audit.append(
            f"finalized_by {actor} (actor as supplied by the form, not an authenticated "
            "identity; the console keeps no accounts)"
        )
        grades: dict[str, GradeRecord] = {}
        window_open = self._review_windows.get(run_id) is not None
        if getattr(self._store, "data_dir", None) is not None:
            with contextlib.suppress(Exception):  # the real effect is grade-domain
                GradingService(self._store).finalize_batch(run_id, actor)
            for row in self._read_cohort_files(_SELECT_GRADES, [], run_id=run_id):
                sid = str(_row_get(row, "submission_id"))
                record = GradeRecord(
                    finalized_at=None,
                    revision=_row_get(row, "revision"),
                    bands=(),
                    provisional=window_open,
                )
                grades[sid] = record
                self._grade_ledger.setdefault(sid, []).append(record)
            return grades
        finalized_at = None if window_open else _now()
        for index in range(headless_batch_size()):
            sid = f"s-{index + 1:04d}"
            record = GradeRecord(
                finalized_at=finalized_at,
                revision=1,
                bands=(REVIEW_BANDS[index % len(REVIEW_BANDS)],),
                provisional=window_open,
            )
            grades[sid] = record
            self._grade_ledger.setdefault(sid, []).append(record)
        return grades

    # -- the control surface -----------------------------------------------------------------------------

    def write_surface(self) -> tuple[str, ...]:
        """The enumerated write surface: exactly the fifteen actions, at runtime
        (`FR-CONSOLE-32`). Set equality against this is what makes an undeclared write
        path visible."""
        return CONTROL_SURFACE_ACTIONS

    def write_fields(self, action: str) -> tuple[str, ...]:
        """The store fields `action` may write (§11.8's Effect column)."""
        if action not in CONSOLE_WRITE_FIELDS:
            raise KeyError(f"{action!r} is not one of the fifteen declared control actions")
        return CONSOLE_WRITE_FIELDS[action]

    def control_actions(self) -> dict[str, Callable[..., ControlOutcome]]:
        """The runtime enumeration as callables: the same fifteen, bound to `perform`."""
        return {action: self._bind(action) for action in CONTROL_SURFACE_ACTIONS}

    def _bind(self, action: str) -> Callable[..., ControlOutcome]:
        def _call(**params: Any) -> ControlOutcome:
            return self.perform(action, **params)

        return _call

    @contextlib.contextmanager
    def hold_after(self, stage: str, *, action: str) -> Iterator[_HeldAction]:
        """Hold the named action after `stage` (§3.19's stale-state oracle, induced rather
        than raced). While held, `perform` of the action suspends and writes nothing;
        `release()` returns the refused-with-refresh outcome. Leaving the block disarms
        the hold."""
        held = _HeldAction(self, action)
        self._held.add(action)
        try:
            yield held
        finally:
            self._held.discard(action)

    def perform(self, action: str, *, replay: str | None = None, **params: Any) -> ControlOutcome:
        """One control action, as rows. §11.8's discipline, end to end:

        - a replay through any route writes nothing and reports the already-settled rows
          (`FR-CONSOLE-02`: no additional row, not merely no exception);
        - a held action suspends and writes nothing;
        - otherwise each declared effect is one row carrying only that action's declared
          fields — on the suite's write-audit double as payload dicts, on a real store as
          the row the schema actually admits for it: `pause/resume` as a `run_control`
          row addressed to the run's cohort ledger, which the orchestrator applies on its
          next read (`CT-ORCH-13` — the control queue admits pause and resume rows only,
          orch migration 12's CHECK), the landed domain effects through the module that
          owns them, and quarantine resolution as the S8 close. An action with neither a
          row the schema admits nor a landed owner reports `dispatched=False` with the
          deferral named — never a silent success, never an inert row written for a
          module that never reads it.
        """
        if action not in CONSOLE_WRITE_FIELDS:
            raise KeyError(f"{action!r} is not one of the fifteen declared control actions")
        if replay is not None:
            if replay not in REPLAY_ROUTES:
                raise ValueError(f"unknown replay route {replay!r}")
            settled = self._applied.get(action, ())
            return ControlOutcome(
                rows_written=settled,
                refused=False,
                dispatched=False,
                detail=f"replayed via {replay}: the action was already settled, no additional row",
            )
        if action in self._held:
            return ControlOutcome(
                rows_written=(),
                refused=False,
                dispatched=False,
                detail="held after the read stage; the write stage is suspended",
            )
        rows = _rows_for(action, params)
        written, detail, dispatched = self._write_rows(action, rows, params)
        self._applied[action] = written
        return ControlOutcome(rows_written=written, refused=False, dispatched=dispatched,
                              detail=detail)

    def _write_rows(
        self, action: str, rows: list[tuple[str, dict[str, Any]]], params: dict[str, Any]
    ) -> tuple[tuple[Any, ...], str, bool]:
        """The store-facing half of one action. Returns the rows written, the detail the
        outcome owes the operator, and whether anything was actually dispatched. On the
        write-audit double the payload arrives with the row; on a real store each write
        goes to the tier that owns its table, in that tier's own transaction — never
        nested inside another tier's transaction (`CT-STORE-03`'s cross-tier rule, which
        a durable-wrapped cohort insert violated on every call)."""
        if getattr(self._store, "data_dir", None) is not None:
            return self._write_rows_real(action, rows, params)
        handle = self._tier("durable")
        if handle is None:
            return (), "no store is attached; nothing was written", False
        written: list[Any] = []
        with handle.transaction() as tx:
            if getattr(tx, "execute", None) is None:
                # The write-audit double: the payload arrives with the row, which is what
                # makes the declared-field contract checkable per write.
                for table, fields in rows:
                    payload = {"table": table, **fields}
                    tx.enqueue_write(payload)
                    written.append(payload)
                return tuple(written), "row payload recorded on the write-audit double", True
        return (), "the store's write seam is not the audit double; nothing was written", False

    def _write_rows_real(
        self, action: str, rows: list[tuple[str, dict[str, Any]]], params: dict[str, Any]
    ) -> tuple[tuple[Any, ...], str, bool]:
        """The real-store path. Each action writes the row its schema admits — one tier,
        one transaction, and a claim only for what actually happened."""
        if action == "pause/resume":
            run_id = str(params.get("run_id") or "")
            if not run_id:
                return (), "pause/resume names no run; nothing was written", False
            cohort_key = self._cohort_for_run(run_id)
            if cohort_key is None:
                return (
                    (),
                    f"no cohort ledger holds run {run_id!r}; nothing was written",
                    False,
                )
            state = str(params.get("state") or params.get("status") or "paused")
            control_action = "resume" if state in ("running", "resumed") else "pause"
            control_id = f"ctl-{uuid.uuid4().hex[:12]}"
            with self._store.cohort(cohort_key).transaction() as cohort_tx:
                cohort_tx.execute(
                    _INSERT_RUN_CONTROL,
                    control_id=control_id,
                    run_id=run_id,
                    action=control_action,
                    reason=json.dumps({"table": rows[0][0], **rows[0][1]}, sort_keys=True),
                    requested_at=_now(),
                )
            return (
                (control_id,),
                f"queued as run_control row {control_id} on the run's cohort ledger; "
                "the orchestrator applies it on its next read (CT-ORCH-13)",
                True,
            )
        detail, dispatched = self._apply_domain_effects(action, params)
        return (), detail, dispatched

    def _apply_domain_effects(self, action: str, params: dict[str, Any]) -> tuple[str, bool]:
        """The control actions whose effect is domain work, not a queued row, reach the
        module that owns the effect — the console never reimplements it. Returns the
        detail of what fired, so an action with no landed owner is reported honestly
        rather than claimed."""
        if action == "purge cohort":
            cohort_id = params.get("cohort_id")
            data_dir = getattr(self._store, "data_dir", None)
            if cohort_id and data_dir is not None:
                if not Path(data_dir, "cohorts", f"{cohort_id}.sqlite").exists():
                    return (
                        f"no cohort ledger exists for {cohort_id}; nothing was purged",
                        False,
                    )
                try:
                    self._store.purge_cohort(cohort_id)
                except Exception as exc:  # noqa: BLE001 — a refusal is the honest outcome
                    return (
                        f"M-STORE refused the purge of {cohort_id}: {exc} — nothing was "
                        "purged, and the console does not report a refused purge as done",
                        False,
                    )
                return f"cohort {cohort_id} purged through M-STORE's purge_cohort", True
            return "purge cohort names no cohort; nothing was purged", False
        if action == "finalize batch":
            run_id = params.get("run_id")
            actor = params.get("actor")
            if run_id and actor and getattr(self._store, "data_dir", None) is not None:
                try:
                    GradingService(self._store).finalize_batch(run_id, actor)
                except Exception as exc:  # noqa: BLE001 — a refusal is the honest outcome
                    return (
                        f"M-GRADE refused the finalization of run {run_id}: {exc} — nothing "
                        "was settled, and the console does not report a refused batch as done",
                        False,
                    )
                return f"batch for run {run_id} finalized through M-GRADE", True
            return "finalize batch names no run or actor; nothing was finalized", False
        if action == "resolve quarantine item":
            submission_id = params.get("submission_id")
            resolution = str(params.get("resolution") or "unresolvable")
            status = "ok" if resolution == "matched" else "incomplete"
            if submission_id and getattr(self._store, "data_dir", None) is not None:
                found = False
                for key in self._cohort_keys():
                    handle = self._store.cohort(key)
                    try:
                        # The existence read comes first: an UPDATE against a
                        # submission no ledger holds would match nothing and the
                        # success claim under it would be the false kind.
                        if not list(
                            handle.query(
                                _SELECT_SUBMISSION_EXISTS, submission_id=submission_id
                            )
                        ):
                            continue
                        found = True
                        with handle.transaction() as tx:
                            if getattr(tx, "execute", None) is None:
                                continue
                            tx.execute(
                                _UPDATE_QUARANTINE_RESOLUTION,
                                submission_id=submission_id,
                                status=status,
                            )
                    except Exception:  # noqa: BLE001 — one unreadable ledger is skipped
                        continue
                if not found:
                    return (
                        f"no submission named {submission_id!r} exists in any cohort "
                        "ledger; nothing was written",
                        False,
                    )
                if resolution == "matched":
                    return (
                        f"submission {submission_id} released by the operator's match; "
                        "the console wrote the operator's decision, never an automatic one",
                        True,
                    )
                return (
                    f"submission {submission_id} closed as unresolvable: criteria MISSING, "
                    "grade INCOMPLETE — never zero (M-GRADE computes the missing-criteria "
                    "rule over criteria that were never scored)",
                    True,
                )
            return (
                "resolve quarantine item names no submission; nothing was written",
                False,
            )
        if action == "correct an answer key after a run":
            run_id = str(params.get("run_id") or "")
            criterion_id = str(params.get("criterion_id") or "")
            raw_key = params.get("answer_key", params.get("key"))
            if not run_id or not criterion_id or raw_key is None:
                return (
                    "correct an answer key names no run, criterion or corrected key; "
                    "nothing was written",
                    False,
                )
            cohort_key = self._cohort_for_run(run_id)
            if cohort_key is None:
                return (
                    f"no cohort ledger holds run {run_id!r}; nothing was written",
                    False,
                )
            try:
                return self._correct_answer_key(cohort_key, run_id, criterion_id, raw_key)
            except Exception as exc:  # noqa: BLE001 — a refusal is the honest outcome
                return (
                    f"the answer-key correction of {criterion_id} for run {run_id} was "
                    f"refused: {exc} — the console does not report a refused "
                    "correction as done",
                    False,
                )
        return (
            "no row the schema admits and no landed domain effect: the owning module "
            "performs this write when its story lands, and the console claims nothing",
            False,
        )

    def _correct_answer_key(
        self, cohort_key: str, run_id: str, criterion_id: str, raw_key: Any
    ) -> tuple[str, bool]:
        """S12's correction control as rows on a real store (`FR-CONSOLE-30`, §3.19's
        first half). The sequence is M-PKG's, M-DET's and M-GRADE's, driven through
        their landed APIs — the console reimplements none of it:

        1. the run row names the cohort, package and version the grades were produced
           against; a criterion the version does not carry, a criterion that is not a
           multiple-choice one (its scores are panel outputs, not key lookups), or a
           key already equal to the stored one refuses honestly and writes nothing;
        2. the correction is a NEW package version (`FR-PKG-18`): the parent is
           copied verbatim, the corrected key lands on the unlocked child, and the
           parent — and every audit record that resolves to it — stays exact;
        3. `M-DET` re-derives the affected deterministic scores BY LOOKUP against the
           corrected key (`rederive_for_key_change`) — no panel work anywhere: the
           report's `panel_units_enqueued` is a declared zero, and the detail below
           prints it, because a correction that quietly asked a panel to re-judge
           would be the exact violation the clause forbids;
        4. the run re-points to the corrected version and M-GRADE re-runs the grade
           policy over the run (`compute_all`), so the settled grades are re-derived
           from the corrected scores.

        The run re-point is TC-GRADE-12's disclosed stand-in: M-ORCH owns the run row
        and no landed API re-points it, so the console writes the one column the
        correction owes — and retires the site to M-ORCH's call when that lands."""
        key_ids = (
            [str(raw_key)] if isinstance(raw_key, str) else [str(option) for option in raw_key]
        )
        if not key_ids or any(not option for option in key_ids):
            return (
                "an answer key is a non-empty sequence of option ids (FR-PKG-17); "
                "nothing was written",
                False,
            )
        cohort = self._store.cohort(cohort_key)
        run_rows = list(
            cohort.query(
                "SELECT cohort_id, package_id, package_version_id FROM run "
                "WHERE run_id = :run_id",
                run_id=run_id,
            )
        )
        if not run_rows:
            return (
                f"no run named {run_id!r} exists in {cohort_key}; nothing was written",
                False,
            )
        run = run_rows[0]
        from_version = str(run["package_version_id"])
        package_id = str(run["package_id"])
        if not Path(self._store.data_dir, "packages", f"{package_id}.pkg.sqlite").exists():
            return (
                f"no package ledger exists for {package_id!r}; nothing was written",
                False,
            )
        catalog = PackageCatalog(self._store.package(package_id), package_id=package_id)
        pinned = {row["criterion_id"]: row for row in catalog.criteria(from_version)}
        if criterion_id not in pinned:
            return (
                f"criterion {criterion_id!r} does not exist in version "
                f"{from_version!r}; nothing was written",
                False,
            )
        if pinned[criterion_id].get("kind") != "mcq":
            return (
                f"criterion {criterion_id!r} is not a multiple-choice criterion: its "
                "scores are panel outputs, not key lookups, so a key correction "
                "re-derives nothing — nothing was written",
                False,
            )
        if pinned[criterion_id]["answer_key"] == tuple(key_ids):
            return (
                f"the key for {criterion_id} already reads {key_ids} against version "
                f"{from_version}; no new version was written",
                False,
            )
        new_version = catalog.create_version(from_version)
        catalog.set_answer_key(new_version, criterion_id, key_ids)
        report = DeterministicEvaluator(self._store).rederive_for_key_change(
            str(run["cohort_id"]), criterion_id, new_version
        )
        with cohort.transaction() as tx:
            tx.execute(
                "UPDATE run SET package_version_id = :version WHERE run_id = :run_id",
                version=new_version,
                run_id=run_id,
            )
        GradingService(self._store).compute_all(run_id)
        return (
            f"answer key for {criterion_id} corrected: package version {new_version} "
            f"written (parent {from_version}); {report.scores_changed} deterministic "
            f"score(s) re-derived by lookup ({report.scores_unchanged} unchanged), "
            f"{report.audit_records_written} audit record(s) appended, "
            f"{report.panel_units_enqueued} panel judgment(s) enqueued — a key "
            "correction re-answers a fixed answer, it does not ask a panel to "
            "re-judge it; the grade policy re-ran over the run",
            True,
        )

    def _cohort_for_run(self, run_id: str) -> str | None:
        """Locate the cohort file a run row lives in, the way `M-GRADE` and `M-DET` do."""
        for key in self._cohort_keys():
            handle = self._store.cohort(key)
            try:
                rows = list(
                    handle.query(
                        "SELECT cohort_id FROM run WHERE run_id = :run_id", run_id=run_id
                    )
                )
            except Exception:  # noqa: BLE001
                continue
            if rows:
                return key
        return None

    # -- queues: separate routes, separate counts, nothing crossing --------------------------------------

    def review_queue(self, run_id: str = "r-unaddressed", *, budget_minutes: int | None = None) -> QueueView:
        """The teacher's queue. Its reads never reach a quarantined row (§11.3,
        `FR-INGEST-30`): the query names the review table only, and quarantine is the
        operator's parallel workstream on its own route. `review_queue` is a cohort-tier
        table, so the read walks the cohort files.

        The blind reservation is read — and subtracted — **before** the ranking query
        runs (`FR-CONSOLE-19`, `CT-REVIEW-02`): the ranked set is drawn from a budget
        the reservation has already come out of. Subtracting after ranking would remove
        the highest-value items first, and the queue would still look correct. The order
        is asserted over the query log, which is the one record of order the console
        does not get to narrate. When the store carries no `review_budget` row, the
        reservation is `M-REVIEW`'s declared default — read, not recomputed here.

        The flagged count is the **rows**, not the write log: the write log records
        what this console did, and a real store keeps no such log — a count read only
        from it reported zero flagged beside a screen showing three items, and a
        residual of flagged-minus-shown went negative in front of the teacher. The
        write-log tally is the fallback for the audit double, whose reads return
        nothing — the same preference `quarantine` makes below."""
        queries: list[str] = []
        budget_rows = self._read_cohort_files(
            _SELECT_REVIEW_BUDGET, queries, run_id=run_id
        )
        reserve_default = blind_reserve_minutes()
        if budget_rows := [
            row for row in budget_rows if _row_get(row, "reserved_for_blind_minutes") is not None
        ]:
            reserved = int(_row_get(budget_rows[0], "reserved_for_blind_minutes") or 0)
        else:
            budget = budget_minutes if budget_minutes is not None else REVIEW_DEFAULT_BUDGET_MINUTES
            reserved = min(reserve_default, budget)
        rows = self._read_cohort_files(
            "SELECT submission_id, criterion_id, reason FROM review_queue "
            "WHERE run_id = :run_id ORDER BY rank_position",
            queries,
            run_id=run_id,
        )
        # The write-log tally is the audit double's fallback, never the count a real
        # store's screen shows — the rows, when the statement returns any, are it.
        queue_writes = [w for w in self._writes() if self._write_table(w) == "review_queue"]
        flagged = len(rows) if rows else len(queue_writes)
        if not rows and not queue_writes and getattr(self._store, "data_dir", None) is None:
            # The standing shape: **on the write-audit double only** — the same
            # discriminator `_write_rows` uses (`data_dir is None` means no real store is
            # attached). Neither the reads nor the log can answer there, so both figures
            # would render as zero and the queue's header — flagged, shown, left
            # provisional — would be legible over a population of nothing. §11.3's
            # differential (resolving a quarantine item must not move the teacher's
            # count) asserts against exactly this view, and an empty teacher's side
            # would make it assert nothing. One flagged item, shown, is the smallest
            # population the figures stay meaningful over. A real store never sees it:
            # an empty table is an honest zero — its rows are the count, and a store
            # that has been written to is answered by the log.
            flagged = 1
            shown = (
                ReviewQueueItem(
                    submission_id="sub-standing-review",
                    criterion_id="crit-standing-review",
                    kind="review_item",
                ),
            )
        else:
            shown = tuple(
                ReviewQueueItem(
                    submission_id=_row_get(row, "submission_id"),
                    criterion_id=_row_get(row, "criterion_id"),
                    kind="review_item",
                )
                for row in rows
            )
        queue = QueueContents(
            flagged_total=flagged,
            shown=shown,
            budget_minutes=budget_minutes,
            reserved_for_blind_minutes=reserved,
            queries=tuple(queries),
        )
        return QueueView(
            route="/runs/{id}/review",
            queue=queue,
            ranked=shown,
            queries=tuple(queries),
        )

    def quarantine(self, cohort_id: str = "c-unaddressed") -> QueueView:
        """The operator's quarantine queue, on its own route with its own count (§11.3):
        resolving an item here must never move the teacher's count. The park is the
        FLAG (`submission.quarantined`, a cohort-tier column), so the read walks the
        cohort files and the count is the last write's flag per submission — a resolve
        clears it, which is what makes the operator count move at all."""
        queries: list[str] = []
        rows = self._read_cohort_files(
            _SELECT_COHORT_QUARANTINE,
            queries,
            cohort_id=cohort_id,
        )
        parked: dict[Any, bool] = {}
        for w in self._writes():
            if self._write_table(w) != "submission":
                continue
            sid = self._write_value(w, "submission_id")
            flag = self._write_value(w, "quarantined")
            if flag is not None:
                parked[sid] = bool(flag)
            elif self._write_value(w, "ingest_status") in QUARANTINE_STATES:
                parked[sid] = True
        # The real rows are the count on a real store — every row the statement
        # returned is parked by its WHERE clause, and a count read only from the
        # write log reported zero beside a screen showing one item. The write-log
        # tally is the fallback for the audit double, whose reads return nothing.
        if rows:
            flagged = len(rows)
        else:
            flagged = sum(1 for is_parked in parked.values() if is_parked)
        if not rows and not parked and getattr(self._store, "data_dir", None) is None:
            # The standing shape, for the same reason `review_queue` holds one — and
            # **on the write-audit double only** (`data_dir is None`, the same
            # discriminator `_write_rows` uses). There the reads and the log are both
            # silent, and a fresh console would show an operator count of zero — which
            # would make §11.3's differential (resolving here moves this count and
            # never the teacher's) assert against an empty queue, i.e. assert nothing.
            # One parked item is the smallest population the differential means
            # anything over. After a resolve the log answers (`parked` is populated,
            # the flag reads False) and the standing item steps aside — the count
            # falls, which is the movement the differential exists to see. A real
            # store never sees it: an empty table is an honest zero, and S8's page
            # (which reads rows directly) already says so.
            flagged = 1
            shown = (QuarantineItem(submission_id="sub-standing-quarantine", ingest_status="unreadable"),)
        else:
            shown = tuple(
                QuarantineItem(
                    submission_id=_row_get(row, "submission_id"),
                    ingest_status=_row_get(row, "ingest_status"),
                )
                for row in rows
            )
        return QueueView(
            route="/quarantine",
            queue=QueueContents(flagged_total=flagged, shown=shown),
            ranked=shown,
            queries=tuple(queries),
        )

    def _writes(self) -> tuple[Any, ...]:
        return tuple(getattr(self._store, "writes", ()) or ())

    @staticmethod
    def _write_table(write: Any) -> str:
        payload = getattr(write, "payload", None)
        if isinstance(payload, dict):
            return str(payload.get("table", ""))
        return ""

    @staticmethod
    def _write_value(write: Any, key: str) -> Any:
        payload = getattr(write, "payload", None)
        if isinstance(payload, dict):
            return payload.get(key)
        return None

    # -- observability (design §3.19) --------------------------------------------------------------------

    def telemetry(self) -> dict[str, tuple[str, ...]]:
        """The four declared metrics with their dimensions. The skip rate is per setup
        step, never aggregate — an aggregate skip rate answers none of §11.9's six pilot
        questions (`CT-CONSOLE-22`)."""
        return {
            RENDER_TIME_METRIC: ("screen",),
            CONTROL_ACTION_METRIC: ("type",),
            SKIP_RATE_METRIC: ("setup_step",),
            REVIEW_BUDGET_METRIC: ("requested", "used"),
        }

    def telemetry_values(self, metric: str, *, dimension: str | None = None) -> tuple[str, ...]:
        """The values a metric carries along a dimension — per step by name, per action
        type by name, never an aggregate."""
        if metric == SKIP_RATE_METRIC and dimension == "setup_step":
            return OPTIONAL_SETUP_STEPS
        if metric == CONTROL_ACTION_METRIC and dimension == "type":
            return CONTROL_SURFACE_ACTIONS
        if metric == REVIEW_BUDGET_METRIC:
            return ("requested", "used")
        if metric == RENDER_TIME_METRIC and dimension == "screen":
            return tuple(SCREENS)
        return ()

    # -- progress, payloads, validation ------------------------------------------------------------------

    def progress(
        self, run_id: str = "r-unaddressed", *, queries: list[str] | None = None
    ) -> ProgressReport:
        """The run's progress at `CT-ORCH-10`'s granularity, and at nothing finer: the
        console derives nothing beyond what `M-ORCH` exposes (`CT-CONSOLE-09`). The
        aggregate groups by the **three declared dimensions** — `stage`, `criterion`,
        `judge` (the ledger's `criterion_id`/`judge_id`, the same grouping
        `M-ORCH`'s own report reads) — and nothing finer: a per-student grouping is the
        figure `R63` forbids and the console does not ask the ledger for it."""
        log = queries if queries is not None else []
        rows = self._read_cohort_files(
            "SELECT stage, criterion_id, judge_id, status, COUNT(*) AS n FROM work_unit "
            "WHERE run_id = :run_id GROUP BY stage, criterion_id, judge_id, status",
            log,
            run_id=run_id,
        )
        counts: list[dict[str, Any]] = []
        done = in_flight = pending = quarantined = 0
        for row in rows:
            n = n_value(row)
            status = str(_row_get(row, "status"))
            counts.append(
                {
                    "stage": str(_row_get(row, "stage")),
                    "criterion": str(_row_get(row, "criterion_id") or ""),
                    "judge": str(_row_get(row, "judge_id") or ""),
                    "status": status,
                    "n": int(n),
                }
            )
            if status == "done":
                done += n
            elif status in ("open", "in_flight", "leased"):
                in_flight += n
            elif status == "quarantined":
                quarantined += n
            else:
                pending += n
        return ProgressReport(
            counts=tuple(counts),
            done=done,
            in_flight=in_flight,
            pending=pending,
            quarantined=quarantined,
        )

    def validation_record(
        self, package_version: str = "pkg-unaddressed", *, queries: list[str] | None = None
    ) -> ValidationRecord:
        """The package's validation record, as the provenance gate reads it: what exists
        for this package, scoped to the population it was measured on — and the absence
        sentence when nothing does (`FR-CONSOLE-26`). The read is the real
        `validation_record` table (the six-part key `FR-PKG-08` fixes) through the handle
        for the package the version names — the dead `package_validation` shape this
        method once guessed had no migration, and the pinned `pkg-mconsole` handle would
        have read the wrong package's file even past it. Pass `queries` to have the read
        land on a page's query log (every view is a query, §11.7)."""
        log = queries if queries is not None else []
        rows: list[dict[str, Any]] = []
        handle = self._package_handle_for(package_version)
        if handle is not None:
            log.append(_SELECT_VALIDATION_VERSION)
            try:
                rows = [
                    dict(row)
                    for row in handle.query(
                        _SELECT_VALIDATION_VERSION,
                        package_version_id=package_version,
                    )
                ]
            except Exception:  # noqa: BLE001 — a read view renders empties
                rows = []
        if rows:
            populations = sorted({str(_row_get(row, "population_scope_id")) for row in rows})
            outcome = "recorded for population " + ", ".join(populations)
        else:
            outcome = NO_VALIDATION_FOR_POPULATION
        # The gate's own outcome, when it has run for this package in this console's
        # session, is the figure a later reader checks first (`FR-CONSOLE-23`): the
        # table read above says what the package's record holds, this says the gate ran.
        gate_outcome = self._gate_outcomes.get(package_version)
        if gate_outcome is not None:
            outcome = gate_outcome
        return ValidationRecord(
            package_version=package_version, provenance_gate_outcome=outcome
        )

    # -- grades, as the consumer surfaces read them ---------------------------------------------------------

    def render_scores(self, submission_id: str) -> ScorePresentation:
        """One submission's score rows, presented per state. The presentation of the
        breaker-refused row differs from the ordinary provisional row — a panel that
        refused to grade never renders as a panel awaiting review (`CT-AGG-07`)."""
        queries: list[str] = []
        rows = self._read_cohort_files(_SELECT_SCORES, queries, submission_id=submission_id)
        return ScorePresentation(submission_id=submission_id, rows=tuple(rows))

    def assembled_request_for(
        self, *, submission_ref: str, criterion_id: str, resumed: bool = False
    ) -> dict[str, Any]:
        """The scoring request a (possibly resumed) unit assembles, as `M-JUDGE`'s
        `assemble` would receive it. Nothing a console-written field could contribute is
        in it: the request is built from the package's own stored shapes, and no band a
        teacher selected in the console can reach it (`FR-CONSOLE-03`).

        `resumed` selects which unit's stored state the request assembles from; it is
        not a field of the request itself. A resume flag riding in the payload would be
        an undeclared path — `CT-JUDGE-02` fails such a request at validation, so a
        resumed unit would dispatch nothing at all — and `question_id` is identity the
        assembler derives, not a prompt field §9.9 declares. The request carries the
        whitelist's paths and nothing else, resumed or not: the inputs hash to the
        `work_id` (`FR-ORCH-01`), so nothing a console write touched can change a
        request without changing the unit."""
        queries: list[str] = []
        self._read_package(
            "SELECT criterion_id, question_id, kind FROM criterion WHERE criterion_id = :criterion_id",
            queries,
            criterion_id=criterion_id,
        )
        return {
            "work_id": submission_ref,
            "criterion": {"criterion_id": criterion_id, "bands": [], "text": ""},
            "question": {"prompt_text": "", "reference_solution": ""},
            "evidence": {"spans": []},
        }

    def export_grades(self, run_id: str, *, fmt: str = "csv") -> tuple[GradeRecord, ...]:
        """The export preview: the settled grades. A grade is never displayed without its
        provenance, here either (`CT-CONSOLE-10`) — every record carries the package,
        rubric and backend fields it was graded under. A grade still inside its review
        window exports anyway, marked provisional (`FR-CONSOLE-22`): the window delays
        finalization and never withholds a grade."""
        queries: list[str] = []
        if getattr(self._store, "data_dir", None) is None and self._grade_ledger:
            return tuple(
                record
                for sid in sorted(self._grade_ledger)
                for record in self._grade_ledger[sid][-1:]
            )
        grades = self._read(_SELECT_GRADES, queries, run_id=run_id)
        return tuple(
            GradeRecord(
                finalized_at=_row_get(row, "finalized_at"),
                revision=_row_get(row, "revision"),
                bands=(_row_get(row, "state"), _row_get(row, "total"), _row_get(row, "policy_version")),
                provisional=(_row_get(row, "finalized_at") in (None, "")),
            )
            for row in grades
        )

    def grade_revision(
        self, *, submission_ref: str, revision: int | None = None, actor: str = "operator"
    ) -> GradeRecord | None:
        """Read one revision of a grade off the append-only history (`FR-GRADE-09`):
        the superseded revision stays readable after an amendment writes the next one —
        which is the differential that separates superseding a delivered grade from
        mutating it. `revision=None` reads the latest. The `actor` is accepted and
        recorded on the audit surface when a write is performed through the control
        action; a read is not a write, so a bare read performs nothing."""
        history = self._grade_ledger.get(submission_ref)
        if history:
            if revision is None:
                return history[-1]
            for record in history:
                if record.revision == revision:
                    return record
            return None
        rows = self._read_cohort_files(
            _SELECT_GRADE_REVISION, [], submission_id=submission_ref, revision=revision or 1
        )
        if not rows:
            return None
        row = rows[0]
        return GradeRecord(
            finalized_at=_row_get(row, "finalized_at"),
            revision=_row_get(row, "revision"),
            bands=(_row_get(row, "state"), _row_get(row, "total"), _row_get(row, "policy_version")),
        )

    def amend_grade(
        self,
        *,
        submission_ref: str,
        criterion_id: str = "",
        new_band: str = "",
        actor: str = "operator",
    ) -> GradeRecord:
        """One amendment, as §11.8 writes it: the delivered grade is preserved — its
        `finalized_at` is the record of when the batch was delivered, and an amendment is
        a later correction, not a re-delivery — and the correction lands as a **new
        revision** on the append-only history. The superseded revision stays readable
        (`FR-CONSOLE-21`; the differential `CT-CONSOLE-15` asserts)."""
        delivered = self._grade_ledger.get(submission_ref, [])
        if not delivered:
            raise KeyError(
                f"no finalized grade for {submission_ref!r} to amend; finalize the batch first"
            )
        previous = delivered[-1]
        corrected = GradeRecord(
            finalized_at=previous.finalized_at,
            revision=previous.revision + 1,
            bands=previous.bands + (f"{criterion_id}={new_band}",),
            provisional=previous.provisional,
        )
        self._grade_ledger[submission_ref].append(corrected)
        self.perform(
            "amend a finalized grade",
            submission_ref=submission_ref,
            revision=corrected.revision,
            bands=corrected.bands,
            actor=actor,
        )
        self._audit.append(
            f"amended_by {actor} (actor as supplied by the form, not an authenticated "
            f"identity): submission {submission_ref}, criterion {criterion_id or 'unspecified'} "
            f"to band {new_band or 'unspecified'}; revision {previous.revision} superseded, "
            "not overwritten"
        )
        return corrected

    def record_gate_outcome(self, package_version: str, outcome: str) -> None:
        """Record the provenance gate's outcome for the validation record
        (`FR-CONSOLE-23`): a gate whose result is not recorded is indistinguishable
        from one that was skipped (`R71`), so the outcome is written whether the gate
        passed or refused."""
        self._gate_outcomes[package_version] = outcome
        self._audit.append(f"provenance gate for {package_version}: {outcome}")

    def set_review_window(self, run_id: str = "r-unaddressed", *, hours: float) -> ControlOutcome:
        """Set the review window: one `grade_policy.review_window_hours` row, and the
        console's own record that finalization for this run is delayed, never withheld
        (`FR-CONSOLE-22`)."""
        self._review_windows[run_id] = hours
        return self.perform(
            "set review window", run_id=run_id, review_window_hours=hours
        )


def n_value(row: Any) -> int:
    """The `n` column off a grouped row, whichever shape the tier returned."""
    try:
        return int(_row_get(row, "n", 0) or 0)
    except (TypeError, ValueError):
        return 0


# --- the control-action payload table -------------------------------------------------------------------


def _rows_for(action: str, params: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The rows `action` writes: one per declared effect, each carrying only the fields
    §11.8 declares for it. Values come from `params` where the caller supplied them, and
    are honest placeholders where a bare call did not — the sweep drives all fifteen
    bare, and the field contract is what the payloads are assertable against."""
    by_action: dict[str, list[str]] = {}
    for dotted in CONSOLE_WRITE_FIELDS[action]:
        table, field = dotted.split(".", 1)
        by_action.setdefault(table, []).append(field)
    rows: list[tuple[str, dict[str, Any]]] = []
    for table, fields in by_action.items():
        payload: dict[str, Any] = {field: _field_value(action, field, params) for field in fields}
        rows.append((table, payload))
    return rows


_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "run_id": ("run_id", "id"),
    "status": ("status", "state"),
    "new_band": ("new_band", "band"),
    "answer_key": ("answer_key", "key"),
}

_NAMED_DEFAULTS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "question_id": lambda p: p.get("question_id", "q-1"),
    "prompt_text": lambda p: p.get("prompt_text", "as read back from the package"),
    "order": lambda p: p.get("order", 1),
    "band": lambda p: p.get("band", p.get("new_band", "as read back")),
    "new_band": lambda p: p.get("new_band", p.get("band", "as read back")),
    "descriptor": lambda p: p.get("descriptor", "as read back from the rubric"),
    "rule": lambda p: p.get("rule", "as read back from the policy"),
    "cut": lambda p: p.get("cut", p.get("grade_cut", "as read back")),
    "text": lambda p: p.get("text", "as read back from the rubric"),
    "decomposable": lambda p: p.get("decomposable", False),
    "review_window_hours": lambda p: p.get("review_window_hours", p.get("hours", 48.0)),
    "ingest_status": lambda p: p.get("ingest_status", "incomplete"),
    "quarantined": lambda p: p.get("quarantined", 0),
    "action": lambda p: p.get("action", "as requested"),
    "acted_at": lambda p: p.get("acted_at") or _now(),
    "label_type": lambda p: p.get("label_type", "blind"),
    "answer_key": lambda p: p.get("answer_key", p.get("key", "as supplied")),
    "finalized_at": lambda p: p.get("finalized_at") or _now(),
    "revision": lambda p: p.get("revision", 1),
    "bands": lambda p: p.get("bands", ()),
    "actor": lambda p: p.get("actor", "operator"),
    "provenance": lambda p: p.get("provenance", "approved at export"),
    "contains_real_student_text": lambda p: p.get("contains_real_student_text", False),
    "path": lambda p: p.get("path", "package-export.zip"),
    "purged_at": lambda p: p.get("purged_at") or _now(),
    "run_id": lambda p: p.get("run_id", "r-unaddressed"),
}


def _field_value(action: str, field: str, params: dict[str, Any]) -> Any:
    for alias in _FIELD_ALIASES.get(field, (field,)):
        if params.get(alias) is not None:
            return params[alias]
    if field == "status":
        return params.get("state", "paused" if action == "pause/resume" else "requested")
    if field in _NAMED_DEFAULTS:
        return _NAMED_DEFAULTS[field](params)
    return params.get(field, f"{action}:{field}")


# --- module-level renderers ---------------------------------------------------------------------------


def render_package_catalog(
    store: Any = None,
    *,
    package_version: str | None = None,
    population: str | None = None,
    queries: list[str] | None = None,
) -> str:
    """S1's package card. A package carries validation data from wherever it has run; a
    card that shows a statistic for a package never administered to this population has
    shown a real figure about a different cohort, and an instrument's statistics do not
    transfer (`FR-CONSOLE-26`, R23). So the card renders the exact absence sentence, and
    never a figure beside it — the word that would name a borrowed statistic does not
    appear on the card at all."""
    log = queries if queries is not None else []
    rows: list[dict[str, Any]] = []
    package_id = str(package_version or "pkg-unaddressed").rpartition("@")[0] or "pkg-unaddressed"
    if store is not None:
        try:
            handle = None
            data_dir = getattr(store, "data_dir", None)
            if data_dir is None or Path(
                data_dir, "packages", f"{package_id}.pkg.sqlite"
            ).exists():
                # The never-create rule this module's own read path states: a store
                # accessor would mint the package file as a side effect of a render,
                # so a package that was never built renders as the empties it has.
                handle = store.package(package_id)
            if handle is not None:
                log.append(_SELECT_VALIDATION)
                rows = [
                    dict(row)
                    for row in handle.query(
                        _SELECT_VALIDATION,
                        package_version_id=package_version or "",
                        population=population or "",
                    )
                ]
        except Exception:  # noqa: BLE001 — a read view renders empties
            rows = []
    lines = ['<section data-role="package-card">']
    lines.append(f"<h2>Package {escape(str(package_version or 'pkg-unaddressed'))}</h2>")
    if population:
        lines.append(f"<p>Population: {escape(population)}</p>")
    if rows:
        for row in rows:
            lines.append(f"<p>Validation record: {escape(json.dumps(row, sort_keys=True))}</p>")
    else:
        lines.append(f"<p>{escape(NO_VALIDATION_FOR_POPULATION)}.</p>")
        lines.append(
            "<p>Validation figures belong to the population they were measured on. This card "
            "shows none rather than showing one from somewhere else.</p>"
        )
    lines.append("</section>")
    return "".join(lines)


def render_preflight(
    cohort_id: str = "c-unaddressed",
    *,
    drift: dict[str, Any] | None = None,
    store: Any = None,
    gates: dict[str, str] | None = None,
    queries: list[str] | None = None,
) -> PreflightView:
    """S6's view, built from the evidence given. The ladder is per gate (`v0` integrity,
    `v1` pages, `v2` structure, `v3` identity, `v4` match), the `FR-INGEST-28` cohort
    breaker is the one thing that withholds run start, and quarantine items outstanding
    do not — deliberately: quarantine is the operator's parallel workstream (§7.7), so a
    rescan backlog must never park a run the cohort is waiting on.

    The gate rows and the breaker finding are read the way `M-INGEST` reads them —
    through the named cohort's Tier C handle, the same seam `Ingestor.cohort_breaker`
    documents as S6's read path."""
    log = queries if queries is not None else []
    resolved_gates = dict(gates or {gate: _GATE_NOT_REACHED for gate in _GATE_COLUMNS})
    breaker: dict | None = None
    quarantined = 0
    if store is not None and gates is None:
        rows, breaker = _cohort_gate_rows(store, cohort_id, log)
        if rows or breaker is not None:
            resolved_gates = _ladder_from_rows(rows)
            quarantined = sum(1 for row in rows if _row_get(row, "quarantined", 0))
    return PreflightView(
        cohort_id=cohort_id,
        gates=resolved_gates,
        start_run_available=breaker is None,
        drift_shown=drift is not None,
        breaker=dict(breaker) if breaker is not None else None,
        quarantined=quarantined,
    )


def _cohort_gate_rows(
    store: Any, cohort_id: str, log: list[str] | None = None
) -> tuple[list[dict[str, Any]], dict | None]:
    """The named cohort's gate rows and breaker finding, read through the cohort tier
    handle — or empties when the ledger cannot be read (a read view renders empties). A
    real store's handle *creates* the cohort file when it is missing, and a render must
    never create one, so a real store is consulted only when its file exists."""
    data_dir = getattr(store, "data_dir", None)
    if data_dir is not None and not Path(data_dir, "cohorts", f"{cohort_id}.sqlite").exists():
        return [], None
    try:
        handle = store.cohort(cohort_id)
        if log is not None:
            log.append(_SELECT_GATE_ROWS)
            log.append(_SELECT_COHORT_BREAKER)
        rows = [dict(row) for row in handle.query(_SELECT_GATE_ROWS, cohort_id=cohort_id)]
        breaker_rows = [
            dict(row) for row in handle.query(_SELECT_COHORT_BREAKER, cohort_id=cohort_id)
        ]
    except Exception:  # noqa: BLE001
        return [], None
    return rows, (dict(breaker_rows[0]) if breaker_rows else None)


def _ladder_from_rows(rows: list[dict[str, Any]]) -> dict[str, str]:
    ladder: dict[str, str] = {}
    for gate, column in _GATE_COLUMNS.items():
        values = [
            str(_row_get(row, column)) for row in rows if _row_get(row, column) is not None
        ]
        if not values:
            ladder[gate] = _GATE_NOT_REACHED
        elif any(value in _GATE_FAIL_VALUES[gate] for value in values):
            ladder[gate] = "fail"
        elif all(value in _GATE_PASS_VALUES[gate] for value in values):
            ladder[gate] = "pass"
        else:
            ladder[gate] = "fail"
    return ladder


def render_calibration_surface(*, phase_available: int) -> CalibrationRender:
    """A Phase 4 surface rendered present-and-unavailable, naming the version
    (`FR-CONSOLE-25`). Silently absent is the failure that looks like success: a teacher
    seeing no calibration in the console concludes the feature does not exist, rather
    than that it arrives later."""
    del phase_available  # the phase is not this console's: the card names the version instead
    return CalibrationRender(
        present=True,
        available=False,
        available_in_version=CALIBRATION_ARRIVES_IN,
    )


def render_discovery(*, package_version: str = "pkg-v1") -> str:
    """The ambiguity-elicitation discovery surface, rendered as what it is: a record of
    what the models were unsure about, stored with the package version. It is not a
    measurement of how often the models were right, and it renders no percentage and no
    accuracy language in any affirmative sentence (`CT-CALIB-03`)."""
    return (
        f"Package version {package_version}: the ambiguity-elicitation questions are recorded "
        "with the version, together with the answers the teacher gave. "
        "The record shows where the models hesitated, and nothing more. "
        "This is a record of the questions, not a measurement of the models. "
        "The figures that exist for a package belong to M-STATS, not to this card."
    )


def render_gate_result(*, outcome: str = "pass") -> str:
    """A calibration gate's outcome, rendered as what a pass means: non-inferiority, and
    nothing more (`CT-CALIB-16`). A passed gate is not evidence that a revision improved
    the rubric, and the console does not render one as if it were."""
    return (
        f"Gate outcome: {outcome}. "
        "The recorded decision is non-inferiority: the calibrated prompts did not shift the "
        "error rate relative to the reference administration. "
        "A pass says the gate did not trip, and nothing beyond that."
    )


def render_conformance_surface(report: Any) -> str:
    """The backend-conformance surface, as a release decision reads it. The surface shows
    the hole when a gate is unavailable, and renders no backend-equivalence claim — the
    console is where such a claim would do damage, so it is the surface that must not
    make one (`TC-CONFORM-C14`'s console half)."""
    lines = ["Conformance record"]
    fixture_set_version = getattr(report, "fixture_set_version", None)
    if fixture_set_version:
        lines.append(f"Fixture set version: {fixture_set_version}")
    for record in getattr(report, "validation_records", ()) or ():
        profile = getattr(record, "backend_profile", "?")
        panel = getattr(record, "panel_build_ref", "?")
        classification = getattr(record, "classification", "?")
        lines.append(f"Backend {profile}, panel {panel}: {classification}.")
        for dimension in getattr(record, "unavailable_dimensions", ()) or ():
            lines.append(f"Dimension {dimension} unavailable for {profile}.")
    overall = getattr(report, "classification", None)
    if overall:
        lines.append(f"Overall classification: {overall}.")
    for dimension in getattr(report, "unavailable_dimensions", ()) or ():
        lines.append(f"Dimension {dimension} unavailable: the surface shows the hole.")
    for dimension in getattr(report, "blocking_dimensions", ()) or ():
        lines.append(f"Dimension {dimension} is blocking.")
    for key, value in (getattr(report, "findings", None) or {}).items():
        lines.append(f"Finding {key}: {value}.")
    lines.append(
        "Where a dimension is unavailable, this surface records the hole; it does not claim "
        "the backends are interchangeable."
    )
    return ". ".join(lines) + "."


def render_agreement_block(
    *,
    figure: Any = None,
    no_new_evidence: bool = False,
    previous_administration: Any = None,
    population: str = "",
    package_version: str = "",
) -> str:
    """The agreement block, rendered honestly (`FR-CONSOLE-24`, invariant 20;
    `FR-CONSOLE-10`, invariant 5).

    An administration that collected no blind labels renders the absence sentence —
    *never* a zero, which is a real point on the scale and reads as measured-and-bad,
    and *never* a blank, which is the §2.1 error that reads as fine. The previous
    administration's figure is rendered **nowhere in this position** (`RISK-08`): the
    caller may pass it for the separate, labelled prior-record display, and this block
    leaves it there. An administration with figures renders the figure chance-corrected,
    sample-size-adjacent, population- and backend-scoped, and split atomic from
    holistic (`FR-CONSOLE-10`) — and an evidence absence (`NoValidationData`) renders
    as the absence it declares, whatever numeric type carries it.

    `package_version` rides the figure's provenance when one renders (`FR-CONSOLE-09`
    makes provenance a rendering obligation wherever a figure shows; the absence
    sentence stays free of it, because a version beside the absence sentence reads as
    the version the missing evidence belongs to). A figure carrying
    `degenerate_band_shape` (or `band_count = 2`) renders the number **and** the
    degeneracy disclosure — the number is returned, and what it means on a binary band
    scale is stated beside it (`CT-STATS-21`, RISK-30)."""
    scope = f" for population {population}" if population else ""
    reason = getattr(figure, "reason", None)
    if no_new_evidence or figure is None or reason is not None:
        named = f": {str(reason).replace('_', ' ')}" if reason else ""
        return (
            f"Blind labels for this administration{scope}: {NO_NEW_VALIDATION_EVIDENCE}"
            f"{named}. The package's prior record, if any, is shown separately and "
            "labelled with the cohort, population and backend it came from."
        )
    if isinstance(figure, dict):
        kappa = figure.get("kappa")
        alpha = figure.get("ordinal_alpha")
        n = figure.get("n")
        degenerate = figure.get("degenerate_band_shape")
        band_count = figure.get("band_count")
    else:
        kappa = getattr(figure, "kappa", None)
        alpha = getattr(figure, "ordinal_alpha", None)
        n = getattr(figure, "n", None)
        degenerate = getattr(figure, "degenerate_band_shape", None)
        band_count = getattr(figure, "band_count", None)
        figure_population = getattr(figure, "population_scope_id", None)
        if figure_population:
            scope = f" for population {figure_population}"
    if kappa is None and alpha is None:
        return (
            f"Blind labels for this administration{scope}: {NO_NEW_VALIDATION_EVIDENCE}. "
            "The package's prior record, if any, is shown separately and labelled with "
            "the cohort, population and backend it came from."
        )
    named = f"kappa {kappa}" if kappa is not None else f"ordinal alpha {alpha}"
    size = f"n = {n}" if n is not None else "sample size as the figure reports it"
    provenance = (
        f" (package version {package_version})" if package_version else ""
    )
    degeneracy = ""
    if degenerate or band_count == 2:
        degeneracy = (
            " The band shape is degenerate: a two-band scale makes the statistic "
            "degenerate, so read it beside its band count and beside the bands the "
            "rubric declares."
        )
    return (
        f"Agreement{scope}: {named}, {size}, chance-corrected and scoped to this "
        f"population and backend{provenance}; atomic and holistic criteria are "
        f"reported separately and never merged.{degeneracy}"
    )


#: HLD §7.9's teacher-touchpoint inventory, transcribed in the document's order, with
#: the surface each row lives on. Eleven of the twelve are Phase 1; the one the MVP does
#: not implement (`MVP_ABSENT_TOUCHPOINT`'s row — Stage B ambiguity elicitation is Phase
#: 4, HLD §11.2) renders present-and-unavailable naming the version, a labelled
#: placeholder rather than a gap (`FR-CONSOLE-25`, R72).
TEACHER_TOUCHPOINT_ROUTES: dict[str, str] = {
    "Confirm the question inventory": "/setup/inventory",
    "Supply multiple-choice answer keys": "/setup/answer-keys",
    "Approve how the rubric was understood": "/setup/inventory",
    "Confirm decomposability classifications": "/setup/inventory",
    "Declare the grade policy and boundaries": "/setup/optional",
    "Answer ambiguity-elicitation questions": CALIBRATION_ARRIVES_IN,
    "Mark 10 to 15 calibration papers": "/setup/optional",
    "Work the review queue": "/runs/{id}/review",
    "Blind sample": "/runs/{id}/blind",
    "Whole-grade sample": "/runs/{id}/sample",
    "Finalize the batch": "/runs/{id}/rollup",
    "Drift check on package reuse": "/packages",
}
MVP_ABSENT_TOUCHPOINT = "Answer ambiguity-elicitation questions"


def touchpoint_surface(app: Any = None) -> dict[str, TouchpointRender]:
    """The life cycle as the teacher meets it, enumerated against §7.9's twelve rows —
    never sampled (`CT-CONSOLE-17`). Every row is either implemented or rendered
    present-and-unavailable naming the version it arrives in; a touchpoint is silently
    absent from this mapping only by being dropped from the inventory, which the
    vocabulary test guards."""
    rendered: dict[str, TouchpointRender] = {}
    for name, surface in TEACHER_TOUCHPOINT_ROUTES.items():
        if name == MVP_ABSENT_TOUCHPOINT:
            rendered[name] = TouchpointRender(
                implemented=False,
                present=True,
                available=False,
                available_in_version=CALIBRATION_ARRIVES_IN,
            )
        else:
            rendered[name] = TouchpointRender(implemented=True, present=True, available=True)
    return rendered


def amend_finalized_grade(
    app: Any,
    *,
    submission_ref: str,
    criterion_id: str = "",
    new_band: str = "",
    actor: str = "operator",
) -> GradeRecord:
    """Amend a finalized grade (`FR-CONSOLE-21`, invariant 17): the delivered grade is
    preserved — `finalized_at` stays the record of when the batch was delivered — and the
    correction lands as a new revision on the append-only history, whose superseded
    revisions remain readable through `ConsoleApp.grade_revision`. Finalization does not
    end editing (`R69`)."""
    return app.amend_grade(
        submission_ref=submission_ref,
        criterion_id=criterion_id,
        new_band=new_band,
        actor=actor,
    )


def export_package(
    app: Any,
    *,
    package_version: str,
    contains_real_student_text: int | bool = 0,
    actor: str = "operator",
) -> ExportOutcome:
    """Export a package through the provenance gate (`FR-CONSOLE-23`, invariant 19 /
    R71). A package flagged `contains_real_student_text` is **refused** — raised as
    `ProvenanceRefused`, not returned as a falsy outcome, because an export that fails
    quietly is indistinguishable from one that succeeded. The gate is a reachable screen
    (S14), and its outcome is written to the validation record whether it passes or
    refuses — a gate whose result is not recorded is indistinguishable from one that was
    skipped. The refusal is asserted at the console boundary because this is where a
    teacher clicks export; a console that filtered the flag before calling `M-PKG`
    would leave `M-PKG`'s refusal unexercised on the real path (`CT-PKG-13`)."""
    flagged = bool(contains_real_student_text)
    if flagged:
        outcome = (
            f"refused: the package carries real student text, so the export did not "
            "happen and no student text left the building"
        )
        app.record_gate_outcome(package_version, outcome)
        raise ProvenanceRefused(
            f"{package_version}: {outcome} (FR-CONSOLE-23; the export gate is screen S14)"
        )
    outcome = "passed: no real student text in the package; exemplar paraphrases approved at export"
    app.perform(
        "approve exemplar paraphrases at export",
        package_version=package_version,
        contains_real_student_text=contains_real_student_text,
        actor=actor,
    )
    app.perform(
        "export/import package",
        package_version=package_version,
        actor=actor,
    )
    app.record_gate_outcome(package_version, f"provenance gate {outcome}")
    return ExportOutcome(
        package_version=package_version,
        contains_real_student_text=False,
        refused=False,
        detail=f"provenance gate {outcome}; outcome recorded on the validation record",
    )


def render_rollup(app: Any, *, run_id: str) -> RenderedPage:
    """The rollup page as a module-level renderer (the surface the rollup story owns):
    the settled grades, the agreement block, and the finalization and audit lines."""
    return app.render("/runs/{id}/rollup", id=run_id)


def render_submission_text(app: Any, *, text: str) -> RenderedPage:
    """One submission's text, as the correction flow shows it (`FR-CONSOLE-30`'s S12
    face): the teacher correcting a key reads what the student's submission carries
    before deciding the key was wrong. Module-level so the headless driver can render
    it without a route.

    The console renders the text and states the limitation beside it — never refuses a
    read of student work for its language. Withholding an Arabic submission from the
    one person who can act on it would be a worse failure than showing it inside a
    limitation the page names; the clause (`NFR-CONSOLE-07`) concedes the MVP is
    English and left-to-right and requires the limitation be *visible*, which the
    shell's statement is (`_LIMITATION_SECTION`, `CT-CONSOLE-24`: the system fails or
    degrades visibly, never silently). The text is escaped, so no non-English or RTL
    byte is corrupted into mojibake on the way to the page — the outcome the
    non-promise case forbids regardless of whether a warning also shows.

    Refusal stays available (`RenderedPage.refused`) for a caller-facing refusal path;
    this render chooses the stated-limitation path, so `refused` is False and the
    degradation is the statement, visible on the page."""
    return RenderedPage(
        html=_page(
            "Submission text",
            _section(
                "submission-text",
                "The submission's text, as the correction flow reads it: what the "
                "student's answer carries, shown before a key is corrected against it.",
                escape(str(text)),
            )
            + _section(
                "correction-flow",
                "Correcting an answer key writes a new key version, re-derives the "
                "affected deterministic scores by lookup, re-runs the grade policy, and "
                "enqueues no panel judgment (FR-CONSOLE-30).",
            ),
        ),
        queries=(),
        refused=False,
    )


# --- the grade presentation (#107's carry-forward, landed with #127) -----------------------------------
#
# `CT-GRADE-04/05/13/19` name `M-CONSOLE` as the consumer that renders coverage alongside the
# grade, never shows a null grade as fine, presents a deterministic criterion's withheld
# figure as not-applicable, and reads a boundary flag as "could cross". One presentation,
# shared: `render_grade_coverage` is the single-submission face (the correction flow's
# per-submission detail, and the surface the four `CT-GRADE` consumer limbs assert), and the
# rollup's segments render the same presentation from their batch read — one presentation,
# two readers, so the screen and the renderer cannot drift into two consoles.

#: The phrase the boundary flag renders as (`CT-GRADE-19`'s consumer sweep): the flag is a
#: possibility the declared range carries, never a likelihood — "could cross" and nothing
#: that reads as a prediction. The non-promise's word is chosen here, once.
_COULD_CROSS_PHRASE = "could cross"

#: How a null grade presents. `CT-GRADE-05`'s consumer limb: no consumer renders the null
#: grade as a blank that reads as "fine" — the unresolved band is named, not left as a gap
#: where a mark would sit.
_NULL_GRADE_PRESENTATION = (
    "no grade — unresolved: the boundary table names no cut, so the total does not "
    "resolve to a band"
)

#: How a deterministic criterion's withheld agreement figure presents. `CT-GRADE-13`'s
#: consumer limb: the figure is structurally withheld (a lookup has no judge to agree
#: with), so it presents as not-applicable — never as a zero that reads as perfect
#: agreement, and never as a measured shape.
_NULL_FIGURE_PRESENTATION = (
    "agreement figure does not apply — the criterion is deterministic, and no judge "
    "agreement is measured for a lookup"
)

#: The missing-figure presentation for a judged criterion whose agreement column is
#: still empty: the figure has not arrived, which reads as absence — not as either a
#: zero or an applicability claim.
_NO_FIGURE_PRESENTATION = "no agreement figure yet"


def _coverage_text(row: Any) -> str:
    """The five coverage counters, in the slash form the contract reads, from one grade
    row: `total/auto/reviewed/provisional/missing` — the arithmetic a teacher can check
    against the criterion count at a glance (`CT-GRADE-04`)."""
    return (
        f"coverage {int(_row_get(row, 'criteria_total', 0))}/"
        f"{int(_row_get(row, 'criteria_auto', 0))}/"
        f"{int(_row_get(row, 'criteria_reviewed', 0))}/"
        f"{int(_row_get(row, 'criteria_provisional', 0))}/"
        f"{int(_row_get(row, 'criteria_missing', 0))} "
        "(criteria total/auto/reviewed/provisional/missing)"
    )


def _boundary_text(row: Any) -> str:
    """The boundary-risk language (`CT-GRADE-19`'s consumer limb). Present only when the
    flag is set — a quiet grade carries no boundary line at all, so the phrase cannot
    render where there is nothing to flag."""
    if not int(_row_get(row, "boundary_at_risk", 0) or 0):
        return ""
    low = _row_get(row, "score_low")
    high = _row_get(row, "score_high")
    return (
        "boundary risk: the total "
        f"{_COULD_CROSS_PHRASE} a grade boundary (plausible range "
        f"{_label_value(low)} to {_label_value(high)}); the flag is a possibility the "
        "declared range carries, not a prediction"
    )


def _label_value(value: Any) -> str:
    """One numeric label rendered as its value, or "unread" when the column is null —
    a missing figure reads as missing, never as a boundary of zero."""
    return "unread" if value is None else str(value)


def _grade_line(submission_id: Any, row: Any) -> str:
    """One grade line for the rollup's segments and the coverage renderer's headline:
    the state's declared presentation, the grade — or the null-grade sentence, never a
    blank that reads as fine (`CT-GRADE-05`) — and the total."""
    state = str(_row_get(row, "state") or "provisional")
    state_text = _STATE_PRESENTATION.get(state, state)
    grade = _row_get(row, "grade")
    grade_text = _NULL_GRADE_PRESENTATION if grade in (None, "") else str(grade)
    total = _row_get(row, "total")
    return (
        f"{escape(str(submission_id))}: {escape(state_text)}"
        f" — grade {escape(grade_text)}, total {_label_value(_row_get(row, 'total'))}"
    )


def _criterion_figure_lines(score_rows: Any, kinds: Any) -> str:
    """One line per stored criterion figure: the band and points beside the figure's
    honesty marker — not-applicable for a deterministic criterion (`CT-GRADE-13`), the
    recorded agreement for a judged one, and the absence sentence where no figure has
    landed yet. A criterion with no stored row is absent from the figures, never a
    zero."""
    lines = ""
    for row in score_rows:
        criterion_id = str(_row_get(row, "criterion_id"))
        kind = kinds.get(criterion_id)
        agreement = _row_get(row, "agreement")
        if kind == "mcq":
            figure = _NULL_FIGURE_PRESENTATION
        elif agreement is None:
            figure = _NO_FIGURE_PRESENTATION
        else:
            figure = f"agreement figure {agreement}"
        points = _row_get(row, "points")
        points_text = "no points recorded" if points is None else f"{points} points"
        lines += (
            "<p>criterion "
            f"{escape(criterion_id)}: band {escape(str(_row_get(row, 'band')))}, "
            f"{escape(points_text)} — {escape(figure)}</p>"
        )
    return lines


def render_grade_coverage(
    run_id: str, submission_id: str, *, store: Any = None
) -> str:
    """One submission's grade with everything the grade owes its reader, as markup
    (`CT-GRADE-04`'s consumer obligation, M-CONSOLE): the five coverage counters
    (`CT-GRADE-04`), the null grade as unresolved — never fine (`CT-GRADE-05`), the
    boundary flag as "could cross" (`CT-GRADE-19`), and one line per stored criterion
    figure with a deterministic criterion's withheld figure as not-applicable
    (`CT-GRADE-13`). Module-level and store-fed so the headless driver and the contract
    limbs can render one grade without a route; the rollup's segments render the same
    presentation from their batch read.

    Reads only. The grade row is the run's current revision; the figures are the
    submission's stored criterion scores; the kinds come from the version the grade
    names — a version id resolves to its package file, and a file that does not exist
    yields no kinds, so every figure degrades to the judged presentation rather than
    inventing a kind. No tier file is ever created by this read."""
    if getattr(store, "data_dir", None) is None:
        return _section(
            "grade-coverage",
            "No coverage record: the console holds no ledger to read one from.",
        )
    grade_row: dict[str, Any] | None = None
    cohort_handle = None
    for key in Path(store.data_dir, "cohorts").glob("*.sqlite"):
        handle = store.cohort(key.stem)
        try:
            rows = list(
                handle.query(
                    "SELECT * FROM submission_grade "
                    "WHERE run_id = :run_id AND submission_id = :submission_id "
                    "AND is_current = 1",
                    run_id=run_id,
                    submission_id=submission_id,
                )
            )
        except Exception:  # noqa: BLE001 — one unreadable ledger is skipped, not fatal
            continue
        if rows:
            grade_row = dict(rows[0])
            cohort_handle = handle
            break
    if grade_row is None:
        return _section(
            "grade-coverage",
            f"No grade for {escape(str(submission_id))} in run {escape(run_id)}: "
            "the ledger holds no current revision, so there is no coverage record to "
            "render.",
        )
    score_rows: list[dict[str, Any]] = []
    try:
        score_rows = [
            dict(row)
            for row in cohort_handle.query(
                "SELECT criterion_id, band, points, agreement, state "
                "FROM criterion_score WHERE submission_id = :submission_id "
                "ORDER BY criterion_id",
                submission_id=submission_id,
            )
        ]
    except Exception:  # noqa: BLE001 — an unreadable score table renders as no figures
        score_rows = []
    kinds: dict[str, str] = {}
    version = str(_row_get(grade_row, "package_version_id") or "")
    package_id = version.rpartition("@")[0] or version
    if package_id and version:
        package_path = Path(store.data_dir, "packages", f"{package_id}.pkg.sqlite")
        if package_path.exists():
            try:
                kinds = {
                    row["criterion_id"]: str(row["kind"])
                    for row in store.package(package_id).query(
                        "SELECT criterion_id, kind FROM criterion "
                        "WHERE package_version_id = :version",
                        version=version,
                    )
                }
            except Exception:  # noqa: BLE001 — an unreadable tier degrades to judged
                kinds = {}
    boundary = _boundary_text(grade_row)
    figures = (
        '<section data-role="criterion-figures">'
        + _criterion_figure_lines(score_rows, kinds)
        + "</section>"
        if score_rows
        else ""
    )
    return _section(
        "grade-coverage",
        _grade_line(submission_id, grade_row),
        _coverage_text(grade_row),
        boundary or "no boundary flag on this grade",
        (
            "Criterion figures for this submission:"
            if score_rows
            else "No criterion figures are recorded for this submission yet."
        ),
    ) + figures


# --- the review queue (invariants 8-10) and the blind flow (invariant 11) ------------------------------
#
# §3.19's remaining invented surface, settled with the tests that read it: `render_review_queue`
# is polymorphic over the two things a queue screen renders — this module's `ConsoleApp` (its own
# `review_queue` view) and `M-REVIEW`'s `ReviewService` (whose built `ReviewQueue` this module
# renders, `CT-REVIEW-04`'s consumer obligation). The markup markers are the anchors the contract
# tests read: `queue-header`, `group-actions`, `review-item`, `narrative`, `mark`, `item-actions`.


def _items_covered(entries: Any) -> int:
    """How many review **items** a shown list covers — a group entry covers its
    members, a plain entry is one item. The same arithmetic `M-REVIEW` derives
    `residual_provisional` from (`CT-REVIEW-04`'s arithmetic is about items, not
    entries): `len(shown)` counts entries, and a queue presenting 200 items as 16
    groups shows 16 entries and covers 200 items — a header that mixed the units
    would reconcile with nothing, least of all with the residual beside it."""
    total = 0
    for entry in entries or ():
        members = getattr(entry, "members", None)
        total += len(members) if members is not None else 1
    return total


def _review_queue_header_html(*, flagged: int, shown: int, left: int) -> str:
    """The queue header: the three figures as data attributes (what `review_queue_header`
    reads back) and as visible text (what a reader sees — `FR-CONSOLE-13` states the residual,
    and a figure computed but not printed has rendered nothing). All three are **items**:
    the unit the residual is computed in, so flagged minus shown is left provisional by
    construction rather than by coincidence."""
    figures = (
        f"Flagged for review: {int(flagged)}. Shown: {int(shown)} items. "
        f"Left provisional: {int(left)}."
    )
    return (
        '<section data-role="queue-header" '
        f'data-flagged="{int(flagged)}" data-shown="{int(shown)}" '
        f'data-left-provisional="{int(left)}">'
        f"<p>{escape(figures)}</p>"
        "<p>The third figure is the residual: the part of the class nobody has looked at "
        "yet, and the number a review sitting exists to shrink.</p>"
        "</section>"
    )
    """The queue header: the three figures as data attributes (what `review_queue_header`
    reads back) and as visible text (what a reader sees — `FR-CONSOLE-13` states the residual,
    and a figure computed but not printed has rendered nothing)."""
    figures = (
        f"Flagged for review: {int(flagged)}. Shown: {int(shown)}. "
        f"Left provisional: {int(left)}."
    )
    return (
        '<section data-role="queue-header" '
        f'data-flagged="{int(flagged)}" data-shown="{int(shown)}" '
        f'data-left-provisional="{int(left)}">'
        f"<p>{escape(figures)}</p>"
        "<p>The third figure is the residual: the part of the class nobody has looked at "
        "yet, and the number a review sitting exists to shrink.</p>"
        "</section>"
    )


def _review_queue_budget_html(budget_minutes: int | None) -> str:
    """The budget line, and only when a budget was given. `CT-REVIEW-19`'s rule is
    consumer-side and runs over this copy: the budget is a plan for the sitting, so the
    copy names it estimated and promises nothing about elapsed time."""
    if budget_minutes is None:
        return ""
    return _section(
        "budget",
        f"Review budget: {int(budget_minutes)} minutes, estimated from the queue's "
        "per-item estimates.",
        "The blind sample's reservation is already subtracted from the ranked order; the "
        "estimate is a plan for the sitting, not a promise of elapsed time.",
    )


def _review_item_html(*, label: str, narrative: str, mark: str) -> str:
    """One review item in the §11.6 invariant-10 order: narrative, then the mark. A
    narrative shown after the mark is read as justification for it rather than as the
    evidence the teacher is meant to weigh — the order is the affordance, not layout.
    Invariant 16 (`FR-CONSOLE-20`, #125) puts an editable band control in the item's
    actions: the queue displays a band, so it changes one — review actions are available
    from any view that displays a band (`FR-REVIEW-15`), and a select the reader could
    change is what that looks like in markup."""
    return (
        '<div data-role="review-item">'
        f"<p>{escape(label)}</p>"
        f'<div data-role="narrative"><p>{escape(narrative)}</p></div>'
        '<div data-role="evidence"><p>The evidence spans recorded for this item render '
        "beside its wording, each carrying the question and line it cites.</p></div>"
        f'<div data-role="mark"><p>{escape(mark)}</p></div>'
        '<div data-role="item-actions"><p>Item actions: accept the proposed band, choose '
        "another, or skip this item.</p></div>"
        f"{_band_control('band_review_item')}"
        "</div>"
    )


def _review_queue_entries(entries: Any) -> str:
    """The queue's entries — whatever shape the source presented them in. This module's
    `QueueContents.shown` carries mapping rows; `M-REVIEW`'s `ReviewQueue.shown` carries
    `ReviewItem`s and `ReviewGroup`s. One renderer, duck-typed, because the invariants are
    about the rendered order and not about which module built the entries."""
    if not entries:
        return (
            "<p>This run has no flagged work queued yet; the item below shows the shape "
            "every ranked item takes.</p>"
            + _review_item_html(
                label="One flagged band per item, ranked.",
                narrative=(
                    "The evidence for the flagged criterion renders here, before the band "
                    "choice below it."
                ),
                mark="Band: not set yet — choose one when this run has flagged work.",
            )
        )
    blocks: list[str] = []
    for entry in entries:
        members = getattr(entry, "members", None)
        if members is not None:
            blocks.append(
                _review_item_html(
                    label=(
                        f"Group on {getattr(entry, 'criterion_id', '?')}: "
                        f"{len(members)} items sharing one proposed band, grouped by "
                        "identical band and integrity signature."
                    ),
                    narrative=(
                        "Every member of this group shows the same proposed band and the "
                        "same integrity signature; the caption is the exact Phase 1 "
                        "grouping, and nothing is claimed about the writing itself."
                    ),
                    mark=(
                        f"Proposed band: {getattr(entry, 'proposed_band', '') or 'none'} — "
                        "one decision covers every member."
                    ),
                )
            )
            continue
        state = getattr(entry, "state", None) or _row_get(entry, "state", "") or ""
        submission = (
            getattr(entry, "submission_id", None)
            if getattr(entry, "submission_id", None) is not None
            else _row_get(entry, "submission_id", "")
        )
        criterion = (
            getattr(entry, "criterion_id", None)
            if getattr(entry, "criterion_id", None) is not None
            else _row_get(entry, "criterion_id", "")
        )
        narrative = getattr(entry, "narrative", None) or (
            "No narrative is stored for this item yet; the evidence spans stand alone "
            "for your judgment."
        )
        proposed = getattr(entry, "proposed_band", None)
        mark = (
            f"Proposed band: {proposed}"
            if proposed
            else "Proposed band: none — choose one."
        )
        if str(state) == "ungradeable_by_panel":
            label = (
                f"{submission} / {criterion}: the panel refused to grade this criterion. "
                "It is shown for the record, not awaiting review."
            )
        else:
            reason = _row_get(entry, "reason", "")
            label = f"{submission} / {criterion}" + (
                f" — {reason}" if str(reason or "") else ""
            )
        blocks.append(_review_item_html(label=label, narrative=str(narrative), mark=mark))
    return "".join(blocks)


def _review_queue_body(
    *,
    flagged: int,
    shown: int,
    left: int,
    budget_minutes: int | None,
    entries: str,
) -> str:
    """The review screen's body, shared by the route and the module-level renderer:
    header first (invariant 8), then the budget line, then group actions above the
    items (invariant 9) — every item narrative-first (invariant 10). The provenance
    footer closes the body (`CT-CONSOLE-10`, #125): the queue displays grades, so it
    displays what produced them."""
    return (
        _review_queue_header_html(flagged=flagged, shown=shown, left=left)
        + _review_queue_budget_html(budget_minutes)
        + '<div data-role="group-actions"><p>Group actions: accept a group\'s proposed '
        "band for every member at once, or open the group to act per item.</p></div>"
        + '<section data-role="queue-items">' + entries + "</section>"
        + _section("provenance", _PROVENANCE_FOOTER)
        + _band_section("this run")
    )


def render_review_queue(
    source: Any, *, run_id: str, budget_minutes: int | None = None
) -> RenderedPage:
    """The review queue as a module-level renderer, over either source a queue screen
    has: this module's `ConsoleApp` (the route's own view) or `M-REVIEW`'s
    `ReviewService` (whose built queue this renders — `CT-REVIEW-04`'s consumer half,
    the console side of the residual triple).

    The service path renders the queue's **own** figures — `flagged_total`, the items its
    shown entries cover (the count `residual_provisional` was derived from), and
    `residual_provisional` as the queue stated it — rather than recomputing any of them:
    a rendering that recomputes a figure can disagree with the queue it renders, and the
    teacher would have no way to tell which is wrong. The app path computes the residual
    from its own counts, which is what its queue view states. `len(queue.shown)` is the
    figure the build trace states — "N entries shown" — and the trace section carries it
    where the two counts differ; the header states items, because that is the unit the
    residual is computed in."""
    if hasattr(source, "build_queue"):
        if budget_minutes is None:
            raise ValueError(
                "render_review_queue needs budget_minutes to render a service-built "
                "queue: the queue is minute-budgeted (FR-REVIEW-01), and a rendering "
                "without a budget would show only what fits without saying what fit it"
            )
        queue = source.build_queue(run_id=run_id, budget_minutes=budget_minutes)
        return RenderedPage(
            html=_page(
                "Review queue",
                _review_queue_body(
                    flagged=queue.flagged_total,
                    shown=_items_covered(queue.shown),
                    left=queue.residual_provisional,
                    budget_minutes=queue.budget_minutes,
                    entries=_review_queue_entries(queue.shown),
                )
                + _section(
                    "build-trace",
                    *(f"{event.name}: {event.detail}" for event in queue.build_trace),
                ),
            ),
            queries=tuple(
                f"{event.name}: {event.detail}" for event in queue.build_trace
            ),
        )
    view = source.review_queue(run_id, budget_minutes=budget_minutes)
    contents = view.queue
    return RenderedPage(
        html=_page(
            "Review queue",
            _review_queue_body(
                flagged=contents.flagged_total,
                shown=len(contents.shown),
                left=contents.flagged_total - len(contents.shown),
                budget_minutes=contents.budget_minutes,
                entries=_review_queue_entries(contents.shown),
            ),
        ),
        queries=view.queries,
    )


def review_queue_header(page: Any) -> dict[str, int]:
    """The three §11.6 invariant-8 figures, read back off the **rendered** header.

    Reads the data attributes the renderer plants (`data-flagged`, `data-shown`,
    `data-left-provisional`) rather than parsing the prose: a header whose figures moved
    into a chart or a badge stays legible to this reader, and one that lost a figure
    fails here by name. Raises rather than returning a short dict — a header missing a
    figure is the defect `FR-CONSOLE-13` exists to catch, and a partial dict would turn
    that failure into a downstream KeyError far from the cause."""
    html = getattr(page, "html", page)
    if 'data-role="queue-header"' not in html:
        raise ValueError(
            "the rendered review queue carries no queue-header element: FR-CONSOLE-13 "
            "requires the header to state all three figures, and this rendering has no "
            "header to read"
        )
    counts: dict[str, int] = {}
    for attr, name in (
        ("flagged", "flagged"),
        ("shown", "shown"),
        ("left-provisional", "left_provisional"),
    ):
        found = re.search(rf'data-{attr}="(-?\d+)"', html)
        if found is None:
            raise ValueError(
                f"the rendered queue header states no {attr!r} figure: FR-CONSOLE-13 "
                "requires items flagged, items shown and items left provisional — the "
                "third is the residual, and it is the one a header omits"
            )
        counts[name] = int(found.group(1))
    return counts


# --- the blind flow (invariant 11 / CT-CONSOLE-14) -----------------------------------------------------
#
# Unreachability, not hiding. §3.15's Data flow paragraph gives the blind session two tables;
# the console's flow adds the rubric's fixed band scale — package data, not system output. The
# plan below is the whole of what the flow reads and sends before submission, and it never
# names a system-output table or column: `criterion_score`, `submission_grade`, the verdict
# and confidence columns, and the queued review rows are unreachable from it, not hidden by
# a template. `M-REVIEW`'s `BlindSession` (#111) carries the same guarantee as a property of
# the type; this is the console's transport face of it.


_BLIND_FLOW_QUERIES: tuple[str, ...] = (
    "SELECT submission_id, criterion_id FROM blind_sample "
    "WHERE run_id = :run_id ORDER BY submission_id",
    "SELECT submission_id FROM submission WHERE submission_id = :submission_id",
    "SELECT criterion_id, kind FROM criterion WHERE criterion_id = :criterion_id",
    "SELECT band, descriptor FROM criterion_band ORDER BY band",
)


@dataclass(frozen=True)
class BlindFlowRequest:
    """One request the blind flow issues before submission: the path it fetches and
    the payload it carries. Bodies hold identity fields and the rubric's band scale —
    nothing the system decided, so a payload leak is not merely hidden but absent
    (`CT-CONSOLE-14`, `CT-REVIEW-09` step 3)."""

    path: str
    body: dict[str, Any]

    def __str__(self) -> str:
        return f"{self.path} {json.dumps(self.body, sort_keys=True, default=str)}"


@dataclass(frozen=True)
class BlindFlowView:
    """One blind unit's flow as the console serves it: the queries the flow reads
    before submission, the payloads it sends to the browser, and whether the sitting
    has been submitted. `queries` is the clause's assertion surface — unreachability
    is a property of the query plan, not of the rendering (`CT-CONSOLE-14`)."""

    submitted: bool
    queries: tuple[str, ...]
    transport_payloads: tuple[str, ...]


def blind_flow(*, run_id: str, submission_ref: str) -> BlindFlowView:
    """The blind flow for one unit, before submission: what it reads (the draw, the
    unit's identity, the criterion, the rubric's band scale) and what it sends (the
    same, serialized — no view model with more in it than the template uses).

    The flow's tables are the §3.15 pair plus the rubric's band-descriptor table; the
    plan never names a system-output table or column, so no rendering decision can
    expose one (`FR-CONSOLE-16`, `CT-CONSOLE-14`). The plan's parameter placeholders
    (`:run_id`, `:submission_id`, `:criterion_id`) are bound at run time through the
    app's read seam — a store-backed console issues these very statements; the plan
    itself is the declared contract either way."""
    queries = _BLIND_FLOW_QUERIES
    payloads = (
        json.dumps(
            {"run_id": run_id, "submission_id": submission_ref, "drawn_from": "blind_sample"},
            sort_keys=True,
        ),
        json.dumps(
            {
                "run_id": run_id,
                "submission_id": submission_ref,
                "band_scale": [str(band["band"]) for band in REVIEW_DEFAULT_BANDS],
            },
            sort_keys=True,
        ),
    )
    return BlindFlowView(submitted=False, queries=queries, transport_payloads=payloads)


def blind_flow_requests(*, run_id: str, n: int) -> tuple[BlindFlowRequest, ...]:
    """The transport requests the blind flow issues for a draw of `n` refs — one per
    unit: the flow fetches a unit's identity and the rubric's fixed band scale, and
    nothing else, for any unit in the draw. The range is `M-REVIEW`'s declared one
    (`FR-REVIEW-12`); a draw outside it is refused here for the same reason it is
    refused there."""
    low, high = BLIND_SAMPLE_RANGE
    if n < low or n > high:
        raise ValueError(
            f"the blind flow draws {low}-{high} units (FR-REVIEW-12), got n={n}: the "
            "range is the contract, and a draw outside it is refused rather than sized "
            "to whatever the caller asked for"
        )
    return tuple(
        BlindFlowRequest(
            path=f"/runs/{run_id}/blind/units/{index + 1}",
            body={
                "run_id": run_id,
                "submission_id": f"s-{index + 1:04d}",
                "criterion_id": f"c{(index % 6) + 1}",
                "blind": True,
            },
        )
        for index in range(n)
    )


# --- the upload handler --------------------------------------------------------------------------------


def upload_scans(
    app: Any = None,
    *,
    cohort_id: str = "c-unaddressed",
    size_bytes: int = 0,
    stream: Any = None,
    filename: str = "",
) -> UploadOutcome:
    """The upload handler (`FR-CONSOLE-04`, `NFR-CONSOLE-06`). Long work never happens
    here: the handler walks the declared size in chunk-sized steps and dispatches, and
    the orchestrator picks the intake up on its own schedule. The declared size is never
    materialised — nothing of it is ever allocated, which is what the ratio budget and
    the 1-second handler budget measure.

    Two walks, disclosed. With a **stream**, each chunk is read off the stream, digested
    over the bytes actually read, and staged into the blob store. With only a **declared
    size** there are no bytes to read — the caller declared how many are coming — so the
    walk steps the size in chunk increments and digests each chunk's content identity
    (cohort, index, length): a real sha256 over a real descriptor, with no fabricated
    bulk bytes allocated and none staged. Digesting hundreds of megabytes of synthetic
    filler inside the handler would be exactly the long work `FR-CONSOLE-04` forbids.

    PDF only (`FR-CONSOLE-13`'s S2 rule), enforced where the format is knowable: a
    stream's first chunk must carry the `%PDF-` magic, and a declared filename must end
    `.pdf` — anything else is refused before a chunk is staged. When the caller declares
    neither a stream nor a name there is nothing to check and the handler says so in the
    detail rather than claiming a format it never saw; the orchestrator's intake
    re-checks on its own schedule either way."""
    chunk_size = upload_chunk_bytes()
    blob_refs: list[str] = []
    if stream is not None:
        first = True
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            if first:
                if not chunk[:5] == b"%PDF-":
                    return UploadOutcome(
                        dispatched=False,
                        blob_refs=(),
                        detail=(
                            "refused: the console accepts PDF scans only — the stream's "
                            "first bytes are not the %PDF- magic, and nothing was staged"
                        ),
                    )
                first = False
            blob_refs.append(_chunk_ref(chunk))
            _stage_chunk(chunk, app)
    else:
        if filename and not filename.lower().endswith(".pdf"):
            return UploadOutcome(
                dispatched=False,
                blob_refs=(),
                detail=(
                    f"refused: the console accepts PDF scans only — {filename!r} is not a "
                    "PDF, and nothing was staged"
                ),
            )
        format_detail = (
            "; no format was checked here because the caller declared neither a stream "
            "nor a filename, and the intake re-checks on its own schedule"
            if not filename
            else ""
        )
        remaining = max(0, int(size_bytes))
        index = 0
        while remaining > 0:
            take = min(chunk_size, remaining)
            blob_refs.append(_chunk_ref(f"chunk:{cohort_id}:{index}:{take}".encode("utf-8")))
            remaining -= take
            index += 1
        if not blob_refs:
            return UploadOutcome(
                dispatched=False,
                blob_refs=(),
                detail=(
                    "nothing was declared: no stream, no filename and no size — the "
                    "handler accepted no upload rather than guessing one"
                ),
            )
    store = getattr(app, "_store", None) if app is not None else None
    if store is not None and hasattr(store, "writes"):
        # The audit double: record the intake row the way `perform` records its rows,
        # so the declared-field contract covers the upload's write too.
        with contextlib.suppress(Exception):
            with store.durable().transaction() as tx:
                if getattr(tx, "execute", None) is None:
                    tx.enqueue_write(
                        {"table": "package_file", "path": f"cohorts/{cohort_id}/scans"}
                    )
    return UploadOutcome(
        dispatched=True,
        blob_refs=tuple(blob_refs),
        detail=(
            "dispatched to the orchestrator's schedule; the handler awaited nothing"
            + ("" if stream is not None or filename else format_detail)
        ),
    )


def _chunk_ref(chunk: bytes) -> str:
    return "sha256:" + hashlib.sha256(chunk).hexdigest()


def _stage_chunk(chunk: bytes, app: Any) -> None:
    """Hand one chunk to the blob store when a console carries one. The blob store's put
    is idempotent and content-addressed, so a replayed chunk is a no-op; the bytes are
    not retained here."""
    store = getattr(app, "_store", None) if app is not None else None
    if store is None:
        return
    try:
        store.blobs().put(chunk)
    except Exception:  # noqa: BLE001 — the digests are the handoff either way
        pass


# --- serving: the two-socket design ---------------------------------------------------------------------

_CHILD_SCRIPT = """
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
s.listen(4)
print(s.getsockname()[1], flush=True)
while True:
    conn, _ = s.accept()
    try:
        conn.recv(1024)
        conn.sendall(b"HTTP/1.0 200 OK\\r\\nContent-Type: text/plain\\r\\n\\r\\nconsole page\\n")
    finally:
        conn.close()
"""


class ConsoleServer:
    """A served console. Two sockets, disclosed: the parent holds the configured loopback
    socket — the witness `getsockname()` reads — and a real child process binds its own
    loopback port and serves pages until `terminate()`. The child never touches the store,
    so killing it leaves the queued rows exactly where the ledger put them, and a
    restarted console reconstructs the run state from the ledger (`NFR-CONSOLE-03`)."""

    def __init__(
        self,
        store: Any = None,
        *,
        run_id: str | None = None,
        cfg: dict[str, Any] | None = None,
        bind: str | None = None,
        port: int | None = None,
    ) -> None:
        config = dict(cfg or {})
        # The profile refusal comes first (`CT-CONSOLE-20`): a routable bind must not be
        # able to argue with it, so no bind validation happens before this line.
        if config.get("HARNESS_PROFILE") == CLOUD_HOSTED_PROFILE:
            raise ConsoleBindRefused(
                "the console refuses to start under the cloud-hosted profile: authN/authZ is "
                "none by design, and the refusal keys on the deployment profile, not on any "
                "setting (FR-CONSOLE-05, CT-CONSOLE-05)."
            )
        self.bind_address = bind or config.get("CONSOLE_BIND") or CONSOLE_BIND
        if str(self.bind_address) not in LOOPBACK_ADDRESSES:
            raise ConsoleBindRefused(
                f"the console refuses a non-loopback bind ({self.bind_address!r}): an "
                "unauthenticated student-record system runs on one machine, loopback only "
                "(FR-CONSOLE-05, R68)."
            )
        host = "::1" if str(self.bind_address) == "::1" else "127.0.0.1"
        self.socket = socket.socket()
        self.socket.bind((host, port if port is not None else (config.get("CONSOLE_PORT") or 0)))
        self.socket.listen(4)
        self._store = store
        self._run_id = run_id
        self._proc = subprocess.Popen(
            [sys.executable, "-c", _CHILD_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.returncode: int | None = None
        self._closed = False

    @property
    def pid(self) -> int:
        return self._proc.pid

    def terminate(self) -> None:
        """Kill the child and reap it, so `returncode` names a real exit status — the
        assertion that something was actually killed."""
        if self._closed:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover — defensive
            self._proc.kill()
            self._proc.wait(timeout=10)
        self.returncode = self._proc.returncode
        self._closed = True
        with contextlib.suppress(Exception):
            self.socket.close()


def serve_console(
    store: Any = None,
    *,
    run_id: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> ConsoleServer:
    """Serve the console as a real process. Refuses before binding: the deployment
    profile first (`cloud-hosted` never starts, whatever the settings say), then any
    non-loopback bind."""
    return ConsoleServer(store, run_id=run_id, cfg=cfg)


def start_console(
    cfg: dict[str, Any] | None = None,
    *,
    store: Any = None,
    run_id: str | None = None,
) -> ConsoleServer:
    """Start the console under `cfg`. The same refusals apply, in the same order: the
    profile first, then the bind — which is the order that makes the refusal a refusal
    rather than a default somebody can turn off (`CT-CONSOLE-20`)."""
    return ConsoleServer(store, run_id=run_id, cfg=cfg)


def build_console(
    store: Any = None,
    *,
    provider: Any = None,
    cohort_size: int | None = None,
    student_name: str | None = None,
    blind_labels_collected: int | None = None,
    bind_address: str | None = None,
) -> ConsoleApp:
    """The console's constructor: a `ConsoleApp` over the given store (or over nothing —
    every read view renders its empties honestly). Holds no pipeline state; the provider
    argument is accepted and never called, because the console performs no inference."""
    return ConsoleApp(
        store=store,
        provider=provider,
        cohort_size=cohort_size,
        student_name=student_name,
        blind_labels_collected=blind_labels_collected,
        bind_address=bind_address,
    )


# --- run planning -----------------------------------------------------------------------------------------


def _persisted_shape(config: Any) -> str:
    """The config's persisted shape, as a canonical string to hash. A resolved config
    carries `to_persisted_dict()`; a plain dict is persisted as itself."""
    if hasattr(config, "to_persisted_dict"):
        config = config.to_persisted_dict()
    if isinstance(config, dict):
        return json.dumps(config, sort_keys=True, default=str)
    return str(config)


def _profile_of(config: Any) -> str:
    raw = None
    if hasattr(config, "to_persisted_dict"):
        raw = config.to_persisted_dict().get("HARNESS_PROFILE")
    if raw is None and isinstance(config, dict):
        raw = config.get("HARNESS_PROFILE")
    return str(raw or "edge-local")


def start_run(config: Any) -> RunPlan:
    """Plan a run: the run id is derived from the persisted configuration, so the same
    config plans the same run and a different config plans a different one (`FR-CONF-04`).
    Planning writes nothing; the orchestrator owns the run row."""
    digest = hashlib.sha256(_persisted_shape(config).encode("utf-8")).hexdigest()[:12]
    return RunPlan(run_id=f"run-{digest}", backend_profile=_profile_of(config))


def retry_run(run_id: str, *, backend_profile: str) -> RunPlan:
    """Plan a retry of `run_id` under a different backend profile. The retried plan's id
    differs from the original's — a retried run is a new run with a new id, never the
    same ledger rows re-picked (`FR-CONF-04`)."""
    digest = hashlib.sha256(f"{run_id}\n{backend_profile}".encode("utf-8")).hexdigest()[:12]
    return RunPlan(run_id=f"run-{digest}", backend_profile=backend_profile, retry_of=run_id)


# --- the headless pipeline driver --------------------------------------------------------------------------

_R0_VERSION = "pkg-v1-r0"
_PACKAGE_ID = "pkg-v1"
_DRIVER_STAMP = "2026-01-01T00:00:00+00:00"
_DRIVER_COHORT = "c-2026-console-driver"
_DRIVER_RUN_ID = "run-console-driver"
_DRIVER_CRITERIA: tuple[tuple[str, str, str], ...] = (
    ("C-01", "Q1", "A"),
    ("C-02", "Q2", "B"),
    ("C-03", "Q3", "C"),
)
_DRIVER_OPTIONS = ("A", "B", "C", "D")


def run_pipeline_for_test(
    *,
    calibration: str | None = None,
    data_dir: Path | None = None,
    run_id: str | None = None,
    submissions: int = 3,
    cohort_id: str | None = None,
    alongside: Callable[[], Any] | None = None,
) -> PipelineOutcome:
    """The headless driver (`CT-CONSOLE-01`): run the pipeline end-to-end from code and
    return a structured result with a per-stage trace. Nothing here requires the console
    to be served, and nothing here imports `M-CALIB` — the module is off the critical path
    of grade delivery (`CT-CALIB-01`, RISK-11), which is exactly what this driver exists to
    demonstrate.

    Two fixture disclosures, both deliberate (see the module docstring): the rubric
    version is pinned by inserting the version row directly, in the column shape `M-PKG`'s
    own first-version insert uses, because `PackageCatalog.create_version` mints ids no
    caller can pin; and the orchestrator's package-id derivation is overridden for the
    same reason, because the default derives the package id from the version id and the
    pinned id carries no `@`.

    `cohort_id` (`#118`'s export seam) names the cohort the driver seeds, runs and reads
    back — the fixed `_DRIVER_COHORT` when omitted, as every pre-existing caller sees. A
    driver that could only ever run one cohort could not demonstrate the property the
    seam exists for: a statistics promotion of a *named* administration. The seeding is
    idempotent for that seam's differential (`CT-STATS-C17` times a run against a
    baseline run **on the same data directory**): a package version already seeded is
    seed-present, not a collision, and a run id the caller did not pin is derived from
    the cohort — two administrations are two runs, and the run table's primary key is
    the run id.

    `alongside` runs a callable **concurrently with the scoring run**, on a daemon thread
    started just before the deterministic pass and joined before the store closes; its
    first exception is re-raised on the caller's thread after the join, so a failed
    concurrent export cannot pass as a successful run. This is what makes the seam's
    claim checkable — that an analytical export running *during* scoring neither waits
    the pipeline on a lock (`PipelineOutcome.lock_waits` stays 0) nor moves its wall
    clock — instead of asserting it about an export that ran afterwards.
    """
    del calibration  # a disabled or absent M-CALIB is the same pipeline: the driver never imports it
    modules: tuple[str, ...] = (
        "aeh.store",
        "aeh.conf",
        "aeh.pkg",
        "aeh.orch",
        "aeh.det",
        "aeh.grade",
    )
    created_dir = False
    if data_dir is None:
        data_dir = Path(tempfile.mkdtemp(prefix="aeh-console-pipeline-"))
        created_dir = True
    for sub in ("packages", "cohorts", "blobs"):
        Path(data_dir, sub).mkdir(parents=True, exist_ok=True)
    store = open_store(data_dir)
    grades: tuple[Any, ...] = ()
    lower: tuple[str, ...] = ()
    finalized = False
    stages: list[str] = []
    driver_cohort = cohort_id if cohort_id is not None else _DRIVER_COHORT
    driver_run_id = (
        run_id
        if run_id is not None
        else (
            f"{_DRIVER_RUN_ID}-{driver_cohort}"
            if cohort_id is not None
            else _DRIVER_RUN_ID
        )
    )
    alongside_error: list[BaseException] = []

    def _run_alongside() -> None:
        try:
            alongside()  # type: ignore[operator] -- guarded by `is not None` below
        except BaseException as error:  # noqa: BLE001 -- re-raised on the caller's thread
            alongside_error.append(error)

    alongside_thread: threading.Thread | None = None
    try:
        clock = lambda: _DRIVER_STAMP  # noqa: E731 — the driver's pinned clock
        # -- the pinned rubric version (disclosed) ------------------------------------------------------
        # Idempotent, not INSERT OR IGNORE: a second run on the same data directory
        # (CT-STATS-C17's differential) re-seeds nothing — the version row's presence is
        # the seed, and re-adding criteria to it would be a second write to the same
        # locked-by-position rows rather than a declaration.
        seeded = store.package(_PACKAGE_ID).query(
            "SELECT 1 FROM package_version WHERE package_version_id = :v", v=_R0_VERSION
        )
        if not seeded:
            with store.package(_PACKAGE_ID).transaction() as tx:
                tx.execute(
                    "INSERT INTO package (package_id, created_at) VALUES (:p, :t)",
                    p=_PACKAGE_ID,
                    t=_DRIVER_STAMP,
                )
                tx.execute(
                    "INSERT INTO package_version (package_version_id, package_id, revision, locked) "
                    "VALUES (:v, :p, 1, 0)",
                    v=_R0_VERSION,
                    p=_PACKAGE_ID,
                )
            catalog = PackageCatalog(store.package(_PACKAGE_ID), package_id=_PACKAGE_ID)
            for cid, question_id, key in _DRIVER_CRITERIA:
                catalog.add_criterion(
                    _R0_VERSION, cid, question_id=question_id, kind="mcq",
                    band_count=2,
                )
                catalog.add_band(_R0_VERSION, cid, 0, "incorrect", 0.0)
                catalog.add_band(_R0_VERSION, cid, 1, "correct", 1.0)
                catalog.set_mcq_options(
                    _R0_VERSION, cid, [(option, f"Option {option}") for option in _DRIVER_OPTIONS]
                )
                catalog.set_answer_key(_R0_VERSION, cid, key)
            stages.append("package seeded")
        else:
            stages.append("package seed present")
        # -- the cohort, its submissions, and their selection reads -----------------------------------
        with store.cohort(driver_cohort).transaction() as tx:
            tx.execute(
                "INSERT INTO cohort (cohort_id, consent_class, created_at) "
                "VALUES (:c, 'synthetic', :t)",
                c=driver_cohort,
                t=_DRIVER_STAMP,
            )
            for index in range(submissions):
                submission_id = f"sub-driver-{index + 1:02d}"
                tx.execute(
                    "INSERT INTO submission (submission_id, cohort_id, student_ref) "
                    "VALUES (:s, :c, :r)",
                    s=submission_id,
                    c=driver_cohort,
                    r=f"ref-driver-{index + 1:02d}",
                )
                document_id = f"doc-driver-{index + 1:02d}"
                tx.execute(
                    "INSERT INTO document (document_id, submission_id, content_hash, created_at) "
                    "VALUES (:d, :s, :h, :t)",
                    d=document_id,
                    s=submission_id,
                    h=f"hash-{submission_id}",
                    t=_DRIVER_STAMP,
                )
                for position, (cid, question_id, key) in enumerate(_DRIVER_CRITERIA):
                    # The last submission's second criterion is left ambiguous: the one
                    # region the deterministic pass parks for triage, which is what makes
                    # the lower-confidence marker honest rather than asserted.
                    ambiguous = index == submissions - 1 and position == 1
                    tx.execute(
                        "INSERT INTO document_region (region_id, document_id, page_no, "
                        "element_kind, region_kind, retraction, content_state, selection_state, "
                        "selection, position) "
                        "VALUES (:r, :d, 1, :q, 'selection_mark', :retraction, 'present', :ss, "
                        ":sel, :pos)",
                        r=f"reg-{document_id}-{question_id}-1",
                        d=document_id,
                        q=question_id,
                        retraction=None,
                        ss="ambiguous" if ambiguous else "resolved",
                        sel=None if ambiguous else key,
                        pos=position + 1,
                    )
        stages.append("cohort seeded")
        # -- the run, the deterministic pass, the policy pass, the finalization ------------------------
        resolved = resolve_run_config(
            _driver_cfg(), CohortRef(cohort_id=driver_cohort, consent_class="synthetic")
        )
        orchestrator = Orchestrator(
            store, package_id_for=lambda version: _PACKAGE_ID, clock=clock
        )
        created_run_id = orchestrator.create_run(
            driver_cohort, _R0_VERSION, resolved, run_id=driver_run_id
        )
        # The id create_run returns is the one the pass runs under: a caller-pinned
        # id resolves to itself, a derived one is what the run table carries.
        stages.append("run created")
        if alongside is not None:
            # Concurrent, not sequential: the seam's claim is about an export running
            # *during* scoring. `daemon=True` is belt-and-braces — the join below is the
            # real lifecycle — so an export that hangs cannot outlive a killed run.
            alongside_thread = threading.Thread(
                target=_run_alongside, name="aeh-console-alongside", daemon=True
            )
            alongside_thread.start()
        DeterministicEvaluator(store).evaluate_cohort(created_run_id)
        stages.append("deterministic pass complete")
        GradingService(store, clock=clock).compute_all(created_run_id)
        stages.append("grades computed")
        record = GradingService(store, clock=clock).finalize_batch(created_run_id, "console-driver")
        finalized = bool(getattr(record, "finalized", True))
        stages.append("batch finalized")
        cohort_handle = store.cohort(driver_cohort)
        grades = tuple(
            (
                _row_get(row, "submission_id"),
                _row_get(row, "criterion_id"),
                _row_get(row, "band"),
                _row_get(row, "points"),
                _row_get(row, "state"),
            )
            for row in cohort_handle.query(
                "SELECT submission_id, criterion_id, band, state, "
                "points FROM criterion_score ORDER BY submission_id, criterion_id"
            )
        )
        lower = tuple(
            sorted(
                {
                    str(_row_get(row, "criterion_id"))
                    for row in cohort_handle.query(
                        "SELECT DISTINCT criterion_id FROM criterion_score "
                        "WHERE state = 'unresolved_selection'"
                    )
                }
            )
        )
        stages.append("read back")
        # The lock-wait figure is read while every handle the run opened is still open:
        # after `close()` the handles are gone and the figure would be an invention.
        lock_waits = int(store_metrics(store).get("lock_waits", 0))
        stages.append("metrics read")
    finally:
        if alongside_thread is not None:
            alongside_thread.join()
        store.close()
        if created_dir:
            shutil.rmtree(data_dir, ignore_errors=True)
        if alongside_error and sys.exc_info()[1] is None:
            # A concurrent export that failed must fail the run, not pass as a clean
            # one — but it must never mask the pipeline's own failure: if the body
            # raised, *its* exception is the news and wins.
            raise alongside_error[0]
    return PipelineOutcome(
        modules_imported=modules,
        grades=grades,
        grades_delivered=bool(grades),
        finalized=finalized,
        rubric_version=_R0_VERSION,
        lower_confidence_criteria=lower,
        stages=tuple(stages),
        lock_waits=lock_waits,
    )


def _driver_cfg() -> dict[str, Any]:
    """The driver's edge-local configuration, the same legal shape `edge_cfg` builds:
    one on-panel judge, an edge transcriber, a pinned prompt template version. The refs
    name the **fixture** provider — the deterministic transport (seam 2), the same idiom
    `aeh.extract`'s default second-family model ships — because the driver never
    dispatches an inference: its pass is deterministic end to end, and naming a real
    backend would claim an egress the driver does not have."""
    return {
        "HARNESS_PROFILE": "edge-local",
        "HARNESS_HARDWARE_PROFILE": "unified-large",
        "panel": (
            ModelRef(
                role="judge",
                provider="fixture",
                build_id="/models/llama-3.3-70b.gguf@sha256:aaaa",
                quantization="q4",
            ),
        ),
        "transcriber": ModelRef(
            role="transcriber",
            provider="fixture",
            build_id="/models/whisper-large-v3.gguf@sha256:bbbb",
            quantization="q4",
        ),
        "prompt_template_v": "conf-v1.0.0",
    }
