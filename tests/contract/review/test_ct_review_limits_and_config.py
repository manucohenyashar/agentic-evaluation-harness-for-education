"""`CT-REVIEW-14`, `-17`, `-18`, `-20` — the contamination boundary, the knobs, the counters, and
what a group actually is.

Test plan §6.11.15, `TC-REVIEW-C14`, `-C17`, `-C18` and `-C20`.

`CT-REVIEW-14` is the security clause and the one whose assertion shape is chosen deliberately.
*"A cross-reference between this module's write set and the fields `M-JUDGE`/`M-EXTRACT` assemble,
asserted as an empty intersection, which is stronger than sampling prompts"* — because sampling
prompts tests the prompts that exist, and the contamination channel opens when somebody adds a
prompt field later and finds a teacher's note sitting in the row it reads.
"""

from __future__ import annotations

import dataclasses

import pytest

from tests.support import broken_review_fixtures as broken
from tests.support import review_vocabulary as vocab
from tests.support.impl import (
    CONSOLE_MODULE,
    EXTRACT_MODULE,
    JUDGE_MODULE,
    REVIEW_MODULE,
    STATS_MODULE,
    require,
    require_attr,
)

pytestmark = pytest.mark.contract


# --- CT-REVIEW-14 — review is downstream of scoring, in the strict sense -------------------------


#: The two modules whose prompt assembly `CT-REVIEW-14` intersects the write set against, each
#: with the story that delivers it. Parametrized rather than looped: `M-JUDGE` (#78) and
#: `M-EXTRACT` (#68) are independent stories and either can land first, so a single test needing
#: both could only be registered against one of them — which is exactly the first-blocker keying
#: `WRITTEN_AHEAD_BLOCKERS` exists to forbid. Two node ids, two honest keys.
PROMPT_ASSEMBLERS: tuple[tuple[str, str], ...] = (("judge", "#78"), ("extract", "#68"))


@pytest.mark.writtenahead
@pytest.mark.parametrize(
    "consumer, issue", PROMPT_ASSEMBLERS, ids=[c for c, _ in PROMPT_ASSEMBLERS]
)
def test_tc_review_c14_the_write_set_and_the_scoring_prompt_fields_do_not_intersect(
    consumer, issue
):
    """The empty-intersection assertion, *"which is stronger than sampling prompts"*.

    Every field this module writes, against every field the consumer assembles into a prompt. The
    intersection is the contamination channel and it must be empty — not "no current prompt reads
    a review field", which is a statement about today's prompts, but "there is no field a prompt
    could read", which survives the next prompt somebody writes.

    Both consumers are checked, and separately, because they assemble different things:
    `M-EXTRACT` reads the submission, `M-JUDGE` reads the evidence, and a review field leaking
    into either is R15.
    """
    module_path = {"judge": JUDGE_MODULE, "extract": EXTRACT_MODULE}[consumer]
    write_fields = require(REVIEW_MODULE, "write_fields", issue="#109")()

    assert write_fields, (
        "the module reports an empty write set, so this intersection is empty for the wrong "
        "reason"
    )

    prompt_fields = set(require(module_path, "prompt_fields", issue=issue)())
    assert prompt_fields, (
        f"M-{consumer.upper()} reports no prompt fields, so the intersection below is vacuous"
    )
    shared = sorted(set(write_fields) & prompt_fields)
    assert shared == [], (
        f"M-REVIEW writes {shared}, which M-{consumer.upper()}'s prompt assembly reads. "
        "FR-REVIEW-17: no field this module writes is read by any scoring prompt — review is "
        "downstream of scoring in the strict sense, and a field on both sides of that line is "
        "the cross-student contamination channel R15 exists to close."
    )


