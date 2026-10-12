"""`TC-CONSOLE-68` (issue #771, FR-CONSOLE-51, CT-CONSOLE-09) — the issues and logs
reads: the run's trouble, in the teacher's words, sourced from the store's own rows.

| Arm | Expected |
|---|---|
| (a) a run with a failed grading step, two second-opinion requests, a tripped breaker and a parked paper | five issue records, each with its `what` / `affects` / `next_step` in teacher language, and the sources counted beside them |
| (b) the same run's logs | only store-held records: the run's milestones, one summary per stage that holds work, one record per group of failed steps — and **nothing** for a stage that holds none (`CT-CONSOLE-09`: no invented lines, no captured stderr) |
| (c) a run no ledger holds | both reads refuse with the switcher sentence |

The rows are written directly, in the column shape the shipped writers produce (the
`console_world` disclosure): the failed step, the escalations and the breaker are the
`M-ORCH` tables' own shape, the parked paper the `M-INGEST` flag's.

**Isolation: rung 3 (E1)** — a real store, a real console on a real loopback socket; both
reads taken over the console's own HTTP surface, refusals included.
"""

from __future__ import annotations

import json

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
    _get_json,
    _request,
    served_console,
)
from tests.support.console_world import STAMP, seed_scored_run

pytestmark = pytest.mark.integration

COHORT = "c-iss"
RUN = "r-iss"
PACKAGE = "pkg-iss"
SUBMISSION_A = "sub-c-iss-01"
SUBMISSION_B = "sub-c-iss-02"


def _seed_trouble(store) -> None:
    """Seed one scored run and write the trouble beside it: one failed grading step, one
    admitted and one waiting second-opinion request, one tripped breaker, one parked
    paper."""
    seed_scored_run(store, cohort_id=COHORT, run_id=RUN, package_id=PACKAGE,
                    submissions=2, finalize=True)
    cohort = store.cohort(COHORT)
    with cohort.transaction() as tx:
        tx.execute(
            "INSERT INTO work_unit (work_id, run_id, submission_id, stage, status, "
            "criterion_id, judge_id, attempts, last_error) "
            "VALUES (:w, :r, :s, 'judged', 'failed', 'C-10', 'j-1', 2, "
            "'JudgeTimeoutError: judge did not answer in time')",
            w="wu-f1", r=RUN, s=SUBMISSION_A,
        )
        for request_id, admitted, moment in (
            ("esc-1", 1, STAMP), ("esc-2", 0, STAMP),
        ):
            tx.execute(
                "INSERT INTO escalation_request (request_id, run_id, submission_id, "
                "criterion_id, expected_value, admitted, requested_at, admitted_at, "
                "detail) VALUES (:q, :r, :s, 'C-10', 3.0, :a, :t, :at, :d)",
                q=request_id, r=RUN, s=SUBMISSION_A, a=admitted, t=moment,
                at=STAMP if admitted else None,
                d="panel second opinion" if admitted else None,
            )
        tx.execute(
            "INSERT INTO circuit_breaker (breaker_id, run_id, criterion_id, kind, "
            "tripped_at, detail) VALUES (:b, :r, 'C-10', 'criterion_escalation', "
            ":t, :d)",
            b="brk-1", r=RUN, t=STAMP, d="too many second opinions for one point",
        )
        tx.execute(
            "UPDATE submission SET quarantined = 1, ingest_status = 'unreadable' "
            "WHERE submission_id = :s",
            s=SUBMISSION_B,
        )
        # The run's own milestones: the clock stamps the logs read renders.
        tx.execute(
            "UPDATE run SET started_at = :t, completed_at = :t, status = 'paused', "
            "pause_reason = 'PauseRequested: paused from the console' WHERE run_id = :r",
            t=STAMP, r=RUN,
        )


def _issues_by_id(issues: list[dict]) -> dict[str, dict]:
    return {issue["issue_id"]: issue for issue in issues}


