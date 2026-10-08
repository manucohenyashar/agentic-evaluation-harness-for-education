"""`TS-151` (#640) — the design delta's new `Requires` rows that cross the SPA, one pairwise
case each, at rung 3 (E6) per operator test plan §6.13:

| Case | Pair | Assertion |
|---|---|---|
| `TC-REQ-128` | M-UI → M-CONSOLE | a scripted E6 session performs the run start on the SPA's run-start screen; the API calls observed are exactly the enumerated routes (the one mutation the enumerated "start run" control); the rows written equal the CLI path's row-for-row |
| `TC-REQ-129` | M-UI → M-HELP | the Q&A panel's traffic is only `ask()`; no other M-HELP endpoint is called from the SPA in the recorded session — its case lives beside the panel's: `tests/browser/spa/test_spa_qa_panel.py` |

The rung-2 halves of this story (`TC-REQ-130`..`133`) are
`tests/contract/requires/test_ts151_requires_delta.py`. The rig is the TS-49/TS-148 family:
`serve_console` for real on the loopback bind, a Chromium-family browser through Playwright
(`spa_page`), the network guard stood down under the `browser` marker (TS-49's rule) — the
no-egress oracle is the browser's own request log (`SpaLog.foreign_requests`). The run-start
differential is TS-148's (`tests/integration/console/test_ts148_console_coverage.py`),
one rung up: the console side drives the SPA's confirmations, not raw JSON.

**The run-start premise, reworked** (disclosed on the PR). The plan row's "publish and run
start" paired the two controls over one setup-ready world — but the SPA's run-start screen is
resume-only by design (FR-UI-03d names FR-CONSOLE-43, whose confirmation posts the served
run's id — the FR-CONF-15 resume; with no served run the screen's button is disabled and it
says there is nothing to start), and the console's publish is the confirmed setup flow's
publish through M-SETUP — a path no `aeh` subcommand performs (`aeh package build` builds
and publishes a spec-built package, a different path), so a publish leg has no CLI twin to
differ against. The case now owns the leg the design actually pins: the confirmation writes
the same run-start rows the CLI writes, `aeh run` continuing the same stored run on a twin
copy of the same world — both drives stubbed (TC-PIPE-26's precedent, via TC-CONSOLE-56's
seams) so the comparison is the start's rows. The publish affordance's own E6 coverage is
TC-UI-05's publish arm over the setup-ready draft (no row-for-row twin there — the publish
leg's twin comparison is dropped with this rework, a plan finding for the row's owner to
amend). The `writtenahead` marker came off and the `WRITTEN_AHEAD_BLOCKERS` entry left with
this rework (#635/#638's wording shipped; the case re-checked green unmarked).

Isolation: real store, real modules, no egress; the run start's model boundary is stubbed at
the drive seam, the same instance kind on both paths (TS-148's double).
"""

from __future__ import annotations

import re
import shutil
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

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
from aeh.console.vocabulary import RUN_START_STATE_READ
from aeh.store import open_store
from tests.support import spa
from tests.support.console_api_vocabulary import (
    MUTATING_METHODS,
    ROUTE_TABLE,
    RUN_START_ISSUE,
    RUN_START_PREVIEW_READ,
    START_RUN_CONTROL,
    matches_template,
    row_differences,
    route_rows,
    tier_rows,
)
from tests.support.impl import CONSOLE_MODULE, NotImplementedYet, require, require_path

pytestmark = [pytest.mark.browser, pytest.mark.integration]

#: The DOM contract for the SPA action this story drives (FR-UI-05): the screen's action button
#: names what it does ("Start the run"), and the confirming button inside the dialog is the one
#: naming the action — never the dialog's Cancel. Declared here, once; the bundle renames there,
#: not here.
RUN_START_ACTION = re.compile(r"start (the |a )?run", re.I)
RUN_START_CONFIRM = re.compile(r"^start\b", re.I)
_CANCEL = re.compile(r"cancel", re.I)

