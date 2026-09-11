"""`TC-GRADE-C18` — the signal artifact's exact names, and the finalization paths as distinct figures (§6.11.14).

`CT-GRADE-18` (observe): "Assert emission of grades by state, `boundary_at_risk`
count, coverage distribution, amendment count, and — the clause singles it out —
**which finalization path was taken**, explicit batch action versus automatic
lapse, as distinct values rather than one counter. That distinction is how the
pilot learns whether HLD `R60`'s automatic path is actually load-bearing, so a
merged counter destroys the only evidence for a live design question."

The limbs, in the row's order:

- **the emitted artifact, names and values** (rung 3, green): the landed surface
  is `aeh.grade:record_grade_signals` (#103) flushing the durable `run_metrics`
  EAV rows. The contract case pins the artifact the row asks for — the metric
  NAMES as emitted (the integration case's token-presence is the looser half of
  the same oracle) and every VALUE reconciled to the ledger's hand count: three
  states summing to the class, the at-risk count, the five coverage counters, the
  amendment count — all read back from the durable table, not only from the
  return value, because an emitted-but-unpersisted signal set is the
  silent-failure shape.
- **the finalization paths, distinct** (rung 3, green): a fixture where BOTH
  roads actually occur — a teacher amendment settles at issuance, the explicit
  `finalize_batch` action settles the windowed remainder — and the artifact
  carries FOUR distinct names (`settled_at_issuance`, `settled_after_issuance`,
  `awaiting_settlement`, and the batch road's own `finalization_path_batch`,
  written by the action itself because the ledger cannot attribute it), with the
  figures DISCTINCT and reconciling: the batch road's figure equals the action's
  own record and differs from the at-issuance road's. One merged counter would
  read the same number for a design question with different answers.

Isolation: rung 3 — real store, real package, real Tier D metrics table. The
socket guard is autouse; `criterion_score` rows are the vocabulary's disclosed
`M-AGG` stand-in; the at-risk row is C05's declared-band-span manufacture (the
provisional criterion's declared span reaches across a floor). The two
`incomplete` grades are the disclosed missing-input manufacture (a criterion
with no row).
"""

from __future__ import annotations

import pytest

from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.contract.grade._drive import graded_run, set_boundaries
from tests.support.impl import GRADE_MODULE, require

pytestmark = [pytest.mark.contract]

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)

#: The floors sit so S-B's total 63.5 can fall across the 63.0 floor (its C2 is
#: provisional with declared span [0.0, 4.0] — the C05 manufacture) and S-A's
#: amended total cannot.
_CUTS = (("B", 63.0),)

