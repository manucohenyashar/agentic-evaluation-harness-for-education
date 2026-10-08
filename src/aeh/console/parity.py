"""The CLI/console parity inventory (`FR-CONSOLE-41`, `NFR-CONSOLE-09`, issue #632).

The console is the operator surface; the CLI is the debugging surface. The parity check is an
inventory, not a vibe: **every `aeh` subcommand either has a console path or is listed in the
console's debugging-only help section with the reason** — no silent gaps. A subcommand added
later without a decision fails the census (`TC-CONSOLE-54`); that failure is the feature.

The two decision tables are the census's data and the debugging-only help section is their
rendering: `GET /api/v1/cli-help` answers `parity_inventory()`, generated from the live
`aeh` parser at request time, so a stale entry cannot hide. The design fixes none of the names;
they are declared here once, and `tests/support/console_api_vocabulary.py` reads the same two.
"""

from __future__ import annotations

import argparse
from typing import Any

from .api import API_PREFIX, API_ROUTES

#: The subcommands the console covers, as `{"<leaf>": "<METHOD> <api path>"}`. A leaf is the
#: parser's subcommand path, space-joined (`"cohort create"`); the route must be a row of
#: `API_ROUTES`, which is what makes "reachable from the console" checkable rather than claimed.
CLI_CONSOLE_PATHS: dict[str, str] = {
    "run": f"POST {API_PREFIX}/actions/start-run",
    "recover": f"POST {API_PREFIX}/actions/recover-runs",
    "ingest": f"POST {API_PREFIX}/uploads",
    "cohort create": f"POST {API_PREFIX}/actions/create-cohort",
    "cohort add-students": f"POST {API_PREFIX}/actions/add-students",
    # `aeh results show` prints the per-student records AND the class rollup; the console
    # answers the same reads through two routes, and the census names one row per command.
    "results show": f"GET {API_PREFIX}/results/class",
    "results export": f"GET {API_PREFIX}/results/export",
}

#: The debugging-only help section: commands a teacher or operator never needs, each entry
#: saying what the command is *for* when a developer reaches for it (`NFR-CONSOLE-09`). A
#: listing without a reason would pass the bare census and defeat the requirement.
DEBUGGING_ONLY_COMMANDS: dict[str, str] = {
    "console": (
        "starts the console server itself; a developer runs it on the school machine when "
        "there is no browser session yet - teachers reach the console in the browser, never "
        "from the terminal"
    ),
    "cohort show": (
        "prints a cohort's consent class and roster size from the terminal; the console's "
        "screens show the roster and its consent class, so this is the read a debugging "
        "session takes without a browser"
    ),
    "package build": (
        "builds and publishes a package from a TOML spec; the console publishes the package "
        "from its setup screens, and the spec is a system-emitted export (FR-PKG-27), so "
        "authoring one is a developer action by design"
    ),
    "package export": (
        "writes a package version's spec TOML for a developer rebuilding or diffing a "
        "published package; the console's export gate delivers the school-facing package "
        "file instead"
    ),
}

#: What each CLI command is *for*, console path or not (`NFR-CONSOLE-09`'s other half): the
#: console's help explains the command to a developer who needs it. Every leaf the parser has
#: is named here; `parity_inventory` reports a leaf that is not.
CLI_COMMAND_PURPOSE: dict[str, str] = {
    "run": (
        "drives one cohort's run to completion from the terminal; the console's run-start "
        "screen starts the same run on a server-owned worker, and a developer reaches for "
        "this to script a run or to read its exit code"
    ),
    "recover": (
        "reclaims expired leases, resumes open runs and settles lapsed review windows from "
        "the terminal; the console's recover control runs the same M-PIPE door, and a "
        "developer uses the command after a crash when no console is open"
    ),
    "console": DEBUGGING_ONLY_COMMANDS["console"],
    "cohort create": (
        "creates a cohort and loads its roster from a file; the console's roster editor takes "
        "the same names pasted in, and a developer scripts a class set-up or loads a CSV "
        "without the browser"
    ),
    "cohort add-students": (
        "adds late students to an existing cohort's roster from a file; the console's roster "
        "editor adds the same rows, and a developer scripts the extension"
    ),
    "cohort show": DEBUGGING_ONLY_COMMANDS["cohort show"],
    "package build": DEBUGGING_ONLY_COMMANDS["package build"],
    "package export": DEBUGGING_ONLY_COMMANDS["package export"],
    "ingest": (
        "reads scanned papers through the intake checks from the terminal; the console's "
        "loading-papers screen reads the same files through the same checks, and a developer "
        "uses the command to watch one sheet's gates line by line"
    ),
    "results show": (
        "prints a run's per-student records and class rollup as JSON; the console's results "
        "views answer the same reads, and a developer diffs the two surfaces or scripts a "
        "check against them"
    ),
    "results export": (
        "writes the school-facing export (the marks CSV and one PDF per student) from the "
        "terminal; the console's results screen delivers the same files, and a developer uses "
        "the command when the download must be scripted"
    ),
}


