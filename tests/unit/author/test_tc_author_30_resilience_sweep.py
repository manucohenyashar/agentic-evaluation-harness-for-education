"""`TC-AUTHOR-30` (FR-AUTHOR-02, FR-AUTHOR-05, FR-AUTHOR-13, CT-AUTHOR-10, P0) — the
resilience injection sweep (TS-155, #707; test plan §5.1 row 30; design delta §3.1's error
table).

Case: the design's error table, exercised by injection at the provider boundary —
`PerJudgeScript` (`tests/support/taxonomy.py`) programs a failure at a chosen build, per the
§4.2 stub-provider rule (the recorded provider records successes; a failure at a chosen call
needs a stub). The sweep, per the plan:

1. **Provider timeout fires → next model** — the chain head raises `TransportError`; the run
   continues at the next seat, the injected reason is recorded first in the affected step's
   `failures` (CT-AUTHOR-03: one reason per rejected model, in fallback order), and no
   exception escapes.
2. **Provider 500s from the head model → fallback** — the head raises `ProviderError("500")`;
   the same fallback and recorded-reason oracles.
3. **Transcription failure mid-run → pages missing, recorded** — AF-10's transcriber raises;
   the run completes without escaping, the failure is recorded in the report's Documents
   section (`FR-AUTHOR-12`), and the undetermined items are visible in the result.

`CT-AUTHOR-10` is the sweep's umbrella: once a document's text is extracted, `draft()` never
raises a provider error — every injected failure lands in the result or the report instead.
Each arm's final assertion is positive: a populated `DraftResult` and both artifacts on disk.

Written ahead of #690 ("the draft front door"), keyed in `WRITTEN_AHEAD_BLOCKERS` as a
`command` probe on the §3.1 surface beside TC-AUTHOR-03/19's entry (no recordings needed);
see that entry's comment block for why the issue's noted `symbol` key was widened. Re-check
the case green before unmarking — never on the notice alone.

Rung 1, guards first (#689's module surface, then the committed corpus limbs).

Disclosed assumptions, to reconcile at the landing (the oracles stay the plan's):
- The timeout is injected as `TransportError` (the taxonomy's retryable transport failure,
  `aeh.prov`), because `SamplingParams` carries no timeout field — the 240s wall-clock knob
  is not observable at this boundary. What the plan pins is the behaviour on *a* provider
  timeout, and `TransportError` is that error's type at rung 1.
- Whether M-PROV's retry policy retries a `TransportError` *before* M-AUTHOR falls back is
  not pinned at this seam, so the scripted queues carry generous depth and the asserted
  oracles are the fallback fact (the next seat is called after the head's failure), the
  recorded reason (`failures[0]` carries the injected message), and no escape — not an exact
  call sequence.
- The Documents section's failure wording is not design-pinned, so the section oracle is
  tolerant: the document named and the injected reason's token present. Section order is
  TC-AUTHOR-15's pin, not repeated here.
"""

from __future__ import annotations

import dataclasses

import pytest

from aeh.conf import ModelRef
from aeh.prov import ProviderError, TransportError
from tests.support.author_vocabulary import (
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    af,
    chain_from_config,
    make_service,
    transcriber_from_config,
)
from tests.support.impl import require, require_path
from tests.support.taxonomy import completion, PerJudgeScript


CASE = "TC-AUTHOR-30"

#: A second reasoning seat, distinct from the dev-ci head, so fallback is observable.
SECOND_SEAT_BUILD = "openrouter/qwen/qwen3-32b@2026-06-01"

UNPARSEABLE_TEXT = "this is not JSON {"

#: Scripted-queue depth, sized beyond CT-AUTHOR-13's call ceiling (steps × items × ATTEMPTS ×
#: |chain|) so the boundary cannot exhaust mid-run: the arms assert on call prefixes, the
#: fallback fact, and the recorded reasons, so depth only keeps a fixture-exhaustion
#: `AssertionError` from masking the assertion.
QUEUE_DEPTH = 64

#: The design's report sections (§3.1). TC-AUTHOR-15 owns their order; this file only needs
#: the Documents section's body, located tolerantly (see `_report_section`).
SECTION_TITLES = ("Documents", "Steps", "Items", "Unresolved", "Next command")

