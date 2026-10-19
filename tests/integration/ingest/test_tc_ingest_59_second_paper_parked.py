"""`TC-INGEST-59` (FR-INGEST-41) — a second paper for a student who already has one is parked.

*Inline regression.* Intake skips a scan only when its bytes were read before. A rescan of a
student's sheet — sharper, or the pages in the right order — is a different file, so it was read
in as a second paper, the identity check matched the same student, and the run graded that
student twice. `park_second_paper` is the door the intake command (`ingest_files`, behind both
`aeh ingest` and the papers screen) calls after each sheet; `TC-PIPE-38` drives it end to end.
The ladder itself is unchanged — a re-read of one sheet still gives the same verdict
(`CT-INGEST-12`). Arms:

(a) the second paper is parked under the student it matched (`already_has_paper`); the first
    stays the student's, untouched, and parking it again changes nothing;
(b) once the earlier paper is removed (M-STORE's `discard_ungraded_paper`), the parked copy is
    given to the student (B8's `assigned` decision) and is graded instead;
(c) a different student's paper is left as read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import aeh.agg  # noqa: F401 — the full cohort chain (CLAUDE.md: all eleven contributors)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.ingest import park_second_paper, record_quarantine_decision
from aeh.store import discard_ungraded_paper
from tests.support import f_names as fx

pytestmark = pytest.mark.integration


def _world(tmp_data_dir: Path, tag: str) -> fx.NamesWorld:
    return fx.NamesWorld(tmp_data_dir / f"w59-{tag}")


def test_tc_ingest_59_a_a_rescan_is_parked_not_graded_twice(tmp_data_dir):
    student = fx.ROWS[0]
    world = _world(tmp_data_dir, "a")
    try:
        first = world.ingest("first", student.full_name)
        assert park_second_paper(world.handle, first.submission_id) is None
        second = world.ingest("rescan", student.full_name)
        assert second.gates.get("v3") == "pass", fx.v3_findings(second)
        assert park_second_paper(world.handle, second.submission_id) == first.submission_id
        row = world.submission(second.submission_id)
        # Parked by the flag and the identity outcome; the diagnosis stays the ladder's own
        # (TC-INGEST-29), and M-ORCH's identity triage gives the copy no unit of any stage.
        assert (row["quarantined"], row["ingest_status"], row["v3_identity"]) == (
            1, "ok", "already_has_paper")
        assert row["student_ref"] == student.student_ref
        assert park_second_paper(world.handle, second.submission_id) is None
        kept = world.submission(first.submission_id)
        assert (kept["student_ref"], kept["quarantined"]) == (student.student_ref, 0)
    finally:
        world.close()


def test_tc_ingest_59_b_the_copy_is_used_once_the_earlier_paper_is_removed(tmp_data_dir):
    student = fx.ROWS[0]
    world = _world(tmp_data_dir, "b")
    try:
        first = world.ingest("first", student.full_name)
        second = world.ingest("rescan", student.full_name)
        park_second_paper(world.handle, second.submission_id)
        discard_ungraded_paper(world.store, fx.COHORT, first.submission_id)
        record_quarantine_decision(world.handle, second.submission_id, resolution="assigned",
                                   actor="teacher", student_ref=student.student_ref)
        row = world.submission(second.submission_id)
        assert (row["student_ref"], row["v3_identity"]) == (student.student_ref, "pass")
        assert not world.handle.query(
            "SELECT 1 FROM submission WHERE submission_id = :s", s=first.submission_id)
    finally:
        world.close()


def test_tc_ingest_59_c_another_students_paper_is_left_as_read(tmp_data_dir):
    world = _world(tmp_data_dir, "c")
    try:
        world.ingest("first", fx.ROWS[0].full_name)
        other = next(r for r in fx.ROWS[1:] if r.student_ref not in fx.COLLISION_REFS)
        report = world.ingest("other", other.full_name)
        assert report.gates.get("v3") == "pass", fx.v3_findings(report)
        assert park_second_paper(world.handle, report.submission_id) is None
        assert world.submission(report.submission_id)["quarantined"] == 0
    finally:
        world.close()
