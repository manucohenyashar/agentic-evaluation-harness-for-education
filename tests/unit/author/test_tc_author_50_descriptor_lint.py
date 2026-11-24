"""`TC-AUTHOR-50` (issue #904; FR-AUTHOR-34) — the descriptor lint's table: a descriptor that
leans on an evaluative word (as a whole word) gets the review screen's note; one that says
what the answer does gets none.

Statistical validity test plan r2 §3.21, story T20. The served half (the note on the review
read, and approval not refused by it) is
`tests/integration/author/test_tc_author_49_50_band_descriptors.py`.

| Descriptor | Note? | Why |
|---|---|---|
| "a good answer" | yes | `good` |
| "names the law and applies it" | no | says what the answer does |
| "clearly states the conclusion" | yes | `clearly`, a whole word |
| "unclear" | no | `clear` inside a word is not a whole-word match |
| "says the keeper feels unwell", "names the goodwill of the fishermen" | no | `well`, `good` inside a longer word |
| "Clearly names Tomas" | yes | case-insensitive |

**Added rows, disclosed.** "unclear" alone cannot catch a lint that drops the whole-word
rule: the listed word is `clearly`, not `clear`, so "unclear" holds no listed word even as a
substring (mutation-checked: removing the `\\b` anchors left the plan's four rows green). The
two substring rows carry the whole-word property the plan's "unclear" row names.

**The oracle is the delta's own sentence**, written out here, and the table is literal — never
read from `AUTHOR_EVALUATIVE_TERMS`, so an oracle cannot widen with the implementation. The
configured extension (`HARNESS_AUTHOR_EVALUATIVE_TERMS`) is cleared for the table and exercised
once on its own.

**Isolation: rung 1.** **Written ahead of implementation: no, in effect** (#870 merged; the
issue says `yes`).

Markers. None: the fast tier.
"""

from __future__ import annotations

import pytest

from aeh.author import descriptor_note


def _note(descriptor: str) -> str:
    return (f"'{descriptor}' says how good the answer is; the grader does better with what "
            "the answer does, for example 'names the law and applies it to the case'.")


@pytest.fixture(autouse=True)
def _no_configured_terms(monkeypatch):
    monkeypatch.delenv("HARNESS_AUTHOR_EVALUATIVE_TERMS", raising=False)


@pytest.mark.parametrize("descriptor, noted", [
    ("a good answer", True),
    ("names the law and applies it", False),
    ("clearly states the conclusion", True),
    ("unclear", False),
    # The whole-word rule's own rows: a listed word inside a longer word is not a match.
    ("says the keeper feels unwell", False),
    ("names the goodwill of the fishermen", False),
    ("Clearly names Tomas", True),
])
def test_tc_author_50_the_lint_table(descriptor: str, noted: bool) -> None:
    assert descriptor_note(descriptor) == (_note(descriptor) if noted else None)


def test_tc_author_50_the_configured_extension_is_read_at_call_time(monkeypatch) -> None:
    descriptor = "gives a decent reason"
    assert descriptor_note(descriptor) is None
    monkeypatch.setenv("HARNESS_AUTHOR_EVALUATIVE_TERMS", "decent")
    assert descriptor_note(descriptor) == _note(descriptor)
