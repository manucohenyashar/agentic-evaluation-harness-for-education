"""Validity T7 (issue #900): the statistical-validity migrations upgrade cleanly, with their pins
bumped and the cohort-migration checklist done.

Traces: TC-PKG-41 (P1, P2; FR-SETUP-20, FR-STATS-33), TC-REVIEW-108 (R1), TC-STORE-32 (S1;
FR-CALIB-17), TC-STORE-33 (J1; FR-JUDGE-40). Source: `docs/design/statistical_validity_test_plan.md`
§3.4, §3.7, §3.10.

| Case | Migration | Built at | Expected after the upgrade |
|---|---|---|---|
| TC-PKG-41 (P1) | Package 17 `pkg_calibration_example_mark` | Package 16 | the table with its PK; a duplicate `(version, document, criterion)` refused |
| TC-PKG-41 (P2) | Durable 14 `pkg_validation_administration` | Durable 13 | an old record reads `absence_reason` NULL and `unmarked_count` 0; `'other'` refused |
| TC-REVIEW-108 | Cohort 37 `review_blind_draw` | Cohort 36 | `blind_draft` with its PK; the checklist (pin, F-SCHEMA, purge lists, SEC-15) |
| TC-STORE-32 | Cohort 38 `store_cohort_purpose` | Cohort 37 | an old class reads `'class'`; `'other'` refused; the column without `aeh.calib` |
| TC-STORE-33 | Cohort 36 `judge_verdict_reanchored` | Cohort 35 | an old verdict reads 0; `2` refused |

**TC-PKG-41 spans two tiers.** The plan says "open a durable store at the previous pin". P2 is
Durable 14, but P1 (`calibration_example_mark`) is Package 17 (#885): marks are reference data
beside a package version. So the P1 arm upgrades a Package file built at 16 and the P2 arm a Tier
D file built at 13.

**Every upgrade has a precondition arm.** It shows the column or table is absent at the earlier
version. Without it, a builder that applied the whole chain would pass every assertion below.
**Every CHECK refusal has an accepted twin of the same shape.** Without it, an IntegrityError from
an unrelated filler column would pass the refusal arm.

**Pins are not literals.** Each named migration is asserted at its version in its owner's chain,
and the tier's pin equal to the chain head. A literal `38` would go stale at the next migration.
The pin gate test (`TC-STORE-04`'s F-SCHEMA golden, and the open-time refusal) owns the rest.

**Isolation: rung 3.** Raw SQLite files built at the earlier version from the tiers' own declared
migrations (`tests/support/tier_at_version.py`), then upgraded by opening a real store. TC-STORE-32's
import arm runs in a fresh interpreter with controlled imports.

**Written ahead: no, in effect.** The issue says `yes`, but R1 (#875), P2 (#879), S1 (#880), P1
(#885) and J1 (#863/#918) are merged, so every case here runs in the gate. No case needs P3.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import aeh.agg  # noqa: F401 -- the full migration chain (CLAUDE.md)
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
from aeh.store import COMPLETE_SCHEMA_VERSIONS, TIER_MIGRATIONS, Tier, open_store
from tests.support.tier_at_version import (
    STAMP,
    build_tier_at,
    columns,
    insert_row,
    primary_key,
    rows,
    schema_version,
    tier_path,
    try_insert,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
F_SCHEMA = REPO_ROOT / "fixtures" / "F-SCHEMA" / "post-migration-checksums.json"

PACKAGE_ID = "pkg-t7"
VERSION_ID = "pkg-t7@aaaaaaaaaaaa"
COHORT_ID = "c-t7"

#: (tier, version, name) of each migration under test.
P1 = (Tier.PACKAGE, 17, "pkg_calibration_example_mark")
P2 = (Tier.DURABLE, 14, "pkg_validation_administration")
J1 = (Tier.COHORT, 36, "judge_verdict_reanchored")
R1 = (Tier.COHORT, 37, "review_blind_draw")
S1 = (Tier.COHORT, 38, "store_cohort_purpose")


def _assert_in_chain_and_pinned(migration: tuple[Tier, int, str]) -> None:
    """The migration sits at its version in its tier's chain, and the tier's pin is the chain's
    head, so the pin was bumped at least to it."""
    tier, version, name = migration
    chain = {m.version: m.name for m in TIER_MIGRATIONS[tier]}
    assert chain.get(version) == name, (
        f"{tier.value} migration {version} is {chain.get(version)!r}, not {name!r}")
    head = max(chain)
    assert COMPLETE_SCHEMA_VERSIONS[tier] == head >= version, (
        f"the {tier.value} pin is {COMPLETE_SCHEMA_VERSIONS[tier]}, the chain head is {head}: "
        f"{name} (v{version}) landed without its pin bump")


def _golden() -> dict:
    """F-SCHEMA: `<tier>@vN` is a file built at N and migrated to head, per table."""
    return json.loads(F_SCHEMA.read_text(encoding="utf-8"))


def _cohort_entries() -> dict[str, dict]:
    entries = {k: v for k, v in _golden().items() if k.startswith("cohort@v")}
    assert entries, "the F-SCHEMA golden holds no cohort entry"
    return entries


# --- seeds: what the older binary left on disk -------------------------------------------------


def _seed_package(connection: sqlite3.Connection) -> None:
    insert_row(connection, "package", {"package_id": PACKAGE_ID, "created_at": STAMP})
    insert_row(connection, "package_version", {
        "package_version_id": VERSION_ID, "package_id": PACKAGE_ID, "revision": 1, "locked": 0})


def _seed_durable(connection: sqlite3.Connection) -> None:
    insert_row(connection, "package_validation", {
        "package_version_id": VERSION_ID, "cohort_id": COHORT_ID, "recorded_at": STAMP,
        "cohorts_used": 1, "operational_count": 0, "blind_count": 4, "n": 4,
        "weakest_per_population": "{}", "surface_proxy_flags": "[]"})


def _seed_cohort(connection: sqlite3.Connection) -> None:
    insert_row(connection, "cohort",
               {"cohort_id": COHORT_ID, "consent_class": "synthetic", "created_at": STAMP})
    insert_row(connection, "submission", {"submission_id": "sub-1", "cohort_id": COHORT_ID,
                                          "student_ref": "ref-1"})
    insert_row(connection, "run", {
        "run_id": "run-1", "cohort_id": COHORT_ID, "package_version_id": VERSION_ID,
        "package_id": PACKAGE_ID, "panel_config": "{}", "backend_profile": "edge-local",
        "provider_config": "{}", "prompt_template_v": "p", "status": "complete",
        "started_at": STAMP})
    insert_row(connection, "work_unit", {"work_id": "w-1", "submission_id": "sub-1",
                                         "stage": "score", "status": "done", "run_id": "run-1"})
    insert_row(connection, "verdict", {"verdict_id": "v-old", "work_id": "w-1",
                                       "judge_id": "j-1", "band": "B2"})


def _upgraded(tmp_data_dir: Path, tier: Tier, at_version: int, seed) -> Path:
    """Build the tier's file at `at_version` with `seed`, then open a real store over it."""
    key = {Tier.PACKAGE: PACKAGE_ID, Tier.COHORT: COHORT_ID}.get(tier, "")
    path = build_tier_at(tier_path(tmp_data_dir, tier, key), tier, at_version, seed)
    assert schema_version(path) == at_version
    store = open_store(tmp_data_dir)
    try:
        if tier is Tier.PACKAGE:
            store.package(PACKAGE_ID)
        elif tier is Tier.COHORT:
            store.cohort(COHORT_ID)
        else:
            store.durable()
    finally:
        store.close()
    assert schema_version(path) == COMPLETE_SCHEMA_VERSIONS[tier], (
        f"opening the store left the {tier.value} file at v{schema_version(path)}")
    return path


