"""The store's floors: throughput, zero-install smoke, capacity, configurable data dir.

Cases `TC-STORE-17`, `TC-STORE-19`, `TC-STORE-20`, `TC-STORE-23` (`NFR-STORE-01`, `-03`,
`-05`, `-06`), test plan §5.3. Issue #16 (TS-10).

Rung 2 — real store, real writes, real bytes on disk. `TC-STORE-17`'s 60-second reference run
and `TC-STORE-20`'s full 350-student fill are the plan's E1-hardware figures; here they are
**knob-scaled** (`CLAUDE.md` seam 3) so CI asserts the same thresholds at CI-scale, the
duration knob can raise them to reference scale, and `TC-STORE-20`'s full fill is `slow`-
marked so it runs on demand rather than on every tier. The actual measured figures are always
reported — `NFR-STORE-06`'s 500 MB is an Assumption the test exists to revisit, not a number
to defend.

`Written ahead of implementation: yes` is stale — the store landed with #10-#13; the cases
run green by design.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from aeh.store import store_metrics
from tests.support.store_api import open_store, statement

pytestmark = [pytest.mark.integration]

ISSUE = "#16"

REPO_SRC = Path(__file__).resolve().parents[3] / "src"

#: `TC-STORE-17`: seconds of sustained writing. The reference figure is 60 s on E1 hardware
#: (`PERF-05` owns that run); CI asserts the same rate floor at knob-scaled duration.
PERF_SECONDS = int(os.environ.get("HARNESS_TEST_PERF_SECONDS", "2"))
RATE_FLOOR = 200  # units/second — NFR-STORE-01, "at least 200 write units/second"

#: `TC-STORE-20`: students in the synthetic fill. 350 is the reference run; the knob exists
#: for a constrained box (the full-scale case is `slow`-marked in any case).
CAPACITY_STUDENTS = int(os.environ.get("HARNESS_TEST_CAPACITY_STUDENTS", "350"))
CAPACITY_LIMIT_BYTES = 500 * 1024 * 1024  # NFR-STORE-06's Assumption, under


def test_tc_store_17_two_hundred_write_units_per_second_sustained(tmp_data_dir, monkeypatch):
    """`TC-STORE-17` — *"200 write units per second sustained ... without queue growth."*

    Oracle: **metric threshold**. The rate is measured over the whole run — first enqueue to
    drained queue — so batching amortization cannot flatter it, and the queue's depth is
    asserted back to zero at the end: a store that wrote 400 units and left 300 pending met
    nothing. The 60-second E1 run is `PERF-05`'s; this case holds the same floor at CI
    scale, and `HARNESS_TEST_PERF_SECONDS` raises the duration to reference scale."""
    monkeypatch.setenv("HARNESS_COMMIT_BATCH", "100")
    monkeypatch.setenv("HARNESS_COMMIT_INTERVAL_MS", "100")
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-perf")
    with handle.transaction() as tx:
        tx.execute(statement(
            "CREATE TABLE perf_rows (unit_no INTEGER NOT NULL, payload TEXT NOT NULL)",
            issue=ISSUE))
    insert = statement(
        "INSERT INTO perf_rows (unit_no, payload) VALUES (:unit_no, :payload)", issue=ISSUE)

    total = RATE_FLOOR * PERF_SECONDS + RATE_FLOOR  # a margin over the floor's worth
    started = time.perf_counter()
    for index in range(total):
        handle.enqueue_write(insert, unit_no=index, payload=f"p{index % 64}")
    deadline = time.perf_counter() + 120
    while int(store_metrics(store)["write_queue_depth"]) > 0:
        if time.perf_counter() >= deadline:
            break
        time.sleep(0.01)
    elapsed = time.perf_counter() - started
    rate = total / elapsed

    assert rate >= RATE_FLOOR, (
        f"TC-STORE-17: sustained {rate:.0f} units/s over {elapsed:.1f}s; the floor is "
        f"{RATE_FLOOR}/s (NFR-STORE-01). A store slower than the floor is the bottleneck the "
        "design says persistence must never be — ~23,000 units over hours has an order of "
        "magnitude of headroom against this number."
    )
    assert int(store_metrics(store)["write_queue_depth"]) == 0, (
        "TC-STORE-17: the queue did not drain. Sustained throughput with a growing queue is "
        "deferred failure, not throughput."
    )
    rows = handle.query(statement("SELECT COUNT(*) FROM perf_rows", issue=ISSUE))
    assert rows[0][0] == total, (
        f"TC-STORE-17: {rows[0][0]} of {total} rows landed. Throughput measured against "
        "rows that did not survive is not throughput."
    )


def test_tc_store_19_a_clean_environment_needs_only_the_data_dir(tmp_data_dir, tmp_path):
    """`TC-STORE-19` — *"A clean virtualenv on a clean machine: the store initializes with only
    `HARNESS_DATA_DIR` set — no server process, no separate install step, no further
    configuration."*

    Oracle: **exact success** — a subprocess whose environment carries nothing but the OS
    minimum and `HARNESS_DATA_DIR` opens the store, writes a row through a transaction, reads
    it back, and exits 0. No config file, no server to start, no initialization step before
    the first write."""
    data_dir = tmp_data_dir / "clean"
    env = {
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", str(tmp_path)),
        "TMP": os.environ.get("TMP", str(tmp_path)),
        "HARNESS_DATA_DIR": str(data_dir),
        "PYTHONPATH": str(REPO_SRC),
    }
    child = (
        "from aeh.store import Statement, open_store\n"
        "# TC-STORE-25: the migration chains concatenate at import time, so a fresh process\n"
        "# imports every contributing module before the first open (#234). aeh.judge owns\n"
        "# Cohort's last migration (14, #78), so the convention's line has seven modules now.\n"
        "import aeh.det, aeh.extract, aeh.ingest, aeh.judge, aeh.orch, aeh.pkg, aeh.synth  # noqa: E401\n"
        "store = open_store()  # no argument: HARNESS_DATA_DIR or refusal\n"
        "handle = store.durable()\n"
        "with handle.transaction() as tx:\n"
        "    tx.execute(Statement('INSERT INTO run_metrics (run_id, metric, value) "
        "VALUES (:r, :m, :v)'), r='smoke', m='boot', v=1.0)\n"
        "rows = handle.query(Statement('SELECT value FROM run_metrics WHERE metric = \\'boot\\''))\n"
        "assert len(rows) == 1 and rows[0][0] == 1.0\n"
        "store.close()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", child], env=env, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        f"TC-STORE-19: the clean-environment store failed to initialize.\n"
        f"stderr: {result.stderr[-800:]}\n"
        "NFR-STORE-03: no server process, no separate installation step, no configuration "
        "beyond a data directory path. Anything the store needs beyond HARNESS_DATA_DIR is a "
        "finding against that clause."
    )
    assert (data_dir / "durable.sqlite").exists()


@pytest.mark.slow
def test_tc_store_20_a_full_scale_run_fits_under_the_capacity_assumption(tmp_data_dir):
    """`TC-STORE-20` — *"A full 350-student run's rows plus blobs: total on-disk footprint
    under 500 MB; the actual figure is reported so the Assumption can be revisited."*

    Oracle: **metric threshold, with the figure reported**. The fill is synthetic at
    reference proportions (HLD §9.12: ~23,000 work units per 350-student run, page rasters
    dominating the bytes), through the store's own write paths. Slow-marked: ~200 MB of
    rasters does not belong in an every-push tier; `HARNESS_TEST_CAPACITY_STUDENTS` scales
    the fill for a constrained box, and the printed figure is what revisits the Assumption —
    a pass that says nothing about where under 500 MB the store landed says nothing."""
    store = open_store(tmp_data_dir)
    blobs = store.blobs()
    handle = store.cohort("c-capacity")

    # ~200 KB per page raster, rasters dominate per §9.12 — and every raster is
    # student-distinct, because content addressing deduplicates identical bytes and a fill
    # whose 1,050 rasters collapse to 3 files measures nothing about the dominant data
    # class (review, B1: the first draft read 8.7 MB; distinct rasters read ~223 MB).
    raster = bytes(range(256)) * 800
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES ('c-capacity', 'consented', '2026-01-01T00:00:00Z')", issue=ISSUE))
    units_per_student = 65  # HLD §9.12's ~23,000 units across 350 students
    for student in range(CAPACITY_STUDENTS):
        student_ref = f"ref-{student:05d}"
        submission = f"s-{student:05d}"
        with handle.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO roster (cohort_id, student_ref) "
                "VALUES ('c-capacity', :student_ref)", issue=ISSUE), student_ref=student_ref)
            tx.execute(statement(
                "INSERT INTO submission (submission_id, cohort_id, student_ref) "
                "VALUES (:submission, 'c-capacity', :student_ref)", issue=ISSUE),
                submission=submission, student_ref=student_ref)
            tx.execute(statement(
                "INSERT INTO document (document_id, submission_id, content_hash) "
                "VALUES (:document, :submission, :content_hash)", issue=ISSUE),
                document=f"d-{student:05d}", submission=submission,
                content_hash=f"hash-{student:05d}")
            for page in range(1, 4):
                blobs.put(raster + bytes([page % 256, student % 256, (student >> 8) % 256]))
                tx.execute(statement(
                    "INSERT INTO document_region (region_id, document_id, page_no, element_kind) "
                    "VALUES (:region, :document, :page_no, 'text')", issue=ISSUE),
                    region=f"r-{student:05d}-{page}", document=f"d-{student:05d}",
                    page_no=page)
        with handle.transaction() as tx:
            for unit in range(units_per_student):
                tx.execute(statement(
                    "INSERT INTO work_unit (work_id, submission_id, stage, status) "
                    "VALUES (:work_id, :submission, 'judge', 'done')", issue=ISSUE),
                    work_id=f"w-{student:05d}-{unit:03d}", submission=submission)
                tx.execute(statement(
                    "INSERT INTO evidence (evidence_id, work_id, document_id) "
                    "VALUES (:evidence, :work_id, :document)", issue=ISSUE),
                    evidence=f"e-{student:05d}-{unit:03d}",
                    work_id=f"w-{student:05d}-{unit:03d}", document=f"d-{student:05d}")
                tx.execute(statement(
                    "INSERT INTO verdict (verdict_id, work_id, judge_id, band) "
                    "VALUES (:verdict, :work_id, 'judge-1', 'b1')", issue=ISSUE),
                    verdict=f"v-{student:05d}-{unit:03d}",
                    work_id=f"w-{student:05d}-{unit:03d}")

    total_bytes = sum(
        f.stat().st_size for f in tmp_data_dir.rglob("*") if f.is_file()
    )
    print(
        f"\nTC-STORE-20: {CAPACITY_STUDENTS} students -> {total_bytes / (1024 * 1024):.1f} MB "
        f"on disk (limit {CAPACITY_LIMIT_BYTES // (1024 * 1024)} MB, NFR-STORE-06's Assumption)"
    )
    store.close()
    assert total_bytes < CAPACITY_LIMIT_BYTES, (
        f"TC-STORE-20: a {CAPACITY_STUDENTS}-student fill occupies "
        f"{total_bytes / (1024 * 1024):.1f} MB — over NFR-STORE-06's 500 MB Assumption. The "
        "figure is reported either way; the Assumption exists to be revisited with data."
    )


def test_tc_store_23_the_data_directory_is_configurable(tmp_data_dir):
    """`TC-STORE-23` — the automatable half. Encryption at rest itself is §2.3 Q-08's
    deployment-checklist item (test plan §7.4: not automatable, accepted risk on device
    theft); what the store *can* assert is that the data directory path is configurable —
    the property that lets an operator place the data on an encrypted volume."""
    elsewhere = tmp_data_dir / "elsewhere"
    from aeh.store import open_store as store_opener

    by_env = store_opener(environ={"HARNESS_DATA_DIR": str(elsewhere)})
    by_env.durable()
    by_env.close()
    assert (elsewhere / "durable.sqlite").exists(), (
        "TC-STORE-23: HARNESS_DATA_DIR did not place the store. NFR-STORE-05's control is "
        "deployment-side (place the data on an encrypted volume); the configurability of the "
        "path is the store-side half of that control, and it is the only automatable claim."
    )
    direct = store_opener(tmp_data_dir / "direct")
    direct.durable()
    direct.close()
    assert (tmp_data_dir / "direct" / "durable.sqlite").exists()
