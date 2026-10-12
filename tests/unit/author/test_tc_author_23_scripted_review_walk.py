"""`TC-AUTHOR-23` (FR-AUTHOR-16, P0) — the scripted review rewrites the draft in place,
re-validates it, and records every answer with its fingerprint; an answer that fails
re-validation is rejected, the item stays open, and nothing invalid lands (#713, the
package-authoring test plan §5.2; design delta §3.1, Q-O9).

Written ahead of #696: the file carried `writtenahead`, keyed `#713 review walk, rung 1` in
`WRITTEN_AHEAD_BLOCKERS`, and ran red until the review walk landed; the marker came off at
the #696 landing — the test itself was never touched.

Rung 1 (headless in-process), the plan's isolation per case: the recorded provider over the
F-AUTHOR recordings (`CT-PROV-10`) and the autouse socket guard, asserted zero-egress at the
end — no live calls in this suite.

**The main case is the plan's scripted review of AF-07**: answers supplied in report order —
the placeholder order the draft states, which the report's Items section walks (disclosed:
report order == draft document order). The oracle is the plan's, exactly: the draft is
rewritten *in place* (same path, same file set, the seeded neighbour untouched), the report
is rewritten with the answer rows and their fingerprint rows, re-validation passes (the
review completes to ready — AF-07's outcome class), and no sentinel survives.

**The Q-O9 variant needs an answer re-validation can actually reject, and AF-07 cannot
supply one**: its placeholders (`model_answer`, `approved_by`) are free text no structural
rule constrains, so a "rejected" answer there would be theatre. The variant therefore runs
against AF-08, the corpus's key-placeholder fixture ("key placeholders for the unkeyed items
3 and 5"): its `key` field is the one field the key-in-options rule (FR-AUTHOR-10) can
reject. The invalid answer is derived from the draft itself — an option letter no mcq
question declares — so the rejection is exact, not a guess about the corpus's option letters.
The oracle is Q-O9's: the answer is rejected, the item stays open, the invalid value never
enters the draft, and the report is still rewritten — the system never accepts an invalid
value silently.

Item ids are the sentinel fields (`tests/support/author_vocabulary.py`,
`PLACEHOLDER_FIELDS_AS_ITEM_IDS`); fingerprints are assumed hex hashes of at least 12
characters (`FINGERPRINT_RE` in the vocabulary — the design pins "the hash over the item's
id and underlying content" but not its rendering). Both reconcile at the landing with
one-line changes here.
"""

from __future__ import annotations

import tomllib

from tests.support.author_vocabulary import (
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    FINGERPRINT_RE,
    RECORDINGS,
    REVIEW_ISSUE,
    af,
    chain_from_config,
    make_service,
    placeholder_fields,
    scripted_answers,
    sha256_of,
)
from tests.support.impl import require, require_attr, require_path

TEACHER = "Sample-materials teacher"
MODEL_ANSWER = "By equivalent fractions with a common denominator."


