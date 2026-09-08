"""`purge_cohort` refuses until promotion, then actually removes the bytes.

Case `TC-STORE-11` (`FR-STORE-07`, `NFR-SYS-03`, P0) and `SEC-13` (§6.5), test plan §5.3.
Issue #15 (TS-09).

Rung 2 — real files, real `VACUUM`, because the oracle is a **raw-byte scan of the cohort
file and the blob directory**: a `DELETE` without `VACUUM` leaves the text recoverable in
freed pages, which is why the requirement names `VACUUM` and why a query-level assertion
would be vacuous.

`Written ahead of implementation: yes` is stale — `purge_cohort` landed with #13 and the blob
store with #12; the case runs green by design.

Promotion is simulated through an **independent** `sqlite3` connection — the owning module's
`ALTER TABLE`/`INSERT` shape, exactly the precedent `TC-STORE-12` set with its poisoned table:
the question is what `purge_cohort` does about Tier D's state, not whether the store can be
persuaded to create it.

The blob variant implements the rule **#225 declares**, which is what the §7.4 variant was
written to be rewritten against: purge reclaims the cohort's blobs by evidence — a hash
another surviving database still references is kept, a hash nothing references is unlinked.
The variant asserts the two consequences a consumer can rely on: a blob shared by two cohorts
survives the first purge and dies with the second.
"""

from __future__ import annotations

import sqlite3

import pytest

from tests.support.store_api import open_store, statement
from tests.support.store_vocabulary import column_names, is_student_name_column, table_names

pytestmark = [pytest.mark.integration]

ISSUE = "#15"

# The sentinel lives in a *known* table's column (`roster.student_ref`): purge fails closed
# on any table it does not recognize, so a scratch table would be refused rather than swept —
# the refusal is correct, and the sentinel's home must be a table the sweep actually clears.
SENTINEL = "SENTINEL-student-text-9f31c2"

PROMOTE_DDL = (
    "ALTER TABLE audit_record ADD COLUMN cohort_id TEXT",
    "ALTER TABLE label ADD COLUMN cohort_id TEXT",
    "ALTER TABLE criterion_stats ADD COLUMN cohort_id TEXT",
)


def _promote(store, cohort_id: str) -> None:
    """Give Tier D the three promotion gates, through an independent connection.

    `store.durable()` runs first: the durable file does not exist until the tier is opened,
    and a raw connection to an absent file would create an empty, migration-less database
    with no `audit_record` to ALTER."""
    store.durable()
    with sqlite3.connect(store.durable_path()) as raw:
        for ddl in PROMOTE_DDL:
            try:
                raw.execute(ddl)
            except sqlite3.OperationalError as error:
                if "duplicate column" not in str(error).lower():
                    raise
        raw.execute(
            "INSERT INTO audit_record (audit_record_id, run_id, recorded_at, profile_summary, "
            "cohort_id) VALUES (?, ?, 't', 'p', ?)", (f"a-{cohort_id}", "run-1", cohort_id))
        raw.execute(
            "INSERT INTO label (label_id, run_id, student_ref, criterion_id, label_type, band, "
            "cohort_id) VALUES (?, 'run-1', 'ref-1', 'CRIT-1', 'human', 'b1', ?)",
            (f"l-{cohort_id}", cohort_id))
        raw.execute(
            "INSERT INTO criterion_stats (package_version_id, criterion_id, backend_profile, "
            "panel_build_ref, n, cohort_id) VALUES (?, 'c', 'bp', ?, 5, ?)",
            (f"pv-{cohort_id}", f"pb-{cohort_id}", cohort_id))


def _seed_cohort(store, cohort_id: str, *, with_sentinel: bool = True) -> None:
    handle = store.cohort(cohort_id)
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            f"VALUES ('{cohort_id}', 'consented', '2026-01-01')", issue=ISSUE))
        tx.execute(statement(
            "INSERT INTO submission (submission_id, cohort_id, student_ref) "
            f"VALUES ('s-{cohort_id}', '{cohort_id}', 'ref-1')", issue=ISSUE))
    if with_sentinel:
        with handle.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO roster (cohort_id, student_ref) "
                f"VALUES ('{cohort_id}', '{SENTINEL}')", issue=ISSUE))


