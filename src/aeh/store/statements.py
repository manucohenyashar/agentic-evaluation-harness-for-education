"""The shared `STATEMENTS` registry: one SQL text per statement name."""

from __future__ import annotations

import sys
from typing import Any, Mapping

from .errors import StatementConflictError
from .interfaces import Statement
from .migrations import _SCHEMA_VERSION_TABLE, TIER_MIGRATIONS
from .purge import (
    _PRAGMA_DEFER_FOREIGN_KEYS,
    _PRAGMA_WAL_CHECKPOINT_TRUNCATE,
    _PURGE_DELETES,
    _PURGE_PROMOTED_ROWS,
    _PURGE_TABLE_INFO,
    _SELECT_COHORT_TABLES,
    _SELECT_COHORT_TRIGGERS_VIEWS,
    _VACUUM,
)
from .connection import (
    _BEGIN,
    _COMMIT,
    _INSERT_VERSION,
    _PRAGMA_FOREIGN_KEYS,
    _PRAGMA_FOREIGN_KEYS_ON,
    _PRAGMA_JOURNAL_MODE,
    _PRAGMA_JOURNAL_WAL,
    _ROLLBACK,
    _SELECT_APPLIED_VERSIONS,
    _SELECT_SCHEMA_VERSION_TABLE,
)


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
    ON CONFLICT(id) DO UPDATE SET
        ticks      = MAX(excluded.ticks, store_lease_clock.ticks),
        wall_clock = excluded.wall_clock
    """
)


def _owning_module(name: str) -> str:
    """The module a registration is attributed to: `aeh.det.schema` registers for `aeh.det`."""
    parts = name.split(".")
    return ".".join(parts[:2]) if parts[0] == "aeh" else name


class _StatementRegistry(dict):
    """The shared `STATEMENTS` registry: one SQL text per name (FR-STORE-16, ADR-32).

    `aeh.det`, `aeh.grade`, `aeh.ingest` and `aeh.pkg` merge their statements into this one
    dictionary at import. Before #511 a name two of them declared differently resolved to
    whichever module imported last (TC-REG-07 was one such crash). A registration that reuses
    a name with different SQL now raises `StatementConflictError` and changes nothing; a
    byte-identical re-registration is allowed, so importing twice is harmless."""

    def __init__(self, entries: Mapping[str, Statement], owner: str) -> None:
        super().__init__(entries)
        self._owners = dict.fromkeys(entries, owner)

    @staticmethod
    def _registering_module() -> str:
        # Frame 0 is this helper, 1 the registry method, 2 the registering code.
        return _owning_module(str(sys._getframe(2).f_globals.get("__name__", "<unknown>")))

    def _admit(self, entries: Mapping[str, Statement], owner: str) -> None:
        for name, statement in entries.items():
            if name in self and str(self[name]) != str(statement):
                raise StatementConflictError(
                    f"statement {name!r} is already registered by {self._owners.get(name)} "
                    f"with different SQL; {owner} must register its statement under a "
                    "different name (FR-STORE-16: one SQL text per statement name)")
        for name, statement in entries.items():
            dict.__setitem__(self, name, statement)
            self._owners.setdefault(name, owner)

    def __setitem__(self, name: str, statement: Statement) -> None:
        self._admit({name: statement}, self._registering_module())

    def update(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        self._admit(dict(*args, **kwargs), self._registering_module())

    def setdefault(self, name: str, statement: Statement) -> Statement:  # type: ignore[override]
        # A conflicting setdefault is a conflicting registration too: returning the other
        # module's SQL silently would be the same defect with the first writer winning.
        self._admit({name: statement}, self._registering_module())
        return self[name]

    def __ior__(self, other: Any) -> "_StatementRegistry":  # type: ignore[override]
        self._admit(dict(other), self._registering_module())
        return self


STATEMENTS: Mapping[str, Statement] = _StatementRegistry({
    # -- schema-version bookkeeping (the migration machinery) ---------------------------------
    "create_schema_version_table": _SCHEMA_VERSION_TABLE,
    "select_applied_versions": _SELECT_APPLIED_VERSIONS,
    "select_schema_version_table": _SELECT_SCHEMA_VERSION_TABLE,
    "insert_version": _INSERT_VERSION,
    # -- connection pragmas and transaction control -------------------------------------------
    "pragma_foreign_keys_on": _PRAGMA_FOREIGN_KEYS_ON,
    "pragma_foreign_keys": _PRAGMA_FOREIGN_KEYS,
    "pragma_journal_wal": _PRAGMA_JOURNAL_WAL,
    "pragma_journal_mode": _PRAGMA_JOURNAL_MODE,
    "pragma_defer_foreign_keys": _PRAGMA_DEFER_FOREIGN_KEYS,
    "begin": _BEGIN,
    "commit": _COMMIT,
    "rollback": _ROLLBACK,
    # -- purge (FR-STORE-07) --------------------------------------------------------------------
    "select_cohort_tables": _SELECT_COHORT_TABLES,
    "select_cohort_triggers_views": _SELECT_COHORT_TRIGGERS_VIEWS,
    "vacuum": _VACUUM,
    "wal_checkpoint_truncate": _PRAGMA_WAL_CHECKPOINT_TRUNCATE,
    "table_info_audit_record": _PURGE_TABLE_INFO["audit_record"],
    "table_info_label": _PURGE_TABLE_INFO["label"],
    "table_info_criterion_stats": _PURGE_TABLE_INFO["criterion_stats"],
    "count_promoted_audit_records": _PURGE_PROMOTED_ROWS["audit_record"],
    "count_promoted_labels": _PURGE_PROMOTED_ROWS["label"],
    "count_promoted_criterion_stats": _PURGE_PROMOTED_ROWS["criterion_stats"],
    "purge_delete_review_queue": _PURGE_DELETES["review_queue"],
    "purge_delete_narrative": _PURGE_DELETES["narrative"],
    "purge_delete_submission_grade": _PURGE_DELETES["submission_grade"],
    "purge_delete_criterion_score": _PURGE_DELETES["criterion_score"],
    "purge_delete_verdict": _PURGE_DELETES["verdict"],
    "purge_delete_evidence": _PURGE_DELETES["evidence"],
    "purge_delete_work_unit": _PURGE_DELETES["work_unit"],
    "purge_delete_document_region": _PURGE_DELETES["document_region"],
    "purge_delete_document": _PURGE_DELETES["document"],
    "purge_delete_submission": _PURGE_DELETES["submission"],
    "purge_delete_roster": _PURGE_DELETES["roster"],
    "purge_delete_cohort": _PURGE_DELETES["cohort"],
    # -- the lease clock (FR-STORE-11, #12) ------------------------------------------------------
    "select_lease_clock": _SELECT_LEASE_CLOCK,
    "upsert_lease_clock": _UPSERT_LEASE_CLOCK,
    # -- migration DDL, included deliberately ----------------------------------------------------
    # `TC-STORE-15`'s sweep is over what the module can *issue*, and a `CREATE VIRTUAL TABLE
    # ... USING fts5` hidden in a migration is precisely the full-text index the schema limb
    # exists to catch — reachable through no method anybody would call `search`. Keyed by
    # tier, version and position so a registry entry names the migration it came from.
    **{
        f"migrate_{tier.value}_{migration.version:03d}_{index:02d}": statement
        for tier, migrations in TIER_MIGRATIONS.items()
        for migration in migrations
        for index, statement in enumerate(migration.statements)
    },
}, owner=_owning_module(__name__))
