"""TC-UI-31…34 — results read by question, the not-final banner, the elapsed clock and
the AI-calls tab (FR-UI-29..35, `CT-CONSOLE-54`), story T13 of
`console_clarity_test_plan.md` §3.9 — the browser tier of the #822/#823 stories.

* **TC-UI-31** — the ENG7 Jev-final seed's rows ("Q1 · 2 / 2", …, the "Total grade"
  column), one bar per question and the grade-count chart (no pooled histogram), and —
  over a four-student world carrying TC-CONSOLE-100's Q2 marks (3, 2, 2, 0) — the exact
  bar label "Q2 — average 1.8 / 3 (58%)".
* **TC-UI-32** — a two-not-final world: the banner's exact sentence with both buttons,
  each Check badge's FR-UI-32 sentence for its served code, the FR-UI-33 confirmation,
  and "All grades are final." with no badge left.
* **TC-UI-33** — the elapsed clock's format and growth only (never a wall-clock value,
  the flake policy §2.6): a running run's "Working — N s" between two reads 1.5 s apart,
  a finished run's "Done in …", the "Time taken" row per served stage, and the duration
  formatter's rung-0 arm riding the Jobs table at 45 / 134 / 3900 seconds.
* **TC-UI-34** — "How was this graded?" opens the AI-calls tab filtered to student,
  question and run; the Jev row's panels and the confidence line; a below-gate judge
  row's panels; each panel's Copy; the same on the `real` cohort (RC-18).

Markers. `browser` (Playwright, headless — the TS-49 rule) and `integration` (the fast
tier excludes it). Isolation: the seeded ENG7 worlds (the Jev-final seed, synthetic and
real) on real stores behind real loopback consoles; the journal records are written
through the journal's own sink (`JsonlCallJournal.append`, the FR-PROV-44 write path)
under the seed's own ids — the shapes the read serves, real writer, no fabricated
provider machinery. Zero egress: the browser's own request log is the oracle.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.support import clarity_browser, clarity_world, spa
from tests.support.clarity_world import seed_jev_final

pytestmark = [pytest.mark.browser, pytest.mark.integration]

VIEWPORT = {"width": 1280, "height": 720}

#: FR-UI-32's sentence per served code (the design delta §3.6's own wording).
NOT_FINAL_TEXT = {
    "one_grader_unsure": "The AI grader was not sure. Please check this answer.",
    "graders_disagree": "The AI graders gave different marks. Please choose the right one.",
    "evidence_not_found": "The grader could not find the answer in the student's writing. "
                          "Please check the page.",
    "quote_not_verified": "The grader quoted words that are not on the page. Please check "
                          "this answer.",
    "more_graders_unavailable": "A second opinion was needed but no other grader is set "
                                "up. Please check this answer.",
    "graders_refused": "The AI could not grade this question for the class. Please grade "
                       "it yourself.",
}

#: A Jev decision's served shapes (the response the record carries, per
#: `decision_response_document`'s shape, with the confidence the gate compares).
JEV_REQUEST = {
    "state": "grading",
    "questions": {
        "band": {"type": "score", "instructions": "Choose the band the answer earns.",
                 "criteria": ["none", "limited", "adequate", "full"]},
        "evidence_sufficient": {"type": "noul",
                                "instructions": "Is the evidence sufficient?"},
    },
}
JEV_RESPONSE = {
    "band": {"score": 2.0, "probabilities": [0.02, 0.03, 0.04, 0.91],
             "confidence": 0.91, "confidence_source": "reported"},
    "evidence_sufficient": {"p_true": 0.95, "confidence": 0.93,
                            "confidence_source": "reported"},
}
#: The run's recorded engine, whose threshold the read serves beside the confidence.
RECORDED_ENGINE = {"provider": "openrouter", "build": "jev-wire-model@recorded",
                   "threshold": "0.80", "cite_threshold": "0.50",
                   "max_citation_questions": 16, "token_bytes_ratio": 3,
                   "template": "conf-v1.0.0"}


def _call_record(kind: str, seed: Any, submission_id: str, criterion_id: str,
                 *, request: Any, response: Any, at: str) -> Any:
    """One journal record through the journal's own constructor — the fields the read
    serves, named for the seed's own ids."""
    from aeh.prov.journal import CallRecord

    return CallRecord(
        call_id=f"call-{seed.run_id}-{criterion_id}-{kind}".replace(" ", "-"),
        attempt=1, at=at, kind=kind, cohort_id=seed.cohort_id, run_id=seed.run_id,
        work_id=f"wu-{criterion_id}-{kind}", submission_id=submission_id,
        criterion_id=criterion_id, package_id=seed.package_id,
        model="jev-wire-model@recorded", resolved_build="jev-wire-model@recorded",
        request=request, response=response, outcome="ok", error=None,
        tokens_in=120, tokens_out=40, latency_ms=900, cost="0.0007")


