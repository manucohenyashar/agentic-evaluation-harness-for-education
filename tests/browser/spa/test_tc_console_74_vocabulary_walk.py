r"""TC-CONSOLE-74 — the exhaustive vocabulary walk: every teacher screen, scanned (E6).

Test plan §3.6 (M-CONSOLE-SCAN, rung Browser): *"Visit **every** teacher screen (16 SPA
routes + the teacher-reachable server-rendered screens) and scan rendered text for:
TOML/JSON/YAML syntax tokens, store path fragments, `pkg-`/`ref-sub-`/`CRIT-`/`Q\\d` raw id
patterns, HTTP status codes, module names (`M-`-prefixed), config key names. Oracle: the
forbidden-term list maintained as a test constant mirroring §3.3.3's left column. Expected:
zero hits. This is the R0 oracle."*

This is the census, not a sample — the RS-08 failure mode is the teacher meeting jargon
exactly once, on the one screen a sample missed. The walk covers the shipped truth: twenty
SPA routes (the plan's sixteen plus the authoring, secondary and status screens the later
stories added) and the eleven server-rendered screens the design delta's route table names.
`CT-CONSOLE-31` is the clause; the scan families are its text-scannable operationalization,
living in `tests/support/redesign_vocabulary.py` beside the term list that TC-REQ-138 pins
to the design delta.

**The world.** Two seeded worlds over one console — a graded, finalized, *published* run and
a mid-run with one paper parked — so the walk meets every screen in a state that gives it
something to render: results, the review screens, the export gate, the parked page, the jobs
table with a running row. The ids the *test controls* are spelled clean (`cls-r-…`,
`run-r-…`, `stu-r-…`) so a seeded id can never trip the raw-id family for the seed's own
spelling; the one id left to the pipeline is the published version id, adjudicated per-hit
below with the reason written next to it.

**Adjudication (out-of-scope, documented per value).** A hit is out of scope only when its
matched string is exactly one of the values below, each with its reason written next to it
in `_adjudicated` — and each scope-narrower than the family it sits in:

- **the published version id** — the address the export gate is routed *by* (§3.3.2's
  `/packages/{version}/export-gate`) and the package screens name; identification, not
  vocabulary. Scoped inside the walk: it may render only on the screens that address or
  name it (`/packages` screens).
- **the shipped placeholder sentinels** (`rv.SHIPPED_SENTINELS`) — what a server screen
  shows when the address names no entity ("Package pkg-unaddressed" for a bare
  `/packages`), documented verbatim in the help manual's page map; a sentinel names
  nothing, so it is not an identifier of anything.
- **the seeded question ids** (`Q1`… from `MCQ_CRITERIA`) — the design renders the
  package's *stored question id* as a grading point's teacher label
  (`_grading_point_labels`, whose own docstring cites `CT-CONSOLE-31` as the reason an
  internal criterion id is never the only name shown); a question id is teacher-authored
  package content echoed back. Scoped inside the walk: only the screens that render
  grading points (`/results` screens) — a `Q\d` anywhere else is the leak RS-08 describes.

Everything else on any screen fails the case — a `pkg-`-spelled id other than the
sentinel, a `Q\d` other than the seeded questions on a screen that shows no grading
points, any syntax token: one screen carrying jargon is exactly the defect this census
exists to catch.

**Oracles on every step** (the E6 floor): no uncaught page error, no unhandled rejection, no
raw error text, no egress (`log.foreign_requests()` empty), and — the walk is read-only — no
mutation request (`/api/v1/actions/`).

Markers: `browser` (E6) and `integration` (the fast tier excludes it, TS-49's rule).
"""

from __future__ import annotations

import json
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pytest

from aeh.pkg import PackageCatalog
from tests.support import console_redesign_world as crw
from tests.support import redesign_vocabulary as rv
from tests.support import spa
from tests.support.console_world import MCQ_CRITERIA, seed_scored_run
from tests.support.impl import require_path

pytestmark = [pytest.mark.browser, pytest.mark.integration]

#: The console's action surface: a URL carrying this prefix is a mutation request. The walk
#: reads; nothing it visits may post.
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


def _goto(page: Any, origin: str, path: str) -> str:
    """Fragment navigation to a route. The wizard home has no level-1 heading, so it waits on
    the stepper; every other screen waits on its `main` h1 (the loaded-screen rule)."""
    route = path.split("?", 1)[0]
    page.goto(f"{origin}#{path}", wait_until="domcontentloaded")
    if route in ("", "/"):
        page.locator('ol[aria-label="The nine stages"] li.stage').first.wait_for(
            state="visible", timeout=spa.STEP_TIMEOUT_MS)
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
    #: The published version id the pipeline generated — the walk's one adjudicated string.
    version_id: str


