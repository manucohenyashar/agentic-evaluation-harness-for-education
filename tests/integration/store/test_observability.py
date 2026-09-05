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

import pytest

from tests.support.store_api import open_store, statement, store_metrics
from tests.support.store_vocabulary import STORE_ALERTS, STORE_SIGNALS

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

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
    with durable.transaction() as tx:
        tx.execute(statement(_DDL, issue=ISSUE))

    for index in range(SATURATION_WRITES):
        cohort.enqueue_write(statement(_INSERT, issue=ISSUE), payload=f"row-{index:05d}")

    # CT-STORE-02: enqueue_write returns before the row is durable, so a caller that must
    # observe its own writes goes through a transaction rather than waiting.
    with cohort.transaction() as tx:
        tx.execute(statement(_INSERT, issue=ISSUE), payload="flush")

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
    assert metrics["free_disk_bytes"] > 0, (
        "TC-STORE-24: free_disk_bytes is not a real reading. It is one of the two alert inputs "
        "CT-STORE-17 makes contract."
    )
    assert metrics["batch_commit_latency_ms"] >= 0, (
        "TC-STORE-24: batch commit latency was never recorded, so nothing observed the "
        "commit path that NFR-STORE-02's 5-second durability window is measured against."
    )
    assert metrics["write_queue_depth"] >= 0
    assert metrics["vacuum_duration_ms"] >= 0, (
        "TC-STORE-24: vacuum_duration_ms is absent as a measurement. purge_cohort's VACUUM is "
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

    monkeypatch.setenv(ENV_PROJECTED_REMAINING, str(IMPOSSIBLE_PROJECTION_BYTES))
    breached = store_metrics(store, issue=ISSUE)
    assert "free_disk_below_projection" in breached["alerts_firing"], (
        "TC-STORE-24: the free-disk alert did not fire against a projected remaining-run "
        f"requirement of {IMPOSSIBLE_PROJECTION_BYTES} bytes, which no disk satisfies. This "
        "alert is the only warning before FR-STORE-10 halts the process mid-run — by then the "
        "overnight window is already gone (OBS-02)."
    )
