"""`TC-GRADE-22` — the exhaustive state-transition matrix of the grade state model.

Test plan §5.14; `FR-GRADE-07` (the `incomplete` biconditional and its operator
routing); Integration / 3; exhaustive state-transition matrix; P0. The case names the
three illegal cells — *final reverting to provisional in place, provisional to
incomplete without a missing criterion, incomplete to final while `criteria_missing >
0`* — and demands that *"every legal transition the design's state model declares
succeeds and every illegal one is refused"*.

The design's state model (detailed-design §3.14, `_settlement_state`) has exactly three
states and no transition surface — states are **computed** per pass, never commanded:

    incomplete ── input arrives ──▶ provisional ── settlement ──▶ final
        │                              │                            │
        └──── still missing ───────────┴─── unchanged ──────────────┘
              (holds, no write)            (holds, no write)

so "refused" for an illegal cell means **structurally unreachable**: no sequence of
passes, settlement pressures or edits can produce it. Each illegal cell below is probed
from every direction the pressure can come from (run completion, a lapsed review
window, and both together), and each legal cell is either asserted here or
cross-referenced to the sibling that owns it:

| From | To | Verdict | Where |
|---|---|---|---|
| incomplete | incomplete (still missing) | holds, no write | here, test 1 |
| incomplete | final while `criteria_missing > 0` | **refused** | here, test 1 — under both settlement pressures |
| incomplete | provisional (input arrives) | succeeds | `test_incomplete_and_routing.py::test_issue_101_a_recovered_incomplete_grade_recomputes_out_of_incomplete` — the recovery limb, whose docstring hands the matrix to this story |
| provisional | provisional (unchanged) | holds, no write | here, test 2 |
| provisional | final (settlement) | succeeds, in place | here, test 2 (the lapsed-window road; the 350-student run-completion road is `test_finalization.py`) |
| provisional | incomplete without a missing criterion | **refused** | here, test 2 — under every pressure; the judgment-uncertainty differential is `TC-GRADE-07`'s limb 3 in `test_incomplete_and_routing.py` |
| final | final (unchanged) | holds, no write | here, test 3 |
| final | provisional **in place** | **refused** | here, test 3 — a content change mints a new revision; the delivered one keeps its state |

`incomplete` is reachable only from ingestion failure (a criterion with no
`criterion_score` row at all), never from judgment uncertainty — a provisional-routed
input keeps the grade out of `incomplete` (test 2). The biconditional sweep
(`state == 'incomplete'` ⟺ `criteria_missing > 0`, FR-GRADE-07's own words) runs over
every row the file's scenarios write.

**Disclosed stand-ins** (`grade_vocabulary.py`, header): the run-completion UPDATE
(`M-ORCH` is the run row's single writer), `write_criterion_scores` standing in for
`M-AGG` — writing *fewer* rows than the package declares is exactly how this fixture
manufactures an ingestion failure — and `backdate_grades` pinning `computed_at` so the
window-lapse pressure is determinizable without a wall-clock seam.

**Isolation:** rung 2 — real store, real package lineage, real grade ledger.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from aeh.pkg import GradePolicy, PackageCatalog
from aeh.store import open_store
from tests.support.grade_vocabulary import (
    GRADE_BLOCKER,
    backdate_grades,
    grade_rows,
    write_criterion_scores,
)
from tests.support.impl import GRADE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration]

ISSUE = GRADE_BLOCKER

_PACKAGE = "pkg-orch"

#: A settled review window: 1 hour, so a backdated grade is past it.
_WINDOW_HOURS = 1

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C3", "kind": "open", "scoring_model": "atomic"},
)


def _lapsed_computed_at():
    """25 hours ago, microsecond-free — the review-window cases' backdate value."""
    return (datetime.now(timezone.utc) - timedelta(hours=25)).replace(
        microsecond=0
    ).isoformat()


def _seed_run(store, submissions, window_hours=_WINDOW_HOURS):
    """A run under a windowed policy, so the window-lapse settlement pressure is
    available alongside run completion."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    _orchestrator, run_id, version = seed_run(
        store, submissions=submissions, criteria=_CRITERIA
    )
    catalog = PackageCatalog(store.package(_PACKAGE), package_id=_PACKAGE)
    catalog.set_grade_policy(
        version, GradePolicy(combination="weighted_sum", review_window_hours=window_hours)
    )
    return run_id, store.cohort(ORCH_COHORT_ID)


def _complete_run(cohort, run_id):
    """The run-completion settlement pressure (the run row is M-ORCH's alone to write)."""
    with cohort.transaction() as tx:
        tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=run_id)


