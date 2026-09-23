"""`TS-83` (issue #377) — `TC-PIPE-05` and `TC-PIPE-06`: the two-verdict fallback, and synthesis
then grading on completion (`FR-PIPE-05`, `FR-PIPE-06`; gap-fix test plan §5 / §6).

| Case | Expected |
|---|---|
| `TC-PIPE-05` | A cell with 3 score units, one quarantining after 3 strikes (`ProviderError("500")` ×3), leaves 2 verdicts → `aggregate` called with `fallback=True`; stored row `judge_count = 1`, `state = 'provisional'`; **no** row with `judge_count = 2` anywhere in the run. Variant: the quarantined unit's re-request succeeds → 3 verdicts, `fallback=False` |
| `TC-PIPE-06` | (a) all submissions complete → 3 narratives, 3 grades. (b) `S3` has an unscored criterion (quarantined) → no narrative for `S3` (`CT-SYNTH-05`) and `S3` still graded `incomplete`. (c) the synthesis fixture for `S2` is missing (`FixtureMissingError`) → no narrative for `S2`, `grades_computed = 3`, and the `synthesize` stage `detail` names `S2` and `FixtureMissingError` (Q-23) |

**`TC-PIPE-05`'s negative sweep is the assertion that matters.** "No row with `judge_count = 2`
exists anywhere in the run" is not a restatement of `judge_count = 1` — it is the specific wrong
answer an implementation gives when it aggregates the two surviving verdicts as an even panel
instead of taking the fallback. `FR-PIPE-05` says never with an even panel, so the sweep looks
across every cell, not just the injured one.

**`TC-PIPE-06` (b) and `TC-REQ-96`.** A submission with an unscored criterion gets no narrative,
and that absence is *not* a failure: the run still completes and no stage `detail` reports an
error for it. An implementation that treated "no narrative" as a fault would pause a run over a
quarantined criterion.

**`TC-PIPE-06` (c) is NOT implemented here, deliberately.** It needs the synthesis fixture for one
submission to be missing from a recorded corpus — a property of `F-DEV-PIPE`, which does not
exist (see this directory's `conftest.py`). Monkeypatching the provider to raise
`FixtureMissingError` would test the patch rather than `F-RECORDED`'s behaviour, so the arm is
left unwritten and named in #377's PR as blocked on the corpus. The `TC-PIPE-06` (c) row of the
RTM is therefore not covered by this file, and saying so is the point.

**The world:** see this directory's `conftest.py`. F-DEV-PIPE does not exist; `S2`/`S3` are
addressed positionally against this world's own admitted ids.

**Written ahead of implementation: yes** — `aeh.pipeline` is #364's.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.impl import PIPE_MODULE, require

pytestmark = pytest.mark.integration

ISSUE = "#364"

#: Three strikes is the ladder the plan names for the quarantining judge.
STRIKES = 3


class _StrikingProvider:
    """Raises `ProviderError("500")` for one judge's calls, forwarding everything else.

    The strikes land on the *provider*, which is where a real 500 lands — striking the worker
    directly would skip the taxonomy the strike ladder is built on.
    """

    def __init__(self, inner: Any, *, judge_id: str, strikes: int = STRIKES) -> None:
        self._inner = inner
        self._judge_id = judge_id
        self._budget = strikes
        self.struck = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def complete(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        build = getattr(getattr(request, "model_ref", None), "build_id", None)
        if build == self._judge_id and self._budget > 0:
            self._budget -= 1
            self.struck += 1
            from aeh.prov import ProviderError

            raise ProviderError("500")
        return self._inner.complete(request, *args, **kwargs)


def _all_scores(world: Any) -> list[dict[str, Any]]:
    from aeh.store import Statement

    return [
        dict(row) for row in world.handle.query(
            Statement(
                "SELECT submission_id, criterion_id, judge_count, state "
                "FROM criterion_score WHERE run_id = :run_id"
            ),
            run_id=world.run_id,
        )
    ]


def _narratives(world: Any) -> set[str]:
    from aeh.store import Statement

    return {
        str(row["submission_id"])
        for row in world.handle.query(
            Statement("SELECT DISTINCT submission_id FROM narrative"),
        )
    }


def _grades(world: Any) -> dict[str, Any]:
    from aeh.store import Statement

    return {
        str(row["submission_id"]): dict(row)
        for row in world.handle.query(
            Statement(
                "SELECT submission_id, status FROM submission_grade "
                "WHERE run_id = :run_id AND is_current = 1"
            ),
            run_id=world.run_id,
        )
    }


# --- TC-PIPE-05 ----------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_pipe_05_two_surviving_verdicts_aggregate_with_fallback(make_pipe_world,
                                                                   monkeypatch):
    """`TC-PIPE-05` — one judge quarantines after three strikes, and the cell is aggregated
    with `fallback=True` rather than as an even two-judge panel.

    The `aggregate` call is spied rather than inferred from the stored row, because the row
    alone cannot distinguish "fallback was requested" from "the numbers happened to agree".
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    import aeh.agg

    observed: list[Any] = []
    original = aeh.agg.aggregate

    def _spy(*args: Any, **kwargs: Any) -> Any:
        observed.append(kwargs.get("fallback"))
        return original(*args, **kwargs)

    monkeypatch.setattr(aeh.agg, "aggregate", _spy)
    world = make_pipe_world()
    striking = _StrikingProvider(world.provider, judge_id=world.panel_refs[0].build_id)

    run_to_completion(
        world.store, world.run_id, provider=striking, run_config=world.resolved,
    )

    assert striking.struck == STRIKES, (
        f"the injected judge was struck {striking.struck} time(s), not {STRIKES}; the strike "
        "ladder never quarantined it, so no cell lost a verdict"
    )
    assert True in observed, (
        f"aggregate was never called with fallback=True: {observed}. FR-PIPE-05 aggregates a "
        "cell left with exactly two verdicts as a fallback, never as an even panel"
    )


