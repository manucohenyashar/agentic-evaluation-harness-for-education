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

**Not in this slice, and deliberately so.** Leasing, heartbeats and the expiry sweeper are
#58's; the two-sweep execution plan, dependency ordering, deterministic-unit admission and
the `ingest_status` admission filter are #59's; escalation, the random arm and the circuit
breakers are #60's; the control-row run lifecycle (start/pause status transitions) is
#61's; dispatch isolation, concurrency and `ProgressReport` are #62's. The `run` row is
created in `status='pending'` and #57 flips no status: the lifecycle is #61's.

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
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from aeh.store import (
    TIER_MIGRATIONS,
    Migration,
    Statement,
    Tier,
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

TIER_MIGRATIONS[Tier.COHORT] = TIER_MIGRATIONS[Tier.COHORT] + (
    Migration(version=7, name="orch_run_ledger", statements=_ORCH_COHORT_007),
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
    ) -> None:
        self._store = store
        self._package_id_for = package_id_for
        #: Maps the store to its cohort tier keys, for the run discovery `resume()` does
        #: with no arguments. Default: the `cohorts/` directory under the store's data
        #: dir — the ledger's own files are the bookkeeping, which is the whole point of
        #: `FR-ORCH-02`. Injectable so a double-backed test can pin discovery.
        self._cohort_keys_for = cohort_keys_for or _cohort_keys_on_filesystem

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
