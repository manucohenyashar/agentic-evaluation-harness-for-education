"""`TC-AGG-01` — points are derived once from the aggregated band, and never averaged.

Test plan §5.12 (block form), issue #94 (TS-35). Traces to `FR-AGG-01`, `FR-AGG-02`,
`NFR-AGG-02`; RISK-05 (Critical) — "points are derived per judge and averaged rather than
the median band being mapped once", detectability **No**, because the wrong number looks
fine. Written ahead of #91 (test plan §8.2): every case here fails only through
`NotImplementedYet` naming #91 until the aggregation surface lands.

**The fixture is deliberately non-linear.** Bands 0..3 map to points 0, 1, 3, 6: a linear
mapping makes median-then-map and map-then-average agree on every symmetric panel, so a
suite of linear cases would pass against the broken implementation. Step 1 of the plan's
block form is kept as a **negative control**: on `[B0, B2, B3]` the two methods coincide at
3.0, so that case alone proves nothing — a suite containing only cases like it would pass
against a broken implementation.

**Interface assumed of #91** is declared in `tests/support/agg_vocabulary.py`; the
step-5 source predicate is declared below at its test.

Isolation: rung 0 — pure functions and value stand-ins only; the socket guard is autouse
and nothing here touches a store.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.agg_vocabulary import AGG_BLOCKER, band, criterion, favourable_signals, panel
from tests.support.impl import AGG_MODULE, require

pytestmark = [pytest.mark.writtenahead]


def _four_band_criterion():
    """The plan's fixture: 4 bands mapping to 0, 1, 3, 6 — non-linear on purpose."""
    return criterion(
        [
            band("B0", 0, 0.0),
            band("B1", 1, 1.0),
            band("B2", 2, 3.0),
            band("B3", 3, 6.0),
        ]
    )


def _aggregator():
    aggregate = require(AGG_MODULE, "aggregate", issue=AGG_BLOCKER)
    return aggregate, _four_band_criterion()


# --- steps 2 and 3 — the cases that distinguish median-then-map from map-then-average ---------


def test_tc_agg_01_points_come_from_the_median_band_not_the_average():
    """`TC-AGG-01` steps 2–3 (`FR-AGG-01`, `FR-AGG-02`, unit / rung 0, P0) — on a
    non-linear point table the median band's points and the per-judge average differ,
    and the score carries the median band's, never the average."""
    aggregate, crit = _aggregator()

    # Step 2: median ordinal 1 -> 1 point. Map-then-average gives (0+1+6)/3 = 2.33.
    score = aggregate(panel(("B0", 0), ("B1", 1), ("B3", 3)), crit, favourable_signals())
    assert score.band == "B1"
    assert score.points == 1.0, (
        f"a [B0, B1, B3] panel on points 0/1/3/6 scored {score.points} — the median band "
        "is B1 (1 point); the map-then-average defect scores 2.33 (RISK-05, FR-AGG-02)"
    )
    assert score.points != pytest.approx((0.0 + 1.0 + 6.0) / 3)
    assert score.judge_count == 3
    assert score.band_spread == 3, (
        f"band_spread is {score.band_spread!r}; the ordinal distance from B0 to B3 is 3 "
        "(FR-AGG-01)"
    )

    # Step 3: median ordinal 3 -> 6 points. Map-then-average gives (6+6+0)/3 = 4.0.
    score = aggregate(panel(("B3", 3), ("B3", 3), ("B0", 0)), crit, favourable_signals())
    assert score.band == "B3"
    assert score.points == 6.0, (
        f"a [B3, B3, B0] panel on points 0/1/3/6 scored {score.points} — the median band "
        "is B3 (6 points); the map-then-average defect scores 4.0 (RISK-05, FR-AGG-02)"
    )
    assert score.points != pytest.approx((6.0 + 6.0 + 0.0) / 3)
    assert score.modal_band == "B3", (
        f"modal band is {score.modal_band!r}; two of three judges said B3 (FR-AGG-01)"
    )
    assert score.band_spread == 3


def test_tc_agg_01_negative_control_where_the_two_methods_coincide():
    """`TC-AGG-01` step 1, kept as the plan's negative control — on `[B0, B2, B3]` the
    median band's points and the per-judge average **coincide** at 3.0, so this case
    alone proves nothing; it exists so the suite cannot quietly lose the non-linear
    fixture that steps 2–3 depend on."""
    aggregate, crit = _aggregator()

    score = aggregate(panel(("B0", 0), ("B2", 2), ("B3", 3)), crit, favourable_signals())
    assert score.band == "B2"
    assert score.points == pytest.approx(3.0), (
        f"a [B0, B2, B3] panel scored {score.points} — median band B2 maps to 3.0; note "
        "the map-then-average answer is also 3.0, which is why this case is a control "
        "and not evidence (test plan §5.12 TC-AGG-01 step 1)"
    )
    assert score.band_spread == 3