def _guards(make_fixture_provider) -> tuple:
    """The require-style gates, and the first thing each test body does: a missing
    implementation is `NotImplementedYet` naming the blocker — never a collection error."""
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself — #689's
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names — #689's
    require_attr(author.AuthoringService, "review", issue=REVIEW_ISSUE)  # #696's new surface
    af07 = require_path(af("AF-07"), "the AF-07 authored fixture", issue=CORPUS_ISSUE)
    af08 = require_path(af("AF-08"), "the AF-08 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, af07, af08, recordings


def _invalid_key_letter(draft_text: str) -> str:
    """An option letter no mcq question in the draft declares — the failing answer.

    Derived from the draft, not guessed: the sentinel `key` placeholders sit in
    `[[criterion]]` lines (the spec vocabulary, FR-PKG-27's export shape) and the options
    they must be drawn from are their questions' `options` tables.
    """
    data = tomllib.loads(draft_text)
    sentinel_keys = [c for c in data.get("criterion", [])
                     if isinstance(c.get("key"), str) and c["key"].startswith("<<PLACEHOLDER:")]
    assert sentinel_keys, (
        "AF-08's draft must carry its key placeholders inside [[criterion]] (the spec "
        f"vocabulary); got tables {sorted(data)}")
    option_letters = {letter
                      for question in data.get("question", [])
                      if question.get("type") == "mcq"
                      for letter in (question.get("options") or {})}
    assert option_letters, "AF-08's mcq questions must declare options"
    return next(letter for code in range(ord("A"), ord("Z") + 1)
                if (letter := chr(code)) not in option_letters)


def test_tc_author_23_the_scripted_review_rewrites_the_draft_and_report_in_place(
        tmp_path, make_fixture_provider, network_guard):
    """Draft AF-07, snapshot every file, run the scripted review with answers in report
    order, and compare: exactly the two artifacts changed, the answers and their fingerprint
    rows are in the report, the answers are in the draft, no sentinel survives, and the
    review completes to ready."""
    author, af07, _af08, recordings = _guards(make_fixture_provider)

    out = tmp_path / "out"
    service = make_service(author, chain_from_config(), make_fixture_provider(recordings))
    result = service.draft(documents=sorted(af07.glob("*.pdf")), output_dir=out)

    neighbour = out / "keep-me.txt"
    neighbour.write_bytes(b"unrelated\n")
    before = {p.name: sha256_of(p) for p in out.iterdir()}
    draft_text = result.draft_path.read_text(encoding="utf-8")
    fields = placeholder_fields(draft_text)
    assert fields, "AF-07 must leave placeholders for the review to fill"

    answers = scripted_answers(author, draft_text, {
        "approved_by": TEACHER,
        "model_answer": MODEL_ANSWER,
    })
    review = service.review(draft_path=result.draft_path, answers=answers)

    # AF-07's outcome class: the review completes to ready — re-validation passed.
    assert review.ready is True and review.remaining == (), review

    # Exactly the two artifacts were rewritten, in place: same file set, the neighbour
    # untouched, both artifacts' content changed.
    after = {p.name: sha256_of(p) for p in out.iterdir()}
    assert set(after) == set(before), f"review changed the file set: {set(after) ^ set(before)}"
    assert after["keep-me.txt"] == before["keep-me.txt"], "a neighbour file was touched"
    for name in (result.draft_path.name, result.report_path.name):
        assert after[name] != before[name], f"{name} was not rewritten by the review"

    # The rewritten draft carries every answer and no sentinel.
    rewritten = result.draft_path.read_text(encoding="utf-8")
    assert not placeholder_fields(rewritten), "a ready draft still carries a sentinel"
    for answer in answers:
        assert answer.value in rewritten, (
            f"{answer.item_id}: the answer never reached the draft")

    # The rewritten report carries the answer records and their fingerprints (FR-AUTHOR-12,
    # CT-AUTHOR-19): per answered item a row naming the item and the answer, and a content
    # fingerprint per answered item.
    report = result.report_path.read_text(encoding="utf-8")
    for answer in answers:
        assert any(answer.item_id in line and answer.value in line
                   for line in report.splitlines()), (
            f"{answer.item_id}: the report has no answer record row")
    fingerprints = set(FINGERPRINT_RE.findall(report))
    assert len(fingerprints) >= len(answers), (
        f"the report lacks fingerprint rows for {len(answers)} answers; found "
        f"{len(fingerprints)} fingerprint-looking tokens")

    # Isolation, positively: zero egress across the draft and the review.
    network_guard.assert_no_network()


def test_tc_author_23_q_o9_an_answer_that_fails_revalidation_is_rejected(
        tmp_path, make_fixture_provider, network_guard):
    """AF-08's `key` placeholder answered with a letter no question declares: the review
    rejects it — the item stays open, the invalid value never enters the draft, the report
    is still rewritten. Never silently invalid (Q-O9)."""
    author, _af07, af08, recordings = _guards(make_fixture_provider)

    out = tmp_path / "out"
    service = make_service(author, chain_from_config(), make_fixture_provider(recordings))
    result = service.draft(documents=sorted(af08.glob("*.pdf")), output_dir=out)

    draft_text = result.draft_path.read_text(encoding="utf-8")
    assert "key" in placeholder_fields(draft_text), (
        "AF-08 must leave key placeholders for the unkeyed items")
    invalid = _invalid_key_letter(draft_text)
    report_before = sha256_of(result.report_path)

    review = service.review(
        draft_path=result.draft_path,
        answers=[author.ReviewAnswer(item_id="key", value=invalid)])

    # The answer is rejected: not ready, the item stays open and is named.
    assert review.ready is False, review
    assert "key" in review.remaining, (
        f"the rejected answer's item must stay in remaining, got {review.remaining!r}")

    # Never silently invalid: the invalid value never landed, the sentinel is still there.
    rewritten = result.draft_path.read_text(encoding="utf-8")
    assert "key" in placeholder_fields(rewritten), (
        "the rejected answer's sentinel must survive — the item stays open")
    criteria = tomllib.loads(rewritten).get("criterion", [])
    assert not [c for c in criteria if c.get("key") == invalid], (
        f"the invalid key {invalid!r} entered the draft despite failing re-validation")

    # The report is still rewritten (FR-AUTHOR-16) — the walk's outcome is recorded even
    # when the answer it was given was refused.
    assert sha256_of(result.report_path) != report_before, (
        "the report was not rewritten after the rejected answer")

    network_guard.assert_no_network()