"""`TC-ORCH-26` (`FR-ORCH-23`, `CT-ORCH-10`, `R63`; artifact assertion / rung 2,
P0) — the `ProgressReport` type and a live progress query: counts by
`(stage, criterion, judge)` plus done / in-flight / pending / quarantined
totals, and **no per-student completion figure exists on the type**, asserted by
field enumeration (**landed with #62**).

`FR-ORCH-23` exposes progress and simultaneously forbids exposing per-student
completion (`R63` pairs it with `FR-CONSOLE-08`: the data must not exist to
render). The two oracles, exactly as the plan states them:

- **Field enumeration** — the type's field set is enumerated and asserted:
  the design's `ProgressReport` (§3.7 M-ORCH Interfaces) carries the position
  and count fields and deliberately no per-student field. Set equality, not
  subset: an added per-student field fails, and so does a renamed count the
  console reads.
- **Live query** — a real ledger in a known state (every unit done except six
  score units quarantined by the shipped fail ladder), read back through
  `progress()` and hand-counted against the ledger's own rows: the report
  counts the WHOLE ledger, not a sample (`CT-ORCH-09`: the ledger grows during
  a run, so a consumer computing progress from the initial count is wrong).

**Interface this file assumes of #62** — shipped exactly as assumed (the same
shape `test_failure_visibility.py` — `TC-ORCH-31` — assumes; the design
reasoning stays):

| Name | Status |
|---|---|
| `Orchestrator.progress(run_id)` | design §3.7 Protocol member #62 ships; called on the instance |
| `report["done"] / ["pending"] / ["in_flight"] / ["quarantined"]` | the four totals, flat on the report |
| `report["by_unit"]` | the counts by `(stage, criterion, judge)` — keyed by that triple |
| `aeh.orch:ProgressReport` | the §3.7 dataclass the field enumeration runs over; shipped with #62 |

**How the two halves' shapes coexist (disclosed deliberately).** The type half
enumerates `dataclasses.fields(ProgressReport)`; the query half reads mapping
access on `progress()`'s return and a `by_unit` key that is NOT among the
declared fields. Both pass together only if the returned object is the §3.7
dataclass WITH mapping behavior (or #62 returns a mapping view beside it), with
`by_unit` riding outside the field set — the same mapping assumption
`test_failure_visibility.py` makes, so #62 reconciles all three surfaces in one
pass. A `progress()` that returns a bare dataclass with neither mapping behavior
nor a companion view fails the query half on purpose: the mapping is the
operator surface the console reads.

Isolation: rung 2 — real store, real Tier P package, real cohort ledger; the
driver plays the workers (lease / complete / fail are the shipped worker
surface, #58); no doubles.
"""

from __future__ import annotations

import dataclasses

import pytest

from aeh.orch import WorkError
from aeh.store import open_store
from tests.support.impl import ORCH_MODULE, require, require_attr
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration]

ISSUE = "#62"

_SUBMISSIONS = tuple(f"SYN-{i:03d}" for i in range(1, 7))
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "holistic"},
)
#: Every submission whose score units COMPLETE — all but SYN-003, whose units
#: (2 criteria x 3 judges = 6) ride the fail ladder into `quarantined`.
_DONE_SUBMISSIONS = frozenset({"SYN-001", "SYN-002", "SYN-004", "SYN-005", "SYN-006"})

#: The §3.7 dataclass, field for field. Set equality is the oracle: a field
#: added here that the design did not declare — per-student above all — fails
#: the case, and a count the console needs that went missing fails it too.
DESIGNED_FIELDS = (
    "stage",
    "criterion_index",
    "criterion_total",
    "judge_index",
    "judge_total",
    "done",
    "in_flight",
    "pending",
    "quarantined",
    "escalation_rate_so_far",
    "estimated_completion",
)


def _ledger_counts(store: object, run_id: str) -> dict:
    """Hand-counted totals off the ledger's own rows — the truth the report
    must reconcile to."""
    rows = store.cohort(ORCH_COHORT_ID).query(
        "SELECT status, stage, criterion_id, judge_id FROM work_unit "
        "WHERE run_id = :r",
        r=run_id,
    )
    counts: dict = {"done": 0, "pending": 0, "leased": 0, "quarantined": 0}
    by_unit: dict = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        key = (row["stage"], row["criterion_id"], row["judge_id"])
        by_unit[key] = by_unit.get(key, 0) + 1
    counts["by_unit"] = by_unit
    return counts


