"""`TC-AGG-C02` — mapped once, after aggregation, from the median band (§6.11.12).

`CT-AGG-02`'s prohibition carrying RISK-05: "Points are derived from the **aggregated**
band via `M-PKG.points_for_band` **exactly once, *after* aggregation** ... and no code
path maps per-judge bands to points and averages them." The value half (the non-linear
table, the median-vs-average negative control, the source-cardinality assertion that the
mapping is defined in exactly one place — `aeh.pkg:points_for_band`) is the shipped
sibling `tests/unit/agg/test_median_band_mapping.py` (`TC-AGG-01`); the hand-computed
panels are `tests/unit/agg/test_median_band_panels.py` (`TC-AGG-02`). Neither runs the
mapping's CALL SHAPE: a per-judge pre-mapping that then averages, a mapping applied to
the modal band instead of the median, or a mapping applied more than once per score row
all produce the same aggregate VALUE on many panels and are visible only in how many
times the canonical function ran and with which band. So this case wraps `aeh.agg`'s own
module-level binding of `points_for_band` with a counting delegator and asserts, per
aggregated criterion score:

- exactly **one** call, and its band argument is the **median** band — the mapping
  happened after aggregation, on the aggregated band, not on any judge's band;
- the value the score carries is that one call's return — never a re-mapping.

The wrapper is honest about its seam: `from aeh.pkg import points_for_band` gives
`aeh.agg` a module-level binding of its own (the sibling purity file's recorded blind
spot, read constructively here), so the count is taken where the clause says the
mapping is applied — the aggregator's call site — and the monkeypatch fixture restores
the binding. A second call site inside the module, or a re-import that bypasses the
binding, moves the count and the case fails.

The six-band case extends the value oracle to the even-scaled band set, the shape where
an average reading is most tempting: `band_count` is even and in 2..6 (CT-PKG-04), so a
six-band scale is a legal package, and the fixture's non-linear top (5.0 then 9.0) is
what separates a mean of points (3.0) and a mean of ordinals (2.0) from the median
band's 5.0 — the sibling's three-way discrimination on a scale its 4-band fixture
cannot reach.

Isolation: rung 0 — pure functions and doubles; the socket guard is autouse.
"""

from __future__ import annotations

import pytest

import aeh.agg
from tests.support.agg_vocabulary import (
    band,
    criterion,
    panel,
    signals,
    agg_config,
)
from tests.support.impl import AGG_MODULE, require

pytestmark = [pytest.mark.contract]

_SPLIT = panel(("B0", 0), ("B1", 1), ("B1", 1), ("B1", 1), ("B2", 2))
#: Median B1, modal B0 (the tie between B0 and B3 breaks toward the median's
#: neighbour B0) — so the band the MAPPING follows is visible as neither the mode
#: nor the panel's most common band.
_MODE_DISAGREES = panel(("B0", 0), ("B0", 0), ("B1", 1), ("B3", 3), ("B3", 3))
#: The six-band mean trap: median B4 (ordinal 4, points 5.0); a mean of points gives
#: 3.0, a mean of ordinals (2.4) maps to B2's 2.0 — both wrong.
_SIX_TRAP = panel(("B0", 0), ("B0", 0), ("B4", 4), ("B4", 4), ("B4", 4))
_TWO_LEFT = panel(("B1", 1), ("B3", 3))

_DETERMINISTIC_ROW = {
    "submission_id": "s-agg-c02",
    "criterion_id": "C-AGG",
    "band": "B2",
    "points": 3.0,
    "judge_count": 0,
    "agreement": None,
    "state": "final",
    "routing": "auto",
}


def _four_band():
    return criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                      band("B3", 3, 6.0)])


def _six_band():
    """A six-band scale (CT-PKG-04's even extreme) whose points are non-linear at
    the top — the shape where mean-of-points and mean-of-ordinals both miss."""
    return criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 2.0),
                      band("B3", 3, 3.0), band("B4", 4, 5.0), band("B5", 5, 9.0)])


class _CountingPoints:
    """A delegating counter over the aggregator's own binding of the canonical
    mapping — the call shape is the oracle; the mapping itself stays M-PKG's."""

    def __init__(self, original):
        self._original = original
        self.calls: list[tuple[tuple, str]] = []

    def __call__(self, bands, band_name):
        self.calls.append((tuple(bands), band_name))
        return self._original(bands, band_name)

    def value_for(self, crit, band_name):
        """The un-wrapped mapping's answer, for the exact-value assertions."""
        return self._original(crit.bands, band_name)


@pytest.fixture()
def counted(monkeypatch):
    """The module's `points_for_band` binding replaced with the counting
    delegator — restored by the monkeypatch fixture, so no other test sees the
    counter."""
    counter = _CountingPoints(aeh.agg.points_for_band)
    monkeypatch.setattr(aeh.agg, "points_for_band", counter)
    return counter


