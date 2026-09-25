"""`TS-92` (issue #386) — `TC-PKG-31`: `criterion.evaluation_mode` arrives by migration with
the old reading preserved, and the column's domain is enforced (`FR-PKG-22`, `CT-PKG-19`,
RISK-57).

| Input | Expected |
|---|---|
| an F-SCHEMA Package v10 DB holding an `mcq` and an `open` criterion | after migration: `mcq` → `deterministic`, `open` → `judged` |
| `INSERT` with `evaluation_mode='llm'` | fails the CHECK |
| `INSERT` with `evaluation_mode=NULL` | fails NOT NULL |
| a revision child, and an export → import round trip | both carry identical values |

**The migration is two statements and the order is the point.** The `ALTER` gives every
existing row `judged`; the `UPDATE` then restores the reading the retired predicate had
(`kind = 'mcq'` meant deterministic). Run the other way round, every MCQ criterion would be
`judged` for the width of one migration. Nobody observes that window — but the order is still
the one that is correct on its own, and a migration whose correctness depends on nobody
looking is a migration that will eventually be interrupted.

**Why the backfill matters more than it looks.** RISK-57: a version that loses
`evaluation_mode` defaults to `judged`, so MCQ items go to judges — extra model spend on every
run against that version, and a judged score where an answer key exists. The failure is
invisible: the run completes and the grades look plausible. The backfill is what keeps every
package that predates the column reading the way it always did.

**The two refusals are different mechanisms and both are asserted.** `'llm'` is a value outside
the closed vocabulary and is caught by the CHECK; `NULL` is caught by NOT NULL. An
implementation carrying only one of them admits the other, and a NULL here is the shape
`_declared_evaluation_mode` would have to guess about.

**The revision and round-trip arms are where the column silently disappears.** A copy that
enumerates columns by hand — which both `create_version(parent)` and the export path must —
drops a new column without failing anything, and the child then reads `judged` for an MCQ
criterion. That is RISK-57 arriving by a different door.

**Isolation: rung 2** — a raw SQLite file built at Package v10 exactly as the pre-delta binary
left it, then migrated by opening a real store. Built rather than committed, following
`tests/support/run_scoped.py`'s precedent: opening a store to build it would build at whatever
head the binary has, which is the one state this case must not start from.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.pkg import EVALUATION_MODES, PackageCatalog
from aeh.store import TIER_MIGRATIONS, Tier, _SCHEMA_VERSION_TABLE, open_store

pytestmark = pytest.mark.integration

#: The Package-tier version immediately before `pkg_criterion_evaluation_mode` (11).
PRE_DELTA_PACKAGE_VERSION = 10
STAMP = "2026-01-01T00:00:00Z"

PACKAGE_ID = "pkg-v10"
VERSION_ID = "pkg-v10@aaaaaaaaaaaa"
MCQ, OPEN = "C-mcq", "C-open"


def _insert(connection: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
    """Insert by column name, filling any NOT NULL column the spec leaves out.

    `tests/support/run_scoped.py`'s `_insert`, transcribed: a later pre-v10 additive column
    must not break the builder.
    """
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
        f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})', tuple(row.values())
    )


def _build_pre_delta_package(data_dir: Path) -> Path:
    """A Package DB standing at version 10, holding one `mcq` and one `open` criterion."""
    path = Path(data_dir) / "packages" / f"{PACKAGE_ID}.pkg.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(str(_SCHEMA_VERSION_TABLE))
        for migration in TIER_MIGRATIONS[Tier.PACKAGE]:
            if migration.version > PRE_DELTA_PACKAGE_VERSION:
                continue
            for statement in migration.statements:
                connection.execute(str(statement))
            connection.execute(
                "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, STAMP),
            )
        _insert(connection, "package", {"package_id": PACKAGE_ID, "created_at": STAMP})
        _insert(connection, "package_version", {
            "package_version_id": VERSION_ID, "package_id": PACKAGE_ID,
            "revision": 1, "locked": 0,
        })
        for criterion_id, kind in ((MCQ, "mcq"), (OPEN, "open")):
            _insert(connection, "criterion", {
                "package_version_id": VERSION_ID, "criterion_id": criterion_id,
                "kind": kind, "scoring_model": "atomic", "max_points": 1.0,
            })
        connection.commit()
    finally:
        connection.close()
    return path


def _modes(path: Path, version_id: str = VERSION_ID) -> dict[str, str]:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    try:
        return {
            str(row["criterion_id"]): str(row["evaluation_mode"])
            for row in connection.execute(
                "SELECT criterion_id, evaluation_mode FROM criterion "
                "WHERE package_version_id = ?",
                (version_id,),
            )
        }
    finally:
        connection.close()


@pytest.fixture
def migrated(tmp_data_dir):
    """The v10 database, migrated to head by opening a real store over it."""
    path = _build_pre_delta_package(tmp_data_dir)
    store = open_store(tmp_data_dir)
    try:
        handle = store.package(PACKAGE_ID)
        yield tmp_data_dir, path, store, handle
    finally:
        store.close()


# --- TC-PKG-31, the migration ------------------------------------------------------------------


def test_tc_pkg_31_the_migration_preserves_the_retired_reading(migrated):
    """`mcq` → `deterministic`, `open` → `judged`.

    Both, because the `ALTER`'s default gives every row `judged` — so the `open` criterion is
    right whether or not the backfill ran, and only the `mcq` one tells you it did.
    """
    _dir, path, _store, _handle = migrated

    modes = _modes(path)

    assert modes == {MCQ: "deterministic", OPEN: "judged"}, (
        f"after migration the modes are {modes}. The ALTER defaults every row to 'judged' "
        "and the UPDATE restores the retired `kind = 'mcq'` reading; an mcq criterion left "
        "judged sends MCQ items to a panel on every run against this version (RISK-57)"
    )


def test_tc_pkg_31_the_pre_migration_database_had_no_such_column(tmp_data_dir):
    """The fixture's own precondition: at v10 the column does not exist.

    Without this the migration assertion above could pass against a builder that had quietly
    created the column itself, and the case would be testing nothing.
    """
    path = _build_pre_delta_package(tmp_data_dir)
    connection = sqlite3.connect(str(path))
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(criterion)")
        }
    finally:
        connection.close()

    assert "evaluation_mode" not in columns, (
        f"the v10 fixture already carries evaluation_mode: {sorted(columns)}"
    )


# --- TC-PKG-31, the column's domain ------------------------------------------------------------


def test_tc_pkg_31_a_value_outside_the_vocabulary_fails_the_check(migrated):
    """`evaluation_mode='llm'` is refused by the CHECK."""
    _dir, path, _store, _handle = migrated
    assert "llm" not in EVALUATION_MODES

    connection = sqlite3.connect(str(path))
    try:
        with pytest.raises(sqlite3.IntegrityError) as caught:
            _insert(connection, "criterion", {
                "package_version_id": VERSION_ID, "criterion_id": "C-bad",
                "kind": "open", "scoring_model": "atomic", "max_points": 1.0,
                "evaluation_mode": "llm",
            })
        assert "CHECK" in str(caught.value).upper() or "constraint" in str(caught.value)
    finally:
        connection.close()

    assert "C-bad" not in _modes(path), "the refused row was written"


def test_tc_pkg_31_a_null_mode_fails_not_null(migrated):
    """`evaluation_mode=NULL` is refused by NOT NULL.

    A different mechanism from the CHECK, and both are needed: an implementation carrying only
    one admits the other, and a NULL is the shape every consumer's `_declared_evaluation_mode`
    would then have to guess about.
    """
    _dir, path, _store, _handle = migrated

    connection = sqlite3.connect(str(path))
    try:
        with pytest.raises(sqlite3.IntegrityError) as caught:
            connection.execute(
                "INSERT INTO criterion (package_version_id, criterion_id, kind, "
                "scoring_model, max_points, evaluation_mode) VALUES (?, ?, ?, ?, ?, NULL)",
                (VERSION_ID, "C-null", "open", "atomic", 1.0),
            )
        assert "NOT NULL" in str(caught.value).upper()
    finally:
        connection.close()


# --- TC-PKG-31, the two copying paths ----------------------------------------------------------


def test_tc_pkg_31_a_revision_child_carries_the_same_modes(migrated):
    """`create_version(parent)` copies `evaluation_mode` for every criterion.

    The door RISK-57 comes through when the migration is right. A copy that enumerates columns
    by hand drops a new one without failing anything, and the child then reads `judged` for the
    MCQ criterion — a package whose parent was correct and whose revision is not.
    """
    _dir, path, _store, handle = migrated
    catalog = PackageCatalog(handle, package_id=PACKAGE_ID)

    child = catalog.create_version(VERSION_ID)

    parent_modes = _modes(path)
    child_modes = _modes(path, child)
    assert child_modes, f"the revision child declares no criteria: {child_modes}"
    assert child_modes == parent_modes, (
        f"the child's modes {child_modes} differ from the parent's {parent_modes}. A revision "
        "that loses evaluation_mode sends the MCQ criterion to a judge panel (RISK-57)"
    )


def test_tc_pkg_31_the_modes_survive_an_export_and_import(migrated, tmp_path):
    """The exported archive, imported into a fresh store, carries identical modes.

    The second copying path, and the one that crosses a process boundary — where a column that
    was never serialised is indistinguishable from one serialised as its default. `export`
    snapshots the whole Tier P database rather than enumerating columns, which is what makes
    the archive carry a column nobody remembered; asserting it keeps that property true if the
    export is ever rewritten as a per-column copy.
    """
    _dir, path, _store, handle = migrated
    catalog = PackageCatalog(handle, package_id=PACKAGE_ID)
    archive = tmp_path / "exported.aehpkg"

    catalog.export(VERSION_ID, archive)
    assert archive.exists(), "the export produced no archive"

    target_dir = tmp_path / "imported"
    target = open_store(target_dir)
    try:
        # Hosted on a DIFFERENT package handle: `import_file` writes
        # `<packages>/<archive's package id>.pkg.sqlite` and refuses when that file already
        # exists — and opening `target.package(PACKAGE_ID)` would create exactly it.
        PackageCatalog(
            target.package("pkg-importer"), package_id="pkg-importer"
        ).import_file(archive)
    finally:
        target.close()

    imported_path = target_dir / "packages" / f"{PACKAGE_ID}.pkg.sqlite"
    assert imported_path.exists(), (
        f"the import wrote no package database: {sorted(target_dir.rglob('*'))}"
    )
    round_tripped = _modes(imported_path)
    assert round_tripped == _modes(path), (
        f"the imported version's modes {round_tripped} differ from the source's "
        f"{_modes(path)}. A mode lost across an export is RISK-57 arriving on a machine that "
        "never ran the migration"
    )
