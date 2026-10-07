"""TS-134 (#545): M-PIPE's four close-out behaviours over F-DEV-PIPE (closeout test plan §5).

| Case | Oracle |
|---|---|
| TC-PIPE-20 (a) | With a baseline `mean=2.0, sd=0.5` stored for C1 under the run's key, the C1 cell at ordinal 5 escalates with a "distributional anomaly" reason (spy on `should_escalate`) |
| TC-PIPE-20 (a′) | That baseline reaches the run through its writer, `record_validation_baseline` under the run's key on the run's version (written ahead: #525) |
| TC-PIPE-20 (b) | No baseline: no anomaly reason, and every call received a `NoValidationData` baseline and history, never `None` |
| TC-PIPE-20 (c) | 6 blind C1 labels, 4 of them overrides: C1's reasons carry the override history (0.67); C2, with no labels, carries the no-data reason |
| TC-PIPE-20 (d) | A baseline stored mid-run is not seen by that run's later cells; the next run sees it (Q-45) |
| TC-PIPE-20 (e) | `aeh/pipeline.py` executes no SQL (CT-PIPE-05, artifact check) |
| TC-PIPE-21 (a) | A complete run's `submission_grade` rows deleted: `recover` grades every submission; a second `recover` writes no new revision |
| TC-PIPE-21 (b) | A `complete` run with no criterion scores is not graded |
| TC-PIPE-22 | MCQ-only package, 2 submissions: M-SYNTH is offered each exactly once, and each gets a narrative row (written ahead: #523) |
| TC-PIPE-23 (a) | One widened arm quarantined, budget available: the replacement arm runs and the cell aggregates over 5 verdicts |
| TC-PIPE-23 (b) | Budget exhausted at the replacement: the cell is `ungradeable_by_panel` / `even_panel_after_quarantine`, routed to review; the run is `complete`; every other cell is final |
| TC-PIPE-23 (c) | Two verdicts with no quarantine (a double over `verdicts_for`): the run pauses |
| RES-25 | The process is killed (`TerminateProcess`) between `complete` and grading; `python -m aeh recover --data-dir D` exits 0 and every submission is graded |

Disclosed fixture choices:
- **Stored baselines (TC-PIPE-20 a, d).** A run always uses a published version, and FR-PKG-04's
  triggers refuse any baseline write onto one. So the fixture stands the two
  `validation_record` lock triggers down around `record_validation_baseline` and restores them.
  That pins the M-PIPE half (read under the run's key, once per run, handed to
  `should_escalate`). Whether a baseline can reach a published version in production is #525's
  open decision; arm (a′) is that half, red until #525 lands, and its shape may move with the
  decision.
- **Escalations F-DEV-PIPE never recorded.** A stored baseline or a contested history makes cells
  escalate that the corpus recorded unescalated, so those widened arms have no recording and the
  run stops at the first one. The TC-PIPE-20 oracles are the decisions the spy saw, which are
  all taken before that point.
- **The quarantine (TC-PIPE-23).** The first `escalation-arm-5` request answers with an illegal
  verdict every time it is sent, so M-JUDGE strikes it out; `escalation-arm-6`, which the corpus
  never recorded, answers with `escalation-arm-4`'s recording. Budget exhaustion is set at the
  moment the replacement is requested: set earlier, the dispatcher also defers the quarantined
  arm's own retries.
"""

from __future__ import annotations

import dataclasses
import json
import os
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import aeh.pipeline as pipeline
from aeh import pkg, review
from aeh.orch import ESCALATION_BUDGET_ENV, Orchestrator
from harness.corpora import dev_pipe
from tests.support import broken_stats_fixtures as broken
from tests.support import pipe_world
from tests.support.source_tree import module_source

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
LOCK_TRIGGERS = ("validation_record_immutable", "validation_record_insert_locked")
#: mean 2.0, population sd 0.5 on the declared ordinal scale.
BASELINE_ORDINALS = {1: 1, 2: 6, 3: 1}


