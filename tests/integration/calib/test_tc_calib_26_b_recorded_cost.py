"""Validity T9 (issue #902): `TC-CALIB-26` (NFR-CALIB-05) on TC-E2E-21's recordings.

Test plan (statistical-validity r2, §3.12): *"On TC-E2E-21's recordings, grading the 4 ENG7 sheets
as examples costs no more than the recorded cost of the 4-student class run (same size, as
NFR-CALIB-05 states it). The cost counts against the ceiling, and the setup read carries it. The
15-paper figure in the NFR is checked by scaling; no 15-sheet corpus exists."*

**Written ahead.** No ENG7 grading recordings exist; TC-E2E-21 (T17, #906) is their source
and recordings are never hand-written (the recording-honesty rule). `WRITTEN_AHEAD_BLOCKERS` key
"#906 TC-E2E-21 capture — TC-CALIB-26's recorded cost"; the probe resolves when a
`test_tc_e2e_21*` case exists. `RECORDINGS` below is this file's assumption of where T17 writes
them — re-point it when T17 lands. Note for T17: replaying the examples' grading needs the
capture to record the examples' own requests too (their documents sit in a calibration cohort
under example roster refs, so their request keys are not the class run's).

The same comparison under the stand-in transport runs green today:
`test_tc_calib_21_23_26_marked_examples.py::test_tc_calib_26_stand_in_examples_cost_no_more_than_the_class_run`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.impl import require_path

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

REPO = Path(__file__).resolve().parents[3]

#: Where T17 (#906) is assumed to write the ENG7 panel recordings.
RECORDINGS = REPO / "fixtures" / "F-ENG7-PANEL" / "recordings"


def test_tc_calib_26_b_recorded_examples_cost_no_more_than_the_recorded_class_run(
        tmp_path, monkeypatch, network_guard):
    from tests.integration.calib.test_tc_calib_21_23_26_marked_examples import _run_cost
    from tests.support.eng7_examples import eng7_examples, examples_checked

    require_path(RECORDINGS, "TC-E2E-21's ENG7 panel recordings", issue="#906")
    monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(RECORDINGS))
    with eng7_examples(tmp_path / "data", tmp_path / "work", monkeypatch,
                       network_guard) as world:
        monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(RECORDINGS))
        examples_checked(world)
        world.start_class()
        (run,) = world.class_runs()
        examples_run = world.store().cohort(world.calib_cohort()).query(
            "SELECT run_id FROM run")[0]["run_id"]
        examples_cost = _run_cost(world, examples_run)
        class_cost = _run_cost(world, run["run_id"])
        read = world.examples_read()
    assert 0 < examples_cost <= class_cost, (examples_cost, class_cost)
    assert examples_cost / 4 * 15 <= class_cost / 4 * 15
    assert float(read["cost"]["spent"]) == pytest.approx(examples_cost)
    assert read["cost"]["ceiling"] is not None and "run cost limit" in read["cost"]["text"]