@pytest.mark.writtenahead
def test_tc_pipe_05_no_cell_is_ever_scored_as_an_even_panel(make_pipe_world):
    """`TC-PIPE-05`'s negative sweep — **no** row with `judge_count = 2` anywhere in the run.

    This is the specific wrong answer, not a restatement of the positive: an implementation
    that aggregated the two survivors as a panel of two writes exactly this row, and every
    other assertion in this file still passes.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()
    striking = _StrikingProvider(world.provider, judge_id=world.panel_refs[0].build_id)

    run_to_completion(
        world.store, world.run_id, provider=striking, run_config=world.resolved,
    )

    even = [row for row in _all_scores(world) if row["judge_count"] == 2]
    assert even == [], (
        f"{len(even)} criterion_score row(s) carry judge_count = 2: {even[:3]}. FR-PIPE-05: a "
        "cell that lost a verdict is aggregated with fallback, never as an even panel"
    )


@pytest.mark.writtenahead
def test_tc_pipe_05_a_successful_re_request_keeps_three_verdicts_and_no_fallback(
    make_pipe_world, monkeypatch
):
    """Variant — one of three is quarantined but its re-request succeeds → 3 verdicts,
    `fallback=False`. The pair is what stops the fallback from being applied unconditionally."""
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    import aeh.agg

    observed: list[Any] = []
    original = aeh.agg.aggregate

    def _spy(*args: Any, **kwargs: Any) -> Any:
        observed.append(kwargs.get("fallback"))
        return original(*args, **kwargs)

    monkeypatch.setattr(aeh.agg, "aggregate", _spy)
    world = make_pipe_world()
    # One strike only: the ladder re-requests and the judge answers.
    striking = _StrikingProvider(world.provider, judge_id=world.panel_refs[0].build_id,
                                 strikes=1)

    run_to_completion(
        world.store, world.run_id, provider=striking, run_config=world.resolved,
    )

    assert striking.struck == 1, "precondition: the single strike never landed"
    assert observed, "aggregate was never called"
    assert True not in observed, (
        f"aggregate was called with fallback=True although every judge answered: {observed}. "
        "The re-request succeeded, so the panel is whole"
    )


# --- TC-PIPE-06 ----------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_pipe_06_a_complete_run_synthesizes_and_grades_every_submission(make_pipe_world):
    """`TC-PIPE-06` (a) — all submissions complete: a narrative and a grade for each.

    `FR-PIPE-06` orders these: synthesize every fully-scored submission, then `compute_all`.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world()
    expected = set(world.admitted_ids())

    result = run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    assert result.status == "complete", f"precondition: the run ended {result.status!r}"
    assert _narratives(world) >= expected, (
        f"submissions with no narrative: {sorted(expected - _narratives(world))}"
    )
    assert set(_grades(world)) >= expected, (
        f"submissions with no grade: {sorted(expected - set(_grades(world)))}"
    )
    assert result.grades_computed == len(expected), (
        f"the trace reports {result.grades_computed} grades for {len(expected)} submissions"
    )


@pytest.mark.writtenahead
def test_tc_pipe_06_an_unscored_criterion_means_no_narrative_and_an_incomplete_grade(
    make_pipe_world
):
    """`TC-PIPE-06` (b) and `TC-REQ-96` — a submission with an unscored criterion gets no
    narrative (`CT-SYNTH-05`) and is still graded `incomplete`, and the run does not treat that
    absence as a failure.

    The third clause is the one an implementation gets wrong: pausing a run because a
    submission could not be synthesized turns a quarantined criterion into an outage.
    """
    run_to_completion = require(PIPE_MODULE, "run_to_completion", issue=ISSUE)
    world = make_pipe_world(quarantine_indices=(1,))

    result = run_to_completion(
        world.store, world.run_id, provider=world.provider, run_config=world.resolved,
    )

    grades = _grades(world)
    incomplete = [sid for sid, row in grades.items() if row.get("status") == "incomplete"]
    assert incomplete, (
        "no submission was graded incomplete, so this arm asserted nothing. The specified "
        "world (F-DEV-PIPE) pins an unscored criterion; that corpus does not exist here, so "
        "#364 must confirm how this arm gets its partially-scored submission"
    )
    for sid in incomplete:
        assert sid not in _narratives(world), (
            f"submission {sid} is graded incomplete but carries a narrative; CT-SYNTH-05 does "
            "not synthesize a submission whose criteria are not all scored"
        )
    assert result.status == "complete", (
        f"the run ended {result.status!r} because a submission could not be synthesized. "
        "TC-REQ-96: that absence is tolerated, not a failure"
    )
    synthesize = next((e for e in result.stages if e.stage == "synthesize"), None)
    assert synthesize is not None, "the trace has no synthesize entry"
    rendered = " ".join(str(item) for item in synthesize.detail).lower()
    assert "error" not in rendered and "fail" not in rendered, (
        f"the synthesize detail reports an error for a tolerated absence: "
        f"{synthesize.detail!r} (TC-REQ-96)"
    )
