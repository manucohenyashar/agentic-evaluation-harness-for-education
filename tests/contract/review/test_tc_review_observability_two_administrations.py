"""`TC-REVIEW-23` — the two-administration observability case, at exact figures.

Test plan §5.15, issue #112 (TS-40). Traces to `FR-REVIEW-01`, `FR-REVIEW-04`. Row form:
*"Two consecutive administrations where one criterion exhausts the budget. `review_minutes_used`,
items shown versus flagged, override rate by criterion, group-action share, blind completion rate
and mean versus estimated seconds all emitted; the exhausted-criterion pattern alert fires across
administrations."* Oracle: exact signal plus alert. P1.

`CT-REVIEW-18` (`tests/contract/review/test_ct_review_limits_and_config.py`) holds the clause
limbs: the counter *names* by set containment, the shown/flagged emission pairing, and the
exhaustion signal's retention across administrations. This file implements the **case**: one
scenario — a criterion eating the whole budget in two consecutive administrations — with every
one of the eight counters at an **exact, hand-computed figure** per administration, and the
alert absent after one administration and exact after two.

One service carries both administrations (`alerts` retention is service state, and the plan's
scenario is one teacher's two terms). The population holds four rows of the exhausted criterion:
two per-item rows for administration 1 and a signature-identical pair whose group administration
2 acts through. The fill arithmetic makes the exhaustion literal: a 12-minute budget minus the
10-minute blind reservation leaves 120s, and C-01's entries take both 60s slots — the group
first (entry order), then the top per-item row — so *only* C-01 is ever shown, in either
administration. Administration 1's action resolves its row, which is why administration 2's
flagged pool is one smaller: the exact figures are the scenario's, not a constant's.

Administration 1 acts per-item (group share 0.0); administration 2 acts through the group
(share 1.0), so the group counter is asserted at a nonzero figure too. `blind_completion_rate`
is `None` in both because neither drew a sample: the unmeasured rate, never a silent zero,
which is itself one of the eight figures the case pins.

**Isolation:** rung 0 — in-memory rows, no store, no model.
"""

from __future__ import annotations

import pytest

from tests.support import broken_review_fixtures as broken
from tests.support import review_vocabulary as vocab
from tests.support.impl import REVIEW_MODULE, require, require_attr

pytestmark = pytest.mark.contract

EXHAUSTED_CRITERION = "C-01"
#: 12 minutes at a 10-minute reservation leaves 120s — exactly two 60s C-01 entries.
BUDGET_MINUTES = 12
RESERVE_MINUTES = vocab.CONFIG_DEFAULTS["REVIEW_BLIND_RESERVE_MINUTES"]
FILLER_ROWS = 4
APPLIED_BAND = "B4"


def _exhausting_row(score_id: str, band: str) -> broken.ScoreRow:
    """One all-max C-01 row: P(error) 4.0, impact 1.0, EV 4/60 — the queue's first picks."""
    return broken.ScoreRow(
        score_id=score_id,
        criterion_id=EXHAUSTED_CRITERION,
        submission_id=f"sub-{score_id}",
        proposed_band=band,
        panel_spread=1.0,
        adverse_integrity_signals=3,
        transcription_overlap=1.0,
        historical_override_rate=1.0,
        criterion_weight=1.0,
        grade_boundary_delta=0.0,
        est_seconds=60,
    )


