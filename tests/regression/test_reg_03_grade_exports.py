"""The exports the school actually receives do not change without someone saying so.

Case: `TC-REG-03` (test plan §6.9), `FR-GRADE-17`, golden file.

    baseline  The CSV and per-student PDF exports
    reviewer  The grading owner
    grounds   Accepted only with a declared export-mapping change; **a diff in a *mark* is a
              defect, not a baseline update**

That second half of the grounds is why this case is not one golden comparison. Layout, column
order and header text are export-mapping questions the grading owner can settle by inspecting
a diff. A changed *mark* is not: it means a delivered grade moved, and there is no version bump
that makes it acceptable. So the marks are lifted out of the CSV and compared **first**, with
their own message, and the layout comparison happens after. A single byte-for-byte assertion
over the whole file would report both failures identically and let the more serious one be
waved through with the less serious one.

**Written ahead of implementation** (§8.2). `export_grade_artifacts` is #104's. Remove the
marker — never the test — when #104 closes, and record the baselines in that PR.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re

import pytest

from tests.support.baselines import assert_matches_golden, entry_for, golden_bytes
from tests.support.impl import GRADE_MODULE, require

pytestmark = pytest.mark.writtenahead

ISSUE = "#104"
CASE = "TC-REG-03"
CSV_GOLDEN = "TC-REG-03/marks.csv"
PDF_GOLDEN = "TC-REG-03/per-student-pdf.manifest.json"

RUN_ID = "RUN-0001"
REVISION = 1

# The column that carries a delivered grade. Named here rather than found by position, because
# "the third column" stops being the mark the moment the mapping changes — which is the change
# the grading owner *is* allowed to make.
MARK_COLUMN = "mark"
STUDENT_COLUMN = "student_ref"


# The PDF fields that differ between two exports of identical content. Normalized out before
# digesting, so the baseline is about the document and not about when it was written.
_VOLATILE_PDF_FIELDS = (
    rb"/CreationDate\s*\([^)]*\)",
    rb"/ModDate\s*\([^)]*\)",
    rb"/Producer\s*\([^)]*\)",
    rb"/Creator\s*\([^)]*\)",
    rb"/ID\s*\[[^\]]*\]",
)


def _canonical_pdf(path) -> dict[str, object]:
    """A PDF as {page count, size, digest of the normalized bytes}.

    The same move `TC-REG-02` makes for the archive: strip what is genuinely non-reproducible,
    then digest the rest. If a producer buries a timestamp inside a compressed object stream
    this will be unstable — and that instability is itself a finding worth surfacing, because a
    per-student export nobody can reproduce cannot be a regression baseline at all.
    """
    raw = path.read_bytes()
    normalized = raw
    for pattern in _VOLATILE_PDF_FIELDS:
        normalized = re.sub(pattern, b"", normalized)
    return {
        "pages": len(re.findall(rb"/Type\s*/Page[^s]", raw)),
        "bytes": len(raw),
        "sha256": hashlib.sha256(normalized).hexdigest(),
    }


def _marks(csv_bytes: bytes) -> dict[str, str]:
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    assert reader.fieldnames and MARK_COLUMN in reader.fieldnames, (
        f"the marks CSV has no {MARK_COLUMN!r} column (columns: {reader.fieldnames}). "
        f"FR-GRADE-17 exports one CSV *of marks*; without that column this baseline cannot "
        f"tell a layout change from a changed grade, which is the distinction §6.9 requires."
    )
    return {row[STUDENT_COLUMN]: row[MARK_COLUMN] for row in reader}


def test_tc_reg_03_the_csv_and_per_student_pdf_exports_match_their_baselines(tmp_path):
    """TC-REG-03 — the CSV of marks and the per-student PDF set.

    Oracle: golden file, with the mark column compared separately and never accepted on diff.
    """
    export = require(GRADE_MODULE, "export_grade_artifacts", issue=ISSUE)
    entry = entry_for(CASE)

    artifacts = export(run_id=RUN_ID, revision=REVISION, dest=tmp_path)

    produced_csv = artifacts.csv_path.read_bytes()

    # The marks first, and with their own failure message. `CT-GRADE-07` makes imputation into a
    # delivered grade a permanent regression entry; a mark that moved between two runs of an
    # unchanged pipeline is that class of defect, and it must never read as "the export format
    # changed".
    baseline_marks = _marks(golden_bytes(CASE, CSV_GOLDEN))
    produced_marks = _marks(produced_csv)
    moved = {
        ref: (baseline_marks[ref], produced_marks.get(ref))
        for ref in baseline_marks
        if produced_marks.get(ref) != baseline_marks[ref]
    }
    assert not moved, (
        f"{len(moved)} delivered mark(s) changed against the baseline: "
        f"{dict(list(moved.items())[:5])}. Per §6.9, a diff in a mark is a **defect, not a "
        f"baseline update** — this is not the grading owner's to accept.\n\n{entry.governance()}"
    )

    # Then the export mapping, which the grading owner *may* accept on a declared change.
    assert_matches_golden(CASE, CSV_GOLDEN, produced_csv)

    # One PDF per student (FR-GRADE-17), and every student in the CSV has one.
    stems = sorted(p.stem for p in artifacts.pdf_paths)
    assert stems == sorted(produced_marks), (
        f"the CSV carries {len(produced_marks)} students and the export wrote {len(stems)} "
        f"PDFs. FR-GRADE-17 is one PDF per student; a student with a mark and no feedback "
        f"document has been dropped silently."
    )

    # The baseline is a canonical projection of each PDF, not its raw bytes: a PDF carries a
    # creation timestamp, a producer string and a file ID, so byte equality would fail on every
    # run and the baseline would be deleted rather than read. The projection is the same move
    # TC-REG-02 makes for the archive container — normalize the volatile fields, then digest
    # what is left — and it keeps the oracle pointed at the *content*. A manifest of filenames
    # alone would pass with every PDF empty or all of them identical.
    manifest = {
        "count": len(artifacts.pdf_paths),
        "students": {p.stem: _canonical_pdf(p) for p in sorted(artifacts.pdf_paths)},
    }
    for stem, projection in manifest["students"].items():
        assert projection["bytes"] > 0, f"{stem}'s PDF is empty"
        assert projection["pages"] >= 1, f"{stem}'s PDF declares no page"
    digests = [p["sha256"] for p in manifest["students"].values()]
    assert len(set(digests)) == len(digests), (
        "two or more per-student PDFs are byte-identical after normalization. Feedback is "
        "per-student (FR-GRADE-17); identical documents mean the export is not reading the "
        "student it names."
    )

    assert_matches_golden(
        CASE,
        PDF_GOLDEN,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
