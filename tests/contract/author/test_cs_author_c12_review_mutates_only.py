"""CT-AUTHOR-12 — review mutates only the draft it was given and rewrites only its report (TS-165, #689).

| TC ID | Clause | Breaks if |
|---|---|---|
| TC-AUTHOR-C12 | CT-AUTHOR-12 state | the scripted review writes anywhere but the two artifacts — a new file, a moved file, or a touched neighbour |

AF-07 is the corpus's review fixture: its inventory cannot fill `model_answer`, so the scripted
review has real items to answer, and its `expected.toml` class says the review completes to
*ready*. The answers are plain prose — `model_answer` is free text and `approved_by` names the
teacher — so the walk's re-validation must accept them; if it does not, the red names the clause.

Rung 1, guards first (#689 then #686). The placeholder item ids are the sentinel fields
(`tests/support/author_vocabulary.py`, `PLACEHOLDER_FIELDS_AS_ITEM_IDS`).
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
    placeholder_fields,
    scripted_answers,
    sha256_of,
)
from tests.support.impl import require, require_attr, require_path

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]


def test_tc_author_c12_review_writes_only_the_draft_and_its_report(
        tmp_path, make_fixture_provider):
    """Draft AF-07, snapshot every file, run the scripted review, and compare: the file set is
    unchanged, the two artifacts changed, the seeded neighbour did not, and the answers landed
    in the draft with no sentinel left."""
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    require_attr(author, "AuthoringInputError", issue=AUTHOR_ISSUE)
    af07 = require_path(af("AF-07"), "the AF-07 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)

    out = tmp_path / "out"
    service = make_service(author, chain_from_config(), make_fixture_provider(recordings))
    result = service.draft(documents=sorted(af07.glob("*.pdf")), output_dir=out)

    neighbour = out / "keep-me.txt"
    neighbour.write_bytes(b"unrelated\n")
    before = {p.name: sha256_of(p) for p in out.iterdir()}
    draft_text = result.draft_path.read_text(encoding="utf-8")
    assert placeholder_fields(draft_text), "AF-07 must leave model_answer placeholders"

    answers = scripted_answers(author, draft_text, {
        field: ("Sample-materials teacher" if "approved" in field.lower()
                else "The teacher's model answer for this question.")
        for field in placeholder_fields(draft_text)})
    review = service.review(draft_path=result.draft_path, answers=answers)

    # AF-07's outcome class: the review completes to ready.
    assert review.ready is True and review.remaining == (), review
    after = {p.name: sha256_of(p) for p in out.iterdir()}
    assert set(after) == set(before), f"review created or removed files: {set(after) ^ set(before)}"
    assert after["keep-me.txt"] == before["keep-me.txt"], "a neighbour file was touched"
    for name in (result.draft_path.name, result.report_path.name):
        assert after[name] != before[name], f"{name} was not rewritten by the review"

    rewritten = result.draft_path.read_text(encoding="utf-8")
    assert not placeholder_fields(rewritten), "a ready draft still carries a sentinel"
    for answer in answers:
        assert answer.value in rewritten, (
            f"{answer.item_id}: the answer never reached the draft")