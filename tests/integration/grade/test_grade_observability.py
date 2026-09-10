"""`TC-GRADE-24` — the grading stage's observability: the full signal set and the
outstanding-`incomplete` alert.

Test plan §5.14; `FR-GRADE-01`, `FR-GRADE-10`; Observability / 2; exact signal plus
alert; P1. The case's fixture is *"A run finishing with two `incomplete` grades past
the window"* and its oracle: *"Grades by state, `boundary_at_risk` count, coverage
distribution, finalization path taken and amendment count all emitted; the
outstanding-`incomplete` alert fires."*

The signal set is design §3.14's observability paragraph (CT-GRADE-18):

- **grades by state** — the three state literals' counts (the `CoverageSummary.
  grades_by_state` shape the vocabulary pinned);
- **`boundary_at_risk` count** — how many of the run's grades sit on a boundary;
- **coverage distribution** — the five-counter coverage over the class, not one scalar;
- **finalization path taken** — which road settled the grades (run completion vs the
  lapsed review window vs the batch action; FR-GRADE-10's two automatic paths);
- **amendment count** — how many amendments the run carries (the revisions' trail);
- **the outstanding-`incomplete` alert** — grades still `incomplete` past the review
  window fire an alert: the operator rescan is late (FR-GRADE-07's operator routing is
  actionable, not a dead end).

**Written ahead of implementation** (test plan §8.2). The signals have no shipped
emitter: nothing in `aeh.grade` writes a metrics or alert surface, and the alert
engine itself (`aeh.orch:evaluate_alerts`) is still reserved for #66 (`TC-ORCH-36`'s
entry in `WRITTEN_AHEAD_BLOCKERS`). The design's M-GRADE observability paragraph is
this story's to implement, so this file carries `@pytest.mark.writtenahead` and its
registry entry is the conjunction over the two symbols below.

**The invented-and-disclosed keys** (the `evaluate_alerts` / `export_grade_artifacts`
precedent — names no design document declares, that the tests call and the landing
reconciles; checked: zero occurrences in both design documents):

- `aeh.grade:record_grade_signals` — the signal writer: the grading stage's figures
  land where every other stage's do, the durable `run_metrics` EAV rows
  `(run_id, metric, value)` (`TC-ORCH-35`'s precedent — CT-ORCH-20 makes that write
  contract; the grading stage's own signal set rides the same table).
- `aeh.grade:evaluate_grade_alerts` — the alert evaluator over the same store state:
  returns the alerts that fire, of which the outstanding-`incomplete`-past-the-window
  is this case's pinned one.

The names reconcile at the story's landing like every other reserved name in this
suite. Keyed on **#103** (the finalization/amendment story — `FR-GRADE-10`'s owner,
whose "Observability from the design implemented" definition-of-done clause is where
this surface ships), not on `#101` (landed — the gate would fire immediately) nor on
a Protocol-declared name (resolves against a stub).

**Disclosed stand-ins** (`grade_vocabulary.py`, header): the run-completion UPDATE
(`M-ORCH` is the run row's single writer), `write_criterion_scores` standing in for
`M-AGG` — writing fewer rows than the package declares is how the fixture manufactures
the two ingestion failures — and `backdate_grades` pinning `computed_at` past the
window (a wall-clock seam on the service is not a design-declared surface).

**Isolation:** rung 2 — real store, real grade ledger, real Tier D metrics table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aeh.store import open_store
from tests.support.grade_vocabulary import backdate_grades, grade_rows, write_criterion_scores
from tests.support.impl import GRADE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [
    pytest.mark.integration,
    # Red by design until the observability surface lands (WRITTEN_AHEAD_BLOCKERS:
    # "#103 grade signals and incomplete alert" -> the conjunction over
    # `aeh.grade:record_grade_signals` and `aeh.grade:evaluate_grade_alerts` — one
    # entry, because the test needs both and a half-landed surface must not fire the
    # gate into a still-red unmark).
    pytest.mark.writtenahead,
]

ISSUE = "#103"

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C3", "kind": "open", "scoring_model": "atomic"},
)

#: Every CT-GRADE-18 signal concept, as (concept label, name tokens that satisfy it) —
#: the `TC-ORCH-35` CONCEPTS precedent: a metric whose concept is present but whose
#: exact string is the writer's to land fails neither the case nor the truth.
CONCEPTS = (
    ("grades by state", ("state", "grades_by_state", "incomplete", "provisional", "final")),
    ("boundary_at_risk count", ("boundary",)),
    ("coverage distribution", ("coverage",)),
    ("finalization path", ("finalization", "finalize", "settlement", "path")),
    ("amendment count", ("amendment",)),
)


def _lapsed_computed_at():
    """A `computed_at` 25 hours in the past — the shipped 24-hour window's lapse."""
    return (
        (datetime.now(timezone.utc) - timedelta(hours=25))
        .replace(microsecond=0)
        .isoformat()
    )


