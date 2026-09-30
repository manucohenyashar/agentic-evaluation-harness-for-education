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
    """A field off a store row, whichever shape the tier returned. Real handles hand back
    `sqlite3.Row` (indexable, not a dict); the audit double hands back dicts."""
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
    """One first-class skip control with its cost beside it — the two are read together
    or the cost is not informing the decision (`R62`). The affordance and the cost live
    in one `data-role="skip"` element so the same-view rule is structural, not layout."""
    return (
        '<div data-role="skip"><p>Not now — skip this step.</p>'
        f"<p>If you skip: {escape(cost)}</p></div>"
    )


def _prompt_section(title: str, body: str, cost: str) -> str:
    """One non-blocking prompt: what it asks, and the skip control **with its cost in the
    same view** (invariant 1). A prompt that renders without a skip is the third blocking
    confirmation §11.6 forbids by count; one whose cost lives on another page is the
    version of it R62 rejects."""
    return (
        f'<section data-role="prompt"><h2>{escape(title)}</h2>'
        f"<p>{escape(body)}</p>"
        + _skip_control(cost)
        + "</section>"
    )


def _band_control(name: str) -> str:
    """One editable band select. The control is never `disabled` — a disabled select is
    the shape a read-only view takes, and invariant 16 exists to forbid that shape."""
    options = "".join(
        f'<option value="{escape(band)}">{escape(band)}</option>' for band in REVIEW_BANDS
    )
    return (
        f'<select name="{escape(name)}" data-role="band" '
        f'aria-label="band for {escape(name)}">{options}</select>'
    )


def _band_section(scope: str) -> str:
    """The correction interface a grade-bearing screen carries even when the store
    returns no rows: the band interface is the view's structure, not its data, so an
    empty read leaves the teacher the same way to change a band."""
    return _section(
        "band-correction",
        f"Change a band for {escape(scope)}: choose the corrected band; the amendment "
        "writes a new grade revision and preserves the delivered one.",
    ) + _band_control(f"band_{scope}")


def n_value(row: Any) -> int:
    """The `n` column off a grouped row, whichever shape the tier returned."""
    try:
        return int(_row_get(row, "n", 0) or 0)
    except (TypeError, ValueError):
        return 0


# --- serving: one in-process HTTP server (ADR-17) ----------------------------------------------

def _stylesheet_bytes() -> bytes:
    """The packaged stylesheet's bytes (`aeh/console_assets/console.css`).

    Read from the installed package rather than from a path relative to the source tree, so
    an installed wheel serves the same bytes a checkout does (#358's packaging)."""
    # This file is aeh/console/html.py; the stylesheet ships in aeh/console_assets/.
    return (Path(__file__).resolve().parent.parent / "console_assets" / "console.css").read_bytes()