def cli_leaf_commands(parser: argparse.ArgumentParser) -> list[str]:
    """Every leaf subcommand of the `aeh` parser, space-joined (`"cohort create"`), walked
    from the parser itself — the inventory is generated, never hand-kept."""
    leaves: list[str] = []

    def walk(node: Any, prefix: tuple[str, ...]) -> None:
        groups = [a for a in node._actions if isinstance(a, argparse._SubParsersAction)]
        if not groups:
            if prefix:
                leaves.append(" ".join(prefix))
            return
        for group in groups:
            for name, child in group.choices.items():
                walk(child, prefix + (name,))

    walk(parser, ())
    return sorted(leaves)


def parity_inventory() -> dict[str, Any]:
    """The full inventory, generated from the live `aeh` parser (`GET /api/v1/cli-help`).

    Every leaf appears exactly once: as a console path, or in the debugging-only section with
    its reason. Anything else — a leaf with no decision, a stale inventory name the parser no
    longer has, a console path that is not a row of `API_ROUTES`, a command with no "what it
    is for" line — lands in `gaps` beside the entries rather than being hidden: the census
    (`TC-CONSOLE-54`) fails on the same list, and a reader of the help sees the gap, not
    silence.
    """
    from aeh.pipeline.cli import _build_parser

    leaves = cli_leaf_commands(_build_parser())
    table = {f"{route.method} {route.path}" for route in API_ROUTES}
    declared = set(CLI_CONSOLE_PATHS) | set(DEBUGGING_ONLY_COMMANDS) | set(CLI_COMMAND_PURPOSE)
    commands: list[dict[str, Any]] = []
    gaps: list[str] = []
    for leaf in leaves:
        path = CLI_CONSOLE_PATHS.get(leaf)
        reason = DEBUGGING_ONLY_COMMANDS.get(leaf)
        purpose = CLI_COMMAND_PURPOSE.get(leaf)
        if path and reason:
            gaps.append(f"`aeh {leaf}` is listed twice: a console path AND debugging-only")
        if not path and not reason:
            gaps.append(f"`aeh {leaf}` is silently unrepresented: no console path and no "
                        "debugging-only listing")
        if purpose is None:
            gaps.append(f"`aeh {leaf}` has no line saying what it is for")
        if path and str(path) not in table:
            gaps.append(f"`aeh {leaf}`'s console path {path!r} is not a row of API_ROUTES")
        entry: dict[str, Any] = {
            "command": leaf,
            "purpose": purpose or "",
            "surface": "console" if path else "debugging-only",
        }
        if path:
            entry["console_path"] = path
        if reason:
            entry["reason"] = reason
        commands.append(entry)
    for name in sorted(declared - set(leaves)):
        gaps.append(f"the inventory lists `aeh {name}`, which the parser does not have")
    return {
        "rule": ("the console is the operator surface; the CLI is the debugging surface "
                 "(NFR-CONSOLE-09). Every `aeh` subcommand either has a console path or is "
                 "listed here as debugging-only with the reason."),
        "commands": commands,
        "gaps": gaps,
    }


__all__ = [
    "CLI_COMMAND_PURPOSE",
    "CLI_CONSOLE_PATHS",
    "DEBUGGING_ONLY_COMMANDS",
    "cli_leaf_commands",
    "parity_inventory",
]