def _seed_run_finishing_with_two_incomplete_past_the_window(store):
    """Four submissions: two complete (their grades finalize at run completion) and
    two with a missing input (`C3` carries no row — the ingestion failure), whose
    grades are `incomplete` and whose window has lapsed: the alert's exact condition."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    _orchestrator, run_id, _version = seed_run(
        store, submissions=("S-O1", "S-O2", "S-O3", "S-O4"), criteria=_CRITERIA
    )
    cohort = store.cohort(ORCH_COHORT_ID)
    write_criterion_scores(
        cohort,
        [(sid, cid, "B2", 7.0, "auto")
         for sid in ("S-O1", "S-O2")
         for cid in ("C1", "C2", "C3")]
        + [(sid, cid, "B1", 5.0, "auto")
           for sid in ("S-O3", "S-O4")
           for cid in ("C1", "C2")],
    )
    svc = require(GRADE_MODULE, "open_grade", issue=ISSUE)(store)
    svc.compute_all(run_id)
    with cohort.transaction() as tx:
        tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=run_id)
    backdate_grades(cohort, _lapsed_computed_at())
    svc.compute_all(run_id)  # the settlement pass over the lapsed, completed run
    incomplete = [g for g in grade_rows(cohort) if g["state"] == "incomplete"]
    assert len(incomplete) == 2, (
        f"fixture premise failed: {len(incomplete)} incomplete grades, expected 2 "
        "(S-O3 and S-O4 miss the C3 input; S-O1 and S-O2 are complete)"
    )
    return run_id


def test_tc_grade_24_the_grading_stage_emits_every_signal_and_fires_the_alert(
    tmp_data_dir,
):
    """`TC-GRADE-24` — the signal set is emitted (every CT-GRADE-18 concept present in
    the durable metrics by name-token; the incomplete figure reconciled to the ledger's
    hand count, the value half of the "exact signal" oracle), and the
    outstanding-`incomplete` alert fires for the two grades past the window."""
    record_grade_signals = require(GRADE_MODULE, "record_grade_signals", issue=ISSUE)
    evaluate_grade_alerts = require(GRADE_MODULE, "evaluate_grade_alerts", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        run_id = _seed_run_finishing_with_two_incomplete(store)

        record_grade_signals(run_id)
        alerts = evaluate_grade_alerts(run_id)

        # The signal set, per concept over the durable EAV rows (the TC-ORCH-35
        # reading): presence by name-token, values reconciled where hand-countable.
        metrics = {
            row["metric"]: row["value"]
            for row in store.durable().query(
                "SELECT metric, value FROM run_metrics WHERE run_id = :r", r=run_id
            )
        }
        assert metrics, (
            "record_grade_signals wrote no metrics rows — a stage-level signal set "
            "that persists nothing is the silent-failure shape (CLAUDE.md seam 4)"
        )
        for label, tokens in CONCEPTS:
            assert any(
                any(token in name.lower() for token in tokens) for name in metrics
            ), (
                f"run_metrics carries no {label} signal — CT-GRADE-18 lists it; "
                f"present: {sorted(metrics)}"
            )
        assert any(
            "incomplete" in name.lower() for name in metrics
        ), (
            f"run_metrics carries no incomplete count — the grades-by-state signal "
            f"must break the states out (present: {sorted(metrics)})"
        )

        # The value half of the "exact signal" oracle: the fixture hand-counts exactly
        # two incomplete grades, so the incomplete-named signal must CARRY that count,
        # not merely exist — a signal whose figure disagrees with the ledger is the
        # silent-failure shape. Token-selected, not name-pinned: among the metrics
        # whose name names `incomplete`, at least one reads the hand count.
        def _numeric(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        incomplete_values = [
            value for name, value in metrics.items() if "incomplete" in name.lower()
        ]
        assert any(_numeric(value) == 2.0 for value in incomplete_values), (
            f"no incomplete-named metric carries the ledger's hand count 2 "
            f"(incomplete-named values: {incomplete_values!r}) — the grades-by-state "
            "signal is reconciled to the ledger, not merely emitted (TC-GRADE-24's "
            "'exact signal' oracle; the fixture's two incomplete grades are counted)"
        )

        # The alert: two incomplete grades outstanding past the window fire one.
        assert alerts, (
            "no alert fired for two incomplete grades outstanding past the review "
            "window — the outstanding-incomplete alert is the case's pinned half "
            "(CT-GRADE-18; an operator's queue needs the alert, not only the count)"
        )
        incomplete_alerts = [
            alert for alert in alerts
            if "incomplete" in str(getattr(alert, "kind", "")).lower()
            or "incomplete" in str(alert).lower()
        ]
        assert incomplete_alerts, (
            f"the alerts {alerts!r} name no incomplete condition — the alert must be "
            "readable as the outstanding-incomplete one"
        )
    finally:
        store.close()