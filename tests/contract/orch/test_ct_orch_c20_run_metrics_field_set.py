"""`TC-ORCH-C20` — `run_metrics` is written IN FULL, by contract name (§6.11.7).

`CT-ORCH-20`'s clause: every dispatch pass ends in a flush that persists the run's
cumulative signals, and the metric NAMES are the contract — `M-STATS` and the
acceptance gate read these by name (RISK-35), so a dropped field is the silent
failure: the reader defaults to null and the operator record lies. The oracle is
therefore **set equality** against the contract list — a flush that writes fourteen
of the sixteen names fails, and so does one that invents a seventeenth — asserted
over a run that gives every group of the list a real producer:

- **tokens, cache, cost, build** — model calls through the transport seam, the
  answers' figures accrued to the run's counters (`CT-PROV-11`'s shape);
- **retries and rate-limit counters** — the seam raises `RateLimitedError` once
  with a `retry-after:` figure, the expected-not-an-error path (`RES-11`): the
  counters increment, the honoured wait accrues, and the unit requeues without
  consuming an attempt;
- **quarantined units** — the failure taxonomy (`FR-ORCH-18`) at its ceiling, one
  unit `fail()`-ed to `quarantined` mid-run;
- **escalated units** — a widened panel riding the dispatch loop itself;
- **total units, wall clock, peak concurrency, estimated completion, model swaps** —
  the dispatch loop's own counters and ledger-derived totals.

The VALUES reconcile beside the names — each metric equals the fixture-observable
it summarizes (`_flush_run_metrics`'s own sentence: "a metric can never tell a
different story from the rows it summarizes"): the token and cost totals equal what
the seam actually answered, the rate-limit counters equal the one 429 the seam
raised, `total_units`/`escalated_units`/`quarantined_units` equal the ledger's
counts, and `resolved_build` names the build the answers carried.

The plan's summary line names "estimated and actual cost": the metrics table
carries `actual_cost` (the answers' billed sum); the ESTIMATE is the run row's
`cost_estimate` (`FR-ORCH-15` — the estimate precedes dispatch, written at
`start()` from the provider seam's per-unit figures, NULL where no estimator was
bound — a fabricated zero would read as a measured price). This case drives both:
`provider=` bound for the estimate, the transport seam for the actuals, and the
run-row figure asserted beside the metrics.

Isolation: rung 2 — real store, real package, real ledger, the real dispatch loop;
the transport and cost seams are the only doubles, and the seam is the shape the
dispatch pass binds (`Orchestrator(store, transport=...)`).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aeh.orch import Orchestrator, WorkError
from aeh.prov import Completion, RateLimitedError
from aeh.store import open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_document, seed_run

pytestmark = [pytest.mark.contract]

_RUN_ID = "run-c20-metrics"

_SUBMISSIONS = ("SYN-001", "SYN-002", "SYN-003")

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
     "band_count": 2},
    {"criterion_id": "C2", "kind": "mcq"},
)

#: The contract list (`CT-ORCH-20`): the names `run_metrics` carries for a
#: dispatched run, read back by set equality — a dropped field fails, a null-
#: defaulted field fails, an invented field fails. TEXT rides the REAL-affinity
#: column beside the floats (`resolved_build` is a label, not a measurement).
_CONTRACT_METRIC_NAMES = frozenset({
    "transport_retries",
    "rate_limited_calls",
    "rate_limit_wait_s",
    "tokens_in",
    "tokens_out",
    "cache_hit_rate",
    "total_units",
    "escalated_units",
    "quarantined_units",
    "wall_clock_ms",
    "peak_concurrency",
    "estimated_completion_s",
    "actual_cost",
    "model_swap_count",
    "model_swap_duration_ms",
    "resolved_build",
})

_UNIT_ESTIMATE = Decimal("0.10")
_ANSWER_COST = Decimal("0.25")


class _Seam:
    """The transport and cost seam in one: one `RateLimitedError` with an explicit
    `retry-after` (the honoured wait the metrics must carry), then completions whose
    figures the test reconciles against the flushed metrics; `estimate_cost` is the
    provider seam `FR-ORCH-15`'s estimate reads."""

    def __init__(self) -> None:
        self.rate_limited = 0
        self.completed = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cache_tokens = 0
        self.cost = Decimal("0")
        self.estimates = 0

    def call(self, request: object) -> Completion:
        if self.rate_limited == 0:
            self.rate_limited += 1
            raise RateLimitedError(
                "429 too many requests; retry-after: 1.5 seconds"
            )
        self.completed += 1
        self.tokens_in += 7
        self.tokens_out += 5
        self.cache_tokens += 3
        self.cost += _ANSWER_COST
        return Completion(
            text="synthetic band: B",
            tokens_in=7,
            tokens_out=5,
            latency_ms=1,
            resolved_build="build-ct-c20-seam",
            cached_prefix_tokens=3,
            cost=_ANSWER_COST,
        )

    def estimate_cost(self, unit: object) -> Decimal:
        self.estimates += 1
        return _UNIT_ESTIMATE


