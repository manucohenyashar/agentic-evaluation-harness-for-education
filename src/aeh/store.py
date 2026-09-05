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
| Schema version is per tier | One `schema_version` table per database; the **set** of applied versions is what pending work is measured against | `FR-STORE-02` says "per tier"; Tier P files are handed between schools and version independently of Tier D |
| Read-only Tier P | `package(id, read_only=True)` over a `file:...?mode=ro` URI | `FR-STORE-13`; a read-only handle never migrates, because migrating is a write |
| Too-new is checked before anything else | `SchemaTooNewError` raised before the first migration and before any row is read | `CT-STORE-11`: "refuses to open, **no partial read**" |
| `SQLITE_BUSY` retry | Internal and **bounded**; exhausting it re-raises SQLite's own error | §3.3 says busy "should not occur" under WAL. No retry loop can promise *never*, and a helper claiming to would be lying about a lock held outside this process |
| `query` refuses a write | The connection is in autocommit, so it would otherwise be a synchronous write channel | `CT-STORE-02` makes writing asynchronous; #11 owns both write paths |
| One file, one mode | A read-only and a writable handle on the same file cannot both be open | `FR-STORE-13` inspects a file whose provenance is in question; two live connections make that inspection meaningless |
| Open-time observability | `Store.opened` — one `TierOpened` per database | `CLAUDE.md` seam 4: a bare success on top of an empty result is the top silent-failure trap |

Configuration
-------------
§3.3 names `HARNESS_DATA_DIR`, `HARNESS_COMMIT_BATCH`, `HARNESS_COMMIT_INTERVAL_MS` and
`HARNESS_WRITE_QUEUE_DEPTH`. All four are read here as of #11, plus knobs for the
environment-sensitive constants this module introduces on its own account — `CLAUDE.md` seam 3:
the production value is the default, the knob exists so a slower box need not edit code.

These are **not** `M-CONF`'s six `HARNESS_*` keys. That tuple is the run-configuration snapshot
and `TC-CONF-C11` sweeps it; these are this module's own and are read here, once, in
`_int_env`/`data_dir_from_environment`.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, ContextManager, Iterator, Mapping, Protocol, Sequence

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
    "BLOB_HASH_PATTERN",
    "STATEMENTS",
    "Clock",
    "ContentAddressedBlobStore",
    "InvalidContentHashError",
    "Lease",
    "LeaseClock",
    "ReadOnlyTierError",
    "StoreLimits",
    "SystemClock",
    "Tx",
    "WriteQueue",
    "WriteQueueClosed",
    "WriteThroughQueryError",
    "WriteUnit",
    "current_schema_version",
    "data_dir_from_environment",
    "blob_store_stats",
    "lease_clock",
    "open_store",
    "store_metrics",
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

#: §3.3 Configuration, with §3.3's own values as the defaults. `FR-STORE-04` calls 100/5000 an
#: Assumption and `FR-STORE-05` calls 1,000 one, which is exactly what makes them knobs rather
#: than literals: the mechanism is fixed, the numbers are calibrated per environment
#: (`CLAUDE.md` seam 3, "production value is the default").
COMMIT_BATCH_ENV = "HARNESS_COMMIT_BATCH"
COMMIT_INTERVAL_MS_ENV = "HARNESS_COMMIT_INTERVAL_MS"
WRITE_QUEUE_DEPTH_ENV = "HARNESS_WRITE_QUEUE_DEPTH"

DEFAULT_COMMIT_BATCH = 100
DEFAULT_COMMIT_INTERVAL_MS = 5_000
DEFAULT_WRITE_QUEUE_DEPTH = 1_000

#: The free-disk alert's other input (§3.3 **Alerts**: "free disk below the projected remaining-run
#: requirement"). `M-ORCH` knows what a run will still write; this module cannot, so the figure is
#: supplied rather than guessed. Zero — the default — means "no projection stated", and an alert
#: with no projection behind it must stay quiet rather than invent a threshold.
PROJECTED_RUN_BYTES_ENV = "HARNESS_PROJECTED_RUN_BYTES"
DEFAULT_PROJECTED_RUN_BYTES = 0

#: How long queue depth must stay at or above the backpressure threshold before the *alert*
#: fires. §3.3 says "queue depth **sustained** above the backpressure threshold", and the word is
#: load-bearing: backpressure at the boundary is normal operation and `CT-STORE-06` tells
#: `M-ORCH` to treat it as a throttle signal, not a fault. An alert that fired on the same edge
#: would page an operator for the system working as designed.
QUEUE_DEPTH_SUSTAIN_MS_ENV = "HARNESS_QUEUE_DEPTH_SUSTAIN_MS"
DEFAULT_QUEUE_DEPTH_SUSTAIN_MS = 5_000

#: How long the writer sleeps between checks when it has nothing due. Bounds how late a
#: time-triggered commit can be, so it is environment-sensitive in the same way the interval is.
WRITER_POLL_MS_ENV = "HARNESS_WRITER_POLL_MS"
DEFAULT_WRITER_POLL_MS = 5

#: `NFR-STORE-06`: *"a 350-student run shall occupy under 500 MB including blobs"*, which §3.3
#: records as an Assumption ("the HLD estimates tens of megabytes for rows; page rasters and crops
#: dominate"). A knob rather than a literal, because #12's own technical note asks for "a measured,
#: knob-adjustable expectation rather than a hard-coded literal" — a cohort of 800 or a school that
#: rasterises at 600 dpi is a different number, and re-deriving it must not need a code change.
CAPACITY_BUDGET_BYTES_ENV = "HARNESS_CAPACITY_BUDGET_BYTES"
DEFAULT_CAPACITY_BUDGET_BYTES = 500 * 1024 * 1024

#: How far the restored lease counter is pushed past the last expiry it recorded, so a lease
#: issued in the instant before an uncontrolled kill cannot come back live on a rounding edge.
#: Seconds; environment-sensitive because it trades reclaim latency against that edge.
LEASE_RESTORE_MARGIN_S_ENV = "HARNESS_LEASE_RESTORE_MARGIN_S"
DEFAULT_LEASE_RESTORE_MARGIN_S = 1

#: The two alerts §3.3 names under **Alerts**, spelled once. `CT-STORE-17` makes their semantics
#: contract, so the names are part of the interface rather than log text.
ALERT_FREE_DISK = "free_disk_below_projection"
ALERT_QUEUE_DEPTH = "queue_depth_sustained"
DECLARED_ALERTS: tuple[str, ...] = (ALERT_FREE_DISK, ALERT_QUEUE_DEPTH)

#: Owner-only, on **each directory this module itself creates** — not on their parents, and not
#: at all on Windows, where `mkdir`'s mode argument is ignored. So this narrows the window rather
#: than closing it, which is worth saying plainly: `FR-STORE-09`'s full rule (refuse a
#: world-writable location with `InsecureLocationError`, and set the mode explicitly) is #13's.
#: Doing this much now means #13 tightens a check rather than migrating existing data out of a
#: directory that was public while it sat there.
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


class WriteThroughQueryError(StoreError):
    """A write was passed to `query`, which reads (`CT-STORE-02`). See `SqliteTierHandle.query`."""


class PurgePreconditionError(StoreError):
    """`purge_cohort` before promotion to Tier D (`FR-STORE-07`). Raised by #13."""


class DiskFullError(StoreError):
    """A write failed for want of disk space (`FR-STORE-10`). Raised by #13."""


class ReadOnlyTierError(StoreError):
    """A write was attempted on a handle opened read-only (`FR-STORE-13`).

    **The class name carries the refusal.** `TC-STORE-16` matches its evidence against the
    exception's type name *as well as* its message, because a store-level guard is more likely to
    say "writes are not permitted on an imported package" than to use the word "readonly" — and
    requiring the wording alone would red a correct store. `ReadOnlyTierError` satisfies the type
    half whatever the message says, which is why the name is not `ImportedPackageWriteError`.

    Raised **before** anything opens a write connection. That ordering is the requirement, not
    tidiness: `FR-STORE-13` exists so an imported package can be inspected *before* it is
    trusted, and a refusal that had already created a `-wal` file beside the database would move
    the mtime and the digest of the very file whose provenance is in question.
    """


class WriteQueueClosed(StoreError):
    """The store closed while a write was queued or blocked on backpressure."""


class InvalidContentHashError(StoreError):
    """A `content_hash` that `put` could not have returned (`FR-STORE-06`, `SEC-09`).

    Raised **before the filesystem is touched**, which is the requirement rather than the
    implementation detail it looks like. Test plan `TC-STORE-22` fixes the rule: *"`get()` and
    `path()` reject any argument that is not 64 lowercase hex characters, before touching the
    filesystem"*. `SEC-09` is why -- it attacks `path()` with `../`, an absolute path, a wrong
    length and mixed case, and a check performed after building the path has already asked the
    operating system to resolve whatever the attacker wrote.

    Design §3.3 names no error for this. The name is this module's and is reported as a gap.
    """


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

TIER_MIGRATIONS: Mapping[Tier, tuple[Migration, ...]] = {
    Tier.PACKAGE: (Migration(1, "package_tier_initial", _PACKAGE_001),),
    Tier.COHORT: (Migration(1, "cohort_tier_initial", _COHORT_001),),
    Tier.DURABLE: (
        Migration(1, "durable_tier_initial", _DURABLE_001),
        Migration(2, "durable_lease_clock", _DURABLE_002),
    ),
}

