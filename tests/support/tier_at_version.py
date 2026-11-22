"""A tier database standing at an earlier schema version, built by hand (Validity T7, #900).

Generalises the builder `tests/integration/pkg/test_tc_pkg_31_evaluation_mode_migration.py` and
`tests/support/run_scoped.py` each carry for one version: the tier's own declared migrations,
up to and including `at_version`, applied into a raw SQLite connection the store never touches,
with the version rows stamped. The result is what an older binary left on disk. Opening a real
store over it then runs exactly the migrations above `at_version` — the upgrade under test.

Built rather than committed, for the reason TC-PKG-31 gives: opening a store to build the file
would build it at the binary's head, the one state an upgrade case must not start from.

The caller imports the eleven chain contributors first (CLAUDE.md), or `TIER_MIGRATIONS` is
truncated and the builder applies a short chain.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

from aeh.store import TIER_MIGRATIONS, Tier, _SCHEMA_VERSION_TABLE

STAMP = "2026-01-01T00:00:00Z"


def tier_path(data_dir: Path, tier: Tier, key: str = "") -> Path:
    """Where the store looks for the tier's file under `data_dir`."""
    data_dir = Path(data_dir)
    if tier is Tier.PACKAGE:
        return data_dir / "packages" / f"{key}.pkg.sqlite"
    if tier is Tier.COHORT:
        return data_dir / "cohorts" / f"{key}.sqlite"
    return data_dir / "durable.sqlite"


def insert_row(connection: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
    """Insert by column name, filling any NOT NULL column without a default the spec leaves
    out (`run_scoped._insert`, transcribed), so an additive column a later migration brings
    does not break a seed."""
    info = connection.execute(f"PRAGMA table_info({table})").fetchall()
    row = dict(values)
    for _cid, name, col_type, not_null, default, _pk in info:
        if name in row or not not_null or default is not None:
            continue
        numeric = "INT" in (col_type or "").upper() or "REAL" in (col_type or "").upper()
        row[name] = 0 if numeric else f"fixture-{name}"
    columns = ", ".join(f'"{c}"' for c in row)
    placeholders = ", ".join("?" for _ in row)
    connection.execute(
        f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})', tuple(row.values()))


def build_tier_at(
    path: Path,
    tier: Tier,
    at_version: int,
    seed: Callable[[sqlite3.Connection], None] | None = None,
) -> Path:
    """Build `path` at `tier`'s schema `at_version`, then let `seed` write the old binary's
    rows. Asserts the seeded file passes its own foreign keys: the builder runs with FKs off
    (SQLite's default), and a file the store's FK pragma would refuse is no state any binary
    wrote."""
    chain = [m for m in TIER_MIGRATIONS[tier] if m.version <= at_version]
    assert chain and chain[-1].version == at_version, (
        f"the {tier.value} chain has no migration {at_version}: "
        f"{[m.version for m in TIER_MIGRATIONS[tier]]}"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(str(_SCHEMA_VERSION_TABLE))
        for migration in chain:
            for statement in migration.statements:
                connection.execute(str(statement))
            connection.execute(
                "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, STAMP),
            )
        if seed is not None:
            seed(connection)
        connection.commit()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        assert not violations, f"the {tier.value} fixture violates its foreign keys: {violations}"
    finally:
        connection.close()
    return path


def schema_version(path: Path) -> int:
    """The highest version stamped in the file."""
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute("SELECT MAX(version) FROM schema_version").fetchone()[0])
    finally:
        connection.close()


def columns(path: Path, table: str) -> dict[str, tuple]:
    """`PRAGMA table_info` by column name: `(type, notnull, default, pk)`."""
    connection = sqlite3.connect(path)
    try:
        return {str(row[1]): (row[2], row[3], row[4], row[5])
                for row in connection.execute(f"PRAGMA table_info({table})")}
    finally:
        connection.close()


def primary_key(path: Path, table: str) -> tuple[str, ...]:
    """The table's primary-key columns, in key order."""
    info = columns(path, table)
    return tuple(name for name, (_t, _n, _d, pk) in
                 sorted(info.items(), key=lambda item: item[1][3]) if pk)


def rows(path: Path, sql: str, *params: Any) -> list[dict[str, Any]]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()


def try_insert(path: Path, table: str, values: dict[str, Any]) -> sqlite3.IntegrityError | None:
    """Insert one row in its own connection; the IntegrityError if refused, else None."""
    connection = sqlite3.connect(path)
    try:
        try:
            insert_row(connection, table, values)
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            return error
        return None
    finally:
        connection.close()


__all__ = [
    "STAMP",
    "build_tier_at",
    "columns",
    "insert_row",
    "primary_key",
    "rows",
    "schema_version",
    "tier_path",
    "try_insert",
]
