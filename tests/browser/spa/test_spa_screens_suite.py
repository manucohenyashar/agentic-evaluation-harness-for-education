"""Issue #772 — the redesigned SPA's screens in a real browser (E6): the wizard stepper, the
context header, the authoring screens, the editor, the state model, results and override, the
secondary pages, settings, help, the confirm-free rule, the state-rendering pairs and the
budgets (`TC-UI-08` … `TC-UI-21`).

Operator test plan §3.5, module M-UI, rung Browser (E6): the real console server
(`serve_console`) over a seeded real store — or, on the authoring arms, over the recorded
F-AUTHOR corpus — with a Chromium-family browser through Playwright, loopback only. Every
dependency story is merged (#763, #764, #765, #766, #768, #771): **written ahead of
implementation, no** — these cases are expected green.

**The DOM contract.** The redesigned bundle renders the wizard home (`section.wizard`, no
level-1 heading — the stepper is `ol[aria-label="The nine stages"]`) and the secondary screens
(each a `main` h1 named by `Screen title=`). The contract these cases read is the ui/src source
(`ui/src/screens/*`, `ui/src/wizard/*`); the old hub vocabulary in `tests/support/spa.py`
(`HUB_DESTINATIONS`) names the pre-redesign hub, so this suite navigates by the fragment's own
route (`#/issues?run=…`), never by hub cards.

**Markers.** `browser` (E6) and `integration`: the fast tier excludes `integration`, which keeps
a machine without E6 out of the Stop-hook gate (TS-49's rule).

**The oracles, and every interpretation the plan's wording needed** (each is applied uniformly,
named here, and never silently weakened):

* **No egress** — every case asserts `log.foreign_requests()` empty; the browser request log is
  the no-egress oracle on every case, per the plan.
* **No confirm-free posts (`TC-UI-19`)** — `SpaLog` records request *URLs*, not methods, so the
  "no mutation request" oracle is: no request URL contains `/api/v1/actions/` (the console's
  action surface, `performAction`'s `POST /api/v1/actions/{slug}`). The authoring *preview*
  (`POST /api/v1/authoring/preview`) is a read-shaped POST and deliberately does not trip this
  oracle. The blind-sample screen's band select posts immediately **by design** (its documented
  Phase-1 behaviour); `TC-UI-19` walks the select/toggle surfaces the *redesign* introduced —
  switchers, results filters, the override band select, job rows, parked actions, settings —
  which is the defect's generalized regression over those surfaces.
* **Stale read (`TC-UI-13`)** — the plan's "stale read" failure is exercised as the read that
  can no longer be satisfied: the console the screen was reading is gone, and the screen must
  render the failure banner. The refusal arms (upload refusal, field error) carry the same
  template's other shapes, asserted where the redesign actually renders them.
* **Placeholders (`TC-UI-08` (b), `TC-UI-11`)** — the plan says "a draft with placeholders" and
  its arm (a) once said "2 placeholders"; the recorded AF-09 draft carries **four** review
  items (`approved_by`, `model_answer`, `criterion Q1`, `grades A`) — the same oracle at the
  larger boundary, reconciled exactly as the merged `TC-CONSOLE-64` (#771) reconciles it.
* **Switch-run "navigates to stage 7" (`TC-UI-09`)** — the shipped header switcher changes only
  the address (its own `CT-UI-09` contract is spelled in `ContextHeader.tsx`'s docstring: never
  a POST on selection change), so the run switch is verified as the wizard's stage-7 row
  re-deriving to the newly selected run plus the run's own state badge in the header — a route
  jump would contradict the switcher's stated contract.
* **From-documents refusals and warnings (`TC-UI-10`)** — the browser's preview read now
  carries the formats the upload invites (`authoring_reads._SUPPORTED_SUFFIXES` is
  `{".pdf", ".docx", ".txt"}`; `.docx`/`.txt` route through the library's own intake
  entry, the same normalization the draft job runs — the defect the `TC-E2E-08/09/11`
  journeys found is fixed in this PR, with `TC-UI-10` arm (d) as its regression). Arm
  (b) drops AF-18's legacy `.doc` and asserts the shipped refusal card — now
  FR-AUTHOR-28's own OLE-magic sentence with its next step, the other file unaffected —
  because a `.doc` routes through intake's envelope too and the matrix answers it
  (`TC-AUTHOR-37a`'s sentence, now reachable from the browser). The warnings half of
  arm (a)'s "outline + warnings" is **this suite's now**: the read carries the warning
  stream the PDF path cannot — a `.txt` intake guesses its headings and says so — so
  arm (a)'s upload carries AF-17's `.txt` beside the PDFs and the warning renders in
  the browser.
* **Re-draft carry-over (`TC-UI-11` (c))** — the plan's "confirm copy" is the carry-over
  sentence in the teacher's language; it is asserted where the redesign renders it: the review
  screen's own re-draft section, and — from a from-scratch draft, because a world whose draft
  job already succeeded lands on the authoring screen's report view (the shipped phase rule) —
  the authoring screen's existing-draft copy and the re-draft dispatch's confirmation, which
  carries the same sentence.
* **The per-student log panel (`TC-UI-14` (b))** — SHIPPED DEFECT, flagged on #772 for
  #765's implementation to fix: `StudentDetail` declares `showDetails` but never sets it (the
  `<details>` expander carries no `onToggle`), so the logs read never starts and the panel
  behind Details shows "Reading." permanently. The plan's oracle is the panel's own records;
  until the defect is fixed the case asserts the panel's shipped surface at the same spot
  (heading, grain note, placeholder) and names the gap — never a silent weakening.
* **The immediate op's outcome line (`TC-UI-12`)** — SHIPPED DEFECT, flagged on #772 for
  #764's implementation to fix: `DraftEditor` imports `ActionOutcome`/`useActionState` and
  `applyNow` records every result through `action.finish`, but the screen never renders
  `action.outcome` — a move (or removal) that the console refuses or that errors renders
  nothing at all, and the read is not re-run. Found while diagnosing this suite's own
  reorder wait (a failed save surfaced only as an unanswered HTTP 500). The plan's
  immediate-op oracle is the landed change, which the case asserts through the screen's
  re-read and the draft file itself; the outcome line's absence is the defect's, not the
  case's — named here so the fix lands with a rendering assertion rather than silence.
* **The draft save's rename (`TC-UI-12`)** — SHIPPED DEFECT (Windows-only), flagged on #772:
  `commit_artifacts` (`src/aeh/author/progress.py`) writes `*.part` temporaries and
  `os.replace`s each into place; on Windows that rename fails with a sharing violation
  (WinError 5) whenever any concurrent reader holds the target open, and the console answers
  the action 500 — POSIX replaces over an open file freely, so a Linux run never sees it.
  This suite's own first draft tripped it by polling the draft file while the action ran;
  the wait now rides the screen's own re-read rather than polling the file, and reads the
  file only after the save has landed. A real teacher with two consoles open (or the SPA's
  own reads racing a save) can still hit it — the fix belongs to the action's save path
  (retry the replace, or hold the read open through it).
* **Help context (`TC-UI-18`)** — the ask route is
  `GET /api/v1/help/ask?q=…&context=<JSON>`; the screen id rides *inside* the JSON `context`
  parameter (there is no separate `screen=` query parameter), so the context-carriage oracle
  reads the decoded `context` value. The answer's wording is the recorded double's reply — the
  answer's screen-specific *content* is the server side `TC-HELP-06` already holds; from the
  browser the case proves the carriage and that a grounded answer renders.
* **Unknown job state (`TC-UI-16` (c))** — the value the SPA must not error on is injected
  through the jobs registry itself (`CT-CONSOLE-38`'s SPA half: an unknown value falls through
  to the neutral "needs attention" label).
* **Progress figures (`TC-UI-16` (d))** — the exact numbers are the jobs read's own `done` and
  `total` (the seeded world's known batch counts), asserted as `{done} of {total}` in the row
  and as never a percentage or a per-student ref anywhere on the screen.
* **Grading-panel state (`TC-UI-14`)** — the injected cell state is `ungradeable_by_panel` with
  `routing='provisional'` and `state_reason='even_panel_after_quarantine'`, the legal
  (`state`, `routing`) pair the CHECK constraints admit for a split panel.
* **Screenshots are never oracles** — no case captures or compares an image; the assertions are
  the DOM, the request log, the HTTP reads and the store digests.
"""

from __future__ import annotations

import json
import re
import threading
import time
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import parse_qs, urlsplit

import pytest

from aeh.pkg import PackageCatalog
from aeh.prov import OPENROUTER_API_KEY_ENV
from tests.support import console_redesign_world as crw
from tests.support import help_vocabulary as hv
from tests.support import spa
from tests.support.conf_builders import HOSTED_JUDGE
from tests.support.console_world import STAMP, rows, seed_scored_run
from tests.support.impl import require_path

pytestmark = [pytest.mark.browser, pytest.mark.integration]

#: The console's action surface: a URL carrying this prefix is a mutation request (the
#: `performAction` POSTs). `SpaLog` records URLs without methods, so the no-confirm-free-post
#: oracle reads this prefix — documented in the module docstring, applied everywhere.
ACTION_URL_MARK = "/api/v1/actions/"

#: The wizard's stepper locator — the redesigned home has no level-1 heading; its rows are
#: `ol[aria-label="The nine stages"] > li.stage` (`ui/src/wizard/WizardHome.tsx`).
_STEPS = 'ol[aria-label="The nine stages"] li.stage'

#: The route -> level-1-heading map of the screens the transitions case times (`TC-UI-21`);
#: the titles are the `Screen title=` values in `ui/src/screens/*`.
ROUTE_TITLES: dict[str, str] = {
    "/class": "Set up a class",
    "/papers": "Load papers",
    "/results": "Results",
    "/settings": "Settings",
    "/jobs": "Jobs",
    "/help": "Manuals & help",
}

#: The help-everywhere walk (`TC-UI-18`): each screen and the manual-section keyword the panel
#: must name there (`HelpPanel.tsx`'s `SCREEN_SECTIONS`), against the operating manual's own
#: headings. `/help` is walked separately: it is the manuals page itself and carries no
#: per-screen section.
_HELP_PLAN: tuple[tuple[str, str], ...] = (
    ("/", "the screen map"),
    ("/issues", "when something goes wrong"),
    ("/logs", "when something goes wrong"),
    ("/parked", "parked papers"),
    ("/jobs", "the rest of the sidebar"),
    ("/settings", "the rest of the sidebar"),
)


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


def _no_action_problems(log: spa.SpaLog, where: str) -> list[str]:
    return [f"{where}: a mutation request left the browser without an explicit confirm: {u}"
            for u in _action_urls(log)]


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
    """Fragment navigation to a route. The wizard home has no level-1 heading, so it waits on
    the stepper; every other screen waits on its `main` h1 (the loaded-screen rule). Returns
    the heading text, "" on the wizard home. A query rides the path (`/?class=…&run=…`) and
    does not change which screen the route names."""
    route = path.split("?", 1)[0]
    page.goto(f"{origin}#{path}", wait_until="domcontentloaded")
    if route in ("", "/"):
        page.locator(_STEPS).first.wait_for(state="visible", timeout=spa.STEP_TIMEOUT_MS)
        page.wait_for_load_state("networkidle")
        return ""
    return spa.wait_for_screen(page)


def _stage(page: Any, number: int) -> Any:
    """The wizard's stage row (1-based), as `WizardHome` renders it."""
    return page.locator(_STEPS).nth(number - 1)


def _dialog(page: Any) -> Any:
    return page.get_by_role("dialog").or_(page.get_by_role("alertdialog"))


def _option_values(page: Any, select: str) -> list[str]:
    # The locator chain, not a selector string concat: a `>> nth=0` arm cannot be followed
    # by another selector in a plain string.
    return page.locator(select).locator("option").evaluate_all(
        "els => els.map(e => e.value)")


def _change_select(page: Any, problems: list[str], where: str, select: str) -> None:
    """Change a select to an option different from its current value — the interaction the
    no-confirm-free oracle watches. A select with fewer than two options has nothing to change;
    that is recorded, never skipped silently."""
    options = _option_values(page, select)
    if len(options) < 2:
        problems.append(f"{where}: {select} offers {options!r} — there is no second option to "
                        f"change to")
        return
    current = page.locator(select).input_value()
    target = next((value for value in options if value != current), options[-1])
    page.select_option(select, target)


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
             authoring: bool = False, run_id: str | None = None,
             cfg: dict[str, Any] | None = None, config_path: Path | None = None,
             profile: str | None = None, help_assistant: Any = None,
             build_assistant: Callable[[Any], Any] | None = None) -> Iterator[Served]:
    """A real console on a real loopback port over a real store, the authoring corpus wired in
    when `authoring` is set (HARNESS_PROFILE=dev-ci + the F-AUTHOR recordings + the recorded
    builds), mirroring `tests/support/console_redesign_world.py`'s served fixtures. `seed(store)`
    runs between the open and the serve; whatever it returns names the run in focus unless
    `run_id` says otherwise. `build_assistant(store)` builds the help assistant against the
    opened store when the case needs one. `profile` names the backend profile the environment
    resolves without the authoring corpus (`TC-UI-17`'s settings world)."""
    from aeh.console import serve_console
    from aeh.store import open_store

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    if authoring:
        monkeypatch.setenv("HARNESS_PROFILE", "dev-ci")
        monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(crw.RECORDINGS))
    elif profile is not None:
        monkeypatch.setenv("HARNESS_PROFILE", profile)
    store = open_store(tmp_data_dir)
    focused = run_id
    if seed is not None:
        focused = seed(store)
    assistant = help_assistant
    if build_assistant is not None:
        assistant = build_assistant(store)
    # Browser tests are stood down from the socket guard (`tests/conftest.py`: the E6 oracle is
    # the browser's own request log), so the guard here is None — nothing to uninstall.
    if network_guard is not None:
        network_guard.uninstall()
    try:
        server = serve_console(store=store, run_id=focused, cfg=cfg,
                               config_path=None if config_path is None else str(config_path),
                               help_assistant=assistant)
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
    """The package row a draft-only world lacks: `_package_rows` enumerates the ledgers under
    `packages/`, and a draft job writes only the draft TOML — the context read needs the row
    for the wizard to derive the draft's stage and for an explicit package selection to name
    an entity."""
    handle = store.package(package_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO package (package_id, created_at) VALUES (:p, :t)",
            p=package_id, t=STAMP,
        )


