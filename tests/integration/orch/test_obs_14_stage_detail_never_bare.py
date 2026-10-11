"""`OBS-14` (issue #393, TS-99) — `RunResult.stages[*].detail` is never a bare status (seam 4).

Gap-fix test plan §6.10 (observability, rung 3), over the composed run of `TC-PIPE-01` and
`TC-PIPE-13` — the whole-pipeline surface, where every hook the drive carries (deterministic,
extraction, integrity, aggregation, escalation, synthesis, grading) must name what it did.

A `status=success` sitting on top of an empty result is the top silent-failure trap: `CLAUDE.md`'s
fourth seam — *stage-level observability in the result. Surface what each stage did, next to the
status* — and `StageTrace`'s own docstring makes the same promise ("`detail` is never a bare
status … so every entry says what was processed"). `CT-INGEST-08` built the promise for one
report (`IngestReport.gates` per-gate, never one boolean); this case holds the pipeline's own
result object to it: every stage trace on a real composed drive carries a non-empty detail
tuple, and no element of any detail is a bare status word — `"ok"`, `"success"`, `"done"` or
`""` — which is the vocabulary a lazy stage substitutes for the description of what it did.
"""

import pytest

import aeh.pipeline as pipeline
from tests.support import pipe_world

pytestmark = pytest.mark.integration

#: The bare status words the clause names. A detail element equal to any of them says nothing
#: about what the stage did — it repeats the result's own status vocabulary inside the detail
#: tuple, which is exactly the substitution the seam forbids.
BARE_STATUS_WORDS = frozenset({"ok", "success", "done", ""})


@pytest.fixture(scope="module")
def composed_result(tmp_path_factory):
    """One composed F-DEV-PIPE drive — the same shape TC-PIPE-11's `uninterrupted` fixture runs,
    keeping the `RunResult` itself instead of its §4.3 projection."""
    root = tmp_path_factory.mktemp("obs14-composed") / "w"
    mp = pytest.MonkeyPatch()
    try:
        world = pipe_world.replay_world(root, monkeypatch=mp)
        world.build_run()
        world.start_run()
        try:
            result = pipe_world.drive_composed(world)
        finally:
            world.store.close()
        assert result.status == "complete", f"fixture: composed run {result.status}"
        return result
    finally:
        mp.undo()


def test_obs_14_no_stage_detail_is_a_bare_status(composed_result):
    result = composed_result
    assert result.stages, "fixture: the composed run produced no stage traces"
    bare = []
    for trace in result.stages:
        if not trace.detail:
            bare.append(f"{trace.stage}: empty detail tuple")
        for element in trace.detail:
            if element in BARE_STATUS_WORDS:
                bare.append(f"{trace.stage}: bare status element {element!r}")
    assert not bare, (
        "seam 4: every stage's detail must be a non-empty tuple that never repeats the "
        f"result's status vocabulary — {bare}"
    )


def test_obs_14_no_paused_stage_detail_is_a_bare_status(tmp_path):
    """The plan row's fixture column names TC-PIPE-13 as well as TC-PIPE-01: the fault path
    builds stage traces the complete run never carries — the hook fault's own detail and the
    recovery pass's — so a stage that emitted a bare status only there would slip past the
    complete-run case. TC-PIPE-13's aggregation-hook fault (`verdicts_for` raising once) is
    driven here, and the same clause is held over the paused drive's stage traces."""
    mp = pytest.MonkeyPatch()
    try:
        real = pipeline.verdicts_for
        raised: list[tuple[str, str]] = []

        def verdicts_for(cohort, run_id, submission_id, criterion_id):
            if not raised:
                raised.append((submission_id, criterion_id))
                raise KeyError("C9")
            return real(cohort, run_id, submission_id, criterion_id)

        mp.setattr(pipeline, "verdicts_for", verdicts_for)
        root = tmp_path / "w"
        world = pipe_world.replay_world(root, monkeypatch=mp)
        world.build_run()
        world.start_run()
        try:
            result = pipe_world.drive_composed(world)
        finally:
            world.store.close()
    finally:
        mp.undo()
    assert raised, "fixture: no aggregation ran"
    assert result.status == "paused", result.status

    bare = []
    for trace in result.stages:
        if not trace.detail:
            bare.append(f"{trace.stage}: empty detail tuple")
        for element in trace.detail:
            if element in BARE_STATUS_WORDS:
                bare.append(f"{trace.stage}: bare status element {element!r}")
    assert not bare, (
        "seam 4 on the paused drive: every stage's detail must be a non-empty tuple that "
        f"never repeats the result's status vocabulary — {bare}"
    )