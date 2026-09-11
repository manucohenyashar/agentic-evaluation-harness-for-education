"""`TC-REVIEW-17` — observed `review_seconds` accumulating over several sessions, Phase 1 limbs.

Test plan §5.15, issue #112 (TS-40). Traces to `FR-REVIEW-16`. Row form: *"Observed
`review_seconds` accumulating over several sessions. `est_seconds` is recorded per item and
calibrated against observed values over time."* Oracle: exact value. P2, **Phase 2**.

What Phase 1 owns — asserted here, because nothing shipped carries it:

* **Accumulation across sessions** (`end_session` boundaries, `FR-REVIEW-08`): per-act
  `review_seconds` lands on each label exactly, the run's totals accumulate exactly across
  sittings, and the residual debt the session closes over is exact too — the queue still owes
  what the sitting did not finish.
* **`est_seconds` recorded per item**: every admitted item carries its own row's estimate —
  not a batch constant — and the per-item values are what the budget's fill consumes and the
  observability surface's mean-estimate figure aggregates.

What the row stamps Phase 2 — the *calibration* of the estimate against observed values over
time — is disposed, not dodged: `CT-REVIEW-19` (`tests/contract/review/
test_ct_review_budget_and_ranking.py`) holds the non-promise (the console never presents the
budget as a guarantee) and the Phase-2 reachability limb (both calibration inputs stored; the
module takes `est_seconds` given at Phase 1). There is no calibration interface to test at
Phase 1, and inventing one would be the defect the plan's own stamp warns against.

**Isolation:** rung 0 — in-memory rows, no store, no model.
"""

from __future__ import annotations

import pytest

from tests.support import broken_review_fixtures as broken
from tests.support.impl import REVIEW_MODULE, require, require_attr

pytestmark = pytest.mark.contract

RUN_ID = "run-1"
#: The four per-sitting figures, chosen so the accumulation is exact and distinct per act:
#: 90 + 60 + 45 + 105 = 300 observed seconds over four sessions.
SESSION_SECONDS = (90, 60, 45, 105)


def _four_estimated_rows() -> list[broken.ScoreRow]:
    """Four rows whose per-item estimates differ by construction.

    `est_seconds` is `FR-REVIEW-16`'s recorded side: the fixture's rows carry 30/60/30/60 so
    "recorded per item" is falsifiable — a module stamping one batch estimate on every item
    fails the exact per-item assertions below.
    """
    return [
        broken.ScoreRow(
            score_id="r0", criterion_id="C-01", submission_id="sub-r0",
            proposed_band="B2", panel_spread=1.0, adverse_integrity_signals=3,
            transcription_overlap=1.0, historical_override_rate=1.0,
            criterion_weight=1.0, grade_boundary_delta=0.0, est_seconds=30,
        ),
        broken.ScoreRow(
            score_id="r1", criterion_id="C-01", submission_id="sub-r1",
            proposed_band="B1", panel_spread=1.0, adverse_integrity_signals=3,
            transcription_overlap=1.0, historical_override_rate=1.0,
            criterion_weight=1.0, grade_boundary_delta=0.0, est_seconds=60,
        ),
        broken.ScoreRow(
            score_id="r2", criterion_id="C-02", submission_id="sub-r2",
            proposed_band="B3", panel_spread=0.5, adverse_integrity_signals=1,
            transcription_overlap=0.5, historical_override_rate=1 / 3,
            criterion_weight=1.0, grade_boundary_delta=0.0, est_seconds=60,
        ),
        broken.ScoreRow(
            score_id="r3", criterion_id="C-02", submission_id="sub-r3",
            proposed_band="B4", panel_spread=1.0, adverse_integrity_signals=3,
            transcription_overlap=1.0, historical_override_rate=1.0,
            criterion_weight=1.0, grade_boundary_delta=0.0, est_seconds=30,
        ),
    ]