#: The two statements the lease counter is read and written with. Module-level literals, never
#: assembled — `SEC-15`, and the same discipline every other statement in this file follows.
_SELECT_LEASE_CLOCK = Statement("SELECT ticks, wall_clock FROM store_lease_clock WHERE id = 1")
#: One literal, not two adjacent ones. `tests/support/sql_scan.py` reads implicit string
#: concatenation as a *computed* statement and refuses it, which is the right call: "declared"
#: has to mean a reader can see the whole statement in one place, and a statement assembled from
#: parts is one `+` away from being assembled from a variable.
_UPSERT_LEASE_CLOCK = Statement(
    """
    INSERT INTO store_lease_clock (id, ticks, wall_clock)
    VALUES (1, :ticks, :wall_clock)
    ON CONFLICT(id) DO UPDATE SET ticks = :ticks, wall_clock = :wall_clock
    """
)


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


_SELECT_APPLIED_VERSIONS = Statement("SELECT version FROM schema_version")
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


#: **The declared-statement registry.** Every statement this module can issue, by name.
#:
#: `FR-STORE-08` offers "keyed lookup and declared queries only", and test plan `TC-STORE-15`
#: reads that as something checkable: *"the registry contains no such statement"* — no
#: similarity, no embedding, no free-text search, no content `LIKE`. A registry is the only form
#: in which that is assertable from outside; a set of private module constants is not enumerable
#: and a reviewer has to find them all by eye.
#:
#: It is also the shape `tests/support/sql_scan.py` sanctions for passing a statement to an
#: execute path: *"an `Attribute` or `Subscript` … is not flagged: a table of declared statements
#: is the sanctioned pattern"*. So the registry is not documentation about the discipline, it is
#: the discipline.
#:
#: **Whose name this is.** `aeh.store:STATEMENTS` had no owner. `tests/support/store_api.py`
#: attributed it to #10, #10 closed without it, #177 re-attributed it to #13 as a presumption and
#: reported the gap. #12 needed the sanctioned pattern for its own write, so the registry arrives
#: here — one story earlier than presumed — and the gap closes with it. The Tier D name guard and
#: the rest of `FR-STORE-08` remain #13's.
#:
#: Migration DDL is included: `TC-STORE-15`'s sweep is over what the module can issue, and a
#: `CREATE VIRTUAL TABLE … USING fts5` hidden in a migration is precisely the full-text index its
#: schema limb exists to catch — reachable through no method anybody would call `search`.
STATEMENTS: Mapping[str, Statement] = {
    "begin_immediate": _BEGIN,
    "commit": _COMMIT,
    "rollback": _ROLLBACK,
    "schema_version_table": _SCHEMA_VERSION_TABLE,
    "select_applied_versions": _SELECT_APPLIED_VERSIONS,
    "select_schema_version_table": _SELECT_SCHEMA_VERSION_TABLE,
    "insert_version": _INSERT_VERSION,
    "pragma_foreign_keys_on": _PRAGMA_FOREIGN_KEYS_ON,
    "pragma_foreign_keys": _PRAGMA_FOREIGN_KEYS,
    "pragma_journal_wal": _PRAGMA_JOURNAL_WAL,
    "pragma_journal_mode": _PRAGMA_JOURNAL_MODE,
    "select_lease_clock": _SELECT_LEASE_CLOCK,
    "upsert_lease_clock": _UPSERT_LEASE_CLOCK,
    **{
        f"migrate_{tier.value}_{migration.version:03d}_{index:02d}": statement
        for tier, migrations in TIER_MIGRATIONS.items()
        for migration in migrations
        for index, statement in enumerate(migration.statements)
    },
}


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

    `SQLITE_BUSY` is retried here rather than at any call site (`CT-STORE-11`). Under WAL with one
    writer it should not occur at all, and "should not" is why the retry is bounded: a lock held
    by something outside this process is not a condition an unbounded retry improves.

    So it is **bounded, not never** — exhausting the retries re-raises SQLite's own error rather
    than a new one, and the caller sees `OperationalError` exactly as it would have without the
    retry. §3.3 says busy "should not occur"; a helper that promised it could not would be
    promising something no retry loop can deliver.
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


