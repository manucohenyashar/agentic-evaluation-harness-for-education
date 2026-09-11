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

**The MVVP as six separately-reported protocols (`FR-STATS-05`, #116).**
``run_mvvp`` runs the Minimum Viable Validation Protocol (HLD §2.5) and
reports each of its six steps individually — step 1 is the chance-corrected
agreement surface above, step 2 the order/position swap, step 3 the
replication floor, step 4 cross-validation by assignment type, step 5 the
consistency-bias pairing, step 6 the compression check. Never one pass/fail:
the return type carries no ``passed``, no ``ok``, no ``verdict`` (`CT-STATS-07`
sweeps the names a convenience property would take). Steps 2–5 re-run
whenever any panel member, build, quantization or prompt-template version
changes (`FR-STATS-19`, HLD R30) — ``result_id`` is content-addressed on the
assignment type and the four trigger dimensions, and no durable result is
kept to reuse, show or merge (`CT-STATS-15` writes nothing), so a changed
dimension is a different result by construction.

**The four checks that read the same population differently (#117).**
``compression_check``, ``surface_proxies``, ``routing_policy_validity`` and
``drift_check`` complete the protocol surface (`FR-STATS-06`..`FR-STATS-09`).
Each is a *comparison* rather than a quality number, and each carries the
interpretation its clause fixes inside the value it returns:

* *Compression is relative, and its blind spot is part of the value*
  (`CT-STATS-10`). The check compares the panel's band shape against the blind
  gold labels' using ``band_entropy`` and ``interior_rate`` and reports
  ``panel_narrower`` — the only direction it can see. A panel and a teacher
  compressing **together** produce a clean result, so the report carries the
  co-compression limitation as a field, including in its empty case, where
  "no distribution" and "no compression found" must not be confusable.
* *The surface-proxy regression is a measured channel.* The regression's
  inputs — assigned scores beside response length, vocabulary complexity, OCR
  quality, handwriting legibility where captured, formatting regularity — are
  the pipeline's score rows, which this module does not hold; the caller that
  measured the per-criterion correlations declares them through
  ``build_stats(surface_correlations=...)`` exactly as #116's MVVP declares
  its measured channels. What this module owns is the interpretation: a
  feature whose ``|r|`` reaches the threshold is a surface-proxy flag, the
  alert ``surface_proxy_flag_on_criterion`` fires on it (`CT-STATS-19`), and
  the per-criterion payload is the ``ProxyReport.surface_proxy_flags`` the
  validation record's writer (#118's ``promote``, through `M-PKG`) stores.
* *Subgroup analysis is a two-key gate* (`NFR-STATS-05`, `CT-STATS-18`).
  ``STATS_SUBGROUP_ANALYSIS_ENABLED`` defaults to false — the declared
  Configuration value, carried as a module constant so the default is
  inspectable — and the environment knob may enable it only where an
  installation has declared the analysis locally lawful, which is a decision
  this module cannot make. Even enabled, the breakdown runs only on an
  explicit ``subgroup=`` request; and a request while the gate is closed is a
  refusal, not an empty result.
* *Similar routing rates are failing, not uninformative* (`CT-STATS-11`,
  HLD R22). The policy is working when the escalated-and-reviewed arm shows
  the larger error rate against blind teachers (the HLD's 8%-versus-1% gap);
  rates within the tolerance mean the policy escalates the wrong things, and
  the verdict is ``failing`` — the finding about `M-AGG`'s constants, not an
  absence of one. The arms are read off the label's ``routing`` column through
  ``ROUTING_POLICY_ARM_SOURCES``: the column carries the queue's admission
  routing (`CT-AGG-06`'s closed set), so the escalated-and-reviewed arm is the
  ``reviewed`` rows — the one value `aeh.agg` never assigns, because it names
  a review that has happened — and the auto-accepted arm is the ``auto`` rows;
  still-queued, triage and provisional rows join neither. The tolerance is an
  environment knob whose default is the declared 0.05, and arms without a
  computable rate return ``no_data`` as a value (`CT-STATS-16`), never an
  exception.
* *Drift is advisory, and the report says what would make it binding*
  (`CT-STATS-12`). The sample is 20–30 submissions (`FR-STATS-09`), taken as a
  deterministic even spread that spans the sample end to end — no randomness,
  and no truncation to its head; a sample below the floor is the absence
  value, not a verdict computed on too little. The comparison runs over judged
  criteria only (`CT-DET-02`'s exclusion), against a baseline the caller
  declares from `M-PKG`'s records. ``binding_threshold`` is ``None`` **by
  design**: there is no distance, severity or sample size at which this check
  starts blocking a run — HLD R11 forbids gating a school's grading on an
  advisory comparison of at most 30 submissions, and `NFR-SYS-08` declares no
  threshold here — so the field states the absence rather than leaving it
  implied.

The four seams (CLAUDE.md): the constructor pair is the headless driver —
``build_stats``/``open_stats`` return structured values with no console in the
loop; the deterministic transport for every external dependency is `aeh.store`
itself, the deterministic local store this module's reads ride (no egress of
its own); the environment-sensitive constants are env-gated knobs read at
call time with the declared production value as the default —
``STATS_SUBGROUP_ANALYSIS_ENABLED`` (pinned by `TC-STATS-C18`'s case) and the
three detector sensitivities #117 adds for the surface-proxy flag, the
routing tolerance and the drift distance — so a slower box or a lawful
installation adjusts without a code change. (``STATS_MIN_N_FOR_HEADLINE``,
pinned by `TC-STATS-C20`, is a declared constant from #115 and deliberately
not an environment knob: the display-qualifier boundary is a contract value,
not an environment-sensitive one.) And every figure is stage-level
observability by construction — n, the excluded count, the stated limitation,
the verdict's stated interpretation and the advisory statement travel with the
number, next to it, not in a footnote.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from aeh.store import Statement

__all__ = [
    "AgreementFigure",
    "BandShape",
    "CompressionOutcome",
    "CompressionReport",
    "CrossValidationOutcome",
    "DRIFT_SAMPLE_RANGE",
    "DriftReport",
    "MVVPReport",
    "MVVPStep",
    "NoValidationData",
    "PositionBiasResult",
    "ProxyReport",
    "ROUTING_POLICY_ARM_SOURCES",
    "ROUTING_POLICY_ARMS",
    "ROUTING_POLICY_DISCRIMINATING_VERDICT",
    "ROUTING_POLICY_FAILING_VERDICT",
    "ROUTING_POLICY_NO_DATA_VERDICT",
    "ReplicationResult",
    "SCORING_MODELS",
    "SURFACE_FEATURES",
    "SURFACE_PROXY_ALERT",
    "SelfAgreementPairing",
    "STATS_MIN_N_FOR_HEADLINE",
    "STATS_STATEMENTS",
    "STATS_SUBGROUP_ANALYSIS_ENABLED",
    "STATS_SURFACE_PROXY_CORRELATION_THRESHOLD",
    "STATS_ROUTING_POLICY_TOLERANCE",
    "STATS_DRIFT_TOLERANCE",
    "StatsAlert",
    "RoutingArm",
    "RoutingPolicyReport",
    "ValidationStats",
    "agreement",
    "alerts",
    "build_stats",
    "compression_check",
    "drift_check",
    "latest_mvvp",
    "open_stats",
    "routing_policy_validity",
    "run_mvvp",
    "surface_proxies",
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


# --- the #117 constants (FR-STATS-06..09, CT-STATS-10/11/12/18/19) ---------------------------------
#
# The declared values are the defaults; the three detector sensitivities are
# env-gated knobs read at call time (seam 3) — an installation adjusts without
# a code change. ``STATS_SUBGROUP_ANALYSIS_ENABLED`` is the Configuration
# block's own knob and is *not* env-defaulted here: the module constant is the
# declared default (``TC-STATS-C18`` pins it), and the environment override is
# read at call time by the one function that implements the gate.

#: The two populations `FR-STATS-08` compares. The names are the comparison
#: protocol's; the values a label actually carries in its ``routing`` column
#: are the queue's admission routing (`CT-AGG-06`'s closed set), copied onto
#: the label for traceability (`CT-REVIEW-07`) — so ``routing_policy_validity``
#: reads the column through ``ROUTING_POLICY_ARM_SOURCES``, which maps each
#: arm onto the routing values that name it.
ROUTING_POLICY_ARMS: tuple[str, ...] = ("escalated_and_reviewed", "auto_accepted")

#: Which ``routing`` values put a label in which arm. The label's ``routing``
#: column carries the queue's admission routing — `CT-AGG-06`'s closed set
#: ``{auto, queued, provisional, reviewed, triage}`` — recorded on the label
#: for traceability (`CT-REVIEW-07`), and the two arms of `FR-STATS-08`'s
#: comparison are read off it: ``reviewed`` — the one value `aeh.agg` never
#: assigns, because it names a review that has happened — is the
#: escalated-and-reviewed arm; ``auto`` — the confidence met the scoring
#: model's threshold — is the auto-accepted arm. Each arm also accepts its own
#: protocol name, which is what an in-memory construction of the comparison
#: uses. The other three values join **neither** arm on purpose: ``queued`` and
#: ``triage`` are judgments still awaiting review — escalated, but the review
#: the arm names has not happened — and ``provisional`` names a single-judge
#: band or a tripped breaker that was never auto-accepted, so it belongs to no
#: population the policy created. Rows predating the column read ``None`` and
#: join neither arm rather than being guessed into one.
ROUTING_POLICY_ARM_SOURCES: Mapping[str, tuple[str, ...]] = {
    "escalated_and_reviewed": ("escalated_and_reviewed", "reviewed"),
    "auto_accepted": ("auto_accepted", "auto"),
}

#: The verdict vocabulary `CT-STATS-11` fixes. ``failing`` is what similar
#: rates in both arms mean — the policy escalates the wrong judgments, which is
#: a finding about `M-AGG`'s declared constants (R22), not an absence of one;
#: ``uninformative`` is the reading the clause forbids and the module never
#: returns it. ``discriminating`` is the healthy direction (the escalated arm's
#: error rate against blind teachers exceeds the auto-accepted one's by at
#: least the tolerance — the HLD's 8%-versus-1% gap). ``no_data`` is the
#: insufficient-data value (`CT-STATS-16`), not a verdict.
ROUTING_POLICY_FAILING_VERDICT = "failing"
ROUTING_POLICY_DISCRIMINATING_VERDICT = "discriminating"
ROUTING_POLICY_NO_DATA_VERDICT = "no_data"

#: The tolerance below which the two arms' error rates count as "similar" —
#: env-gated at call time under this same name, production default declared
#: here. A detector sensitivity, not a quality threshold: it decides when the
#: comparison cannot tell the arms apart, never whether the system is good.
STATS_ROUTING_POLICY_TOLERANCE = 0.05

#: The ``|r|`` at which a surface feature becomes a surface-proxy flag —
#: env-gated at call time under this same name. A detector sensitivity, not a
#: quality threshold (`CT-STATS-20`'s non-promise is about verdicts on
#: agreement figures; this decides when the alert `CT-STATS-19` declares fires).
STATS_SURFACE_PROXY_CORRELATION_THRESHOLD = 0.7

#: The total-variation distance at which a criterion's sample distribution
#: counts as drifted from the baseline — env-gated at call time. The check is
#: advisory regardless (`CT-STATS-12`); this only decides which distances the
#: report names, and no threshold makes the check binding.
STATS_DRIFT_TOLERANCE = 0.1

#: `NFR-STATS-05`'s gate, as the Configuration block declares it. **False is
#: the contract**: a subgroup analysis running by default is a regulatory
#: exposure nobody chose. The module constant is the declared default; the
#: environment knob of the same name may enable it where an installation has
#: declared the analysis locally lawful — a decision this module cannot make —
#: and even then the breakdown runs only on an explicit ``subgroup=`` request.
STATS_SUBGROUP_ANALYSIS_ENABLED = False

#: `FR-STATS-09`'s declared sample window, inclusive at both ends. A sample
#: below the low end is the absence value (`TC-STATS-C12` asserts both
#: boundaries); above the high end the check takes an even spread of the
#: declared size and reports how many it used.
DRIFT_SAMPLE_RANGE: tuple[int, int] = (20, 30)

#: `FR-STATS-07`'s surface features that *ought to be irrelevant* to a score.
#: ``subgroup`` is deliberately absent here — it is not a regression input on
#: this surface but the gated analysis behind ``surface_proxies(subgroup=)``
#: (`NFR-STATS-05`); ``handwriting_legibility_band`` is reported as captured
#: only where the declared correlations carry it.
SURFACE_FEATURES: tuple[str, ...] = (
    "response_length_tokens",
    "vocabulary_complexity",
    "ocr_quality_score",
    "handwriting_legibility_band",
    "formatting_regularity",
)

#: The alert name `CT-STATS-19` declares contract — the only detector for a
#: criterion with an excellent κ and no validity. A length or OCR correlation
#: means that criterion is measuring something other than what it claims,
#: **whatever its agreement statistic says**.
SURFACE_PROXY_ALERT = "surface_proxy_flag_on_criterion"

#: The stated interpretation `CT-STATS-11` fixes, carried in the report itself
#: (the same discipline as `CT-STATS-10`'s limitation): the verdict vocabulary
#: travels with the reading that justifies it.
_ROUTING_POLICY_INTERPRETATION = (
    "similar error rates in both arms are failing, not uninformative: a policy "
    "whose escalated arm shows no more teacher disagreement than its "
    "auto-accepted arm is escalating the wrong judgments, which is a finding "
    "about the escalation constants, not an absence of one (CT-STATS-11, HLD R22)"
)

#: The advisory statement the drift report carries (`CT-STATS-12`). It is part
#: of the value, like the compression check's limitation: the field answers
#: the reader's next question — what would make this binding — instead of
#: leaving the answer in a docstring.
_DRIFT_ADVISORY_STATEMENT = (
    "advisory, never a gate: no distance, severity or sample size makes this "
    "check binding. A binding threshold would stop a school's grading on an "
    "advisory comparison of at most 30 submissions against a baseline (HLD "
    "R11, CT-STATS-12), and NFR-SYS-08 declares no threshold here — so there "
    "is no binding threshold, by design, and the consumer decides what to do "
    "with the distances; the check only reports them."
)


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
    side falls back to ``band`` when the explicit column is NULL. ``routing``
    is `CT-REVIEW-07`'s column (`FR-STATS-08`'s arms read it); rows predating
    the column read as ``None``, which `routing_policy_validity` keeps out of
    both arms rather than guessing an arm for them."""

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
        self.routing = mapping.get("routing")


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
    """The measured channel's per-judge rates, validated as what they claim.

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
    """The result id, content-addressed on what the result is a claim about.

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
    """`FR-STATS-15`'s step-2 result for one judge: the band-change rate over
    the held-out fixture subset re-scored with the exemplar order and the
    reference-material presentation order permuted.

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
    """`FR-STATS-16`'s step-3 result for one judge — and the two claims it
    reports **together** because they are different claims about different
    things.

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
    """`FR-STATS-17`'s step-4 outcome: the agreement figures for **one**
    assignment type, one criterion at a time — and the structural refusal the
    clause demands for the wider claim.

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
    """`FR-STATS-18`'s paired row for one judge: the step-3 rate and step 2's
    position-bias result, one value, never one without the other.

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
    """`FR-STATS-06`'s step-6 outcome: the panel's band shape against the
    gold's, computed over the paired population — the two sides of the same
    agreement pairs step 1's figure is computed over.

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
    """One protocol step's individually-reported record (`CT-STATS-07`).

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
    """The MVVP report: six separately-reported steps, one configuration,
    one result id (`FR-STATS-05`, `FR-STATS-19`, #116).

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
    """`FR-STATS-17`'s step-4 outcome: agreement per assignment type.

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
    """Shannon entropy of one side's band distribution, in bits.

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
    """The rate of interior bands — non-extreme on the ordinal scale.

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
    """`FR-STATS-06`'s step-6 outcome: the panel's band shape against the
    gold's, over the paired population both sides carry.

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
    """The Minimum Viable Validation Protocol, as six separately-reported
    protocol steps (`FR-STATS-05`, #116; HLD §2.5).

    One call, six answers — each step's own outcome record beside its own
    requirement (`MVVP_STEP_REQUIREMENTS` is `FR-STATS-05`'s mapping), never
    collapsed into one pass/fail (`CT-STATS-07`). The steps:

    1. the chance-corrected agreement surface (`FR-STATS-02`) — the figures
       `agreement` emits, one per criterion in scope, or the surface's own
       absence value for a population with no criteria to figure;
    2. the order/position swap (`FR-STATS-15`) — the held-out fixture subset
       re-scored with the exemplar order and the reference-material
       presentation order permuted, per judge (`TC-STATS-16`'s live tier
       measures the rate through the injected provider seam, the one egress
       point; headlessly each judge's result is the explicit not-measured
       value with its declared reason);
    3. the replication floor (`FR-STATS-16`) — per-judge self-agreement
       reported **together with** the backend's declared
       ``deterministic_at_temperature_zero`` (`CT-PROV-04`'s claim), the two
       different claims they are, never merged;
    4. cross-validation by assignment type (`FR-STATS-17`) — one assignment
       type's figures, per criterion, with the spanning refusal structural:
       no figure spanning assignment types is representable in the value, and
       where the labels carry types and none is named, the step is the
       disclosed refusal (`no_assignment_type_named`), never a pooled figure;
    5. the consistency-bias pairing (`FR-STATS-18`) — every judge in scope's
       step-3 rate beside its step-2 position-bias result, one pair, never
       one figure alone;
    6. the compression check (`FR-STATS-06`) — the panel's band shape
       against the gold's, with its stated limitation in the value.

    **The measured channel** (the four seams' third): what a caller has
    measured arrives declared — ``measured_self_agreement`` for step 3, the
    ≥3-run replication's per-judge rates; ``measured_position_bias`` for
    step 2's swap; ``backend_claims_deterministic_at_temperature_zero`` for
    the backend's declaration. A rate is reported verbatim — never clamped,
    floored or omitted (`TC-JUDGE-C17` limb 3: a measured value below 1.0 is
    the finding the protocol exists to surface, not a failure). What was not
    measured is the declared not-measured value with its reason — never a
    plausible number, never a raise (`CT-STATS-03`, `CT-STATS-16`).

    **Re-run semantics (`FR-STATS-19`, `CT-STATS-08`).** ``configuration``
    carries the four trigger dimensions; each is echoed in the result's
    ``measured_configuration`` and in steps 2–5's own records, so a consumer
    can verify the match itself. ``result_id`` digests the assignment type
    and the four — a changed dimension is a different id, and ``latest_mvvp``
    answers consult-time calls by measuring fresh, because no durable result
    is kept to reuse, show or merge.

    Defined at module level and bound into ``ValidationStats`` below, so the
    surface ``require(STATS_MODULE, "run_mvvp")`` names and the method the
    instance carries are the same function. Raises on programming errors
    only (`CT-STATS-16`): a malformed argument propagates. Insufficient data
    is the per-step outcome."""
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
    """`CT-STATS-08`'s consult-time entry: the **current** result for a
    configuration.

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


# --- the four comparisons (#117, FR-STATS-06..09) --------------------------------------------------
#
# Four checks over the same admissible population that the agreement figure
# reads, each a comparison rather than a quality number and each carrying its
# fixed interpretation inside its own value. Like ``agreement`` above, each is
# defined at module level and bound into ``ValidationStats``, so the surface
# ``require(STATS_MODULE, ...)`` names and the method the instance carries are
# the same function — and each routes its population through the single
# filter's application (``admissible_labels()``, `NFR-STATS-04`): no figure on
# this surface is computed over any other population.


def _env_flag(name: str, default: bool) -> bool:
    """One boolean environment knob, read at call time (seam 3).

    The declared production value is the default; the knob exists so an
    installation adjusts without a code change. An unset or empty variable
    falls through to the default, a recognised boolean spelling is honoured,
    and anything else is refused with the knob's name — a mis-spelled
    ``STATS_SUBGROUP_ANALYSIS_ENABLED=tru`` must fail loudly, not silently run
    the gate closed.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    lowered = raw.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ValueError(
        f"environment knob {name}={raw!r} is not a boolean; use 1/true/yes/on "
        "or 0/false/no/off."
    )


def _env_float(name: str, default: float) -> float:
    """One numeric environment knob, read at call time (seam 3).

    Non-finite values are refused along with unparseable ones: a threshold of
    ``nan`` or ``inf`` would silently disable the detector it calibrates — a
    mis-spelled value must fail loudly, the same refusal ``_env_flag`` makes.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(
            f"environment knob {name}={raw!r} is not a number."
        ) from error
    if not math.isfinite(value):
        raise ValueError(
            f"environment knob {name}={raw!r} is not a finite number; a "
            "non-finite sensitivity would silently disable the detector it "
            "calibrates."
        )
    return value


def _subgroup_analysis_enabled() -> bool:
    """The subgroup gate's effective state: the declared default, overridden by
    the environment knob of the same name where an installation declares the
    analysis locally lawful (`NFR-STATS-05`)."""
    return _env_flag("STATS_SUBGROUP_ANALYSIS_ENABLED", STATS_SUBGROUP_ANALYSIS_ENABLED)


def _surface_proxy_threshold() -> float:
    return _env_float(
        "STATS_SURFACE_PROXY_CORRELATION_THRESHOLD",
        STATS_SURFACE_PROXY_CORRELATION_THRESHOLD,
    )


def _routing_policy_tolerance() -> float:
    return _env_float(
        "STATS_ROUTING_POLICY_TOLERANCE", STATS_ROUTING_POLICY_TOLERANCE
    )


def _drift_tolerance() -> float:
    return _env_float("STATS_DRIFT_TOLERANCE", STATS_DRIFT_TOLERANCE)


def _require_str_or_none(member: str, **named: Any) -> None:
    """A population key is a string or ``None``; anything else is a programming
    error, and `CT-STATS-16` raises on programming errors."""
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
    """Refuse a report that would name a cohort the instance does not hold.

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
    """Both sides of each label's band pair, dropping the genuinely one-sided.

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
    """The features whose ``|r|`` reaches the flag threshold, in a stable order.

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
    """The total-variation distance between two band distributions.

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


@dataclass(frozen=True)
class BandShape:
    """One side's band-distribution shape, as the compression check reads it.

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
    """`compression_check`'s return value (`FR-STATS-06`, `CT-STATS-10`).

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
    """`surface_proxies`' return value (`FR-STATS-07`).

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
    """One arm of the routing-policy comparison (`FR-STATS-08`).

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
    """`routing_policy_validity`'s return value (`FR-STATS-08`, `CT-STATS-11`).

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
    """One contract alert (`CT-STATS-19`): the declared name, beside the
    criterion and the correlation that provoked it."""
    name: str
    detail: str


@dataclass(frozen=True)
class DriftReport:
    """`drift_check`'s return value (`FR-STATS-09`, `CT-STATS-12`).

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


def compression_check(
    self: "ValidationStats",
    cohort_id: str | None = None,
    criterion_id: str | None = None,
) -> CompressionReport:
    """The compression check for one criterion (`FR-STATS-06`, `CT-STATS-10`):
    the panel's band shape against the blind gold labels' shape, measured by
    ``band_entropy`` and ``interior_rate``, with the finding
    (``panel_narrower``) and the co-compression limitation in the same value.

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
    """The surface-proxy report for one criterion (`FR-STATS-07`): the
    per-criterion correlations the caller measured between assigned scores and
    the surface features that ought to be irrelevant, and the flags where a
    feature's ``|r|`` reaches the threshold.

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
    """The routing-policy validity report for one cohort (`FR-STATS-08`,
    `CT-STATS-11`): the error rate among escalated-and-reviewed judgments
    against the error rate among auto-accepted ones, both populations drawn
    from the admissible labels by their ``routing`` column read through
    ``ROUTING_POLICY_ARM_SOURCES`` — the column carries the queue's admission
    routing (`CT-AGG-06`'s closed set, recorded for traceability), and a label
    joins an arm when its routing names that arm or is the queue value the arm
    corresponds to: ``reviewed`` for escalated-and-reviewed, ``auto`` for
    auto-accepted.

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
    """The advisory drift check for one package (`FR-STATS-09`, `CT-STATS-12`).

    The sample is 20–30 submissions (`DRIFT_SAMPLE_RANGE`, inclusive at both
    ends). Above the high end the check takes an even spread of the declared
    size and reports how many it used; below the low end there is no valid
    sample and the answer is the absence value with ``n`` as context — a drift
    verdict computed on nineteen submissions is exactly the substitute figure
    `CT-STATS-16` forbids. The spread is deterministic on purpose: the sample
    must span the caller's list end to end, first and last submission
    included, and no randomness may enter a claim's evidence.

    The comparison runs over **judged** criteria only: a criterion the
    constructor declares deterministic is excluded from
    ``criteria_covered``, because a deterministic result carries no verdicts
    and there is no distribution to compare (`CT-DET-02`). The sample's
    distributions come from the declared ``current=`` channel when the caller
    supplies one, otherwise from the constructor's admissible population —
    the current administration's judged distribution — and
    ``sample_source`` names which. With the constructor population as the
    source, ``sample_size`` still describes the caller's submission sample
    while the per-criterion distributions cover the instance's whole
    admissible population — the disclosure is in ``sample_source`` precisely
    so the two are never confused. The baseline comes from the caller's
    declared ``baseline=`` channel (`M-PKG`'s records; this module writes
    nothing and owns no baseline of its own), and ``distances`` compares the
    two where both sides exist — the total-variation distance, with the
    drifted criteria named at the tolerance.

    ``advisory`` is always true and ``binding_threshold`` is always ``None``
    (`CT-STATS-12`): the statement in the value says what would make it
    binding and why none exists. Raises on programming errors only; a sample
    below the floor is the absence value, not a raise."""
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
    """The contract alerts the instance's declared channels provoke
    (`CT-STATS-19`). The surface-proxy alert is the only detector for a
    criterion with an excellent κ and no validity: a length or OCR
    correlation means that criterion is measuring something other than what
    it claims, **whatever its agreement statistic says** — no other view in
    the system can see it, because every other view is downstream of the
    score. The blind-sample alert is the validation record's (#118), whose
    writer owns the administrations channel this alert reads.

    Deterministic: criteria and features in sorted order, so the same
    declared correlations produce the same alerts on every call."""
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
    return tuple(fired)


class ValidationStats:
    """The protocol surface §3.16's Interfaces block declares, over one label
    population. ``agreement`` (#115), ``run_mvvp`` (#116), and the four
    comparisons (#117) are the members this file delivers; ``promote``
    (#118) — the validation record's writer — is the one that arrives with
    its story. The constructor holds what the delivered members read and
    nothing else (`TC-STATS-C16` holds every entry point to the
    no-raise-on-little-data discipline).

    Beyond #115/#116's constructor state, #117's members read three more
    declared channels: ``cohort_id``, the cohort ``open_stats`` read the
    labels for (so a report cannot name a cohort the instance does not
    hold); ``evaluation_modes``, the criterion-to-mode declaration whose
    ``deterministic`` entries `CT-DET-02` puts outside a verdict
    distribution; and ``surface_correlations``/``subgroup_correlations``,
    the measured channels #116's precedent fixed — the correlations are
    the pipeline's measurement, and this module owns their interpretation.

    All state is underscore-prefixed: the instance's public surface is the
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
        cohort_id: str | None = None,
        evaluation_modes: Mapping[str, str] | None = None,
        surface_correlations: Mapping[str, Mapping[str, float]] | None = None,
        subgroup_correlations: Mapping[str, Mapping[str, float]] | None = None,
    ) -> None:
        self._labels = list(labels)
        self._scoring_models = dict(scoring_models or {})
        self._population_scopes = list(population_scopes or [])
        self._backend_profiles = list(backend_profiles or [])
        self._band_counts = dict(band_counts or {})
        self._administration_id = administration_id
        self._cohort_id = cohort_id
        self._evaluation_modes = dict(evaluation_modes or {})
        self._surface_correlations = {
            criterion: dict(features)
            for criterion, features in (surface_correlations or {}).items()
        }
        self._subgroup_correlations = {
            criterion: dict(features)
            for criterion, features in (subgroup_correlations or {}).items()
        }

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

    #: The MVVP member (#116), defined at module level and bound here — see
    #: ``run_mvvp`` above.
    run_mvvp = run_mvvp

    #: The four comparisons and the alert surface (#117), defined at module
    #: level and bound here — see each above. The same require-name reaches
    #: the same function whether the caller goes through the module or the
    #: instance, which is what the contract vocabulary's ``require`` binds.
    compression_check = compression_check
    surface_proxies = surface_proxies
    routing_policy_validity = routing_policy_validity
    drift_check = drift_check
    alerts = alerts

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
    cohort_id: str | None = None,
    evaluation_modes: Mapping[str, str] | None = None,
    surface_correlations: Mapping[str, Mapping[str, float]] | None = None,
    subgroup_correlations: Mapping[str, Mapping[str, float]] | None = None,
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
    (`CT-REVIEW-10`'s keying).

    #117's members read three more: ``cohort_id=`` declares the cohort the
    labels belong to (so a report naming a different cohort is refused),
    ``evaluation_modes=`` declares each criterion's mode — the declaration
    `CT-DET-02` makes binding for a verdict distribution — and
    ``surface_correlations=``/``subgroup_correlations=`` are the measured
    channels the proxy interpretation reads, declared by the caller exactly
    as the MVVP's channels are (#116's pattern)."""
    return ValidationStats(
        labels,
        scoring_models=scoring_models,
        population_scopes=population_scopes,
        backend_profiles=backend_profiles,
        band_counts=band_counts,
        administration_id=administration_id,
        cohort_id=cohort_id,
        evaluation_modes=evaluation_modes,
        surface_correlations=surface_correlations,
        subgroup_correlations=subgroup_correlations,
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
    # The cohort binding travels with the labels: an instance that read one
    # cohort's rows must refuse a report naming any other (CT-STATS-C18's
    # boundary, enforced at the report rather than by convention). Where no
    # cohort was named the instance holds every cohort's rows and binds none.
    return ValidationStats(labels, cohort_id=cohort_id)