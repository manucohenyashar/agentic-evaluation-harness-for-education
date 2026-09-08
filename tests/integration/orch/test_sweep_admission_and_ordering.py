"""`TC-ORCH-25`, `TC-ORCH-06`, `TC-ORCH-07`, `TC-ORCH-08` — the admission filter and the
two-sweep execution plan.

- `TC-ORCH-25` (`FR-ORCH-22`, integration / rung 2): submissions with each `ingest_status`
  value — only `ok` and `low_confidence_ocr` enter Sweep 1; a quarantined submission
  generates no scoring work until re-ingested, after which it does. Oracle: **exact
  enumeration**.
- `TC-ORCH-06` (`FR-ORCH-05`, integration / rung 2): a package with the dependency chain
  c2 → c4 → c7 and two independent criteria. Sweep 1 units are enumerated over judged
  criteria only and dispatched in topological order; a deterministic criterion produces no
  extraction unit. Oracle: order assertion plus exact enumeration.
- `TC-ORCH-07` (`FR-ORCH-06`, integration / rung 2): the same package, with c2's
  extraction incomplete. Sweep 2 for c4 does not begin until every extraction c4 depends
  on is `done`; once it does, Sweep 2 carries **no** dependency ordering — asserted by
  confirming its order is driven purely by the `FR-ORCH-07` key. Oracle: ordering
  invariant.
- `TC-ORCH-08` (`FR-ORCH-07`, integration / rung 3): the same run on `edge-local` and on
  `dev-ci`. Sweep 2 order is judge, then question, then criterion, then parallel over
  submissions, on **both** profiles; the two execution traces are comparable. Oracle:
  differential across profiles.

**Dispatch order is observed through `lease`.** The sweeps have no other observable
surface: a worker's lease probes *are* the execution trace. `_lease_one_by_one` claims one
unit at a time until the stage runs dry and returns the units in the order they were
handed out.

**Written ahead of #59** (the two-sweep plan, dependency ordering, deterministic-unit
admission and the `ingest_status` filter). Registered in `WRITTEN_AHEAD_BLOCKERS`:

- `TC-ORCH-25` on `aeh.orch:SWEEP1_ADMITTED_INGEST_STATUSES` — the admission set is the
  one inspectable name the filter needs (`CT-INGEST-11` lets `M-ORCH` treat
  {`ok`, `low_confidence_ocr`} as the complete admission rule, so the set is a constant,
  not a query).
- `TC-ORCH-06/07/08` on the **conjunction** `Orchestrator.lease` +
  `SWEEP1_ADMITTED_INGEST_STATUSES`: the ordering cases are observable only through
  `lease` (#58's), and #59's acceptance criteria bundle the admission filter with the
  sweep plan, so the conjunction fires when the story lands. The name is one the tests
  invent and use together (the TS-56 reasoning); if #59 ships the filter under a different
  name, the rename here and in the registry is one visible line.

**Interface this case assumes of #58/#59**, listed so it is reconciled deliberately
(the `record_run_start` precedent):

| Name | Status |
|---|---|
| `Orchestrator.lease(worker_id, stage, n)` | design §3.7 Interfaces; returns a sequence of claimed units (the ledger's `WorkUnit` rows), empty when nothing is claimable |
| `SWEEP1_ADMITTED_INGEST_STATUSES` | **assumed here** — the admission set as a module constant |
| criterion `question_id` from the catalog | shipped (`PackageCatalog.add_criterion`); `work_unit` does not carry it, so Sweep 2's question key is read from the package the run names |

**Disclosed stand-ins.** Marking extraction units `done` writes the ledger directly: the
complete surface that does this in production is #58's, and the rows written are exactly
the rows it will write (`work_unit.status`). Re-ingesting the quarantined submission
writes `ingest_status = 'ok'` (and clears `quarantined`) directly — the re-ingest pass's
own row update (`update_submission_gates`). No production module may write these rows
(`CT-ORCH-17`); this is test scaffolding standing in for their writers.

**What the admission assertions deliberately do not pin:** the requirement scopes the
filter to Sweep 1 and to *scoring* work (`FR-ORCH-22`, `CT-INGEST-11`); whether the
`deterministic` stage admits by the same rule is #59's to reconcile, and these tests do
not bet on it — the deterministic units of non-admitted submissions are unasserted here
(their extract and score units are not).
"""

from __future__ import annotations

