"""Validity T9 (issue #902): `TC-CALIB-24` — the clarified rubric's gates (FR-CALIB-18,
CT-CALIB-02, CT-CALIB-13). Rung 1.

Test plan (statistical-validity r2, §3.12):

- Back-translation runs at R₁ creation. (Rung 3, through the console's `examples answer`:
  `tests/integration/console/test_tc_console_112_115_examples_console.py::
  test_tc_calib_24_back_translation_runs_when_r1_is_created`.)
- Assumption threshold 0.10: 10 % of marks moving passes, 11 % fails.
- No path ships R₁ with a warning: a decision table over {BT pass/fail} × {NI pass/fail} gives
  R₁ only on pass/pass.

The decision is `aeh.calib.first_class.gate_decision`, the pure table `finish_first_class` reads;
the boundary is `aeh.calib.non_inferiority` over the module's band-shift roster seam
(`cohort_with_band_shift`), with the threshold passed as the declared value (never defaulted).
"""

from __future__ import annotations

import itertools

import pytest


@pytest.fixture(autouse=True)
def _no_standing_threshold():
    from aeh.calib import _clear_institutional_threshold

    _clear_institutional_threshold()
    yield
    _clear_institutional_threshold()


#: Every outcome a gate can report to the decision: passed, failed, or did not run.
OUTCOMES = ("pass", "fail", "not_run")


@pytest.mark.parametrize("bt, ni", list(itertools.product(OUTCOMES, OUTCOMES)))
def test_tc_calib_24_the_decision_table_gives_r1_only_on_pass_pass(bt, ni):
    """{BT} × {NI}: `live` (R1 delivered) exactly when both passed; every other cell sets R1
    aside. The table has two states only — there is no third "live with a warning"."""
    from aeh.calib.first_class import gate_decision

    decision = gate_decision(bt, ni)
    expected = "live" if (bt, ni) == ("pass", "pass") else "set_aside"
    assert decision == expected, (
        f"back-translation {bt} × non-inferiority {ni} decided {decision!r}; R1 ships only "
        "on pass/pass (CT-CALIB-02)")


@pytest.mark.parametrize("shifted, outcome", [(10, "pass"), (11, "reject")],
                         ids=["10-percent-passes", "11-percent-fails"])
def test_tc_calib_24_threshold_ten_percent_moving_passes_eleven_fails(shifted, outcome):
    """Threshold 0.10 on a class of 100: 10 papers moving a full band is not *more than* the
    threshold, so it passes; 11 is, so it fails — and the failure reverts to R0 with no note
    attached to a shipping revision."""
    from aeh.calib import cohort_with_band_shift, non_inferiority
    from aeh.calib.first_class import gate_decision

    cohort = cohort_with_band_shift(fraction=shifted / 100, class_size=100)
    result = non_inferiority(r0="pkg@r0", r1="pkg@r1", cohort_id=cohort, threshold=0.10)

    assert (result.shifted_papers, result.class_size) == (shifted, 100)
    assert result.threshold_used == 0.10 and result.threshold_source == "argument"
    assert result.outcome == outcome, (
        f"{shifted} of 100 moving against 0.10 gave {result.outcome!r}, expected {outcome!r} "
        "(FR-CALIB-08: rejected only when MORE than the threshold moved)")
    assert result.advisory_only is False
    assert result.revert_to == ("pkg@r0" if outcome == "reject" else None)
    # The gate's outcome, as finish_first_class maps it, decides R1 with a passed BT.
    ni = "pass" if result.outcome == "pass" else "fail"
    assert gate_decision("pass", ni) == ("live" if outcome == "pass" else "set_aside")
