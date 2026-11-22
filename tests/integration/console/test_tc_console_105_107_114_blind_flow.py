"""Validity T8 (issue #901): the blind sample as the console offers and runs it.

| Case | What is asserted |
|---|---|
| TC-CONSOLE-105 (FR-CONSOLE-81) | `blind-sample skip` answers the delta's sentence verbatim; `promote_administration` ran once, `skip`; the record says `skipped`; a draw is refused afterwards |
| TC-CONSOLE-106 (FR-CONSOLE-82, R60) | the run-start outcome carries the delta's sentence with n = the draw's size and m = the reserve the review queue reports; the completion outcome's `next` is the sample, then the results; with the draw open the CSV and XLSX exports answer every student's mark |
| TC-CONSOLE-107 (FR-CONSOLE-83, CT-REVIEW-09) | `GET /api/v1/blind-seats` seat keys are TC-REVIEW-106's allowlist, beside `progress {marked, total}`; `draft` moves `progress.marked`; `finish` closes the draw; `blind-sample submission` is unknown, refused, and writes nothing |
| TC-CONSOLE-114 (FR-CONSOLE-89, SV-15) | Finish with 12 of 15 seats marked: `rows_written == 12` == the blind label rows in the store |

**World.** The ENG7 class graded by the console's own `start run` (`tests/support/eng7_console.py`),
rung 3 over HTTP. Which 15 of the 16 cells are drawn is random per run; every test reads the draw.

**Written ahead: no**, although the issue says yes: S11 (#881), S12 (#882) and S13 (#883) had
merged before these were written, so every case here runs green.

**Disclosed.** TC-CONSOLE-106's m is compared with the queue read's `reserved_for_blind_minutes`
under the default settings. The run-start sentence reads the console's own knob
(`HARNESS_CONSOLE_BLIND_RESERVE_MINUTES`) while the queue reads M-REVIEW's
`REVIEW_BLIND_RESERVE_MINUTES`, so the two can disagree once the console knob is set (reported
in the PR, not asserted).
"""

from __future__ import annotations

import io
import zipfile

import pytest

from tests.integration.review.test_tc_review_101_102_106_107_reg_24_labels import _SEAT_KEYS
from tests.support.eng7_console import eng7_console

pytestmark = pytest.mark.integration

#: FR-CONSOLE-81's reply, verbatim from the design delta.
SKIP_SENTENCE = ("Skipped. Every mark stays as it is; the only cost is no new evidence about "
                 "how accurate the marking is.")


def _start_sentence(n: int, m: int) -> str:
    """FR-CONSOLE-82's run-start sentence, verbatim from the design delta."""
    return (f"When marking finishes you'll be asked to mark about {n} answers yourself, "
            f"without seeing the system's marks (about {m} minutes). It's optional; your class "
            "is graded either way.")


def _blind_labels(served) -> list[dict]:
    return served.rows("SELECT * FROM label WHERE label_type = 'blind' AND run_id = ?",
                       served.run_id, tier="durable")


def _validation_rows(served) -> list[dict]:
    return served.rows("SELECT * FROM package_validation WHERE cohort_id = ?",
                       served.cohort_id, tier="durable")


def _teacher_band(seat: dict) -> str:
    """A band the teacher gives that is never the system's lowest one."""
    return seat["bands"][-1]["name"]


