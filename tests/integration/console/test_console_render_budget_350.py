"""`TS-49` (issue #130) — the review queue and the rollup render inside their budgets for a
350-student run, over a real store.

Test plan §5.19 `TC-CONSOLE-33` (`NFR-CONSOLE-01`), Performance / rung 3, metric threshold per
§6.4 `PERF-08`: a 350-student run with about 800 flagged items; the queue renders in under 2 s,
the rollup in under 3 s, single request, timed by the test (`perf_counter`), never read off the
page.

**What this adds over `CT-CONSOLE-C19`.** The clause case times renders on `StoreSpy` at the
reference cohort size, where the console's reads return nothing and the screen renders its
standing shape. A render budget over pages with nothing on them measures the template. Here the
store holds the real run — 350 submissions scored through `M-DET`/`M-GRADE`, 350 grade rows, and
800 judged scores queued for review — and each timed page must actually carry that load: the
queue's header must state 800 flagged, the rollup must render all 350 grade lines. Only then is
the time a measurement of the budget the requirement names.

**Disclosed stand-in** (the `TC-GRADE-16` precedent): the 800 queued judged scores are
`criterion_score` rows routed `queued` — `M-AGG`'s write, the population `M-REVIEW` admits — over
three judged criteria (C-10 and C-11 for all 350, C-12 for the first 100).

**Written ahead of implementation.** The issue says `yes`; stale — `M-CONSOLE` landed (#122, #124).
"""

from __future__ import annotations

import re
import time

import pytest

from aeh.console import SCREENS, build_console, review_queue_header
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.support.console_vocabulary import (
    REFERENCE_COHORT_SIZE,
    REVIEW_QUEUE_BUDGET_SECONDS,
    ROLLUP_BUDGET_SECONDS,
)
from tests.support.console_world import rows, seed_scored_run

pytestmark = [pytest.mark.integration]

#: PERF-08's "about 800 flagged".
FLAGGED_ITEMS = 800


def test_tc_console_33_queue_and_rollup_render_within_budget_for_a_350_student_run(tmp_data_dir):
    """`TC-CONSOLE-33` — metric threshold, with the load proven present on each timed page."""
    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store, submissions=REFERENCE_COHORT_SIZE, with_open_criteria=True)
        catalog = PackageCatalog(store.package(world.package_id), package_id=world.package_id)
        catalog.add_criterion(world.package_version_id, "C-12", question_id="Q12", kind="open",
                              scoring_model="holistic")
        flagged = [(s, c) for c in ("C-10", "C-11") for s in world.submissions]
        flagged += [(s, "C-12") for s in world.submissions[: FLAGGED_ITEMS - len(flagged)]]
        assert len(flagged) == FLAGGED_ITEMS
        cohort = store.cohort(world.cohort_id)
        with cohort.transaction() as tx:
            for submission_id, criterion_id in flagged:
                tx.execute(
                    "INSERT OR REPLACE INTO criterion_score (run_id, submission_id, criterion_id, band, "
                    "points, judge_count, routing, state) VALUES (COALESCE((SELECT run_id FROM run ORDER BY COALESCE(started_at, '') DESC, run_id DESC LIMIT 1), 'run-fixture'), :s, :c, 'B2', 2.0, 3, 'queued', "
                    "'provisional_unreviewed')",
                    s=submission_id, c=criterion_id,
                )
        grades = rows(cohort, "SELECT COUNT(*) AS n FROM submission_grade WHERE run_id = :r",
                      r=world.run_id)[0]["n"]
        assert grades == REFERENCE_COHORT_SIZE, f"fixture: {grades} grade rows"

        problems: list[str] = []
        app = build_console(store=store)

        started = time.perf_counter()
        queue_page = app.render(SCREENS["S9"], id=world.run_id).html
        queue_seconds = time.perf_counter() - started
        header = review_queue_header(queue_page)
        if header.get("flagged") != FLAGGED_ITEMS:
            problems.append(
                f"the timed review queue states {header!r} for a run with {FLAGGED_ITEMS} judged "
                f"items queued (criterion_score rows routed 'queued' — M-REVIEW's admitted "
                f"population), so its {queue_seconds:.3f}s does not measure the load PERF-08 "
                f"names. The budget cannot be asserted until the queue carries it "
                f"(NFR-CONSOLE-01). [When written: the console reads review_queue by "
                f"run_id/rank_position — columns that table lacks — and renders zero; that table "
                f"also holds ~700 M-GRADE missing-input rows here, so fixing only the column "
                f"names would count those instead.]"
            )
        if queue_seconds >= REVIEW_QUEUE_BUDGET_SECONDS:
            problems.append(f"the review queue rendered in {queue_seconds:.3f}s, over the "
                            f"{REVIEW_QUEUE_BUDGET_SECONDS}s budget")

        started = time.perf_counter()
        rollup_page = app.render(SCREENS["S12"], id=world.run_id).html
        rollup_seconds = time.perf_counter() - started
        lines = len(re.findall(r'<div data-role="grade">', rollup_page))
        if lines != REFERENCE_COHORT_SIZE:
            problems.append(f"the timed rollup rendered {lines} grade lines for "
                            f"{REFERENCE_COHORT_SIZE} graded students")
        if rollup_seconds >= ROLLUP_BUDGET_SECONDS:
            problems.append(f"the rollup rendered in {rollup_seconds:.3f}s, over the "
                            f"{ROLLUP_BUDGET_SECONDS}s budget")
        assert not problems, "\n\n".join(problems)
    finally:
        store.close()