def _population() -> list[broken.ScoreRow]:
    """Four C-01 rows and the fillers: the exhausted criterion eats the whole spendable window.

    `x1`/`x2` carry distinct bands (the exact-signature rule keeps them per-item entries) and
    are administration 1's per-item targets. `e1`/`e2` share a band and signature — one group,
    administration 2's target — so acting per-item in administration 1 cannot disturb it. The
    groups-first entry rule means both administrations' builds open with the group and spend
    their second slot on the highest-ranked remaining C-01 row: only C-01 is ever shown.
    """
    return [
        broken.ScoreRow(
            score_id="x1", criterion_id=EXHAUSTED_CRITERION, submission_id="sub-x1",
            proposed_band="B2", panel_spread=1.0, adverse_integrity_signals=3,
            transcription_overlap=1.0, historical_override_rate=1.0,
            criterion_weight=1.0, grade_boundary_delta=0.0, est_seconds=60,
        ),
        broken.ScoreRow(
            score_id="x2", criterion_id=EXHAUSTED_CRITERION, submission_id="sub-x2",
            proposed_band="B1", panel_spread=1.0, adverse_integrity_signals=3,
            transcription_overlap=1.0, historical_override_rate=1.0,
            criterion_weight=1.0, grade_boundary_delta=0.0, est_seconds=60,
        ),
        broken.ScoreRow(
            score_id="e1", criterion_id=EXHAUSTED_CRITERION, submission_id="sub-e1",
            proposed_band="B3", panel_spread=1.0, adverse_integrity_signals=3,
            transcription_overlap=1.0, historical_override_rate=1.0,
            criterion_weight=1.0, grade_boundary_delta=0.0, est_seconds=60,
        ),
        broken.ScoreRow(
            score_id="e2", criterion_id=EXHAUSTED_CRITERION, submission_id="sub-e2",
            proposed_band="B3", panel_spread=1.0, adverse_integrity_signals=3,
            transcription_overlap=1.0, historical_override_rate=1.0,
            criterion_weight=1.0, grade_boundary_delta=0.0, est_seconds=60,
        ),
        *[
            broken.ScoreRow(
                score_id=f"f{i}", criterion_id=f"C-{i + 2:02d}", submission_id=f"sub-f{i}",
                proposed_band="B1", panel_spread=0.02, adverse_integrity_signals=0,
                transcription_overlap=0.0, historical_override_rate=0.0,
                criterion_weight=1.0, grade_boundary_delta=0.0, est_seconds=60,
            )
            for i in range(FILLER_ROWS)
        ],
    ]


def _build_and_exhaust(service, run_id: str):
    """Build the administration's queue and record the exhaustion; return the queue.

    The fixture sanity the exact figures lean on: every shown entry belongs to the exhausted
    criterion — C-01 ate the whole spendable window, which is what makes every counter below
    an exhaustion figure.
    """
    queue = service.build_queue(run_id=run_id, budget_minutes=BUDGET_MINUTES)
    assert queue.reserved_for_blind_minutes == RESERVE_MINUTES
    shown_criteria = {entry.criterion_id for entry in queue.shown}
    assert shown_criteria == {EXHAUSTED_CRITERION}, (
        f"{run_id}'s build did not exhaust the budget on {EXHAUSTED_CRITERION} alone: shown "
        f"covers {shown_criteria}"
    )
    service.exhaust_budget_on(criterion_id=EXHAUSTED_CRITERION, administration_id=run_id)
    return queue


