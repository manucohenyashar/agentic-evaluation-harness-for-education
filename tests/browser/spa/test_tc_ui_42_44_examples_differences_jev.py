"""Validity T13 (issue #910): the marked examples step, the differences and questions, and the
Jev block, in the browser — TC-UI-42, TC-UI-43, TC-UI-44 (statistical-validity test plan
§3.14; FR-UI-44, FR-UI-45, FR-UI-46, FR-UI-29, CT-CALIB-03).

| Case | What is asserted |
|---|---|
| TC-UI-42 | `#/package/examples`: the heading "Your marked examples" and FR-UI-44's sentence; the format line "Unmarked PDF copies, one per student, 10 to 15 recommended" both in the always-shown line and in the file field's own format line; the marking form is built from the seat component (`data-component="blind-seat"`, TC-UI-38's), one seat per hand-marked part; **Check my examples** shows the elapsed clock "Working — N s" while the check runs and "Done in N s" when it ends; **Skip this step** is present at every sub-step — nothing uploaded, uploaded but unmarked, checking, and checked with the differences showing |
| TC-UI-43 | "Where the system read your rubric differently": the three cause groups with their headings and the model-failure group's "We've reported this; your rubric is not changed."; each difference side by side ("You: …" / "The system: …"), the teacher-inconsistency one with both answers; "Question 1 of 3" … "Question 3 of 3", each with its options (and "In my own words") and two examples; the fixed "a percentage would not tell you" sentence; census of the screen's text: no `%`, no "rate" |
| TC-UI-44 | System status's Jev block, two partitions: on the validity seed with every blind answer on a decision-engine cell, "Jev's answers are final when it is confident and one judge agrees (on). Evidence so far: 12 of 60 blind answers needed." and no warning; on a seed where Jev's answers agree less well than the judges' on one question, the warning names that question and not the other, and the evidence sentence is gone |

Markers. `browser` (Playwright, headless — the TS-49 rule) and `integration` (the fast tier
excludes it). Isolation: rung 4 in the browser over real loopback consoles.

**Worlds.**

* TC-UI-42/43: `tests/support/eng7_examples.py` — the ENG7 class under the shipped panel config
  behind `serve_console()`, the four ENG7 sheets uploaded as the marked examples. Its stand-in
  transport builds each reply from the request (the module docstring says so): the issue's
  "on recordings" is not literal here — no live reply is replayed, and none is hand-written as
  if it were one. The upload and the teacher's marks go over the console's own actions
  (`examples upload` / `examples mark`); **Check my examples** is clicked in the browser, so the
  clock is the SPA's own.
* TC-UI-42's running clock is held deterministically: the judge stand-in waits on an event
  while the check runs, so "Working — N s" is read without racing a four-second job.
* TC-UI-43's three causes come from the shipped triage rule over controlled marks: the system
  marks every line at its lowest level; the teacher marks C1a, C1b and C2 higher on all four
  papers (three rubric-ambiguity questions, each with four examples, two shown); C3 is marked
  `retell` on E7-001 against `none` on E7-004, both at the system's `none` (a teacher
  inconsistency, paired with E7-003 by the shipped rule); and on E7-003 the extractor offers no evidence for Q3
  (`evidence_rule`), which the teacher marked `evidenced` (a model failure).
* TC-UI-44: `tests/support/validity_seed.py` — 12 submissions, both open lines drawn whole,
  marked, Finish, then M-PIPE's `promote_administration`. Which engine scored a cell is read by
  M-STATS from the cell's verdicts (`scoring_engine = 'decision'`); the seed has no verdicts, so
  the case writes one decision verdict per chosen cell through M-JUDGE's own `insert_verdict`
  statement — a disclosed stand-in for the decision engine's write, like the seed's
  `grade_vocabulary` stand-in for M-AGG's.
  - *Evidence arm*: every cell a decision cell; the default minimum of 60.
  - *Failing arm*: on the atomic line (label "Q10") the six decision cells carry the three
    disagreements, the six judge-only cells agree; the holistic line ("Q11") has no decision
    cell. The minimum is lowered to 6 through its declared knob
    (`HARNESS_STATS_ENGINE_MIN_LABELS`, seam 3), read in this process by both the promote and
    the System status read: Q10's decision alpha 0.5 against the judges' 1.0 fails
    non-inferiority; Q11 stays `insufficient_data`.

**Pinned to the implementation, not the plan.** FR-UI-45 quotes the model-failure group's
follow-up line; the other two groups' follow-up lines ("A question below asks how you meant
it.", "Both are shown side by side; nothing is changed.") are the design's paraphrase made
concrete by S18, and are pinned here as served. Likewise the warning's full wording is S19's;
the plan's oracle is that it names the question, which is what TC-UI-44 asserts.

**Written ahead: no** — S18 (#888) and S19 (#889) are merged.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from tests.support import spa
from tests.support.eng7_examples import SHEETS, eng7_examples

pytestmark = [pytest.mark.browser, pytest.mark.integration]

ROUTE = "/#/package/examples"

#: FR-UI-44's heading and sentence, verbatim.
HEADING = "Your marked examples"
INTRO = "Mark a few papers yourself so the system can check it reads your rubric the way you do."
#: FR-UI-44's format line, verbatim.
FORMAT = "Unmarked PDF copies, one per student, 10 to 15 recommended"
#: TC-UI-38's seat component: the blind screen's `data-component`, shared by the examples form.
SEAT = '[data-component="blind-seat"]'
SKIP = "Skip this step"

WORKING = re.compile(r"Working — (\d+ s|\d+ min \d+ s)")
DONE = re.compile(r"Done in (\d+ s|\d+ min \d+ s)")

#: FR-UI-45's three causes, in the screen's order, and the model-failure line it quotes.
CAUSE_HEADINGS = ("The rubric may be unclear", "The system misread a clear rule",
                  "Two similar answers were marked differently")
MODEL_FAILURE_LINE = "We've reported this; your rubric is not changed."
#: The other two follow-up lines, as S18 serves them (pinned to the implementation).
CAUSE_LINES = ("A question below asks how you meant it.", MODEL_FAILURE_LINE,
               "Both are shown side by side; nothing is changed.")
#: FR-UI-45's fixed sentence, verbatim.
NO_PERCENTAGE = ("With a dozen papers you chose, a percentage would not tell you how accurate "
                 "the marking is. That's what the blind sample is for.")
QUESTION_OPTIONS = ["Broaden the description", "Narrow the description", "Keep it as it is",
                    "In my own words"]
#: CT-CALIB-03's census over the screen: "rate" as a word ("accurate" in the fixed sentence is
#: not a rate), and any percent sign.
RATE_WORD = re.compile(r"\brates?\b", re.IGNORECASE)

#: FR-UI-46's sentences, verbatim.
JEV_ON = "Jev's answers are final when it is confident and one judge agrees (on)."
EVIDENCE_12_OF_60 = "Evidence so far: 12 of 60 blind answers needed."

#: TC-UI-43's marks (see the module docstring): the system marks every line at its lowest.
TEACHER_MARKS: dict[str, dict[str, str]] = {
    "E7-001-strong": {"C1a": "present", "C1b": "present", "C2": "full", "C3": "retell"},
    "E7-002-middle": {"C1a": "present", "C1b": "present", "C2": "full", "C3": "none"},
    "E7-003-weak": {"C1a": "present", "C1b": "present", "C2": "full", "C3": "evidenced"},
    "E7-004-mostly-blank": {"C1a": "present", "C1b": "present", "C2": "full", "C3": "none"},
}
#: Q3's prompt, which tells the extractor's request for C3 apart.
Q3_PROMPT = "how Tomas changes"

#: How long a screen may take to show what its read served, in seconds. Env-gated (seam 3).
SETTLE_S = float(__import__("os").environ.get("AEH_TEST_SPA_SETTLE_S", "20"))


def _wait_until(predicate: Any, what: str, timeout: float = SETTLE_S) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    raise AssertionError(f"timed out after {timeout:.0f} s waiting for {what}")


def _open_examples(page: Any, origin: str) -> str:
    page.goto(origin + ROUTE)
    heading = spa.wait_for_screen(page)
    _wait_until(lambda: INTRO in spa.main_text(page), "the examples step's read")
    return heading


def _skip_buttons(page: Any) -> int:
    return page.locator("main").get_by_role("button", name=SKIP, exact=True).count()


class _StoodDown:
    """The socket guard as a `browser` case receives it: stood down (the conftest yields None,
    the TS-49 rule), so the worlds' install/uninstall calls are no-ops. The network oracle is
    the browser's own request log."""

    def install(self) -> None:
        pass

    def uninstall(self) -> None:
        pass