@pytest.mark.writtenahead
def test_tc_review_c14_the_module_exposes_no_per_student_annotation_surface():
    """*"Assert it exposes no per-student annotation surface."*

    The surface arrives named for its screen — `annotate_submission`, `student_notes`,
    `add_comment` — rather than for the prohibition, which is why the rule matches substrings and
    why it is controlled in both directions in the vocabulary suite.

    Worth separating from the intersection test above: an annotation surface that writes to a
    table no prompt currently reads passes that one, and it is a per-student free-text field
    sitting one join away from every future prompt.
    """
    module = require(REVIEW_MODULE, issue="#109")
    surface = [name for name in dir(module) if not name.startswith("_")]

    found = vocab.annotation_surface_members(surface)
    assert found == [], (
        f"the module exposes {found}. FR-REVIEW-17: no per-student annotation surface that a "
        "later judgment could pick up."
    )


@pytest.mark.writtenahead
def test_tc_review_c14_nothing_a_teacher_records_reaches_a_rerun_of_the_same_unit():
    """The rung-3 reachability half, *"including on a resumed or re-run unit, which is the route
    that would actually open."*

    And it is the route that would actually open, because a re-run is where reuse is the obvious
    optimization: the unit has been scored, a teacher has corrected it, and re-running from
    scratch throws away information somebody paid for. Every instinct says feed the correction
    back. `FR-REVIEW-17` says the opposite, and the reason is R15 — a panel that can see a
    teacher's earlier judgement is not an independent one, and the agreement figure computed
    afterwards is measuring an echo.

    Asserted over the prompt the re-run actually assembles, not over the module's declared write
    set, because this is the path where a field crosses without being declared anywhere.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    assemble_prompt = require(JUDGE_MODULE, "assemble_prompt", issue="#78")

    service = build_review(scores=broken.flagged_population(20))
    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    item = queue.shown[0]
    service.act(item, action="override", new_band="B1", review_seconds=45)

    prompt = assemble_prompt(
        submission_id=item.submission_id, criterion_id=item.criterion_id, rerun=True
    )
    text = str(prompt)

    assert "B1" not in text, (
        "the teacher's override band appears in the prompt assembled for a re-run of the same "
        "unit. FR-REVIEW-17, R15: nothing a teacher records here can reach a later judgment."
    )
    # Whole words. `origin` is a substring of `original`, and a prompt saying "the original
    # submission" is compliant — a substring scan fails it. Review caught that.
    carried = vocab.label_fields_in(text)
    assert carried == [], (
        f"the re-run prompt carries the label fields {carried}. A panel that can see how the "
        "unit was reviewed is not scoring it independently."
    )


# --- CT-REVIEW-17 — the four knobs are M-STATS's inputs -----------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("knob", sorted(vocab.CONFIG_DEFAULTS))
def test_tc_review_c17_each_knob_declares_its_documented_default(knob):
    """*"Assert the four knobs' declared defaults (10, 15, 12, 30)."*

    Transcribed from §3.15's Configuration line and asserted against the module. Parametrized so a
    failure names the knob rather than reporting that a dict comparison failed — four numbers in
    one assertion produce a message nobody can act on.
    """
    declared = require(REVIEW_MODULE, knob, issue="#108")

    assert declared == vocab.CONFIG_DEFAULTS[knob], (
        f"{knob} defaults to {declared!r} against §3.15's declared "
        f"{vocab.CONFIG_DEFAULTS[knob]!r}. "
        "These are Assumption values — changing one is a design decision, not an implementation "
        "detail, because CT-REVIEW-17 makes all four M-STATS's inputs."
    )


@pytest.mark.writtenahead
@pytest.mark.parametrize("knob", ["REVIEW_BLIND_N"])
def test_tc_review_c17_moving_a_knob_changes_how_much_validation_evidence_is_produced(knob):
    """*"Measured as label counts, not as a settings read."*

    The distinction is the case. A test that reads the setting back asserts that a variable was
    assigned; `CT-REVIEW-17`'s claim is that these four knobs *"change how much validation
    evidence an administration produces"*, which is a claim about the label store. A module that
    accepts the knob and ignores it passes the settings read and fails here.

    **One knob rather than four, and that is a finding.** `CT-REVIEW-17` says all four *"change
    how much validation evidence an administration produces"*, and three of them cannot be
    measured that way inside this module.

    * `REVIEW_WHOLE_GRADE_N` sizes a sample that writes no label — `FR-REVIEW-14` offers it as a
      display, and `FR-REVIEW-09` writes labels for teacher *actions*.
    * `REVIEW_DEFAULT_BUDGET_MINUTES` is a default for a parameter §3.15's own Interfaces block
      declares as required — `build_queue(self, run_id, budget_minutes)` — so nothing in this
      module ever reads it.
    * `REVIEW_BLIND_RESERVE_MINUTES` sizes the *reservation*, and nothing in §3.15 couples
      reserved minutes to sample size: `blind_sample(n=...)` draws `REVIEW_BLIND_N` submissions
      whatever the reserve is. An earlier draft swept it here and the assertion could not have
      passed for any implementation — review caught that.

    All four are asserted for their declared values by the test above. Only `REVIEW_BLIND_N` has
    a label-count differential to measure, and inventing one for the other three would be worse
    than reporting it.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    population = broken.flagged_population(120, criteria=1)
    require_attr(build_review(scores=population), "blind_sample", issue="#111")

    counts = {}
    for value in (vocab.CONFIG_DEFAULTS[knob], vocab.CONFIG_DEFAULTS[knob] + 5):
        service = build_review(scores=population, **{knob.lower(): value})
        session = service.blind_sample(run_id="run-1")
        ids = service.submit_blind(
            session.session_id, bands={ref: "B2" for ref in session.items}
        )
        counts[value] = len(ids)

    low, high = sorted(counts)
    assert counts[high] > counts[low], (
        f"raising {knob} from {low} to {high} produced {counts[low]} and {counts[high]} labels — "
        "no change. CT-REVIEW-17: these knobs change how much validation evidence an "
        "administration produces, and §7.4 records that a low budget silently weakens every "
        "validity claim that administration makes."
    )


