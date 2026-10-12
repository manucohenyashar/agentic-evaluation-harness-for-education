"""`TC-AUTHOR-25` (FR-AUTHOR-21, P1) — re-running the draft command is always the retry and
the recreate (the package-authoring test plan §5.2; design delta §3.1 v1.12-delta).

    | Re-run `aeh author draft` for AF-02 from a fresh process — a fresh interpreter, no state
    | carried over, a fresh output directory — twice |
    Expected: always produces a fresh draft; nothing blocks or skews the second run.
    Oracle: file set + success.

Story #697 (TS-163), which depends on #696; written ahead of both, keyed `#697 retry
recreate` in `WRITTEN_AHEAD_BLOCKERS`. LANDED (#695): the service landed with #696/#697 and
both integration files re-ran green from fresh processes at the landing, so the marker came
off — never the test.

**Rung 3, and the limb this case owns.** `TC-AUTHOR-C18`'s clause file drives the overwrite
matrix in ONE process through `cli.main` with the provider seam monkeypatched; the plan's
§5.2 rows for -25/-26 are rung 3 with **fresh subprocesses**, and the limb the clause suite
cannot reach is the process boundary itself: each run here is a fresh interpreter (`python
-m aeh`, the same entry the installed `aeh` command runs) that builds its own module state,
env and hash-table draws from nothing, into a fresh output directory — twice. A retry that
only works when some process-local state survives the first run is exactly the failure
FR-AUTHOR-21 exists to refuse ("no state outside the module's two artifacts is needed to
retry"), and it is invisible to an in-process re-run.

The oracle is the plan's — file set + success — deliberately NOT determinism: byte-identical
re-runs are `TC-AUTHOR-18`'s oracle (`CT-AUTHOR-07`) and are asserted there. This case holds
the cheaper half: the second fresh run succeeds and writes exactly the same two artifact
names, and nothing about the first run blocks or skews it (a fresh directory cannot see the
first run's report, so no carry-over can fire — `FR-AUTHOR-23` reads a prior report for the
same package id from the output directory, and there is none).

Isolation, per the plan's row ("recorded provider, socket guard; no live calls in this
suite"): the child's `HARNESS_FIXTURE_DIR` binds the recorded tree (`CT-PROV-10`), and
`OPENROUTER_API_KEY` is **removed** from the child env — never handed to a subprocess, which
both keeps the key out of another process's environment and makes a live call impossible even
if the child's provider binding were wrong. The in-process autouse socket guard covers every
parent-side arm (the guards and the parser probe), and the final assertion is that it
recorded zero attempts. The child itself cannot be watched by the parent's guard; the
recorded binding plus the stripped key are the child's isolation, disclosed here.

Disclosed fixture assumptions, to reconcile at the landing (the assertions stay the plan's):
- The recordings must exist for a real draft to replay: the guard requires
  `recordings/coverage.json` (#686's capture manifest — the same signal the recordings
  honesty entry keys on), not merely an empty `recordings/` directory.
- The two artifacts share one package stem (`<package>.package.draft.toml` and
  `<package>.authoring-report.md`, `FR-AUTHOR-12`/`FR-AUTHOR-14`), asserted here by name
  shape; the exact package id is #686's corpus fact, not this case's oracle.
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
)
from tests.support.impl import NotImplementedYet, require, require_path

pytestmark = [pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Seam 3: the child timeout is a knob, not a constant calibrated on one box. A recorded
#: replay is seconds; a slow box may still need room.
CHILD_TIMEOUT_S = int(os.environ.get("HARNESS_TEST_AUTHOR_CHILD_TIMEOUT_S", "300"))


def _guards() -> None:
    """The blockers each limb of this case waits on, each naming its issue (the `#635`
    re-check rule: the registry probe and these guards re-check the same limbs at unmarking
    time). The first missing name raises `NotImplementedYet` — the designed red — never a
    collection error or a bare `AttributeError`. The module surface is named with this
    file's own story (#697 — whose closure removes the marker; the class itself lands with
    the first service story, #690 — the disclosure the registry entry carries); the corpus
    paths are #686's facts."""
    require(AUTHOR_MODULE, issue=RETRY_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=RETRY_ISSUE)  # the §3.1 names
    require("aeh.conf", "panel_for_profile", issue=CHAIN_ISSUE)
    require_path(af("AF-02"), "the AF-02 authored fixture", issue=CORPUS_ISSUE)
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


