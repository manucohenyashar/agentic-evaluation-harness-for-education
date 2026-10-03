"""What a cohort has already read in: the questions the intake command asks first (blocker B4).

`aeh ingest` asks them before it reads a file, so a re-run over the same folder of scans does not
mint a second gradable submission for a paper already read: `ingest_submission` mints a new
submission id on every call, and two submissions for one paper would grade the student twice.
The one write here, `park_interrupted_submissions`, touches only intake's own `submission` table.
"""

from __future__ import annotations

import json
from typing import Any

from .schema import INGEST_STATEMENTS
from .settings import GATE_NOT_REACHED


def submitted_sources(handle: Any) -> frozenset[str]:
    """The content hashes of every scan already read into a submission document in this cohort.

    A scan that never became a document (V0 found it unreadable, or transcription failed) is not
    here: reading it again creates another quarantined record, which is never graded."""
    sources: set[str] = set()
    for row in handle.query(INGEST_STATEMENTS["select_submission_sources"]):
        # `source_blobs` is the document's provenance: its `pages`, each naming the scan
        # (`blob_hash`) the page was rasterized from (`documents.py`).
        try:
            provenance = json.loads(row["source_blobs"] or "{}")
        except (TypeError, ValueError):
            continue
        for page in provenance.get("pages", ()) if isinstance(provenance, dict) else ():
            if isinstance(page, dict) and page.get("blob_hash"):
                sources.add(str(page["blob_hash"]))
    return frozenset(sources)


def has_assessment_document(handle: Any) -> bool:
    """Whether the cohort already holds the test paper as an `assessment` document, which the
    right-test check (V4) compares each paper's answers against."""
    return bool(handle.query(INGEST_STATEMENTS["select_assessment_documents"]))


def park_interrupted_submissions(handle: Any) -> tuple[str, ...]:
    """Quarantine every submission whose read was cut off, and return their ids.

    `ingest_submission` commits the submission row before it reads the pages, so a read stopped
    by Ctrl-C or a killed process leaves a row with no status and no document. Left alone, a run
    would admit it as a paper not yet judged, and the re-read of the same scan would make a
    second one. Parked as `incomplete` and quarantined, it waits in S8 to be closed and is never
    graded; the scan itself is read again. Call it only while no other intake writes the cohort."""
    rows = [dict(row) for row in handle.query(
        INGEST_STATEMENTS["select_interrupted_submissions"])]
    if rows:
        # Every gate `not_reached`: the ladder never got to any of them, so none counts as a
        # pass or a fail (`GATE_PASS_VALUES`), and a release is refused (nothing was read).
        with handle.transaction() as tx:
            for row in rows:
                tx.execute(INGEST_STATEMENTS["update_submission_gates"],
                           submission_id=row["submission_id"], v0=GATE_NOT_REACHED,
                           v1=GATE_NOT_REACHED, v2=GATE_NOT_REACHED, v3=GATE_NOT_REACHED,
                           v4=GATE_NOT_REACHED, v4_signals="{}", status="incomplete",
                           quarantined=1, student_ref=row["student_ref"])
    return tuple(str(row["submission_id"]) for row in rows)