#: The twin's config file: the `edge-local` section `aeh run` re-resolves the stored run's
#: continuation against. The seeded world's run froze `edge_cfg`'s values (tests/support/
#: conf_builders.py), and `aeh run` refuses a continuation whose resolved backend profile
#: differs from the run's (FR-CONF-15's posture, cli.py) — so the twin re-resolves the same
#: profile, panel and transcriber the run froze. Profile sections only, no top-level
#: `HARNESS_PROFILE`: the CLI call names it in the environment (FR-CONF-14).
TWIN_PROFILE = "edge-local"
TWIN_CONFIG_TOML = (
    'prompt_template_v = "conf-v1.0.0"\n'
    "[profiles.edge-local]\n"
    'HARNESS_HARDWARE_PROFILE = "unified-large"\n'
    'HARNESS_DECISION_ENGINE = "off"\n'
    "[[profiles.edge-local.panel]]\n"
    'role = "judge"\nprovider = "ollama"\n'
    'build_id = "/models/llama-3.3-70b.gguf@sha256:aaaa"\nquantization = "q4"\n'
    "[profiles.edge-local.transcriber]\n"
    'role = "transcriber"\nprovider = "ollama"\n'
    'build_id = "/models/whisper-large-v3.gguf@sha256:bbbb"\nquantization = "q4"\n'
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


# --- the twin world: one scored pending run, seeded once, copied twice --------------------------


def _resume_world(tmp_path: Path) -> dict[str, Any]:
    """One scored **pending** run seeded once (console_world's seeding: the shipped M-ORCH,
    M-DET and M-GRADE writers over a real store; `create_run` freezes the resolved
    `edge_cfg` configuration on the run row, which is what the resume restarts under,
    FR-CONF-15) and the closed store copied, so the console's store and the CLI's twin start
    identical — TC-CONSOLE-56's `_run_world` one premise up: a stored run, not a fresh
    cohort-and-package pair."""
    from tests.support.console_world import seed_scored_run

    base = tmp_path / "base"
    store = open_store(base)
    try:
        seeded = seed_scored_run(store, submissions=2)
    finally:
        _close(store)
    console_dir, cli_dir = tmp_path / "console", tmp_path / "cli"
    shutil.copytree(base, console_dir)
    shutil.copytree(base, cli_dir)
    config = tmp_path / "harness.toml"
    config.write_text(TWIN_CONFIG_TOML, encoding="utf-8")
    return {"cohort": seeded.cohort_id, "version": seeded.package_version_id,
            "run_id": seeded.run_id, "console": console_dir, "cli": cli_dir,
            "config": config}


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



def _open_confirmation(page, action: re.Pattern[str], what: str, problems: list[str]):
    """Click the first enabled button named for `action` on the current screen, and return the
    dialog it opened (None, with the problem recorded, when it opened none)."""
    buttons = page.locator("main").get_by_role("button", name=action)
    enabled = [buttons.nth(i) for i in range(buttons.count()) if buttons.nth(i).is_enabled()]
    if not enabled:
        problems.append(f"{what}: no enabled {action.pattern!r} action on its screen")
        return None
    enabled[0].click()
    dialog = page.get_by_role("dialog")
    try:
        dialog.first.wait_for(state="visible")
    except Exception:
        problems.append(f"{what}: {action.pattern!r} opened no confirmation dialog")
        return None
    return dialog.first


def _confirm_dialog(dialog, names: re.Pattern[str], what: str, problems: list[str]) -> bool:
    """Click the dialog's button naming the action (never a cancel/close)."""
    named = dialog.get_by_role("button", name=names)
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
    (never an orphan, never a read). `route_rows` yields `(METHOD, path template, control)`;
    a read route's `control` is None, which is fine for a GET."""
    _serve, routes = require(CONSOLE_MODULE, "serve_console", ROUTE_TABLE, issue="#629")
    templates = route_rows(routes)
    problems: list[str] = []
    for method, path in observed:
        hit = next(((m, t, c) for m, t, c in templates
                    if m.upper() == method.upper() and matches_template(t, path)), None)
        if hit is None:
            problems.append(f"the SPA called an API path no route enumerates: {method} {path}")
            continue
        _m, _t, control = hit
        if method.upper() in MUTATING_METHODS and control is None:
            problems.append(
                f"the SPA issued a mutating call whose route carries no enumerated "
                f"control: {method} {path}")
    return problems


# --- TC-REQ-128 --------------------------------------------------------------------------------


def test_tc_req_128_the_spa_session_starts_the_run_like_the_cli(tmp_path, monkeypatch, capsys):
    """`TC-REQ-128` / M-UI→M-CONSOLE (P0) — a scripted E6 session performs the run start on the
    SPA's run-start screen (FR-UI-03d): the screen reads the run the console serves, its
    confirmation opens on the preview read (FR-CONSOLE-43's banner and estimate — rendering it
    writes nothing), and confirming posts the served run's id: the FR-CONF-15 resume, the run's
    own frozen configuration, nothing composed from today's environment. Every `/api/` call the
    session made is an enumerated route and its one mutation is the enumerated "start run"
    control (CT-CONSOLE-30 at the pair level); and the SPA-started run's rows equal, row for
    row, the rows `aeh run` writes continuing the same stored run on a twin copy of the same
    world (FR-CONSOLE-43: "the same run-start rows the CLI writes; there is no second start
    path") — TC-CONSOLE-56's differential, one rung up, minted ids masked.

    *Premise, reworked (disclosed on the PR):* the first draft paired "publish and run start"
    over a setup-ready world with no run — but the SPA's run-start screen is resume-only by
    design (with no served run its button is disabled and it says there is nothing to start),
    and the console's publish is the confirmed setup flow's publish through M-SETUP, a path
    no `aeh` subcommand performs (`aeh package build` publishes a spec-built package, a
    different path), so a publish leg has no CLI twin to differ against. The publish
    affordance's own E6 coverage is TC-UI-05's publish arm over the setup-ready draft; this
    case owns the leg FR-CONSOLE-43 pins."""
    _require_bundle()
    # The run-start screen's own failure path must still degrade as FR-UI-07 names it (the
    # preview read's refusal wording is #635's): a cheap probe at the door, before the twin
    # world would crash deep in the drive.
    if not spa.text_in_bundle(spa.BUNDLE_INDEX.parent, "check that the console service is "
                                                         "running"):
        raise NotImplementedYet(
            "the SPA bundle does not carry the recovery wording yet (blocked on #635); "
            "the wording is that story's to ship.")
    _start_seams(monkeypatch)
    world = _resume_world(tmp_path)
    serve, routes = require(CONSOLE_MODULE, "serve_console", ROUTE_TABLE, issue="#629")
    state = _route(routes, RUN_START_ISSUE, read=RUN_START_STATE_READ)
    preview = _route(routes, RUN_START_ISSUE, read=RUN_START_PREVIEW_READ)
    start = _route(routes, RUN_START_ISSUE, control=START_RUN_CONTROL)

    store = open_store(world["console"])
    problems: list[str] = []
    observed: list[tuple[str, str]] = []
    try:
        server = serve(store=store, run_id=world["run_id"])
        host, port = server.socket.getsockname()[:2]
        origin = f"http://{host}:{port}"
        with spa.spa_page(origin) as (page, log):
            observed = _observed_api_calls(page, log)
            spa.open_hub(page, origin)
            spa.go_to(page, origin, "run_start")
            text = spa.main_text(page)
            for value in (world["run_id"], world["cohort"], world["version"]):
                if value not in text:
                    problems.append(
                        f"run start: the screen does not show the served run's {value!r} — "
                        "the state read did not render what would start")
            before = spa.store_digest(world["console"])
            dialog = _open_confirmation(page, RUN_START_ACTION, "run start", problems)
            if dialog is not None:
                if spa.store_digest(world["console"]) != before:
                    problems.append(
                        "run start: opening the confirmation (its preview read) wrote "
                        + str(spa.changed_tables(before, spa.store_digest(world["console"]))))
                if _confirm_dialog(dialog, RUN_START_CONFIRM, "run start", problems):
                    _wait_for_write(page, before, world["console"], "run start", problems)
                    outcome = page.locator("main").get_by_role("status")
                    try:
                        outcome.first.wait_for(state="visible", timeout=2_000)
                    except Exception:
                        pass
                    if outcome.count() and outcome.first.inner_text().strip().startswith(
                            "Refused"):
                        problems.append("run start: the confirmation was refused: "
                                        + outcome.first.inner_text().strip())
            for thread in list(getattr(server.app, "_run_threads", {}).values()):
                thread.join(timeout=30)
            problems += [f"uncaught page error {e!r}" for e in log.page_errors]
            problems += [f"a request left the console's origin: {u}"
                         for u in log.foreign_requests()]
    finally:
        # The served fixture's cleanup (test_spa_hub_screens.py): the accept loop and its
        # socket back, before the store's tier handles.
        server.terminate()
        _close(store)

    run = _the_run(world["console"])
    if run["status"] != "running":
        problems.append(
            f"run start: the served run is {run['status']!r}, not 'running' — the "
            "confirmation did not start it")
    if run["package_version_id"] != world["version"]:
        problems.append(
            f"run start: the started run names {run['package_version_id']!r}, not the served "
            f"{world['version']!r} — the SPA started something else")
    for route, what in ((state, "the run-start state read"),
                        (preview, "the run-start preview read"),
                        (start, "the start-run confirmation")):
        if (route.method.upper(), route.path) not in observed:
            problems.append(
                f"run start: the session never made {what} ({route.method} {route.path}); "
                "the pairing is not what was driven")
    problems += _api_census_problems(observed)
    _fail_with(problems)

    # The CLI twin: the same stored run, continued by `aeh run` over the twin copy — the rows
    # the confirmation must equal. Both drives are stubbed (`_start_seams`), so what is
    # compared is what the START wrote, before any dispatch.
    code, out, err = _cli_run(world, monkeypatch, capsys)
    assert code == 0, f"TC-REQ-128: the CLI twin did not continue its run: {out + err}"

    differences = row_differences(
        tier_rows(world["console"], mask={world["run_id"]: "<run>"}),
        tier_rows(world["cli"], mask={world["run_id"]: "<run>"}))
    assert not differences, (
        "TC-REQ-128: the SPA's confirmed start did not write exactly the rows `aeh run` "
        "writes continuing the same stored run (row for row; minted ids masked):\n  "
        + "\n  ".join(differences))


def _cli_run(world: dict[str, Any], monkeypatch, capsys) -> tuple[int, str, str]:
    """`aeh run` continuing the twin's stored run: the CLI names the run's cohort and package
    version (how the command finds a run to continue) and re-resolves the frozen profile from
    the twin's config file — the run resumes on the backend it froze (FR-CONF-15)."""
    from aeh.pipeline import cli

    monkeypatch.setenv("HARNESS_PROFILE", TWIN_PROFILE)
    monkeypatch.setenv("HARNESS_HARDWARE_PROFILE", "unified-large")
    try:
        capsys.readouterr()
        code = cli.main(["run", "--data-dir", str(world["cli"]), "--cohort", world["cohort"],
                         "--package-version", world["version"], "--config",
                         str(world["config"])])
        captured = capsys.readouterr()
    finally:
        monkeypatch.delenv("HARNESS_PROFILE", raising=False)
        monkeypatch.delenv("HARNESS_HARDWARE_PROFILE", raising=False)
    return code, captured.out, captured.err


def _fail_with(problems: list[str]) -> None:
    assert not problems, "\n\n".join(problems)

