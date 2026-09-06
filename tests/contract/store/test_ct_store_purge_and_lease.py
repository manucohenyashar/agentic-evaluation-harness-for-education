"""`CT-STORE-10`, `CT-STORE-14`, `CT-STORE-15` — purge, the lease clock, the floors.

Cases `TC-STORE-C10`, `TC-STORE-C14`, `TC-STORE-C15`, test plan §6.11.3. Issue #17 (TS-60).

Rung 2. C10's sweep is **exhaustive, not sampled** — the operation is irreversible and the
only one that deletes student work, so every precondition-missing state is visited. C14 is
the sweeper's trust, adversarially. C15 asserts the floors as pass/fail thresholds; the
500 MB half's full-scale fill is `TC-STORE-20`'s (slow-marked) — this case holds the
throughput threshold live and cites the capacity case for the footprint half rather than
writing 200 MB into a contract suite.

`Written ahead of implementation: yes` is stale; green by design.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from aeh.store import LeaseClock, PurgePreconditionError, open_store, store_metrics
from tests.support.clock import EPOCH, FrozenClock
from tests.support.store_api import open_store as api_open_store
from tests.support.store_api import statement

pytestmark = pytest.mark.contract

ISSUE = "#17"

PROMOTE = (
    "ALTER TABLE audit_record ADD COLUMN cohort_id TEXT",
    "ALTER TABLE label ADD COLUMN cohort_id TEXT",
    "ALTER TABLE criterion_stats ADD COLUMN cohort_id TEXT",
)

#: The three gates `CT-STORE-10` names, in its words — swept exhaustively below.
GATES = ("audit records", "labels", "per-criterion statistics")


def _promote_all(store, cohort_id: str, *, skip: int = -1) -> None:
    """Give Tier D all three promotion gates except `skip` (by index), via an independent
    connection — the owning module's ALTER+INSERT shape, per the TC-STORE-12 precedent."""
    store.durable()
    with sqlite3.connect(store.durable_path()) as raw:
        for index, ddl in enumerate(PROMOTE):
            if index == skip:
                continue
            try:
                raw.execute(ddl)
            except sqlite3.OperationalError as error:
                if "duplicate column" not in str(error).lower():
                    raise
        if 0 != skip:
            raw.execute(
                "INSERT INTO audit_record (audit_record_id, run_id, recorded_at, "
                "profile_summary, cohort_id) VALUES (?, 'r', 't', 'p', ?)",
                (f"a-{cohort_id}-{skip}", cohort_id))
        if 1 != skip:
            raw.execute(
                "INSERT INTO label (label_id, run_id, student_ref, criterion_id, label_type, "
                "band, cohort_id) VALUES (?, 'r', 'ref', 'c', 'human', 'b', ?)",
                (f"l-{cohort_id}-{skip}", cohort_id))
        if 2 != skip:
            raw.execute(
                "INSERT INTO criterion_stats (package_version_id, criterion_id, "
                "backend_profile, panel_build_ref, n, cohort_id) "
                "VALUES (?, 'c', 'bp', ?, 1, ?)", (f"pv-{cohort_id}-{skip}",
                                                   f"pb-{cohort_id}-{skip}", cohort_id))


