"""Opening a database file, migrating it, and `_run`, the one place SQL reaches SQLite."""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

from .settings import DEFAULT_BUSY_RETRIES, OWNER_ONLY_DIR
from .errors import (
    ConfigurationProblem,
    IncompleteMigrationChainError,
    SchemaTooNewError,
    WriteThroughQueryError,
)
from .security import _harden_dir, _harden_files
from .interfaces import Statement, Tier
from .migrations import (
    COMPLETE_SCHEMA_VERSIONS,
    current_schema_version,
    MigrationPrecondition,
    _SCHEMA_VERSION_TABLE,
    TIER_MIGRATIONS,
)


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


#: The per-thread lock-wait sink (`#118`'s export-seam figure). `None` means "nothing is
#: counting" — the open-time sites (migration, pragmas) run exactly there. A handle-owned
#: window installs its counter dict for the statements it runs; `_run` reads the sink of
#: *this thread* on every retry, so the drain thread's waits land in the same counter the
#: handle's metrics report, and a caller code path inside a `transaction()` body counts
#: into the same number (its `Tx` statements run inside the transaction's window).
_LOCK_WAIT_SINK = threading.local()


@contextmanager
def _counting_lock_waits(counter: dict[str, int]) -> Iterator[None]:
    """Install `counter` as this thread's lock-wait sink for the wrapped block.

    Stack discipline, not assignment: a nested window (a caller running another handle's
    `query` inside a `transaction()` body) restores the outer sink on exit, so each
    handle's waits land in its own counter.
    """
    previous = getattr(_LOCK_WAIT_SINK, "counter", None)
    _LOCK_WAIT_SINK.counter = counter
    try:
        yield
    finally:
        _LOCK_WAIT_SINK.counter = previous


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

    `lock_waits` (the `#118` export-seam figure) is counted through the thread-local sink
    `_LOCK_WAIT_SINK`, not through this signature: a test that patches `_run` with a
    same-shape wrapper (TC-STORE-13's does, verbatim) must keep working, and a new keyword
    would break every one of them. A handle-owned window (`SqliteTierHandle.query`,
    `WriteQueue._commit`, `WriteQueue.transaction`) installs its counter dict for the
    statements it runs; every SQLITE_BUSY retry slept through inside the window increments
    it, and the count surfaces in `SqliteTierHandle._metrics` → `store_metrics` →
    `PipelineOutcome.lock_waits`. Open-time sites (migration, the pragmas) run outside any
    window and are deliberately outside the count: the figure is about a *run's* waits,
    not the file's construction.
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
            sink = getattr(_LOCK_WAIT_SINK, "counter", None)
            if sink is not None:
                sink["lock_waits"] += 1
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
                cursor = _run(connection, statement, retries=retries)
                check = getattr(statement, "check", None)
                if isinstance(statement, MigrationPrecondition) and check is not None:
                    check(cursor.fetchall())
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

    The chain-completeness refusal comes **first**, before the existence check and before the
    too-new check: a process whose migration chain is short cannot be trusted to judge *any*
    file — its too-new verdict would be an artifact of the missing migrations rather than a
    property of the file, and an open it allowed would build the file short of the full schema
    for a failure at a distance. `COMPLETE_SCHEMA_VERSIONS` carries the per-tier pin;
    `IncompleteMigrationChainError` carries the story (`#234`).
    """
    implemented = current_schema_version(tier)
    complete = COMPLETE_SCHEMA_VERSIONS[tier]
    # A chain is complete when every version up to the pin is registered, not merely the
    # highest: a module that owns a middle migration (#359's `aeh.agg` at Cohort 20, under
    # `aeh.judge`'s 22) is otherwise missed whenever a later owner was imported (#361).
    registered = {migration.version for migration in TIER_MIGRATIONS[tier]}
    if implemented < complete or not set(range(1, complete + 1)) <= registered:
        missing = sorted(set(range(1, complete + 1)) - registered)
        raise IncompleteMigrationChainError(
            f"{tier.value!r} would open against a migration chain that ends at version "
            f"{implemented} and is missing version(s) {missing}, but this binary implements "
            f"1..{complete} for the tier once every "
            f"module that contributes migrations has been imported. The chains in "
            f"TIER_MIGRATIONS are concatenated at import time by the modules that own the "
            f"schema they add (Tier P: aeh.pkg and aeh.det; Cohort: aeh.ingest, aeh.det, "
            f"aeh.orch, aeh.extract, aeh.synth, aeh.judge, aeh.agg and aeh.grade; "
            f"Tier D: aeh.det, aeh.integ, aeh.review, aeh.pkg and aeh.judge), so this "
            f"process has imported some "
            f"of them and not the rest. Import the owning modules before the first open — "
            f"`import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, "
            f"aeh.judge, aeh.orch, aeh.pkg, aeh.synth, aeh.review` "
            f"registers every "
            f"tier's complete chain — or the file builds short of the full schema and the "
            f"missing columns surface later, far from this open, as a distant `no such "
            f"column` (#46's probe: `no such column: parent_version_id`; #234)."
        )
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
            # Owner-only on the directory (umask-filtered at mkdir), on the file this
            # connection just created or reopened, and on the `-wal`/`-shm` siblings the
            # WAL pragma above created (`FR-STORE-09`). Only ever on the writable path,
            # and only after the refusal: a read-only inspection must not touch the file
            # or directory it is inspecting, and the too-new refusal must leave what it
            # refused untouched — chmod'ing the parent there would have done both.
            _harden_dir(path.parent)
            _harden_files(path)

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
