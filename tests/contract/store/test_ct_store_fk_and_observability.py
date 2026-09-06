"""`CT-STORE-13` and `CT-STORE-17` — FK enforcement everywhere, and named signals.

Cases `TC-STORE-C13` and `TC-STORE-C17`, test plan §6.11.3. Issue #17 (TS-60).

Rung 2. C13's loss mode is the lazy connection: the pragma is per-connection, and the
connections opened *after* open — on other threads, after a reopen — are where it usually
disappears. C17's oracle is exact names plus unit semantics (free-disk is bytes-remaining,
queue-depth is a gauge).

`Written ahead of implementation: yes` is stale; green by design.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from aeh.store import store_metrics
from tests.support.store_api import open_store, statement

pytestmark = pytest.mark.contract

ISSUE = "#17"


def test_tc_store_c13_foreign_keys_are_on_for_every_connection_including_lazy_ones(
    tmp_data_dir,
):
    """`TC-STORE-C13` — *'assert foreign_keys enforcement is on for every connection —
    including connections opened lazily, on other threads, and after a reopen.'*

    Three connections exercised: the opening thread's, a second thread's lazy read
    connection, and a reopen's. Each proves the pragma by *behavior* — a violating write
    fails — because a pragma query asserts the setting while behavior asserts the effect."""
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-c13")
    with handle.transaction() as tx:
        tx.execute(statement(
            "CREATE TABLE c13_parent (id TEXT PRIMARY KEY)", issue=ISSUE))
        tx.execute(statement(
            "CREATE TABLE c13_child (parent_id TEXT NOT NULL "
            "REFERENCES c13_parent(id))", issue=ISSUE))
        tx.execute(statement("INSERT INTO c13_parent VALUES ('p1')", issue=ISSUE))

    def second_thread_write() -> str:
        try:
            with handle.transaction() as tx:
                tx.execute(statement(
                    "INSERT INTO c13_child VALUES ('no-such-parent')", issue=ISSUE))
            return "no error"
        except Exception as error:  # noqa: BLE001 -- the shape of the failure IS the assertion
            return type(error).__name__

    outcome: dict[str, str] = {}
    thread = threading.Thread(target=lambda: outcome.setdefault("second", second_thread_write()))
    thread.start()
    thread.join(timeout=30)
    assert outcome.get("second") == "IntegrityError", (
        f"TC-STORE-C13: a lazy second-thread connection accepted an FK-violating write "
        f"({outcome.get('second')!r}). The pragma is per-connection, and the connections "
        "opened after open — other threads, reopens — are where it is usually lost. A "
        "pragma lost there converts every DDL constraint into a convention."
    )
    store.close()

    reopened = open_store(tmp_data_dir)
    reopened_handle = reopened.cohort("c-c13")
    with pytest.raises(sqlite3.IntegrityError):
        with reopened_handle.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO c13_child VALUES ('still-no-parent')", issue=ISSUE))
    reopened.close()


def test_tc_store_c13_constraint_violations_fail_the_write(tmp_data_dir):
    """C13's second limb: a CHECK and an FK violation each **fail the write** — the DDL's
    constraints are real guarantees (the clause), not advice caught downstream."""
    store = open_store(tmp_data_dir)
    handle = store.cohort("c-c13b")
    with pytest.raises(sqlite3.IntegrityError):
        with handle.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO cohort (cohort_id, consent_class, created_at) "
                "VALUES ('c-c13b', 'not-a-consent-class', '2026-01-01')", issue=ISSUE))
    with pytest.raises(sqlite3.IntegrityError):
        with handle.transaction() as tx:
            tx.execute(statement(
                "INSERT INTO document (document_id, submission_id, content_hash) "
                "VALUES ('d-orph', 'no-such-submission', 'h')", issue=ISSUE))
    store.close()


def test_tc_store_c17_the_five_signals_are_emitted_under_their_names(tmp_data_dir):
    """`TC-STORE-C17` — *'write-queue depth, batch commit latency, database file sizes, free
    disk space and VACUUM duration are emitted under those exact names.'* The names are the
    vocabulary `STORE_SIGNALS` pins; the assertion here is presence by exact name plus the
    two alert inputs' units."""
    store = open_store(tmp_data_dir)
    store.durable()
    metrics = store_metrics(store)
    from tests.support.store_vocabulary import STORE_SIGNALS

    missing = [name for name in STORE_SIGNALS if name not in metrics]
    assert not missing, (
        f"TC-STORE-C17: signals missing under their contract names: {missing}. Ops and "
        "M-ORCH read them by name; an inverted or renamed alert input is indistinguishable "
        "from a healthy system (RISK-35)."
    )
    # Unit semantics: free-disk is bytes-remaining (a real reading, not a percent), and
    # queue-depth is a gauge (an int level, present and bounded by the configured depth).
    free = metrics["free_disk_bytes"]
    assert isinstance(free, int) and free > 1024 ** 3, (
        f"TC-STORE-C17: free_disk_bytes = {free!r}. The contract unit is bytes-remaining — "
        "a percentage or a bool would invert the alert's meaning on a large disk."
    )
    depth = metrics["write_queue_depth"]
    assert isinstance(depth, int) and 0 <= depth <= store.limits.write_queue_depth, (
        f"TC-STORE-C17: write_queue_depth = {depth!r}. The alert input is a gauge — an "
        "int level bounded by the configured depth, not a counter that only grows."
    )
    store.close()
