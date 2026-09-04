"""`CT-CONSOLE-13` and `-14` — what the review queue says, in what order, and what the blind flow
cannot reach.

Test plan §6.11.19, TS-77 (issue #132). Both clauses are about **rendering**, and §6.11.19 says
why that is where the case belongs: *"a rendering assertion because that is where the dishonesty
would occur"*. The queue can compute its residual correctly and not print it; the blind flow can
hide system output on the page while still fetching it.

* `-13` — the header states all three counts, group actions rank above per-item ones, and
  narrative renders **before** the mark carrying no numeral-bearing or overall-quality claim.
  The ordering is not cosmetic: a narrative shown after the mark is read as justification for it
  rather than as the evidence the teacher is meant to weigh.
* `-14` — the blind-sample flow has no **reachable** path to system output before submission, and
  the clause insists on unreachability rather than non-display. So the assertion is against the
  flow's **queries**, not its rendering, plus the transport payload — because RISK-13 has no
  symptom (HLD `R21`): a biased blind label looks exactly like an unbiased one.

Both are written ahead of **#124** (interface invariants 8–14). Every name they call is invented;
the whole surface is settled once in `tests/support/console_vocabulary.py`, because design §3.19
declares no Python interface at all — only prose and a route table.
"""

from __future__ import annotations

import pytest

from tests.support.console_vocabulary import (
    dom_order,
    element_text,
    forbidden_narrative_claims,
    visible_text,
)
from tests.support.impl import CONSOLE_MODULE, require

pytestmark = pytest.mark.contract


# --- CT-CONSOLE-13 — the queue header, the order, and the narrative -------------------------------


@pytest.mark.writtenahead
def test_tc_console_c13_the_queue_header_states_flagged_shown_and_left_provisional():
    """`CT-CONSOLE-13` / `FR-CONSOLE-13` — **all three** counts, and the third is the honest one.

    This is the console-side discharge of `CT-REVIEW-04`. *Flagged* and *shown* are the
    comfortable numbers; **items left provisional** is the one a queue would quietly omit, because
    it is the count that says how much of the class nobody looked at. `R58` makes unreviewed items
    provisional rather than withheld, so the residual is real on every run and stating it is the
    whole point.

    Asserted on the **rendered header**, and on the numbers rather than on the labels: a header
    that prints the word "provisional" beside a hard-coded zero has said nothing.
    """
    render_queue = require(CONSOLE_MODULE, "render_review_queue", issue="#124")
    header = require(CONSOLE_MODULE, "review_queue_header", issue="#124")
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    rendered = render_queue(build_console(), run_id="r-1")
    counts = header(rendered)

    assert set(counts) == {"flagged", "shown", "left_provisional"}, (
        f"the review queue header states {sorted(counts)}; FR-CONSOLE-13 requires items flagged, "
        f"items shown and items left provisional — the third is the residual, and it is the one a "
        f"queue omits"
    )
    for name, value in counts.items():
        assert isinstance(value, int), f"{name} is not a count"

    text = visible_text(rendered.html)
    for value in counts.values():
        assert str(value) in text, (
            f"the header computed {counts} and rendered {text!r}: a count that is computed and not "
            f"printed is the dishonesty this case is a rendering assertion to catch"
        )

    assert counts["left_provisional"] == counts["flagged"] - counts["shown"], (
        f"the residual does not reconcile: {counts}. A 'left provisional' figure that is not "
        f"flagged minus shown is a number with no relationship to the class."
    )


@pytest.mark.writtenahead
def test_tc_console_c13_group_actions_render_above_per_item_actions():
    """`FR-CONSOLE-14` — *"whenever a group exists"*, which is the half that has to be constructed.

    A queue with no groups satisfies the ordering trivially, so the case builds a run whose queue
    **has** a group and asserts the order there. Asserted by DOM position rather than by substring:
    a wrapper carrying `data-role="item-actions"` around a group block would satisfy a `str.find`
    check while rendering the opposite.
    """
    # `render_review_queue` first, deliberately: this case is registered against #124, and
    # `require()` reports whichever blocker it reaches first. Resolving `build_console` (which is
    # #122's) ahead of it would print "blocked on #122" on a test that #122 landing does not
    # unmark — a failure message naming the wrong issue is how a gate stops being believed.
    render_queue = require(CONSOLE_MODULE, "render_review_queue", issue="#124")
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    rendered = render_queue(build_console(), run_id="r-with-groups")

    group, item = dom_order(rendered.html, "group-actions", "item-actions")
    assert group >= 0, (
        "the queue rendered no group actions at all, so this ordering assertion has nothing to "
        "assert — the fixture must contain a group (FR-CONSOLE-14 is conditional on one existing)"
    )
    assert item >= 0, "the queue rendered no per-item actions"
    assert group < item, (
        "per-item actions render above group actions. The order is the affordance: a teacher "
        "working a budget in minutes acts on the group they can see first."
    )


