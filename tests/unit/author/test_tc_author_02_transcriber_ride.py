"""`TC-AUTHOR-02` (FR-AUTHOR-02, P0) — only pages without a text layer ride the transcriber
(TS-155, #707; test plan §5.1 row 2; design delta §3.1, ADR-44).

Case: AF-10 (scan-style, no text layer) with `HARNESS_AUTHOR_TRANSCRIBE=auto`, the recorded
provider behind a counting wrapper (`CT-PROV-10`), the autouse socket guard armed. Oracle:
**exact call count + report content** — one transcriber provider call per page without a
text layer, and the report's Documents section records how each page's text was obtained
(`FR-AUTHOR-12`). Variant: AF-12 — the gating's other half, a document whose text comes from
its text layer must make **zero** transcriber calls.

Written ahead of #690 ("the draft front door"), keyed in `WRITTEN_AHEAD_BLOCKERS` as a
`command` probe beside TC-AUTHOR-01's entry (the §3.1 surface + the corpus recordings limb) —
see that entry's comment block for why the issue's noted `symbol` key was widened. Re-check
the case green before unmarking — never on the notice alone.

Rung 1, guards first (#689's module surface, then #686's corpus).

Disclosed corpus reconciliations, to settle at the landing (the behaviour pinned stays the
plan's):
- The plan's oracle says "one transcriber provider call for the scan page" (singular); the
  committed AF-10 has **two** scanned pages (`Page 1 of 2` / `Page 2 of 2`, the corpus's own
  header text), so the per-page rule (`FR-AUTHOR-02`: a page without a text layer rides the
  transcriber) pins the count at two — one call per scanned page. If #686 re-cuts AF-10 to
  one page, this assertion moves with the corpus.
- The plan's variant premise says AF-12 is "a mixed doc — only the scan page is transcribed";
  the committed AF-12 (`lang7-vocab-01-test.pdf`) has **no** scan page — it is one typed page
  mixing mcq and judged *lines* (design §5.1's wording, the corpus's `expected.toml` notes).
  This arm therefore pins the gating's other half on the corpus as committed: a text-layer
  document transcribes nothing, and its text resolves end to end. A mixed-*page* probe would
  need a synthetic document whose transcriber request no recording can replay
  (`FixtureMissingError` by construction), so the corpus-only shape is kept.
- AF-10's pages carry a tiny header text layer that literally reads "photocopy, no text
  layer" — the corpus's own marker. The corpus-declared semantics is pinned: AF-10's pages
  ride the transcriber; the header is not an extractable body. If #690 treats any
  extractable text as a text layer, this case goes red at the landing and the corpus
  semantics get reconciled in the open.
- The Documents section's rendering is not design-pinned (`FR-AUTHOR-12` pins that the
  section records how each page's text was obtained, not its words), so the section oracle
  is tolerant: the document named, a transcription marker present. Section *order* is
  TC-AUTHOR-15's pin, not repeated here.
"""

from __future__ import annotations

import pytest

from tests.support.author_vocabulary import (
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    CountingProvider,
    RECORDINGS,
    af,
    chain_from_config,
    make_service,
    transcriber_from_config,
)
from tests.support.impl import require, require_path


CASE = "TC-AUTHOR-02"

#: AF-10's committed page count — the corpus's own header text says "Page N of 2".
AF10_PAGE_COUNT = 2

#: The design's report sections (§3.1). TC-AUTHOR-15 owns their order; this file only needs
#: the Documents section's body, located tolerantly (see `_report_section`).
SECTION_TITLES = ("Documents", "Steps", "Items", "Unresolved", "Next command")


