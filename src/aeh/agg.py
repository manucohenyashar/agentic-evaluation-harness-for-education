"""M-AGG — the aggregation core: median band, the single band→points mapping and
ordinal α (detailed-design.md §3.12; issue #91).

A panel's verdicts become one criterion score in three pure steps, in this order
and no other (`FR-AGG-01`, `FR-AGG-02`, R41):

1. **Aggregate on the ordinal band scale** — the score's band is the panel's
   **median band ordinal**, never a mean of bands and never a mean of points. The
   scale has no metric, so a mean of bands is meaningless, and a mean of points
   imported from bands is worse: it would produce a value no judge gave and no band
   describes (HLD §9.9's worked example: 3.33 from three verdicts of which none
   said it). The modal band and `band_spread` — the ordinal distance between the
   panel's lowest and highest valuations — are recorded beside the median (`FR-AGG-01`).
2. **Map once** — points are derived from the *aggregated* band through M-PKG's
   canonical `points_for_band`, exactly once, *after* aggregation. There is no code
   path that maps per-judge bands to points and averages them, and none may be
   added (`FR-AGG-02`, `NFR-AGG-02`, CT-AGG-02): the mapping is applied in exactly
   one place in the source, `aeh.pkg:points_for_band`, the only sanctioned reader
   of the band table's points (`CT-PKG-05`).
3. **Agree ordinally** — agreement is Krippendorff's α **with an ordinal metric**
   (`FR-AGG-04`), under the convention `tests/unit/agg/test_ordinal_alpha.py`
   declares (see `ordinal_alpha` below). A raw "2 of 3 agreed" count is never the
   agreement figure.

Everything here is a pure function — no store access, no model call, no clock, no
configuration read beyond the values passed in (`CT-AGG-01`, `NFR-AGG-01`). That
purity is what makes the whole confidence and escalation policy unit-testable
(NFR-ORCH-04) and what keeps this module's write set empty (`CT-AGG-11`): the
caller owns the transaction; this module returns a value.

**The four seams** (CLAUDE.md code conventions), for what this module adds:

1. *Headless driver* — `aggregate`/`ordinal_alpha`/`describe_agreement` are plain
   code-level entry points; nothing here requires the console or a run.
2. *Deterministic transport* — the module takes on **no external dependency**:
   no network, no store, no clock. There is nothing to fake, which is the point
   of keeping M-AGG pure.
3. *Env-gated knobs* — nothing here reads the environment (`CT-AGG-01`): the
   thresholds, caps and multipliers the design names (`AGG_AUTO_THRESHOLD_*`,
   `AGG_CAP_TABLE`, the multipliers) are **module constants as production
   defaults**, and every one of them arrives injected at the call —
   `aggregate(..., config=...)` — so a different environment or a test tunes by
   passing values, never by reaching for `os.environ` (Q-04: injected as
   configuration, never test literals).
4. *Stage-level observability* — `CriterionScore` carries every stage's output as
   a named field next to the result: the panel's size (`judge_count`), the chosen
   band (`band`/`ordinal`), the mapped value (`points`), the modal band
   and spread, the agreement figure with its degeneracy marker, and the band
   histogram the aggregation stage saw (`CT-AGG-15`'s per-criterion band
   histogram). Nothing is folded into a bare status.

Design interpretations this implementation commits to (recorded for review, the
det.py precedent):

- **The α convention** (the design's own `TBD`, resolved the only way the test
  plan's differential can hold): α = 1 − D_o / D_e, where D_o is the mean
  pairwise ordinal distance among the panel's valuations and D_e is the mean
  pairwise ordinal distance over all ordered pairs of *distinct declared bands*
  of the criterion — a property of the criterion alone, identical for two panels
  of equal shape, so the differential is carried entirely by D_o. Distances are
  normalized `|i − j| / (K − 1)` over the criterion's declared band scale. See
  `ordinal_alpha`.
- **The modal tie-break** (the design pins none; `TC-AGG-02`'s declared
  assumption makes it #91's to declare): among bands tied for the mode, the band
  whose ordinal is **closest to the median band's ordinal** wins; still tied, the
  lower ordinal wins. The modal band is always one the panel actually gave — the
  tie-break only ever chooses *among* the tied bands, never outside the
  histogram.
- **The degeneracy marker**: `agreement_degenerate` is True exactly when the
  criterion's band scale has fewer than three bands — the two-band case
  (`CT-AGG-17`), where the ordinal and nominal metrics coincide and a unanimous
  panel yields α = 1 by construction. The figure is still returned (the number is
  the promise; the marker is the honesty — `TC-AGG-19`).
- **Single-verdict panels** aggregate honestly (the panel's own band, spread 0,
  judge_count 1) and carry `agreement = None`: with no pairs, ordinal α is
  *undefined*, and `CT-AGG-04` forbids a substitute number. The confidence prior
  for a single judge is #92's surface and is not pretended here.
- **An empty verdict list is a programming error** and raises `EmptyVerdictsError`
  before anything else is looked at (`CT-AGG-12`) — never a zero, a lowest band,
  or a null score. An even panel raises `EvenPanelError` (`FR-AGG-03`): a failed
  computation, not a rounded verdict — the store's odd-`judge_count` CHECK
  (`det` migration v9) is the second half of that refusal, and this module never
  hands it an even row.

Scope: #91 landed the aggregation core above plus `describe_agreement`, the
module's own honest description of an agreement figure (`CT-STATS-21`'s M-AGG
consumer limb). #92 landed the confidence surface on that core: the integrity
inversion (`FR-AGG-05`, ADR-10 — a cap is a `min`, never a penalty term, so
unanimity cannot outrun bad evidence), the four integrity inputs recorded on
the score row (`FR-AGG-13`), the from-the-row-alone re-derivation
(`recompute_confidence`, `NFR-AGG-04`), and the cohort migration that carries
the columns. #93 completes the module: the closed routing set with the
`triage`/`queued` split (`FR-AGG-07` — an ingestion-caused state is the
operator's rescan, never a teacher's marking decision), the four score states
assigned per cause with the breaker's `ungradeable_by_panel` (`FR-AGG-11`),
the two-verdict discard composed with `EvenPanelError` (`FR-AGG-12` — the
module never adjudicates between two), the deterministic pass-through
(`FR-AGG-10`), and the escalation policy `should_escalate` (`FR-AGG-08/09`):
observable signals only, model self-confidence one weighted input and never
the sole trigger (R22's failure mode), one judge to three and never to two.
The decision is returned to `M-ORCH`, which enqueues (`FR-ORCH-09`) — this
module imports no orchestrator and offers no enqueue; the dependency stays
one-way. The write set is unchanged and stays empty of SQL (`CT-AGG-11`):
every value here is returned for the caller's transaction, so `M-AGG` has no
write path to `narrative` and none to anything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Sequence

from aeh.pkg import PackageError, points_for_band
from aeh.store import (
    Migration,
    Statement,
    Tier,
    TIER_MIGRATIONS,
)

__all__ = [
    "AGG_AUTO_THRESHOLD_ATOMIC",
    "AGG_AUTO_THRESHOLD_HOLISTIC",
    "AGG_CAP_TABLE",
    "AGG_ESCALATION_ANOMALY_SIGMA",
    "AGG_ESCALATION_OVERRIDE_RATE",
    "AGG_ESCALATION_NO_DATA_WEIGHT",
    "AGG_ESCALATION_SELF_CONFIDENCE_WEIGHT",
    "AGG_ESCALATION_SIGNAL_WEIGHT",
    "AGG_ESCALATION_THRESHOLD",
    "AGG_HOLISTIC_MULTIPLIER",
    "AGG_UNCITED_MULTIPLIER",
    "AggregateError",
    "CriterionEscalationRank",
    "CriterionScore",
    "EmptyVerdictsError",
    "EscalationDecision",
    "EvenPanelError",
    "aggregate",
    "describe_agreement",
    "ordinal_alpha",
    "rank_criteria_for_escalation",
    "recompute_confidence",
    "should_escalate",
]


# --- errors ----------------------------------------------------------------------------------------


class AggregateError(Exception):
    """Base class for the aggregation refusals, so callers can catch the module's
    own failures without catching the package's too."""


