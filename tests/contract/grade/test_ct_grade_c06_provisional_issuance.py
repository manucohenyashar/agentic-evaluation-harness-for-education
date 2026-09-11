"""`TC-GRADE-C06` — provisional inputs are issued, marked, and never withheld (§6.11.14).

`CT-GRADE-06` (behaviour): "Assert a grade with provisional inputs is **issued and
exportable**, marked `provisional`. The decisive negative: assert **no path** by
which a provisional input **withholds** a grade — swept across configuration, since
this is the failure that reads as caution and is RISK-11. Then assert a review
window **delays finalization only**: during an open window, assert grades are
complete, visible and exportable throughout."

The limbs, in the row's order:

- **issued and exportable** (rung 3/4, green): a submission with one provisional
  criterion delivers a grade whose state reads `provisional`, whose coverage names
  the provisional class, and whose total includes the provisional criterion's own
  figure; the module's own export renders it (a grade that exists in the ledger but
  not on the page is not exportable).
- **the decisive negative, swept across configuration** (rung 3, green): across the
  policy vocabulary — bare, weighted (the provisional figure weighted), scaled,
  rounded, selected, dropped, gated, null window, open window — the grade is
  delivered with a present total and a state that is NEVER `incomplete`
  (`incomplete` is ingestion-failure-only, `CT-GRADE-08`: judgment uncertainty
  reads `provisional`). A withheld grade reads as caution and is exactly the
  failure RISK-11 names.
- **the window delays finalization only** (rung 3/4, green): under an open review
  window the grade stands — visible in the current-grades read, counted in
  coverage, exported to the page — and the lapse settles the SAME revision in
  place (`provisional` -> `final`, `finalized_at` stamped), minting no new
  revision: the state model's arrow is a settlement, not a new computation.

Isolation: rung 3 — real store, real package, real service; rung 4 for the export
limbs. The socket guard is autouse; `criterion_score` rows are the vocabulary's
disclosed `M-AGG` stand-in; `backdate_grades` is the disclosed timestamp stand-in.
"""

from __future__ import annotations

import csv

import pytest

from aeh.pkg import GradePolicy, GateRule, ScaleRule
from aeh.store import open_store
from tests.contract.grade._drive import (
    current_grades,
    graded_run,
    set_policy,
)
from tests.support.impl import GRADE_MODULE, require
from tests.support.grade_vocabulary import backdate_grades

pytestmark = [pytest.mark.contract]

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C3", "kind": "open", "scoring_model": "atomic"},
)

#: One provisional criterion in the set — scored, but not yet accepted.
_ROWS = (
    ("S-PROV", "C1", "B2", 7.0, "auto"),
    ("S-PROV", "C2", "B2", 5.0, "provisional"),
    ("S-PROV", "C3", "B1", 3.0, "auto"),
)


