"""`TS-88` (issue #382) — `TC-AGG-22` and `RES-21`: the `criterion_score` rebuild onto
`(run_id, submission_id, criterion_id)` is lossless, refuses ambiguous attribution loudly, and is
atomic under a kill.

Gap-fix test plan §5 / §6 (`FR-AGG-16`, `RISK-43` Critical and irreversible; base `FR-STORE-02`).

`TC-AGG-22` — open each F-SCHEMA Cohort DB with the full migration chain. Oracle: checksum golden
+ exact error.

| Variant | Store at v19 | Expected |
|---|---|---|
| (a) | 1 run, 45 score rows | all 45 survive; `run_id` = that run; the `(submission_id, criterion_id, band, points, judge_count)` checksum equals the pre-migration one; `band_spread = 0` and `modal_band = band` |
| (b) | 2 runs, 45 rows | the open raises `MigrationError("criterion_score rows cannot be attributed to a run: 2 runs")`; the file is unchanged (byte-identical `criterion_score` table, `schema_version` still 19) |
| (c) | 2 runs, 0 rows | migrates; the table has the new PK |
| (d) | after (a) | a `judge_count = 2` row fails the CHECK; two rows differing only in `run_id` coexist |
| (e) | after (a) | the Cohort `COMPLETE_SCHEMA_VERSIONS` pin equals the new head; `IncompleteMigrationChainError` fires if `aeh.agg` is not imported |

`RES-21` — a process killed between `CREATE TABLE criterion_score_new` and `DROP TABLE
criterion_score`, simulated by a raising statement: on reopen, either the migration completed with
all 45 rows or the file is still at v19 with all 45 rows; no state has zero rows or both tables.

**The raising statement.** The migration's own statement tuple is replaced, for one open, by a copy
with a statement that fails inserted immediately before its `DROP TABLE criterion_score` — the
position the plan names, found in the migration rather than assumed. The failing statement is plain
invalid SQL, so the failure is the database's, at exactly that point in the migration transaction.

**Written ahead of implementation: yes** — every case is keyed to #359, which adds the migration.
Before it lands each case fails in the fixture's own precondition (`run_scoped_migration()` is
`None`) and names #359.

**Error type.** `MigrationError` is the design's name; `aeh.store` declares no such class today, so
the case asserts the raised type's **name** and the exact message, and the PR says so.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from aeh.store import COMPLETE_SCHEMA_VERSIONS, TIER_MIGRATIONS, Tier, open_store
from tests.support.impl import NotImplementedYet
from tests.support.run_scoped import (
    PRE_DELTA_COHORT_VERSION,
    SCHEMA_COHORT_ID,
    SCORE_ROWS,
    build_pre_delta_cohort,
    cohort_db_path,
    run_scoped_migration,
    schema_versions,
    score_checksum,
    table_sql_and_rows,
    tables,
)

pytestmark = pytest.mark.integration

ISSUE = "#359"
REPO_ROOT = Path(__file__).resolve().parents[3]


def _require_migration():
    migration = run_scoped_migration()
    if migration is None:
        raise NotImplementedYet(
            f"no cohort migration named 'agg_run_scoped_score' is registered (blocked on {ISSUE})"
        )
    return migration


def _open_cohort(data_dir: Path):
    store = open_store(data_dir)
    try:
        store.cohort(SCHEMA_COHORT_ID)
    except BaseException:
        store.close()
        raise
    return store


def _pk_columns(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        info = connection.execute("PRAGMA table_info(criterion_score)").fetchall()
    finally:
        connection.close()
    return [row[1] for row in sorted(info, key=lambda r: r[5]) if row[5]]


# --- TC-AGG-22 (a), (d), (e) -----------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_agg_22_a_a_single_run_store_migrates_losslessly(tmp_data_dir):
    """(a) — 45 rows survive under the one run, checksum unchanged, spread 0, modal = band;
    (d) — the CHECK survives and the new key admits a second run's row."""
    _require_migration()
    (run_id,) = build_pre_delta_cohort(tmp_data_dir, runs=1, with_scores=True)
    path = cohort_db_path(tmp_data_dir)
    before = score_checksum(path)

    store = _open_cohort(tmp_data_dir)
    try:
        handle = store.cohort(SCHEMA_COHORT_ID)
        rows = [dict(r) for r in handle.query("SELECT * FROM criterion_score")]
        assert len(rows) == SCORE_ROWS, f"{len(rows)} rows survived the rebuild, expected 45"
        assert {r["run_id"] for r in rows} == {run_id}, "rows were not attributed to the one run"
        assert all(r["band_spread"] == 0 for r in rows), "migrated rows must carry band_spread 0"
        assert all(r["modal_band"] == r["band"] for r in rows), "migrated modal_band != band"
    finally:
        store.close()
    assert score_checksum(path) == before, "the rebuild changed a migrated score's value"
    assert _pk_columns(path) == ["run_id", "submission_id", "criterion_id"]

    # (d) the judge_count CHECK is kept; run_id is part of the key.
    connection = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO criterion_score (run_id, submission_id, criterion_id, band, "
                "judge_count) VALUES ('run-other', 'S01', 'C1', 'B1', 2)")
        connection.execute(
            "INSERT INTO criterion_score (run_id, submission_id, criterion_id, band, "
            "judge_count) VALUES ('run-other', 'S01', 'C1', 'B1', 3)")
        count = connection.execute(
            "SELECT COUNT(*) FROM criterion_score WHERE submission_id = 'S01' "
            "AND criterion_id = 'C1'").fetchone()[0]
    finally:
        connection.close()
    assert count == 2, "two rows differing only in run_id must coexist"