def _absent_before(tmp_data_dir: Path, tier: Tier, at_version: int, seed, table: str,
                   column: str | None = None) -> None:
    key = {Tier.PACKAGE: PACKAGE_ID, Tier.COHORT: COHORT_ID}.get(tier, "")
    path = build_tier_at(tier_path(tmp_data_dir, tier, key), tier, at_version, seed)
    present = columns(path, table)
    if column is None:
        assert not present, f"{table} already exists at {tier.value} v{at_version}"
    else:
        assert present and column not in present, (
            f"{table}.{column} already exists at {tier.value} v{at_version}: {sorted(present)}")


# --- TC-PKG-41: P1 (Package 17) and P2 (Durable 14) --------------------------------------------


def test_tc_pkg_41_precondition_no_mark_table_at_package_16_nor_new_columns_at_durable_13(
        tmp_data_dir):
    _absent_before(tmp_data_dir, Tier.PACKAGE, 16, _seed_package, "calibration_example_mark")
    _absent_before(tmp_data_dir, Tier.DURABLE, 13, _seed_durable, "package_validation",
                   "absence_reason")
    _absent_before(tmp_data_dir / "again", Tier.DURABLE, 13, _seed_durable,
                   "package_validation", "unmarked_count")


def test_tc_pkg_41_p1_calibration_example_mark_has_its_key_and_refuses_a_duplicate(tmp_data_dir):
    """Package 16 → 17: the marks table exists with PK (version, document, criterion); one mark
    per criterion of a marked example, so a second insert of the same key is refused."""
    path = _upgraded(tmp_data_dir, Tier.PACKAGE, 16, _seed_package)

    assert primary_key(path, "calibration_example_mark") == (
        "package_version_id", "document_id", "criterion_id")
    mark = {"package_version_id": VERSION_ID, "document_id": "doc-1", "criterion_id": "C1",
            "band": "B2", "marked_at": STAMP}
    assert try_insert(path, "calibration_example_mark", mark) is None, "the first mark refused"
    other = try_insert(path, "calibration_example_mark", {**mark, "criterion_id": "C2"})
    assert other is None, f"a mark on another criterion was refused: {other}"

    duplicate = try_insert(path, "calibration_example_mark", {**mark, "band": "B3"})

    assert duplicate is not None and "UNIQUE" in str(duplicate).upper(), (
        f"a second mark for (version, doc-1, C1) was not refused by the key: {duplicate}")
    stored = rows(path, "SELECT criterion_id, band FROM calibration_example_mark "
                        "ORDER BY criterion_id")
    assert stored == [{"criterion_id": "C1", "band": "B2"},
                      {"criterion_id": "C2", "band": "B2"}], stored


