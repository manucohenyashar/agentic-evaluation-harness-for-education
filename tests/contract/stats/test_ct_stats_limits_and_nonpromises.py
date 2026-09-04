"""`CT-STATS-16`, `-17`, `-19`, `-20`, `-21` — the error discipline, the cost, and the two
non-promises.

Test plan §6.11.16, `TC-STATS-C16`, `-C17`, `-C19`, `-C20`, `-C21`. §6.11.16's own summary of the
last two: *"`CT-STATS-20` and `-21` are non-promises and are the two most important sentences in
this suite."*

They are important because they are the only two clauses whose violation is committed by a
**consumer**. `-20` says a console that renders one headline number has violated the contract even
though every figure inside it is correct; `-21` says a two-band α of 1.00 is a construction
artifact, and a consumer showing it beside a four-band figure has made a claim the module never
made. So both cases are consumer sweeps, as §6.11 requires of a non-promise, rather than a single
assertion against `M-STATS`.
"""

from __future__ import annotations

import os
import time

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import (
    AGG_MODULE,
    CONSOLE_MODULE,
    ORCH_MODULE,
    PKG_MODULE,
    REVIEW_MODULE,
    STATS_MODULE,
    require,
)

pytestmark = pytest.mark.contract

#: `NFR-STATS-03`'s *"in seconds"*, as an env-gated knob rather than a hard-coded constant — the
#: seam `CLAUDE.md` names third. The production value is the default; a slower test box raises it
#: without a code change, which is what stops a bound calibrated on one machine becoming a phantom
#: bug on every other one.
ACCUMULATED_SECONDS = float(os.environ.get("HARNESS_STATS_ACCUMULATED_SECONDS", "5"))

#: *"Months of accumulated labels … not a single cohort, since the bound is about accumulation."*
ACCUMULATED_ADMINISTRATIONS = int(
    os.environ.get("HARNESS_STATS_ACCUMULATED_ADMINISTRATIONS", "12")
)
LABELS_PER_ADMINISTRATION = int(
    os.environ.get("HARNESS_STATS_LABELS_PER_ADMINISTRATION", "400")
)


# --- CT-STATS-16 — insufficient data is a value ------------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("member", sorted(vocab.PROTOCOL_MEMBERS), ids=sorted(vocab.PROTOCOL_MEMBERS))
def test_tc_stats_c16_no_entry_point_raises_because_there_is_too_little_data(member):
    """*"Sweep every entry point with an empty or tiny label set."* All seven, `promote` included.

    This is the weaker and universal half of the claim, which is why `promote` belongs here and
    not in `TC-STATS-C03`'s type sweep: whatever `promote` returns for an administration that
    collected nothing, `CT-STATS-05` decides — but *raising* is out of the question for every one
    of the seven.

    A single tiny label set rather than an empty one on the second pass, because "too little" and
    "none" fail differently: n = 1 is the case where a κ is computable and meaningless, and it is
    the one an implementation is most likely to let through to a `ZeroDivisionError` deep inside a
    statistic.
    """
    issue = vocab.MEMBER_ISSUE[member]
    require(STATS_MODULE, member, issue=issue)  # the member this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")

    for labels in ([], [broken.ADMISSIBLE_LABEL]):
        stats = build_stats(labels=labels)
        try:
            getattr(stats, member)(**vocab.EMPTY_DATA_CALL[member])
        except Exception as exc:  # noqa: BLE001 - any raise is the failure
            pytest.fail(
                f"{member}() raised {type(exc).__name__} for a label set of {len(labels)}. "
                "CT-STATS-16: insufficient data is a value, not an exception."
            )


