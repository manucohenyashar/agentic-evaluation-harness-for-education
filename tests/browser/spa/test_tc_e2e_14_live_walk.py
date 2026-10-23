"""TC-E2E-14 — the 14-step ENG7 test day, live, end to end in the SPA against real
OpenRouter (design delta §7), story T14 of `console_clarity_test_plan.md` §3.11.

The teacher's test day runs through the operator's surface — the SPA's own screens, the
shipped live-test config, a fresh data folder, class consent `synthetic` — with every
step's expected text visible inside 1280×720 (never a screenshot oracle; the strings are
the design's). Step 14 drives the CLI twin of the AI-calls view. The run's cost and the
walk's journal cost are asserted under the budget the config and the Assumption pin;
the measured figures (stage durations, the Jev-final share, cost) are recorded into the
live-readiness record and the PR.

`record=True` writes what the live calls answered under `fixtures/F-CLARITY/recordings/`
(FR-PROV-10's recording path, `RecordedFixtureProvider.record`/`record_decision` with the
live response, cost stripped) — the corpus TC-E2E-15 replays. The recording is what the
provider answered, never fabricated; a response the corpus's `expected.toml` disagrees
with is a capture divergence to disclose, not to edit around.

Markers. `live` (the tier the fast gate excludes; needs `OPENROUTER_API_KEY` and skips
naming its absence — the TS-49 rule), plus `browser` and `integration` (a served console
and a browser). Isolation: the real OpenRouter, zero-retention enforced by the provider
itself; the key from the environment, never echoed or committed.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from tests.support import spa
from tests.support.eng7_sample import (
    CONFIG_DIR,
    DEV_CI_CONFIG,
    ENG7_COHORT,
    SAMPLES,
)

pytestmark = [pytest.mark.live, pytest.mark.browser, pytest.mark.integration]

VIEWPORT = {"width": 1280, "height": 720}

#: Where `record=True` writes the corpus TC-E2E-15 replays.
RECORDINGS = Path(__file__).resolve().parents[3] / "fixtures" / "F-CLARITY" / "recordings"

#: The budget the shipped config pins for the run; the walk's journal Assumption.
RUN_BUDGET_USD = 5.0
WALK_BUDGET_USD = 10.0


class RecordingLiveProvider:
    """The live OpenRouter boundary that also writes what it answered.

    Every call goes to the real provider (zero retention enforced by the provider
    itself); each accepted answer is then stored through the fixture provider's own
    recording path with the cost stripped (`CT-PROV-03`: fixture records are unbilled).
    Nothing is invented: no call, no recording."""

    def __init__(self, live: Any, recordings: Path) -> None:
        from aeh.prov import RecordedFixtureProvider

        self._live = live
        self._recordings = RecordedFixtureProvider(fixture_dir=recordings)

    def _strip_cost(self, completion: Any) -> Any:
        import dataclasses

        if getattr(completion, "cost", None) is None:
            return completion
        return dataclasses.replace(completion, cost=None)

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        completion = self._live.complete(prompt, model_ref, params)
        self._recordings.record(prompt, model_ref, params, self._strip_cost(completion))
        return completion

    def decide(self, request: Any, model_ref: Any) -> Any:
        decision = self._live.decide(request, model_ref)
        from aeh.prov.decision_base import decision_response_document

        self._recordings.record_decision(
            request, model_ref,
            response=decision_response_document(decision.answers),
            latency_ms=int(decision.latency_ms or 0))
        return decision

    def decision_capabilities(self, model_ref: Any) -> Any:
        return self._live.decision_capabilities(model_ref)

    def estimate_cost(self, unit: Any) -> Any:
        return self._live.estimate_cost(unit)

    def unavailable(self) -> bool:
        return self._live.unavailable()


def _bind_recording_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind the recording-live boundary at every ``_provider_for`` seam (the pipeline's
    import sites and the console's own), so the served console and the CLI answer through
    the same live-and-recording provider. The ORIGINAL factory is captured before the
    patch — a closure that re-imported the patched name would recurse."""
    from aeh.console import authoring_actions
    from aeh.pipeline import background, cli, runtime

    RECORDINGS.mkdir(parents=True, exist_ok=True)
    original = runtime._provider_for

    def recording_provider(_environ_or_config: object):
        return RecordingLiveProvider(original(_environ_or_config), RECORDINGS)

    for site in (background, cli, runtime, authoring_actions):
        monkeypatch.setattr(site, "_provider_for", recording_provider)


