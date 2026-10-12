"""`TC-PIPE-37` (FR-PIPE-10, P0) — the `aeh author` subcommands register (#712, the
package-authoring test plan §5.3; design delta §3.3, §3.1).

Written ahead of #695, keyed `#695 cli registration` in `WRITTEN_AHEAD_BLOCKERS`. LANDED
(#695): the `author` group is registered with both subcommands and the file re-ran green at
the landing, so the marker came off — never the test.

Rung 3 (console): the CLI texts, driven headless through `aeh.pipeline.cli.main` — the same
in-process entry the TC-PIPE-27 package-build cases drive. `main` returns the exit code
rather than raising (`CT-PIPE-01`), and argparse's `--help` paths raise `SystemExit(0)`
in-process, which the arms read through `capsys`. Isolation is the plan's, per case:
`HARNESS_FIXTURE_DIR` binds the recorded provider (`CT-PROV-10`) so no arm can reach a live
model even by accident, the autouse socket guard is armed throughout, and the final
assertion is that it recorded zero attempts — no live calls in this suite.

**The blocker's target, recorded because the issue's note names a trap.** The note said
`aeh.pipe:_build_parser`; that module does not exist (the registration site today is
`aeh.pipeline.cli`), and `_build_parser` itself landed with #364 — a `symbol` key on it
resolves immediately, which is the resolved-blocker situation the registry exists to
prevent. #695's acceptance criteria mandate no new Python name either ("registered in
`_build_parser`'s `author` subcommand group, following the existing `package` group
pattern" — the house group handlers admit several plausible names, `_author_command`,
`_author_draft_command`, ...), so a symbol key would bet on an invented name with the late
direction: never fires, and a P0 case sits outside the gate forever. The `#635`/`#638`
precedent applies — when a story ships a behaviour with no mandated name, the key probes
the behaviour itself: `blocker_is_resolved` builds the parser and exits 0 exactly when the
`author` group carries both `draft` and `review`, the thing #695 is the first to ship. No
other open story touches the `aeh` subcommand table, so nothing can ship it earlier; at
resolution, re-check the case green before unmarking — never on the notice alone.

Disclosed fixture assumptions, to reconcile at the landing (the assertions stay the plan's):
- A complete draft is a spec in M-PKG's vocabulary carrying no sentinel: design delta §3.1's
  dependency table gives M-AUTHOR "the spec vocabulary (FR-PKG-27's export shape)", and §3.1's
  flow ends `aeh package build --spec draft`. The ready arm's draft is therefore the sample
  spec `ps9-forces-01.package.toml`, which passes every structural check today (TC-PIPE-27
  builds and publishes it).
- The items-remaining arm pins the exit code only. The CLI walk is interactive
  (`review(answers=None)`), so under pytest's captured stdin it cannot proceed, and the
  "lists the items that remain" output distinction is `TC-AUTHOR-24`'s library-level oracle
  (rung 1, scripted answers). What this arm holds is the code — items remain → 1 — and the
  ready wording's absence: the build command prints only when the draft is ready.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from aeh.pipeline import cli
from tests.support.impl import NotImplementedYet

REPO = Path(__file__).resolve().parents[3]
SAMPLE_SPEC = REPO / "docs" / "live-tests" / "config" / "ps9-forces-01.package.toml"
DEV_CI_CONFIG = REPO / "docs" / "live-tests" / "config" / "live-test.dev-ci.toml"

# FR-PIPE-10: "the `draft` help shall state that the package publishes only through
# `aeh package build` after review". FR-PIPE-10 names the surface — the draft's own help,
# which `aeh author draft --help` renders — so the oracle is that contiguous statement on
# that surface. The only tolerance is quoting style: backticks are stripped before the
# match, since the design's own sentence quotes the command name in them.
PUBLISH_WORDING = "publishes only through aeh package build after review"


def _author_group() -> "dict[str, object]":
    """The `author` group's subcommand choices, or the designed red naming #695.

    The require()-style gate, and the first thing the test body does: a missing
    registration is `NotImplementedYet` — an `AssertionError` naming the blocker — never a
    collection error or a bare argparse complaint, so the failure states its cause (the
    `tests/support/impl.py` doctrine).
    """
    parser = cli._build_parser()
    top = next(action for action in parser._actions
               if isinstance(action, argparse._SubParsersAction) and action.dest == "command")
    author = top.choices.get("author")
    if author is None:
        raise NotImplementedYet(
            "aeh.pipeline.cli._build_parser registers no `author` subcommand group yet "
            "(blocked on #695). This test is written ahead of its implementation (test plan "
            "§8.2) and is expected to fail until #695 lands.")
    inner = next((action for action in author._actions
                  if isinstance(action, argparse._SubParsersAction)), None)
    missing = {"draft", "review"} - (set(inner.choices) if inner is not None else set())
    if missing:
        raise NotImplementedYet(
            f"aeh.pipeline.cli registers `author` but not {sorted(missing)} yet (blocked on "
            "#695). This test is written ahead of its implementation (test plan §8.2).")
    return dict(inner.choices)


def test_tc_pipe_37_the_author_subcommands_register_with_the_documented_texts_and_exits(
        tmp_path, monkeypatch, capsys, network_guard):
    """The plan's oracle, in order: the registration gate first (the designed red while #695
    is open), then the exact help texts, then the exit codes — 0 and 1 reachable from the
    documented paths, 2 left to argparse alone, and no new exit constant anywhere."""
    _author_group()  # <- the require-style gate; everything below runs only once it resolves.

    # The recorded provider (CT-PROV-10): every arm's refusal precedes any model call, and
    # nothing in this suite should call out at all — asserted positively at the end.
    (tmp_path / "recorded-fixtures").mkdir()
    monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(tmp_path / "recorded-fixtures"))

    # --- `aeh --help`: the author group is listed ---------------------------------------------
    with pytest.raises(SystemExit) as top:
        cli.main(["--help"])
    assert top.value.code == 0
    assert "author" in capsys.readouterr().out, (
        "TC-PIPE-37: `aeh --help` does not list the `author` subcommand (FR-PIPE-10)")

    # --- `aeh author --help`: both subcommands listed -------------------------------------------
    with pytest.raises(SystemExit) as author:
        cli.main(["author", "--help"])
    assert author.value.code == 0
    author_help = capsys.readouterr().out
    assert "draft" in author_help and "review" in author_help, (
        f"TC-PIPE-37: `aeh author --help` must list both subcommands (FR-PIPE-10):\n{author_help}")

    # --- the publish-only-after-review wording ---------------------------------------------------
    with pytest.raises(SystemExit) as draft:
        cli.main(["author", "draft", "--help"])
    assert draft.value.code == 0
    draft_help = capsys.readouterr().out
    assert PUBLISH_WORDING in draft_help.replace("`", ""), (
        "TC-PIPE-37: the draft help does not state that the package publishes only through "
        "`aeh package build` after review (FR-PIPE-10):\n" + draft_help)

    # --- exit 0: a ready draft prints the build command (FR-AUTHOR-17, FR-PIPE-10) ---------------
    ready = tmp_path / "PS9-FORCES-01.package.draft.toml"
    ready.write_text(SAMPLE_SPEC.read_text(encoding="utf-8"), encoding="utf-8")
    assert cli.main(["author", "review", "--draft", str(ready)]) == 0, (
        "TC-PIPE-37: review of a ready draft — zero placeholders, every structural check "
        "passing — must exit 0 (FR-AUTHOR-17)")
    assert "aeh package build" in capsys.readouterr().out, (
        "TC-PIPE-37: the ready exit says so with the build command (FR-AUTHOR-17)")

    # --- exit 1: items remain — the same code, and never the ready wording ------------------------
    partial = tmp_path / "PS9-FORCES-01-partial.package.draft.toml"
    partial.write_text(
        SAMPLE_SPEC.read_text(encoding="utf-8").replace(
            'key = "C"', 'key = "<<PLACEHOLDER: key>>"', 1),
        encoding="utf-8")
    assert cli.main(["author", "review", "--draft", str(partial)]) == 1, (
        "TC-PIPE-37: review while items remain must exit 1 (FR-AUTHOR-17)")
    assert "aeh package build" not in capsys.readouterr().out, (
        "TC-PIPE-37: the build command is the ready wording; a draft with items remaining "
        "must not print it (FR-AUTHOR-17)")

    # --- exit 1: a missing draft file, with the reason --------------------------------------------
    missing = tmp_path / "no-such-draft.toml"
    assert cli.main(["author", "review", "--draft", str(missing)]) == 1, (
        "TC-PIPE-37: review of a missing draft file must exit 1 (FR-PIPE-10, §3.1's exit "
        "convention)")
    assert missing.name in capsys.readouterr().err, (
        "TC-PIPE-37: the missing-draft refusal's reason names the file (FR-PIPE-10)")

    # --- exit 1: an unreadable document, and nothing written ---------------------------------------
    out_dir = tmp_path / "never-written"
    ghost = tmp_path / "no-such-test-paper.pdf"
    assert cli.main(["author", "draft", "--config", str(DEV_CI_CONFIG),
                     "--docs", str(ghost), "--out", str(out_dir)]) == 1, (
        "TC-PIPE-37: a draft whose only document is unreadable exits 1 (FR-AUTHOR-13, "
        "FR-PIPE-10)")
    error_text = capsys.readouterr().err
    assert "AuthoringInputError" in error_text and ghost.name in error_text, (
        "TC-PIPE-37: the unreadable-document refusal is an AuthoringInputError naming the "
        f"document (FR-AUTHOR-13):\n{error_text}")
    assert not out_dir.exists() or not any(out_dir.iterdir()), (
        "TC-PIPE-37: the refused draft writes nothing (FR-AUTHOR-13)")

    # --- exit 2 stays argparse's alone --------------------------------------------------------------
    with pytest.raises(SystemExit) as usage:
        cli.main(["author", "bogus"])
    assert usage.value.code == 2, (
        "TC-PIPE-37: exit 2 is argparse's usage-error code alone (FR-PIPE-10)")
    # And the exit-code contract stays the module's three constants — no new code anywhere.
    assert {cli.EXIT_OK, cli.EXIT_ERROR, cli.EXIT_PAUSED} == {0, 1, 3}, (
        "TC-PIPE-37: no new exit code is introduced (FR-PIPE-10, §3.1's exit convention)")

    # --- isolation, positively: zero egress across every arm ----------------------------------------
    network_guard.assert_no_network()