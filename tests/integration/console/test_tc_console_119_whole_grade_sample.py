"""Validity T18 (issue #903): TC-CONSOLE-119 (FR-CONSOLE-93; pair M-CONSOLE→CT-REVIEW-11) — the
whole-grade sample, served. Rung 3, over HTTP.

| Arm | World | What is asserted |
|---|---|---|
| population and size | the validity store: class A with 17 papers whose every line is `auto` and one with a single `queued` line; class B (a SECOND class, same package) with 12 all-`auto` papers | 10 to 15 drawn; every drawn paper is in class A's all-`auto` population (asserted against `criterion_score.routing`); the mixed paper and every class-B paper are never drawn (the run scoping #869 fixed); no grade letter (no boundary table); no short-sample sentence; every read is the same draw |
| per student, fewer than 10 | ENG7 (boundary table `pass = 6`), two papers routed wholly `auto` | exactly those two drawn, with the sentence naming 2 and the range; per student: roster name, the stored total and grade letter, per-question points equal to the stored points of the question's lines, each line's level equal to its stored band, a narrative; the population note verbatim |
| the answers | ENG7 | `whole-grade confirm` and `whole-grade skip` each write exactly one `audit_record` and no `label`; a repeat writes nothing; the completion outcome's `next` lists the whole-grade sample after the blind sample and before the results |
"""

from __future__ import annotations

import pytest

from tests.support.console_r2_world import name_all, served_validity
from tests.support.eng7_console import eng7_console

pytestmark = pytest.mark.integration

#: CT-REVIEW-11's population note, verbatim from the design (FR-CONSOLE-93).
POPULATION_NOTE = (
    "drawn from the answers the system accepted on its own, not the ones you reviewed")
WHOLE_GRADE_RANGE = (10, 15)


def _sample(served) -> dict:
    status, document = served.get("/api/v1/results/whole-grade-sample", run_id=served.run_id)
    assert status == 200, document
    return document


def _auto_population(served) -> set[str]:
    """Papers whose every line of the run is routed `auto`, read from the stored rows."""
    routings: dict[str, set[str]] = {}
    for row in served.rows("SELECT submission_id, routing FROM criterion_score WHERE run_id = ?",
                           served.run_id):
        routings.setdefault(row["submission_id"], set()).add(row["routing"])
    return {sub for sub, seen in routings.items() if seen == {"auto"}}


