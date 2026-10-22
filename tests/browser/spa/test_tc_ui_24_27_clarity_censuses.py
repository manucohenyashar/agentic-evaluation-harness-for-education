"""TC-UI-24…27 — the clarity censuses (FR-UI-23/24/25/36, `CT-CONSOLE-53`), story T11 of
`console_clarity_test_plan.md` §3.9.

* **TC-UI-24** — walk every SPA route (the shared `SPA_WALK_ROUTES`, extending
  TC-CONSOLE-74's walk): the visible text matches no FR-UI-23 pattern, and Results and
  Review carry none of the four engineering words (finalize, batch, provisional, no-op).
* **TC-UI-25** — for every action the SPA can reach: scroll the button into view at
  1280×720, press it (confirming its dialog), and the outcome banner's box is inside the
  viewport, a toast appears, and the button was disabled while its request was in flight.
  The census enumerates from the live `/api/v1/controls` payload (a clicked action's slug
  must be one the payload lists) and clicks every confirmation-opening button on every
  walked route — so a new action on an existing screen is covered automatically. The edge
  the census cannot see from here: an action on a route outside `SPA_WALK_ROUTES` is the
  route walk's catch (the shared list is where a new route is registered).
* **TC-UI-26** — three refusals (approve with a gap open, delete a graded class,
  out-of-range passing score) each render what / why / next as three visible sentences.
* **TC-UI-27** — input census: every `input`/`select`/`textarea` except `type=search` has
  a visible label and a non-empty `aria-describedby` format line; every whole-number
  field refuses `min-1`, `max+1` and `abc` inline ("Please enter " + the format line)
  with its submit disabled, nothing sent. Where the API serves the hint (the draft gap's
  `answer_hint`), the format line is asserted equal to it.

Markers. `browser` (Playwright, headless — the TS-49 rule: a visibly skipped case, never a
silently passing one) and `integration` (the fast tier excludes it). Isolation: the ENG7
Jev-final world (`clarity_world.seed_jev_final_world`) on a real store over a real loopback
console, plus the recorded AF-09 draft (the recorded authoring corpus — its review screen
carries the whole-number passing-score gap); zero egress, the browser's own request log
being the oracle. The action census (TC-UI-25) gets its own console: it acts, and the
censuses must not depend on each other's mutations.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.support import clarity_world, console_redesign_world as crw, spa
from tests.support.redesign_vocabulary import SPA_WALK_ROUTES
from urllib.parse import urlsplit

pytestmark = [pytest.mark.browser, pytest.mark.integration]

#: TC-UI-25's viewport, pinned: the plan's oracle is the banner inside 1280×720, and
#: Playwright's default happens to match — pinned so a default change cannot silently
#: weaken the oracle.
VIEWPORT = {"width": 1280, "height": 720}

#: The FR-UI-23 patterns (plan §3.9; `teacher_text.py`'s own `_ID` and
#: `VERSION_ID_PATTERN`): a requirement id, a version hash, the internal package prefix,
#: a UUID, a path into the store's files, the template placeholder marks. An `*_id`-named
#: field is exempt **by name** — none is rendered as visible text anyway.
ID_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a requirement id", re.compile(r"\b(?:FR|NFR|CT|TC|ADR|RS)-[A-Z0-9]+(?:-[0-9]+)*\b")),
    ("a version hash", re.compile(r"@[0-9a-f]{12}\b")),
    ("the internal package prefix", re.compile(r"\bpkg-")),
    ("a UUID", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")),
    ("a store-file path", re.compile(r"\S+[\\/]\S*\.(?:sqlite|toml)\b")),
    ("a template placeholder", re.compile(r"\[\[")),
)

#: The engineering words Results and Review must never show (FR-UI-23's word list).
ENGINEERING_WORDS = re.compile(r"\b(finalizes|finalized|finalize|batch|provisional|no-op)\b",
                               re.IGNORECASE)

#: The review screen's whole-number refusal reads its bounds off the format line —
#: "A whole number from 1 to 8." — the one definition the field's check restates.
WHOLE_NUMBER_FORMAT = re.compile(r"A whole number from (-?\d+) to (-?\d+)")


def _ensure_draft_ledger(store: Any, package_id: str) -> None:
    """The package row a draft-only world lacks: the draft job writes only the draft TOML,
    and the context read needs the row (the screens suite's `_ensure_ledger`)."""
    from tests.support.clarity_world import STAMP

    with store.package(package_id).transaction() as tx:
        tx.execute("INSERT OR IGNORE INTO package (package_id, created_at) VALUES (:p, :t)",
                   p=package_id, t=STAMP)


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


@pytest.fixture(scope="module")
def eng7_world(tmp_path_factory: Any) -> Iterator[dict[str, Any]]:
    """The censuses' world: the ENG7 Jev-final seed (published test, graded run, roster)
    and the recorded AF-09 draft (a review screen with the whole-number passing-score
    gap), on one store behind one console. The draft job runs against the live console
    (the corpus's recorded replies); the authoring corpus rides the environment the way
    `served_authoring` sets it."""
    from aeh.console import serve_console
    from aeh.store import open_store

    root = tmp_path_factory.mktemp("ui-census")
    store = open_store(root / "data")
    world = clarity_world.seed_jev_final_world(store)
    try:
        # The authoring corpus rides the environment the way `served_authoring` sets it —
        # `set_world_env` (the sanctioned direct path), restored with the fixture.
        from tests.support.env_hygiene import restore_world_env, set_world_env

        for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
            import os

            os.environ.pop(name, None)
        set_world_env("HARNESS_PROFILE", "dev-ci")
        set_world_env("HARNESS_FIXTURE_DIR", str(crw.RECORDINGS))
        server = serve_console(store=store, run_id=world.synthetic.run_id,
                               cfg=crw.recorded_authoring_config())
    except BaseException:
        store.close()
        raise
    host, port = server.socket.getsockname()[:2]
    origin = f"http://{host}:{port}"
    # The AF-09 draft: a real draft through the console's own authoring job, replaying
    # the recorded model calls (zero egress — the request log asserts it per case).
    _answer, record = crw.run_draft_job(port, "AF-09")
    assert record["state"] == "succeeded", f"the AF-09 draft job ended {record['state']}"
    draft = crw.draft_read(port)["draft"]
    assert draft is not None and draft["missing_pieces"] > 0, (
        "fixture: the AF-09 draft carries no missing pieces to ask about")
    _ensure_draft_ledger(store, draft["package_id"])
    try:
        yield {"origin": origin, "port": port, "store": store, "world": world,
               "draft": draft}
    finally:
        from tests.support.env_hygiene import restore_world_env

        server.terminate()
        restore_world_env()
        store.close()


def test_tc_ui_24_every_route_shows_no_id_and_no_engineering_word(eng7_world, request):
    """`TC-UI-24` (P1) — the route census: every SPA route on the ENG7 world renders no
    FR-UI-23 pattern in its visible text, and Results and Review carry none of the four
    engineering words. The routes come from the shared walk list, so a new screen is
    walked without touching this file."""
    submission_id = next(iter(eng7_world["world"].synthetic.submissions.values()))
    with spa.spa_page(eng7_world["origin"], viewport=VIEWPORT) as (page, log):
        problems: list[str] = []
        for route in SPA_WALK_ROUTES:
            heading = _goto(page, eng7_world["origin"], route, submission_id)
            text = spa.main_text(page)
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
    tmp_path_factory, network_guard, monkeypatch, request
):
    """`TC-UI-25` (P0) — the action census, on its own console (it acts): walk the routes,
    and on each, press every visible action button — confirming its dialog when one
    opens — and assert the outcome banner's box is inside the 1280×720 viewport, a toast
    appears, the button was disabled while pending, and the POST went to a slug the live
    controls payload lists. Empty forms and refused actions are censused too: a refusal
    is an outcome, and its banner obeys the same viewport rule."""
    from aeh.console import serve_console
    from aeh.store import open_store

    root = tmp_path_factory.mktemp("ui-census-actions")
    store = open_store(root / "data")
    world = clarity_world.seed_jev_final_world(store)
    try:
        for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("HARNESS_PROFILE", "dev-ci")
        monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(crw.RECORDINGS))
        server = serve_console(store=store, run_id=world.synthetic.run_id,
                               cfg=crw.recorded_authoring_config())
        host, port = server.socket.getsockname()[:2]
        origin = f"http://{host}:{port}"
        # The draft too, so the review screen's own action is censused.
        _answer, record = crw.run_draft_job(port, "AF-09")
        assert record["state"] == "succeeded", f"the AF-09 draft job ended {record['state']}"
        draft = crw.draft_read(port)["draft"]
        _ensure_draft_ledger(store, draft["package_id"])
        # The census compares slug to slug, both sides built the way the SPA's own
        # `performAction` slugifies (lowercase, spaces and slashes to dashes).
        controls = {row["action"].lower().replace("/", "-").replace(" ", "-")
                    for row in crw._get_json(port, "/api/v1/controls")["controls"]}
        submission_id = next(iter(world.synthetic.submissions.values()))
        with spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
            problems: list[str] = []
            pressed: list[str] = []

            def wait_banner(seconds: float) -> Any:
                """The outcome banner, bounded; `None` when none shows."""
                for _ in range(int(seconds / 0.25)):
                    page.wait_for_timeout(250)
                    banner = page.locator(".outcome-banner")
                    if banner.count():
                        return banner.first
                return None

            for route in SPA_WALK_ROUTES:
                _goto(page, origin, route, submission_id)
                main = page.locator("main")
                buttons = main.locator("button.button, button.button-primary")
                for index in range(buttons.count()):
                    button = buttons.nth(index)
                    if not button.is_visible() or not button.is_enabled():
                        continue
                    label = (button.inner_text() or "").strip()
                    if label == "":
                        continue
                    button.scroll_into_view_if_needed()
                    # The actions log only grows; the delta is index-based, so a second
                    # press of a same-slug action is a fresh POST, not a seen one.
                    before_count = len([u for u in log.api_requests()
                                        if "/api/v1/actions/" in u])
                    button.click()
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
                            _goto(page, origin, route, submission_id)
                            continue
                        confirm.click()
                        # React's discrete-event flush has applied the busy state before
                        # click() returns: the confirm is disabled while in flight.
                        if not confirm.is_disabled():
                            problems.append(
                                f"{route}: “{label}”'s confirm was enabled while in flight")
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
                    problems += spa.raw_errors_in(spa.main_text(page))
                    problems += log.foreign_requests()
                    # Reload the world's view before the next press: an action may have
                    # replaced the screen's own buttons.
                    _goto(page, origin, route, submission_id)
            if len(pressed) < 4:
                problems.append(f"the census pressed only {len(pressed)} actions — the walk "
                                "is not reaching the screens' controls")
            _fail_with(problems)
    finally:
        server.terminate()
        store.close()