def test_tc_orch_26_progress_report_type_has_no_per_student_field():
    """`TC-ORCH-26` type half — the `ProgressReport` field set, enumerated:
    exactly the designed fields, and none of them a per-student completion
    figure (FR-ORCH-23's prohibition, asserted structurally)."""
    ProgressReport = require(ORCH_MODULE, "ProgressReport", issue=ISSUE)
    require_attr(
        require(ORCH_MODULE, "Orchestrator", issue=ISSUE), "progress", issue=ISSUE
    )

    actual = tuple(f.name for f in dataclasses.fields(ProgressReport))
    assert actual == DESIGNED_FIELDS, (
        f"ProgressReport's fields are {actual}, the design declares "
        f"{DESIGNED_FIELDS} — an added field must be a design change asserted "
        "here, and a per-student completion figure is the one field R63 exists "
        "to keep off this type"
    )
    offenders = [
        name for name in actual if "student" in name or "learner" in name
    ]
    assert not offenders, (
        f"ProgressReport carries per-student-shaped field(s) {offenders} — "
        "FR-ORCH-23: no per-student completion figure exists on the type, "
        "so the console cannot render one (R63)"
    )


def test_tc_orch_26_live_progress_query_matches_the_ledger(tmp_data_dir):
    """`TC-ORCH-26` query half — a ledger in a known state (every extract unit
    done; every score unit done except SYN-003's six, which quarantined by the
    shipped three-fail ladder): `progress()` reports the
    same counts a hand-count of the ledger's rows produces, by total and by
    `(stage, criterion, judge)`."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    require_attr(Orchestrator, "progress", issue=ISSUE)

    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _version = seed_run(
            store,
            submissions=_SUBMISSIONS,
            criteria=_CRITERIA,
            panel=None,  # orch_cfg's default: the three-judge edge panel
        )
        orch.enumerate_units(run_id)

        # Extract units complete (the deterministic stage is empty in this
        # all-open fixture), which unlocks Sweep 2.
        for stage in ("extract", "deterministic"):
            while True:
                batch = orch.lease("report-worker", stage, 64)
                if not batch:
                    break
                for unit in batch:
                    orch.complete(unit.work_id)

        # Score units: every submission completes except SYN-003, whose units
        # ride the shipped fail ladder — one fail per lease round, three
        # rounds, so each ends `quarantined` (FR-ORCH-18) with the run none
        # the wiser.
        for _round in range(3):
            while True:
                batch = orch.lease("report-worker", "score", 64)
                if not batch:
                    break
                for unit in batch:
                    if unit.submission_id in _DONE_SUBMISSIONS:
                        orch.complete(unit.work_id)
                    else:
                        orch.fail(
                            unit.work_id,
                            WorkError(message="injected: the quarantine leg"),
                        )

        expected = _ledger_counts(store, run_id)
        assert expected["quarantined"] == 6, (
            f"fixture precondition: expected 6 quarantined score units "
            f"(3 judges x 2 criteria for SYN-003), the ledger holds "
            f"{expected['quarantined']}"
        )
        assert expected["leased"] == 0 and expected["pending"] == 0, (
            f"fixture precondition: every unit should be done or quarantined, "
            f"the ledger holds {expected}"
        )

        report = orch.progress(run_id)

        assert report["done"] == expected["done"], (
            f"progress reports done={report['done']}, the ledger counts "
            f"{expected['done']} — the report must count the whole ledger "
            "(CT-ORCH-09), and a done total that drifts misleads every consumer"
        )
        assert report["quarantined"] == expected["quarantined"], (
            f"progress reports quarantined={report['quarantined']}, the ledger "
            f"counts {expected['quarantined']} — the quarantined leg of the "
            "fixture must be visible on the operator surface (FR-ORCH-18)"
        )
        assert report["pending"] == expected["pending"], (
            f"progress reports pending={report['pending']}, the ledger counts "
            f"{expected['pending']}"
        )
        assert report["in_flight"] == expected["leased"], (
            f"progress reports in_flight={report['in_flight']}, the ledger "
            f"counts {expected['leased']} leased"
        )
        assert report["by_unit"] == expected["by_unit"], (
            f"progress's per-(stage, criterion, judge) counts {report['by_unit']} "
            f"do not reconcile to the ledger's {expected['by_unit']} — "
            "FR-ORCH-23's granularity is the (stage, criterion, judge) triple, "
            "not a bare total"
        )
        exposed_keys = [str(key) for key in report.keys()]
        assert not any("student" in key for key in exposed_keys), (
            f"the live report exposes student-keyed view(s) {exposed_keys} — "
            "the prohibition is not only on the type but on what a query "
            "returns (FR-ORCH-23)"
        )
    finally:
        store.close()
