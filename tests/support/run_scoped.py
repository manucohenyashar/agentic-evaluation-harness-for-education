"""`TS-88` (issue #382) support: the F-SCHEMA additions and the run-scoped-score worlds.

Gap-fix test plan §4.2:

    F-SCHEMA additions — Cohort DB at version 19 with `criterion_score` rows and **one** run;
    Cohort DB at version 19 with **two** runs and rows; Cohort DB at version 19 with two runs
    and **no** rows.

**Generated, not committed** — the `tests/integration/store/test_migrations.py` precedent
(`_fixture_database`): the tier's migrations `1..19` are applied by hand to a raw SQLite file, the
version rows stamped, and deterministic rows seeded. That is exactly the state a database written
by the pre-delta binary is in, and it stays that state after later migrations ship — building by
opening a store would silently build at whatever head the binary has.

Rows are inserted by column name; any NOT NULL column without a default that a spec leaves out is
filled with a fixed placeholder, so a later pre-v19 additive column cannot break the builder.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import aeh.agg  # noqa: F401 — the full cohort chain (CLAUDE.md: all eleven contributors)
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
from aeh.store import TIER_MIGRATIONS, Tier, _SCHEMA_VERSION_TABLE

PRE_DELTA_COHORT_VERSION = 19
STAMP = "2026-01-01T00:00:00Z"
SCHEMA_COHORT_ID = "c-fschema"
SCORE_ROWS = 45  # 15 submissions × 3 criteria
CRITERIA = ("C1", "C2", "C3")
SUBMISSIONS = tuple(f"S{i:02d}" for i in range(1, 16))

#: The projection the lossless-migration checksum is taken over (TC-AGG-22 (a)).
CHECKSUM_COLUMNS = ("submission_id", "criterion_id", "band", "points", "judge_count")


def cohort_db_path(data_dir: Path, cohort_id: str = SCHEMA_COHORT_ID) -> Path:
    return Path(data_dir) / "cohorts" / f"{cohort_id}.sqlite"


def _insert(connection: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
    info = connection.execute(f"PRAGMA table_info({table})").fetchall()
    row = dict(values)
    for _cid, name, col_type, not_null, default, pk in info:
        if name in row or not not_null or default is not None:
            continue
        row[name] = 0 if "INT" in (col_type or "").upper() or "REAL" in (col_type or "").upper() \
            else f"fixture-{name}"
    columns = ", ".join(f'"{c}"' for c in row)
    placeholders = ", ".join("?" for _ in row)
    connection.execute(f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})',
                       tuple(row.values()))


def build_pre_delta_cohort(
    data_dir: Path, *, runs: int, with_scores: bool, cohort_id: str = SCHEMA_COHORT_ID
) -> tuple[str, ...]:
    """A Cohort DB standing at version 19 with `runs` run rows and, if `with_scores`, the 45
    `criterion_score` rows. Returns the run ids."""
    path = cohort_db_path(data_dir, cohort_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(str(_SCHEMA_VERSION_TABLE))
        for migration in TIER_MIGRATIONS[Tier.COHORT]:
            if migration.version > PRE_DELTA_COHORT_VERSION:
                continue
            for statement in migration.statements:
                connection.execute(str(statement))
            connection.execute(
                "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, STAMP),
            )
        _insert(connection, "cohort",
                {"cohort_id": cohort_id, "consent_class": "synthetic", "created_at": STAMP})
        for submission_id in SUBMISSIONS:
            _insert(connection, "submission", {"submission_id": submission_id,
                                               "cohort_id": cohort_id,
                                               "student_ref": f"ref-{submission_id}"})
        run_ids = tuple(f"run-fschema-{index}" for index in range(1, runs + 1))
        for run_id in run_ids:
            _insert(connection, "run", {
                "run_id": run_id, "cohort_id": cohort_id, "package_version_id": "pv-fschema",
                "package_id": "pkg-fschema", "panel_config": "{}", "backend_profile": "edge-local",
                "provider_config": "{}", "prompt_template_v": "p", "status": "complete",
                "started_at": STAMP,
            })
        if with_scores:
            for s_index, submission_id in enumerate(SUBMISSIONS):
                for c_index, criterion_id in enumerate(CRITERIA):
                    _insert(connection, "criterion_score", {
                        "submission_id": submission_id, "criterion_id": criterion_id,
                        "band": f"B{(s_index + c_index) % 4}",
                        "points": float((s_index * 3 + c_index) % 10),
                        "judge_count": 3, "agreement": 0.5, "state": "final", "routing": "auto",
                    })
        connection.commit()
    finally:
        connection.close()
    return run_ids


def score_checksum(path: Path) -> str:
    """sha256 over the ordered `CHECKSUM_COLUMNS` projection of `criterion_score`."""
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            f"SELECT {', '.join(CHECKSUM_COLUMNS)} FROM criterion_score "
            f"ORDER BY submission_id, criterion_id"
        ).fetchall()
    finally:
        connection.close()
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def table_sql_and_rows(path: Path, table: str) -> tuple[str | None, list[tuple]]:
    """The table's DDL and every row, for a byte-identical 'unchanged' comparison."""
    connection = sqlite3.connect(path)
    try:
        ddl = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        rows = connection.execute(f'SELECT * FROM "{table}" ORDER BY 1, 2').fetchall() \
            if ddl else []
    finally:
        connection.close()
    return (ddl[0] if ddl else None), rows


def schema_versions(path: Path) -> list[int]:
    connection = sqlite3.connect(path)
    try:
        return [row[0] for row in connection.execute(
            "SELECT version FROM schema_version ORDER BY version")]
    finally:
        connection.close()


def tables(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        connection.close()


#: The run a seed attributes its `criterion_score` rows to when the world it seeds has no real run
#: (#359: every score row names a run, and consumers read the cohort's newest run).
FIXTURE_RUN_ID = "run-fixture"


def ensure_fixture_run(tx: Any, cohort_id: str) -> None:
    """Give a run-less seeded cohort the one run its hand-written score rows name.

    A no-op when the cohort already has a run: the seeds' `run_id` subquery then names that run,
    so the rows stay with the real run. `started_at` is NULL, so a real run always sorts newer."""
    tx.execute(
        "INSERT INTO run (run_id, cohort_id, package_version_id, package_id, panel_config, "
        "backend_profile, provider_config, prompt_template_v, status) "
        "SELECT :r, :c, 'pv-fixture', 'pkg-fixture', '{}', 'edge-local', '{}', 'p', 'complete' "
        "WHERE NOT EXISTS (SELECT 1 FROM run WHERE cohort_id = :c)",
        r=FIXTURE_RUN_ID, c=cohort_id,
    )


#: The design's migration name (FR-AGG-16), which the blockers probe for.
RUN_SCOPED_MIGRATION = "agg_run_scoped_score"


def run_scoped_migration() -> Any:
    """The `agg_run_scoped_score` migration object, or `None` before #359 lands."""
    for migration in TIER_MIGRATIONS[Tier.COHORT]:
        if migration.name == RUN_SCOPED_MIGRATION:
            return migration
    return None


__all__ = [
    "CHECKSUM_COLUMNS",
    "CRITERIA",
    "FIXTURE_RUN_ID",
    "PRE_DELTA_COHORT_VERSION",
    "RUN_SCOPED_MIGRATION",
    "SCHEMA_COHORT_ID",
    "SCORE_ROWS",
    "SUBMISSIONS",
    "build_pre_delta_cohort",
    "cohort_db_path",
    "ensure_fixture_run",
    "run_scoped_migration",
    "schema_versions",
    "score_checksum",
    "table_sql_and_rows",
    "tables",
]
