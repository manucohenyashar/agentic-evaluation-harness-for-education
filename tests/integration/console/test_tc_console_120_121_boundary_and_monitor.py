"""Validity T18 (issue #903): M-GRADE's boundary fields as stored (TC-CONSOLE-120) and the
monitor's position (TC-CONSOLE-121). Rung 3, over HTTP.

| Case | What is asserted |
|---|---|
| TC-CONSOLE-120 (FR-CONSOLE-94, CT-CONSOLE-59) | ENG7 (boundary table `pass = 6`, `"not yet" = 0`) with its current `submission_grade` rows rewritten: one student at risk across the pass line (odd values M-GRADE would not compute from these cells), the rest not at risk with a one-point range. The results read and the student read carry `boundary_at_risk`, `score_low`, `score_high` equal to the stored row, `grade_low`/`grade_high` equal to the letters the spec's table gives those ends (worked in the test), and `boundary_risk_count = 1`. No-boundary twin (the validity store, no `[grades]`): `grade_low`/`grade_high` absent (not null), `score_low`/`score_high` and `boundary_at_risk` equal to the stored row |
| TC-CONSOLE-121 (FR-CONSOLE-95) | the monitor read's `stage`, `criterion_position {index, total, label}` and `judge_position {index, total}` equal M-ORCH's progress report for the run (read in the test through a report-only `Orchestrator`), on the finished run and again with the later criteria's scoring units put back to `pending`; census: no key names a student or a submission, and no paper's id, ref or name appears anywhere in the answer |

**Departure (disclosed in the PR).** The plan's no-boundary arm expects "the points range
present". M-GRADE stores a null range on a student who is not at risk, and without a boundary
table no student is at risk (FR-GRADE-05), so the twin's range is asserted equal to the stored
row: a seeded at-risk row's range is served, a not-at-risk row's null range is served null.

**Mutations (run by hand, recorded in the PR):** `score_low` dropped from the served boundary
fields -> 120 red.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

import pytest

from tests.support.console_r2_world import letter_for, served_validity
from tests.support.eng7_console import eng7_console

pytestmark = pytest.mark.integration

FIELDS = ("boundary_at_risk", "score_low", "score_high")


def _set_grade(served: Any, sub: str, at_risk: int, low: float | None,
               high: float | None) -> None:
    """Mint a new current revision of the student's grade row carrying these boundary fields
    (the ledger is append-only, FR-GRADE-12: the old revision is superseded, never edited)."""
    (row,) = served.rows("SELECT * FROM submission_grade WHERE run_id = ? AND "
                         "submission_id = ? AND is_current = 1", served.run_id, sub)
    served.execute("UPDATE submission_grade SET is_current = 0, superseded_at = ? WHERE "
                   "run_id = ? AND submission_id = ? AND revision = ?",
                   "2026-11-24T00:00:00+00:00", served.run_id, sub, row["revision"])
    row.update(revision=row["revision"] + 1, is_current=1, superseded_at=None,
               boundary_at_risk=at_risk, score_low=low, score_high=high)
    served.execute(f"INSERT INTO submission_grade ({', '.join(row)}) "
                   f"VALUES ({', '.join('?' for _ in row)})", *row.values())


def _stored(served: Any) -> dict[str, dict]:
    return {row["submission_id"]: row for row in served.rows(
        "SELECT * FROM submission_grade WHERE run_id = ? AND is_current = 1", served.run_id)}


def _reads(served: Any) -> tuple[dict, list[tuple[str, dict]]]:
    status, screen = served.get("/api/v1/results/screen", run_id=served.run_id)
    assert status == 200, screen
    documents = [("results", student) for student in screen["students"]]
    for student in screen["students"]:
        status, detail = served.get("/api/v1/results/student-detail", run_id=served.run_id,
                                    submission_id=student["submission_id"])
        assert status == 200, detail
        documents.append(("student detail", detail))
    return screen, documents


def test_tc_console_120_boundary_fields_are_served_as_stored(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-120 on ENG7 (with a boundary table)."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        subs = sorted(served.names())
        at_risk = subs[1]
        for sub in subs:
            if sub == at_risk:
                _set_grade(served, sub, 1, 5.25, 6.75)  # spans the pass line (6)
            else:
                _set_grade(served, sub, 0, 2.5, 3.5)
        stored = _stored(served)
        screen, documents = _reads(served)
        assert screen["boundary_risk_count"] == 1, screen["boundary_risk_count"]
        assert len(documents) == 2 * len(subs)
        problems = []
        for where, student in documents:
            row = stored[student["submission_id"]]
            for key in FIELDS:
                if key not in student or student[key] != row[key]:
                    problems.append(f"{where} {student['submission_id']} {key}: "
                                    f"served {student.get(key, '<absent>')!r}, stored {row[key]!r}")
            for key, end in (("grade_low", "score_low"), ("grade_high", "score_high")):
                if student.get(key, "<absent>") != letter_for(row[end]):
                    problems.append(f"{where} {student['submission_id']} {key}: "
                                    f"{student.get(key, '<absent>')!r}, the table gives "
                                    f"{letter_for(row[end])!r}")
        assert not problems, "\n  ".join(problems)
        risky = [s for w, s in documents if s["submission_id"] == at_risk]
        assert all(s["grade_low"] != s["grade_high"] for s in risky), (
            "fixture: the at-risk range does not cross a grade line")


def test_tc_console_120_without_a_boundary_table_no_letters(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-120's no-boundary twin (the validity store declares no `[grades]`)."""
    from tests.support.validity_seed import ATOMIC, HOLISTIC, ValidityStore

    world = ValidityStore(tmp_path / "v")
    try:
        administration = world.administer("c-twin", {ATOMIC: ("pass",) * 4,
                                                     HOLISTIC: ("B2",) * 4})
        with served_validity(world, administration, monkeypatch, network_guard) as served:
            seeded = administration.submission(0)
            _set_grade(served, seeded, 1, 1.75, 4.25)
            stored = _stored(served)
            screen, documents = _reads(served)
            assert screen["boundary_risk_count"] == 1, screen["boundary_risk_count"]
            for where, student in documents:
                sub = student["submission_id"]
                assert "grade_low" not in student and "grade_high" not in student, (
                    where, sub, student.get("grade_low"), student.get("grade_high"))
                for key in FIELDS:
                    assert key in student and student[key] == stored[sub][key], (
                        where, sub, key, student.get(key), stored[sub][key])
            assert [(s["score_low"], s["score_high"]) for _w, s in documents
                    if s["submission_id"] == seeded] == [(1.75, 4.25)] * 2
    finally:
        world.close()


