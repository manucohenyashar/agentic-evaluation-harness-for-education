"""Recording the uploaded parts of a cohort's scans, and reading them in assembled order."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .schema import INGEST_STATEMENTS
from .assembly import _natural_key


def record_upload_part(store: Any, cohort_id: str, filename: str, blob_ref: str,
                       received_at: str | None = None) -> None:
    """Record one uploaded part of a cohort's scans: its file name, the content address of its
    first chunk, and when it arrived (FR-CONSOLE-27). Safe to repeat per (cohort, file name, blob).
    """
    stamp = received_at or datetime.now(timezone.utc).isoformat()
    with store.cohort(cohort_id).transaction() as tx:
        tx.execute(INGEST_STATEMENTS["insert_upload_part"], cohort_id=cohort_id,
                   filename=filename, blob_ref=blob_ref, received_at=stamp)


def upload_parts_in_order(store: Any, cohort_id: str) -> tuple[str, ...]:
    """The cohort's uploaded parts in assembly order: natural file-name order (`page-2` before
    `page-10`), the same key assembly uses. Two names at the same position keep their arrival order
    (assembly itself refuses them, FR-INGEST-31). Empty when nothing was uploaded."""
    names: list[str] = []
    for row in store.cohort(cohort_id).query(INGEST_STATEMENTS["select_upload_parts"],
                                             cohort_id=cohort_id):
        name = str(row["filename"])
        if name not in names:
            names.append(name)
    return tuple(sorted(names, key=_natural_key))