class EmptyVerdictsError(AggregateError, ValueError):
    """An aggregation over an empty verdict set (`CT-AGG-12`).

    A programming error, raised: it is never a zero, a lowest band, or a null
    score. Distinct from `EvenPanelError` because the design refuses the two on
    different clauses — an empty panel is a caller bug (`CT-AGG-12`), an even
    panel is a real panel the contract refuses to adjudicate (`FR-AGG-03`).
    """


class EvenPanelError(AggregateError, ValueError):
    """An aggregation whose `judge_count` is even (`FR-AGG-03`).

    An even panel is a failed write, not a rounded verdict: the median ordinal of
    an even panel is a choice between two bands, and any tie-break would be a
    hidden thumb on the scale (HLD §9.9). The `criterion_score.judge_count` CHECK
    (`judge_count = 0 OR judge_count % 2 = 1`, det migration v9) enforces the same
    refusal at the store, which is what makes this a *failed write* rather than a
    convention (`CT-STORE-13`).
    """


# --- #92: the confidence surface's declared constants (§3.12) ---------------------------------------
#
# Production defaults, declared here and injected at the call (`config=`): the
# policy reads no configuration beyond the values passed in (`CT-AGG-01`), so
# these constants are what a `config=None` call uses — never a second reading
# path. The numbers are §3.12's Assumption-numbered cap table and thresholds:
# fixture data in the tests (Q-04), production defaults here.

#: Auto-accept threshold for an atomic criterion (§3.12: auto-accept iff
#: `confidence >= auto_threshold_for(scoring_model)`).
AGG_AUTO_THRESHOLD_ATOMIC: float = 0.80
#: Auto-accept threshold for a holistic criterion — a holistic panel is held to
#: the higher bar §3.12 names.
AGG_AUTO_THRESHOLD_HOLISTIC: float = 0.90
#: §3.12's multiplier applied to the base when any verdict is uncited.
AGG_UNCITED_MULTIPLIER: float = 0.80
#: §3.12's multiplier applied to the base for a holistic criterion.
AGG_HOLISTIC_MULTIPLIER: float = 0.85
#: §3.12's Assumption cap table: the hard ceiling each adverse integrity signal
#: puts on the confidence. ADR-10's whole point lives in how these are applied:
#: a cap is a `min`, never a penalty term, so no amount of panel agreement can
#: lift the figure past the worst adverse signal (R19). A signal reading
#: `None` — "not measured" — is adverse, fail-closed, and binds the same cap.
AGG_CAP_TABLE = MappingProxyType({
    "spans_verified": 0.25,
    "evidence_present": 0.25,
    "sufficiency_flag": 0.25,
    "ocr_overlap_risk": 0.30,
    "described_evidence": 0.50,
    "extractor_disagreement": 0.40,
})

#: The favourable polarity of each signal — the value meaning "nothing wrong"
#: (§3.12): `spans_verified` and `evidence_present` are favourable when True;
#: the other four are favourable when False (e.g. `ocr_overlap_risk = False` is
#: no overlap risk). Any other value — the opposite boolean, or `None` = "not
#: measured" — is adverse, fail-closed. One map, so the adverse reading is
#: computed from ONE definition everywhere (the test vocabulary's `FAVOURABLE`
#: precedent, mirrored here as production data).
#:
#: §3.12's cap table declares one cap conditional — `evidence_present` binds
#: only where "evidence is required". The criterion expresses that through
#: `evidence_required` (M-PKG's citation-requiring reading); a criterion that
#: does not declare the flag is read as requiring evidence — fail-closed: the
#: cap can bind, never be skipped by an omission.
_AGG_FAVOURABLE = MappingProxyType({
    "spans_verified": True,
    "evidence_present": True,
    "sufficiency_flag": False,
    "ocr_overlap_risk": False,
    "described_evidence": False,
    "extractor_disagreement": False,
})

#: The four integrity inputs `FR-AGG-13` records on the score row — the inputs
#: `recompute_confidence` can re-apply from stored data. `described_evidence`
#: and `extractor_disagreement` are read at aggregation time but are NOT among
#: FR-AGG-13's recorded fields, so a confidence they capped is not fully
#: re-derivable from the row (the design's own four-field list; the residual is
#: disclosed on `recompute_confidence`).
_RECORDED_SIGNAL_FIELDS: tuple[str, ...] = (
    "spans_verified",
    "evidence_present",
    "sufficiency_flag",
    "ocr_overlap_risk",
)


# --- #93: the escalation policy's declared constants (§3.12, §3.8) ----------------------------------
#
# The design pins the SHAPE of the escalation decision — observable signals,
# self-confidence weighted but never authoritative — and records the weights
# themselves as a `TBD`: "whether the escalation policy weights over observable
# signals are fixed constants at Phase 1 or fitted against the accumulated label
# store from Phase 2 ... Phase 1 ships fixed weights" (§3.8). These are those
# fixed Phase-1 weights: production defaults declared here and injected at the
# call (`should_escalate(..., config=...)`), the same shape as the confidence
# surface's — the policy reads no configuration beyond the values passed in
# (`CT-AGG-01`), never the environment. The numbers are Assumption-class, the
# same standing §3.12's cap table has, and R22's whole point lives in their
# RATIOS, not their absolute scale: every observable signal weighs a full
# `AGG_ESCALATION_SIGNAL_WEIGHT`, the decision fires at
# `AGG_ESCALATION_THRESHOLD`, and self-confidence's largest possible
# contribution — its weight times the full sweep of its range — stays strictly
# below that threshold. That inequality is the "never the sole trigger"
# requirement made structural rather than accidental: no value a model reports
# about itself can cross the line alone, under any tuning that keeps the
# inequality.

