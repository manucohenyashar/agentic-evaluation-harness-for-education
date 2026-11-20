"""`TC-REVIEW-100` and `TC-REVIEW-107` (a) (issue #897, Validity T4): label identity and the
actor, with the blind sample drafted and finished through the console's own actions.

**Written ahead, keyed on S12 (#882).** The plan keys both cases on the last story they need
(§6: "TC-REVIEW-100, TC-REVIEW-107 | S6 and S12 | S12's console action"). S6 (#867) has
landed. S12 has not: it adds the `blind-sample draft` (seat, band) and `blind-sample finish`
(run) actions, and the seat allowlist (with `seat_id`) on `GET /api/v1/blind-seats`
(FR-CONSOLE-83). Until it lands, these cases fail at the first missing piece, with a message
naming #882. The registry entry is a `command` probe on `CONTROL_SURFACE_ACTIONS`, because S12
adds action strings, not a symbol a `symbol` key could see. When it resolves, remove the
`writtenahead` marker, keep the tests, and drop the entry.

**The oracle already runs green.** `tests/support/label_identity_world.assert_label_identity`
is the TC-REVIEW-100 row oracle. TC-REG-24
(`test_tc_review_101_102_106_107_reg_24_labels.py`) runs it today over the same world, with
Finish through the console's own review service. So the oracle has been mutation-checked
before this drive can reach it. Only the drive differs here: every write is an HTTP request.

**The request shapes** follow FR-CONSOLE-83's parameter names: `blind-sample draft` takes
`run_id`, `seat_id` and `band`, and `blind-sample finish` takes `run_id`. If S12 settles other
names, re-base the two calls in `_finish_three_seats` and nothing else.

Isolation: rung 3, a real store behind `serve_console()`, every label written over HTTP.
"""

from __future__ import annotations

import pytest

from harness.corpora import dev_pipe
from tests.support.label_identity_world import (
    assert_agreement_scope_is_accepted,
    assert_label_identity,
    served_run,
)

pytestmark = pytest.mark.integration

BLOCKER = "#882 (Validity S12: the console's blind-sample draft and finish actions)"


def _finish_three_seats(served) -> None:
    """Read the seats, draft the three seats with a spread of bands, and Finish, all over
    HTTP.

    Re-based at S12 (#882): since #928 (FR-AGG-22, holistic 0.95) the F-DEV-PIPE world routes every C1 cell `auto`, so C1 is never flagged and never drawn; the three queued C2 cells are the whole draw. The reviewed cells that follow are the same three C2 cells, after
    Finish; the counts (three blind, three operational labels) are unchanged."""
    status, read = served.get("/api/v1/blind-seats", run_id=served.run_id)
    assert status == 200, f"the blind-seats read answered {status}: {read!r}"
    seats = [seat for seat in read["seats"] if seat.get("criterion_id") == "C2"]
    assert len(seats) == 3, f"fixture: the draw holds C2 seats {seats}"
    assert all("seat_id" in seat for seat in seats), (
        f"the console's seats carry no seat_id, so a draft cannot name its seat; blocked on "
        f"{BLOCKER}: {sorted(seats[0])}")
    for seat, ordinal in zip(seats, (1, 3, 5)):
        status, outcome = served.action("blind-sample draft", run_id=served.run_id,
                                        seat_id=seat["seat_id"],
                                        band=dev_pipe.band_at("C2", ordinal))
        assert status == 200 and outcome.get("dispatched"), (
            f"blind-sample draft was not dispatched ({status} {outcome!r}); blocked on {BLOCKER}")
    labels_before = [label for label in served.labels() if label["label_type"] == "blind"]
    assert not labels_before, "a draft wrote a blind label before Finish (FR-REVIEW-26)"
    status, outcome = served.action("blind-sample finish", run_id=served.run_id)
    assert status == 200 and outcome.get("dispatched"), (
        f"blind-sample finish was not dispatched ({status} {outcome!r}); blocked on {BLOCKER}")


def _review_three_c2_cells(served) -> None:
    c2 = served.cells("C2")
    assert len(c2) == 3, f"fixture: queued C2 cells {c2}"
    for (submission_id, criterion_id), decision, ordinal in zip(
            c2, ("accept", "edit", "override"), (None, 2, 4)):
        params = {"run_id": served.run_id, "submission_id": submission_id,
                  "criterion_id": criterion_id, "decision": decision}
        if ordinal is not None:
            stored = served.rows(
                "SELECT band FROM criterion_score WHERE run_id = ? AND submission_id = ? AND "
                "criterion_id = ?", served.run_id, submission_id, criterion_id)[0]["band"]
            band = dev_pipe.band_at(criterion_id, ordinal)
            params["new_band"] = band if band != stored else dev_pipe.band_at(
                criterion_id, ordinal - 1)
        served.dispatched("review action", **params)


def test_tc_review_100_every_console_label_carries_its_real_identity(
        tmp_path, monkeypatch, network_guard):
    """TC-REVIEW-100 (FR-REVIEW-25, CT-REVIEW-26; RSV-06). The run is complete. Then
    `blind-sample draft` x3 and `blind-sample finish`, then one accept, one edit and one
    override, all through the console API. For every label row:
    - `run_id` is the run's id and differs from the cohort id;
    - `student_ref` is the roster ref and differs from the submission id;
    - `cohort_id`, `score_id`, `package_version_id`, `backend_profile` and `panel_config` are
      non-null and equal the run's frozen values;
    - `origin` is one of {base, escalation, random_arm}, the one its cell's units derive.
    `agreement()` over the blind labels is a figure the console's scope rule accepts.

    Mutation: see TC-REG-24. The same oracle goes red with `_attribution_run` returning the
    cohort id, or with `_persist_label` writing the submission id as the student."""
    with served_run(tmp_path / "w", monkeypatch, network_guard) as served:
        _finish_three_seats(served)
        _review_three_c2_cells(served)
        labels = served.labels()
        blind = [label for label in labels if label["label_type"] == "blind"]
        assert len(blind) == 3 and len(labels) == 6, (
            f"expected 3 blind labels and 3 operational ones, got "
            f"{[(label['label_type'], label['review_queue_action']) for label in labels]}")
        assert_label_identity(served, labels)
        assert_agreement_scope_is_accepted(served, "C2", blind_count=3)


def test_tc_review_107_a_the_consoles_blind_finish_writes_the_teachers_labels(
        tmp_path, monkeypatch, network_guard):
    """TC-REVIEW-107 (a) (FR-REVIEW-28). A label written by the console's `blind-sample
    finish` has actor `teacher`, and so does each label the console's review action writes.
    The operator arm (CLI, live check) has no label-writing path in `src/` today. It is
    reported in the PR as not implementable as specified."""
    with served_run(tmp_path / "w", monkeypatch, network_guard) as served:
        _finish_three_seats(served)
        _review_three_c2_cells(served)
        actors = {(label["label_type"], label["actor"]) for label in served.labels()}
    assert {actor for _type, actor in actors} == {"teacher"}, (
        f"labels the console wrote carry actors {sorted(actors)}; FR-REVIEW-28 makes a label "
        "written through the console's blind finish the teacher's")
    assert ("blind", "teacher") in actors, sorted(actors)
