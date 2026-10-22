"""`TC-CONSOLE-71` (issue #771, CT-CONSOLE-33, RS-06) — the refusal-shape sweep: every
refusing arm the neighbouring cases drive, scanned as a body.

| Arm | Expected |
|---|---|
| every refusing control action scanned | a teacher `detail`, never an exception class name, never a `Traceback` fragment, never an HTTP status code (`CT-CONSOLE-33`), and `next_action` where the action ships one |
| the refusing reads scanned | the read route's own shape: a 400 with the teacher's sentence in `error` |
| the `_RefreshRequired` staleness arm | the stale item's refusal names the supersession and tells the teacher to refresh the queue |

**Disclosed divergences, behaviour unchanged — all flagged for follow-up in the PR:**

1. `outcome_json` carries `next_action` only when the action set one, so two shipped
   refusals here (the textless edit, the cancel of an unknown job) carry no
   `next_action` at all — the plan's "every body has detail + next_action" holds only
   for the arms that ship one.
2. ~~The staleness arm's `ControlOutcome` sets `refresh_required=True`, but
   `outcome_json` drops that field~~ — fixed in the follow-up to PR #794's finding 4:
   the body now carries `refresh_required: true` when the outcome set it, and the scan
   below asserts the flag alongside the text.
3. ~~The class-vocabulary refusals keep `refused=False`~~ — fixed in the follow-up to
   PR #794's finding 3: they now set `refused=True` (asserted in `TC-CONSOLE-65`).

**Isolation: rung 3 (E1)** — real store, real console over real HTTP, the recorded
provider where an authoring fixture is needed.
"""

from __future__ import annotations

import json
import re

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
from tests.support.console_redesign_world import (
    _action,
    _request,
    draft_read,
    run_draft_job,
    served_authoring,
    served_console,
)
from tests.support.console_world import seed_scored_run

pytestmark = pytest.mark.integration

#: The fragments `CT-CONSOLE-33` bans from a teacher-facing body: a traceback fragment,
#: an exception class name (with or without its colon), and a bare 4xx/5xx status token.
TRACEBACK_FRAGMENT = "Traceback"
EXCEPTION_COLON = re.compile(r"\b\w+Error:")
EXCEPTION_NAME = re.compile(r"\b\w+(?:Error|Exception|Warning)\b")
STATUS_TOKEN = re.compile(r"\b[45]\d{2}\b")
LEADING_EXCEPTION = re.compile(r"\A\w+(?:Error|Exception|Warning):")


def _scan_body(arm: str, body: dict) -> None:
    """The response-body text scan the TC's oracle names, over one refusal body."""
    text = json.dumps(body)
    assert TRACEBACK_FRAGMENT not in text, (
        f"the {arm} refusal carries a traceback fragment: {text[:400]!r}")
    assert not EXCEPTION_COLON.search(text), (
        f"the {arm} refusal names an exception class: "
        f"{EXCEPTION_COLON.search(text).group()!r} in {text[:400]!r}")
    assert not STATUS_TOKEN.search(text), (
        f"the {arm} refusal carries an HTTP-status token: "
        f"{STATUS_TOKEN.search(text).group()!r} in {text[:400]!r}")
    detail = str(body.get("detail") or body.get("error") or "")
    assert detail.strip(), f"the {arm} refusal carries no teacher detail: {body!r}"
    assert not LEADING_EXCEPTION.match(detail), (
        f"the {arm} refusal opens with an exception name: {detail[:120]!r}")
    for sentence in (body.get("next_action"), body.get("error")):
        if sentence:
            assert not EXCEPTION_NAME.search(str(sentence)), (
                f"the {arm} refusal's next step names an exception: {sentence!r}")


def _refusal_of(port: int, action: str, params: dict) -> dict:
    answer = _action(port, action, params)
    assert answer["refused"] is True, f"the {action} arm was not refused: {answer!r}"
    assert answer["dispatched"] is False
    return answer


