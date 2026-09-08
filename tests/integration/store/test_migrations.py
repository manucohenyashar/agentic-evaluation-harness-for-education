"""Every prior schema version migrates to current, and too-new refuses untouched.

Cases `TC-STORE-04`, `TC-STORE-05`, `TC-STORE-06` (`FR-STORE-02`, `NFR-STORE-04`), test plan
§5.3. Issue #16 (TS-10).

Rung 2 — real SQLite files, because a migration that corrupts data corrupts *files*, and a
fixture built through the store's own migration machinery asserts the machinery against
itself. The fixtures are **generated, not committed** (`F-SCHEMA` is "synthetic, grown as
versions ship", test plan §4.x): the builder applies the tier's migrations 1..N by hand to a
raw database, seeds deterministic rows, and stamps `schema_version` — exactly the state a
database written by binary version N is in. `TC-STORE-04`'s oracle is a **golden file** of
post-migration checksums (`fixtures/F-SCHEMA/post-migration-checksums.json`, planted by this
PR and grown with each version): a migration that silently reshapes data fails the golden
before it fails a user.

`Written ahead of implementation: yes` is stale — migrations landed with #10; the case runs
green by design.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import time
from pathlib import Path

import pytest

import aeh.pkg  # noqa: F401 -- imports the owning module so Tier P's registry is complete
import aeh.ingest  # noqa: F401 -- imports the owning module so the cohort tier's registry is complete
import aeh.orch  # noqa: F401 -- the cohort tier's latest owner; imported last so the
# registry reads [1, 2..6 ingest, 7 orch] in version order, which TC-STORE-04's
# registry-filtered expectation walks. The store sorts by version when applying, so
# runtime is order-independent either way; this keeps the test's walk honest.
from aeh.store import (
    TIER_MIGRATIONS,
    Tier,
    _SCHEMA_VERSION_TABLE,
    current_schema_version,
    open_store,
)
from tests.support.store_api import statement

pytestmark = [pytest.mark.integration]

ISSUE = "#16"

GOLDEN = Path(__file__).resolve().parents[3] / "fixtures" / "F-SCHEMA" / "post-migration-checksums.json"

#: Deterministic rows, per table: the fixture data every version's database carries. Values
#: respect the migration-001 constraints; a later migration that adds columns must extend
#: this map in the same change it extends `_DURABLE_001`-style DDL, or TC-STORE-04 reds —
#: which is the golden doing its job.
FIXTURE_ROWS: dict[Tier, dict[str, list[tuple]]] = {
    Tier.PACKAGE: {
        "package": [("PKG-FIX", "2026-01-01T00:00:00Z")],
        # locked = 0: migration 002 installs the immutability triggers, and seeding
        # children of a LOCKED version would trip them — a fixture database standing at
        # version N is a work-in-progress draft, not a published version.
        "package_version": [("PV-FIX", "PKG-FIX", 1, 0)],
        # Column order matches the DDL: criterion(criterion_id, package_version_id, ...).
        # The first draft had it swapped — the builder's raw connection runs with FKs off,
        # so nothing caught it until the FK check below did (review, B2).
        "criterion": [
            ("CRIT-1", "PV-FIX", "Q-1", "open"),
            ("CRIT-2", "PV-FIX", "Q-2", "open"),
        ],
        "band": [("PV-FIX", "CRIT-1", 0, "b0", 0.0)],
        "criterion_dependency": [("PV-FIX", "CRIT-2", "CRIT-1")],
        "exemplar": [("EX-FIX", "PV-FIX", "CRIT-1", "b0")],
        "grade_policy": [("PV-FIX", '{"policy":"fixed"}')],
        "validation_record": [("VR-FIX", "PV-FIX", "bp-1", "panel-1", "2026-01-01T00:00:00Z")],
    },
    Tier.COHORT: {
        "cohort": [("C-FIX", "consented", "2026-01-01T00:00:00Z")],
        "roster": [("C-FIX", "ref-1")],
        "submission": [("S-FIX", "C-FIX", "ref-1")],
        "document": [("D-FIX", "S-FIX", "hash-fix")],
        "document_region": [("R-FIX", "D-FIX", 1, "text")],
        "work_unit": [("W-FIX", "S-FIX", "judge", "done")],
        "evidence": [("E-FIX", "W-FIX", "D-FIX")],
        "verdict": [("V-FIX", "W-FIX", "judge-1", "b1")],
        "criterion_score": [("S-FIX", "CRIT-1", "b1")],
        "submission_grade": [("S-FIX", 0)],
        "narrative": [("N-FIX", "S-FIX", "CRIT-1")],
        "review_queue": [("Q-FIX", "S-FIX", "CRIT-1", "low-agreement")],
    },
    Tier.DURABLE: {
        "audit_record": [("AR-FIX", "run-1", "2026-01-01T00:00:00Z", '{"profile":"fixed"}')],
        "label": [("L-FIX", "run-1", "ref-1", "CRIT-1", "human", "b1")],
        "criterion_stats": [("PV-FIX", "CRIT-1", "bp-1", "panel-1", 5)],
        "mcq_item_stats": [("PV-FIX", "CRIT-1", "A", 3)],
        "mcq_item_summary": [("PV-FIX", "CRIT-1")],
        "run_metrics": [("run-1", "kappa", 0.5)],
    },
}

#: The fixture's deterministic stamps for `schema_version` itself. The table is excluded from
#: the checksum (its `applied_at` is inherently "now" once a *new* migration applies), but the
#: version rows it carries are asserted exactly.
FIXTURE_VERSION_STAMP = "2026-01-01T00:00:00Z"


def _fixture_database(db_path: Path, tier: Tier, at_version: int) -> None:
    """Build a database standing at schema version `at_version`, by hand.

    The migrations are applied through this module's own declared statements — the same SQL
    `_open_tier` would run — into a raw connection the store never touches, then the version
    rows are stamped. The result is what a database written by an older binary looks like:
    the store's DDL, the store's version bookkeeping, data the old binary put there."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        # The store's `_migrate` creates the version table inside the migration transaction,
        # not as part of any migration's statements — the fixture does the same.
        connection.execute(str(_SCHEMA_VERSION_TABLE))
        migrations = [m for m in TIER_MIGRATIONS[tier] if m.version <= at_version]
        for migration in migrations:
            for statement_text in migration.statements:
                connection.execute(str(statement_text))
            connection.execute(
                "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, FIXTURE_VERSION_STAMP),
            )
        for table, rows in FIXTURE_ROWS[tier].items():
            # The insert names its columns and takes the FIRST len(values) of the table's
            # declaration order: later additive migrations only append columns, so the
            # leading columns are exactly what migration 001 declared and what the
            # positional fixture rows describe — at every schema version.
            declared = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
            named = declared[: len(rows[0])]
            placeholders = ", ".join("?" for _ in rows[0])
            column_list = ", ".join(f'"{c}"' for c in named)
            connection.executemany(
                f'INSERT INTO "{table}" ({column_list}) VALUES ({placeholders})', rows)
        connection.commit()
        # The builder's connection runs with FKs off (SQLite's default), which is exactly
        # how a value-swapped row passed silently once: NOT NULL/CHECK/PK are enforced, FK
        # is not. Assert the fixture is what the store's own pragma would accept.
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        assert not violations, (
            f"the {tier.value} fixture violates its own foreign keys: {violations[:4]}. A "
            "database the store's FK pragma would refuse is not a state any binary could "
            "have written, and a migration judged against it is judged against corrupt data."
        )
    finally:
        connection.close()