import aeh.ingest  # noqa: F401 — registers the ingest migration that adds the
# submission's ingest_status/quarantined columns; without it a targeted run of this file
# applies cohort migrations [1, 7] only and the fixture UPDATEs hit "no such column".
import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.orch import Orchestrator
from aeh.store import open_store
from tests.support.conf_builders import (
    EDGE_PANEL_3,
    HOSTED_PANEL_3,
    edge_cfg,
    hosted_cfg,
)
from tests.support.impl import ORCH_MODULE, require
from tests.support.orch_run import (
    ORCH_COHORT_ID,
    seed_cohort,
    seed_package,
    seed_run,
)

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#59"

# --- TC-ORCH-25: one submission per ingest_status value --------------------------------------
#
# The five values are the migration's own CHECK set (ingest migration). `unreadable` is
# the one ingest quarantines, so it carries the quarantine flag the plan's "a quarantined
# submission" names; the other three are non-admitted without being quarantined.
_STATUS_SUBMISSIONS: tuple[tuple[str, str, int], ...] = (
    ("SYN-OK", "ok", 0),
    ("SYN-LCO", "low_confidence_ocr", 0),
    ("SYN-UNR", "unreadable", 1),
    ("SYN-INC", "incomplete", 0),
    ("SYN-UMA", "unmatched_assessment", 0),
)

_ADMITTED = ("SYN-OK", "SYN-LCO")

# --- TC-ORCH-06/07: "the same package" — the chain, two independents, one deterministic -
#
# Question ids are chosen so the FR-ORCH-07 key order (c4, c2, i1, i2, c7) is NOT a
# topological order: c4's score unit dispatches before c2's despite the c2 -> c4 edge.
# That is what makes "Sweep 2 carries no dependency ordering" discriminating rather than
# vacuous — with default (equal) question ids the key order would coincide with
# alphabetical order and an alphabetical sweep could pass as key-driven.
_CHAIN_CRITERIA: tuple[dict, ...] = (
    {"criterion_id": "c2", "kind": "open", "scoring_model": "atomic",
     "question_id": "Q2"},
    {"criterion_id": "c4", "kind": "open", "scoring_model": "atomic",
     "question_id": "Q1", "dependencies": ("c2",)},
    {"criterion_id": "c7", "kind": "open", "scoring_model": "atomic",
     "question_id": "Q5", "dependencies": ("c4",)},
    # Alphabetically FIRST, topologically LAST: on c2 -> c4 -> c7 alone the topological
    # order coincides with criterion-id order (which is the order the shipped
    # enumeration walks), so a lease that ignores dependencies would pass. a1 breaks the
    # coincidence — it must dispatch after c7 despite sorting before it.
    {"criterion_id": "a1", "kind": "open", "scoring_model": "atomic",
     "question_id": "Q6", "dependencies": ("c7",)},
    {"criterion_id": "i1", "kind": "open", "scoring_model": "atomic",
     "question_id": "Q3"},
    {"criterion_id": "i2", "kind": "open", "scoring_model": "atomic",
     "question_id": "Q4"},
    {"criterion_id": "m1", "kind": "mcq"},
)

#: All-atomic package, one judge each, so every score unit shares a judge and the key
#: reduces to question -> criterion.
_EXPECTED_SCORE_ORDER = ("c4", "c2", "i1", "i2", "c7", "a1")


def _set_ingest_status(cohort_handle, submission_id: str, status: str, quarantined: int):
    """The re-ingest pass's own row update, as a disclosed stand-in."""
    with cohort_handle.transaction() as tx:
        tx.execute(
            "UPDATE submission SET ingest_status = :s, quarantined = :q "
            "WHERE submission_id = :sid",
            s=status,
            q=quarantined,
            sid=submission_id,
        )


def _complete_extracts(cohort_handle, run_id: str, exclude_criterion: str | None = None):
    """Stand-in for the complete surface (#58): flip extraction units to `done`."""
    with cohort_handle.transaction() as tx:
        if exclude_criterion is None:
            tx.execute(
                "UPDATE work_unit SET status = 'done' "
                "WHERE run_id = :r AND stage = 'extract'",
                r=run_id,
            )
        else:
            tx.execute(
                "UPDATE work_unit SET status = 'done' "
                "WHERE run_id = :r AND stage = 'extract' AND criterion_id != :c",
                r=run_id,
                c=exclude_criterion,
            )


def _reset_stage(cohort_handle, run_id: str, stage: str):
    """Return a stage's units to `pending` — scaffolding between probes, disclosed above."""
    with cohort_handle.transaction() as tx:
        tx.execute(
            "UPDATE work_unit SET status = 'pending' WHERE run_id = :r AND stage = :s",
            r=run_id,
            s=stage,
        )


