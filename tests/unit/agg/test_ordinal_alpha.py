"""`TC-AGG-05` and `TC-AGG-19` — ordinal agreement and the two-band degeneracy.

Test plan §5.12, issue #94 (TS-35). Traces to `FR-AGG-04`. Written ahead of #91 (test
plan §8.2).

**TC-AGG-05's convention, declared because the oracle is a hand-computed reference.**
The design requires Krippendorff's α *with an ordinal metric* (`FR-AGG-04`) but §3.12
records a `TBD`: Krippendorff's own coincidence treatment is degenerate here, because a
criterion's panel is a **single unit** — over one unit, observed and expected
disagreement are the same pair population, so the textbook α collapses to 0 for any
disagreeing panel and to 1 for a unanimous one, under *any* per-pair distance (the
distance scale cancels). No convention built on the observed marginal alone can satisfy
the plan's requirement that adjacent-band disagreement score **higher** than distant
disagreement at equal raw agreement. The convention these cases pin is the one that can:

    alpha  = 1 - D_o / D_e
    D_o    = mean pairwise distance among the panel's valuations
    delta  = |i - j| / (K - 1)        over the criterion's *declared* band scale
    D_e    = mean pairwise distance over all ordered pairs of distinct declared bands

`D_e` is a property of the criterion alone, so it is identical for the two panels — the
differential is carried entirely by `D_o`. Hand computation for the 4-band fixture
(distances 1/3, 2/3, 1):

    D_e   = (2 x (3 x 1/3 + 2 x 2/3 + 1 x 1)) / 12 = (20/3) / 12 = 5/9
    D_o   = 4/15 for [B0, B1, B1, B1, B2]   ->  alpha = 1 - (4/15)/(5/9) = 13/25 = 0.52
    D_o   = 2/5  for [B0, B1, B1, B1, B3]   ->  alpha = 1 - (2/5)/(5/9)  =  7/25 = 0.28

Both panels have the **same raw agreement** — modal count 3 of 5, seven disagreeing and
three agreeing pairs — so a raw "3 of 5 agreed" figure scores them equally and fails
here, and a nominal metric (any disagreement = 1) gives both panels D_o = 0.7 and fails
here too. The exact values are the pin; #91 reconciles the convention at landing (the
same status as the design's own TBD), and the differential plus the raw-count exclusion
are the load-bearing oracles.

Isolation: rung 0. Interface assumed of #91: `tests/support/agg_vocabulary.py`.
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

#: Equal raw agreement by construction: both panels are 5 judges, modal count 3,
#: three agreeing pairs, seven disagreeing pairs — only the *distance* of the
#: disagreement differs.
_ADJACENT = panel(("B0", 0), ("B1", 1), ("B1", 1), ("B1", 1), ("B2", 2))
_DISTANT = panel(("B0", 0), ("B1", 1), ("B1", 1), ("B1", 1), ("B3", 3))


def test_tc_agg_05_adjacent_disagreement_scores_higher_than_distant_at_equal_raw_agreement():
    """`TC-AGG-05` (`FR-AGG-04`, unit / rung 0, P0) — ordinal α is **higher** for the
    adjacent-band split (0.52) than for the distant split (0.28), the plan's hand-computed
    reference under the declared convention."""
    aggregate = require(AGG_MODULE, "aggregate", issue=AGG_BLOCKER)

    adjacent = aggregate(_ADJACENT, _FOUR_BAND, favourable_signals())
    distant = aggregate(_DISTANT, _FOUR_BAND, favourable_signals())

    assert adjacent.agreement == pytest.approx(0.52), (
        f"adjacent-band disagreement scored agreement {adjacent.agreement!r}; the "
        "hand-computed ordinal figure is 13/25 (D_o = 4/15 against D_e = 5/9) — "
        "FR-AGG-04, declared convention in this module's docstring"
    )
    assert distant.agreement == pytest.approx(0.28), (
        f"distant-band disagreement scored agreement {distant.agreement!r}; the "
        "hand-computed ordinal figure is 7/25 (D_o = 2/5 against D_e = 5/9) — "
        "FR-AGG-04, declared convention in this module's docstring"
    )
    assert adjacent.agreement > distant.agreement, (
        "adjacent-band disagreement did not score higher than distant disagreement — "
        "an ordinal metric counts adjacent disagreement for less (FR-AGG-04); a linear "
        "or nominal treatment that scores them equally condemns itself here"
    )


def test_tc_agg_05_a_raw_agreement_count_is_never_returned_as_the_figure():
    """`TC-AGG-05`'s API assertion — the two panels agree at the same raw rate (3 of 5
    modal, 3 of 10 pairs), so a raw count scores them identically; the API surface must
    return figures that differ, and neither may be a raw ratio."""
    aggregate = require(AGG_MODULE, "aggregate", issue=AGG_BLOCKER)

    adjacent = aggregate(_ADJACENT, _FOUR_BAND, favourable_signals()).agreement
    distant = aggregate(_DISTANT, _FOUR_BAND, favourable_signals()).agreement

    assert adjacent != pytest.approx(distant), (
        f"adjacent and distant disagreement scored the same agreement ({adjacent!r}) — "
        "equal raw agreement, so that figure IS a raw count, and FR-AGG-04 forbids a raw "
        "'N of M agreed' figure as the agreement (CT-AGG-04)"
    )
    raw_ratios = {0.6, 0.3, 0.7, 0.0}  # 3/5 modal, 3/10 pairs, 7/10 pairs, no-agreement
    for figure in (adjacent, distant):
        for raw in raw_ratios:
            assert figure != pytest.approx(raw), (
                f"agreement figure {figure!r} equals the raw ratio {raw!r} — a raw 'N of "
                "M agreed' count is not the agreement figure (FR-AGG-04)"
            )
        assert -1.0 <= figure <= 1.0, (
            f"agreement figure {figure!r} outside α's range — agreement is Krippendorff's "
            "α with an ordinal metric, not an arbitrary score (FR-AGG-04)"
        )


def test_tc_agg_05_a_unanimous_panel_scores_one():
    """`TC-AGG-05`'s anchor: full agreement is α = 1 under the convention too — guards
    the differential above against a convention that cannot reach the top."""
    aggregate = require(AGG_MODULE, "aggregate", issue=AGG_BLOCKER)

    score = aggregate(panel(("B1", 1), ("B1", 1), ("B1", 1)), _FOUR_BAND, favourable_signals())
    assert score.agreement == pytest.approx(1.0), (
        f"a unanimous panel scored agreement {score.agreement!r} — perfect agreement is "
        "alpha = 1 (FR-AGG-04)"
    )


# --- TC-AGG-19 — the two-band degeneracy, pinned because it is the default band shape ---------


def test_tc_agg_19_two_band_unanimous_alpha_is_one_by_construction_with_the_degeneracy_marker():
    """`TC-AGG-19` (`FR-AGG-04`, unit / rung 0, degenerate, P0) — on a **two-band**
    criterion (the default band shape), three unanimous verdicts give α = 1.0 **by
    construction**, and the score carries the degeneracy marker `M-STATS` needs. This
    pins §2.3 Q-03 / CT-AGG-17; it does not endorse the figure — the marker exists so no
    consumer renders 1.0 as if it were information."""
    aggregate = require(AGG_MODULE, "aggregate", issue=AGG_BLOCKER)
    ordinal_alpha = require(AGG_MODULE, "ordinal_alpha", issue=AGG_BLOCKER)

    two_band = criterion([band("not met", 0, 0.0), band("met", 1, 1.0)],
                         criterion_id="C-DEGENERATE")
    verdicts = panel(("met", 1), ("met", 1), ("met", 1))

    alpha = ordinal_alpha(verdicts)
    assert alpha == 1.0, (
        f"ordinal_alpha on a unanimous two-band panel returned {alpha!r} — 1.0 by "
        "construction (the ordinal and nominal metrics coincide on two values); the "
        "design's TBD pins this behaviour, TC-AGG-19 exists to hold it still"
    )

    score = aggregate(verdicts, two_band, favourable_signals())
    assert score.agreement == pytest.approx(1.0), (
        f"the aggregated score carries agreement {score.agreement!r} for the same panel"
    )
    assert getattr(score, "agreement_degenerate", None) is True, (
        "the two-band degenerate agreement arrived without its degeneracy marker — "
        "TC-AGG-19: the return value is accompanied by the marker M-STATS needs "
        "(CT-AGG-17); the field name `agreement_degenerate` is the assumed pin and "
        "reconciles at #91"
    )
