"""`TC-GRADE-C08` — `incomplete` is ingestion failure's state alone, and it names its inputs (§6.11.14).

`CT-GRADE-08` (data): "Assert `incomplete` is set **only** when `criteria_missing >
0` — both directions — that it **names the specific missing inputs** rather than a
count alone, and that it routes to the **operator as a rescan**, never to the
teacher as a marking decision. Then the conflation the clause forbids: `incomplete`
is caused **exclusively by ingestion failure, never by judgment uncertainty**, so
the case asserts at rung 3 that consumers do not conflate it with `provisional`.
Two different problems with two different owners; merging them sends scanner faults
to the teacher (`CT-GRADE-08`)."

The limbs, in the row's order:

- **the biconditional, both directions** (rung 3, green): every delivered grade
  with `criteria_missing > 0` reads `incomplete`, and every grade reading
  `incomplete` has `criteria_missing > 0` — a mixed cohort exercises both arrows at
  once, and the completion arrow adds the never-settled half: present inputs
  settle on completion, the ingestion failure does not.
- **the naming clause** (rung 3, green): `missing_criteria` names the specific
  inputs — not a count alone — matching the criterion rows' actual absences.
- **the owner routing** (rung 3, green): the absent criterion's queue item is the
  operator's rescan, never a teacher marking decision.
- **the consumer differential** (rung 3, green): the two states ride DIFFERENT
  paths — `provisional` grades carry their unsettled criterion in
  `criteria_provisional` with NO operator item, `incomplete` grades carry the
  rescan item. The failure the clause forbids is the conflation: scanner faults
  sent to the teacher as marking work.

Isolation: rung 3 — real store, real package, real service. The socket guard is
autouse; `criterion_score` rows are the vocabulary's disclosed `M-AGG` stand-in.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
from tests.contract.grade._drive import complete_run, current_grades, graded_run
from tests.support.impl import GRADE_MODULE, require

pytestmark = [pytest.mark.contract]

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)

#: A cohort where both states arise in one run: S-GONE is missing an input
#: (ingestion failure), S-PROV has a scored-but-unaccepted criterion (judgment
#: uncertainty), S-FULL is fully scored.
_ROWS = (
    ("S-GONE", "C1", "B2", 7.0, "auto"),
    # S-GONE's C2: no row at all — the ingestion failure.
    ("S-PROV", "C1", "B2", 7.0, "auto"),
    ("S-PROV", "C2", "B2", 5.0, "provisional"),
    ("S-FULL", "C1", "B2", 7.0, "auto"),
    ("S-FULL", "C2", "B3", 4.0, "auto"),
)

#: States on a PENDING run (null window: completion is the only settle path):
#: the ingestion failure reads incomplete; scored-but-unaccepted reads
#: provisional; a fully-scored submission on a pending run is issued provisional
#: until completion settles it.
_EXPECTED_STATES = {
    "S-GONE": "incomplete", "S-PROV": "provisional", "S-FULL": "provisional"
}


def _queue_for(cohort, submission_id):
    return cohort.query(
        "SELECT queue_id, criterion_id, reason FROM review_queue "
        "WHERE submission_id = :s",
        s=submission_id,
    )


def test_tc_grade_c08_incomplete_tracks_missing_in_both_directions(tmp_data_dir):
    """`TC-GRADE-C08` (`CT-GRADE-08`, rung 3) — the biconditional over a mixed
    cohort: every grade with a missing criterion reads `incomplete` and names the
    specific inputs; every grade reading `incomplete` has a missing criterion; the
    present-input twins never read `incomplete`; and on run completion the
    present-input grades settle while the ingestion failure does NOT — `incomplete`
    is never settled."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=tuple(_EXPECTED_STATES),
            criteria=_CRITERIA,
            rows=_ROWS,
        )
        grades = {
            row["submission_id"]: row
            for row in current_grades(world.cohort, world.run_id)
        }
        assert set(grades) == set(_EXPECTED_STATES), (
            "fixture bug: the mixed cohort did not deliver one grade per submission"
        )
        for sid, state in _EXPECTED_STATES.items():
            row = grades[sid]
            assert row["state"] == state, (
                f"{sid}: state {row['state']!r}, expected {state!r} — the state "
                "model's three literals must partition the cohort by input "
                "condition (CT-GRADE-08's biconditional)"
            )
            missing_count = int(row["criteria_missing"])
            named = __import__("json").loads(row["missing_criteria"])
            # Direction 1: missing > 0  <=>  incomplete.
            if state == "incomplete":
                assert missing_count > 0 and named, (
                    f"{sid} reads incomplete with no missing criterion — the "
                    "incomplete state is set ONLY when criteria_missing > 0 "
                    "(CT-GRADE-08's biconditional, direction 1)"
                )
                assert named == ["C2"], (
                    f"{sid} names {named!r} missing — the record names the SPECIFIC "
                    "missing inputs, not a count alone (CT-GRADE-08)"
                )
            else:
                assert missing_count == 0, (
                    f"{sid} reads {state!r} with {missing_count} missing — a grade "
                    "whose inputs are present is never incomplete (CT-GRADE-08's "
                    "biconditional, direction 2)"
                )

        # The completion arrow: the run completes — the present-input grades
        # settle, the ingestion failure does NOT. `incomplete` is never settled:
        # it is a missing input awaiting an operator, not a deliverable awaiting
        # a window.
        complete_run(world.cohort, world.run_id)
        world.service.compute_all(world.run_id)
        settled = {
            row["submission_id"]: row
            for row in current_grades(world.cohort, world.run_id)
        }
        assert settled["S-FULL"]["state"] == "final", (
            f"the completed run left the fully-scored submission at "
            f"{settled['S-FULL']['state']!r} — completion is the settle path for "
            "present inputs (FR-GRADE-10)"
        )
        assert settled["S-GONE"]["state"] == "incomplete", (
            f"the ingestion failure settled to {settled['S-GONE']['state']!r} on "
            "run completion — an incomplete grade is not a deliverable awaiting a "
            "window, it is a missing input awaiting an operator (CT-GRADE-08: "
            "incomplete is never settled)"
        )
    finally:
        store.close()


