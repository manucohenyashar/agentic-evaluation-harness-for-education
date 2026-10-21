"""Every refusal in three parts (FR-UI-25, CT-CONSOLE-33): what happened, why, and what to
do next — each a full sentence — on every refused action and every refusing read.

The outcomes that predate the three-part shape carry a teacher `detail` (an action) or an
`error` (a read) and, for some, a `next_action`. This is where they gain the other parts,
at the API boundary, so no refusal reaches the screen without them: `why` is the refusal's
own sentence; `what` and `next_action` are the outcome's own when it set them, and
otherwise the plain fallbacks below. An outcome that states its parts at source (the
approve refusals, FR-CONSOLE-73) keeps them.

A refusal never echoes an internal reference it was handed (FR-UI-23): a UUID — a run or job
id the teacher never typed — is replaced by "that one" in the refusal's text.
"""

from __future__ import annotations

import re
from typing import Any

_UUID = re.compile(
    r"'?\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b'?")
_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*\Z")

ACTION_NEXT = "Check what the screen shows, then try again."
READ_WHAT = "That could not be shown."
READ_NEXT = "Go back, choose again from the list on the screen, and try once more."


def without_references(text: str) -> str:
    """`text` with every UUID it echoes replaced by "that one"."""
    return _UUID.sub("that one", text)


def sentence(text: Any) -> str:
    """`text` as one full sentence: stripped and ending in `.`, `!` or `?` (a closing quote
    or bracket may follow). Empty stays empty. The first letter is left as written: a
    sentence may open with a test name such as ``eng8-essay-01``, which is not recased."""
    said = without_references(str(text or "")).strip()
    if not said:
        return ""
    if not _SENTENCE_END.search(said):
        said = said.rstrip(":;,—– ") + "."
    return said


def action_what(action: str) -> str:
    return f"Nothing was changed: “{action}” did not go through."


def refusal_parts(*, why: Any, what: Any = None, next_action: Any = None,
                  fallback_what: str, fallback_next: str) -> dict[str, str]:
    """The three parts of one refusal, each a sentence."""
    because = sentence(why) or "The console could not do it."
    return {
        "what": sentence(what) or fallback_what,
        "why": because,
        "next_action": sentence(next_action) or fallback_next,
    }


def read_refusal(error: Any, **extra: Any) -> dict[str, Any]:
    """A refusing read's (or a refused request's) body: the `error` sentence kept for the
    callers that read it, with the three parts beside it."""
    said = without_references(str(error))
    return {**extra, "error": said,
            **refusal_parts(why=said, fallback_what=READ_WHAT, fallback_next=READ_NEXT)}


__all__ = [
    "action_what",
    "read_refusal",
    "refusal_parts",
    "sentence",
    "without_references",
]
