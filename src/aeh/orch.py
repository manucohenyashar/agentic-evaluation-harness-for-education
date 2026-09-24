"""`M-ORCH` — the Run Orchestrator & Work Ledger (design §3.7).

The ledger is the system's only source of truth about what has run, what is running and
what is left, which is what makes the console stateless and resume bookkeeping-free. This
first slice (issue #57) is the ledger's foundation:

- **`WorkUnit`** — the unit type itself (design v1.5 note: this story owns the type, not
  just the ledger rows). Its field list is fixed by the design note and is deliberate;
  see the class docstring for why `student_name` is on it.
- **`compute_work_id`** — `FR-ORCH-01`'s content address. Changing any of the nine inputs
  that can affect the answer produces a different unit, so a stale result is structurally
  unreusable rather than manually cleaned up (R14, NFR-EXTRACT-02/03).
- **Enumeration** — `create_run` / `enumerate_units`: base units per the §3.7 data flow,
  inserted idempotently, so enumerating twice produces byte-identical `work_id` sets
  (NFR-ORCH-05) and re-running a completed run is a no-op (FR-ORCH-03).
- **`resume()`** — takes no arguments (`FR-ORCH-02`: an argument is a place for an
  operator to be wrong under time pressure), skips every `done` unit, and is safe to
  invoke when nothing is wrong.

**This slice (#58) adds the lease** (`FR-ORCH-04`): `lease(worker_id, stage, n)` claims
pending units exclusively with an owner and an expiry, `heartbeat(work_id)` extends a live
lease, `sweep_expired_leases()` returns abandoned leases to `pending` — and the failure
taxonomy (`FR-ORCH-18`): `complete(work_id, result)` marks a unit `done` and `fail(work_id,
error)` requeues a unit until `ORCH_MAX_ATTEMPTS`, then quarantines it with its last error
retained while the run continues ("fail the unit, never the run"). Expiry is derived from
`M-STORE`'s monotonic lease counter (`LeaseClock`, `FR-STORE-11`/`CT-STORE-14`) — never
from the wall clock, so a clock moved backwards across a restart still reads an expired
lease as expired. The wall-clock timestamp beside the ticks is for the operator reading
the row; the sweeper's comparison is the counter's alone.

**This slice (#59) adds the two-sweep execution plan** (`FR-ORCH-05/06/07/08/22`):
Sweep 1 (extraction) is enumerated over **admitted** submissions only —
`SWEEP1_ADMITTED_INGEST_STATUSES` is the admission rule — and dispatched in topological
order over the criterion dependency graph; Sweep 2 (scoring) for a criterion does not
begin until every extraction unit it depends on is `done`, and is then ordered judge →
question → criterion → parallel over submissions on every backend profile (`FR-ORCH-07`'s
fixed key — no dependency ordering in Sweep 2, per the design's technical note). A
`deterministic` criterion generates exactly one `stage='deterministic'` unit with a null
`judge_id` and no extraction and no scoring unit (`FR-ORCH-08`).

**This slice (#60) adds the escalation machinery** (`FR-ORCH-09/10/11/13/14/26`):
`enqueue_escalation(tx, criterion_score_key, judges)` — the design's `CT-ORCH-08`
form, the caller's transaction first — widens a pair's panel one judge to three,
never to two; an even plan raises `EvenEscalationPlanError` (`FR-ORCH-10`), and the
widened units carry `origin='escalation'` in the transaction the caller commits with
the verdict that triggered them (`FR-ORCH-09`). The **random arm** samples judged
pairs at `ORCH_RANDOM_ARM_RATE` during enumeration (`origin='random_arm'`,
independent of confidence, never suppressed by the budget or a breaker —
`CT-ORCH-15`); the seeded draw is `random_arm_selection`. The **criterion breaker**
(`FR-ORCH-13`) latches when a criterion escalates for more than half of the first
`ORCH_CRITERION_BREAKER_MIN_N` submissions processed — escalation halts for that
criterion, the remainder single-judge provisional. The **run-wide budget**
(`FR-ORCH-14`) rations dispatch: `enqueue_escalation` writes the plan the verdict
needs (the atomicity clause leaves it no choice), and the claim pass admits pending
escalation units through `admit_escalations` only while the observed rate is at or
under `ORCH_ESCALATION_BUDGET` — above it the remainder stays pending, marked
provisional in expected-value order, until growth returns headroom. Scrutiny is
never silently reduced. Every decision is pure policy (`escalation_plan`,
`validate_escalation_plan`, `admit_escalations`, `criterion_breaker_tripped`,
`random_arm_selection`) — evaluable with no model call (`NFR-ORCH-04`).

**This slice (#61) adds the control-row run lifecycle** (`FR-ORCH-15/16/17/25`,
`CT-ORCH-12/13`): `start(run_id)` flips `pending → running` and obtains + displays the
run's estimated cost from the injected provider seam **before** any dispatch;
`pause(run_id, cause=...)` records the request as a `run_control` row and applies it
through the control-read pass — immediately on a `running` run, queued on a `pending`
one (request ≠ effect: the effect lands at the next `start`), so a pause written while
the orchestrator was down is honoured at the next read rather than lost. The four
`CT-ORCH-12` pause conditions all land in the same place: `ProviderUnavailableError`
(`FR-ORCH-16`) and `BuildChangedError` (`FR-ORCH-17`) via `cause=`, the operator's own
request via `cause=None`, and the cost ceiling sensed in the claim pass itself — the
frozen ceiling (`FR-CONF-07`) is checked against the provider seam's **measured**
per-unit figures (`FR-PROV-12/04`, never an estimated optimism), spend accrues in the
claim transaction, a dispatch that would land **above** the ceiling is refused and the
run pauses naming its spend and remaining unit count. `resume(run_id)` is the
`paused → running` edge and re-binds to nothing: lifecycle writes touch status columns
only, so the frozen backend is the resumed backend by construction — there is no
substitution code path (`FR-ORCH-16`). The ledger is preserved across every pause: a
pause is a stop and a reason, never a purge.

**This slice (#62) adds the dispatch loop and the `ProgressReport`**
(`FR-ORCH-12/19/21/23/24`): `progress(run_id)` is the dispatch loop's beat — with a
transport injected it completes the extraction walk through the seam, completes the
deterministic walk directly (deterministic evaluation makes no model call), and claims ONE
score batch no larger than the pass's effective concurrency, running its model calls
concurrently against the injected transport seam (`Orchestrator(store, transport=...)`,
`call(request) -> Completion` or a raise of the real taxonomy error) — the seam receives
the **assembled** closed request (`FR-ORCH-20`: what is dispatched is "exactly one
submission per scoring or extraction request", so the dispatch assembles the stage's
shipped schema — `ScoringRequest` via `M-JUDGE`'s `ScoringWorker.assemble`, the
`ExtractionRequest` via `M-EXTRACT`'s `assemble_request` — and sends that, never the
ledger row); without a transport the call is the
report-only surface the console polls, which reads the ledger and dispatches nothing.
On `edge-local` the claim walk is **residency-batched**: one judge model stays resident
until the ledger holds none of its work, each model change is a recorded swap (count and
measured duration, `FR-ORCH-19`), and every handout batch is single-model. The
concurrency governor starts at the run's frozen ceiling, divides on rate-limit/OOM
signals and clamps further while M-STORE signals write backpressure — a signal to reduce
dispatch, never a fault (`CT-STORE-06`). The report counts by
`(stage, criterion, judge)` and totals done/in-flight/pending/quarantined — **no
per-student figure exists on the type** (`FR-ORCH-23`/`R63`) — with the completion
predicate read off the ledger (`FR-ORCH-12`: nothing pending and no in-flight scoring
judgment that could spawn an escalation) and the estimate adjusted by the observed
escalation rate (`estimated_completion_seconds`, `FR-ORCH-24`).

**The four seams** (CLAUDE.md): the orchestrator runs end-to-end from code and returns a
structured result with per-gate detail (`EnumerationReport`, `EscalationReport`,
`ProgressReport` — the `IngestReport.gates` precedent); its one external dependency to
transport — the model call — is injected (`transport=`), so a dispatch runs with no
network and the store arrives by injection the same way; every budget, threshold, rate
and window constant is env-gated and read at call time; and every report carries
stage-level detail rather than a bare status.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass, field, fields as dataclass_fields
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping, NamedTuple, Protocol, Sequence

from aeh.prov import (
    BuildChangedError,
    Completion,
    ProviderUnavailableError,
    RateLimitedError,
)
from aeh.store import (
    TIER_MIGRATIONS,
    LeaseClock,
    Migration,
    Statement,
    Tier,
    lease_clock,
    store_metrics,
)

# The admission filter (`FR-ORCH-22`) reads `submission.ingest_status` — a column the
# ingest migration adds. M-ORCH depends on M-INGEST ("submission readiness", design §3.7's
# dependency table); importing the owning module here is that dependency made literal, so
# a ledger opened after `import aeh.orch` alone still holds the column the filter selects.
# Migrations apply in version order regardless of registration order (`store`'s apply loop).
import aeh.ingest  # noqa: F401 — the admission read's schema dependency

#: The canonical JSON separators used for every config string the ledger stores. Chosen
#: once, here, so two code paths cannot serialize the same panel differently and silently
#: fork the work-ID space (`panel_config` is a hash input).
_JSON_SEPARATORS = (",", ":")

#: The extraction build this orchestrator enumerates for (`FR-ORCH-01`'s
#: `extractor_version` input). `M-EXTRACT` does not exist yet (#68) — when it lands it
#: owns this value and its release cadence; until then it is a module constant so the
#: ninth hash input is a real, stable string rather than a placeholder that changes.
EXTRACTOR_VERSION = "extract/1"

#: The work-unit stages (HLD §9.6's `work_unit.stage` comment). `deterministic` carries a
#: null judge: MCQ items are in the ledger so a run stays resumable and idempotent, but no
#: judge runs. `synth_l1`/`synth_l2` units are enumerated by `M-SYNTH` later, not here.
STAGE_EXTRACT = "extract"
STAGE_SCORE = "score"
STAGE_DETERMINISTIC = "deterministic"

#: The complete `ingest_status` admission rule for Sweep 1 (`FR-ORCH-22`, `CT-ORCH-14`):
#: a submission's extraction and scoring work is enumerated only when its status is in
#: this set. `CT-INGEST-11` fixes the set as the complete rule — the orchestrator treats
#: it as the whole of admission, never re-deriving ingest's gates.
#:
#: **Interpretation recorded (#59): a `NULL` `ingest_status` admits.** The column carries
#: no default (the ingest migration adds it bare), so a submission ingest has not yet
#: judged reads NULL — a state the five-value CHECK does not cover and the requirement's
#: three refused values are not. The refused work the requirement names is the work ingest
#: *assigned a refused status*; a row ingest has not judged is not that. The enumeration
#: tests' seeded submissions (which set no status) depend on this reading.
SWEEP1_ADMITTED_INGEST_STATUSES: frozenset[str] = frozenset(
    {"ok", "low_confidence_ocr"}
)

#: Where the base enumeration's depths come from (`FR-SETUP-08`): base scoring depth 1
#: for `atomic`/`atomic_with_gate` criteria and 3 for `holistic` ones. Unknown scoring
#: models enumerate at depth 1 — the conservative base — and a package introducing a new
#: model name must extend this map rather than inherit a guess.
SCORING_MODEL_BASE_DEPTH: Mapping[str, int] = MappingProxyType({
    "atomic": 1,
    "atomic_with_gate": 1,
    "holistic": 3,
})


# --- the WorkUnit type (design v1.5 note) ------------------------------------------------------


@dataclass(frozen=True)
class WorkUnit:
    """One unit of work, as §3.7's v1.5 note defines it.

    The field list is exactly the design note's: `work_id`, `run_id`, `stage`,
    `student_ref`, `student_name`, `submission_id`, `criterion_id`, `submission_text`,
    `judge` (None for a deterministic unit) and `attempt`.

    **`student_name` is on the unit deliberately** (§3.7): the pseudonymization boundary
    is at **assembly** (`M-JUDGE`), not at the ledger. A unit carrying only `student_ref`
    would make `TC-PROV-21`, `SEC-04` and `TC-PROV-C13` unfalsifiable — they would pass
    against an assembler that copies every field it is given. The name travels on the unit
    so those cases can assert the assembled payload drops it.

    **`student_name` and `submission_text` are None on enumerated units.** The ledger row
    carries none of it — Tier C's tables hold `student_ref`, and text lives in the
    documents — so enumeration returns units with these unresolved; the lease surface
    (#58, `FR-ORCH-04`) resolves them from the store before handing a unit to a worker.
    None, not an empty string: None is visible ("not resolved yet"), an empty string is
    the silent-failure shape. Neither field is a `work_id` input, so resolving them later
    cannot fork the work-ID space.
    """

    work_id: str
    run_id: str
    stage: str
    student_ref: str
    student_name: str | None
    submission_id: str
    criterion_id: str | None
    submission_text: str | None
    judge: str | None
    attempt: int = 0


@dataclass(frozen=True)
class UnitProvenance:
    """Where one work unit's text came from: unit -> submission -> document (#223).

    Design §3.7's `WorkUnit` field list is closed, so the join is a lookup over the
    submission row rather than a field on the unit. The record carries identifiers only —
    no `student_ref`, `student_name` or text — so reading provenance widens nothing the
    ledger exposes; the pseudonymization boundary stays at assembly (`M-JUDGE`).

    `document_id` is the document the unit's text **came from**. Once the unit has been
    extracted, that is the document its evidence rows name (`read_from_evidence` is True),
    even if the submission was re-transcribed since. Before extraction it is the
    submission's current document, the row extraction will read. `current_document_id` is
    always the head of `M-INGEST`'s ordering; the two differ exactly when a re-transcription
    superseded the text a finished unit read. `document_ids` lists every document of the
    submission, oldest first. `hops` is the join as it was followed, one entry per table
    (with an `evidence:` hop when the evidence decided), so the trace shows the path.
    """

    work_id: str
    run_id: str
    stage: str
    submission_id: str
    document_id: str
    content_hash: str
    current_document_id: str
    read_from_evidence: bool
    document_ids: tuple[str, ...]
    hops: tuple[str, ...]


# --- the work-ID scheme (FR-ORCH-01) -----------------------------------------------------------


#: `FR-ORCH-01`'s nine inputs, in the requirement's own order. `compute_work_id` hashes
#: them in this order, and `TC-REG-06`'s committed reference population declares the same
#: order (`work-id-reference.inputs.json`); the two are kept visually adjacent on purpose.
WORK_ID_INPUTS: tuple[str, ...] = (
    "run_id",
    "stage",
    "submission_id",
    "criterion_id",
    "judge_id",
    "package_version_id",
    "panel_config",
    "prompt_template_version",
    "extractor_version",
)


def _row_evaluation_mode(criterion: Any) -> str:
    """One criterion row's declared evaluation mode (`FR-PKG-22`, `FR-ORCH-35`).

    Read from the column, with the shape default only for a row that predates the column
    — a package file migrated to version 11 always carries it, so the fallback covers the
    in-memory catalogue doubles rather than any stored package. `kind = 'mcq'` is NOT a
    test any consumer may make: the equivalence it encoded was retired with the column,
    because a judged multiple-choice criterion is a package the design allows and that
    test makes unrepresentable.
    """
    try:
        declared = criterion["evaluation_mode"]
    except (KeyError, IndexError, TypeError):
        declared = getattr(criterion, "evaluation_mode", None)
    if declared:
        return str(declared)
    try:
        kind = criterion["kind"]
    except (KeyError, IndexError, TypeError):
        kind = getattr(criterion, "kind", None)
    return "deterministic" if kind == "mcq" else "judged"


def _encode_field(value: str | None) -> bytes:
    """The canonical byte encoding of one `work_id` input.

    **The encoding `M-ORCH` chose where §3.7 is silent** (recorded on the #57 PR, and the
    migration note `TC-REG-06`'s grounds require): each field is encoded as a **type tag
    plus a decimal byte length plus the UTF-8 bytes**, and the nine encodings are
    concatenated in `WORK_ID_INPUTS` order and sha256'd once.

    - A `str` value encodes as ``S<len>:<utf-8 bytes>`` (e.g. ``S7:RUN-0001``).
    - `None` encodes as ``N`` — the deterministic-unit judge (`judge_id=None`), distinct
      from every string by tag, so no judge id can collide with the null judge and no
      separator-guessing is ever needed.

    Length-prefixed concatenation is canonical and unambiguous where a delimiter is not:
    ``("a", "bc")`` and ``("ab", "c")`` encode differently, which a join with any
    separator — including one as exotic as ``\\x1f`` — cannot promise across arbitrary
    field values. The tag is what makes the null-judge sentinel unforgeable rather than a
    string no real judge is likely to be named.

    A change to this encoding changes every `work_id` at once. That is the correct effect
    — it is the encoding, not the data, that moved — but it must be a conscious act with
    the migration note `TC-REG-06`'s grounds demand, never a side effect.
    """
    if value is None:
        return b"N"
    data = value.encode("utf-8")
    return b"S" + str(len(data)).encode("ascii") + b":" + data


def compute_work_id(
    *,
    run_id: str,
    stage: str,
    submission_id: str,
    criterion_id: str | None,
    judge_id: str | None,
    package_version_id: str,
    panel_config: str,
    prompt_template_version: str,
    extractor_version: str,
) -> str:
    """The content address of one unit of work (`FR-ORCH-01`, verbatim in structure).

    ``sha256`` over the nine named inputs, in `WORK_ID_INPUTS` order, under
    `_encode_field`'s canonical encoding; returned as the 64-character lowercase hex
    digest (`work_id` is a TEXT primary key in the ledger).

    Changing **any** input changes the id, which is what makes invalidation automatic
    (NFR-EXTRACT-02/03): a superseded document, a new prompt template version or a
    changed panel produces new units rather than a cleanup job. The arguments are
    keyword-only so a caller cannot transpose `criterion_id` and `judge_id` and silently
    address the wrong unit. `criterion_id` and `judge_id` admit None (a unit need not
    carry either); every other input is a string.

    Pure and total: no clock, no environment, no I/O — `NFR-ORCH-05`'s determinism is a
    property of the function alone, which is why the oracle is byte-identical `work_id`
    sets across two whole enumerations rather than a count.
    """
    values = {
        "run_id": run_id,
        "stage": stage,
        "submission_id": submission_id,
        "criterion_id": criterion_id,
        "judge_id": judge_id,
        "package_version_id": package_version_id,
        "panel_config": panel_config,
        "prompt_template_version": prompt_template_version,
        "extractor_version": extractor_version,
    }
    digest = hashlib.sha256()
    for name in WORK_ID_INPUTS:
        digest.update(_encode_field(values[name]))
    return digest.hexdigest()


# --- errors ------------------------------------------------------------------------------------


class WorkLedgerError(Exception):
    """Base class for the orchestrator's own failures.

    Distinct from `store.StoreError`: the store reports persistence mechanics; this module
    owns the ledger's meaning and its callers distinguish the two.
    """


class BrokenLineageError(WorkLedgerError):
    """A work unit's provenance does not reach a source document (#223, `FR-INGEST-01`).

    Raised by `Orchestrator.provenance` when the unit carries no submission, names a
    submission the cohort does not hold, or its submission has no document row. The join
    is refused rather than returned with a NULL `document_id`: a unit that cannot say
    which text it came from must not look traceable."""


class RunNotFoundError(WorkLedgerError):
    """No run row carries the id the caller named. Raised rather than guessed at: resume
    with no arguments finds its own runs, so an explicit `run_id` that resolves to nothing
    is a caller mistake worth naming."""


class RunStateError(WorkLedgerError):
    """A control operation named an edge FR-ORCH-25's machine does not declare.

    `run.status` follows `pending → running → (paused ↔ running) → complete | failed`
    and nothing else: `start` from anything but `pending`, and the terminal states as
    sources, are refused with this error while the row's state stays exactly where it
    was — the refusal is named, never absorbed, and never a state change."""


class EscalationPlanError(WorkLedgerError):
    """An escalation plan this module refuses to build (`FR-ORCH-10`'s gate).

    The plan builder is a pure function and its refusals are part of its contract
    (`TC-ORCH-20` asserts the exact exception): a plan that does not widen the panel
    (an escalation to the same count, or a reduction) is not an escalation — enqueuing
    it would look like work while adding nothing, which is the silent-no-op shape.
    Even panels raise the subclass, `EvenEscalationPlanError`.
    """


class EvenEscalationPlanError(EscalationPlanError):
    """An escalation plan producing an **even** `judge_count` (`FR-ORCH-10`, R48).

    A two-way tie broken by rule is a coin flip presented as a judgement — the fairness
    rule the odd-panel requirement exists for (`CT-AGG-03`: `judge_count` is 0 or odd,
    enforced by CHECK at the write). This is the exact exception `TC-ORCH-20` asserts
    for plans producing 2 or 4 judges; the ledger-side CHECK (`det_score_state_columns`)
    is the backstop, this refusal is the front one.
    """


# --- the ledger's schema (a numbered migration, per §3.3's discipline) --------------------------
#
# Tier C's registry stood at version 6 (`M-INGEST`'s five). The owning module adds its
# columns in a later numbered migration — the same discipline `M-PKG` followed on Tier P:
# `M-STORE` created `work_unit` with a minimal column set, and `M-ORCH` decides what a
# work unit carries.


_ORCH_COHORT_007: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE run (
            run_id             TEXT NOT NULL PRIMARY KEY,
            cohort_id          TEXT NOT NULL REFERENCES cohort(cohort_id),
            package_version_id TEXT NOT NULL,
            package_id         TEXT NOT NULL,
            panel_config       TEXT NOT NULL,
            backend_profile    TEXT NOT NULL,
            provider_config    TEXT NOT NULL,
            prompt_template_v  TEXT NOT NULL,
            status             TEXT NOT NULL
                CHECK (status IN ('pending', 'running', 'paused', 'complete', 'failed')),
            started_at         TEXT,
            completed_at       TEXT
        )
        """
    ),
    Statement("ALTER TABLE work_unit ADD COLUMN run_id TEXT NOT NULL DEFAULT ''"),
    Statement("ALTER TABLE work_unit ADD COLUMN criterion_id TEXT"),
    Statement("ALTER TABLE work_unit ADD COLUMN judge_id TEXT"),
    Statement(
        "ALTER TABLE work_unit ADD COLUMN origin TEXT NOT NULL DEFAULT 'base' "
        "CHECK (origin IN ('base', 'escalation', 'random_arm'))"
    ),
    Statement("ALTER TABLE work_unit ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"),
    Statement("ALTER TABLE work_unit ADD COLUMN last_error TEXT"),
    Statement(
        "CREATE INDEX idx_wu_sched ON work_unit(run_id, status, stage, criterion_id)"
    ),
)

#: #58's columns: the lease. `lease_owner` names the worker holding the claim;
#: `lease_expires_ticks` is the `M-STORE` monotonic counter value the lease expires at —
#: the **only** value the sweeper compares (`FR-STORE-11`: a wall-clock expiry would read
#: every lease live after the host clock moves backwards, `CT-STORE-14`'s exact failure);
#: `lease_expires_at` is the same expiry rendered on the wall clock for the operator
#: reading the row — recorded, never compared. Three columns rather than a lease table:
#: the lease is a work unit's transient state, and the state model has one home.
_ORCH_COHORT_008: tuple[Statement, ...] = (
    Statement("ALTER TABLE work_unit ADD COLUMN lease_owner TEXT"),
    Statement("ALTER TABLE work_unit ADD COLUMN lease_expires_ticks REAL"),
    Statement("ALTER TABLE work_unit ADD COLUMN lease_expires_at TEXT"),
)

TIER_MIGRATIONS[Tier.COHORT] = TIER_MIGRATIONS[Tier.COHORT] + (
    Migration(version=7, name="orch_run_ledger", statements=_ORCH_COHORT_007),
    Migration(version=8, name="orch_leasing", statements=_ORCH_COHORT_008),
)

#: #60's ledger growth: the escalation queue, the circuit-breaker latch, and the
#: completion ticks the criterion breaker's window reads. The cohort registry stood at
#: version 9 (`M-DET`'s `det_score_state_columns`) — this takes the next free number.
#:
#: - **`escalation_request`** is the escalation budget's memory (`FR-ORCH-14`): when the
#:   run-wide rate is over budget, a request that expected-value order cannot admit *now*
#:   is persisted here (`admitted = 0`) instead of being refused into silence — a queue
#:   held only in the process would lose the remainder to a crash, and a lost remainder is
#:   scrutiny reduced by an accident, exactly the shape `CT-ORCH-16` forbids. `request_id`
#:   is **content-derived** (run, submission, criterion, the prior judge count the plan
#:   widened from), so a retried enqueue after a crash is `INSERT OR IGNORE`'d onto the
#:   request it already made — at-least-once callers cannot queue a rung twice.
#: - **`circuit_breaker`** is the criterion breaker's latch (`FR-ORCH-13`): tripping is a
#:   one-way event the operator surface alerts on, so it is a row, not a derived predicate.
#:   `breaker_id` is content-derived (run, criterion, kind) for the same idempotence.
#: - **`work_unit.done_ticks`** is the `M-STORE` monotonic counter reading at completion —
#:   the "first 20–30 submissions **processed**" of `FR-ORCH-13` needs a completion ORDER,
#:   and the lease counter is the only monotonic order the ledger already has (`FR-STORE-11`).
#:   Written by `complete()`, read by the breaker's window; a row completed without ticks
#:   (test scaffolding's direct writes) is order-unknown and sits outside the window.
_ORCH_COHORT_010: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE escalation_request (
            request_id     TEXT NOT NULL PRIMARY KEY,
            run_id         TEXT NOT NULL REFERENCES run(run_id),
            submission_id  TEXT NOT NULL,
            criterion_id   TEXT NOT NULL,
            expected_value REAL,
            admitted       INTEGER NOT NULL CHECK (admitted IN (0, 1)),
            requested_at   TEXT NOT NULL,
            admitted_at    TEXT,
            detail         TEXT
        )
        """
    ),
    Statement(
        """
        CREATE TABLE circuit_breaker (
            breaker_id   TEXT NOT NULL PRIMARY KEY,
            run_id       TEXT NOT NULL REFERENCES run(run_id),
            criterion_id TEXT NOT NULL,
            kind         TEXT NOT NULL CHECK (kind IN ('criterion_escalation')),
            tripped_at   TEXT NOT NULL,
            detail       TEXT NOT NULL,
            UNIQUE (run_id, criterion_id, kind)
        )
        """
    ),
    Statement("ALTER TABLE work_unit ADD COLUMN done_ticks REAL"),
    Statement(
        "CREATE INDEX idx_wu_escalation ON "
        "work_unit(run_id, origin, criterion_id, submission_id)"
    ),
    Statement(
        "CREATE INDEX idx_esc_queue ON "
        "escalation_request(run_id, admitted, expected_value)"
    ),
)

TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT]
    + (Migration(version=10, name="orch_escalation_ledger", statements=_ORCH_COHORT_010),),
    key=lambda m: m.version,
))

#: #61's lifecycle columns and the control-row queue. The cohort registry stood at
#: version 11 (`M-EXTRACT`'s `extract_evidence_columns`, #68 — this branch originally
#: took 11 too, and the merge renumbered to the next free number rather than rewrite
#: a landed migration's number). `cost_estimate` carries the
#: pre-dispatch estimate start() displays (canonical Decimal string; NULL where no
#: estimator seam was available — a fabricated zero would read as a measured price,
#: the principle `CT-PROV-03` states for cost figures). `cost_spend` is the accrual the
#: ceiling is enforced against, written in the same transaction as each claim that
#: incurred it — the ledger's own figure, never a side-file counter and never an
#: up-front optimism. `pause_reason` is every pause's alert text: what the operator
#: surface reads to learn WHY the run stopped. `run_control` is CT-ORCH-13's queue:
#: pause and resume requests land here and are effected when the orchestrator reads
#: them — the request is never the effect, which is why a control row written while
#: nothing is dispatching queues and is honoured at the next read.
_ORCH_COHORT_012: tuple[Statement, ...] = (
    Statement("ALTER TABLE run ADD COLUMN cost_estimate TEXT"),
    Statement("ALTER TABLE run ADD COLUMN cost_spend TEXT NOT NULL DEFAULT '0'"),
    Statement("ALTER TABLE run ADD COLUMN pause_reason TEXT"),
    Statement(
        """
        CREATE TABLE run_control (
            control_id   TEXT NOT NULL PRIMARY KEY,
            run_id       TEXT NOT NULL REFERENCES run(run_id),
            action       TEXT NOT NULL CHECK (action IN ('pause', 'resume')),
            reason       TEXT,
            requested_at TEXT NOT NULL,
            applied_at   TEXT
        )
        """
    ),
    Statement(
        "CREATE INDEX idx_run_control_open ON run_control(run_id, applied_at)"
    ),
)

TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT]
    + (Migration(version=12, name="orch_run_lifecycle", statements=_ORCH_COHORT_012),),
    key=lambda m: m.version,
))

#: #62's report indexes — the poll-serving covering indexes (`NFR-ORCH-06`:
#: 40,000 units without degradation). The progress report's aggregates must stay
#: index-served as the ledger grows, or a poll's cost grows with the sort rather
#: than the scan: `idx_wu_report` carries the `(stage, criterion_id, judge_id)`
#: triples the report's granularity groups (`FR-ORCH-23`) in index order, so
#: `select_run_by_unit` streams instead of temp-sorting 40,000 rows per poll —
#: every indexed column is insert-time constant, so the index never pays
#: maintenance on a status transition. `idx_wu_pairs` serves the escalation
#: rate's pair denominator (`FR-ORCH-14`): the done-score `(submission_id,
#: criterion_id)` DISTINCT streams in index order instead of sorting the run's
#: whole score ledger; `status` sits at position 2, the same maintenance
#: profile `idx_wu_sched` (the leasing scan it sits beside) already pays.
#: The version is 15: #78's `judge_verdict_columns` (13) and #97's
#: `synth_narrative_key` (14) took the numbers first at their merges, so this
#: renumbered at the merge — the pin-rot rule's documented dance, and the pin in
#: `store.py` moved 14→15 in the same change.
_ORCH_COHORT_015: tuple[Statement, ...] = (
    Statement(
        "CREATE INDEX idx_wu_report ON "
        "work_unit(run_id, stage, criterion_id, judge_id)"
    ),
    Statement(
        "CREATE INDEX idx_wu_pairs ON "
        "work_unit(run_id, status, stage, submission_id, criterion_id)"
    ),
)

TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT]
    + (Migration(version=15, name="orch_report_indexes", statements=_ORCH_COHORT_015),),
    key=lambda m: m.version,
))


# --- the runtime statements (declared, never assembled — FR-STORE-08, SEC-15) -------------------

#: Tier C, migration 24 (#362, `FR-ORCH-28`): the per-cell composition phases.
#:
#: A cell is one (submission, criterion). The composition layer walks it in phases —
#: `integrity_pre` before the panel scores it, `integrity_post` after, `aggregated` when the
#: score row is written — and each phase must be recorded where a RESTART can see it: the pipeline
#: is resume-safe (`NFR-PIPE-01`), and a phase kept in memory would be re-run after a crash,
#: re-billing the model calls it stands for. `units_consumed` is how many terminal units the
#: phase was computed over, which is what lets `ready_cells` tell "aggregated once, then three
#: more verdicts landed" from "aggregated, nothing since".
#:
#: The PK is `(run_id, submission_id, criterion_id, phase)`: one row per phase per cell, so
#: marking the same phase twice is an upsert rather than a second row, and a phase outside the
#: declared three is refused by the CHECK rather than by the caller's care.
_ORCH_CELL_PHASE: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE cell_phase (
            run_id         TEXT    NOT NULL,
            submission_id  TEXT    NOT NULL,
            criterion_id   TEXT    NOT NULL,
            phase          TEXT    NOT NULL
                CHECK (phase IN ('integrity_pre', 'integrity_post', 'aggregated')),
            units_consumed INTEGER NOT NULL DEFAULT 0,
            recorded_at    TEXT    NOT NULL,
            PRIMARY KEY (run_id, submission_id, criterion_id, phase)
        )
        """
    ),
    # `ready_cells` groups the run's units by cell on every poll — the composition layer's
    # heartbeat — and without this index that read is a full scan of `work_unit` per poll.
    # The phases themselves ride the `cell_phase` PK's own prefix and need no second index.
    Statement(
        "CREATE INDEX idx_wu_cell ON work_unit (run_id, submission_id, criterion_id, stage)"
    ),
)

TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (
        Migration(version=24, name="orch_cell_phase", statements=_ORCH_CELL_PHASE),
    ), key=lambda m: m.version
))