def test_tc_review_23_all_eight_counters_carry_the_exact_figures_in_both_administrations():
    """Every named counter, at its hand-computed value, per administration.

    The containment clause is `CT-REVIEW-C18`'s; what is new here is the arithmetic. The two
    administrations differ only in the action path (one per-item edit, then one group action),
    so the counters that could be run-blind — minutes, means, the group share — move exactly
    as the scenario says, and a counter carrying the other administration's figures fails.

    Administration 1: the group plus `x1` shown (3 items of 8), 90s of individual override
    (1.5 minutes), mean review 90.0 against mean estimate 60.0, override counts
    `{"C-01": 1}`, group share 0.0, blind rate an honest `None`. Administration 2: the same
    shown shape over the one-smaller flagged pool (7 — `x1` resolved in administration 1),
    120s through the group (2.0 minutes), per-member share 1.0, mean review 60.0.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=_population())
    require_attr(service, "observability_counters", issue="#110")

    # Administration 1: per-item decisions — the group's members are not touched, so the
    # group survives to administration 2.
    queue_1 = _build_and_exhaust(service, "admin-1")
    service.act(queue_1.shown[-1], action="override", new_band="B1", review_seconds=90)

    # Administration 2: one decision through the group — the share becomes 1.0.
    queue_2 = _build_and_exhaust(service, "admin-2")
    groups = [entry for entry in queue_2.shown if hasattr(entry, "members")]
    assert groups, "administration 2's build lost the exhausted criterion's group"
    service.act_on_group(groups[0], band=APPLIED_BAND, review_seconds=120)

    expected = {
        "admin-1": {
            "review_minutes_used": 1.5,
            "review_items_shown": 3,
            "review_items_flagged": 2 + 2 + FILLER_ROWS,
            "override_rate_by_criterion": {EXHAUSTED_CRITERION: 1},
            "group_action_usage_share": 0.0,
            "blind_completion_rate": None,
            "mean_review_seconds": 90.0,
            "mean_est_seconds": 60.0,
        },
        "admin-2": {
            "review_minutes_used": 2.0,
            "review_items_shown": 3,
            "review_items_flagged": 2 + 2 + FILLER_ROWS - 1,
            "override_rate_by_criterion": {EXHAUSTED_CRITERION: 2},
            "group_action_usage_share": 1.0,
            "blind_completion_rate": None,
            "mean_review_seconds": 60.0,
            "mean_est_seconds": 60.0,
        },
    }

    for administration, figures in expected.items():
        counters = service.observability_counters(run_id=administration)
        missing = sorted(set(vocab.OBSERVABILITY_COUNTERS) - set(counters))
        assert missing == [], (
            f"{administration} does not emit {missing}. TC-REVIEW-23: every named counter is "
            "emitted for the exhausted-criterion administration — a counter that is absent is a "
            "question nobody can ask of a finished run."
        )
        for name, expected_value in figures.items():
            assert counters[name] == expected_value, (
                f"{administration}'s {name} reads {counters[name]!r} against the scenario's "
                f"{expected_value!r}. TC-REVIEW-23 asserts exact signal: a counter that is "
                "emitted but wrong is the same silent failure as one that is missing."
            )


def test_tc_review_23_the_exhaustion_alert_fires_at_two_consecutive_administrations():
    """The pattern alert: absent after one administration, exact at two.

    `CT-REVIEW-C18`'s retention test exhausts the criterion by calling the precondition twice;
    this case runs the two administrations the plan pins and asserts the alert's *absence*
    after the first — a module firing at one administration has not seen a pattern, it has seen
    a busy week — and the exact shape at two: the declared name, the exhausted criterion, two
    consecutive administrations in order.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    service = build_review(scores=_population())
    require_attr(service, "alerts", issue="#110")

    _build_and_exhaust(service, "admin-1")

    assert service.alerts() == (), (
        "an alert fired after one administration. §3.15's Alert surfaces a *pattern* — one "
        "criterion exhausting the budget once is a busy week, and firing then is the "
        "absorbed-each-term reading of a signal that exists to survive the term boundary."
    )

    _build_and_exhaust(service, "admin-2")
    matching = [
        alert for alert in service.alerts()
        if alert.name == vocab.BUDGET_EXHAUSTION_ALERT
    ]
    assert len(matching) == 1, (
        f"after two consecutive exhausted administrations the standing alerts are "
        f"{service.alerts()!r} — exactly one exhaustion alert for the exhausted criterion"
    )
    alert = matching[0]
    assert alert.criterion_id == EXHAUSTED_CRITERION
    assert alert.consecutive_administrations == vocab.ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS, (
        f"the alert reports {alert.consecutive_administrations} consecutive administrations "
        f"against the declared minimum of "
        f"{vocab.ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS} — the count is the pattern's size, "
        "not a threshold the module rounds"
    )
    assert alert.administrations == ("admin-1", "admin-2"), (
        f"the alert's administrations are {alert.administrations!r}; the two administrations "
        "the scenario names, in order, are what the retention keeps"
    )