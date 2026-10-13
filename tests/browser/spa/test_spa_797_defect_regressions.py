"""PR #797's shipped-defect findings — the two SPA halves, as regressions (`TC-UI-22`,
`TC-UI-23`).

PR #797's screens suite (TC-UI-08…21) flagged three defects in the shipped stories while
writing it. Its cases assert the shipped surface at the defect's spot and name the gap;
this module is the fix's own half — one regression per SPA defect, red against the
unfixed tree before the fix landed, per the fix-issue exception rule:

* `TC-UI-22` — the per-student log panel (for #765): `StudentDetail` declared
  `showDetails` but never set it — the `<details>` expander carried no `onToggle` — so
  the logs read never started and the panel behind Details showed "Reading."
  permanently. The regression opens the expander and demands the run's own records.
* `TC-UI-23` — an immediate op's failure renders nothing (for #764): `DraftEditor`
  recorded every result through `action.finish`, but never rendered `action.outcome`, so
  a move the console refused or errored on showed nothing and (for an error, whose
  landing is unknown) did not re-read. The regressions drive the failure at the action
  route itself — the console's real refusal shape (a 4xx `{"error": …}`), the 500 an
  unreachable or failing save answers, and the dropped connection — and demand the
  outcome line the state model renders, plus the re-read after the error arm (where the
  op may or may not have landed). A refusal mutates nothing, and the fix still re-reads
  once to show the server's truth — arm (a) pins the refusal's rendering itself.

The third finding (the draft save's rename losing to a concurrent reader on Windows) is
server-side and carries its own rung-1 regression:
`tests/unit/author/test_tc_author_43_commit_sharing_retry.py`.

Markers: `browser` (E6) and `integration`, like the neighbouring SPA suites. The failures
are driven at the route, so no egress ever leaves the console's origin — the browser
request log stays the no-egress oracle.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from tests.support import console_redesign_world as crw
from tests.support import spa
from tests.support.console_world import STAMP, seed_scored_run
from tests.support.impl import require_path

pytestmark = [pytest.mark.browser, pytest.mark.integration]

#: The console's action surface: a URL carrying this prefix is a mutation request
#: (`performAction`'s POSTs).
ACTION_URL_MARK = "/api/v1/actions/"


def _require_bundle() -> None:
    require_path(spa.BUNDLE_INDEX, "the committed SPA bundle (FR-UI-01)", issue="#634")


def _fail_with(problems: list[str]) -> None:
    assert not problems, "\n\n".join(problems)


def _health(page: Any, log: spa.SpaLog, where: str) -> list[str]:
    """CT-UI-04's floor, checked after every step: no uncaught error, no unhandled rejection, no
    raw stack trace in what the teacher sees."""
    problems = [f"{where}: uncaught page error {e!r}" for e in log.page_errors]
    problems += [f"{where}: unhandled Promise rejection {r!r}" for r in spa.rejections(page)]
    try:
        text = page.locator("body").inner_text()
    except Exception as error:  # a page without a body is itself the failure
        return problems + [f"{where}: no body to read ({error})"]
    problems += [f"{where}: a raw error reached the page ({p})" for p in spa.raw_errors_in(text)]
    log.page_errors.clear()
    return problems


def _egress_problems(log: spa.SpaLog, where: str) -> list[str]:
    """The no-egress oracle, on every case: nothing the browser requested left the console's
    origin."""
    return [f"{where}: a request left the console's origin: {u}" for u in log.foreign_requests()]


def _action_urls(log: spa.SpaLog) -> list[str]:
    """The session's mutation requests, as the request log names them (see `ACTION_URL_MARK`)."""
    return [u for u in log.requests if ACTION_URL_MARK in u]


