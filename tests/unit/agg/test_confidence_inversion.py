"""`TC-AGG-06` — a unanimous panel on unverified evidence yields low confidence and routes.

Test plan §5.12 (full block form), issue #95 (TS-36). Traces to `FR-AGG-05`,
`FR-AGG-13`, `NFR-AGG-04`; RISK-01 (Critical) — the single assertion the design says
makes R19 testable, and what ADR-10 / CT-AGG-05 call "the single most important test in
this module". Written ahead of #92 (the cap table and the recorded integrity inputs;
the `aggregate` core it drives is #91's — the same key the `#76 forged evidence` entry
uses, with the same recorded residual weakness).

**The oracle is an invariant, not an expected value.** For any combination of the six
M-INTEG signals, `confidence <= min(applicable caps)`. A cap is a `min`, never a penalty
term, so **no amount of panel agreement can lift confidence past one** — that
distinction is the whole of ADR-10, and it is what a weighted-sum implementation would
silently fail while every individual expected-value check still passed. Two structural
consequences the cases below pin separately:

- the 64-cell sweep (step 4) asserts the invariant against the **injected** cap table
  (Q-04: injected as configuration, never test literals);
- the unanimity-vs-cap cases assert *distinctive injected caps* (0.313/0.414/… —
  numbers no tuning table would choose) come back **exactly** — one per signal — and,
  for the 0.313 limb, for a unanimous panel and a split panel alike. A penalty-term
  implementation fails the second limb: subtracting the same penalty from different
  base confidences lands on different values.

Isolation: rung 0 — pure function, no doubles beyond the value objects of
`tests/support/agg_vocabulary.py`. Interface assumed of #91/#92: module-level
`aggregate(verdicts, criterion, signals, *, config=None) -> score`, the score carrying
`.confidence`, `.routing` and the four FR-AGG-13 integrity fields
(`.spans_verified`, `.evidence_present`, `.sufficiency_flag`, `.ocr_overlap_risk`),
and `aggregate` accepting the cap table + thresholds through `config`.
"""

from __future__ import annotations

import itertools

import pytest

from tests.support.agg_vocabulary import (
    DESIGN_CAPS,
    FAVOURABLE,
    band,
    criterion,
    panel,
    signals,
    agg_config,
)
from tests.support.impl import AGG_MODULE, require

pytestmark = [pytest.mark.writtenahead]

#: The case's fixture: three verdicts, all top band of a 4-band criterion, all cited,
#: all with high `self_confidence` — the maximally agreeing panel the inversion must
#: not be able to outrun.
_TOP_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                       band("B3", 3, 6.0)])
_UNANIMOUS_TOP = panel(("B3", 3), ("B3", 3), ("B3", 3))

#: A split panel at the same band distance as TC-AGG-05's adjacent fixture — for the
#: unanimity-vs-cap case, which must score the SAME under a binding cap as the
#: unanimous one (α = 0.52 by the TC-AGG-05 convention, above the 0.313 cap).
_SPLIT = panel(("B0", 0), ("B1", 1), ("B1", 1), ("B1", 1), ("B2", 2))


def _aggregate(sig):
    """The one seam every case enters through; the blocker is named once, here."""
    return require(
        AGG_MODULE, "aggregate", "AGG_AUTO_THRESHOLD_ATOMIC", issue="#92"
    )(_UNANIMOUS_TOP, _TOP_BAND, sig, config=agg_config())


def test_tc_agg_06_fully_favourable_unanimous_panel_is_high_confidence_and_auto_acceptable():
    """`TC-AGG-06` step 1 (`FR-AGG-05`, unit / rung 0, P0) — with all signals
    favourable, the unanimous top-band panel is high-confidence and may auto-accept:
    the baseline every adverse case is measured against."""
    aggregate = require(
        AGG_MODULE, "aggregate", "AGG_AUTO_THRESHOLD_ATOMIC", issue="#92"
    )
    score = aggregate(_UNANIMOUS_TOP, _TOP_BAND, signals(), config=agg_config())

    assert score.confidence == pytest.approx(1.0), (
        f"a unanimous cited top-band panel on fully favourable signals scored "
        f"{score.confidence!r} — the favourable baseline is the agreement figure itself "
        "(α = 1) with no cap binding (FR-AGG-05's shape)"
    )
    assert score.routing == "auto", (
        f"the fully-favourable unanimous result routed {score.routing!r} — step 1's "
        "expected result: high-confidence AND may auto-accept (test plan §5.12)"
    )


