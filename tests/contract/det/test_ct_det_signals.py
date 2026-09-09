"""`CT-DET-13` — the per-question signals and the scanning alert (`TC-DET-C13`).

Case of test plan §6.11.11; issue #90 (TS-68). Green by design — `M-DET`
shipped via #246/#249.

The clause: the pass emits, **per question**, correct rate, blank count,
unresolved count and most-chosen distractor; an unresolved count above
threshold alerts as a **scanning** problem — reading it as item difficulty is
the specific misinterpretation the metric is separated to prevent.

The clause discriminator: C08 pinned the figures' separation at the API and
DDL layers; this case pins the EMISSION — what a consumer (ops, `M-CONSOLE`)
actually receives and reads:
- **the emission names are contract**: the summary dataclass's field set is
  asserted EXACTLY — the four clause figures exist under exactly those names,
  dimensioned by `criterion_id`/`question_id`, and the values are hand-built
  per question, including the no-distractor question and the blank that stays
  inside the incorrect band;
- **the alert is threshold-exact and per question**: two questions straddle
  the knob — one at 0.3 (crosses), one at 0.1 with an unresolved row of its
  own (does not) — so the threshold, not the mere presence of unresolved
  rows, is what fires; the alert carries the question's own identity plus the
  threshold it crossed, so an operator can answer "which question" and "by
  how much" from the emission alone;
- **the names alone cannot be conflated**: no emitted key anywhere — summary
  field, alert key or report field — carries difficulty vocabulary, and the
  alert's `kind` names the scan while `reads_as` names the prohibition.
"""

from __future__ import annotations

import dataclasses

import pytest

from aeh.det import (
    CriterionSummary,
    DeterministicEvaluator,
    UNRESOLVED_ALERT_RATE_ENV,
)
from tests.support.det_vocabulary import (
    open_det_store,
    seed_cohort,
    seed_det_package,
    seed_head_document,
    seed_answer_region,
)
from aeh.conf import resolve_run_config
from aeh.orch import Orchestrator
from tests.support.conf_builders import CohortRef, edge_cfg

pytestmark = pytest.mark.contract

from tests.contract.det._doubles import ISSUE  # noqa: F401 — register citation