def _connect(path: Path, *, read_only: bool, busy_timeout_ms: int,
             retries: int, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open one database and enable foreign keys. **Writes nothing.**

    `foreign_keys` is set on **every** connection, including read-only ones: SQLite defaults it
    off and the setting is per-connection, not per-database, so the CHECK and FOREIGN KEY
    constraints the HLD relies on as guarantees are only guarantees if this line runs every time.
    It is a connection setting and touches no byte of the file.

    **`journal_mode = WAL` is deliberately not set here**, and the ordering is the whole point.
    Setting WAL rewrites bytes 18 and 19 of the file header — so a version check performed *after*
    it has already modified a database the store is about to refuse to open. Review measured
    exactly that: a v99 database came back with a changed mtime and a changed content hash after
    `SchemaTooNewError`, which is what `TC-STORE-05`'s oracle ("the file is unmodified, asserted
    by mtime and content hash") exists to catch, and what `CT-STORE-11`'s "no partial read" means
    in practice. `_open_tier` sets WAL after the check, on the writable path only.
    """
    if read_only:
        # `as_uri()` rather than a hand-built string: it produces the canonical `file:///...`
        # form on both platforms and percent-encodes a path containing a space, which SQLite's
        # URI parser then decodes. A hand-built `"file:" + str(path)` opens the wrong file — or
        # silently creates a new one — the first time a school puts its data under a directory
        # with a space in the name.
        connection = sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, timeout=busy_timeout_ms / 1000,
            check_same_thread=check_same_thread,
        )
    else:
        connection = sqlite3.connect(
            path, timeout=busy_timeout_ms / 1000, check_same_thread=check_same_thread
        )
    connection.row_factory = sqlite3.Row
    # Autocommit at the driver level, which as of #11 is what lets this module issue its own
    # BEGIN / COMMIT / ROLLBACK through `_run` rather than having sqlite3 open transactions
    # behind it. Set before any DDL so a migration's BEGIN is the only transaction in play.
    connection.isolation_level = None
    _run(connection, _PRAGMA_FOREIGN_KEYS_ON, retries=retries)
    return connection


def _applied_versions(connection: sqlite3.Connection, retries: int) -> frozenset[int]:
    """Every migration version this database has recorded, as a set.

    A **set**, not `MAX(version)`, and review is what forced the difference. `schema_version`
    carries one row per applied migration, so a database at 1 and 3 — the shape a withdrawn
    migration 2 leaves behind, or a branch merged in the wrong order — reports a maximum of 3.
    Filtering pending work by `version > 3` then skips 2 forever, silently, and the tier opens
    reporting a version whose schema it does not have. Measured: `migration 2 SKIPPED = True`,
    its table absent.

    The set makes "pending" mean what it says: any numbered migration this database has not
    recorded. `NFR-STORE-04`'s migrate-every-prior-version suite is the thing that would have
    caught this, and it cannot exist until there is more than one version — see the PR.
    """
    if not _run(connection, _SELECT_SCHEMA_VERSION_TABLE, retries=retries).fetchall():
        return frozenset()
    rows = _run(connection, _SELECT_APPLIED_VERSIONS, retries=retries).fetchall()
    return frozenset(int(row[0]) for row in rows if row[0] is not None)


def _migrate(connection: sqlite3.Connection, tier: Tier, already: frozenset[int],
             retries: int) -> tuple[int, ...]:
    """Apply every migration this database has not recorded, in version order.

    Pending is "not in `already`" rather than "above the maximum", so a database carrying 1 and 3
    still gets 2 when the binary supplies it. See `_applied_versions`.

    One transaction **per migration** rather than one for all of them: SQLite can roll back DDL,
    so a failure leaves the database at the last *complete* migration rather than at an
    intermediate state no version number describes. That is what makes re-running the open safe,
    and it is why `applied` is returned as the versions that actually landed.
    """
    applied: list[int] = []
    pending = sorted(
        (m for m in TIER_MIGRATIONS[tier] if m.version not in already), key=lambda m: m.version
    )
    for migration in pending:
        _run(connection, _BEGIN, retries=retries)
        try:
            _run(connection, _SCHEMA_VERSION_TABLE, retries=retries)
            for statement in migration.statements:
                _run(connection, statement, retries=retries)
            _run(
                connection,
                _INSERT_VERSION,
                {
                    "version": migration.version,
                    "name": migration.name,
                    "applied_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                retries=retries,
            )
            _run(connection, _COMMIT, retries=retries)
        except Exception:
            # The rollback is best-effort and its failure is **swallowed**, deliberately. SQLite
            # rolls a statement-level failure back on its own, so the explicit ROLLBACK then
            # raises "cannot rollback - no transaction is active" — and letting that propagate
            # replaces the real finding (an IntegrityError, or ENOSPC, which is exactly what #13's
            # DiskFullError has to classify) with a message about transaction bookkeeping. Review
            # measured the swap.
            try:
                _run(connection, _ROLLBACK, retries=retries)
            except sqlite3.Error:
                pass
            raise
        applied.append(migration.version)
    return tuple(applied)


def _open_tier(path: Path, tier: Tier, *, read_only: bool, busy_timeout_ms: int,
               retries: int) -> tuple[sqlite3.Connection, TierOpened]:
    """Open, refuse if too new, migrate if behind, and report what happened.

    The order is the requirement. Nothing writes to the file until the version check has passed,
    so `CT-STORE-11`'s *"refuses to open, no partial read"* and `TC-STORE-05`'s *"the file is
    unmodified, asserted by mtime and content hash"* are both properties of the control flow
    rather than of anyone's care.
    """
    if read_only and not path.exists():
        raise ConfigurationProblem(
            f"{path} does not exist, so it cannot be opened read-only. FR-STORE-13 is about "
            f"inspecting an *imported* package before it is trusted."
        )

    path.parent.mkdir(parents=True, exist_ok=True, mode=OWNER_ONLY_DIR)
    connection = _connect(
        path, read_only=read_only, busy_timeout_ms=busy_timeout_ms, retries=retries
    )

    try:
        already = _applied_versions(connection, retries)
        present = max(already, default=0)
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
            # The first write to the file, and it happens **after** the refusal above.
            # `journal_mode = WAL` rewrites the header, so setting it earlier would modify a
            # database the store was about to refuse — see `_connect`.
            _run(connection, _PRAGMA_JOURNAL_WAL, retries=retries)
            applied = _migrate(connection, tier, already, retries)

        after = max(_applied_versions(connection, retries), default=0)
        journal_mode = str(_run(connection, _PRAGMA_JOURNAL_MODE, retries=retries).fetchone()[0])
        foreign_keys = bool(_run(connection, _PRAGMA_FOREIGN_KEYS, retries=retries).fetchone()[0])
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


#: The statement verbs `query` accepts. Everything else is a write and belongs on the queue
#: (`CT-STORE-02`) or inside a transaction (`CT-STORE-03`), both of which are #11's.
READ_VERBS: frozenset[str] = frozenset({"select", "with", "values", "explain", "pragma"})


def _refuse_write(declared: Statement) -> None:
    """Raise unless `declared` starts with a read verb. See `SqliteTierHandle.query`."""
    words = declared.sql.lstrip().lstrip("(").split(None, 1)
    first = words[0].lower() if words else ""
    if first in READ_VERBS:
        return
    raise WriteThroughQueryError(
        f"query() was given a {first.upper() or 'blank'} statement. It reads; writing goes "
        f"through enqueue_write (asynchronous, CT-STORE-02) or transaction() (atomic, "
        f"CT-STORE-03), both of which are issue #11. A synchronous write named query() would "
        f"let callers be written against the opposite of the contract."
    )


@dataclass(frozen=True)
class StoreLimits:
    """The environment-sensitive numbers, resolved once at `open_store`.

    Resolved at construction, not per call, and that is a decision `TC-STORE-24` depends on:
    seam 3 says "production value is the default; the knob exists so a slower test box can
    adjust without a code change", which describes a value read when the process configures
    itself. A store that re-read `os.environ` on every enqueue would be promising live reload,
    which nothing requires and which makes the configured value unobservable.
    """

    commit_batch: int = DEFAULT_COMMIT_BATCH
    commit_interval_ms: int = DEFAULT_COMMIT_INTERVAL_MS
    write_queue_depth: int = DEFAULT_WRITE_QUEUE_DEPTH
    projected_run_bytes: int = DEFAULT_PROJECTED_RUN_BYTES
    queue_depth_sustain_ms: int = DEFAULT_QUEUE_DEPTH_SUSTAIN_MS
    writer_poll_ms: int = DEFAULT_WRITER_POLL_MS
    capacity_budget_bytes: int = DEFAULT_CAPACITY_BUDGET_BYTES
    lease_restore_margin_s: int = DEFAULT_LEASE_RESTORE_MARGIN_S
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS
    retries: int = DEFAULT_BUSY_RETRIES

    def __post_init__(self) -> None:
        """Refuse a knob whose value is meaningless, rather than hanging on it.

        `_int_env` rejects a negative, which leaves zero -- and zero is not a small value here,
        it is a different program. `commit_batch=0` makes every batch empty, so the writer spins
        forever committing nothing while the queue never shrinks; `write_queue_depth=0` makes
        `enqueue_write` block on its first call, since the depth is reached before anything is
        queued. Both are silent hangs from one mistyped environment variable, and seam 3 exists
        so a slower box can retune these -- retuning is when a typo happens.
        """
        for name, env, value in (
            ("commit_batch", COMMIT_BATCH_ENV, self.commit_batch),
            ("commit_interval_ms", COMMIT_INTERVAL_MS_ENV, self.commit_interval_ms),
            ("write_queue_depth", WRITE_QUEUE_DEPTH_ENV, self.write_queue_depth),
            ("writer_poll_ms", WRITER_POLL_MS_ENV, self.writer_poll_ms),
            ("capacity_budget_bytes", CAPACITY_BUDGET_BYTES_ENV, self.capacity_budget_bytes),
        ):
            if value <= 0:
                raise ConfigurationProblem(
                    f"{env} is {value}; it must be greater than zero. A {name} of zero does not "
                    "mean 'no limit' — it stalls the write queue with nothing to report."
                )

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> StoreLimits:
        return cls(
            commit_batch=_int_env(COMMIT_BATCH_ENV, DEFAULT_COMMIT_BATCH, environ),
            commit_interval_ms=_int_env(
                COMMIT_INTERVAL_MS_ENV, DEFAULT_COMMIT_INTERVAL_MS, environ),
            write_queue_depth=_int_env(
                WRITE_QUEUE_DEPTH_ENV, DEFAULT_WRITE_QUEUE_DEPTH, environ),
            projected_run_bytes=_int_env(
                PROJECTED_RUN_BYTES_ENV, DEFAULT_PROJECTED_RUN_BYTES, environ),
            queue_depth_sustain_ms=_int_env(
                QUEUE_DEPTH_SUSTAIN_MS_ENV, DEFAULT_QUEUE_DEPTH_SUSTAIN_MS, environ),
            writer_poll_ms=_int_env(WRITER_POLL_MS_ENV, DEFAULT_WRITER_POLL_MS, environ),
            capacity_budget_bytes=_int_env(
                CAPACITY_BUDGET_BYTES_ENV, DEFAULT_CAPACITY_BUDGET_BYTES, environ),
            lease_restore_margin_s=_int_env(
                LEASE_RESTORE_MARGIN_S_ENV, DEFAULT_LEASE_RESTORE_MARGIN_S, environ),
            busy_timeout_ms=_int_env(BUSY_TIMEOUT_MS_ENV, DEFAULT_BUSY_TIMEOUT_MS, environ),
            retries=_int_env(BUSY_RETRIES_ENV, DEFAULT_BUSY_RETRIES, environ),
        )


class Tx:
    """The handle a `transaction()` body writes through (`CT-STORE-03`).

    Section 3.3's Interfaces block types `transaction()` as `ContextManager[Tx]` and never
    defines `Tx`, so its one method is this module's. `execute(statement, **params)` mirrors
    `query` deliberately: same declared-`Statement` argument, same keyword parameters, so a
    caller moving a read into a transaction changes the method name and nothing else.

    **No `commit` and no `rollback`.** The context manager owns both -- commit on a clean exit,
    rollback on any exception -- because `CT-STORE-03`'s promise is "atomic and synchronous over
    its whole body", and a body that could commit halfway through would make "both present or
    both absent" a convention rather than a guarantee. `FUZZ-07` is the case that notices:
    review proved its atomicity property vacuous against a `transaction()` that was a bare
    `yield`, and a `Tx` exposing `commit()` is the same hole one level up.
    """

    __slots__ = ("_connection", "_retries")

    def __init__(self, connection: sqlite3.Connection, retries: int) -> None:
        self._connection = connection
        self._retries = retries

    def execute(self, statement: Statement, **params: Any) -> Sequence[Row]:
        """Run one declared statement inside the open transaction.

        Reads are allowed as well as writes -- `_refuse_write` guards `query`, not this --
        because a transaction that could not read cannot do the read-modify-write every ledger
        transition is. The rows come back for the same reason `query` returns them.
        """
        declared = statement if isinstance(statement, Statement) else Statement(statement)
        return _run(self._connection, declared, params, retries=self._retries).fetchall()


#: What a `content_hash` must look like: exactly 64 lowercase hex characters, anchored.
#:
#: Anchored, and lowercase-only. `re.match` without `$` would accept
#: `"a"*64 + "/../../etc/passwd"`, and `hexdigest()` returns lowercase -- so accepting uppercase
#: would mean two spellings of one blob, which is a second copy of the file the whole module
#: exists to store once. `TC-STORE-22` generates mixed case as a rejection input for exactly that
#: reason.
BLOB_HASH_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")

#: Where an in-progress blob is written before it is renamed into place. **Outside `blobs/`**, and
#: that is not tidiness: `TC-STORE-09` counts every file under the blob root and asserts that
#: storing one blob created exactly one file, so a temp file that lived there -- or was left there
#: by a crash -- would fail a correct store.
INCOMING_DIR = ".incoming"

#: Owner-only, on the blob files themselves (`FR-STORE-09`). Ignored on Windows, like the
#: directory mode #10 records; #13 owns the full rule.
OWNER_ONLY_FILE = 0o600


class ContentAddressedBlobStore:
    """Blobs keyed by the SHA-256 of their content (`FR-STORE-06`, `CT-STORE-07`).

    **Content-addressed means idempotent for free.** `put` computes the digest, and the digest
    *is* the location, so storing the same bytes twice writes to the same path and the second
    write is skipped rather than deduplicated afterwards by a comparison. There is no index to
    fall out of step with the directory, which is also why `stats()` walks.

    **Two-level fan-out**, `blobs/<aa>/<bb>/<hash>`. A 350-student run's page rasters and crops
    run to tens of thousands of files (`NFR-STORE-06`), and tens of thousands of entries in one
    directory is where `readdir` and most filesystem tools start to degrade. The path is derived
    from the hash alone, so it is reproducible from the content and nothing needs to record it.

    **Written to a temp file and renamed.** A crash partway through a 3 MB page raster would
    otherwise leave a truncated file *at its own content address* -- the one state this design
    cannot detect, since the address no longer describes the bytes. `os.replace` is atomic within
    a filesystem, and the temp lives under the data directory rather than the system temp so it
    is on that same filesystem (and outside a world-writable path, `FR-STORE-09`).
    """

    __slots__ = ("_incoming", "_root")

    def __init__(self, root: Path, incoming: Path) -> None:
        self._root = root
        self._incoming = incoming

    # -- the three members §3.3 declares --------------------------------------------------------

    def put(self, data: bytes) -> str:
        """Store `data`, returning its SHA-256 hex digest. Idempotent (`CT-STORE-07`)."""
        if isinstance(data, (bytearray, memoryview)):
            data = bytes(data)
        if not isinstance(data, bytes):
            raise InvalidContentHashError(
                f"put() takes bytes, got {type(data).__name__}. A blob is the source PDF, the "
                "page raster or the crop; encoding is the caller's decision, not this module's."
            )
        content_hash = hashlib.sha256(data).hexdigest()
        target = self._path_for(content_hash)
        if target.exists():
            # FR-STORE-06's "deduplicate identical content on write". Not an optimisation: this
            # is what makes `put` idempotent, and rewriting would also mean a window in which an
            # existing, valid blob is replaced by a partial one.
            return content_hash
        target.parent.mkdir(parents=True, exist_ok=True, mode=OWNER_ONLY_DIR)
        self._incoming.mkdir(parents=True, exist_ok=True, mode=OWNER_ONLY_DIR)
        staged = self._incoming / f"{content_hash}.{secrets.token_hex(8)}"
        try:
            staged.write_bytes(data)
            try:
                staged.chmod(OWNER_ONLY_FILE)
            except OSError:
                pass  # Windows ignores the mode; #13 owns the full FR-STORE-09 rule
            os.replace(staged, target)
        finally:
            # A failed write must not leave the staging file behind: `TC-STORE-09` counts every
            # file under the data directory's blob root, and an operator counting disk usage
            # would be reading a number that includes rubbish.
            if staged.exists():
                staged.unlink()
        return content_hash

    def get(self, content_hash: str) -> bytes:
        """The bytes `put` stored under `content_hash`."""
        path = self.path(content_hash)
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise KeyError(
                f"no blob stored under {content_hash}. `put` returns the hash it stored; a hash "
                "that is well-formed but absent means the blob belongs to a different data "
                "directory, or to a cohort that has been purged."
            ) from error

    def path(self, content_hash: str) -> Path:
        """Where `content_hash` lives on disk. **Validated before the filesystem is touched.**

        `SEC-09` attacks this with a crafted hash, and the order of the two lines below is the
        defence: the pattern is checked first, so `../`, an absolute path and a wrong length are
        all rejected without the operating system ever being asked to resolve them. The
        containment assertion after it is belt and braces against a future change to the layout
        -- 64 hex characters cannot escape `_root`, and the day the fan-out changes is the day
        that stops being obvious.
        """
        self._validate(content_hash)
        resolved = self._path_for(content_hash)
        root = self._root.resolve()
        if not resolved.resolve().is_relative_to(root):
            raise InvalidContentHashError(
                f"{content_hash} resolves outside the blob directory ({resolved}). This cannot "
                "happen for 64 hex characters and is asserted anyway: FR-STORE-09 requires "
                "resolution to stay inside the data directory, and SEC-09 attacks exactly here."
            )
        return resolved

    # -- accounting -------------------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """File count and bytes on disk, **by walking the directory**.

        A walk rather than a counter this module maintains. `TC-STORE-09` cross-checks this
        against its own walk and says why: *"a stats accessor that disagrees with the filesystem
        is reporting on something other than the filesystem"*. A maintained counter has to be
        right across every restart, every purge and every crash; a walk cannot drift because
        there is nothing to drift from.
        """
        file_count = 0
        bytes_on_disk = 0
        for entry in self._root.rglob("*"):
            if entry.is_file():
                file_count += 1
                bytes_on_disk += entry.stat().st_size
        return {
            "file_count": file_count,
            "bytes_on_disk": bytes_on_disk,
            "root": self._root,
        }

    # -- internals ----------------------------------------------------------------------------------

    @staticmethod
    def _validate(content_hash: Any) -> None:
        if not isinstance(content_hash, str) or not BLOB_HASH_PATTERN.match(content_hash):
            raise InvalidContentHashError(
                f"{content_hash!r} is not a content hash. `put` returns 64 lowercase hex "
                "characters (SHA-256, CT-STORE-07); anything else was not produced by this "
                "store and is refused before the filesystem is touched (TC-STORE-22, SEC-09)."
            )

    def _path_for(self, content_hash: str) -> Path:
        return self._root / content_hash[:2] / content_hash[2:4] / content_hash


# --- the monotonic lease clock -------------------------------------------------------------------


class Clock(Protocol):
    """Wall time and monotonic time, separately (`FR-STORE-11`).

    Two methods rather than one because the requirement is about the difference between them:
    lease expiry derives from the monotonic counter, and the wall clock is recorded beside it for
    an operator reading the row. A single `now()` cannot express that.

    Declared here rather than imported: `tests/support/clock.py` has the matching `FrozenClock`,
    but that is test support and production code cannot import it. Structural typing means the
    test double satisfies this without either file knowing about the other, which is what
    `CLAUDE.md` seam 2 asks for.
    """

    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class SystemClock:
    """The production `Clock`. UTC, and `time.monotonic` for the counter."""

    __slots__ = ()

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()


@dataclass(frozen=True)
class Lease:
    """A claim with an expiry, expressed in the store's own monotonic ticks.

    `expires_ticks` is what `expired()` compares. `issued_at` is the wall clock at issue and is
    for an operator reading a ledger row -- it is deliberately *not* what expiry is computed
    from, which is the whole of `FR-STORE-11`.
    """

    expires_ticks: float
    issued_ticks: float
    issued_at: datetime
    ttl_seconds: float


class LeaseClock:
    """Lease expiry from a monotonic counter persisted alongside wall clock (`FR-STORE-11`).

    `CT-STORE-14` states the failure this exists to prevent: NTP corrects the host clock
    backwards while a run is resumed, and every expired lease reads as live -- so `M-ORCH`'s
    sweeper reclaims nothing and the work is stranded, or it reclaims twice and the work is
    duplicated. The test plan calls the bug *"a 'simplification' to `datetime.now()`"*.

    **What is persisted is the furthest expiry ever issued**, not the current tick. Persisting
    the current tick is the obvious design and it is wrong: a lease issued at tick 100 with a
    60-second TTL expires at 160, the process runs on to tick 200 and is killed, and a restore
    from 100 reads that lease as live again. Recording 160 at the moment of issue means the
    restored counter is at or past every expiry that was ever issued.

    **So a restart expires every outstanding lease, and that is the correct direction.** There is
    no server process here (§3.3, `NFR-STORE-03`), so a lease outstanding at restart was held by
    a process that is gone. Reclaiming it is recoverable; believing it live is the stranded work
    `CT-STORE-14` names. The conservatism is stated rather than hidden because it is a real
    behaviour a caller can observe.

    The write is **synchronous, through `transaction()`**, not `enqueue_write`. `CT-STORE-02`
    makes the queue asynchronous, and a counter that an uncontrolled kill can lose is a counter
    that restores lower than the leases it was supposed to outlive -- which is the bug, arrived
    at from the other side.
    """

    __slots__ = ("_clock", "_durable", "_margin_s", "_origin", "_persisted_ticks")

    def __init__(self, store: SqliteStore, clock: Clock | None = None) -> None:
        self._clock = clock if clock is not None else SystemClock()
        self._durable = store.durable()
        self._margin_s = store.limits.lease_restore_margin_s
        restored = self._restore()
        # The margin covers the instant between computing an expiry and committing it: a kill
        # in that window would otherwise restore just short of a lease that had been issued.
        self._persisted_ticks = restored + (self._margin_s if restored else 0.0)
        self._origin = self._clock.monotonic()

    # -- the counter --------------------------------------------------------------------------

    def ticks(self) -> float:
        """The current monotonic tick: what was persisted, plus this process's own elapsed time.

        Never derived from the wall clock, in either term. Moving the host clock backwards
        changes `now()` and changes nothing here, which is `CT-STORE-14`'s assertion.
        """
        return self._persisted_ticks + (self._clock.monotonic() - self._origin)

    def issue(self, ttl_seconds: float) -> Lease:
        """Issue a lease expiring `ttl_seconds` from now, and persist its expiry first."""
        if ttl_seconds <= 0:
            raise ConfigurationProblem(
                f"a lease TTL must be positive, got {ttl_seconds}. A lease that expires on issue "
                "is a work unit M-ORCH reclaims from itself."
            )
        issued_ticks = self.ticks()
        expires_ticks = issued_ticks + ttl_seconds
        issued_at = self._clock.now()
        # Persisted *before* the lease is returned. A lease handed to a caller and then lost to a
        # kill before its expiry reached the database is the one case that could come back live.
        self._persist(expires_ticks, issued_at)
        return Lease(
            expires_ticks=expires_ticks, issued_ticks=issued_ticks, issued_at=issued_at,
            ttl_seconds=float(ttl_seconds),
        )

    def expired(self, lease: Lease) -> bool:
        """Whether `lease` has expired. The comparison `M-ORCH`'s sweeper trusts."""
        return self.ticks() >= lease.expires_ticks

    # -- persistence ---------------------------------------------------------------------------

    def _restore(self) -> float:
        rows = self._durable.query(STATEMENTS["select_lease_clock"])
        return float(rows[0]["ticks"]) if rows else 0.0

    def _persist(self, ticks: float, wall: datetime) -> None:
        highest = max(ticks, self._persisted_high_water())
        with self._durable.transaction() as tx:
            # Through the registry rather than the module constant, which is the shape
            # `sql_scan` sanctions for an execute path — see `STATEMENTS`. `Tx.execute` is this
            # module's own declared-statement API and delegates to `_run`, so the number of
            # places a statement actually reaches SQLite is still one; the *call* is a second
            # site the walker can see, and it is listed in `KNOWN_EXECUTE_SITES` with this note.
            tx.execute(STATEMENTS["upsert_lease_clock"], ticks=highest,
                       wall_clock=wall.isoformat())

    def _persisted_high_water(self) -> float:
        rows = self._durable.query(STATEMENTS["select_lease_clock"])
        return float(rows[0]["ticks"]) if rows else 0.0


class WriteQueue:
    """The single writer: one queue, one thread, batched commits, backpressure at the depth.

    `FR-STORE-03` ("serialize all writes through a single writer thread fed by an in-process
    queue; concurrent readers shall not block the writer"), `FR-STORE-04` (batch at 100 rows or
    5 seconds, whichever comes first) and `FR-STORE-05` (backpressure above a configured depth)
    are one mechanism, so they are one class.

    **Why a second connection rather than a shared mutex.** The reader connection stays exactly
    where #10 left it and this queue opens its own. Under WAL that is what makes `CT-STORE-04`
    ("concurrent readers never block the writer") true *at the database level* -- a reader holds
    no lock the writer needs. A single connection guarded by a lock would satisfy `TC-STORE-03`,
    whose docstring says so plainly ("what this case does not catch: a per-operation shared
    mutex"), and would fail `NFR-STORE-01` under real load. The contract is the promise; the
    test is only what happens to be checkable.

    **What "single writer" means once `transaction()` exists.** Section 3.3 hands the caller a
    context manager, so a transaction body necessarily runs on the caller's thread -- it cannot
    be marshalled to the writer thread without marshalling arbitrary user code. So the
    serialization point is the write *connection*, guarded by `_write_lock`: the drain thread
    takes it per batch, `transaction()` takes it for its whole body, and at most one write
    transaction is ever open on the tier. One writer, in the sense the requirement is about --
    never two writes interleaved, never a partially applied transaction observable -- and the
    sense in which the design's own interface makes "one thread executes every statement"
    unachievable is recorded here rather than quietly redefined.

    **Ordering.** A `deque`, popped from the left, committed in slices. Single-caller FIFO holds
    end to end, which is what `TC-STORE-03` asserts and `CT-STORE-04` promises; ordering
    *across* callers is explicitly not promised and nothing here manufactures it.
    """

    __slots__ = (
        "_condition", "_connect_write", "_failures", "_holder", "_last_latency_ms",
        "_limits", "_over_since", "_pending", "_queue", "_stamps", "_stopping", "_thread",
        "_write_lock",
    )

    def __init__(self, connect_write: Any, limits: StoreLimits) -> None:
        self._connect_write = connect_write
        self._limits = limits
        self._queue: deque[WriteUnit] = deque()
        self._stamps: deque[float] = deque()
        self._condition = threading.Condition()
        self._write_lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._last_latency_ms = 0.0
        self._over_since: float | None = None
        self._failures: list[BaseException] = []
        # Rows enqueued and not yet durable -- queued *or* in flight. One counter rather than
        # two terms; see `depth`.
        self._pending = 0
        # Whether *this* thread is inside a `transaction()` body on this queue. See `enqueue`.
        self._holder = threading.local()

    # -- what the metrics read -----------------------------------------------------------------

    @property
    def depth(self) -> int:
        """Rows enqueued and not yet durable -- queued *or* mid-commit.

        "Not yet durable" rather than "still on the deque", and the difference is what a caller
        waiting for its writes depends on: `CT-STORE-02` makes `enqueue_write` asynchronous and
        nothing else says when the row arrives, so polling this to zero is the only way to wait.
        Counting the deque alone reports zero the instant the last batch is *popped*, while it is
        still inside `COMMIT`, and the caller reads back one commit short. Measured before this
        was a single counter: `TC-STORE-03` landed 225 of 250 rows -- in order, nothing lost,
        the drain simply believing it had finished a batch early.

        **One counter, not two terms added together.** An earlier form was
        `len(self._queue) + self._in_flight`, incremented after the pops; review found the gap
        between the last `popleft` and the `+=` still reads zero for a batch that is in neither
        place. Narrower than a whole `COMMIT`, and not tripped in nine attempts -- but a window
        the docstring claimed was closed. A single `int` read is atomic in CPython and has no
        such gap.

        No lock, deliberately. The merged `_drain` polls this in a tight loop with no sleep, and
        a poll contending with the writer for the writer's own lock on every iteration would be
        the reader blocking the writer, in the one place this module exists to prevent it.
        """
        return self._pending

    @property
    def backpressure_active(self) -> bool:
        """`FR-STORE-05`'s level, at or above the configured depth.

        At, not above. The requirement says "when the pending write queue exceeds a configured
        depth" and `TC-STORE-07` reads that boundary as inclusive -- `N-1` clear, `N` raised. A
        signal that first appeared at `N+1` would let the queue reach the bound
        `NFR-STORE-02`'s durability window is computed from before saying anything.
        """
        return self.depth >= self._limits.write_queue_depth

    @property
    def last_commit_latency_ms(self) -> float:
        return self._last_latency_ms

    @property
    def failures(self) -> tuple[BaseException, ...]:
        return tuple(self._failures)

    def sustained_over_threshold(self) -> bool:
        """Whether backpressure has held long enough to be the *alert* rather than the signal."""
        since = self._over_since
        if since is None:
            return False
        return (time.monotonic() - since) * 1000.0 >= self._limits.queue_depth_sustain_ms

    # -- the caller side -----------------------------------------------------------------------

    def enqueue(self, unit: WriteUnit) -> None:
        """Append, blocking while the queue is at or above the configured depth.

        Blocking is one of the two behaviours `FR-STORE-05` sanctions, and it is the one that
        cannot lie: a caller that is blocked has demonstrably reduced its dispatch rate, whereas
        "slowing" is a promise about a duration nobody can hold. `CT-STORE-06` tells `M-ORCH` to
        read it as a throttle signal rather than a fault, which is why this raises nothing while
        the store is open.

        The writer thread is started **before** the wait, not after. Starting it afterwards
        deadlocks the first caller the moment the depth is reached: nothing would be draining
        the queue it is waiting on.
        """
        if getattr(self._holder, "in_transaction", False):
            # F2: this thread is inside a `transaction()` body, so it holds `_write_lock` -- the
            # same lock the drain thread needs to commit anything. Waiting for backpressure to
            # clear would wait for a drain that cannot start, and the process hangs with no
            # timeout and no diagnostic.
            #
            # `CT-STORE-04` is the reason this is a raise rather than a docstring note: "write
            # ordering across different `enqueue_write` calls ... is not guaranteed **except
            # within one `transaction()`**" reads, naturally, as contemplating enqueues inside a
            # transaction body. It cannot mean that here -- an enqueued row is committed by the
            # *writer*, in its own transaction, so it could not be part of the caller's one even
            # if the lock allowed it. Saying so is better than deadlocking at depth 1,000 in an
            # M-ORCH bulk path.
            raise WriteThroughQueryError(
                "enqueue_write was called inside a transaction() body on the same tier. The "
                "queue commits in its own transaction, so the row could not join this one; and "
                "the body holds the write lock the queue's writer needs, so at the configured "
                "depth this call would block forever on a drain that cannot start. Write it "
                "with tx.execute() to be part of this transaction, or enqueue it after the "
                "body exits."
            )
        self._ensure_writer()
        with self._condition:
            while self._pending >= self._limits.write_queue_depth and not self._stopping:
                self._condition.notify_all()
                self._condition.wait(timeout=self._limits.writer_poll_ms / 1000)
            if self._stopping:
                raise WriteQueueClosed(
                    "the store closed while this write was waiting on backpressure; the row was "
                    "not queued and has not been written"
                )
            self._queue.append(unit)
            self._stamps.append(time.monotonic())
            self._pending += 1
            self._note_depth_locked()
            self._condition.notify_all()

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        """Atomic and synchronous over the whole body, within one tier (`CT-STORE-03`).

        `BEGIN IMMEDIATE` rather than a deferred begin: the write lock is already held, so taking
        the database's write lock at the same moment keeps the two in step and means a competing
        process fails at the `BEGIN` -- where `_run`'s bounded `SQLITE_BUSY` retry can see it --
        rather than partway through the body.

        Rollback on **`BaseException`**, not `Exception`. `FUZZ-07` injects its abort as a custom
        exception and a `KeyboardInterrupt` mid-transaction is exactly the "uncontrolled kill"
        `NFR-STORE-02` is about; catching only `Exception` would leave a transaction open on the
        connection for the next caller to inherit.
        """
        if self._stopping:
            # Without this a transaction on a closed store reopens the write connection and
            # commits, so `close()` refuses one write door and holds the other open.
            raise WriteQueueClosed(
                "transaction() was called on a closed store. Reopening the write connection "
                "here would commit to a tier whose handle has already been released."
            )
        with self._write_lock:
            connection = self._connect_write()
            _run(connection, _BEGIN, retries=self._limits.retries)
            self._holder.in_transaction = True
            try:
                yield Tx(connection, self._limits.retries)
            except BaseException:
                self._holder.in_transaction = False
                try:
                    _run(connection, _ROLLBACK, retries=self._limits.retries)
                except sqlite3.Error:
                    pass  # the transaction is already gone; the caller's exception is the news
                raise
            self._holder.in_transaction = False
            _run(connection, _COMMIT, retries=self._limits.retries)

    # -- the writer side -----------------------------------------------------------------------

    def _ensure_writer(self) -> None:
        with self._condition:
            if self._thread is not None or self._stopping:
                return
            thread = threading.Thread(
                target=self._drain_forever, name="aeh-store-writer", daemon=True
            )
            # Started **inside** the lock, and published only once started. Publishing first and
            # starting after left a window in which `close()` read the attribute and called
            # `join()` on a thread that had not begun: `RuntimeError: cannot join thread before
            # it is started`. A shutdown racing a first `enqueue_write` is the ordinary shape of
            # a cancelled run, not an exotic one.
            thread.start()
            self._thread = thread

    def _note_depth_locked(self) -> None:
        """Track how long depth has been at or above the threshold. Call under `_condition`."""
        if self._pending >= self._limits.write_queue_depth:
            if self._over_since is None:
                self._over_since = time.monotonic()
        else:
            self._over_since = None

    def _next_batch(self) -> list[WriteUnit] | None:
        """The next batch to commit, or `None` once the queue is stopped and empty.

        `FR-STORE-04`'s "at most 100 results or 5 seconds, whichever comes first" is two
        conditions on one queue, and both are checked here so one place decides. The age is the
        age of the **oldest** pending row, which is what makes the interval a durability bound:
        `NFR-STORE-02` promises at most one commit window of results is lost, and a window
        measured from the newest row would never close under steady load.
        """
        poll = self._limits.writer_poll_ms / 1000
        with self._condition:
            while True:
                if self._queue:
                    oldest_age_ms = (time.monotonic() - self._stamps[0]) * 1000.0
                    due = (
                        len(self._queue) >= self._limits.commit_batch
                        or oldest_age_ms >= self._limits.commit_interval_ms
                        or self._stopping
                    )
                    if due:
                        take = min(len(self._queue), self._limits.commit_batch)
                        batch = [self._queue.popleft() for _ in range(take)]
                        for _ in range(take):
                            self._stamps.popleft()
                        # `_pending` is untouched here: these rows are still not durable, only
                        # somewhere else. It drops in `_commit`'s `finally`, which is what keeps
                        # `depth` from dipping through the gap between the deque and the COMMIT.
                        self._note_depth_locked()
                        # Wake anyone blocked on backpressure: the depth just dropped.
                        self._condition.notify_all()
                        return batch
                elif self._stopping:
                    return None
                self._condition.wait(timeout=poll)

    def _drain_forever(self) -> None:
        while True:
            batch = self._next_batch()
            if batch is None:
                return
            self._commit(batch)

    def _commit(self, batch: list[WriteUnit]) -> None:
        """One batch, one transaction, one latency measurement.

        A failure is **recorded, not swallowed**. The rows are already off the queue, so a writer
        that logged and moved on would let `write_queue_depth` reach zero with the rows gone -- a
        drain reporting success against data that was never written, which is the silent-failure
        trap `CLAUDE.md` seam 4 names. `close()` re-raises the first one and `store_metrics`
        counts them.
        """
        started = time.perf_counter()
        try:
            with self._write_lock:
                connection = self._connect_write()
                _run(connection, _BEGIN, retries=self._limits.retries)
                try:
                    for unit in batch:
                        _run(connection, unit.statement, unit.params,
                             retries=self._limits.retries)
                except BaseException:
                    try:
                        _run(connection, _ROLLBACK, retries=self._limits.retries)
                    except sqlite3.Error:
                        pass
                    raise
                _run(connection, _COMMIT, retries=self._limits.retries)
        except BaseException as error:  # noqa: BLE001 -- recorded; see the docstring
            self._failures.append(error)
        finally:
            # Measured even on failure: a batch that took four seconds to fail is the number an
            # operator needs, and `NFR-STORE-02`'s window is about elapsed time, not success.
            self._last_latency_ms = (time.perf_counter() - started) * 1000.0
            with self._condition:
                self._pending -= len(batch)
                self._note_depth_locked()
                self._condition.notify_all()

    # -- lifecycle ------------------------------------------------------------------------------

    def close(self, *, timeout_s: float = 30.0) -> None:
        """Flush what is queued, stop the thread, then re-raise the first write failure.

        Flush rather than discard: `close()` is the controlled shutdown, and the bounded loss
        `NFR-STORE-02` permits is the loss to an *uncontrolled* kill. Dropping queued rows on a
        clean close would make the two indistinguishable.
        """
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout_s)
        if self._failures:
            raise self._failures[0]


