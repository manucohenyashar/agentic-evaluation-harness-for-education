"""`PERF-05` (issue #146, TS-53) — sustained write load at the reference duration.

Test plan §6.4: *"Sustained write load | 60 s | Synthetic write units | Write units per second |
≥ 200/s with no queue growth | E1"* (`NFR-STORE-01`).

**What this adds over `TC-STORE-17`.** That case enqueues a burst of units as fast as the loop runs,
for a 2-second CI duration, then waits for the queue to drain. It checks the rate floor and that the
queue ends empty. Its docstring hands the 60-second run to `PERF-05`. A burst-then-drain run shows
throughput. It does not show *sustained* throughput, and it cannot see queue growth that recovers
before the end. This case keeps load on for the whole minute:

- **Offered load at the floor, paced.** Units are enqueued at exactly the floor, 200/s, for
  `DURATION_S` seconds, one tick every 100 ms. Offering more would fail a store that meets the floor
  but not the higher rate, and offering less would pass one that misses it.
- **Kept up, counted from the table.** By the end of the load window, the rows committed must be
  within one commit batch of the rows sent. A writer below 200/s falls further behind every second,
  and only a writer sustaining the floor stays within a batch. Rows are counted from the table, so a
  counted row is one that survived. The run must then drain, and every unit must land.
- **No queue growth, sampled.** `write_queue_depth` is read at every tick. The mean depth over the
  last third of the run must not exceed the mean over the first third by more than one commit batch.
  A writer 10% below the floor grows its queue by about 20 units a second, which is 400 units
  between the two thirds' midpoints at the default duration.

Setting `HARNESS_PERF_05_SECONDS` low weakens the growth check along with the duration: thirds of a
few seconds hold few samples, and a slow writer's backlog has little time to build.

The pacing sleep is a load generator's clock, not a synchronization point. §4.6's rule forbids
sleeping to wait for a result, and nothing here waits for the store by sleeping except the final
drain, which is bounded and checked.

`HARNESS_PERF_05_SECONDS` shortens the run on a constrained box. The threshold never moves (seam
rule 3). Markers: `integration` and `slow`, so a one-minute run stays out of the fast tier.
Environment E1.
"""

from __future__ import annotations

import os
import statistics
import time

import pytest

from aeh.store import store_metrics
from tests.support.store_api import open_store, statement

pytestmark = [pytest.mark.integration, pytest.mark.slow]

ISSUE = "#146"
ENVIRONMENT = "E1"

#: `PERF-05`'s duration: 60 s of sustained load.
DURATION_S = int(os.environ.get("HARNESS_PERF_05_SECONDS", "60"))
#: `NFR-STORE-01`: at least 200 write units per second.
RATE_FLOOR = 200
#: The arrival rate: the floor itself, so keeping up with it is meeting it.
OFFERED_RATE = RATE_FLOOR
TICK_S = 0.1
#: The store's commit batch for this run; one batch of depth is ordinary queue noise.
COMMIT_BATCH = 100


def test_perf_05_two_hundred_write_units_per_second_for_a_minute_with_no_queue_growth(
    tmp_data_dir, monkeypatch
):
    """`PERF-05`: 60 s of paced load at 200 units/s. The writer keeps up within one commit batch,
    the queue does not grow over the run, and every unit lands."""
    monkeypatch.setenv("HARNESS_COMMIT_BATCH", str(COMMIT_BATCH))
    monkeypatch.setenv("HARNESS_COMMIT_INTERVAL_MS", "100")
    store = open_store(tmp_data_dir)
    try:
        handle = store.cohort("c-perf-05")
        with handle.transaction() as tx:
            tx.execute(statement(
                "CREATE TABLE perf_rows (unit_no INTEGER NOT NULL, payload TEXT NOT NULL)",
                issue=ISSUE))
        insert = statement(
            "INSERT INTO perf_rows (unit_no, payload) VALUES (:unit_no, :payload)", issue=ISSUE)

        per_tick = int(OFFERED_RATE * TICK_S)
        ticks = int(DURATION_S / TICK_S)
        depths: list[int] = []
        sent = 0
        started = time.perf_counter()
        for tick in range(ticks):
            for _ in range(per_tick):
                handle.enqueue_write(insert, unit_no=sent, payload=f"p{sent % 64}")
                sent += 1
            depths.append(int(store_metrics(store)["write_queue_depth"]))
            # Pace against the schedule, not the last tick, so a slow tick is not compounded.
            lag = started + (tick + 1) * TICK_S - time.perf_counter()
            if lag > 0:
                time.sleep(lag)
        offered_seconds = time.perf_counter() - started
        committed_in_window = handle.query(
            statement("SELECT COUNT(*) FROM perf_rows", issue=ISSUE))[0][0]

        deadline = time.perf_counter() + 120
        while int(store_metrics(store)["write_queue_depth"]) > 0 and time.perf_counter() < deadline:
            time.sleep(0.01)
        elapsed = time.perf_counter() - started
        landed = handle.query(statement("SELECT COUNT(*) FROM perf_rows", issue=ISSUE))[0][0]
        final_depth = int(store_metrics(store)["write_queue_depth"])
    finally:
        store.close()

    third = max(len(depths) // 3, 1)
    early, late = statistics.mean(depths[:third]), statistics.mean(depths[-third:])
    rate = committed_in_window / offered_seconds
    report = (
        f"PERF-05 on {ENVIRONMENT} (not evidence about E4): offered {sent} units over "
        f"{offered_seconds:.1f}s ({sent / offered_seconds:.0f}/s); {committed_in_window} committed in "
        f"the window ({rate:.0f}/s), {landed} landed by {elapsed:.1f}s; queue depth mean {early:.0f} in the first third, "
        f"{late:.0f} in the last, max {max(depths)}, final {final_depth}"
    )
    print(report)

    assert sent == per_tick * ticks and offered_seconds >= DURATION_S * 0.95, (
        f"fixture: the load was not sustained for the duration. {report}"
    )
    problems = []
    if landed != sent:
        problems.append(f"{landed} of {sent} units landed; a unit that never lands is not "
                        f"throughput")
    if final_depth != 0:
        problems.append(f"the queue never drained (depth {final_depth} after a 120 s wait)")
    if committed_in_window < sent - COMMIT_BATCH:
        problems.append(f"the writer fell behind a {RATE_FLOOR}/s arrival rate: {committed_in_window} of "
                        f"{sent} units committed by the end of the load window ({rate:.0f}/s), more "
                        f"than one {COMMIT_BATCH}-unit batch behind (NFR-STORE-01)")
    if late > early + COMMIT_BATCH:
        problems.append(f"the queue grew over the run: mean depth {early:.0f} in the first third, "
                        f"{late:.0f} in the last (more than one {COMMIT_BATCH}-unit batch). "
                        f"PERF-05 allows no queue growth")
    assert not problems, "\n".join(problems) + f"\n{report}"
