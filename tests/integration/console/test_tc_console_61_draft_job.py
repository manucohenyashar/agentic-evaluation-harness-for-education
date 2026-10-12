"""`TC-CONSOLE-61` (issue #771, FR-CONSOLE-61/52, CT-CONSOLE-32, RS-04) — the draft job,
end to end over the console's HTTP surface: a real `AuthoringService` behind the console's
own draft worker, the recorded provider as the only transport (`HARNESS_FIXTURE_DIR`; no
network, `CT-PROV-15`).

| Arm | Expected |
|---|---|
| `draft package from documents` over AF-02 | the action returns a job id **immediately** (the answer carries `job_id` with `dispatched: true`, and the request returns before the model work runs) |
| the jobs read, polled | `kind == 'authoring_draft'`, the progress fields advancing (`done`/`total`/`current`, `stage`, `attempt`/`attempts`), final state `succeeded` |
| the store, digested before/after | **`rows_written == 0`** on the action's outcome and the store digest unchanged — the draft's state is the draft files, never a store row (`ADR-45`, RS-04) |
| replay, same documents, no `replace` | not dispatched: the console names the standing draft and its succeeded job, and the draft on disk is byte-identical |
| replay with `replace` | a fresh attempt job (`-r2`) completes, and the redrafted file is byte-identical to the first — deterministic authoring, observed one level up from `CT-AUTHOR-21` |

The recorded chain is the support module's declared reconcile (`RECORDED_TRANSCRIBER` /
`RECORDED_JUDGE`): the corpus is keyed on those builds, so the console is served the
configuration that names them.

**Isolation: rung 3 (E1)** — a real store, a real console on a real loopback socket, the
recorded provider. Nothing here is a spy.
"""

from __future__ import annotations

import hashlib
import threading
import time

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
    _get_json,
    draft_path_in,
    draft_read,
    run_draft_job,
    served_authoring,
    start_draft,
    wait_for_job,
)
from tests.support.spa import store_digest

pytestmark = pytest.mark.integration


def _file_digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_tc_console_61_draft_job_returns_a_job_id_and_advances_to_succeeded_without_a_store_row(
        served_authoring):
    """The draft action answers immediately with a job id; the jobs read shows an
    advancing `authoring_draft` job that ends `succeeded`; the store holds not one new
    row (`rows_written == 0`, digest unchanged, RS-04)."""
    server, port, _store, data_dir = served_authoring
    before = store_digest(data_dir)

    answer, record = run_draft_job(port, "AF-02")

    # The action answered immediately, carrying the job id the jobs read serves.
    assert answer["dispatched"] is True
    assert answer["refused"] is False
    assert answer["rows_written"] == 0
    assert answer["job_id"].startswith("authoring-")
    assert answer["next_action"] == (
        "watch the job on the jobs page; the draft opens on the authoring screen "
        "when it finishes.")

    # The job's terminal record: the registry's own shape (`CT-CONSOLE-37`), the
    # authoring fields at their final values, and `succeeded`.
    assert record["job_id"] == answer["job_id"]
    assert record["kind"] == "authoring_draft"
    assert record["state"] == "succeeded"
    assert record["stage"] == "writing draft"
    assert record["attempt"] == 1
    assert record["attempts"] == 1
    assert record["progress"]["total"] == 2
    assert record["progress"]["done"] == 2
    assert "the draft stands at" in record["progress"]["current"]
    assert "review item(s) to answer" in record["progress"]["current"]
    assert record["error"]["detail"] is None
    assert record["error"]["next_action"] is None

    # The draft exists where the detail says it does, and the store wrote nothing.
    document = draft_read(port)["draft"]
    path = draft_path_in(data_dir, document["package_id"])
    assert path.is_file(), f"the draft job wrote no draft at {path}"
    # The terminal `current` names the draft file itself (the count it carries is the
    # workflow's own `result.placeholders`, which is not the draft read's placeholder
    # list — the two count different things, so the file name is the pinned part).
    assert record["progress"]["current"].startswith("the draft stands at ")
    assert path.name in record["progress"]["current"], (
        f"the terminal progress does not name the draft file: "
        f"{record['progress']['current']!r}")
    after = store_digest(data_dir)
    assert before == after, (
        "the draft job wrote store rows "
        f"({sorted(set(after) - set(before))} appeared); ADR-45 keeps a draft's state "
        "in its files, and RS-04's oracle is a digest that does not move.")


