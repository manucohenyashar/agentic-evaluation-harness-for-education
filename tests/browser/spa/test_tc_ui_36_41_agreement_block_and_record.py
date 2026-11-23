"""Validity T12 (issue #909): the results agreement block and the test's record in the SPA —
TC-UI-36 (FR-UI-38, CT-CONSOLE-55) and TC-UI-41 (FR-UI-43). Browser tier (E6), 1280x720.

| Case | World | What is asserted |
|---|---|---|
| TC-UI-36 (a) | class A (marked in full agreement, promoted) then class B, the validity seed, drafted through M-REVIEW and **finished in the browser** | the block "How closely the marking matched yours" lies wholly inside 1280x720 at scroll 0; the matched sentence with n = 24 and matched = 17; per question "agreement beyond chance" 0.50 (simple checks) and 0.38 (overall judgements) with "12 answers"; "Too few answers to rely on yet (12 of the 30 needed)."; the differences sentence by roster name, grouped less/more credit, and **Review these** opening the sample; no `%` and no "accuracy" in the block; class A's record on its own labelled `.prior-record` line, never among the current figures |
| TC-UI-36 (b) | three more classes of the same version | skipped -> FR-UI-38's exact skipped sentence; not offered -> "You have not marked ..." with the link to the sample; in progress -> "... not finished yet." with the link |
| TC-UI-41 (a) | one class, 12 blind answers on the holistic line, promoted, the version published | Past tests and the package catalog: "How well this test has been marked so far", "12 of 30 blind answers collected; too few to rely on yet", the class with its date and "12 blind answers" |
| TC-UI-41 (b) | TC-STATS-44's record seed (A 12, B skipped, C 20 -> 32) | per-question agreement with n ("agreement beyond chance 0.60 — 32 answers"), and each class with its date (B "the blind sample was skipped") |

**Disclosed.**
- The validity seed's students carry no roster row, so `validity_browser.name_students` gives
  each a synthetic roster name (FR-UI-38 names students). The figures are worked out here from
  the seed's own confusion tables (atomic kappa 0.5, holistic 5/13; validity_seed.py), not
  read back from the system.
- The page census of the plan ("no accuracy, no %") is scoped to the block in its recorded
  state: Results also carries FR-UI-31's average bars ("(58%)"), and FR-UI-38's own skipped
  sentence ends "no new evidence about accuracy" — that sentence is asserted exactly instead.
  The plan's page-wide census contradicts FR-UI-38's text; reported in the PR.

**Written ahead: no** (S13 #883 and S14 #884 merged).
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any

import pytest

from tests.support import spa
from tests.support import validity_seed as vs
from tests.support.validity_browser import (
    VIEWPORT,
    assert_clean,
    name_students,
    open_screen,
    served,
)

pytestmark = [pytest.mark.browser, pytest.mark.integration]

BLOCK = "How closely the marking matched yours"
RECORD = "How well this test has been marked so far"
SKIPPED = ("You skipped the blind sample for this class, so there is no new evidence about "
           "accuracy.")


def _block(page: Any) -> Any:
    return page.locator(f'section[aria-label="{BLOCK}"]')


def _labels(origin: str, run_id: str) -> dict[str, str]:
    with urllib.request.urlopen(f"{origin}/api/v1/results/validity?run_id={run_id}") as answer:
        read = json.loads(answer.read())
    return {view["criterion_id"]: view["label"] for view in read["criteria"]}


def _differences(administration: vs.Administration, names: dict[str, str],
                 labels: dict[str, str]) -> str:
    """FR-UI-38's differences sentence, worked out from the seed: grouped less credit then
    more credit, each item "<name>, <question>", in question then name order."""
    groups: dict[str, list[tuple[str, str]]] = {"less": [], "more": []}
    for criterion, bands in vs.BANDS.items():
        for index, (system, teacher) in enumerate(zip(vs.VALIDITY_SYSTEM[criterion],
                                                      vs.VALIDITY_TEACHER[criterion])):
            if system == teacher:
                continue
            key = "less" if bands.index(system) < bands.index(teacher) else "more"
            groups[key].append((labels[criterion], names[administration.submission(index)]))
    parts = []
    for key in ("less", "more"):
        items = sorted(groups[key], key=lambda item: (item[0], item[1].casefold()))
        where = " · ".join(f"{name}, {question}" for question, name in items)
        parts.append(f"it gave {key} credit than you on {len(items)}: {where}")
    return f"Where it differed, {'; '.join(parts)}."


def test_tc_ui_36_the_agreement_block_after_finish(tmp_path, monkeypatch):
    """TC-UI-36 (a): Finish in the browser on the validity seed, then Results' block."""
    world = vs.ValidityStore(tmp_path / "w")
    try:
        prior = world.administer("class-a", vs.VALIDITY_SYSTEM)
        world.mark(prior, world.draw(prior, 24), vs.teacher_bands(prior, vs.VALIDITY_SYSTEM))
        world.finish(prior)
        assert world.promote(prior, "finish").promoted

        current = world.administer("class-b", vs.VALIDITY_SYSTEM)
        names = name_students(world, current)
        seats = world.draw(current, 24)
        assert world.mark(current, seats,
                          vs.teacher_bands(current, vs.VALIDITY_TEACHER)) == 24

        with served(world, monkeypatch) as origin, \
                spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
            open_screen(page, origin, "/review/blind", current)
            page.locator("main").get_by_role("button", name="Finish").click()
            dialog = page.get_by_role("dialog").or_(page.get_by_role("alertdialog")).first
            dialog.get_by_role("button", name="Finish").click()
            page.get_by_role("button", name="See the results").click()
            assert spa.wait_for_screen(page) == "Results"
            block = _block(page)
            block.locator(".agreement-matched").wait_for()
            page.evaluate("() => window.scrollTo(0, 0)")
            box = block.bounding_box()
            assert box is not None and box["y"] >= 0 and box["y"] + box["height"] <= 720, (
                f"the agreement block is not wholly inside 1280x720 at scroll 0: {box}")
            assert block.get_by_role("heading", level=2).inner_text() == BLOCK

            labels = _labels(origin, current.run_id)
            n = sum(len(bands) for bands in vs.VALIDITY_SYSTEM.values())
            matched = sum(s == t for c in vs.BANDS for s, t in
                          zip(vs.VALIDITY_SYSTEM[c], vs.VALIDITY_TEACHER[c]))
            assert (n, matched) == (24, 17), "fixture: the seed's own counts"
            assert block.locator(".agreement-matched").inner_text() == (
                f"On the {n} answers you marked without seeing the system's marks, it gave "
                f"the same level on {matched}.")
            lines = block.locator(".agreement-figures > li").all_inner_texts()
            assert lines == [
                f"{labels[vs.ATOMIC]} (simple checks): agreement beyond chance "
                f"{0.5:.2f} — 12 answers",
                f"{labels[vs.HOLISTIC]} (overall judgements): agreement beyond chance "
                f"{5 / 13:.2f} — 12 answers",
            ], lines
            assert block.locator(".agreement-too-few").inner_text() == (
                "Too few answers to rely on yet (12 of the 30 needed).")
            differences = block.locator(".agreement-differences")
            text = differences.inner_text()
            expected = _differences(current, names, labels)
            assert text.startswith(expected), f"{text!r}\n!= {expected!r}"
            assert "ref-" not in block.inner_text(), "the block names a student by ref"

            # The census, on the block in its recorded state (see the module docstring).
            whole = block.inner_text()
            assert "%" not in whole and "accuracy" not in whole.lower(), whole

            # The earlier class's record: its own labelled line, never a current figure.
            record = block.locator(".prior-record")
            assert record.count() == 1, "no separate prior-record line"
            label = record.get_attribute("aria-label") or ""
            assert label and record.inner_text().startswith(label), record.inner_text()
            assert "24 of 30 blind answers collected; too few to rely on yet" in \
                record.inner_text(), record.inner_text()
            assert block.locator(".agreement-figures .prior-record").count() == 0
            assert all("1.00" not in line for line in lines), (
                f"class A's figure (kappa 1.00) stands among the current figures: {lines}")

            differences.get_by_role("button", name="Review these").click()
            assert spa.wait_for_screen(page) == "Blind sample"
            assert spa.screen_route(page.url) == "/review/blind", page.url
            assert_clean(page, log)
    finally:
        world.close()


