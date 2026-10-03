"""The `aeh` command line: `aeh run`, `aeh recover` and their options."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from typing import Any, Mapping, Sequence

from aeh.conf import effective_config
from aeh.orch import Orchestrator

from .settings import _int_knob, MAX_PASSES_ENV, PASS_SLEEP_MS_ENV
from .results import RunResult
from .hooks import _FAULT_PREFIX
from .driver import recover, run_to_completion
from .runtime import _describe_provider, _load_config_file, _open_store, _provider_for
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

    recover_parser = sub.add_parser("recover", help="reclaim leases, resume and settle grades")
    recover_parser.add_argument("--data-dir", required=True)

    console_parser = sub.add_parser("console", help="recover, then serve the operator console")
    console_parser.add_argument("--data-dir", required=True)
    console_parser.add_argument("--config", default=None)
    return parser


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
        if args.command == "recover":
            store = _open_store(args.data_dir)
            try:
                report = recover(store)
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
            server = serve_console(store, cfg=config)
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
        store = _open_store(args.data_dir)
        try:
            recover(store)
            result = _run_command(store, args, config)
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


def _run_command(store: Any, args: Any, config: Mapping[str, Any]) -> RunResult:
    """`aeh run`: find the run or create it, then drive it (FR-PIPE-08)."""
    from aeh.conf import resolve_run_config

    existing = [
        handle for handle in Orchestrator(store).runs()
        if handle.cohort_id == args.cohort
        and handle.package_version_id == args.package_version
    ]
    # The cohort's DECLARED consent class, read from the store. `CohortRef`'s default is
    # `'real'` and fail-closed, so passing the bare id would refuse every synthetic cohort
    # against a remote backend — the gate firing on an answer nobody looked up.
    run_config = resolve_run_config(dict(config), Orchestrator(store).cohort_ref(args.cohort))
    # The providers are built BEFORE the run exists and bound to the orchestrator that creates
    # it. A `cloud-hosted` run's retention gate runs inside `create_run` and asks them
    # (`FR-PROV-14`); without one it refused every hosted run as "given no provider able to
    # verify zero-retention routing" (live-test blocker B1). The decision provider is bound
    # too, so the gate asks IT about the decision model: left unbound, the gate falls back to
    # the completion provider, which would answer for a model it never dispatches to.
    provider = _provider_for(run_config)
    decision_provider = _decision_provider_for_run(run_config, provider, None)
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
    else:
        run_id = orchestrator.create_run(
            args.cohort, args.package_version, run_config)
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
    summary = getattr(run_config, "profile_summary", None)
    if callable(summary):
        print(summary())
    print(f"provider: {_describe_provider(provider)}")
    return run_to_completion(
        store, run_id, provider=provider, run_config=run_config,
        decision_provider=decision_provider)


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
