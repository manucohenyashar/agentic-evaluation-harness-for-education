"""`TC-STATS-19` — planted narrative defects, detected at the stated n.

Test plan §5.16 (`TC-STATS-19`), issue #120 (TS-43). Traces to `FR-STATS-12`
and `NFR-SYNTH-01`. The plan's row: *"A sample of narratives with planted
hallucinated claims and planted invalid citations. Citation-validity rate
and hallucinated-claim rate detect the planted defects at the sample size
used, and are reported **separately** from criterion-score agreement."*
Planted-defect detection with stated n, P1.

Two defect classes, planted into one synthesis run's narratives:

- **a planted hallucinated claim** — an L1 narrative citing a criterion from
  a *different* question than its own: the #98 anchoring rule counts it
  hallucinating (the citation reaches outside the evidence this student's
  own work fed the narrative), and `hallucinated_claim_rate` names it;
- **a planted invalid citation** — an L1 narrative citing *nothing*: a claim
  anchored to nothing is not citation-valid either, and it lowers
  `citation_validity_rate` without raising the hallucinated rate — the gap
  between the two rates is the defect class neither rate alone carries.

The stated n is the sample size the declared sample rate draws: one
five-question submission synthesizes 5 L1 + 1 L2 narratives, the knob
`HARNESS_SYNTH_SAMPLE_RATE` is set to 1.0 so the sample is the whole run
(6), and the exact fractions are 4/6 citation-valid (three clean L1 rows and
the L2 row, whose empty citation list is valid at the package level) and
1/6 hallucinated. Detection at the sample size used means the planted
fractions are the reported ones exactly — a detector that measured
"validity" over only the citing narratives would read 4/5, and one that
counted an uncited L1 as valid would read 5/6; each is a different claim
about the same sample.

The **separation** half of the row — the narrative report's own type, never a
field of the agreement figure, no combining function — is `CT-STATS-C14`'s
(`test_ct_stats_figures_and_keying.py`), cross-referenced not repeated; the
second test here re-asserts the leak prohibition *with the channel declared*,
the state C14's own run does not exercise: the planted rates travel the
``narrative_metrics=`` channel to `narrative_quality` verbatim and appear
nowhere on the agreement figure.

Isolation: rung 2 for the measurement half — real store, the capture
provider at the model boundary (`TC-SYNTH-08`'s world, whose fixture
`synth_vocabulary` owns); rung 0 for the channel half (`build_stats`). No
network is reachable (`network_guard` is autouse and each case asserts it).
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import STATS_MODULE, SYNTH_MODULE, require
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    COHORT_ID,
    FIVE_QUESTION_CRITERIA,
    SYNTH_ISSUE,
    WORKER,
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = pytest.mark.integration

#: The run's shape — one submission, five questions of two criteria each, the
#: `TC-SYNTH-01` fixture (`seed_run` + `seed_scored_submission`).
SUBMISSION = "STATS-19-001"
QUESTIONS = tuple(f"Q{q}" for q in range(1, 6))
L2_TEXT = "Overall: the submission works through each question in turn."

#: The stated n: one five-question submission is 5 L1 narratives + 1 L2, and
#: the declared sample rate for this run draws all six.
STATED_N = 6

#: The planted defects, one each: Q4's reply cites another question's
#: criterion (the hallucinated claim), Q5's reply cites nothing (the invalid
#: citation — a claim anchored to nothing). The other four replies are clean:
#: three L1 rows citing their own question's criteria, and the L2 row whose
#: empty citations are valid at the package level.
PLANTED_HALLUCINATION = ("Q3C1",)
CLEAN_CITATIONS = {
    "Q1": ("Q1C1", "Q1C2"),
    "Q2": ("Q2C1", "Q2C2"),
    "Q3": ("Q3C1", "Q3C2"),
}

#: The exact fractions the planted sample must produce — detection at the
#: stated n is the exact-fraction assertion, not a "rate below 1" shrug.
EXPECTED_VALIDITY = 4 / STATED_N
EXPECTED_HALLUCINATED = 1 / STATED_N


def _measured_report(store, monkeypatch):
    """One synthesis over the planted feed, with the declared sample rate at
    1.0 so the sample is the whole run (stated n = 6)."""
    monkeypatch.setenv("HARNESS_SYNTH_SAMPLE_RATE", "1.0")
    _, run_id, _ = seed_run(store, submissions=(SUBMISSION,),
                            criteria=FIVE_QUESTION_CRITERIA)
    seed_scored_submission(store, run_id, SUBMISSION, complete_questions=set(QUESTIONS))
    replies = []
    for question in QUESTIONS:
        citations = (
            PLANTED_HALLUCINATION if question == "Q4"
            else () if question == "Q5"
            else CLEAN_CITATIONS[question]
        )
        replies.append(narrative_completion(
            f"Question {question[1:]}: the response works through the "
            "evidence for this question.",
            citations,
        ))
    replies.append(narrative_completion(L2_TEXT))
    provider = CaptureProvider(replies)
    Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
    return Worker(store, provider, synth_ref()).synthesize_submission(
        run_id, SUBMISSION
    )


def test_tc_stats_19_the_planted_defects_are_detected_at_the_stated_n(
    tmp_data_dir, network_guard, monkeypatch
):
    """The two rates name the two planted classes exactly, at n = 6.

    The detector is the shipped anchoring (`#98`'s per-claim form, over the
    stored narratives `TC-SYNTH-08` samples); what is TC-STATS-19's is the
    detection claim: the planted defects are *detected* at the sample size
    used — the fractions are exact, and the two rates are different
    measurements (the uncited L1 row lowers validity without raising the
    hallucinated rate, so neither rate alone carries the full finding)."""
    store = open_store(tmp_data_dir)
    try:
        report = _measured_report(store, monkeypatch)

        assert report.sample_size == STATED_N, (
            f"the sample drew {report.sample_size}; the stated n is the "
            "declared rate's draw over the run's six stored narratives — "
            "detection at a sample size nobody states is detection nobody "
            "can weigh (TC-SYNTH-08 attaches the size; TC-STATS-19 detects "
            "at it)"
        )
        assert report.citation_validity_rate == pytest.approx(EXPECTED_VALIDITY), (
            f"citation_validity_rate={report.citation_validity_rate!r}; the "
            "planted sample carries three cleanly-anchored L1 rows and the "
            "L2 row (4 valid of 6) — an implementation counting the uncited "
            "L1 row as valid reads 5/6, one measuring over only the citing "
            "narratives reads 4/5, and either is a different claim about "
            "the same planted sample (FR-STATS-12, NFR-SYNTH-01)"
        )
        assert report.hallucinated_claim_rate == pytest.approx(
            EXPECTED_HALLUCINATED
        ), (
            f"hallucinated_claim_rate={report.hallucinated_claim_rate!r}; "
            "the planted cross-question citation is the one hallucinating "
            "narrative in the sample (1 of 6) — a rate of 0.0 is a detector "
            "that never saw the planted claim, and any other value is "
            "counting something the sample does not carry"
        )
        assert report.citation_validity_rate != report.hallucinated_claim_rate
        network_guard.assert_no_network()
    finally:
        store.close()


def test_tc_stats_19_the_measured_rates_travel_the_channel_and_never_the_figure(
    tmp_data_dir, network_guard
):
    """The planted rates, declared through the channel, arrive verbatim in
    `narrative_quality` — and nowhere on the agreement figure.

    The channel is the shape the two suites share: the measurement is
    `M-SYNTH`'s (`SynthesisReport`'s rates over the sampled narratives),
    the report is `M-STATS`'s (`narrative_quality`, the channel's own type —
    `CT-STATS-14`). With the channel declared, the leak prohibition is
    sharper than C14's no-channel run: a metric that leaks onto the figure
    here would be one the planted channel put there."""
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(
        labels=broken.agreeing_population(),
        narrative_metrics={
            "citation_validity_rate": EXPECTED_VALIDITY,
            "hallucinated_claim_rate": EXPECTED_HALLUCINATED,
        },
    )

    narrative = stats.narrative_quality()
    assert narrative.citation_validity_rate == pytest.approx(EXPECTED_VALIDITY), (
        "the channel's citation-validity rate did not arrive verbatim; the "
        "planted sample's measured fraction is the value the report carries "
        "(FR-STATS-12)"
    )
    assert narrative.hallucinated_claim_rate == pytest.approx(
        EXPECTED_HALLUCINATED
    ), "the planted hallucination rate did not arrive verbatim through the channel"
    assert narrative.channel_declared is True

    figure = stats.agreement(**vocab.EMPTY_DATA_CALL["agreement"])
    leaked = [name for name in vocab.NARRATIVE_QUALITY_METRICS if hasattr(figure, name)]
    assert leaked == [], (
        f"{leaked} appear on the agreement figure with the narrative channel "
        "declared. The rates are reported separately from criterion-score "
        "agreement (CT-STATS-14), and a channel's presence is not a licence "
        "to merge — a system with an excellent kappa and hallucinated "
        "feedback is failing at its most valuable job."
    )
    network_guard.assert_no_network()