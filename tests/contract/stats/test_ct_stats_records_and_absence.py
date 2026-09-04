"""`CT-STATS-05`, `-06`, `-09`, `-12` — the validation record, and the four ways it lies quietly.

Test plan §6.11.16, `TC-STATS-C05`, `-C06`, `-C09`, `-C12`. What these four clauses have in common
is that every violation looks like a working system:

* an administration that collected no blind labels, showing last term's number (RISK-08);
* operational volume counted into validation depth, so a package looks better the more it is used
  and never better measured (RISK-07);
* a criterion nobody has reviewed reported as a criterion nobody disagrees with;
* an advisory drift heuristic that has quietly become a gate, and stops a school's grading.

None of the four produces an error, a warning, or a number anybody would question. That is why
each is a contract clause rather than a requirement, and why the assertions below are differentials
and consumer sweeps rather than checks that a call returned.
"""

from __future__ import annotations

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import (
    AGG_MODULE,
    CONSOLE_MODULE,
    PKG_MODULE,
    REVIEW_MODULE,
    STATS_MODULE,
    require,
)

pytestmark = pytest.mark.contract


def _operational(count: int) -> list[broken.Label]:
    """Operational labels that **disagree** with the panel.

    The bands matter and an earlier draft left them at the `Label` defaults, where system and
    teacher agree on band 3. Promoting sixty such labels into an agreeing population leaves κ
    identical whether or not the filter admits them — so `TC-STATS-C06`'s κ-invariance assertion
    passed for a module with no filter at all, which is the violation it exists to catch. Review
    found it; these disagree, so contamination moves the number.
    """
    return [
        broken.Label(
            label_id=f"op-{i}",
            label_type="operational",
            origin="accept",
            band=1,
            teacher_band=4,
        )
        for i in range(count)
    ]


def _blind(count: int) -> list[broken.Label]:
    """An admissible population with a spread of bands and some disagreement — see
    `broken_stats_fixtures.agreeing_population` for why unanimity is the wrong fixture here."""
    return broken.agreeing_population(count)


# --- CT-STATS-05 — the administration that collected nothing ---------------------------------


@pytest.mark.writtenahead
@pytest.mark.integration
def test_tc_stats_c05_an_administration_with_no_blind_labels_does_not_advance_the_figures(
    tmp_data_dir,
):
    """*"A **first-class value**, and — the decisive half — it **does not advance** the package's
    agreement figures."*

    A **differential**, which is the only form that catches the failure: read the package's
    agreement figure, promote an administration carrying operational labels and no blind ones,
    read it again. The two must be identical, including `n`. Asserting only that the message came
    back passes for a module that reports the message *and* advances the record, which is the
    silent carry-forward RISK-08 names.

    Rung 2 — the figure has to come back from a stored validation record, not from a value the
    same call just produced. Marked `integration` for the real store.
    """
    require(STATS_MODULE, "promote", issue="#118")  # the member this story delivers
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")

    stats = open_stats(data_dir=tmp_data_dir)
    for label in _blind(40):
        record_label(data_dir=tmp_data_dir, label=label)
    stats.promote(cohort_id="coh-spring")

    before = stats.agreement(**vocab.EMPTY_DATA_CALL["agreement"])
    assert before.n == 40, "the first administration did not land, so the differential is vacuous"

    for label in _operational(25):
        record_label(data_dir=tmp_data_dir, label=label)
    update = stats.promote(cohort_id="coh-autumn")

    after = stats.agreement(**vocab.EMPTY_DATA_CALL["agreement"])

    assert vocab.NO_NEW_VALIDATION_EVIDENCE in str(update.message).lower(), (
        f"the administration reported {update.message!r} rather than "
        f"{vocab.NO_NEW_VALIDATION_EVIDENCE!r} (FR-STATS-11)"
    )
    assert (after.n, after.kappa) == (before.n, before.kappa), (
        f"the agreement figure moved from n={before.n}/κ={before.kappa} to n={after.n}/"
        f"κ={after.kappa} on an administration that collected no blind labels. CT-STATS-05: it "
        "does not advance the package's agreement figures (RISK-08)."
    )