@pytest.mark.writtenahead
def test_tc_agg_22_e_the_cohort_pin_is_the_head_and_a_chain_without_agg_refuses(tmp_data_dir):
    """(e) — the Cohort pin equals the highest registered cohort migration, and a process that
    opens a store without importing `aeh.agg` refuses at the open.

    **Limit, disclosed.** The store's guard compares the highest version present with the pin,
    not chain completeness, so this arm discriminates only while `aeh.agg` owns the newest Cohort
    migration (true once #359 lands). A later migration owned by another module would turn it red
    with nothing wrong in `aeh.agg` — which is the highest-version-only check showing, not a
    defect in this arm."""
    _require_migration()
    head = max(m.version for m in TIER_MIGRATIONS[Tier.COHORT])
    assert COMPLETE_SCHEMA_VERSIONS[Tier.COHORT] == head

    others = "aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch, " \
             "aeh.pkg, aeh.review, aeh.synth"
    script = (
        "import sys; sys.path.insert(0, 'src'); "
        f"import {others}; "
        "import aeh.store as s; "
        f"store = s.open_store(r'{tmp_data_dir}'); "
        "\ntry:\n    store.cohort('c-no-agg')\n"
        "except s.IncompleteMigrationChainError:\n    print('REFUSED')\n"
        "except Exception as e:\n    print('OTHER', type(e).__name__, e)\n"
        "else:\n    print('OPENED')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO_ROOT, capture_output=True, text=True, timeout=120
    )
    assert completed.stdout.strip().startswith("REFUSED"), (
        f"a store opened without aeh.agg did not refuse: {completed.stdout!r} {completed.stderr!r}"
    )


# --- TC-AGG-22 (b), (c) ----------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_agg_22_b_two_runs_with_rows_refuse_and_leave_the_file_untouched(tmp_data_dir):
    """(b) — ambiguous attribution: exact error, and the file is exactly as it was."""
    _require_migration()
    build_pre_delta_cohort(tmp_data_dir, runs=2, with_scores=True)
    path = cohort_db_path(tmp_data_dir)
    table_before = table_sql_and_rows(path, "criterion_score")

    with pytest.raises(Exception) as refusal:
        _open_cohort(tmp_data_dir).close()

    assert type(refusal.value).__name__ == "MigrationError", (
        f"expected MigrationError, got {type(refusal.value).__name__}: {refusal.value}"
    )
    assert str(refusal.value) == "criterion_score rows cannot be attributed to a run: 2 runs"
    assert table_sql_and_rows(path, "criterion_score") == table_before, (
        "the refused migration changed the criterion_score table"
    )
    assert schema_versions(path)[-1] == PRE_DELTA_COHORT_VERSION
    assert "criterion_score_new" not in tables(path)


