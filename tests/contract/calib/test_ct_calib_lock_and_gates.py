"""`CT-CALIB-06`…`-10`, `-13`, `-14`, `-16` — the lock, the two gates, and what a pass means.

Test plan §6.11.17, TS-74 (issue #142). These are the clauses that stand between a proposed rubric
edit and a live one. The design is explicit about why they exist in this module specifically:

> **Security.** […] The integrity control that matters is `M-PKG`'s lock: this module is where
> construct drift would enter, and the design's answer is that it structurally cannot write the
> fields that would carry it.

That shape recurs. `CT-CALIB-06` makes the lock structural by routing every edit through `M-PKG`.
`CT-CALIB-07` and `-08` are the two guardrail gates. `CT-CALIB-13` makes the threshold an owned
decision rather than a default. And `CT-CALIB-16` is a **non-promise** that draws the line between
*non-inferiority* and *improvement* — the misreading that would turn all of the above into a
quality claim nobody made.

All red. See `test_ct_calib_vocabulary.py` for what is green and why it is not coverage.
"""

from __future__ import annotations

import pytest

from tests.support.calib_vocabulary import (
    DECLARED_KNOBS,
    affirmative_sentences,
    LOCKED_FIELDS,
    SUPERIORITY_LANGUAGE,
)
from tests.support.impl import (
    CALIB_MODULE,
    CONSOLE_MODULE,
    GRADE_MODULE,
    STATS_MODULE,
    require,
)
from tests.support.guards import recording_write_audit

pytestmark = pytest.mark.contract


# --- CT-CALIB-06 — every edit goes through M-PKG, and the lock does the rest ----------------------


@pytest.mark.writtenahead
def test_tc_calib_c06_no_edit_reaches_tier_p_except_through_the_catalog():
    """`CT-CALIB-06` — **every** applied edit is written through `M-PKG`, under a Tier P write
    audit. No direct write, on any path.

    The clause's value is that `M-CALIB` needs **no second check of its own**: route the write
    through the catalog and `FR-PKG-03`'s lock applies to calibration output for free. A second
    check implemented here is the thing that would drift out of step with the first (RISK-06) — so
    the assertion is about the *route*, not about the outcome.

    Rung 3, with a real catalog and a write audit over the Tier P file: a direct write is invisible
    to any assertion made through the catalog's own API, which is exactly why the audit is the
    oracle.
    """
    calib = require(CALIB_MODULE, issue="#138")
    apply_answers = require(CALIB_MODULE, "apply_answers", issue="#138")

    tier_p = calib.tier_p_path_for_test()
    catalog = calib.catalog_for_test(tier_p_path=tier_p)

    # A **recording** audit, not the blocking `write_audit()`. This case must tell a permitted
    # write (the catalog's, which is required) from a forbidden one (anything else) — and the
    # blocking guard raises on whichever comes first, making the two indistinguishable and the
    # "did the catalog write?" assertion below unreachable. §6.11.17's Oracle is a
    # "**write-audit log**", which is a recorder rather than a guard.
    with recording_write_audit() as writes:
        apply_answers({"q1": "broaden"}, catalog=catalog)

    touched_tier_p = [w for w in writes if str(tier_p) in str(w.target)]
    assert touched_tier_p, (
        "nothing wrote to Tier P at all, so this audit observed no write to classify and the "
        "assertion below would pass over an empty log"
    )

    outside = [w for w in touched_tier_p if w not in catalog.audited_writes]
    assert not outside, (
        "M-CALIB wrote to Tier P outside the catalog: "
        + ", ".join(f"{w.api}({w.target!r})" for w in outside)
        + ". CT-CALIB-06 makes the lock structural by routing every edit through M-PKG; a "
        "direct write bypasses FR-PKG-03 entirely."
    )
    assert catalog.writes, "the edit did not reach the catalog either — nothing was applied"


