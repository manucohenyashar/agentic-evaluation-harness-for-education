"""`TS-89` (issue #383) — `TC-REVIEW-25`: every `FR-REVIEW-18` ranking input is read from the
stored row or the run's package, never from a literal default.

The plan's sweep, one case per line:

| Input | Stored value | Expected |
|---|---|---|
| `panel_spread` | `criterion_score.band_spread = 2` | 2 |
| `adverse_integrity_signals` | uncited=1, ocr_overlap=1, described=0, disagreement=NULL | 2 (NULL is not adverse) |
| `transcription_overlap` | `ocr_overlap_risk = 1` | truthy |
| `scoring_model` | criterion `holistic` in the run's version | `"holistic"` |
| `criterion_weight` | grade-policy weight 2.5 | 2.5 |
| `historical_override_rate` | 4 judgments, 1 override (n = 4 < 5) | `None` |
| `historical_override_rate` | 5 judgments, 2 overrides | 0.4 — **blocked on #433** |
| `grade_boundary_delta` | total 69.5, nearest boundary 70 | 0.5 |
| `est_seconds` | atomic / holistic, knobs unset | 45 / 90 |
| run filter | run RB has `band_spread = 3` for the same pair | R's row still reads 2 |

**The defect this sweep exists to prevent made the entire ranking constant.** The seven inputs
were fetched under the *ranking's* vocabulary — `panel_spread`, `transcription_overlap`,
`criterion_weight` — and `select_run_advisory_scores` has never returned those names. Every one
resolved `None`, `_impact_of` multiplies by `criterion_weight`, and so every store-backed row
scored `rank_score = 0.0`. The queue was ordered by the store's row order while presenting
itself as a ranking, and nothing reported it: a constant score is a legal score.

**So "not a literal default" is the assertion, not "not None".** Each case below pins a value
the stored row or the package actually carries, and each value is chosen to differ from the
input's declared fallback — a weight of 2.5 against the fallback of 1.0, a `holistic` model
against the model-free default, a spread of 2 against nothing at all.

**The run filter is the last line and the quietest failure.** Two runs over one cohort hold
rows for the same `(submission, criterion)`. A read that dropped `run_id` would rank run R by
run RB's panel spread — a number that is real, plausible, and about a different run.

**`historical_override_rate`'s second row is `writtenahead` on #433.** The input is inert:
`_ScoreRowContext` is never constructed with `override_rates`, so the rate is `None` for every
store-backed row whatever the history holds. The `n = 4` row therefore passes today for the
wrong reason and the `n = 5` row cannot pass at all — see
`tests/unit/stats/test_tc_stats_31_override_history.py`, which carries the blocker entry.

**Isolation: rung 2** — a real store, a real package with weights, models and a boundary
table, and the rows the service actually built.
"""

from __future__ import annotations

from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
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
from aeh.pkg import GradePolicy, PackageCatalog
from aeh.review import (
    REVIEW_EST_SECONDS_ATOMIC,
    REVIEW_EST_SECONDS_HOLISTIC,
    _service_from_store,
)
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_run

pytestmark = pytest.mark.integration

SUBMISSION = "S001"
HOLISTIC = "C1"
ATOMIC = "C2"

#: The weight the grade policy declares for C1. Deliberately not 1.0, which is the declared
#: fallback for a criterion the policy does not name — a test at 1.0 would pass against a
#: reader that never looked.
C1_WEIGHT = 2.5

#: The submission's total and the boundary it sits below: 70 − 69.5 = 0.5.
TOTAL = 69.5
BOUNDARY = 70.0
EXPECTED_BOUNDARY_DELTA = 0.5

EXPECTED_SPREAD = 2
EXPECTED_ADVERSE = 2

CRITERIA = (
    {"criterion_id": HOLISTIC, "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": ATOMIC, "kind": "open", "scoring_model": "atomic"},
)

