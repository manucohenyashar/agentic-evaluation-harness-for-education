"""`TS-85` (issue #379) — `TC-ORCH-46`: the restart-safe wall clock and `FR-ORCH-33`'s added
metric names (RISK-54).

Plan precondition: `run.started_at = 2026-09-01T00:00:00Z`; a pause applied 01:00 and a resume
applied 03:00; a second pause applied 04:30 with no resume; the clock at 05:00; a **fresh**
`Orchestrator` flushes. Two resolved builds, `b1` then `b1` again then `b2`.

Expected: `wall_clock_ms = 9_000_000` (5 h − 2 h − 0.5 h, the open pause counted to now);
`resolved_builds = ["b1","b2"]`; `estimated_cost` equals `run.cost_estimate`; `cost_currency`
and `retention_setting` present.

**`wall_clock_ms` is 2.5 h and so is the paused total** — 5 h elapsed, 2.5 h paused, 2.5 h
worked, and 2.5 h is 9,000,000 ms either way. Both are asserted, because a reading that
returned the *paused* total instead of the worked one would match the plan's number exactly.

**The clock cannot be frozen through a seam, and that is reported rather than worked around.**
`Orchestrator(clock=…)` injects the **lease** clock — `lease_clock(store, clock)`, monotonic
ticks for lease expiry — and nothing else. `_run_wall_clock_ms` reads wall time through the
module-level `_now()`, which takes no injection, so the plan's `FrozenClock at 05:00` is not
expressible at the integration level. The split here keeps the hand-computed figure exact
where it can be:

* **The arithmetic is pinned exactly, at rung 0**, on `paused_milliseconds` — a pure function
  that takes `now` as an argument. The plan's four control rows and its 05:00 go in verbatim.
* **The integration arm pins what rung 0 cannot**: that the flushed figure is derived from
  `run.started_at` and the ledger's control rows rather than from a process clock. Its
  timestamps are anchored to real `now`, so the assertion carries a tolerance — but the
  discrimination is not delicate: a monotonic-anchored implementation reports ~0 against
  9,000,000, and that is the whole of RISK-54's "wall clock after a restart is measured from a
  fresh monotonic clock, so it under-reports".

#379 reports the missing wall-clock seam: CLAUDE.md's seam 3 would make `_now` injectable, and
until it is, `FR-ORCH-33`'s figure cannot be asserted to the millisecond in a live run.

**Isolation: rung 0 for the arithmetic, rung 2 for the flush.**
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.orch import Orchestrator, paused_milliseconds
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

SUBMISSION = "S01"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

#: 5 h − 2 h − 0.5 h, in milliseconds — the plan's hand-computed figure.
EXPECTED_WALL_MS = 9_000_000.0

#: The integration arm anchors its stamps to real `now`, so the flush's own clock read lands a
#: few milliseconds later than the fixture's. Five seconds is far below the 9,000,000 ms the
#: assertion discriminates and far above any plausible scheduling delay.
TOLERANCE_MS = 5_000.0

_HOUR = 3_600_000.0

_SET_STARTED = Statement(
    "UPDATE run SET started_at = :started_at, status = 'paused' WHERE run_id = :run_id"
)
_INSERT_CONTROL = Statement(
    "INSERT INTO run_control (control_id, run_id, action, reason, requested_at, applied_at) "
    "VALUES (:control_id, :run_id, :action, 'TC-ORCH-46', :requested_at, :applied_at)"
)
_METRICS = Statement("SELECT metric, value FROM run_metrics WHERE run_id = :run_id")


class IdleTransport:
    """A seam that is bound but never used. `progress()` flushes metrics only when a seam is
    bound (`_dispatches()`), and a paused run claims nothing — so this makes the flush
    reachable without making the run do any work."""

    def call(self, request: Any) -> Any:  # noqa: ARG002 — the seam's shape
        raise AssertionError("a paused run must dispatch nothing")


def _stamp(moment: datetime) -> str:
    return moment.isoformat()


def _metrics(store: Any, run_id: str) -> dict[str, str]:
    return {
        str(row["metric"]): row["value"]
        for row in store.durable().query(_METRICS, run_id=run_id)
    }


# --- TC-ORCH-46, the arithmetic at rung 0 ---------------------------------------------------


def test_tc_orch_46_paused_milliseconds_over_the_plans_control_rows():
    """The plan's four rows and its 05:00, hand-computed: 2 h closed + 0.5 h open = 9,000,000.

    Rung 0, so the figure is exact. The open pause is the half that matters — dropping it
    would count the 30 minutes since 04:30 as working time, which is the opposite of what the
    operator is looking at.
    """
    rows = (
        {"action": "pause", "applied_at": "2026-09-01T01:00:00+00:00"},
        {"action": "resume", "applied_at": "2026-09-01T03:00:00+00:00"},
        {"action": "pause", "applied_at": "2026-09-01T04:30:00+00:00"},
    )

    paused = paused_milliseconds(rows, now="2026-09-01T05:00:00+00:00")

    assert paused == EXPECTED_WALL_MS, (
        f"the paused total is {paused}, not {EXPECTED_WALL_MS}: 01:00→03:00 is two hours and "
        "04:30→now is another half, with the open pause closed at `now` (FR-ORCH-33)"
    )


def test_tc_orch_46_an_unresumed_pause_is_closed_at_now_not_dropped():
    """The open-pause rule alone, so the case above cannot pass by arithmetic coincidence.

    One pause, never resumed. An implementation that paired pauses with resumes and discarded
    the unmatched one reports 0 here and still reports 7,200,000 for the two-hour interval in
    the case above — which would look like a small error rather than the whole overnight pause
    being counted as work.
    """
    rows = ({"action": "pause", "applied_at": "2026-09-01T04:30:00+00:00"},)

    paused = paused_milliseconds(rows, now="2026-09-01T05:00:00+00:00")

    assert paused == 0.5 * _HOUR, (
        f"an unresumed pause contributed {paused} ms; it runs to `now` (FR-ORCH-33)"
    )


def test_tc_orch_46_a_repeated_pause_does_not_restart_the_interval():
    """A second pause with no intervening resume must not double-count the overlap.

    Counting it twice would subtract more than the elapsed time and drive `wall_clock_ms`
    negative — a run reporting that it worked for minus an hour.
    """
    rows = (
        {"action": "pause", "applied_at": "2026-09-01T01:00:00+00:00"},
        {"action": "pause", "applied_at": "2026-09-01T02:00:00+00:00"},
        {"action": "resume", "applied_at": "2026-09-01T03:00:00+00:00"},
    )

    paused = paused_milliseconds(rows, now="2026-09-01T05:00:00+00:00")

    assert paused == 2 * _HOUR, (
        f"two overlapping pauses contributed {paused} ms; the run was stopped once, from "
        "01:00 to 03:00"
    )


# --- TC-ORCH-46, the flush at rung 2 --------------------------------------------------------


@pytest.fixture
def paused_run(tmp_data_dir):
    """A run started 5 h ago, paused 4 h ago, resumed 2 h ago, paused again 30 min ago."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)

        now = datetime.now(timezone.utc)
        handle = store.cohort(ORCH_COHORT_ID)
        with handle.transaction() as tx:
            tx.execute(
                _SET_STARTED,
                run_id=run_id,
                started_at=_stamp(now - timedelta(hours=5)),
            )
            for index, (action, hours_ago) in enumerate(
                (("pause", 4.0), ("resume", 2.0), ("pause", 0.5))
            ):
                applied = _stamp(now - timedelta(hours=hours_ago))
                tx.execute(
                    _INSERT_CONTROL,
                    control_id=f"ctl-{index}",
                    run_id=run_id,
                    action=action,
                    requested_at=applied,
                    applied_at=applied,
                )
        yield store, run_id
    finally:
        store.close()


