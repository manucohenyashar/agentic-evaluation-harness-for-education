"""`TC-REVIEW-18` — the queue builds **and renders** within 2 seconds at the stated load.

Test plan §5.15, issue #112 (TS-40). Traces to `NFR-REVIEW-01`. Row form: *"A 350-student run
with about 800 flagged items. The queue builds and renders within 2 seconds."* Oracle: metric
threshold (`PERF-08`). P1.

`CT-REVIEW-C16` (`tests/contract/review/test_ct_review_budget_and_ranking.py`) holds the build
half of the threshold and the build-time-excluded-from-the-budget accounting. What nothing
shipped carries is the **render** half: the case's threshold is for the queue *and its
rendering* — the screen the teacher opens — and a build that fits two seconds is not the case
if the page takes another two to state itself. This file times the service path end to end
(`render_review_queue` over a `ReviewService` builds the queue itself and renders it, so one
clock covers both halves) at `vocab`'s pinned load, and asserts the page that comes back is the
real queue screen — the header figures read back off the data attributes the header plants,
every shown entry rendered, the budget section — rather than a fast stub. The build-trace
section alone cannot satisfy these: the trace restates the flagged total and even the
reservation arithmetic (`M-REVIEW` emits "N of M minutes reserved" as a trace event), so
figure-presence assertions pass on a body-stubbed page; the header read-back and the
per-entry rendering cannot.

The threshold is `vocab.QUEUE_BUILD_SECONDS` (2.0) for the whole path, the same constant the
build half reads: the plan states one figure for the pair of operations, and splitting it
between two suites would let each pass on half the budget.

**Isolation:** rung 0 — in-memory rows, no store, no model; `slow` because it constructs the
full stated load (§4.6 keeps load cases out of the fast tier).
"""

from __future__ import annotations

import time

import pytest

from tests.support import broken_review_fixtures as broken
from tests.support import review_vocabulary as vocab
from tests.support.impl import CONSOLE_MODULE, REVIEW_MODULE, require

pytestmark = pytest.mark.contract


@pytest.mark.slow
def test_tc_review_18_the_queue_builds_and_renders_within_two_seconds_at_the_stated_load():
    """One clock over build + render at the pinned load, and a real page at the end of it.

    The service path builds the queue inside the render, so the timing below is the case's own
    pair of operations. The page assertions are load-bearing, not decoration: a renderer that
    got fast by rendering an empty shell would pass any clock and still not be the queue
    screen, so the html must state the pinned figures, the reservation and the budget.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    render_review_queue = require(CONSOLE_MODULE, "render_review_queue", issue="#124")
    review_queue_header = require(CONSOLE_MODULE, "review_queue_header", issue="#125")
    service = build_review(
        scores=broken.flagged_population(vocab.PERF_FLAGGED_ITEMS, criteria=8)
    )

    started = time.perf_counter()
    rendering = render_review_queue(service, run_id="run-1", budget_minutes=30)
    elapsed = time.perf_counter() - started

    assert elapsed < vocab.QUEUE_BUILD_SECONDS, (
        f"the queue took {elapsed:.2f}s to build and render at {vocab.PERF_STUDENTS} students "
        f"and {vocab.PERF_FLAGGED_ITEMS} flagged items, against NFR-REVIEW-01's "
        f"{vocab.QUEUE_BUILD_SECONDS}s for the pair. TC-REVIEW-18: the queue is opened at the "
        "start of a fixed time budget, so every second the screen spends is a second not spent "
        "reviewing."
    )

    html = rendering.html
    # The page substance, read the way the console itself reads it: `review_queue_header`
    # parses the data attributes only the body's header section plants and raises when the
    # section is absent, so an empty-shell render fails here by name — the build-trace
    # section restates the same figures, but it is provenance, not the screen.
    header = review_queue_header(rendering)
    queue = _queue(service)
    assert header == {
        "flagged": queue.flagged_total,
        "shown": vocab.items_shown(queue),
        "left_provisional": queue.residual_provisional,
    }, (
        f"the rendered header states {header!r} against the queue's own triple "
        f"(flagged {queue.flagged_total}, shown {vocab.items_shown(queue)}, left "
        f"{queue.residual_provisional}) — a header that disagrees with the queue it renders "
        "is the defect FR-CONSOLE-13 exists to catch, and a stub that renders none fails "
        "here by name"
    )
    assert html.count('data-role="review-item"') == len(queue.shown), (
        f"the page rendered {html.count('data-role=\"review-item\"')} review items against "
        f"the queue's {len(queue.shown)} shown entries — the entries the teacher acts on are "
        "the screen this case times, not only the header above them"
    )
    assert "Review budget: 30 minutes" in html, (
        "the rendered page carries no budget line — the minute budget (FR-REVIEW-01) is "
        "stated on the screen itself, not only in the trace beside it"
    )
    assert vocab.unstated_residual(html, queue) == [], (
        "the rendered page does not state the residual triple the queue stated"
    )
    assert f"{vocab.CONFIG_DEFAULTS['REVIEW_BLIND_RESERVE_MINUTES']} of 30 minutes reserved" in html, (
        "the rendered page does not state the reservation — the header's subtraction claim is "
        "part of the screen this case times"
    )
    assert vocab.budget_guarantee_language(html) == [], (
        "the rendered page promises the budget as elapsed time. The estimate is uncalibrated at "
        "Phase 1, so the screen renders a plan — a fast page that promises is worse than a slow "
        "one that does not."
    )
    assert "build-trace" in html, (
        "the rendered page carries no build-trace section, so the figures the teacher sees have "
        "no provenance"
    )


def _queue(source):
    """The service-built queue the rendering above derives from, for figure checks."""
    return source.build_queue(run_id="run-1", budget_minutes=30)