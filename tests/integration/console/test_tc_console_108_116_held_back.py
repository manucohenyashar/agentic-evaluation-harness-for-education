"""Validity T8 (issue #901): what a drawn line says, held back while the draw is open.

| Case | What is asserted |
|---|---|
| TC-CONSOLE-108 (CT-CONSOLE-56, FR-CONSOLE-89 r2) | with the draw open, every GET in `API_ROUTES` (exports and the seats read aside) and the legacy rollup, review and student pages: no node about a drawn (submission, criterion) carries its band, points, reason, quotes, graders or feedback; no drawn cell's work id (its journal records) appears in any answer; a question whose only line is drawn shows no points. Positive controls: the one undrawn line shows its band, its single-line question its points, and its AI calls are listed |
| TC-CONSOLE-116 (FR-CONSOLE-89 r2) | while open, results and student detail carry `hidden_until_blind = true` on each drawn line and on each drawn student's total, and the exports carry every mark; after Finish, and separately after Skip, every line and total is shown |

**World.** The ENG7 class graded by the console's own `start run` (`tests/support/eng7_console.py`),
rung 3 over HTTP. One cell, (first student, `C3`), is routed `auto` before the draw opens, so
M-REVIEW draws exactly the other fifteen (it draws only queued and provisional cells) and the
positive control is the same cell on every run. `Q3` holds only `C3`, so its points are the
single-line-question control.

**Written ahead: no** (S11/S12/S13 merged; see the PR).

**Departures, following the design delta (D6, ADR-62).** The plan's TC-CONSOLE-108 inference
arm says "the student total stays" and TC-CONSOLE-116 "the totals include the drawn points".
FR-CONSOLE-89 r2 hides a drawn student's total, grade and range while the draw is open, so these
cases assert the hidden form, and the CSV and XLSX exports carrying every mark (R60).
TC-CONSOLE-116's "the export carries the drawn bands": no export carries per-line bands (the
CSV and the workbook carry the mark and grade per student), so the export arm asserts the marks;
the per-line arm is reported in the PR as not implementable as written.

**Mutations (run by hand, recorded in the PR).** `AI_CALLS_READ` taken out of the drop list in
`HELD_BACK_READS` -> 108 red (a drawn cell's work id is served). `points_awarded` taken out of
`held_back.QUESTION_KEYS` -> 108's per-question arm red. The legacy rollup's and student page's
hold-backs in `results_screens.py` bypassed -> 108's legacy-page arm red (the rollup served
`total 3.0`, the student page the narrative).
"""

from __future__ import annotations

import io
import re
from typing import Any, Iterator

import pytest

from aeh.console.api import API_ROUTES
from tests.support.eng7_console import Eng7Console, eng7_console

pytestmark = pytest.mark.integration

#: The routes outside the census, and why: the exports carry every mark by design
#: (FR-CONSOLE-89, R60); the seats read is the sample itself (TC-CONSOLE-107's allowlist); the
#: ask read calls the Q&A model, and the readable package export is the blank test.
EXCLUDED = {
    "/api/v1/results/export", "/api/v1/results/workbook", "/api/v1/packages/readable",
    "/api/v1/blind-seats", "/api/v1/help/ask",
}

#: The teacher-facing reads that must answer (a refusal would pass any absence check).
MUST_ANSWER = {
    "/api/v1/results/class", "/api/v1/results/student", "/api/v1/results/screen",
    "/api/v1/results/student-detail", "/api/v1/review-queue", "/api/v1/ai-calls",
    "/api/v1/logs", "/api/v1/issues", "/api/v1/past-tests", "/api/v1/class-roster",
    "/api/v1/monitor", "/api/v1/context", "/api/v1/results/validity",
}

#: What a line says that grading decided, by key (spelled here, not imported from the code).
LINE_GRADING_KEY = re.compile(
    r"band|points|reason|rationale|cited|quote|evidence|feedback|narrative|verdict|graders|"
    r"panel|confidence|^text$|^flag$|^routing$")

#: Package data, not a decision: the scale a line is marked on.
SCALE_KEYS = {"levels", "bands", "score_levels", "scales", "options", "request"}