def test_tc_console_68a_the_issues_read_names_each_trouble_in_teacher_language(
        served_console):
    """The five trouble records, each saying what happened, what it affects and the next
    step — no exception names, no store identifiers where a teacher word exists."""
    _server, port, store, _data_dir = served_console
    _seed_trouble(store)

    payload = _get_json(port, f"/api/v1/issues?run_id={RUN}")

    issues = _issues_by_id(payload["issues"])
    assert sorted(issues) == [
        "breaker:brk-1", "escalation:esc-1", "escalation:esc-2",
        "parked:sub-c-iss-02", "work-unit:wu-f1",
    ], f"the read answered {sorted(issues)}"

    step = issues["work-unit:wu-f1"]
    assert step["source"] == "grading step"
    assert step["what"] == "A grading step gave up after 2 tries.", step["what"]
    assert step["affects"] == "The paper it was grading may be missing a score."
    assert step["next_step"] == "Use the console's recover action to pick the work back up."

    parked = issues["parked:sub-c-iss-02"]
    assert parked["source"] == "parked paper"
    assert parked["what"] == "A paper could not be read."
    assert parked["affects"] == "That paper is parked; its marks are not graded."
    assert parked["next_step"] == (
        "Upload a clearer scan of the paper from the parked page, or mark it "
        "unresolvable.")

    admitted = issues["escalation:esc-1"]
    assert admitted["source"] == "second opinion"
    assert admitted["what"] == "A grading point needed a second opinion."
    assert admitted["affects"] == (
        "That score took longer to settle; the result is unchanged.")
    assert admitted["next_step"] == (
        "Nothing to do — the second opinion is part of the check.")

    waiting = issues["escalation:esc-2"]
    assert waiting["what"] == "A grading point is waiting for a second opinion slot."
    assert waiting["affects"] == "That score is not settled yet."
    assert waiting["next_step"] == "Wait: the run admits it when the budget allows."

    breaker = issues["breaker:brk-1"]
    assert breaker["source"] == "grading point"
    assert breaker["what"] == (
        "One grading point needed too many second opinions, so second opinions for it "
        "were stopped.")
    assert breaker["affects"] == (
        "Scores on that grading point may need review before exporting.")
    assert breaker["next_step"] == "Review that grading point's scores before exporting."

    assert payload["projected"] == {
        "issues": 5,
        "sources": {"grading step": 1, "parked paper": 1, "second opinion": 2,
                    "grading point": 1},
        "ledgers_skipped": 0,
    }


def test_tc_console_68b_the_logs_read_carries_only_the_records_the_store_holds(
        served_console):
    """The run's logs: its milestones, one summary for the stage that holds work, one
    record for the failed step with the exception name stripped — and no summary for a
    stage that holds nothing."""
    _server, port, store, _data_dir = served_console
    _seed_trouble(store)

    payload = _get_json(port, f"/api/v1/logs?run_id={RUN}")

    records = payload["records"]
    assert len(records) == 4, (
        f"the read answered {len(records)} record(s): "
        f"{[record['record_id'] for record in records]}")
    assert all(record["record_id"].startswith(f"run:{RUN}:") for record in records), (
        "a record's id does not carry the run prefix; nothing may be invented")
    first, summary, problem, last = records

    assert first == {
        "record_id": f"run:{RUN}:started", "kind": "milestone", "stage": "The run",
        "at": STAMP, "text": "The grading run started.", "detail": None,
    }
    assert summary == {
        "record_id": f"run:{RUN}:stage:Grading the written answers",
        "kind": "summary", "stage": "Grading the written answers", "at": None,
        "text": "Grading the written answers — 1 failed.", "detail": None,
    }
    assert problem["kind"] == "problem"
    assert problem["text"] == "1 step gave up at grading point C-10.", problem["text"]
    assert problem["detail"] == "judge did not answer in time", (
        f"the problem record's detail is {problem['detail']!r}; the exception class "
        "name must be stripped (CT-CONSOLE-33)")
    assert last == {
        "record_id": f"run:{RUN}:paused", "kind": "milestone", "stage": "The run",
        "at": STAMP, "text": "The grading run was paused.", "detail": None,
    }

    stages = {record["stage"] for record in records if record["kind"] == "summary"}
    assert "Reading the papers" not in stages, (
        "a stage with no work units must show nothing — no empty placeholder claim "
        "(CT-CONSOLE-09)")
    assert payload["page"] == {"size": 200, "shown": 4, "more_available": False}
    assert payload["projected"] == {
        "records": 4, "sources": {"run": 2, "stage": 1, "problem": 1},
        "ledgers_skipped": 0,
    }


def test_tc_console_68c_a_run_no_ledger_holds_is_refused_with_the_switcher_sentence(
        served_console):
    """Both reads refuse an unknown run with the teacher's sentence — they do not answer
    empty records about something that does not exist."""
    _server, port, _store, _data_dir = served_console

    for path in (f"/api/v1/issues?run_id={RUN}", f"/api/v1/logs?run_id={RUN}"):
        status, _headers, raw = _request(port, "GET", path)
        body = json.loads(raw)
        assert status == 400, f"GET {path} answered {status}: {body!r}"
        assert body["error"] == (
            "There is no grading run with that reference. "
            "Choose one from the switcher."), f"the refusal body is {body!r}"
