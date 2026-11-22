"""Validity T8 (issue #901): TC-CONSOLE-104, the validity read
(`GET /api/v1/results/validity`, FR-CONSOLE-80, CT-CONSOLE-55; pairs CT-STATS-27/28/29).

| Arm | World | What is asserted |
|---|---|---|
| a, lifecycle and disagreements | ENG7 through the console | `not_offered_yet` before any read opens the draw, `in_progress` with the draw open (no criteria, no differences), `recorded` after Finish; each difference names the student by roster name (never the ref) with `direction = less_credit` where the system's level is below the teacher's |
| b, the figures | the validity seed, two administrations | per judged criterion: `label`, `scoring_model`, `matched`, `n`, `kappa`, `qwk` only on the four-band line, `min_n_for_headline = 30`; the deterministic line is absent even with a blind label on it; no figure pools the two lines; `prior_record` carries the first class, and its values never stand under `criteria` |
| c, `too_few` at 29 / 30 | the validity seed, plus labels | the atomic line at n = 29 is `too_few`, the holistic line at n = 30 is not |

`skipped` (the plan's "on a second run") is asserted in TC-CONSOLE-105, where the console's
Skip produces it.

**Disclosed.** A draw holds at most 25 seats (FR-REVIEW-12), so arm (c)'s 29 and 30 cannot come
from one real draw: the seed's 24 real labels are joined by 17 atomic and 18 holistic labels
inserted in the blind flow's column shape before `promote_administration` (TC-STATS-47's
precedent). Arm (b)'s deterministic label is inserted the same way (TC-STATS-41's). The
validity seed's students carry no roster name, so the full-name arm runs on ENG7.

**Written ahead: no** (S11 #881 merged).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pytest

from tests.support.eng7_console import eng7_console
from tests.support.label_identity_world import ServedRun
from tests.support.validity_seed import (
    ATOMIC,
    DETERMINISTIC,
    HOLISTIC,
    VALIDITY_SYSTEM,
    teacher_bands,
    validity_seed,
)

pytestmark = pytest.mark.integration

VIEW_KEYS = {"label", "scoring_model", "matched", "n", "kappa", "min_n_for_headline", "too_few"}


@contextmanager
def _console(world, administration, monkeypatch, network_guard) -> Iterator[ServedRun]:
    from aeh.console import serve_console

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    network_guard.uninstall()
    server = serve_console(store=world.store)
    try:
        yield ServedRun(world=administration, server=server,
                        port=server.socket.getsockname()[1], root=world.root)
    finally:
        try:
            server.terminate()
        finally:
            network_guard.install()


def _read(console: ServedRun, run_id: str) -> dict:
    status, read = console.get("/api/v1/results/validity", run_id=run_id)
    assert status == 200, read
    return read


def test_tc_console_104_a_the_lifecycle_and_differences_by_name(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-104 (a): not_offered_yet -> in_progress -> recorded on the console's ENG7 run;
    every seat marked at the top level, so every difference is the system giving less credit,
    named by the student's roster name."""
    with eng7_console(tmp_path / "w", tmp_path / "work", monkeypatch, network_guard) as served:
        before = _read(served, served.run_id)
        assert before["state"] == "not_offered_yet", before
        assert served.service().draw_state(served.run_id) == "not_drawn", (
            "the validity read opened the draw")

        read = served.open_draw()
        during = _read(served, served.run_id)
        assert during["state"] == "in_progress", during
        assert (during["criteria"], during["disagreements"]) == ([], []), during

        seats = served.seat_cells(read)
        cells = served.judged_cells()
        teacher_of: dict[str, str] = {}
        for seat in read["seats"]:
            # The stand-in judge marks C2 at its top band and every other line at its lowest:
            # the teacher answers the opposite end, so differences run both ways.
            system = cells[seats[seat["seat_id"]]]["band"]
            scale = [band["name"] for band in seat["bands"]]
            teacher_of[seat["seat_id"]] = scale[0] if system == scale[-1] else scale[-1]
            served.dispatched("blind-sample draft", run_id=served.run_id,
                              seat_id=seat["seat_id"], band=teacher_of[seat["seat_id"]])
        served.dispatched("blind-sample finish", run_id=served.run_id)
        after = _read(served, served.run_id)
        assert after["state"] == "recorded", after

        names = served.names()
        refs = {row["submission_id"]: row["student_ref"]
                for row in served.rows("SELECT submission_id, student_ref FROM submission")}
        expected = {}
        for seat in read["seats"]:
            sub, crit = seats[seat["seat_id"]]
            scale = [band["name"] for band in seat["bands"]]
            teacher, system = teacher_of[seat["seat_id"]], cells[(sub, crit)]["band"]
            if system != teacher:
                direction = ("less_credit" if scale.index(system) < scale.index(teacher)
                             else "more_credit")
                expected[(names[sub], crit)] = (teacher, system, direction)
        got = {(item["student"], item["criterion_id"]): (
            item["teacher_band"], item["system_band"], item["direction"])
            for item in after["disagreements"]}
        assert got == expected, f"differences {got} != the marked seats' {expected}"
        assert {d for _t, _s, d in expected.values()} == {"less_credit", "more_credit"}, (
            f"fixture: the differences run one way only: {expected}")
        for item in after["disagreements"]:
            assert item["student"] in names.values() and item["student"] not in refs.values(), (
                f"a difference names {item['student']!r}, not the student's roster name")
        assert after["criteria"] and all(
            view["criterion_id"] in {c for _s, c in seats.values()}
            for view in after["criteria"]), after["criteria"]


