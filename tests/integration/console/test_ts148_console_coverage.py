"""`TS-148` (issue #633) — console coverage: the roster editor, run start, results and exports
against the CLI (`TC-CONSOLE-55`, `TC-CONSOLE-56`, `TC-CONSOLE-57`; `FR-CONSOLE-42..44`).
`TC-CONSOLE-54` (the parity census, rung 1) is `tests/unit/console/test_tc_console_54_parity_census.py`.

Operator-requirements test plan §5.6. **Rung 2**: a real `serve_console` on the loopback bind over
a real store, real HTTP through `#629`'s API, the network guard loosened for loopback only; the
CLI side is the real `aeh` entry point (`aeh.pipeline.cli.main`) over a **twin** data directory.
Console-vs-CLI parity is a differential — same rows, same bytes.

| Case | What is asserted |
|---|---|
| 55 (a) | a 10-row names-only editor submission (F-NAMES, collision pair included) creates the cohort with exactly the rows `aeh cohort create` writes for the same names (every tier, row for row, wall-clock columns dropped) |
| 55 (b) | names + IDs: the same differential |
| 55 (c)/(d) | IDs only, and one row with an empty name: refused with FR-INGEST-40's message (names the requirement / the row), **no byte written**; the CLI refuses the same input |
| 55 consent | the consent class comes from the editor's control (`consented`, not the seed default), and matches the CLI's |
| 56 | the run-start preview for a `cloud-hosted` run renders the banner (profile, every panel build, `jev > 0.80`, `QA_ASSISTANT`) and an estimate equal to the orchestrator's (`_run_cost_estimate` over the started run's units); the preview writes **zero** rows; the confirmation (`start run`) writes exactly the rows `aeh run` writes into a twin store |
| 56 control | the CLI twin alone starts a run and the orchestrator's estimate for it is positive — proves the differential above cannot pass on two empty sides (green today) |
| 57 | the console's CSV and every per-student PDF are byte-identical to `aeh results export` for the same run and revision; the per-student and class views equal what `aeh results show` prints, and both equal the grade ledger |

**Written ahead of implementation: yes** — 55 keyed to #630, 56 and 57 to #631. Every name the
design leaves open is invented once in `tests/support/console_api_vocabulary.py` (TS-148
section); each case fails with `NotImplementedYet` naming its issue until the route exists.

**Readings, disclosed in the PR.**

* *A `cloud-hosted` run from the console.* The console refuses to bind, and refuses every
  action, under `HARNESS_PROFILE=cloud-hosted` (CT-CONSOLE-05/20/27, TC-CONF-21). So the console
  process runs unprofiled over the operator's config file, and the run's profile is named per
  request (`profile`). That this needs saying is a plan finding: FR-CONSOLE-41/43 and the
  cloud-hosted default meet CT-CONSOLE-05 here and the design does not reconcile them.
* *Run-start rows.* Both paths' drive (`run_to_completion`) is stubbed — the TC-PIPE-26
  precedent — and the decision provider is a double that confirms zero retention offline, at
  both import sites, identically. What is compared is what the start writes, before any
  dispatch. Minted run ids are masked; nothing else is.
* *Without the confirmation* is observed at rung 2 as: rendering the preview writes nothing.
  The browser-level "no-op until confirmed" is TC-UI-05's (E6).
* *The CLI side of 57.* No `aeh` subcommand exports or prints grades today (finding): the
  cases assume `aeh results show|export` (#631), the school-facing export being
  `export_grade_artifacts` (marks CSV + one PDF per student, FR-GRADE-17). The 54 census then
  covers it automatically.
* *55's editor rows* take first and last name (FR-CONSOLE-42); the CLI file takes `full_name`
  (TS-143's reading). The differential therefore pins `full_name == "first last"`.
* *55 and C30.* Cohort creation is not one of the fifteen enumerated control actions, so the
  roster route will meet `TC-CONSOLE-C30`'s orphan check — #630 must decide how (plan finding).
"""

from __future__ import annotations

import json
import re
import shutil
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
from aeh.store import open_store
from tests.support import f_names as fx
from tests.support.console_api_vocabulary import (
    COVERAGE_KEYS,
    EXPORT_READ,
    GRADE_KEYS,
    PROFILE_PARAM,
    RESULTS_CLASS_READ,
    RESULTS_STUDENT_READ,
    ROSTER_CONTROL,
    ROSTER_ISSUE,
    ROUTE_TABLE,
    RUN_START_ISSUE,
    RUN_START_PREVIEW_READ,
    START_RUN_CONTROL,
    answer_text,
    get_bytes,
    get_json,
    on_loopback,
    post_json,
    refused,
    results_export_argv,
    results_show_argv,
    route_for,
    row_differences,
    tier_rows,
)
from tests.support.impl import CONSOLE_MODULE, NotImplementedYet, require
from tests.support.spa import changed_tables, store_digest

