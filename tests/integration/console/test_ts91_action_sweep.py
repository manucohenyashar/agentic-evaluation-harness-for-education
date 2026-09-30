"""TS-91 (#385) / TS-96 (#390): TC-CONSOLE-44's action sweep and TC-CONSOLE-C26's biconditional.

Every Phase-1 action of the control surface, run on a real store twice: once where the owning door
succeeds and once where it refuses.
- **Success arm:** the effect exists and `dispatched=True`.
- **Refusal arm:** `dispatched=False`, the owning module's exception message is in the outcome's
  text (a spy on the owner records what it raised), and the effect is absent.
- **Both arms (TC-CONSOLE-C26):** `dispatched=True` never coexists with a missing effect.
- **Static:** no owning door is called under `contextlib.suppress(Exception)` in `console.py` (the
  audit double's own row write sits under one; it calls no door).

The actions are HLD §11.8's, as `CONTROL_SURFACE_ACTIONS` names them. Setup actions run over the
Stage A chain (`stage_chain`); run-time actions over a completed F-DEV-PIPE run.

Disclosed (arms not as the sweep table states them, each with its reason):
- Row 3's success arm (a scripted read-back through the console) is M-SETUP's TC-SETUP-C05/C06.
- Row 4's success arm and row 6's refusal arm contradict the design and are asserted as the design
  says: a run's version is published and immutable, so "set review window" is refused for a run
  (ADR-3, FR-PKG-01); and a resume on a completed run is a queued control row the orchestrator
  treats as a no-op (CT-ORCH-13, CT-ORCH-03). Both are for the plan owner.
- Row 9's refusal ("sampling after the quota is exhausted") and row 13's import arms are not
  reachable through the console: the blind draw has no quota state, and the console's action only
  exports. Row 11's refusal ("an unresolved gate") has no implementation: `finalize_batch` never
  refuses, so the arm uses an unknown run. Row 12's refusal amends an unknown submission (a
  completed run's grades settle final on completion, so no provisional grade exists).
- C26's biconditional is therefore asserted over the arms that exist, not all 14 x 2.

Written ahead, keyed 'unowned' (each needs an issue): arms where the console's behaviour contradicts
the sweep table are marked `writtenahead` individually, with the reason in the test's docstring.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

import aeh.console as console
from aeh.console import build_console
from tests.support import pipe_world

pytestmark = pytest.mark.integration


class _Owner:
    """Spy on an owning door: record every exception message it raises, re-raising it."""

    def __init__(self, monkeypatch, owner, name):
        self.raised: list[str] = []
        real = getattr(owner, name)

        def spy(*args, **kwargs):
            try:
                return real(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - recorded and re-raised
                self.raised.append(str(exc))
                raise

        monkeypatch.setattr(owner, name, spy)


def _refused_by(outcome, owner: _Owner):
    assert not outcome.dispatched, f"a refused action reported dispatched: {outcome}"
    assert owner.raised, f"fixture: the owning door never refused ({outcome.detail})"
    assert owner.raised[-1] in outcome.detail, (
        f"the refusal text is not the owner's message: {outcome.detail!r} vs {owner.raised[-1]!r}")


def _pipe_world(root: Path, monkeypatch, *, run: bool = True):
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world.build_run()
    if run:
        world.start_run()
        assert pipe_world.drive_composed(world).status == "complete"
    return world


def _rows(root: Path, sql: str, *params, tier: str = "cohort"):
    path = (root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite") if tier == "cohort" else (root / "durable.sqlite")
    with sqlite3.connect(path) as c:
        c.row_factory = sqlite3.Row
        return c.execute(sql, params).fetchall()


#: The owning doors the console calls (the sweep's owners), by method name.
_DOORS = {"finalize_batch", "act", "purge_cohort", "confirm_inventory", "set_answer_keys",
          "read_back_rubric", "set_review_window", "amend", "submit_blind", "blind_sample",
          "start_run_in_background", "export", "import_file", "create_run", "perform"}


def test_tc_console_44_static_no_door_call_under_a_blanket_suppression():
    import ast

    tree = ast.parse(Path(console.__file__).read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        if not any("suppress" in ast.unparse(item.context_expr) and "Exception" in ast.unparse(item.context_expr)
                   for item in node.items):
            continue
        called = {getattr(c.func, "attr", getattr(c.func, "id", "")) for b in node.body for c in ast.walk(b)
                  if isinstance(c, ast.Call)}
        if called & _DOORS:
            offenders.append((node.lineno, sorted(called & _DOORS)))
    assert not offenders, f"console.py calls an owning door under suppress(Exception): {offenders}"


# --- setup actions (pre-lock), over the Stage A chain ---------------------------------------


@pytest.fixture
def chain(tmp_data_dir):
    from tests.contract.setup._doubles import ingest_document, stage_chain

    chain = stage_chain(tmp_data_dir / "live")
    chain.doc = ingest_document(chain.store, kind="assessment")
    yield chain
    chain.store.close()


def _confirmed_questions(chain) -> int:
    return int(chain.store.package(chain.package_id).query(
        "SELECT COUNT(*) AS n FROM question WHERE confirmed_at IS NOT NULL")[0]["n"])


def test_tc_console_44_row1_approve_question_inventory(chain, monkeypatch):
    import aeh.setup as setup

    chain.service.propose_inventory(chain.doc)
    owner = _Owner(monkeypatch, setup.SetupService, "confirm_inventory")
    app = build_console(store=chain.store)
    ok = app.perform("approve question inventory", package_id=chain.package_id)
    assert ok.dispatched and _confirmed_questions(chain) > 0, ok
    again = app.perform("approve question inventory", package_id=chain.package_id)
    _refused_by(again, owner)


def test_tc_console_44_row2_supply_answer_keys(chain, monkeypatch):
    import aeh.setup as setup
    from tests.contract.setup._doubles import stage_confirmed

    stage_confirmed(chain)
    owner = _Owner(monkeypatch, setup.SetupService, "set_answer_keys")
    app = build_console(store=chain.store)
    bad = app.perform("supply answer keys", package_id=chain.package_id,
                      answer_keys={"CRIT-Q4": ["Z"]})
    _refused_by(bad, owner)
    keyed = lambda: chain.catalog.answer_key("CRIT-Q4")  # noqa: E731
    assert not keyed(), "a refused key was stored"
    ok = app.perform("supply answer keys", package_id=chain.package_id, answer_keys={"CRIT-Q4": ["A"]})
    assert ok.dispatched and tuple(keyed()) == ("A",), (ok, keyed())


# --- run-time actions, over a completed F-DEV-PIPE run --------------------------------------


def test_tc_console_44_row4_set_review_window_refuses_negative_hours(tmp_path, monkeypatch):
    from aeh.pkg import PackageCatalog

    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch)
    owner = _Owner(monkeypatch, PackageCatalog, "set_review_window")
    try:
        bad = build_console(store=world.store).perform("set review window", run_id=world.run_id, hours=-1)
    finally:
        world.store.close()
    _refused_by(bad, owner)


def test_tc_console_44_row4_a_runs_published_version_refuses_a_window_change(tmp_path, monkeypatch):
    """The plan's success arm (48 h "on the run's version", Q-22) contradicts the design: every
    run's version is published and ADR-3 puts the window inside the locked policy, so M-PKG refuses
    and the console says so (a plan-owner question, not a code defect)."""
    from aeh.pkg import PackageCatalog

    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch)
    owner = _Owner(monkeypatch, PackageCatalog, "set_review_window")
    try:
        outcome = build_console(store=world.store).perform("set review window", run_id=world.run_id, hours=48)
    finally:
        world.store.close()
    _refused_by(outcome, owner)


def test_tc_console_44_row5_start_run(tmp_path, monkeypatch):
    from tests.support.conf_builders import edge_cfg

    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch, run=False)
    # The worker's model calls are refused, so the background run pauses rather than completing:
    # the arm is about the door (a run left pending, a worker started), not the drive.
    monkeypatch.setattr(pipe_world.StrictReplayProvider, "complete",
                        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("no model in this arm")))
    try:
        app = build_console(store=world.store)
        ok = app.perform("start run", run_id=world.run_id, config=edge_cfg(panel=world.panel_refs))
        assert ok.dispatched and world.run_id in app._run_threads, ok
        app._run_threads[world.run_id].join(timeout=60)
        status = _rows(root, "SELECT status FROM run WHERE run_id = ?", world.run_id)[0]["status"]
        assert status != "pending", "the start door reported dispatched but the run never left pending"
        runs_before = len(_rows(root, "SELECT run_id FROM run"))
        # The refusal arm: the run has left `pending`, so the start door refuses a second start
        # (the grade-policy refusal of the plan's row is the exit-1 case of TC-REQ-90).
        import aeh.pipeline as pipeline

        owner = _Owner(monkeypatch, pipeline, "start_run_in_background")
        bad = app.perform("start run", run_id=world.run_id, config=edge_cfg(panel=world.panel_refs))
    finally:
        world.store.close()
    _refused_by(bad, owner)
    assert len(_rows(root, "SELECT run_id FROM run")) == runs_before, "a refused start wrote a run row"


def test_tc_console_44_row6_pause_queues_a_control_row(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch, run=False)
    world.start_run()
    try:
        ok = build_console(store=world.store).perform("pause/resume", run_id=world.run_id, state="paused")
    finally:
        world.store.close()
    assert ok.dispatched and _rows(root, "SELECT 1 FROM run_control WHERE run_id = ? AND action = 'pause'",
                                   world.run_id), ok


def test_tc_console_44_row6_a_resume_on_a_completed_run_is_queued_and_changes_nothing(tmp_path, monkeypatch):
    """The plan's refusal arm contradicts the design: a control row queues and the orchestrator
    honours it on its own schedule (CT-ORCH-13), and resuming a completed run is a no-op
    (CT-ORCH-03). So the row is written (C26 holds: dispatched with its effect) and the run stays
    complete."""
    from aeh.orch import Orchestrator

    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch)
    try:
        outcome = build_console(store=world.store).perform("pause/resume", run_id=world.run_id, state="running")
        Orchestrator(world.store).resume()
    finally:
        world.store.close()
    assert outcome.dispatched and _rows(root, "SELECT 1 FROM run_control WHERE run_id = ? AND action = 'resume'",
                                        world.run_id), outcome
    assert _rows(root, "SELECT status FROM run WHERE run_id = ?", world.run_id)[0]["status"] == "complete"


def test_tc_console_44_row7_resolve_quarantine_item(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch)
    sid = _rows(root, "SELECT submission_id FROM submission LIMIT 1")[0]["submission_id"]
    try:
        app = build_console(store=world.store)
        stale = app.perform("resolve quarantine item", submission_id="sub-nobody")
        ok = app.perform("resolve quarantine item", submission_id=sid, resolution="unresolvable")
    finally:
        world.store.close()
    assert not stale.dispatched and "sub-nobody" in stale.detail, stale
    assert not _rows(root, "SELECT 1 FROM submission WHERE submission_id = 'sub-nobody'"), "the refusal wrote"
    assert ok.dispatched, ok
    assert _rows(root, "SELECT ingest_status FROM submission WHERE submission_id = ?", sid)[0][0] == "incomplete"


def test_tc_console_44_row8_review_action(tmp_path, monkeypatch):
    from aeh import review

    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch)
    owner = _Owner(monkeypatch, review.ReviewService, "act")
    try:
        app = build_console(store=world.store)
        item = app.review_queue(world.run_id).queue.shown[0]
        members = getattr(item, "members", None) or (item,)
        target = members[0]
        labels_before = len(_rows(root, "SELECT label_id FROM label", tier="durable"))
        stale = app.perform("review action", run_id=world.run_id, submission_id=target.submission_id,
                            criterion_id=target.criterion_id, decision="accept", revision=999)
        labels_mid = len(_rows(root, "SELECT label_id FROM label", tier="durable"))
    finally:
        world.store.close()
    assert not stale.dispatched and owner.raised and owner.raised[0] in stale.detail, stale
    assert labels_mid == labels_before, "a refused review wrote a label"


def test_tc_console_44_row8_accepting_a_review_item_records_a_label(tmp_path, monkeypatch):
    """Written ahead; green since #598. The console's review service
    (`review_service_over`, via `_review_service`) binds no package catalog, so M-REVIEW maps
    bands on `REVIEW_DEFAULT_BANDS` and refuses a band the run's package declares
    ("the declared band set carries no band 'secure'"): no review of an F-DEV-PIPE item, whose
    band names are its own, can be accepted from the console."""
    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch)
    try:
        app = build_console(store=world.store)
        item = app.review_queue(world.run_id).queue.shown[0]
        target = (getattr(item, "members", None) or (item,))[0]
        labels_before = len(_rows(root, "SELECT label_id FROM label", tier="durable"))
        ok = app.perform("review action", run_id=world.run_id, submission_id=target.submission_id,
                         criterion_id=target.criterion_id, decision="accept")
    finally:
        world.store.close()
    assert ok.dispatched, ok
    assert len(_rows(root, "SELECT label_id FROM label", tier="durable")) == labels_before + 1


def test_tc_console_44_row10_correct_an_answer_key(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch)
    scores = lambda: [tuple(r) for r in _rows(root, "SELECT submission_id, band FROM criterion_score "  # noqa: E731
                                                    "WHERE run_id = ? AND criterion_id = 'C3' ORDER BY 1", world.run_id)]
    before = scores()
    try:
        app = build_console(store=world.store)
        bad = app.perform("correct an answer key after a run", run_id=world.run_id,
                          criterion_id="C-nowhere", answer_key=["A"])
        mid = scores()
        ok = app.perform("correct an answer key after a run", run_id=world.run_id,
                         criterion_id="C3", answer_key=["A"])
    finally:
        world.store.close()
    assert not bad.dispatched and "C-nowhere" in bad.detail, bad
    assert mid == before, "a refused correction re-derived scores"
    assert ok.dispatched and "re-derived" in ok.detail, ok
    assert scores() != before, "the corrected key re-derived nothing for this run"


def test_tc_console_44_row11_finalize_batch(tmp_path, monkeypatch):
    from aeh.grade import GradingService

    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch)
    owner = _Owner(monkeypatch, GradingService, "finalize_batch")
    try:
        app = build_console(store=world.store)
        bad = app.perform("finalize batch", run_id="run-nowhere", actor="teacher")
        ok = app.perform("finalize batch", run_id=world.run_id, actor="teacher")
    finally:
        world.store.close()
    assert not bad.dispatched and "run-nowhere" in bad.detail, bad
    assert ok.dispatched, ok
    states = {r["state"] for r in _rows(root, "SELECT state FROM submission_grade WHERE run_id = ? "
                                              "AND is_current = 1", world.run_id)}
    assert states == {"final"}, states


def test_tc_console_44_row13_export(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch)
    try:
        app = build_console(store=world.store)
        bad = app.perform("export/import package", package_version="pkg-nowhere@000")
        ok = app.perform("export/import package", package_version=world.version)
    finally:
        world.store.close()
    assert not bad.dispatched and not (root / "exports" / "pkg-nowhere@000.aehpkg").exists(), bad
    assert ok.dispatched and (root / "exports" / f"{world.version}.aehpkg").exists(), ok


def test_tc_console_44_row14_purge_before_promotion_is_refused(tmp_path, monkeypatch):
    from aeh.store import SqliteStore

    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch)
    owner = _Owner(monkeypatch, SqliteStore, "purge_cohort")
    try:
        bad = build_console(store=world.store).perform("purge cohort", cohort_id=world.cohort_id)
    finally:
        world.store.close()
    _refused_by(bad, owner)
    assert (root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite").exists(), "a refused purge deleted"


def test_tc_console_44_row14_purge_after_promotion_removes_the_cohort(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch)
    cohort_file = root / "cohorts" / f"{pipe_world.PIPE_COHORT_ID}.sqlite"
    with sqlite3.connect(root / "durable.sqlite") as c:  # the three promotion gates, met
        c.execute("INSERT INTO audit_record (audit_record_id, run_id, recorded_at, profile_summary, cohort_id) "
                  "VALUES ('a-p', ?, '2026-09-01T00:00:00Z', 'edge-local', ?)", (world.run_id, world.cohort_id))
        c.execute("INSERT INTO criterion_stats (package_version_id, criterion_id, backend_profile, panel_build_ref, "
                  "n, cohort_id) VALUES (?, 'C1', 'edge-local', '', 5, ?)", (world.version, world.cohort_id))
        c.execute("INSERT INTO label (label_id, run_id, student_ref, criterion_id, label_type, band, evaluation_mode, "
                  "saw_system_output, routing, origin, cohort_id) VALUES ('l-p', ?, 'P-0001', 'C1', 'blind', 'B1', "
                  "'judged', 0, 'queued', 'blind_sample', ?)", (world.run_id, world.cohort_id))
    try:
        ok = build_console(store=world.store).perform("purge cohort", cohort_id=world.cohort_id)
    finally:
        world.store.close()
    assert ok.dispatched, ok
    # FR-STORE-07 empties Tiers C and R and keeps the migrated file (schema_version survives).
    with sqlite3.connect(cohort_file) as c:
        left = c.execute("SELECT COUNT(*) FROM submission").fetchone()[0]
    assert left == 0, f"a purge reported done left {left} submissions in the cohort file"


def test_tc_console_44_row15_exemplar_paraphrases_are_unavailable(tmp_path, monkeypatch):
    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch, run=False)
    try:
        outcome = build_console(store=world.store).perform("approve exemplar paraphrases at export")
    finally:
        world.store.close()
    assert not outcome.dispatched and "3.5" in outcome.detail, outcome


def test_tc_console_44_row3_rubric_read_back_without_a_setup_model_is_refused(chain):
    """Row 3's refusal arm: with no setup model reference the door refuses before anything is
    read. Disclosed: the success arm (a scripted read-back through the console) is not driven
    here; the read-back itself is M-SETUP's TC-SETUP-C05/C06 over the same chain."""
    from tests.contract.setup._doubles import stage_confirmed

    stage_confirmed(chain)
    before = int(chain.store.package(chain.package_id).query(
        "SELECT COUNT(*) AS n FROM criterion")[0]["n"])
    outcome = build_console(store=chain.store, provider=chain.provider).perform(
        "accept or correct rubric read-back", package_id=chain.package_id)
    assert not outcome.dispatched and "setup model" in outcome.detail, outcome
    after = int(chain.store.package(chain.package_id).query("SELECT COUNT(*) AS n FROM criterion")[0]["n"])
    assert after == before, "a refused read-back wrote criteria"