def test_tc_grade_c06_a_provisional_grade_is_issued_and_exportable(
    tmp_data_dir, monkeypatch
):
    """`TC-GRADE-C06` (`CT-GRADE-06`, rung 3/4) — a provisional input is issued,
    marked `provisional`, counted in the coverage's provisional class, and exported:
    the mark page carries the row with its status and its total."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    export_dir = tmp_data_dir.parent / "c06-exports"
    monkeypatch.setenv("HARNESS_GRADE_EXPORT_DIR", str(export_dir))
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-PROV",), criteria=_CRITERIA, rows=_ROWS,
            compute=False,
        )
        from tests.contract.grade._drive import set_boundaries

        set_boundaries(store, world.version, (("B", 10.0),))
        world.service.compute_all(world.run_id)
        (row,) = current_grades(world.cohort, world.run_id)
        assert row["state"] == "provisional", (
            f"the provisional-input grade reads {row['state']!r} — it is ISSUED, "
            "marked provisional (CT-GRADE-06)"
        )
        assert int(row["criteria_provisional"]) == 1 and int(row["criteria_total"]) == 3, (
            f"the coverage reads ({row['criteria_total']!r}, "
            f"{row['criteria_provisional']!r}) — the provisional criterion is named "
            "in its own class (CT-GRADE-06 with CT-GRADE-04)"
        )
        assert float(row["total"]) == 15.0 and row["grade"], (
            f"the grade delivered ({row['total']!r}, {row['grade']!r}) — the "
            "provisional criterion's OWN figure is in the total, and a band "
            "resolves beside it"
        )
        # Exportable: the module's own page carries the provisional row.
        path = world.service.export(world.run_id, 1, "csv")
        with path.open(newline="", encoding="utf-8") as handle:
            rendered = list(csv.DictReader(handle))
        assert len(rendered) == 1 and rendered[0]["state"] == "provisional", (
            f"the export renders {rendered!r} — the provisional grade must reach "
            "the page with its status, not hide in the ledger (CT-GRADE-06)"
        )
        assert rendered[0]["total"], (
            "the exported provisional row lost its total (CT-GRADE-06)"
        )
    finally:
        store.close()


def test_tc_grade_c06_no_configuration_lets_a_provisional_input_withhold(
    tmp_data_dir,
):
    """`TC-GRADE-C06`'s decisive negative (`CT-GRADE-06`, rung 3) — swept across the
    policy vocabulary, a grade carrying a provisional input is always DELIVERED:
    a present total, a state that is never `incomplete` (that state belongs to
    ingestion failure alone, `CT-GRADE-08`), and a live row in the current-grades
    read. A withheld grade is the caution that misleads — RISK-11."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-PROV",), criteria=_CRITERIA, rows=_ROWS,
            compute=False,  # each shape is installed before its pass
        )
        shapes = [
            ("bare sum", GradePolicy()),
            ("provisional weighted", GradePolicy(
                weights=(("C2", 2.0),),
            )),
            ("scaled", GradePolicy(scale=ScaleRule(factor=1.5))),
            ("rounded", GradePolicy(rounding="nearest", decimals=0)),
            ("best k of n", GradePolicy(combination="best_k_of_n", k=2)),
            ("drop lowest", GradePolicy(combination="drop_lowest_n", drop=1)),
            ("gate met on the auto criterion", GradePolicy(
                gate=GateRule(criterion_id="C1", minimum=1.0),
            )),
            ("open window 48h", GradePolicy(review_window_hours=48)),
            ("null window", GradePolicy(review_window_hours=None)),
        ]
        for label, policy in shapes:
            set_policy(store, world.version, policy)
            world.service.compute_all(world.run_id)
            rows = current_grades(world.cohort, world.run_id)
            assert len(rows) == 1 and rows[0]["submission_id"] == "S-PROV", (
                f"{label}: the current-grades read holds {rows!r} — the grade was "
                "withheld: a provisional input must never stop a grade from "
                "being issued (CT-GRADE-06's decisive negative, RISK-11)"
            )
            row = rows[0]
            assert row["total"] is not None, (
                f"{label}: the grade's total is NULL — a withheld figure is the "
                "withholding path the clause forbids (CT-GRADE-06, RISK-11)"
            )
            assert row["state"] in ("provisional", "final"), (
                f"{label}: the state reads {row['state']!r} — judgment uncertainty "
                "never reads `incomplete`, which is ingestion failure's state alone "
                "(CT-GRADE-06 with CT-GRADE-08)"
            )
            assert int(row["criteria_provisional"]) == 1, (
                f"{label}: the provisional class lost its criterion "
                f"({row['criteria_provisional']!r}) — the mark rides with its "
                "coverage record (CT-GRADE-04's counters)"
            )
    finally:
        store.close()


def test_tc_grade_c06_an_open_window_delays_finalization_only(tmp_data_dir):
    """`TC-GRADE-C06`'s window limb (`CT-GRADE-06`, rung 3) — during an open review
    window the grade is complete, visible and delivered; the lapse settles the SAME
    revision in place — no new revision, because finalization is a settlement, not a
    recomputation."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-PROV",), criteria=_CRITERIA, rows=_ROWS,
            compute=False,
        )
        from tests.contract.grade._drive import set_policy as _install

        _install_policy(store, world.version, GradePolicy(review_window_hours=48))
        world.service.compute_all(world.run_id)
        (open_row,) = current_grades(world.cohort, world.run_id)
        assert open_row["state"] == "provisional" and float(open_row["total"]) == 15.0, (
            f"fixture bug: the open-window grade is ({open_row['state']!r}, "
            f"{open_row['total']!r}) — issued and complete during the window"
        )
        assert open_row["finalized_at"] is None, (
            "the open-window grade is already finalized — the window must delay "
            "finalization, not be ignored (CT-GRADE-06)"
        )

        # The lapse: the window is measured from issuance's timestamp; the disclosed
        # stand-in writes it backwards, past the window's edge.
        backdate_grades(world.cohort, _hours_ago(72))
        world.service.compute_all(world.run_id)
        (settled_row,) = current_grades(world.cohort, world.run_id)
        assert settled_row["state"] == "final" and settled_row["finalized_at"], (
            f"the lapsed window did not settle ({settled_row['state']!r}) — the "
            "configured lapse is a finalization path (CT-GRADE-06 with FR-GRADE-10)"
        )
        assert settled_row["revision"] == open_row["revision"], (
            f"the lapse minted a new revision ({settled_row['revision']!r} after "
            f"{open_row['revision']!r}) — the window's arrow is a settlement, not "
            "a new computation (CT-GRADE-06's delays-finalization-only clause)"
        )
    finally:
        store.close()


def _install_policy(store, version, policy):
    """The pass's policy shape — the drive's `set_policy`, aliased here so the
    window test's install reads apart from the sweep's loop variable."""
    set_policy(store, version, policy)


def _hours_ago(hours: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()