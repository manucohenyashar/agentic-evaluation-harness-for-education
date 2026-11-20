"""`TC-AGG-32` (issue #896, FR-AGG-22, CT-AGG-14 amended) — holistic is harder, not never.

Statistical-validity test plan §3.5 (story T3). At the frozen defaults — atomic bar 0.80,
holistic bar 0.90, uncited multiplier 0.80, holistic multiplier 0.95 — `aggregate` (called with
`config=None`, i.e. M-AGG's declared constants, and again with the run-frozen `AggKnobs` the
pipeline passes) routes:

| # | Cell | Expected |
|---|---|---|
| (a) | holistic, 3 judges unanimous, all cited, no cap | `auto`, confidence 0.95 |
| (b) | holistic, 2 of 3 agree | not `auto` |
| (c) | holistic, unanimous, one adverse cap fires (each of the six) | not `auto`, confidence = the cap |
| (d) | holistic, unanimous, one verdict uncited | not `auto`, confidence 0.76 |
| (e) | holistic, confidence 0.8999 / 0.9000 | `queued` / `auto` — CT-AGG-14's `>=`, both sides |
| (f) | atomic rows of the reachability table | as before, and unmoved by the holistic multiplier |

Plus the Hypothesis arm (§4.4): for any holistic cell with a dissent — any legal band set (2, 4
or 6 bands, FR-PKG-06), panels of 3 and 5 — routing is never `auto` at the defaults.

(e)'s confidence is set through the holistic multiplier itself on a unanimous panel (α = 1.0),
so the figure is exactly the knob: 1.0 × 0.8999 and 1.0 × 0.9 are exact in binary floating point
against the 0.9 bar the comparison reads.

**Isolation: rung 0** — pure calls. **Written ahead of implementation: no** — #865 (PR #928).

Markers. None, `property` on the Hypothesis arm (fast tier).
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aeh.agg import aggregate
from aeh.conf import AggKnobs
from tests.support.agg_vocabulary import DESIGN_CAPS, band, criterion, panel, signals, verdict

_BANDS = [band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0), band("B3", 3, 6.0)]
HOLISTIC = criterion(_BANDS, scoring_model="holistic")
ATOMIC = criterion(_BANDS)
UNANIMOUS = panel(("B3", 3), ("B3", 3), ("B3", 3))
TWO_OF_THREE = panel(("B3", 3), ("B3", 3), ("B2", 2))

#: The frozen defaults as a run freezes them (FR-AGG-21) — the value the pipeline passes.
FROZEN_DEFAULTS = AggKnobs(auto_threshold_atomic=0.80, auto_threshold_holistic=0.90,
                           uncited_multiplier=0.80, holistic_multiplier=0.95)
#: Both readings of "the defaults": M-AGG's constants (`config=None`) and the frozen knobs.
CONFIGS = pytest.mark.parametrize("config", [None, FROZEN_DEFAULTS],
                                  ids=["module-constants", "frozen-knobs"])

CAPS = ("spans_verified", "evidence_present", "sufficiency_flag", "ocr_overlap_risk",
        "described_evidence", "extractor_disagreement")
#: The adverse reading of each signal (`None` — "not measured" — is adverse too, fail-closed).
ADVERSE = {"spans_verified": False, "evidence_present": False, "sufficiency_flag": True,
           "ocr_overlap_risk": True, "described_evidence": True, "extractor_disagreement": True}


@CONFIGS
def test_tc_agg_32a_unanimous_cited_uncapped_holistic_auto_accepts(config):
    score = aggregate(UNANIMOUS, HOLISTIC, signals(), config=config)
    assert (score.routing, score.state) == ("auto", "final"), score
    assert score.confidence == pytest.approx(0.95), score.confidence
    assert not score.caps_fired, score.caps_fired


@CONFIGS
def test_tc_agg_32b_two_of_three_holistic_is_not_auto(config):
    score = aggregate(TWO_OF_THREE, HOLISTIC, signals(), config=config)
    assert score.routing != "auto", score
    assert score.confidence < 0.90, score.confidence


@CONFIGS
@pytest.mark.parametrize("cap", CAPS)
def test_tc_agg_32c_one_adverse_cap_keeps_unanimous_holistic_off_auto(config, cap):
    score = aggregate(UNANIMOUS, HOLISTIC, signals(**{cap: ADVERSE[cap]}), config=config)
    assert score.routing != "auto", (cap, score)
    assert cap in score.caps_fired, (cap, score.caps_fired)
    assert score.confidence == pytest.approx(DESIGN_CAPS[cap]), (cap, score.confidence)


@CONFIGS
def test_tc_agg_32d_an_uncited_verdict_keeps_unanimous_holistic_off_auto(config):
    uncited = [verdict("B3", 3), verdict("B3", 3), verdict("B3", 3, cited=False)]
    score = aggregate(uncited, HOLISTIC, signals(), config=config)
    assert score.routing != "auto", score
    assert score.confidence == pytest.approx(1.0 * 0.80 * 0.95), score.confidence


@pytest.mark.parametrize("multiplier, routing", [(0.8999, "queued"), (0.9000, "auto")])
def test_tc_agg_32e_the_holistic_bar_is_met_at_exactly_0_90(multiplier, routing):
    """CT-AGG-14's comparison rule (`confidence >= threshold`), both sides of 0.90."""
    knobs = AggKnobs(auto_threshold_atomic=0.80, auto_threshold_holistic=0.90,
                     uncited_multiplier=0.80, holistic_multiplier=multiplier)
    score = aggregate(UNANIMOUS, HOLISTIC, signals(), config=knobs)
    assert score.confidence == multiplier, score.confidence  # exact: α = 1.0, no cap
    assert score.routing == routing, (multiplier, score)