#: A distinctive token each injected failure carries, so the recorded reason is provably the
#: injected one, not a coincidental message.
TIMEOUT_TOKEN = "simulated-authoring-timeout"
SERVER_500_TOKEN = "simulated-authoring-500"
TRANSCRIBE_TOKEN = "simulated-transcription-failure"


def _report_section(report: str, title: str) -> str:
    """The body between the heading naming `title` and the next section heading (tolerant;
    see TC-AUTHOR-02's twin helper for the rationale)."""
    lines = report.splitlines()
    lowered = [other.lower() for other in SECTION_TITLES if other != title]
    starts = [i for i, line in enumerate(lines)
              if line.lstrip().startswith("#") and title.lower() in line.lower()]
    if not starts:
        starts = [i for i, line in enumerate(lines)
                  if line.strip().lower().rstrip(":") == title.lower()]
    assert starts, f"{CASE}: no {title!r} heading in the report:\n{report}"
    start = starts[0]
    end = len(lines)
    for i in range(start + 1, len(lines)):
        raw = lines[i].strip()
        if raw.startswith("#"):
            stripped = raw.lstrip("#").strip().lower().rstrip(":")
            if any(other in stripped for other in lowered):
                end = i
                break
        elif raw.rstrip(":").lower() in lowered:
            end = i
            break
    return "\n".join(lines[start:end])


def _guards() -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)
    # The surface guard: `require` with names returns the symbols (a tuple), not the module,
    # so the module the arms drive comes from the zero-names call above and this call only
    # asserts the §3.1 surface exists (the two-call pattern the landed sibling files use).
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)
    require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    require_path(af("AF-10"), "the AF-10 authored fixture", issue=CORPUS_ISSUE)
    return author


def _two_seat_scripts(head_steps: list) -> tuple[list, dict, str]:
    """A two-seat chain with the head scripted to fail and the fallback seat scripted to
    strike. Returns (chain, scripts, fallback build id)."""
    chain = [*chain_from_config(),
             ModelRef(role="judge", provider="openrouter",
                      build_id=SECOND_SEAT_BUILD, quantization=None)]
    fallback = chain[1].build_id
    scripts = {
        chain[0].build_id: head_steps,
        fallback: [completion(UNPARSEABLE_TEXT, build_id=fallback)
                   for _ in range(QUEUE_DEPTH)],
    }
    return chain, scripts, fallback


def _assert_no_escape_and_populated(result, boundary, output_dir, head_build: str) -> None:
    """The sweep's shared oracles: the run returned a populated result, the head's failure
    was recorded first in fallback order, and both artifacts exist."""
    assert result is not None and result.outcomes, (
        f"{CASE}: the run must return a populated DraftResult, got none")
    assert [field.name for field in dataclasses.fields(result)] == [
        "draft_path", "report_path", "outcomes", "placeholders", "resolved", "unresolved",
        "models_used"], f"{CASE}: DraftResult's field set is not CT-AUTHOR-03's exact seven"
    assert boundary.calls and boundary.calls[0] == head_build, (
        f"{CASE}: the first call must be the failing head ({head_build!r}), got "
        f"{boundary.calls[:1]}")
    recorded = [outcome.failures for outcome in result.outcomes if outcome.failures]
    assert recorded, (
        f"{CASE}: no step recorded a failure — the injected reason must land in "
        f"failures (CT-AUTHOR-03)")
    assert output_dir.is_dir() and result.draft_path.is_file() and result.report_path.is_file(), (
        f"{CASE}: the run must write both artifacts even when items stay unresolved")


