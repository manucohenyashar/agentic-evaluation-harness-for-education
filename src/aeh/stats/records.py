"""The reports M-STATS returns: compression, proxies, routing, drift, the validation record."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class BandShape:
    """The shape of one side's band distribution, as the compression check reads it.

    The two statistics `FR-STATS-06` names, plus the ``n`` they were computed
    over — the same discipline as the agreement figure's sample size
    (`NFR-STATS-02`): a shape without its population is not representable.
    ``None`` statistics are the explicit not-measured value: no distribution,
    no entropy, and a band count below three has no interior to measure."""
    band_entropy: float | None
    interior_rate: float | None
    n: int


@dataclass(frozen=True)
class CompressionReport:
    """What `compression_check` returns (FR-STATS-06, CT-STATS-10).

    ``panel_narrower`` is the check's finding — **relative** compression, the
    only direction the comparison can see — and ``stated_limitation`` is part
    of the value, not a footnote beside it (`CT-STATS-10`): the check compares
    the panel against the teacher, so a panel and a teacher compressing
    together produce a clean result, and the report says so wherever it goes.
    The empty population carries the same limitation with no distribution, so
    "no compression found" and "nothing measured" cannot be confused."""
    cohort_id: str | None
    criterion_id: str | None
    gold: BandShape
    panel: BandShape
    panel_narrower: bool | None
    stated_limitation: str
    n: int
    excluded_count: int


@dataclass(frozen=True)
class ProxyReport:
    """What `surface_proxies` returns (FR-STATS-07).

    ``correlations`` is the declared measured channel — what the caller
    measured, per criterion and per surface feature — and
    ``surface_proxy_flags`` is the per-criterion payload `FR-STATS-07` stores
    in the validation record: the features whose ``|r|`` reached the
    threshold, with their correlations. The durable write of that payload is
    the validation record writer's (#118's ``promote``, through `M-PKG`,
    `CT-STATS-15`) — this report carries the payload, and the report is the
    seam it hands over. ``captured_features`` discloses which of
    `FR-STATS-07`'s features the channel actually supplied — the
    handwriting-legibility band is a regression input *where captured*, and a
    feature absent here was not measured, not measured at zero.

    ``subgroup_breakdowns`` is ``None`` unless the subgroup gate is open and
    the caller asked — the two-key gate of `NFR-STATS-05`."""
    cohort_id: str | None
    criterion_id: str | None
    correlations: Mapping[str, Mapping[str, float]]
    surface_proxy_flags: Mapping[str, Mapping[str, float]]
    captured_features: tuple[str, ...]
    n: int
    subgroup_breakdowns: Mapping[str, Mapping[str, float]] | None = None


@dataclass(frozen=True)
class RoutingArm:
    """One arm of the routing-policy comparison (FR-STATS-08).

    ``n`` is the arm's admissible population — the population the claim is
    about (`TC-STATS-C11`'s oracle reads it); ``error_rate`` is computed over
    the paired subset and is ``None`` where the arm carries no paired labels,
    which is what makes ``no_data`` reachable as a value."""
    n: int
    paired: int
    errors: int
    error_rate: float | None


@dataclass(frozen=True)
class RoutingPolicyReport:
    """What `routing_policy_validity` returns (FR-STATS-08, CT-STATS-11).

    ``verdict`` uses the vocabulary the clause fixes: ``failing`` when the two
    arms' error rates are similar (or inverted), ``discriminating`` when the
    escalated arm shows the larger rate by at least the tolerance, and
    ``no_data`` where an arm has no computable rate (`CT-STATS-16`'s value,
    not an exception). ``stated_interpretation`` carries the reading the
    verdict vocabulary rests on — similar rates are a finding about
    `M-AGG`'s constants, never ``uninformative``."""
    cohort_id: str | None
    verdict: str
    label_population: Mapping[str, RoutingArm]
    tolerance: float
    stated_interpretation: str
    n: int


@dataclass(frozen=True)
class StatsAlert:
    """One contract alert (CT-STATS-19): its declared name, with the criterion and the correlation
    that caused it."""
    name: str
    detail: str


@dataclass(frozen=True)
class DriftReport:
    """What `drift_check` returns (FR-STATS-09, CT-STATS-12).

    ``sample_size`` is what the check actually used — inside
    ``DRIFT_SAMPLE_RANGE``, an even spread of what was available — and
    ``sample_source`` discloses where the distributions came from: the
    caller's ``current=`` channel, or the instance's admissible population,
    in which case ``sample_size`` still describes the caller's submission
    sample while the distributions cover that whole population. ``criteria_
    covered`` names the criteria the check covered, judged criteria
    only (`CT-DET-02`'s exclusion makes the exclusion real rather than
    declarative). ``distances`` compares each criterion's sample distribution
    against the baseline the caller declared from `M-PKG`'s records; a
    criterion absent from ``distances`` had no comparable baseline, which
    ``baseline_distributions`` discloses rather than hides.

    ``advisory`` is always true and ``binding_threshold`` is always ``None``:
    `CT-STATS-12`'s *"advisory, never a gate"* is a property of the check, not
    a mode the caller selects, and ``why_not_binding`` states what the
    absence means — no threshold would make it binding, by design."""
    package_version: str | None
    sample_size: int
    sample_ids: tuple[Any, ...]
    sample_source: str
    criteria_covered: tuple[str, ...]
    distributions: Mapping[str, Mapping[Any, int]]
    baseline_distributions: Mapping[str, Mapping[Any, int]] | None
    distances: Mapping[str, float]
    drifted: tuple[str, ...]
    severity: float | None
    advisory: bool
    binding_threshold: None
    why_not_binding: str


# --- the validation record's return types (#118, FR-STATS-10..14) -----------------------------------
#
# Every one is a figure-shaped value: ids, counts, coefficients and the names
# of flags — never prose about the system's quality. `promote`'s update is
# swept for exactly that property (the sentinel scan reads every field of the
# value `promote` returns), and the aggregate carries the weakest criterion
# beside the figures it summarizes rather than instead of them.


@dataclass(frozen=True)
class ValidationUpdate:
    """What recording one administration changed (FR-STATS-10, CT-STATS-05, CT-STATS-06): the three
    counters, each answering its own question, and the figure the administration's blind labels
    support.

    ``cohorts_used`` counts the administrations the record now speaks for;
    ``blind_count`` and ``operational_count`` count the claimed labels
    **separately** — merging any two would let operational volume read as
    validation depth (RISK-07), and `CT-STATS-06` pins all three values
    distinct. ``n`` is the blind population the record's ``agreement_kappa``
    was computed over; ``agreement_kappa`` is ``None`` whenever that population
    is multi-criterion (a blended headline is the claim `CT-STATS-04` keeps
    unrepresentable) or too small to compute one — the per-criterion figures
    travel in ``weakest_per_population`` instead.

    ``message`` carries `NO_NEW_VALIDATION_EVIDENCE` when the administration
    collected no blind labels (``CT-STATS-05``'s first-class absence value) and
    is otherwise empty — the counters, not prose, are the record's content.
    ``surface_proxy_flags`` is #117's `ProxyReport` payload seam, carried
    through to the durable record; ``weakest_per_population`` maps each
    population (the claimed cohort, or the declared scopes at rung 0) to its
    weakest criterion. All fields are figures and ids — never a claim about the
    system."""
    cohort_id: str | None
    package_version_id: str | None
    cohorts_used: int
    operational_count: int
    blind_count: int
    n: int
    agreement_kappa: float | None
    weakest_per_population: Mapping[str, Mapping[str, Any]]
    surface_proxy_flags: tuple[str, ...]
    message: str
    #: `#373`, seam 4: what became of each criterion's baseline distribution, keyed by
    #: criterion id, valued by `aeh.pkg`'s `BASELINE_*` reason — `BASELINE_RECORDED` when
    #: it landed, and the reason it did not otherwise. Defaulted empty because rung 0
    #: writes nothing at all, so it has no outcomes to report rather than failed ones.
    #:
    #: It is a field rather than a log line because the refusals are ORDINARY: an
    #: administration promoted against a published package is the normal case, and
    #: `FR-PKG-04` freezes that version's validation records. Without this, `promote`
    #: would return its counters and a success status over a baseline that was never
    #: stored, leaving `should_escalate`'s input no-data with nothing anywhere saying so.
    baseline_outcomes: Mapping[str, str] = field(default_factory=dict)
    #: FR-STATS-29 (#454): per criterion, what the non-inferiority write did — the verdict
    #: recorded, or why nothing was (a published version, no cohort file). Empty for an
    #: engine-off administration, which writes nothing.
    noninferiority_outcomes: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationAggregate:
    """The per-population aggregate (CT-STATS-04): one value per declared population scope, never a
    figure spanning them.

    ``weakest_per_population`` is the clause's *"the weakest criterion per
    population is exposed alongside every aggregate figure"* (`FR-STATS-13`):
    each declared scope maps to its weakest criterion — the one whose blind
    agreement figure is lowest — so a consumer reading the aggregate reads the
    criterion the whole population stands or falls on, in the same value. A
    scope whose labels carry no per-label scope attribute reports the
    population-wide weakest (the labels a caller supplies through the
    in-memory constructor carry no scope of their own; the declared scopes are
    what this installation knows, and the aggregate refuses to invent a
    per-scope split the data does not carry — that disclosure is this class's
    whole reason to exist, and `aggregate()`'s docstring states it)."""

    population_scopes: tuple[str, ...]
    weakest_per_population: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class CriterionOverrideHistory:
    """One criterion's override history (CT-STATS-09): the number of reviews, how many overrode the
    panel, and the rate. A criterion nobody reviewed returns `NoValidationData`, because a zero
    rate would rank it safest in the very queue that decides what gets looked at next."""
    criterion_id: str
    n: int
    override_count: int
    override_rate: float | None


@dataclass(frozen=True)
class CriterionDisagreement:
    """One criterion's disagreement rate (FR-STATS-28): over every blind or operational label with
    both bands, how many gave a different band from the system's. It is the review ranking's eighth
    input (FR-REVIEW-18)."""
    criterion_id: str
    n: int
    disagreements: int
    rate: float


@dataclass(frozen=True)
class NarrativeQualityReport:
    """The narrative-quality figures, reported separately from score agreement (FR-STATS-12,
    CT-STATS-14): citation validity rate, hallucinated-claim rate, and the teacher's rating when
    collected.

    The three ride this report and never an `AgreementFigure` — combining
    them would let a narrative channel's numbers dress an agreement statistic
    up as a quality claim, which is the combination `CT-STATS-14` forbids.
    Each metric is ``None`` where its channel was not declared: absence is the
    value, not a zero."""
    cohort_id: str | None
    citation_validity_rate: float | None
    hallucinated_claim_rate: float | None
    teacher_rating: float | None
    channel_declared: bool


@dataclass(frozen=True)
class OperationalSignal:
    """The weighted operational signal (FR-STATS-14), with the weights that produced it. It is a
    signal, not a validated figure.

    ``signal`` is the weighted mean agreement over the paired population;
    ``weights`` are the evidence weights it was computed with (the declared
    ordering's defaults, or the caller's); ``weighted`` says whether any
    non-default weight was applied at all, so a consumer can tell a weighted
    signal from an unweighted one without re-deriving it. The value carries no
    validity claim: the agreement figure is the only place a validity claim
    comes from, and it is computed unweighted."""
    signal: float | None
    weights: Mapping[str, float]
    n: int
    weighted: bool


@dataclass(frozen=True)
class CriterionFigure:
    """One criterion's figure as the validation record keeps it (FR-STATS-13): the criterion, the
    rubric revision it was measured under, and the scope it is a claim about. `rubric_version` is
    required, because a figure without it is a claim about an unnamed revision."""
    criterion_id: str
    rubric_version: str | None
    backend_profile: str | None
    panel_build_ref: str | None
    n: int
    cohort_id: str | None
