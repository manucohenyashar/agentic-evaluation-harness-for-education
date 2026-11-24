"""Validity T14 (issue #911): TC-CONSOLE-113 (FR-CONSOLE-88, NFR-STATS-06) — System status, the
graders. Statistical-validity test plan §3.11.

`GET /api/v1/system-status` on a real console (rung 3) over a store holding one promoted
administration, read under the shipped minimums (60 per engine partition, 20 per gate bin —
no knob lowered):

| Line | Partition | Labels | Expected |
|---|---|---|---|
| atomic (`C-10`) | decision | 60 (cells 0, 1, 5: 19 + 20 + 21) | `measured`, an alpha |
| atomic | llm_engine_off | 60 (cells 2..4, 6..11, cell 2 repeated) | `measured`, an alpha |
| holistic (`C-11`) | decision | 59 (cell 0 repeated) | `insufficient_data`, no alpha |
| holistic | llm_engine_off | 60 (cells 1..11, cell 1 repeated) | `measured` |

The atomic decision cells' accepted gate confidences are 0.82, 0.87 and 0.97, so the gate's
bins (from the 0.80 threshold, 0.05 wide) hold 19, 20, 0 and 21 labels: 19 is
`insufficient_data` with no figure, 20 and 21 are measured with their exact agreement (cells 0 and
1 agree with the teacher, cell 5 does not: 1.0, 1.0 and 0.0).

Non-inferiority: the atomic line has both partitions measured, so its stored verdict is shown —
`false` here, the decision cells holding the line's one disagreement 21 times over — and the
line is named in `noninferiority_failing`; the holistic line is `insufficient_data` (its
decision partition is withheld at 59). Jev-final follows `HARNESS_JEV_FINAL_ON_ACCEPT` (two
consoles, `false` and unset), and the consistency report is the newest of two reference-set
records.

**The seed.** The validity seed (`tests/support/validity_seed.py`): 12 papers, both open lines
drawn whole, marked, Finish, then M-PIPE's `promote_administration` — the real promote computes
and stores every figure the read serves. The counts beyond the 24 real labels are copies of a
real label row (`insert_labels_like`, TC-CONSOLE-104 (c)'s precedent): a copy keeps its paper and
line, so it falls in that cell's engine partition and gate bin. Which engine scored a cell is
M-JUDGE's decision verdict, written through `insert_verdict` as TC-UI-44 does (the disclosed
stand-in for the engine's write), with the accepted pre-screen row the gate's confidence is read
from. The two consistency reports are written through M-PKG's `record_graders_event`, the
writer M-CALIB's re-grade uses.

**Written ahead: no** (#889 merged).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from tests.support.label_identity_world import ServedRun
from tests.support.validity_seed import (
    ATOMIC,
    BANDS,
    HOLISTIC,
    validity_seed,
)

pytestmark = pytest.mark.integration

#: (paper index, line) -> the accepted gate confidence of the engine's answer.
DECISION_CELLS: dict[tuple[int, str], float | None] = {
    (0, ATOMIC): 0.82, (1, ATOMIC): 0.87, (5, ATOMIC): 0.97, (0, HOLISTIC): None,
}
#: (paper index, line) -> how many labels the cell holds in total (1 real + copies).
LABELS_PER_CELL: dict[tuple[int, str], int] = {
    (0, ATOMIC): 19, (1, ATOMIC): 20, (5, ATOMIC): 21,
    (2, ATOMIC): 52,          # with atomic cells 3, 4, 6..11 (8 more): 60 judge-only
    (0, HOLISTIC): 59,        # the holistic decision partition, one short
    (1, HOLISTIC): 50,        # with holistic cells 2..11 (10 more): 60 judge-only
}


def _decision_cells(world: Any, administration: Any) -> None:
    """The engine's answer on each decision cell: an M-JUDGE decision verdict (the cell's system
    band) and, where a gate confidence is named, the accepted pre-screen row."""
    from aeh.judge.schema import JUDGE_STATEMENTS

    handle = world.store.cohort(administration.cohort_id)
    with handle.transaction() as tx:
        for (index, criterion), confidence in DECISION_CELLS.items():
            submission = administration.submission(index)
            work_id = tx.execute(
                "SELECT work_id FROM work_unit WHERE run_id = :r AND submission_id = :s "
                "AND criterion_id = :c AND stage = 'score'",
                r=administration.run_id, s=submission, c=criterion)[0]["work_id"]
            band = administration.system[(submission, criterion)]
            tx.execute(JUDGE_STATEMENTS["insert_verdict"], verdict_id=f"jev-{work_id}",
                       work_id=work_id, judge_id="jev", band=band,
                       band_ordinal=BANDS[criterion].index(band), self_confidence=0.95,
                       cited_spans="[]", evidence_sufficient=1, uncited=0,
                       evidence_assessment="", latency_ms=1, scoring_engine="decision",
                       engine_build="jev@seed", reanchored=0)
            if confidence is not None:
                tx.execute(
                    "INSERT INTO decision_prescreen (work_id, run_id, submission_id, "
                    "criterion_id, engine_build, outcome, band_confidence, threshold, "
                    "argmax_band) VALUES (:w, :r, :s, :c, 'jev@seed', 'accepted', :conf, "
                    "0.80, :band)",
                    w=work_id, r=administration.run_id, s=submission, c=criterion,
                    conf=confidence, band=band)


def _copies(world: Any, administration: Any) -> None:
    labels = world.labels(administration)
    refs = {row["submission_id"]: row["student_ref"] for row in world.store.cohort(
        administration.cohort_id).query("SELECT submission_id, student_ref FROM submission")}
    by_cell = {(row["student_ref"], row["criterion_id"]): row for row in labels}
    rows = []
    for (index, criterion), total in LABELS_PER_CELL.items():
        source = by_cell[(refs[administration.submission(index)], criterion)]
        rows += [{**source, "label_id": f"copy-{index}-{criterion}-{k:02d}"}
                 for k in range(total - 1)]
    world.insert_labels_like(labels[0], rows)


@contextmanager
def _console(world: Any, administration: Any, monkeypatch: Any,
             network_guard: Any) -> Iterator[ServedRun]:
    from aeh.console import serve_console

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    network_guard.uninstall()
    try:
        server = serve_console(store=world.store, run_id=administration.run_id)
        try:
            yield ServedRun(world=administration, server=server,
                            port=server.socket.getsockname()[1], root=world.root)
        finally:
            server.terminate()
    finally:
        network_guard.install()


def _graders(console: ServedRun, run_id: str) -> dict:
    status, read = console.get("/api/v1/system-status", run_id=run_id)
    assert status == 200, (status, read)
    return read["graders"]


def test_tc_console_113_system_status_serves_the_graders_with_their_minimums(
        tmp_path, monkeypatch, network_guard):
    from aeh import pkg

    for name in ("HARNESS_STATS_ENGINE_MIN_LABELS", "HARNESS_STATS_CALIBRATION_MIN_LABELS",
                 "HARNESS_JEV_FINAL_ON_ACCEPT"):
        monkeypatch.delenv(name, raising=False)
    world, administration = validity_seed(tmp_path / "w")
    try:
        _decision_cells(world, administration)
        _copies(world, administration)
        assert world.promote(administration, "finish").promoted
        version = administration.package_version_id
        for when, moved in (("2026-11-01T09:00:00+00:00", 3), ("2026-11-02T09:00:00+00:00", 1)):
            pkg.record_graders_event(
                world.root, package_version_id=version, kind="reference_set",
                trigger="model_build", configuration={"model_build": when}, outcome="ran",
                detail={"criteria": {ATOMIC: {"moved": moved, "examples": 4}}},
                recorded_at=when)

        with _console(world, administration, monkeypatch, network_guard) as console:
            graders = _graders(console, administration.run_id)
        monkeypatch.setenv("HARNESS_JEV_FINAL_ON_ACCEPT", "false")
        with _console(world, administration, monkeypatch, network_guard) as console:
            off = _graders(console, administration.run_id)
    finally:
        try:
            world.close()
        except Exception as error:  # noqa: BLE001 - teardown after the assertions
            if "same thread" not in str(error):
                raise

    # The shipped minimums, unlowered.
    assert (graders["min_per_engine"], graders["min_per_bin"]) == (60, 20), graders
    assert graders["package_version_id"] == version
    by_line = {item["criterion_id"]: item for item in graders["criteria"]}
    assert set(by_line) == {ATOMIC, HOLISTIC}, sorted(by_line)

    atomic, holistic = by_line[ATOMIC]["per_engine"], by_line[HOLISTIC]["per_engine"]
    # 60 per partition: present.
    for name, view in (("atomic decision", atomic["decision"]),
                       ("atomic judge-only", atomic["llm_engine_off"]),
                       ("holistic judge-only", holistic["llm_engine_off"])):
        assert view["n"] == 60 and view["status"] == "measured", (name, view)
        assert isinstance(view["ordinal_alpha"], float), (name, view)
    # 59: withheld, no number.
    assert holistic["decision"] == {"n": 59, "ordinal_alpha": None,
                                    "status": "insufficient_data"}, holistic["decision"]

    bins = [(item["n"], item["status"], item["exact_agreement"])
            for item in by_line[ATOMIC]["gate_bins"]]
    assert bins == [(19, "insufficient_data", None), (20, "measured", 1.0),
                    (0, "insufficient_data", None), (21, "measured", 0.0)], bins
    assert all(item["status"] == "insufficient_data" and item["exact_agreement"] is None
               for item in by_line[HOLISTIC]["gate_bins"]), by_line[HOLISTIC]["gate_bins"]

    # Non-inferiority: the measured line's verdict, shown and named; the withheld one is not.
    assert by_line[ATOMIC]["noninferiority"] == "false", by_line[ATOMIC]
    assert by_line[HOLISTIC]["noninferiority"] == "insufficient_data", by_line[HOLISTIC]
    assert graders["noninferiority"] == "false"
    assert graders["noninferiority_failing"] == [by_line[ATOMIC]["label"]], graders
    assert graders["decision_answers"] == 60

    # Jev-final follows HARNESS_JEV_FINAL_ON_ACCEPT.
    assert graders["jev_final_on"] is True and off["jev_final_on"] is False

    # The latest consistency report (FR-CALIB-19).
    report = graders["consistency_report"]
    assert report is not None, "System status carries no consistency report"
    assert report["recorded_at"] == "2026-11-02T09:00:00+00:00", report
    assert report["criteria"] == {ATOMIC: {"moved": 1, "examples": 4}}, report
    assert report["label"] == "Consistency check"
    assert "accuracy" not in json.dumps(report).lower(), report