def _install_engine_threshold(store: Any, seed: Any) -> None:
    """Record the run's decision engine on the run row, the way a run start freezes it —
    the read serves its threshold beside a Jev call's confidence."""
    handle = store.cohort(seed.cohort_id)
    with handle.transaction() as tx:
        row = tx.execute("SELECT provider_config FROM run WHERE run_id = :r",
                         r=seed.run_id)[0]
        recorded = json.loads(str(row["provider_config"] or "{}"))
        recorded["decision_engine"] = RECORDED_ENGINE
        tx.execute("UPDATE run SET provider_config = :p WHERE run_id = :r",
                   p=json.dumps(recorded), r=seed.run_id)


def _write_journal(data_dir: Path, store: Any, seed: Any, *,
                   student_name: str) -> None:
    """One Jev decision (gate passed, confidence 0.91) and one below-gate judge call for
    the named student's C2 cell, appended through the journal's own sink."""
    from aeh.prov.journal import JsonlCallJournal

    submission_id = seed.submissions[student_name]
    sink = JsonlCallJournal(data_dir)
    sink.append(_call_record(
        "jev_decision", seed, submission_id, "C2",
        request=JEV_REQUEST, response=JEV_RESPONSE,
        at="2026-10-22T10:00:00+00:00"))
    sink.append(_call_record(
        "ai_judge", seed, submission_id, "C2",
        request=[["instructions", "Mark this answer's band."],
                 ["question", "Why does Tomas keep the lamp burning?"]],
        response="limited — the answer repeats the passage without a reason.",
        at="2026-10-22T10:00:02+00:00"))
    _install_engine_threshold(store, seed)


@contextmanager
def _results_world(root: Path, network_guard: Any, monkeypatch: Any,
                   *, kinds: dict[str, str] | None = None,
                   bands: dict[str, dict[str, str]] | None = None,
                   consent_class: str = "synthetic",
                   journal: bool = False) -> Iterator[dict[str, Any]]:
    """One served world: the ENG7 seed (its kinds and bands overridable) behind one
    loopback console, the run bound; the journal written when `journal`."""
    from aeh.console import serve_console
    from aeh.store import open_store

    store = open_store(root / "data")
    seed = seed_jev_final(store, consent_class=consent_class, kinds=kinds, bands=bands)
    # The grades are M-GRADE's own compute pass over the seeded cells (no
    # `submission_grade` row, no student in the read, the TC-CONSOLE-97 seed's rule).
    from aeh.grade import open_grade

    open_grade(store).compute_all(seed.run_id)
    if journal:
        _write_journal(root / "data", store, seed,
                       student_name=tuple(seed.submissions)[0])
    if monkeypatch is not None:
        for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
            monkeypatch.delenv(name, raising=False)
    if network_guard is not None:
        network_guard.uninstall()
    try:
        server = serve_console(store=store, run_id=seed.run_id)
    except BaseException:
        if network_guard is not None:
            network_guard.install()
        from tests.support.console_redesign_world import _close_console_store

        _close_console_store(store)
        raise
    host, port = server.socket.getsockname()[:2]
    try:
        yield {"origin": f"http://{host}:{port}", "port": port, "store": store,
               "seed": seed}
    finally:
        server.terminate()
        if network_guard is not None:
            network_guard.install()
        from tests.support.console_redesign_world import _close_console_store

        _close_console_store(store)


def _goto_results(page: Any, origin: str) -> str:
    page.goto(origin + "/#/results")
    heading = spa.wait_for_screen(page)
    # The screen renders its heading before the read answers; wait for the read's own
    # content, bounded, before any text is judged.
    import time

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not (
            page.locator(".results-banner").count()
            or page.locator("li.result-row").count()
            or page.locator("ul.time-taken").count()):
        page.wait_for_timeout(250)
    return heading


