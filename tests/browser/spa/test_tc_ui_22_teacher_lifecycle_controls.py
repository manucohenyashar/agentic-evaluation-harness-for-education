"""`TC-UI-22` — the teacher's lifecycle controls work in the browser, with no terminal.

*Inline regression* for the console gaps the live test met (the class screen offered no form,
the papers inputs were inert, the run screen could only restart the console's launch-time run,
and a nameless parked paper could only be closed). One journey, driven through the SPA's own
controls in a real browser over a real console and store:

1. **Set up a class** — the form makes `ps9-class` from a typed list, consent chosen.
2. **Load papers** — the test paper and the six sample sheets are chosen and read through the
   upload; the page's progress settles on three ready and three parked.
3. **Parked** — S9-006's nameless paper is given to its student; the decision is recorded.
4. **Start a run** — a new grading run for the class and the published version is started
   behind its priced confirmation, and the console opens that run's monitor.

The page reader is the real `OpenRouterProvider` over a stand-in transport that answers each
page with the sample script's transcript (`TC-PIPE-30`'s), so the reading is the shipped
intake. The run itself is not graded here — its judges are not staged — so the case asserts
that it started and is the monitor's run, nothing about its marks.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pytest

from aeh.conf import effective_config
from aeh.pipeline import background, cli
from aeh.pipeline.runtime import _open_store, _UnitPricedProvider
from aeh.prov import OpenRouterProvider
from tests.support import spa
from tests.unit.pipe.test_ingest_command import (
    DEV_CI_CONFIG,
    SAMPLE_SPEC,
    SAMPLES,
    _FakeOpenRouter,
)

pytestmark = [pytest.mark.browser, pytest.mark.integration]


def _wait(predicate, what: str, timeout: float = 60.0, detail=lambda: "") -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError(f"TC-UI-22: gave up waiting for {what}. The page said:\n"
                                 f"{str(detail())[:1500]}")
        time.sleep(0.25)


def test_tc_ui_22_class_papers_parked_and_run_start_from_the_browser(
        tmp_data_dir, tmp_path, monkeypatch, capsys):
    pytest.importorskip("pypdfium2")
    monkeypatch.syspath_prepend(str(SAMPLES))
    import build_sample_materials as sm
    import verify_sample_materials as v

    for key in ("HARNESS_FIXTURE_DIR", "HARNESS_PROFILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "0")
    assert cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(SAMPLE_SPEC)]) == 0
    version = json.loads(capsys.readouterr().out)["package_version"]

    files = sm.build_all()
    fake = _FakeOpenRouter()
    store = _open_store(str(tmp_data_dir))
    blobs = store.blobs()
    paper = tmp_path / "01-test-paper.pdf"
    paper.write_bytes(files[f"{sm.PHYSICS_ID}/01-test-paper.pdf"])
    fake.pages[(blobs.put(paper.read_bytes()), 1)] = v.assessment_transcript(sm.PHYSICS_ID)
    sheets = []
    for sheet in sm.PHYSICS_SHEETS:
        path = tmp_path / f"{sheet['stem']}.pdf"
        path.write_bytes(files[f"{sm.PHYSICS_ID}/answer-sheets/{sheet['stem']}.pdf"])
        fake.pages[(blobs.put(path.read_bytes()), 1)] = v.sheet_transcript(sheet)
        sheets.append(str(path))
    # Wrapped the way the shipped factory wraps every provider, so the run's cost ceiling can
    # price a unit (`runtime._UnitPricedProvider`).
    provider = _UnitPricedProvider(OpenRouterProvider.enforcing_zero_retention(
        api_key="sk-or-test", base_url="https://openrouter.test/api/v1", transport=fake))
    monkeypatch.setattr(background, "_provider_for", lambda run_config: provider)

    from aeh.console import serve_console

    config = effective_config(cli._load_config_file(str(DEV_CI_CONFIG)))
    server = serve_console(store, cfg=config, config_path=str(DEV_CI_CONFIG))
    origin = f"http://127.0.0.1:{server.port}"
    roster = "\n".join(s["student"] or "S9-006" for s in sm.PHYSICS_SHEETS)
    try:
        with spa.spa_page(origin) as (page, log):
            # 1. the class, through the form
            page.goto(origin + "/#/class")
            page.get_by_label("Class name").fill("ps9-class")
            page.get_by_label("made-up practice work").check()
            page.get_by_label("One student per line").fill(roster)
            page.get_by_role("button", name="Make the class").click()
            page.get_by_role("region", name="Class ps9-class").wait_for()

            # 2. the papers, through the upload
            page.goto(origin + "/#/papers?class=ps9-class")
            page.locator("#papers-test").set_input_files(str(paper))
            page.locator("#papers-sheets").set_input_files(sheets)
            page.get_by_role("button", name="Read the papers").click()
            page.get_by_role("dialog").get_by_role("button", name="Read them").click()
            _wait(lambda: "7 file(s) done" in spa.main_text(page), "the reading job to settle",
                  detail=lambda: spa.main_text(page))
            assert "3 paper(s) ready to grade, 3 parked" in spa.main_text(page)

            # 3. the nameless paper, given to its student
            page.goto(origin + "/#/parked?class=ps9-class")
            card = page.locator("li.parked-card").filter(has=page.get_by_label("This paper belongs to"))
            card.first.wait_for()
            card.first.get_by_label("This paper belongs to").select_option("S9-006")
            card.first.get_by_label("Your note (optional)").fill("the hand matches S9-006")
            card.first.get_by_role("button", name="Give it to this student").click()
            page.get_by_role("dialog").get_by_role("button", name="Give it").click()
            # FR-UI-22: the outcome names the student by name (the roster's name is the
            # ref here — the sample class lists S9-006 under that name).
            page.get_by_role("status").filter(has_text="was given to S9-006").wait_for()

            # 4. a new grading run, from the run screen
            page.goto(origin + "/#/run?class=ps9-class")
            page.get_by_label("Test version").select_option(version)
            page.get_by_role("button", name="Start a new grading run").click()
            dialog = page.get_by_role("dialog")
            dialog.wait_for()
            # FR-UI-23: the confirmation names the settings profile it runs under (the
            # preview read's banner), never the raw version id; the class was already
            # named by the screen the run starts from.
            assert "dev-ci" in dialog.inner_text(), dialog.inner_text()
            assert not re.search(r"HARNESS_|\"\w+\":", dialog.inner_text()), \
                "the start confirmation shows raw settings"
            dialog.get_by_role("button", name=re.compile(r"^start$", re.I)).click()
            # The monitor opens the started run: its own heading and the run's state
            # sentence (FR-UI-23: no "Run run-…" id). DEFECT FINDING (recorded on #827's
            # PR; the world here is byte-identical to main's): this journey's monitor
            # shows the run paused with "paused: composition fault: KeyError:
            # 'source_blob_hash'" — a raw exception class in a teacher-facing pause
            # reason, which no FR-UI-23 census catches because `STACK_TRACE_PATTERNS`
            # does not know it. The pause itself is the seeded world's staged shape; the
            # wording is the defect.
            _wait(lambda: spa.main_text(page).startswith("Monitor run")
                  and "The grading run" in spa.main_text(page),
                  "the console to open the started run's monitor",
                  detail=lambda: spa.main_text(page))

            assert not log.page_errors, log.page_errors
            assert not log.foreign_requests(), log.foreign_requests()

        handle = store.cohort("ps9-class")
        # The typed list names each student; the console generates their references, so the
        # paper is checked against the roster NAME the operator chose.
        assigned = list(handle.query(
            "SELECT r.full_name, d.note FROM quarantine_decision d "
            "JOIN submission s ON s.submission_id = d.submission_id "
            "JOIN roster r ON r.student_ref = s.student_ref "
            "WHERE d.resolution = 'assigned'"))
        assert [(r["full_name"], r["note"]) for r in assigned] \
            == [("S9-006", "the hand matches S9-006")]
        runs = list(handle.query("SELECT package_version_id FROM run"))
        assert [r["package_version_id"] for r in runs] == [version]
    finally:
        server.terminate()
        for thread in list(getattr(server.app, "_run_threads", {}).values()):
            thread.join(timeout=30)
        try:
            store.close()
        except Exception:  # noqa: BLE001 — a tier first opened on a request thread
            pass
        for name in ("build_sample_materials", "verify_sample_materials"):
            sys.modules.pop(name, None)
