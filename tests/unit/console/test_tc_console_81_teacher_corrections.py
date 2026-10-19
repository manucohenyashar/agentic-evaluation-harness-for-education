"""`TC-CONSOLE-81` … `TC-CONSOLE-86` — every teacher mistake with a class or its papers has a
way back in the browser (`docs/design/console_teacher_corrections_delta.md`).

*Inline regressions* for the teacher-corrections delta. Each case drives the enumerated control
action through `ConsoleApp.perform` over a real store — the door the SPA's POST reaches — and
reads the result back through the screen reads the SPA renders:

* `TC-CONSOLE-81` (FR-CONSOLE-64/65) — a misspelt name is corrected in place; a student listed
  by mistake is taken off the list; a student who has a paper cannot be (the paper would be
  graded under nobody).
* `TC-CONSOLE-82` (FR-CONSOLE-66) — a paper matched to the wrong student moves to the right
  one, recorded in the decision trail; never onto a student who already has a paper.
* `TC-CONSOLE-83` (FR-CONSOLE-67) — an ungraded paper is removed with everything intake wrote,
  so its scan can be read again; a graded paper is refused, naming its run.
* `TC-CONSOLE-84` (FR-CONSOLE-68) — the wrong test paper is removed while nothing is graded,
  optionally with its ungraded sheets; refused once a paper is graded.
* `TC-CONSOLE-85` (FR-CONSOLE-69) — the class and papers reads say how many are listed, how
  many papers are in and exactly who has none; a nameless paper is never a phantom student.
* `TC-CONSOLE-86` (FR-CONSOLE-70) — past tests lists every run newest first with its class,
  test and dates, and each graded student by name.
"""

from __future__ import annotations

import pytest

from aeh.console import build_console
from aeh.console.history_reads import past_tests_read
from aeh.console.screen_reads import class_roster_read, papers_read, results_screen_read
from aeh.store import open_store

CLASS = "7b-corrections"


@pytest.fixture()
def console_store(tmp_path):
    store = open_store(tmp_path / "data")
    try:
        console = build_console(store=store)
        made = console.perform("create class", class_id=CLASS, consent_class="synthetic",
                               paste="Ada Lovelace\nAlan Turing\nGrace Hopper")
        assert made.dispatched, made.detail
        yield console, store
    finally:
        store.close()


def _roster(store) -> dict[str, str]:
    return {str(r["full_name"]): str(r["student_ref"]) for r in store.cohort(CLASS).query(
        "SELECT student_ref, full_name FROM roster")}


def _paper(store, submission_id: str, student_ref: str, *, document: bool = True,
           identity: str = "pass", quarantined: int = 0, status: str = "ok") -> None:
    with store.cohort(CLASS).transaction() as tx:
        tx.execute("INSERT INTO submission (submission_id, cohort_id, student_ref) "
                   "VALUES (:s, :c, :r)", s=submission_id, c=CLASS, r=student_ref)
        tx.execute("UPDATE submission SET v3_identity = :v, quarantined = :q, "
                   "ingest_status = :st WHERE submission_id = :s",
                   v=identity, q=quarantined, st=status, s=submission_id)
        if document:
            tx.execute("INSERT INTO document (document_id, submission_id, content_hash, kind) "
                       "VALUES (:d, :s, 'h', 'submission')", d=f"doc-{submission_id}",
                       s=submission_id)
            tx.execute("INSERT INTO document_region (region_id, document_id, page_no, "
                       "element_kind) VALUES (:r, :d, 1, 'text')", r=f"reg-{submission_id}",
                       d=f"doc-{submission_id}")


def _run(store, run_id: str, *, started: str, graded: tuple[str, ...] = ()) -> None:
    with store.cohort(CLASS).transaction() as tx:
        tx.execute(
            "INSERT INTO run (run_id, cohort_id, package_version_id, package_id, panel_config, "
            "backend_profile, provider_config, prompt_template_v, status, started_at, "
            "completed_at) VALUES (:r, :c, 'quiz-v1', 'quiz', '{}', 'dev-ci', '{}', 'v1', "
            "'complete', :st, :st)", r=run_id, c=CLASS, st=started)
        for index, submission_id in enumerate(graded):
            tx.execute("INSERT INTO work_unit (work_id, submission_id, stage, status, run_id) "
                       "VALUES (:w, :s, 'score', 'done', :r)", w=f"wu-{run_id}-{index}",
                       s=submission_id, r=run_id)