def _draft_child(out_dir: Path, docs: list[Path]) -> subprocess.CompletedProcess:
    """One fresh interpreter: `python -m aeh author draft` over the recorded tree.

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
        [sys.executable, "-m", "aeh", "author", "draft",
         "--config", str(DEV_CI_CONFIG),
         "--docs", *[str(p) for p in docs],
         "--out", str(out_dir)],
        capture_output=True, text=True, cwd=str(REPO_ROOT), env=env,
        timeout=CHILD_TIMEOUT_S,
    )


def _artifact_names(out_dir: Path) -> list[str]:
    return sorted(p.name for p in out_dir.iterdir())


def test_tc_author_25_a_fresh_process_redrafts_af02_into_a_fresh_directory_twice(
        tmp_path, network_guard):
    """Two fresh interpreters, two fresh output directories, the same AF-02 documents: each
    run exits 0 and writes exactly the two artifacts — and the second run is not blocked or
    skewed by the first, which it cannot even see."""
    _guards()
    docs = sorted(af("AF-02").glob("*.pdf"))
    assert docs, "AF-02 must carry its documents"

    # --- run one: a fresh process, a fresh output directory -----------------------------------
    first_out = tmp_path / "run-one"
    first = _draft_child(first_out, docs)
    assert first.returncode == 0, (
        f"TC-AUTHOR-25: the first fresh `aeh author draft` must succeed (FR-AUTHOR-21); "
        f"stderr:\n{first.stderr}")
    names_one = _artifact_names(first_out)
    assert len(names_one) == 2, (
        f"TC-AUTHOR-25: a draft writes exactly two artifacts (FR-AUTHOR-14), got "
        f"{names_one}")
    drafts = [n for n in names_one if n.endswith(".package.draft.toml")]
    reports = [n for n in names_one if n.endswith(".authoring-report.md")]
    assert len(drafts) == 1 and len(reports) == 1, (
        f"TC-AUTHOR-25: the two artifacts are the draft spec and the report (FR-AUTHOR-12, "
        f"FR-AUTHOR-14), got {names_one}")
    assert drafts[0].removesuffix(".package.draft.toml") == reports[0].removesuffix(
        ".authoring-report.md"), (
        f"TC-AUTHOR-25: both artifacts share the package stem (FR-AUTHOR-12), got "
        f"{names_one}")
    assert all((first_out / n).stat().st_size > 0 for n in names_one), (
        "TC-AUTHOR-25: both artifacts are written, not placeholder-empty files")

    # --- run two: another fresh interpreter, another fresh directory ----------------------------
    second_out = tmp_path / "run-two"
    second = _draft_child(second_out, docs)
    assert second.returncode == 0, (
        f"TC-AUTHOR-25: the second fresh run — the retry — must not be blocked or skewed by "
        f"the first (FR-AUTHOR-21); stderr:\n{second.stderr}")
    names_two = _artifact_names(second_out)
    assert names_two == names_one, (
        f"TC-AUTHOR-25: the retry produces the same file set from the same documents "
        f"(FR-AUTHOR-21), got {names_two} vs {names_one}")
    assert all((second_out / n).stat().st_size > 0 for n in names_two), (
        "TC-AUTHOR-25: the retry wrote both artifacts whole")

    # --- nothing carried over: a fresh directory holds no prior report to carry from -----------
    # FR-AUTHOR-23's carry-over reads a prior report for the same package id from the OUTPUT
    # directory; run two's directory never contained one, so nothing from run one may appear
    # in it — asserted by path, not by content, so no report-wording bet is taken here.
    first_paths = {str(first_out / n) for n in names_one}
    second_text = "\n".join(
        (second_out / n).read_text(encoding="utf-8", errors="replace") for n in names_two)
    leaked = [p for p in first_paths if p in second_text]
    assert not leaked, (
        f"TC-AUTHOR-25: the fresh run's artifacts reference the first run's files {leaked} — "
        f"state outside the two artifacts leaked into the retry (FR-AUTHOR-21)")

    # --- isolation, positively: the parent side made zero attempts ------------------------------
    network_guard.assert_no_network()