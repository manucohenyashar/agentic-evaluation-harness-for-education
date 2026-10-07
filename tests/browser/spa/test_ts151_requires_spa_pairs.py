"""`TS-151` (#640) — the design delta's new `Requires` rows that cross the SPA, one pairwise
case each, at rung 3 (E6) per operator test plan §6.13:

| Case | Pair | Assertion |
|---|---|---|
| `TC-REQ-128` | M-UI → M-CONSOLE | a scripted E6 session performs publish and run start; the API calls observed are exactly the enumerated controls; the rows written equal the CLI path's row-for-row |
| `TC-REQ-129` | M-UI → M-HELP | the Q&A panel's traffic is only `ask()`; no other M-HELP endpoint is called from the SPA in the recorded session |

The rung-2 halves of this story (`TC-REQ-130`..`133`) are
`tests/contract/requires/test_ts151_requires_delta.py`. The rig is the TS-49/TS-148 family:
`serve_console` for real on the loopback bind, a Chromium-family browser through Playwright
(`spa_page`), the network guard loosened for loopback only. The run-start differential is
TS-148's (`tests/integration/console/test_ts148_console_coverage.py`), one rung up: the console
side drives the SPA's confirmations, not raw JSON.

**Written ahead of implementation: yes.** Both cases are red until their paired stories land;
they fail in milliseconds on the missing bundle (`NotImplementedYet` naming #634) — never a
navigation timeout that reads like a broken server — and their `writtenahead` marker is keyed
in `WRITTEN_AHEAD_BLOCKERS` on the conjunction of #632's parity inventory, #634's committed
bundle, #636's assistant and #638's answers-only affordance. #631's run-start routes and the
publish control's route ship no keyed name in any open story, so when the key fires, re-check
both cases green before unmarking; never unmark on the notice alone.

Isolation: real store, real modules, no network (`network_guard`); the Q&A session's model
boundary is the recorded QA double behind `RecordedFixtureProvider` — the only egress point
(CT-PROV-15).
"""

from __future__ import annotations

import re
import shutil
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.store import open_store
from tests.support import spa
from tests.support.console_api_vocabulary import (
    PROFILE_PARAM,
    ROUTE_TABLE,
    RUN_START_PREVIEW_READ,
    START_RUN_CONTROL,
    matches_template,
    route_rows,
    row_differences,
    tier_rows,
)
from tests.support.impl import CONSOLE_MODULE, NotImplementedYet, require, require_path

pytestmark = [pytest.mark.browser, pytest.mark.integration]

#: Invented DOM contract for the two SPA actions this story drives (FR-UI-05: every confirmation
#: names what it does, and the confirming button is the one naming the action — never a header
#: close/x). Declared here, once; #635 aligns the bundle or these patterns move with a one-line
#: edit — rename there, not here.
PUBLISH_ACTION = re.compile(r"publish", re.I)
RUN_START_ACTION = re.compile(r"start (the |a )?run", re.I)
_CANCEL = re.compile(r"cancel", re.I)

#: The publish control's API label — **invented**: no route in #629's table publishes the setup
#: flow's package version yet, and no open story names the label. #632's census owns the
#: enumerated-controls inventory; when it lands, re-point this constant or the case.
PUBLISH_CONTROL = "publish package version"
PUBLISH_ISSUE = "#632"

PROFILE = "cloud-hosted"
JEV_BUILD = "openrouter/typesafe/jev-1.13@20260917"
PANEL_BUILDS = (
    "openrouter/qwen/qwen3-30b-a3b@2026-06-01",
    "openrouter/meta-llama/llama-3.3-70b-instruct@2026-06-01",
    "openrouter/mistralai/mistral-small-3.2-24b-instruct@2026-06-01",
)
#: The operator's config file: profile sections only, no top-level `HARNESS_PROFILE` — the
#: console process runs unprofiled and the run names its profile per request (TS-148's reading).
CONFIG_TOML = (
    'prompt_template_v = "judge-prompt/2"\n'
    "[profiles.cloud-hosted]\n"
    "HARNESS_COST_CEILING = 50\n"
    'HARNESS_COST_CURRENCY = "USD"\n'
    'retention_setting = "zero-retention"\n'
    'HARNESS_DECISION_ENGINE = "jev"\n'
    'HARNESS_DECISION_PROVIDER = "openrouter-jev"\n'
    f'HARNESS_JEV_BUILD = "{JEV_BUILD}"\n'
    "[profiles.cloud-hosted.transcriber]\n"
    'role = "transcriber"\nprovider = "openrouter"\n'
    'build_id = "openrouter/qwen/qwen3-vl-8b-instruct@2026-06-01"\n'
    + "".join(f'[[profiles.cloud-hosted.panel]]\nrole = "judge"\nprovider = "openrouter"\n'
              f'build_id = "{build}"\n' for build in PANEL_BUILDS)
)
CRITERIA = (
    {"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C02", "kind": "open", "scoring_model": "holistic"},
)