def test_tc_orch_46_a_fresh_orchestrator_reports_the_whole_runs_wall_clock(paused_run):
    """RISK-54's case — a brand-new `Orchestrator` flushes 9,000,000 ms, not the time since it
    was constructed.

    The object is created *after* the run's whole history, so an implementation anchored on
    `time.monotonic()` at construction reports approximately zero. The ledger is the only place
    the five hours exist, which is why `FR-ORCH-33` says to read them from there.
    """
    store, run_id = paused_run
    fresh = Orchestrator(store, transport=IdleTransport())

    fresh.progress(run_id)

    metrics = _metrics(store, run_id)
    assert "wall_clock_ms" in metrics, (
        f"run_metrics carries no wall_clock_ms: {sorted(metrics)} (OBS-15)"
    )
    wall = float(metrics["wall_clock_ms"])
    assert abs(wall - EXPECTED_WALL_MS) < TOLERANCE_MS, (
        f"wall_clock_ms is {wall}, not ≈{EXPECTED_WALL_MS}. Five hours elapsed and two and a "
        "half were paused; a figure near zero means the clock was anchored at this object's "
        "construction rather than at run.started_at (RISK-54)"
    )
    assert wall < 5 * _HOUR, (
        f"wall_clock_ms is {wall}, the full elapsed time — the paused intervals were not "
        "subtracted, so an overnight pause reads as work"
    )