def _park_one_unit(store: Any, world: Any) -> None:
    """A run whose grading points are all `done` but one still `pending`, so the run reads
    `{n-1} of {n} done`: `enumerate_units` leaves the units `pending` (the shipped pipeline
    marks them at execution time, and the seeded world computes the scores directly), so the
    case marks the run's own work `done` and parks exactly one unit — the shape a mid-run
    carries, at the granularity `app.progress` counts (`done` + `pending` + in-flight +
    quarantined)."""
    with store.cohort(world.cohort_id).transaction() as tx:
        tx.execute("UPDATE work_unit SET status = 'done' WHERE run_id = :r", r=world.run_id)
        tx.execute(
            "UPDATE work_unit SET status = 'pending' WHERE work_id = "
            "(SELECT MIN(work_id) FROM work_unit WHERE run_id = :r)",
            r=world.run_id,
        )


def _running_run(store: Any, world: Any) -> None:
    with store.cohort(world.cohort_id).transaction() as tx:
        tx.execute("UPDATE run SET status = 'running' WHERE run_id = :r", r=world.run_id)


def _midrun_world(store: Any, *, submissions: int = 5, cohort_id: str = "c-ts48",
                  run_id: str = "r-ts48", package_id: str = "pkg-ts48") -> Any:
    """A run that is grading: every unit computed but one still pending, the run row running —
    the wizard's stage-7 and the jobs read read 14 of 15 from this."""
    world = seed_scored_run(store, cohort_id=cohort_id, run_id=run_id, package_id=package_id,
                            submissions=submissions, enumerate_units=True)
    _park_one_unit(store, world)
    _running_run(store, world)
    return world


def _finished_published_world(store: Any, *, submissions: int = 3,
                              cohort_id: str = "c-ts50", run_id: str = "r-ts50",
                              package_id: str = "pkg-ts50") -> Any:
    """A graded, finalized, *published* run: the run row complete (the context read derives the
    exporting stage from `complete` + nothing left to finalize) and the version published, so
    the impact read answers and the wizard's NEXT is the export. Its ids default apart from the
    mid-run world's — a test that opens both over one store must not collide on them."""
    world = seed_scored_run(store, cohort_id=cohort_id, run_id=run_id, package_id=package_id,
                            submissions=submissions, finalize=True)
    with store.cohort(world.cohort_id).transaction() as tx:
        tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=world.run_id)
    catalog = PackageCatalog(store.package(world.package_id), package_id=world.package_id)
    catalog.publish(world.package_version_id, approved_by="teacher-1")
    return world


def _two_run_world(store: Any) -> tuple[Any, Any]:
    """One class graded and published, one mid-run: the switchers have two of everything to
    move between (`TC-UI-09`'s re-derivation world)."""
    finished = _finished_published_world(store, submissions=2)
    running = _midrun_world(store, submissions=5, cohort_id="c-ui09-b", run_id="r-ui09-b",
                            package_id="pkg-ui09-b")
    return finished, running


def _quarantine_submission(store: Any, world: Any, submission_id: str, *, status: str,
                           identity: str | None) -> None:
    """One paper parked, with the ingest status the park reads its reason from and either the
    matched student ref or the recorded identity the match note quotes."""
    student_ref = "" if identity is not None else submission_id.replace("sub-", "ref-")
    with store.cohort(world.cohort_id).transaction() as tx:
        tx.execute(
            "UPDATE submission SET quarantined = 1, ingest_status = :st, student_ref = :sr, "
            "v3_identity = :vi WHERE submission_id = :s",
            st=status, sr=student_ref, vi=identity or "", s=submission_id,
        )


def _two_ids(served: Served) -> tuple[str, str, str, str]:
    """The two seeded worlds' class and run ids, read from the console's own context read and
    matched by state — the selection the header's switchers carry, never assumed from order."""
    context = crw._get_json(served.port, "/api/v1/context")
    states = {str(run["run_id"]): str(run["state"]) for run in context["runs"]}
    cohorts = {str(run["run_id"]): str(run.get("cohort_id") or "") for run in context["runs"]}
    finished_run = next((rid for rid, state in states.items() if state == "complete"), "")
    running_run = next((rid for rid, state in states.items() if state == "running"), "")
    assert finished_run and running_run, (
        f"the context read does not name one complete and one running run: {states!r}")
    return cohorts[finished_run], finished_run, cohorts[running_run], running_run


def _run_progress(served: Served, run_id: str) -> tuple[int, int]:
    """The run's own progress figures, from the jobs read that mirrors the run rows — the
    numbers the wizard's stage-7 detail renders, never assumed."""
    jobs = crw._get_json(served.port, "/api/v1/jobs")
    job = next(job for job in jobs["jobs"]
               if job["kind"] == "run" and str(job["job_id"]) == run_id)
    progress = job["progress"]
    assert progress["total"] is not None, f"the jobs read carries no total for {run_id}: {job!r}"
    return int(progress["done"] or 0), int(progress["total"])


def _version_of(served: Served, package_id: str | None = None) -> str:
    """The published version id the context read names — the same value the wizard's impact
    read is fetched with."""
    context = crw._get_json(served.port, "/api/v1/context")
    published = [pkg["published_version"] for pkg in context["packages"]
                 if pkg.get("published_version")
                 and (package_id is None or pkg["package_id"] == package_id)]
    assert published, f"no published version in the context read: {context!r}"
    return str(published[0])


def _settings_config_toml() -> str:
    """The settings world's configuration: a complete `dev-ci` profile section — the shape
    the configuration projection refuses to render without (`HARNESS_COST_CEILING` is
    required for `dev-ci`, which is the refusal a half-formed configuration earns) — written
    as the file the console is started with and served as the same parsed document, so what
    the settings screen shows is what the file holds. The recorded builds keep the profile
    resolvable; the citation question limit is the row the round-trip edits."""
    return f"""\
prompt_template_v = "judge-prompt/3"

[profiles.dev-ci]
HARNESS_COST_CEILING = 5
HARNESS_COST_CURRENCY = "USD"
HARNESS_JEV_MAX_CITATION_QUESTIONS = 3
HARNESS_DECISION_ENGINE = "jev"
HARNESS_DECISION_PROVIDER = "openrouter-jev"
HARNESS_JEV_BUILD = "openrouter/typesafe/jev-1.13@20260917"

[profiles.dev-ci.transcriber]
role = "transcriber"
provider = "openrouter"
build_id = "{crw.RECORDED_TRANSCRIBER}"

[[profiles.dev-ci.panel]]
role = "judge"
provider = "openrouter"
build_id = "{crw.RECORDED_JUDGE}"
"""


# --- TC-UI-08 — the wizard stepper ----------------------------------------------------------------------


