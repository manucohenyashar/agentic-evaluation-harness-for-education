"""TS-83 (#377): M-PIPE composition over F-DEV-PIPE — the cases still missing.

| Case | Oracle |
|---|---|
| TC-PIPE-02 | No `done` unit without its payload row (extract → evidence, score → verdict, deterministic → criterion_score), with a fault injected after a recorded reply returns, on the second score call of one cell; the faulted unit is not `done` |
| TC-PIPE-02 (clean) | With no fault the same invariant holds |
| TC-PIPE-03 | `integrity_pre` verifies a cell exactly once, only when its extraction is terminal: (a) both done → 1 call and a phase row; (b) one pending → 0 calls; (c) one quarantined → 1 call; (d) a second pass → still 1 |
| TC-PIPE-04 | For an escalating C2 cell the first aggregation runs verify → verdicts_for → aggregate → write_score → should_escalate → enqueue_escalation → mark_cell_phase('aggregated', 3); it re-aggregates at 5; one score row; escalation units inserted once |
| TC-PIPE-04 (atomicity) | `write_score` raising `IntegrityError` leaves no score row, no escalation unit and no `aggregated` phase for the cell, and pauses the run with `composition fault: IntegrityError` |
| TC-PIPE-04 (no escalation) | A non-escalating cell records its phase at 3 with no `enqueue_escalation` call |
| TC-PIPE-06 | (a) every submission narrated and graded; (b) a submission with an unscored (quarantined) criterion gets no narrative and grades `incomplete`; (c) a missing synthesis fixture for one submission: no narrative for it, `grades_computed = 3`, and the `synthesize` detail names it and `FixtureMissingError` |
| TC-PIPE-13 | `verdicts_for` raising `KeyError('C9')` pauses the run with `pause_reason == "composition fault: KeyError: 'C9'"`; `run_to_completion` returns |

Disclosed:
- **TC-PIPE-02's outcome.** The plan expects the faulted unit to strike and the run to complete.
  The design's error rule (gap-fix design, M-PIPE *Error handling*) is that any exception other
  than the provider taxonomy "is recorded in that stage's detail, and the run pauses with
  `composition fault: <type>: <msg>`". So the run pauses; the invariant (the case's P0 oracle)
  and "the faulted unit is not done" are asserted as written.
- **TC-PIPE-06 (b)** uses S1 (its C1 cell is unanimous and never escalated) rather than the
  plan's S3, so all three arms can be struck without touching an escalation.
- **TC-PIPE-03's cells.** F-DEV-PIPE enumerates ONE extract unit per cell, so the plan's two-unit
  cells ((b) "one done, one pending", (c) "one done, one quarantined") reduce to a pending unit
  and a quarantined unit; the oracle (verify only once the extraction is terminal, quarantine
  counting as terminal) is unchanged. The hook is called directly with a counting gate.
- **TC-PIPE-06 (c)'s detail.** The row says the detail names the submission AND
  `FixtureMissingError`; Q-23's resolution asks only for the submission. M-SYNTH absorbs a
  `ProviderError` (which `FixtureMissingError` is) per question into its failure count by design,
  so the class never reaches the trace. The case asserts the submission is named with zero
  narratives and a non-zero failure count.
- **Submission names.** F-DEV-PIPE mints its submission ids; cells are named here by their
  corpus content (S1's C1 evidence begins "I did not get to th").
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest

import aeh.pipeline as pipeline
from aeh.orch import Orchestrator
from aeh.prov import FixtureMissingError
from tests.support import pipe_world

pytestmark = pytest.mark.integration

S1_C1 = "I did not get to th"


def _world(root: Path, monkeypatch):
    monkeypatch.setenv("HARNESS_PIPE_MAX_PASSES", "300")  # a regression that never settles fails, never hangs
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    return world


def _rows(root: Path, sql: str, *params):
    with sqlite3.connect(root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite") as c:
        c.row_factory = sqlite3.Row
        return c.execute(sql, params).fetchall()


def _field(prompt, name) -> str:
    return str(dict(prompt.fields).get(name))


def _s1(root: Path) -> str:
    """S1's minted submission id: the document whose C1 region holds S1's corpus text."""
    (row,) = _rows(root, "SELECT DISTINCT d.submission_id FROM document d JOIN document_region r ON "
                         "r.document_id = d.document_id WHERE r.content LIKE ?", f"%{S1_C1}%")
    return row[0]


# --- TC-PIPE-02 -----------------------------------------------------------------------------

#: done units with no payload row, per stage (the plan's three invariant queries).
_ORPHANS = {
    "extract": "SELECT w.work_id FROM work_unit w WHERE w.run_id = ? AND w.stage = 'extract' "
               "AND w.status = 'done' AND NOT EXISTS (SELECT 1 FROM evidence e WHERE e.work_id = w.work_id)",
    "score": "SELECT w.work_id FROM work_unit w WHERE w.run_id = ? AND w.stage = 'score' "
             "AND w.status = 'done' AND NOT EXISTS (SELECT 1 FROM verdict v WHERE v.work_id = w.work_id)",
    "deterministic": "SELECT w.work_id FROM work_unit w WHERE w.run_id = ? AND w.stage = 'deterministic' "
                     "AND w.status = 'done' AND NOT EXISTS (SELECT 1 FROM criterion_score s WHERE "
                     "s.run_id = w.run_id AND s.submission_id = w.submission_id "
                     "AND s.criterion_id = w.criterion_id)",
}


def _orphans(root: Path, run_id: str) -> dict[str, int]:
    return {stage: len(_rows(root, sql, run_id)) for stage, sql in _ORPHANS.items()}


@pytest.mark.parametrize("fault", [True, False], ids=["after-call-fault", "clean"])
def test_tc_pipe_02_no_unit_is_done_without_its_payload(tmp_path, monkeypatch, fault):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    inner = world.provider.complete
    seen: list[str] = []
    faulted: list[str] = []

    def complete(prompt, model_ref, params):
        reply = inner(prompt, model_ref, params)
        if (fault and model_ref.role == "judge" and "criterion_id: C1" in _field(prompt, "criterion")
                and S1_C1 in _field(prompt, "submission")):
            seen.append(model_ref.build_id)
            if len(seen) == 2 and not faulted:
                faulted.append(model_ref.build_id)
                raise RuntimeError("after-call")
        return reply

    world.provider.complete = complete
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert _orphans(root, world.run_id) == {"extract": 0, "score": 0, "deterministic": 0}, (
        f"done units without their payload row: {_orphans(root, world.run_id)} (FR-PIPE-02)")
    if not fault:
        assert result.status == "complete", result.pause_reason
        return
    assert faulted, "fixture: the fault never fired"
    unit = _rows(root, "SELECT status FROM work_unit WHERE run_id = ? AND stage = 'score' AND judge_id = ? "
                       "AND criterion_id = 'C1' AND submission_id = ?", world.run_id, faulted[0], _s1(root))
    assert len(unit) == 1 and unit[0]["status"] != "done", (
        f"S1's C1 unit by {faulted[0]} is {[tuple(u) for u in unit]} although its worker raised after the call")
    assert result.status == "paused" and result.pause_reason.startswith(
        "composition fault: RuntimeError: after-call"), (result.status, result.pause_reason)


def test_tc_pipe_02_variant_an_extract_fault_after_the_call_leaves_its_unit_not_done(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    inner = world.provider.complete
    fired: list[bool] = []

    def complete(prompt, model_ref, params):
        reply = inner(prompt, model_ref, params)
        if model_ref.role == "extractor" and S1_C1 in _field(prompt, "submission") and not fired:
            fired.append(True)
            raise RuntimeError("after-call")
        return reply

    world.provider.complete = complete
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert fired, "fixture: no extraction of S1 was made"
    assert _orphans(root, world.run_id) == {"extract": 0, "score": 0, "deterministic": 0}
    assert result.status == "paused" and "RuntimeError" in (result.pause_reason or ""), result


def test_tc_pipe_02_variant_a_deterministic_fault_completes_no_unit(tmp_path, monkeypatch):
    from aeh.det import DeterministicEvaluator

    def fault(self, *args, **kwargs):
        raise RuntimeError("inside evaluate")

    monkeypatch.setattr(DeterministicEvaluator, "evaluate_cohort", fault)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        try:
            pipe_world.drive_composed(world)
        except RuntimeError:
            pass  # a pause instead of an escape is the arm below (#594)
    finally:
        world.store.close()
    assert _rows(root, "SELECT 1 FROM work_unit WHERE stage = 'deterministic' AND status = 'done'") == [], (
        "a deterministic unit is done although its evaluation raised")
    assert _orphans(root, world.run_id)["deterministic"] == 0


def test_tc_pipe_02_variant_a_deterministic_fault_pauses_rather_than_escaping(tmp_path, monkeypatch):
    """Written ahead; green since #594. `run_to_completion` used to call `evaluate_cohort` outside
    its fault handling, so the exception escaped the driver instead of pausing the run with a
    composition fault. The error rule names hooks, and `evaluate_cohort` is a pre-dispatch step;
    the expectation rests on FR-PIPE-01 ("returns a `RunResult`" whose status is the stored
    status) and seam 1 (a structured result, never a traceback), which an escaping exception
    breaks."""
    from aeh.det import DeterministicEvaluator

    def fault(self, *args, **kwargs):
        raise RuntimeError("inside evaluate")

    monkeypatch.setattr(DeterministicEvaluator, "evaluate_cohort", fault)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert result.status == "paused" and result.pause_reason.startswith("composition fault: RuntimeError")


# --- TC-PIPE-03 -----------------------------------------------------------------------------


class _CountingGate:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def verify(self, run_id, submission_id, criterion_id):
        self.calls.append((submission_id, criterion_id))


def test_tc_pipe_03_integrity_pre_runs_once_when_extraction_is_terminal(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        orch = Orchestrator(world.store)
        orch.enumerate_units(world.run_id)
        cells = [tuple(r) for r in _rows(
            root, "SELECT submission_id, criterion_id FROM work_unit WHERE run_id = ? AND stage = 'extract' "
                  "GROUP BY submission_id, criterion_id ORDER BY 1, 2", world.run_id)]
        assert len(cells) >= 3, f"fixture: extract cells: {cells}"
        (a, b, c) = cells[:3]
        with sqlite3.connect(root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite") as db:
            for cell, status in ((a, "done"), (c, "quarantined")):  # b stays pending
                db.execute("UPDATE work_unit SET status = ? WHERE run_id = ? AND stage = 'extract' "
                           "AND submission_id = ? AND criterion_id = ?", (status, world.run_id, *cell))
        handle = orch.run_handle(world.run_id)
        gate = _CountingGate()
        pipeline._integrity_pre_hook(orch, handle, gate)
        pipeline._integrity_pre_hook(orch, handle, gate)  # (d) the second pass
        phases = {(r["submission_id"], r["criterion_id"]) for r in _rows(
            root, "SELECT submission_id, criterion_id FROM cell_phase WHERE run_id = ? "
                  "AND phase = 'integrity_pre'", world.run_id)}
    finally:
        world.store.close()
    assert gate.calls.count(a) == 1, f"(a)/(d): {gate.calls}"
    assert gate.calls.count(b) == 0, f"(b) verified a cell whose extraction is pending: {gate.calls}"
    assert gate.calls.count(c) == 1, f"(c) a quarantined unit is terminal: {gate.calls}"
    assert a in phases and c in phases and b not in phases, phases


# --- TC-PIPE-04 -----------------------------------------------------------------------------


class _Trace:
    """Hook events in call order, attributed to the cell the hook is working on."""

    def __init__(self, monkeypatch):
        self.events: list[tuple[tuple[str, str], str]] = []
        self.current: tuple[str, str] | None = None
        import aeh.integ as integ

        def wrap(owner, name, key_of):
            real = getattr(owner, name)

            def spy(*args, **kwargs):
                key = key_of(*args, **kwargs)
                if key is not None:
                    self.current = key
                self.events.append((self.current, name if name != "mark_cell_phase"
                                    else f"mark_cell_phase:{args[5] if len(args) > 5 else kwargs.get('phase')}"
                                         f":{kwargs.get('units_consumed', args[6] if len(args) > 6 else 0)}"))
                return real(*args, **kwargs)

            monkeypatch.setattr(owner, name, spy)

        wrap(integ.IntegrityGate, "verify", lambda self, run, s, c: (s, c))
        wrap(pipeline, "verdicts_for", lambda cohort, run, s, c: (s, c))
        wrap(pipeline, "aggregate", lambda *a, **k: None)
        wrap(pipeline, "write_score", lambda tx, run, s, score, signals: (s, str(score.criterion_id)))
        wrap(pipeline, "should_escalate", lambda *a, **k: None)
        wrap(Orchestrator, "enqueue_escalation", lambda self, tx, key, *a, **k: (key[1], key[2]))
        wrap(Orchestrator, "mark_cell_phase", lambda self, tx, run, s, c, *a, **k: (s, c))

    def of(self, cell):
        return [name for key, name in self.events if key == cell]


_FIRST_PASS = ["verify", "verdicts_for", "aggregate", "write_score", "should_escalate",
               "enqueue_escalation", "mark_cell_phase:aggregated:3"]


def test_tc_pipe_04_the_aggregate_hook_order_for_an_escalating_cell(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    trace = _Trace(monkeypatch)
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert result.status == "complete", result.pause_reason
    c2 = sorted({key for key, _n in trace.events if key and key[1] == "C2"})
    assert c2, "fixture: no C2 cell was traced"
    cell = c2[0]
    events = trace.of(cell)
    start = events.index("mark_cell_phase:integrity_pre:0") + 1
    assert events[start:start + len(_FIRST_PASS)] == _FIRST_PASS, (
        f"first aggregation of {cell}: {events[start:]}")
    assert "mark_cell_phase:aggregated:5" in events[start + len(_FIRST_PASS):], (
        f"{cell} never re-aggregated over five verdicts: {events}")
    assert len(_rows(root, "SELECT 1 FROM criterion_score WHERE run_id = ? AND submission_id = ? "
                           "AND criterion_id = ?", world.run_id, *cell)) == 1
    assert len(_rows(root, "SELECT 1 FROM work_unit WHERE run_id = ? AND submission_id = ? AND "
                           "criterion_id = ? AND origin = 'escalation'", world.run_id, *cell)) == 2


def test_tc_pipe_04_a_non_escalating_cell_records_its_phase_without_enqueueing(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    trace = _Trace(monkeypatch)
    try:
        pipe_world.drive_composed(world)
    finally:
        world.store.close()
    quiet = [key for key in {k for k, _n in trace.events if k}
             if "mark_cell_phase:aggregated:3" in trace.of(key) and "enqueue_escalation" not in trace.of(key)]
    assert quiet, "fixture: every cell escalated"
    for key in quiet:
        assert "mark_cell_phase:aggregated:5" not in trace.of(key), (key, trace.of(key))


def test_tc_pipe_04_atomicity_a_failed_score_write_leaves_nothing(tmp_path, monkeypatch):
    real = pipeline.write_score
    failed: list[tuple[str, str]] = []

    def write_score(tx, run_id, submission_id, score, signals):
        if str(score.criterion_id) == "C2" and not failed:
            failed.append((submission_id, "C2"))
            raise sqlite3.IntegrityError("injected")
        return real(tx, run_id, submission_id, score, signals)

    monkeypatch.setattr(pipeline, "write_score", write_score)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert failed, "fixture: no C2 score write was attempted"
    cell = failed[0]
    assert result.status == "paused" and result.pause_reason.startswith("composition fault: IntegrityError"), (
        result.status, result.pause_reason)
    for sql in ("SELECT 1 FROM criterion_score WHERE run_id = ? AND submission_id = ? AND criterion_id = ?",
                "SELECT 1 FROM work_unit WHERE run_id = ? AND submission_id = ? AND criterion_id = ? "
                "AND origin = 'escalation'",
                "SELECT 1 FROM cell_phase WHERE run_id = ? AND submission_id = ? AND criterion_id = ? "
                "AND phase = 'aggregated'"):
        assert _rows(root, sql, world.run_id, *cell) == [], f"{cell}: a row survived the rollback: {sql}"


# --- TC-PIPE-06 -----------------------------------------------------------------------------


def _narrated(root: Path) -> set[str]:
    return {r[0] for r in _rows(root, "SELECT DISTINCT submission_id FROM narrative")}


def _grade_states(root: Path, run_id: str) -> dict[str, str]:
    return {r["submission_id"]: r["state"] for r in _rows(
        root, "SELECT submission_id, state FROM submission_grade WHERE run_id = ? AND is_current = 1", run_id)}


def test_tc_pipe_06_a_every_complete_submission_is_narrated_and_graded(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        result = pipe_world.drive_composed(world)
        submissions = set(Orchestrator(world.store).submissions(world.run_id))
    finally:
        world.store.close()
    assert result.status == "complete" and result.grades_computed == 3, result
    assert _narrated(root) == submissions and set(_grade_states(root, world.run_id)) == submissions


def test_tc_pipe_06_b_an_unscored_criterion_gets_no_narrative_and_an_incomplete_grade(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    inner = world.provider.complete

    def complete(prompt, model_ref, params):
        reply = inner(prompt, model_ref, params)
        if (model_ref.role == "judge" and "criterion_id: C1" in _field(prompt, "criterion")
                and S1_C1 in _field(prompt, "submission")):
            return dataclasses.replace(reply, text="not a verdict")
        return reply

    world.provider.complete = complete
    try:
        pipe_world.drive_composed(world)
    finally:
        world.store.close()
    struck = {r[0] for r in _rows(root, "SELECT submission_id FROM work_unit WHERE run_id = ? AND "
                                        "stage = 'score' AND status = 'quarantined'", world.run_id)}
    assert len(struck) == 1, f"fixture: quarantined score units on {struck}"
    (s1,) = struck
    assert s1 not in _narrated(root), "a submission with an unscored criterion was narrated (CT-SYNTH-05)"
    assert _grade_states(root, world.run_id).get(s1) == "incomplete", _grade_states(root, world.run_id)


def test_tc_pipe_06_c_a_missing_synthesis_fixture_never_blocks_grading(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    inner = world.provider.complete
    missed: list[str] = []

    def complete(prompt, model_ref, params):
        if model_ref.role == "synthesizer":
            submission = _field(prompt, "submission")
            if not missed or missed[0] == submission:
                missed.append(submission)
                raise FixtureMissingError("no synthesis recording for this submission")
        return inner(prompt, model_ref, params)

    world.provider.complete = complete
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert missed, "fixture: no synthesis request was made"
    victim = missed[0]
    synth = [s for s in result.stages if s.stage == "synthesize"]
    named = [d for d in synth[0].detail if d.startswith(f"{victim}:")] if synth else []
    assert len(named) == 1 and "0 narratives" in named[0] and " 0 failures" not in named[0], (
        f"the synthesize detail does not name {victim} with its failures: {synth}")
    assert result.grades_computed == 3, result
    assert victim not in _narrated(root) and len(_narrated(root)) == 2, (victim, _narrated(root))


# --- TC-PIPE-13 -----------------------------------------------------------------------------


def test_tc_pipe_13_a_hook_fault_pauses_and_is_named(tmp_path, monkeypatch):
    real = pipeline.verdicts_for
    raised: list[tuple[str, str]] = []

    def verdicts_for(cohort, run_id, submission_id, criterion_id):
        if not raised:
            raised.append((submission_id, criterion_id))
            raise KeyError("C9")
        return real(cohort, run_id, submission_id, criterion_id)

    monkeypatch.setattr(pipeline, "verdicts_for", verdicts_for)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    assert raised, "fixture: no aggregation ran"
    assert result.status == "paused", result.status
    assert result.pause_reason == "composition fault: KeyError: 'C9'", result.pause_reason
    agg = [s for s in result.stages if s.stage == "aggregate" and s.detail]
    assert any("KeyError" in d for s in agg for d in s.detail), [s.detail for s in agg]


def test_tc_pipe_13_the_fault_detail_names_the_cell(tmp_path, monkeypatch):
    """Written ahead; green since #595. The aggregate stage's fault detail used to carry only the
    exception, never the cell the hook was working on (TC-PIPE-13: "the aggregate stage detail
    names the cell")."""
    real = pipeline.verdicts_for
    raised: list[tuple[str, str]] = []

    def verdicts_for(cohort, run_id, submission_id, criterion_id):
        if not raised:
            raised.append((submission_id, criterion_id))
            raise KeyError("C9")
        return real(cohort, run_id, submission_id, criterion_id)

    monkeypatch.setattr(pipeline, "verdicts_for", verdicts_for)
    root = tmp_path / "w"
    world = _world(root, monkeypatch)
    try:
        result = pipe_world.drive_composed(world)
    finally:
        world.store.close()
    sid, cid = raised[0]
    details = [d for s in result.stages if s.stage == "aggregate" for d in s.detail]
    assert any(sid in d and cid in d for d in details), details