def test_tc_agg_c02_points_are_mapped_exactly_once_from_the_median_band(counted):
    """`TC-AGG-C02` (`CT-AGG-02`, `FR-AGG-02`, `NFR-AGG-02`, unit / rung 0, exact
    call count, P0) — one aggregated criterion score, exactly one call to the
    canonical mapping, on the median band, after aggregation."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")
    crit = _four_band()

    score = aggregate(_SPLIT, crit, signals(), config=agg_config())

    assert len(counted.calls) == 1, (
        f"aggregating one criterion score called the canonical mapping "
        f"{len(counted.calls)} times — points are derived from the aggregated band "
        "exactly once, after aggregation (CT-AGG-02, NFR-AGG-02); a per-judge "
        "pre-mapping or a re-mapped score shows up here as extra calls"
    )
    mapped_bands, mapped_band = counted.calls[0]
    assert mapped_band == "B1", (
        f"the mapping was applied to band {mapped_band!r} — the aggregated (median) "
        "band, not any judge's own band (FR-AGG-02, RISK-05)"
    )
    assert mapped_bands == tuple(crit.bands), (
        "the mapping was applied to a band set other than the criterion's declared "
        "one — the canonical mapping consumes the criterion's bands"
    )
    assert score.points == counted.value_for(crit, "B1") == 1.0, (
        f"the score carries points {score.points!r} — the one mapped value, never a "
        "re-mapping or an average over mappings (FR-AGG-02)"
    )


def test_tc_agg_c02_the_mapping_follows_the_median_band_not_the_modal_one(counted):
    """`TC-AGG-C02` (`CT-AGG-02`, unit / rung 0, exact value, P0) — on a panel whose
    modal band and median band differ, the points come from the MEDIAN band: the
    mapping is applied after aggregation, and the aggregation is the median."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")
    crit = _four_band()

    score = aggregate(_MODE_DISAGREES, crit, signals(), config=agg_config())

    assert score.band == "B1" and score.modal_band == "B0", (
        f"fixture bug: the panel's median ({score.band!r}) and modal ({score.modal_band!r}) "
        "band agree, so this case discriminates nothing"
    )
    assert len(counted.calls) == 1 and counted.calls[0][1] == "B1", (
        f"the mapping was called {counted.calls} — exactly once, on the median band "
        "B1, never on the modal band (FR-AGG-01's median reading; RISK-05)"
    )
    assert score.points == 1.0, (
        f"the score carries points {score.points!r} — the median band B1's points on "
        "the non-linear table, not the modal band B0's 0.0 (FR-AGG-02)"
    )


def test_tc_agg_c02_a_six_band_scale_maps_the_median_band_once(counted):
    """`TC-AGG-C02` (`CT-AGG-02`, unit / rung 0, exact value, P0) — the even-scaled
    band set, where an average reading is most tempting: the median band's points,
    mapped exactly once, on a scale a mean of points (3.0) and a mean of ordinals
    (2.4 → B2's 2.0) both miss."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")
    crit = _six_band()

    score = aggregate(_SIX_TRAP, crit, signals(), config=agg_config())

    assert score.band == "B4" and score.points == 5.0, (
        f"the six-band panel recorded {score.band!r} / {score.points!r} — the median "
        "band B4's 5.0, not a mean of points (3.0) or a mean of ordinals mapped "
        "through (2.0) (FR-AGG-01/02; the even-scale edge case)"
    )
    assert len(counted.calls) == 1, (
        f"the six-band aggregation called the canonical mapping {len(counted.calls)} "
        "times — exactly once, on the aggregated band (CT-AGG-02)"
    )


def test_tc_agg_c02_the_fallback_discard_maps_the_kept_band_exactly_once(counted):
    """`TC-AGG-C02` (`CT-AGG-02` × `FR-AGG-12`, unit / rung 0, P0) — the two-verdict
    discard maps exactly once too: the kept base judge's band, never both verdicts'
    bands."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")
    crit = _four_band()

    score = aggregate(_TWO_LEFT, crit, signals(), fallback=True, config=agg_config())

    assert score.band == "B1" and score.judge_count == 1, (
        f"the discard recorded {score.band!r} at judge_count {score.judge_count!r} — "
        "the base single-judge band stands (FR-AGG-12; TC-AGG-12's composition)"
    )
    assert len(counted.calls) == 1 and counted.calls[0][1] == "B1", (
        f"the discard called the canonical mapping {counted.calls} — exactly once, "
        "on the kept band: the discarded second verdict's band is never mapped "
        "(CT-AGG-02's exactly-once holds on the fallback path too)"
    )


def test_tc_agg_c02_a_deterministic_pass_through_maps_nothing(counted):
    """`TC-AGG-C02` (`CT-AGG-02` × `FR-AGG-10`, unit / rung 0, P0) — the
    deterministic pass-through echoes the row's own points and calls the canonical
    mapping zero times: the row arrived complete (FR-DET-03) and is never
    re-mapped."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")

    score = aggregate([], _four_band(), signals(), deterministic_score=_DETERMINISTIC_ROW,
                      config=agg_config())

    assert score.points == 3.0 and score.band == "B2", (
        "the pass-through changed the row's own mapping (FR-AGG-10)"
    )
    assert counted.calls == [], (
        f"the pass-through called the canonical mapping {counted.calls} — a row "
        "judged without a panel arrives complete and passes through unchanged, "
        "never re-mapped (FR-AGG-10, CT-AGG-02's exactly-once read on the "
        "pass-through path: the count is zero, not one)"
    )
