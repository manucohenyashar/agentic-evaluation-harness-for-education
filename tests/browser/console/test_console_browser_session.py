"""`TS-49` (issue #130) — the browser-level console facts, in a real headless browser (E6).

Test plan §5.19 and §6.5: `TC-CONSOLE-40` (`FR-CONSOLE-17`), `TC-CONSOLE-41` / `SEC-12`
(`FR-CONSOLE-18`), the composite `TC-CONSOLE-37` (`NFR-CONSOLE-04`), and the declared
limitation `TC-CONSOLE-42` (`NFR-CONSOLE-07`). Rung 4: the console is served for real
(`serve_console`) over a real store carrying a scored run and a student narrative, and a real
Chromium-family browser visits it through Playwright (`tests/support/console_browser.py`).

**Why a browser.** `CT-CONSOLE-C06` and `TC-REVIEW-19` scan the served *markup* for code that
could write to storage or reach another origin, and both name this suite as the runtime half:
`localStorage`, `sessionStorage`, service-worker registrations, Cache Storage and the network log
are facts only a browser holds.

**Non-vacuity comes first.** An empty browser has empty storage and makes no foreign request, so
every clause here is anchored: each visited view must be the console's real page (HTTP 200, the
screen's own `<title>`), and the student view must carry the sentinel student text — otherwise
"no student text in storage" is a statement about a session that never saw any.

**Markers.** `browser` (E6) and `integration`: the fast tier (`scripts/test.sh`) excludes neither
`browser` nor `e2e`, so without `integration` a machine lacking the E6 environment — or a red
case — would fail the Stop-hook gate. When the Playwright driver or a browser is unavailable the
cases skip, naming the missing piece.

**`TC-CONSOLE-42` — not automatable, by declaration.** English and left-to-right only in the MVP is
a *stated limitation* with no failing case (test plan §2.3 Q-11, §7.4). Its visible-degradation
consequence is asserted by `CT-CONSOLE-C24`
(`test_tc_console_c24_non_english_and_rtl_content_fails_or_degrades_visibly`); the limitation
itself is recorded here so the RTM names where the case lives, and nothing is asserted for it.

**Written ahead of implementation.** The issue says `yes`; stale for the console (`M-CONSOLE`
landed, #122 … #127). These are written against the shipped `serve_console`.
"""

from __future__ import annotations

import pytest

from aeh.console import SCREENS, build_console, serve_console
from aeh.store import open_store
from tests.support.console_browser import run_browser_session
from tests.support.console_security_vocabulary import browser_storage_writes, external_origins
from tests.support.console_world import seed_scored_run

pytestmark = [pytest.mark.browser, pytest.mark.integration]

#: Student text no page would render by accident, planted in the data the student view reads.
SENTINEL_TEXT = "Ngozi-Sentinel-7731 argued that evaporation outpaces rainfall in July"

#: The three views `TC-CONSOLE-40` names, with the `<title>` each screen renders.
_VIEWS = {
    "review": (SCREENS["S9"], "Review queue"),
    "blind": (SCREENS["S11"], "Blind sample"),
    "student": (SCREENS["S13"], "Student detail"),
}


def _fail_with(problems: list[str]) -> None:
    assert not problems, "\n\n".join(problems)


