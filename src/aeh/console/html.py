"""Small HTML building blocks shared by every screen, and the packaged stylesheet."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from .vocabulary import REVIEW_BANDS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_get(row: Any, key: str, default: Any = "") -> Any:
    """One field from a store row, whatever shape the tier returned: real handles return
    `sqlite3.Row` (indexable, not a dict) and the audit double returns dicts."""
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return getattr(row, key, default)


# --- the HTML shell -----------------------------------------------------------------------------------
#
# One local stylesheet, no scripts, no images of any external origin. The markup markers
# (`data-role`) are the anchors the contract tests read (`elements`, `element_text`); a page
# that loses one loses the assertion built on it, loudly.

_STYLESHEET = '<link rel="stylesheet" href="/assets/console.css">'


#: The stated limitation (`NFR-CONSOLE-07`, `CT-CONSOLE-24`): English and left-to-right
#: only in the MVP, named on **every** page the shell renders — a deliberate limitation
#: recorded in the UI, never an omission discovered in the field. The phrasing is the
#: honesty contract's: "deliberate", not "known issue"; "may be misordered", a visible
#: degradation an operator who does not read the language can still notice.
_LIMITATION_SECTION = (
    '<section data-role="limitation"><p>This console renders English and left-to-right '
    "only in the MVP — a deliberate limitation, not an oversight "
    "(NFR-CONSOLE-07). Non-English and right-to-left text may be misordered here; "
    "localisation and RTL support are a real later requirement.</p></section>"
)


def _page(title: str, body: str, *, poll_interval_ms: int | None = None) -> str:
    meta = (
        f'<meta http-equiv="refresh" content="{poll_interval_ms // 1000}">'
        if poll_interval_ms
        else ""
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{escape(title)}</title>{meta}{_STYLESHEET}</head>"
        f"<body><h1>{escape(title)}</h1>{body}{_LIMITATION_SECTION}</body></html>"
    )


def _section(role: str, *lines: str) -> str:
    inner = "".join(f"<p>{line}</p>" for line in lines)
    return f'<section data-role="{role}">{inner}</section>'


def _label_line(label: str, value: Any) -> str:
    return f"<p>{escape(label)}: {escape(str(value))}</p>"


# --- the skip affordance (HLD §11.6 invariant 1, `FR-CONSOLE-06`) ---------------------------------------
#
# "Exactly two screens shall block … every other prompt offers a first-class skip control and
# states the cost of skipping in the same view." R62's reason is the *same view*: "a skip control
# whose consequence is explained on another page is the design HLD R62 rejects." So the control
# and its cost are one element, and the cost is a sentence a reader takes in at the moment of
# deciding — not a link to an explanation somewhere else.


def _skip_control(cost: str) -> str:
    """A skip button with its cost shown next to it; the cost only informs the decision if both are
    read together (R62). Both live in one `data-role="skip"` element, so keeping them together does
    not depend on layout."""
    return (
        '<div data-role="skip"><p>Not now — skip this step.</p>'
        f"<p>If you skip: {escape(cost)}</p></div>"
    )


def _prompt_section(title: str, body: str, cost: str) -> str:
    """One non-blocking prompt: its question, plus a skip button with its cost in the same view
    (invariant 1). A prompt with no skip would be a third blocking confirmation, which §11.6
    forbids; a cost shown on another page is what R62 rejects."""
    return (
        f'<section data-role="prompt"><h2>{escape(title)}</h2>'
        f"<p>{escape(body)}</p>"
        + _skip_control(cost)
        + "</section>"
    )


def _band_control(name: str) -> str:
    """One editable band dropdown. It is never `disabled`, because a disabled dropdown is how a
    read-only view looks, and invariant 16 forbids that."""
    options = "".join(
        f'<option value="{escape(band)}">{escape(band)}</option>' for band in REVIEW_BANDS
    )
    return (
        f'<select name="{escape(name)}" data-role="band" '
        f'aria-label="band for {escape(name)}">{options}</select>'
    )


def _band_section(scope: str) -> str:
    """The band-correction controls a grade screen shows even when the store returns no rows. They
    are part of the screen's structure, not its data, so an empty result still lets the teacher
    change a band."""
    return _section(
        "band-correction",
        f"Change a band for {escape(scope)}: choose the corrected band; the amendment "
        "writes a new grade revision and preserves the delivered one.",
    ) + _band_control(f"band_{scope}")


def n_value(row: Any) -> int:
    """The `n` column from a grouped row, whatever shape the tier returned."""
    try:
        return int(_row_get(row, "n", 0) or 0)
    except (TypeError, ValueError):
        return 0


# --- serving: one in-process HTTP server (ADR-17) ----------------------------------------------

def _stylesheet_bytes() -> bytes:
    """The bytes of the packaged stylesheet (`aeh/console_assets/console.css`).

    Read from the installed package rather than from a path relative to the source tree, so
    an installed wheel serves the same bytes a checkout does (#358's packaging)."""
    # This file is aeh/console/html.py; the stylesheet ships in aeh/console_assets/.
    return (Path(__file__).resolve().parent.parent / "console_assets" / "console.css").read_bytes()
