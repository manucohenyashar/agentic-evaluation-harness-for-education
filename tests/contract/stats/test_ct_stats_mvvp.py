"""`CT-STATS-07`, `-08` — the MVVP is six answers, and it never outlives its configuration.

Test plan §6.11.16, `TC-STATS-C07` and `-C08`. Both clauses defend the same thing from two sides:
a validation result is a claim about one exact configuration, and the two ways it stops being true
are collapsing it into a verdict and carrying it across a change.

`CT-STATS-07`'s specific requirement is the one worth reading twice. A judge whose measured
self-agreement exceeds 0.95 must have its **position-bias result reported alongside**, because a
judge that answers identically every time may simply be anchored — high stability reported on its
own reads as reassurance and can coexist with severe position bias (§2.3). The pair is the
finding; either figure alone is a different, more comfortable claim.
"""

from __future__ import annotations

import pytest

from tests.support import stats_vocabulary as vocab
from tests.support.impl import STATS_MODULE, require

pytestmark = pytest.mark.contract

#: The configuration the sweep mutates, one dimension at a time. Values are this suite's; the four
#: **dimensions** are `FR-STATS-19`'s, transcribed and asserted in `test_ct_stats_vocabulary.py`.
BASE_CONFIGURATION: dict[str, object] = {
    "panel_member": ("judge-a", "judge-b", "judge-c"),
    "model_build": "qwen2.5-14b-instruct@3f9c",
    "quantization": "q4_K_M",
    "prompt_template_version": "judge-v7",
}

#: What the sweep changes each dimension to. One value per dimension so a failure names the change
#: that stopped triggering a re-run rather than reporting "the configuration changed".
CHANGED_TO: dict[str, object] = {
    "panel_member": ("judge-a", "judge-b", "judge-d"),
    "model_build": "qwen2.5-14b-instruct@7a02",
    "quantization": "q8_0",
    "prompt_template_version": "judge-v8",
}


# --- CT-STATS-07 — six steps, reported individually ------------------------------------------


@pytest.mark.writtenahead
def test_tc_stats_c07_reports_the_six_steps_individually_and_offers_no_single_verdict():
    """*"Reports the six MVVP steps **individually**, never as one pass/fail — asserted on the
    return type, since a convenience `passed` property is the plausible addition."*

    Two halves, and the second is the one the clause is actually about. Reporting six outcomes is
    easy to get right; keeping a seventh, summarising one from appearing is what needs a test,
    because the seventh is what every screen and every caller will ask for. Once `report.passed`
    exists, five of the six answers stop being read.

    The six are asserted against `FR-STATS-05`'s own mapping, so a step silently dropped — or two
    steps merged into one entry — fails here rather than being counted as "six things reported".
    """
    run_mvvp = require(STATS_MODULE, "run_mvvp", issue="#116")
    report = run_mvvp(assignment_type="extended_response")

    assert set(report.steps) == set(vocab.MVVP_STEPS), (
        f"the report covers steps {sorted(report.steps)}; FR-STATS-05 defines six: "
        f"{sorted(vocab.MVVP_STEPS)}"
    )
    for step, requirement in vocab.MVVP_STEPS.items():
        assert report.steps[step].requirement == requirement, (
            f"step {step} reports against {report.steps[step].requirement} rather than "
            f"{requirement} (FR-STATS-05)"
        )
        assert report.steps[step].outcome is not None, (
            f"step {step} has no outcome of its own, so the six are not separately reported"
        )

    collapsed = [
        name
        for name in ("passed", "ok", "success", "verdict", "overall", "is_valid")
        if hasattr(report, name)
    ]
    assert collapsed == [], (
        f"the MVVP report offers {collapsed}. CT-STATS-07: never as one pass/fail — a single "
        "verdict is what lets a screen show one thing and stop reading the other five."
    )


@pytest.mark.writtenahead
def test_tc_stats_c07_a_judge_above_the_stability_threshold_carries_its_position_bias_result():
    """`FR-STATS-18` — the paired-reporting fixture, constructed to sit exactly where it bites.

    A judge measured at 0.97 self-agreement (step 3) must have step 2's position-bias figure
    reported **with** it. The construction is the point: 0.97 alone is the most reassuring number
    in the whole protocol, and it is entirely compatible with a judge that assigns whatever band
    it sees first.

    The boundary is not asserted here. `FR-STATS-18` says *exceeds*, and a module that pairs the
    figures for every judge is not violating anything — asserting that a judge at exactly 0.95
    goes unpaired would fail a stricter implementation for being stricter.
    """
    run_mvvp = require(STATS_MODULE, "run_mvvp", issue="#116")

    report = run_mvvp(
        assignment_type="extended_response",
        measured_self_agreement={"judge-a": 0.97, "judge-b": 0.62},
    )
    step5 = report.steps[5]
    paired = step5.paired_results["judge-a"]

    assert paired.self_agreement > vocab.SELF_AGREEMENT_PAIRING_THRESHOLD, (
        "the fixture's stable judge is not above the threshold, so this asserts nothing"
    )
    assert paired.position_bias is not None, (
        "a judge measured at 0.97 self-agreement was reported without its position-bias result. "
        "FR-STATS-18: high stability is never reported as reassurance on its own — a judge that "
        "answers identically every time may simply be anchored (§2.3)."
    )


# --- CT-STATS-08 — the full re-run, and no carry-forward -------------------------------------