def test_tc_store_c10_every_missing_precondition_refuses_and_deletes_nothing(tmp_data_dir):
    """`TC-STORE-C10` — the precondition sweep, **exhaustive in both directions**: each gate
    missing alone (the other two promoted — the state the clause's sentence describes) and
    none promoted. Every failing state raises `PurgePreconditionError` and leaves the cohort
    file byte-identical; the naming says exactly which gates are unmet — no more, no fewer.
    Each state runs in its OWN store directory — Tier D is permanent, so a durable file
    shared across states would accumulate promotions and the sweep would be asserting
    against blurred states."""
    for missing in (-1, 0, 1, 2):  # -1 = nothing promoted; k = only gate k missing
        data_dir = tmp_data_dir / f"state-{missing}"
        store = api_open_store(data_dir)
        handle = store.cohort("s-c10")
        with handle.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO cohort (cohort_id, consent_class, created_at) "
                "VALUES ('s-c10', 'consented', '2026-01-01')", issue=ISSUE))
        store.durable()
        for index, ddl in enumerate(PROMOTE):
            if missing == -1 or index == missing:
                continue  # the gate this state leaves unmet (-1: all of them)
            with sqlite3.connect(store.durable_path()) as raw:
                try:
                    raw.execute(ddl)
                except sqlite3.OperationalError as error:
                    if "duplicate column" not in str(error).lower():
                        raise
                if index == 0:
                    raw.execute(
                        "INSERT INTO audit_record (audit_record_id, run_id, recorded_at, "
                        "profile_summary, cohort_id) VALUES (?, 'r', 't', 'p', 's-c10')",
                        (f"a-{missing}",))
                elif index == 1:
                    raw.execute(
                        "INSERT INTO label (label_id, run_id, student_ref, criterion_id, "
                        "label_type, band, cohort_id) VALUES (?, 'r', 'ref', 'c', 'human', "
                        "'b', 's-c10')", (f"l-{missing}",))
                else:
                    raw.execute(
                        "INSERT INTO criterion_stats (package_version_id, criterion_id, "
                        "backend_profile, panel_build_ref, n, cohort_id) "
                        "VALUES (?, 'c', 'bp', ?, 1, 's-c10')", (f"pv-{missing}",
                                                                 f"pb-{missing}"))
        path = store.cohort_path("s-c10")
        before = path.read_bytes()
        with pytest.raises(PurgePreconditionError) as refused:
            store.purge_cohort("s-c10")
        assert path.read_bytes() == before, (
            f"TC-STORE-C10 (missing={missing}): the refusal touched the cohort file. The "
            "clause's state assertion is 'nothing deleted', per failing case."
        )
        named = str(refused.value)
        for index, gate in enumerate(GATES):
            unmet = missing == -1 or index == missing
            if unmet:
                assert gate in named, (
                    f"TC-STORE-C10 (missing={missing}): the refusal does not name the unmet "
                    f"gate {gate!r}. An operator fixing gates one at a time needs the list."
                )
            else:
                assert gate not in named, (
                    f"TC-STORE-C10 (missing={missing}): the refusal names {gate!r}, which "
                    "this state promoted. Naming a met gate misdirects the operator."
                )
        store.close()

    # The happy path: everything promoted — the purge deletes, and the oracle is the
    # plan's byte-level one: a distinctive payload's bytes are gone from the cohort file
    # AND its -wal, not merely unreferenced. A purge that skipped its VACUUM leaves the
    # text recoverable in freed pages, which is the exact failure the clause names.
    store = api_open_store(tmp_data_dir / "happy")
    handle = store.cohort("s-c10")
    sentinel = b"CT-STORE-C10-student-text-4b7e"
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES ('s-c10', 'consented', '2026-01-01')", issue=ISSUE))
        tx.execute(statement(
            "INSERT INTO roster (cohort_id, student_ref) VALUES ('s-c10', ?)".replace(
                "?", f"'{sentinel.decode()}'"), issue=ISSUE))
    _promote_all(store, "s-c10")
    report = store.purge_cohort("s-c10")
    assert report.tables_cleared and report.rows_deleted_by_table["cohort"] == 1
    assert report.vacuum_duration_ms > 0.0
    path = store.cohort_path("s-c10")
    assert sentinel not in path.read_bytes(), (
        "TC-STORE-C10: the payload is recoverable from the cohort file's raw bytes after "
        "the purge. CT-STORE-10's oracle is byte-level file verification — a DELETE without "
        "VACUUM leaves student text in freed pages, which is why the clause names VACUUM."
    )
    wal = path.with_name(path.name + "-wal")
    assert not wal.exists() or sentinel not in wal.read_bytes(), (
        "TC-STORE-C10: the payload survives in the -wal. Freed pages sit there until a "
        "checkpoint reclaims them; purge truncates the WAL for exactly this reason."
    )
    store.close()


def test_tc_store_c14_the_sweeper_trusts_expiry_across_a_backwards_jump(tmp_data_dir):
    """`TC-STORE-C14` — *'Move the wall clock backwards across a restart and assert an
    expired lease still compares as expired.'* The invariant is the sweeper's decision,
    under the adversarial clock, across a real persisted restore."""
    clock = FrozenClock(start=EPOCH)
    store = api_open_store(tmp_data_dir)
    lease_clock = LeaseClock(store, clock=clock)
    lease = lease_clock.issue(ttl_seconds=30.0)
    clock.advance(60)
    store.close()

    clock.set_wall_clock(EPOCH - __import__("datetime").timedelta(hours=1))  # the correction
    reopened = api_open_store(tmp_data_dir)
    restored = LeaseClock(reopened, clock=clock)
    assert restored.expired(lease) is True, (
        "TC-STORE-C14: after a backwards wall-clock correction across a restart, an expired "
        "lease compares as live. A 'simplification' to datetime.now() duplicates or strands "
        "exactly the work M-ORCH's sweeper is deciding about — silently."
    )
    assert restored.ticks() >= lease.expires_ticks
    reopened.close()


def test_tc_store_c15_the_throughput_floor_holds_as_a_threshold(tmp_data_dir):
    """`TC-STORE-C15` — the throughput floor as **pass/fail against the figure**, so a
    loosened bound (RISK-33) must edit the number in review. The footprint half of the
    clause (350 students under 500 MB including blobs) is `TC-STORE-20`'s full-scale,
    slow-marked run — referenced, not duplicated: this case holds the threshold CI can
    measure in seconds."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("HARNESS_COMMIT_BATCH", "100")
    monkeypatch.setenv("HARNESS_COMMIT_INTERVAL_MS", "100")
    try:
        store = api_open_store(tmp_data_dir)
        handle = store.cohort("s-c15")
        with handle.transaction() as tx:
            tx.execute(statement(
                "CREATE TABLE c15_rows (n INTEGER)", issue=ISSUE))
        insert = statement("INSERT INTO c15_rows VALUES (:n)", issue=ISSUE)
        total = 600
        started = time.perf_counter()
        for index in range(total):
            handle.enqueue_write(insert, n=index)
        deadline = time.perf_counter() + 60
        while int(store_metrics(store)["write_queue_depth"]) > 0 and time.perf_counter() < deadline:
            time.sleep(0.01)
        elapsed = time.perf_counter() - started
        assert total / elapsed >= 200, (
            f"TC-STORE-C15: {total / elapsed:.0f} units/s; the clause holds at least 200 "
            "on the reference hardware and this threshold is where a loosened bound has to "
            "be edited in review."
        )
        store.close()
    finally:
        monkeypatch.undo()
