"""Review counters, their emissions, and the budget-exhaustion alert."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .settings import (
    _ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS,
    _OBSERVABILITY_COUNTERS,
    REVIEW_BUDGET_EXHAUSTION_ALERT,
)
from .records import CounterEmission, LabelRecord, ReviewAlert


class ObservabilityMixin:
    """The run's counters, their emissions, and the budget-exhaustion alerts."""

    def observability_counters(self, run_id: str) -> dict[str, Any]:
        """The run's counters (CT-REVIEW-18): every name in `OBSERVABILITY_COUNTERS`, with the
        value the service's own records support. `blind_completion_rate` is answered over drawn
        references, or None for a run that never drew. `override_rate_by_criterion` is, for now, a
        count of edit and override labels per criterion, not yet a rate."""
        builds = self._builds.get(run_id)
        labels = self._run_labels.get(run_id, [])
        drawn = self._blind_drawn.get(run_id)
        if builds is None and not labels and not drawn:
            return {name: None for name in _OBSERVABILITY_COUNTERS}
        est = builds["est_seconds"] if builds else ()
        used = sum(label.review_seconds for label in labels)
        judged = [label for label in labels if label.label_type in ("edit", "override")]
        by_criterion: dict[str, float] = {}
        for label in judged:
            by_criterion[label.criterion_id] = by_criterion.get(label.criterion_id, 0) + 1
        total = len(labels)
        return {
            "review_minutes_used": used / 60,
            "review_items_shown": builds["shown_items"] if builds else 0,
            "review_items_flagged": builds["flagged"] if builds else 0,
            "override_rate_by_criterion": dict(by_criterion),
            "group_action_usage_share": (
                (sum(1 for label in labels if label.via_group) / total) if total else None
            ),
            # #111's blind flow, measured: answered refs over drawn refs for
            # this run; None when the run never drew — an unmeasured rate,
            # never a silent zero.
            "blind_completion_rate": self._blind_rate(run_id),
            "mean_review_seconds": (
                sum(label.review_seconds for label in labels) / total if total else None
            ),
            "mean_est_seconds": (
                sum(est) / len(est) if est else None
            ),
        }

    def counter_emissions(self, run_id: str) -> tuple[CounterEmission, ...]:
        """The run's counter emissions, in order (CT-REVIEW-18)."""
        return tuple(self._emissions.get(run_id, ()))

    def exhaust_budget_on(self, criterion_id: str, administration_id: str) -> None:
        """Record that a criterion used up its review budget in one administration (CT-REVIEW-18).
        Recording the same administration again does not lengthen the streak."""
        streak = self._exhaustions.setdefault(criterion_id, [])
        if administration_id not in streak:
            streak.append(administration_id)

    def alerts(self) -> tuple[ReviewAlert, ...]:
        """The standing alerts: one per criterion whose run of budget exhaustion has reached
        `ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS`, recomputed from the kept history and never reset
        between terms (CT-REVIEW-18)."""
        return tuple(
            ReviewAlert(
                name=REVIEW_BUDGET_EXHAUSTION_ALERT,
                criterion_id=criterion_id,
                consecutive_administrations=len(streak),
                administrations=tuple(streak),
            )
            for criterion_id, streak in self._exhaustions.items()
            if len(streak) >= _ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS
        )

    def _record_emission(
        self,
        run_id: str,
        names: tuple[str, ...],
        values: Mapping[str, Any],
    ) -> None:
        """Record one counter emission, stamped with the service's clock and attributed to the run
        (CT-REVIEW-18)."""
        self._emissions.setdefault(run_id, []).append(
            CounterEmission(at=self._clock(), names=names, values=dict(values))
        )

    def _record_action_emission(self, labels: Sequence[LabelRecord]) -> None:
        """The per-action emission (CT-REVIEW-18): minutes used and the running mean, emitted once
        per action when its labels are written (a group action is one decision)."""
        if not labels:
            return
        run_id = self._attribution_run()
        if run_id is None:
            return
        run_labels = self._run_labels.get(run_id, ())
        total = sum(label.review_seconds for label in run_labels)
        self._record_emission(
            run_id,
            ("review_minutes_used", "mean_review_seconds"),
            {
                "review_minutes_used": total / 60,
                "mean_review_seconds": total / len(run_labels) if run_labels else None,
            },
        )
