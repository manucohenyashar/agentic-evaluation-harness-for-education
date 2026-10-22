"""`TC-CONSOLE-60` (issue #771, FR-CONSOLE-49) — the impact read: what editing a package
version would touch, before the teacher commits to an edit.

| Arm | Expected |
|---|---|
| (a) a version two runs covered, 24 students each | exactly `{runs: 2, students: 48}`, the two run records beside them, and the re-grading warning with the count in it |
| (b) a version nothing ever used | a measured zero — `{runs: 0, students: 0}` and the nothing-downstream sentence, never a refusal |
| (c) a version no package declares | refused with the teacher's sentence naming the package page |

The store is seeded through the shipped chain (`seed_scored_run`): one package version
administered to two cohorts, both runs graded and finalized, so the 48 counted students
are the read's own `is_current`-grade query's answer.

**Isolation: rung 3 (E1)** — a real store, a real console on a real loopback socket; the
read is taken over the console's own HTTP surface, refusals included.
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
from aeh.pkg import PackageCatalog
from tests.support.console_redesign_world import (
    _get_json,
    _request,
    served_console,
)
from tests.support.console_world import seed_scored_run

pytestmark = pytest.mark.integration


def test_tc_console_60a_a_version_two_runs_covered_reads_two_runs_and_forty_eight_students(
        served_console):
    """One version, two administrations, 24 students each: the read answers exactly two
    runs and 48 students, with the re-grading warning carrying the count."""
    _server, port, store, _data_dir = served_console
    first = seed_scored_run(store, cohort_id="c-i1", run_id="r-i1",
                            package_id="pkg-imp", submissions=24, finalize=True)
    version = first.package_version_id
    seed_scored_run(store, cohort_id="c-i2", run_id="r-i2", package_id="pkg-imp",
                    submissions=24, finalize=True, reuse_version=version)

    impact = _get_json(port, f"/api/v1/impact?package_version={version}")

    assert impact["package_version_id"] == version  # the id; `package_version` is the label (#808)
    assert impact["runs"] == 2, (
        f"the read counted {impact['runs']} run(s) under {version}; two "
        "administrations used it")
    assert impact["students"] == 48, (
        f"the read counted {impact['students']} student(s) graded under {version}; "
        "24 per administration, 48 in all")
    records = sorted(impact["run_records"], key=lambda row: row["run_id"])
    assert [row["run_id"] for row in records] == ["r-i1", "r-i2"]
    assert [row["cohort_id"] for row in records] == ["c-i1", "c-i2"]
    assert all(row["state"] == "pending" for row in records), (
        f"the run records' states are {[row['state'] for row in records]}; the seeded "
        "runs sit pending (created, not dispatched)")
    assert impact["regrading"] == {
        "triggered": True,
        "detail": "Editing the grading guide means 48 already-graded papers need "
                  "re-grading.",
    }
    assert impact["projected"] == {"runs": 2, "students": 48, "ledgers_skipped": 0}


def test_tc_console_60a_a_version_nothing_used_answers_a_measured_zero(served_console):
    """A second version of the same package, created and never administered: the read
    answers zeros with the nothing-downstream sentence — a measured zero, not a
    refusal."""
    _server, port, store, _data_dir = served_console
    first = seed_scored_run(store, cohort_id="c-i1", run_id="r-i1",
                            package_id="pkg-imp", submissions=3, finalize=True)
    catalog = PackageCatalog(store.package("pkg-imp"), package_id="pkg-imp")
    unused_version = catalog.create_version(None)
    assert unused_version != first.package_version_id

    impact = _get_json(port,
                       f"/api/v1/impact?package_version={unused_version}")

    assert impact["package_version_id"] == unused_version
    assert impact["runs"] == 0
    assert impact["students"] == 0
    assert impact["run_records"] == []
    assert impact["regrading"] == {
        "triggered": False,
        "detail": "Nothing downstream yet — no paper has been graded under it.",
    }
    assert impact["projected"] == {"runs": 0, "students": 0, "ledgers_skipped": 0}


def test_tc_console_60c_an_unknown_version_is_refused_with_the_package_page_sentence(
        served_console):
    """A version no package declares is refused with the teacher's sentence — the read
    refuses, it does not answer zeros about something that does not exist."""
    _server, port, _store, _data_dir = served_console

    status, _headers, raw = _request(
        port, "GET", "/api/v1/impact?package_version=pkg-imp@nosuch")
    body = json.loads(raw)

    assert status == 400, f"the unknown version answered {status}: {body!r}"
    assert body["error"] == (
        "There is no test package version with that reference. "
        "Choose one from the list on the package page."), (
        f"the refusal body is {body!r}")