def test_tc_console_104_b_per_criterion_figures_and_the_prior_record_apart(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-104 (b). Class A is the validity seed (atomic kappa 0.5, matched 9; holistic
    kappa 5/13, QWK 0.5), with a blind label on the deterministic line, promoted. Class B, the
    same version, marked in full agreement (kappa 1, matched 12 on each line), promoted. B's
    read: its own figures under `criteria`, A's only under `prior_record`."""
    world, first = validity_seed(tmp_path / "w")
    try:
        source = world.labels(first)[0]
        world.insert_label_like(
            source, label_id="label-deterministic", criterion_id=DETERMINISTIC,
            evaluation_mode="deterministic", band="correct", teacher_band="correct",
            system_band="incorrect", saw_system_output=0, label_type="blind")
        assert world.promote(first, "finish").promoted

        second = world.administer("c-second", VALIDITY_SYSTEM)
        seats = world.draw(second, 24)
        world.mark(second, seats, teacher_bands(second, VALIDITY_SYSTEM))
        world.finish(second)
        assert world.promote(second, "finish").promoted

        with _console(world, second, monkeypatch, network_guard) as console:
            read = _read(console, second.run_id)
            first_read = _read(console, first.run_id)
        assert read["state"] == "recorded" and read["min_n_for_headline"] == 30, read
        figures = {view["criterion_id"]: view for view in read["criteria"]}
        assert sorted(figures) == sorted({ATOMIC, HOLISTIC}) and len(read["criteria"]) == 2, (
            f"criteria {sorted(figures)}: the deterministic line has no figure (R53), and "
            "each judged line has exactly one")
        for criterion, view in figures.items():
            assert VIEW_KEYS <= set(view), (criterion, sorted(view))
            assert view["min_n_for_headline"] == 30 and view["too_few"] is True, view
            assert (view["n"], view["matched"]) == (12, 12), view
            assert view["kappa"] == pytest.approx(1.0), view
        assert (figures[ATOMIC]["scoring_model"], figures[HOLISTIC]["scoring_model"]) == (
            "atomic", "holistic")
        assert "qwk" not in figures[ATOMIC] and figures[HOLISTIC]["qwk"] == pytest.approx(1.0)
        assert not {"kappa", "qwk", "matched", "n"} & set(read), (
            f"a top-level figure pools the lines: {sorted(read)}")

        first_figures = {view["criterion_id"]: view for view in first_read["criteria"]}
        assert first_figures[ATOMIC]["kappa"] == pytest.approx(0.5)
        assert first_figures[HOLISTIC]["kappa"] == pytest.approx(5 / 13)
        assert DETERMINISTIC not in first_figures, first_figures

        prior = read["prior_record"]
        assert prior is not None and prior["classes"] == [first.cohort_id], prior
        assert {view["criterion_id"]: view["n"] for view in prior["criteria"]} == {
            ATOMIC: 12, HOLISTIC: 12}, prior["criteria"]
        assert all(view["kappa"] != pytest.approx(0.5) and view["matched"] != 9
                   for view in read["criteria"]), "the earlier class's figure stands as current"
        assert first_read["prior_record"] is None, first_read["prior_record"]
    finally:
        world.close()


def test_tc_console_104_c_too_few_is_true_at_29_and_false_at_30(
        tmp_path, monkeypatch, network_guard):
    """TC-CONSOLE-104 (c): the atomic line at n = 29 is `too_few`; the holistic line at n = 30
    is not (pins `n < 30`)."""
    world, administration = validity_seed(tmp_path / "w")
    try:
        labels = world.labels(administration)
        by_criterion = {row["criterion_id"]: row for row in labels}
        extra = []
        for criterion, count in ((ATOMIC, 17), (HOLISTIC, 18)):
            source = by_criterion[criterion]
            extra += [{**source, "label_id": f"label-extra-{criterion}-{i:02d}"}
                      for i in range(count)]
        world.insert_labels_like(labels[0], extra)
        assert world.promote(administration, "finish").promoted

        with _console(world, administration, monkeypatch, network_guard) as console:
            read = _read(console, administration.run_id)
        figures = {view["criterion_id"]: view for view in read["criteria"]}
        assert (figures[ATOMIC]["n"], figures[ATOMIC]["too_few"]) == (29, True), figures[ATOMIC]
        assert (figures[HOLISTIC]["n"], figures[HOLISTIC]["too_few"]) == (30, False), (
            figures[HOLISTIC])
    finally:
        world.close()
