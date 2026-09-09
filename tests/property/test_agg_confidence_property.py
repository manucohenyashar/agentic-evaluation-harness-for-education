"""`TC-AGG-10` — confidence is monotone in the signals and never outruns the minimum cap.

Test plan §5.12 (row form: Property / rung 0), issue #95 (TS-36). Traces to
`FR-AGG-05`. Written ahead of #92 (the caps; the `aggregate` core is #91's — the
`#76 forged evidence` key precedent, with the same recorded residual weakness).

`TC-AGG-06` sweeps the 64 boolean combinations against the unanimous fixture; this
property generalizes the same invariant over **generated verdict sets**: odd panel
sizes 1..5, any band shape of the fixture criterion, and independent signal
combinations. The oracle is stated against the **injected** cap table (Q-04), never
against literals:

- **monotone non-increasing as signals worsen**: for a panel and two signal
  combinations where the second is at least as adverse as the first on every field,
  `conf(second) <= conf(first)`. Worsening is fieldwise — flipping any favourable
  signal to its adverse reading can never raise the confidence. A penalty-term
  implementation fails this the moment a second adverse signal is added on top of a
  first whose penalty already saturated.
- **never exceeds the minimum applicable cap**: `conf <= min(caps of the adverse
  signals)`, for every generated input — and in the no-adverse-signal case the ceiling
  is the design's base figure itself: `ordinal_alpha` for a panel of three or more
  (§3.12's structure: `base = ordinal_alpha(verdicts)`, and no multiplier applies to
  the generated all-cited atomic panels), the domain bound 1.0 for the single-judge
  shape, whose base is the band-position prior.

Isolation: rung 0 — pure function. Interface assumed of #91/#92: module-level
`aggregate(verdicts, criterion, signals, *, config=None)`; the same assumed surface
`tests/unit/agg/test_confidence_inversion.py` declares.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

import pytest

from tests.support.agg_vocabulary import (
    DESIGN_CAPS,
    FAVOURABLE as _FAVOURABLE,
    band,
    criterion,
    signals,
    verdict,
    agg_config,
)
from tests.support.impl import AGG_MODULE, require

pytestmark = [pytest.mark.writtenahead]

#: The fixture criterion — the plan's 4-band shape; the property varies the panel, not
#: the band definition.
_FOUR_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                        band("B3", 3, 6.0)])
_BAND_NAMES = [b.band for b in _FOUR_BAND.bands]
_ORDINALS = {b.band: b.ordinal for b in _FOUR_BAND.bands}

_signal_combo = st.fixed_dictionaries({name: st.booleans() for name in DESIGN_CAPS})
_panel = st.lists(
    st.sampled_from(_BAND_NAMES), min_size=1, max_size=5
).filter(lambda bands: len(bands) % 2 == 1)  # odd — even panels refuse (FR-AGG-03)


def _verdicts(panel_bands):
    return [verdict(name, _ORDINALS[name]) for name in panel_bands]


def _aggregate(panel_bands, sig):
    aggregate = require(
        AGG_MODULE, "aggregate", "AGG_AUTO_THRESHOLD_ATOMIC", issue="#92"
    )
    return aggregate(_verdicts(panel_bands), _FOUR_BAND, sig, config=agg_config())


def _worsen(combo: dict, decisions: dict) -> dict:
    """The second combination: every field adverse in `combo` stays adverse; every
    favourable field follows its `decisions` coin (True = worsened)."""
    out = {}
    for name, value in combo.items():
        if value != _FAVOURABLE[name]:
            out[name] = value
        else:
            out[name] = not _FAVOURABLE[name] if decisions[name] else value
    return out


@given(panel=_panel, first=_signal_combo, worsen=_signal_combo)
def test_tc_agg_10_confidence_is_monotone_non_increasing_as_signals_worsen(
    panel, first, worsen
):
    """`TC-AGG-10` (`FR-AGG-05`, property / rung 0, P0) — for a generated panel and a
    generated signal combination, the fieldwise-worsened combination's confidence is
    never higher."""
    worse = _worsen(first, worsen)
    base = _aggregate(panel, signals(**first))
    worse_score = _aggregate(panel, signals(**worse))

    assert worse_score.confidence <= base.confidence, (
        f"panel={panel} signals={first} -> {base.confidence!r}; worsened to {worse} "
        f"-> {worse_score.confidence!r} — worsening signals raised the confidence "
        "(FR-AGG-05: confidence is monotone non-increasing as signals worsen)"
    )


@given(panel=_panel, combo=_signal_combo)
def test_tc_agg_10_confidence_never_exceeds_the_minimum_applicable_cap(panel, combo):
    """`TC-AGG-10` (`FR-AGG-05`, property / rung 0, P0) — for every generated input,
    the confidence never exceeds the minimum applicable cap of the injected table.
    When no cap binds, the ceiling is the design's base figure: the agreement itself
    (`ordinal_alpha`) for a panel of three or more — no multiplier applies to the
    generated all-cited atomic panels — and the domain bound 1.0 for the
    single-judge shape, whose base is the band-position prior, a different figure."""
    score = _aggregate(panel, signals(**combo))

    applicable = [
        DESIGN_CAPS[name]
        for name, value in combo.items()
        if value != _FAVOURABLE[name]
    ]
    if applicable:
        ceiling = min(applicable)
    elif len(panel) >= 3:
        ordinal_alpha = require(AGG_MODULE, "ordinal_alpha", issue="#91")
        alpha = ordinal_alpha(_verdicts(panel))
        assert alpha is not None, (
            f"ordinal_alpha returned None for a {len(panel)}-judge panel on a 4-band "
            "criterion — the design defines α wherever there are pairable units "
            "(CT-AGG-04), and three or more verdicts on four bands are pairable"
        )
        ceiling = alpha
    else:
        ceiling = 1.0
    assert score.confidence <= pytest.approx(ceiling), (
        f"panel={panel} signals={combo}: confidence {score.confidence!r} exceeds the "
        f"minimum applicable cap {ceiling!r} — a cap is a min, not a penalty term "
        "(FR-AGG-05, ADR-10)"
    )
