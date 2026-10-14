"""TC-REQ-137 — the derivation matrix: every §3.3.4 row, a seeded store, exact states (E6).

Test plan §3.7 (issue #774): *"For each row of the design delta's derivation table (§3.3.4),
a seeded store state whose derived wizard states are asserted exactly (spans reads + UI; the
UI arms are TC-UI-08's, this is the derivation-matrix completeness case at rung 3)."*

Design delta §3.3.4: *"States derive from data, not from clicks: the derivation table below
is the contract between the reads and the stepper."* The table's nine rows are the contract;
this case seeds each row's store state and asserts the wizard's nine stage rows **exactly** —
state, detail line and next action, against `ui/src/wizard/derivation.ts`'s shipped rules.
"Exactly" is the oracle: a *looser* assertion (state only) would stay green when a detail
invented a count no read supplied (`CT-UI-08`) or an action named a route the stage cannot
honor — the derivation's words are part of the design's contract, not decoration.

**The seven worlds.** §3.3.4's nine rows share states (row 4's "a published version exists"
is one state for two seeds: published-with-draft and published-final), so the matrix needs
seven seeded store states to cover **every row** — each row's state as the shipped
derivation derives it, exactly. Coverage is per *row*, not per arm: a few sibling arms are
left to the suites that reach them in a journey (stage 7's queued arm is TC-REQ-139's
papers snapshot; stage 5's zero-uploaded and stage 6's failed arms are the derivation's
degenerate shapes this matrix's worlds do not seed). A regression inside a covered arm
fails here; one inside an uncovered arm must be caught by its own suite or a later story —
this case does not claim to carry it:

| world | rows | store state |
|---|---|---|
| bare | 1 | a class ledger with two roster students; nothing else exists |
| draft-missing | 2, 3 | the class, a package, and a draft carrying two `<<PLACEHOLDER: …>>` sentinels |
| draft-ready | 3 | the draft with every piece filled — zero sentinels |
| finished | 4, 5, 6, 7, 8, 9 | graded, finalized, published, nothing left to finalize (the exporting stage) |
| midrun | 5, 7 | a running run with one grading point still pending |
| reviewing | 8 | a complete run whose grades are not final (the reviewing stage) |
| parked | 5, 6 | the midrun with one paper parked |

The draft worlds exercise the shipped placeholder machinery, not a stub: a draft file is a
real TOML under the console's draft directory, and "missing pieces" is `draft_placeholders`'s
count of `<<PLACEHOLDER: …>>` sentinels (`aeh.console.authoring_reads`), the same figure the
authoring screens count.

**Three consoles, one reason.** Row 1's world is served alone: with any other world's
package in the store, the context read carries packages and the wizard's row-2 fallback
honestly says "Choose a test package." — a true derivation of a *different* store state. The
matrix's rows are store states, so each console's store holds exactly the worlds it serves;
within a console every per-entity stage is reached by explicit selection (`/?class=…&
package=…&run=…`), the address's own contract, so no world's counts can borrow another's.

**The server half.** "Spans reads + UI" is asserted, not narrated: for each world the
context read's own wizard rows (the package stages' server-derived states) and the run's
derived stage are read over HTTP and asserted beside the rendered stepper. One shipped
consequence is asserted as it ships: the context read carries a wizard row's detail only for
`needs_attention`/`failed` states (`_package_rows`), so a *done* package stage's rendered
detail is empty even though the read computes a sentence for it — the client renders the
read's own answer, never its own copy of the rule.

**Progress figures.** The midrun's "Grading points: … of … done." is asserted against the
jobs read's own figures (`done`/`total` for the run's job) — the same read the derivation
counts — plus the seeded shape (`done == total - 1`), so the detail line can neither invent
nor round.

**Oracles on every console** (the E6 floor): no uncaught page error, no unhandled rejection,
no raw error text, no egress (`log.foreign_requests()` empty), and no mutation request — the
matrix only reads.

Markers: `browser` (E6) and `integration` (the fast tier excludes it, TS-49's rule).
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from aeh.pkg import PackageCatalog
from tests.support import console_redesign_world as crw
from tests.support import spa
from tests.support.console_world import STAMP, seed_scored_run
from tests.support.impl import require_path

pytestmark = [pytest.mark.browser, pytest.mark.integration]

#: The console's action surface: a URL carrying this prefix is a mutation request. The
#: matrix reads; nothing it visits may post.
ACTION_URL_MARK = "/api/v1/actions/"

#: The wizard's stepper locator — the redesigned home has no level-1 heading; its rows are
#: `ol[aria-label="The nine stages"] > li.stage` (`ui/src/wizard/WizardHome.tsx`).
_STEPS = 'ol[aria-label="The nine stages"] li.stage'

#: The wizard home's route prefix: every world is reached by explicit selection.
_HOME = "/"


# --- the seven worlds' ids -------------------------------------------------------------------------


IDS = {
    "bare": ("cls-d137a", None, None),
    "draft_missing": ("cls-d137b", "pap-d137b", None),
    "draft_ready": ("cls-d137c", "pap-d137c", None),
    "finished": ("cls-d137d", "pap-d137d", "run-d137d"),
    "midrun": ("cls-d137e", "pap-d137e", "run-d137e"),
    "reviewing": ("cls-d137f", "pap-d137f", "run-d137f"),
    "parked": ("cls-d137g", "pap-d137g", "run-d137g"),
}


def _route(world: str) -> str:
    """The wizard home's address for one world: explicit selection, the hash's own contract."""
    cls, pkg, run = IDS[world]
    parts = [f"class={cls}"]
    if pkg is not None:
        parts.append(f"package={pkg}")
    if run is not None:
        parts.append(f"run={run}")
    return f"{_HOME}?{'&'.join(parts)}"


# --- the expected vectors ---------------------------------------------------------------------------
#
# Each world's nine stage rows, exactly as `derivation.ts` derives them and `WizardHome`
# renders them: `(state, detail, action-or-None)` per row, in stage order. The badge's text
# for each state is `stageStateLabel`'s mapping (asserted beside the class below).


def _vec(*rows: tuple[str, str, str | None]) -> tuple[tuple[str, str, str | None], ...]:
    assert len(rows) == 9, f"a world's vector names {len(rows)} of the 9 stages"
    return rows


NO_RUN_TAIL: tuple[tuple[str, str, str | None], ...] = (
    ("not_started", "", None),   # 6 reading
    ("not_started", "No grading run has started.", "Start the run"),   # 7
    ("not_started", "", None),   # 8 review
    ("not_started", "", None),   # 9 export
)

EXPECTED: dict[str, tuple[tuple[str, str, str | None], ...]] = {
    # Row 1: the class exists with at least two students — and nothing else exists yet.
    "bare": _vec(
        ("done", "2 students.", None),
        ("not_started", "No test package exists yet.", "Create the package"),
        ("not_started", "", None),
        ("not_started", "", None),
        ("not_started", "No papers are uploaded yet.", "Upload the papers"),
        *NO_RUN_TAIL,
    ),
    # Rows 2-3, the draft's missing pieces: the review walk is not complete.
    "draft_missing": _vec(
        ("done", "2 students.", None),
        ("done", "", None),
        ("needs_attention", "The draft has 2 missing pieces.", "Review the draft"),
        ("not_started", "Nothing is published yet.", None),
        ("not_started", "No papers are uploaded yet.", "Upload the papers"),
        *NO_RUN_TAIL,
    ),
    # Row 3's done arm: no missing pieces, the review walk complete.
    "draft_ready": _vec(
        ("done", "2 students.", None),
        ("done", "", None),
        ("done", "", None),
        ("not_started", "Nothing is published yet.", "Review and approve"),
        ("not_started", "No papers are uploaded yet.", "Upload the papers"),
        *NO_RUN_TAIL,
    ),
    # Rows 4-9, the finished arm of each: published, every paper read, the run finished,
    # every grade final, the export the one thing left.
    "finished": _vec(
        ("done", "3 students.", None),
        ("done", "", None),
        ("done", "", None),
        ("done", "A published version is ready.", None),
        ("done", "3 papers uploaded for 3 students.", None),
        ("done", "Every paper was read; none are parked.", None),
        ("done", "The run finished.", None),
        ("done", "Every grade is final.", None),
        ("queued", "The grades are final — the export can run.", "Export the results"),
    ),
    # Rows 5 and 7's in-flight arms: the papers are in, the run is grading one point short.
    "midrun": _vec(
        ("done", "5 students.", None),
        ("done", "", None),
        ("not_started", "", None),
        ("not_started", "Nothing is published yet.", None),
        ("done", "5 papers uploaded for 5 students.", None),
        ("done", "Every paper was read; none are parked.", None),
        ("in_progress", "PROGRESS", None),   # replaced with the jobs read's own figures
        ("not_started", "", None),
        ("not_started", "", None),
    ),
    # Row 8's other arm: the run is complete, the grades are not final yet.
    "reviewing": _vec(
        ("done", "2 students.", None),
        ("done", "", None),
        ("not_started", "", None),
        ("not_started", "Nothing is published yet.", None),
        ("done", "2 papers uploaded for 2 students.", None),
        ("done", "Every paper was read; none are parked.", None),
        ("done", "The run finished.", None),
        ("in_progress", "The grades need review before they are final.", "Review results"),
        ("not_started", "", None),
    ),
    # Rows 5-6's needs-attention arms: a paper is parked.
    "parked": _vec(
        ("done", "5 students.", None),
        ("done", "", None),
        ("not_started", "", None),
        ("not_started", "Nothing is published yet.", None),
        ("needs_attention", "1 paper is parked.", "Open the parked page"),
        ("needs_attention", "1 paper is parked.", "Open the parked page"),
        ("in_progress", "PROGRESS", None),   # replaced with the jobs read's own figures
        ("not_started", "", None),
        ("not_started", "", None),
    ),
}

#: The context read's wizard rows per world: stage -> (state, detail). The read carries a
#: detail only for `needs_attention`/`failed` rows — the shipped rule asserted below.
WIZARD_ROWS: dict[str, dict[str, tuple[str, str]]] = {
    # The bare world carries no package: the context read lists none, and the expectation
    # is that absence — the wizard's stage-2 fallback arm is the row's absence made copy.
    "bare": {},
    "draft_missing": {
        "create package": ("done", ""),
        "review draft": ("needs_attention", "The draft has 2 missing pieces."),
        "approve package": ("not_started", ""),
    },
    "draft_ready": {
        "create package": ("done", ""),
        "review draft": ("done", ""),
        "approve package": ("not_started", ""),
    },
    "finished": {
        "create package": ("done", ""),
        "review draft": ("done", ""),
        "approve package": ("done", ""),
    },
}
_NO_DRAFT_ROWS = {
    "create package": ("done", ""),
    "review draft": ("not_started", ""),
    "approve package": ("not_started", ""),
}
for _world in ("midrun", "reviewing", "parked"):
    WIZARD_ROWS[_world] = dict(_NO_DRAFT_ROWS)

#: The run stage the context read derives per world (§3.3.4's stage column, runs only).
RUN_STAGE = {"finished": "exporting", "midrun": "grading", "reviewing": "reviewing",
             "parked": "grading"}


# --- the served console -------------------------------------------------------------------------------


@dataclass
class Served:
    data_dir: Path
    store: Any
    server: Any
    origin: str
    port: int


@contextmanager
def _console(root: Path, network_guard: Any, monkeypatch: Any,
             seed: Callable[[Any, Path], str | None]) -> Iterator[Served]:
    """A real console on a real loopback port over a real store seeded by `seed(store,
    data_dir)`; whatever the seeder returns names the run in focus."""
    from aeh.console import serve_console
    from aeh.store import open_store

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    root.mkdir(parents=True, exist_ok=True)
    store = open_store(root)
    # Browser tests are stood down from the socket guard (`tests/conftest.py`: the E6 oracle
    # is the browser's own request log), so the guard here is None — nothing to uninstall.
    if network_guard is not None:
        network_guard.uninstall()
    try:
        focused = seed(store, root)
        server = serve_console(store=store, run_id=focused, cfg=None, config_path=None)
    except BaseException:
        if network_guard is not None:
            network_guard.install()
        crw._close_console_store(store)
        raise
    host, port = server.socket.getsockname()[:2]
    try:
        yield Served(root, store, server, f"http://{host}:{port}", port)
    finally:
        try:
            server.terminate()
        finally:
            if network_guard is not None:
                network_guard.install()
            crw._close_console_store(store)


def _fetch(origin: str, path: str) -> str:
    with urllib.request.urlopen(origin + path) as response:
        return response.read().decode("utf-8", errors="replace")


# --- the seeding, world by world ----------------------------------------------------------------------


def _class_ledger(store: Any, cohort_id: str, students: int = 2) -> None:
    """A bare class ledger: the cohort row and its roster students, no papers."""
    handle = store.cohort(cohort_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES (:c, 'synthetic', :t)", c=cohort_id, t=STAMP)
        for index in range(1, students + 1):
            tx.execute("INSERT INTO roster (cohort_id, student_ref) VALUES (:c, :r)",
                       c=cohort_id, r=f"stu-{cohort_id}-{index:02d}")


def _draft(store_data_dir: Path, package_id: str, placeholders: int) -> None:
    """A real draft file: valid TOML under the console's draft directory, carrying
    `placeholders` `<<PLACEHOLDER: …>>` sentinels — the shipped missing-piece signal."""
    root = Path(store_data_dir, "authoring")
    root.mkdir(parents=True, exist_ok=True)
    pieces = [
        'text = "<<PLACEHOLDER: the question text is unwritten>>"',
        'model_answer = "<<PLACEHOLDER: the expected answer is unwritten>>"',
    ]
    filled = [
        'text = "What does the water cycle move?"',
        'model_answer = "Water becomes vapour, rises and falls as rain."',
    ]
    lines = [f'title = "Derivation draft {package_id}"', "", "[[question]]", 'id = "Q1"',
             'type = "mcq"', filled[0] if placeholders < 1 else pieces[0], "", "[[question]]",
             'id = "Q2"', 'type = "open"', filled[1] if placeholders < 2 else pieces[1], ""]
    Path(root, f"{package_id}.package.draft.toml").write_text(
        "\n".join(lines), encoding="utf-8")


def _package_ledger(store: Any, package_id: str) -> None:
    handle = store.package(package_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO package (package_id, created_at) VALUES (:p, :t)",
            p=package_id, t=STAMP)


def _park_one_unit(store: Any, world: Any) -> None:
    """A run whose grading points are all `done` but one still `pending` — the midrun shape
    `app.progress` counts (`done` + `pending` + in-flight + quarantined)."""
    with store.cohort(world.cohort_id).transaction() as tx:
        tx.execute("UPDATE work_unit SET status = 'done' WHERE run_id = :r", r=world.run_id)
        tx.execute(
            "UPDATE work_unit SET status = 'pending' WHERE work_id = "
            "(SELECT MIN(work_id) FROM work_unit WHERE run_id = :r)", r=world.run_id)


def _running_run(store: Any, world: Any) -> None:
    with store.cohort(world.cohort_id).transaction() as tx:
        tx.execute("UPDATE run SET status = 'running' WHERE run_id = :r", r=world.run_id)


def _publish(store: Any, world: Any) -> None:
    catalog = PackageCatalog(store.package(world.package_id), package_id=world.package_id)
    catalog.publish(world.package_version_id, approved_by="teacher-1")


def _complete(store: Any, world: Any) -> None:
    with store.cohort(world.cohort_id).transaction() as tx:
        tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=world.run_id)


def _park_paper(store: Any, world: Any) -> None:
    """One paper parked, with the ingest status the park reads its reason from."""
    submission = world.submissions[0]
    with store.cohort(world.cohort_id).transaction() as tx:
        tx.execute(
            "UPDATE submission SET quarantined = 1, ingest_status = 'unreadable', "
            "v3_identity = '' WHERE submission_id = :s", s=submission)


def _seed_bare(store: Any, data_dir: Path) -> str | None:
    _class_ledger(store, IDS["bare"][0])
    return None


def _seed_drafts(store: Any, data_dir: Path) -> str | None:
    for world, missing in (("draft_missing", 2), ("draft_ready", 0)):
        cls, pkg, _ = IDS[world]
        _class_ledger(store, cls)
        _package_ledger(store, pkg)
        _draft(data_dir, pkg, missing)
    return None


def _seed_runs(store: Any, data_dir: Path) -> str | None:
    # finished — rows 4..9's done arms: graded, finalized, published, nothing to finalize.
    finished = seed_scored_run(
        store, cohort_id=IDS["finished"][0], run_id=IDS["finished"][2],
        package_id=IDS["finished"][1], submissions=3, finalize=True)
    _complete(store, finished)
    _publish(store, finished)

    # midrun — rows 5 and 7's in-flight arms: running, one grading point pending.
    midrun = seed_scored_run(
        store, cohort_id=IDS["midrun"][0], run_id=IDS["midrun"][2],
        package_id=IDS["midrun"][1], submissions=5, enumerate_units=True)
    _park_one_unit(store, midrun)
    _running_run(store, midrun)

    # reviewing — row 8's other arm: complete, the grades not final.
    reviewing = seed_scored_run(
        store, cohort_id=IDS["reviewing"][0], run_id=IDS["reviewing"][2],
        package_id=IDS["reviewing"][1], submissions=2, finalize=False)
    _complete(store, reviewing)

    # parked — rows 5-6's needs-attention arms: the midrun with one paper parked.
    parked = seed_scored_run(
        store, cohort_id=IDS["parked"][0], run_id=IDS["parked"][2],
        package_id=IDS["parked"][1], submissions=5, enumerate_units=True)
    _park_one_unit(store, parked)
    _running_run(store, parked)
    _park_paper(store, parked)
    return finished.run_id


# --- the browser plumbing ---------------------------------------------------------------- them.


def _require_bundle() -> None:
    require_path(spa.BUNDLE_INDEX, "the committed SPA bundle (FR-UI-01)", issue="#634")


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


def _goto_home(page: Any, origin: str, query: str) -> None:
    """Fragment navigation to the wizard home with an explicit selection, waited until the
    stepper is visible and the console's read burst has settled."""
    page.goto(f"{origin}#{_HOME}{query}", wait_until="domcontentloaded")
    page.locator(_STEPS).first.wait_for(state="visible", timeout=spa.STEP_TIMEOUT_MS)
    page.wait_for_load_state("networkidle")