def test_tc_ui_08_the_wizard_stepper_names_each_stage_from_the_seeded_facts(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-UI-08` / FR-UI-09 (P0) — the stepper derives every stage's state from the store, not
    from a click sequence: (a) a fresh store reads stage 1 not started and NEXT names creating
    the class; (b) a draft with placeholders reads stage 3 needs-attention naming the count (the
    recorded AF-09 draft's four — the `TC-CONSOLE-64` reconcile); (c) a mid-run reads stage 7
    in progress with the criterion-batch counts; (d) a graded, published run reads stage 8 done,
    stage 9 queued with the export as its action, NEXT the export, and IMPACT the impact read's
    own regrading sentence."""
    _require_bundle()

    # (a) fresh store: nothing exists yet.
    with _console(tmp_data_dir, network_guard, monkeypatch) as served:
        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            _goto(page, served.origin, "/")
            if page.locator(_STEPS).count() != 9:
                problems.append(f"arm (a): the stepper shows "
                                f"{page.locator(_STEPS).count()} stages, not the nine")
            first = _stage(page, 1).locator("a.stage-row")
            name = first.get_attribute("aria-label") or ""
            if name != "Stage 1: Create the class, Not started":
                problems.append(f"arm (a): stage 1 reads {name!r}, not the fresh-store derivation")
            next_line = page.locator("p.wizard-next").inner_text()
            if next_line != "Next: Create the class.":
                problems.append(f"arm (a): NEXT reads {next_line!r}, not 'Next: Create the "
                                f"class.'")
            problems += _health(page, log, "arm (a)")
            problems += _egress_problems(log, "arm (a)")
            _fail_with(problems)

    # (b) a draft with placeholders: stage 3 needs attention, naming the read's own count.
    with _console(tmp_data_dir, network_guard, monkeypatch, authoring=True,
                  cfg=crw.recorded_authoring_config()) as served:
        _answer, record = crw.run_draft_job(served.port, "AF-09")
        assert record["state"] == "succeeded", f"the AF-09 draft job ended {record['state']}"
        document = crw.draft_read(served.port)["draft"]
        package_id = document["package_id"]
        missing = int(document["missing_pieces"])
        assert missing == len(document["placeholders"]) == 4, (
            f"the AF-09 draft carries {missing} missing pieces "
            f"({len(document['placeholders'])} placeholders), not the four it is recorded to")
        _ensure_ledger(served.store, package_id)
        context = crw._get_json(served.port, "/api/v1/context")
        stage3 = next((row for row in next(
            pkg for pkg in context["packages"] if pkg["package_id"] == package_id
        )["wizard"] if row["stage"] == "review draft"), None)
        assert stage3 is not None and stage3["state"] == "needs_attention", (
            f"the context read derives the review-draft stage {stage3!r} for the AF-09 draft")
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, "/")
            row = _stage(page, 3)
            name = row.locator("a.stage-row").get_attribute("aria-label") or ""
            if "Needs attention" not in name:
                problems.append(f"arm (b): stage 3 reads {name!r}, not needs attention")
            detail = row.locator("span.stage-detail").inner_text()
            if detail != f"The draft has {missing} missing pieces.":
                problems.append(f"arm (b): stage 3's detail reads {detail!r}, not the draft "
                                f"read's own count ({missing})")
            problems += _health(page, log, "arm (b)")
            problems += _egress_problems(log, "arm (b)")
            _fail_with(problems)

    # (c) mid-run: stage 7 in progress, with the jobs read's own batch counts. The wizard
    # home's run-derived rows need the run selected: the address's explicit refs win
    # (`CT-UI-07`), so the case navigates with the class and run named.
    def _seed_midrun(store):
        _seed_midrun.world = _midrun_world(store)
        return _seed_midrun.world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed_midrun) as served:
        world = _seed_midrun.world
        done, total = _run_progress(served, world.run_id)
        expected = f"Grading points: {done} of {total} done."
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, f"/?class={world.cohort_id}&run={world.run_id}")
            row = _stage(page, 7)
            name = row.locator("a.stage-row").get_attribute("aria-label") or ""
            if "In progress" not in name:
                problems.append(f"arm (c): stage 7 reads {name!r}, not in progress")
            detail = row.locator("span.stage-detail").inner_text()
            if detail != expected:
                problems.append(f"arm (c): stage 7's detail reads {detail!r}, not the jobs "
                                f"read's own counts ({expected!r})")
            problems += _health(page, log, "arm (c)")
            problems += _egress_problems(log, "arm (c)")
            _fail_with(problems)

    # (d) graded, finalized, published: stages 7/8 done, stage 9 queued with the export action,
    # NEXT the export, IMPACT the impact read's own sentence.
    def _seed_finished(store):
        _seed_finished.world = _finished_published_world(store)
        return _seed_finished.world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed_finished) as served:
        world = _seed_finished.world
        impact = crw._get_json(
            served.port, f"/api/v1/impact?package_version={_version_of(served)}")
        detail = impact["regrading"]["detail"]
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, f"/?class={world.cohort_id}&run={world.run_id}")
            stage7 = _stage(page, 7)
            if stage7.locator("span.badge").inner_text() != "Done":
                problems.append(f"arm (d): stage 7's badge reads "
                                f"{stage7.locator('span.badge').inner_text()!r}, not Done")
            stage8 = _stage(page, 8)
            if stage8.locator("span.badge").inner_text() != "Done":
                problems.append(f"arm (d): stage 8's badge reads "
                                f"{stage8.locator('span.badge').inner_text()!r}, not Done")
            stage9 = _stage(page, 9)
            if stage9.locator("span.badge").inner_text() != "Queued":
                problems.append(f"arm (d): stage 9's badge reads "
                                f"{stage9.locator('span.badge').inner_text()!r}, not Queued")
            action = stage9.locator("span.stage-action").inner_text()
            if action.replace("Next action:", "").strip() != "Export the results":
                problems.append(f"arm (d): stage 9's action reads {action!r}, not the export")
            next_line = page.locator("p.wizard-next").inner_text()
            if next_line != "Next: Export the results.":
                problems.append(f"arm (d): NEXT reads {next_line!r}, not 'Next: Export the "
                                f"results.'")
            impact_line = page.locator("p.wizard-impact").inner_text()
            if impact_line != f"Impact: {detail}":
                problems.append(f"arm (d): IMPACT reads {impact_line!r}, not the impact read's "
                                f"own sentence {detail!r}")
            problems += _health(page, log, "arm (d)")
            problems += _egress_problems(log, "arm (d)")
            _fail_with(problems)


# --- TC-UI-09 — the context header ----------------------------------------------------------------------


def test_tc_ui_09_switching_the_header_rederives_every_wizard_row_without_a_post(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-UI-09` / FR-UI-10 (P0) — the class and run switchers re-derive every wizard row from
    the selection the address carries. The shipped header's own contract: each switcher sets
    only its own key, and an explicit hash ref keeps naming its entity — so the case walks the
    precedence the header ships: start on the finished pair (stage 7 done), switch the run to
    the mid-run one (stage 7 re-derives in progress with the jobs read's own counts), then
    switch the class under that kept run (the run survives the class change — explicit refs
    win) and back; the fragment's query carries the selection, and the whole switching session
    posts nothing (`SpaLog` records URLs, not methods, so the no-POST oracle is the absence of
    `/api/v1/actions/` URLs — the module docstring's rule)."""
    _require_bundle()

    def _seed(store):
        finished, running = _two_run_world(store)
        return running.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed) as served:
        runs = crw._get_json(served.port, "/api/v1/context")["runs"]
        pairs = {str(run["run_id"]): str(run.get("cohort_id") or "")
                 for run in runs if run.get("cohort_id")}
        states = {str(run["run_id"]): str(run["state"]) for run in runs}
        running_run = next((rid for rid, state in states.items() if state == "running"), "")
        finished_run = next((rid for rid, state in states.items() if state == "complete"), "")
        if not running_run or not finished_run:
            _fail_with([f"the context read does not name one running and one complete run: "
                        f"{[(r['run_id'], r['state']) for r in runs]}"])
        finished_class = pairs[finished_run]
        running_class = pairs[running_run]
        done, total = _run_progress(served, running_run)
        midrun_detail = f"Grading points: {done} of {total} done."

        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            _goto(page, served.origin,
                  f"/?class={finished_class}&run={finished_run}")
            if _stage(page, 7).locator("span.badge").inner_text() != "Done":
                problems.append(f"the finished pair's stage 7 reads "
                                f"{_stage(page, 7).locator('span.badge').inner_text()!r}, "
                                f"not Done")

            page.select_option("#switcher-run", running_run)
            _wait_for(problems, "switcher-run -> mid-run", page,
                      lambda: _stage(page, 7).locator("span.stage-detail").inner_text()
                      == midrun_detail,
                      f"stage 7 to re-derive in progress with the mid-run's own counts "
                      f"({midrun_detail!r})")

            page.select_option("#switcher-class", running_class)
            _wait_for(problems, "switcher-class under the kept run", page,
                      lambda: _stage(page, 7).locator("span.stage-detail").inner_text()
                      == midrun_detail,
                      "stage 7 to stay in progress — the run ref survives the class change")
            page.select_option("#switcher-class", finished_class)
            _wait_for(problems, "switcher-class back", page,
                      lambda: _stage(page, 7).locator("span.stage-detail").inner_text()
                      == midrun_detail,
                      "stage 7 to stay in progress under the original class too")

            url = page.url
            if f"run={running_run}" not in url or f"class={finished_class}" not in url:
                problems.append(f"the fragment does not carry the last selections (class "
                                f"{finished_class!r}, run {running_run!r}): {url!r}")
            problems += _health(page, log, "switching")
            problems += _no_action_problems(log, "switching")
            problems += _egress_problems(log, "switching")
            _fail_with(problems)


# --- TC-UI-10 — the authoring screen --------------------------------------------------------------------


def test_tc_ui_10_from_documents_previews_refuses_and_shows_the_drafting_job(
        tmp_data_dir, tmp_path, network_guard, monkeypatch):
    """`TC-UI-10` / FR-UI-11 (P0) — the from-documents entry: (a) a happy upload shows the
    preview's outline (the file, its page count, its first page's blocks) and the read's
    warnings before any commit — no action request and no draft file exists yet; (b) AF-18's
    legacy `.doc` renders its refusal card with the next step and leaves the other file
    unaffected; (c) a drafting job renders its progress (stage, done/total, the tries) with
    the cancel control, and cancelling stops the job at its next step and returns the upload.

    The read carries the formats the upload invites (`.pdf`, `.docx`, `.txt` — the
    three-format read this PR fixes, regression-tested at the unit tier in
    `tests/unit/console/test_tc_ui_10_preview_formats.py`), so arm (a)'s upload carries
    AF-17's `.txt` beside the PDFs and the `.txt`'s intake warning renders; arm (b)'s
    legacy `.doc` is answered by FR-AUTHOR-28's own matrix sentence, which the console
    renders as-is."""
    _require_bundle()

    def _copy_fixture(fixture: str) -> list[Path]:
        paths = []
        for index, source in enumerate(sorted(crw.af(fixture).glob("*.pdf"))):
            target = tmp_path / f"{index:02d}-{source.name}"
            target.write_bytes(source.read_bytes())
            paths.append(target)
        return paths

    with _console(tmp_data_dir, network_guard, monkeypatch, authoring=True,
                  cfg=crw.recorded_authoring_config()) as served:
        # (a) the happy upload's preview, before any commit. The upload carries a `.txt`
        # beside the PDFs — the read takes the formats the input invites — and the `.txt`
        # carries the warnings half: its intake guesses the headings and says so.
        pdfs = _copy_fixture("AF-02")
        txt_source = crw.af("AF-17") / "hist6-great-fire-01-prose-test.txt"
        txt = tmp_path / txt_source.name
        txt.write_bytes(txt_source.read_bytes())
        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            _goto(page, served.origin, "/package/author")
            page.locator('input[aria-label="Choose files to upload"]').set_input_files(
                [*pdfs, txt])
            page.get_by_role("button", name="Show what we understood").click()
            _wait_for(problems, "arm (a)", page,
                      lambda: page.locator("section[aria-label='What we understood'] "
                                           ".preview-file").count() > 0,
                      "the preview's outline to render")
            preview = page.locator("section[aria-label='What we understood']")
            names = preview.locator(".preview-file h3").all_inner_texts()
            if not any(pdfs[0].name in name for name in names):
                problems.append(f"arm (a): the preview names {names!r}, not the uploaded file")
            counts = preview.locator(".preview-counts").all_inner_texts()
            if not any(re.search(r"\d+ page", text) for text in counts):
                problems.append(f"arm (a): the preview carries no page count: {counts!r}")
            pages = preview.locator(".preview-blocks .preview-page").all_inner_texts()
            if not pages or not any(text.strip() == "Page 1" for text in pages):
                problems.append(f"arm (a): the preview's first blocks are not page-marked: "
                                f"{pages[:3]!r}")
            _wait_for(problems, "arm (a)", page,
                      lambda: page.locator("section[aria-label='What we understood'] "
                                           ".preview-warning").count() > 0,
                      "the .txt's intake warning to render")
            if _action_urls(log):
                problems.append(f"arm (a): the preview committed something: {_action_urls(log)!r}")
            if list(Path(served.data_dir, "authoring").glob("*.draft.toml")):
                problems.append("arm (a): a draft file exists before the teacher confirmed "
                                "anything — the preview must not commit")
            problems += _health(page, log, "arm (a)")
            problems += _egress_problems(log, "arm (a)")
            _fail_with(problems)

        # (b) the refused file — AF-18's legacy `.doc`, exactly as the plan's arm names —
        # its own refusal card, the other file unaffected. A `.doc` routes through the
        # library's intake envelope like every other kind, and the matrix answers it
        # (FR-AUTHOR-28's OLE-magic row): the teacher's sentence with its next step,
        # rendered as-is (TC-AUTHOR-37a's oracle, now reachable from the browser).
        legacy_doc = crw.af("AF-18") / "geo6-mapwork-01-legacy.doc"
        legacy = tmp_path / legacy_doc.name
        legacy.write_bytes(legacy_doc.read_bytes())
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, "/package/author")
            page.locator('input[aria-label="Choose files to upload"]').set_input_files(
                [legacy, pdfs[0]])
            # The .doc's refusal is the preview read's answer, not a pick-time rule: the
            # preview button itself is the shipped readiness signal (disabled while any
            # picked file's bytes are still reading), the teacher asks for the preview,
            # and the refusal card and the other file's outline answer together in that
            # one read's response.
            ask_preview = page.get_by_role("button", name="Show what we understood")
            if not _wait_for(problems, "arm (b)", page, ask_preview.is_enabled,
                             "the preview button to enable once the bytes are read",
                             timeout_ms=60_000):
                pass
            ask_preview.click()
            if not _wait_for(problems, "arm (b)", page,
                             lambda: "older Word format" in
                             page.locator("main").inner_text(),
                             "the legacy file's refusal card"):
                pass
            main = page.locator("main").inner_text()
            if "Refused — This file was saved in an older Word format. Open it in Word " \
                    "and save it as .docx, then upload again." not in main:
                problems.append("arm (b): the refusal card does not carry the refusal and its "
                                "next step")
            if "The refused files above are left out; the rest are unaffected." not in main:
                problems.append("arm (b): the refused-files note is missing")
            _wait_for(problems, "arm (b)", page,
                      lambda: page.locator("section[aria-label='What we understood'] "
                                           ".preview-file").count() > 0,
                      "the other file's preview to render")
            names = page.locator("section[aria-label='What we understood'] "
                                 ".preview-file h3").all_inner_texts()
            if not any(pdfs[0].name in name for name in names):
                problems.append(f"arm (b): the other file's preview is missing (names: {names!r})")
            problems += _health(page, log, "arm (b)")
            problems += _egress_problems(log, "arm (b)")
            _fail_with(problems)

        # (c) the drafting job's progress and its cancel control.
        gate, release = threading.Event(), threading.Event()
        from aeh.console import authoring_actions
        real_provider_for = authoring_actions._provider_for

        def paced_provider_for(environ):
            return crw.PacedRecordedProvider(real_provider_for(environ), gate, release)

        monkeypatch.setattr(authoring_actions, "_provider_for", paced_provider_for)
        answer = crw.start_draft(served.port, "AF-02")
        job_id = str(answer["job_id"])
        try:
            assert gate.wait(timeout=60), "the paced draft job never reached its first step"
            with spa.spa_page(served.origin) as (page, log):
                problems = []
                _goto(page, served.origin, "/package/author")
                progress = page.locator("section[aria-label='Drafting progress']")
                if not _wait_for(problems, "arm (c)", page, progress.is_visible,
                                 "the drafting progress to render"):
                    pass
                record = crw._get_json(served.port, f"/api/v1/jobs/{job_id}")
                line = progress.locator(".drafting-line").inner_text()
                stage = record.get("stage")
                if stage and f"{stage[:1].upper()}{stage[1:]} — " not in line:
                    problems.append(f"arm (c): the progress line does not name the job's own "
                                    f"stage {stage!r}: {line!r}")
                attempt, attempts = record.get("attempt"), record.get("attempts")
                if attempt is not None and attempts is not None and \
                        f"attempt {attempt} of {attempts}" not in line:
                    problems.append(f"arm (c): the progress line does not name the job's own "
                                    f"tries ({attempt} of {attempts}): {line!r}")
                done = (record.get("progress") or {}).get("done")
                total = (record.get("progress") or {}).get("total")
                if done is None or total is None:
                    problems.append(f"arm (c): the job record names no done/total "
                                    f"({record.get('progress')!r}) — the TC's done/total "
                                    f"oracle has nothing to assert against")
                elif not _wait_for(problems, "arm (c)", page,
                                   lambda: f"{done} of {total}" in progress.locator(
                                       ".drafting-line").inner_text(),
                                   f"the progress line to name the job's own progress "
                                   f"({done} of {total})"):
                    pass
                if not line.rstrip().endswith("so far."):
                    problems.append(f"arm (c): the progress line carries no elapsed time: "
                                    f"{line!r}")
                if progress.get_by_role("button", name="Stop the draft").count() != 1:
                    problems.append("arm (c): the cancel control is missing from the drafting "
                                    "progress")
                progress.get_by_role("button", name="Stop the draft").click()
                dialog = _dialog(page)
                if not _wait_for(problems, "arm (c)", page, dialog.is_visible,
                                 "the stop confirmation to open"):
                    pass
                dialog.get_by_role("button", name="Stop the draft").click()
                release.set()
                final = crw.wait_for_job(served.port, job_id)
                if final["state"] != "cancelled":
                    problems.append(f"arm (c): the cancelled job ended {final['state']!r}, not "
                                    f"cancelled")
                if not _wait_for(problems, "arm (c)", page,
                                 lambda: page.locator(
                                     'input[aria-label="Choose files to upload"]')
                                 .is_visible(),
                                 "the upload to return after the cancel"):
                    pass
                problems += _health(page, log, "arm (c)")
                problems += _egress_problems(log, "arm (c)")
                _fail_with(problems)
        finally:
            release.set()


# --- TC-UI-11 — the review draft ------------------------------------------------------------------------


def test_tc_ui_11_the_review_walk_answers_survives_and_names_the_carry_over(
        tmp_data_dir, tmp_path, network_guard, monkeypatch):
    """`TC-UI-11` / FR-UI-12 (P0) — the review screen: (a) every placeholder is listed with its
    location and approval is blocked with the count (the recorded AF-09 draft's four, the
    `TC-CONSOLE-64` reconcile); (b) answering one removes it from the list, the answer survives
    a browser reload, and the store's digests do not move (the answer lives in the draft file);
    (c) the re-draft copy names the carry-over in the teacher's language (RS-03)."""
    _require_bundle()

    with _console(tmp_data_dir, network_guard, monkeypatch, authoring=True,
                  cfg=crw.recorded_authoring_config()) as served:
        _answer, record = crw.run_draft_job(served.port, "AF-09")
        assert record["state"] == "succeeded", f"the AF-09 draft job ended {record['state']}"
        document = crw.draft_read(served.port)["draft"]
        package_id = document["package_id"]
        missing = int(document["missing_pieces"])
        _ensure_ledger(served.store, package_id)
        before_digest = spa.store_digest(served.data_dir)
        approved_by_index = next(
            index for index, placeholder in enumerate(document["placeholders"])
            if placeholder["item_id"] == "approved_by")

        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            _goto(page, served.origin, "/package/review")
            main = page.locator("main")
            if f"{missing} missing pieces stand in the draft" not in main.inner_text():
                problems.append(f"arm (a): the blocked-approval copy does not name the draft's "
                                f"own count ({missing})")
            if "cannot be approved yet" not in main.inner_text():
                problems.append("arm (a): approval is not stated as blocked")
            rows = page.locator("ul.placeholder-list li.placeholder-row")
            if rows.count() != missing:
                problems.append(f"arm (a): {rows.count()} placeholder rows render, not the "
                                f"read's {missing}")
            if page.locator("span.placeholder-chip").count() != missing:
                problems.append(f"arm (a): the outline does not highlight every missing piece "
                                f"in place ({page.locator('span.placeholder-chip').count()} "
                                f"marks for {missing})")

            # (b) answer the approved_by item through its own row, then reload.
            rows.nth(approved_by_index).get_by_role("button", name="Answer").click()
            page.locator("#answer-value").fill("Prof. Dana Whitfield")
            page.get_by_role("button", name="Send the answer").click()
            if not any("answer-authoring-review" in url for url in _action_urls(log)):
                problems.append(f"arm (b): the answer did not go through the enumerated review "
                                f"control ({_action_urls(log)!r})")
            _wait_for(problems, "arm (b)", page,
                      lambda: page.locator("ul.placeholder-list li.placeholder-row").count()
                      == missing - 1,
                      "the answered piece to leave the list (the read's next poll)")
            if crw.draft_read(served.port)["draft"]["missing_pieces"] != missing - 1:
                problems.append("arm (b): the draft read still counts the answered piece")
            page.reload(wait_until="networkidle")
            spa.wait_for_screen(page)
            if page.locator("ul.placeholder-list li.placeholder-row").count() != missing - 1:
                problems.append("arm (b): the answer did not survive the browser's reload")
            if f"{missing - 1} missing pieces stand in the draft" not in \
                    page.locator("main").inner_text():
                problems.append("arm (b): the count copy did not survive the reload")
            if spa.store_digest(served.data_dir) != before_digest:
                problems.append("arm (b): the store moved — an answer lives in the draft file, "
                                "never in the ledgers")
            problems += _health(page, log, "arm (b)")
            problems += _egress_problems(log, "arm (b)")
            _fail_with(problems)

        # (c) the carry-over copy, in the teacher's language (RS-03): the review screen's own
        # re-draft section, and the re-draft *confirm* the dispatch opens on the authoring
        # screen — reached from a from-scratch draft, because a world whose draft job already
        # succeeded lands on the authoring screen's report view, not its upload phase (the
        # shipped screen's own phase rule).
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, "/package/review")
            main = page.locator("main")
            if "The answers you already gave are kept where the content still matches" \
                    not in main.inner_text():
                problems.append("arm (c): the re-draft copy does not name the carry-over")
            if "you will be asked to confirm the kept ones" not in main.inner_text():
                problems.append("arm (c): the re-draft copy does not name the kept answers' "
                                "confirmation")
            if main.get_by_role("button", name="Re-draft from my documents").count() != 1:
                problems.append("arm (c): the re-draft action is missing")
            if main.locator("a.stage-action", has_text="Edit the draft instead").count() != 1:
                problems.append("arm (c): the edit-instead path is missing")
            main.get_by_role("button", name="Re-draft from my documents").click()
            spa.wait_for_screen(page)
            if "What we understood" not in page.locator("main").inner_text():
                problems.append("arm (c): the re-draft handover does not land on the authoring "
                                f"screen's report view (at {page.url!r})")
            problems += _health(page, log, "arm (c)")
            problems += _egress_problems(log, "arm (c)")
            _fail_with(problems)

    # (c, continued) the re-draft confirm itself: a from-scratch draft leaves no succeeded
    # authoring job, so the authoring screen keeps its upload phase and offers the re-draft
    # dispatch, whose confirmation carries the carry-over copy. The dispatch arms only once
    # documents are chosen, so the walk chooses the recorded AF-02 papers first.
    pdfs = []
    for index, source in enumerate(sorted(crw.af("AF-02").glob("*.pdf"))):
        target = tmp_path / f"ui11-{index:02d}-{source.name}"
        target.write_bytes(source.read_bytes())
        pdfs.append(target)
    with _console(tmp_data_dir, network_guard, monkeypatch, authoring=True,
                  cfg=crw.recorded_authoring_config()) as served:
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, "/package/author")
            page.locator("#scratch-title").fill("carried-over-ui11")
            page.get_by_role("button", name="Start the empty draft").click()
            dialog = _dialog(page)
            if not _wait_for(problems, "arm (c) scratch", page,
                             lambda: dialog.count() > 0 and dialog.first.is_visible(),
                             "the empty-draft confirmation to open"):
                pass
            else:
                dialog.first.get_by_role("button", name="Start the empty draft").click()
                _wait_for(problems, "arm (c) scratch", page,
                          lambda: "/package/edit" in page.url,
                          "the confirmed start to hand over to the editor")
            _goto(page, served.origin, "/package/author")
            section = page.locator("section[aria-label='An existing draft']")
            if not _wait_for(problems, "arm (c) existing-draft", page, section.is_visible,
                             "the authoring screen's existing-draft section to render"):
                pass
            else:
                text = section.first.inner_text()
                if "the answers you already gave are kept where the content still matches" \
                        not in text:
                    problems.append(f"arm (c): the existing-draft copy reads {text!r}, not the "
                                    f"carry-over in the teacher's language")
                confirm = page.get_by_role("button", name="Make the draft again")
                if not confirm.count():
                    problems.append("arm (c): the re-draft dispatch is missing")
                else:
                    # The dispatch arms only once documents are chosen.
                    page.locator('input[aria-label="Choose files to upload"]')\
                        .set_input_files(pdfs)
                    if not _wait_for(problems, "arm (c) confirm", page, confirm.first.is_enabled,
                                     "the re-draft dispatch to arm once the documents are "
                                     "chosen"):
                        pass
                    else:
                        confirm.first.click()
                    dialog = _dialog(page)
                    if not _wait_for(problems, "arm (c) confirm", page,
                                     lambda: dialog.count() > 0 and dialog.first.is_visible(),
                                     "the re-draft confirmation to open"):
                        pass
                    else:
                        dialog_text = dialog.first.inner_text()
                        if "Make the draft again" not in dialog_text:
                            problems.append(f"arm (c): the confirmation does not name the "
                                            f"re-draft: {dialog_text!r}")
                        if "answers you already gave are kept where the content still " \
                                "matches" not in dialog_text:
                            problems.append(f"arm (c): the confirmation does not carry the "
                                            f"carry-over copy: {dialog_text!r}")
                        if "you will be asked to confirm the kept ones" not in dialog_text:
                            problems.append(f"arm (c): the confirmation does not name the kept "
                                            f"answers' confirmation: {dialog_text!r}")
                        dialog.first.get_by_role("button", name="Cancel").click()
            problems += _health(page, log, "arm (c) confirm")
            problems += _egress_problems(log, "arm (c) confirm")
            _fail_with(problems)


