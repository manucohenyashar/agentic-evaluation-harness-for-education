"""`TS-48` (issue #129) — S2 and the upload handler over a real blob store and real bytes.

Test plan §5.19, `TC-CONSOLE-04` and `TC-CONSOLE-27`, Integration / rung 3.

**What these add over `CT-CONSOLE-C18`.** The clause case drives the handler with a *declared
size* and no bytes — the handler's own disclosed "no stream" walk, which digests chunk
descriptors and stages nothing. That path proves the handler never allocates the declared size;
it cannot prove the batch arrives. Here the handler is given a real byte stream of the probe size
and a store whose blob directory is real, so the oracle becomes the content: the staged blobs,
read back in order, must hash to exactly the bytes the client sent.

**Written ahead of implementation.** The issue says `yes`; stale — `M-CONSOLE` landed (#122,
#126).
"""

from __future__ import annotations

import hashlib
import html as html_lib
import io
import re
import time
import tracemalloc

import pytest

from aeh.console import SCREENS, build_console, upload_chunk_bytes, upload_scans
from aeh.store import open_store
from tests.support.console_vocabulary import (
    HANDLER_BUDGET_SECONDS,
    MEMORY_FLOOR_BYTES,
    UPLOAD_PROBE_BYTES,
    UPLOAD_RSS_RATIO_CEILING,
    dom_order,
    element_text,
    visible_text,
)
from tests.support.console_world import count, seed_scored_run

pytestmark = [pytest.mark.integration]