@pytest.mark.writtenahead
def test_tc_stats_c05_the_console_renders_the_message_not_the_previous_administrations_number():
    """The consumer obligation at **rung 3**, `M-CONSOLE`'s half — keyed on #125.

    `FR-CONSOLE-24` states it from the console's side: the agreement block renders the message and
    *"never a prior administration's figure in that position"*. The fixture supplies a prior
    figure precisely so the test can fail on it appearing: without one in the fixture, any
    rendering passes.
    """
    render_agreement_block = require(CONSOLE_MODULE, "render_agreement_block", issue="#125")

    rendered = render_agreement_block(
        figure=None,
        no_new_evidence=True,
        previous_administration={"kappa": 0.71, "n": 142},
        population="y9-2026-spring",
    )
    text = rendered if isinstance(rendered, str) else rendered.text

    assert vocab.NO_NEW_VALIDATION_EVIDENCE in text.lower(), (
        f"the block does not carry the message: {text!r}"
    )
    assert "0.71" not in text and "142" not in text, (
        f"the previous administration's figure is in the block: {text!r}. FR-CONSOLE-24 forbids it "
        "in that position — a teacher reads it as this administration's evidence."
    )


@pytest.mark.writtenahead
def test_tc_stats_c05_the_package_record_reports_the_message_rather_than_a_stale_figure():
    """The same obligation on `M-PKG`'s side — keyed on **#29**, the validation-record story.

    `CT-PKG-07` says `validation_for(...)` returns a record or a `NoValidationData` *"never a
    figure from an adjacent key"*. This is that clause read from `M-STATS`' side: the adjacent key
    here is the previous administration, and the answer for this one is the message.
    """
    validation_for = require(PKG_MODULE, "validation_for", issue="#29")
    record_validation = require(PKG_MODULE, "record_validation", issue="#29")

    # Arranged. An earlier draft asked the catalog about a package nothing had ever written a
    # record for, and demanded the "no new validation evidence" message — which a correct M-PKG
    # answers with `no_data_for_population`, because that is the truth about a package it has
    # never seen. Review caught it. Seeding the **previous** administration is what makes the
    # question meaningful: the adjacent key now holds a figure, and CT-PKG-07 says the answer for
    # this key is still not that figure.
    record_validation(
        package_version="pkg-v1",
        criterion="C-01",
        population_scope="y9-2026-spring",
        backend_profile="edge-local-q4",
        panel_build_ref="9f2a1c",
        scoring_model="atomic",
        administration="coh-spring",
        figure={"kappa": 0.71, "n": 142},
    )

    record = validation_for(
        package_version="pkg-v1",
        criterion="C-01",
        population_scope="y9-2026-spring",
        backend_profile="edge-local-q4",
        panel_build_ref="9f2a1c",
        scoring_model="atomic",
        administration="coh-autumn",
    )

    assert vocab.NO_NEW_VALIDATION_EVIDENCE in str(
        getattr(record, "message", record)
    ).lower(), (
        "the catalog answered with a figure for an administration that collected no blind labels "
        "(CT-STATS-05, CT-PKG-07)"
    )


# --- CT-STATS-06 — three counters, and the field closed to operational labels ------------------


@pytest.mark.writtenahead
@pytest.mark.integration
def test_tc_stats_c06_promote_increments_the_three_counters_separately(tmp_data_dir):
    """Exact counter arithmetic, three assertions rather than one.

    *"Merging any two would let operational volume inflate apparent validation depth"* — and the
    merge is attractive: `blind_count + operational_count` is "how much evidence we have", it goes
    up faster, and it is wrong. Seven blind and five operational labels give three distinct
    expected values, so no two counters can be reading the same total and pass.
    """
    require(STATS_MODULE, "promote", issue="#118")  # the member this story delivers
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")

    for label in _blind(7) + _operational(5):
        record_label(data_dir=tmp_data_dir, label=label)

    stats = open_stats(data_dir=tmp_data_dir)
    update = stats.promote(cohort_id="coh-spring")

    expected = {"cohorts_used": 1, "blind_count": 7, "operational_count": 5}
    actual = {counter: getattr(update, counter) for counter in vocab.PROMOTE_COUNTERS}

    assert actual == expected, (
        f"promote reported {actual}, expected {expected}. Each counter answers a different "
        "question and merging any two lets operational volume read as validation depth "
        "(FR-STATS-10, R18/R20)."
    )