@pytest.mark.writtenahead
@pytest.mark.parametrize("locked_field", LOCKED_FIELDS)
def test_tc_calib_c06_an_edit_attempting_a_locked_field_raises_schema_lock_violation(locked_field):
    """The §6.2 lock swept **from `M-CALIB`'s side**, one row per forbidden field.

    `FR-CALIB-07` names the acceptance form exactly: *"a calibration edit attempting any locked
    field raises `SchemaLockViolation`"*. Parametrized over the full list so a regression names the
    field that stopped being locked — the seven are not interchangeable, and `criterion_band` in
    particular is the one whose loss would let a revision redefine what a band *means* while every
    band label stayed the same.

    The exception must come from the **catalog**, not from a guard in `M-CALIB`. That is the whole
    clause: a check here would be a second implementation of the lock, and two implementations of
    one rule drift.
    """
    calib = require(CALIB_MODULE, issue="#138")
    apply_answers = require(CALIB_MODULE, "apply_answers", issue="#138")
    SchemaLockViolation = require(CALIB_MODULE, "SchemaLockViolation", issue="#138")

    catalog = calib.catalog_for_test()
    edit = calib.edit_touching(locked_field)

    with pytest.raises(SchemaLockViolation) as caught:
        apply_answers({"q1": "broaden"}, catalog=catalog, forced_edit=edit)

    assert locked_field in str(caught.value), (
        f"the refusal does not name {locked_field!r}; FR-PKG-03 says each attempt raises "
        "SchemaLockViolation *naming the field*"
    )
    assert caught.value.raised_by == "catalog", (
        f"{locked_field} was refused by M-CALIB rather than by the catalog. CT-CALIB-06's point is "
        "that this module needs no second check — and a second check is what drifts (RISK-06)."
    )


# --- CT-CALIB-07 — the non-inferiority gate -------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_calib_c07_the_gate_refuses_to_run_on_the_calibration_set():
    """`CT-CALIB-07` / `NFR-CALIB-02` — the gate operates on the **full class**, and refuses the
    calibration set.

    A refusal rather than a warning, because the calibration set *"lacks the sample size to mean
    anything"*: a gate run on twenty papers returns a number, and a number that means nothing is
    worse than no number — it is a passed gate somebody will cite.
    """
    calib = require(CALIB_MODULE, issue="#139")
    non_inferiority = require(CALIB_MODULE, "non_inferiority", issue="#139")

    with pytest.raises(calib.InsufficientPopulation):
        non_inferiority(r0="pkg-v1", r1="pkg-v2", cohort_id=calib.CALIBRATION_SET, threshold=0.10)


@pytest.mark.writtenahead
@pytest.mark.parametrize(
    "shifted_fraction, expected",
    [
        # Fractions a realistic class can express. An earlier draft used 0.0999 and 0.1001,
        # which need a cohort of 10,000 — with any real class the fixture must round, and
        # 0.1001 rounding to 0.10 turns the reject row into a spurious failure. A 100-student
        # class expresses every fraction below exactly.
        (0.05, "pass"),
        (0.09, "pass"),
        (0.10, "pass"),     # exactly at threshold: "more than" is strict, so this passes
        (0.11, "reject"),
        (0.25, "reject"),
    ],
)
def test_tc_calib_c07_the_revision_is_rejected_above_the_threshold(shifted_fraction, expected):
    """The boundary sweep, including **exactly at threshold**.

    `FR-CALIB-08` rejects when **more than** a declared threshold of the class shifts by a full
    band. "More than" is strict, so exactly-at-threshold passes — and that is the row an
    implementation using `>=` gets wrong. It is one comparison operator between a revision going
    live and being rejected.

    A **full band**, not any change: a student moving within a band has not been regraded in any
    sense a teacher would recognize, and counting those would reject every revision.
    """
    calib = require(CALIB_MODULE, issue="#139")
    non_inferiority = require(CALIB_MODULE, "non_inferiority", issue="#139")

    cohort = calib.cohort_with_band_shift(fraction=shifted_fraction, class_size=100)
    result = non_inferiority(r0="pkg-v1", r1="pkg-v2", cohort_id=cohort, threshold=0.10)

    assert result.outcome == expected, (
        f"{shifted_fraction:.2f} of the class shifted a full band against a 0.10 threshold and "
        f"the gate returned {result.outcome!r}, not {expected!r}. FR-CALIB-08 rejects on *more "
        "than* the threshold, so exactly-at-threshold passes."
    )


