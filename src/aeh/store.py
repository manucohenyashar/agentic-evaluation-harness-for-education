"""`M-STORE` — Persistence Substrate (design §3.3).

Owns the physical stores: four SQLite databases by lifetime tier, the schema discipline that
lets Tiers P and D outlive software versions, and — from the stories that follow — the
single-writer commit queue, the content-addressed blob directory, and purge.

It owns **no schema meaning**. Table semantics belong to the module that owns the tier (`M-PKG`
for Tier P, `M-ORCH` for the ledger, `M-STATS` for Tier D's figures). What lives here is files,
connections, transactions, migrations, and the absence of a retrieval API.

Scope of this file today
------------------------
Issue **#10** only: `FR-STORE-01` (four tier handles, WAL), `FR-STORE-02` (`schema_version`,
forward-only numbered migrations, `SchemaTooNewError`), `FR-STORE-13` (read-only Tier P),
`FR-STORE-14` (`foreign_keys` on every connection), `NFR-STORE-03` (no server, no install, no
configuration beyond a data directory) and `NFR-STORE-04` (migrations forward-only and numbered).

Three siblings are declared and **raise `NotImplementedError` naming their issue**, rather than
being absent or — much worse — being written as no-ops:

| Surface | Issue | Requirements |
|---|---|---|
| `TierHandle.enqueue_write`, `TierHandle.transaction` | #11 | `FR-STORE-03`, `-04`, `-05` |
| `Store.blobs` | #12 | `FR-STORE-06`, `-11` |
| `Store.purge_cohort`, `InsecureLocationError`, `DiskFullError` enforcement | #13 | `FR-STORE-07`, `-08`, `-09`, `-10`, `-12` |

A no-op `transaction()` would be the worst of the three: `FUZZ-07`'s own docstring records that
review proved that case vacuous by dropping in a bare `yield` and watching 500/500 examples pass.
Raising keeps the shape without creating a green-by-blindness path.

Decisions this file fixes, that the design underdetermines
----------------------------------------------------------
Recorded here rather than in a commit message, because `TS-08`/`TS-09`/`TS-10` (#14, #15, #16)
and `TS-60` (#17) are written against whatever this module ships, and a signature they have to
guess is a suite that asserts the wrong thing.

| Decision | Choice | Forced by |
|---|---|---|
| Entry point | `open_store(data_dir)`, positional **and** by keyword | §3.3's Interfaces block names no constructor; three merged tests already call it both ways |
| `Statement` | A `str` subclass carrying `.sql` | `SEC-15` requires `query`'s first parameter to be annotated `Statement` and not `str`; merged tests pass module-level SQL literals, which *are* declared statements |
| What reaches `execute()` | `declared.sql`, never the parameter | `tests/support/sql_scan.py` flags a parameter reaching an execute call and explicitly sanctions attribute access on a declared-statement table. One execute site in the module, registered in `KNOWN_EXECUTE_SITES` |
| Migration 001 creates the tier's tables | Yes — the table *names* from §3.3's data model, with a minimal column set | `TC-STATS-C18` asserts Tier D has tables and would be vacuous over an empty database; `FR-STORE-14` needs a real FK to enforce |
| Later columns | `ALTER TABLE ADD COLUMN` in a later numbered migration, contributed by the owning module | §3.3: this module owns migrations, not table semantics |
| `result` table | **Not** created here | It is not in §3.3's data model; `FUZZ-07` reads it and is keyed on #11, which is the story that builds the write path |
| Schema version is per tier | One `schema_version` table per database, `MAX(version)` is current | `FR-STORE-02` says "per tier"; Tier P files are handed between schools and version independently of Tier D |
| Read-only Tier P | `package(id, read_only=True)` over a `file:...?mode=ro` URI | `FR-STORE-13`; a read-only handle never migrates, because migrating is a write |
| Too-new is checked before anything else | `SchemaTooNewError` raised before the first migration and before any row is read | `CT-STORE-11`: "refuses to open, **no partial read**" |
| `SQLITE_BUSY` retry | Internal, bounded, never surfaced | §3.3 Error handling; `CT-STORE-11` says it never reaches a caller |
| Open-time observability | `Store.opened` — one `TierOpened` per database | `CLAUDE.md` seam 4: a bare success on top of an empty result is the top silent-failure trap |

Configuration
-------------
§3.3 names `HARNESS_DATA_DIR`, `HARNESS_COMMIT_BATCH`, `HARNESS_COMMIT_INTERVAL_MS` and
`HARNESS_WRITE_QUEUE_DEPTH`. The last three belong to #11's write queue. This file reads the
first, plus two knobs for the environment-sensitive constants it introduces — `CLAUDE.md` seam 3:
the production value is the default, the knob exists so a slower box need not edit code.

These are **not** `M-CONF`'s six `HARNESS_*` keys. That tuple is the run-configuration snapshot
and `TC-CONF-C11` sweeps it; these are this module's own and are read here, once, in
`_int_env`/`data_dir_from_environment`.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ContextManager, Mapping, Protocol, Sequence

__all__ = [
    "BlobStore",
    "DiskFullError",
    "InsecureLocationError",
    "Migration",
    "PurgePreconditionError",
    "Row",
    "SchemaTooNewError",
    "Statement",
    "Store",
    "StoreError",
    "TIER_MIGRATIONS",
    "Tier",
    "TierHandle",
    "TierOpened",
    "WriteUnit",
    "current_schema_version",
    "data_dir_from_environment",
    "open_store",
]


# --- configuration ---------------------------------------------------------------------------

#: §3.3: *"no configuration beyond a data directory path"* (`NFR-STORE-03`).
DATA_DIR_ENV = "HARNESS_DATA_DIR"

#: How long SQLite waits for a lock before raising `SQLITE_BUSY`, and how many times this module
#: retries after that. Both are environment-sensitive: WAL plus a single writer should make busy
#: impossible (§3.3), but a slow or networked filesystem makes "should" into "usually", and a
#: constant calibrated for a developer SSD becomes a phantom failure everywhere else.
BUSY_TIMEOUT_MS_ENV = "HARNESS_SQLITE_BUSY_TIMEOUT_MS"
BUSY_RETRIES_ENV = "HARNESS_SQLITE_BUSY_RETRIES"

DEFAULT_BUSY_TIMEOUT_MS = 5_000
DEFAULT_BUSY_RETRIES = 4

#: Owner-only, on the directories this module creates. `FR-STORE-09`'s full rule — refusing a
#: world-writable location with `InsecureLocationError` — is #13's; creating the tree private in
#: the first place is a one-line default that would be strange to defer, and doing it now means
#: #13 tightens a check rather than migrating existing data out of a public directory.
OWNER_ONLY_DIR = 0o700


def _int_env(name: str, default: int, environ: Mapping[str, str] | None = None) -> int:
    source = os.environ if environ is None else environ
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationProblem(f"{name}={raw!r} is not an integer") from exc
    if value < 0:
        raise ConfigurationProblem(f"{name}={value} must not be negative")
    return value


def data_dir_from_environment(environ: Mapping[str, str] | None = None) -> Path:
    """`HARNESS_DATA_DIR`, or a refusal that names it.

    No default path. A store that silently picked one would put student work somewhere the
    operator did not choose, and Tier C is the largest PII surface in the system (§3.3 security).
    """
    source = os.environ if environ is None else environ
    raw = source.get(DATA_DIR_ENV)
    if raw is None or not raw.strip():
        raise ConfigurationProblem(
            f"{DATA_DIR_ENV} is unset. NFR-STORE-03 requires no configuration beyond a data "
            f"directory path — but it does require that one."
        )
    return Path(raw).expanduser()


# --- errors ----------------------------------------------------------------------------------


class StoreError(Exception):
    """Base for every error this module raises.

    Siblings rather than a hierarchy of causes, for the reason `M-CONF` gives for its own four:
    every `CT-STORE-11` oracle is "exact exception type", and a subclass relationship makes
    `pytest.raises(StoreError)` pass for a defect the case meant to distinguish.
    """


class ConfigurationProblem(StoreError):
    """The data directory or a knob is unusable. Raised before any file is touched."""


class SchemaTooNewError(StoreError):
    """The database was written by a newer binary (`FR-STORE-02`, `CT-STORE-11`).

    Raised **before** any migration runs and before any row is read, so "no partial read" is a
    property of the control flow rather than a promise. A store that degraded to reading what it
    recognized would hand a caller a partial view of a package it does not understand.
    """


class InsecureLocationError(StoreError):
    """The data directory resolves inside a world-writable path (`FR-STORE-09`).

    Declared here so the taxonomy `CT-STORE-11` names is complete from the first commit.
    **Nothing raises it yet** — the check is #13's, and this module creates its directories
    owner-only in the meantime.
    """


class PurgePreconditionError(StoreError):
    """`purge_cohort` before promotion to Tier D (`FR-STORE-07`). Raised by #13."""


