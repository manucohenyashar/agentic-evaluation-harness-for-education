"""`TC-STATS-12` — the routing-policy verdict when the rates clearly differ.

Test plan §5.16 (`TC-STATS-12`), issue #120 (TS-43). Traces to `FR-STATS-08`.
The plan's row: *"Blind labels over escalated-and-reviewed and auto-accepted
populations, in two scenarios: similar error rates, and clearly different
rates. A policy showing **similar** rates in both is reported as **failing**,
not as merely uninformative."* Exact verdict, P0.

The **similar** half is `CT-STATS-C11`'s (`test_ct_stats_checks_and_scope.py`):
same rate in both arms → `failing`, never `uninformative` — cross-referenced,
not repeated here. What this file adds is the verdict's other branches over
the same report, each an exact-value assertion on the vocabulary `FR-STATS-08`
fixes:

- **clearly different** — the HLD's 8%-versus-1% gap, hand-computed below —
  is `discriminating`: the policy escalates the judgments whose review
  actually finds errors, which is the verdict a working policy earns. A
  report that can only say `failing` would make a working policy and a
  broken one indistinguishable;
- **the tolerance boundary** — a gap of exactly `STATS_ROUTING_POLICY_TOLERANCE`
  is *past* similar (`abs(escalated − auto) < tolerance` is the similar test),
  so it is `discriminating`, not `failing`;
- **the inverted direction** — the auto-accepted arm showing the larger rate —
  is `failing`: a policy routing the wrong way is worse than one routing
  nothing, and the same verdict word carries both findings with the rates
  beside them to tell the two apart;
- **an arm without a computable rate** is `no_data` as a value (`CT-STATS-16`),
  never an exception and never a verdict manufactured from one arm's rate.

Every population is the same blind-only shape `CT-STATS-C11` pins — the arms
read the admissible labels by their routing (`FR-STATS-08`), so an
operational label in either arm would compare the review with itself.

Isolation: rung 0 — in-memory labels through `build_stats`. Interface: the
landed `routing_policy_validity` surface (#117), required under `#117`.
"""

from __future__ import annotations

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import STATS_MODULE, require

pytestmark = pytest.mark.contract


def _arm_labels(arm: str, *, errors: int, clean: int, prefix: str) -> list:
    """One arm's population: ``errors`` labels disagreeing with the blind
    teacher, ``clean`` agreeing — so the arm's error rate is
    ``errors / (errors + clean)`` by construction, every cell countable."""
    labels = [
        broken.Label(
            label_id=f"{prefix}-err-{i}", routing=arm, band=1, teacher_band=4
        )
        for i in range(errors)
    ]
    labels += [
        broken.Label(
            label_id=f"{prefix}-ok-{i}", routing=arm, band=3, teacher_band=3
        )
        for i in range(clean)
    ]
    return labels


def _report(labels) -> object:
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    return build_stats(labels=labels).routing_policy_validity(cohort_id="coh-12")


# --- the clearly-different scenario -------------------------------------------------------------


def test_tc_stats_12_clearly_different_rates_are_discriminating():
    """The HLD's 8%-versus-1% gap, hand-computed: `discriminating`.

    Escalated-and-reviewed: 2 errors in 25 (0.08). Auto-accepted: 1 error in
    100 (0.01). The gap is 0.07, past the declared 0.05 tolerance — the
    policy escalates the judgments whose review finds errors, which is the
    policy working, and the report says so with the one word the vocabulary
    reserves for it. (``n`` is the arm's whole admissible population — 25 and
    100, not the paired 25 and 100 they happen to be here, where every label
    carries both sides; the count is the population the claim is about.)"""
    escalated = _arm_labels(
        vocab.ROUTING_POLICY_ARMS[0], errors=2, clean=23, prefix="esc"
    )
    auto = _arm_labels(vocab.ROUTING_POLICY_ARMS[1], errors=1, clean=99, prefix="auto")
    report = require(STATS_MODULE, "routing_policy_validity", issue="#117")(
        require(STATS_MODULE, "build_stats", issue="#115")(
            labels=escalated + auto
        ),
        cohort_id="coh-12",
    )

    assert report.label_population[vocab.ROUTING_POLICY_ARMS[0]].n == 25
    assert report.label_population[vocab.ROUTING_POLICY_ARMS[1]].n == 100
    assert report.verdict == "discriminating", (
        f"the report returned {report.verdict!r} for a 0.08-versus-0.01 gap. "
        "FR-STATS-08: the escalated arm above the auto-accepted arm by at "
        "least the tolerance is discriminating — the policy working is the "
        "verdict, and a report that cannot distinguish it from a failing one "
        "is uninformative in the sense the clause refuses"
    )
    # The rates beside the verdict are the hand-computed ones, exact.
    arms = report.label_population
    assert arms[vocab.ROUTING_POLICY_ARMS[0]].error_rate == pytest.approx(0.08), (
        "2 errors in 25 is 0.08 — the HLD's escalated-arm figure"
    )
    assert arms[vocab.ROUTING_POLICY_ARMS[1]].error_rate == pytest.approx(0.01), (
        "1 error in 100 is 0.01 — the HLD's auto-accepted figure; a policy "
        "whose two rates cannot be recomputed from the report is a verdict "
        "nobody can check"
    )