@pytest.mark.writtenahead
def test_tc_calib_c07_the_threshold_is_recorded_before_any_result_exists():
    """The methodological assertion that makes the gate honest — an **event-order** oracle.

    `FR-CALIB-08`: the threshold is *"declared before the comparison rather than chosen after"*.
    A threshold chosen after the results is not a gate, it is a description of what happened, and
    the whole apparatus of dual-scoring becomes ceremony around a decision already made.

    Asserted as ordering rather than as presence: the threshold's recorded timestamp precedes the
    first result's. A post-hoc adjustment then shows up as one — which is the point. The gate
    cannot prevent somebody re-running it with a looser number; it can make that visible.
    """
    calib = require(CALIB_MODULE, issue="#139")
    non_inferiority = require(CALIB_MODULE, "non_inferiority", issue="#139")

    # Read **from configuration**, not passed as a literal. An earlier draft passed
    # `threshold=0.10` and then asserted `threshold_source == "configuration"` — a module
    # honestly reporting where its value came from would say "argument", so the only way to
    # pass was to misreport, or to ignore the parameter §3.17 declares.
    calib.declare_institutional_threshold(0.10)
    cohort = calib.cohort_with_band_shift(fraction=0.05, class_size=100)
    result = non_inferiority(r0="pkg-v1", r1="pkg-v2", cohort_id=cohort, threshold=None)

    assert result.threshold_used == 0.10, "the declared institutional threshold was not used"
    assert result.threshold_declared_at is not None, "the threshold was never recorded"
    assert result.first_result_at is not None
    assert result.threshold_declared_at < result.first_result_at, (
        "the threshold was recorded at or after the first result, so nothing distinguishes a "
        "declared threshold from one chosen to fit the outcome (FR-CALIB-08)"
    )
    assert result.threshold_source == "configuration", (
        f"the threshold came from {result.threshold_source!r} rather than from configuration"
    )


# --- CT-CALIB-08 — adversarial back-translation ---------------------------------------------------


@pytest.mark.writtenahead
def test_tc_calib_c08_an_off_panel_model_shared_with_the_panel_is_refused_at_configuration_time():
    """`CT-CALIB-08` / `NFR-CALIB-04` — the off-panel model is **not in the scoring panel**, and a
    shared build is refused.

    At **configuration time**, which is the assertion. A shared build would let the panel's own
    blind spots define the adversarial search: the model looking for a response on which R₀ and R₁
    differ is the same model that produced the scores, so the responses it cannot imagine are
    exactly the ones it will not construct. The gate would pass by construction.

    Refused when the *build* matches, not merely the provider — `M-CONF`'s `panel_build_ref` exists
    because two entries naming the same served build are the same model however they are labelled.
    """
    calib = require(CALIB_MODULE, issue="#139")
    back_translate = require(CALIB_MODULE, "back_translate", issue="#139")

    shared = calib.model_ref_in_panel()

    with pytest.raises(calib.OffPanelConfigurationError):
        back_translate(r0="pkg-v1", r1="pkg-v2", off_panel=shared)


