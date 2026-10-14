"""TC-REQ-139 — the progress-honesty journey: every rendered count is the store's (E6).

Test plan §3.7 (issue #774): *"Replay a seeded run in the browser, snapshotting progress
rendering at each stage: every rendered count matches the store's stage/criterion-batch
facts at that moment; no percentage or student-count appears anywhere (RS-05's
journey-level sweep)."*

RS-05's failure mode is a progress figure that is *almost* the truth: a percentage (which
invents a denominator the ledger never ratified), a per-student framing ("3 students
graded" — grading points are the unit the pipeline counts, `CT-CONSOLE-09`), or a count
that has drifted from the ledger by the time it renders. So the journey replays one seeded
run through its four stages — papers (not started), grading (mid-run), reviewing (finished,
grades not final), exporting (every grade final) — and at each stage snapshots the three
surfaces that render progress:

- the wizard's grading row (stage 7), whose detail is the read's `Grading points: D of T done.`;
- the monitor's Progress panel, M-ORCH's own grouped report (`done`/`in flight`/`pending`/
  `quarantined`);
- the jobs table's run row, whose Progress cell is the server's own counts ("12 of 40",
  `Jobs.tsx`'s stated contract).

**Bound to the store, not to the reads.** "Matches the store's facts" is asserted against
the `work_unit` ledger directly — the same grouped counts `app.progress` computes, read
here by SQL — and the rendered figures must equal them at every snapshot. The intermediate
reads (`/api/v1/jobs`) are asserted too, so a drift is localized: store → read → render.

**The bans, and the one interpretation the plan's wording needed.** No percentage
(`\\d+\\s*%`) may appear anywhere on the three screens at any snapshot. The student-count
ban is scoped to the progress-bearing elements — the grading row's detail, the monitor's
Progress panel, the jobs row's Progress cell — because §3.3.3's rule bans *progress counted
in students* ("students graded"), and the wizard's stage-5 sentence ("5 papers uploaded for
5 students") is the upload stage's own roster fact, the derivation's shipped copy the design
mandates: a page-wide word ban would condemn the design's own sentence, which is not the
defect RS-05 names. Progress is counted in grading points, nowhere in students.

**Between snapshots the store is mutated directly** (the ledger's own rows), and each
surface is revisited by fresh navigation — what renders is what the store holds *now*, not
what a poll cached. The journey never posts: the mutation is the test's SQL, the screens
only read.

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
from typing import Any, Iterator

import pytest

from aeh.grade import GradingService
from tests.support import console_redesign_world as crw
from tests.support import spa
from tests.support.console_world import STAMP, seed_scored_run
from tests.support.impl import require_path

pytestmark = [pytest.mark.browser, pytest.mark.integration]

#: The console's action surface: a URL carrying this prefix is a mutation request. The
#: journey reads; nothing it visits may post.
ACTION_URL_MARK = "/api/v1/actions/"

#: The wizard's stepper locator — the redesigned home has no level-1 heading (`WizardHome.tsx`).
_STEPS = 'ol[aria-label="The nine stages"] li.stage'

#: The percentage ban, RS-05's first dishonest unit: a figure the ledger never ratified.
_PERCENTAGE = re.compile(r"\d+\s*%")

#: The monitor's Progress panel is bound by **parsing** the rendered line into its
#: `field: value` pairs and asserting the four equal the store's counts — containment
#: ("done: 14" inside "done: 140") would let a drifted-up count pass as a digit prefix.
_MONITOR_PAIR = re.compile(r"\b(done|in flight|pending|quarantined):\s*(\d+)")

#: The world's ids: one class, one package, one run, five papers, three grading points each.
COHORT_ID, PACKAGE_ID, RUN_ID = "cls-h139", "pap-h139", "run-h139"
SUBMISSIONS = 5

#: The wizard home's address with the journey's selection: the hash carries the opaque refs
#: (`CT-UI-07`) and the derivation resolves the stage rows from them — a bare `/` selects
#: nothing, and stage 7 would honestly read "No grading run has started." over a run the
#: store holds. The journey names its run the way a teacher's arrival does.
_HOME = f"/?class={COHORT_ID}&run={RUN_ID}"

#: The run job's row on the jobs table, and the Progress cell's place in it (`Jobs.tsx`'s
#: column order: what, state, progress, elapsed, cost, actions).
_RUN_ROW = "tr.job-row"


# --- the served console -------------------------------------------------------------------------------


@dataclass
class Served:
    data_dir: Path
    store: Any
    server: Any
    origin: str
    port: int


@contextmanager
def _console(tmp_data_dir: Path, network_guard: Any, monkeypatch: Any) -> Iterator[Served]:
    """A real console on a real loopback port over a real store, seeded with the journey's
    one run — created and enumerated, its grading points still pending (the run row
    `pending`: the journey's first stage)."""
    from aeh.console import serve_console
    from aeh.store import open_store

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    store = open_store(tmp_data_dir)

    def _seed(store: Any) -> str:
        seed_scored_run(store, cohort_id=COHORT_ID, run_id=RUN_ID, package_id=PACKAGE_ID,
                        submissions=SUBMISSIONS, enumerate_units=True)
        return RUN_ID

    focused = _seed(store)
    # Browser tests are stood down from the socket guard (`tests/conftest.py`: the E6 oracle
    # is the browser's own request log), so the guard here is None — nothing to uninstall.
    if network_guard is not None:
        network_guard.uninstall()
    try:
        server = serve_console(store=store, run_id=focused, cfg=None, config_path=None)
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


def _fetch(origin: str, path: str) -> str:
    with urllib.request.urlopen(origin + path) as response:
        return response.read().decode("utf-8", errors="replace")


# --- the store's own facts ----------------------------------------------------------------------------


def _unit_counts(served: Served) -> dict[str, int]:
    """The run's grading-point counts, straight from the `work_unit` ledger — the store's
    own facts, grouped exactly as `app.progress` groups them (`done`; `open`/`in_flight`/
    `leased` in flight; `quarantined`; everything else pending)."""
    counts = {"done": 0, "in_flight": 0, "pending": 0, "quarantined": 0}
    rows = served.store.cohort(COHORT_ID).query(
        "SELECT status, COUNT(*) AS n FROM work_unit WHERE run_id = :r GROUP BY status",
        r=RUN_ID,
    )
    for row in rows:
        status, n = str(row["status"]), int(row["n"])
        if status == "done":
            counts["done"] += n
        elif status in ("open", "in_flight", "leased"):
            counts["in_flight"] += n
        elif status == "quarantined":
            counts["quarantined"] += n
        else:
            counts["pending"] += n
    counts["total"] = sum(counts.values())
    return counts


def _advance(served: Served, stage: str) -> None:
    """Move the seeded run to a stage by writing the ledger the way the pipeline would:
    grading points land `done` as the run proceeds; the run row moves; finalization makes
    every grade final. The journey's mutation is the store's, never a screen's."""
    with served.store.cohort(COHORT_ID).transaction() as tx:
        if stage != "papers":
            tx.execute("UPDATE work_unit SET status = 'done' WHERE run_id = :r", r=RUN_ID)
        if stage == "grading":
            # The midrun shape: every grading point computed but one still pending.
            tx.execute(
                "UPDATE work_unit SET status = 'pending' WHERE work_id = "
                "(SELECT MIN(work_id) FROM work_unit WHERE run_id = :r)", r=RUN_ID)
            tx.execute("UPDATE run SET status = 'running' WHERE run_id = :r", r=RUN_ID)
        elif stage in ("reviewing", "exporting"):
            tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=RUN_ID)
    if stage == "exporting":
        GradingService(served.store, clock=lambda: STAMP).finalize_batch(RUN_ID, "h139-journey")


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