def test_tc_review_17_review_seconds_accumulate_across_sessions():
    """Four acts over four sessions: every figure exact, at every boundary.

    Hand-computed: 300 observed seconds accumulate as 1.5, 2.5, 3.25, 5.0 minutes used, a mean
    of 75.0 per act — and the residual debt shrinks 3, 2, 1, 0 as the sessions resolve their
    rows. The accumulation is read back after each `end_session` boundary, and every label
    carries the exact seconds its sitting spent.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=_four_estimated_rows())
    require_attr(service, "end_session", issue="#111")
    require_attr(service, "observability_counters", issue="#110")

    used_by_session = []
    residual_by_session = []
    for session, seconds in enumerate(SESSION_SECONDS):
        queue = service.build_queue(run_id=RUN_ID, budget_minutes=30)
        label = service.label(
            service.act(
                queue.shown[0], action="override", new_band="B1", review_seconds=seconds
            )
        )
        assert label.review_seconds == seconds, (
            f"session {session + 1}'s label recorded {label.review_seconds!r} observed seconds "
            f"against the sitting's {seconds!r} — the observed value is the calibration side, "
            "and it has to arrive per label"
        )
        report = service.end_session(run_id=RUN_ID)
        assert report.moment == "end_session"

        counters = service.observability_counters(run_id=RUN_ID)
        used_by_session.append(counters["review_minutes_used"])
        residual_by_session.append(report.residual_provisional)

    assert used_by_session == [
        sum(SESSION_SECONDS[:n]) / 60 for n in range(1, len(SESSION_SECONDS) + 1)
    ], (
        f"review minutes used over the sessions read {used_by_session}; the observed seconds "
        "accumulate exactly — 1.5, 2.5, 3.25, 5.0 — or a sitting's time was dropped"
    )
    assert residual_by_session == [4 - n for n in (1, 2, 3, 4)], (
        f"the residual across sessions read {residual_by_session}; the queue still owes what "
        "each sitting did not finish — 3, 2, 1, 0 — and a session boundary that reset it would "
        "silently convert 'not reviewed' into 'reviewed'"
    )

    labels = service.labels_for(run_id=RUN_ID)
    assert len(labels) == len(SESSION_SECONDS), (
        f"{len(labels)} labels after four acting sessions — a session boundary dropped one"
    )
    assert sorted(label.review_seconds for label in labels) == sorted(SESSION_SECONDS), (
        "the label store's per-act seconds do not match the sittings' figures — the "
        "accumulation is the labels', not a separate tally"
    )
    final = service.observability_counters(run_id=RUN_ID)
    assert final["review_minutes_used"] == pytest.approx(sum(SESSION_SECONDS) / 60), (
        f"four sessions accumulated {final['review_minutes_used']!r} minutes against 300 "
        "observed seconds"
    )
    assert final["mean_review_seconds"] == pytest.approx(
        sum(SESSION_SECONDS) / len(SESSION_SECONDS)
    ), (
        f"the mean observed seconds read {final['mean_review_seconds']!r} against 75.0"
    )


def test_tc_review_17_est_seconds_is_recorded_per_item_and_is_what_the_budget_spends():
    """The estimate side, at exact per-item values.

    `FR-REVIEW-16`: *"the module shall record `est_seconds` per item."* A batch estimate — one
    figure stamped on every row — satisfies a non-`None` check and makes the budget meaningless
    for exactly the items whose review pace differs. The fixture's rows carry 30/60/30/60; the
    queue's fill spends them per item (30 + 30 + 60 reaches exactly the 120 spendable seconds
    at a 12-minute budget and the second 60s row does not), and the observability surface's
    mean-estimate figure is the mean of the recorded per-item values, 40.0.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=_four_estimated_rows())
    require_attr(service, "observability_counters", issue="#110")

    expected_by_id = {row.score_id: row.est_seconds for row in _four_estimated_rows()}
    # 12 minutes minus the 10-minute reservation: 120s. The ranked order (r0, r3, r1, r2)
    # spends 30 + 30 + 60 and the 60s second estimate does not fit — the fill consumed the
    # per-item values, which is the recording's consequence, not just its bookkeeping.
    queue = service.build_queue(run_id=RUN_ID, budget_minutes=12)
    shown = list(queue.shown)

    assert [entry.score_id for entry in shown] == ["r0", "r3", "r1"], (
        f"the budget's fill over per-item estimates showed "
        f"{[entry.score_id for entry in shown]} against the ranked spend of 30 + 30 + 60"
    )
    assert queue.residual_provisional == 1, (
        f"a window spent exactly on three of four rows left a residual of "
        f"{queue.residual_provisional}"
    )
    for entry in shown:
        assert entry.est_seconds == expected_by_id[entry.score_id], (
            f"{entry.score_id} shows est_seconds {entry.est_seconds!r} against its row's "
            f"{expected_by_id[entry.score_id]!r}. FR-REVIEW-16 records the estimate per item: "
            "a batch constant makes the budget meaningless for the items whose review pace "
            "differs."
        )

    counters = service.observability_counters(run_id=RUN_ID)
    assert counters["mean_est_seconds"] == pytest.approx(40.0), (
        f"the observability surface's mean estimate read {counters['mean_est_seconds']!r} "
        "against (30 + 30 + 60) / 3 = 40.0 — the recorded per-item values, not a batch figure"
    )