@pytest.mark.writtenahead
def test_tc_calib_c08_a_successful_construction_rejects_the_revision():
    """The interpretation the clause fixes: a construction is **evidence the construct changed**.

    `FR-CALIB-09` treats a successful construction — a response on which R₀ and R₁ differ — as
    evidence, not as a curiosity. So the outcome is a **rejection**, not an advisory note attached
    to a revision that ships anyway.

    That distinction is the case. An advisory note is `CT-CALIB-02`'s forbidden "revision with a
    warning" wearing a different name: the revision goes live, scores the class, and its results
    enter every accumulated validation record.
    """
    calib = require(CALIB_MODULE, issue="#139")
    back_translate = require(CALIB_MODULE, "back_translate", issue="#139")

    result = back_translate(
        r0="pkg-v1", r1="pkg-v2", off_panel=calib.model_ref_off_panel(),
    )

    assert result.divergent_response_found, "the fixture did not construct a divergence"
    assert result.outcome == "reject", (
        f"a constructed divergence produced {result.outcome!r}. FR-CALIB-09 treats it as evidence "
        "the construct changed, and an advisory note is CT-CALIB-02's warned revision renamed."
    )
    assert not result.advisory_only


# --- CT-CALIB-09 — R₁ pinning, and the rollup boundary --------------------------------------------


@pytest.mark.writtenahead
def test_tc_calib_c09_r1_is_pinned_with_the_approval_and_a_timestamp():
    """`CT-CALIB-09`, first half — R₁ is version-pinned **with the teacher's approval and a
    timestamp** (`FR-CALIB-11`).

    Three fields, and the approval is the one that matters: a revision pinned with a version and a
    time but no approver is a rubric change nobody owns. `elicitation_history` records how the edit
    was reached; this records who accepted it.
    """
    calib = require(CALIB_MODULE, issue="#139")
    pin = require(CALIB_MODULE, "pin_revision", issue="#139")

    pinned = pin(r1="pkg-v2", approved_by="t.mensah")

    assert pinned.package_version == "pkg-v2"
    assert pinned.approved_by == "t.mensah", "the pinned revision names no approver"
    assert pinned.approved_at is not None, "the pinned revision carries no timestamp"
    assert calib is not None


@pytest.mark.writtenahead
def test_tc_calib_c09_a_rollup_never_mixes_r0_and_r1_results_without_annotation():
    """`CT-CALIB-09`'s **consumer half**, at rung 3 and on its own blocker (`M-GRADE`).

    *"R₀-scored and R₁-scored results never appear in one class rollup without explicit
    annotation."* This is where RISK-06 actually arrives: the numbers describe **two different
    instruments**, and a mean over both is a figure about nothing. Nobody notices, because it
    looks like every other class mean.

    Either behaviour satisfies the clause — separate them, or annotate — so the assertion admits
    both and rejects the third thing: one undifferentiated rollup. Split from the pinning half
    above because it lands with `M-GRADE`, not with the gate story.
    """
    grade = require(GRADE_MODULE, issue="#101")
    rollup = require(GRADE_MODULE, "class_rollup", issue="#101")

    mixed = rollup(cohort_id=grade.cohort_with_mixed_revisions())

    separated = len(mixed.segments) > 1
    annotated = bool(mixed.revision_annotation)

    assert separated or annotated, (
        "a class rollup mixed R₀-scored and R₁-scored results with neither separation nor "
        "annotation. The numbers describe two different instruments (CT-CALIB-09, RISK-06)."
    )
    if separated:
        assert {segment.rubric_version for segment in mixed.segments} == {"pkg-v1", "pkg-v2"}


@pytest.mark.writtenahead
def test_tc_calib_c09_m_stats_scopes_its_figures_across_the_revision_boundary():
    """`CT-CALIB-09`'s **second consumer**, missing from the first draft.

    §6.11.17: *"…and that `M-STATS` scopes its figures across the revision boundary."* The
    rollup assertion above is `M-GRADE`'s; this is `M-STATS`'s, and it matters for longer — an
    accumulated validation record spanning a revision describes two instruments, and it is then
    used to decide whether the *next* revision is safe. That is RISK-06 compounding.
    """
    stats = require(STATS_MODULE, issue="#118")
    figures = require(STATS_MODULE, "criterion_figures", issue="#118")

    scoped = figures(cohort_id=stats.cohort_with_mixed_revisions())

    assert scoped, "M-STATS produced no figures for a cohort spanning a revision"
    assert all(figure.rubric_version is not None for figure in scoped), (
        "M-STATS produced figures that name no rubric version, so a reader cannot tell which "
        "instrument they describe (CT-CALIB-09)"
    )
    assert {figure.rubric_version for figure in scoped} == {"pkg-v1", "pkg-v2"}, (
        "the figures do not span both revisions, so nothing shows they were scoped rather "
        "than silently merged"
    )


