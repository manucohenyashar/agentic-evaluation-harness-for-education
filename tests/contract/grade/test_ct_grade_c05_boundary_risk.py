"""`TC-GRADE-C05` — the boundary-at-risk flag, and the null discipline that guards it (§6.11.14).

`CT-GRADE-05` (data): "`boundary_at_risk` is set, and `score_low`/`score_high`
populated, when the provisional criteria's full plausible band range could move the
student across a boundary. `grade` is null where the package declares no boundary
table, never invented — and no consumer renders it as a blank that reads as 'fine'."

The limbs, in the plan's order:

- **the discriminating pair** (rung 0 over the pure seam): one grade whose
  provisional interval's range spans a boundary floor (must flag, with the
  interval's endpoints populated) and one whose range does not (must not) — same
  total, different interval, so the flag tracks the movement range and nothing
  else. Floors are INCLUSIVE at both ends (the shipped DDL's resolution rule), and
  the degenerate zero-width range — no provisional criteria, nothing left to move —
  never flags even when the total sits exactly on a floor (#102's pinned limb).
- **the flag at the service level** (rung 3): the pair re-run through the real
  service, where the interval source is the DECLARED band span (`TC-GRADE-06`'s
  injection contract) and the movement offsets cross the same transforms the score
  did. Two submissions carry the same declared span and the same provisional
  figure; only the auto criterion's figure differs — so one total sits in reach of
  the 63.0 floor (flagged, interval populated) and one cannot reach it (settled).
  Both resolve to the same band, proving the flag is independent information, not
  a withheld grade.
- **the null discipline** (rung 3/4): where the package declares no boundary table,
  the resolved grade is null — never an invented band — and the module's own export
  renders that null as an honest absence, not a blank that reads as "fine".
- **the console limb** (`[m_console]`, writtenahead): the clause's consumer
  obligation — no consumer renders the null grade as fine. The landed console
  module renders grades with no boundary-risk language at all, so this waits on
  the disclosed `aeh.console:render_grade_coverage` (#107).

Isolation: rung 0 for the pure seam; rung 3 for the service limbs; rung 4 for the
export. The socket guard is autouse; `criterion_score` rows are the vocabulary's
disclosed `M-AGG` stand-in.
"""

from __future__ import annotations

import csv

import pytest

from aeh.grade import boundary_risk, resolve_grade
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.contract.grade._drive import (
    current_grades,
    graded_run,
    set_boundaries,
)
from tests.support.impl import CONSOLE_MODULE, GRADE_MODULE, require
from tests.support.grade_vocabulary import boundary

pytestmark = [pytest.mark.contract]

#: One floor pair is all the discrimination needs: 63.0 splits the reach of a
#: total sitting just above it, 85.0 sits beyond anything the spans can reach.
_CUTS = (("B", 63.0), ("A", 85.0))

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)


def test_tc_grade_c05_the_pure_seam_flags_exactly_when_the_range_spans_a_floor():
    """`TC-GRADE-C05` (`CT-GRADE-05`, rung 0) — the flag's exact rule over the pure
    seam: flag iff the range has positive width AND a boundary floor lies inside
    `[score_low, score_high]` inclusive; zero width never flags (nothing left to
    move — #102's degenerate limb, `test_issue_102_a_degenerate_range_cannot_cross_
    a_boundary`); a score below every floor resolves to no grade at all, and no
    table answers None — never an invented band."""
    require(GRADE_MODULE, "boundary_risk", issue="#101")
    require(GRADE_MODULE, "resolve_grade", issue="#101")
    cuts = [boundary("B", 63.0), boundary("A", 85.0)]

    # The discriminating pair: same total, intervals that do and do not reach a floor.
    crossing = boundary_risk(64.0, [(-3.5, 0.5)], cuts)
    assert crossing.at_risk and crossing.score_low == 60.5 and crossing.score_high == 64.5, (
        f"the crossing range did not flag ({crossing!r}) — a provisional interval "
        "whose range spans 63.0 must set boundary_at_risk and populate the "
        "interval (CT-GRADE-05)"
    )
    safe = boundary_risk(64.0, [(-0.1, 0.1)], cuts)
    assert not safe.at_risk and safe.score_low is None and safe.score_high is None, (
        f"the non-crossing range flagged ({safe!r}) — a range that cannot reach a "
        "floor must not flag, and the interval stays withheld (CT-GRADE-05: a "
        "range nobody acts on is noise)"
    )
    # Endpoints are inclusive: a range whose BEST case lands exactly on the floor
    # is a crossing — landing exactly on a cut resolves to that cut's band.
    touching = boundary_risk(63.0, [(0.0, 1.0)], cuts)
    assert touching.at_risk and touching.score_low == 63.0, (
        f"a range whose edge lands exactly on the floor did not flag ({touching!r}) "
        "— landing exactly on a cut RESOLVES to that cut's band, so it is a "
        "crossing (the floors are INCLUSIVE; CT-GRADE-05)"
    )
    # The degenerate limb: zero width — nothing left to move — never flags, even
    # with the total sitting exactly on the floor.
    degenerate = boundary_risk(63.0, [], cuts)
    assert not degenerate.at_risk and degenerate.score_low is None, (
        f"the zero-width range flagged ({degenerate!r}) — a total that cannot move "
        "is not at risk (#102's degenerate limb, CT-GRADE-05)"
    )
    # The resolution nulls: no table, or below every floor — None, never invented.
    assert resolve_grade(70.0, None) is None, (
        "a package with no boundary table resolved a grade — an invented band is "
        "the NoValidationData violation (CT-GRADE-05, FR-GRADE-03)"
    )
    assert resolve_grade(10.0, cuts) is None, (
        "a score below every declared floor resolved a grade — the lowest floor is "
        "inclusive, and below it there is no band to invent (CT-GRADE-05)"
    )
    assert resolve_grade(63.0, cuts) == "B", (
        "exactly-on-a-cut resolved to the wrong band — the greatest floor <= the "
        "score resolves, so exactly 63.0 IS a B (CT-GRADE-05's exact-boundary)"
    )


