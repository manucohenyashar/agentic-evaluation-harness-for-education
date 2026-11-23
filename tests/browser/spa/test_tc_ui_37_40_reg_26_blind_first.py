"""Validity T12 (issue #909): blind first, the blind screen, the comparison and the hidden
lines in the SPA — TC-UI-37 (FR-UI-39, amends FR-UI-33), TC-UI-38 (FR-UI-40), TC-UI-39
(FR-UI-41), TC-UI-40 (FR-UI-42) and TC-REG-26 (SV-19). Browser tier (E6), 1280x720.

**World.** `tests/support/eng7_browser.py`: the ENG7 class graded by the console's own start
run; (first student, C3) kept out of the draw, so 15 seats. The stand-in judge marks C2 at
its top band ("full") and every other line at its lowest, so a teacher's choice can differ
from the system's either way.

| Case | What is asserted |
|---|---|
| TC-UI-37 | Monitor's banner reads FR-UI-39's sentence with n = the draw's size and m = the reserve-minutes knob (set to 7 here, so the default cannot pass), banner and both buttons inside 1280x720; **Mark the sample** opens the sample; "Approve all grades" while open carries "This does not finish your blind sample; you can still mark it." and, after a Skip, does not |
| TC-UI-38 | per seat: the roster name and question, the answer text, **View the page** opening the scan (200, image bytes; a page the seat does not name and the same link after Finish both 404), levels with the spec's descriptors; "0 of 15 marked" with Finish disabled, a choice -> "1 of 15 marked", Finish enabled, both surviving a reload; 12 marked -> the exact 3-unmarked confirmation; no anchor to a student page while open or after Finish |
| TC-UI-39 | after Finish: each row "You: <teacher>" / "The system: <stored band>", every differing row before every agreeing one, more/less credit by the scale's order, none on an agreeing row; **See the results** after the list, opening Results |
| TC-UI-40 | with the draw open: on Results each drawn question cell reads the sentence with the **Mark the sample** link, each drawn line in "How each line was scored" reads it with no band, the undrawn line shows its band; on the student page each drawn card reads it with the link (which opens the sample), the undrawn card its band |
| TC-REG-26 | on completion Monitor offers the sample first (`next[0]` and the banner's first button), Results hides the drawn lines; **Skip and see results** lands on Results with every line shown |

**Disclosed.**
- TC-UI-37's Approve-all arm: the console's ENG7 run computes every grade `final`, so Results
  shows no "Approve all grades" (it appears only with answers not final). The case sets the
  run's `submission_grade.state` to `provisional` — a stand-in for a run whose grades await
  approval; the confirmation's text is what is under test.
- TC-UI-40's "the shown total includes it" is superseded by D6 / FR-CONSOLE-89 r2 (the drawn
  students' totals are hidden while the draw is open; T19/T18 own the totals); this case
  asserts the hidden total form instead.
- TC-UI-38's answer text is compared with the seats read's `answer_text` (what the page must
  render); the seat text itself carries the printed question and a stray "## Q2" heading —
  reported in the PR as a possible span defect, not asserted here.

**Written ahead: no** (S13 #883 merged).
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import Any

import pytest

from tests.support import spa
from tests.support.eng7_browser import (
    HELD_BACK,
    VIEWPORT,
    Eng7Browser,
    assert_clean,
    dialog,
    eng7_browser,
    open_draw,
    scales,
)

pytestmark = [pytest.mark.browser, pytest.mark.integration]

OPEN_SENTENCE = "This does not finish your blind sample; you can still mark it."
STUDENT_LINK = "a[href*='results/students'], a[href*='/students/']"


def _inside(box: dict | None) -> bool:
    return box is not None and box["x"] >= 0 and box["y"] >= 0 and \
        box["x"] + box["width"] <= 1280 and box["y"] + box["height"] <= 720


def _fetch(url: str) -> tuple[int, bytes, str]:
    try:
        with urllib.request.urlopen(url) as answer:
            return answer.status, answer.read(), answer.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers.get("Content-Type", "")


def _approve_dialog_text(world: Eng7Browser, page: Any) -> str:
    world.open(page, "/results")
    page.reload()  # the same address twice is no navigation: read the results afresh
    spa.wait_for_screen(page)
    page.get_by_role("button", name="Approve all grades").click()
    text = dialog(page).inner_text()
    dialog(page).get_by_role("button", name="Cancel").click()
    return text


# --- TC-UI-37 -----------------------------------------------------------------------------------


def test_tc_ui_37_the_completion_banner_and_the_approve_all_sentence(tmp_path, monkeypatch):
    """TC-UI-37: the banner with n and m and both buttons in the viewport; Approve all's
    added sentence while the draw is open, and not after a Skip."""
    monkeypatch.setenv("HARNESS_CONSOLE_BLIND_RESERVE_MINUTES", "7")
    with eng7_browser(tmp_path, monkeypatch) as world, \
            spa.spa_page(world.origin, viewport=VIEWPORT) as (page, log):
        world.open(page, "/monitor")
        banner = page.get_by_role("region", name="Marking finished")
        banner.wait_for()
        n = len(world.drawn())
        assert n == 15, f"fixture: {n} drawn"
        assert banner.locator(".outcome-what").inner_text() == (
            f"Marking finished. Mark {n} answers yourself first, without seeing the system's "
            f"marks (about 7 min), or skip and see the results.")
        mark = banner.get_by_role("button", name="Mark the sample")
        skip = banner.get_by_role("button", name="Skip and see results")
        for what, locator in (("banner", banner), ("Mark the sample", mark),
                              ("Skip and see results", skip)):
            assert _inside(locator.bounding_box()), (
                f"{what} is not inside 1280x720: {locator.bounding_box()}")
        mark.click()
        assert spa.wait_for_screen(page) == "Blind sample"
        assert spa.screen_route(page.url) == "/review/blind"

        world.served.execute("UPDATE submission_grade SET state = 'provisional' "
                             "WHERE run_id = ?", world.run_id)
        while_open = _approve_dialog_text(world, page)
        assert f"the change is recorded. {OPEN_SENTENCE}" in while_open, while_open

        world.served.dispatched("blind-sample skip", run_id=world.run_id)
        after_skip = _approve_dialog_text(world, page)
        assert "Approve all grades for" in after_skip, after_skip
        assert OPEN_SENTENCE not in after_skip, (
            f"the open-sample sentence stays after the sample was skipped: {after_skip}")
        assert_clean(page, log)


# --- TC-UI-38 -----------------------------------------------------------------------------------


def test_tc_ui_38_the_blind_screen(tmp_path, monkeypatch):
    """TC-UI-38: the seat, View the page, the levels, progress and its reload, Finish's
    enablement and 3-unmarked confirmation, and no student-page anchor."""
    with eng7_browser(tmp_path, monkeypatch) as world, \
            spa.spa_page(world.origin, viewport=VIEWPORT) as (page, log):
        read = open_draw(world)
        seats = world.served.seat_cells(read)
        names = world.names()
        levels = scales()
        world.open(page, "/review/blind")
        cards = page.locator("[data-component='blind-seat']")
        cards.first.wait_for()
        assert cards.count() == len(read["seats"]) == 15
        for index, seat in enumerate(read["seats"]):
            card = cards.nth(index)
            submission, criterion = seats[seat["seat_id"]]
            heading = card.get_by_role("heading", level=2).inner_text()
            assert heading == f"{names[submission]} — {world.questions[criterion]}", heading
            assert seat["answer_text"] and card.locator("blockquote").inner_text() == \
                seat["answer_text"].strip(), (heading, card.locator("blockquote").inner_text())
            shown = [label.strip() for label in card.locator("label").all_inner_texts()]
            assert shown == [f"{band} — {descriptor}" for band, descriptor in
                             levels[criterion]], (heading, shown)

        # View the page: the scan of this seat's page; nothing else through the route.
        first = cards.first
        link = first.get_by_role("link", name=re.compile(r"^View the page"))
        href = link.get_attribute("href") or ""
        assert href.startswith("/blind-page?"), href
        with page.expect_popup() as popup_info:
            link.click()
        popup = popup_info.value
        popup.wait_for_load_state()
        assert "/blind-page?" in popup.url, popup.url
        popup.close()
        status, body, kind = _fetch(world.origin + href)
        assert status == 200 and kind.startswith("image/") and len(body) > 1000, (
            status, kind, len(body))
        stray = href.replace("page=1", "page=99")
        assert stray != href and _fetch(world.origin + stray)[0] == 404, stray

        # Progress and Finish: 0 -> disabled; one choice -> "1 of 15", enabled; a reload.
        progress = page.locator(".blind-progress")
        finish = page.locator("main").get_by_role("button", name="Finish", exact=True)
        assert progress.inner_text() == "0 of 15 marked"
        assert finish.is_disabled()
        chosen = levels[seats[read["seats"][0]["seat_id"]][1]][-1][0]
        first.get_by_role("radio", name=re.compile(rf"^{re.escape(chosen)}\b")).check()
        page.wait_for_function(
            "() => document.querySelector('.blind-progress')?.textContent === '1 of 15 marked'")
        assert finish.is_enabled()
        page.reload()
        spa.wait_for_screen(page)
        assert page.locator(".blind-progress").inner_text() == "1 of 15 marked"
        radio = page.locator("[data-component='blind-seat']").first.locator(
            f"input[type=radio][value='{chosen}']")
        assert radio.is_checked(), "the chosen level did not survive the reload"
        assert finish.is_enabled()

        # 12 marked (11 more drafts through the console), 3 unmarked -> the exact confirmation.
        for seat in read["seats"][1:12]:
            world.served.dispatched("blind-sample draft", run_id=world.run_id,
                                    seat_id=seat["seat_id"], band=seat["bands"][0]["name"])
        page.reload()
        spa.wait_for_screen(page)
        assert page.locator(".blind-progress").inner_text() == "12 of 15 marked"
        finish.click()
        assert dialog(page).locator("p").first.inner_text() == (
            "Finish with 3 answers unmarked? Only the ones you marked will count.")
        assert page.locator(STUDENT_LINK).count() == 0, (
            "the blind screen links to a student page")

        dialog(page).get_by_role("button", name="Finish").click()
        page.locator(".blind-comparison").wait_for()
        assert page.locator(STUDENT_LINK).count() == 0, (
            "the comparison links to a student page")
        assert _fetch(world.origin + href)[0] == 404, "the scan is served after Finish"
        assert_clean(page, log)


# --- TC-UI-39 -----------------------------------------------------------------------------------


def test_tc_ui_39_the_comparison(tmp_path, monkeypatch):
    """TC-UI-39: every seat marked (C1 aspects 'present' over the system's 'absent', C2
    'none' under its 'full', C3 'none' as the system), Finish in the browser, then the
    comparison."""
    teacher_choice = {"C1a": "present", "C1b": "present", "C2": "none", "C3": "none"}
    with eng7_browser(tmp_path, monkeypatch) as world, \
            spa.spa_page(world.origin, viewport=VIEWPORT) as (page, log):
        read = open_draw(world)
        seats = world.served.seat_cells(read)
        cells = world.cells()
        names = world.names()
        order = {criterion: [band for band, _d in scale] for criterion, scale in scales().items()}
        for seat in read["seats"]:
            world.served.dispatched("blind-sample draft", run_id=world.run_id,
                                    seat_id=seat["seat_id"],
                                    band=teacher_choice[seats[seat["seat_id"]][1]])
        expected: dict[str, list[tuple[str, str]]] = {}
        for submission, criterion in seats.values():
            key = f"{names[submission]} — {world.questions[criterion]}"
            expected.setdefault(key, []).append(
                (teacher_choice[criterion], cells[(submission, criterion)]["band"]))

        world.open(page, "/review/blind")
        page.locator("main").get_by_role("button", name="Finish", exact=True).click()
        assert dialog(page).locator("p").first.inner_text() == (
            "Finish with all 15 answers marked? Your marks can't be changed afterwards.")
        dialog(page).get_by_role("button", name="Finish").click()
        section = page.locator(".blind-comparison")
        section.wait_for()
        rows = section.locator("li.blind-compared")
        assert rows.count() == 15
        seen_agreeing = False
        kinds = set()
        remaining = {key: list(pairs) for key, pairs in expected.items()}
        for index in range(rows.count()):
            row = rows.nth(index)
            head = row.locator(".step-name").inner_text()
            yours = row.locator(".blind-yours").inner_text()
            system = row.locator(".blind-system").inner_text()
            teacher_band = yours.removeprefix("You: ")
            system_band = system.removeprefix("The system: ")
            assert yours.startswith("You: ") and system.startswith("The system: "), (yours, system)
            assert (teacher_band, system_band) in remaining.get(head, []), (
                f"row {index} {head}: {yours} / {system} is not a marked seat's pair "
                f"{expected.get(head)}")
            remaining[head].remove((teacher_band, system_band))
            criterion = next(c for c in order if teacher_band in order[c] and
                             system_band in order[c] and world.questions[c] == head[-2:])
            direction = row.locator(".blind-direction")
            if teacher_band == system_band:
                seen_agreeing = True
                assert direction.count() == 0, f"an agreeing row says {direction.inner_text()}"
                continue
            assert not seen_agreeing, f"row {index} differs but follows an agreeing row"
            scale = order[criterion]
            more = scale.index(system_band) > scale.index(teacher_band)
            kinds.add(more)
            assert direction.inner_text() == (
                "The system gave more credit than you." if more
                else "The system gave less credit than you."), (head, direction.inner_text())
        assert kinds == {True, False}, "fixture: the differences run one way only"
        assert seen_agreeing, "fixture: no agreeing row"
        assert all(not pairs for pairs in remaining.values()), remaining

        see = page.locator("main").get_by_role("button", name="See the results")
        assert see.count() == 1
        assert section.evaluate("(s, b) => !!(s.compareDocumentPosition(b) & 4)",
                                see.element_handle()), "See the results is not after the list"
        see.click()
        assert spa.wait_for_screen(page) == "Results"
        assert_clean(page, log)


# --- TC-UI-40 -----------------------------------------------------------------------------------


def test_tc_ui_40_drawn_lines_hidden_on_results_and_the_student_page(tmp_path, monkeypatch):
    """TC-UI-40: with the draw open, every drawn line on Results and the student page reads
    "Hidden until you mark your sample or skip it" with the link; the undrawn line shows."""
    with eng7_browser(tmp_path, monkeypatch) as world, \
            spa.spa_page(world.origin, viewport=VIEWPORT) as (page, log):
        open_draw(world)
        drawn = world.drawn()
        cells = world.cells()
        names = world.names()
        by_name = {name: sub for sub, name in names.items()}
        world.open(page, "/results")
        rows = page.locator("li.result-row")
        rows.first.wait_for()
        assert rows.count() == 4
        checked_kept = False
        for index in range(rows.count()):
            row = rows.nth(index)
            submission = by_name[row.locator(".result-head a").inner_text()]
            assert row.locator(".total-grade").inner_text() == f"Total grade: {HELD_BACK}", (
                "a drawn student's total is shown (D6)")
            for cell_index in range(row.locator("li.question-cell").count()):
                cell = row.locator("li.question-cell").nth(cell_index)
                head = cell.locator(":scope > span").first.inner_text()
                question = head.split(" · ")[0]
                criteria = [c for c, q in world.questions.items() if q == question]
                cell.locator("summary").click()
                lines = cell.locator(".band-list > li")
                if any((submission, c) in drawn for c in criteria):
                    assert head == f"{question} · {HELD_BACK} Mark the sample", head
                    assert cell.get_by_role("link", name="Mark the sample").count() == 1
                for line_index, criterion in enumerate(
                        sorted(criteria)):
                    line = lines.nth(line_index).inner_text()
                    band = cells[(submission, criterion)]["band"]
                    if (submission, criterion) in drawn:
                        # Exactly the line's label and the sentence: no level beside it.
                        label = lines.nth(line_index).locator(".step-note").inner_text()
                        assert line.split() == f"{label} {HELD_BACK}".split() and                             lines.nth(line_index).locator(".band-value").count() == 0, (
                                submission, criterion, line)
                    else:
                        assert lines.nth(line_index).locator(".band-value").inner_text() == \
                            band, (submission, criterion, line)
                        assert head == f"{question} · {cells[(submission, criterion)]['points']:g}" \
                            f" / 3", head
                        checked_kept = True
        assert checked_kept, "the undrawn control line was never seen on Results"

        # The student page of the kept student: drawn cards hidden with the link, the undrawn
        # card its band; the link opens the sample.
        submission = world.kept[0]
        world.open(page, f"/results/students/{submission}")
        status, detail = world.served.get("/api/v1/results/student-detail",
                                          run_id=world.run_id, submission_id=submission)
        assert status == 200, detail
        groups = page.locator(".question-group")
        assert groups.count() == 3
        for group_index, question in enumerate(("Q1", "Q2", "Q3")):
            order = [c["criterion_id"] for c in detail["criteria"]
                     if c["question_id"] == question]
            cards = groups.nth(group_index).locator("li.criterion-card")
            assert cards.count() == len(order), (question, order)
            for card_index, criterion in enumerate(order):
                card = cards.nth(card_index)
                text = card.inner_text()
                if (submission, criterion) in drawn:
                    label = card.locator("strong").first.inner_text()
                    assert text.split() == f"{label} {HELD_BACK} Mark the sample".split()                         and card.get_by_role("link", name="Mark the sample").count() == 1, (
                            criterion, text)
                    assert card.locator(".band-value").count() == 0, (criterion, text)
                else:
                    assert card.locator(".band-value").inner_text() == \
                        cells[(submission, criterion)]["band"], (criterion, text)
                    assert HELD_BACK not in text
        groups.first.locator("li.criterion-card").first.get_by_role(
            "link", name="Mark the sample").click()
        assert spa.wait_for_screen(page) == "Blind sample"
        assert_clean(page, log)


# --- TC-REG-26 ----------------------------------------------------------------------------------


def test_tc_reg_26_blind_sample_offered_before_results_with_drawn_lines_hidden(
        tmp_path, monkeypatch):
    """TC-REG-26 (SV-19): on completion the sample comes first and Results hides the drawn
    lines; Skip and see results then lands on Results with every line shown."""
    with eng7_browser(tmp_path, monkeypatch) as world, \
            spa.spa_page(world.origin, viewport=VIEWPORT) as (page, log):
        status, monitor = world.served.get("/api/v1/monitor", run_id=world.run_id)
        assert status == 200 and monitor["blind_sample"] == "open", monitor
        assert monitor["next"][0]["route"] == "/review/blind", monitor["next"]
        world.open(page, "/monitor")
        banner = page.get_by_role("region", name="Marking finished")
        buttons = banner.get_by_role("button").all_inner_texts()
        assert buttons[:2] == ["Mark the sample", "Skip and see results"], buttons

        world.open(page, "/results")
        page.locator("li.result-row").first.wait_for()
        hidden = page.locator("main [data-held-back]").count()
        assert hidden >= len(world.drawn()), f"only {hidden} held-back marks on Results"
        assert page.locator("main .band-value").count() == 1, (
            "Results shows a level other than the one undrawn line's")

        world.open(page, "/monitor")
        page.get_by_role("region", name="Marking finished").get_by_role(
            "button", name="Skip and see results").click()
        page.wait_for_function("() => location.hash.startsWith('#/results')")
        assert spa.wait_for_screen(page) == "Results"
        page.locator("li.result-row").first.wait_for()
        page.wait_for_function("() => !document.querySelector('main [data-held-back]')")
        assert world.served.service().draw_state(world.run_id) == "skipped"
        assert page.locator("main .total-grade").first.inner_text().startswith(
            "Total grade: ") and HELD_BACK not in spa.main_text(page)
        assert_clean(page, log)