# --- CT-CALIB-10 — a rubric published in advance ---------------------------------------------------


@pytest.mark.writtenahead
def test_tc_calib_c10_a_published_rubric_defaults_to_r0_and_says_why():
    """`CT-CALIB-10` / `FR-CALIB-12` — where the rubric was published to students in advance, the
    module **defaults to R₀** and **surfaces the fairness implication explicitly**.

    Two assertions, and the second is why this is not one. A silent default is *correct behaviour
    nobody can see*: calibration quietly does nothing, the teacher assumes it ran, and the reason
    — that revising a rubric students were shown in advance changes the assignment after they
    answered it — is never stated. The clause asks for the explanation, so the case asserts the
    explanation exists and names the reason rather than merely being non-empty.
    """
    calib = require(CALIB_MODULE, issue="#138")
    run = require(CALIB_MODULE, "run_for_assignment", issue="#138")

    outcome = run(assignment=calib.assignment(rubric_published_in_advance=True))

    assert outcome.active_rubric == outcome.r0_version, (
        "calibration revised a rubric that had been published to students in advance"
    )
    assert outcome.fairness_note, (
        "the module defaulted to R₀ without surfacing why. A silent default is correct behaviour "
        "nobody can see (CT-CALIB-10)."
    )
    assert "published" in outcome.fairness_note.lower(), (
        f"the surfaced note does not name the reason: {outcome.fairness_note!r}"
    )


# --- CT-CALIB-13 — the threshold is an owned decision ---------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("knob", sorted(DECLARED_KNOBS))
def test_tc_calib_c13_each_knob_is_read_and_has_an_externally_visible_effect(knob):
    """`CT-CALIB-13` — the three knobs are read, and moving each changes something observable.

    A knob read and then ignored is worse than one never read: the operator sets it, the value
    appears in configuration, and the run behaves as though it were never set. Nothing contradicts
    them.

    The declared *values* are asserted separately, against the design, in
    `test_ct_calib_vocabulary.py` — deliberately, because `CALIB_NONINFERIORITY_THRESHOLD`'s
    declared value and its behaviour are two different claims (see the case below).
    """
    calib = require(CALIB_MODULE, issue="#139")

    assert knob in calib.KNOBS, f"{knob} is not among the knobs the module reads"

    # The knob is **moved and the difference observed**, not reported on. An earlier draft
    # asserted `calib.knob_has_visible_effect(knob)` — the module grading its own homework,
    # satisfied by a method returning True. A knob read and then ignored is worse than one
    # never read: the operator sets it, the value appears in configuration, and nothing
    # contradicts them.
    low, high = calib.contrasting_values_for(knob)

    assert calib.observable_behaviour_with(knob, low) != calib.observable_behaviour_with(
        knob, high
    ), (
        f"{knob} moved from {low!r} to {high!r} and nothing observable changed — it is read "
        "and then ignored"
    )


@pytest.mark.writtenahead
def test_tc_calib_c13_the_gate_refuses_to_run_when_no_institutional_threshold_is_declared():
    """`CT-CALIB-13`'s substance, and the reason 0.10 is **not a default**.

    The clause is explicit: the threshold is *"an example value from the HLD, not a validated
    one"* and *"must be declared per institution before use"*. So the behaviour is a **refusal**,
    not a fallback — a defaulted threshold is an unowned decision governing whether a rubric
    changes, and the institution that inherits it never chose it.

    This case and the declared-value assertion in `test_ct_calib_vocabulary.py` are deliberately
    apart. Asserting both in one place would be asserting that 0.10 is simultaneously the default
    and not one; here, 0.10 is what the design *documents*, and the *system* refuses to proceed
    until somebody declares their own.
    """
    calib = require(CALIB_MODULE, issue="#139")
    non_inferiority = require(CALIB_MODULE, "non_inferiority", issue="#139")

    cohort = calib.cohort_with_band_shift(fraction=0.05)

    with pytest.raises(calib.ThresholdNotDeclared):
        non_inferiority(r0="pkg-v1", r1="pkg-v2", cohort_id=cohort, threshold=None)