def _build_run_with_both_finalization_roads(store):
    """Five submissions whose current revisions span every signal: one settled at
    issuance by a teacher amendment, two settled by the explicit batch action (one
    of them boundary-flagged), two incomplete past any settlement. Returns the
    world and the batch action's own record, so the figures reconcile to BOTH."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    world = graded_run(
        store,
        submissions=("S-A", "S-B", "S-C", "S-D", "S-E"),
        criteria=_CRITERIA,
        rows=[
            ("S-A", "C1", "B2", 7.0, "auto"),
            ("S-A", "C2", "B2", 5.0, "auto"),
            ("S-B", "C1", "B2", 60.0, "auto"),
            ("S-B", "C2", "B1", 3.5, "provisional"),
            ("S-C", "C1", "B2", 7.0, "auto"),
            ("S-C", "C2", "B2", 5.0, "auto"),
            ("S-D", "C1", "B2", 7.0, "auto"),
            ("S-E", "C1", "B2", 7.0, "auto"),
            # S-D and S-E's C2 never scored — the incomplete class.
        ],
        compute=False,  # the declarations must exist before the one pass
    )
    set_boundaries(store, world.version, _CUTS)
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    for ordinal, points in enumerate((0.0, 4.0)):
        catalog.add_band(world.version, "C2", ordinal, f"SP{ordinal}", points)
    world.service.compute_all(world.run_id)
    # Road 1, at issuance: the teacher's amendment settles that revision the
    # moment it is issued (finalized_at == computed_at).
    world.service.amend(
        world.run_id, "S-A", {"C1": 10.0}, actor="teacher-1", reason="band move",
    )
    # Road 2, explicit batch action: settles the remaining provisionals (S-B, S-C).
    record = world.service.finalize_batch(world.run_id, actor="operator-7")
    return world, record


def test_tc_grade_c18_the_emitted_artifact_names_every_figure_with_the_ledgers_value(
    tmp_data_dir,
):
    """`TC-GRADE-C18` (`CT-GRADE-18`, rung 3) — the signal artifact's exact metric
    names, and every value reconciled to the ledger's hand count, read back from the
    durable table: the states sum to the class, the at-risk count names the flagged
    grade, the coverage counters sum the five-counter distribution, the amendment
    count names the trail."""
    record_grade_signals = require(
        GRADE_MODULE, "record_grade_signals", issue="#103"
    )
    store = open_store(tmp_data_dir)
    try:
        world, _record = _build_run_with_both_finalization_roads(store)
        emitted = record_grade_signals(world.run_id, store=store)

        # The NAMES: the derived flush carries the concept list exactly — grades
        # by state (per state literal), the boundary count, the coverage
        # distribution's five counters, the derivation's three finalization
        # paths, the amendment count. The batch road's own figure is NOT among
        # the derived set — the action writes it itself — so the durable table
        # carries one more name than the return value does.
        assert set(emitted) == {
            "grades_by_state_incomplete",
            "grades_by_state_provisional",
            "grades_by_state_final",
            "boundary_at_risk_count",
            "coverage_criteria_total",
            "coverage_criteria_auto",
            "coverage_criteria_reviewed",
            "coverage_criteria_provisional",
            "coverage_criteria_missing",
            "finalization_path_settled_at_issuance",
            "finalization_path_settled_after_issuance",
            "finalization_path_awaiting_settlement",
            "amendment_count",
        }, (
            f"the emitted metric names are {sorted(emitted)!r} — the signal set "
            "must carry every CT-GRADE-18 figure under a queryable name "
            "(CT-GRADE-18's names oracle)"
        )

        # The VALUES, hand-computed from the fixture the clause's reader can audit:
        # S-A settled at issuance by the amendment; S-B batch-settled and
        # boundary-flagged; S-C batch-settled clean; S-D and S-E incomplete
        # (their C2 never scored).
        expected = {
            "grades_by_state_final": 3.0,
            "grades_by_state_incomplete": 2.0,
            "grades_by_state_provisional": 0.0,
            "boundary_at_risk_count": 1.0,
            "coverage_criteria_total": 10.0,
            "coverage_criteria_auto": 7.0,
            "coverage_criteria_reviewed": 0.0,
            "coverage_criteria_provisional": 1.0,
            "coverage_criteria_missing": 2.0,
            "amendment_count": 1.0,
            "finalization_path_batch": 2.0,
            "finalization_path_settled_at_issuance": 1.0,
            "finalization_path_settled_after_issuance": 2.0,
            "finalization_path_awaiting_settlement": 2.0,
        }
        for name, value in expected.items():
            if name == "finalization_path_batch":
                continue  # the action's own row — checked in the persisted set
            assert emitted[name] == value, (
                f"the {name} signal reads {emitted[name]!r}, expected {value!r} — "
                "a signal whose figure disagrees with the ledger's hand count is "
                "the silent-failure shape (CT-GRADE-18's value oracle)"
            )

        # The artifact half: the figures PERSIST — the durable `run_metrics` EAV
        # rows read back the same values, or the emission was a returned promise
        # over an empty table.
        persisted = {
            row["metric"]: row["value"]
            for row in store.durable().query(
                "SELECT metric, value FROM run_metrics WHERE run_id = :r",
                r=world.run_id,
            )
        }
        assert persisted == expected, (
            f"the durable run_metrics read back {persisted!r}, expected "
            f"{expected!r} — the signal set must land in the EAV table, the "
            "write contract every other stage's figures ride (CT-GRADE-18)"
        )

        # The reconciliation: each family's figures cover the whole class —
        # 3 final + 0 provisional + 2 incomplete = 5.
        assert (
            emitted["grades_by_state_final"]
            + emitted["grades_by_state_provisional"]
            + emitted["grades_by_state_incomplete"]
        ) == 5.0, (
            "the grades-by-state figures do not sum to the class — a state signal "
            "that loses submissions is a counter, not a census (CT-GRADE-18)"
        )
    finally:
        store.close()


def test_tc_grade_c18_the_finalization_paths_are_distinct_figures_not_one_counter(
    tmp_data_dir,
):
    """`TC-GRADE-C18`'s singled-out limb (`CT-GRADE-18`, rung 3) — which
    finalization path was taken is carried as FOUR distinct named figures: the
    amendment's at-issuance settlement, the batch action's own count (its figure
    equals the action's record and differs from the at-issuance road's), the
    derived after-issuance figure, and the awaiting class. One merged counter
    would read the same number for a design question with different answers —
    HLD `R60`'s evidence."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    record_grade_signals = require(
        GRADE_MODULE, "record_grade_signals", issue="#103"
    )
    store = open_store(tmp_data_dir)
    try:
        world, record = _build_run_with_both_finalization_roads(store)
        record_grade_signals(world.run_id, store=store)
        # The pilot's surface is the durable table: the derived roads land by
        # the flush, the batch road's figure is the ACTION's own write — so
        # the paths are read where they all land.
        metrics = {
            row["metric"]: row["value"]
            for row in store.durable().query(
                "SELECT metric, value FROM run_metrics WHERE run_id = :r",
                r=world.run_id,
            )
        }

        # The roads have DISTINCT NAMES — a merged counter destroys the only
        # evidence for whether the automatic path is load-bearing.
        path_names = {
            "finalization_path_settled_at_issuance",
            "finalization_path_settled_after_issuance",
            "finalization_path_awaiting_settlement",
            "finalization_path_batch",
        }
        assert path_names <= set(metrics), (
            f"the finalization paths ride {sorted(set(metrics) & path_names)!r} — "
            "the clause singles out WHICH path was taken: explicit batch action "
            "versus automatic lapse are distinct values, not one counter "
            "(CT-GRADE-18's singled-out limb)"
        )
        # ... and DISTINCT VALUES, each reconciled to its road's own evidence:
        # the amendment settled one grade at issuance (its finalized_at equals
        # its computed_at); the batch action settled two (its figure is the
        # action's own record); the two incompletes await.
        at_issuance = metrics["finalization_path_settled_at_issuance"]
        after_issuance = metrics["finalization_path_settled_after_issuance"]
        awaiting = metrics["finalization_path_awaiting_settlement"]
        batch = metrics["finalization_path_batch"]
        assert batch == float(record.finalized) == 2.0, (
            f"the batch figure reads {batch!r} against the action's record "
            f"{record.finalized!r} — the batch road's figure is the action's own "
            "count, not a share of a merged total (CT-GRADE-18)"
        )
        assert at_issuance == 1.0, (
            f"the at-issuance figure reads {at_issuance!r} — the amendment's "
            "settlement is its own road, its figure its own (CT-GRADE-18)"
        )
        assert batch != at_issuance and awaiting != at_issuance, (
            f"the path figures read ({at_issuance!r}, {after_issuance!r}, "
            f"{awaiting!r}, {batch!r}) — a pilot reading them learns the batch "
            "road carried TWO settlements and the amendment road ONE; a merged "
            "counter would report 5 and answer nothing (CT-GRADE-18)"
        )
        # The split covers the class — the distinct figures partition, not
        # overlap: every grade is accounted on exactly one road.
        assert (at_issuance + after_issuance + awaiting) == 5.0, (
            "the finalization-path figures do not cover the class — the roads' "
            "distinct values must sum to the population they classify "
            "(CT-GRADE-18)"
        )
        # The ledger evidence the figures derive from: the at-issuance row's
        # stamps agree, the batch-settled row's do not — the distinctness is
        # real settlement evidence, not a naming convention.
        rows = {
            row["submission_id"]: row
            for row in world.cohort.query(
                "SELECT submission_id, state, finalized_at, computed_at "
                "FROM submission_grade WHERE is_current = 1"
            )
        }
        assert rows["S-A"]["finalized_at"] == rows["S-A"]["computed_at"], (
            "fixture bug: the amended grade did not settle at issuance"
        )
        assert rows["S-B"]["finalized_at"] != rows["S-B"]["computed_at"], (
            "fixture bug: the batch-settled grade's stamps should differ"
        )
    finally:
        store.close()