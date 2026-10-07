"""`TS-148` (issue #633) — `TC-CONSOLE-54`: the CLI/console parity census (`FR-CONSOLE-41`,
`NFR-CONSOLE-09`). Operator-requirements test plan §5.6, rung 1; §4 rule 5: "console parity is a
census, not a vibe … when a subcommand is added later, the census fails until someone decides —
that failure is the feature."

| Case | What is asserted |
|---|---|
| census | the `aeh` parser's leaf subcommands, enumerated in-process, each appear **exactly once** in the console's inventory: a console path that is a real `API_ROUTES` row, or the debugging-only help section with a reason; the inventory names nothing the parser lacks |
| doc arm (bounded) | each debugging-only entry says what the command is *for* (a sentence, not a label) — NFR-CONSOLE-09's "the console's help explains what each CLI command is for" |
| control: planted subcommand | the census oracle itself, against a parser with one extra subcommand: it reports that subcommand as silently unrepresented (green today) |
| control: walk | the leaf walk reaches the nested groups (`cohort create`, `package build`), not just the top level (green today) |

**Landed by #632**: the inventory lives in `aeh.console.parity` (`CLI_CONSOLE_PATHS`,
`DEBUGGING_ONLY_COMMANDS`); the two names were invented in `tests/support/console_api_vocabulary.py`
before the implementation existed, and the implementation adopted them.

**Not implemented as specified, stated:** NFR-CONSOLE-09's documentation rewrite (onboarding
and manuals written to the console-primary split) is prose quality, judged by #632's reviewer;
the case bounds the doc arm to the inventory's own reasons.
"""

from __future__ import annotations

import argparse

import pytest

from tests.support.console_api_vocabulary import (
    DEBUGGING_ONLY,
    PARITY_ISSUE,
    PARITY_PATHS,
    ROUTE_TABLE,
    cli_leaf_commands,
    parity_census,
)
from tests.support.impl import CONSOLE_MODULE, require


def _parser():
    from aeh.pipeline.cli import _build_parser

    return _build_parser()


def test_tc_console_54_every_aeh_subcommand_has_a_console_path_or_a_debugging_only_reason():
    routes, console_paths, debugging_only = require(
        CONSOLE_MODULE, ROUTE_TABLE, PARITY_PATHS, DEBUGGING_ONLY, issue=PARITY_ISSUE)
    leaves = cli_leaf_commands(_parser())
    problems = parity_census(leaves, dict(console_paths), dict(debugging_only), list(routes))
    assert not problems, (
        "TC-CONSOLE-54: the parity inventory is not an exact census of the `aeh` parser "
        "(FR-CONSOLE-41):\n  " + "\n  ".join(problems))


def test_tc_console_54_the_teacher_operations_have_console_paths_not_debugging_listings():
    """FR-CONSOLE-41 names the operations a teacher needs from the console: cohort creation and
    roster loading, loading papers, run start, recover, results and export (`cohort show` is a
    read the console's screens already answer, so either listing is a decision). Listing those as debugging-only would pass
    the bare census and defeat the requirement."""
    console_paths, debugging_only = require(
        CONSOLE_MODULE, PARITY_PATHS, DEBUGGING_ONLY, issue=PARITY_ISSUE)
    leaves = cli_leaf_commands(_parser())
    must_be_console = [leaf for leaf in leaves
                       if leaf.split()[0] in {"cohort", "run", "recover", "ingest", "results"}
                       and leaf != "cohort show"]
    assert must_be_console, "fixture: the parser has none of the teacher operations"
    demoted = [leaf for leaf in must_be_console if leaf not in dict(console_paths)]
    assert not demoted, (
        f"TC-CONSOLE-54: teacher operations without a console path: {demoted} "
        f"(debugging-only: {sorted(k for k in demoted if k in dict(debugging_only))})")


def test_tc_console_54_control_a_planted_subcommand_fails_the_census():
    """The oracle's negative control: an inventory exact for the parser fails the moment a
    subcommand is added without a decision."""
    parser = argparse.ArgumentParser(prog="aeh")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run")
    group = sub.add_parser("cohort").add_subparsers(dest="cohort_command")
    group.add_parser("create")
    routes = [type("R", (), {"method": "POST", "path": "/api/v1/actions/start-run",
                             "control": "start run"})()]
    paths = {"run": "POST /api/v1/actions/start-run"}
    debug = {"cohort create": "for a developer scripting a class set-up without the browser"}
    assert parity_census(cli_leaf_commands(parser), paths, debug, routes) == []

    sub.add_parser("frobnicate")
    problems = parity_census(cli_leaf_commands(parser), paths, debug, routes)
    assert any("aeh frobnicate" in p and "silently unrepresented" in p for p in problems), problems

    # A label that is not a reason, a route the table lacks, a double listing, a stale name.
    bad = parity_census(
        ["run", "cohort create"], {"run": "POST /api/v1/nope", "cohort create": "GET /x"},
        {"cohort create": "debug", "gone": "a command that no longer exists anywhere"}, routes)
    joined = "\n".join(bad)
    assert "not a row of API_ROUTES" in joined
    assert "listed twice" in joined
    assert "no reason" in joined
    assert "aeh gone" in joined


def test_tc_console_54_control_the_walk_reaches_nested_subcommands():
    leaves = cli_leaf_commands(_parser())
    assert "cohort create" in leaves and "package build" in leaves and "run" in leaves, leaves
    assert "cohort" not in leaves, "a group is not a leaf"
