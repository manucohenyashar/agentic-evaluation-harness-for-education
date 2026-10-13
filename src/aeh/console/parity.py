"""The CLI/console parity inventory (`FR-CONSOLE-41`, `NFR-CONSOLE-09`, issue #632).

The console is the operator surface; the CLI is the debugging surface. The parity check is an
inventory, not a vibe: **every `aeh` subcommand either has a console path or is listed in the
console's debugging-only help section with the reason** — no silent gaps. A subcommand added
later without a decision fails the census (`TC-CONSOLE-54`); that failure is the feature.

The two decision tables are the census's data and the debugging-only help section is their
rendering: `GET /api/v1/cli-help` answers `parity_inventory()`, generated from the live
`aeh` parser at request time, so a stale entry cannot hide. The design fixes none of the names;
they are declared here once, and `tests/support/console_api_vocabulary.py` reads the same two.

The authoring commands are listed as debugging-only rows with the reason (`FR-CONSOLE-46`,
design delta §3.5): `aeh author draft` / `aeh author review` are CLI first (FR-PIPE-10,
#695 registered them), and the authoring screens are future console work, so the listing
says so instead of inventing a console path this delta does not build.

`FR-CONSOLE-41`'s other half is the console-redesign delta's own capabilities (§1.2: every
new capability "has a terminal counterpart or a debugging-only listing; the parity census is
updated in the same change that adds the actions"). `CONSOLE_CAPABILITY_PARITY` is that
census: one decision row per capability the delta added, naming the `aeh` command that opens
the same door or stating the console-only posture with the reason, rendered beside the
command rows in `parity_inventory()` (#767 — #760 added the actions without the rows).
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
    # `aeh author draft` / `aeh author review` are CLI first (FR-PIPE-10) and registered
    # (#695); the authoring screens — upload the documents, render the report, collect the
    # review answers — are future console work (FR-CONSOLE-46, design delta §3.5). The
    # console path is not invented, and the reason says the screens have yet to be built.
    "author draft": (
        "turns teacher-authored documents into a draft package spec plus an authoring report "
        "from the terminal, or with --from-scratch writes an empty skeleton and a "
        "created-empty report (FR-AUTHOR-29); the authoring screens are future console work "
        "(FR-CONSOLE-46), so a developer runs the command in the terminal until they are built"
    ),
    "author review": (
        "walks the teacher through every unresolved item of a draft before the package can be "
        "built; the authoring screens are future console work (FR-CONSOLE-46), so the walk "
        "runs in the terminal until they are built"
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
    "author draft": (
        "runs the authoring draft over teacher-authored documents from the terminal, or "
        "starts one from an empty skeleton with --from-scratch --title (FR-AUTHOR-29); the "
        "console's authoring screens are future work (FR-CONSOLE-46), and a developer uses "
        "the command to produce the draft spec and report without a browser"
    ),
    "author review": (
        "walks a draft's unresolved items to resolution ahead of the package build from the "
        "terminal; the console's authoring screens are future work (FR-CONSOLE-46), and a "
        "developer uses the command to finish a review when no console session is open"
    ),
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


#: The console-redesign delta's capability parity (`FR-CONSOLE-41`, design delta §1.2 and
#: §3.2.2): every capability the delta adds to the console, each with its **terminal
#: counterpart** — the `aeh` command that opens the same door — or the statement that the
#: console is the capability's only surface, with the reason. The design's rule is that the
#: census is updated in the same change that adds the actions; #760 added the eleven without
#: touching this module, so the decision rows land here with #767, and a capability added
#: later without a row is the same silent gap an unlisted subcommand is.
#:
#: Keys are the capability names as the design's §3.2.2 table declares them; where the
#: shipped surface carries a capability as a read rather than a control row (the two
#: exports, synchronous file deliveries like the existing results export), the row says
#: which read carries it. The `author draft` / `author review` CLI rows above keep their
#: present-and-unavailable posture (`FR-CONSOLE-46`, TC-CONSOLE-58's oracle) — this table is
#: the other direction: the console capability and its terminal door, not the command's row.
CONSOLE_CAPABILITY_PARITY: dict[str, str] = {
    "draft package from documents": (
        "the `aeh author draft` command opens the same AuthoringService door (ADR-45) from "
        "the terminal; the console stages the same documents as a job (ADR-47) and renders "
        "the progress the command does not have"
    ),
    "answer authoring review": (
        "`aeh author review` walks the same unresolved items against the same draft file; "
        "the console answers one item at a time over the same AuthoringService review call, "
        "so the draft on disk is current under either surface (FR-AUTHOR-16)"
    ),
    "edit draft package": (
        "console-only by design: the structured editor (add/edit/reorder/delete through "
        "`aeh.author`'s validate/persist path) has no terminal counterpart — `aeh author "
        "review` resolves review items but applies no structural edit, and the console never "
        "sends the TOML text a terminal round-trip would need"
    ),
    "approve draft package": (
        "`aeh package build` opens the same M-PKG build and publish door; the console's "
        "approval adds the placeholder gate (FR-PKG-28) around the same build, so a draft "
        "the console refuses is one the command refuses too"
    ),
    "create class": (
        "the same cohort-ledger door `aeh cohort create` opens (ADR-48: a class is the "
        "ledger in a roster-only state); the command creates the ledger without the class "
        "vocabulary, which is the console's distinction over one storage concept"
    ),
    "create cohort from class": (
        "console-only: copying a class ledger into a grading cohort with consent state "
        "carried has no terminal command — `aeh cohort create` builds a cohort from a roster "
        "file, never from another ledger (ADR-48)"
    ),
    "import roster file": (
        "`aeh cohort create` and `aeh cohort add-students` load the same roster files "
        "through the same validation; the console's import adds the preview-before-commit "
        "(R7) the commands do not render"
    ),
    "update configuration": (
        "console-only by design: the guided write goes through M-CONF's update write path "
        "(FR-CONF-34) — validated, atomic, teacher-editable subset only — while the terminal "
        "path is editing the configuration file by hand, which is exactly what the guided "
        "form exists to replace"
    ),
    "export results workbook": (
        "console-only for now: `aeh results export` writes the marks CSV and one PDF per "
        "student, and the workbook (.xlsx via openpyxl, ADR-49) rides the console's "
        "`results workbook` read (FR-CONSOLE-58) until the command grows the format"
    ),
    "export readable package": (
        "console-only by design: the readable package PDF is the deterministic stdlib writer "
        "(ADR-49 — no DOCX writer) rendered for the teacher through the `readable package "
        "export` read (FR-CONSOLE-59), while `aeh package export` writes the spec TOML a "
        "developer diffs; the two exports answer different questions"
    ),
    "cancel job": (
        "console-only: authoring jobs cancel cooperatively at a step boundary (CT-AUTHOR-24, "
        "CT-CONSOLE-35) inside the console's own job registry (ADR-47, console memory), and "
        "a run's cancel is the existing `pause/resume` control row — the terminal has no job "
        "registry to cancel into"
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

    A debugging-only command the parser does not have *yet* is still served as a row:
    the listing — the reason and the what-it-is-for line — is the console's decision, made
    when the tables were amended, and the help section must show it even before the command
    is registered. The census gap for the unregistered name stays in `gaps` until the
    parser catches up, so a declared command the parser will never have cannot hide behind
    its row.
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
        # A declared debugging-only command is served even while unregistered: the listing is
        # the decision (FR-CONSOLE-46's present-and-unavailable pattern), and the reason and
        # purpose rows above are what the help section renders. The gap stays until the
        # parser registers the command, so the row can never hide a stale name.
        reason = DEBUGGING_ONLY_COMMANDS.get(name)
        if reason is not None:
            commands.append({
                "command": name,
                "purpose": CLI_COMMAND_PURPOSE.get(name, ""),
                "surface": "debugging-only",
                "reason": reason,
            })
    return {
        "rule": ("the console is the operator surface; the CLI is the debugging surface "
                 "(NFR-CONSOLE-09). Every `aeh` subcommand either has a console path or is "
                 "listed here as debugging-only with the reason."),
        "commands": commands,
        "gaps": gaps,
        # The other half of FR-CONSOLE-41: the console-redesign delta's own capabilities, each
        # with its terminal counterpart or the console-only statement. Rendered beside the
        # command rows so the help section answers both directions of the parity question.
        "console_capabilities": {
            "rule": ("every capability the console-redesign delta adds to the console has a "
                     "terminal counterpart — the `aeh` command that opens the same door — or "
                     "is stated here as the console's only surface, with the reason "
                     "(FR-CONSOLE-41)."),
            "capabilities": [
                {"capability": name, "parity": parity}
                for name, parity in sorted(CONSOLE_CAPABILITY_PARITY.items())
            ],
        },
    }


__all__ = [
    "CLI_COMMAND_PURPOSE",
    "CLI_CONSOLE_PATHS",
    "CONSOLE_CAPABILITY_PARITY",
    "DEBUGGING_ONLY_COMMANDS",
    "cli_leaf_commands",
    "parity_inventory",
]