pytestmark = pytest.mark.integration

CONSENT = "consented"  # not the seeds' `synthetic`: the editor's control has to be what set it


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT", "HARNESS_FIXTURE_DIR",
                 "HARNESS_EXPORT_DIR"):
        monkeypatch.delenv(name, raising=False)


def _close(store) -> None:
    """Close the store, tolerating a tier handle the console's request thread opened: SQLite
    refuses to close a connection from another thread (`ProgrammingError`). That is teardown,
    not an oracle — every assertion here reads the files through its own read-only connection."""
    import sqlite3

    try:
        store.close()
    except sqlite3.ProgrammingError:
        pass


def _api(issue: str):
    serve, routes = require(CONSOLE_MODULE, "serve_console", ROUTE_TABLE, issue=issue)
    return serve, list(routes)


def _route(routes, issue: str, *, control: str | None = None, read: str | None = None):
    found = route_for(routes, control=control, read=read)
    if found is None:
        label = control if control is not None else read
        raise NotImplementedYet(
            f"API_ROUTES has no route for {label!r} yet (blocked on {issue}); the name is "
            "invented in tests/support/console_api_vocabulary.py (TS-148).")
    return found


def _cli(argv: list[str], capsys) -> tuple[int, str, str]:
    from aeh.pipeline import cli

    capsys.readouterr()
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _cli_or_blocked(argv: list[str], capsys, issue: str) -> tuple[int, str, str]:
    """The CLI, with a missing subcommand reported as the blocker it is — never as argparse's
    `SystemExit(2)`."""
    from aeh.pipeline.cli import _build_parser
    from tests.support.console_api_vocabulary import cli_leaf_commands

    leaf = " ".join(argv[:2])
    if leaf not in cli_leaf_commands(_build_parser()):
        raise NotImplementedYet(f"`aeh {leaf}` does not exist yet (blocked on {issue}).")
    return _cli(argv, capsys)


# =============================================================================================
# TC-CONSOLE-55 — the roster editor writes the CLI's rows
# =============================================================================================

COHORT = "class-7b"


def _split(full_name: str) -> tuple[str, str]:
    first, _, last = full_name.partition(" ")
    return first, last


def _editor_rows(with_ids: bool) -> list[dict[str, str]]:
    rows = []
    for row in fx.ROWS:
        first, last = _split(row.full_name)
        entry = {"first_name": first, "last_name": last}
        if with_ids:
            entry["student_ref"] = row.student_ref
        rows.append(entry)
    return rows


def _roster_csv(path: Path, with_ids: bool) -> Path:
    if with_ids:
        text = "full_name,student_ref\n" + "".join(
            f"{r.full_name},{r.student_ref}\n" for r in fx.ROWS)
    else:
        text = "full_name\n" + "".join(f"{r.full_name}\n" for r in fx.ROWS)
    path.write_text(text, encoding="utf-8")
    return path


def _editor(tmp_path: Path, network_guard, payload: dict[str, Any]):
    """Submit `payload` to the roster editor's route on a fresh store; returns the status, the
    answer, the data directory and its digest before the request."""
    serve, routes = _api(ROSTER_ISSUE)
    route = _route(routes, ROSTER_ISSUE, control=ROSTER_CONTROL)
    data_dir = tmp_path / "console"
    store = open_store(data_dir)
    try:
        before = store_digest(data_dir)
        server = serve(store=store)
        with on_loopback(server, network_guard) as (port, _census):
            status, answer = post_json(port, route.path, payload)
        after = store_digest(data_dir)
    finally:
        _close(store)
    network_guard.assert_no_network()
    return status, answer, data_dir, before, after


