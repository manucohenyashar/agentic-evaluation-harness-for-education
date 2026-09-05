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
every wait is bounded by a knob rather than by a guessed duration. A test that sleeps to let a
queue drain passes on a fast box and flakes on a slow one, which §4.6's flake policy makes a P1
defect rather than an inconvenience.

**Written ahead of implementation** (test plan §8.2): expected to fail with `NotImplementedYet`
naming #11 — or #10, whichever is missing first, since a write queue needs a store to write to.
Registered under `#11 store_metrics`.
"""

from __future__ import annotations

import os
import statistics
import threading
import time

import pytest

from tests.support.store_api import open_store, statement, store_metrics

pytestmark = [pytest.mark.integration]

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

#: Writes the ordering half enqueues. Enough that an out-of-order commit is visible and a batch
#: boundary is crossed; small enough to stay inside the integration tier's budget.
ORDERED_WRITES = int(os.environ.get("HARNESS_TEST_ORDERED_WRITES", "250"))

#: Every bounded wait in this file. Not a sleep: nothing waits for this to elapse on the happy
#: path — it is the ceiling past which a hang is reported as a failure instead of hanging CI.
THREAD_TIMEOUT_S = float(os.environ.get("HARNESS_TEST_THREAD_TIMEOUT_S", "30"))

#: How long a *blocked* `enqueue_write` must stay blocked before the case believes it.
BLOCK_OBSERVATION_S = float(os.environ.get("HARNESS_TEST_BLOCK_OBSERVATION_S", "0.5"))

#: How much slower an above-threshold `enqueue_write` must be before "slowed" is believed.
#: A bare `>` against the sub-threshold median is a coin flip — an implementation applying *no*
#: backpressure clears it about half the time purely on timing noise, which is not an oracle.
SLOWDOWN_FACTOR = float(os.environ.get("HARNESS_TEST_SLOWDOWN_FACTOR", "5"))

#: …and a factor alone is not enough either. Seven enqueues of a pure-Python queue `put` each
#: take single-digit microseconds, so `5x` is a bar of about 10 µs that one GC pause or context
#: switch clears. The absolute floor is what makes the limb mean "a human-visible slowdown"
#: rather than "noise in the right direction". Env-gated, since it is a wall-clock figure and
#: therefore environment-sensitive (`CLAUDE.md` seam 3).
SLOWDOWN_FLOOR_S = float(os.environ.get("HARNESS_TEST_SLOWDOWN_FLOOR_S", "0.001"))

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


def _drain(store) -> int:
    """Wait, bounded, for the write queue to reach zero pending rows; return what it reached.

    `CT-STORE-02` makes `enqueue_write` asynchronous — "it returns before the row is durable" —
    so reading back enqueued rows without waiting asserts a promise the contract does not make,
    and would red a *correct* async store. Polling the module's own depth signal is what keeps
    this sleep-free: there is no interval to guess, and the bound is a knob.
    """
    deadline = time.monotonic() + THREAD_TIMEOUT_S
    while True:
        depth = int(store_metrics(store, issue=ISSUE)["write_queue_depth"])
        if depth == 0 or time.monotonic() >= deadline:
            return depth
    # Deliberately no `time.sleep` anywhere in the loop, not even `sleep(0)`: §4.6 sanctions
    # exactly one sleep in this suite and it is TC-ORCH-09's. The poll is bounded by the
    # deadline instead, and each iteration makes a real call that releases the GIL — which is
    # also what lets reader threads be scheduled while this runs (see TC-STORE-03).


def test_tc_store_03_readers_never_block_the_writer_and_writes_land_in_enqueue_order(
    tmp_data_dir, monkeypatch
):
    """`TC-STORE-03` — *"Readers never block the writer; writes land in enqueue order; no
    `SQLITE_BUSY` surfaces to a caller."*

    Oracle: **ordering invariant plus no-exception**.

    **Readers never block the writer** is the P0 claim, and asserting it needs care: "the writer
    finished" is passed by any implementation that finishes eventually, including one that
    serialized every read behind the write. So the oracle here is *interleaving*, sampled rather
    than inferred.

    Each reader publishes a progress counter. Two barriers bracket the setup: the first releases
    everyone together, the second holds the writer until every reader has completed at least one
    query — which is what stops the writer racing to the end before a reader has run at all, and
    makes "a reader completed zero queries" impossible rather than unlikely. The writer then
    snapshots every counter, enqueues, **drains the queue while the readers are still
    spinning**, and snapshots again.

    *Writer side* — the drain must complete under read load. This is the limb that names
    `FR-STORE-03`'s promise: a rollback-journal database whose writer cannot take EXCLUSIVE past
    eight SHARED locks times out here. Draining after the readers exit would say nothing, since
    a writer that starves behind reader locks drains perfectly once they stop.

    *Reader side* — no reader shows a zero delta across the write phase, so reads and writes
    genuinely interleaved.

    Two earlier forms of this assertion were wrong, and both reasons are worth keeping. "Readers
    were still in their loop when the writer finished" was true by construction, since the loop
    exits *on* that event. Snapshotting around the enqueues alone was worse: 250 `enqueue_write`
    calls are pure Python and finish inside CPython's 5 ms switch interval, so the writer held
    the GIL across both snapshots and every reader showed a zero delta — a false red against a
    *correct* store, measured in 20 runs out of 20. The drain is what puts real, GIL-releasing
    work between the snapshots.

    What this case does **not** catch, stated rather than implied: a per-operation shared mutex,
    where readers and the writer simply alternate and every counter advances. Throughput under
    contention is `TC-STORE-17`'s (`NFR-STORE-01`, 200 write units/second), not this case's.

    **Enqueue order** is read with an explicit `ORDER BY`, because `CT-STORE-18` says the module
    chooses no order and "a caller needing an order states it in the statement", and only after
    the drain, because `CT-STORE-02` says the rows are not durable when `enqueue_write` returns.

    **No `SQLITE_BUSY`** (`CT-STORE-11`: "retried internally and never surfaces") is swept over
    every thread. Eight concurrent readers against an active writer is exactly the condition
    that produces it, and a reader that swallowed one would leave the writer's assertions green.
    """
    monkeypatch.setenv(ENV_COMMIT_BATCH, "25")
    monkeypatch.setenv(ENV_COMMIT_INTERVAL_MS, "50")

    store = open_store(tmp_data_dir, issue=ISSUE)
    handle = store.cohort("COH-CONC")
    with handle.transaction() as tx:
        tx.execute(statement(_ORDERED_DDL, issue=ISSUE))

    start = threading.Barrier(READER_THREADS + 1, timeout=THREAD_TIMEOUT_S)
    readers_warm = threading.Barrier(READER_THREADS + 1, timeout=THREAD_TIMEOUT_S)
    writer_done = threading.Event()
    progress = [0] * READER_THREADS
    snapshots: dict[str, list[int]] = {}
    errors: list[BaseException] = []

    def reader(index: int) -> None:
        try:
            start.wait()
            # One query before the writer is allowed to begin, so "this reader never ran" is
            # impossible by construction rather than merely unlikely under load.
            list(handle.query(statement(_ORDERED_COUNT, issue=ISSUE)))
            progress[index] = 1
            readers_warm.wait()
            while not writer_done.is_set():
                list(handle.query(statement(_ORDERED_COUNT, issue=ISSUE)))
                progress[index] += 1
        except BaseException as error:  # noqa: BLE001 — every escape is a finding
            errors.append(error)

    def writer() -> None:
        try:
            start.wait()
            readers_warm.wait()
            snapshots["before"] = list(progress)
            for seq in range(ORDERED_WRITES):
                handle.enqueue_write(statement(_ORDERED_INSERT, issue=ISSUE), seq=seq)
            # The drain happens **here**, inside the write phase, while the readers are still
            # spinning. Two reasons, and the first is why an earlier draft was wrong:
            #
            # 1. 250 `enqueue_write` calls are pure Python and return in well under CPython's
            #    5 ms switch interval, so the writer would hold the GIL across both snapshots
            #    and every reader would show a zero delta — a deterministic false red against a
            #    *correct* WAL store, measured at 20 runs out of 20.
            # 2. Draining under read load is the only place writer-side progress is observed
            #    while readers hold locks. Draining after they exit tells us nothing: a store
            #    whose writer starves behind reader locks drains perfectly once the readers stop.
            snapshots["drained"] = _drain(store)
            snapshots["after"] = list(progress)
        except BaseException as error:  # noqa: BLE001
            errors.append(error)
        finally:
            writer_done.set()

    threads = [
        threading.Thread(target=reader, args=(index,), name=f"reader-{index}", daemon=True)
        for index in range(READER_THREADS)
    ]
    threads.append(threading.Thread(target=writer, name="writer", daemon=True))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=THREAD_TIMEOUT_S)

    live = [thread.name for thread in threads if thread.is_alive()]
    assert not live, (
        f"TC-STORE-03: {live} did not finish within {THREAD_TIMEOUT_S}s. A writer that cannot "
        "make progress behind concurrent readers is the FR-STORE-03 failure; a reader that "
        "cannot finish means the writer held the file exclusively."
    )

    busy = [error for error in errors if _is_busy_error(error)]
    assert not busy, (
        "TC-STORE-03: SQLITE_BUSY reached a caller. CT-STORE-11: it is retried internally and "
        f"never surfaces, and under WAL with a single writer it should not occur: {busy}"
    )
    assert not errors, f"TC-STORE-03: a reader or the writer raised: {errors}"

    assert "before" in snapshots and "after" in snapshots, (
        "TC-STORE-03: the writer never reached its sampling points, so the interleaving "
        "assertion below would pass vacuously."
    )

    # The writer-side half, and the one that names FR-STORE-03's actual promise.
    assert snapshots["drained"] == 0, (
        f"TC-STORE-03: the writer could not drain its queue while {READER_THREADS} readers were "
        f"active — {snapshots['drained']} rows still pending after {THREAD_TIMEOUT_S}s. That is "
        "'readers block the writer', which FR-STORE-03 forbids and CT-STORE-04 promises every "
        "writer. It is a rollback-journal database whose writer cannot take EXCLUSIVE past the "
        "readers' SHARED locks; it is not a slow box, and raising THREAD_TIMEOUT_S is not the "
        "fix."
    )

    # The reader-side half: no reader was starved for the whole write phase.
    stalled = [
        index
        for index in range(READER_THREADS)
        if snapshots["after"][index] <= snapshots["before"][index]
    ]
    assert not stalled, (
        f"TC-STORE-03: readers {stalled} completed no query while the writer was writing and "
        f"draining (before={snapshots['before']}, after={snapshots['after']}). Reads and writes "
        "did not interleave at all, so the two are serialized against each other."
    )

    rows = list(handle.query(statement(_ORDERED_READ, issue=ISSUE)))
    landed = [row[0] for row in rows]
    assert landed == list(range(ORDERED_WRITES)), (
        "TC-STORE-03: writes did not land in enqueue order. FR-STORE-03 serializes all writes "
        "through one writer thread fed by an in-process queue, and CT-STORE-04 makes the "
        f"single-caller ordering a promise. Expected 0..{ORDERED_WRITES - 1} in order, got "
        f"{landed[:12]}... ({len(landed)} rows)"
    )


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
    are asserted — `N-1` clear, `N` raised, `N+1` still raised — rather than checking only that
    it eventually goes up.

    **Driven through the knob, not the literal.** The plan says 999/1000/1001, which is design
    §3.3's default depth ±1. This case sets `HARNESS_WRITE_QUEUE_DEPTH` small, asserts the
    boundary relative to the *configured* value, and then asserts separately that the default
    really is 1000. That is strictly stronger than the literal reading: an implementation that
    hard-codes 1000 and ignores the knob passes the plan as written and fails here, and a
    constant "calibrated for prod" is exactly the phantom bug `CLAUDE.md` seam 3 exists to stop.

    Reaching depth `N` deterministically needs the writer not to drain, done with the two
    documented commit knobs — a batch larger than the queue, a long interval — rather than a
    test-only pause backdoor.

    **"Slowed" is asserted against a factor, not a `>`.** A bare comparison against the median
    of seven timings of the same operation is cleared by pure noise roughly half the time, so an
    implementation applying no backpressure at all would pass at a coin flip. `SLOWDOWN_FACTOR`
    is what makes this limb an oracle instead of a lottery.
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
    assert depth == TEST_QUEUE_DEPTH, (
        f"TC-STORE-07: expected the queue to hold exactly {TEST_QUEUE_DEPTH} pending rows at "
        f"the boundary, it holds {depth}."
    )
    assert signalled, (
        f"TC-STORE-07: at depth {depth} — exactly the configured threshold — backpressure is "
        "not raised. FR-STORE-05 applies it 'when the pending write queue exceeds a configured "
        "depth'; a signal that only appears later lets the queue grow past the bound "
        "NFR-STORE-02's durability window is computed from."
    )

    # --- above the threshold: still raised, and enqueue blocks or slows -----------------------
    over: dict[str, float | None] = {"duration": None}
    finished = threading.Event()

    def enqueue_over_threshold() -> None:
        try:
            over["duration"] = enqueue(TEST_QUEUE_DEPTH)
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

    if blocked:
        # Blocking is one of the two behaviours FR-STORE-05 sanctions, and this fixture pins the
        # commit interval at ten minutes so the queue cannot drain — a blocked enqueue is
        # expected to stay blocked for the rest of the case, and the daemon thread dies with the
        # session. That does mean a permanent deadlock and legitimate backpressure look alike
        # here; telling them apart needs a drain, which is TC-STORE-08's ground, not this case's.
        pass
    else:
        finished.wait(timeout=THREAD_TIMEOUT_S)
        baseline = statistics.median(below_durations) if below_durations else 0.0
        duration = over["duration"]
        bar = max(baseline * SLOWDOWN_FACTOR, SLOWDOWN_FLOOR_S)
        assert duration is not None and duration > bar, (
            "TC-STORE-07: the enqueue above the threshold neither blocked nor slowed "
            f"meaningfully — {duration:.6f}s against a bar of {bar:.6f}s "
            f"(max of {SLOWDOWN_FACTOR}x the sub-threshold median {baseline:.6f}s, and the "
            f"{SLOWDOWN_FLOOR_S:.6f}s absolute floor). FR-STORE-05 requires blocking or "
            "slowing; an enqueue that sails through above the depth applies no backpressure at "
            "all, whatever the signal says."
        )

    thread.join(timeout=BLOCK_OBSERVATION_S)

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