def test_tc_console_61_the_jobs_read_shows_progress_advancing_from_the_first_poll(
        served_authoring, monkeypatch):
    """Polled early, the job record already carries `kind='authoring_draft'` and the
    progress fields advancing — `queued` to `running` with `done` moving and a stage
    named is what FR-CONSOLE-52's progress triple promises, and the polls that see it
    here are paced so the observation is not a race with a fast replay."""
    server, port, _store, data_dir = served_authoring
    gate, release = threading.Event(), threading.Event()
    real_provider_for = authoring_actions._provider_for

    def paced_provider_for(environ):
        return PacedRecordedProvider(real_provider_for(environ), gate, release)

    monkeypatch.setattr(authoring_actions, "_provider_for", paced_provider_for)

    answer = start_draft(port, "AF-02")
    try:
        assert gate.wait(timeout=30), "the paced provider was never called"

        seen: list[dict] = []
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            seen.append(_get_json(port, f"/api/v1/jobs/{answer['job_id']}"))
            if seen[-1]["state"] == "succeeded":
                break
            time.sleep(0.05)
    finally:
        # Release the paced worker even when an assertion above fails, so the run does
        # not wait out the worker's timeout before reporting the failure.
        release.set()
    final = wait_for_job(port, answer["job_id"])

    assert seen, "the jobs read was never polled while the job ran"
    assert seen[0]["kind"] == "authoring_draft", (
        f"the mid-flight job read as {seen[0]['kind']!r}; FR-CONSOLE-52's registry "
        "carries the authoring kind from registration on")
    assert seen[0]["state"] in ("queued", "running")
    midflight = [record for record in seen if record["state"] == "running"]
    assert midflight, (
        "no poll caught the job running: the progress advance FR-CONSOLE-52 promises "
        "was never observable")
    assert final["state"] == "succeeded"
    dones = [record["progress"]["done"] for record in midflight
             if record["progress"]["done"] is not None]
    assert dones == sorted(dones), (
        f"the progress went {dones}; CT-AUTHOR-40a's monotone rule holds at the "
        "console's own jobs read too")
    assert any(record["stage"] for record in midflight), (
        "a running authoring job reported no stage")


def test_tc_console_61_replaying_the_same_documents_answers_not_dispatched_and_the_draft_stands(
        served_authoring):
    """The same request twice: the second call is not dispatched — the console names the
    standing draft and the succeeded job that produced it — and the draft file on disk is
    byte-identical afterwards."""
    server, port, _store, data_dir = served_authoring
    answer, _record = run_draft_job(port, "AF-02")
    document = draft_read(port)["draft"]
    path = draft_path_in(data_dir, document["package_id"])
    before = _file_digest(path)

    replay = start_draft(port, "AF-02")

    assert replay["dispatched"] is False, (
        f"the replay dispatched a second job ({replay!r}); the standing draft must be "
        "named, not silently replaced")
    assert replay["refused"] is False
    assert "already stands" in replay["detail"]
    assert answer["job_id"] in replay["detail"], (
        "the replay's detail does not name the succeeded job that produced the draft")
    assert "job_id" not in replay, (
        "a not-dispatched replay carried a job id; nothing started")
    assert replay["next_action"] == "open the draft on the authoring screen."
    assert _file_digest(path) == before


def test_tc_console_61_replace_redrafts_under_a_new_attempt_and_the_draft_is_byte_identical(
        served_authoring):
    """`replace` re-drafts from the same documents: a fresh attempt job (`-r2`) runs and
    completes, and the rewritten draft file is byte-identical to the first — the recorded
    workflow is deterministic, so a teacher re-confirming the same documents gets the
    same draft."""
    server, port, _store, data_dir = served_authoring
    answer, _record = run_draft_job(port, "AF-02")
    document = draft_read(port)["draft"]
    path = draft_path_in(data_dir, document["package_id"])
    first_digest = _file_digest(path)
    first_job = answer["job_id"]

    answer, record = run_draft_job(port, "AF-02", replace=True)

    assert answer["dispatched"] is True
    assert answer["job_id"] == f"{first_job}-r2", (
        f"the replace job answered {answer['job_id']!r}; the attempt suffix is what "
        "keeps a second attempt's job distinct in the registry")
    assert record["state"] == "succeeded"
    # The registry's `attempt`/`attempts` are the job's own retry counter, not the
    # authoring attempt number — the `-r2` suffix is the attempt marker.
    assert _file_digest(path) == first_digest, (
        "the same documents redrafted to different bytes; deterministic authoring "
        "(CT-AUTHOR-21) must hold through the console's worker too")
