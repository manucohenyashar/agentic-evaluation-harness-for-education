"""TS-93 (#387): the CS-PIPE clause suite, TC-PIPE-C01..C07 (gap-fix test plan §6.11.1).

| Case | Clause | Assertion (breaks if the clause is broken) |
|---|---|---|
| TC-PIPE-C01 | CT-PIPE-01 | `run_to_completion(store, run_id, *, provider, run_config, ...)`, `recover(store, *, clock=None)` and `main(argv=None)` keep their names and kinds; `python -m aeh --help` exits 0 |
| TC-PIPE-C02 | CT-PIPE-02 | after `complete` with one cell's every arm quarantined: each admitted judged pair has one score row xor a quarantined unit; every submission a current grade |
| TC-PIPE-C03 | CT-PIPE-03 | re-entering `run_to_completion` on the complete run changes no row in the cohort file and returns `complete` |
| TC-PIPE-C04 | CT-PIPE-04 | a provider outage and a build change each pause the run naming the class, with no unit quarantined by it |
| TC-PIPE-C05 | CT-PIPE-05 | rung 0: no SQL in `aeh/pipeline.py` and no `aeh.pipeline` census site; rung 3: no statement executed over a full run has `aeh.pipeline` as its innermost `aeh` frame |
| TC-PIPE-C06 | CT-PIPE-06 | rung 0: `aeh/pipeline.py` calls no `.complete`/`.decide` and imports no HTTP client; rung 3: every model call's nearest caller is a stage worker (`aeh.extract` / `aeh.judge` / `aeh.synth`) |
| TC-PIPE-C07 | CT-PIPE-07 (non-promise) | the ready-cell order fixed, reversed and shuffled (seed 7) give equal score, grade and narrative tables and the same review queue order |

Disclosed:
- **C01.** The design lists `run_to_completion(store, run_id, *, provider, run_config)`; the
  shipped function has further keyword-only parameters (extractor, synthesizer, ...), all
  defaulted. The case pins the design's names and kinds and that every addition is keyword-only
  with a default (additive, per the compatibility rule).
- **C02.** The plan says "xor". With FR-PIPE-05's two-verdict fallback a cell with ONE quarantined
  arm legitimately holds both a score and a quarantined unit, so the case quarantines every arm
  of one cell, where xor is what the clause means.
- **C06.** `aeh/pipeline.py` does import provider classes: the CLI's `_provider_for` constructs
  the provider from configuration (FR-PIPE-08). The rung-0 check is therefore that it CALLS no
  model surface; construction is not a call.
- **C07.** M-CONSOLE's S9 rows are not compared (the page carries render-time text); the review
  queue order is.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import random
import sqlite3
import subprocess
import sys
import traceback
from pathlib import Path

import pytest

import aeh.pipeline as pipeline
import aeh.store as store_mod
from aeh.orch import Orchestrator
from aeh.prov import BuildChangedError, ProviderUnavailableError
from tests.support import pipe_world

REPO = Path(__file__).resolve().parents[3]
S1_C1 = "I did not get to th"


def _world(root: Path, monkeypatch):
    monkeypatch.setenv("HARNESS_PIPE_MAX_PASSES", "300")
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    return world


def _cohort(root: Path) -> Path:
    return root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite"


def _rows(root: Path, sql: str, *params):
    with sqlite3.connect(_cohort(root)) as c:
        c.row_factory = sqlite3.Row
        return c.execute(sql, params).fetchall()


# --- TC-PIPE-C01 ----------------------------------------------------------------------------


def test_tc_pipe_c01_the_entry_points_keep_their_surface():
    run = inspect.signature(pipeline.run_to_completion).parameters
    assert list(run)[:4] == ["store", "run_id", "provider", "run_config"], list(run)
    assert [run[n].kind for n in ("store", "run_id")] == [inspect.Parameter.POSITIONAL_OR_KEYWORD] * 2
    assert all(run[n].kind is inspect.Parameter.KEYWORD_ONLY for n in ("provider", "run_config"))
    for name, p in list(run.items())[4:]:
        assert p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is not inspect.Parameter.empty, (
            f"run_to_completion's {name} is not an additive keyword-only default")
    rec = inspect.signature(pipeline.recover).parameters
    assert list(rec) == ["store", "clock"] and rec["clock"].kind is inspect.Parameter.KEYWORD_ONLY
    assert rec["clock"].default is None
    main = inspect.signature(pipeline.main).parameters
    assert list(main) == ["argv"] and main["argv"].default is None
    done = subprocess.run([sys.executable, "-m", "aeh", "--help"], capture_output=True, text=True,
                          cwd=str(REPO), timeout=120,
                          env={**__import__("os").environ, "PYTHONPATH": f"{REPO / 'src'};{REPO}"})
    assert done.returncode == 0, done.stderr[-1000:]


# --- TC-PIPE-C02 ----------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_pipe_c02_every_pair_is_scored_xor_quarantined(tmp_path, monkeypatch):
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
        assert pipe_world.drive_composed(world).status == "complete"
        submissions = Orchestrator(world.store).submissions(world.run_id)
    finally:
        world.store.close()
    pairs = _rows(root, "SELECT DISTINCT submission_id, criterion_id FROM work_unit WHERE run_id = ? "
                        "AND stage IN ('extract', 'score')", world.run_id)
    assert _rows(root, "SELECT 1 FROM work_unit WHERE run_id = ? AND status = 'quarantined'", world.run_id)
    for sid, cid in pairs:
        scores = len(_rows(root, "SELECT 1 FROM criterion_score WHERE run_id = ? AND submission_id = ? "
                                 "AND criterion_id = ?", world.run_id, sid, cid))
        quarantined = bool(_rows(root, "SELECT 1 FROM work_unit WHERE run_id = ? AND submission_id = ? "
                                       "AND criterion_id = ? AND status = 'quarantined'", world.run_id, sid, cid))
        assert (scores == 1) != quarantined and scores <= 1, (sid, cid, scores, quarantined)
    graded = {r[0] for r in _rows(root, "SELECT submission_id FROM submission_grade WHERE run_id = ? "
                                        "AND is_current = 1", world.run_id)}
    assert graded == set(submissions), (graded, submissions)


# --- TC-PIPE-C03 ----------------------------------------------------------------------------


def _dump(path: Path) -> dict:
    with sqlite3.connect(path) as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {t: sorted(map(repr, c.execute(f"SELECT * FROM {t}").fetchall())) for t in tables}


@pytest.mark.integration
def test_tc_pipe_c03_re_entry_on_a_complete_run_writes_nothing(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        first = pipe_world.drive_composed(world)
        assert first.status == "complete"
        before = _dump(_cohort(root))
        again = pipe_world.drive_composed(world)
        after = _dump(_cohort(root))
    finally:
        world.store.close()
    assert again.status == first.status
    changed = sorted(t for t in set(before) | set(after) if before.get(t) != after.get(t))
    assert not changed, f"re-entry changed rows in {changed} (CT-PIPE-03)"


# --- TC-PIPE-C04 ----------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("error", [ProviderUnavailableError, BuildChangedError])
def test_tc_pipe_c04_an_outage_pauses_and_quarantines_nothing(tmp_path, monkeypatch, error):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    inner = world.provider.complete

    def complete(prompt, model_ref, params):
        if model_ref.role == "judge":
            raise error("injected")
        return inner(prompt, model_ref, params)

    world.provider.complete = complete
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert result.status == "paused" and error.__name__ in (result.pause_reason or ""), (
        result.status, result.pause_reason)
    assert _rows(root, "SELECT 1 FROM work_unit WHERE status = 'quarantined'") == []
    assert _rows(root, "SELECT 1 FROM work_unit WHERE stage = 'score' AND attempts > 0") == [], (
        "the outage consumed strikes")


# --- TC-PIPE-C05 ----------------------------------------------------------------------------


def test_tc_pipe_c05_rung_0_no_sql_in_the_composition_layer():
    source = (REPO / "src" / "aeh" / "pipeline.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("execute", "executemany", "executescript")]
    assert not calls, f"aeh/pipeline.py executes SQL: {calls}"
    imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imports |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "sqlite3" not in imports, imports
    statements = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call)
                  and getattr(n.func, "id", getattr(n.func, "attr", None)) == "Statement"]
    assert not statements, f"aeh/pipeline.py builds a Statement at lines {statements}"
    import re as _re
    literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and _re.match(r"\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|REPLACE)\s", n.value, _re.IGNORECASE)]
    assert not literals, literals
    from tests.artifact.test_store_query_surface import KNOWN_EXECUTE_SITES
    assert not [s for s in KNOWN_EXECUTE_SITES if s.startswith("aeh.pipeline:")]


def _innermost_aeh(stack) -> str | None:
    for frame in reversed(stack):
        module = frame.f_globals.get("__name__", "") if hasattr(frame, "f_globals") else ""
        if module.startswith("aeh.") and module != "aeh.store":
            return module
    return None


@pytest.mark.integration
def test_tc_pipe_c05_rung_3_every_statement_is_an_owning_modules(tmp_path, monkeypatch):
    owners: list[str | None] = []
    real_execute = store_mod.Tx.execute
    real_query = store_mod.SqliteTierHandle.query

    def frames():
        f, out = sys._getframe(2), []
        while f is not None:
            out.append(f)
            f = f.f_back
        return list(reversed(out))

    def execute(self, statement, **params):
        owners.append(_innermost_aeh(frames()))
        return real_execute(self, statement, **params)

    def query(self, statement, **params):
        owners.append(_innermost_aeh(frames()))
        return real_query(self, statement, **params)

    monkeypatch.setattr(store_mod.Tx, "execute", execute)
    monkeypatch.setattr(store_mod.SqliteTierHandle, "query", query)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        assert pipe_world.drive_composed(world).status == "complete"
    finally:
        world.store.close()
    assert len(owners) > 50, f"fixture: only {len(owners)} statements were seen"
    assert "aeh.pipeline" not in owners, "a statement's innermost aeh frame is aeh.pipeline (CT-PIPE-05)"


# --- TC-PIPE-C06 ----------------------------------------------------------------------------


def test_tc_pipe_c06_rung_0_the_composition_layer_calls_no_model():
    tree = ast.parse((REPO / "src" / "aeh" / "pipeline.py").read_text(encoding="utf-8"))
    model_calls = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute) and n.func.attr in ("complete", "decide")]
    assert not model_calls, f"aeh/pipeline.py calls a model surface at lines {model_calls}"
    modules = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    modules |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not modules & {"requests", "httpx", "urllib3", "http", "openai", "anthropic", "aiohttp"}, modules


@pytest.mark.integration
def test_tc_pipe_c06_rung_3_every_model_call_comes_from_a_stage_worker(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    inner = world.provider.complete
    callers: list[str | None] = []

    def complete(prompt, model_ref, params):
        f, chain = sys._getframe(1), []
        while f is not None:
            chain.append(f.f_globals.get("__name__", ""))
            f = f.f_back
        callers.append(next((m for m in chain if m.startswith("aeh.") and m not in ("aeh.orch", "aeh.prov")),
                            None))
        return inner(prompt, model_ref, params)

    world.provider.complete = complete
    try:
        assert pipe_world.drive_composed(world).status == "complete"
    finally:
        world.store.close()
    assert callers, "fixture: no model call was made"
    assert set(callers) <= {"aeh.extract", "aeh.judge", "aeh.synth"}, (
        f"model calls made from {sorted(set(map(str, callers)))} (CT-PIPE-06)")


@pytest.mark.integration
@pytest.mark.writtenahead
def test_tc_pipe_c06_rung_3_every_model_call_passes_the_governor(tmp_path, monkeypatch):
    """Written ahead, owned by no issue yet: `_synthesize` hands `SynthesisWorker` the raw provider,
    so synthesis calls bypass `GovernedProvider` (no accrual, no ceiling) — ADR-14 puts EVERY call
    through a worker holding the governed provider (CT-PIPE-06)."""
    from collections import Counter

    import aeh.orch as orch

    governed: Counter = Counter()
    real_governed = orch.GovernedProvider.complete

    def counted(self, payload, model_ref=None, params=None):
        governed[getattr(model_ref, "role", "?")] += 1
        return real_governed(self, payload, model_ref, params)

    monkeypatch.setattr(orch.GovernedProvider, "complete", counted)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    raw: Counter = Counter()
    inner = world.provider.complete
    world.provider.complete = lambda prompt, ref, params: raw.update([ref.role]) or inner(prompt, ref, params)
    try:
        assert pipe_world.drive_composed(world).status == "complete"
    finally:
        world.store.close()
    assert raw and governed == raw, f"calls at the provider {dict(raw)} vs through the governor {dict(governed)}"


# --- TC-PIPE-C07 ----------------------------------------------------------------------------


def _outcome(root: Path, run_id: str, data_dir: Path) -> dict:
    from aeh import review

    out = {
        "scores": sorted(map(tuple, _rows(root, "SELECT submission_id, criterion_id, band, points, "
                                               "judge_count, state FROM criterion_score WHERE run_id = ?", run_id))),
        "grades": sorted(map(tuple, _rows(root, "SELECT submission_id, grade, total, state FROM "
                                               "submission_grade WHERE run_id = ? AND is_current = 1", run_id))),
        "narratives": sorted(map(tuple, _rows(root, "SELECT submission_id, level, question_id, text "
                                                   "FROM narrative"))),
    }
    service = review.open_review(data_dir, run_id=run_id)
    try:
        queue = service.build_queue(run_id=run_id, budget_minutes=600)
        out["queue"] = [(str(getattr(e, "submission_id", "")), str(getattr(e, "criterion_id", "")))
                        for e in queue.shown]
    finally:
        service.close()
    return out


@pytest.mark.integration
def test_tc_pipe_c07_ready_cell_order_changes_no_outcome(tmp_path, monkeypatch):
    real = Orchestrator.ready_cells
    outcomes = {}
    for order in ("fixed", "reversed", "shuffled"):
        rng = random.Random(7)

        def ready_cells(self, run_id, hook, _order=order, _rng=rng):
            cells = list(real(self, run_id, hook))
            if _order == "reversed":
                cells.reverse()
            elif _order == "shuffled":
                _rng.shuffle(cells)
            return tuple(cells)

        with monkeypatch.context() as m:
            m.setattr(Orchestrator, "ready_cells", ready_cells)
            root = tmp_path / order
            world = _world(root, m)
            try:
                assert pipe_world.drive_composed(world).status == "complete"
            finally:
                world.store.close()
        outcomes[order] = _outcome(root, world.run_id, root)
    assert outcomes["fixed"]["scores"], "fixture: nothing was scored"
    assert outcomes["reversed"] == outcomes["fixed"], "reversing the ready-cell order changed an outcome"
    assert outcomes["shuffled"] == outcomes["fixed"], "shuffling the ready-cell order changed an outcome"
