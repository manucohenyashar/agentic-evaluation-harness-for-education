"""`TC-AUTHOR-16` (FR-AUTHOR-13, CT-AUTHOR-09, P0) — the fail-fast matrix (TS-155, #707;
test plan §5.1 row 16; design delta §3.1's error table).

Case: each refusal in the matrix raises the correct type **naming the failing document,
before any provider call, with zero artifacts written**; the CLI limb additionally exits 1 —
M-PIPE's `EXIT_ERROR` (§3.1's exit convention). The matrix, per the plan:

1. **Corrupt PDF** — an unreadable document refuses as `AuthoringInputError` naming it.
2. **Zero text with transcribe off** — AF-10 under `HARNESS_AUTHOR_TRANSCRIBE=off` refuses
   as `AuthoringInputError` naming document and page (TC-AUTHOR-03's refusal, in the matrix).
3. **Empty panel** — a chain of zero models refuses as `ConfigurationError` before any call.
4. **CLI exit 1** — the first limb through `aeh author draft` exits `EXIT_ERROR`, the error
   naming `AuthoringInputError` and the document on stderr, nothing written.

The provider boundary in every library limb is a scripted tripwire with no replies
programmed (`tests.support.taxonomy.PerJudgeScript`): any call at all fails loudly, so
"before any call" is asserted by the run surviving with the calls list empty.

Written ahead of #690 ("the draft front door"), keyed in `WRITTEN_AHEAD_BLOCKERS` as a
`command` probe on the §3.1 surface **plus #695's `author draft` registration** — limb 4
drives the CLI, whose registration is #695's deliverable, so a key on the surface alone would
fire at #690 and leave the case red inside `TEST_CMD` on #695 (the early-fire direction the
registry exists to prevent). See the registry entry's comment block. LANDED (#695): the
registration resolved and the matrix re-ran green at the landing, so the marker came off.

Rung 1, guards first (#689's module surface, the committed corpus limbs, #695's registration).

Disclosed overlap: limb 4's unreadable-document exit is also `TC-PIPE-37`'s last arm
(`tests/unit/pipe/test_tc_pipe_37_author_subcommands.py`) — the same behaviour read from the
M-PIPE side. This file keeps its limb because the plan's matrix pins it here too; the two
assertions are the same oracle, not two suites for one requirement.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from aeh.conf import ConfigurationError
from aeh.pipeline import cli
from tests.support.author_vocabulary import (
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    DEV_CI_CONFIG,
    af,
    chain_from_config,
    make_service,
)
from tests.support.impl import NotImplementedYet, require, require_path
from tests.support.taxonomy import PerJudgeScript

CASE = "TC-AUTHOR-16"

#: The refuse-on-first-call tripwire: no replies programmed, so a single provider call
#: raises AssertionError naming the unscripted call.
TRIPWIRE_SCRIPTS: dict = {}


def _author_draft_registered() -> None:
    """The `author draft` subcommand exists, or the designed red naming #695.

    The require()-style gate for limb 4 (the same shape `TC-PIPE-37`'s file uses): a missing
    registration is `NotImplementedYet` — an `AssertionError` naming the blocker — never a
    bare argparse complaint.
    """
    top = next(action for action in cli._build_parser()._actions
               if isinstance(action, argparse._SubParsersAction) and action.dest == "command")
    author = top.choices.get("author")
    inner = next((action for action in author._actions
                  if isinstance(action, argparse._SubParsersAction)), None) if author else None
    if inner is None or "draft" not in inner.choices:
        raise NotImplementedYet(
            "aeh.pipeline.cli registers no `author draft` subcommand yet (blocked on #695). "
            "This test is written ahead of its implementation (test plan §8.2) and is "
            "expected to fail until #695 lands.")


def _guards() -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)
    # The surface guard: `require` with names returns the symbols (a tuple), not the module,
    # so the module the limbs drive comes from the zero-names call above and this call only
    # asserts the §3.1 surface plus the refusal type exists (the two-call pattern the landed
    # sibling files use).
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, "AuthoringInputError", issue=AUTHOR_ISSUE)
    require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    require_path(af("AF-10"), "the AF-10 authored fixture", issue=CORPUS_ISSUE)
    return author


def _assert_nothing_written(output_dir: Path) -> None:
    assert not output_dir.exists() or not any(output_dir.iterdir()), (
        f"{CASE}: the refused draft writes nothing (FR-AUTHOR-13)")


def test_tc_author_16_a_corrupt_pdf_refuses_as_authoring_input_error(
        tmp_path, network_guard):
    """Limb 1: an unreadable document refuses as `AuthoringInputError` naming it, before any
    call, writing nothing."""
    author = _guards()
    corrupt = tmp_path / "corrupt-test-paper.pdf"
    corrupt.write_bytes(b"%PDF-1.7\n%this file is truncated garbage \x00\xff not a pdf\n")

    tripwire = PerJudgeScript(scripts=TRIPWIRE_SCRIPTS)
    output_dir = tmp_path / "out-corrupt"
    with pytest.raises(author.AuthoringInputError) as raised:
        make_service(author, chain_from_config(), tripwire).draft(
            documents=[corrupt], output_dir=output_dir)

    message = str(raised.value)
    assert corrupt.name in message, (
        f"{CASE}: the refusal must name the failing document, got: {message}")
    assert tripwire.calls == [], (
        f"{CASE}: the refusal must fire before any provider call, got {len(tripwire.calls)}")
    _assert_nothing_written(output_dir)
    network_guard.assert_no_network()


def test_tc_author_16_zero_text_with_transcribe_off_refuses(
        tmp_path, monkeypatch, network_guard):
    """Limb 2: AF-10 under `transcribe=off` refuses as `AuthoringInputError` naming document
    and page (TC-AUTHOR-03's refusal, inside the matrix)."""
    author = _guards()
    monkeypatch.setenv("HARNESS_AUTHOR_TRANSCRIBE", "off")

    tripwire = PerJudgeScript(scripts=TRIPWIRE_SCRIPTS)
    output_dir = tmp_path / "out-textless"
    document = af("AF-10") / "geo7-mapwork-01-scanned-test.pdf"
    with pytest.raises(author.AuthoringInputError) as raised:
        make_service(author, chain_from_config(), tripwire).draft(
            documents=[document], output_dir=output_dir)

    message = str(raised.value)
    assert document.name in message and "page" in message.lower(), (
        f"{CASE}: the refusal must name the document and the page, got: {message}")
    assert tripwire.calls == [], (
        f"{CASE}: the refusal must fire before any provider call, got {len(tripwire.calls)}")
    _assert_nothing_written(output_dir)
    network_guard.assert_no_network()


def test_tc_author_16_an_empty_panel_refuses_as_configuration_error(
        tmp_path, network_guard):
    """Limb 3: a chain of zero models refuses as `ConfigurationError` before any call."""
    author = _guards()
    tripwire = PerJudgeScript(scripts=TRIPWIRE_SCRIPTS)
    output_dir = tmp_path / "out-empty-chain"
    with pytest.raises(ConfigurationError):
        service = author.AuthoringService(
            chain=(), provider=tripwire, transcriber=None,
            settings=author.AuthoringSettings())
        service.draft(documents=sorted(af("AF-01").glob("*.pdf")), output_dir=output_dir)

    assert tripwire.calls == [], (
        f"{CASE}: the refusal must fire before any provider call, got {len(tripwire.calls)}")
    _assert_nothing_written(output_dir)
    network_guard.assert_no_network()


def test_tc_author_16_the_cli_exits_error_on_the_unreadable_document(
        tmp_path, monkeypatch, capsys, network_guard):
    """Limb 4: the same refusal through `aeh author draft` exits 1 — M-PIPE's `EXIT_ERROR` —
    with the type and document named on stderr, and nothing written."""
    _author_draft_registered()
    _guards()
    # Isolation: the recorded provider bound to an empty tree, so no arm can reach a live
    # model even by accident (`CT-PROV-10`).
    (tmp_path / "recorded-fixtures").mkdir()
    monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(tmp_path / "recorded-fixtures"))

    corrupt = tmp_path / "corrupt-cli-paper.pdf"
    corrupt.write_bytes(b"%PDF-1.7\n%truncated garbage \x00\xff\n")
    output_dir = tmp_path / "out-cli"
    exit_code = cli.main(["author", "draft", "--config", str(DEV_CI_CONFIG),
                          "--docs", str(corrupt), "--out", str(output_dir)])

    assert exit_code == cli.EXIT_ERROR == 1, (
        f"{CASE}: the unreadable-document draft must exit M-PIPE's EXIT_ERROR (1), got "
        f"{exit_code}")
    error_text = capsys.readouterr().err
    assert "AuthoringInputError" in error_text and corrupt.name in error_text, (
        f"{CASE}: the CLI refusal's reason names the type and the document (FR-AUTHOR-13):\n"
        + error_text)
    _assert_nothing_written(output_dir)
    network_guard.assert_no_network()