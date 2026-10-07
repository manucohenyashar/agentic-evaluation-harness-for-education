"""TS-97 (#391): the gap-fix delta's `Requires` pairs, each against the real provider module.

| Case | Pair | Assertion |
|---|---|---|
| TC-REQ-90 | M-PIPE → M-ORCH | over a full run M-PIPE uses only the declared composition surface of M-ORCH, drives an executor-bound orchestrator, and escalates with three-element keys only |
| TC-REQ-91 | M-PIPE → M-EXTRACT | a taxonomy error from extraction reaches the dispatch pass unconverted: the run pauses naming it and no extract unit loses an attempt |
| TC-REQ-92 | M-PIPE → M-JUDGE | the same for scoring; and `aggregate` receives `verdicts_for`'s very tuple (no re-sort, no filter) |
| TC-REQ-93 | M-PIPE → M-INTEG | the gate is built with a `StoreExtractionView`; verifying each cell twice (integrity_pre, aggregate) strikes nothing |
| TC-REQ-94 | M-PIPE → M-AGG | `aggregate` gets no store handle or transaction; `write_score`, `enqueue_escalation` and `mark_cell_phase` share the cell's one transaction |
| TC-REQ-95 | M-PIPE → M-GRADE | `compute_all` is called with the driven run and no other |
| TC-REQ-96 | M-PIPE → M-SYNTH | a submission with an unscored criterion gets no narrative, and the run still completes with no error reported for it |
| TC-REQ-100 | M-CONSOLE → M-CONF | the console composes its run configuration through `effective_config` → `environment_snapshot`; no `resolve_run_config` call in `console.py` is handed `os.environ` |
| TC-REQ-101 | M-PIPE → M-DET | deterministic scores are written by M-DET, never by M-PIPE, and every deterministic unit ends `done` with its score row |
| TC-REQ-102 | M-PIPE → M-CONF | `main` composes its configuration through `environment_snapshot` (spy) |

Disclosed:
- **TC-REQ-90** also names "calls `resume` with no arguments". `run_to_completion` calls
  `resume(run_id)` as its sanctioned closer (a no-op on a running run), so the no-argument form is
  not its usage. `fail` and `unit_status` are in the surface: a strike is recorded through
  M-ORCH's own door, which is the owner marking its unit, not M-PIPE. The exit-1 arm drives
  `main(["run", ...])` with `create_run` refusing (the store is real; the refusal is injected).
- **For the plan owner (TC-REQ-100/101/102):** the plan rows say "`os.environ` does not appear
  in `console.py`" and "`evaluate(...)` then `complete()`". Neither matches the design text this
  code implements (seam-3 knobs read `os.environ`; `evaluate_cohort` is the recorded door). The
  cases pin the clause's intent and flag the rows for re-wording rather than weakening silently.
- **TC-REQ-100 / 102.** `os.environ` does appear in `console.py` and `pipeline.py`, for seam-3
  knobs (`CONSOLE_*`, `HARNESS_PIPE_*`), which are not run configuration. The clause's point —
  the RUN configuration enters only through the snapshot — is what is asserted.
- **TC-REQ-101.** The plan row says M-PIPE calls `evaluate(...)` then `complete()` per unit.
  M-PIPE calls `DeterministicEvaluator.evaluate_cohort(run_id)` and M-ORCH's walk closes the
  units (the module docstring's recorded design). The owned-write half is asserted by the
  statement owner of every deterministic score insert.
"""

from __future__ import annotations

import ast
import dataclasses
import sqlite3
import sys
from pathlib import Path

import pytest

import aeh.integ as integ
import aeh.pipeline as pipeline
import aeh.store as store_mod
from aeh.grade import GradingService
from aeh.orch import Orchestrator
from aeh.prov import BuildChangedError, ProviderUnavailableError
from tests.support import pipe_world
from tests.support.source_tree import class_members, package_source, top_module

REPO = Path(__file__).resolve().parents[3]
S1_C1 = "I did not get to th"

