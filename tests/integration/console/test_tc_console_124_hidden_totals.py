"""Validity T18 (issue #903): TC-CONSOLE-124 (FR-CONSOLE-89 r2, CT-CONSOLE-56 amended; D6,
ADR-62) — the drawn students' totals are held back while the draw is open. Rung 3, over HTTP.

**World.** ENG7 graded by the console's own `start run`. Before the draw opens, every line of
the first student is routed `auto`, so M-REVIEW's pool is the other three students' twelve
cells and the draw (15 to 25, smaller when the pool is) takes all twelve: three students have
drawn lines and one has none, the positive control on every run.

**Asserted.**
- While open, on Results and the student read: each drawn student carries
  `hidden_until_blind = true` and no total, grade or range figure (`total`, `total_points`,
  `grade`, `score_low`, `score_high`, `grade_low`, `grade_high`, `boundary_at_risk`); the
  undrawn student's total and grade are served and equal the stored grade row.
- The class-level per-question distribution (`question_stats`) is complete: identical to the
  one served before the draw opened.
- The CSV and XLSX exports carry every student's mark, equal to the stored totals (R60).
- After Finish, every total is served, equal to the stored grade row.

**Overlap.** TC-CONSOLE-116 (`test_tc_console_108_116_held_back.py`, T8) already asserts the
hidden form, the exports and the after-Finish arm on a world where every student is drawn. What
this case adds is the undrawn positive control, the per-field census of the range and boundary
fields, and the class distribution. Reported in the PR as a duplication of the shared arms.

**Mutations (run by hand, recorded in the PR):** `total` taken out of `held_back.TOTAL_KEYS`
-> red.
"""

from __future__ import annotations

import csv
import io

import pytest

from tests.support.eng7_console import Eng7Console, eng7_console

pytestmark = pytest.mark.integration

#: A student's figures that `total - visible lines` would reveal a drawn line through, with
#: FR-CONSOLE-94's range and boundary fields (spelled here, not imported from the code).
HIDDEN_FIGURES = ("total", "total_points", "grade", "grade_letter", "range", "score_low",
                  "score_high", "grade_low", "grade_high", "boundary_at_risk")


def _blank(value) -> bool:
    return value in (None, "", [], {})


def _students(served: Eng7Console) -> tuple[dict, list[tuple[str, dict]]]:
    status, screen = served.get("/api/v1/results/screen", run_id=served.run_id)
    assert status == 200, screen
    documents = [("results", s) for s in screen["students"]]
    for sub in sorted(served.names()):
        status, detail = served.get("/api/v1/results/student-detail", run_id=served.run_id,
                                    submission_id=sub)
        assert status == 200, detail
        documents.append(("student read", detail))
    return screen, documents


def _stored_totals(served: Eng7Console) -> dict[str, dict]:
    return {row["submission_id"]: row for row in served.rows(
        "SELECT submission_id, total, grade FROM submission_grade WHERE run_id = ? AND "
        "is_current = 1", served.run_id)}


def test_tc_console_124_drawn_students_totals_are_held_back_while_the_draw_is_open(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-124 (see the module docstring)."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        subs = sorted(served.names())
        kept = subs[0]
        served.execute("UPDATE criterion_score SET routing = 'auto' WHERE run_id = ? AND "
                       "submission_id = ?", served.run_id, kept)
        before, _documents = _students(served)

        read = served.open_draw()
        drawn = served.drawn_cells()
        hidden = {sub for sub, _crit in drawn}
        assert hidden == set(subs) - {kept}, f"fixture: drawn students {sorted(hidden)}"
        stored = _stored_totals(served)
        assert all(stored[s]["total"] for s in subs), f"fixture: a zero total {stored}"

        screen, documents = _students(served)
        problems = []
        for where, student in documents:
            sub = student["submission_id"]
            if sub in hidden:
                if student.get("hidden_until_blind") is not True:
                    problems.append(f"{where} {sub}: not hidden_until_blind")
                shown = {k: student[k] for k in HIDDEN_FIGURES
                         if k in student and not _blank(student[k])}
                if shown:
                    problems.append(f"{where} {sub}: figures served while open {shown}")
            else:
                if student.get("hidden_until_blind") or student.get("total") is None or \
                        float(student["total"]) != pytest.approx(float(stored[sub]["total"])) \
                        or student.get("grade") != stored[sub]["grade"]:
                    problems.append(f"{where} {sub} (undrawn): total {student.get('total')!r} "
                                    f"grade {student.get('grade')!r}, stored {stored[sub]}")
        assert not problems, "while the draw is open:\n  " + "\n  ".join(problems)
        assert screen["question_stats"] == before["question_stats"], (
            "the class distribution changed when the draw opened", before["question_stats"],
            screen["question_stats"])

        # R60: the exports carry every total.
        status, text = served.get("/api/v1/results/export", run_id=served.run_id, format="csv")
        assert status == 200, text
        header, *rows = list(csv.reader(io.StringIO(text.strip())))
        marks = {dict(zip(header, r))["submission_id"]: dict(zip(header, r))["mark"]
                 for r in rows}
        assert set(marks) == set(subs), marks
        for sub, mark in marks.items():
            assert float(mark) == pytest.approx(float(stored[sub]["total"])), (sub, mark)
        status, body = served.raw_get(f"/api/v1/results/workbook?run_id={served.run_id}")
        assert status == 200
        from openpyxl import load_workbook

        sheet = load_workbook(io.BytesIO(body), read_only=True).worksheets[0]
        table = list(sheet.iter_rows(values_only=True))
        columns = list(table[0])
        listed = {r[columns.index("submission_id")]: r[columns.index("mark")] for r in table[1:]}
        assert set(listed) == set(subs), listed
        for sub, mark in listed.items():
            assert float(mark) == pytest.approx(float(stored[sub]["total"])), (sub, mark)

        # After Finish, every total is served.
        for seat in read["seats"]:
            served.dispatched("blind-sample draft", run_id=served.run_id,
                              seat_id=seat["seat_id"], band=seat["bands"][0]["name"])
        served.dispatched("blind-sample finish", run_id=served.run_id)
        stored = _stored_totals(served)
        _screen, documents = _students(served)
        for where, student in documents:
            sub = student["submission_id"]
            assert not student.get("hidden_until_blind"), (where, sub)
            assert student.get("total") is not None and float(student["total"]) == \
                pytest.approx(float(stored[sub]["total"])), (where, sub, student.get("total"))
            assert student.get("grade") == stored[sub]["grade"], (where, sub)
