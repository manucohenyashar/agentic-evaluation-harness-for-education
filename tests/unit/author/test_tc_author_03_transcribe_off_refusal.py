"""`TC-AUTHOR-03` (FR-AUTHOR-02, FR-AUTHOR-13, P0) — `transcribe=off` refuses a textless
document up front (TS-155, #707; test plan §5.1 row 3; design delta §3.1's error table).

Case: AF-10 with `HARNESS_AUTHOR_TRANSCRIBE=off`. Oracle: **exact exception type +
filesystem diff empty** — `AuthoringInputError` naming the document and the page, raised
*before any provider call*, with nothing written to the output directory. The provider
boundary here is a scripted tripwire with no replies programmed: any call at all fails
loudly, so "zero provider calls" is asserted by the run surviving with the calls list empty.

Written ahead of #690 ("the draft front door"), keyed in `WRITTEN_AHEAD_BLOCKERS` as a
`command` probe on the §3.1 surface beside TC-AUTHOR-19/30's entry (no recordings needed —
the scripted boundary is the point); see that entry's comment block for why the issue's noted
`symbol`/`aeh.author:AuthoringService` key was widened to the surface these bodies resolve.
Re-check the case green before unmarking — never on the notice alone.

Rung 1, guards first (#689's module surface, then the committed corpus limbs).

Disclosed corpus reconciliation, to settle at the landing: AF-10's pages carry a tiny header
text layer that literally reads "photocopy, no text layer" — the corpus's own marker. The
corpus-declared semantics is pinned: with transcription off, an AF-10 page is a page without
a text layer, and the refusal fires naming the document and page. If #690 treats any
extractable text as a text layer, this case goes red at the landing and the corpus semantics
get reconciled in the open.
"""

from __future__ import annotations

import pytest

from tests.support.author_vocabulary import (
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    af,
    chain_from_config,
    make_service,
)
from tests.support.impl import require, require_path
from tests.support.taxonomy import PerJudgeScript

pytestmark = [pytest.mark.writtenahead]

CASE = "TC-AUTHOR-03"


def test_tc_author_03_transcribe_off_refuses_af10_naming_document_and_page(
        tmp_path, monkeypatch, network_guard):
    """AF-10 with transcription off: `AuthoringInputError` naming document and page, zero
    provider calls, nothing written."""
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)
    # The surface guard: `require` with names returns the symbols (a tuple), not the module,
    # so the module the test drives comes from the zero-names call above and this call only
    # asserts the §3.1 surface plus the refusal type exists (the two-call pattern the landed
    # sibling files use).
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, "AuthoringInputError", issue=AUTHOR_ISSUE)
    require_path(af("AF-10"), "the AF-10 authored fixture", issue=CORPUS_ISSUE)
    monkeypatch.setenv("HARNESS_AUTHOR_TRANSCRIBE", "off")

    # The tripwire boundary: no replies programmed, so a single provider call raises
    # AssertionError naming the unscripted call — "zero provider calls" fails loudly.
    tripwire = PerJudgeScript(scripts={})
    output_dir = tmp_path / "never-written"

    document = af("AF-10") / "geo7-mapwork-01-scanned-test.pdf"
    with pytest.raises(author.AuthoringInputError) as raised:
        make_service(author, chain_from_config(), tripwire).draft(
            documents=[document], output_dir=output_dir)

    message = str(raised.value)
    assert document.name in message, (
        f"{CASE}: the refusal must name the failing document, got: {message}")
    assert "page" in message.lower(), (
        f"{CASE}: the refusal must name the page (FR-AUTHOR-02 pins the page as the unit "
        f"without a text layer), got: {message}")
    assert tripwire.calls == [], (
        f"{CASE}: the refusal must fire before any provider call (FR-AUTHOR-13's fail-fast), "
        f"got {len(tripwire.calls)}")
    assert not output_dir.exists() or not any(output_dir.iterdir()), (
        f"{CASE}: the refused draft writes nothing (FR-AUTHOR-13)")
    network_guard.assert_no_network()