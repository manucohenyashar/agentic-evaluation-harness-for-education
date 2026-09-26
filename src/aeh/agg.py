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

import json
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Sequence

from aeh.pkg import PackageError, points_for_band
from aeh.store import (
    Migration,
    MigrationError,
    MigrationPrecondition,
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
    "PanelCorrelationError",
    "aggregate",
    "AGG_STATEMENTS",
    "AggregationSignals",
    "aggregation_signals",
    "describe_agreement",
    "ordinal_alpha",
    "rank_criteria_for_escalation",
    "adverse_signal_count",
    "recompute_confidence",
    "write_score",
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


class PanelCorrelationError(AggregateError, ValueError):
    """A panel carrying two or more decision-engine verdicts (Jev design delta FR-AGG-18,
    CT-AGG-22). The decision engine answers identical input near-identically, so two of its
    verdicts in one panel would manufacture unanimity (alpha near 1) rather than measure it.
    The seat rule (CT-JUDGE-21) makes this unreachable; the refusal is what makes a future
    break of that rule fail loudly instead of auto-accepting. Not retryable; nothing is written.
    """

    retryable = False


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

#: The four integrity inputs recorded on every score row since cohort migration
#: v16 — the inputs `recompute_confidence` re-applies from any stored row.
_RECORDED_SIGNAL_FIELDS: tuple[str, ...] = (
    "spans_verified",
    "evidence_present",
    "sufficiency_flag",
    "ocr_overlap_risk",
)

#: `FR-AGG-13` amended (#360): the two signals `write_score` records beside the
#: four, so the stored row carries all six. They are re-applied only from a row
#: `write_score` wrote — one whose `caps_fired` is recorded — because an older
#: row's `NULL` in these columns means "column did not exist", not "not
#: measured", and reading it adverse would re-derive a figure lower than the one
#: that was stored.
_WRITTEN_SIGNAL_FIELDS: tuple[str, ...] = ("described_evidence", "extractor_disagreement")


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
    #: #360 (`FR-AGG-13` amended): the remaining two signals, passed through as
    #: received so `write_score` stores all six.
    described_evidence: Any = None
    extractor_disagreement: Any = None
    #: #360 (`FR-AGG-15`): the caps that bound, named by their `AGG_CAP_TABLE`
    #: key, in the table's order — an adverse signal whose cap sits below the
    #: pre-cap base, so the cap lowered the figure. Empty when none did.
    caps_fired: tuple[str, ...] = ()


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


def adverse_signal_count(row: Any) -> int:
    """How many of the row's stored integrity signals read adverse (`FR-REVIEW-18`).

    M-REVIEW's ranking input, computed HERE because the polarity that makes a signal
    adverse is declared here once (`_AGG_FAVOURABLE`) and a second copy in the ranker
    could disagree with the confidence the same row already carries.

    The field set follows `recompute_confidence`'s rule exactly: the four recorded since
    cohort v16, plus the two `write_score` adds only when the row's `caps_fired` is
    recorded. A `NULL` in `described_evidence` on a row without `caps_fired` means "this
    column did not exist when the row was written", not "not measured", and counting it
    adverse would rank an old row above a new one for having been written earlier.
    Within the selected fields `None` IS adverse, fail-closed, as everywhere else.
    """
    fields = _RECORDED_SIGNAL_FIELDS
    if _row_value(row, "caps_fired") is not None:
        fields = fields + _WRITTEN_SIGNAL_FIELDS
    return sum(
        1
        for field in fields
        if _signal_adverse(_row_value(row, field), _AGG_FAVOURABLE[field])
    )


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
    # FR-AGG-18: the only place aggregation reads a verdict's engine. Everything below is
    # engine-blind (FR-AGG-19, CT-AGG-23): a decision-engine verdict is a verdict.
    decision_verdicts = sum(
        1 for verdict in verdicts if _row_field(verdict, "scoring_engine") == "decision")
    if decision_verdicts > 1:
        raise PanelCorrelationError(
            f"aggregate refuses a panel carrying {decision_verdicts} decision-engine verdicts "
            f"(FR-AGG-18): two answers from one near-deterministic engine are one opinion "
            f"counted twice, never agreement (CT-JUDGE-21, CT-AGG-22)."
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
    caps_fired: list[str] = []
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
            if float(cap) < confidence_base:
                caps_fired.append(signal_name)

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
        described_evidence=getattr(signals, "described_evidence", None),
        extractor_disagreement=getattr(signals, "extractor_disagreement", None),
        caps_fired=tuple(caps_fired),
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
        band=band_name,
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
        described_evidence=_row_value(row, "described_evidence"),
        extractor_disagreement=_row_value(row, "extractor_disagreement"),
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
    figure exactly as before. A row `write_score` wrote (#360: its `caps_fired`
    is recorded) carries `described_evidence` and `extractor_disagreement` too,
    and their caps are re-applied the same way, so the residual `TC-AGG-C15`
    disclosed closes for such rows; an older row without them re-derives from
    the four. The multipliers' inputs (the uncited mark) ride `confidence_base`,
    which already has them applied.
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
    fields = _RECORDED_SIGNAL_FIELDS
    if _row_value(row, "caps_fired") is not None:
        fields = fields + _WRITTEN_SIGNAL_FIELDS
    for field in fields:
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


# --- the writer: the score row in the caller's transaction (FR-AGG-15, #360) ----------------------
#
# `aggregate` stays pure (`CT-AGG-01`); persisting its result is this one declared
# upsert, run in the transaction the caller opened (`CT-AGG-19`) so a score and
# whatever the caller writes beside it — the escalation it enqueues — land or
# vanish together. Keyed on the run-scoped key (#359), so a second write of the
# same (run, submission, criterion) updates the one row.

AGG_STATEMENTS: dict[str, Statement] = {
    "upsert_criterion_score": Statement(
        "INSERT INTO criterion_score (run_id, submission_id, criterion_id, band, "
        "modal_band, band_spread, points, judge_count, agreement, confidence, "
        "confidence_base, spans_verified, evidence_present, sufficiency_flag, "
        "ocr_overlap_risk, described_evidence, extractor_disagreement, caps_fired, "
        "routing, state) VALUES (:run_id, :submission_id, :criterion_id, :band, "
        ":modal_band, :band_spread, :points, :judge_count, :agreement, :confidence, "
        ":confidence_base, :spans_verified, :evidence_present, :sufficiency_flag, "
        ":ocr_overlap_risk, :described_evidence, :extractor_disagreement, :caps_fired, "
        ":routing, :state) "
        "ON CONFLICT (run_id, submission_id, criterion_id) DO UPDATE SET "
        "band = excluded.band, modal_band = excluded.modal_band, "
        "band_spread = excluded.band_spread, points = excluded.points, "
        "judge_count = excluded.judge_count, agreement = excluded.agreement, "
        "confidence = excluded.confidence, confidence_base = excluded.confidence_base, "
        "spans_verified = excluded.spans_verified, "
        "evidence_present = excluded.evidence_present, "
        "sufficiency_flag = excluded.sufficiency_flag, "
        "ocr_overlap_risk = excluded.ocr_overlap_risk, "
        "described_evidence = excluded.described_evidence, "
        "extractor_disagreement = excluded.extractor_disagreement, "
        "caps_fired = excluded.caps_fired, routing = excluded.routing, "
        "state = excluded.state"
    ),
}


#: FR-AGG-17's reads: one run's stored score rows and its score work units. Nothing else —
#: the signals are re-derivable from the database by anyone, which is what makes a figure in a
#: report answerable months later.
AGG_SIGNAL_STATEMENTS: dict[str, Statement] = {
    "select_run_scores": Statement(
        "SELECT criterion_id, band, band_spread, agreement, routing, caps_fired "
        "FROM criterion_score WHERE run_id = :run_id "
        "ORDER BY criterion_id, submission_id"
    ),
    # Panels, not units: one widening writes TWO units (1→3, 3→5), so counting rows would
    # report twice the share of panels widened and could exceed 1.0. The shipped precedent is
    # M-ORCH's own `select_escalated_results` — COUNT(DISTINCT submission_id).
    "select_run_escalated_panels": Statement(
        "SELECT criterion_id, COUNT(DISTINCT submission_id) AS n FROM work_unit "
        "WHERE run_id = :run_id AND stage = 'score' AND origin = 'escalation' "
        "GROUP BY criterion_id"
    ),
    "select_run_judged_panels": Statement(
        "SELECT criterion_id, COUNT(DISTINCT submission_id) AS n FROM work_unit "
        "WHERE run_id = :run_id AND stage = 'score' GROUP BY criterion_id"
    ),
}
AGG_STATEMENTS.update(AGG_SIGNAL_STATEMENTS)


@dataclass(frozen=True)
class AggregationSignals:
    """One run's aggregation signals, per criterion (`FR-AGG-17`, `CT-AGG-15`).

    Every field is a mapping keyed by criterion id:

    * `band_histogram` — band → count, the distribution the moderation meeting reads.
    * `band_spread_distribution` — spread → count; a panel's disagreement, not its average.
    * `agreement_distribution` — the stored ordinal α values, as value → count.
    * `escalation_rate` — the share of the criterion's PANELS that were widened: submissions
      carrying an escalation-origin unit over submissions the run judged for the criterion. A
      widening writes two units (1→3, 3→5), so units would count each widening twice.
    * `auto_accept_rate` — rows routed `auto` over the criterion's rows.
    * `caps_fired` — cap name → count, per criterion, from the `caps_fired` list
      `write_score` stored: the per-cap dimensionality `CT-AGG-15` asks for, never one total.
    """

    band_histogram: dict[str, dict[str, int]]
    band_spread_distribution: dict[str, dict[int, int]]
    agreement_distribution: dict[str, dict[float, int]]
    escalation_rate: dict[str, float]
    auto_accept_rate: dict[str, float]
    caps_fired: dict[str, dict[str, int]]


def aggregation_signals(handle: Any, run_id: str) -> AggregationSignals:
    """One run's aggregation signals, read only from stored rows (`FR-AGG-17`).

    The score rows carry the bands, spreads, α values, routings and fired caps; the work
    ledger carries the widenings (`origin='escalation'`). A second run of the same cohort
    contributes nothing: every read names the run (`CT-AGG-20`).
    """
    bands: dict[str, dict[str, int]] = {}
    spreads: dict[str, dict[int, int]] = {}
    agreements: dict[str, dict[float, int]] = {}
    caps: dict[str, dict[str, int]] = {}
    auto: dict[str, int] = {}
    rows_seen: dict[str, int] = {}
    for row in handle.query(AGG_STATEMENTS["select_run_scores"], run_id=run_id):
        criterion_id = str(row["criterion_id"])
        rows_seen[criterion_id] = rows_seen.get(criterion_id, 0) + 1
        band_counts = bands.setdefault(criterion_id, {})
        band_name = str(row["band"])
        band_counts[band_name] = band_counts.get(band_name, 0) + 1
        spread_counts = spreads.setdefault(criterion_id, {})
        spread = int(row["band_spread"] or 0)
        spread_counts[spread] = spread_counts.get(spread, 0) + 1
        if row["agreement"] is not None:
            alpha_counts = agreements.setdefault(criterion_id, {})
            alpha = float(row["agreement"])
            alpha_counts[alpha] = alpha_counts.get(alpha, 0) + 1
        else:
            agreements.setdefault(criterion_id, {})
        if row["routing"] == "auto":
            auto[criterion_id] = auto.get(criterion_id, 0) + 1
        fired = caps.setdefault(criterion_id, {})
        raw = row["caps_fired"]
        if raw:
            try:
                names = json.loads(raw)
            except ValueError:
                names = []
            for name in names or ():
                fired[str(name)] = fired.get(str(name), 0) + 1

    judged_panels: dict[str, int] = {}
    escalated_panels: dict[str, int] = {}
    for row in handle.query(AGG_STATEMENTS["select_run_judged_panels"], run_id=run_id):
        judged_panels[str(row["criterion_id"])] = int(row["n"])
    for row in handle.query(AGG_STATEMENTS["select_run_escalated_panels"], run_id=run_id):
        escalated_panels[str(row["criterion_id"])] = int(row["n"])

    escalation_rate: dict[str, float] = {}
    auto_rate: dict[str, float] = {}
    for criterion_id, seen in rows_seen.items():
        # The denominator is the criterion's judged panels where the ledger has them, and its
        # score rows otherwise — the same population either way for a run whose panels each
        # produced a row (a hand-seeded world without a ledger reads the rows).
        denominator = judged_panels.get(criterion_id) or seen
        escalation_rate[criterion_id] = escalated_panels.get(criterion_id, 0) / denominator
        auto_rate[criterion_id] = auto.get(criterion_id, 0) / seen
    return AggregationSignals(
        band_histogram=bands,
        band_spread_distribution=spreads,
        agreement_distribution=agreements,
        escalation_rate=escalation_rate,
        auto_accept_rate=auto_rate,
        caps_fired=caps,
    )


def _stored_signal(value: Any) -> int | None:
    """One integrity signal as the row stores it: 0/1, or `NULL` for "not measured"."""
    return None if value is None else int(bool(value))


def write_score(
    tx: Any, run_id: str, submission_id: str, score: CriterionScore, signals: Any
) -> None:
    """Persist one aggregated score in the caller's transaction (`FR-AGG-15`, `CT-AGG-18/19`).

    Upserts the row keyed `(run_id, submission_id, criterion_id)` with every field
    of `score` and all six integrity signals from `signals` (`FR-AGG-13`
    amended): each stored 0/1, `None` stored `NULL` — "not measured" stays
    distinguishable from a measured `False`. `caps_fired` is the JSON list of the
    caps that bound (`[]` when none). Idempotent: an identical second call
    leaves one unchanged row; a changed score updates it.

    `tx` must be a transaction the caller opened (`with handle.transaction() as
    tx`): this function never opens, commits or rolls one back, so a caller's
    rollback removes the row. Anything that is not a transaction — a tier
    handle, which has no `execute` — is refused with `TypeError` before any
    write.
    """
    if not callable(getattr(tx, "execute", None)):
        raise TypeError(
            f"write_score needs the caller's open transaction (CT-AGG-19), got "
            f"{type(tx).__name__}: open one with `with handle.transaction() as tx`."
        )
    tx.execute(
        AGG_STATEMENTS["upsert_criterion_score"],
        run_id=run_id,
        submission_id=submission_id,
        criterion_id=score.criterion_id,
        band=score.band,
        modal_band=score.modal_band,
        band_spread=score.band_spread,
        points=score.points,
        judge_count=score.judge_count,
        agreement=score.agreement,
        confidence=score.confidence,
        confidence_base=score.confidence_base,
        spans_verified=_stored_signal(getattr(signals, "spans_verified", None)),
        evidence_present=_stored_signal(getattr(signals, "evidence_present", None)),
        sufficiency_flag=_stored_signal(getattr(signals, "sufficiency_flag", None)),
        ocr_overlap_risk=_stored_signal(getattr(signals, "ocr_overlap_risk", None)),
        described_evidence=_stored_signal(getattr(signals, "described_evidence", None)),
        extractor_disagreement=_stored_signal(
            getattr(signals, "extractor_disagreement", None)
        ),
        caps_fired=json.dumps(list(score.caps_fired)),
        routing=score.routing,
        state=score.state,
    )


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
    odd-plan check) and `reasons`. Under the production constants a decision
    not to escalate carries the current panel depth unchanged and no reasons
    (every weight is sub-threshold alone, so nothing fires without escalating);
    an injected sub-threshold signal weight can fire a reason without reaching
    the threshold — the fired observables are recorded either way.
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

    # 1. Interior band position — the panel did not reach a scale edge. A
    # recorded `None` on either figure is a recorded inconclusive, not a claim
    # (the same absent-vs-None reading as the signals below): the limb is
    # skipped, never crashed through.
    ordinal = _row_field(score, "ordinal")
    band_count = _row_field(score, "band_count")
    if band_count is _AGG_ABSENT:
        declared = getattr(criterion, "band_count", None)
        if declared is None:
            declared = len(getattr(criterion, "bands", ()) or ())
        band_count = declared if declared else _AGG_ABSENT
    if (
        ordinal is not _AGG_ABSENT
        and ordinal is not None
        and band_count is not _AGG_ABSENT
        and band_count is not None
    ):
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
# `state` and `routing` already exist (det migration v9's CHECK admits every
# value this module's paths write — `final`, `queued` and, since #93,
# `provisional` on routing and `provisional_unreviewed`/`ungradeable_by_panel`
# on state);
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


# --- #359: run-scoped criterion_score (FR-AGG-16, CT-AGG-20) ---------------------------------
#
# A second run of a cohort must never overwrite the first run's scores, so the score row is keyed
# by the run: `(run_id, submission_id, criterion_id)`. SQLite cannot change a primary key in
# place, so the table is rebuilt — the grade v18 precedent (`_GRADE_SUBMISSION_GRADE_KEY`):
# create `criterion_score_new`, copy, drop, rename — inside the one migration transaction, so a
# failure at any statement leaves the old table whole (`RES-21`).
#
# The surviving columns keep their declaration order and the new ones follow them — the grade
# v18 precedent — so a positional reader of the table's leading columns (F-SCHEMA's fixture
# builder) reads the same columns at every version; the key's order is the PRIMARY KEY clause's.
#
# `run_id` carries **no default**: the backfill names the run explicitly, and a writer that
# forgets the run fails the NOT NULL rather than landing under a placeholder. It is not a foreign
# key either — the cohort ledger's other run-scoped tables (`submission_grade`) do not declare
# one, and the ledger's run rows are not the only producers of score rows under test.
#
# The backfill attributes existing rows to the cohort's only run. With rows present and any other
# run count — two or more (ambiguous) or zero (no run to name) — the guard refuses with
# `MigrationError` before a statement runs; with no rows there is nothing to attribute and the
# rebuild proceeds whatever the run count. Migrated rows were single-verdict-band rows, so
# `modal_band = band` and `band_spread = 0`. The three FR-AGG-15 columns #360's `write_score`
# fills (`described_evidence`, `extractor_disagreement`, `caps_fired`) arrive NULL: not measured.

def _refuse_unattributable_scores(rows: list[Any]) -> None:
    """Refuse the rebuild when existing score rows cannot be attributed to exactly one run."""
    present, runs = int(rows[0][0]), int(rows[0][1])
    if present and runs != 1:
        raise MigrationError(f"criterion_score rows cannot be attributed to a run: {runs} runs")


_AGG_RUN_SCOPED_SCORE = Migration(
    version=20,
    name="agg_run_scoped_score",
    statements=(
        MigrationPrecondition(
            "SELECT EXISTS (SELECT 1 FROM criterion_score) AS present, "
            "(SELECT COUNT(*) FROM run) AS runs",
            check=_refuse_unattributable_scores,
        ),
        Statement(
            """
            CREATE TABLE criterion_score_new (
                submission_id          TEXT    NOT NULL REFERENCES submission(submission_id),
                criterion_id           TEXT    NOT NULL,
                band                   TEXT    NOT NULL,
                points                 REAL,
                judge_count            INTEGER NOT NULL DEFAULT 0
                    CHECK (judge_count = 0 OR judge_count % 2 = 1),
                agreement              REAL,
                state                  TEXT    NOT NULL DEFAULT 'final'
                    CHECK (state IN ('final', 'provisional_unreviewed', 'ungradeable_by_panel',
                                     'unresolved_selection')),
                routing                TEXT    NOT NULL DEFAULT 'auto'
                    CHECK (routing IN ('auto', 'queued', 'reviewed', 'provisional', 'triage')),
                confidence             REAL,
                confidence_base        REAL,
                spans_verified         INTEGER CHECK (spans_verified IN (0, 1)),
                evidence_present       INTEGER CHECK (evidence_present IN (0, 1)),
                sufficiency_flag       INTEGER CHECK (sufficiency_flag IN (0, 1)),
                ocr_overlap_risk       INTEGER CHECK (ocr_overlap_risk IN (0, 1)),
                run_id                 TEXT    NOT NULL,
                modal_band             TEXT,
                band_spread            INTEGER NOT NULL DEFAULT 0,
                described_evidence     INTEGER,
                extractor_disagreement INTEGER,
                caps_fired             TEXT,
                PRIMARY KEY (run_id, submission_id, criterion_id)
            )
            """
        ),
        Statement(
            "INSERT INTO criterion_score_new (run_id, submission_id, criterion_id, band, "
            "modal_band, band_spread, points, judge_count, agreement, state, routing, "
            "confidence, confidence_base, spans_verified, evidence_present, sufficiency_flag, "
            "ocr_overlap_risk) SELECT (SELECT run_id FROM run), submission_id, criterion_id, "
            "band, band, 0, points, judge_count, agreement, state, routing, confidence, "
            "confidence_base, spans_verified, evidence_present, sufficiency_flag, "
            "ocr_overlap_risk FROM criterion_score"
        ),
        Statement("DROP TABLE criterion_score"),
        Statement("ALTER TABLE criterion_score_new RENAME TO criterion_score"),
    ),
)

TIER_MIGRATIONS[Tier.COHORT] = tuple(sorted(
    TIER_MIGRATIONS[Tier.COHORT] + (_AGG_RUN_SCOPED_SCORE,), key=lambda m: m.version
))
