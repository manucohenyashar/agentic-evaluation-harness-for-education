"""Validity T18 (issue #903): TC-REG-28 (r2, SV-23) — the Review screen has a budget input and
posts at least one `review action` or `review group action`. Browser tier (E6), 1280x720.

SV-23 was a Review screen that read the queue and never acted on it. Pinned here: on the SPA's
`/review` route the teacher types a budget into the text field (no numeric input, CT-UI-12) and
presses **Go**, which re-reads the queue for that budget; **Apply to all n** then posts one
`review group action`, and that post writes one label per member.

**World.** `tests/support/eng7_browser.py` (ENG7 graded by the console's own start run), shaped
by `console_r2_world.shape_queue` so the queue holds one group. The draw is not opened, so the
group is whole.
"""

from __future__ import annotations

import re

import pytest

from tests.support import spa
from tests.support.console_r2_world import shape_queue
from tests.support.eng7_browser import VIEWPORT, assert_clean, eng7_browser

pytestmark = [pytest.mark.browser, pytest.mark.integration]


def test_tc_reg_28_the_review_screen_takes_a_budget_and_posts_a_review_action(
        tmp_path, monkeypatch):
    """TC-REG-28 (see the module docstring)."""
    with eng7_browser(tmp_path, monkeypatch) as world, \
            spa.spa_page(world.origin, viewport=VIEWPORT) as (page, log):
        served = world.served
        shape_queue(served)
        status, queue = served.get("/api/v1/review-queue", run_id=served.run_id)
        assert status == 200, queue
        (group,) = [e for e in queue["entries"] if e["kind"] == "group"]

        world.open(page, "/review")
        budget = page.locator("form.review-budget input[name='budget-minutes']")
        budget.wait_for()
        assert budget.get_attribute("type") == "text", budget.get_attribute("type")
        budget.fill("45")
        page.locator("form.review-budget button[type='submit']", has_text="Go").click()
        page.wait_for_function(
            "() => performance.getEntriesByType('resource').some("
            "(e) => e.name.includes('/api/v1/review-queue') && e.name.includes('budget_minutes=45'))")

        apply = page.get_by_role("button", name=re.compile(rf"^Apply to all {group['size']}$"))
        apply.first.click()
        page.wait_for_function(
            "() => performance.getEntriesByType('resource').some("
            "(e) => e.name.includes('/api/v1/actions/review-group-action'))")
        page.wait_for_timeout(300)

        posted = [u for u in log.requests
                  if re.search(r"/api/v1/actions/review-(group-)?action\b", u)]
        assert posted, f"the Review screen posted no review action: {log.api_requests()}"
        labels = served.rows("SELECT * FROM label WHERE run_id = ?", served.run_id,
                             tier="durable")
        assert len(labels) == group["size"], (
            f"the post wrote {len(labels)} labels, not one per member ({group['size']})")
        assert_clean(page, log)