@contextmanager
def _served_examples(tmp_path: Path, monkeypatch: Any, network_guard: Any) -> Iterator[Any]:
    with eng7_examples(tmp_path / "data", tmp_path / "work", monkeypatch,
                       network_guard or _StoodDown()) as world:
        yield world


# --- TC-UI-42: the examples step ----------------------------------------------------------------


def test_tc_ui_42_the_examples_step_sentence_format_seats_clock_and_skip_on_every_substep(
        tmp_path, monkeypatch, network_guard):
    """TC-UI-42 (FR-UI-44, FR-UI-29). Four sub-steps visited in turn on one console."""
    gate = threading.Event()

    def held(paper: str, criterion: str, bands: tuple[str, ...], text: str) -> str | None:
        # The check's judge calls wait here, so the clock is read while the check runs.
        gate.wait(120)
        return None

    with _served_examples(tmp_path, monkeypatch, network_guard) as world, \
            spa.spa_page(f"http://127.0.0.1:{world.port}") as (page, log):
        origin = f"http://127.0.0.1:{world.port}"
        try:
            # Sub-step 1: nothing uploaded.
            heading = _open_examples(page, origin)
            assert heading == HEADING, f"the screen's heading is {heading!r}"
            text = spa.main_text(page)
            assert INTRO in text, f"FR-UI-44's sentence is missing:\n{text[:1500]}"
            always = page.locator("main p.examples-test").inner_text()
            assert FORMAT in always, f"the always-shown line lacks the format: {always!r}"
            field = page.locator('main input[type="file"]')
            assert field.count() == 1, "the upload sub-step has no file field"
            described = field.get_attribute("aria-describedby") or ""
            field_format = " ".join(page.locator(f'[id="{ident}"]').inner_text()
                                    for ident in described.split())
            assert FORMAT in field_format, (
                f"the file field's own format line does not give the format: {field_format!r}")
            assert _skip_buttons(page) == 1, "no 'Skip this step' before anything is uploaded"

            # Sub-step 2: uploaded, not yet marked — the form is the seat component.
            _, job = world.upload()
            assert job["state"] == "succeeded", f"fixture: the upload ended {job}"
            page.reload()
            _open_examples(page, origin)
            form = page.locator("main form.examples-form")
            _wait_until(lambda: form.count() == 1, "the first paper's marking form")
            parts = len(world.examples_read()["examples"][0]["parts"])
            seats = form.locator(SEAT)
            assert parts > 0 and seats.count() == parts, (
                f"the marking form shows {seats.count()} seat components for {parts} parts "
                f"(the form must be built from TC-UI-38's {SEAT})")
            assert form.locator(f'{SEAT} input[type="radio"]').count() > 0, (
                "the seat component on the form offers no levels to choose")
            assert _skip_buttons(page) == 1, "no 'Skip this step' while the papers are unmarked"

            # Sub-step 3: marked, then Check my examples — the clock while it runs.
            world.mark({stem: dict(TEACHER_MARKS[stem]) for stem in SHEETS})
            world.judge_rule = held
            page.reload()
            _open_examples(page, origin)
            check = page.locator("main section[aria-label='Check my examples']")
            check.get_by_role("button", name="Check my examples").click()
            clock = check.locator(".run-clock")
            _wait_until(lambda: clock.count() and WORKING.fullmatch(clock.inner_text().strip()),
                        "the running clock 'Working — N s'")
            assert _skip_buttons(page) == 1, "no 'Skip this step' while the check runs"

            # Sub-step 4: the check ends — "Done in …", the differences, and Skip still there.
            gate.set()
            done = page.locator("main p.run-clock")
            _wait_until(lambda: done.count() and DONE.search(done.first.inner_text()),
                        "the finished clock 'Done in N s'")
            finished = done.first.inner_text().strip()
            assert re.fullmatch(r"Your examples were checked\. Done in (\d+ s|\d+ min \d+ s)",
                                finished), f"the finished clock reads {finished!r}"
            _wait_until(lambda: page.locator("main section.examples-cause").count() > 0,
                        "the differences after the check")
            assert _skip_buttons(page) == 1, (
                "no 'Skip this step' once the differences and questions are shown")
            assert not log.page_errors, f"page errors: {log.page_errors}"
            assert not log.foreign_requests(), f"egress: {log.foreign_requests()}"
        finally:
            gate.set()