@pytest.mark.writtenahead
def test_tc_stats_c16_a_genuine_programming_error_still_raises():
    """The other side of the clause, and the one that keeps the first side honest.

    *"This module raises only on programming errors"* — so a module that satisfies the sweep above
    by wrapping every entry point in `except Exception: return NoValidationData(...)` has not
    implemented the clause, it has disabled its own error reporting. Every real bug in the module
    then reports itself as an absence of evidence, which is the one answer nobody investigates.

    The probe is a malformed **argument**: `None` where a scope string belongs. §3.16's Error
    handling paragraph names no exception type, so the assertion is that *something* propagates
    and that it is not the absence value — pinning a type here would invent a contract.
    """
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    NoValidationData = require(STATS_MODULE, "NoValidationData", issue="#115")

    stats = build_stats(labels=[broken.ADMISSIBLE_LABEL] * 40)
    call = dict(vocab.EMPTY_DATA_CALL["agreement"], scope=None, criterion_id=object())

    try:
        result = stats.agreement(**call)
    except Exception:  # noqa: BLE001 - propagating is the required outcome
        return

    pytest.fail(
        f"a malformed argument returned {result!r} instead of raising. "
        + (
            "A blanket `except` that reports programming errors as absence of evidence is the "
            "failure this half of CT-STATS-16 exists to catch."
            if isinstance(result, NoValidationData)
            else "CT-STATS-16 raises on programming errors."
        )
    )


# --- CT-STATS-17 — the cost, at accumulated scale ------------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.integration
@pytest.mark.slow
def test_tc_stats_c17_statistics_over_accumulated_labels_compute_within_the_budget(tmp_data_dir):
    """*"Asserted against a synthetic multi-administration label store, not a single cohort, since
    the bound is about accumulation."*

    A single cohort is fast in every implementation, including the one that re-reads every label
    ever recorded on each call. Twelve administrations is what separates them, and twelve is a
    knob rather than a constant so a slower box can lower it without editing this file.

    Marked `slow` as well as `integration`: it writes ~4,800 labels through a real store, and
    §4.10 budgets the contract tier at 60 seconds. Chosen now rather than at unmark time, when the
    choice would fall to whoever is reading a timeout.
    """
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")

    for administration in range(ACCUMULATED_ADMINISTRATIONS):
        for i in range(LABELS_PER_ADMINISTRATION):
            record_label(
                data_dir=tmp_data_dir,
                label=broken.Label(label_id=f"a{administration}-{i}"),
                cohort_id=f"coh-{administration}",
            )

    stats = open_stats(data_dir=tmp_data_dir)
    started = time.perf_counter()
    figure = stats.agreement(**vocab.EMPTY_DATA_CALL["agreement"])
    elapsed = time.perf_counter() - started

    assert figure.n >= LABELS_PER_ADMINISTRATION, (
        "the figure was computed over less than one administration's labels, so the timing below "
        "measures the wrong thing"
    )
    assert elapsed < ACCUMULATED_SECONDS, (
        f"statistics over {ACCUMULATED_ADMINISTRATIONS} administrations took {elapsed:.1f}s, "
        f"budget {ACCUMULATED_SECONDS}s (NFR-STATS-03: months of accumulated labels compute in "
        "seconds)"
    )


