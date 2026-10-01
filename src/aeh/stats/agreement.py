"""The chance-corrected agreement figure: kappa, weighted kappa, ordinal alpha and its interval."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dataclasses import dataclass
from typing import Any, Sequence

from aeh.pkg import NoValidationData

from .settings import _INTERVAL_Z_95, _WORST_CASE_VARIANCE
from .admissibility import _label_backend, _system_side

if TYPE_CHECKING:
    from .service import ValidationStats


# --- the two return types (§3.16's Interfaces block) ------------------------------------------------


@dataclass(frozen=True)
class AgreementFigure:
    """One chance-corrected agreement figure together with its scope (CT-STATS-02, NFR-STATS-02):
    the statistic, `n`, the scoring model, `population_scope_id`, `backend_profile` and
    `panel_build_ref`. A figure cannot be built without all of them.

    Field order is §3.16's declaration order; ``degenerate_band_shape`` is
    this suite's declared ninth field (`CT-STATS-21`'s disclosure). The three
    statistics are ``| None`` by the design's own signatures — a figure whose
    every coefficient is 0/0 still exists, and discloses what it sits in
    through alpha's exact 1.0 and this flag rather than a number a reader
    would take as a finding.

    The disclosures a consumer holds *beside* the statistic — ``excluded_
    count``, ``interval_low``, ``interval_high``, ``input_fields`` — are
    instance attributes attached after construction, deliberately **not**
    dataclass fields: `TC-STATS-C02` pins the declared field set to the
    design's nine, and a tenth field would be drift from §3.16. Disclosure
    that is not a field is how the two clauses hold together.
    """

    kappa: float | None
    qwk: float | None
    ordinal_alpha: float | None
    n: int
    scoring_model: str
    population_scope_id: str | None
    backend_profile: str | None
    panel_build_ref: str | None
    #: `CT-STATS-21`'s disclosure: a two-band criterion's alpha = 1 is a
    #: construction artifact, and the figure says which shape it measured.
    degenerate_band_shape: bool

    @property
    def computed_over(self) -> str:
        """What the figure is computed over: bands, never points (CT-REVIEW-07)."""
        return "band"


# --- the statistics (the design fixes the names; the shapes are disclosed) -------------------------
#
# The helpers carry deliberately neutral names and are called from exactly one
# place — the ``agreement`` implementation below — which is what keeps the
# figure's construction in one function routed through the single filter
# (`NFR-STATS-04`).


def _band_ordinals(pairs: Sequence[tuple[Any, Any]]) -> tuple[list[tuple[int, int]], int]:
    """Both sides of each label pair mapped onto one ordinal scale, and the number of bands `K`.

    Integer bands map to ``int(v) − 1``; any other shape maps to its rank in
    the sorted set of observed values, which keeps ``"B1".."B4"`` in suffix
    order. ``K`` is the largest observed ordinal plus one — the
    criterion-free inference `aeh.agg`'s ordinal alpha makes when no table
    carries the count; the declared count, when the caller has one, is taken
    alongside it by the caller."""
    all_values = [value for pair in pairs for value in pair]
    all_integers = all(
        isinstance(value, int) and not isinstance(value, bool) for value in all_values
    )
    if all_integers:
        mapped = [(int(a) - 1, int(b) - 1) for a, b in pairs]
    else:
        ranks = {
            value: index
            for index, value in enumerate(sorted({str(value) for value in all_values}))
        }
        mapped = [(ranks[str(a)], ranks[str(b)]) for a, b in pairs]
    largest = max((value for pair in mapped for value in pair), default=-1)
    return mapped, largest + 1


def _observed_and_expected(pairs: Sequence[tuple[int, int]]) -> tuple[float, float]:
    """Observed agreement `po` and chance agreement `pe` over the pairs.

    ``pe`` sums each category's two marginal frequencies over the union of
    the categories either side used — a category the system never used still
    contributes its teacher-side marginal against a zero system side, which
    is the honest independence expectation."""
    total = len(pairs)
    system_counts: dict[int, int] = {}
    teacher_counts: dict[int, int] = {}
    agreeing = 0
    for system_ordinal, teacher_ordinal in pairs:
        agreeing += system_ordinal == teacher_ordinal
        system_counts[system_ordinal] = system_counts.get(system_ordinal, 0) + 1
        teacher_counts[teacher_ordinal] = teacher_counts.get(teacher_ordinal, 0) + 1
    po = agreeing / total
    pe = sum(
        (system_counts.get(category, 0) / total)
        * (teacher_counts.get(category, 0) / total)
        for category in set(system_counts) | set(teacher_counts)
    )
    return po, pe


def _chance_corrected_coefficient(po: float, pe: float) -> float | None:
    """Cohen's kappa, `(po - pe) / (1 - pe)`; undefined only when `pe = 1`.

    pe = 1 is the single-category population — every chance-corrected
    coefficient is 0/0 there, and the figure carries the unanimity it sits in
    through alpha's exact 1.0 and the degeneracy disclosure rather than a
    number a reader would take as a finding (`NFR-STATS-01` names unanimity a
    degenerate case; `TC-STATS-C02`'s note records why the sweep does not
    demand one from it)."""
    if pe == 1:
        return None
    return (po - pe) / (1 - pe)


def _weighted_coefficient(
    pairs: Sequence[tuple[int, int]], band_count: int
) -> float | None:
    """The quadratic-weighted kappa over the ordinal pairs; undefined when there are fewer than two
    bands or the denominator is zero.

    The weight matrix is the plan's quadratic form, ``w = (i − j)²/(K − 1)²``,
    over the observed joint against the independence expectation — the same
    matrix `aeh.agg`'s convention declares for the panel-vs-teacher pair. All
    mass on the diagonal drives both sums to zero, where the coefficient is
    0/0 and ``None`` is the honest answer."""
    if band_count < 2:
        return None
    total = len(pairs)
    system_counts = [0] * band_count
    teacher_counts = [0] * band_count
    joint: dict[tuple[int, int], int] = {}
    for system_ordinal, teacher_ordinal in pairs:
        system_counts[system_ordinal] += 1
        teacher_counts[teacher_ordinal] += 1
        joint[(system_ordinal, teacher_ordinal)] = (
            joint.get((system_ordinal, teacher_ordinal), 0) + 1
        )
    numerator = 0.0
    denominator = 0.0
    for a in range(band_count):
        for b in range(band_count):
            weight = (a - b) ** 2 / (band_count - 1) ** 2
            numerator += joint.get((a, b), 0) / total * weight
            denominator += (
                (system_counts[a] / total) * (teacher_counts[b] / total) * weight
            )
    if denominator == 0:
        return None
    return 1 - numerator / denominator


def _distance_coefficient(
    pairs: Sequence[tuple[int, int]], band_count: int
) -> float | None:
    """Ordinal Krippendorff's alpha for two raters, following `aeh.agg`'s convention: `alpha = 1 -
    D_o/D_e`. Complete agreement gives exactly 1.0 (checked before the band count); fewer than two
    bands, or `D_e` of zero, gives None. `D_o` is the mean distance between the panel's band and
    the teacher's."""
    if not pairs:
        return None
    if len({ordinal for pair in pairs for ordinal in pair}) == 1:
        return 1.0  # unanimous, exact — before the band-count test, as #91's alpha does
    if band_count < 2:
        return None
    scale = band_count - 1
    observed = (
        sum(
            abs(system_ordinal - teacher_ordinal)
            for system_ordinal, teacher_ordinal in pairs
        )
        / len(pairs)
        / scale
    )
    expected = (
        sum(abs(a - b) for a in range(band_count) for b in range(band_count) if a != b)
        / scale
        / (band_count * (band_count - 1))
    )
    if expected == 0:
        return None
    return 1 - observed / expected


