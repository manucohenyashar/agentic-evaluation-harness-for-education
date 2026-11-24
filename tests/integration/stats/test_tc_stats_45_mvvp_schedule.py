"""Validity T14 (issue #911): TC-STATS-45 (FR-STATS-36) — the MVVP schedule. Statistical-validity
test plan §3.13.

| Arm | What is asserted |
|---|---|
| (a) approval | the console's `approve draft package` on the ENG7 draft runs `run_mvvp` exactly once (spy, joined on the approval's measuring thread); a second press of the unchanged draft runs nothing more; one `graders_record` row, trigger `package_approval`, outcome `ran`; System status's `graders.mvvp` shows it |
| (b) each trigger | on the ENG7 console, after the class's first run measured the graders, a run of the class frozen by M-ORCH under one changed dimension — panel member, model build, quantization, prompt template, a decision engine swapped in — runs `run_mvvp` once per change, the record's trigger naming the changed dimensions; a run under the unchanged configuration runs nothing |
| (c) cost ceiling | `HARNESS_MVVP_ESTIMATED_COST` 16 against the run's frozen ceiling 15 (the shipped panel config's): the console run's MVVP is refused before `run_mvvp` (spy 0), recorded `refused` with the reason, System status shows the refusal, and the refused configuration is not retried; at exactly 15 `schedule_mvvp` runs it (the comparison is "over", not "at") |
| (d) inside promote | `promote_administration` on the validity seed calls the compression check and the surface-proxy measurement once each (spies on `aeh.stats.promotion`), the stored record carries the compression outcome, and System status serves it |
| (e) console run start | on the ENG7 console, `start run` with no earlier measurement runs the MVVP once (trigger: every dimension); asking again for the same run's unchanged configuration schedules nothing |

**Seams.** `run_mvvp` is spied on its module (`schedule_mvvp` imports it at call time); the
compression check and the length correlations are spied where `promote` binds them. Every spy
calls through. Arm (b)'s later runs are real run rows written by M-ORCH's `create_run` under the
console's resolved configuration with one dimension changed (`tests/support/grader_runs.py`),
handed to `on_run_started` — the function the console's `start run` calls — on the console's own
app; the measuring thread it returns is joined. They are never driven: the trigger reads only the
frozen row.

**Red on main: a real defect (arm b).** `grader_configuration` reads the run row's
`panel_config` / `provider_config` columns as if they held `RunConfig.to_persisted_dict()`'s
shape, and `on_run_started` selects only those two columns. M-ORCH writes `panel_config` as the
work-identity string `{"arms": [build ids]}` and keeps the whole frozen `RunConfig` in the
`run_config` column, so every real run reads as the same empty configuration (no panel, no
build, no quantization, no template, engine `off`): after a version's first measurement no
FR-STATS-19 change ever triggers the MVVP. Arm (b) fails at the first change. Arms (a), (c) and
(e) do not depend on change detection.

**"Results go to System status" (FR-STATS-36), as read here.** System status serves the latest
scheduled MVVP (arms a, c) and the latest record's compression check (arm d); arm (d) asserts both.
The surface-proxy result is stored with the record (`package_validation.surface_proxy_flags`) but
System status's `graders` block does not serve it, so no assertion here can check it there. That
is a reported gap for the owner to rule on (does FR-STATS-36's sentence cover the surface
proxies?), not a weaker oracle chosen quietly.

**Written ahead: no** (#889 merged).
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Iterator

import pytest

import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ  # noqa: F401,E401
import aeh.judge, aeh.orch, aeh.pkg, aeh.review, aeh.synth  # noqa: F401,E401
from tests.support.console_redesign_world import served_console  # noqa: F401 - fixture
from tests.support.label_identity_world import ServedRun

pytestmark = pytest.mark.integration

#: How long one measuring thread may take (seconds).
JOIN_S = 120.0


class _Spy:
    """Call-through spy: counts calls and keeps each return value."""

    def __init__(self, real: Any) -> None:
        self.real = real
        self.calls: list[tuple[tuple, dict]] = []
        self.returned: list[Any] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        value = self.real(*args, **kwargs)
        self.returned.append(value)
        return value


@pytest.fixture
def run_mvvp_spy(monkeypatch):
    import aeh.stats.mvvp as mvvp
    from aeh.console import graders

    spy = _Spy(mvvp.run_mvvp)
    monkeypatch.setattr(mvvp, "run_mvvp", spy)
    monkeypatch.delenv("HARNESS_MVVP_ESTIMATED_COST", raising=False)
    graders._IN_FLIGHT.clear()
    yield spy
    for thread in threading.enumerate():
        if thread.name.startswith("aeh-graders-"):
            thread.join(JOIN_S)
    graders._IN_FLIGHT.clear()


def _records(store: Any, version: str | None = None) -> list[dict]:
    from aeh.pkg import graders_records

    return graders_records(store, kind="mvvp", package_version_id=version)


@contextmanager
def _status_console(store: Any, monkeypatch: Any, network_guard: Any,
                    run_id: str | None = None) -> Iterator[ServedRun]:
    from aeh.console import serve_console

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    network_guard.uninstall()
    try:
        server = serve_console(store=store, run_id=run_id)
        try:
            yield ServedRun(world=None, server=server, port=server.socket.getsockname()[1],
                            root=store.data_dir)
        finally:
            server.terminate()
    finally:
        network_guard.install()


def _graders(console: ServedRun) -> dict:
    status, read = console.get("/api/v1/system-status")
    assert status == 200, (status, read)
    return read["graders"]


# --- (a) package approval -----------------------------------------------------------------------


def test_tc_stats_45_a_package_approval_runs_the_mvvp_once(served_console, run_mvvp_spy) -> None:
    from aeh.console import graders
    from aeh.stats import PACKAGE_APPROVAL_TRIGGER
    from tests.support.clarity_world import write_eng7_draft
    from tests.support.console_redesign_world import _action

    _server, port, store, data_dir = served_console
    started: list[threading.Thread] = []
    real = graders.on_package_approved

    def watched(app: Any, version: str) -> Any:
        thread = real(app, version)
        if thread is not None:
            started.append(thread)
        return thread

    # The approval imports the trigger at call time, so the module attribute is the seam.
    graders.on_package_approved = watched
    try:
        write_eng7_draft(data_dir / "authoring", {"pass": None, "not yet": None})
        assert _action(port, "answer authoring review", {
            "package_id": "ENG7-READ-01",
            "answers": [{"item_id": "approved_by", "value": "Dana Teacher"},
                        {"item_id": "grades pass", "value": "6"}]})["refused"] is False
        first = _action(port, "approve draft package", {"package_id": "ENG7-READ-01"})
        assert first["refused"] is False, first
        assert len(started) == 1, "the approval scheduled no measurement"
        started[0].join(JOIN_S)
        assert not started[0].is_alive()
        assert len(run_mvvp_spy.calls) == 1, run_mvvp_spy.calls

        again = _action(port, "approve draft package", {"package_id": "ENG7-READ-01"})
        assert again["refused"] is False and again["detail"].startswith("Already published")
        for thread in started:
            thread.join(JOIN_S)
    finally:
        graders.on_package_approved = real

    assert len(run_mvvp_spy.calls) == 1, "the second press of an unchanged draft ran the MVVP"
    records = _records(store)
    assert [(r["trigger"], r["outcome"]) for r in records] == [
        (PACKAGE_APPROVAL_TRIGGER, "ran")], records
    assert set(records[0]["detail"]["steps"]) == {"1", "2", "3", "4", "5", "6"}, records[0]

    status, read = ServedRun(world=None, server=None, port=port, root=data_dir).get(
        "/api/v1/system-status")
    assert status == 200, read
    mvvp = read["graders"]["mvvp"]
    assert (mvvp["trigger"], mvvp["outcome"], mvvp["refusal"]) == (
        PACKAGE_APPROVAL_TRIGGER, "ran", None), mvvp
    assert set(mvvp["steps"]) == {"1", "2", "3", "4", "5", "6"}, mvvp


# --- (b) and (c): the run-start trigger on a frozen configuration ------------------------------


def _started(world: Any, run_id: str) -> Any:
    """What the console's `start run` does once a run has started: `on_run_started` on the
    console's own app, joined."""
    from aeh.console.graders import on_run_started

    thread = on_run_started(world.server.app, run_id=run_id, cohort_id=world.cohort_id,
                            package_version_id=world.package_version, config=None)
    if thread is not None:
        thread.join(JOIN_S)
        assert not thread.is_alive(), "the measuring thread did not finish"
    return thread