def _seed_two_question_world(store):
    """A world whose two questions read differently: `M1` (Q1) takes six
    answers — three B (key), one C, one blank, one ambiguous; `M2` (Q2) takes
    three, all D against key B. Hand counts live in the assertions."""
    submissions = ("S1", "S2", "S3", "S4", "S5", "S6")
    seed_cohort(store, submissions, "c-det-signals")
    version = seed_det_package(
        store,
        [
            {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
            {"criterion_id": "M2", "question_id": "Q2", "key": ("B",)},
        ],
    )
    for s in submissions:
        seed_head_document(store, "c-det-signals", s)
    # Q1: S1/S2/S4 answer B (correct), S5 answers C, S6 is blank, S3 is
    # ambiguous — the three-way distinction in one question.
    q1 = [
        ("S1", dict(selection="B")),
        ("S2", dict(selection="B")),
        ("S3", dict(selection_state="ambiguous")),
        ("S4", dict(selection="B")),
        ("S5", dict(selection="C")),
        ("S6", dict(content_state="blank")),
    ]
    # Q2: everyone answers D; the key is B — confidently wrong, and no
    # non-key choice to complicate the distractor reading. All six answer so
    # the question's n matches M1's (an absent read would be unresolved, not
    # missing from n).
    q2 = [(s, dict(selection="D")) for s in submissions]
    for s, kwargs in q1:
        seed_answer_region(store, "c-det-signals", f"doc-{s}", "Q1", **kwargs)
    for s, kwargs in q2:
        seed_answer_region(store, "c-det-signals", f"doc-{s}", "Q2", **kwargs)

    resolved = resolve_run_config(
        edge_cfg(), CohortRef(cohort_id="c-det-signals", consent_class="synthetic")
    )
    run_id = Orchestrator(store).create_run("c-det-signals", version, resolved)
    return run_id, version


def _seed_straddle_world(store):
    """The threshold straddle: ten submissions, three questions, key B on all.
    `M1` (Q1): three ambiguous of ten — unresolved rate 0.3, ABOVE the knob.
    `M2` (Q2): one ambiguous of ten — rate 0.1, below it. `M3` (Q3): two
    ambiguous of ten — rate 0.2, EXACTLY the knob, the boundary cell: the
    clause says "above", so equality does not fire. Everything else answers
    the key."""
    submissions = tuple(f"S{i:02d}" for i in range(1, 11))
    seed_cohort(store, submissions, "c-det-straddle")
    version = seed_det_package(
        store,
        [
            {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
            {"criterion_id": "M2", "question_id": "Q2", "key": ("B",)},
            {"criterion_id": "M3", "question_id": "Q3", "key": ("B",)},
        ],
    )
    for s in submissions:
        seed_head_document(store, "c-det-straddle", s)
        seed_answer_region(store, "c-det-straddle", f"doc-{s}", "Q1",
                           selection=("B" if s not in ("S01", "S02", "S03")
                                      else None),
                           selection_state=(None if s not in
                                            ("S01", "S02", "S03")
                                            else "ambiguous"))
        seed_answer_region(store, "c-det-straddle", f"doc-{s}", "Q2",
                           selection=("B" if s != "S01" else None),
                           selection_state=("ambiguous" if s == "S01"
                                            else None))
        seed_answer_region(store, "c-det-straddle", f"doc-{s}", "Q3",
                           selection=("B" if s not in ("S01", "S02")
                                      else None),
                           selection_state=(None if s not in ("S01", "S02")
                                            else "ambiguous"))
    resolved = resolve_run_config(
        edge_cfg(), CohortRef(cohort_id="c-det-straddle", consent_class="synthetic")
    )
    run_id = Orchestrator(store).create_run("c-det-straddle", version, resolved)
    return run_id, version


def test_tc_det_c13_the_emission_names_and_per_question_values(tmp_data_dir):
    """`TC-DET-C13` (the emission) — the summary's field set is EXACTLY the
    nine names the design fixes (the four clause figures among them, each
    question identified by criterion and question id), and the values read
    back per question exactly as hand-counted: M1 — n=6, correct_rate 0.5,
    blank 1, unresolved 1, distractor C; M2 — n=6, all wrong, no blank, no
    unresolved, distractor D. One summary per question, never a cohort-wide
    merge."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version = _seed_two_question_world(store)
        report = DeterministicEvaluator(store).evaluate_cohort(run_id)

        # The emission's field set, exact — a rename or an addition changes
        # the surface every consumer reads.
        names = {f.name for f in dataclasses.fields(CriterionSummary)}
        assert names == {
            "criterion_id", "question_id", "n", "correct", "correct_rate",
            "blank_count", "unresolved_count", "unresolved_rate",
            "most_chosen_distractor",
        }, (
            f"TC-DET-C13: the per-question emission is {sorted(names)} — the "
            "surface moved under its consumers."
        )

        by_criterion = {s.criterion_id: s for s in report.summaries}
        assert set(by_criterion) == {"M1", "M2"}, (
            "TC-DET-C13: the emission is not per question — "
            f"{sorted(by_criterion)}."
        )

        m1 = by_criterion["M1"]
        assert m1.question_id == "Q1"
        assert m1.n == 6 and m1.correct == 3
        assert m1.correct_rate == pytest.approx(0.5)
        assert m1.blank_count == 1 and m1.unresolved_count == 1
        assert m1.unresolved_rate == pytest.approx(1 / 6)
        assert m1.most_chosen_distractor == "C", (
            "TC-DET-C13: the distractor read is not the highest-count non-key "
            "option."
        )

        m2 = by_criterion["M2"]
        assert m2.question_id == "Q2"
        assert m2.n == 6 and m2.correct == 0
        assert m2.correct_rate == pytest.approx(0.0)
        assert m2.blank_count == 0 and m2.unresolved_count == 0
        assert m2.most_chosen_distractor == "D"
    finally:
        store.close()


def test_tc_det_c13_the_alert_is_threshold_exact_and_a_scanning_problem(
        tmp_data_dir, monkeypatch):
    """`TC-DET-C13` (the alert) — with the knob at 0.2: M1's unresolved rate
    (0.3) crosses and alerts exactly once, keyed to its own question, carrying
    n, the count, the rate and the threshold crossed, with `kind` naming the
    scan and `reads_as` naming the prohibition; M2's rate (0.1) stays below
    and emits NO alert even though it holds an unresolved row of its own —
    the threshold, not the count, is what fires; and M3 sits EXACTLY at the
    knob (0.2 == 0.2) and does not alert either — the clause says "above",
    so equality is not above, pinned by a cell that would catch a `>=`
    regression. No emitted key anywhere carries difficulty vocabulary: the
    misreading the separation exists to prevent cannot be built from the
    emission's names alone."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version = _seed_straddle_world(store)
        monkeypatch.setenv(UNRESOLVED_ALERT_RATE_ENV, "0.2")
        report = DeterministicEvaluator(store).evaluate_cohort(run_id)

        by_criterion = {s.criterion_id: s for s in report.summaries}
        assert by_criterion["M1"].unresolved_rate == pytest.approx(0.3)
        assert by_criterion["M2"].unresolved_count == 1, (
            "TC-DET-C13: the below-threshold question holds no unresolved "
            "row — the differential is vacuous."
        )
        assert by_criterion["M2"].unresolved_rate == pytest.approx(0.1)
        # The boundary cell: exactly at the knob, unresolved rows in hand.
        assert by_criterion["M3"].unresolved_count == 2
        assert by_criterion["M3"].unresolved_rate == pytest.approx(0.2)

        # Exactly one alert, and it names M1 — the question that crossed.
        # Equality is not above: M3's 0.2 did not fire against knob 0.2.
        assert len(report.alerts) == 1, (
            f"TC-DET-C13: {len(report.alerts)} alerts — one question crossed "
            "the threshold, one sat below it and one sat exactly at it, all "
            "with unresolved rows in hand; the emission must say exactly "
            "that."
        )
        alert = report.alerts[0]
        assert alert["criterion_id"] == "M1" and alert["question_id"] == "Q1", (
            "TC-DET-C13: the alert is not dimensioned to its own question."
        )
        assert alert["n"] == 10
        assert alert["unresolved_count"] == 3
        assert alert["unresolved_rate"] == pytest.approx(0.3)
        assert alert["threshold"] == pytest.approx(0.2)

        # The kind names the scan; reads_as names the prohibition verbatim.
        assert alert["kind"] == "scanning_problem"
        assert alert["reads_as"] == "rescan_queue_never_item_difficulty"

        # The conflation proof: no emitted key — summary field, alert key or
        # report field — carries difficulty vocabulary, and no alert field is
        # a difficulty figure.
        emitted = (
            {f.name for f in dataclasses.fields(CriterionSummary)}
            | set(alert.keys())
            | {f.name for f in dataclasses.fields(type(report))}
        )
        difficulty_words = ("difficulty", "hardness", "p_value", "discrimination")
        offenders = {
            name for name in emitted
            if any(word in name.lower() for word in difficulty_words)
        }
        assert not offenders, (
            f"TC-DET-C13: the emission carries difficulty vocabulary: "
            f"{sorted(offenders)} — the scanning signal is reading as item "
            "difficulty."
        )
    finally:
        store.close()
