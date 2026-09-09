"""`TS-23`'s escalation-policy unit cases — `TC-ORCH-13`, `TC-ORCH-14`, `TC-ORCH-20`
**landed at #60** (unmarked there); `TC-ORCH-27` (`#62`, the estimator) and `TC-ORCH-32`
(`#95`, `should_escalate`) remain written ahead of their stories.

`NFR-ORCH-04` requires the escalation policy to be a pure function of observable signals
and configuration, evaluable without a model call — which is what makes all five cases
rung 0. Each case enters at the symbol its story owes; nothing here touches a store.

**Interface of #60 / #62 / #95**, listed so it is reconciled deliberately rather than
discovered (the `test_leasing.py` and `test_pause_lifecycle.py` precedents — their
assumed names resolved, or failed visibly, at landing):

| Name | Status |
|---|---|
| `aeh.orch:criterion_breaker_tripped(escalated, processed, *, rate=None, min_n=None) -> bool` | **landed at #60** (the design pins the semantics and the two constants but no function name — this file's invented name is what shipped): tripped iff `processed >= min_n` **and** `escalated / processed > rate` — "more than half", strict, of the first `ORCH_CRITERION_BREAKER_MIN_N` submissions (FR-ORCH-13, CT-ORCH-16). Defaults are the module constants. |
| `aeh.orch:admit_escalations(candidates, *, escalated, processed, budget=None) -> AdmissionPlan` | **landed at #60** with the declared shape: candidates are `(key, expected_value)` pairs; the returned plan exposes `.admitted` and `.provisional` as tuples of keys (a NamedTuple). |
| `aeh.orch:validate_escalation_plan(judge_count) -> int` | **landed at #60**: returns the normalized escalated panel depth; raises `EvenEscalationPlanError` on any even count (FR-ORCH-10, CT-ORCH-08) — the invented name is the "exact exception" oracle's pin and is what shipped. |
| `aeh.orch:estimated_completion_seconds(*, completed, remaining, elapsed_seconds, escalation_rate_so_far) -> float` | **invented**: the pure core behind `ProgressReport.estimated_completion` (§3.7); reconciles at #62's landing. |
| above-budget admission = defer **all** pending, in EV-desc order | **the landed reading**: a hard rate cap admits nothing while the rate exceeds it; FR-ORCH-14's "continue admitting in expected-value order" is honored as the EV order in which deferral is recorded and later admission resumes as `processed` grows. The 31% limb passes against the shipped `admit_escalations`. |
| at-budget is **not** above-budget | "exceeds the configured budget" is read strict, matching the breaker's "more than half": 30% behaves like 29%, and 31% is the first rationed state. Landed. |
| `should_escalate(score, criterion, history, baseline)` | design §3.8 Protocol member; the stand-ins carry the design's field names and reconcile at #95's landing. |

Statistical parameters are stated (the oracle is "statistical with stated n and tolerance"):
the convergence limb draws n=10,000 at p=0.07 (σ ≈ 0.00255) with a ±0.008 tolerance (≈3.1σ);
the strata limbs draw n=5,000 each (σ ≈ 0.0036) with ±0.011 tolerances. The seed is the
suite's `seeded_random` fixture, so every figure is reproducible by hand.

Isolation: rung 0 — pure functions and doubles only; the socket guard and the refusing
store spy of `TC-ORCH-32` are the case's own oracle, not suite plumbing.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from tests.support.impl import AGG_MODULE, ORCH_MODULE, require


# --- TC-ORCH-13 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("escalated", "processed", "expected"),
    [
        (9, 20, False),   # below half at the minimum
        (10, 20, False),  # exactly half — "more than half" is strict
        (11, 20, True),   # above half at the minimum — the trip point
        (10, 19, False),  # above half but BELOW the 20-submission minimum
        (11, 19, False),  # ditto, higher rate — the minimum gates before the rate does
        (12, 24, False),  # exactly half again, past the minimum
        (13, 24, True),   # above half past the minimum
    ],
)
def test_tc_orch_13_breaker_trips_only_above_half_at_or_after_the_twenty_minimum(
    escalated, processed, expected
):
    """`TC-ORCH-13` (`FR-ORCH-13`, unit / rung 0, boundary, P0) — a criterion escalating
    for 9, 10 and 11 of the first 20 submissions: the breaker trips **only** above half,
    **at or after** the 20-submission minimum (`ORCH_CRITERION_BREAKER_MIN_N`), so neither
    a hot streak under the minimum nor exactly-half contention trips it."""
    tripped, breaker_rate, breaker_min_n = require(
        ORCH_MODULE,
        "criterion_breaker_tripped",
        "ORCH_CRITERION_BREAKER_RATE",
        "ORCH_CRITERION_BREAKER_MIN_N",
        issue="#60",
    )

    # The design's Configuration block pins both constants (§3.7): 0.50 and 20.
    assert breaker_rate == 0.50, (
        f"ORCH_CRITERION_BREAKER_RATE is {breaker_rate!r} — the design fixes 0.50 "
        "(a criterion escalating for more than half of its window trips)"
    )
    assert breaker_min_n == 20, (
        f"ORCH_CRITERION_BREAKER_MIN_N is {breaker_min_n!r} — the design fixes 20 "
        "(the 20–30 window's declared knob default)"
    )

    # Defaults must BE the constants: a function whose defaults drifted from them
    # would trip at a rate the design never declared.
    assert tripped(escalated, processed) is expected, (
        f"criterion_breaker_tripped({escalated}, {processed}) is not {expected!r} — "
        "the breaker must trip only above half (strict) at or after the 20-submission "
        "minimum; a trip below the minimum hides a working criterion behind "
        "ungradeable_by_panel, and a missed trip leaves the panel escalating a "
        "criterion the budget cannot carry (RISK-24)"
    )
    # ...and the explicit form must agree with the default form.
    assert tripped(escalated, processed, rate=breaker_rate, min_n=breaker_min_n) is expected


# --- TC-ORCH-14 ---------------------------------------------------------------------------


def test_tc_orch_14_budget_rations_above_it_and_marks_the_remainder_provisional():
    """`TC-ORCH-14` (`FR-ORCH-14`, unit / rung 0, boundary, P0) — run-wide escalation rate
    at 29%, 30% and 31% against `ORCH_ESCALATION_BUDGET` (0.30): at and below budget every
    escalation is admitted and none is provisional; above budget nothing further is
    admitted and the remainder is **marked provisional in expected-value order** — visible
    degradation, never a silent reduction of scrutiny and never a dropped candidate."""
    admit_escalations, budget = require(
        ORCH_MODULE, "admit_escalations", "ORCH_ESCALATION_BUDGET", issue="#60"
    )
    assert budget == 0.30, (
        f"ORCH_ESCALATION_BUDGET is {budget!r} — the design fixes 0.30 (§3.7 Configuration)"
    )

    # Expected values unsorted on purpose: any order-dependence in the policy's output
    # must come from the expected values, not from the caller's input order.
    candidates = [("c-low", 0.10), ("c-mid", 0.55), ("c-high", 0.90)]
    ev = dict(candidates)

    def plan(escalated, processed):
        return admit_escalations(candidates, escalated=escalated, processed=processed)

    # 29% and 30% — below and exactly at the budget: everything admitted, nothing
    # provisional. Rationing must not start early: that is the "silently reducing
    # scrutiny" failure the requirement names (R26).
    for escalated in (29, 30):
        p = plan(escalated, 100)
        assert set(p.admitted) == set(ev) and not p.provisional, (
            f"at {escalated}% the plan admitted {p.admitted!r} and deferred "
            f"{p.provisional!r} — the budget is 0.30 and 'exceeds' is strict, so "
            "escalations are admitted in full at and below it"
        )

    # 31% — above budget: nothing more is admitted; the remainder is marked provisional
    # (not dropped, not downgraded quietly), in expected-value order so that admission
    # resumes with the highest-value criteria when the rate allows.
    p = plan(31, 100)
    assert not p.admitted, (
        f"above budget the plan still admitted {p.admitted!r} — the window is overrun: "
        "every further escalation past a rate already above 0.30 deepens the overrun "
        "FR-ORCH-14 forbids"
    )
    assert tuple(p.provisional) == ("c-high", "c-mid", "c-low"), (
        f"the deferred remainder is {p.provisional!r} — it must be exactly the pending "
        "set, marked provisional (visible, recoverable), in expected-value order"
    )

    # The invariant that holds for ANY admitted/provisional split — this is the part an
    # allowance-based partial admission must also satisfy: full accounting, no overlap,
    # and no expected-value inversion (a lower-value escalation admitted while a
    # higher-value one is deferred would be the ordering failure the oracle names).
    for escalated, processed in ((29, 100), (30, 100), (31, 100), (61, 200), (5, 10)):
        q = plan(escalated, processed)
        a, d = set(q.admitted), set(q.provisional)
        assert not (a & d) and a | d == set(ev), (
            f"at {escalated}/{processed} the plan lost or duplicated candidates: "
            f"admitted={q.admitted!r} provisional={q.provisional!r} — scrutiny is "
            "silently reduced exactly when a candidate is dropped instead of marked"
        )
        if a and d:
            assert min(ev[k] for k in a) >= max(ev[k] for k in d), (
                f"expected-value inversion at {escalated}/{processed}: admitted "
                f"{q.admitted!r} deferred {q.provisional!r} — admission must follow "
                "expected-value order (FR-ORCH-14)"
            )


# --- TC-ORCH-20 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("judge_count", "expected"),
    [(1, 3), (3, 3), (5, 5)],
)
def test_tc_orch_20_odd_escalation_plans_are_accepted_with_one_escalating_to_three(
    judge_count, expected
):
    """`TC-ORCH-20` (`FR-ORCH-10`, unit / rung 0, negative, P0) — the odd half: plans
    producing 1, 3 and 5 judges are legal panels, and a plan for a one-judge criterion
    escalates to **three** — never to two."""
    validate, error = require(
        ORCH_MODULE, "validate_escalation_plan", "EvenEscalationPlanError", issue="#60"
    )
    assert validate(judge_count) == expected, (
        f"validate_escalation_plan({judge_count}) returned {validate(judge_count)!r}, "
        f"expected {expected} — odd panels are legal, and a one-judge escalation "
        "targets three (FR-ORCH-10)"
    )


@pytest.mark.parametrize("judge_count", [2, 4])
def test_tc_orch_20_even_escalation_plans_are_rejected(judge_count):
    """`TC-ORCH-20` (`FR-ORCH-10`, unit / rung 0, negative, P0) — the even half: a plan
    yielding an even `judge_count` is **rejected** — an even panel cannot aggregate
    (R48: a tie broken by rule is a coin flip presented as a judgement)."""
    validate, error = require(
        ORCH_MODULE, "validate_escalation_plan", "EvenEscalationPlanError", issue="#60"
    )
    with pytest.raises(error):
        validate(judge_count)
    # The escalation of one judge is three — the "never to two" half asserted against
    # the value itself, not only against the rejection of the even plan.
    if judge_count == 2:
        assert validate(1) != 2, (
            "a one-judge escalation produced a two-judge panel — FR-ORCH-10: one to "
            "three, never to two"
        )


# --- TC-ORCH-27 ---------------------------------------------------------------------------


def test_tc_orch_27_estimated_completion_adjusts_for_the_observed_escalation_rate():
    """`TC-ORCH-27` (`FR-ORCH-24`, unit / rung 0, P1) — estimated completion from observed
    throughput against remaining units **adjusted for the escalation rate observed so
    far**. Hand-computed reference: 100 units completed in 100s (throughput 1/s), 200
    remaining; each escalation turns one unit into three (+2 units), so the adjusted
    remainder is `remaining * (1 + 2*rate)` — 0% -> 200s, 15% -> 260s, 30% -> 320s. A
    naive remaining-units estimate is measurably different at 15% and 30% and is thereby
    rejected."""
    estimated = require(ORCH_MODULE, "estimated_completion_seconds", issue="#62")

    completed, remaining, elapsed = 100, 200, 100.0

    # 0% observed: nothing has escalated, so the adjusted estimate IS the naive one.
    assert estimated(
        completed=completed,
        remaining=remaining,
        elapsed_seconds=elapsed,
        escalation_rate_so_far=0.0,
    ) == pytest.approx(200.0), (
        "at a 0% observed escalation rate the estimate is not the naive 200s — the "
        "adjustment must be a no-op when nothing has escalated"
    )

    # 15% and 30%: the adjusted figure is the naive one times (1 + 2*rate) — and the
    # difference from naive is exactly the escalation growth, hand-computed.
    for rate, expected in ((0.15, 260.0), (0.30, 320.0)):
        adjusted = estimated(
            completed=completed,
            remaining=remaining,
            elapsed_seconds=elapsed,
            escalation_rate_so_far=rate,
        )
        naive = remaining / (completed / elapsed)
        assert adjusted == pytest.approx(expected), (
            f"at a {rate:.0%} observed escalation rate the estimate is {adjusted!r}, "
            f"expected {expected}s (remaining {remaining} adjusted by (1 + 2*rate) at "
            "1 unit/s) — escalations add units the initial count never held "
            "(FR-ORCH-24), and an estimate that ignores them commits the run to a "
            "window it will overrun"
        )
        assert adjusted - naive == pytest.approx(remaining * 2 * rate), (
            f"the adjustment at {rate:.0%} is {adjusted - naive!r}s over naive, "
            f"expected {remaining * 2 * rate!r}s — the naive remaining-units estimate "
            "is measurably different, which is what rejects it"
        )


# --- TC-ORCH-32 ---------------------------------------------------------------------------


class _RefusingStoreSpy:
    """A store spy that fails on **any** access — `TC-ORCH-32`'s purity oracle.

    Hand this to `should_escalate` wherever its signature accepts a store-shaped
    parameter; a call that reaches for a store through the front door fails here, and a
    call that reaches the network fails the socket guard mid-connect.
    """

    def __getattr__(self, name: str):
        raise AssertionError(
            f"the escalation policy touched the store during evaluation ({name!r}) — "
            "NFR-ORCH-04: it is a pure function of observable signals and configuration"
        )


@pytest.mark.writtenahead
def test_tc_orch_32_escalation_policy_is_pure_no_sockets_no_store(network_guard):
    """`TC-ORCH-32` (`NFR-ORCH-04`, artifact assertion / rung 0, P0) — the escalation
    policy function is evaluable with **no model call and no store access**: called under
    the TS-00 socket guard with a store spy that fails on any access."""
    should_escalate = require(AGG_MODULE, "should_escalate", issue="#95")

    # Stand-ins carrying the design's field names (§3.8): the score, the criterion, the
    # criterion's history, and the package's expected distribution. They reconcile at
    # #95's landing; the purity oracle below does not depend on their contents.
    score = SimpleNamespace(band="B", confidence=0.62, judge_count=3)
    criterion = SimpleNamespace(
        criterion_id="C1", scoring_model="atomic", bands=("A", "B", "C", "D")
    )
    history = SimpleNamespace(override_rate=0.1, escalations=0)
    baseline = SimpleNamespace(mean=2.0, std=0.5)

    # Hand the spy to every store-shaped parameter the signature declares — name-agnostic
    # over the usual seams; a policy with no store parameter (the design's shape) simply
    # takes none, and the guard carries the assertion.
    spy_names = {"store", "store_handle", "session", "conn", "connection"}
    spy_kwargs = {
        name: _RefusingStoreSpy()
        for name in inspect.signature(should_escalate).parameters
        if name.lower() in spy_names
    }

    decision = should_escalate(
        score=score, criterion=criterion, history=history, baseline=baseline, **spy_kwargs
    )

    # Any shape of decision is fine — the oracle is the absence of I/O, not the value.
    # Determinism is the one behavioural corollary of purity that is checkable here:
    # the same inputs, evaluated again, must return an equal decision. Declared landing
    # assumption: the decision type compares by value (the enum / dataclass /
    # NamedTuple / bool shape §3.8's Protocol implies); a decision type with identity
    # equality cannot express this corollary and reconciles at #95's landing.
    again = should_escalate(
        score=score, criterion=criterion, history=history, baseline=baseline, **spy_kwargs
    )
    assert again == decision, (
        f"the escalation policy returned {decision!r} then {again!r} for identical "
        "inputs — a policy that is not deterministic is not a pure function of its "
        "signals (NFR-ORCH-04)"
    )
    network_guard.assert_no_network()
