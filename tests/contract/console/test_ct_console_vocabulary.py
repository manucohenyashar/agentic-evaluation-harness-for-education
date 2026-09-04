"""The green half of TS-77: does the fixture still match the design, and do the rules still fire?

**None of this is coverage of a `CT-CONSOLE` clause.** All twelve cases are behaviourally red
behind `writtenahead`, waiting on five stories (#122, #124, #125, #126, #127). What runs here is
the scaffolding they stand on:

* the **transcription** — HLD §7.9's twelve-row touchpoint inventory, §11.8's fifteen control
  actions, §11.9's six pilot questions, the three knobs, the two render budgets, the four
  observability metrics — each checked against the document it was copied from;
* the **rules** — the narrative claim detector, the DOM-order reader, the audit-surface sweep and
  the visible-degradation predicate — each checked against copy a correct console would render
  *and* copy the clause forbids.

The second half is where the work is. Every rule in this suite is a claim detector, and a claim
detector fails in two directions: TS-74 shipped one that rejected the disclaimer its own clause
required, and TS-57 shipped one whose control asserted only that something was flagged while four
of six rules were dead. So each rule is asserted on a hard correct case as well as on the
violation — a narrative full of numerals must pass, an audit page that renders `finalized_by` and
says what it is not must pass.
"""

from __future__ import annotations

import re

import pytest

from tests.support import broken_console_fixtures as fixtures
from tests.support.console_vocabulary import (
    BLOCKING_TOUCHPOINTS,
    CONSOLE_KNOBS,
    CONTROL_SURFACE_ACTIONS,
    MVP_ABSENT_TOUCHPOINT,
    OBSERVABILITY_METRICS,
    OPERATOR_ROUTES,
    OPTIONAL_SETUP_STEPS,
    PILOT_QUESTIONS,
    REFERENCE_COHORT_SIZE,
    REVIEW_QUEUE_BUDGET_SECONDS,
    ROLLUP_BUDGET_SECONDS,
    ROUTABLE_BIND,
    TEACHER_ROUTES,
    TEACHER_TOUCHPOINTS,
    UPLOAD_PROBE_BYTES,
    UPLOAD_RSS_RATIO_CEILING,
    authenticated_identity_claims,
    dom_order,
    element_text,
    forbidden_narrative_claims,
    visible_text,
    visibly_degraded,
)
from tests.support.doc_tables import markdown_rows, read_repo_text

pytestmark = pytest.mark.contract

DESIGN = "docs/design/detailed-design.md"
HLD = "docs/agentic-evaluation-harness-for-education.md"


def _normalized(repo_root, relative: str) -> str:
    """A document with its line wrapping removed, lower-cased.

    Every transcription check below is a substring match against prose, and the design documents
    wrap mid-sentence — TS-75 lost two green tests to exactly that before normalizing.
    """
    return " ".join(read_repo_text(repo_root, relative).lower().split())


# --- the transcription ------------------------------------------------------------------------------


def test_the_touchpoint_inventory_transcribes_hld_7_9_in_full(repo_root):
    """`CT-CONSOLE-17`'s sweep is *"enumerated against §7.9 rather than sampled"* — so is this.

    Twelve rows, each asserted still present in the HLD's own table. A sampled fixture would pass
    while the touchpoint nobody sampled had been silently dropped from the design, which is the
    same failure the clause names one level up.

    The **blocking** column is asserted too, and it is the load-bearing one: `R60`'s standing test
    is *"could a teacher start a run, do nothing at all, and still have every student graded the
    next morning?"*, and it becomes false the moment a third row blocks.
    """
    hld = _normalized(repo_root, HLD)

    missing = [name for name in TEACHER_TOUCHPOINTS if name.lower() not in hld]
    assert not missing, (
        f"these touchpoints are no longer in HLD §7.9's inventory: {missing}. The fixture was "
        f"transcribed from that table and the table has moved."
    )
    assert len(TEACHER_TOUCHPOINTS) == 12, (
        "HLD §7.9's inventory has twelve rows; a fixture of a different size makes CT-CONSOLE-17's "
        "sweep assert something other than 'every touchpoint'"
    )

    blocking = {name for name, blocks in TEACHER_TOUCHPOINTS.items() if blocks}
    assert blocking == BLOCKING_TOUCHPOINTS, (
        f"the inventory says {sorted(blocking)} block; the fixture's declared set is "
        f"{sorted(BLOCKING_TOUCHPOINTS)}"
    )
    assert len(BLOCKING_TOUCHPOINTS) == 2, (
        "R60 and CT-CONSOLE-07 both turn on there being exactly two blocking setup items"
    )