def test_tc_stats_45_b_each_grader_dimension_and_an_engine_swap_trigger_the_mvvp(
        tmp_path, monkeypatch, network_guard, run_mvvp_spy) -> None:
    """The class's first console run measures the graders (no baseline); each later run frozen
    by M-ORCH under one changed dimension measures them again, its record naming the change; a
    run under the last configuration again measures nothing."""
    from tests.support import grader_runs
    from tests.support.eng7_examples import eng7_examples

    changes = [
        (grader_runs.change_panel_member, "panel_member,model_build"),
        (grader_runs.change_model_build, "model_build"),
        (grader_runs.change_quantization, "quantization"),
        (grader_runs.change_prompt_template, "prompt_template_version"),
        (grader_runs.swap_in_decision_engine, "model_build,decision_engine"),
    ]
    with eng7_examples(tmp_path / "data", tmp_path / "work", monkeypatch,
                       network_guard) as world:
        world.start_class()
        assert len(run_mvvp_spy.calls) == 1, "a never-measured version was not measured"
        cfg = grader_runs.console_run_config(world.server.app, world.cohort_id)
        for count, (change, trigger) in enumerate(changes, start=2):
            cfg = change(cfg)
            run_id = grader_runs.frozen_run(world.root, world.cohort_id,
                                            world.package_version, cfg)
            assert _started(world, run_id) is not None, (
                f"{trigger}: a run frozen under a changed grader configuration scheduled no "
                "MVVP")
            assert len(run_mvvp_spy.calls) == count, (trigger, len(run_mvvp_spy.calls))
            latest = _records(world.store(), world.package_version)[0]
            assert (latest["trigger"], latest["outcome"]) == (trigger, "ran"), latest

        # Unchanged: another run under the same configuration measures nothing.
        run_id = grader_runs.frozen_run(world.root, world.cohort_id, world.package_version, cfg)
        assert _started(world, run_id) is None
        assert len(run_mvvp_spy.calls) == len(changes) + 1
        assert len(_records(world.store(), world.package_version)) == len(changes) + 1


