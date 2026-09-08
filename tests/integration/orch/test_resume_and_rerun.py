"""`TC-ORCH-02` and `TC-ORCH-03` — the ledger half of resume and the completed-run no-op.

- `TC-ORCH-02` (`FR-ORCH-02`): a run with 40% of its units `done`; `resume()` — with **no
  arguments** — skips every `done` unit, and no bookkeeping beyond the ledger is read. The
  state-independence half of the oracle is asserted two ways: the store's data directory
  holds **no** auxiliary state file to delete (the ledger is the only bookkeeping there
  is), and a decoy state file planted beside it leaves `resume()` unaffected.
- `TC-ORCH-03` (`FR-ORCH-03`): a completed run, re-run — no new rows in **any** table;
  the operation is a no-op. Oracle: row-count invariant over every table in the file, not
  merely the ledger's own.

**Isolation: rung 3** — real store, real Tier P package, real cohort ledger; no doubles
(`§4.2` forbids an in-memory stand-in for the store contract outright).

**Disclosed stand-ins.** Marking units `done` and the run `complete` writes the ledger rows
directly: the lease/complete surface that does this in production is #58's, and the
control-row status transition is #61's. The rows written here are exactly the rows those
surfaces will write (`work_unit.status`, `run.status`), so the resume behavior under test
— skip what is done, insert nothing new — is the shipped one, exercised against the same
state it will meet in production. No production module may write these rows
(`CT-ORCH-17`); this is test scaffolding standing in for its writer, not a peer module.
"""

from __future__ import annotations

import json

import pytest

from aeh.store import open_store
from tests.support.orch_run import seed_run

pytestmark = pytest.mark.integration

ISSUE = "#63"

_SUBMISSIONS = ("SYN-001", "SYN-002", "SYN-003", "SYN-004", "SYN-005")

#: One judged atomic criterion and one deterministic one — three base units per
#: submission (extract, score, deterministic), fifteen total, so "40% of units done"
#: is exactly six rows and no rounding is hidden in the fixture.
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "mcq"},
)


def _mark_done(cohort_handle, run_id: str, work_ids, count: int) -> None:
    """Stand-in for the lease/complete surface (#58): flip the first `count` units."""
    with cohort_handle.transaction() as tx:
        for work_id in work_ids[:count]:
            tx.execute(
                "UPDATE work_unit SET status = 'done' "
                "WHERE work_id = :w AND run_id = :r",
                w=work_id,
                r=run_id,
            )


def _is_sqlite_file(name: str) -> bool:
    """True for the database files themselves: `<name>.sqlite` and its `-wal`/`-shm`
    journal pair. Anything else in the data directory is auxiliary state."""
    return (
        name.endswith(".sqlite")
        or name.endswith(".sqlite-wal")
        or name.endswith(".sqlite-shm")
    )


def _ledger_rows(cohort_handle, run_id: str) -> dict[str, tuple[str, str]]:
    """The run's units as `work_id -> (stage, status)`, in sorted order."""
    rows = cohort_handle.query(
        "SELECT work_id, stage, status FROM work_unit WHERE run_id = :r "
        "ORDER BY work_id",
        r=run_id,
    )
    return {row["work_id"]: (row["stage"], row["status"]) for row in rows}


