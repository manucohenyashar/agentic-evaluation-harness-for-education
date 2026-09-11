"""`TC-STATS-20` — the self-agreement pairing boundary, exact at 0.94/0.95/0.96.

Test plan §5.16 (`TC-STATS-20`), issue #120 (TS-43). Traces to `FR-STATS-18`.
The plan's row: *"A judge with measured self-agreement of 0.94, 0.95 and 0.96.
Above 0.95 the position-bias result from `FR-STATS-15` is **required to be
present** and the pair is reported together; high stability is never reported
as reassurance alone."*

`CT-STATS-C07` (the contract tier, `test_ct_stats_mvvp.py`) pins the pairing
*shape* — a judge at 0.97 carries its position-bias result — and deliberately
does not assert the boundary, because a stricter implementation that pairs
every judge violates nothing. This file pins the boundary itself, at the three
values the plan's row names:

- 0.94 and 0.95 are **not** pairing-required: `FR-STATS-18` says *exceeds*,
  so a judge at exactly the threshold goes unpaired and an implementation
  that pairs at ``>= 0.95`` fails here, not just in a code review;
- 0.96 **is**: and the finding is one record carrying both figures — the
  stability number beside the order-bias result, never the stability number
  alone, because 0.97 is the most reassuring figure in the protocol and it is
  entirely compatible with a judge that assigns whatever band it sees first
  (§2.3).

The rates arrive through the declared measured channel (`measured_self_agreement=`,
the same channel `CT-STATS-C07` constructs with), so this is rung 0: no store,
no provider, no measured runs — the pairing decision is the module's own and
the boundary is what this file pins. The three cases also pin the threshold's
*source*: `MVVP_SELF_AGREEMENT_PAIRING_THRESHOLD` in the module against
`vocab.SELF_AGREEMENT_PAIRING_THRESHOLD` in the suite's vocabulary — one
constant, two spellings, and a drift between them is a silent redefinition of
"high stability".

Isolation: rung 0 — `run_mvvp` over no population. Interface: the landed
`run_mvvp` surface (#116), required under `#116`.
"""

from __future__ import annotations

import pytest

from tests.support import stats_vocabulary as vocab
from tests.support.impl import STATS_MODULE, require

pytestmark = pytest.mark.contract

#: The judge whose stability each case measures. A single-member panel keeps
#: every reading attributable to one judge — the plan's row is about one
#: judge's rate, not a panel average.
JUDGE = "judge-boundary"


def _pairing(self_agreement: float):
    """The step-5 pairing record for one judge measured at ``self_agreement``,
    through the same rung-0 call `CT-STATS-C07` makes."""
    run_mvvp = require(STATS_MODULE, "run_mvvp", issue="#116")
    report = run_mvvp(
        assignment_type="extended_response",
        measured_self_agreement={JUDGE: self_agreement},
    )
    pairing = report.steps[5].paired_results[JUDGE]
    # Non-vacuity: the record must actually carry the rate this case measured,
    # or every boundary assertion below would pin a fixture, not the module.
    assert pairing.self_agreement == self_agreement, (
        f"the pairing carried self_agreement={pairing.self_agreement!r} for a "
        f"judge measured at {self_agreement!r}; the measured channel is "
        "reported verbatim (TC-JUDGE-C17 limb 3), so a remapped rate would "
        "redefine the boundary instead of sitting on it"
    )
    return pairing


def test_tc_stats_20_self_agreement_below_the_threshold_is_not_pairing_required():
    """0.94 — one point under the threshold: `pairing_required` is **False**.

    A judge at 0.94 has not earned the pairing; reporting its position-bias
    result beside the rate is a module's prerogative, but *requiring* it is
    the finding `FR-STATS-18` reserves for stability the threshold calls
    high."""
    pairing = _pairing(0.94)
    assert pairing.pairing_required is False, (
        "a judge measured at 0.94 self-agreement was reported as requiring "
        "its position-bias pairing; FR-STATS-18 pairs above 0.95, and a "
        "boundary that fires early makes 'high stability' mean something "
        "other than the protocol's own declared threshold"
    )
    assert pairing.self_agreement_measured is True


