"""Validity T14 (issue #911): TC-CALIB-25 (FR-CALIB-19) — the marked examples as a reference set.
Statistical-validity test plan §3.12.

| Arm | What is asserted |
|---|---|
| no trigger | the four ENG7 examples graded under R0, then the console's `start run` on the class under the same configuration: no re-grade — no `reference_set` record, the calibration class still holds its one run, no consistency report on System status |
| each trigger | a run of the class frozen under a configuration changed in one FR-STATS-19 dimension at a time — panel member, model build, quantization, prompt template — and `on_run_started` (what `start run` calls) re-grades the examples each time: a fresh calibration run, a `reference_set` record whose trigger names the dimension, and per-criterion moved counts equal to the hand count of the judge's changed answers |
| the report | labelled "Consistency check", with no "accuracy" anywhere in it — as stored and as System status serves it; the served report is the newest |
| unchanged after | the same configuration asked again re-grades nothing |

**Moved counts, by hand.** The judge stand-in (`tests/support/eng7_examples.py`) answers the
lowest band unless the case's rule names one. R0's grading is the three-disagreement system:
C2 `full` on E7-004. Each re-grade then answers:

| Re-grade (trigger) | The rule's overrides | Moved against the previous grading |
|---|---|---|
| 1 `panel_member` | R0's, and C3 `evidenced` on E7-001 | C3 1 |
| 2 `model_build` | 1's, and C3 `evidenced` on E7-002, C2 `adequate` on E7-003 | C2 1, C3 1 |
| 3 `quantization` | 2's, unchanged | nothing |
| 4 `prompt_template_version` | none (every line at its lowest) | C2 2, C3 2 |

Every other criterion the examples are scored on moves 0 times, each out of the 4 examples.

**Disclosed.** The stand-in transport answers whatever model is named, so "the panel changed" is
a run of the class frozen by M-ORCH's own `create_run` under the console's resolved configuration
with that one dimension changed (`tests/support/grader_runs.py`) — what the trigger check reads —
not a different set of live models; the re-grade itself runs through the composition root's driver
under the console's configuration, as shipped. The judge's changed answers are what makes a
level move. No reply is a live recording.

**Red on main: a real defect.** The trigger check reads a run's grader configuration from the
row's `panel_config` / `provider_config` columns in `RunConfig.to_persisted_dict()`'s shape
(`aeh.stats.grader_configuration`, through `reference_set.run_configuration` and the console's
`run_grader_configuration`, both selecting only those two columns). M-ORCH writes `panel_config`
as `{"arms": [build ids]}` and keeps the frozen `RunConfig` in `run_config`, so the calibration
run and every class run read as the same empty configuration and no change ever re-grades the
examples: the case fails at the first trigger ("panel_member: no re-grade was scheduled"). The
no-trigger arm passes today for the same reason, vacuously; it becomes meaningful once the check
reads the real configuration. With the check reading `run_config` (tried locally, not shipped
here) every assertion below passes, the moved counts included.

**Written ahead: no** (#889 merged).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.support.eng7_examples import (
    SHEETS,
    THREE_DISAGREEMENTS_TEACHER,
    eng7_examples,
)

pytestmark = pytest.mark.integration

#: R0's overrides (the three-disagreement system) and each re-grade's, (paper, criterion) -> band.
R0 = {("E7-004-mostly-blank", "C2"): "full"}
REGRADES: list[tuple[str, dict[tuple[str, str], str], dict[str, int]]] = [
    ("panel_member", {**R0, ("E7-001-strong", "C3"): "evidenced"}, {"C3": 1}),
    ("model_build", {**R0, ("E7-001-strong", "C3"): "evidenced",
                     ("E7-002-middle", "C3"): "evidenced",
                     ("E7-003-weak", "C2"): "adequate"}, {"C2": 1, "C3": 1}),
    ("quantization", {**R0, ("E7-001-strong", "C3"): "evidenced",
                      ("E7-002-middle", "C3"): "evidenced",
                      ("E7-003-weak", "C2"): "adequate"}, {}),
    ("prompt_template_version", {}, {"C2": 2, "C3": 2}),
]


def _rule(overrides: dict[tuple[str, str], str]):
    def rule(paper: str, criterion: str, bands: tuple[str, ...], bands_text: str) -> str | None:
        return overrides.get((paper, criterion))
    return rule


def _change(dimension: str):
    """The change that moves one FR-STATS-19 dimension of a resolved `RunConfig`."""
    from tests.support import grader_runs

    return {
        "panel_member": grader_runs.change_panel_member,
        "model_build": grader_runs.change_model_build,
        "quantization": grader_runs.change_quantization,
        "prompt_template_version": grader_runs.change_prompt_template,
    }[dimension]


def _reference_records(world: Any) -> list[dict]:
    from aeh.pkg import graders_records

    return graders_records(world.store(), kind="reference_set",
                           package_version_id=world.package_version)


def _calib_runs(world: Any) -> list[dict]:
    import sqlite3

    path = world.root / "cohorts" / f"{world.calib_cohort()}.sqlite"
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(
            "SELECT run_id, status FROM run ORDER BY started_at, run_id")]


def _graders(world: Any) -> dict:
    status, read = world.get("/api/v1/system-status")
    assert status == 200, (status, read)
    return read["graders"]


def test_tc_calib_25_each_trigger_regrades_the_examples_and_no_trigger_does_not(
        tmp_path, monkeypatch, network_guard) -> None:
    from aeh.calib.reference_set import CONSISTENCY_LABEL
    from aeh.console.graders import on_run_started
    from aeh.console.run_start import compose_run_start_config
    from tests.support import grader_runs

    with eng7_examples(tmp_path / "data", tmp_path / "work", monkeypatch, network_guard,
                       judge_rule=_rule(R0)) as world:
        _, job = world.upload()
        assert job["state"] == "succeeded", job
        world.mark({stem: dict(THREE_DISAGREEMENTS_TEACHER) for stem in SHEETS})
        _, job = world.grade()
        assert job["state"] == "succeeded", job
        assert [r["status"] for r in _calib_runs(world)] == ["complete"]

        # No trigger: the class runs under the configuration the examples were graded under.
        world.start_class()
        class_runs = world.class_runs()
        assert [r["status"] for r in class_runs] == ["complete"], class_runs
        assert _reference_records(world) == [], (
            "the examples were re-graded although no grader dimension changed: "
            f"{_reference_records(world)}")
        assert len(_calib_runs(world)) == 1, _calib_runs(world)
        assert _graders(world)["consistency_report"] is None

        cfg = grader_runs.console_run_config(world.server.app, world.cohort_id)
        # The configuration `start run` hands `on_run_started` (effects.py), composed the same way.
        start_config = compose_run_start_config(world.server.app, {
            "cohort_id": world.cohort_id, "package_version": world.package_version})
        for number, (dimension, overrides, moved) in enumerate(REGRADES, start=1):
            cfg = _change(dimension)(cfg)
            run_id = grader_runs.frozen_run(world.root, world.cohort_id, world.package_version,
                                            cfg)
            world.judge_rule = _rule(overrides)
            thread = on_run_started(world.server.app, run_id=run_id, cohort_id=world.cohort_id,
                                    package_version_id=world.package_version,
                                    config=start_config)
            assert thread is not None, f"{dimension}: no re-grade was scheduled"
            thread.join(600)
            assert not thread.is_alive(), f"{dimension}: the re-grade did not finish"

            records = _reference_records(world)
            assert len(records) == number, (dimension, records)
            latest = records[0]
            assert latest["outcome"] == "ran", (dimension, latest["detail"])
            assert dimension in latest["trigger"].split(","), (dimension, latest["trigger"])
            if dimension != "panel_member":
                assert latest["trigger"] == dimension, latest["trigger"]
            calib = _calib_runs(world)
            assert len(calib) == number + 1 and calib[-1]["status"] == "complete", calib
            assert latest["detail"]["run_id"] == calib[-1]["run_id"]
            assert latest["detail"]["previous_run_id"] == calib[-2]["run_id"]
            criteria = latest["detail"]["criteria"]
            assert {"C1a", "C1b", "C2", "C3"} <= set(criteria), criteria
            assert {name: counts["moved"] for name, counts in criteria.items()} == {
                name: moved.get(name, 0) for name in criteria}, (dimension, criteria)
            assert all(counts["examples"] == 4 for counts in criteria.values()), criteria
            text = json.dumps(latest).lower()
            assert latest["detail"]["label"] == CONSISTENCY_LABEL == "Consistency check"
            assert "accuracy" not in text, (dimension, latest)

        # Nothing changed since the last re-grade: nothing is re-graded.
        run_id = grader_runs.frozen_run(world.root, world.cohort_id, world.package_version, cfg)
        assert on_run_started(world.server.app, run_id=run_id, cohort_id=world.cohort_id,
                              package_version_id=world.package_version,
                              config=start_config) is None
        assert len(_reference_records(world)) == len(REGRADES)

        served = _graders(world)["consistency_report"]
    assert served is not None
    assert served["label"] == "Consistency check"
    assert served["trigger"] == "prompt_template_version", served
    assert {name: counts["moved"] for name, counts in served["criteria"].items()} == {
        name: REGRADES[-1][2].get(name, 0) for name in served["criteria"]}, served
    assert "accuracy" not in json.dumps(served).lower(), served