# --- TC-CONSOLE-81 — the class list's corrections ------------------------------------------------


def test_tc_console_81_a_misspelt_name_is_corrected_and_its_paper_stays(console_store):
    console, store = console_store
    ada = _roster(store)["Ada Lovelace"]
    _paper(store, "sub-1", ada)
    fixed = console.perform("rename student", cohort_id=CLASS, student_ref=ada,
                            full_name="Ada King-Lovelace")
    assert fixed.dispatched and not fixed.refused, fixed.detail
    assert _roster(store)["Ada King-Lovelace"] == ada
    listed = {s["student_ref"]: s for s in class_roster_read(None, console, {})["cohorts"][0][
        "students"]}
    assert listed[ada]["full_name"] == "Ada King-Lovelace"
    assert listed[ada]["submission_id"] == "sub-1"
    blank = console.perform("rename student", cohort_id=CLASS, student_ref=ada, full_name="  ")
    assert blank.refused and not blank.dispatched
    assert _roster(store)["Ada King-Lovelace"] == ada


def test_tc_console_81_a_student_listed_by_mistake_is_removed_but_not_one_with_a_paper(
        console_store):
    console, store = console_store
    names = _roster(store)
    _paper(store, "sub-1", names["Ada Lovelace"])
    gone = console.perform("remove student", cohort_id=CLASS, student_ref=names["Alan Turing"])
    assert gone.dispatched and not gone.refused, gone.detail
    assert "Alan Turing" not in _roster(store)
    kept = console.perform("remove student", cohort_id=CLASS, student_ref=names["Ada Lovelace"])
    assert kept.refused and not kept.dispatched
    # Said with the student's name, the way the teacher knows them — never a ref or a paper id.
    assert "Ada Lovelace has a paper" in kept.detail and "Nothing was written" in kept.detail
    assert names["Ada Lovelace"] not in kept.detail and "sub-1" not in kept.detail
    assert "Ada Lovelace" in _roster(store)


# --- TC-CONSOLE-82 — a paper moved to its rightful student -------------------------------------


def test_tc_console_82_a_paper_matched_to_the_wrong_student_moves_and_is_recorded(
        console_store):
    console, store = console_store
    names = _roster(store)
    _paper(store, "sub-1", names["Ada Lovelace"])
    _paper(store, "sub-2", names["Grace Hopper"])
    onto_taken = console.perform("move paper to student", cohort_id=CLASS,
                                 submission_id="sub-1", student_ref=names["Grace Hopper"])
    assert onto_taken.refused and "Grace Hopper already has a paper" in onto_taken.detail
    moved = console.perform("move paper to student", cohort_id=CLASS, submission_id="sub-1",
                            student_ref=names["Alan Turing"], actor="ms-cohen",
                            note="similar handwriting")
    assert moved.dispatched and not moved.refused, moved.detail
    assert "Alan Turing" in moved.detail and names["Alan Turing"] not in moved.detail
    handle = store.cohort(CLASS)
    assert handle.query("SELECT student_ref FROM submission WHERE submission_id = 'sub-1'")[0][
        "student_ref"] == names["Alan Turing"]
    trail = handle.query("SELECT resolution, actor, student_ref, note FROM quarantine_decision")
    assert [dict(r) for r in trail] == [{
        "resolution": "assigned", "actor": "ms-cohen", "student_ref": names["Alan Turing"],
        "note": f"moved from {names['Ada Lovelace']}: similar handwriting"}]
    again = console.perform("move paper to student", cohort_id=CLASS, submission_id="sub-1",
                            student_ref=names["Alan Turing"])
    assert again.dispatched and "nothing was changed" in again.detail
    assert len(handle.query("SELECT decision_id FROM quarantine_decision")) == 1


# --- TC-CONSOLE-83 — an ungraded paper removed; a graded one kept -------------------------------


def test_tc_console_83_an_ungraded_paper_is_removed_with_its_rows(console_store):
    console, store = console_store
    _paper(store, "sub-1", _roster(store)["Ada Lovelace"])
    gone = console.perform("remove paper", cohort_id=CLASS, submission_id="sub-1")
    assert gone.dispatched and not gone.refused, gone.detail
    handle = store.cohort(CLASS)
    for table in ("submission", "document", "document_region"):
        assert handle.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"] == 0, table
    twice = console.perform("remove paper", cohort_id=CLASS, submission_id="sub-1")
    assert twice.refused and "no paper" in twice.detail


