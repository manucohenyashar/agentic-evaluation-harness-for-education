"""Reading the JSON a model reply carries, when the model wrapped it."""

from __future__ import annotations

import json
import re
from typing import Any

#: One fenced block: ```json … ``` or ``` … ```.
_FENCE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\n(?P<body>.*?)\n?[ \t]*```", re.DOTALL)


def json_from_reply(text: str) -> Any:
    """The JSON value a model reply carries (TC-REG-16).

    Live models wrap JSON they were asked for: in a ```json fence, or after a sentence. The
    reply is read as written first; then the body of its one fenced block; then the span from
    its first `{` to its last `}` — an OBJECT only: a bare list is accepted from a fence, never
    fished out of prose (a sentence ending in `[]`, or the inner array of an object, must not
    read as an answer). The value is never altered — object keys keep their order, so a
    parser's order check still applies — and a reply with no parseable JSON raises the
    ORIGINAL `json.JSONDecodeError`, so every caller's "not JSON" refusal reads exactly as
    before. Prose is never mined for values: an offset written in a sentence is not JSON and is
    refused, and two objects in one reply span invalid JSON and are refused too."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        original = error
    candidates: list[str] = []
    fences = _FENCE.findall(text)
    if len(fences) == 1:
        candidates.append(fences[0])
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise original
