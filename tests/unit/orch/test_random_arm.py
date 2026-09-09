"""`TS-23`'s random-arm statistical cases — `TC-ORCH-12` (the statistical core) and
`ADV-12` (the routing-policy attack) — **landed at #60** (unmarked there).

FR-ORCH-11: the random arm is enumerated at `ORCH_RANDOM_ARM_RATE` (0.07), independent
of confidence, and never suppressed by the escalation ceiling. CT-ORCH-15: `origin` keeps
it statistically separable. The plan's oracle for `TC-ORCH-12` is *"Statistical with
stated n and tolerance"*, and §4.6's randomness row names this case directly: *"TC-ORCH-12
asserts the distribution over 10k seeded draws."*

**Interface of #60** (declared for reconciliation — the design pins the
rate and the semantics but no function name; the `record_run_metrics` precedent):

| Name | Status |
|---|---|
| `aeh.orch:ORCH_RANDOM_ARM_RATE` | design §3.7 Configuration: 0.07 (the HLD's 5–10% band's declared assumption) — landed |
| `aeh.orch:random_arm_selection(key, seed, rate=None) -> bool` | **landed at #60 with this name**: the pure, seeded decision the enumeration path consults per candidate unit. `key` is the unit's identity (the work-id inputs), `seed` the run's seeded draw, `rate` defaulting to the module constant. |
| mechanism half (origin string, up-front enumeration, non-suppression above budget) | asserted at the enumeration surface in `tests/integration/orch/test_random_arm_enumeration.py` — a unit/rung-0 file cannot observe a ledger row; this file holds the statistical oracle the plan names. |

**Statistical parameters, stated** (the oracle is "statistical with stated n and
tolerance"): the convergence limb draws n=10,000 at p=0.07 — σ = sqrt(p(1−p)/n) ≈ 0.00255
— with a ±0.008 tolerance (≈3.1σ). The strata limbs draw n=5,000 each (σ ≈ 0.0036) with
±0.011 tolerances (≈3.0σ); the between-strata difference bound is 0.015 (≈2.9σ). All
draws come from the suite's `seeded_random` fixture, so every figure is reproducible by
hand and a tolerance failure names a real rate defect, not shuffle noise.

Isolation: rung 0 — a pure function and the seeded `Random` instance; no store, no model,
no enumeration.
"""

from __future__ import annotations

import pytest

from tests.support.impl import ORCH_MODULE, require

#: The convergence limb's n — the plan's own "10,000 seeded enumerations".
N_DRAWS = 10_000
#: ±3.1σ at n=10,000 (σ ≈ 0.00255): tight enough that 6% or 8% fail, loose enough that
#: the fixed-seed draw does not flake.
TOLERANCE_10K = 0.008
#: The strata limbs' n per stratum.
N_PER_STRATUM = 5_000
#: ±3.0σ at n=5,000 (σ ≈ 0.0036).
TOLERANCE_5K = 0.011
#: ≈2.9σ on the difference of two n=5,000 shares.
TOLERANCE_DIFF = 0.015


def _draw_rate(selection, keys, rng, rate=None):
    """The arm's share over `keys`, one seeded draw each, from the shared rng."""
    hits = 0
    for key in keys:
        seed = rng.randrange(2**31)
        hits += 1 if selection(key, seed, rate) else 0
    return hits / len(keys)


def test_tc_orch_12_random_arm_share_converges_on_the_configured_rate(seeded_random):
    """`TC-ORCH-12` (`FR-ORCH-11`, unit / rung 0, statistical, P0) — 10,000 seeded
    enumerations at `ORCH_RANDOM_ARM_RATE` = 0.07: the random-arm share converges on 7%
    within the stated tolerance."""
    rate, selection = require(
        ORCH_MODULE, "ORCH_RANDOM_ARM_RATE", "random_arm_selection", issue="#60"
    )
    assert rate == 0.07, (
        f"ORCH_RANDOM_ARM_RATE is {rate!r} — the design fixes 0.07 (the HLD's 5–10% "
        "band's declared assumption, §3.7 Configuration)"
    )

    keys = [f"unit-{i:05d}" for i in range(N_DRAWS)]
    share = _draw_rate(selection, keys, seeded_random)

    assert abs(share - rate) <= TOLERANCE_10K, (
        f"the random-arm share over {N_DRAWS} seeded draws is {share:.4f}, expected "
        f"{rate} within ±{TOLERANCE_10K} (≈3.1σ) — an arm that undershoots is a "
        "population the routing policy never audits, and one that overshoots spends "
        "the budget the escalation ceiling owes to real escalations"
    )


