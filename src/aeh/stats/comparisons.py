"""The comparisons: compression, surface proxies, routing-policy validity, drift, alerts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typing import Any, Mapping, Sequence

from aeh.pkg import NoValidationData

from .settings import (
    BLIND_SAMPLE_SKIPPED_ALERT,
    _blind_skip_alert_after,
    _DRIFT_ADVISORY_STATEMENT,
    DRIFT_SAMPLE_RANGE,
    _drift_tolerance,
    ROUTING_POLICY_ARM_SOURCES,
    ROUTING_POLICY_ARMS,
    ROUTING_POLICY_DISCRIMINATING_VERDICT,
    ROUTING_POLICY_FAILING_VERDICT,
    _ROUTING_POLICY_INTERPRETATION,
    ROUTING_POLICY_NO_DATA_VERDICT,
    _routing_policy_tolerance,
    _subgroup_analysis_enabled,
    SURFACE_FEATURES,
    SURFACE_PROXY_ALERT,
    _surface_proxy_threshold,
)
from .admissibility import _system_side
from .agreement import _band_ordinals
from .mvvp import _band_entropy, _CO_COMPRESSION_LIMITATION, _interior_rate
from .records import (
    BandShape,
    CompressionReport,
    DriftReport,
    ProxyReport,
    RoutingArm,
    RoutingPolicyReport,
    StatsAlert,
)

if TYPE_CHECKING:
    from .service import ValidationStats


def _require_str_or_none(member: str, **named: Any) -> None:
    """Check that a population key is a string or None; anything else is a programming error and
    raises (CT-STATS-16)."""
    for name, value in named.items():
        if value is not None and not isinstance(value, str):
            raise TypeError(
                f"{member}() got {name}={value!r}; a population key is a "
                "string or None, and anything else is a programming error "
                "(CT-STATS-16 raises on programming errors)"
            )


def _refuse_foreign_cohort(
    self: "ValidationStats", cohort_id: str | None, member: str
) -> None:
    """Refuse a report that names a cohort this instance does not hold.

    The constructor pair binds the instance to one population — ``open_stats``
    reads one cohort's rows when it is given a cohort — and a report naming a
    cohort it was not computed over is the mislabeled claim `CT-STATS-02`'s
    discipline exists to prevent, applied to the report's own label. Where the
    instance never declared a cohort (``build_stats``, or an unbound
    ``open_stats`` over every cohort), nothing is checked and the report
    carries the cohort the caller named."""
    held = getattr(self, "_cohort_id", None)
    if cohort_id is not None and held is not None and cohort_id != held:
        raise ValueError(
            f"{member}() was asked for cohort {cohort_id!r} but the instance "
            f"holds {held!r}'s labels; a report naming a cohort it was not "
            "computed over is the mislabeled claim this module exists to "
            "prevent (CT-STATS-02's discipline, on the report's own label)"
        )


def _paired_sides(population: Sequence[Any]) -> list[tuple[Any, Any]]:
    """Both bands of each label pair, leaving out labels that have only one side.

    The same extraction ``agreement`` makes: the label's system side
    (``_system_side``) and its teacher side, kept only where both exist. A
    blind label whose system column is NULL stays in the population counts and
    drops out of the paired statistic — borrowing the teacher's side would
    manufacture the very comparison the label cannot support."""
    return [
        (system, teacher)
        for system, teacher in (
            (_system_side(label), getattr(label, "teacher_band", None))
            for label in population
        )
        if system is not None and teacher is not None
    ]


def _flagged_features(
    correlations: Mapping[str, float], threshold: float
) -> tuple[str, ...]:
    """The surface features whose correlation `|r|` reaches the flag threshold, in a stable order.

    Sorted so the alert's detail line and the report's flags are deterministic
    — the same measured correlations produce the same output on two runs,
    which is what makes the alert comparable across administrations."""
    return tuple(
        sorted(
            feature
            for feature, value in correlations.items()
            if abs(value) >= threshold
        )
    )


def _distribution_counts(values: Sequence[Any]) -> dict[Any, int]:
    counts: dict[Any, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _total_variation(
    first: Mapping[Any, int], second: Mapping[Any, int]
) -> float:
    """The total variation distance between two band distributions.

    The drift check's per-criterion measure: half the L1 distance between the
    two normalized distributions, in ``[0, 1]`` — 0.0 for identical shapes and
    1.0 for disjoint support. Chosen over an entropy difference because the
    baseline and the sample can disagree in either direction, and a signed
    measure would bury the direction the reader needs next to the magnitude.
    """
    total_first = sum(first.values())
    total_second = sum(second.values())
    keys = set(first) | set(second)
    return 0.5 * sum(
        abs(first.get(key, 0) / total_first - second.get(key, 0) / total_second)
        for key in keys
    )


def compression_check(
    self: "ValidationStats",
    cohort_id: str | None = None,
    criterion_id: str | None = None,
) -> CompressionReport:
    """Check one criterion for compression (FR-STATS-06, CT-STATS-10): compare the shape of the
    panel's bands with the blind labels' bands, by band entropy and interior rate. Returns the
    finding (`panel_narrower`) with the co-compression caveat.

    The population is the admissible one, always — the filter exists once and
    this call routes through it — narrowed to ``criterion_id`` where one is
    named. "Gold" is the **teacher side** of the blind labels: comparing the
    panel against operational teacher bands would compare it against teachers
    who saw its own output, and the finding would disappear. Both shapes are
    measured against the same band count — the larger of the criterion's
    declared count and the inferred one, exactly as the MVVP's step-6 outcome
    takes it — so ``panel_narrower`` is a fair comparison and the interior
    rates are computed on the same scale.

    Raises on programming errors only (`CT-STATS-16`): a malformed argument
    propagates, and a cohort the instance does not hold is refused. An empty
    paired population is a value — a report whose shapes carry no distribution
    and whose limitation is still stated."""
    _require_str_or_none(
        "compression_check", cohort_id=cohort_id, criterion_id=criterion_id
    )
    _refuse_foreign_cohort(self, cohort_id, "compression_check")
    admissible = self.admissible_labels()
    population = [
        label
        for label in admissible
        if criterion_id is None or getattr(label, "criterion_id", "") == criterion_id
    ]
    excluded_count = len(self._labels) - len(admissible)
    pairs = _paired_sides(population)
    if not pairs:
        empty = BandShape(band_entropy=None, interior_rate=None, n=0)
        return CompressionReport(
            cohort_id=cohort_id,
            criterion_id=criterion_id,
            gold=empty,
            panel=empty,
            panel_narrower=None,
            stated_limitation=_CO_COMPRESSION_LIMITATION,
            n=0,
            excluded_count=excluded_count,
        )
    ordinals, inferred_band_count = _band_ordinals(pairs)
    if criterion_id is None:
        declared_band_count = max(self._band_counts.values(), default=0)
    else:
        declared_band_count = self._band_counts.get(criterion_id) or 0
    band_count = max(declared_band_count, inferred_band_count)
    panel_bands = [system for system, _ in ordinals]
    gold_bands = [teacher for _, teacher in ordinals]
    gold_entropy = _band_entropy(gold_bands)
    panel_entropy = _band_entropy(panel_bands)
    panel_narrower = (
        panel_entropy < gold_entropy
        if panel_entropy is not None and gold_entropy is not None
        else None
    )
    return CompressionReport(
        cohort_id=cohort_id,
        criterion_id=criterion_id,
        gold=BandShape(
            band_entropy=gold_entropy,
            interior_rate=_interior_rate(gold_bands, band_count),
            n=len(gold_bands),
        ),
        panel=BandShape(
            band_entropy=panel_entropy,
            interior_rate=_interior_rate(panel_bands, band_count),
            n=len(panel_bands),
        ),
        panel_narrower=panel_narrower,
        stated_limitation=_CO_COMPRESSION_LIMITATION,
        n=len(pairs),
        excluded_count=excluded_count,
    )


def surface_proxies(
    self: "ValidationStats",
    cohort_id: str | None = None,
    criterion_id: str | None = None,
    *,
    subgroup: str | None = None,
) -> ProxyReport:
    """The surface-proxy report for one criterion (FR-STATS-07): the caller's measured correlations
    between scores and surface features that should be irrelevant (such as length), flagging any
    feature whose `|r|` reaches the threshold.

    The regression's inputs are the pipeline's score rows, which this module
    does not hold — the correlations arrive through the declared
    ``surface_correlations`` channel exactly as #116's MVVP declares its
    measured channels, and what this module owns is the interpretation: the
    threshold decision, the per-criterion payload
    (``surface_proxy_flags``, the shape the validation record stores), and the
    alert (`CT-STATS-19`) that fires on a flag. ``captured_features``
    discloses what the channel measured — a feature not captured is absent
    from the disclosure, not measured at zero.

    The subgroup gate (`NFR-STATS-05`, `CT-STATS-18`): the breakdown runs only
    where the knob says the analysis is locally lawful **and** the caller asks
    for it by name; a request while the gate is closed is a refusal, not an
    empty result — a knob nothing reads is a comment, and an empty result
    would read as "no subgroup differences found".

    Raises on programming errors and on the closed-gate refusal; an empty
    population or an empty channel returns the empty report as a value
    (`CT-STATS-16`)."""
    _require_str_or_none(
        "surface_proxies",
        cohort_id=cohort_id,
        criterion_id=criterion_id,
        subgroup=subgroup,
    )
    _refuse_foreign_cohort(self, cohort_id, "surface_proxies")
    if subgroup:
        if not _subgroup_analysis_enabled():
            raise ValueError(
                "surface_proxies() refuses the subgroup breakdown: NFR-STATS-05 "
                "gates subgroup analysis on local lawfulness and "
                "STATS_SUBGROUP_ANALYSIS_ENABLED is false — a subgroup analysis "
                "running by default is a regulatory exposure nobody chose. "
                "Enable the knob where the analysis is locally lawful, then ask "
                "again."
            )
    correlations = self._surface_correlations
    if criterion_id is not None:
        correlations = {
            name: feats
            for name, feats in correlations.items()
            if name == criterion_id
        }
    threshold = _surface_proxy_threshold()
    flags = {
        name: {
            feature: value
            for feature, value in feats.items()
            if abs(value) >= threshold
        }
        for name, feats in correlations.items()
    }
    flags = {name: flagged for name, flagged in flags.items() if flagged}
    admissible = self.admissible_labels()
    population = [
        label
        for label in admissible
        if criterion_id is None or getattr(label, "criterion_id", "") == criterion_id
    ]
    captured = tuple(
        feature
        for feature in SURFACE_FEATURES
        if any(feature in feats for feats in correlations.values())
    )
    subgroup_breakdowns = None
    if subgroup:
        scoped = self._subgroup_correlations
        if criterion_id is not None:
            scoped = {
                name: feats
                for name, feats in scoped.items()
                if name == criterion_id
            }
        subgroup_breakdowns = {name: dict(feats) for name, feats in scoped.items()}
    return ProxyReport(
        cohort_id=cohort_id,
        criterion_id=criterion_id,
        correlations={name: dict(feats) for name, feats in correlations.items()},
        surface_proxy_flags=flags,
        captured_features=captured,
        n=len(population),
        subgroup_breakdowns=subgroup_breakdowns,
    )


def routing_policy_validity(
    self: "ValidationStats",
    cohort_id: str | None = None,
) -> RoutingPolicyReport:
    """Whether the routing policy works for one cohort (FR-STATS-08, CT-STATS-11): compare the
    error rate among escalated-and-reviewed judgments with the error rate among auto-accepted ones.
    Both groups are admissible labels, split by their `routing` column through
    `ROUTING_POLICY_ARM_SOURCES`: `reviewed` for escalated-and-reviewed, `auto` for auto-accepted.

    Both arms read the same filter's population — an operational label on
    either side would compare the review with itself, and the escalated arm's
    error rate would go to zero precisely where the policy does the most work.
    The error is the judgment's band disagreeing with the blind teacher's,
    over the labels that carry both sides of the pair; ``n`` counts the arm's
    whole admissible population, the population the claim is about.

    The verdict's reading is the clause's, and it travels in the report:
    similar rates in both arms are ``failing`` — the policy escalates the
    wrong judgments, a finding about `M-AGG`'s declared constants, and never
    ``uninformative``; the escalated arm above the auto-accepted one by at
    least the tolerance is ``discriminating`` (the HLD's 8%-versus-1% gap);
    the inverted direction is also ``failing``, because a policy routing the
    wrong way is worse than one routing nothing. Arms without a computable
    rate return ``no_data`` as a value (`CT-STATS-16`), never an exception.

    Raises on programming errors only."""
    _require_str_or_none("routing_policy_validity", cohort_id=cohort_id)
    _refuse_foreign_cohort(self, cohort_id, "routing_policy_validity")
    admissible = self.admissible_labels()
    tolerance = _routing_policy_tolerance()
    arms: dict[str, RoutingArm] = {}
    for arm in ROUTING_POLICY_ARMS:
        sources = ROUTING_POLICY_ARM_SOURCES[arm]
        population = [
            label
            for label in admissible
            if getattr(label, "routing", None) in sources
        ]
        paired = _paired_sides(population)
        errors = sum(1 for system, teacher in paired if system != teacher)
        arms[arm] = RoutingArm(
            n=len(population),
            paired=len(paired),
            errors=errors,
            error_rate=errors / len(paired) if paired else None,
        )
    rates = [arms[arm].error_rate for arm in ROUTING_POLICY_ARMS]
    if any(rate is None for rate in rates):
        verdict = ROUTING_POLICY_NO_DATA_VERDICT
    else:
        escalated_rate, auto_rate = rates
        if abs(escalated_rate - auto_rate) < tolerance:
            verdict = ROUTING_POLICY_FAILING_VERDICT
        elif escalated_rate > auto_rate:
            verdict = ROUTING_POLICY_DISCRIMINATING_VERDICT
        else:
            # Inverted: the auto-accepted arm shows the larger rate, so the
            # policy is routing the wrong way — worse than similar, and
            # failing for the same reason.
            verdict = ROUTING_POLICY_FAILING_VERDICT
    return RoutingPolicyReport(
        cohort_id=cohort_id,
        verdict=verdict,
        label_population=arms,
        tolerance=tolerance,
        stated_interpretation=_ROUTING_POLICY_INTERPRETATION,
        n=len(admissible),
    )


def drift_check(
    self: "ValidationStats | None" = None,
    package_version: str | None = None,
    sample: Sequence[Any] = (),
    *,
    baseline: Mapping[str, Sequence[Any]] | None = None,
    current: Mapping[str, Sequence[Any]] | None = None,
) -> "DriftReport | NoValidationData":
    """The advisory drift check for one package (FR-STATS-09, CT-STATS-12).

    More detail: `docs/code-notes/stats.md`, section `comparisons.py: drift_check`.
    """
    if package_version is not None and not isinstance(package_version, str):
        raise TypeError(
            f"drift_check() got package_version={package_version!r}; a package "
            "version is a string or None, and anything else is a programming "
            "error (CT-STATS-16 raises on programming errors)"
        )
    if isinstance(sample, (str, bytes)):
        raise TypeError(
            "drift_check() got a string where a submission sample belongs; a "
            "sample is a sequence of submission identities, and anything else "
            "is a programming error (CT-STATS-16 raises on programming errors)"
        )
    submissions = tuple(sample)
    available = len(submissions)
    low, high = DRIFT_SAMPLE_RANGE
    if available < low:
        # Below the floor there is no sample of the kind the check consumes —
        # the judged submissions the blind flow produces — which is the
        # no-data condition the absence type carries, with what *was* given as
        # context. A verdict on too small a sample is the substitute figure
        # CT-STATS-16 forbids.
        return NoValidationData(reason="no_blind_labels", n=available)
    size = min(available, high)
    if size == available:
        chosen = submissions
    else:
        # The even spread: strictly increasing indices scaled across the
        # sample's full length, so the first and the last submission are both
        # represented — a 31-submission administration is sampled end to end,
        # not by its first thirty. (Scaling by ``(available - 1) / (size -
        # 1)`` rather than ``available / size`` is what reaches the tail: the
        # latter's largest index never gets past the second-to-last element,
        # and at the minimal overflow it is exactly the sample's head.)
        chosen = tuple(
            submissions[index * (available - 1) // (size - 1)]
            for index in range(size)
        )
    evaluation_modes = getattr(self, "_evaluation_modes", {}) or {}
    declared_deterministic = {
        criterion
        for criterion, mode in evaluation_modes.items()
        if mode == "deterministic"
    }
    judged_declared = {
        criterion for criterion, mode in evaluation_modes.items() if mode == "judged"
    }
    if current is not None:
        sample_source = "declared_current_channel"
        current_counts = {
            criterion: _distribution_counts(tuple(values))
            for criterion, values in current.items()
        }
    elif self is not None:
        sample_source = "constructor_population"
        buckets: dict[str, list[Any]] = {}
        for label in self.admissible_labels():
            band = _system_side(label)
            if band is not None:
                buckets.setdefault(
                    getattr(label, "criterion_id", "") or "", []
                ).append(band)
        current_counts = {
            criterion: _distribution_counts(values)
            for criterion, values in buckets.items()
        }
    else:
        sample_source = "none"
        current_counts = {}
    covered = sorted(
        (set(current_counts) | judged_declared) - declared_deterministic
    )
    baseline_counts = {
        criterion: _distribution_counts(tuple(values))
        for criterion, values in (baseline or {}).items()
    }
    distributions = {
        criterion: current_counts[criterion]
        for criterion in covered
        if criterion in current_counts
    }
    tolerance = _drift_tolerance()
    distances = {
        criterion: _total_variation(
            distributions[criterion], baseline_counts[criterion]
        )
        for criterion in covered
        if criterion in distributions
        and criterion in baseline_counts
        and distributions[criterion]
        and baseline_counts[criterion]
    }
    drifted = tuple(
        sorted(
            criterion
            for criterion, distance in distances.items()
            if distance >= tolerance
        )
    )
    severity = max(distances.values()) if distances else None
    return DriftReport(
        package_version=package_version,
        sample_size=size,
        sample_ids=chosen,
        sample_source=sample_source,
        criteria_covered=tuple(covered),
        distributions=distributions,
        baseline_distributions=baseline_counts or None,
        distances=distances,
        drifted=drifted,
        severity=severity,
        advisory=True,
        binding_threshold=None,
        why_not_binding=_DRIFT_ADVISORY_STATEMENT,
    )


def alerts(self: "ValidationStats") -> tuple["StatsAlert", ...]:
    """The contract alerts this instance's inputs trigger (CT-STATS-19).

    The surface-proxy alert is the only thing that catches a criterion with excellent agreement but
    no validity: a correlation with length or OCR quality means the criterion measures something
    else, whatever its agreement says. The blind-sample alert fires when
    `STATS_BLIND_SKIP_ALERT_AFTER` administrations in a row skipped their blind sample: grading is
    going on without evidence.

    Deterministic: criteria and features in sorted order, administrations in
    declared order, one alert per maximal consecutive skip run that reaches
    the threshold — so the same declared channels produce the same alerts on
    every call."""
    threshold = _surface_proxy_threshold()
    fired: list["StatsAlert"] = []
    for criterion in sorted(self._surface_correlations):
        correlations = self._surface_correlations[criterion]
        flagged = _flagged_features(correlations, threshold)
        if flagged:
            detail = ", ".join(
                f"{feature} r={correlations[feature]:+.2f}" for feature in flagged
            )
            fired.append(
                StatsAlert(
                    name=SURFACE_PROXY_ALERT,
                    detail=f"{criterion}: {detail}",
                )
            )
    fired.extend(_blind_skip_alerts(self._administrations))
    return tuple(fired)


def _administration_fields(administration: Any) -> tuple[str | None, bool]:
    """One administration's `(cohort_id, blind_sample)`, from a mapping or an object. An
    administration that states nothing about its blind sample did not skip it."""
    if isinstance(administration, Mapping):
        cohort_id = administration.get("cohort_id")
        blind_sample = administration.get("blind_sample", True)
    else:
        cohort_id = getattr(administration, "cohort_id", None)
        blind_sample = getattr(administration, "blind_sample", True)
    return cohort_id, bool(blind_sample)


def _blind_skip_alerts(
    administrations: Sequence[Any],
) -> list["StatsAlert"]:
    """The `blind_sample_skipped_consecutive_administrations` alerts, in the declared order: one
    per unbroken run of skipped administrations that reaches the threshold. A run of three alerts
    once, not twice."""
    threshold = _blind_skip_alert_after()
    alerts: list["StatsAlert"] = []
    run: list[str | None] = []
    for administration in administrations:
        cohort_id, blind_sample = _administration_fields(administration)
        if blind_sample:
            if len(run) >= threshold:
                alerts.append(_blind_skip_alert(run))
            run = []
            continue
        run.append(cohort_id)
    if len(run) >= threshold:
        alerts.append(_blind_skip_alert(run))
    return alerts


def _blind_skip_alert(run: Sequence[str | None]) -> "StatsAlert":
    named = ", ".join(str(cohort_id) for cohort_id in run if cohort_id is not None)
    suffix = f": {named}" if named else ""
    return StatsAlert(
        name=BLIND_SAMPLE_SKIPPED_ALERT,
        detail=(
            f"{len(run)} consecutive administrations without a blind sample"
            f"{suffix}"
        ),
    )
