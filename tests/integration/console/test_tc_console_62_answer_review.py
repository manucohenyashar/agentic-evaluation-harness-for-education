"""`TC-CONSOLE-62` (issue #771, FR-CONSOLE-55, ADR-45) — `answer authoring review`: the
answer walk through the console, the single-writer rule it runs under, and the answers'
survival across a full server restart.

| Arm | Expected |
|---|---|
| one answer over the AF-11 draft | the draft file on disk is rewritten **in place** — the same path, new bytes, the answered item's sentinel gone — and the outcome says what still stands |
| a second action while the first is mid-flight | refused with the single-writer message ("this draft already has an action in progress; finish it before starting another.") and the draft file unchanged while the first was held |
| a full server restart (terminate, serve again over the same store) | the answered draft reads back answered — the answer lived in the draft file, not in console memory |

**A disclosed wording divergence, behaviour unchanged.** The plan quotes the concurrent
refusal as "A review of this draft is already open"; the shipped refusal the concurrent
arm meets is the draft directory's single-writer sentence, asserted verbatim below. The
oracle is the refusal of the concurrent action under `ADR-45`'s locking, which holds
either way; if the wording itself is to be pinned, that is #760's sentence to change, not
this case's.

The concurrent arm is paced, not raced (§4.6): the first request's review walk is held
open by a wrapper around the `run_review` seam the console imports, so the second request
lands while the first is provably mid-flight.

**Isolation: rung 3 (E1)** — real store, real console over real HTTP, the recorded
provider (see the support module's reconcile for the recorded chain).
"""

from __future__ import annotations

import hashlib
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
from aeh.console import serve_console
from aeh.console import authoring_actions
from tests.support.console_redesign_world import (
    _action,
    draft_path_in,
    draft_read,
    recorded_authoring_config,
    run_draft_job,
    served_authoring,
)
from tests.support.spa import store_digest

pytestmark = pytest.mark.integration

#: The AF-11 draft's two review items, and the teacher-shaped answer the walk accepts for
#: the first (the approving teacher's name, as the fixture's expected answers carry).
ITEM_APPROVER = "approved_by"
ITEM_GRADES = "grades"
APPROVER_ANSWER = "Prof. Dana Whitfield"


def _file_digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _af11_draft(served_authoring):
    """Run the recorded AF-11 draft job; `(port, data_dir, draft path, draft document)`."""
    _server, port, _store, data_dir = served_authoring
    _answer, record = run_draft_job(port, "AF-11")
    assert record["state"] == "succeeded", f"the draft job ended {record['state']}"
    document = draft_read(port)["draft"]
    package_id = document["package_id"]
    return port, data_dir, draft_path_in(data_dir, package_id), package_id


def test_tc_console_62_an_answer_rewrites_the_draft_in_place_and_says_what_still_stands(
        served_authoring):
    """One answer: the same draft file, new bytes, the answered sentinel gone; the
    outcome reports the review item(s) that still stand."""
    port, data_dir, path, package_id = _af11_draft(served_authoring)
    before = _file_digest(path)
    assert draft_read(port)["draft"]["placeholders"], "the fresh draft has no open items"

    answer = _action(port, "answer authoring review", {
        "package_id": package_id, "item_id": ITEM_APPROVER, "value": APPROVER_ANSWER,
    })

    assert answer["dispatched"] is True
    assert answer["refused"] is False
    assert "the answer was recorded" in answer["detail"]
    # The AF-11 draft's standing review items after the answer are the `grades`
    # placeholder and the `spec` validation issue the review walk reports — the shipped
    # outcome counts both, which is what the review screen asks about.
    assert "2 review item(s) still stand (grades, spec)" in answer["detail"], (
        f"the outcome did not report the standing review item(s): {answer['detail']!r}")
    assert answer["next_action"] == "answer the remaining review items on the review screen."

    assert _file_digest(path) != before, (
        "the answer left the draft file byte-identical; the review must rewrite it "
        "in place")
    assert path.is_file(), "the answer replaced the draft file instead of rewriting it"
    rewritten = draft_read(port)["draft"]
    standing = {item["item_id"] for item in rewritten["placeholders"]}
    assert standing == {ITEM_GRADES}, (
        f"the draft's open items after the answer are {standing}; the answered "
        "sentinel must be gone and the untouched one standing")