def test_tc_pkg_41_p2_an_old_record_reads_null_reason_and_zero_unmarked(tmp_data_dir):
    """Durable 13 → 14: the record an older binary wrote reads `absence_reason` NULL (it is not
    an absence) and `unmarked_count` 0."""
    path = _upgraded(tmp_data_dir, Tier.DURABLE, 13, _seed_durable)

    (record,) = rows(path, "SELECT * FROM package_validation")

    assert record["blind_count"] == 4, record
    assert record["absence_reason"] is None, record
    assert record["unmarked_count"] == 0, record
    assert columns(path, "package_validation")["unmarked_count"][1] == 1, "not NOT NULL"


def test_tc_pkg_41_p2_absence_reason_other_is_refused_by_the_check(tmp_data_dir):
    path = _upgraded(tmp_data_dir, Tier.DURABLE, 13, _seed_durable)
    record = {"package_version_id": VERSION_ID, "recorded_at": STAMP, "cohorts_used": 1,
              "operational_count": 0, "blind_count": 0, "n": 0,
              "weakest_per_population": "{}", "surface_proxy_flags": "[]"}

    for accepted, reason in (("c-skip", "skipped"), ("c-none", "none_marked")):
        error = try_insert(path, "package_validation",
                           {**record, "cohort_id": accepted, "absence_reason": reason})
        assert error is None, f"absence_reason={reason!r} refused: {error}"
    refused = try_insert(path, "package_validation",
                         {**record, "cohort_id": "c-other", "absence_reason": "other"})

    assert refused is not None and "CHECK" in str(refused).upper(), (
        f"absence_reason='other' was not refused by the CHECK: {refused}")
    stored = {r["cohort_id"] for r in rows(path, "SELECT cohort_id FROM package_validation")}
    assert stored == {COHORT_ID, "c-skip", "c-none"}, stored