def test_tc_console_83_a_graded_paper_is_refused_naming_its_run(console_store):
    console, store = console_store
    _paper(store, "sub-1", _roster(store)["Ada Lovelace"])
    _run(store, "run-a", started="2026-03-01T09:00:00+00:00", graded=("sub-1",))
    kept = console.perform("remove paper", cohort_id=CLASS, submission_id="sub-1")
    assert kept.refused and "run-a" in kept.detail
    assert store.cohort(CLASS).query("SELECT COUNT(*) AS n FROM submission")[0]["n"] == 1


# --- TC-CONSOLE-84 — the wrong test paper replaced ------------------------------------------------


def _test_paper(store) -> None:
    with store.cohort(CLASS).transaction() as tx:
        tx.execute("INSERT INTO document (document_id, submission_id, content_hash, kind) "
                   "VALUES ('doc-test', NULL, 'h', 'assessment')")


def test_tc_console_84_the_wrong_test_paper_is_removed_with_its_sheets(console_store):
    console, store = console_store
    _test_paper(store)
    _paper(store, "sub-1", "unknown", identity="unmatched", quarantined=1,
           status="unmatched_assessment")
    assert papers_read(None, console, {"cohort_id": CLASS})["test_paper_read"] is True
    swapped = console.perform("replace test paper", cohort_id=CLASS, with_sheets="true")
    assert swapped.dispatched and not swapped.refused, swapped.detail
    after = papers_read(None, console, {"cohort_id": CLASS})
    assert after["test_paper_read"] is False
    assert after["sheets"] == []


def test_tc_console_84_a_graded_class_keeps_its_test_paper(console_store):
    console, store = console_store
    _test_paper(store)
    _paper(store, "sub-1", _roster(store)["Ada Lovelace"])
    _run(store, "run-a", started="2026-03-01T09:00:00+00:00", graded=("sub-1",))
    kept = console.perform("replace test paper", cohort_id=CLASS)
    assert kept.refused and "already graded" in kept.detail
    assert papers_read(None, console, {"cohort_id": CLASS})["test_paper_read"] is True


# --- TC-CONSOLE-85 — who is missing, at a glance -----------------------------------------------------


def test_tc_console_85_the_class_says_who_has_no_paper_and_lists_no_phantoms(console_store):
    console, store = console_store
    names = _roster(store)
    _paper(store, "sub-1", names["Ada Lovelace"])
    # A paper no student was matched to, closed: never a student called 'unknown'.
    _paper(store, "sub-2", "unknown", identity="unmatched", status="incomplete")
    # A second paper for Ada, parked: never Ada twice.
    _paper(store, "sub-3", names["Ada Lovelace"], identity="already_has_paper",
           quarantined=1, status="incomplete")
    cohort = class_roster_read(None, console, {})["cohorts"][0]
    assert [s["full_name"] for s in cohort["students"]].count("Ada Lovelace") == 1
    assert "unknown" not in [s["student_ref"] for s in cohort["students"]]
    assert cohort["summary"] == {"listed": 3, "with_paper": 1,
                                 "without_paper": ["Alan Turing", "Grace Hopper"]}
    assert cohort["deletable"] is False and cohort["papers"] == 3
    sheets = {s["submission_id"]: s for s in papers_read(None, console, {"cohort_id": CLASS})[
        "sheets"]}
    assert sheets["sub-1"]["full_name"] == "Ada Lovelace" and sheets["sub-1"]["matched"]
    assert not sheets["sub-3"]["matched"] and sheets["sub-3"]["parked"]


# --- TC-CONSOLE-86 — past tests ---------------------------------------------------------------------


def test_tc_console_86_past_tests_lists_runs_newest_first_with_names(console_store,
                                                                     monkeypatch):
    console, store = console_store
    names = _roster(store)
    _paper(store, "sub-1", names["Ada Lovelace"])
    _run(store, "run-march", started="2026-03-01T09:00:00+00:00", graded=("sub-1",))
    _run(store, "run-may", started="2026-05-01T09:00:00+00:00", graded=("sub-1",))

    def records(_store, run_id):
        return [{"submission_id": "sub-1", "total": 7 if run_id == "run-march" else 9,
                 "state": "final"}]

    import aeh.console.history_reads as history

    monkeypatch.setattr(history, "run_grade_records", records)
    doc = past_tests_read(None, console, {})
    assert [run["run_id"] for run in doc["runs"]] == ["run-may", "run-march"]
    march = doc["runs"][1]
    assert (march["cohort_id"], march["package_version_id"]) == (CLASS, "quiz-v1")
    assert march["started_at"].startswith("2026-03-01")
    assert march["students"] == [{"submission_id": "sub-1", "student_ref": names["Ada Lovelace"],
                                  "full_name": "Ada Lovelace", "total": 7, "state": "final"}]
    assert past_tests_read(None, console, {"cohort_id": "other"})["runs"] == []