#: M-ORCH's surface a composition layer is entitled to (CT-ORCH-22..26 and the base lifecycle).
COMPOSITION_SURFACE = {
    "__init__", "run_handle", "progress", "ready_cells",
    # #597 (NFR-PIPE-02): the aggregate hook reads the ready cells and their per-cell unit
    # figures from one door — the two run-wide GROUP BY reads it used to issue per pass are
    # folded into the ready read itself.
    "ready_cells_with_units", "cell_unit_counts", "cell_quarantined_counts",
    "mark_cell_phase", "enqueue_escalation", "enqueue_replacement_arm", "resume", "pause", "runs",
    "submissions", "tripped_breakers", "escalation_budget_state", "record_pause_reason",
    "has_queued_resume", "cohort_ref", "create_run", "start", "sweep_expired_leases",
    # A judge strike is recorded through M-ORCH's own door (the unit's owner marks it, never
    # M-PIPE); `unit_status` is the read that tells a struck-out extraction from an empty one.
    "fail", "unit_status",
    # #596 (design 1.9.1 §5.4 R22, CT-PIPE-06): synthesis runs after the last dispatch pass, so
    # M-PIPE takes the run's governed provider, persists its counters, and charges and checks
    # the frozen ceiling through M-ORCH's doors; still no SQL of its own (CT-PIPE-05).
    "governed_provider", "flush_metrics", "charge_post_dispatch", "post_dispatch_ceiling_reached",
}


def _world(root: Path, monkeypatch):
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    return world