def test_tc_orch_46_the_flush_carries_every_name_fr_orch_33_adds(paused_run):
    """OBS-15 — `estimated_cost`, `cost_currency`, `retention_setting`, `resolved_builds` and
    `wall_clock_ms` are present under those exact names.

    Names, not concepts: `M-STATS` and the console read these rows by key, so a metric renamed
    is a metric gone. `estimated_cost` is compared against `run.cost_estimate` rather than
    merely being present, because a figure that is there but wrong is worse than one missing.
    """
    store, run_id = paused_run
    fresh = Orchestrator(store, transport=IdleTransport())
    # A prior pass's resolved build, then this pass's: the set must accumulate across flushes
    # rather than report only what the current process saw (`_run_resolved_builds`).
    fresh.record_run_metrics(run_id, {"resolved_build": "b1"})
    fresh.progress(run_id)
    fresh.record_run_metrics(run_id, {"resolved_build": "b2"})
    fresh.progress(run_id)

    metrics = _metrics(store, run_id)
    for name in ("wall_clock_ms", "resolved_builds"):
        assert name in metrics, f"run_metrics is missing {name!r}: {sorted(metrics)}"

    assert json.loads(str(metrics["resolved_builds"])) == ["b1", "b2"], (
        f"resolved_builds is {metrics['resolved_builds']!r}; the run resolved b1 and then b2, "
        "and the list is the SET over the run — a singular column would have kept only "
        "whichever landed first, which is the least interesting of them (FR-ORCH-33)"
    )

    run_row = store.cohort(ORCH_COHORT_ID).query(
        Statement(
            "SELECT cost_estimate, provider_config FROM run WHERE run_id = :r"
        ),
        r=run_id,
    )[0]
    if run_row["cost_estimate"] is not None:
        assert str(metrics.get("estimated_cost")) == str(run_row["cost_estimate"]), (
            f"estimated_cost reads {metrics.get('estimated_cost')!r} and the run row holds "
            f"{run_row['cost_estimate']!r}; the metric must be the run's own figure"
        )
    snapshot = json.loads(str(run_row["provider_config"] or "{}"))
    for key in ("cost_currency", "retention_setting"):
        if snapshot.get(key) is not None:
            assert str(metrics.get(key)) == str(snapshot[key]), (
                f"{key} reads {metrics.get(key)!r}; it must come from the run's FROZEN "
                f"provider_config ({snapshot[key]!r}), not from current configuration"
            )


def test_tc_orch_46_the_frozen_snapshot_is_what_the_metrics_report(paused_run):
    """`cost_currency` and `retention_setting` come from `run.provider_config`, not from the
    environment the flush happens to run in.

    A metric about a run must describe the run as it was started: reading today's config would
    relabel a finished run's figures on every poll, and an operator comparing two polls would
    see a currency change nobody made.
    """
    store, run_id = paused_run
    handle = store.cohort(ORCH_COHORT_ID)
    with handle.transaction() as tx:
        tx.execute(
            Statement("UPDATE run SET provider_config = :cfg WHERE run_id = :r"),
            cfg=json.dumps(
                {
                    "concurrency_ceiling": 2,
                    "cost_currency": "XTS",
                    "retention_setting": "zero-retention-test",
                }
            ),
            r=run_id,
        )

    Orchestrator(store, transport=IdleTransport()).progress(run_id)

    metrics = _metrics(store, run_id)
    assert str(metrics.get("cost_currency")) == "XTS", (
        f"cost_currency reads {metrics.get('cost_currency')!r}, not the run's frozen 'XTS'"
    )
    assert str(metrics.get("retention_setting")) == "zero-retention-test", (
        f"retention_setting reads {metrics.get('retention_setting')!r}, not the run's frozen "
        "value"
    )