def test_tc_console_44_row9_a_blind_label_is_recorded(tmp_path, monkeypatch):
    """Written ahead; green since #598 (the row-8 cause): the console's review service bound
    no package catalog, so every blind band the run's package declares is refused on the default
    scale."""
    from harness.corpora import dev_pipe

    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch)
    try:
        app = build_console(store=world.store)
        cells = [tuple(r) for r in world.handle.query(
            "SELECT submission_id, criterion_id FROM criterion_score WHERE criterion_id IN ('C1', 'C2')")]
        outcomes = [app.perform("blind-sample submission", run_id=world.run_id, submission_id=s,
                                criterion_id=c, band=dev_pipe.band_at(c, 2)) for s, c in cells]
    finally:
        world.store.close()
    assert any(o.dispatched for o in outcomes), [o.detail[:120] for o in outcomes]
    assert _rows(root, "SELECT 1 FROM label WHERE label_type = 'blind'", tier="durable")


def test_tc_console_44_row12_amend_a_finalized_grade(tmp_path, monkeypatch):
    """Disclosed: the refusal arm amends an unknown submission. The plan's "amending a provisional
    grade" needs a provisional grade, and a completed run's grades settle final on completion."""
    from harness.corpora import dev_pipe
    from aeh.grade import GradingService

    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch)
    owner = _Owner(monkeypatch, GradingService, "amend")
    try:
        app = build_console(store=world.store)
        sid = world.handle.query("SELECT submission_id FROM submission_grade LIMIT 1")[0][0]
        prior = [tuple(r) for r in world.handle.query(
            "SELECT revision, grade, total FROM submission_grade WHERE submission_id = :s", s=sid)]
        bad = app.perform("amend a finalized grade", run_id=world.run_id, submission_id="sub-nobody",
                          criterion_id="C1", new_band=dev_pipe.band_at("C1", 2), actor="teacher", reason="r")
        ok = app.perform("amend a finalized grade", run_id=world.run_id, submission_id=sid,
                         criterion_id="C1", new_band=dev_pipe.band_at("C1", 2), actor="teacher", reason="r")
        after = [tuple(r) for r in world.handle.query(
            "SELECT revision, grade, total, is_current FROM submission_grade WHERE submission_id = :s", s=sid)]
    finally:
        world.store.close()
    assert not bad.dispatched, bad
    assert ok.dispatched, ok
    assert len(after) == len(prior) + 1 and [r[:3] for r in after[:len(prior)]] == prior, (prior, after)
    assert after[-1][3] == 1 and all(r[3] == 0 for r in after[:-1]), after