# --- the block form's Variants line ------------------------------------------------------------


def test_tc_agg_01_variants_single_verdict_two_band_and_even_rejection():
    """`TC-AGG-01` Variants — a single verdict; a 2-band criterion; an even-length list,
    which FR-AGG-03 must reject before the median is ever taken."""
    aggregate = require(AGG_MODULE, "aggregate", issue=AGG_BLOCKER)
    even_panel_error = require(AGG_MODULE, "EvenPanelError", issue=AGG_BLOCKER)
    crit = _four_band_criterion()

    single = aggregate(panel(("B2", 2)), crit, favourable_signals())
    assert single.band == "B2" and single.points == pytest.approx(3.0), (
        f"a single B2 verdict scored {single.points!r}/{single.band!r} — with one judge "
        "the panel's band is the verdict's own (FR-AGG-01)"
    )
    assert single.judge_count == 1 and single.band_spread == 0

    two_band = criterion([band("not met", 0, 0.0), band("met", 1, 1.0)],
                         criterion_id="C-TWO")
    score = aggregate(panel(("not met", 0), ("met", 1), ("met", 1)),
                      two_band, favourable_signals())
    assert score.band == "met" and score.points == pytest.approx(1.0), (
        f"a two-band [not met, met, met] panel scored {score.points!r}/{score.band!r} — "
        "median ordinal 1 maps to 1.0 (the default band shape is even-counted, only the "
        "panel may not be)"
    )

    for even in (panel(("B0", 0), ("B1", 1)), panel(("B0", 0), ("B1", 1), ("B2", 2), ("B3", 3))):
        with pytest.raises(even_panel_error) as refused:
            aggregate(even, crit, favourable_signals())
        assert type(refused.value).__name__ == "EvenPanelError", (
            f"an even panel of {len(even)} was refused by "
            f"{type(refused.value).__name__!r} — FR-AGG-03's exact exception oracle is "
            "pinned on EvenPanelError (assumed name, reconciles at #91)"
        )


# --- step 5 — the source-level single-mapping assertion (NFR-AGG-02's acceptance form) ---------

#: The predicate this test applies, declared because a source scan is only as honest as
#: its convention. "In exactly one place in the source" (the Goal) is asserted
#: structurally where it is structural — one *definition* of the mapping, in `M-PKG`
#: (CT-PKG-05: `points_for_band` is the single canonical mapping and the only sanctioned
#: reader of the band table's points) — and behaviourally where it is behavioural: the
#: worked examples above pin that the band `M-AGG` maps is the *median* — on a
#: non-linear table, map-then-average and any modal echo produce different points — and
#: `tests/artifact/test_agg_single_mapping.py` scans the source for a second definition
#: or a direct band-table read. A lexical count of exactly one mention would condemn the
#: real call shape (`PackageCatalog.points_for_band` is a method:
#: `catalog.points_for_band(...)` and `from aeh.pkg import points_for_band` differ in
#: mention count), and a same-band repeat lookup is idempotent — unobservable and
#: harmless. What fires on the defect the plan names: a reimplementation in `M-AGG` that
#: never routes through the canonical mapping, or a second definition anywhere.


def test_tc_agg_01_step5_the_band_to_points_mapping_is_applied_in_exactly_one_place(repo_root):
    """`TC-AGG-01` step 5 (`NFR-AGG-02`, artifact assertion, P0) — `M-AGG` routes through
    the canonical mapping rather than reimplementing it, and the mapping is defined in
    exactly one module."""
    agg_module = require(AGG_MODULE, issue=AGG_BLOCKER)
    agg_source = Path(agg_module.__file__).read_text(encoding="utf-8")

    assert "points_for_band" in agg_source, (
        "M-AGG never references points_for_band — the aggregate must route through "
        "M-PKG's canonical mapping, the only sanctioned reader of the band table's "
        "points (CT-PKG-05, NFR-AGG-02, TC-AGG-01 step 5); a reimplementation of the "
        "mapping inside M-AGG is exactly the second place this guards against"
    )

    tree = repo_root / "src" / "aeh"
    defining = [
        path.name
        for path in sorted(tree.glob("*.py"))
        if "def points_for_band" in path.read_text(encoding="utf-8")
    ]
    assert defining == ["pkg.py"], (
        f"points_for_band is defined in {defining} — the band→points mapping exists in "
        "exactly one place in the source, M-PKG (NFR-AGG-02's acceptance form; "
        "CT-PKG-05)"
    )
