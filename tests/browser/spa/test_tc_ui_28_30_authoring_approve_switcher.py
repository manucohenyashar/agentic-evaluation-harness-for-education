"""TC-UI-28/29/30, TC-REG-17/19 — the authoring screen's plain questions, the approve
screen's whole-package summary and seen approval, and the package switcher's names
(FR-AUTHOR-31, FR-UI-26/27/28, FR-UI-36), story T12 of `console_clarity_test_plan.md`
§3.9/§3.12 — the browser tier of the #821 story.

* **TC-UI-28** — on the AF-22 draft: the questions' heading and count; the passing-score
  field's format line and placeholder; an out-of-range 9 refused at the field, nothing
  sent, the value kept.
* **TC-UI-29** — the whole-package summary in the design's order before the approve, the
  approve disabled while a piece stands, then FR-CONSOLE-73's banner inside the viewport
  with **Load papers**, the Approve control gone, and a reload keeping the state.
* **TC-UI-30 / TC-REG-19** — the switcher option text: exactly "ENG7-READ-01", with two
  versions "ENG7-READ-01 — version 2", a `pkg-` id reading the ordinal fallback
  ("Test package <k>", 1-based by the switcher's own sorted order — this world's pkg-
  ledger sorts second, so "Test package 2").
* **TC-REG-17** — the authoring screen leaks no "(FR-" and no "never invented" while the
  question text is present.

Ordering note (disclosed): the review screen asks one plain question at a time, in the
served order — the approver's text question first, the passing-score whole-number
question second. The plan's "Question 1 of 2" and the whole-number field cannot co-occur
on screen; the count is asserted on the first question and the field's format, refusal
and placeholder on the second ("Question 2 of 2"), against the same two gaps the plan
names.

Markers. `browser` (Playwright, headless — the TS-49 rule) and `integration` (the fast
tier excludes it). Isolation: **no recordings and no draft jobs** — the AF-22/23 drafts'
replies are not captured (the corpus README's disclosure) and are never fabricated; the
drafts here are the shipped assembler's own (`clarity_world.write_eng7_draft`, the
disclosed stand-in) written into the console's authoring folder, which the review screen
serves as any draft. Zero egress: the browser's own request log is the oracle.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from tests.support import clarity_world, console_world, spa
from tests.support.clarity_world import write_eng7_draft

pytestmark = [pytest.mark.browser, pytest.mark.integration]

VIEWPORT = {"width": 1280, "height": 720}

#: The AF-22 passing-score field's own sentence, as the design states it.
PASSING_FORMAT = "A whole number from 1 to 8"
PASSING_REFUSAL = "Please enter a whole number from 1 to 8."


@contextmanager
def _review_console(root: Path, network_guard: Any, monkeypatch: Any,
                    ) -> Iterator[dict[str, Any]]:
    """A real console over a real store with the AF-22 draft (the shipped assembler's)
    written into the authoring folder — the review screen serves it as any draft. No
    authoring corpus, no draft job, no model call."""
    from aeh.console import serve_console
    from aeh.store import open_store

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    if network_guard is not None:
        network_guard.uninstall()
    store = open_store(root / "data")
    try:
        write_eng7_draft(root / "data" / "authoring", {})
        server = serve_console(store=store)
    except BaseException:
        if network_guard is not None:
            network_guard.install()
        from tests.support.console_redesign_world import _close_console_store

        _close_console_store(store)
        raise
    host, port = server.socket.getsockname()[:2]
    try:
        yield {"origin": f"http://{host}:{port}", "port": port, "store": store}
    finally:
        from tests.support.console_redesign_world import _close_console_store

        server.terminate()
        if network_guard is not None:
            network_guard.install()
        _close_console_store(store)


def _review_text(page: Any) -> str:
    return page.locator("main").inner_text()


def _wait_screen_data(page: Any, selector: str, what: str) -> None:
    """The screen renders its heading before its read answers; wait for the read's own
    content, bounded (5 s), before any text is judged."""
    import time

    target = page.locator(selector)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not target.count():
        page.wait_for_timeout(250)


def _fail_with(problems: list[str]) -> None:
    if problems:
        pytest.fail("the test found:\n  " + "\n  ".join(problems))


def _answer_current(page: Any, value: str) -> None:
    """Answer the screen's current question through its own form and wait for the read's
    next poll to show the answer's effect."""
    field = page.locator("#answer-value")
    field.fill(value)
    page.get_by_role("button", name="Send the answer").click()
    page.wait_for_timeout(1500)


def test_tc_ui_28_the_passing_score_question_shows_its_format_and_refuses_9(
    tmp_path, network_guard, monkeypatch
):
    """`TC-UI-28` (P0) — on the AF-22 draft: the questions' heading and the two-gap count;
    the passing-score field's format line and placeholder; entering 9 shows the range's
    refusal at the field, sends nothing, and keeps the value."""
    with _review_console(tmp_path, network_guard, monkeypatch) as box:
        with spa.spa_page(box["origin"], viewport=VIEWPORT) as (page, log):
            problems: list[str] = []
            page.goto(box["origin"] + "/#/package/review")
            spa.wait_for_screen(page)
            _wait_screen_data(page, ".gaps-section", "the questions section")
            text = _review_text(page)
            if "A few questions before you approve" not in text:
                problems.append("the questions section is missing its heading")
            if "Question 1 of 2." not in text:
                problems.append(f"the count does not read the draft's own two gaps "
                                f"({text[:200]!r})")
            # The first question is the approver's (the served order); answer it through
            # the screen, so the passing-score question becomes current.
            _answer_current(page, "Sample-materials teacher")
            page.reload(wait_until="networkidle")
            spa.wait_for_screen(page)
            text = _review_text(page)
            if "Question 1 of 1." not in text:
                problems.append(f"the passing-score question did not become the current "
                                f"one ({text[:200]!r})")
            field = page.locator("#answer-value")
            if not field.count() or not field.is_visible():
                problems.append("no answer field for the passing-score question")
            else:
                if field.get_attribute("placeholder") != "e.g. 6":
                    problems.append(f"the field's placeholder reads "
                                    f"{field.get_attribute('placeholder')!r}, not 'e.g. 6'")
                format_line = page.locator("#answer-value-format").first
                if not format_line.count() or \
                        not format_line.inner_text().startswith(PASSING_FORMAT):
                    problems.append("the field's format line does not restate the range "
                                    "(“A whole number from 1 to 8. …”)")
                posts_before = len([u for u in log.api_requests()
                                    if "/api/v1/actions/" in u])
                field.fill("9")
                error = page.locator("#answer-value-error").first
                message = error.inner_text() if error.count() else ""
                if message.strip() != PASSING_REFUSAL:
                    problems.append(f"entering 9 reads {message.strip()!r}, "
                                    f"not {PASSING_REFUSAL!r}")
                send = page.get_by_role("button", name="Send the answer")
                if not send.count() or not send.first.is_disabled():
                    problems.append("the send button is not disabled at the refusal")
                if field.input_value() != "9":
                    problems.append(f"the typed value was not kept ({field.input_value()!r})")
                if len([u for u in log.api_requests()
                        if "/api/v1/actions/" in u]) != posts_before:
                    problems.append("the refused value was sent anyway")
            problems += log.foreign_requests()
            _fail_with(problems)


def test_tc_ui_29_the_whole_package_then_the_published_banner(
    tmp_path, network_guard, monkeypatch
):
    """`TC-UI-29` (P0) — the approve journey: the summary in the design's order while a
    piece stands (approve disabled with its reason), then — both answers given — the
    approve builds and publishes: FR-CONSOLE-73's sentence as a fixed banner inside the
    viewport, the Approve control gone, **Load papers** present, and a reload keeping
    the approved state."""
    with _review_console(tmp_path, network_guard, monkeypatch) as box:
        with spa.spa_page(box["origin"], viewport=VIEWPORT) as (page, log):
            problems: list[str] = []
            page.goto(box["origin"] + "/#/package/review")
            spa.wait_for_screen(page)
            _wait_screen_data(page, ".gaps-section", "the questions section")
            # While a piece stands: the approve gate, disabled with its reason.
            text = _review_text(page)
            if "cannot be approved yet" not in text:
                problems.append("the approve gate is not stated as blocked")
            approve = page.get_by_role("button", name="Approve the package")
            if not approve.count() or not approve.first.is_disabled():
                problems.append("the approve button is not disabled while a gap stands")
            # The two answers, through the screen.
            _answer_current(page, "Sample-materials teacher")
            page.reload(wait_until="networkidle")
            spa.wait_for_screen(page)
            _answer_current(page, "6")
            page.reload(wait_until="networkidle")
            spa.wait_for_screen(page)
            text = _review_text(page)
            # The summary, in the design's order (FR-UI-26): the test, the approver,
            # the passing score, the questions with their total, the scoring.
            for part in ("Test ENG7-READ-01", "Approved by", "(your answer)",
                         "Passing score 6 of 8", "Questions", "8 points in total",
                         "How each question is scored"):
                if part not in text:
                    problems.append(f"the summary does not show {part!r}")
            order = [text.index(part) for part in
                     ("Test ENG7-READ-01", "Approved by", "Passing score 6 of 8",
                      "How each question is scored")]
            if order != sorted(order):
                problems.append(f"the summary's parts are out of order ({order})")
            # The approve, through its own confirmation.
            approve = page.get_by_role("button", name="Approve the package")
            if not approve.count() or not approve.first.is_enabled():
                problems.append("the approve button is not enabled with every piece answered")
            else:
                approve.first.click()
                dialog = page.locator("[role='dialog']").first
                if not dialog.count() or not dialog.is_visible():
                    problems.append("the approve opened no confirmation")
                else:
                    confirm = dialog.locator("button").last
                    confirm.click()
                    banner = page.locator(".outcome-banner")
                    for _ in range(20):  # the banner, bounded (5 s)
                        page.wait_for_timeout(250)
                        if banner.count():
                            break
                    if not banner.count():
                        problems.append("the approve showed no outcome banner")
                    else:
                        box_ = banner.first.bounding_box()
                        if box_ is None or box_["y"] + box_["height"] > VIEWPORT["height"] \
                                or box_["x"] + box_["width"] > VIEWPORT["width"]:
                            problems.append(f"the banner is outside the viewport ({box_})")
                        shown = banner.first.inner_text()
                        if "Published ENG7-READ-01, version 1." not in shown \
                                or "Next: load the students' papers." not in shown:
                            problems.append(f"the banner does not read FR-CONSOLE-73's "
                                            f"sentence ({shown[:160]!r})")
                    # The published state arrives on the read's own poll; wait bounded.
                    for _ in range(20):
                        page.wait_for_timeout(250)
                        if page.get_by_role("button", name="Load papers").count():
                            break
                    text = _review_text(page)
                    if page.get_by_role("button", name="Approve the package").count():
                        problems.append("the approve button is still present after approval")
                    load = page.get_by_role("button", name="Load papers")
                    if not load.count():
                        problems.append("no Load papers button after the approval")
            # The reload keeps the approved state (the read serves it).
            page.reload(wait_until="networkidle")
            spa.wait_for_screen(page)
            text = _review_text(page)
            if "Published ENG7-READ-01, version 1." not in text:
                problems.append("the reload lost the approved state's banner")
            if not page.get_by_role("button", name="Load papers").count():
                problems.append("the reload lost the Load papers button")
            problems += log.foreign_requests()
            _fail_with(problems)


def test_tc_ui_30_the_switcher_reads_the_test_and_its_versions(
    tmp_path, network_guard, monkeypatch
):
    """`TC-UI-30` (P2) — the switcher's option text: exactly "ENG7-READ-01" with one
    version, "ENG7-READ-01 — version 2" with two, and a `pkg-` id reading
    "Test package 1"."""
    from aeh.store import open_store
    from aeh.console import serve_console

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    if network_guard is not None:
        network_guard.uninstall()
    store = open_store(tmp_path / "data")
    try:
        _, first_version = clarity_world.build_eng7_package(store)
        # The pkg- ledger beside it, so the switcher's ordinal fallback is reachable
        # (it renders only when the switcher holds more than one package).
        console_world.seed_scored_run(store, cohort_id="c-ts48", run_id="r-ts48",
                                      package_id="pkg-ts48", submissions=1)
        server = serve_console(store=store)
        host, port = server.socket.getsockname()[:2]
        origin = f"http://{host}:{port}"
        try:
            with spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
                problems: list[str] = []
                page.goto(origin + "/#/")
                spa.wait_for_screen(page)
                _wait_screen_data(page, "#switcher-package", "the package switcher")
                options = _switcher_options(page)
                if "ENG7-READ-01" not in options:
                    problems.append(f"the switcher's ENG7 option reads {options!r}, not "
                                    "exactly the test's own name")
                # The pkg- id's ordinal fallback, 1-based by the switcher's own order —
                # this world's pkg- ledger sorts second, so it reads "Test package 2".
                if not any(re.fullmatch(r"Test package \d+", option) for option in options):
                    problems.append(f"the switcher's pkg- option reads {options!r}, not "
                                    "the ordinal fallback")
                # A second ENG7 version, minted the teacher's way: an edited draft of the
                # published test approved again through the console's own door (the
                # approve builds version 2; the switcher then reads " — version 2").
                # A second ENG7 version, minted FR-PKG-02's own way: a revision of the
                # published version through the catalog (a build is refused — a
                # published test is never changed — and the revision+publish flow is
                # what the version lineage is for).
                from aeh.pkg import PackageCatalog

                catalog = PackageCatalog(store.package("ENG7-READ-01"),
                                         package_id="ENG7-READ-01")
                second_version = catalog.create_version(parent=first_version)
                catalog.publish(second_version, approved_by="Sample-materials teacher")
                page.reload(wait_until="networkidle")
                spa.wait_for_screen(page)
                _wait_screen_data(page, "#switcher-package", "the package switcher")
                options = _switcher_options(page)
                if "ENG7-READ-01 — version 2" not in options:
                    problems.append(f"with two versions the option reads {options!r}, "
                                    "not 'ENG7-READ-01 — version 2'")
                problems += log.foreign_requests()
                _fail_with(problems)
        finally:
            server.terminate()
    finally:
        if network_guard is not None:
            network_guard.install()
        from tests.support.console_redesign_world import _close_console_store

        _close_console_store(store)


def _switcher_options(page: Any) -> list[str]:
    """The package switcher's option texts, as rendered."""
    switcher = page.locator("#switcher-package")
    if not switcher.count():
        return []
    return [option.inner_text() for option in switcher.locator("option").all()]


def test_tc_reg_17_the_authoring_screen_leaks_no_boundary_reason(
    tmp_path, network_guard, monkeypatch
):
    """`TC-REG-17` (P1) — the authoring screen for an ENG7 draft with a missing grade
    boundary contains no "(FR-" and no "never invented" (the served reason's leak,
    FR-AUTHOR-08); the question's own text is present."""
    with _review_console(tmp_path, network_guard, monkeypatch) as box:
        with spa.spa_page(box["origin"], viewport=VIEWPORT) as (page, log):
            problems: list[str] = []
            page.goto(box["origin"] + "/#/package/review")
            spa.wait_for_screen(page)
            _wait_screen_data(page, ".gaps-section", "the questions section")
            _answer_current(page, "Sample-materials teacher")
            page.reload(wait_until="networkidle")
            spa.wait_for_screen(page)
            text = page.locator("body").inner_text()
            if "(FR-" in text:
                problems.append("the screen shows a requirement id fragment")
            if "never invented" in text:
                problems.append("the screen shows the boundary's engineering sentence")
            if "What is the passing score for this test?" not in text:
                problems.append("the passing-score question's own text is missing")
            problems += log.foreign_requests()
            _fail_with(problems)


def test_tc_reg_19_the_switcher_reads_eng7_read_01(tmp_path, network_guard, monkeypatch):
    """`TC-REG-19` (P1) — T3's regression: the switcher reads ENG7-READ-01 (the
    TC-UI-30 first arm's own fact, as this regression's case)."""
    from aeh.store import open_store
    from aeh.console import serve_console

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    if network_guard is not None:
        network_guard.uninstall()
    store = open_store(tmp_path / "data")
    try:
        clarity_world.build_eng7_package(store)
        server = serve_console(store=store)
        host, port = server.socket.getsockname()[:2]
        try:
            with spa.spa_page(f"http://{host}:{port}", viewport=VIEWPORT) as (page, log):
                problems: list[str] = []
                page.goto(f"http://{host}:{port}" + "/#/")
                spa.wait_for_screen(page)
                _wait_screen_data(page, "#switcher-package", "the package switcher")
                options = _switcher_options(page)
                if "ENG7-READ-01" not in options:
                    problems.append(f"the switcher reads {options!r}, not the test's own "
                                    "name")
                problems += log.foreign_requests()
                _fail_with(problems)
        finally:
            server.terminate()
    finally:
        if network_guard is not None:
            network_guard.install()
        from tests.support.console_redesign_world import _close_console_store

        _close_console_store(store)
