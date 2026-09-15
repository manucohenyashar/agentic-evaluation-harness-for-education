"""`TS-49` (issue #130) — the console process killed mid-run: the run does not notice, and the
control rows queued before the kill are applied afterwards.

Test plan §5.19 `TC-CONSOLE-35` (`NFR-CONSOLE-03`) and §6.8 `RES-16` (`FR-CONSOLE-01`,
`NFR-CONSOLE-03`), Resilience / rung 3 — one scenario, asserted once under both IDs.

**What this adds over `CT-CONSOLE-C01`'s kill case.** That case kills a served console over
`StoreSpy` and checks the queued payloads are still in the double's write log. Here the run is
real and live: a scored package, an enumerated ledger, a started run whose deterministic units
are being leased and completed by the orchestrator when the console process is killed; the pause
the console queued before the kill is a real `run_control` row, and "picked up on the next start"
is the orchestrator's own claim loop (`lease` applies unapplied control rows before it hands out
work, `CT-ORCH-13`) — so the oracle is the run row's status, the control row's `applied_at`, and
the run reaching `complete`.

**Disclosed shape of the served console — and what it limits.** `serve_console` is a two-socket
design whose child process never touches the store and serves no console page (`aeh/console.py`;
the TS-49 browser and clean-machine cases fail on exactly that). The control action is therefore
performed by the console's application object over the same store, as `CT-CONSOLE-C01` does, and
the kill is a real `terminate()` of the served process with its exit status reaped. Until the
served process *is* the console, "the kill changes nothing" cannot fail — the process killed holds
nothing to lose. The replay half (queued rows applied by the orchestrator, never by a restart on
its own) is real today; the kill half becomes a real probe when the served process serves the
console, with no edit to this test.

**Written ahead of implementation.** The issue says `yes`; stale — `M-CONSOLE` and `M-ORCH` landed.
"""

from __future__ import annotations

import pytest

from aeh.console import SCREENS, build_console, serve_console
from aeh.orch import Orchestrator
from aeh.store import open_store
from tests.support.console_world import rows, seed_scored_run

pytestmark = [pytest.mark.integration]

_STAGE = "deterministic"


def test_tc_console_35_res_16_killing_the_console_mid_run_leaves_the_run_and_its_queued_rows(
    tmp_data_dir,
):
    """`TC-CONSOLE-35` / `RES-16` — run completion plus control-row replay.

    1. A run is started and half its units are completed; a console is served over the store.
    2. The console queues a **pause** (a `run_control` row), then its process is killed.
    3. The kill changes nothing: every ledger row the run owns is as it was before the kill.
    4. The orchestrator's next claim applies the queued pause — the run reads `paused`, the row is
       stamped applied, and no work is handed out while paused.
    5. A restarted console renders the paused state from the ledger (nothing survived in memory to
       render it from) and queues a **resume**, which stays queued (the run still paused) until a
       restarted worker's argument-free `resume()` applies it — and a restart with no queued
       resume, run first as the control, leaves the run paused.
    6. The remaining units drain and the run reaches `complete`, with every unit `done`.
    """
    store = open_store(tmp_data_dir)
    server = restarted = None
    try:
        world = seed_scored_run(store, submissions=4, enumerate_units=True)
        cohort = store.cohort(world.cohort_id)
        orchestrator = Orchestrator(store)
        orchestrator.start(world.run_id)
        units = rows(cohort, "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :r",
                     r=world.run_id)[0]["n"]
        assert units >= 8, f"fixture: {units} units is too few to kill anything mid-run"
        for unit in orchestrator.lease("w-before-kill", _STAGE, units // 2):
            orchestrator.complete(unit.work_id)

        server = serve_console(store=store, run_id=world.run_id)
        console = build_console(store=store)
        queued = console.perform("pause/resume", run_id=world.run_id, state="paused")
        assert queued.dispatched and queued.rows_written, queued.detail

        def _ledger():
            return {
                "run": rows(cohort, "SELECT status FROM run WHERE run_id = :r", r=world.run_id),
                "units": rows(cohort, "SELECT work_id, status, attempts FROM work_unit "
                                      "WHERE run_id = :r ORDER BY work_id", r=world.run_id),
                "control": rows(cohort, "SELECT control_id, action, applied_at FROM run_control "
                                        "WHERE run_id = :r ORDER BY control_id", r=world.run_id),
            }

        before_kill = _ledger()
        server.terminate()
        assert server.returncode is not None, "the console process was not reaped"
        assert _ledger() == before_kill, "killing the console changed the run's ledger"
        assert before_kill["run"] == [{"status": "running"}]
        assert [c["applied_at"] for c in before_kill["control"]] == [None], (
            f"fixture: the pause must still be queued when the console dies: {before_kill!r}"
        )

        handed_out = orchestrator.lease("w-after-kill", _STAGE, units)
        after_claim = _ledger()
        assert after_claim["run"] == [{"status": "paused"}], (
            f"the pause queued before the console was killed was not applied on the "
            f"orchestrator's next claim: {after_claim['run']!r} (NFR-CONSOLE-03)"
        )
        assert all(c["applied_at"] for c in after_claim["control"]), after_claim["control"]
        assert not handed_out, f"a paused run handed out {len(handed_out)} unit(s)"

        restarted = serve_console(store=store, run_id=world.run_id)
        fresh = build_console(store=store)
        monitor = fresh.render(SCREENS["S7"], id=world.run_id).html
        assert f"Run {world.run_id} status: paused" in monitor, (
            "a restarted console does not render the paused run from the ledger"
        )
        Orchestrator(store).resume()  # the control: a restart alone does not un-pause
        assert rows(cohort, "SELECT status FROM run WHERE run_id = :r", r=world.run_id) == [
            {"status": "paused"}
        ], "fixture: a bare worker restart un-paused the run, so the replay below proves nothing"
        resumed = fresh.perform("pause/resume", run_id=world.run_id, state="running")
        assert resumed.dispatched, resumed.detail
        queued_resume = _ledger()
        assert queued_resume["run"] == [{"status": "paused"}] and [
            c["applied_at"] for c in queued_resume["control"]
        ].count(None) == 1, (
            f"the console's resume must be a queued request, not an in-request state change "
            f"(CT-ORCH-13): {queued_resume!r}"
        )
        # A paused run hands out nothing, so the queued resume is picked up where M-ORCH picks up
        # control rows for runs that are not running: the worker's next start — the
        # argument-free `resume()` a restarted orchestrator runs (FR-ORCH-02), which applies
        # control rows and never auto-unpauses a run nobody asked to resume. That last clause is
        # what makes this the console's row being applied, not the restart un-pausing on its own.
        restarted_worker = Orchestrator(store)
        restarted_worker.resume()
        assert rows(cohort, "SELECT status FROM run WHERE run_id = :r", r=world.run_id) == [
            {"status": "running"}
        ], "the resume queued through the restarted console was not applied on the next start"
        orchestrator = restarted_worker

        while True:
            batch = orchestrator.lease("w-after-restart", _STAGE, units)
            if not batch:
                break
            for unit in batch:
                orchestrator.complete(unit.work_id)
        final = _ledger()
        assert final["run"] == [{"status": "complete"}], (
            f"the run did not complete after the console was killed and restarted: {final['run']!r}"
        )
        assert {u["status"] for u in final["units"]} == {"done"} and len(final["units"]) == units
        assert all(c["applied_at"] for c in final["control"]) and len(final["control"]) == 2
    finally:
        for served in (server, restarted):
            if served is not None:
                served.terminate()
        store.close()