def test_exactly_one_touchpoint_is_absent_from_the_mvp(repo_root):
    """The row that makes `CT-CONSOLE-17` a test rather than a tautology.

    *"Either implemented or rendered present-and-unavailable"* is satisfied by the first branch
    alone if every touchpoint is implemented — the clause would assert nothing and the case would
    be green against a console with no placeholder mechanism at all. HLD §11.9 says the MVP
    executes *"§7.9's inventory minus one touchpoint"*, so exactly one row must take the second
    branch, and `CT-CONSOLE-17` asserts that it does with a version named.
    """
    hld = _normalized(repo_root, HLD)

    assert MVP_ABSENT_TOUCHPOINT in TEACHER_TOUCHPOINTS, (
        "the touchpoint the MVP omits must be one of the inventory's own rows"
    )
    assert not TEACHER_TOUCHPOINTS[MVP_ABSENT_TOUCHPOINT], (
        "the omitted touchpoint blocks grades, which would mean the MVP cannot deliver a grade at "
        "all — R60's test would already be failing"
    )
    assert "inventory minus one touchpoint" in hld, (
        "HLD §11.9 no longer says the console executes the inventory minus one touchpoint. If the "
        "MVP now implements all twelve, CT-CONSOLE-17's second branch is untested by this suite."
    )


def test_the_control_surface_transcribes_hld_11_8(repo_root):
    """`FR-CONSOLE-32` — the write surface is *exactly* §11.8's table, and it is enumerable.

    `CT-CONSOLE-21`'s durable half rests on this list being closed: the console is *"replaceable
    without touching the harness"* only because its whole coupling is these writes plus its reads.
    An action added to the design and not here would leave that seam asserted against a stale set.
    """
    hld = _normalized(repo_root, HLD)
    assert "the console's entire write surface to the pipeline is small enough to enumerate" in hld

    design = _normalized(repo_root, DESIGN)
    for action in ("start run", "finalize batch", "amend a finalized grade", "purge cohort"):
        assert action in design, f"design §3.19 no longer lists {action!r} on the control surface"

    assert len(CONTROL_SURFACE_ACTIONS) == 15
    assert len(set(CONTROL_SURFACE_ACTIONS)) == 15, "the enumeration has a duplicate"


def test_the_knob_defaults_transcribe_the_design_configuration_line(repo_root):
    """`CT-CONSOLE-20`'s three knobs, with the one that has no declared default left `None`.

    `CONSOLE_PORT` is named and undefaulted in design §3.19. Inventing 8080 here would make it the
    requirement the first time somebody hit it — the reasoning `conf_builders` already documents
    for `retention_setting`.
    """
    design = _normalized(repo_root, DESIGN)
    assert "`console_bind` (127.0.0.1), `console_port`, `console_poll_interval_ms` (3000)" in design

    assert CONSOLE_KNOBS == {
        "CONSOLE_BIND": "127.0.0.1",
        "CONSOLE_PORT": None,
        "CONSOLE_POLL_INTERVAL_MS": 3000,
    }
    assert CONSOLE_KNOBS["CONSOLE_BIND"] != ROUTABLE_BIND, (
        "the adversarial bind value must differ from the default, or CT-CONSOLE-20's refusal case "
        "sets nothing and passes against a console that ignores the knob entirely"
    )


