"""`CT-REVIEW-09` — system output is *unreachable* from the blind flow, not merely hidden.

Test plan §6.11.15, `TC-REVIEW-C09`, block form. The second §4.7 **safety property** in this
module, and the one whose difference from a passing test is invisible in a screenshot.

The distinction the clause is built on: *hiding* is a property of a template and survives exactly
as long as nobody edits the template; *unreachability* is a property of the query and survives
anything the rendering layer does. §3.15 says which one it means twice — the Data flow paragraph
(*"it deliberately cannot join to `criterion_score`"*) and the Compatibility paragraph (*"the
required negative test is that a blind session's query plan **cannot** reach `criterion_score`,
which is asserted against the query, not the rendering"*).

**A note on the primary assertion.** §3.15's Interfaces block declares nothing that exposes a
query, so step 1 is written against an invented `BlindSession.readable_tables()`, declared in
`review_vocabulary`'s docstring. A source-level scan of `aeh/review/` was the alternative and it
is a **weaker claim** — it asserts that no code in the module names the table, which an
implementation reaching it through a store helper or a database view satisfies while violating
the clause. The static scan is kept below as an *additional* assertion. The gap is a finding on
the PR, not a silent substitution.
"""

from __future__ import annotations

import pytest

from tests.support import broken_review_fixtures as broken
from tests.support import review_vocabulary as vocab
from tests.support.impl import CONSOLE_MODULE, REVIEW_MODULE, require, require_attr

pytestmark = pytest.mark.contract


# --- step 1: unreachability, at the query level -----------------------------------------------


@pytest.mark.writtenahead
def test_tc_review_c09_the_blind_session_cannot_reach_criterion_score_at_the_query_level():
    """Step 1 — *"asserted at the query/session level, so the guarantee holds regardless of what
    any template does. Hiding in the UI is what this clause explicitly refuses, so a case that
    only checks the rendered page has tested the wrong thing."*

    Two assertions, and the second is not implied by the first. Set **equality** against
    `{submission, criterion}` says the session reads those two and nothing else; the explicit
    `criterion_score` absence says the one table the clause names is gone. Equality alone would
    pass a session that read `{submission, criterion}` under aliases, and the named absence alone
    would pass a session that reached `label` or `submission_grade` instead — both of which carry
    the system's band.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(30))

    session = service.blind_sample(run_id="run-1", n=vocab.BLIND_SAMPLE_RANGE[0])
    require_attr(session, "readable_tables", issue="#111")
    readable = frozenset(session.readable_tables())

    assert vocab.BLIND_FORBIDDEN_TABLE not in readable, (
        f"the blind session can reach {vocab.BLIND_FORBIDDEN_TABLE!r}. CT-REVIEW-09 requires "
        "unreachability, not hiding: a session that can join to the score row is one template "
        "change away from displaying it, and a blind label collected after a glance is an "
        "acceptance label mislabeled."
    )
    assert readable == vocab.BLIND_READABLE_TABLES, (
        f"the blind session reads {sorted(readable)}; §3.15's Data flow paragraph says "
        f"{sorted(vocab.BLIND_READABLE_TABLES)} only. Anything else on that list is a route to "
        "the system's band that this clause has not considered."
    )


@pytest.mark.writtenahead
def test_tc_review_c09_no_blind_session_object_caches_a_score_row():
    """The block form's **adversarial construction**, asserted on the object rather than the page.

    *"Prefetch the score row into the blind session 'to make submission instant', rendering
    nothing."* Nothing is displayed, the flow looks identical, and the guarantee has degraded
    from unreachable to hidden. This is the construction the clause is worded to defeat, and it
    passes any assertion made over rendered output — which is why the probe reads attributes.

    `blind_prefetch_attributes` is controlled in both directions in the vocabulary suite: it stays
    silent on a compliant session and fires on this construction.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(30))
    session = service.blind_sample(run_id="run-1", n=vocab.BLIND_SAMPLE_RANGE[0])
    require_attr(session, "readable_tables", issue="#111")

    cached = vocab.blind_prefetch_attributes(session)
    assert cached == [], (
        f"the blind session carries {cached}. Rendering nothing is not the guarantee "
        "CT-REVIEW-09 makes — a prefetched score row is the difference between *unreachable* "
        "and *hidden*, and the second one is one template change from visible."
    )


