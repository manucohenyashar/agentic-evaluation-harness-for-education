"""The console's rendered HTML, and the invariants no layout change may drop.

Case: `TC-REG-04` (test plan §6.9), `FR-CONSOLE-13`, `FR-CONSOLE-15`, golden file.

    baseline  Rendered HTML of the review queue, the rollup and the student view
    reviewer  The console owner
    grounds   Accepted for deliberate layout changes; **never** for a change that removes a
              §11.6 invariant's rendered element

The word "never" is what this file is built around. A golden-HTML baseline is a layout
baseline, and layout changes constantly: a class renamed, a wrapper added, a column moved. If
the only assertion were byte equality, the console owner would accept a diff a week, and the
one diff that removed the *items left provisional* count would be accepted along with the rest
— because it looks like every other diff.

So the invariant elements are asserted **separately and first**, out of the same rendering:

- `FR-CONSOLE-13` (§11.6 invariant 8) — the queue header states items flagged, items shown and
  items left provisional. The third is the residual: how much of the class nobody looked at.
- `FR-CONSOLE-15` (invariant 10) — narrative renders before the mark, in every item, and the
  narrative carries no numeral-bearing or overall-quality claim.

Those two assertions have no grounds for acceptance at all. The byte comparison that follows
does, and the failure message says which of the two a reader is looking at.

**Written ahead of implementation** (§8.2). The queue is #124's, the rollup #125's. Remove the
marker — never the test — when #125 closes, and record the baselines in that PR.
"""

from __future__ import annotations

import pytest

from tests.support.baselines import assert_matches_golden, entry_for
from tests.support.console_vocabulary import (
    dom_order,
    element_text,
    elements,
    forbidden_narrative_claims,
    visible_text,
)
from tests.support.impl import CONSOLE_MODULE, require

pytestmark = pytest.mark.writtenahead

CASE = "TC-REG-04"
RUN_ID = "r-1"

QUEUE_GOLDEN = "TC-REG-04/review-queue.html"
ROLLUP_GOLDEN = "TC-REG-04/rollup.html"
STUDENT_GOLDEN = "TC-REG-04/student-view.html"


def _assert_invariant_elements_survive(queue_html: str, counts: dict) -> None:
    """§11.6 invariants 8 and 10, checked against the rendering the baseline was taken from.

    Not a duplicate of `TC-CONSOLE-13`/`-15`: those cases assert the console renders these
    things at all. This asserts they are still in the artifact the baseline froze, which is the
    only place a *baseline update* could drop them.
    """
    assert set(counts) == {"flagged", "shown", "left_provisional"}, (
        f"the review queue header states {sorted(counts)}. FR-CONSOLE-13 requires items "
        f"flagged, items shown and items left provisional; the third is the residual, and it "
        f"is the one a layout change omits. §6.9: never acceptable as a baseline update."
    )
    text = visible_text(queue_html)
    for name, value in counts.items():
        assert str(value) in text, (
            f"the header computed {name}={value} and did not render it. A count that is "
            f"computed and not printed is the omission §11.6 invariant 8 exists to forbid, and "
            f"§6.9 puts it outside what the console owner may accept."
        )

    items = elements(queue_html, "review-item")
    assert items, "the review queue rendered no items, so invariant 10 has nothing to check"
    for index, item in enumerate(items):
        narrative, mark = dom_order(item, "narrative", "mark")
        assert 0 <= narrative < mark, (
            f"item {index}: FR-CONSOLE-15 renders narrative before mark. Found narrative at "
            f"{narrative} and mark at {mark}."
        )
        claims = forbidden_narrative_claims(element_text(item, "narrative"))
        assert not claims, (
            f"item {index}: the narrative carries {claims}. FR-CONSOLE-15 forbids a "
            f"numeral-bearing or overall-quality claim in narrative text."
        )


def test_tc_reg_04_the_three_rendered_surfaces_match_their_baselines(tmp_path):
    """TC-REG-04 — review queue, rollup and student view.

    Oracle: golden file, plus a separate invariant-element check that no diff can waive.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")
    render_queue = require(CONSOLE_MODULE, "render_review_queue", issue="#124")
    render_rollup = require(CONSOLE_MODULE, "render_rollup", issue="#125")
    queue_header = require(CONSOLE_MODULE, "review_queue_header", issue="#124")
    entry = entry_for(CASE)

    app = build_console()
    queue = render_queue(app, run_id=RUN_ID)
    rollup = render_rollup(app, run_id=RUN_ID)
    student = app.render("student-view", run_id=RUN_ID, submission_ref="SYN-001")

    # First: the things no layout change may drop.
    _assert_invariant_elements_survive(queue.html, dict(queue_header(queue)))

    # Then: the layout itself, which the console owner may accept on a deliberate change.
    for golden, page in (
        (QUEUE_GOLDEN, queue),
        (ROLLUP_GOLDEN, rollup),
        (STUDENT_GOLDEN, student),
    ):
        assert golden in entry.golden, f"{golden} is not a registered {CASE} baseline"
        assert_matches_golden(CASE, golden, page.html.encode("utf-8"))
