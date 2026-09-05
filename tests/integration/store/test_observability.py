"""The five store signals, and the free-disk alert.

Case `TC-STORE-24` (`FR-STORE-01`, `FR-STORE-03`, P1, Observability), test plan §5.3 and
`OBS-02` (§6.6). Issue #14 (TS-08); implemented by issue **#11**.

Rung 2 — real files, because two of the five signals (per-tier file sizes, free disk space) are
measurements of a real filesystem and mean nothing against a double.

**Written ahead of implementation** (test plan §8.2). Registered under `#11 store_metrics`.

Why an observability case is not decoration here. `CT-STORE-17` makes these signals *contract*:
"Free-disk and queue-depth are alert inputs and their semantics are contract." Design §3.3
lists two alerts — free disk below the projected remaining-run requirement, and queue depth
sustained above the backpressure threshold — and `FR-STORE-10`'s halt-on-`ENOSPC` is what
happens when the first one is ignored. A run that fills the disk at hour six of an overnight
window has lost the window; the alert is the only thing that says so in time.
"""

from __future__ import annotations

import os
import time

import pytest

from tests.support.store_api import open_store, statement, store_metrics
from tests.support.store_vocabulary import STORE_ALERTS, STORE_SIGNALS

pytestmark = [pytest.mark.integration]

ISSUE = "#11"

ENV_COMMIT_BATCH = "HARNESS_COMMIT_BATCH"
ENV_COMMIT_INTERVAL_MS = "HARNESS_COMMIT_INTERVAL_MS"

#: `OBS-02`'s precondition is "a saturated run". Env-gated: enough writes to move every signal
#: off its initial value, tunable down on a constrained box (`CLAUDE.md` seam 3).
SATURATION_WRITES = int(os.environ.get("HARNESS_TEST_SATURATION_WRITES", "400"))

#: The synthetic breach. `OBS-02`: "the free-disk alert fires against a synthetic breach of the
#: projected remaining-run requirement." Expressed as a projection larger than any real disk, so
#: the breach is a property of the arithmetic rather than of whatever machine runs the suite.
IMPOSSIBLE_PROJECTION_BYTES = 1 << 60  # 1 EiB

#: Bound on the drain poll before reading commit latency. A ceiling, not a sleep — §4.6
#: sanctions one sleep in this suite and it is TC-ORCH-09's.
DRAIN_TIMEOUT_S = float(os.environ.get("HARNESS_TEST_THREAD_TIMEOUT_S", "30"))
ENV_PROJECTED_REMAINING = "HARNESS_PROJECTED_RUN_BYTES"

_DDL = "CREATE TABLE metric_rows (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
_INSERT = "INSERT INTO metric_rows (payload) VALUES (:payload)"


