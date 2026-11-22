"""Validity T9 (issue #902): the marked examples as the console serves them, and the clarified
rubric's first class — `TC-CONSOLE-111`, `TC-CONSOLE-112`, `TC-CONSOLE-115`, and `TC-CALIB-24`'s
"back-translation runs at R₁ creation" arm.

| Case | What is asserted |
|---|---|
| TC-CONSOLE-111 (FR-CONSOLE-86, CT-CONSOLE-17) | on the served console, both calibration touchpoints report implemented and their reads answer; `MVP_ABSENT_TOUCHPOINT` is gone; the legacy upload page (`/packages/new`) carries the examples step with no retired or rate claim; mutation: unregister `GET /api/v1/calibration/differences` → both rows "not implemented" and the read no longer answers. (The SPA half of "claims nothing the SPA lacks" is `test_tc_console_111_b_spa_examples_step.py`, written ahead on S18 #888.) |
| TC-CONSOLE-112 (FR-CONSOLE-87, CT-CALIB-03) | every examples action and read works end to end on the 4 ENG7 examples, and no response — action outcome, job read or read — has a key matching `rate|percent|agreement|kappa|matched|accuracy|share` or a string value with `%`. (`examples skip` at each step: `test_tc_calib_23_tc_console_112_skip_at_any_step…` in the calib file.) |
| TC-CONSOLE-115 (FR-CONSOLE-90, CT-CONSOLE-57, FR-CALIB-18) | R₁ pending: console start-run plans the R₁ pass and the outcome carries the sentence; the class is graded under R₀; gates pass → R₁ delivered, the same class's export byte-identical across the decision, the next class runs R₁; NI fails / BT fails → R₁ set aside with its reason, delivered R₀; headless `aeh run` → R₀, R₁ still pending, no pass |
| TC-CALIB-24 (BT at creation) | `examples answer` runs back-translation at once: the checker is asked before any class run and the outcome is recorded on R₁ |

**World.** `tests/support/eng7_examples.py` (rung 3, a real console on a loopback port). The
back-translation checker is the declared off-panel model bound to a scripted stand-in
(`off_panel_checker`); the non-inferiority threshold is declared through its env channel
(`HARNESS_CALIB_NONINFERIORITY_THRESHOLD = 0.10`). R₁ is made to move marks by the judge
stand-in answering differently when the band block carries R₁'s clarification
(`shifting_under_r1`).

**Written ahead: no**, although the issue says yes: S16 (#886) and S17 (#887) had merged.

**Disclosed (not asserted):** the SPA's run-start screen (`ui/src/screens/RunStart.tsx`) shows a
fixed `said:` line, so the clarified-rubric sentence the console's outcome carries is not shown in
the SPA. TC-CONSOLE-115 asks for the console outcome, which carries it.
"""

from __future__ import annotations

import io
import json
import re
from contextlib import redirect_stdout
from typing import Any

import pytest

from tests.support.eng7_examples import (
    PANEL_CONFIG,
    SHEETS,
    THREE_DISAGREEMENTS_TEACHER,
    eng7_examples,
    examples_checked,
    off_panel_checker,
    shifting_under_r1,
)

pytestmark = pytest.mark.integration

#: FR-CONSOLE-90's run-start sentence, verbatim from the test plan.
CHECKING_SENTENCE = ("Your clarified rubric is being checked on this class; this class is "
                     "graded with your original rubric.")

#: CT-CALIB-03's no-rate census, as the plan spells it.
RATE_KEY = re.compile(r"rate|percent|agreement|kappa|matched|accuracy|share", re.IGNORECASE)

THRESHOLD_ENV = "HARNESS_CALIB_NONINFERIORITY_THRESHOLD"

CALIBRATION_ROWS = ("Mark 10 to 15 calibration papers", "Answer ambiguity-elicitation questions")


def _world(tmp_path, monkeypatch, network_guard, **kwargs):
    return eng7_examples(tmp_path / "data", tmp_path / "work", monkeypatch, network_guard,
                         **kwargs)