def _rendered_rows(page: Any) -> list[tuple[str, str, str | None]]:
    """The nine stage rows as rendered: `(state, badge text, detail, action)` — the class
    names the state, the badge the legend's label, the detail and action spans the words."""
    rows: list[tuple[str, str, str | None]] = []
    steps = page.locator(_STEPS)
    for index in range(9):
        row = steps.nth(index)
        classes = str(row.get_attribute("class") or "").split()
        state = next((c.removeprefix("stage-") for c in classes
                      if c.startswith("stage-") and c != "stage"), "")
        badge = row.locator("span.badge").inner_text().strip()
        detail = row.locator("span.stage-detail").inner_text().strip()
        actions = row.locator("span.stage-action")
        if actions.count() > 0:
            # The screen-reader prefix rides the same span (`.visually-hidden` is clipped,
            # not display-none, so inner_text carries it); the teacher's words follow it.
            action = re.sub(r"^Next action:\s*", "", actions.inner_text().strip())
        else:
            action = None
        rows.append((f"{state}|{badge}", detail, action))
    return rows


def _assert_world(page: Any, log: spa.SpaLog, served: Served, world: str,
                  problems: list[str]) -> None:
    """One world, asserted exactly: the rendered nine rows against the world's vector, the
    context read's wizard rows and run stage against the derivation's server half."""
    where = f"{world} ({_route(world)})"
    _goto_home(page, served.origin, _route(world)[len(_HOME):])

    expected = EXPECTED[world]
    # The midrun worlds' stage-7 detail is the jobs read's own figures — read them here, the
    # same read the derivation counts, so the rendered line can neither invent nor round.
    if "PROGRESS" in [row[1] for row in expected]:
        jobs = json.loads(_fetch(served.origin, "/api/v1/jobs"))
        job = next(j for j in jobs["jobs"]
                   if j["kind"] == "run" and str(j["job_id"]) == IDS[world][2])
        progress = job["progress"]
        assert progress["total"] is not None, (
            f"{where}: the jobs read carries no total for the run: {job!r}")
        done, total = int(progress["done"] or 0), int(progress["total"])
        assert done == total - 1, (
            f"{where}: the seeded midrun should read {total - 1} of {total} done, "
            f"the jobs read says {done} of {total}")
        expected = tuple(
            (state, f"Grading points: {done} of {total} done.", action)
            if detail == "PROGRESS" else (state, detail, action)
            for state, detail, action in expected)

    # The bounded poll — never a bare sleep: the derivation re-renders as the supplemental
    # reads land, so the rows are polled until they match or the bound passes.
    deadline = time.monotonic() + 20_000 / 1000.0
    while True:
        try:
            rendered = _rendered_rows(page)
            if rendered == [(f"{s}|{_badge(s)}", d, a) for s, d, a in expected]:
                break
        except Exception:  # the read may be mid-render; the bound decides
            rendered = None
        if time.monotonic() >= deadline:
            actual = rendered if rendered is not None else _rendered_rows(page)
            diff = "\n".join(
                f"  stage {index + 1}: expected {expected[index]!r}, rendered {actual[index]!r}"
                for index in range(9)
                if actual[index] != [(f"{s}|{_badge(s)}", d, a) for s, d, a in expected][index])
            problems.append(
                f"{where}: the wizard's rows do not derive the seeded state exactly:\n{diff}")
            break
        page.wait_for_timeout(250)

    # The server half: the context read's own wizard rows and run stage.
    context = json.loads(_fetch(served.origin, "/api/v1/context"))
    cls, pkg, run = IDS[world]
    rows_by_stage = {}
    for entry in context["packages"]:
        if entry["package_id"] == pkg:
            rows_by_stage = {str(row["stage"]): (str(row["state"]), str(row["detail"]))
                             for row in entry["wizard"]}
            break
    expected_rows = WIZARD_ROWS[world]
    if rows_by_stage != expected_rows:
        problems.append(
            f"{where}: the context read's wizard rows are not the derivation table's: "
            f"expected {expected_rows!r}, read {rows_by_stage!r}")
    stages = {str(r["run_id"]): str(r["stage"]) for r in context["runs"]}
    if run is not None and stages.get(run) != RUN_STAGE[world]:
        problems.append(
            f"{where}: the context read derives stage {stages.get(run)!r} for the run, "
            f"expected {RUN_STAGE[world]!r}")

    problems += _health(page, log, where)
    problems += _egress_problems(log, where)
    actions = _action_urls(log)
    if actions:
        problems.append(f"{where}: the matrix only reads, but mutation requests were issued: "
                        f"{actions}")