def _assert_cohort_differential(tmp_path, network_guard, capsys, with_ids: bool, arm: str):
    status, answer, console_dir, _before, _after = _editor(
        tmp_path, network_guard,
        {"cohort_id": COHORT, "consent_class": CONSENT, "rows": _editor_rows(with_ids)})
    assert not refused(status, answer), (
        f"TC-CONSOLE-55 {arm}: the editor refused a valid roster: {status} {answer!r}")
    cli_dir = tmp_path / "cli"
    code, _out, err = _cli(["cohort", "create", "--data-dir", str(cli_dir), "--cohort", COHORT,
                            "--consent", CONSENT, "--roster",
                            str(_roster_csv(tmp_path / "roster.csv", with_ids))], capsys)
    assert code == 0, f"TC-CONSOLE-55 {arm}: the CLI refused the same roster: {err}"

    console_rows, cli_rows = tier_rows(console_dir), tier_rows(cli_dir)
    roster_key = next((k for k in cli_rows if k.endswith(":roster")), None)
    assert roster_key and len(cli_rows[roster_key]) == len(fx.ROWS), (
        f"fixture: the CLI wrote {cli_rows.get(roster_key)} — not the ten F-NAMES rows")
    differences = row_differences(console_rows, cli_rows)
    assert not differences, (
        f"TC-CONSOLE-55 {arm}: the editor's cohort is not the cohort `aeh cohort create` "
        "writes for the same input (row for row):\n  " + "\n  ".join(differences))
    cohort_key = roster_key.replace(":roster", ":cohort")
    assert any(f"'consent_class', '{CONSENT}'" in r for r in console_rows.get(cohort_key, [])), (
        f"TC-CONSOLE-55: the consent class is not the editor's {CONSENT!r}: "
        f"{console_rows.get(cohort_key)}")


def test_tc_console_55_a_a_names_only_paste_creates_the_cli_cohort(
        tmp_path, network_guard, capsys):
    _assert_cohort_differential(tmp_path, network_guard, capsys, with_ids=False, arm="(a)")


def test_tc_console_55_b_names_and_ids_create_the_cli_cohort(tmp_path, network_guard, capsys):
    _assert_cohort_differential(tmp_path, network_guard, capsys, with_ids=True, arm="(b)")


@pytest.mark.parametrize("cell, rows, csv_text, console_words, cli_words", [
    # (c): the message names the requirement — a name per student.
    ("c ids-only", [{"student_ref": "S-1"}, {"student_ref": "S-2"}],
     "student_ref\nS-1\nS-2\n", (r"\bnames?\b",), (r"\bnames?\b",)),
    # (d): the message names the requirement AND the offending row: the editor's second row,
    # which is the CLI file's line 3 (the header is line 1).
    ("d empty-name", [{"first_name": "Amara", "last_name": "Okafor", "student_ref": "S-1"},
                      {"first_name": "", "last_name": "", "student_ref": "S-2"}],
     "full_name,student_ref\nAmara Okafor,S-1\n,S-2\n",
     (r"name", r"\b(row|line)\s*2\b"), (r"name", r"\bline\s*3\b")),
])
def test_tc_console_55_c_d_a_roster_without_names_is_refused_and_writes_nothing(
        tmp_path, network_guard, capsys, cell, rows, csv_text, console_words, cli_words):
    status, answer, data_dir, before, after = _editor(
        tmp_path, network_guard, {"cohort_id": COHORT, "consent_class": CONSENT, "rows": rows})
    text = answer_text(answer)
    assert refused(status, answer), (
        f"TC-CONSOLE-55 ({cell}): not refused (a 5xx is a crash, not a refusal): {status} {text}")
    missing = [w for w in console_words if not re.search(w, text, re.I)]
    assert not missing, (
        f"TC-CONSOLE-55 ({cell}): the refusal does not carry FR-INGEST-40's message "
        f"(missing {missing}): {text}")
    assert not changed_tables(before, after), (
        f"TC-CONSOLE-55 ({cell}): a refused roster wrote "
        f"{changed_tables(before, after)} — no partial cohort")
    # The CLI refuses the same input (FR-INGEST-40: the two refuse identically).
    roster = tmp_path / "refused.csv"
    roster.write_text(csv_text, encoding="utf-8")
    code, _out, err = _cli(["cohort", "create", "--data-dir", str(tmp_path / "cli"), "--cohort",
                            COHORT, "--consent", CONSENT, "--roster", str(roster)], capsys)
    assert code != 0 and all(re.search(w, err, re.I) for w in cli_words), (
        f"TC-CONSOLE-55 ({cell}): the CLI did not refuse the same roster the same way: {err}")


# =============================================================================================
# TC-CONSOLE-56 — run start: banner, estimate, and the same start rows as `aeh run`
# =============================================================================================

