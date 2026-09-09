"""`TC-AGG-02` — the median band ordinal across panel sizes and split shapes.

Test plan §5.12 (row form), issue #94 (TS-35). Traces to `FR-AGG-01`. Boundary: panels of
1, 3 and 5 verdicts; all-agree; maximally split; adjacent-band split. Median ordinal,
modal band and `band_spread` in each; `band_spread` is the ordinal distance between the
lowest and highest verdict — asserted both by hand value and by the definition computed
from the panel itself. Written ahead of #91 (test plan §8.2).

**Declared assumption (modal tie-break).** On a maximally split panel two bands can tie
for the mode and the design pins no tie-break (`FR-AGG-01` says "record the modal band";
§3.12's observability line records a band *histogram*). These cases assert the modal band
is one of the tied bands, not a particular one — a tie-break that picks a band outside
the panel's own histogram would be a defect, a tie-break that picks among the tied bands
is #91's to declare.

Interface assumed of #91: `tests/support/agg_vocabulary.py`. Isolation: rung 0.
"""

from __future__ import annotations

import pytest

from tests.support.agg_vocabulary import AGG_BLOCKER, band, criterion, favourable_signals, panel
from tests.support.impl import AGG_MODULE, require

pytestmark = [pytest.mark.writtenahead]

_FOUR_BAND = criterion(
    [
        band("B0", 0, 0.0),
        band("B1", 1, 1.0),
        band("B2", 2, 3.0),
        band("B3", 3, 6.0),
    ]
)

# (label, panel, expected median band, expected points, acceptable modal bands)
_CASES = [
    ("panel_of_1", panel(("B2", 2)), "B2", 3.0, {"B2"}),
    ("panel_of_3_all_agree", panel(("B1", 1), ("B1", 1), ("B1", 1)), "B1", 1.0, {"B1"}),
    ("panel_of_5_all_agree",
     panel(("B3", 3), ("B3", 3), ("B3", 3), ("B3", 3), ("B3", 3)), "B3", 6.0, {"B3"}),
    ("panel_of_5_adjacent_split",
     panel(("B0", 0), ("B1", 1), ("B2", 2), ("B2", 2), ("B3", 3)), "B2", 3.0, {"B2"}),
    ("panel_of_5_maximally_split",
     panel(("B0", 0), ("B0", 0), ("B1", 1), ("B3", 3), ("B3", 3)), "B1", 1.0, {"B0", "B3"}),
    ("panel_of_3_all_distinct",
     panel(("B0", 0), ("B1", 1), ("B3", 3)), "B1", 1.0, {"B0", "B1", "B3"}),
]


@pytest.mark.parametrize(
    ("label", "verdicts", "median_band", "points", "modal_ok"), _CASES,
    ids=[case[0] for case in _CASES],
)
def test_tc_agg_02_median_modal_and_spread_by_hand_across_panel_shapes(
    label, verdicts, median_band, points, modal_ok
):
    """`TC-AGG-02` (`FR-AGG-01`, unit / rung 0, boundary, P0) — for panels of 1, 3 and 5
    (all-agree, maximally split, adjacent split): the median band ordinal, the modal band
    and `band_spread` are each the hand-computed value, and the spread equals the ordinal
    distance between the lowest and highest verdict computed from the panel itself."""
    aggregate = require(AGG_MODULE, "aggregate", issue=AGG_BLOCKER)

    score = aggregate(verdicts, _FOUR_BAND, favourable_signals())

    assert score.band == median_band, (
        f"{label}: aggregated band is {score.band!r}, expected {median_band!r} — the "
        "median band ordinal of the panel (FR-AGG-01)"
    )
    assert score.points == pytest.approx(points), (
        f"{label}: points are {score.points!r}, expected {points!r} — derived from the "
        "median band via the criterion's band table, once (FR-AGG-02)"
    )
    assert score.judge_count == len(verdicts), (
        f"{label}: judge_count is {score.judge_count!r} for a {len(verdicts)}-judge panel"
    )

    ordinals = [verdict.ordinal for verdict in verdicts]
    defined_spread = max(ordinals) - min(ordinals)
    assert score.band_spread == defined_spread, (
        f"{label}: band_spread is {score.band_spread!r} — FR-AGG-01 defines it as the "
        f"ordinal distance between the lowest and highest verdict, which is "
        f"{defined_spread} for this panel"
    )

    assert score.modal_band in modal_ok, (
        f"{label}: modal band is {score.modal_band!r}; the panel's histogram mode is "
        f"{sorted(modal_ok)} — a band outside the panel's own histogram is a defect, and "
        "among tied modes the design pins no tie-break (declared at #91's reconciliation)"
    )
