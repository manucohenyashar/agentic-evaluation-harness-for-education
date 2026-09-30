"""The run's progress report, its alerts, and its persisted metrics."""

from __future__ import annotations

import json
from typing import Any, Mapping

from aeh.store import store_metrics

from .constants import _JSON_SEPARATORS, STAGE_SCORE
from .statements import ORCH_STATEMENTS
from .settings import BACKPRESSURE_DIVISOR_DEFAULT, BACKPRESSURE_DIVISOR_ENV, _env_int
from .alerts import (
    _as_float,
    evaluate_alerts,
    _mapping_get,
    _millis_between,
    paused_milliseconds,
    _provider_config,
    RunAlert,
)
from .reports import estimated_completion_seconds, ProgressReport


class ReportingMixin:
    """Builds the progress report, evaluates the run's alerts and writes its metrics."""

    def flush_metrics(self, run_id: str) -> None:
        """Save the run's dispatch counters to `run_metrics` without running a dispatch pass
        (#596).

        `progress()` flushes after every pass; model calls made after the last pass (synthesis)
        would otherwise accrue into counters nothing persists. `progress()` itself is not the
        flush for them: its claim walk serves whichever open run it reaches first. A run with
        no dispatch state (no pass ever ran in this process) has nothing to flush.
        """
        cohort, run_row = self._find_run(run_id)
        state = self._dispatch_states.get(run_id)
        if state is None:
            return
        report = self._progress_report(cohort, run_row, run_id, state)
        self._flush_run_metrics(cohort, run_id, state, report)

    def _progress_report(
        self,
        cohort: Any,
        run_row: Any,
        run_id: str,
        state: dict[str, Any] | None,
    ) -> ProgressReport:
        """Build the progress report from the ledger's own counts (FR-ORCH-23).

        Every figure is a count of rows — the ledger is the only bookkeeping, so a
        report computed from anything else would drift on exactly the growing ledger
        `CT-ORCH-09` exists for. The position fields walk the first open unit: its
        stage, and its criterion's and judge's 1-based positions in the run's
        criterion list and panel order — with no open work the report points at the
        end of both axes. The estimate feeds `estimated_completion_seconds` the
        ledger's own totals and the observed escalation rate (`FR-ORCH-24`), and the
        completion predicate is ledger-derived (`FR-ORCH-12`): nothing pending, and
        no in-flight unit — a scoring judgment in flight can still disagree with its
        panel and spawn an escalation, so a run with one is not done.
        """
        counts: dict[str, int] = {}
        for row in cohort.query(
            ORCH_STATEMENTS["select_run_status_counts"], run_id=run_id
        ):
            counts[row["status"]] = int(row["n"])
        done = counts.get("done", 0)
        in_flight = counts.get("leased", 0)
        pending = counts.get("pending", 0)
        quarantined = counts.get("quarantined", 0)
        by_unit: dict[tuple[str, str | None, str | None], int] = {}
        for row in cohort.query(ORCH_STATEMENTS["select_run_by_unit"], run_id=run_id):
            by_unit[(row["stage"], row["criterion_id"], row["judge_id"])] = int(
                row["n"]
            )
        # The criterion axis rides the same aggregate (see the statement's note):
        # every criterion the ledger holds appears in some group's key.
        criteria = sorted({criterion for _, criterion, _ in by_unit})
        arms = self._panel_arms(run_row["panel_config"])
        open_rows = cohort.query(
            ORCH_STATEMENTS["select_run_first_open"], run_id=run_id
        )
        first = open_rows[0] if open_rows else None
        stage = first["stage"] if first is not None else STAGE_SCORE
        criterion_index = (
            criteria.index(first["criterion_id"]) + 1
            if first is not None and first["criterion_id"] in criteria
            else len(criteria)
        )
        judge_index = (
            arms.index(first["judge_id"]) + 1
            if first is not None and first["judge_id"] in arms
            else len(arms)
        )
        _processed, _escalated, rate = self._escalation_rate(cohort.query, run_id)
        # `FR-ORCH-33`: ONE elapsed reading, the ledger's, for both the dispatching and
        # the report-only path. The monotonic branch measured how long this PROCESS had
        # been running, so a resumed run extrapolated its throughput from the restart —
        # and a run paused overnight extrapolated it from the pause. The wall clock
        # excludes paused intervals, which is what makes it a throughput window rather
        # than a stopwatch left running.
        elapsed = self._run_wall_clock_ms(cohort, run_id) / 1000.0
        estimate = estimated_completion_seconds(
            completed=done,
            remaining=pending + in_flight,
            elapsed_seconds=elapsed,
            escalation_rate_so_far=rate,
        )
        report = ProgressReport(
            stage=stage,
            criterion_index=criterion_index,
            criterion_total=len(criteria),
            judge_index=judge_index,
            judge_total=len(arms),
            done=done,
            in_flight=in_flight,
            pending=pending,
            quarantined=quarantined,
            escalation_rate_so_far=rate,
            estimated_completion=estimate,
        )
        leased_score = int(
            cohort.query(
                ORCH_STATEMENTS["select_run_leased_score"], run_id=run_id
            )[0]["n"]
        )
        # The report's concurrency is the cap the NEXT pass will run at (the
        # reduction a 429/OOM landed this pass is already in `cap`; the backpressure
        # clamp is sensed again at flush time — the operator reads the width that
        # takes effect, `RES-11`/`RES-13`'s observable back-off, and a store still
        # signalling pressure reads as the clamped width).
        concurrency = 0
        if state is not None:
            concurrency = state["cap"]
            if store_metrics(self._store).get("backpressure_active"):
                concurrency = max(
                    concurrency
                    // _env_int(
                        BACKPRESSURE_DIVISOR_ENV, BACKPRESSURE_DIVISOR_DEFAULT
                    ),
                    1,
                )
        object.__setattr__(
            report,
            "_extras",
            {
                "complete": pending == 0 and in_flight == 0 and leased_score == 0,
                "concurrency": concurrency,
                "by_unit": by_unit,
                # `FR-ORCH-32`: the five §3.7 conditions, evaluated over state this pass
                # already read. The rules live in a pure function so they can be
                # exercised one condition at a time; `progress()` is where the operator
                # actually meets them.
                "alerts": self._run_alerts(cohort, run_id, run_row, rate),
            },
        )
        return report

    def _run_alerts(
        self, cohort: Any, run_id: str, run_row: Any, rate: float
    ) -> tuple[RunAlert, ...]:
        """The run's fired alerts (FR-ORCH-32), read from the ledger and evaluated.

        Gathering is here and the RULES are in `evaluate_alerts`: the split is what keeps
        each condition independently breachable without a store (`TC-ORCH-36`'s rung), and
        what stops the thresholds being spelled twice.
        """
        snapshot = _provider_config(run_row)
        ceiling = snapshot.get("cost_ceiling")
        budget_state = {
            "escalation_rate": rate,
            "ceiling": _as_float(ceiling) if ceiling is not None else 0.0,
            "spend": _as_float(_mapping_get(run_row, "cost_spend")),
        }
        # The RUN-scoped read: `select_breaker` answers about one criterion, and the
        # alert is about the run having any tripped breaker at all.
        breaker_rows = cohort.query(
            ORCH_STATEMENTS["select_run_breakers"], run_id=run_id
        )
        # This run's cache hit rate, and the rates EVERY OTHER RUN IN THE STORE recorded
        # — the baseline a collapse is measured against. Without enough history there is
        # no baseline and `evaluate_alerts` declines to fire, the honest answer for a
        # first run. The baseline is deliberately unscoped and unwindowed for now, which
        # is a calibration weakness disclosed on #370: runs of different packages, panels
        # and backends widen the variance, and a wide variance is what lets a genuine
        # collapse sit inside the sigma band.
        durable = self._store.durable()
        # `-1.0` is `evaluate_alerts`' declared "not measured" sentinel, and starting at
        # 0.0 instead defeated it: `progress()` evaluates alerts BEFORE the pass flushes,
        # so every run's first poll in a store with enough prior runs reported a perfect
        # cache as a total collapse. A rate nobody has measured is not a rate of zero.
        current = -1.0
        tokens_in = 0.0
        for row in durable.query(
            ORCH_STATEMENTS["select_run_metric_values"], run_id=run_id
        ):
            metric = str(_mapping_get(row, "metric", ""))
            if metric == "cache_hit_rate":
                current = _as_float(_mapping_get(row, "value"), -1.0)
            elif metric == "tokens_in":
                tokens_in = _as_float(_mapping_get(row, "value"))
        if tokens_in <= 0:
            # `_flush_run_metrics` records `cache_hit_rate = 0.0` for a pass that sent no
            # tokens, because the field is under CT-ORCH-20's set-equality contract and
            # cannot be omitted. A run that has dispatched nothing — idle, paused,
            # enumerated but not started — has no cache behaviour to judge, so that zero
            # is read here as the absence it is rather than as a collapse that would
            # alert forever.
            current = -1.0
        history = [
            _as_float(_mapping_get(row, "value"))
            for row in durable.query(
                ORCH_STATEMENTS["select_prior_cache_hit_rates"], run_id=run_id
            )
        ]
        return evaluate_alerts(
            run_row=run_row,
            metrics={"escalation_rate": rate, "cache_hit_rate": current},
            breaker_rows=breaker_rows,
            budget_state=budget_state,
            cache_history=history,
        )

    def _flush_run_metrics(
        self,
        cohort: Any,
        run_id: str,
        state: dict[str, Any],
        report: ProgressReport,
    ) -> None:
        """Save this pass's running totals to `run_metrics` (CT-ORCH-20).

        M-ORCH is the table's sole writer (`CT-STORE-03`): the dispatch loop's own
        counters plus the ledger-derived totals, written at the end of every pass —
        a poll that flushes nothing would leave `M-STATS` reading a stale record on
        exactly the runs an operator is watching. The totals are computed FROM the
        ledger at flush time (the report's own counts), so a metric can never tell a
        different story from the rows it summarizes.
        """
        escalated = int(
            cohort.query(
                ORCH_STATEMENTS["select_run_escalation_units"], run_id=run_id
            )[0]["n"]
        )
        total_units = report.done + report.in_flight + report.pending + (
            report.quarantined
        )
        tokens_in = state["tokens_in"]
        metrics: dict[str, Any] = {
            "transport_retries": float(state["transport_retries"]),
            "rate_limited_calls": float(state["rate_limited_calls"]),
            "rate_limit_wait_s": float(state["rate_limit_wait_s"]),
            "tokens_in": float(tokens_in),
            "tokens_out": float(state["tokens_out"]),
            "cache_hit_rate": (
                state["cache_tokens"] / tokens_in if tokens_in else 0.0
            ),
            "total_units": float(total_units),
            "escalated_units": float(escalated),
            "quarantined_units": float(report.quarantined),
            "wall_clock_ms": self._run_wall_clock_ms(cohort, run_id),
            "peak_concurrency": float(state["peak_concurrency"]),
            "estimated_completion_s": float(report.estimated_completion),
            "actual_cost": float(state["cost"]),
            "model_swap_count": float(state["residency"]["swaps"]),
            "model_swap_duration_ms": float(state["residency"]["swap_ms"]),
        }
        # FR-ORCH-38 / CT-PROV-24: the decision provider's counters, by their contract names,
        # when one is bound (a provider without counters — the fixture double — reports none).
        decision_counters = getattr(self._decision_provider, "decision_counters", None)
        if decision_counters is not None:
            for name in ("decision_calls", "decision_tokens_in", "decision_transport_retries",
                         "decision_rate_limited_calls", "decision_actual_cost",
                         "decision_provider_unreported"):
                metrics[name] = float(getattr(decision_counters, name))
            # CT-PROV-24 / FR-PROV-29: `actual_cost` is the sum of both surfaces.
            metrics["actual_cost"] = float(state["cost"] + decision_counters.decision_actual_cost)
        # TEXT rides the REAL-affinity column as TEXT: these are labels, not
        # measurements, and the EAV shape carries both.
        if state["resolved_build"]:
            metrics["resolved_build"] = state["resolved_build"]
        # `FR-ORCH-33`: the SET over the run, as a JSON list. A run can resolve more than
        # one build — a judge dropped after an OOM, a panel narrowed mid-run — and the
        # singular column recorded only whichever one landed first, which is the least
        # interesting of them. Sorted, so two runs that resolved the same builds write
        # the same bytes (`NFR-ORCH-05`).
        resolved = self._run_resolved_builds(cohort, run_id, state)
        if resolved:
            metrics["resolved_builds"] = json.dumps(
                resolved, separators=_JSON_SEPARATORS
            )
        run_row = self._run_row_in(cohort, run_id)
        if run_row is not None:
            estimate = _mapping_get(run_row, "cost_estimate")
            if estimate is not None:
                metrics["estimated_cost"] = str(estimate)
            # `cost_currency` and `retention_setting` live in the run's FROZEN backend
            # snapshot (`run.provider_config`), not in current configuration: a metric
            # about a run must describe the run as it was started, and reading today's
            # config would relabel a finished run's figures on the next poll.
            snapshot = _provider_config(run_row)
            for key in ("cost_currency", "retention_setting"):
                value = snapshot.get(key)
                if value is not None:
                    metrics[key] = str(value)
        self.record_run_metrics(run_id, metrics)

    def _run_wall_clock_ms(self, cohort: Any, run_id: str) -> float:
        """Time since `run.started_at`, minus every paused period (FR-ORCH-33).

        Read from the LEDGER, never from `time.monotonic()`. A monotonic anchor measures
        how long *this process* has been running, so a run resumed after a restart
        reported a clock that began at the restart — and a run paused overnight reported
        the pause as work. Both readings are wrong in the direction that flatters the
        run, which is the direction an operator cannot afford.
        """
        run_row = self._run_row_in(cohort, run_id)
        started_at = _mapping_get(run_row, "started_at") if run_row is not None else None
        if not started_at:
            return 0.0
        now = self._wall_now()
        elapsed = _millis_between(started_at, now)
        paused = paused_milliseconds(
            cohort.query(ORCH_STATEMENTS["select_applied_control"], run_id=run_id),
            now=now,
        )
        return max(elapsed - paused, 0.0)

    def _run_resolved_builds(
        self, cohort: Any, run_id: str, state: Mapping[str, Any]
    ) -> list[str]:
        """Every model build this run used, sorted: this pass's builds plus those earlier passes
        recorded, so a restart does not shorten the list."""
        seen: set[str] = set()
        if state.get("resolved_build"):
            seen.add(str(state["resolved_build"]))
        # `run_metrics` is Tier D (`record_run_metrics` writes it there), so the prior
        # passes' rows are read from the durable handle, not the cohort's.
        for row in self._store.durable().query(
            ORCH_STATEMENTS["select_run_metric_values"], run_id=run_id
        ):
            metric = str(_mapping_get(row, "metric", "") or "")
            value = _mapping_get(row, "value")
            if metric == "resolved_build" and value:
                seen.add(str(value))
            elif metric == "resolved_builds" and value:
                try:
                    seen.update(str(item) for item in json.loads(str(value)))
                except (ValueError, TypeError):
                    continue
        return sorted(seen)

    def record_run_metrics(self, run_id: str, metrics: Mapping[str, Any]) -> None:
        """Write one run's metrics as one row per metric (CT-ORCH-20).

        **A reserved name, landed** (`#65` reserved it for TS-25; the design's Protocol
        has no metrics member): whether the dispatch flushes through it internally or a
        caller records explicitly, the write is this method's — one transaction, one
        REPLACE per metric, so a re-flush updates in place and the table never holds
        two rows for one signal. M-ORCH is `run_metrics`' sole writer (`CT-STORE-03`).
        """
        if not metrics:
            return
        durable = self._store.durable()
        with durable.transaction() as tx:
            for name, value in metrics.items():
                tx.execute(
                    ORCH_STATEMENTS["insert_run_metric"],
                    run_id=run_id,
                    metric=str(name),
                    value=value,
                )
