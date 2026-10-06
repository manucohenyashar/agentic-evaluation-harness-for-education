"""The base schema of each tier, `Migration`, the `TIER_MIGRATIONS` chains and their pins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .interfaces import Statement, Tier


# --- the schema --------------------------------------------------------------------------------
#
# One numbered migration per tier so far. Each is a tuple of `Statement`s applied in order inside
# one transaction, and each creates the tables §3.3's data model names for that tier with a
# **minimal column set**: a primary key, the foreign keys the tier's own structure implies, and
# the columns a merged test already reads.
#
# That is the line between owning files and owning meaning. The owning module adds its columns in
# a later numbered migration (`ALTER TABLE ... ADD COLUMN`, which SQLite does in place) — so
# `M-PKG` decides what a criterion carries and `M-ORCH` decides what a work unit carries, while
# the file layout, the constraints and the version discipline stay here.
#
# Every statement below is a literal. `tests/artifact/test_store_query_surface.py` scans this
# tree for SQL assembled from anything else, and it is green today precisely because nothing here
# builds a statement.

_SCHEMA_VERSION_TABLE = Statement(
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version    INTEGER NOT NULL PRIMARY KEY,
        name       TEXT    NOT NULL,
        applied_at TEXT    NOT NULL
    )
    """
)


#: Tier P — `packages/<package_id>.pkg.sqlite`, permanent, no PII by construction.
_PACKAGE_001: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE package (
            package_id TEXT NOT NULL PRIMARY KEY,
            created_at TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE package_version (
            package_version_id TEXT    NOT NULL PRIMARY KEY,
            package_id         TEXT    NOT NULL REFERENCES package(package_id),
            revision           INTEGER NOT NULL CHECK (revision >= 0),
            locked             INTEGER NOT NULL DEFAULT 0 CHECK (locked IN (0, 1))
        )
        """
    ),
    Statement(
        """
        CREATE TABLE criterion (
            criterion_id       TEXT NOT NULL,
            package_version_id TEXT NOT NULL REFERENCES package_version(package_version_id),
            question_id        TEXT NOT NULL,
            kind               TEXT NOT NULL CHECK (kind IN ('open', 'mcq')),
            PRIMARY KEY (package_version_id, criterion_id)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE band (
            package_version_id TEXT    NOT NULL,
            criterion_id       TEXT    NOT NULL,
            ordinal            INTEGER NOT NULL CHECK (ordinal >= 0),
            band               TEXT    NOT NULL,
            points             REAL    NOT NULL CHECK (points >= 0),
            PRIMARY KEY (package_version_id, criterion_id, ordinal),
            FOREIGN KEY (package_version_id, criterion_id)
                REFERENCES criterion(package_version_id, criterion_id)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE criterion_dependency (
            package_version_id TEXT NOT NULL,
            criterion_id       TEXT NOT NULL,
            depends_on         TEXT NOT NULL,
            PRIMARY KEY (package_version_id, criterion_id, depends_on),
            FOREIGN KEY (package_version_id, criterion_id)
                REFERENCES criterion(package_version_id, criterion_id),
            CHECK (criterion_id <> depends_on)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE exemplar (
            exemplar_id        TEXT NOT NULL PRIMARY KEY,
            package_version_id TEXT NOT NULL,
            criterion_id       TEXT NOT NULL,
            band               TEXT NOT NULL,
            FOREIGN KEY (package_version_id, criterion_id)
                REFERENCES criterion(package_version_id, criterion_id)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE grade_policy (
            package_version_id TEXT NOT NULL PRIMARY KEY
                REFERENCES package_version(package_version_id),
            policy             TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE validation_record (
            validation_record_id TEXT NOT NULL PRIMARY KEY,
            package_version_id   TEXT NOT NULL REFERENCES package_version(package_version_id),
            backend_profile      TEXT NOT NULL,
            panel_build_ref      TEXT NOT NULL,
            recorded_at          TEXT NOT NULL
        )
        """
    ),
)


#: Tiers C and R — `cohorts/<cohort_id>.sqlite`, one file, per administration, heavy PII.
#: C first, then R: R's rows reference C's, and SQLite checks a foreign key against a table that
#: must already exist.
_COHORT_001: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE cohort (
            cohort_id     TEXT NOT NULL PRIMARY KEY,
            consent_class TEXT NOT NULL CHECK (consent_class IN ('synthetic', 'consented', 'real')),
            created_at    TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE roster (
            cohort_id   TEXT NOT NULL REFERENCES cohort(cohort_id),
            student_ref TEXT NOT NULL,
            PRIMARY KEY (cohort_id, student_ref)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE submission (
            submission_id TEXT NOT NULL PRIMARY KEY,
            cohort_id     TEXT NOT NULL REFERENCES cohort(cohort_id),
            student_ref   TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE document (
            document_id   TEXT NOT NULL PRIMARY KEY,
            submission_id TEXT NOT NULL REFERENCES submission(submission_id),
            content_hash  TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE document_region (
            region_id    TEXT    NOT NULL PRIMARY KEY,
            document_id  TEXT    NOT NULL REFERENCES document(document_id),
            page_no      INTEGER NOT NULL CHECK (page_no >= 1),
            element_kind TEXT    NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE work_unit (
            work_id       TEXT NOT NULL PRIMARY KEY,
            submission_id TEXT REFERENCES submission(submission_id),
            stage         TEXT NOT NULL,
            status        TEXT NOT NULL
                CHECK (status IN ('pending', 'leased', 'done', 'failed', 'quarantined'))
        )
        """
    ),
    Statement(
        """
        CREATE TABLE evidence (
            evidence_id TEXT NOT NULL PRIMARY KEY,
            work_id     TEXT NOT NULL REFERENCES work_unit(work_id),
            document_id TEXT REFERENCES document(document_id)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE verdict (
            verdict_id TEXT NOT NULL PRIMARY KEY,
            work_id    TEXT NOT NULL REFERENCES work_unit(work_id),
            judge_id   TEXT NOT NULL,
            band       TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE criterion_score (
            submission_id TEXT NOT NULL REFERENCES submission(submission_id),
            criterion_id  TEXT NOT NULL,
            band          TEXT NOT NULL,
            PRIMARY KEY (submission_id, criterion_id)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE submission_grade (
            submission_id TEXT    NOT NULL REFERENCES submission(submission_id),
            revision      INTEGER NOT NULL CHECK (revision >= 0),
            PRIMARY KEY (submission_id, revision)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE narrative (
            narrative_id  TEXT NOT NULL PRIMARY KEY,
            submission_id TEXT NOT NULL REFERENCES submission(submission_id),
            criterion_id  TEXT
        )
        """
    ),
    Statement(
        """
        CREATE TABLE review_queue (
            queue_id      TEXT NOT NULL PRIMARY KEY,
            submission_id TEXT NOT NULL REFERENCES submission(submission_id),
            criterion_id  TEXT,
            reason        TEXT NOT NULL
        )
        """
    ),
)


#: Tier D — `durable.sqlite`, permanent, pseudonymized.
#:
#: No column here is a student name and none ever may be: Tier D survives the cohort purge, so a
#: name that reaches it outlives every mechanism built to remove it (`FR-STORE-12`,
#: `CT-STORE-09`). `student_ref` is the only identity column, and `TC-STATS-C18` sweeps this
#: schema for the alternatives.
_DURABLE_001: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE audit_record (
            audit_record_id TEXT NOT NULL PRIMARY KEY,
            run_id          TEXT NOT NULL,
            recorded_at     TEXT NOT NULL,
            profile_summary TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE label (
            label_id     TEXT NOT NULL PRIMARY KEY,
            run_id       TEXT NOT NULL,
            student_ref  TEXT,
            criterion_id TEXT NOT NULL,
            label_type   TEXT NOT NULL,
            band         TEXT NOT NULL
        )
        """
    ),
    Statement(
        """
        CREATE TABLE criterion_stats (
            package_version_id TEXT    NOT NULL,
            criterion_id       TEXT    NOT NULL,
            backend_profile    TEXT    NOT NULL,
            panel_build_ref    TEXT    NOT NULL,
            n                  INTEGER NOT NULL CHECK (n >= 0),
            PRIMARY KEY (package_version_id, criterion_id, backend_profile, panel_build_ref)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE mcq_item_stats (
            package_version_id TEXT    NOT NULL,
            criterion_id       TEXT    NOT NULL,
            option             TEXT    NOT NULL,
            chosen             INTEGER NOT NULL CHECK (chosen >= 0),
            PRIMARY KEY (package_version_id, criterion_id, option)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE mcq_item_summary (
            package_version_id TEXT NOT NULL,
            criterion_id       TEXT NOT NULL,
            PRIMARY KEY (package_version_id, criterion_id)
        )
        """
    ),
    Statement(
        """
        CREATE TABLE run_metrics (
            run_id     TEXT NOT NULL,
            metric     TEXT NOT NULL,
            value      REAL NOT NULL,
            PRIMARY KEY (run_id, metric)
        )
        """
    ),
)


@dataclass(frozen=True)
class Migration:
    """One numbered, forward-only schema change.

    Forward-only and reversible **only by restoring a copy** (`NFR-STORE-04`). There is no `down`
    field and there will not be one: a reversal that runs against production data is how a
    migration that was wrong becomes two migrations that are wrong.
    """

    version: int
    name: str
    statements: tuple[Statement, ...]


class MigrationPrecondition(Statement):
    """A read declared inside a migration whose result decides whether the migration may run.

    `_migrate` runs it like any other statement, in the migration's own transaction, and hands
    the fetched rows to `check`, which raises `MigrationError` to refuse — the refusal rolls the
    whole migration back. SQL alone cannot refuse with a message naming a count (`RAISE` is
    trigger-only and takes a literal), which is why this exists (#359). A statement rather than
    a `Migration` field: a migration stays version + name + statements (`TC-STORE-06`), and a
    raw replay of a chain's statements (F-SCHEMA's fixture builders) runs the read harmlessly.
    Constructed without a `check`, it is an ordinary statement.
    """

    def __new__(
        cls, sql: str, check: Callable[[list[Any]], None] | None = None
    ) -> "MigrationPrecondition":
        declared = super().__new__(cls, sql)
        declared.check = check
        return declared


#: Migration 2 for Tier D: the monotonic lease counter (`FR-STORE-11`), added by #12.
#:
#: **Tier D, and forward-only as a second numbered migration** rather than an edit to
#: `_DURABLE_001`. `FR-STORE-02` makes migrations forward-only and numbered and `NFR-STORE-04`
#: says a migration is "reversible only by restoring a copy", so editing the first one would
#: silently disagree with every database already at version 1. Tier D because the counter must
#: outlive a cohort: it is the one tier `purge_cohort` does not touch (§3.3), and a lease counter
#: reset by a purge is a lease counter that can move backwards.
#:
#: This is `M-STORE`'s own bookkeeping, not schema *meaning* — the same footing as
#: `schema_version`. Nothing here says what a lease is *for*; that is `M-ORCH`'s ledger.
#:
#: One row, enforced by the CHECK. A second row would make "the persisted counter" ambiguous at
#: exactly the moment it has to be trusted.
_DURABLE_002: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE store_lease_clock (
            id         INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
            ticks      REAL    NOT NULL,
            wall_clock TEXT    NOT NULL
        )
        """
    ),
)


# --- Tier D, migration 11 (#375, `FR-CALIB-15`): the dual-scored roster ----------------------
#
# **Declared here rather than in `aeh.calib`, deliberately.** CLAUDE.md's convention is that a
# migration is owned by the module that owns the schema it adds, and by that rule this belongs
# to M-CALIB. `TC-REQ-89` outranks the convention: the console must render with M-CALIB absent
# (`sys.modules["aeh.calib"] = None`), so a module the system is contractually required to run
# WITHOUT cannot own a mandatory link in a tier's chain — every durable open in that world
# would refuse with `IncompleteMigrationChainError`. `FR-CALIB-15` names the table, never its
# owner. `aeh.store` is unconditionally imported, so the chain is complete in both worlds, and
# it already declares other modules' base tables for the same reason (`criterion_score`,
# `label`, `submission_grade`). Do not move this into `aeh.calib`.
#
# `_CLASS_ROSTERS` is a module-level dict in M-CALIB, so a roster registered into it alone
# survives exactly as long as the process does — and the operator who runs the non-inferiority
# gate on Monday and again on Tuesday is a new process (`CT-CALIB-17`). This is where a
# registered roster actually lives; that dict is a cache of it.
#
# Tier D's standing rule holds: no column here is a student name and none ever may be.
# `paper_id` carries the submission id, which is what `M-REVIEW` already writes into Tier D's
# own identity column (`review.py:2769`) — a keyed reference to the work, never a name.
#
# The primary key is the comparison plus the cell: one cohort can be dual-scored under more
# than one (R₀, R₁) pair over its life, and each such comparison has its own roster.
_DURABLE_011: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE calib_roster (
            cohort_id    TEXT NOT NULL,
            r0           TEXT NOT NULL,
            r1           TEXT NOT NULL,
            paper_id     TEXT NOT NULL,
            criterion_id TEXT NOT NULL,
            r0_band      TEXT NOT NULL,
            r1_band      TEXT NOT NULL,
            recorded_at  TEXT NOT NULL,
            PRIMARY KEY (cohort_id, r0, r1, paper_id, criterion_id)
        )
        """
    ),
)


class _VersionOrderedRegistry(dict):
    """Keeps each tier's migration chain in ascending version order, whatever order the owning
    modules are imported in. Owners append at import time, and import order cannot be controlled
    once several modules do, so the chain is sorted on every write (TC-STORE-06)."""

    def __setitem__(self, key: Tier, value: tuple[Migration, ...]) -> None:
        super().__setitem__(key, tuple(sorted(value, key=lambda m: m.version)))


TIER_MIGRATIONS: Mapping[Tier, tuple[Migration, ...]] = _VersionOrderedRegistry(
    {
        Tier.PACKAGE: (Migration(1, "package_tier_initial", _PACKAGE_001),),
        Tier.COHORT: (Migration(1, "cohort_tier_initial", _COHORT_001),),
        Tier.DURABLE: (
            Migration(1, "durable_tier_initial", _DURABLE_001),
            Migration(2, "durable_lease_clock", _DURABLE_002),
            Migration(11, "calib_dual_scored_roster", _DURABLE_011),
        ),
    }
)


def current_schema_version(tier: Tier) -> int:
    """The schema version this code implements for a tier.

    `max`, not `len`: a migration withdrawn before release leaves a gap in the numbering, and a
    count would then claim a version the binary does not implement.
    """
    migrations = TIER_MIGRATIONS[tier]
    return max((m.version for m in migrations), default=0)


#: The schema version each tier must reach once every module that contributes migrations has
#: been imported. The chains in `TIER_MIGRATIONS` are concatenated **at import time** by the
#: owning modules (see `IncompleteMigrationChainError`), so `current_schema_version` reports the
#: *in-process* chain — short of this pin whenever a contributing module has not been imported
#: yet. `_open_tier` compares the two and refuses an open that falls short, because a file built
#: from a truncated chain does not fail at the open: it opens, records the short version, and
#: the columns the missing migrations would have added surface later, far from the open, as
#: `no such column: parent_version_id` (#46's probe; #94 found the suite's own seeds choosing
#: between the two worlds). #234 added the pin and the refusal; the chains themselves are
#: untouched — the guard is an assertion about them, not a change to them. (#269's
#: `_VersionOrderedRegistry` fixed the chains' *order* at the write site; a module that was
#: never imported still contributes nothing to sort, which is the world this pin refuses.)
#:
#: **Maintenance rule**: a change that adds a migration bumps this pin **in the same change**.
#: `tests/regression/store/test_import_order_tier_p.py` imports every contributing module and
#: fails until the pin matches the chain — a stale pin refuses opens in the *full* world, the
#: same phantom bug in mirror image. (The rule has now fired five times since the pin
#: `grade_submission_grade_key` moved it 17→18, and `aeh.grade` joined the contributor
#: import lists the same way — the tail returning to `aeh.grade`. #110's
#: `review_label_store_columns` moved Durable 5→6, and `aeh.review` joined the
#: contributor import lists — Durable's tail is now `aeh.review`'s. #103's
#: `grade_superseded_at_and_append_only` moved Cohort 18→19 and its
#: `grade_audit_record_append_only` moved Durable 6→7 — `aeh.grade` holds both tails.
#: #118's `pkg_validation_record` moved Durable 7→8 and `aeh.pkg` joined the
#: contributor lists the same way — Durable's tail is now `aeh.pkg`'s.
#: #359's `agg_run_scoped_score` moved Cohort 19→20 — Cohort's tail is now `aeh.agg`'s.
#: #361's `extract_latency` (21) and `judge_verdict_assessment` (22) moved Cohort 20→22 and its
#: `judge_run_metrics_judge_dimension` moved Durable 8→9 — `aeh.judge` holds both tails.
#: #355's `ingest_selection_biconditional` moved Cohort 22→23 — Cohort's tail is `aeh.ingest`'s
#: again, where it began. #362's `orch_cell_phase` moved Cohort 23→24, and `aeh.orch` holds the
#: tail. #363's `integ_read_indexes` moved Cohort 24→25 — `aeh.integ` holds it now.)
COMPLETE_SCHEMA_VERSIONS: Mapping[Tier, int] = {
    Tier.PACKAGE: 14,
    Tier.COHORT: 33,
    Tier.DURABLE: 12,
}