class _ConfirmingDecisionProvider:
    """The Jev decision provider at the boundary: confirms zero retention without a network
    call and prices a decision call at a fixed figure — TS-148's double, the same instance
    kind on both paths."""

    def verify_retention(self, refs):
        from aeh.prov import RetentionReport

        return RetentionReport(confirmed=tuple(refs), unconfirmed=())

    def estimate_cost(self, plan):
        from aeh.prov import CostEstimate

        return CostEstimate(calls=plan.calls, tokens_in=0, tokens_out=0,
                            cost=Decimal("0.0004") * plan.calls)


def _close(store) -> None:
    """Close the store, tolerating a tier handle the console's request thread opened."""
    import sqlite3

    try:
        store.close()
    except sqlite3.ProgrammingError:
        pass


def _require_bundle() -> None:
    require_path(spa.BUNDLE_INDEX, "the committed SPA bundle (FR-UI-01)", issue="#634")


def _route(routes, issue: str, *, control: str | None = None, read: str | None = None):
    from tests.support.console_api_vocabulary import route_for

    found = route_for(routes, control=control, read=read)
    if found is None:
        label = control if control is not None else read
        raise NotImplementedYet(
            f"API_ROUTES has no route for {label!r} yet (blocked on {issue}); the name is "
            "invented beside this case.")
    return found


# --- the twin world: one confirmed setup flow, seeded twice ------------------------------------


def _seed_flow(data_dir: Path):
    """The confirmed setup flow over one real store: store, document ingested, the proposed
    inventory confirmed, every answer key keyed — the publishable draft (`TC-UI-05`'s
    setup-ready world), beside a synthetic cohort and its papers loaded. The support seeds are
    deterministic, so seeding this twice yields two identical stores; minted ids are masked in
    the differential (`tier_rows`'s `<minted>` rule), never assumed equal."""
    from tests.support.orch_run import seed_cohort
    from tests.support.setup_harness import ingest_document, stage_chain
    chain = stage_chain(data_dir)
    try:
        assessment = ingest_document(chain.store)
        proposal = chain.service.propose_inventory(assessment)
        chain.service.confirm_inventory(proposal.proposal_id)
        chain.service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"], "CRIT-Q6": ["A"]})
        seed_cohort(chain.store, ("S001", "S002", "S003"))
        return chain
    finally:
        _close(chain.store)


def _flow_world(tmp_path: Path) -> dict[str, Any]:
    """One confirmed flow seeded twice and copied, so the console's store and the CLI's twin
    start identical (TS-148's `_run_world`, with the setup draft in it)."""
    from tests.support.orch_run import ORCH_COHORT_ID

    base = tmp_path / "base"
    chain = _seed_flow(base)
    console_dir, cli_dir = tmp_path / "console", tmp_path / "cli"
    shutil.copytree(base, console_dir)
    shutil.copytree(base, cli_dir)
    config = tmp_path / "harness.toml"
    config.write_text(CONFIG_TOML, encoding="utf-8")
    return {"cohort": ORCH_COHORT_ID, "version": chain.version, "console": console_dir,
            "cli": cli_dir, "config": config}


def _start_seams(monkeypatch) -> None:
    """Both paths: the decision provider double at both import sites, and the drive stubbed
    (TC-PIPE-26's precedent) so the comparison is the start's rows, not drive progress —
    TS-148's seams, unchanged."""
    from aeh.pipeline import background, cli
    from aeh.pipeline.results import RunResult

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-ts151-dummy")
    monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "0")
    double = _ConfirmingDecisionProvider()
    for module in (cli, background):
        monkeypatch.setattr(module, "_decision_provider_for_run",
                            lambda run_config, provider, given: double)

    def _no_drive(store, run_id, **_kw):
        return RunResult(run_id=run_id, status="complete", pause_reason=None, stages=(),
                         grades_computed=0, grades_final=0)

    monkeypatch.setattr(cli, "run_to_completion", _no_drive)
    monkeypatch.setattr(background, "run_to_completion", _no_drive)