def _checksum(db_path: Path, projection: dict[str, list[str]] | None = None) -> dict[str, dict]:
    """Per-table row counts and content checksums, over every user table.

    Rows are serialized in declaration-stable order (ordered by every column, repr-normalized
    for blob cells) and hashed — so the checksum moves if a migration rewrites, drops,
    reshapes or reorders data, and stays put if a migration only adds empty structure.
    `schema_version` is excluded: once a *new* migration applies, its `applied_at` is
    legitimately "now", and a checksum that moved on every migration would be noise.

    `projection` restricts each table's checksum to the named columns — the differential's
    tool for a column-ADDING migration, where comparing whole rows would flag the new
    column as changed data (TC-STORE-04's own advisory anticipated exactly this edit, and
    #26's Tier P lineage migration is the first column-adder)."""
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = sorted(
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
            if not row[0].startswith("sqlite_") and row[0] != "schema_version"
        )
        result: dict[str, dict] = {}
        for table in tables:
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
            selected = (
                [c for c in (projection or {}).get(table, columns) if c in columns]
                if projection else columns
            )
            order = ", ".join(f'"{c}"' for c in (selected or columns))
            rows = connection.execute(
                f'SELECT {order} FROM "{table}" ORDER BY {order}').fetchall()
            digest = hashlib.sha256()
            digest.update(repr(rows).encode())
            result[table] = {
                "rows": len(rows),
                "columns": columns,
                "checksum": digest.hexdigest(),
            }
        return result
    finally:
        connection.close()


