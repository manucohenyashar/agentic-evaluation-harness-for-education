"""`SqliteStore` over a data directory, `open_store`, and the store's metrics."""

from __future__ import annotations

import shutil
import sqlite3
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from .settings import (
    ALERT_FREE_DISK,
    ALERT_QUEUE_DEPTH,
    data_dir_from_environment,
    DECLARED_ALERTS,
    OWNER_ONLY_DIR,
)
from .errors import ConfigurationProblem, PurgePreconditionError, ReadOnlyTierError
from .disk_full import _halt_if_disk_full
from .security import _harden_dir, _harden_files, _refuse_insecure_location, _validated_component
from .interfaces import Tier
from .purge import (
    _assert_purge_order_matches_fk_graph,
    _COHORT_PURGE_ORDER,
    _collect_blob_hash_references,
    _collect_blob_hash_references_from_dump,
    _is_pure_refusal_trigger,
    _PRAGMA_DEFER_FOREIGN_KEYS,
    _PRAGMA_WAL_CHECKPOINT_TRUNCATE,
    _PURGE_BLOB_HASH_SCANS,
    _PURGE_DELETES,
    _PURGE_PRECONDITIONS,
    _PURGE_PROMOTED_ROWS,
    _PURGE_TABLE_INFO,
    PurgeReport,
    _SCHEMA_VERSION_TABLE_NAME,
    _SELECT_COHORT_TABLES,
    _SELECT_COHORT_TRIGGERS_VIEWS,
    _VACUUM,
)
from .connection import _BEGIN, _COMMIT, _connect, _open_tier, _ROLLBACK, _run, TierOpened
from .limits import StoreLimits
from .blobs import ContentAddressedBlobStore, INCOMING_DIR
from .tier_handle import SqliteTierHandle


# --- the store ---------------------------------------------------------------------------------