def _rows(root: Path, sql: str, *params):
    with sqlite3.connect(root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite") as c:
        c.row_factory = sqlite3.Row
        return c.execute(sql, params).fetchall()


def _caller_modules() -> list[str]:
    f, out = sys._getframe(2), []
    while f is not None:
        out.append(top_module(f.f_globals.get("__name__", "")))
        f = f.f_back
    return out


# --- TC-REQ-90 ------------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_req_90_m_pipe_uses_only_the_composition_surface(tmp_path, monkeypatch):
    used: set[str] = set()
    keys: list[tuple] = []
    bound: list[bool] = []
    for name, member in class_members(Orchestrator):
        if name.startswith("_") and name != "__init__" or not callable(member):
            continue

        def spy(self, *args, _name=name, _real=member, **kwargs):
            if _caller_modules()[0] == "aeh.pipeline":
                used.add(_name)
                if _name == "enqueue_escalation":
                    keys.append(tuple(args[1]))
            result = _real(self, *args, **kwargs)
            if _name == "__init__" and _caller_modules()[0] == "aeh.pipeline":
                bound.append(getattr(self, "_executor", None) is not None)
            return result

        monkeypatch.setattr(Orchestrator, name, spy)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    inner = world.provider.complete
    struck: list[str] = []

    def complete(prompt, model_ref, params):  # one prompt always illegal: the strike path runs
        reply = inner(prompt, model_ref, params)
        key = repr(sorted(dict(prompt.fields).items()))
        if model_ref.role == "judge" and (not struck or key == struck[0]):
            struck[:1] = [key]
            return dataclasses.replace(reply, text="not a verdict")
        return reply

    world.provider.complete = complete
    try:
        assert pipe_world.drive_composed(world).status == "complete"
    finally:
        world.store.close()
    assert "fail" in used, "fixture: the strike path never ran"
    assert used and used <= COMPOSITION_SURFACE, f"M-PIPE used {sorted(used - COMPOSITION_SURFACE)}"
    assert bound and all(bound), "M-PIPE drove an orchestrator with no executor bound (CT-ORCH-22)"
    assert keys and all(len(k) == 3 for k in keys), f"escalation keys: {keys} (CT-ORCH-26)"


def test_tc_req_90_a_package_integrity_refusal_exits_1(tmp_path, monkeypatch, capsys):
    import aeh.conf as conf
    from aeh.pkg import PackageIntegrityError

    root = tmp_path / "w"
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)  # built, no run yet
    try:
        resolved = world.resolved if hasattr(world, "resolved") else None
        world.build_run()
        resolved = world.resolved
        with sqlite3.connect(root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite") as c:
            c.execute("DELETE FROM work_unit")
            c.execute("DELETE FROM run")
    finally:
        world.store.close()
    monkeypatch.setattr(conf, "resolve_run_config", lambda cfg, cohort: resolved)

    def refuse(self, *args, **kwargs):
        raise PackageIntegrityError("version v, criterion C1, band B9, run r: the package is not whole")

    monkeypatch.setattr(Orchestrator, "create_run", refuse)
    code = pipeline.main(["run", "--data-dir", str(root), "--cohort", pipe_world.PIPE_COHORT_ID,
                          "--package-version", world.version])
    err = capsys.readouterr().err
    assert code == 1, f"main returned {code} for a PackageIntegrityError (CT-ORCH-25: exit 1)"
    assert "PackageIntegrityError" in err, err


# --- TC-REQ-91 / TC-REQ-92 ------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("role", ["extractor", "judge"])
@pytest.mark.parametrize("error", [ProviderUnavailableError, BuildChangedError])
def test_tc_req_91_92_a_taxonomy_error_reaches_the_dispatch_pass(tmp_path, monkeypatch, role, error):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    inner = world.provider.complete

    def complete(prompt, model_ref, params):
        if model_ref.role == role:
            raise error("injected")
        return inner(prompt, model_ref, params)

    world.provider.complete = complete
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert result.status == "paused" and error.__name__ in (result.pause_reason or ""), result
    stage = "extract" if role == "extractor" else "score"
    assert _rows(root, "SELECT 1 FROM work_unit WHERE stage = ? AND (attempts > 0 OR status = "
                       "'quarantined')", stage) == [], f"the {error.__name__} consumed a strike"


@pytest.mark.integration
def test_tc_req_92_aggregate_gets_verdicts_for_tuple_unmodified(tmp_path, monkeypatch):
    handed: list[tuple] = []
    received: list[bool] = []
    real_for, real_agg = pipeline.verdicts_for, pipeline.aggregate

    def verdicts_for(*args, **kwargs):
        result = real_for(*args, **kwargs)
        handed.append(result)
        return result

    def aggregate(verdicts, *args, **kwargs):
        received.append(verdicts is handed[-1])
        return real_agg(verdicts, *args, **kwargs)

    monkeypatch.setattr(pipeline, "verdicts_for", verdicts_for)
    monkeypatch.setattr(pipeline, "aggregate", aggregate)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        assert pipe_world.drive_composed(world).status == "complete"
    finally:
        world.store.close()
    assert received and all(received), "aggregate received something other than verdicts_for's tuple"


# --- TC-REQ-93 ------------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_req_93_the_gate_reads_the_store_and_a_second_verify_strikes_nothing(tmp_path, monkeypatch):
    views: list[object] = []
    verifies: dict[tuple, list] = {}
    real_init, real_verify = integ.IntegrityGate.__init__, integ.IntegrityGate.verify

    def init(self, cohort, blobs, view, *args, **kwargs):
        views.append(view)
        return real_init(self, cohort, blobs, view, *args, **kwargs)

    def verify(self, run_id, submission_id, criterion_id):
        result = real_verify(self, run_id, submission_id, criterion_id)
        # The cell's attempts after this call (CT-INTEG-16 / RISK-45). Status may move: the
        # second call runs after the panel landed, so its inputs are not the first call's.
        verifies.setdefault((submission_id, criterion_id), []).append(sorted(
            (r["work_id"], r["attempts"]) for r in self_cohort[0].query(
                "SELECT work_id, attempts FROM work_unit WHERE run_id = :r AND "
                "submission_id = :s AND criterion_id = :c AND stage = 'extract'",
                r=run_id, s=submission_id, c=criterion_id)))
        return result

    monkeypatch.setattr(integ.IntegrityGate, "__init__", init)
    monkeypatch.setattr(integ.IntegrityGate, "verify", verify)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    self_cohort = [world.handle]
    try:
        assert pipe_world.drive_composed(world).status == "complete"
    finally:
        world.store.close()
    assert views and all(isinstance(v, integ.StoreExtractionView) for v in views), views
    assert verifies and min(len(v) for v in verifies.values()) >= 2, "fixture: a cell was verified once only"
    for cell, snapshots in verifies.items():
        assert snapshots[1] == snapshots[0], (
            f"the second verify of {cell} changed its extract units: {snapshots[0]} -> {snapshots[1]}")


# --- TC-REQ-94 ------------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_req_94_aggregate_is_pure_and_the_cell_writes_share_one_transaction(tmp_path, monkeypatch):
    impure: list[object] = []
    txs: dict[tuple, dict[str, int]] = {}
    real_agg, real_write = pipeline.aggregate, pipeline.write_score
    real_enq, real_mark = Orchestrator.enqueue_escalation, Orchestrator.mark_cell_phase

    def aggregate(*args, **kwargs):
        impure.extend(a for a in (*args, *kwargs.values())
                      if isinstance(a, store_mod.Tx) or hasattr(a, "transaction"))
        return real_agg(*args, **kwargs)

    def note(cell, name, tx):
        txs.setdefault(cell, {})[name] = id(tx)

    def write_score(tx, run_id, submission_id, score, signals):
        note((submission_id, str(score.criterion_id)), "write_score", tx)
        return real_write(tx, run_id, submission_id, score, signals)

    def enqueue(self, tx, key, *args, **kwargs):
        note((key[1], key[2]), "enqueue_escalation", tx)
        return real_enq(self, tx, key, *args, **kwargs)

    def mark(self, tx, run_id, submission_id, criterion_id, phase, *args, **kwargs):
        if phase == "aggregated":
            note((submission_id, criterion_id), "mark_cell_phase", tx)
        return real_mark(self, tx, run_id, submission_id, criterion_id, phase, *args, **kwargs)

    monkeypatch.setattr(pipeline, "aggregate", aggregate)
    monkeypatch.setattr(pipeline, "write_score", write_score)
    monkeypatch.setattr(Orchestrator, "enqueue_escalation", enqueue)
    monkeypatch.setattr(Orchestrator, "mark_cell_phase", mark)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        assert pipe_world.drive_composed(world).status == "complete"
    finally:
        world.store.close()
    assert not impure, f"aggregate was handed a store handle or transaction: {impure[:2]}"
    escalated = {cell: t for cell, t in txs.items() if "enqueue_escalation" in t}
    assert escalated, "fixture: no cell escalated"
    for cell, t in escalated.items():
        assert t["write_score"] == t["enqueue_escalation"] == t["mark_cell_phase"], (cell, t)


# --- TC-REQ-95 ------------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_req_95_grading_is_asked_for_the_driven_run_only(tmp_path, monkeypatch):
    runs: list[str] = []
    real = GradingService.compute_all
    monkeypatch.setattr(GradingService, "compute_all",
                        lambda self, run_id, *a, **k: runs.append(run_id) or real(self, run_id, *a, **k))
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        assert pipe_world.drive_composed(world).status == "complete"
    finally:
        world.store.close()
    assert runs and set(runs) == {world.run_id}, runs


# --- TC-REQ-96 ------------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_req_96_no_narrative_for_an_incomplete_submission_is_not_a_failure(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    inner = world.provider.complete

    def complete(prompt, model_ref, params):
        reply = inner(prompt, model_ref, params)
        fields = dict(prompt.fields)
        if (model_ref.role == "judge" and "criterion_id: C1" in str(fields.get("criterion"))
                and S1_C1 in str(fields.get("submission"))):
            return dataclasses.replace(reply, text="not a verdict")
        return reply

    world.provider.complete = complete
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    (s1,) = {r[0] for r in _rows(root, "SELECT submission_id FROM work_unit WHERE status = 'quarantined'")}
    assert result.status == "complete" and result.pause_reason is None, result.pause_reason
    synth = [d for s in result.stages if s.stage == "synthesize" for d in s.detail if d.startswith(s1)]
    assert synth and " 0 failures" in synth[0] and "Error" not in synth[0], synth


# --- TC-REQ-100 / TC-REQ-102 ----------------------------------------------------------------


def _resolve_calls_with_environ(source: str) -> list[int]:
    tree = ast.parse(source)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "resolve_run_config":
            if "os.environ" in ast.unparse(node):
                bad.append(node.lineno)
    return bad


def test_tc_req_100_the_console_composes_config_through_the_snapshot(monkeypatch):
    import aeh.conf as conf
    import aeh.console as console

    calls: list[object] = []
    real = conf.environment_snapshot
    monkeypatch.setattr(conf, "environment_snapshot", lambda *a, **k: calls.append(a) or real(*a, **k))
    monkeypatch.setenv("HARNESS_PROFILE", "edge-local")
    composed = conf.effective_config({})
    assert calls, "effective_config did not read the environment through environment_snapshot"
    assert composed.get("HARNESS_PROFILE") == "edge-local"
    assert _resolve_calls_with_environ(package_source(console)) == []


@pytest.mark.integration
def test_tc_req_100_the_console_start_door_resolves_through_the_snapshot(tmp_path, monkeypatch):
    """The console's own "start run" door, given no config, composes one through the snapshot and
    hands `resolve_run_config` that composed dict (never `os.environ` itself)."""
    import os

    import aeh.conf as conf
    from aeh.console import build_console

    snapshots: list[object] = []
    handed: list[object] = []
    real_snapshot, real_resolve = conf.environment_snapshot, conf.resolve_run_config

    def snapshot(*a, **k):
        result = real_snapshot(*a, **k)
        snapshots.append(result)
        return result

    def resolve(cfg, cohort):
        handed.append(cfg)
        raise conf.ConfigurationError("stop here: the composition is what is asserted")

    monkeypatch.setattr(conf, "environment_snapshot", snapshot)
    monkeypatch.setattr(conf, "resolve_run_config", resolve)
    root = tmp_path / "w"
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world.build_run()
    try:
        build_console(store=world.store).perform("start run", run_id=world.run_id)
    finally:
        world.store.close()
    assert snapshots, "the start door never read the environment through environment_snapshot"
    assert handed and handed[0] is not os.environ and isinstance(handed[0], dict), handed
    assert all(handed[0].get(k) == v for k, v in snapshots[-1].items()), (
        "resolve_run_config was not handed the snapshot's keys (CT-CONF-05)")


def test_tc_req_102_main_composes_config_through_the_snapshot(tmp_path, monkeypatch):
    import aeh.conf as conf

    calls: list[object] = []
    real = conf.environment_snapshot
    monkeypatch.setattr(conf, "environment_snapshot", lambda *a, **k: calls.append(a) or real(*a, **k))
    data = tmp_path / "d"
    for sub in ("packages", "cohorts", "blobs"):
        (data / sub).mkdir(parents=True)
    code = pipeline.main(["recover", "--data-dir", str(data)])
    assert code == 0
    assert calls, "main's recover path never read the environment through environment_snapshot"
    assert _resolve_calls_with_environ(package_source(pipeline)) == []


# --- TC-REQ-101 -----------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_req_101_deterministic_scores_are_m_dets_writes(tmp_path, monkeypatch):
    owners: list[str] = []
    real = store_mod.Tx.execute

    def execute(self, statement, **params):
        if str(statement).lstrip().upper().startswith("INSERT") and "criterion_score" in str(statement):
            chain = _caller_modules()
            owners.append(next((m for m in chain if m.startswith("aeh.") and m != "aeh.store"), ""))
        return real(self, statement, **params)

    monkeypatch.setattr(store_mod.Tx, "execute", execute)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        assert pipe_world.drive_composed(world).status == "complete"
    finally:
        world.store.close()
    assert "aeh.det" in owners, f"fixture: no deterministic score insert seen ({owners})"
    assert "aeh.pipeline" not in owners, owners
    undone = _rows(root, "SELECT w.work_id FROM work_unit w WHERE w.stage = 'deterministic' AND "
                         "(w.status != 'done' OR NOT EXISTS (SELECT 1 FROM criterion_score s WHERE "
                         "s.run_id = w.run_id AND s.submission_id = w.submission_id AND "
                         "s.criterion_id = w.criterion_id AND s.judge_count = 0))")
    assert undone == [], f"deterministic units without a done status and a judge_count-0 score: {undone}"


# --- TC-REQ-97 ------------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_req_97_s9_renders_the_services_order_verbatim(tmp_path, monkeypatch):
    from aeh.console import SCREENS, build_console

    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        assert pipe_world.drive_composed(world).status == "complete"
        app = build_console(store=world.store)
        shown = app.review_queue(world.run_id).queue.shown
        html = app.render(SCREENS["S9"], id=world.run_id).html
    finally:
        world.store.close()
    assert len(shown) >= 3, f"fixture: the queue shows {len(shown)} item(s)"
    starts, position = [], 0
    for item in shown:
        found = html.find(str(item.submission_id), position)
        assert found >= 0, (
            f"S9 does not render {item.submission_id}/{item.criterion_id} after the previous row: "
            "the console reordered M-REVIEW's queue (CT-REVIEW-04)")
        starts.append(found)
        position = found + 1
    for index, item in enumerate(shown):
        row = html[starts[index]:starts[index + 1] if index + 1 < len(starts) else len(html)]
        assert f"/ {item.criterion_id}" in row, (
            f"S9's row {index} is not {item.submission_id}/{item.criterion_id}: the console reordered "
            "the queue within a submission (CT-REVIEW-04)")


# --- TC-REQ-98 ------------------------------------------------------------------------------

#: S5's card for each optional setup step (the console declares the cards; M-SETUP the steps).
_OPTIONAL_CARD = {
    "rubric_readback": "Approve how the rubric was understood",
    "decomposability": "Confirm decomposability classifications",
    "grade_policy": "Declare the grade policy and boundaries",
}


def test_tc_req_98_setup_screens_follow_m_setups_steps(tmp_data_dir):
    import re

    from aeh.console import SCREENS, SETUP_STEP_SCREENS, build_console
    from tests.contract.setup._doubles import ingest_document, stage_chain

    chain = stage_chain(tmp_data_dir / "live")
    try:
        chain.doc = ingest_document(chain.store, kind="assessment")
        steps = chain.service.steps().steps
        app = build_console(store=chain.store)
        blocking = [s.step_id for s in steps if s.blocking]
        optional = [s.step_id for s in steps if not s.blocking]
        assert app.blocking_screens() == tuple(SETUP_STEP_SCREENS[s] for s in blocking), (
            app.blocking_screens(), blocking)
        for screen in app.blocking_screens():
            html = app.render(SCREENS[screen]).html
            assert "blocks run start" in html, f"{screen} does not say it blocks the run"
            assert not re.search(r"skip", html, re.IGNORECASE), f"blocking {screen} offers a skip"
        s5 = app.render(SCREENS["S5"]).html
    finally:
        chain.store.close()
    assert set(optional) <= set(_OPTIONAL_CARD), f"setup has an optional step S5 has no card for: {optional}"
    positions = [s5.find(_OPTIONAL_CARD[s]) for s in optional]
    assert all(p >= 0 for p in positions) and positions == sorted(positions), (
        f"S5 does not render setup's optional steps {optional} in order: {positions}")


# --- TC-REQ-99 ------------------------------------------------------------------------------


def _start_paused_run(tmp_path, monkeypatch):
    """Start a run through the console's "start run" door with every model call down; return
    the worker's thread names and the S7 page once the worker has stopped."""
    import threading

    from aeh.console import SCREENS, build_console
    from tests.support.conf_builders import edge_cfg

    drivers: list[str] = []
    real_run = pipeline.run_to_completion

    def run_to_completion(*args, **kwargs):
        drivers.append(threading.current_thread().name)
        return real_run(*args, **kwargs)

    class Down:
        def complete(self, *a, **k):
            raise ProviderUnavailableError("injected outage")

    monkeypatch.setattr(pipeline, "run_to_completion", run_to_completion)
    monkeypatch.setattr(pipeline, "_provider_for", lambda config: Down())
    root = tmp_path / "w"
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world.build_run()
    try:
        app = build_console(store=world.store)
        app.perform("start run", run_id=world.run_id, config=edge_cfg(panel=world.panel_refs))
        thread = app._run_threads[world.run_id]
        thread.join(timeout=120)
        assert not thread.is_alive(), "the worker never finished"
        status = world.handle.query("SELECT status, pause_reason FROM run")[0]
        s7 = app.render(SCREENS["S7"], id=world.run_id).html
    finally:
        world.store.close()
    return drivers, tuple(status), s7


@pytest.mark.integration
def test_tc_req_99_start_run_drives_on_a_server_thread_and_s7_shows_paused(tmp_path, monkeypatch):
    import threading

    drivers, status, s7 = _start_paused_run(tmp_path, monkeypatch)
    assert drivers and threading.main_thread().name not in drivers, drivers
    assert status[0] == "paused" and "ProviderUnavailableError" in status[1], status
    assert "status: paused" in s7, "S7 does not show the paused status"


@pytest.mark.integration
def test_tc_req_99_s7_shows_why_the_run_paused(tmp_path, monkeypatch):
    """Written ahead; green since #602. `console.py` never read `pause_reason`, so the
    operator saw a paused run with no reason (CT-PIPE-04's M-CONSOLE consumer)."""
    _drivers, status, s7 = _start_paused_run(tmp_path, monkeypatch)
    assert status[0] == "paused"
    assert "ProviderUnavailableError" in s7, "S7 shows no reason for the pause (CT-PIPE-04)"


# --- TC-REQ-103 -----------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_req_103_review_reads_the_runs_own_package_version(tmp_data_dir):
    from aeh import review
    from aeh.pkg import PackageCatalog
    from aeh.store import open_store
    from tests.support.grade_vocabulary import write_criterion_scores
    from tests.support.orch_run import ORCH_COHORT_ID, seed_run

    store = open_store(tmp_data_dir)
    try:
        _o, run_id, v1 = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        write_criterion_scores(store.cohort(ORCH_COHORT_ID), [("S1", "C1", "B1", 1.0, "provisional")])
        package_id = v1.rpartition("@")[0]
        catalog = PackageCatalog(store.package(package_id), package_id=package_id)
        v2 = catalog.create_version(v1)
        catalog.update_criterion_field(v2, "C1", "scoring_model", "holistic")
        models = {v: {str(r["criterion_id"]): str(r["scoring_model"]) for r in catalog.criteria(v)}
                  for v in (v1, v2)}
    finally:
        store.close()
    assert models == {v1: {"C1": "atomic"}, v2: {"C1": "holistic"}}, f"fixture: {models}"
    service = review.open_review(tmp_data_dir, run_id=run_id)
    try:
        rows = {str(r.criterion_id): r for r in service._rows}
    finally:
        service.close()
    assert rows["C1"].scoring_model == "atomic", (
        f"the review row for a run on {v1} reads scoring_model {rows['C1'].scoring_model!r}: "
        "not the run's own version")


@pytest.mark.integration
def test_tc_req_103_a_run_on_the_older_of_two_versions_is_not_read_as_the_first(tmp_data_dir):
    """The mirror: the run is on v2 (the newer), so a reader that always takes the FIRST version
    fails here where the v1 case above would not catch it."""
    from aeh import review
    from aeh.pkg import PackageCatalog
    from aeh.store import open_store
    from tests.support.grade_vocabulary import write_criterion_scores
    from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_run

    store = open_store(tmp_data_dir)
    try:
        orch, _run1, v1 = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        package_id = v1.rpartition("@")[0]
        catalog = PackageCatalog(store.package(package_id), package_id=package_id)
        v2 = catalog.create_version(v1)
        catalog.update_criterion_field(v2, "C1", "scoring_model", "holistic")
        catalog.publish(v2, approved_by="the package owner") if hasattr(catalog, "publish") else None
        run2 = orch.create_run(ORCH_COHORT_ID, v2, orch_cfg())
        orch.enumerate_units(run2)
        orch.start(run2)
        write_criterion_scores(store.cohort(ORCH_COHORT_ID), [("S1", "C1", "B1", 1.0, "provisional")])
    finally:
        store.close()
    service = review.open_review(tmp_data_dir, run_id=run2)
    try:
        rows = {str(r.criterion_id): r for r in service._rows}
    finally:
        service.close()
    assert rows["C1"].scoring_model == "holistic", (
        f"the review row for a run on {v2} reads {rows['C1'].scoring_model!r}, not v2's holistic")
