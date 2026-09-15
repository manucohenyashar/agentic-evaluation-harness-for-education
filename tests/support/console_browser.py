"""E6 — the headless-browser session `TS-49` (issue #130) drives against the served console.

Test plan §4.5: *"E6 — headless browser: the three browser-level console facts
(`FR-CONSOLE-17/18`, service worker) — Playwright or equivalent against the loopback console."*
`localStorage`, `sessionStorage`, service-worker registrations, the Cache Storage API and the
network log are facts about a browser, not about markup: `CT-CONSOLE-C06` and `TC-REVIEW-19` scan
the served HTML for the code that *could* reach them, and say in their own docstrings that the
runtime half is this one.

**The browser.** Playwright's Python driver (`requirements-dev.txt`) launching an installed
Chromium-family browser by channel — Edge, then Chrome — so no browser download is needed on a
developer machine. When neither the driver nor a browser is available the session reports
`unavailable` with the reason, and the caller skips *naming the missing dependency*: a silently
passing browser case is worse than a visibly skipped one.

**Transport.** Playwright talks to its driver over stdio pipes, and the browser is its own
process, so the suite's socket guard (which patches this interpreter's `socket` module) neither
sees nor blocks the session's traffic. The **network log is therefore the oracle** for requests —
`context.on("request")` records every request the browser context issues — every page, frame,
popup and subresource — and each navigation waits for network idle, so a request fired just after
load is not cancelled by the next navigation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

#: The browser channels tried in order: both are Chromium-family and ship with the platforms this
#: suite runs on (Windows, `windows-only-suite-seams`), so the driver needs no downloaded browser.
BROWSER_CHANNELS = ("msedge", "chrome")

#: Per-navigation budget, env-gated (seam 3). A console that serves a page answers a loopback request
#: in milliseconds; the budget exists so a server that accepts nothing fails the case in seconds,
#: not minutes — and a slower box raises it without a code change.
NAVIGATION_TIMEOUT_MS = int(os.environ.get("HARNESS_E6_NAVIGATION_TIMEOUT_MS", "5000"))


@dataclass
class VisitedView:
    route: str
    status: int | None
    title: str
    html: str
    error: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class BrowserSession:
    """What one session observed. Everything here is read from the browser, never from the
    console under test."""

    unavailable: str | None = None
    origin: str = ""
    views: list[VisitedView] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    local_storage: list[tuple[str, str]] | None = None
    session_storage: list[tuple[str, str]] | None = None
    service_workers: int | None = None
    cache_entries: list[str] | None = None
    cache_texts: list[str] = field(default_factory=list)
    inspection_error: str | None = None

    def foreign_requests(self) -> list[str]:
        """Every recorded request whose origin is not the console's own."""
        own = urlsplit(self.origin)
        return [
            url for url in self.requests
            if urlsplit(url).scheme in ("http", "https", "ws", "wss")
            and (urlsplit(url).hostname, urlsplit(url).port) != (own.hostname, own.port)
        ]


def run_browser_session(origin: str, routes: list[str]) -> BrowserSession:
    """Visit each route on `origin` in one browser context, then inspect that context's storage.

    Storage is read on the console's own origin (a document on `about:blank` has no storage to
    read). If no view loaded, the inspection is attempted on the origin root anyway, and any error
    is recorded rather than raised — the caller decides what an uninspectable session means.
    """
    session = BrowserSession(origin=origin)
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        session.unavailable = f"the Playwright driver is not installed ({error}); pip install -r requirements-dev.txt"
        return session

    with sync_playwright() as driver:
        browser = None
        launch_errors = []
        for channel in BROWSER_CHANNELS:
            try:
                browser = driver.chromium.launch(channel=channel, headless=True)
                break
            except PlaywrightError as error:
                launch_errors.append(f"{channel}: {str(error).splitlines()[0]}")
        if browser is None:
            session.unavailable = "no Chromium-family browser could be launched: " + "; ".join(
                launch_errors
            )
            return session
        try:
            context = browser.new_context()
            # On the context, not the page: popups, workers and every page the context opens are
            # recorded too.
            context.on("request", lambda request: session.requests.append(request.url))
            page = context.new_page()
            for route in routes:
                view = VisitedView(route=route, status=None, title="", html="")
                try:
                    response = page.goto(origin + route, timeout=NAVIGATION_TIMEOUT_MS,
                                         wait_until="networkidle")
                    view.status = response.status if response is not None else None
                    view.headers = dict(response.headers) if response is not None else {}
                    view.title = page.title()
                    view.html = page.content()
                except PlaywrightError as error:
                    view.error = str(error).splitlines()[0]
                session.views.append(view)
            _inspect_storage(page, origin, session, PlaywrightError)
        finally:
            browser.close()
    return session


def _inspect_storage(page: Any, origin: str, session: BrowserSession, error_type: type) -> None:
    try:
        if not page.url.startswith(origin):
            page.goto(origin + "/", timeout=NAVIGATION_TIMEOUT_MS, wait_until="load")
        facts = page.evaluate(
            """async () => {
                const entries = (s) => Array.from({length: s.length}, (_, i) => [s.key(i), s.getItem(s.key(i))]);
                const workers = navigator.serviceWorker
                    ? (await navigator.serviceWorker.getRegistrations()).length : 0;
                const cached = [];
                const texts = [];
                if (self.caches) {
                    for (const name of await caches.keys()) {
                        const cache = await caches.open(name);
                        for (const request of await cache.keys()) {
                            cached.push(request.url);
                            const response = await cache.match(request);
                            texts.push(response ? await response.text() : "");
                        }
                    }
                }
                return {local: entries(localStorage), session: entries(sessionStorage),
                        workers, cached, texts};
            }"""
        )
        session.local_storage = [tuple(item) for item in facts["local"]]
        session.session_storage = [tuple(item) for item in facts["session"]]
        session.service_workers = int(facts["workers"])
        session.cache_entries = list(facts["cached"])
        session.cache_texts = list(facts["texts"])
    except error_type as error:
        session.inspection_error = str(error).splitlines()[0]


__all__ = ["BROWSER_CHANNELS", "BrowserSession", "NAVIGATION_TIMEOUT_MS", "VisitedView",
           "run_browser_session"]
