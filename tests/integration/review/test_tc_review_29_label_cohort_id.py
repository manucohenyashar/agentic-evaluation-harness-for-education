"""`TS-89` (issue #383) — `TC-REVIEW-29`: a label's `cohort_id` is the cohort, never the run
(`FR-REVIEW-22`).

| Input | Expected |
|---|---|
| a new label collected under run `RA` of cohort `K1` | `cohort_id = 'K1'`, never `'RA'` |
| an F-SCHEMA Durable v8 DB whose labels carry run ids | the resolvable rows are rewritten to `'K1'` — **#434's, see below** |
| an unresolvable row | pending Q-16 |

**Why the column has to be the cohort.** `cohort_id` is what the purge gate reads: a cohort is
purged when its Tier C rows are gone and its Tier D evidence is accounted for. A label carrying
a *run* id there belongs to a cohort the gate cannot find, so the gate looks for rows under a
key nothing holds — and the purge it guards can never pass. The failure is silent and it
accumulates: every run leaves labels the retention sweep will never be able to clear.

**One run is not one cohort.** A cohort is graded by many runs over its life — a re-run, a
re-scored criterion, a second administration against a revised package — so a run id in a
cohort column is not merely the wrong name for the right thing. It partitions one cohort's
labels into as many groups as it had runs.

**The backfill arm is #434's and is deliberately not written here.** Issue #434 —
"M-REVIEW: decide FR-REVIEW-22's historical `cohort_id` backfill (**not expressible as a
migration**)" — is open, and it is open on the *decision*, not on the code: a migration cannot
resolve a run id to a cohort id without reading a different tier's tables, and what to do with
an unresolvable row is Q-16, still unanswered. Writing a test against an interface nobody has
chosen would pin a guess. So this file asserts the arm that ships — every label the system can
write today carries the cohort — and #383 reports the backfill arm as waiting on #434's
decision, with the unresolvable variant waiting on Q-16 behind it.

**Isolation: rung 2** — a real store, a real run, and the service route that writes the column.
"""

from __future__ import annotations

from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
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
from aeh.review import _service_from_store
from aeh.store import Statement, open_store
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

SUBMISSION = "S001"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

_LABELS = Statement("SELECT label_id, run_id, cohort_id FROM label ORDER BY rowid")


@pytest.fixture
def cohort_world(tmp_data_dir):
    """Run RA over cohort K1 (`ORCH_COHORT_ID`), with one queued score to act on."""
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_id, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        write_criterion_scores(
            store.cohort(ORCH_COHORT_ID),
            [(SUBMISSION, CRITERION, "B1", 6.0, "provisional")],
        )
        yield store, tmp_data_dir, run_id
    finally:
        store.close()


def _labels(tmp_data_dir) -> list[dict[str, Any]]:
    store = open_store(tmp_data_dir)
    try:
        return [dict(row) for row in store.durable().query(_LABELS)]
    finally:
        store.close()


def _act(store: Any, run_id: str) -> None:
    service = _service_from_store(
        store, cohort_ids=[ORCH_COHORT_ID], run_id=run_id,
    )
    queue = service.build_queue(run_id, 60, record=False)
    entry = queue.shown[0]
    members = getattr(entry, "members", None)
    service.act(members[0] if members else entry, "accept")


# --- TC-REVIEW-29 ---------------------------------------------------------------------------


def test_tc_review_29_a_new_label_carries_the_cohort_not_the_run(cohort_world):
    """The label written under run RA of cohort K1 carries `cohort_id = K1`.

    Both halves of the assertion matter. "Is K1" is the requirement; "is not RA" is the
    regression, because a run id in this column is a plausible-looking value that no purge
    gate can resolve — the failure is silent, and it accumulates one cohort's worth of
    unclearable labels per run.
    """
    store, tmp_data_dir, run_id = cohort_world
    _act(store, run_id)

    rows = _labels(tmp_data_dir)
    assert len(rows) == 1, f"the action wrote {len(rows)} labels, not one"
    label = rows[0]

    assert label["cohort_id"] == ORCH_COHORT_ID, (
        f"the label's cohort_id is {label['cohort_id']!r}, not {ORCH_COHORT_ID!r}. The purge "
        "gate reads this column to find a cohort's labels; a value it cannot resolve means "
        "the gate never passes and the rows are never cleared (FR-REVIEW-22)"
    )
    assert label["cohort_id"] != run_id, (
        f"the label's cohort_id is the RUN id {run_id!r}. One cohort is graded by many runs "
        "over its life, so a run id here also splits one cohort's labels into one group per "
        "run"
    )


def test_tc_review_29_the_run_is_recorded_separately_and_is_still_the_run(cohort_world):
    """`run_id` and `cohort_id` are different columns holding different facts.

    The control for the case above: asserting only "cohort_id is not the run id" would pass
    against a writer that left the column NULL, or that lost the run attribution entirely.
    Both facts are recorded, and each in its own column.
    """
    store, tmp_data_dir, run_id = cohort_world
    _act(store, run_id)

    label = _labels(tmp_data_dir)[0]

    assert label["run_id"] == run_id, (
        f"the label's run_id is {label['run_id']!r}, not {run_id!r} — the run attribution is "
        "a real fact and moving the cohort into the right column must not lose it"
    )
    assert label["cohort_id"] and label["run_id"], (
        f"a column was left empty: cohort_id={label['cohort_id']!r}, "
        f"run_id={label['run_id']!r}"
    )


def test_tc_review_29_the_cohort_column_resolves_to_a_real_cohort(cohort_world):
    """The value written is a cohort the store actually holds.

    What the purge gate needs is not "a cohort-shaped string" but a key that resolves. This
    is the assertion a writer that stamped a constant, or a sanitised version of the name,
    would fail — and it is the property the gate depends on.
    """
    store, tmp_data_dir, run_id = cohort_world
    _act(store, run_id)

    label = _labels(tmp_data_dir)[0]
    cohorts = {
        str(row["cohort_id"])
        for row in store.cohort(ORCH_COHORT_ID).query(
            Statement("SELECT cohort_id FROM cohort")
        )
    }

    assert str(label["cohort_id"]) in cohorts, (
        f"the label names cohort {label['cohort_id']!r}, which the store does not hold: "
        f"{sorted(cohorts)}"
    )
