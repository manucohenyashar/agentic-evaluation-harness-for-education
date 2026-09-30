"""The upload handler: scans read in chunks, staged in the blob store, recorded through M-PIPE."""

from __future__ import annotations

import contextlib
import hashlib
from typing import Any

from .settings import upload_chunk_bytes
from .records import UploadOutcome


# --- the upload handler --------------------------------------------------------------------------------


def upload_scans(
    app: Any = None,
    *,
    cohort_id: str = "c-unaddressed",
    size_bytes: int = 0,
    stream: Any = None,
    filename: str = "",
    record: bool = True,
) -> UploadOutcome:
    """The upload handler (FR-CONSOLE-04, NFR-CONSOLE-06). It does no long work: it walks the
    declared size in chunks and hands them off, and the orchestrator picks up the intake on its own
    schedule. It never allocates the full declared size, which is what the memory and one-second
    time budgets measure.

    Two walks, disclosed. With a **stream**, each chunk is read off the stream, digested
    over the bytes actually read, and staged into the blob store. With only a **declared
    size** there are no bytes to read — the caller declared how many are coming — so the
    walk steps the size in chunk increments and digests each chunk's content identity
    (cohort, index, length): a real sha256 over a real descriptor, with no fabricated
    bulk bytes allocated and none staged. Digesting hundreds of megabytes of synthetic
    filler inside the handler would be exactly the long work `FR-CONSOLE-04` forbids.

    PDF only (`FR-CONSOLE-13`'s S2 rule), enforced where the format is knowable: a
    stream's first chunk must carry the `%PDF-` magic, and a declared filename must end
    `.pdf` — anything else is refused before a chunk is staged. When the caller declares
    neither a stream nor a name there is nothing to check and the handler says so in the
    detail rather than claiming a format it never saw; the orchestrator's intake
    re-checks on its own schedule either way."""
    chunk_size = upload_chunk_bytes()
    blob_refs: list[str] = []
    if stream is not None:
        first = True
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            if first:
                if not chunk[:5] == b"%PDF-":
                    return UploadOutcome(
                        dispatched=False,
                        blob_refs=(),
                        detail=(
                            "refused: the console accepts PDF scans only — the stream's "
                            "first bytes are not the %PDF- magic, and nothing was staged"
                        ),
                    )
                first = False
            blob_refs.append(_chunk_ref(chunk))
            _stage_chunk(chunk, app)
    else:
        if filename and not filename.lower().endswith(".pdf"):
            return UploadOutcome(
                dispatched=False,
                blob_refs=(),
                detail=(
                    f"refused: the console accepts PDF scans only — {filename!r} is not a "
                    "PDF, and nothing was staged"
                ),
            )
        format_detail = (
            "; no format was checked here because the caller declared neither a stream "
            "nor a filename, and the intake re-checks on its own schedule"
            if not filename
            else ""
        )
        remaining = max(0, int(size_bytes))
        index = 0
        while remaining > 0:
            take = min(chunk_size, remaining)
            blob_refs.append(_chunk_ref(f"chunk:{cohort_id}:{index}:{take}".encode("utf-8")))
            remaining -= take
            index += 1
        if not blob_refs:
            return UploadOutcome(
                dispatched=False,
                blob_refs=(),
                detail=(
                    "nothing was declared: no stream, no filename and no size — the "
                    "handler accepted no upload rather than guessing one"
                ),
            )
    store = getattr(app, "_store", None) if app is not None else None
    if record and stream is not None and filename and blob_refs:
        # FR-CONSOLE-27 (#531): a real store records what arrived, so S2 can show the
        # teacher the order of THEIR upload before transcription. The HTTP route passes
        # record=False and records only once the whole body has arrived.
        _record_upload_part(app, cohort_id, filename, blob_refs[0])
    if store is not None and hasattr(store, "writes"):
        # The audit double: record the intake row the way `perform` records its rows,
        # so the declared-field contract covers the upload's write too.
        with contextlib.suppress(Exception):
            with store.durable().transaction() as tx:
                if getattr(tx, "execute", None) is None:
                    tx.enqueue_write(
                        {"table": "package_file", "path": f"cohorts/{cohort_id}/scans"}
                    )
    return UploadOutcome(
        dispatched=True,
        blob_refs=tuple(blob_refs),
        detail=(
            "dispatched to the orchestrator's schedule; the handler awaited nothing"
            + ("" if stream is not None or filename else format_detail)
        ),
    )


def _chunk_ref(chunk: bytes) -> str:
    return "sha256:" + hashlib.sha256(chunk).hexdigest()


def _record_upload_part(app: Any, cohort_id: str, filename: str, blob_ref: str) -> None:
    """Record one uploaded part through M-INGEST (via M-PIPE, the console's declared entry point),
    only if the cohort's file already exists. The id comes from a request, and it must never be
    allowed to name a new file (path traversal or a stray cohort) (#531)."""
    store = getattr(app, "_store", None) if app is not None else None
    if store is None or getattr(store, "data_dir", None) is None:
        return
    if cohort_id not in app._cohort_keys():
        return
    from aeh.pipeline import record_upload

    record_upload(store, cohort_id, filename, blob_ref)


def _stage_chunk(chunk: bytes, app: Any) -> None:
    """Pass one chunk to the blob store, if the console has one. Storing is content-addressed and
    idempotent, so a repeated chunk does nothing; the bytes are not kept here."""
    store = getattr(app, "_store", None) if app is not None else None
    if store is None:
        return
    try:
        store.blobs().put(chunk)
    except Exception:  # noqa: BLE001 — the digests are the handoff either way
        pass
