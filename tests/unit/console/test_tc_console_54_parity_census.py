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

**TC-CONSOLE-58 (package-authoring delta, TS-167, #716)** re-runs the same census with the
authoring module present. `aeh author draft` / `aeh author review` arrive registered (#695,
TS-161) before the console screens exist, and FR-CONSOLE-46 holds the parity door open by
listing them **present-and-unavailable** — the FR-CONSOLE-34 pattern — with the reason that the
authoring screens are future console work, so the census passes without inventing a console
path this delta does not build. **#700 made that listing** (a data edit to
`aeh/console/parity.py`, no new symbol): the two author commands are listed with that reason in
`DEBUGGING_ONLY_COMMANDS`, `CLI_COMMAND_PURPOSE` carries their what-it-is-for lines, and
`parity_inventory` serves the declared rows even while the parser does not register the
commands yet — the census gap for the unregistered names stays until #695 catches up. While
the listing was missing, each case raised `NotImplementedYet` naming #700 before it asserted
anything; the marker came off when the story landed. The unmarked control plants the `author`
group exactly as #695 registers it and proves the census discriminates: registered but
unlisted, both author commands are reported as silently unrepresented.

**Not implemented as specified, stated:** NFR-CONSOLE-09's documentation rewrite (onboarding
and manuals written to the console-primary split) is prose quality, judged by #632's reviewer;
the case bounds the doc arm to the inventory's own reasons.
"""

from __future__ import annotations

import argparse
import re

import pytest

from tests.support.console_api_vocabulary import (
    DEBUGGING_ONLY,
    PARITY_ISSUE,
    PARITY_PATHS,
    ROUTE_TABLE,
    cli_leaf_commands,
    parity_census,
)
from tests.support.impl import CONSOLE_MODULE, NotImplementedYet, require


def _parser():
    from aeh.pipeline.cli import _build_parser

    return _build_parser()


# Waits on #695 with the `"#695 cli registration"` blocker: the parity inventory lists
# `aeh author draft`/`aeh author review` (added by #700) while the parser does not have
# the `author` group yet, so the exact-census assertion is red until it lands.
@pytest.mark.writtenahead
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


# ===========================================================================================
# TC-CONSOLE-58 (package-authoring delta, TS-167, #716; FR-CONSOLE-46, FR-CONSOLE-41,
# FR-CONSOLE-34) — the census with the authoring module present.
# ===========================================================================================
#
# `aeh author draft` / `aeh author review` are CLI first (#695, TS-161); the console screens
# are explicitly future work (design delta §3.5), and FR-CONSOLE-46 keeps the parity census
# honest in between: the author commands are listed present-and-unavailable, with the reason
# that the authoring screens are future console work — never with an invented console path.
# The listing is DATA in `aeh/console/parity.py` (its census tables), not a new symbol; #700
# landed it and the marker came off. The `_author_listing` guard below stays as the oracle's
# own tripwire: if the rows are ever dropped from the tables, the cases fail naming the data
# edit that is missing rather than reporting a false pass.

#: The author leaves, as FR-CONSOLE-46 names them.
AUTHOR_LEAVES = ("author draft", "author review")


def _parser_with_author_group():
    """The `aeh` parser as #695 (TS-161) registers it: an `author` group with `draft` and
    `review`, following the existing `package` group pattern (`TC-PIPE-37`'s acceptance).
    Planted here so the census cases below run against the author commands even before #695
    merges — the census discrimination does not wait on the CLI story. Once #695 has
    registered the real group, the plant stands down and the census walks the real
    registration: re-adding a duplicate `author` would raise `ValueError: conflicting
    subparser`, and the planted shape and the registered one are the same two leaves."""
    parser = _parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    if "author" in sub.choices:
        return parser
    author = sub.add_parser("author")
    author_sub = author.add_subparsers(dest="author_command")
    author_sub.add_parser("draft")
    author_sub.add_parser("review")
    return parser


def _author_listing(leaf: str, console_paths: dict, debugging_only: dict) -> str:
    """The row's present-and-unavailable listing, or the `NotImplementedYet` tripwire.

    Checks the *wrong* listing first — a console path would make the census fail on the
    route-table check (`FR-CONSOLE-46`: "without inventing a console path this delta does not
    build") — and only then reports a missing row: the listing is data in
    `aeh/console/parity.py` (#700's amendment), and the guard names that data edit if the
    rows are ever dropped, so the cases fail loudly instead of passing on a hollow table.
    """
    assert leaf not in console_paths, (
        f"TC-CONSOLE-58: `aeh {leaf}` is listed as a console path, but FR-CONSOLE-46 holds the "
        "console screens as future work and forbids inventing a console path this delta does "
        "not build — present-and-unavailable is the debugging-only-style listing with the "
        "reason, the FR-CONSOLE-34 pattern.")
    reason = debugging_only.get(leaf)
    if reason is None:
        raise NotImplementedYet(
            f"`aeh {leaf}` is not listed in the parity census tables yet (blocked on #700, the "
            "console census): FR-CONSOLE-46's present-and-unavailable listing — the reason that "
            "the authoring screens are future console work — is data in aeh/console/parity.py's "
            "census tables, which #700 adds. This test is written ahead of that data edit "
            "(test plan §8.2) and is expected to fail until it lands."
        )
    return reason


def _assert_reason_names_future_console_work(leaf: str, reason: str) -> None:
    """FR-CONSOLE-46's clause: the reason is "that the authoring screens are future console
    work". Asserted on its substance, not on one prose choice: the authoring command and the
    console must be named, and the future-work posture must be stated — by "future" or any
    honest way of saying the same thing ("later", "planned", "not built yet"), since a
    faithful reason that words it differently is not a violation."""
    lowered = str(reason).lower()
    for word in ("author", "console"):
        assert word in lowered, (
            f"TC-CONSOLE-58: `aeh {leaf}`'s listing reason does not say the authoring screens "
            f"are future console work (FR-CONSOLE-46) — no {word!r} in: {reason!r}")
    cues = ("future", "later", "upcoming", "planned", "yet", "not built", "not implemented",
            "not part of")
    assert any(cue in lowered for cue in cues), (
        f"TC-CONSOLE-58: `aeh {leaf}`'s listing reason does not say the authoring screens are "
        f"future console work (FR-CONSOLE-46) — no future-work statement in: {reason!r}")


def _assert_purpose_line(leaf: str, purpose: dict) -> None:
    """`NFR-CONSOLE-09`'s other half reaches the author rows too: every leaf the parser has is
    named in `CLI_COMMAND_PURPOSE`, and #700's amendment added the author rows to it."""
    line = purpose.get(leaf)
    assert line, (
        f"TC-CONSOLE-58: `aeh {leaf}` has no line in CLI_COMMAND_PURPOSE saying what it is for "
        f"(NFR-CONSOLE-09; #700's acceptance criteria update that table with the author rows)")
    assert len(re.findall(r"[A-Za-z]{2,}", str(line))) >= 4, (
        f"TC-CONSOLE-58: `aeh {leaf}`'s purpose line is a label, not a sentence: {line!r}")


def test_tc_console_58_author_draft_is_listed_present_and_unavailable():
    routes, console_paths, debugging_only = require(
        CONSOLE_MODULE, ROUTE_TABLE, PARITY_PATHS, DEBUGGING_ONLY, issue=PARITY_ISSUE)
    purpose = require(CONSOLE_MODULE, "CLI_COMMAND_PURPOSE", issue=PARITY_ISSUE)
    leaf = "author draft"
    reason = _author_listing(leaf, dict(console_paths), dict(debugging_only))
    _assert_reason_names_future_console_work(leaf, reason)
    _assert_purpose_line(leaf, dict(purpose))
    # The listing is a real census row, not a free-floating string: the live census over the
    # tables must accept it (census equality is the next case's whole oracle; this is the
    # per-row slice of it).
    leaves = cli_leaf_commands(_parser_with_author_group())
    problems = parity_census(leaves, dict(console_paths), dict(debugging_only), list(routes))
    row_problems = [p for p in problems if f"aeh {leaf}" in p]
    assert not row_problems, (
        f"TC-CONSOLE-58: `aeh {leaf}` is listed yet the census still reports it (FR-CONSOLE-41):\n  "
        + "\n  ".join(row_problems))


def test_tc_console_58_author_review_is_listed_present_and_unavailable():
    routes, console_paths, debugging_only = require(
        CONSOLE_MODULE, ROUTE_TABLE, PARITY_PATHS, DEBUGGING_ONLY, issue=PARITY_ISSUE)
    purpose = require(CONSOLE_MODULE, "CLI_COMMAND_PURPOSE", issue=PARITY_ISSUE)
    leaf = "author review"
    reason = _author_listing(leaf, dict(console_paths), dict(debugging_only))
    _assert_reason_names_future_console_work(leaf, reason)
    _assert_purpose_line(leaf, dict(purpose))
    leaves = cli_leaf_commands(_parser_with_author_group())
    problems = parity_census(leaves, dict(console_paths), dict(debugging_only), list(routes))
    row_problems = [p for p in problems if f"aeh {leaf}" in p]
    assert not row_problems, (
        f"TC-CONSOLE-58: `aeh {leaf}` is listed yet the census still reports it (FR-CONSOLE-41):\n  "
        + "\n  ".join(row_problems))


def test_tc_console_58_the_census_passes_once_the_author_commands_are_listed():
    """The case's oracle, exact: census equality. The parser is the planted one (`_parser_with_
    author_group`), so the oracle is satisfiable by the listing alone — #695 registering the
    same group changes nothing here — and with #700's rows landed, the census with the author
    commands present reports no problems at all, the way the existing TC-CONSOLE-54 census
    does for every other leaf."""
    routes, console_paths, debugging_only = require(
        CONSOLE_MODULE, ROUTE_TABLE, PARITY_PATHS, DEBUGGING_ONLY, issue=PARITY_ISSUE)
    console_paths, debugging_only = dict(console_paths), dict(debugging_only)
    for leaf in AUTHOR_LEAVES:
        # The tripwire: a dropped row fails here, naming the data edit that is missing,
        # rather than letting the census-equality assert below pass on a hollow table.
        _author_listing(leaf, console_paths, debugging_only)
    problems = parity_census(cli_leaf_commands(_parser_with_author_group()),
                             console_paths, debugging_only, list(routes))
    assert problems == [], (
        "TC-CONSOLE-58: the parity census is not exact with the author commands listed "
        "present-and-unavailable (FR-CONSOLE-46, FR-CONSOLE-41):\n  " + "\n  ".join(problems))


def test_tc_console_58_control_the_census_fails_while_the_author_commands_are_registered_but_unlisted():
    """The negative control, and the feature's mechanism: with `author` registered but
    unlisted, the census FAILS — that failure is what forces the listing (FR-CONSOLE-34's
    pattern, stated in the plan's §4 rule for the census). The `author` group is planted
    exactly as #695 registers it, and any author rows are stripped from the tables' copy —
    today there are none to strip; after #700 there are, and stripping is what keeps this
    control proving the discrimination *while unlisted* rather than turning red once the
    listing lands. Green today and after #700 alike; never marked."""
    routes, console_paths, debugging_only = require(
        CONSOLE_MODULE, ROUTE_TABLE, PARITY_PATHS, DEBUGGING_ONLY, issue=PARITY_ISSUE)
    unlisted_paths = {k: v for k, v in dict(console_paths).items()
                      if not k.startswith("author")}
    unlisted_debug = {k: v for k, v in dict(debugging_only).items()
                      if not k.startswith("author")}
    problems = parity_census(cli_leaf_commands(_parser_with_author_group()),
                             unlisted_paths, unlisted_debug, list(routes))
    for leaf in AUTHOR_LEAVES:
        assert any(f"aeh {leaf}" in p and "silently unrepresented" in p for p in problems), (
            f"TC-CONSOLE-58 control: with `aeh {leaf}` registered but unlisted, the census must "
            f"report it as silently unrepresented — that failure is the feature forcing the "
            f"listing (FR-CONSOLE-34's pattern); got: {problems!r}")