#: The concern level at which `should_escalate` decides to escalate. Each
#: observable signal carries `AGG_ESCALATION_SIGNAL_WEIGHT` when it fires, so
#: any one of them alone reaches the threshold; self-confidence cannot.
AGG_ESCALATION_THRESHOLD: float = 1.0
#: The weight of one fired observable signal (§3.12/§7.1's enumeration:
#: interior band position, adverse integrity signals, uncited verdict,
#: transcription overlap, criterion override history, distributional anomaly).
AGG_ESCALATION_SIGNAL_WEIGHT: float = 1.0
#: The weight an unmeasured override history contributes (CT-STATS-09: a
#: criterion nobody has reviewed is not a criterion nobody disagrees with —
#: "no data" is not a zero). Deliberately below the threshold: a fresh
#: criterion with no history draws attention in the ranking
#: (`rank_criteria_for_escalation`) but does not escalate on absence alone.
AGG_ESCALATION_NO_DATA_WEIGHT: float = 0.5
#: The weight of model self-confidence — ONE weighted input (FR-AGG-08). It
#: enters as `weight × (1 − self_confidence)`, clamped to the weight's own
#: ceiling: at the most self-doubting report possible it adds the full weight,
#: and `weight < AGG_ESCALATION_THRESHOLD` is what makes it structurally
#: incapable of triggering alone (R22: a model's own certainty is the least
#: reliable signal available).
AGG_ESCALATION_SELF_CONFIDENCE_WEIGHT: float = 0.25
#: How many standard deviations from the package's expected band position
#: counts as a distributional anomaly (§3.12's "distributional anomaly against
#: the package baseline"; the design names no k — declared here, the
#: α-convention precedent).
AGG_ESCALATION_ANOMALY_SIGMA: float = 2.0
#: The override rate above which the criterion's own history counts as an
#: escalation signal — "more than half of its reviewed scores were overridden",
#: the same strict reading the criterion breaker takes (CT-ORCH-16). The design
#: names no rate; declared here so the knob is injectable with the rest
#: (`should_escalate(..., config=...)`), never hard-coded at the call.
AGG_ESCALATION_OVERRIDE_RATE: float = 0.5


# --- the score -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionScore:
    """One aggregated criterion score — the value §3.14's `apply_policy` consumes.

    The shipped `criterion_score` columns (det migration v9: band, points,
    judge_count, agreement, state, routing) plus `FR-AGG-01`'s recorded modal band
    and spread, the degeneracy marker `CT-AGG-17`/`TC-AGG-19` require, the
    aggregation stage's histogram, and #92's confidence surface: the figure, the
    pre-cap base it was computed from, its routing, and the four integrity inputs
    `FR-AGG-13` records so the figure is reconstructible from the stored row
    alone (`NFR-AGG-04`). The defaults exist only for constructions that predate
    a field; `aggregate` always fills every field.
    """

    criterion_id: str
    band: str
    ordinal: int
    #: The mapped value. `None` only on a deterministic pass-through row whose
    #: unresolved selection never mapped one (FR-DET-03) — the panel path always
    #: maps exactly once (FR-AGG-02).
    points: float | None
    modal_band: str
    band_spread: int
    judge_count: int
    agreement: float | None
    agreement_degenerate: bool
    #: The panel's band histogram, in the criterion's own band order — the
    #: aggregation stage's observability (`CT-AGG-15`'s per-criterion band
    #: histogram, surfaced on the result rather than folded into a status).
    histogram: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    #: #92 (`FR-AGG-05`, ADR-10): the confidence figure — the base (the panel's
    #: own α for three or more judges, the band-position prior for one) with the
    #: design's multipliers applied and each adverse integrity signal's hard cap
    #: taken as a `min`. `None` is never produced by `aggregate`; the default
    #: exists for constructions that predate the field.
    confidence: float | None = None
    #: What the caps consumed: the post-multiplier, pre-cap base. Recorded
    #: beside `agreement` because the two are different figures — `agreement`
    #: is α on the criterion's declared scale (#91's convention), the base is
    #: α on the panel's own inferred scale (§3.12's `base = ordinal_alpha(verdicts)`),
    #: and the two diverge exactly when the panel never reached the declared
    #: top band. Recorded on the row (cohort migration v16) so the confidence
    #: is re-derivable from stored data alone.
    confidence_base: float | None = None
    #: The closed routing set (`FR-AGG-07`, `CT-AGG-06`): `auto` — the
    #: confidence met the scoring model's threshold; `queued` — the TEACHER's
    #: review queue, panel disagreement below the threshold; `provisional` — a
    #: single-judge band (or a score under a tripped criterion breaker), never
    #: auto-accepted; `reviewed` — a reviewer has acted, M-REVIEW's to write;
    #: `triage` — the OPERATOR's queue, for unresolved-selection and
    #: ingestion-caused states only. `reviewed` is the one value this module
    #: never assigns: it names a review that has happened.
    routing: str = "queued"
    #: The score's state, naming the cause (`FR-AGG-11`, `CT-AGG-07`):
    #: `final` — a full panel's settled aggregation; `provisional_unreviewed` —
    #: a single-judge band awaiting its panel; `ungradeable_by_panel` — the
    #: criterion's `M-ORCH` circuit breaker tripped (consumers surface it, never
    #: treat it as an ordinary provisional); `unresolved_selection` — M-DET's
    #: unresolved selection, arriving routed `triage`.
    state: str = "final"
    #: #93 (seam 4): what this module did to produce the score, in order — the
    #: cause markers for the two-verdict discard, the single-judge provisional,
    #: the breaker mark and the deterministic pass-through. Clauses carry the
    #: FR id that required them, so a consumer reading the row alone can tell a
    #: discarded second verdict from a never-run one.
    notes: tuple[str, ...] = ()
    #: The four recorded integrity inputs (`FR-AGG-13`), passed through exactly
    #: as received — including `None` ("not measured"), which is adverse
    #: fail-closed wherever the figure is consumed. Recorded so the confidence
    #: is answerable from stored data alone.
    spans_verified: Any = None
    evidence_present: Any = None
    sufficiency_flag: Any = None
    ocr_overlap_risk: Any = None


# --- the aggregation -------------------------------------------------------------------------------


def _band_row(row: Any, field_name: str) -> Any:
    """A band row's field, whether the row is a store mapping (M-PKG's catalog
    cache) or the declared band value the criterion carries (`CT-PKG-04`)."""
    if isinstance(row, dict):
        return row[field_name]
    return getattr(row, field_name)


def _band_by_ordinal(criterion: Any, ordinal: int) -> Any:
    """The criterion's declared band carrying `ordinal` — bands are unique by
    ordinal (`CT-PKG-04`: ordered ascending), so the scan is exact."""
    for row in criterion.bands:
        if _band_row(row, "ordinal") == ordinal:
            return row
    raise PackageError(
        f"criterion {criterion.criterion_id!r} declares no band at ordinal {ordinal!r}."
    )


