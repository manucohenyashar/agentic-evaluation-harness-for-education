"""M-REVIEW — the minute-budgeted review queue (§3.15, issue #108).

The teacher states a minute budget; the queue spends it where a wrong score
costs the most per review second. Everything here is a pure function of the
stored signals (`NFR-REVIEW-02`): the ranking reads the four observable
error-probability inputs (`FR-REVIEW-03`), the two impact inputs, and the cost
estimate — and nothing else. `self_confidence` is deliberately unread (R22).

**The ranking score.** ``expected_value = (P(score wrong) × impact) / est_seconds``:

* ``P`` is an equal-weight sum of the four signals `FR-REVIEW-03` names — panel
  spread, adverse integrity signals (normalized by a cap), transcription
  overlap, and the criterion's historical override rate. §3.15 names the four
  inputs and no weights; equal weights are the uncommitted reading, and each
  carries a knob (`AEH_REVIEW_*`) so a Phase 2 calibration can replace them
  without a code change. `self_confidence` is not an input (R22).
* ``impact`` is ``criterion_weight × boundary proximity``, where proximity is
  ``1 / (1 + grade_boundary_delta / half_width)`` — a smooth 1→0 falloff that
  is 1 at the boundary and halves at the half width. The design says
  "proximity to a grade boundary" and names no shape; this one is monotone,
  bounded, and sensitive at the scale the fixtures use.
* The quotient — not an additive cost term — is the clause's own arithmetic
  (`TC-REVIEW-C03`'s ratio case), and `rank_queue_items` returns it as
  ``expected_value``, the same name the `#95 TS-36` unit suite already pins.

**Interpretations this module records** (each is a place the design is silent
and this implementation chose; all are reported on the PR):

* *The 5-minute budget under a 10-minute reserve.* `NFR-REVIEW-05` promises
  honest degradation at 5 minutes; `REVIEW_BLIND_RESERVE_MINUTES` is 10 and is
  subtracted first (`FR-REVIEW-02`), which would leave nothing to spend. The
  queue never returns an empty ``shown`` over a non-empty admitted population:
  when no entry fits, it shows the single top-ranked entry and states the
  truth in the residual. The floor of one keeps the degradation honest — fewer
  items, larger residual, same ranking rule — where an empty queue would make
  the same-rule assertion vacuous.
* *The blind reserve is capped at the budget*: ``min(REVIEW_BLIND_RESERVE_MINUTES,
  budget_minutes)``. A queue cannot reserve minutes the teacher did not offer.
* *The fill is greedy and never reorders.* Entries are taken in rank order
  (groups first, `FR-REVIEW-05`), each taken when it fits and passed over when
  it does not; the walk never reorders and never revisits, so the ranking rule
  is identical at every budget and the build never bills its own seconds to
  the teacher (`CT-REVIEW-16`). The residual counts items, not entries — a
  group covers its members (`vocab.items_shown`).
* *A flagged item is named by the teacher's routing, whatever its state.* The
  admitted population is ``routing`` in ``queued``/``provisional`` — the
  panel-routed work (`CT-AGG-06`) plus the provisional family, whose
  single-judge fallback and breaker refusal route identically and are told
  apart by state alone — in the judged mode (`FR-REVIEW-06`, enforced from the
  evaluation-mode column per `CT-DET-06`), outside the never-rendered origins
  (`FR-REVIEW-07`). The state column does not gate admission: `CT-AGG-07`
  binds consumers to surface ``ungradeable_by_panel`` rather than treat it as
  an ordinary provisional, and a state gate would hide exactly the row that
  clause names — the c07 consumer differential forces the read (both its rows
  route ``provisional``, one state apart, and the queue must present them
  differently). Panel work the panel routed to the teacher arrives ``final``
  (`CT-AGG-06` puts ``queued`` in the teacher's queue regardless). An acted-on
  row leaves the count through the service's acted-set (in memory) or #109's
  annotation (at rung 2), which is what makes ``flagged_total`` fall by
  exactly the reviewed item across sessions.
* *No-data override history reads as 0.5* (`AEH_REVIEW_OVERRIDE_RATE_NO_DATA`) —
  the same unmeasured-risk posture as `aeh.agg`'s escalation weight: a
  criterion nobody has reviewed is not a criterion nobody disagrees with
  (`CT-STATS-09`). The criteria-form ranker mirrors
  ``aeh.agg.rank_criteria_for_escalation`` exactly (no data first, then
  override rate descending, stable), which is what the `CT-STATS-09` consumer
  differential asserts of both consumers.
* *A group costs one decision.* ``ReviewGroup.est_seconds`` is its most
  expensive member's estimate: acting on the group is one band decision
  however many members it resolves, and that is what the budget accounting
  charges. The group's ranking value sums its members' value-per-decision.
* *Groups form only at two or more members* sharing criterion and signature —
  a one-member "group" would be a per-item entry wearing a costume, and
  `CT-REVIEW-20`'s sweep would count its lone member as grouped.
* *``est_seconds`` of zero or less is missing data*, not a free item: it takes
  the default estimate rather than dividing the score by zero or ranking the
  item first. ``REVIEW_DEFAULT_EST_SECONDS`` is the default (`FR-REVIEW-16`:
  the estimate is uncalibrated at Phase 1, and a missing one is not a zero).
* *Group labels record the honest per-member time*: ``review_seconds`` is
  divided across the members, because the group action genuinely took less per
  member — which is why ``GROUP_INDISTINGUISHABILITY_FIELDS`` excludes it.
* *The skip-over fill is not a prefix fill at every budget.* The ranking rule
  is identical at every budget (same score, same order), but because an entry
  that does not fit is passed over rather than stopping the walk, a squeezed
  budget can show a different selection than a prefix of the generous budget's
  — a cheap tail item can ride along while an expensive head item is skipped.
  ``CT-REVIEW-C01``'s pinned assertion (the 5-minute floor-of-one showing the
  single top entry) is structurally a prefix at any fixture, so the case holds
  today; the divergence lives at intermediate budgets the plan does not pin.
  A prefix fill was rejected because it would strand the budget behind one
  expensive entry the design's "spend it where a wrong score costs the most"
  does not ask for.
* *Ranking is vacuous at rung 2 until the store carries the signals.*
  ``FR-REVIEW-03``'s seven inputs exist in no landed schema (``criterion_score``
  carries band/state/routing/confidence and the integrity booleans only), so
  ``open_review``'s admitted rows all score ``expected_value = 0.0`` (P falls
  to the 0.5 no-data default; impact falls to 0 with ``criterion_weight``
  absent) and the queue ranks by store row order. Admission, grouping, the
  budget and the residual all work; the expected-value ordering arrives with
  M-GRADE/M-STATS's columns, and no migration was added here (the issue
  forbids one).

**The four seams.**

1. *Headless driver.* ``build_queue``/``act``/``act_on_group`` return structured
   results — the queue carries the residual triple plus a per-stage
   ``build_trace`` (one ``BuildEvent`` per stage, in order), and every action
   returns the label it wrote (or ``None`` for a skip). Nothing needs a console.
2. *Deterministic transport.* There is no egress here. The rung-2 constructor
   ``open_review`` reads the cohort's own SQLite through ``aeh.store`` — the
   same deterministic store every other module reads — and never opens a
   network path. Ranking is a pure function of those rows.
3. *Env-gated knobs.* The four §3.15 configuration knobs are module constants
   injected at the call (``build_review(..., review_blind_n=..., config=...)``:
   keyword wins over a ``config=`` attribute, which wins over the constant).
   The calibration constants are read from the environment at call time
   through ``_env_float`` (`orch.py`'s shape): invalid values refuse rather
   than fall back, so a typo'd override cannot silently take the production
   number.
4. *Stage-level observability.* ``ReviewQueue.build_trace`` records what each
   build stage did, in order — `CT-REVIEW-02`'s event-order contract (reserve
   before rank) is asserted against exactly this trace — and the residual
   triple in the header is the run's own observability surface.

``ReviewService`` here is the concrete in-memory implementation of the §3.15
Protocol's three #108 members (``build_queue``, ``act``, ``act_on_group``); the
two samples (``blind_sample``, ``submit_blind``, ``whole_grade_sample``) are
#111's and the label store's persistence surface is #110's — deliberately
absent here. Actions write in-memory labels until those stories land, and a
label's ``new_points`` stays ``None`` until #110 routes it through
`CT-PKG-05`'s pinned mapping (``aeh.pkg.points_for_band``), which `NFR-AGG-02`
keeps defined in exactly one place in the source.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping, Sequence

__all__ = [
    "REVIEW_BLIND_RESERVE_MINUTES",
    "REVIEW_BLIND_N",
    "REVIEW_WHOLE_GRADE_N",
    "REVIEW_DEFAULT_BUDGET_MINUTES",
    "ReviewError",
    "StaleReviewItemError",
    "ReviewItem",
    "ReviewGroup",
    "ReviewQueue",
    "BuildEvent",
    "LabelRecord",
    "CriterionOverrideRank",
    "SupersededScore",
    "ReviewService",
    "build_review",
    "open_review",
    "rank_queue_items",
]


# --- the four §3.15 configuration knobs (CT-REVIEW-17) ----------------------------------------------
#
# §3.15's Configuration line, transcribed with their declared Assumption values.
# CT-REVIEW-17 makes all four M-STATS's inputs as much as this module's settings,
# so the names are part of the contract — a story cannot rename them without the
# design changing first.

#: Minutes always reserved for the blind sample, subtracted BEFORE any ranking
#: (`FR-REVIEW-02`) — the event order is the contract (`CT-REVIEW-02`).
REVIEW_BLIND_RESERVE_MINUTES = 10
#: Submissions the blind sample draws (`FR-REVIEW-12`); #111 sizes the draw.
REVIEW_BLIND_N = 15
#: Complete final grades the whole-grade sample draws (`FR-REVIEW-14`); #111's.
REVIEW_WHOLE_GRADE_N = 12
#: The budget `build_queue` assumes when a caller states none. §3.15's
#: Interfaces block declares ``budget_minutes`` required, so nothing reads this
#: today — it is declared because CT-REVIEW-17 asserts its value.
REVIEW_DEFAULT_BUDGET_MINUTES = 30


# --- the calibration constants (Phase 1; FR-REVIEW-16's calibration is Phase 2) ---------------------
#
# §3.15 names the formula's factors and no numbers. These are the Phase 1
# reading, each env-gated at call time (seam 3) so a differently-shaped corpus
# can adjust without a code change, and each injectable through ``config=``
# under its own name.

#: Weight of one unit of panel spread in P(score wrong). Equal weights: the
#: design names four inputs and no weighting.
REVIEW_PANEL_SPREAD_WEIGHT: float = 1.0
#: Weight of one adverse integrity signal, after the cap below.
REVIEW_INTEGRITY_SIGNAL_WEIGHT: float = 1.0
#: Weight of transcription overlap in P(score wrong).
REVIEW_TRANSCRIPTION_OVERLAP_WEIGHT: float = 1.0
#: Weight of the criterion's historical override rate in P(score wrong).
REVIEW_OVERRIDE_RATE_WEIGHT: float = 1.0
#: The count of adverse integrity signals read as "the panel is shouting";
#: the signal is normalized by this cap, not by trust.
REVIEW_INTEGRITY_SIGNAL_CAP: int = 3
#: Boundary proximity ``1/(1 + delta/half_width)`` halves here: a criterion
#: whose band sits this far from a grade boundary is half as boundary-urgent.
REVIEW_BOUNDARY_HALF_WIDTH: float = 10.0
#: P contribution of an override history nobody has measured (`CT-STATS-09`:
#: no data is not a zero; the unmeasured criterion is the risky one).
REVIEW_OVERRIDE_RATE_NO_DATA: float = 0.5
#: The estimate used when a row carries no usable ``est_seconds``.
REVIEW_DEFAULT_EST_SECONDS: float = 60.0

_WEIGHT_LOW, _WEIGHT_HIGH = 0.0, 10.0

# --- errors -----------------------------------------------------------------------------------------


class ReviewError(Exception):
    """Base class for the review module's refusals, so callers can catch the
    module's own failures without catching the package's too."""


class StaleReviewItemError(ReviewError):
    """An action arrived for a score row the queue no longer reflects
    (`CT-REVIEW-15`): the row was superseded by an escalation after this queue
    was built, and acting on the stale copy would overwrite a judgment somebody
    else already made. The message says to refresh the queue."""


# --- the queue's wire shapes ------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewItem:
    """One flagged criterion as the queue presents it — §3.15's wire shape plus
    the identity fields a differential reads and the ranking surface (`FR-REVIEW-03`,
    `FR-AGG-06`'s tie-break input). ``state`` rides through because `CT-AGG-07`
    binds consumers to surface ``ungradeable_by_panel`` rather than merge it
    into the provisional presentation."""

    score_id: str
    criterion_id: str
    submission_id: str
    version: int
    state: str | None
    proposed_band: str | None
    band_options: tuple[str, ...]
    proposed_points: float | None
    max_points: float | None
    narrative: str | None
    evidence_spans: tuple[Any, ...]
    reason: str
    est_seconds: float
    package_version_id: str | None
    grade_boundary_delta: float
    expected_value: float
    scoring_model: str | None


@dataclass(frozen=True)
class ReviewGroup:
    """One signature-identical group presented as a single entry (`FR-REVIEW-05`).

    ``members`` carries the full per-item rows, so "one label per member" is
    countable (`CT-REVIEW-13`) and the group's per-item view survives the
    collapse. ``est_seconds`` is the most expensive member's estimate — one
    band decision is charged once, at the slowest member's pace."""

    members: tuple[ReviewItem, ...]
    signature: Mapping[str, Any]
    criterion_id: str
    proposed_band: str
    est_seconds: float
    expected_value: float
    reason: str


@dataclass(frozen=True)
class BuildEvent:
    """One stage of a queue build (`NFR-REVIEW-01`'s trace seam). ``name`` is the
    stable identifier the event-order contract reads (`CT-REVIEW-02`)."""

    name: str
    detail: str = ""


@dataclass(frozen=True)
class ReviewQueue:
    """The built queue — §3.15's five declared fields plus the group list, the
    build's own timing, and the per-stage trace."""

    run_id: str
    budget_minutes: int
    reserved_for_blind_minutes: int
    flagged_total: int
    shown: tuple["ReviewItem | ReviewGroup", ...]
    residual_provisional: int
    groups: tuple[ReviewGroup, ...]
    build_seconds: float
    build_trace: tuple[BuildEvent, ...]


@dataclass(frozen=True)
class LabelRecord:
    """The label an action writes — `FR-REVIEW-09`'s eight fields, `NFR-REVIEW-03`'s
    attribution, and the identity fields a differential reads. In memory until
    #110 lands the store surface; deliberately carries none of the fields
    `CT-REVIEW-07` forbids (no confidence, no narrative, and no points but
    ``new_points``, derived through `CT-PKG-05`'s pinned mapping once #110 lands
    the route through it — `None` until then)."""

    label_id: str
    label_type: str
    saw_system_output: int
    routing: str
    origin: str
    evaluation_mode: str
    review_seconds: float
    system_band: str | None
    teacher_band: str | None
    actor: str
    timestamp: str
    score_id: str
    criterion_id: str
    review_queue_action: str
    new_points: float | None


@dataclass(frozen=True)
class CriterionOverrideRank:
    """One criterion's row in the criteria-form ranking — the mirror of
    ``aeh.agg.CriterionEscalationRank`` (`CT-STATS-09`'s consumer differential):
    ``override_rate`` is None exactly when there was no figure to give; a
    genuine zero keeps its zero and its ``no_data=False``."""

    criterion_id: str
    override_rate: float | None
    no_data: bool


@dataclass(frozen=True)
class SupersededScore:
    """What ``escalate`` returns (`CT-REVIEW-15`'s induced race): the score id and
    the version every queue built before the escalation now carries stale."""

    score_id: str
    version: int


# --- the admitted population and the ranking --------------------------------------------------------

#: The teacher's population, by routing (`CT-AGG-06`): ``queued`` — the
#: panel-routed work — and ``provisional`` — the single-judge fallback and the
#: breaker refusal, which route identically and are told apart by state alone
#: (`CT-AGG-07`'s consumer differential). ``auto`` never arrives here
#: (deterministic work grades itself), and ``triage`` is the operator's queue,
#: not the teacher's.
_ADVISORY_ROUTINGS = ("queued", "provisional")
#: `FR-REVIEW-06` (`CT-DET-06`): the exclusion is enforced from this column.
_JUDGED_MODE = "judged"
#: `FR-REVIEW-07`'s never-rendered origins: quarantine, the blind sample, and
#: the random arm — the arm is the only unbiased comparison RISK-07 has, and it
#: spends compute, never teacher minutes (`CT-REVIEW-05`).
_EXCLUDED_ORIGINS = frozenset({"quarantine", "blind_sample", "random_arm"})

#: §3.15's ``act`` action domain. ``skip`` is an action but not a label type —
#: a skipped item stays residual (`CT-REVIEW-06`).
_ACTIONS = ("accept", "edit", "override", "skip")

#: `CT-REVIEW-20`'s exact Phase 1 grouping signature: two items differing in any
#: of these five components are not grouped, even when semantically identical.
SIGNATURE_COMPONENTS: tuple[str, ...] = (
    "proposed_band",
    "spans_verified",
    "evidence_present",
    "sufficiency_flag",
    "ocr_overlap_risk",
)


def _signature_of(row: Any) -> dict[str, Any]:
    """The five-component signature of one row (`CT-REVIEW-20`), as a mapping
    keyed by the declared component names."""
    return {component: getattr(row, component) for component in SIGNATURE_COMPONENTS}


def _group_key(row: Any) -> tuple:
    """Two rows group only when they share a criterion *and* the signature."""
    signature = _signature_of(row)
    return (str(getattr(row, "criterion_id", "")),) + tuple(
        signature[component] for component in SIGNATURE_COMPONENTS
    )


def _admitted(rows: Iterable[Any]) -> list[Any]:
    """The rows the queue may render: the teacher's population by routing and
    mode (`CT-AGG-06`, `FR-REVIEW-06/-07`), minus the never-rendered origins
    (`FR-REVIEW-07`), and only work still awaiting it (`CT-REVIEW-05`).

    The state column rides through to the presentation rather than gating
    admission: `CT-AGG-07` binds consumers to surface ``ungradeable_by_panel``
    rather than treat it as an ordinary provisional, and a state gate would
    hide exactly the row that clause names — both of the c07 differential's
    rows route ``provisional``, one state apart, and the queue must present
    them differently."""
    return [
        row
        for row in rows
        if getattr(row, "routing", None) in _ADVISORY_ROUTINGS
        and getattr(row, "evaluation_mode", None) == _JUDGED_MODE
        and getattr(row, "origin", None) not in _EXCLUDED_ORIGINS
    ]


def _score_id_of(row: Any) -> str:
    return str(getattr(row, "score_id"))


def _est_seconds_of(row: Any, default: float) -> float:
    """The row's cost estimate, or the default when it carries none (`FR-REVIEW-16`;
    a missing or non-positive estimate is missing data, not a free item)."""
    raw = getattr(row, "est_seconds", None)
    if raw is None:
        return default
    value = float(raw)
    return default if value <= 0 else value


def _override_rate_of(row: Any, knobs: Mapping[str, float]) -> float:
    """The criterion's measured override rate — or the no-data default
    (`CT-STATS-09`: a criterion nobody has reviewed is not a criterion nobody
    disagrees with, so no data is not read as a zero)."""
    rate = getattr(row, "historical_override_rate", None)
    if rate is None:
        return knobs["override_rate_no_data"]
    return float(rate)


def _p_error(row: Any, knobs: Mapping[str, float]) -> float:
    """P(score wrong) from the four observable signals (`FR-REVIEW-03`), equal
    weights, integrity normalized by its cap. ``self_confidence`` is unread (R22)."""
    integrity = min(
        float(getattr(row, "adverse_integrity_signals", 0) or 0),
        knobs["integrity_signal_cap"],
    )
    return (
        knobs["panel_spread_weight"] * float(getattr(row, "panel_spread", 0.0) or 0.0)
        + knobs["integrity_signal_weight"] * (integrity / knobs["integrity_signal_cap"])
        + knobs["transcription_overlap_weight"]
        * float(getattr(row, "transcription_overlap", 0.0) or 0.0)
        + knobs["override_rate_weight"] * _override_rate_of(row, knobs)
    )


def _impact_of(row: Any, knobs: Mapping[str, float]) -> float:
    """The criterion's share of the final grade, weighted by boundary proximity."""
    weight = float(getattr(row, "criterion_weight", 0.0) or 0.0)
    delta = float(getattr(row, "grade_boundary_delta", 0.0) or 0.0)
    proximity = 1.0 / (1.0 + abs(delta) / knobs["boundary_half_width"])
    return weight * proximity


def _expected_value(row: Any, knobs: Mapping[str, float]) -> float:
    """`FR-REVIEW-03`'s score: ``(P(score wrong) × impact) / est_seconds``."""
    est = _est_seconds_of(row, knobs["default_est_seconds"])
    return (_p_error(row, knobs) * _impact_of(row, knobs)) / est


def _calibration_knobs() -> dict[str, float]:
    """The calibration knobs for one build, env-gated at call time (seam 3).
    Invalid overrides refuse rather than fall back, so a typo cannot silently
    take the production number."""
    return {
        "panel_spread_weight": _env_float(
            "AEH_REVIEW_PANEL_SPREAD_WEIGHT", REVIEW_PANEL_SPREAD_WEIGHT,
            low=_WEIGHT_LOW, high=_WEIGHT_HIGH,
        ),
        "integrity_signal_weight": _env_float(
            "AEH_REVIEW_INTEGRITY_SIGNAL_WEIGHT", REVIEW_INTEGRITY_SIGNAL_WEIGHT,
            low=_WEIGHT_LOW, high=_WEIGHT_HIGH,
        ),
        "transcription_overlap_weight": _env_float(
            "AEH_REVIEW_TRANSCRIPTION_OVERLAP_WEIGHT", REVIEW_TRANSCRIPTION_OVERLAP_WEIGHT,
            low=_WEIGHT_LOW, high=_WEIGHT_HIGH,
        ),
        "override_rate_weight": _env_float(
            "AEH_REVIEW_OVERRIDE_RATE_WEIGHT", REVIEW_OVERRIDE_RATE_WEIGHT,
            low=_WEIGHT_LOW, high=_WEIGHT_HIGH,
        ),
        "integrity_signal_cap": _env_float(
            "AEH_REVIEW_INTEGRITY_SIGNAL_CAP", float(REVIEW_INTEGRITY_SIGNAL_CAP),
            low=1.0, high=100.0,
        ),
        "boundary_half_width": _env_float(
            "AEH_REVIEW_BOUNDARY_HALF_WIDTH", REVIEW_BOUNDARY_HALF_WIDTH,
            low=1e-06, high=1e06,
        ),
        "override_rate_no_data": _env_float(
            "AEH_REVIEW_OVERRIDE_RATE_NO_DATA", REVIEW_OVERRIDE_RATE_NO_DATA,
            low=0.0, high=1.0,
        ),
        "default_est_seconds": _env_float(
            "AEH_REVIEW_DEFAULT_EST_SECONDS", REVIEW_DEFAULT_EST_SECONDS,
            low=1.0, high=3600.0,
        ),
    }


def _env_float(name: str, default: float, *, low: float, high: float) -> float:
    """One float environment knob, read at call time (``orch._env_float``'s shape).

    Absent or blank takes the default; an unparseable value or one outside
    ``[low, high]`` raises rather than falling back — a typo'd override silently
    taking the production value is the phantom-bug shape the seam exists to
    prevent, and a clamped misconfiguration would BE the bug.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ReviewError(f"{name}={raw!r} is not a number") from exc
    if value < low or value > high:
        raise ReviewError(f"{name}={raw!r} is outside [{low}, {high}]")
    return value


def _resolve_knob(explicit: Any, config: Any, name: str, default: Any) -> Any:
    """One §3.15 knob: keyword-injected value, then ``config`` attribute, then
    the module constant (``aeh.agg._escalation_knob``'s reading: the policy
    reads no configuration beyond what the call passes)."""
    if explicit is not None:
        return explicit
    if config is not None:
        attr = getattr(config, name, None)
        if attr is not None:
            return attr
    return default


# --- items and groups -------------------------------------------------------------------------------


def _itemize(row: Any, knobs: Mapping[str, float]) -> ReviewItem:
    """One score row as the queue presents it (§3.15's wire shape). The fields
    the row does not carry stay None/empty: the teacher's view is filled by
    whoever has the package context, and the queue does not invent one."""
    return ReviewItem(
        score_id=_score_id_of(row),
        criterion_id=str(getattr(row, "criterion_id", "") or ""),
        submission_id=str(getattr(row, "submission_id", "") or ""),
        version=int(getattr(row, "version", 1) or 1),
        state=getattr(row, "state", None),
        proposed_band=getattr(row, "proposed_band", None),
        band_options=tuple(getattr(row, "band_options", ()) or ()),
        proposed_points=_opt_float(getattr(row, "proposed_points", None)),
        max_points=_opt_float(getattr(row, "max_points", None)),
        narrative=getattr(row, "narrative", None),
        evidence_spans=tuple(getattr(row, "evidence_spans", ()) or ()),
        reason=str(getattr(row, "reason", None) or "flagged for review"),
        est_seconds=_est_seconds_of(row, knobs["default_est_seconds"]),
        package_version_id=getattr(row, "package_version_id", None),
        grade_boundary_delta=float(getattr(row, "grade_boundary_delta", 0.0) or 0.0),
        expected_value=_expected_value(row, knobs),
        scoring_model=getattr(row, "scoring_model", None),
    )


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _ranked_rows(rows: Sequence[Any], knobs: Mapping[str, float]) -> list[Any]:
    """The rows ranked best-first: expected value per review second, holistic
    first at ties (`FR-AGG-06`), stable otherwise (`NFR-REVIEW-02`)."""
    return sorted(
        rows,
        key=lambda row: (
            -_expected_value(row, knobs),
            0 if getattr(row, "scoring_model", None) == "holistic" else 1,
        ),
    )


def _group_identical(
    ranked_rows: Sequence[Any], knobs: Mapping[str, float]
) -> tuple[list[ReviewGroup], list[ReviewItem]]:
    """Collapse signature-identical rows into group entries (`CT-REVIEW-20`'s
    exact Phase 1 rule): same criterion, same band, same four integrity
    signals. Groups form at two or more members; singletons stay per-item
    entries. Groups rank above per-item entries (`FR-REVIEW-05`) and are
    ordered among themselves by expected value."""
    items = [(_itemize(row, knobs), row) for row in ranked_rows]
    buckets: dict[tuple, list[ReviewItem]] = {}
    signatures: dict[tuple, dict[str, Any]] = {}
    for item, row in items:
        key = _group_key(row)
        buckets.setdefault(key, []).append(item)
        signatures.setdefault(key, _signature_of(row))

    groups: list[ReviewGroup] = []
    used: set[str] = set()
    for key, members in buckets.items():
        if len(members) < 2:
            continue
        first = members[0]
        est = max(member.est_seconds for member in members)
        # Σ p×impact = Σ expected_value × est_seconds, per member.
        numerator = sum(member.expected_value * member.est_seconds for member in members)
        groups.append(
            ReviewGroup(
                members=tuple(members),
                signature=signatures[key],
                criterion_id=first.criterion_id,
                proposed_band=str(first.proposed_band or ""),
                est_seconds=est,
                expected_value=numerator / est,
                reason=first.reason,
            )
        )
        used.update(member.score_id for member in members)

    groups.sort(key=lambda group: -group.expected_value)
    leftovers = [item for item, _ in items if item.score_id not in used]
    return groups, leftovers


def _fill_to_budget(entries: Sequence[Any], available_seconds: float) -> list[Any]:
    """Greedy fill in entry order: take every entry that fits, pass over one
    that does not, never reorder (`NFR-REVIEW-02`/`-05`). Over a non-empty
    entry list the queue never shows nothing: when no entry fits, the single
    top-ranked entry is shown and the residual states the truth (the recorded
    5-minute interpretation)."""
    shown: list[Any] = []
    spent = 0.0
    for entry in entries:
        if spent + entry.est_seconds <= available_seconds:
            shown.append(entry)
            spent += entry.est_seconds
    if not shown and entries:
        shown.append(entries[0])
    return shown


def _items_shown_count(shown: Iterable[Any]) -> int:
    """How many review *items* a shown list covers — a group counts its members
    (`CT-REVIEW-04`'s arithmetic is about items, not entries)."""
    total = 0
    for entry in shown:
        members = getattr(entry, "members", None)
        total += len(members) if members is not None else 1
    return total


# --- the ranking, at both of its declared shapes ----------------------------------------------------


def rank_queue_items(items: Sequence[Any] | None = None, *, criteria: Any = None) -> Any:
    """The ranking, at both of its declared shapes.

    ``items`` (the ``#95 TS-36`` limb): review-queue items carrying
    ``expected_value`` and ``scoring_model`` — ordered best-first, expected
    value dominant, holistic ranking above atomic at equal value, stable
    otherwise. The caller's ``expected_value`` is taken as given: this is the
    queue's ordering rule over items whose value some producer has stated.
    Stored score rows (mappings, as ``SELECT *`` hands them back) are
    normalized to items first, honest defaults for the columns the store does
    not carry — the c16 consumer sweep's declared assumption, that the ranker
    takes the stored rows and returns the ranked queue.

    ``criteria`` (the ``CT-STATS-09`` consumer limb): a mapping of criterion ids
    to override-history payloads — mirrors
    ``aeh.agg.rank_criteria_for_escalation`` exactly, so both consumers rank no
    data first and a measured zero by its rate. Returns
    ``CriterionOverrideRank`` rows.
    """
    if criteria is not None:
        return _rank_criteria(criteria)
    if items is None:
        raise ReviewError(
            "rank_queue_items takes the items to rank, or criteria= for the criteria form"
        )
    knobs = _calibration_knobs()
    normalized: list[Any] = []
    for item in items:
        if hasattr(item, "expected_value"):
            normalized.append(item)
            continue
        if not hasattr(item, "keys"):
            raise ReviewError(
                "rank_queue_items takes review items carrying expected_value, or "
                "stored score rows as mappings; "
                f"{type(item).__name__} carries neither"
            )
        normalized.append(
            _itemize(
                _StoredScoreRow(_row_mapping(item), knobs["default_est_seconds"]),
                knobs,
            )
        )
    return sorted(
        normalized,
        key=lambda ranked: (
            -float(ranked.expected_value),
            0 if getattr(ranked, "scoring_model", None) == "holistic" else 1,
        ),
    )


def _rank_criteria(criteria: Any) -> tuple[CriterionOverrideRank, ...]:
    """The criteria form — ``aeh.agg.rank_criteria_for_escalation``'s semantics,
    mirrored so both consumers answer `CT-STATS-09` the same way: no data
    first, then override rate descending, ties keeping the caller's order."""
    ranks: list[tuple[tuple[int, float], CriterionOverrideRank]] = []
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
                CriterionOverrideRank(
                    criterion_id=str(criterion_id),
                    override_rate=None if override_rate is None else float(override_rate),
                    no_data=no_data,
                ),
            )
        )
    ranks.sort(key=lambda entry: entry[0])
    return tuple(rank for _, rank in ranks)


# --- the service ------------------------------------------------------------------------------------


class ReviewService:
    """The in-memory review service: builds the queue, ranks it, writes labels.

    Constructed by ``build_review`` (rung 0/1, over score rows in memory) or
    ``open_review`` (rung 2, over a stored run). The three §3.15 members #108
    owns are here; the samples and the label store's persistence are #111's and
    #110's and are not on this class yet — actions write in-memory labels until
    those stories land.
    """

    def __init__(
        self,
        rows: Sequence[Any],
        *,
        actor: str = "teacher",
        clock: Callable[[], str] | None = None,
        catalog: Any = None,
        config: Any = None,
        blind_reserve_minutes: int | None = None,
        blind_n: int | None = None,
        whole_grade_n: int | None = None,
        default_budget_minutes: int | None = None,
        store: Any = None,
    ) -> None:
        self._rows = tuple(rows)
        self._rows_by_id = {_score_id_of(row): row for row in self._rows}
        self._actor_name = actor
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        # Held for #110's points route through `aeh.pkg.points_for_band` — unused
        # until the label store lands (see ``LabelRecord.new_points``).
        self._catalog = catalog
        self._blind_reserve = blind_reserve_minutes
        self._blind_n = blind_n
        self._whole_grade_n = whole_grade_n
        self._default_budget = default_budget_minutes
        self._store = store
        self._labels: list[LabelRecord] = []
        self._acted: set[str] = set()
        self._versions: dict[str, int] = {}

    # -- the queue -----------------------------------------------------------------------------------

    def build_queue(self, run_id: str, budget_minutes: int) -> ReviewQueue:
        """Build the minute-budgeted queue (`FR-REVIEW-01`).

        Stage order is the contract, not an implementation detail
        (`CT-REVIEW-02`): the blind reserve is subtracted **before** anything is
        ranked, and the trace says so. The queue fills in rank order, takes what
        fits, and states what is left over — and never bills its own build
        seconds to the teacher (`CT-REVIEW-16`).
        """
        started = perf_counter()
        trace: list[BuildEvent] = []
        knobs = _calibration_knobs()

        admitted = self._admitted_rows()
        flagged_total = len(admitted)
        trace.append(BuildEvent("count_flagged", f"{flagged_total} queued judged rows"))

        reserve = min(self._blind_reserve, budget_minutes)
        available_seconds = max(budget_minutes - reserve, 0) * 60
        trace.append(
            BuildEvent(
                "reserve_blind_minutes",
                f"{reserve} of {budget_minutes} minutes reserved; "
                f"{available_seconds}s spendable",
            )
        )

        ranked = _ranked_rows(admitted, knobs)
        trace.append(BuildEvent("rank_items", f"{len(ranked)} items ranked"))

        groups, leftovers = _group_identical(ranked, knobs)
        trace.append(
            BuildEvent(
                "group_identical_signatures",
                f"{len(groups)} groups over "
                f"{sum(len(group.members) for group in groups)} items",
            )
        )

        shown = _fill_to_budget([*groups, *leftovers], available_seconds)
        trace.append(
            BuildEvent(
                "truncate_to_budget", f"{len(shown)} entries shown within {available_seconds}s"
            )
        )

        residual = flagged_total - _items_shown_count(shown)
        trace.append(
            BuildEvent(
                "compute_residual", f"{residual} of {flagged_total} remain provisional"
            )
        )

        return ReviewQueue(
            run_id=run_id,
            budget_minutes=budget_minutes,
            reserved_for_blind_minutes=reserve,
            flagged_total=flagged_total,
            shown=tuple(shown),
            residual_provisional=residual,
            groups=tuple(groups),
            build_seconds=perf_counter() - started,
            build_trace=tuple(trace),
        )

    def queue(
        self, run_id: str = "run-1", budget_minutes: int | None = None
    ) -> tuple["ReviewItem | ReviewGroup", ...]:
        """The built queue as its consumer reads it (`§3.15`): the shown
        entries — signature groups collapsed, singletons per-item — in
        presentation order.

        ``build_review(store).queue()`` is the store form's declared read
        (the c05/c07/c09 consumer limbs' shape): no run id and no budget
        arrive, so the module's default budget governs. The residual header
        and the per-stage trace stay on ``build_queue`` — this is the queue's
        face, not its bookkeeping."""
        budget = (
            int(budget_minutes)
            if budget_minutes is not None
            else int(self._default_budget or REVIEW_DEFAULT_BUDGET_MINUTES)
        )
        return self.build_queue(run_id, budget).shown

    def rank_queue_items(self, run_id: str) -> tuple[ReviewItem, ...]:
        """The ranking, separable from the queue (`FR-REVIEW-03`): every admitted
        item, best-first, each carrying its ``expected_value`` — the ranking's
        full output, without the budget's truncation."""
        knobs = _calibration_knobs()
        admitted = self._admitted_rows()
        ranked = _ranked_rows(admitted, knobs)
        return tuple(_itemize(row, knobs) for row in ranked)

    def group_signature(self, row: Any) -> dict[str, Any]:
        """The exact Phase 1 grouping signature (`CT-REVIEW-20`): the five
        declared components and nothing else — a rule with fewer components
        groups items the clause says are different; one with more never groups
        anything."""
        return _signature_of(row)

    # -- actions -------------------------------------------------------------------------------------

    def act(
        self,
        item: Any,
        action: str,
        new_band: str | None = None,
        review_seconds: float = 0,
    ) -> str | None:
        """One teacher decision on one queue item (§3.15's Protocol member).

        ``accept`` keeps the proposed band; ``edit``/``override`` name a new one
        — an edit without a band is refused, because there is nowhere to put a
        number (`FR-REVIEW-10`); ``skip`` writes no label and leaves the item
        residual (`CT-REVIEW-06`). Acting on a superseded score is refused with
        a refresh message (`CT-REVIEW-15`). Returns the label id, or None.
        """
        if action not in _ACTIONS:
            raise ValueError(f"{action!r} is not a review action; one of {_ACTIONS}")
        if action == "skip":
            return None
        if action in ("edit", "override") and new_band is None:
            raise ValueError("an edit names a band")
        item = self._as_item(item)
        self._check_not_stale(item)
        label = self._write_label(
            item,
            label_type=action,
            teacher_band=item.proposed_band if action == "accept" else new_band,
            review_seconds=review_seconds,
            review_queue_action=action,
        )
        self._acted.add(item.score_id)
        return label.label_id

    def act_on_group(self, group: Any, band: str, review_seconds: float = 0) -> list[str]:
        """One band decision over a whole group (§3.15's Protocol member): one
        label per member (`CT-REVIEW-13`) — a single group label would
        under-weight bulk decisions in every agreement figure — each carrying
        the member's own identity and the per-member share of the time."""
        members = tuple(getattr(group, "members"))
        if not members:
            return []
        per_member = review_seconds / len(members)
        label_ids: list[str] = []
        for member in members:
            self._check_not_stale(member)
            action = "accept" if band == member.proposed_band else "edit"
            label = self._write_label(
                member,
                label_type=action,
                teacher_band=band,
                review_seconds=per_member,
                review_queue_action=action,
            )
            self._acted.add(member.score_id)
            label_ids.append(label.label_id)
        return label_ids

    def escalate(self, score_id: str) -> SupersededScore:
        """Mark one score superseded (`CT-REVIEW-15`'s induced race): every queue
        built before this call carries the old version, and an action on it is
        refused with a refresh message."""
        current = self._versions.get(score_id)
        if current is None:
            row = self._rows_by_id.get(score_id)
            current = int(getattr(row, "version", 1) or 1) if row is not None else 1
        bumped = current + 1
        self._versions[score_id] = bumped
        return SupersededScore(score_id=score_id, version=bumped)

    def close(self) -> None:
        """Release the rung-2 store handle, if this service was opened over one."""
        if self._store is not None:
            self._store.close()
            self._store = None

    def _with_store(self, store: Any) -> "ReviewService":
        """Attach the rung-2 store handle (``open_review``'s plumbing)."""
        self._store = store
        return self

    # -- internals -----------------------------------------------------------------------------------

    def _admitted_rows(self) -> list[Any]:
        """The still-flagged rows this run admits (`_admitted`), minus the ones
        this service has already acted on."""
        return [
            row for row in _admitted(self._rows) if _score_id_of(row) not in self._acted
        ]

    def _as_item(self, item: Any) -> ReviewItem:
        """The queue entry an action arrives on. A ``ReviewGroup`` is not an
        action target — ``act_on_group`` is the group's path."""
        if getattr(item, "members", None) is not None:
            raise ReviewError(
                "act() takes a single review item; a group is acted on through "
                "act_on_group, which writes one label per member"
            )
        if getattr(item, "score_id", None) is None:
            raise ReviewError("act() takes a queue item carrying score_id")
        return item

    def _check_not_stale(self, item: ReviewItem) -> None:
        current = self._versions.get(item.score_id)
        if current is not None and current != item.version:
            raise StaleReviewItemError(
                f"score {item.score_id!r} is stale: it was superseded by an escalation "
                f"(the store now carries version {current}, the queue built version "
                f"{item.version}); refresh the queue before acting"
            )

    def _write_label(
        self,
        item: ReviewItem,
        *,
        label_type: str,
        teacher_band: str | None,
        review_seconds: float,
        review_queue_action: str,
    ) -> LabelRecord:
        row = self._rows_by_id.get(item.score_id)
        self._versions.setdefault(item.score_id, item.version)
        label = LabelRecord(
            label_id=f"label-{len(self._labels) + 1:04d}",
            label_type=label_type,
            # A queue action happens with the system's band on the screen
            # (`CT-REVIEW-08`'s per-path values; the blind flow's earned 0 is #111's).
            saw_system_output=1,
            routing=str(getattr(row, "routing", "queued") or "queued"),
            origin=str(getattr(row, "origin", "escalation") or "escalation"),
            evaluation_mode=str(getattr(row, "evaluation_mode", "judged") or "judged"),
            review_seconds=review_seconds,
            system_band=item.proposed_band,
            teacher_band=teacher_band,
            actor=self._actor_name,
            timestamp=self._clock(),
            score_id=item.score_id,
            criterion_id=item.criterion_id,
            review_queue_action=review_queue_action,
            # ``new_points`` is derived from ``new_band`` through `CT-PKG-05`'s
            # pinned mapping (`FR-REVIEW-10`) — and the mapping is defined in
            # exactly one place (`aeh.pkg.points_for_band`, `NFR-AGG-02`), so the
            # derivation here is a *route through* it, which arrives with the
            # label store (#110). Until then an in-memory label records the band
            # alone rather than inventing a second mapping.
            new_points=None,
        )
        self._labels.append(label)
        return label


# --- the constructors -------------------------------------------------------------------------------


def build_review(
    scores: Any = None,
    *,
    actor: str = "teacher",
    clock: Callable[[], str] | None = None,
    catalog: Any = None,
    config: Any = None,
    review_blind_reserve_minutes: int | None = None,
    review_blind_n: int | None = None,
    review_whole_grade_n: int | None = None,
    review_default_budget_minutes: int | None = None,
) -> ReviewService:
    """The rung-0/1 constructor: a review service over score rows — or, in the
    store form, over a whole store.

    The four §3.15 knobs arrive as keywords (``review_blind_n=20``), as
    ``config=`` attributes named after the constants, or not at all — the
    module constants are the declared defaults (`CT-REVIEW-17`). The store
    form (`build_review(store)`, the c05/c07/c09 consumer limbs' declared
    shape) reads every cohort the store carries and admits the same
    population `open_review` does; the queue is then the service's read path
    (``.queue()``)."""
    if scores is not None and hasattr(scores, "cohort"):
        return _service_from_store(
            scores,
            actor=actor,
            clock=clock,
            catalog=catalog,
            config=config,
            review_blind_reserve_minutes=review_blind_reserve_minutes,
            review_blind_n=review_blind_n,
            review_whole_grade_n=review_whole_grade_n,
            review_default_budget_minutes=review_default_budget_minutes,
        )
    return ReviewService(
        scores or (),
        actor=actor,
        clock=clock,
        catalog=catalog,
        config=config,
        blind_reserve_minutes=_resolve_knob(
            review_blind_reserve_minutes, config, "REVIEW_BLIND_RESERVE_MINUTES",
            REVIEW_BLIND_RESERVE_MINUTES,
        ),
        blind_n=_resolve_knob(
            review_blind_n, config, "REVIEW_BLIND_N", REVIEW_BLIND_N
        ),
        whole_grade_n=_resolve_knob(
            review_whole_grade_n, config, "REVIEW_WHOLE_GRADE_N", REVIEW_WHOLE_GRADE_N
        ),
        default_budget_minutes=_resolve_knob(
            review_default_budget_minutes, config, "REVIEW_DEFAULT_BUDGET_MINUTES",
            REVIEW_DEFAULT_BUDGET_MINUTES,
        ),
    )


def _store_cohort_ids(store: Any) -> list[str]:
    """The cohort ids a store carries, in stable id order — the same discovery
    the store's own surfaces use (`cohorts/<cohort_id>.sqlite`, one file per
    administration; `aeh.det` and `aeh.orch` walk the identical layout)."""
    return sorted(
        path.stem for path in Path(store.data_dir, "cohorts").glob("*.sqlite")
    )


def _service_from_store(
    store: Any,
    *,
    cohort_ids: Sequence[str] | None = None,
    actor: str = "teacher",
    clock: Callable[[], str] | None = None,
    catalog: Any = None,
    config: Any = None,
    review_blind_reserve_minutes: int | None = None,
    review_blind_n: int | None = None,
    review_whole_grade_n: int | None = None,
    review_default_budget_minutes: int | None = None,
) -> ReviewService:
    """The rung-2 constructor's body, shared by ``open_review`` (one named
    cohort) and ``build_review`` (a whole store — every cohort it carries).

    Reads the cohort's stored ``criterion_score`` rows through ``aeh.store`` —
    the deterministic store, no egress — and maps them onto the score-row
    vocabulary with honest defaults for the columns the store does not carry.
    The query takes both of the teacher's routings (`CT-AGG-06`: ``queued``;
    the provisional family whose fallback and breaker rows `CT-AGG-07` binds
    this module to surface); the state column rides through to the item, and
    the admission predicate — the same one the in-memory service runs — does
    the excluding."""
    # The store's tier migration chains are concatenated at import time by the
    # modules that own the schema they add (CLAUDE.md): the cohort handle this
    # opens must not be the first open in a process that skipped the imports.
    import aeh.agg  # noqa: F401
    import aeh.det  # noqa: F401
    import aeh.extract  # noqa: F401
    import aeh.grade  # noqa: F401
    import aeh.ingest  # noqa: F401
    import aeh.integ  # noqa: F401
    import aeh.judge  # noqa: F401
    import aeh.orch  # noqa: F401
    import aeh.pkg  # noqa: F401
    import aeh.synth  # noqa: F401

    from aeh.store import Statement

    if cohort_ids is None:
        cohort_ids = _store_cohort_ids(store)
    rows: list[Any] = []
    for cohort_id in cohort_ids:
        rows.extend(
            _row_mapping(row)
            for row in store.cohort(cohort_id).query(
                Statement(
                    "SELECT * FROM criterion_score "
                    "WHERE routing IN ('queued', 'provisional')"
                )
            )
        )
    knobs = _calibration_knobs()
    mapped = [
        _StoredScoreRow(mapping, knobs["default_est_seconds"]) for mapping in rows
    ]
    return build_review(
        mapped,
        actor=actor,
        clock=clock,
        catalog=catalog,
        config=config,
        review_blind_reserve_minutes=review_blind_reserve_minutes,
        review_blind_n=review_blind_n,
        review_whole_grade_n=review_whole_grade_n,
        review_default_budget_minutes=review_default_budget_minutes,
    )._with_store(store)


class _StoredScoreRow:
    """One stored ``criterion_score`` row as the ranking reads it: the store's
    column names mapped onto the score-row vocabulary, with the row's own
    values wherever the store carries them and honest defaults where it does
    not (the review inputs the store does not carry yet arrive with their
    stories — an override history the store has none of reads as no data)."""

    def __init__(self, mapping: Mapping[str, Any], default_est_seconds: float) -> None:
        submission_id = mapping.get("submission_id")
        criterion_id = mapping.get("criterion_id")
        self.score_id = f"{submission_id}:{criterion_id}"
        self.criterion_id = criterion_id
        self.submission_id = submission_id
        self.routing = mapping.get("routing")
        self.origin = mapping.get("origin", "escalation")
        self.evaluation_mode = mapping.get("evaluation_mode", "judged")
        self.state = mapping.get("state")
        self.proposed_band = mapping.get("band")
        self.panel_spread = mapping.get("panel_spread")
        self.adverse_integrity_signals = mapping.get("adverse_integrity_signals") or 0
        self.transcription_overlap = mapping.get("transcription_overlap")
        self.historical_override_rate = mapping.get("historical_override_rate")
        self.criterion_weight = mapping.get("criterion_weight")
        self.grade_boundary_delta = mapping.get("grade_boundary_delta")
        est = mapping.get("est_seconds")
        self.est_seconds = default_est_seconds if not est else est
        self.self_confidence = mapping.get("confidence")
        self.spans_verified = mapping.get("spans_verified")
        self.evidence_present = mapping.get("evidence_present")
        self.sufficiency_flag = mapping.get("sufficiency_flag")
        self.ocr_overlap_risk = mapping.get("ocr_overlap_risk")
        self.version = 1
        self.scoring_model = "atomic"


def _row_mapping(row: Any) -> dict[str, Any]:
    """One store row as a plain mapping, whatever ``Row`` shape the tier hands
    back."""
    try:
        return {key: row[key] for key in row.keys()}
    except AttributeError:
        return dict(row)


def open_review(
    data_dir: Path | str,
    *,
    run_id: str,
    actor: str = "teacher",
    clock: Callable[[], str] | None = None,
    catalog: Any = None,
    config: Any = None,
    review_blind_reserve_minutes: int | None = None,
    review_blind_n: int | None = None,
    review_whole_grade_n: int | None = None,
    review_default_budget_minutes: int | None = None,
) -> ReviewService:
    """The rung-2 constructor: a review service over a stored run's flagged rows.

    Reads the cohort's own ``criterion_score`` rows through ``aeh.store`` — the
    deterministic store, no egress — and admits the same population the
    in-memory service does. Until #110 lands the label store, actions write
    in-memory labels; the queue and the ranking are complete.
    """
    from aeh.store import open_store as _open_store

    store = _open_store(Path(data_dir))
    try:
        return _service_from_store(
            store,
            cohort_ids=[run_id],
            actor=actor,
            clock=clock,
            catalog=catalog,
            config=config,
            review_blind_reserve_minutes=review_blind_reserve_minutes,
            review_blind_n=review_blind_n,
            review_whole_grade_n=review_whole_grade_n,
            review_default_budget_minutes=review_default_budget_minutes,
        )
    except Exception:
        store.close()
        raise