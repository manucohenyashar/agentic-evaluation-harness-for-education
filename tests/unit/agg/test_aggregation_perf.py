"""`TC-AGG-20` — aggregation adds negligible wall clock: 5,250 aggregations per run.

Test plan §5.12 (row form, P2), issue #94 (TS-35). Traces to `NFR-AGG-03` (~5,250
aggregations per run, each microseconds; CT-AGG-13 folds the run-level half into
`PERF-06` — this case holds the per-call scale at unit tier). Landed at #91 (unmarked
there; test plan §8.2).

The production figure is microseconds per aggregation; the ceilings here are the
generous reading that keeps the case meaningful on a slow box without asserting a
specific machine's speed (the four-seams rule for environment-sensitive constants):

- `AEH_TEST_AGG_PERF_SECONDS` (default 10.0) — wall-clock budget for the whole batch.
- The per-call mean ceiling derives from the batch: 5,250 calls in the budget, and
  separately under one millisecond each — an aggregation that takes *milliseconds*
  is not "microseconds each" and fails even on a box granted the full budget.

Isolation: rung 0 — pure aggregation over generated odd panels, real clock (a
performance oracle is the one place the frozen clock is the wrong instrument).
"""

from __future__ import annotations

import os
import time

import pytest

from tests.support.agg_vocabulary import AGG_BLOCKER, band, criterion, favourable_signals, verdict
from tests.support.impl import AGG_MODULE, require

#: NFR-AGG-03's figure, verbatim.
BATCH = 5_250

#: Env-gated knob (the four-seams rule): production-sized budget by default, adjustable
#: on a slower box without a code change.
BUDGET_SECONDS = float(os.environ.get("AEH_TEST_AGG_PERF_SECONDS", "10.0"))

_PER_CALL_CEILING_SECONDS = 0.001  # one millisecond; the design says microseconds


def test_tc_agg_20_five_thousand_two_hundred_fifty_aggregations_add_negligible_wall_clock(
    seeded_random,
):
    """`TC-AGG-20` (`NFR-AGG-03`, performance / rung 0, P2) — 5,250 aggregations over
    mixed panel sizes and band counts complete within the budget and well under a
    millisecond each."""
    aggregate = require(AGG_MODULE, "aggregate", issue=AGG_BLOCKER)

    criteria = [
        criterion([band(f"B{i}", i, float(i)) for i in range(count)],
                  criterion_id=f"C-PERF-{count}")
        for count in (2, 4, 6)  # CT-PKG-04: band_count even, in 2..6
    ]
    panels = []
    for _ in range(BATCH):
        crit = criteria[seeded_random.randrange(len(criteria))]
        size = seeded_random.choice((1, 3, 5))
        panels.append((
            [(f"B{o}", o) for o in
             (seeded_random.randrange(crit.band_count) for _ in range(size))],
            crit,
        ))

    started = time.perf_counter()
    for specs, crit in panels:
        aggregate([verdict(name, ordinal) for name, ordinal in specs],
                  crit, favourable_signals())
    elapsed = time.perf_counter() - started

    assert elapsed < BUDGET_SECONDS, (
        f"{BATCH} aggregations took {elapsed:.3f}s against a {BUDGET_SECONDS}s budget — "
        "aggregation must add negligible wall clock (NFR-AGG-03); raise "
        "AEH_TEST_AGG_PERF_SECONDS only on a genuinely slower box"
    )
    per_call = elapsed / BATCH
    assert per_call < _PER_CALL_CEILING_SECONDS, (
        f"mean aggregation time is {per_call * 1e6:.0f} microseconds — NFR-AGG-03 says "
        "microseconds each; a millisecond-scale aggregation is a defect even inside the "
        "wall-clock budget"
    )
