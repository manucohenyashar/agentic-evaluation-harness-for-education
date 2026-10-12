"""`TC-CONSOLE-59` (issue #771, FR-CONSOLE-48, CT-CONSOLE-38) — the context read: the
switcher feed every entity on the home page renders from.

| Arm | Expected |
|---|---|
| a console over an empty store | every collection an **empty list**, never null; the enums exactly the declared sets |
| a store seeded with 2 classes, 3 cohorts, 2 packages, 2 runs | each entity present with its `state` in the declared enum, and the derived states the ledger population dictates: a roster-only ledger is a class, a ledger with papers but no run is a ready cohort, a ledger whose newest run is pending is grading |

The seeding writes the ledger rows the shipped writers produce (the `console_world`
discipline): the two runs ride `seed_scored_run`'s real `PackageCatalog` / `Orchestrator`
/ `DeterministicEvaluator` / `GradingService` chain; the extra ledger rows are the column
shape `M-INGEST` and the class actions write.

**Isolation: rung 3 (E1)** — a real store, a real console on a real loopback socket; the
read is taken over the console's own HTTP surface.
"""

from __future__ import annotations

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
from tests.support.console_redesign_world import _get_json, served_console
from tests.support.console_world import seed_scored_run

pytestmark = pytest.mark.integration

#: The declared enum sets, as the read itself publishes them — asserted verbatim so a
#: renamed or dropped value fails here rather than at the SPA.
DECLARED_ENUMS = {
    "stage_states": ["done", "in_progress", "not_started", "needs_attention",
                     "failed", "queued"],
    "class_states": ["empty", "roster_only"],
    "cohort_states": ["empty", "ready", "grading", "graded", "stalled"],
    "package_states": ["drafting", "draft_ready", "published"],
    "run_states": ["pending", "running", "paused", "complete", "failed"],
    "run_stages": ["papers", "grading", "reviewing", "exporting"],
}


def _seed_class_ledger(store, cohort_id: str, students: int) -> None:
    """One class ledger: a cohort row and `students` roster rows, no papers, no runs —
    the shape `create class` leaves and `ADR-48` classifies as a class."""
    handle = store.cohort(cohort_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES (:c, 'synthetic', '2026-01-01T00:00:00+00:00')",
            c=cohort_id,
        )
        for index in range(students):
            tx.execute(
                "INSERT INTO roster (cohort_id, student_ref) VALUES (:c, :r)",
                c=cohort_id, r=f"ref-{cohort_id}-{index + 1}",
            )


def _seed_papers_only_ledger(store, cohort_id: str, papers: int) -> None:
    """One grading cohort with papers but no run yet — the ready state `_cohort_state`
    derives when nothing has run."""
    handle = store.cohort(cohort_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES (:c, 'synthetic', '2026-01-01T00:00:00+00:00')",
            c=cohort_id,
        )
        for index in range(papers):
            tx.execute(
                "INSERT INTO submission (submission_id, cohort_id, student_ref) "
                "VALUES (:s, :c, :r)",
                s=f"sub-{cohort_id}-{index + 1}", c=cohort_id,
                r=f"ref-{cohort_id}-{index + 1}",
            )


def test_tc_console_59_an_empty_store_answers_empty_collections_and_the_declared_enums(
        served_console):
    """With nothing seeded, every collection is an empty list — never null, never an
    error — and the enums are exactly the declared sets."""
    _server, port, _store, _data_dir = served_console

    context = _get_json(port, "/api/v1/context")

    for name in ("classes", "cohorts", "packages", "runs"):
        assert context[name] == [], (
            f"the empty console's {name} read as {context[name]!r}; the switcher "
            "renders empties, so an empty store answers an empty list, not null")
    assert context["enums"] == DECLARED_ENUMS
    assert context["projected"] == {
        "classes": 0, "cohorts": 0, "packages": 0, "runs": 0, "ledgers_skipped": 0,
    }


def test_tc_console_59_a_seeded_store_classifies_every_entity_into_its_declared_enum(
        served_console):
    """The seeded store reads back as 2 classes, 3 cohorts, 2 packages and 2 runs, every
    entity's state inside the enum the read declares, and the derived states the ledger
    contents dictate."""
    _server, port, store, _data_dir = served_console
    seed_scored_run(store, cohort_id="c-a", run_id="r-a", package_id="pkg-a",
                    submissions=3, finalize=True)
    seed_scored_run(store, cohort_id="c-b", run_id="r-b", package_id="pkg-b",
                    submissions=3, finalize=True)
    _seed_papers_only_ledger(store, "c-c", papers=2)
    _seed_class_ledger(store, "cl-a", students=3)
    _seed_class_ledger(store, "cl-b", students=0)

    context = _get_json(port, "/api/v1/context")

    assert len(context["classes"]) == 2, (
        f"the read listed {len(context['classes'])} class(es): "
        f"{[row['cohort_id'] for row in context['classes']]}")
    assert len(context["cohorts"]) == 3
    assert len(context["packages"]) == 2
    assert len(context["runs"]) == 2

    classes = {row["cohort_id"]: row for row in context["classes"]}
    assert classes["cl-a"]["state"] == "roster_only", (
        "a ledger with roster rows and no papers or runs is a class in roster-only "
        "state (ADR-48)")
    assert classes["cl-a"]["students"] == 3
    assert classes["cl-b"]["state"] == "empty"
    assert classes["cl-b"]["students"] == 0

    cohorts = {row["cohort_id"]: row for row in context["cohorts"]}
    # Both seeded cohorts' newest run is `pending` (the seed never starts the run's
    # clock, the same state a run sits in between creation and dispatch).
    assert cohorts["c-a"]["state"] == "grading"
    assert cohorts["c-b"]["state"] == "grading"
    assert cohorts["c-c"]["state"] == "ready", (
        "a cohort with papers and no run yet is ready, not empty")
    assert cohorts["c-c"]["students"] == 2

    for row in context["packages"]:
        assert row["state"] in DECLARED_ENUMS["package_states"]
        assert row["package_id"] in ("pkg-a", "pkg-b")
        assert row["published_version"] is None, (
            "a seeded catalog version is not locked, so nothing is published yet")
        assert [stage["stage"] for stage in row["wizard"]] == [
            "create package", "review draft", "approve package"]
        assert all(stage["state"] in DECLARED_ENUMS["stage_states"]
                   for stage in row["wizard"])

    for row in context["runs"]:
        assert row["state"] in DECLARED_ENUMS["run_states"]
        assert row["stage"] in DECLARED_ENUMS["run_stages"]
        assert row["run_id"] in ("r-a", "r-b")
        assert row["package_id"] in ("pkg-a", "pkg-b")
        assert row["cohort_id"] in ("c-a", "c-b")
        assert row["package_version_id"], "the run row names no package version"

    for name, states in (("classes", DECLARED_ENUMS["class_states"]),
                         ("cohorts", DECLARED_ENUMS["cohort_states"])):
        for row in context[name]:
            assert row["state"] in states, (
                f"{name} entry {row['cohort_id']!r} carries state "
                f"{row['state']!r}, outside the declared enum")

    assert context["projected"] == {
        "classes": 2, "cohorts": 3, "packages": 2, "runs": 2, "ledgers_skipped": 0,
    }