_INSERT_SCORE = Statement(
    "INSERT INTO criterion_score (run_id, submission_id, criterion_id, band, points, "
    "routing, state, band_spread, spans_verified, evidence_present, sufficiency_flag, "
    "ocr_overlap_risk, described_evidence, extractor_disagreement, caps_fired) "
    "VALUES (:run_id, :submission_id, :criterion_id, :band, 6.0, 'provisional', "
    "'provisional_unreviewed', :band_spread, :spans_verified, 1, 0, :ocr_overlap_risk, "
    "0, NULL, NULL)"
)
_INSERT_TOTAL = Statement(
    # `revision` is NOT NULL: `submission_grade` is append-only with revisions (#103), and
    # `select_run_submission_totals` reads `is_current = 1` so a superseded revision does not
    # place the submission at a boundary it has already left.
    "INSERT INTO submission_grade (run_id, submission_id, total, revision, is_current) "
    "VALUES (:run_id, :submission_id, :total, 1, 1)"
)


@pytest.fixture
def sweep_world(tmp_data_dir):
    """Run R with both criteria scored, a second run RB holding a different spread.

    `caps_fired` is left NULL on purpose. `adverse_signal_count` selects the two written
    signals (`described_evidence`, `extractor_disagreement`) only for a row whose `caps_fired`
    is recorded, because a NULL in them on an older row means "this column did not exist", not
    "not measured". With `caps_fired` NULL the count is over the four recorded signals, which
    is what makes the plan's "disagreement=NULL → not adverse" true.
    """
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_a, version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        catalog.set_grade_policy(
            version,
            GradePolicy(
                combination="weighted_sum",
                weights=((HOLISTIC, C1_WEIGHT), (ATOMIC, 1.0)),
            ),
        )
        catalog.set_boundaries(version, (("A", BOUNDARY), ("B", 60.0), ("C", 50.0)))

        from aeh.orch import Orchestrator

        run_b = Orchestrator(store).create_run(ORCH_COHORT_ID, version, orch_cfg())

        cohort = store.cohort(ORCH_COHORT_ID)
        with cohort.transaction() as tx:
            tx.execute(
                _INSERT_SCORE,
                run_id=run_a, submission_id=SUBMISSION, criterion_id=HOLISTIC,
                band="B3", band_spread=EXPECTED_SPREAD,
                spans_verified=0,      # "uncited": the spans did not verify — adverse
                ocr_overlap_risk=1,    # adverse
            )
            tx.execute(
                _INSERT_SCORE,
                run_id=run_a, submission_id=SUBMISSION, criterion_id=ATOMIC,
                band="B2", band_spread=1, spans_verified=1, ocr_overlap_risk=0,
            )
            # RB's row for the SAME pair, with a different spread.
            tx.execute(
                _INSERT_SCORE,
                run_id=run_b, submission_id=SUBMISSION, criterion_id=HOLISTIC,
                band="B4", band_spread=3, spans_verified=1, ocr_overlap_risk=0,
            )
            tx.execute(
                _INSERT_TOTAL, run_id=run_a, submission_id=SUBMISSION, total=TOTAL
            )
    finally:
        store.close()
    return tmp_data_dir, run_a, run_b


def _service(world):
    """A run-scoped service over the stored rows.

    **Not `open_review`, and that is a reported defect rather than a preference.**
    `open_review(data_dir, run_id=X)` passes `cohort_ids=[run_id]` and leaves
    `_service_from_store`'s own `run_id` as `None` (`review.py:3431`), so the parameter named
    `run_id` is used as the COHORT id and the scope falls through to
    `_newest_run_id(store, cohort_id)`. Two consequences, both measured here:

    * a real run id opens `store.cohort(<run id>)` — **creating a stray cohort file** — and
      finds no rows at all;
    * a cohort id serves whichever run is newest, so there is no way to ask `open_review` for
      a named run. With two unstarted runs the tiebreak is `run_id DESC`, which is a uuid
      comparison, so which run answers is effectively random per fixture.

    Its docstring says "a review service over a stored **run's** flagged rows" and "attributed
    to the `run_id` named here"; neither holds. #383 reports it. This case needs the scoping
    the plan's last sweep row is about, so it uses the internal constructor that has it.
    """
    tmp_data_dir, run_a, _run_b = world
    store = open_store(tmp_data_dir)
    service = _service_from_store(
        store, cohort_ids=[ORCH_COHORT_ID], run_id=run_a,
    )
    return store, service


