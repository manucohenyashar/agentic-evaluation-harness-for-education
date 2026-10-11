"""`TC-AUTHOR-24` (FR-AUTHOR-17, P0) — the ready gate's exit-code matrix, through the CLI:
all resolved exits 0 printing the build command; one withheld item exits 1 listing what
remains with the partial updates kept; a missing draft file and a non-authoring TOML exit 1
with the reason — the same code as items-remaining, the output distinguishing them; no new
exit code anywhere (#713, the package-authoring test plan §5.2; design delta §3.1's exit
convention).

Written ahead of #696: `aeh.author` does not exist yet, so the case is red until the review
walk lands. The file carries `writtenahead`, keyed `#713 ready gate, rung 3` in
`WRITTEN_AHEAD_BLOCKERS`; when #696 closes the marker comes off — never the test.

Rung 3 (console) over rung-1 setup: the drafts are CLI-drafted AF-07 (the plan's review
fixture) through `aeh.pipeline.cli.main` — the same in-process entry TC-PIPE-27 and the
C02 clause file drive — with `cli._provider_for` monkeypatched over the F-AUTHOR recordings
exactly as `tests/contract/author/test_cs_author_c02_c18_cli.py` does, so the CLI runs the
test tier, no network. The review itself makes no model call; the socket guard's
zero-egress assertion at the end holds the isolation positively.

**The stdin walk protocol** is the C02 disclosure: one answer line per remaining item, in
the report's order (disclosed: report order == the draft's placeholder order), and EOF at a
prompt means *stop* — which is what makes "one withheld" drivable without inventing a skip
affordance: the withheld item is the last placeholder, the answers before it are fed, and
EOF arrives at its prompt. FR-AUTHOR-17 then demands what the oracle pins: the walk still
applied what it could (the earlier answers are in the draft, their sentinels gone), lists
the item that remains, and exits 1 — never 0, and never the ready wording.

The non-authoring TOML is content-based, not name-based: a valid TOML file with no package
id, no questions and no criteria — a file no reading of "authoring draft" accepts (the
C02/TC-PIPE-37 disclosure has review accepting spec-vocabulary files, so the refusal must
come from the content, and this file has none of it).
"""

from __future__ import annotations

import argparse
import io
import sys

import pytest

from aeh.pipeline import cli
from tests.support.author_vocabulary import (
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    DEV_CI_CONFIG,
    RECORDINGS,
    REVIEW_ISSUE,
    af,
    placeholder_fields,
)
from tests.support.impl import NotImplementedYet, require, require_attr, require_path

pytestmark = [pytest.mark.writtenahead]

TEACHER = "Sample-materials teacher"
MODEL_ANSWER = "By equivalent fractions with a common denominator."

#: The stdin walk's one answer per item, in report order: `approved_by` names the teacher,
#: everything else is plain-language model-answer prose (AF-07's placeholders are free text).
_ANSWER_FOR = {"approved_by": TEACHER}


def _answer_for(field: str) -> str:
    return _ANSWER_FOR.get(field, MODEL_ANSWER)


