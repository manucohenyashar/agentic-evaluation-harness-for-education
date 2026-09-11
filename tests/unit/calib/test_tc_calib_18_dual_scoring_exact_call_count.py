"""`TC-CALIB-18` — dual scoring costs one additional full-class pass; back-translation a handful.

Test plan §5.17, `TC-CALIB-18` (NFR-CALIB-03, Performance / rung 3) — the oracle is the **exact
call count**, measured, not reported.

The contract suite carries the disclosure ordering (`TC-CALIB-C12`: the unregistered cohort's
plan, zero calls before authorization, `calls == estimated_calls == class_size × criteria_count`
after). What no green test carried before this file:

* the **registered-roster** plan row — the plan reads the roster's true shape instead of the
  declared example class, and the notes say so (`CT-CALIB-12`'s floor assumption is not what a
  registered cohort is budgeted on);
* plan time costs **zero** provider calls even when the roster is registered — a disclosure that
  probes the provider has already begun spending the invoice it is disclosing;
* the refusal teeth of "budgeted": an **unauthorized** plan does not run, and an authorized plan
  does not run **twice** — a budgeted cost is incurred once, and a second pass doubles the
  invoice the operator approved;
* the executed timestamp is recorded **after** the authorization's, so disclose → authorize →
  run is observed as an order, not asserted as three non-None fields;
* **back-translation costs a handful of calls** — exactly the bound attempts (three, on both
  fixtures), not one and not a class-size number of calls; the handful is the whole of its cost
  and the `attempts` record is where it is counted.

The provider is the injected counting provider (seam 2); nothing here reaches the network.
"""

from __future__ import annotations

import pytest

from tests.support.impl import CALIB_MODULE, require


# --- dual scoring: one additional full-class pass, measured ---------------------------------------


def test_tc_calib_18_a_registered_roster_plans_its_true_shape_and_pays_exactly_that():
    """The plan reads the registered roster's shape; the run makes exactly the disclosed calls.

    `plan_dual_scoring` against a **registered** cohort plans class_size × criteria_count from
    the roster — not the declared example class — and the notes say which. The measured call
    count after the run is exactly the disclosed figure: one call per (submission, criterion)
    pair across the full class, the additional pass `NFR-CALIB-03` budgets.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "plan_dual_scoring", "authorize", "run_dual_scoring", issue="#140")
    provider = calib.counting_provider_for_test()

    cohort = calib.cohort_with_band_shift(fraction=0.05, class_size=25)
    plan = calib.plan_dual_scoring(
        cohort_id=cohort, r0="pkg-v1", r1="pkg-v2", provider=provider
    )

    assert plan.class_size == 25 and plan.criteria_count == 1, (
        f"the plan read {plan.class_size} submissions on {plan.criteria_count} criteria; the "
        "registered roster carries 25 submissions on one criterion, and a registered cohort is "
        "budgeted at its true shape, not the declared example class"
    )
    assert plan.estimated_calls == 25 * 1, (
        f"estimated_calls is {plan.estimated_calls}; one additional full-class pass over 25 "
        "submissions on 1 criterion is exactly 25 calls (NFR-CALIB-03)"
    )
    assert any("registered roster" in note for note in plan.notes), (
        f"the plan's notes are {plan.notes!r}; a registered cohort must be disclosed as "
        "planned against its roster — the example-class assumption is what an unregistered "
        "cohort gets, and the note is what tells them apart"
    )
    assert provider.calls == 0, (
        f"{provider.calls} provider calls were made while planning a registered cohort; the "
        "cost is estimated from the roster's shape, and nothing is spent before authorization"
    )

    calib.authorize(plan)
    calib.run_dual_scoring(plan)
    assert provider.calls == 25, (
        f"the run made {provider.calls} calls after authorizing 25; the disclosed figure is "
        "the cost paid, measured call by call (the plan's own estimate is not the oracle)"
    )
    assert len(plan.scores) == 25 and all(len(row) == 1 for row in plan.scores), (
        "the scores are not one row per submission with one band per criterion; what was paid "
        "for sits on plan.scores next to what it cost (seam 4)"
    )


def test_tc_calib_18_the_pass_runs_once_and_only_after_authorization():
    """Unauthorized refused; authorized runs; re-run refused; the order is disclose → authorize
    → execute.

    Each refusal is the budget's teeth: a cost nobody approved was never budgeted, and a second
    pass doubles the invoice the operator approved. The ordering is asserted on the timestamps
    the plan carries — strictly increasing, not merely present — because "present" is satisfied
    by a plan that stamps all three at once.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "plan_dual_scoring", "authorize", "run_dual_scoring", issue="#140")
    provider = calib.counting_provider_for_test()

    cohort = calib.cohort_with_band_shift(fraction=0.05, class_size=4)
    plan = calib.plan_dual_scoring(
        cohort_id=cohort, r0="pkg-v1", r1="pkg-v2", provider=provider
    )

    with pytest.raises(calib.CalibrationError):
        calib.run_dual_scoring(plan)  # unauthorized: nothing runs

    calib.authorize(plan)
    calib.run_dual_scoring(plan)

    with pytest.raises(calib.CalibrationError) as exc:
        calib.run_dual_scoring(plan)
    assert "already run" in str(exc.value), (
        f"the re-run refusal reads {exc.value!s}; a budgeted cost is incurred once"
    )

    assert plan.disclosed_at < plan.authorized_at < plan.executed_at, (
        f"the timestamps are disclosed={plan.disclosed_at}, authorized={plan.authorized_at}, "
        f"executed={plan.executed_at}; a budgeted cost is disclosed, then authorized, then "
        "run — strictly in that order, or the disclosure is a receipt"
    )
    assert provider.calls == 4, (
        f"{provider.calls} provider calls after one authorized run over 4 submissions; the "
        "re-run refusal must leave the count where the first pass left it"
    )


