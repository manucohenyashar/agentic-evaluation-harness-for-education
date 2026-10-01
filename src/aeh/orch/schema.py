"""The cohort-tier migrations M-ORCH contributes to the store."""

from __future__ import annotations

from aeh.store import TIER_MIGRATIONS, Migration, Statement, Tier


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


# --- Tier C, migration 31 (#527, CT-CONF-06 / FR-CONF-15): the frozen RunConfig, whole ------------
#
# `panel_config`/`provider_config` carry the forms M-ORCH reads (build ids, the arms), not the
# refs' providers, quantizations or the transcriber, so `rehydrate_run_config` could not read a
# run back. The whole `to_persisted_dict()` goes beside them; NULL on rows written before.
_ORCH_RUN_CONFIG = Migration(
    version=31,
    name="orch_run_config",
    statements=(Statement("ALTER TABLE run ADD COLUMN run_config TEXT"),),
)


TIER_MIGRATIONS[Tier.COHORT] = TIER_MIGRATIONS[Tier.COHORT] + (_ORCH_RUN_CONFIG,)