#: A student's figures that `total - visible lines` would reveal a drawn line through.
TOTAL_KEYS = {"total", "grade", "grade_letter", "total_points", "range", "total_range",
              "grade_range", "plausible_range"}

KEPT_CELL_CRITERION = "C3"
KEPT_CELL_QUESTION = "Q3"


def _blank(value: Any) -> bool:
    return value in (None, "", [], {})


class Context:
    """Maps the ways a read names a student to the submission."""

    def __init__(self, served: Eng7Console) -> None:
        rows = served.rows("SELECT s.submission_id, s.student_ref, r.full_name FROM submission s "
                           "LEFT JOIN roster r ON r.student_ref = s.student_ref")
        self.by_ref = {row["student_ref"]: row["submission_id"] for row in rows}
        self.by_name = {row["full_name"]: row["submission_id"] for row in rows if row["full_name"]}

    def submission(self, node: dict, inherited: str | None) -> str | None:
        for key in ("submission_id",):
            if isinstance(node.get(key), str) and node[key].startswith("sub-"):
                return node[key]
        if isinstance(node.get("student_ref"), str) and node["student_ref"] in self.by_ref:
            return self.by_ref[node["student_ref"]]
        for key in ("full_name", "student_name", "student"):
            if isinstance(node.get(key), str) and node[key] in self.by_name:
                return self.by_name[node[key]]
        return inherited


def _nodes(value: Any, ctx: Context, sub: str | None = None,
           crit: str | None = None) -> Iterator[tuple[dict, str | None, str | None]]:
    """Every dict of a JSON answer with the (submission, criterion) it is about."""
    if isinstance(value, list):
        for item in value:
            yield from _nodes(item, ctx, sub, crit)
    elif isinstance(value, dict):
        sub = ctx.submission(value, sub)
        if isinstance(value.get("criterion_id"), str):
            crit = value["criterion_id"]
        yield value, sub, crit
        for key, item in value.items():
            if key not in SCALE_KEYS:
                yield from _nodes(item, ctx, sub, crit)


def _line_leaks(answer: Any, ctx: Context, drawn: set[tuple[str, str]],
                bands: dict[tuple[str, str], str]) -> list[str]:
    found = []
    for node, sub, crit in _nodes(answer, ctx):
        if (sub, crit) not in drawn:
            continue
        for key, value in node.items():
            if key in SCALE_KEYS or key == "hidden_until_blind":
                continue
            if LINE_GRADING_KEY.search(key) and not _blank(value):
                found.append(f"({sub}, {crit}) {key}={value!r}")
            elif isinstance(value, str) and value == bands[(sub, crit)] and key != "state":
                found.append(f"({sub}, {crit}) {key} names the drawn band {value!r}")
    return found


def _question_points_leaks(answer: Any, ctx: Context,
                           fully_drawn: set[tuple[str, str]]) -> list[str]:
    found = []
    for node, sub, _crit in _nodes(answer, ctx):
        question = node.get("question_id")
        if "criterion_id" in node or (sub, question) not in fully_drawn:
            continue
        for key in ("points_awarded", "points", "awarded_points"):
            if not _blank(node.get(key)):
                found.append(f"({sub}, {question}) {key}={node[key]!r}")
    return found


def _total_leaks(answer: Any, ctx: Context, drawn_students: set[str]) -> list[str]:
    found = []
    for node, sub, crit in _nodes(answer, ctx):
        if crit is not None or "question_id" in node or sub not in drawn_students:
            continue
        if ctx.submission(node, None) != sub:
            continue  # only the student's own record, not a child of it
        for key in TOTAL_KEYS & set(node):
            if not _blank(node[key]):
                found.append(f"{sub} {key}={node[key]!r}")
    return found


#: The stand-in's narrative text (`tests/support/eng7_sample.py`), the same for every student.
STAND_IN_NARRATIVE = "The answer names some of what the question asks for."