def _rows(world) -> dict[str, Any]:
    """The `_StoredScoreRow` objects run R's service built, keyed by criterion."""
    store, service = _service(world)
    try:
        return {str(row.criterion_id): row for row in service._rows}
    finally:
        store.close()


# --- TC-REVIEW-25, one case per sweep row ---------------------------------------------------


def test_tc_review_25_panel_spread_is_the_stored_band_spread(sweep_world):
    """`panel_spread` reads `criterion_score.band_spread`, not a re-derivation.

    The aggregator recorded the ordinal distance between the panel's extreme bands; the
    ranker reads that figure rather than recomputing one that could disagree with the
    confidence already stored on the same row.
    """
    row = _rows(sweep_world)[HOLISTIC]

    assert row.panel_spread == EXPECTED_SPREAD, (
        f"panel_spread is {row.panel_spread!r}, not {EXPECTED_SPREAD}. The store's column is "
        "`band_spread`; fetching it under the ranking's own name returns None and ranks every "
        "row identically"
    )


def test_tc_review_25_the_adverse_signal_count_excludes_an_unrecorded_null(sweep_world):
    """Two adverse signals: the unverified spans and the OCR overlap. NULL is not one.

    `caps_fired` is NULL on this row, so the two written signals are outside the field set —
    a NULL there means the column did not exist when the row was written, and counting it
    adverse would rank an older row above a newer one for having been written earlier.
    """
    row = _rows(sweep_world)[HOLISTIC]

    assert row.adverse_integrity_signals == EXPECTED_ADVERSE, (
        f"the adverse count is {row.adverse_integrity_signals!r}, not {EXPECTED_ADVERSE}: "
        "spans_verified=0 and ocr_overlap_risk=1 are adverse, evidence_present=1 and "
        "sufficiency_flag=0 are not, and the two written signals are out of scope on a row "
        "with no caps_fired"
    )


def test_tc_review_25_transcription_overlap_is_the_ocr_risk_flag(sweep_world):
    """`transcription_overlap` reads `ocr_overlap_risk` — the 0/1 column `_p_error` weights."""
    rows = _rows(sweep_world)

    assert rows[HOLISTIC].transcription_overlap, (
        f"transcription_overlap is {rows[HOLISTIC].transcription_overlap!r} for a row whose "
        "ocr_overlap_risk is 1"
    )
    assert not rows[ATOMIC].transcription_overlap, (
        "the row with ocr_overlap_risk = 0 reads as overlapping, so the input is not the flag"
    )


def test_tc_review_25_the_scoring_model_comes_from_the_run_s_package(sweep_world):
    """`C1` reads `holistic` and `C2` reads `atomic` — the version's declarations.

    Both, so a reader returning one constant is caught. The hard-coded `"atomic"` this
    replaces answered for both and budgeted the holistic criterion at half a teacher's time.
    """
    rows = _rows(sweep_world)

    assert rows[HOLISTIC].scoring_model == "holistic", (
        f"C1's model reads {rows[HOLISTIC].scoring_model!r}"
    )
    assert rows[ATOMIC].scoring_model == "atomic", (
        f"C2's model reads {rows[ATOMIC].scoring_model!r}"
    )


def test_tc_review_25_est_seconds_follows_the_model(sweep_world):
    """45 s for the atomic criterion, 90 s for the holistic one, knobs unset.

    The consequence of the row above. Reading the model right and then estimating both at the
    same figure leaves the budget arithmetic exactly as wrong as the hard-coded default did.
    """
    rows = _rows(sweep_world)

    assert rows[ATOMIC].est_seconds == REVIEW_EST_SECONDS_ATOMIC == 45.0, (
        f"the atomic criterion is estimated at {rows[ATOMIC].est_seconds}s"
    )
    assert rows[HOLISTIC].est_seconds == REVIEW_EST_SECONDS_HOLISTIC == 90.0, (
        f"the holistic criterion is estimated at {rows[HOLISTIC].est_seconds}s, not 90 — a "
        "holistic criterion budgeted at an atomic one's minutes is the defect FR-REVIEW-19 "
        "exists to fix"
    )