def _served_world(tmp_data_dir):
    """A real store with a scored run and a narrative carrying the sentinel, served for real."""
    store = open_store(tmp_data_dir)
    world = seed_scored_run(store, submissions=2)
    student = world.submissions[0]
    # Disclosed M-SYNTH stand-in: the narrative row the student view reads (`_SELECT_NARRATIVE`).
    with store.cohort(world.cohort_id).transaction() as tx:
        tx.execute(
            "INSERT INTO narrative (narrative_id, submission_id, run_id, level, question_id, "
            "text, score_claim_flag) VALUES (:n, :s, :r, 'l1_question', 'Q1', :t, 0)",
            n=f"nar-{student}-Q1", s=student, r=world.run_id, t=SENTINEL_TEXT,
        )
    assert SENTINEL_TEXT in build_console(store=store).render(SCREENS["S13"], ref=student).html, (
        "fixture: the student view does not render the sentinel narrative, so a browser session "
        "over it would hold no student text to leak"
    )
    server = serve_console(store=store, run_id=world.run_id)
    host, port = server.socket.getsockname()[:2]
    origin = f"http://{host}:{port}"
    routes = {
        "review": _VIEWS["review"][0].replace("{id}", world.run_id),
        "blind": _VIEWS["blind"][0].replace("{id}", world.run_id),
        "student": _VIEWS["student"][0].replace("{ref}", student),
    }
    return store, server, origin, routes, world


def _session_or_skip(origin: str, routes: dict[str, str]):
    session = run_browser_session(origin, list(routes.values()))
    if session.unavailable:
        pytest.skip(f"E6 unavailable: {session.unavailable}")
    return session


def _views_rendered(session, routes: dict[str, str]) -> list[str]:
    """The non-vacuity clause: every visited view is the console's real page."""
    problems = []
    for name, route in routes.items():
        view = next(v for v in session.views if v.route == route)
        expected_title = _VIEWS[name][1]
        if view.error or view.status != 200 or expected_title not in view.title:
            problems.append(
                f"the {name} view at {session.origin}{route} did not render as the console's page "
                f"(status={view.status}, title={view.title!r}, error={view.error!r}). Storage and "
                f"network assertions over a session that never loaded a view prove nothing "
                f"(FR-CONSOLE-17/18 are about the console's pages in a browser). [Diagnosis when "
                f"this suite was written: serve_console's configured socket listens but never "
                f"accepts, and its child answers every request with plain-text 'console page'.]"
            )
        elif name == "student" and SENTINEL_TEXT not in view.html:
            problems.append("the student view loaded without the sentinel student text")
    return problems


# --- TC-CONSOLE-40 — no browser storage of student text, no service worker, no cache ---------------


def test_tc_console_40_a_browser_session_leaves_no_storage_worker_or_cache_behind(tmp_data_dir):
    """`TC-CONSOLE-40` / `FR-CONSOLE-17` (invariant 12, runtime half) — browser storage inspection.

    One session visits the review, blind and student views. Afterwards, on the console's origin:
    `localStorage` and `sessionStorage` are empty, no service worker is registered, and no Cache
    Storage entry exists (so none can hold student text) — each read from the browser itself. The
    HTTP cache is not inspectable through the page, so its half is the response itself: the student
    view is served `Cache-Control: no-store`.
    """
    store, server, origin, routes, world = _served_world(tmp_data_dir)
    try:
        session = _session_or_skip(origin, routes)
        problems = _views_rendered(session, routes)
        student_view = next(v for v in session.views if v.route == routes["student"])
        cache_control = {k.lower(): v for k, v in student_view.headers.items()}.get(
            "cache-control", "")
        if student_view.status == 200 and "no-store" not in cache_control.lower():
            problems.append(
                f"the student view is served with Cache-Control {cache_control!r}: without "
                f"no-store the browser's HTTP cache may keep student text (FR-CONSOLE-17: no "
                f"client-side cache)"
            )
        if session.inspection_error:
            problems.append(f"the browser's storage could not be inspected on {origin}: "
                            f"{session.inspection_error}")
        else:
            if session.local_storage:
                problems.append(f"localStorage holds {session.local_storage!r}")
            if session.session_storage:
                problems.append(f"sessionStorage holds {session.session_storage!r}")
            if session.service_workers:
                problems.append(f"{session.service_workers} service worker(s) registered")
            if session.cache_entries:
                problems.append(f"Cache Storage holds {session.cache_entries!r}")
            if any(SENTINEL_TEXT in text for text in session.cache_texts):
                problems.append("a Cache Storage entry holds the sentinel student text")
        _fail_with(problems)
    finally:
        server.terminate()
        store.close()