@pytest.mark.writtenahead
def test_tc_console_c13_narrative_renders_before_the_mark_and_claims_no_score():
    """`FR-CONSOLE-15` — two assertions that fail independently, so both are made.

    **Order.** Narrative before the mark. §6.11.19: *"a narrative shown after the mark is read as
    justification rather than as evidence"* — the teacher has already seen the verdict and is now
    reading the reasons for it, which is the opposite of the judgment the queue exists to support.

    **Content.** No numeral-bearing or overall-quality claim. Not "no numerals": an
    evidence-grounded narrative cites question numbers and line numbers, and a rule that condemned
    digits would fail every correct console. `forbidden_narrative_claims` scopes it to a numeral in
    scoring company, and its controls — including a correct narrative full of numbers — run green
    in `test_ct_console_vocabulary.py`.
    """
    render_queue = require(CONSOLE_MODULE, "render_review_queue", issue="#124")
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    rendered = render_queue(build_console(), run_id="r-1")

    narrative, mark = dom_order(rendered.html, "narrative", "mark")
    assert narrative >= 0 and mark >= 0, (
        "the review item renders no narrative or no mark, so the ordering clause has nothing to "
        "order"
    )
    assert narrative < mark, (
        "the mark renders before its narrative. FR-CONSOLE-15 puts the evidence first because the "
        "order is what decides whether the teacher weighs it or rationalises from it."
    )

    # Sliced to the narrative element, not the page: the mark is a numeral in scoring company by
    # definition, so a rule run over the whole rendering would condemn every correct review item.
    claims = forbidden_narrative_claims(element_text(rendered.html, "narrative"))
    assert not claims, (
        f"the narrative makes a score or overall-quality claim: {claims}. FR-CONSOLE-15 keeps the "
        f"mark out of the narrative so the narrative stays evidence."
    )


# --- CT-CONSOLE-14 — unreachable, not merely undisplayed --------------------------------------------


@pytest.mark.writtenahead
def test_tc_console_c14_the_blind_flow_issues_no_query_that_reaches_system_output():
    """`CT-CONSOLE-14` — asserted against the flow's **queries**, as the clause insists.

    *"No reachable path to system output before submission"* — and §6.11.19 spells out that this is
    *"unreachability rather than non-display, against the flow's queries rather than its
    rendering"*. The difference is the whole clause. A flow that fetches the panel's verdict and
    hides it with CSS has a reachable path: the next person to add a debug view, or a template that
    interpolates the wrong variable, exposes it — and nobody would notice, because RISK-13 has no
    symptom. A blind label biased by having seen the system's answer looks exactly like an unbiased
    one, and it is the only unbiased ground truth the system has (`R21`).

    So the sweep is over the tables and columns the flow reads, before submission.
    """
    flow_for = require(CONSOLE_MODULE, "blind_flow", issue="#124")

    flow = flow_for(run_id="r-1", submission_ref="s-0007")
    assert not flow.submitted, "the flow must be inspected before submission"

    forbidden = {
        "verdict",
        "band",
        "self_confidence",
        "aggregated_band",
        "submission_grade",
        "review_queue",
        "narrative",
        "criterion_score",
    }
    reached = {
        token
        for query in flow.queries
        for token in forbidden
        if token in str(query).lower()
    }
    assert not reached, (
        f"the blind flow queries {sorted(reached)} before submission. CT-CONSOLE-14 requires the "
        f"path to be unreachable, not merely undisplayed: data that is fetched is one template "
        f"change away from being shown, and a blind label that saw the system's answer is "
        f"indistinguishable from one that did not (R21, RISK-13)."
    )
    assert flow.queries, (
        "the flow issued no queries at all, so this sweep would pass against a flow that had not "
        "been built yet"
    )


@pytest.mark.writtenahead
def test_tc_console_c14_the_transport_carries_no_system_output_even_unrendered():
    """`CT-CONSOLE-14`'s second half — the payload, not the page.

    The query sweep above catches a flow that *asks* for system output. This catches the one that
    receives it anyway: a view model assembled once for several screens, a serializer that ships
    the whole row, a template context with more in it than the template uses. None of that is
    visible in the rendering and all of it is on the wire.

    §6.11.19 keeps both this case and `TC-REVIEW-C09` because *"the guarantee can be broken
    independently at either end"* — `M-REVIEW` can leak into the payload it hands the console, and
    the console can leak a payload `M-REVIEW` kept clean.
    """
    flow_for = require(CONSOLE_MODULE, "blind_flow", issue="#124")

    flow = flow_for(run_id="r-1", submission_ref="s-0007")
    payloads = " ".join(str(payload).lower() for payload in flow.transport_payloads)
    assert payloads, "the flow sent nothing to the browser, so this assertion is vacuous"

    for leak in ("verdict", "self_confidence", "aggregated_band", "predicted_band"):
        assert leak not in payloads, (
            f"the blind flow's transport payload carries {leak!r} before submission. It is not "
            f"rendered, which is exactly what makes it the version of this failure nobody sees."
        )
