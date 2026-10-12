"""`TC-AUTHOR-15` (FR-AUTHOR-12, CT-AUTHOR-05, P0) — the authoring report (TS-159, #711).

Case: test plan §5.1 row 15; design delta §3.1 (FR-AUTHOR-12). The clause twin
`tests/contract/author/test_cs_author_c04_c05_artifacts.py` already holds the report's
section contract on AF-06; this file holds the plan's own oracle on the two limbs C05 does
not carry:

1. **AF-01, the fully resolved run** — the five sections (Documents → Steps → Items →
   Unresolved → Next command) in order, every handed-in document named in the Documents
   section, and the Steps section carrying each outcome's item id, winning model and
   failure reasons **in fallback order** — strictly increasing positions, which presence
   alone (C05's check) does not pin.
2. **The total-failure variant** — a run whose single chain member is the absent head
   (`ABSENT_HEAD_BUILD`, recorded nowhere, so every reasoning step fails through
   FR-AUTHOR-05a's fallback chain): `draft()` still returns a populated result
   (CT-AUTHOR-10's never-raises guarantee) and **the report is still written** with all
   five sections in order — FR-AUTHOR-12's "written even when every reasoning step failed"
   — and AF-09's first unresolved item heads the Unresolved list in review order (design
   §3.1's error table: "item unresolved; run continues; report lists it first").

Written ahead of #694 ("the report, summary, logging and prompt pins" — #693's §5.2
escalation story is still open), keyed `#694 report logging` in `WRITTEN_AHEAD_BLOCKERS` —
a `command` probe; see the registry comment for why the issue's `symbol` note does not
survive contact with the tree, and re-check the case green before unmarking — never on the
notice alone.

Rung 1, guards first (#689's module surface, then #686's corpus). Markup is deliberately
unpinned (CT-AUTHOR-05's rule): the order check is a word-subsequence scan, the per-item
checks are substring presence against the module's own outcome fields.
"""

from __future__ import annotations

import re

import pytest

from tests.support.author_vocabulary import (
    ABSENT_HEAD_BUILD,
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


SECTIONS = ("Documents", "Steps", "Items", "Unresolved", "Next command")


def _guards() -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    for fixture in ("AF-01", "AF-09"):
        require_path(af(fixture), f"the {fixture} authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, recordings


def _absent_ref():
    from aeh.conf import ModelRef

    return ModelRef(role="judge", provider="openrouter", build_id=ABSENT_HEAD_BUILD,
                    quantization=None)


def _section_positions(report: str) -> dict[str, int]:
    """The five sections' offsets, as a word subsequence — markup unpinned, order pinned.

    Each search starts at the previous match's end, so the scan itself enforces the order:
    a section rendered before its predecessor makes the subsequence fail.
    """
    cursor = 0
    positions: dict[str, int] = {}
    for section in SECTIONS:
        match = re.search(rf"\b{re.escape(section)}\b", report[cursor:], flags=re.IGNORECASE)
        assert match, f"TC-AUTHOR-15: the report has no {section!r} section"
        positions[section] = cursor + match.start()
        cursor += match.end()
    return positions


def test_tc_author_15_the_af01_report_sections_documents_and_fallback_ordered_steps(
        tmp_path, make_fixture_provider):
    """AF-01 (fully resolved): all five sections in order, every handed-in document named
    in the Documents section, and the Steps section carrying each outcome's item id,
    winning model and failure reasons — the reasons strictly increasing, fallback order."""
    author, recordings = _guards()
    documents = sorted(af("AF-01").glob("*.pdf"))
    result = make_service(author, chain_from_config(),
                          make_fixture_provider(recordings)).draft(
        documents=documents, output_dir=tmp_path / "af01")
    assert result.report_path.is_file(), (
        "TC-AUTHOR-15: no report written beside the draft (FR-AUTHOR-12)")
    report = result.report_path.read_text(encoding="utf-8")
    positions = _section_positions(report)

    # Documents: every handed-in document is named in the first section.
    documents_text = report[positions["Documents"]:positions["Steps"]]
    for path in documents:
        assert path.name in documents_text, (
            f"TC-AUTHOR-15: document {path.name} missing from the report's Documents "
            f"section (FR-AUTHOR-12)")

    # Steps: per item — the outcome, the winning model, and every failure reason in
    # fallback order (strictly increasing positions, not mere presence).
    steps_text = report[positions["Steps"]:positions["Items"]]
    assert re.search(r"\battempts?\b", steps_text, flags=re.IGNORECASE), (
        "TC-AUTHOR-15: the Steps section states no attempt count (FR-AUTHOR-12)")
    for outcome in result.outcomes:
        assert outcome.item_id in steps_text, (
            f"TC-AUTHOR-15: {outcome.item_id} missing from the Steps section")
        if outcome.model:
            assert outcome.model in steps_text, (
                f"TC-AUTHOR-15: {outcome.item_id}'s winning model {outcome.model} missing "
                f"from the Steps section")
        cursor = 0
        for reason in outcome.failures:
            at = steps_text.find(reason, cursor)
            assert at >= 0, (
                f"TC-AUTHOR-15: {outcome.item_id}'s failure reason {reason!r} missing from "
                f"the Steps section or stated before an earlier attempt's failure "
                f"(fallback order)")
            cursor = at + len(reason)


def test_tc_author_15_the_report_survives_total_step_failure_and_af09_heads_unresolved(
        tmp_path, make_fixture_provider):
    """AF-09 behind a chain whose only member is the absent head: every reasoning step
    fails, the run still returns a populated result (CT-AUTHOR-10), the report is still
    written with all five sections in order, and the first unresolved item heads the
    Unresolved list in review order."""
    author, recordings = _guards()
    result = make_service(author, [_absent_ref()],
                          make_fixture_provider(recordings)).draft(
        documents=sorted(af("AF-09").glob("*.pdf")), output_dir=tmp_path / "af09")

    assert result.outcomes, "TC-AUTHOR-15: a total-failure run returned no outcomes"
    assert all(outcome.model is None for outcome in result.outcomes), (
        "TC-AUTHOR-15: the absent-head chain let an outcome claim a winning model")

    assert result.report_path.is_file(), (
        "TC-AUTHOR-15: FR-AUTHOR-12 — the report is written even when every reasoning "
        "step failed")
    report = result.report_path.read_text(encoding="utf-8")
    positions = _section_positions(report)

    unresolved_ids = [outcome.item_id for outcome in result.outcomes
                      if outcome.status == "unresolved"]
    assert unresolved_ids, "TC-AUTHOR-15: a total-failure run left nothing unresolved"
    unresolved_text = report[positions["Unresolved"]:positions["Next command"]]
    offsets = {item_id: unresolved_text.find(item_id) for item_id in unresolved_ids}
    assert all(offset >= 0 for offset in offsets.values()), (
        f"TC-AUTHOR-15: not every unresolved item is listed in the Unresolved section: "
        f"{offsets}")
    first = unresolved_ids[0]
    assert offsets[first] == min(offsets.values()), (
        f"TC-AUTHOR-15: {first} must head the Unresolved list in review order (design "
        f"§3.1's error table: the report lists it first), got offsets {offsets}")