# --- CT-CALIB-14 — what it emits, and how it alerts ------------------------------------------------


@pytest.mark.writtenahead
def test_tc_calib_c14_the_module_emits_findings_by_category_questions_and_gate_outcomes():
    """`CT-CALIB-14` — an **artifact assertion on names and dimensionality**.

    Four things: findings **by triage category**, questions asked **versus** answered, gate
    outcomes, and the class shift distribution under dual scoring.

    Dimensionality is the assertion, not just presence. Findings emitted as a single total cannot
    answer *which kind* — and the three categories mean entirely different things: a rubric with
    many `rubric_ambiguity` findings needs a conversation, one with many `model_failure` findings
    needs a pipeline fix, and one with many `teacher_inconsistency` findings needs neither. Asked
    versus answered is the same shape: the gap is the signal, and a single "questions" count hides
    it.
    """
    calib = require(CALIB_MODULE, issue="#139")
    emitted = calib.metrics_for_test()

    findings = emitted["findings"]
    assert set(findings.labels) == {"triage_category"}, (
        f"findings are emitted with labels {set(findings.labels)}; CT-CALIB-14 requires them by "
        "triage category, and a single total cannot say which kind"
    )

    assert {"questions_asked", "questions_answered"} <= set(emitted), (
        "questions are not emitted as asked-versus-answered; the gap between them is the signal"
    )
    assert "gate_outcome" in emitted
    assert emitted["class_shift"].is_distribution, (
        "the class shift is emitted as a scalar; CT-CALIB-14 asks for the distribution, and a "
        "mean shift hides whether two students moved a band or forty moved a little"
    )


@pytest.mark.writtenahead
def test_tc_calib_c14_a_noisy_rubric_alerts_once_on_the_aggregate():
    """`CT-CALIB-14`'s **alert semantics**, which the clause states as wording.

    *"A rubric surfacing more than a handful of ambiguities alerts as `the rubric needs a
    conversation`, not as twenty questions to answer."*

    The per-finding form buries the signal in the workload it describes: twenty alerts about twenty
    ambiguities is a queue, and the thing that needed saying — *this rubric has a problem* — is
    the one thing nobody reads out of it. So the assertion is on the alert's **shape**: one alert,
    fired on the aggregate, not N fired per finding.
    """
    calib = require(CALIB_MODULE, issue="#139")
    alerts = calib.alerts_for_test(finding_count=20)

    assert len(alerts) == 1, (
        f"twenty ambiguities produced {len(alerts)} alerts. CT-CALIB-14: the per-finding form "
        "buries the signal in the workload it describes."
    )
    assert alerts[0].scope == "aggregate"
    assert "conversation" in alerts[0].message.lower(), (
        f"the alert reads {alerts[0].message!r}; the clause states the wording — the rubric needs "
        "a conversation, not twenty questions to answer"
    )