def _lease_one_by_one(orchestrator, worker_id: str, stage: str, limit: int = 200) -> list:
    """Claim one unit at a time until the stage runs dry; the hand-out order is the
    dispatch order."""
    claimed: list = []
    for _ in range(limit):
        got = orchestrator.lease(worker_id, stage, 1)
        if not got:
            return claimed
        claimed.extend(got)
    raise AssertionError(
        f"lease never ran dry on stage {stage!r} after {limit} probes — a bounded run "
        "must exhaust its ledger"
    )


def _units_of(cohort_handle, run_id: str) -> list[dict]:
    return cohort_handle.query(
        "SELECT work_id, stage, criterion_id, judge_id, status FROM work_unit "
        "WHERE run_id = :r ORDER BY work_id",
        r=run_id,
    )


# ------------------------------------------------------------------------------------------
# TC-ORCH-25 — admission by ingest_status
# ------------------------------------------------------------------------------------------


def test_tc_orch_25_only_admitted_submissions_enter_sweep_1_until_reingested(
    tmp_data_dir,
):
    """`TC-ORCH-25` — only `ok` and `low_confidence_ocr` are admitted; the quarantined
    submission generates no scoring work until re-ingested, after which it does."""
    SWEEP1_ADMITTED_INGEST_STATUSES = require(
        ORCH_MODULE, "SWEEP1_ADMITTED_INGEST_STATUSES", issue=ISSUE
    )
    assert set(SWEEP1_ADMITTED_INGEST_STATUSES) == {"ok", "low_confidence_ocr"}, (
        "the admission set is not the complete rule CT-INGEST-11 states — anything "
        "beyond {ok, low_confidence_ocr} admits work ingest refused"
    )

    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store,
            submissions=tuple(sid for sid, _, _ in _STATUS_SUBMISSIONS),
            criteria=(
                {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
                {"criterion_id": "M1", "kind": "mcq"},
            ),
        )
        cohort = store.cohort("c-2026-7B-orch")
        for sid, status, quarantined in _STATUS_SUBMISSIONS:
            _set_ingest_status(cohort, sid, status, quarantined)

        orchestrator.enumerate_units(run_id)

        # Exact enumeration, per submission: an admitted submission carries the full
        # judged shape (one extract unit, one score unit — atomic, depth 1); every other
        # ingest_status carries neither.
        for sid, _, _ in _STATUS_SUBMISSIONS:
            rows = cohort.query(
                "SELECT stage, COUNT(*) AS n FROM work_unit "
                "WHERE run_id = :r AND submission_id = :s AND stage IN "
                "('extract', 'score') GROUP BY stage",
                r=run_id,
                s=sid,
            )
            counts = {row["stage"]: row["n"] for row in rows}
            if sid in _ADMITTED:
                assert counts == {"extract": 1, "score": 1}, (
                    f"{sid} (ingest_status admitted) did not get its Sweep 1 shape: "
                    f"{counts}"
                )
            else:
                assert counts == {}, (
                    f"{sid} (ingest_status not admitted) generated scoring work: "
                    f"{counts} — FR-ORCH-22 admits only ok and low_confidence_ocr"
                )

        # The quarantined submission rejoins the same run once re-ingested: the operator
        # action flips the row's status, and the next enumeration produces its work.
        _set_ingest_status(cohort, "SYN-UNR", "ok", 0)
        report = orchestrator.enumerate_units(run_id)
        assert report.units_inserted == 2, (
            f"re-ingesting the quarantined submission produced {report.units_inserted} "
            "units, expected 2 (extract + score) — it did not rejoin the same run"
        )
        rejoined = cohort.query(
            "SELECT stage, COUNT(*) AS n FROM work_unit "
            "WHERE run_id = :r AND submission_id = 'SYN-UNR' AND stage IN "
            "('extract', 'score') GROUP BY stage",
            r=run_id,
        )
        assert {row["stage"]: row["n"] for row in rejoined} == {"extract": 1, "score": 1}
    finally:
        store.close()


# ------------------------------------------------------------------------------------------
# TC-ORCH-06 — Sweep 1: judged-only, topological
# ------------------------------------------------------------------------------------------