def _rate_findings(value: Any, where: str) -> list[str]:
    """Every key matching the census pattern and every string value carrying `%`."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if RATE_KEY.search(str(key)):
                found.append(f"{where}: key {key!r}")
            found += _rate_findings(item, f"{where}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found += _rate_findings(item, f"{where}[{index}]")
    elif isinstance(value, str) and "%" in value:
        found.append(f"{where}: {value!r}")
    return found


# --- TC-CONSOLE-111 ------------------------------------------------------------------------------


def test_tc_console_111_both_calibration_touchpoints_are_implemented_and_served(
        tmp_path, monkeypatch, network_guard):
    """On the served console: both calibration rows of §7.9 report implemented, their reads
    answer 200, `MVP_ABSENT_TOUCHPOINT` is gone, and the legacy upload page carries the examples
    step without the retired "stored, not used" claim or any rate. Mutation: with the
    differences read unregistered, both rows read "not implemented" (present, unavailable, a
    version named) and the read no longer answers."""
    import aeh.console as console
    from aeh.console import api_handler, touchpoint_surface

    with _world(tmp_path, monkeypatch, network_guard) as world:
        app = world.server.app
        rendered = touchpoint_surface(app)
        reads = {path: world.get(path, package_version=world.package_version)[0]
                 for path in ("/api/v1/calibration/examples", "/api/v1/calibration/differences",
                              "/api/v1/calibration/questions")}
        status, legacy = world.raw_get("/packages/new")
        page = legacy.decode("utf-8")

        reader = api_handler._READS.pop("calibration differences")
        try:
            degraded = touchpoint_surface(app)
            # A route whose reader is gone is not served (the handler drops the request).
            try:
                unregistered = world.get("/api/v1/calibration/differences",
                                         package_version=world.package_version)[0]
            except ConnectionError:
                unregistered = None
        finally:
            api_handler._READS["calibration differences"] = reader

    for name in CALIBRATION_ROWS:
        assert rendered[name].implemented and rendered[name].available, (name, rendered[name])
        assert not degraded[name].implemented, f"{name} still implemented with a read gone"
        assert degraded[name].present and not degraded[name].available
        assert degraded[name].available_in_version, degraded[name]
    assert set(reads.values()) == {200}, reads
    assert unregistered != 200, "the differences read still answers after it was unregistered"
    assert not hasattr(console, "MVP_ABSENT_TOUCHPOINT")
    assert status == 200 and "Mark 10 to 15 calibration papers" in page
    lowered = page.lower()
    for retired in ("not used", "stored_not_used", "until m-calib", "%", "agreement",
                    "accuracy"):
        assert retired not in lowered, f"the legacy upload page claims {retired!r}"


# --- TC-CONSOLE-112 ------------------------------------------------------------------------------


def test_tc_console_112_every_examples_action_and_read_works_and_carries_no_rate(
        tmp_path, monkeypatch, network_guard):
    """Upload, mark, grade and answer over HTTP on the 4 ENG7 examples, each job read, and the
    three reads before and after the check: every one answers, and the no-rate census finds no
    key matching `rate|percent|agreement|kappa|matched|accuracy|share` and no `%` anywhere."""
    responses: dict[str, Any] = {}
    with _world(tmp_path, monkeypatch, network_guard) as world, \
            off_panel_checker(monkeypatch, constructs=False):
        from tests.support.eng7_examples import three_disagreements_rule

        world.judge_rule = three_disagreements_rule

        def reads(tag: str) -> None:
            for path in ("/api/v1/calibration/examples", "/api/v1/calibration/differences",
                         "/api/v1/calibration/questions"):
                status, body = world.get(path, package_version=world.package_version)
                assert status == 200, (path, body)
                responses[f"{tag} GET {path}"] = body

        def job(tag: str, outcome: dict) -> None:
            world.wait_job(outcome["job_id"])
            status, body = world.get(f"/api/v1/jobs/{outcome['job_id']}")
            assert status == 200 and body["state"] == "succeeded", body
            responses[f"{tag} job"] = body

        outcome, _ = world.upload()
        responses["examples upload"] = outcome
        job("upload", outcome)
        reads("uploaded")
        for index, outcome in enumerate(world.mark(
                {stem: dict(THREE_DISAGREEMENTS_TEACHER) for stem in SHEETS})):
            responses[f"examples mark {index}"] = outcome
        reads("marked")
        outcome, _ = world.grade()
        responses["examples grade"] = outcome
        job("grade", outcome)
        reads("checked")
        responses["examples answer"] = world.dispatched(
            "examples answer", package_version=world.package_version, answers={"q1": "broaden"})
        reads("answered")

    assert responses["uploaded GET /api/v1/calibration/examples"]["status"] == "uploaded"
    assert responses["marked GET /api/v1/calibration/examples"]["status"] == "marked"
    assert responses["checked GET /api/v1/calibration/examples"]["status"] == "checked"
    assert responses["answered GET /api/v1/calibration/examples"]["status"] == "answered"
    assert responses["checked GET /api/v1/calibration/differences"]["groups"], \
        "the check found no difference, so the census read an empty differences read"
    assert len(responses["checked GET /api/v1/calibration/questions"]["questions"]) == 1
    findings = [f for where, body in responses.items() for f in _rate_findings(body, where)]
    assert not findings, "a rate reached the examples step:\n  " + "\n  ".join(findings)


# --- TC-CONSOLE-115 and TC-CALIB-24 --------------------------------------------------------------


def _answered(world) -> str:
    """The examples checked and the one question answered "broaden": R1 pending. Returns R1."""
    examples_checked(world)
    world.dispatched("examples answer", package_version=world.package_version,
                     answers={"q1": "broaden"})
    (revision,) = world.catalog().calibration_revisions(world.package_version)
    assert revision["state"] == "pending", revision
    return revision["revision_version_id"]


def _export(world, run_id: str) -> bytes:
    status, body = world.raw_get("/api/v1/results/export", run_id=run_id, format="csv")
    assert status == 200, body[:300]
    return body


def test_tc_calib_24_back_translation_runs_when_r1_is_created(tmp_path, monkeypatch,
                                                              network_guard):
    """`examples answer` mints R1 and runs back-translation at once: the off-panel checker is
    asked (once per angle) before any class has run, and R1's record carries the outcome."""
    with _world(tmp_path, monkeypatch, network_guard) as world, \
            off_panel_checker(monkeypatch, constructs=False) as checker:
        examples_checked(world)
        assert checker.calls == []
        world.dispatched("examples answer", package_version=world.package_version,
                         answers={"q1": "broaden"})
        (revision,) = world.catalog().calibration_revisions(world.package_version)
        runs = world.class_runs()
    assert len(checker.calls) == 3, f"the checker was asked {len(checker.calls)} time(s)"
    assert runs == [], "a class ran before the check, so 'at creation' is not shown"
    assert revision["back_translation"] == "pass" and revision["state"] == "pending", revision
    assert {call["r1"] != call["r0"] for call in checker.calls} == {True}