def test_tc_store_24_every_named_signal_is_emitted_and_the_free_disk_alert_fires(
    tmp_data_dir, monkeypatch
):
    """`TC-STORE-24` / `OBS-02` — *"Write-queue depth, batch commit latency, per-tier file
    sizes, free disk space and `VACUUM` duration are emitted; the free-disk alert fires against
    a synthetic breach."*

    Oracle: **exact signal presence**.

    **Presence by exact name**, from `tests.support.store_vocabulary.STORE_SIGNALS`. Design
    §3.3 names the five signals in prose and `CT-STORE-17` says they are emitted "under those
    names" without fixing a spelling, so this case pins one and the PR reports the gap. An
    unassertable observability clause is the one a consumer discovers is broken.

    **Per-tier file sizes, keyed by tier.** The design says "database file sizes", plural, and
    the tiers have different lifetimes — Tier D is permanent, C+R are purged. One aggregate
    number cannot answer "which tier is growing", which is the only question the signal exists
    to answer, so the case asserts a mapping with a key per open tier rather than a scalar.

    **Values that moved.** Presence alone is passed by a constructor that emits five zeros. The
    case saturates the store first and then asserts the signals are *plausible*: a queue that
    was used, a file that has bytes, a disk with a real reading. Not exact values — those are
    machine-dependent — but each one distinguishable from "never measured".

    **The alert, against a synthetic breach.** Asserted in both directions: quiet before the
    breach, firing after. An alert that is always on is worth exactly as much as one that is
    always off, and only the pair of assertions tells them apart.
    """
    monkeypatch.setenv(ENV_COMMIT_BATCH, "50")
    monkeypatch.setenv(ENV_COMMIT_INTERVAL_MS, "50")

    store = open_store(tmp_data_dir, issue=ISSUE)
    cohort = store.cohort("COH-OBS")
    durable = store.durable()

    with cohort.transaction() as tx:
        tx.execute(statement(_DDL, issue=ISSUE))
    # `durable` needs no scratch table: opening it above created and migrated the file, and
    # #13's schema authorizer refuses caller DDL on Tier D write connections — schema there
    # belongs to migrations. (This case's original draft created `metric_rows` on both
    # tiers; the durable half of that fixture is what the refusal disproved, not any
    # assertion — nothing ever wrote to it.)

    # Sampled *during* saturation, because that is the only moment a queue-depth signal can be
    # distinguished from a hard-coded zero. Reading it after the queue drains reports 0 whether
    # the store counts pending rows or returns a constant.
    peak_depth = 0
    for index in range(SATURATION_WRITES):
        cohort.enqueue_write(statement(_INSERT, issue=ISSUE), payload=f"row-{index:05d}")
        if index % 50 == 0:
            peak_depth = max(
                peak_depth, int(store_metrics(store, issue=ISSUE)["write_queue_depth"])
            )

    # CT-STORE-02: enqueue_write returns before the row is durable, so a caller that must
    # observe its own writes goes through a transaction rather than waiting.
    with cohort.transaction() as tx:
        tx.execute(statement(_INSERT, issue=ISSUE), payload="flush")

    # Let the batches actually commit before reading commit latency: nothing else in this case
    # waits for one, and a metric read before any commit honestly reports nothing.
    deadline = time.monotonic() + DRAIN_TIMEOUT_S
    while int(store_metrics(store, issue=ISSUE)["write_queue_depth"]) > 0:
        if time.monotonic() >= deadline:
            break

    metrics = store_metrics(store, issue=ISSUE)

    missing = [name for name in STORE_SIGNALS if name not in metrics]
    assert not missing, (
        "TC-STORE-24: these signals are not emitted: "
        + ", ".join(f"{name} ({STORE_SIGNALS[name]})" for name in missing)
        + ". Design §3.3 names all five and CT-STORE-17 makes them contract — ops and M-ORCH "
        f"read them by name. Emitted: {sorted(metrics)}"
    )

    # --- per-tier file sizes, as a mapping ----------------------------------------------------
    sizes = metrics["database_file_bytes"]
    assert isinstance(sizes, dict), (
        "TC-STORE-24: database_file_bytes is a scalar. The tiers have different lifetimes — D "
        "is permanent, C+R are purged — so one aggregate cannot answer 'which tier is growing', "
        f"which is the only question the signal exists to answer. Got {sizes!r}."
    )
    assert "durable" in sizes and any(key.startswith("cohort") for key in sizes), (
        "TC-STORE-24: database_file_bytes does not carry a key per open tier. "
        f"Got {sorted(sizes)}."
    )
    assert all(value > 0 for value in sizes.values()), (
        f"TC-STORE-24: a tier reports zero bytes after {SATURATION_WRITES} writes: {sizes}. "
        "A signal that never leaves its initial value is not a measurement."
    )

    # --- the values moved ---------------------------------------------------------------------
    #
    # `>= 0` would be a tautology on every one of these — a constructor returning a dict of five
    # zeros satisfies it, which is exactly the implementation the presence check above already
    # fails to distinguish. Each assertion below is one a zeros-dict fails.
    assert metrics["free_disk_bytes"] > 0, (
        "TC-STORE-24: free_disk_bytes is not a real reading. It is one of the two alert inputs "
        "CT-STORE-17 makes contract."
    )
    assert metrics["batch_commit_latency_ms"] > 0, (
        f"TC-STORE-24: batch commit latency is {metrics['batch_commit_latency_ms']!r} after "
        f"{SATURATION_WRITES} writes across a 50 ms commit interval, and after waiting for the "
        "queue to drain. Commits demonstrably happened, so a zero means nothing observed the "
        "commit path — the path NFR-STORE-02's five-second durability window is measured "
        "against."
    )
    assert peak_depth > 0, (
        f"TC-STORE-24: write_queue_depth never rose above zero while {SATURATION_WRITES} writes "
        "were being enqueued, so it is not counting pending rows. An `isinstance(..., int)` "
        "check here would be satisfied by the hard-coded zero this assertion exists to rule "
        "out. It is one of the two alert inputs CT-STORE-17 makes contract, and M-ORCH "
        "throttles on it."
    )
    # `vacuum_duration_ms` is deliberately asserted only for presence and type here: no VACUUM
    # has run, so zero is the *honest* value, and demanding a positive one would require a
    # `purge_cohort` — which needs the promotion preconditions of `FR-STORE-07`. The non-zero
    # assertion belongs to `TC-STORE-11` (§5.3's purge block form), and is left there rather
    # than half-made here.
    assert isinstance(metrics["vacuum_duration_ms"], (int, float)), (
        "TC-STORE-24: vacuum_duration_ms is not a numeric measurement. purge_cohort's VACUUM is "
        "the longest operation the store performs and the one an operator waits on."
    )

    # --- the alert, in both directions --------------------------------------------------------
    quiet = store_metrics(store, issue=ISSUE)
    assert not quiet["alerts_firing"], (
        "TC-STORE-24: an alert is firing on a healthy store with megabytes of free disk. An "
        f"always-on alert is worth what an always-off one is worth. Firing: {quiet['alerts_firing']}"
    )
    assert set(quiet["alerts_declared"]) == STORE_ALERTS, (
        "TC-STORE-24: the declared alert set is not design §3.3's two — free disk below the "
        "projected remaining-run requirement, and queue depth sustained above the backpressure "
        f"threshold. Got {sorted(quiet['alerts_declared'])}."
    )

    # The breach is configured **before** the store that reads it is opened. Seam 3 knobs are
    # read at construction — that is what "production value is the default" means — so setting
    # the projection on a store that is already open would assert a live-reload behaviour
    # nothing requires, and would red a correct implementation on the one half OBS-02 names.
    monkeypatch.setenv(ENV_PROJECTED_REMAINING, str(IMPOSSIBLE_PROJECTION_BYTES))
    breached_store = open_store(tmp_data_dir / "breached", issue=ISSUE)
    breached_store.durable()
    breached = store_metrics(breached_store, issue=ISSUE)
    assert "free_disk_below_projection" in breached["alerts_firing"], (
        "TC-STORE-24: the free-disk alert did not fire against a projected remaining-run "
        f"requirement of {IMPOSSIBLE_PROJECTION_BYTES} bytes, which no disk satisfies. This "
        "alert is the only warning before FR-STORE-10 halts the process mid-run — by then the "
        "overnight window is already gone (OBS-02)."
    )
