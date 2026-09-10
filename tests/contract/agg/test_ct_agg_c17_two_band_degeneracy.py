"""`TC-AGG-C17` — α on two bands carries less than it appears to, and says so (§6.11.12).

`CT-AGG-17` (**not promised**): "agreement is degenerate on two-band criteria, which
are the *default* band shape (§4.6 item 1). `ordinal_alpha` returns a number there
that carries less information than it appears to; `M-STATS` owns the resolution and
`M-CONSOLE` must not render it without one."

Two-band criteria are the COMMON case, not an edge case. This file carries the
producing side (`M-AGG`'s half of the clause):

- **the degenerate fixture** (the case's own oracle): a two-band unanimous panel
  scores α = 1.0 **by construction** — `D_o` = 0 under any per-pair distance — and
  the score carries `agreement_degenerate` so no consumer can mistake that 1.00
  for information. The same 1.00 from a ≥3-band panel is flagged differently: the
  flag is the only thing distinguishing two numbers that read alike;
- **the empty-ordinal-information differential**: on a two-band scale every
  disagreement is distance 1, so the ordinal metric's extra information is EMPTY —
  the same-shaped disagreement scores the same α the nominal metric would, where
  on a four-band scale adjacent and distant disagreement at the same raw rate
  score differently (`TC-AGG-C04`'s discriminating pair). The case asserts the
  degeneracy is detected, not that a value is correct — §7.4 keeps the resolution
  open, and `M-STATS` owns it;
- **the disclosure is conditional**: `describe_agreement` annotates a two-band
  figure with the degeneracy limitation and leaves a ≥3-band figure unannotated —
  suppress-or-annotate, never a bare 1.00 (RISK-30: undisclosed, it is the most
  confident number on the screen).

Cross-references, not duplicates: the consumer side of this clause is
`TC-STATS-C21`'s sweep — `M-CONSOLE`'s rendering (`render_agreement_block`, keyed
#123) and `M-STATS`'s detection (`figure.degenerate_band_shape`, keyed #115) are
asserted there, and `M-AGG`'s describe-not-equivocate runs there too. This file
holds the producer's arithmetic and its own conditional disclosure, which no
sibling asserts.

Isolation: rung 0 — pure calls; the socket guard is autouse.
"""

from __future__ import annotations

import pytest

from tests.support.agg_vocabulary import band, criterion, panel, signals, agg_config
from tests.support.impl import AGG_MODULE, require

pytestmark = [pytest.mark.contract]

#: §4.6 item 1's DEFAULT band shape: two bands, both used.
_TWO_BAND = criterion([band("A", 0, 2.0), band("B", 1, 4.0)])
_FOUR_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                        band("B3", 3, 6.0)])
_UNANIMOUS_TOP_2 = panel(("B", 1), ("B", 1), ("B", 1))
_UNANIMOUS_TOP_4 = panel(("B3", 3), ("B3", 3), ("B3", 3))


def test_tc_agg_c17_a_two_band_unanimity_is_a_construction_artifact_and_flagged():
    """`TC-AGG-C17` (`CT-AGG-17`, behaviour / rung 0, degenerate fixture, P0) —
    the two-band unanimous panel returns its number (α = 1.0, by construction)
    AND carries `agreement_degenerate`: the same 1.00 a four-band panel earns,
    flagged as the artifact it is. The clause is a non-promise about
    interpretation, not a prohibition on measurement — refusing or substituting
    `None` would be a different contract."""
    aggregate, ordinal_alpha = require(
        AGG_MODULE, "aggregate", "ordinal_alpha", issue="#91"
    )

    alpha = ordinal_alpha(_UNANIMOUS_TOP_2, _TWO_BAND)
    assert alpha == 1.0, (
        f"the two-band unanimous panel scored α = {alpha!r} — by construction "
        "(D_o = 0 under any per-pair distance) it must read 1.0; the "
        "non-promise is about what the number MEANS, not its value (CT-AGG-17)"
    )
    score = aggregate(_UNANIMOUS_TOP_2, _TWO_BAND, signals(), config=agg_config())
    assert score.agreement == pytest.approx(alpha), (
        "the score's agreement left the panel's α"
    )
    assert score.agreement_degenerate is True, (
        "the two-band score does not flag its degeneracy — RISK-30: α = 1 here "
        "is a construction artifact, and undisclosed it is the most confident "
        "number on the screen (CT-AGG-17)"
    )
    wide = aggregate(_UNANIMOUS_TOP_4, _FOUR_BAND, signals(), config=agg_config())
    assert wide.agreement_degenerate is False, (
        "the four-band score flags degeneracy — the flag must separate the two "
        "1.00s, not decorate every score (CT-AGG-17)"
    )