@pytest.mark.writtenahead
@pytest.mark.integration
def test_tc_stats_c17_the_analytical_export_is_read_only_and_does_not_touch_a_live_run(
    tmp_data_dir,
):
    """*"Verified by running it during an active scoring run and asserting no lock contention, no
    writes, and no effect on run wall clock."*

    The three failures are different and only the first is loud. A write from the export corrupts;
    a lock held by the export **stalls** the run, which looks like a slow model rather than a
    reporting tool; and a run whose wall clock moves has been affected by something nobody would
    think to look at. So all three are asserted, and the differential — a run's duration with and
    without the export alongside it — is what catches the third.

    `NFR-STATS-03` is explicit that the export is optional and *"never touches the scoring
    pipeline"*, which is precisely the promise an analytical tool acquires exceptions to.
    """
    from tests.support.guards import recording_write_audit

    analytical_export = require(STATS_MODULE, "analytical_export", issue="#118")
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    # The run is `M-ORCH`'s, not this module's, and it lands well before: #118 -> #115 ->
    # #110 -> #108 -> #93 -> M-ORCH, so #118 is the last of the two and the one this test is
    # registered under. Required after the export so `require()` reports #118 first.
    run_scoring = require(ORCH_MODULE, "run_pipeline_for_test", issue="#61")

    baseline_started = time.perf_counter()
    run_scoring(data_dir=tmp_data_dir, cohort_id="coh-baseline")
    baseline = time.perf_counter() - baseline_started

    stats = open_stats(data_dir=tmp_data_dir)
    with recording_write_audit() as writes:
        concurrent_started = time.perf_counter()
        run = run_scoring(data_dir=tmp_data_dir, cohort_id="coh-live", alongside=lambda: analytical_export(stats))
        concurrent = time.perf_counter() - concurrent_started

    export_writes = [w for w in writes if w.initiated_by == "M-STATS" and "export" in str(w.target)]
    assert export_writes == [] or all(
        "export" in str(w.target) and "cohorts" not in str(w.target) for w in export_writes
    ), f"the export wrote into the scoring pipeline's data: {[str(w.target) for w in export_writes]}"

    assert not run.lock_waits, (
        f"the run waited on {run.lock_waits} locks while the export was running. A read-only "
        "export that stalls a run looks like a slow model, which is the diagnosis nobody revisits."
    )
    assert concurrent < baseline * 2, (
        f"the run took {concurrent:.1f}s alongside the export against {baseline:.1f}s alone "
        "(NFR-STATS-03: the export never touches the scoring pipeline)"
    )


# --- CT-STATS-19 — the counters and the two alerts ------------------------------------------------


@pytest.mark.writtenahead
def test_tc_stats_c19_emits_the_declared_counters():
    """An artifact assertion on **names**, since the names are what an operator's dashboard binds.

    *"Label counts by type **and origin**"* is two counters, not one: type is `blind` versus
    `operational` and origin is `CT-ORCH-15`'s `random_arm` versus the rest. Collapsing them makes
    the random arm invisible, and the random arm is the only unconditioned sample there is.
    """
    require(STATS_MODULE, "observability_counters", issue="#118")  # the member this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(labels=[broken.ADMISSIBLE_LABEL] * 40)

    counters = stats.observability_counters()
    missing = [name for name in vocab.OBSERVABILITY_COUNTERS if name not in counters]

    assert missing == [], f"§3.16's Observability paragraph declares {missing}, and they are absent"


@pytest.mark.writtenahead
@pytest.mark.parametrize(
    "alert, issue",
    [
        (vocab.CONTRACT_ALERTS[0], "#118"),
        (vocab.CONTRACT_ALERTS[1], "#117"),
    ],
    ids=["blind_sample_skipped", "surface_proxy_flag"],
)
def test_tc_stats_c19_each_contract_alert_exists_and_fires(alert, issue):
    """*"Each asserted to exist **and fire**."* Both halves, because a defined alert nothing can
    reach is the same as no alert.

    The two rows have different owners — the blind-skip alert is the validation record's (#118),
    the surface-proxy flag is the proxy regression's (#117) — so they are keyed separately rather
    than both on the later story.

    The second alert is the one §6.11.16 calls *"the only detector for a criterion with excellent
    κ and no validity"*: a criterion whose scores track response length or OCR quality is
    measuring something other than what it claims, **whatever its agreement statistic says**. No
    other view in the system can see that, because every other view is downstream of the score.
    """
    require(STATS_MODULE, "alerts", issue=issue)  # the alert surface this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")

    provoking = {
        vocab.CONTRACT_ALERTS[0]: {
            "administrations": [
                {"cohort_id": "coh-1", "blind_sample": False},
                {"cohort_id": "coh-2", "blind_sample": False},
            ]
        },
        vocab.CONTRACT_ALERTS[1]: {
            "surface_correlations": {"C-01": {"response_length_tokens": 0.81}}
        },
    }[alert]

    stats = build_stats(labels=[broken.ADMISSIBLE_LABEL] * 40, **provoking)
    fired = {a.name if hasattr(a, "name") else a for a in stats.alerts()}

    assert alert in fired, (
        f"{alert} did not fire on a fixture constructed to provoke it; the alerts that fired were "
        f"{sorted(fired)} (CT-STATS-19)"
    )