def _current(cohort, submission_id):
    rows = [g for g in grade_rows(cohort) if g["submission_id"] == submission_id]
    currents = [g for g in rows if g["is_current"]]
    assert len(currents) == 1, (
        f"{len(currents)} current rows for {submission_id} — exactly one is_current "
        "row is the ledger's invariant (ADR-9)"
    )
    return currents[0], len(rows)


def _assert_biconditional(cohort):
    """FR-GRADE-07's own words over every row in the ledger: `incomplete` only when
    `criteria_missing > 0`, and every `criteria_missing > 0` row reads `incomplete`."""
    for row in grade_rows(cohort):
        missing = int(row["criteria_missing"])
        state = row["state"]
        assert (state == "incomplete") == (missing > 0), (
            f"{row['submission_id']} revision {row['revision']}: state={state!r} with "
            f"criteria_missing={missing} — the biconditional (`incomplete` only when "
            "`criteria_missing > 0`, and every missing-input grade carries it) is "
            "FR-GRADE-07's sentence, and it must hold on every row the model writes"
        )


def test_tc_grade_22_incomplete_holds_under_every_settlement_pressure(tmp_data_dir):
    """Illegal cell 3: `incomplete` → `final` while `criteria_missing > 0` — refused
    under run completion, under a lapsed window, and under both together; the legal
    hold cell (`incomplete` → `incomplete`, no write) is what the refusals leave."""
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort = _seed_run(store, ("S-T1",))
        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        # C2 and C3 carry no row at all: the ingestion failure FR-GRADE-07 names.
        write_criterion_scores(cohort, [("S-T1", "C1", "B2", 7.0, "auto")])
        svc.compute_all(run_id)
        first, total_rows = _current(cohort, "S-T1")
        assert first["state"] == "incomplete", (
            f"fixture premise failed: the first grade reads {first['state']!r}, "
            "expected `incomplete` over the two missing inputs"
        )
        assert first["criteria_missing"] == 2, (
            f"criteria_missing reads {first['criteria_missing']!r}, expected 2 over "
            "the absent C2 and C3 (fixture drift)"
        )
        assert json.loads(first["missing_criteria"] or "[]") == ["C2", "C3"], (
            f"the grade names {first['missing_criteria']!r} — FR-GRADE-07: the grade "
            "shall name the specific missing inputs"
        )

        # Pressure 1 alone: the run completes while the input is still missing.
        _complete_run(cohort, run_id)
        svc.compute_all(run_id)
        held, rows_now = _current(cohort, "S-T1")
        assert held["state"] == "incomplete" and held["revision"] == 1 and rows_now == total_rows, (
            f"run completion moved the incomplete grade (state={held['state']!r}, "
            f"revision={held['revision']}, rows={rows_now}) — `incomplete` is never "
            "settled: a missing input awaits an operator, not a window or a run "
            "completion (illegal cell 3, TC-GRADE-22)"
        )

        # Pressure 2 alone: the review window lapses while the input is still missing.
        backdate_grades(cohort, _lapsed_computed_at())
        _svc2 = open_grade(store)
        _svc2.compute_all(run_id)
        held2, rows_now2 = _current(cohort, "S-T1")
        assert held2["state"] == "incomplete" and held2["revision"] == 1 and rows_now2 == total_rows, (
            f"a lapsed window moved the incomplete grade (state={held2['state']!r}, "
            f"revision={held2['revision']}, rows={rows_now2}) — the window delays "
            "finalization only (FR-GRADE-11); it cannot settle an incomplete grade"
        )

        # Both pressures together: still held, still one revision.
        svc.compute_all(run_id)
        held3, rows_now3 = _current(cohort, "S-T1")
        assert held3["state"] == "incomplete" and held3["revision"] == 1 and rows_now3 == total_rows, (
            "run completion plus a lapsed window settled an incomplete grade — no "
            "settlement pressure reaches an incomplete grade (illegal cell 3)"
        )
        _assert_biconditional(cohort)
    finally:
        store.close()


