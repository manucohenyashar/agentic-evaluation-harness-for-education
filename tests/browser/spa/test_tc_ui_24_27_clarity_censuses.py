"""TC-UI-24…27 — the clarity censuses (FR-UI-23/24/25/36, `CT-CONSOLE-53`), story T11 of
`console_clarity_test_plan.md` §3.9.

* **TC-UI-24** — walk every SPA route (the shared `SPA_WALK_ROUTES`, extending
  TC-CONSOLE-74's walk): the page body — the header's switchers and sidebar included —
  matches no FR-UI-23 pattern, and Results and Review carry none of the four engineering
  words (finalize, batch, provisional, no-op).
* **TC-UI-25** — for every action the SPA can reach: scroll the button into view at
  1280×720, press it (confirming its dialog), and the outcome banner the press itself
  raised is inside the viewport, a toast appears, and the button was disabled while its
  request was in flight — a dialog's confirm as a busy button, a direct action's own busy
  state. The census enumerates from the live `/api/v1/controls` payload (a clicked
  action's slug must be one the payload lists) and clicks every confirmation-opening
  button on every walked route, so a new action on an existing screen is covered
  automatically. Two edges, named in the tests: a payload action no SPA screen renders is
  reported for the record (the payload also lists the server-rendered screens' actions);
  an action on a route outside the walk list is the route walk's catch.
* **TC-UI-26** — three refusals (approve with a gap open, delete a graded class,
  out-of-range passing score) each render what / why / next as three visible sentences —
  the field-level refusal (the third) is FR-AUTHOR-31's refused-at-the-field shape, so
  its arm asserts the inline refusal, the disabled submit, the kept value and the silent
  network instead of the outcome shape.
* **TC-UI-27** — input census: every `input`/`select`/`textarea` except `type=search` has
  a visible label and a non-empty `aria-describedby` format line; every whole-number
  field refuses `min-1`, `max+1` and `abc` inline ("Please enter " + the format line)
  with its own submit disabled, nothing sent. Where the API serves the hint (the draft
  gap's `answer_hint`), the format line is asserted equal to it.

Markers. `browser` (Playwright, headless — the TS-49 rule: a visibly skipped case, never a
silently passing one) and `integration` (the fast tier excludes it). Isolation: the ENG7
Jev-final world (`clarity_world.seed_jev_final_world`) on a real store over a real loopback
console, plus the recorded AF-09 draft (the recorded authoring corpus — its review screen
carries the whole-number passing-score gap); zero egress, the browser's own request log
being the oracle. TC-UI-25/26/27 each get their own console: they act, and the censuses
must not depend on each other's mutations.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from aeh.console.teacher_text import VERSION_ID_PATTERN, _ID
from tests.support import clarity_browser, clarity_world, console_redesign_world as crw, spa
from tests.support.redesign_vocabulary import SPA_WALK_ROUTES

pytestmark = [pytest.mark.browser, pytest.mark.integration]

#: TC-UI-25's viewport, pinned: the plan's oracle is the banner inside 1280×720, and
#: Playwright's default happens to match — pinned so a default change cannot silently
#: weaken the oracle.
VIEWPORT = {"width": 1280, "height": 720}


@pytest.fixture(scope="module")
def eng7_world(tmp_path_factory: Any) -> Iterator[dict[str, Any]]:
    """The route census's world (TC-UI-24 reads and never writes, so it can share one
    console across the module)."""
    root = tmp_path_factory.mktemp("ui-census")
    with clarity_browser.serve_eng7_world(root, None, None) as world:
        yield world

#: The FR-UI-23 patterns (plan §3.9): a requirement id — `teacher_text.py`'s own `_ID`
#: regex, imported so the census and the boundary can never disagree about what an id is
#: — a version hash (the boundary's own `VERSION_ID_PATTERN`), the internal package
#: prefix, a UUID, a path into the store's files, the template placeholder marks. A
#: student's `*_ref` (shown when the roster holds no name, FR-UI-22) and every `*_id`-
#: named field are exempt by name — the census scans what a teacher reads, and the seed's
#: refs are the seed's own spelling, not the console's copy.
ID_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a requirement id", re.compile(_ID)),
    ("a version hash", re.compile(VERSION_ID_PATTERN)),
    ("the internal package prefix", re.compile(r"\bpkg-")),
    ("a UUID", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")),
    ("a store-file path", re.compile(r"\S+[\\/]\S*\.(?:sqlite|toml)\b")),
    ("a template placeholder", re.compile(r"\[\[")),
)

#: The engineering words Results and Review must never show (FR-UI-23's word list).
ENGINEERING_WORDS = re.compile(r"\b(finalizes|finalized|finalize|batch|provisional|no-op)\b",
                               re.IGNORECASE)

#: The whole-number format line's own bounds — "A whole number from 1 to 8." — the one
#: definition the field's check restates; the boundary arm reads its values from here.
WHOLE_NUMBER_FORMAT = re.compile(r"A whole number from (-?\d+) to (-?\d+)")


def _goto(page: Any, origin: str, route: str, submission_id: str) -> str:
    """Fragment navigation to one walk route (the `{submission_id}` route takes the
    seed's), returning the screen's heading."""
    page.goto(f"{origin}/#{route.format(submission_id=submission_id)}")
    return spa.wait_for_screen(page)


def _hits(text: str) -> list[str]:
    """Every FR-UI-23 pattern the text trips, named."""
    found = []
    for name, pattern in ID_PATTERNS:
        if pattern.search(text):
            found.append(name)
    return found


def _fail_with(problems: list[str]) -> None:
    """The arm pattern's tail: fail naming every problem, or stay quiet."""
    if problems:
        pytest.fail("the census found:\n  " + "\n  ".join(problems))


def test_tc_ui_24_every_route_shows_no_id_and_no_engineering_word(eng7_world):
    """`TC-UI-24` (P1) — the route census: every SPA route on the ENG7 world renders no
    FR-UI-23 pattern in its visible text, and Results and Review carry none of the four
    engineering words. The routes come from the shared walk list, so a new screen is
    walked without touching this file."""
    submission_id = next(iter(eng7_world["world"].synthetic.submissions.values()))
    with spa.spa_page(eng7_world["origin"], viewport=VIEWPORT) as (page, log):
        problems: list[str] = []
        for route in SPA_WALK_ROUTES:
            heading = _goto(page, eng7_world["origin"], route, submission_id)
            # The census scans the page body, not just `main`: the context header's
            # switchers and the sidebar render outside it, and they are exactly where a
            # version's naming lives (FR-CONSOLE-74).
            text = page.locator("body").inner_text()
            if not text.replace(heading, "").strip():
                problems.append(f"{route}: rendered nothing beyond its heading")
            for hit in _hits(text):
                problems.append(f"{route}: shows {hit}")
            if route in ("/results", "/review") and ENGINEERING_WORDS.search(text):
                problems.append(f"{route}: shows an engineering word "
                                f"({ENGINEERING_WORDS.search(text).group(0)!r})")
            problems += spa.raw_errors_in(text)
            problems += log.foreign_requests()
        _fail_with(problems)


def test_tc_ui_25_every_action_shows_its_outcome_inside_the_viewport(
    tmp_path_factory, network_guard, monkeypatch,
):
    """`TC-UI-25` (P0) — the action census, on its own console (it acts): walk the routes,
    and on each, press every visible action button — confirming its dialog when one
    opens — and assert the outcome banner the press raised is inside the 1280×720
    viewport, a toast appears, the button was disabled while pending, and the POST went
    to a slug the live controls payload lists. Empty forms and refused actions are
    censused too: a refusal is an outcome, and its banner obeys the same viewport rule."""
    with clarity_browser.serve_eng7_world(tmp_path_factory.mktemp("ui-census-actions"),
                      network_guard, monkeypatch) as world_box:
        port = world_box["port"]
        origin = world_box["origin"]
        world = world_box["world"]
        # The census compares slug to slug, both sides built the way the SPA's own
        # `performAction` slugifies (lowercase, spaces and slashes to dashes).
        controls = {row["action"].lower().replace("/", "-").replace(" ", "-")
                    for row in crw._get_json(port, "/api/v1/controls")["controls"]}
        submission_id = next(iter(world.synthetic.submissions.values()))
        seed = world.synthetic
        # The action-reach selection, threaded into every navigation: with two cohorts in
        # the world nothing is "lone", so the screens that act need the subject named
        # (class, package, run — the address's own refs, CT-UI-07). The draft screens'
        # subject is the draft's own package (the seed's is published, with no draft).
        draft_package = world_box["draft"]["package_id"]

        def goto_for_actions(route: str) -> str:
            package = draft_package if route in ("/package/review", "/package/edit") \
                else seed.package_id
            return _goto(page, origin,
                         route + f"?class={seed.cohort_id}&package={package}"
                                 f"&run={seed.run_id}",
                         submission_id)

        with spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
            problems: list[str] = []
            pressed: list[str] = []
            pressed_slugs: set[str] = set()

            def wait_banner(seconds: float) -> Any:
                """A NEW outcome banner, bounded; `None` when none shows. Results keeps a
                standing settled-grades banner (FR-UI-33) — it is not an action's
                outcome, so the census excludes it and demands a banner the press itself
                raised."""
                for _ in range(int(seconds / 0.25)):
                    page.wait_for_timeout(250)
                    banner = page.locator(".outcome-banner:not(.results-banner)")
                    if banner.count():
                        return banner.first
                return None

            for route in SPA_WALK_ROUTES:
                goto_for_actions(route)
                main = page.locator("main")
                # Light assists so a gated control is reachable: the review screen's
                # send stays disabled until its current question has a value; the class
                # screen's create stays disabled until the name is typed. The assist is
                # the same typing a teacher does — never a bypass of the gate.
                if route == "/package/review":
                    answer = main.locator("#answer-value")
                    if answer.count() and answer.is_visible():
                        answer.fill("1")
                elif route == "/class":
                    name = main.get_by_label("Class name")
                    if name.count() and name.is_visible():
                        name.fill("Census probe class")
                # The press list is the route's own visible action labels, collected once;
                # each press then starts from a fresh navigation — a press can replace the
                # screen's own buttons, and a stale index would race the re-render.
                labels: list[str] = []
                buttons = main.locator("button.button, button.button-primary")
                for index in range(buttons.count()):
                    button = buttons.nth(index)
                    if not button.is_visible() or not button.is_enabled():
                        continue
                    label = (button.inner_text() or "").strip()
                    if label and label not in labels:
                        labels.append(label)
                for label in labels:
                    goto_for_actions(route)
                    main = page.locator("main")
                    button = main.locator("button.button, button.button-primary") \
                        .filter(has_text=label).first
                    if not button.count() or not button.is_visible() \
                            or not button.is_enabled():
                        continue
                    try:
                        button.scroll_into_view_if_needed()
                    except Exception:
                        # A re-render removed the button between the check and the
                        # scroll: the next _goto re-collects it — nothing to report.
                        continue
                    # The actions log only grows; the delta is index-based, so a second
                    # press of a same-slug action is a fresh POST, not a seen one.
                    before_count = len([u for u in log.api_requests()
                                        if "/api/v1/actions/" in u])
                    try:
                        button.click()
                        # A busy button is disabled in the click's own task (React's
                        # discrete-event flush) — the pending state, asserted for the
                        # direct path here and for a dialog's confirm below.
                        busy_now = not button.is_enabled()
                    except Exception:
                        # An earlier press on this route changed the screen's own state
                        # and this control is legitimately gone (a phase moved on); the
                        # re-collection at the next route's labels starts fresh.
                        continue
                    # Classify the press: the action opens its confirmation (the preview
                    # read may sit between, so the wait is bounded), or posts directly.
                    # A press that does neither — a tab, a toggle, an expander — is not
                    # an action and carries no banner by design.
                    slug: str | None = None
                    dialog_open = False
                    for _ in range(12):
                        page.wait_for_timeout(250)
                        since = [u for u in log.api_requests()
                                 if "/api/v1/actions/" in u][before_count:]
                        if since:
                            slug = urlsplit(since[0]).path.rsplit("/", 1)[-1]
                            break
                        dialog = page.locator("[role='dialog']").first
                        if dialog.count() and dialog.is_visible():
                            dialog_open = True
                            break
                    if not dialog_open and slug is None:
                        continue
                    if dialog_open:
                        dialog = page.locator("[role='dialog']").first
                        confirm = dialog.locator("button").last
                        if not (confirm.count() and confirm.is_enabled()):
                            goto_for_actions(route)
                            continue
                        confirm.click()
                        # React's discrete-event flush has applied the busy state before
                        # click() returns: the confirm is disabled while in flight.
                        if not confirm.is_disabled():
                            problems.append(
                                f"{route}: “{label}”'s confirm was enabled while in flight")
                    elif not busy_now:
                        problems.append(
                            f"{route}: “{label}” posted without disabling while pending "
                            "(FR-UI-24(c))")
                    banner = wait_banner(5.0)
                    if banner is None:
                        problems.append(f"{route}: “{label}” showed no outcome banner")
                        continue
                    since = [u for u in log.api_requests()
                             if "/api/v1/actions/" in u][before_count:]
                    slug = urlsplit(since[0]).path.rsplit("/", 1)[-1] if since else ""
                    if slug not in controls:
                        problems.append(
                            f"{route}: “{label}” posted unlisted slug {slug!r} "
                            f"({since[0] if since else 'no URL captured'}; banner read "
                            f"{banner.inner_text()[:120]!r})")
                    box = banner.bounding_box()
                    if box is None:
                        problems.append(f"{route}: “{label}”'s banner has no box")
                    elif (box["x"] < 0 or box["y"] < 0
                          or box["x"] + box["width"] > VIEWPORT["width"]
                          or box["y"] + box["height"] > VIEWPORT["height"]):
                        problems.append(f"{route}: “{label}”'s banner is outside the viewport "
                                        f"({box})")
                    if not page.locator(".toast").count():
                        problems.append(f"{route}: “{label}” raised no toast")
                    pressed.append(f"{route}:{label}")
                    pressed_slugs.add(slug)
                    problems += spa.raw_errors_in(spa.main_text(page))
                    problems += log.foreign_requests()
            unpressed = sorted(controls - pressed_slugs)
            if unpressed:
                print("controls the walk never pressed (recorded, not failed):",
                      ", ".join(unpressed))
            if len(pressed) < 4:
                problems.append(f"the census pressed only {len(pressed)} actions — the walk "
                                "is not reaching the screens' controls")
            _fail_with(problems)


def _answer_gap(origin: str, package_id: str, item_id: str, value: str) -> None:
    """One answer through the console's own review door — the same enumerated control the
    screen's send posts to, used here to drive past the gaps the field under test waits
    behind."""
    import json
    import urllib.request

    request = urllib.request.Request(
        f"{origin}/api/v1/actions/answer-authoring-review",
        data=json.dumps({"package_id": package_id, "item_id": item_id,
                         "value": value}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request) as reply:
        assert reply.status == 200, f"the answer for {item_id!r} did not land"


def test_tc_ui_26_refusals_show_what_why_next_as_three_sentences(
    tmp_path, network_guard, monkeypatch,
):
    """`TC-UI-26` (P1) — three refusals, each as three visible sentences: the approve
    screen's disabled reason while the draft's gap stands; the class screen's refusal of a
    graded class's delete (the refusal the class's own state serves before the teacher
    asks, FR-CONSOLE-69); the review screen's field refusal of an out-of-range passing
    score — nothing sent, value kept. The gaps the review screen asks one-at-a-time
    (FR-AUTHOR-31) ahead of the passing-score question are driven through the console's
    own answer door, so the field under test is the screen's current question."""
    with clarity_browser.serve_eng7_world(tmp_path, network_guard, monkeypatch) as world_box:
        origin = world_box["origin"]
        package_id = world_box["draft"]["package_id"]
        draft_route = f"/package/review?package={package_id}"
        with spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
            problems: list[str] = []

            def sentences_seen(where: str, text: str) -> None:
                """The refusal shape: what, why and next — three visible sentences."""
                got = [s.strip() for s in text.split(".") if s.strip()]
                if len(got) < 3:
                    problems.append(f"{where}: the refusal is not three sentences: {text!r}")

            # (a) approve with a gap open: the disabled Approve button's reason beside it.
            _goto(page, origin, draft_route, "unused")
            reason = page.locator(".approve-section .disabled-reason").first
            if not reason.count() or "cannot be approved" not in reason.inner_text():
                problems.append("approve-with-gap: no visible disabled reason")
            else:
                sentences_seen("approve-with-gap", reason.inner_text())

            # (b) delete a graded class: the class's own state refuses before the teacher
            # asks (FR-CONSOLE-69) — the refusal paragraph that stands where the delete
            # disclosure would be, what/why/next as three sentences.
            _goto(page, origin, "/class", "unused")
            trigger = page.locator("main").get_by_role(
                "button", name=re.compile("delete this class", re.I))
            refusal = page.locator("main p.refusal-shape").filter(
                has_text=re.compile("cannot be deleted", re.I)).first
            if trigger.count():
                trigger.first.click()
                confirmation = page.locator("main").get_by_role(
                    "group", name=re.compile("delete class", re.I))
                if confirmation.count() and confirmation.first.is_visible():
                    sentences_seen("delete-class", confirmation.first.inner_text())
                else:
                    problems.append("delete-class: the confirmation did not open")
            elif refusal.count():
                sentences_seen("delete-class", refusal.inner_text())
            else:
                problems.append("delete-class: neither a delete disclosure nor the "
                                "class's own refusal text")

            # (c) out-of-range passing score: drive the free-text gaps ahead of it
            # through the answer door — re-reading each round, because an answer can
            # clear one row and surface the same gap under the criterion's own spelling
            # — until a grades gap is the question standing; then refuse the
            # out-of-range value at the field.
            for _ in range(8):
                draft_now = (crw.draft_read(world_box["port"]).get("draft") or {})
                gaps = (list(draft_now.get("placeholders") or [])
                        + list(draft_now.get("points_questions") or []))
                askable = [g for g in gaps
                           if not g.get("waiting_on")
                           and not str(g.get("item_id") or "").startswith("grades")]
                if not askable:
                    break
                for gap in askable:
                    value = ("1" if gap.get("answer_kind") == "whole_number"
                             else "absent: no evidence (0 points); "
                                  "present: the evidence is there (2 points)")
                    _answer_gap(origin, package_id, str(gap["item_id"]), value)
            _goto(page, origin, draft_route, "unused")
            field = page.locator("main input[inputmode='numeric']").first
            if not field.count() or not field.is_visible():
                problems.append("passing-score: the whole-number gap never became the "
                                "current question")
            else:
                # The out-of-range value is the field's own format line's max + 1 — the
                # range the screen itself states (the draft's own total, the one
                # definition the check restates).
                format_line = page.locator(
                    "main #answer-value-format, main [id$='-format']").first
                bounds = WHOLE_NUMBER_FORMAT.search(
                    format_line.inner_text() if format_line.count() else "")
                out_of_range = str(int(bounds.group(2)) + 1) if bounds else "9"
                actions_before = len([u for u in log.api_requests()
                                      if "/api/v1/actions/" in u])
                field.fill(out_of_range)
                error = page.locator("main #answer-value-error").first
                if not error.count() or "Please enter" not in (error.inner_text() or ""):
                    problems.append("passing-score: no inline refusal at the field")
                send = page.locator("main").get_by_role("button",
                                                        name=re.compile("send", re.I))
                if not send.count() or not send.first.is_disabled():
                    problems.append("passing-score: the send button is not disabled")
                kept = field.input_value()
                if kept != out_of_range:
                    problems.append(f"passing-score: the typed value was not kept ({kept!r})")
                if len([u for u in log.api_requests()
                        if "/api/v1/actions/" in u]) != actions_before:
                    problems.append("passing-score: the refused value was sent anyway")
            problems += log.foreign_requests()
            _fail_with(problems)


def test_tc_ui_27_every_input_has_label_format_line_and_matching_check(
    tmp_path, network_guard, monkeypatch,
):
    """`TC-UI-27` (P0) — the input census, on its own console: every
    `input`/`select`/`textarea` except `type=search` has a visible label and a non-empty
    format line; every whole-number field refuses `min-1`, `max+1` and `abc` inline
    ("Please enter " + the format line) with its own submit disabled and nothing sent.
    The draft gap's format line is asserted equal to the API-served hint — the gaps ahead
    of it are driven through the answer door first, so the whole-number field is on
    screen. The walk is per route, from the routes themselves."""
    with clarity_browser.serve_eng7_world(tmp_path, network_guard, monkeypatch) as world_box:
        origin = world_box["origin"]
        port = world_box["port"]
        package_id = world_box["draft"]["package_id"]
        world = world_box["world"]
        submission_id = next(iter(world.synthetic.submissions.values()))
        # The API-served hints for the review screen's gaps (the one read that serves
        # them), and the drive past the gaps ahead of the whole-number one.
        served_hints: dict[str, str] = {}
        for _ in range(8):
            draft_now = (crw.draft_read(port).get("draft") or {})
            gaps = (list(draft_now.get("placeholders") or [])
                    + list(draft_now.get("points_questions") or []))
            for gap in gaps:
                if gap.get("answer_hint"):
                    served_hints[str(gap.get("question") or "")] = str(gap["answer_hint"])
            askable = [g for g in gaps
                       if not g.get("waiting_on")
                       and not str(g.get("item_id") or "").startswith("grades")]
            if not askable:
                break
            for gap in askable:
                value = ("1" if gap.get("answer_kind") == "whole_number"
                         else "absent: no evidence (0 points); "
                              "present: the evidence is there (2 points)")
                _answer_gap(origin, package_id, str(gap["item_id"]), value)
        with spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
            problems: list[str] = []
            for route in SPA_WALK_ROUTES:
                _goto(page, origin, route, submission_id)
                main = page.locator("main")
                fields = main.locator("input:not([type='search']), select, textarea")
                seen: set[tuple[str, str]] = set()
                for index in range(fields.count()):
                    field = fields.nth(index)
                    if not field.is_visible():
                        continue
                    field_id = field.get_attribute("id") or ""
                    kind = field.get_attribute("type") or field.evaluate(
                        "el => el.tagName.toLowerCase()")
                    key = (field_id, kind)
                    if key in seen:
                        continue
                    seen.add(key)
                    # A visible label: the labelled-by text or the wrapping label's text.
                    label = ""
                    if field_id:
                        for_attr = page.locator(f"label[for='{field_id}']").first
                        if for_attr.count():
                            label = for_attr.inner_text()
                    if label == "":
                        wrap = field.locator("xpath=ancestor::label").first
                        if wrap.count():
                            label = wrap.inner_text()
                    if label.strip() == "":
                        problems.append(f"{route}: field {field_id!r} has no visible label")
                    described = field.get_attribute("aria-describedby") or ""
                    format_line = ""
                    if described != "":
                        for_id = page.locator(f"#{described.split(' ')[0]}").first
                        if for_id.count():
                            format_line = for_id.inner_text().strip()
                    if format_line == "":
                        problems.append(f"{route}: field {field_id!r} has no format line")
                    match = WHOLE_NUMBER_FORMAT.search(format_line or "")
                    if match is None:
                        continue
                    low, high = int(match.group(1)), int(match.group(2))
                    # The draft gap's format line is the API's own hint (FR-AUTHOR-31):
                    # on the review screen, the standing question's served hint.
                    gap_hint = next((hint for hint in served_hints.values()
                                     if hint.startswith(f"A whole number from {low} to {high}")),
                                    None)
                    if route == "/package/review" and gap_hint is not None \
                            and format_line.rstrip(".") != gap_hint.rstrip("."):
                        problems.append(f"{route}: the gap's format line {format_line!r} is "
                                        f"not the served hint {gap_hint!r}")
                    # The field's own submit: the primary button in the form (or the
                    # answer form) the field lives in — not just any enabled primary on
                    # the screen.
                    submit = field.locator(
                        "xpath=ancestor::form//button[contains(@class,'button')] | "
                        "ancestor::div[contains(@class,'answer-form')]//button["
                        "contains(@class,'button')]").last
                    actions_before = len([u for u in log.api_requests()
                                          if "/api/v1/actions/" in u])
                    for bad, why in ((str(low - 1), "min-1"),
                                     (str(high + 1), "max+1"), ("abc", "abc")):
                        field.fill(bad)
                        expected = f"Please enter a whole number from {low} to {high}."
                        error = page.locator(f"#{field_id}-error") if field_id else \
                            page.locator("main [id$='-error']").first
                        message = error.first.inner_text() if error.count() else ""
                        if message.strip() != expected:
                            problems.append(f"{route}: field {field_id!r} on {why} reads "
                                            f"{message.strip()!r}, not {expected!r}")
                        if submit.count():
                            if not submit.first.is_disabled():
                                problems.append(f"{route}: field {field_id!r} on {why} "
                                                "leaves its own submit enabled")
                            reason = submit.first.locator(
                                "xpath=following-sibling::span[contains(@class,"
                                "'disabled-reason')]").first
                            if not reason.count() or reason.first.inner_text().strip() == "":
                                problems.append(f"{route}: field {field_id!r} on {why} "
                                                "disables its submit with no reason")
                    if len([u for u in log.api_requests()
                            if "/api/v1/actions/" in u]) != actions_before:
                        problems.append(f"{route}: field {field_id!r} sent a refused value")
                    field.fill("")
                problems += spa.raw_errors_in(spa.main_text(page))
                problems += log.foreign_requests()
            _fail_with(problems)