def _tier_path(data_dir: Path, tier: Tier, key: str) -> Path:
    if tier is Tier.PACKAGE:
        return data_dir / "packages" / f"{key}.pkg.sqlite"
    if tier is Tier.COHORT:
        return data_dir / "cohorts" / f"{key}.sqlite"
    return data_dir / "durable.sqlite"


def test_tc_store_04_every_prior_version_migrates_to_current_without_data_loss(tmp_data_dir):
    """`TC-STORE-04` — *"Forward-only numbered migrations bring each prior schema version to
    current with no data loss; row counts and a content checksum preserved for every
    surviving table."*

    One fixture database per prior version, per tier (today that is exactly one — version 1
    is the only version and also the current one, so the loop below is written to grow as
    versions ship, and reds the day a migration diverges from the golden). The oracle is the
    **golden file** of post-migration checksums: `fixtures/F-SCHEMA/post-migration-
    checksums.json`, compared exactly. A migration that alters, drops or reshapes fixture
    data must update the golden in the same PR — a silent data change is the failure the
    golden exists to catch."""
    prior_versions = {
        tier: list(range(1, current_schema_version(tier) + 1)) for tier in Tier
    }
    golden = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else None
    report: dict[str, dict] = {}
    for tier in Tier:
        for version in prior_versions[tier]:
            key = f"fix-v{version}"
            data_dir = tmp_data_dir / f"{tier.value}-v{version}"
            data_dir.mkdir(parents=True)
            db_path = _tier_path(data_dir, tier, key)
            _fixture_database(db_path, tier, version)
            before = _checksum(db_path)

            if tier is Tier.PACKAGE:
                store = open_store(data_dir)
                handle = store.package(key)
            elif tier is Tier.COHORT:
                store = open_store(data_dir)
                handle = store.cohort(key)
            else:
                store = open_store(data_dir)
                handle = store.durable()
            opened = handle._open_report  # noqa: SLF001 -- the open report, privately read
            assert opened.schema_version_before == version
            assert opened.schema_version_after == current_schema_version(tier)
            assert opened.migrations_applied == tuple(
                m.version for m in TIER_MIGRATIONS[tier] if m.version > version
            ), (
                f"TC-STORE-04: {tier.value} v{version} applied {opened.migrations_applied}; "
                "pending is 'not in the applied set', in version order."
            )
            before_projection = {t: b["columns"] for t, b in before.items()}
            # Two reads with two jobs: the PROJECTED read feeds the before/after
            # differential (a column-adding migration changes the row shape, and
            # projecting onto the old columns separates "data changed" from "shape
            # changed"); the UNPROJECTED read is the post-migration state the golden
            # pins — the golden describes the world as the current schema holds it.
            after = _checksum(db_path, projection=before_projection)
            after_full = _checksum(db_path)
            # "preserved for every *surviving* table" (the plan's wording): a migration may
            # ADD tables (#12's store_lease_clock, #26's triggers) — the oracle is that
            # nothing vanishes and every surviving table's data is intact, compared over
            # the BEFORE-shape columns: a column-ADDING migration legitimately changes the
            # row shape, and projecting onto the old columns is what separates "data
            # changed" from "shape changed" — the differential's own stated tool, applied
            # now that #26's Tier P lineage migration is the first real column-adder.
            vanished = set(before) - set(after)
            assert not vanished, (
                f"TC-STORE-04: migrating {tier.value} v{version} dropped table(s) {sorted(vanished)}. "
                "Forward-only migrations add and reshape; they do not remove."
            )
            lost_rows = {
                t for t in before if before[t]["rows"] != after.get(t, {}).get("rows")
            }
            assert not lost_rows, (
                f"TC-STORE-04: migrating {tier.value} v{version} changed row counts in "
                f"{sorted(lost_rows)}. NFR-STORE-04: no data loss."
            )
            changed = {
                t for t in before if before[t]["checksum"] != after.get(t, {}).get("checksum")
            }
            assert not changed, (
                f"TC-STORE-04: migrating {tier.value} v{version} -> "
                f"{current_schema_version(tier)} changed data in {sorted(changed)}: "
                f"{ {t: (before[t], after[t]) for t in sorted(changed)} }. "
                "NFR-STORE-04: forward-only, no data loss. If the migration legitimately "
                "transforms data, the golden and FIXTURE_ROWS move with it — in the same PR."
            )
            store.close()
            report[f"{tier.value}@v{version}"] = after_full

    assert golden is not None, (
        "TC-STORE-04: fixtures/F-SCHEMA/post-migration-checksums.json is missing. The golden "
        "is the oracle; a suite that computes checksums and compares them to nothing asserts "
        "nothing. Regenerate it from this run's report and review the diff."
    )
    assert report == golden, (
        "TC-STORE-04: post-migration checksums differ from the golden. A migration changed "
        "data without updating fixtures/F-SCHEMA/post-migration-checksums.json — or the "
        "fixture rows drifted. Either way the diff is the review: golden updates are "
        "conscious decisions, not test noise."
    )