# --- step 2: five absences, swept individually -------------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("forbidden", vocab.BLIND_FORBIDDEN_FIELDS)
def test_tc_review_c09_no_system_output_is_available_before_submission(forbidden):
    """Step 2 — *"swept as five separate absences over the rendered flow and over the session's
    available data."*

    Parametrized rather than looped so a failure names which of the five leaked. `FR-REVIEW-11`
    lists them individually and the plausible defect is one of them surviving a refactor; a single
    combined assertion names none of them when it fails.

    Both surfaces are checked in one test because they are one requirement: the field must be
    absent from what the session *has*, not merely from what the flow *shows*. A session holding
    the value and a template omitting it satisfies the second and fails the first.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(30))
    session = service.blind_sample(run_id="run-1", n=vocab.BLIND_SAMPLE_RANGE[0])
    require_attr(session, "available_data", issue="#111")
    require_attr(service, "render_blind_flow", issue="#111")

    available = session.available_data()
    assert forbidden not in available, (
        f"the blind session's available data carries {forbidden!r} before submission "
        f"(FR-REVIEW-11). The teacher has not answered yet, so anything the system decided is "
        "an anchor on the answer they are about to give."
    )

    rendered = service.render_blind_flow(session.session_id)
    assert forbidden not in rendered, (
        f"the blind flow renders {forbidden!r} before submission (FR-REVIEW-11)."
    )


# --- step 3: the transport layer ---------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_review_c09_no_blind_flow_request_returns_system_output_even_unrendered():
    """Step 3 — *"A value present in a payload but hidden by CSS satisfies step 2's naive form and
    fails here."*

    **This assertion is `M-CONSOLE`'s, not `M-REVIEW`'s.** The transport layer is the console's
    HTTP surface (`FR-CONSOLE-*`, stories #124/#125); `M-REVIEW` has no requests. The clause is
    still `CT-REVIEW-09`'s and the block form lists the step, so the case is written here and
    keyed on the console story that delivers the surface — which is why this is a separate test
    rather than a third assertion inside step 2's sweep. Reported on the PR: a P0 safety-property
    step that lands outside the module its clause belongs to.

    The probe reads the payloads rather than the DOM for the stated reason: CSS is not a security
    boundary, and a field serialized into a response has already left the module.
    """
    blind_flow_requests = require(
        CONSOLE_MODULE, "blind_flow_requests", issue="#124"
    )

    payloads = blind_flow_requests(run_id="run-1", n=vocab.BLIND_SAMPLE_RANGE[0])
    assert payloads, (
        "the blind flow made no requests, so this test asserts nothing about transport"
    )

    leaked = {
        request.path: [f for f in vocab.BLIND_FORBIDDEN_FIELDS if f in request.body]
        for request in payloads
    }
    leaked = {path: fields for path, fields in leaked.items() if fields}
    assert leaked == {}, (
        f"blind-flow responses carry system output in their payloads: {leaked}. Hidden by the "
        "template is not absent — CT-REVIEW-09 step 3."
    )


# --- step 4: the two clauses are one guarantee -------------------------------------------------


@pytest.mark.writtenahead
def test_tc_review_c09_blind_labels_carry_saw_system_output_zero_legitimately():
    """Step 4 — joining `CT-REVIEW-08`, *"so the two clauses are verified as the single guarantee
    they jointly make."*

    The word doing the work is **legitimately**. `saw_system_output = 0` on a blind label is
    trivially true of any implementation that writes the constant; what makes it a validity claim
    rather than a stored zero is that the session it came from could not reach the output. So the
    test asserts both in one place: the labels carry 0, *and* the session that produced them was
    unreachable. Either alone is satisfiable by a module the other one condemns.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(30))

    session = service.blind_sample(run_id="run-1", n=vocab.BLIND_SAMPLE_RANGE[0])
    require_attr(session, "readable_tables", issue="#111")
    require_attr(service, "label", issue="#110")
    assert vocab.BLIND_FORBIDDEN_TABLE not in frozenset(session.readable_tables()), (
        "the session could reach the score row, so the zeros below are a stored constant rather "
        "than evidence of anything"
    )

    label_ids = service.submit_blind(
        session.session_id, bands={ref: "B2" for ref in session.items}
    )
    labels = [service.label(label_id) for label_id in label_ids]

    assert labels, "the blind submission produced no labels, so step 4 asserts nothing"
    wrong = [
        label.label_id
        for label in labels
        if getattr(label, vocab.ADMISSIBILITY_COLUMN, None) != 0
    ]
    assert wrong == [], (
        f"blind labels {wrong} carry {vocab.ADMISSIBILITY_COLUMN} != 0. CT-REVIEW-08 and "
        "CT-REVIEW-09 make one guarantee between them: the flow could not show the answer, and "
        "the label records that it did not."
    )
    assert all(label.label_type == "blind" for label in labels), (
        "a blind submission wrote a label of another type, so M-STATS's admissibility filter — "
        "which reads label_type as well as this column — would not see these"
    )