class SqliteStore:
    """`Store` over a data directory. One file per package, one per cohort, one shared durable.

    Handles are cached per id, so two calls to `cohort("c-1")` return one handle over one
    connection. That matters more than it looks: `CT-STORE-04` promises readers never observe a
    partially applied transaction, and two connections to one file would make "the writer" a
    matter of which handle a caller happened to hold.
    """

    __slots__ = (
        "_blobs", "_busy_timeout_ms", "_data_dir", "_handles", "_last_vacuum_ms",
        "_lease_clock", "_limits", "_opened", "_read_only", "_retries",
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
        self._lease_clock: Any = None
        # The last `purge_cohort`'s VACUUM duration, honestly 0.0 until one runs — the
        # CT-STORE-17 signal `store_metrics` reports.
        self._last_vacuum_ms = 0.0

    # -- layout, verbatim from §3.3's data model ------------------------------------------------

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def limits(self) -> StoreLimits:
        """The knob values this store was constructed with. See `StoreLimits`."""
        return self._limits

    @property
    def lease_clock_instance(self) -> Any:
        """This store's `LeaseClock`, or `None`. Set by `lease_clock()`; see why it is cached."""
        return self._lease_clock

    def attach_lease_clock(self, clock: Any) -> None:
        """Record the store's one lease clock. Called by `lease_clock()`, not by callers."""
        self._lease_clock = clock

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
            if not self._read_only:
                # Once, on first use. A read-only store must touch nothing (`FR-STORE-13`).
                self._blobs.reap_staged(self._limits.staged_blob_ttl_s)
        return self._blobs

    def purge_cohort(self, cohort_id: str) -> PurgeReport:
        """Delete Tiers C and R and `VACUUM` (`FR-STORE-07`, `CT-STORE-10`).

        Irreversible, and the only operation in this module that deletes student work.

        The precondition is checked **against Tier D, before anything is deleted**:
        `audit_record`, `label` and `criterion_stats` must each exist, carry the `cohort_id`
        scoping column, and hold at least one row for this cohort. Any unmet gate raises
        `PurgePreconditionError` naming every missing promotion, and the cohort file is left
        byte-for-byte as it was. Inspecting Tier D opens it: on a store whose Tier D never
        existed this creates the empty, migrated file and then refuses — nothing of the
        cohort's is touched either way.

        What purge deletes is the **content** of Tiers C and R — every row of every table in
        the cohort file — inside one transaction with foreign keys deferred to the commit,
        followed by a `VACUUM` and a truncate checkpoint. The vacuum is why a sentinel
        embedded in a submission is gone from the file's raw bytes afterward: a `DELETE`
        alone leaves text recoverable in freed pages, which is the reason the requirement
        names `VACUUM` — and the checkpoint is why it is gone from the `-wal` too, where the
        freed pages would otherwise sit until the last connection closed. The file itself
        remains, empty and migrated — and `schema_version` survives with it, because wiping
        it would make the next open re-run migration 001 against the surviving tables and
        leave the file permanently unopenable.

        Around the caller:

        - The cached cohort handle is **closed and evicted first**. Its queued writes are
          flushed (a flush failure aborts the purge before anything is deleted — rows that
          could not commit would otherwise land in the emptied file), Windows file locks are
          released, and no queued write can repopulate the tables after the delete. A handle
          a caller still holds past this point fails with a raw `sqlite3.ProgrammingError` —
          declared here rather than discovered there.
        - Blobs **are** reclaimed (#225): the cohort's hash-shaped references are read
          inside the transaction, and after the commit every hash no other database in
          the data directory still holds is unlinked from the content-addressed store —
          a blob shared with a surviving cohort keeps resolving (test plan §7.4's
          dedup-vs-purge tension resolves in favor of the survivor), and a blob
          referenced by nothing loses its student bytes. The count is
          `PurgeReport.blobs_deleted`.
        - On a read-only store this raises `ReadOnlyTierError` — a purge is a write by any
          definition that matters.

        A purge that fails partway (say, `VACUUM` cannot get its temp copy) has already
        committed its deletes; re-running it completes the vacuum — the tables are empty and
        the preconditions still hold. One asymmetry #225 makes explicit: if the **blob**
        phase fails after the commit, re-running cannot finish it — the rows that named the
        cohort's hashes are gone, so the error names the hash it stopped on and the
        leftover blob is unreferenced orphan. The scan-before-any-unlink discipline keeps
        that window as small as a post-commit phase can be.
        """
        cohort_id = _validated_component("cohort id", cohort_id)
        if self._read_only:
            raise ReadOnlyTierError(
                f"purge_cohort was called on a read-only store for cohort {cohort_id!r}. A "
                "purge is a write by any definition that matters — it is the one operation "
                "that deletes student work — and FR-STORE-13's read-only entry exists to "
                "inspect without touching."
            )
        missing = self._purge_precondition_failures(cohort_id)
        if missing:
            raise PurgePreconditionError(
                f"cohort {cohort_id!r} is not promoted to Tier D (FR-STORE-07, CT-STORE-10); "
                f"nothing was deleted. Unmet gates: {'; '.join(missing)}. Promotion is "
                f"M-STATS/M-REVIEW's promote; the gates check Tier D's audit_record, label "
                f"and criterion_stats tables, scoped by cohort_id."
            )

        path = self.cohort_path(cohort_id)
        # Close **before** evicting: if the close raises (a recorded batch failure
        # re-raised by queue.close()), the handle stays cached and reachable — for
        # `store.close()`'s cleanup and for the caller — instead of becoming an unreachable
        # object holding open connections on the very file a retry will need to delete.
        handle = self._handles.get((Tier.COHORT, cohort_id, False))
        if handle is not None:
            handle._close()  # noqa: SLF001 -- flush queued writes; a failure propagates — nothing deleted
            self._handles.pop((Tier.COHORT, cohort_id, False), None)

        rows: dict[str, int] = {}
        vacuum_ms = 0.0
        bytes_before = path.stat().st_size if path.exists() else 0
        bytes_after = bytes_before
        tables_cleared: tuple[str, ...] = ()
        blob_hashes: set[str] = set()
        if path.exists():
            connection = _connect(
                path, read_only=False, busy_timeout_ms=self._busy_timeout_ms,
                retries=self._retries,
            )
            try:
                try:
                    # Before the BEGIN, deliberately: SQLite makes `defer_foreign_keys` a
                    # no-op inside a transaction, and it resets at the end of the next one
                    # — this is exactly the shape it exists for.
                    _run(connection, _PRAGMA_DEFER_FOREIGN_KEYS, retries=self._retries)
                    _run(connection, _BEGIN, retries=self._retries)
                    found = {
                        str(row[0])
                        for row in _run(
                            connection, _SELECT_COHORT_TABLES, retries=self._retries
                        ).fetchall()
                    }
                    # Triggers and views are refused, not swept: an AFTER DELETE trigger
                    # would fire on this very sweep's DELETEs and repopulate tables the
                    # report is about to claim cleared — student text surviving a
                    # "successful" purge. Views are refused for the same fail-closed
                    # reason. The one carve-out is the pure refusal trigger (see
                    # `_is_pure_refusal_trigger`): a BEFORE UPDATE or BEFORE INSERT
                    # trigger whose body is a single RAISE never fires on the sweep's
                    # DELETEs and cannot write a row, so it cannot repopulate anything —
                    # #103's append-only content lock and #355's selection biconditional
                    # (FR-INGEST-37, which needs both directions) ride exactly this shape. (Indexes stay: they are
                    # SQLite-managed structure, emptied with their tables, and a
                    # legitimate performance object.)
                    objects = _run(
                        connection, _SELECT_COHORT_TRIGGERS_VIEWS, retries=self._retries
                    ).fetchall()
                    refused_objects = sorted(
                        (str(name), str(kind))
                        for name, kind, _sql in objects
                        if kind == "view" or not _is_pure_refusal_trigger(_sql)
                    )
                    if refused_objects:
                        raise ConfigurationProblem(
                            f"{path} declares trigger(s) or view(s) this purge refuses: "
                            f"{sorted(refused_objects)}. A trigger that fires on the "
                            "sweep's own DELETEs — or carries a write in its body — can "
                            "repopulate tables the report would claim cleared — student "
                            "text surviving a purge. Schema belongs to migrations "
                            "(NFR-STORE-04); the only coexisting shape is a "
                            "pure refusal trigger — one that fires BEFORE a row is written "
                            "or updated and whose body is a single RAISE "
                            "(`_is_pure_refusal_trigger`) — the shape #103's append-only "
                            "enforcement and #355's selection biconditional ride. Nothing "
                            "was removed."
                        )
                    unknown = sorted(
                        table for table in found
                        if not table.startswith("sqlite_")
                        and table != _SCHEMA_VERSION_TABLE_NAME
                        and table not in _PURGE_DELETES
                    )
                    if unknown:
                        # Fail closed, before the first DELETE: a table purge cannot name is
                        # student text it would leave behind. See the purge section's comment.
                        raise ConfigurationProblem(
                            f"{path} declares schema object(s) this purge does not "
                            f"recognize: {unknown}. FR-STORE-07 removes Tiers C and R "
                            "*content*, and a name the purge's registry lacks is student "
                            "text it would leave behind — purge refuses rather than "
                            "half-purge. A migration extending the cohort tier must extend "
                            "_PURGE_DELETES in the same change. Nothing was removed."
                        )
                    # #225: the order is asserted against the LIVE foreign-key graph of the
                    # file being purged, before the first DELETE — a migration that extends
                    # the cohort tier without extending _COHORT_PURGE_ORDER refuses here
                    # with the edge named instead of rotting into a raw IntegrityError at
                    # COMMIT. Deferred FKs would make a wrong order harmless only if the
                    # sweep were complete; this assertion is what pins completeness.
                    _assert_purge_order_matches_fk_graph(
                        connection, found, path, retries=self._retries)
                    # #225: the blob references are read while the rows still exist —
                    # after the COMMIT the cohort's hashes are unrecoverable from the file,
                    # and the reclamation phase after the vacuum runs on the set taken here.
                    blob_hashes = _collect_blob_hash_references(
                        connection, found & frozenset(_COHORT_PURGE_ORDER),
                        retries=self._retries)
                    # Only tables the file actually carries, in dependency order. A file at an
                    # older schema version than this process's registry — #57's `run` table,
                    # created by a migration registered when `aeh.orch` is imported, absent
                    # from a file last written at v6 — holds nothing in a table it does not
                    # have, so there is nothing to delete. The sweep above already refused
                    # everything `found` holds that the registry cannot name, so nothing
                    # cohort-scoped can survive this loop either way.
                    cleared: list[str] = []
                    for table in _COHORT_PURGE_ORDER:
                        if table not in found:
                            continue
                        cursor = _run(connection, _PURGE_DELETES[table], retries=self._retries)
                        count = cursor.rowcount
                        rows[table] = count if count is not None and count >= 0 else 0
                        cleared.append(table)
                    tables_cleared = tuple(cleared)
                    _run(connection, _COMMIT, retries=self._retries)
                except BaseException as error:
                    try:
                        _run(connection, _ROLLBACK, retries=self._retries)
                    except sqlite3.Error:
                        pass
                    # Disk-full at a DELETE or the COMMIT: classify and halt here too —
                    # FR-STORE-10 names no door exemption, and a raw OperationalError from
                    # a purge would look retryable to a caller on a disk that cannot
                    # recover until the run stops.
                    _halt_if_disk_full(error)
                    raise
                try:
                    started = time.perf_counter()
                    _run(connection, _VACUUM, retries=self._retries)
                    vacuum_ms = (time.perf_counter() - started) * 1000.0
                    # The vacuum's freed pages — with the student text in them — sit in the
                    # -wal until a checkpoint reclaims them. Truncate it now, while this
                    # connection is open, rather than rely on close() being the last close.
                    _run(connection, _PRAGMA_WAL_CHECKPOINT_TRUNCATE, retries=self._retries)
                except BaseException as error:
                    _halt_if_disk_full(error)
                    raise
            finally:
                connection.close()
                # The dedicated connection recreated the -wal/-shm siblings under the
                # process umask; tighten all three again (no-op on Windows).
                _harden_files(path)
            bytes_after = path.stat().st_size

        # #225: blob reclamation, after the deletes are committed. The rows named the
        # cohort's hashes and are gone now, so the set taken inside the transaction is the
        # only record of them. Sharing is decided by evidence, not by a refcount table the
        # store does not have: every other database in the data directory is scanned for
        # the same hashes, and only a hash NO surviving database references is reclaimed.
        # The scan completes before the first unlink, so a scan failure deletes nothing.
        # A failure partway through the unlinks itself leaves the rows purged and the
        # surviving blobs orphaned — the error names the hash it stopped on, and the
        # honest-refusal shape cannot cover a phase that runs post-commit by necessity
        # (the hashes die with the rows).
        blobs_deleted = 0
        if blob_hashes:
            referenced_elsewhere = self._blob_hashes_referenced_elsewhere(path)
            for content_hash in sorted(blob_hashes - referenced_elsewhere):
                if self.blobs().delete(content_hash):
                    blobs_deleted += 1

        self._last_vacuum_ms = vacuum_ms
        return PurgeReport(
            cohort_id=cohort_id,
            preconditions_verified=tuple(name for name, _table in _PURGE_PRECONDITIONS),
            tables_cleared=tables_cleared,
            rows_deleted_by_table=rows,
            file_bytes_before=bytes_before,
            file_bytes_after=bytes_after,
            vacuum_duration_ms=vacuum_ms,
            blobs_deleted=blobs_deleted,
        )

    def _blob_hashes_referenced_elsewhere(self, purged_path: Path) -> set[str]:
        """Hash-shaped values any OTHER database in the data directory still holds (#225).

        The blob directory is shared across the whole data directory — the other cohort
        files, the package tier and Tier D — so "shared blob" means referenced from any
        file but the one being purged. The package tier is scanned, not assumed
        irrelevant: an import re-puts the archive's exemplar blobs into this store and the
        package file's exemplar rows reference the hashes. Other cohort files share this
        module's schema and go through the declared scans; package and durable files carry
        foreign schemas (`M-STORE` owns no schema meaning) and go through the dump walk.
        Read-only, one pass per file. The scan runs to completion before any blob is
        deleted: an exception here propagates and the reclamation phase is skipped whole,
        leaving the purge's committed deletes and every blob intact — the conservative
        direction, and the documented re-run shape covers it.
        """
        referenced: set[str] = set()
        others = sorted(self._data_dir.glob("cohorts/*.sqlite"))
        others += sorted(self._data_dir.glob("packages/*.sqlite"))
        durable_path = self.durable_path()
        if durable_path.exists():
            others.append(durable_path)
        cohort_dir = self._data_dir / "cohorts"
        for other in others:
            if other == purged_path:
                continue
            connection = _connect(
                other, read_only=True, busy_timeout_ms=self._busy_timeout_ms,
                retries=self._retries,
            )
            try:
                if other.parent == cohort_dir:
                    tables = {
                        str(row[0]) for row in _run(
                            connection, _SELECT_COHORT_TABLES, retries=self._retries
                        ).fetchall()
                        if not str(row[0]).startswith("sqlite_")
                        and str(row[0]) != _SCHEMA_VERSION_TABLE_NAME
                    }
                    unknown = sorted(
                        table for table in tables if table not in _PURGE_BLOB_HASH_SCANS
                    )
                    if unknown:
                        # Fail closed: a cohort file at a schema this process does not
                        # know cannot be checked for references, and a purge that cannot
                        # check must not delete. The rows are already committed; the
                        # documented re-run shape applies once the file is at a known
                        # schema.
                        raise ConfigurationProblem(
                            f"{other} carries cohort-scoped name(s) this process's "
                            f"registry lacks: {unknown}. Blob references in it cannot "
                            f"be checked, so the reclamation for {purged_path.name} "
                            f"was skipped rather than risk deleting a shared blob. "
                            f"Nothing further is reclaimed on this call."
                        )
                    referenced |= _collect_blob_hash_references(
                        connection, tables, retries=self._retries)
                else:
                    # Package files and Tier D: foreign schemas, walked by the stdlib dump.
                    referenced |= _collect_blob_hash_references_from_dump(connection)
            finally:
                connection.close()
        return referenced

    def _purge_precondition_failures(self, cohort_id: str) -> list[str]:
        """The unmet Tier D promotion gates for `cohort_id`; empty when purge may run.

        A gate (`CT-STORE-10`'s three, in its words) passes iff Tier D holds the table, the
        table carries the `cohort_id` scoping column, and the table holds a row for this
        cohort. Fail-**closed** on all three: a table that does not exist or does not carry
        the column is one promotion structurally cannot have written — #10's minimal Tier D
        columns carry no cohort scope, so the scoping column arrives only when the owning
        module's migration adds it, which is what "promoted" means here. Anything weaker —
        nonempty tables regardless of cohort, say — would let one cohort's promotion unlock
        purging another, and `CT-STORE-10`'s sweep is per-precondition for exactly that
        reason.
        """
        durable = self.durable()
        missing: list[str] = []
        for name, table in _PURGE_PRECONDITIONS:
            columns = {str(row[1]) for row in durable.query(_PURGE_TABLE_INFO[table])}
            if "cohort_id" not in columns:
                missing.append(
                    f"{name} — Tier D's {table!r} does not carry the cohort_id scoping column"
                )
                continue
            count = durable.query(_PURGE_PROMOTED_ROWS[table], cohort_id=cohort_id)[0][0]
            if not count:
                missing.append(f"{name} — no {table} rows for cohort {cohort_id!r} in Tier D")
        return missing

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

    The location is checked **before the first directory is created** (`FR-STORE-09`): a data
    directory that resolves inside a world-writable path raises `InsecureLocationError` and
    creates nothing. The directories are then created and explicitly hardened to
    `OWNER_ONLY_DIR` — `mkdir`'s mode argument is filtered through the umask, so the `chmod`
    is the part that actually holds on POSIX (no-op on Windows; see `_harden_dir`).

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
    # The refusal resolves symlinks itself (`realpath`), so a data directory that is a
    # symlink pointing into /tmp is judged by where it lands. Running it before the mkdir
    # loop is what makes "refuses to start, nothing created" a property of the control flow.
    _refuse_insecure_location(root)
    for child in (root, root / "packages", root / "cohorts", root / "blobs"):
        child.mkdir(parents=True, exist_ok=True, mode=OWNER_ONLY_DIR)
        _harden_dir(child)

    return SqliteStore(
        root, limits=StoreLimits.from_environment(environ), read_only=read_only
    )


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
    performs is `purge_cohort`'s, and the store records the last measured duration — so the
    signal is a real measurement of the last purge, not an invention, and zero means "no
    purge has run in this process".
    """
    depth = 0
    latency_ms = 0.0
    failures = 0
    lock_waits = 0
    backpressure = False
    sustained = False
    sizes: dict[str, int] = {}

    for (tier, key, _read_only), handle in store._handles.items():  # noqa: SLF001
        share = handle._metrics  # noqa: SLF001 -- observability reads the private accessor
        depth += int(share["write_queue_depth"])
        latency_ms = max(latency_ms, float(share["batch_commit_latency_ms"]))
        failures += int(share["write_failures"])
        lock_waits += int(share.get("lock_waits", 0))
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
        "vacuum_duration_ms": float(store._last_vacuum_ms),  # noqa: SLF001 -- module-internal
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
        # -- SQLITE_BUSY retries slept through, per handle summed (#118's export-seam figure) --
        # Zero is the only healthy value under WAL's single-writer design; the figure exists so
        # a run that *did* wait says so rather than silently slowing down.
        "lock_waits": lock_waits,
    }