@pytest.mark.writtenahead
@pytest.mark.integration
def test_tc_stats_c06_an_operational_only_administration_leaves_kappa_unchanged(tmp_data_dir):
    """The categorical prohibition, as **κ-invariance**: *"promoting an administration of purely
    operational labels and asserting κ is unchanged."*

    Invariance rather than a comparison against a computed value, because the failure is not a
    wrong κ — it is a κ that moved for a reason κ is not allowed to move for. An operational label
    is a teacher who saw the system's answer; letting one in makes the system agree with itself
    and the number goes **up**, which is HLD §0.8's whole observation about this module.
    """
    require(STATS_MODULE, "promote", issue="#118")  # the member this story delivers
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")

    for label in _blind(40):
        record_label(data_dir=tmp_data_dir, label=label)
    stats = open_stats(data_dir=tmp_data_dir)
    stats.promote(cohort_id="coh-spring")
    first = stats.agreement(**vocab.EMPTY_DATA_CALL["agreement"])
    before, n_before = first.kappa, first.n

    for label in _operational(60):
        record_label(data_dir=tmp_data_dir, label=label)
    stats.promote(cohort_id="coh-autumn")
    second = stats.agreement(**vocab.EMPTY_DATA_CALL["agreement"])
    after, n_after = second.kappa, second.n

    assert after == before, (
        f"κ moved from {before} to {after} after promoting sixty operational labels and no blind "
        f"ones. CT-STATS-06: an operational count never contributes to "
        f"{vocab.AGREEMENT_FIELD_CLOSED_TO_OPERATIONAL} (R18/R20, RISK-07)."
    )
    assert n_after == n_before, (
        f"the sample size moved from {n_before} to {n_after}, so the operational labels are in "
        "the population even if κ happened not to move — n is the population, and this is the "
        "assertion that does not depend on the fixture's bands"
    )


@pytest.mark.writtenahead
def test_tc_stats_c06_label_weighting_applies_to_operational_signals_and_not_to_the_figure():
    """`FR-STATS-14` — the weighting exists, and it *"never blurs into a validity claim"*.

    Both halves, because either alone is satisfiable by the wrong module. A module with no
    weighting at all passes "the figure is unweighted"; a module that weights the agreement figure
    passes "the weighting exists". So the assertion is the pair: the operational signal responds
    to the declared ordering, and κ does not respond to it at all.
    """
    require(STATS_MODULE, "operational_signal", issue="#118")  # the member this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    labels = _blind(20) + _operational(20)

    unweighted = build_stats(labels=labels, operational_weights=None)  # noqa: E501 - see below
    weighted = build_stats(
        labels=labels, operational_weights={"acceptance": 0.1, "override": 1.0, "blind": 1.0}
    )

    assert weighted.operational_signal(cohort_id="coh-1") != unweighted.operational_signal(
        cohort_id="coh-1"
    ), "the declared weighting changed nothing, so FR-STATS-14's weighting is not implemented"

    assert (
        weighted.agreement(**vocab.EMPTY_DATA_CALL["agreement"]).kappa
        == unweighted.agreement(**vocab.EMPTY_DATA_CALL["agreement"]).kappa
    ), (
        "the operational weighting moved κ. FR-STATS-14 weights operational signals only, and a "
        "weighted validity figure is a validity claim built out of labels that cannot support one."
    )


# --- CT-STATS-09 — a criterion nobody has reviewed --------------------------------------------