# --- TC-UI-43: the differences and the questions ------------------------------------------------


def test_tc_ui_43_differences_by_cause_three_questions_fixed_sentence_and_no_rate(
        tmp_path, monkeypatch, network_guard):
    """TC-UI-43 (FR-UI-45, CT-CALIB-03)."""
    with _served_examples(tmp_path, monkeypatch, network_guard) as world:
        world.evidence_rule = lambda paper, prompt: not (
            paper == "E7-003-weak" and Q3_PROMPT in prompt)
        _, job = world.upload()
        assert job["state"] == "succeeded", f"fixture: the upload ended {job}"
        world.mark(TEACHER_MARKS)
        _, job = world.grade()
        assert job["state"] == "succeeded", f"fixture: the check ended {job}"
        origin = f"http://127.0.0.1:{world.port}"
        with spa.spa_page(origin) as (page, log):
            _open_examples(page, origin)
            questions = page.locator("main article.examples-question")
            causes = page.locator("main section.examples-cause")
            _wait_until(lambda: causes.count() == 3 and questions.count() == 3,
                        "three cause groups and three questions")

            headings = [causes.nth(i).locator("h3").inner_text().strip() for i in range(3)]
            assert tuple(headings) == CAUSE_HEADINGS, f"the cause groups read {headings}"
            lines = [causes.nth(i).locator("p.step-note").first.inner_text().strip()
                     for i in range(3)]
            assert tuple(lines) == CAUSE_LINES, f"the cause groups' next lines read {lines}"

            # Each difference side by side: "You: …" and "The system: …".
            for i in range(3):
                for row in causes.nth(i).locator("ul.examples-differences > li").all():
                    row_text = row.inner_text()
                    assert re.search(r"^You: \S", row_text, re.M) and re.search(
                        r"^The system: \S", row_text, re.M), (
                        f"a difference under {headings[i]!r} is not side by side:\n{row_text}")
            failure = causes.nth(1).inner_text()
            assert "E7-003-weak.pdf" in failure and "You: evidenced" in failure \
                and "The system: none" in failure, (
                    f"the model-failure group does not show E7-003's Q3:\n{failure}")
            paired = causes.nth(2).locator("ul.examples-differences > li").first
            sides = paired.locator(".examples-side")
            assert sides.count() == 2, "the teacher inconsistency does not show both answers"
            # Both answers the system put at `none`, with the teacher's two different marks: the
            # shipped triage pairs E7-001 (retell) with the first other paper at the same system
            # level and a different mark, E7-003 (evidenced).
            first, second = sides.nth(0).inner_text(), sides.nth(1).inner_text()
            assert "E7-001-strong.pdf" in first and re.search(r"^You: retell$", first, re.M), (
                f"the first side is not E7-001 marked retell:\n{first}")
            assert "E7-003-weak.pdf" in second and re.search(r"^You: evidenced$", second, re.M), (
                f"the paired side is not E7-003 with the teacher's own mark:\n{second}")

            # The questions: "Question N of 3", options, two examples each.
            for number in range(3):
                card = questions.nth(number)
                assert card.locator("h3").inner_text().strip() == f"Question {number + 1} of 3"
                options = [label.inner_text().strip()
                           for label in card.locator("fieldset label").all()]
                assert options == QUESTION_OPTIONS, (
                    f"question {number + 1} offers {options}")
                examples = card.locator(".examples-side")
                assert examples.count() == 2, (
                    f"question {number + 1} shows {examples.count()} examples, not two")
                for example in examples.all():
                    side = example.inner_text()
                    assert "You: " in side and "The system: " in side, side
            assert page.locator("main").get_by_role("button", name="Send my answers").count() == 1

            sentence = page.locator("main p.examples-sentence").inner_text().strip()
            assert sentence == NO_PERCENTAGE, f"the fixed sentence reads {sentence!r}"

            # Census: the screen as the teacher reads it.
            text = spa.main_text(page)
            problems = [f"'%' in {line!r}" for line in text.splitlines() if "%" in line]
            problems += [f"'rate' in {line!r}" for line in text.splitlines()
                         if RATE_WORD.search(line)]
            assert not problems, "the differences screen gives a rate:\n  " + \
                "\n  ".join(problems)
            assert not log.page_errors, f"page errors: {log.page_errors}"
            assert not log.foreign_requests(), f"egress: {log.foreign_requests()}"