def test_tc_orch_06_sweep1_is_judged_only_and_dispatched_topologically(tmp_data_dir):
    """`TC-ORCH-06` — extract units exist for judged criteria only and are dispatched in
    topological order over the dependency graph; the deterministic criterion produces no
    extraction unit."""
    require(ORCH_MODULE, "Orchestrator.lease", "SWEEP1_ADMITTED_INGEST_STATUSES",
            issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store, submissions=("SYN-001",), criteria=_CHAIN_CRITERIA
        )
        report = orchestrator.enumerate_units(run_id)

        cohort = store.cohort("c-2026-7B-orch")
        # Exact enumeration: 6 judged criteria x (1 extract + 1 score) + 1 deterministic.
        assert report.units_enumerated == 13, (
            f"expected 13 units (6 extract + 6 score + 1 deterministic), "
            f"got {report.units_enumerated}"
        )
        m1_rows = _units_of(cohort, run_id)
        m1_stages = [row["stage"] for row in m1_rows if row["criterion_id"] == "m1"]
        assert m1_stages == ["deterministic"], (
            f"the deterministic criterion produced stages {m1_stages} — an extraction "
            "unit for it would dispatch a judge against work M-DET owns"
        )

        # Dispatch order: the extract units are handed out in topological order — every
        # criterion before the criteria that depend on it. The independents may interleave
        # anywhere; the chain's precedence is the invariant.
        extract_order = [
            unit.criterion_id for unit in _lease_one_by_one(orchestrator, "worker-a",
                                                            "extract")
        ]
        assert sorted(extract_order) == ["a1", "c2", "c4", "c7", "i1", "i2"], (
            f"Sweep 1 handed out {extract_order} — judged criteria only, exactly one "
            "extraction unit each"
        )
        # a1 sorts before c2 but depends on c7, so id order and topological order
        # disagree — an id-ordered dispatch is not a topological one, and only the
        # second satisfies FR-ORCH-05.
        assert extract_order.index("c2") < extract_order.index("c4") < (
            extract_order.index("c7")
        ) < extract_order.index("a1"), (
            f"Sweep 1 dispatch order {extract_order} is not topological over "
            "c2 -> c4 -> c7 -> a1 — a criterion ran before the dependency it consumes"
        )
    finally:
        store.close()


# ------------------------------------------------------------------------------------------
# TC-ORCH-07 — the Sweep 2 gate, and no dependency ordering inside Sweep 2
# ------------------------------------------------------------------------------------------


def test_tc_orch_07_sweep2_gates_on_dependency_extraction_then_orders_by_key_only(
    tmp_data_dir,
):
    """`TC-ORCH-07` — with c2's extraction incomplete, Sweep 2 for c4 does not begin;
    once every extraction is done, Sweep 2's order is the FR-ORCH-07 key and nothing
    else — c4 dispatches before c2 despite c2 -> c4."""
    require(ORCH_MODULE, "Orchestrator.lease", "SWEEP1_ADMITTED_INGEST_STATUSES",
            issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store, submissions=("SYN-001",), criteria=_CHAIN_CRITERIA
        )
        orchestrator.enumerate_units(run_id)
        cohort = store.cohort("c-2026-7B-orch")

        c4_score_id = cohort.query(
            "SELECT work_id FROM work_unit WHERE run_id = :r AND criterion_id = 'c4' "
            "AND stage = 'score'",
            r=run_id,
        )[0]["work_id"]

        # Every extraction is done EXCEPT c2's — the one c4 depends on.
        _complete_extracts(cohort, run_id, exclude_criterion="c2")

        # The gate: whatever Sweep 2 can hand out right now, c4's score unit is not in it.
        # (i1/i2 depend on nothing; whether c7 — whose direct dependency c4 is extracted —
        # is claimable is a transitive-vs-direct reading the requirement does not settle,
        # so only c4's absence is asserted: it is blocked under both readings.)
        in_flight = orchestrator.lease("worker-gate", "score", 10)
        gated_ids = {unit.work_id for unit in in_flight}
        assert c4_score_id not in gated_ids, (
            "Sweep 2 for c4 began while the extraction it depends on (c2) was still "
            "pending — scoring c4 before c2's extraction exists scores a judgment "
            "over nothing"
        )

        # Now every extraction is done. Sweep 2 must run with NO dependency ordering:
        # its order is the FR-ORCH-07 key (here one judge, so question -> criterion).
        # The gate probe above may have claimed the units that were claimable, so the
        # stage is reset first (scaffolding, disclosed in the module docstring).
        _reset_stage(cohort, run_id, "score")
        _complete_extracts(cohort, run_id)
        score_order = [
            unit.criterion_id for unit in _lease_one_by_one(orchestrator, "worker-a",
                                                            "score")
        ]
        assert score_order == list(_EXPECTED_SCORE_ORDER), (
            f"Sweep 2 dispatched {score_order}, expected {_EXPECTED_SCORE_ORDER} — the "
            "FR-ORCH-07 key (judge, question, criterion) and nothing else. c4 before c2 "
            "is the point: a dependency-ordered Sweep 2 would put c2 first, and "
            "re-ordering scoring by the criterion graph buys nothing (the graph was "
            "Sweep 1's) while costing cache locality"
        )
        assert "m1" not in score_order, (
            "the deterministic criterion produced scoring work in Sweep 2"
        )
    finally:
        store.close()