def _declare_band_span(store, version, criterion_id, low, high):
    """Declare a criterion's band range — the shipped `PackageCatalog.add_band`,
    the declaration the surface's `band_spans` reads (`TC-GRADE-06`'s injected
    interval source). Two bands are the minimum that gives the span width."""
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    for ordinal, points in enumerate((low, high)):
        catalog.add_band(version, criterion_id, ordinal, f"SP{ordinal}", points)


def test_tc_grade_c05_the_service_flags_the_total_in_reach_and_not_the_settled_one(
    tmp_data_dir,
):
    """`TC-GRADE-C05` (`CT-GRADE-05`, rung 3) — the pair through the real service,
    where the movement interval is the criterion's DECLARED band span (min..max of
    the declared band points) offset by the row's current points. Both submissions
    carry the SAME declared span and the SAME provisional figure; only the auto
    criterion's figure differs — so one total sits within reach of the 63.0 floor
    (flagged) and one cannot reach it (settled), while both resolve to B: the flag
    rides alongside a delivered grade, it never withholds one."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-CROSS", "S-SAFE"),
            criteria=_CRITERIA,
            rows=[
                ("S-CROSS", "C1", "B2", 60.0, "auto"),
                ("S-CROSS", "C2", "B1", 3.5, "provisional"),
                ("S-SAFE", "C1", "B2", 64.0, "auto"),
                ("S-SAFE", "C2", "B1", 3.5, "provisional"),
            ],
            compute=False,  # the declarations must exist before the one pass
        )
        version = world.version
        set_boundaries(store, version, _CUTS)
        # C2's declared span [0.0, 4.0] against its current 3.5: the movement
        # interval is (-3.5, +0.5) — S-CROSS's total 63.5 can fall to 60.0, across
        # the floor; S-SAFE's 67.5 falls only to 64.0, which still resolves B.
        _declare_band_span(store, version, "C2", 0.0, 4.0)
        world.service.compute_all(world.run_id)

        grades = {
            row["submission_id"]: row
            for row in current_grades(world.cohort, world.run_id)
        }
        assert set(grades) == {"S-CROSS", "S-SAFE"}, (
            "fixture bug: the pair did not both deliver a grade"
        )
        cross, safe = grades["S-CROSS"], grades["S-SAFE"]
        # Fixture sanity gate: the ONLY fixture difference is C1's figure — same
        # declared span, same provisional row — so the differential tracks the
        # total's position against the floors and nothing else.
        assert int(cross["criteria_total"]) == int(safe["criteria_total"]) == 2, (
            "fixture bug: the pair's coverage totals differ"
        )

        assert int(cross["boundary_at_risk"]) == 1, (
            f"S-CROSS's grade is not flagged ({cross['boundary_at_risk']}) — its "
            "provisional criterion's declared band range reaches below the 63.0 "
            "floor, and the total sits within reach (CT-GRADE-05: the flag must "
            "fire on the crossing pair)"
        )
        assert float(cross["score_low"]) == 60.0 and float(cross["score_high"]) == 64.0, (
            f"S-CROSS's interval is ({cross['score_low']!r}, {cross['score_high']!r}) "
            "— the interval must span the provisional criterion's full declared band "
            "range, transformed into the total's space (CT-GRADE-05)"
        )
        assert cross["grade"] == "B" and float(cross["total"]) == 63.5, (
            f"S-CROSS delivered ({cross['total']!r}, {cross['grade']!r}) — the flag "
            "is a proximity warning riding alongside a delivered grade, never a "
            "withheld one"
        )

        assert int(safe["boundary_at_risk"]) == 0, (
            f"S-SAFE's grade is flagged ({safe['boundary_at_risk']}) — its total "
            "67.5 falls at worst to 64.0, still inside the B band: nothing it can "
            "reach crosses a floor (CT-GRADE-05: the flag must NOT fire on the "
            "settled twin)"
        )
        assert safe["score_low"] is None and safe["score_high"] is None, (
            f"S-SAFE's interval is ({safe['score_low']!r}, {safe['score_high']!r}) "
            "— a range nobody acts on is withheld, not populated (CT-GRADE-05)"
        )
        assert safe["grade"] == "B" and float(safe["total"]) == 67.5, (
            "fixture bug: the settled twin should resolve the same B band"
        )
    finally:
        store.close()


def test_tc_grade_c05_a_degenerate_total_on_a_floor_never_flags(tmp_data_dir):
    """`TC-GRADE-C05`'s degenerate limb at the service level (`CT-GRADE-05`, rung 3,
    #102's carry) — a submission whose total sits EXACTLY on a boundary floor with
    no provisional criteria left to move it: the flag stays down, because a range
    of zero width cannot cross anything, and #102's fix pinned that reading."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-SETTLED",),
            criteria=(
                {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
            ),
            rows=[("S-SETTLED", "C1", "B2", 63.0, "auto")],
            compute=False,
        )
        set_boundaries(store, world.version, _CUTS)
        world.service.compute_all(world.run_id)
        (row,) = current_grades(world.cohort, world.run_id)
        assert float(row["total"]) == 63.0 and row["grade"] == "B", (
            f"fixture bug: the settled-on-the-floor grade is ({row['total']!r}, "
            f"{row['grade']!r}) — exactly 63.0 resolves to B (floors inclusive)"
        )
        assert int(row["boundary_at_risk"]) == 0 and row["score_low"] is None, (
            f"the degenerate total flagged at risk ({row['boundary_at_risk']}, "
            f"{row['score_low']!r}) — a zero-width range cannot cross a boundary, "
            "even sitting exactly on one (#102's limb, CT-GRADE-05)"
        )
    finally:
        store.close()


