"""Validity T5 (issue #898): the draw closes only by Finish, Skip or window lapse, and promotion
fires exactly once, on close. These cases run over a completed F-DEV-PIPE run behind a real
console; every Finish, Skip, draft and "Approve all grades" is an HTTP request.

| Case | What it pins | Rung |
|---|---|---|
| TC-REVIEW-104 (non-transitions) | `finalize_batch`, the console's "Approve all grades" (`finalize batch`), run completion and the recovery sweep leave an open draw `open` | 3, HTTP |
| TC-PIPE-40 | a spy on `ValidationStats.promote`: 0 on completion, finalization, "Approve all", recovery and an M-PIPE call while open; 1 on Finish; 1 on Skip; 0 more on a second close; a never-closed draw writes no `package_validation` row | 3, HTTP |
| TC-PIPE-41 | the run trace's `validity` stage: `not_offered_yet`, `in_progress`, then claimed labels, per-criterion figures and reasoned absences after Finish; `skipped` after Skip; the stage follows grading in trace order | 3 |

The window-lapse row of TC-PIPE-40 needs the injected clock, so it runs in
`tests/integration/review/test_tc_review_103_105_drafts_and_window.py` (TC-REVIEW-105), which
asserts the same spy count through the console's own settle path.

**The world.** Since #928 (FR-AGG-22, holistic 0.95) the F-DEV-PIPE world routes every C1 cell
`auto`, so C1 is never drawn; the three queued C2 cells are the whole draw (the re-base #934
made).

**Disclosed departures (in the PR as well).**

1. *The plan's mutation does not bite, by design.* The plan's TC-PIPE-40 mutation is "call
   `promote_administration` from finalization". `promote_administration` reads the draw state
   itself and promotes nothing for an open or undrawn draw (#879), so that mutation alone stays
   green: the behaviour it would break is structurally prevented. The biting mutation is
   "drop the closed-draw guard" in `promote_administration`. Its production witnesses are the
   recovery sweep (`aeh.pipeline.recover`, which calls `promote_administration` for every
   complete run) and the direct M-PIPE call while open, both rows of the spy table here. The
   plan's mutation together with the guard dropped turns the finalization row red too.
2. *Run completion.* The plan names finalization at `console/driver.py:212`. The run here
   completes through M-PIPE's `run_to_completion` (the shipped composed driver), with the spy
   installed before the drive. The open-draw arm re-drives the completed run, which runs the
   finishing step (grading, then the validity stage) again with the draw open.
"""

from __future__ import annotations

from typing import Any

import pytest

from harness.corpora import dev_pipe
from tests.support import pipe_world
from tests.support.label_identity_world import served_run

pytestmark = pytest.mark.integration

#: FR-PIPE-20's closed set of reasons an absent figure may carry.
ABSENT_REASONS = {"skipped", "none_marked", "too_few_labels", "insufficient_data"}


class PromoteSpy:
    """Counts `ValidationStats.promote` calls, delegating to the real method."""

    def __init__(self, monkeypatch: Any) -> None:
        from aeh.stats.service import ValidationStats

        self.calls: list[dict] = []
        real = ValidationStats.promote

        def counting(stats, *args, **kwargs):
            self.calls.append({"args": args, **kwargs})
            return real(stats, *args, **kwargs)

        monkeypatch.setattr(ValidationStats, "promote", counting)

    @property
    def count(self) -> int:
        return len(self.calls)


def _state(served) -> str:
    """The draw state, read through M-REVIEW's `draw_state(run_id)` on the console's service."""
    return served.server.app._review_service(served.run_id).draw_state(served.run_id)


def _open_the_draw(served) -> list[str]:
    """Open the draw the way the console does (the blind-seats read draws once) and return
    the seat ids."""
    status, read = served.get("/api/v1/blind-seats", run_id=served.run_id)
    assert status == 200, f"the blind-seats read answered {status}: {read!r}"
    assert read["state"] == "open", read
    seats = [seat["seat_id"] for seat in read["seats"]]
    assert len(seats) == 3, f"fixture: the F-DEV-PIPE draw holds three C2 seats, got {read}"
    return seats


def _draft(served, seat_ids: list[str]) -> None:
    for seat_id, ordinal in zip(seat_ids, (1, 3, 5)):
        served.dispatched("blind-sample draft", run_id=served.run_id, seat_id=seat_id,
                          band=dev_pipe.band_at("C2", ordinal))


def _validation_rows(served) -> int:
    """The administration's durable `package_validation` rows (the record promote writes)."""
    rows = served.rows("SELECT COUNT(*) AS n FROM package_validation WHERE cohort_id = ? "
                       "AND package_version_id = ?", served.cohort_id,
                       served.run_row()["package_version_id"], tier="durable")
    return int(rows[0]["n"])