@contextmanager
def _console(tmp_data_dir: Path, network_guard: Any, monkeypatch: Any) -> Iterator[Served]:
    """A real console on a real loopback port over a real store, seeded with the walk's two
    worlds (see the module docstring)."""
    from aeh.console import serve_console
    from aeh.store import open_store

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    store = open_store(tmp_data_dir)

    def _rewrite_refs(cohort_id: str, prefix: str) -> None:
        """The seeded `ref-sub-…` student refs spelled clean, so the seed's own id scheme
        cannot trip the raw-id family the scan watches (`WALK_IDS`'s reason)."""
        with store.cohort(cohort_id).transaction() as tx:
            rows = tx.execute(
                "SELECT submission_id FROM submission WHERE cohort_id = :c ORDER BY submission_id",
                c=cohort_id,
            )
            for index, row in enumerate(rows, start=1):
                tx.execute(
                    "UPDATE submission SET student_ref = :sr WHERE submission_id = :s",
                    sr=f"{prefix}-{index:02d}", s=str(row["submission_id"]),
                )

    def _seed(store: Any) -> str:
        # World 1 — graded, finalized, published: results, review screens, export gate.
        finished = seed_scored_run(
            store, cohort_id=rv.WALK_IDS["cohort_id"], run_id=rv.WALK_IDS["run_id"],
            package_id=rv.WALK_IDS["package_id"], submissions=3, finalize=True)
        with store.cohort(finished.cohort_id).transaction() as tx:
            tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=finished.run_id)
        catalog = PackageCatalog(store.package(finished.package_id),
                                 package_id=finished.package_id)
        catalog.publish(finished.package_version_id, approved_by="teacher-1")
        _rewrite_refs(finished.cohort_id, "stu-r-9k3m2p")

        # World 2 — mid-run, one paper parked: the parked page, the jobs table's running row,
        # the monitor's progress.
        mid = seed_scored_run(
            store, cohort_id="cls-r-8k2nvw", run_id="run-r-8k2nvw", package_id="pap-r-8k2nvw",
            submissions=5, enumerate_units=True)
        with store.cohort(mid.cohort_id).transaction() as tx:
            tx.execute("UPDATE work_unit SET status = 'done' WHERE run_id = :r", r=mid.run_id)
            tx.execute(
                "UPDATE work_unit SET status = 'pending' WHERE work_id = "
                "(SELECT MIN(work_id) FROM work_unit WHERE run_id = :r)", r=mid.run_id)
            tx.execute("UPDATE run SET status = 'running' WHERE run_id = :r", r=mid.run_id)
            tx.execute(
                "UPDATE submission SET quarantined = 1, ingest_status = 'unreadable', "
                "v3_identity = '' WHERE submission_id = :s", s=mid.submissions[0])
        _rewrite_refs(mid.cohort_id, "stu-r-8k2nvw")
        return finished.run_id

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
    context = json.loads(_fetch(f"http://{host}:{port}", "/api/v1/context"))
    published = [pkg["published_version"] for pkg in context["packages"]
                 if pkg.get("published_version")]
    assert published, f"the walk's world carries no published version: {context!r}"
    try:
        yield Served(tmp_data_dir, store, server, f"http://{host}:{port}", port,
                     version_id=str(published[0]))
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


def _adjudicated(version_id: str) -> dict[str, tuple[str, str]]:
    """The walk's out-of-scope hits, keyed by the exact matched string, each with the
    reason written next to it and the screen scope the exemption is good on (a substring
    of the walk's `where` label; `""` means any screen). The plan's out-of-scope
    adjudication, made checkable *and* scoped: an exemption holds only where the design
    gives it a reason — the same matched string on a screen outside its entry's scope is
    in scope after all, and fails like any hit. Each entry exempts one string and no
    other, so a second, different id slipping onto a screen (a real `pkg-` id, an
    unseeding spelling) fails like any hit."""
    return {
        version_id: (
            "the published version id the pipeline generated — the export gate is routed "
            "by version (§3.3.2) and the package screens name it; identification, not "
            "vocabulary",
            "/packages",
        ),
        **{
            sentinel: (
                "the shipped placeholder sentinel — a screen's 'nothing is named' card, "
                "documented in the help manual's page map; it names nothing, so it is not "
                "an id of anything",
                "",
            )
            for sentinel in rv.SHIPPED_SENTINELS
        },
        **{
            question_id: (
                "the package's own authored question id — the design renders the stored "
                "question_id as the grading point's teacher label (_grading_point_labels, "
                "citing CT-CONSOLE-31); the teacher's own words echoed back",
                "/results",
            )
            for _criterion_id, question_id, _key in MCQ_CRITERIA
        },
    }


