"""M-STORE: the persistence layer, SQLite files plus a content-addressed blob store (design §3.3).

There are three kinds of database file ("tiers"): one per package (Tier P), one per cohort
(Tier C) and one durable file (Tier D) for what outlives a cohort. Other modules reach them
only through a `TierHandle`, which offers exactly three things: `query` (reads),
`enqueue_write` and `transaction` (writes). All writes go through one writer thread per store,
which batches commits and applies backpressure. Every SQL statement is declared as a
`Statement`, never assembled from strings, and every one reaches SQLite through a single
execute site (`_run`).

Each module that owns tables contributes its migrations to `TIER_MIGRATIONS` at import time.
Opening a tier with an incomplete migration chain is refused at the open, naming the cause.

Files:
    settings.py      the data directory and every environment-sensitive number, with its knob
    errors.py        the errors this package raises
    disk_full.py     recognizing a full disk and halting the process
    student_names.py keeping student names out of the durable tier
    security.py      owner-only file permissions and refusing world-writable locations
    interfaces.py    `Statement`, `Tier`, `TierHandle`, `BlobStore` and `Store`
    migrations.py    the base schemas, `Migration`, `TIER_MIGRATIONS` and the version pins
    purge.py         purging a cohort file once its results are promoted
    connection.py    opening a database, migrating it, and the single execute site `_run`
    limits.py        `StoreLimits`, the numbers resolved once when the store opens
    blobs.py         the content-addressed blob store
    leases.py        the store's clocks, and leases timed by a persisted monotonic counter
    transaction.py   `Tx`, the handle a transaction body writes through
    write_queue.py   `WriteQueue`, the single writer thread
    tier_handle.py   `SqliteTierHandle`, one tier's database
    sqlite_store.py  `SqliteStore`, `open_store`, and the store's metrics
    statements.py    the shared `STATEMENTS` registry

Detailed design notes (the full original module description): `docs/code-notes/store.md`.
"""

from __future__ import annotations

import os

from .settings import (
    ALERT_FREE_DISK,
    ALERT_QUEUE_DEPTH,
    BUSY_RETRIES_ENV,
    BUSY_TIMEOUT_MS_ENV,
    CAPACITY_BUDGET_BYTES_ENV,
    COMMIT_BATCH_ENV,
    COMMIT_INTERVAL_MS_ENV,
    DATA_DIR_ENV,
    data_dir_from_environment,
    DECLARED_ALERTS,
    DEFAULT_BUSY_RETRIES,
    DEFAULT_BUSY_TIMEOUT_MS,
    DEFAULT_CAPACITY_BUDGET_BYTES,
    DEFAULT_COMMIT_BATCH,
    DEFAULT_COMMIT_INTERVAL_MS,
    DEFAULT_LEASE_RESTORE_MARGIN_S,
    DEFAULT_PROJECTED_RUN_BYTES,
    DEFAULT_QUEUE_DEPTH_SUSTAIN_MS,
    DEFAULT_STAGED_BLOB_TTL_S,
    DEFAULT_WRITE_QUEUE_DEPTH,
    DEFAULT_WRITER_POLL_MS,
    DISK_FULL_EXIT_CODE,
    LEASE_RESTORE_MARGIN_S_ENV,
    OWNER_ONLY_DIR,
    OWNER_ONLY_FILE,
    PROJECTED_RUN_BYTES_ENV,
    QUEUE_DEPTH_SUSTAIN_MS_ENV,
    STAGED_BLOB_TTL_S_ENV,
    WRITE_QUEUE_DEPTH_ENV,
    WRITER_POLL_MS_ENV,
)
from .errors import (
    ConfigurationProblem,
    CrossTierTransactionError,
    DiskFullError,
    IncompleteMigrationChainError,
    InsecureLocationError,
    InvalidContentHashError,
    MigrationError,
    PurgePreconditionError,
    ReadOnlyTierError,
    SchemaTooNewError,
    StatementConflictError,
    StoreError,
    StudentNameInTierDError,
    WriteQueueClosed,
    WriteThroughQueryError,
)
from .disk_full import _halt_process_on_disk_full
from .student_names import (
    BARE_NAME_COLUMNS,
    is_student_name_column,
    NAME_TOKENS,
    PERSON_TOKENS,
    PSEUDONYM_TOKENS,
    STRONG_NAME_TOKENS,
    TIER_D_IDENTITY_COLUMN,
    WEAK_NAME_TOKENS,
)
from .security import _insecure_location_reason
from .interfaces import BlobStore, Row, Statement, Store, Tier, TierHandle, WriteUnit
from .migrations import (
    COMPLETE_SCHEMA_VERSIONS,
    current_schema_version,
    Migration,
    MigrationPrecondition,
    _SCHEMA_VERSION_TABLE,
    TIER_MIGRATIONS,
)
from .purge import PurgeReport
from .connection import READ_VERBS, _run, TierOpened
from .limits import StoreLimits
from .blobs import BLOB_HASH_PATTERN, blob_store_stats, ContentAddressedBlobStore, INCOMING_DIR
from .leases import Clock, Lease, lease_clock, LeaseClock, SystemClock
from .transaction import Tx
from .write_queue import WriteQueue
from .tier_handle import SqliteTierHandle
from .sqlite_store import open_store, SqliteStore, store_metrics
from .statements import STATEMENTS


__all__ = [
    "BlobStore",
    "COMPLETE_SCHEMA_VERSIONS",
    "CrossTierTransactionError",
    "DiskFullError",
    "InsecureLocationError",
    "IncompleteMigrationChainError",
    "Migration",
    "MigrationError",
    "MigrationPrecondition",
    "PurgePreconditionError",
    "PurgeReport",
    "Row",
    "SchemaTooNewError",
    "Statement",
    "Store",
    "StoreError",
    "StudentNameInTierDError",
    "TIER_D_IDENTITY_COLUMN",
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
    "is_student_name_column",
    "open_store",
    "store_metrics",
]
