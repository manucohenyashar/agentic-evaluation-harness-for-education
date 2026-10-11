"""`TC-AUTHOR-26` (FR-AUTHOR-22 / CT-AUTHOR-18, P0) — the overwrite matrix, each arm a fresh
process (the package-authoring test plan §5.2; design delta §3.1 v1.12-delta).

    | Draft, re-draft without confirmation, re-draft with `--force`, re-draft answering `y`,
    | and a re-draft of a different package id — each from a fresh process |
    Expected: the overwrite refusal names what would be replaced and the answers that would
    carry over; `--force` and `y` proceed; a different package id never collides.
    Oracle: file hashes + exit codes.

Story #697 (TS-163); written ahead of it, keyed `#697 retry recreate`. Marker off — never
test off — when #697 closes.

**Rung 3, and the limbs this case owns.** `TC-AUTHOR-C18`'s clause file drives the same
matrix in ONE process through `cli.main` with the provider seam monkeypatched; the plan's
§5.2 row for -26 is rung 3, and what a fresh interpreter adds is that the confirmation walk
runs against a REAL stdin (EOF, or a piped `y`) rather than pytest's captured one, and that
byte-preservation is observed across a process boundary — a refusal that "protects" the files
only by mutating shared in-process state would pass the clause suite and fail here. The arms,
in the plan's order:

1. the initial draft (exit 0, the two artifacts);
2. a review child answering the placeholder over stdin, so the directory holds recorded
   answers for the carry-over note to name (the stdin protocol — one line per remaining
   item, EOF stops — is the clause suite's disclosed one; the review's own outcome class is
   `TC-AUTHOR-24`'s library oracle, not this matrix's, so the child's code is asserted only
   within the documented exit set {0, 1});
3. the refusal: re-draft, no `--force`, EOF on stdin → exit 1, the output names BOTH artifact
   filenames (what would be replaced) and mentions the carry-over ("carry" or "answer",
   case-insensitive — CT-AUTHOR-18's wording is free, the mention is not), and every file in
   the directory is byte-identical afterwards;
4. `--force` → exit 0, the same two names rewritten;
5. the interactive confirm: no `--force`, `y` piped in → exit 0;
6. the different package id: AF-07's documents into the same directory, EOF on stdin →
   exit 0 with no prompt refused (a different package id does not collide with AF-01's
   artifact names), AF-01's artifacts byte-unchanged, AF-07's two artifacts added.

Isolation is the plan's, per the row: the child's `HARNESS_FIXTURE_DIR` binds the recorded
tree (`CT-PROV-10`) and `OPENROUTER_API_KEY` is removed from the child env — never handed to
a subprocess, which makes a live call impossible even if the child's provider binding were
wrong. The parent-side autouse socket guard covers every parent arm, and the final assertion
is that it recorded zero attempts. The child itself cannot be watched by the parent's guard;
the recorded binding plus the stripped key are the child's isolation, disclosed here.

Disclosed fixture assumptions, to reconcile at the landing (the assertions stay the plan's):
- AF-01 and AF-07 carry different package ids (the clause suite's different-id arm already
  bets this); the exact ids are #686's corpus facts, read off the produced filenames here,
  never hard-coded.
- The refusal's exit is 1 (the design's exit convention: 0/1 only, 2 is argparse's alone).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.author_vocabulary import (
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CHAIN_ISSUE,
    CORPUS_ISSUE,
    DEV_CI_CONFIG,
    RECORDINGS,
    RETRY_ISSUE,
    af,
    sha256_of,
)
from tests.support.impl import NotImplementedYet, require, require_path

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Seam 3: the child timeout is a knob, not a constant calibrated on one box.
CHILD_TIMEOUT_S = int(os.environ.get("HARNESS_TEST_AUTHOR_CHILD_TIMEOUT_S", "300"))

TEACHER = "Sample-materials teacher"


def _guards() -> None:
    """The blockers each limb waits on, each naming its issue (the `#635` re-check rule).
    The module surface is named with this file's own story (#697 — whose closure removes the
    marker; the class itself lands with #690 — the disclosure the registry entry carries);
    the corpus paths are #686's facts."""
    require(AUTHOR_MODULE, issue=RETRY_ISSUE)
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=RETRY_ISSUE)
    require("aeh.conf", "panel_for_profile", issue=CHAIN_ISSUE)
    for fixture in ("AF-01", "AF-07"):
        require_path(af(fixture), f"the {fixture} authored fixture", issue=CORPUS_ISSUE)
    require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    require_path(
        RECORDINGS / "coverage.json", "the authoring recordings' capture manifest",
        issue=CORPUS_ISSUE)
    _author_draft_parser()