def test_tc_grade_22_a_fully_scored_grade_never_mints_incomplete(tmp_data_dir):
    """Illegal cell 2: provisional → incomplete without a missing criterion — refused
    under every pressure; `incomplete` is reachable only from ingestion failure, never
    from judgment uncertainty. The legal cells it leaves behind: provisional holds
    unchanged (no write), then settles `final` in place (same revision, no mint)."""
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort = _seed_run(store, ("S-T2",))
        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        # Every input scored; C2's routing is `provisional` — judgment uncertainty,
        # the only alternative cause a state model could confuse with incompleteness.
        write_criterion_scores(
            cohort,
            [("S-T2", "C1", "B2", 7.0, "auto"), ("S-T2", "C2", "B1", 6.0, "provisional"),
             ("S-T2", "C3", "B2", 7.5, "auto")],
        )
        svc.compute_all(run_id)
        issued, rows_at_issue = _current(cohort, "S-T2")
        assert issued["state"] == "provisional", (
            f"the issued grade reads {issued['state']!r} — a fully-scored submission "
            "with a provisional input issues `provisional` (FR-GRADE-06), and the "
            "provisional routing shows in the coverage counter, not the state"
        )
        assert int(issued["criteria_provisional"]) == 1 and int(issued["criteria_missing"]) == 0, (
            f"coverage reads provisional={issued['criteria_provisional']!r} missing="
            f"{issued['criteria_missing']!r} — the uncertainty is counted in the "
            "coverage record (FR-GRADE-04), never folded into `incomplete`"
        )

        # Cell: provisional -> provisional (unchanged) — the hold cell. An unchanged
        # recompute over the issued grade writes nothing: same revision, same row
        # count, state still provisional. (TC-GRADE-18's idempotence limb pins the
        # same no-write from the row-count side; here the matrix cell is the state's.)
        svc.compute_all(run_id)
        held, rows_after_hold = _current(cohort, "S-T2")
        assert held["state"] == "provisional" and held["revision"] == issued["revision"], (
            f"an unchanged recompute left state={held['state']!r} revision="
            f"{held['revision']} — the provisional hold cell: an unchanged pass "
            "touches nothing, no mint and no settlement (TC-GRADE-18/NFR-GRADE-05)"
        )
        assert rows_after_hold == rows_at_issue, (
            f"{rows_after_hold - rows_at_issue} new rows from an unchanged recompute — "
            "the provisional hold cell writes nothing (NFR-GRADE-05)"
        )

        # Pressure: the window lapses with nothing changed. The grade settles to
        # `final` IN PLACE — the same revision, no mint — and never dips through
        # `incomplete` on the way.
        backdate_grades(cohort, _lapsed_computed_at())
        svc.compute_all(run_id)
        settled, rows_after_settle = _current(cohort, "S-T2")
        assert settled["state"] == "final" and settled["revision"] == 1, (
            f"the lapsed-window pass left state={settled['state']!r} "
            f"revision={settled['revision']} — settlement is provisional→final IN "
            "PLACE: the only in-place transition the model has, and it must not mint "
            "a revision to settle (test_finalization.py owns the two roads; this is "
            "the matrix cell)"
        )
        assert rows_after_settle == rows_at_issue, (
            f"{rows_after_settle - rows_at_issue} new rows from a settlement — "
            "settling an unchanged grade writes its state in place, never a new "
            "revision"
        )
        assert all(row["state"] != "incomplete" for row in grade_rows(cohort)), (
            "a row reads `incomplete` in a run where nothing was ever missing — "
            "illegal cell 2: `incomplete` without a missing criterion (FR-GRADE-07's "
            "biconditional; the judgment-uncertainty differential is TC-GRADE-07's)"
        )

        # Pressure: run completion, then a recompute — `final` holds (cell final→final).
        _complete_run(cohort, run_id)
        svc.compute_all(run_id)
        after, _rows = _current(cohort, "S-T2")
        assert after["state"] == "final" and after["revision"] == 1, (
            f"the settled grade reads {after['state']!r} revision {after['revision']} "
            "after run completion — `final` holds under recomputation (final→final)"
        )
        _assert_biconditional(cohort)
    finally:
        store.close()


