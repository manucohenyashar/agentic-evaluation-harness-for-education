"""The screen context a context-aware ask carries (FR-HELP-06, 1.13-delta §3.5).

The help panel sends, with the question, the screen it was asked from: the screen's id and the
opaque object refs that screen already renders (`CT-UI-07`). The ids are carried verbatim — the
assistant never resolves a ref to the object it names, so no store read stands between the ask
and the model, and nothing but the ids themselves can reach the prompt.

`parse_screen_context` is the privacy clause's server-side shape: the request's ``context``
value is admitted only as an object carrying exactly ``screen`` (a non-empty string) and
``refs`` (a list of non-empty strings, possibly empty). Anything else — a bare string, a
number, an unknown key a client could smuggle free text through — is refused with the named
gap, so the only channel from a screen to the model's prompt is the channel the design names.

The ids themselves are held to the shape every id in this system has: a slug without
whitespace. A ref that carries whitespace is prose, not an identifier — a student name ("Zelda
Quartermaine") or a fragment of paper text — so it is refused at the edge (RS-14: the
assembled prompt must never carry student text, including text hidden in a ref). The server
cannot recognize a name it was never told, and a single-token word slips this rule; the
assembled-prompt sweep (`TC-HELP-06`'s privacy arm) is the backstop, and the SPA-side rule
(`CT-UI-07`, `TC-UI-18`) is the primary one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: A whitespace character anywhere in an id means the value is prose, not an identifier:
#: student names carry spaces, paper text is sentences, and every id this system mints is a
#: slug ("c-help-7Q", "pkg-…", "d-…"). Refused rather than escaped (RS-14, `CT-UI-07`).
#: ``str.isspace`` rather than an ASCII set, so a non-breaking space — which a raw-text sweep
#: would not match against its spaced form — is refused here too.


def _is_identifier(value: Any) -> bool:
    """Whether ``value`` is a non-empty string with no whitespace in it — the shape of an
    opaque id, as opposed to a name or a passage of text."""
    return isinstance(value, str) and bool(value) and not any(c.isspace() for c in value)


@dataclass(frozen=True)
class ScreenContext:
    """One ask's screen context: the screen id and the opaque refs the screen renders.

    ``refs`` are identity only — never a name, never paper text (`CT-UI-07`); the prompt
    carries them as the identifiers they are, next to the manuals, and the grounding rules
    stay unchanged (`FR-HELP-06`).
    """

    screen: str
    refs: tuple[str, ...] = ()


def parse_screen_context(value: Any) -> ScreenContext:
    """The request's ``context`` value as a :class:`ScreenContext`, or a `ValueError` naming
    the gap. Admits exactly ``{"screen": <id>, "refs": [<id>...]}`` — ``refs`` optional and
    empty by default, every id a non-empty slug without whitespace (a value that carries
    whitespace is prose, not an identifier, and prose never rides to the model: RS-14). Every
    other shape is refused, unknown keys included, so nothing but screen identity and opaque
    refs can reach the prompt."""
    if isinstance(value, ScreenContext):
        return value
    if not isinstance(value, dict):
        raise ValueError(
            f"the ask's context must be an object {{screen, refs}}, got "
            f"{type(value).__name__} (FR-HELP-06)"
        )
    unknown = sorted(set(value) - {"screen", "refs"})
    if unknown:
        raise ValueError(
            f"the ask's context carries unknown key(s) {unknown}: only screen and refs are "
            "admitted (FR-HELP-06, CT-UI-07 — no free-text channel to the model)"
        )
    screen = value.get("screen")
    if not _is_identifier(screen):
        raise ValueError(
            f"the ask's context names no screen: 'screen' must be a non-empty id without "
            f"whitespace, got {screen!r} (FR-HELP-06)"
        )
    refs_value = value.get("refs", ())
    if not isinstance(refs_value, (list, tuple)) or not all(
        _is_identifier(ref) for ref in refs_value
    ):
        raise ValueError(
            f"the ask's context refs must be a list of ids without whitespace, got "
            f"{refs_value!r} (FR-HELP-06 — the same opaque ids the screens already render, "
            "never student names or paper text, CT-UI-07)"
        )
    return ScreenContext(screen=screen, refs=tuple(refs_value))