def test_the_render_budgets_transcribe_nfr_console_01(repo_root):
    """Two seconds and three, at 350 students — and the two are different numbers.

    `CT-CONSOLE-19` gives the reason and `TC-CONSOLE-C19` preserves it: both screens are opened
    *"inside a fixed time budget"*, so render time comes straight out of the teacher's review
    minutes. A fixture that collapsed the two into one bound would stop asserting the rollup's.
    """
    design = _normalized(repo_root, DESIGN)
    assert "review queue shall render within 2 seconds and the rollup within 3 seconds" in design
    assert "350-student run" in design

    assert (REVIEW_QUEUE_BUDGET_SECONDS, ROLLUP_BUDGET_SECONDS) == (2.0, 3.0)
    assert REVIEW_QUEUE_BUDGET_SECONDS < ROLLUP_BUDGET_SECONDS
    assert REFERENCE_COHORT_SIZE == 350


def test_the_observability_metrics_transcribe_the_design_and_the_six_pilot_questions(repo_root):
    """`CT-CONSOLE-22` — four metrics, and the one that is contract rather than telemetry.

    The clause singles the skip rates out: they are *"the pilot's actual instrument for HLD §11.9's
    six questions"*. So the six are transcribed alongside, and the optional setup steps the rate
    must be broken down by — because §6.11.19 is explicit that an aggregate skip rate cannot answer
    any of the six.
    """
    design = _normalized(repo_root, DESIGN)
    assert "skip rates per optional setup step" in design
    assert "review budget requested versus used" in design

    assert len(OBSERVABILITY_METRICS) == 4

    hld = _normalized(repo_root, HLD)
    missing = [phrase for phrase in PILOT_QUESTIONS if phrase.lower() not in hld]
    assert not missing, f"HLD §11.9 no longer poses these questions: {missing}"
    assert len(PILOT_QUESTIONS) == 6, (
        "the clause says six. HLD §11.9 lists six and then calls them 'those five answers', which "
        "is why this count is asserted rather than counted from the document."
    )

    # Every optional setup step must be a non-blocking row of the inventory. A step in this list
    # that blocks cannot be skipped, so a skip rate for it would always be zero and would answer
    # none of the six questions.
    for step in OPTIONAL_SETUP_STEPS:
        assert step in TEACHER_TOUCHPOINTS, f"{step!r} is not a §7.9 touchpoint"
        assert not TEACHER_TOUCHPOINTS[step], f"{step!r} blocks, so it cannot be skipped"


def test_the_route_table_transcribes_the_design(repo_root):
    """Design §3.19 splits routes by surface, and `CT-CONSOLE-16` needs that to mean something.

    The clause requires the provenance gate to be *"a reachable screen rather than an internal
    check"*, which is an assertion about the route table. Transcribed here so the reachability
    check has a fixed set to be reachable within.
    """
    rows = markdown_rows(read_repo_text(repo_root, DESIGN))

    # **Set equality per surface, not containment.** Mutation testing caught this: asserting only
    # that each fixture route is still in the design leaves the check green when a route is deleted
    # from the *fixture*, which is the direction that silently narrows `CT-CONSOLE-16`'s
    # reachability sweep and `CT-CONSOLE-23`'s route scan.
    for surface, expected in (("Teacher", TEACHER_ROUTES), ("Operator", OPERATOR_ROUTES)):
        matching = [row for row in rows if row and row[0] == surface]
        assert len(matching) == 1, (
            f"expected exactly one route-table row whose first cell is {surface!r}; found "
            f"{len(matching)}. The fixture is keyed to that row."
        )
        declared = set(re.findall(r"`(/[^`]*)`", " ".join(matching[0])))
        assert declared == set(expected), (
            f"design §3.19 declares {sorted(declared)} for the {surface} surface; the fixture "
            f"carries {sorted(expected)}"
        )

    assert not set(TEACHER_ROUTES) & set(OPERATOR_ROUTES), (
        "a route on both surfaces would defeat FR-CONSOLE-11's separation, which CT-CONSOLE-11 "
        "(TS-76) asserts — the two suites must at least agree the surfaces are disjoint"
    )