def _wait_for(problems: list[str], where: str, page: Any, predicate: Callable[[], bool],
              what: str, timeout_ms: int = 20_000) -> bool:
    """A bounded poll — never a bare sleep: the predicate is retried every 250 ms until it turns
    true or the bound passes; a timeout is a recorded problem, not a hang."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while True:
        try:
            if predicate():
                return True
        except Exception:  # the read may be mid-render; the bound decides, not the exception
            pass
        if time.monotonic() >= deadline:
            problems.append(f"{where}: gave up waiting for {what}")
            return False
        page.wait_for_timeout(250)


def _goto(page: Any, origin: str, path: str) -> str:
    """Fragment navigation to a route; the screen waits on its `main` h1 (the loaded-screen
    rule). A query rides the path (`/package/edit?package=…`)."""
    route = path.split("?", 1)[0]
    page.goto(f"{origin}#{path}", wait_until="domcontentloaded")
    if route in ("", "/"):
        page.wait_for_load_state("networkidle")
        return ""
    return spa.wait_for_screen(page)


# --- the served console -------------------------------------------------------------------------------


@dataclass
class Served:
    data_dir: Path
    store: Any
    server: Any
    origin: str
    port: int


@contextmanager
def _console(tmp_data_dir: Path, network_guard: Any, monkeypatch: Any, *, seed: Any = None,
             authoring: bool = False, cfg: dict[str, Any] | None = None) -> Iterator[Served]:
    """A real console on a real loopback port over a real store, the authoring corpus wired
    in when `authoring` is set (HARNESS_PROFILE=dev-ci + the F-AUTHOR recordings), mirroring
    `tests/support/console_redesign_world.py`'s served fixtures. `seed(store)` runs between
    the open and the serve; whatever it returns names the run in focus."""
    from aeh.console import serve_console
    from aeh.store import open_store

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    if authoring:
        monkeypatch.setenv("HARNESS_PROFILE", "dev-ci")
        monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(crw.RECORDINGS))
    store = open_store(tmp_data_dir)
    focused = None
    if seed is not None:
        focused = seed(store)
    # Browser tests are stood down from the socket guard (`tests/conftest.py`: the E6 oracle is
    # the browser's own request log), so the guard here is None — nothing to uninstall.
    if network_guard is not None:
        network_guard.uninstall()
    try:
        server = serve_console(store=store, run_id=focused, cfg=cfg, config_path=None)
    except BaseException:
        if network_guard is not None:
            network_guard.install()
        crw._close_console_store(store)
        raise
    host, port = server.socket.getsockname()[:2]
    try:
        yield Served(tmp_data_dir, store, server, f"http://{host}:{port}", port)
    finally:
        try:
            server.terminate()
        finally:
            if network_guard is not None:
                network_guard.install()
            crw._close_console_store(store)


def _ensure_ledger(store: Any, package_id: str) -> None:
    """The package row a draft-only world lacks — the context read needs it for the wizard
    to derive the draft's stage (as `tests/support/console_redesign_world.py`'s served
    authoring fixtures do)."""
    handle = store.package(package_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO package (package_id, created_at) VALUES (:p, :t)",
            p=package_id, t=STAMP,
        )


def _draft_reads(log: spa.SpaLog) -> list[str]:
    """The session's editor reads, as the request log names them — the re-read oracle."""
    return [u for u in log.requests if "/api/v1/authoring/draft" in u]


# --- TC-UI-22 — the per-student log panel -------------------------------------------------------------