ORCH_STATEMENTS: dict[str, Statement] = {
    "insert_run": Statement(
        "INSERT INTO run (run_id, cohort_id, package_version_id, package_id, "
        "panel_config, backend_profile, provider_config, prompt_template_v, status) "
        "VALUES (:run_id, :cohort_id, :package_version_id, :package_id, :panel_config, "
        ":backend_profile, :provider_config, :prompt_template_v, 'pending')"
    ),
    # The run-row read carries the lifecycle columns #61 added (`cost_estimate`,
    # `cost_spend`, `pause_reason`) beside the frozen backend snapshot — the ceiling is
    # enforced from the row's OWN figures, never from current configuration.
    "select_run": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id, panel_config, "
        "backend_profile, provider_config, prompt_template_v, status, started_at, "
        "completed_at, cost_estimate, cost_spend, pause_reason "
        "FROM run WHERE run_id = :run_id"
    ),
    # The runs resume() may drive: everything not yet finished. Ordered by run_id so two
    # enumerations of the same state walk the same rows in the same order (NFR-ORCH-05).
    "select_open_runs": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id, panel_config, "
        "backend_profile, provider_config, prompt_template_v, status, started_at, "
        "completed_at, cost_estimate, cost_spend, pause_reason "
        "FROM run WHERE status IN ('pending', 'running', 'paused') "
        "ORDER BY run_id"
    ),
    # The same columns with no status filter: `recover` (FR-PIPE-07) has to find runs that are
    # COMPLETE but whose grades are not all final, and those are exactly the runs
    # `select_open_runs` excludes. Filtering in Python rather than in SQL keeps one statement
    # for every status a caller might ask about.
    # The cohort's declared consent class (`ADR-5`). `M-PIPE` needs it to build the `CohortRef`
    # `resolve_run_config` gates on: `CohortRef` defaults to `'real'` and that default is
    # fail-closed by design, so a caller that does not read the stored value refuses every
    # synthetic cohort against a remote backend (`FR-CONF-08`).
    # Rewrite ONLY the recorded reason on a run that is already paused. `pause()` deliberately
    # changes nothing in that case — an operator double-pausing must not manufacture a state
    # flip — but a run refused for a NEW cause needs the new cause on the row, or the operator
    # surface explains the stop with a reason that is no longer why.
    "update_pause_reason": Statement(
        "UPDATE run SET pause_reason = :pause_reason "
        "WHERE run_id = :run_id AND status = 'paused'"
    ),
    # One unit's ledger status. A stage door may terminalise its own unit — `M-EXTRACT`'s
    # worker quarantines at the strike ceiling and RETURNS rather than raising — and the
    # composition layer has to know that before it reports the unit completed, because
    # `complete()` refuses a unit a worker already quarantined.
    "select_unit_status": Statement(
        "SELECT status FROM work_unit WHERE work_id = :work_id"
    ),
    "select_cohort_row": Statement(
        "SELECT cohort_id, consent_class FROM cohort WHERE cohort_id = :cohort_id"
    ),
    "select_all_runs": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id, panel_config, "
        "backend_profile, provider_config, prompt_template_v, status, started_at, "
        "completed_at, cost_estimate, cost_spend, pause_reason "
        "FROM run ORDER BY run_id"
    ),
    "select_run_work_ids": Statement(
        "SELECT work_id FROM work_unit WHERE run_id = :run_id"
    ),
    "select_submissions": Statement(
        "SELECT submission_id, student_ref, ingest_status FROM submission "
        "WHERE cohort_id = :cohort_id ORDER BY submission_id"
    ),
    "select_run_counts": Statement(
        "SELECT stage, status, COUNT(*) AS n FROM work_unit WHERE run_id = :run_id "
        "GROUP BY stage, status"
    ),
    "insert_work_unit": Statement(
        "INSERT OR IGNORE INTO work_unit "
        "(work_id, submission_id, stage, status, run_id, criterion_id, judge_id, "
        "origin, attempts) "
        "VALUES (:work_id, :submission_id, :stage, 'pending', :run_id, :criterion_id, "
        ":judge_id, :origin, 0)"
    ),
    # Read inside the same transaction as each `insert_work_unit`: the ledger's own
    # count of what that write did, since `OR IGNORE` reports neither an ignored
    # duplicate nor a refused row.
    "select_changes": Statement("SELECT changes() AS n"),
    "insert_audit_record": Statement(
        "INSERT INTO audit_record (audit_record_id, run_id, recorded_at, profile_summary) "
        "VALUES (:audit_record_id, :run_id, :recorded_at, :profile_summary)"
    ),
    # -- leasing (FR-ORCH-04) ------------------------------------------------------------------
    # Claim candidates: pending units of one stage **of one run** (a paused run schedules
    # nothing — CT-ORCH-12 — and #59's claim pass walks open runs individually, because
    # the dispatch order is a function of the run's own package). Ordered by work_id as
    # the base order — the stage's sweep key is applied over these rows in Python, where
    # the run's catalog lives; work_id is the deterministic tie-break beneath every key.
    # Unbounded per read, on purpose: the sweep order must choose from ALL pending
    # candidates of the run, and a SQL LIMIT applied before the Python order would
    # truncate by work_id and silently mis-order the sweep. What keeps the fine-grained
    # drain off the quadratic (NFR-ORCH-01) is not a LIMIT here but `_claim_pass`'s
    # order cache: the sorted result is derived once and drained front to back, so a
    # one-at-a-time poll late in a large run serves its head instead of re-reading and
    # re-sorting the whole pending set.
    "select_run_claimable": Statement(
        "SELECT w.work_id, w.run_id, w.stage, w.submission_id, w.criterion_id, "
        "w.judge_id, w.origin, w.attempts AS attempt, s.student_ref AS student_ref "
        "FROM work_unit w "
        "JOIN submission s ON s.submission_id = w.submission_id "
        "WHERE w.run_id = :run_id AND w.status = 'pending' AND w.stage = :stage "
        "ORDER BY w.work_id"
    ),
    # The Sweep 2 gate's read (`FR-ORCH-06`): the extraction units of the run that are
    # not done — pending, leased, or quarantined. A score unit is claimable only when
    # neither its own criterion's extraction nor any dependency's is in this set. One
    # indexed query per run per claim pass; the set it returns is what the gate diffs.
    "select_not_done_extracts": Statement(
        "SELECT criterion_id, submission_id FROM work_unit "
        "WHERE run_id = :run_id AND stage = 'extract' AND status != 'done'"
    ),
    "select_work_unit": Statement(
        "SELECT * FROM work_unit WHERE work_id = :work_id"
    ),
    # --- #362 (FR-ORCH-28/29/30): the per-cell composition phases -----------------------------
    "upsert_cell_phase": Statement(
        "INSERT INTO cell_phase (run_id, submission_id, criterion_id, phase, "
        "units_consumed, recorded_at) VALUES (:run_id, :submission_id, :criterion_id, "
        ":phase, :units_consumed, :recorded_at) "
        "ON CONFLICT (run_id, submission_id, criterion_id, phase) DO UPDATE SET "
        "units_consumed = excluded.units_consumed, recorded_at = excluded.recorded_at"
    ),
    "select_cell_phases": Statement(
        "SELECT submission_id, criterion_id, phase, units_consumed FROM cell_phase "
        "WHERE run_id = :run_id"
    ),
    # One row per (cell, stage) with its terminal and total unit counts — `ready_cells`'
    # whole input beside the phases. Terminal is `done` or `quarantined`: a quarantined unit
    # will not produce more evidence, so a cell waiting on it would wait forever.
    "select_cell_unit_counts": Statement(
        "SELECT submission_id, criterion_id, stage, "
        "SUM(CASE WHEN status IN ('done', 'quarantined') THEN 1 ELSE 0 END) AS terminal, "
        "COUNT(*) AS total FROM work_unit WHERE run_id = :run_id "
        "GROUP BY submission_id, criterion_id, stage"
    ),
    # The provenance join (#223, FR-INGEST-01): unit -> submission -> document, LEFT-joined
    # so a broken hop reads as NULL here and is refused by `provenance()`, never imputed.
    # One row per document of the submission, oldest first; the head is the last row, the
    # same ordering `M-INGEST`'s `select_document_head` defines.
    "select_unit_provenance": Statement(
        "SELECT w.work_id, w.run_id, w.stage, w.submission_id, "
        "s.submission_id AS joined_submission_id, d.document_id, d.content_hash "
        "FROM work_unit w "
        "LEFT JOIN submission s ON s.submission_id = w.submission_id "
        "LEFT JOIN document d ON d.submission_id = s.submission_id "
        "WHERE w.work_id = :work_id "
        "ORDER BY d.created_at, d.document_id"
    ),
    # The document a unit's text was actually READ from, once extraction has run: the
    # evidence rows it wrote carry the document_id of the head at that moment.
    "select_unit_evidence_documents": Statement(
        "SELECT DISTINCT document_id FROM evidence "
        "WHERE work_id = :work_id AND document_id IS NOT NULL ORDER BY document_id"
    ),
    # The one-row existence probe behind lease()'s enumerate-on-empty gate: a run whose
    # ledger holds *any* row was enumerated (or partially so, which is a crash
    # `resume()` repairs) — re-enumerating it on every drained poll would make the
    # hot claim path a full enumeration pass (NFR-ORCH-01).
    "select_any_work_unit": Statement(
        "SELECT work_id FROM work_unit WHERE run_id = :run_id LIMIT 1"
    ),
    "select_leased_units": Statement(
        "SELECT w.work_id, w.run_id, w.lease_expires_ticks FROM work_unit w "
        "JOIN run r ON r.run_id = w.run_id "
        "WHERE w.status = 'leased' AND r.status IN ('pending', 'running') "
        "ORDER BY w.work_id"
    ),
    # The claim: pending → leased, guarded on `status = 'pending'` so two claimers
    # cannot both win. `changes()` read in the same transaction says whether THIS write
    # won — the lease-clock expiry was persisted before the attempt, so a lost guard is
    # a no-op here and a slightly-raised counter there (see lease()'s docstring).
    "mark_leased": Statement(
        "UPDATE work_unit SET status = 'leased', lease_owner = :owner, "
        "lease_expires_ticks = :expires_ticks, lease_expires_at = :expires_at "
        "WHERE work_id = :work_id AND status = 'pending'"
    ),
    # The heartbeat: extends a live lease's expiry only. `:owner IS NULL OR` makes the
    # owner check optional — a caller naming its worker_id cannot extend a lease another
    # worker holds, and an unnamed heartbeat is still guarded on `leased`. The guard
    # makes a lost lease a zero-row write, which the caller detects via `changes()`.
    "extend_lease": Statement(
        "UPDATE work_unit SET lease_expires_ticks = :expires_ticks, "
        "lease_expires_at = :expires_at "
        "WHERE work_id = :work_id AND status = 'leased' "
        "AND (:owner IS NULL OR lease_owner = :owner)"
    ),
    # The sweeper's requeue: expired lease → pending, lease columns cleared. Attempts
    # survive the round-trip: the unit's failure history is not the lease's.
    "requeue_expired": Statement(
        "UPDATE work_unit SET status = 'pending', lease_owner = NULL, "
        "lease_expires_ticks = NULL, lease_expires_at = NULL "
        "WHERE work_id = :work_id AND status = 'leased'"
    ),
    "mark_done": Statement(
        "UPDATE work_unit SET status = 'done', lease_owner = NULL, "
        "lease_expires_ticks = NULL, lease_expires_at = NULL, "
        "done_ticks = :done_ticks "
        "WHERE work_id = :work_id AND status IN ('leased', 'pending')"
    ),
    # The failure taxonomy: requeue with the attempt counted, or quarantine at the
    # ceiling — last_error retained in both arms, lease columns cleared. The count and
    # the status arm are computed **inside the statement** (`attempts + 1`; every SET
    # expression sees the pre-update row), so two failure reports cannot both read the
    # same count and write the same increment — one attempt can never be lost, and
    # quarantine lands on the report that actually reaches the ceiling.
    "record_failure": Statement(
        "UPDATE work_unit SET "
        "status = CASE WHEN attempts + 1 >= :max_attempts THEN 'quarantined' "
        "ELSE 'pending' END, "
        "attempts = attempts + 1, "
        "last_error = :last_error, lease_owner = NULL, "
        "lease_expires_ticks = NULL, lease_expires_at = NULL "
        "WHERE work_id = :work_id AND status IN ('leased', 'pending')"
    ),
    # -- escalation, the random arm and the breakers (FR-ORCH-09/10/11/13/14) ------------------
    # The criterion's judges for one (submission, criterion): every score unit's judge,
    # whatever its origin — the base panel, the random arm's widening and a prior
    # escalation rung are all the panel the criterion now has. Ordered by work_id so the
    # prior-judge list is deterministic (the plan's derivation reads it).
    "select_pair_score_judges": Statement(
        "SELECT judge_id FROM work_unit "
        "WHERE run_id = :run_id AND submission_id = :submission_id "
        "AND criterion_id = :criterion_id AND stage = 'score' ORDER BY work_id"
    ),
    # The criterion breaker's window (`FR-ORCH-13`): the submissions whose judged
    # scoring for one criterion completed EARLIEST, by the monotonic completion ticks.
    # Rows without ticks are order-unknown and excluded — the window is the first N
    # the ledger can honestly order. MIN(), not bare completion, because a submission's
    # panel completes unit by unit; its processing moment is its FIRST verdict.
    "select_criterion_window": Statement(
        "SELECT submission_id, MIN(done_ticks) AS first_done FROM work_unit "
        "WHERE run_id = :run_id AND criterion_id = :criterion_id "
        "AND stage = 'score' AND judge_id IS NOT NULL AND status = 'done' "
        "AND done_ticks IS NOT NULL "
        "GROUP BY submission_id ORDER BY first_done ASC, submission_id ASC LIMIT :n"
    ),
    # The escalation pairs of one criterion: distinct submissions with at least one
    # escalation-origin unit. The breaker intersects this with its window.
    "select_criterion_escalated": Statement(
        "SELECT DISTINCT submission_id FROM work_unit "
        "WHERE run_id = :run_id AND criterion_id = :criterion_id "
        "AND origin = 'escalation'"
    ),
    # One pair's escalation count — the idempotence probe: an enqueue for a pair that
    # already carries escalation-origin units is a no-op, whatever path widened it.
    "select_pair_escalated": Statement(
        "SELECT COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id AND submission_id = :submission_id "
        "AND criterion_id = :criterion_id AND origin = 'escalation'"
    ),
    # The run-wide budget's OBSERVED rate (`FR-ORCH-14`): distinct (submission,
    # criterion) pairs whose judged scoring has completed, and pairs whose escalation
    # has completed. Both sides are done-based because the rate is an observation —
    # an escalation whose panel is still running has produced no outcome to count,
    # and counting plans instead of outcomes would defer the very units the budget
    # exists to carry (a run's first escalated pair would read as a 100% rate). Both
    # are indexed aggregates over the run's score units, never a side-file counter
    # (the ledger is the only bookkeeping, FR-ORCH-02). `idx_wu_pairs` (the report
    # indexes' migration) carries the processed side: its (status, stage) range
    # precedes the (submission_id, criterion_id) pair, so the DISTINCT streams in
    # index order instead of temp-sorting every done score unit per poll.
    "select_processed_results": Statement(
        "SELECT COUNT(*) AS n FROM (SELECT DISTINCT submission_id, criterion_id "
        "FROM work_unit WHERE run_id = :run_id AND stage = 'score' "
        "AND judge_id IS NOT NULL AND status = 'done')"
    ),
    "select_escalated_results": Statement(
        "SELECT COUNT(*) AS n FROM (SELECT DISTINCT submission_id, criterion_id "
        "FROM work_unit WHERE run_id = :run_id AND origin = 'escalation' "
        "AND status = 'done')"
    ),
    # The escalation record (`FR-ORCH-14`). A request is content-addressed (see the
    # migration note) and INSERT OR IGNORE'd, so a retried enqueue cannot record a
    # rung twice; the row carries the caller's expected value, which is the ranking
    # key the dispatch-time admission consumes. The enqueue flips `admitted` once its
    # units are written — the flag records "this request's units are in the ledger",
    # not a budget decision: the budget rations DISPATCH (`admit_escalations` at the
    # claim pass), because the atomicity clause (`CT-ORCH-08`) has the enqueue write
    # the plan into the verdict's transaction whatever the budget is doing.
    "insert_escalation_request": Statement(
        "INSERT OR IGNORE INTO escalation_request "
        "(request_id, run_id, submission_id, criterion_id, expected_value, "
        "admitted, requested_at, detail) "
        "VALUES (:request_id, :run_id, :submission_id, :criterion_id, "
        ":expected_value, 0, :requested_at, :detail)"
    ),
    "select_queue_depth": Statement(
        "SELECT COUNT(*) AS n FROM escalation_request "
        "WHERE run_id = :run_id AND admitted = 0"
    ),
    # The dispatch gate's read (`FR-ORCH-14`): the run's pending escalation pairs with
    # their request's expected value (0.0 when the request row is absent — the arm
    # never writes one and a lost row must not rank above a valued one). This is the
    # candidate list `admit_escalations` evaluates at claim time; the provisional
    # half is the remainder `FR-ORCH-14` marks.
    "select_pending_escalation_pairs": Statement(
        "SELECT w.submission_id, w.criterion_id, "
        "COALESCE(q.expected_value, 0.0) AS expected_value "
        "FROM work_unit w "
        "LEFT JOIN escalation_request q "
        "ON q.run_id = w.run_id AND q.submission_id = w.submission_id "
        "AND q.criterion_id = w.criterion_id "
        "WHERE w.run_id = :run_id AND w.origin = 'escalation' "
        "AND w.status = 'pending' "
        "GROUP BY w.submission_id, w.criterion_id, q.expected_value"
    ),
    # The deprecated two-element key's resolution (FR-ORCH-34, CT-ORCH-26): the runs
    # whose ledger holds the pair's score panel, open runs flagged. Exactly one
    # candidate resolves; two or more are ambiguous and refused — a key that names no
    # run must not widen every run's panel.
    "select_pair_runs": Statement(
        "SELECT DISTINCT w.run_id, "
        "r.status IN ('pending', 'running', 'paused') AS is_open "
        "FROM work_unit w JOIN run r ON r.run_id = w.run_id "
        "WHERE w.submission_id = :submission_id AND w.criterion_id = :criterion_id "
        "AND w.stage = 'score' ORDER BY w.run_id"
    ),
    # The three-element key's check: the named run's ledger holds the pair's panel.
    "select_run_pair_panel": Statement(
        "SELECT 1 FROM work_unit WHERE run_id = :run_id "
        "AND submission_id = :submission_id AND criterion_id = :criterion_id "
        "AND stage = 'score' LIMIT 1"
    ),
    "admit_request": Statement(
        "UPDATE escalation_request SET admitted = 1, admitted_at = :admitted_at, "
        "detail = :detail WHERE request_id = :request_id AND admitted = 0"
    ),
    # The breaker latch (`FR-ORCH-13`): content-addressed, INSERT OR IGNORE — a
    # criterion trips once; a second trip evaluation cannot rewrite the first event.
    "insert_breaker": Statement(
        "INSERT OR IGNORE INTO circuit_breaker "
        "(breaker_id, run_id, criterion_id, kind, tripped_at, detail) "
        "VALUES (:breaker_id, :run_id, :criterion_id, 'criterion_escalation', "
        ":tripped_at, :detail)"
    ),
    "select_breaker": Statement(
        "SELECT breaker_id, criterion_id, kind, tripped_at, detail "
        "FROM circuit_breaker WHERE run_id = :run_id AND criterion_id = :criterion_id "
        "AND kind = 'criterion_escalation'"
    ),
    "select_run_breakers": Statement(
        "SELECT criterion_id, kind, tripped_at, detail FROM circuit_breaker "
        "WHERE run_id = :run_id ORDER BY criterion_id ASC, kind ASC"
    ),
    # -- the run lifecycle and the cost ceiling (FR-ORCH-15/16/17/25, #61) -----------------------
    # start()'s edge: pending → running, stamping started_at. The guard makes every
    # undeclared edge a zero-row write the caller detects via changes() — the machine
    # never moves along an edge FR-ORCH-25 does not declare.
    "transition_run_started": Statement(
        "UPDATE run SET status = 'running', started_at = :started_at, "
        "pause_reason = NULL, completed_at = NULL "
        "WHERE run_id = :run_id AND status = 'pending'"
    ),
    # The lifecycle's guarded transition, shared by pause/resume/complete: the
    # from_status guard IS the transition matrix's enforcement — a request from a
    # state the machine does not declare the edge from writes nothing.
    "transition_run_status": Statement(
        "UPDATE run SET status = :to_status, pause_reason = :pause_reason, "
        "completed_at = :completed_at "
        "WHERE run_id = :run_id AND status = :from_status"
    ),
    # The orchestrator's own sensed pauses (cost ceiling reached mid-dispatch): from
    # either dispatchable state, never from a terminal one. The reason text is the
    # alert — the pause names its spend and what remains (FR-ORCH-15).
    "pause_run_sensed": Statement(
        "UPDATE run SET status = 'paused', pause_reason = :pause_reason, "
        "completed_at = NULL "
        "WHERE run_id = :run_id AND status IN ('running', 'pending')"
    ),
    "accrue_run_spend": Statement(
        "UPDATE run SET cost_spend = :cost_spend WHERE run_id = :run_id"
    ),
    "set_run_estimate": Statement(
        "UPDATE run SET cost_estimate = :cost_estimate WHERE run_id = :run_id"
    ),
    "count_run_pending": Statement(
        "SELECT COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id AND status = 'pending'"
    ),
    # The completion probe's read (FR-ORCH-12): a run completes when nothing is
    # pending and nothing is in flight. Quarantined units hold the run open only
    # through the scoring they gated (their score units stay pending).
    "select_run_open_units": Statement(
        "SELECT COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id AND status IN ('pending', 'leased')"
    ),
    # The estimate's units: everything the run may still dispatch, one row per unit
    # with the seam's keys (the same shape the claim select hands over).
    "select_run_units_for_estimate": Statement(
        "SELECT w.work_id, w.run_id, w.stage, w.submission_id, w.criterion_id, "
        "w.judge_id, w.origin, w.attempts AS attempt, s.student_ref AS student_ref "
        "FROM work_unit w "
        "JOIN submission s ON s.submission_id = w.submission_id "
        "WHERE w.run_id = :run_id AND w.status IN ('pending', 'leased') "
        "ORDER BY w.work_id"
    ),
    # -- the control rows (CT-ORCH-13) ------------------------------------------------------------
    # A control action WRITES a row; the orchestrator EFFECTS it when it reads one —
    # the request is never the effect. A row written while no orchestrator is reading
    # queues (applied_at NULL) and is honoured at the next read: start, resume, or a
    # claim pass of a run that is actively dispatching.
    "insert_run_control": Statement(
        "INSERT INTO run_control "
        "(control_id, run_id, action, reason, requested_at) "
        "VALUES (:control_id, :run_id, :action, :reason, :requested_at)"
    ),
    "select_unapplied_control": Statement(
        "SELECT control_id, action, reason, requested_at FROM run_control "
        "WHERE run_id = :run_id AND applied_at IS NULL "
        "ORDER BY requested_at ASC, control_id ASC"
    ),
    #: `FR-ORCH-33`: the APPLIED controls, in the order they took effect. The wall clock
    #: subtracts paused intervals, and an interval is a pause that actually happened —
    #: `applied_at`, not `requested_at`: a pause requested and superseded before it ever
    #: applied never stopped the clock, and subtracting it would under-report the work.
    "select_applied_control": Statement(
        "SELECT control_id, action, applied_at FROM run_control "
        "WHERE run_id = :run_id AND applied_at IS NOT NULL "
        "ORDER BY applied_at ASC, control_id ASC"
    ),
    "mark_control_applied": Statement(
        "UPDATE run_control SET applied_at = :applied_at "
        "WHERE control_id = :control_id AND applied_at IS NULL"
    ),
    # A later resume supersedes the pause requests queued before it (latest control
    # intent wins): superseded pause rows are marked applied so the next start does
    # not pause a run the operator already resumed.
    "mark_pauses_applied": Statement(
        "UPDATE run_control SET applied_at = :applied_at "
        "WHERE run_id = :run_id AND action = 'pause' AND applied_at IS NULL"
    ),
    # The same supersede, bounded by request time: a resume supersedes only the
    # pauses queued BEFORE it — a pause requested after the resume is a later
    # intent, and marking it applied here would drop a request that was never
    # effected (it would be honoured at its own pass otherwise).
    "mark_pauses_applied_before": Statement(
        "UPDATE run_control SET applied_at = :applied_at "
        "WHERE run_id = :run_id AND action = 'pause' AND applied_at IS NULL "
        "AND requested_at < :requested_at"
    ),
    # -- progress, dispatch and run metrics (#62/#66) -------------------------------------------
    # The report's status totals: one GROUP BY over the run's rows. The ledger is the
    # only bookkeeping (FR-ORCH-02), so the report counts rows — never side-file
    # counters, which is what makes it right on a ledger that is growing underneath the
    # poll (CT-ORCH-09).
    "select_run_status_counts": Statement(
        "SELECT status, COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id GROUP BY status"
    ),
    # The report's (stage, criterion, judge) counts — FR-ORCH-23's granularity. One row
    # per distinct triple over ALL the run's units (judge NULL for extract and
    # deterministic units), so the counts sum to the ledger exactly (TC-ORCH-31).
    # The report's criterion axis rides the same aggregate: the distinct criteria the
    # run's ledger holds are exactly the criterion members of these groups, so one
    # pass feeds both and no second ledger scan is spent on the same set.
    "select_run_by_unit": Statement(
        "SELECT stage, criterion_id, judge_id, COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id GROUP BY stage, criterion_id, judge_id"
    ),
    # The first open unit, for the report's position fields (stage first with open
    # work, then its criterion and judge positions). The pick is the schedule
    # order `idx_wu_sched` already keeps — (status, stage, criterion_id), in-flight
    # first — not `work_id` order: an ordered probe down that index reads a
    # handful of entries where an `ORDER BY work_id` scan read the ledger's head
    # on every poll (the 40k-scaling degradation NFR-ORCH-06 exists to prevent).
    # No case pins WHICH open unit is pointed at — the position fields are coarse
    # operator pointers, and this reading is the one the index serves.
    "select_run_first_open": Statement(
        "SELECT stage, criterion_id, judge_id FROM work_unit "
        "WHERE run_id = :run_id AND status IN ('pending', 'leased') "
        "ORDER BY status, stage, criterion_id LIMIT 1"
    ),
    # The residency boundary's check (FR-ORCH-19): whether the resident judge still
    # holds score work **in flight** — its batch, the units already handed out for it.
    # A swap fires only when the answer is no: unloading a model whose judgments are
    # still running is the thrash the residency policy exists to prevent. Pending
    # units do not count — gated or budget-deferred work is not dispatchable (it may
    # never become ready without an operator), so it is no batch's tail; when it does
    # become ready the model reloads to serve it.
    "select_judge_leased_units": Statement(
        "SELECT COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id AND stage = 'score' AND judge_id = :judge_id "
        "AND status = 'leased'"
    ),
    # The score units in flight: the completion predicate's second clause
    # (FR-ORCH-12) — a scoring judgment in flight can still disagree with its panel
    # and spawn an escalation.
    "select_run_leased_score": Statement(
        "SELECT COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id AND stage = 'score' AND status = 'leased'"
    ),
    # The run's escalation-origin units (any status) — the escalated-units metric's
    # numerator is the ledger's own rows (FR-ORCH-02).
    "select_run_escalation_units": Statement(
        "SELECT COUNT(*) AS n FROM work_unit "
        "WHERE run_id = :run_id AND origin = 'escalation'"
    ),
    # The run-metrics write (CT-ORCH-20 makes the names contract): one EAV row per
    # metric, REPLACE so a re-flush updates in place. M-ORCH is the sole writer
    # (CT-STORE-03's single-writership: the orchestrator owns what the run did).
    #: `FR-ORCH-32`: the cache hit rates OTHER runs recorded — this run's baseline. Its
    #: own row is excluded, or the current figure would be part of the mean it is being
    #: compared against and a collapse would partly hide itself.
    "select_prior_cache_hit_rates": Statement(
        "SELECT value FROM run_metrics WHERE metric = 'cache_hit_rate' "
        "AND run_id <> :run_id ORDER BY run_id"
    ),
    #: `FR-ORCH-33`: this run's already-recorded metrics, so a flush can EXTEND a set
    #: rather than replace it with whatever this process happened to observe. Tier D.
    "select_run_metric_values": Statement(
        "SELECT metric, value FROM run_metrics WHERE run_id = :run_id ORDER BY metric"
    ),
    "insert_run_metric": Statement(
        "INSERT OR REPLACE INTO run_metrics (run_id, metric, value) "
        "VALUES (:run_id, :metric, :value)"
    ),
    # The OOM remedy's panel record (RES-13): the reduced panel is written to the run
    # row as a strict subset — a later validation record cannot claim the full panel
    # the box could not hold.
    "record_reduced_panel": Statement(
        "UPDATE run SET panel_config = :panel_config WHERE run_id = :run_id"
    ),
}


def panel_config_json(panel: Sequence[Any]) -> str:
    """The canonical `panel_config` string a run records and hashes.

    `panel_config` is one of `FR-ORCH-01`'s nine inputs, so its serialization is part of
    the work-ID scheme and lives in exactly one place. The panel is serialized as a JSON
    array of the judges' build ids **in panel order** — order is semantic (it is the
    dispatch order and the escalation ladder's first arm), so sorting would merge distinct
    panels the way `CT-CONF-C07` forbids for `panel_build_ref`. `separators` and
    `sort_keys` are pinned so two code paths cannot serialize the same panel differently
    and silently fork the work-ID space.

    A judge here is identified by its **resolved build id** (`FR-CONF-03`: a build
    identity, never a friendly name) — the same string the unit's `judge_id` hash input
    carries, so a panel change and a judge change are both visible to the hash.
    """
    return json.dumps(
        {"arms": [ref.build_id for ref in panel]},
        separators=_JSON_SEPARATORS,
        sort_keys=True,
    )


def default_package_id_for(package_version_id: str) -> str:
    """The Tier P key a version id lives under, by the catalog's own minted convention.

    `PackageCatalog.create_version` mints ``f"{package_id}@{uuid4().hex[:12]}"``, so the
    package id is everything before the **last** ``@``. Injectable on the orchestrator
    (`package_id_for`) so a deployment that names versions differently overrides this
    rather than bending the orchestrator to a guess — and so a test can pin the whole
    resolution without a real Tier P file.
    """
    package_id, _, _ = package_version_id.rpartition("@")
    if not package_id:
        raise WorkLedgerError(
            f"package version id {package_version_id!r} carries no '@<suffix>' portion, "
            "so it does not match the catalog's minted '<package_id>@<suffix>' form and "
            "its Tier P database cannot be resolved. Pass package_id_for explicitly if "
            "this deployment names versions differently."
        )
    return package_id


# --- environment-gated knobs (CLAUDE.md seam 3) -------------------------------------------------

#: The number of ledger inserts per committed transaction during enumeration. Production
#: default; `HARNESS_ORCH_ENUM_COMMIT_BATCH` adjusts it for a slower test box without a
#: code change. Read at **call** time, so a test can set the variable and call — a value
#: captured at construction would make the knob a lie.
ENUM_COMMIT_BATCH_ENV = "HARNESS_ORCH_ENUM_COMMIT_BATCH"
ENUM_COMMIT_BATCH_DEFAULT = 500

#: The lease TTL in seconds (design §3.7 Configuration: `ORCH_LEASE_SECONDS`, 300).
#: Production default; `HARNESS_ORCH_LEASE_SECONDS` adjusts it at **call** time — the
#: seam a slower test box (or a real-elapsed expiry case) sets instead of sleeping five
#: minutes. A lease this short would be a production incident, which is why the knob
#: refuses to be set implicitly: it only ever comes from the environment or this default.
ORCH_LEASE_SECONDS = 300
LEASE_SECONDS_ENV = "HARNESS_ORCH_LEASE_SECONDS"

#: The attempts a unit may fail before it quarantines (design §3.7 Configuration:
#: `ORCH_MAX_ATTEMPTS`, 3 — the state model's "attempts = 3"). Production default;
#: `HARNESS_ORCH_MAX_ATTEMPTS` adjusts it at call time. The taxonomy is honest at any
#: value: fewer attempts quarantine sooner and more visibly, never silently.
ORCH_MAX_ATTEMPTS = 3
MAX_ATTEMPTS_ENV = "HARNESS_ORCH_MAX_ATTEMPTS"

#: The random-arm sample rate (`FR-ORCH-11`, design §3.7 Configuration: `ORCH_RANDOM_ARM_RATE`,
#: 0.07 — the HLD's 5–10% band's stated Assumption). The arm measures the routing policy
#: itself (`FR-STATS-08`), so it draws independently of confidence and is **never**
#: suppressed by the escalation budget or a breaker (`CT-ORCH-15`) — its knob tunes the
#: sample size, nothing gates it. Production default; `HARNESS_ORCH_RANDOM_ARM_RATE`
#: adjusts it at **call** time. A rate of 0 disables the arm honestly (a test or a
#: deployment that does not want the compute spends none); a rate above 1 is refused.
ORCH_RANDOM_ARM_RATE = 0.07
RANDOM_ARM_RATE_ENV = "HARNESS_ORCH_RANDOM_ARM_RATE"

#: The run-wide escalation budget (`FR-ORCH-14`, design §3.7 Configuration:
#: `ORCH_ESCALATION_BUDGET`, 0.30): the share of processed results that may escalate
#: before further requests are admitted only in expected-value order, the remainder
#: queued and marked provisional. Production default; `HARNESS_ORCH_ESCALATION_BUDGET`
#: adjusts it at **call** time. The rate is never silently reduced by this knob: over
#: budget means rationed in the open (`CT-ORCH-16`), never refused quietly.
ORCH_ESCALATION_BUDGET = 0.30

# --- #370 (`FR-ORCH-32`): the five run alerts ---------------------------------------------
#
# §3.7 names five conditions an operator must hear about. They were design text with no
# surface carrying them, so `TC-ORCH-36` was written ahead against an invented name. This
# is that surface: ONE pure function over already-gathered state, which is what lets each
# condition be breached independently in a test and what keeps the rules out of the
# dispatch loop, where they would only be reachable by running a whole pass.

#: The fraction of the ceiling at which spend becomes an alert, BEFORE the pause at the
#: ceiling itself (`FR-ORCH-15`'s early form — "within 10% of ceiling"). A knob because
#: a ceiling's useful warning distance depends on how fast the run burns it.
COST_WARNING_FRACTION_DEFAULT = 0.9
COST_WARNING_FRACTION_ENV = "HARNESS_ORCH_COST_WARNING_FRACTION"

#: Cache collapse is RISK-23's ONLY detection path: nothing errors, throughput just dies.
#: Three guards, because a bare "below average" would cry wolf on every ordinary dip:
#:   * `_SIGMA` — how many standard deviations below the run history counts as a break
#:     rather than noise;
#:   * `_FLOOR` — an absolute floor the rate must ALSO be under, so a perfectly steady
#:     history (zero variance) does not make a 1% dip a three-sigma event;
#:   * `_MIN_HISTORY` — the fewest prior runs that make a mean meaningful at all. Below
#:     it there is no alert, because two runs are not a baseline (`CT-STATS-09`'s reading
#:     of "no data is not a zero", applied to a threshold instead of a rate).
CACHE_COLLAPSE_SIGMA_DEFAULT = 3.0
CACHE_COLLAPSE_SIGMA_ENV = "HARNESS_ORCH_CACHE_COLLAPSE_SIGMA"
CACHE_COLLAPSE_FLOOR_DEFAULT = 0.5
CACHE_COLLAPSE_FLOOR_ENV = "HARNESS_ORCH_CACHE_COLLAPSE_FLOOR"
CACHE_COLLAPSE_MIN_HISTORY_DEFAULT = 3
CACHE_COLLAPSE_MIN_HISTORY_ENV = "HARNESS_ORCH_CACHE_COLLAPSE_MIN_HISTORY"

#: The five names, stable and declared here rather than spelled at each raise site: an
#: operator's runbook keys off them, and a name assembled at the raise is a name that can
#: drift between two branches of the same condition.
ALERT_ESCALATION_RATE = "orch_escalation_rate_above_budget"
ALERT_CRITERION_BREAKER = "orch_criterion_breaker_tripped"
ALERT_COST_NEAR_CEILING = "orch_cost_near_ceiling"
ALERT_CACHE_COLLAPSE = "orch_cache_hit_rate_collapse"
ALERT_RUN_PAUSED = "orch_run_paused"

RUN_ALERT_NAMES: tuple[str, ...] = (
    ALERT_ESCALATION_RATE,
    ALERT_CRITERION_BREAKER,
    ALERT_COST_NEAR_CEILING,
    ALERT_CACHE_COLLAPSE,
    ALERT_RUN_PAUSED,
)


@dataclass(frozen=True)
class RunAlert:
    """One fired alert (`FR-ORCH-32`): its stable `name`, and the `detail` that tells the
    operator which figure fired it.

    `detail` is deliberately not part of equality-by-name usage — `OBS-05`'s oracle is
    about WHICH condition fired, and a test comparing whole objects would break whenever
    a message improved. `str(alert)` is the name, so a fired tuple reads as its names.
    """

    name: str
    detail: str = ""

    def __str__(self) -> str:
        return self.name


def _alert_knobs() -> dict[str, float]:
    """The alert thresholds, read at CALL time (seam 3) and refused rather than clamped:
    a `HARNESS_ORCH_COST_WARNING_FRACTION` of 1.5 would mean "warn only after the ceiling
    is passed", which is not a warning, and a clamp would silently make it 1.0."""
    return {
        "cost_warning_fraction": _env_float(
            COST_WARNING_FRACTION_ENV, COST_WARNING_FRACTION_DEFAULT,
            low=0.0, high=1.0,
        ),
        "cache_sigma": _env_float(
            CACHE_COLLAPSE_SIGMA_ENV, CACHE_COLLAPSE_SIGMA_DEFAULT,
            low=0.0, high=100.0,
        ),
        "cache_floor": _env_float(
            CACHE_COLLAPSE_FLOOR_ENV, CACHE_COLLAPSE_FLOOR_DEFAULT,
            low=0.0, high=1.0,
        ),
        "cache_min_history": float(
            _env_int(CACHE_COLLAPSE_MIN_HISTORY_ENV, CACHE_COLLAPSE_MIN_HISTORY_DEFAULT)
        ),
    }


def _as_float(value: Any, default: float = 0.0) -> float:
    """One figure from a row or mapping, with a declared default. A metric that is absent
    is not a metric that is zero everywhere — but for these five rules the absent reading
    is the quiet one (no spend recorded is no spend alert), which is the safe direction."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mapping_get(row: Any, key: str, default: Any = None) -> Any:
    """One field from whichever row shape the caller holds — `sqlite3.Row`, a mapping, or
    a dataclass-ish object."""
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        value = getattr(row, key, None)
    return default if value is None else value


def paused_milliseconds(control_rows: Any, *, now: str) -> float:
    """How long the run spent paused, from its APPLIED control rows (`FR-ORCH-33`).

    Pairs each `pause` with the next `resume` after it. Two cases decide the shape:

    * **An open pause** — paused and never resumed — is closed at `now`. AC4's second
      pause has no resume, and dropping it would count the time since as working time,
      which is the opposite of what the operator sees.
    * **A repeated pause** with no intervening resume does not restart the interval: the
      run was already stopped, and counting the overlap twice would subtract more than
      the elapsed time and drive the clock negative.
    """
    total = 0.0
    open_since: str | None = None
    for row in (control_rows or ()):
        action = str(_mapping_get(row, "action", "") or "").lower()
        applied_at = _mapping_get(row, "applied_at")
        if not applied_at:
            continue
        if action == "pause":
            if open_since is None:
                open_since = str(applied_at)
        elif action == "resume" and open_since is not None:
            total += max(_millis_between(open_since, str(applied_at)), 0.0)
            open_since = None
    if open_since is not None:
        total += max(_millis_between(open_since, now), 0.0)
    return total


def _provider_config(run_row: Any) -> dict[str, Any]:
    """The run's FROZEN backend snapshot as a mapping, or empty when there is none.

    `run.provider_config` is the run as it was STARTED — the ceiling, the currency, the
    retention setting. Reading current configuration instead would relabel a finished
    run's figures every time an operator polled it."""
    raw = _mapping_get(run_row, "provider_config")
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_utc(timestamp: Any) -> Any:
    """One ledger timestamp as an aware datetime, or `None` when there is no honest one —
    `_elapsed_seconds_since`'s reading, factored out so the two agree about what a naive
    stamp means (UTC) and about an unparseable one (no reading, never a guess)."""
    if not timestamp:
        return None
    try:
        moment = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _millis_between(start: Any, end: Any) -> float:
    """Milliseconds between two stored timestamps, or 0.0 when either is unreadable —
    an unparseable stamp must not make the clock negative."""
    began, ended = _as_utc(start), _as_utc(end)
    if began is None or ended is None:
        return 0.0
    return (ended - began).total_seconds() * 1000.0