def _table_counts(handle) -> dict[str, int]:
    """One row count per user table in the file the handle opens."""
    names = handle.query(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return {
        row["name"]: len(handle.query(f'SELECT * FROM "{row["name"]}"'))
        for row in names
    }


def test_tc_orch_02_resume_skips_every_done_unit_with_no_bookkeeping_beyond_the_ledger(
    tmp_data_dir,
):
    """`TC-ORCH-02` — 40% done; `resume()` takes no arguments, skips every `done` unit,
    and reads no bookkeeping beyond the ledger. Oracle: exact value plus
    state-independence."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA
        )
        report = orchestrator.enumerate_units(run_id)
        assert report.units_enumerated == 15, (
            "the fixture drifted: 5 submissions x 3 base units is the shape the 40% "
            "fraction below is computed against"
        )

        cohort = store.cohort("c-2026-7B-orch")
        done_ids = sorted(_ledger_rows(cohort, run_id))
        _mark_done(cohort, run_id, done_ids, count=6)
        # The state resume() must preserve: the ledger as the lease/complete surface
        # (#58) leaves it — six units done, the rest pending.
        before = _ledger_rows(cohort, run_id)
        assert sum(1 for _, (_, status) in before.items() if status == "done") == 6

        # The state-independence half, first form: the data directory holds no auxiliary
        # state file — only the SQLite databases themselves (a `-wal`/`-shm` pair is the
        # database's own journal, not bookkeeping a resume could lose). A resume that
        # needed a cursor file, a progress sidecar or any other state would have one to
        # lose here.
        data_files = sorted(
            str(path.relative_to(tmp_data_dir))
            for path in tmp_data_dir.rglob("*")
            if path.is_file()
        )
        strays = [name for name in data_files if not _is_sqlite_file(name)]
        assert data_files and not strays, (
            f"the store wrote auxiliary state beside the ledgers: {strays}. "
            "resume() may depend on the ledger alone (FR-ORCH-02); a side file is a "
            "cursor an uncontrolled kill would strand."
        )

        # Second form: a decoy auxiliary file planted beside the ledgers leaves resume()
        # unaffected — it is neither read nor consumed.
        decoy = tmp_data_dir / "resume-state.json"
        decoy.write_text(json.dumps({"done": ["nothing"]}), encoding="utf-8")

        # A sixth submission arrives after the done units exist (as a re-ingested or
        # late-arriving submission would). resume() must find the run by discovery,
        # enumerate the newcomer's units, and still skip every done one — without this
        # positive half, a resume() that did nothing at all would pass as a perfect skip.
        with cohort.transaction() as tx:
            tx.execute(
                "INSERT INTO submission (submission_id, cohort_id, student_ref) "
                "VALUES ('SYN-006', :c, 'ref-SYN-006')",
                c="c-2026-7B-orch",
            )

        # resume() with NO arguments — the requirement, not ergonomics. The run is
        # discovered from the ledger itself.
        orchestrator.resume()

        after = _ledger_rows(cohort, run_id)
        preserved = {w: after[w] for w in before}
        assert preserved == before, (
            "resume() changed the ledger beyond the new submission's units: done units "
            "must be skipped in place — a re-enumeration that rewrites status or "
            "identity is a re-run, not a resume"
        )
        assert sum(1 for _, (_, status) in after.items() if status == "done") == 6, (
            "a done unit came back pending — the skip is made of INSERT OR IGNORE, and "
            "a resume that resurrects done work recomputes results it already holds"
        )
        newcomer = [
            work_id for work_id, (stage, _) in after.items()
            if work_id not in before
        ]
        assert len(newcomer) == 3, (
            f"resume() enumerated {len(newcomer)} units for the new submission, "
            "expected 3 (extract, score, deterministic) — the discovery-and-enumerate "
            "half of the no-argument resume did not run"
        )
        assert all(after[w][1] == "pending" for w in newcomer)
        assert decoy.read_text(encoding="utf-8") == json.dumps({"done": ["nothing"]}), (
            "resume() consumed or rewrote the decoy state file — it read bookkeeping "
            "beyond the ledger"
        )
    finally:
        store.close()


def test_tc_orch_03_a_completed_run_rerun_inserts_no_rows_in_any_table(tmp_data_dir):
    """`TC-ORCH-03` — a completed run, re-run: no new rows in **any** table; the
    operation is a no-op. Oracle: row-count invariant over every table, plus the
    report's own `no-op` status."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA
        )
        orchestrator.enumerate_units(run_id)

        cohort = store.cohort("c-2026-7B-orch")
        with cohort.transaction() as tx:
            tx.execute("UPDATE work_unit SET status = 'done' WHERE run_id = :r", r=run_id)
        durable = store.durable()
        # The run-row status transition is #61's control-row write; the completed state
        # it will produce is what this case re-runs against.
        with cohort.transaction() as tx:
            tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=run_id)

        before = {**_table_counts(cohort), **_table_counts(durable)}

        report = orchestrator.enumerate_units(run_id)
        orchestrator.resume()  # the no-argument form must also find nothing to do

        after = {**_table_counts(cohort), **_table_counts(durable)}

        assert report.status == "no-op", (
            f"re-running a completed run reported {report.status!r}; the shape a "
            "completed run's re-run must have is 'no-op' (FR-ORCH-03)"
        )
        assert report.units_inserted == 0
        assert report.units_already_present == report.units_enumerated
        assert after == before, (
            "re-running a completed run added or removed rows: "
            f"{ {k: (before.get(k), after.get(k)) for k in set(before) | set(after) if before.get(k) != after.get(k)} }"
        )
        # And the completed run stayed completed — the no-op did not resurrect it.
        status = cohort.query(
            "SELECT status FROM run WHERE run_id = :r", r=run_id
        )[0]["status"]
        assert status == "complete"
    finally:
        store.close()
