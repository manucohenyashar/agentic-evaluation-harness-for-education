"""The Minimum Viable Validation Protocol: six separately reported steps and their results."""

from __future__ import annotations

from typing import TYPE_CHECKING

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from aeh.pkg import NoValidationData

from .admissibility import _system_side
from .agreement import AgreementFigure, _band_ordinals

if TYPE_CHECKING:
    from .service import ValidationStats


# --- the MVVP: six separately-reported protocol steps (#116, FR-STATS-05) -------------------------

#: The six MVVP steps and the requirement each reports against — `FR-STATS-05`'s
#: own mapping, as data, so a step's ``requirement`` cannot be mis-mapped by a
#: call site: step 1 is the chance-corrected agreement figure (`FR-STATS-02`),
#: step 2 the order/position swap (`FR-STATS-15`), step 3 the replication floor
#: (`FR-STATS-16`), step 4 cross-validation by assignment type (`FR-STATS-17`),
#: step 5 the consistency-bias pairing (`FR-STATS-18`) and step 6 the
#: compression check (`FR-STATS-06`, HLD §2.5's v2.7 addition).
MVVP_STEP_REQUIREMENTS: dict[int, str] = {
    1: "FR-STATS-02",
    2: "FR-STATS-15",
    3: "FR-STATS-16",
    4: "FR-STATS-17",
    5: "FR-STATS-18",
    6: "FR-STATS-06",
}


#: `FR-STATS-19`'s four re-run triggers (`CT-STATS-08`, HLD R30): a change to
#: any one of the four forces the **full** protocol's re-run, and the result
#: names the exact value it measured for each (`CT-STATS-08`). The set is the
#: design's trigger set, held as data so a fifth dimension arriving is a change
#: to this tuple first.
MVVP_RERUN_DIMENSIONS: tuple[str, ...] = (
    "panel_member",
    "model_build",
    "quantization",
    "prompt_template_version",
)


#: `FR-STATS-18`'s pairing threshold: *"Where a judge's measured self-agreement
#: (FR-STATS-16) exceeds 0.95 …"* — strictly exceeds; a judge at exactly 0.95
#: is below the trigger.
MVVP_SELF_AGREEMENT_PAIRING_THRESHOLD = 0.95


#: `FR-STATS-16`'s replication floor: at least this many independent runs per
#: judgment. The measured rate the caller supplies is that replication's
#: summary; the record carries the floor itself (`runs_required`), so a reader
#: can see what a supplied rate had to summarise — the actual run count stays
#: with the live tier's measurement (`TC-STATS-16`), not with this record.
MVVP_REPLICATION_RUNS = 3


#: The step outcomes' declared not-measured reasons — the absence-is-a-type
#: discipline (`CT-STATS-03`) extended to the per-step records: a step that
#: could not measure reports the declared reason, never a bare ``None`` and
#: never a raise (`CT-STATS-16`). A measured value and an unmeasured one are
#: distinguishable in the record itself, which is what keeps an absent figure
#: from rendering as a zero.
_NO_POSITION_MEASUREMENT = "no_position_bias_measurement_supplied"


_NO_REPLICATION_MEASUREMENT = "no_replication_measurement_supplied"


_NOT_DECLARED = "not_declared"


_ASSIGNMENT_TYPE_NOT_RECORDED = "assignment_type_not_recorded"


_NO_ASSIGNMENT_TYPE_NAMED = "no_assignment_type_named"


_NO_LABELS_FOR_ASSIGNMENT_TYPE = "no_labels_for_assignment_type"


#: The compression check's limitation, carried **in the return value** rather
#: than a footnote (`FR-STATS-06`, `CT-STATS-10`): the check compares the
#: panel's band shape against the gold's, and two distributions drifting to
#: the same narrow shape together are invisible to any panel-vs-gold
#: comparison. `TC-STATS-C10` asserts on this content.
_CO_COMPRESSION_LIMITATION = "cannot detect panel and teacher compressing together"


