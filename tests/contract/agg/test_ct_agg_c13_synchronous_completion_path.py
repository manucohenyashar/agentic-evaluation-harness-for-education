"""`TC-AGG-C13` — microseconds each, so a consumer may aggregate inline (§6.11.12).

`CT-AGG-13`: "~5,250 aggregations per run, each microseconds; aggregation adds
negligible wall clock (`NFR-AGG-03`). A consumer may aggregate synchronously on the
completion path."

Disposition, disclosed:

- **the stated load** — the shipped sibling
  `tests/unit/agg/test_aggregation_perf.py` (`TC-AGG-20`, #94) holds the batch
  figure at unit tier: 5,250 aggregations under the `AEH_TEST_AGG_PERF_SECONDS`
  knob, each under a millisecond. Not repeated here;
- **the completion path** (this file, the case's rung-3 limb): a REAL driven
  run's stored panel, aggregated INLINE — the exact call a consumer makes on the
  completion path — at the same stated load, under the same env-gated budget and
  the same per-call ceiling. The grant is the clause's point: synchronous
  aggregation is permitted BECAUSE it is cheap, and a regression would not fail
  any other test — it would slowly make the synchronous path a bad idea. So the
  bound is asserted where the grant is exercised, not only where the arithmetic
  is.

The number of aggregations is the clause's, verbatim (~5,250), not a smaller
stand-in. The budget is the sibling's knob (`AEH_TEST_AGG_PERF_SECONDS`, default
10.0) — one knob per environment-sensitive constant, not a second one.

Isolation: rung 3 (real store, real workers, real stored verdicts off the
ledger); the socket guard is autouse.
"""

from __future__ import annotations

import os
import time

import pytest

from aeh.store import open_store
from tests.contract.agg._drive import (
    criterion_bands,
    drive_scored_run,
    stored_verdicts,
)
from tests.support.agg_vocabulary import signals, criterion, agg_config
from tests.support.impl import AGG_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = [pytest.mark.contract]

#: `NFR-AGG-03`'s figure, verbatim — the load the completion path must carry.
SWEEP_N = 5_250
#: The sibling's knob, reused — one knob per constant (the four-seams rule).
BUDGET_SECONDS = float(os.environ.get("AEH_TEST_AGG_PERF_SECONDS", "10.0"))
#: The sibling's per-call ceiling: the design says microseconds, so a
#: millisecond-scale aggregation fails even inside the wall-clock budget.
_PER_CALL_CEILING_SECONDS = 0.001

_COHORT = ORCH_COHORT_ID
_SUBMISSION = "SYN-C13"
_CRITERION = "C1"


def test_tc_agg_c13_the_completion_path_aggregates_inline_within_the_budget(
    tmp_data_dir, make_fixture_provider
):
    """`TC-AGG-C13` (`CT-AGG-13`, perf / rung 3, synchronous-path budget, P1) — a
    real driven run's stored three-judge panel, aggregated INLINE at the stated
    load: the exact synchronous call the clause grants the consumer, budgeted
    where the grant is exercised. The verdicts come off the ledger; nothing is
    mocked, and the batch is the clause's own ~5,250 figure."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")

    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        # A `holistic` criterion: the shipped enumeration's base depth for it is
        # 3 (`FR-SETUP-08`), so the drive judges a real three-judge panel — the
        # panel shape every completion-path consumer aggregates.
        _, run_id, _ = drive_scored_run(
            store, provider, submissions=(_SUBMISSION,),
            criterion_specs=[{"criterion_id": _CRITERION, "kind": "open",
                              "scoring_model": "holistic", "band_count": 2}],
        )
        rows = stored_verdicts(store, run_id, _SUBMISSION, _CRITERION)
        assert len(rows) == 3, (
            "fixture bug: the driven run did not store a three-judge panel — the "
            "inline aggregation below would not be the completion path's call"
        )
        crit = criterion(criterion_bands(store, _CRITERION),
                         criterion_id=_CRITERION, scoring_model="holistic")

        started = time.perf_counter()
        results = [
            aggregate(rows, crit, signals(), config=agg_config())
            for _ in range(SWEEP_N)
        ]
        elapsed = time.perf_counter() - started

        first = results[0]
        assert first.band and first.judge_count == 3, (
            "fixture bug: the inline call did not aggregate the stored panel — "
            "the timing below would bound nothing"
        )
        assert elapsed < BUDGET_SECONDS, (
            f"{SWEEP_N} inline aggregations over the run's stored panel took "
            f"{elapsed:.3f}s (budget {BUDGET_SECONDS}s) — a consumer may "
            "aggregate synchronously on the completion path only while it adds "
            "negligible wall clock (CT-AGG-13, NFR-AGG-03); raise "
            "AEH_TEST_AGG_PERF_SECONDS only on a genuinely slower box"
        )
        per_call = elapsed / SWEEP_N
        assert per_call < _PER_CALL_CEILING_SECONDS, (
            f"the completion path's mean aggregation time is "
            f"{per_call * 1e6:.0f} µs — the clause says microseconds each; a "
            "millisecond-scale aggregation makes the synchronous grant a bad "
            "idea even inside the budget (CT-AGG-13)"
        )
    finally:
        store.close()