@pytest.mark.writtenahead
def test_tc_agg_22_c_two_runs_without_rows_migrate_to_the_new_key(tmp_data_dir):
    """(c) — nothing to attribute, so two runs are no obstacle."""
    _require_migration()
    build_pre_delta_cohort(tmp_data_dir, runs=2, with_scores=False)
    _open_cohort(tmp_data_dir).close()
    path = cohort_db_path(tmp_data_dir)
    assert _pk_columns(path) == ["run_id", "submission_id", "criterion_id"]
    assert schema_versions(path)[-1] > PRE_DELTA_COHORT_VERSION


# --- RES-21 — killed mid-rebuild ------------------------------------------------------------


@pytest.mark.writtenahead
def test_res_21_a_kill_mid_rebuild_leaves_either_the_old_or_the_new_table_whole(
    tmp_data_dir, monkeypatch
):
    """`RES-21` — a failure between `CREATE TABLE criterion_score_new` and `DROP TABLE
    criterion_score`: the reopen finds 45 rows in exactly one `criterion_score` table."""
    migration = _require_migration()
    build_pre_delta_cohort(tmp_data_dir, runs=1, with_scores=True)
    path = cohort_db_path(tmp_data_dir)

    texts = [str(statement) for statement in migration.statements]
    drops = [i for i, text in enumerate(texts)
             if "DROP TABLE" in text.upper() and "CRITERION_SCORE" in text.upper()
             and "CRITERION_SCORE_NEW" not in text.upper()]
    creates = [i for i, text in enumerate(texts) if "CRITERION_SCORE_NEW" in text.upper()
               and "CREATE TABLE" in text.upper()]
    assert drops and creates and creates[0] < drops[0], (
        "precondition: the rebuild is expected to CREATE criterion_score_new before it DROPs "
        f"criterion_score; statements were {[t.split(chr(10))[0][:60] for t in texts]}"
    )
    raising = type(migration.statements[0])("SELECT * FROM res_21_simulated_kill_point")
    killed = dataclasses.replace(
        migration,
        statements=tuple(migration.statements[: drops[0]]) + (raising,)
        + tuple(migration.statements[drops[0]:]),
    )
    chain = tuple(killed if m is migration else m for m in TIER_MIGRATIONS[Tier.COHORT])
    monkeypatch.setitem(TIER_MIGRATIONS, Tier.COHORT, chain)

    with pytest.raises(Exception):
        _open_cohort(tmp_data_dir).close()
    monkeypatch.undo()

    present = tables(path)
    assert not {"criterion_score", "criterion_score_new"} <= present, (
        "after the kill both the old and the new table exist"
    )
    connection = sqlite3.connect(path)
    try:
        surviving = connection.execute("SELECT COUNT(*) FROM criterion_score").fetchone()[0]
    finally:
        connection.close()
    assert surviving == SCORE_ROWS, f"after the kill criterion_score holds {surviving} rows"
    assert schema_versions(path)[-1] == PRE_DELTA_COHORT_VERSION, (
        "the failed migration left a version stamp behind"
    )

    # The reopen with the real chain completes, all 45 rows intact.
    store = _open_cohort(tmp_data_dir)
    try:
        count = store.cohort(SCHEMA_COHORT_ID).query(
            "SELECT COUNT(*) AS n FROM criterion_score")[0]["n"]
    finally:
        store.close()
    assert count == SCORE_ROWS
