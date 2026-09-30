"""The review queue rendered at module level, over a console or a review service."""

from __future__ import annotations

import re
from typing import Any

from .html import _page, _section
from .provenance import _PROVENANCE_FOOTER
from .records import RenderedPage
from .review_rendering import _items_covered, _review_queue_body, _review_queue_entries
from .run_planning import build_console


def render_review_queue(
    source: Any, *, run_id: str, budget_minutes: int | None = None
) -> RenderedPage:
    """Render the review queue from either source: a `ConsoleApp` (the route's own view) or
    M-REVIEW's `ReviewService` (rendering the queue it built; the console side of CT-REVIEW-04).

    The service path renders the queue's **own** figures — `flagged_total`, the items its
    shown entries cover (the count `residual_provisional` was derived from), and
    `residual_provisional` as the queue stated it — rather than recomputing any of them:
    a rendering that recomputes a figure can disagree with the queue it renders, and the
    teacher would have no way to tell which is wrong. The app path computes the residual
    from its own counts, which is what its queue view states. `len(queue.shown)` is the
    figure the build trace states — "N entries shown" — and the trace section carries it
    where the two counts differ; the header states items, because that is the unit the
    residual is computed in."""
    if hasattr(source, "build_queue"):
        if budget_minutes is None:
            raise ValueError(
                "render_review_queue needs budget_minutes to render a service-built "
                "queue: the queue is minute-budgeted (FR-REVIEW-01), and a rendering "
                "without a budget would show only what fits without saying what fit it"
            )
        queue = source.build_queue(run_id=run_id, budget_minutes=budget_minutes)
        return RenderedPage(
            html=_page(
                "Review queue",
                _review_queue_body(
                    flagged=queue.flagged_total,
                    shown=_items_covered(queue.shown),
                    left=queue.residual_provisional,
                    budget_minutes=queue.budget_minutes,
                    entries=_review_queue_entries(queue.shown),
                    provenance=_service_provenance(source, run_id),
                )
                + _section(
                    "build-trace",
                    *(f"{event.name}: {event.detail}" for event in queue.build_trace),
                ),
            ),
            queries=tuple(
                f"{event.name}: {event.detail}" for event in queue.build_trace
            ),
        )
    view = source.review_queue(run_id, budget_minutes=budget_minutes)
    contents = view.queue
    return RenderedPage(
        html=_page(
            "Review queue",
            _review_queue_body(
                flagged=contents.flagged_total,
                shown=len(contents.shown),
                left=contents.flagged_total - len(contents.shown),
                budget_minutes=contents.budget_minutes,
                entries=_review_queue_entries(contents.shown),
                provenance=source._provenance_line(run_id=run_id),
            ),
        ),
        queries=view.queries,
    )


def _service_provenance(service: Any, run_id: str) -> str:
    """The provenance line for a queue a `ReviewService` built (FR-CONSOLE-40): from the run that
    produced it when the service has a real store, otherwise the storeless double's fixed value."""
    store = getattr(service, "_store", None)
    if store is None or getattr(store, "data_dir", None) is None:
        return _PROVENANCE_FOOTER
    return build_console(store=store)._provenance_line(run_id=run_id)


def review_queue_header(page: Any) -> dict[str, int]:
    """The three queue-header figures (§11.6 invariant 8), read back from the rendered page.

    Reads the data attributes the renderer plants (`data-flagged`, `data-shown`,
    `data-left-provisional`) rather than parsing the prose: a header whose figures moved
    into a chart or a badge stays legible to this reader, and one that lost a figure
    fails here by name. Raises rather than returning a short dict — a header missing a
    figure is the defect `FR-CONSOLE-13` exists to catch, and a partial dict would turn
    that failure into a downstream KeyError far from the cause."""
    html = getattr(page, "html", page)
    if 'data-role="queue-header"' not in html:
        raise ValueError(
            "the rendered review queue carries no queue-header element: FR-CONSOLE-13 "
            "requires the header to state all three figures, and this rendering has no "
            "header to read"
        )
    counts: dict[str, int] = {}
    for attr, name in (
        ("flagged", "flagged"),
        ("shown", "shown"),
        ("left-provisional", "left_provisional"),
    ):
        found = re.search(rf'data-{attr}="(-?\d+)"', html)
        if found is None:
            raise ValueError(
                f"the rendered queue header states no {attr!r} figure: FR-CONSOLE-13 "
                "requires items flagged, items shown and items left provisional — the "
                "third is the residual, and it is the one a header omits"
            )
        counts[name] = int(found.group(1))
    return counts