def ordinal_alpha(verdicts: Sequence[Any], criterion: Any = None) -> float | None:
    """Krippendorff's α with the **ordinal metric** (`FR-AGG-04`, `CT-AGG-04`).

    The design requires the ordinal metric but records a `TBD`: the textbook
    coincidence-matrix α is degenerate here, because a criterion's panel is a
    **single unit** — over one unit, observed and expected disagreement are the
    same pair population, so the textbook α collapses to 0 for any disagreeing
    panel and 1 for a unanimous one, under *any* per-pair distance. No convention
    built on the observed marginal alone can satisfy the plan's requirement that
    adjacent-band disagreement score **higher** than distant disagreement at
    equal raw agreement. The convention this module commits to is the one that
    can, and it is the one `tests/unit/agg/test_ordinal_alpha.py` pins by hand:

        alpha  = 1 - D_o / D_e
        D_o    = mean pairwise distance among the panel's valuations
        delta  = |i - j| / (K - 1)     over the criterion's *declared* band scale
        D_e    = mean pairwise distance over all ordered pairs of distinct
                 declared bands

    `D_e` is a property of the criterion alone, so two panels of equal raw
    agreement differ only through `D_o` — which is exactly the differential the
    requirement is: a `[B0, B1, B1, B1, B2]` panel and a `[B0, B1, B1, B1, B3]`
    panel agree at the same raw rate (3 of 5 modal, three agreeing and seven
    disagreeing pairs of ten) and score 0.52 against 0.28 on the four-band scale.

    Returns `None` where α is **undefined** rather than a substitute number
    (`CT-AGG-04`): fewer than two verdicts (no pairs), or a scale with fewer than
    two declared bands carrying actual disagreement (`D_e` would be zero). A
    unanimous panel is *defined*, not degenerate-by-absence: D_o = 0 gives α = 1
    exactly — including the two-band case, where the design's `TBD` pins α = 1
    **by construction** (`TC-AGG-19`) and the score carries
    `agreement_degenerate` so no consumer renders that 1 as if it were
    information (`CT-AGG-17`) — and including the criterion-free call on a panel
    whose valuations all sit at one ordinal, where the inferred scale is one
    band and unanimity is still defined.

    When `criterion` is omitted the declared scale is inferred from the panel's
    own highest ordinal (`K = max(ordinal) + 1`) — the reading a caller can take
    holding nothing but the verdicts. `aggregate` always passes the criterion, so
    every score row's agreement is computed on the full declared scale.

    The convention bounds nothing below: unlike `aggregate`, this function does
    not refuse an even panel, and a panel spread across the full scale (or using
    ordinals outside any declared scale) can score below −1. Only the
    fewer-than-two and one-band cases are `None`; callers needing a figure from
    a legal panel should route through `aggregate`, whose odd panels stay within
    the familiar range on a declared scale.
    """
    if len(verdicts) < 2:
        return None
    ordinals = [_verdict_ordinal(v) for v in verdicts]

    # A unanimous panel is *defined*, not degenerate-by-absence: D_o = 0 gives
    # α = 1 exactly — under any scale, including a criterion-free call whose
    # inferred scale holds a single distinct value (every verdict at ordinal 0,
    # where `D_e` would be undefined but is never needed: 1 − 0/D_e = 1 for any
    # positive D_e). Checked BEFORE the scale test below, which is the order the
    # docstring already promises ("a unanimous panel is defined, not
    # degenerate-by-absence: D_o = 0 gives α = 1 exactly") and the order the
    # TC-AGG-10 property's no-cap cell relies on when it calls this function
    # criterion-free and asserts α is defined for any pairable panel (#92).
    if len(set(ordinals)) == 1:
        return 1.0

    if criterion is not None:
        band_count = int(criterion.band_count)
    else:
        band_count = max(ordinals) + 1
    if band_count < 2:
        return None  # D_e is undefined on a one-band scale; refuse a substitute.

    scale = band_count - 1

    # D_o: the mean pairwise distance among the panel's valuations. Equal-valued
    # pairs contribute 0 and still count in the mean — a panel of three judges is
    # six ordered (three unordered) comparisons, not the two that disagree.
    pair_distance_total = 0
    for i in range(len(ordinals)):
        for j in range(i + 1, len(ordinals)):
            pair_distance_total += abs(ordinals[i] - ordinals[j])
    pair_count = len(ordinals) * (len(ordinals) - 1) // 2
    observed = pair_distance_total / pair_count / scale

    # D_e: the mean pairwise distance over all ORDERED pairs of distinct declared
    # bands — the expected disagreement of the declared instrument itself.
    expected_total = sum(
        abs(a - b) for a in range(band_count) for b in range(band_count) if a != b
    )
    expected = (expected_total / scale) / (band_count * (band_count - 1))

    return 1.0 - observed / expected


def _verdict_ordinal(verdict: Any) -> int:
    """One judge's band ordinal (`CT-JUDGE`: each judge names a declared band with
    an ordinal, and carries no mapped value of its own — M-JUDGE validated it
    before here)."""
    return int(verdict.ordinal)


def _verdict_cited(verdict: Any) -> bool:
    """Whether one judge's verdict cites its evidence (§3.12: "uncited verdicts
    arrive marked" — M-JUDGE marks them, so the absence of a mark is not
    evidence of absence: an unmarked verdict is read as cited).

    `cited` is the declared field (the test vocabulary's shape); `cited_spans`
    is the consumer-constructed shape the `#76` file reconciled (an uncited
    verdict carries no spans). Absent both, the verdict is read as cited — the
    mark is the signal, and this module does not invent one.
    """
    cited = getattr(verdict, "cited", None)
    if cited is not None:
        return bool(cited)
    spans = getattr(verdict, "cited_spans", None)
    if spans is not None:
        return bool(spans)
    return True


def _signal_adverse(value: Any, favourable: bool) -> bool:
    """Whether one integrity signal's value is adverse (fail-closed, §3.12).

    `None` means "not measured" — no second extraction ran, the span check did
    not fire — and is adverse, never favourable and never absent (CT-INTEG-02's
    reading: a consumer that collapses `None` into `False` reads "not measured"
    as "measured, and agreed", the equivalence the clause names wrong by name).
    Otherwise the value is adverse exactly when it is not the signal's
    favourable polarity (`_AGG_FAVOURABLE`).
    """
    if value is None:
        return True
    return bool(value) != favourable


