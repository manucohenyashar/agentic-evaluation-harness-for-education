"""The manuals pages as the server-rendered console serves them (M-HELP, FR-HELP-01).

The SPA's Q&A panel cites manual sections, and a citation "resolves" only when following it
lands on a page that carries an element of that id — so the pages the citations point at are
part of the citation rule. They are served here, from the console's server-rendered surface
(the `/assets/console.css` precedent in `server.do_GET`), as pure functions of the packaged
manuals: a read creates and touches no stored byte, and the SPA itself never calls the
manuals reads, so the panel's traffic is exactly the ask endpoint (TC-REQ-129).

Anchors. `aeh.help` derives each section's anchor within its manual; this page renders all
manuals from one origin, so a section's element id is the anchor the read payload carries,
verbatim, and the manual's id rides in the path: a citation is
`/manuals/{manual_id}#{anchor}`. Two pages therefore share the convention — this renderer
owns the target side, the SPA builds the href side — and both quote it in their docstrings.
"""

from __future__ import annotations

from html import escape

from .html import _page
from .help_read import MANUAL_ID_PARAM

_LIBRARY_TITLE = "Manuals"
_MANUAL_TITLE_TEMPLATE = "Manual: {title}"


def _toc_link(manual_id: str, anchor: str, heading: str) -> str:
    quoted = escape(manual_id, quote=True)
    return (
        f'<li><a href="/manuals/{quoted}#{escape(anchor)}">{escape(heading)}</a></li>'
    )


def manuals_library_html() -> str:
    """The library page: every packaged manual with its table of contents, linking into the
    manual's own page at the section's anchor."""
    from aeh.help import load_manuals

    sections = []
    for manual in load_manuals():
        links = "".join(
            _toc_link(manual.manual_id, entry.anchor, entry.heading)
            for entry in manual.toc
        )
        quoted = escape(manual.manual_id, quote=True)
        sections.append(
            f'<section data-role="manual-listing" data-manual="{quoted}">'
            f"<h2>{escape(manual.title)}</h2>"
            f'<ul data-role="manual-toc">{links}</ul></section>'
        )
    return _page(_LIBRARY_TITLE, "".join(sections))


def manual_page_html(manual_id: str) -> str | None:
    """One manual as a page, or `None` when no packaged manual carries the id — the caller
    answers an unknown id with a 404, never a guessed manual."""
    from aeh.help import load_manuals

    for manual in load_manuals():
        if manual.manual_id != manual_id:
            continue
        toc = "".join(
            f'<li><a href="#{escape(entry.anchor)}">{escape(entry.heading)}</a></li>'
            for entry in manual.toc
        )
        sections = "".join(
            f'<section data-role="manual-section" id="{escape(s.anchor)}">'
            f"<h2>{escape(s.heading)}</h2>"
            f'<div data-role="manual-text">{escape(s.text)}</div></section>'
            for s in manual.sections
        )
        title = _MANUAL_TITLE_TEMPLATE.format(title=manual.title)
        return _page(title, f'<nav data-role="manual-toc"><ul>{toc}</ul></nav>{sections}')
    return None


__all__ = ["MANUAL_ID_PARAM", "manual_page_html", "manuals_library_html"]