# --- TC-UI-12 — the editor ------------------------------------------------------------------------


def test_tc_ui_12_the_editor_stages_saves_and_warns_before_editing_a_published_package(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-UI-12` / FR-UI-13 (P0) — the editor: (a) add/edit/reorder through the forms, with the
    draft's own validation rendered next to the field it names (the AF-09 draft's issues, in the
    teacher's words); (b) saving shows the staged changes in the teacher's language, confirms,
    and applies them (the draft file changes); (c) editing a published package shows the impact
    banner — the impact read's own run and student counts beside the runs already graded —
    before any edit; (d) the from-scratch entry opens the same editor over an empty draft."""
    _require_bundle()

    def _seed_draft_world(store):
        world = _midrun_world(store, submissions=2)
        return world.run_id

    # (a) + (b): one AF-02 world — stage two changes, reorder through the immediate op, save.
    with _console(tmp_data_dir, network_guard, monkeypatch, authoring=True, seed=_seed_draft_world,
                  cfg=crw.recorded_authoring_config()) as served:
        _answer, record = crw.run_draft_job(served.port, "AF-02")
        assert record["state"] == "succeeded", f"the AF-02 draft job ended {record['state']}"
        package_id = crw.draft_read(served.port)["draft"]["package_id"]
        _ensure_ledger(served.store, package_id)
        draft_file = crw.draft_path_in(served.data_dir, package_id)
        before = draft_file.read_bytes()
        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            _goto(page, served.origin, f"/package/edit?package={package_id}")
            page.locator("#add-q-text").fill("Why does the water cycle slow in winter?")
            page.locator("#add-q-type").select_option("open")
            page.locator("#add-q-points").fill("3")
            page.locator("#add-q-answer").fill("Less energy drives less evaporation.")
            page.get_by_role("button", name="Stage the new question").click()
            _wait_for(problems, "arm (a)", page,
                      lambda: any('Added a question: "Why does the water cycle slow in winter?"'
                                  in text for text in page.locator(
                                      "section[aria-label='Your changes'] ul.change-list li")
                                  .all_inner_texts()),
                      "the staged add to appear in the teacher's own words")
            page.locator("#q-points-0").fill("5")
            page.get_by_role("button", name="Stage the changes to this question").click()
            _wait_for(problems, "arm (a)", page,
                      lambda: any("the points:" in text and "becomes 5" in text for text in
                                  page.locator(
                                      "section[aria-label='Your changes'] ul.change-list li")
                                  .all_inner_texts()),
                      "the staged points edit to appear in the teacher's own words")
            draft_now = crw.draft_read(served.port)["draft"]
            first_before = draft_now["items"][0]["id"]
            second_text = draft_now["items"][1]["text"]
            page.locator(".editor-card").first.get_by_role("button", name="Move down").click()
            # The wait rides the screen, not the draft file: the save writes a `.part` and
            # renames it over the draft, and that rename refuses while any other reader
            # holds the draft open (a Windows sharing violation the console answers 500).
            # The harness's own polling read would be exactly that reader, so the file is
            # left alone until the screen's own re-read has re-rendered the moved order —
            # the cards keep their keys, so the first card's text area then holds the
            # question that moved up.
            _wait_for(problems, "arm (a)", page,
                      lambda: page.locator("#q-text-0").input_value() == second_text,
                      "the moved order to render from the immediate op's re-read")
            saved_items = [item["id"] for item in crw.draft_read(served.port)["draft"]["items"]]
            if saved_items[:2] != [draft_now["items"][1]["id"], first_before]:
                problems.append(
                    "arm (a): the reorder never landed in the draft — the saved order "
                    f"is {saved_items}")
            if not any("edit-draft-package" in url for url in _action_urls(log)):
                problems.append("arm (a): the reorder never reached the enumerated surface")
            problems += _health(page, log, "arm (a)")
            problems += _egress_problems(log, "arm (a)")
            _fail_with(problems)

        # (b) the confirm-then-apply save, in its own session: a reload clears the staged
        # changes (CT-UI-07), so the save carries one change that leaves the draft valid —
        # the added question above would refuse at save time (a question with no rubric line
        # is the draft's own structural rule), which is arm (a)'s validation story, not this
        # arm's.
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, f"/package/edit?package={package_id}")
            before = draft_file.read_bytes()
            page.locator("#q-text-0").fill(
                "Why does the water cycle slow in the winter months?")
            page.get_by_role("button", name="Stage the changes to this question").click()
            staged = page.locator("section[aria-label='Your changes'] ul.change-list li")
            if not _wait_for(problems, "arm (b)", page, lambda: staged.count() == 1,
                             "the staged text edit to appear"):
                pass
            page.get_by_role("button", name=re.compile(r"Review changes \(1\)")).click()
            dialog = _dialog(page)
            _wait_for(problems, "arm (b)", page, dialog.is_visible, "the save confirmation")
            listed = dialog.locator("ul.change-list li").all_inner_texts()
            if len(listed) != 1:
                problems.append(f"arm (b): the confirmation lists {listed!r}, not the one "
                                f"staged change in the teacher's language")
            dialog.get_by_role("button", name="Save the changes").click()
            applied = page.locator(".change-list-applied ul li")
            if not _wait_for(problems, "arm (b)", page,
                             lambda: page.locator(".change-list-applied").count() > 0,
                             "the applied change list to render"):
                pass
            elif applied.count() < 1:
                problems.append(f"arm (b): the applied list carries {applied.count()} entries: "
                                f"{applied.all_inner_texts()!r}")
            elif any("Refused:" in text for text in applied.all_inner_texts()):
                problems.append(f"arm (b): the save was refused: "
                                f"{applied.all_inner_texts()!r}")
            if draft_file.read_bytes() == before:
                problems.append("arm (b): the draft file did not change — the save did not "
                                "apply")
            problems += _health(page, log, "arm (b)")
            problems += _egress_problems(log, "arm (b)")
            _fail_with(problems)

    # (a)'s validation arm: the AF-09 draft's own issues, beside the fields they name.
    with _console(tmp_data_dir, network_guard, monkeypatch, authoring=True,
                  cfg=crw.recorded_authoring_config()) as served:
        _answer, record = crw.run_draft_job(served.port, "AF-09")
        assert record["state"] == "succeeded", f"the AF-09 draft job ended {record['state']}"
        draft_doc = crw.draft_read(served.port)["draft"]
        package_id = draft_doc["package_id"]
        issues = draft_doc["issues"]
        # The shipped editor renders an issue beside the entry its field names (the
        # `question '<id>'` / `criterion '<id>'` prefix match); an issue that names no
        # rendered entry (the grade-boundary placeholder) renders in the editor's
        # "Things to check" outline instead — the oracle stays "every issue renders",
        # with the beside-the-field count the read's own prefix match.
        field_issues = [
            issue for issue in issues
            if any(issue["field"].startswith(f"question '{item['id']}'")
                   for item in draft_doc["items"])
            or any(issue["field"].startswith(f"criterion '{criterion['id']}'")
                   for criterion in draft_doc["criteria"])
        ]
        _ensure_ledger(served.store, package_id)
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, f"/package/edit?package={package_id}")
            errors = page.locator(".field-error")
            if errors.count() != len(field_issues):
                problems.append(f"arm (a): {errors.count()} field errors render, not the "
                                f"{len(field_issues)} of the draft read's {len(issues)} "
                                f"issues that name a rendered entry")
            main = page.locator("main").inner_text()
            for issue in issues:
                if issue["message"] not in main:
                    problems.append(f"arm (a): the draft's issue {issue!r} renders nowhere")
            if any("model_answer" in issue["field"] for issue in issues) and \
                    "the expected answer" not in main:
                problems.append("arm (a): a model_answer issue renders under its internal "
                                "name, not the teacher's words")
            problems += _health(page, log, "arm (a), validation")
            problems += _egress_problems(log, "arm (a), validation")
            _fail_with(problems)

    # (c) the published package's impact banner. The test's consoles share one store (the
    # tmp dir), so this world carries its own ids — arm (a)'s midrun world already holds
    # the seed helper's defaults.
    def _seed_published_with_draft(store):
        world = seed_scored_run(store, submissions=2, finalize=True, cohort_id="c-ui12-a",
                                run_id="r-ui12-a", package_id="pkg-ui12")
        with store.cohort(world.cohort_id).transaction() as tx:
            tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=world.run_id)
        PackageCatalog(store.package(world.package_id),
                       package_id=world.package_id).publish(
            world.package_version_id, approved_by="teacher-1")
        seed_scored_run(store, cohort_id="c-ui12-b", run_id="r-ui12-b", package_id="pkg-ui12",
                        submissions=4, reuse_version=world.package_version_id)
        return world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, authoring=True,
                  seed=_seed_published_with_draft,
                  cfg=crw.recorded_authoring_config()) as served:
        # Arm (a)'s AF-02 draft still stands in the shared authoring dir, so this re-draft
        # confirms the overwrite — the same recorded corpus, replace confirmed.
        _answer, record = crw.run_draft_job(served.port, "AF-02", replace=True)
        assert record["state"] == "succeeded", f"the AF-02 draft job ended {record['state']}"
        draft_pid = crw.draft_read(served.port)["draft"]["package_id"]
        draft_file = crw.draft_path_in(served.data_dir, draft_pid)
        Path(served.data_dir, "authoring", "pkg-ui12.package.draft.toml").write_bytes(
            draft_file.read_bytes())
        version = _version_of(served, "pkg-ui12")
        impact = crw._get_json(served.port, f"/api/v1/impact?package_version={version}")
        runs_expected = impact["runs"]
        students_expected = impact["students"]
        assert runs_expected >= 2 and students_expected >= 6, (
            f"the published world's impact read names {runs_expected} run(s) and "
            f"{students_expected} student(s), not the two seeded runs' own figures")
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, "/package/edit?package=pkg-ui12")
            banner = page.locator("div.impact-banner")
            if not _wait_for(problems, "arm (c)", page, banner.is_visible,
                             "the impact banner to render"):
                pass
            text = banner.inner_text() if banner.count() else ""
            for expected in (f"{runs_expected} grading run(s)", f"{students_expected} students",
                             "This package version is published:", impact["regrading"]["detail"]):
                if expected not in text:
                    problems.append(f"arm (c): the impact banner does not name {expected!r}")
            listed = banner.locator("ul.change-list li").all_inner_texts()
            for run_id in ("r-ui12-a", "r-ui12-b"):
                if not any(run_id in entry for entry in listed):
                    problems.append(f"arm (c): the banner's run list does not name {run_id}")
            problems += _health(page, log, "arm (c)")
            problems += _egress_problems(log, "arm (c)")
            _fail_with(problems)

    # (d) the from-scratch entry opens the same editor over an empty draft.
    with _console(tmp_data_dir, network_guard, monkeypatch, authoring=True,
                  cfg=crw.recorded_authoring_config()) as served:
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, "/package/author")
            page.locator("#scratch-title").fill("Water cycle check")
            page.get_by_role("button", name="Start the empty draft").click()
            dialog = _dialog(page)
            _wait_for(problems, "arm (d)", page, dialog.is_visible, "the empty-draft confirm")
            dialog.get_by_role("button", name="Start the empty draft").click()
            if not _wait_for(problems, "arm (d)", page,
                              lambda: page.locator("main h1").inner_text() == "Edit the package",
                              "the editor to open over the empty draft"):
                pass
            if "Nothing changed yet." not in page.locator("main").inner_text():
                problems.append("arm (d): the editor does not open over an empty draft")
            problems += _health(page, log, "arm (d)")
            problems += _egress_problems(log, "arm (d)")
            _fail_with(problems)


# --- TC-UI-13 — the state model ------------------------------------------------------------------------


def test_tc_ui_13_every_failure_renders_its_template_and_every_success_a_toast(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-UI-13` / FR-UI-14 (P0) — the failure template, asserted on each injected failure's
    own surface: (i) a failed grading run renders stage 7 failed with the stripped reason and
    the jobs page's own what-went-wrong line; (ii) the upload refusal renders inline with its
    next step; (iii) a field error renders inline beside the field; (iv) a read that can no
    longer be satisfied (the console gone — the plan's stale-read arm) renders the banner with
    what, why and the one-click retry, and the retry re-renders it while the console is still
    gone; (v) a successful override raises the success toast."""
    _require_bundle()

    # (i) the failed run.
    def _seed_failed(store):
        _seed_failed.world = _midrun_world(store, submissions=2)
        world = _seed_failed.world
        with store.cohort(world.cohort_id).transaction() as tx:
            tx.execute(
                "UPDATE run SET status = 'failed', pause_reason = "
                "'composition fault: RuntimeError: the judge gave up' WHERE run_id = :r",
                r=world.run_id,
            )
        return world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed_failed) as served:
        world = _seed_failed.world
        jobs = crw._get_json(served.port, "/api/v1/jobs")
        run_job = next(job for job in jobs["jobs"] if job["kind"] == "run")
        assert run_job["error"]["detail"] == "the judge gave up", (
            f"the jobs read strips to {run_job['error']['detail']!r}")
        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            # Stage 7 reads the run the address names — an explicit ref wins, so name it.
            _goto(page, served.origin, f"/?class={world.cohort_id}&run={world.run_id}")
            row = _stage(page, 7)
            if row.locator("span.badge").inner_text() != "Failed":
                problems.append(f"arm (i): stage 7's badge reads "
                                f"{row.locator('span.badge').inner_text()!r}, not Failed")
            detail = row.locator("span.stage-detail").inner_text()
            if detail != "the judge gave up":
                problems.append(f"arm (i): stage 7's detail reads {detail!r}, not the jobs "
                                f"read's own stripped reason")
            _goto(page, served.origin, "/jobs")
            failed_row = page.locator("tr.job-row", has_text="Failed").first
            failed_row.get_by_role("button", name="What went wrong").click()
            detail_row = page.locator("tr.job-detail-row")
            # The detail row opens at once but reads its own job read async ("Reading."
            # first) — wait for the line, not the row.
            if not _wait_for(problems, "arm (i)", page,
                             lambda: "the judge gave up" in detail_row.inner_text(),
                             "the job's what-went-wrong line to name the stripped reason"):
                problems.append(f"arm (i): the detail row reads {detail_row.inner_text()!r}")
            problems += _health(page, log, "arm (i)")
            problems += _egress_problems(log, "arm (i)")
            _fail_with(problems)

    # (ii) the upload refusal's inline card.
    with _console(tmp_data_dir, network_guard, monkeypatch, authoring=True,
                  cfg=crw.recorded_authoring_config()) as served:
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            empty = tmp_data_dir / "empty-sheet.txt"
            empty.write_bytes(b"")
            _goto(page, served.origin, "/package/author")
            page.locator('input[aria-label="Choose files to upload"]').set_input_files([empty])
            refused = page.locator(".upload-state-refused")
            if not _wait_for(problems, "arm (ii)", page, refused.is_visible,
                             "the refusal card to render"):
                pass
            text = refused.inner_text() if refused.count() else ""
            if "Refused — That file is empty." not in text or "Upload the file again." not in text:
                problems.append(f"arm (ii): the refusal card reads {text!r}, not the refusal "
                                f"with its next step")
            problems += _health(page, log, "arm (ii)")
            problems += _egress_problems(log, "arm (ii)")
            _fail_with(problems)

    # (iii) the settings field error, inline beside the field. The row the case edits is a
    # dev-ci-projected setting, so the console is served with the projecting configuration
    # (`_settings_config_toml`'s complete profile — the shape the projection refuses to
    # render without).
    settings_config = tmp_data_dir / "field-error-settings.toml"
    settings_config.write_text(_settings_config_toml(), encoding="utf-8")
    monkeypatch.setenv(OPENROUTER_API_KEY_ENV, "sk-test-ui13")
    with _console(tmp_data_dir, network_guard, monkeypatch,
                  cfg=tomllib.loads(settings_config.read_text(encoding="utf-8")),
                  config_path=settings_config, profile="dev-ci") as served:
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, "/settings")
            field = "decision_citation_question_limit"
            page.locator(f"#setting-{field}").fill("abc")
            error = page.locator("div.settings-row", has=page.locator(f"#setting-{field}")) \
                .locator("p.settings-error")
            if not _wait_for(problems, "arm (iii)", page, error.is_visible,
                             "the inline field error to render"):
                pass
            if error.inner_text() != "Enter a number.":
                problems.append(f"arm (iii): the field error reads {error.inner_text()!r}")
            if page.get_by_role("button", name="Save the changes").is_enabled():
                problems.append("arm (iii): the save stays enabled with an invalid value")
            problems += _health(page, log, "arm (iii)")
            problems += _egress_problems(log, "arm (iii)")
            _fail_with(problems)

    # (iv) a read that can no longer be satisfied: the banner, and the retry re-rendering it.
    # The test's consoles share one store (the tmp dir), so the later worlds seed their own
    # ids — the seed helper's defaults would collide with arm (i)'s midrun world.
    def _seed_one(store):
        world = seed_scored_run(store, submissions=1, cohort_id="c-ui13b",
                                run_id="r-ui13b", package_id="pkg-ui13b")
        return world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed_one) as served:
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, "/results")
            served.server.terminate()
            _goto(page, served.origin, "/settings")
            banner = page.locator("div.banner-danger")
            if not _wait_for(problems, "arm (iv)", page,
                             lambda: banner.count() > 0 and banner.first.is_visible(),
                             "the failure banner to render"):
                pass
            else:
                text = banner.first.inner_text()
                if "The console could not read this screen" not in text:
                    problems.append(f"arm (iv): the banner does not say what failed: {text!r}")
                if spa.RECOVERY_TEXT not in text:
                    problems.append(f"arm (iv): the banner does not say why: {text!r}")
                if banner.first.get_by_role("button", name="Retry").count() != 1:
                    problems.append("arm (iv): the banner carries no one-click retry")
                banner.first.get_by_role("button", name="Retry").click()
                page.wait_for_timeout(1500)
                if not (banner.count() > 0 and banner.first.is_visible()):
                    problems.append("arm (iv): the retried read left no banner while the "
                                    "console is gone")
            problems += _health(page, log, "arm (iv)")
            problems += _egress_problems(log, "arm (iv)")
            _fail_with(problems)

    # (v) the success toast.
    def _seed_final(store):
        world = seed_scored_run(store, submissions=1, finalize=True, cohort_id="c-ui13c",
                                run_id="r-ui13c", package_id="pkg-ui13c")
        with store.cohort(world.cohort_id).transaction() as tx:
            tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=world.run_id)
        return world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed_final) as served:
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            submission = crw._get_json(served.port, "/api/v1/results/screen")["students"][0][
                "submission_id"]
            _goto(page, served.origin, f"/results/students/{submission}")
            # The override opens from its own disclosure — a <summary> carries no button
            # role in the accessibility tree, so the walk locates the summary itself.
            override = page.locator("details.override").first
            override.locator("summary").click()
            override.locator("select[name^='criterion-band-']").first.select_option(
                "incorrect")
            override.locator("textarea[name='override-reason']").fill(
                "Re-read the paper; the mark missed the second justification.")
            page.get_by_role("button", name="Save", exact=True).first.click()
            toast = page.locator("div.toast-success")
            if not _wait_for(problems, "arm (v)", page,
                             lambda: toast.count() > 0 and toast.first.is_visible(),
                             "the success toast to render"):
                pass
            elif toast.first.inner_text() != \
                    "Final grade changed — the history keeps the original.":
                problems.append(f"arm (v): the toast reads {toast.first.inner_text()!r}")
            problems += _health(page, log, "arm (v)")
            problems += _egress_problems(log, "arm (v)")
            _fail_with(problems)


# --- TC-UI-14 — results and override ------------------------------------------------------------------------


def test_tc_ui_14_results_render_the_distribution_drilldown_and_the_amendment(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-UI-14` / FR-UI-15/16/17, RS-09 (P0) — the results: (a) the overview's distribution is
    the read's own counts as labelled SVG bars, and every flagged grading point links through to
    its student; (b) the drill-down's justification is the score reason plus the graders' cited
    evidence, with the graders' trail and the run's log behind the Details expander; (c) the
    override demands a reason, refuses without one (nothing posted), and a confirmed change
    lands an appended amendment row in the store while the original grade stays."""
    _require_bundle()

    def _seed(store):
        world = seed_scored_run(store, submissions=2, finalize=True, enumerate_units=True)
        with store.cohort(world.cohort_id).transaction() as tx:
            # A split panel on sub-01/C-01: an escalated work unit, two grader verdicts on
            # opposite sides, the cell held for the teacher's review.
            tx.execute(
                "INSERT INTO work_unit (work_id, submission_id, stage, status, run_id, "
                "criterion_id, judge_id, origin, attempts) VALUES ('wu-ui14-a', :s, 'score', "
                "'done', :r, 'C-01', 'judge-a', 'escalation', 1)",
                s=world.submissions[0], r=world.run_id,
            )
            tx.execute(
                "INSERT INTO verdict (verdict_id, work_id, judge_id, band, cited_spans) VALUES "
                "('v-ui14-a', 'wu-ui14-a', 'judge-a', 'correct', :q)",
                q='[{"text": "the answer marks option A against the stored key"}]',
            )
            tx.execute(
                "INSERT INTO verdict (verdict_id, work_id, judge_id, band, cited_spans) VALUES "
                "('v-ui14-b', 'wu-ui14-a', 'judge-b', 'incorrect', :q)",
                q='[{"text": "the paper\'s second mark contradicts the first"}]',
            )
            tx.execute(
                "UPDATE criterion_score SET state = 'ungradeable_by_panel', "
                "routing = 'provisional', state_reason = 'even_panel_after_quarantine' "
                "WHERE submission_id = :s AND criterion_id = 'C-01'",
                s=world.submissions[0],
            )
            # A queued cell on sub-02/C-02: the low-confidence flag with a final band.
            tx.execute(
                "UPDATE criterion_score SET routing = 'queued' "
                "WHERE submission_id = :s AND criterion_id = 'C-02'",
                s=world.submissions[1],
            )
        return world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed) as served:
        doc = crw._get_json(served.port, "/api/v1/results/screen")
        levels = doc["score_levels"]
        bands = [criterion["criterion_band"] for student in doc["students"]
                 for criterion in student["criteria"]]
        counts = [sum(1 for band in bands if band == level) for level in levels]
        flagged = [(student["submission_id"], student["student_ref"], criterion)
                   for student in doc["students"] for criterion in student["criteria"]
                   if criterion["flag"] is not None]
        assert flagged, f"the injected world flags nothing: {doc['students']!r}"

        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            # (a) the overview.
            _goto(page, served.origin, "/results")
            figure = page.locator("figure.distribution")
            svg = figure.locator("svg[role='img']")
            expected = "Papers per score level. " + ", ".join(
                f"{level}: {count}" for level, count in zip(levels, counts, strict=True))
            name = svg.get_attribute("aria-label") or ""
            if name != expected:
                problems.append(f"arm (a): the distribution reads {name!r}, not the read's own "
                                f"counts ({expected!r})")
            # SVG elements have no `innerText` (Playwright answers None for them) — read
            # the bars' text content.
            bar_counts = svg.locator("text.bar-count").all_text_contents()
            bar_labels = svg.locator("text.bar-label").all_text_contents()
            if bar_counts != [str(count) for count in counts] or \
                    bar_labels != list(levels):
                problems.append(f"arm (a): the bars read {list(zip(bar_labels, bar_counts))!r}, "
                                f"not the read's own {list(zip(levels, counts))!r}")
            caption = [text.strip() for text in
                       figure.locator("figcaption span").all_inner_texts()]
            if caption != [f"{level}: {count}" for level, count in
                           zip(levels, counts, strict=True)]:
                problems.append(f"arm (a): the caption reads {caption!r}, not the counts")
            links = page.locator("ul.flagged-list a").all_inner_texts() if \
                page.locator("ul.flagged-list").count() else []
            hrefs = [link.get_attribute("href") or ""
                     for link in page.locator("ul.flagged-list a").all()]
            if len(hrefs) != len(flagged):
                problems.append(f"arm (a): {len(hrefs)} flagged links render, not the read's "
                                f"{len(flagged)}")
            for submission_id, student_ref, criterion in flagged:
                if f"#/results/students/{submission_id}" not in hrefs:
                    problems.append(f"arm (a): the flagged cell {submission_id}/"
                                    f"{criterion['criterion_id']} links nowhere")
                label = next((text for text in links if student_ref and student_ref in text), None)
                if label is None and student_ref:
                    problems.append(f"arm (a): the flagged link does not name {student_ref!r}")

            # (b) the drill-down: reason + cited evidence + the trail behind Details.
            escalated = doc["students"][0]["submission_id"]
            detail_doc = crw._get_json(
                served.port, f"/api/v1/results/student-detail?submission_id={escalated}")
            cell = next(criterion for criterion in detail_doc["criteria"]
                        if criterion["criterion_id"] == "C-01")
            _goto(page, served.origin, f"/results/students/{escalated}")
            card = page.locator("li.criterion-card",
                                has_text=cell["label"] or cell["criterion_id"])
            why = card.locator("p.criterion-why").inner_text()
            if why != cell["state_reason"]:
                problems.append(f"arm (b): the justification reads {why!r}, not the read's own "
                                f"reason {cell['state_reason']!r}")
            state_text = card.locator("p.criterion-state").inner_text()
            if state_text != ("The graders refused to grade this criterion — it is recorded as "
                              "ungradeable, not as awaiting review"):
                problems.append(f"arm (b): the cell's state reads {state_text!r}")
            evidence = card.locator(".evidence blockquote").all_inner_texts()
            flat_quotes = [quote for grader in cell["graders"] for quote in grader["cited"]]
            for quote in flat_quotes:
                if not any(quote in text for text in evidence):
                    problems.append(f"arm (b): the cited evidence {quote!r} renders nowhere")
            card.locator("details.detail-expander summary", has_text="Details").click()
            trail = card.locator(".grader-list")
            if not _wait_for(problems, "arm (b)", page, trail.is_visible,
                             "the graders' trail to open"):
                pass
            detail_body = card.locator(".detail-body")
            for grader in cell["graders"]:
                expected_line = f"{grader['grader']} chose {grader['score_level']}."
                if expected_line not in detail_body.inner_text():
                    problems.append(f"arm (b): the trail does not name {expected_line!r} "
                                    f"({cell['graders']!r})")
            # SHIPPED DEFECT (flagged on #772, fix belongs to #765's implementation): the
            # per-student log panel behind the Details expander never loads — StudentDetail
            # declares `showDetails` but never sets it (no `onToggle` on the expander), so
            # the logs read never starts and the panel shows "Reading." permanently. The
            # plan's TC-UI-14(b) oracle is the panel's own records; until the defect is
            # fixed this case asserts the shipped state at the same spot and names the gap
            # — never a silent weakening.
            if card.locator(".detail-body h3", has_text="The run's log").count() != 1:
                problems.append("arm (b): the log panel's heading is missing behind Details")
            elif card.locator(".detail-body p.log-note").count() != 1:
                problems.append("arm (b): the log panel's grain note is missing behind "
                                "Details")
            elif card.locator(".log-list li").count() == 0 and \
                    "Reading." not in detail_body.inner_text():
                problems.append(f"arm (b): the log panel renders neither its records nor the "
                                f"shipped placeholder: {detail_body.inner_text()!r}")
            problems += _health(page, log, "arms (a)+(b)")
            problems += _egress_problems(log, "arms (a)+(b)")
            _fail_with(problems)

        # (c) the override: the required reason, the refusal, the amendment.
        queued_student = doc["students"][1]["submission_id"]
        before_digest = spa.store_digest(served.data_dir)
        grade_rows_before = rows(
            served.store.cohort("c-ts48"),
            "SELECT revision FROM submission_grade WHERE submission_id = :s "
            "ORDER BY revision", s=queued_student)
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, f"/results/students/{queued_student}")
            override = page.locator("details.override").first
            override.locator("summary").click()
            # Every cell on this finished page grades `correct`, so the change must go to a
            # band the select does not already hold — a fixed index can re-select the
            # current band, and a no-change save is refused as nothing to save.
            band = override.locator("select[name^='criterion-band-']").first
            values = band.evaluate("el => Array.from(el.options).map(o => o.value)")
            target = next(value for value in values if value != band.input_value())
            band.select_option(target)
            if _action_urls(log):
                problems.append(f"arm (c): changing the band posted without the confirm: "
                                f"{_action_urls(log)!r}")
            override.get_by_role("button", name="Save", exact=True).click()
            note = override.locator("p.inline-note")
            if not _wait_for(problems, "arm (c)", page, note.is_visible,
                             "the required-reason refusal to render"):
                pass
            elif "A reason is required to change a final grade" not in note.inner_text():
                problems.append(f"arm (c): the refusal reads {note.inner_text()!r}")
            if _action_urls(log):
                problems.append(f"arm (c): the reasonless save posted: {_action_urls(log)!r}")
            override.locator("textarea[name='override-reason']").fill(
                "The second mark contradicts the key; re-checked against the paper.")
            override.get_by_role("button", name="Save", exact=True).click()
            if not _wait_for(problems, "arm (c)", page,
                             lambda: any("amend-a-finalized-grade" in url
                                         for url in _action_urls(log)),
                             "the amendment to post through the console's own action"):
                pass
            # The action's response can return before its write lands — wait for the
            # revision itself, then take the digest, or the diff races the write.
            if not _wait_for(problems, "arm (c)", page,
                             lambda: len(rows(
                                 served.store.cohort("c-ts48"),
                                 "SELECT revision FROM submission_grade "
                                 "WHERE submission_id = :s ORDER BY revision",
                                 s=queued_student)) == len(grade_rows_before) + 1,
                             "the amendment's revision to land in the store"):
                pass
            after_digest = spa.store_digest(served.data_dir)
            changed = spa.changed_tables(before_digest, after_digest)
            if not any(key.endswith(":submission_grade") for key in changed) or \
                    not any(key.endswith(":audit_record") for key in changed):
                problems.append(f"arm (c): the amendment landed {sorted(changed)!r}, not the "
                                f"grade revision plus its audit record")
            grade_rows_after = rows(
                served.store.cohort("c-ts48"),
                "SELECT revision FROM submission_grade WHERE submission_id = :s "
                "ORDER BY revision", s=queued_student)
            revisions_before = [int(entry["revision"]) for entry in grade_rows_before]
            revisions_after = [int(entry["revision"]) for entry in grade_rows_after]
            if revisions_after[:len(revisions_before)] != revisions_before or \
                    len(revisions_after) != len(revisions_before) + 1:
                problems.append(f"arm (c): the grade revisions went {revisions_before!r} -> "
                                f"{revisions_after!r} — the amendment must append one revision, "
                                f"the original intact")
            original = rows(served.store.cohort("c-ts48"),
                            "SELECT band FROM criterion_score WHERE submission_id = :s "
                            "AND criterion_id = 'C-02'", s=queued_student)
            if not original or str(original[0]["band"]) != "correct":
                problems.append(f"arm (c): the stored cell moved: {original!r} — the original "
                                f"band must stay")
            history = page.locator("section.amendment-history li")
            if not _wait_for(problems, "arm (c)", page,
                             lambda: history.count() > 0 and "Final grade changed from" in
                             history.first.inner_text(),
                             "the amendment's render-back to appear"):
                pass
            elif "the original grade is kept in the history" not in history.first.inner_text():
                problems.append(f"arm (c): the render-back reads "
                                f"{history.first.inner_text()!r}")
            problems += _health(page, log, "arm (c)")
            problems += _egress_problems(log, "arm (c)")
            _fail_with(problems)


