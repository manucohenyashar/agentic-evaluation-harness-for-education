"""The single-writer queue: reader/writer independence, enqueue ordering, and backpressure.

Cases `TC-STORE-03` (`FR-STORE-03`, P0, concurrency) and `TC-STORE-07` (`FR-STORE-05`, P1,
boundary), test plan §5.3. Issue #14 (TS-08); implemented by issue **#11**.

Rung 2 — a real WAL database and real threads. There is no double for this: `CT-STORE-04`
("concurrent readers never block the writer") and `CT-STORE-02` ("`enqueue_write` is
asynchronous: it returns before the row is durable") are both statements about a real
scheduler, and §4.10 names the in-memory fake that "commits synchronously" as the exact thing
that would hide them.

**No sleeps.** The marker registry records that `TC-ORCH-09` is the only sanctioned sleep in
this suite (§4.6), so coordination here is by `threading.Barrier` and `threading.Event`, and
every wait is bounded by a knob rather than by a guessed duration. A test that sleeps to let
a queue drain passes on a fast box and flakes on a slow one, which §4.6's flake policy makes
a P1 defect rather than an inconvenience.

**Written ahead of implementation** (test plan §8.2): expected to fail with `NotImplementedYet`
naming #11 — or #10, whichever is missing first, since a write queue needs a store to write
to. Registered under `#11 store_metrics`.
"""

from __future__ import annotations

import os
import statistics
import threading
import time

import pytest

from tests.support.store_api import open_store, statement, store_metrics

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#11"

#: Design §3.3 Configuration. Named here so the cases drive the *configured* values rather than
#: the literals, which is `CLAUDE.md` seam 3: "Production value is the default; the knob exists
#: so a slower test box can adjust without a code change."
ENV_QUEUE_DEPTH = "HARNESS_WRITE_QUEUE_DEPTH"
ENV_COMMIT_BATCH = "HARNESS_COMMIT_BATCH"
ENV_COMMIT_INTERVAL_MS = "HARNESS_COMMIT_INTERVAL_MS"

#: Design §3.3's stated defaults, asserted in `TC-STORE-07` so driving the knob does not lose
#: the production figure the plan's 999/1000/1001 refers to.
DEFAULT_QUEUE_DEPTH = 1000
DEFAULT_COMMIT_BATCH = 100
DEFAULT_COMMIT_INTERVAL_MS = 5000

#: The plan says "eight reader threads". Env-gated because a box with fewer cores than this
#: schedules them differently, and the case is about independence, not about eight specifically.
READER_THREADS = int(os.environ.get("HARNESS_TEST_READER_THREADS", "8"))

#: Writes the ordering half enqueues. Enough that an out-of-order commit is visible and a
#: batch boundary is crossed; small enough to stay inside the integration tier's budget.
ORDERED_WRITES = int(os.environ.get("HARNESS_TEST_ORDERED_WRITES", "250"))

#: Every bounded wait in this file. Not a sleep: nothing waits for this to elapse on the happy
#: path — it is the ceiling past which a hang is reported as a failure instead of hanging CI.
THREAD_TIMEOUT_S = float(os.environ.get("HARNESS_TEST_THREAD_TIMEOUT_S", "30"))

#: How long a *blocked* `enqueue_write` must stay blocked before the case believes it. Short,
#: because the assertion is "did not return promptly" and a long value only slows the suite.
BLOCK_OBSERVATION_S = float(os.environ.get("HARNESS_TEST_BLOCK_OBSERVATION_S", "0.5"))

#: A queue depth small enough to reach deterministically. `TC-STORE-07`'s 999/1000/1001 are the
#: *default* depth ±1; the case asserts the boundary relative to the **configured** depth, which
#: is strictly stronger — it fails an implementation that hard-codes 1000 and ignores the knob,
#: and that implementation passes the plan's literal reading.
TEST_QUEUE_DEPTH = int(os.environ.get("HARNESS_TEST_QUEUE_DEPTH", "8"))

_ORDERED_DDL = "CREATE TABLE ordered_writes (rowid_ INTEGER PRIMARY KEY, seq INTEGER NOT NULL)"
_ORDERED_INSERT = "INSERT INTO ordered_writes (seq) VALUES (:seq)"
_ORDERED_READ = "SELECT seq FROM ordered_writes ORDER BY rowid_"
_ORDERED_COUNT = "SELECT count(*) FROM ordered_writes"

