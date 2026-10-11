"""`TC-AUTHOR-22` (FR-AUTHOR-19, P0) — the `aeh.author` logger's lines and silences (TS-159, #711).

Case: test plan §5.1 row 22; design delta §3.1 (FR-AUTHOR-19). The clause twin
`tests/contract/author/test_cs_author_c15_c16_observability.py` already holds the logger's
levels on AF-06/AF-09; this file holds the plan's own oracle across the two fixtures the
plan names (AF-01 happy, AF-06 partial) plus the fallback arm, and adds the silences the
plan pins: the logger never carries a credential and never carries wholesale document
text. Log-line wording is unpinned — the pin is the logger NAME, the LEVELS and the ids
the lines carry, so the assertions are record-name, level and substring checks against the
module's own outcome ids.

Arms:
1. AF-01 and AF-06 through the recorded corpus: an INFO line per step outcome, naming the
   step and the item id.
2. AF-06's placeholder fields: each in a WARNING (the partial fixture has real material).
3. The fallback arm — AF-06 behind the absent head prepended to the recorded chain: every
   item falls back once, and each fallback lands in a WARNING.
4. At least one DEBUG record carries failure detail.
5. Silences: a canary seeded in `OPENROUTER_API_KEY` reaches no record at any level, and
   wholesale AF-01 document text reaches no `aeh.author` record.

Written ahead of #694 ("the report, summary, logging and prompt pins"), keyed
`#694 report logging` in `WRITTEN_AHEAD_BLOCKERS` — a `command` probe; see the registry
comment for why the issue's `symbol` note does not survive contact with the tree, and
re-check the case green before unmarking — never on the notice alone.

Rung 1, guards first (#689's module surface, then #686's corpus). The canary is a fixed
fake key written into the environment for the run; the module must never read it (the
provider does), so nothing it produces may contain it — the C16 construction.
"""

from __future__ import annotations

import logging
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
    placeholder_fields,
)
from tests.support.impl import require, require_path

pytestmark = [pytest.mark.writtenahead]

CANARY = "sk-canary-tc-author-22-000000000000"


def _guards() -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    for fixture in ("AF-01", "AF-06"):
        require_path(af(fixture), f"the {fixture} authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, recordings


def _absent_ref():
    from aeh.conf import ModelRef

    return ModelRef(role="judge", provider="openrouter", build_id=ABSENT_HEAD_BUILD,
                    quantization=None)


def test_tc_author_22_the_aeh_author_logger_levels_silences_and_ids(
        tmp_path, caplog, make_fixture_provider, monkeypatch):
    """INFO per outcome (AF-01 and AF-06), WARNING per placeholder and per fallback, DEBUG
    carrying failure detail — and no credential, no wholesale document text, at any level."""
    author, recordings = _guards()
    monkeypatch.setenv("OPENROUTER_API_KEY", CANARY)
    caplog.set_level(logging.DEBUG)

    service = make_service(author, chain_from_config(), make_fixture_provider(recordings))
    af01 = service.draft(documents=sorted(af("AF-01").glob("*.pdf")),
                         output_dir=tmp_path / "af01")
    af06 = make_service(author, chain_from_config(), make_fixture_provider(recordings)).draft(
        documents=sorted(af("AF-06").glob("*.pdf")), output_dir=tmp_path / "af06")
    fallback = make_service(author, [_absent_ref(), *chain_from_config()],
                            make_fixture_provider(recordings)).draft(
        documents=sorted(af("AF-06").glob("*.pdf")), output_dir=tmp_path / "af06-fallback")

    records = [record for record in caplog.records if record.name == AUTHOR_MODULE]
    assert records, f"TC-AUTHOR-22: no log record came from the {AUTHOR_MODULE!r} logger"

    def _has(record, *substrings):
        text = record.getMessage()
        return all(s in text for s in substrings)

    # 1. INFO per step outcome across both fixtures, with the step and item ids in the line.
    for result in (af01, af06):
        assert result.outcomes, f"TC-AUTHOR-22: {result.draft_path} produced no outcomes"
        for outcome in result.outcomes:
            assert any(record.levelno == logging.INFO
                       and _has(record, outcome.step, outcome.item_id)
                       for record in records), (
                f"TC-AUTHOR-22: no INFO line names step {outcome.step} and item "
                f"{outcome.item_id} (FR-AUTHOR-19)")

    # 2. WARNING per placeholder: AF-06 carries one, and its field names the item.
    for field in placeholder_fields(af06.draft_path.read_text(encoding="utf-8")):
        assert any(record.levelno == logging.WARNING and field in record.getMessage()
                   for record in records), (
            f"TC-AUTHOR-22: no WARNING names placeholder {field} (FR-AUTHOR-19)")

    # 3. WARNING per fallback: behind the absent head, every AF-06 item fell back once.
    assert fallback.outcomes, "TC-AUTHOR-22: the fallback arm produced no outcomes"
    for outcome in fallback.outcomes:
        assert any(record.levelno == logging.WARNING and outcome.item_id in record.getMessage()
                   for record in records), (
            f"TC-AUTHOR-22: no WARNING records the fallback for {outcome.item_id} "
            f"(FR-AUTHOR-19)")

    # 4. DEBUG carries the failure detail: the fallback arm guarantees real failures, so a
    # DEBUG record must name one of the fallback items — a heartbeat line is not detail.
    assert any(record.levelno == logging.DEBUG and outcome.item_id in record.getMessage()
               for outcome in fallback.outcomes for record in records), (
        "TC-AUTHOR-22: no DEBUG record carries the failure detail of a fallback item "
        "(FR-AUTHOR-19)")

    # 5. The silences. The extracted document text, read here with the same library the
    # module uses — the text whose only exit is a step request through M-PROV. The pin is
    # FR-AUTHOR-19's own ("never … full document text"), so the check is the wholesale
    # squeeze, the clause twin C16's rule — prompt fragments in failure detail are not a
    # listed silence, and this file does not invent a stricter one.
    from pypdf import PdfReader

    extracted = " ".join(" ".join((page.extract_text() or "").split())
                         for path in sorted(af("AF-01").glob("*.pdf"))
                         for page in PdfReader(str(path)).pages)
    squeezed = re.sub(r"\s+", "", extracted)
    assert len(squeezed) >= 200, (
        "TC-AUTHOR-22: AF-01's text layer is too small to test wholesale leakage")
    for record in caplog.records:
        rendered = f"{record.getMessage()} {record.__dict__!r}"
        assert CANARY not in rendered, (
            f"TC-AUTHOR-22: the canary key leaked into a log record: {record}")
        if record.name == AUTHOR_MODULE:
            assert squeezed not in re.sub(r"\s+", "", rendered), (
                f"TC-AUTHOR-22: wholesale document text in a log line: {record}")