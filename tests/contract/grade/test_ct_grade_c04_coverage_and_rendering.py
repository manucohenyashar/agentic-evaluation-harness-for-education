"""`TC-GRADE-C04` — the five coverage fields, and rendering them alongside the grade (§6.11.14).

`CT-GRADE-04` (data): "every grade carries the five coverage fields
(`criteria_total`, `criteria_auto`, `criteria_reviewed`, `criteria_provisional`,
`criteria_missing`) and they sum consistently against `criteria_total`. Consumers
must render coverage alongside the grade — a grade shown without it is a stronger
claim than the system is making."

Three limbs:

- **field arithmetic** (rung 3, green): over a mixed cohort — auto-accepted,
  teacher-reviewed, provisional, and never-scored criteria in one run — every
  delivered grade's four classes sum to its `criteria_total`, and
  `criteria_total` equals the package's criterion count (the full-criterion list
  is what makes a no-row criterion counted missing rather than silently absent).
- **the module's own export** (rung 4, green): `M-GRADE`'s CSV renders the five
  counters on every grade row, matching the row — a coverage record that exists in
  the ledger but not on the page has satisfied the letter and lost the point.
- **the console's grade render** (rung 3, `[m_console]`, green): the clause
  names `M-CONSOLE` as the consumer that must render coverage alongside the grade.
  Landed at #127: the render is `aeh.console:render_grade_coverage` (#107's
  disclosed surface), the one that shows a grade WITH its coverage record, and
  the limb below keys on it.

Isolation: rung 3 (real store, real package, real service); rung 4 for the export.
The socket guard is autouse; `criterion_score` rows are the vocabulary's disclosed
`M-AGG` stand-in.
"""

from __future__ import annotations

import csv
import re

import pytest

from aeh.store import open_store
from tests.contract.grade._drive import current_grades, graded_run
from tests.support.impl import CONSOLE_MODULE, GRADE_MODULE, require

pytestmark = [pytest.mark.contract]

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)

#: A mixed cohort: every coverage class present somewhere in one run.
_ROWS = (
    ("S-A", "C1", "B2", 7.0, "auto"),
    ("S-A", "C2", "B1", 6.0, "reviewed"),
    ("S-B", "C1", "B2", 7.0, "auto"),
    ("S-B", "C2", "B2", 5.0, "provisional"),
    ("S-C", "C1", "B2", 7.0, "auto"),
    # S-C's C2 never scored — the missing class is the row's absence.
)

_EXPECTED = {
    "S-A": (2, 1, 1, 0, 0),  # total, auto, reviewed, provisional, missing
    "S-B": (2, 1, 0, 1, 0),
    "S-C": (2, 1, 0, 0, 1),
}