# --- TC-CONSOLE-41 / SEC-12 — zero requests to any origin but the console's own -------------------


def test_tc_console_41_sec_12_a_full_session_requests_nothing_from_another_origin(tmp_data_dir):
    """`TC-CONSOLE-41` / `SEC-12` / `FR-CONSOLE-18` (invariant 13, runtime half) — network log.

    The same session's recorded requests — navigations and every subresource the pages pulled —
    must all be to the console's own origin. Anchored: the log must contain the console's own
    navigations, so an empty log (a browser that recorded nothing) cannot pass.
    """
    store, server, origin, routes, world = _served_world(tmp_data_dir)
    try:
        session = _session_or_skip(origin, routes)
        problems = _views_rendered(session, routes)
        own = [url for url in session.requests if url.startswith(origin)]
        if len(own) < len(routes):
            problems.append(f"the network log recorded {len(own)} request(s) to {origin} for "
                            f"{len(routes)} navigations — the log is not recording the session")
        foreign = session.foreign_requests()
        if foreign:
            problems.append(f"the session requested other origins: {foreign} — no CDN, web font, "
                            f"analytics or telemetry (FR-CONSOLE-18, SEC-12)")
        _fail_with(problems)
    finally:
        server.terminate()
        store.close()


# --- TC-CONSOLE-37 — the composite: loopback, no browser storage, no external origins -------------


def test_tc_console_37_the_running_console_is_loopback_storage_free_and_origin_closed(
    tmp_data_dir,
):
    """`TC-CONSOLE-37` / `NFR-CONSOLE-04` — composed from `TC-CONSOLE-05/17/18` and their runtime
    halves, over one running console:

    * **05** — the bound socket (`getsockname()`, the witness the code cannot fake) is loopback;
    * **17/18 static halves** — every screen rendered over this store, the student view included,
      carries no storage-reaching script and no external reference (the `CT-CONSOLE-C06` scanners),
      anchored on the pages referencing real assets and on the sentinel appearing;
    * **17/18 runtime halves** — the browser session's storage and network log, as in `-40`/`-41`.
    """
    store, server, origin, routes, world = _served_world(tmp_data_dir)
    try:
        problems: list[str] = []
        host = server.socket.getsockname()[0]
        if host not in ("127.0.0.1", "::1"):
            problems.append(f"the running console is bound to {host!r}, not loopback")

        app = build_console(store=store)
        assets = 0
        saw_sentinel = False
        for screen, route in app.screens().items():
            params = {
                "id": world.cohort_id if screen == "S6" else world.run_id,
                "ref": world.submissions[0],
                "version": world.package_version_id,
            }
            html = app.render(route, **params).html
            assets += html.count("<link") + html.count("<script") + html.count("<img")
            saw_sentinel = saw_sentinel or SENTINEL_TEXT in html
            problems.extend(f"{screen} reaches {api}" for api in browser_storage_writes(html))
            problems.extend(f"{screen} references {o}" for o in external_origins(html))
        assert assets and saw_sentinel, "fixture: the static sweep saw no assets or no student text"
        # The loopback and static halves are complete here; a missing E6 environment must not
        # turn their failures into a skip.
        if problems:
            _fail_with(problems + ["(the browser half was not run: the halves above already fail)"])

        session = _session_or_skip(origin, routes)
        problems.extend(_views_rendered(session, routes))
        if session.inspection_error:
            problems.append(f"storage uninspectable: {session.inspection_error}")
        elif session.local_storage or session.session_storage or session.service_workers \
                or session.cache_entries:
            problems.append("the browser holds console state after the session")
        if session.foreign_requests():
            problems.append(f"foreign requests: {session.foreign_requests()}")
        _fail_with(problems)
    finally:
        server.terminate()
        store.close()
