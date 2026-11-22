"""Validity T8 (issue #901), rung 3: TC-CONSOLE-109 (FR-CONSOLE-85) and TC-CONSOLE-110
(FR-CONSOLE-84).

| Case | What is asserted |
|---|---|
| TC-CONSOLE-109 | on the console's ENG7 run, before any record (draw open) and after Finish (recorded), no answer of any GET in the route table and no legacy page shows 0.63, nor an `n` of 15 beside an agreement figure; the legacy rollup with no record shows the absence sentence |
| TC-CONSOLE-110 | the package record read on a record seed: the version's FR-CONSOLE-74 label, the class names, and no string field matching the TC-CONSOLE-87 census |

The AST halves (`STANDING_AGREEMENT_FIGURE` absent, no 0.63 literal; TC-REG-25) are in
`tests/contract/console/test_tc_console_109_reg_25_no_fabricated_figure.py`.

**Disclosed.** TC-CONSOLE-110's record seed is two administrations of one version (class A
marked in full, class B skipped) through M-REVIEW and `promote_administration`, with the
package named `PHYS-QUIZ-01` rather than the validity seed's `pkg-validity`: that fixture id
would trip the census's `pkg-` pattern through the version label, which is a fixture
artifact, not the read's. Class names are the class ids the console uses as their names
everywhere (the context read's `label` is the cohort key too).

**Written ahead: no** (S11 #881 merged).
"""

from __future__ import annotations

import html
import re
from typing import Any

import pytest

from tests.integration.console.test_tc_console_108_116_held_back import _drive
from tests.support import validity_seed
from tests.support.eng7_console import eng7_console
from tests.support.label_identity_world import ServedRun
from tests.support.teacher_text_census import census_findings

pytestmark = pytest.mark.integration

FABRICATED = re.compile(r"(?<![\d.])0\.63(?!\d)")
FIGURE_KEYS = {"kappa", "qwk", "agreement", "agreement_kappa", "matched"}
ABSENCE = ("no new validation evidence for this administration",
           "The package's prior record, if any, is shown separately")


def _figure_n_15(value: Any) -> list[str]:
    found = []
    if isinstance(value, dict):
        if value.get("n") == 15 and FIGURE_KEYS & set(value):
            found.append(repr(value)[:200])
        for item in value.values():
            found += _figure_n_15(item)
    elif isinstance(value, list):
        for item in value:
            found += _figure_n_15(item)
    return found


def _fabricated(answers: dict[str, Any]) -> list[str]:
    problems = []
    for where, answer in answers.items():
        text = answer if isinstance(answer, str) else repr(answer)
        if FABRICATED.search(text):
            problems.append(f"{where}: shows 0.63")
        if isinstance(answer, str):
            if re.search(r"n\s*=\s*15\b|\"n\":\s*15\b", answer) and "kappa" in answer:
                problems.append(f"{where}: an n of 15 beside kappa")
        else:
            problems += [f"{where}: {item}" for item in _figure_n_15(answer)]
    return problems


def test_tc_console_109_no_served_answer_shows_the_fabricated_figure(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-109 (rung 3). The route-table walk twice: with the draw open (no record:
    the legacy rollup shows the absence sentence) and after Finish (a record stands)."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        read = served.open_draw()
        subs = sorted(served.names())
        open_answers = _drive(served, subs)
        rollup = html.unescape(open_answers["/runs/{id}/rollup"])
        assert all(part in rollup for part in ABSENCE), (
            f"the legacy rollup with no record does not show the absence sentence: "
            f"{rollup[:2000]}")
        problems = _fabricated(open_answers)

        for seat in read["seats"]:
            served.dispatched("blind-sample draft", run_id=served.run_id,
                              seat_id=seat["seat_id"], band=seat["bands"][-1]["name"])
        served.dispatched("blind-sample finish", run_id=served.run_id)
        recorded = _drive(served, subs)
        status, validity = served.get("/api/v1/results/validity", run_id=served.run_id)
        assert status == 200 and validity["state"] == "recorded", validity
        problems += _fabricated(recorded)
        assert not problems, "a fabricated agreement figure is served:\n  " + \
            "\n  ".join(problems)


def test_tc_console_110_the_package_record_read_speaks_in_teacher_labels(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-110. `GET /api/v1/packages/record` on a two-class record: `version_label` is
    the FR-CONSOLE-74 label (`<package> version 1`), the administrations name the classes,
    and no string field matches the teacher-text census."""
    from aeh.console import serve_console

    monkeypatch.setattr(validity_seed, "PACKAGE_ID", "PHYS-QUIZ-01")
    world = validity_seed.ValidityStore(tmp_path / "w")
    try:
        first = world.administer("class-a", validity_seed.VALIDITY_SYSTEM)
        seats = world.draw(first, 24)
        world.mark(first, seats, validity_seed.teacher_bands(first,
                                                             validity_seed.VALIDITY_TEACHER))
        world.finish(first)
        assert world.promote(first, "finish").promoted
        second = world.administer("class-b", validity_seed.VALIDITY_SYSTEM)
        world.skip(second)
        world.promote(second, "skip")

        for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
            monkeypatch.delenv(name, raising=False)
        network_guard.uninstall()
        server = serve_console(store=world.store)
        try:
            console = ServedRun(world=first, server=server,
                                port=server.socket.getsockname()[1], root=world.root)
            status, read = console.get("/api/v1/packages/record",
                                       package_version_id=first.package_version_id)
        finally:
            try:
                server.terminate()
            finally:
                network_guard.install()
        assert status == 200, read
        assert read["version_label"] == "PHYS-QUIZ-01 version 1", read["version_label"]
        assert [item["class_name"] for item in read["administrations"]] == [
            "class-a", "class-b"], read["administrations"]
        assert read["blind_labels"] == 24, read
        findings = census_findings(read)
        assert not findings, "the record read shows ids to the teacher:\n  " + \
            "\n  ".join(findings)
        planted = census_findings({**read, "version_label": first.package_version_id})
        assert planted, "the census does not see a version id in a teacher field"
    finally:
        world.close()
