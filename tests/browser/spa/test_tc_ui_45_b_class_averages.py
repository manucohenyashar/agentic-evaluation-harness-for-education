"""Validity T12 (issue #909): TC-UI-45 (b), CT-CONSOLE-56 r2 — a defect the blindness census
found. Written ahead (red until fixed).

With the draw open, Results' "Average by question" bars are worked out from every student's
points, drawn lines included: on the ENG7 world every student's C2 (Q2's only line) is drawn,
yet the bar reads "Q2 — average 3.0 / 3 (100%)" and "full marks: 4 of 4 students" — each
drawn C2 cell's points, and so its band ("full"), to the point. The same holds for Q1 (both
aspects drawn for every student). CT-CONSOLE-56 r2: while a draw is open no teacher-facing
read returns a drawn line's points.

The leak is in the server read, not the SPA: `screen_reads` computes `question_stats` from
the students before `held_back.hold_back` blanks their drawn lines, and a `question_stats`
entry names no submission, so the hold-back (and TC-CONSOLE-108's node walk, which ties a
node to a student) never sees it.

The oracle: for each question every one of whose cells (across the class) is drawn, the
Results page shows no average and no full/no-marks count for it; the question with an
undrawn cell (Q3) may.

**Written ahead: yes** — `WRITTEN_AHEAD_BLOCKERS["#909 defect — Results question averages
reveal drawn points"]`.
"""

from __future__ import annotations

import re

import pytest

from tests.support import spa
from tests.support.eng7_browser import VIEWPORT, assert_clean, eng7_browser, open_draw

pytestmark = [pytest.mark.browser, pytest.mark.integration, pytest.mark.writtenahead]


def test_tc_ui_45_b_question_averages_reveal_no_drawn_points(tmp_path, monkeypatch):
    with eng7_browser(tmp_path, monkeypatch) as world, \
            spa.spa_page(world.origin, viewport=VIEWPORT) as (page, log):
        open_draw(world)
        drawn = world.drawn()
        cells = world.cells()
        fully_drawn = sorted({
            question for question in set(world.questions.values())
            if all(cell in drawn for cell in cells if world.questions[cell[1]] == question)})
        assert fully_drawn == ["Q1", "Q2"], f"fixture: fully drawn questions {fully_drawn}"
        world.open(page, "/results")
        stats = page.locator("li.question-stat")
        stats.first.wait_for()
        problems = []
        for index in range(stats.count()):
            text = stats.nth(index).inner_text()
            question = text.split(" — ", 1)[0].strip()
            if question in fully_drawn and re.search(
                    r"average \d|full marks: \d|no marks: \d", text):
                problems.append(f"{question}: {text!r}")
        assert not problems, (
            "Results' class averages reveal wholly drawn questions' points while the draw is "
            "open (CT-CONSOLE-56 r2):\n  " + "\n  ".join(problems))
        assert_clean(page, log)