# --- CT-CALIB-16 — the non-promise ----------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_calib_c16_a_genuinely_worse_revision_that_shifts_few_students_passes():
    """`CT-CALIB-16` — the **non-promise**, asserted with its inverted fixture.

    *"A passed gate is not evidence that a revision improved the rubric — only that it did not
    shift the class by more than the declared threshold and that an off-panel model could not
    construct a divergent case."*

    So the case constructs a revision that is **genuinely worse** yet shifts few students, and
    asserts it **passes**. That is the promised behaviour, and asserting it is what stops the gate
    being read as a quality check.

    **This assertion is inverted and it is easy to write backwards.** A test that asserted the
    worse revision is *rejected* would look more sensible, pass against a gate that had quietly
    become a quality check, and turn a documented non-promise into a superiority claim — which is
    the exact misreading §7.3 records as residual risk. The fixture's two properties are asserted
    explicitly first, so a reader can see that "worse" and "few students shifted" are both true of
    it and neither is the thing being tested.
    """
    calib = require(CALIB_MODULE, issue="#139")
    non_inferiority = require(CALIB_MODULE, "non_inferiority", issue="#139")

    revision = calib.worse_but_low_shift_revision()

    assert revision.is_genuinely_worse, "the fixture is not actually a worse rubric"
    assert revision.shifted_fraction < DECLARED_KNOBS["CALIB_NONINFERIORITY_THRESHOLD"], (
        "the fixture shifts more of the class than the threshold, so it cannot show that a worse "
        "revision passes"
    )

    result = non_inferiority(
        r0=revision.r0, r1=revision.r1, cohort_id=revision.cohort_id, threshold=0.10
    )

    assert result.outcome == "pass", (
        "a worse revision that shifts few students was rejected. CT-CALIB-16 is a non-promise: "
        "passing means only that the class did not shift beyond the threshold and that an "
        "off-panel model found no divergence. A gate that rejected this would be making a quality "
        "claim the design explicitly does not make (§7.3, residual risk)."
    )


@pytest.mark.writtenahead
def test_tc_calib_c16_consumers_present_the_gate_as_non_inferiority_never_superiority():
    """`CT-CALIB-16`'s **consumer sweep**, which is what a non-promise needs (§6.11).

    A non-promise is only safe if no consumer has quietly come to depend on the thing nobody
    promised (RISK-36). `M-CALIB` can hold its side perfectly while `M-CONSOLE` renders a passed
    gate as *"the revision improved the rubric"* — and the teacher believes the console, not the
    clause.

    Asserted over **rendered language**, because that is where the claim reaches a person. Both
    consumers the clause names are swept.
    """
    console = require(CONSOLE_MODULE, issue="#122")
    render = require(CONSOLE_MODULE, "render_gate_result", issue="#122")

    surface = render(outcome="pass").lower()

    # Scanned in **affirmative sentences only**. `CT-CALIB-16`'s own wording is a negation —
    # "a passed gate is *not* evidence that a revision improved the rubric" — so a raw
    # substring sweep forbids the console from stating the very thing the clause requires.
    # Review demonstrated a correct console failing on `improved` inside its own disclaimer.
    affirmative = affirmative_sentences(surface)
    found = sorted(
        term for term in SUPERIORITY_LANGUAGE
        if any(term in sentence.lower() for sentence in affirmative)
    )
    assert not found, (
        f"the console claims superiority in {found}. CT-CALIB-16 says a pass is "
        "non-inferiority and nothing more."
    )
    assert "non-inferiority" in surface.lower() or "did not shift" in surface.lower(), (
        f"the rendered surface does not say what the pass actually means: {surface[:120]!r}"
    )
    assert console is not None


@pytest.mark.writtenahead
def test_tc_calib_c16_m_stats_presents_the_gate_as_non_inferiority_too():
    """`CT-CALIB-16`'s **second consumer**, which the first draft's docstring claimed to sweep
    and did not.

    §6.11.17 names two: *"assert `M-CONSOLE` **and `M-STATS`** present it as non-inferiority,
    never superiority."* Design §2 lists `M-STATS` among this clause's consumers, and it is the
    one whose output is most likely to be read as a quality claim — a table of figures carries
    an authority a console message does not.
    """
    stats = require(STATS_MODULE, issue="#118")
    describe = require(STATS_MODULE, "describe_revision_gate", issue="#118")

    surface = describe(outcome="pass")

    found = sorted(
        term for term in SUPERIORITY_LANGUAGE
        if any(term in sentence.lower() for sentence in affirmative_sentences(surface))
    )
    assert not found, (
        f"M-STATS presents a passed gate using superiority language {found} (CT-CALIB-16)"
    )
    assert stats is not None
