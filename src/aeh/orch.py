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

**Not in this slice, and deliberately so.** The two-sweep execution plan, dependency
ordering, deterministic-unit admission and the `ingest_status` admission filter are #59's;
escalation, the random arm and the circuit breakers are #60's; the control-row run
lifecycle (start/pause status transitions), the cost ceiling and provider pauses are
#61's; dispatch isolation, concurrency and `ProgressReport` are #62's. The `run` row is
created in `status='pending'` and no story before #61 flips it: the lifecycle is #61's.

**The four seams** (CLAUDE.md): the orchestrator runs end-to-end from code and returns a
structured result with per-gate detail (`EnumerationReport`, the `IngestReport.gates`
precedent); it has no external dependency to transport — the store arrives by injection
and no judge is ever contacted here, so the run needs no network; the one
environment-sensitive constant (enumeration commit batch) is env-gated and read at call
time; and every report carries stage-level detail rather than a bare status.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from aeh.store import (
    TIER_MIGRATIONS,
    LeaseClock,
    Migration,
    Statement,
    Tier,
    lease_clock,
)

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


class RunNotFoundError(WorkLedgerError):
    """No run row carries the id the caller named. Raised rather than guessed at: resume
    with no arguments finds its own runs, so an explicit `run_id` that resolves to nothing
    is a caller mistake worth naming."""


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


# --- the runtime statements (declared, never assembled — FR-STORE-08, SEC-15) -------------------

