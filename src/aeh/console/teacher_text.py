"""The teacher-text boundary (FR-CONSOLE-71, CT-CONSOLE-53, ADR-53).

Every string the console API returns for display passes through `teacher_text()` on its
way out. The function is pure and a safety net, not the fix: the strings a teacher meets
most are written in teacher words at their source (FR-CONSOLE-73's approve outcomes, the
package summary). What it does, and all it does:

(a) drops a parenthetical whose contents are only requirement or test IDs, with the space
    before it — ``"x (FR-AUTHOR-08)"`` → ``"x"``, ``"x (FR-PKG-28, CT-PKG-03)."`` → ``"x."``;
(a') inside a parenthetical that also carries words, drops the IDs and the separator beside
    them — ``"(ADR-47, console memory)"`` → ``"(console memory)"``,
    ``"(FR-CONSOLE-43: a run's profile is named per request)"`` → ``"(a run's profile is
    named per request)"``. The words stay; only the reference goes (the census, ADR-53,
    found engineering asides of this shape on several reads);
(b) replaces a package-version id (``<package>@<12 hex>``) with the package name and the
    teacher label the caller's `version_label` resolver gives it
    (``"ENG7-READ-01@e34abeaceb0a"`` → ``"ENG7-READ-01 version 1"``, FR-CONSOLE-74); with
    no resolver, or one that does not know the version, the package name stands alone,
    because the hash never reaches a teacher either way;
(c) leaves everything else untouched — ``"answer (Q2)"`` and ``"(2 of 3)"`` are the
    teacher's own words.

`teacher_payload()` applies it to every string in a JSON-shaped answer except identifier
fields, which the SPA sends back to the API and which must keep their exact value: a key
named ``id`` or ending in ``_id``, ``_ids`` or ``_ref`` (the census exempts ids by name,
FR-UI-23). The `<package>@<hash>` form stays in those fields, in exports and in logs; it is
internal (FR-CONSOLE-74).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

#: A requirement or test ID, FR-UI-23's first pattern widened to the multi-part forms the
#: design uses (`FR-AUTHOR-08`, `NFR-CONSOLE-06`, `TC-REG-18`, `RS-08`), optionally quoted
#: in backticks the way source strings often carry them.
_ID = r"`?\b(?:FR|NFR|CT|TC|ADR|RS)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b`?"
_SEPARATOR = r"\s*(?:,|;|/|\band\b|·)\s*"
#: (a): a parenthetical holding only IDs, with the whitespace before it, so
#: ``"x (FR-PKG-28)."`` reads ``"x."`` rather than ``"x ."``.
_ID_PARENTHETICAL = re.compile(rf"\s*\(\s*{_ID}(?:{_SEPARATOR}{_ID})*\s*\)")
#: (a'): a run of IDs opening the parenthetical and closed by a separator
#: (``"ADR-47, console memory"``, ``"FR-CONSOLE-43: a run's profile"``), or a run closing
#: it after a separator (``"console memory, ADR-47"``). An ID inside prose
#: (``"see FR-PKG-28 for details"``, ``"RS-232 cable"``) is left alone: cutting it would
#: leave broken words, and the census still reports it.
_ID_IN_WORDS = re.compile(
    rf"^\s*{_ID}(?:{_SEPARATOR}{_ID})*\s*(?:[,;:·—–]|\s-\s)\s*(?=\S)"
    rf"|\s*(?:[,;·]|\band\b)\s*{_ID}(?:{_SEPARATOR}{_ID})*\s*$")
_INNER_PARENTHETICAL = re.compile(r"\(([^()]*)\)")
_ANY_ID = re.compile(_ID)

#: A package-version id: the package id, `@`, and twelve lowercase hex digits
#: (`aeh.pkg.versions` mints them as `f"{package_id}@{uuid4().hex[:12]}"`).
VERSION_ID_PATTERN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)@([0-9a-f]{12})\b")

#: The resolver a caller passes: the full version id in, the teacher label for that
#: version (``"version 1"``) out, or `None` when it does not know the version.
VersionLabel = Callable[[str], "str | None"]


def _words_only(match: re.Match[str]) -> str:
    inner = match.group(1)
    if not _ANY_ID.search(inner):
        return match.group(0)
    return f"({_ID_IN_WORDS.sub('', inner).strip()})"


def teacher_text(text: str, *, version_label: VersionLabel | None = None) -> str:
    """`text` with requirement IDs taken out of its parentheticals and package-version ids
    replaced by their teacher label; anything else unchanged. Pure: the resolver is the
    caller's, and this function reads no store. Applying it twice changes nothing more."""
    if not text:
        return text
    cleaned, previous = text, None
    while cleaned != previous:  # nested asides: an outer one is innermost on the next pass
        previous = cleaned
        cleaned = _ID_PARENTHETICAL.sub("", cleaned)
        cleaned = _INNER_PARENTHETICAL.sub(_words_only, cleaned)

    def label(match: re.Match[str]) -> str:
        package = match.group(1)
        resolved = version_label(match.group(0)) if version_label is not None else None
        return f"{package} {resolved}" if resolved else package

    return VERSION_ID_PATTERN.sub(label, cleaned)


def is_identifier_key(key: str) -> bool:
    """Whether a field's value is an identifier, exempt from the boundary."""
    return key == "id" or key.endswith(("_id", "_ids", "_ref"))


def teacher_payload(value: Any, version_label: VersionLabel | None = None) -> Any:
    """A JSON-shaped answer with `teacher_text()` applied to every display string: every
    string value, in dicts and lists at any depth, except under an identifier key (whose
    whole value is kept). Keys, numbers, booleans and `None` pass through."""
    if isinstance(value, str):
        return teacher_text(value, version_label=version_label)
    if isinstance(value, dict):
        return {
            key: (inner if isinstance(key, str) and is_identifier_key(key)
                  else teacher_payload(inner, version_label))
            for key, inner in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [teacher_payload(inner, version_label) for inner in value]
    return value


__all__ = [
    "VERSION_ID_PATTERN",
    "VersionLabel",
    "is_identifier_key",
    "teacher_payload",
    "teacher_text",
]