def test_tc_ui_36_b_skipped_not_offered_and_in_progress_states(tmp_path, monkeypatch):
    """TC-UI-36 (b): the block's sentence or link per state of the class's sample."""
    world = vs.ValidityStore(tmp_path / "w")
    try:
        skipped = world.administer("class-skip", vs.VALIDITY_SYSTEM)
        world.draw(skipped, 24)
        world.skip(skipped)
        assert world.promote(skipped, "skip") is not None
        waiting = world.administer("class-wait", vs.VALIDITY_SYSTEM)
        open_draw = world.administer("class-open", vs.VALIDITY_SYSTEM)
        world.draw(open_draw, 24)

        with served(world, monkeypatch) as origin, \
                spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
            open_screen(page, origin, "/results", skipped)
            body = _block(page).locator("p").first
            body.wait_for()
            assert body.inner_text() == SKIPPED
            assert _block(page).get_by_role("link", name="Mark the sample").count() == 0

            for administration, sentence in (
                    (waiting, "You have not marked a blind sample for this class yet."),
                    (open_draw, "Your blind sample for this class is not finished yet.")):
                open_screen(page, origin, "/results", administration)
                link = _block(page).get_by_role("link", name="Mark the sample")
                link.wait_for()
                assert _block(page).locator("p").first.inner_text() == \
                    f"{sentence} Mark the sample"
                link.click()
                assert spa.wait_for_screen(page) == "Blind sample"
                assert spa.screen_route(page.url) == "/review/blind"
                assert f"run={administration.run_id}" in page.url, page.url
            assert world.service(waiting).draw_state(waiting.run_id) != "skipped"
            assert_clean(page, log)
    finally:
        world.close()