def test_tc_grade_c05_a_null_grade_is_rendered_as_an_honest_absence(
    tmp_data_dir, monkeypatch
):
    """`TC-GRADE-C05`'s export limb (`CT-GRADE-05`, rung 4) — where the package
    declares no boundary table, the grade is null and the module's own export
    renders that null as an honest absence: an empty cell, never a zero, never an
    invented band letter, never a blank that reads as 'fine'."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    export_dir = tmp_data_dir.parent / "c05-exports"
    monkeypatch.setenv("HARNESS_GRADE_EXPORT_DIR", str(export_dir))
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-NO-TABLE",),
            criteria=(
                {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
            ),
            rows=[("S-NO-TABLE", "C1", "B2", 63.0, "auto")],
        )  # no set_boundaries: the package declares no table
        path = world.service.export(world.run_id, 1, "csv")
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1, "fixture bug: the export lost its row"
        rendered = rows[0]
        assert rendered["grade"] == "", (
            f"the export renders grade {rendered['grade']!r} for a no-table package "
            "— the null must stay null on the page: an empty cell, never an "
            "invented band or a zero (CT-GRADE-05's null discipline, RISK-08)"
        )
        assert float(rendered["total"]) == 63.0, (
            f"the export renders total {rendered['total']!r} — the total is not "
            "null, only its band resolution is (CT-GRADE-05)"
        )
        assert int(rendered["boundary_at_risk"]) == 0, (
            "the export flags boundary risk for a package with no table — no "
            "floors, nothing to cross (CT-GRADE-05)"
        )
    finally:
        store.close()


def test_tc_grade_c05_the_console_does_not_render_a_null_grade_as_fine(tmp_data_dir):
    """`TC-GRADE-C05`'s console limb (`CT-GRADE-05`, rung 3, `[m_console]`) — no
    consumer renders the null grade as a blank that reads as "fine": the console's
    grade presentation must mark the unresolved band as absent/unresolved, not
    leave a gap where a mark would sit.

    Writtenahead on the same disclosed surface as C04's console limb
    (`aeh.console:render_grade_coverage`, #107): the landed console module renders
    grades with no boundary-risk language and no null-band presentation, so the
    clause's consumer obligation waits on that landing."""
    require(GRADE_MODULE, "open_grade", issue="#101")
    render_grade_coverage = require(
        CONSOLE_MODULE, "render_grade_coverage", issue="#107"
    )
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-NO-TABLE",),
            criteria=(
                {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
            ),
            rows=[("S-NO-TABLE", "C1", "B2", 63.0, "auto")],
        )  # no boundary table: the grade is null
        rendered = render_grade_coverage(world.run_id, "S-NO-TABLE", store=store)
        text = rendered if isinstance(rendered, str) else str(rendered)
        assert "fine" not in text.lower() and "no concern" not in text.lower(), (
            "the console presents a null grade as if nothing were wrong — a blank "
            "that reads as 'fine' is the RISK-08 presentation the clause forbids "
            "(CT-GRADE-05's consumer limb, M-CONSOLE)"
        )
        assert any(
            word in text.lower()
            for word in ("null", "none", "unresolved", "no grade", "absent")
        ), (
            f"the console renders the null grade as {text[:80]!r}... — the "
            "unresolved band must be presented as absent, not as a blank mark "
            "(CT-GRADE-05's consumer limb, M-CONSOLE)"
        )
    finally:
        store.close()