def test_tc_author_30_a_provider_timeout_falls_through_to_the_next_model(
        tmp_path, network_guard):
    """Arm 1: the head raises `TransportError` — the run continues at the next seat, the
    injected reason is recorded first, nothing escapes."""
    author = _guards()
    chain, scripts, fallback = _two_seat_scripts(
        [TransportError(f"{TIMEOUT_TOKEN}: provider timeout")
         for _ in range(QUEUE_DEPTH)])
    boundary = PerJudgeScript(scripts=scripts)
    output_dir = tmp_path / "af01-timeout"
    output_dir.mkdir()

    result = make_service(author, chain, boundary).draft(
        documents=sorted(af("AF-01").glob("*.pdf")), output_dir=output_dir)

    _assert_no_escape_and_populated(result, boundary, output_dir, chain[0].build_id)
    assert fallback in boundary.calls, (
        f"{CASE}: a timeout on the head must fall through to the next model (FR-AUTHOR-05), "
        f"but only {set(boundary.calls)} were called")
    first_failures = next(outcome.failures for outcome in result.outcomes if outcome.failures)
    assert TIMEOUT_TOKEN in first_failures[0], (
        f"{CASE}: the head's failure must be recorded first in fallback order (CT-AUTHOR-03), "
        f"got {first_failures!r}")
    assert result.unresolved, (
        f"{CASE}: with every model striking, the items must land unresolved, not silently "
        f"resolved")
    network_guard.assert_no_network()


def test_tc_author_30_head_model_500s_fall_back(
        tmp_path, network_guard):
    """Arm 2: the head raises `ProviderError("500 …")` — the same fallback and recorded-reason
    oracles as the timeout arm."""
    author = _guards()
    chain, scripts, fallback = _two_seat_scripts(
        [ProviderError(f"{SERVER_500_TOKEN}: provider 500") for _ in range(QUEUE_DEPTH)])
    boundary = PerJudgeScript(scripts=scripts)
    output_dir = tmp_path / "af01-500s"
    output_dir.mkdir()

    result = make_service(author, chain, boundary).draft(
        documents=sorted(af("AF-01").glob("*.pdf")), output_dir=output_dir)

    _assert_no_escape_and_populated(result, boundary, output_dir, chain[0].build_id)
    assert fallback in boundary.calls, (
        f"{CASE}: 500s from the head must fall back (FR-AUTHOR-05), but only "
        f"{set(boundary.calls)} were called")
    first_failures = next(outcome.failures for outcome in result.outcomes if outcome.failures)
    assert SERVER_500_TOKEN in first_failures[0], (
        f"{CASE}: the head's failure must be recorded first in fallback order (CT-AUTHOR-03), "
        f"got {first_failures!r}")
    network_guard.assert_no_network()


def test_tc_author_30_a_transcription_failure_is_recorded_and_survivable(
        tmp_path, monkeypatch, network_guard):
    """Arm 3: AF-10's transcriber raises mid-run — no exception escapes, the failure is
    recorded in the report's Documents section, and the pages' items stay undetermined."""
    author = _guards()
    monkeypatch.delenv("HARNESS_AUTHOR_TRANSCRIBE", raising=False)
    transcriber = transcriber_from_config()
    chain = chain_from_config()
    scripts = {
        transcriber.build_id: [
            TransportError(f"{TRANSCRIBE_TOKEN}: transcription failed")
            for _ in range(QUEUE_DEPTH)
        ],
        chain[0].build_id: [completion(UNPARSEABLE_TEXT, build_id=chain[0].build_id)
                            for _ in range(QUEUE_DEPTH)],
    }
    boundary = PerJudgeScript(scripts=scripts)
    output_dir = tmp_path / "af10-transcribe-failure"
    output_dir.mkdir()

    result = make_service(author, chain, boundary).draft(
        documents=sorted(af("AF-10").glob("*.pdf")), output_dir=output_dir)

    assert result is not None and result.outcomes, (
        f"{CASE}: the run must survive a transcription failure and return a populated "
        f"result (CT-AUTHOR-10: no exception escapes once text is extracted)")
    assert result.report_path.is_file() and result.draft_path.is_file(), (
        f"{CASE}: the run must write both artifacts even with pages missing")
    report = result.report_path.read_text(encoding="utf-8")
    documents_section = _report_section(report, "Documents")
    document_name = "geo7-mapwork-01-scanned-test.pdf"
    assert document_name in documents_section, (
        f"{CASE}: the Documents section must name the document whose pages went missing:\n"
        + documents_section)
    assert TRANSCRIBE_TOKEN in documents_section, (
        f"{CASE}: the transcription failure must be recorded in the Documents section "
        f"(FR-AUTHOR-12), got:\n" + documents_section)
    assert result.unresolved or result.placeholders, (
        f"{CASE}: with the pages missing, their items must be visible as unresolved or "
        f"placeholder — not silently dropped")
    network_guard.assert_no_network()