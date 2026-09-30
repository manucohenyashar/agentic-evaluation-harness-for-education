"""Panel agreement: Krippendorff's ordinal alpha, and how an agreement figure is described."""

from __future__ import annotations

from typing import Any, Sequence


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