def _world(root: Path, monkeypatch):
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    return world


def _key(world):
    return Orchestrator(world.store).run_handle(world.run_id)


def _cohort_rows(root: Path, sql: str, *params):
    with sqlite3.connect(root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite") as c:
        c.row_factory = sqlite3.Row
        return c.execute(sql, params).fetchall()


def _record_baseline(root: Path, key, criterion_id: str):
    return pkg.record_validation_baseline(
        root, package_version_id=key.package_version_id, criterion_id=criterion_id,
        band_histogram={dev_pipe.band_at(criterion_id, o): n for o, n in BASELINE_ORDINALS.items()},
        backend_profile=key.backend_profile, panel_build_ref=key.panel_build_ref)


def _seed_baseline(root: Path, key, criterion_id: str = "C1") -> None:
    """Store the baseline on the run's (published) version, the lock triggers stood down."""
    saved: list[tuple[Path, list[str]]] = []
    for path in sorted((root / "packages").glob("*.pkg.sqlite")):
        with sqlite3.connect(path) as c:
            sqls = [r[0] for r in c.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name IN (?, ?)",
                LOCK_TRIGGERS)]
            for name in LOCK_TRIGGERS:
                c.execute(f"DROP TRIGGER IF EXISTS {name}")
        saved.append((path, sqls))
    assert any(len(sqls) == 2 for _p, sqls in saved), "fixture: no package carries the lock triggers"
    try:
        write = _record_baseline(root, key, criterion_id)
    finally:
        for path, sqls in saved:
            with sqlite3.connect(path) as c:
                for sql in sqls:
                    c.execute(sql)
    assert write.recorded, f"fixture: the baseline was not stored ({write.reason})"


class _EscalationSpy:
    """Every `should_escalate` call M-PIPE makes: the cell's criterion and ordinal, the two
    inputs it passed, and the decision."""

    def __init__(self, monkeypatch, before=None):
        self.calls: list[SimpleNamespace] = []
        real = pipeline.should_escalate

        def spy(**kwargs):
            if before is not None:
                before(self)
            decision = real(**kwargs)
            score = kwargs["score"]
            self.calls.append(SimpleNamespace(
                criterion_id=str(score.criterion_id), ordinal=getattr(score, "ordinal", None),
                baseline=kwargs["baseline"], history=kwargs["history"], decision=decision))
            return decision

        monkeypatch.setattr(pipeline, "should_escalate", spy)

    def of(self, criterion_id, ordinal=None):
        return [c for c in self.calls if c.criterion_id == criterion_id
                and (ordinal is None or c.ordinal == ordinal)]


def _anomalous(call) -> bool:
    return any(str(r).startswith("distributional anomaly") for r in call.decision.reasons)


def _mean_sd(baseline):
    return (baseline["mean"], baseline["std"])


# --- TC-PIPE-20 -----------------------------------------------------------------------------