def test_tc_stats_12_a_gap_exactly_at_the_tolerance_is_discriminating():
    """A gap of exactly the tolerance is *past* similar: `discriminating`.

    The similar test is strict (`abs(a − b) < tolerance`), so a gap of
    exactly `STATS_ROUTING_POLICY_TOLERANCE` = 0.05 is not similar — and an
    implementation using ``<=`` fails here, collapsing the boundary into the
    failing verdict. Escalated 2/20 = 0.10, auto-accepted 1/20 = 0.05: the
    gap is 0.05 exactly, both arms fully paired and countable."""
    escalated = _arm_labels(
        vocab.ROUTING_POLICY_ARMS[0], errors=2, clean=18, prefix="esc-tol"
    )
    auto = _arm_labels(
        vocab.ROUTING_POLICY_ARMS[1], errors=1, clean=19, prefix="auto-tol"
    )
    report = require(STATS_MODULE, "routing_policy_validity", issue="#117")(
        require(STATS_MODULE, "build_stats", issue="#115")(
            labels=escalated + auto
        ),
        cohort_id="coh-12",
    )

    arms = report.label_population
    assert arms[vocab.ROUTING_POLICY_ARMS[0]].error_rate == pytest.approx(0.10)
    assert arms[vocab.ROUTING_POLICY_ARMS[1]].error_rate == pytest.approx(0.05)
    assert report.verdict == "discriminating", (
        f"the report returned {report.verdict!r} for a gap of exactly the "
        f"tolerance ({report.tolerance}); *similar* is the strict-below "
        "reading, so the boundary gap is discriminating, and an implementation "
        "that pairs at `<=` reports a working policy as failing"
    )
    assert report.tolerance == pytest.approx(0.05), (
        "the tolerance the verdict was read against moved from the declared "
        "STATS_ROUTING_POLICY_TOLERANCE — the boundary above is pinned "
        "against the declared constant, whatever a caller might recalibrate"
    )


# --- the two verdicts the clearly-different scenario is not -------------------------------------


def test_tc_stats_12_an_inverted_policy_is_failing_not_discriminating():
    """The inverted direction — the auto-accepted arm showing the larger rate —
    is `failing`.

    A policy whose auto-accepted judgments err *more* than its escalated ones
    is routing the wrong way: the escalated arm's errors are the review's
    findings, and an arm finding fewer of them than the no-review arm is the
    policy doing harm, not nothing. `discriminating` is reserved for the
    escalated arm above the auto one — the direction the clause's gap names —
    and an implementation that reads the comparison symmetrically (any clear
    gap is discriminating) fails here."""
    escalated = _arm_labels(
        vocab.ROUTING_POLICY_ARMS[0], errors=1, clean=99, prefix="esc-inv"
    )
    auto = _arm_labels(
        vocab.ROUTING_POLICY_ARMS[1], errors=2, clean=23, prefix="auto-inv"
    )
    report = require(STATS_MODULE, "routing_policy_validity", issue="#117")(
        require(STATS_MODULE, "build_stats", issue="#115")(
            labels=escalated + auto
        ),
        cohort_id="coh-12",
    )

    assert report.verdict == vocab.ROUTING_POLICY_FAILING_VERDICT, (
        f"the report returned {report.verdict!r} for a policy whose "
        "auto-accepted arm errs more than its reviewed one; the inverted "
        "direction is failing — the policy is routing the wrong way"
    )


def test_tc_stats_12_an_arm_without_a_computable_rate_is_no_data():
    """One arm carries no paired labels: `no_data`, as a value.

    The verdict is not computed from the one computable rate — a report that
    calls a half-measured policy anything at all is filling the missing arm
    with optimism. The absent arm's own record still discloses what it held
    (`n` counts its admissible population, the rate is `None`), and the
    report's overall `n` still counts every admissible label — the population
    was there; the comparison is what could not be made (`CT-STATS-16`)."""
    escalated = _arm_labels(
        vocab.ROUTING_POLICY_ARMS[0], errors=2, clean=23, prefix="esc-nd"
    )
    auto = [
        # The auto-accepted arm's labels carry band only: no teacher side, so
        # no pair — the arm's rate is genuinely not computable.
        broken.Label(
            label_id=f"auto-unpaired-{i}",
            routing=vocab.ROUTING_POLICY_ARMS[1],
            band=3,
            teacher_band=None,
        )
        for i in range(10)
    ]
    report = require(STATS_MODULE, "routing_policy_validity", issue="#117")(
        require(STATS_MODULE, "build_stats", issue="#115")(
            labels=escalated + auto
        ),
        cohort_id="coh-12",
    )

    arms = report.label_population
    assert arms[vocab.ROUTING_POLICY_ARMS[1]].n == 10, (
        "the unpaired arm's population was dropped; n counts the admissible "
        "population the claim is about, whether or not a rate was computable"
    )
    assert arms[vocab.ROUTING_POLICY_ARMS[1]].error_rate is None
    assert report.verdict == "no_data", (
        f"the report returned {report.verdict!r} with one arm's rate missing; "
        "a half-measured comparison is no_data as a value, never a verdict "
        "computed from the other arm's rate alone (CT-STATS-16)"
    )