# --- CT-STATS-20 — no figure here is a system-wide accuracy claim ------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize(
    "consumer, module, entry, issue",
    [
        ("M-CONSOLE", CONSOLE_MODULE, "render_agreement_block", "#123"),
        ("M-PKG", PKG_MODULE, "export_package", "#31"),
    ],
    ids=["m_console", "m_pkg_export"],
)
def test_tc_stats_c20_no_consumer_renders_or_exports_a_single_headline_figure(
    consumer, module, entry, issue
):
    """The **consumer sweep** a non-promise requires, one row per consumer.

    *"A consumer that renders a single headline number has violated this contract even if every
    figure in it is correct."* That is an unusually precise violation condition and it is asserted
    directly: the detector reads the *framing* rather than the numbers, because by hypothesis the
    numbers are right.

    Both consumers, because the export is the worse half. A headline on a screen is wrong in one
    school; a headline in an exported package is wrong in every school it reaches, and `CT-PKG-17`
    says population scopes are not even portable between them.
    """
    render = require(module, entry, issue=issue)
    rendered = render(package_version="pkg-v1", population="y9-2026-spring")
    text = rendered if isinstance(rendered, str) else str(getattr(rendered, "text", rendered))

    problems = vocab.unscoped_headline_figures(text)
    assert problems == [], (
        f"{consumer} renders {problems}. CT-STATS-20: an agreement figure is a claim about one "
        "criterion, one population, one backend, one panel build, and nothing more."
    )


@pytest.mark.writtenahead
def test_tc_stats_c20_the_module_declares_no_pass_fail_threshold_over_a_quality_figure():
    """*"Assert no threshold is declared here (`NFR-SYS-08`)"* — read as `NFR-SYS-08` reads it.

    The literal sentence cannot be asserted: §3.16's own Configuration block declares
    `STATS_MIN_N_FOR_HEADLINE`, and HLD §11.5's S12 mock depends on it — below that n the figure
    renders with an explicit *"too few to draw conclusions from"* qualifier. A case asserting that
    no threshold constant exists goes red against a **compliant** module.

    `NFR-SYS-08` scopes it: *"No single threshold is declared here, because … a system-wide
    accuracy claim would be the §2.1 error."* The forbidden thing is a **verdict** — a figure that
    also tells you whether it is good enough — not a display-qualifier boundary. So the assertion
    is that no figure carries a pass/fail field and no such name is on the surface.

    The collision itself is asserted in `test_ct_stats_vocabulary.py`, so if the clause is
    reworded the finding goes red rather than being quietly outlived by this test.
    """
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(labels=[broken.ADMISSIBLE_LABEL] * 40)

    figure = stats.agreement(**vocab.EMPTY_DATA_CALL["agreement"])
    on_figure = [name for name in vocab.FORBIDDEN_VERDICT_FIELDS if hasattr(figure, name)]
    assert on_figure == [], (
        f"the agreement figure carries {on_figure}. A figure that also says whether it passes is a "
        "pass/fail claim about the system wearing a scoped statistic (CT-STATS-20, NFR-SYS-08)."
    )

    exposed = [name for name in dir(stats) if not name.startswith("_")]
    on_surface = [
        name
        for name in exposed
        if any(forbidden in name.lower() for forbidden in vocab.FORBIDDEN_VERDICT_FIELDS)
    ]
    assert on_surface == [], f"the module offers {on_surface}, which is a threshold by another name"

    assert require(STATS_MODULE, vocab.MIN_N_FOR_HEADLINE_KNOB, issue="#115") == (
        vocab.MIN_N_FOR_HEADLINE_DEFAULT
    ), (
        "the display-qualifier boundary is missing or has moved. It is not a verdict threshold and "
        "this case does not forbid it — HLD §11.5's S12 mock renders the qualifier at n = 15."
    )