def test_tc_stats_45_c_over_the_run_cost_ceiling_the_mvvp_is_refused_and_recorded(
        tmp_path, monkeypatch, network_guard, run_mvvp_spy) -> None:
    """`HARNESS_MVVP_ESTIMATED_COST` 16 against the run's frozen ceiling 15 (the shipped panel
    config's): refused before `run_mvvp`, recorded with the reason, served on System status; at
    exactly the ceiling `schedule_mvvp` runs it."""
    from aeh.stats import schedule_mvvp
    from tests.support.eng7_examples import eng7_examples

    monkeypatch.setenv("HARNESS_MVVP_ESTIMATED_COST", "16")
    with eng7_examples(tmp_path / "data", tmp_path / "work", monkeypatch,
                       network_guard) as world:
        world.start_class()
        assert run_mvvp_spy.calls == [], "the MVVP ran over the run cost ceiling"
        records = _records(world.store(), world.package_version)
        assert len(records) == 1 and records[0]["outcome"] == "refused", records
        refusal = records[0]["detail"]["refusal"]
        assert refusal == "the MVVP's expected cost 16 is over the run cost ceiling 15", refusal
        mvvp = _graders(world)["mvvp"]
        assert (mvvp["outcome"], mvvp["refusal"]) == ("refused", refusal), mvvp
        # A refusal is the baseline: the same run's unchanged configuration is not retried.
        assert _started(world, world.class_runs()[0]["run_id"]) is None
        assert run_mvvp_spy.calls == []

        # At the ceiling exactly it runs: the gate is "over", not "at".
        at = schedule_mvvp(world.store(), package_version_id=world.package_version,
                           trigger="tc-stats-45-at-ceiling", configuration={},
                           cost_ceiling=Decimal("15"),
                           environ={"HARNESS_MVVP_ESTIMATED_COST": "15"})
        assert at.ran and at.refusal is None, at
        assert len(run_mvvp_spy.calls) == 1
        assert _records(world.store(), world.package_version)[0]["outcome"] == "ran"


# --- (d) the compression check and the surface proxies inside promote ---------------------------


def test_tc_stats_45_d_compression_and_surface_proxies_run_inside_promote(
        tmp_path, monkeypatch, network_guard) -> None:
    import dataclasses

    import aeh.stats.promotion as promotion
    from tests.support.validity_seed import validity_seed

    compression = _Spy(promotion._compression_outcome)
    correlations = _Spy(promotion._length_correlations)
    monkeypatch.setattr(promotion, "_compression_outcome", compression)
    monkeypatch.setattr(promotion, "_length_correlations", correlations)
    world, administration = validity_seed(tmp_path / "w")
    try:
        assert compression.calls == [] and correlations.calls == []
        assert world.promote(administration, "finish").promoted
        assert len(compression.calls) == 1, compression.calls
        assert len(correlations.calls) == 1, correlations.calls
        runs = correlations.calls[0][0][1]
        assert set(runs) == {administration.run_id}, runs
        stored = world.package_validation(administration)
        assert len(stored) == 1 and stored[0]["compression"], stored
        expected = json.loads(json.dumps(dataclasses.asdict(compression.returned[0])))
        assert json.loads(stored[0]["compression"]) == expected
        with _status_console(world.store, monkeypatch, network_guard,
                             run_id=administration.run_id) as console:
            served = _graders(console)["compression"]
        assert served == expected, served
    finally:
        try:
            world.close()
        except Exception as error:  # noqa: BLE001
            if "same thread" not in str(error):
                raise


# --- (e) the console's own start run ------------------------------------------------------------


def test_tc_stats_45_e_console_start_run_measures_new_graders_once(
        tmp_path, monkeypatch, network_guard, run_mvvp_spy) -> None:
    from aeh.console.graders import on_run_started
    from aeh.stats import GRADER_DIMENSIONS
    from tests.support.eng7_examples import eng7_examples

    with eng7_examples(tmp_path / "data", tmp_path / "work", monkeypatch,
                       network_guard) as world:
        world.start_class()
        runs = world.class_runs()
        assert [r["status"] for r in runs] == ["complete"], runs
        assert len(run_mvvp_spy.calls) == 1, "the first start run did not measure the graders"
        records = _records(world.store(), world.package_version)
        assert [(r["trigger"], r["outcome"]) for r in records] == [
            (",".join(GRADER_DIMENSIONS), "ran")], records
        again = on_run_started(world.server.app, run_id=runs[0]["run_id"],
                               cohort_id=world.cohort_id,
                               package_version_id=world.package_version, config=world.config)
        assert again is None, "an unchanged configuration scheduled a measurement"
        assert len(run_mvvp_spy.calls) == 1