def _band_position_prior(ordinal: int, band_count: int) -> float:
    """§3.12's single-judge base — `prior_for_band_position(band, criterion)` —
    under the design's one declared property: "extreme bands score higher".

    The design names the shape and no numbers; this implementation declares them
    (the α-convention precedent, recorded for review): the prior rises linearly
    with how far the named band sits from the scale's centre, from 0.50 at the
    centre to 0.75 at an extreme. A single judge who named an extreme band has
    placed the work at the scale's edge with no panel to contradict them; the
    figure tops out below the atomic auto-accept threshold (0.75 < 0.80), which
    is the property the shape wants: one judge's word alone, however placed, is
    never sufficient to auto-accept. The figure never exceeds 1.0 — the
    single-judge domain bound TC-AGG-10's no-cap cell pins.
    """
    bands = int(band_count)
    if bands <= 1:
        # One declared band: the panel is unanimous on it by construction
        # (unreachable per CT-PKG-04's band_count >= 2, kept for honesty).
        return 1.0
    center = (bands - 1) / 2
    extremity = 2.0 * abs(int(ordinal) - center) / (bands - 1)
    return 0.50 + 0.25 * extremity


def _confidence_base(verdicts: Sequence[Any], criterion: Any) -> float:
    """§3.12's base figure: `base = ordinal_alpha(verdicts)` for a panel of
    three or more judges; the band-position prior for a single judge.

    The α term is computed **without** the criterion — §3.12's literal form —
    so the base is a property of the panel's own scale. For a panel whose
    valuations never reach the declared top band, the inferred scale is smaller
    than the declared one and the inferred α is the SMALLER figure
    (α = 1 − 3·D̄/(K+1) grows with K), which is exactly the reading TC-AGG-10's
    no-cap cell pins as its ceiling: the confidence never exceeds the panel's
    own α. The score's `agreement` field stays α on the DECLARED scale (#91's
    convention), so the base is recorded beside it (`confidence_base`) rather
    than conflated with it.
    """
    if len(verdicts) >= 3:
        return ordinal_alpha(verdicts)
    return _band_position_prior(_verdict_ordinal(verdicts[0]), criterion.band_count)


