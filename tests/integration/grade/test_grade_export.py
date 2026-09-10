"""`TC-GRADE-17` — export from a named grade revision.

Test plan §5.14; `FR-GRADE-17`; Integration / 2; golden file; P1. The case's oracle
sentence is *"One CSV of marks and one PDF per student; the export names the revision it
was produced from; output matches its golden file"*, and this file owns the shipped half
of it — the CSV member `GradingService.export` (design §3.14's Protocol member) — while
the school-facing golden baseline (the column-order/header mapping as a committed
baseline, plus the per-student PDF) is `TC-REG-03`'s registered surface:
`tests/regression/test_reg_03_grade_exports.py`, red on `#104`'s
`export_grade_artifacts`. Cross-referenced, not duplicated — `FR-GRADE-17` traces to
both cases, and re-asserting the baseline here would put two golden owners on one file.

What is GREEN and pinned here, against shipped code:

1. **The export names the revision it was produced from** — in the filename
   (`grade-{run}-rev{N}.csv`) and in a `revision` column on every row, and the export
   reads the NAMED revision, not the current one: after an amendment, `rev1`'s file is
   byte-identical to what it was before the amendment, and `rev2`'s file carries the
   amended row.
2. **The export mapping** — the exact 18-column header (the module's own declared
   column order), one row per graded submission in `submission_id` order, and the
   hand-pinned record values (state, grade, total, coverage counters) reproduced from
   the ledger, verified against an independent readback.
3. **The PDF refusal is exact** — `fmt="pdf"` raises `NotImplementedError` naming
   `#104` / `export_grade_artifacts` / `TC-REG-03` / `FR-GRADE-17`. Pinned as the
   shipped behaviour on purpose: the refusal IS the boundary between this module's
   member and #104's, and a silent half-implementation (a stub PDF, an empty file)
   would be the failure mode the pin prevents. When #104 lands, `TC-REG-03`'s baseline
   supersedes the refusal and this pin is revisited with it.

**Disclosed stand-ins** (`grade_vocabulary.py`, header): the run-completion UPDATE
(`M-ORCH` is the run row's single writer), `write_criterion_scores` standing in for
`M-AGG`, and `backdate_grades` pinning `computed_at` to a fixed instant so the export
content is deterministic — a wall-clock seam on the service is not a design-declared
surface. The run id is caller-pinned (`seed_run(run_id=...)`) for the same reason.

**Isolation:** rung 2 — real store, real package lineage, real grade ledger; exports
redirected to the test's own directory via the `HARNESS_GRADE_EXPORT_DIR` knob
(CLAUDE.md seam 3) so the case never writes into the platform temp default.
"""

from __future__ import annotations

import csv

import pytest

from aeh.pkg import GradePolicy, PackageCatalog
from aeh.store import open_store
from tests.support.grade_vocabulary import (
    GRADE_BLOCKER,
    backdate_grades,
    grade_rows,
    write_criterion_scores,
)
from tests.support.impl import GRADE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration]

ISSUE = GRADE_BLOCKER

_PACKAGE = "pkg-orch"
_RUN_ID = "r-exp-01"
_BACKDATED = "2026-08-01T09:00:00+00:00"

#: The export mapping `GradingService.export` declares — pinned verbatim, order
#: included, because a school-facing column order is exactly what drifts quietly.
_COLUMNS = (
    "run_id", "submission_id", "revision", "state", "grade", "total",
    "policy_version", "answer_key_ref", "computed_at",
    "criteria_total", "criteria_auto", "criteria_reviewed",
    "criteria_provisional", "criteria_missing",
    "boundary_at_risk", "score_low", "score_high", "missing_criteria",
)


