"""`TC-AUTHOR-01` (FR-AUTHOR-01, NFR-AUTHOR-03, CT-AUTHOR-01, CT-CONSOLE-01, P0) — the
headless draft (TS-155, #707; test plan §5.1 row 1; design delta §3.1).

Case: AF-01 via `AuthoringService.draft()`, in-process, the recorded provider
(`RecordedFixtureProvider` over `fixtures/F-AUTHOR/recordings/`, `CT-PROV-10`), the autouse
socket guard armed throughout. The oracle, in the plan's order:

1. **Populated DraftResult** — every `CT-AUTHOR-03` field present and the AF-01 corpus
   expectation realised: at least one resolved item, zero placeholders, zero unresolved
   (`expected.toml`: `outcome = "resolved"`, `placeholders = []`).
2. **`models_used` ⊆ chain with first = panel seat 0** — the headless run used the injected
   chain and started at its head (`FR-AUTHOR-04`).
3. **Exactly two artifacts written** — the draft and the report, named after the package id
   (`<package>.package.draft.toml` + `<package>.authoring-report.md`, design §3.1), and
   nothing else in the output directory.
4. **Zero egress** — the socket guard recorded no attempt: the headless run is real
   (`CT-CONSOLE-01`) and needs no console and no network.

Written ahead of #690 ("the draft front door"), keyed in `WRITTEN_AHEAD_BLOCKERS` as a
`command` probe — see the registry entry's comment block for why the issue's noted
`symbol`/`aeh.author:AuthoringService` key was widened to the §3.1 surface + the corpus
recordings limb (a bare `AuthoringService` symbol fires before the dataclass surface these
bodies resolve, and TC-AUTHOR-01 replays the corpus, which does not exist until #686's
capture pass). Re-check the case green before unmarking — never on the notice alone.

Rung 1, guards first (#689's module surface, then #686's corpus).

Disclosed fixture assumptions, to reconcile at the landing (the assertions stay the plan's):
- `DraftResult` is a frozen dataclass (§3.1's Data-structures block), so `dataclasses.fields`
  reads its field set; a rename there is one line in `AUTHOR_SURFACE`'s home.
- `placeholders`/`unresolved` are sequences, so the corpus expectation is read as falsy
  rather than pinned to a concrete container type.
"""

from __future__ import annotations

import dataclasses

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

pytestmark = [pytest.mark.writtenahead]

CASE = "TC-AUTHOR-01"

#: CT-AUTHOR-03 pins DraftResult's field set exactly: these seven, no more.
DRAFT_RESULT_FIELDS = (
    "draft_path",
    "report_path",
    "outcomes",
    "placeholders",
    "resolved",
    "unresolved",
    "models_used",
)
#: CT-AUTHOR-03 pins StepOutcome's field set exactly: these six, no more.
STEP_OUTCOME_FIELDS = ("step", "item_id", "status", "model", "attempts", "failures")
#: CT-AUTHOR-03 pins the status domain exactly.
STATUS_DOMAIN = {"resolved", "derived", "placeholder", "unresolved"}


def test_tc_author_01_af01_drafts_headless_with_the_recorded_provider(
        tmp_path, make_fixture_provider, network_guard):
    """AF-01 through `AuthoringService.draft()`: populated result, chain-honest
    `models_used`, exactly two artifacts, zero egress."""
    author = require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)
    require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)

    chain = chain_from_config()
    provider = make_fixture_provider(recordings)
    output_dir = tmp_path / "af01-draft"
    output_dir.mkdir()

    result = make_service(author, chain, provider).draft(
        documents=sorted(af("AF-01").glob("*.pdf")), output_dir=output_dir)

    # --- the result is populated and its surface is exactly CT-AUTHOR-03's --------------------
    assert [field.name for field in dataclasses.fields(result)] == list(DRAFT_RESULT_FIELDS), (
        f"{CASE}: DraftResult's field set is not CT-AUTHOR-03's exact seven")
    assert result.outcomes, f"{CASE}: the draft produced no outcomes"
    for outcome in result.outcomes:
        assert [field.name for field in dataclasses.fields(outcome)] == list(
            STEP_OUTCOME_FIELDS), (
            f"{CASE}: a StepOutcome's field set is not CT-AUTHOR-03's exact six")
        assert outcome.status in STATUS_DOMAIN, (
            f"{CASE}: StepOutcome status {outcome.status!r} outside CT-AUTHOR-03's domain")
    assert result.resolved >= 1, f"{CASE}: AF-01 resolves (expected.toml) but none did"
    assert not result.placeholders, (
        f"{CASE}: AF-01 declares zero placeholders but the draft emitted some")
    assert not result.unresolved, (
        f"{CASE}: AF-01 declares a fully resolved outcome but items stayed unresolved")

    # --- models_used ⊆ chain, first = panel seat 0 (FR-AUTHOR-04) ------------------------------
    chain_builds = [ref.build_id for ref in chain]
    assert result.models_used, f"{CASE}: models_used is empty — the run recorded no model"
    assert set(result.models_used) <= set(chain_builds), (
        f"{CASE}: models_used names a build outside the injected chain "
        f"({result.models_used} vs {chain_builds})")
    assert result.models_used[0] == chain_builds[0], (
        f"{CASE}: the first model used must be the panel's seat 0 ({chain_builds[0]!r}), "
        f"got {result.models_used[0]!r}")

    # --- exactly two artifacts, named after the package (design §3.1) --------------------------
    written = sorted(path.name for path in output_dir.iterdir())
    assert written == sorted({result.draft_path.name, result.report_path.name}), (
        f"{CASE}: the headless draft must write exactly its two artifacts, wrote {written}")
    assert result.draft_path.name.endswith(".package.draft.toml"), (
        f"{CASE}: the draft artifact is not <package>.package.draft.toml "
        f"({result.draft_path.name})")
    assert result.report_path.name.endswith(".authoring-report.md"), (
        f"{CASE}: the report artifact is not <package>.authoring-report.md "
        f"({result.report_path.name})")
    assert result.draft_path.is_file() and result.report_path.is_file(), (
        f"{CASE}: the named artifacts do not exist on disk")

    # --- zero egress, positively (CT-CONSOLE-01's isolation arm) --------------------------------
    network_guard.assert_no_network()