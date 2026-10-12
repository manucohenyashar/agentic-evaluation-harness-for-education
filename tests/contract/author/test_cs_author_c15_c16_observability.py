"""CT-AUTHOR-15 and CT-AUTHOR-16 — the `aeh.author` logger and the credential canary (TS-165, #689).

| TC ID | Clause | Breaks if |
|---|---|---|
| TC-AUTHOR-C15 | CT-AUTHOR-15 observe | the logger is not named `aeh.author`, the lines do not carry the step and item ids, INFO does not cover each step's outcome, WARNING does not cover every fallback and placeholder, or DEBUG does not carry the failure detail |
| TC-AUTHOR-C16 | CT-AUTHOR-16 security | a credential canary seeded in the environment reaches any log record, the report, the draft or an exception message; wholesale document text reaches a log line or an artifact; or the payloads carry anything but extracted text and step prompts (checked: the document text reaches the model only through M-PROV, and only chain members are ever addressed) |

The log-line wording is unpinned — the clause pins the logger NAME, the LEVELS and the ids the
lines carry, so the assertions are record-name, level and substring checks against the module's
own outcome ids. The canary is a fixed fake key written into `OPENROUTER_API_KEY` for the run;
the module must never read it (the provider does), so nothing it produces may contain it.

Rung 1, guards first (#689 then #686). AF-06 supplies the placeholder, AF-09 run behind the
absent head (recorded nowhere, so every call for it is a provider error) supplies the
fallbacks.
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
    CountingProvider,
    RECORDINGS,
    af,
    chain_from_config,
    make_service,
    placeholder_fields,
)
from tests.support.impl import require, require_attr, require_path

pytestmark = [pytest.mark.contract]

CANARY = "sk-canary-authoring-suite-000000000000"


def _guards(make_fixture_provider) -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    require_attr(author, "AuthoringInputError", issue=AUTHOR_ISSUE)
    for fixture in ("AF-01", "AF-06", "AF-09"):
        require_path(af(fixture), f"the {fixture} authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, recordings


def _absent_ref():
    from aeh.conf import ModelRef

    return ModelRef(role="judge", provider="openrouter", build_id=ABSENT_HEAD_BUILD,
                    quantization=None)


# --- TC-AUTHOR-C15 ----------------------------------------------------------------------------


def test_tc_author_c15_the_aeh_author_logger_levels_and_ids(
        tmp_path, caplog, make_fixture_provider):
    """INFO names every outcome's step and item; WARNING covers the placeholder (AF-06) and
    every fallback (AF-09 behind an absent head); DEBUG carries failure detail; and every
    authoring line comes from the one logger name."""
    author, recordings = _guards(make_fixture_provider)
    absent = _absent_ref()

    caplog.set_level(logging.DEBUG)
    result = make_service(author, chain_from_config(), CountingProvider(
        make_fixture_provider(recordings))).draft(
        documents=sorted(af("AF-06").glob("*.pdf")), output_dir=tmp_path / "af06")
    fallback = make_service(author, [absent, *chain_from_config()], CountingProvider(
        make_fixture_provider(recordings))).draft(
        documents=sorted(af("AF-09").glob("*.pdf")), output_dir=tmp_path / "af09")

    author_records = [r for r in caplog.records if r.name == AUTHOR_MODULE]
    assert author_records, f"no log record came from the {AUTHOR_MODULE!r} logger"

    def _has(record, *substrings):
        text = record.getMessage()
        return all(s in text for s in substrings)

    # INFO per step outcome, with the step and item ids in the line.
    for outcome in result.outcomes:
        assert any(r.levelno == logging.INFO and _has(r, outcome.step, outcome.item_id)
                   for r in author_records), (
            f"no INFO line names step {outcome.step} and item {outcome.item_id}")

    # WARNING per placeholder: AF-06 carries one, and its field names the item. Disclosed
    # reconcile (the landing): `approved_by` rides on every outcome class (TC-AUTHOR-12) and
    # is never counted (TC-AUTHOR-01), so the per-placeholder oracle reads the content
    # sentinels — the sign-off slot is not unresolved work to warn about.
    for field in (f for f in placeholder_fields(result.draft_path.read_text(encoding="utf-8"))
                  if f != "approved_by"):
        assert any(r.levelno == logging.WARNING and field in r.getMessage()
                   for r in author_records), f"no WARNING names placeholder {field}"

    # WARNING per fallback: behind the absent head, every AF-09 item fell back once.
    assert fallback.outcomes
    for outcome in fallback.outcomes:
        assert any(r.levelno == logging.WARNING and outcome.item_id in r.getMessage()
                   for r in author_records), (
            f"no WARNING records the fallback for {outcome.item_id}")

    # DEBUG carries the failure detail: the failing run's reasons reached the debug stream.
    assert any(r.levelno == logging.DEBUG for r in author_records), (
        "no DEBUG record carries failure detail")


# --- TC-AUTHOR-C16 ----------------------------------------------------------------------------


def test_tc_author_c16_the_credential_canary_leaks_nowhere(
        tmp_path, caplog, make_fixture_provider, monkeypatch):
    """With a canary key in the environment, a full draft round trip leaves it in no payload,
    no log record, no artifact and no exception message; the document text reaches the model
    only through M-PROV, and no model outside the chain is ever addressed."""
    author, recordings = _guards(make_fixture_provider)

    monkeypatch.setenv("OPENROUTER_API_KEY", CANARY)
    caplog.set_level(logging.DEBUG)

    provider = CountingProvider(make_fixture_provider(recordings))
    af01 = af("AF-01")
    result = make_service(author, chain_from_config(), provider).draft(
        documents=sorted(af01.glob("*.pdf")), output_dir=tmp_path / "out")

    draft_text = result.draft_path.read_text(encoding="utf-8")
    report_text = result.report_path.read_text(encoding="utf-8")

    # The extracted document text, read here with the same library the module uses — this is
    # the text whose only exit is a step request through M-PROV (FR-AUTHOR-03).
    from pypdf import PdfReader
    extracted = " ".join(" ".join((page.extract_text() or "").split())
                         for path in sorted(af01.glob("*.pdf"))
                         for page in PdfReader(str(path)).pages)
    squeezed = re.sub(r"\s+", "", extracted)
    assert len(squeezed) >= 200, "AF-01's text layer is too small to test wholesale leakage"
    # A probe phrase that repr() cannot mangle: no quote, no backslash in the window.
    phrase = next(squeezed[i:i + 40] for i in range(0, len(squeezed) - 40, 25)
                  if not (set(squeezed[i:i + 40]) & {'"', "'", "\\"}))

    # 1. The payloads: canary absent, document text present, chain members only.
    joined = "\n".join(repr((prompt, model_ref, params))
                       for prompt, model_ref, params in provider.calls)
    assert CANARY not in joined, "the canary key reached a request payload"
    assert phrase in re.sub(r"\s+", "", joined), (
        "the extracted document text never reached the model through M-PROV")
    chain_ids = {ref.build_id for ref in chain_from_config()}
    assert {m for m in provider.models_called if m not in chain_ids} == set(), (
        "a request was addressed outside the injected chain")

    # 2. The logs: no canary anywhere, and no wholesale document text from aeh.author.
    for record in caplog.records:
        rendered = f"{record.getMessage()} {record.__dict__!r}"
        assert CANARY not in rendered, f"the canary key leaked into a log record: {record}"
        if record.name == AUTHOR_MODULE:
            assert squeezed not in re.sub(r"\s+", "", rendered), (
                f"wholesale document text in a log line: {record}")

    # 3. The artifacts.
    assert CANARY not in draft_text and CANARY not in report_text
    assert squeezed not in re.sub(r"\s+", "", draft_text)
    assert squeezed not in re.sub(r"\s+", "", report_text), (
        "wholesale document text in the draft or the report")

    # 4. An exception message: the input-error path never sees the canary either.
    garbage = tmp_path / "garbage.pdf"
    garbage.write_bytes(b"not a pdf\n")
    with pytest.raises(author.AuthoringInputError) as exc:
        make_service(author, chain_from_config(), provider).draft(
            documents=[garbage], output_dir=tmp_path / "err")
    assert CANARY not in str(exc.value)