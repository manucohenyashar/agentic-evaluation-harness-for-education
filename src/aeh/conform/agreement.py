"""Chance-corrected agreement between two graders, for the conformance reports (FR-CONFORM-19,
CT-CONFORM-18).

Exact and adjacent agreement say how often two graders landed on the same band, or within one.
Neither corrects for chance: two graders who both put most cells in one band agree often by
accident. Every conformance agreement report therefore carries Cohen's kappa and ordinal alpha
beside them, computed here with the same statistics the validity figures use
(`aeh.stats.agreement`), so a conformance figure and a validity figure on the same pairs are the
same number.

The two graders here are both machines (two decision backends, or the decision engine and the LLM
panel). Their agreement is consistency between graders, never accuracy: the report says so in
`GRADER_CONSISTENCY_NOTE`.

The formulas, over `n` pairs of 0-based band ordinals `(a, b)` on a criterion with `K` bands:

- exact = share of pairs with `a == b`; adjacent = share with `|a - b| <= 1`.
- kappa = `(po - pe) / (1 - pe)`, where `po` is the exact share and `pe` sums, over every band
  either side used, the product of the two sides' marginal shares. Undefined (None) when
  `pe == 1` (both sides used one band only).
- ordinal alpha = `1 - D_o / D_e`, the repo's convention (`aeh.agg.ordinal_alpha`,
  `aeh.stats.agreement`): `D_o` is the mean of `|a - b| / (K - 1)` over the pairs; `D_e` is the
  mean of `|i - j| / (K - 1)` over every ordered pair of distinct declared bands `i != j`
  (the declared instrument's own spread, not the observed marginals). All pairs on one band give
  exactly 1.0; fewer than two declared bands give None.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = [
    "CHANCE_CORRECTED_KEYS",
    "GRADER_CONSISTENCY_NOTE",
    "chance_corrected_agreement",
]

#: FR-CONFORM-19's sentence, verbatim. Every conformance agreement report carries it.
GRADER_CONSISTENCY_NOTE = "agreement between graders is consistency, not agreement with teachers"

#: The two chance-corrected figures every conformance agreement report carries beside the exact
#: and adjacent agreement (CT-CONFORM-18). Kept apart from `DECISION_REPORT_KEYS`, which is
#: CT-CONFORM-15's four names exactly.
DECISION_BAND_KAPPA = "decision_band_kappa"
DECISION_BAND_ORDINAL_ALPHA = "decision_band_ordinal_alpha"
CHANCE_CORRECTED_KEYS: tuple[str, ...] = (DECISION_BAND_KAPPA, DECISION_BAND_ORDINAL_ALPHA)


def chance_corrected_agreement(
    pairs: Sequence[tuple[int, int]], band_count: int,
) -> Mapping[str, Any]:
    """Exact, adjacent, kappa and ordinal alpha over `pairs` of 0-based band ordinals on a
    criterion with `band_count` declared bands (formulas in the module docstring).

    No pairs gives every figure None and `pairs` 0: an unmeasured agreement is not a zero one.
    """
    from aeh.stats.agreement import (
        _chance_corrected_coefficient,
        _distance_coefficient,
        _observed_and_expected,
    )

    ordinals = [(int(a), int(b)) for a, b in pairs]
    n = len(ordinals)
    if not n:
        return {"pairs": 0, "decision_band_exact_agreement": None,
                "decision_band_adjacent_agreement": None,
                DECISION_BAND_KAPPA: None, DECISION_BAND_ORDINAL_ALPHA: None}
    po, pe = _observed_and_expected(ordinals)
    return {
        "pairs": n,
        "decision_band_exact_agreement": po,
        "decision_band_adjacent_agreement": sum(1 for a, b in ordinals if abs(a - b) <= 1) / n,
        DECISION_BAND_KAPPA: _chance_corrected_coefficient(po, pe),
        DECISION_BAND_ORDINAL_ALPHA: _distance_coefficient(ordinals, int(band_count)),
    }