def test_tc_pkg_41_the_package_and_durable_pins_are_bumped():
    _assert_in_chain_and_pinned(P1)
    _assert_in_chain_and_pinned(P2)
    golden = _golden()
    assert golden[f"package@v{P1[1]}"]["calibration_example_mark"]["columns"] == [
        "package_version_id", "document_id", "criterion_id", "band", "marked_at"]
    durable = golden[f"durable@v{P2[1]}"]["package_validation"]["columns"]
    assert {"absence_reason", "unmarked_count"} <= set(durable), durable


# --- TC-REVIEW-108: R1 (Cohort 37) and its checklist -------------------------------------------


def test_tc_review_108_precondition_no_blind_draft_at_cohort_36(tmp_data_dir):
    _absent_before(tmp_data_dir, Tier.COHORT, 36, _seed_cohort, "blind_draft")


def test_tc_review_108_blind_draft_exists_with_its_key_after_the_upgrade(tmp_data_dir):
    """Cohort 36 → 37: one draft per (run, submission, criterion), changeable by replacing it,
    never two."""
    path = _upgraded(tmp_data_dir, Tier.COHORT, 36, _seed_cohort)

    assert primary_key(path, "blind_draft") == ("run_id", "submission_id", "criterion_id")
    assert set(columns(path, "blind_draft")) == {
        "run_id", "submission_id", "criterion_id", "band", "updated_at"}
    draft = {"run_id": "run-1", "submission_id": "sub-1", "criterion_id": "C1", "band": "B1",
             "updated_at": STAMP}
    assert try_insert(path, "blind_draft", draft) is None
    duplicate = try_insert(path, "blind_draft", {**draft, "band": "B3"})
    assert duplicate is not None and "UNIQUE" in str(duplicate).upper(), duplicate
    assert {"blind_draw", "blind_draw_seat"} <= {
        r["name"] for r in rows(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_tc_review_108_the_cohort_pin_and_the_f_schema_golden():
    """The pin moved with R1, and the F-SCHEMA golden was regenerated: each `cohort@vN` entry is
    a file built at N and migrated to head, so every one (and a `cohort@v37` entry exists) carries
    the three draw tables. TC-STORE-04 holds the golden equal to what the migrations build, so
    this reads the golden rather than rebuilding it."""
    _assert_in_chain_and_pinned(R1)
    entries = _cohort_entries()
    assert f"cohort@v{R1[1]}" in entries
    for key, tables in entries.items():
        assert tables.get("blind_draft", {}).get("columns") == [
            "run_id", "submission_id", "criterion_id", "band", "updated_at"], key
        assert {"blind_draw", "blind_draw_seat"} <= set(tables), key


def test_tc_review_108_the_draw_tables_are_in_the_purge_lists():
    """The checklist's purge item: each draw table is swept (`_PURGE_DELETES`), visited
    (`_COHORT_PURGE_ORDER`, children before `run`), and scanned for blob references."""
    from aeh.store import purge

    order = purge._COHORT_PURGE_ORDER  # noqa: SLF001 -- the registry under audit
    for table in ("blind_draft", "blind_draw_seat", "blind_draw"):
        assert table in order, f"{table} is not in _COHORT_PURGE_ORDER"
        assert order.index(table) < order.index("run"), f"{table} is swept after run"
        assert str(purge._PURGE_DELETES[table]).strip() == f"DELETE FROM {table}"  # noqa: SLF001
        assert table in purge._PURGE_BLOB_HASH_SCANS  # noqa: SLF001


def test_tc_review_108_the_draw_tables_are_not_ingest_owned():
    """The checklist's owned-table item. R1's tables are M-REVIEW's, so the item holds when
    M-INGEST's owned-table lists do NOT name them and no ingest statement writes them. (Adding
    them there would be the defect.)"""
    from aeh import ingest
    from tests.contract.ingest._doubles import INGEST_OWNED_TABLES

    draw_tables = {"blind_draft", "blind_draw", "blind_draw_seat"}
    assert not draw_tables & set(INGEST_OWNED_TABLES)
    texts = _module_statement_texts(ingest)
    assert texts, "the ingest statement registry read nothing"
    writes = [t for t in texts
              if t.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}]
    assert writes, "no ingest write statement found; the sweep inspects nothing"
    assert not [t for t in writes if any(name in t for name in draw_tables)]


def test_tc_review_108_the_draw_statements_are_in_the_sec_15_census():
    """The checklist's SEC-15 item: `aeh.review.blind` assembles no SQL, every execute site in
    it is one the census lists, and each draw statement is a declared `Statement`."""
    from aeh.review.schema import BLIND_DRAW_STATEMENTS
    from aeh.store import Statement
    from tests.artifact.test_store_query_surface import KNOWN_EXECUTE_SITES
    from tests.support.sql_scan import execute_call_sites, scan_module

    blind = REPO_ROOT / "src" / "aeh" / "review" / "blind.py"
    assert scan_module("aeh.review.blind", blind, REPO_ROOT) == []
    sites = {s for s in execute_call_sites(REPO_ROOT) if s.startswith("aeh.review.blind:")}
    assert sites, "the census walk found no execute site in aeh.review.blind"
    assert sites <= KNOWN_EXECUTE_SITES, sorted(sites - KNOWN_EXECUTE_SITES)
    assert all(isinstance(s, Statement) for s in BLIND_DRAW_STATEMENTS.values())
    assert any("blind_draft" in str(s) for s in BLIND_DRAW_STATEMENTS.values())


def _module_statement_texts(package) -> list[str]:
    """The SQL of every `Statement` reachable as a module-level value (or a mapping's value) in
    the package's submodules."""
    import importlib
    import pkgutil

    from aeh.store import Statement

    texts: list[str] = []
    for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        module = importlib.import_module(info.name)
        for value in vars(module).values():
            candidates = value.values() if isinstance(value, dict) else (value,)
            texts.extend(str(c) for c in candidates if isinstance(c, Statement))
    return texts


# --- TC-STORE-32: S1 (Cohort 38) ---------------------------------------------------------------


def test_tc_store_32_precondition_no_purpose_at_cohort_37(tmp_data_dir):
    _absent_before(tmp_data_dir, Tier.COHORT, 37, _seed_cohort, "cohort", "purpose")


def test_tc_store_32_an_existing_class_reads_class_and_other_is_refused(tmp_data_dir):
    path = _upgraded(tmp_data_dir, Tier.COHORT, 37, _seed_cohort)

    assert rows(path, "SELECT cohort_id, purpose FROM cohort") == [
        {"cohort_id": COHORT_ID, "purpose": "class"}]
    base = {"consent_class": "synthetic", "created_at": STAMP}
    assert try_insert(path, "cohort", {**base, "cohort_id": "c-cal",
                                       "purpose": "calibration"}) is None
    refused = try_insert(path, "cohort", {**base, "cohort_id": "c-other", "purpose": "other"})

    assert refused is not None and "CHECK" in str(refused).upper(), refused
    assert {r["cohort_id"] for r in rows(path, "SELECT cohort_id FROM cohort")} == {
        COHORT_ID, "c-cal"}


_WITHOUT_CALIB = """
import sqlite3, sys, pathlib
import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch
import aeh.pkg, aeh.review, aeh.synth
from aeh.store import open_store
loaded = sorted(m for m in sys.modules if m == "aeh.calib" or m.startswith("aeh.calib."))
root = pathlib.Path(sys.argv[1])
store = open_store(root)
store.cohort("c-fresh")
store.close()
connection = sqlite3.connect(root / "cohorts" / "c-fresh.sqlite")
columns = [row[1] for row in connection.execute("PRAGMA table_info(cohort)")]
connection.close()
print(repr((loaded, columns)))
"""


def test_tc_store_32_a_fresh_process_without_aeh_calib_builds_the_column(tmp_data_dir):
    """S1 is declared in M-STORE, not in its consumer M-CALIB, because M-CALIB may be absent: a
    process that imports the eleven contributors and never `aeh.calib` still builds a cohort
    file carrying `purpose`."""
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    result = subprocess.run(
        [sys.executable, "-c", _WITHOUT_CALIB, str(tmp_data_dir)], cwd=REPO_ROOT, env=env,
        capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr

    loaded, built = eval(result.stdout.strip().splitlines()[-1])  # noqa: S307 -- our own repr

    assert loaded == [], f"the eleven contributors pulled in {loaded}; the case is void"
    assert "purpose" in built, f"a cohort built without aeh.calib lacks purpose: {built}"


def test_tc_store_32_the_cohort_pin_and_the_f_schema_golden():
    _assert_in_chain_and_pinned(S1)
    entries = _cohort_entries()
    assert f"cohort@v{S1[1]}" in entries
    for key, tables in entries.items():
        assert "purpose" in tables["cohort"]["columns"], key


def test_tc_store_32_purpose_needs_no_purge_or_census_entry():
    """The checklist for S1: it adds a column to `cohort`, which is already swept, and no table;
    so the purge lists and the owned-table lists are unchanged by it, and `cohort` stays the last
    table swept. No statement assembles SQL around it (the migration is a declared literal)."""
    from aeh.store import purge
    from tests.support.sql_scan import scan_module

    assert purge._COHORT_PURGE_ORDER[-1] == "cohort"  # noqa: SLF001
    assert "cohort" in purge._PURGE_DELETES  # noqa: SLF001
    migrations_py = REPO_ROOT / "src" / "aeh" / "store" / "migrations.py"
    assert scan_module("aeh.store.migrations", migrations_py, REPO_ROOT) == []


# --- TC-STORE-33: J1 (Cohort 36) ---------------------------------------------------------------


def test_tc_store_33_precondition_no_reanchored_at_cohort_35(tmp_data_dir):
    _absent_before(tmp_data_dir, Tier.COHORT, 35, _seed_cohort, "verdict", "reanchored")


def test_tc_store_33_an_old_verdict_reads_zero_and_two_is_refused(tmp_data_dir):
    path = _upgraded(tmp_data_dir, Tier.COHORT, 35, _seed_cohort)

    assert rows(path, "SELECT verdict_id, reanchored FROM verdict") == [
        {"verdict_id": "v-old", "reanchored": 0}]
    base = {"work_id": "w-1", "judge_id": "j-2", "band": "B1"}
    assert try_insert(path, "verdict", {**base, "verdict_id": "v-one", "reanchored": 1}) is None
    refused = try_insert(path, "verdict", {**base, "verdict_id": "v-two", "reanchored": 2})

    assert refused is not None and "CHECK" in str(refused).upper(), refused
    assert {r["verdict_id"] for r in rows(path, "SELECT verdict_id FROM verdict")} == {
        "v-old", "v-one"}


def test_tc_store_33_shares_the_cohort_pin_with_r1_and_s1():
    """J1, R1 and S1 each moved the cohort pin by one in their landing PRs (36, 37, 38): the
    three are consecutive in the chain and the pin is the head."""
    for migration in (J1, R1, S1):
        _assert_in_chain_and_pinned(migration)
    assert [J1[1], R1[1], S1[1]] == [36, 37, 38]
    for key, tables in _cohort_entries().items():
        if "verdict" in tables:
            assert "reanchored" in tables["verdict"]["columns"], key
