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
3. *Env-gated knobs* — the module declares **no environment-sensitive constant**:
   every threshold, cap and multiplier the design names (`AGG_AUTO_THRESHOLD_*`,
   the cap table) is #92's confidence surface and arrives injected as
   configuration, never read from the environment here. Nothing to knob.
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

Scope (#91): the aggregation core above plus `describe_agreement`, the module's
own honest description of an agreement figure (`CT-STATS-21`'s M-AGG consumer
limb). The confidence caps and the stored integrity inputs are #92's; the
escalation policy, routing and score states are #93's — `signals` is accepted
here as the declared surface's third argument and consumed by #92, not by this
story.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from aeh.pkg import PackageError, points_for_band

__all__ = [
    "AggregateError",
    "CriterionScore",
    "EmptyVerdictsError",
    "EvenPanelError",
    "aggregate",
    "describe_agreement",
    "ordinal_alpha",
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


# --- the score -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionScore:
    """One aggregated criterion score — the value §3.14's `apply_policy` consumes.

    The shipped `criterion_score` columns (det migration v9: band, points,
    judge_count, agreement, state, routing) plus `FR-AGG-01`'s recorded modal band
    and spread, the degeneracy marker `CT-AGG-17`/`TC-AGG-19` require, and the
    aggregation stage's histogram. `state`/`routing` are #93's assignment and are
    deliberately absent here: this story returns the aggregation's figures and
    invents no state vocabulary ahead of the story that owns the states.
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
    two declared bands (`D_e` would be zero). A unanimous panel is *defined*, not
    degenerate-by-absence: D_o = 0 gives α = 1 exactly — including the two-band
    case, where the design's `TBD` pins α = 1 **by construction** (`TC-AGG-19`)
    and the score carries `agreement_degenerate` so no consumer renders that 1 as
    if it were information (`CT-AGG-17`).

    When `criterion` is omitted the declared scale is inferred from the panel's
    own highest ordinal (`K = max(ordinal) + 1`) — the reading a caller can take
    holding nothing but the verdicts. `aggregate` always passes the criterion, so
    every score row's agreement is computed on the full declared scale.
    """
    if len(verdicts) < 2:
        return None
    if criterion is not None:
        band_count = int(criterion.band_count)
    else:
        band_count = max(_verdict_ordinal(v) for v in verdicts) + 1
    if band_count < 2:
        return None  # D_e is undefined on a one-band scale; refuse a substitute.

    scale = band_count - 1
    ordinals = [_verdict_ordinal(v) for v in verdicts]

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


def aggregate(verdicts: Sequence[Any], criterion: Any, signals: Any) -> CriterionScore:
    """Aggregate a panel's verdicts into one criterion score (`FR-AGG-01/02/03/04`).

    Pure (`CT-AGG-01`): the verdicts, the criterion's declared band set and the
    integrity signals are values; nothing here reads a store, a clock, or any
    configuration beyond its arguments. The result is the **median band ordinal**,
    mapped to points exactly once through M-PKG's canonical `points_for_band`
    (`CT-PKG-05`, `NFR-AGG-02`) — never a mean of bands, never a mean of points,
    and never a per-judge average (RISK-05).

    An empty panel raises `EmptyVerdictsError` (a programming error, `CT-AGG-12`);
    an even panel raises `EvenPanelError` before any median is taken
    (`FR-AGG-03`). The integrity `signals` are the declared third argument of the
    surface (§3.12's Protocol) and are consumed by #92's confidence computation,
    not by this story's core.
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