def test_tc_console_115_gates_pass_r1_delivered_from_the_next_class_and_this_class_unchanged(
        tmp_path, monkeypatch, network_guard):
    """R1 pending, threshold 0.10, BT passes and R1 moves nothing. Console start-run: the outcome
    carries the sentence, the class is graded and delivered under R0. When the R1 check decides,
    R1 is live and delivered; this class's export is byte-identical before and after the
    decision; the next class's run is graded with R1 and plans no second pass."""
    import aeh.calib.first_class as first_class

    exports: list[bytes] = []
    with _world(tmp_path, monkeypatch, network_guard) as world, \
            off_panel_checker(monkeypatch, constructs=False):
        monkeypatch.setenv(THRESHOLD_ENV, "0.10")
        r0 = world.package_version
        r1 = _answered(world)
        real_finish = first_class.finish_first_class

        def finish_after_capture(store, plan, **kwargs):
            exports.append(_export(world, plan.run_id))
            exports.append(_export(world, plan.run_id))
            return real_finish(store, plan, **kwargs)

        monkeypatch.setattr(first_class, "finish_first_class", finish_after_capture)
        outcome = world.start_class()
        first_runs = world.class_runs()
        run = first_runs[0]
        exports.append(_export(world, run["run_id"]))
        revision = world.catalog().calibration_revision(r1)
        delivered = world.catalog().delivered_version()
        scored_versions = {row["package_version_id"] for row in world.rows(
            "SELECT r.package_version_id FROM criterion_score c JOIN run r "
            "ON r.run_id = c.run_id")}
        clarified = world.examples_read()["clarified_rubric"]

        nxt = world.start_class(package_version=delivered)
        runs = world.class_runs()

    assert outcome["detail"].endswith(CHECKING_SENTENCE), outcome["detail"]
    assert [(r["package_version_id"], r["status"]) for r in first_runs] == [(r0, "complete")], (
        f"the class's file holds {first_runs} after the decision: the gate pass re-graded the "
        "current class (CT-CONSOLE-57)")
    assert scored_versions == {r0}, f"the class file holds grades under {scored_versions}"
    assert r1.encode() not in exports[0], "the class export cites R1"
    assert len(exports) == 3, "the R1 check never ran"
    assert exports[0] == exports[1], "fixture: the export is not stable with nothing changed"
    assert exports[2] == exports[0], (
        "the class's export changed when R1 went live: the gate pass touched the first class")
    assert revision["state"] == "live" and revision["non_inferiority"] == "pass", revision
    assert delivered == r1, f"the next class would be graded with {delivered}, not R1"
    assert clarified["state"] == "live", clarified
    assert CHECKING_SENTENCE not in nxt["detail"], "a second R1 pass was planned"
    assert [r["package_version_id"] for r in runs] == [r0, r1], runs