def test_tc_ui_26_refusals_show_what_why_next_as_three_sentences(eng7_world, request):
    """`TC-UI-26` (P1) — three refusals, each as three visible sentences: the approve
    screen's disabled reason while the draft's gap stands; the class screen's refusal of a
    graded class's delete (the disclosure the class's own state replaces — its refusal
    text is the screen's answer to the delete); the review screen's field refusal of an
    out-of-range passing score (nothing is sent, the value is kept). The gaps the review
    screen asks one-at-a-time (FR-AUTHOR-31) ahead of the passing-score question are
    answered through the console's own answer door — the drive to the field under test."""
    import json
    import urllib.request

    package_id = eng7_world["draft"]["package_id"]
    draft_route = f"/package/review?package={package_id}"

    def answer_gap(item_id: str, value: str) -> None:
        request = urllib.request.Request(
            f"{eng7_world['origin']}/api/v1/actions/answer-authoring-review",
            data=json.dumps({"package_id": package_id, "item_id": item_id,
                             "value": value}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request) as reply:
            assert reply.status == 200, f"the answer for {item_id!r} did not land"

    with spa.spa_page(eng7_world["origin"], viewport=VIEWPORT) as (page, log):
        problems: list[str] = []

        def sentences_seen(where: str, text: str) -> None:
            """The refusal shape: what, why and next — three visible sentences."""
            got = [s.strip() for s in text.split(".") if s.strip()]
            if len(got) < 3:
                problems.append(f"{where}: the refusal is not three sentences: {text!r}")

        # (a) approve with a gap open: the disabled Approve button's reason beside it.
        _goto(page, eng7_world["origin"], draft_route, "unused")
        reason = page.locator(".approve-section .disabled-reason").first
        if not reason.count() or "cannot be approved" not in reason.inner_text():
            problems.append("approve-with-gap: no visible disabled reason")
        else:
            sentences_seen("approve-with-gap", reason.inner_text())

        # (b) delete a graded class: the class's own state refuses before the teacher
        # asks (FR-CONSOLE-69) — the refusal paragraph that stands where the delete
        # disclosure would be, what/why/next as three sentences.
        _goto(page, eng7_world["origin"], "/class", "unused")
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

        # (c) out-of-range passing score: drive the free-text gaps ahead of it through
        # the console's own answer door — re-reading each round, because an answer can
        # clear one row and surface the same gap under the criterion's own spelling —
        # until the grades gap is the question standing; then refuse the out-of-range
        # value at the field.
        for _ in range(8):
            draft_now = (crw.draft_read(eng7_world["port"]).get("draft") or {})
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
                answer_gap(str(gap["item_id"]), value)
        _goto(page, eng7_world["origin"], draft_route, "unused")
        field = page.locator("main input[inputmode='numeric']").first
        if not field.count() or not field.is_visible():
            problems.append("passing-score: the whole-number gap never became the "
                            "current question")
        else:
            # The out-of-range value is the field's own format line's max + 1 — the
            # range the screen itself states (the draft's own total, the one definition
            # the check restates).
            format_line = page.locator("main #answer-value-format, main [id$='-format']").first
            bounds = WHOLE_NUMBER_FORMAT.search(
                format_line.inner_text() if format_line.count() else "")
            out_of_range = str(int(bounds.group(2)) + 1) if bounds else "9"
            field.fill(out_of_range)
            error = page.locator("main #answer-value-error").first
            if not error.count() or "Please enter" not in (error.inner_text() or ""):
                problems.append("passing-score: no inline refusal at the field")
            send = page.locator("main").get_by_role("button", name=re.compile("send", re.I))
            if not send.count() or not send.first.is_disabled():
                problems.append("passing-score: the send button is not disabled")
            kept = field.input_value()
            if kept != out_of_range:
                problems.append(f"passing-score: the typed value was not kept ({kept!r})")
        problems += log.foreign_requests()
        _fail_with(problems)


def test_tc_ui_27_every_input_has_label_format_line_and_matching_check(eng7_world, request):
    """`TC-UI-27` (P0) — the input census: every `input`/`select`/`textarea` except
    `type=search` has a visible label and a non-empty format line; every whole-number
    field refuses `min-1`, `max+1` and `abc` inline ("Please enter " + the format line)
    with its submit disabled and nothing sent. The draft gap's format line is asserted
    equal to the API-served hint. The walk is per route, from the routes themselves."""
    submission_id = next(iter(eng7_world["world"].synthetic.submissions.values()))
    # The API-served hints for the review screen's gaps (the one read that serves them).
    draft_doc = crw.draft_read(eng7_world["port"])
    served_hints: dict[str, str] = {}
    draft = draft_doc.get("draft") or {}
    for gap in list(draft.get("placeholders") or []) + list(draft.get("points_questions") or []):
        if gap.get("answer_hint"):
            served_hints[str(gap.get("question") or "")] = str(gap["answer_hint"])
    with spa.spa_page(eng7_world["origin"], viewport=VIEWPORT) as (page, log):
        problems: list[str] = []
        for route in SPA_WALK_ROUTES:
            if route == "/results/students/{submission_id}":
                pass  # the student detail's inputs ride the same rules; walked anyway
            _goto(page, eng7_world["origin"], route, submission_id)
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
                # The draft gap's format line is the API's own hint (FR-AUTHOR-31).
                gap_hint = next((hint for question, hint in served_hints.items()
                                 if hint.startswith(f"A whole number from {low} to {high}")),
                                None)
                if route == "/package/review" and gap_hint is not None \
                        and format_line.rstrip(".") != gap_hint.rstrip("."):
                    problems.append(f"{route}: the gap's format line {format_line!r} is not "
                                    f"the served hint {gap_hint!r}")
                for bad, why in ((str(low - 1), "min-1"), (str(high + 1), "max+1"), ("abc", "abc")):
                    field.fill(bad)
                    error = page.locator(f"main #{field_id.replace(' ', '')}-error, "
                                         f"main [id$='-error']").first
                    message = error.inner_text() if error.count() else ""
                    expected = f"Please enter a whole number from {low} to {high}."
                    if message.strip() != expected:
                        problems.append(f"{route}: field {field_id!r} on {why} reads "
                                        f"{message.strip()!r}, not {expected!r}")
                    submit = main.locator("button.button-primary:not([disabled])").first
                    if submit.count():
                        disabled_reason = main.locator(".disabled-reason, p").last
                        # The screen's own wording says why — any visible reason beside the
                        # disabled submit counts; the oracle is the disabled state itself.
                        if not submit.is_disabled() and disabled_reason.count() == 0:
                            problems.append(f"{route}: field {field_id!r} on {why} leaves the "
                                            "submit enabled with no reason")
                    elif not main.locator("button[disabled]").count():
                        problems.append(f"{route}: field {field_id!r} on {why} leaves no "
                                        "disabled submit")
                field.fill("")
            problems += spa.raw_errors_in(spa.main_text(page))
            problems += log.foreign_requests()
        _fail_with(problems)


def _fail_with(problems: list[str]) -> None:
    """The arm pattern's tail: fail naming every problem, or stay quiet."""
    if problems:
        pytest.fail("the census found:\n  " + "\n  ".join(problems))