def _report_section(report: str, title: str) -> str:
    """The body between the heading naming `title` and the next section heading.

    The heading's rendering is not design-pinned, so the match is tolerant: a markdown
    heading of any level containing the title, falling back to a bare-word line. The section
    ends at the next heading naming one of the design's other sections.
    """
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
    # so the module the tests drive comes from the zero-names call above and this call only
    # asserts the §3.1 surface exists (the two-call pattern the landed sibling files use).
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)
    require_path(af("AF-10"), "the AF-10 authored fixture", issue=CORPUS_ISSUE)
    require_path(af("AF-12"), "the AF-12 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, recordings


def test_tc_author_02_each_textless_page_rides_the_transcriber_once(
        tmp_path, monkeypatch, make_fixture_provider, network_guard):
    """AF-10, transcribe=auto: one transcriber call per scanned page (two), and the report's
    Documents section names the document and records the transcription."""
    author, recordings = _guards()
    monkeypatch.setenv("HARNESS_AUTHOR_TRANSCRIBE", "auto")

    counting = CountingProvider(make_fixture_provider(recordings))
    output_dir = tmp_path / "af10-draft"
    output_dir.mkdir()
    result = make_service(author, chain_from_config(), counting).draft(
        documents=sorted(af("AF-10").glob("*.pdf")), output_dir=output_dir)

    transcriber_build = transcriber_from_config().build_id
    transcriber_calls = counting.models_called.count(transcriber_build)
    assert transcriber_calls == AF10_PAGE_COUNT, (
        f"{CASE}: exactly one transcriber call per page without a text layer is the rule "
        f"(FR-AUTHOR-02) and AF-10 has {AF10_PAGE_COUNT} scanned pages — got "
        f"{transcriber_calls} transcriber calls for {transcriber_build!r}")
    assert result.outcomes, f"{CASE}: the draft produced no outcomes"

    report = result.report_path.read_text(encoding="utf-8")
    documents_section = _report_section(report, "Documents")
    document_name = "geo7-mapwork-01-scanned-test.pdf"
    assert document_name in documents_section, (
        f"{CASE}: the report's Documents section does not name {document_name}:\n"
        + documents_section)
    assert "transcrib" in documents_section.lower(), (
        f"{CASE}: the Documents section does not record that the pages' text came from the "
        f"transcriber (FR-AUTHOR-12):\n" + documents_section)
    network_guard.assert_no_network()


def test_tc_author_02_a_text_layer_page_never_transcribes(
        tmp_path, monkeypatch, make_fixture_provider, network_guard):
    """AF-12 (typed, no scan page), transcribe=auto: zero transcriber calls, the document
    named in the Documents section, and its text layer resolves everything but the
    `model_answer` gap.

    Disclosed reconcile (the landing): AF-12's judged lines state no expected solution, so
    the honest draft carries the FR-AUTHOR-06 `model_answer` gap on them (a bands set does
    not determine a model answer — the landing disclosure the merged TC-AUTHOR-09/12 file
    records). This case's own claim is the transcriber gating: the text layer resolves the
    document end to end *except for that gap* — zero unresolved, and the only standing
    placeholders are `model_answer`."""
    author, recordings = _guards()
    monkeypatch.setenv("HARNESS_AUTHOR_TRANSCRIBE", "auto")

    counting = CountingProvider(make_fixture_provider(recordings))
    output_dir = tmp_path / "af12-draft"
    output_dir.mkdir()
    result = make_service(author, chain_from_config(), counting).draft(
        documents=sorted(af("AF-12").glob("*.pdf")), output_dir=output_dir)

    transcriber_build = transcriber_from_config().build_id
    assert transcriber_build not in counting.models_called, (
        f"{CASE}: AF-12's text comes from its text layer — the transcriber must not be "
        f"called (FR-AUTHOR-02's gating), got calls for it")
    assert result.resolved >= 3 and not result.unresolved, (
        f"{CASE}: AF-12's text layer resolves the document (expected.toml) — the gating "
        "must not have cost the document its text")
    assert result.placeholders == 2, (
        f"{CASE}: AF-12's only standing placeholders are the judged lines' two "
        f"`model_answer` gaps (the landing disclosure) — got {result.placeholders}")

    report = result.report_path.read_text(encoding="utf-8")
    documents_section = _report_section(report, "Documents")
    document_name = "lang7-vocab-01-test.pdf"
    assert document_name in documents_section, (
        f"{CASE}: the report's Documents section does not name {document_name}:\n"
        + documents_section)
    network_guard.assert_no_network()