# --- ADV-14 (TS-99, #393): a door that raises is never reported done -------------------------

_ADV14 = [
    # (action, owner module attr path, method, params builder)
    ("finalize batch", "aeh.grade:GradingService", "finalize_batch",
     lambda w: {"run_id": w.run_id, "actor": "teacher"}),
    ("review action", "aeh.review:ReviewService", "act", None),
    ("purge cohort", "aeh.store:SqliteStore", "purge_cohort", lambda w: {"cohort_id": w.cohort_id}),
    ("amend a finalized grade", "aeh.grade:GradingService", "amend", None),
    ("export/import package", "aeh.pkg:PackageCatalog", "export", lambda w: {"package_version": w.version}),
    ("set review window", "aeh.pkg:PackageCatalog", "set_review_window",
     lambda w: {"run_id": w.run_id, "hours": 48}),
    ("start run", "aeh.pipeline:start_run_in_background", None, None),
]


@pytest.mark.parametrize("action, owner, method, build", _ADV14, ids=[a[0] for a in _ADV14])
def test_adv_14_a_raising_door_is_reported_refused(tmp_path, monkeypatch, action, owner, method, build):
    """ADV-14: the owning door raises `RuntimeError("x")`; the console reports `dispatched=False`
    with the text. Disclosed: (1) seven of the fourteen actions — the ones whose effect goes through
    a single owning method; pause/resume and resolve-quarantine write the console's own row, and the
    setup, blind and correction doors are exercised in their sweep rows. (2) The door raises on
    ENTRY, so "no partial effect" is shown only for a door that never started; a raise after a
    partial write inside the door's transaction is not constructed here."""
    import importlib

    from harness.corpora import dev_pipe
    from tests.support.conf_builders import edge_cfg

    module_name, _, attr = owner.partition(":")
    module = importlib.import_module(module_name)

    def boom(*args, **kwargs):
        raise RuntimeError(f"x-{action}")

    if method is None:
        monkeypatch.setattr(module, attr, boom)
    else:
        monkeypatch.setattr(getattr(module, attr), method, boom)
    root = tmp_path / "w"
    world = _pipe_world(root, monkeypatch, run=action != "start run")
    before = {t: len(_rows(root, f"SELECT * FROM {t}")) for t in ("run", "submission_grade", "run_control")}
    labels_before = len(_rows(root, "SELECT * FROM label", tier="durable"))
    try:
        app = build_console(store=world.store)
        if build is not None:
            params = build(world)
        elif action == "start run":
            params = {"run_id": world.run_id, "config": edge_cfg(panel=world.panel_refs)}
        else:
            sid, cid = world.handle.query("SELECT submission_id, criterion_id FROM criterion_score "
                                          "WHERE criterion_id = 'C1' LIMIT 1")[0]
            params = {"run_id": world.run_id, "submission_id": sid, "criterion_id": cid,
                      "new_band": dev_pipe.band_at("C1", 2), "decision": "edit", "actor": "teacher",
                      "reason": "r"}
        outcome = app.perform(action, **params)
    finally:
        world.store.close()
    assert not outcome.dispatched and f"x-{action}" in outcome.detail, outcome
    assert {t: len(_rows(root, f"SELECT * FROM {t}")) for t in before} == before, "a partial effect survived"
    assert len(_rows(root, "SELECT * FROM label", tier="durable")) == labels_before
    if action == "export/import package":
        assert not (root / "exports" / f"{world.version}.aehpkg").exists()