@pytest.mark.parametrize("field", list(DESIGN_CAPS))
def test_tc_agg_06_one_adverse_signal_caps_the_unanimous_panel_and_routes(field):
    """`TC-AGG-06` steps 2–3 (`FR-AGG-05`, unit / rung 0, decision table, P0) — each
    integrity signal varied alone from the favourable baseline: the confidence is
    capped to that signal's injected cap and the result does not route to `auto`. The
    adverse value is read from the vocabulary's shared polarity map (`FAVOURABLE`),
    so the cell can never drift into testing the favourable reading by accident
    (the step-2 input is `spans_verified = false`, not `true`)."""
    score = _aggregate(signals(**{field: not FAVOURABLE[field]}))

    cap = DESIGN_CAPS[field]
    assert score.confidence <= pytest.approx(cap), (
        f"{field} adverse on an otherwise unanimous cited panel scored "
        f"{score.confidence!r} against its injected cap {cap!r} — the inversion is a "
        "hard cap, so the panel's unanimity cannot lift the confidence past it "
        "(FR-AGG-05; ADR-10; CT-AGG-05)"
    )
    assert score.routing != "auto", (
        f"{field} adverse left routing at 'auto' — step 5's routing limb: where a cap "
        "fired below the auto-accept threshold the result may not auto-accept"
    )


def test_tc_agg_06_all_sixty_four_signal_combinations_stay_at_or_below_their_minimum_cap():
    """`TC-AGG-06` step 4 (`FR-AGG-05`, unit / rung 0, exhaustive over the signal
    space, P0) — the sweep: for every combination of the six booleans, the confidence
    never exceeds the minimum of the caps that apply, and never exceeds the
    all-favourable baseline. A weighted-sum implementation can pass every
    single-signal case above and still fail here; this cell is the one that catches it.
    """
    aggregate = require(
        AGG_MODULE, "aggregate", "AGG_AUTO_THRESHOLD_ATOMIC", issue="#92"
    )
    baseline = aggregate(_UNANIMOUS_TOP, _TOP_BAND, signals(), config=agg_config())

    for values in itertools.product([True, False], repeat=len(DESIGN_CAPS)):
        combo = dict(zip(DESIGN_CAPS, values))
        score = aggregate(
            _UNANIMOUS_TOP, _TOP_BAND, signals(**combo), config=agg_config()
        )
        applicable = [
            DESIGN_CAPS[name]
            for name, value in combo.items()
            if value != FAVOURABLE[name]
        ]
        ceiling = min(applicable) if applicable else 1.0
        assert score.confidence <= pytest.approx(ceiling), (
            f"{combo}: confidence {score.confidence!r} exceeds the minimum applicable "
            f"cap {ceiling!r} — a cap is a min, not a penalty term, so no combination "
            "of panel agreement and favourable signals may outrun the worst adverse "
            "signal (FR-AGG-05, ADR-10)"
        )
        assert score.confidence <= baseline.confidence, (
            f"{combo}: confidence {score.confidence!r} exceeds the all-favourable "
            f"baseline {baseline.confidence!r} — worsening signals can never raise "
            "confidence (the monotonicity limb of the same invariant)"
        )
        if applicable:
            assert score.routing != "auto", (
                f"{combo}: a cap below the auto-accept threshold fired and routing "
                "stayed 'auto' — step 5's routing limb (test plan §5.12)"
            )


def test_tc_agg_06_the_named_variant_three_unanimous_verdicts_on_unverified_evidence():
    """`TC-AGG-06` Variants (`FR-AGG-05`, unit / rung 0, P0) — the case the design
    names explicitly: three unanimous verdicts with `spans_verified = False` must
    produce a low-confidence, routed result. RISK-01's single assertion — the one that
    makes R19 testable."""
    score = _aggregate(signals(spans_verified=False))

    assert score.confidence <= pytest.approx(DESIGN_CAPS["spans_verified"]), (
        f"three unanimous top-band verdicts on unverified evidence scored "
        f"{score.confidence!r} — this is RISK-01: a confident, agreeing panel on "
        "hallucinated evidence must come out LOW, not high (FR-AGG-05)"
    )
    assert score.routing != "auto", (
        f"the unverified-evidence unanimous result routed {score.routing!r} — it must "
        "be routed (reviewed/queued/triage), never auto-accepted (RISK-01)"
    )


def test_tc_agg_06_a_missing_signal_is_treated_as_adverse_fail_closed():
    """`TC-AGG-06` Variants (`FR-AGG-05`, `NFR-INTEG-03`, unit / rung 0, P0) — a
    *missing* integrity signal (`None` = not measured) is treated as adverse
    (fail-closed), never as favourable and never as absent: the same cap binds as if
    the signal had been measured adverse."""
    for field, cap in DESIGN_CAPS.items():
        score = _aggregate(signals(**{field: None}))
        assert score.confidence <= pytest.approx(cap), (
            f"{field} missing (None) scored {score.confidence!r} against the cap "
            f"{cap!r} a measured-adverse value would get — a missing signal is adverse, "
            "not favourable and not absent (fail-closed, NFR-INTEG-03)"
        )
        assert score.routing != "auto", (
            f"{field} missing (None) left routing at 'auto' — fail-closed caps route, "
            "they do not pass"
        )