# ------------------------------------------------------------------------------------------
# TC-ORCH-08 — the FR-ORCH-07 key on both profiles, and comparable traces
# ------------------------------------------------------------------------------------------


def test_tc_orch_08_sweep2_order_is_the_key_on_both_profiles_and_comparable(
    tmp_data_dir,
):
    """`TC-ORCH-08` — the same run on `edge-local` and on `dev-ci`: Sweep 2 order is
    judge, then question, then criterion, then parallel over submissions, on both, and
    the two traces are comparable."""
    require(ORCH_MODULE, "Orchestrator.lease", "SWEEP1_ADMITTED_INGEST_STATUSES",
            issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        submissions = ("SYN-001", "SYN-002")
        # Two holistic criteria: base depth 3, so Sweep 2 spreads over all three judges
        # and the judge-outermost half of the key is exercised, not just question ->
        # criterion. Questions are inverted against criterion ids (h2 on Q1, h1 on Q2)
        # so key order and alphabetical order differ.
        criteria = (
            {"criterion_id": "h1", "kind": "open", "scoring_model": "holistic",
             "question_id": "Q2"},
            {"criterion_id": "h2", "kind": "open", "scoring_model": "holistic",
             "question_id": "Q1"},
        )
        seed_cohort(store, submissions, cohort_id=ORCH_COHORT_ID)
        profiles = (
            ("edge-local", "pkg-orch08-edge", EDGE_PANEL_3,
             resolve_run_config(
                 edge_cfg(HARNESS_PROFILE="edge-local", panel=EDGE_PANEL_3),
                 CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
             )),
            ("dev-ci", "pkg-orch08-dev", HOSTED_PANEL_3,
             resolve_run_config(
                 hosted_cfg(profile="dev-ci", panel=HOSTED_PANEL_3),
                 CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
             )),
        )

        traces: dict[str, list[tuple[int, str, str]]] = {}
        for profile, package_id, panel, cfg in profiles:
            version = seed_package(store, criteria, package_id=package_id)
            orchestrator = Orchestrator(store)
            run_id = orchestrator.create_run(ORCH_COHORT_ID, version, cfg)
            orchestrator.enumerate_units(run_id)

            cohort = store.cohort(ORCH_COHORT_ID)
            # Sweep 2 begins only once every extraction is done (FR-ORCH-06's gate).
            _complete_extracts(cohort, run_id)

            arm_ids = [arm.build_id for arm in panel]
            trace: list[tuple[int, str, str]] = []
            for unit in _lease_one_by_one(orchestrator, "worker-a", "score"):
                trace.append(
                    (arm_ids.index(unit.judge),
                     "Q2" if unit.criterion_id == "h1" else "Q1",
                     unit.criterion_id)
                )
            # Submissions run parallel: same-key units are unordered, so collapse the
            # trace to its first occurrence of each key before comparing.
            traces[profile] = list(dict.fromkeys(trace))

        expected = [
            (0, "Q1", "h2"), (0, "Q2", "h1"),
            (1, "Q1", "h2"), (1, "Q2", "h1"),
            (2, "Q1", "h2"), (2, "Q2", "h1"),
        ]
        for profile in ("edge-local", "dev-ci"):
            assert traces[profile] == expected, (
                f"Sweep 2 on {profile} dispatched {traces[profile]}, expected "
                f"{expected} — the FR-ORCH-07 key is judge outermost, then question, "
                "then criterion, on EVERY backend profile"
            )
        assert traces["edge-local"] == traces["dev-ci"], (
            "the two profiles' Sweep 2 traces differ — execution traces must remain "
            "comparable across profiles, or a trace recorded on one backend cannot be "
            "checked against a run on another"
        )
    finally:
        store.close()
