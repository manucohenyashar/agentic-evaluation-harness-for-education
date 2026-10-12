"""CT-AUTHOR-02 and CT-AUTHOR-18 — the `aeh author` CLI surface and the no-silent-overwrite gate (TS-165, #689).

| TC ID | Clause | Breaks if |
|---|---|---|
| TC-AUTHOR-C02 | CT-AUTHOR-02 surface | `aeh author draft` / `aeh author review` are not registered by M-PIPE with §3.1's flags, the draft help does not say publishing waits for review, or the exit-code matrix is wrong: argparse-only errors exit 2, an input error or a review with items remaining exits 1 (naming what remains), a missing draft file exits 1 with the reason, a completed draft prints the exact next commands (FR-AUTHOR-18) and a ready review prints the build command (FR-AUTHOR-17) |
| TC-AUTHOR-C18 | CT-AUTHOR-18 error | a re-draft over an existing draft and report for the same package id writes anything before confirmation; the refusal fails to name what would be replaced and that recorded review answers may carry over (FR-AUTHOR-22); or a different package id in the same directory is blocked |

Guard order (each names its blocker): the `aeh.author` surface (#689), the config-side chain
machinery `panel_for_profile` (#687 — the CLI resolves the reasoning chain from the run
configuration), the corpus (#686), and the registration probe (#695, `NotImplementedYet`).
The provider seam is monkeypatched exactly as `tests/unit/pipe/test_ingest_command.py` does —
`cli._provider_for` over the authoring recordings — so the CLI runs the test tier, no network.

Disclosed assumptions:
- **The stdin walk protocol.** FR-AUTHOR-16 pins "one item at a time" and "plain-language
  answers" but not the line protocol; these cases feed one answer line per remaining item, in
  the report's order, and treat EOF at a prompt as *stop* (exit 1, remaining named). If #695's
  implementation reads answers a different way, this file is what reconciles.
- **AF-01's one placeholder.** The corpus table calls AF-01 "fully resolved; zero placeholders",
  and FR-AUTHOR-09 makes `approved_by` a placeholder the model must never fill — so the suite
  reads AF-01 as: every reasoning-step field resolved, plus the mandatory `approved_by` the
  teacher answers at review. The scripted cases answer exactly that.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import pytest

from aeh.pipeline import cli
from tests.support.author_vocabulary import (
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CHAIN_ISSUE,
    CORPUS_ISSUE,
    DEV_CI_CONFIG,
    RECORDINGS,
    af,
    chain_from_config,
    make_service,
    scripted_answers,
    sha256_of,
)
from tests.support.impl import NotImplementedYet, require, require_attr, require_path

pytestmark = [pytest.mark.contract]

TEACHER = "Sample-materials teacher"


def _guards(make_fixture_provider) -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    require_attr(author, "AuthoringInputError", issue=AUTHOR_ISSUE)
    require("aeh.conf", "panel_for_profile", issue=CHAIN_ISSUE)
    af01 = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    af07 = require_path(af("AF-07"), "the AF-07 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, af01, af07, recordings


def _author_subparsers() -> dict:
    """The `aeh author` subcommand parsers, registered by M-PIPE (#695) — or a stated red."""
    parser = cli._build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    if "author" not in sub.choices:
        raise NotImplementedYet("#695: the aeh CLI registers no author subcommand")
    author = sub.choices["author"]
    author_sub = next(a for a in author._actions if isinstance(a, argparse._SubParsersAction))
    missing = {"draft", "review"} - set(author_sub.choices)
    if missing:
        raise NotImplementedYet(f"#695: aeh author is missing subcommands {sorted(missing)}")
    return author_sub.choices


def _cli(capsys, *argv: str) -> tuple[int, str, str]:
    capsys.readouterr()
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _draft_args(af_dir: Path, out: Path, force: bool = False) -> list[str]:
    argv = ["author", "draft", "--config", str(DEV_CI_CONFIG),
            "--docs", *[str(p) for p in sorted(af_dir.glob("*.pdf"))], "--out", str(out)]
    if force:
        argv.append("--force")
    return argv


# --- TC-AUTHOR-C02 ----------------------------------------------------------------------------


def test_tc_author_c02_the_author_cli_surface_flags_and_exit_codes(
        tmp_path, capsys, make_fixture_provider, monkeypatch):
    """Registration, the §3.1 flags, the publish-only-after-review wording, and the exit-code
    matrix: 2 for argparse-only errors, 1 with the reason for input errors and unfinished
    reviews, 0 with the exact next commands when the draft or the review completes."""
    author, af01, _af07, recordings = _guards(make_fixture_provider)
    choices = _author_subparsers()
    monkeypatch.setattr(cli, "_provider_for", lambda config: make_fixture_provider(RECORDINGS))

    # The flags §3.1 lists, and the draft help says publishing waits for review.
    draft_help = choices["draft"].format_help()
    for flag in ("--config", "--docs", "--out", "--force"):
        assert flag in draft_help, f"aeh author draft is missing {flag}"
    assert "review" in draft_help.lower(), (
        "the draft help must say a draft is published only after review")
    assert "--draft" in choices["review"].format_help()

    # Argparse-only errors exit 2 (a missing --out is a usage error, not a run failure).
    with pytest.raises(SystemExit) as usage:
        cli.main(["author", "draft", "--config", str(DEV_CI_CONFIG),
                  "--docs", str(next(af01.glob("*.pdf")))])
    assert usage.value.code == 2

    # A completed draft prints the exact next commands (FR-AUTHOR-18).
    out = tmp_path / "out"
    code, draft_out, draft_err = _cli(capsys, *_draft_args(af01, out))
    assert code == 0, draft_err
    next_commands = draft_out + draft_err
    assert "aeh author review" in next_commands and "package build" in next_commands

    # A review of a missing draft file exits 1 and names it (§3.1's exit convention).
    code, _out, err = _cli(capsys, "author", "review", "--draft", str(out / "absent.package.draft.toml"))
    assert code == 1 and "absent" in _out + err, err

    # The interactive walk: EOF at the first prompt stops it — exit 1, what remains is named.
    draft_file = next(out.glob("*.package.draft.toml"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    code, _out, walk_err = _cli(capsys, "author", "review", "--draft", str(draft_file))
    assert code == 1, walk_err
    assert "approved_by" in _out + walk_err, (
        f"the interrupted walk must name the item that remains, got: {walk_err!r}")

    # Answered in plain language, one line per remaining item: exit 0, build command printed.
    monkeypatch.setattr(sys, "stdin", io.StringIO(TEACHER + "\n"))
    code, ready_out, ready_err = _cli(capsys, "author", "review", "--draft", str(draft_file))
    assert code == 0, ready_err
    assert "package build" in ready_out + ready_err, (
        "a ready review must print the build command (FR-AUTHOR-17)")


# --- TC-AUTHOR-C18 ----------------------------------------------------------------------------


def test_tc_author_c18_a_redraft_of_a_reviewed_draft_confirms_before_it_writes(
        tmp_path, capsys, make_fixture_provider, monkeypatch):
    """Re-drafting AF-01 over a reviewed draft asks first: the refusal names the draft and that
    recorded answers may carry over, and writes nothing; `y` confirms; `--force` skips the
    prompt; and a different package id in the same directory is not blocked."""
    author, af01, af07, recordings = _guards(make_fixture_provider)
    _author_subparsers()
    monkeypatch.setattr(cli, "_provider_for", lambda config: make_fixture_provider(RECORDINGS))
    out = tmp_path / "out"

    code, _out, err = _cli(capsys, *_draft_args(af01, out))
    assert code == 0, err
    draft_file = next(out.glob("*.package.draft.toml"))

    # The prior report holds a recorded teacher answer (the scripted review form, §3.1).
    service = make_service(author, chain_from_config(), make_fixture_provider(RECORDINGS))
    review = service.review(draft_path=draft_file, answers=scripted_answers(
        author, draft_file.read_text(encoding="utf-8"), {"approved_by": TEACHER}))
    assert review.ready
    before = {p.name: sha256_of(p) for p in out.iterdir()}

    # Refusal: EOF instead of confirmation — exit 1, what would be replaced is named, the
    # carry-over of recorded answers is mentioned, and nothing at all is written.
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    code, _out, refusal = _cli(capsys, *_draft_args(af01, out))
    assert code == 1, refusal
    assert draft_file.name in refusal, f"the refusal does not name the draft: {refusal!r}"
    assert "carry" in refusal.lower() or "answer" in refusal.lower(), (
        f"the refusal does not mention the recorded answers: {refusal!r}")
    assert {p.name: sha256_of(p) for p in out.iterdir()} == before, (
        "the refusal wrote something before confirmation")

    # Confirmed interactively, the re-draft proceeds.
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\n"))
    code, _out, confirmed_err = _cli(capsys, *_draft_args(af01, out))
    assert code == 0, confirmed_err

    # --force is the non-interactive confirmation: no prompt, no refusal.
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    code, _out, forced_err = _cli(capsys, *_draft_args(af01, out, force=True))
    assert code == 0, forced_err

    # A different package id in the same directory overwrites nothing of AF-01's — no prompt.
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    code, _out, other_err = _cli(capsys, *_draft_args(af07, out))
    assert code == 0, other_err