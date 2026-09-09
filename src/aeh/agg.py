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
consumer limb). #92 lands the confidence surface on that core: the integrity
inversion (`FR-AGG-05`, ADR-10 — a cap is a `min`, never a penalty term, so
unanimity cannot outrun bad evidence), the four integrity inputs recorded on
the score row (`FR-AGG-13`), the from-the-row-alone re-derivation
(`recompute_confidence`, `NFR-AGG-04`), and the cohort migration that carries
the columns. The escalation policy, the remaining routing values and the score
states are #93's: `aggregate` returns the panel path's own `state` (`final`)
and routes `auto`/`queued` only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    "AGG_HOLISTIC_MULTIPLIER",
    "AGG_UNCITED_MULTIPLIER",
    "AggregateError",
    "CriterionScore",
    "EmptyVerdictsError",
    "EvenPanelError",
    "aggregate",
    "describe_agreement",
    "ordinal_alpha",
    "recompute_confidence",
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
    points: float
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
    #: `auto` iff `confidence >= auto_threshold_for(scoring_model)`, else
    #: `queued` (§3.12; the remaining routing values are #93's).
    routing: str = "queued"
    #: The panel path's own state. The other states — fallback, breaker,
    #: deterministic — are #93's assignment.
    state: str = "final"
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
) -> CriterionScore:
    """Aggregate a panel's verdicts into one criterion score (`FR-AGG-01/02/03/04`)
    with its confidence (`FR-AGG-05`, `FR-AGG-13`, `NFR-AGG-04`).

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

    Routing is `auto` iff `confidence >= auto_threshold_for(scoring_model)`
    (§3.12), else `queued`; the state is the panel path's own `final` (the
    remaining states are #93's). The four integrity inputs `FR-AGG-13` records
    are carried on the score exactly as received, beside the pre-cap base —
    the fields that make the figure reconstructible from the stored row alone
    (`recompute_confidence`).

    An empty panel raises `EmptyVerdictsError` (a programming error, `CT-AGG-12`);
    an even panel raises `EvenPanelError` before any median is taken
    (`FR-AGG-03`).
    """
    if len(verdicts) == 0:
        raise EmptyVerdictsError(
            "aggregate over an empty verdict set is a programming error (CT-AGG-12): "
            "it is never a zero, a lowest band, or a null score."
        )
    if len(verdicts) % 2 == 0:
        raise EvenPanelError(
            f"a panel of {len(verdicts)} judges is even — an even panel is a failed "
            "write, not a rounded verdict (FR-AGG-03): escalate 1 → 3, never to 2."
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
        routing="auto" if confidence >= threshold else "queued",
        state="final",
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


# --- the cohort migration: the confidence surface's stored columns (`FR-AGG-13`) -------------------
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