class DiskFullError(StoreError):
    """A write failed for want of disk space (`FR-STORE-10`). Raised by #13."""


# --- the declared-statement type ---------------------------------------------------------------


class Statement(str):
    """A SQL statement the caller declared, rather than assembled.

    A `str` subclass, and deliberately so: a module-level SQL literal **is** a declared
    statement, which is the pattern every caller already uses (`FUZZ-07`'s `LEDGER_ROW`,
    `TC-STATS-C18`'s `sqlite_master` read), and a type that rejected those would force every
    caller to wrap a literal in a constructor for no gain in safety.

    What the type buys is the thing `FR-STORE-08` is actually about. `TierHandle.query` is
    annotated `Statement`, so `SEC-15`'s reflective probe can tell this interface from
    `query(sql: str)` — and inside this module the value that reaches `execute()` is
    `declared.sql`, an attribute of a declared statement, which is the shape
    `tests/support/sql_scan.py` sanctions. There is no path by which text assembled *in this
    module* reaches SQLite.

    It is **not** a defence against a caller writing bad SQL, and nothing here pretends
    otherwise: every caller is in-process trusted code and there is no untrusted input path into
    a statement. `CT-STORE-08`'s guarantee is the absence of a *search surface* — no similarity,
    no embeddings, no free text over student work — not the rejection of SQL.
    """

    __slots__ = ()

    @property
    def sql(self) -> str:
        """The statement text. Passing this, rather than the parameter, is the point."""
        return str(self)