def evaluate_alerts(
    *,
    run_row: Any = None,
    metrics: Any = None,
    breaker_rows: Any = (),
    budget_state: Any = None,
    cache_history: Any = (),
) -> tuple[RunAlert, ...]:
    """`FR-ORCH-32`: the run's fired alerts, as a pure function of already-read state.

    Pure on purpose. Every input is a value the caller has already gathered, so the rules
    can be exercised one condition at a time without a store, a clock or a model call —
    `TC-ORCH-36`'s isolation rung — and so the operator surface and a test see the same
    function rather than two spellings of the same thresholds.

    `OBS-05`'s oracle is that each condition fires its OWN alert and not another's, so the
    five rules below are independent by construction: no rule reads another's input, and
    none of them short-circuits the rest.
    """
    knobs = _alert_knobs()
    fired: list[RunAlert] = []

    rate = _as_float(_mapping_get(metrics, "escalation_rate"), -1.0)
    if rate < 0:
        rate = _as_float(_mapping_get(budget_state, "escalation_rate"), -1.0)
    budget = _env_float(
        ESCALATION_BUDGET_ENV, ORCH_ESCALATION_BUDGET, low=0.0, high=1.0
    )
    if rate > budget:
        # ABOVE the budget, never at it: the budget is the allowance, and a run that
        # spends exactly its allowance has not overrun it. The budget is the same
        # call-time knob the admission sites read — an alert that fires at 0.30 while
        # the dispatcher admits to 1.0 is noise on a compliant run, and one that stays
        # silent to 0.30 while the dispatcher refuses at 0.10 hides a real overrun.
        fired.append(RunAlert(
            ALERT_ESCALATION_RATE,
            f"escalation rate {rate:.4f} is above the {budget} budget",
        ))

    tripped = [row for row in (breaker_rows or ()) if row is not None]
    if tripped:
        names = ", ".join(
            str(_mapping_get(row, "criterion_id", "")) for row in tripped
        )
        fired.append(RunAlert(
            ALERT_CRITERION_BREAKER,
            f"criterion breaker tripped: {names}" if names else "criterion breaker tripped",
        ))

    ceiling = _as_float(_mapping_get(budget_state, "ceiling"))
    if not ceiling:
        # The run's FROZEN declared ceiling, never `cost_estimate`: the estimate is what
        # the run is expected to cost, the ceiling is what it may not exceed, and reading
        # one as the other makes this alert fire on a different quantity's data.
        ceiling = _as_float(_provider_config(run_row).get("cost_ceiling"))
    spend = _as_float(_mapping_get(budget_state, "spend"))
    if not spend:
        spend = _as_float(_mapping_get(run_row, "cost_spend"))
    if ceiling > 0 and spend >= knobs["cost_warning_fraction"] * ceiling:
        fired.append(RunAlert(
            ALERT_COST_NEAR_CEILING,
            f"spend {spend} is at or past "
            f"{knobs['cost_warning_fraction']:.2f} of the {ceiling} ceiling",
        ))

    history = [
        _as_float(value, -1.0) for value in (cache_history or ())
    ]
    history = [value for value in history if value >= 0]
    current = _as_float(_mapping_get(metrics, "cache_hit_rate"), -1.0)
    if current >= 0 and len(history) >= int(knobs["cache_min_history"]):
        mean = sum(history) / len(history)
        variance = sum((value - mean) ** 2 for value in history) / len(history)
        deviation = variance ** 0.5
        breach = mean - knobs["cache_sigma"] * deviation
        # BOTH guards: statistically unusual against the baseline history, AND absolutely
        # low. A steady history has no deviation, which would otherwise make any dip at
        # all a three-sigma event.
        if current < breach and current < knobs["cache_floor"]:
            fired.append(RunAlert(
                ALERT_CACHE_COLLAPSE,
                f"cache hit rate {current:.3f} is below both the history's "
                f"{knobs['cache_sigma']}-sigma break ({breach:.3f}) and the "
                f"{knobs['cache_floor']} floor",
            ))

    # `status` is the run row's own lifecycle column and the authority on whether the run
    # is paused (`CHECK (status IN ('pending','running','paused','complete','failed'))`).
    # `pause_reason` is kept as a second signal, not the primary one: it says WHY, and a
    # pause recorded without a reason is still a pause.
    status_text = str(_mapping_get(run_row, "status", "") or "").lower()
    pause_reason = _mapping_get(run_row, "pause_reason")
    paused_flag = _mapping_get(budget_state, "paused")
    if status_text == "paused" or pause_reason or bool(paused_flag):
        reason = str(pause_reason or "") or "no reason recorded"
        fired.append(RunAlert(ALERT_RUN_PAUSED, f"run is paused: {reason}"))

    return tuple(fired)
ESCALATION_BUDGET_ENV = "HARNESS_ORCH_ESCALATION_BUDGET"

#: The criterion circuit breaker's rate (`FR-ORCH-13`, design §3.7 Configuration:
#: `ORCH_CRITERION_BREAKER_RATE`, 0.50): a criterion escalating for **more than** this
#: share of the first `ORCH_CRITERION_BREAKER_MIN_N` submissions processed trips the
#: breaker — escalation halts for it, it is marked un-gradeable by panel, and the
#: remainder scores single-judge provisional. Production default;
#: `HARNESS_ORCH_CRITERION_BREAKER_RATE` adjusts it at **call** time.
ORCH_CRITERION_BREAKER_RATE = 0.50
CRITERION_BREAKER_RATE_ENV = "HARNESS_ORCH_CRITERION_BREAKER_RATE"

#: The criterion breaker's window (`FR-ORCH-13`, design §3.7 Configuration:
#: `ORCH_CRITERION_BREAKER_MIN_N`, 20 — the HLD's "first 20–30" band's floor, the stated
#: Assumption): the breaker evaluates only once at least this many submissions have been
#: processed for the criterion. Production default;
#: `HARNESS_ORCH_CRITERION_BREAKER_MIN_N` adjusts it at **call** time.
ORCH_CRITERION_BREAKER_MIN_N = 20
CRITERION_BREAKER_MIN_N_ENV = "HARNESS_ORCH_CRITERION_BREAKER_MIN_N"

#: The extract/deterministic rows one dispatch pass completes directly (`#62`): their
#: handling is the ledger transition — the extraction payload is `M-EXTRACT`'s — and
#: scoring gates on the transition, so the pass completes them to unlock the judged
#: batch. Bounded, not open-ended: a 40,000-unit walk in one pass is exactly the
#: unbounded dispatch the concurrency story exists to prevent. Production default;
#: `HARNESS_ORCH_DISPATCH_WALK_BATCH` adjusts it for a slower test box at call time.
DISPATCH_WALK_BATCH_ENV = "HARNESS_ORCH_DISPATCH_WALK_BATCH"
DISPATCH_WALK_BATCH_DEFAULT = 4096

#: The divisor the backpressure clamp applies to the governor's cap while M-STORE's
#: `backpressure_active` level is ON (`FR-ORCH-21`, `CT-STORE-06`): the pass runs at
#: `max(cap // divisor, 1)`. The clamp is sensed per pass and never persists — a
#: reduction that never recovers is one slow store throttling a run forever. Production
#: default 4; `HARNESS_ORCH_BACKPRESSURE_DIVISOR` adjusts it at call time.
BACKPRESSURE_DIVISOR_ENV = "HARNESS_ORCH_BACKPRESSURE_DIVISOR"
BACKPRESSURE_DIVISOR_DEFAULT = 4

#: The divisor the governor applies to the cap after a pass in which any model call came
#: back rate-limited or OOM (`FR-ORCH-21`'s reduce; §9.13's back-off). Floor 1 — the
#: dispatch never stops on the signal alone, it narrows. Production default 2 (halve);
#: `HARNESS_ORCH_CONCURRENCY_REDUCTION` adjusts it at call time.
CONCURRENCY_REDUCTION_ENV = "HARNESS_ORCH_CONCURRENCY_REDUCTION"
CONCURRENCY_REDUCTION_DEFAULT = 2

#: The cumulative OOM count a judge reaches before the governor drops it from the
#: panel (§9.11's "drop to a smaller panel", RES-13): the reduced panel is written to
#: the run row's `panel_config` as a strict subset, never below one judge. Production
#: default 2; `HARNESS_ORCH_OOM_DROP_THRESHOLD` adjusts it at call time.
OOM_DROP_THRESHOLD_ENV = "HARNESS_ORCH_OOM_DROP_THRESHOLD"
OOM_DROP_THRESHOLD_DEFAULT = 2

#: The `backend_profile` value that carries model residency (`FR-ORCH-19`): weights
#: loaded one model at a time, so the dispatcher keeps one judge resident per run. A
#: hosted backend holds no weights and batches across judges freely.
BACKEND_EDGE_LOCAL = "edge-local"

#: The worker identity the dispatch loop leases under (`#62`): the dispatch pass is a
#: lease holder like any worker — at-least-once, sweepable — so its in-flight batch is
#: visible on the ledger as exactly what it is, and an interrupted pass's leases are
#: the sweeper's ordinary reclaim, never a special case.
DISPATCH_OWNER = "orchestrator-dispatch"


def _env_int(name: str, default: int) -> int:
    """One integer environment knob, read at call time (`store._int_env`'s shape).

    Invalid and negative values refuse rather than fall back to the default: a typo in an
    operator's override silently taking the production value is the phantom-bug shape the
    seam exists to prevent.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise WorkLedgerError(f"{name}={raw!r} is not an integer") from exc
    if value <= 0:
        raise WorkLedgerError(f"{name}={value} must be positive")
    return value


def _env_float(name: str, default: float, *, low: float, high: float) -> float:
    """One float environment knob, read at call time — the rate knobs' seam.

    The same refusal posture as `_env_int`: a typo'd override silently taking the
    production value is the phantom-bug shape the seam exists to prevent, so an
    unparseable value raises. Rates are bounded — a share outside ``[low, high]`` is
    not a stricter policy, it is a misconfiguration, and it refuses rather than clamps
    (a clamped 7% becomes a silent 100% escalation rate; the clamp would BE the bug).
    Zero is a legal low bound: the random arm may honestly be disabled by rate 0.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise WorkLedgerError(f"{name}={raw!r} is not a number") from exc
    if not low <= value <= high:
        raise WorkLedgerError(
            f"{name}={value} is outside its allowed range [{low}, {high}]"
        )
    return value


def _now() -> str:
    """The one wall-clock read the ledger writes, UTC ISO-8601 (`ingest._now`'s form)."""
    return datetime.now(timezone.utc).isoformat()


def _elapsed_seconds_since(timestamp: str | None) -> float:
    """Wall seconds since a ledger timestamp, or 0.0 when there is no honest one.

    The report-only path's elapsed anchor (`#62`): a poll with no dispatch state has
    no monotonic start of its own, so the run's own `started_at` is the throughput
    window the estimate extrapolates from. A missing or unparseable timestamp is no
    observed window — 0.0, never an infinity extrapolated from nothing (the same
    posture `estimated_completion_seconds` takes).
    """
    if not timestamp:
        return 0.0
    try:
        started = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return 0.0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - started).total_seconds(), 0.0)


def _known_key(value: Any) -> tuple[int, Any]:
    """A sort key that sends an absent value last, without ever comparing it.

    Present values key ``(0, value)``; absent ones ``(1, None)`` — the first element
    decides before the second is ever compared, so `None` is never ordered against a real
    value and two absentees tie into the next key. The dispatch order uses it for a
    candidate whose criterion the version's maps do not name (a shape the immutable
    package cannot produce): the order stays total and deterministic either way.
    """
    return (0, value) if value is not None else (1, None)


def _dependency_closure(
    graph: Mapping[str, Sequence[str]],
) -> dict[str, frozenset[str]]:
    """The transitive closure of a dependency graph, per criterion.

    Input: criterion -> its direct dependencies (`PackageCatalog.dependency_graph`'s
    shape). Output: criterion -> every criterion it depends on, itself excluded (the
    graph cannot carry a self-edge — `FR-PKG-05` refuses one).

    **Kahn's sweep, honestly iterative**: an indegree pass, then a worklist drained
    from the sources inward — every criterion is closed only after all of its
    dependencies are, so the recursion depth is zero and a deep chain (a criterion per
    link, a thousand long) costs heap records, not call-stack frames. A criterion a
    dependency names but the graph does not (a dangling id, which `M-PKG`'s loader
    refuses but this helper does not trust) contributes itself and closes over
    nothing. The graph is a DAG (`FR-PKG-05` refuses cycles); a violated assumption
    leaves the cycle's members at their reserved empty closure — a bounded incomplete
    answer, not a crash or a hang — and the closure sets themselves are order-
    independent `frozenset`s, so the sweep's emission order cannot leak into results.
    """
    closure: dict[str, frozenset[str]] = {cid: frozenset() for cid in graph}
    indegree = {cid: 0 for cid in graph}
    dependents: dict[str, list[str]] = {cid: [] for cid in graph}
    for cid, deps in graph.items():
        for dep in deps:
            if dep in indegree:  # a dangling dep is not a graph edge to wait on
                indegree[cid] += 1
                dependents[dep].append(cid)
    ready = [cid for cid in graph if indegree[cid] == 0]
    while ready:
        cid = ready.pop()
        closure[cid] = frozenset().union(
            *(  # type: ignore[arg-type]
                {dep} | closure.get(dep, frozenset())
                for dep in graph.get(cid, ())
            )
        )
        for dependent in dependents[cid]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
    return closure


# --- the escalation policy, as pure functions (NFR-ORCH-04) -------------------------------------
#
# The *decision to escalate* is `M-AGG`'s (`FR-AGG-08`, `CT-AGG-08` — this module must not
# import that policy, and imports nothing from it). What IS this module's is the plan the
# decision becomes and the gates the plan passes through: the odd-panel ladder, the
# random-arm draw, the breaker arithmetic. All three are pure functions of observable
# signals and configuration — no model call, no store, no clock — which is what
# `TC-ORCH-32`'s purity assertion evaluates.


#: The namespace of derived escalation judges. A run's panel carries the ladder's first
#: arms (`panel_config_json`); when a widening outruns it — a `holistic` criterion's base
#: panel is already the whole panel — the ladder continues on derived judge identities
#: named by ladder position. The ledger does not resolve builds (`M-CONF`/`M-JUDGE` do,
#: downstream), and a deployment that owns real fifth judges passes them explicitly
#: (`enqueue_escalation`'s `judges`), which is the design's own `judges` parameter.
ESCALATION_ARM_PREFIX = "escalation-arm"


def _extension_arms(
    panel_arms: Sequence[str], prior_judges: Sequence[str], count: int = 2
) -> tuple[str, ...]:
    """The judges a widening adds when the caller names none, in ladder order.

    The run panel's arms the pair does not already carry come first — panel order is the
    escalation ladder's first arms (`panel_config_json`) — and past them the ladder
    continues on derived identities: ``escalation-arm-<k>`` numbered from the panel's end.
    A derived name a prior rung already put on the panel is skipped, so rung over rung
    (1 → 3 → 5 → …) never re-adds a judge. Deterministic: the same panel and prior produce
    the same additions, which is what makes a retried enqueue content-address the same units.
    """
    additions: list[str] = [arm for arm in panel_arms if arm not in prior_judges]
    position = len(tuple(panel_arms))
    while len(additions) < count:
        position += 1
        name = f"{ESCALATION_ARM_PREFIX}-{position}"
        if name not in prior_judges:
            additions.append(name)
    return tuple(additions[:count])


def _judge_id_of(judge: Any) -> str:
    """The judge's ledger identity, from whatever the caller named it with: a string
    is the build id itself; anything else must be a model ref carrying one
    (`FR-CONF-03` — a judge is a build identity, never a friendly name) — the same
    string `panel_config_json` records and a unit's `judge_id` hash input carries, so
    an escalated panel's additions are the same ids the seated panel's arms read as.
    """
    if isinstance(judge, str):
        return judge
    build_id = getattr(judge, "build_id", None)
    if isinstance(build_id, str) and build_id:
        return build_id
    raise EscalationPlanError(
        f"an escalation's judges are named by build id — a string, or a model ref "
        f"carrying one; got {judge!r}, which names no build identity (FR-CONF-03)."
    )


def escalation_plan(
    prior_judges: Sequence[str],
    *,
    add_judges: Sequence[str] | None = None,
    panel_arms: Sequence[str] = (),
) -> tuple[str, ...]:
    """Build one escalation rung: the widened panel, or the named refusal (`FR-ORCH-10`).

    Pure — `TC-ORCH-20` and `TC-ORCH-32` evaluate it with no store and no model. The
    result is the FULL widened panel in order: the criterion's prior judges followed by
    the additions, so the plan's ``judge_count`` is ``len(result)`` and the odd-panel rule
    reads directly off the return value.

    **The rules, each from the design's own sentence:**

    - The criterion escalates **from one judge to three, never to two** — the canonical
      rung widens by two. With no caller-named judges the plan widens by exactly two,
      taken from the run panel's unused arms first, then derived extension arms
      (`_extension_arms`). An odd panel widened by an even addition stays odd, so the
      default ladder never leaves the odd numbers: 1 → 3 → 5 → …
    - **A plan producing an even ``judge_count`` is rejected** — `EvenEscalationPlanError`,
      the exact exception `TC-ORCH-20` asserts for counts 2 and 4. A two-way tie broken by
      rule is a coin flip presented as a judgement; the ledger's CHECK (`CT-AGG-03`) is
      the backstop, this refusal is the front.
    - A plan that does not widen (equal or smaller than the panel it starts from) is
      refused with `EscalationPlanError`: an escalation that adds nothing looks like work
      while being the silent no-op shape.
    - A criterion with **no judges yet** (prior count 0) has no band to widen — refusing
      rather than treating first enumeration as escalation keeps "escalate" meaning
      *widen a panel that exists*.
    - A caller-named judge already on the panel is refused (`EscalationPlanError`), and so
      is a plan naming the **same judge twice among the additions** (`EscalationPlanError`):
      one judge, one seat — a doubled seat would let one verdict outweigh another, and a
      doubled seat can also hide an even distinct-judge panel behind an odd `len`.

    An even PRIOR panel is refused with `EvenEscalationPlanError` as well: the ledger
    should never hold one (the CHECK refuses the write), and a plan built on top of a
    corrupted panel would launder it rather than surface it.
    """
    prior = tuple(prior_judges)
    if len(prior) == 0:
        raise EscalationPlanError(
            "no judges to escalate from: a criterion with judge_count 0 has no panel "
            "to widen. Enumeration gives every judged criterion its base panel; an "
            "escalation before that is a caller error."
        )
    if len(prior) % 2 == 0:
        raise EvenEscalationPlanError(
            f"the criterion's current panel {prior!r} carries an even judge_count "
            f"({len(prior)}); an even panel is the state the odd-panel rule exists to "
            "prevent (CT-AGG-03) and no escalation plan may be built on top of it — "
            "the panel is corrupt, and widening it would launder the corruption."
        )
    additions = (
        _extension_arms(panel_arms, prior)
        if add_judges is None
        else tuple(add_judges)
    )
    if not additions:
        raise EscalationPlanError(
            "the escalation plan adds no judges: a plan that does not widen the panel "
            "is not an escalation (FR-ORCH-10), and enqueuing it would look like work "
            "while adding nothing."
        )
    if len(set(additions)) != len(additions):
        raise EscalationPlanError(
            f"the escalation plan names the same judge more than once among its "
            f"additions: {additions!r}. One judge, one seat — a doubled seat would let "
            "one verdict outweigh another in the widened panel's aggregation, and an "
            "odd length built on a repeated name hides an even panel of distinct "
            "judges behind it."
        )
    overlap = [judge for judge in additions if judge in prior]
    if overlap:
        raise EscalationPlanError(
            f"the escalation plan re-adds judge(s) already on the panel: {overlap!r}. "
            "One judge, one seat — a doubled seat would let one verdict outweigh "
            "another in the widened panel's aggregation."
        )
    total = len(prior) + len(additions)
    if total % 2 == 0:
        raise EvenEscalationPlanError(
            f"the escalation plan produces an even judge_count ({total}: {len(prior)} "
            f"prior + {len(additions)} added). Escalation goes one judge to three, "
            "never to two (FR-ORCH-10, R48) — an even panel is a tie broken by rule, "
            "which is a coin flip presented as a judgement."
        )
    if total <= len(prior):
        raise EscalationPlanError(
            f"the escalation plan produces a judge_count of {total}, not wider than "
            f"the panel it starts from ({len(prior)})."
        )
    return prior + additions


def _random_arm_key_bytes(key: Any) -> bytes:
    """The draw's canonical bytes for one candidate key: a string is itself; anything
    else (the (submission_id, criterion_id) tuple the enumeration path passes) is its
    parts, ``\\x1f``-joined. Deterministic and collision-free for the key shapes the
    module uses, and total over the opaque strings the statistical cases draw with."""
    if isinstance(key, str):
        return key.encode("utf-8")
    if isinstance(key, (tuple, list)):
        return b"\x1f".join(str(part).encode("utf-8") for part in key)
    return repr(key).encode("utf-8")


def random_arm_selection(key: Any, seed: int, rate: float | None = None) -> bool:
    """Whether one candidate draws into the random arm (`FR-ORCH-11`, `TC-ORCH-12`).

    Pure and **seeded**: the draw is sha256 over the candidate's key and the caller's
    seed read as a uniform integer against the rate, so the same (key, seed) draws the
    same way on every enumeration — `CT-ORCH-02`'s byte-identical enumeration and
    `NFR-ORCH-05`'s determinism survive the arm being in the pass — while across keys
    the draws are uniform, which is what makes the arm's share converge on the rate
    (the 10,000-draw sweep of `TC-ORCH-12`). ``rate`` defaults to the module constant
    `ORCH_RANDOM_ARM_RATE` — the pure function never reads the environment; the
    production path reads the knob at call time and passes the rate explicitly (the
    env seam, `§4.6`). No confidence input, no store, no clock: the arm is independent
    of confidence **by construction** (`R22` — that independence is the point of the
    arm, `FR-STATS-08`), and a rate of 0 disables it honestly.
    """
    if rate is None:
        rate = ORCH_RANDOM_ARM_RATE
    if rate <= 0:
        return False
    digest = hashlib.sha256(
        b"aeh.orch\x1frandom_arm\x1f"
        + _random_arm_key_bytes(key)
        + b"\x1f"
        + str(int(seed)).encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64) < rate


def run_random_arm_seed(run_id: str) -> int:
    """The run's seeded draw for the random arm, derived from the run id.

    A run's arm membership must be a property of the RUN (the same cohort re-enumerated
    into a new run re-draws — new run, new sample), and it must be deterministic within
    the run (`CT-ORCH-02`). The run id is the seed's whole input: sha256 under the
    module prefix, read as an integer in the statistical cases' own draw range
    (``rng.randrange(2**31)``).
    """
    digest = hashlib.sha256(b"aeh.orch\x1frun_arm_seed\x1f" + run_id.encode("utf-8"))
    return int.from_bytes(digest.digest()[:8], "big") % (2**31)


def criterion_breaker_tripped(
    escalated: int,
    processed: int,
    *,
    rate: float | None = None,
    min_n: int | None = None,
) -> bool:
    """Whether the criterion escalation breaker trips (`FR-ORCH-13`, `TC-ORCH-13`).

    Pure, the design's own sentence twice over: the breaker evaluates only **at or
    after the window minimum** (`processed >= min_n` — a criterion that escalates 11 of
    its first 10 processed has not met the window yet, and the minimum gates before the
    rate does), and it trips when the criterion escalated for **more than** ``rate`` of
    what it has processed — half of twenty is ten, and ten of twenty does not trip;
    eleven does. Defaults are the module constants; the production path reads the env
    knobs at call time and passes them explicitly (the env seam, `§4.6`).

    The caller chooses what window `escalated`/`processed` count over — the enqueue
    path feeds the criterion's first `min_n` submissions by completion tick, so the
    comparison is "more than half of the first twenty", exactly the design's window.
    """
    if rate is None:
        rate = ORCH_CRITERION_BREAKER_RATE
    if min_n is None:
        min_n = ORCH_CRITERION_BREAKER_MIN_N
    if processed < min_n:
        return False
    return escalated / processed > rate


def validate_escalation_plan(judge_count: int) -> int:
    """Normalize one escalation's target panel depth (`FR-ORCH-10`, `TC-ORCH-20`).

    The declared pure surface of the odd-panel rule: an odd depth is legal and stands
    (3 judges stay 3, 5 stay 5), a **one-judge criterion escalates to three — never to
    two**, and any even count raises `EvenEscalationPlanError` (a two-way tie broken by
    rule is a coin flip presented as a judgement, R48). `escalation_plan` composes this
    rule with the widening arithmetic; this function is the rule alone.
    """
    if judge_count % 2 == 0:
        raise EvenEscalationPlanError(
            f"an escalation plan for judge_count {judge_count} produces an even "
            "panel — an even panel is a tie broken by rule, a coin flip presented "
            "as a judgement (FR-ORCH-10, R48). One judge escalates to three, never "
            "to two."
        )
    return 3 if judge_count == 1 else judge_count


class AdmissionPlan(NamedTuple):
    """One batch's escalation admission decision (`FR-ORCH-14`, `TC-ORCH-14`).

    `admitted` and `provisional` are tuples of the candidates' keys; the provisional
    half is ordered by expected value, highest first — the order admission resumes in
    when the rate allows — so the remainder is **marked, not dropped**: scrutiny is
    degraded visibly, never silently reduced (R26, `CT-ORCH-16`).
    """

    admitted: tuple
    provisional: tuple


def admit_escalations(
    candidates: Sequence[tuple[Any, float]],
    *,
    escalated: int,
    processed: int,
    budget: float | None = None,
) -> AdmissionPlan:
    """One batch's admission against the run-wide escalation budget (`FR-ORCH-14`).

    Pure: the caller reads the ledger's observed counts (the escalations and the
    processed results it names) and hands the batch's ``(key, expected_value)``
    candidates; this says which are admitted and which are marked provisional. The
    declared reading, strict like the breaker's "more than half": the budget is
    exceeded when ``escalated / processed`` is **strictly above** it — at-budget
    behaves like below-budget (rationing must not start early; that is the "silently
    reducing scrutiny" failure R26 names) — and above it **nothing further is
    admitted**: every further escalation past a rate already above the budget deepens
    the overrun FR-ORCH-14 forbids. The deferred remainder is the full pending set in
    expected-value order, so admission resumes with the highest-value criteria when
    the rate allows. Full accounting is the invariant: no candidate is dropped, none
    duplicated, none appears on both sides. A window with nothing processed yet has no
    observed rate to exceed — the batch is admitted.
    """
    if budget is None:
        budget = ORCH_ESCALATION_BUDGET
    ordered = tuple(
        key
        for key, _ in sorted(
            candidates,
            key=lambda pair: (-float(pair[1]), str(pair[0])),
        )
    )
    if processed > 0 and escalated / processed > budget:
        return AdmissionPlan((), ordered)
    return AdmissionPlan(ordered, ())


# --- the worker-facing report types -------------------------------------------------------------


@dataclass(frozen=True)
class WorkError:
    """What a worker reports when a unit fails (`FR-ORCH-18`'s input).

    One field, deliberately: the ledger retains the **message** — `last_error` is what
    the operator surface reads when it asks what happened to a quarantined unit, and a
    message is the only part of a failure that stays true after the process that hit it
    is gone. A worker may also pass a bare string; the orchestrator stores what it is
    given rather than wrapping it in this type's repr.
    """

    message: str


@dataclass(frozen=True)
class WorkResult:
    """What a worker reports when a unit completes (the design's `WorkResult`).

    Deliberately minimal in this slice: the **payload** each stage persists is that
    stage's to own (extraction spans, verdicts — #68 and onward land beside `M-EXTRACT`
    and `M-JUDGE`), and Tier C holds none of it by design. The ledger's `complete` half
    records the transition — `done` is the state resume skips (`FR-ORCH-02`) — and the
    stages that own payloads write them through their own surfaces.
    """

    summary: str = ""


# --- the enumeration report ---------------------------------------------------------------------


@dataclass(frozen=True)
class EnumerationReport:
    """What one enumeration pass did (`CLAUDE.md` seam 4).

    The `gates` dict is deliberately per-gate rather than one boolean — the
    `IngestReport.gates` precedent (`CT-INGEST-08`): a bare `status=enumerated` on top of
    an empty report is the top silent-failure trap, so each stage of the pass says what it
    saw. `work_ids` is the sorted set the pass computed, which is what NFR-ORCH-05's
    byte-identical comparison is over (a set-of-bytes comparison, never a count).

    `status` is `"enumerated"` when the pass inserted at least one new ledger row and
    `"no-op"` when every unit the pass computed was already present — the shape a
    completed run's re-run must have (FR-ORCH-03). Either way the report is complete:
    a no-op still names its counts, its gates and its `work_ids`.
    """

    run_id: str
    status: str
    work_ids: tuple[str, ...]
    units_enumerated: int
    units_inserted: int
    units_already_present: int
    by_stage: Mapping[str, int] = field(default_factory=dict)
    by_status: Mapping[str, int] = field(default_factory=dict)
    gates: dict[str, str] = field(default_factory=dict)


# --- the sweeper's report ------------------------------------------------------------------------


@dataclass(frozen=True)
class SweepPlan:
    """The two sweeps' ordering data for one package version, derived once (`FR-ORCH-05/07`).

    Everything the dispatch order needs, read off the immutable package and cached:
    `extract_positions` is the criterion's position in `M-PKG`'s topological order
    (`FR-PKG-05` — dependencies before dependents, Kahn's with sorted emission, so the
    order is reproducible); `question_of` maps a criterion to its question, `FR-ORCH-07`'s
    second key; `dependency_closure` maps a criterion to the transitive set of criteria it
    depends on — the extraction units whose completion gates its scoring (`FR-ORCH-06`).

    The closure is computed here, not in `M-PKG`: the topology is `M-PKG`'s data (this
    module consumes it rather than re-deriving the graph), and what the *gate* needs —
    transitive closure over that topology — is scheduling policy, this module's own.
    """

    extract_positions: Mapping[str, int]
    question_of: Mapping[str, str]
    dependency_closure: Mapping[str, frozenset[str]]


@dataclass(frozen=True)
class SweeperReport:
    """What one lease-expiry sweep did (`CLAUDE.md` seam 4).

    A bare count would be the silent-failure shape — a sweep that examined nothing and
    requeued nothing is indistinguishable from one that never ran — so the report names
    all three outcomes: `examined`, `requeued`, `still_held`, plus the `gates` detail
    (the `EnumerationReport`/`IngestReport.gates` precedent).

    `still_held` is derived (`examined - requeued`), and a unit that completes or
    moves during the sweep counts as still held: the report is a reading taken at
    sweep time, the ledger row is the truth. Report-level approximation, stated
    rather than hidden.
    """

    examined: int
    requeued: int
    still_held: int
    gates: dict[str, str] = field(default_factory=dict)


# --- the progress report and the dispatch loop's report surface (#62) ----------------------------


#: The operator extras `ProgressReport` serves beside the designed field set. They are
#: deliberately NOT dataclass fields — the field set is §3.7's, asserted by set equality
#: (TC-ORCH-26), and these ride outside it through the mapping protocol.
PROGRESS_EXTRA_FIELDS = ("complete", "concurrency", "by_unit", "alerts")

#: The per-student figure FR-ORCH-23 forbids, named once so the prohibition is
#: checkable: neither the type's fields nor the mapping's keys may carry it.
_PROGRESS_FORBIDDEN_TOKENS = ("student", "submission", "learner")


def estimated_completion_seconds(
    *,
    completed: int,
    remaining: int,
    elapsed_seconds: float,
    escalation_rate_so_far: float,
) -> float:
    """The run's estimated completion, from observed throughput adjusted for the
    escalation rate observed so far (`FR-ORCH-24`, pure — `NFR-ORCH-04`).

    The naive figure is `remaining / observed_throughput`, with the throughput the
    run has actually sustained (`completed` units over `elapsed_seconds`) — not the
    plan's optimism. Each escalation widens a pair's panel from one judge to three
    (`FR-ORCH-10`: one to three, never to two), so a widened unit becomes three: the
    observed rate grows the remaining work by `(1 + 2 * rate)` — one added unit per
    pair plus the pair's own re-judgment. At a 0% rate the adjustment is a no-op and
    the estimate IS the naive one; at 15% of 200 remaining it adds 60s; the growth
    the escalations commit the run to is exactly what a naive estimate hides
    (TC-ORCH-27).

    No completed work or no elapsed time is no observed throughput — 0.0, not an
    infinity extrapolated from nothing.
    """
    if completed <= 0 or elapsed_seconds <= 0:
        return 0.0
    naive = remaining * elapsed_seconds / completed
    return naive * (1.0 + 2.0 * escalation_rate_so_far)


@dataclass(frozen=True)
class ProgressReport:
    """The run-state report `progress(run_id)` returns (design §3.7, `FR-ORCH-23`).

    The field set is the design's, exactly and deliberately: the position fields
    (which stage, which criterion, which judge the open work sits at), the four
    status totals, the observed escalation rate and the adjusted estimate. It
    carries **no per-student figure** — `FR-ORCH-23`'s prohibition, paired with
    `R63`: the console renders what the type holds, so the data must not exist to
    render (`FR-CONSOLE-08`).

    **The mapping behavior is deliberate** (recorded interpretation): the report is
    the §3.7 dataclass AND the query surface the console reads — field access
    (`report.complete`) and mapping access (`report["done"]`, `report.keys()`) are
    both first-class, with the three operator extras (the completion predicate, the
    dispatch's current concurrency, the per-unit counts) riding OUTSIDE the field
    set. `dataclasses.fields(ProgressReport)` stays exactly the designed eleven;
    an added per-student field would fail that set equality, and the mapping's
    keys are checked by the same prohibition.
    """

    stage: str
    criterion_index: int
    criterion_total: int
    judge_index: int
    judge_total: int
    done: int
    in_flight: int
    pending: int
    quarantined: int
    escalation_rate_so_far: float
    estimated_completion: float

    def __post_init__(self) -> None:
        # The extras ride outside the field set: attached per instance, not declared,
        # so the field enumeration the prohibition is asserted over stays the
        # design's. A report built without dispatch state reports what the ledger
        # says: not complete, no measured concurrency yet.
        object.__setattr__(
            self,
            "_extras",
            {
                "complete": self.pending == 0 and self.in_flight == 0,
                "concurrency": 0,
                "by_unit": {},
                # `FR-ORCH-32`: an extra, not a field. The designed field set is exactly
                # eleven and `FR-ORCH-23`'s per-student prohibition is asserted over that
                # enumeration, so alerts ride beside the other operator extras. A report
                # built without run state has no alerts — not "no problems", simply
                # nothing evaluated; `progress()` attaches the evaluated tuple.
                "alerts": (),
            },
        )
        for key in (*PROGRESS_EXTRA_FIELDS, *(f.name for f in dataclass_fields(self))):
            text = str(key).lower()
            offending = [t for t in _PROGRESS_FORBIDDEN_TOKENS if t in text]
            if offending:
                raise ValueError(
                    f"ProgressReport key {key!r} carries a per-student token "
                    f"({offending[0]!r}) — FR-ORCH-23: no per-student completion "
                    "figure exists on the type, so the console cannot render one (R63)."
                )

    # -- the operator extras, and the mapping protocol over fields + extras ------

    def _map(self) -> dict[str, Any]:
        mapped = {f.name: getattr(self, f.name) for f in dataclass_fields(self)}
        mapped.update(self.__dict__.get("_extras", {}))
        return mapped

    def __getattr__(self, name: str) -> Any:
        # Only reached for names that are not dataclass fields (normal lookup
        # already failed): the extras, and nothing else.
        extras = self.__dict__.get("_extras")
        if extras is not None and name in extras:
            return extras[name]
        raise AttributeError(
            f"{type(self).__name__} has no field or extra named {name!r} — the "
            f"designed fields are {tuple(f.name for f in dataclass_fields(self))} "
            f"and the operator extras are {PROGRESS_EXTRA_FIELDS}."
        )

    def __getitem__(self, key: str) -> Any:
        try:
            return self._map()[key]
        except KeyError:
            raise KeyError(key) from None

    def __contains__(self, key: object) -> bool:
        return key in self._map()

    def __iter__(self) -> Any:
        return iter(self._map())

    def __len__(self) -> int:
        return len(self._map())

    def keys(self) -> Any:
        return self._map().keys()

    def values(self) -> Any:
        return self._map().values()

    def items(self) -> Any:
        return self._map().items()

    def get(self, key: str, default: Any = None) -> Any:
        return self._map().get(key, default)