@pytest.mark.writtenahead
def test_tc_review_c17_m_stats_achievable_precision_moves_with_the_knobs():
    """The rung-3 half: the knobs are *"`M-STATS`'s inputs as much as this module's settings"*.

    Asserted as the width of the interval `M-STATS` can report, because that is what "achievable
    precision" means and it is the thing a teacher's budget decision actually buys. A smaller
    sample is not a wrong figure; it is a wider one, and the clause's point is that the setting
    lives here while the consequence lands there.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    population = broken.flagged_population(200, criteria=1)
    require_attr(build_review(scores=population), "blind_sample", issue="#111")

    widths = {}
    for n in (vocab.BLIND_SAMPLE_RANGE[0], vocab.BLIND_SAMPLE_RANGE[1]):
        service = build_review(scores=population, review_blind_n=n)
        session = service.blind_sample(run_id="run-1", n=n)
        ids = service.submit_blind(
            session.session_id, bands={ref: "B2" for ref in session.items}
        )
        figure = build_stats(labels=[service.label(i) for i in ids]).agreement(scope=None)
        widths[n] = figure.interval_high - figure.interval_low

    small, large = vocab.BLIND_SAMPLE_RANGE
    assert widths[large] < widths[small], (
        f"a sample of {large} produced an interval of width {widths[large]:.3f} against "
        f"{widths[small]:.3f} at {small}. CT-REVIEW-17: the knob is M-STATS's input — more blind "
        "labels buy a narrower claim, and a system where they do not is not reporting an interval "
        "that depends on its evidence."
    )


# --- CT-REVIEW-18 — the counters, in pairs, retained across administrations ----------------------


@pytest.mark.writtenahead
def test_tc_review_c18_every_named_counter_is_emitted():
    """§3.15's Observability line, by set containment.

    Containment rather than equality: a module emitting extra counters is not violating anything,
    and asserting equality would fail the first useful addition. The clause names a floor.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(40))
    require_attr(service, "observability_counters", issue="#110")

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    service.act(queue.shown[0], action="accept", new_band=None, review_seconds=20)
    emitted = set(service.observability_counters(run_id="run-1"))

    missing = sorted(set(vocab.OBSERVABILITY_COUNTERS) - emitted)
    assert missing == [], (
        f"the module does not emit {missing}. §3.15's Observability line names these, and a "
        "counter that is not emitted is a question nobody can ask of a finished run."
    )