#: What `query` hands back. `sqlite3.Row` supports both `row[0]` and `row["column"]`, which is
#: what the merged suites already assume — `TC-STATS-C18` indexes positionally and `FUZZ-07`
#: reads `row["status"]`.
Row = sqlite3.Row


@dataclass(frozen=True)
class WriteUnit:
    """One row bound for the single-writer queue (`FR-STORE-03`).

    Declared so `TierHandle.enqueue_write`'s signature matches §3.3's Interfaces block from the
    first commit. #11 owns what happens to it.
    """

    statement: Statement
    params: Mapping[str, Any] = field(default_factory=dict)


# --- the protocols §3.3 declares ----------------------------------------------------------------


class TierHandle(Protocol):
    """`query`, `enqueue_write`, `transaction` — and nothing else (`CT-STORE-01`)."""

    def query(self, statement: Statement, **params: Any) -> Sequence[Row]: ...

    def enqueue_write(self, unit: WriteUnit) -> None: ...

    def transaction(self) -> ContextManager[Any]: ...


class BlobStore(Protocol):
    """Content-addressed on SHA-256 (`CT-STORE-07`). Implemented by #12."""

    def put(self, data: bytes) -> str: ...

    def get(self, content_hash: str) -> bytes: ...

    def path(self, content_hash: str) -> Path: ...


class Store(Protocol):
    """Exactly three handle kinds, plus `blobs()` and `purge_cohort()` (`CT-STORE-01`)."""

    def package(self, package_id: str) -> TierHandle: ...

    def cohort(self, cohort_id: str) -> TierHandle: ...

    def durable(self) -> TierHandle: ...

    def blobs(self) -> BlobStore: ...

    def purge_cohort(self, cohort_id: str) -> Any: ...


# --- tiers -------------------------------------------------------------------------------------