def _legacy_leaks(answers: dict[str, Any], drawn: set[tuple[str, str]],
                  kept: tuple[str, str]) -> list[str]:
    """The server-rendered pages, checked page by page: the rollup holds back every drawn
    student's grade line (total, grade, range: D6), and the student page of a student whose
    every line is drawn shows none of the paper's narrative."""
    import html as html_lib

    problems = []
    rollup = html_lib.unescape(answers["/runs/{id}/rollup"])
    for sub in sorted({s for s, _c in drawn}):
        match = re.search(r'<div data-role="grade"([^>]*)><p>' + re.escape(sub) +
                          r":([^<]*)</p>", rollup)
        if match is None:
            problems.append(f"rollup: no grade line for {sub}")
            continue
        attrs, text = match.groups()
        if 'data-hidden-until-blind="true"' not in attrs or re.search(
                r"total|range|grade|\d", text):
            problems.append(f"rollup: {sub}'s grade line is served: {text.strip()!r}")
    for sub in sorted({s for s, _c in drawn} - {kept[0]}):
        page = html_lib.unescape(answers[f"/students/{sub}"])
        if STAND_IN_NARRATIVE in page:
            problems.append(f"/students/{sub}: the drawn paper's narrative is shown")
    return problems


def _keep_one_cell(served: Eng7Console) -> tuple[str, str]:
    """Route (first student, C3) `auto` before the draw opens, so it is never drawn."""
    first = sorted(served.names())[0]
    served.execute("UPDATE criterion_score SET routing = 'auto' WHERE run_id = ? AND "
                   "submission_id = ? AND criterion_id = ?", served.run_id, first,
                   KEPT_CELL_CRITERION)
    return first, KEPT_CELL_CRITERION


def _questions(served: Eng7Console) -> dict[str, str]:
    """criterion -> question, from the package as the run froze it."""
    status, screen = served.get("/api/v1/results/screen", run_id=served.run_id)
    assert status == 200, screen
    return {line["criterion_id"]: line["question_id"]
            for student in screen["students"] for line in student["criteria"]}


def _drive(served: Eng7Console, submissions: list[str]) -> dict[str, Any]:
    """Every GET of the route table with real parameters, plus the legacy pages."""
    refs = {row["submission_id"]: row["student_ref"]
            for row in served.rows("SELECT submission_id, student_ref FROM submission")}
    base = {"run_id": served.run_id, "cohort_id": served.cohort_id,
            "package_version": served.package_version,
            "package_version_id": served.package_version}
    answers: dict[str, Any] = {}
    for route in API_ROUTES:
        if route.method != "GET" or route.path in EXCLUDED:
            continue
        path = (route.path.replace("{job_id}", served.run_id)
                .replace("{manual_id}", "teacher-guide"))
        per_student = "student" in path or path.endswith("/ai-calls")
        variants = ([{**base, "submission_id": s, "student_ref": refs[s], "student": refs[s]}
                     for s in submissions] if per_student else [base])
        for index, query in enumerate(variants):
            status, body = served.get(path, **query)
            if route.path in MUST_ANSWER:
                assert status == 200, f"{path} answered {status}: {body!r}"
            answers[f"{path}#{index}"] = body
    for page in ("rollup", "review", "monitor", "sample", "blind"):
        status, body = served.get(f"/runs/{served.run_id}/{page}")
        assert status == 200, (page, status)
        answers[f"/runs/{{id}}/{page}"] = body
    for sub in submissions:
        for key in (sub, refs[sub]):
            status, body = served.get(f"/students/{key}")
            assert status == 200, (key, status)
            answers[f"/students/{key}"] = body
    return answers