# --- the escalation reports (CLAUDE.md seam 4) ---------------------------------------------------


#: What `enqueue_escalation` decided. Both outcomes are named, never absorbed: the
#: breaker's halt is the visible degradation `CT-ORCH-16` demands — a caller that
#: receives `halted_by_breaker` knows scrutiny was reduced and why (the mark on the
#: result is M-AGG's to write). The budget does not decide here: the enqueue writes
#: the plan the verdict's transaction needs (`CT-ORCH-08`/`FR-ORCH-09`), and the
#: budget rations DISPATCH — the claim pass defers pending escalation units through
#: `admit_escalations`, the remainder provisional (`FR-ORCH-14`).
DECISION_ADMITTED = "admitted"
DECISION_HALTED_BY_BREAKER = "halted_by_breaker"

#: The content-address space of escalation bookkeeping: request and breaker rows are
#: keyed on a sha256 over what they are ABOUT — never on the wall clock or a uuid — so a
#: retried enqueue or a second trip evaluation addresses the SAME row (`INSERT OR
#: IGNORE` then makes the retry a no-op, `FR-ORCH-03`'s idempotence carried into the
#: escalation path). `kind` namespaces the two id spaces; the module name prefixes the
#: digest so these cannot collide with anything else keyed by bare sha256.
_CONTENT_ID_KIND_REQUEST = "escalation_request"
_CONTENT_ID_KIND_BREAKER = "criterion_breaker"


def _content_id(kind: str, *parts: str) -> str:
    """A content-addressed id for escalation bookkeeping: sha256 over the kind and the
    row's identity parts, `\\x1f`-joined under the module prefix. Pure and total — the
    same facts always address the same row."""
    digest = hashlib.sha256()
    digest.update(b"aeh.orch\x1f")
    digest.update(kind.encode())
    for part in parts:
        digest.update(b"\x1f")
        digest.update(part.encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class EscalationReport:
    """What one escalation enqueue did (`FR-ORCH-09/10/13/14`, seam 4).

    `decision` is the enqueue's outcome — `admitted` (units inserted), `queued` (over
    budget, held in the persisted queue in expected-value order; the caller marks its
    result provisional), or `halted_by_breaker` (the criterion breaker has tripped;
    escalation halts for the criterion). The numbers beside the decision — the rate, the
    budget, the queue depth, the judge counts — are what make the decision auditable:
    a bare `status=refused` on top of an empty report is the silent-failure shape the
    `IngestReport.gates` precedent exists to prevent.
    """

    run_id: str
    submission_id: str
    criterion_id: str
    decision: str
    prior_judges: tuple[str, ...]
    added_judges: tuple[str, ...]
    judge_count: int
    units_inserted: int
    expected_value: float | None
    escalation_rate: float
    escalation_budget: float
    queue_depth: int
    breaker_tripped: bool
    gates: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BreakerTrip:
    """One criterion-breaker trip, as the operator surface reads it (`FR-ORCH-13`).

    The alert the design names ("any criterion tripping the circuit breaker") reads
    these rows: which criterion, when, and the window arithmetic that tripped it —
    `detail` carries the numbers so the alert answers "why", not just "what".
    """

    run_id: str
    criterion_id: str
    kind: str
    tripped_at: str
    detail: str


@dataclass(frozen=True)
class EscalationBudgetState:
    """The run-wide escalation ledger's state, as the operator reads it (`FR-ORCH-14`).

    The rate-above-budget alert's source (`CT-ORCH-16`: both breakers degrade visibly):
    the processed/escalated pair the rate is computed from, the budget it is compared
    against, the queued remainder, and the criteria whose breakers have tripped. Read
    from the ledger every time — no side-file counters (`FR-ORCH-02`).
    """

    run_id: str
    processed_results: int
    escalated_results: int
    escalation_rate: float
    budget: float
    over_budget: bool
    queued_requests: int
    tripped_criteria: tuple[str, ...]
    provisional_pairs: tuple[str, ...] = ()
    gates: dict[str, str] = field(default_factory=dict)


# --- the orchestrator ---------------------------------------------------------------------------


def _cohort_keys_on_filesystem(store: Any) -> tuple[str, ...]:
    """The default cohort-key discovery: the ledger's own files.

    `SqliteStore` lays Tier C out as one file per cohort under `<data_dir>/cohorts/`
    (§3.3's layout); listing that directory is the no-bookkeeping way to find every
    ledger there is. A store that lays the tier out differently injects its own key
    function on the orchestrator.
    """
    data_dir = getattr(store, "data_dir", None)
    if data_dir is None:
        raise WorkLedgerError(
            "resume() with no arguments discovers runs from the store's cohort ledger "
            "files, which needs the store's data directory; this store exposes no "
            "`data_dir`. Pass an explicit run_id, or inject a cohort_keys_for function."
        )
    return tuple(
        path.stem for path in Path(data_dir, "cohorts").glob("*.sqlite")
    )


def validate_grade_policy(catalog: Any, package_version_id: str) -> None:
    """Refuse a version whose grade policy names criteria the version does not declare
    (`FR-ORCH-31`, `CT-ORCH-25`, `CT-GRADE-15`'s run-start half).

    Called by `create_run` before the run row exists, so a refusal leaves nothing behind: the
    policy's ghost criterion is caught at run start rather than at grading time, where the
    operator meets it as a missing input on a run that has already spent money.

    Every referencing field of the shipped `GradePolicy` is checked — the `weights` members and
    the `gate`'s criterion. `FR-ORCH-31` also names per-question rules and best-k members;
    neither has a field in the landed policy object (`best_k_of_n` carries `k`, a count, and no
    member list), so there is nothing to read for them today. A policy that grows either field
    must extend `_policy_criterion_ids` in the same change.

    A version with no declared policy is not an error: the default policy references nothing.
    """
    from aeh.pkg import PackageIntegrityError  # `aeh.pkg` owns Tier P's migrations (see
    # `_catalog`: the import stays local so registration order remains each module's own).

    declared_policy = getattr(catalog, "grade_policy_declared", None)
    if callable(declared_policy) and not declared_policy(package_version_id):
        return
    policy = catalog.grade_policy(package_version_id)
    referenced = _policy_criterion_ids(policy)
    if not referenced:
        return
    declared = {
        _criterion_id_of(row) for row in catalog.criteria(package_version_id)
    }
    missing = sorted(name for name in referenced if name not in declared)
    if missing:
        raise PackageIntegrityError(
            f"the grade policy of {package_version_id!r} names criteria the version does not "
            f"declare: {', '.join(repr(name) for name in missing)}. The run refuses to start "
            f"(FR-ORCH-31): a policy referring to a criterion that is not there grades by a "
            f"rule nobody can satisfy, and the package is what needs fixing. Declared: "
            f"{sorted(declared)}"
        )


def _criterion_id_of(row: Any) -> str:
    """One criterion row's id, whatever shape the catalog hands back (mapping or object)."""
    if isinstance(row, dict):
        return str(row.get("criterion_id"))
    try:
        return str(row["criterion_id"])
    except (TypeError, KeyError, IndexError):
        return str(getattr(row, "criterion_id", ""))


def _policy_criterion_ids(policy: Any) -> set[str]:
    """Every criterion id the policy references, across its referencing fields."""
    referenced: set[str] = set()
    for criterion_id, _weight in getattr(policy, "weights", ()) or ():
        if criterion_id:
            referenced.add(str(criterion_id))
    gate = getattr(policy, "gate", None)
    gate_criterion = getattr(gate, "criterion_id", None) if gate is not None else None
    if gate_criterion:
        referenced.add(str(gate_criterion))
    return referenced


# --- #362: the stage-executor seam (FR-ORCH-27, ADR-14) -------------------------------------


class StageExecutor(Protocol):
    """What the composition layer hands the orchestrator to do a unit's real work.

    `execute(unit, governed)` runs ONE leased unit through its stage's shipped worker — the
    extraction worker, the scoring worker — with `governed` as the provider those workers call.
    The orchestrator owns the ledger, the pool width and the counters; the executor owns what a
    unit *means*. That split is why this is a seam and not a branch: `M-PIPE` binds a real
    executor, the report-only console binds none, and neither can reach the other's behaviour.
    """

    def execute(self, unit: Any, governed: Any) -> Any: ...

    # The contract the dispatch loop relies on, stated because it cannot enforce it:
    #
    # * Return a `StageOutcome` — `completed=False` requeues the unit, `completed=True` closes
    #   it. Returning a provider `Completion` instead is the transport seam's shape and would
    #   accrue to the run's counters a second time.
    # * Do not close or quarantine the unit yourself: the orchestrator owns that ledger
    #   transition, and `complete()` refuses a unit a worker has already quarantined.
    # * Let `RateLimitedError`, `MemoryError`, `ProviderUnavailableError` and
    #   `BuildChangedError` propagate — the loop classifies each one. Anything else is a
    #   defect and stops the pass with the units left leased for the sweeper.


@dataclass(frozen=True)
class StageOutcome:
    """One executed unit's result, as the dispatch loop reads it.

    `completed` is the honest answer to "did this unit finish": a worker that struck out
    within its own budget returns False, and the orchestrator requeues rather than closing the
    unit. `detail` is carried for the caller's own reporting and is never parsed here.
    """

    completed: bool = True
    detail: str | None = None


class GovernedProvider:
    """The run's provider, with the run's dispatch counters wrapped around it (`FR-ORCH-27`).

    Every `complete()` a stage worker makes through this object accrues to the run: tokens in
    and out, cost, cached prefix tokens, the resolved build, and the in-flight/peak concurrency
    the governor's ceiling is about. The worker cannot opt out and does not know it is counted —
    which is the point. A worker that makes three calls and then strikes the unit out has still
    spent three calls, and the run's bill says so (`CT-PROV-11`: the counters are the
    provider's, read and persisted by M-ORCH).

    Everything else on the wrapped provider passes through untouched, so a worker that reaches
    for an attribute this class never heard of still finds the real provider's.
    """

    def __init__(self, provider: Any, state: dict[str, Any]) -> None:
        self._provider = provider
        self._state = state

    def complete(self, payload: Any, model_ref: Any = None, params: Any = None) -> Any:
        lock = self._state["lock"]
        with lock:
            self._state["in_flight_calls"] += 1
            self._state["peak_concurrency"] = max(
                self._state["peak_concurrency"], self._state["in_flight_calls"]
            )
        try:
            answer = self._provider.complete(payload, model_ref, params)
        finally:
            with lock:
                self._state["in_flight_calls"] -= 1
        _accrue_completion(self._state, answer)
        return answer

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)


class TransportStageExecutor:
    """The `transport=` seam, as an executor (`FR-ORCH-27`): test-only, call-counting.

    It exists so the two seams are one code path rather than two: the dispatch loop always
    submits `executor.execute(...)`, and this is what a `transport=`-driven orchestrator binds.
    It calls `transport.call(request)` with the request assembled before the pool existed — no
    stage worker, no store write beyond the ledger's own.

    It returns the transport's own `Completion`, which the dispatch loop then accrues exactly
    as it always did: the transport seam makes ONE model call per unit, so the unit IS the
    call, and the in-flight counters are taken around it here rather than inside a provider
    the transport path never touches.
    """

    def __init__(self, transport: Any, payloads: dict[str, Any], state: dict[str, Any]) -> None:
        self._transport = transport
        self._payloads = payloads
        self._state = state

    def execute(self, unit: Any, governed: Any) -> Any:  # noqa: ARG002 — seam shape
        lock = self._state["lock"]
        with lock:
            self._state["in_flight_calls"] += 1
            self._state["peak_concurrency"] = max(
                self._state["peak_concurrency"], self._state["in_flight_calls"]
            )
        try:
            return self._transport.call(self._payloads[unit.work_id])
        finally:
            with lock:
                self._state["in_flight_calls"] -= 1


class _PreparedExecutor:
    """One executor with an optional pre-pass over the batch.

    The transport seam assembles every request BEFORE the pool exists — a raise then lands with
    nothing submitted, and the burst that follows reaches the full pool width (the pipelined
    alternative would never be observed to). A bound stage executor assembles inside its own
    worker, where the stage owns that door. This wrapper lets the dispatch loop hold one shape
    for both.
    """

    def __init__(self, executor: Any, prepare: Any = None,
                 payloads: dict[str, Any] | None = None) -> None:
        self._executor = executor
        self._prepare = prepare
        self._payloads = payloads

    def prepare(self, batch: Any) -> None:
        if self._prepare is None or self._payloads is None:
            return
        for unit in batch:
            self._payloads[unit.work_id] = self._prepare(unit)

    def execute(self, unit: Any, governed: Any) -> Any:
        # Bound first, then called: SEC-15's walker reads `<x>.execute(<arg>)` as a database
        # execute site whose statement is a parameter, and this is the STAGE seam
        # (`FR-ORCH-27`'s own name for it), not SQL. The alias keeps the public interface the
        # FR names while leaving the SQL vocabulary unambiguous.
        run_unit = self._executor.execute
        return run_unit(unit, governed)


def _accrue_completion(state: dict[str, Any], answer: Any) -> None:
    """Accrue one model answer to a run's counters (`CT-PROV-11`) — the ONE definition both
    seams use.

    The fields are read directly rather than through `getattr(..., 0)`: an answer that is not
    a `Completion` is a defect in whatever produced it, and a lenient read would accrue silent
    zeros — a run reporting no tokens and no cost for calls it actually made is the
    silent-failure shape the counters exist to prevent.
    """
    with state["lock"]:
        state["calls"] += 1
        state["tokens_in"] += answer.tokens_in
        state["tokens_out"] += answer.tokens_out
        state["cache_tokens"] += answer.cached_prefix_tokens or 0
        if answer.cost is not None:
            state["cost"] += answer.cost
        if state["resolved_build"] is None and answer.resolved_build:
            state["resolved_build"] = answer.resolved_build


#: `FR-ORCH-28`'s closed phase vocabulary. A phase outside it is a caller's mistake, refused
#: here and by the table's CHECK — two places, because the table outlives this process.
CELL_PHASES: tuple[str, ...] = ("integrity_pre", "integrity_post", "aggregated")

#: `FR-ORCH-29`'s hooks, and the phase each one reads.
READY_HOOKS: tuple[str, ...] = ("integrity_pre", "aggregate")


class CellKey(NamedTuple):
    """One cell: a (submission, criterion) pair, named so a tuple of them reads."""

    submission_id: str
    criterion_id: str


@dataclass(frozen=True)
class RunHandle:
    """Everything a composition layer needs to drive one run without reading the ledger.

    `M-PIPE` opens the transaction that `write_score`, `enqueue_escalation` and
    `mark_cell_phase` share (`FR-PIPE-04` requires the three to commit together), and a
    transaction comes from the cohort handle. `CT-PIPE-05` says `M-PIPE` executes no SQL, so
    it cannot find that handle by querying the run row itself — it asks the module that owns
    the row. That is what this is: one read, answered by `M-ORCH`, returning the handle and
    the four identities every hook needs.

    `status` and `pause_reason` are the stored values at the moment of the call —
    `RunResult.status` is required to equal `run.status`, and reading it through any other
    path would be reading around the owner.
    """

    run_id: str
    cohort_id: str
    cohort: Any
    package_id: str
    package_version_id: str
    status: str
    pause_reason: "str | None"
    #: The backend profile the run FROZE at creation (`FR-CONF-07`). A composition layer
    #: compares it against the process's current profile so a resume never rebinds a run to a
    #: backend its operator never approved (`FR-CONF-15`).
    backend_profile: str = ""


class PackageCatalogProtocol(Protocol):
    """The slice of `PackageCatalog` enumeration reads. Typed as a protocol so a test
    double satisfies it without a Tier P file (`CLAUDE.md` seam 2 — no network, no real
    upstream; the package arrives by injection like every other dependency)."""

    def criteria(self, v: str, question_id: str | None = None) -> tuple: ...