def test_tc_orch_c20_run_metrics_written_in_full_by_contract_name(
    tmp_data_dir, monkeypatch
):
    """Over a run driven through the real dispatch loop with a 429, a quarantine and
    a widened panel, `run_metrics` holds exactly the contract names — and each
    reconciles with what the run actually did."""
    # The escalation's units must DISPATCH, not defer: the 0.30 default budget is
    # C16's subject and would defer 1-of-3-pairs-escalated (0.33 > 0.30) for reasons
    # this clause does not name. The breaker's 20-window default is far above this
    # cohort's 3 submissions, so no trip interferes; attempts stay at the default 3,
    # which is the quarantine ceiling the drive relies on.
    monkeypatch.setenv("HARNESS_ORCH_ESCALATION_BUDGET", "1.0")
    monkeypatch.setenv("HARNESS_ORCH_MAX_ATTEMPTS", "3")

    seam = _Seam()
    store = open_store(tmp_data_dir)
    try:
        _, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS,
            criteria=_CRITERIA, transport=seam, run_id=_RUN_ID,
        )
        # The same ledger, re-bound with BOTH seams: the transport the dispatch
        # pass calls and the provider the estimate reads (FR-ORCH-15).
        orchestrator = Orchestrator(store, transport=seam, provider=seam)
        for submission_id in _SUBMISSIONS:
            seed_document(store, submission_id)

        orchestrator.enumerate_units(run_id)
        assert orchestrator.start(run_id) == "running"
        # The estimate preceded dispatch (FR-ORCH-15): the run row carries the
        # provider seam's summed per-unit figure, not a fabricated zero.
        run_row = store.cohort(ORCH_COHORT_ID).query(
            "SELECT cost_estimate FROM run WHERE run_id = :r", r=run_id
        )[0]
        assert run_row["cost_estimate"] is not None, (
            "start() wrote no cost_estimate although a provider seam was bound — "
            "the estimate is absent where the plan requires it displayed, and the "
            "estimated-cost half of CT-ORCH-20 would be untested"
        )
        assert Decimal(run_row["cost_estimate"]) == _UNIT_ESTIMATE * seam.estimates, (
            f"the run row's cost_estimate {run_row['cost_estimate']!r} is not the "
            f"provider seam's summed figure ({_UNIT_ESTIMATE} x {seam.estimates} "
            "units) — the displayed estimate tells a different story from the seam "
            "the run will dispatch against"
        )

        # The quarantine: one BASE score unit fail()-ed to the ceiling — three
        # reports, the third lands `quarantined` with its last_error retained
        # (FR-ORCH-18). A base score unit, not an extract unit: a quarantined
        # extraction gates its criterion's scoring pending forever (the scoring
        # waits for evidence that will never come) and the run could not complete
        # for the quarantine's own reasons; a quarantined score unit only removes
        # one judged grade, which is the taxonomy's "fail the unit, never the run".
        victim = store.cohort(ORCH_COHORT_ID).query(
            "SELECT work_id FROM work_unit WHERE run_id = :r "
            "AND stage = 'score' AND origin = 'base' "
            "AND submission_id = 'SYN-002' "
            "ORDER BY work_id LIMIT 1",
            r=run_id,
        )[0]["work_id"]
        for attempt in range(3):
            orchestrator.fail(victim, WorkError(f"synthetic defect #{attempt}"))
        status = store.cohort(ORCH_COHORT_ID).query(
            "SELECT status FROM work_unit WHERE work_id = :w", w=victim
        )[0]["status"]
        assert status == "quarantined", (
            f"the thrice-failed unit is {status!r}, not 'quarantined' — the "
            "quarantined_units metric below would reconcile against nothing"
        )

        # The escalation: SYN-001's panel widens, and its widened units ride the
        # dispatch loop itself (the judged batch) — the escalated_units metric's
        # subjects.
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            reports = orchestrator.enqueue_escalation(tx, ("SYN-001", "C1"))
        assert sum(rep.units_inserted for rep in reports) == 2, (
            "the escalation inserted no widened units — the escalated_units "
            "metric would reconcile against nothing"
        )

        report = orchestrator.progress(run_id)
        for _ in range(64):
            if report.complete:
                break
            report = orchestrator.progress(run_id)
        assert report.complete, (
            "the metrics run never exhausted — a flush over a partial drive would "
            "let a metric stand for a signal the run never reached"
        )
        assert seam.completed >= 1 and seam.rate_limited == 1, (
            "precondition: the seam answered no completions or recorded no 429 — "
            "the token and rate-limit metrics below would reconcile against "
            "nothing"
        )

        # --- the oracle: set equality against the contract list. ---
        rows = store.durable().query(
            "SELECT metric, value FROM run_metrics WHERE run_id = :r", r=run_id
        )
        written = {row["metric"]: row["value"] for row in rows}
        assert set(written) == set(_CONTRACT_METRIC_NAMES), (
            "run_metrics is not written in full: missing="
            f"{sorted(set(_CONTRACT_METRIC_NAMES) - set(written))} unexpected="
            f"{sorted(set(written) - set(_CONTRACT_METRIC_NAMES))} — the names are "
            "the contract (CT-ORCH-20): M-STATS and the acceptance gate read these "
            "by name (RISK-35), so a dropped field fails rather than defaulting "
            "to null"
        )

        # --- the values reconcile with the run that produced them. ---
        unit_rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT status, COUNT(*) AS n FROM work_unit WHERE run_id = :r "
            "GROUP BY status",
            r=run_id,
        )
        counts = {row["status"]: row["n"] for row in unit_rows}
        ledger_total = sum(counts.values())
        ledger_escalated = store.cohort(ORCH_COHORT_ID).query(
            "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :r "
            "AND origin = 'escalation'",
            r=run_id,
        )[0]["n"]

        assert float(written["total_units"]) == ledger_total, (
            f"total_units={written['total_units']!r} but the ledger holds "
            f"{ledger_total} units — the metric tells a different story from the "
            "rows it summarizes"
        )
        assert float(written["escalated_units"]) == ledger_escalated, (
            f"escalated_units={written['escalated_units']!r} but the ledger holds "
            f"{ledger_escalated} escalation-origin units"
        )
        assert ledger_escalated >= 1, (
            "the drive escalated nothing — the escalated_units metric would be "
            "zero by absence, not by measurement"
        )
        assert float(written["quarantined_units"]) == counts.get("quarantined", 0), (
            f"quarantined_units={written['quarantined_units']!r} but the ledger "
            f"holds {counts.get('quarantined', 0)} quarantined units"
        )
        assert float(written["tokens_in"]) == seam.tokens_in, (
            f"tokens_in={written['tokens_in']!r} but the seam answered "
            f"{seam.tokens_in} — the accrued counters and the flushed metric "
            "disagree (CT-PROV-11's shape)"
        )
        assert float(written["tokens_out"]) == seam.tokens_out
        assert float(written["cache_hit_rate"]) == pytest.approx(
            seam.cache_tokens / seam.tokens_in
        ), (
            f"cache_hit_rate={written['cache_hit_rate']!r} but the seam's answers "
            f"carry {seam.cache_tokens}/{seam.tokens_in} cached prefix tokens"
        )
        assert float(written["actual_cost"]) == pytest.approx(float(seam.cost)), (
            f"actual_cost={written['actual_cost']!r} but the seam billed "
            f"{seam.cost} across its answers"
        )
        assert float(written["rate_limited_calls"]) == 1.0, (
            f"rate_limited_calls={written['rate_limited_calls']!r} but the seam "
            "raised exactly one 429 — the counter counted a call that never "
            "happened or missed the one that did"
        )
        assert float(written["transport_retries"]) == 1.0
        assert float(written["rate_limit_wait_s"]) == pytest.approx(1.5), (
            f"rate_limit_wait_s={written['rate_limit_wait_s']!r} but the 429 "
            "carried retry-after: 1.5 — the honoured wait did not accrue "
            "(FR-PROV-07's shape)"
        )
        assert written["resolved_build"] == "build-ct-c20-seam", (
            f"resolved_build={written['resolved_build']!r} — the build label the "
            "answers carried never reached the metrics"
        )
        assert float(written["peak_concurrency"]) >= 1.0
        assert float(written["wall_clock_ms"]) >= 0.0
        assert float(written["estimated_completion_s"]) >= 0.0
        assert float(written["model_swap_count"]) >= 0.0
        assert float(written["model_swap_duration_ms"]) >= 0.0
    finally:
        store.close()