def test_tc_console_62_a_second_action_while_one_is_mid_flight_is_refused_by_the_draft_lock(
        served_authoring, monkeypatch):
    """The single-writer rule (`ADR-45`): while a review is provably mid-flight, a second
    action on the same draft is refused with the file-lock sentence, and nothing is
    written behind the first's back."""
    port, data_dir, path, package_id = _af11_draft(served_authoring)
    before = _file_digest(path)

    real_run_review = authoring_actions.run_review
    entered, release = threading.Event(), threading.Event()

    def paced_run_review(draft_path, answers):
        entered.set()
        assert release.wait(timeout=60), "the held review was never released"
        return real_run_review(draft_path, answers)

    monkeypatch.setattr(authoring_actions, "run_review", paced_run_review)

    outcomes: dict[str, object] = {}

    def first():
        outcomes["first"] = _action(port, "answer authoring review", {
            "package_id": package_id, "item_id": ITEM_APPROVER,
            "value": APPROVER_ANSWER,
        })

    worker = threading.Thread(target=first, name="paced-review")
    worker.start()
    try:
        assert entered.wait(timeout=30), "the first review never reached its walk"
        second = _action(port, "answer authoring review", {
            "package_id": package_id, "item_id": ITEM_GRADES, "value": "80",
        })
    finally:
        release.set()
        worker.join(timeout=60)

    assert second["refused"] is True, (
        f"the concurrent action was answered {second!r}; ADR-45's lock must refuse it")
    assert second["detail"] == (
        "another review, edit or approval of a draft in this directory is running; "
        "try again in a moment."), (
        f"the concurrent action's refusal is not the single-writer sentence: "
        f"{second['detail']!r}")
    first_outcome = outcomes["first"]
    assert first_outcome["refused"] is False
    assert first_outcome["dispatched"] is True
    # The first answer still landed exactly once: the sentinel it answered is gone.
    standing = {item["item_id"] for item in draft_read(port)["draft"]["placeholders"]}
    assert standing == {ITEM_GRADES}
    assert _file_digest(path) != before


def test_tc_console_62_answers_survive_a_full_server_restart(served_authoring):
    """Terminate the console and serve a fresh one over the same store: the answered
    draft reads back answered. The review's state is the draft file (`ADR-45`), never
    console memory — which is what makes the restart survivable."""
    server, port, store, data_dir = served_authoring
    _answer, _record = run_draft_job(port, "AF-11")
    document = draft_read(port)["draft"]
    package_id = document["package_id"]
    answer = _action(port, "answer authoring review", {
        "package_id": package_id, "item_id": ITEM_APPROVER, "value": APPROVER_ANSWER,
    })
    assert answer["refused"] is False

    server.terminate()
    restarted = serve_console(store=store, cfg=recorded_authoring_config())
    try:
        _host, new_port = restarted.socket.getsockname()[:2]
        after = draft_read(new_port)["draft"]
        standing = {item["item_id"] for item in after["placeholders"]}
        assert standing == {ITEM_GRADES}, (
            f"after the restart the draft's open items are {standing}; the answered "
            "item must have survived the process ending")
        assert after["package_id"] == package_id
        replay = _action(new_port, "answer authoring review", {
            "package_id": package_id, "item_id": ITEM_APPROVER,
            "value": APPROVER_ANSWER,
        })
        assert replay["refused"] is True, (
            "the restarted console accepted the already-answered item again")
        assert "not one this draft still asks about" in replay["detail"]
    finally:
        restarted.terminate()