def test_tc_console_106_blind_first_at_start_and_completion_and_the_export_stays_final(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-106. Start: the outcome ends in the sentence with n = the draw's size and
    m = the reserve the review queue holds back. Completion: `next[0]` is the blind sample and
    `next[1]` the results, `blind_count` the draw's size. With the draw open, the CSV and XLSX
    exports answer 200 with every student's mark, state final (R60)."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        status, monitor = served.get("/api/v1/monitor", run_id=served.run_id)
        assert status == 200, monitor
        assert monitor["blind_sample"] == "open", monitor
        assert [entry["label"] for entry in monitor["next"]] == [
            "Mark the sample", "See the results"], monitor["next"]
        assert monitor["next"][0]["route"] == "/review/blind", monitor["next"]
        assert monitor["next"][1]["route"] == "/results", monitor["next"]

        drawn = served.drawn_cells()
        status, queue = served.get("/api/v1/review-queue", run_id=served.run_id)
        assert status == 200, queue
        reserve = queue["reserved_for_blind_minutes"]
        assert monitor["blind_count"] == len(drawn) and monitor["blind_minutes"] == reserve, (
            monitor, len(drawn), reserve)
        detail = served.start_outcome["detail"]
        assert detail.endswith(_start_sentence(len(drawn), reserve)), (
            f"the run-start outcome {detail!r} does not end with FR-CONSOLE-82's sentence for "
            f"n={len(drawn)}, m={reserve}")

        students = set(served.names())
        status, csv_text = served.get("/api/v1/results/export", run_id=served.run_id,
                                      format="csv")
        assert status == 200, csv_text
        header, *lines = [line.split(",") for line in csv_text.strip().splitlines()]
        rows = [dict(zip(header, line)) for line in lines]
        assert {row["submission_id"] for row in rows} == students, rows
        assert all(row["mark"] not in ("", None) and row["state"] == "final" for row in rows), (
            f"with the draw open the export must carry every final mark (R60): {rows}")

        status, body = served.raw_get(f"/api/v1/results/workbook?run_id={served.run_id}")
        assert status == 200, body[:300]
        from openpyxl import load_workbook

        sheet_text = " ".join(
            str(cell) for sheet in load_workbook(io.BytesIO(body), read_only=True).worksheets
            for row in sheet.iter_rows(values_only=True) for cell in row if cell is not None)
        names = served.names()
        assert all(names[sub] in sheet_text for sub in students), (
            "the workbook export, with the draw open, does not list every student (R60)")
        assert zipfile.is_zipfile(io.BytesIO(body))


def test_tc_console_107_the_seats_read_draft_finish_and_no_per_choice_submit(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-107. Each seat's keys are exactly TC-REVIEW-106's allowlist; the read carries
    `progress {marked, total}`. A draft moves `marked` by one; Finish closes the draw. The old
    `blind-sample submission` is unknown: not dispatched and no label written."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        read = served.open_draw()
        assert {"seats", "progress", "state"} <= set(read), sorted(read)
        for number, seat in enumerate(read["seats"], 1):
            assert set(seat) == _SEAT_KEYS, (
                f"seat {number} keys differ from the allowlist by "
                f"{sorted(set(seat) ^ _SEAT_KEYS)}")
        total = len(read["seats"])
        assert read["progress"] == {"marked": 0, "total": total}, read["progress"]

        status, refused = served.action("blind-sample submission", run_id=served.run_id,
                                        seat_id=read["seats"][0]["seat_id"],
                                        band=_teacher_band(read["seats"][0]))
        assert not (status == 200 and isinstance(refused, dict) and refused.get("dispatched")), (
            f"the per-choice submit is still served: {status} {refused!r}")
        assert status in (400, 404, 405), (status, refused)

        first = read["seats"][0]
        served.dispatched("blind-sample draft", run_id=served.run_id, seat_id=first["seat_id"],
                          band=_teacher_band(first))
        status, after = served.get("/api/v1/blind-seats", run_id=served.run_id)
        assert status == 200 and after["progress"] == {"marked": 1, "total": total}, after
        assert _blind_labels(served) == [], "a draft or the refused submit wrote a label"

        served.dispatched("blind-sample finish", run_id=served.run_id)
        status, closed = served.get("/api/v1/blind-seats", run_id=served.run_id)
        assert status == 200 and closed["state"] != "open", closed
        assert served.service().draw_state(served.run_id) not in ("open", "not_drawn")
        assert len(_blind_labels(served)) == 1


def test_tc_console_114_finish_with_twelve_marked_reports_twelve_rows(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-114. Twelve of the fifteen seats drafted, then Finish: the outcome's
    `rows_written` is 12, and 12 blind label rows are in the store for the run."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        read = served.open_draw()
        assert len(read["seats"]) == 15, f"fixture: the draw holds {len(read['seats'])} seats"
        for seat in read["seats"][:12]:
            served.dispatched("blind-sample draft", run_id=served.run_id,
                              seat_id=seat["seat_id"], band=_teacher_band(seat))
        outcome = served.dispatched("blind-sample finish", run_id=served.run_id)
        stored = _blind_labels(served)
        assert outcome["rows_written"] == 12 == len(stored), (
            f"rows_written {outcome['rows_written']}, label rows {len(stored)}; both must be 12")


def test_tc_console_105_skip_answers_the_sentence_promotes_once_and_refuses_a_draw(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-105 (the skip; the repeated-skip alert arm is its own written-ahead file,
    `test_tc_console_105_b_repeated_skip_alert.py`). `blind-sample skip` with the draw open
    answers the delta's sentence exactly; `promote_administration` was called once, with
    `skip`; the stored record's absence reason is `skipped`; the validity read says `skipped`;
    a new draw is refused."""
    import aeh.pipeline

    calls: list[tuple[str, str]] = []
    real = aeh.pipeline.promote_administration

    def counting(store, run_id, trigger, **kwargs):
        calls.append((run_id, trigger))
        return real(store, run_id, trigger, **kwargs)

    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        read = served.open_draw()
        served.dispatched("blind-sample draft", run_id=served.run_id,
                          seat_id=read["seats"][0]["seat_id"],
                          band=_teacher_band(read["seats"][0]))
        monkeypatch.setattr(aeh.pipeline, "promote_administration", counting)
        outcome = served.dispatched("blind-sample skip", run_id=served.run_id)
        assert outcome["detail"] == SKIP_SENTENCE, outcome["detail"]
        assert calls == [(served.run_id, "skip")], calls

        (record,) = _validation_rows(served)
        assert record["absence_reason"] == "skipped" and record["blind_count"] == 0, record
        assert _blind_labels(served) == [], "a skip turned the draft into a label"
        status, validity = served.get("/api/v1/results/validity", run_id=served.run_id)
        assert status == 200 and validity["state"] == "skipped", validity

        from aeh.review import ReviewError

        with pytest.raises(ReviewError, match="skipped"):
            served.service().blind_sample(served.run_id)
        status, seats = served.get("/api/v1/blind-seats", run_id=served.run_id)
        assert not (status == 200 and seats.get("state") == "open"), seats
