"""The review queue's markup: the header figures, the budget line and each item."""

from __future__ import annotations

from html import escape
from typing import Any

from .html import _band_control, _band_section, _row_get, _section
from .provenance import _PROVENANCE_FOOTER


# --- the review queue (invariants 8-10) and the blind flow (invariant 11) ------------------------------
#
# §3.19's remaining invented surface, settled with the tests that read it: `render_review_queue`
# is polymorphic over the two things a queue screen renders — this module's `ConsoleApp` (its own
# `review_queue` view) and `M-REVIEW`'s `ReviewService` (whose built `ReviewQueue` this module
# renders, `CT-REVIEW-04`'s consumer obligation). The markup markers are the anchors the contract
# tests read: `queue-header`, `group-actions`, `review-item`, `narrative`, `mark`, `item-actions`.


def _items_covered(entries: Any) -> int:
    """How many review items a list of entries covers: a group counts as all its members, a plain
    entry counts as one. This matches how M-REVIEW computes `residual_provisional` (CT-REVIEW-04).
    A queue showing 200 items as 16 groups has 16 entries but covers 200 items; mixing the two in
    the header would make the figures disagree."""
    total = 0
    for entry in entries or ():
        members = getattr(entry, "members", None)
        total += len(members) if members is not None else 1
    return total


def _review_queue_header_html(*, flagged: int, shown: int, left: int) -> str:
    """The queue header: the three figures as data attributes (read back by `review_queue_header`)
    and as visible text (FR-CONSOLE-13). All three count items, so flagged minus shown always
    equals what is left provisional."""
    figures = (
        f"Flagged for review: {int(flagged)}. Shown: {int(shown)} items. "
        f"Left provisional: {int(left)}."
    )
    return (
        '<section data-role="queue-header" '
        f'data-flagged="{int(flagged)}" data-shown="{int(shown)}" '
        f'data-left-provisional="{int(left)}">'
        f"<p>{escape(figures)}</p>"
        "<p>The third figure is the residual: the part of the class nobody has looked at "
        "yet, and the number a review sitting exists to shrink.</p>"
        "</section>"
    )
    """The queue header: the three figures as data attributes (what `review_queue_header`
    reads back) and as visible text (what a reader sees — `FR-CONSOLE-13` states the residual,
    and a figure computed but not printed has rendered nothing)."""
    figures = (
        f"Flagged for review: {int(flagged)}. Shown: {int(shown)}. "
        f"Left provisional: {int(left)}."
    )
    return (
        '<section data-role="queue-header" '
        f'data-flagged="{int(flagged)}" data-shown="{int(shown)}" '
        f'data-left-provisional="{int(left)}">'
        f"<p>{escape(figures)}</p>"
        "<p>The third figure is the residual: the part of the class nobody has looked at "
        "yet, and the number a review sitting exists to shrink.</p>"
        "</section>"
    )


def _review_queue_budget_html(budget_minutes: int | None) -> str:
    """The budget line, shown only when a budget was given. The wording calls it an estimate and
    promises nothing about actual time (CT-REVIEW-19)."""
    if budget_minutes is None:
        return ""
    return _section(
        "budget",
        f"Review budget: {int(budget_minutes)} minutes, estimated from the queue's "
        "per-item estimates.",
        "The blind sample's reservation is already subtracted from the ranked order; the "
        "estimate is a plan for the sitting, not a promise of elapsed time.",
    )


def _review_item_html(*, label: str, narrative: str, mark: str) -> str:
    """One review item, with the explanation before the mark (§11.6 invariant 10). An explanation
    shown after the mark reads as a justification for it rather than evidence to weigh. The item
    also has an editable band dropdown (invariant 16, FR-CONSOLE-20, #125): any view that shows a
    band must let the teacher change it (FR-REVIEW-15)."""
    return (
        '<div data-role="review-item">'
        f"<p>{escape(label)}</p>"
        f'<div data-role="narrative"><p>{escape(narrative)}</p></div>'
        '<div data-role="evidence"><p>The evidence spans recorded for this item render '
        "beside its wording, each carrying the question and line it cites.</p></div>"
        f'<div data-role="mark"><p>{escape(mark)}</p></div>'
        '<div data-role="item-actions"><p>Item actions: accept the proposed band, choose '
        "another, or skip this item.</p></div>"
        f"{_band_control('band_review_item')}"
        "</div>"
    )