def test_tc_console_108_no_teacher_facing_read_says_what_a_drawn_line_says(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-108, the census over the route table with the draw open (see the module
    docstring for the oracle, the controls and the mutations)."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        kept = _keep_one_cell(served)
        questions = _questions(served)
        served.open_draw()
        drawn = served.drawn_cells()
        cells = served.judged_cells()
        assert kept not in drawn and len(drawn) == len(cells) - 1, (
            f"fixture: the draw holds {len(drawn)} of {len(cells)} cells, kept {kept}")
        bands = {cell: row["band"] for cell, row in cells.items()}
        by_question: dict[tuple[str, str], set[str]] = {}
        for sub, crit in cells:
            by_question.setdefault((sub, questions[crit]), set()).add(crit)
        fully_drawn = {key for key, crits in by_question.items()
                       if all((key[0], c) in drawn for c in crits)}
        assert any(q in ("Q2", "Q3") for _s, q in fully_drawn), fully_drawn
        drawn_work = {row["work_id"] for row in served.rows(
            "SELECT work_id, submission_id, criterion_id FROM work_unit WHERE run_id = ?",
            served.run_id) if (row["submission_id"], row["criterion_id"]) in drawn}
        kept_work = {row["work_id"] for row in served.rows(
            "SELECT work_id FROM work_unit WHERE run_id = ? AND submission_id = ? AND "
            "criterion_id = ? AND stage = 'score'", served.run_id, *kept)}
        assert drawn_work and kept_work, "fixture: no work units"

        ctx = Context(served)
        answers = _drive(served, sorted(served.names()))
        problems: list[str] = []
        for where, answer in answers.items():
            text = answer if isinstance(answer, str) else repr(answer)
            for work_id in drawn_work:
                if work_id in text:
                    problems.append(f"{where}: a journal record of a drawn cell ({work_id})")
            if isinstance(answer, str):
                for sub, crit in drawn:
                    if f"{sub} / {crit}" in answer:
                        problems.append(f"{where}: the drawn item {sub} / {crit} is listed")
                continue
            problems += [f"{where}: {leak}" for leak in _line_leaks(answer, ctx, drawn, bands)]
            problems += [f"{where}: per-question points {leak}"
                         for leak in _question_points_leaks(answer, ctx, fully_drawn)]
            problems += [f"{where}: a drawn student's total (D6) {leak}"
                         for leak in _total_leaks(answer, ctx, {s for s, _c in drawn})]
        problems += _legacy_leaks(answers, drawn, kept)
        assert not problems, "drawn lines readable while the draw is open:\n  " + \
            "\n  ".join(sorted(set(problems))[:60])

        # Positive controls: the undrawn line, its single-line question and its AI calls.
        status, detail = served.get("/api/v1/results/student-detail", run_id=served.run_id,
                                    submission_id=kept[0])
        assert status == 200, detail
        (line,) = [item for item in detail["criteria"] if item["criterion_id"] == kept[1]]
        assert line.get("criterion_band") == bands[kept] and not line.get("hidden_until_blind"), (
            f"the undrawn line is hidden too, so the census proves nothing: {line}")
        (question,) = [item for item in detail["questions"]
                       if item["question_id"] == KEPT_CELL_QUESTION]
        assert question["points_awarded"] is not None, (
            f"the undrawn single-line question shows no points: {question}")
        calls = repr(answers["/api/v1/ai-calls#" + str(sorted(served.names()).index(kept[0]))])
        assert any(work_id in calls for work_id in kept_work), (
            "the undrawn cell's AI calls are not listed, so the journal arm proves nothing")


def _hidden_state(served: Eng7Console, drawn: set[tuple[str, str]]) -> list[str]:
    """Everything wrong about the open-draw form of results and student detail."""
    problems = []
    students = {sub for sub, _crit in drawn}
    status, screen = served.get("/api/v1/results/screen", run_id=served.run_id)
    assert status == 200, screen
    documents = [("results", student) for student in screen["students"]]
    for sub in sorted(served.names()):
        status, detail = served.get("/api/v1/results/student-detail", run_id=served.run_id,
                                    submission_id=sub)
        assert status == 200, detail
        documents.append(("student detail", detail))
    for where, student in documents:
        sub = student["submission_id"]
        for line in student["criteria"]:
            if (sub, line["criterion_id"]) in drawn and line.get("hidden_until_blind") is not True:
                problems.append(f"{where} {sub} {line['criterion_id']}: not hidden_until_blind")
        if sub in students:
            if student.get("hidden_until_blind") is not True:
                problems.append(f"{where} {sub}: the total is not hidden_until_blind (D6)")
            shown = {k: student[k] for k in TOTAL_KEYS & set(student) if not _blank(student[k])}
            if shown:
                problems.append(f"{where} {sub}: total figures served {shown}")
    return problems


def _all_shown(served: Eng7Console, cells: dict[tuple[str, str], dict]) -> list[str]:
    problems = []
    status, screen = served.get("/api/v1/results/screen", run_id=served.run_id)
    assert status == 200, screen
    documents = [("results", s) for s in screen["students"]]
    for sub in sorted(served.names()):
        status, detail = served.get("/api/v1/results/student-detail", run_id=served.run_id,
                                    submission_id=sub)
        documents.append(("student detail", detail))
    for where, student in documents:
        sub = student["submission_id"]
        if student.get("hidden_until_blind") or student.get("total") is None:
            problems.append(f"{where} {sub}: total still held back {student.get('total')!r}")
        for line in student["criteria"]:
            cell = (sub, line["criterion_id"])
            if line.get("hidden_until_blind") or line.get("criterion_band") != cells[cell]["band"]:
                problems.append(f"{where} {cell}: band {line.get('criterion_band')!r} "
                                f"(stored {cells[cell]['band']!r}), "
                                f"hidden={line.get('hidden_until_blind')!r}")
    return problems


def _export_marks(served: Eng7Console) -> dict[str, str]:
    status, text = served.get("/api/v1/results/export", run_id=served.run_id, format="csv")
    assert status == 200, text
    header, *rows = [line.split(",") for line in text.strip().splitlines()]
    return {dict(zip(header, row))["submission_id"]: dict(zip(header, row))["mark"]
            for row in rows}


@pytest.mark.parametrize("close", ["finish", "skip"])
def test_tc_console_116_held_back_while_open_and_shown_after_the_close(
        close, tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-116. While open: each drawn line and each drawn student's total carry
    `hidden_until_blind = true` in results and student detail, and the CSV and XLSX exports
    carry every student's mark. After Finish (or Skip): every line shows its stored band and
    every total is served."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        read = served.open_draw()
        drawn = served.drawn_cells()
        cells = served.judged_cells()
        assert len(drawn) == 15, f"fixture: {len(drawn)} drawn"

        problems = _hidden_state(served, drawn)
        assert not problems, "while the draw is open:\n  " + "\n  ".join(problems)
        marks = _export_marks(served)
        assert set(marks) == set(served.names()) and all(marks.values()), marks
        status, body = served.raw_get(f"/api/v1/results/workbook?run_id={served.run_id}")
        assert status == 200
        from openpyxl import load_workbook

        sheet = load_workbook(io.BytesIO(body), read_only=True).worksheets[0]
        rows = list(sheet.iter_rows(values_only=True))
        header = list(rows[0])
        listed = {row[header.index("submission_id")]: row[header.index("mark")]
                  for row in rows[1:]}
        assert set(listed) == set(marks) and all(v not in (None, "") for v in listed.values()), (
            f"the workbook, with the draw open, lacks marks: {listed}")

        if close == "finish":
            for seat in read["seats"]:
                served.dispatched("blind-sample draft", run_id=served.run_id,
                                  seat_id=seat["seat_id"], band=seat["bands"][-1]["name"])
            served.dispatched("blind-sample finish", run_id=served.run_id)
        else:
            served.dispatched("blind-sample skip", run_id=served.run_id)
        problems = _all_shown(served, cells)
        assert not problems, f"after {close}:\n  " + "\n  ".join(problems)

        # R60: the mark the export carried while the draw was open is the whole total, drawn
        # lines' points included (the stand-in marks C2 at its top band, so it is not 0).
        stored = {}
        for (sub, _crit), row in cells.items():
            stored[sub] = stored.get(sub, 0.0) + float(row["points"] or 0)
        status, screen = served.get("/api/v1/results/screen", run_id=served.run_id)
        shown = {s["submission_id"]: s["total_points"] for s in screen["students"]}
        for sub, mark in marks.items():
            assert stored[sub] > 0, f"fixture: {sub} has no points"
            assert shown[sub] == pytest.approx(stored[sub]), (sub, shown[sub], stored[sub])
            assert float(mark) == pytest.approx(float(listed[sub])), (sub, mark, listed[sub])
            assert float(mark) > 0, (
                f"{sub}: the export, with the draw open, carried mark {mark} without the drawn "
                f"lines' points ({stored[sub]} stored)")