class Tier(str, Enum):
    """The three physical databases, named as §3.3's data model names them.

    Three rather than four: **C and R share one file**, deliberately, because they are created
    and purged together and one file keeps `purge_cohort` a `VACUUM` on one database rather than
    a two-file consistency problem (§3.3). `FR-STORE-01` counts four *tiers*; this counts files.
    """

    PACKAGE = "package"
    COHORT = "cohort"
    DURABLE = "durable"


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
    """One numbered, forward-only schema step.

    Forward-only and reversible **only by restoring a copy** (`NFR-STORE-04`). There is no `down`
    field and there will not be one: a reversal that runs against production data is how a
    migration that was wrong becomes two migrations that are wrong.
    """

    version: int
    name: str
    statements: tuple[Statement, ...]


TIER_MIGRATIONS: Mapping[Tier, tuple[Migration, ...]] = {
    Tier.PACKAGE: (Migration(1, "package_tier_initial", _PACKAGE_001),),
    Tier.COHORT: (Migration(1, "cohort_tier_initial", _COHORT_001),),
    Tier.DURABLE: (Migration(1, "durable_tier_initial", _DURABLE_001),),
}


def current_schema_version(tier: Tier) -> int:
    """The schema version this binary implements for `tier`.

    `max`, not `len`: a migration withdrawn before release leaves a gap in the numbering, and a
    count would then claim a version the binary does not implement.
    """
    migrations = TIER_MIGRATIONS[tier]
    return max((m.version for m in migrations), default=0)


# --- connections ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class TierOpened:
    """What opening one database actually did (`CLAUDE.md` seam 4).

    Per-field rather than a boolean, for the reason `IngestReport.gates` is per-gate: a bare
    "opened successfully" sitting on top of a database with `journal_mode=delete` and foreign keys
    off is the top silent-failure trap, and every field below is one somebody would otherwise
    have to take on trust.
    """

    tier: Tier
    path: Path
    read_only: bool
    schema_version_before: int
    schema_version_after: int
    migrations_applied: tuple[int, ...]
    journal_mode: str
    foreign_keys: bool


_SELECT_MAX_VERSION = Statement("SELECT MAX(version) FROM schema_version")
_SELECT_SCHEMA_VERSION_TABLE = Statement(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
)
_INSERT_VERSION = Statement(
    "INSERT INTO schema_version (version, name, applied_at) "
    "VALUES (:version, :name, :applied_at)"
)
_PRAGMA_FOREIGN_KEYS_ON = Statement("PRAGMA foreign_keys = ON")
_PRAGMA_FOREIGN_KEYS = Statement("PRAGMA foreign_keys")
_PRAGMA_JOURNAL_WAL = Statement("PRAGMA journal_mode = WAL")
_PRAGMA_JOURNAL_MODE = Statement("PRAGMA journal_mode")
_BEGIN = Statement("BEGIN IMMEDIATE")
_COMMIT = Statement("COMMIT")
_ROLLBACK = Statement("ROLLBACK")


def _run(connection: sqlite3.Connection, declared: Statement,
         params: Mapping[str, Any] | None = None, *, retries: int = DEFAULT_BUSY_RETRIES
         ) -> sqlite3.Cursor:
    """The module's single execute site (`FR-STORE-08`, `SEC-15`).

    One site, so `KNOWN_EXECUTE_SITES` in `tests/artifact/test_store_query_surface.py` stays a
    list a reviewer can actually read, and so the `SQLITE_BUSY` retry below cannot be forgotten
    at some other call.

    What is passed is `declared.sql` — an attribute of a declared statement, which is the shape
    `tests/support/sql_scan.py` sanctions — never the parameter itself. Passing the parameter
    would mean "whatever the caller passed reaches SQLite unchecked", and the scanner is right
    that that is a different interface from the one §3.3 declares.

    `SQLITE_BUSY` is retried here and **never surfaces** (`CT-STORE-11`). Under WAL with one
    writer it should not occur at all; "should not" is why the retry is bounded and why exhausting
    it raises the original error rather than a new one.
    """
    attempt = 0
    while True:
        try:
            return connection.execute(declared.sql, dict(params or {}))
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
            if attempt >= retries:
                raise
            attempt += 1
            time.sleep(0.02 * attempt)