def aggregate(
    verdicts: Sequence[Any],
    criterion: Any,
    signals: Any,
    *,
    config: Any = None,
    fallback: bool = False,
    breaker_tripped: bool = False,
    deterministic_score: Any = None,
) -> CriterionScore:
    """Aggregate a panel's verdicts into one criterion score (`FR-AGG-01/02/03/04`)
    with its confidence (`FR-AGG-05`, `FR-AGG-13`, `NFR-AGG-04`), its routing
    and its state (`FR-AGG-07/10/11/12`).

    Pure (`CT-AGG-01`): the verdicts, the criterion's declared band set, the
    integrity signals and the configuration are values; nothing here reads a
    store, a clock, or any configuration beyond its arguments — `config` is
    `None` (the module constants above are the production defaults) or a value
    carrying any of `auto_threshold_atomic`, `auto_threshold_holistic`,
    `uncited_multiplier`, `holistic_multiplier` and `caps` (a mapping from each
    of the six signal names to its hard cap; absent it entirely, `AGG_CAP_TABLE`
    applies).

    The aggregation is the **median band ordinal**, mapped to points exactly
    once through M-PKG's canonical `points_for_band` (`CT-PKG-05`,
    `NFR-AGG-02`) — never a mean of bands, never a mean of points, and never a
    per-judge average (RISK-05).

    The confidence (`FR-AGG-05`, ADR-10) is §3.12's computation in three steps:

    1. **Base** — the panel's own agreement figure (`ordinal_alpha(verdicts)`,
       criterion-free) for a panel of three or more; the band-position prior
       for a single judge ("extreme bands score higher").
    2. **Multipliers** — `× uncited_multiplier` when any verdict is uncited,
       `× holistic_multiplier` for a holistic criterion. Multipliers shape the
       base; they never touch a cap.
    3. **Caps** — each adverse integrity signal's cap is a hard `min` (ADR-10:
       a cap is a `min`, never a penalty term, so no amount of panel agreement
       can lift the figure past the worst adverse signal — R19). Fail-closed:
       `None` ("not measured") is adverse, never favourable, never absent, and
       binds the same cap as a measured-adverse value (`NFR-INTEG-03`); a
       signal with no entry in the injected table binds nothing. One cap is
       conditional (§3.12): `evidence_present` binds only where the criterion
       requires evidence — read fail-closed when the criterion does not
       declare the flag.

    Routing and state (`#93`) are assigned **per cause**, in precedence order —
    breaker, then panel size, then the threshold:

    * `breaker_tripped=True` — the criterion's `M-ORCH` circuit breaker tripped
      (`CT-ORCH-16`): the score is routed `provisional` and its state is
      `ungradeable_by_panel`. It is surfaced, never treated as an ordinary
      provisional, and never auto-accepted — no confidence can lift it.
    * a single-judge panel — routed `provisional`, state
      `provisional_unreviewed`: one judge's word awaits its panel
      (`FR-ORCH-13`'s "scored single-judge provisional"), never auto-accepted.
    * otherwise — `auto` iff `confidence >= auto_threshold_for(scoring_model)`
      (§3.12), else `queued`; state `final`.

    The four integrity inputs `FR-AGG-13` records are carried on the score
    exactly as received, beside the pre-cap base — the fields that make the
    figure reconstructible from the stored row alone (`recompute_confidence`).
    `notes` records what this call did, one clause per cause (`FR-AGG-12`'s
    discard, the single-judge mark, the breaker mark, the pass-through).

    The two marked alternative entries (`#93`):

    * `deterministic_score=` (`FR-AGG-10`) — an M-DET row judged without a
      panel (`judge_count` 0). It is its own entry and is checked first,
      because an empty panel is exactly how such a row arrives. The row is
      **echoed, never re-aggregated**: band, points, ordinal, judge_count,
      agreement and the recorded signals are carried as received, and
      `routing`/`state` are taken off the row (`unresolved_selection` arrives
      routed `triage`), with `auto`/`final` as the fallbacks when a row omits
      them. A non-empty panel alongside a row is a contradictory call and
      raises `ValueError`.
    * `fallback=True` (`FR-AGG-12`) — the one even case with a declared
      fallback: a panel **left at exactly two** by an unrecoverable judge
      failure. The second verdict is discarded — never adjudicated between,
      since a tie broken by rule is a coin flip presented as a judgement
      (R48) — and the base single-judge band is kept, provisional. Any other
      even size still raises `EvenPanelError`; an odd panel aggregates
      normally regardless of the mark.

    An empty panel with no deterministic row raises `EmptyVerdictsError` (a
    programming error, `CT-AGG-12`); any other even panel raises
    `EvenPanelError` before any median is taken (`FR-AGG-03`).
    """
    # The deterministic pass-through (FR-AGG-10) is its own entry and is checked
    # first: an empty panel is exactly how a row judged without a panel arrives,
    # so this entry must come before the empty-panel refusal it is the marked
    # alternative to. A non-empty panel alongside a row is a contradictory call.
    if deterministic_score is not None:
        if len(verdicts) != 0:
            raise ValueError(
                "aggregate received both a verdict panel and a deterministic score — "
                "FR-AGG-10's entry is for rows judged without a panel; the two are "
                "never combined."
            )
        return _passthrough_score(deterministic_score, criterion)
    if len(verdicts) == 0:
        raise EmptyVerdictsError(
            "aggregate over an empty verdict set is a programming error (CT-AGG-12): "
            "it is never a zero, a lowest band, or a null score."
        )
    if len(verdicts) % 2 == 0:
        if fallback and len(verdicts) == 2:
            # The two-verdict discard (FR-AGG-12), composed with the even-panel
            # refusal: the ONE even case with a declared fallback — a panel left
            # at exactly two by an unrecoverable judge failure. The second
            # verdict is discarded, never adjudicated between: two judges whose
            # verdicts disagree is a coin flip a rule would present as a
            # judgement (R48). The base single-judge band is kept and the score
            # is provisional — never a rounded verdict, never a settled panel.
            single = aggregate(
                verdicts[:1],
                criterion,
                signals,
                config=config,
                breaker_tripped=breaker_tripped,
            )
            return replace(
                single,
                notes=single.notes
                + (
                    "second verdict discarded: panel left at two by an unrecoverable "
                    "failure — the base single-judge band is kept, never adjudicated "
                    "between the two (FR-AGG-12)",
                ),
            )
        raise EvenPanelError(
            f"a panel of {len(verdicts)} judges is even — an even panel is a failed "
            "write, not a rounded verdict (FR-AGG-03): escalate 1 → 3, never to 2. "
            "(A panel left at exactly two by an unrecoverable failure is the one "
            "fallback: mark it with fallback=True, FR-AGG-12.)"
        )

    ordinals = sorted(_verdict_ordinal(v) for v in verdicts)
    median_ordinal = ordinals[len(ordinals) // 2]
    median_row = _band_by_ordinal(criterion, median_ordinal)
    band = _band_row(median_row, "band")

    # The single mapping, applied once, after aggregation (`FR-AGG-02`): the
    # median band's points are a lookup through M-PKG's canonical function —
    # a lookup, not a computation — and there is deliberately no other place in
    # this module that reads a band's points.
    points = points_for_band(criterion.bands, band)

    counts: dict[int, int] = {}
    for ordinal in ordinals:
        counts[ordinal] = counts.get(ordinal, 0) + 1
    top = max(counts.values())
    # The declared tie-break: among bands tied for the mode, the one whose ordinal
    # is closest to the median band's; still tied, the lower ordinal. Always a band
    # the panel gave (`TC-AGG-02`'s declared assumption, declared at #91).
    modal_ordinal = min(
        (ordinal for ordinal, count in counts.items() if count == top),
        key=lambda ordinal: (abs(ordinal - median_ordinal), ordinal),
    )
    modal_band = _band_row(_band_by_ordinal(criterion, modal_ordinal), "band")

    band_spread = ordinals[-1] - ordinals[0]

    histogram = tuple(
        (_band_row(_band_by_ordinal(criterion, ordinal), "band"), counts[ordinal])
        for ordinal in sorted(counts)
    )

    # --- the confidence surface (#92) ------------------------------------------------------------
    # Configuration: `config=None` means the module constants; a `config` value
    # supplies any subset of the knobs, each defaulting to its constant. The
    # values are read through getattr with the constant as default, never from
    # the environment (`CT-AGG-01`).
    if config is not None:
        caps = getattr(config, "caps", None)
        atomic_threshold = getattr(config, "auto_threshold_atomic", AGG_AUTO_THRESHOLD_ATOMIC)
        holistic_threshold = getattr(
            config, "auto_threshold_holistic", AGG_AUTO_THRESHOLD_HOLISTIC
        )
        uncited_multiplier = getattr(config, "uncited_multiplier", AGG_UNCITED_MULTIPLIER)
        holistic_multiplier = getattr(config, "holistic_multiplier", AGG_HOLISTIC_MULTIPLIER)
    else:
        caps = None
        atomic_threshold = AGG_AUTO_THRESHOLD_ATOMIC
        holistic_threshold = AGG_AUTO_THRESHOLD_HOLISTIC
        uncited_multiplier = AGG_UNCITED_MULTIPLIER
        holistic_multiplier = AGG_HOLISTIC_MULTIPLIER
    cap_table = dict(AGG_CAP_TABLE) if caps is None else dict(caps)

    scoring_model = getattr(criterion, "scoring_model", "atomic")
    threshold = holistic_threshold if scoring_model == "holistic" else atomic_threshold

    # Step 1 — the base. Step 2 — the multipliers. A `None` base is impossible
    # here: a panel of three or more always pair (unanimity is defined; see
    # `ordinal_alpha`), and a single judge always has a prior.
    base = _confidence_base(verdicts, criterion)
    multiplier = 1.0
    if any(not _verdict_cited(v) for v in verdicts):
        multiplier *= uncited_multiplier
    if scoring_model == "holistic":
        multiplier *= holistic_multiplier
    confidence_base = base * multiplier

    # Step 3 — the caps. A cap is a `min`, never a penalty term (ADR-10): each
    # adverse signal's cap is a hard ceiling on the figure, taken in any order,
    # and unanimity cannot buy any of it back.
    confidence = confidence_base
    for signal_name, favourable in _AGG_FAVOURABLE.items():
        if not _signal_adverse(getattr(signals, signal_name, None), favourable):
            continue
        # §3.12's one conditional cap: `evidence_present` binds only where
        # evidence is required. A criterion that does not declare the flag is
        # read as requiring it — fail-closed (the cap can bind, never be
        # skipped by an omission).
        if signal_name == "evidence_present" and not getattr(
            criterion, "evidence_required", True
        ):
            continue
        cap = cap_table.get(signal_name)
        if cap is not None:
            confidence = min(confidence, float(cap))

    # --- #93: routing and state, assigned per cause (FR-AGG-07, FR-AGG-11) -------------------
    # Precedence is the cause's, not the confidence's: the breaker mark and the
    # single-judge construction both force `provisional` regardless of the
    # confidence figure — a capped-high number is still one judge's word or a
    # criterion the panel could not grade (CT-ORCH-16: consumers surface it,
    # never treat it as an ordinary provisional).
    notes: tuple[str, ...] = ()
    if breaker_tripped:
        routing = "provisional"
        state = "ungradeable_by_panel"
        notes += (
            "criterion breaker tripped: ungradeable_by_panel (FR-AGG-11, CT-ORCH-16)",
        )
    elif len(verdicts) == 1:
        # A single-judge band is provisional by construction (§3.12): it awaits
        # its panel — FR-AGG-09's escalation to three is M-ORCH's to enqueue —
        # and one judge's word alone is never sufficient to auto-accept.
        routing = "provisional"
        state = "provisional_unreviewed"
        notes += ("single-judge band: provisional by construction (FR-AGG-07, FR-AGG-11)",)
    else:
        routing = "auto" if confidence >= threshold else "queued"
        state = "final"

    return CriterionScore(
        criterion_id=criterion.criterion_id,
        band=band,
        ordinal=median_ordinal,
        points=points,
        modal_band=modal_band,
        band_spread=band_spread,
        judge_count=len(verdicts),
        agreement=ordinal_alpha(verdicts, criterion),
        agreement_degenerate=int(criterion.band_count) < 3,
        histogram=histogram,
        confidence=confidence,
        confidence_base=confidence_base,
        routing=routing,
        state=state,
        notes=notes,
        spans_verified=getattr(signals, "spans_verified", None),
        evidence_present=getattr(signals, "evidence_present", None),
        sufficiency_flag=getattr(signals, "sufficiency_flag", None),
        ocr_overlap_risk=getattr(signals, "ocr_overlap_risk", None),
    )


# --- the re-derivation: confidence from the stored row alone (`NFR-AGG-04`) ------------------------


def _row_value(row: Any, field: str) -> Any:
    """A tolerant read of one field off a stored score row.

    `row` is the stored `criterion_score` mapping — a `sqlite3.Row`, a `dict`,
    or a dataclass; the accessor is whichever the row answers to. A missing
    field reads as `None` ("not recorded"), which is exactly how the migration
    leaves every pre-existing row.
    """
    if isinstance(row, dict):
        return row.get(field)
    if hasattr(row, "keys"):
        try:
            return row[field] if field in row.keys() else None
        except (IndexError, KeyError):
            return None
    return getattr(row, field, None)


def _passthrough_score(row: Any, criterion: Any) -> CriterionScore:
    """Echo a deterministic M-DET row through as a score (`FR-AGG-10`).

    The row judged without a panel arrives **already scored** — M-DET mapped the
    band and its mapped value, or left it `NULL` for an unresolved choice — so
    this is an echo, never a re-aggregation: the module invents no band, maps no
    points, and derives no confidence. `routing`/`state` come from the row (an
    unresolved choice arrives routed `triage` — the OPERATOR queue, the same
    boundary `FR-INGEST-30`/`FR-CONSOLE-11` draw); `auto`/`final` are the
    fallbacks when a row omits them, not overrides. The one clause in `notes`
    marks the entry, so a consumer reading the row alone can tell a
    pass-through from a panel score.
    """
    band_name = _row_value(row, "band")
    if band_name is None:
        # A det row always names its band; an absent one is echoed as the empty
        # name rather than invented from the criterion.
        band_name = ""
    ordinal = _row_value(row, "ordinal")
    if ordinal is None and band_name:
        # No ordinal on the row: a lookup through the criterion's declared bands
        # by name — the same single source the panel path maps through.
        for declared in getattr(criterion, "bands", ()) or ():
            if _band_row(declared, "band") == band_name:
                ordinal = _band_row(declared, "ordinal")
                break
    points = _row_value(row, "points")
    judge_count = _row_value(row, "judge_count")
    agreement = _row_value(row, "agreement")
    band_spread = _row_value(row, "band_spread")
    histogram = _row_value(row, "histogram")
    return CriterionScore(
        criterion_id=_row_value(row, "criterion_id") or criterion.criterion_id,
        band=band_name if band_name is not None else "",
        ordinal=int(ordinal) if ordinal is not None else 0,
        points=None if points is None else float(points),
        modal_band=_row_value(row, "modal_band") or band_name or "",
        band_spread=int(band_spread) if band_spread is not None else 0,
        judge_count=int(judge_count) if judge_count is not None else 0,
        agreement=None if agreement is None else float(agreement),
        agreement_degenerate=int(getattr(criterion, "band_count", 0)) < 3,
        histogram=histogram if isinstance(histogram, tuple) else (),
        confidence=_row_value(row, "confidence"),
        confidence_base=_row_value(row, "confidence_base"),
        routing=_row_value(row, "routing") or "auto",
        state=_row_value(row, "state") or "final",
        notes=("deterministic score passed through unchanged (FR-AGG-10)",),
        spans_verified=_row_value(row, "spans_verified"),
        evidence_present=_row_value(row, "evidence_present"),
        sufficiency_flag=_row_value(row, "sufficiency_flag"),
        ocr_overlap_risk=_row_value(row, "ocr_overlap_risk"),
    )


def recompute_confidence(row: Any, criterion: Any, *, config: Any = None) -> float | None:
    """Re-derive a stored row's confidence from the stored row alone (`NFR-AGG-04`).

    The reconstruction contract: what `FR-AGG-13` records is enough. The four
    integrity inputs ride the row itself (`spans_verified`, `evidence_present`,
    `sufficiency_flag`, `ocr_overlap_risk` — each as received, `NULL` = not
    measured = adverse), and the pre-cap base rides `confidence_base`. So the
    figure is re-derived by replaying the same computation the aggregator ran,
    from fields a reader of the database can see:

    1. **Base** — `confidence_base` (the post-multiplier, pre-cap figure the
       aggregator consumed) when the row carries it; else `agreement` for a
       panel of three or more, exact whenever the panel touched the declared
       top band (where the criterion-free and criterion-declared alpha readings
       coincide); else the band-position prior for a single-judge row, from the
       row's own `ordinal`.
    2. **Caps** — the recorded signals' caps, fail-closed, as hard `min`s
       (ADR-10), exactly as `aggregate` applied them.

    `None` is returned, never zero, when the row cannot support a re-derivation:
    no panel (a deterministic row's `judge_count` is 0), an even panel (a failed
    write), or no base derivable at all. The four recorded signals cap the
    figure exactly as before; the two signals that are *not* recorded
    (`described_evidence`, `extractor_disagreement`) and the multipliers' inputs
    (the uncited mark) are the disclosed residual — a row whose stored
    confidence they capped or shaped re-derives higher than it was stored.
    `config` carries an injected cap table the same way `aggregate`'s does.
    """
    caps = getattr(config, "caps", None) if config is not None else None
    cap_table = dict(AGG_CAP_TABLE) if caps is None else dict(caps)

    judge_count = _row_value(row, "judge_count")
    if judge_count is None:
        return None
    judge_count = int(judge_count)
    # The HLD §9.6 constraint is also the re-derivation's: 0 or odd. A
    # deterministic row (judge_count 0) has no confidence to re-derive; an even
    # panel is a failed write, not a figure.
    if judge_count <= 0 or judge_count % 2 == 0:
        return None

    base = _row_value(row, "confidence_base")
    if base is None and judge_count >= 3:
        # Legacy rows predate the base column: the stored agreement is the
        # criterion-declared alpha reading, exact wherever the panel reached
        # the declared top band (the two readings coincide there — and for any
        # panel whose spread never leaves the declared scale's top band).
        base = _row_value(row, "agreement")
    if base is None and judge_count == 1:
        ordinal = _row_value(row, "ordinal")
        if ordinal is not None:
            base = _band_position_prior(int(ordinal), int(criterion.band_count))
    if base is None:
        return None

    confidence = float(base)
    for field in _RECORDED_SIGNAL_FIELDS:
        if not _signal_adverse(_row_value(row, field), _AGG_FAVOURABLE[field]):
            continue
        # The same conditional cap the aggregator applied (§3.12): the row's
        # `evidence_present` caps only where the criterion requires evidence,
        # read fail-closed when the criterion does not declare the flag.
        if field == "evidence_present" and not getattr(
            criterion, "evidence_required", True
        ):
            continue
        cap = cap_table.get(field)
        if cap is not None:
            confidence = min(confidence, float(cap))
    return confidence


# --- the agreement figure's own description --------------------------------------------------------


def describe_agreement(figure: Any, population: str) -> str:
    """The module's own description of an agreement figure (`CT-STATS-21`).

    M-AGG is one of the consumers the clause binds: a two-band criterion's α is
    **degenerate** — the ordinal and nominal metrics coincide there, so a
    unanimous panel yields 1.0 by construction and the number carries less
    information than it appears to (`CT-AGG-17`, RISK-30: undisclosed, it is the
    most confident number on the screen). The figure is still reported — the
    clause is a non-promise about interpretation, not a prohibition on
    measurement — but never presented as equivalent to a multi-band agreement.

    `figure` is the agreement figure's mapping (`ordinal_alpha`, `band_count`,
    `degenerate_band_shape`); `population` names the scope the figure was
    computed over. The text names the degeneracy on a line of its own, phrased as
    a limitation rather than an equivalence.
    """
    alpha = figure.get("ordinal_alpha") if isinstance(figure, dict) else figure.ordinal_alpha
    band_count = figure.get("band_count") if isinstance(figure, dict) else figure.band_count
    degenerate = (
        figure.get("degenerate_band_shape")
        if isinstance(figure, dict)
        else figure.degenerate_band_shape
    )

    if alpha is None:
        # A figure this module itself produces (a single-verdict score carries
        # no alpha) describes as undefined, not as a coerced number.
        lines = [
            f"Agreement for population {population}: Krippendorff's ordinal "
            f"alpha is undefined over {int(band_count)} bands."
        ]
    else:
        lines = [
            f"Agreement for population {population}: Krippendorff's ordinal alpha = "
            f"{float(alpha):.2f} over {int(band_count)} bands."
        ]
    if degenerate or int(band_count) < 3:
        lines.append(
            "Two-band degeneracy: on a two-band criterion the ordinal metric "
            "coincides with the nominal one, so this alpha carries less "
            "information than a multi-band figure, and a unanimous panel "
            "scores 1.0 by construction."
        )
    return "\n".join(lines)


# --- #93: the escalation policy (`FR-AGG-08/09`, §3.8) ----------------------------------------------
#
# The decision M-AGG returns to M-ORCH: whether a criterion score warrants a
# bigger panel, decided from OBSERVABLE signals — the row's interior band
# position, its recorded integrity inputs, the uncited mark, the criterion's
# override history, the distributional position against the package baseline —
# with model self-confidence one weighted input and structurally incapable of
# triggering alone (R22). The ENQUEUE the decision feeds is M-ORCH's
# (`FR-ORCH-09`): this module imports no orchestrator and offers no enqueue —
# the dependency stays one-way (`FR-AGG-14`).

#: A sentinel distinguishing "the row does not carry this field" from "the row
#: carries it as `None`". The escalation policy reads them differently — an
#: absent signal is no claim at all and its limb is skipped; a recorded `None`
#: is "measured, and inconclusive", which is adverse fail-closed wherever a
#: value is consumed (the `_signal_adverse` reading). The confidence surface
#: does not need the distinction (a row's recorded fields are always present,
#: `None`-valued or not); the escalation policy does, because it reads rows
#: both this module produced (all fields present) and stand-ins that name only
#: the fields their story varies.
_AGG_ABSENT = object()


def _row_field(row: Any, field: str) -> Any:
    """A tolerant read that distinguishes absent from `None` (see `_AGG_ABSENT`).

    The same accessor forms `_row_value` accepts — a mapping, a `sqlite3.Row`,
    an object — returning the `_AGG_ABSENT` sentinel where `_row_value` would
    return `None`, so a caller can tell "the row says nothing about it" from
    "the row recorded that it was not measured".
    """
    if isinstance(row, dict):
        return row[field] if field in row else _AGG_ABSENT
    if hasattr(row, "keys"):
        try:
            return row[field] if field in row.keys() else _AGG_ABSENT
        except (IndexError, KeyError):
            return _AGG_ABSENT
    return getattr(row, field, _AGG_ABSENT)


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
    odd-plan check) and `reasons`. A decision not to escalate carries the
    current panel depth unchanged and no reasons.
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

    # 1. Interior band position — the panel did not reach a scale edge.
    ordinal = _row_field(score, "ordinal")
    band_count = _row_field(score, "band_count")
    if band_count is _AGG_ABSENT:
        declared = getattr(criterion, "band_count", None)
        if declared is None:
            declared = len(getattr(criterion, "bands", ()) or ())
        band_count = declared if declared else _AGG_ABSENT
    if ordinal is not _AGG_ABSENT and ordinal is not None and band_count is not _AGG_ABSENT:
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
#
# M-AGG owns this migration because it owns the columns' meaning: the four
# integrity inputs ride the score row so the figure is reconstructible from
# stored data alone (`NFR-AGG-04`), and `confidence_base` carries what the caps
# consumed (the post-multiplier, pre-cap base) so the replay is exact rather
# than approximate. Every column is nullable: `NULL` = not recorded, which is
# how the migration leaves every pre-existing row, and the re-derivation reads
# `NULL` fail-closed — the same polarity the live signals carry. The stored
# booleans are constrained to 0/1-or-NULL (three-valued, like the signals
# themselves: `NULL` is neither favourable nor zero) — a real 0/1 with `NULL`
# allowed, not a fake third value.
#
# `state` and `routing` already exist (det migration v9's CHECK admits both
# `final` and `queued`, the two values this module's panel path writes);
# only the six columns #92 introduces are added here.

_AGG_CONFIDENCE_COLUMNS = Migration(
    version=16,
    name="agg_confidence_columns",
    statements=(
        Statement("ALTER TABLE criterion_score ADD COLUMN confidence REAL"),
        Statement("ALTER TABLE criterion_score ADD COLUMN confidence_base REAL"),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN spans_verified "
            "INTEGER CHECK (spans_verified IN (0, 1))"
        ),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN evidence_present "
            "INTEGER CHECK (evidence_present IN (0, 1))"
        ),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN sufficiency_flag "
            "INTEGER CHECK (sufficiency_flag IN (0, 1))"
        ),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN ocr_overlap_risk "
            "INTEGER CHECK (ocr_overlap_risk IN (0, 1))"
        ),
    ),
)

TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (_AGG_CONFIDENCE_COLUMNS,), key=lambda m: m.version
))