def test_tc_agg_c17_two_bands_leave_the_ordinal_metric_no_information():
    """`TC-AGG-C17` (`CT-AGG-17`, behaviour / rung 0, information differential,
    P0) — on a two-band scale the ordinal metric's extra information is EMPTY:
    every disagreement is distance 1, so the same raw disagreement scores the
    same α a nominal metric would. On four bands, the same raw rate scores
    differently by distance — the metric has something to say. The degeneracy is
    not that α is wrong on two bands; it is that there is nothing for the metric
    to add, which is what `agreement_degenerate` discloses."""
    ordinal_alpha = require(AGG_MODULE, "ordinal_alpha", issue="#91")

    # Same raw disagreement pattern (one dissenter in three), two scales.
    split_two = panel(("B", 1), ("B", 1), ("A", 0))
    split_two_alpha = ordinal_alpha(split_two, _TWO_BAND)

    # On two bands, ordinal and nominal distances coincide — the figure the
    # nominal metric would produce, computed inline over the same panel.
    disagreeing_pairs = sum(
        1
        for i in range(len(split_two))
        for j in range(i + 1, len(split_two))
        if split_two[i].ordinal != split_two[j].ordinal
    )
    total_pairs = len(split_two) * (len(split_two) - 1) // 2
    nominal = 1.0 - disagreeing_pairs / total_pairs
    assert split_two_alpha == pytest.approx(nominal), (
        f"the two-band α ({split_two_alpha!r}) differs from the nominal reading "
        f"({nominal!r}) — on two bands the ordinal metric has distance "
        "information the nominal metric lacks, which contradicts the "
        "degeneracy this clause discloses (CT-AGG-17)"
    )

    # Four bands, same raw disagreement rate: distance now matters.
    adjacent = panel(("B3", 3), ("B3", 3), ("B2", 2))
    distant = panel(("B3", 3), ("B3", 3), ("B0", 0))
    adjacent_alpha = ordinal_alpha(adjacent, _FOUR_BAND)
    distant_alpha = ordinal_alpha(distant, _FOUR_BAND)
    assert adjacent_alpha > distant_alpha, (
        f"adjacent-band α ({adjacent_alpha!r}) did not outrank distant-band α "
        f"({distant_alpha!r}) at the same raw rate — the ordinal information "
        "two-band criteria cannot carry (CT-AGG-04's discriminating pair, "
        "asserted here as the contrast the degeneracy removes)"
    )


def test_tc_agg_c17_the_producers_disclosure_is_conditional_on_the_degeneracy():
    """`TC-AGG-C17` (`CT-AGG-17`, behaviour / rung 0, conditional disclosure,
    P0) — `describe_agreement` annotates a two-band figure with the degeneracy
    limitation, and leaves a ≥3-band figure unannotated: the annotation tracks
    the actual band shape, so a suppressed-or-annotated figure is the rendered
    norm and a bare 1.00 has to arrive UNANNOTATED to be a violation. The
    consumer side (M-CONSOLE's rendering) is `TC-STATS-C21`'s sweep, keyed #123;
    M-STATS owns the resolution — this is the producing side's half."""
    describe_agreement = require(AGG_MODULE, "describe_agreement", issue="#91")

    degenerate_text = describe_agreement(
        figure={"ordinal_alpha": 1.0, "band_count": 2, "degenerate_band_shape": True},
        population="y9-2026-spring",
    )
    assert "coincides with the nominal" in degenerate_text, (
        f"the two-band figure's description reads: {degenerate_text!r} — the "
        "producer's own description must disclose that the ordinal metric "
        "coincides with the nominal one on two bands, a unanimous panel scores "
        "1.0 by construction (CT-AGG-17, RISK-30)"
    )

    wide_text = describe_agreement(
        figure={"ordinal_alpha": 1.0, "band_count": 4, "degenerate_band_shape": False},
        population="y9-2026-spring",
    )
    assert "coincides with the nominal" not in wide_text, (
        f"the four-band figure's description carries the degeneracy line: "
        f"{wide_text!r} — the annotation is conditional on the actual band "
        "shape; a ≥3-band figure is NOT degenerate and must not borrow the "
        "two-band caveat (CT-AGG-17)"
    )