@pytest.mark.writtenahead
def test_tc_review_c18_shown_and_flagged_are_emitted_as_a_pair():
    """*"Both, since the pair **is** the R12 honesty check and either alone is uninformative."*

    `review_items_shown` on its own reads as productivity — 40 items reviewed, good sitting.
    Beside `review_items_flagged` at 812 it reads as what it is. So the assertion is that neither
    is emitted without the other, which is a stronger claim than both being present in one
    snapshot: a module that emits `shown` per sitting and `flagged` per run publishes the
    reassuring half four times as often.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(200))
    require_attr(service, "counter_emissions", issue="#110")

    queue = service.build_queue(run_id="run-1", budget_minutes=30)
    service.act(queue.shown[0], action="accept", new_band=None, review_seconds=20)

    emissions = service.counter_emissions(run_id="run-1")
    shown, flagged = vocab.HONESTY_CHECK_PAIR

    assert emissions, (
        "the module recorded no counter emissions, so the pairing assertion below holds over an "
        "empty list and asserts nothing"
    )
    assert any(shown in e.names or flagged in e.names for e in emissions), (
        f"neither {shown!r} nor {flagged!r} was ever emitted. A module that emits neither is "
        "trivially consistent about the pair and has published nothing about R12's honesty check."
    )

    unpaired = [e.at for e in emissions if (shown in e.names) != (flagged in e.names)]
    assert unpaired == [], (
        f"{len(unpaired)} emissions carried one of {vocab.HONESTY_CHECK_PAIR} without the other. "
        "R12's honesty check is the pair: how much was shown, against how much there was. Either "
        "figure alone is a different and more comfortable claim."
    )


@pytest.mark.writtenahead
def test_tc_review_c18_the_budget_exhaustion_signal_is_retained_across_administrations():
    """*"So assert the signal is retained across administrations rather than reset each term,
    which is what 'absorbed each term' describes."*

    §3.15's Alert is about a **pattern**: one criterion eating the whole budget once is a busy
    week, and the same criterion doing it three terms running is a rubric problem. A signal that
    resets each administration can never see the second one — and "absorbed each term" is exactly
    how HLD §10 item 5 describes the failure it wants surfaced.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=broken.flagged_population(200))
    require_attr(service, "exhaust_budget_on", issue="#110")
    require_attr(service, "alerts", issue="#110")

    for administration in ("admin-1", "admin-2"):
        service.exhaust_budget_on(criterion_id="C-01", administration_id=administration)

    alerts = list(service.alerts())
    matching = [a for a in alerts if a.name == vocab.BUDGET_EXHAUSTION_ALERT]

    assert matching, (
        f"no {vocab.BUDGET_EXHAUSTION_ALERT!r} alert fired after C-01 exhausted the budget in "
        f"{vocab.ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS} consecutive administrations. §3.15's "
        "Alert surfaces this as a pattern rather than letting it be absorbed each term."
    )
    alert = matching[0]
    assert alert.consecutive_administrations >= vocab.ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS, (
        f"the alert reports {alert.consecutive_administrations} consecutive administrations, so "
        "the signal did not survive the administration boundary — which is the whole content of "
        "the requirement."
    )