def _validated_rate_map(
    values: Mapping[str, Any] | None, name: str
) -> dict[str, float]:
    """The per-judge rates from a measured input, checked to be what they claim.

    A programming error propagates (`CT-STATS-16`'s other half): a non-mapping,
    a non-string judge id, a non-numeric rate or a boolean — a bool is an
    ``int`` subclass and ``isinstance(True, float)`` is ``False`` for a reason —
    each raises. A rate outside 0..1 is a value no measurement can produce.
    """
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise TypeError(
            f"run_mvvp() got {name}={values!r}; a per-judge rate map is a "
            "mapping of judge id to rate, and anything else is a programming "
            "error (CT-STATS-16 raises on programming errors)"
        )
    validated: dict[str, float] = {}
    for judge_id, rate in values.items():
        if not isinstance(judge_id, str):
            raise TypeError(
                f"run_mvvp() got {name} key {judge_id!r}; a judge id is a string "
                "(CT-STATS-16 raises on programming errors)"
            )
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise TypeError(
                f"run_mvvp() got {name}[{judge_id!r}]={rate!r}; a measured rate "
                "is a number, and anything else is a programming error"
            )
        if not 0.0 <= float(rate) <= 1.0:
            raise ValueError(
                f"run_mvvp() got {name}[{judge_id!r}]={rate!r}; a rate lives in "
                "[0, 1] and anything outside is a figure that was never measured"
            )
        validated[judge_id] = float(rate)
    return validated