def test_tc_console_119_the_sample_is_drawn_from_this_runs_auto_accepted_grades(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-119, the population, size and run-scoping arm (validity store)."""
    from tests.support.validity_seed import ATOMIC, HOLISTIC, ValidityStore

    world = ValidityStore(tmp_path / "v")
    try:
        a = world.administer("c-a", {ATOMIC: ("pass",) * 18, HOLISTIC: ("B2",) * 18})
        b = world.administer("c-b", {ATOMIC: ("pass",) * 12, HOLISTIC: ("B3",) * 12})
        names = name_all(world, a)
        name_all(world, b, offset=len(names))
        mixed = a.submission(17)
        for administration in (a, b):
            with world.store.cohort(administration.cohort_id).transaction() as tx:
                tx.execute("UPDATE criterion_score SET routing = 'auto' WHERE run_id = :r",
                           r=administration.run_id)
        with world.store.cohort(a.cohort_id).transaction() as tx:
            tx.execute("UPDATE criterion_score SET routing = 'queued' WHERE run_id = :r AND "
                       "submission_id = :s AND criterion_id = :c", r=a.run_id, s=mixed,
                       c=HOLISTIC)
        with served_validity(world, a, monkeypatch, network_guard) as served:
            population = _auto_population(served)
            assert len(population) == 17 and mixed not in population, "fixture"
            document = _sample(served)
            drawn = [s["submission_id"] for s in document["students"]]
            low, high = WHOLE_GRADE_RANGE
            assert low <= len(drawn) <= high and document["drawn_count"] == len(drawn), drawn
            assert len(set(drawn)) == len(drawn), "a paper drawn twice"
            assert set(drawn) <= population, (
                f"drawn outside the auto-accepted population: {set(drawn) - population}")
            assert mixed not in drawn, "a paper with a reviewable line was drawn"
            assert not set(drawn) & set(b.run.submissions), "another class's papers were drawn"
            assert document["short_sample_note"] is None, document["short_sample_note"]
            assert document["population_note"] == POPULATION_NOTE
            assert all(s["full_name"] == names[s["submission_id"]] for s in document["students"])
            assert all("grade" not in s for s in document["students"]), (
                "a grade letter without a boundary table")
            assert [s["submission_id"] for s in _sample(served)["students"]] == drawn, (
                "a second read is a different draw")
    finally:
        world.close()


def test_tc_console_119_fewer_than_ten_students_and_the_answers(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-119 on ENG7: the short sample with its sentence, each student as received,
    the population note, the two answers and the completion order."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        names = served.names()
        auto = sorted(names)[:2]
        for sub in auto:
            served.execute("UPDATE criterion_score SET routing = 'auto' WHERE run_id = ? AND "
                           "submission_id = ?", served.run_id, sub)
        assert _auto_population(served) == set(auto), "fixture"
        document = _sample(served)
        assert sorted(s["submission_id"] for s in document["students"]) == auto
        assert document["drawn_count"] == 2
        note = document["short_sample_note"] or ""
        assert "2" in note and "10" in note and "15" in note, note
        assert document["population_note"] == POPULATION_NOTE

        cells = served.judged_cells()
        grades = {row["submission_id"]: row for row in served.rows(
            "SELECT * FROM submission_grade WHERE run_id = ? AND is_current = 1", served.run_id)}
        for student in document["students"]:
            sub = student["submission_id"]
            assert student["full_name"] == names[sub]
            assert student["total"] == grades[sub]["total"], (student["total"], grades[sub])
            assert student.get("grade") == grades[sub]["grade"] and student["grade"], student
            assert student["narrative"], f"{sub}: no narrative"
            assert student["questions"], f"{sub}: no questions"
            seen_lines = set()
            for question in student["questions"]:
                lines = question["lines"]
                assert lines, question
                stored_points = sum(float(cells[(sub, line["criterion_id"])]["points"] or 0)
                                    for line in lines)
                assert question["points_awarded"] == pytest.approx(stored_points), question
                for line in lines:
                    assert line["level"] == cells[(sub, line["criterion_id"])]["band"], line
                    seen_lines.add(line["criterion_id"])
            assert seen_lines == {c for (s, c) in cells if s == sub}, seen_lines

        def counts() -> tuple[int, int]:
            audits = served.rows("SELECT COUNT(*) AS n FROM audit_record", tier="durable")[0]["n"]
            labels = served.rows("SELECT COUNT(*) AS n FROM label", tier="durable")[0]["n"]
            return audits, labels

        audits, labels = counts()
        served.dispatched("whole-grade confirm", run_id=served.run_id)
        assert counts() == (audits + 1, labels), "confirm: not exactly one audit row, no label"
        status, _repeat = served.action("whole-grade confirm", run_id=served.run_id)
        assert status == 200 and counts() == (audits + 1, labels), "a repeat wrote a row"
        served.dispatched("whole-grade skip", run_id=served.run_id)
        assert counts() == (audits + 2, labels), "skip: not exactly one audit row, no label"
        recorded = served.rows("SELECT profile_summary FROM audit_record ORDER BY rowid DESC "
                               "LIMIT 2", tier="durable")
        assert all(served.run_id in row["profile_summary"] for row in recorded), recorded

        status, monitor = served.get("/api/v1/monitor", run_id=served.run_id)
        assert status == 200, monitor
        routes = [step["route"] for step in monitor["next"]]
        assert "/results/whole-grade" in routes and "/review/blind" in routes, routes
        assert routes.index("/review/blind") < routes.index("/results/whole-grade") < \
            routes.index("/results"), routes
