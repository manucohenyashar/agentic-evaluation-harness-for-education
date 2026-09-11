"""M-STATS — the admissible-label filter, chance-corrected agreement and scoped
results (§3.16, issue #115).

The module that decides what the system is allowed to *claim*. Every figure
here is a validity claim about one criterion, one population, one backend
profile, one panel build and one scoring model — and the whole design of this
file exists to make the wider claim unrepresentable rather than merely
discouraged (`CT-STATS-02` puts the scope inside the figure's own value;
`TC-STATS-C02` asserts that by construction refusal).

**The single filter (`NFR-STATS-04`).** Admissible to a validity claim means
``label_type = 'blind'`` AND ``evaluation_mode = 'judged'`` (R20/R53), and the
predicate lives exactly once in this source (``_is_admissible``) and is reused
by every path — `NFR-STATS-04`: *"The 'labels admissible to a validity claim'
filter shall exist once in the source and be reused, so R20 and R53 cannot be
violated by a new caller."* ``TC-STATS-C01`` asserts the cardinality of one on
the source, so the third copy is the one that fails the suite, not the next
caller who never learns the rule. The conjunction also reads the visibility
column (`CT-REVIEW-08`'s): a label may carry ``label_type = 'blind'`` and
still have been produced by a teacher who reached the system's output — blind
is a claim about reachability, not a naming convention.

**Chance-corrected agreement (`FR-STATS-02`).** Every figure carries Cohen's
kappa, QWK, or ordinal Krippendorff's alpha — at least one of them carries a
value, never a raw percent agreement alone. Each figure also carries its
sample size in the same value: ``n``, the scoring model,
``population_scope_id``, ``backend_profile`` and ``panel_build_ref`` are
fields of the figure, not footnotes beside it (`FR-STATS-02`, `NFR-STATS-02`).

**Absence is a type (`CT-STATS-03`).** Where there is no figure, the module
returns an explicit ``NoValidationData`` carrying one of three declared
reasons — never a null, never a zero, never a sentinel float. Insufficient
data is a value, not an exception (`CT-STATS-16`): the module raises only on
programming errors, never because there is too little data.

**Atomic and holistic are kept apart (`CT-STATS-04`)** — reported separately,
never merged; no function on this surface offers a figure spanning population,
backend, assignment type, or the narrative-quality dimensions.

**Interpretations this module records** (each is a place the design is silent
and this implementation chose; all are reported on the PR):

* *The figure-vs-absence boundary.* ``agreement`` returns a figure when the
  admissible population holds at least two labels carrying both sides of the
  agreement pair; below that the answer is ``no_blind_labels`` — a first-class
  absence that still carries what *was* measured (``n``, ``excluded_count``,
  and, where a statistic could not be computed, the achievable-precision
  interval) so a reader can tell "one label, no claim" from "never
  administered". The design types ``agreement`` as
  ``AgreementFigure | NoValidationData`` and fixes no boundary; a paired
  population below two is where no chance-corrected statistic is computable at
  all, which is the boundary the contract's own type discipline points at.
* *n is the admissible population, the statistic is computed over the paired
  subset.* ``n`` counts every admissible label (the population the claim is
  about, `CT-REVIEW-08` step 4's non-lossiness); kappa/QWK/alpha are computed
  over the paired subset — labels carrying both sides of the pair. A figure
  whose ``n`` silently equaled its paired count would hide the unpaired labels
  it dropped.
* *The interval is achievable precision, not a confidence interval.* Half-width
  ``h = 1.96 · sqrt(p0(1 − p0)/n) / (1 − pe)`` — the Fleiss asymptotic
  standard error of kappa at Z = 1.96 — centred on kappa when one is
  computable; when no statistic is computable the band is the worst-case
  ``±1.96 · sqrt(0.25/n)`` centred on zero. The width is strictly decreasing
  in ``n`` (`TC-REVIEW-C17`'s differential): more blind labels buy a narrower
  claim, and a system where they do not is not reporting an interval that
  depends on its evidence. It is disclosed as achievable precision — the
  precision the sample size can support — not as a computed confidence
  interval, and carries no verdict about quality (`CT-STATS-20`).
* *Ordinal mapping for declared bands.* Band values that are integers map to
  ``int(v) − 1`` (the plan's 1..K bands are 0-based ordinals); values that are
  not map to their rank in the sorted set of observed values (``"B1".."B4"``
  keeps its suffix order). ``K`` is the larger of the ``band_counts``
  declaration and the largest observed ordinal — the criterion-free inference
  `aeh.agg`'s ordinal alpha makes when no table carries the count.
* *Two-rater alpha and QWK.* Ordinal alpha follows `aeh.agg`'s declared
  convention (``alpha = 1 − D_o/D_e``, unanimous exact 1.0 checked before the
  band-count test) with the panel-vs-teacher population as the two-rater
  ``D_o`` — the mean per-label distance between the two sides. QWK is the
  quadratic-weighted kappa over the same ordinals. Kappa is undefined only
  where chance agreement is 1 (a single category on both sides), where
  ``pe = 1`` makes every chance-corrected coefficient 0/0; the figure still
  exists and discloses the degeneracy it sits in.
* *Rung 2 reads the current cohort's labels only* (`CT-STATS-18`): the
  constructor reads the declared statement with a bound cohort parameter —
  never a join to another cohort or to Tier C — and this module writes
  nothing (`CT-STATS-15`).
* *`STATS_MIN_N_FOR_HEADLINE` is a display-qualifier boundary, not a verdict.*
  Below it a figure renders with an explicit "too few to draw conclusions
  from" qualifier (HLD §11.5's S12 mock); it says nothing about whether the
  figure is good (`NFR-SYS-08`).

The four seams (CLAUDE.md): the constructor pair is the headless driver —
``build_stats``/``open_stats`` return structured values with no console in the
loop; the deterministic transport for every external dependency is `aeh.store`
itself, the deterministic local store this module's reads ride (no egress of
its own); the one environment-sensitive constant this contract lets the module
declare, ``STATS_MIN_N_FOR_HEADLINE``, is pinned by ``TC-STATS-C20`` to the
declared default — the seam it gets is the test tier's own
``HARNESS_STATS_ACCUMULATED_SECONDS`` knob, which gates the cost bound without
a code change; and every figure is stage-level observability by construction —
n, the excluded count, the interval and the degeneracy disclosure travel with
the number, next to it, not in a footnote.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from aeh.store import Statement

__all__ = [
    "AgreementFigure",
    "NoValidationData",
    "SCORING_MODELS",
    "STATS_MIN_N_FOR_HEADLINE",
    "STATS_STATEMENTS",
    "ValidationStats",
    "agreement",
    "build_stats",
    "open_stats",
]

#: A criterion's scoring-model values (`FR-STATS-17`). ``atomic`` and
#: ``atomic_with_gate`` are reported together and ``holistic`` separately —
#: the clause's *"reported separately and no function merges them"*.
SCORING_MODELS: tuple[str, ...] = ("atomic", "atomic_with_gate", "holistic")

#: The display-qualifier boundary from §3.16's Configuration block: below this
#: n a figure renders with an explicit "too few to draw conclusions from"
#: qualifier. It is **not** a quality threshold — a figure below it says the
#: claim is wide, not that the system failed (`CT-STATS-20`'s finding keeps
#: the two apart, and `TC-STATS-C20` pins the declared default).
STATS_MIN_N_FOR_HEADLINE = 30

#: The three declared absence reasons (`CT-STATS-03`). Declared here as data
#: so ``NoValidationData``'s constructor validates against the transcription
#: rather than a convention.
_NO_DATA_REASONS: tuple[str, ...] = (
    "no_blind_labels",
    "no_data_for_population",
    "no_data_for_backend",
)

#: The normal distribution's two-sided 95% critical value. A named constant
#: rather than an inline 1.96 so the interval's provenance is one line.
_INTERVAL_Z_95 = 1.96

#: The worst-case band variance when no statistic is computable: the binomial
#'s maximum variance at p = 0.5, the widest claim an ``n`` can honestly make.
_WORST_CASE_VARIANCE = 0.25


# --- the admissibility filter (NFR-STATS-04) ------------------------------------------------------
#
# The predicate exists exactly once in the source (`NFR-STATS-04`) and is
# reused: ``ValidationStats.admissible_labels()`` applies it and every figure
# routes through that application, so R20 and R53 cannot be violated by a new
# caller — the second figure the clause ("none will be added") exists to
# prevent has no door to enter by.
#
# The predicate is the conjunction the contract states, and it reads the two
# columns that own their own enforcement: ``saw_system_output`` is M-REVIEW's
# (`CT-REVIEW-08`) and ``evaluation_mode`` is `CT-DET-06`'s, which is what
# makes the exclusion enforceable from the data rather than by convention.


def _is_admissible(label: Any) -> bool:
    """Whether one label is admissible to a validity claim.

    Admissible means ``label_type = 'blind'`` **and** ``evaluation_mode =
    'judged'`` (R20/R53) — and the visibility flag rides with them: a label
    may carry ``label_type = 'blind'`` and still have been produced by a
    teacher who reached the system's output, so the flag's **truthfulness**
    is the third condition — a 1 excludes, and a falsy flag admits. No
    shipped producer can hand this predicate a null: every collection path
    writes the column (`CT-REVIEW-08` step 1 pins no default and no null),
    so the flag is decidable on the store rows; on the duck-typed in-memory
    shapes the column predates, an absent attribute reads as the pre-column
    shape and admits, and a ``None`` is falsy like a 0 — the two are
    indistinguishable at this predicate by `CT-REVIEW-08`'s own warning,
    which is why the column's enforcement lives at the producers. This
    function is the filter's single definition; every figure
    this module emits is computed over the population it admits
    (`NFR-STATS-04`), and `TC-STATS-C01` asserts that the definition exists
    exactly once.
    """
    return (
        getattr(label, "label_type", "") == "blind"
        and getattr(label, "evaluation_mode", "") == "judged"
        and not getattr(label, "saw_system_output", 0)
    )


def _system_side(label: Any) -> Any:
    """The label's system-side band, whichever attribute shape carries it.

    The review service's labels name the pair ``system_band``/``teacher_band``
    (`CT-REVIEW-08`); the collection fixtures name the system side ``band``
    with the teacher's band beside it. Both shapes carry the same two facts,
    so the extraction reads the pair whichever way it is spelled, and the
    figure's ``input_fields`` disclosure names the attributes actually read —
    never a points field (`CT-REVIEW-07`).

    A stored label whose ``system_band`` column is NULL (the blind flow's —
    #111) returns ``None``: the pair is genuinely one-sided, and the label
    stays in ``n`` while dropping out of the statistic rather than borrowing
    the teacher's side of the pair, which would manufacture agreement."""
    if hasattr(label, "system_band"):
        return label.system_band
    return getattr(label, "band", None)


# --- the two return types (§3.16's Interfaces block) ------------------------------------------------


@dataclass(frozen=True)
class AgreementFigure:
    """One chance-corrected agreement figure, carrying its scope in the same
    value (`CT-STATS-02`, `NFR-STATS-02`): the statistic and the ``n``,
    the scoring model, ``population_scope_id``, ``backend_profile`` and
    ``panel_build_ref`` it is a claim about are one value, and the dataclass
    refuses to represent a figure without them (`TC-STATS-C02` asserts the
    refusal by construction).

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
        """The column the figure is computed over — bands, never points
        (`CT-REVIEW-07`, `TC-REVIEW-C07`'s disclosure). One value either way:
        the claim is coarse exactly because it is the thing a reader checks at
        a glance."""
        return "band"


class NoValidationData:
    """The absence of validation evidence, as a value (`FR-STATS-04`).

    Not a null, not a zero, not a sentinel float (`CT-STATS-03`): a distinct
    type whose ``reason`` is one of the three declared literals —
    ``no_blind_labels`` (nobody collected blind labels here),
    ``no_data_for_population`` (this population was never administered),
    ``no_data_for_backend`` (this backend was never measured). Returning a
    plausible-looking number instead would be the most damaging possible
    failure in the system, which is why the distinction lives in the type
    system rather than in a convention (`TC-STATS-C03`).

    The value is **not numerically coercible by any route**: ``float()``,
    arithmetic, threshold comparison, percent formatting and multiplication
    each raise, so a package with no evidence cannot advertise ``0.00``
    through a call site that kept working (`CT-STATS-03`'s adversarial
    construction is precisely a ``float`` subclass — this class defines none
    of the dunders those probes reach). A plain object is the whole defence.

    What *was* measured travels with the absence as context attributes —
    ``n``, ``excluded_count``, and the interval where one applies — so a run
    whose labels are all operational reports "20 labels excluded, no figure"
    rather than a bare message (`CT-REVIEW-08` step 4's non-silent exclusion;
    `TC-STATS-C01`'s rung-2 pin reads ``n`` off the absence value itself).
    """

    def __init__(
        self,
        *,
        reason: Literal[
            "no_blind_labels", "no_data_for_population", "no_data_for_backend"
        ],
        n: int | None = None,
        excluded_count: int | None = None,
        interval_low: float | None = None,
        interval_high: float | None = None,
    ) -> None:
        if reason not in _NO_DATA_REASONS:
            raise ValueError(
                f"reason must be one of {_NO_DATA_REASONS}, got {reason!r}. "
                "The Literal is part of the type: a reason outside it is not "
                "representable (CT-STATS-03)."
            )
        self.reason = reason
        self.n = n
        self.excluded_count = excluded_count
        self.interval_low = interval_low
        self.interval_high = interval_high

    def __repr__(self) -> str:
        return f"NoValidationData(reason={self.reason!r})"


# --- the statistics (the design fixes the names; the shapes are disclosed) -------------------------
#
# The helpers carry deliberately neutral names and are called from exactly one
# place — the ``agreement`` implementation below — which is what keeps the
# figure's construction in one function routed through the single filter
# (`NFR-STATS-04`).


def _band_ordinals(pairs: Sequence[tuple[Any, Any]]) -> tuple[list[tuple[int, int]], int]:
    """Both sides of each pair mapped onto one ordinal scale, and ``K``.

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
    """Observed agreement ``po`` and chance agreement ``pe`` over the pairs.

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
    """Cohen's kappa = (po − pe)/(1 − pe); undefined only when pe = 1.

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
    """The quadratic-weighted kappa over the ordinal pairs, undefined below
    K = 2 or at a degenerate denominator.

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
    """Ordinal Krippendorff's alpha over the two-rater population,
    `aeh.agg`'s declared convention (issue #91): ``alpha = 1 − D_o/D_e``,
    the unanimous exact 1.0 checked **before** the band-count test, ``None``
    below K = 2 or at a degenerate ``D_e``. ``D_o`` is the two-rater form —
    the mean per-label distance between the panel's side and the teacher's."""
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
    """The three chance-corrected statistics over the paired population.

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
    """The interval the sample size can honestly buy, centred on its figure.

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


# --- the durable read (CT-STATS-15/-18) -------------------------------------------------------------

#: This module's declared statements (`FR-STORE-08`): reads only — the clause
#: closes every write on this module (`TC-STATS-C15`'s static limb), and the
#: read is the current cohort's labels plus the pair columns, bound as a
#: parameter so no other cohort's rows and no student-identifying column ever
#: enter the query (`CT-STATS-C18`).
STATS_STATEMENTS: dict[str, Statement] = {
    # Reads only (`CT-STATS-15`), the current cohort's labels plus everything
    # beside them (`CT-STATS-C18`), bound as a parameter. The columns are read
    # wholesale rather than named one by one for the same reason the statement
    # names no mode condition: the label table's ``evaluation_mode`` column is
    # `aeh.det`'s (`CT-DET-06`, `TC-DET-09`) — its exclusion predicate is that
    # module's one definition, and a consumer's SQL that names the column
    # beside a filter is the re-spelling `NFR-DET-03` forbids. This statement
    # carries the column (as #110's insert merely carries it) and filters
    # nothing but the cohort; the admissible-label conjunction is applied to
    # the rows by this module's own filter (`NFR-STATS-04`, `TC-STATS-C01`).
    "select_labels": Statement(
        "SELECT * FROM label WHERE cohort_id = :cohort_id"
    ),
    "select_labels_all": Statement(
        "SELECT * FROM label"
    ),
}


class _StoredLabel:
    """One stored ``label`` row as the filter reads it: the durable column
    names mapped onto the label vocabulary. ``band`` is the effective band the
    label stands for (`FR-REVIEW-09`) and ``teacher_band`` rides beside it —
    ``M-REVIEW`` writes both from the teacher's band, so the row's teacher
    side falls back to ``band`` when the explicit column is NULL."""

    def __init__(self, mapping: Mapping[str, Any]) -> None:
        self.label_id = mapping.get("label_id")
        self.criterion_id = mapping.get("criterion_id") or ""
        self.label_type = mapping.get("label_type") or ""
        self.evaluation_mode = mapping.get("evaluation_mode") or ""
        self.saw_system_output = int(mapping.get("saw_system_output") or 0)
        self.system_band = mapping.get("system_band")
        self.teacher_band = (
            mapping["teacher_band"]
            if mapping.get("teacher_band") is not None
            else mapping.get("band")
        )


def _row_mapping(row: Any) -> dict[str, Any]:
    """One store row as a plain mapping, whatever ``Row`` shape the tier
    hands back (``sqlite3.Row`` carries ``keys()``; the accommodation costs
    nothing)."""
    try:
        return {key: row[key] for key in row.keys()}
    except AttributeError:
        return dict(row)


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
    """The agreement figure for one criterion, one population, one backend
    profile, one panel build and one scoring model (`FR-STATS-02`,
    `FR-STATS-03`) — or the explicit absence value for the kind of absence
    found (`FR-STATS-04`).

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


class ValidationStats:
    """The protocol surface §3.16's Interfaces block declares, over one label
    population. ``agreement`` is the member this story delivers; the other six
    members arrive with their stories (#116/#117/#118) — the constructor holds
    what they will need and nothing else (`TC-STATS-C16` holds every entry
    point to the no-raise-on-little-data discipline).

    All state is underscore-prefixed: the instance's public surface is the two
    methods, which is what the surface scans (`TC-STATS-C04`'s merge refusal)
    read."""

    def __init__(
        self,
        labels: Iterable[Any] = (),
        *,
        scoring_models: Mapping[str, str] | None = None,
        population_scopes: Sequence[str] | None = None,
        backend_profiles: Sequence[str] | None = None,
        band_counts: Mapping[str, int] | None = None,
        administration_id: str | None = None,
    ) -> None:
        self._labels = list(labels)
        self._scoring_models = dict(scoring_models or {})
        self._population_scopes = list(population_scopes or [])
        self._backend_profiles = list(backend_profiles or [])
        self._band_counts = dict(band_counts or {})
        self._administration_id = administration_id

    def admissible_labels(self) -> list[Any]:
        """The admissible population — the single filter's application
        (`NFR-STATS-04`). Every figure this module emits routes through this
        call, so R20 and R53 cannot be violated by a new caller: a caller who
        wants a figure asks here, and a caller who adds a second filter adds
        a cardinality defect `TC-STATS-C01` catches on the day it appears."""
        return [label for label in self._labels if _is_admissible(label)]

    #: §3.16's declared member, defined at module level and bound here — see
    #: ``agreement`` above.
    agreement = agreement

    def __repr__(self) -> str:
        return f"ValidationStats(labels={len(self._labels)})"


def build_stats(
    labels: Iterable[Any] = (),
    *,
    scoring_models: Mapping[str, str] | None = None,
    population_scopes: Sequence[str] | None = None,
    backend_profiles: Sequence[str] | None = None,
    band_counts: Mapping[str, int] | None = None,
    administration_id: str | None = None,
) -> ValidationStats:
    """The rung-0/1 constructor: the protocol over an in-memory label
    population (§3.16's Interfaces block names the members; the constructor is
    this suite's, keyed on #115).

    The declared kwargs arrive as keywords — the scoring-models declaration
    keys criteria to their declared scoring models, ``population_scopes=`` and
    ``backend_profiles=`` declare the populations and backends this
    installation knows (which is what makes ``no_data_for_population`` and
    ``no_data_for_backend`` reachable rather than declarable,
    `TC-STATS-C03`'s step 3), ``band_counts=`` declares the band count a
    criterion's table carries (`TC-STATS-C21`'s disclosure), and
    ``administration_id=`` names the administration the figures speak for
    (`CT-REVIEW-10`'s keying)."""
    return ValidationStats(
        labels,
        scoring_models=scoring_models,
        population_scopes=population_scopes,
        backend_profiles=backend_profiles,
        band_counts=band_counts,
        administration_id=administration_id,
    )


def open_stats(
    data_dir: Path | str | None = None,
    *,
    cohort_id: str | None = None,
) -> ValidationStats:
    """The rung-2 constructor: statistics over a real store's labels.

    Holds the store the way ``open_review`` does (`CT-STORE-01`'s rung-2
    shape), reads the **current cohort's** label rows through the declared
    statement with the cohort bound as a parameter (`CT-STATS-C18` — a second
    cohort's labels are as much a boundary crossing as another tier), and
    writes nothing (`CT-STATS-15`). No cohort named here reads every cohort
    the store carries, which is what the accumulated-scale case
    (`TC-STATS-C17`) times.

    The rows are read at construction — the constructor is where a trace sees
    the query (`TC-STATS-C18` asserts over its actual queries) — and every
    statistic after that is computed over the labels the constructor read."""
    # The store's tier migration chains are concatenated at import time by the
    # modules that own the schema they add (CLAUDE.md): the durable handle this
    # opens must not be the first open in a process that skipped the imports.
    # These ten plus this package's review module — which owns Durable's #110
    # label-store columns this read uses — make the complete chain.
    import aeh.agg  # noqa: F401
    import aeh.det  # noqa: F401
    import aeh.extract  # noqa: F401
    import aeh.grade  # noqa: F401
    import aeh.ingest  # noqa: F401
    import aeh.integ  # noqa: F401
    import aeh.judge  # noqa: F401
    import aeh.orch  # noqa: F401
    import aeh.pkg  # noqa: F401
    import aeh.review  # noqa: F401
    import aeh.synth  # noqa: F401

    from aeh.store import open_store as _open_store

    store = _open_store(data_dir)
    try:
        handle = store.durable()
        if cohort_id is not None:
            rows = handle.query(STATS_STATEMENTS["select_labels"], cohort_id=cohort_id)
        else:
            rows = handle.query(STATS_STATEMENTS["select_labels_all"])
        labels = [_StoredLabel(_row_mapping(row)) for row in rows]
    except Exception:
        store.close()
        raise
    store.close()
    return ValidationStats(labels)