def test_tc_store_05_a_too_new_database_refuses_to_open_and_is_not_touched(tmp_data_dir):
    """`TC-STORE-05` — *"A database whose schema_version exceeds the binary's: SchemaTooNewError
    at open; the file is unmodified, asserted by mtime and content hash."*

    The immutability half is the clause's teeth (`CT-STORE-11`: "refuses to open, **no partial
    read**"): the store must not set WAL, must not migrate, must not so much as touch the
    bytes of a file it does not understand."""
    data_dir = tmp_data_dir / "durable"
    data_dir.mkdir(parents=True)
    db_path = _tier_path(data_dir, Tier.DURABLE, "")
    _fixture_database(db_path, Tier.DURABLE, 1)
    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        raw.execute("INSERT INTO schema_version (version, name, applied_at) VALUES (99, 'from-the-future', ?)",
                    (FIXTURE_VERSION_STAMP,))
        raw.commit()

    before_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    before_mtime = db_path.stat().st_mtime

    store = open_store(data_dir)
    with pytest.raises(Exception) as refused:
        store.durable()
    assert type(refused.value).__name__ == "SchemaTooNewError", (
        f"TC-STORE-05: refused with {type(refused.value).__name__} — CT-STORE-11's oracle is "
        "the exact type; degrading to a partial read of what the binary recognizes is the "
        "failure the clause names."
    )
    assert "99" in str(refused.value)

    assert db_path.stat().st_mtime == before_mtime, (
        "TC-STORE-05: the refused open moved the file's mtime. A refusal that touches the "
        "file breaks the provenance guarantee an inspection depends on."
    )
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before_hash, (
        "TC-STORE-05: the refused open changed the file's bytes — setting WAL rewrites the "
        "header, and a database the binary refuses must not be written in any way."
    )
    store.close()


def test_tc_store_06_no_migration_declares_a_reverse_step():
    """`TC-STORE-06` — *"Every migration is numbered and forward-only; no migration declares a
    reverse step, so the restore-from-a-copy policy is enforced rather than assumed."*

    Oracle: **artifact assertion** over the migration set itself. `Migration` carries version,
    name and statements — and nothing else: a `down`, `reverse` or `undo` field is the escape
    hatch NFR-STORE-04 exists to close, so its absence is asserted structurally (the
    dataclass's own field list), not by convention."""
    for tier in Tier:
        versions = [m.version for m in TIER_MIGRATIONS[tier]]
        assert versions == sorted(set(versions)), (
            f"TC-STORE-06: {tier.value}'s migration versions {versions} are not strictly "
            "increasing and unique. Numbered, forward-only — a duplicate or out-of-order "
            "version is an ambiguous history."
        )
        assert versions and versions[0] >= 1
        for migration in TIER_MIGRATIONS[tier]:
            fields = sorted(migration.__dataclass_fields__)
            assert fields == ["name", "statements", "version"], (
                f"TC-STORE-06: {tier.value} migration {migration.version} declares fields "
                f"{fields}. A Migration is version + name + statements — a reverse or down "
                "step is the escape hatch NFR-STORE-04 closes, and this assertion is what "
                "closes it structurally rather than by review convention."
            )
            assert migration.statements, (
                f"TC-STORE-06: {tier.value} v{migration.version} carries no statements."
            )
    with pytest.raises(Exception) as frozen:
        TIER_MIGRATIONS[Tier.DURABLE][0].version = 2  # type: ignore[misc]
    assert "cannot assign to field" in str(frozen.value).lower() or "frozen" in str(
        frozen.value).lower(), (
        "TC-STORE-06: a Migration is mutable. A rewrite-in-place history is not forward-only "
        "in any sense the word carries."
    )
