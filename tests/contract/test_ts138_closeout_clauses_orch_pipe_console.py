"""TS-138 (#549): design 1.9's clause suites — M-ORCH, M-PIPE, M-CONSOLE.

| Case | Clause | Assertion (breaks if the clause is broken) |
|---|---|---|
| TC-ORCH-C31 | CT-ORCH-31 | engine on, every seat claim accrues LLM + 0.000063 and every NON-seat claim the LLM figure alone; engine off, every claim the LLM figure alone |
| TC-ORCH-C32 | CT-ORCH-32 | `submissions` lists a deterministic-only run's submissions and never another run's |
| TC-ORCH-C33 | CT-ORCH-33 | one replacement per cell per quarantine, a new arm identity, one escalation request recorded, refused over budget |
| TC-ORCH-C34 | CT-ORCH-34 | a defaulted `wall_clock` changes no outcome (row sets equal); an injected one gives the exact figure |
| TC-PIPE-C10 | CT-PIPE-10 | over a full F-DEV-PIPE run no escalation input is `None`; the anomaly limb fires for a criterion iff it has a stored baseline |
| TC-PIPE-C11 | CT-PIPE-11 | after `recover`, no complete run holds scores without a current grade; a double recover leaves one revision per submission |
| TC-PIPE-C12 | CT-PIPE-12 | one quarantined arm never pauses the run, budget available or exhausted, and leaves no unit open |
| TC-PIPE-C13 | CT-PIPE-13 | over a mixed package each enumerated submission is offered to synthesis exactly once (counter spy) |
| TC-CONSOLE-C29 | CT-CONSOLE-29 | two runs render two provenance lines, each equal to the line its run's resolved config implies; Jev names provider and build; no credential, URL or confidence |

Disclosed, TC-ORCH-C33 (a plan finding): the plan's "the budget counter increments by 1" has no
counter to move. The escalation rate counts escalated CELLS (`select_escalated_results`), and a
replacement is only ever requested for a widened cell, which is already counted. What CT-ORCH-33's
"counts against the escalation budget" does observably is (i) record the replacement as an
escalation request and (ii) refuse it over budget; both are asserted. TC-REQ-122 (TS-139) pins
the dispatch half (a replacement is deferred like any escalation when over budget).
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.pkg  # noqa: F401,E401
import aeh.review, aeh.synth  # noqa: F401,E401
import aeh.pipeline as pipeline
from aeh import pkg
from aeh.console import SCREENS, build_console
from aeh.orch import (
    ESCALATION_BUDGET_ENV,
    REPLACEMENT_ALREADY_REQUESTED,
    REPLACEMENT_INSERTED,
    REPLACEMENT_REFUSED,
    STAGE_SCORE,
    Orchestrator,
)
from aeh.store import open_store
from tests.integration.console.test_ts135_grade_provenance import (  # noqa: F401 (the fixture)
    JEV_BUILD, JEV_CONFIDENCE, JEV_URL, SENTINEL, _cloud_engine_config, two_runs)
from tests.integration.orch.test_ts133_closeout_orch import (
    _ScoreOnlySeam, _arms, _pause_resume_rows, _quarantine, _widened_cell)
from tests.integration.pipe.test_ts134_closeout_pipe import (
    _EscalationSpy, _anomalous, _cohort_rows, _grades, _key, _quarantine_one_widened_arm,
    _seed_baseline, _world)
from tests.support import pipe_world
from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_cohort, seed_package, seed_run

#: The per-seat decision figure (FR-ORCH-41), as TC-ORCH-54 pins it.
SEAT = Decimal("0.000063")
LLM = Decimal("0.002")


# --- TC-ORCH-C31 ----------------------------------------------------------------------------


def _three_arm_config(engine_on: bool):
    from aeh.conf import CohortRef, ModelRef, resolve_run_config
    from tests.support.conf_builders import hosted_cfg

    panel = tuple(ModelRef(role="judge", provider="openrouter",
                           build_id=f"openrouter/judge-{i}@2026-01-01", quantization=None)
                  for i in range(3))
    extra = ({"HARNESS_DECISION_ENGINE": "jev", "HARNESS_JEV_BUILD": JEV_BUILD}
             if engine_on else {})
    return resolve_run_config(
        hosted_cfg("cloud-hosted", panel=panel, HARNESS_COST_CEILING="12.50", **extra),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"))


def _claim_deltas(data_dir: Path, engine_on: bool) -> tuple[list[str], list[tuple[str, Decimal]]]:
    """Every score claim's judge and the `cost_spend` it moved, over a 3-arm holistic panel."""
    from aeh.prov import JevOpenRouterProvider

    store = open_store(data_dir)
    try:
        cohort = seed_cohort(store, ["S1", "S2"])
        version = seed_package(store, [{"criterion_id": "C1", "kind": "open",
                                        "scoring_model": "holistic"}])
        decider = (JevOpenRouterProvider(api_key="k", retention_answers=lambda b: "zero-retention")
                   if engine_on else None)
        orch = Orchestrator(store, provider=_ScoreOnlySeam(), decision_provider=decider)
        run_id = orch.create_run(cohort, version, _three_arm_config(engine_on))
        orch.enumerate_units(run_id)
        orch.start(run_id)
        handle = store.cohort(cohort)

        def spend() -> Decimal:
            row = handle.query("SELECT cost_spend FROM run WHERE run_id = :r", r=run_id)[0]
            return Decimal(str(row["cost_spend"] or "0"))

        while units := orch.lease("w", "extract", 1):
            orch.complete(units[0].work_id)
        arms = json.loads(handle.query("SELECT panel_config FROM run WHERE run_id = :r",
                                       r=run_id)[0]["panel_config"])["arms"]
        deltas: list[tuple[str, Decimal]] = []
        before = spend()
        while units := orch.lease("w", STAGE_SCORE, 1):
            after = spend()
            deltas.append((units[0].judge, after - before))
            before = after
            orch.complete(units[0].work_id)
        return arms, deltas
    finally:
        store.close()


