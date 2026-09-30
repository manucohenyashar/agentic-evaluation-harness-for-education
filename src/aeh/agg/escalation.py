"""Whether a cell needs more judges, and the ranking of criteria by urgency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aeh.pkg import NoValidationData

from .settings import (
    AGG_ESCALATION_ANOMALY_SIGMA,
    AGG_ESCALATION_NO_DATA_WEIGHT,
    AGG_ESCALATION_OVERRIDE_RATE,
    AGG_ESCALATION_SELF_CONFIDENCE_WEIGHT,
    AGG_ESCALATION_SIGNAL_WEIGHT,
    AGG_ESCALATION_THRESHOLD,
)
from .rows import _AGG_ABSENT, _AGG_FAVOURABLE, _row_field, _signal_adverse


@dataclass(frozen=True)
class EscalationDecision:
    """The escalation decision M-AGG returns to M-ORCH (`FR-AGG-08/09`, §3.8).

    `escalate` is the bool; `target_judge_count` carries FR-AGG-09's one-to-
    three-and-never-two (an even target is impossible by construction: the
    target is the next odd at least two above the current panel). `reasons`
    names each fired observable signal, in the policy's enumeration order —
    the observability seam: the enqueue this decision feeds is M-ORCH's
    (`FR-ORCH-09`), and this module returns the decision, never enqueues.

    Value equality is the point (`NFR-ORCH-04`'s purity corollary): the same
    inputs must decide the same way, and self-confidence is deliberately
    ABSENT from `reasons` — it shapes the concern and can never be the reason
    a decision escalated (R22). A caller diffing two decisions therefore
    diffs only the observables that actually fired.
    """

    escalate: bool
    target_judge_count: int
    reasons: tuple[str, ...] = ()


def _escalation_knob(config: Any, name: str, default: float) -> float:
    """One escalation knob, injected at the call (`CT-AGG-01`: never the
    environment). `config=None` or an absent attribute means the constant."""
    value = getattr(config, name, None) if config is not None else None
    return default if value is None else float(value)


def should_escalate(
    score: Any,
    criterion: Any,
    history: Any,
    baseline: Any,
    *,
    config: Any = None,
) -> EscalationDecision:
    """The escalation policy (`FR-AGG-08`, §3.8's `Aggregator.should_escalate`
    Protocol member as the module-level pure function, the same reading
    `aggregate` and `ordinal_alpha` take): decide whether a criterion score
    warrants a bigger panel, from observable signals only.

    Pure (`NFR-ORCH-04`, `CT-AGG-01`): the score row, the criterion, the
    criterion's override history and the package baseline are values; no
    store, no clock, no model call, no network, and no configuration beyond
    the arguments — `config` may carry any of `escalation_threshold`,
    `escalation_signal_weight`, `escalation_no_data_weight`,
    `escalation_self_confidence_weight`, `escalation_anomaly_sigma` and
    `escalation_override_rate` (each defaulting to its module constant).

    The decision is a concern level against the threshold. Each observable
    signal contributes `AGG_ESCALATION_SIGNAL_WEIGHT` when it fires (§7.1's
    enumeration, in order):

    1. **Interior band position** — the score sits in a declared band that is
       neither the top nor the bottom of the criterion's scale: the panel did
       not reach a scale edge, where bands are best discriminated. Read off
       the row's `ordinal` against `band_count` (the row's, else the
       criterion's); a row carrying neither is not making the claim, and the
       limb is skipped.
    2. **Adverse integrity signals** — each of the six M-INTEG fields read
       off the row: adverse (the opposite polarity, or a recorded `None` =
       not measured, fail-closed) fires; an absent field is no claim and
       skips its limb.
    3. **Uncited verdict** — the row's `uncited` mark.
    4. **Criterion override history** — `history.override_rate` above
       `AGG_ESCALATION_OVERRIDE_RATE` (more than half of the criterion's
       reviewed scores were overridden, the breaker's strict "more than
       half"), or the criterion already escalated before
       (`history.escalations`). A recorded no-data rate contributes
       `AGG_ESCALATION_NO_DATA_WEIGHT` — not a zero (CT-STATS-09), but not a
       trigger either.
    5. **Distributional anomaly** — the score's ordinal sits
       `AGG_ESCALATION_ANOMALY_SIGMA` standard deviations or further from the
       package baseline's expected band position. A baseline without a usable
       `std` is unmeasurable, not anomalous.

    Model self-confidence (`score.self_confidence`) enters once, weighted:
    `AGG_ESCALATION_SELF_CONFIDENCE_WEIGHT × (1 − self_confidence)`. It is
    never appended to `reasons` — a decision escalated on self-confidence
    alone is structurally impossible (its full-sweep contribution stays below
    the threshold, R22), so every reason is an observable a reviewer can go
    and look at. Absent, it contributes nothing: absence is no claim.

    Returns the `EscalationDecision`: `escalate`, the target panel depth (the
    next odd at least two above the current panel — 1 → 3, never 2,
    `FR-AGG-09`; `validate_escalation_plan` in `aeh.orch` is the consumer's
    odd-plan check) and `reasons`. Under the production constants a decision
    not to escalate carries the current panel depth unchanged and no reasons
    (every weight is sub-threshold alone, so nothing fires without escalating);
    an injected sub-threshold signal weight can fire a reason without reaching
    the threshold — the fired observables are recorded either way.
    """
    threshold = _escalation_knob(config, "escalation_threshold", AGG_ESCALATION_THRESHOLD)
    signal_weight = _escalation_knob(
        config, "escalation_signal_weight", AGG_ESCALATION_SIGNAL_WEIGHT
    )
    no_data_weight = _escalation_knob(
        config, "escalation_no_data_weight", AGG_ESCALATION_NO_DATA_WEIGHT
    )
    self_confidence_weight = _escalation_knob(
        config, "escalation_self_confidence_weight", AGG_ESCALATION_SELF_CONFIDENCE_WEIGHT
    )
    anomaly_sigma = _escalation_knob(
        config, "escalation_anomaly_sigma", AGG_ESCALATION_ANOMALY_SIGMA
    )
    override_rate_threshold = _escalation_knob(
        config, "escalation_override_rate", AGG_ESCALATION_OVERRIDE_RATE
    )

    concern = 0.0
    reasons: list[str] = []

    # 1. Interior band position — the panel did not reach a scale edge. A
    # recorded `None` on either figure is a recorded inconclusive, not a claim
    # (the same absent-vs-None reading as the signals below): the limb is
    # skipped, never crashed through.
    ordinal = _row_field(score, "ordinal")
    band_count = _row_field(score, "band_count")
    if band_count is _AGG_ABSENT:
        declared = getattr(criterion, "band_count", None)
        if declared is None:
            declared = len(getattr(criterion, "bands", ()) or ())
        band_count = declared if declared else _AGG_ABSENT
    if (
        ordinal is not _AGG_ABSENT
        and ordinal is not None
        and band_count is not _AGG_ABSENT
        and band_count is not None
    ):
        if 0 < int(ordinal) < int(band_count) - 1:
            concern += signal_weight
            reasons.append("interior band position")

    # 2. Adverse integrity signals — recorded `None` is adverse (fail-closed);
    # an absent field is no claim and skips its limb.
    for field_name, favourable in _AGG_FAVOURABLE.items():
        value = _row_field(score, field_name)
        if value is _AGG_ABSENT:
            continue
        if _signal_adverse(value, favourable):
            concern += signal_weight
            reasons.append(f"adverse integrity signal: {field_name}")

    # 3. The uncited mark — M-JUDGE marks it; absent, no claim.
    uncited = _row_field(score, "uncited")
    if uncited is not _AGG_ABSENT and uncited is not None and bool(uncited):
        concern += signal_weight
        reasons.append("uncited verdict")

    # 4. The criterion's override history — contested, escalated before, or
    # unmeasured (weighted low, never read as a zero — CT-STATS-09).
    override_rate = _row_field(history, "override_rate")
    if isinstance(history, NoValidationData):
        # CT-STATS-09 / FR-AGG-08 (#520): M-STATS answers "no override data" with its absence
        # value, which carries no `override_rate` at all. It is the no-data case, weighted
        # low, never skipped as if the field were simply missing.
        override_rate = None
    if override_rate is not _AGG_ABSENT:
        if override_rate is None:
            concern += no_data_weight
            reasons.append("criterion override history: no data")
        elif float(override_rate) > override_rate_threshold:
            concern += signal_weight
            reasons.append(
                f"criterion override history (override_rate={float(override_rate):.2f})"
            )
    escalations = _row_field(history, "escalations")
    if escalations is not _AGG_ABSENT and escalations is not None and int(escalations) > 0:
        concern += signal_weight
        reasons.append("criterion previously escalated")

    # 5. The distributional anomaly against the package baseline.
    baseline_mean = _row_field(baseline, "mean")
    baseline_std = _row_field(baseline, "std")
    if (
        ordinal is not _AGG_ABSENT
        and ordinal is not None
        and baseline_mean is not _AGG_ABSENT
        and baseline_mean is not None
        and baseline_std is not _AGG_ABSENT
        and baseline_std is not None
        and float(baseline_std) > 0.0
    ):
        z = (float(ordinal) - float(baseline_mean)) / float(baseline_std)
        if abs(z) >= anomaly_sigma:
            concern += signal_weight
            reasons.append(
                f"distributional anomaly vs package baseline (z={z:.2f})"
            )

    # Self-confidence: one weighted input (FR-AGG-08), never a reason (R22).
    self_confidence = _row_field(score, "self_confidence")
    if self_confidence is not _AGG_ABSENT and self_confidence is not None:
        clamped = min(1.0, max(0.0, float(self_confidence)))
        concern += self_confidence_weight * (1.0 - clamped)

    escalate = concern >= threshold
    judge_count = _row_field(score, "judge_count")
    if judge_count is _AGG_ABSENT or judge_count is None:
        judge_count = 1
    judge_count = int(judge_count)
    if escalate:
        # FR-AGG-09: the next odd panel at least two above the current one —
        # 1 → 3, never 2 (`aeh.orch:validate_escalation_plan` enforces the odd
        # plan; this module's target never produces an even one).
        target = judge_count + 2
        if target % 2 == 0:
            target += 1
    else:
        target = judge_count
    return EscalationDecision(
        escalate=bool(escalate), target_judge_count=int(target), reasons=tuple(reasons)
    )


@dataclass(frozen=True)
class CriterionEscalationRank:
    """One criterion's row in the escalation ranking (`CT-STATS-09`'s consumer
    differential, `FR-AGG-08`): its id, its override rate as measured, and
    whether the row is **no data** — never reviewed, or a recorded no-data
    rate. `override_rate` is `None` exactly when the history had no figure to
    give; a genuine zero keeps its zero and its `no_data=False`."""

    criterion_id: str
    override_rate: float | None
    no_data: bool


def rank_criteria_for_escalation(criteria: Any) -> tuple:
    """Rank criteria for escalation, most urgent first (`FR-AGG-08`, CT-STATS-09).

    `criteria` maps criterion ids to their override-history payloads — mappings
    or objects carrying `override_rate` and `reviewed`. A criterion with **no
    data** (never reviewed, or a recorded no-data rate) ranks FIRST: the
    criterion nobody has looked at is not the safest, it is the one whose risk
    is unmeasured (CT-STATS-09's named failure — reading no data as a zero is
    what makes it the queue's "safest"). Data-bearing criteria then rank by
    override rate, most overridden first, so a criterion overridden on half its
    reviews outranks one overridden on none. Ties keep the caller's order
    (a stable sort over the mapping's own order — the ranking invents no
    order of its own).

    The distinction is observable in the output (`tests/contract`'s c09
    differential): a no-data criterion changes position when its payload changes
    from no history to a measured zero, because the two rank differently — that
    is the whole point of M-STATS's `NoValidationData` distinct value.
    """
    ranks: list[tuple[tuple[int, float], CriterionEscalationRank]] = []
    for criterion_id, payload in dict(criteria).items():
        if isinstance(payload, dict):
            override_rate = payload.get("override_rate")
            reviewed = payload.get("reviewed")
        else:
            override_rate = getattr(payload, "override_rate", None)
            reviewed = getattr(payload, "reviewed", None)
        no_data = override_rate is None or reviewed is False
        key = (0, 0.0) if no_data else (1, -float(override_rate))
        ranks.append(
            (
                key,
                CriterionEscalationRank(
                    criterion_id=str(criterion_id),
                    override_rate=None if override_rate is None else float(override_rate),
                    no_data=no_data,
                ),
            )
        )
    ranks.sort(key=lambda entry: entry[0])
    return tuple(rank for _, rank in ranks)