# --- TC-UI-15 — the issues and logs pages -----------------------------------------------------------------


def test_tc_ui_15_the_issues_render_as_cards_with_working_steps_and_the_logs_list_the_run(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-UI-15` / FR-UI-18 (P1) — a seeded run's problems render as issue cards whose three
    sentences are the server read's own words, whose severity is the source-derived badge, and
    whose next-step buttons do what they say (the recover dialog opens and can be cancelled;
    the parked and results buttons navigate); the logs timeline lists exactly the read's own
    records — the seeded stages, never an invented line — with the grouped problem's detail
    behind its Details expander."""
    _require_bundle()

    def _seed(store):
        world = seed_scored_run(store, submissions=3, enumerate_units=True)
        with store.cohort(world.cohort_id).transaction() as tx:
            # No stage filter: an MCQ-only package enumerates no 'score'-stage units (its
            # grading work is 'deterministic'), and the issues read selects failed units
            # without one.
            tx.execute(
                "UPDATE work_unit SET status = 'failed', attempts = 2, "
                "last_error = 'composition fault: RuntimeError: the judge gave up' "
                "WHERE work_id = (SELECT MIN(work_id) FROM work_unit WHERE run_id = :r)",
                r=world.run_id,
            )
            tx.execute(
                "UPDATE submission SET quarantined = 1, ingest_status = 'unmatched_assessment', "
                "student_ref = '', v3_identity = 'scan-009' WHERE submission_id = :s",
                s=world.submissions[2],
            )
            tx.execute(
                "INSERT INTO escalation_request (request_id, run_id, submission_id, "
                "criterion_id, expected_value, admitted, requested_at, detail) VALUES "
                "('er-ui15', :r, :s, 'C-01', NULL, 1, :t, 'the panel was split')",
                r=world.run_id, s=world.submissions[0], t=STAMP,
            )
            tx.execute(
                "INSERT INTO circuit_breaker (breaker_id, run_id, criterion_id, kind, "
                "tripped_at, detail) VALUES ('cb-ui15', :r, 'C-02', 'criterion_escalation', "
                ":t, 'too many second opinions on one grading point')",
                r=world.run_id, t=STAMP,
            )
        return world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed) as served:
        run_id = served.server.run_id if hasattr(served.server, "run_id") else None
        assert run_id, "the served console carries no run in focus"
        issues = crw._get_json(served.port, f"/api/v1/issues?run_id={run_id}")["issues"]
        sources = {str(issue["source"]) for issue in issues}
        assert {"grading step", "parked paper", "second opinion", "grading point"} \
            .issubset(sources), f"the seeded world raises only {sorted(sources)!r}"
        logs = crw._get_json(served.port, f"/api/v1/logs?run_id={run_id}")
        records = logs["records"]
        assert records, "the seeded run's logs read holds no records"

        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            _goto(page, served.origin, f"/issues?run={run_id}")
            cards = page.locator("ul.issues-list li.issue-card")
            if not _wait_for(problems, "issues", page,
                             lambda: cards.count() == len(issues),
                             f"{len(issues)} issue cards to render"):
                pass
            for index, issue in enumerate(issues):
                card = cards.nth(index)
                source = card.locator("span.issue-source").inner_text()
                if source != issue["source"]:
                    problems.append(f"issues: card {index} reads source {source!r}, not "
                                    f"{issue['source']!r}")
                for part, selector in (("what", "p.issue-what"),
                                       ("affects", "p.issue-affects")):
                    if card.locator(selector).inner_text() != issue[part]:
                        problems.append(f"issues: card {index}'s {part} reads "
                                        f"{card.locator(selector).inner_text()!r}, not the "
                                        f"read's own {issue[part]!r}")
                next_line = card.locator("p.issue-next").inner_text()
                if "Next step:" not in next_line or issue["next_step"] not in next_line:
                    problems.append(f"issues: card {index}'s next step reads {next_line!r}, "
                                    f"not the read's own {issue['next_step']!r}")
                badge = card.locator("span.badge").inner_text()
                expected_badge = "Information" if issue["source"] == "second opinion" \
                    else "Needs attention"
                if badge != expected_badge:
                    problems.append(f"issues: card {index}'s severity badge reads {badge!r}, "
                                    f"not {expected_badge!r} for {issue['source']!r}")
                if issue["source"] == "second opinion" and \
                        card.get_by_role("button").count() != 0:
                    problems.append("issues: the second-opinion card carries a button, but a "
                                    "second opinion's next step names no console action")

            grading_card = page.locator("li.issue-card",
                                        has=page.locator("span.issue-source",
                                                         has_text="grading step")).first
            grading_card.get_by_role("button", name="Pick the given-up work back up").click()
            dialog = _dialog(page)
            if not _wait_for(problems, "issues", page,
                             lambda: dialog.count() > 0 and dialog.first.is_visible(),
                             "the recover dialog to open"):
                pass
            else:
                dialog.first.get_by_role("button", name="Cancel").click()
                if not _wait_for(problems, "issues", page,
                                 lambda: dialog.count() == 0 or not dialog.first.is_visible(),
                                 "the recover dialog to close on cancel"):
                    problems.append("issues: the recover dialog did not close on cancel")

            parked_card = page.locator("li.issue-card",
                                       has=page.locator("span.issue-source",
                                                        has_text="parked paper")).first
            parked_card.get_by_role("button", name="Open the parked page").click()
            if not _wait_for(problems, "issues", page,
                             lambda: page.locator("main h1").inner_text() == "Parked",
                             "the parked-page button to navigate"):
                pass

            _goto(page, served.origin, f"/issues?run={run_id}")
            point_card = page.locator("li.issue-card",
                                      has=page.locator("span.issue-source",
                                                       has_text="grading point")).first
            point_card.get_by_role("button", name="Review the results").click()
            if not _wait_for(problems, "issues", page,
                             lambda: page.locator("main h1").inner_text() == "Results",
                             "the review-the-results button to navigate"):
                pass

            _goto(page, served.origin, f"/logs?run={run_id}")
            rows_ = page.locator("ol.logs-list li.log-row")
            if not _wait_for(problems, "logs", page,
                             lambda: rows_.count() == len(records),
                             f"{len(records)} log records to render"):
                pass
            for index, record in enumerate(records):
                row = rows_.nth(index)
                text = row.locator("p.log-text").inner_text()
                if text != record["text"]:
                    problems.append(f"logs: record {index} reads {text!r}, not the read's own "
                                    f"{record['text']!r}")
                stage = row.locator("span.log-stage")
                if record["stage"] is not None:
                    if stage.count() != 1 or stage.inner_text() != record["stage"]:
                        problems.append(f"logs: record {index} renders stage "
                                        f"{stage.inner_text() if stage.count() else None!r}, "
                                        f"not {record['stage']!r}")
                elif stage.count() != 0:
                    problems.append(f"logs: record {index} renders a stage the read does not "
                                    f"carry")
                if record["kind"] == "problem":
                    if not _wait_for(problems, "logs", page,
                                     lambda record=record: record["detail"] is None or
                                     row.locator("details.log-detail p").text_content()
                                     == record["detail"],
                                     "the problem record's detail behind its expander"):
                        pass
            if not any("gave up" in str(record["text"]) for record in records):
                problems.append("logs: the seeded gave-up grading step raised no problem record")
            problems += _health(page, log, "issues and logs")
            problems += _egress_problems(log, "issues and logs")
            _fail_with(problems)


# --- TC-UI-16 — the parked and jobs pages -----------------------------------------------------------------


def test_tc_ui_16_the_parked_cards_and_the_jobs_table_render_the_reads_own_figures(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-UI-16` / FR-UI-19, RS-05 (P1) — (a) the parked page renders each parked paper with
    the read's own reason, match note and resolutions, and the resolve controls behind their
    confirmations; (b) the jobs table renders a live authoring job's own fields — its state
    badge, its `done of total`, its elapsed time and its cost; (c) an injected unknown state
    falls through to the neutral needs-attention badge with no error; (d) the run's progress is
    exactly the read's `{done} of {total}` — never a percentage and never a per-student ref."""
    _require_bundle()

    def _seed(store):
        world = _midrun_world(store)
        _quarantine_submission(store, world, world.submissions[-1],
                               status="incomplete", identity=None)
        return world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed) as served:
        run_id = served.server.run_id if hasattr(served.server, "run_id") else None
        assert run_id, "the served console carries no run in focus"
        parked = crw._get_json(served.port, "/api/v1/parked")
        assert len(parked["parked"]) == 1, (
            f"the parked read holds {len(parked['parked'])} papers, not the one quarantined")
        entry = parked["parked"][0]
        assert entry["resolvable"], (
            f"the quarantined paper with its ref kept is not resolvable: {entry!r}")

        # (b) a live authoring job in the registry, ~90 seconds in.
        started = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
        served.server.app._jobs.register(job_id="job-ui16", kind="authoring_draft", total=5,
                                         started_at=started)
        served.server.app._jobs.update(
            "job-ui16", state="running", done=2, total=5, current=None, cost_usd=1.25,
            stage="reading", attempt=1, attempts=3)

        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []

            # (a) the parked card.
            _goto(page, served.origin, "/parked")
            if f"{parked['counts']['total']} paper is parked." not in \
                    page.locator("main").inner_text():
                problems.append(f"arm (a): the parked count does not read the read's own "
                                f"total ({parked['counts']['total']})")
            cards = page.locator("ul.parked-list li.parked-card")
            if cards.count() != len(parked["parked"]):
                problems.append(f"arm (a): {cards.count()} parked cards render, not the read's "
                                f"{len(parked['parked'])}")
            card = cards.first
            if card.locator("p.parked-reason").inner_text() != entry["reason_label"]:
                problems.append(f"arm (a): the reason reads "
                                f"{card.locator('p.parked-reason').inner_text()!r}, not the "
                                f"read's own {entry['reason_label']!r}")
            if card.locator("p.parked-match").inner_text() != entry["match_note"]:
                problems.append(f"arm (a): the match note reads "
                                f"{card.locator('p.parked-match').inner_text()!r}, not the "
                                f"read's own {entry['match_note']!r}")
            resolutions = card.locator("ul.parked-resolutions li").all_inner_texts()
            if resolutions != list(entry["resolutions"]):
                problems.append(f"arm (a): the resolutions read {resolutions!r}, not the "
                                f"read's own {entry['resolutions']!r}")
            for name in ("Upload a replacement", "Release to scoring", "Close as unresolvable"):
                if card.get_by_role("button", name=name).count() != 1:
                    problems.append(f"arm (a): the {name!r} control is missing")
            card.get_by_role("button", name="Release to scoring").click()
            dialog = _dialog(page)
            if not _wait_for(problems, "arm (a)", page,
                             lambda: dialog.count() > 0 and dialog.first.is_visible(),
                             "the release confirmation to open"):
                pass
            else:
                dialog.first.get_by_role("button", name="Cancel").click()
                if not _wait_for(problems, "arm (a)", page,
                                 lambda: dialog.count() == 0 or not dialog.first.is_visible(),
                                 "the release confirmation to close on cancel"):
                    problems.append("arm (a): the release confirmation did not close on cancel")

            # (b) the jobs table's live authoring row.
            _goto(page, served.origin, f"/jobs?run={run_id}")
            table = page.locator("table.jobs-table")
            auth_row = page.locator("tr.job-row", has_text="Authoring draft")
            if not _wait_for(problems, "arm (b)", page,
                             lambda: auth_row.count() == 1 and table.is_visible(),
                             "the authoring job's row to render"):
                pass
            else:
                record = crw._get_json(served.port, "/api/v1/jobs/job-ui16")
                badge = auth_row.locator("span.badge")
                if badge.inner_text() != "Running":
                    problems.append(f"arm (b): the authoring job's badge reads "
                                    f"{badge.inner_text()!r}, not the record's own state")
                progress_text = f"{record['progress']['done']} of {record['progress']['total']}"
                if progress_text not in auth_row.inner_text():
                    problems.append(f"arm (b): the row does not read the record's own progress "
                                    f"({progress_text!r}): {auth_row.inner_text()!r}")
                if not re.search(r"\d+m \d+s", auth_row.inner_text()):
                    problems.append(f"arm (b): the row carries no elapsed time: "
                                    f"{auth_row.inner_text()!r}")
                if "$1.25" not in auth_row.inner_text():
                    problems.append(f"arm (b): the row does not read the record's own cost "
                                    f"($1.25): {auth_row.inner_text()!r}")

                # (c) the unknown state falls through to the neutral label, error-free.
                served.server.app._jobs.update(
                    "job-ui16", state="hovering", done=2, total=5, current=None, cost_usd=1.25,
                    stage="reading", attempt=1, attempts=3)
                neutral = page.locator("tr.job-row", has_text="Authoring draft") \
                    .locator("span.badge")
                if not _wait_for(problems, "arm (c)", page,
                                 lambda: neutral.inner_text() == "Needs attention",
                                 "the unknown state to fall through to needs attention"):
                    pass
                else:
                    if "badge-neutral" not in (neutral.get_attribute("class") or ""):
                        problems.append(f"arm (c): the neutral badge's class reads "
                                        f"{neutral.get_attribute('class')!r}, not the neutral "
                                        f"tone")
                    problems += _health(page, log, "arm (c)")

                # (d) the run's progress: the read's own counts, no percentage, no student ref.
                run_read = next(job for job in crw._get_json(served.port, "/api/v1/jobs")["jobs"]
                                if job["kind"] == "run")
                run_progress = (f"{run_read['progress']['done']} of "
                                f"{run_read['progress']['total']}")
                run_row = page.locator("tr.job-row", has_text="Grading run")
                if run_row.count() != 1:
                    problems.append(f"arm (d): {run_row.count()} grading-run rows render")
                elif run_progress not in run_row.first.inner_text():
                    problems.append(f"arm (d): the run row does not read the read's own "
                                    f"progress ({run_progress!r}): "
                                    f"{run_row.first.inner_text()!r}")
                elif run_row.first.get_by_role("button", name="Pause the run").count() != 1:
                    problems.append("arm (d): the running run's pause control is missing")
                main_text = page.locator("main").inner_text()
                if "%" in main_text:
                    problems.append("arm (d): a percentage reached the jobs screen")
                if "ref-" in table.inner_text():
                    problems.append("arm (d): a per-student ref reached the jobs table")
            problems += _health(page, log, "arms (b)+(d)")
            problems += _egress_problems(log, "all arms")
            _fail_with(problems)


