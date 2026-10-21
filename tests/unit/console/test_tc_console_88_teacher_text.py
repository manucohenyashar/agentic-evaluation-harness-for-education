"""`TC-CONSOLE-88` (issue #815, FR-CONSOLE-71; RC-15) — what `teacher_text()` does.

Console clarity test plan §3.4, story T4; the property arm is §4.3's.

| Input | Output |
|---|---|
| `"x (FR-AUTHOR-08)"` | `"x"` |
| `"x (FR-PKG-28, CT-PKG-03)."` | `"x."` |
| `"answer (Q2)"` | unchanged — a meaningful parenthetical (RC-15) |
| `"(2 of 3)"` | unchanged |
| `"ENG7-READ-01@e34abeaceb0a"`, stub `version_label` resolver answering "version 1" | `"ENG7-READ-01 version 1"` |
| `""` | `""` |

Applying it twice changes nothing more (idempotent). The property arm: any string carrying no
FR-UI-23 ID pattern comes back unchanged — rule (c), "leaves everything else untouched".

**Interface assumed** (the design names the function and its resolver, not the module):
`aeh.console.teacher_text.teacher_text(text: str, *, version_label: Callable[[str], str])
-> str`. The resolver is handed the whole package-version id (`"ENG7-READ-01@e34abeaceb0a"`)
and answers the teacher label's version part (`"version 1"`); the function writes
`"<package> <label>"` in the id's place. The function is pure (it reads no store); the real
resolver is TC-CONSOLE-89's.

**Isolation: rung 0.** **Written ahead of implementation: yes** (#808) — every case fails
with `NotImplementedYet` until `aeh.console.teacher_text` exists.

**Markers.** `writtenahead`, keyed in `WRITTEN_AHEAD_BLOCKERS` under #808.
"""

from __future__ import annotations

import re

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from tests.support.impl import CONSOLE_MODULE, require

pytestmark = pytest.mark.writtenahead

ISSUE = "#808"
VERSION_ID = "ENG7-READ-01@e34abeaceb0a"

#: The FR-UI-23 ID patterns the property arm keeps out of its inputs.
REQUIREMENT_ID = re.compile(r"\b(FR|NFR|CT|TC|ADR|RS)-[A-Z0-9]+(-\d+)?\b")
VERSION_HASH = re.compile(r"@[0-9a-f]{12}\b")


def _teacher_text():
    return require(f"{CONSOLE_MODULE}.teacher_text", "teacher_text", issue=ISSUE)


class _StubResolver:
    """The stub `version_label` resolver: answers "version 1" and records what it was asked."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def __call__(self, version_id: str) -> str:
        self.asked.append(version_id)
        return "version 1"


def _unused_resolver(version_id: str) -> str:
    raise AssertionError(
        f"the resolver was asked about {version_id!r}, but the input carries no package "
        "version id")


#: (input, expected output) — the plan's table, minus the resolver row (its own case below).
TABLE: tuple[tuple[str, str], ...] = (
    ("x (FR-AUTHOR-08)", "x"),
    ("x (FR-PKG-28, CT-PKG-03).", "x."),
    ("answer (Q2)", "answer (Q2)"),
    ("(2 of 3)", "(2 of 3)"),
    ("", ""),
)


@pytest.mark.parametrize(("given_text", "expected"), TABLE, ids=[repr(t[0]) for t in TABLE])
def test_tc_console_88_teacher_text_table(given_text, expected):
    """TC-CONSOLE-88: an ID-only parenthetical goes (with the space before it); a meaningful
    one stays; empty stays empty; and a second pass changes nothing more."""
    teacher_text = _teacher_text()
    once = teacher_text(given_text, version_label=_unused_resolver)
    assert once == expected, f"teacher_text({given_text!r}) gave {once!r}, not {expected!r}"
    twice = teacher_text(once, version_label=_unused_resolver)
    assert twice == once, f"a second pass changed {once!r} into {twice!r}: not idempotent"


def test_tc_console_88_teacher_text_names_a_version_through_the_resolver():
    """TC-CONSOLE-88: `<package>@<hash>` reads as `<package> version <n>`, the label coming
    from the resolver the caller passes — the function itself reads no store."""
    teacher_text = _teacher_text()
    resolver = _StubResolver()
    once = teacher_text(VERSION_ID, version_label=resolver)
    assert once == "ENG7-READ-01 version 1", (
        f"teacher_text({VERSION_ID!r}) gave {once!r}, not 'ENG7-READ-01 version 1'")
    assert resolver.asked == [VERSION_ID], (
        f"the resolver was asked {resolver.asked!r}; it is handed the whole package-version "
        f"id, once")
    twice = teacher_text(once, version_label=resolver)
    assert twice == once, f"a second pass changed {once!r} into {twice!r}: not idempotent"
    assert resolver.asked == [VERSION_ID], "the second pass found a version id to resolve"

    # Inside a sentence the id is replaced in place and the rest stands.
    sentence = teacher_text(f"Published {VERSION_ID}. Next: load the papers.",
                            version_label=_StubResolver())
    assert sentence == "Published ENG7-READ-01 version 1. Next: load the papers.", sentence


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=80))
def test_tc_console_88_teacher_text_leaves_id_free_text_unchanged(text):
    """§4.3's property arm of TC-CONSOLE-88: for any string without an ID pattern,
    `teacher_text(s) == s`."""
    assume(not REQUIREMENT_ID.search(text) and not VERSION_HASH.search(text))
    teacher_text = _teacher_text()
    assert teacher_text(text, version_label=_unused_resolver) == text
