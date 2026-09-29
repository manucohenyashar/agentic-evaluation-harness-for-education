"""TS-139 (#550): design 1.9 §4's new `Requires` rows, one pairwise case each against the real provider.

| Case | Pair | Assertion |
|---|---|---|
| TC-REQ-119 | M-PIPE → M-PKG | escalation receives exactly the baseline stored under the run's key; one stored under another `backend_profile` is not used |
| TC-REQ-120 | M-PIPE → M-STATS | a 3-label lineage hands M-AGG a `NoValidationData`, and M-AGG applies the no-data weight (its reason), never the zero path |
| TC-REQ-121 | M-REVIEW → M-STATS | every review row's eighth input equals `stored_disagreement_rates` for its criterion |
| TC-REQ-122 | M-PIPE → M-ORCH | synthesis is offered exactly `submissions(run_id)`; a replacement arm is budgeted: over budget the budget report defers its cell |
| TC-REQ-123 | M-STATS → M-REVIEW | labels M-REVIEW wrote from two backends give two figures of n = 8, never one of 16 |
| TC-REQ-124 | M-REVIEW → M-ORCH | `open_review` serves the cohort `run_handle` reports for the run |
| TC-REQ-125 | M-CONSOLE → M-CONF | the console's engine line equals the run config's `ProfileSummary` engine; engine off, no line |
| TC-REQ-126 | M-STATS → M-PKG | `promote`'s verdict reads back through `validation_for` under the run's key |
| TC-REQ-127 | declaring modules → M-STORE | in both import orders, every name a module declares resolves through the shared registry to that module's own SQL |

Disclosed, TC-REQ-122: "a replacement arm's budget use shows in the budget report" is asserted as
the report's `provisional_pairs` naming the replaced cell once the run is over budget. The
report's escalated-cells count cannot move for a replacement (the cell is already escalated;
see TS-138's TC-ORCH-C33 note).
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.pkg  # noqa: F401,E401
import aeh.review, aeh.synth  # noqa: F401,E401
from aeh import pkg, review, stats
from aeh.console import SCREENS, build_console
from aeh.orch import ESCALATION_BUDGET_ENV, REPLACEMENT_INSERTED, Orchestrator
from aeh.store import open_store
from tests.integration.console.test_ts135_grade_provenance import (  # noqa: F401 (the fixture)
    _cloud_engine_config, two_runs)
from tests.integration.orch.test_ts133_closeout_orch import _arms, _quarantine, _widened_cell
from tests.integration.pipe.test_ts134_closeout_pipe import _EscalationSpy, _key, _seed_baseline, _world
from tests.integration.review.test_ts130_override_figures import (
    _label, _ranked_rows, _rows_by_criterion, _seed_rate_labels)
from tests.integration.stats import test_ts131_noninferiority_persistence as ts131
from tests.support import broken_stats_fixtures as broken
from tests.support import pipe_world
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_cohort, seed_package

REPO = Path(__file__).resolve().parents[3]


# --- TC-REQ-119 -----------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("backend", ["run's", "other"])
def test_tc_req_119_escalation_reads_the_baseline_under_the_runs_key(tmp_path, monkeypatch, backend):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        key = _key(world)
        if backend == "other":
            key = dataclasses.replace(key, backend_profile="cloud-hosted")
            assert key.backend_profile != _key(world).backend_profile
        _seed_baseline(root, key, "C1")
        spy = _EscalationSpy(monkeypatch)
        pipe_world.drive_composed(world)
    finally:
        world.store.close()
    c1 = spy.of("C1")
    assert c1, "no C1 decision"
    for call in c1:
        if backend == "run's":
            assert (call.baseline["mean"], call.baseline["std"]) == (2.0, 0.5), call.baseline
        else:
            assert isinstance(call.baseline, pkg.NoValidationData), (
                f"a baseline stored under another backend reached the run: {call.baseline!r}")


# --- TC-REQ-120 -----------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_req_120_a_short_lineage_is_no_data_and_weighted_as_such(tmp_path, monkeypatch):
    monkeypatch.delenv("HARNESS_REVIEW_OVERRIDE_MIN_N", raising=False)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        for i in range(3):
            review.record_label(data_dir=root, label=broken.Label(
                label_id=f"L-C1-{i}", criterion_id="C1", band=2, teacher_band=3 if i == 0 else 2,
                origin="override" if i == 0 else "blind_sample"))
        spy = _EscalationSpy(monkeypatch)
        pipe_world.drive_composed(world)
    finally:
        world.store.close()
    for call in spy.of("C1"):
        assert isinstance(call.history, pkg.NoValidationData), call.history
        assert "criterion override history: no data" in call.decision.reasons, call.decision.reasons
        assert not any("override_rate=" in r for r in call.decision.reasons), (
            "three labels were read as a rate (the zero path, CT-STATS-09)")


# --- TC-REQ-121 -----------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_req_121_the_eighth_input_is_m_stats_figure(tmp_data_dir, monkeypatch):
    monkeypatch.delenv("HARNESS_REVIEW_OVERRIDE_MIN_N", raising=False)
    run_id = _ranked_rows(tmp_data_dir)
    _seed_rate_labels(tmp_data_dir)
    rows = _rows_by_criterion(tmp_data_dir, run_id)
    store = open_store(tmp_data_dir)
    try:
        version = Orchestrator(store).run_handle(run_id).package_version_id
        stored = stats.stored_disagreement_rates(store, version)
    finally:
        store.close()
    assert set(rows) == {"C-HI", "C-LO", "C-NONE"} <= set(stored), (set(rows), set(stored))
    for criterion, row in rows.items():
        figure = stored[criterion]
        expected = None if isinstance(figure, pkg.NoValidationData) else figure.rate
        assert row.historical_override_rate == expected, (criterion, row.historical_override_rate, figure)


# --- TC-REQ-122 -----------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_req_122_a_synthesis_is_offered_exactly_the_runs_submissions(tmp_path, monkeypatch):
    import aeh.synth as synth

    offered: Counter = Counter()
    real = synth.SynthesisWorker.synthesize_submission
    monkeypatch.setattr(synth.SynthesisWorker, "synthesize_submission",
                        lambda self, run_id, sid, *a, **k: offered.update([sid]) or real(self, run_id, sid, *a, **k))
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        pipe_world.drive_composed(world)
        expected = Orchestrator(world.store).submissions(world.run_id)
    finally:
        world.store.close()
    assert sorted(offered.elements()) == sorted(expected), (dict(offered), expected)


def test_tc_req_122_b_a_replacement_arm_is_deferred_by_the_budget_like_any_escalation(
        tmp_data_dir, monkeypatch):
    store = open_store(tmp_data_dir)
    try:
        orch, run_id, cohort = _widened_cell(store)
        _quarantine(tmp_data_dir, run_id, _arms(cohort, run_id)[-1])
        with cohort.transaction() as tx:
            assert orch.enqueue_replacement_arm(tx, (run_id, "S1", "C1")).decision == REPLACEMENT_INSERTED
        within = orch.escalation_budget_state(run_id)
        monkeypatch.setattr(Orchestrator, "_escalation_rate", lambda self, ex, run: (10, 9, 0.9))
        monkeypatch.setenv(ESCALATION_BUDGET_ENV, "0.5")
        over = orch.escalation_budget_state(run_id)
    finally:
        store.close()
    assert "S1/C1" not in within.provisional_pairs, within
    assert "S1/C1" in over.provisional_pairs, (
        f"over budget, the report does not defer the replaced cell: {over.provisional_pairs}")


# --- TC-REQ-123 -----------------------------------------------------------------------------


def test_tc_req_123_two_backends_give_two_figures(tmp_data_dir):
    for backend in ("edge-local", "cloud-hosted"):
        for i in range(8):
            review.record_label(data_dir=tmp_data_dir, label=dataclasses.replace(
                _label(i, "C1", system=2 if i % 3 else 1, teacher=2), label_id=f"L-{backend}-{i}",
                backend_profile=backend))
    service = stats.open_stats(data_dir=tmp_data_dir)
    figures = {b: service.agreement(criterion_id="C1", backend_profile=b)
               for b in ("edge-local", "cloud-hosted")}
    for backend, figure in figures.items():
        assert getattr(figure, "n", None) == 8, f"{backend}: {figure!r} (CT-REVIEW-25: n = 8, never 16)"


# --- TC-REQ-124 -----------------------------------------------------------------------------


def test_tc_req_124_open_review_follows_the_run_registry(tmp_data_dir, monkeypatch):
    store = open_store(tmp_data_dir)
    try:
        for cohort, sub in (("c-ts139-a", "SA1"), ("c-ts139-b", "SB1")):
            seed_cohort(store, [sub], cohort_id=cohort)
            version = seed_package(store, [{"criterion_id": "C1", "kind": "open",
                                            "scoring_model": "atomic"}], package_id=f"pkg-{cohort}")
            Orchestrator(store).create_run(cohort, version, orch_cfg("edge-local"), run_id="run-R")
            write_criterion_scores(store.cohort(cohort), [(sub, "C1", "B1", 1.0, "provisional")])
    finally:
        store.close()
    real = Orchestrator.run_handle
    served = {}
    for reported in ("c-ts139-a", "c-ts139-b"):
        def run_handle(self, run_id, _cohort=reported):
            handle = real(self, run_id)
            return dataclasses.replace(handle, cohort_id=_cohort, cohort=self._store.cohort(_cohort))

        monkeypatch.setattr(Orchestrator, "run_handle", run_handle)
        service = review.open_review(tmp_data_dir, run_id="run-R")
        try:
            served[reported] = {str(row.submission_id) for row in service._rows}
        finally:
            service.close()
    assert served == {"c-ts139-a": {"SA1"}, "c-ts139-b": {"SB1"}}, served


# --- TC-REQ-125 -----------------------------------------------------------------------------


def test_tc_req_125_the_engine_line_is_the_profile_summarys(two_runs):
    store, (run_a, _ra, _va), (run_b, _rb, _vb) = two_runs
    app = build_console(store=store)
    engine = _cloud_engine_config().profile_summary().decision_engine
    html_b = app.render(SCREENS["S12"], id=run_b).html
    assert f"decision engine {engine.provider} {engine.build_id}" in html_b, (engine, html_b[:300])
    assert orch_cfg("edge-local").profile_summary().decision_engine is None
    assert "decision engine" not in app.render(SCREENS["S12"], id=run_a).html


# --- TC-REQ-126 -----------------------------------------------------------------------------


def test_tc_req_126_promotes_verdict_reads_back_through_validation_for(tmp_data_dir, monkeypatch):
    run_id, version = ts131._draft(tmp_data_dir)
    ts131._administration(tmp_data_dir, run_id, engine_on=True)
    monkeypatch.setattr(stats, "agreement_by_engine", lambda labels, partition_of, **k: {
        "decision": stats.EngineAgreement("decision", 60, 0.70, False),
        "llm_engine_off": stats.EngineAgreement("llm_engine_off", 60, 0.74, False)})
    stats.open_stats(data_dir=tmp_data_dir).promote(ORCH_COHORT_ID, package_version=version)
    store = open_store(tmp_data_dir)
    try:
        key = Orchestrator(store).run_handle(run_id)
        package_id = version.rpartition("@")[0]
        record = pkg.PackageCatalog(store.package(package_id), package_id=package_id).validation_for(
            version, "", key.backend_profile, key.panel_build_ref, "", criterion_id="C1")
    finally:
        store.close()
    assert not isinstance(record, pkg.NoValidationData), (
        "promote's verdict is not readable under the run's key: it was filed under another "
        "backend_profile / panel_build_ref (#454)")
    assert record["decision_engine_noninferior"] == "true", record


# --- TC-REQ-127 -----------------------------------------------------------------------------

_RESOLVE = r"""
import importlib, json, pkgutil, sys
import aeh
from aeh.store import STATEMENTS, Statement
mods = sorted(m.name for m in pkgutil.iter_modules(aeh.__path__))
if sys.argv[1] == "reverse":
    mods = mods[::-1]
for m in mods:
    importlib.import_module("aeh." + m)
checked, wrong = 0, []
for m in mods:
    for attr, registry in vars(sys.modules["aeh." + m]).items():
        if not attr.endswith("STATEMENTS") or not isinstance(registry, dict) or registry is STATEMENTS:
            continue
        for name, own in registry.items():
            if isinstance(own, Statement) and name in STATEMENTS:
                checked += 1
                if str(STATEMENTS[name]) != str(own):
                    wrong.append(f"aeh.{m}.{attr}[{name!r}]")
print(json.dumps({"checked": checked, "wrong": sorted(set(wrong))}))
"""


@pytest.mark.integration
@pytest.mark.parametrize("order", ["alphabetical", "reverse"])
def test_tc_req_127_every_declared_name_resolves_to_its_own_sql(order):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO / "src"), str(REPO)])}
    done = subprocess.run([sys.executable, "-c", _RESOLVE, order], capture_output=True, text=True,
                          env=env, cwd=str(REPO), timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["checked"] > 0, "fixture: no module's names reach the shared registry"
    assert out["wrong"] == [], (
        f"{order} import: these names resolve through M-STORE to SQL other than their module's "
        f"own: {out['wrong']} (CT-STORE-19)")