def _normalized_mvvp_configuration(
    configuration: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The four trigger dimensions, normalized to the values the run measured.

    Every dimension the result names (`CT-STATS-08`'s "a consumer can verify
    the match itself"): an undeclared dimension is carried as ``None`` — the
    run measured nothing there, and saying so is the honest echo. An unknown
    key is a programming error, not a silent drop: a configuration key the
    report silently drops is a trigger the no-carry-forward guarantee misses.
    """
    if configuration is None:
        return {dim: None for dim in MVVP_RERUN_DIMENSIONS} | {"panel_member": ()}
    unknown = sorted(set(configuration) - set(MVVP_RERUN_DIMENSIONS))
    if unknown:
        raise TypeError(
            f"run_mvvp() got unknown configuration keys {unknown}; the trigger "
            f"set is FR-STATS-19's {MVVP_RERUN_DIMENSIONS}, and a dimension the "
            "report does not name is a trigger it cannot notice (CT-STATS-08)"
        )
    raw_panel = configuration.get("panel_member")
    if raw_panel is None:
        panel: tuple[str, ...] = ()
    elif isinstance(raw_panel, str) or not isinstance(raw_panel, Iterable):
        raise TypeError(
            f"run_mvvp() got panel_member={raw_panel!r}; the panel is the "
            "panel's members — a sequence of judge ids, not a single id"
        )
    else:
        panel = tuple(raw_panel)
    bad = [member for member in panel if not isinstance(member, str)]
    if bad:
        raise TypeError(
            f"run_mvvp() got panel members {bad!r}; a judge id is a string "
            "(CT-STATS-16 raises on programming errors)"
        )
    normalized: dict[str, Any] = {"panel_member": panel}
    for dimension in MVVP_RERUN_DIMENSIONS:
        if dimension == "panel_member":
            continue
        value = configuration.get(dimension)
        if value is not None and not isinstance(value, str):
            raise TypeError(
                f"run_mvvp() got {dimension}={value!r}; a build identity is a "
                "string or None, and anything else is a programming error"
            )
        normalized[dimension] = value
    return normalized


def _mvvp_result_id(
    assignment_type: str | None, measured_configuration: Mapping[str, Any]
) -> str:
    """The result id: a content hash of what the result is a claim about.

    `FR-STATS-19`/`CT-STATS-08`: a validation record must not outlive the thing
    it validated (R30), so the id is a digest of the assignment type and the
    four trigger dimensions — a changed dimension digests differently, and two
    runs under one configuration name the same claim. The panel digests in
    sorted order: a panel is a set of members, and a member-listing order that
    changed is not a panel change.
    """
    payload = json.dumps(
        {
            "assignment_type": assignment_type,
            **{
                dimension: (
                    sorted(measured_configuration[dimension])
                    if dimension == "panel_member"
                    else measured_configuration[dimension]
                )
                for dimension in MVVP_RERUN_DIMENSIONS
            },
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "mvvp-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class PositionBiasResult:
    """Step 2's result for one judge (FR-STATS-15): the rate of band changes on the held-out
    fixtures when the worked-example order and the reference-material order are shuffled.

    ``measured=False`` is an explicit not-measured value, not a null — the
    rate's oracle is the live tier's (`TC-STATS-16`, where model calls run
    through the injected provider seam), and the headless report says the
    measurement did not happen rather than rendering a rate it does not have
    (`CT-STATS-03`'s absence-is-a-type, extended to the step records). The
    rate is reported verbatim when supplied — never clamped, floored or
    omitted (`TC-JUDGE-C17`'s finding-not-failure discipline)."""

    judge_id: str
    measured: bool
    band_change_rate: float | None
    reason: str


@dataclass(frozen=True)
class ReplicationResult:
    """Step 3's result for one judge (FR-STATS-16), reporting two separate claims about two
    different things together.

    ``self_agreement`` is M-STATS's measurement: the per-judge rate over
    ``runs_required`` or more independent runs, reported verbatim — a value
    below 1.0 is the finding the protocol exists to surface, not a failure
    (`TC-JUDGE-C17`). ``backend_claims_deterministic_at_temperature_zero``
    is M-PROV's **declared** claim about the backend (`CT-PROV-04`), read off
    the bound provider's capabilities by whoever binds the transport — a
    promise, not a measurement, and never merged into the rate it sits
    beside: a backend that claims determinism and a judge that disagrees
    with itself is a finding only where both figures are readable together."""

    judge_id: str
    measured: bool
    self_agreement: float | None
    reason: str
    runs_required: int
    backend_claims_deterministic_at_temperature_zero: bool | None
    backend_claim_source: str


@dataclass(frozen=True)
class CrossValidationOutcome:
    """Step 4's result (FR-STATS-17): agreement figures for one assignment type, one criterion at a
    time, and a refusal of any wider claim.

    A figure spanning assignment types is not representable in this value:
    one ``assignment_type`` is a field of the outcome, not a dimension that
    could be summed over, so the spanning claim has no surface to render on —
    and where labels carry types and the caller names none, the outcome is
    the disclosed refusal (`no_assignment_type_named`), not a pooled figure
    under this flag. (`CT-STATS-04`'s sweep of the refusal is keyed on
    `aggregate` — #118 — which is where the behavioural refusal lives; this
    outcome carries the structural half, ``spanning_refused``, because a
    report cannot be asked to span and a value that cannot represent the span
    cannot emit it.)"""

    assignment_type: str | None
    figures: Mapping[str, "AgreementFigure | NoValidationData"]
    assignment_type_recorded: bool
    reason: str
    spanning_refused: bool


@dataclass(frozen=True)
class SelfAgreementPairing:
    """One judge's step-3 rate paired with its step-2 position-bias result; never one without the
    other (FR-STATS-18).

    The clause's requirement is where the threshold bites — a judge whose
    measured self-agreement exceeds 0.95 — and ``pairing_required`` marks
    that; the pair is reported for **every** judge in scope, because a module
    that pairs the figures for every judge is not violating anything, and a
    judge above the threshold reads its position-bias result beside its
    stability figure whether the bias was measured or not: high stability
    reported alone reads as reassurance, and a judge that answers identically
    every time may simply be anchored (§2.3)."""

    judge_id: str
    self_agreement: float | None
    self_agreement_measured: bool
    self_agreement_reason: str
    pairing_required: bool
    position_bias: PositionBiasResult


@dataclass(frozen=True)
class CompressionOutcome:
    """Step 6's result (FR-STATS-06): the shape of the panel's bands against the gold labels', over
    the same label pairs step 1 uses.

    ``band_entropy`` is the distribution's Shannon entropy in bits and
    ``interior_rate`` the rate of non-extreme bands; ``panel_narrower`` is
    the comparison's answer — the panel distribution's entropy lower than
    the gold's, the shape a panel compressing toward the middle produces.
    ``stated_limitation`` is part of the return value, not a footnote
    (`CT-STATS-10`): the check compares two distributions measured over the
    same labels, and a panel and the gold compressing **together** are
    invisible to it — the one failure mode the check cannot see, stated
    where a consumer reads the number."""

    gold_band_entropy: float | None
    gold_interior_rate: float | None
    panel_band_entropy: float | None
    panel_interior_rate: float | None
    panel_narrower: bool | None
    stated_limitation: str
    n: int


@dataclass(frozen=True)
class MVVPStep:
    """One protocol step's own record (CT-STATS-07).

    Six of these travel on one report — never a seventh that summarises
    them. ``requirement`` is the FR the step reports against (`FR-STATS-05`'s
    mapping); ``outcome`` is the step's own value — a figure, an absence or a
    per-judge mapping, whatever the step measured — and is never ``None``:
    a step that could not measure reports the not-measured value with its
    declared reason, because the six answers are the report's substance
    (`CT-STATS-16`: insufficient data is a value). ``paired_results`` is
    `FR-STATS-18`'s pairing, populated where the step produces one."""

    step: int
    requirement: str
    outcome: Any
    measured_at: datetime
    measured_configuration: Mapping[str, Any]
    paired_results: Mapping[str, SelfAgreementPairing]


@dataclass(frozen=True)
class MVVPReport:
    """The MVVP report: six separately reported steps, one configuration, one result id
    (FR-STATS-05, FR-STATS-19).

    ``result_id`` is content-addressed on the assignment type and the four
    re-run trigger dimensions — a changed dimension is a different result by
    construction, which is what makes *"re-runs whenever … changes"*
    (`FR-STATS-19`, HLD R30) a property of the type rather than a habit of
    the caller. ``contributing_results`` names what this value was built
    from — itself, and nothing else: the provenance is required rather than
    read with a default, because a merge leaves no trace by construction and
    a consumer verifying *"not reused, not shown, not merged"* (`CT-STATS-08`)
    has to be able to check. There is deliberately no ``passed``: six
    individually-reported steps, never one pass/fail (`CT-STATS-07`)."""

    assignment_type: str | None
    steps: Mapping[int, MVVPStep]
    result_id: str
    measured_configuration: Mapping[str, Any]
    contributing_results: tuple[str, ...]
    measured_at: datetime
    judges_in_scope: tuple[str, ...]


def _cross_validation_outcome(
    stats: "ValidationStats", assignment_type: str | None, admissible: list[Any]
) -> CrossValidationOutcome:
    """Step 4: agreement for each assignment type (FR-STATS-17).

    The store's label table predates the assignment-type column the HLD's
    label schema names, so the dimension is read off the labels when they
    carry it — duck-typed, the way `_system_side` reads the band pair — and
    its absence is **disclosed** (`assignment_type_not_recorded`) rather than
    papered over with a figure computed over a population nobody split. So is
    the unnamed type: where the labels carry types and the caller names none,
    the outcome is the disclosed refusal (`no_assignment_type_named`, no
    figures) — a figure over the union of every type is exactly the spanning
    figure the requirement refuses, and it is never computed. The figures are
    the single filter's own application: the matching labels are built into a
    sub-surface whose `agreement` routes through the same admissible
    population every other figure uses (`NFR-STATS-04`)."""
    from .service import ValidationStats  # here, not at the top: .service imports this file
    typed = [
        label
        for label in admissible
        if getattr(label, "assignment_type", None) is not None
    ]
    if not typed:
        return CrossValidationOutcome(
            assignment_type=assignment_type,
            figures={},
            assignment_type_recorded=False,
            reason=_ASSIGNMENT_TYPE_NOT_RECORDED,
            spanning_refused=True,
        )
    if assignment_type is None:
        return CrossValidationOutcome(
            assignment_type=None,
            figures={},
            assignment_type_recorded=True,
            reason=_NO_ASSIGNMENT_TYPE_NAMED,
            spanning_refused=True,
        )
    population = [
        label for label in typed if getattr(label, "assignment_type") == assignment_type
    ]
    if not population:
        return CrossValidationOutcome(
            assignment_type=assignment_type,
            figures={},
            assignment_type_recorded=True,
            reason=_NO_LABELS_FOR_ASSIGNMENT_TYPE,
            spanning_refused=True,
        )
    sub = ValidationStats(
        population,
        scoring_models=stats._scoring_models,
        band_counts=stats._band_counts,
        administration_id=stats._administration_id,
    )
    criteria = sorted({getattr(label, "criterion_id", "") for label in population} - {""})
    return CrossValidationOutcome(
        assignment_type=assignment_type,
        figures={criterion: sub.agreement(criterion_id=criterion) for criterion in criteria}
        if criteria
        else {},
        assignment_type_recorded=True,
        reason="",
        spanning_refused=True,
    )


def _band_entropy(values: Sequence[int]) -> float | None:
    """The Shannon entropy of one side's band distribution, in bits.

    The compression check's first statistic (`FR-STATS-06`): the shape of
    what the panel produced, against the same measure of the gold's side.
    An empty population is ``None`` — no distribution, no entropy — and a
    unanimous one is a true 0.0, the narrowest claim a population can make."""
    if not values:
        return None
    total = len(values)
    entropy = -sum(
        (count / total) * math.log2(count / total)
        for count in Counter(values).values()
    )
    return 0.0 if entropy == 0 else entropy


def _interior_rate(values: Sequence[int], band_count: int) -> float | None:
    """The share of bands that are not at either end of the scale.

    The compression check's second statistic (`FR-STATS-06`): a panel that
    compresses toward the middle leaves fewer extreme bands than the gold's
    shape shows. Ordinals are 0-based (`_band_ordinals`), so interior means
    strictly between the scale's ends. A band count below 3 has no interior —
    the statistic says nothing there, and says so with ``None`` rather than a
    zero that would read as a measured extreme-heavy shape."""
    if not values:
        return None
    if band_count < 3:
        return None
    interior = sum(1 for value in values if 0 < value < band_count - 1)
    return interior / len(values)


def _compression_outcome(
    stats: "ValidationStats", admissible: list[Any]
) -> CompressionOutcome:
    """Step 6: the shape of the panel's bands against the gold labels', over the pairs both sides
    have (FR-STATS-06).

    The comparison routes through the single filter's application
    (`NFR-STATS-04`): the caller hands in the admissible population, and the
    two distributions are its panel side and its gold side. Below one paired
    label no distribution exists and every statistic is the explicit
    not-measured value. ``band_count`` is the larger of the declared counts
    and the inferred one — the declared half is the maximum over the surface's
    criteria, because the check is population-wide and keys on no single
    criterion, so one criterion's narrower declared count cannot bound it;
    both sides are measured against the same count either way, which is what
    keeps ``panel_narrower`` fair. The stated limitation is part of the value
    (`CT-STATS-10`), not a footnote beside it."""
    pairs = [
        (system, teacher)
        for system, teacher in (
            (_system_side(label), getattr(label, "teacher_band", None))
            for label in admissible
        )
        if system is not None and teacher is not None
    ]
    if not pairs:
        return CompressionOutcome(
            gold_band_entropy=None,
            gold_interior_rate=None,
            panel_band_entropy=None,
            panel_interior_rate=None,
            panel_narrower=None,
            stated_limitation=_CO_COMPRESSION_LIMITATION,
            n=0,
        )
    ordinals, inferred_band_count = _band_ordinals(pairs)
    band_count = max(max(stats._band_counts.values(), default=0), inferred_band_count)
    panel_bands = [system for system, _ in ordinals]
    gold_bands = [teacher for _, teacher in ordinals]
    panel_entropy = _band_entropy(panel_bands)
    gold_entropy = _band_entropy(gold_bands)
    panel_narrower = (
        panel_entropy < gold_entropy
        if panel_entropy is not None and gold_entropy is not None
        else None
    )
    return CompressionOutcome(
        gold_band_entropy=gold_entropy,
        gold_interior_rate=_interior_rate(gold_bands, band_count),
        panel_band_entropy=panel_entropy,
        panel_interior_rate=_interior_rate(panel_bands, band_count),
        panel_narrower=panel_narrower,
        stated_limitation=_CO_COMPRESSION_LIMITATION,
        n=len(pairs),
    )


def run_mvvp(
    self: "ValidationStats | None" = None,
    assignment_type: str | None = None,
    *,
    configuration: Mapping[str, Any] | None = None,
    measured_self_agreement: Mapping[str, Any] | None = None,
    measured_position_bias: Mapping[str, Any] | None = None,
    backend_claims_deterministic_at_temperature_zero: bool | None = None,
) -> MVVPReport:
    """Run the Minimum Viable Validation Protocol as six separately reported steps (FR-STATS-05,
    HLD §2.5).

    More detail: `docs/code-notes/stats.md`, section `mvvp.py: run_mvvp`.
    """
    from .service import ValidationStats  # here, not at the top: .service imports this file
    if assignment_type is not None and not isinstance(assignment_type, str):
        raise TypeError(
            f"run_mvvp() got assignment_type={assignment_type!r}; an assignment "
            "type is a string or None, and anything else is a programming error "
            "(CT-STATS-16 raises on programming errors)"
        )
    if backend_claims_deterministic_at_temperature_zero is not None and not isinstance(
        backend_claims_deterministic_at_temperature_zero, bool
    ):
        raise TypeError(
            "run_mvvp() got backend_claims_deterministic_at_temperature_zero="
            f"{backend_claims_deterministic_at_temperature_zero!r}; the backend's "
            "declaration is a bool or None — a claim is carried beside the "
            "measured rate, never computed, and anything else is a programming "
            "error (CT-STATS-16 raises on programming errors)"
        )
    measured_self = _validated_rate_map(
        measured_self_agreement, "measured_self_agreement"
    )
    measured_swap = _validated_rate_map(
        measured_position_bias, "measured_position_bias"
    )
    measured_configuration = _normalized_mvvp_configuration(configuration)
    panel = measured_configuration["panel_member"]
    if panel:
        surplus = sorted((set(measured_self) | set(measured_swap)) - set(panel))
        if surplus:
            raise TypeError(
                f"run_mvvp() got measured rates for judges outside the declared "
                f"panel {surplus}; the panel is the report's scope "
                f"({measured_configuration['panel_member']!r}), and a rate for a "
                "judge it does not name is either a stale measurement or a "
                "mistyped id — the same silent drop the unknown-configuration-"
                "key guard refuses (CT-STATS-16 raises on programming errors)"
            )

    stats = self if self is not None else ValidationStats()
    admissible = stats.admissible_labels()
    measured_at = datetime.now(timezone.utc)
    judges = panel or tuple(sorted(set(measured_self) | set(measured_swap)))

    # --- step 1: the agreement surface (FR-STATS-02), one figure per criterion
    criteria = sorted({getattr(label, "criterion_id", "") for label in admissible} - {""})
    step1_outcome = (
        {criterion: stats.agreement(criterion_id=criterion) for criterion in criteria}
        if criteria
        else stats.agreement()
    )

    # --- step 2: the order/position swap, per judge (FR-STATS-15) ------------
    step2_outcome = {
        judge: (
            PositionBiasResult(
                judge_id=judge,
                measured=True,
                band_change_rate=measured_swap[judge],
                reason="",
            )
            if judge in measured_swap
            else PositionBiasResult(
                judge_id=judge,
                measured=False,
                band_change_rate=None,
                reason=_NO_POSITION_MEASUREMENT,
            )
        )
        for judge in judges
    }

    # --- step 3: the replication floor (FR-STATS-16), two claims, one row ----
    step3_outcome = {
        judge: ReplicationResult(
            judge_id=judge,
            measured=judge in measured_self,
            self_agreement=measured_self.get(judge),
            reason="" if judge in measured_self else _NO_REPLICATION_MEASUREMENT,
            runs_required=MVVP_REPLICATION_RUNS,
            backend_claims_deterministic_at_temperature_zero=(
                backend_claims_deterministic_at_temperature_zero
            ),
            backend_claim_source=(
                "declared_by_caller"
                if backend_claims_deterministic_at_temperature_zero is not None
                else _NOT_DECLARED
            ),
        )
        for judge in judges
    }

    # --- step 4: cross-validation by assignment type (FR-STATS-17) -----------
    step4_outcome = _cross_validation_outcome(stats, assignment_type, admissible)

    # --- step 5: the consistency-bias pairing (FR-STATS-18) ------------------
    step5_outcome = {
        judge: SelfAgreementPairing(
            judge_id=judge,
            self_agreement=measured_self.get(judge),
            self_agreement_measured=judge in measured_self,
            self_agreement_reason=(
                "" if judge in measured_self else _NO_REPLICATION_MEASUREMENT
            ),
            pairing_required=(
                judge in measured_self
                and measured_self[judge] > MVVP_SELF_AGREEMENT_PAIRING_THRESHOLD
            ),
            position_bias=step2_outcome[judge],
        )
        for judge in judges
    }

    # --- step 6: the compression check (FR-STATS-06) -------------------------
    step6_outcome = _compression_outcome(stats, admissible)

    outcomes: dict[int, Any] = {
        1: step1_outcome,
        2: step2_outcome,
        3: step3_outcome,
        4: step4_outcome,
        5: step5_outcome,
        6: step6_outcome,
    }
    steps = {
        step: MVVPStep(
            step=step,
            requirement=MVVP_STEP_REQUIREMENTS[step],
            outcome=outcomes[step],
            measured_at=measured_at,
            measured_configuration=measured_configuration,
            paired_results=step5_outcome if step == 5 else {},
        )
        for step in MVVP_STEP_REQUIREMENTS
    }
    result_id = _mvvp_result_id(assignment_type, measured_configuration)
    return MVVPReport(
        assignment_type=assignment_type,
        steps=steps,
        result_id=result_id,
        measured_configuration=measured_configuration,
        contributing_results=(result_id,),
        measured_at=measured_at,
        judges_in_scope=judges,
    )


def latest_mvvp(
    assignment_type: str | None = None,
    *,
    configuration: Mapping[str, Any] | None = None,
    measured_self_agreement: Mapping[str, Any] | None = None,
    measured_position_bias: Mapping[str, Any] | None = None,
    backend_claims_deterministic_at_temperature_zero: bool | None = None,
) -> MVVPReport:
    """The current MVVP result for a configuration (CT-STATS-08).

    Measures fresh on every call. There is no durable MVVP result to serve —
    this module writes nothing (`CT-STATS-15`) — so no prior result can be
    reused, shown or merged across a change: the newest result is the one
    just measured, under the configuration asked for, and ``result_id``
    digests that configuration's content, so a changed dimension is a
    different result by construction (`FR-STATS-19`, HLD R30) and a stale one
    is provably outside ``contributing_results`` (`TC-STATS-C08`)."""
    return run_mvvp(
        None,
        assignment_type,
        configuration=configuration,
        measured_self_agreement=measured_self_agreement,
        measured_position_bias=measured_position_bias,
        backend_claims_deterministic_at_temperature_zero=(
            backend_claims_deterministic_at_temperature_zero
        ),
    )