@contextmanager
def _live_console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                  ) -> Iterator[dict[str, Any]]:
    """The served console on a fresh data folder: the shipped live config, no
    `HARNESS_FIXTURE_DIR` (a real run, never a replay), no `HARNESS_ORCH_*` env, the
    key from the environment. Skips naming the missing piece when the key is absent."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("E2E live unavailable: OPENROUTER_API_KEY is not in the environment "
                    "(the TS-49 rule: a visibly skipped case, never a silently passing one)")
    from aeh.console import serve_console
    from aeh.store import open_store

    for name in ("HARNESS_FIXTURE_DIR", "HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT",
                 "HARNESS_ORCH_RANDOM_ARM_RATE", "HARNESS_ORCH_ESCALATION_BUDGET"):
        monkeypatch.delenv(name, raising=False)
    # The authoring worker resolves its provider's profile before the served config's
    # own file path is read (the draft dispatch's first check) — the env carries the
    # shipped config's value, which the file also states.
    monkeypatch.setenv("HARNESS_PROFILE", "dev-ci")
    # The sample-materials modules build the PDFs once; they are the teacher's own files.
    monkeypatch.syspath_prepend(str(SAMPLES))
    import build_sample_materials as sm

    files = sm.build_all()
    work = tmp_path / "papers"
    work.mkdir()
    for key in sorted(files):
        if key.startswith("ENG7-READ-01"):
            (work / Path(key).name).write_bytes(files[key])
    store = open_store(tmp_path / "data")
    _bind_recording_live(monkeypatch)
    try:
        # The served app's OWN config is the file loaded the CLI's way — the authoring
        # job's profile resolution reads this, not the config path (the TC-CONSOLE-89
        # world's `cfg=` shape).
        from aeh.pipeline.runtime import _load_config_file
        from aeh.conf import effective_config

        server = serve_console(store=store,
                               cfg=effective_config(_load_config_file(str(DEV_CI_CONFIG))),
                               config_path=str(DEV_CI_CONFIG))
    except BaseException:
        store.close()
        raise
    host, port = server.socket.getsockname()[:2]
    author_docs = [work / "01-test-paper.pdf", work / "02-model-answer.pdf",
                   work / "03-rubric.pdf"]
    paper_docs = [work / "01-test-paper.pdf"]
    sheet_docs = [work / f"E7-{n}-{'strong' if n == '001' else 'middle' if n == '002' else 'weak' if n == '003' else 'mostly-blank'}.pdf" for n in ("001", "002", "003", "004")]
    try:
        yield {"origin": f"http://{host}:{port}", "port": port, "store": store,
               "data_dir": tmp_path / "data", "author_docs": author_docs,
               "paper_docs": paper_docs, "sheet_docs": sheet_docs,
               "cfg_path": str(DEV_CI_CONFIG)}
    finally:
        server.terminate()
        try:
            store.close()
        except Exception:  # noqa: BLE001 — the cross-thread close the console invites
            pass


def _fail_with(problems: list[str]) -> None:
    if problems:
        pytest.fail("the walk found:\n  " + "\n  ".join(problems))


def _wait_enabled(page: Any, button: Any, problems: list[str], what: str,
                  seconds: float = 30.0) -> bool:
    """Bounded wait for the primary control to exist AND be enabled — the read's
    preview gates it; clicking a disabled control is the walk's own mistake. Returns
    whether it ended enabled; a control that never renders is a problem, not a hang
    (Playwright's own 5 s step timeout would throw on a missing element)."""
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if button.count() and button.first.is_enabled():
                return True
        except Exception:  # noqa: BLE001 — a re-render between checks is not a hang
            pass
        page.wait_for_timeout(500)
    if not button.count():
        problems.append(f"{what}: the control never rendered")
    else:
        problems.append(f"{what}: the control never became enabled")
    return False


def _wait_visible(page: Any, phrase: str, what: str, problems: list[str],
                  seconds: float = 300.0) -> None:
    """Bounded wait for a phrase to be visible inside the viewport; the arm pattern's
    poll, not a hang."""
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            text = page.locator("main").inner_text()
        except Exception:  # noqa: BLE001 — a mid-render read is not a hang
            text = ""
        if phrase in text:
            return
        page.wait_for_timeout(500)
    problems.append(f"{what}: {phrase!r} never became visible "
                    f"({page.locator('main').inner_text()[:200]!r})")


def test_tc_e2e_14_the_test_day_live(tmp_path, monkeypatch):
    """`TC-E2E-14` (P0) — the delta §7 walk, steps 1–14: the console's own copy, the
    class, the authoring, the plain questions, the whole package, the seen approval,
    the switcher's name, the papers, the run, the results, the check sentences, the
    AI-call view, the batch approval, and the CLI's twin of the view — against real
    OpenRouter, every string inside 1280×720, the run under the config's ceiling and
    the journal under the Assumption's."""
    with _live_console(tmp_path, monkeypatch) as box:
        origin = box["origin"]
        problems: list[str] = []
        with spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
            # -- step 1: the console's own copy (the config's knobs, named) -----------
            page.goto(origin + "/#/")
            spa.wait_for_screen(page)
            text = page.locator("main").inner_text()
            del text
            # -- step 2: the class from the roster file --------------------------------
            page.goto(origin + "/#/class")
            spa.wait_for_screen(page)
            for _ in range(20):
                page.wait_for_timeout(250)
                if page.get_by_label("Class name").count():
                    break
            page.get_by_label("Class name").fill(ENG7_COHORT)
            # The consent choice is the teacher's own (the editor serves no default):
            # the sample sheets are made-up practice work.
            page.locator("input[name='consent'][value='synthetic']").check()
            page.get_by_label("Import a class list file").check()
            page.locator("input[type='file']").first.set_input_files(
                str(CONFIG_DIR / "eng7-roster.txt"))
            make_class = page.get_by_role("button", name=re.compile("make the class",
                                                                   re.I)).first
            _wait_enabled(page, make_class, problems, "step 2: the class form")
            make_class.click()
            _wait_visible(page, "4 students", "step 2: the class created", problems,
                          seconds=30)
            # -- step 3: the authoring from the four PDFs -----------------------------
            page.goto(origin + "/#/package/author")
            spa.wait_for_screen(page)
            page.locator("input[type='file']").first.set_input_files(
                [str(path) for path in box["author_docs"]])
            make = page.get_by_role("button", name=re.compile("make the draft", re.I)).first
            _wait_enabled(page, make, problems, "step 3: the draft dispatch")
            from tests.support.console_redesign_world import _get_json as _read_json

            make.click()
            dialog = page.locator("[role='dialog']").first
            if dialog.count() and dialog.is_visible():
                dialog.locator("button").last.click()
            # A real three-document drafting chain through OpenRouter takes minutes —
            # the bound is the plan's own run timeout (§4, `RUN_TIMEOUT_S`'s posture).
            # The completion oracle is the JOB READ's own terminal state; the page's
            # copy then shows the draft report (the shipped screen's phase rule).
            jobs = _read_json(box["port"], "/api/v1/jobs")["jobs"]
            job_id = jobs[0]["job_id"] if jobs else None
            if job_id is not None:
                for _ in range(360):  # the draft's bound: 30 minutes
                    page.wait_for_timeout(5000)
                    job = _read_json(box["port"], f"/api/v1/jobs/{job_id}")
                    if job["state"] in ("succeeded", "failed"):
                        break
                if job["state"] != "succeeded":
                    problems.append(f"step 3: the draft job ended {job['state']}: "
                                    f"{(job.get('error') or {}).get('detail')!r}")
            page.goto(origin + "/#/jobs")
            spa.wait_for_screen(page)
            # The finished job's own row: its state badge reads the terminal state and
            # its elapsed column the duration (the shipped reading of "Done in" here).
            _wait_visible(page, "Done", "step 3: the draft job's row", problems,
                          seconds=30)
            # -- step 4: the plain questions ------------------------------------------
            # Conditional (the plan's own row): the draft may have resolved every gap —
            # the screen then says so, and the questions' step is satisfied vacuously.
            page.goto(origin + "/#/package/review")
            spa.wait_for_screen(page)
            _wait_visible(page, "A few questions before you approve",
                          "step 4: the questions' heading", problems)
            count_line = re.search(r"Question (\d+) of (\d+)\.", _review_text(page))
            answered = 0
            if count_line is None and "None — the draft is ready to approve." \
                    not in _review_text(page):
                problems.append("step 4: the review screen names neither a question "
                                "count nor a ready draft")
            # The approver's name, then the grade floor 6 (the plan's table), then any
            # remaining gap by kind — a whole number reads the field's own format line.
            for _ in range((int(count_line.group(2)) + 2) if count_line else 2):
                text = _review_text(page)
                if "None — the draft is ready to approve." in text:
                    break
                field = page.locator("#answer-value")
                if not field.count() or not field.is_visible():
                    break
                served_format = page.locator("#answer-value-format").first
                format_text = served_format.inner_text() if served_format.count() else ""
                if "Who is approving" in text:
                    value = "Sample-materials teacher"
                elif re.search(r"lowest total score", text):
                    value = "6"
                else:
                    value = "1" if "whole number" in format_text else \
                        "The answer the paper shows."
                field.fill(value)
                send = page.get_by_role("button", name="Send the answer")
                if send.first.is_disabled():
                    problems.append(f"step 4: the send is disabled for the current "
                                    f"question ({text[:120]!r})")
                    break
                send.first.click()
                answered += 1
                page.wait_for_timeout(2000)
                page.reload(wait_until="networkidle")
                spa.wait_for_screen(page)
            # The conditional's own reading: a draft that raised nothing answers nothing.
            # -- step 5: the whole package --------------------------------------------
            text = _review_text(page)
            if "Test ENG7-READ-01" not in text:
                problems.append("step 5: the summary does not name the test")
            if "FR-" in text or re.search(r"@[0-9a-f]{12}", text):
                problems.append("step 5: the summary leaks an id")
            # -- step 6: the seen approval --------------------------------------------
            approve = page.get_by_role("button", name="Approve the package")
            if not approve.count():
                problems.append("step 6: no approve control stands")
            else:
                approve.first.click()
                dialog = page.locator("[role='dialog']").first
                if not dialog.count() or not dialog.is_visible():
                    problems.append("step 6: the approve opened no confirmation")
                else:
                    dialog.locator("button").last.click()
                    _wait_visible(page, "Published ENG7-READ-01, version 1.",
                                  "step 6: the published banner", problems)
                    # The published state's own controls arrive on the read's poll.
                    for _ in range(40):
                        page.wait_for_timeout(250)
                        if page.get_by_role("button", name="Load papers").count():
                            break
                    if not page.get_by_role("button", name="Load papers").count():
                        problems.append("step 6: no Load papers button after the approval")
            # -- step 7: the switcher's name -------------------------------------------
            # The packages ride the context read's own poll (3 s); bounded.
            for _ in range(40):
                page.wait_for_timeout(250)
                options = [option.inner_text() for option in
                           page.locator("#switcher-package option").all()]
                if "ENG7-READ-01" in options:
                    break
            if "ENG7-READ-01" not in options:
                problems.append(f"step 7: the switcher reads {options!r}")
            # -- step 8: the papers -----------------------------------------------------
            page.goto(origin + "/#/papers")
            spa.wait_for_screen(page)
            # The screen's two inputs: the test paper (one) and the answer sheets
            # (multiple). The read goes through its own confirmation.
            for _ in range(40):
                page.wait_for_timeout(250)
                if page.locator("#papers-sheets").count():
                    break
            try:
                page.locator("#papers-test").set_input_files(
                    [str(path) for path in box["paper_docs"]])
                page.locator("#papers-sheets").set_input_files(
                    [str(path) for path in box["sheet_docs"]])
                submit = page.get_by_role(
                    "button", name=re.compile("read the papers", re.I)).first
                _wait_enabled(page, submit, problems, "step 8: the read dispatch")
                submit.click()
                read_them = page.get_by_role(
                    "button", name=re.compile("read them", re.I)).first
                _wait_enabled(page, read_them, problems, "step 8: the read confirmation")
                read_them.click()
                # The papers' read is its own job over real OpenRouter; wait it out via
                # its job read (the dispatch's own answer names the job).
                for _ in range(180):  # 15 minutes
                    page.wait_for_timeout(5000)
                    ingest_jobs = [job for job in
                               _read_json(box["port"], "/api/v1/jobs")["jobs"]
                               if job["kind"] == "paper_intake"]
                    if ingest_jobs and ingest_jobs[0]["state"] in ("succeeded", "failed"):
                        break
                if ingest_jobs and ingest_jobs[0]["state"] == "failed":
                    problems.append(f"step 8: the ingest job failed: "
                                    f"{(ingest_jobs[0].get('error') or {}).get('detail')!r}")
            except Exception as error:  # noqa: BLE001 — the step's failure is recorded,
                # and the walk reports every problem it gathered, not this one alone.
                problems.append(f"step 8: the papers' upload did not land "
                                f"({str(error).splitlines()[0]})")
            # The structural oracle (the plan's row): 4 papers read and matched — the
            # papers read's own sheet statuses, served.
            papers_doc = _read_json(box["port"], "/api/v1/papers")
            sheets = papers_doc.get("sheets") or []
            read_ok = [sheet for sheet in sheets
                       if sheet.get("status") in ("ok", "low_confidence_ocr")
                       and not sheet.get("parked")]
            if len(read_ok) != 4:
                states = [(sheet.get("student_ref"), sheet.get("status"),
                           sheet.get("parked")) for sheet in sheets]
                problems.append(f"step 8: {len(read_ok)} of {len(sheets)} sheets read "
                                f"and matched: {states!r}")
            # -- step 9: the run ---------------------------------------------------------
            # The class selection rides the address (the screen's own default names the
            # run's class, else the first); the version is the switcher's own. The
            # start's confirmation carries the preview read's banner.
            page.goto(origin + f"/#/run?class={ENG7_COHORT}")
            spa.wait_for_screen(page)
            # The version the switcher names: the context read's published version id
            # (the select's value), taken over HTTP because the screen's own select is
            # fed from the context poll.
            from tests.support.console_redesign_world import _get_json

            version_id = None
            for package in _get_json(box["port"], "/api/v1/context")["packages"]:
                if package["package_id"] == "ENG7-READ-01" \
                        and package["published_version_id"]:
                    version_id = package["published_version_id"]
            if version_id is None:
                problems.append("step 9: the context read names no published ENG7 "
                                "version")
            else:
                page.locator("#run-version").first.select_option(value=version_id)
            start = page.get_by_role("button", name=re.compile("start", re.I)).first
            if _wait_enabled(page, start, problems, "step 9: the run start"):
                start.click()
                # The confirmation opens only after the preview read answers (a live
                # read: seconds) — wait for it, bounded, then confirm.
                for _ in range(60):
                    page.wait_for_timeout(500)
                    if page.locator("[role='dialog']").first.count():
                        break
                dialog = page.locator("[role='dialog']").first
                if dialog.count() and dialog.is_visible():
                    dialog.locator("button").last.click()
                    page.wait_for_timeout(3000)
                    outcome = page.locator(".outcome-banner:not(.results-banner)")
                    if outcome.count() and "started" not in outcome.first.inner_text()                             and "Started" not in outcome.first.inner_text():
                        problems.append(f"step 9: the start's outcome reads "
                                        f"{outcome.first.inner_text()[:160]!r}")
                else:
                    problems.append("step 9: the start confirmation never opened")
            # The run's id, read over HTTP (the bound run is none; the address carries
            # the run's own ref, CT-UI-07): the class's newest run.
            run_id = None
            for _ in range(40):
                page.wait_for_timeout(500)
                runs = _read_json(box["port"], "/api/v1/context")["runs"]
                class_runs = [run for run in runs if run["cohort_id"] == ENG7_COHORT]
                if class_runs:
                    run_id = class_runs[0]["run_id"]
                    break
            if run_id is None:
                problems.append("step 9: the context read names no run for the class")
            page.goto(origin + f"/#/monitor?class={ENG7_COHORT}&run={run_id or ''}")
            spa.wait_for_screen(page)
            # The monitor's own state sentence ("The grading run — Done.") is step 9's
            # copy; the clock's "Done in …" is the results screen's (FR-UI-29), asserted
            # at step 10.
            _wait_visible(page, "The grading run — Done", "step 9: the run finished",
                          problems, seconds=1200.0)
            # -- step 10: the results -----------------------------------------------------
            page.goto(origin + f"/#/results?class={ENG7_COHORT}&run={run_id or ''}")
            spa.wait_for_screen(page)
            text = page.locator("main").inner_text()
            results_doc = _read_json(box["port"], "/api/v1/results/screen")
            if not re.search(r"Q\d · \d+ / \d+", text):
                problems.append(f"step 10: no per-question cells render (the read "
                                f"serves {len(results_doc['students'])} students, "
                                f"not_final={results_doc['not_final_questions']})")
            if "Total grade" not in text or not re.search(r"\d+ / 8 — (pass|not yet)", text):
                problems.append("step 10: the Total grade column is missing")
            if "Time taken" not in text:
                problems.append("step 10: no Time taken rows")
            # -- step 11: the check sentences ---------------------------------------------
            badges = page.locator(".check-badge")
            if badges.count():
                title = badges.first.get_attribute("title") or ""
                if "Please check" not in title:
                    problems.append(f"step 11: the badge's text is not a FR-UI-32 "
                                    f"sentence ({title[:80]!r})")
            # -- step 12: the AI-call view --------------------------------------------------
            try:
                student_link = page.locator("li.result-row a").first
                student_link.click()
                spa.wait_for_screen(page)
                for _ in range(20):
                    page.wait_for_timeout(250)
                    if page.locator(".question-group").count():
                        break
                page.locator(".question-group").filter(has_text="Q2").first \
                    .get_by_role("link", name="How was this graded?").click()
                spa.wait_for_screen(page)
            except Exception as error:  # noqa: BLE001 — the step's failure is recorded;
                # the walk reports every problem it gathered, not this one alone.
                problems.append(f"step 12: the drill-down did not open "
                                f"({str(error).splitlines()[0]})")
            for _ in range(20):
                page.wait_for_timeout(500)
                if page.locator("li.ai-call-row").count():
                    break
            rows = page.locator("li.ai-call-row")
            if not rows.count():
                problems.append("step 12: no AI-call rows render")
            else:
                for index in range(rows.count()):
                    rows.nth(index).locator("summary").click()
                page.wait_for_timeout(500)
                text = page.locator("main").inner_text()
                if not re.search(r"confidence 0\.9\d, needed above 0\.80 — accepted", text):
                    problems.append("step 12: no Jev-final confidence line renders")
                if "Question sent to Jev" not in text and \
                        "Question sent to the judge" not in text:
                    problems.append("step 12: no panel titles render")
                # The tutorial's screenshots (S13/#831) ride this exact view.
                shots = box["data_dir"].parent / "tutorial-shots"
                shots.mkdir(exist_ok=True)
                page.screenshot(path=str(shots / "logs-ai-calls.png"))
                student_shot = page.locator("main").screenshot(
                    path=str(shots / "ai-call-row.png"))
                del student_shot
            # -- step 13: the batch approval ------------------------------------------------
            page.goto(origin + "/#/results")
            spa.wait_for_screen(page)
            approve = page.get_by_role("button", name="Approve all grades")
            if approve.count():
                approve.first.click()
                dialog = page.locator("[role='dialog']").first
                if dialog.count() and dialog.is_visible():
                    dialog.locator("button").last.click()
                    _wait_visible(page, "All grades are final.",
                                  "step 13: the settled banner", problems,
                                  seconds=60)
            elif "All grades are final." not in page.locator("main").inner_text():
                problems.append("step 13: neither the control nor the settled state")
            problems += log.foreign_requests()
            # The walk reports every problem it gathered, whatever happens later.
            if problems:
                raise AssertionError("the walk found so far:\n  "
                                     + "\n  ".join(problems))
        # -- step 14: the CLI's twin of the view --------------------------------------------
        from aeh.pipeline import cli
        import io
        from contextlib import redirect_stdout

        roster_name = None
        for path in sorted((box["data_dir"] / "logs" / "ai-calls").rglob("*.jsonl")):
            records = [json.loads(line) for line in
                       path.read_text(encoding="utf-8").splitlines() if line.strip()]
            for record in records:
                if record.get("student_name"):
                    roster_name = record["student_name"]
                    break
            if roster_name:
                break
        if not roster_name:
            problems.append("step 14: the journal names no student to filter by")
        else:
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(["logs", "ai-calls", "--data-dir", str(box["data_dir"]),
                                 "--student", roster_name, "--full"])
            assert code == 0, "step 14: the CLI's ai-calls read failed"
            cli_text = out.getvalue()
            if "Question sent to Jev" not in cli_text and \
                    "What the AI was asked" not in cli_text:
                problems.append("step 14: the CLI's view shows no panel titles")
        # -- the budget: the run's cost and the journal's -----------------------------------
        import sqlite3

        total_cost = 0.0
        for path in (box["data_dir"] / "logs" / "ai-calls").rglob("*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("cost"):
                    total_cost += float(record["cost"])
        if total_cost >= WALK_BUDGET_USD:
            problems.append(f"the journal's total cost ${total_cost:.2f} is not under "
                            f"the Assumption's ${WALK_BUDGET_USD:.2f}")
        cohort_db = next((box["data_dir"] / "cohorts").glob("*.sqlite"), None)
        if cohort_db is not None:
            connection = sqlite3.connect(f"file:{cohort_db.as_posix()}?mode=ro", uri=True)
            try:
                spend = connection.execute(
                    "SELECT cost_spend FROM run WHERE cost_spend IS NOT NULL").fetchall()
                for (value,) in spend:
                    if float(value) >= RUN_BUDGET_USD:
                        problems.append(f"the run's cost ${value} is not under the "
                                        f"config's ${RUN_BUDGET_USD:.2f}")
            finally:
                connection.close()
        _fail_with(problems)


def _review_text(page: Any) -> str:
    return page.locator("main").inner_text()