def test_tc_orch_c31_only_a_seat_claim_carries_the_decision_figure(tmp_path):
    arms, on = _claim_deltas(tmp_path / "on", engine_on=True)
    assert len(on) == 6 and any(j != arms[0] for j, _d in on), f"fixture: claims {on}"
    for judge, delta in on:
        expected = LLM + (SEAT if judge == arms[0] else Decimal("0"))
        assert delta == expected, (
            f"a claim by {judge} ({'seat' if judge == arms[0] else 'non-seat'}) moved cost_spend "
            f"by {delta}, not {expected} (CT-ORCH-31)")
    _arms_off, off = _claim_deltas(tmp_path / "off", engine_on=False)
    assert [d for _j, d in off] == [LLM] * 6, f"engine-off claims moved spend by {off} (NFR-SYS-14)"


# --- TC-ORCH-C32 ----------------------------------------------------------------------------


def test_tc_orch_c32_submissions_covers_a_deterministic_only_run_and_only_it(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        orch, r1, _v = seed_run(store, submissions=("S1", "S2"),
                                criteria=({"criterion_id": "C9", "kind": "mcq"},))
        orch.enumerate_units(r1)
        seed_cohort(store, ["S9"], cohort_id="c-ts138-other")
        other = seed_package(store, [{"criterion_id": "C1", "kind": "open",
                                      "scoring_model": "atomic"}], package_id="pkg-ts138-other")
        r2 = Orchestrator(store).create_run("c-ts138-other", other, orch_cfg("edge-local"))
        Orchestrator(store).enumerate_units(r2)
        assert orch.submissions(r1) == ("S1", "S2"), orch.submissions(r1)
        assert orch.submissions(r2) == ("S9",), orch.submissions(r2)
    finally:
        store.close()


# --- TC-ORCH-C33 ----------------------------------------------------------------------------


def _requests(cohort, run_id) -> int:
    return int(cohort.query("SELECT COUNT(*) AS n FROM escalation_request WHERE run_id = :r",
                            r=run_id)[0]["n"])


def test_tc_orch_c33_one_new_arm_per_quarantine_budgeted_like_an_escalation(tmp_data_dir, monkeypatch):
    store = open_store(tmp_data_dir)
    try:
        orch, run_id, cohort = _widened_cell(store)
        panel = _arms(cohort, run_id)
        _quarantine(tmp_data_dir, run_id, panel[-1])
        requests = _requests(cohort, run_id)
        with cohort.transaction() as tx:
            first = orch.enqueue_replacement_arm(tx, (run_id, "S1", "C1"))
        assert first.decision == REPLACEMENT_INSERTED and first.arm not in panel, first
        assert _requests(cohort, run_id) == requests + 1, "the replacement is not a recorded escalation"
        with cohort.transaction() as tx:
            again = orch.enqueue_replacement_arm(tx, (run_id, "S1", "C1"))
        assert again.decision == REPLACEMENT_ALREADY_REQUESTED, again
        assert _arms(cohort, run_id) == panel + [first.arm]
        assert _requests(cohort, run_id) == requests + 1, "a repeat recorded a second request"
    finally:
        store.close()
    store = open_store(tmp_data_dir / "over")
    try:
        orch, run_id, cohort = _widened_cell(store)
        panel = _arms(cohort, run_id)
        _quarantine(tmp_data_dir / "over", run_id, panel[-1])
        # Nothing is processed in this fixture (rate 0/0), so the observed rate is set above
        # the shipped budget through the seam TC-ORCH-56 (b) uses.
        monkeypatch.setattr(Orchestrator, "_escalation_rate", lambda self, ex, run: (10, 9, 0.9))
        with cohort.transaction() as tx:
            refused = orch.enqueue_replacement_arm(tx, (run_id, "S1", "C1"))
        assert refused.decision == REPLACEMENT_REFUSED and "budget" in refused.reason, refused
        assert _arms(cohort, run_id) == panel
    finally:
        store.close()


# --- TC-ORCH-C34 ----------------------------------------------------------------------------


def test_tc_orch_c34_the_wall_clock_seam_changes_figures_never_outcomes(tmp_path):
    from datetime import datetime, timedelta, timezone

    fixed = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    assert (_pause_resume_rows(tmp_path / "i", lambda s: Orchestrator(s, wall_clock=lambda: fixed))
            == _pause_resume_rows(tmp_path / "d", lambda s: Orchestrator(s)))
    now = {"t": fixed}
    store = open_store(tmp_path / "fig")
    try:
        _o, run_id, _v = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        orch = Orchestrator(store, wall_clock=lambda: now["t"])
        orch.enumerate_units(run_id)
        orch.start(run_id)
        now["t"] += timedelta(hours=2, minutes=5)
        assert orch._run_wall_clock_ms(store.cohort(ORCH_COHORT_ID), run_id) == 7_500_000
    finally:
        store.close()


# --- TC-PIPE-C10 ----------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("stored", [False, True], ids=["no-baseline", "c1-baseline"])
def test_tc_pipe_c10_inputs_are_never_none_and_the_anomaly_limb_follows_the_baseline(
        tmp_path, monkeypatch, stored):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        if stored:
            _seed_baseline(root, _key(world), "C1")
        spy = _EscalationSpy(monkeypatch)
        pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert spy.of("C1") and spy.of("C2"), [(c.criterion_id, c.ordinal) for c in spy.calls]
    for call in spy.calls:
        assert call.baseline is not None and call.history is not None, call
        has_baseline = not isinstance(call.baseline, pkg.NoValidationData)
        assert has_baseline == (stored and call.criterion_id == "C1"), call
        # mean 2.0, sd 0.5: every C1 ordinal in the corpus (0, 3, 5) is 2+ sd out.
        assert _anomalous(call) == has_baseline, (
            f"{call.criterion_id} at {call.ordinal}: anomaly {_anomalous(call)} with baseline "
            f"{call.baseline!r} (CT-PIPE-10: evaluated iff a baseline is stored)")


# --- TC-PIPE-C11 ----------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_pipe_c11_recover_leaves_no_complete_run_ungraded(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        assert pipe_world.drive_composed(world).status == "complete"
        with sqlite3.connect(root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite") as c:
            c.execute("DELETE FROM submission_grade")
        pipeline.recover(world.store)
        pipeline.recover(world.store)
    finally:
        world.store.close()
    for run in _cohort_rows(root, "SELECT run_id FROM run WHERE status = 'complete'"):
        scored = {r[0] for r in _cohort_rows(
            root, "SELECT DISTINCT submission_id FROM criterion_score WHERE run_id = ?", run[0])}
        grades = _grades(root, run[0])
        assert {g["submission_id"] for g in grades if g["is_current"]} == scored, (run[0], grades)
        per = Counter(g["submission_id"] for g in grades)
        assert set(per.values()) == {1}, f"a double recover wrote more than one revision: {per}"


# --- TC-PIPE-C12 ----------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("budget", ["available", "exhausted"])
def test_tc_pipe_c12_one_quarantined_arm_never_pauses_the_run(tmp_path, monkeypatch, budget):
    decisions: list[str] = []
    real = Orchestrator.enqueue_replacement_arm

    def replacement(self, tx, key):
        if budget == "exhausted":
            monkeypatch.setenv(ESCALATION_BUDGET_ENV, "0.0")
        report = real(self, tx, key)
        decisions.append(report.decision)
        return report

    monkeypatch.setattr(Orchestrator, "enqueue_replacement_arm", replacement)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        _quarantine_one_widened_arm(world)
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert _cohort_rows(root, "SELECT 1 FROM work_unit WHERE status = 'quarantined'"), (
        "fixture: nothing was quarantined")
    assert result.status == "complete" and result.pause_reason is None, (
        f"{budget}: {result.status} / {result.pause_reason} (CT-PIPE-12)")
    expected = REPLACEMENT_REFUSED if budget == "exhausted" else REPLACEMENT_INSERTED
    assert expected in decisions, f"{budget}: the replacement decisions were {decisions}, not {expected}"
    assert _cohort_rows(root, "SELECT work_id FROM work_unit WHERE status IN ('pending', 'leased')") == [], (
        "the run completed around an open unit")


# --- TC-PIPE-C13 ----------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_pipe_c13_each_enumerated_submission_is_offered_once(tmp_path, monkeypatch):
    import aeh.synth as synth

    offered: Counter = Counter()
    real = synth.SynthesisWorker.synthesize_submission

    def spy(self, run_id, submission_id, *args, **kwargs):
        offered[submission_id] += 1
        return real(self, run_id, submission_id, *args, **kwargs)

    monkeypatch.setattr(synth.SynthesisWorker, "synthesize_submission", spy)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        assert pipe_world.drive_composed(world).status == "complete"
        enumerated = Orchestrator(world.store).submissions(world.run_id)
    finally:
        world.store.close()
    assert len(enumerated) == 3, enumerated
    assert offered == Counter({s: 1 for s in enumerated}), f"offered {dict(offered)}, enumerated {enumerated}"


# --- TC-CONSOLE-C29 -------------------------------------------------------------------------


def _provenance(html: str) -> str:
    start = html.index("package version ")
    return html[start:html.index("<", start)].strip()


def _expected_line(version: str, config) -> str:
    summary = config.profile_summary()
    parts = [f"package version {version}", f"rubric version {version.rpartition('@')[2]}",
             f"backend profile {summary.backend_profile}",
             "panel " + ", ".join(ref.build_id for ref in summary.panel)]
    engine = getattr(summary, "decision_engine", None)
    if engine is not None:
        parts.append(f"decision engine {engine.provider} {engine.build_id}")
    return " · ".join(parts)


def test_tc_console_c29_each_run_renders_its_own_provenance(two_runs):
    store, (run_a, _ref_a, version_a), (run_b, _ref_b, version_b) = two_runs
    app = build_console(store=store)
    html_a = app.render(SCREENS["S12"], id=run_a).html
    html_b = app.render(SCREENS["S12"], id=run_b).html
    line_a, line_b = _provenance(html_a), _provenance(html_b)
    assert line_a != line_b
    assert line_a == _expected_line(version_a, orch_cfg("edge-local")), line_a
    assert line_b == _expected_line(version_b, _cloud_engine_config()), line_b
    assert f"decision engine openrouter-jev {JEV_BUILD}" in line_b and "decision engine" not in line_a
    for html in (html_a, html_b):
        for forbidden in (SENTINEL, "sk-or-", JEV_URL, "jev.example.invalid", JEV_CONFIDENCE, "97.31"):
            assert forbidden not in html, forbidden
