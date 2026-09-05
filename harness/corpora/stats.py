"""`F-STATS` — label sets whose statistics were worked out by hand.

§4.7: *"Statistics reference — hand-computed constants committed as fixtures. **Not**
`scikit-learn` — a library is not a reference; two implementations agreeing on a wrong
convention is the classic failure."* `NFR-STATS-01` then names the degenerate cases that must
be in the set: a single label, unanimous agreement, a two-band criterion, and an empty blind
population. §4.4 adds a maximally-disagreeing panel.

**What "hand-computed" means here, precisely.** Each case below carries its own arithmetic,
written out in the comment above it, and the reference value is committed as an **exact
rational** wherever one exists. Nothing in this module computes κ, QWK or α in general: there
is no `def cohens_kappa(...)`, deliberately, because a general implementation living next to
the fixtures is a second implementation, and `M-STATS` agreeing with it would prove only that
two people read the same Wikipedia page. The one thing evaluated rather than transcribed is
Shannon entropy, from the closed form written in each case's comment — `math.log2` of a
hand-derived expression is arithmetic, not a statistics library.

**Undefined is a value.** Three of these cases have figures that are genuinely undefined —
κ is 0/0 when expected agreement is 1, and every figure is undefined over an empty
population. They are committed as `null` with a stated `reason`, never as 0 or 1.
`FR-STATS-04` and `FR-STATS-11` require the module to carry `NoValidationData` as a
first-class value rather than a null or a zero, and `CT-STATS-03` makes rendering absence as a
number a permanent regression entry — so a fixture that quietly wrote 0.0 here would be
teaching the implementation the exact bug the contract forbids.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any, Mapping, Sequence

# The band scale these label sets are on: the reference package's four-band open scale, with
# `two_band` cases on the two-band MCQ scale. Interior bands are the ones that are neither the
# lowest nor the highest ordinal — the interior rate is what tells you whether a criterion is
# actually being used as an ordinal scale or collapsed to a pass/fail (FR-STATS-*).
OPEN_ORDINALS = (0, 1, 2, 3)
TWO_BAND_ORDINALS = (0, 1)


def _interior_rate(labels: Sequence[int], ordinals: Sequence[int]) -> Fraction | None:
    """Share of labels that are neither the lowest nor the highest ordinal.

    A counting operation, not a statistic — no convention is at stake, so evaluating it here
    does not make this module a second implementation of anything.
    """
    if not labels:
        return None
    interior = set(ordinals[1:-1])
    return Fraction(sum(1 for label in labels if label in interior), len(labels))


def _entropy_bits(counts: Sequence[int]) -> float | None:
    """`H = -Σ p log₂ p` over the observed label distribution, in bits.

    Evaluated from the closed form each case's comment states. The definition has no competing
    conventions to get wrong, which is why this one is computed rather than transcribed to ten
    decimal places by hand.
    """
    total = sum(counts)
    if total == 0:
        return None
    # `+ 0.0` normalizes the single-category case: `-(1 * log2(1))` is `-0.0`, and a committed
    # `-0.0` is a reference value that reads as a sign error to everyone who opens the file.
    return -sum((c / total) * math.log2(c / total) for c in counts if c) + 0.0


def _figure(exact: Fraction | None, *, undefined_reason: str | None = None) -> dict[str, Any]:
    if exact is None:
        return {"value": None, "exact": None, "undefined_reason": undefined_reason}
    return {"value": float(exact), "exact": f"{exact.numerator}/{exact.denominator}"}


# --- CASE 1: a single label ----------------------------------------------------------------
# One unit, one label, band `developing` (ordinal 2) on the four-band open scale.
#
#   κ    - undefined. Cohen's κ needs two raters; there is one label, so there is no pair to
#          agree or disagree, and the marginals of a single observation carry no information.
#   QWK  - undefined, same reason.
#   α    - undefined. Krippendorff's α is computed over *pairable* values; a unit labelled once
#          contributes none, so n = 0 and D_e is 0/0.
#   H    - 0 bits exactly. One observation in one category: -1·log₂1 = 0.
#   int. - 1 (1 of 1 label is interior).
_SINGLE_LABEL = {
    "case_id": "STATS-SINGLE-LABEL",
    "description": "One unit, one label. NFR-STATS-01's first degenerate case.",
    "scale": "open_four_band",
    "raters": 1,
    "units": 1,
    "labels": [{"unit": "u1", "rater": "r1", "ordinal": 2}],
    "figures": {
        "cohens_kappa": _figure(
            None, undefined_reason="one rater: no pair of labels exists to agree or disagree"
        ),
        "quadratic_weighted_kappa": _figure(
            None, undefined_reason="one rater: no pair of labels exists to agree or disagree"
        ),
        "ordinal_alpha": _figure(
            None, undefined_reason="no pairable values: a singly-labelled unit contributes none"
        ),
        "entropy_bits": {"value": _entropy_bits([1]), "closed_form": "-1*log2(1)"},
        "interior_rate": _figure(_interior_rate([2], OPEN_ORDINALS)),
    },
}

# --- CASE 2a: unanimous agreement, one category (the 0/0 case) ------------------------------
# 10 units, 2 raters, every label `secure` (ordinal 3).
#
#   p_o = 1.0.  Both marginals are concentrated on one category, so p_e = 1·1 = 1.0, and
#   κ = (1 - 1)/(1 - 1) = 0/0 — **undefined**, not 1. This is the case where a library that
#   returns 0.0 or nan quietly turns perfect agreement into no agreement.
#   α: D_o = 0 and D_e = 0 for the same reason, so α is 0/0 as well.
#   H = 0 bits (one category). Interior rate = 0 (ordinal 3 is the top band).
_UNANIMOUS_ONE_CATEGORY = {
    "case_id": "STATS-UNANIMOUS-ONE-CATEGORY",
    "description": (
        "Two raters agree on every unit and use a single category. Expected agreement is 1, so "
        "κ is 0/0 — the case where returning 0.0 reports perfect agreement as none."
    ),
    "scale": "open_four_band",
    "raters": 2,
    "units": 10,
    "labels": [
        {"unit": f"u{i}", "rater": rater, "ordinal": 3}
        for i in range(1, 11)
        for rater in ("r1", "r2")
    ],
    "figures": {
        "cohens_kappa": _figure(
            None, undefined_reason="expected agreement is 1, so κ = (1-1)/(1-1) is 0/0"
        ),
        "quadratic_weighted_kappa": _figure(
            None, undefined_reason="expected disagreement is 0, so QWK = 1 - 0/0 is undefined"
        ),
        "ordinal_alpha": _figure(
            None, undefined_reason="D_e = 0 with one category in use, so α = 1 - 0/0 is undefined"
        ),
        "entropy_bits": {"value": _entropy_bits([20]), "closed_form": "-1*log2(1)"},
        "interior_rate": _figure(_interior_rate([3] * 20, OPEN_ORDINALS)),
    },
}

# --- CASE 2b: unanimous agreement, two categories (the defined case) ------------------------
# 10 units, 2 raters, perfect agreement: 6 units `secure` (3), 4 units `absent` (0).
#
#   p_o = 1.0
#   marginals: both raters 0.6 secure / 0.4 absent
#   p_e = 0.6² + 0.4² = 0.36 + 0.16 = 0.52
#   κ   = (1 - 0.52)/(1 - 0.52) = 1                                     exactly 1
#   QWK = 1 - 0/(positive expected disagreement) = 1                    exactly 1
#   α:  the coincidence matrix has no off-diagonal mass, so D_o = 0 and, since two categories
#       are in use, D_e > 0 — α = 1 - 0/D_e = 1                         exactly 1
#   H   = -(0.6 log₂0.6 + 0.4 log₂0.4)
#   int.= 0 (only the bottom and top bands are used)
#
# Carried alongside 2a because "unanimous agreement" has two entirely different answers
# depending on whether the raters used one category or several, and a fixture set with only
# one of them lets an implementation pass while getting the other backwards.
_UNANIMOUS_TWO_CATEGORIES = {
    "case_id": "STATS-UNANIMOUS-TWO-CATEGORIES",
    "description": "Two raters agree on every unit across two categories: κ, QWK and α are all 1.",
    "scale": "open_four_band",
    "raters": 2,
    "units": 10,
    "labels": [
        {"unit": f"u{i}", "rater": rater, "ordinal": 3 if i <= 6 else 0}
        for i in range(1, 11)
        for rater in ("r1", "r2")
    ],
    "figures": {
        "cohens_kappa": _figure(Fraction(1)),
        "quadratic_weighted_kappa": _figure(Fraction(1)),
        "ordinal_alpha": _figure(Fraction(1)),
        "entropy_bits": {
            "value": _entropy_bits([12, 8]),
            "closed_form": "-(0.6*log2(0.6) + 0.4*log2(0.4))",
        },
        "interior_rate": _figure(_interior_rate([3] * 12 + [0] * 8, OPEN_ORDINALS)),
    },
}

# --- CASE 3: a two-band criterion at a 95% base rate (the κ paradox) ------------------------
# 100 units, 2 raters, categories not_met (0) / met (1). Cross-tabulation:
#
#              r2:met   r2:not_met
#   r1:met        90         5        = 95
#   r1:not_met     4         1        =  5
#                 94         6          100
#
#   p_o = (90 + 1)/100 = 0.91
#   p_e = 0.95·0.94 + 0.05·0.06 = 0.893 + 0.003 = 0.896
#   κ   = (0.91 - 0.896)/(1 - 0.896) = 0.014/0.104 = 7/52 ≈ 0.1346
#   QWK: with two categories the quadratic weights are 0 on the diagonal and 1 off it, which is
#        the unweighted weighting — so QWK = κ = 7/52 exactly. Stated rather than left implicit
#        because an implementation that special-cases k=2 differently is wrong here.
#   α:  coincidence matrix over n = 200 pairable values: o_00 = 2, o_11 = 180, o_01 = o_10 = 9;
#       marginals n_0 = 11, n_1 = 189.
#       Two categories, so the ordinal metric's scale factor cancels between D_o and D_e:
#           D_o/D_e = [18/200] / [2·11·189/(200·199)] = 3582/4158 = 199/231
#           α = 1 - 199/231 = 32/231 ≈ 0.1385
#   H   = -(0.945 log₂0.945 + 0.055 log₂0.055)
#   int.= undefined-by-construction is *not* right here: a two-band scale has no interior band,
#         so the rate is 0 over 200 labels, and that 0 is a real 0.
#
# This is the case that catches a "high agreement therefore high κ" bug: 91% of the labels
# agree and κ is 0.13.
_TWO_BAND_HIGH_BASE_RATE = {
    "case_id": "STATS-TWO-BAND-95-BASE-RATE",
    "description": (
        "A two-band criterion where 94-95% of labels are `met`. Observed agreement is 0.91 and "
        "κ is 7/52 — the base-rate paradox NFR-STATS-01's two-band case exists to pin down."
    ),
    "scale": "two_band",
    "raters": 2,
    "units": 100,
    "cross_tabulation": {"1,1": 90, "1,0": 5, "0,1": 4, "0,0": 1},
    "figures": {
        "cohens_kappa": _figure(Fraction(7, 52)),
        "quadratic_weighted_kappa": _figure(Fraction(7, 52)),
        "ordinal_alpha": _figure(Fraction(32, 231)),
        "entropy_bits": {
            "value": _entropy_bits([189, 11]),
            "closed_form": "-(0.945*log2(0.945) + 0.055*log2(0.055))",
        },
        "interior_rate": _figure(Fraction(0)),
    },
}

# --- CASE 4: an empty blind population ------------------------------------------------------
# No labels at all. `FR-STATS-11`: the module reports "no new validation evidence for this
# administration" as a first-class value and does not advance the package's figures.
# `CT-STATS-01` makes computing agreement over an inadmissible population a permanent
# regression entry, and `CT-STATS-03` does the same for rendering absence as a number.
_EMPTY_BLIND_POPULATION = {
    "case_id": "STATS-EMPTY-BLIND-POPULATION",
    "description": (
        "No blind labels were collected. Every figure is NoValidationData — not 0, not null, "
        "and not the previous administration's number (FR-STATS-11, CT-STATS-03)."
    ),
    "scale": "open_four_band",
    "raters": 0,
    "units": 0,
    "labels": [],
    "expected_result_type": "NoValidationData",
    "figures": {
        name: _figure(None, undefined_reason="empty population: no labels were collected")
        for name in (
            "cohens_kappa",
            "quadratic_weighted_kappa",
            "ordinal_alpha",
            "entropy_bits",
            "interior_rate",
        )
    },
}

# --- CASE 5: a maximally-disagreeing panel --------------------------------------------------
# 4 units, 2 judges, four-band open scale, arranged so every band is used exactly twice and no
# unit agrees:
#
#   u1: r1=0 r2=3    u2: r1=3 r2=0    u3: r1=1 r2=2    u4: r1=2 r2=1
#
#   κ:   p_o = 0; each marginal is uniform at 1/4, so p_e = 4·(1/4)² = 1/4
#        κ = (0 - 1/4)/(1 - 1/4) = -1/3
#   QWK: weights w_ij = (i-j)²/9.
#        Σ w·O = 9/9 + 9/9 + 1/9 + 1/9 = 20/9
#        E_ij = (1·1)/4 = 1/4 for all 16 cells; Σ_{i,j}(i-j)² = 40, so Σ w·E = (1/4)(40/9) = 10/9
#        QWK = 1 - (20/9)/(10/9) = -1
#   α:   coincidence matrix o_03 = o_30 = o_12 = o_21 = 2, n = 8, every marginal n_g = 2.
#        Ordinal metric δ²(c,k) = (Σ_{g=c..k} n_g - (n_c + n_k)/2)²:
#            δ²(0,1) = (4-2)² = 4     δ²(0,2) = (6-2)² = 16    δ²(0,3) = (8-2)² = 36
#            δ²(1,2) = (4-2)² = 4     δ²(1,3) = (6-2)² = 16    δ²(2,3) = (4-2)² = 4
#        D_o = (1/8)[2·36 + 2·36 + 2·4 + 2·4] = 160/8 = 20
#        D_e = (1/(8·7))·Σ_{c≠k} n_c n_k δ²_ck = (4/56)·(2·80) = 80/7
#        α = 1 - 20/(80/7) = 1 - 7/4 = -3/4
#   H:   uniform over four categories = log₂4 = 2 bits
#   int.= 4 of 8 labels are interior = 1/2
#
# The negative values are the point. A panel that disagrees more than chance is a real state
# with a real sign, and an implementation that clamps at 0 reports it as "no agreement" —
# which reads as noise rather than as the systematic opposition it is.
_MAXIMAL_DISAGREEMENT = {
    "case_id": "STATS-MAXIMAL-DISAGREEMENT",
    "description": (
        "A two-judge panel that disagrees maximally on every unit with uniform marginals: "
        "κ = -1/3, QWK = -1, ordinal α = -3/4. The signs are the assertion."
    ),
    "scale": "open_four_band",
    "raters": 2,
    "units": 4,
    "labels": [
        {"unit": "u1", "rater": "r1", "ordinal": 0},
        {"unit": "u1", "rater": "r2", "ordinal": 3},
        {"unit": "u2", "rater": "r1", "ordinal": 3},
        {"unit": "u2", "rater": "r2", "ordinal": 0},
        {"unit": "u3", "rater": "r1", "ordinal": 1},
        {"unit": "u3", "rater": "r2", "ordinal": 2},
        {"unit": "u4", "rater": "r1", "ordinal": 2},
        {"unit": "u4", "rater": "r2", "ordinal": 1},
    ],
    "figures": {
        "cohens_kappa": _figure(Fraction(-1, 3)),
        "quadratic_weighted_kappa": _figure(Fraction(-1)),
        "ordinal_alpha": _figure(Fraction(-3, 4)),
        "entropy_bits": {"value": _entropy_bits([2, 2, 2, 2]), "closed_form": "log2(4)"},
        "interior_rate": _figure(_interior_rate([0, 3, 3, 0, 1, 2, 2, 1], OPEN_ORDINALS)),
    },
}

CASES: tuple[Mapping[str, Any], ...] = (
    _SINGLE_LABEL,
    _UNANIMOUS_ONE_CATEGORY,
    _UNANIMOUS_TWO_CATEGORIES,
    _TWO_BAND_HIGH_BASE_RATE,
    _EMPTY_BLIND_POPULATION,
    _MAXIMAL_DISAGREEMENT,
)