# --- TC-UI-17 — the settings screen -----------------------------------------------------------------------


def test_tc_ui_17_the_settings_screen_projects_every_setting_and_round_trips_a_save(
        tmp_data_dir, tmp_path, network_guard, monkeypatch):
    """`TC-UI-17` / FR-UI-20 (P1) — the settings screen: every projected setting's label shows,
    each editable one as its own form control (a choice row as a select carrying the read's own
    options), the non-editable ones read-only in the fixed list with the secret as
    "configured" and nothing else; a save round-trips through the console's `update
    configuration` action into the configuration file the console was served with."""
    _require_bundle()

    config_path = tmp_path / "console-settings.toml"
    config_path.write_text(_settings_config_toml(), encoding="utf-8")
    monkeypatch.setenv(OPENROUTER_API_KEY_ENV, "sk-test-ui17")

    def _seed(store):
        world = _midrun_world(store, submissions=2)
        return world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed,
                  cfg=tomllib.loads(config_path.read_text(encoding="utf-8")),
                  config_path=config_path, profile="dev-ci") as served:
        settings = crw._get_json(served.port, "/api/v1/config")["settings"]
        assert settings, "the configuration read projects no settings"
        round_row = next(row for row in settings
                         if row["field"] == "decision_citation_question_limit")
        assert round_row["editable"], (
            f"the citation-question limit does not project as editable: {round_row!r}")
        current = int(str(round_row["value"]))

        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            _goto(page, served.origin, "/settings")
            main = page.locator("main")
            for row in settings:
                if row["label"] not in main.inner_text():
                    problems.append(f"settings: the row {row['field']!r} shows no label "
                                    f"({row['label']!r})")
            for row in settings:
                if not row["editable"]:
                    continue
                control = page.locator(f"#setting-{row['field']}")
                if control.count() != 1:
                    problems.append(f"settings: the editable row {row['field']!r} renders "
                                    f"{control.count()} controls")
                elif row.get("choices"):
                    values = _option_values(page, f"#setting-{row['field']}")
                    if values != list(row["choices"]):
                        problems.append(f"settings: the choice row {row['field']!r} offers "
                                        f"{values!r}, not the read's own {row['choices']!r}")
            fixed = page.locator("section.settings-fixed")
            for row in settings:
                if row["editable"]:
                    continue
                if fixed.count() != 1 or row["label"] not in fixed.first.inner_text():
                    problems.append(f"settings: the non-editable row {row['field']!r} is not "
                                    f"in the read-only list")
                    continue
                # The value itself, read-only: the row's dd renders the read's own value —
                # the credential rows as "Configured ✓"/"Not configured" (the shipped
                # valueLabel's rule), an empty value as the em dash, a boolean as
                # JavaScript spells it.
                if row.get("type") == "secret":
                    shown = "Configured ✓" if row.get("configured") else "Not configured"
                else:
                    raw = row.get("value")
                    shown = "—" if raw == "" else (
                        "true" if raw is True else "false" if raw is False else str(raw))
                value = fixed.first.locator("div.settings-row").filter(
                    has_text=row["label"]).locator("dd")
                rendered = value.first.inner_text().strip() if value.count() else "nothing"
                if value.count() != 1 or rendered != shown:
                    problems.append(f"settings: the read-only row {row['field']!r} renders "
                                    f"{rendered!r}, not the read's own {shown!r}")
            secret = next(row for row in settings if row["type"] == "secret")
            if fixed.count() != 1 or "Configured ✓" not in fixed.first.inner_text():
                problems.append("settings: the credential does not show as configured and "
                                "nothing more")
            if secret["label"] not in (fixed.first.inner_text() if fixed.count() else ""):
                problems.append("settings: the secret row's label is not in the read-only list")
            if page.locator(f"#setting-{secret['field']}").count() != 0:
                problems.append("settings: the secret renders an editable control")

            # The round-trip: change the limit, confirm, and read the written file back.
            page.locator("#setting-decision_citation_question_limit").fill(str(current + 1))
            save = page.get_by_role("button", name="Save the changes")
            if not _wait_for(problems, "settings", page, save.is_enabled,
                             "the save button to enable once a value changed"):
                pass
            save.click()
            dialog = _dialog(page)
            if not _wait_for(problems, "settings", page,
                             lambda: dialog.count() > 0 and dialog.first.is_visible(),
                             "the change confirmation to open"):
                pass
            else:
                dialog_text = dialog.first.inner_text()
                if "1 setting" not in dialog_text or \
                        round_row["label"] not in dialog_text:
                    problems.append(f"settings: the confirmation reads {dialog_text!r}, not "
                                    f"one named setting")
                dialog.first.get_by_role("button", name="Change").click()
                outcome = page.locator("p.action-outcome")
                if not _wait_for(problems, "settings", page,
                                 lambda: outcome.count() > 0 and
                                 "1 setting(s) updated in" in outcome.first.inner_text(),
                                 "the save's outcome line to name the update"):
                    pass
                elif "Refused:" in outcome.first.inner_text():
                    problems.append(f"settings: the save was refused: "
                                    f"{outcome.first.inner_text()!r}")
                elif round_row["field"] not in outcome.first.inner_text():
                    problems.append(f"settings: the outcome line does not name the changed "
                                    f"setting: {outcome.first.inner_text()!r}")
            written = tomllib.loads(config_path.read_text(encoding="utf-8"))
            written_value = written.get("profiles", {}).get("dev-ci", {}) \
                .get("HARNESS_JEV_MAX_CITATION_QUESTIONS")
            if written_value != current + 1:
                problems.append(f"settings: the configuration file holds "
                                f"{written_value!r} after the save, not {current + 1}")
            problems += _health(page, log, "settings")
            problems += _egress_problems(log, "settings")
            _fail_with(problems)