@pytest.mark.writtenahead
def test_tc_stats_c09_a_criterion_with_no_history_returns_no_data_rather_than_a_zero_rate():
    """The clause in its own words: *"a criterion nobody has reviewed is not a criterion nobody
    disagrees with"*.

    Zero and absence are the same pixel on a screen and the opposite finding underneath. A zero
    override rate on a reviewed criterion is evidence the criterion is working; a zero on an
    unreviewed one is evidence of nothing at all, and it ranks the criterion **safest** in exactly
    the queue that decides what gets looked at next.

    **This clause has no requirement behind it.** Every other `CT-STATS` clause cites an
    `FR-STATS-*`; `-09` cites none, and no requirement in §3.16 mentions override history — so no
    story implements it. Keyed on #118 as the story that owns label-derived record surfaces, and
    asserted as a finding in `test_ct_stats_vocabulary.py` so the gap is reported rather than
    absorbed by this test quietly passing one day.
    """
    require(STATS_MODULE, "criterion_override_history", issue="#118")  # the member this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    NoValidationData = require(STATS_MODULE, "NoValidationData", issue="#115")

    stats = build_stats(
        labels=[broken.Label(label_id="rev-1", criterion_id="C-02", origin="override")]
    )

    reviewed = stats.criterion_override_history(criterion_id="C-02")
    never_reviewed = stats.criterion_override_history(criterion_id="C-77")

    assert not isinstance(reviewed, NoValidationData), (
        "the reviewed criterion also came back as no-data, so the distinction below is vacuous"
    )
    assert isinstance(never_reviewed, NoValidationData), (
        f"a criterion with no review history returned {never_reviewed!r}. If that is a zero "
        "override rate, the criterion ranks as the safest one in the queue on the strength of "
        "nobody having looked at it (CT-STATS-09)."
    )


@pytest.mark.writtenahead
@pytest.mark.parametrize(
    "consumer, module, entry, issue",
    [
        ("M-AGG", AGG_MODULE, "rank_criteria_for_escalation", "#93"),
        ("M-REVIEW", REVIEW_MODULE, "rank_queue_items", "#108"),
    ],
    ids=["m_agg", "m_review"],
)
def test_tc_stats_c09_both_consumers_rank_no_data_differently_from_a_genuine_zero(
    consumer, module, entry, issue
):
    """The consumer differential at **rung 3**, one row per consumer, each on its own story.

    The clause exposes the history *"as an escalation and ranking input to `M-AGG` and
    `M-REVIEW`"*, so the distinction only matters if the consumers act on it. A module that
    returns a distinct no-data value to two consumers that both coerce it to zero has satisfied
    the type and lost the finding.

    A differential over the **input**, not over list positions: rank the same three criteria
    twice, changing only whether the third has no history or a genuine zero, and assert the two
    orders differ. An earlier draft compared the positions of two items in one ranking — which
    `enumerate` makes distinct by construction, so it could not fail. Review caught it.

    The third criterion, measured at a high override rate, is the non-vacuity anchor: without it
    a consumer that ignores `override_rate` entirely would produce the same order both times for
    the right reason, and this could not tell that from the failure.
    """
    rank = require(module, entry, issue=issue)

    def order(third: dict) -> list[str]:
        ranked = rank(
            criteria={
                "C-contested": {"override_rate": 0.6, "reviewed": True},
                "C-measured-zero": {"override_rate": 0.0, "reviewed": True},
                "C-under-test": third,
            }
        )
        return [item.criterion_id for item in ranked]

    with_a_genuine_zero = order({"override_rate": 0.0, "reviewed": True})
    with_no_history = order({"override_rate": None, "reviewed": False})

    assert with_a_genuine_zero.index("C-contested") < with_a_genuine_zero.index(
        "C-measured-zero"
    ), (
        f"{consumer} does not rank a contested criterion above an uncontested one, so its ranking "
        "does not respond to override rate at all and the differential below means nothing"
    )
    assert with_no_history != with_a_genuine_zero, (
        f"{consumer} ranks a criterion nobody has reviewed exactly where it ranks one measured at "
        "zero disagreement, so the no-data value is being read as a zero — and the criterion "
        "nobody has looked at is now the one the queue says is safest (CT-STATS-09)"
    )


