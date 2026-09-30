"""Which rows the queue admits, how they rank by expected value, grouping, and budget fill."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .settings import _calibration_knobs
from .errors import ReviewError
from .records import CriterionOverrideRank, ReviewGroup, ReviewItem
from .stored_rows import _row_mapping, _StoredScoreRow


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


#: `FR-REVIEW-08`'s residual mark: an item nobody looked at is provisional and
#: unreviewed, and it says so. ``aeh.agg`` writes the mark when it routes the
#: row; this module only ever leaves it alone — ``end_session``/``close_run``
#: persist the residual by never touching it.
_RESIDUAL_STATE = "provisional_unreviewed"


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
    """A row's five-part grouping signature, as a mapping by component name (CT-REVIEW-20)."""
    return {component: getattr(row, component) for component in SIGNATURE_COMPONENTS}


def _group_key(row: Any) -> tuple:
    """The key two rows must share to be grouped: the criterion and the signature."""
    signature = _signature_of(row)
    return (str(getattr(row, "criterion_id", "")),) + tuple(
        signature[component] for component in SIGNATURE_COMPONENTS
    )


def _admitted(rows: Iterable[Any]) -> list[Any]:
    """The rows the queue may show: the teacher's population by routing and evaluation mode
    (CT-AGG-06, FR-REVIEW-06, FR-REVIEW-07), without the origins that are never shown
    (FR-REVIEW-07), and only work still waiting (CT-REVIEW-05).

    The state is passed through rather than used to filter: `ungradeable_by_panel` rows must be
    shown differently from ordinary provisional ones (CT-AGG-07), and a state filter would hide
    them.

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
    """The row's review-time estimate, or the default when it has none (FR-REVIEW-16). A missing or
    non-positive estimate is missing data, not a free item."""
    raw = getattr(row, "est_seconds", None)
    if raw is None:
        return default
    value = float(raw)
    return default if value <= 0 else value


def _override_rate_of(row: Any, knobs: Mapping[str, float]) -> float:
    """The criterion's measured override rate, or the no-data default (CT-STATS-09): a criterion
    nobody has reviewed is not one nobody disagrees with."""
    rate = getattr(row, "historical_override_rate", None)
    if rate is None:
        return knobs["override_rate_no_data"]
    return float(rate)


def _p_error(row: Any, knobs: Mapping[str, float]) -> float:
    """The chance the score is wrong, from the four observable signals, equally weighted, with
    integrity divided by its cap (FR-REVIEW-03). `self_confidence` is not used (R22)."""
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
    """The criterion's share of the final grade, weighted by how close the grade is to a boundary.
    """
    weight = float(getattr(row, "criterion_weight", 0.0) or 0.0)
    delta = float(getattr(row, "grade_boundary_delta", 0.0) or 0.0)
    proximity = 1.0 / (1.0 + abs(delta) / knobs["boundary_half_width"])
    return weight * proximity


def _expected_value(row: Any, knobs: Mapping[str, float]) -> float:
    """The ranking score: `(chance the score is wrong × impact) / estimated seconds`
    (FR-REVIEW-03)."""
    est = _est_seconds_of(row, knobs["default_est_seconds"])
    return (_p_error(row, knobs) * _impact_of(row, knobs)) / est


# --- items and groups -------------------------------------------------------------------------------


def _itemize(row: Any, knobs: Mapping[str, float]) -> ReviewItem:
    """One score row as the queue shows it (design §3.15). Fields the row does not carry stay
    empty; the queue does not invent package context."""
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
        # CT-SYNTH-01/03 (#534): a narrative M-SYNTH flagged for a score claim is withheld,
        # read together with its flag; an unflagged one is shown exactly as M-SYNTH wrote it
        # (M-REVIEW does not re-check the text).
        narrative=(None if getattr(row, "score_claim_flag", 0)
                   else getattr(row, "narrative", None)),
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
    """The rows ranked best first by expected value per review second, holistic criteria first on
    ties (FR-AGG-06), otherwise stable (NFR-REVIEW-02)."""
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
    """Collapse rows with identical signatures into groups (CT-REVIEW-20): same criterion, same
    band, same four integrity signals. A group needs two or more members; single rows stay as
    items. Groups rank above single items and among themselves by expected value (FR-REVIEW-05)."""
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
    """Fill the budget greedily in ranked order: take every entry that fits, skip one that does
    not, never reorder (NFR-REVIEW-02, NFR-REVIEW-05). If nothing fits, the top entry is still
    shown and the residual says so, so a non-empty queue never shows nothing."""
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
    """How many review items the shown entries cover; a group counts each member (CT-REVIEW-04)."""
    total = 0
    for entry in shown:
        members = getattr(entry, "members", None)
        total += len(members) if members is not None else 1
    return total


# --- the ranking, at both of its declared shapes ----------------------------------------------------


def rank_queue_items(items: Sequence[Any] | None = None, *, criteria: Any = None) -> Any:
    """Rank queue items, in either of the two declared forms.

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
    """Rank criteria the same way `aeh.agg.rank_criteria_for_escalation` does (CT-STATS-09):
    no-data criteria first, then by override rate descending, keeping the caller's order on ties.
    """
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