def test_tc_store_11_purge_refuses_every_partial_promotion_then_removes_the_bytes(
    tmp_data_dir,
):
    """`TC-STORE-11`'s three Tier D states, in order: nothing promoted; audit records only;
    everything promoted. The first two refuse with `PurgePreconditionError` and leave the
    cohort file byte-for-byte intact; the third deletes Tiers C and R, and the sentinel is
    gone from the file's **raw bytes** — not merely unreferenced."""
    store = open_store(tmp_data_dir)
    _seed_cohort(store, "c-purge")
    cohort_path = store.cohort_path("c-purge")

    # --- state 1: nothing promoted -----------------------------------------------------------
    before = cohort_path.read_bytes()
    with pytest.raises(Exception) as first:
        store.purge_cohort("c-purge")
    assert type(first.value).__name__ == "PurgePreconditionError", (
        f"TC-STORE-11: purge refused with {type(first.value).__name__}, not "
        "PurgePreconditionError — CT-STORE-11's oracle is the exact type."
    )
    assert "audit records" in str(first.value) and "labels" in str(first.value)
    assert cohort_path.read_bytes() == before, "the refusal must not touch the cohort file"

    # --- state 2: audit records promoted, labels and statistics missing ----------------------
    store.durable()  # open + migrate the durable file before the raw connection ALTERs it
    with sqlite3.connect(store.durable_path()) as raw:
        raw.execute(PROMOTE_DDL[0])
        raw.execute(
            "INSERT INTO audit_record (audit_record_id, run_id, recorded_at, profile_summary, "
            "cohort_id) VALUES ('a-partial', 'run-1', 't', 'p', 'c-purge')")
    with pytest.raises(Exception) as second:
        store.purge_cohort("c-purge")
    assert type(second.value).__name__ == "PurgePreconditionError"
    assert "labels" in str(second.value) and "per-criterion" in str(second.value)
    assert "audit records" not in str(second.value), (
        "TC-STORE-11: the refusal names every unmet gate, not just the first — an operator "
        "fixing one gate and re-running deserves to learn the state of the other two at once."
    )
    assert cohort_path.read_bytes() == before

    # --- state 3: fully promoted — the purge happens, and the bytes are gone ------------------
    _promote(store, "c-purge")
    report = store.purge_cohort("c-purge")
    assert report.cohort_id == "c-purge"
    assert set(report.rows_deleted_by_table) and report.rows_deleted_by_table["cohort"] == 1
    assert report.vacuum_duration_ms > 0.0, "FR-STORE-07 names VACUUM; a purge that skipped it"
    assert report.file_bytes_after <= report.file_bytes_before

    # The oracle: raw bytes, not the SQL surface.
    after = cohort_path.read_bytes()
    assert SENTINEL.encode() not in after, (
        "TC-STORE-11: the sentinel is recoverable from the cohort file's raw bytes after a "
        "successful purge. A DELETE without VACUUM leaves student text in freed pages — the "
        "exact failure NFR-SYS-03's purge-with-VACUUM exists to prevent."
    )
    wal = cohort_path.with_name(cohort_path.name + "-wal")
    assert not wal.exists() or SENTINEL.encode() not in wal.read_bytes(), (
        "TC-STORE-11: the sentinel survives in the -wal. Freed pages sit there until a "
        "checkpoint reclaims them; purge truncates the WAL for exactly this reason."
    )
    # Tier D is intact and untouched.
    durable = store.durable()
    kept = durable.query(statement(
        "SELECT COUNT(*) FROM label WHERE cohort_id = 'c-purge'", issue=ISSUE))
    assert kept[0][0] == 1, "TC-STORE-11: Tier D must survive the purge — it is the promoted copy"


def test_tc_store_11_a_blob_shared_by_two_cohorts_survives_the_first_purge(tmp_data_dir):
    """The §7.4 variant, asserted against the rule #225 declares: purge reclaims the
    cohort's blobs **by evidence** — a blob referenced from another cohort's rows survives
    that cohort's purge, and is unlinked once nothing references it anymore."""
    store = open_store(tmp_data_dir)
    blob_store = store.blobs()
    shared = blob_store.put(b"page-raster-shared-by-two-cohorts")
    _seed_cohort(store, "c-a", with_sentinel=False)
    _seed_cohort(store, "c-b", with_sentinel=False)
    for cohort_id in ("c-a", "c-b"):
        handle = store.cohort(cohort_id)
        with handle.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO document (document_id, submission_id, content_hash) "
                f"VALUES ('d-{cohort_id}', 's-{cohort_id}', '{shared}')", issue=ISSUE))
    _promote(store, "c-a")
    _promote(store, "c-b")

    report_a = store.purge_cohort("c-a")
    assert report_a.blobs_deleted == 0, (
        "TC-STORE-11: c-b's rows still reference the shared hash, and purge's scan of "
        "the surviving databases must see them — deleting the blob here would break a "
        "cohort mid-life (CT-STORE-07's lifetime promise)."
    )
    assert blob_store.path(shared).exists(), (
        "TC-STORE-11: the shared blob file did not survive a purge whose cohort was not "
        "its last referencer."
    )
    report_b = store.purge_cohort("c-b")
    assert report_b.blobs_deleted == 1, (
        "TC-STORE-11: with both cohorts purged nothing references the hash anymore, so "
        "the blob must be reclaimed — leaving it would be student bytes outliving every "
        "purge that should have removed them."
    )
    assert not blob_store.path(shared).exists(), (
        "TC-STORE-11: the blob file outlived its last referencing cohort's purge."
    )