# --- TC-UI-41: the test's record --------------------------------------------------------------

#: TC-STATS-44's record seed (holistic line only): class A 12 marked, B skipped, C 20 marked.
A_SYSTEM = ("B1",) + ("B2",) * 10 + ("B3",)
A_TEACHER = ("B1",) * 3 + ("B2",) * 6 + ("B3",) * 3
B_SYSTEM = ("B2",) * 15
C_SYSTEM = ("B2",) * 10 + ("B3",) * 10
C_TEACHER = ("B2",) * 8 + ("B3",) * 2 + ("B2",) + ("B3",) * 9


def _administer(world: vs.ValidityStore, cohort_id: str, system: tuple[str, ...],
                teacher: tuple[str, ...], *, skip: bool = False) -> vs.Administration:
    administration = world.administer(cohort_id, {vs.HOLISTIC: system})
    seats = world.draw(administration, max(15, len(system)))
    assert len(seats) == len(system), f"fixture: {cohort_id} drew {len(seats)}"
    if skip:
        world.skip(administration)
        world.promote(administration, "skip")
        return administration
    marked = world.mark(administration, seats, {
        (administration.submission(i), vs.HOLISTIC): band for i, band in enumerate(teacher)})
    assert marked == len(system)
    world.finish(administration)
    assert world.promote(administration, "finish").promoted
    return administration


def _publish(world: vs.ValidityStore) -> None:
    world.catalog().publish(world.package_version_id, approved_by="teacher-1")


def _today() -> str:
    day = datetime.now(timezone.utc).date()
    return f"{day.day} {day:%b %Y}"


def _record_sections(page: Any, origin: str, administration: vs.Administration) -> list[Any]:
    """The record section on Past tests, then on the package catalog."""
    found = []
    for route in ("/past", "/package"):
        open_screen(page, origin, route, administration)
        section = page.locator(f'section[aria-label="{RECORD}"]').first
        section.locator(".record-headline, .record-figures").first.wait_for()
        found.append((route, section))
    return found


def _classes(section: Any) -> list[list[str]]:
    rows = section.locator(".record-classes > li")
    return [[part.strip() for part in rows.nth(i).locator(":scope > span").all_inner_texts()]
            for i in range(rows.count())]


def test_tc_ui_41_a_twelve_of_thirty_collected(tmp_path, monkeypatch):
    """TC-UI-41 (a): one class, 12 blind answers -> "12 of 30 ... too few to rely on yet"."""
    world = vs.ValidityStore(tmp_path / "w")
    try:
        first = _administer(world, "class-a", A_SYSTEM, A_TEACHER)
        _publish(world)
        with served(world, monkeypatch) as origin, \
                spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
            for route, section in _record_sections(page, origin, first):
                assert section.get_by_role("heading", level=2).inner_text() == RECORD, route
                assert section.locator(".record-headline").inner_text() == (
                    "12 of 30 blind answers collected; too few to rely on yet"), route
                assert section.locator(".record-figures").count() == 0, route
                assert _classes(section) == [["class-a", _today(), "12 blind answers"]], (
                    route, _classes(section))
            assert_clean(page, log)
    finally:
        world.close()


def test_tc_ui_41_b_the_32_label_record_per_question_with_each_class(tmp_path, monkeypatch):
    """TC-UI-41 (b): the record seed, n = 32 >= 30 -> the per-question figure with its n
    (pooled kappa 49/81 = 0.60, TC-STATS-44) and each class with its date."""
    world = vs.ValidityStore(tmp_path / "w")
    try:
        first = _administer(world, "class-a", A_SYSTEM, A_TEACHER)
        _administer(world, "class-b", B_SYSTEM, (), skip=True)
        _administer(world, "class-c", C_SYSTEM, C_TEACHER)
        _publish(world)
        with served(world, monkeypatch) as origin, \
                spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
            label = _labels(origin, first.run_id)[vs.HOLISTIC]
            for route, section in _record_sections(page, origin, first):
                assert section.locator(".record-headline").count() == 0, route
                figures = section.locator(".record-figures > li").all_inner_texts()
                assert figures == [f"{label} (overall judgements): agreement beyond chance "
                                   f"{49 / 81:.2f} — 32 answers"], (route, figures)
                assert _classes(section) == [
                    ["class-a", _today(), "12 blind answers"],
                    ["class-b", _today(), "the blind sample was skipped"],
                    ["class-c", _today(), "20 blind answers"],
                ], (route, _classes(section))
                text = section.inner_text()
                assert "%" not in text and not re.search(r"accura", text, re.I), text
            assert_clean(page, log)
    finally:
        world.close()
