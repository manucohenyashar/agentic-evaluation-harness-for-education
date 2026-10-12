"""CT-AUTHOR-01 and CT-AUTHOR-03 — the headless surface and the declared field sets (TS-165, #689).

| TC ID | Clause | Breaks if |
|---|---|---|
| TC-AUTHOR-C01 | CT-AUTHOR-01 surface | `draft()`/`review()` are synchronous and complete with no network under the injected `RecordedFixtureProvider`, and the `DraftResult` carries a per-stage trace — any path requiring the console, or a bare status with an empty trace, is the top silent-failure trap (`CT-INGEST-08`'s lesson applied to the new module) |
| TC-AUTHOR-C03 | CT-AUTHOR-03 data | `DraftResult`, `StepOutcome`, `ReviewResult`, `ReviewAnswer`, `DraftIssue` carry exactly the §3.1 fields; `ItemStatus` is the four-member literal; `model` stays absent (`None`) rather than empty for an unresolved item |

Both cases are rung 1: the service is constructed in-process with the chain read from the
dev-ci config (`tests/support/author_vocabulary.py` — the corpus's recordings are keyed on the
assembled request, build id included) and a `RecordedFixtureProvider` over
`fixtures/F-AUTHOR/recordings/`. The guards run before anything else: `aeh.author` and the
corpus do not exist yet, so each case fails with `NotImplementedYet` naming its issue.

The `Path` constants (`af`, `RECORDINGS`) are imported at module scope on purpose — they are
data, not the module under test; only `aeh.author` is resolved inside the bodies via `require`.
"""

from __future__ import annotations

import dataclasses
import typing
from pathlib import Path

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
    placeholder_fields,
    scripted_answers,
)
from tests.support.impl import require, require_attr, require_path

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]


def _guards(make_fixture_provider, tmp_path: Path) -> tuple:
    """The surface, then the corpus — in that order, so the red names #689 before #686."""
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    require_attr(author, "AuthoringInputError", issue=AUTHOR_ISSUE)  # FR-AUTHOR-13's type
    corpus = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, corpus, recordings


# --- TC-AUTHOR-C01 ----------------------------------------------------------------------------


def test_tc_author_c01_draft_and_review_run_headless_with_a_per_stage_trace(
        tmp_path, network_guard, make_fixture_provider):
    """`draft()` returns a populated `DraftResult` whose per-stage trace is present, writes both
    artifacts, and `review()` returns a `ReviewResult` — all in-process, all offline."""
    author, corpus, recordings = _guards(make_fixture_provider, tmp_path)
    provider = make_fixture_provider(recordings)
    service = make_service(author, chain_from_config(), provider)

    result = service.draft(documents=sorted(corpus.glob("*.pdf")), output_dir=tmp_path / "out")

    assert isinstance(result, author.DraftResult)
    # Seam 4: the trace sits next to the status, not behind it. An empty outcomes tuple on a
    # successful draft is exactly the bare-status failure CT-AUTHOR-01 forbids.
    assert result.outcomes, "draft() returned no per-stage trace"
    assert result.draft_path.exists() and result.report_path.exists()
    assert result.models_used, "no model is recorded as having produced the draft"
    network_guard.assert_no_network()

    # The review half of the clause: synchronous, scripted (no tty), and a ReviewResult.
    draft_text = result.draft_path.read_text(encoding="utf-8")
    fields = placeholder_fields(draft_text)
    answers = scripted_answers(
        author, draft_text, {field: "Sample-materials teacher" for field in fields})
    review = service.review(draft_path=result.draft_path, answers=answers)
    assert isinstance(review, author.ReviewResult)
    assert review.ready and review.remaining == ()
    network_guard.assert_no_network()


# --- TC-AUTHOR-C03 ----------------------------------------------------------------------------