class _ScanStream:
    """A client's upload body: `size` bytes of a PDF-headed scan batch, produced chunk by chunk
    and never retained, so the only copy of the batch that can exist in this process is one the
    handler makes. It hashes what it hands over (the oracle for "arrived intact") and times its
    own reads (the client's share of the handler's wall clock)."""

    def __init__(self, size: int) -> None:
        self.remaining = size
        self.index = 0
        self.digest = hashlib.sha256()
        self.read_seconds = 0.0

    def read(self, n: int) -> bytes:
        started = time.perf_counter()
        take = min(n, self.remaining)
        if take <= 0:
            return b""
        head = b"%PDF-1.7\n" if self.index == 0 else b""
        block = hashlib.sha256(self.index.to_bytes(8, "big")).digest()
        chunk = (head + block * (take // len(block) + 1))[:take]
        self.remaining -= take
        self.index += 1
        self.digest.update(chunk)
        self.read_seconds += time.perf_counter() - started
        return chunk


def _blob_files(data_dir) -> int:
    return sum(1 for path in (data_dir / "blobs").rglob("*") if path.is_file())


# --- TC-CONSOLE-04 — several hundred megabytes stream to the blob store ------------------------------


@pytest.mark.slow
def test_tc_console_04_a_multi_hundred_megabyte_upload_streams_intact_to_the_blob_store(
    tmp_data_dir, monkeypatch
):
    """`TC-CONSOLE-04` / `FR-CONSOLE-04`, `NFR-CONSOLE-06` — memory watermark plus handler duration.

    The probe is `HARNESS_CONSOLE_UPLOAD_PROBE_BYTES` (300 MiB by default, the suite's env-gated
    knob), sent as a real stream into a console over a real store. Oracles:

    * **streams to the content-addressed blob store** — every `blob_ref` resolves in the store, and
      the blobs read back in order hash to exactly the bytes the client sent;
    * **memory watermark** — `tracemalloc`'s peak stays under the suite's ceiling
      (`max(8 MiB, 0.25 × upload)`), measured here, never reported by the handler;
    * **no long work in the handler** — nothing downstream of the upload ran inside it (no
      document, submission or work-unit row was written: transcription is the orchestrator's,
      on its own schedule), and the handler's own time — its wall clock minus the client's reads,
      the per-chunk content digests and the blob store's writes, which are the streaming itself —
      is under the 1-second handler budget.
    """
    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store, submissions=1)
        cohort = store.cohort(world.cohort_id)
        ledger_before = {t: count(cohort, t) for t in ("document", "submission", "work_unit")}

        blob_seconds = [0.0]
        blob_type = type(store.blobs())
        original_put = blob_type.put

        def _timed_put(self, data):  # noqa: ANN001
            started = time.perf_counter()
            try:
                return original_put(self, data)
            finally:
                blob_seconds[0] += time.perf_counter() - started

        monkeypatch.setattr(blob_type, "put", _timed_put)

        # The per-chunk content digest is streaming work too (content addressing is per byte),
        # so it comes out of the handler's own share alongside the reads and the writes.
        import aeh.console as console_module

        digest_seconds = [0.0]
        original_ref = console_module._chunk_ref

        def _timed_ref(chunk):  # noqa: ANN001
            started = time.perf_counter()
            try:
                return original_ref(chunk)
            finally:
                digest_seconds[0] += time.perf_counter() - started

        monkeypatch.setattr(console_module, "_chunk_ref", _timed_ref)

        app = build_console(store=store)
        stream = _ScanStream(UPLOAD_PROBE_BYTES)
        tracemalloc.start()
        started = time.perf_counter()
        try:
            outcome = upload_scans(app, cohort_id=world.cohort_id, stream=stream,
                                   filename="scan-batch.pdf")
            elapsed = time.perf_counter() - started
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        monkeypatch.undo()

        assert outcome.dispatched and not outcome.staged_in_browser, outcome.detail
        expected_chunks = -(-UPLOAD_PROBE_BYTES // upload_chunk_bytes())
        assert len(outcome.blob_refs) == expected_chunks, (
            f"{len(outcome.blob_refs)} blob refs for a {UPLOAD_PROBE_BYTES}-byte stream at "
            f"{upload_chunk_bytes()}-byte chunks; expected {expected_chunks}"
        )
        reassembled = hashlib.sha256()
        for ref in outcome.blob_refs:
            reassembled.update(store.blobs().get(ref.removeprefix("sha256:")))
        assert reassembled.hexdigest() == stream.digest.hexdigest(), (
            "the blobs the upload staged do not reassemble to the bytes the client sent — "
            "FR-CONSOLE-04: the upload streams to the content-addressed blob store"
        )

        ceiling = max(MEMORY_FLOOR_BYTES, UPLOAD_RSS_RATIO_CEILING * UPLOAD_PROBE_BYTES)
        assert peak < ceiling, (
            f"peak traced memory {peak} bytes for a {UPLOAD_PROBE_BYTES}-byte upload, over the "
            f"ceiling {ceiling:.0f} — NFR-CONSOLE-06: the batch is streamed, never buffered"
        )

        ledger_after = {t: count(cohort, t) for t in ledger_before}
        assert ledger_after == ledger_before, (
            f"the upload handler wrote pipeline rows {ledger_before} -> {ledger_after}; "
            f"transcription and scoring are the orchestrator's, never the request's"
        )
        handler_own = elapsed - stream.read_seconds - blob_seconds[0] - digest_seconds[0]
        assert handler_own < HANDLER_BUDGET_SECONDS, (
            f"the handler spent {handler_own:.2f}s of its own ({elapsed:.2f}s wall, "
            f"{stream.read_seconds:.2f}s reading the client, {digest_seconds[0]:.2f}s digesting "
            f"chunks, {blob_seconds[0]:.2f}s writing blobs) — FR-CONSOLE-04: no long work in a "
            f"request handler"
        )
    finally:
        store.close()


# --- TC-CONSOLE-27 — S2: PDF only, several files per document, order before transcription ---------


def test_tc_console_27_s2_accepts_pdf_parts_shows_their_order_first_and_stores_calibration(
    tmp_data_dir,
):
    """`TC-CONSOLE-27` / `FR-CONSOLE-27` — exact behaviour plus content assertion.

    1. **PDF only** — a non-PDF (ZIP magic, `.docx`) is refused with nothing staged: the blob
       directory's file count is unchanged, while a PDF part in the same console stages.
    2. **Several files per logical document** — one assessment arrives as three PDF parts, posted
       out of order (part 2, part 3, part 1); each is accepted.
    3. **The assembled page order is shown before transcription** — S2, rendered by a fresh
       console after the uploads (no tab holds the upload), lists exactly the three uploaded parts
       in assembled order (`M-INGEST`'s filename tier: part 1, 2, 3), in a section that precedes
       the transcription section, while no document row exists yet. A list of files that were
       never uploaded is not the assembled order.
    4. **Calibration papers** — the calibration card says the papers are stored with the package
       for a later version, and makes no claim of ambiguity discovery.
    """
    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store, submissions=1)
        cohort = store.cohort(world.cohort_id)
        app = build_console(store=store)
        problems: list[str] = []

        blobs_before = _blob_files(tmp_data_dir)
        refused = upload_scans(app, cohort_id=world.cohort_id,
                               stream=io.BytesIO(b"PK\x03\x04" + b"\x00" * 64),
                               filename="assessment.docx")
        if refused.dispatched or refused.blob_refs or _blob_files(tmp_data_dir) != blobs_before:
            problems.append(f"a non-PDF upload was accepted or staged: {refused!r}")
        disguised = upload_scans(app, cohort_id=world.cohort_id,
                                 stream=io.BytesIO(b"PK" + b"\x00" * 64),
                                 filename="assessment.pdf")
        if disguised.dispatched or disguised.blob_refs:
            problems.append(f"non-PDF bytes named .pdf were accepted: {disguised!r} — the format "
                            f"check must read the bytes, not the name")
        named_only = upload_scans(app, cohort_id=world.cohort_id, filename="assessment.docx",
                                  size_bytes=1024)
        if named_only.dispatched:
            problems.append(f"a declared .docx was accepted: {named_only!r}")

        parts = ("assessment-part-2.pdf", "assessment-part-3.pdf", "assessment-part-1.pdf")
        for name in parts:
            outcome = upload_scans(app, cohort_id=world.cohort_id,
                                   stream=io.BytesIO(b"%PDF-1.7\n" + name.encode() * 64),
                                   filename=name)
            if not outcome.dispatched or not outcome.blob_refs:
                problems.append(f"PDF part {name} was not accepted: {outcome!r}")
        if _blob_files(tmp_data_dir) <= blobs_before:
            problems.append("no PDF part reached the blob store")

        assert count(cohort, "document") == 1, "fixture: only the seeded paper's document exists"
        # Scoped the way the upload form scopes it: the cohort the parts were posted for.
        page = build_console(store=store).render(SCREENS["S2"], cohort_id=world.cohort_id).html
        listed = [html_lib.unescape(item) for item in re.findall(
            r"<li>Page \d+: ([^<]*)</li>", page)]
        assembled = sorted(parts)
        if listed != assembled:
            problems.append(
                f"S2's assembled page order lists {listed}; the three parts uploaded were "
                f"{assembled} (assembled by part number). The upload handler writes no record of "
                f"what arrived on a real store, and S2 falls back to a hard-coded list — so the "
                f"order a teacher is asked to check before transcription is not the order of their "
                f"upload (FR-CONSOLE-27)."
            )
        order = dom_order(page, "page-order", "transcription")
        if -1 in order or order[0] > order[1]:
            problems.append(f"the page order does not render before transcription: {order}")

        calibration = next(
            (section for section in re.findall(r'<section data-role="prompt">.*?</section>', page,
                                                re.S)
             if "calibration" in section.lower()),
            "",
        )
        text = visible_text(calibration).lower()
        if "stored" not in text or "later version" not in text:
            problems.append(f"the calibration card does not say the papers are stored for a later "
                            f"version: {text!r}")
        if "ambigu" in text:
            problems.append(f"the calibration card claims ambiguity discovery: {text!r}")
        if "transcription starts after" not in element_text(page, "transcription").lower():
            problems.append("the transcription section does not wait on the accepted order")
        _fail_with(problems)
    finally:
        store.close()


def _fail_with(problems: list[str]) -> None:
    assert not problems, "\n\n".join(problems)