class SqliteTierHandle:
    """One tier's database. `query`, `enqueue_write`, `transaction` — and nothing else.

    The member list is `CT-STORE-01`'s and it is closed on purpose: `FUZZ-07`'s docstring records
    an earlier draft that reached for `handle.has_result()` and `handle.status()`, which would
    have added two members to a protocol the design deliberately shuts. Anything a caller needs
    is a declared statement through `query`.
    """

    __slots__ = (
        "_connection", "_extra_readers", "_limits", "_local", "_opened", "_owner_thread",
        "_path", "_queue", "_read_only", "_retries", "_write_connection",
    )

    def __init__(self, connection: sqlite3.Connection, opened: TierOpened, *,
                 path: Path, limits: StoreLimits | None = None,
                 retries: int | None = None) -> None:
        self._connection = connection
        self._opened = opened
        self._read_only = opened.read_only
        self._path = path
        limits = limits if limits is not None else StoreLimits()
        if retries is not None:
            limits = replace(limits, retries=retries)
        self._limits = limits
        self._retries = limits.retries
        self._write_connection: sqlite3.Connection | None = None
        # One read connection per thread. `CT-STORE-04` promises concurrent readers never block
        # the writer, and sqlite3 refuses a connection used off its creating thread at all --
        # `ProgrammingError`, before SQLite is even reached. Passing `check_same_thread=False` and
        # sharing one connection would silence that check and put every reader behind the GIL and
        # behind each other's cursors, which is "readers block readers" wearing the right answer's
        # clothes. Under WAL a per-thread connection holds no lock the writer needs, which is the
        # property the requirement is actually about.
        self._local = threading.local()
        self._extra_readers: list[sqlite3.Connection] = []
        self._owner_thread = threading.get_ident()
        # No queue on a read-only handle, and no lazy one either. `FR-STORE-13` opens a Tier P
        # database to inspect a package *before* it is trusted, so the write path must be absent
        # rather than merely unused -- a queue that existed and refused later is a queue that
        # could open a connection and move the file's mtime while refusing.
        self._queue: WriteQueue | None = (
            None if self._read_only else WriteQueue(self._open_write_connection, limits)
        )

    # -- the read connections ------------------------------------------------------------------

    def _read_connection(self) -> sqlite3.Connection:
        """This thread's read connection, opened on first use.

        The connection `_open_tier` built is this handle's own and stays the one the constructing
        thread uses -- it is the one migrations ran on and the one `TierOpened` describes. Every
        other thread gets its own, recorded in `_extra_readers` so `close()` can reach it: a
        connection nothing closes is, on Windows, a file `purge_cohort` cannot delete.
        """
        existing = getattr(self._local, "connection", None)
        if existing is not None:
            return existing
        connection = _connect(
            self._path, read_only=self._read_only,
            busy_timeout_ms=self._limits.busy_timeout_ms, retries=self._limits.retries,
            # Used by exactly one thread -- the one this branch just created it for -- so the
            # WAL argument above is untouched. The flag is off because `close()` runs on a
            # *different* thread, and with the check on it raised `ProgrammingError` there,
            # aborting the loop and leaving every later reader and the handle's own connection
            # open: precisely the locked file this list exists to prevent.
            check_same_thread=False,
        )
        self._local.connection = connection
        self._extra_readers.append(connection)
        return connection

    # -- the write connection ----------------------------------------------------------------

    def _open_write_connection(self) -> sqlite3.Connection:
        """The second connection, opened on first write and kept for the handle's life.

        **Separate from the read connection, and that is `CT-STORE-04`.** Under WAL a reader
        holds no lock a writer needs, so two connections is what makes "concurrent readers never
        block the writer" a property of the database rather than of a mutex this module happens
        to release often enough.

        `check_same_thread=False` because two threads legitimately use it -- the drain thread for
        batches, the caller's thread for a `transaction()` body -- and `WriteQueue._write_lock`
        is what keeps them from doing so at once. The flag disables sqlite3's own thread check;
        it does not make the connection safe on its own, and the lock is not decoration.

        `journal_mode` is not set here: WAL lives in the file header, `_open_tier` wrote it, and
        this connection inherits it. `foreign_keys` is the opposite -- per connection, never
        persisted -- so `_connect` setting it is exactly what `FR-STORE-14` needs, since this is
        the connection that actually issues every write `CT-STORE-13` promises will fail.
        """
        if self._write_connection is None:
            self._write_connection = _connect(
                self._path, read_only=False, busy_timeout_ms=self._limits.busy_timeout_ms,
                retries=self._limits.retries, check_same_thread=False,
            )
        return self._write_connection

    def _refuse_read_only(self, door: str) -> None:
        if self._read_only:
            raise ReadOnlyTierError(
                f"{door} was called on a read-only handle for {self._path.name}. FR-STORE-13 "
                "opens a Tier P database read-only so an imported package can be inspected "
                "before it is trusted, and a write through that handle would alter the file "
                "whose provenance is the question."
            )

    @property
    def opened(self) -> TierOpened:
        """What opening this database did. Read-only; see `TierOpened`."""
        return self._opened

    def query(self, statement: Statement, **params: Any) -> Sequence[Row]:
        """Run a declared **read** and return its rows.

        **No order is promised** (`CT-STORE-18`): rows come back in whatever order SQLite
        produces, and a caller needing an order states it in the statement. Nothing here sorts,
        because a module that sorted would make every caller's unstated assumption work until the
        day it did not.

        **A write through here is refused**, and that is not tidiness. The connection is in
        autocommit, so before this guard `query(Statement("INSERT ..."))` wrote and committed
        synchronously — review used exactly that to seed every fixture it needed.
        `CT-STORE-02` makes writing *asynchronous*, through `enqueue_write`; a synchronous write
        channel wearing the name `query` is the contract violation that clause exists to prevent.
        Today it is the only write path there is, so every caller written before #11 lands would
        be written against it. `TC-STORE-C01` says the closed member list matters *"because it is
        the door through which every other clause here gets bypassed"* — this is that door, one
        level below the member list.

        The test is the statement's first keyword. Reads are `SELECT`, `WITH`, `VALUES`,
        `EXPLAIN` and `PRAGMA` — `PRAGMA` because schema introspection is how a caller inspects an
        imported package (`FR-STORE-13`) and how `TC-STATS-C18` sweeps Tier D for a name column.
        It is a keyword check and not a parser: it stops a caller reaching for the wrong method,
        which is the only thing that needs stopping, because every caller is in-process trusted
        code and there is no untrusted path into a statement.
        """
        declared = statement if isinstance(statement, Statement) else Statement(statement)
        _refuse_write(declared)
        return _run(self._connection_for_this_thread(), declared, params,
                    retries=self._retries).fetchall()

    def _connection_for_this_thread(self) -> sqlite3.Connection:
        """`_connection` on the thread that opened the handle, a private one on any other.

        Compared by thread identity rather than by trying the connection and catching
        `ProgrammingError`: a probe would be a second `execute()` in this module, and
        `KNOWN_EXECUTE_SITES` in `tests/artifact/test_store_query_surface.py` is an exact set for
        the good reason that every site is somewhere a statement reaches SQLite.
        """
        if threading.get_ident() == self._owner_thread:
            return self._connection
        return self._read_connection()

    def enqueue_write(self, unit: WriteUnit | Statement | str, /, **params: Any) -> None:
        """Queue one write and return. **Asynchronous** (`CT-STORE-02`).

        Returns before the row is durable, and that is the clause design 3.3 calls "the single
        most load-bearing clause in this contract and the easiest to get wrong". A caller that
        must observe its own write reads through `transaction()` or waits for the commit batch;
        nothing here waits on its behalf.

        **Two accepted forms, because the design and the suite disagree.** 3.3's Interfaces block
        types the parameter `WriteUnit`; every merged case calls
        `enqueue_write(statement, **params)`. Both work: a `WriteUnit` is used as given, and a
        statement plus keywords is packed into one. Supporting only the declared form would break
        four merged files including a P0; supporting only the convenience form would drop the
        signature the design states. The gap is reported against the design rather than resolved
        by picking a side.

        Blocks at the configured depth (`FR-STORE-05`) -- see `WriteQueue.enqueue`.
        """
        self._refuse_read_only("enqueue_write")
        if isinstance(unit, WriteUnit):
            if params:
                raise TypeError(
                    "enqueue_write got both a WriteUnit and keyword parameters. The unit already "
                    "carries its params; passing both leaves it ambiguous which wins."
                )
            queued = unit
        else:
            declared = unit if isinstance(unit, Statement) else Statement(unit)
            queued = WriteUnit(statement=declared, params=params)
        assert self._queue is not None  # guaranteed by _refuse_read_only above
        self._queue.enqueue(queued)

    def transaction(self) -> ContextManager[Tx]:
        """Atomic, synchronous, whole-body, within one tier (`CT-STORE-03`).

        Within **one tier handle**. Cross-tier atomicity is deliberately not provided, and a
        caller needing a row in Tier C and a row in Tier D together does not get it from here --
        `CT-STORE-03` says so, and two databases cannot be committed atomically without a
        transaction manager this design rejects along with the server process.
        """
        self._refuse_read_only("transaction")
        assert self._queue is not None  # guaranteed by _refuse_read_only above
        return self._queue.transaction()

    @property
    def metrics(self) -> dict[str, Any]:
        """This tier's share of `CT-STORE-17`'s signals. Aggregated by `store_metrics`."""
        queue = self._queue
        return {
            "write_queue_depth": 0 if queue is None else queue.depth,
            "batch_commit_latency_ms": 0.0 if queue is None else queue.last_commit_latency_ms,
            "backpressure_active": False if queue is None else queue.backpressure_active,
            "queue_depth_sustained": False if queue is None else queue.sustained_over_threshold(),
            "write_failures": 0 if queue is None else len(queue.failures),
            "database_file_bytes": self._path.stat().st_size if self._path.exists() else 0,
        }

    def _close(self) -> None:
        """Flush the queue, then close both connections.

        **Private, and `CT-STORE-01` is why.** Design §3.3 fixes the `TierHandle` surface at
        `query`, `enqueue_write` and `transaction` — *"and nothing else"* — and `TC-STORE-15`
        asserts that over the concrete class rather than the Protocol, precisely because a fourth
        public method is where an off-protocol search arrives. #10 shipped this as `close()`,
        which made the handle a four-member object; the written-ahead case caught it the moment
        `blobs()` let the case run. Lifecycle belongs to `Store.close()`, which is the only
        caller and is where `TC-STORE-16`'s `require_attr(store, "close")` looks for it.

        The queue closes **first**: it is still holding rows bound for the write connection, and
        closing that connection out from under a batch mid-flight is how a clean shutdown starts
        losing the writes an uncontrolled kill was supposed to be the only thing that loses.
        """
        if self._queue is not None:
            try:
                self._queue.close()
            finally:
                if self._write_connection is not None:
                    self._write_connection.close()
                    self._write_connection = None
        # Every one of them, even if one raises. A loop that stopped at the first failure would
        # leave the rest open while reporting the problem, which on Windows is a file
        # `purge_cohort` cannot delete -- the failure this list exists to prevent, reached by the
        # cleanup rather than by the absence of one.
        for reader in self._extra_readers:
            try:
                reader.close()
            except sqlite3.Error:
                pass
        self._extra_readers.clear()
        self._connection.close()