@pytest.mark.writtenahead
@pytest.mark.integration
@pytest.mark.parametrize("dimension", vocab.MVVP_RERUN_TRIGGERS)
def test_tc_stats_c08_the_full_mvvp_reruns_when_each_dimension_changes(dimension):
    """*"Swept one at a time, four cases, since a partial trigger set is the realistic bug."*

    Nobody implements zero triggers. What ships is three of four — panel membership and model
    build are obvious, quantization is easy to forget, and a prompt-template bump does not feel
    like a model change at all. So the sweep is per dimension and a failure names the one that
    stopped triggering.

    **Full**, not partial: steps 2–5 are the ones `FR-STATS-19` re-runs, and a result that re-ran
    step 3 alone while reusing step 2's position-bias figure is carrying a prior result across the
    change under a fresh timestamp.

    Rung 2 and marked `integration`: replication (step 3) runs each fixture judgment at least three
    times, and §4.10 budgets the contract tier at 60 seconds.
    """
    run_mvvp = require(STATS_MODULE, "run_mvvp", issue="#116")

    before = run_mvvp(assignment_type="extended_response", configuration=BASE_CONFIGURATION)
    changed = dict(BASE_CONFIGURATION, **{dimension: CHANGED_TO[dimension]})
    after = run_mvvp(assignment_type="extended_response", configuration=changed)

    assert after.result_id != before.result_id, (
        f"changing {dimension} returned the same MVVP result. FR-STATS-19 re-runs the full "
        "protocol on any of the four, and R30's risk is a validation record outliving the thing "
        "it validated."
    )
    for step in (2, 3, 4, 5):
        assert after.steps[step].measured_configuration[dimension] == CHANGED_TO[dimension], (
            f"step {step} reports having measured "
            f"{after.steps[step].measured_configuration[dimension]!r} after {dimension} changed "
            f"to {CHANGED_TO[dimension]!r} — a partial re-run, which is a prior result carried "
            "across the change under a fresh result id"
        )

    # Asserted per step on the **configuration it names**, not on a timestamp. Two MVVP runs under
    # `RecordedFixtureProvider` can complete inside one clock tick, so a `measured_at` comparison
    # would flake — and flakiness in a P0 case is how a case stops being trusted.


@pytest.mark.writtenahead
@pytest.mark.integration
def test_tc_stats_c08_a_prior_result_is_not_reused_shown_or_merged_after_a_change():
    """The prohibition that carries the risk: *"not reused, not shown, and not merged."*

    Two of the three verbs are `M-STATS`' to answer and both are asserted here. **Reused** is the
    stale figure returned as current; **merged** is the two averaged, which is the worst because
    the result is a number that was never measured anywhere — and it is unfalsifiable unless the
    result says what contributed to it, so that provenance is required rather than read with a
    default.

    **Shown** is a consumer's verb: displaying the stale figure beside the current one with equal
    standing is a rendering decision, and it belongs with `M-CONSOLE`'s cases rather than here.
    Naming it in a docstring while asserting nothing about it is how a suite comes to claim
    coverage it does not have.
    """
    run_mvvp = require(STATS_MODULE, "run_mvvp", issue="#116")
    latest_mvvp = require(STATS_MODULE, "latest_mvvp", issue="#116")

    stale = run_mvvp(assignment_type="extended_response", configuration=BASE_CONFIGURATION)
    changed = dict(BASE_CONFIGURATION, prompt_template_version="judge-v8")
    current = latest_mvvp(assignment_type="extended_response", configuration=changed)

    assert current.result_id != stale.result_id, "the stale result was reused as current"

    # `contributing_results` is **required**, not read with a default. A `getattr(..., ())` fallback
    # passes for a module that has no such attribute — including one that merged, since a merge
    # leaves no trace by construction. Review caught it: the assertion has to fail when the
    # provenance is missing, because missing provenance is indistinguishable from a merge.
    assert hasattr(current, "contributing_results"), (
        "the MVVP result does not say what contributed to it, so 'not merged' is unverifiable — "
        "and an unverifiable guarantee is one a consumer has to take on trust (FR-STATS-19, R30)"
    )
    assert stale.result_id not in current.contributing_results, (
        "the stale result contributed to the current one, so a figure measured under a different "
        "prompt template is inside a number presented as current"
    )
    assert current.measured_configuration["prompt_template_version"] == "judge-v8"


@pytest.mark.writtenahead
def test_tc_stats_c08_a_result_names_the_exact_configuration_it_measured():
    """*"A consumer can verify the match itself."*

    All four dimensions in the result, carrying the values the run actually used — which is what
    makes the no-carry-forward guarantee checkable by somebody who was not there. Without it, a
    consumer holding an MVVP result has to trust that the module noticed the change, and RISK-22
    is precisely that it did not.
    """
    run_mvvp = require(STATS_MODULE, "run_mvvp", issue="#116")
    report = run_mvvp(assignment_type="extended_response", configuration=BASE_CONFIGURATION)

    measured = report.measured_configuration
    for dimension in vocab.MVVP_RERUN_TRIGGERS:
        assert dimension in measured, (
            f"the MVVP result does not name the {dimension} it measured, so a consumer cannot "
            "check whether it still applies (CT-STATS-08)"
        )
        assert measured[dimension] == BASE_CONFIGURATION[dimension], (
            f"the result names a {dimension} other than the one the run used"
        )
