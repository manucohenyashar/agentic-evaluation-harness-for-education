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

The blob variant implements the rule **declared**, not the one §7.4 left open: purge does not
touch the blob directory (`PurgeReport.blobs_deleted` is a documented honest zero, and the
dedup-vs-purge question is an accepted risk pending a design decision). The variant asserts
the consequence a consumer can rely on today — a blob shared by two cohorts survives either
cohort's purge — and the PR records that a change to the declared rule rewrites this case.
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


def test_tc_store_11_a_blob_shared_by_two_cohorts_survives_either_purge(tmp_data_dir):
    """The §7.4 variant, asserted against the **declared** rule: purge does not touch the blob
    directory, so a blob referenced from both cohorts' rows survives both purges. A change to
    the declared rule rewrites this case — that is what the variant is for."""
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
        "TC-STORE-11: the declared rule (test plan §7.4's accepted risk, PurgeReport's "
        "documented honest zero) is that purge does not touch the blob directory. If that "
        "rule changes, this case and PurgeReport's docstring change with it."
    )
    store.purge_cohort("c-b")
    assert blob_store.get(shared) == b"page-raster-shared-by-two-cohorts", (
        "TC-STORE-11: the shared blob did not survive both purges. Whatever rule is declared, "
        "a blob another surviving cohort still references must resolve (CT-STORE-07's "
        "lifetime promise) — and per the declared rule, purge does not reclaim blobs at all."
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
    blob_store.put(f"raster-for-c-sec {SENTINEL}".encode())
    _seed_cohort(store, "c-sec")
    _promote(store, "c-sec")

    store.purge_cohort("c-sec")

    cohort_path = store.cohort_path("c-sec")
    assert SENTINEL.encode() not in cohort_path.read_bytes()
    # The blob half is the §7.4 accepted risk, pinned: the declared rule is that purge does
    # not touch the blob directory, so student bytes in a blob survive the purge that removed
    # their database rows. That is the "leaves student bytes behind" direction of the open
    # question, accepted because the alternative breaks another cohort's shared blobs. When
    # the design declares the rule, this assertion and PurgeReport's honest zero change with
    # it — the pin is what makes the gap visible instead of forgotten.
    surviving = [
        blob_file for blob_file in sorted((tmp_data_dir / "blobs").rglob("*"))
        if blob_file.is_file() and SENTINEL.encode() in blob_file.read_bytes()
    ]
    assert surviving, (
        "SEC-13: the sentinel blob is gone, but purge never reclaims blobs under the "
        "declared rule — it can only disappear if something else deleted it."
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