# --- the store ---------------------------------------------------------------------------------


class SqliteStore:
    """`Store` over a data directory. One file per package, one per cohort, one shared durable.

    Handles are cached per id, so two calls to `cohort("c-1")` return one handle over one
    connection. That matters more than it looks: `CT-STORE-04` promises readers never observe a
    partially applied transaction, and two connections to one file would make "the writer" a
    matter of which handle a caller happened to hold.
    """

    __slots__ = (
        "_blobs", "_busy_timeout_ms", "_data_dir", "_handles", "_limits", "_opened",
        "_read_only", "_retries",
    )

    def __init__(self, data_dir: Path, *, busy_timeout_ms: int | None = None,
                 retries: int | None = None, limits: StoreLimits | None = None,
                 read_only: bool = False) -> None:
        self._read_only = read_only
        if limits is None:
            limits = StoreLimits()
        if busy_timeout_ms is not None:
            limits = replace(limits, busy_timeout_ms=busy_timeout_ms)
        if retries is not None:
            limits = replace(limits, retries=retries)
        self._limits = limits
        self._data_dir = data_dir
        self._busy_timeout_ms = limits.busy_timeout_ms
        self._retries = limits.retries
        self._handles: dict[tuple[Tier, str, bool], SqliteTierHandle] = {}
        self._opened: list[TierOpened] = []
        self._blobs: ContentAddressedBlobStore | None = None

    # -- layout, verbatim from §3.3's data model ------------------------------------------------

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def limits(self) -> StoreLimits:
        """The knob values this store was constructed with. See `StoreLimits`."""
        return self._limits

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
        # One file, one mode. Review measured the alternative: with both cached, two connections
        # were live on one package and the read-only handle observed the writable one's migration
        # — so "inspect an imported package before it is trusted" (`FR-STORE-13`) was inspecting a
        # file this same process had just changed. Refusing is the honest answer: the two modes
        # answer different questions, and holding both at once means neither answer is the one the
        # caller thinks it has.
        conflict = self._handles.get((tier, key, not read_only))
        if conflict is not None:
            raise ConfigurationProblem(
                f"{path} is already open {'read-write' if read_only else 'read-only'} in this "
                f"store. FR-STORE-13's read-only handle exists to inspect a file whose "
                f"provenance is in question, and a writable handle on the same file in the same "
                f"process is what makes that inspection meaningless. Close the store, or inspect "
                f"through the handle you already hold."
            )
        connection, opened = _open_tier(
            path, tier, read_only=read_only, busy_timeout_ms=self._busy_timeout_ms,
            retries=self._retries,
        )
        handle = SqliteTierHandle(connection, opened, path=path, limits=self._limits)
        self._handles[(tier, key, read_only)] = handle
        self._opened.append(opened)
        return handle

    def package(self, package_id: str, *, read_only: bool | None = None) -> SqliteTierHandle:
        """Tier P — one file per package, permanent, no PII by construction.

        `read_only=True` is `FR-STORE-13`: an imported package is inspected *before* it is
        trusted, and inspecting it through a writable handle would let the inspection itself
        migrate a file whose provenance is exactly what is in question.
        """
        return self._handle(
            Tier.PACKAGE, package_id, self.package_path(package_id),
            read_only=self._read_only if read_only is None else read_only,
        )

    def cohort(self, cohort_id: str) -> SqliteTierHandle:
        """Tiers C **and** R — one file, per administration, heavy PII."""
        return self._handle(
            Tier.COHORT, cohort_id, self.cohort_path(cohort_id), read_only=self._read_only
        )

    def durable(self) -> SqliteTierHandle:
        """Tier D — one shared file, permanent, pseudonymized."""
        return self._handle(Tier.DURABLE, "", self.durable_path(), read_only=self._read_only)

    # -- the two surfaces later stories fill in ---------------------------------------------------

    def blobs(self) -> ContentAddressedBlobStore:
        """The content-addressed blob directory (`FR-STORE-06`).

        Cached, so two calls return one store over one directory — the same reason handles are
        cached. It holds no connection and no thread, so this is about identity rather than
        resources: `blobs() is blobs()` keeps "the blob store" a thing a caller can talk about.
        """
        if self._blobs is None:
            self._blobs = ContentAddressedBlobStore(
                self._data_dir / "blobs", self._data_dir / INCOMING_DIR
            )
        return self._blobs

    def purge_cohort(self, cohort_id: str) -> Any:
        """Delete Tiers C and R and `VACUUM` (`FR-STORE-07`). **#13.**"""
        raise NotImplementedError(
            "Store.purge_cohort is issue #13 (FR-STORE-07). It is irreversible and it is the "
            "only operation that deletes student work, so it arrives with its "
            "PurgePreconditionError check or not at all."
        )

    # -- lifecycle ---------------------------------------------------------------------------------

    def close(self) -> None:
        """Close every handle, then report the first write failure any of them recorded.

        Every handle is closed even if one raises. A store that abandoned the remaining tiers on
        the first bad one would leave open connections behind while reporting the failure, and on
        Windows an open connection is a file nothing else can delete -- which is how `close()`
        starts breaking `purge_cohort` rather than merely reporting a problem.
        """
        first: BaseException | None = None
        for handle in self._handles.values():
            try:
                handle._close()  # noqa: SLF001 -- Store owns handle lifecycle; see _close
            except BaseException as error:  # noqa: BLE001 -- re-raised below, after every close
                first = first if first is not None else error
        self._handles.clear()
        if first is not None:
            raise first

    def __enter__(self) -> SqliteStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def open_store(data_dir: Path | str | None = None, *, read_only: bool = False,
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

    `read_only=True` makes **every** handle this store hands out read-only. `FR-STORE-13` is
    written about Tier P, and `package(id, read_only=True)` remains the narrow form — but the
    situation the requirement describes is inspecting an untrusted import, and a store that
    refused to write the package while happily migrating `durable.sqlite` on the way past would
    have modified the data directory during the very session that was supposed to leave no trace.
    The flag is the whole-store form of the same promise, and `TC-STORE-16` opens it this way.
    """
    root = Path(data_dir).expanduser() if data_dir is not None else data_dir_from_environment(
        environ
    )
    root = root.resolve()
    for child in (root, root / "packages", root / "cohorts", root / "blobs"):
        child.mkdir(parents=True, exist_ok=True, mode=OWNER_ONLY_DIR)

    return SqliteStore(
        root, limits=StoreLimits.from_environment(environ), read_only=read_only
    )


# --- observability -------------------------------------------------------------------------------


def blob_store_stats(blobs: ContentAddressedBlobStore) -> dict[str, Any]:
    """`file_count` and `bytes_on_disk` for a blob directory, by walking it.

    A function rather than a `BlobStore` member for the reason `store_metrics` is one:
    `CT-STORE-07` fixes that protocol at `put` / `get` / `path`, and `TC-STORE-C07` asserts the
    surface. Accounting is not one of the three.
    """
    return blobs.stats()


def lease_clock(store: SqliteStore, clock: Clock | None = None) -> LeaseClock:
    """The store's monotonic lease clock (`FR-STORE-11`, `CT-STORE-14`).

    `clock` is the injection point (`CLAUDE.md` seam 2, test plan §4.2): a `FrozenClock` whose
    wall time can be moved backwards while its monotonic counter is not is the only way to assert
    `CT-STORE-14`, and a module that reached for `time.monotonic()` directly could not be told to.

    Not a `Store` member: §3.3 closes that protocol at five, and `TC-STORE-C01` calls the closed
    list "the door through which every other clause here gets bypassed". Design §3.3 names no
    accessor for the lease clock at all, which is reported as a gap — see
    `tests/support/store_api.py`.
    """
    return LeaseClock(store, clock)


def store_metrics(store: SqliteStore) -> dict[str, Any]:
    """`CT-STORE-17`'s five signals, the two alerts, and the configured values behind them.

    *"Emits write-queue depth, batch commit latency, database file sizes, free disk space, and
    `VACUUM` duration under those names. Free-disk and queue-depth are alert inputs and their
    semantics are contract."* Design 3.3 names them in prose and fixes no spelling, so the
    spelling is here and the gap is reported against the design.

    A **function**, not a `Store` member, and deliberately: `CT-STORE-01` closes `Store` to
    `package`, `cohort`, `durable`, `blobs` and `purge_cohort`, and `TC-STORE-C01` calls that
    closed member list "the door through which every other clause here gets bypassed". Adding a
    sixth method to read metrics would open exactly that door for the most innocuous-looking
    reason there is.

    **`database_file_bytes` is a mapping, not a scalar.** The tiers have different lifetimes --
    Tier D is permanent, C and R are purged together -- so one aggregate number cannot answer
    "which tier is growing", which is the only question the signal exists to answer.

    **`vacuum_duration_ms` is honestly zero until a `VACUUM` runs.** The only one this module
    performs is `purge_cohort`'s, which is #13's, so reporting anything else here would be
    inventing a measurement.
    """
    depth = 0
    latency_ms = 0.0
    failures = 0
    backpressure = False
    sustained = False
    sizes: dict[str, int] = {}

    for (tier, key, _read_only), handle in store._handles.items():  # noqa: SLF001
        share = handle.metrics
        depth += int(share["write_queue_depth"])
        latency_ms = max(latency_ms, float(share["batch_commit_latency_ms"]))
        failures += int(share["write_failures"])
        backpressure = backpressure or bool(share["backpressure_active"])
        sustained = sustained or bool(share["queue_depth_sustained"])
        # Keyed per open tier, so "which tier is growing" is answerable. `TC-STORE-24` reads
        # `durable` and a key beginning `cohort`; the id is carried too, because two cohorts in
        # one run are two files and an aggregate over them answers nothing.
        label = tier.value if not key else f"{tier.value}:{key}"
        sizes[label] = int(share["database_file_bytes"])

    limits = store.limits
    free_bytes = shutil.disk_usage(store.data_dir).free

    # `NFR-STORE-06`'s 500 MB, measured rather than assumed. §3.3 records the figure as an
    # Assumption and #12 asks for "a measured, knob-adjustable expectation": reporting the actual
    # footprint next to the budget is what lets `TC-STORE-20` state the number so the Assumption
    # can be revisited, instead of asserting a literal nobody re-derived.
    blob_bytes = store.blobs().stats()["bytes_on_disk"]
    data_dir_bytes = sum(
        entry.stat().st_size for entry in store.data_dir.rglob("*") if entry.is_file()
    )

    firing: list[str] = []
    # A projection of zero means "M-ORCH stated no remaining-run requirement". An alert with no
    # projection behind it stays quiet rather than inventing a threshold -- an always-on alert is
    # worth exactly what an always-off one is worth.
    if limits.projected_run_bytes > 0 and free_bytes < limits.projected_run_bytes:
        firing.append(ALERT_FREE_DISK)
    if sustained:
        firing.append(ALERT_QUEUE_DEPTH)

    return {
        # -- the five CT-STORE-17 signals ------------------------------------------------------
        "write_queue_depth": depth,
        "batch_commit_latency_ms": latency_ms,
        "database_file_bytes": sizes,
        "free_disk_bytes": free_bytes,
        "vacuum_duration_ms": 0.0,
        # -- NFR-STORE-06's capacity Assumption, measured (#12) ---------------------------------
        "blob_bytes_on_disk": blob_bytes,
        "data_dir_bytes": data_dir_bytes,
        "capacity_budget_bytes": limits.capacity_budget_bytes,
        # -- the alerts, declared and firing ---------------------------------------------------
        "alerts_declared": list(DECLARED_ALERTS),
        "alerts_firing": firing,
        # -- FR-STORE-05's level, which M-ORCH throttles on (CT-STORE-06, FR-ORCH-21) ----------
        "backpressure_active": backpressure,
        # -- what the knobs resolved to, so a caller can tell a boundary from a default --------
        "configured_queue_depth": limits.write_queue_depth,
        "configured_commit_batch": limits.commit_batch,
        "configured_commit_interval_ms": limits.commit_interval_ms,
        "configured_projected_run_bytes": limits.projected_run_bytes,
        # -- writes the queue accepted and could not commit. Zero is the only healthy value ----
        "write_failures": failures,
    }
