"""`TS-88` (issue #382) — `TC-AGG-23`: `aggregation_signals` over one run's stored rows.

Gap-fix test plan §5 (`FR-AGG-17`, P1, rung 2):

    Run R with 3 criteria: C1 bands `[1,1,2,3]` with spreads `[0,1,2,0]`, 1 of 4 escalated, 2 of
    4 auto-accepted, cap `uncited_cap` fired twice. Expected: `band_histogram(C1) = {1:2, 2:1,
    3:1}`, `band_spread_distribution = {0:2, 1:1, 2:1}`, `escalation_rate = 0.25`,
    `auto_accept_rate = 0.5`, `caps_fired.uncited_cap = 2`; α distribution matches the hand value;
    another run's rows excluded. Oracle: hand-computed.

**Hand-built rows.** `criterion_score` rows (run-scoped, #359's shape) and one escalation
`work_unit` (`origin='escalation'`, the ledger's shipped marker for a widened unit) are written
directly — FR-AGG-17 says the emitter reads "only from stored `criterion_score` and `work_unit`
rows", so rows are the right input. Band names are the ordinals as text (`"1"`, `"2"`, `"3"`) so the
plan's numeric keys and a name-keyed histogram read the same; keys are compared as strings.

**The α distribution's hand value.** The rows carry agreements `[1.0, 0.6, 0.6, 1.0]`; the
distribution must hold exactly those four values (as a value→count mapping or a sequence — both
are read). The plan points at F-STATS for the value; the F-STATS generator fixes no per-row α for
this case, so the stored values are the hand value.

Run RB's rows sit in the same cohort file with every figure different (all band 3, spread 2,
all escalated, all capped), so a missing run filter moves every assertion.

**Written ahead of implementation: yes** — keyed on `aeh.agg:aggregation_signals` (#371, which
depends on #359's run-scoped table).

**Interface assumed:** `aggregation_signals(handle, run_id)` returns an object whose contract names
(CT-AGG-21: `band_histogram`, `band_spread_distribution`, `agreement_distribution`,
`escalation_rate`, `auto_accept_rate`, `caps_fired`) are per-criterion mappings, with
`caps_fired[criterion]` a cap-name→count mapping.
"""

from __future__ import annotations

import json
from collections import Counter

import pytest

import aeh.agg  # noqa: F401 — the full migration chain
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.store import open_store
from tests.support.impl import AGG_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort

pytestmark = pytest.mark.integration

ISSUE = "#371"
RUN_R = "run-tc-agg-23-r"
RUN_RB = "run-tc-agg-23-rb"
SUBMISSIONS = ("S1", "S2", "S3", "S4")

#: C1 per submission: (band, spread, routing, agreement, caps_fired).
C1_ROWS = (
    ("1", 0, "auto", 1.0, ["uncited_cap"]),
    ("1", 1, "queued", 0.6, ["uncited_cap"]),
    ("2", 2, "queued", 0.6, []),
    ("3", 0, "auto", 1.0, []),
)


def _seed(store) -> None:
    seed_cohort(store, SUBMISSIONS)
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        def score(run_id, submission, criterion, band, spread, routing, agreement, caps):
            tx.execute(
                "INSERT INTO criterion_score (run_id, submission_id, criterion_id, band, "
                "modal_band, band_spread, points, judge_count, agreement, routing, state, "
                "caps_fired) VALUES (:r, :s, :c, :b, :b, :sp, 1.0, 3, :a, :ro, 'final', :cf)",
                r=run_id, s=submission, c=criterion, b=band, sp=spread, a=agreement, ro=routing,
                cf=json.dumps(caps),
            )

        for submission, (band, spread, routing, agreement, caps) in zip(SUBMISSIONS, C1_ROWS):
            score(RUN_R, submission, "C1", band, spread, routing, agreement, caps)
            score(RUN_R, submission, "C2", "2", 0, "auto", 1.0, [])
            score(RUN_R, submission, "C3", "2", 0, "auto", 1.0, [])
            score(RUN_RB, submission, "C1", "3", 2, "queued", 0.1, ["uncited_cap", "other_cap"])
            tx.execute(
                "INSERT INTO work_unit (work_id, submission_id, stage, status, run_id, "
                "criterion_id, judge_id, origin) VALUES (:w, :s, 'score', 'done', :r, 'C1', "
                "'judge-x', 'escalation')",
                w=f"esc-rb-{submission}", s=submission, r=RUN_RB,
            )
        # Base score units for every (submission, criterion) of run R, so the escalation rate
        # reads the same whether its denominator is the criterion's score rows or its base units.
        for submission in SUBMISSIONS:
            for criterion in ("C1", "C2", "C3"):
                tx.execute(
                    "INSERT INTO work_unit (work_id, submission_id, stage, status, run_id, "
                    "criterion_id, judge_id, origin) VALUES (:w, :s, 'score', 'done', :r, :c, "
                    "'judge-x', 'base')",
                    w=f"base-r-{submission}-{criterion}", s=submission, r=RUN_R, c=criterion,
                )
        # Run R: exactly one of C1's four submissions escalated.
        tx.execute(
            "INSERT INTO work_unit (work_id, submission_id, stage, status, run_id, criterion_id, "
            "judge_id, origin) VALUES ('esc-r-S2', 'S2', 'score', 'done', :r, 'C1', 'judge-x', "
            "'escalation')",
            r=RUN_R,
        )


def _as_counter(distribution) -> Counter:
    if hasattr(distribution, "items"):
        return Counter({float(k): int(v) for k, v in distribution.items()})
    return Counter(float(v) for v in distribution)


def _str_keys(mapping) -> dict[str, int]:
    return {str(k): int(v) for k, v in dict(mapping).items()}


@pytest.mark.writtenahead
def test_tc_agg_23_aggregation_signals_match_the_hand_computed_values(tmp_data_dir):
    """`TC-AGG-23` — every C1 figure hand-computed from four rows; RB contributes nothing."""
    aggregation_signals = require(AGG_MODULE, "aggregation_signals", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        _seed(store)
        signals = aggregation_signals(store.cohort(ORCH_COHORT_ID), RUN_R)

        assert _str_keys(signals.band_histogram["C1"]) == {"1": 2, "2": 1, "3": 1}
        assert _str_keys(signals.band_spread_distribution["C1"]) == {"0": 2, "1": 1, "2": 1}
        assert signals.escalation_rate["C1"] == 0.25, (
            f"escalation_rate(C1) = {signals.escalation_rate['C1']!r}; one of four escalated"
        )
        assert signals.auto_accept_rate["C1"] == 0.5
        assert int(dict(signals.caps_fired["C1"]).get("uncited_cap", 0)) == 2
        assert "other_cap" not in dict(signals.caps_fired["C1"]), "run RB's caps leaked"
        assert _as_counter(signals.agreement_distribution["C1"]) == Counter({1.0: 2, 0.6: 2})

        assert set(signals.band_histogram) >= {"C1", "C2", "C3"}
        assert _str_keys(signals.band_histogram["C2"]) == {"2": 4}
        assert signals.escalation_rate["C2"] == 0.0
    finally:
        store.close()