def _review_queue_entries(entries: Any) -> str:
    """The queue's entries, whatever shape the source used: `QueueContents.shown` holds mapping
    rows, M-REVIEW's `ReviewQueue.shown` holds `ReviewItem`s and `ReviewGroup`s. One renderer
    handles both, because the rules are about the rendered order, not about who built the entries.
    """
    if not entries:
        return (
            "<p>This run has no flagged work queued yet; the item below shows the shape "
            "every ranked item takes.</p>"
            + _review_item_html(
                label="One flagged band per item, ranked.",
                narrative=(
                    "The evidence for the flagged criterion renders here, before the band "
                    "choice below it."
                ),
                mark="Band: not set yet — choose one when this run has flagged work.",
            )
        )
    blocks: list[str] = []
    for entry in entries:
        members = getattr(entry, "members", None)
        if members is not None:
            blocks.append(
                _review_item_html(
                    label=(
                        f"Group on {getattr(entry, 'criterion_id', '?')}: "
                        f"{len(members)} items sharing one proposed band, grouped by "
                        "identical band and integrity signature."
                    ),
                    narrative=(
                        "Every member of this group shows the same proposed band and the "
                        "same integrity signature; the caption is the exact Phase 1 "
                        "grouping, and nothing is claimed about the writing itself."
                    ),
                    mark=(
                        f"Proposed band: {getattr(entry, 'proposed_band', '') or 'none'} — "
                        "one decision covers every member."
                    ),
                )
            )
            continue
        state = getattr(entry, "state", None) or _row_get(entry, "state", "") or ""
        submission = (
            getattr(entry, "submission_id", None)
            if getattr(entry, "submission_id", None) is not None
            else _row_get(entry, "submission_id", "")
        )
        criterion = (
            getattr(entry, "criterion_id", None)
            if getattr(entry, "criterion_id", None) is not None
            else _row_get(entry, "criterion_id", "")
        )
        narrative = getattr(entry, "narrative", None) or (
            "No narrative is stored for this item yet; the evidence spans stand alone "
            "for your judgment."
        )
        proposed = getattr(entry, "proposed_band", None)
        mark = (
            f"Proposed band: {proposed}"
            if proposed
            else "Proposed band: none — choose one."
        )
        if str(state) == "ungradeable_by_panel":
            label = (
                f"{submission} / {criterion}: the panel refused to grade this criterion. "
                "It is shown for the record, not awaiting review."
            )
        else:
            reason = _row_get(entry, "reason", "")
            label = f"{submission} / {criterion}" + (
                f" — {reason}" if str(reason or "") else ""
            )
        blocks.append(_review_item_html(label=label, narrative=str(narrative), mark=mark))
    return "".join(blocks)


def _review_queue_body(
    *,
    flagged: int,
    shown: int,
    left: int,
    budget_minutes: int | None,
    entries: str,
    provenance: str = _PROVENANCE_FOOTER,
) -> str:
    """The review screen's body, used by both the route and the module-level renderer: the header
    first (invariant 8), then the budget line, then group actions above the items (invariant 9),
    each item with its explanation first (invariant 10). A provenance footer ends it, because the
    queue shows grades and must show what produced them (CT-CONSOLE-10, #125)."""
    return (
        _review_queue_header_html(flagged=flagged, shown=shown, left=left)
        + _review_queue_budget_html(budget_minutes)
        + '<div data-role="group-actions"><p>Group actions: accept a group\'s proposed '
        "band for every member at once, or open the group to act per item.</p></div>"
        + '<section data-role="queue-items">' + entries + "</section>"
        + _section("provenance", provenance)
        + _band_section("this run")
    )