def _the_run(data_dir: Path) -> dict[str, Any]:
    """The single run row in every tier file under `data_dir`, read-only (TS-148's oracle)."""
    import sqlite3

    rows = []
    for db in Path(data_dir).rglob("*.sqlite"):
        connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'run'").fetchone():
                rows += [dict(r) for r in connection.execute("SELECT * FROM run")]
        finally:
            connection.close()
    assert len(rows) == 1, f"expected exactly one run row, found {len(rows)}"
    return rows[0]


def _published_version(data_dir: Path) -> Any:
    """The store's published package version (`package_version.locked = 1`, read-only) —
    what the SPA's publish confirmation must have landed."""
    import sqlite3

    versions: list[str] = []
    for db in Path(data_dir).rglob("*.sqlite"):
        connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            if connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = 'package_version'").fetchone():
                versions += [r[0] for r in connection.execute(
                    "SELECT package_version_id FROM package_version WHERE locked = 1")]
        finally:
            connection.close()
    assert len(versions) == 1, (
        f"expected exactly one published package version, found {versions}")
    return versions[0]


def _observed_api_calls(page, log: spa.SpaLog) -> list[tuple[str, str]]:
    """(method, path) for every `/api/` request the page issued since it was attached —
    the pair-level census's operand. `SpaLog.requests` holds URLs only; Playwright's request
    object carries the method, so this listener is attached by the test, not the rig."""
    calls: list[tuple[str, str]] = []

    def _on_request(request: Any) -> None:
        url = request.url
        if "/api/" in url and url.startswith(log.origin):
            calls.append((request.method, url[len(log.origin):].split("?")[0]))

    page.on("request", _on_request)
    return calls



def _confirm(page, action: re.Pattern[str], what: str, problems: list[str]) -> bool:
    """Click the first enabled button named for `action` on the current screen, confirm the
    dialog with the button naming the action (never a cancel/close), and report problems."""
    buttons = page.locator("main").get_by_role("button", name=action)
    enabled = [buttons.nth(i) for i in range(buttons.count()) if buttons.nth(i).is_enabled()]
    if not enabled:
        problems.append(f"{what}: no enabled {action.pattern!r} action on its screen")
        return False
    enabled[0].click()
    dialog = page.get_by_role("dialog")
    try:
        dialog.first.wait_for(state="visible")
    except Exception:
        problems.append(f"{what}: {action.pattern!r} opened no confirmation dialog")
        return False
    named = dialog.first.get_by_role("button", name=action)
    confirm = [named.nth(i) for i in range(named.count()) if not _CANCEL.search(
        named.nth(i).inner_text())]
    if not confirm:
        problems.append(f"{what}: the confirmation has no button naming the action")
        return False
    confirm[0].click()
    return True


def _wait_for_write(page, before: dict[str, Any], data_dir: Path, what: str,
                    problems: list[str]) -> None:
    """Wait (bounded, the E6 knob) until the store changed after a confirmation."""
    deadline = time.monotonic() + spa.STEP_TIMEOUT_MS / 1000
    while spa.store_digest(data_dir) == before and time.monotonic() < deadline:
        page.wait_for_timeout(100)
    if spa.store_digest(data_dir) == before:
        problems.append(f"{what}: confirming wrote nothing — the row did not land")


def _api_census_problems(observed: list[tuple[str, str]]) -> list[str]:
    """CT-CONSOLE-30 at the pair level: every `/api/` request the session made names an
    enumerated route of the route table, and every mutating one is an enumerated control row
    (never an orphan, never a read)."""
    _serve, routes = require(CONSOLE_MODULE, "serve_console", ROUTE_TABLE, issue="#629")
    templates = route_rows(routes)
    problems: list[str] = []
    for method, path in observed:
        hit = next(((m, c, t) for m, c, t in templates
                    if m.upper() == method.upper() and matches_template(t, path)), None)
        if hit is None:
            problems.append(f"the SPA called an API path no route enumerates: {method} {path}")
            continue
        _m, control, _t = hit
        if method.upper() in ("POST", "PUT", "PATCH", "DELETE") and control is None:
            problems.append(
                f"the SPA issued a mutating call whose route carries no enumerated "
                f"control: {method} {path}")
    return problems