# --- CT-STATS-12 — the advisory drift check ----------------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("available", [19, 31])
def test_tc_stats_c12_the_check_stays_inside_the_declared_sample_range(available):
    """`FR-STATS-09`'s *"20–30 submission sample"*, asserted at both boundaries — as a **range**.

    Both ends, because the two failures differ, and they differ in kind:

    * **31 available.** The check samples into the range and says how many it used. Comparing all
      thirty-one is not a refusal-worthy offence, it is the check quietly costing what the design
      chose to avoid — so the assertion is on the size it reports having used.
    * **19 available.** There is no valid sample, and `CT-STATS-16` already fixes what a module
      does with insufficient data: it returns the value, it does not raise and it does not
      substitute a figure. A drift verdict computed on nineteen submissions is exactly the
      substitute.

    An earlier draft demanded a **raise** at both ends. Neither `FR-STATS-09` nor the plan's
    "range assertion" oracle says that, and a compliant module that samples 25 from what it is
    given would have failed it — review caught it.
    """
    drift_check = require(STATS_MODULE, "drift_check", issue="#117")
    NoValidationData = require(STATS_MODULE, "NoValidationData", issue="#115")
    low, high = vocab.DRIFT_SAMPLE_RANGE

    assert not low <= available <= high, "the fixture size is inside the declared range"

    report = drift_check(
        package_version="pkg-v1", sample=tuple(f"sub-{i}" for i in range(available))
    )

    if available < low:
        assert isinstance(report, NoValidationData), (
            f"the drift check returned {report!r} from {available} submissions, below "
            f"FR-STATS-09's floor of {low}. A verdict computed on too small a sample is the "
            "substitute figure CT-STATS-16 forbids."
        )
    else:
        assert low <= report.sample_size <= high, (
            f"the check used {report.sample_size} submissions from {available} available; "
            f"FR-STATS-09 fixes the sample at {low}–{high}"
        )


@pytest.mark.writtenahead
def test_tc_stats_c12_the_drift_check_covers_judged_criteria_only():
    """*"Runs over **judged** criteria only."*

    A deterministic criterion has no band distribution to compare — `CT-DET-02` says a
    deterministic `criterion_score` carries `agreement = NULL` and produces no verdicts — so
    including one either compares against nothing or invents a distribution. The assertion names
    the criteria the check actually covered rather than trusting a flag.
    """
    require(STATS_MODULE, "drift_check", issue="#117")  # the member this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(
        labels=_blind(30),
        evaluation_modes={"C-01": "judged", "C-mcq": "deterministic"},
    )

    report = stats.drift_check(
        package_version="pkg-v1", sample=tuple(f"sub-{i}" for i in range(25))
    )

    assert "C-01" in report.criteria_covered, (
        "the judged criterion was not covered, so the exclusion below is vacuous"
    )
    assert "C-mcq" not in report.criteria_covered, (
        "a deterministic criterion entered the drift check. CT-DET-02: it carries no verdicts and "
        "a NULL agreement, so there is no distribution to compare (FR-STATS-09)."
    )


@pytest.mark.writtenahead
def test_tc_stats_c12_a_maximally_adverse_drift_result_does_not_block_a_run():
    """*"Advisory, never a gate"* at **rung 3** — driven with the worst result the check can give.

    Keyed on **#126**, S6 Preflight: `FR-CONSOLE-28` is where "start run" is withheld or permitted,
    so the console's preflight is the consumer that could turn this into a gate, and it is the one
    place the assertion is meaningful. Driving a merely-elevated drift figure would pass for a
    gate with a threshold above it; the maximum is the only value that cannot.

    The risk is concrete: an advisory statistical heuristic that has become a gate stops a school's
    grading, on a comparison of 25 submissions against a baseline (HLD `R11`).
    """
    render_preflight = require(CONSOLE_MODULE, "render_preflight", issue="#126")

    preflight = render_preflight(
        cohort_id="coh-spring",
        drift=({"advisory": True, "severity": 1.0, "criteria_drifted": ["C-01", "C-02"]}),
    )

    assert preflight.start_run_available, (
        "the console withheld 'start run' on a drift result. CT-STATS-12: the drift check is "
        "advisory, never a gate — a consumer must not block a run on it (R11)."
    )
    assert preflight.drift_shown, (
        "the drift result was not shown at all, so the run proceeding says nothing: advisory means "
        "reported and not binding, not suppressed"
    )