def _corrected_statistics(
    pairs: Sequence[tuple[int, int]], band_count: int
) -> tuple[float | None, float | None, float | None, float, float]:
    """The three chance-corrected statistics over the paired labels.

    Kappa, QWK and ordinal alpha (`FR-STATS-02`): at least one of them
    carries a value on every figure this module emits — a figure with all
    three ``None`` is a raw percent agreement wearing the dataclass, the
    failure `FR-STATS-02`'s second half governs. ``po`` and ``pe`` come back
    beside them because the interval needs the same marginals."""
    po, pe = _observed_and_expected(pairs)
    kappa = _chance_corrected_coefficient(po, pe)
    qwk = _weighted_coefficient(pairs, band_count)
    alpha = _distance_coefficient(pairs, band_count)
    return kappa, qwk, alpha, po, pe


def _achievable_precision(
    n: int, po: float | None, pe: float | None
) -> tuple[float | None, float | None]:
    """The confidence interval the sample size supports, centred on the figure.

    ``h = 1.96 · sqrt(po(1 − po)/n) / (1 − pe)`` centred on the kappa the
    marginals give — the Fleiss asymptotic standard error of kappa at
    Z = 1.96 — and the worst-case band ``±1.96 · sqrt(0.25/n)`` centred on
    zero where no coefficient is computable (unpaired labels, or a population
    where ``pe = 1`` makes every chance-corrected coefficient 0/0). The
    width, ``2h``, is strictly decreasing in ``n`` (`TC-REVIEW-C17`'s
    differential): more blind labels buy a narrower claim, and a system where
    they do not is not reporting an interval that depends on its evidence. It
    is achievable precision, not a promise about the system (`CT-STATS-20`)."""
    if n <= 0:
        return (None, None)
    if po is None or pe is None or pe >= 1:
        half_width = _INTERVAL_Z_95 * (_WORST_CASE_VARIANCE / n) ** 0.5
        return (-half_width, half_width)
    half_width = _INTERVAL_Z_95 * (po * (1 - po) / n) ** 0.5 / (1 - pe)
    centre = _chance_corrected_coefficient(po, pe)
    assert centre is not None, "pe < 1 always yields a defined kappa"
    return (centre - half_width, centre + half_width)