# --- TC-UI-44: the Jev block --------------------------------------------------------------------


def _decision_cells(world: Any, administration: Any, cells: list[tuple[int, str]]) -> None:
    """One decision-engine verdict per named cell, through M-JUDGE's `insert_verdict` (the
    disclosed stand-in for the decision engine's write): the cell's system band, so the
    engine's answer is the score the teacher's blind mark is compared with."""
    from aeh.judge.schema import JUDGE_STATEMENTS
    from tests.support.validity_seed import BANDS

    handle = world.store.cohort(administration.cohort_id)
    with handle.transaction() as tx:
        for index, criterion in cells:
            submission = administration.submission(index)
            work_id = tx.execute(
                "SELECT work_id FROM work_unit WHERE run_id = :r AND submission_id = :s "
                "AND criterion_id = :c AND stage = 'score'",
                r=administration.run_id, s=submission, c=criterion)[0]["work_id"]
            band = administration.system[(submission, criterion)]
            tx.execute(JUDGE_STATEMENTS["insert_verdict"], verdict_id=f"jev-{work_id}",
                       work_id=work_id, judge_id="jev", band=band,
                       band_ordinal=BANDS[criterion].index(band), self_confidence=0.95,
                       cited_spans="[]", evidence_sufficient=1, uncited=0,
                       evidence_assessment="", latency_ms=1, scoring_engine="decision",
                       engine_build="jev@seed", reanchored=0)