def test_tc_author_c03_declared_field_sets_and_the_empty_vs_absent_distinctions(
        tmp_path, make_fixture_provider):
    """Every dataclass carries exactly the §3.1 fields and is frozen; `ItemStatus` has exactly
    the four members; a real unresolved run keeps `model` absent, a resolved run keeps
    `failures` empty."""
    author, corpus, recordings = _guards(make_fixture_provider, tmp_path)
    af09 = require_path(af("AF-09"), "the AF-09 authored fixture", issue=CORPUS_ISSUE)

    assert [f.name for f in dataclasses.fields(author.DraftResult)] == [
        "draft_path", "report_path", "outcomes", "placeholders", "resolved", "unresolved",
        "models_used"]
    assert [f.name for f in dataclasses.fields(author.StepOutcome)] == [
        "step", "item_id", "status", "model", "attempts", "failures"]
    assert [f.name for f in dataclasses.fields(author.ReviewResult)] == ["ready", "remaining"]
    assert [f.name for f in dataclasses.fields(author.ReviewAnswer)] == ["item_id", "value"]
    assert [f.name for f in dataclasses.fields(author.DraftIssue)] == ["field", "message"]

    # Frozen: empty collapsing into absent is exactly what a mutable default invites.
    for instance, attr, value in (
        (author.DraftResult(Path("d"), Path("r"), (), 0, 0, 0, ()), "placeholders", 1),
        (author.StepOutcome("inventory", "q", "resolved", "m", 1, ()), "attempts", 2),
        (author.ReviewResult(True, ()), "ready", False),
        (author.ReviewAnswer("i", "v"), "value", "w"),
        (author.DraftIssue("f", "m"), "message", "x"),
    ):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(instance, attr, value)  # noqa: B010

    hints = typing.get_type_hints(author.StepOutcome)
    assert typing.get_args(hints["status"]) == (
        "resolved", "derived", "placeholder", "unresolved")

    provider = make_fixture_provider(recordings)
    chain = chain_from_config()
    # A resolved run: every winning outcome names a model; `failures` may still record the
    # legitimate rejections that came before the winning reply (§3.1's trace contract).
    happy = make_service(author, chain, provider).draft(
        documents=sorted(corpus.glob("*.pdf")), output_dir=tmp_path / "happy")
    assert happy.outcomes
    for outcome in happy.outcomes:
        assert outcome.status in ("resolved", "derived", "placeholder", "unresolved")
        if outcome.status in ("resolved", "derived"):
            assert outcome.model, f"{outcome.item_id}: resolved with no model recorded"
    # Disclosed reconcile (the landing): `approved_by` rides on every outcome class
    # (TC-AUTHOR-12) and is never counted (TC-AUTHOR-01 pins AF-01 at zero), so the count
    # oracle reads the content sentinels — the sign-off slot is excluded here, once.
    assert happy.placeholders == len([field for field in placeholder_fields(
        happy.draft_path.read_text(encoding="utf-8")) if field != "approved_by"])
    # Fully resolved means nothing the reasoning proposed stayed unresolved (AF-01's outcome
    # class). The one placeholder FR-AUTHOR-09 mandates — approved_by, never model-generated —
    # may or may not be counted here depending on #686's expected class; the suite accepts
    # exactly that one and nothing else.
    assert happy.unresolved == 0
    assert set(placeholder_fields(happy.draft_path.read_text(encoding="utf-8"))) <= {
        "approved_by"}, "AF-01 is fully resolved: only approved_by may be a placeholder"

    # A failing run (AF-09: contradictory grading): unresolved items keep model ABSENT —
    # `None`, not "" — and carry the failure reasons that got them there.
    failed = make_service(author, chain, provider).draft(
        documents=sorted(af09.glob("*.pdf")), output_dir=tmp_path / "failed")
    unresolved = [o for o in failed.outcomes if o.status == "unresolved"]
    assert unresolved, "AF-09's contradictory description must leave items unresolved"
    for outcome in unresolved:
        assert outcome.model is None, f"{outcome.item_id}: unresolved with a model recorded"
        assert outcome.failures, f"{outcome.item_id}: unresolved with no failure reasons"