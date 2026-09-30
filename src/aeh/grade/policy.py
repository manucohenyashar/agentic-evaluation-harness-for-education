"""The pure grade computation: criterion scores in, grade, coverage and boundary risk out."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Any, Iterable

from aeh.pkg import GradePolicy

from .constants import _PROVISIONAL_ROUTINGS, ROUTING_AUTO, ROUTING_REVIEWED


# --- the pure result records -----------------------------------------------------------------------


@dataclass(frozen=True)
class GradeComputation:
    """The pure result of applying a policy to a population of criterion scores.

    `total` is the declared pin (FUZZ-05's and TC-GRADE-02's oracle): a float when the
    grade stands, `None` when the policy's gate refuses — never an exception, never a
    fabricated figure. `gate_met` states the gate's verdict alongside, so a refusal is
    observable rather than only an absent number. `panel_refused` carries the same
    honesty to the circuit breaker: the criteria the input population carries with
    state `ungradeable_by_panel` (CT-ORCH-16). Their single-judge provisional figures
    are real and the policy consumes them, but the presentation says a panel refused
    to grade — never merging the refusal into the ordinary provisional presentation
    (CT-AGG-07's consumer obligation)."""

    total: float | None
    gate_met: bool
    panel_refused: tuple[str, ...] = ()


@dataclass(frozen=True)
class Coverage:
    """The five-counter coverage record (`FR-GRADE-04`, `CT-GRADE-04`) — the field
    names are design-declared verbatim. The four classes sum to `criteria_total`
    because a criterion with no row is counted `criteria_missing` from the criterion
    list, never dropped (`FR-GRADE-07`)."""

    criteria_total: int
    criteria_auto: int
    criteria_reviewed: int
    criteria_provisional: int
    criteria_missing: int

    def as_tuple(self) -> tuple[int, int, int, int, int]:
        return (
            self.criteria_total,
            self.criteria_auto,
            self.criteria_reviewed,
            self.criteria_provisional,
            self.criteria_missing,
        )


@dataclass(frozen=True)
class BoundaryRisk:
    """The boundary-risk triple (`FR-GRADE-05`, `CT-GRADE-05`): whether a plausible
    movement of the provisional criteria could move the student across a band edge,
    and the achievable range when — and only when — it could."""

    at_risk: bool
    score_low: float | None
    score_high: float | None


@dataclass(frozen=True)
class CriterionInput:
    """One criterion score as the computation consumes it. The same duck type the
    test vocabulary's `score()` stand-in returns (`criterion_id` / `points` /
    `routing`), so the pure seams take either."""

    criterion_id: str
    band: str
    points: float
    routing: str
    state: str


# --- the pure seams ---------------------------------------------------------------------------------
#
# Design §3.14 declares the behaviour on the service; the rung-0 cases need pure entry
# points (the `verify_span` / `synthesize` precedent), and the service composes them —
# the same functions the unit cases call by name are the ones the batch path runs.


def apply_policy(scores: Iterable[Any], policy: GradePolicy) -> GradeComputation:
    """Apply the closed-vocabulary policy to a population of criterion scores — pure,
    deterministic, unit-testable (`CT-GRADE-02`), no store and no model in the path.

    The rule vocabulary, exactly as shipped on `aeh.pkg.GradePolicy`:

    - `weighted_sum` — each criterion's points multiplied by its declared weight
      (a criterion with no declared weight weighs 1.0), summed. With no weights at all
      this is the plain sum (`FR-SETUP-12`'s default).
    - `best_k_of_n` — the k highest points, summed. Ties at the cut are broken by
      criterion id for determinism; because tied values are equal, the total is
      invariant under every arrival order either way (`TC-GRADE-03`).
    - `drop_lowest_n` — the n lowest points dropped before summing (scored out, never
      scored as zero).
    - `gate` — the named criterion must reach `minimum`, inclusively (`TC-GRADE-03`'s
      pinned reading). A criterion with no row refuses the gate: absence is not a zero.
      A refusal is a `None` total, never an exception (`CT-GRADE-02`).
    - `scale` — the combined total multiplied by the factor, after combination.
    - `rounding` — applied last: `nearest` is HALF-UP at exactly .5 (`TC-GRADE-03`'s
      pinned reading — Python's `round()` is half-even and would fail the case),
      `up` rounds away from zero's floor, `down` truncates.

    Sums run through `math.fsum` (exactly rounded, therefore order-independent over
    criteria — `TC-GRADE-21`'s permutation limb reads the same total in every order).

    The result also surfaces the population's breaker-refused criteria in
    `panel_refused` (`CT-AGG-07`): a criterion the escalation breaker marked
    `ungradeable_by_panel` contributes its stored figure — CT-ORCH-16 leaves it scored
    single-judge provisional — and is named in the result, so the grade's presentation
    of the breaker-refused row differs from its presentation of the identical
    ordinary-provisional row.
    """
    score_list = list(scores)
    points = {score.criterion_id: float(score.points) for score in score_list}
    # Duck-typed state read: the pure seams' score stand-ins carry no state (only
    # criterion_id / points / routing), and a missing state is simply never refused.
    panel_refused = tuple(sorted(
        score.criterion_id for score in score_list
        if getattr(score, "state", None) == "ungradeable_by_panel"
    ))

    if policy.gate is not None:
        gated = points.get(policy.gate.criterion_id)
        if gated is None or gated < policy.gate.minimum:
            return GradeComputation(total=None, gate_met=False,
                                    panel_refused=panel_refused)

    if policy.combination == "weighted_sum":
        weights = {cid: w for cid, w in (policy.weights or ())}
        raw = math.fsum(points[cid] * weights.get(cid, 1.0) for cid in points)
    elif policy.combination == "best_k_of_n":
        k = policy.k if policy.k is not None else len(points)
        ranked = sorted(points.items(), key=lambda item: (-item[1], item[0]))
        raw = math.fsum(value for _, value in ranked[:k])
    elif policy.combination == "drop_lowest_n":
        n = policy.drop if policy.drop is not None else 0
        ranked = sorted(points.items(), key=lambda item: (item[1], item[0]))
        raw = math.fsum(value for _, value in ranked[n:])
    else:
        raise ValueError(
            f"combination {policy.combination!r} is not a member of the closed rule "
            "vocabulary; a GradePolicy from aeh.pkg cannot carry it."
        )

    if policy.scale is not None:
        raw = raw * policy.scale.factor

    if policy.rounding is not None:
        decimals = policy.decimals if policy.decimals is not None else 0
        quantum = Decimal(1).scaleb(-decimals)
        mode = {
            "nearest": ROUND_HALF_UP,
            "up": ROUND_UP,
            "down": ROUND_DOWN,
        }.get(policy.rounding)
        if mode is None:
            raise ValueError(
                f"rounding {policy.rounding!r} is not a member of the closed rule "
                "vocabulary; a GradePolicy from aeh.pkg cannot carry it."
            )
        raw = float(Decimal(str(raw)).quantize(quantum, rounding=mode))

    return GradeComputation(total=raw, gate_met=True, panel_refused=panel_refused)


def resolve_grade(
    scaled_score: float, boundaries: Iterable[tuple[str, float]] | None
) -> str | None:
    """Resolve a scaled score to its band — or `None` where no table declares one
    (`FR-GRADE-03`, the NoValidationData honesty rule: an absent input stays visibly
    absent, never an invented band).

    The rule is the shipped `grade_boundary` DDL's own words (aeh/pkg.py migration 5):
    floors are INCLUSIVE — the grade with the greatest floor <= the scaled score
    resolves. A score below every declared floor resolves to no grade at all."""
    if not boundaries:
        return None
    resolved: str | None = None
    best_floor: float | None = None
    score = float(scaled_score)
    for grade, floor in boundaries:
        floor = float(floor)
        if floor <= score and (best_floor is None or floor >= best_floor):
            best_floor, resolved = floor, grade
    return resolved


def coverage_for(scores: Iterable[Any], criterion_ids: Iterable[str]) -> Coverage:
    """The five-counter coverage record over the package's full criterion list
    (`FR-GRADE-04`).

    The criterion-id list is what makes a criterion with **no** row count as missing
    rather than silently vanish — `criteria_missing` is counted from the list, so the
    four classes always sum to `criteria_total`. A row whose routing is `triage`
    (or unrecognized) also counts missing: the extraction never delivered a figure
    (`CT-AGG-06`'s routing column, read through the module docstring's class map)."""
    by_id: dict[str, Any] = {}
    for score in scores:
        by_id[score.criterion_id] = score

    auto = reviewed = provisional = missing = 0
    for criterion_id in criterion_ids:
        score = by_id.get(criterion_id)
        if score is None:
            missing += 1
        elif score.routing == ROUTING_AUTO:
            auto += 1
        elif score.routing == ROUTING_REVIEWED:
            reviewed += 1
        elif score.routing in _PROVISIONAL_ROUTINGS:
            provisional += 1
        else:
            # `triage` and anything unrecognized: no usable figure arrived, which is
            # the ingestion-failure population — counted missing, never substituted.
            missing += 1
    return Coverage(
        criteria_total=auto + reviewed + provisional + missing,
        criteria_auto=auto,
        criteria_reviewed=reviewed,
        criteria_provisional=provisional,
        criteria_missing=missing,
    )


def boundary_risk(
    total: float,
    provisional_intervals: Iterable[tuple[float, float]],
    boundaries: Iterable[tuple[str, float]] | None,
) -> BoundaryRisk:
    """Whether the provisional criteria's plausible movement could cross a boundary
    (`FR-GRADE-05`) — with the interval source **injected** (test plan `TC-GRADE-06`;
    the full-band-range assumption is design TBD §7.4, `CT-GRADE-19`).

    `provisional_intervals` is one `(low, high)` offset pair per provisional
    criterion — where that criterion's eventual points may yet move relative to its
    current ones. Because each criterion's current points sit inside its own range,
    `total` always lies inside `[score_low, score_high]` (`CT-GRADE-05`'s containment
    invariant). `at_risk` fires when the range has positive width and any boundary
    floor lies inside it, inclusive both ends — landing exactly on a floor resolves
    to that floor's band (floors are inclusive), which is the range spanning a band
    edge. A **zero-width** range (no provisional criteria, or every provisional
    interval collapsed to nothing) cannot move the student anywhere, so it can never
    span a band edge even when the total sits exactly on a floor — a settled grade
    on a floor is settled, not at risk (the #102 degenerate limb of `TC-GRADE-06`).
    When not at risk the range is withheld: a range nobody acts on is noise
    (`CT-GRADE-05`)."""
    intervals = list(provisional_intervals)
    low = math.fsum([float(total), *(float(pair[0]) for pair in intervals)])
    high = math.fsum([float(total), *(float(pair[1]) for pair in intervals)])
    if boundaries and low < high:
        at_risk = any(
            low <= float(floor) <= high for _, floor in boundaries
        )
    else:
        at_risk = False
    if at_risk:
        return BoundaryRisk(at_risk=True, score_low=low, score_high=high)
    return BoundaryRisk(at_risk=False, score_low=None, score_high=None)