@contextmanager
def _status_world(root: Path, monkeypatch: Any, network_guard: Any,
                  decision: list[tuple[int, str]]) -> Iterator[str]:
    """The validity seed with `decision` cells scored by the engine, marked, finished and
    promoted, behind one loopback console; yields the origin."""
    from aeh.console import serve_console
    from tests.support.console_redesign_world import _close_console_store
    from tests.support.validity_seed import (
        VALIDITY_ESCALATED,
        VALIDITY_PROVISIONAL,
        VALIDITY_SYSTEM,
        VALIDITY_TEACHER,
        ValidityStore,
        teacher_bands,
    )

    world = ValidityStore(root)
    try:
        administration = world.administer("c-validity", VALIDITY_SYSTEM,
                                          provisional=VALIDITY_PROVISIONAL,
                                          escalated=VALIDITY_ESCALATED)
        _decision_cells(world, administration, decision)
        seats = world.draw(administration, 24)
        marked = world.mark(administration, seats,
                            teacher_bands(administration, VALIDITY_TEACHER))
        assert marked == 24, f"fixture: {marked} of 24 seats marked"
        world.finish(administration)
        outcome = world.promote(administration, "finish")
        assert outcome.promoted, f"fixture: not promoted: {outcome.reason!r}"
        for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
            monkeypatch.delenv(name, raising=False)
        guard = network_guard or _StoodDown()
        guard.uninstall()
        try:
            server = serve_console(store=world.store, run_id=administration.run_id)
            host, port = server.socket.getsockname()[:2]
            try:
                yield f"http://{host}:{port}"
            finally:
                server.terminate()
        finally:
            guard.install()
    finally:
        _close_console_store(world.store)