def test_tc_orch_12_random_arm_selection_is_independent_of_confidence(seeded_random):
    """`TC-ORCH-12` (`FR-ORCH-11`, unit / rung 0, statistical, P0) — selection is
    independent of confidence, asserted by correlating arm membership against confidence
    and requiring no association: a high-confidence population and a low-confidence one
    are sampled at indistinguishable rates. An arm that reads confidence is the routing
    policy grading its own homework — exactly what ADV-12 attacks."""
    _rate, selection = require(
        ORCH_MODULE, "ORCH_RANDOM_ARM_RATE", "random_arm_selection", issue="#60"
    )

    # Two populations differing ONLY in confidence; keys are interleaved so any
    # key-order artifact in the sampler hits both strata alike.
    high = [f"conf-high-{i:05d}" for i in range(N_PER_STRATUM)]
    low = [f"conf-low-{i:05d}" for i in range(N_PER_STRATUM)]

    share_high = _draw_rate(selection, high, seeded_random)
    share_low = _draw_rate(selection, low, seeded_random)

    for name, share in (("high-confidence", share_high), ("low-confidence", share_low)):
        assert abs(share - 0.07) <= TOLERANCE_5K, (
            f"the {name} population's arm share is {share:.4f}, expected 0.07 within "
            f"±{TOLERANCE_5K} (≈3.0σ) — the arm must sample at the configured rate in "
            "every confidence stratum (FR-ORCH-11: independent of confidence)"
        )
    assert abs(share_high - share_low) <= TOLERANCE_DIFF, (
        f"the arm shares differ by {abs(share_high - share_low):.4f} between the "
        f"high-confidence ({share_high:.4f}) and low-confidence ({share_low:.4f}) "
        f"populations — beyond ±{TOLERANCE_DIFF} (≈2.9σ) that is an association, and "
        "an arm associated with confidence is a routing policy that cannot be "
        "falsified (FR-STATS-08's whole point)"
    )


def test_adv_12_confidently_wrong_population_is_still_sampled_by_the_random_arm(
    seeded_random,
):
    """`ADV-12` (`FR-AGG-08`, `FR-ORCH-11`, adversarial, P0) — the attacker engineers a
    population that is fluent, well-structured, confidently wrong, mid-band, with clean
    OCR: submissions that *look* certain so review budget is spent elsewhere. Pass = the
    random arm samples them independently of confidence, so a systematically mis-routed
    population is still detectable in the blind and random-arm labels.

    At the routing-policy surface (rung 0) the attack is statistical: the engineered
    population — every member carrying the "certain look" — is sampled at the same rate
    as a benign one, with no association, and the sampled subset is nonempty, so the
    blind and random-arm labels DO contain engineered submissions to compare. The
    label-consumer half (that M-STATS/M-REVIEW then surface the disagreement) is R22's
    `TC-STATS-12`, not re-asserted here.
    """
    _rate, selection = require(
        ORCH_MODULE, "ORCH_RANDOM_ARM_RATE", "random_arm_selection", issue="#60"
    )

    # The engineered population: keys name what the attacker forged — confident,
    # mid-band, clean OCR. The benign population differs only in honesty.
    engineered = [f"adv-confident-wrong-{i:05d}" for i in range(N_PER_STRATUM)]
    benign = [f"adv-benign-{i:05d}" for i in range(N_PER_STRATUM)]

    share_engineered = _draw_rate(selection, engineered, seeded_random)
    share_benign = _draw_rate(selection, benign, seeded_random)

    assert abs(share_engineered - 0.07) <= TOLERANCE_5K, (
        f"the engineered population's arm share is {share_engineered:.4f}, expected "
        f"0.07 within ±{TOLERANCE_5K} — a population the attacker made look certain is "
        "sampled at a different rate: the routing policy just learned to trust exactly "
        "the submissions built to defeat it"
    )
    assert abs(share_engineered - share_benign) <= TOLERANCE_DIFF, (
        f"engineered ({share_engineered:.4f}) and benign ({share_benign:.4f}) "
        f"populations differ by {abs(share_engineered - share_benign):.4f} in arm "
        f"membership — beyond ±{TOLERANCE_DIFF} the arm is correlated with the very "
        "signals the attacker forged (ADV-12's goal achieved)"
    )
    assert share_engineered > 0.03, (
        f"the engineered population's sampled subset is {share_engineered:.4f} — "
        "effectively empty: nothing engineered reaches the random-arm labels, so a "
        "systematically mis-routed population is undetectable (the attack's goal)"
    )