ORCH_STATEMENTS: dict[str, Statement] = {
    "insert_run": Statement(
        "INSERT INTO run (run_id, cohort_id, package_version_id, package_id, "
        "panel_config, backend_profile, provider_config, prompt_template_v, status) "
        "VALUES (:run_id, :cohort_id, :package_version_id, :package_id, :panel_config, "
        ":backend_profile, :provider_config, :prompt_template_v, 'pending')"
    ),
    "select_run": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id, panel_config, "
        "backend_profile, provider_config, prompt_template_v, status, started_at, "
        "completed_at FROM run WHERE run_id = :run_id"
    ),
    # The runs resume() may drive: everything not yet finished. Ordered by run_id so two
    # enumerations of the same state walk the same rows in the same order (NFR-ORCH-05).
    "select_open_runs": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id, panel_config, "
        "backend_profile, provider_config, prompt_template_v, status, started_at, "
        "completed_at FROM run WHERE status IN ('pending', 'running', 'paused') "
        "ORDER BY run_id"
    ),
    "select_run_work_ids": Statement(
        "SELECT work_id FROM work_unit WHERE run_id = :run_id"
    ),
    "select_submissions": Statement(
        "SELECT submission_id, student_ref FROM submission WHERE cohort_id = :cohort_id "
        "ORDER BY submission_id"
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
    # Claim candidates: pending units of one stage, on runs that are still dispatching
    # (a paused run schedules nothing — CT-ORCH-12; that transition is #61's, and the
    # filter here is where it will bite first). Ordered by work_id so two claimers walk
    # the same candidates in the same order — determinism the scheduling tests can stand
    # on — and limited to what the caller asked for.
    "select_claimable": Statement(
        "SELECT w.work_id, w.run_id, w.stage, w.submission_id, w.criterion_id, "
        "w.judge_id, w.attempts AS attempt, s.student_ref AS student_ref "
        "FROM work_unit w "
        "JOIN run r ON r.run_id = w.run_id "
        "JOIN submission s ON s.submission_id = w.submission_id "
        "WHERE w.status = 'pending' AND w.stage = :stage "
        "AND r.status IN ('pending', 'running') "
        "ORDER BY w.work_id LIMIT :n"
    ),
    "select_work_unit": Statement(
        "SELECT * FROM work_unit WHERE work_id = :work_id"
    ),
    "select_leased_units": Statement(
        "SELECT w.work_id, w.lease_expires_ticks FROM work_unit w "
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
    # The heartbeat: extends a live lease's expiry only — a requeued unit is not this
    # worker's anymore, and the guard makes that refusal a zero-row write.
    "extend_lease": Statement(
        "UPDATE work_unit SET lease_expires_ticks = :expires_ticks, "
        "lease_expires_at = :expires_at "
        "WHERE work_id = :work_id AND status = 'leased'"
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
        "lease_expires_ticks = NULL, lease_expires_at = NULL "
        "WHERE work_id = :work_id AND status IN ('leased', 'pending')"
    ),
    # The failure taxonomy: requeue with the attempt counted, or quarantine at the
    # ceiling — last_error retained in both arms, lease columns cleared. The status arm
    # is a bound parameter (a value, not an identifier) so requeue and quarantine are
    # one declared statement and the two arms cannot drift apart.
    "record_failure": Statement(
        "UPDATE work_unit SET status = :status, attempts = :attempts, "
        "last_error = :last_error, lease_owner = NULL, "
        "lease_expires_ticks = NULL, lease_expires_at = NULL "
        "WHERE work_id = :work_id AND status IN ('leased', 'pending')"
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


def _now() -> str:
    """The one wall-clock read the ledger writes, UTC ISO-8601 (`ingest._now`'s form)."""
    return datetime.now(timezone.utc).isoformat()


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
class SweeperReport:
    """What one lease-expiry sweep did (`CLAUDE.md` seam 4).

    A bare count would be the silent-failure shape — a sweep that examined nothing and
    requeued nothing is indistinguishable from one that never ran — so the report names
    all three outcomes: `examined`, `requeued`, `still_held`, plus the `gates` detail
    (the `EnumerationReport`/`IngestReport.gates` precedent).
    """

    examined: int
    requeued: int
    still_held: int
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


class PackageCatalogProtocol(Protocol):
    """The slice of `PackageCatalog` enumeration reads. Typed as a protocol so a test
    double satisfies it without a Tier P file (`CLAUDE.md` seam 2 — no network, no real
    upstream; the package arrives by injection like every other dependency)."""

    def criteria(self, v: str, question_id: str | None = None) -> tuple: ...


class Orchestrator:
    """The ledger slice of §3.7's Orchestrator: create a run, enumerate its units,
    resume. Leasing, sweeps, escalation and the control-row lifecycle arrive with
    #58/#59/#60/#61 — the members here are the ones `FR-ORCH-01/02/03` and `NFR-ORCH-05`
    own, and `resume` takes no arguments from its first commit.

    The store is injected (`CLAUDE.md` seam 2). Nothing here opens a network connection
    or contacts a judge: enumeration is a pure function of the ledger, the package
    catalog and the roster, over an injected store.
    """

    def __init__(
        self,
        store: Any,
        *,
        package_id_for: Any = default_package_id_for,
        cohort_keys_for: Any = None,
        clock: Any = None,
    ) -> None:
        self._store = store
        self._package_id_for = package_id_for
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
        if run_id is None:
            run_id = f"run-{uuid.uuid4().hex}"
        panel_config = panel_config_json(cfg.panel)
        provider_config = json.dumps(
            {
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
        record_run_start(self._store, cfg, run_id=run_id)
        return run_id

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

        **Base shapes** (§3.7's data flow, as far as #57's slice reaches): a judged
        criterion (the catalog's `kind='open'`) gets one `stage='extract'` unit with a
        null judge — extraction is judge-independent by §7.2 Rule 2 — plus one
        `stage='score'` unit per panel arm up to the criterion's base depth
        (`FR-SETUP-08`: 1 for `atomic`/`atomic_with_gate`, 3 for `holistic`). An
        `kind='mcq'` criterion — deterministic evaluation, §7.8 — gets exactly one
        `stage='deterministic'` unit with a null judge and no extraction and no scoring
        unit. **Interpretation recorded on #57:** the design's `evaluation_mode` column
        does not exist until #59 adds it; the catalog's `kind` is the stand-in, and #59
        owns reconciling the two. Admission by `ingest_status` (FR-ORCH-22), sweep
        ordering, escalations and the random arm are later stories' — enumerated base
        units here are deliberately every (submission, criterion) pair the shapes above
        produce, with no admission filter.

        Commit batches of `HARNESS_ORCH_ENUM_COMMIT_BATCH` inserts keep one pass from
        holding a write lock across 23,000 inserts; the knob exists so a slower box can
        shrink it without a code change (NFR-ORCH-01 keeps per-unit cost trivial; the
        benchmark is S-ORCH-03's, not this module's).
        """
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

        batch = _env_int(ENUM_COMMIT_BATCH_ENV, ENUM_COMMIT_BATCH_DEFAULT)

        computed: list[tuple[str, dict[str, Any]]] = []
        for submission in submissions:
            for criterion in criteria:
                kind = criterion["kind"]
                if kind == "mcq":
                    computed.append(self._unit(
                        row, STAGE_DETERMINISTIC, submission, criterion, None,
                    ))
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

        The dispatch half of resume — leasing the pending units to workers — is #58's
        `lease` landing on this same ledger; the ledger half (nothing done is re-run,
        nothing lost, nothing duplicated) is complete here.
        """
        if run_id is not None:
            self.enumerate_units(run_id)
            return
        for open_run in self._open_run_ids():
            self.enumerate_units(open_run)

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
        base enumeration `resume()` uses — idempotent by construction — and claims
        again, so a caller that created a run and leased receives units without a
        separate enumerate step and a completed ledger costs one no-op pass. An empty
        return after that is a true empty (the stage's units are done, in flight, or
        the run is not dispatching), not a bookkeeping gap.

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
            # not silently receive zero units because the base enumeration had not been
            # run. Enumeration is idempotent by construction (`INSERT OR IGNORE` over
            # computed work ids), so the empty first pass triggers the exact mechanism
            # `resume()` uses, and the claim runs again against the completed ledger.
            # A lease that returns empty *after* that is a true empty: every unit of
            # the stage is done, in flight, or the run is not dispatching. The hot path
            # stays one claim query — the enumeration costs a full pass and pays for
            # itself only when the ledger is short of what the run owes.
            for open_run in self._open_run_ids():
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

        **Exclusivity is the guard on the write**, not the read: candidates are read
        `status = 'pending'`, the expiry is issued, and the claim is an
        `UPDATE ... WHERE status = 'pending'` whose `changes()` — read in the same
        transaction — decides whether *this* claim won. A claim that loses the guard
        writes nothing and returns nothing; the unit's new holder is whoever won. The
        lost-guard race leaves the persisted high-water raised by one unused expiry —
        the store's own stated conservatism (a restart expires every outstanding lease,
        `CT-STORE-14`), arrived at from the harmless side: a raised counter can only make
        the sweeper *more* willing to reclaim, never less.

        Claims walk cohorts and their open runs in sorted order and candidates by
        `work_id` — deterministic where nothing depends on it (the sweep order itself is
        #59's). A paused run schedules nothing (`CT-ORCH-12`): its units are not
        candidates.
        """
        ttl = self._lease_ttl()
        lease_clock_obj = self._lease_clock()
        claimed: list[Any] = []
        for key in self._cohort_keys():
            if len(claimed) >= n:
                break
            cohort = self._store.cohort(key)
            candidates = cohort.query(
                ORCH_STATEMENTS["select_claimable"], stage=stage, n=n - len(claimed)
            )
            for row in candidates:
                issued = lease_clock_obj.issue(ttl)
                expires_at = self._wall_expiry(lease_clock_obj.clock, ttl)
                with cohort.transaction() as tx:
                    tx.execute(
                        ORCH_STATEMENTS["mark_leased"],
                        work_id=row["work_id"],
                        owner=worker_id,
                        expires_ticks=issued.expires_ticks,
                        expires_at=expires_at,
                    )
                    won = int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"])
                if won:
                    claimed.append(row)
        return claimed

    def heartbeat(self, work_id: str) -> None:
        """Extend a live lease by another TTL — the while-it-works half of `FR-ORCH-04`.

        A slow-but-alive worker must not lose its unit at the original expiry: the
        heartbeat re-issues the lease from **now**, so the expiry moves out by a full
        TTL from the moment of the call. The re-issue goes through `LeaseClock.issue()`
        like every claim, so the persisted counter moves with it and the extension
        survives an uncontrolled kill.

        Refusals are named, never absorbed: a unit that is not `leased` (the sweeper
        requeued it, another worker completed it) or does not exist raises
        `WorkLedgerError` — a heartbeat that silently no-ops would let its caller keep
        working a unit it no longer holds, the double-run `CT-ORCH-04` warns of.
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
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["extend_lease"],
                work_id=work_id,
                expires_ticks=issued.expires_ticks,
                expires_at=expires_at,
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
        for key in self._cohort_keys():
            cohort = self._store.cohort(key)
            rows = cohort.query(ORCH_STATEMENTS["select_leased_units"])
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
                        requeued += int(
                            tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"]
                        )
            examined += len(rows)
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
        operator surface said what happened, and it must stay true. `result` is the
        worker's `WorkResult`; the ledger records the transition, the payload is the
        owning stage's to persist (#68 onward).
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
            tx.execute(ORCH_STATEMENTS["mark_done"], work_id=work_id)

    def fail(self, work_id: str, error: WorkError | str) -> None:
        """Count one failed attempt against a unit; requeue it, or quarantine it at the
        ceiling (`FR-ORCH-18`).

        The unit's `attempts` increments; below `ORCH_MAX_ATTEMPTS`
        (env: `HARNESS_ORCH_MAX_ATTEMPTS`) it returns to `pending` and is claimable
        again; at the ceiling it becomes `quarantined` with `last_error` retained —
        the operator surface can say *what* happened, not just that something did. Both
        arms clear the lease columns; the run continues either way — "fail the unit,
        never the run" (`NFR-ORCH-03`) is the whole point of the taxonomy, so no arm of
        this method raises into the caller's loop over a unit's own failure.

        Refusals stay narrow and named: a failure for a unit that does not exist, or
        one whose ledger state moved underneath the worker (a completion or a
        quarantine recorded between the read and the write), raises rather than
        guessing; a failure for an already-quarantined unit is a no-op — the record
        stands, and a duplicate report from an at-least-once worker must not
        double-count it.
        """
        max_attempts = _env_int(MAX_ATTEMPTS_ENV, ORCH_MAX_ATTEMPTS)
        message = error.message if isinstance(error, WorkError) else str(error)
        cohort, row = self._find_unit(work_id)
        if row["status"] == "quarantined":
            return
        if row["status"] == "done":
            raise WorkLedgerError(
                f"failure for unit {work_id[:12]} refused: the unit is 'done' — a "
                "completed unit cannot also have failed; whichever report is wrong is "
                "a caller bug worth naming, not a state to guess out of."
            )
        attempts = int(row["attempts"]) + 1
        status = "quarantined" if attempts >= max_attempts else "pending"
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["record_failure"],
                work_id=work_id,
                status=status,
                attempts=attempts,
                last_error=message,
            )
            won = int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"])
        if not won:
            raise WorkLedgerError(
                f"failure for unit {work_id[:12]} could not be recorded: the unit's "
                f"state moved from '{row['status']}' while the attempt was being "
                "counted. Re-read the ledger before reporting again."
            )

    # -- internals ------------------------------------------------------------------------------

    def _unit(
        self,
        row: Any,
        stage: str,
        submission: Any,
        criterion: Any,
        judge_id: str | None,
    ) -> tuple[str, dict[str, Any]]:
        """One computed unit: its `work_id` and its insert parameters.

        Kept beside `compute_work_id`'s call so the nine inputs' provenance is one
        glance: run and package from the run row, prompt template version from the
        frozen config, extractor version from the module constant, judge from the arm.
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
            "origin": "base",
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
        same reason."""
        from aeh.pkg import PackageCatalog

        return PackageCatalog(
            self._store.package(row["package_id"]),
            package_id=row["package_id"],
        )

    def _run_row(self, run_id: str) -> Any:
        """The run's ledger row, found by walking the cohort files.

        There is deliberately no index of run ids outside the ledger: the run row lives
        in its cohort's Tier C file (§9.6 puts run state beside cohort state), and a
        side index would be exactly the bookkeeping FR-ORCH-02 forbids. Cohort counts
        are small; a scan is a handful of indexed queries.
        """
        for key in self._cohort_keys():
            rows = self._store.cohort(key).query(
                ORCH_STATEMENTS["select_run"], run_id=run_id
            )
            if rows:
                return rows[0]
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

    def _open_run_ids(self) -> tuple[str, ...]:
        """Every not-yet-finished run, across every cohort ledger, in run-id order."""
        found: list[str] = []
        for key in self._cohort_keys():
            for row in self._store.cohort(key).query(ORCH_STATEMENTS["select_open_runs"]):
                found.append(row["run_id"])
        return tuple(sorted(found))


# --- the audit record (TC-CONF-17's producer) ---------------------------------------------------


def record_run_start(store: Any, config: Any, *, run_id: str | None = None) -> str:
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
    """
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