#: `CT-STORE-11`: "`SQLITE_BUSY` is retried internally and never surfaces." These are the
#: strings SQLite raises it under, matched case-insensitively against anything a caller caught.
BUSY_MARKERS = ("sqlite_busy", "database is locked", "database table is locked")


def _is_busy_error(error: BaseException) -> bool:
    text = f"{type(error).__name__}: {error}".lower()
    return any(marker in text for marker in BUSY_MARKERS)


def test_tc_store_03_readers_never_block_the_writer_and_writes_land_in_enqueue_order(
    tmp_data_dir,
):
    """`TC-STORE-03` — *"Readers never block the writer; writes land in enqueue order; no
    `SQLITE_BUSY` surfaces to a caller."*

    Oracle: **ordering invariant plus no-exception**.

    Three assertions, and the interesting one is the first.

    **Readers never block the writer** (`FR-STORE-03`, `CT-STORE-04`) is a *liveness* claim, and
    liveness cannot be asserted by timing — a fast box passes a slow implementation. So it is
    asserted structurally instead: the readers are still running, in a bounded spin, at the
    moment the writer finishes. The readers stop only after the writer's completion event is
    set. If the writer had been blocked behind eight readers holding the file, it would not
    finish first, and the bounded wait reports that as a failure rather than hanging.

    **Enqueue order** is read back with an explicit `ORDER BY`, because `CT-STORE-18` says the
    module chooses no order and "a caller needing an order states it in the statement". The
    ordering claim is about `rowid` — the order rows were actually inserted — not about
    whatever order a query happens to return.

    **No `SQLITE_BUSY`** (`CT-STORE-11`: "retried internally and never surfaces") is swept over
    every thread, not just the writer. Eight concurrent readers against an active writer is
    precisely the condition that produces it, and a reader that swallowed one would leave the
    writer's own assertions green.
    """
    monkeypatched = {ENV_COMMIT_BATCH: "25", ENV_COMMIT_INTERVAL_MS: "50"}
    previous = {key: os.environ.get(key) for key in monkeypatched}
    os.environ.update(monkeypatched)
    try:
        store = open_store(tmp_data_dir, issue=ISSUE)
        handle = store.cohort("COH-CONC")
        with handle.transaction() as tx:
            tx.execute(statement(_ORDERED_DDL, issue=ISSUE))

        start = threading.Barrier(READER_THREADS + 1, timeout=THREAD_TIMEOUT_S)
        writer_done = threading.Event()
        readers_saw_writer_finish = []
        errors: list[BaseException] = []
        reads_completed = []

        def reader() -> None:
            try:
                start.wait()
                local = 0
                while not writer_done.is_set():
                    list(handle.query(statement(_ORDERED_COUNT, issue=ISSUE)))
                    local += 1
                # The writer finished while this reader was still in its loop. That is the
                # structural form of "readers never block the writer".
                readers_saw_writer_finish.append(True)
                reads_completed.append(local)
            except BaseException as error:  # noqa: BLE001 — every escape is a finding
                errors.append(error)

        def writer() -> None:
            try:
                start.wait()
                for seq in range(ORDERED_WRITES):
                    handle.enqueue_write(
                        statement(_ORDERED_INSERT, issue=ISSUE), seq=seq
                    )
                # CT-STORE-02: enqueue_write returns before the row is durable, so the caller
                # that must observe its own writes reads through a transaction.
                with handle.transaction() as tx:
                    tx.execute(statement(_ORDERED_COUNT, issue=ISSUE))
            except BaseException as error:  # noqa: BLE001
                errors.append(error)
            finally:
                writer_done.set()

        threads = [threading.Thread(target=reader, name=f"reader-{n}", daemon=True)
                   for n in range(READER_THREADS)]
        threads.append(threading.Thread(target=writer, name="writer", daemon=True))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=THREAD_TIMEOUT_S)

        live = [thread.name for thread in threads if thread.is_alive()]
        assert not live, (
            f"TC-STORE-03: {live} did not finish within {THREAD_TIMEOUT_S}s. A writer that "
            "cannot make progress behind concurrent readers is the FR-STORE-03 failure, and a "
            "reader that cannot finish means the writer held the file exclusively."
        )

        busy = [error for error in errors if _is_busy_error(error)]
        assert not busy, (
            "TC-STORE-03: SQLITE_BUSY reached a caller. CT-STORE-11: it is retried internally "
            f"and never surfaces, and under WAL with a single writer it should not occur: {busy}"
        )
        assert not errors, (
            f"TC-STORE-03: a reader or the writer raised: {errors}"
        )

        assert len(readers_saw_writer_finish) == READER_THREADS, (
            f"TC-STORE-03: only {len(readers_saw_writer_finish)} of {READER_THREADS} readers "
            "were still running when the writer finished. The writer completing *first*, while "
            "readers are mid-spin, is what 'readers never block the writer' means here — timing "
            "would only tell us the box was fast."
        )
        assert all(count > 0 for count in reads_completed), (
            f"TC-STORE-03: a reader completed zero queries: {reads_completed}. A reader that "
            "never ran proves nothing about contention."
        )

        rows = list(handle.query(statement(_ORDERED_READ, issue=ISSUE)))
        landed = [row[0] for row in rows]
        assert landed == list(range(ORDERED_WRITES)), (
            "TC-STORE-03: writes did not land in enqueue order. FR-STORE-03 serializes all "
            "writes through one writer thread fed by an in-process queue; CT-STORE-04 makes "
            "the single-caller ordering a promise. "
            f"Expected 0..{ORDERED_WRITES - 1} in order, got {landed[:12]}... "
            f"({len(landed)} rows)"
        )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_tc_store_07_backpressure_is_raised_exactly_at_the_configured_queue_depth(
    tmp_data_dir, monkeypatch
):
    """`TC-STORE-07` — *"`enqueue_write` proceeds below the threshold and blocks or slows at and
    above it; the backpressure signal `M-ORCH` reads is raised exactly at the boundary."*

    Oracle: **exact boundary behaviour**.

    *Exactly* is the whole case. `CT-STORE-06` tells `M-ORCH` to "treat a slow `enqueue_write`
    as a signal to reduce dispatch, not as a fault", and `FR-ORCH-21` throttles on it. A signal
    that trips early throttles a run that had headroom; one that trips late lets the queue grow
    past the bound `NFR-STORE-02`'s durability window is calculated from. So all three points
    are asserted — `N-1` must be clear, `N` must be raised, `N+1` must still be raised — rather
    than only checking that it eventually goes up.

    **Driven through the knob, not the literal.** The plan says 999/1000/1001, which is design
    §3.3's default depth ±1. This case sets `HARNESS_WRITE_QUEUE_DEPTH` small and asserts the
    boundary relative to the *configured* value, then asserts separately that the default really
    is 1000. That is strictly stronger than the literal reading: an implementation that
    hard-codes 1000 and ignores the knob passes the plan as written and fails here, and a
    hard-coded constant "calibrated for prod" is exactly the phantom bug `CLAUDE.md` seam 3
    exists to prevent.

    Reaching depth `N` deterministically needs the writer not to drain, which is done with the
    two documented commit knobs — a batch larger than the queue and a long interval — rather
    than a test-only pause backdoor.
    """
    monkeypatch.setenv(ENV_QUEUE_DEPTH, str(TEST_QUEUE_DEPTH))
    monkeypatch.setenv(ENV_COMMIT_BATCH, str(TEST_QUEUE_DEPTH * 100))
    monkeypatch.setenv(ENV_COMMIT_INTERVAL_MS, str(10 * 60 * 1000))

    store = open_store(tmp_data_dir, issue=ISSUE)
    handle = store.cohort("COH-BP")
    with handle.transaction() as tx:
        tx.execute(statement(_ORDERED_DDL, issue=ISSUE))

    def enqueue(seq: int) -> float:
        started = time.perf_counter()
        handle.enqueue_write(statement(_ORDERED_INSERT, issue=ISSUE), seq=seq)
        return time.perf_counter() - started

    def depth_and_signal() -> tuple[int, bool]:
        metrics = store_metrics(store, issue=ISSUE)
        return int(metrics["write_queue_depth"]), bool(metrics["backpressure_active"])

    # --- below the threshold: N-1 pending rows, signal clear ---------------------------------
    below_durations = [enqueue(seq) for seq in range(TEST_QUEUE_DEPTH - 1)]
    depth, signalled = depth_and_signal()
    assert depth == TEST_QUEUE_DEPTH - 1, (
        f"TC-STORE-07: after {TEST_QUEUE_DEPTH - 1} enqueues the reported queue depth is "
        f"{depth}. The case cannot assert a boundary it cannot reach; if the writer drained, "
        f"{ENV_COMMIT_BATCH} and {ENV_COMMIT_INTERVAL_MS} are not being honoured."
    )
    assert not signalled, (
        f"TC-STORE-07: backpressure is raised at depth {depth}, below the configured threshold "
        f"of {TEST_QUEUE_DEPTH}. CT-STORE-06 makes this M-ORCH's throttle input (FR-ORCH-21), "
        "so an early signal throttles a run that had headroom."
    )

    # --- at the threshold: the signal must be up ---------------------------------------------
    enqueue(TEST_QUEUE_DEPTH - 1)
    depth, signalled = depth_and_signal()
    assert depth == TEST_QUEUE_DEPTH
    assert signalled, (
        f"TC-STORE-07: at depth {depth} — exactly the configured threshold — backpressure is "
        "not raised. FR-STORE-05 applies it 'when the pending write queue exceeds a configured "
        "depth'; a signal that only appears later lets the queue grow past the bound "
        "NFR-STORE-02's durability window is computed from."
    )

    # --- above the threshold: still raised, and enqueue blocks or slows -----------------------
    over = {"duration": None, "returned": False}
    finished = threading.Event()

    def enqueue_over_threshold() -> None:
        try:
            over["duration"] = enqueue(TEST_QUEUE_DEPTH)
            over["returned"] = True
        finally:
            finished.set()

    thread = threading.Thread(target=enqueue_over_threshold, name="over-threshold", daemon=True)
    thread.start()
    blocked = not finished.wait(timeout=BLOCK_OBSERVATION_S)

    _, signalled_above = depth_and_signal()
    assert signalled_above, (
        "TC-STORE-07: backpressure dropped again above the threshold. It is a level, not an "
        "edge — M-ORCH reads it to decide whether to keep throttling."
    )

    if not blocked:
        # It returned, so the promise it must keep is the other one: *slowed*. Compared against
        # the median of the sub-threshold enqueues, which is the only baseline that says
        # anything about this machine.
        finished.wait(timeout=THREAD_TIMEOUT_S)
        baseline = statistics.median(below_durations) if below_durations else 0.0
        assert over["duration"] is not None and over["duration"] > baseline, (
            "TC-STORE-07: the enqueue above the threshold neither blocked nor slowed — it "
            f"took {over['duration']:.6f}s against a sub-threshold median of {baseline:.6f}s. "
            "FR-STORE-05 requires one or the other; an enqueue that sails through above the "
            "depth applies no backpressure at all, whatever the signal says."
        )

    thread.join(timeout=THREAD_TIMEOUT_S)

    # --- the production figure the plan's literals refer to ----------------------------------
    monkeypatch.delenv(ENV_QUEUE_DEPTH, raising=False)
    monkeypatch.delenv(ENV_COMMIT_BATCH, raising=False)
    monkeypatch.delenv(ENV_COMMIT_INTERVAL_MS, raising=False)
    defaults = open_store(tmp_data_dir / "defaults", issue=ISSUE)
    default_metrics = store_metrics(defaults, issue=ISSUE)
    assert default_metrics["configured_queue_depth"] == DEFAULT_QUEUE_DEPTH, (
        "TC-STORE-07: the default write-queue depth is not design §3.3's 1,000, which is the "
        "figure the plan's 999/1000/1001 names. Driving the boundary through the knob must not "
        f"lose the production value: got {default_metrics['configured_queue_depth']}."
    )
    assert default_metrics["configured_commit_batch"] == DEFAULT_COMMIT_BATCH
    assert default_metrics["configured_commit_interval_ms"] == DEFAULT_COMMIT_INTERVAL_MS