def _author_draft_parser() -> "object":
    """The `aeh author draft` subparser with its `--force` flag, or a stated red naming the
    story that owns the gap.

    Both the registration and the `--force` flag belong to #695 (FR-PIPE-10): its acceptance
    criteria register `aeh author draft ... [--force]`, and #697's technical notes say the
    flag was registered there while #697 "implements the behaviour behind it". So a missing
    group, subcommand or flag is a stated red naming #695, not an argparse complaint.
    """
    from aeh.pipeline import cli

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
    draft = inner.choices["draft"]
    if not any("--force" in getattr(action, "option_strings", ())
               for action in draft._actions):
        raise NotImplementedYet(
            "aeh author draft registers no `--force` flag yet (blocked on #695, whose "
            "acceptance criteria register `aeh author draft ... [--force]`; #697 implements "
            "the behaviour behind the flag). This test is written ahead of its "
            "implementation.")
    return draft


def _child(args: list[str], stdin_text: str | None = None) -> subprocess.CompletedProcess:
    """One fresh interpreter running `python -m aeh ...` with the given argv tail.

    `OPENROUTER_API_KEY` is removed, never passed through (see the module docstring); the
    recorded binding is the child's only egress point (`CT-PROV-10`).
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        str(REPO_ROOT / "src")
        + os.pathsep
        + str(REPO_ROOT)
        + os.pathsep
        + env.get("PYTHONPATH", "")
    )
    env["HARNESS_FIXTURE_DIR"] = str(RECORDINGS)
    env.pop("OPENROUTER_API_KEY", None)
    return subprocess.run(
        [sys.executable, "-m", "aeh", *args],
        input=stdin_text, capture_output=True, text=True, cwd=str(REPO_ROOT), env=env,
        timeout=CHILD_TIMEOUT_S,
    )


def _draft_args(af_id: str, out_dir: Path, *, force: bool) -> list[str]:
    args = ["author", "draft", "--config", str(DEV_CI_CONFIG),
            "--docs", *[str(p) for p in sorted(af(af_id).glob("*.pdf"))],
            "--out", str(out_dir)]
    if force:
        args.append("--force")
    return args


def _hashes(out_dir: Path) -> dict[str, str]:
    return {p.name: sha256_of(p) for p in sorted(out_dir.iterdir())}


def _artifact_names(out_dir: Path) -> list[str]:
    return sorted(p.name for p in out_dir.iterdir())


def test_tc_author_26_the_overwrite_matrix_from_fresh_processes(tmp_path, network_guard):
    """Draft → review → refuse → force → confirm-y → different-id, every arm its own fresh
    interpreter: exit codes and byte-preservation exactly as CT-AUTHOR-18 pins them."""
    _guards()
    out = tmp_path / "out"

    # --- arm 1: the initial draft --------------------------------------------------------------
    first = _child(_draft_args("AF-01", out, force=False))
    assert first.returncode == 0, (
        f"TC-AUTHOR-26: the initial draft must succeed; stderr:\n{first.stderr}")
    names = _artifact_names(out)
    assert len(names) == 2, f"TC-AUTHOR-26: a draft writes exactly two artifacts, got {names}"
    draft_name = next(n for n in names if n.endswith(".package.draft.toml"))
    report_name = next(n for n in names if n.endswith(".authoring-report.md"))

    # --- arm 2: a review child records answers over stdin ----------------------------------------
    review = _child(["author", "review", "--draft", str(out / draft_name)],
                    stdin_text=TEACHER + "\n")
    assert review.returncode in (0, 1), (
        f"TC-AUTHOR-26: the review child must exit within the documented set {{0, 1}} "
        f"(the stdin protocol is the clause suite's disclosed one; the review's own outcome "
        f"class is TC-AUTHOR-24's oracle); stderr:\n{review.stderr}")

    # --- arm 3: the refusal — no --force, EOF on stdin ---------------------------------------------
    before = _hashes(out)
    refused = _child(_draft_args("AF-01", out, force=False), stdin_text="")
    assert refused.returncode == 1, (
        f"TC-AUTHOR-26: an overwrite without confirmation must refuse with exit 1 "
        f"(FR-AUTHOR-22); stdout:\n{refused.stdout}\nstderr:\n{refused.stderr}")
    said = refused.stdout + refused.stderr
    assert draft_name in said and report_name in said, (
        f"TC-AUTHOR-26: the refusal must name what would be replaced — both artifact "
        f"filenames (FR-AUTHOR-22); said:\n{said}")
    assert ("carry" in said.lower()) or ("answer" in said.lower()), (
        f"TC-AUTHOR-26: the refusal must note the answers that would carry over "
        f"(FR-AUTHOR-22); said:\n{said}")
    assert _hashes(out) == before, (
        "TC-AUTHOR-26: the refusal must leave every file byte-identical (CT-AUTHOR-18)")

    # --- arm 4: --force proceeds --------------------------------------------------------------------
    forced = _child(_draft_args("AF-01", out, force=True), stdin_text="")
    assert forced.returncode == 0, (
        f"TC-AUTHOR-26: `--force` must proceed (FR-AUTHOR-22); stderr:\n{forced.stderr}")
    assert _artifact_names(out) == names, (
        "TC-AUTHOR-26: the forced re-draft rewrites the same two artifact names")

    # --- arm 5: the interactive confirm — a piped `y` proceeds ---------------------------------------
    confirmed = _child(_draft_args("AF-01", out, force=False), stdin_text="y\n")
    assert confirmed.returncode == 0, (
        f"TC-AUTHOR-26: answering `y` at the confirm must proceed (FR-AUTHOR-22); "
        f"stdout:\n{confirmed.stdout}\nstderr:\n{confirmed.stderr}")
    assert _artifact_names(out) == names
    after_confirm = _hashes(out)

    # --- arm 6: a different package id never collides --------------------------------------------------
    added = _child(_draft_args("AF-07", out, force=False), stdin_text="")
    assert added.returncode == 0, (
        f"TC-AUTHOR-26: drafting a different package id into the same directory must not "
        f"collide or refuse (FR-AUTHOR-22); stdout:\n{added.stdout}\nstderr:\n{added.stderr}")
    names_now = _artifact_names(out)
    af07_drafts = [n for n in names_now
                   if n.endswith(".package.draft.toml") and n != draft_name]
    assert len(af07_drafts) == 1, (
        f"TC-AUTHOR-26: exactly one other package's draft artifact was added, got {names_now}")
    af07_report = af07_drafts[0].removesuffix(".package.draft.toml") + ".authoring-report.md"
    assert af07_report in names_now, (
        f"TC-AUTHOR-26: AF-07's report artifact was added alongside its draft, got {names_now}")
    # AF-01's two artifacts are byte-unchanged by the AF-07 arm.
    assert sha256_of(out / draft_name) == after_confirm[draft_name] and \
        sha256_of(out / report_name) == after_confirm[report_name], (
        "TC-AUTHOR-26: the different-id arm must not touch the other package's artifacts "
        "(FR-AUTHOR-22)")

    # --- isolation, positively: the parent side made zero attempts --------------------------------------
    network_guard.assert_no_network()