@pytest.mark.parametrize(
    ("field", "injected"),
    [
        ("spans_verified", 0.313),
        ("evidence_present", 0.414),
        ("sufficiency_flag", 0.515),
        ("ocr_overlap_risk", 0.616),
        ("described_evidence", 0.717),
        ("extractor_disagreement", 0.818),
    ],
)
def test_tc_agg_06_unanimity_cannot_outrun_a_cap_the_injected_table_is_honoured_exactly(
    field, injected
):
    """`TC-AGG-06` Oracle (`FR-AGG-05`, `NFR-AGG-04`, unit / rung 0, exact value per
    cell, P0) — with a *distinctive* injected cap for `field` (0.313/0.414/… — numbers
    no tuning table would choose; every other cap held non-binding at 0.99) the
    confidence comes back exactly that value for a unanimous panel: the cap table is
    honoured per signal, not approximated by a penalty term. An implementation that
    hardcodes the design numbers and ignores `config.caps` fails five of the six
    cells (Q-04: these are injected tuning parameters, not literals)."""
    aggregate = require(
        AGG_MODULE, "aggregate", "AGG_AUTO_THRESHOLD_ATOMIC", issue="#92"
    )
    config = agg_config(
        auto_threshold_atomic=0.90,
        caps={name: injected if name == field else 0.99 for name in DESIGN_CAPS},
    )

    unanimous = aggregate(
        _UNANIMOUS_TOP, _TOP_BAND, signals(**{field: not FAVOURABLE[field]}),
        config=config,
    )

    assert unanimous.confidence == pytest.approx(injected), (
        f"the unanimous panel under the {injected!r} injected cap for {field} scored "
        f"{unanimous.confidence!r} — the cap must come back exactly: a min, not a "
        "penalty term, so unanimity cannot lift the value past it and a penalty term "
        "lands somewhere else entirely (ADR-10; Q-04's injected cap table)"
    )


def test_tc_agg_06_above_a_binding_cap_agreement_buys_nothing():
    """`TC-AGG-06` Oracle, second limb (`FR-AGG-05`, unit / rung 0, exact value, P0) —
    for a split panel whose α (0.52 by the TC-AGG-05 hand-computed convention) sits
    ABOVE the 0.313 injected cap, the confidence is the cap exactly: above a binding
    cap, agreement changes nothing, so the unanimous and the split panel land on the
    same value (the distinction a penalty term cannot satisfy)."""
    aggregate = require(
        AGG_MODULE, "aggregate", "AGG_AUTO_THRESHOLD_ATOMIC", issue="#92"
    )
    config = agg_config(
        auto_threshold_atomic=0.90,
        caps={name: 0.313 if name == "spans_verified" else 0.99
              for name in DESIGN_CAPS},
    )

    unanimous = aggregate(
        _UNANIMOUS_TOP, _TOP_BAND, signals(spans_verified=False), config=config
    )
    split = aggregate(
        _SPLIT, _TOP_BAND, signals(spans_verified=False), config=config
    )

    assert unanimous.confidence == pytest.approx(0.313), (
        f"the unanimous panel under the 0.313 injected cap scored "
        f"{unanimous.confidence!r} — the cap comes back exactly (ADR-10)"
    )
    assert split.confidence == pytest.approx(0.313), (
        f"the split panel (α = 0.52, above the cap) scored {split.confidence!r} — "
        "above a binding cap, agreement changes nothing: the unanimous and the split "
        "panel must land on the same value"
    )


def test_tc_agg_06_the_integrity_inputs_are_recorded_on_the_score_row():
    """`TC-AGG-06` step 6 (`FR-AGG-13`, `NFR-AGG-04`, unit / rung 0, P0) — the four
    recorded integrity inputs are on the returned score, so the confidence is
    reconstructible from stored data alone (TC-AGG-15 asserts the stored half)."""
    sig = signals(sufficiency_flag=True)
    score = _aggregate(sig)

    assert score.spans_verified is True, "spans_verified was not recorded on the score row (FR-AGG-13)"
    assert score.evidence_present is True, "evidence_present was not recorded on the score row (FR-AGG-13)"
    assert score.sufficiency_flag is True, (
        "the varied signal (sufficiency_flag) was not recorded on the score row — "
        "step 6: every score row carries its integrity inputs (FR-AGG-13)"
    )
    assert score.ocr_overlap_risk is False, "ocr_overlap_risk was not recorded on the score row (FR-AGG-13)"
