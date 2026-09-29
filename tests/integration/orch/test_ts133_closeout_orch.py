"""TS-133 (#544): design 1.9's M-ORCH behaviours, each with an exact-value case.

| Case | Requirement | Oracle |
|---|---|---|
| TC-ORCH-54 | FR-ORCH-41 | engine-on seat claims accrue LLM + per-seat decision figure; the 5th claim is refused at 0.008252; the engine-off twin admits it |
| TC-ORCH-55 | FR-ORCH-42 | `submissions(R1) == ('S1', 'S2')`, deterministic-only included, another run's excluded, nothing written |
| TC-ORCH-56 | FR-ORCH-43 | one replacement arm inserted (a new identity), refused over budget, never twice for one cell |
| TC-ORCH-57 | FR-ORCH-44 | an injected wall clock: 09:00 start, paused 10:00–10:30, read at 12:00 → 9,000,000 ms |
| TC-ORCH-58 | FR-ORCH-28 (amended) | a bogus phase / negative count raises a `WorkLedgerError` that is also a `ValueError`; no row written |

Disclosed adaptations:
- **TC-ORCH-54.** The plan's scenario cannot pass `start()`: FR-ORCH-37's start check refuses a
  run whose estimate (5 × 0.002063 = 0.010315) is over the 0.0100 ceiling. So the run starts
  under a generous ceiling and the frozen ceiling is then lowered to 0.0100 on the run row,
  which is the value every later claim reads. Extraction is not billed (the seam answers
  `None`), so only seat claims move the spend. Spend is compared as a Decimal (the ledger
  stores `0.008252000`).
- **TC-ORCH-57.** The stored `run_metrics.run_wall_clock_ms` is written by a DISPATCHING
  orchestrator's flush (`progress` with a provider seam); the case measures the same figure
  through the method that flush writes (`_run_wall_clock_ms`) on the injected clock, and adds the
  plan's defaulted-clock arm as a row-set comparison.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.pkg  # noqa: F401,E401
import aeh.review, aeh.synth  # noqa: F401,E401
from aeh.orch import (
    REPLACEMENT_ALREADY_REQUESTED,
    REPLACEMENT_INSERTED,
    REPLACEMENT_REFUSED,
    STAGE_SCORE,
    CellPhaseError,
    Orchestrator,
    WorkLedgerError,
)
from aeh.store import open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration


# --- TC-ORCH-54 -----------------------------------------------------------------------------


class _ScoreOnlySeam:
    """LLM seam: a score unit costs 0.002; an extraction is not billed."""

    def verify_retention(self, refs):
        from aeh.prov import RetentionReport
        return RetentionReport(confirmed=tuple(refs), unconfirmed=())

    def estimate_cost(self, unit):
        return Decimal("0.002") if getattr(unit, "stage", None) == STAGE_SCORE else None


def _one_arm_config(engine_on: bool):
    from aeh.conf import CohortRef, ModelRef, resolve_run_config
    from tests.support.conf_builders import hosted_cfg

    panel = (ModelRef(role="judge", provider="openrouter",
                      build_id="openrouter/judge-0@2026-01-01", quantization=None),)
    extra = ({"HARNESS_DECISION_ENGINE": "jev",
              "HARNESS_JEV_BUILD": "openrouter/typesafe/jev-1.13@2026-09-17"}
             if engine_on else {})
    return resolve_run_config(
        hosted_cfg("cloud-hosted", panel=panel, HARNESS_COST_CEILING="12.50", **extra),
        CohortRef(cohort_id="c-2026-7B-orch", consent_class="synthetic"))


def _drive_seat_claims(data_dir: Path, engine_on: bool) -> tuple[list[Decimal], str, str]:
    from aeh.prov import JevOpenRouterProvider
    from tests.support.orch_run import seed_cohort, seed_package

    store = open_store(data_dir)
    try:
        cohort = seed_cohort(store, [f"S{i}" for i in range(5)])
        version = seed_package(store, [{"criterion_id": "C1", "kind": "open",
                                        "scoring_model": "holistic"}])
        decider = (JevOpenRouterProvider(api_key="k", retention_answers=lambda b: "zero-retention")
                   if engine_on else None)
        orch = Orchestrator(store, provider=_ScoreOnlySeam(), decision_provider=decider)
        config = _one_arm_config(engine_on)
        run_id = orch.create_run(cohort, version, config)
        orch.enumerate_units(run_id)
        orch.start(run_id)
        # Lower the frozen ceiling to the plan's 0.0100 on the row every claim reads.
        handle = store.cohort(cohort)
        with handle.transaction() as tx:
            tx.execute("UPDATE run SET provider_config = json_set(provider_config, "
                       "'$.cost_ceiling', '0.0100') WHERE run_id = :r", r=run_id)
        while True:
            units = orch.lease("w", "extract", 1)
            if not units:
                break
            orch.complete(units[0].work_id)
        spends: list[Decimal] = []
        for _ in range(5):
            units = orch.lease("w", STAGE_SCORE, 1)
            row = handle.query("SELECT cost_spend, status, pause_reason FROM run "
                               "WHERE run_id = :r", r=run_id)[0]
            spends.append(Decimal(str(row["cost_spend"] or "0")))
            if not units:
                break
        return spends, str(row["status"]), str(row["pause_reason"] or "")
    finally:
        store.close()


def test_tc_orch_54_decision_spend_counts_against_the_mid_run_ceiling(tmp_path):
    spends, status, reason = _drive_seat_claims(tmp_path / "on", engine_on=True)
    assert spends[3] == Decimal("0.008252"), (
        f"after 4 seat claims cost_spend is {spends[3]}; each seat claim accrues the LLM figure "
        "plus the per-seat decision figure: 4 x (0.002 + 0.000063) = 0.008252 (FR-ORCH-41)")
    assert len(spends) == 5 and spends[4] == Decimal("0.008252"), (
        f"the 5th seat claim was not refused: spends {spends}. It would reach 0.010315 > 0.0100")
    assert status == "paused" and "0.008252" in reason, (status, reason)
    assert "1 unit(s) remaining" in reason, f"the pause does not name the remaining count: {reason}"

    off, off_status, _ = _drive_seat_claims(tmp_path / "off", engine_on=False)
    assert off[3] == Decimal("0.008"), f"engine-off spend after 4 claims is {off[3]}, not 0.008"
    assert off[4] == Decimal("0.010"), (
        f"the engine-off twin refused its 5th claim (spends {off}): with no decision part the "
        "5th claim reaches exactly the ceiling and is admitted (NFR-SYS-14)")
    assert off_status == "paused", f"the engine-off twin at its ceiling is {off_status!r}, not paused"


# --- TC-ORCH-55 -----------------------------------------------------------------------------


def _counts(data_dir: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    with sqlite3.connect(Path(data_dir) / "cohorts" / f"{ORCH_COHORT_ID}.sqlite") as c:
        for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            out[table] = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return out


def test_tc_orch_55_submissions_lists_every_enumerated_submission_and_only_its_run(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        from tests.support.orch_run import orch_cfg

        orch, r1, version = seed_run(store, submissions=("S1", "S2"), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
            {"criterion_id": "C2", "kind": "mcq"}))
        orch.enumerate_units(r1)
        r2 = orch.create_run(ORCH_COHORT_ID, version, orch_cfg())  # same cohort, not enumerated
        before = _counts(tmp_data_dir)
        assert orch.submissions(r1) == ("S1", "S2")
        assert orch.submissions(r2) == (), "R2 enumerated nothing; R1's submissions leaked in"
        assert _counts(tmp_data_dir) == before, "submissions() wrote to the ledger"
    finally:
        store.close()


def test_tc_orch_55_a_deterministic_only_submission_is_listed(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _v = seed_run(store, submissions=("S1", "S2"),
                                    criteria=({"criterion_id": "Q1", "kind": "mcq"},))
        orch.enumerate_units(run_id)
        assert orch.submissions(run_id) == ("S1", "S2"), (
            "an MCQ-only paper has only deterministic units, and is still an enumerated "
            "submission (FR-ORCH-42)")
    finally:
        store.close()


# --- TC-ORCH-56 -----------------------------------------------------------------------------


def _widened_cell(store):
    # A holistic criterion seats the full three-arm panel, which widens to five: the plan's cell.
    orch, run_id, _v = seed_run(store, submissions=("S1", "S2"), criteria=(
        {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},))
    orch.enumerate_units(run_id)
    cohort = store.cohort(ORCH_COHORT_ID)
    with cohort.transaction() as tx:
        orch.enqueue_escalation(tx, (run_id, "S1", "C1"))
    return orch, run_id, cohort


def _arms(cohort, run_id) -> list[str]:
    return [r["judge_id"] for r in cohort.query(
        "SELECT judge_id FROM work_unit WHERE run_id = :r AND submission_id = 'S1' "
        "AND stage = 'score' ORDER BY rowid", r=run_id)]


def _quarantine(data_dir, run_id, judge_id) -> None:
    with sqlite3.connect(Path(data_dir) / "cohorts" / f"{ORCH_COHORT_ID}.sqlite") as c:
        c.execute("UPDATE work_unit SET status = 'quarantined' WHERE run_id = ? AND "
                  "submission_id = 'S1' AND stage = 'score' AND judge_id = ?", (run_id, judge_id))


def test_tc_orch_56_a_quarantined_arm_gets_one_replacement_and_never_two(tmp_data_dir):
    store = open_store(tmp_data_dir)
    try:
        orch, run_id, cohort = _widened_cell(store)
        panel = _arms(cohort, run_id)
        assert len(panel) == 5 and panel[-1] == "escalation-arm-5", f"fixture: the panel is {panel}"
        _quarantine(tmp_data_dir, run_id, panel[-1])  # four terminal verdicts remain
        with cohort.transaction() as tx:
            first = orch.enqueue_replacement_arm(tx, (run_id, "S1", "C1"))
        assert first.decision == REPLACEMENT_INSERTED, first
        assert first.arm == "escalation-arm-6", (
            f"the replacement is {first.arm!r}; the next arm the cell does not carry is "
            "escalation-arm-6 (never re-adding escalation-arm-5)")
        with cohort.transaction() as tx:
            again = orch.enqueue_replacement_arm(tx, (run_id, "S1", "C1"))
        assert again.decision == REPLACEMENT_ALREADY_REQUESTED, again
        assert _arms(cohort, run_id) == panel + [first.arm], "a second call inserted another arm"
    finally:
        store.close()


def test_tc_orch_56_b_an_exhausted_budget_refuses_the_replacement(tmp_data_dir, monkeypatch):
    store = open_store(tmp_data_dir)
    try:
        orch, run_id, cohort = _widened_cell(store)
        panel = _arms(cohort, run_id)
        _quarantine(tmp_data_dir, run_id, panel[-1])
        monkeypatch.setattr(Orchestrator, "_escalation_rate", lambda self, ex, run: (10, 9, 0.9))
        with cohort.transaction() as tx:
            report = orch.enqueue_replacement_arm(tx, (run_id, "S1", "C1"))
        assert report.decision == REPLACEMENT_REFUSED and "budget" in report.reason, report
        assert _arms(cohort, run_id) == panel, "a refused replacement inserted a unit"
    finally:
        store.close()


# --- TC-ORCH-57 -----------------------------------------------------------------------------


def _pause_resume_rows(data_dir, orch_factory):
    store = open_store(data_dir)
    try:
        _seeded, run_id, _v = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        orch = orch_factory(store)
        orch.enumerate_units(run_id)
        orch.start(run_id)
        orch.pause(run_id, cause="operator")
        orch.lease("w", "extract", 1)
        orch.resume(run_id)
        orch.lease("w", "extract", 1)
        cohort = store.cohort(ORCH_COHORT_ID)
        return (sorted((r["stage"], r["status"]) for r in cohort.query(
                    "SELECT stage, status FROM work_unit WHERE run_id = :r", r=run_id)),
                cohort.query("SELECT status FROM run WHERE run_id = :r", r=run_id)[0]["status"],
                cohort.query("SELECT COUNT(*) AS n FROM run_control WHERE run_id = :r",
                             r=run_id)[0]["n"])
    finally:
        store.close()


def test_tc_orch_57_a_defaulted_wall_clock_changes_no_outcome(tmp_path):
    fixed = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    injected = _pause_resume_rows(tmp_path / "injected",
                                  lambda store: Orchestrator(store, wall_clock=lambda: fixed))
    defaulted = _pause_resume_rows(tmp_path / "defaulted", lambda store: Orchestrator(store))
    assert injected == defaulted, "injecting a wall clock changed an outcome (FR-ORCH-44: values aside)"


def test_tc_orch_57_run_wall_clock_reads_the_injected_clock(tmp_data_dir):
    now = {"t": datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)}
    store = open_store(tmp_data_dir)
    try:
        _seeded, run_id, _v = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        orch = Orchestrator(store, wall_clock=lambda: now["t"])
        orch.enumerate_units(run_id)
        orch.start(run_id)
        now["t"] += timedelta(hours=1)
        orch.pause(run_id, cause="operator")
        orch.lease("w", "extract", 1)  # the read pass applies the pause
        now["t"] += timedelta(minutes=30)
        orch.resume(run_id)
        orch.lease("w", "extract", 1)
        now["t"] += timedelta(hours=1, minutes=30)
        elapsed = orch._run_wall_clock_ms(store.cohort(ORCH_COHORT_ID), run_id)
        assert elapsed == 9_000_000, (
            f"run wall clock read {elapsed} ms; 09:00 to 12:00 less the 30-minute pause is "
            "9,000,000 ms on the injected clock (FR-ORCH-44)")
    finally:
        store.close()


# --- TC-ORCH-58 -----------------------------------------------------------------------------


@pytest.mark.parametrize("phase, consumed", [("bogus", 0), ("aggregated", -1)])
def test_tc_orch_58_a_bad_cell_phase_is_a_declared_error_and_writes_nothing(
        tmp_data_dir, phase, consumed):
    store = open_store(tmp_data_dir)
    try:
        orch, run_id, _v = seed_run(store, submissions=("S1",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        orch.enumerate_units(run_id)
        cohort = store.cohort(ORCH_COHORT_ID)
        with pytest.raises(WorkLedgerError) as caught:
            with cohort.transaction() as tx:
                orch.mark_cell_phase(tx, run_id, "S1", "C1", phase, units_consumed=consumed)
        assert isinstance(caught.value, ValueError) and isinstance(caught.value, CellPhaseError)
        rows = cohort.query("SELECT COUNT(*) AS n FROM cell_phase WHERE run_id = :r", r=run_id)
        assert rows[0]["n"] == 0, "a refused phase wrote a cell_phase row"
    finally:
        store.close()