def test_tc_grade_22_a_final_grade_never_reverts_in_place(tmp_data_dir):
    """Illegal cell 1: final reverting to provisional in place — refused. An unchanged
    recompute touches nothing; a content change mints a NEW revision (fresh window) and
    the delivered revision keeps its state and its row: retention, not demotion."""
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort = _seed_run(store, ("S-T3",))
        open_grade = require(GRADE_MODULE, "open_grade", issue=ISSUE)
        svc = open_grade(store)
        write_criterion_scores(
            cohort,
            [("S-T3", "C1", "B2", 7.0, "auto"), ("S-T3", "C2", "B1", 6.0, "auto"),
             ("S-T3", "C3", "B2", 7.5, "auto")],
        )
        svc.compute_all(run_id)
        # The window lapses over an unchanged grade: the settlement road of
        # test 2, already exercised there — here it only arms the `final` state.
        backdate_grades(cohort, _lapsed_computed_at())
        svc.compute_all(run_id)
        final_row, rows_before = _current(cohort, "S-T3")
        assert final_row["state"] == "final" and final_row["revision"] == 1, (
            f"fixture premise failed: state={final_row['state']!r} "
            f"revision={final_row['revision']} — expected revision 1 settled `final`"
        )

        # An unchanged recompute after settlement: nothing at all happens.
        svc.compute_all(run_id)
        unchanged, rows_after_unchanged = _current(cohort, "S-T3")
        assert rows_after_unchanged == rows_before and unchanged["revision"] == 1, (
            "an unchanged recompute after settlement rewrote the ledger — NFR-GRADE-05 "
            "reaching settled rows (the illegal in-place revert is also a phantom "
            "write)"
        )
        assert unchanged["state"] == "final", (
            f"the settled grade reads {unchanged['state']!r} after an unchanged "
            "recompute — `final` never demotes in place (illegal cell 1)"
        )

        # A content change after settlement: the model's only road out of `final` is
        # a NEW revision — the delivered one keeps its state and its row.
        write_criterion_scores(cohort, [("S-T3", "C1", "B2", 3.0, "auto")])
        svc.compute_all(run_id)
        delivered, rows_after_edit = _current(cohort, "S-T3")
        assert rows_after_edit == rows_before + 1 and delivered["revision"] == 2, (
            f"the corrected content wrote {rows_after_edit - rows_before} new rows and "
            f"the current revision is {delivered['revision']} — a change after "
            "settlement must mint revision 2, not rewrite revision 1"
        )
        assert delivered["state"] == "provisional", (
            f"revision 2 reads {delivered['state']!r} — a fresh revision earns a "
            "fresh review window (`_settlement_state`'s fresh-issuance anchor); the "
            "model produces a new provisional revision, it does not revert the "
            "delivered one in place"
        )
        superseded = [g for g in grade_rows(cohort) if g["revision"] == 1][0]
        assert superseded["state"] == "final" and not superseded["is_current"], (
            f"revision 1 reads state={superseded['state']!r} is_current="
            f"{superseded['is_current']!r} — the delivered `final` revision must keep "
            "its state when a new revision arrives: demotion clears the current flag, "
            "never the state (illegal cell 1: final reverting to provisional IN PLACE)"
        )
        _assert_biconditional(cohort)
    finally:
        store.close()


def test_tc_grade_22_the_service_surface_carries_no_in_place_transition_path(tmp_data_dir):
    """The structural half of every illegal cell: there is no path. The grade state
    model has no transition API — states are computed per pass — so the service's
    public surface carries no method by which a caller could command one: no
    revert/demote/unfinalize/reopen/set-state member exists to even attempt an
    illegal transition with (the `FR-GRADE-06` "shall provide no path" phrasing,
    applied to the state model)."""
    store = open_store(tmp_data_dir)
    try:
        run_id, _cohort = _seed_run(store, ("S-T4",))
        svc = require(GRADE_MODULE, "open_grade", issue=ISSUE)(store)

        surface = [
            name for name in dir(svc)
            if not name.startswith("_") and callable(getattr(svc, name, None))
        ]
        forbidden = (
            "revert", "demote", "unfinalize", "un_finalize", "reopen", "re_open",
            "regress", "downgrade", "retract", "set_state", "setstate", "transition",
            "mutate",
        )
        offenders = [
            name for name in surface
            if any(token in name.lower() for token in forbidden)
        ]
        assert not offenders, (
            f"the grading service exposes in-place transition surfaces {offenders!r} — "
            "the state model has no transition path (states are computed per pass, "
            "FR-GRADE-07's biconditional and FR-GRADE-12's retention are structural, "
            "not API-enforced): every illegal cell of TC-GRADE-22 must be "
            "unreachable, and a callable that commands state would make them "
            "reachable"
        )
        assert not hasattr(svc, "transition"), (
            "a transition method exists — the matrix's refusals must be structural"
        )
    finally:
        store.close()