# --- CT-STATS-21 — α and κ are degenerate on two-band criteria ----------------------------------------


@pytest.mark.writtenahead
def test_tc_stats_c21_a_two_band_criterion_returns_its_number_and_discloses_the_degeneracy():
    """*"The case asserts the degeneracy is **detected and disclosed**, not that a value is
    correct."*

    Both halves, and the first is easy to get wrong in the direction of caution: the module
    **returns the number**. Refusing, or returning `NoValidationData`, would be a different
    contract — `CT-STATS-21` is a non-promise about interpretation, not a prohibition on
    measurement, and §7.4 carries the resolution as an open design question.

    The fixture is the degenerate case §4.6 item 1 calls the **default** band shape: two bands,
    unanimous agreement, α = 1 as a construction artifact rather than a finding.
    """
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    binary = [
        broken.Label(label_id=f"bin-{i}", band=1, teacher_band=1)
        for i in range(vocab.DEGENERATE_BAND_COUNT * 20)
    ]

    stats = build_stats(labels=binary, band_counts={"C-01": vocab.DEGENERATE_BAND_COUNT})
    figure = stats.agreement(**vocab.EMPTY_DATA_CALL["agreement"])

    assert figure.ordinal_alpha is not None or figure.kappa is not None, (
        "the module returned no number for a two-band criterion. CT-STATS-21 promises the number: "
        "the non-promise is about what it means, and §7.4 keeps the resolution open."
    )
    assert figure.degenerate_band_shape is True, (
        "a two-band criterion's figure does not disclose its degeneracy. RISK-30: α = 1 here is a "
        "construction artifact, and undisclosed it is the most confident number on the screen."
    )


@pytest.mark.writtenahead
@pytest.mark.parametrize(
    "consumer, module, entry, issue",
    [
        ("M-CONSOLE", CONSOLE_MODULE, "render_agreement_block", "#123"),
        ("M-AGG", AGG_MODULE, "describe_agreement", "#91"),
    ],
    ids=["m_console", "m_agg"],
)
def test_tc_stats_c21_no_consumer_presents_binary_agreement_as_equivalent_to_multi_band(
    consumer, module, entry, issue
):
    """The consumer sweep — *"asserted over `M-CONSOLE`'s rendering and `M-AGG`'s use"*.

    The clause binds the consumers, so a single assertion against `M-STATS` would leave it
    untested. Both are swept and each is keyed on its own story: the console's rendering of scoped
    agreement is #123's invariant 5, `M-AGG`'s ordinal α is #91's.

    Pairs with `TC-AGG-C17`, which asserts the same limitation from the producing side. Two
    consumers and a producer all have to hold it, because the number itself is perfectly valid and
    only its comparison is not.
    """
    render = require(module, entry, issue=issue)
    rendered = render(
        figure={"ordinal_alpha": 1.0, "band_count": 2, "degenerate_band_shape": True},
        population="y9-2026-spring",
    )
    text = rendered if isinstance(rendered, str) else str(getattr(rendered, "text", rendered))

    problems = vocab.presents_binary_agreement_as_equivalent(text)
    assert problems == [], f"{consumer} presents the degenerate figure as equivalent: {problems}"

    assert any(term in text.lower() for term in vocab.DEGENERACY_DISCLOSURE_TERMS), (
        f"{consumer} renders a two-band α of 1.00 with no disclosure at all. Silence is the "
        "failure mode RISK-30 names: it is the most confident number on the screen."
    )