def _finalize_directly(served) -> None:
    from aeh.grade import GradingService

    GradingService(served.world.store).finalize_batch(served.run_id, "tc-pipe-40")


def _approve_all_grades(served) -> None:
    """The console's "Approve all grades" button posts `finalize batch` (ui Results.tsx)."""
    status, outcome = served.action("finalize batch", run_id=served.run_id, actor="operator")
    assert status == 200 and isinstance(outcome, dict), (status, outcome)


def _recover(served) -> Any:
    from aeh.pipeline import recover

    return recover(served.world.store)


def _redrive(served) -> Any:
    """Run completion again on the completed run: `run_to_completion`'s finishing step."""
    result = pipe_world.drive_composed(served.world)
    assert result.status == "complete", result.status
    return result


# --- TC-REVIEW-104: the non-transitions ---------------------------------------------------------


def test_tc_review_104_c_finalization_approve_all_and_completion_leave_the_draw_open(
        tmp_path, monkeypatch, network_guard):
    """TC-REVIEW-104 (FR-REVIEW-30, CT-REVIEW-27): non-transitions. With the draw open,
    `finalize_batch(run_id)`, the console's "Approve all grades", run completion and the
    recovery sweep each leave `draw_state(run_id) == 'open'`, and the drafts stay drafts (no
    blind label). The legal and illegal transitions are
    `test_tc_review_104_a/b` in the review file, over the injected-clock world."""
    with served_run(tmp_path / "w", monkeypatch, network_guard) as served:
        assert _state(served) == "not_drawn", "fixture: the headless run drew a sample"
        seats = _open_the_draw(served)
        _draft(served, seats[:2])
        steps = (("finalize_batch", _finalize_directly),
                 ("Approve all grades", _approve_all_grades),
                 ("run completion", _redrive),
                 ("recover", _recover))
        for name, step in steps:
            step(served)
            assert _state(served) == "open", f"{name} moved the open draw to {_state(served)!r}"
        blind = [label for label in served.labels() if label["label_type"] == "blind"]
        assert not blind, f"a non-transition turned drafts into labels: {blind}"
        status, read = served.get("/api/v1/blind-seats", run_id=served.run_id)
        assert read["progress"] == {"marked": 2, "total": 3}, read


# --- TC-PIPE-40: promotion fires once, on draw close only ---------------------------------------


def test_tc_pipe_40_a_promote_runs_once_on_finish_and_never_while_open(
        tmp_path, monkeypatch, network_guard):
    """TC-PIPE-40 (FR-PIPE-21, CT-PIPE-16): the spy table's Finish arm.

    | Trigger | promote calls |
    |---|---|
    | run completion (the composed drive, spy installed first; and a re-drive while open) | 0 |
    | `finalize_batch` while open | 0 |
    | "Approve all grades" while open | 0 |
    | the recovery sweep while open | 0 |
    | `promote_administration(.., "finish")` while open | 0, promoted=False |
    | a draw not (yet) closed | no `package_validation` row |
    | Finish | 1 |
    | a second Finish, a Skip, a recovery sweep after Finish | 0 more |

    Mutation: drop the closed-draw guard in `promote_administration` -> the recovery and
    direct-call rows go red (1, not 0)."""
    from aeh.pipeline import promote_administration

    spy = PromoteSpy(monkeypatch)
    with served_run(tmp_path / "w", monkeypatch, network_guard) as served:
        assert spy.count == 0, f"run completion promoted ({spy.count} call(s))"
        seats = _open_the_draw(served)
        _draft(served, seats[:2])
        for name, step in (("run completion (re-drive while open)", _redrive),
                           ("finalize_batch while open", _finalize_directly),
                           ("Approve all grades while open", _approve_all_grades),
                           ("recover while open", _recover)):
            step(served)
            assert spy.count == 0, f"{name} called promote {spy.count} time(s)"
        outcome = promote_administration(served.world.store, served.run_id, "finish")
        assert not outcome.promoted and spy.count == 0, (
            f"promote_administration on an open draw promoted: {outcome.reason!r}, "
            f"{spy.count} call(s)")
        assert _validation_rows(served) == 0, "an open draw left a package_validation row"

        served.dispatched("blind-sample finish", run_id=served.run_id)
        assert spy.count == 1, f"Finish called promote {spy.count} time(s), expected 1"
        assert spy.calls[0].get("run_id") == served.run_id, spy.calls[0]
        assert spy.calls[0].get("unmarked_count") == 1, spy.calls[0]
        assert _validation_rows(served) == 1

        status, second = served.action("blind-sample finish", run_id=served.run_id)
        assert status == 200 and not second.get("dispatched"), (
            f"a second Finish was dispatched: {second!r}")
        status, skip = served.action("blind-sample skip", run_id=served.run_id)
        assert not skip.get("dispatched"), f"a Skip after Finish was dispatched: {skip!r}"
        _recover(served)
        assert spy.count == 1, f"a second close called promote again ({spy.count} calls)"
        assert _validation_rows(served) == 1