def _guards(tmp_path, monkeypatch, make_fixture_provider):
    """The require-style gates, and the first thing the test body does: a missing
    implementation is `NotImplementedYet` naming its blocker — never a collection error."""
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself — #689's
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names — #689's
    require_attr(author.AuthoringService, "review", issue=REVIEW_ISSUE)  # #696's new surface
    af07 = require_path(af("AF-07"), "the AF-07 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    _author_subparsers()  # the registration gate — the designed red while #695 is open
    monkeypatch.setattr(cli, "_provider_for",
                        lambda config: make_fixture_provider(RECORDINGS))
    return af07


def _author_subparsers() -> None:
    """The `aeh author` subcommands, registered by M-PIPE (#695) — or the stated red.

    The exit-code matrix drives `aeh author draft` (the setup) and `aeh author review`
    (the surface under test) through `cli.main`, so both must be registered.
    """
    parser = cli._build_parser()
    top = next(a for a in parser._actions
               if isinstance(a, argparse._SubParsersAction) and a.dest == "command")
    author = top.choices.get("author")
    if author is None:
        raise NotImplementedYet(
            "aeh.pipeline.cli._build_parser registers no `author` subcommand group yet "
            "(blocked on #695). This test is written ahead of its implementation (test plan "
            "§8.2) and is expected to fail until #695 lands.")
    inner = next((a for a in author._actions if isinstance(a, argparse._SubParsersAction)), None)
    missing = {"draft", "review"} - (set(inner.choices) if inner is not None else set())
    if missing:
        raise NotImplementedYet(
            f"aeh.pipeline.cli registers `author` but not {sorted(missing)} yet (blocked on "
            "#695). This test is written ahead of its implementation (test plan §8.2).")


def _cli(capsys, *argv: str) -> tuple[int, str, str]:
    capsys.readouterr()
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _draft_args(af_dir, out) -> list[str]:
    return ["author", "draft", "--config", str(DEV_CI_CONFIG),
            "--docs", *[str(p) for p in sorted(af_dir.glob("*.pdf"))], "--out", str(out)]


def _draft_af07(capsys, af07, out):
    """One CLI-drafted AF-07: exit 0, the draft file, and its placeholder fields in order."""
    code, _out, err = _cli(capsys, *_draft_args(af07, out))
    assert code == 0, err
    draft = next(out.glob("*.package.draft.toml"))
    fields = placeholder_fields(draft.read_text(encoding="utf-8"))
    assert fields, "AF-07 must leave placeholders for the review to fill"
    return draft, fields


def test_tc_author_24_the_ready_gate_exit_code_matrix(
        tmp_path, capsys, monkeypatch, make_fixture_provider, network_guard):
    """The plan's oracle, in order: exit 0 only when ready, with the build command; exit 1
    with the remaining items listed and the partial updates kept; exit 1 with the reason for
    a missing draft and for a non-authoring TOML — the same code, the output distinguishing
    them; and no new exit code anywhere."""
    af07 = _guards(tmp_path, monkeypatch, make_fixture_provider)

    # --- arm 1: all resolved — ready says so, with the build command, and exits 0 ------------
    draft1, fields1 = _draft_af07(capsys, af07, tmp_path / "ready")
    monkeypatch.setattr(sys, "stdin",
                        io.StringIO("".join(_answer_for(f) + "\n" for f in fields1)))
    code, ready_out, ready_err = _cli(capsys, "author", "review", "--draft", str(draft1))
    assert code == 0, ready_err
    assert "package build" in ready_out + ready_err, (
        "a ready review must say so with the build command (FR-AUTHOR-17)")
    rewritten1 = draft1.read_text(encoding="utf-8")
    assert not placeholder_fields(rewritten1), "a ready draft still carries a sentinel"
    for field in fields1:
        assert _answer_for(field) in rewritten1, (
            f"{field}: the walked answer never reached the draft")

    # --- arm 2: one withheld — exit 1, what remains is listed, the partial updates are kept --
    draft2, fields2 = _draft_af07(capsys, af07, tmp_path / "withheld")
    withheld = fields2[-1]
    kept = fields2[:-1]
    monkeypatch.setattr(sys, "stdin",
                        io.StringIO("".join(_answer_for(f) + "\n" for f in kept)))
    code, remain_out, remain_err = _cli(capsys, "author", "review", "--draft", str(draft2))
    assert code == 1, remain_err
    assert withheld in remain_out + remain_err, (
        f"the exit-1 listing must name the item that remains ({withheld!r}), got "
        f"{remain_out!r} / {remain_err!r}")
    assert "package build" not in remain_out + remain_err, (
        "the build command is the ready wording; items remaining must not print it "
        "(FR-AUTHOR-17)")
    rewritten2 = draft2.read_text(encoding="utf-8")
    remaining_fields = placeholder_fields(rewritten2)
    assert len(remaining_fields) == 1 and remaining_fields[0] == withheld, (
        f"exactly the withheld item must stay open, got {remaining_fields!r}")
    for field in kept:
        assert _answer_for(field) in rewritten2, (
            f"{field}: the partial update was not kept across the exit-1 review")

    # --- arm 3: the draft file is missing — exit 1, with the reason naming it -----------------
    absent = tmp_path / "absent.package.draft.toml"
    code, missing_out, missing_err = _cli(capsys, "author", "review", "--draft", str(absent))
    assert code == 1
    assert absent.name in missing_out + missing_err, (
        f"the missing-draft refusal's reason must name the file, got {missing_out!r} / "
        f"{missing_err!r}")

    # --- arm 4: a non-authoring TOML — exit 1, with the reason --------------------------------
    # Valid TOML, but no package id, no questions, no criteria: not an authoring draft under
    # any reading, so the refusal is content-based.
    not_a_draft = tmp_path / "gradebook-notes.toml"
    not_a_draft.write_text(
        '# A perfectly valid TOML file that is not an authoring draft.\n'
        'title = "Gradebook notes"\n\n[terms]\nautumn = true\n',
        encoding="utf-8")
    code, nota_out, nota_err = _cli(capsys, "author", "review", "--draft", str(not_a_draft))
    assert code == 1
    assert not_a_draft.name in nota_out + nota_err, (
        f"the non-authoring refusal's reason must name the file, got {nota_out!r} / "
        f"{nota_err!r}")
    assert "package build" not in nota_out + nota_err

    # --- the same code, the output distinguishing them (M-PIPE's convention) ------------------
    # Items-remaining, missing-file and non-authoring all exit 1 — no new exit code — and
    # what tells them apart is the output, which must actually differ. The comparison surface
    # is the full output (out + err), the same surface the presence checks above read, so the
    # assertion cannot pass vacuously on empty strings whichever stream the landing prints to.
    remain_text = remain_out + remain_err
    missing_text = missing_out + missing_err
    nota_text = nota_out + nota_err
    assert remain_text != missing_text != nota_text != remain_text, (
        "the three exit-1 reasons must be distinguishable by their output (§3.1's exit "
        "convention): items-remaining vs missing-file vs non-authoring")

    # --- no new exit code: the constants stay M-PIPE's three -----------------------------------
    assert {cli.EXIT_OK, cli.EXIT_ERROR, cli.EXIT_PAUSED} == {0, 1, 3}, (
        "no new exit code is introduced (§3.1's exit convention)")

    # --- isolation, positively: zero egress across every arm ------------------------------------
    network_guard.assert_no_network()