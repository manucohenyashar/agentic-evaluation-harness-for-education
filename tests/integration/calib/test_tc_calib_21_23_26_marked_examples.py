"""Validity T9 (issue #902): the teacher's marked examples, graded under R₀ in a calibration
cohort and compared — `TC-SETUP-28`, `TC-CALIB-21`, `TC-CALIB-22`, `TC-CALIB-23` and
`TC-CALIB-26`'s stand-in arm.

| Case | What is asserted |
|---|---|
| TC-SETUP-28 (CT-SETUP-11 amended) | after `examples upload` + `examples mark`, M-PKG's `calibration_example_mark` holds every form band; `examples grade` scores every judged criterion of the same documents (the retired "stored, not used" arm is `test_tc_setup_28_b_not_used_retired.py`, written ahead) |
| TC-CALIB-21 (FR-CALIB-17, R31) | the cohort row reads `purpose = 'calibration'`; the run grades R₀; a ceiling below the spend stops the examples run (it counts against the run ceiling); `real` consent on the remote dev-ci profile is refused before any call — the transport saw nothing |
| TC-CALIB-22 (CT-CALIB-18) | examples, a class run, Finish (promotes): no calibration id in any class read, export, review queue, label, `package_validation`, `validation_record` or the package record; `aeh.stats` opened the class's file and never a calibration one; mutation: listing calibration files in `class_cohort_keys` is caught by the same trace |
| TC-CALIB-23 (FR-CALIB-16, CT-CALIB-15, FR-CALIB-13, CT-CALIB-10) | 4 examples, 3 disagreements: `discover` → `triage` → `elicit`, all three rubric ambiguity, one question; with max + 2 ambiguous criteria exactly max questions; answering mints R₁ pending (R₀ untouched, locked); skip at discovery / triage / questions → R₀ with the ambiguous part recorded; published-in-advance → R₀ and "next class" |
| TC-CALIB-26 (NFR-CALIB-05), stand-in arm | grading the 4 sheets as examples costs no more than the 4-student class run under the same transport; the examples read carries the cost and the ceiling. NOT the plan's oracle (TC-E2E-21's recordings): that arm is `test_tc_calib_26_b_recorded_cost.py`, written ahead |

**World.** `tests/support/eng7_examples.py`: the ENG7 class and test behind a real console
(rung 3), the panel config, the stand-in OpenRouter transport with a controlled judge.

**Written ahead: no** for every case here, although the issue says yes: S15 (#885), S16 (#886)
and S17 (#887) had merged before these were written.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from tests.support.eng7_examples import (
    CRITERIA,
    SHEETS,
    THREE_DISAGREEMENTS_TEACHER,
    eng7_examples,
    examples_checked,
    three_disagreements_rule,
)

pytestmark = pytest.mark.integration


def _world(tmp_path, monkeypatch, network_guard, **kwargs):
    return eng7_examples(tmp_path / "data", tmp_path / "work", monkeypatch, network_guard,
                         **kwargs)


def _file_rows(path: Path, sql: str, *params) -> list[dict]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(sql, params).fetchall()]


def _calib_rows(world, sql: str, *params) -> list[dict]:
    return _file_rows(world.root / "cohorts" / f"{world.calib_cohort()}.sqlite", sql, *params)


# --- TC-SETUP-28 ---------------------------------------------------------------------------------


def test_tc_setup_28_examples_are_stored_with_bands_and_graded(tmp_path, monkeypatch,
                                                               network_guard):
    """After upload and marking, M-PKG holds every band the forms gave, per document; `examples
    grade` then scores every judged criterion of those same documents (system bands)."""
    with _world(tmp_path, monkeypatch, network_guard,
                judge_rule=three_disagreements_rule) as world:
        _, job = world.upload()
        assert job["state"] == "succeeded", job
        world.mark({stem: dict(THREE_DISAGREEMENTS_TEACHER) for stem in SHEETS})
        documents = world.document_of()
        stored = {(row["document_id"], row["criterion_id"]): row["band"]
                  for row in world.catalog().example_marks(world.package_version)}
        assert stored == {(documents[stem], criterion): band for stem in SHEETS
                          for criterion, band in THREE_DISAGREEMENTS_TEACHER.items()}, stored

        _, job = world.grade()
        assert job["state"] == "succeeded", job
        scored = _calib_rows(
            world,
            "SELECT d.document_id, c.criterion_id, c.band FROM criterion_score c "
            "JOIN document d ON d.submission_id = c.submission_id")
    by_document: dict[str, set[str]] = {}
    for row in scored:
        by_document.setdefault(row["document_id"], set()).add(row["criterion_id"])
    assert by_document == {documents[stem]: set(CRITERIA) for stem in SHEETS}, (
        f"`examples grade` did not give a system band for every judged criterion of the "
        f"marked documents: {by_document}")


# --- TC-CALIB-21 --------------------------------------------------------------------------------


def test_tc_calib_21_graded_under_r0_in_a_calibration_cohort(tmp_path, monkeypatch,
                                                             network_guard):
    """The calibration cohort's row reads `purpose = 'calibration'`, its one run grades R0 (the
    version the marks were made under) and completes, and the examples read reports the run's
    spend against the run cost ceiling the config declares."""
    with _world(tmp_path, monkeypatch, network_guard) as world:
        examples_checked(world)
        cohorts = _calib_rows(world, "SELECT cohort_id, purpose FROM cohort")
        runs = _calib_rows(world, "SELECT run_id, status, package_version_id FROM run")
        read = world.examples_read()
        class_runs = world.class_runs()
    assert cohorts == [{"cohort_id": world.calib_cohort(), "purpose": "calibration"}], cohorts
    assert world.calib_cohort().startswith("calibration-")
    assert [(r["status"], r["package_version_id"]) for r in runs] == [
        ("complete", world.package_version)], runs
    assert class_runs == [], "grading the examples started a run in the class's own file"
    cost = read["cost"]
    assert cost["ceiling"] == "15" and cost["currency"] == "USD", cost
    assert cost["spent"] is not None and 0 < float(cost["spent"]) <= 15, cost


def test_tc_calib_21_the_examples_run_counts_against_the_run_cost_ceiling(
        tmp_path, monkeypatch, network_guard):
    """With a run cost ceiling below what checking four examples spends, the examples run stops
    at the ceiling instead of completing: its cost is counted against the same ceiling a class
    run has (FR-CALIB-17, NFR-CALIB-05)."""
    with _world(tmp_path, monkeypatch, network_guard,
                judge_rule=three_disagreements_rule) as world:
        _, job = world.upload()
        world.mark({stem: dict(THREE_DISAGREEMENTS_TEACHER) for stem in SHEETS})
        monkeypatch.setenv("HARNESS_COST_CEILING", "0.0001")
        _, job = world.grade()
        runs = _calib_rows(world, "SELECT status, pause_reason FROM run")
    assert job["state"] == "failed", f"the examples check finished under a tiny ceiling: {job}"
    assert len(runs) == 1 and runs[0]["status"] == "paused", runs
    assert "cost" in str(runs[0]["pause_reason"]).lower(), runs


def test_tc_calib_21_real_work_on_a_remote_profile_is_refused_before_any_call(
        tmp_path, monkeypatch, network_guard):
    """R31: on the remote dev-ci profile, examples whose consent class is `real` are refused at
    the upload, before anything is read: the transport saw no request and no calibration
    cohort exists."""
    with _world(tmp_path, monkeypatch, network_guard) as world:
        before = list(world.fake.sent)
        status, outcome = world.action(
            "examples upload", package_version=world.package_version, consent="real",
            documents=[{"name": "E7-001-strong.pdf",
                        "content_base64": __import__("base64").b64encode(
                            world.sheets["E7-001-strong"]).decode()}],
            test_paper={"name": "01-test-paper.pdf",
                        "content_base64": __import__("base64").b64encode(
                            world.test_paper).decode()})
        after = list(world.fake.sent)
        threads = dict(getattr(world.server.app, "_examples_threads", {}) or {})
        cohort_file = world.root / "cohorts" / f"{world.calib_cohort()}.sqlite"
    assert outcome.get("refused") is True and not outcome.get("dispatched"), (status, outcome)
    assert "Nothing was sent" in outcome["detail"], outcome
    assert after == before, f"the refused upload reached the transport: {after[len(before):]}"
    assert threads == {}, "a job was started for a refused upload"
    assert not cohort_file.exists(), "a calibration cohort was created for refused real work"


# --- TC-CALIB-22 --------------------------------------------------------------------------------


class _CohortTrace:
    """Every `store.cohort(key)` call, with whether an `aeh.stats` frame was on the stack."""

    def __init__(self, monkeypatch, store_type: type) -> None:
        self.calls: list[tuple[str, bool]] = []
        real = store_type.cohort
        trace = self

        def cohort(self, key, *args, **kwargs):
            frame, from_stats = sys._getframe(1), False
            while frame is not None:
                name = frame.f_globals.get("__name__", "")
                if name == "aeh.stats" or name.startswith("aeh.stats."):
                    from_stats = True
                    break
                frame = frame.f_back
            trace.calls.append((str(key), from_stats))
            return real(self, key, *args, **kwargs)

        monkeypatch.setattr(store_type, "cohort", cohort)

    def stats_keys(self) -> set[str]:
        return {key for key, from_stats in self.calls if from_stats}


def _stats_reads(world, run_id: str) -> None:
    """The two `aeh.stats` reads that enumerate cohort files from the data folder."""
    from aeh.stats import judge_signals

    judge_signals(world.store(), run_id)


def _sink_bodies(world, run_id: str) -> dict[str, str]:
    """Every class-facing read and export the case scans, as text."""
    bodies: dict[str, str] = {}

    def text(path, **query):
        status, body = world.raw_get(path, **query)
        assert status == 200, (path, status, body[:300])
        bodies[f"{path} {query}"] = body.decode("utf-8", errors="replace") \
            if path != "/api/v1/results/workbook" else _xlsx_text(body)

    for path in ("/api/v1/hub", "/api/v1/past-tests"):
        text(path)
    text("/api/v1/class-roster", cohort_id=world.cohort_id)
    for path in ("/api/v1/results/class", "/api/v1/results/screen", "/api/v1/review-queue",
                 "/api/v1/results/validity", "/api/v1/monitor"):
        text(path, run_id=run_id)
    text("/api/v1/results/export", run_id=run_id, format="csv")
    text("/api/v1/results/workbook", run_id=run_id)
    text("/api/v1/packages/record", package_version_id=world.package_version)
    for row in world.rows("SELECT submission_id FROM submission"):
        text("/api/v1/results/student-detail", run_id=run_id,
             submission_id=row["submission_id"])
    return bodies


def _xlsx_text(data: bytes) -> str:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return "\n".join(archive.read(name).decode("utf-8", errors="replace")
                         for name in archive.namelist())


def test_tc_calib_22_examples_reach_no_sink(tmp_path, monkeypatch, network_guard):
    """Grade 4 examples, then a class run, Finish the blind sample (which promotes): no
    calibration cohort id, examples run id, example submission id or example document id is in
    any class list, results or student read, export, the review queue, the label table,
    `package_validation`, `validation_record` or the package record read. `aeh.stats` opened
    the class's file and never a calibration one — and the same trace, with calibration files
    listed in `class_cohort_keys` (the CT-CALIB-18 mutation), catches the leak."""
    from aeh.store import CALIBRATION_COHORT_PREFIX

    with _world(tmp_path, monkeypatch, network_guard) as world:
        examples_checked(world)
        trace = _CohortTrace(monkeypatch, type(world.store()))
        world.start_class()
        (run,) = world.class_runs()
        status, seats = world.get("/api/v1/blind-seats", run_id=run["run_id"])
        assert status == 200, seats
        for seat in seats.get("seats", ()):
            world.dispatched("blind-sample draft", run_id=run["run_id"],
                             seat_id=seat["seat_id"], band=seat["bands"][-1]["name"])
        world.dispatched("blind-sample finish", run_id=run["run_id"])
        _stats_reads(world, run["run_id"])

        tokens = {world.calib_cohort()}
        tokens |= {r["run_id"] for r in _calib_rows(world, "SELECT run_id FROM run")}
        tokens |= {r["submission_id"] for r in _calib_rows(world,
                                                           "SELECT submission_id FROM submission")}
        tokens |= {r["document_id"] for r in _calib_rows(world, "SELECT document_id FROM document")}
        class_ids = {r["submission_id"] for r in world.rows("SELECT submission_id FROM submission")}
        class_ids |= {r["document_id"] for r in world.rows("SELECT document_id FROM document")}
        assert not (tokens & class_ids), "fixture: example and class ids collide; the scan " \
                                         "could not tell them apart"

        bodies = _sink_bodies(world, run["run_id"])
        durable = world.root / "durable.sqlite"
        labels = _file_rows(durable, "SELECT * FROM label")
        validations = _file_rows(durable, "SELECT * FROM package_validation")
        records = [row for path in sorted((world.root).rglob("*.sqlite"))
                   if "validation_record" in {r["name"] for r in _file_rows(
                       path, "SELECT name FROM sqlite_master WHERE type = 'table'")}
                   for row in _file_rows(path, "SELECT * FROM validation_record")]
        stats_keys = trace.stats_keys()

        # The mutation: list the calibration file among the classes; the trace must see it.
        import aeh.store

        real_keys = aeh.store.class_cohort_keys
        monkeypatch.setattr(aeh.store, "class_cohort_keys", lambda data_dir: tuple(
            sorted({*real_keys(data_dir), world.calib_cohort()})))
        trace.calls.clear()
        try:
            _stats_reads(world, run["run_id"])
        except ValueError:
            pass
        mutated_keys = trace.stats_keys()

    assert labels, "fixture: Finish wrote no label row, so the label scan proves nothing"
    assert validations, "fixture: Finish promoted nothing, so the validation scan proves nothing"
    leaks = [(where, token) for where, body in bodies.items() for token in tokens
             if token in body]
    for name, rows in (("label", labels), ("package_validation", validations),
                       ("validation_record", records)):
        leaks += [(name, token) for row in rows for token in tokens
                  if token in json.dumps(row, default=str)]
    assert not leaks, f"examples reached a class sink: {leaks[:20]}"
    assert world.cohort_id in stats_keys, (
        f"aeh.stats opened no class file ({stats_keys}), so the trace proves nothing")
    assert not [k for k in stats_keys if k.startswith(CALIBRATION_COHORT_PREFIX)], stats_keys
    assert world.calib_cohort() in mutated_keys, (
        "with the calibration cohort listed as a class, the trace did not see aeh.stats open "
        f"it ({mutated_keys}) — the census could not catch the CT-CALIB-18 mutation")


# --- TC-CALIB-23 --------------------------------------------------------------------------------


def test_tc_calib_23_three_disagreements_run_discover_triage_elicit(tmp_path, monkeypatch,
                                                                   network_guard):
    """4 examples, 3 disagreements (C2 on E7-001…003): reading the differences runs `discover`,
    then `triage` on each difference, then `elicit` — in that order. All three are rubric
    ambiguity (no agreeing example shares the system's band), so one question is asked, about
    C2's `full` level, within `CALIB_MAX_QUESTIONS`."""
    import aeh.calib.examples as examples
    from aeh.calib import CALIB_MAX_QUESTIONS

    order: list[str] = []
    for name in ("discover", "triage", "elicit"):
        real = getattr(examples, name)

        def spy(*args, _name=name, _real=real, **kwargs):
            order.append(_name)
            return _real(*args, **kwargs)

        monkeypatch.setattr(examples, name, spy)

    with _world(tmp_path, monkeypatch, network_guard) as world:
        examples_checked(world)
        order.clear()
        status, differences = world.get("/api/v1/calibration/differences",
                                        package_version=world.package_version)
        assert status == 200, differences
        steps = list(order)
        status, questions = world.get("/api/v1/calibration/questions",
                                      package_version=world.package_version)
    assert steps == ["discover", "triage", "triage", "triage", "elicit"], steps
    groups = {g["cause"]: g["differences"] for g in differences["groups"]}
    assert set(groups) == {"rubric_ambiguity"}, groups
    assert sorted((d["example"], d["your_mark"], d["system_mark"])
                  for d in groups["rubric_ambiguity"]) == [
        (f"{stem}.pdf", "full", "none") for stem in SHEETS[:3]], groups
    assert len(questions["questions"]) == 1 <= CALIB_MAX_QUESTIONS, questions
    assert (questions["questions"][0]["part"], questions["questions"][0]["level"]) == ("Q2",
                                                                                       "full")


def test_tc_calib_23_max_plus_two_ambiguities_ask_exactly_max_questions(
        tmp_path, monkeypatch, network_guard):
    """With every judged line marked at its top band by the teacher and its lowest by the system,
    all four criteria are ambiguous. With `HARNESS_CALIB_MAX_QUESTIONS = 2` (max + 2 = 4),
    exactly 2 questions are asked; at 4, all four; the knob is read on each read."""
    teacher = {criterion: bands[-1] for criterion, bands in CRITERIA.items()}
    with _world(tmp_path, monkeypatch, network_guard, judge_rule=lambda *a: None) as world:
        _, job = world.upload()
        world.mark({stem: dict(teacher) for stem in SHEETS})
        _, job = world.grade()
        assert job["state"] == "succeeded", job
        counts = {}
        for cap in ("2", "4"):
            monkeypatch.setenv("HARNESS_CALIB_MAX_QUESTIONS", cap)
            status, read = world.get("/api/v1/calibration/questions",
                                     package_version=world.package_version)
            assert status == 200, read
            counts[cap] = len(read["questions"])
    assert counts == {"2": 2, "4": 4}, (
        f"questions asked per cap: {counts}; with max + 2 ambiguous criteria exactly max are "
        "asked")


def test_tc_calib_23_an_answer_mints_r1_pending_through_the_lock(tmp_path, monkeypatch,
                                                                  network_guard):
    """`examples answer` (broaden) → `apply_answers` makes R1 on the published R0 through M-PKG:
    R0 stays published, locked and unchanged; R1 is a new unpublished version whose C2 `full`
    descriptor carries the clarification, recorded pending its gates; delivered stays R0."""
    from tests.support.eng7_examples import BROADENED_CLAUSE

    with _world(tmp_path, monkeypatch, network_guard) as world:
        examples_checked(world)
        catalog = world.catalog()
        r0 = world.package_version
        before = [dict(b) for b in catalog.bands("C2")]
        outcome = world.dispatched("examples answer", package_version=r0,
                                   answers={"q1": "broaden"})
        (revision,) = catalog.calibration_revisions(r0)
        r1 = revision["revision_version_id"]
        r0_full = [b for b in catalog.bands("C2") if b["band"] == "full"]
        locked = (catalog.is_locked(r0), catalog.is_locked(r1))
        delivered = catalog.delivered_version()
        r1_text = __import__("aeh.calib.first_class", fromlist=["rubric_text"]).rubric_text(
            catalog, r1)
    assert "clarified version" in outcome["detail"], outcome
    assert revision["state"] == "pending" and revision["base_version_id"] == r0, revision
    assert r1 != r0
    assert locked == (True, False), f"R0 locked, R1 not yet published: {locked}"
    assert delivered == r0, f"the next class would be graded with {delivered}, not R0"
    assert BROADENED_CLAUSE in r1_text, "R1 does not carry the teacher's clarification"
    assert BROADENED_CLAUSE not in json.dumps(before + r0_full), "R0's descriptor was edited"


@pytest.mark.parametrize("step", ["discovery", "triage", "questions"])
def test_tc_calib_23_tc_console_112_skip_at_any_step_leaves_r0_with_the_ambiguous_part_recorded(
        tmp_path, monkeypatch, network_guard, step):
    """`examples skip` before grading (discovery), after grading (triage), or with the questions
    read (questions): no clarified version, delivered R0; once a difference was found, the
    skip records each question as skipped and says the part is recorded as possibly unclear."""
    with _world(tmp_path, monkeypatch, network_guard,
                judge_rule=three_disagreements_rule) as world:
        _, job = world.upload()
        world.mark({stem: dict(THREE_DISAGREEMENTS_TEACHER) for stem in SHEETS})
        if step != "discovery":
            world.grade()
        if step == "questions":
            world.get("/api/v1/calibration/questions", package_version=world.package_version)
        outcome = world.dispatched("examples skip", package_version=world.package_version)
        catalog = world.catalog()
        revisions = catalog.calibration_revisions(world.package_version)
        delivered = catalog.delivered_version()
        history = catalog.elicitation_history(world.package_version)
        status, questions = world.get("/api/v1/calibration/questions",
                                      package_version=world.package_version)
    assert revisions == (), revisions
    assert delivered == world.package_version
    assert outcome["detail"].startswith("Skipped. Your test is marked with your rubric as "
                                        "written."), outcome
    if step == "discovery":
        assert history == () and "possibly unclear" not in outcome["detail"]
    else:
        assert "The 1 part(s) a question was about are recorded as possibly unclear" in \
            outcome["detail"], outcome
        assert [row["answer_given"] for row in history] == ["skipped"], history
        assert questions["status"] == "skipped", questions


def test_tc_calib_23_a_rubric_published_in_advance_stays_r0_and_says_next_class(
        tmp_path, monkeypatch, network_guard):
    """Answers on a rubric the students saw in advance: nothing is applied (no R1, delivered
    R0), the answers are kept in the history for the next class, and the outcome says so."""
    with _world(tmp_path, monkeypatch, network_guard) as world:
        examples_checked(world)
        outcome = world.dispatched("examples answer", package_version=world.package_version,
                                   answers={"q1": "broaden"},
                                   rubric_published_in_advance="true")
        catalog = world.catalog()
        revisions = catalog.calibration_revisions(world.package_version)
        history = catalog.elicitation_history(world.package_version)
        delivered = catalog.delivered_version()
    assert "your clarifications apply to the next class" in outcome["detail"], outcome
    assert revisions == () and delivered == world.package_version
    assert [row["answer_given"] for row in history] == ["broaden"], history


# --- TC-CALIB-26, the stand-in arm --------------------------------------------------------------


def _run_cost(world, run_id: str) -> float:
    rows = _file_rows(world.root / "durable.sqlite",
                      "SELECT value FROM run_metrics WHERE run_id = ? AND metric = 'actual_cost' "
                      "AND (submission_id IS NULL OR submission_id = '') "
                      "AND (criterion_id IS NULL OR criterion_id = '')", run_id)
    assert rows, f"fixture: run {run_id} recorded no actual_cost"
    return float(rows[-1]["value"])


def test_tc_calib_26_stand_in_examples_cost_no_more_than_the_class_run(
        tmp_path, monkeypatch, network_guard):
    """Under the stand-in transport (same per-call price for every call): grading the 4 ENG7
    sheets as examples costs no more than grading the same 4 sheets as a class, per paper and so
    at the NFR's 15 papers by scaling; the examples read carries that spend and the ceiling.
    The plan's oracle is the same comparison on TC-E2E-21's recordings (written ahead)."""
    with _world(tmp_path, monkeypatch, network_guard) as world:
        examples_checked(world)
        world.start_class()
        (run,) = world.class_runs()
        examples_run = _calib_rows(world, "SELECT run_id FROM run")[0]["run_id"]
        examples_cost = _run_cost(world, examples_run)
        class_cost = _run_cost(world, run["run_id"])
        read = world.examples_read()
    assert 0 < examples_cost <= class_cost, (examples_cost, class_cost)
    assert examples_cost / 4 * 15 <= class_cost / 4 * 15
    assert float(read["cost"]["spent"]) == pytest.approx(examples_cost), read["cost"]
    assert read["cost"]["ceiling"] == "15" and "run cost limit" in read["cost"]["text"]
