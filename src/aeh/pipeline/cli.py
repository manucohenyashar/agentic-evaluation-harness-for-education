"""The `aeh` command line: `aeh run`, `aeh recover` and their options."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
import webbrowser
from typing import Any, Mapping, Sequence

from aeh.conf import effective_config
from aeh.orch import Orchestrator

from .settings import _int_knob, MAX_PASSES_ENV, PASS_SLEEP_MS_ENV
from .results import RunResult
from .hooks import _FAULT_PREFIX
from .driver import recover, run_to_completion
from .runtime import (
    _describe_provider, _escalation_judge_refs, _load_config_file, _model_pins, _open_store,
    _provider_for,
)
from .decision_engine import _decision_provider_for_run
from .background import resume_runs_in_background


EXIT_OK = 0


EXIT_ERROR = 1


EXIT_PAUSED = 3


def _build_parser() -> Any:
    parser = argparse.ArgumentParser(
        prog="aeh",
        description="Run, recover and serve the agentic evaluation harness.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="drive a cohort's run to completion")
    run_parser.add_argument("--data-dir", required=True)
    run_parser.add_argument("--cohort", required=True)
    run_parser.add_argument("--package-version", required=True)
    run_parser.add_argument("--config", default=None)
    # FR-PIPE-19: the optional pins naming which extractor and synthesizer this run's
    # stages use, `provider|build_id[|quantization]`. Recorded in the run's frozen
    # config, so a replay pins the recorded corpus it replays (TC-SMOKE-12, RES-19).
    run_parser.add_argument(
        "--extractor", default=None, metavar="REF",
        help="pin the extractor build: provider|build_id[|quantization]")
    run_parser.add_argument(
        "--synthesizer", default=None, metavar="REF",
        help="pin the synthesizer build: provider|build_id[|quantization]")

    recover_parser = sub.add_parser("recover", help="reclaim leases, resume and settle grades")
    recover_parser.add_argument("--data-dir", required=True)
    # FR-PIPE-19: validate-only — recovery creates no run, and each run keeps the pin it
    # froze; a flag that disagrees with a recorded pin is refused before anything writes.
    recover_parser.add_argument(
        "--extractor", default=None, metavar="REF",
        help="validate against the runs' frozen extractor pin")
    recover_parser.add_argument(
        "--synthesizer", default=None, metavar="REF",
        help="validate against the runs' frozen synthesizer pin")

    console_parser = sub.add_parser("console", help="recover, then serve the operator console")
    console_parser.add_argument("--data-dir", required=True)
    console_parser.add_argument("--config", default=None)
    # FR-PIPE-11: the startup URL may auto-open the default browser; this flag is the first of
    # the two ways an operator disables that (the other is HARNESS_CONSOLE_AUTO_OPEN=0).
    console_parser.add_argument(
        "--no-open", action="store_true",
        help="do not open the console in the default browser")

    # Live-test blocker B3: the operator's way to create a cohort and load its roster.
    cohort_parser = sub.add_parser(
        "cohort", help="make a cohort (class) with its consent class and roster, or show one")
    cohort_sub = cohort_parser.add_subparsers(dest="cohort_command", required=True)
    create = cohort_sub.add_parser(
        "create", help="make a cohort; its consent class can never be changed afterwards")
    create.add_argument("--data-dir", required=True)
    create.add_argument("--cohort", required=True)
    create.add_argument("--consent", required=True, choices=_consent_classes(),
                        help="synthetic (made-up practice work), consented, or real")
    create.add_argument("--roster", required=True,
                        help="a file of students' full names: one per line, or a CSV with a "
                             "full_name column and an optional student_ref (ID) column. Papers "
                             "are matched by the name on their 'Student:' line")
    add = cohort_sub.add_parser("add-students", help="add students to an existing cohort")
    add.add_argument("--data-dir", required=True)
    add.add_argument("--cohort", required=True)
    add.add_argument("--roster", required=True)
    show = cohort_sub.add_parser("show", help="print a cohort's consent class and roster size")
    show.add_argument("--data-dir", required=True)
    show.add_argument("--cohort", required=True)

    # Live-test blocker B5: the operator's way to build and publish a package from a spec.
    package_parser = sub.add_parser(
        "package", help="build and publish a package (a test's questions, rubric and keys)")
    package_sub = package_parser.add_subparsers(dest="package_command", required=True)
    build = package_sub.add_parser(
        "build", help="build and publish a package from a TOML spec; it can never be changed")
    build.add_argument("--data-dir", required=True)
    build.add_argument("--spec", required=True, help="the package spec (TOML)")
    # FR-PKG-27: the spec is a system-emitted export, and this is the command that emits it —
    # the inverse of `build`, kept as the debugging/export path (Q-O6). No teacher-facing
    # surface presents TOML authoring.
    export = package_sub.add_parser(
        "export",
        help="write a package version's spec TOML, which `aeh package build --spec` accepts "
             "unchanged")
    export.add_argument("--data-dir", required=True)
    export.add_argument("--package-version", required=True,
                        help="the package version id, as build and the console print it")
    export.add_argument("--spec", required=True, help="the file the spec is written to")

    # FR-PIPE-10 (#695): the authoring draft and review as CLI subcommands — the library's
    # `AuthoringService` surface (CT-AUTHOR-01) driven from the terminal. The console's
    # authoring screens are future console work (FR-CONSOLE-46), so the terminal is the
    # surface this delta builds; the exit codes are §3.1's convention: 0 when the draft is
    # written or the review is ready, 1 on every error, 2 left to argparse alone.
    author_parser = sub.add_parser(
        "author", help="draft a package spec from teacher documents, then review it")
    author_sub = author_parser.add_subparsers(dest="author_command", required=True)
    draft = author_sub.add_parser(
        "draft",
        description=(
            "Turn teacher-authored documents into a draft package spec and an authoring\n"
            "report. A draft publishes only through `aeh package build` after review; the\n"
            "review walk collects the answers the draft leaves open."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    draft.add_argument("--config", required=True, help="the configuration file (TOML)")
    draft.add_argument("--docs", required=False, default=None, nargs="+", metavar="PDF",
                       help="the teacher-authored documents to read (PDFs) — omitted when "
                            "--from-scratch starts from an empty skeleton instead")
    draft.add_argument("--out", required=True,
                       help="the directory the draft spec and report are written into")
    draft.add_argument(
        "--force", action="store_true",
        help="overwrite an existing draft and report for the same package id without "
             "confirming (recorded review answers still carry over)")
    # FR-AUTHOR-29 (console redesign delta §3.1.2, #759): the from-scratch counterpart,
    # the same library method the console's *from scratch* entry drives; it joins the
    # parity census (FR-CONSOLE-41) as this command's other mode.
    draft.add_argument(
        "--from-scratch", action="store_true",
        help="write an empty draft skeleton — zero questions, zero criteria, no "
             "placeholders — and a report marked created empty, instead of reading "
             "documents; fill the skeleton in the console's structured editor")
    draft.add_argument(
        "--title", default=None,
        help="the package's name; with --from-scratch it is slugified into the package "
             "id the draft and report are written under")
    review = author_sub.add_parser(
        "review", help="walk a draft's unresolved items to resolution ahead of the build")
    review.add_argument("--draft", required=True, help="the draft spec (TOML) to review")

    # Live-test blocker B4: read scanned papers through the intake checks.
    ingest_parser = sub.add_parser(
        "ingest", help="read the test paper and answer sheets (PDFs) through the intake checks")
    ingest_parser.add_argument("--data-dir", required=True)
    ingest_parser.add_argument("--cohort", required=True)
    ingest_parser.add_argument("--package-version", required=True)
    ingest_parser.add_argument("--config", default=None)
    ingest_parser.add_argument("--assessment", default=None,
                               help="the test paper PDF (needed once per cohort)")
    ingest_parser.add_argument("sheets", nargs="+",
                               help="answer sheet PDFs, one per student, or folders of them")

    # #631 (FR-CONSOLE-44): the results reads as CLI subcommands. The console's results
    # views are compared against these — the export byte for byte (TC-CONSOLE-57) — and
    # a debugging session reaches for them without a browser, so they are the inverse
    # half of the same reads, not a second implementation.
    results_parser = sub.add_parser(
        "results", help="show a run's grades and rollup, or export the school-facing set")
    results_sub = results_parser.add_subparsers(dest="results_command", required=True)
    results_show = results_sub.add_parser(
        "show", help="print the run's per-student records and class rollup as JSON")
    results_show.add_argument("--data-dir", required=True)
    results_show.add_argument("--run", required=True)
    results_export = results_sub.add_parser(
        "export", help="write the school-facing export: the marks CSV and one PDF per student")
    results_export.add_argument("--data-dir", required=True)
    results_export.add_argument("--run", required=True)
    results_export.add_argument("--revision", type=int, default=1)
    results_export.add_argument("--out", required=True,
                                help="the directory the export's files are written into")
    return parser


def _results_command(args: Any) -> int:
    """`aeh results show | export` (#631, FR-CONSOLE-44). Both are M-GRADE's doors —
    the same reads the console's results views call — so the CLI and the console are one
    implementation, and a refusal (a run no ledger holds, a revision with no rows) leaves
    nothing written."""
    from pathlib import Path

    from aeh.grade import export_grade_artifacts, run_results

    store = _open_store(args.data_dir)
    try:
        if args.results_command == "show":
            print(json.dumps(_as_json(run_results(store, args.run)), indent=2, sort_keys=True))
            return EXIT_OK
        artifacts = export_grade_artifacts(
            args.run, int(args.revision), Path(args.out), store=store)
        # Paths are printed as strings themselves (`_as_json` passes a `Path` through),
        # so the export's shape is exactly the file names an operator acts on.
        print(json.dumps(
            {"csv_path": str(artifacts.csv_path),
             "pdf_paths": [str(p) for p in artifacts.pdf_paths]},
            indent=2, sort_keys=True))
        return EXIT_OK
    finally:
        store.close()


def _ingest_command(args: Any) -> int:
    """`aeh ingest`. One line per sheet on stderr as it goes, then the whole result as JSON.
    Exits 1 when a sheet errored, the cohort was stopped, or no sheet could be read at all."""
    from aeh.conf import resolve_run_config

    from .intake import answer_sheet_files, ingest_files

    sheets = answer_sheet_files(args.sheets)  # checked before the store opens
    config = effective_config(_load_config_file(args.config))
    store = _open_store(args.data_dir)
    try:
        # The consent gate runs here, before a page is read: a cohort whose work may not leave
        # the machine is refused on a remote profile (FR-CONF-08).
        run_config = resolve_run_config(dict(config), Orchestrator(store).cohort_ref(args.cohort))
        provider = _provider_for(run_config)
        print(f"provider: {_describe_provider(provider)}", file=sys.stderr)
        result = ingest_files(
            store, run_config, args.cohort, args.package_version, assessment=args.assessment,
            sheets=sheets, provider=provider,
            on_sheet=lambda sheet: print(f"{sheet.file}: {sheet.status} {sheet.detail}".rstrip(),
                                         file=sys.stderr, flush=True))
    finally:
        store.close()
    if result.interrupted:
        print(f"parked {len(result.interrupted)} paper(s) an earlier, cut-off read left behind; "
              "they wait in quarantine (S8) to be closed as 'unresolvable'", file=sys.stderr)
    print(json.dumps(_as_json(result), indent=2, sort_keys=True))
    if result.nothing_readable:
        print("no answer sheet could be read: this is usually the page-reading model, not the "
              "scans (check the API key, the account's credit and the model name in the warnings "
              "above). Each sheet now waits in quarantine; close those and read the folder again.",
              file=sys.stderr)
        return EXIT_ERROR
    return EXIT_ERROR if any(s.status in ("stopped", "error") for s in result.sheets) else EXIT_OK


def _package_command(args: Any) -> int:
    """`aeh package build`. Prints the built package as JSON, including the package version id
    `aeh run` and `aeh ingest` need."""
    from pathlib import Path

    from .packages import build_package, plan_package, read_package_spec

    # Read and checked in full before the store opens, so a refused spec touches nothing, not
    # even the data folder's skeleton.
    spec = read_package_spec(args.spec)
    plan_package(spec, Path(args.data_dir) / "packages")
    store = _open_store(args.data_dir)
    try:
        built = build_package(store, spec)
    finally:
        store.close()
    print(json.dumps(_as_json(built), indent=2, sort_keys=True))
    return EXIT_OK


def _package_export_command(args: Any) -> int:
    """`aeh package export`. Writes the spec TOML for one published package version and prints
    what was written as JSON; the store is only read."""
    from pathlib import Path

    from .spec_export import export_spec

    store = _open_store(args.data_dir)
    try:
        exported = export_spec(store, args.package_version, Path(args.spec))
    finally:
        store.close()
    print(json.dumps(_as_json(exported), indent=2, sort_keys=True))
    return EXIT_OK


def _author_draft_command(args: Any) -> int:
    """`aeh author draft` (#695, FR-PIPE-10). The library's `AuthoringService.draft` driven
    from the terminal — the CLI is a thin frontend (CT-AUTHOR-01), so no workflow logic
    lives here: the config resolves the profile the way `aeh run` does (`HARNESS_PROFILE`,
    the environment over the file), and the provider comes from `_provider_for`, the
    pipeline's resolution seam (`HARNESS_FIXTURE_DIR` -> the recorded provider, `CT-PROV-10`).

    `--from-scratch` (FR-AUTHOR-29, #759) drives `AuthoringService.draft_from_scratch`
    instead — an empty skeleton and a created-empty report, no documents read and no model
    called; `--title` is required with it, and `--docs` is unnecessary (the skeleton reads
    nothing).

    An existing draft and report for the same package id are refused before anything is
    written (FR-AUTHOR-22); `--force` is the non-interactive confirmation, and without it
    the refusal asks — `y`/`yes` re-drafts, anything else (EOF included) stops with nothing
    written. Errors surface through `main`'s wrapper: exit 1, nothing written.
    """
    from pathlib import Path

    from aeh.author.errors import OverwriteRefusedError
    from aeh.author.service import authoring_service

    if args.from_scratch:
        if not str(args.title or "").strip():
            print("aeh author draft: --from-scratch needs --title: the title names the "
                  "package the skeleton is written under (FR-AUTHOR-29).", file=sys.stderr)
            return EXIT_ERROR
    elif not args.docs:
        print("aeh author draft: error: the following arguments are required: --docs "
              "(or --from-scratch, which reads no documents)", file=sys.stderr)
        return 2

    config = effective_config(_load_config_file(args.config))
    profile = str(config.get("HARNESS_PROFILE") or "")
    provider = _provider_for({"backend_profile": profile})
    service = authoring_service(config, profile, provider=provider)
    output_dir = Path(args.out)
    try:
        if args.from_scratch:
            service.draft_from_scratch(output_dir, str(args.title or "").strip(),
                                       force=args.force)
            return EXIT_OK
        service.draft([Path(document) for document in args.docs], output_dir,
                      force=args.force)
    except OverwriteRefusedError as error:
        print(f"aeh author draft: {type(error).__name__}: {error}", file=sys.stderr)
        if not _confirmed("Overwrite the existing draft and report for this package id?"):
            return EXIT_ERROR
        if args.from_scratch:
            service.draft_from_scratch(
                output_dir, str(args.title or "").strip(), force=True)
        else:
            service.draft([Path(document) for document in (args.docs or [])],
                          output_dir, force=True)
    return EXIT_OK


def _author_review_command(args: Any) -> int:
    """`aeh author review` (#695, FR-PIPE-10). The review walk over a draft, which makes no
    model call: it reads the draft, asks the teacher one answer per unresolved item on
    stdin (EOF stops, keeping what it applied — FR-AUTHOR-17), and prints the build command
    only when the draft is ready. Exit 0 when ready, 1 when items remain — and the same 1
    for a missing or non-authoring draft, whose reason the walk raises
    (`AuthoringInputError`) for `main`'s wrapper to print; the outputs distinguish them.
    """
    from pathlib import Path

    from aeh.author.review import run_review

    result = run_review(Path(args.draft), None)
    return EXIT_OK if result.ready else EXIT_ERROR


def _confirmed(prompt: str) -> bool:
    """The interactive confirmation for an otherwise-refused overwrite. EOF — a scripted or
    closed stdin — is a no: a prompt nobody could answer must not proceed."""
    try:
        answer = input(f"{prompt} [y/N]: ")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def _consent_classes() -> tuple[str, ...]:
    from aeh.orch.cohorts import CONSENT_CLASSES

    return CONSENT_CLASSES


def _cohort_command(args: Any) -> int:
    """`aeh cohort create | add-students | show`. Prints the cohort as JSON; a refusal is raised
    and reported by `main` like every other error, and writes nothing."""
    from aeh.orch.cohorts import add_to_roster, check_cohort_id, cohort_summary, create_cohort

    from .rosters import read_roster_file

    # Checked and read BEFORE the store is opened, so a typo'd id or a bad roster file leaves no
    # data-folder skeleton behind.
    check_cohort_id(args.cohort)
    entries = read_roster_file(args.roster) if args.cohort_command != "show" else ()
    store = _open_store(args.data_dir)
    try:
        if args.cohort_command == "create":
            summary = create_cohort(store, args.cohort, args.consent, entries)
        elif args.cohort_command == "add-students":
            summary = add_to_roster(store, args.cohort, entries)
        else:
            summary = cohort_summary(store, args.cohort)
            if summary is None:
                raise ValueError(f"no cohort {args.cohort!r} exists in {args.data_dir}")
    finally:
        store.close()
    print(json.dumps(_as_json(summary), indent=2, sort_keys=True))
    if summary.consent_class == "real":
        print("note: consent class 'real' - the dev-ci and cloud-hosted profiles will refuse to "
              "send this cohort's work to a hosted model unless HARNESS_ALLOW_REMOTE_REAL_WORK and "
              "allow_remote_real_work_supplied_by are both set.", file=sys.stderr)
    return EXIT_OK


#: The knob `aeh console` reads for the startup auto-open (FR-PIPE-11): the design enumerates
#: the *disable* values only, so anything else is not a recognized value and falls back to the
#: default with a warning naming the knob and the value.
CONSOLE_AUTO_OPEN_ENV = "HARNESS_CONSOLE_AUTO_OPEN"

_CONSOLE_AUTO_OPEN_OFF = frozenset({"0", "false", "off"})


def _console_auto_open(no_open: bool) -> tuple[bool, str | None]:
    """Whether `aeh console` may open the default browser after the bind succeeds (FR-PIPE-11).

    `--no-open` wins first. Then `HARNESS_CONSOLE_AUTO_OPEN`: `0`, `false` or `off` (any case)
    disables, and any other value is refused with a warning naming the knob and the value, the
    default standing in its place. The default itself is "on for an interactive terminal, off
    otherwise": tests, piped output and in-process drivers get no browser, which is the headless
    rule (`CT-CONSOLE-01`) — and why `serve_console()` never opens one either. The empty string
    reads as unset.
    """
    if no_open:
        return False, None
    default = sys.stdin.isatty() and sys.stdout.isatty()
    raw = os.environ.get(CONSOLE_AUTO_OPEN_ENV)
    if raw is None or raw == "":
        return default, None
    if raw.strip().lower() in _CONSOLE_AUTO_OPEN_OFF:
        return False, None
    return default, (
        f"warning: {CONSOLE_AUTO_OPEN_ENV}={raw!r} is not a recognized value "
        f"(use 0, false or off); using the default (auto-open {'on' if default else 'off'})."
    )


def _open_console_browser(url: str) -> bool:
    """Open `url` in the default browser — the seam a test patches instead of the browser
    itself. A browser that will not open must never take the console down, so a failure is
    reported as `False` and nothing more."""
    try:
        return bool(webbrowser.open(url))
    except Exception:  # noqa: BLE001 — the serve path must not depend on the browser opening
        return False


def main(argv: "Sequence[str] | None" = None) -> int:
    """The `aeh` command line (`python -m aeh` and the installed `aeh` command) (FR-PIPE-08,
    FR-PIPE-09). Returns the exit code.

    Exit codes are the contract (`CT-PIPE-01`): **0** when the run completes, **3** when it
    pauses, **1** on any error. A paused run is not a failure — it is a run waiting for an
    operator — and collapsing the two would make an outage indistinguishable from a bug in
    every script that calls this.

    Returns rather than raising `SystemExit`: `aeh/__main__.py` does the raising, so this
    function stays callable from a test without catching an exception to read an integer.
    """
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "cohort":
            return _cohort_command(args)
        if args.command == "author":
            if args.author_command == "draft":
                return _author_draft_command(args)
            return _author_review_command(args)
        if args.command == "package":
            if args.package_command == "export":
                return _package_export_command(args)
            return _package_command(args)
        if args.command == "ingest":
            return _ingest_command(args)
        if args.command == "results":
            return _results_command(args)
        if args.command == "recover":
            # FR-PIPE-19 / TC-PIPE-35: the pins are resolved and refused BEFORE the store
            # opens — the same checked-before-the-store posture the knob checks above have,
            # so an unresolvable ref leaves no data-folder skeleton behind. The effective
            # configuration decides the profile: recovery reads no config file, so the
            # environment wins exactly as it does on the run path.
            pins = _model_pins(args, str(effective_config({}).get("HARNESS_PROFILE") or ""))
            store = _open_store(args.data_dir)
            try:
                report = recover(
                    store,
                    extractor=pins.get("extractor"), synthesizer=pins.get("synthesizer"))
            finally:
                store.close()
            print(json.dumps(_as_json(report), indent=2, sort_keys=True))
            return EXIT_OK

        if args.command == "console":
            from aeh.console import serve_console

            config = effective_config(_load_config_file(args.config))
            store = _open_store(args.data_dir)
            # `FR-PIPE-09`: recovery runs BEFORE the socket accepts, so an expired lease is
            # reclaimed rather than sitting held while an operator watches a stalled queue.
            recover(store)
            # NFR-CONSOLE-08: a run the killed server was driving continues here, on a
            # worker this server owns, once `recover` has reclaimed its leases.
            resume_runs_in_background(store, config=config)
            server = serve_console(store, cfg=config, config_path=args.config)
            if config.get("HARNESS_PROFILE"):
                # Which backend a run started from this console will call (seam 4): the same
                # line `aeh run` prints, so an operator can see a stray HARNESS_FIXTURE_DIR.
                print("provider for runs started here: " + _describe_provider(
                    _provider_for({"backend_profile": config["HARNESS_PROFILE"]})))
            # `serve_console` BINDS and returns: the accept loop runs on a daemon thread
            # (`console.py`), so returning here would end the process and take the thread with
            # it — the socket would close before anything could connect, and #365's "the
            # expired lease is reclaimed before the socket accepts" would be vacuously true
            # against a console that never accepted. So the command blocks, which is what an
            # operator running `aeh console` expects it to do.
            print(f"console listening on port {getattr(server, 'port', '?')} "
                  f"(pid {getattr(server, 'pid', '?')}); Ctrl-C to stop")
            # FR-PIPE-11: after the bind succeeds the operator gets the clickable full URL and
            # the one-line next step (design delta §3.2.5), and the default browser opens
            # unless it was disabled. The auto-open lives here, on the CLI path, and never in
            # `serve_console()` — tests and in-process drivers are unaffected.
            host = ("[::1]" if str(getattr(server, "bind_address", "")) == "::1"
                    else "127.0.0.1")
            url = f"http://{host}:{getattr(server, 'port', '?')}/"
            print(f"  Grading console:  {url}")
            print("  Next step:        create a class, then a test package — "
                  "the home page walks you through it.")
            open_browser, auto_open_warning = _console_auto_open(
                bool(getattr(args, "no_open", False)))
            if auto_open_warning:
                print(auto_open_warning, file=sys.stderr)
            if open_browser and not _open_console_browser(url):
                print(f"warning: the default browser could not be opened; "
                      f"the console is at {url}", file=sys.stderr)
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
            finally:
                terminate = getattr(server, "terminate", None)
                if callable(terminate):
                    terminate()
            return EXIT_OK

        # TC-PIPE-14: a malformed knob is refused before the store is opened. `recover` below
        # can reclaim leases, which is a write, so validating only inside `run_to_completion`
        # would refuse the knob after rows had already changed.
        _int_knob(MAX_PASSES_ENV, None, minimum=1)
        _int_knob(PASS_SLEEP_MS_ENV, 0, minimum=0)
        config = effective_config(_load_config_file(args.config))
        # FR-PIPE-19 / TC-PIPE-35: the pins are resolved against the profile the effective
        # configuration settled on, BEFORE the store opens — an unresolvable ref exits 1
        # and creates no run row, exactly like a malformed knob above.
        pins = _model_pins(args, str(config.get("HARNESS_PROFILE") or ""))
        store = _open_store(args.data_dir)
        try:
            recover(store)
            result = _run_command(store, args, config, pins)
        finally:
            store.close()
        print(json.dumps(_as_json(result), indent=2, sort_keys=True))
        if str(result.pause_reason or "").startswith(_FAULT_PREFIX):
            # A composition fault that could not pause the run — `pause()` refuses a terminal
            # run — used to leave `status == "complete"` and return 0, reporting success for a
            # run whose hook raised and whose scores may be missing. The fault is on the
            # result either way, so the exit code follows it (`CT-PIPE-01`).
            #
            # **A deliberate narrowing of FR-PIPE-08's literal "3 on paused".** A run PAUSED by
            # a composition fault now exits 1 rather than 3. #365's own criterion qualifies
            # the 3 as "(provider outage)" — an operator condition to wait out — and a
            # composition fault is a defect in this module, which is what 1 is for. Stated
            # here because it is a choice, not an oversight.
            print(f"aeh run: {result.pause_reason}", file=sys.stderr)
            return EXIT_ERROR
        return EXIT_OK if result.status == "complete" else EXIT_PAUSED
    except Exception as error:  # noqa: BLE001 - the command line reports, never traces back
        print(f"aeh {args.command}: {type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_ERROR


def _run_command(
    store: Any, args: Any, config: Mapping[str, Any], pins: Mapping[str, Any] | None = None,
) -> RunResult:
    """`aeh run`: find the run or create it, then drive it (FR-PIPE-08).

    `pins` (`FR-PIPE-19`) is the `--extractor` / `--synthesizer` mapping, already
    resolved against the effective profile. On a NEW run it is frozen into the row; on a
    CONTINUING one it must match what the run froze, and a role the run recorded but the
    operator did not flag is re-applied from the row — a run keeps the identities it
    froze (`FR-CONF-15`'s posture, `TC-PIPE-36`).
    """
    from aeh.conf import environment_snapshot, resolve_orch_knobs, resolve_run_config

    given = dict(pins or {})
    existing = [
        handle for handle in Orchestrator(store).runs()
        if handle.cohort_id == args.cohort
        and handle.package_version_id == args.package_version
    ]
    # The cohort's DECLARED consent class, read from the store. `CohortRef`'s default is
    # `'real'` and fail-closed, so passing the bare id would refuse every synthetic cohort
    # against a remote backend — the gate firing on an answer nobody looked up.
    run_config = resolve_run_config(dict(config), Orchestrator(store).cohort_ref(args.cohort))
    # FR-CONF-36 / CT-CONF-25: the escalation budget and random-arm rate, environment > config
    # file > default, recorded on the run row so the run grades by them.
    orch_knobs = resolve_orch_knobs(config)
    # The providers are built BEFORE the run exists and bound to the orchestrator that creates
    # it. A `cloud-hosted` run's retention gate runs inside `create_run` and asks them
    # (`FR-PROV-14`); without one it refused every hosted run as "given no provider able to
    # verify zero-retention routing" (live-test blocker B1). The decision provider is bound
    # too, so the gate asks IT about the decision model: left unbound, the gate falls back to
    # the completion provider, which would answer for a model it never dispatches to.
    provider = _provider_for(run_config)
    decision_provider = _decision_provider_for_run(run_config, provider, None)
    # Before the run exists: a live run without a real model for every judge seat an
    # escalation can add is refused here, not on its first disagreement.
    judge_refs = _escalation_judge_refs(
        config, run_config, Orchestrator(store).cohort_ref(args.cohort), provider)
    orchestrator = Orchestrator(store, provider=provider, decision_provider=decision_provider)
    if existing:
        # Latest by start time. `run_id` is `run-<uuid4 hex>` and `select_all_runs` orders by
        # it, so "the last row" is an arbitrary run among several for the same cohort and
        # package version — picking it would continue whichever run happened to sort highest.
        handle = max(existing, key=lambda h: (h.started_at, h.run_id))
        run_id = handle.run_id
        # `FR-CONF-15` / `FR-ORCH-16`: a run resumes on the backend it froze. This command
        # resolves a FRESH `RunConfig` from the current environment, so driving an existing
        # run with it would rebind that run to whatever profile this process happens to carry.
        # Rebuilding the frozen `RunConfig` from the run row is not a surface this module has,
        # so the mismatch is refused rather than papered over: fail closed and say which
        # profile the run expects. Reported on #365 as the narrower gap it is.
        if handle.backend_profile and run_config.backend_profile != handle.backend_profile:
            raise ValueError(
                f"run {run_id} froze backend profile {handle.backend_profile!r} and this "
                f"process resolved {run_config.backend_profile!r}; a run resumes on the "
                f"backend it froze (FR-CONF-15). Set HARNESS_PROFILE to "
                f"{handle.backend_profile!r} to continue it."
            )
        # `FR-PIPE-19`: the same posture for the model pins. A flag naming a build the run
        # did not freeze — or a flag at all for a role the run never pinned — would rebind
        # the run's extract or synthesis identity, and re-pinning mid-run re-addresses
        # enumerated work (the pin feeds `compute_work_id`'s extractor input). Refused
        # before anything is driven; a role recorded but not flagged is re-applied below.
        applied = _applied_pins(given, handle)
        # A continuing run grades by the values ITS row recorded at start (or the defaults, for
        # a run started before they were recorded), with the environment still first — so the
        # banner below describes those, not today's file.
        orch_knobs = resolve_orch_knobs({
            **_recorded_orch_knobs(orchestrator._run_row(run_id)),
            **environment_snapshot(include_orch=True),
        })
    else:
        run_id = orchestrator.create_run(
            args.cohort, args.package_version, run_config, model_pins=given or None,
            orch_knobs=orch_knobs)
        applied = dict(given)
    # `create_run` leaves the run `pending`, and a pending run never reaches the completion
    # predicate: `_maybe_complete_run` fires only from `running`. Without this the command
    # dispatches every unit, spends every model call, and then returns `pending` with no
    # synthesis and no grades — exit 3 on a run that in fact finished its work. `start` is
    # idempotent enough to be safe on a run this command just created; an existing run that
    # is already running or paused is left to `recover` and the loop.
    if orchestrator.run_handle(run_id).status == "pending":
        orchestrator.start(run_id)
    # `FR-CONF-14`'s composition is only observable if the command says what it resolved, so
    # the profile summary goes to stdout before the run starts — an operator who switched
    # `HARNESS_PROFILE` can see which profile was selected and where it came from
    # (`TC-CONF-23`), rather than inferring it from how the run behaves.
    # Where the profile came from, then what it resolved to. The source is the half an
    # operator cannot infer from the summary: `HARNESS_PROFILE` in the environment beats the
    # file (`FR-CONF-14`), and after a switch the question is always "did it take mine?".
    source = "environment" if os.environ.get("HARNESS_PROFILE") else "config file"
    print(f"HARNESS_PROFILE source: {source}")
    for line in orch_knobs.banner_lines():
        print(line)
    summary = getattr(run_config, "profile_summary", None)
    if callable(summary):
        print(summary())
    print(f"provider: {_describe_provider(provider)}")
    return run_to_completion(
        store, run_id, provider=provider, run_config=run_config,
        decision_provider=decision_provider, judge_refs=judge_refs,
        extractor=applied.get("extractor"), synthesizer=applied.get("synthesizer"))


def _recorded_orch_knobs(run_row: Any) -> dict[str, Any]:
    """The `orch_*` values a run row's `provider_config` recorded (FR-CONF-36); empty when none."""
    from aeh.conf import ESCALATION_BUDGET_FILE_KEY, RANDOM_ARM_RATE_FILE_KEY

    try:
        recorded = json.loads(run_row["provider_config"] or "{}")
    except (KeyError, IndexError, TypeError, ValueError):
        return {}
    if not isinstance(recorded, dict):
        return {}
    return {key: recorded[key] for key in (ESCALATION_BUDGET_FILE_KEY, RANDOM_ARM_RATE_FILE_KEY)
            if key in recorded}


def _applied_pins(given: Mapping[str, Any], handle: Any) -> dict[str, Any]:
    """The pins this continuation drives with (`FR-PIPE-19`, `TC-PIPE-36`).

    A flagged role must match the run's recorded pin exactly (provider, build and
    quantization — the full identity the run froze, not just the part the hash reads);
    a role recorded but not flagged is re-applied from the row, so a run continued
    without flags keeps its frozen identities rather than falling back to the stage
    defaults. A flag for a role the run never pinned is refused: re-pinning mid-run
    would re-address the work the enumeration already wrote.
    """
    from aeh.conf import ModelRef

    frozen = {pin[0]: pin for pin in handle.model_pins}
    applied: dict[str, Any] = {}
    for role in sorted(set(frozen) | set(given)):
        record = frozen.get(role)
        ref = given.get(role)
        if record is not None and ref is not None:
            if (ref.provider, ref.build_id, ref.quantization) != (
                    record[1], record[2], record[3]):
                raise ValueError(
                    f"run {handle.run_id} froze {role} pin build {record[2]!r} and this "
                    f"command's flag names {ref.build_id!r}; a run resumes with the "
                    f"identities it froze (FR-PIPE-19, the FR-CONF-15 posture). Re-pin "
                    f"only a run that has not started."
                )
            applied[role] = ref
        elif record is not None:
            applied[role] = ModelRef(
                role=role, provider=record[1], build_id=record[2], quantization=record[3])
        else:
            raise ValueError(
                f"run {handle.run_id} recorded no {role} pin and this command's flag "
                f"names build {ref.build_id!r}: pinning a role mid-run would re-address "
                f"the work already enumerated under the run's recorded identity. Create a "
                f"new run to pin a different build (FR-PIPE-19)."
            )
    return applied


def _as_json(value: Any) -> Any:
    """A `RunResult` or `RecoveryReport` as plain JSON, the shape printed to stdout."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _as_json(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, (list, tuple)):
        return [_as_json(item) for item in value]
    if isinstance(value, Mapping):
        return {str(k): _as_json(v) for k, v in value.items()}
    return value