def _jev_block(page: Any, origin: str) -> Any:
    page.goto(origin + "/#/status")
    spa.wait_for_screen(page)
    block = page.locator('main [data-component="jev-block"]')
    _wait_until(lambda: block.count() == 1, "the Jev block on System status")
    return block


def test_tc_ui_44_a_the_jev_block_counts_the_evidence_toward_sixty(
        tmp_path, monkeypatch, network_guard):
    """TC-UI-44, evidence partition: 12 blind answers on decision cells, minimum 60."""
    from tests.support.validity_seed import ATOMIC, HOLISTIC

    monkeypatch.delenv("HARNESS_STATS_ENGINE_MIN_LABELS", raising=False)
    monkeypatch.delenv("HARNESS_JEV_FINAL_ON_ACCEPT", raising=False)  # the default: on
    cells = [(index, line) for index in range(12) for line in (ATOMIC, HOLISTIC)]
    with _status_world(tmp_path / "w", monkeypatch, network_guard, cells) as origin, \
            spa.spa_page(origin) as (page, log):
        block = _jev_block(page, origin)
        opening = block.locator("p").first.inner_text().strip()
        assert opening == f"{JEV_ON} {EVIDENCE_12_OF_60}", (
            f"the Jev block reads {opening!r}")
        assert block.locator("[data-noninferiority]").count() == 0, (
            "a non-inferiority warning is shown with too few answers to judge it")
        assert not log.page_errors, f"page errors: {log.page_errors}"


def test_tc_ui_44_b_a_failing_non_inferiority_warning_names_the_question(
        tmp_path, monkeypatch, network_guard):
    """TC-UI-44, failing partition: Q10's decision cells hold its three disagreements."""
    from tests.support.validity_seed import ATOMIC

    monkeypatch.setenv("HARNESS_STATS_ENGINE_MIN_LABELS", "6")
    # Atomic disagreements are on submissions 5, 6 and 7 (the seed's confusion matrix).
    cells = [(index, ATOMIC) for index in (0, 5, 6, 7, 8, 9)]
    with _status_world(tmp_path / "w", monkeypatch, network_guard, cells) as origin, \
            spa.spa_page(origin) as (page, log):
        block = _jev_block(page, origin)
        warning = block.locator('[data-noninferiority="failing"]')
        assert warning.count() == 1, f"no warning in the Jev block:\n{block.inner_text()}"
        assert warning.get_attribute("role") == "alert"
        said = warning.inner_text()
        assert re.search(r"\bQ10\b", said), f"the warning does not name Q10: {said!r}"
        assert not re.search(r"\bQ11\b", said), f"the warning names Q11 as well: {said!r}"
        assert "Evidence so far" not in block.inner_text(), (
            "the evidence sentence is shown beside measured figures")
        assert not log.page_errors, f"page errors: {log.page_errors}"