class Orchestrator:
    """The ledger slice of §3.7's Orchestrator: create a run, enumerate its units,
    resume, lease them under the two-sweep plan, and widen panels — escalation
    (`enqueue_escalation`), the random arm, the criterion breakers and the run-wide
    escalation budget are #60's. **#61 lands the run lifecycle** (`FR-ORCH-25`):
    `start(run_id)` is the `pending → running` edge and displays the run's estimated
    cost before any dispatch (`FR-ORCH-15`); `pause(run_id, cause=...)` writes the
    control row and applies it through the read pass the claim loop shares — a
    `ProviderUnavailableError` (`FR-ORCH-16`), a `BuildChangedError` (`FR-ORCH-17`) or
    an operator request pause a run without substituting anything; the cost ceiling the
    run froze is enforced from the provider seam's measured figures inside every claim
    transaction, and a crossing dispatch pauses the run naming spend and remaining
    (`CT-ORCH-12`'s four pause conditions — the fourth being the sensed ceiling).
    Pauses touch lifecycle columns only, so a resume re-binds to the frozen backend
    structurally: there is no substitution code path to suppress. Control rows written
    while the orchestrator was not dispatching queue in `run_control` and are honoured
    at the next read (`CT-ORCH-13`). Dispatch isolation and `ProgressReport` are #62's,
    below. `resume` takes no arguments from its first commit.

    **Recorded interpretations (#62) — dispatch, residency, concurrency, progress.**
    The dispatch loop's model-call seam takes the stage's ASSEMBLED closed request —
    `ScoringRequest` via `M-JUDGE`'s `ScoringWorker.assemble`, `ExtractionRequest`
    via `M-EXTRACT`'s `assemble_request` (`FR-ORCH-20`'s own wording: "exactly one
    submission per scoring or extraction request" — what is dispatched is the
    request, and its exactly-one form is assertable only over the closed type,
    `CT-JUDGE-02`). The loop's classification, batching and residency are untouched
    by the payload's shape; deterministic units cross nothing (their evaluation
    makes no model call), so the deterministic walk completes directly. Residency
    batches **judge models only**:
    `residency_policy` lists the roles permitted resident, and the units this loop
    dispatches are score units whose `judge_id` names a model — the transcriber's
    residency is the transcription stage's, not yet this module's. A judge's
    **batch** is its dispatchable work: the units the ready order hands out for it,
    plus the ones in flight; a gated or budget-deferred pending unit is not
    dispatchable (it may never become ready without an operator) and cannot hold a
    model resident — a residency held over undispatchable work starves every judge
    behind it — and when gated work becomes ready the model reloads to serve it. A
    residency swap's
    duration is the wall time of the first model call after the swap — the load rides
    that call; a swap whose first call is still to come records the count and adds the
    duration when the load is actually paid. The dispatch loop's extract walk sends
    the assembled `ExtractionRequest` (extraction IS a model call — `FR-ORCH-20`
    covers extraction requests); the deterministic walk is the ledger transition
    itself, completed with no transport (a deterministic criterion's evaluation makes
    no model call): completing the transition is what unlocks the judged batch, and
    the walks are bounded per pass by `HARNESS_ORCH_DISPATCH_WALK_BATCH`. The
    concurrency governor's cap is per run, starts at the run's frozen
    `concurrency_ceiling` (never the environment's — `FR-CONF-07`'s freeze), divides
    once per pass on any rate-limited/OOM call (floor 1) and is clamped per pass while
    M-STORE signals write backpressure (`CT-STORE-06`: a signal to reduce, never a
    fault — the clamp is sensed at the pass's start and does not persist). The report's
    `concurrency` is the cap the NEXT pass will run at (post-clamp, post-reduction) —
    the operator reads the reduction that takes effect. The OOM remedy requeues the
    judge's in-flight units without consuming attempts (the box's condition is not the
    unit taxonomy's, §9.11), halves the cap, and at the drop threshold removes the
    judge from the run's `panel_config` as a strict subset (never below one judge) —
    its un-run units stay in the ledger for an operator to re-queue under a smaller
    panel, never silently discarded. The completion predicate on the report is
    **ledger-derived, not run-status-derived** (`FR-ORCH-12`): nothing pending and no
    in-flight scoring judgment — a score unit in flight can still disagree with its
    panel and spawn an escalation. The report's estimate feeds
    `estimated_completion_seconds` with the ledger's own totals. `progress()` with no
    transport dispatches nothing: it is the report-only surface (the console's poll).

    **Recorded interpretations (#61).** The ceiling comparison is strict `>` per
    dispatch (a dispatch landing exactly at the ceiling proceeds; the run pauses once
    spend sits at the ceiling) — the breaker's and budget's reading of an "at or above"
    boundary; the at-ceiling sense fires only when the claim actually moved spend (a
    not-billed figure adds nothing and consumes no ceiling, so replayed work drains
    past an at-ceiling pause without re-pausing it). The estimate displayed at start is
    the sum of the units' seam figures. Every pause and resume — operator, sensed, or
    explicit `resume(run_id)` — is written as a `run_control` row and effected through
    the control-read pass (request ≠ effect, `CT-ORCH-13`); a resume supersedes the
    pauses queued before it (latest control intent wins, bounded by request time), and
    a queued pause on a `pending` run is honoured at `start` (the machine's declared
    edges have no `pending → paused` from mid-flight); a queued pause on a `running`
    run applies at the next claim pass; an operator's pause stays sticky across a
    no-argument `resume` (a stop outranks a scheduler's restart). Run-level `complete`
    is probed after every won lifecycle write and fires only for a `running` run with
    at least one unit and none open (quarantined units are not open — their record
    stands).

    The store is injected (`CLAUDE.md` seam 2). Nothing here opens a network connection
    or contacts a judge: enumeration is a pure function of the ledger, the package
    catalog and the roster, over an injected store, and every escalation decision is
    pure policy over ledger state (`NFR-ORCH-04`). The provider seam is injected the
    same way and consulted only for cost figures — no dispatch, retry or pause decision
    ever asks the provider what to do.
    """

    def __init__(
        self,
        store: Any,
        *,
        package_id_for: Any = default_package_id_for,
        cohort_keys_for: Any = None,
        clock: Any = None,
        provider: Any = None,
        transport: Any = None,
        executor: Any = None,
    ) -> None:
        self._store = store
        self._package_id_for = package_id_for
        #: The cost seam (`FR-ORCH-15`): the object the orchestrator consults for a
        #: unit's cost figure. Declared protocol: `estimate_cost(unit) -> Decimal |
        #: CostEstimate` — a `Decimal` is the figure; a `CostEstimate`-shaped answer
        #: contributes its `.cost` (None = not billed, which adds nothing to the
        #: accrual — replay is not billed and must not consume ceiling). Optional: a
        #: run whose frozen config carries no ceiling never consults it, and the
        #: estimate-at-start is simply not displayed when no seam was injected — a
        #: fabricated zero would read as a measured price (`CT-PROV-03`'s principle).
        #: A run that DID freeze a ceiling but is dispatched without a seam is refused
        #: at the claim pass, loudly: a ceiling checked against nothing is the
        #: estimated-optimism shape the seam exists to prevent.
        self._provider = provider
        #: The model-call transport seam (`FR-ORCH-19/21`, CLAUDE.md seam 2 — built the
        #: moment the dependency exists). Declared protocol: `call(request) ->
        #: Completion` (the real shipped type, `aeh.prov.Completion`) or a raise of the
        #: real taxonomy error (`RateLimitedError`, `MemoryError`) — the dispatch loop
        #: classifies by type and nothing else. `request` is the stage's ASSEMBLED
        #: closed request (`FR-ORCH-20`: the dispatch sends "exactly one submission per
        #: scoring or extraction request", never the ledger row — the assembler is the
        #: owning stage's shipped door, and `FR-JUDGE-02`'s exactly-one form is
        #: assertable only over the closed type). No default implementation: a
        #: fabricated in-process "provider" would be a network-shaped dependency
        #: smuggled past the seam. None means this orchestrator does not dispatch
        #: model work: `progress()` is then the report-only surface (the console's
        #: poll), which reads the ledger and claims nothing.
        self._transport = transport
        #: #362 (`FR-ORCH-27`, ADR-14): the stage-executor seam. `M-PIPE` binds one and the
        #: units do their real work through the shipped stage workers; `transport=` stays the
        #: test-only call-counting shape, adapted to the same protocol by
        #: `TransportStageExecutor` so the dispatch loop has one path rather than two.
        #: Binding both is refused rather than silently preferring one — a run dispatching
        #: through a seam the caller did not think it bound is a confusion neither seam can
        #: diagnose afterwards.
        if executor is not None and transport is not None:
            raise ValueError(
                "bind an executor OR a transport, not both (FR-ORCH-27): the executor runs "
                "units through their stage workers and the transport is the test-only "
                "call-counting seam, so a run holding both would dispatch through one of "
                "them for reasons no caller stated."
            )
        if executor is not None and provider is None:
            raise ValueError(
                "an executor was bound with no provider (FR-ORCH-27): the stage workers it "
                "runs make their model calls through the GovernedProvider wrapped around the "
                "run's provider, so a run without one would fail at the first call, far from "
                "the binding that caused it."
            )
        self._executor = executor
        #: Maps the store to its cohort tier keys, for the run discovery `resume()` does
        #: with no arguments. Default: the `cohorts/` directory under the store's data
        #: dir — the ledger's own files are the bookkeeping, which is the whole point of
        #: `FR-ORCH-02`. Injectable so a double-backed test can pin discovery.
        self._cohort_keys_for = cohort_keys_for or _cohort_keys_on_filesystem
        #: The injected clock, driving the store's monotonic lease counter (`FR-STORE-11`).
        #: None means the production clock (`aeh.store.SystemClock`). Passed through to
        #: `lease_clock()` on first use and cached — one lease clock per store, the
        #: store's own rule, and lazy so an orchestrator that only enumerates never
        #: claims the store's clock slot from one that leases.
        self._clock = clock
        self._lease_clock_obj: LeaseClock | None = None
        #: Package catalogs held open per (package_id, package_version_id) — the claim
        #: pass reads the catalog on every dispatch, and `NFR-PKG-05`'s per-run cache is
        #: per instance, so one live catalog per version is what makes the hot path one
        #: indexed query instead of a version load.
        self._catalogs: dict[tuple[str, str], Any] = {}
        #: The two sweeps' derived ordering data, per package version (`_sweep_plan`).
        #: The package is immutable for the run, so the plan is computed once and reused
        #: for the run's lifetime — the topological positions and the dependency closure
        #: are pure functions of the version.
        self._sweep_plans: dict[str, SweepPlan] = {}
        #: The dispatch order of one (run, stage), drained front to back across claim
        #: passes (`_claim_pass`). Keyed `(run_id, stage)`; an entry holds only the
        #: still-unclaimed ready candidates. Rebuilt on exhaustion, on a lost claim
        #: guard, on a requeue (failure or sweeper reclaim), and on re-enumeration —
        #: the invalidation set `_claim_pass` states.
        self._order_cache: dict[tuple[str, str], deque[Any]] = {}
        #: Per-run dispatch state (`_dispatch_state`): the concurrency governor's cap,
        #: the residency batch's state, the OOM ladder's counts and the run-metrics
        #: accumulators. Keyed by run_id, rebuilt from the ledger when absent — the
        #: ledger is the bookkeeping (`FR-ORCH-02`); this holds only what the ledger
        #: cannot say (the seam's in-memory counters); the dropped judges are ledger
        #: state, not this dict's (`_dropped_judges`).
        self._dispatch_states: dict[str, dict[str, Any]] = {}

    # -- run creation ---------------------------------------------------------------------------

    def create_run(
        self,
        cohort_id: str,
        package_version: str,
        cfg: Any,
        *,
        run_id: str | None = None,
    ) -> str:
        """Create the run row and its audit record; return the run id.

        `run_id` is minted as ``run-<uuid4 hex>`` — two runs of the same (cohort, package
        version, config) are *different runs* and must not share work ids, which is why
        `run_id` is a hash input. Keyword override for a caller (or test) that names its
        own. The row is born `status='pending'`; `FR-ORCH-25`'s status transitions are
        control-row territory (#61) and #57 flips none of them.

        `provider_config` is the run's frozen backend snapshot, serialized canonically —
        the HLD's "provider, per-judge model ref, retention setting in force, concurrency
        cap, cost ceiling", every field the audit may one day ask the run to account for.

        The run start is logged here too: exactly one `run_start` line through
        `aeh.conf.log_run_start`, whose returned summary is the one the audit record stores.

        The audit record is written here, on the durable tier, by `record_run_start` —
        the run's configuration is frozen the moment the row exists, and the audit trail
        should not depend on a later story landing. The two writes are two transactions
        on two tiers (a cross-tier transaction is refused by design, `CT-STORE-06`): the
        run row commits first, so a crash between them leaves a run whose audit record
        is absent — visible in the durable tier, and repairable without touching the
        ledger: read the run's id back from the run table and call
        `record_run_start(store, cfg, run_id=<that id>)` to write the missing record.
        Creating the run "again" would mint a second `run_id` and a second audit
        record, which is not a retry. Never a half-written ledger.
        """
        package_id = self._package_id_for(package_version)
        # FR-ORCH-31: the version's own declarations must hang together before the run row
        # exists — beside the retention check below, and for the same reason: a refusal at
        # run start leaves nothing behind.
        from aeh.pkg import PackageCatalog

        validate_grade_policy(
            PackageCatalog(self._store.package(package_id), package_id=package_id),
            package_version,
        )
        if run_id is None:
            run_id = f"run-{uuid.uuid4().hex}"
        panel_config = panel_config_json(cfg.panel)
        # A `cloud-hosted` run starts only once zero-retention routing is confirmed for every
        # panel member (`FR-PROV-14`, `NFR-SYS-03`, `SEC-03`): verified here, before the run
        # row exists, so a refusal leaves nothing behind.
        retention = self._verify_retention_at_start(cfg)
        provider_fields: dict[str, Any] = {}
        if retention is not None:
            # "Recorded per run": the confirmed build ids, in the run's frozen snapshot.
            provider_fields["retention_verified"] = sorted(
                ref.build_id for ref in retention.confirmed
            )
        provider_config = json.dumps(
            {
                **provider_fields,
                "backend_profile": cfg.backend_profile,
                "panel_build_ref": cfg.panel_build_ref,
                "panel": [ref.build_id for ref in cfg.panel],
                "transcriber": cfg.transcriber.build_id,
                "prompt_template_v": cfg.prompt_template_v,
                "concurrency_ceiling": cfg.concurrency_ceiling,
                "retention_setting": cfg.retention_setting,
                "cost_ceiling": (
                    str(cfg.cost_ceiling) if cfg.cost_ceiling is not None else None
                ),
                "cost_currency": cfg.cost_currency,
            },
            separators=_JSON_SEPARATORS,
            sort_keys=True,
        )
        handle = self._store.cohort(cohort_id)
        try:
            with handle.transaction() as tx:
                tx.execute(
                    ORCH_STATEMENTS["insert_run"],
                    run_id=run_id,
                    cohort_id=cohort_id,
                    package_version_id=package_version,
                    package_id=package_id,
                    panel_config=panel_config,
                    backend_profile=cfg.backend_profile,
                    provider_config=provider_config,
                    prompt_template_v=cfg.prompt_template_v,
                )
        except sqlite3.IntegrityError as error:
            # Named, not raw: the two ways this write is refused are caller mistakes
            # worth naming, in the same posture as `RunNotFoundError` — a nonexistent
            # cohort (the run row's FK refuses the write) or an explicit `run_id`
            # already taken. Either way nothing was created and nothing needs cleanup.
            raise WorkLedgerError(
                f"run {run_id!r} was not created for cohort {cohort_id!r}: {error}. "
                "Either the cohort does not exist (create it with ingest first) or the "
                "run id is already taken by an earlier run."
            ) from error
        # The run start is this moment, and only this caller knows it (`log_run_start`'s own
        # docstring): the one structured line is emitted here, once per run, and the audit
        # record stores the very summary the line carried (`FR-CONF-09`, `CT-CONF-13`,
        # `NFR-SYS-11`, OBS-10). Resolution never logs, so a console that resolved on the
        # request path does not produce a second line.
        from aeh.conf import log_run_start

        summary = log_run_start(cfg)
        record_run_start(self._store, cfg, run_id=run_id, summary=summary)
        return run_id

    def _verify_retention_at_start(self, cfg: Any) -> Any:
        """`FR-PROV-14` at run start, fail-closed.

        `None` for a profile that sends nothing off the machine. For `cloud-hosted`, the
        provider seam's `RetentionReport`, confirmed for every panel member. A missing seam,
        a seam without `verify_retention`, or a report that leaves any member unconfirmed
        raises `RetentionPolicyError` — the gate is never skipped, because a skipped check
        reads as a kept privacy promise.
        """
        if cfg.backend_profile != "cloud-hosted":
            return None
        from aeh.prov import RetentionPolicyError

        verify = getattr(self._provider, "verify_retention", None)
        if verify is None:
            raise RetentionPolicyError(
                "a cloud-hosted run cannot start: the orchestrator was given no provider "
                "able to verify zero-retention routing (FR-PROV-14), so retention for the "
                f"{len(cfg.panel)} panel members is unconfirmed and nothing was created."
            )
        report = verify(tuple(cfg.panel))
        confirmed = {ref.build_id for ref in getattr(report, "confirmed", ())}
        unconfirmed = [ref for ref in cfg.panel if ref.build_id not in confirmed]
        unconfirmed += list(getattr(report, "unconfirmed", ()) or ())
        if unconfirmed:
            names = "; ".join(f"{ref.provider}:{ref.build_id}" for ref in unconfirmed)
            raise RetentionPolicyError(
                f"zero-retention routing unconfirmed for panel members: {names}. A "
                "cloud-hosted run does not start until every member is confirmed."
            )
        return report

    def _invalidate_order_cache(self, run_id: str) -> None:
        """Drop the dispatch-order cache entries for one run (`NFR-ORCH-01`).

        Any write that changes the claimable set — enumeration, a failure requeue, a
        sweeper reclaim — can falsify a cached order; the next claim pass re-reads
        instead of trusting it.
        """
        for key in [k for k in self._order_cache if k[0] == run_id]:
            del self._order_cache[key]

    # -- enumeration ----------------------------------------------------------------------------

    def enumerate_units(self, run_id: str) -> EnumerationReport:
        """Compute and insert the run's base units; idempotent by construction.

        The pass is a pure function of the ledger's run row, the package catalog and the
        cohort roster, walked in sorted order — so the same (cohort, package version,
        config) enumerates byte-identical `work_id` sets (NFR-ORCH-05). Each unit is
        inserted `INSERT OR IGNORE` keyed on `work_id`: a row already present is left
        exactly as the ledger holds it — `done` stays done, `quarantined` stays
        quarantined — which is what makes re-running a completed run a no-op that
        produces no duplicate rows (FR-ORCH-03) and what resume's skip is made of
        (FR-ORCH-02). The work-ID scheme is the invalidation: a changed input computes a
        new `work_id` and the prior result is simply unreachable from the new unit
        (NFR-EXTRACT-02/03) — there is no cleanup step to forget.

        **Base shapes** (§3.7's data flow): a judged criterion (the catalog's
        `kind='open'`) gets one `stage='extract'` unit with a null judge — extraction is
        judge-independent by §7.2 Rule 2 — plus one `stage='score'` unit per panel arm up
        to the criterion's base depth (`FR-SETUP-08`: 1 for `atomic`/`atomic_with_gate`,
        3 for `holistic`). A criterion the package declares
        `evaluation_mode='deterministic'` gets exactly one `stage='deterministic'` unit
        with a null judge and no extraction and no scoring unit.
        **Reconciliation closed (#369, retiring #59's note):** that note recorded the
        design's `evaluation_mode` column as existing in no shipped schema, and stood the
        equivalence `kind='mcq'` IS `evaluation_mode='deterministic'` in its place.
        `FR-PKG-22` ships the column, so the equivalence is retired here and everywhere
        that read it (`FR-ORCH-35`): shape and evaluation are separate claims, and a
        package may declare a multiple-choice criterion whose options a panel weighs.
        The migration's backfill makes the switch lossless — `deterministic` exactly where
        `kind='mcq'` held — so no existing package changes behaviour. Extract and score
        units are enumerated for **admitted** submissions only (`FR-ORCH-22`); the
        deterministic unit is enumerated for every submission.

        **The random arm** (`FR-ORCH-11`, this story): after a judged pair's base score
        units, the pair draws at `HARNESS_ORCH_RANDOM_ARM_RATE` (default 0.07) — the
        seeded draw `random_arm_selection` runs over the pair's key with the run's own
        seed (`run_random_arm_seed`, derived from the run id), so the byte-identical
        enumeration guarantee (NFR-ORCH-05) survives: the same inputs draw the same
        pairs every pass, and `INSERT OR IGNORE` keeps a drawn pair's units from
        duplicating. A drawn pair gets the widened panel an escalation would build
        (1→3, 3→5), marked `origin='random_arm'` — the origin is why the work exists,
        deliberately NOT a `work_id` input, so a base panel and a random-arm panel for
        the same (submission, criterion, judge) share rows rather than
        double-scoring. The draw consults neither confidence, nor the escalation
        budget, nor a breaker (`CT-ORCH-15`: suppression would make the routing
        policy unfalsifiable). Explicit escalations stay with `enqueue_escalation`
        below — enumeration does not create them.

        Commit batches of `HARNESS_ORCH_ENUM_COMMIT_BATCH` inserts keep one pass from
        holding a write lock across 23,000 inserts; the knob exists so a slower box can
        shrink it without a code change (NFR-ORCH-01 keeps per-unit cost trivial; the
        benchmark is S-ORCH-03's, not this module's).
        """
        # The claim pass's order caches hold rows read before this pass may insert new
        # ones — drop the run's entries, or a cached order would keep the new units
        # undiscoverable until an unrelated exhaustion.
        self._invalidate_order_cache(run_id)
        row = self._run_row(run_id)
        gates: dict[str, str] = {
            "run_row": f"found (status={row['status']}, cohort={row['cohort_id']})",
        }
        arms = self._panel_arms(row["panel_config"])
        gates["panel_config"] = f"{len(arms)} arm(s) in panel order"
        prompt_template_version = row["prompt_template_v"]

        catalog = self._catalog(row)
        criteria = sorted(
            catalog.criteria(row["package_version_id"]),
            key=lambda c: c["criterion_id"],
        )
        gates["catalog"] = (
            f"package {row['package_id']} version {row['package_version_id']}: "
            f"{len(criteria)} criterion(a)"
        )

        cohort = self._store.cohort(row["cohort_id"])
        submissions = cohort.query(
            ORCH_STATEMENTS["select_submissions"], cohort_id=row["cohort_id"]
        )
        gates["submissions"] = f"{len(submissions)} submission(s) in the cohort"

        # The admission filter (`FR-ORCH-22`): Sweep 1 work is enumerated for admitted
        # submissions only; a quarantined (or otherwise refused) submission generates no
        # scoring work until it is re-ingested — re-ingestion flips the row's status, and
        # the next enumeration inserts its units into the SAME run (`INSERT OR IGNORE`
        # keeps everything already there). **The `deterministic` stage admits every
        # submission**: a deterministic criterion has no extraction unit for admission to
        # gate (`FR-ORCH-08` — none exists to wait for), and M-DET scores the structured
        # answer data ingest validated, not the extracted evidence the refused statuses
        # describe. The sweep-ordering tests' `units_inserted == 2` on re-ingest pins
        # this shape: had the deterministic unit waited for admission, three units would
        # arrive, not two.
        admitted = [
            s for s in submissions
            if s["ingest_status"] is None
            or s["ingest_status"] in SWEEP1_ADMITTED_INGEST_STATUSES
        ]
        admitted_ids = {s["submission_id"] for s in admitted}
        withheld = len(submissions) - len(admitted)
        refused = sorted(
            {
                s["ingest_status"] for s in submissions
                if s["ingest_status"] is not None
                and s["ingest_status"] not in SWEEP1_ADMITTED_INGEST_STATUSES
            }
        )
        gates["admission"] = (
            f"{len(admitted)} of {len(submissions)} admitted to Sweep 1 "
            f"(rule: {sorted(SWEEP1_ADMITTED_INGEST_STATUSES)} or unjudged); "
            f"{withheld} withheld"
            + (f" (statuses: {refused})" if refused else "")
        )

        batch = _env_int(ENUM_COMMIT_BATCH_ENV, ENUM_COMMIT_BATCH_DEFAULT)
        random_arm_rate = _env_float(
            RANDOM_ARM_RATE_ENV, ORCH_RANDOM_ARM_RATE, low=0.0, high=1.0
        )
        run_seed = run_random_arm_seed(run_id)

        computed: list[tuple[str, dict[str, Any]]] = []
        random_arm_pairs = 0
        random_arm_units = 0
        for submission in submissions:
            for criterion in criteria:
                # `FR-ORCH-35`: the criterion's DECLARED mode, not its shape. A package
                # may declare a judged multiple-choice criterion — one whose options a
                # panel must weigh — and enumerating it as deterministic would skip the
                # extract and score units it is entitled to.
                if _row_evaluation_mode(criterion) == "deterministic":
                    computed.append(self._unit(
                        row, STAGE_DETERMINISTIC, submission, criterion, None,
                    ))
                    continue
                if submission["submission_id"] not in admitted_ids:
                    continue
                computed.append(self._unit(
                    row, STAGE_EXTRACT, submission, criterion, None,
                ))
                depth = min(
                    SCORING_MODEL_BASE_DEPTH.get(criterion["scoring_model"], 1),
                    len(arms),
                )
                for arm in arms[:depth]:
                    computed.append(self._unit(
                        row, STAGE_SCORE, submission, criterion, arm,
                    ))
                # The random arm (`FR-ORCH-11`, `CT-ORCH-15`): the pair draws at the
                # configured rate, independent of confidence — the draw takes the
                # pair's identities and the rate and nothing else — and a drawn pair
                # gets the widened panel an escalation would build, marked
                # `origin = 'random_arm'` so the sample stays statistically separable
                # (`M-STATS`/`M-REVIEW` read the mark). **Nothing suppresses it**: the
                # draw runs before any escalation exists to gate and consults neither
                # the budget nor a breaker — the arm measures the routing policy
                # itself (`FR-STATS-08`), and a budget that could silence it would
                # make the policy unfalsifiable. It spends compute, never teacher
                # minutes, and produces no review item (`FR-REVIEW-07`).
                if random_arm_selection(
                    (submission["submission_id"], criterion["criterion_id"]),
                    run_seed,
                    random_arm_rate,
                ):
                    widened = escalation_plan(arms[:depth], panel_arms=arms)
                    for judge in widened[depth:]:
                        computed.append(self._unit(
                            row, STAGE_SCORE, submission, criterion, judge,
                            origin="random_arm",
                        ))
                    random_arm_pairs += 1
                    random_arm_units += len(widened) - depth

        work_ids = sorted(work_id for work_id, _ in computed)
        existing = {
            r["work_id"] for r in cohort.query(
                ORCH_STATEMENTS["select_run_work_ids"], run_id=run_id
            )
        }
        gates["ledger_read"] = (
            f"{len(existing)} unit(s) already in the ledger for this run"
        )

        pending = [
            (work_id, params) for work_id, params in computed
            if work_id not in existing
        ]
        inserted = 0
        for start in range(0, len(pending), batch):
            with cohort.transaction() as tx:
                for _, params in pending[start:start + batch]:
                    # The existing-set read and this write are separated by design —
                    # the single-writer queue serializes them — and INSERT OR IGNORE is
                    # the idempotent form regardless: a row that appeared between read
                    # and write is left exactly as the ledger holds it, never rewritten.
                    tx.execute(ORCH_STATEMENTS["insert_work_unit"], **params)
                    # `OR IGNORE` cannot report what it did: an ignored row is either a
                    # duplicate that raced in between the read and this write, or a row
                    # a constraint refused — and `OR IGNORE` swallows both silently.
                    # Counting the loop's iterations would report the ledger as having
                    # taken rows it does not hold, so the count comes from the ledger:
                    # `changes()` read in the same transaction, of the write that
                    # transaction itself just made.
                    inserted += int(
                        tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"]
                    )

        counts: dict[tuple[str, str], int] = {}
        for r in cohort.query(ORCH_STATEMENTS["select_run_counts"], run_id=run_id):
            counts[(r["stage"], r["status"])] = r["n"]
        by_stage: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for (stage, status), n in counts.items():
            by_stage[stage] = by_stage.get(stage, 0) + n
            by_status[status] = by_status.get(status, 0) + n
        gates["ledger_write"] = (
            f"{inserted} inserted, {len(computed) - inserted} already present"
        )
        gates["ledger_counts"] = ", ".join(
            f"{status}={by_status[status]}" for status in sorted(by_status)
        ) or "ledger empty for this run"
        # `CT-ORCH-15`'s observability: the arm's sample size is visible next to the
        # enumeration's status, and the gate names its independence — a reader of the
        # report can tell drawn units from suppressed ones without re-deriving the
        # draw.
        gates["random_arm"] = (
            f"{random_arm_pairs} pair(s) drawn at rate {random_arm_rate} "
            f"({random_arm_units} unit(s), origin='random_arm'); independent of "
            "confidence — never suppressed by the escalation budget or a breaker"
        )

        return EnumerationReport(
            run_id=run_id,
            status="enumerated" if inserted else "no-op",
            work_ids=tuple(work_ids),
            units_enumerated=len(computed),
            units_inserted=inserted,
            units_already_present=len(computed) - inserted,
            by_stage=by_stage,
            by_status=by_status,
            gates=gates,
        )

    # -- resume (FR-ORCH-02) --------------------------------------------------------------------

    # -- the run lifecycle: start, pause, resume (FR-ORCH-15/16/17/25, CT-ORCH-12/13) -----------

    def start(self, run_id: str) -> str:
        """Dispatch a `pending` run: `pending → running` (`FR-ORCH-25`'s declared edge).

        **The estimate precedes dispatch** (`FR-ORCH-15`): before the status flips, the
        run's estimated cost is obtained from the provider seam — the per-unit figures the
        run will actually be dispatched against, summed — and written to the run row, so
        the operator surface can read the figure before a single unit is leased. A run
        with no seam injected (or nothing enumerated yet) displays no estimate: a
        fabricated zero would read as a measured price (`CT-PROV-03`'s principle).

        **A queued pause is honoured at start** (`CT-ORCH-13`): a control row written
        while the orchestrator was not dispatching (a `pause` requested of a `pending`
        run — request ≠ effect) is applied here instead of starting, so the run pauses
        rather than races past a stop someone already asked for. The start that loses to
        a queued pause is not swallowed: the row reads `paused`, with the requester's
        reason, not `running`.

        From any state but `pending` — including `paused` (an operator resumes, never
        re-starts, a paused run: `FR-ORCH-25` declares `paused → running` as resume's
        edge) — this raises `RunStateError` and the row's state stays exactly where it
        was. Returns the status the run row carries after the call.
        """
        cohort, row = self._find_run(run_id)
        if row["status"] != "pending":
            raise RunStateError(
                f"start({run_id[:12]}) refused: the run is '{row['status']}', not "
                "'pending' — FR-ORCH-25's machine declares pending → running as the "
                "start edge and nothing else; resume() un-pauses a paused run."
            )
        # Control rows first: a queued pause outranks the start that honours it
        # (`CT-ORCH-13` — the request was already made; the effect lands now).
        self._apply_control_rows(cohort, run_id, honour_queued_pause=True)
        row = self._run_row(run_id)
        if row["status"] == "paused":
            return "paused"
        # FR-ORCH-15's displayed estimate, before any dispatch.
        estimate = self._run_cost_estimate(cohort, run_id)
        if estimate is not None:
            with cohort.transaction() as tx:
                tx.execute(
                    ORCH_STATEMENTS["set_run_estimate"],
                    run_id=run_id,
                    cost_estimate=str(estimate),
                )
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["transition_run_started"],
                run_id=run_id,
                started_at=_now(),
            )
            won = int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"])
        if won:
            self._maybe_complete_run(cohort, run_id)
        return "running"

    def pause(
        self, run_id: str, cause: BaseException | str | None = None
    ) -> str:
        """Pause a run: write the **control row**, then let the control-read pass apply it.

        The two-step is the point, not overhead: the control row is the durable request
        (`CT-ORCH-13` — request ≠ effect, the orchestrator reads control rows on its own
        schedule), and applying through the same pass the claim loop reads means a pause
        lands identically whether it was requested a second ago or written while the
        orchestrator was down. On a `running` run the read pass runs immediately and the
        effect is immediate; on a `pending` run the row stays queued and the effect lands
        at the next `start` — a run that has not begun dispatching is not torn down for a
        stop it can simply honour first. An already-`paused` run records the request as
        satisfied (applied at once): the state the request asks for already holds.
        Terminal states (`complete`, `failed`) refuse with `RunStateError` — a stop is
        not a result.

        `cause` is one of `CT-ORCH-12`'s four pause conditions: a `ProviderUnavailableError`
        (`FR-ORCH-16`), a `BuildChangedError` (`FR-ORCH-17`), the cost ceiling (the claim
        pass pauses on its own — it writes a sensed pause naming spend and remaining, never
        calling this), or `None` for an operator request. The rendered reason lands on the
        run row (`pause_reason`) so the operator surface can say *why* the run stopped,
        never just that it did.

        The pause touches lifecycle columns only — never `provider_config`/`panel_config`
        (`FR-ORCH-16`'s resume-same-backend: the backend the run was frozen with is the
        backend it resumes with, because nothing here can change it). Returns the status
        the run row carries after the call.
        """
        cohort, row = self._find_run(run_id)
        status = row["status"]
        if status in ("complete", "failed"):
            raise RunStateError(
                f"pause({run_id[:12]}) refused: the run is '{status}' — a terminal "
                "run keeps its record; a pause is a stop, not a rewrite of history."
            )
        reason = self._pause_reason_text(cause)
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["insert_run_control"],
                control_id=f"control-{uuid.uuid4().hex}",
                run_id=run_id,
                action="pause",
                reason=reason,
                requested_at=_now(),
            )
        if status == "paused":
            # The requested state already holds: record the request as applied, change
            # nothing. (An operator double-pausing must not manufacture a state flip.)
            with cohort.transaction() as tx:
                tx.execute(
                    ORCH_STATEMENTS["mark_pauses_applied"],
                    applied_at=_now(),
                    run_id=run_id,
                )
            return "paused"
        # Apply through the control-read pass — immediate on a running run, queued on a
        # pending one (CT-ORCH-13).
        status_after, _queued = self._apply_control_rows(cohort, run_id)
        return status_after

    def resume(self, run_id: str | None = None) -> None:
        """Resume work with **no arguments** — the requirement, not ergonomics.

        With no argument, the open runs are discovered from the ledger itself: every run
        whose status is `pending`, `running` or `paused`, across every cohort file the
        store holds. No side file, no cursor, no operator input — `resume` requires no
        bookkeeping beyond the ledger (`FR-ORCH-02`), and an argument would be a place
        for an operator to be wrong under time pressure.

        Resuming re-enumerates, and re-enumeration is where "skip every unit with
        `status='done'`" is realized: a done unit's `work_id` is already in the ledger,
        `INSERT OR IGNORE` leaves it untouched, and no result is recomputed or duplicated.
        A completed run resumed — by discovery's omission or by explicit id — enumerates
        to a no-op. Invoked when nothing is wrong, it inserts nothing and changes
        nothing: the safe no-op the acceptance criterion asks for.

        **Control rows are both the input and the effect here** (`CT-ORCH-13`): the
        no-argument form reads each open run's unapplied control rows first — a resume
        written while the orchestrator was down flips its paused run back to `running`
        through the same guarded transition an explicit resume uses. **An explicit
        `run_id` is itself written as a control row** — request ≠ effect applies to
        every resume, no-argument or named: the row is the durable request, the read
        pass the effect. On a paused run the pass effects the `paused → running` edge
        (`FR-ORCH-25`) and supersedes the pauses queued before it; on a pending or
        running one the request is vacuous and is marked applied. Either way the resume
        re-binds to nothing and consults no current configuration — the run's frozen
        `provider_config`/`panel_config` are the backend (`FR-ORCH-16`'s
        resume-same-backend is structural: the lifecycle transitions write status
        columns only, so *no code path exists* by which a resume could substitute a
        backend). An operator's pause stays sticky across a restart:
        the no-argument form applies control rows and enumerates but does not auto-unpause
        a run nobody asked to resume — a stop an operator requested outranks a scheduler's
        restart.

        The dispatch half of resume — leasing the pending units to workers — is #58's
        `lease` landing on this same ledger; the ledger half (nothing done is re-run,
        nothing lost, nothing duplicated) is complete here.
        """
        if run_id is not None:
            cohort, row = self._find_run(run_id)
            if row["status"] not in ("complete", "failed"):
                # The explicit resume is a control row like any other (`CT-ORCH-13` —
                # a resume request is effected by WRITING the row and letting the
                # control-read pass apply it, never as an in-request state change;
                # the row is the durable request, `applied_at` the evidence it was
                # honoured). On a paused run the pass effects the `paused → running`
                # edge; on a pending/running one the request is vacuous and is marked
                # applied; either way it supersedes the pauses queued before it.
                with cohort.transaction() as tx:
                    tx.execute(
                        ORCH_STATEMENTS["insert_run_control"],
                        control_id=f"control-{uuid.uuid4().hex}",
                        run_id=run_id,
                        action="resume",
                        reason=None,
                        requested_at=_now(),
                    )
                status_after, _ = self._apply_control_rows(cohort, run_id)
                if status_after == "running":
                    # The resumed run's last open unit may have closed while it was
                    # paused (completions keep landing; the probe only fires from
                    # `running`) — a resume that opens a finished run completes it.
                    self._maybe_complete_run(cohort, run_id)
            self.enumerate_units(run_id)
            return
        for open_run in self._open_run_ids():
            cohort, row = self._find_run(open_run)
            self._apply_control_rows(cohort, open_run)
            self.enumerate_units(open_run)

    def _apply_control_rows(
        self, cohort: Any, run_id: str, *, honour_queued_pause: bool = False
    ) -> tuple[str, str | None]:
        """Read and apply a run's unapplied control rows, oldest request first.

        Returns `(status, queued_pause_reason)`: the run row's status after application,
        and the reason of a pause still queued on a `pending` run (queued, not dropped —
        `CT-ORCH-13`'s request ≠ effect; the claim pass uses a non-None reason to stop
        dispatching into a run someone has asked to stop, and `start`'s
        `honour_queued_pause=True` call applies it instead of starting).

        **The arms.** A `pause` on a `running` run transitions it to `paused` carrying the
        requester's reason; on a `pending` run it stays queued (unless
        `honour_queued_pause` — `start`'s call — applies it as `pending → paused`); on an
        already-`paused` run it is marked applied (the requested state holds). A `resume`
        on a `paused` run transitions it to `running` and supersedes every pause still
        queued behind it (the latest control intent wins); elsewhere it is vacuous and is
        marked applied so the ledger does not accumulate forever-unapplied rows. Every
        transition is the guarded `UPDATE ... WHERE status = :from_status` whose
        `changes()` decides the win — a concurrent writer's move absorbs the request,
        exactly the claim guard's discipline.
        """
        fresh = cohort.query(ORCH_STATEMENTS["select_run"], run_id=run_id)
        if not fresh:
            raise RunNotFoundError(
                f"no run row named {run_id!r} exists in this cohort ledger."
            )
        controls = cohort.query(
            ORCH_STATEMENTS["select_unapplied_control"], run_id=run_id
        )
        if not controls:
            return fresh[0]["status"], None
        status = fresh[0]["status"]
        queued_reason: str | None = None
        for control in controls:
            action = control["action"]
            reason = control["reason"]
            control_id = control["control_id"]
            if action == "pause":
                if status == "running":
                    if self._transition_run(
                        cohort,
                        run_id,
                        to_status="paused",
                        pause_reason=reason,
                        completed_at=None,
                        from_status="running",
                    ):
                        status = "paused"
                    self._mark_control_applied(cohort, control_id)
                elif status == "pending" and honour_queued_pause:
                    if self._transition_run(
                        cohort,
                        run_id,
                        to_status="paused",
                        pause_reason=reason,
                        completed_at=None,
                        from_status="pending",
                    ):
                        status = "paused"
                    self._mark_control_applied(cohort, control_id)
                elif status == "pending":
                    queued_reason = reason  # stays unapplied: honoured at start
                else:  # already paused — the request is satisfied
                    self._mark_control_applied(cohort, control_id)
            elif action == "resume":
                if status == "paused":
                    if self._transition_run(
                        cohort,
                        run_id,
                        to_status="running",
                        pause_reason=None,
                        completed_at=None,
                        from_status="paused",
                    ):
                        status = "running"
                # The supersede is bounded by request time: a resume supersedes the
                # pauses queued BEFORE it — a pause requested after the resume is a
                # later intent this resume must not consume, and it is honoured at
                # its own pass (controls apply oldest-request-first).
                with cohort.transaction() as tx:
                    tx.execute(
                        ORCH_STATEMENTS["mark_pauses_applied_before"],
                        applied_at=_now(),
                        run_id=run_id,
                        requested_at=control["requested_at"],
                    )
                queued_reason = None
                # Applied in every arm: the resume was honoured (paused → running)
                # or is vacuous (the run was never paused) — either way the request
                # is resolved, and marking it so is what keeps the ledger from
                # accumulating forever-unapplied rows.
                self._mark_control_applied(cohort, control_id)
        return status, queued_reason

    def _mark_control_applied(self, cohort: Any, control_id: str) -> None:
        """Mark one control row applied (`applied_at` read-back is the operator's
        evidence the request was honoured, not just recorded)."""
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["mark_control_applied"],
                control_id=control_id,
                applied_at=_now(),
            )

    def _transition_run(
        self,
        cohort: Any,
        run_id: str,
        *,
        to_status: str,
        pause_reason: str | None,
        completed_at: str | None,
        from_status: str,
    ) -> bool:
        """One guarded run-state transition (`FR-ORCH-25`'s edges, nothing else).

        The `WHERE status = :from_status` guard is the same write-time discipline as the
        claim's: two writers racing to move the same run resolve by the row's state at
        write time, and the loser's `changes()` reads zero. Returns whether this caller
        won.
        """
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["transition_run_status"],
                run_id=run_id,
                to_status=to_status,
                pause_reason=pause_reason,
                completed_at=completed_at,
                from_status=from_status,
            )
            return bool(int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"]))

    def _maybe_complete_run(self, cohort: Any, run_id: str) -> None:
        """Flip a `running` run to `complete` when its last open unit closed.

        Deliberately **conservative**: the probe only fires from a `running` run that
        holds at least one `work_unit` row and zero open ones (`pending` or `leased`).
        The unit-existence guard keeps a never-enumerated run `running` — a run started
        but not yet enumerated is not complete, it is unpopulated; quarantined units are
        not open (their record stands), so a run whose remainder is quarantined completes
        with that record intact. The probe runs after every won lifecycle write that
        could close the run (a completion, a quarantine, a resume) and is one indexed
        count in the common case.
        """
        rows = cohort.query(ORCH_STATEMENTS["select_run"], run_id=run_id)
        if not rows or rows[0]["status"] != "running":
            return
        if not cohort.query(
            ORCH_STATEMENTS["select_any_work_unit"], run_id=run_id
        ):
            return
        if cohort.query(
            ORCH_STATEMENTS["select_run_open_units"], run_id=run_id
        )[0]["n"]:
            return
        self._transition_run(
            cohort,
            run_id,
            to_status="complete",
            pause_reason=None,
            completed_at=_now(),
            from_status="running",
        )

    # -- the cost seam (FR-ORCH-15) --------------------------------------------------------------

    def _run_ceiling(self, run_row: Any) -> Decimal | None:
        """The cost ceiling the run **froze** at creation, or None.

        Read from the run row's frozen `provider_config` — never from the current
        environment (`FR-CONF-07`'s freeze: a ceiling changed mid-run would let spend
        outpace the number the operator approved). Malformed JSON or a non-numeric
        ceiling is a named `WorkLedgerError`, not a guessed absence: a ceiling the
        orchestrator cannot read must stop scheduling loudly, never silently uncap the
        run.
        """
        raw = run_row["provider_config"]
        try:
            cfg = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise WorkLedgerError(
                f"run {run_row['run_id'][:12]} carries malformed provider_config — "
                "the frozen ceiling cannot be read, and an unreadable ceiling must "
                "halt scheduling loudly rather than silently uncap the run."
            ) from exc
        value = cfg.get("cost_ceiling") if isinstance(cfg, dict) else None
        if value is None:
            return None
        try:
            ceiling = Decimal(str(value))
        except InvalidOperation as exc:
            raise WorkLedgerError(
                f"run {run_row['run_id'][:12]} froze a non-numeric cost ceiling "
                f"{value!r} — refused: the ceiling is the boundary spend may not "
                "cross, and an unparseable boundary is not a boundary."
            ) from exc
        if ceiling < 0:
            raise WorkLedgerError(
                f"run {run_row['run_id'][:12]} froze a negative cost ceiling "
                f"{ceiling} — refused: a negative boundary would pause the run on "
                "its first measured unit, which is a misconfiguration, not a spend."
            )
        return ceiling

    def _normalize_figure(self, answer: Any, run_id: str) -> Decimal | None:
        """One provider answer → the Decimal the ledger accrues, or None (not billed).

        The seam's declared protocol: `estimate_cost(unit) -> Decimal | CostEstimate`. A
        bare `Decimal` is the figure; a `CostEstimate`-shaped answer contributes its
        `.cost`. None means *not billed* (`CT-PROV-03`: a zero would read as a measured
        price — not-billed adds nothing to the accrual and consumes no ceiling, which is
        how replayed work passes a ceiling honestly). A negative figure is refused: it
        would move spend *away* from the ceiling.
        """
        figure = getattr(answer, "cost", answer)
        if figure is None:
            return None
        if not isinstance(figure, Decimal):
            figure = Decimal(str(figure))
        if figure < 0:
            raise WorkLedgerError(
                f"provider estimated a negative cost ({figure}) for a unit of run "
                f"{run_id[:12]} — refused: a negative figure would make spend move "
                "away from the ceiling, which is a ceiling that never trips."
            )
        return figure

    def _cost_figure(self, cohort: Any, unit_row: Any, ceiling: Decimal) -> Decimal:
        """The billed figure one unit adds to its run's spend, before it is dispatched.

        Consults the injected provider seam — **the measured protocol**, never an
        estimated optimism (`FR-PROV-12/04`: the ceiling is enforced from the same
        figures the run is billed against). A run frozen with a ceiling but dispatched
        without a seam raises: a ceiling checked against nothing is the exact shape the
        seam exists to prevent, and halting scheduling honestly is the stated behaviour.
        """
        if self._provider is None:
            raise WorkLedgerError(
                f"run {unit_row['run_id'][:12]} froze a cost ceiling ({ceiling}) but "
                "this orchestrator holds no provider seam to measure units against — "
                "a ceiling checked against nothing is not enforcement. Construct the "
                "Orchestrator with provider=... (estimate_cost) or clear the ceiling."
            )
        figure = self._normalize_figure(
            self._provider.estimate_cost(self._unit_from_row(unit_row)),
            unit_row["run_id"],
        )
        return Decimal("0") if figure is None else figure

    def _run_cost_estimate(self, cohort: Any, run_id: str) -> Decimal | None:
        """The run's estimated cost: the sum of its units' seam figures (`FR-ORCH-15`).

        None when there is no seam (no figure is displayed — a fabricated zero would
        read as a measured price) or nothing is enumerated yet (an empty run's estimate
        is absent, not zero).
        """
        if self._provider is None:
            return None
        rows = cohort.query(
            ORCH_STATEMENTS["select_run_units_for_estimate"], run_id=run_id
        )
        if not rows:
            return None
        total = Decimal("0")
        for unit_row in rows:
            figure = self._normalize_figure(
                self._provider.estimate_cost(self._unit_from_row(unit_row)),
                run_id,
            )
            if figure is not None:
                total += figure
        return total

    @staticmethod
    def _pause_reason_text(cause: BaseException | str | None) -> str:
        """The reason text a pause writes on the run row — always say *why*.

        An operator request (`None`) says so plainly rather than rendering an empty
        string; an exception renders `Type: message` so the operator surface can name
        the condition (`FR-ORCH-16/17`: pause **and alert** — the alert's content is
        this reason); a bare string is taken as given.
        """
        if cause is None:
            return "operator request"
        if isinstance(cause, BaseException):
            return f"{type(cause).__name__}: {cause}"
        return str(cause)

    # -- the lease (FR-ORCH-04) -----------------------------------------------------------------

    def _lease_clock(self) -> LeaseClock:
        """The store's monotonic lease counter, built on this orchestrator's clock.

        Lazily, and cached: `lease_clock()` allows one instance per store, and the first
        caller's clock is the store's clock for its lifetime — a second orchestrator
        injecting a different clock is refused by the store rather than silently ignored,
        which is `CT-STORE-14`'s other half (a second counter would restore past every
        outstanding lease and reclaim work that is genuinely held).
        """
        if self._lease_clock_obj is None:
            self._lease_clock_obj = lease_clock(self._store, self._clock)
        return self._lease_clock_obj

    def _lease_ttl(self) -> int:
        """The lease TTL in seconds, read from the environment at **call** time."""
        return _env_int(LEASE_SECONDS_ENV, ORCH_LEASE_SECONDS)

    def _wall_expiry(self, clock: Any, ttl_seconds: int) -> str:
        """The expiry rendered on the wall clock, for the operator reading the row.

        Recorded beside the ticks, never compared (`LeaseClock`'s own split, `FR-STORE-11`):
        a wall-clock expiry would read every lease live after the host clock moved
        backwards, which is `CT-STORE-14`'s named failure. The comparison input is and
        stays `lease_expires_ticks`.
        """
        return (clock.now() + timedelta(seconds=ttl_seconds)).isoformat()

    def lease(self, worker_id: str, stage: str, n: int) -> Sequence[WorkUnit]:
        """Claim up to `n` pending units of one stage for `worker_id`, exclusively.

        The claim mechanics — the `pending → leased` transition, the expiry derived from
        `M-STORE`'s monotonic counter, the guarded write that makes one claim win — are
        `_claim_pass`'s, stated once there. This surface adds two things over the raw
        pass:

        **Self-healing enumeration.** A first pass that claims nothing triggers the
        base enumeration `resume()` uses — idempotent by construction — but only for
        runs whose ledger holds no units at all **and** whose cohort holds an
        admissible submission (`_runs_missing_units`: a cohort that is all-refused
        enumerates to the empty set legitimately, and a drained poll must not pay
        for re-deriving that), and claims again, so a caller that created a run and
        leased receives units without a separate enumerate step while a drained poll
        late in a large run pays one claim query and one existence probe, never a
        full pass. An empty return after that is a true empty (the stage's units are
        done, in flight, or the run is not dispatching), not a bookkeeping gap.

        **The unit handed over.** The returned units carry `student_ref`;
        `student_name` and `submission_text` stay `None` — the ledger holds neither
        (Tier C carries pseudonymous refs, the text lives in the documents), and
        resolving them is the assembler's act at dispatch, `M-EXTRACT`'s territory.
        #57's WorkUnit docstring expected #58 to resolve them; that expectation is
        hereby reconciled to the schema — the lease resolves the identity, the
        assembler the words.

        Leasing is **at-least-once with an expiry** (`CT-ORCH-04`): an abandoned lease
        returns to `pending` via `sweep_expired_leases()` and the unit is claimed again.
        Workers must therefore be safe to run twice on the same unit — a precondition on
        the worker, not a guarantee from the orchestrator.
        """
        if n <= 0:
            raise WorkLedgerError(
                f"lease(n={n}) claims a positive number of units; {n} claims nothing, "
                "and a call that claims nothing while appearing to work is the "
                "silent-failure shape."
            )
        claimed = self._claim_pass(worker_id, stage, n)
        if not claimed:
            # **The no-bookkeeping rule applied to leasing** (`FR-ORCH-02`): a caller
            # that created a run and leases — without a separate enumerate step — must
            # not silently receive zero units because the base enumeration had not
            # been run. The fallback enumerates only runs whose ledger holds **no
            # units at all** (`_runs_missing_units`) — a run with rows was enumerated,
            # and an empty claim against it is a true empty (every unit done, in
            # flight, or the run not dispatching), not a bookkeeping gap. Re-
            # enumerating on every drained poll would make the hot path a full
            # enumeration pass late in a 23,000-unit run; the gate keeps it one claim
            # query and one existence probe. A ledger partially populated by a crash
            # mid-enumeration has rows and is `resume()`'s repair, not lease's.
            for open_run in self._runs_missing_units():
                self.enumerate_units(open_run)
            claimed = self._claim_pass(worker_id, stage, n)
        return tuple(self._unit_from_row(row) for row in claimed)

    def _claim_pass(self, worker_id: str, stage: str, n: int) -> list[Any]:
        """One claim sweep over every cohort's open runs, up to `n` units.

        Each claim transitions the unit `pending → leased` with the worker as `lease_owner`
        and an expiry `ORCH_LEASE_SECONDS` (env: `HARNESS_ORCH_LEASE_SECONDS`) out, derived
        from `M-STORE`'s **monotonic counter** — the store's `LeaseClock.issue()` persists
        the expiry before the claim commits, so a lease that survives an uncontrolled kill
        still compares honestly after a restart whose wall clock moved backwards
        (`FR-STORE-11`, `CT-STORE-14`).

        **The walk and its order (#59's two-sweep plan).** Cohorts are walked sorted, and
        within a cohort each open run individually — the dispatch order is a function of
        the run's own package (its dependency topology and criteria), so candidates are
        gathered, ordered and claimed per run, in `run_id` order. A paused run schedules
        nothing (`CT-ORCH-12`): its units are never candidates. The stage's order is
        `_dispatch_order`'s: Sweep 1 in topological dependency order (`FR-ORCH-05`),
        Sweep 2 gated on done extraction and then keyed judge → question → criterion
        (`FR-ORCH-06/07`); every other stage keeps `work_id` order. The claim applies the
        order front to back, so the units a claim hands out are the sweep's head.

        **Exclusivity is the guard on the write**, not the read: candidates are read
        `status = 'pending'`, the expiry is issued, and the claim is an
        `UPDATE ... WHERE status = 'pending'` whose `changes()` — read in the same
        transaction — decides whether *this* claim won. A claim that loses the guard
        writes nothing and returns nothing; the unit's new holder is whoever won. The
        lost-guard race leaves the persisted high-water raised by one unused expiry —
        the store's own stated conservatism (a restart expires every outstanding lease,
        `CT-STORE-14`), arrived at from the harmless side: a raised counter can only make
        the sweeper *more* willing to reclaim, never less.

        **The order cache** (`NFR-ORCH-01`). The sweep key is not expressible in SQL —
        it reads the run's package topology and panel — so the ordered candidates are
        derived in Python, and deriving them per poll made a one-at-a-time drain
        quadratic (re-reading and re-sorting the whole pending set per claim: measured
        5.3 ms/unit at 750 pending, over budget, and growing). The ordered ready list
        is therefore cached per `(run_id, stage)` and drained front to back across
        passes; the guard on the write stays the only correctness check. The cache's
        invalidation set is exactly the events that can falsify it:

        - **Exhaustion** — the remaining candidates were claimed; new units (a later
          enumeration) are discoverable only from the ledger, so the entry is dropped
          and the next pass re-reads.
        - **A lost guard** — another writer won a unit this cache held pending, so
          the view of pending is stale; the entry is dropped wholesale.
        - **A requeue** — a failure below the ceiling (`fail`) or a sweeper reclaim
          returns a unit this cache has already popped to `pending`; the run's entries
          are dropped so the next pass re-reads — a requeue the cached order cannot
          see is a unit lost to the run (`TC-ORCH-18`).
        - **A budget deferral** (`FR-ORCH-14`) — an escalation unit the dispatch gate
          deferred was skipped mid-pass; the entry is dropped so the next pass
          re-derives with the current observed rate. Unlike the Sweep 2 gate, this
          gate's answer can move both ways (completions raise the rate, growth lowers
          it), so a deferral the cached order could not revisit would be a deferral
          that never lifts — the provisional remainder must stay recoverable.
        - **Re-enumeration** — `enumerate_units` drops the run's entries, because it
          may add rows this cache has never seen.

        An empty order is never cached: readiness only grows, but it grows outside
        the cache's view, so a stage whose candidates are all gated out re-derives
        per pass — caching the empty list would starve the newly ready. What the
        cache deliberately does **not** re-check per pass is the Sweep 2 gate: the
        gate was evaluated at derivation, and a unit ready then stays ready (an
        extraction's `done` is terminal within a run), so serving the cached order
        can never dispatch a judge over absent evidence; only the not-yet-ready set
        can change, and those units are not in the cache at all.
        """
        ttl = self._lease_ttl()
        lease_clock_obj = self._lease_clock()
        claimed: list[Any] = []
        for key in self._cohort_keys():
            if len(claimed) >= n:
                break
            cohort = self._store.cohort(key)
            for run_row in cohort.query(ORCH_STATEMENTS["select_open_runs"]):
                if len(claimed) >= n:
                    break
                if run_row["status"] not in ("pending", "running"):
                    continue
                # **The control-row read** (`CT-ORCH-13`): the claim pass is the
                # orchestrator's own schedule's heartbeat, so this is where a control
                # row written while nobody was dispatching is honoured. A pause applied
                # here (a `running` run flips to `paused`) schedules nothing, exactly
                # like a pause sensed at the ceiling; a pause still queued on a
                # `pending` run gates dispatch below — a stop someone asked for is not
                # raced past, and `start` will honour it.
                status_now, queued_pause = self._apply_control_rows(
                    cohort, run_row["run_id"]
                )
                if (
                    status_now not in ("pending", "running")
                    or queued_pause is not None
                ):
                    continue
                # The **frozen ceiling** (`FR-ORCH-15`, `FR-CONF-07`): parsed once per
                # run per pass from the run row's `provider_config` — never from the
                # current environment. None means no ceiling: the seam is never
                # consulted and spend is never accrued for a run that froze no budget.
                ceiling = self._run_ceiling(run_row)
                # The **dropped judges** (`RES-13`): read from the run row itself,
                # once per run per pass — the frozen panel minus the recorded one.
                dropped_judges = self._dropped_judges(run_row)
                cache_key = (run_row["run_id"], stage)
                ordered = self._order_cache.get(cache_key)
                if ordered is None:
                    candidates = cohort.query(
                        ORCH_STATEMENTS["select_run_claimable"],
                        run_id=run_row["run_id"],
                        stage=stage,
                    )
                    if not candidates:
                        continue
                    ordered = deque(
                        self._dispatch_order(run_row, stage, candidates, cohort)
                    )
                    if not ordered:
                        # Every candidate was gated out (Sweep 2 waiting on
                        # extraction). Readiness only grows, but it grows outside
                        # this cache's view, so an empty order is re-derived per
                        # pass — caching it would starve the newly ready.
                        continue
                    self._order_cache[cache_key] = ordered
                # The budget's dispatch gate (`FR-ORCH-14`): read once per run per
                # pass — the observed rate moves only on completions, which happen
                # outside claim passes, so one admission decision covers the pass.
                escalation_admission: frozenset | None = None
                # The **dispatch state** (`#62`): the per-run governor, residency and
                # OOM bookkeeping, created lazily the first time any claim walk —
                # the dispatch pass's or a worker's — reaches the run. The residency
                # gate below is the only in-walk consumer; the dispatch pass's
                # counters and the completion report ride the same dict.
                edge_residency = (
                    stage == STAGE_SCORE
                    and run_row["backend_profile"] == BACKEND_EDGE_LOCAL
                )
                state = self._dispatch_state(run_row)
                residency = state["residency"]
                run_claims = 0
                while ordered and len(claimed) < n:
                    row = ordered.popleft()
                    if (
                        stage == STAGE_SCORE
                        and row["origin"] == "escalation"
                    ):
                        if escalation_admission is None:
                            escalation_admission = (
                                self._escalation_dispatch_admission(
                                    cohort, run_row["run_id"]
                                )
                            )
                        if (row["submission_id"], row["criterion_id"]) not in (
                            escalation_admission
                        ):
                            # Above budget, this pair's escalation is part of the
                            # provisional remainder: the unit stays pending — never
                            # claimed, never dropped — and the cache entry goes so
                            # the NEXT pass re-derives with the current rate. A
                            # deferral the cached order could not revisit would be
                            # a deferral that never lifts.
                            self._order_cache.pop(cache_key, None)
                            continue
                    if row["judge_id"] in dropped_judges:
                        # **A dropped judge's un-run units stay in the ledger**
                        # (`RES-13`): pending, never claimed, never discarded — for
                        # an operator to re-queue under the smaller panel. The skip
                        # reads the run row's OWN panels (frozen minus recorded,
                        # `_dropped_judges`), so it is durable: a fresh
                        # Orchestrator over the same store skips the same units the
                        # recording one did, where an in-memory dropped set would
                        # have re-dispatched them after a restart (#62 review
                        # finding 1). Extract and deterministic rows carry a null
                        # judge, which no drop set contains.
                        continue
                    if edge_residency:
                        # **The residency boundary** (`FR-ORCH-19`). On an edge-local
                        # run the box holds ONE judge model resident, so a score
                        # handout never mixes models. The gate reads the walk's own
                        # judge-major order: crossing into a judge that is not the
                        # resident one is the unload/load boundary, and it is legal
                        # only when the resident's **batch** is finished — no more
                        # dispatchable work this walk (`run_claims == 0`: the ready
                        # order held nothing more for it) and none of its units in
                        # flight. Gated or budget-deferred pending units are not
                        # dispatchable — they are not in this order and may never
                        # become ready without an operator — so they cannot hold a
                        # model resident; a residency held over undispatchable work
                        # starves every other judge behind it (their handouts refuse
                        # empty while the ledger still holds claimable units, the
                        # stall shape). When gated work does become ready, the walk
                        # reaches the resident again and the model reloads — a swap —
                        # to serve it. The FIRST model of a run loads without a
                        # swap: there is nothing to unload yet.
                        resident = residency["resident"]
                        if resident in dropped_judges:
                            # The OOM remedy unloaded this judge (`RES-13`): it is
                            # out of the panel, so the next model loads as an
                            # initial load — the drop already paid the unload.
                            residency["resident"] = None
                            resident = None
                        if row["judge_id"] != resident:
                            if resident is None:
                                residency["resident"] = row["judge_id"]
                            elif (
                                run_claims == 0
                                and not cohort.query(
                                    ORCH_STATEMENTS["select_judge_leased_units"],
                                    run_id=run_row["run_id"],
                                    judge_id=resident,
                                )[0]["n"]
                            ):
                                # A clean boundary: nothing claimed yet this walk
                                # and the resident's work is finished — record the
                                # swap and load the next model in place. The swap's
                                # duration is the wall time to the batch's first
                                # model call (the load rides that call), timed
                                # from here by the dispatch pass.
                                residency["swaps"] += 1
                                residency["swap_started"] = time.monotonic()
                                residency["resident"] = row["judge_id"]
                            else:
                                # Mid-batch crossing (this pass already claimed
                                # the resident's tail) or the resident still holds
                                # open work: the boundary row goes back and the
                                # walk stops — this handout stays single-model,
                                # and the next pass re-derives from the ledger.
                                ordered.appendleft(row)
                                self._order_cache.pop(cache_key, None)
                                break
                    # The **measured figure** (`FR-ORCH-15`, `FR-PROV-12/04`): before
                    # the claim, this unit's cost comes from the provider seam — the
                    # same measured protocol the run is billed against, never an
                    # estimated optimism. Outside the transaction: the seam may be a
                    # real transport, and no egress belongs inside a ledger write.
                    figure: Decimal | None = None
                    if ceiling is not None:
                        figure = self._cost_figure(cohort, row, ceiling)
                    issued = lease_clock_obj.issue(ttl)
                    expires_at = self._wall_expiry(lease_clock_obj.clock, ttl)
                    refused = False
                    at_ceiling = False
                    won = False
                    with cohort.transaction() as tx:
                        if figure is not None:
                            spend = Decimal(
                                tx.execute(
                                    ORCH_STATEMENTS["select_run"],
                                    run_id=row["run_id"],
                                )[0]["cost_spend"]
                                or "0"
                            )
                            if spend + figure > ceiling:
                                # **The crossing dispatch is refused** (strict `>`,
                                # the breaker's and budget's reading): the unit stays
                                # pending — never claimed, never dropped — and the run
                                # pauses **in this transaction**, naming the spend and
                                # the remaining unit count (`FR-ORCH-15`'s operator
                                # surface; `CT-ORCH-12`'s ceiling condition). A pause
                                # that said only THAT it stopped could not be told
                                # from a crash.
                                remaining = tx.execute(
                                    ORCH_STATEMENTS["count_run_pending"],
                                    run_id=row["run_id"],
                                )[0]["n"]
                                tx.execute(
                                    ORCH_STATEMENTS["pause_run_sensed"],
                                    run_id=row["run_id"],
                                    pause_reason=(
                                        f"cost ceiling reached: spend "
                                        f"{spend} of ceiling {ceiling}; next "
                                        f"dispatch would reach {spend + figure}; "
                                        f"{remaining} unit(s) remaining"
                                    ),
                                )
                                refused = True
                        if not refused:
                            tx.execute(
                                ORCH_STATEMENTS["mark_leased"],
                                work_id=row["work_id"],
                                owner=worker_id,
                                expires_ticks=issued.expires_ticks,
                                expires_at=expires_at,
                            )
                            won = int(
                                tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"]
                            )
                            if won and figure is not None:
                                # The accrual rides the **same transaction** as the
                                # claim (`FR-ORCH-15`): spend and the unit's lease
                                # commit together, so no crash between them can
                                # dispatch work the ceiling never saw, and no accrual
                                # can outlive a claim that lost its guard.
                                new_spend = spend + figure
                                tx.execute(
                                    ORCH_STATEMENTS["accrue_run_spend"],
                                    run_id=row["run_id"],
                                    cost_spend=str(new_spend),
                                )
                                if figure > 0 and new_spend >= ceiling:
                                    # Spend now sits **at** the ceiling: the run
                                    # pauses in the same transaction — the dispatch
                                    # that landed it there proceeded (strict `>`), and
                                    # the next BILLED one would cross. A not-billed
                                    # figure (`None` → 0) adds nothing and consumes no
                                    # ceiling — that is how replayed work passes a
                                    # ceiling honestly (`_normalize_figure`) — so a
                                    # zero accrual must not re-fire this arm: a
                                    # resumed ceiling-paused run would otherwise
                                    # re-pause on every replay claim, one operator
                                    # resume per unit, never draining. The refusal
                                    # arm above already covers any future crossing
                                    # dispatch, billed or not.
                                    remaining = tx.execute(
                                        ORCH_STATEMENTS["count_run_pending"],
                                        run_id=row["run_id"],
                                    )[0]["n"]
                                    tx.execute(
                                        ORCH_STATEMENTS["pause_run_sensed"],
                                        run_id=row["run_id"],
                                        pause_reason=(
                                            f"cost ceiling reached: spend "
                                            f"{new_spend} of ceiling {ceiling}; "
                                            f"{remaining} unit(s) remaining"
                                        ),
                                    )
                                    at_ceiling = True
                    if won:
                        claimed.append(row)
                        run_claims += 1
                    if refused or at_ceiling or not won:
                        # The run paused mid-order (sensed ceiling) or the guarded
                        # write lost (stale view): drop the entry wholesale — the next
                        # pass re-derives from the ledger, which now holds the pause.
                        self._order_cache.pop(cache_key, None)
                        break
                if not ordered:
                    # Exhausted: the remaining candidates were all claimed. Drop the
                    # entry so the next pass re-reads — new units (enumeration, the
                    # sweeper's requeue) can only be discovered from the ledger.
                    self._order_cache.pop(cache_key, None)
        return claimed

    def _dispatch_order(
        self, run_row: Any, stage: str, rows: Sequence[Any], cohort: Any
    ) -> list[Any]:
        """The candidates of one run's stage, in the order they may be handed out.

        `Sweep 1` (`extract`) is **topological order over the criterion dependency
        graph** (`FR-ORCH-05`) — a priority order over pending units, not a completion
        gate: the design dispatches extraction in dependency order, and nothing in it
        says a criterion's extraction waits for another's to finish. `Sweep 2`
        (`score`) first **gates** (`FR-ORCH-06`) — a score unit is ready only when its
        own criterion's extraction and every extraction in its dependency closure, for
        its submission, are `done` — and then **orders by the fixed key and nothing
        else** (`FR-ORCH-07`): judge model outermost, then question, then criterion, the
        submissions parallel beneath. No criterion-graph term appears in the key; the
        graph was Sweep 1's, and re-ordering scoring by it would cost cache locality for
        nothing. Every other stage (the deterministic units, and the stages later stories
        add) keeps `work_id` order.

        The gate reads `done` on the extraction units of the run — one indexed query per
        pass (`select_not_done_extracts`); a quarantined extraction is not `done`, so the
        scoring it feeds stays gated until an operator re-queues it: the gate never
        scores over nothing. Deterministic criteria carry no extraction unit, so a
        dependency on one is satisfied vacuously — there is nothing to wait for.

        **Interpretations recorded (#59):** the gate is per (criterion, submission) — a
        score unit reads that submission's evidence — and it includes the criterion's own
        extraction plus the transitive closure of its dependencies; the requirement's
        "every extraction unit that criterion depends on" leaves direct-vs-transitive and
        own-extraction open (`TC-ORCH-07` discloses the same), and this reading is the
        one under which no judge ever reads absent evidence. Within a `(judge, question,
        criterion)` group the submission order is `work_id`'s — `CT-ORCH-21` explicitly
        does not promise submission order inside a batch. The key's judge term is the
        judge's position in the run's panel order (the dispatch order, not the build
        id's lexical order), and its criterion term is the criterion id ascending;
        `FR-ORCH-07` fixes the levels, not the within-level measure, and these are the
        stable choices.
        """
        if stage not in (STAGE_EXTRACT, STAGE_SCORE):
            return list(rows)
        plan = self._sweep_plan(run_row)
        if stage == STAGE_EXTRACT:
            return sorted(
                rows,
                key=lambda r: (
                    _known_key(plan.extract_positions.get(r["criterion_id"])),
                    r["criterion_id"] or "",
                    r["work_id"],
                ),
            )
        blocked = {
            (r["criterion_id"], r["submission_id"])
            for r in cohort.query(
                ORCH_STATEMENTS["select_not_done_extracts"],
                run_id=run_row["run_id"],
            )
        }
        arms = self._panel_arms(run_row["panel_config"])
        # `FR-ORCH-30`: with an executor bound — a run driven by `M-PIPE` — a score unit also
        # waits for its cell's `integrity_pre` phase, so no panel scores a cell whose
        # extraction the integrity gate has not passed on. ONLY with an executor bound: the
        # report-only path and the `transport=` test path record no phases, and gating them
        # would make every score unit unclaimable forever.
        gated = (
            self._cells_with_integrity_pre(cohort, run_row["run_id"])
            if self._executor is not None
            else None
        )
        ready = [
            r for r in rows
            if self._score_dependencies_done(r, blocked, plan)
            and (gated is None
                 or (str(r["submission_id"]), str(r["criterion_id"])) in gated)
        ]
        return sorted(
            ready,
            key=lambda r: (
                self._judge_key(r["judge_id"], arms),
                _known_key(plan.question_of.get(r["criterion_id"])),
                r["criterion_id"] or "",
                r["work_id"],
            ),
        )

    @staticmethod
    def _score_dependencies_done(
        row: Any, blocked: set[tuple[str, str]], plan: SweepPlan
    ) -> bool:
        """Whether one score unit's extraction evidence is all `done` (`FR-ORCH-06`)."""
        if (row["criterion_id"], row["submission_id"]) in blocked:
            return False
        closure = plan.dependency_closure.get(row["criterion_id"], frozenset())
        return all(
            (dep, row["submission_id"]) not in blocked for dep in closure
        )

    @staticmethod
    def _judge_key(judge_id: str | None, arms: Sequence[str]) -> tuple[int, int | str]:
        """`FR-ORCH-07`'s outermost key: the judge's position in the run's panel.

        Panel order, not the build id's lexical order — the panel order is the dispatch
        order and the escalation ladder's first arm (`panel_config_json`), and the fixed
        cross-profile key reads the same on every backend (`TC-ORCH-08`'s arm-index
        oracle). A judge outside the panel (later stories' escalation arms) sorts after
        every panel judge, deterministically. A score unit without a judge is a ledger
        this module did not write, and ordering it anywhere would dispatch judgeless
        work to a judge — refused, not absorbed.
        """
        if judge_id is None:
            raise WorkLedgerError(
                "a 'score' unit without a judge reached the dispatch order — the base "
                "enumeration gives every score unit a panel arm, so the row is not this "
                "module's. Order it by hand only after deciding what judgeless scoring "
                "means; the orchestrator refuses to guess."
            )
        # The index compares as the **integer** it is, never stringified: at ten or
        # more arms a lexical compare would order `arm-10` before `arm-2` and break
        # the panel's own ladder. The two branches never compare second elements
        # across the branch boundary — the leading 0/1 decides first — so an
        # in-panel int and an out-of-panel str can never meet in a comparison.
        return (0, arms.index(judge_id)) if judge_id in arms else (1, judge_id)

    def _sweep_plan(self, run_row: Any) -> SweepPlan:
        """The dispatch-order data for the run's package version, derived once.

        Pure functions of the immutable version: the topological order comes from
        `M-PKG` (`FR-PKG-05`, consumed rather than re-derived), the question map from the
        version's criteria, the closure from the version's dependency graph. Cached per
        version on the orchestrator, so a claim pass pays the derivation once per run
        lifetime, never per unit (`NFR-ORCH-01`).
        """
        version = run_row["package_version_id"]
        plan = self._sweep_plans.get(version)
        if plan is None:
            catalog = self._catalog(run_row)
            order = catalog.topological_order(version)
            positions = {criterion_id: i for i, criterion_id in enumerate(order)}
            question_of = {
                c["criterion_id"]: c["question_id"]
                for c in catalog.criteria(version)
            }
            plan = SweepPlan(
                extract_positions=positions,
                question_of=question_of,
                dependency_closure=_dependency_closure(
                    catalog.dependency_graph(version)
                ),
            )
            self._sweep_plans[version] = plan
        return plan

    def heartbeat(self, work_id: str, owner: str | None = None) -> None:
        """Extend a live lease by another TTL — the while-it-works half of `FR-ORCH-04`.

        A slow-but-alive worker must not lose its unit at the original expiry: the
        heartbeat re-issues the lease from **now**, so the expiry moves out by a full
        TTL from the moment of the call. The re-issue goes through `LeaseClock.issue()`
        like every claim, so the persisted counter moves with it and the extension
        survives an uncontrolled kill.

        `owner` names the calling worker and is checked against `lease_owner` — a
        heartbeat naming its worker cannot extend a lease another worker holds, which
        is the double-run `CT-ORCH-04` warns of from the other side. Unnamed
        heartbeats (the assumed test surface) extend whoever holds the lease; passing
        the worker id is the recommended form and the only one a multi-worker ledger
        should rely on.

        Refusals are named, never absorbed: a unit that is not `leased` (the sweeper
        requeued it, another worker completed it), is held by a different named worker,
        or does not exist raises `WorkLedgerError` — and the guard's `changes()` read
        catches the race where the lease was lost **between** the read and the write,
        so a heartbeat cannot succeed without having extended anything.
        """
        ttl = self._lease_ttl()
        lease_clock_obj = self._lease_clock()
        issued = lease_clock_obj.issue(ttl)
        expires_at = self._wall_expiry(lease_clock_obj.clock, ttl)
        cohort, row = self._find_unit(work_id)
        if row["status"] != "leased":
            raise WorkLedgerError(
                f"heartbeat for unit {work_id[:12]} refused: the unit is "
                f"'{row['status']}', not 'leased' — the lease was lost while this "
                "worker held it, and extending a lease that returned to pending would "
                "double-claim work another worker may already hold."
            )
        if owner is not None and row["lease_owner"] != owner:
            raise WorkLedgerError(
                f"heartbeat for unit {work_id[:12]} refused: 'lease_owner' names "
                f"{row['lease_owner']!r}, not {owner!r} — extending another worker's "
                "live lease would let two workers run one unit."
            )
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["extend_lease"],
                work_id=work_id,
                owner=owner,
                expires_ticks=issued.expires_ticks,
                expires_at=expires_at,
            )
            won = int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"])
        if not won:
            raise WorkLedgerError(
                f"heartbeat for unit {work_id[:12]} could not be applied: the lease "
                f"was lost between the read ('{row['status']}') and the write — the "
                "sweeper requeued it or the unit moved underneath this worker. "
                "Re-lease before continuing; a heartbeat that succeeds without "
                "extending anything is the silent no-op this method exists to refuse."
            )

    def sweep_expired_leases(self) -> SweeperReport:
        """Return every lease whose expiry has passed to `pending`, and report the sweep.

        The comparison is `ticks >= lease_expires_ticks` on the store's **monotonic
        counter** — the same inequality `LeaseClock.expired()` states — and never the
        wall clock (`FR-STORE-11`): the host clock moving backwards across a restart
        changes nothing the sweeper reads. A leased row carrying no expiry is a ledger
        that cannot be swept honestly, so it raises rather than being skipped or
        treated as expired — both arms of that guess would be silent-failure shapes.

        Requeued units clear their lease columns and keep their `attempts`: the failure
        history belongs to the unit, the lease to the moment. The report is the sweep's
        stage-level detail (`CLAUDE.md` seam 4) — examined, requeued, still held — so a
        sweep over an empty ledger is visible as zero, not as absence.
        """
        lease_clock_obj = self._lease_clock()
        now_ticks = lease_clock_obj.ticks()
        gates: dict[str, str] = {
            "lease_clock": f"monotonic ticks at sweep: {now_ticks:.3f} (FR-STORE-11)",
        }
        examined = 0
        requeued = 0
        requeued_runs: set[str] = set()
        for key in self._cohort_keys():
            cohort = self._store.cohort(key)
            rows = cohort.query(ORCH_STATEMENTS["select_leased_units"])
            run_by_work = {row["work_id"]: row["run_id"] for row in rows}
            expired: list[str] = []
            for row in rows:
                ticks = row["lease_expires_ticks"]
                if ticks is None:
                    raise WorkLedgerError(
                        f"leased unit {row['work_id'][:12]} carries no expiry ticks, "
                        "so the sweeper can neither hold nor reclaim it honestly — "
                        "a lease is written with its expiry or not at all."
                    )
                if now_ticks >= float(ticks):
                    expired.append(row["work_id"])
            if expired:
                with cohort.transaction() as tx:
                    for work_id in expired:
                        tx.execute(
                            ORCH_STATEMENTS["requeue_expired"], work_id=work_id
                        )
                        won = int(
                            tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"]
                        )
                        requeued += won
                        if won:
                            requeued_runs.add(run_by_work[work_id])
            examined += len(rows)
        # A reclaim returns units to `pending` — drop the affected runs' dispatch-order
        # cache entries so the next claim pass sees them (the same visibility rule as
        # `fail`'s requeue, `TC-ORCH-18`).
        for run_id in requeued_runs:
            self._invalidate_order_cache(run_id)
        gates["sweep"] = (
            f"{examined} leased examined, {requeued} requeued, "
            f"{examined - requeued} still held"
        )
        return SweeperReport(
            examined=examined,
            requeued=requeued,
            still_held=examined - requeued,
            gates=gates,
        )

    # -- the failure taxonomy (FR-ORCH-18) ------------------------------------------------------

    def complete(self, work_id: str, result: WorkResult | None = None) -> None:
        """Record a unit's completion: `leased → done`, lease columns cleared.

        Idempotent (`CT-ORCH-03`): a completion recorded twice leaves one `done` row.
        A completion arriving after the sweeper requeued the unit still lands —
        at-least-once leasing means a reclaim may double-run a unit, and the worker
        that actually finished is recording a real result; the second worker's own
        completion is then the no-op. A completion for a `quarantined` unit is refused
        with a named error: three failures were recorded, and quietly accepting a
        result underneath that record would un-quarantine by side effect — the
        operator surface said what happened, and it must stay true. The guard's
        `changes()` read catches the race where the unit was quarantined **between**
        the read and the write — the silent version of the same refusal. `result` is
        the worker's `WorkResult`; the ledger records the transition, the payload is
        the owning stage's to persist (#68 onward).
        """
        cohort, row = self._find_unit(work_id)
        if row["status"] == "done":
            return
        if row["status"] not in ("leased", "pending"):
            raise WorkLedgerError(
                f"completion for unit {work_id[:12]} refused: the unit is "
                f"'{row['status']}' — a quarantined unit keeps its record until an "
                "operator re-queues it; a result does not arrive underneath it."
            )
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["mark_done"],
                work_id=work_id,
                done_ticks=self._lease_clock().ticks(),
            )
            won = int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"])
        if not won:
            raise WorkLedgerError(
                f"completion for unit {work_id[:12]} could not be recorded: the "
                f"unit's state moved from '{row['status']}' between the read and the "
                "write — a failure report quarantined it mid-flight. The ledger's "
                "record stands; re-read it before reporting again."
            )
        # The last open unit closed — probe the run (`FR-ORCH-25`'s running → complete;
        # the probe is self-guarding and a no-op unless this really was the last).
        self._maybe_complete_run(cohort, row["run_id"])

    def fail(self, work_id: str, error: WorkError | str) -> None:
        """Count one failed attempt against a unit; requeue it, or quarantine it at the
        ceiling (`FR-ORCH-18`).

        The unit's `attempts` increments; below `ORCH_MAX_ATTEMPTS`
        (env: `HARNESS_ORCH_MAX_ATTEMPTS`) it returns to `pending` and is claimable
        again; at the ceiling it becomes `quarantined` with `last_error` retained —
        the operator surface can say *what* happened, not just that something did. Both
        arms clear the lease columns; the run continues either way — "fail the unit,
        never the run" (`NFR-ORCH-03`) is the whole point of the taxonomy, so **no arm
        of this method raises into the caller's loop over a unit's own failure**: the
        only raise is for a work id that resolves to no unit at all. A won report also
        drops this run's dispatch-order cache entries — the requeued unit must be
        visible to the very next claim pass (`TC-ORCH-18`).

        **A failure report wins over a live lease.** The design fixes this signature at
        `(work_id, error)` — no owner identity — so the report cannot name its holder,
        and the ledger treats it as authoritative about the attempt: the unit requeues
        (or quarantines) and its lease columns clear even if another worker currently
        shows as holding them. At-least-once leasing makes the holder tolerate losing
        the claim; its own next heartbeat is a named refusal (the guard catches it), so
        the stale holder cannot keep working silently.

        Races are absorbed by the ledger's state at write time, not raised: a failure
        for a unit that completed (a completion beat this report — under
        `CT-ORCH-04`'s at-least-once that is an expected outcome, and the real result
        exists), one already quarantined (the record stands; a duplicate report from a
        double-run worker must not double-count it), or one whose state moved between
        the read and the guarded write — all no-ops. The count and the ceiling
        comparison are computed **inside the statement** from the row as the write sees
        it, so two concurrent reports cannot both read the same count and lose an
        attempt; quarantine lands on the report that actually reaches the ceiling.
        """
        max_attempts = _env_int(MAX_ATTEMPTS_ENV, ORCH_MAX_ATTEMPTS)
        message = error.message if isinstance(error, WorkError) else str(error)
        cohort, row = self._find_unit(work_id)
        if row["status"] in ("quarantined", "done"):
            return
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["record_failure"],
                work_id=work_id,
                max_attempts=max_attempts,
                last_error=message,
            )
            won = int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"])
        if not won:
            # The unit moved underneath the report (reclaimed, completed, quarantined
            # by a concurrent holder). The ledger's state at write time wins; raising
            # here would fail a run over a unit-level race, which is the one thing
            # this taxonomy refuses to do (NFR-ORCH-03).
            return
        # A won report moved the unit within the claimable set — back to `pending`
        # below the ceiling, out of it at quarantine — so this run's cached dispatch
        # order is stale: the requeued unit must be visible to the very next claim
        # pass, or a requeue the dispatcher cannot see is a unit lost to the run
        # (`TC-ORCH-18`).
        self._invalidate_order_cache(row["run_id"])
        # Quarantine can close a run: a unit at its attempt ceiling leaves the open
        # set (its record stands), and if it was the last open one the run is complete
        # (`FR-ORCH-25`; the probe is self-guarding).
        self._maybe_complete_run(cohort, row["run_id"])

    # -- escalation, the breakers and the budget (FR-ORCH-09/10/13/14, FR-ORCH-26) --------------

    def enqueue_escalation(
        self,
        tx: Any,
        criterion_score_key: Sequence[str],
        judges: Sequence[str] | None = None,
        *,
        expected_value: float | None = None,
    ) -> tuple[EscalationReport, ...]:
        """Widen one (submission, criterion) panel — the escalation path M-AGG walks
        when a verdict lands outside its band (`FR-ORCH-09/10`, §7.1), in the design's
        own form (`CT-ORCH-08`): **the caller's transaction first**, the criterion
        score key second — the ``(run_id, submission_id, criterion_id)`` triple, the
        way `criterion_score` names its rows (#359, `FR-ORCH-34`) — and the judges to
        ADD third. The shape is
        the requirement, not a convenience: a run's score result for a criterion and
        the escalation that widens that criterion's panel are one logical step, *both
        present or both absent after any crash* is `CT-STORE-03`'s atomicity clause
        read across the boundary — so the widened units are written into the
        transaction the CALLER opened and commits (or aborts) with its verdict. This
        method never commits and never rolls back the transaction it is handed, and it
        never opens one of its own: a caller with no transaction of its own wraps the
        call in `cohort.transaction()` — the same discipline every other ledger writer
        follows.

        **The key names its run** (`FR-ORCH-34`, `CT-ORCH-26`): the escalation widens
        that run's panel only, and the one-element tuple returned is that run's report.
        The two-element ``(submission_id, criterion_id)`` form is **deprecated**: it
        resolves the run from the ledger only when exactly one open run holds the
        pair's score units, and raises `WorkLedgerError` — before anything is written
        — when none or two or more do. A run whose base units all completed has
        auto-completed (`_maybe_complete_run`), so a caller escalating it names the
        run with the three-element key. A key no run holds a panel for raises
        `EscalationPlanError` before anything is written.

        **The decision, in order** (each stage reported in `gates` — seam 4):

        1. *Plan.* The pair's prior judges are the score units the ledger enumerates
           for it — any origin, any status: the panel IS the enumerated units, not the
           verdicts landed so far. `escalation_plan` widens 1→3, 3→5 (never to two,
           `FR-ORCH-10`; `validate_escalation_plan` is the rule's pure surface) —
           with caller-named judges exactly, or the ladder's next two arms when
           `judges` is None. A plan that is not a widening, produces an even
           `judge_count`, or names a judge twice raises before anything is written
           (`EvenEscalationPlanError` is the subclass `TC-ORCH-20` asserts).
        2. *Idempotence.* A pair already carrying escalation-origin units is a no-op
           (`admitted`, zero units): the widened panel exists, whatever path built it
           — including a random-arm draw, whose units are the SAME rows this path
           would insert (origin is not a `work_id` input, `CT-ORCH-15`), so a retried
           enqueue inserts nothing and reports honestly.
        3. *Criterion breaker* (`FR-ORCH-13`). A latched breaker for the criterion
           halts immediately (`halted_by_breaker`); otherwise the first
           `ORCH_CRITERION_BREAKER_MIN_N` submissions processed for the criterion —
           by completion tick, the ledger's honest ordering — are checked with
           `criterion_breaker_tripped`, and a trip latches a content-addressed
           breaker row (INSERT OR IGNORE: one trip, one event) whose detail names the
           mark the design requires — `un-gradeable_by_panel`, remainder single-judge
           provisional. The mark on the criterion's RESULT is `M-AGG`'s artifact to
           write; the ledger's breaker row and this report's decision are what tell
           it to. Random-arm units are never counted here (origin='escalation'
           only) — the breaker gates the routing policy, not its control sample.
        4. *The units.* The escalation's units are inserted **unconditionally** — the
           budget rations dispatch, not the plan write. The atomicity clause leaves
           no choice: a budget that refused the insert would put the escalation
           OUTSIDE the verdict's transaction, and a crash between the two would leave
           exactly the partial write `CT-STORE-03` forbids — a verdict recorded, its
           panel never widened. The caller's `expected_value` is recorded on the
           request row (content-addressed, INSERT OR IGNORE) as the ranking key the
           dispatch-time admission consumes.
        5. *The budget, at dispatch* (`FR-ORCH-14`). The claim pass admits pending
           escalation units through `admit_escalations` only while the run's observed
           escalation rate is at or under `ORCH_ESCALATION_BUDGET`; above it the
           units stay pending — the remainder `FR-ORCH-14` marks provisional — and
           dispatch resumes in expected-value order when growth returns headroom.
           `escalation_budget_state` is the operator surface that shows the split;
           nothing here reads the budget, because the decision is dispatch's, not the
           plan write's.

        The inserted units invalidate this run's dispatch-order cache (the claim pass
        must see them). Pure policy — `escalation_plan`, `validate_escalation_plan`,
        `criterion_breaker_tripped`, `admit_escalations` — does every decision here;
        the method only reads the ledger and writes rows, and never contacts a judge
        (`NFR-ORCH-04`: the escalation policy is evaluable with no model call).
        """
        key = tuple(str(part) for part in criterion_score_key)
        if len(key) == 3:
            run_id, submission_id, criterion_id = key
            if not list(tx.execute(
                ORCH_STATEMENTS["select_run_pair_panel"],
                run_id=run_id, submission_id=submission_id, criterion_id=criterion_id,
            )):
                raise EscalationPlanError(
                    f"run {run_id!r}'s ledger holds no score panel for "
                    f"({submission_id!r}, {criterion_id!r}): an escalation widens a panel "
                    "that exists — enumerate the run first (a criterion with no units has "
                    "no band to widen)."
                )
        elif len(key) == 2:
            submission_id, criterion_id = key
            holding = list(tx.execute(
                ORCH_STATEMENTS["select_pair_runs"],
                submission_id=submission_id,
                criterion_id=criterion_id,
            ))
            pair_runs = [r["run_id"] for r in holding if r["is_open"]]
            if not holding:
                raise EscalationPlanError(
                    f"no run's ledger holds a score panel for "
                    f"({submission_id!r}, {criterion_id!r}): an escalation widens a panel "
                    "that exists — enumerate the run first (a criterion with no units has "
                    "no band to widen)."
                )
            if len(pair_runs) != 1:
                raise WorkLedgerError(
                    f"the deprecated (submission_id, criterion_id) escalation key "
                    f"({submission_id!r}, {criterion_id!r}) is ambiguous: {len(pair_runs)} "
                    f"open runs hold the pair ({', '.join(pair_runs)}) — name the run with "
                    "the (run_id, submission_id, criterion_id) key (FR-ORCH-34)."
                )
            (run_id,) = pair_runs
        else:
            raise EscalationPlanError(
                f"criterion_score_key must be the (run_id, submission_id, criterion_id) "
                f"triple, got {key!r} — the key names the escalation's target the way the "
                "criterion_score table does (CT-ORCH-08, FR-ORCH-34)."
            )
        return (
            self._enqueue_escalation_locked(
                tx,
                self._run_row(run_id),
                submission_id=submission_id,
                criterion_id=criterion_id,
                judges=judges,
                expected_value=expected_value,
            ),
        )

    def _enqueue_escalation_locked(
        self,
        tx: Any,
        row: Any,
        *,
        submission_id: str,
        criterion_id: str,
        judges: Sequence[str] | None,
        expected_value: float | None,
    ) -> EscalationReport:
        """The enqueue's decision, run inside a transaction the caller sees.

        Every read and write goes through `tx` — the caller's (`CT-ORCH-08`) or this
        method's own — so the decision is one consistent step against the ledger: the
        budget's counts, the breaker's window and the request row see the same state,
        and `FR-ORCH-09`'s same-transaction guarantee is a parameter, not a promise.
        """
        run_id = row["run_id"]
        arms = self._panel_arms(row["panel_config"])
        budget = _env_float(
            ESCALATION_BUDGET_ENV, ORCH_ESCALATION_BUDGET, low=0.0, high=1.0
        )
        breaker_rate = _env_float(
            CRITERION_BREAKER_RATE_ENV, ORCH_CRITERION_BREAKER_RATE, low=0.0, high=1.0
        )
        breaker_min_n = _env_int(CRITERION_BREAKER_MIN_N_ENV, ORCH_CRITERION_BREAKER_MIN_N)
        gates: dict[str, str] = {}

        # 1. The pair's prior panel — the score units the ledger enumerates for it,
        #    any origin, any status. The plan is validated BEFORE anything else: a
        #    caller asking for a non-widening or even-count escalation has broken the
        #    contract, and the refusal must be loud whatever the routing state is.
        prior = tuple(
            r["judge_id"] for r in tx.execute(
                ORCH_STATEMENTS["select_pair_score_judges"],
                run_id=run_id,
                submission_id=submission_id,
                criterion_id=criterion_id,
            )
        )
        named = None if judges is None else tuple(_judge_id_of(j) for j in judges)
        target = escalation_plan(prior, add_judges=named, panel_arms=arms)
        additions = target[len(prior):]
        gates["plan"] = (
            f"{len(prior)} -> {len(target)} judges (+{', '.join(additions)})"
        )

        # 2. Idempotence: the pair is already escalated — a no-op that reports the
        #    panel it finds. The widened panel exists; that is what `admitted` means.
        if int(tx.execute(
            ORCH_STATEMENTS["select_pair_escalated"],
            run_id=run_id,
            submission_id=submission_id,
            criterion_id=criterion_id,
        )[0]["n"]):
            gates["idempotence"] = (
                "pair already carries escalation-origin units; widened panel stands"
            )
            processed, escalated, rate = self._escalation_rate(tx.execute, run_id)
            return self._escalation_report(
                tx, row, submission_id, criterion_id, DECISION_ADMITTED,
                prior_judges=prior, added_judges=(), judge_count=len(prior),
                units_inserted=0, expected_value=expected_value,
                escalation_rate=rate, processed_results=processed,
                escalated_results=escalated, budget=budget,
                breaker_tripped=False, gates=gates,
            )

        # 3. The criterion breaker (`FR-ORCH-13`): latch first, then the window.
        latch = tx.execute(
            ORCH_STATEMENTS["select_breaker"], run_id=run_id, criterion_id=criterion_id
        )
        if latch:
            gates["breaker"] = f"latched {latch[0]['tripped_at']}: {latch[0]['detail']}"
            processed, escalated, rate = self._escalation_rate(tx.execute, run_id)
            return self._escalation_report(
                tx, row, submission_id, criterion_id, DECISION_HALTED_BY_BREAKER,
                prior_judges=prior, added_judges=(), judge_count=len(prior),
                units_inserted=0, expected_value=expected_value,
                escalation_rate=rate, processed_results=processed,
                escalated_results=escalated, budget=budget,
                breaker_tripped=True, gates=gates,
            )
        window = tx.execute(
            ORCH_STATEMENTS["select_criterion_window"],
            run_id=run_id, criterion_id=criterion_id, n=breaker_min_n,
        )
        window_ids = {r["submission_id"] for r in window}
        escalated_ids = {
            r["submission_id"] for r in tx.execute(
                ORCH_STATEMENTS["select_criterion_escalated"],
                run_id=run_id, criterion_id=criterion_id,
            )
        }
        escalated_in_window = len(window_ids & escalated_ids)
        if criterion_breaker_tripped(
            escalated_in_window,
            len(window_ids),
            rate=breaker_rate,
            min_n=breaker_min_n,
        ):
            detail = (
                f"{escalated_in_window}/{len(window_ids)} of the first "
                f"{breaker_min_n} submissions processed escalated, above "
                f"{breaker_rate:.0%}: escalation halts for {criterion_id} — "
                "un-gradeable_by_panel, remainder single-judge provisional"
            )
            tx.execute(
                ORCH_STATEMENTS["insert_breaker"],
                breaker_id=_content_id(
                    _CONTENT_ID_KIND_BREAKER, run_id, criterion_id
                ),
                run_id=run_id,
                criterion_id=criterion_id,
                tripped_at=_now(),
                detail=detail,
            )
            gates["breaker"] = f"TRIPPED and latched: {detail}"
            processed, escalated, rate = self._escalation_rate(tx.execute, run_id)
            return self._escalation_report(
                tx, row, submission_id, criterion_id, DECISION_HALTED_BY_BREAKER,
                prior_judges=prior, added_judges=(), judge_count=len(prior),
                units_inserted=0, expected_value=expected_value,
                escalation_rate=rate, processed_results=processed,
                escalated_results=escalated, budget=budget,
                breaker_tripped=True, gates=gates,
            )
        gates["breaker"] = (
            f"not tripped ({escalated_in_window}/{len(window_ids)} in the window "
            f"of {breaker_min_n})"
        )

        # 4. The request row (the record the dispatch-time admission reads its EV
        #    from) and the units — written UNCONDITIONALLY: the budget rations
        #    dispatch, not the plan write (`FR-ORCH-14` at the claim pass, not here;
        #    see the method docstring's step 4). Content-addressed: a retried
        #    enqueue lands on the same rows and changes nothing.
        request_id = _content_id(
            _CONTENT_ID_KIND_REQUEST, run_id, submission_id, criterion_id
        )
        detail = json.dumps(
            {"judges": list(named) if named is not None else None},
            sort_keys=True,
        )
        tx.execute(
            ORCH_STATEMENTS["insert_escalation_request"],
            request_id=request_id,
            run_id=run_id,
            submission_id=submission_id,
            criterion_id=criterion_id,
            expected_value=expected_value,
            requested_at=_now(),
            detail=detail,
        )
        gates["request_row"] = (
            f"{request_id[:12]}… recorded at {expected_value!r} expected value"
        )
        inserted = self._insert_escalation_units(
            tx, row, submission_id, criterion_id, additions
        )
        tx.execute(
            ORCH_STATEMENTS["admit_request"],
            request_id=request_id,
            admitted_at=_now(),
            detail=detail,
        )
        gates["admission"] = (
            f"units written: {len(prior)} -> {len(target)} judges, {inserted} "
            "unit(s) inserted into the caller's transaction; dispatch admits them "
            "while the observed rate is at or under the budget"
        )
        if inserted:
            self._invalidate_order_cache(run_id)

        # 5. The observed rate, reported (the budget's numbers beside the decision —
        #    the decision itself is the claim pass's, through `admit_escalations`).
        processed, escalated, rate = self._escalation_rate(tx.execute, run_id)
        gates["budget"] = (
            f"observed rate {rate:.4f} ({escalated}/{processed} processed pairs "
            f"escalated) vs budget {budget}: dispatch admits pending escalation "
            "units while at or under, defers the remainder provisional above"
        )
        queue_depth = int(tx.execute(
            ORCH_STATEMENTS["select_queue_depth"], run_id=run_id
        )[0]["n"])
        gates["queue"] = f"{queue_depth} request(s) without written units"
        return self._escalation_report(
            tx, row, submission_id, criterion_id,
            DECISION_ADMITTED,
            prior_judges=prior,
            added_judges=additions,
            judge_count=len(target),
            units_inserted=inserted,
            expected_value=expected_value,
            escalation_rate=rate,
            processed_results=processed,
            escalated_results=escalated,
            budget=budget,
            breaker_tripped=False,
            gates=gates,
        )

    def _insert_escalation_units(
        self,
        tx: Any,
        row: Any,
        submission_id: str,
        criterion_id: str,
        additions: Sequence[str],
    ) -> int:
        """One pair's widening, inserted `origin='escalation'` (`FR-ORCH-09`).

        The additions are the plan's — derived by the caller from the pair's CURRENT
        panel in this same transaction, with the caller's named judges when it named
        any, so what was validated and reported is exactly what lands. Units are
        `INSERT OR IGNORE`d on the content address enumeration computes, so a pair
        widened by another path — the random arm draws the same (run, submission,
        criterion) — inserts nothing rather than scoring one judge twice.
        """
        inserted = 0
        for judge in additions:
            _, params = self._unit(
                row,
                STAGE_SCORE,
                {"submission_id": submission_id},
                {"criterion_id": criterion_id},
                judge,
                origin="escalation",
            )
            tx.execute(ORCH_STATEMENTS["insert_work_unit"], **params)
            # `OR IGNORE` cannot report what it did (the enumerate pass's note): the
            # count comes from the ledger, read in the same transaction.
            inserted += int(
                tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"]
            )
        return inserted

    def _escalation_dispatch_admission(self, cohort: Any, run_id: str) -> frozenset:
        """The pairs whose pending escalation units may dispatch this pass
        (`FR-ORCH-14`).

        `admit_escalations` IS the decision — the claim pass is the production caller
        the pure policy owes its honesty to: the candidates are the run's pending
        escalation pairs with their recorded expected values (`FR-ORCH-14` admits in
        expected-value order), the counts are the ledger's observed (done-based) pair
        aggregates, the budget the env knob read at call time. The result is stable
        within a claim pass — completions happen outside it — so the pass reads it
        once per run and the gate itself is a set lookup per candidate. An
        over-budget pass defers every pending escalation pair (the provisional
        remainder `FR-ORCH-14` marks, EV-ordered in `escalation_budget_state`'s
        surface); the deferral lifts when growth returns headroom, and the cache drop
        at the defer site is what makes the next pass re-derive rather than serve a
        stale order.
        """
        budget = _env_float(
            ESCALATION_BUDGET_ENV, ORCH_ESCALATION_BUDGET, low=0.0, high=1.0
        )
        processed, escalated, _rate = self._escalation_rate(cohort.query, run_id)
        candidates = [
            ((r["submission_id"], r["criterion_id"]), r["expected_value"])
            for r in cohort.query(
                ORCH_STATEMENTS["select_pending_escalation_pairs"], run_id=run_id
            )
        ]
        plan = admit_escalations(
            candidates, escalated=escalated, processed=processed, budget=budget
        )
        return frozenset(plan.admitted)

    def _escalation_rate(
        self, read: Callable[..., Sequence[Any]], run_id: str
    ) -> tuple[int, int, float]:
        """(processed pairs, escalated pairs, rate) for one run — the budget's
        numerator and denominator are always the ledger's own aggregates
        (`FR-ORCH-14`, `FR-ORCH-02`).

        `read` is a bound reader — a transaction's `execute` (reads are legal inside a
        transaction; the read-modify-write every ledger transition is) or a cohort
        handle's `query` for the read-only surfaces. One helper, both doors, so the
        rate an enqueue decides on and the rate the operator surface shows are computed
        by the same lines.
        """
        processed = int(read(
            ORCH_STATEMENTS["select_processed_results"], run_id=run_id
        )[0]["n"])
        escalated = int(read(
            ORCH_STATEMENTS["select_escalated_results"], run_id=run_id
        )[0]["n"])
        rate = (escalated / processed) if processed else 0.0
        return processed, escalated, rate

    def _escalation_report(
        self,
        tx: Any,
        row: Any,
        submission_id: str,
        criterion_id: str,
        decision: str,
        *,
        prior_judges: tuple[str, ...],
        added_judges: tuple[str, ...],
        judge_count: int,
        units_inserted: int,
        expected_value: float | None,
        escalation_rate: float,
        processed_results: int,
        escalated_results: int,
        budget: float,
        breaker_tripped: bool,
        gates: dict[str, str],
    ) -> EscalationReport:
        """Assemble the report with the queue depth read in the same transaction."""
        queue_depth = int(tx.execute(
            ORCH_STATEMENTS["select_queue_depth"], run_id=row["run_id"]
        )[0]["n"])
        return EscalationReport(
            run_id=row["run_id"],
            submission_id=submission_id,
            criterion_id=criterion_id,
            decision=decision,
            prior_judges=prior_judges,
            added_judges=added_judges,
            judge_count=judge_count,
            units_inserted=units_inserted,
            expected_value=expected_value,
            escalation_rate=escalation_rate,
            escalation_budget=budget,
            queue_depth=queue_depth,
            breaker_tripped=breaker_tripped,
            gates=gates,
        )

    def escalation_budget_state(self, run_id: str) -> EscalationBudgetState:
        """The run-wide escalation ledger's state — the operator surface the
        rate-above-budget alert reads (`FR-ORCH-14`, `CT-ORCH-16`).

        Every number is read from the ledger at call time: the rate is recomputed, the
        queue depth counted, the tripped criteria listed — no cached counters, because
        `FR-ORCH-02` allows no bookkeeping beyond the ledger and an alert computed from
        stale counters is a silent degradation, the exact shape `CT-ORCH-16` forbids.
        """
        row = self._run_row(run_id)
        cohort = self._store.cohort(row["cohort_id"])
        budget = _env_float(
            ESCALATION_BUDGET_ENV, ORCH_ESCALATION_BUDGET, low=0.0, high=1.0
        )
        processed, escalated, rate = self._escalation_rate(cohort.query, run_id)
        queue_depth = int(cohort.query(
            ORCH_STATEMENTS["select_queue_depth"], run_id=run_id
        )[0]["n"])
        tripped = tuple(
            r["criterion_id"] for r in cohort.query(
                ORCH_STATEMENTS["select_run_breakers"], run_id=run_id
            )
        )
        over = rate > budget
        # The admission split, computed by the SAME lines the claim pass decides with
        # (`admit_escalations` — one policy, both doors): the pending escalation
        # pairs with their recorded expected values, so the provisional remainder is
        # marked here exactly as the gate defers it there.
        pending_pairs = cohort.query(
            ORCH_STATEMENTS["select_pending_escalation_pairs"], run_id=run_id
        )
        plan = admit_escalations(
            [
                ((r["submission_id"], r["criterion_id"]), r["expected_value"])
                for r in pending_pairs
            ],
            escalated=escalated,
            processed=processed,
            budget=budget,
        )
        provisional = tuple(
            f"{pair[0]}/{pair[1]}" for pair in plan.provisional
        )
        return EscalationBudgetState(
            run_id=run_id,
            processed_results=processed,
            escalated_results=escalated,
            escalation_rate=rate,
            budget=budget,
            over_budget=over,
            queued_requests=queue_depth,
            tripped_criteria=tripped,
            provisional_pairs=provisional,
            gates={
                "rate": (
                    f"{escalated}/{processed} processed pairs escalated "
                    f"({rate:.4f}) vs budget {budget} — "
                    + ("OVER: dispatch defers pending escalation pairs, remainder "
                       "provisional until growth returns headroom"
                       if over else "within budget")
                ),
                "provisional": (
                    f"{len(provisional)} pending escalation pair(s) marked "
                    f"provisional (EV order): {', '.join(provisional)}"
                    if provisional
                    else "no pending escalation pairs deferred"
                ),
                "queue": f"{queue_depth} request(s) without written units",
                "breakers": (
                    f"{len(tripped)} criterion breaker(s) latched: "
                    f"{', '.join(tripped)}" if tripped else "none latched"
                ),
            },
        )

    def tripped_breakers(self, run_id: str) -> tuple[BreakerTrip, ...]:
        """The run's latched circuit breakers, criterion-ordered (`FR-ORCH-13`) — the
        alert surface ("any criterion tripping the circuit breaker") reads these rows;
        each carries the window arithmetic that tripped it, so the alert answers
        'why', not just 'what'."""
        row = self._run_row(run_id)
        cohort = self._store.cohort(row["cohort_id"])
        return tuple(
            BreakerTrip(
                run_id=run_id,
                criterion_id=r["criterion_id"],
                kind=r["kind"],
                tripped_at=r["tripped_at"],
                detail=r["detail"],
            )
            for r in cohort.query(
                ORCH_STATEMENTS["select_run_breakers"], run_id=run_id
            )
        )

    # -- internals ------------------------------------------------------------------------------

    def _unit(
        self,
        row: Any,
        stage: str,
        submission: Any,
        criterion: Any,
        judge_id: str | None,
        origin: str = "base",
    ) -> tuple[str, dict[str, Any]]:
        """One computed unit: its `work_id` and its insert parameters.

        Kept beside `compute_work_id`'s call so the nine inputs' provenance is one
        glance: run and package from the run row, prompt template version from the
        frozen config, extractor version from the module constant, judge from the arm.

        `origin` names the unit's provenance — `'base'`, `'escalation'` or
        `'random_arm'` (`FR-ORCH-09/11`). It is deliberately **not** a `work_id` input:
        the id addresses the work (run, stage, submission, criterion, judge, versions,
        panel), and the origin says why that work exists. A base unit and a random-arm
        unit for the same (submission, criterion, judge) are the SAME work — one row,
        one lease, one verdict — and the origin column keeps the base row's provenance
        while the arm's extra judges carry the arm's mark. Consumers requiring the
        separation (`CT-ORCH-15`) read the arm's own units, never re-derive them.
        """
        work_id = compute_work_id(
            run_id=row["run_id"],
            stage=stage,
            submission_id=submission["submission_id"],
            criterion_id=criterion["criterion_id"],
            judge_id=judge_id,
            package_version_id=row["package_version_id"],
            panel_config=row["panel_config"],
            prompt_template_version=row["prompt_template_v"],
            extractor_version=EXTRACTOR_VERSION,
        )
        params = {
            "work_id": work_id,
            "submission_id": submission["submission_id"],
            "stage": stage,
            "run_id": row["run_id"],
            "criterion_id": criterion["criterion_id"],
            "judge_id": judge_id,
            "origin": origin,
        }
        return work_id, params

    def _unit_from_row(self, row: Any) -> WorkUnit:
        """The `WorkUnit` a claimed ledger row becomes when handed to a worker.

        The claim select carries `student_ref` (the identity the assembler needs) and
        aliases `attempts AS attempt` to the type's field; `student_name` and
        `submission_text` are `None` — the ledger holds neither, and their resolution
        is assembly's act (`M-EXTRACT`), not the lease's. The name-agnostic row reads
        keep the helper honest across the two selects that feed it.
        """
        keys = set(row.keys())
        return WorkUnit(
            work_id=row["work_id"],
            run_id=row["run_id"],
            stage=row["stage"],
            student_ref=row["student_ref"] if "student_ref" in keys else "",
            student_name=None,
            submission_id=row["submission_id"],
            criterion_id=row["criterion_id"],
            submission_text=None,
            judge=row["judge_id"],
            attempt=int(row["attempt"] if "attempt" in keys else row["attempts"]),
        )

    def provenance(self, work_id: str) -> UnitProvenance:
        """Follow one unit to its source document: work_unit -> submission -> document.

        Raises `BrokenLineageError` naming the broken hop when the unit has no submission,
        its submission is absent from the cohort, the submission has no document, or the
        unit's evidence names a document that is ambiguous or not the submission's — no
        imputation, never a NULL `document_id` (#223). Raises `WorkLedgerError` for a
        work id no cohort holds, as `_find_unit` does.
        """
        cohort, _row = self._find_unit(work_id)
        rows = cohort.query(ORCH_STATEMENTS["select_unit_provenance"], work_id=work_id)
        first = rows[0]
        short = work_id[:12]
        if first["submission_id"] is None:
            raise BrokenLineageError(
                f"work unit {short}… carries no submission_id, so it cannot be traced to a "
                "source document; the unit is refused rather than joined to NULL."
            )
        if first["joined_submission_id"] is None:
            raise BrokenLineageError(
                f"work unit {short}… names submission {first['submission_id']!r}, which "
                "this cohort does not hold; its lineage is broken at the submission hop."
            )
        documents = [row for row in rows if row["document_id"] is not None]
        if not documents:
            raise BrokenLineageError(
                f"work unit {short}… belongs to submission {first['submission_id']!r}, "
                "which has no document row; its lineage is broken at the document hop."
            )
        head = documents[-1]
        by_id = {row["document_id"]: row for row in documents}
        read = [
            row["document_id"]
            for row in cohort.query(
                ORCH_STATEMENTS["select_unit_evidence_documents"], work_id=work_id
            )
        ]
        if len(read) > 1:
            raise BrokenLineageError(
                f"work unit {short}…'s evidence names {len(read)} documents ({read}); one "
                "unit reads one document, so its source is ambiguous and is not guessed."
            )
        if read and read[0] not in by_id:
            raise BrokenLineageError(
                f"work unit {short}…'s evidence names document {read[0]!r}, which is not a "
                f"document of submission {first['submission_id']!r}."
            )
        source = by_id[read[0]] if read else head
        hops = [f"work_unit:{work_id}", f"submission:{first['submission_id']}"]
        if read:
            hops.append(f"evidence:{work_id}")
        hops.append(f"document:{source['document_id']}")
        return UnitProvenance(
            work_id=work_id,
            run_id=first["run_id"],
            stage=first["stage"],
            submission_id=first["submission_id"],
            document_id=source["document_id"],
            content_hash=source["content_hash"],
            current_document_id=head["document_id"],
            read_from_evidence=bool(read),
            document_ids=tuple(row["document_id"] for row in documents),
            hops=tuple(hops),
        )

    def _find_unit(self, work_id: str) -> tuple[Any, Any]:
        """(cohort handle, ledger row) for one work unit, by walking the cohort files.

        The same no-side-index discipline as `_run_row`: the ledger is its own
        directory, and a side index of work ids would be exactly the bookkeeping
        `FR-ORCH-02` forbids. A work id that resolves nowhere is a caller error worth
        naming — the same posture as `RunNotFoundError`.
        """
        for key in self._cohort_keys():
            cohort = self._store.cohort(key)
            rows = cohort.query(
                ORCH_STATEMENTS["select_work_unit"], work_id=work_id
            )
            if rows:
                return cohort, rows[0]
        raise WorkLedgerError(
            f"no work unit named {work_id[:12]}… exists in any cohort ledger. The id "
            "is the ledger's own content address; one that resolves to nothing was "
            "never enumerated (or names a run this store does not hold)."
        )

    def _cohort_keys(self) -> tuple[str, ...]:
        """The store's cohort tier keys, in sorted order — the discovery surface resume's
        no-argument form walks. Every key's file is opened and read; a cohort with no
        open runs costs one query."""
        return tuple(sorted(self._cohort_keys_for(self._store)))

    def _catalog(self, row: Any) -> PackageCatalogProtocol:
        """The package catalog for the run's version, opened on the version's Tier P
        database. Imported here, not at module top: `aeh.pkg` appends its own migrations
        to the Tier P registry on import, and the import order of the owning modules is
        each module's own concern — `test_migrations.py` imports them explicitly for the
        same reason.

        One catalog instance is held open per (package_id, package_version_id): the
        catalog's own cache is per instance (`NFR-PKG-05`), and the claim pass reads the
        version on every dispatch, so a fresh instance per read would reload the version
        per claim — the per-instance cache is the point of holding it open.
        """
        key = (row["package_id"], row["package_version_id"])
        catalog = self._catalogs.get(key)
        if catalog is None:
            from aeh.pkg import PackageCatalog

            catalog = PackageCatalog(
                self._store.package(row["package_id"]),
                package_id=row["package_id"],
            )
            self._catalogs[key] = catalog
        return catalog

    def _run_row(self, run_id: str) -> Any:
        """The run's ledger row, found by walking the cohort files.

        There is deliberately no index of run ids outside the ledger: the run row lives
        in its cohort's Tier C file (§9.6 puts run state beside cohort state), and a
        side index would be exactly the bookkeeping FR-ORCH-02 forbids. Cohort counts
        are small; a scan is a handful of indexed queries.
        """
        return self._find_run(run_id)[1]

    def _find_run(self, run_id: str) -> tuple[Any, Any]:
        """(cohort handle, run row) for one run — the lifecycle writers need both, and
        re-walking the cohorts to turn the row back into its handle would be the same
        scan twice. Same no-side-index rule as `_run_row`, which is this minus the
        handle."""
        for key in self._cohort_keys():
            cohort = self._store.cohort(key)
            rows = cohort.query(ORCH_STATEMENTS["select_run"], run_id=run_id)
            if rows:
                return cohort, rows[0]
        raise RunNotFoundError(
            f"no run row named {run_id!r} exists in any cohort ledger. resume() with "
            "no arguments finds its own runs; an explicit run_id that resolves to "
            "nothing is a caller error worth naming."
        )

    def _panel_arms(self, panel_config: str) -> tuple[str, ...]:
        """The panel's ordered judge ids, from the run row's canonical `panel_config`."""
        arms = json.loads(panel_config).get("arms")
        if not isinstance(arms, list) or not all(isinstance(a, str) for a in arms):
            raise WorkLedgerError(
                f"run row carries panel_config {panel_config!r}, which is not the "
                "canonical {\"arms\": [...]} form this module writes (panel_config_json)."
            )
        return tuple(arms)

    def _dropped_judges(self, run_row: Any) -> frozenset[str]:
        """The judges the OOM ladder dropped from this run's panel (`RES-13`), read
        from the run row itself: the arms the FROZEN `provider_config` snapshot named
        minus the arms the run's `panel_config` names now. The drop is durable in the
        run row — the remedy rewrote `panel_config` down to the smaller panel — so the
        skip this set drives survives a restart, where the in-memory dispatch state
        does not (#62 review: a fresh Orchestrator over the same store must skip the
        same units the recording one skipped; the dropped judges' un-run units stay
        pending for an operator to re-queue under the smaller panel). A judge the
        frozen panel never carried is not a drop: derived escalation arms
        (`escalation-arm-<k>`, `_extension_arms`) and explicitly-passed escalation
        judges are outside both panels, so they are never in this set. An unreadable
        frozen panel skips nothing — stranding units on an unreadable snapshot is the
        conservative side, and `_concurrency_ceiling` refuses malformed configs
        loudly beside this."""
        try:
            frozen = json.loads(run_row["provider_config"]).get("panel")
            current = set(self._panel_arms(run_row["panel_config"]))
        except (TypeError, ValueError, WorkLedgerError):
            return frozenset()
        if not isinstance(frozen, list):
            return frozenset()
        return frozenset(
            arm for arm in frozen if isinstance(arm, str) and arm not in current
        )

    def _runs_missing_units(self) -> tuple[str, ...]:
        """Open runs whose ledger holds no work_unit rows at all, in run-id order.

        The gate behind lease()'s enumerate-on-empty fallback: enumerating is a full
        pass over catalog, roster and computed ids, and a drained poll late in a large
        run must not pay it (NFR-ORCH-01). A run with rows — even partially populated
        by a crash mid-enumeration — is `resume()`'s repair, not lease's; the
        existence probe is one indexed query per open run.

        **The admissible-submission gate (#59 review).** A run can hold no units
        *legitimately*, and forever: a cohort whose submissions are all refused — or
        which has none yet — enumerates to the empty set, and re-deriving that empty
        set on every drained poll is precisely the full pass this gate exists to
        prevent ("never enumerated" and "legitimately empty" must not cost the same).
        A run whose cohort holds no admissible submission — none with a NULL
        `ingest_status` (pre-ingest, admits per `SWEEP1_ADMITTED_INGEST_STATUSES`'s
        recorded reading) and none in the admitted set — is therefore skipped. The
        gate re-opens by itself: a submission re-ingested into an admissible status
        makes the cohort admissible again on the next poll, which is the self-heal
        path. A cohort that stays admissible while the package yields no units for
        another reason (a version with zero criteria — `M-PKG` refuses the shape, so
        this helper does not defend against it) would still re-enumerate per poll.
        """
        found: list[str] = []
        admissible_by_cohort: dict[str, bool] = {}
        for key in self._cohort_keys():
            cohort = self._store.cohort(key)
            for row in cohort.query(ORCH_STATEMENTS["select_open_runs"]):
                cohort_id = row["cohort_id"]
                if cohort_id not in admissible_by_cohort:
                    admissible_by_cohort[cohort_id] = any(
                        s["ingest_status"] is None
                        or s["ingest_status"] in SWEEP1_ADMITTED_INGEST_STATUSES
                        for s in cohort.query(
                            ORCH_STATEMENTS["select_submissions"],
                            cohort_id=cohort_id,
                        )
                    )
                if not admissible_by_cohort[cohort_id]:
                    continue
                if not cohort.query(
                    ORCH_STATEMENTS["select_any_work_unit"], run_id=row["run_id"]
                ):
                    found.append(row["run_id"])
        return tuple(sorted(found))

    def _open_run_ids(self) -> tuple[str, ...]:
        """Every not-yet-finished run, across every cohort ledger, in run-id order."""
        found: list[str] = []
        for key in self._cohort_keys():
            for row in self._store.cohort(key).query(ORCH_STATEMENTS["select_open_runs"]):
                found.append(row["run_id"])
        return tuple(sorted(found))

    # -- the dispatch loop, residency, concurrency and the report (#62) --------------------------

    def progress(self, run_id: str) -> ProgressReport:
        """One dispatch pass over `run_id`, then the run-state report (`FR-ORCH-23`).

        **The two modes.** With a transport bound (`Orchestrator(store, transport=...)`)
        the pass dispatches: the extraction walk sends its assembled `ExtractionRequest`
        through the model-call seam, the deterministic walk completes its ledger
        transition directly (no model call exists for it), one judged batch at the
        governor's effective concurrency runs
        through the model-call seam as assembled `ScoringRequest`s, and the run's
        metrics flush to `run_metrics`
        (`CT-ORCH-20`). With no transport the call is the **report-only surface** — the
        (`CT-ORCH-20`). With no transport the call is the **report-only surface** — the
        console's poll (`CT-CONSOLE-01`'s headless driver needs progress to work with no
        console and no provider): the ledger is read and the report built, and nothing
        is claimed, called or flushed.

        **The pass drives the shared worker surface.** The walks and the judged batch
        claim through `lease()` under `DISPATCH_OWNER` — the dispatch loop is a lease
        holder like any worker, at-least-once and sweepable, so an interrupted pass's
        in-flight units are the sweeper's ordinary reclaim, never a special case. The
        claim pass walks the store's open runs (`#59`'s shape), so a poll nominally for
        `run_id` serves whichever open run the walk reaches first; the single-run store
        every dispatch case runs against makes the distinction invisible, and a
        multi-run operator gets run-id-order service from the walk itself — recorded
        interpretation, reconciled if a case ever pins multi-run dispatch.

        progress() never raises for an expected provider condition: a rate limit or an
        OOM is absorbed into the governor and the report (`RES-11`, `RES-13` —
        "expected, not an error"). A failure that is not one of the taxonomy's two
        transport conditions propagates: an unexpected exception mid-dispatch is a
        defect, and absorbing it would be the silent-failure shape.
        """
        cohort, run_row = self._find_run(run_id)
        state: dict[str, Any] | None = None
        if self._dispatches():
            state = self._dispatch_state(run_row)
            self._dispatch_pass(cohort, run_row, state)
        report = self._progress_report(cohort, run_row, run_id, state)
        if state is not None:
            self._flush_run_metrics(cohort, run_id, state, report)
        return report

    def _concurrency_ceiling(self, run_row: Any) -> int:
        """The concurrency ceiling the run **froze** at creation (`FR-ORCH-21`).

        Read from the run row's frozen `provider_config` — never from the current
        environment (`FR-CONF-07`'s freeze, the same discipline `_run_ceiling` states
        for the cost ceiling: a concurrency ceiling changed mid-run is a ceiling the
        operator never approved). A row whose frozen config carries no readable
        ceiling refuses loudly: a dispatch that guessed a width would be a dispatch
        nobody bounded.
        """
        raw = run_row["provider_config"]
        try:
            cfg = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise WorkLedgerError(
                f"run {run_row['run_id'][:12]} carries malformed provider_config — "
                "the frozen concurrency ceiling cannot be read, and an unreadable "
                "ceiling must halt dispatch loudly rather than guess a width."
            ) from exc
        value = cfg.get("concurrency_ceiling") if isinstance(cfg, dict) else None
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise WorkLedgerError(
                f"run {run_row['run_id'][:12]} froze a concurrency ceiling of "
                f"{value!r} — refused: the ceiling bounds how many model calls run "
                "at once, and a non-positive or non-integer one is not a bound."
            )
        return value

    def _dispatch_state(self, run_row: Any) -> dict[str, Any]:
        """The per-run dispatch state, created lazily and rebuilt-free thereafter.

        Holds the governor's cap (starting at the frozen ceiling, `FR-CONF-07`), the
        residency state (`FR-ORCH-19`), the per-judge OOM counts (`RES-13`), the
        provider counters the metrics flush persists (`CT-ORCH-20`, `CT-PROV-11`) and
        the pass's timing anchors. The OOM drop's skip is NOT here: it reads the run
        row's own panels (`_dropped_judges`) so it survives a restart. Kept per run —
        not per pass — so
        the counters a report reads are the run's own cumulative truth, and the
        governor's reduction survives between passes. An in-memory dict on a module
        whose bookkeeping rule is the ledger (`FR-ORCH-02`) is a deliberate exception:
        these are the OBSERVABILITY accumulators, not the work state — the work lives
        in `work_unit` rows, and a restart re-derives nothing but fresh counters.
        """
        run_id = run_row["run_id"]
        state = self._dispatch_states.get(run_id)
        if state is None:
            state = {
                "cap": self._concurrency_ceiling(run_row),
                "residency": {
                    "resident": None,
                    "swaps": 0,
                    "swap_ms": 0.0,
                    "swap_started": None,
                },
                "oom_counts": {},
                "rate_limited_calls": 0,
                "transport_retries": 0,
                "rate_limit_wait_s": 0.0,
                "tokens_in": 0,
                "tokens_out": 0,
                "cache_tokens": 0,
                "cost": Decimal("0"),
                "resolved_build": None,
                "calls": 0,
                "peak_concurrency": 0,
                "in_flight_calls": 0,
                "reduced_this_pass": False,
                "lock": threading.Lock(),
            }
            self._dispatch_states[run_id] = state
        return state

    def _dispatch_pass(
        self, cohort: Any, run_row: Any, state: dict[str, Any]
    ) -> None:
        """One dispatch pass: the walks, then one judged batch, at the effective cap.

        **The governor** (`FR-ORCH-21`). The pass runs at the state's cap — starting
        at the run's frozen ceiling, never the environment's — reduced once per pass
        on the first rate-limited or OOM call (floor 1; applied the moment the signal
        lands, so the report this pass returns carries the reduced width) and clamped
        while `M-STORE` signals write backpressure (`CT-STORE-06`: a signal to reduce,
        never a fault — sensed per pass, never persisted, so a store that recovers is
        a dispatch that resumes full width).

        **The walks** (`#62`'s interpretation, recorded on the class): scoring gates on
        the extraction transition, so the pass completes extract units — through the
        seam, because extraction IS a model call: the assembled `ExtractionRequest`
        (`M-EXTRACT`'s `assemble_request`) goes over the wire and a transport that
        rate-limits rate-limits it too — bounded by
        `HARNESS_ORCH_DISPATCH_WALK_BATCH`; the deterministic walk completes its units
        directly (deterministic evaluation makes no model call), then the pass claims
        one judged batch of at most the effective cap. Residency shapes the judged
        batch from inside the claim
        walk (`_claim_pass`'s gate) — the pass itself is residency-blind.
        """
        state["reduced_this_pass"] = False
        effective = state["cap"]
        if store_metrics(self._store).get("backpressure_active"):
            effective = max(
                effective
                // _env_int(BACKPRESSURE_DIVISOR_ENV, BACKPRESSURE_DIVISOR_DEFAULT),
                1,
            )
        walk_batch = _env_int(DISPATCH_WALK_BATCH_ENV, DISPATCH_WALK_BATCH_DEFAULT)
        completed_total = 0
        while completed_total < walk_batch:
            batch = list(
                self.lease(
                    DISPATCH_OWNER,
                    STAGE_EXTRACT,
                    min(walk_batch - completed_total, effective),
                )
            )
            if not batch:
                break
            completed = self._run_model_batch(
                cohort, run_row, state, batch, effective
            )
            completed_total += completed
            if completed == 0:
                # The pass made no headway: every claim came back
                # transport-blocked (rate-limited or OOM) and requeued. Claiming
                # again would re-run the same blocked batch until the walk
                # bound — the back-off is the reduction and the NEXT pass.
                break
        # The deterministic walk completes DIRECTLY (`#62`'s assembled-request
        # reconciliation): a deterministic criterion's evaluation makes no model
        # call (`TC-ORCH-10`'s shape — the unit carries a null judge and there is
        # no request schema for it to assemble), so there is nothing to send
        # across the transport and nothing a rate-limited provider could block —
        # the ledger transition IS the stage's dispatch, the way the extraction
        # payload is the owning stage's to persist (#68 onward).
        for unit in self.lease(DISPATCH_OWNER, STAGE_DETERMINISTIC, walk_batch):
            self.complete(unit.work_id)
        judged = list(self.lease(DISPATCH_OWNER, STAGE_SCORE, effective))
        self._run_model_batch(cohort, run_row, state, judged, effective)

    def _assemble_dispatch_payload(self, unit: Any) -> Any:
        """Assemble the closed per-stage request the dispatch sends (`FR-ORCH-20`).

        What crosses the model-call boundary is the ASSEMBLED request, never the
        ledger row: "the module shall dispatch exactly one submission per scoring or
        extraction request" (`FR-ORCH-20`), and the exactly-one form is assertable
        only over the closed schema (`CT-JUDGE-02`). The assembler is the OWNING
        stage's shipped door — `M-JUDGE`'s `ScoringWorker.assemble` for score units,
        `M-EXTRACT`'s `assemble_request` for extract units — invoked with the store
        so the words resolve here (the lease resolved the identity). The imports are
        deferred because the owning modules import this one (the registry's
        contributor graph has `aeh.orch` as an ancestor, not a leaf).

        Deterministic units never reach the seam (no model call exists — the
        deterministic walk completes them directly), so no schema is invented here
        for one: a stage without a request schema reaching this helper is a dispatch
        defect, not a payload to fabricate.
        """
        if unit.stage == STAGE_SCORE:
            from aeh.judge import ScoringWorker

            return ScoringWorker(store=self._store).assemble(unit)
        if unit.stage == STAGE_EXTRACT:
            from aeh.extract import assemble_request

            return assemble_request(unit, store=self._store)
        raise ValueError(
            f"unit {unit.work_id[:12]} carries stage {unit.stage!r}, which makes no "
            f"model call — only extract and score units cross the transport seam; "
            f"deterministic units complete directly"
        )

    # -- #362: the stage-executor seam, cell phases and readiness (FR-ORCH-27/28/29/30) --------

    def _dispatches(self) -> bool:
        """Whether this orchestrator dispatches model work at all.

        `None` on both seams is the report-only surface (the console's poll): it reads the
        ledger and claims nothing, which is why `progress()` must not build a dispatch state
        for it."""
        return self._executor is not None or self._transport is not None

    def _stage_executor(self, state: dict[str, Any]) -> Any:
        """The executor this pass dispatches through — the bound one, or the transport
        adapted to the same protocol so the loop has a single path."""
        if self._executor is not None:
            return _PreparedExecutor(self._executor)
        payloads: dict[str, Any] = {}
        return _PreparedExecutor(
            TransportStageExecutor(self._transport, payloads, state),
            prepare=self._assemble_dispatch_payload,
            payloads=payloads,
        )

    def mark_cell_phase(
        self, tx: Any, run_id: str, submission_id: str, criterion_id: str,
        phase: str, units_consumed: int = 0,
    ) -> None:
        """Record that one cell reached one composition phase (`FR-ORCH-28`).

        Written through the CALLER's transaction, so a phase and whatever it stands for — the
        integrity verdict, the score row — commit together or not at all: a phase recorded
        beside work that rolled back would make a restart skip the work (`NFR-PIPE-01` is
        about exactly that). Marking the same phase twice updates the one row rather than
        adding a second, so redelivery is a no-op.

        `units_consumed` is how many terminal units the phase was computed over. It is what
        lets `ready_cells` distinguish "aggregated, and three more verdicts have landed since"
        from "aggregated, nothing since" — a count, not a flag, because the second aggregation
        is exactly what a re-scored cell needs.
        """
        if phase not in CELL_PHASES:
            raise ValueError(
                f"{phase!r} is not a composition phase; the declared vocabulary is "
                f"{CELL_PHASES} (FR-ORCH-28). The table's CHECK refuses it too — this "
                "refusal is the one that names the phases."
            )
        tx.execute(
            ORCH_STATEMENTS["upsert_cell_phase"],
            run_id=run_id, submission_id=submission_id, criterion_id=criterion_id,
            phase=phase, units_consumed=int(units_consumed), recorded_at=_now(),
        )

    def run_handle(self, run_id: str) -> RunHandle:
        """The run's cohort handle and identities, for a composition layer (`FR-PIPE-04`).

        `M-PIPE` needs a transaction to commit a score, its escalation and its cell phase
        together, and a transaction comes from the cohort handle. It is forbidden its own SQL
        (`CT-PIPE-05`), so it asks here rather than querying the run row — which is the same
        discipline every other cross-module read in this system follows: the owner answers.

        Raises `RunNotFoundError` for an unknown run, exactly as the lifecycle writers do.
        """
        cohort, row = self._find_run(run_id)
        return RunHandle(
            run_id=run_id,
            cohort_id=str(row["cohort_id"]),
            cohort=cohort,
            package_id=str(row["package_id"]),
            package_version_id=str(row["package_version_id"]),
            status=str(row["status"]),
            pause_reason=row["pause_reason"],
            backend_profile=str(row["backend_profile"] or ""),
        )

    def unit_status(self, work_id: str) -> str:
        """One unit's ledger status, or `""` if the ledger has no such unit.

        A stage executor needs it to tell "the worker did the work" from "the worker struck
        the unit out and the ledger already closed it". `complete()` refuses the second case
        and the refusal would surface as a composition fault, pausing a run over a single
        unparseable reply — so the executor asks first.
        """
        for key in self._cohort_keys():
            rows = self._store.cohort(key).query(
                ORCH_STATEMENTS["select_unit_status"], work_id=work_id)
            if rows:
                return str(rows[0]["status"])
        return ""

    def has_queued_resume(self, run_id: str) -> bool:
        """Whether an unapplied **resume** request is waiting on this run.

        The distinction a recovery pass depends on. `resume()`'s no-argument form applies
        queued control rows and deliberately never lifts a bare operator pause — "a stop an
        operator requested outranks a scheduler's restart" — but it also re-enumerates every
        open run it discovers, `pending` ones included, which writes work units for a run
        nobody started. An explicit `resume(run_id)` enumerates only the run named, and
        supersedes the pauses before it.

        So a caller that wants the first rule without the second has to know which paused runs
        carry a request, and that is this. Without it a recovery either restarts stopped work
        or enumerates unstarted work; neither is acceptable and both have a case asserting so.
        """
        cohort, _row = self._find_run(run_id)
        return any(
            str(row["action"]) == "resume"
            for row in cohort.query(
                ORCH_STATEMENTS["select_unapplied_control"], run_id=run_id)
        )

    def record_pause_reason(self, run_id: str, cause: "BaseException | str") -> None:
        """Record WHY an already-paused run is staying paused, with no state change.

        `pause()` is the right call to stop a run and the wrong one to annotate a stopped one:
        on a `paused` run it records the request as satisfied and changes nothing, which is
        deliberate. But a run that recovery refuses to resume — a profile switch, say
        (`FR-CONF-15`) — needs the refusal on the row, because an operator who switched
        profiles and found a run stopped reads `pause_reason` to learn why, and a stale
        operator note answers a different question.

        Touches `pause_reason` and nothing else: not the status, not the frozen
        `provider_config`/`panel_config` (`FR-ORCH-16`'s resume-same-backend). A run that is
        not paused is left alone — this annotates, it never stops anything.
        """
        cohort, _row = self._find_run(run_id)
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["update_pause_reason"],
                run_id=run_id, pause_reason=self._pause_reason_text(cause),
            )

    def cohort_ref(self, cohort_id: str) -> "CohortRef":
        """The cohort's declared identity, as `M-CONF` wants it (`FR-CONF-08`, `ADR-5`).

        `CohortRef`'s `consent_class` defaults to `'real'`, deliberately: an undeclared cohort
        must fail closed against a remote backend. That makes the stored value something a
        caller has to READ rather than omit, and a composition layer cannot read it itself
        (`CT-PIPE-05`). So the owner answers, as it does for `run_handle`.

        An unknown cohort returns the fail-closed default rather than raising: the consent gate
        is the right place for that refusal, and it states the reason better than this would.
        """
        from aeh.conf import CohortRef

        for key in self._cohort_keys():
            rows = self._store.cohort(key).query(
                ORCH_STATEMENTS["select_cohort_row"], cohort_id=cohort_id)
            if rows:
                declared = str(rows[0]["consent_class"] or "real")
                return CohortRef(cohort_id=cohort_id, consent_class=declared)
        return CohortRef(cohort_id=cohort_id)

    def runs(self, statuses: Sequence[str] | None = None) -> tuple[RunHandle, ...]:
        """Every run the store holds, optionally filtered by status, in ledger order.

        `recover` (`FR-PIPE-07`) needs the runs that are COMPLETE but not fully graded, and
        `resume`'s discovery deliberately sees only open ones. A composition layer cannot walk
        the cohorts itself (`CT-PIPE-05`), so the owner answers — the same reasoning as
        `run_handle`, widened from one run to all of them.
        """
        wanted = None if statuses is None else {str(s) for s in statuses}
        found: list[RunHandle] = []
        for key in self._cohort_keys():
            cohort = self._store.cohort(key)
            for row in cohort.query(ORCH_STATEMENTS["select_all_runs"]):
                status = str(row["status"])
                if wanted is not None and status not in wanted:
                    continue
                found.append(RunHandle(
                    run_id=str(row["run_id"]),
                    cohort_id=str(row["cohort_id"]),
                    cohort=cohort,
                    package_id=str(row["package_id"]),
                    package_version_id=str(row["package_version_id"]),
                    status=status,
                    pause_reason=row["pause_reason"],
                    backend_profile=str(row["backend_profile"] or ""),
                ))
        return tuple(found)

    def cell_unit_counts(self, run_id: str, stage: str) -> dict["CellKey", tuple[int, int]]:
        """`(terminal, total)` units per cell for one stage — the count a phase is computed over.

        `mark_cell_phase(..., units_consumed=n)` wants the number of TERMINAL units the phase
        consumed, and `ready_cells` compares that number against the cell's terminal count to
        decide whether a widened panel needs re-aggregating. A composition layer therefore has
        to record the same number this module counts, and it cannot count for itself
        (`CT-PIPE-05`). Recording a verdict count instead would be a quiet bug: a quarantined
        unit produces no verdict, so the cell would read as ready on every later pass and
        aggregate forever.

        Same read `ready_cells` performs, exposed rather than duplicated.
        """
        cohort, _run_row = self._find_run(run_id)
        counts: dict[CellKey, tuple[int, int]] = {}
        for row in cohort.query(ORCH_STATEMENTS["select_cell_unit_counts"], run_id=run_id):
            if str(row["stage"]) != stage:
                continue
            counts[CellKey(str(row["submission_id"]), str(row["criterion_id"]))] = (
                int(row["terminal"] or 0), int(row["total"] or 0)
            )
        return counts

    def ready_cells(self, run_id: str, hook: str) -> tuple["CellKey", ...]:
        """The cells ready for one composition hook (`FR-ORCH-29`), in ledger order.

        * `integrity_pre` — every extract unit of the cell is terminal and the cell carries no
          `integrity_pre` phase yet. That is the moment the integrity gate can read a complete
          extraction and has not already.
        * `aggregate` — every score unit of the cell is terminal, and MORE of them are terminal
          than the `aggregated` phase consumed (or the cell has never aggregated). The count
          comparison is what makes a widened panel re-aggregate: three verdicts became five,
          so the cell is ready again.

        Terminal means `done` or `quarantined`: a quarantined unit will produce no further
        evidence, and a cell waiting for one would wait forever.
        """
        if hook not in READY_HOOKS:
            raise ValueError(
                f"{hook!r} is not a composition hook; the declared hooks are "
                f"{READY_HOOKS} (FR-ORCH-29)."
            )
        cohort, _run_row = self._find_run(run_id)
        counts: dict[tuple[str, str], dict[str, tuple[int, int]]] = {}
        for row in cohort.query(ORCH_STATEMENTS["select_cell_unit_counts"], run_id=run_id):
            key = (str(row["submission_id"]), str(row["criterion_id"]))
            counts.setdefault(key, {})[str(row["stage"])] = (
                int(row["terminal"] or 0), int(row["total"] or 0)
            )
        phases: dict[tuple[str, str], dict[str, int]] = {}
        for row in cohort.query(ORCH_STATEMENTS["select_cell_phases"], run_id=run_id):
            key = (str(row["submission_id"]), str(row["criterion_id"]))
            phases.setdefault(key, {})[str(row["phase"])] = int(row["units_consumed"] or 0)
        stage = STAGE_EXTRACT if hook == "integrity_pre" else STAGE_SCORE
        ready: list[CellKey] = []
        for key in sorted(counts):
            terminal, total = counts[key].get(stage, (0, 0))
            if not total or terminal < total:
                continue
            marked = phases.get(key, {})
            if hook == "integrity_pre":
                if "integrity_pre" not in marked:
                    ready.append(CellKey(*key))
            elif "aggregated" not in marked or terminal > marked["aggregated"]:
                ready.append(CellKey(*key))
        return tuple(ready)

    def _cells_with_integrity_pre(self, cohort: Any, run_id: str) -> set[tuple[str, str]]:
        """The cells whose `integrity_pre` phase is recorded — the Sweep-2 gate's extra
        condition when an executor is bound (`FR-ORCH-30`)."""
        return {
            (str(row["submission_id"]), str(row["criterion_id"]))
            for row in cohort.query(ORCH_STATEMENTS["select_cell_phases"], run_id=run_id)
            if str(row["phase"]) == "integrity_pre"
        }

    def _run_model_batch(
        self,
        cohort: Any,
        run_row: Any,
        state: dict[str, Any],
        batch: Sequence[Any],
        effective: int,
    ) -> int:
        """Run one claimed batch through the model-call seam at the effective width.

        Each unit's ASSEMBLED request is built on the calling thread BEFORE the pool
        takes anything — the assembler is the owning stage's shipped door, it reads
        the store (the words resolve here: "the lease resolves the identity, the
        assembler the words"), and the store is not a thread-shared surface — so the
        only thing that runs concurrently is the model call itself. Assembly
        completes for the WHOLE batch before the first submit, and the submits are
        then back-to-back: pipelining assembly into the submission loop would pace
        the ramp at the assembly interval, and Little's law would cap the observed
        in-flight peak at `call_duration / assembly_interval` — a figure set by the
        assembler's speed, not by the governor. With the payloads pre-built, calls
        run on a thread pool bounded by `min(len(batch), effective)` and the pool
        width IS the observable in-flight concurrency the governor's ceiling governs
        (`FR-ORCH-21`; the seam's spy counts the peak — the caller bounds a batch to
        `effective` so the pre-assembly latency is bounded by the same figure). Every
        outcome is classified, never absorbed silently:

        - **Completion** — the real `Completion`: the unit closes (`complete`), and
          the answer's tokens, cost, cache prefix and resolved build accrue to the
          run's counters (`CT-PROV-11`'s shape — M-ORCH reads the provider's
          counters and persists them).
        - **`RateLimitedError`** (`RES-11`) — expected, not an error: the counters
          increment (the parsed `Retry-After` accrues to the honoured wait), the
          unit requeues **without consuming an attempt and without a unit-level
          error** (a rate limit is the provider's condition, not the unit's — §9.11),
          and the governor reduces next pass.
        - **`MemoryError`** (`RES-13`) — the box's condition: the unit requeues the
          same way (the box's condition is not the unit taxonomy's, §9.11), the cap
          reduces, and the OOM ladder's cumulative count may drop the judge from the
          panel.

        Any other exception propagates — an unexpected transport failure is a defect,
        and the units stay leased on the ledger where the sweeper reclaims them.
        Returns the number of units the batch closed — the walk's headway check.
        """
        if not batch:
            return 0
        workers = max(1, min(len(batch), effective))
        reduction = _env_int(CONCURRENCY_REDUCTION_ENV, CONCURRENCY_REDUCTION_DEFAULT)
        requeue_list: list[str] = []
        oomed: dict[str | None, list[str]] = {}
        completed = 0

        executor = self._stage_executor(state)
        governed = GovernedProvider(self._provider, state)
        paused: list[BaseException] = []

        run_unit = executor.execute  # bound first — see `_PreparedExecutor.execute`

        def invoke(unit: Any) -> Any:
            # The executor owns what a unit means; the counters are wrapped around the
            # provider it is handed, so a worker cannot spend calls this run does not count.
            return run_unit(unit, governed)

        # For the transport seam, assembly still completes for the WHOLE batch before the
        # pool exists — a raise here lands with nothing submitted, and the burst that follows
        # reaches the full pool width (the pipelined alternative would never be observed to).
        # A bound executor assembles inside its own worker, where the stage owns the door.
        executor.prepare(batch)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            submitted = [(unit, pool.submit(invoke, unit)) for unit in batch]
            for unit, future in submitted:
                try:
                    answer = future.result()
                except RateLimitedError as error:
                    self._absorb_rate_limit(state, error)
                    requeue_list.append(unit.work_id)
                    continue
                except MemoryError:
                    judge = unit.judge
                    oomed.setdefault(judge, []).append(unit.work_id)
                    requeue_list.append(unit.work_id)
                    continue
                except (ProviderUnavailableError, BuildChangedError) as error:
                    # `FR-ORCH-30` (V-1's pause half): the provider is gone, or answering as
                    # a different build. Neither is the unit's fault, so it requeues with its
                    # attempts untouched — and the RUN pauses (`FR-ORCH-16/17`), because every
                    # other unit is about to meet the same condition. The pass then stops
                    # rather than burning the batch against an outage.
                    requeue_list.append(unit.work_id)
                    paused.append(error)
                    continue
                if isinstance(answer, StageOutcome):
                    if not answer.completed:
                        # The worker struck the unit out inside its own budget. The calls it
                        # made are already on the run's counters; the unit goes back to
                        # pending for a later pass.
                        requeue_list.append(unit.work_id)
                        continue
                else:
                    self._absorb_completion(state, answer)
                # The swap's duration closes on the batch's first successful call
                # — the load rides that call, so the wall time from the boundary
                # to here is the duration the swap cost (`FR-ORCH-19`).
                started = state["residency"]["swap_started"]
                if started is not None:
                    state["residency"]["swap_ms"] += (
                        time.monotonic() - started
                    ) * 1000.0
                    state["residency"]["swap_started"] = None
                self.complete(unit.work_id)
                completed += 1
        if requeue_list:
            self._requeue_units(cohort, run_row["run_id"], requeue_list)
        if paused:
            self.pause(run_row["run_id"], cause=paused[0])
        for judge, ooms in oomed.items():
            self._oom_remedy(cohort, run_row, state, judge, ooms=len(ooms))
        if (requeue_list or oomed) and not state["reduced_this_pass"]:
            # The governor's reduction (`FR-ORCH-21`): once per pass, on the first
            # pass that saw a rate-limited or OOM call — applied NOW, not at the
            # next pass's start, so the report the caller is about to read carries
            # the reduced width (the operator reads the reduction that takes
            # effect, `RES-11`'s observable back-off).
            state["cap"] = max(state["cap"] // reduction, 1)
            state["reduced_this_pass"] = True
        return completed

    def _absorb_completion(self, state: dict[str, Any], answer: Any) -> None:
        """Accrue one successful model answer to the run's counters (`CT-PROV-11`).

        The method stays as the dispatch loop's name for it; the accrual itself is
        `_accrue_completion`, which `GovernedProvider` calls too — one definition, so the two
        seams cannot come to count differently."""
        _accrue_completion(state, answer)

    def _absorb_rate_limit(
        self, state: dict[str, Any], error: RateLimitedError
    ) -> None:
        """Count one rate-limited call and honour its `Retry-After` (`FR-PROV-07`).

        The honouring here is the dispatch's own half of §9.13: the wait the provider
        asked for accrues to the run's counter and the unit defers to a later pass at
        a reduced cap — the back-off is the deferral, not a sleep inside the dispatch
        loop (a loop that sleeps holds its worker hostage to the provider's clock).
        """
        with state["lock"]:
            state["rate_limited_calls"] += 1
            state["transport_retries"] += 1
            match = re.search(
                r"retry-after:\s*([0-9]*\.?[0-9]+)", str(error), re.IGNORECASE
            )
            if match:
                state["rate_limit_wait_s"] += float(match.group(1))

    def _oom_remedy(
        self,
        cohort: Any,
        run_row: Any,
        state: dict[str, Any],
        judge: str | None,
        *,
        ooms: int = 1,
    ) -> None:
        """The OOM ladder for one judge (`RES-13`, §9.11): reduce, retry, drop.

        The cumulative per-judge count is of OOM **calls** — every failed load counts,
        including the several one batch can produce — and the drop lands when the
        count reaches the threshold: the batch's own requeue IS the "retry" the
        ladder's remedy names (the units return to pending and are claimed again at
        the reduced cap before the panel ever shrinks). The drop removes the judge
        from the run's `panel_config` as a **strict subset, never below one judge**
        and records it in the run row — a later validation record cannot claim a
        panel the box could not hold (`CT-PROV-08`: drops, never substitutions). The
        dropped judge's un-run units stay in the ledger, pending, for an operator to
        re-queue under the smaller panel; the claim walk skips them — durably,
        reading the run row's own panels (`_dropped_judges`), so the skip survives a
        restart.
        """
        count = state["oom_counts"].get(judge, 0) + ooms
        state["oom_counts"][judge] = count
        threshold = _env_int(OOM_DROP_THRESHOLD_ENV, OOM_DROP_THRESHOLD_DEFAULT)
        if judge is None or count < threshold:
            return
        arms = self._panel_arms(run_row["panel_config"])
        if judge not in arms or len(arms) <= 1:
            return
        reduced = tuple(arm for arm in arms if arm != judge)
        # The reduced panel is written in `panel_config_json`'s canonical shape —
        # same separators, same sort — built from the arm STRINGS the row already
        # carries (the arms are build ids; the frozen row is the identity source).
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["record_reduced_panel"],
                panel_config=json.dumps(
                    {"arms": list(reduced)},
                    separators=_JSON_SEPARATORS,
                    sort_keys=True,
                ),
                run_id=run_row["run_id"],
            )
        # The panel the order cache was derived from no longer exists: every cached
        # order for the run is stale, and a claim that trusted it could hand out a
        # dropped judge's unit past the walk's skip. The skip itself needs no
        # in-memory mark — it reads the run row's OWN panels (frozen minus the
        # just-recorded reduction, `_dropped_judges`), so a fresh Orchestrator over
        # the same store skips the same units after a restart.
        self._invalidate_order_cache(run_row["run_id"])

    def _requeue_units(
        self, cohort: Any, run_id: str, work_ids: Sequence[str]
    ) -> None:
        """Return units to `pending` without consuming an attempt or writing an error.

        The transport-condition requeue (rate limit, OOM — `RES-11`, `RES-13`): the
        unit's failure history is not the provider's or the box's to write, and an
        attempt consumed here would quarantine a whole cohort under a sustained 429 —
        the exact failure `RES-11` forbids. One transaction, one guarded write per
        unit (the sweeper's own shape), and the order cache drops so the very next
        claim pass sees the requeued units (`TC-ORCH-18`).
        """
        requeued = 0
        with cohort.transaction() as tx:
            for work_id in work_ids:
                tx.execute(ORCH_STATEMENTS["requeue_expired"], work_id=work_id)
                requeued += int(
                    tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"]
                )
        if requeued:
            self._invalidate_order_cache(run_id)

    def _progress_report(
        self,
        cohort: Any,
        run_row: Any,
        run_id: str,
        state: dict[str, Any] | None,
    ) -> ProgressReport:
        """Build the report from the ledger's own aggregates (`FR-ORCH-23`).

        Every figure is a count of rows — the ledger is the only bookkeeping, so a
        report computed from anything else would drift on exactly the growing ledger
        `CT-ORCH-09` exists for. The position fields walk the first open unit: its
        stage, and its criterion's and judge's 1-based positions in the run's
        criterion list and panel order — with no open work the report points at the
        end of both axes. The estimate feeds `estimated_completion_seconds` the
        ledger's own totals and the observed escalation rate (`FR-ORCH-24`), and the
        completion predicate is ledger-derived (`FR-ORCH-12`): nothing pending, and
        no in-flight unit — a scoring judgment in flight can still disagree with its
        panel and spawn an escalation, so a run with one is not done.
        """
        counts: dict[str, int] = {}
        for row in cohort.query(
            ORCH_STATEMENTS["select_run_status_counts"], run_id=run_id
        ):
            counts[row["status"]] = int(row["n"])
        done = counts.get("done", 0)
        in_flight = counts.get("leased", 0)
        pending = counts.get("pending", 0)
        quarantined = counts.get("quarantined", 0)
        by_unit: dict[tuple[str, str | None, str | None], int] = {}
        for row in cohort.query(ORCH_STATEMENTS["select_run_by_unit"], run_id=run_id):
            by_unit[(row["stage"], row["criterion_id"], row["judge_id"])] = int(
                row["n"]
            )
        # The criterion axis rides the same aggregate (see the statement's note):
        # every criterion the ledger holds appears in some group's key.
        criteria = sorted({criterion for _, criterion, _ in by_unit})
        arms = self._panel_arms(run_row["panel_config"])
        open_rows = cohort.query(
            ORCH_STATEMENTS["select_run_first_open"], run_id=run_id
        )
        first = open_rows[0] if open_rows else None
        stage = first["stage"] if first is not None else STAGE_SCORE
        criterion_index = (
            criteria.index(first["criterion_id"]) + 1
            if first is not None and first["criterion_id"] in criteria
            else len(criteria)
        )
        judge_index = (
            arms.index(first["judge_id"]) + 1
            if first is not None and first["judge_id"] in arms
            else len(arms)
        )
        _processed, _escalated, rate = self._escalation_rate(cohort.query, run_id)
        # `FR-ORCH-33`: ONE elapsed reading, the ledger's, for both the dispatching and
        # the report-only path. The monotonic branch measured how long this PROCESS had
        # been running, so a resumed run extrapolated its throughput from the restart —
        # and a run paused overnight extrapolated it from the pause. The wall clock
        # excludes paused intervals, which is what makes it a throughput window rather
        # than a stopwatch left running.
        elapsed = self._run_wall_clock_ms(cohort, run_id) / 1000.0
        estimate = estimated_completion_seconds(
            completed=done,
            remaining=pending + in_flight,
            elapsed_seconds=elapsed,
            escalation_rate_so_far=rate,
        )
        report = ProgressReport(
            stage=stage,
            criterion_index=criterion_index,
            criterion_total=len(criteria),
            judge_index=judge_index,
            judge_total=len(arms),
            done=done,
            in_flight=in_flight,
            pending=pending,
            quarantined=quarantined,
            escalation_rate_so_far=rate,
            estimated_completion=estimate,
        )
        leased_score = int(
            cohort.query(
                ORCH_STATEMENTS["select_run_leased_score"], run_id=run_id
            )[0]["n"]
        )
        # The report's concurrency is the cap the NEXT pass will run at (the
        # reduction a 429/OOM landed this pass is already in `cap`; the backpressure
        # clamp is sensed again at flush time — the operator reads the width that
        # takes effect, `RES-11`/`RES-13`'s observable back-off, and a store still
        # signalling pressure reads as the clamped width).
        concurrency = 0
        if state is not None:
            concurrency = state["cap"]
            if store_metrics(self._store).get("backpressure_active"):
                concurrency = max(
                    concurrency
                    // _env_int(
                        BACKPRESSURE_DIVISOR_ENV, BACKPRESSURE_DIVISOR_DEFAULT
                    ),
                    1,
                )
        object.__setattr__(
            report,
            "_extras",
            {
                "complete": pending == 0 and in_flight == 0 and leased_score == 0,
                "concurrency": concurrency,
                "by_unit": by_unit,
                # `FR-ORCH-32`: the five §3.7 conditions, evaluated over state this pass
                # already read. The rules live in a pure function so they can be
                # exercised one condition at a time; `progress()` is where the operator
                # actually meets them.
                "alerts": self._run_alerts(cohort, run_id, run_row, rate),
            },
        )
        return report

    def _run_alerts(
        self, cohort: Any, run_id: str, run_row: Any, rate: float
    ) -> tuple[RunAlert, ...]:
        """The run's fired alerts (`FR-ORCH-32`), gathered from the ledger and evaluated.

        Gathering is here and the RULES are in `evaluate_alerts`: the split is what keeps
        each condition independently breachable without a store (`TC-ORCH-36`'s rung), and
        what stops the thresholds being spelled twice.
        """
        snapshot = _provider_config(run_row)
        ceiling = snapshot.get("cost_ceiling")
        budget_state = {
            "escalation_rate": rate,
            "ceiling": _as_float(ceiling) if ceiling is not None else 0.0,
            "spend": _as_float(_mapping_get(run_row, "cost_spend")),
        }
        # The RUN-scoped read: `select_breaker` answers about one criterion, and the
        # alert is about the run having any tripped breaker at all.
        breaker_rows = cohort.query(
            ORCH_STATEMENTS["select_run_breakers"], run_id=run_id
        )
        # This run's cache hit rate, and the rates EVERY OTHER RUN IN THE STORE recorded
        # — the baseline a collapse is measured against. Without enough history there is
        # no baseline and `evaluate_alerts` declines to fire, the honest answer for a
        # first run. The baseline is deliberately unscoped and unwindowed for now, which
        # is a calibration weakness disclosed on #370: runs of different packages, panels
        # and backends widen the variance, and a wide variance is what lets a genuine
        # collapse sit inside the sigma band.
        durable = self._store.durable()
        # `-1.0` is `evaluate_alerts`' declared "not measured" sentinel, and starting at
        # 0.0 instead defeated it: `progress()` evaluates alerts BEFORE the pass flushes,
        # so every run's first poll in a store with enough prior runs reported a perfect
        # cache as a total collapse. A rate nobody has measured is not a rate of zero.
        current = -1.0
        tokens_in = 0.0
        for row in durable.query(
            ORCH_STATEMENTS["select_run_metric_values"], run_id=run_id
        ):
            metric = str(_mapping_get(row, "metric", ""))
            if metric == "cache_hit_rate":
                current = _as_float(_mapping_get(row, "value"), -1.0)
            elif metric == "tokens_in":
                tokens_in = _as_float(_mapping_get(row, "value"))
        if tokens_in <= 0:
            # `_flush_run_metrics` records `cache_hit_rate = 0.0` for a pass that sent no
            # tokens, because the field is under CT-ORCH-20's set-equality contract and
            # cannot be omitted. A run that has dispatched nothing — idle, paused,
            # enumerated but not started — has no cache behaviour to judge, so that zero
            # is read here as the absence it is rather than as a collapse that would
            # alert forever.
            current = -1.0
        history = [
            _as_float(_mapping_get(row, "value"))
            for row in durable.query(
                ORCH_STATEMENTS["select_prior_cache_hit_rates"], run_id=run_id
            )
        ]
        return evaluate_alerts(
            run_row=run_row,
            metrics={"escalation_rate": rate, "cache_hit_rate": current},
            breaker_rows=breaker_rows,
            budget_state=budget_state,
            cache_history=history,
        )

    def _flush_run_metrics(
        self,
        cohort: Any,
        run_id: str,
        state: dict[str, Any],
        report: ProgressReport,
    ) -> None:
        """Persist the pass's cumulative signals into `run_metrics` (`CT-ORCH-20`).

        M-ORCH is the table's sole writer (`CT-STORE-03`): the dispatch loop's own
        counters plus the ledger-derived totals, written at the end of every pass —
        a poll that flushes nothing would leave `M-STATS` reading a stale record on
        exactly the runs an operator is watching. The totals are computed FROM the
        ledger at flush time (the report's own counts), so a metric can never tell a
        different story from the rows it summarizes.
        """
        escalated = int(
            cohort.query(
                ORCH_STATEMENTS["select_run_escalation_units"], run_id=run_id
            )[0]["n"]
        )
        total_units = report.done + report.in_flight + report.pending + (
            report.quarantined
        )
        tokens_in = state["tokens_in"]
        metrics: dict[str, Any] = {
            "transport_retries": float(state["transport_retries"]),
            "rate_limited_calls": float(state["rate_limited_calls"]),
            "rate_limit_wait_s": float(state["rate_limit_wait_s"]),
            "tokens_in": float(tokens_in),
            "tokens_out": float(state["tokens_out"]),
            "cache_hit_rate": (
                state["cache_tokens"] / tokens_in if tokens_in else 0.0
            ),
            "total_units": float(total_units),
            "escalated_units": float(escalated),
            "quarantined_units": float(report.quarantined),
            "wall_clock_ms": self._run_wall_clock_ms(cohort, run_id),
            "peak_concurrency": float(state["peak_concurrency"]),
            "estimated_completion_s": float(report.estimated_completion),
            "actual_cost": float(state["cost"]),
            "model_swap_count": float(state["residency"]["swaps"]),
            "model_swap_duration_ms": float(state["residency"]["swap_ms"]),
        }
        # TEXT rides the REAL-affinity column as TEXT: these are labels, not
        # measurements, and the EAV shape carries both.
        if state["resolved_build"]:
            metrics["resolved_build"] = state["resolved_build"]
        # `FR-ORCH-33`: the SET over the run, as a JSON list. A run can resolve more than
        # one build — a judge dropped after an OOM, a panel narrowed mid-run — and the
        # singular column recorded only whichever one landed first, which is the least
        # interesting of them. Sorted, so two runs that resolved the same builds write
        # the same bytes (`NFR-ORCH-05`).
        resolved = self._run_resolved_builds(cohort, run_id, state)
        if resolved:
            metrics["resolved_builds"] = json.dumps(
                resolved, separators=_JSON_SEPARATORS
            )
        run_row = self._run_row_in(cohort, run_id)
        if run_row is not None:
            estimate = _mapping_get(run_row, "cost_estimate")
            if estimate is not None:
                metrics["estimated_cost"] = str(estimate)
            # `cost_currency` and `retention_setting` live in the run's FROZEN backend
            # snapshot (`run.provider_config`), not in current configuration: a metric
            # about a run must describe the run as it was started, and reading today's
            # config would relabel a finished run's figures on the next poll.
            snapshot = _provider_config(run_row)
            for key in ("cost_currency", "retention_setting"):
                value = snapshot.get(key)
                if value is not None:
                    metrics[key] = str(value)
        self.record_run_metrics(run_id, metrics)

    def _run_row_in(self, cohort: Any, run_id: str) -> Any:
        """The run's row from a cohort handle the caller already holds.

        Distinct from `_run_row(run_id)`, which WALKS the cohort files to find which one
        owns the run. Both flush and report already know the cohort, so re-walking would
        open every cohort file to answer a question the caller had answered."""
        rows = cohort.query(ORCH_STATEMENTS["select_run"], run_id=run_id)
        return rows[0] if rows else None

    def _run_wall_clock_ms(self, cohort: Any, run_id: str) -> float:
        """`FR-ORCH-33`: elapsed since `run.started_at`, less every paused interval.

        Read from the LEDGER, never from `time.monotonic()`. A monotonic anchor measures
        how long *this process* has been running, so a run resumed after a restart
        reported a clock that began at the restart — and a run paused overnight reported
        the pause as work. Both readings are wrong in the direction that flatters the
        run, which is the direction an operator cannot afford.
        """
        run_row = self._run_row_in(cohort, run_id)
        started_at = _mapping_get(run_row, "started_at") if run_row is not None else None
        if not started_at:
            return 0.0
        now = _now()
        elapsed = _millis_between(started_at, now)
        paused = paused_milliseconds(
            cohort.query(ORCH_STATEMENTS["select_applied_control"], run_id=run_id),
            now=now,
        )
        return max(elapsed - paused, 0.0)

    def _run_resolved_builds(
        self, cohort: Any, run_id: str, state: Mapping[str, Any]
    ) -> list[str]:
        """Every build this run resolved, as a sorted set. The pass's own answer plus
        whatever earlier passes already recorded, so a restart does not shorten the
        list to just what this process happened to see."""
        seen: set[str] = set()
        if state.get("resolved_build"):
            seen.add(str(state["resolved_build"]))
        # `run_metrics` is Tier D (`record_run_metrics` writes it there), so the prior
        # passes' rows are read from the durable handle, not the cohort's.
        for row in self._store.durable().query(
            ORCH_STATEMENTS["select_run_metric_values"], run_id=run_id
        ):
            metric = str(_mapping_get(row, "metric", "") or "")
            value = _mapping_get(row, "value")
            if metric == "resolved_build" and value:
                seen.add(str(value))
            elif metric == "resolved_builds" and value:
                try:
                    seen.update(str(item) for item in json.loads(str(value)))
                except (ValueError, TypeError):
                    continue
        return sorted(seen)

    def record_run_metrics(self, run_id: str, metrics: Mapping[str, Any]) -> None:
        """Write one run's metrics as EAV rows — the write `CT-ORCH-20` makes contract.

        **A reserved name, landed** (`#65` reserved it for TS-25; the design's Protocol
        has no metrics member): whether the dispatch flushes through it internally or a
        caller records explicitly, the write is this method's — one transaction, one
        REPLACE per metric, so a re-flush updates in place and the table never holds
        two rows for one signal. M-ORCH is `run_metrics`' sole writer (`CT-STORE-03`).
        """
        if not metrics:
            return
        durable = self._store.durable()
        with durable.transaction() as tx:
            for name, value in metrics.items():
                tx.execute(
                    ORCH_STATEMENTS["insert_run_metric"],
                    run_id=run_id,
                    metric=str(name),
                    value=value,
                )


