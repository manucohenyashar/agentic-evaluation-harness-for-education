"""Issue #639 — `TC-UI-06`: the SPA's Q&A panel renders a grounded answer whose citations are
links to real anchors on the manuals page, under a persistent answers-only affordance (FR-UI-06).

Rung 3 (E6): the real console server over a real store, a Chromium-family browser. The answer
comes from the recorded QA provider the server is configured with below the nightly tier
(operator test plan §4 rule 7) — never a live model. Which question the recorded double grounds is
`M-HELP`'s (#636); the question used is `spa.QA_MANUALS_QUESTION`, invented and declared there.
The server is configured with the double through `serve_console`'s `help_assistant` seam —
the same way `spa_dir` names a bundle — so no production path invents a model to answer with.

**Landed with #638**: the Q&A panel, the manuals pages the citations point at, and the
`help_assistant` seam above. The `writtenahead` marker and the `WRITTEN_AHEAD_BLOCKERS` entry
(keyed on the bundle carrying FR-UI-06's affordance wording) left with it.

The anchor oracle is the browser's own: a citation "resolves" when following it lands on the
manuals page and `document.getElementById(<fragment>)` finds an element there — not when the href
merely has a `#`.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from urllib.parse import urlsplit

import pytest

from tests.support import help_vocabulary as hv
from tests.support import spa
from tests.support.conf_builders import HOSTED_JUDGE
from tests.support.impl import require_path

pytestmark = [pytest.mark.browser, pytest.mark.integration]

#: The api traffic a recorded session may carry: the hub state read the shell makes on load
#: (not an M-HELP call) and the ask itself (TC-REQ-129). Anything else fails.
ALLOWED_API_PATHS = ("/api/v1/hub", hv.ASK_ROUTE[1])


def _affordance_problems(scope, when: str) -> list[str]:
    text = scope.inner_text()
    return [f"the answers-only affordance is missing {p.pattern!r} {when}"
            for p in spa.AFFORDANCE_PATTERNS if not p.search(text)]


@contextmanager
def _console_with_recorded_qa(tmp_data_dir):
    """The real console server over a seeded store, the recorded QA double wired through
    `serve_console`'s `help_assistant` seam (operator test plan §4 rule 7)."""
    from aeh.console import serve_console
    from aeh.store import open_store
    from tests.support.console_world import seed_scored_run

    store = open_store(tmp_data_dir)
    world = seed_scored_run(store, submissions=1)
    double = hv.QaDouble(tmp_data_dir / "qa-rec")
    assistant = hv.make_assistant(store, double, HOSTED_JUDGE)
    server = serve_console(store=store, run_id=world.run_id, help_assistant=assistant)
    host, port = server.socket.getsockname()[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.terminate()
        store.close()


def _panel(page):
    panel = page.get_by_role("region", name=re.compile(r"question|ask|assistant", re.I)).or_(
        page.get_by_role("complementary", name=re.compile(r"question|ask|assistant", re.I)))
    if not panel.count():
        pytest.fail("manuals & help: no Q&A panel (a region or complementary landmark "
                    "named for questions / the assistant)")
    return panel.first


def _ask(panel, question: str) -> None:
    box = panel.get_by_role("textbox")
    if not box.count():
        pytest.fail("the Q&A panel has no question box")
    box.first.fill(question)
    panel.get_by_role("button", name=re.compile(r"ask|send|submit", re.I)).first.click()


def _traffic_problems(log) -> list[str]:
    """TC-REQ-129: in the recorded session the SPA's api traffic is exactly the hub state read
    and the ask — no other M-HELP endpoint (no manuals read, no cli-help) is called."""
    api = log.api_requests()
    problems = [f"an api call the SPA must not make reached the server: {u}"
                for u in api if urlsplit(u).path not in ALLOWED_API_PATHS]
    if not any(urlsplit(u).path == hv.ASK_ROUTE[1] for u in api):
        problems.append(f"no ask reached the server (api traffic: {api!r})")
    problems += [f"a request left the console's origin: {u}" for u in log.foreign_requests()]
    return problems


def test_tc_ui_06_a_manuals_answer_cites_real_anchors_under_the_answers_only_affordance(
    tmp_data_dir,
):
    """`TC-UI-06` / FR-UI-06 (P1) — open manuals & help from the hub, ask the panel a manuals
    question: the answer renders with at least one citation link; every citation is same-origin,
    names a fragment, and following it lands on the manuals page with an element of that id; the
    affordance "this assistant answers questions; it does not operate the system" is on the panel
    before the question and still there after the answer (persistent)."""
    require_path(spa.BUNDLE_INDEX, "the committed SPA bundle (FR-UI-01)", issue="#634")
    with _console_with_recorded_qa(tmp_data_dir) as origin:
        with spa.spa_page(origin) as (page, log):
            problems: list[str] = []
            spa.go_to(page, origin, "help")
            panel = _panel(page)
            problems += _affordance_problems(panel, "before a question is asked")
            _ask(panel, spa.QA_MANUALS_QUESTION)
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
            problems += _traffic_problems(log)
            assert not problems, "\n\n".join(problems)


def test_tc_ui_06_b_a_not_found_answer_renders_the_pointer_to_the_manuals_page(
    tmp_data_dir,
):
    """`TC-UI-06` / FR-UI-06 arm — a question no manual grounds: the panel renders the explicit
    pointer to the manuals page (a same-origin link), and the model's unsourced recorded reply —
    the hallucinated one the double would hand back — never reaches the answer."""
    require_path(spa.BUNDLE_INDEX, "the committed SPA bundle (FR-UI-01)", issue="#634")
    with _console_with_recorded_qa(tmp_data_dir) as origin:
        with spa.spa_page(origin) as (page, log):
            problems: list[str] = []
            spa.go_to(page, origin, "help")
            panel = _panel(page)
            _ask(panel, hv.NOT_FOUND_T.question)
            pointer = panel.locator("a[href='/manuals']")
            try:
                pointer.first.wait_for(state="visible")
            except Exception:
                pytest.fail(f"a not-found answer rendered no pointer to the manuals page "
                            f"(panel text: {panel.inner_text()[:200]!r})")
            if "442" in panel.inner_text():
                problems.append("the model's hallucinated reply reached the answer")
            if "do not cover" not in panel.inner_text().lower():
                problems.append(f"the not-found branch did not render — the panel text "
                                f"is a failed ask's, not the not-found answer's: "
                                f"{panel.inner_text()[:200]!r}")
            problems += [f"uncaught page error {e!r}" for e in log.page_errors]
            problems += _traffic_problems(log)
            assert not problems, "\n\n".join(problems)


def test_tc_ui_06_c_an_action_implying_question_names_the_console_page_and_calls_only_ask(
    tmp_data_dir,
):
    """`TC-UI-06` / FR-UI-06 failure-path arm (and TC-REQ-129) — "Start the run for me.": the
    answer names the console page the real control lives on, and the recorded session's api
    traffic is exactly the hub read and the ask (TC-REQ-129). That nothing was written is
    `TC-HELP-03`'s rung-2 assertion over the tiers; this case proves the surface only."""
    require_path(spa.BUNDLE_INDEX, "the committed SPA bundle (FR-UI-01)", issue="#634")
    with _console_with_recorded_qa(tmp_data_dir) as origin:
        with spa.spa_page(origin) as (page, log):
            problems: list[str] = []
            spa.go_to(page, origin, "help")
            panel = _panel(page)
            _ask(panel, hv.ACTION_T.question)
            try:
                panel.get_by_text(re.compile(r"run start", re.I)).first.wait_for(state="visible")
            except Exception:
                pytest.fail(f"the answer to an action-implying question does not name the console "
                            f"page (panel text: {panel.inner_text()[:200]!r})")
            problems += [f"uncaught page error {e!r}" for e in log.page_errors]
            problems += _traffic_problems(log)
            assert not problems, "\n\n".join(problems)