def _goto(page: Any, origin: str, path: str) -> str:
    """Fragment navigation to a route. The wizard home has no level-1 heading, so it waits on
    the stepper; every other screen waits on its `main` h1 (the loaded-screen rule)."""
    route = path.split("?", 1)[0]
    page.goto(f"{origin}#{path}", wait_until="domcontentloaded")
    if route in ("", "/"):
        page.locator(f"{_STEPS}").first.wait_for(state="visible", timeout=spa.STEP_TIMEOUT_MS)
        page.wait_for_load_state("networkidle")
        return ""
    return spa.wait_for_screen(page)


def _poll(page: Any, predicate: Any, timeout_ms: int = 20_000) -> bool:
    """A bounded poll — never a bare sleep: retried every 250 ms until it turns true or the
    bound passes."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while True:
        try:
            if predicate():
                return True
        except Exception:  # the read may be mid-render; the bound decides
            pass
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(250)


# --- the three surfaces, per snapshot -----------------------------------------------------------------


def _wizard_row7(page: Any) -> tuple[str, str]:
    """The wizard's grading row as rendered: `(state, detail)` — the class names the state,
    the detail span the count line."""
    row = page.locator(_STEPS).nth(6)
    classes = str(row.get_attribute("class") or "").split()
    state = next((c.removeprefix("stage-") for c in classes
                  if c.startswith("stage-") and c != "stage"), "")
    return state, row.locator("span.stage-detail").inner_text().strip()


def _monitor_progress(page: Any) -> str:
    """The monitor's Progress panel's own line (the counts' sentence)."""
    return page.locator("section.panel").filter(
        has=page.get_by_role("heading", name="Progress")).locator("p").first.inner_text()


def _monitor_counts(page: Any) -> dict[str, int]:
    """The Progress line's `field: value` pairs, parsed — the four counts as rendered, so
    they can be asserted equal to the store's rather than merely contained in the line."""
    return {field: int(n) for field, n in _MONITOR_PAIR.findall(_monitor_progress(page))}


def _jobs_row(served: Served, page: Any) -> tuple[str, str]:
    """The run job's row as rendered: `(state badge, progress cell)`."""
    row = page.locator(_RUN_ROW).filter(has=page.get_by_role("rowheader", name="Grading run"))
    badge = row.locator("span.badge").first.inner_text().strip()
    return badge, row.locator("td").nth(1).inner_text().strip()


def _snapshot(served: Served, page: Any, log: spa.SpaLog, stage: str,
              problems: list[str]) -> None:
    """One stage of the journey: revisit the three surfaces fresh and bind every rendered
    count to the store's facts at this moment, plus the two bans."""
    counts = _unit_counts(served)
    where = f"stage {stage}"

    # --- the wizard's grading row ------------------------------------------------------------------
    _goto(page, served.origin, _HOME)
    expected_detail = {
        "papers": "The run is waiting to start.",
        "grading": f"Grading points: {counts['done']} of {counts['total']} done.",
        "reviewing": "The run finished.",
        "exporting": "The run finished.",
    }[stage]
    expected_state = {"papers": "queued", "grading": "in_progress",
                      "reviewing": "done", "exporting": "done"}[stage]
    # The jobs row's state badge: the run row's state as `jobStateLabel` names it
    # (queued -> Waiting, running -> Running, succeeded -> Done).
    expected_badge = {"papers": "Waiting", "grading": "Running",
                      "reviewing": "Done", "exporting": "Done"}[stage]

    def _row7_ok() -> bool:
        state, detail = _wizard_row7(page)
        return state == expected_state and detail == expected_detail

    if not _poll(page, _row7_ok):
        state, detail = _wizard_row7(page)
        problems.append(
            f"{where}: the wizard's grading row renders ({state!r}, {detail!r}), expected "
            f"({expected_state!r}, {expected_detail!r}) — the store holds "
            f"{counts['done']} done of {counts['total']} grading points")
    _state, rendered_detail = _wizard_row7(page)
    if "student" in rendered_detail.lower():
        problems.append(f"{where}: the grading row's detail counts students — progress is "
                        "counted in grading points, never in students (RS-05)")

    # --- the monitor's Progress panel --------------------------------------------------------------
    _goto(page, served.origin, "/monitor")
    expected_counts = {"done": counts["done"], "in flight": counts["in_flight"],
                       "pending": counts["pending"], "quarantined": counts["quarantined"]}

    def _monitor_ok() -> bool:
        return _monitor_counts(page) == expected_counts

    if not _poll(page, _monitor_ok):
        problems.append(
            f"{where}: the monitor's Progress panel is not the store's counts — rendered "
            f"{_monitor_counts(page)!r}, expected {expected_counts!r}")
    monitor_line = _monitor_progress(page)
    if "student" in monitor_line.lower():
        problems.append(f"{where}: the monitor's progress line counts students — progress is "
                        "counted in grading points, never in students (RS-05)")

    # --- the jobs table's run row ------------------------------------------------------------------
    _goto(page, served.origin, "/jobs")
    jobs = json.loads(_fetch(served.origin, "/api/v1/jobs"))
    run_jobs = [job for job in jobs["jobs"] if job["kind"] == "run"
                and str(job["job_id"]) == RUN_ID]
    assert run_jobs, f"{where}: the jobs read carries no record for the run: {jobs!r}"
    progress = run_jobs[0]["progress"]
    # The read's own figures are the store's: a drift here is localized to the read.
    if (progress["total"] is None or int(progress["done"] or 0) != counts["done"]
            or int(progress["total"]) != counts["total"]):
        problems.append(
            f"{where}: the jobs read's progress {progress!r} is not the store's — the ledger "
            f"holds {counts['done']} done of {counts['total']} grading points")
    expected_cell = (
        f"{int(progress['done'] or 0)} of {int(progress['total'])}"
        if progress["done"] is not None and progress["total"] is not None
        else (progress["current"] or "—"))

    def _jobs_ok() -> bool:
        _badge, cell = _jobs_row(served, page)
        return cell == expected_cell

    if not _poll(page, _jobs_ok):
        _badge, cell = _jobs_row(served, page)
        problems.append(
            f"{where}: the jobs row's Progress cell renders {cell!r}, expected "
            f"{expected_cell!r} — the read's own counts")
    badge, cell = _jobs_row(served, page)
    if badge != expected_badge:
        problems.append(
            f"{where}: the jobs row's state badge renders {badge!r}, expected "
            f"{expected_badge!r} — the run row's own state, mirrored")
    if "student" in cell.lower():
        problems.append(f"{where}: the jobs row's progress cell counts students — progress is "
                        "counted in grading points, never in students (RS-05)")

    problems += _health(page, log, where)
    problems += _egress_problems(log, where)
    actions = _action_urls(log)
    if actions:
        problems.append(f"{where}: the journey only reads, but mutation requests were issued: "
                        f"{actions}")


def _body(page: Any) -> str:
    return page.locator("body").inner_text()


# --- the case ------------------------------------------------------------------------------------------


def test_tc_req_139_progress_rendering_matches_the_store_at_every_stage(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-REQ-139` — the seeded run replayed through its four stages: every rendered count
    is the store's, and no percentage or student-count progress appears anywhere."""
    _require_bundle()

    with _console(tmp_data_dir, network_guard, monkeypatch) as served:
        with spa.spa_page(served.origin) as (page, log):
            problems: list[str] = []
            for stage in ("papers", "grading", "reviewing", "exporting"):
                _advance(served, stage)
                _snapshot(served, page, log, stage, problems)
                # The percentage ban over every screen the snapshot visited — the whole
                # rendered text, RS-05's journey-level sweep. The wizard home is visited
                # with the journey's selection (`_HOME`): the screen the snapshot bound to
                # the store is the screen the ban sweeps, not the unselected one.
                for route in (_HOME, "/monitor", "/jobs"):
                    _goto(page, served.origin, route)
                    hit = _PERCENTAGE.search(_body(page))
                    if hit:
                        problems.append(
                            f"stage {stage}: {route} renders a percentage ({hit.group(0)!r}) — "
                            "progress is the server's own counts, never a fraction")
                problems += _health(page, log, "stage " + stage)
            assert not problems, "\n\n".join(problems)