JEV_BUILD = "openrouter/typesafe/jev-1.13@20260917"
PANEL_BUILDS = (
    "openrouter/qwen/qwen3-30b-a3b@2026-06-01",
    "openrouter/meta-llama/llama-3.3-70b-instruct@2026-06-01",
    "openrouter/mistralai/mistral-small-3.2-24b-instruct@2026-06-01",
)
#: The operator's config file: profile sections only, no top-level `HARNESS_PROFILE` — the
#: console process runs unprofiled and the run names `cloud-hosted` (see the docstring).
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
    call (`FR-PROV-28`'s gate is the shipped code; only the answer is stood in for) and prices
    a decision call at a fixed figure. The same instance kind on both paths."""

    def verify_retention(self, refs):
        from aeh.prov import RetentionReport

        return RetentionReport(confirmed=tuple(refs), unconfirmed=())

    def estimate_cost(self, plan):
        from aeh.prov import CostEstimate

        return CostEstimate(calls=plan.calls, tokens_in=0, tokens_out=0,
                            cost=Decimal("0.0004") * plan.calls)


def _start_seams(monkeypatch) -> None:
    """Both paths: the decision provider double at both import sites, and the drive stubbed
    (TC-PIPE-26's precedent) so the comparison is the start's rows, not drive progress."""
    from aeh.pipeline import background, cli
    from aeh.pipeline.results import RunResult

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-ts148-dummy")
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


def _run_world(tmp_path: Path) -> dict[str, Any]:
    """One seeded store (a synthetic cohort with three submissions and a two-criterion
    package), closed and copied, so the console's store and the CLI's twin start identical."""
    from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package

    base = tmp_path / "base"
    store = open_store(base)
    try:
        seed_cohort(store, ("S001", "S002", "S003"))
        version = seed_package(store, CRITERIA)
    finally:
        _close(store)
    console_dir, cli_dir = tmp_path / "console", tmp_path / "cli"
    shutil.copytree(base, console_dir)
    shutil.copytree(base, cli_dir)
    config = tmp_path / "harness.toml"
    config.write_text(CONFIG_TOML, encoding="utf-8")
    return {"cohort": ORCH_COHORT_ID, "version": version, "console": console_dir,
            "cli": cli_dir, "config": config}


def _cli_start(world, monkeypatch, capsys) -> tuple[int, str]:
    monkeypatch.setenv("HARNESS_PROFILE", "cloud-hosted")
    try:
        code, out, err = _cli(["run", "--data-dir", str(world["cli"]), "--cohort",
                               world["cohort"], "--package-version", world["version"],
                               "--config", str(world["config"])], capsys)
    finally:
        monkeypatch.delenv("HARNESS_PROFILE", raising=False)
    return code, out + err


def _the_run(data_dir: Path) -> dict[str, Any]:
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


def _orchestrator_estimate(world: dict[str, Any], run_id: str, tmp_path: Path) -> Decimal:
    """The orchestrator's estimate for the run the CLI started (FR-ORCH-15's sum of unit
    estimates, `_run_cost_estimate`), over a third copy so the differential is undisturbed.

    Computed after enumerating the run's units, because the start itself records none: `aeh
    run` calls `start()` before any unit exists (enumeration is lazy, at the first lease), so
    `run.cost_estimate` is NULL on every shipped start — a finding reported on #633's PR."""
    from aeh.conf import effective_config, resolve_run_config
    from aeh.orch import Orchestrator
    from aeh.pipeline.runtime import _load_config_file, _provider_for

    copy = tmp_path / "estimate"
    shutil.copytree(world["cli"], copy)
    store = open_store(copy)
    try:
        cfg = effective_config({**_load_config_file(str(world["config"])),
                                "HARNESS_PROFILE": "cloud-hosted"})
        orchestrator = Orchestrator(store)
        run_config = resolve_run_config(dict(cfg), orchestrator.cohort_ref(world["cohort"]))
        orchestrator = Orchestrator(store, provider=_provider_for(run_config),
                                    decision_provider=_ConfirmingDecisionProvider())
        orchestrator.enumerate_units(run_id)
        cohort, _row = orchestrator._find_run(run_id)
        estimate = orchestrator._run_cost_estimate(cohort, run_id)
    finally:
        _close(store)
    assert estimate is not None and estimate > 0, f"fixture: no orchestrator estimate ({estimate})"
    return Decimal(estimate)


def test_tc_console_56_control_the_cli_twin_starts_a_run_and_the_orchestrator_estimates_it(
        tmp_path, monkeypatch, capsys):
    """Green today: the CLI half of the differential starts a `cloud-hosted` run offline, and
    the orchestrator's estimate for it is a positive figure — so neither the differential nor
    the estimate oracle below can pass on two empty sides."""
    _start_seams(monkeypatch)
    world = _run_world(tmp_path)
    code, output = _cli_start(world, monkeypatch, capsys)
    assert code == 0, f"fixture: `aeh run` did not start the twin's run: {output}"
    run = _the_run(world["cli"])
    assert run["backend_profile"] == "cloud-hosted"
    assert run["status"] == "running", run["status"]
    assert _orchestrator_estimate(world, run["run_id"], tmp_path) > 0


def test_tc_console_56_the_run_start_banner_estimate_and_confirmation_match_the_cli(
        tmp_path, monkeypatch, capsys, network_guard):
    from aeh.pipeline.runtime import _load_config_file

    _start_seams(monkeypatch)
    world = _run_world(tmp_path)
    serve, routes = _api(RUN_START_ISSUE)
    preview = _route(routes, RUN_START_ISSUE, read=RUN_START_PREVIEW_READ)
    start = _route(routes, RUN_START_ISSUE, control=START_RUN_CONTROL)
    query = {"cohort_id": world["cohort"], "package_version": world["version"],
             PROFILE_PARAM: "cloud-hosted"}

    store = open_store(world["console"])
    try:
        server = serve(store=store, cfg=_load_config_file(str(world["config"])))
        with on_loopback(server, network_guard) as (port, _census):
            before = store_digest(world["console"])
            status, shown = get_json(port, preview.path, query)
            after_preview = store_digest(world["console"])
            assert status == 200 and isinstance(shown, dict), (
                f"TC-CONSOLE-56: the run-start preview did not render: {status} {shown!r}")
            # Without the confirmation: zero rows.
            assert not changed_tables(before, after_preview), (
                "TC-CONSOLE-56: rendering the run-start screen wrote "
                f"{changed_tables(before, after_preview)} before any confirmation")
            status, outcome = post_json(port, start.path, dict(query))
            assert not refused(status, outcome), (
                f"TC-CONSOLE-56: the confirmation did not start the run: {status} {outcome!r}")
            for thread in list(getattr(server.app, "_run_threads", {}).values()):
                thread.join(timeout=30)
    finally:
        _close(store)
    network_guard.assert_no_network()

    banner = str(shown.get("banner", ""))
    assert "cloud-hosted" in banner, f"TC-CONSOLE-56: the banner names no profile: {banner}"
    missing = [build for build in PANEL_BUILDS if build not in banner]
    assert not missing, f"TC-CONSOLE-56: the banner omits panel builds {missing}: {banner}"
    assert re.search(r"jev\s*>\s*0\.80\b", banner, re.I), (
        f"TC-CONSOLE-56: the banner does not show the decision gate `jev > 0.80`: {banner}")
    assert "QA_ASSISTANT" in banner, f"TC-CONSOLE-56: no QA_ASSISTANT line: {banner}"

    code, output = _cli_start(world, monkeypatch, capsys)
    assert code == 0, f"fixture: `aeh run` did not start the twin's run: {output}"
    console_run, cli_run = _the_run(world["console"]), _the_run(world["cli"])
    expected = _orchestrator_estimate(world, cli_run["run_id"], tmp_path)
    assert shown.get("estimate") is not None and Decimal(str(shown["estimate"])) == expected, (
        f"TC-CONSOLE-56: the estimate shown ({shown.get('estimate')!r}) is not the "
        f"orchestrator's ({expected})")

    differences = row_differences(
        tier_rows(world["console"], mask={console_run["run_id"]: "<run>"}),
        tier_rows(world["cli"], mask={cli_run["run_id"]: "<run>"}))
    assert not differences, (
        "TC-CONSOLE-56: the console's confirmation did not write exactly the rows `aeh run` "
        "writes (row for row; minted run ids masked):\n  " + "\n  ".join(differences))


# =============================================================================================
# TC-CONSOLE-57 — results views and exports equal the CLI's
# =============================================================================================


def _by_submission(records: Any, source: str) -> dict[str, dict[str, Any]]:
    assert isinstance(records, list) and records, f"{source}: no per-student records: {records!r}"
    out = {}
    for record in records:
        missing = [k for k in GRADE_KEYS + COVERAGE_KEYS if k not in record]
        assert not missing, f"{source}: a per-student record lacks {missing}: {record}"
        total = record["total"]
        out[str(record["submission_id"])] = {
            **{k: record[k] for k in GRADE_KEYS + COVERAGE_KEYS},
            "total": None if total is None else round(float(total), 6)}
    return out


def _ledger(store, run_id: str) -> dict[str, dict[str, Any]]:
    cohort = store.cohort("c-ts48")
    rows = cohort.query(
        "SELECT * FROM submission_grade WHERE run_id = :r AND is_current = 1", r=run_id)
    return _by_submission([dict(r) for r in rows], "the grade ledger")


def test_tc_console_57_exports_are_byte_identical_and_views_match_the_cli(
        tmp_data_dir, tmp_path, capsys, network_guard):
    from tests.support.console_world import seed_scored_run

    serve, routes = _api(RUN_START_ISSUE)
    export = _route(routes, RUN_START_ISSUE, read=EXPORT_READ)
    class_view = _route(routes, RUN_START_ISSUE, read=RESULTS_CLASS_READ)
    student_view = _route(routes, RUN_START_ISSUE, read=RESULTS_STUDENT_READ)

    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store, finalize=True)
        truth = _ledger(store, world.run_id)
    finally:
        _close(store)
    assert len(truth) == len(world.submissions) >= 3, f"fixture: ledger {truth}"

    out = tmp_path / "cli-export"
    code, _o, err = _cli_or_blocked(results_export_argv(tmp_data_dir, world.run_id, 1, out),
                                    capsys, RUN_START_ISSUE)
    assert code == 0, f"fixture: `aeh results export` failed: {err}"
    cli_csv = sorted(out.glob("*.csv"))
    cli_pdfs = sorted(out.glob("*.pdf"))
    assert len(cli_csv) == 1 and len(cli_pdfs) == len(world.submissions), (
        f"fixture: the CLI export is not one CSV + one PDF per student: {sorted(out.iterdir())}")
    code, printed, err = _cli_or_blocked(results_show_argv(tmp_data_dir, world.run_id), capsys,
                                         RUN_START_ISSUE)
    assert code == 0, f"fixture: `aeh results show` failed: {err}"
    shown_by_cli = json.loads(printed)

    store = open_store(tmp_data_dir)
    try:
        server = serve(store=store)
        with on_loopback(server, network_guard) as (port, _census):
            status, _h, csv_bytes = get_bytes(
                port, export.path, {"run_id": world.run_id, "revision": 1, "format": "csv"})
            assert status == 200, f"TC-CONSOLE-57: the CSV export answered {status}"
            pdfs = {}
            for pdf in cli_pdfs:
                status, _h, body = get_bytes(
                    port, export.path, {"run_id": world.run_id, "revision": 1,
                                        "format": "pdf", "student_ref": pdf.stem})
                assert status == 200, f"TC-CONSOLE-57: the PDF for {pdf.stem} answered {status}"
                pdfs[pdf.name] = body
            _s, students = get_json(port, student_view.path, {"run_id": world.run_id})
            _s, rollup = get_json(port, class_view.path, {"run_id": world.run_id})
    finally:
        _close(store)
    network_guard.assert_no_network()

    assert csv_bytes == cli_csv[0].read_bytes(), (
        "TC-CONSOLE-57: the console's CSV export is not byte-identical to the CLI's")
    differ = [name for name, body in pdfs.items() if body != (out / name).read_bytes()]
    assert not differ, f"TC-CONSOLE-57: PDFs not byte-identical to the CLI's: {differ}"

    console_students = _by_submission((students or {}).get("students"), "the console's view")
    cli_students = _by_submission(shown_by_cli.get("students"), "`aeh results show`")
    assert console_students == cli_students, (
        f"TC-CONSOLE-57: the per-student view differs from what the CLI prints:\n"
        f"  console {console_students}\n  cli     {cli_students}")
    assert cli_students == truth, (
        f"TC-CONSOLE-57: both surfaces agree but not with the grade ledger: {truth}")
    assert (rollup or {}).get("rollup") not in (None, {}, []), (
        f"TC-CONSOLE-57: the class view shows no rollup: {rollup!r}")
    assert rollup.get("rollup") == shown_by_cli.get("rollup"), (
        f"TC-CONSOLE-57: the class view differs from the CLI's: {rollup.get('rollup')!r} vs "
        f"{shown_by_cli.get('rollup')!r}")
