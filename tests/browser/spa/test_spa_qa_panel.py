"""Issue #639 — `TC-UI-06`: the SPA's Q&A panel renders a grounded answer whose citations are
links to real anchors on the manuals page, under a persistent answers-only affordance (FR-UI-06).

Rung 3 (E6): the real console server over a real store, a Chromium-family browser. The answer
comes from the recorded QA provider the server is configured with below the nightly tier
(operator test plan §4 rule 7) — never a live model. Which question the recorded double grounds is
`M-HELP`'s (#636); the question used is `spa.QA_MANUALS_QUESTION`, invented and declared there.

**Written ahead of #638** (and of #634/#636 beneath it): `writtenahead`, keyed in
`WRITTEN_AHEAD_BLOCKERS` on the bundle carrying FR-UI-06's affordance wording. Red today on the
missing bundle (`NotImplementedYet` naming #634), before any server or browser starts.

The anchor oracle is the browser's own: a citation "resolves" when following it lands on the
manuals page and `document.getElementById(<fragment>)` finds an element there — not when the href
merely has a `#`.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import pytest

from tests.support import spa
from tests.support.impl import require_path

pytestmark = [pytest.mark.browser, pytest.mark.integration]


def _affordance_problems(scope, when: str) -> list[str]:
    text = scope.inner_text()
    return [f"the answers-only affordance is missing {p.pattern!r} {when}"
            for p in spa.AFFORDANCE_PATTERNS if not p.search(text)]


@pytest.mark.writtenahead
def test_tc_ui_06_a_manuals_answer_cites_real_anchors_under_the_answers_only_affordance(
    tmp_data_dir,
):
    """`TC-UI-06` / FR-UI-06 (P1) — open manuals & help from the hub, ask the panel a manuals
    question: the answer renders with at least one citation link; every citation is same-origin,
    names a fragment, and following it lands on the manuals page with an element of that id; the
    affordance "this assistant answers questions; it does not operate the system" is on the panel
    before the question and still there after the answer (persistent)."""
    require_path(spa.BUNDLE_INDEX, "the committed SPA bundle (FR-UI-01)", issue="#634")
    from aeh.console import serve_console
    from aeh.store import open_store
    from tests.support.console_world import seed_scored_run

    store = open_store(tmp_data_dir)
    world = seed_scored_run(store, submissions=1)
    server = serve_console(store=store, run_id=world.run_id)
    host, port = server.socket.getsockname()[:2]
    origin = f"http://{host}:{port}"
    try:
        with spa.spa_page(origin) as (page, log):
            problems: list[str] = []
            spa.go_to(page, origin, "help")
            panel = page.get_by_role("region", name=re.compile(r"question|ask|assistant", re.I)).or_(
                page.get_by_role("complementary", name=re.compile(r"question|ask|assistant", re.I)))
            if not panel.count():
                pytest.fail("manuals & help: no Q&A panel (a region or complementary landmark "
                            "named for questions / the assistant)")
            panel = panel.first
            problems += _affordance_problems(panel, "before a question is asked")
            box = panel.get_by_role("textbox")
            if not box.count():
                pytest.fail("the Q&A panel has no question box")
            box.first.fill(spa.QA_MANUALS_QUESTION)
            panel.get_by_role("button", name=re.compile(r"ask|send|submit", re.I)).first.click()
            citations = panel.locator("a[href*='#']")
            try:
                citations.first.wait_for(state="visible")
            except Exception:
                pytest.fail(f"the answer rendered no citation link "
                            f"(panel text: {panel.inner_text()[:200]!r})")
            problems += _affordance_problems(panel, "after the answer rendered")
            hrefs = [citations.nth(i).get_attribute("href") or "" for i in range(citations.count())]
            for href in hrefs:
                target = href if href.startswith("http") else origin + (href if href.startswith("/")
                                                                       else "/" + href)
                parts = urlsplit(target)
                if f"{parts.scheme}://{parts.netloc}" != origin:
                    problems.append(f"a citation leaves the console's origin: {href}")
                    continue
                if not parts.fragment:
                    problems.append(f"a citation names no anchor: {href}")
                    continue
                page.goto(target, wait_until="networkidle")
                found = page.evaluate("(id) => !!document.getElementById(decodeURIComponent(id))",
                                      parts.fragment)
                if not found:
                    problems.append(f"the citation {href} resolves to no anchor on the manuals page")
            problems += [f"uncaught page error {e!r}" for e in log.page_errors]
            problems += [f"a request left the console's origin: {u}" for u in log.foreign_requests()]
            assert not problems, "\n\n".join(problems)
    finally:
        server.terminate()
        store.close()