def test_tc_console_86_results_name_each_student(console_store, monkeypatch):
    console, store = console_store
    names = _roster(store)
    _paper(store, "sub-1", names["Ada Lovelace"])
    _run(store, "run-a", started="2026-03-01T09:00:00+00:00", graded=("sub-1",))
    import aeh.console.screen_reads as reads

    monkeypatch.setattr(reads, "run_grade_records", lambda _s, _r: [
        {"submission_id": "sub-1", "total": 7, "state": "final"}])
    doc = results_screen_read(None, console, {"run_id": "run-a"})
    assert doc["students"][0]["full_name"] == "Ada Lovelace"


# --- review findings: revisions, and papers a run graded without work units ----------------------


@pytest.mark.parametrize("parent, child", [("doc-a", "doc-b"), ("doc-b", "doc-a")])
def test_tc_console_83_a_revised_paper_is_removed_whatever_its_ids(console_store, parent, child):
    """A revision is a child document with regions of its own; the removal deletes it before
    its parent whatever order the ids sort in (a foreign-key failure was a coin flip)."""
    console, store = console_store
    _paper(store, "sub-1", _roster(store)["Ada Lovelace"], document=False)
    with store.cohort(CLASS).transaction() as tx:
        for doc, parent_id in ((parent, None), (child, parent)):
            tx.execute("INSERT INTO document (document_id, submission_id, content_hash, kind, "
                       "parent_doc_id) VALUES (:d, 'sub-1', 'h', 'submission', :p)",
                       d=doc, p=parent_id)
            tx.execute("INSERT INTO document_region (region_id, document_id, page_no, "
                       "element_kind) VALUES (:r, :d, 1, 'text')", r=f"reg-{doc}", d=doc)
    gone = console.perform("remove paper", cohort_id=CLASS, submission_id="sub-1")
    assert gone.dispatched and not gone.refused, gone.detail
    assert store.cohort(CLASS).query("SELECT COUNT(*) AS n FROM document")[0]["n"] == 0


def test_tc_console_83_a_paper_a_run_graded_without_work_is_kept_and_said_so(console_store):
    """M-GRADE grades every paper in the class — a parked one INCOMPLETE, with a rescan review
    row and no work unit. Such a paper is part of the run's record: refused in words, never a
    foreign-key error, and the screen does not offer the removal."""
    console, store = console_store
    _paper(store, "sub-1", "unknown", identity="unmatched", quarantined=1, status="incomplete")
    _run(store, "run-a", started="2026-03-01T09:00:00+00:00")
    with store.cohort(CLASS).transaction() as tx:
        tx.execute("INSERT INTO review_queue (queue_id, run_id, submission_id, criterion_id, "
                   "reason) VALUES ('q1', 'run-a', 'sub-1', 'C1', 'rescan')")
    kept = console.perform("remove paper", cohort_id=CLASS, submission_id="sub-1")
    assert kept.refused and "part of a grading run's record" in kept.detail, kept.detail
    assert "IntegrityError" not in kept.detail
    sheets = papers_read(None, console, {"cohort_id": CLASS})["sheets"]
    assert sheets[0]["graded"] is True


def test_tc_console_85_a_parked_second_copy_is_not_graded(console_store):
    """FR-INGEST-41: M-GRADE's run population skips a parked second copy, so the student is
    never shown twice in the results; once given to the student it is graded again."""
    from aeh.grade import GRADE_STATEMENTS

    console, store = console_store
    names = _roster(store)
    _paper(store, "sub-1", names["Ada Lovelace"])
    _paper(store, "sub-2", names["Ada Lovelace"], identity="already_has_paper", quarantined=1)
    population = [r["submission_id"] for r in store.cohort(CLASS).query(
        GRADE_STATEMENTS["select_run_submissions"], cohort_id=CLASS)]
    assert population == ["sub-1"]
