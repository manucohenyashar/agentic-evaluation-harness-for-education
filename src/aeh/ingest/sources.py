"""What a cohort has already read in: the read-only questions the intake command asks (blocker B4).

Reads only. `aeh ingest` asks them before it reads a file, so a re-run over the same folder of
scans does not mint a second submission for a paper already read: `ingest_submission` mints a new
submission id on every call, and two submissions for one paper would grade the student twice.
"""

from __future__ import annotations

import json
from typing import Any

from .schema import INGEST_STATEMENTS


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