def test_the_upload_probe_is_knob_gated_and_asserted_as_a_ratio():
    """`CT-CONSOLE-18`'s size is environment-sensitive, so it is a knob (`CLAUDE.md`, seam 3).

    The clause says hundreds of megabytes are *"a normal upload, not an edge case"*, and the
    default reflects that. But a hard-coded 300 MB is a constant calibrated for one machine, and it
    becomes a phantom failure on a smaller test box — so it is overridable, and the assertion is a
    **ratio** of peak memory to upload size rather than an absolute number of bytes. An
    implementation that streams uses memory proportional to its buffer; one that buffers the batch
    is at or above 1.0 by construction, on any machine and at any probe size.
    """
    assert UPLOAD_PROBE_BYTES >= 1024, "the probe must be large enough for the ratio to mean anything"
    assert 0 < UPLOAD_RSS_RATIO_CEILING < 1.0, (
        "a ceiling at or above 1.0 is satisfied by an implementation that buffers the entire "
        "upload in memory, which is the one CT-CONSOLE-18 forbids"
    )


# --- the rules, against copy a correct console renders ------------------------------------------------


def test_the_narrative_rule_passes_evidence_and_catches_a_score_claim():
    """`FR-CONSOLE-15` forbids a *numeral-bearing score claim*, not a numeral.

    An evidence-grounded narrative is full of digits — question numbers, line numbers, quantities
    out of the student's own working. That is what the design asks for. A rule that condemned every
    digit would fail every correct narrative and would be switched off by whoever hit it first,
    which is exactly the bug TS-74 shipped twice and had to fix in review.

    So both directions are asserted, and the correct fixture is deliberately the hard one.
    """
    assert forbidden_narrative_claims(fixtures.CORRECT_NARRATIVE) == [], (
        "the rule condemns a correct evidence-grounded narrative, so TC-CONSOLE-C13 would go red "
        "against a compliant console"
    )

    scored = forbidden_narrative_claims(fixtures.NARRATIVE_WITH_A_SCORE_CLAIM)
    assert len(scored) == 1 and "7 out of 10" in scored[0]

    overall = forbidden_narrative_claims(fixtures.NARRATIVE_WITH_AN_OVERALL_CLAIM)
    assert len(overall) == 1 and "excellent" in overall[0].lower()

    # The near-miss that decides whether the rule reads context or counts digits: a criterion index
    # beside the word `band`. `band` is scoring vocabulary, so this is caught — and it should be,
    # since naming the band in the narrative is stating the mark before the mark.
    assert forbidden_narrative_claims(fixtures.NARRATIVE_NAMING_A_BAND)


def test_the_dom_order_reader_is_not_fooled_by_an_attribute():
    """`CT-CONSOLE-13` asserts narrative renders **before** the mark — by element, not by substring.

    The ordering is the assertion, because it is what shapes judgment: a narrative shown after the
    mark is read as justification for it rather than as the evidence it is meant to be.

    `str.find` cannot make that assertion. The correct fixture carries `data-contains="mark
    narrative"` on the wrapper *enclosing* the narrative — realistic markup, and enough to put the
    string "mark" ahead of the narrative in the raw HTML while the rendered order is correct.
    """
    narrative, mark = dom_order(fixtures.CORRECT_REVIEW_ITEM_HTML, "narrative", "mark")
    assert narrative >= 0 and mark >= 0, "both markers must be found, or the order proves nothing"
    assert narrative < mark, "the reader was fooled by an attribute value"

    narrative, mark = dom_order(fixtures.MARK_BEFORE_NARRATIVE_HTML, "narrative", "mark")
    assert mark < narrative, "the reader missed a mark rendered ahead of its narrative"

    group, item = dom_order(fixtures.CORRECT_REVIEW_ITEM_HTML, "group-actions", "item-actions")
    assert group < item
    group, item = dom_order(fixtures.ITEM_ACTIONS_ABOVE_GROUP_HTML, "group-actions", "item-actions")
    assert item < group

    # A marker that is not there reads as -1 rather than as position 0, so a missing element cannot
    # silently satisfy an ordering assertion.
    assert dom_order(fixtures.ITEM_ACTIONS_ABOVE_GROUP_HTML, "narrative") == [-1]