def test_tc_pipe_40_b_promote_runs_once_on_skip(tmp_path, monkeypatch, network_guard):
    """TC-PIPE-40: the Skip arm. Skip from an open draw with one draft promotes once, with the
    absence `skipped`; a second Skip and a Finish after it promote nothing more."""
    spy = PromoteSpy(monkeypatch)
    with served_run(tmp_path / "w", monkeypatch, network_guard) as served:
        seats = _open_the_draw(served)
        _draft(served, seats[:1])
        assert spy.count == 0
        served.dispatched("blind-sample skip", run_id=served.run_id)
        assert spy.count == 1, f"Skip called promote {spy.count} time(s), expected 1"
        assert spy.calls[0].get("absence_reason") == "skipped", spy.calls[0]
        status, again = served.action("blind-sample skip", run_id=served.run_id)
        status, finish = served.action("blind-sample finish", run_id=served.run_id)
        assert not finish.get("dispatched"), f"Finish after Skip was dispatched: {finish!r}"
        _recover(served)
        assert spy.count == 1, f"a close after Skip called promote again ({spy.count} calls)"
        assert _validation_rows(served) == 1
        blind = [label for label in served.labels() if label["label_type"] == "blind"]
        assert not blind, f"Skip turned its draft into a label: {blind}"


# --- TC-PIPE-41: the validity stage in the trace ------------------------------------------------


def _stage(result: Any) -> Any:
    names = [stage.stage for stage in result.stages]
    assert names.count("validity") == 1, f"the trace has no single validity stage: {names}"
    return result.stages[names.index("validity")]


def _assert_follows_grading(result: Any) -> None:
    names = [stage.stage for stage in result.stages]
    assert "grade" in names, names
    assert names.index("validity") > names.index("grade"), (
        f"the validity stage does not follow finalization in trace order: {names}")


def test_tc_pipe_41_a_validity_stage_through_finish(tmp_path, monkeypatch, network_guard):
    """TC-PIPE-41 (FR-PIPE-20, CT-PIPE-15): before any draw the trace's `validity` stage reads
    `not_offered_yet`; drawn, `in_progress`; after Finish with 2 of 3 seats marked, the labels
    claimed equal the marked count (2), figures are keyed per criterion (C2 among them), and
    every absent figure names a reason from FR-PIPE-20's set. The stage follows grading."""
    from aeh.pipeline import validity_stage

    with served_run(tmp_path / "w", monkeypatch, network_guard) as served:
        before = _redrive(served)
        _assert_follows_grading(before)
        assert _stage(before).metrics["state"] == "not_offered_yet", _stage(before).metrics

        seats = _open_the_draw(served)
        _draft(served, seats[:2])
        drawn = _redrive(served)
        _assert_follows_grading(drawn)
        assert _stage(drawn).metrics["state"] == "in_progress", _stage(drawn).metrics

        served.dispatched("blind-sample finish", run_id=served.run_id)
        after = _redrive(served)
        _assert_follows_grading(after)
        metrics = _stage(after).metrics
        assert metrics == validity_stage(served.world.store, served.run_id).metrics
        assert metrics["state"] == "recorded", metrics
        assert metrics["labels_claimed"] == 2, metrics
        assert metrics["unmarked_count"] == 1, metrics
        assert "C2" in metrics["figures"], metrics["figures"]
        assert all(isinstance(figure, dict) for figure in metrics["figures"].values())
        assert metrics["figures"]["C2"].get("n") == 2, (
            f"C2's figure was not computed over the two claimed labels: {metrics['figures']}")
        assert metrics["absent"], "fixture: no absent figure, so the reason check is vacuous"
        reasons = {item["reason"] for item in metrics["absent"]}
        assert reasons <= ABSENT_REASONS, f"absent figures with reasons outside FR-PIPE-20: {reasons}"
        assert all(item["reason"] for item in metrics["absent"]), metrics["absent"]


def test_tc_pipe_41_b_validity_stage_after_skip(tmp_path, monkeypatch, network_guard):
    """TC-PIPE-41: after Skip the stage reads `skipped`, claims 0 labels, and names the absent
    agreement with the reason `skipped`."""
    with served_run(tmp_path / "w", monkeypatch, network_guard) as served:
        _open_the_draw(served)
        served.dispatched("blind-sample skip", run_id=served.run_id)
        after = _redrive(served)
        _assert_follows_grading(after)
        metrics = _stage(after).metrics
        assert metrics["state"] == "skipped", metrics
        assert metrics["labels_claimed"] == 0, metrics
        assert metrics["absence_reason"] == "skipped", metrics
        assert {"figure": "agreement", "criterion_id": "", "reason": "skipped"} in \
            metrics["absent"], metrics["absent"]