_BADGE = {"done": "Done", "in_progress": "In progress", "not_started": "Not started",
          "needs_attention": "Needs attention", "queued": "Queued", "failed": "Failed"}


def _badge(state: str) -> str:
    """The legend's label for a state (`vocabulary.ts`'s `stageStateLabel`) — asserted beside
    the row's class so the badge can never silently contradict the state it carries."""
    return _BADGE[state]


# --- the case ------------------------------------------------------------------------------------------


def test_tc_req_137_every_derivation_row_asserts_its_exact_wizard_states(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-REQ-137` — every §3.3.4 row's seeded store state derives exactly the wizard's
    nine stage rows, on the reads and on the rendered stepper both."""
    _require_bundle()
    problems: list[str] = []

    # One browser per console: the no-egress oracle is the request log matched against the
    # console's own origin, and three loopback consoles are three origins.
    # Row 1's world, alone: the fallback arms are honest only in a store holding
    # nothing else (the module docstring's three-console reason).
    with _console(tmp_data_dir / "bare", network_guard, monkeypatch,
                  seed=_seed_bare) as served:
        with spa.spa_page(served.origin) as (page, log):
            _assert_world(page, log, served, "bare", problems)

    # Rows 2-3: the draft worlds — the review walk's two arms.
    with _console(tmp_data_dir / "drafts", network_guard, monkeypatch,
                  seed=_seed_drafts) as served:
        with spa.spa_page(served.origin) as (page, log):
            _assert_world(page, log, served, "draft_missing", problems)
            _assert_world(page, log, served, "draft_ready", problems)

    # Rows 4-9: the run worlds — every run-borne arm of the table.
    with _console(tmp_data_dir / "runs", network_guard, monkeypatch,
                  seed=_seed_runs) as served:
        with spa.spa_page(served.origin) as (page, log):
            for world in ("finished", "midrun", "reviewing", "parked"):
                _assert_world(page, log, served, world, problems)

    assert not problems, "\n\n".join(problems)