def test_the_audit_sweep_permits_the_actor_string_and_catches_the_claim():
    """`CT-CONSOLE-23` forbids presenting an actor string as an identity — not the string itself.

    A correct console **renders** `finalized_by`: the audit record exists, and the actor string is
    what the form supplied. What it may not do is present that string as verified, because in a
    dispute that is a false claim (RISK-12).

    So the honest rendering — the field, plus a sentence saying what it is not — must pass. A sweep
    that forbade the field outright would fail the correct implementation, and the honest sentence
    contains the very words the naive net looks for.
    """
    assert authenticated_identity_claims(fixtures.HONEST_AUDIT_SURFACE) == [], (
        "the sweep rejects the honest rendering, which is the copy CT-CONSOLE-23 requires"
    )
    assert "finalized by" in fixtures.HONEST_AUDIT_SURFACE.lower(), (
        "the honest fixture must actually render the actor string, or it is not the hard case"
    )

    claims = authenticated_identity_claims(fixtures.DISHONEST_AUDIT_SURFACE)
    assert len(claims) >= 2, (
        f"the sweep caught {len(claims)} of the three false identity claims in the dishonest "
        f"rendering: {claims}"
    )


def test_visible_degradation_is_a_predicate_and_not_the_absence_of_mojibake():
    """`CT-CONSOLE-24` allows failing **or** degrading visibly — so the predicate is a disjunction.

    The trap is phrasing this as "no mojibake". Almost every output satisfies that, including a
    page that renders right-to-left text perfectly silently and leaves a monolingual operator with
    no way to know the ordering is wrong. That page is the failure the clause is about.

    So the three acceptable outcomes are enumerated — raised, refused, or a rendering that names
    the limitation — and a silent render satisfies none.
    """
    assert not visibly_degraded(fixtures.SILENTLY_DEGRADED_RENDERING, None, refused=False), (
        "a page that renders non-English text and says nothing counts as visible degradation, so "
        "the predicate would pass on the exact outcome CT-CONSOLE-24 forbids"
    )
    assert visibly_degraded(fixtures.HONESTLY_DEGRADED_RENDERING, None, refused=False)
    assert visibly_degraded("", ValueError("unsupported script"), refused=False)
    assert visibly_degraded("", None, refused=True)


def test_visible_text_reads_the_page_rather_than_the_markup():
    """The claim sweeps are about what a reader sees.

    Run over raw markup, a sweep trips on class names and template comments and misses copy that
    lives in an attribute. `CT-CONSOLE-23`'s and `-24`'s assertions are both about rendered text,
    so both go through this.
    """
    assert visible_text(fixtures.CORRECT_REVIEW_ITEM_HTML) == (
        "Accept all 12 Reviewed The derivation on line 12 omits its assumption. met Skip"
    )
    assert "data-role" not in visible_text(fixtures.CORRECT_REVIEW_ITEM_HTML)


def test_element_text_slices_to_one_element_rather_than_the_page():
    """`CT-CONSOLE-13` runs the narrative rule over the **narrative**, not the rendering.

    The mark is a numeral in scoring company by definition — that is what a mark is — so a rule run
    over the whole page condemns every correct review item. Mutation testing found this: making
    `element_text` return the whole page left the suite green, which meant the slice nothing was
    asserting was the thing keeping `TC-CONSOLE-C13` from failing against a compliant console.
    """
    narrative = element_text(fixtures.CORRECT_REVIEW_ITEM_HTML, "narrative")
    assert narrative == "The derivation on line 12 omits its assumption."
    assert "Accept all 12" not in narrative and "met" not in narrative, (
        "the slice leaked the group action and the mark, so the narrative rule would be run over "
        "the mark it is meant to exclude"
    )
    assert element_text(fixtures.CORRECT_REVIEW_ITEM_HTML, "mark") == "met"
    assert element_text(fixtures.CORRECT_REVIEW_ITEM_HTML, "not-a-marker") == ""

    # And the composition the case actually relies on, on an item whose mark renders its points:
    # the page as a whole trips the narrative rule, the sliced narrative does not. If both behaved
    # the same the slice would be decoration, and TC-CONSOLE-C13 would go red against a correct
    # console the first time a mark displayed a number.
    page = fixtures.REVIEW_ITEM_WHOSE_MARK_TRIPS_THE_RULE
    assert forbidden_narrative_claims(visible_text(page)), (
        "the whole-page sweep does not trip on a mark that renders its points, so this fixture no "
        "longer demonstrates why the slice is needed"
    )
    assert not forbidden_narrative_claims(element_text(page, "narrative"))