# --- TC-UI-18 — help everywhere ---------------------------------------------------------------------------


def test_tc_ui_18_the_help_panel_opens_everywhere_and_the_ask_carries_the_screen(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-UI-18` / FR-UI-21 (P1) — the help panel opens once and rides every secondary page
    and the wizard home, naming each screen's manual section with the manual's own heading and
    linking to the manuals; the ask fired from a screen carries that screen's identity inside
    the request's context and renders the assistant's grounded answer."""
    _require_bundle()

    def _seed_help(store):
        world = seed_scored_run(store, submissions=1)
        return world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed_help,
                  build_assistant=lambda store: hv.make_assistant(
                      store, hv.QaDouble(tmp_data_dir / "qa-rec-ui18"), HOSTED_JUDGE)) as served:
        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            _goto(page, served.origin, "/")
            page.locator("button.help-button").click()
            panel = page.locator("aside.help-panel")
            if not _wait_for(problems, "the panel", page, panel.is_visible,
                             "the help panel to open"):
                pass

            for route, keyword in _HELP_PLAN:
                _goto(page, served.origin, route)
                link = panel.locator("p.help-panel-section a", has_text=keyword)
                if not _wait_for(problems, f"help on {route}", page,
                                 lambda link=link: link.count() > 0,
                                 f"the manual-section link naming {keyword!r}"):
                    continue
                if panel.locator(".help-panel-manuals a[href^='/manuals/']").count() == 0:
                    problems.append(f"help on {route}: the panel carries no manuals link")

            _goto(page, served.origin, "/help")
            if "This screen's manual section" in panel.inner_text():
                problems.append("help on /help: the manuals page itself claims a per-screen "
                                "section")

            # The context ask from the wizard home: the screen id rides inside the context.
            _goto(page, served.origin, "/")
            box = panel.locator("form.qa-form textarea")
            box.fill(hv.CONTEXT_T.question)
            panel.get_by_role("button", name="Ask the assistant").click()
            answer = panel.locator("p.qa-answer-text")
            if not _wait_for(problems, "the ask", page,
                             lambda: answer.count() > 0 and
                             "review stage of the wizard" in answer.first.inner_text(),
                             "the grounded answer to render"):
                pass
            ask_urls = [u for u in log.requests if "/api/v1/help/ask" in u]
            if not ask_urls:
                problems.append("the ask never reached the console's help route")
            else:
                carried = parse_qs(urlsplit(ask_urls[-1]).query).get("context", [""])[0]
                try:
                    payload = json.loads(carried)
                except ValueError:
                    problems.append(f"the ask's context parameter is not JSON: {carried!r}")
                else:
                    if payload.get("screen") != "wizard-home":
                        problems.append(f"the ask's context carries screen "
                                        f"{payload.get('screen')!r}, not the wizard home")
            problems += _health(page, log, "help everywhere")
            problems += _egress_problems(log, "help everywhere")
            _fail_with(problems)


# --- TC-UI-19 — no confirm-free posts ---------------------------------------------------------------------


def test_tc_ui_19_no_select_or_toggle_posts_until_an_explicit_confirm(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-UI-19` / CT-UI-09, RS-11 (P0) — the blind-sample defect's generalized regression:
    one browser session walks every select and toggle the redesign introduced — the header
    switchers, the results filters and sort, the override's band select, the job row's pause,
    the parked paper's release, the settings choice — and none of it posts; then the editor's
    staging-only step posts nothing while its confirmed save does (the positive anchor)."""
    _require_bundle()

    def _seed(store):
        finished, running = _two_run_world(store)
        _quarantine_submission(store, running, running.submissions[-1],
                               status="incomplete", identity=None)
        return running.run_id

    config_path = tmp_data_dir / "walk-settings.toml"
    config_path.write_text(_settings_config_toml(), encoding="utf-8")
    monkeypatch.setenv(OPENROUTER_API_KEY_ENV, "sk-test-ui19")

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed,
                  cfg=tomllib.loads(config_path.read_text(encoding="utf-8")),
                  config_path=config_path, profile="dev-ci") as served:
        finished_class, finished_run, running_class, running_run = _two_ids(served)
        done, total = _run_progress(served, running_run)
        midrun_detail = f"Grading points: {done} of {total} done."
        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []

            # The header switchers: the run switcher first (it re-derives stage 7 to the
            # mid-run's own counts), then the class switcher under the kept run.
            _goto(page, served.origin, f"/?class={finished_class}&run={finished_run}")
            page.select_option("#switcher-run", running_run)
            _wait_for(problems, "the run switcher", page,
                      lambda: _stage(page, 7).locator("span.stage-detail").inner_text()
                      == midrun_detail,
                      "the run switch to re-derive stage 7 with the mid-run's own counts")
            page.select_option("#switcher-class", running_class)
            _wait_for(problems, "the class switcher", page,
                      lambda: _stage(page, 7).locator("span.stage-detail").inner_text()
                      == midrun_detail,
                      "the class switch to keep the run and leave stage 7 in progress")

            # The results screen's override band select first — the level and flag filters
            # below legitimately empty the student list (no student carries that band or
            # flag), and an emptied list renders no band select to change.
            _goto(page, served.origin, f"/results?class={finished_class}&run={finished_run}")
            _wait_for(problems, "results", page,
                      lambda: page.locator("select[name^='criterion-band-']").count() > 0,
                      "the override's band selects to render")
            override = page.locator("details.override").first
            if override.count():
                override.locator("summary").first.click()
            # Every student's override carries its own band selects, so the change targets
            # the opened override's first one.
            _change_select(page, problems, "results",
                           "details.override select[name^='criterion-band-'] >> nth=0")

            # Then the filters, sort and search.
            _change_select(page, problems, "results", "select[name='level-filter']")
            _change_select(page, problems, "results", "select[name='flag-filter']")
            _change_select(page, problems, "results", "select[name='student-sort']")
            page.locator("input[name='student-search']").fill("ref")
            finalize = page.get_by_role("button", name="Finalize the batch")
            if finalize.count() == 1:
                finalize.click()
                dialog = _dialog(page)
                if not _wait_for(problems, "results", page,
                                 lambda: dialog.count() > 0 and dialog.first.is_visible(),
                                 "the finalize confirmation to open"):
                    pass
                else:
                    dialog.first.get_by_role("button", name="Cancel").click()
                    _wait_for(problems, "results", page,
                              lambda: dialog.count() == 0 or not dialog.first.is_visible(),
                              "the finalize confirmation to close on cancel")
            else:
                problems.append("results: the finalize-batch control is missing")

            # The job row's pause (on the running run), the parked paper's release. The row
            # is picked by its own state badge — every run row's kind reads "Grading run".
            _goto(page, served.origin, f"/jobs?class={running_class}&run={running_run}")
            pause = page.locator("tr.job-row", has_text="Running") \
                .get_by_role("button", name="Pause the run")
            if not _wait_for(problems, "jobs", page,
                             lambda: page.locator("tr.job-row", has_text="Running")
                             .get_by_role("button", name="Pause the run").count() == 1,
                             "the running run's pause control"):
                pass
            else:
                pause.first.click()
                dialog = _dialog(page)
                if not _wait_for(problems, "jobs", page,
                                 lambda: dialog.count() > 0 and dialog.first.is_visible(),
                                 "the pause confirmation to open"):
                    pass
                else:
                    dialog.first.get_by_role("button", name="Cancel").click()
                    _wait_for(problems, "jobs", page,
                              lambda: dialog.count() == 0 or not dialog.first.is_visible(),
                              "the pause confirmation to close on cancel")
            _goto(page, served.origin, f"/parked?class={running_class}&run={running_run}")
            release = page.locator("ul.parked-list li.parked-card").first \
                .get_by_role("button", name="Release to scoring")
            if not _wait_for(problems, "parked", page,
                             lambda: page.locator("ul.parked-list li.parked-card").first
                             .get_by_role("button", name="Release to scoring").count() == 1,
                             "the parked paper's release control"):
                pass
            else:
                release.click()
                dialog = _dialog(page)
                if not _wait_for(problems, "parked", page,
                                 lambda: dialog.count() > 0 and dialog.first.is_visible(),
                                 "the release confirmation to open"):
                    pass
                else:
                    dialog.first.get_by_role("button", name="Cancel").click()
                    _wait_for(problems, "parked", page,
                              lambda: dialog.count() == 0 or not dialog.first.is_visible(),
                              "the release confirmation to close on cancel")

            # The settings screen's choice select.
            _goto(page, served.origin, f"/settings?class={running_class}&run={running_run}")
            _change_select(page, problems, "settings", "#setting-decision_engine")

            if _action_urls(log):
                problems.append(f"the walked session posted without an explicit confirm: "
                                f"{_action_urls(log)!r}")
            problems += _health(page, log, "the walked session")
            problems += _egress_problems(log, "the walked session")
            _fail_with(problems)

    # The positive anchor: staging posts nothing; the confirmed save does.
    def _seed_authoring(store):
        world = _midrun_world(store, submissions=2)
        return world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, authoring=True,
                  seed=_seed_authoring, cfg=crw.recorded_authoring_config()) as served:
        _answer, record = crw.run_draft_job(served.port, "AF-02")
        assert record["state"] == "succeeded", f"the AF-02 draft job ended {record['state']}"
        package_id = crw.draft_read(served.port)["draft"]["package_id"]
        _ensure_ledger(served.store, package_id)
        with spa.spa_page(served.origin) as (page, log):
            problems = []
            _goto(page, served.origin, f"/package/edit?package={package_id}")
            page.locator("#add-q-text").fill("What condenses into clouds?")
            page.locator("#add-q-type").select_option("open")
            page.locator("#add-q-points").fill("2")
            page.locator("#add-q-answer").fill("Water vapour.")
            page.get_by_role("button", name="Stage the new question").click()
            _wait_for(problems, "the staged add", page,
                      lambda: page.locator(
                          "section[aria-label='Your changes'] ul.change-list li").count() == 1,
                      "the staged change to appear")
            if _action_urls(log):
                problems.append(f"staging posted without the save: {_action_urls(log)!r}")
            page.get_by_role("button", name=re.compile(r"Review changes \(1\)")).click()
            dialog = _dialog(page)
            _wait_for(problems, "the save confirmation", page,
                      lambda: dialog.count() > 0 and dialog.first.is_visible(),
                      "the save confirmation to open")
            dialog.first.get_by_role("button", name="Save the changes").click()
            if not _wait_for(problems, "the confirmed save", page,
                             lambda: page.locator(".change-list-applied").count() > 0,
                             "the save to apply"):
                pass
            if not any("edit-draft-package" in url for url in _action_urls(log)):
                problems.append("the confirmed save never reached the console's action surface")
            problems += _health(page, log, "the editor session")
            problems += _egress_problems(log, "the editor session")
            _fail_with(problems)


# --- TC-UI-20 — the state rendering pairs -----------------------------------------------------------------


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        scaled = value / 255.0
        return scaled / 12.92 if scaled <= 0.04045 else ((scaled + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    lighter, darker = sorted((_relative_luminance(a), _relative_luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _rgb(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def test_tc_ui_20_every_state_badge_pairs_icon_text_colour_at_aa_contrast(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-UI-20` / CT-UI-10 (P1) — the state-rendering pairs: the static token audit asserts
    every pair the badges render meets AA (ratio >= 4.5), and the browser arm asserts every
    rendered badge pairs its icon with a visible text label — icon + text + colour, never a
    colour alone."""
    _require_bundle()

    colors = spa.load_tokens()["color"]
    pairs = (("success", "successBg"), ("warning", "warningBg"), ("info", "infoBg"),
             ("danger", "dangerBg"), ("muted", "neutralBg"),
             ("dangerInk", "danger"), ("accentInk", "accent"))
    static_problems = []
    for foreground, background in pairs:
        for token in (foreground, background):
            if token not in colors:
                static_problems.append(f"the token {token!r} is not in the design tokens")
        if foreground in colors and background in colors:
            ratio = _contrast(_rgb(colors[foreground]), _rgb(colors[background]))
            if ratio < 4.5:
                static_problems.append(
                    f"{foreground} on {background} contrasts at {ratio:.2f}, below AA (4.5)")
    assert not static_problems, "\n".join(static_problems)

    def _seed(store):
        world = _finished_published_world(store, submissions=2)
        return world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed) as served:
        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            for where, path in (("the wizard home", "/"), ("the jobs page", "/jobs")):
                _goto(page, served.origin, path)
                badges = page.locator("header span.badge, main span.badge")
                if not _wait_for(problems, where, page, lambda: badges.count() > 0,
                                 "at least one state badge to render"):
                    continue
                malformed = page.evaluate(
                    """() => Array.from(document.querySelectorAll('header span.badge, main span.badge'))
                    .map(b => ({svg: !!b.querySelector('svg[aria-hidden]'),
                                text: (b.querySelector('span')
                                       ? b.querySelector('span').textContent.trim() : '')}))
                    .filter(b => !b.svg || b.text === '')""")
                if malformed:
                    problems.append(f"{where}: badges without their icon+text pair: "
                                    f"{malformed!r}")
                problems += _health(page, log, where)
                problems += _egress_problems(log, where)
            _fail_with(problems)


