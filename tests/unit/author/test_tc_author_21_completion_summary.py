"""`TC-AUTHOR-21` (FR-AUTHOR-18, P0) — the printed completion summary (TS-159, #711).

Case: test plan §5.1 row 21; design delta §3.1 (FR-AUTHOR-18). After a draft completes,
one paragraph is printed carrying the counts (resolved / placeholders / unresolved), every
model used, and both next commands verbatim — `aeh author review …` first, then
`aeh package build …` (the rung order: review before the build that publishes).

The clause twins do not hold this: C05 pins the report file's sections, and TC-PIPE-37
pins the CLI's ready-exit wording. The plan's oracle here is the library-level print on
the happy AF-01 run. The paragraph granularity is the design's ("a one-paragraph
summary"), so the assertions hold within a single blank-line-delimited paragraph — if the
landing splits counts and commands across paragraphs, that is a reconciliation against
FR-AUTHOR-18's sentence, disclosed here rather than pre-loosened.

Disclosed assumption: the summary goes to stdout (design §3.1's console flow prints
results; there is no mandated stderr mention), read through `capsys`.

Written ahead of #694 ("the report, summary, logging and prompt pins"), keyed
`#694 report logging` in `WRITTEN_AHEAD_BLOCKERS` — a `command` probe; see the registry
comment for why the issue's `symbol` note does not survive contact with the tree, and
re-check the case green before unmarking — never on the notice alone.

Rung 1, guards first (#689's module surface, then #686's corpus).
"""

from __future__ import annotations

import pytest

from tests.support.author_vocabulary import (
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    RECORDINGS,
    af,
    chain_from_config,
    make_service,
)
from tests.support.impl import require, require_path



def _guards() -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, recordings


def test_tc_author_21_the_af01_summary_counts_models_and_next_commands(
        tmp_path, capsys, make_fixture_provider):
    """AF-01: the printed summary paragraph carries the three counts, every model used,
    the actual draft file name, and both next commands — review first, then build."""
    author, recordings = _guards()
    result = make_service(author, chain_from_config(),
                          make_fixture_provider(recordings)).draft(
        documents=sorted(af("AF-01").glob("*.pdf")), output_dir=tmp_path / "af01")
    out = capsys.readouterr().out

    paragraphs = [paragraph for paragraph in out.split("\n\n") if paragraph.strip()]
    summary = next(
        (paragraph for paragraph in paragraphs if "aeh package build" in paragraph), None)
    assert summary is not None, (
        "TC-AUTHOR-21: no printed summary paragraph carries the build command "
        "(FR-AUTHOR-18)")
    review_at = summary.find("aeh author review")
    build_at = summary.find("aeh package build")
    assert review_at >= 0 and review_at < build_at, (
        "TC-AUTHOR-21: the summary's next commands must be `aeh author review` first, "
        "then `aeh package build` (FR-AUTHOR-18's rung order)")

    for count in (result.resolved, result.placeholders, result.unresolved):
        assert str(count) in summary, (
            f"TC-AUTHOR-21: the summary paragraph does not state the count "
            f"{count} (FR-AUTHOR-18)")
    for model in result.models_used:
        assert model in summary, (
            f"TC-AUTHOR-21: the summary paragraph does not name the used model "
            f"{model} (FR-AUTHOR-18)")
    assert result.draft_path.name in summary, (
        "TC-AUTHOR-21: the next commands must name the actual draft file the review "
        "command will open (FR-AUTHOR-18)")