# --- the agreement implementation -------------------------------------------------------------------


def agreement(
    self: "ValidationStats",
    package_version: str | None = None,
    criterion_id: str | None = None,
    scope: str | None = None,
    backend_profile: str | None = None,
    panel_build_ref: str | None = None,
    scoring_model: str | None = None,
) -> "AgreementFigure | NoValidationData":
    """The agreement figure for one criterion, population, backend profile, panel build and scoring
    model (FR-STATS-02, FR-STATS-03), or a value saying which kind of data is missing
    (FR-STATS-04).

    The population is the admissible one, always (`FR-STATS-01`): the filter
    exists once (`NFR-STATS-04`) and this call routes through it. A
    ``criterion_id`` narrows that population to the criterion's labels — a
    validity claim is per-criterion, and a figure naming a criterion it was
    not computed over is the claim `CT-STATS-04` keeps unrepresentable. Every
    figure carries its four scope dimensions in the same value
    (`TC-STATS-C04`), and ``scope=None`` is an unscoped request, legal here
    and disclosed on the figure as ``None`` — the caller asked for an
    unscoped population and the figure says so rather than stamping one.

    Defined at module level and bound into ``ValidationStats`` below, so the
    surface ``require(STATS_MODULE, "agreement")`` names and the method the
    instance carries are the same function.

    Raises on programming errors only (`CT-STATS-16`): a malformed argument
    propagates. Insufficient data returns the absence value."""
    for name, value in (
        ("criterion_id", criterion_id),
        ("scope", scope),
        ("backend_profile", backend_profile),
        ("panel_build_ref", panel_build_ref),
        ("package_version", package_version),
    ):
        if value is not None and not isinstance(value, str):
            raise TypeError(
                f"agreement() got {name}={value!r}; a population key is a "
                "string or None, and anything else is a programming error "
                "(CT-STATS-16 raises on programming errors)"
            )
    if scoring_model is None:
        # The criterion's declared model is the figure's default — the package
        # classifies the criterion (CT-SETUP-05), and the figure carries what
        # the package declared rather than a consumer's guess.
        scoring_model = self._scoring_models.get(criterion_id or "")

    if self._population_scopes and scope is not None and (
        scope not in self._population_scopes
    ):
        return NoValidationData(reason="no_data_for_population")
    if self._backend_profiles and backend_profile is not None and (
        backend_profile not in self._backend_profiles
    ):
        return NoValidationData(reason="no_data_for_backend")

    admissible = self.admissible_labels()
    excluded_count = len(self._labels) - len(admissible)
    population = [
        label
        for label in admissible
        if criterion_id is None or getattr(label, "criterion_id", "") == criterion_id
    ]
    if backend_profile is not None:
        # CT-STATS-04 (#514): a figure stamped with a backend is computed over that
        # backend's labels only. A label recording no backend is not attributable: it is
        # left out and reported by `exclusion_reasons(backend_profile=...)` as
        # `backend_not_recorded`. `excluded_count` stays the INADMISSIBLE count
        # (TC-STATS-05), and another backend's label is simply keyed out.
        population = [label for label in population
                      if _label_backend(label) == backend_profile]
    if not population:
        return NoValidationData(
            reason="no_blind_labels", n=0, excluded_count=excluded_count
        )

    paired = [
        (system, teacher)
        for system, teacher in (
            (_system_side(label), getattr(label, "teacher_band", None))
            for label in population
        )
        if system is not None and teacher is not None
    ]
    n = len(population)
    if len(paired) < 2:
        # No chance-corrected coefficient is computable over fewer than two
        # paired valuations; the answer is the absence value, carrying what
        # *was* measured (`TC-STATS-C01`'s rung-2 pin reads ``n`` off it;
        # `TC-REVIEW-C17` reads the interval off it).
        low, high = _achievable_precision(n, None, None)
        return NoValidationData(
            reason="no_blind_labels",
            n=n,
            excluded_count=excluded_count,
            interval_low=low,
            interval_high=high,
        )

    declared = self._band_counts.get(criterion_id or "")
    ordinals, inferred_band_count = _band_ordinals(paired)
    band_count = max(declared or 0, inferred_band_count)
    kappa, qwk, alpha, po, pe = _corrected_statistics(ordinals, band_count)
    interval_low, interval_high = _achievable_precision(n, po, pe)

    figure = AgreementFigure(
        kappa=kappa,
        qwk=qwk,
        ordinal_alpha=alpha,
        n=n,
        scoring_model=scoring_model,
        population_scope_id=scope,
        backend_profile=backend_profile,
        panel_build_ref=panel_build_ref,
        degenerate_band_shape=band_count == 2,
    )
    object.__setattr__(figure, "excluded_count", excluded_count)
    object.__setattr__(figure, "interval_low", interval_low)
    object.__setattr__(figure, "interval_high", interval_high)
    object.__setattr__(
        figure,
        "input_fields",
        (
            ("system_band", "teacher_band")
            if hasattr(population[0], "system_band")
            else ("band", "teacher_band")
        ),
    )
    return figure