def test_tc_console_71_the_authoring_refusals_speak_teacher_language(served_authoring):
    """The refusing arms of the authoring actions — the invalid edit, the approval of an
    unfinished draft, the cancel of a finished job — scanned as bodies."""
    _server, port, _store, _data_dir = served_authoring

    # The invalid edit (TC-CONSOLE-63's arm): a question with no text.
    _a, record = run_draft_job(port, "AF-02")
    package_id = draft_read(port)["draft"]["package_id"]
    edit = _refusal_of(port, "edit draft package", {
        "package_id": package_id, "operation": "add question",
        "question_type": "open", "text": "   ",
    })
    _scan_body("invalid edit", edit)
    assert "the edit carries no text" in edit["detail"]
    assert "Nothing was saved." in edit["detail"]
    assert re.search(r"question '\w+'", edit["detail"]), (
        f"the refusal does not name the question it was about: {edit['detail']!r}")

    # The unfinished approval (TC-CONSOLE-64's arm): AF-09 still carries placeholders.
    _a2, draft_record = run_draft_job(port, "AF-09")
    assert draft_record["state"] == "succeeded"
    af09_package = draft_read(port)["draft"]["package_id"]
    approval = _refusal_of(port, "approve draft package",
                           {"package_id": af09_package})
    _scan_body("unfinished approval", approval)
    # #808 (FR-UI-25): the approve refusal speaks the teacher's three parts.
    assert approval["detail"].startswith(f"{af09_package} was not published.")
    assert approval["next_action"] == (
        "Answer the remaining questions on the review screen, then press Approve again.")

    # The finished job's cancel (TC-CONSOLE-70's arm): the AF-02 job already succeeded.
    cancel = _refusal_of(port, "cancel job", {"job_id": record["job_id"]})
    _scan_body("finished-job cancel", cancel)
    assert cancel["detail"] == (
        f"the job {record['job_id']} is already succeeded; there is nothing to "
        "cancel.")
    assert cancel["next_action"] == (
        "open the job on the jobs page; its outcome and the files it wrote are "
        "listed there.")


def test_tc_console_71_the_reads_the_unknown_job_and_the_stale_item_speak_teacher_language(
        served_console):
    """The refusing reads answer 400 with the teacher's sentence; the cancel of a job
    nothing runs; the stale review item's refusal names the supersession and asks for a
    refresh."""
    _server, port, store, _data_dir = served_console
    seeded = seed_scored_run(store, cohort_id="c-rs", run_id="r-rs", package_id="pkg-rs",
                             submissions=2, with_open_criteria=True, finalize=False)

    # The unknown package version (TC-CONSOLE-60's read refusal).
    status, _headers, raw = _request(
        port, "GET", "/api/v1/impact?package_version=pkg-rs@nosuch")
    body = json.loads(raw)
    assert status == 400, f"the unknown version answered {status}: {body!r}"
    _scan_body("unknown version read", body)
    assert body["error"] == (
        "There is no test package version with that reference. "
        "Choose one from the list on the package page.")

    # The cancel of a job nothing runs.
    cancel = _refusal_of(port, "cancel job", {"job_id": "no-such-job"})
    _scan_body("unknown-job cancel", cancel)
    assert cancel["detail"] == (
        "no job named no-such-job is running; the jobs page lists this console's "
        "jobs, and the runs screen lists its runs.")

    # The stale review item: the score the queue built is superseded before the
    # teacher's review posts, and the refusal says so (CT-REVIEW-15's check).
    cohort = store.cohort(seeded.cohort_id)
    with cohort.transaction() as tx:
        tx.execute(
            "INSERT OR REPLACE INTO criterion_score (run_id, submission_id, "
            "criterion_id, band, points, judge_count, routing, state) "
            "VALUES (:r, :s, 'C-10', 'B2', 2.0, 3, 'queued', 'provisional_unreviewed')",
            r=seeded.run_id, s=seeded.submissions[0],
        )
    with cohort.transaction() as tx:
        tx.execute(
            "UPDATE criterion_score SET band = 'B3', points = 3.0, judge_count = 5 "
            "WHERE submission_id = :s AND criterion_id = 'C-10'",
            s=seeded.submissions[0],
        )
    stale_status, _headers, stale_raw = _request(
        port, "POST", "/api/v1/actions/review-action", {
            "run_id": seeded.run_id, "submission_id": seeded.submissions[0],
            "criterion_id": "C-10", "band": "B3", "revision": 1,
        })
    stale = json.loads(stale_raw)
    assert stale_status == 200
    assert stale["refused"] is True and stale["dispatched"] is False, stale
    # PR #794's finding 4 fixed: `outcome_json` carries the outcome's `refresh_required`
    # when the staleness refusal set it, so the SPA reads the refresh request from the
    # body, not only out of the detail text.
    assert stale.get("refresh_required") is True, (
        f"the staleness body does not carry the refresh request the outcome set: "
        f"{stale!r}")
    _scan_body("stale review item", stale)
    assert "is stale" in stale["detail"] and "superseded" in stale["detail"], (
        f"the refusal does not name the supersession: {stale['detail']!r}")
    assert "refresh the queue before acting" in stale["detail"], (
        f"the refusal does not tell the teacher to refresh: {stale['detail']!r}")