#: The atomic rows of the reachability table (CT-AGG-06/14), at the defaults:
#: `(cell, verdicts, signals overrides, expected confidence, expected routing)`.
ATOMIC_ROWS = (
    ("unanimous", UNANIMOUS, {}, 1.0, "auto"),
    ("uncited unanimous", [verdict("B3", 3), verdict("B3", 3), verdict("B3", 3, cited=False)],
     {}, 0.80, "auto"),
    ("spans capped", UNANIMOUS, {"spans_verified": False}, 0.25, "queued"),
    ("ocr capped", UNANIMOUS, {"ocr_overlap_risk": True}, 0.30, "queued"),
)


@CONFIGS
@pytest.mark.parametrize("cell, verdicts, overrides, confidence, routing", ATOMIC_ROWS,
                         ids=[row[0] for row in ATOMIC_ROWS])
def test_tc_agg_32f_atomic_rows_are_unchanged(config, cell, verdicts, overrides, confidence,
                                               routing):
    score = aggregate(verdicts, ATOMIC, signals(**overrides), config=config)
    assert (score.confidence, score.routing) == (pytest.approx(confidence), routing), (cell, score)
    # The holistic multiplier never reaches an atomic cell: moving it moves nothing here.
    moved = AggKnobs(auto_threshold_atomic=0.80, auto_threshold_holistic=0.90,
                     uncited_multiplier=0.80, holistic_multiplier=0.5)
    again = aggregate(verdicts, ATOMIC, signals(**overrides), config=moved)
    assert (again.confidence, again.routing) == (score.confidence, score.routing), cell


@pytest.mark.property
@settings(max_examples=300, deadline=None)
@given(data=st.data(), band_count=st.sampled_from((2, 4, 6)), size=st.sampled_from((3, 5)))
def test_tc_agg_32_property_a_holistic_cell_with_a_dissent_is_never_auto(data, band_count,
                                                                         size):
    ordinals = data.draw(
        st.lists(st.integers(0, band_count - 1), min_size=size, max_size=size)
        .filter(lambda xs: len(set(xs)) > 1), label="panel ordinals")
    holistic = criterion([band(f"B{i}", i, float(i)) for i in range(band_count)],
                         scoring_model="holistic")
    verdicts = [verdict(f"B{o}", o) for o in ordinals]
    for config in (None, FROZEN_DEFAULTS):
        score = aggregate(verdicts, holistic, signals(), config=config)
        assert score.routing != "auto", (band_count, ordinals, score.confidence)