def _seed_final_run(store, submissions):
    """A completed run, fully scored under a windowless policy, graded `final`."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    criteria = (
        {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
        {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
    )
    _orchestrator, run_id, version = seed_run(
        store,
        submissions=submissions,
        criteria=criteria,
        run_id=_RUN_ID,
    )
    catalog = PackageCatalog(store.package(_PACKAGE), package_id=_PACKAGE)
    catalog.set_grade_policy(version, GradePolicy(combination="weighted_sum"))
    cohort = store.cohort(ORCH_COHORT_ID)
    write_criterion_scores(
        cohort,
        [(sid, "C1", "B2", 7.0, "auto") for sid in submissions]
        + [(sid, "C2", "B1", 6.0, "auto") for sid in submissions],
    )
    svc = require(GRADE_MODULE, "open_grade", issue=ISSUE)(store)
    svc.compute_all(run_id)
    with cohort.transaction() as tx:
        tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=run_id)
    svc.compute_all(run_id)  # the settlement pass: revision 1 reads final in place
    backdate_grades(cohort, _BACKDATED)
    return run_id, cohort, svc


def _read_csv(path) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def test_tc_grade_17_the_export_names_the_revision_it_was_produced_from(
    tmp_data_dir, monkeypatch
):
    """`TC-GRADE-17` — the filename carries the revision, every row carries a
    `revision` column, and the export reads the NAMED revision: `rev1` is frozen the
    moment `rev2` exists, and `rev2` carries the amendment."""
    monkeypatch.setenv("HARNESS_GRADE_EXPORT_DIR", str(tmp_data_dir / "exports"))
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort, svc = _seed_final_run(store, ("S-E1", "S-E2"))

        first = svc.export(run_id, 1, "csv")

        assert first.name == f"grade-{run_id}-rev1.csv", (
            f"the export is named {first.name!r} — FR-GRADE-17: the export names the "
            "revision it was produced from (grade-{run}-rev{N}.csv)"
        )
        header, rows = _read_csv(first)
        assert tuple(header) == _COLUMNS, (
            f"the CSV header is {header!r} — the export mapping this module owns is "
            "the pinned 18-column set, order included"
        )
        assert [row["submission_id"] for row in rows] == ["S-E1", "S-E2"], (
            "one row per graded submission, in submission_id order — the CSV of marks"
        )
        assert all(row["revision"] == "1" for row in rows), (
            "the revision column does not say '1' on every row — the export must name "
            "the revision it was produced from in the data, not only in the filename"
        )
        assert all(row["run_id"] == run_id for row in rows), (
            "the run_id column does not carry the exported run — provenance columns "
            "are part of the record the CSV projects"
        )
        by_student = {row["submission_id"]: row for row in rows}
        assert by_student["S-E1"]["state"] == "final", (
            f"the exported state is {by_student['S-E1']['state']!r} — the completed "
            "run settled its grades, the export must not withhold the state"
        )
        assert by_student["S-E1"]["total"] == "13.0", (
            f"the exported total is {by_student['S-E1']['total']!r}, expected 13.0 — "
            "C1 7.0 + C2 6.0, the hand-pinned mark (fixture drift)"
        )
        assert by_student["S-E1"]["criteria_total"] == "2", (
            f"criteria_total reads {by_student['S-E1']['criteria_total']!r} — the "
            "coverage counters are exported columns (FR-GRADE-04)"
        )
        assert by_student["S-E1"]["missing_criteria"] == "[]", (
            f"missing_criteria reads {by_student['S-E1']['missing_criteria']!r} — "
            "nothing is missing in this fixture"
        )

        # The export projects the ledger at the named revision — compared against an
        # independent readback of the stored rows, not against itself.
        expected = {
            row["submission_id"]: row for row in grade_rows(cohort)
            if row["revision"] == 1
        }
        for row in rows:
            stored = expected[row["submission_id"]]
            assert row["policy_version"] == stored["policy_version"], (
                "the exported policy_version does not match the ledger — the CSV "
                "projects the stored record, it does not re-derive it"
            )
            assert row["answer_key_ref"] == stored["answer_key_ref"], (
                "the exported answer_key_ref does not match the ledger — the key the "
                "grade pinned by is provenance the CSV must carry"
            )
            assert row["computed_at"] == stored["computed_at"], (
                "the exported computed_at does not match the ledger row"
            )

        # The amendment mints revision 2; revision 1's export must not move.
        before_amendment = first.read_bytes()
        svc.amend(run_id, "S-E1", {"C1": 3.0}, actor="t-may", reason="mis-banded")

        assert first.read_bytes() == before_amendment, (
            "revision 1's export changed when revision 2 landed — the export reads "
            "the NAMED revision, and revision 1 is immutable (FR-GRADE-12's retention "
            "reaching the export surface)"
        )
        second = svc.export(run_id, 2, "csv")
        assert second.name == f"grade-{run_id}-rev2.csv", (
            f"the amended export is named {second.name!r} — revision 2 must name "
            "itself, not silently overwrite revision 1's file"
        )
        _, amended_rows = _read_csv(second)
        assert all(row["revision"] == "2" for row in amended_rows), (
            "revision 2's export does not name revision 2 on its rows"
        )
        assert next(
            row for row in amended_rows if row["submission_id"] == "S-E1"
        )["total"] == "9.0", (
            "the amended student's exported total is not 9.0 — the export must read "
            "the amended revision's marks (C1 3.0 + C2 6.0)"
        )
    finally:
        store.close()


def test_tc_grade_17_the_pdf_refusal_is_exact(tmp_data_dir, monkeypatch):
    """`TC-GRADE-17` — the PDF is #104's surface, and the refusal says so exactly.

    The pin is deliberate: `export`'s non-CSV refusal is the boundary between this
    module's declared member and `#104`'s `export_grade_artifacts`. A half-implementation
    (an empty file, a CSV with a PDF name) would pass every shape assertion below and
    still be wrong — so the exception type and the four names the message carries are
    the assertion."""
    monkeypatch.setenv("HARNESS_GRADE_EXPORT_DIR", str(tmp_data_dir / "exports"))
    store = open_store(tmp_data_dir)
    try:
        run_id, _cohort, svc = _seed_final_run(store, ("S-E3",))

        with pytest.raises(Exception) as excinfo:
            svc.export(run_id, 1, "pdf")

        assert type(excinfo.value).__name__ == "NotImplementedError", (
            f"the PDF request raised {type(excinfo.value).__name__} — the refusal is "
            "exact: NotImplementedError naming the surface that owes the format"
        )
        message = str(excinfo.value)
        for token in ("pdf", "#104", "export_grade_artifacts", "TC-REG-03", "FR-GRADE-17"):
            assert token in message, (
                f"the refusal message does not name {token!r}: {message!r} — the "
                "boundary must be discoverable from the error alone"
            )
        assert not list((tmp_data_dir / "exports").glob("**/*")), (
            "the refused export left files behind — a refusal that writes is not a "
            "refusal"
        )
    finally:
        store.close()