# --- TC-REQ-128 --------------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_req_128_the_spa_session_performs_publish_and_run_start_like_the_cli(
        tmp_path, network_guard, monkeypatch, capsys):
    """`TC-REQ-128` / M-UI→M-CONSOLE (P0) — a scripted E6 session performs publish and run
    start on a setup-ready world; every `/api/` call the session made is an enumerated route
    and every mutation is an enumerated control (CT-CONSOLE-30 at the pair level); and the
    run-start confirmation's rows equal the CLI path's row-for-row (FR-CONSOLE-43's own claim:
    "the same run-start rows the CLI writes; there is no second start path"), masked minted
    ids. TS-148's TC-CONSOLE-56 differential, one rung up.

    *Reading, disclosed in the PR:* the design's row-for-row claim is the run-start leg's —
    no `aeh` subcommand publishes (R-12 makes the console the publish path), so the publish
    leg is pinned by the census (an enumerated control wrote it) and by the published version
    landing. When #632's census names publish's console path, the publish leg can join the
    differential."""
    _require_bundle()
    # Red-by-design guards BEFORE the fixture work: the session needs the lifecycle screens'
    # recovery wording (#635, FR-UI-07) and the answers-only affordance (#638, FR-UI-06) —
    # the same two bundle probes the TS-152 journey's registry command uses. Without these,
    # the case would crash deep in the twin world instead of refusing at its door.
    for phrase, issue in (("check that the console service is running", "#635"),
                          ("does not operate the system", "#638")):
        if not spa.text_in_bundle(spa.BUNDLE_INDEX.parent, phrase):
            raise NotImplementedYet(
                f"the SPA bundle does not carry {phrase!r} yet (blocked on {issue}); "
                "the wording is that story's to ship.")

    serve, routes = require(CONSOLE_MODULE, "serve_console", ROUTE_TABLE, issue="#629")

    store = open_store(world["console"])
    problems: list[str] = []
    observed: list[tuple[str, str]] = []
    try:
        server = serve(store=store)
        with on_loopback(server, network_guard) as (port, _census):
            origin = f"http://localhost:{port}"
            with spa.spa_page(origin) as (page, log):
                observed = _observed_api_calls(page, log)
                spa.open_hub(page, origin)
                spa.go_to(page, origin, "package")
                before = spa.store_digest(world["console"])
                if _confirm(page, PUBLISH_ACTION, "package: publish", problems):
                    _wait_for_write(page, before, world["console"], "package: publish",
                                    problems)
                spa.go_to(page, origin, "run_start")
                before_start = spa.store_digest(world["console"])
                if _confirm(page, RUN_START_ACTION, "run start", problems):
                    _wait_for_write(page, before_start, world["console"], "run start",
                                    problems)
                for thread in list(getattr(server.app, "_run_threads", {}).values()):
                    thread.join(timeout=30)
                problems += [f"uncaught page error {e!r}" for e in log.page_errors]
                problems += [f"a request left the console's origin: {u}"
                             for u in log.foreign_requests()]
    finally:
        _close(store)
    network_guard.assert_no_network()

    published = _published_version(world["console"])
    run = _the_run(world["console"])
    assert run["package_version_id"] == published, (
        f"TC-REQ-128: the run the session started names {run['package_version_id']!r}, not "
        "the version the session published — the SPA started a run on a second path")
    problems += _api_census_problems(observed)
    _fail_with(problems)

    # The CLI twin: the same flow, published by the same setup surface, then `aeh run` on the
    # published version — the rows the confirmation must equal.
    from aeh.pipeline import cli as cli_module

    twin = stage_chain(world["cli"])
    try:
        twin_version = twin.service.publish(_TEACHER)
    finally:
        _close(twin.store)
    code, out, err = _cli(tmp_path, world, twin_version, capsys)
    assert code == 0, f"TC-REQ-128: the CLI twin did not start its run: {out + err}"

    console_run, cli_run = _the_run(world["console"]), _the_run(world["cli"])
    differences = row_differences(
        tier_rows(world["console"], mask={console_run["run_id"]: "<run>",
                                          published: "<version>"}),
        tier_rows(world["cli"], mask={cli_run["run_id"]: "<run>",
                                      twin_version: "<version>"}))
    assert not differences, (
        "TC-REQ-128: the SPA session did not write exactly the CLI path's rows (row for row; "
        "minted ids masked):\n  " + "\n  ".join(differences))


def _fail_with(problems: list[str]) -> None:
    assert not problems, "\n\n".join(problems)

