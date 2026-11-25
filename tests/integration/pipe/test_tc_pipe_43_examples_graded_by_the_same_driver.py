"""TC-PIPE-43 (issue #907; CT-PIPE-01 amended, FR-CALIB-17): examples are graded by the same driver.

Pair M-CALIB→M-PIPE. Statistical-validity test plan §3.12, story T10. M-CALIB grades 4 ENG7
marked examples, and the class is then graded too. Expected:

- both gradings go through `run_to_completion`. A wrapping spy (it calls the real driver)
  captures each call's run and result. M-CALIB reaches it through `aeh.pipeline.drive_run`, and
  the console's class start through the background worker;
- the examples' result carries the same stage set as the class run's. This is compared as a set
  of stage names, because pass counts differ with panel widening;
- the examples' cohort row reads `purpose = 'calibration'`, and the class's reads `class`.

TC-CALIB-21 (#902) already asserts the calibration cohort's purpose, from the examples read's
side. The overlap is noted in the PR. What is new here is the driver identity and the stage-set
parity.

**World.** `tests/support/eng7_examples.py`. The ENG7 class and test sit behind a real console
(rung 3), with the panel config and the stand-in OpenRouter transport. The four ENG7 sheets are
uploaded as the examples with `examples upload`, marked with `examples mark` and graded with
`examples grade`. The class is then started with the console's `start run`.

Markers: `integration`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

import aeh.pipeline
from tests.support.eng7_examples import SHEETS, eng7_examples, three_disagreements_rule
from tests.support.eng7_examples import THREE_DISAGREEMENTS_TEACHER

pytestmark = pytest.mark.integration

pytest.importorskip("pypdfium2")


def _cohort_of_run(root: Path, run_id: str) -> tuple[str, str]:
    """(cohort id, purpose) of the cohort file whose `run` table holds `run_id`."""
    found = []
    for path in sorted((root / "cohorts").glob("*.sqlite")):
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            if connection.execute("SELECT 1 FROM run WHERE run_id = ?", (run_id,)).fetchall():
                row = connection.execute("SELECT cohort_id, purpose FROM cohort").fetchone()
                found.append((str(row["cohort_id"]), str(row["purpose"])))
    assert len(found) == 1, f"run {run_id} found in {found}"
    return found[0]


def test_tc_pipe_43_examples_go_through_run_to_completion_with_the_class_stage_set(
        tmp_path, monkeypatch, network_guard) -> None:
    real = aeh.pipeline.run_to_completion
    calls: list[tuple[str, Any]] = []

    def spy(store: Any, run_id: str, *args: Any, **kwargs: Any) -> Any:
        result = real(store, run_id, *args, **kwargs)
        calls.append((str(run_id), result))
        return result

    # `package_patching` carries the patch to every `aeh.pipeline` file holding the driver
    # (`background.py`'s `drive_run` and its worker, `cli.py`).
    monkeypatch.setattr(aeh.pipeline, "run_to_completion", spy)

    with eng7_examples(tmp_path / "data", tmp_path / "work", monkeypatch, network_guard,
                       judge_rule=three_disagreements_rule) as world:
        _, job = world.upload()
        assert job["state"] == "succeeded", job
        assert len(world.document_of()) == len(SHEETS) == 4
        world.mark({stem: dict(THREE_DISAGREEMENTS_TEACHER) for stem in SHEETS})
        _, job = world.grade()
        assert job["state"] == "succeeded", job
        assert len(calls) == 1, f"grading the examples drove {len(calls)} runs"
        world.start_class()
        assert len(calls) == 2, f"the class start drove {len(calls) - 1} runs"
        calib_cohort = world.calib_cohort()
        root = world.root

    by_cohort = {}
    for run_id, result in calls:
        cohort_id, purpose = _cohort_of_run(root, run_id)
        by_cohort[cohort_id] = (purpose, result)
    assert set(by_cohort) == {calib_cohort, "class-eng7"}, sorted(by_cohort)

    examples_purpose, examples = by_cohort[calib_cohort]
    class_purpose, class_run = by_cohort["class-eng7"]
    assert (examples_purpose, class_purpose) == ("calibration", "class")
    assert examples.status == class_run.status == "complete", (examples.status, class_run.status)

    examples_stages = {trace.stage for trace in examples.stages}
    class_stages = {trace.stage for trace in class_run.stages}
    assert {"extract", "score", "aggregate", "grade"} <= class_stages, class_stages
    assert examples_stages == class_stages, (
        f"the examples ran stages {sorted(examples_stages)}; a class run "
        f"{sorted(class_stages)}: only in examples {sorted(examples_stages - class_stages)}, "
        f"only in class {sorted(class_stages - examples_stages)}")