# --- CT-REVIEW-20 — what grouping is at Phase 1, and what it may be called ------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("component", sorted(vocab.GROUP_SIGNATURE_COMPONENTS))
def test_tc_review_c20_two_items_differing_in_any_signature_component_are_not_grouped(component):
    """*"Assert the actual grouping rule rather than a semantic one: two items differing in any
    signature component are **not** grouped, even when semantically identical."*

    Parametrized per component so a failure names the one the grouping ignores. A single
    "different row" fixture would pass a rule that reads `proposed_band` and none of the four
    integrity signals — which is the likely first implementation, and it groups an item whose
    spans were never verified with eleven whose were.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    members = broken.identical_signature_population(12)
    variant = broken.signature_variants(members[0])[component]

    service = build_review(scores=[*members, variant])
    require_attr(service, "group_signature", issue="#108")
    queue = service.build_queue(run_id="run-1", budget_minutes=600)

    grouped_ids = {m.score_id for group in queue.groups for m in group.members}
    assert variant.score_id not in grouped_ids, (
        f"an item differing only in {component!r} was grouped with twelve that share the other "
        "components. CT-REVIEW-20: Phase 1 grouping is exact band-plus-integrity-signature, and "
        "a teacher applying one band to this group would be acting on a false premise about "
        "which one."
    )
    assert len(grouped_ids) == len(members), (
        f"{len(grouped_ids)} items were grouped against the {len(members)} that share a "
        "signature, so the group is not the set the rule defines"
    )


@pytest.mark.writtenahead
def test_tc_review_c20_the_group_signature_is_exactly_the_declared_components():
    """The other direction of the same rule: twelve items sharing all five components **do** group.

    Without this, the case above is satisfied by a module that never groups anything — which
    would pass every "not grouped" assertion and deliver none of `FR-REVIEW-05`'s value. Grouping
    that is too narrow fails silently and looks like caution.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    members = broken.identical_signature_population(12)
    service = build_review(scores=members)

    queue = service.build_queue(run_id="run-1", budget_minutes=600)
    assert queue.groups, (
        "twelve rows sharing a band and all four integrity signals produced no group. "
        "FR-REVIEW-05 presents one group item rather than N separate ones; a grouping rule that "
        "never fires is not conservative, it is absent."
    )
    assert len(queue.groups[0].members) == len(members), (
        f"the group holds {len(queue.groups[0].members)} of {len(members)} identical items"
    )
    signature = service.group_signature(members[0])
    assert set(signature) == set(vocab.GROUP_SIGNATURE_COMPONENTS), (
        f"the group signature is built from {sorted(signature)} against §3.15's "
        f"{sorted(vocab.GROUP_SIGNATURE_COMPONENTS)}. A signature with fewer components groups "
        "items the clause says are different; one with more never groups anything."
    )


@pytest.mark.writtenahead
def test_tc_review_c20_the_console_does_not_describe_a_group_as_semantically_clustered():
    """The consumer obligation, over rendered language.

    *"The risk this guards is a teacher applying one band to a group they believe is homogeneous
    when it is only signature-identical — a bulk action taken on a false premise."* The false
    premise arrives in the caption: "210 similar responses" is a claim about content that Phase 1
    grouping does not make and cannot support.

    `semantic_clustering_language` matches whole words for single terms and substrings for
    phrases, so *"dissimilar in wording"* passes and *"210 similar responses"* does not — both
    controlled in the vocabulary suite.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    render_review_queue = require(CONSOLE_MODULE, "render_review_queue", issue="#124")

    # Rendered from a population that actually groups, so there is a group caption to sweep. Over
    # a queue with no group the sweep is empty and passes for any console — review caught that.
    service = build_review(scores=broken.identical_signature_population(12))
    queue = service.build_queue(run_id="run-1", budget_minutes=600)
    assert queue.groups, (
        "the fixture produced no group, so the rendering carries no group caption and this sweep "
        "asserts nothing"
    )
    rendering = render_review_queue(service, run_id="run-1", budget_minutes=600)
    claims = vocab.semantic_clustering_language(rendering)

    assert claims == [], (
        f"the queue screen describes a group with {claims}. CT-REVIEW-20: Phase 1 grouping is "
        "exact band-plus-integrity-signature, which is weaker than the HLD's 'all 210 show the "
        "same pattern' implies (§4.6) — and the gap between the two is a bulk action taken on a "
        "false premise."
    )