# --- the walk -----------------------------------------------------------------------------------------


def test_tc_console_74_every_teacher_screen_scans_clean_against_the_forbidden_terms(
        tmp_data_dir, network_guard, monkeypatch):
    """`TC-CONSOLE-74` — every teacher screen's rendered text carries none of the six
    forbidden-term families, save the one documented adjudication."""
    _require_bundle()

    with _console(tmp_data_dir, network_guard, monkeypatch) as served:
        values = {
            "run_id": rv.WALK_IDS["run_id"],
            "submission_id": f"sub-{rv.WALK_IDS['cohort_id']}-01",
            "student_ref": rv.WALK_IDS["student_ref"],
            "package_version": served.version_id,
        }
        spa_routes = rv.fill_screens(rv.SPA_WALK_ROUTES, values)
        server_routes = rv.fill_screens(rv.SERVER_WALK_SCREENS, values)
        # The enumeration mechanism, asserted rather than assumed: every template filled —
        # a route silently left carrying its placeholder would render a not-found screen,
        # which scans clean and proves nothing.
        assert len(spa_routes) == len(rv.SPA_WALK_ROUTES) == 20, (
            f"the SPA walk enumerates {len(spa_routes)} of {len(rv.SPA_WALK_ROUTES)} routes — "
            "a placeholder went unfilled, and the census cannot skip a screen silently")
        assert len(server_routes) == len(rv.SERVER_WALK_SCREENS) == 11, (
            f"the server walk enumerates {len(server_routes)} of {len(rv.SERVER_WALK_SCREENS)} "
            "screens — a placeholder went unfilled")

        hits: list[tuple[str, rv.ScanHit]] = []
        adjudicated: list[tuple[str, rv.ScanHit, str]] = []
        reasons = _adjudicated(served.version_id)
        problems: list[str] = []

        with spa.spa_page(served.origin) as (page, log):
            for route in spa_routes:
                where = f"SPA {route}"
                try:
                    _goto(page, served.origin, route)
                    text = page.locator("body").inner_text()
                except Exception as error:  # a screen that will not render is the finding
                    problems.append(f"{where}: would not render ({error})")
                    continue
                if not text.strip():
                    problems.append(f"{where}: rendered no text at all — the scan would be "
                                    "vacuous over it")
                    continue
                for hit in rv.scan_text(text):
                    entry = reasons.get(hit.matched)
                    if entry is not None and (not entry[1] or entry[1] in where):
                        adjudicated.append((where, hit, entry[0]))
                    else:
                        hits.append((where, hit))
                problems += _health(page, log, where)
            problems += _egress_problems(log, "the SPA walk")
            walked_actions = _action_urls(log)
            if walked_actions:
                problems.append(f"the walk is read-only, but mutation requests were issued: "
                                f"{walked_actions}")

        for route in server_routes:
            where = f"server {route}"
            try:
                html = _fetch(served.origin, route)
            except Exception as error:  # a screen that will not serve is the finding
                problems.append(f"{where}: would not serve ({error})")
                continue
            text = rv.server_screen_text(html)
            if not text.strip():
                problems.append(f"{where}: rendered no text at all — the scan would be "
                                "vacuous over it")
                continue
            for hit in rv.scan_text(text):
                entry = reasons.get(hit.matched)
                if entry is not None and (not entry[1] or entry[1] in where):
                    adjudicated.append((where, hit, entry[0]))
                else:
                    hits.append((where, hit))

        if hits:
            inventory = "\n".join(
                f"  {where}: [{hit.family}] {hit.matched!r} near …{hit.context}…"
                for where, hit in hits)
            problems.append(
                f"the forbidden-term census found {len(hits)} in-scope hit(s):\n{inventory}")
        # Each exemption's scope is enforced at classification time (see the loops above):
        # a documented string on a screen outside its scope lands in `hits`, not here.
        # And the adjudication must be exercised: an exemption that saw no hit is either a
        # stale reason or a world that no longer renders what the design ships — both make
        # the documented list a lie about what the census actually saw.
        if not adjudicated:
            problems.append(
                "the adjudication saw no hits at all — the walk's world no longer renders "
                "any of the documented strings (the published version id, the placeholder "
                "sentinels, the seeded question ids); the exemption list is dead weight and "
                "either the world or the list is stale")
        else:
            seen = "\n".join(
                f"  {where}: {hit.matched!r} — {reason}"
                for where, hit, reason in adjudicated)
            print(f"[tc-console-74] adjudicated {len(adjudicated)} out-of-scope hit(s):\n{seen}")
        _fail_with(problems)