def test_tc_pipe_20_a_a_stored_baseline_makes_the_ordinal_5_cell_escalate_as_an_anomaly(
        tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        _seed_baseline(root, _key(world))
        spy = _EscalationSpy(monkeypatch)
        pipe_world.drive_composed(world)
    finally:
        world.store.close()
    cells = spy.of("C1", 5)
    assert cells, f"no C1 cell at ordinal 5 reached should_escalate: {[(c.criterion_id, c.ordinal) for c in spy.calls]}"
    first = cells[0]
    assert _mean_sd(first.baseline) == (2.0, 0.5), f"the stored baseline did not arrive: {first.baseline!r}"
    assert first.decision.escalate and _anomalous(first), (
        f"C1 at ordinal 5 (z = 6) did not escalate as an anomaly: {first.decision!r} (FR-PIPE-15)")


@pytest.mark.writtenahead
def test_tc_pipe_20_a_prime_the_baseline_reaches_the_runs_version_through_its_writer(
        tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        key = _key(world)
        write = _record_baseline(root, key, "C1")
        from aeh.pkg import PackageCatalog
        package_id = key.package_version_id.rpartition("@")[0]
        read = PackageCatalog(world.store.package(package_id), package_id=package_id).baselines_for(
            key.package_version_id, backend_profile=key.backend_profile,
            panel_build_ref=key.panel_build_ref)["C1"]
    finally:
        world.store.close()
    assert write.recorded, (
        f"the baseline writer refused the run's version ({write.reason}): in production no "
        "baseline can reach a run (#525)")
    assert _mean_sd(read) == (2.0, 0.5), read


def test_tc_pipe_20_b_no_baseline_passes_no_data_and_raises_no_anomaly(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        spy = _EscalationSpy(monkeypatch)
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert result.status == "complete" and result.pause_reason is None, result.pause_reason
    assert spy.calls, "should_escalate was never called"
    for call in spy.calls:
        assert call.baseline is not None and call.history is not None, call
        assert isinstance(call.baseline, pkg.NoValidationData), (
            f"{call.criterion_id}: baseline {call.baseline!r} is not NoValidationData (CT-PIPE-10)")
        assert isinstance(call.history, pkg.NoValidationData), call.history
        assert not _anomalous(call), f"an anomaly with no baseline stored: {call.decision!r}"
    assert spy.of("C1", 5), "fixture: the ordinal-5 cell was not decided"


def test_tc_pipe_20_c_a_contested_history_enters_the_escalation_reason(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        for i in range(6):
            override = i < 4
            review.record_label(data_dir=root, label=broken.Label(
                label_id=f"L-C1-{i}", criterion_id="C1", band=2, teacher_band=3 if override else 2,
                origin="override" if override else "blind_sample"))
        spy = _EscalationSpy(monkeypatch)
        pipe_world.drive_composed(world)
    finally:
        world.store.close()
    c1, c2 = spy.of("C1"), spy.of("C2")
    assert c1 and c2, [(c.criterion_id, c.ordinal) for c in spy.calls]
    for call in c1:
        assert getattr(call.history, "override_rate", None) == pytest.approx(4 / 6), call.history
        assert "criterion override history (override_rate=0.67)" in call.decision.reasons, (
            f"C1's reasons omit its override history: {call.decision.reasons}")
    for call in c2:
        assert "criterion override history: no data" in call.decision.reasons, call.decision.reasons


def test_tc_pipe_20_d_a_mid_run_baseline_waits_for_the_next_run(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    key = _key(world)
    stored = []

    def promote_mid_run(spy):
        if not stored:
            _seed_baseline(root, key)
            stored.append(True)

    try:
        first = _EscalationSpy(monkeypatch, before=promote_mid_run)
        pipe_world.drive_composed(world)
        assert stored and len(first.of("C1")) >= 2, "fixture: fewer than two C1 decisions in run 1"
        for call in first.of("C1"):
            assert isinstance(call.baseline, pkg.NoValidationData), (
                f"run 1 saw a baseline stored after its first read: {call.baseline!r} (Q-45)")
        world.run_id = f"{pipe_world.PIPE_RUN_ID}-next"
        world.provider = pipe_world.StrictReplayProvider(pipe_world.recordings_dir())
        world.orchestrator = Orchestrator(world.store, provider=world.provider)
        world.build_run()
        world.start_run()
        second = _EscalationSpy(monkeypatch)
        pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert second.of("C1"), "run 2 decided no C1 cell"
    assert _mean_sd(second.of("C1")[0].baseline) == (2.0, 0.5), "the next run did not see the baseline"


def test_tc_pipe_20_e_pipeline_executes_no_sql():
    code = module_source("pipeline", REPO / "src" / "aeh")
    for pattern in (r"\bimport sqlite3\b", r"\.execute(?:many|script)?\(", r"\.query\(",
                    r"\bStatement\(", r"[\"'](?:SELECT|INSERT|UPDATE|DELETE|REPLACE)\s"):
        assert not re.search(pattern, code, re.IGNORECASE), (
            f"aeh/pipeline.py matches {pattern!r} (CT-PIPE-05)")


# --- TC-PIPE-21 -----------------------------------------------------------------------------


def _grades(root: Path, run_id: str):
    return _cohort_rows(root, "SELECT submission_id, revision, is_current FROM submission_grade "
                              "WHERE run_id = ? ORDER BY submission_id, revision", run_id)


def test_tc_pipe_21_a_recover_grades_a_complete_run_left_without_grades(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        result = pipe_world.drive_composed(world)
        assert result.status == "complete" and result.pause_reason is None, result.pause_reason
        submissions = {r[0] for r in _cohort_rows(
            root, "SELECT DISTINCT submission_id FROM criterion_score WHERE run_id = ?", world.run_id)}
        assert len(submissions) == dev_pipe.DEV_PIPE_COUNT
        with sqlite3.connect(root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite") as c:
            c.execute("DELETE FROM submission_grade WHERE run_id = ?", (world.run_id,))
        assert _grades(root, world.run_id) == []
        report = pipeline.recover(world.store)
        after = _grades(root, world.run_id)
        again = pipeline.recover(world.store)
        after_again = _grades(root, world.run_id)
    finally:
        world.store.close()
    assert world.run_id in report.runs_regraded, report
    assert {r["submission_id"] for r in after if r["is_current"]} == submissions, (
        f"recover left submissions ungraded: {[tuple(r) for r in after]} (FR-PIPE-16)")
    assert world.run_id not in again.runs_regraded, again
    assert [tuple(r) for r in after_again] == [tuple(r) for r in after], (
        "a second recover wrote a new grade revision")


def test_tc_pipe_21_b_a_complete_run_with_no_scores_is_not_graded(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        with sqlite3.connect(root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite") as c:
            c.execute("UPDATE run SET status = 'complete' WHERE run_id = ?", (world.run_id,))
        assert _cohort_rows(root, "SELECT 1 FROM criterion_score WHERE run_id = ?", world.run_id) == []
        report = pipeline.recover(world.store)
    finally:
        world.store.close()
    assert world.run_id not in report.runs_regraded, report
    assert _grades(root, world.run_id) == []


# --- TC-PIPE-22 -----------------------------------------------------------------------------


def test_tc_pipe_22_an_mcq_only_paper_is_offered_to_synthesis_and_narrated(tmp_path, monkeypatch):
    import aeh.synth as synth

    mcq = tuple(c for c in dev_pipe.CRITERIA if c.kind == "mcq")
    for name, value in (("CRITERIA", mcq), ("OPEN_CRITERION_IDS", ()),
                        ("CRITERION_IDS", tuple(c.criterion_id for c in mcq)),
                        ("BY_ID", {c.criterion_id: c for c in mcq}),
                        ("MAX_POINTS", sum(c.bands[-1].points for c in mcq)),
                        ("_ASSIGNED", tuple((s, r, {}, ok) for s, r, _o, ok in dev_pipe._ASSIGNED)),
                        ("DEV_PIPE_COUNT", 2)):
        monkeypatch.setattr(dev_pipe, name, value)
    offered: list[str] = []
    real = synth.SynthesisWorker.synthesize_submission

    def spy(self, run_id, submission_id, *args, **kwargs):
        offered.append(submission_id)
        return real(self, run_id, submission_id, *args, **kwargs)

    monkeypatch.setattr(synth.SynthesisWorker, "synthesize_submission", spy)
    root = tmp_path / "w"
    for sub in ("packages", "cohorts", "blobs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / "fx").mkdir()
    world = pipe_world.PipeWorld(root, tmp_path / "fx", record_as_you_go=True, monkeypatch=monkeypatch)
    try:
        world.build_run()
        world.start_run()
        result = pipe_world.drive_composed(world)
        submissions = sorted(r[0] for r in _cohort_rows(
            root, "SELECT DISTINCT submission_id FROM criterion_score WHERE run_id = ?", world.run_id))
    finally:
        world.store.close()
    assert result.status == "complete" and result.pause_reason is None, result.pause_reason
    assert len(submissions) == 2, submissions
    assert sorted(offered) == submissions, f"M-SYNTH was offered {offered}, not each of {submissions} once"
    narrated = {r[0] for r in _cohort_rows(root, "SELECT DISTINCT submission_id FROM narrative")}
    assert narrated == set(submissions), (
        f"an MCQ-only submission got no narrative: narrated {sorted(narrated)} of {submissions} "
        "(FR-PIPE-17; #523)")


# --- TC-PIPE-23 -----------------------------------------------------------------------------


def _quarantine_one_widened_arm(world):
    """The first `escalation-arm-5` request answers illegally every time; `escalation-arm-6`
    answers with `escalation-arm-4`'s recording."""
    inner = world.provider.complete
    target: list[str] = []

    def complete(prompt, model_ref, params):
        if model_ref.build_id == "escalation-arm-5":
            key = json.dumps(dict(prompt.fields), sort_keys=True, default=str)
            if not target:
                target.append(key)
            if key == target[0]:
                return dataclasses.replace(inner(prompt, model_ref, params), text="not a verdict")
        if model_ref.build_id == "escalation-arm-6":
            # The corpus's own arm-4 identity: a derived arm-6 ref differs in more than its build.
            model_ref = pipe_world.corpus_refs()["judge_refs"]["escalation-arm-4"]
        return inner(prompt, model_ref, params)

    world.provider.complete = complete


def _quarantined_cell(root: Path, run_id: str) -> tuple[str, str]:
    rows = _cohort_rows(root, "SELECT submission_id, criterion_id FROM work_unit "
                              "WHERE run_id = ? AND status = 'quarantined'", run_id)
    assert len(rows) == 1, f"fixture: expected one quarantined arm, found {[tuple(r) for r in rows]}"
    return rows[0]["submission_id"], rows[0]["criterion_id"]


def _scores(root: Path, run_id: str):
    return {(r["submission_id"], r["criterion_id"]): r for r in _cohort_rows(
        root, "SELECT * FROM criterion_score WHERE run_id = ?", run_id)}


def test_tc_pipe_23_a_a_replacement_arm_restores_an_odd_panel(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        _quarantine_one_widened_arm(world)
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    cell = _quarantined_cell(root, world.run_id)
    replacement = _cohort_rows(
        root, "SELECT status FROM work_unit WHERE run_id = ? AND submission_id = ? "
              "AND criterion_id = ? AND judge_id = 'escalation-arm-6'", world.run_id, *cell)
    assert [r["status"] for r in replacement] == ["done"], (
        f"the replacement arm for {cell} is {[tuple(r) for r in replacement]}, not one done unit "
        "(FR-PIPE-18)")
    assert result.status == "complete" and result.pause_reason is None, result.pause_reason
    assert _scores(root, world.run_id)[cell]["judge_count"] == 5, (
        f"cell {cell} did not re-aggregate over 5 verdicts")


def test_tc_pipe_23_b_no_budget_leaves_the_cell_ungradeable_and_the_run_complete(
        tmp_path, monkeypatch):
    real = Orchestrator.enqueue_replacement_arm

    def exhausted(self, tx, key):
        monkeypatch.setenv(ESCALATION_BUDGET_ENV, "0.0")
        return real(self, tx, key)

    monkeypatch.setattr(Orchestrator, "enqueue_replacement_arm", exhausted)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        _quarantine_one_widened_arm(world)
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    cell = _quarantined_cell(root, world.run_id)
    scores = _scores(root, world.run_id)
    assert result.status == "complete" and result.pause_reason is None, (
        f"the run is {result.status}: {result.pause_reason} (CT-PIPE-12)")
    row = scores[cell]
    assert (row["state"], row["state_reason"]) == ("ungradeable_by_panel", "even_panel_after_quarantine"), (
        f"cell {cell}: {dict(row)}")
    assert row["routing"] == "provisional", f"cell {cell} was not routed to review: {row['routing']!r}"
    others = {k: r["state"] for k, r in scores.items() if k != cell}
    assert set(others.values()) == {"final"}, f"other cells are not all final: {others}"


def test_tc_pipe_23_c_an_even_panel_without_quarantine_pauses_the_run(tmp_path, monkeypatch):
    real = pipeline.verdicts_for
    shortened: list[tuple[str, str]] = []

    def two_verdicts(cohort, run_id, submission_id, criterion_id):
        verdicts = real(cohort, run_id, submission_id, criterion_id)
        if not shortened and len(verdicts) == 3:
            shortened.append((submission_id, criterion_id))
        if shortened and shortened[0] == (submission_id, criterion_id):
            return verdicts[:2]
        return verdicts

    monkeypatch.setattr(pipeline, "verdicts_for", two_verdicts)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert shortened, "fixture: no three-verdict cell was reached"
    assert _cohort_rows(root, "SELECT 1 FROM work_unit WHERE run_id = ? AND status = 'quarantined'",
                        world.run_id) == []
    assert result.status == "paused", f"an even panel with no quarantine did not pause: {result.status}"
    assert "EvenPanelError" in (result.pause_reason or ""), result.pause_reason


# --- RES-25 ---------------------------------------------------------------------------------


_KILL_BEFORE_GRADING = r"""
import sys, time
from pathlib import Path
import aeh.pipeline.driver as driver
from tests.support import pipe_world

world = pipe_world.replay_world(Path(sys.argv[1]))
world.build_run()
world.start_run()

def _grading_never_finishes(*args, **kwargs):
    print("GRADING", flush=True)
    time.sleep(600)

# `_grade` is private to the package: patch it where the driver calls it.
driver._grade = _grading_never_finishes
pipe_world.drive_composed(world)
"""


def test_res_25_recover_after_a_kill_between_complete_and_grading(tmp_path):
    root = tmp_path / "d"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO / "src"), str(REPO)]),
           "PYTHONUNBUFFERED": "1"}
    child = subprocess.Popen([sys.executable, "-c", _KILL_BEFORE_GRADING, str(root)], cwd=str(REPO),
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(x) for x in child.stdout], daemon=True).start()
    try:
        deadline = time.monotonic() + 180
        while True:
            try:
                line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                pytest.fail("the run never reached grading")
            if "GRADING" in line:
                break
        child.kill()  # TerminateProcess on Windows, SIGKILL on POSIX
        child.wait(timeout=30)
    finally:
        if child.poll() is None:
            child.kill()
    # Windows releases a terminated process's file mapping asynchronously: the first read can
    # meet "disk I/O error" for a moment after `wait()` returns.
    for _attempt in range(50):
        try:
            runs = _cohort_rows(root, "SELECT run_id, status FROM run")
            break
        except sqlite3.OperationalError as error:
            if "disk I/O" not in str(error):
                raise
            time.sleep(0.2)
    else:
        pytest.fail("the killed run's cohort file stayed unreadable for 10 s")
    assert [tuple(r) for r in runs] == [(pipe_world.PIPE_RUN_ID, "complete")], [tuple(r) for r in runs]
    assert _grades(root, pipe_world.PIPE_RUN_ID) == [], "fixture: grades exist, so the kill came too late"
    done = subprocess.run([sys.executable, "-m", "aeh", "recover", "--data-dir", str(root)],
                          capture_output=True, text=True, env=env, cwd=str(REPO), timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    submissions = {r[0] for r in _cohort_rows(
        root, "SELECT DISTINCT submission_id FROM criterion_score WHERE run_id = ?", pipe_world.PIPE_RUN_ID)}
    graded = {r["submission_id"] for r in _grades(root, pipe_world.PIPE_RUN_ID) if r["is_current"]}
    assert len(submissions) == dev_pipe.DEV_PIPE_COUNT and graded == submissions, (graded, submissions)
