"""`TC-CONSOLE-70` (issue #771, FR-CONSOLE-57, CT-CONSOLE-35) — `cancel job`: the one
action over both kinds of job, and what each kind's cancellation may touch.

| Arm | Expected |
|---|---|
| (a) cancel an authoring draft mid-flight | the job ends `cancelled`, the files the last completed step left stand (no draft written), and the outcome says the stop happens at the next step boundary |
| (b) cancel a run | a `run_control` row is written and nothing else — the run's own row unchanged, the orchestrator to apply the pause at its next control read (`CT-ORCH-13`) |
| (c) cancel a finished job | refused: it is already `succeeded`; the jobs page lists what it wrote |

The mid-flight arm is paced, not raced (§4.6): the draft's first model call is held open
by the support module's paced wrapper around the recorded provider, so the cancel lands
while the job is provably running.

**Isolation: rung 3 (E1)** — real store, real console over real HTTP, the recorded
provider (see the support module's reconcile for the recorded chain).
"""

from __future__ import annotations

import re
import threading

import pytest

import aeh.agg  # noqa: F401 — the full migration chain before the first store open (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.console import authoring_actions
from tests.support.console_redesign_world import (
    PacedRecordedProvider,
    _action,
    _get_json,
    run_draft_job,
    served_authoring,
    served_console,
    start_draft,
    wait_for_job,
)
from tests.support.spa import changed_tables, store_digest
from tests.support.console_world import seed_scored_run

pytestmark = pytest.mark.integration


def test_tc_console_70a_cancelling_a_draft_mid_flight_ends_it_cancelled_and_leaves_no_draft(
        served_authoring, monkeypatch):
    """The paced draft is cancelled at its first step boundary: the job reads
    `cancelled`, and no draft file exists — the files written stay as the last completed
    step left them, and the last completed step wrote no draft."""
    _server, port, _store, data_dir = served_authoring
    gate, release = threading.Event(), threading.Event()
    real_provider_for = authoring_actions._provider_for

    def paced_provider_for(environ):
        return PacedRecordedProvider(real_provider_for(environ), gate, release)

    monkeypatch.setattr(authoring_actions, "_provider_for", paced_provider_for)

    answer = start_draft(port, "AF-02")
    assert gate.wait(timeout=30), "the paced provider was never called"

    try:
        cancel = _action(port, "cancel job", {"job_id": answer["job_id"]})

        assert cancel["dispatched"] is True, cancel["detail"]
        assert cancel["refused"] is False
        assert cancel["detail"] == (
            f"cancel requested for job {answer['job_id']}; it stops at its next step "
            "boundary, and the files it has written stay exactly as the last completed "
            "step left them."), cancel["detail"]
    finally:
        # Release the paced worker even when an assertion above fails, so the run does
        # not wait out the worker's timeout before reporting the failure.
        release.set()
    record = wait_for_job(port, answer["job_id"])

    assert record["state"] == "cancelled", (
        f"the cancelled job's terminal state is {record['state']!r}")
    assert record["error"]["detail"], "the cancelled job names no reason"
    assert record["error"]["next_action"] == "start the draft again from the documents."
    drafts = list(data_dir.glob("authoring/**/*.toml"))
    assert drafts == [], (
        f"the cancelled job left draft file(s) {[path.name for path in drafts]}; the "
        "draft is written only when the workflow completes its steps")


def test_tc_console_70b_cancelling_a_run_writes_a_control_row_and_nothing_else(
        served_console):
    """A run's cancellation is a `run_control` row the orchestrator applies at its next
    control read (`CT-ORCH-13`): the run's own row is untouched."""
    _server, port, store, data_dir = served_console
    seeded = seed_scored_run(store, cohort_id="c-cn", run_id="r-cn",
                             package_id="pkg-cn", submissions=2, finalize=False)
    digest_before = store_digest(data_dir)
    run_before = [dict(row) for row in store.cohort("c-cn").query(
        "SELECT run_id, status, started_at, completed_at FROM run WHERE run_id = :r",
        r=seeded.run_id)]

    answer = _action(port, "cancel job", {"job_id": seeded.run_id})

    assert answer["dispatched"] is True, answer["detail"]
    assert answer["refused"] is False
    assert answer["detail"].startswith(f"cancel requested for run {seeded.run_id}: "), (
        answer["detail"])
    assert "on the run's cohort ledger" in answer["detail"]
    assert "The run stops at its next control-read boundary." in answer["detail"]
    control_id = re.search(r"queued as run_control row (\S+) on the run's",
                           answer["detail"])
    assert control_id is not None, (
        f"the outcome does not name the control row it wrote: {answer['detail']!r}")

    controls = [dict(row) for row in store.cohort("c-cn").query(
        "SELECT control_id, run_id, action FROM run_control WHERE run_id = :r",
        r=seeded.run_id)]
    assert len(controls) == 1 and controls[0]["control_id"] == control_id.group(1), (
        f"the run_control rows are {controls}")
    assert controls[0]["action"] == "pause"

    # The spec's digest-restriction oracle (`RS-12`): the cancel writes the run_control
    # row and NOTHING else — the whole-store snapshot may move only on that table.
    digest_after = store_digest(data_dir)
    changed = changed_tables(digest_before, digest_after)
    assert len(changed) == 1 and changed[0].endswith(":run_control"), (
        f"cancelling a run changed {changed}; the control row is the only write")
    count_before, _hash_before = digest_before[changed[0]]
    count_after, _hash_after = digest_after[changed[0]]
    assert count_after == count_before + 1, (
        f"the run_control table went {count_before} -> {count_after} rows; exactly "
        "one control row is the cancel's write")
    run_after = [dict(row) for row in store.cohort("c-cn").query(
        "SELECT run_id, status, started_at, completed_at FROM run WHERE run_id = :r",
        r=seeded.run_id)]
    assert run_after == run_before, (
        "cancelling a run changed the run's own row; the pause is the control row's "
        "to apply, at the orchestrator's next read")


def test_tc_console_70c_cancelling_a_finished_job_is_refused_with_the_jobs_page(
        served_authoring):
    """A succeeded job cannot be cancelled: the refusal says so and points at the jobs
    page, where the job's outcome and files are listed."""
    _server, port, _store, _data_dir = served_authoring
    _answer, record = run_draft_job(port, "AF-02")
    assert record["state"] == "succeeded", f"the draft job ended {record['state']}"

    cancel = _action(port, "cancel job", {"job_id": record["job_id"]})

    assert cancel["refused"] is True
    assert cancel["dispatched"] is False
    assert cancel["detail"] == (
        f"the job {record['job_id']} is already succeeded; there is nothing to "
        "cancel."), cancel["detail"]
    assert cancel["next_action"] == (
        "open the job on the jobs page; its outcome and the files it wrote are "
        "listed there.")