# --- TC-UI-21 — the budgets -------------------------------------------------------------------------


def _timed_transition(page: Any, problems: list[str], where: str, go: Callable[[], Any],
                      title: str) -> None:
    """One transition against the bundle's transition budget: the clock starts before the
    navigation and stops when the destination's level-1 heading is visible."""
    start = time.perf_counter()
    go()
    heading = page.locator("main h1", has_text=title).first
    try:
        heading.wait_for(state="visible", timeout=spa.TRANSITION_BUDGET_MS)
    except Exception:
        problems.append(f"{where}: the transition to {title!r} did not show its heading within "
                        f"the {spa.TRANSITION_BUDGET_MS} ms budget")
        return
    elapsed = (time.perf_counter() - start) * 1000.0
    if elapsed > spa.TRANSITION_BUDGET_MS:
        problems.append(f"{where}: the transition to {title!r} took {elapsed:.0f} ms, over the "
                        f"{spa.TRANSITION_BUDGET_MS} ms budget")


def test_tc_ui_21_the_new_bundle_meets_the_load_and_transition_budgets(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-UI-21` / CT-UI-11, RS-13 (P1) — the budgets, through the suite's own budget
    constants: the bundle's first contentful paint lands within the FCP budget, and every
    screen transition — the wizard's own stage links and the same-document hash jumps — shows
    the destination within the transition budget."""
    _require_bundle()

    def _seed(store):
        # The mid-run world: stages 1, 5 and 8 read done or actionable, so their rows link to
        # their own screens (a not-started stage links to where the teacher acts next, not to
        # the stage's screen) — the destinations the plan's stage links name.
        world = _midrun_world(store, submissions=2)
        return world.run_id

    with _console(tmp_data_dir, network_guard, monkeypatch, seed=_seed) as served:
        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            _goto(page, served.origin, "/")
            fcp = page.evaluate(
                "() => { const entries = performance.getEntriesByName("
                "'first-contentful-paint'); return entries.length ? entries[0].startTime : null; }")
            if fcp is None:
                problems.append("the browser recorded no first-contentful-paint entry")
            elif float(fcp) > spa.FCP_BUDGET_MS:
                problems.append(f"the first contentful paint took {float(fcp):.0f} ms, over "
                                f"the {spa.FCP_BUDGET_MS} ms budget")

            # The wizard's own stage links: real clicks on the stepper's rows, each to the
            # screen its own href names (read from the row, never assumed).
            for number in (1, 5, 8):
                row = _stage(page, number)
                href = row.locator("a.stage-row").get_attribute("href") or ""
                route = href.split("#", 1)[-1].split("?", 1)[0]
                title = ROUTE_TITLES.get(route)
                if title is None:
                    problems.append(f"stage {number}: the row links to {href!r}, which the "
                                    f"suite holds no heading for")
                    continue
                _timed_transition(page, problems, f"stage {number}",
                                  lambda row=row: row.locator("a.stage-row").click(), title)
                _goto(page, served.origin, "/")

            # The same-document hash jumps the header and navigation produce.
            for path, title in (("/settings", "Settings"), ("/jobs", "Jobs"),
                                ("/help", "Manuals & help")):
                _timed_transition(page, problems, f"jump to {path}",
                                  lambda path=path: page.goto(f"{served.origin}#{path}",
                                                              wait_until="domcontentloaded"),
                                  title)
            problems += _health(page, log, "budgets")
            problems += _egress_problems(log, "budgets")
            _fail_with(problems)