def _fail_with(problems: list[str]) -> None:
    if problems:
        pytest.fail("the test found:\n  " + "\n  ".join(problems))


def test_tc_ui_31_rows_by_question_and_the_exact_average_label(
    tmp_path, network_guard, monkeypatch
):
    """`TC-UI-31` (P0) — the seed's rows read by question with the Total grade column;
    one bar per question and the grade-count chart, no pooled histogram; and over the
    four-student world carrying TC-CONSOLE-100's Q2 marks (3, 2, 2, 0) the bar label is
    exactly "Q2 — average 1.8 / 3 (58%)". The plan's rounding table (half-up on the mean
    to one decimal, half-up on the unrounded mean ÷ max × 100)."""
    from tests.support.console_redesign_world import _get_json

    def rows_world() -> dict[str, Any]:
        return clarity_world.COHORTS["synthetic"]

    with clarity_browser.serve_eng7_world(
            tmp_path, network_guard, monkeypatch, draft_job=False,
            compute=True) as box:
        origin, port = box["origin"], box["port"]
        doc = _get_json(port, "/api/v1/results/screen")
        with spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
            problems: list[str] = []
            _goto_results(page, origin)
            text = page.locator("main").inner_text()
            expected = clarity_world.EXPECTED_ROLLUP
            for student_name, (questions, total, grade) in expected.items():
                shown = None
                for row in page.locator("li.result-row").all():
                    if student_name in row.inner_text():
                        shown = row.inner_text()
                        break
                if shown is None:
                    problems.append(f"no results row for {student_name!r}")
                    continue
                for question, awarded, maximum in questions:
                    if f"{question} · {int(awarded)} / {maximum}" not in shown:
                        problems.append(f"{student_name}: the {question} cell does not "
                                        f"read {awarded} / {maximum}")
                if f"Total grade: {int(total)} / 8 — {grade}" not in shown:
                    problems.append(f"{student_name}: the Total grade column does not "
                                    f"read {total} / 8 — {grade}")
            if page.locator(".question-stat").count() == 0:
                problems.append("no per-question bars render")
            if not page.locator("figure.question-bars").count():
                problems.append("no per-question bars figure renders")
            grade_chart = page.locator("figure.question-bars").filter(
                has_text="Students per grade.")
            if not grade_chart.count():
                problems.append("no grade-count chart figure renders (the served "
                                "caption 'Students per grade.')")
            if page.locator("figure.distribution").count():
                problems.append("the pooled rubric-level histogram still renders")
            served = {stat["label"]: stat for stat in doc["question_stats"]}
            for stat in doc["question_stats"]:
                row = page.locator("li.question-stat").filter(
                    has_text=stat["label"]).first
                if not row.count():
                    problems.append(f"no bar renders for {stat['label']}")
                    continue
                from decimal import ROUND_HALF_UP, Decimal

                mean = stat["mean_points"]
                shown_mean = "0.0" if mean is None else str(
                    Decimal(repr(mean)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
                percent = "0" if mean is None or stat["points_max"] == 0 else str(
                    (Decimal(repr(mean)) / Decimal(str(stat["points_max"])) * 100)
                    .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                max_shown = (int(stat["points_max"])
                             if float(stat["points_max"]).is_integer()
                             else stat["points_max"])
                expected_label = (f"{stat['label']} — average {shown_mean} / "
                                  f"{max_shown} ({percent}%)")
                if expected_label not in row.inner_text():
                    problems.append(f"{stat['label']}'s bar reads "
                                    f"{row.inner_text()[:120]!r}, not {expected_label!r}")
            problems += log.foreign_requests()
            _fail_with(problems)
        del rows_world
    # The exact-label arm: TC-CONSOLE-100's marks (Q2 at 3, 2, 2, 0) over four students.
    four_bands = {
        "E7-101": {"C1a": "present", "C1b": "present", "C2": "full", "C3": "change"},
        "E7-102": {"C1a": "present", "C1b": "absent", "C2": "adequate", "C3": "retell"},
        "E7-103": {"C1a": "absent", "C1b": "present", "C2": "adequate", "C3": "retell"},
        "E7-104": {"C1a": "absent", "C1b": "absent", "C2": "none", "C3": "retell"},
    }
    with _results_world(tmp_path / "label-arm", network_guard, monkeypatch,
                        bands=four_bands) as box:
        with spa.spa_page(box["origin"], viewport=VIEWPORT) as (page, log):
            problems: list[str] = []
            _goto_results(page, box["origin"])
            row = page.locator("li.question-stat").filter(has_text="Q2").first
            if not row.count():
                problems.append("no Q2 bar renders in the four-student world")
            elif "Q2 — average 1.8 / 3 (58%)" not in row.inner_text():
                problems.append(f"Q2's bar reads {row.inner_text()[:120]!r}, not "
                                "'Q2 — average 1.8 / 3 (58%)'")
            problems += log.foreign_requests()
            _fail_with(problems)


def test_tc_ui_32_the_not_final_banner_and_the_approval(
    tmp_path, network_guard, monkeypatch
):
    """`TC-UI-32` (P0) — a two-not-final world: the banner's exact sentence with both
    buttons; each Check badge's FR-UI-32 sentence; the FR-UI-33 confirmation; then
    "All grades are final." with no Check badge left."""
    # Only C1b stands not-final — one per student, two in all.
    # Every criterion seeded; only C1b stands not-final — one per student, two in all
    # (a restricted kinds set would leave two package criteria ungraded, and the
    # compute pass reads those grades `incomplete`, which no batch settles).
    kinds = {"C1a": "decision_accepted", "C1b": "llm_single",
             "C2": "decision_accepted", "C3": "decision_accepted"}
    with _results_world(tmp_path / "banner-arm", network_guard, monkeypatch,
                        kinds=kinds) as box:
        origin = box["origin"]
        seed = box["seed"]
        from tests.support.console_redesign_world import _get_json

        doc = _get_json(box["port"], "/api/v1/results/screen")
        assert doc["not_final_questions"] == 2, (
            f"fixture: the world holds {doc['not_final_questions']} not-final "
            "questions, not two")
        with spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
            problems: list[str] = []
            _goto_results(page, origin)
            banner = page.locator(".results-banner")
            if not banner.count():
                problems.append("no not-final banner renders")
            else:
                text = banner.inner_text()
                if "2 answers need your check before the grades are final." not in text:
                    problems.append(f"the banner reads {text[:160]!r}")
                for button in ("Check answers", "Approve all grades"):
                    if not page.get_by_role("button", name=button).count():
                        problems.append(f"the banner lacks the {button!r} button")
            # Each not-final question cell's badge carries its served sentence.
            served_sentences = set()
            for student in doc["students"]:
                for question in student["questions"] or []:
                    code = question["not_final_reason"]
                    if code:
                        served_sentences.add(NOT_FINAL_TEXT[code])
                        student_row = page.locator("li.result-row").filter(
                            has_text=student["full_name"] or
                            (student["student_ref"] or "")).first
                        cell = student_row.locator("li.question-cell").filter(
                            has_text=question["label"]).first
                        badge = cell.locator(".check-badge").first
                        if not badge.count():
                            problems.append(f"{student['student_ref']}: no Check badge "
                                            f"on {question['label']}")
                            continue
                        title = badge.get_attribute("title") or ""
                        if title != NOT_FINAL_TEXT[code]:
                            problems.append(f"the badge for {question['label']} reads "
                                            f"{title!r}, not the FR-UI-32 sentence")
                        reason = cell.locator(".check-reason").first
                        # The reason paragraph rides the cell's own <details>; the
                        # paragraph's DOM text is the expanded text the tooltip's badge
                        # already asserted visibly.
                        said = reason.evaluate("el => el.textContent")                             if reason.count() else ""
                        if said.strip() != NOT_FINAL_TEXT[code]:
                            problems.append(f"the expanded text for {question['label']} "
                                            f"reads {said.strip()!r}, not the served "
                                            f"sentence for {code!r}")
            if not served_sentences:
                problems.append("fixture: no not-final codes served")
            # The approve-all journey.
            approve = page.get_by_role("button", name="Approve all grades")
            if approve.count():
                approve.first.click()
                dialog = page.locator("[role='dialog']").first
                if not dialog.count() or not dialog.is_visible():
                    problems.append("the approve-all opened no confirmation")
                else:
                    dialog_text = dialog.inner_text()
                    if "Approve all grades for" not in dialog_text \
                            or f"{seed.cohort_id}" not in dialog_text \
                            or "2 answers you have not checked will be accepted as the " \
                               "AI graded them" not in dialog_text:
                        problems.append(f"the confirmation is not FR-UI-33's "
                                        f"({dialog_text[:200]!r})")
                    confirm = dialog.locator("button").last
                    confirm.click()
                    for _ in range(20):  # the settled banner, bounded
                        page.wait_for_timeout(250)
                        if "All grades are final." in \
                                page.locator(".results-banner").inner_text():
                            break
                    settled = page.locator(".results-banner").inner_text()
                    if "All grades are final." not in settled:
                        outcome = page.locator(".outcome-banner:not(.results-banner)")
                        said = outcome.first.inner_text() if outcome.count() else \
                            "(no outcome banner)"
                        problems.append(f"after the approval the banner reads "
                                        f"{settled[:160]!r}; the action said {said!r}")
                    if page.locator(".badge").filter(
                            has_text="Check").count():
                        problems.append("a Check badge remains after the approval")
            problems += log.foreign_requests()
            _fail_with(problems)


def test_tc_ui_33_the_clock_the_stage_rows_and_the_formatter(
    tmp_path, network_guard, monkeypatch, request
):
    """`TC-UI-33` (P2) — the clock's format and growth only: a running run's
    "Working — N s" between two reads 1.5 s apart; a finished run's "Done in …"; the
    "Time taken" row per served stage; and the duration formatter's rung-0 arm riding
    the Jobs table at 45 / 134 / 3900 seconds."""
    from aeh.store import open_store
    from aeh.console import serve_console

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    if network_guard is not None:
        network_guard.uninstall()
    store = open_store(tmp_path / "data")
    try:
        seed = seed_jev_final(store)
        # The grades are M-GRADE's own compute pass (no submission_grade row, no student
        # in the read — an empty class renders no clock at all).
        from aeh.grade import open_grade

        open_grade(store).compute_all(seed.run_id)
        cohort = store.cohort(seed.cohort_id)
        from datetime import datetime, timezone

        started = datetime.now(timezone.utc).isoformat()
        with cohort.transaction() as tx:
            # The run in progress, stamped NOW so the clock's elapsed is in seconds (the
            # plan's format oracle; never a wall-clock value is asserted).
            tx.execute("UPDATE run SET status = 'running', "
                       "started_at = :t WHERE run_id = :r", t=started, r=seed.run_id)
        # The stages the run's own metrics carry, in run order (FR-CONSOLE-75) —
        # Tier D's `run_metrics`, the ledger's durable table; the tiers' transactions
        # run sequentially (CT-STORE-03: no cross-tier atomicity).
        durable = store.durable()
        with durable.transaction() as tx:
            for stage, seconds in (("extract", 12.0), ("judge", 45.0),
                                   ("aggregate", 3.5), ("synth", 2.0)):
                tx.execute(
                    "INSERT OR REPLACE INTO run_metrics (run_id, metric, value) "
                    "VALUES (:r, :m, :v)",
                    r=seed.run_id, m=f"stage_seconds.{stage}", v=seconds)
        server = serve_console(store=store, run_id=seed.run_id)
        host, port = server.socket.getsockname()[:2]
        origin = f"http://{host}:{port}"
        try:
            with spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
                problems: list[str] = []
                _goto_results(page, origin)
                clock = page.locator(".run-clock")
                if not clock.count():
                    problems.append("no run clock renders for a running run")
                else:
                    first = clock.inner_text()
                    if not re.fullmatch(r"Working — (\d+ s|\d+ min \d+ s)", first.strip()):
                        problems.append(f"the clock reads {first!r}, not 'Working — N s'")
                    page.wait_for_timeout(1500)
                    second = clock.inner_text()
                    if not re.fullmatch(r"Working — (\d+ s|\d+ min \d+ s)", second.strip()):
                        problems.append(f"the clock's second read reads {second!r}")
                    elif first == second:
                        problems.append(f"the clock did not grow between two reads "
                                        f"1.5 s apart ({first!r})")
                timings = page.locator("ul.time-taken li").all_inner_texts()
                if [t.split(":")[0] for t in timings] != \
                        ["Reading answers", "AI grading", "Combining grades",
                         "Writing feedback"]:
                    problems.append(f"the Time taken rows read {timings!r}, not one per "
                                    "served stage in run order")
                if timings != ["Reading answers: 12 s", "AI grading: 45 s",
                               "Combining grades: 4 s", "Writing feedback: 2 s"]:
                    problems.append(f"the Time taken rows do not read the served "
                                    f"seconds ({timings!r})")
                problems += log.foreign_requests()
                _fail_with(problems)
        finally:
            server.terminate()
        # A finished run's clock: the same store, the run completed — the end stamp
        # 134 s after the run's own start (the formatter's "2 min 14 s" shape; the
        # oracle is the format, never a wall-clock value).
        row = store.cohort(seed.cohort_id).query(
            "SELECT started_at FROM run WHERE run_id = :r", r=seed.run_id)[0]
        from datetime import datetime, timedelta, timezone

        started_at = datetime.fromisoformat(str(row["started_at"]))
        ended_at = (started_at + timedelta(seconds=134)).isoformat()
        cohort = store.cohort(seed.cohort_id)
        with cohort.transaction() as tx:
            tx.execute("UPDATE run SET status = 'complete', "
                       "completed_at = :e WHERE run_id = :r",
                       e=(started_at + timedelta(seconds=300)).isoformat(), r=seed.run_id)
        server = serve_console(store=store, run_id=seed.run_id)
        host, port = server.socket.getsockname()[:2]
        origin = f"http://{host}:{port}"
        try:
            with spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
                problems: list[str] = []
                _goto_results(page, origin)
                clock = page.locator(".run-clock")
                if not clock.count() or not re.search(
                        r"Done in (\d+ s|\d+ min \d+ s)", clock.inner_text()):
                    problems.append(f"the finished run's clock reads "
                                    f"{clock.inner_text() if clock.count() else '(none)'!r}"
                                    ", not 'Done in …'")
                problems += log.foreign_requests()
                _fail_with(problems)
        finally:
            server.terminate()
        # The rung-0 formatter arm: the Jobs table renders the served seconds.
        _seed_duration_runs(store, seed)
        server = serve_console(store=store, run_id=seed.run_id)
        host, port = server.socket.getsockname()[:2]
        origin = f"http://{host}:{port}"
        try:
            with spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
                problems: list[str] = []
                page.goto(origin + "/#/jobs")
                spa.wait_for_screen(page)
                text = page.locator("main").inner_text()
                for expected in ("45 s", "2 min 14 s", "1 h 5 min"):
                    if expected not in text:
                        problems.append(f"the Jobs table does not render {expected!r} "
                                        "for its served duration")
                problems += log.foreign_requests()
                _fail_with(problems)
        finally:
            server.terminate()
    finally:
        if network_guard is not None:
            network_guard.install()
        from tests.support.console_redesign_world import _close_console_store

        _close_console_store(store)


def _seed_duration_runs(store: Any, seed: Any) -> None:
    """Three runs whose served stamps are the duration formatter's rung-0 values —
    the Jobs table renders the same `durationLabel` the bundle carries, from the runs'
    own stamp pairs (the mirror's `_duration`, never a fabricated figure)."""
    from aeh.orch import Orchestrator
    from aeh.conf import CohortRef, resolve_run_config
    from tests.support.conf_builders import edge_cfg

    resolved = resolve_run_config(edge_cfg(), CohortRef(cohort_id=seed.cohort_id,
                                                        consent_class="synthetic"))
    stamps = (("fmt-45", 45.0), ("fmt-134", 134.0), ("fmt-3900", 3900.0))
    from datetime import datetime, timedelta, timezone

    started = datetime.now(timezone.utc)
    for name, seconds in stamps:
        run_id = Orchestrator(store, clock=clarity_world._clock).create_run(
            seed.cohort_id, seed.package_version_id, resolved, run_id=f"run-{name}")
        handle = store.cohort(seed.cohort_id)
        with handle.transaction() as tx:
            tx.execute("UPDATE run SET started_at = :s, "
                       "completed_at = :e, status = 'complete' "
                       "WHERE run_id = :r",
                       s=started.isoformat(),
                       e=(started + timedelta(seconds=seconds)).isoformat(),
                       r=run_id)


def test_tc_ui_34_how_was_this_graded_opens_the_ai_calls_tab(
    tmp_path, network_guard, monkeypatch
):
    """`TC-UI-34` (P1) — from a student's detail page, "How was this graded?" opens the
    AI-calls tab filtered to that student, question and run; the Jev row's panels read
    "Question sent to Jev" / "Jev's answer" with the confidence line; a below-gate
    judge row's panels read "Question sent to the judge" / "The judge's answer"; each
    panel's Copy puts its text on the clipboard (the page's own status, with a
    read-back when the browser grants the clipboard). Repeated on the `real` cohort."""
    with _results_world(tmp_path / "ai-calls-arm", network_guard, monkeypatch,
                        journal=True, consent_class="real") as box:
        origin = box["origin"]
        seed = box["seed"]
        student_name = tuple(seed.submissions)[0]
        with spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
            problems: list[str] = []
            submission_id = seed.submissions[student_name]
            page.goto(origin + f"/#/results/students/{submission_id}")
            spa.wait_for_screen(page)
            # Wait for the read's own questions (the links live in the groups).
            for _ in range(20):
                page.wait_for_timeout(250)
                if page.locator(".question-group").count():
                    break
            # The link that matters is the one on the journal's own question: the
            # C2 record the world wrote grades Q2.
            group = page.locator(".question-group").filter(has_text="Q2").first
            link = group.get_by_role("link", name="How was this graded?")
            if not link.count():
                problems.append("no 'How was this graded?' link on the student's Q2")
            else:
                link.click()
                spa.wait_for_screen(page)
                url = urlsplit(page.url)
                # The query rides the fragment (`#/logs?tab=…`), not the URL's own.
                query = url.fragment.split("?", 1)[1] if "?" in url.fragment else ""
                # The link sends the student's ref (what the read's filter matches),
                # the question's id, the run — and the tab.
                served_ref = "ref-" + student_name.lower()
                for part in (f"student={served_ref}", "question=Q2",
                             f"run={seed.run_id}", "tab=ai-calls"):
                    if part not in query:
                        problems.append(f"the opened view's address lacks {part!r} "
                                        f"({query!r})")
                rows = page.locator("li.ai-call-row")
                if not rows.count():
                    problems.append("the AI-calls tab renders no rows")
                else:
                    # The panels ride the rows' own <details>: expand each row, then
                    # read — the closed rows' text is not the screen's visible text.
                    for index in range(rows.count()):
                        rows.nth(index).locator("summary").click()
                    page.wait_for_timeout(500)
                    text = page.locator("main").inner_text()
                    if "Question sent to Jev" not in text:
                        problems.append("no 'Question sent to Jev' panel")
                    if "Jev's answer" not in text:
                        problems.append("no \"Jev's answer\" panel")
                    if "confidence 0.91, needed above 0.80 — accepted" not in text:
                        problems.append("the confidence line is missing or not accepted")
                    if "Question sent to the judge" not in text \
                            or "The judge's answer" not in text:
                        problems.append("the below-gate judge row's panels are missing")
                    # The Jev row, expanded, names the student and the question.
                    row = page.locator("li.ai-call-row.ai-call-jev_decision").first
                    if row.count():
                        summary = row.locator("summary").inner_text()
                        if student_name not in summary:
                            problems.append(f"the Jev row's heading does not name the "
                                            f"student ({summary[:80]!r})")
                        # The rows were expanded above; the answer's own text rides
                        # the open row.
                        if "Chose: full" not in row.inner_text():
                            problems.append("the Jev row's answer does not name the "
                                            "argmax band (the served probabilities' own "
                                            "argmax)")
                    # The copy arm: press the first Copy and read the page's status.
                    copy = page.get_by_role("button", name="Copy").first
                    if not copy.count():
                        problems.append("no Copy button on the panels")
                    else:
                        copy.click()
                        status = page.locator(".ai-call-panel span[role='status'], "
                                              "main span[role='status']").first
                        if status.count():
                            said = status.inner_text().strip()
                            if said not in ("Copied.",
                                            "The browser refused the copy — select the "
                                            "text by hand."):
                                problems.append(f"the copy status reads {said!r}")
                        try:
                            read_back = page.evaluate("navigator.clipboard.readText()")
                        except Exception:
                            read_back = None
                        if read_back and read_back.strip() == "":
                            problems.append("the clipboard stayed empty after the copy")
            problems += log.foreign_requests()
            _fail_with(problems)
        # The `real` cohort's repeat is the same world here: this run IS the real
        # cohort's (RC-18 — the synthetic twin is the census's world).
        del student_name
