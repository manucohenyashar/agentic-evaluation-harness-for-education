"""Validity T12 (issue #909): TC-UI-45 (CT-CONSOLE-56; RSV-09) — blindness on screen. With
the draw open, every route of the SPA's route table, every student page, and Logs -> AI calls
reached through "How was this graded?" on a drawn question: no drawn line's band name, reason
or quote appears in the page's text. Browser tier (E6), 1280x720.

**World.** `tests/support/eng7_browser.py` (ENG7 graded by the console's start run; first
student's C3 kept out of the draw, 15 seats drawn). The stand-in judge marks C1a/C1b at
"absent", C2 at "full" and C3 at "none".

**The route table** is read from `ui/src/App.tsx` (each `address.path === "…"` literal, the
`ROUTES` keys and the student route), so a screen added later is visited without editing
this file.

**The oracle, and why it is shaped so.** ENG7's band names are ordinary words ("none",
"present", "change", "full") that also appear in fixed screen text ("full marks", "Change
the grade") and as the scale itself (the Score-level filter's options, the blind seat's
choices — package data, not a decision). So:
- page-wide, in every route's text with `<select>` elements and the blind seat's level
  choices taken out: no "absent" (every C1 cell is drawn and marked absent) and no "full"
  other than the fixed "full marks"; no drawn cell's cited quote (read from the store);
- per drawn student (every line drawn): the student page shows no level, no state, no reason
  and no "What the paper shows" evidence; the kept student's undrawn card shows its band and
  reason (the positive control);
- AI calls opened from a drawn question list no call for it; from the kept question they do.
The help screen is outside the band-word census (manual prose).
"none" (the drawn C3 cells' level) is not in the page-wide band census — it is an ordinary
word in fixed screen text; the drawn lines' exact held-back text on Results and the student
page (TC-UI-40) is what rules a "none" out there. A drawn line's *reason* is checked through
the student page's reason element only: the stand-in's reason is the same generic sentence
for every cell (the undrawn one included), so there is no distinctive string to census.

**Not covered here, written ahead as a defect:** the Results "Average by question" bars
reveal a wholly drawn question's points ("Q2 — average 3.0 / 3", "full marks: 4 of 4") —
`test_tc_ui_45_b_class_averages.py`.

**Written ahead: no** (S12 #882, S13 #883 merged).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.support import spa
from tests.support.eng7_browser import (
    VIEWPORT,
    assert_clean,
    eng7_browser,
    open_draw,
)

pytestmark = [pytest.mark.browser, pytest.mark.integration]

APP = Path(__file__).resolve().parents[3] / "ui" / "src" / "App.tsx"

#: The page's text with the scale's own renderings taken out (see the module docstring).
TEXT_WITHOUT_SCALES = """() => {
  const clone = document.body.cloneNode(true);
  clone.querySelectorAll('select, fieldset.blind-levels, script, style')
       .forEach((node) => node.remove());
  return clone.textContent || '';
}"""
BAND_WORDS = (re.compile(r"\babsent\b", re.I), re.compile(r"\bfull\b(?! marks| name)", re.I))


def app_routes() -> list[str]:
    source = APP.read_text(encoding="utf-8")
    routes = set(re.findall(r'address\.path === "(/[^"]*)"', source))
    block = re.search(r"const ROUTES[^{]*\{(.*?)\};", source, re.S)
    assert block, "App.tsx no longer declares ROUTES"
    routes |= set(re.findall(r'"(/[^"]+)":', block.group(1)))
    assert "STUDENT_ROUTE" in source, "App.tsx no longer has the student route"
    return sorted(routes)


def _plant_quotes(world: Any) -> dict[tuple[str, str], str]:
    """Give every judged cell's verdicts one distinctive cited quote (the stand-in judge cites
    nothing, so without this the quote arm would search for nothing). Before the draw opens,
    in the verdict ledger's own `cited_spans` shape (`[{"text": ...}]`, what the student
    detail read parses). Returns cell -> quote."""
    rows = world.served.rows(
        "SELECT v.verdict_id, w.submission_id, w.criterion_id FROM verdict v "
        "JOIN work_unit w ON w.work_id = v.work_id WHERE w.run_id = ?", world.run_id)
    quotes: dict[tuple[str, str], str] = {}
    for index, row in enumerate(sorted(rows, key=lambda r: r["verdict_id"])):
        cell = (row["submission_id"], row["criterion_id"])
        quote = quotes.setdefault(cell, f"the keeper climbed stair number {100 + index} slowly")
        world.served.execute("UPDATE verdict SET cited_spans = ? WHERE verdict_id = ?",
                             json.dumps([{"text": quote}]), row["verdict_id"])
    assert set(quotes) == set(world.cells()), "fixture: a judged cell has no verdict"
    return quotes


def test_tc_ui_45_no_drawn_line_band_reason_or_quote_on_any_screen(tmp_path, monkeypatch):
    """TC-UI-45: the route census with the draw open (see the module docstring)."""
    with eng7_browser(tmp_path, monkeypatch) as world, \
            spa.spa_page(world.origin, viewport=VIEWPORT) as (page, log):
        planted = _plant_quotes(world)
        open_draw(world)
        drawn = world.drawn()
        names = world.names()
        quotes = {quote for cell, quote in planted.items() if cell in drawn}
        routes = app_routes()
        assert {"/", "/results", "/review", "/review/blind", "/logs", "/monitor"} <= set(routes)
        visits = [r for r in routes] + [f"/results/students/{s}" for s in sorted(names)] + \
            ["/logs?tab=ai-calls"]
        package = world.served.package_version.split("@")[0]

        problems: list[str] = []
        for route in visits:
            target = route + (f"?package={package}" if route.startswith("/package") else "")
            # A full load per route (never a hash-only hop), so the text read is this screen's
            # and not the previous one's still on the page.
            page.goto("about:blank")
            page.goto(world.route(target))
            try:
                spa.wait_for_screen(page)
            except Exception as error:  # noqa: BLE001 — a screen that never loads is a finding
                problems.append(f"{route}: the screen did not load ({str(error)[:120]})")
                continue
            page.wait_for_timeout(300)
            text = page.evaluate(TEXT_WITHOUT_SCALES)
            if route != "/help":
                for pattern in BAND_WORDS:
                    for match in pattern.finditer(text):
                        context = text[max(0, match.start() - 60):match.end() + 60]
                        problems.append(f"{route}: a drawn band {match.group(0)!r}: "
                                        f"...{context!r}...")
            problems += [f"{route}: a drawn cell's quote {q!r}" for q in quotes if q in text]

        # Per drawn student: no level, state, reason or evidence on the student page.
        for submission in sorted(names):
            page.goto(world.route(f"/results/students/{submission}"))
            spa.wait_for_screen(page)
            cards = page.locator("li.criterion-card")
            cards.first.wait_for()
            undrawn = [c for s, c in world.cells() if s == submission and (s, c) not in drawn]
            for selector in (".band-value", ".criterion-state", ".criterion-why", ".evidence"):
                count = cards.filter(has=page.locator(selector)).count()
                if count > len(undrawn):
                    problems.append(f"student {names[submission]}: {count} cards show "
                                    f"{selector} for {len(undrawn)} undrawn line(s)")
            if submission == world.kept[0]:
                assert page.locator("li.criterion-card .band-value").all_inner_texts() == [
                    world.cells()[world.kept]["band"]], "the undrawn control card shows no band"
                assert page.locator("li.criterion-card .criterion-why").count() == 1, (
                    "the undrawn control card shows no reason, so the census proves nothing")
                assert planted[world.kept] in page.evaluate(TEXT_WITHOUT_SCALES), (
                    "the undrawn control card shows no quote, so the quote arm proves nothing")

        # Logs -> AI calls through "How was this graded?": a drawn question lists no call; the
        # kept question lists its call.
        kept_name = names[world.kept[0]]
        drawn_student = next(s for s in sorted(names) if s != world.kept[0])
        for submission, question, expect_calls in (
                (drawn_student, "Q2", False), (world.kept[0], "Q3", True)):
            page.goto(world.route(f"/results/students/{submission}"))
            spa.wait_for_screen(page)
            group = page.locator(".question-group").filter(
                has=page.locator("h3", has_text=re.compile(rf"^{question} —")))
            group.get_by_role("link", name="How was this graded?").click()
            page.wait_for_function("() => location.hash.startsWith('#/logs')")
            spa.wait_for_screen(page)
            # The AI-calls view has answered: its page line, "N call(s) on this page of M."
            page.locator(".logs-pages").first.wait_for()
            assert "tab=ai-calls" in page.url and f"question={question}" in page.url, page.url
            text = page.evaluate(TEXT_WITHOUT_SCALES)
            call = re.compile(rf"AI judge\s+{re.escape(names[submission])} — {question}")
            if expect_calls:
                assert call.search(text), (
                    f"the undrawn {kept_name} {question} lists no AI call, so the arm proves "
                    f"nothing: {text[-600:]!r}")
            elif call.search(text):
                problems.append(f"AI calls list a drawn cell's call: {names[submission]} "
                                f"{question}")
            for pattern in BAND_WORDS:
                if not expect_calls and pattern.search(text):
                    problems.append(f"AI calls for {names[submission]} {question} name a band")

        assert not problems, "drawn lines readable on screen while the draw is open:\n  " + \
            "\n  ".join(problems[:60])
        assert_clean(page, log)