# --- TC-CONSOLE-121 ------------------------------------------------------------------------


def _keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def _expected_position(root: Any, run_id: str, questions: dict[str, str]) -> dict:
    """M-ORCH's progress report for the run, read in this thread through a report-only
    orchestrator over a second store handle on the same data folder."""
    import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ  # noqa: F401,E401
    import aeh.judge, aeh.orch, aeh.pkg, aeh.review, aeh.synth  # noqa: F401,E401
    from aeh.orch import Orchestrator
    from aeh.store import open_store

    store = open_store(root)
    try:
        report = Orchestrator(store).progress(run_id)
    finally:
        store.close()
    axis = sorted({str(c) for _s, c, _j in report.by_unit if c is not None})
    index = int(report.criterion_index)
    criterion = axis[index - 1] if 0 < index <= len(axis) else None
    return {
        "stage": str(report.stage),
        "criterion_position": {"index": index, "total": int(report.criterion_total),
                               "label": questions.get(criterion) if criterion else None},
        "judge_position": {"index": int(report.judge_index), "total": int(report.judge_total)},
    }


def _position(monitor: dict) -> dict:
    return {key: monitor.get(key) for key in ("stage", "criterion_position", "judge_position")}


def test_tc_console_121_the_monitor_serves_m_orchs_position_and_no_student(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-121 (see the module docstring)."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        status, screen = served.get("/api/v1/results/screen", run_id=served.run_id)
        assert status == 200, screen
        questions = {line["criterion_id"]: line["question_id"]
                     for student in screen["students"] for line in student["criteria"]}
        identities = set()
        for row in served.rows("SELECT s.submission_id, s.student_ref, r.full_name FROM "
                               "submission s LEFT JOIN roster r ON r.student_ref = s.student_ref"):
            identities |= {v for v in row.values() if v}

        seen = []
        for phase in ("finished", "mid-run"):
            if phase == "mid-run":
                # The later criteria's scoring back to pending, and a second arm on the panel
                # (dev-ci has one judge, so without it index == total and a judge-position
                # mix-up could not show).
                served.execute("UPDATE work_unit SET status = 'pending' WHERE run_id = ? AND "
                               "stage = 'score' AND criterion_id IN ('C2', 'C3')", served.run_id)
                (run,) = served.rows("SELECT panel_config FROM run WHERE run_id = ?",
                                     served.run_id)
                arms = json.loads(run["panel_config"])["arms"]
                served.execute("UPDATE run SET panel_config = ? WHERE run_id = ?",
                               json.dumps({"arms": [*arms, "second-grader"]}), served.run_id)
            status, monitor = served.get("/api/v1/monitor", run_id=served.run_id)
            assert status == 200, monitor
            expected = _expected_position(served.root, served.run_id, questions)
            assert _position(monitor) == expected, (phase, _position(monitor), expected)
            assert monitor["criterion_position"]["label"], (phase, monitor["criterion_position"])
            seen.append(json.dumps(_position(monitor), sort_keys=True))
            named = [k for k in _keys(monitor) if "student" in k.lower()
                     or "submission" in k.lower()]
            assert not named, f"{phase}: keys naming a student or submission: {named}"
            text = json.dumps(monitor)
            leaked = sorted(i for i in identities if i in text)
            assert not leaked, f"{phase}: the monitor names papers: {leaked}"
        assert seen[0] != seen[1], (
            "fixture: the position did not move, so the equality proves little: " + seen[0])
