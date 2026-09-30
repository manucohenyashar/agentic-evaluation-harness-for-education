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
        """The run's counter surface (`CT-REVIEW-18`): every name in
        ``OBSERVABILITY_COUNTERS`` as a key, with the value the service's own
        bookkeeping supports. ``blind_completion_rate`` is measured from #111's
        blind flow — answered refs over drawn refs for this run — and is
        ``None`` for a run that never drew, which stays an unmeasured rate,
        never a silent zero.
        ``override_rate_by_criterion`` is a per-criterion *count* of
        edit/override labels for now — the denominator a rate divides by (the
        judgments the criterion received) is #115's read over the stored
        labels, and a count is the honest numerator the service itself
        observed; the name is the contract's (`CT-REVIEW-18`'s plan), the
        shape is decided there."""
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
        """The ordered emissions the run produced (`CT-REVIEW-18`'s read back)."""
        return tuple(self._emissions.get(run_id, ()))

    def exhaust_budget_on(self, criterion_id: str, administration_id: str) -> None:
        """Record that a criterion exhausted its budget on one administration
        (`CT-REVIEW-18`'s exhaustion signal). A repeat for an administration
        already recorded does not extend the streak: the signal is that the
        criterion exhausted, once per administration."""
        streak = self._exhaustions.setdefault(criterion_id, [])
        if administration_id not in streak:
            streak.append(administration_id)

    def alerts(self) -> tuple[ReviewAlert, ...]:
        """The standing alerts: one per criterion whose exhaustion streak has
        reached `ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS`, recomputed from the
        retained sequence — never reset between terms (`CT-REVIEW-18`)."""
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
        """One observability emission, stamped at the service's clock and
        attributed to the run (`CT-REVIEW-18`'s seam 4)."""
        self._emissions.setdefault(run_id, []).append(
            CounterEmission(at=self._clock(), names=names, values=dict(values))
        )

    def _record_action_emission(self, labels: Sequence[LabelRecord]) -> None:
        """The per-action emission (`CT-REVIEW-18`): minutes used and the
        running mean, emitted together at the instant the labels were written —
        one emission per action, not per label (a group action is one decision)."""
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