def _connect(path: Path, *, read_only: bool, busy_timeout_ms: int) -> sqlite3.Connection:
    """Open one database with the two settings `FR-STORE-01` and `FR-STORE-14` require.

    `foreign_keys` is set on **every** connection, including read-only ones: SQLite defaults it
    off and the setting is per-connection, not per-database, so the CHECK and FOREIGN KEY
    constraints the HLD relies on as guarantees are only guarantees if this line runs every time.

    `journal_mode = WAL` is persistent in the file header, which is why a read-only connection
    does not set it — and why it does not need to.
    """
    if read_only:
        # `as_uri()` rather than a hand-built string: it produces the canonical `file:///...`
        # form on both platforms and percent-encodes a path containing a space, which SQLite's
        # URI parser then decodes. A hand-built `"file:" + str(path)` opens the wrong file — or
        # silently creates a new one — the first time a school puts its data under a directory
        # with a space in the name.
        connection = sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, timeout=busy_timeout_ms / 1000
        )
    else:
        connection = sqlite3.connect(path, timeout=busy_timeout_ms / 1000)
    connection.row_factory = sqlite3.Row
    # Autocommit; #11 replaces this with the single-writer queue and explicit batches. Set before
    # any DDL so a migration's BEGIN is the only transaction in play.
    connection.isolation_level = None
    _run(connection, _PRAGMA_FOREIGN_KEYS_ON)
    if not read_only:
        _run(connection, _PRAGMA_JOURNAL_WAL)
    return connection


def _read_schema_version(connection: sqlite3.Connection) -> int:
    """The database's current schema version, or 0 if it has never been migrated."""
    if not _run(connection, _SELECT_SCHEMA_VERSION_TABLE).fetchall():
        return 0
    row = _run(connection, _SELECT_MAX_VERSION).fetchone()
    return int(row[0]) if row is not None and row[0] is not None else 0