@pytest.mark.parametrize("gate", ["non_inferiority", "back_translation"])
def test_tc_console_115_a_failed_gate_sets_r1_aside_with_its_reason(
        tmp_path, monkeypatch, network_guard, gate):
    """NI fails (R1 moves three of four papers a full band against 0.10) or BT fails (the
    checker constructs a divergent answer): R1 is set aside with the reason the teacher reads,
    the class keeps R0's grades, and the next class is delivered R0. A failed BT buys no R1
    pass: no run grades R1 anywhere."""
    from aeh.calib.first_class import BACK_TRANSLATION_REASON, NON_INFERIORITY_REASON

    with _world(tmp_path, monkeypatch, network_guard) as world, \
            off_panel_checker(monkeypatch, constructs=(gate == "back_translation")):
        monkeypatch.setenv(THRESHOLD_ENV, "0.10")
        if gate == "non_inferiority":
            world.judge_rule = shifting_under_r1
        r0 = world.package_version
        r1 = _answered(world)
        outcome = world.start_class()
        revision = world.catalog().calibration_revision(r1)
        delivered = world.catalog().delivered_version()
        clarified = world.examples_read()["clarified_rubric"]
        (run,) = world.class_runs()
        r1_runs = [path.name for path in (world.root / "cohorts").glob("*.sqlite")
                   if _runs_under(path, r1)]
    assert outcome["detail"].endswith(CHECKING_SENTENCE), outcome["detail"]
    assert run["package_version_id"] == r0
    assert revision["state"] == "set_aside", revision
    assert delivered == r0, f"a set-aside R1 is delivered: {delivered}"
    reason = NON_INFERIORITY_REASON if gate == "non_inferiority" else BACK_TRANSLATION_REASON
    assert revision["reason"] == reason and clarified == {"state": "set_aside",
                                                          "text": reason}, (revision, clarified)
    if gate == "non_inferiority":
        assert (revision["non_inferiority"], revision["shifted_papers"]) == ("fail", 3), revision
    else:
        assert revision["non_inferiority"] == "not_run", revision
        assert r1_runs == [], f"a failed back-translation still bought an R1 pass: {r1_runs}"


def _runs_under(path, version: str) -> bool:
    import sqlite3

    with sqlite3.connect(path) as connection:
        try:
            return bool(connection.execute(
                "SELECT 1 FROM run WHERE package_version_id = ?", (version,)).fetchall())
        except sqlite3.OperationalError:
            return False


def test_tc_console_115_headless_aeh_run_grades_r0_only_and_leaves_r1_pending(
        tmp_path, monkeypatch, network_guard):
    """With R1 pending, the headless `aeh run` grades the class under R0, plans no R1 pass (no
    claim on R1, no run under R1 anywhere) and leaves R1 pending."""
    from aeh.pipeline import cli

    with _world(tmp_path, monkeypatch, network_guard) as world, \
            off_panel_checker(monkeypatch, constructs=False):
        monkeypatch.setenv(THRESHOLD_ENV, "0.10")
        r0 = world.package_version
        r1 = _answered(world)
        with redirect_stdout(io.StringIO()) as out:
            code = cli.main(["run", "--data-dir", str(world.root), "--cohort", world.cohort_id,
                             "--package-version", r0, "--config", str(PANEL_CONFIG)])
        result = json.loads(out.getvalue()[out.getvalue().index("{"):])
        revision = world.catalog().calibration_revision(r1)
        runs = world.class_runs()
        r1_runs = [path.name for path in (world.root / "cohorts").glob("*.sqlite")
                   if _runs_under(path, r1)]
    assert code == 0 and result["status"] == "complete", result.get("status")
    assert [r["package_version_id"] for r in runs] == [r0], runs
    assert revision["state"] == "pending" and not revision["first_class_run_id"], revision
    assert r1_runs == [], f"the headless run graded R1 somewhere: {r1_runs}"