def test_tc_grade_c08_the_two_states_take_their_own_owners(tmp_data_dir):
    """`TC-GRADE-C08`'s routing and consumer limbs (`CT-GRADE-08`, rung 3) — the
    owner differential: the ingestion failure routes to the OPERATOR as a rescan;
    the judgment uncertainty queues NOTHING and stays with the grade as
    `provisional`. Merging the two sends scanner faults to the teacher — the
    conflation the clause exists to forbid."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=tuple(_EXPECTED_STATES),
            criteria=_CRITERIA,
            rows=_ROWS,
        )
        cohort = world.cohort
        # The ingestion failure's item: the operator's rescan, never the teacher's.
        gone_items = _queue_for(cohort, "S-GONE")
        assert len(gone_items) == 1 and gone_items[0]["criterion_id"] == "C2", (
            f"the missing input's queue holds "
            f"{[(i['criterion_id'], i['reason']) for i in gone_items]!r} "
            "— one operator item for the absent criterion (CT-GRADE-08)"
        )
        reason = str(gone_items[0]["reason"]).lower()
        assert "rescan" in reason and "mark" not in reason, (
            f"the missing input routes as {gone_items[0]['reason']!r} — an ingestion "
            "failure is the OPERATOR's rescan, never a teacher marking decision "
            "(CT-GRADE-08's owner clause)"
        )
        # The judgment uncertainty's half: no queue item, and the state names the
        # difference — the two problems take two different paths.
        prov_items = _queue_for(cohort, "S-PROV")
        assert prov_items == [], (
            f"the provisional criterion queued {prov_items!r} — judgment "
            "uncertainty is not an operator item: the two problems have two "
            "different owners (CT-GRADE-08's conflation clause)"
        )
        assert _queue_for(cohort, "S-FULL") == [], (
            "the fully-scored twin queued an item — a complete submission routes "
            "nowhere (fixture differential)"
        )
    finally:
        store.close()