def test_tc_ui_22_opening_the_details_expander_starts_the_logs_read(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-UI-22` (for #765 / FR-UI-16) — the drill-down's Details expander holds the
    graders' trail and the run's log; opening it starts the logs read, and the panel
    renders the run's own records. Red before the fix: `showDetails` was declared but
    never set (no `onToggle`), so the read never started and the panel read "Reading."
    for as long as the expander stayed open."""
    _require_bundle()

    def _seed(store):
        world = seed_scored_run(store, submissions=2, finalize=True, enumerate_units=True)
        return world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed) as served:
        submission_id = "sub-c-ts48-01"
        doc = crw._get_json(served.port,
                            f"/api/v1/results/student-detail?submission_id={submission_id}")
        assert doc["criteria"], f"the seeded drill-down carries no criteria: {doc!r}"
        assert doc["run_id"], f"the drill-down names no run: {doc!r}"
        logs = crw._get_json(served.port, f"/api/v1/logs?run_id={doc['run_id']}")
        assert logs["records"], (
            f"the seeded world's log read carries no records — the panel would have "
            f"nothing to render even fixed: {logs!r}")

        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            _goto(page, served.origin, f"/results/students/{submission_id}")
            card = page.locator("li.criterion-card").first
            card.locator("details.detail-expander summary").click()
            if not _wait_for(problems, "the log panel", page,
                             lambda: card.locator(".log-list li").count() > 0,
                             "the run's log records to render behind Details"):
                body = card.locator(".detail-body")
                problems.append(f"the panel behind Details reads {body.inner_text()!r} — the "
                                "logs read never started")
            panel_reads = [u for u in log.requests if "/api/v1/logs" in u]
            if not panel_reads:
                problems.append(f"opening Details issued no logs read: {log.requests!r}")
            if "Reading." in card.locator(".detail-body").inner_text():
                problems.append("the panel still reads its loading placeholder after the "
                                "read had every chance to answer")
            problems += _health(page, log, "the drill-down")
            problems += _egress_problems(log, "the drill-down")
            _fail_with(problems)


# --- TC-UI-23 — the immediate op's outcome ------------------------------------------------------------


def test_tc_ui_23_a_failed_immediate_op_renders_the_outcome_and_re_reads(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-UI-23` (for #764 / FR-UI-13) — a move the console refuses renders the refusal
    through the state model's outcome line; an op the console *errors* on (the 500 a
    failing save answers — the landing is unknown) renders the outcome *and* re-reads the
    draft, so the screen shows the server's truth; a dropped connection says the change
    was not sent. Red before the fix: `DraftEditor` recorded every result through
    `action.finish` but never rendered `action.outcome` — every failure here rendered
    nothing at all, and no re-read followed the error."""
    _require_bundle()

    with _console(tmp_data_dir, network_guard, monkeypatch, authoring=True,
                  cfg=crw.recorded_authoring_config()) as served:
        _answer, record = crw.run_draft_job(served.port, "AF-02")
        assert record["state"] == "succeeded", f"the AF-02 draft job ended {record['state']}"
        package_id = crw.draft_read(served.port)["draft"]["package_id"]
        _ensure_ledger(served.store, package_id)

        ACTION = "**/api/v1/actions/edit-draft-package"
        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            _goto(page, served.origin, f"/package/edit?package={package_id}")
            outcome = page.locator("p.action-outcome")
            move_down = page.locator(".editor-card").first.get_by_role(
                "button", name="Move down")

            # (a) the console refuses the move — the refusal shape a 4xx carries. Nothing
            # mutated; the fix still re-reads once to show the server's truth, and what
            # this arm pins is the refusal's rendering in the outcome line.
            page.route(ACTION, lambda route: route.fulfill(
                status=400, content_type="application/json",
                body=json.dumps({"action": "edit draft package",
                                 "error": "the draft refuses the move: the grading point "
                                          "must keep grading a question it has"})))
            move_down.click()
            if not _wait_for(problems, "arm (a)", page,
                             lambda: outcome.count() > 0,
                             "the refusal to render in the outcome line"):
                problems.append("arm (a): the refused move rendered nothing at all")
            elif "Refused:" not in outcome.first.inner_text() or \
                    "the grading point must keep grading" not in outcome.first.inner_text():
                problems.append(f"arm (a): the outcome reads {outcome.first.inner_text()!r} "
                                "— not the console's refusal in the state model's shape")
            page.unroute(ACTION)

            # (b) the console errors — the 500 a failing save answers. The landing is
            # unknown, so the screen re-reads the draft: the server's state is the truth.
            reads_before = _draft_reads(log)
            page.route(ACTION, lambda route: route.fulfill(
                status=500, content_type="application/json",
                body=json.dumps({"action": "edit draft package",
                                 "error": "the draft file could not be replaced: the file "
                                          "is held open by another process"})))
            move_down.click()
            if not _wait_for(problems, "arm (b)", page,
                             lambda: outcome.count() > 0 and
                             "held open by another process" in outcome.first.inner_text(),
                             "the failed op's outcome to render"):
                problems.append("arm (b): the errored move rendered nothing at all")
            if not _wait_for(problems, "arm (b), the re-read", page,
                             lambda: len(_draft_reads(log)) > len(reads_before),
                             "the draft read to re-run after the errored op"):
                problems.append(f"arm (b): the errored move did not re-read the draft "
                                f"({len(reads_before)} reads before) — the landing was "
                                f"unknown, the screen must show the server's truth")
            page.unroute(ACTION)

            # (c) the console unreachable — the dropped connection is caught and says the
            # change was not sent, never left as an unhandled rejection. The change was
            # never sent, so no re-read follows: the absence is given a settle window, not
            # a bare assertion at the first poll.
            reads_before = _draft_reads(log)
            page.route(ACTION, lambda route: route.abort())
            move_down.click()
            if not _wait_for(problems, "arm (c)", page,
                             lambda: outcome.count() > 0 and
                             "could not be reached" in outcome.first.inner_text(),
                             "the dropped connection to render in the outcome line"):
                problems.append("arm (c): the unreachable console rendered nothing at all")
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline and len(_draft_reads(log)) == len(reads_before):
                page.wait_for_timeout(250)
            if len(_draft_reads(log)) != len(reads_before):
                problems.append("arm (c): the dropped connection re-read the draft — the "
                                "change was never sent, there is nothing to reconcile")
            page.unroute(ACTION)

            problems += _health(page, log, "the editor")
            problems += _egress_problems(log, "the editor")
            if not _action_urls(log):
                problems.append("the immediate ops never reached the enumerated surface")
            _fail_with(problems)
