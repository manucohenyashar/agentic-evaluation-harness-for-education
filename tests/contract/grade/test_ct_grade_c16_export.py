"""`TC-GRADE-C16` — the export's revision is real, its directory is a knob, and it never leaves the machine (§6.11.14).

`CT-GRADE-16` (surface): "Assert `export(run_id, revision, fmt)` emits from a
**specified grade revision** — so exporting an older revision yields that
revision's figures, which is the assertion that makes the revision parameter real
rather than decorative. Assert output goes to `GRADE_EXPORT_DIR` on the school's
own filesystem, and the security half: **export never leaves the machine**,
asserted with a socket guard during export."

The limbs, in the row's order:

- **the revision differential** (rung 3, green): one run, one amendment — the
  superseded revision 1 and the amended revision 2 carry different figures, and
  each export call emits the figures of ITS revision: exporting the older one
  yields the older total. A decorative revision parameter would emit the current
  figures for every request; the differential is what makes the parameter real.
- **the directory knob** (rung 3, green): with `GRADE_EXPORT_DIR` set, the export
  lands in it — the design §3.14 configuration name, resolved at call time (the
  env-gated knob seam 3), on the school's own filesystem as a written local path.
- **the egress half** (rung 3, green): the export runs under the socket guard and
  the guard records nothing — the module's export is file bytes on this machine,
  and the assertion is the guard's own record during the export, not a promise in
  a docstring.

Isolation: rung 3 — real store, real service, real written files under the
Windows-safe temp seam (`tmp_path` ⊂ `gettempdir()`). The socket guard is autouse
and taken explicitly for the egress assertion; `criterion_score` rows are the
vocabulary's disclosed `M-AGG` stand-in.
"""

from __future__ import annotations

import csv

import pytest

from aeh.store import open_store
from tests.contract.grade._drive import (
    current_grades,
    grade_revision,
    graded_run,
    set_boundaries,
)
from tests.support.impl import GRADE_MODULE, require

pytestmark = [pytest.mark.contract]

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)

_ROWS = (
    ("S-ONE", "C1", "B2", 7.0, "auto"),
    ("S-ONE", "C2", "B2", 5.0, "auto"),
)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_tc_grade_c16_exporting_an_older_revision_yields_that_revisions_figures(
    tmp_data_dir, monkeypatch
):
    """`TC-GRADE-C16` (`CT-GRADE-16`, rung 3) — the revision differential: after an
    amendment, exporting revision 1 yields revision 1's retained figures and
    exporting revision 2 yields the amended ones. The revision parameter is real,
    not decorative — it selects WHICH figures the page carries."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    monkeypatch.setenv("GRADE_EXPORT_DIR", str(tmp_data_dir.parent / "c16-exports"))
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-ONE",), criteria=_CRITERIA, rows=_ROWS,
            compute=False,
        )
        set_boundaries(store, world.version, (("B", 10.0),))
        world.service.compute_all(world.run_id)
        first_total = float(current_grades(world.cohort, world.run_id)[0]["total"])
        world.service.amend(
            world.run_id, "S-ONE", {"C1": 10.0}, actor="teacher-1", reason="band move",
        )
        second_total = float(current_grades(world.cohort, world.run_id)[0]["total"])
        assert second_total != first_total, (
            "fixture bug: the amendment did not change the total — the "
            "differential would read the same figures twice"
        )

        older = _read_csv(world.service.export(world.run_id, 1, "csv"))
        fresher = _read_csv(world.service.export(world.run_id, 2, "csv"))
        assert len(older) == 1 and older[0]["revision"] == "1", (
            f"the older revision's export carries {older!r} — the page must name "
            "the revision it was emitted from (CT-GRADE-16's revision parameter)"
        )
        assert float(older[0]["total"]) == first_total, (
            f"exporting revision 1 yielded total {older[0]['total']!r}, not the "
            "retained revision's own figures — the revision parameter is real, "
            "not decorative (CT-GRADE-16)"
        )
        assert fresher[0]["revision"] == "2" and float(
            fresher[0]["total"]
        ) == second_total, (
            f"the amended revision's export reads ({fresher[0]['revision']!r}, "
            f"{fresher[0]['total']!r}) — the page carries revision 2's figures "
            "(CT-GRADE-16)"
        )
        # The differential's anchor: the two pages disagree because the ledger's
        # two revisions disagree, each read through its own key.
        assert first_total == float(
            grade_revision(world.cohort, world.run_id, "S-ONE", 1)["total"]
        ), "fixture bug: revision 1's retained row still reads its own total"
    finally:
        store.close()


def test_tc_grade_c16_output_goes_to_the_configured_export_dir(
    tmp_data_dir, monkeypatch
):
    """`TC-GRADE-C16`'s directory limb (rung 3) — with `GRADE_EXPORT_DIR` set, the
    export is written there: the design §3.14 configuration name, resolved at call
    time, on the school's own filesystem as a real local path. A hard-coded or
    ignored directory would put the school's marks somewhere nobody configured."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    school_dir = tmp_data_dir.parent / "school-exports"
    monkeypatch.delenv("HARNESS_GRADE_EXPORT_DIR", raising=False)
    monkeypatch.setenv("GRADE_EXPORT_DIR", str(school_dir))
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-ONE",), criteria=_CRITERIA, rows=_ROWS,
        )
        path = world.service.export(world.run_id, 1, "csv")
        assert school_dir in path.parents or path.parent == school_dir, (
            f"the export landed at {str(path)!r}, outside the configured "
            f"{str(school_dir)!r} — output goes to GRADE_EXPORT_DIR "
            "(CT-GRADE-16's directory limb)"
        )
        assert path.exists() and path.stat().st_size > 0, (
            "the export wrote no readable file — an artifact assertion on the "
            "written path, not a returned promise (CT-GRADE-16)"
        )
    finally:
        store.close()


def test_tc_grade_c16_an_export_never_leaves_the_machine(
    tmp_data_dir, network_guard
):
    """`TC-GRADE-C16`'s security half (rung 3) — the export runs entirely under the
    socket guard and the guard records nothing: no connection is attempted, no
    transport is opened, the figures become file bytes on the local disk alone.
    The guard is the same one every non-live test runs under; this case asserts
    the export specifically never trips it."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store, submissions=("S-ONE",), criteria=_CRITERIA, rows=_ROWS,
        )
        path = world.service.export(world.run_id, 1, "csv")
        assert path.exists(), (
            "the export did not complete — the egress assertion below only means "
            "something over an export that actually ran (CT-GRADE-16)"
        )
        network_guard.assert_no_network()
        # The assertion above raises if any connection was attempted during the
        # export; its message names the clause: export never leaves the machine
        # (CT-GRADE-16's security half).
    finally:
        store.close()