def test_sec_13_after_purge_student_text_is_unrecoverable_and_tier_d_is_pseudonymized(
    tmp_data_dir,
):
    """`SEC-13` — the retention probe, composed: purge a cohort, then scan the raw file bytes
    and the blob directory for the sentinel, and sweep Tier D's schema for name-mapped
    columns. The purge half reuses `TC-STORE-11`'s mechanics; the sweep half is
    `TC-STORE-12`'s third limb, re-run here because the security case is the named home for
    the combined claim."""
    store = open_store(tmp_data_dir)
    blob_store = store.blobs()
    sentinel_hash = blob_store.put(f"raster-for-c-sec {SENTINEL}".encode())
    _seed_cohort(store, "c-sec")
    # The sentinel must be referenced by a cohort row: the rule #225 declares reclaims
    # blobs the cohort's rows name, so an orphan blob would be nobody's to reclaim.
    handle = store.cohort("c-sec")
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO document (document_id, submission_id, content_hash) "
            f"VALUES ('d-c-sec', 's-c-sec', '{sentinel_hash}')", issue=ISSUE))
    _promote(store, "c-sec")

    store.purge_cohort("c-sec")

    cohort_path = store.cohort_path("c-sec")
    assert SENTINEL.encode() not in cohort_path.read_bytes()
    # The blob half, post-#225: the sentinel is referenced by a document row of the purged
    # cohort and by nothing else in this data directory, so purge reclaims it — student
    # bytes no longer outlive the purge that removed their last reference.
    surviving = [
        blob_file for blob_file in sorted((tmp_data_dir / "blobs").rglob("*"))
        if blob_file.is_file() and SENTINEL.encode() in blob_file.read_bytes()
    ]
    assert surviving == [], (
        f"SEC-13: the sentinel blob survived the purge: {surviving}. Purge reclaims the "
        "blobs the cohort's rows referenced (#225); leaving student bytes behind is the "
        "failure this probe exists to catch."
    )
    durable_path = store.durable_path()
    offenders = []
    for table in sorted(table_names(durable_path)):
        if table.startswith("sqlite_") or table == "schema_version":
            continue
        for column in column_names(durable_path, table):
            if is_student_name_column(column):
                offenders.append(f"{table}.{column}")
    assert not offenders, (
        f"SEC-13: Tier D declares student-name column(s) ({', '.join(offenders)}). The "
        "permanent tier is the one purge never touches — a name there outlives every "
        "retention control in the system (RISK-21)."
    )


def test_225_purge_refuses_a_file_whose_fk_graph_contradicts_the_order(tmp_data_dir):
    """#225's durability demand, asserted against its own refusal branch: the sweep order
    is checked against the file's **live** `pragma foreign_key_list` graph before the
    first DELETE, so a migration that extends the cohort tier without extending
    `_COHORT_PURGE_ORDER` refuses with the edge named instead of aborting at COMMIT with
    a raw IntegrityError (the shape the F8 probe produced). The crafted file carries only
    names the sweep knows, with one edge inverted — the shipped graph has `roster`
    referencing `cohort`, this one has `cohort` referencing `roster`, which puts the
    child after its parent in the order tuple."""
    store = open_store(tmp_data_dir)
    cohort_path = tmp_data_dir / "cohorts" / "c-fk.sqlite"
    cohort_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(cohort_path) as raw:
        raw.execute(
            "CREATE TABLE roster ("
            " cohort_id TEXT NOT NULL, student_ref TEXT NOT NULL,"
            " PRIMARY KEY (cohort_id, student_ref))"
        )
        raw.execute(
            "CREATE TABLE cohort ("
            " cohort_id TEXT NOT NULL PRIMARY KEY REFERENCES roster(student_ref),"
            " consent_class TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        raw.execute("INSERT INTO roster VALUES ('c-fk', 'ref-1')")
        raw.execute("INSERT INTO cohort VALUES ('c-fk', 'consented', '2026-01-01')")
        raw.commit()
    _promote(store, "c-fk")

    with pytest.raises(Exception) as refused:
        store.purge_cohort("c-fk")
    assert type(refused.value).__name__ == "ConfigurationProblem", (
        f"#225: a contradicted FK graph refused with "
        f"{type(refused.value).__name__}, not ConfigurationProblem — the assertion's "
        "whole point is a named refusal before the first DELETE, not a late abort."
    )
    assert "cohort references roster" in str(refused.value), (
        f"#225: the refusal must name the edge it refused, got: {refused.value}"
    )
    # Zero partial effects: the refusal fired before the sweep's first DELETE.
    with sqlite3.connect(cohort_path) as raw:
        assert raw.execute("SELECT COUNT(*) FROM cohort").fetchone()[0] == 1, (
            "#225: the refused purge removed rows — the honest-refusal shape requires "
            "zero partial effects."
        )
        assert raw.execute("SELECT COUNT(*) FROM roster").fetchone()[0] == 1