def test_tc_grade_c04_the_five_coverage_fields_sum_consistently_on_every_grade(
    tmp_data_dir,
):
    """`TC-GRADE-C04` (`CT-GRADE-04`, rung 3) — over a cohort carrying all four
    coverage classes at once, every delivered grade's counters are exact and
    arithmetically consistent: auto + reviewed + provisional + missing ==
    `criteria_total`, and `criteria_total` is the package's criterion count (a
    criterion with no row counts missing, never silently absent)."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=tuple(_EXPECTED), criteria=_CRITERIA, rows=_ROWS
        )
        grades = {row["submission_id"]: row for row in current_grades(world.cohort, world.run_id)}
        assert set(grades) == set(_EXPECTED), (
            "fixture bug: the mixed cohort did not deliver a grade per submission"
        )
        for sid, (total, auto, reviewed, provisional, missing) in _EXPECTED.items():
            row = grades[sid]
            got = (
                int(row["criteria_total"]), int(row["criteria_auto"]),
                int(row["criteria_reviewed"]), int(row["criteria_provisional"]),
                int(row["criteria_missing"]),
            )
            assert got == (total, auto, reviewed, provisional, missing), (
                f"{sid}'s coverage record is {got!r}, expected "
                f"{(total, auto, reviewed, provisional, missing)!r} — the five "
                "design-named counters (FR-GRADE-04/CT-GRADE-04, verbatim)"
            )
            assert auto + reviewed + provisional + missing == total, (
                f"{sid}'s classes sum to {auto + reviewed + provisional + missing}, "
                f"not {total} — the coverage record does not sum consistently "
                "against criteria_total (CT-GRADE-04's arithmetic clause)"
            )
    finally:
        store.close()


def test_tc_grade_c04_the_module_export_renders_coverage_alongside_the_grade(
    tmp_data_dir, monkeypatch
):
    """`TC-GRADE-C04`'s export limb (`CT-GRADE-04`, rung 4) — `M-GRADE`'s own
    consumer surface renders the coverage record beside the grade: the CSV carries
    the five counters on every row, and they match the ledger's. A coverage record
    that exists in the row but not on the page has satisfied the letter and lost
    the point; the export is the module's own page."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    export_dir = tmp_data_dir.parent / "c04-exports"
    monkeypatch.setenv("HARNESS_GRADE_EXPORT_DIR", str(export_dir))
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=tuple(_EXPECTED), criteria=_CRITERIA, rows=_ROWS
        )
        path = world.service.export(world.run_id, 1, "csv")
        with path.open(newline="", encoding="utf-8") as handle:
            rows = {row["submission_id"]: row for row in csv.DictReader(handle)}
        assert set(rows) == set(_EXPECTED), (
            "fixture bug: the export does not carry one row per graded submission"
        )
        for sid, expected in _EXPECTED.items():
            rendered = rows[sid]
            assert all(name in rendered for name in (
                "criteria_total", "criteria_auto", "criteria_reviewed",
                "criteria_provisional", "criteria_missing",
            )), (
                f"{sid}'s exported row lacks a coverage column — the export renders "
                "the grade without the coverage record (CT-GRADE-04: a grade shown "
                "without coverage is a stronger claim than the system is making)"
            )
            got = tuple(int(rendered[name]) for name in (
                "criteria_total", "criteria_auto", "criteria_reviewed",
                "criteria_provisional", "criteria_missing",
            ))
            assert got == expected, (
                f"{sid}'s rendered coverage {got!r} != the ledger's {expected!r} — "
                "the export must render the row's own record (CT-GRADE-04)"
            )
            assert rendered["state"] and rendered["total"], (
                f"{sid}'s export row lost its grade columns — coverage must ride "
                "WITH the grade, not replace it"
            )
    finally:
        store.close()


def test_tc_grade_c04_the_console_renders_coverage_alongside_the_grade(tmp_data_dir):
    """`TC-GRADE-C04`'s console limb (`CT-GRADE-04`, rung 3, `[m_console]`) —
    `M-CONSOLE` renders the coverage record alongside the grade, because a grade
    shown without its coverage is a stronger claim than the system is making.

    Landed at #127: `aeh.console:render_grade_coverage` (the #107-disclosed render) is
    the standing assertion that the five counters ride with the grade — and the rollup's
    grade rows render through the same presentation helpers, so the screen cannot
    quietly drop them."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    render_grade_coverage = require(
        CONSOLE_MODULE, "render_grade_coverage", issue="#107"
    )
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=tuple(_EXPECTED), criteria=_CRITERIA, rows=_ROWS
        )
        for sid, (total, auto, reviewed, provisional, missing) in _EXPECTED.items():
            rendered = render_grade_coverage(world.run_id, sid, store=store)
            text = rendered if isinstance(rendered, str) else str(rendered)
            assert f"{total}/{auto}/{reviewed}/{provisional}/{missing}" in text or all(
                re.search(rf"(?<!\d){re.escape(str(count))}(?!\d)", text)
                for count in (total, auto, reviewed, provisional, missing)
            ), (
                f"{sid}'s rendered grade carries no coverage record — a grade shown "
                "without it is a stronger claim than the system is making "
                "(CT-GRADE-04's consumer clause, M-CONSOLE)"
            )
    finally:
        store.close()