def test_tc_stats_20_self_agreement_at_the_threshold_is_not_pairing_required():
    """0.95 — exactly at the threshold: **not** pairing-required.

    The case that separates *exceeds* from *at least*: `FR-STATS-18` reads
    *"exceeds 0.95"*, so a judge at exactly 0.95 is on the unpaired side and
    an implementation pairing at ``>=`` fails here — the boundary is the
    value, not the spelling of the comparison in a docstring."""
    pairing = _pairing(0.95)
    assert pairing.pairing_required is False, (
        "a judge measured at exactly 0.95 was reported as pairing-required; "
        f"the threshold {vocab.SELF_AGREEMENT_PAIRING_THRESHOLD} is *exceeded*, "
        "not met — the plan's row puts 0.95 on the unpaired side of the "
        "boundary by construction"
    )


def test_tc_stats_20_self_agreement_above_the_threshold_requires_the_pair():
    """0.96 — one point over: `pairing_required` is **True**, and the record is
    the pair, not the number.

    The two figures travel in one record: the stability rate beside a
    position-bias result (`FR-STATS-15`'s step-2 value for the same judge).
    High stability is never reported as reassurance alone — the pair is the
    finding, because a judge that answers identically every time may simply
    be anchored, and a report showing 0.96 without its bias figure is the
    comfortable half of the story."""
    run_mvvp = require(STATS_MODULE, "run_mvvp", issue="#116")
    report = run_mvvp(
        assignment_type="extended_response",
        measured_self_agreement={JUDGE: 0.96},
    )
    pairing = report.steps[5].paired_results[JUDGE]
    assert pairing.pairing_required is True, (
        "a judge measured at 0.96 self-agreement went unpaired; above "
        f"{vocab.SELF_AGREEMENT_PAIRING_THRESHOLD} the position-bias result is "
        "required to be present (FR-STATS-18) — the pair is the finding, not "
        "the stability number"
    )
    assert pairing.position_bias is not None, (
        "the pairing record required the position-bias result and did not "
        "carry one — the pair is not reported together"
    )
    # The bias result is step 2's own record for the same judge — the pairing
    # points at the figure the swap step measured, not a private copy.
    step2 = report.steps[2].outcome[JUDGE]
    assert pairing.position_bias is step2, (
        "the pairing carried a position-bias result distinct from step 2's "
        "own record for the judge; FR-STATS-15's figure is the one the pair "
        "reports"
    )
    # The measured half of the pair rides the replication step's own record:
    # one rate, two steps, the same number — never a restatement that could
    # drift from what was measured.
    step3 = report.steps[3].outcome[JUDGE]
    assert step3.self_agreement == 0.96
    assert step3.runs_required == 3, (
        "the replication step's runs_required moved; FR-STATS-16 fixes the "
        "floor at three, and TC-STATS-17's live tier measures the rate over "
        "exactly that many runs"
    )


def test_tc_stats_20_a_pairing_judge_still_reports_the_swap_verbatim():
    """The pair carries the measured swap rate **verbatim** — 0.02, unclamped.

    The paired-reporting requirement is worth nothing if the bias figure it
    pairs is laundered on the way in: a clamp, floor or omission would turn
    the finding into the reassurance the clause exists to prevent. A low
    measured swap rate is *reported* (`TC-JUDGE-C17` limb 3: a measured value
    below 1.0 is the finding, not a failure) and a high one is flagged — the
    module's job is the verbatim transit, and this pins it at the boundary's
    paired side."""
    run_mvvp = require(STATS_MODULE, "run_mvvp", issue="#116")
    report = run_mvvp(
        assignment_type="extended_response",
        measured_self_agreement={JUDGE: 0.96},
        measured_position_bias={JUDGE: 0.02},
    )
    pairing = report.steps[5].paired_results[JUDGE]
    assert pairing.pairing_required is True
    assert pairing.position_bias.band_change_rate == 0.02, (
        f"the paired bias figure was {pairing.position_bias.band_change_rate!r}; "
        "the measured 0.02 arrives verbatim — a clamped or floored figure makes "
        "the pair the clause requires report something other than what the "
        "swap measured (FR-STATS-18)"
    )
    assert pairing.position_bias.measured is True
    assert pairing.position_bias.reason == ""