def test_tc_review_25_criterion_weight_comes_from_the_grade_policy(sweep_world):
    """`C1`'s weight is 2.5 — the policy's figure, not the 1.0 fallback.

    This is the input that made the ranking constant: `_impact_of` multiplies by it, so a
    weight that resolved `None` zeroed the product however loud the other six inputs were.
    2.5 is chosen precisely because 1.0 is the declared fallback for an unnamed criterion.
    """
    row = _rows(sweep_world)[HOLISTIC]

    assert float(row.criterion_weight) == C1_WEIGHT, (
        f"criterion_weight is {row.criterion_weight!r}, not {C1_WEIGHT}. A weight of 1.0 here "
        "would mean the policy was never read — `_impact_of` multiplies by this, so the "
        "whole ranking depends on it"
    )


def test_tc_review_25_the_boundary_delta_is_the_distance_to_the_nearest_cut(sweep_world):
    """Total 69.5 against a boundary at 70 → 0.5.

    Hand-computed, and the figure that makes proximity mean anything: a submission half a
    point below a grade boundary is where a teacher's minute is worth most.
    """
    row = _rows(sweep_world)[HOLISTIC]

    assert row.grade_boundary_delta == pytest.approx(EXPECTED_BOUNDARY_DELTA), (
        f"grade_boundary_delta is {row.grade_boundary_delta!r}, not "
        f"{EXPECTED_BOUNDARY_DELTA}: the submission totals {TOTAL} and the nearest cut is at "
        f"{BOUNDARY}"
    )


def test_tc_review_25_a_second_runs_row_never_leaks_into_this_ones(sweep_world):
    """RB holds `band_spread = 3` for the same pair; R's row still reads 2.

    The quietest failure in the sweep. A read that dropped `run_id` would rank run R by run
    RB's panel spread — a number that is real, plausible, and about a different run.
    """
    tmp_data_dir, run_a, run_b = sweep_world
    rows = _rows(sweep_world)

    assert rows[HOLISTIC].panel_spread == EXPECTED_SPREAD, (
        f"run R's row reads panel_spread {rows[HOLISTIC].panel_spread!r}; RB's row for the "
        f"same (submission, criterion) carries 3, so the read is not scoped to the run"
    )
    assert run_a != run_b, "the fixture built one run twice"


def test_tc_review_25_an_override_rate_below_the_minimum_is_absent(sweep_world):
    """`historical_override_rate` is `None` where the history is too short to be a rate.

    Four teachers who overrode once are not a 25% override rate; they are four teachers, and
    `CT-STATS-09`'s no-data figure applies rather than a number.

    **This passes today for the wrong reason** — the input is inert, so it is `None` for every
    row whatever the history holds (#433). It is kept because `None` is the right answer for
    this row either way, and its companion (`n = 5` → 0.4) is the case that cannot pass;
    `tests/unit/stats/test_tc_stats_31_override_history.py` carries it and the blocker entry.
    """
    row = _rows(sweep_world)[HOLISTIC]

    assert row.historical_override_rate is None, (
        f"historical_override_rate is {row.historical_override_rate!r}; below the minimum "
        "count the rate is absent, and a zero would say nobody ever disagrees with this "
        "criterion"
    )


def test_tc_review_25_the_ranking_is_not_constant_across_the_two_rows(sweep_world):
    """The sweep's point, in one assertion: two differently-flagged rows rank differently.

    Every case above could pass with the inputs read correctly into a ranker that ignored
    them. This is the end-to-end check that they reach the score — and it is the exact
    symptom the defect produced, since `rank_score = 0.0` for every row is what a missing
    input actually looked like.
    """
    _tmp, run_a, _run_b = sweep_world
    store, service = _service(sweep_world)
    queue = service.build_queue(run_a, 120, record=False)

    values = [
        float(getattr(member, "expected_value", 0.0))
        for entry in queue.shown
        for member in (getattr(entry, "members", None) or (entry,))
    ]

    assert len(values) == 2, f"the build showed {len(values)} items, not two"
    assert len(set(values)) == 2, (
        f"both rows scored {values[0]}. A constant expected value is what a ranking whose "
        "inputs all resolve None looks like — it is a legal score, and nothing reports it"
    )
    assert any(value > 0.0 for value in values), (
        f"every row scored zero: {values}"
    )