# --- back-translation costs a handful -------------------------------------------------------------


@pytest.mark.parametrize("constructs", [True, False], ids=["constructs", "fails-to-construct"])
def test_tc_calib_18_back_translation_costs_exactly_the_bound_handful(constructs):
    """The gate's cost is exactly the attempts the session bound — three, both ways.

    "A handful of calls" is the design's word for back-translation's budget, and the handful is
    *bounded*: not one call, not one per submission. The bound attempts are the calls the gate
    makes, and the result's `attempts` record renders each — so the count is measured against
    what the fixture bound, on both the constructing and the failing transport.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "back_translate", issue="#140")

    ref = calib._off_panel_model_ref(constructs=constructs)
    result = calib.back_translate(r0="pkg-v1", r1="pkg-v2", off_panel=ref)

    assert len(result.attempts) == 3, (
        f"the gate rendered {len(result.attempts)} attempt(s); the fixture bound exactly three "
        "angles and back-translation costs a handful of calls — the attempts record is the "
        "count, and a class-size loop here would be the budget NFR-CALIB-03 does not authorize"
    )
    assert result.attempts[:2] == (
        "probing the top band's boundary: no construction",
        "probing the bottom band's boundary: no construction",
    ), (
        f"the first two attempts read {result.attempts[:2]!r}; both sessions probe the band "
        "boundaries first and neither constructs there, so two of the handful are spent "
        "finding nothing — visible in the record, not collapsed into a bare count"
    )
    third = result.attempts[2]
    if constructs:
        assert third == (
            "a response the clarified descriptor reads differently: "
            "constructed a divergent response"
        ), (
            f"the constructing session's third attempt reads {third!r}; the construction is "
            "rendered with its angle and its outcome, so the record shows which call paid off"
        )
    else:
        assert third == (
            "probing a mid-band response the clarifications touch: no construction"
        ), (
            f"the failing session's third attempt reads {third!r}; every angle appears with "
            "its outcome, so the handful is inspectable rather than a count alone"
        )