def _migrate(connection: sqlite3.Connection, tier: Tier, present: int) -> tuple[int, ...]:
    """Apply every migration above `present`, in order, each in its own transaction.

    Per migration rather than one transaction for all of them: SQLite can roll back DDL, so a
    failure leaves the database at the last **complete** migration rather than at an intermediate
    state no version number describes. That is what makes re-running the open safe.
    """
    applied: list[int] = []
    pending = sorted(
        (m for m in TIER_MIGRATIONS[tier] if m.version > present), key=lambda m: m.version
    )
    for migration in pending:
        _run(connection, _BEGIN)
        try:
            _run(connection, _SCHEMA_VERSION_TABLE)
            for statement in migration.statements:
                _run(connection, statement)
            _run(
                connection,
                _INSERT_VERSION,
                {
                    "version": migration.version,
                    "name": migration.name,
                    "applied_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            )
        except Exception:
            _run(connection, _ROLLBACK)
            raise
        _run(connection, _COMMIT)
        applied.append(migration.version)
    return tuple(applied)


def _open_tier(path: Path, tier: Tier, *, read_only: bool,
               busy_timeout_ms: int) -> tuple[sqlite3.Connection, TierOpened]:
    """Open, refuse if too new, migrate if behind, and report what happened."""
    if read_only and not path.exists():
        raise ConfigurationProblem(
            f"{path} does not exist, so it cannot be opened read-only. FR-STORE-13 is about "
            f"inspecting an *imported* package before it is trusted."
        )

    path.parent.mkdir(parents=True, exist_ok=True, mode=OWNER_ONLY_DIR)
    connection = _connect(path, read_only=read_only, busy_timeout_ms=busy_timeout_ms)

    try:
        present = _read_schema_version(connection)
        implemented = current_schema_version(tier)

        # Before anything is read out of a table and before the first migration: `CT-STORE-11`
        # says the store "refuses to open, no partial read", and the only way to mean that is to
        # decide it here.
        if present > implemented:
            raise SchemaTooNewError(
                f"{path} is at schema version {present}; this binary implements {implemented} "
                f"for tier {tier.value!r}. Migrations are forward-only (NFR-STORE-04), so there "
                f"is nothing to run and nothing safe to read — upgrade the binary or restore a "
                f"copy taken at version {implemented} or below."
            )

        if read_only:
            applied: tuple[int, ...] = ()
        else:
            applied = _migrate(connection, tier, present)

        after = _read_schema_version(connection)
        journal_mode = str(_run(connection, _PRAGMA_JOURNAL_MODE).fetchone()[0])
        foreign_keys = bool(_run(connection, _PRAGMA_FOREIGN_KEYS).fetchone()[0])
    except Exception:
        connection.close()
        raise

    return connection, TierOpened(
        tier=tier,
        path=path,
        read_only=read_only,
        schema_version_before=present,
        schema_version_after=after,
        migrations_applied=applied,
        journal_mode=journal_mode,
        foreign_keys=foreign_keys,
    )


# --- the handles ----------------------------------------------------------------------------------


class SqliteTierHandle:
    """One tier's database. `query`, `enqueue_write`, `transaction` — and nothing else.

    The member list is `CT-STORE-01`'s and it is closed on purpose: `FUZZ-07`'s docstring records
    an earlier draft that reached for `handle.has_result()` and `handle.status()`, which would
    have added two members to a protocol the design deliberately shuts. Anything a caller needs
    is a declared statement through `query`.
    """

    __slots__ = ("_connection", "_opened", "_read_only", "_retries")

    def __init__(self, connection: sqlite3.Connection, opened: TierOpened, *,
                 retries: int = DEFAULT_BUSY_RETRIES) -> None:
        self._connection = connection
        self._opened = opened
        self._read_only = opened.read_only
        self._retries = retries

    @property
    def opened(self) -> TierOpened:
        """What opening this database did. Read-only; see `TierOpened`."""
        return self._opened

    def query(self, statement: Statement, **params: Any) -> Sequence[Row]:
        """Run a declared statement and return its rows.

        **No order is promised** (`CT-STORE-18`): rows come back in whatever order SQLite
        produces, and a caller needing an order states it in the statement. Nothing here sorts,
        because a module that sorted would make every caller's unstated assumption work until the
        day it did not.
        """
        declared = statement if isinstance(statement, Statement) else Statement(statement)
        return _run(self._connection, declared, params, retries=self._retries).fetchall()

    def enqueue_write(self, unit: WriteUnit) -> None:
        """Asynchronous single-writer enqueue (`FR-STORE-03`, `CT-STORE-02`). **#11.**"""
        raise NotImplementedError(
            "TierHandle.enqueue_write is issue #11 (FR-STORE-03/-04/-05: the single-writer "
            "queue, batch commits and backpressure). It is deliberately absent rather than a "
            "synchronous stand-in: CT-STORE-02 makes this call asynchronous, and a stub that "
            "wrote through would let every caller be written against the wrong contract."
        )

    def transaction(self) -> ContextManager[Any]:
        """Atomic, synchronous, whole-body, within one tier (`CT-STORE-03`). **#11.**"""
        raise NotImplementedError(
            "TierHandle.transaction is issue #11 (FR-STORE-04). Deliberately raising rather "
            "than yielding: FUZZ-07 records that review proved its atomicity case vacuous by "
            "supplying a bare `yield` and watching 500/500 examples pass."
        )

    def close(self) -> None:
        self._connection.close()


# --- the store ---------------------------------------------------------------------------------


class SqliteStore:
    """`Store` over a data directory. One file per package, one per cohort, one shared durable.

    Handles are cached per id, so two calls to `cohort("c-1")` return one handle over one
    connection. That matters more than it looks: `CT-STORE-04` promises readers never observe a
    partially applied transaction, and two connections to one file would make "the writer" a
    matter of which handle a caller happened to hold.
    """

    __slots__ = ("_busy_timeout_ms", "_data_dir", "_handles", "_opened", "_retries")

    def __init__(self, data_dir: Path, *, busy_timeout_ms: int, retries: int) -> None:
        self._data_dir = data_dir
        self._busy_timeout_ms = busy_timeout_ms
        self._retries = retries
        self._handles: dict[tuple[Tier, str, bool], SqliteTierHandle] = {}
        self._opened: list[TierOpened] = []

    # -- layout, verbatim from §3.3's data model ------------------------------------------------

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def package_path(self, package_id: str) -> Path:
        return self._data_dir / "packages" / f"{package_id}.pkg.sqlite"

    def cohort_path(self, cohort_id: str) -> Path:
        return self._data_dir / "cohorts" / f"{cohort_id}.sqlite"

    def durable_path(self) -> Path:
        return self._data_dir / "durable.sqlite"

    @property
    def opened(self) -> tuple[TierOpened, ...]:
        """One record per database this store has opened, in the order it opened them."""
        return tuple(self._opened)

    # -- the three handle kinds ------------------------------------------------------------------

    def _handle(self, tier: Tier, key: str, path: Path, *, read_only: bool) -> SqliteTierHandle:
        cached = self._handles.get((tier, key, read_only))
        if cached is not None:
            return cached
        connection, opened = _open_tier(
            path, tier, read_only=read_only, busy_timeout_ms=self._busy_timeout_ms
        )
        handle = SqliteTierHandle(connection, opened, retries=self._retries)
        self._handles[(tier, key, read_only)] = handle
        self._opened.append(opened)
        return handle

    def package(self, package_id: str, *, read_only: bool = False) -> SqliteTierHandle:
        """Tier P — one file per package, permanent, no PII by construction.

        `read_only=True` is `FR-STORE-13`: an imported package is inspected *before* it is
        trusted, and inspecting it through a writable handle would let the inspection itself
        migrate a file whose provenance is exactly what is in question.
        """
        return self._handle(
            Tier.PACKAGE, package_id, self.package_path(package_id), read_only=read_only
        )

    def cohort(self, cohort_id: str) -> SqliteTierHandle:
        """Tiers C **and** R — one file, per administration, heavy PII."""
        return self._handle(Tier.COHORT, cohort_id, self.cohort_path(cohort_id), read_only=False)

    def durable(self) -> SqliteTierHandle:
        """Tier D — one shared file, permanent, pseudonymized."""
        return self._handle(Tier.DURABLE, "", self.durable_path(), read_only=False)

    # -- the two surfaces later stories fill in ---------------------------------------------------

    def blobs(self) -> BlobStore:
        """Content-addressed blob directory (`FR-STORE-06`). **#12.**"""
        raise NotImplementedError(
            "Store.blobs is issue #12 (FR-STORE-06: content-addressed on SHA-256, deduplicating "
            "identical content). The directory is created by open_store so #12 adds a store "
            "rather than a layout."
        )

    def purge_cohort(self, cohort_id: str) -> Any:
        """Delete Tiers C and R and `VACUUM` (`FR-STORE-07`). **#13.**"""
        raise NotImplementedError(
            "Store.purge_cohort is issue #13 (FR-STORE-07). It is irreversible and it is the "
            "only operation that deletes student work, so it arrives with its "
            "PurgePreconditionError check or not at all."
        )

    # -- lifecycle ---------------------------------------------------------------------------------

    def close(self) -> None:
        for handle in self._handles.values():
            handle.close()
        self._handles.clear()

    def __enter__(self) -> SqliteStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def open_store(data_dir: Path | str | None = None, *,
               environ: Mapping[str, str] | None = None) -> SqliteStore:
    """Open the store rooted at `data_dir`, or at `HARNESS_DATA_DIR` when none is given.

    Positional **and** by keyword, because both forms are already in the suite:
    `open_store(tmp_data_dir)` in `TC-CONF-17` and `FUZZ-07`, `open_store(data_dir=tmp_data_dir)`
    in `TC-STATS-C18`. §3.3's Interfaces block names no constructor at all, so the name and the
    signature are this module's — recorded in the file docstring rather than left to be inferred.

    Nothing is opened here. The three directories are created and the store is returned; each
    database opens on the first call to `package()`, `cohort()` or `durable()`, which is what
    keeps `NFR-STORE-03`'s "no installation step" true — a store constructed against a fresh
    directory has created no `durable.sqlite` a caller never asked for.
    """
    root = Path(data_dir).expanduser() if data_dir is not None else data_dir_from_environment(
        environ
    )
    root = root.resolve()
    for child in (root, root / "packages", root / "cohorts", root / "blobs"):
        child.mkdir(parents=True, exist_ok=True, mode=OWNER_ONLY_DIR)

    return SqliteStore(
        root,
        busy_timeout_ms=_int_env(BUSY_TIMEOUT_MS_ENV, DEFAULT_BUSY_TIMEOUT_MS, environ),
        retries=_int_env(BUSY_RETRIES_ENV, DEFAULT_BUSY_RETRIES, environ),
    )