# --- the audit record (TC-CONF-17's producer) ---------------------------------------------------


def record_run_start(
    store: Any, config: Any, *, run_id: str | None = None, summary: Any = None
) -> str:
    """Write the run-start audit record: the orchestrator's write of what graded this run.

    **Invented here** — the name appears in no Interfaces block (checked: zero occurrences
    in either design document), which is exactly why it is this module's to define: the
    store keeps the row, the orchestrator owns what it means.

    The stored summary is `config.profile_summary().to_canonical_json()` — the **same
    serializer** `log_run_start` puts on the log line, which is what makes TC-CONF-17's
    differential ("the stored profile_summary is byte-identical to the one logged at run
    start") a property of the code rather than a hope. Reaching for `json.dumps(asdict(...))`
    here is the defect that case exists to catch.

    `run_id` is minted when the caller has none (an audit row's id needs uniqueness, not
    determinism); `create_run` passes the run's own id so the record names the run it
    belongs to. Returns the run id written.

    `summary` is the `ProfileSummary` `log_run_start` returned, when the caller logged the
    run start (`Orchestrator.create_run` does): storing that object rather than computing a
    second one makes the stored record literally the logged one. Omitted, the summary is
    computed here, as the repair path in `create_run`'s docstring needs.
    """
    if summary is None:
        summary = config.profile_summary()
    resolved_run_id = run_id if run_id is not None else f"run-{uuid.uuid4().hex}"
    durable = store.durable()
    with durable.transaction() as tx:
        tx.execute(
            ORCH_STATEMENTS["insert_audit_record"],
            audit_record_id=uuid.uuid4().hex,
            run_id=resolved_run_id,
            recorded_at=_now(),
            profile_summary=summary.to_canonical_json(),
        )
    return resolved_run_id


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
