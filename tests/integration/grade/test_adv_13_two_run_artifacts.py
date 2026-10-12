"""`ADV-13` (issue #393, TS-99) — the "re-run until a better mark" attack over
F-DEV-PIPE-TWO-RUN: run B (a re-run after a key correction, judged higher up the scale) must
not move anything an operator already read about run A.

Gap-fix test plan §6.6 (adversarial, rung 3), tracing `CT-AGG-20`, `FR-GRADE-18` and
`FR-REVIEW-18`. `TC-GRADE-25` owns the underlying read (`M-GRADE`'s `compute_all(A)` is
run-scoped, over hand-written scores); this case drives BOTH runs through the composed
pipeline and holds the wider surface the attack actually aims at: run A's console screens
(S9 review, S12 rollup), its recomputed grades, its review queue and its aggregation signals.
Every run-A artifact is byte-identical to its pre-B snapshot — or the console refuses to
render A — and run B's band names appear in none of them.

Disclosed: the corpus's `run-b` arm sits at ordinal 3 ('developing') of the six-band scale,
not literally the top — what the case needs is bands run B awarded that run A never did, and
the two arms' bands are disjoint (ordinals 1 vs 3). `ReviewQueue.build_seconds` is a
wall-clock measurement of the build itself and is
excluded from the byte comparison; everything else in each serialization is content. The band
absence is asserted as substring absence over each artifact. As verified against this corpus,
run A's S9/S12 HTML carry no band name at all, so that clause bites on the three data
serializations (grades, review queue, aggregation signals) while byte-identity is what
protects the screens; if a future screen renders a band legend, the substring check would
fail there as a false positive — narrow the clause to the data fields in the same change.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from aeh.console import SCREENS, build_console
from aeh.grade import open_grade
from aeh.review import review_service_over
from harness.corpora import dev_pipe
from tests.support import pipe_world

pytestmark = pytest.mark.integration

#: The review budget a queue build is asked for — fixed, so the build itself is deterministic.
BUDGET_MINUTES = 30

#: Run A's judged bands come from the two-run corpus's `run-a` arm, run B's from `run-b`: the
#: corpus panels every judged criterion unanimously at ONE ordinal per arm, so each run's final
#: bands are exactly its arm's ordinal. They must differ — or the attack has nothing to catch.
RUN_A_ORDINAL = dev_pipe.TWO_RUN_ORDINALS["run-a"]
RUN_B_ORDINAL = dev_pipe.TWO_RUN_ORDINALS["run-b"]


def _bands(ordinal: int) -> frozenset[str]:
    return frozenset(
        dev_pipe.band_at(criterion_id, ordinal)
        for criterion_id in dev_pipe.OPEN_CRITERION_IDS
    )


def _queue_bytes(store, run_id: str) -> str:  # noqa: ANN001
    queue = review_service_over(store, run_id=run_id).build_queue(
        run_id, BUDGET_MINUTES, record=False
    )
    payload = dataclasses.asdict(queue)
    payload.pop("build_seconds")  # the build's own wall time: measurement, not content
    return json.dumps(payload, sort_keys=True, default=str)


def _grade_bytes(store, run_id: str) -> str:  # noqa: ANN001
    open_grade(store).compute_all(run_id)
    rows = sorted(
        (dict(row) for row in store.cohort(pipe_world.PIPE_COHORT_ID).query(
            "SELECT submission_id, total, grade, criteria_total, criteria_auto, score_low, "
            "score_high, state FROM submission_grade WHERE run_id = :r AND is_current = 1",
            r=run_id)),
        key=lambda row: row["submission_id"])
    return json.dumps(rows, sort_keys=True, default=str)


def _signals_bytes(store, run_id: str) -> str:  # noqa: ANN001
    from aeh.agg.metrics import aggregation_signals

    signals = aggregation_signals(store.cohort(pipe_world.PIPE_COHORT_ID), run_id)
    return json.dumps(dataclasses.asdict(signals), sort_keys=True, default=str)


def _judged_bands(store, run_id: str) -> set[str]:  # noqa: ANN001
    handle = store.cohort(pipe_world.PIPE_COHORT_ID)
    placeholders = ", ".join(f":c{i}" for i in range(len(dev_pipe.OPEN_CRITERION_IDS)))
    params = {"r": run_id, **{
        f"c{i}": cid for i, cid in enumerate(dev_pipe.OPEN_CRITERION_IDS)}}
    return {
        str(row["band"])
        for row in handle.query(
            f"SELECT DISTINCT band FROM criterion_score WHERE run_id = :r "
            f"AND criterion_id IN ({placeholders})", **params)
    }


def _artifacts(store, run_id: str) -> dict[str, str]:  # noqa: ANN001
    """Every artifact the plan row names, as a comparable string keyed by what it is."""
    app = build_console(store=store)
    return {
        "S9": app.render(SCREENS["S9"], id=run_id).html,
        "S12": app.render(SCREENS["S12"], id=run_id).html,
        "grades": _grade_bytes(store, run_id),
        "review_queue": _queue_bytes(store, run_id),
        "aggregation_signals": _signals_bytes(store, run_id),
    }


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory):
    """Run A driven and snapshotted; run B driven over the SAME store; run A re-snapshotted.

    The fixture also holds the attack's precondition where it is checkable: both runs
    completed, each judged at its own arm's bands, and the arms' bands differ."""
    root = tmp_path_factory.mktemp("adv13-two-run") / "w"
    mp = pytest.MonkeyPatch()
    try:
        world = pipe_world.two_run_replay_world(root, "run-a", monkeypatch=mp)
        world.build_run()
        world.start_run()
        try:
            result = pipe_world.drive_composed(world)
            assert result.status == "complete", f"fixture: run A {result.status}"
            run_a = world.run_id
            assert _judged_bands(world.store, run_a) == _bands(RUN_A_ORDINAL), (
                "fixture: run A's judged bands are not its arm's"
            )
            pre = _artifacts(world.store, run_a)

            run_b = pipe_world.drive_second_run(world, "run-b")
            assert _judged_bands(world.store, run_b) == _bands(RUN_B_ORDINAL), (
                "fixture: run B's judged bands are not its arm's"
            )
            assert _bands(RUN_A_ORDINAL) & _bands(RUN_B_ORDINAL) == set(), (
                "fixture: the two arms' bands do not differ"
            )
            post = _artifacts(world.store, run_a)
        finally:
            world.store.close()
        return run_a, run_b, pre, post
    finally:
        mp.undo()


def test_adv_13_run_b_moves_nothing_run_a_already_showed(two_runs):
    run_a, run_b, pre, post = two_runs
    assert run_b != run_a, "fixture: the second drive did not open a new run"

    for name, before in pre.items():
        assert post[name] == before, (
            f"ADV-13: run B moved run A's {name} — a re-run may produce its own record, "
            "never rewrite the one the operator already read (CT-AGG-20, FR-GRADE-18, "
            f"FR-REVIEW-18)\nfirst difference at: {_first_difference(before, post[name])}"
        )


def test_adv_13_run_b_bands_appear_in_no_run_a_artifact(two_runs):
    run_a, _run_b, pre, _post = two_runs
    leaked = {
        name: band
        for name, artifact in pre.items()
        for band in _bands(RUN_B_ORDINAL)
        if band in artifact
    }
    assert not leaked, (
        f"ADV-13: run B's band names appear in run A's artifacts {leaked} — run B's top "
        "bands must appear in none of them"
    )


def _first_difference(before: str, after: str) -> str:
    for index, (left, right) in enumerate(zip(before, after)):
        if left != right:
            return f"offset {index}: ...{before[max(0, index - 40):index + 40]!r}..."
    return f"length {len(before)} -> {len(after)}"