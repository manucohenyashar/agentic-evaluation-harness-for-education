"""Validity T18 (issue #903): TC-CONSOLE-122 (FR-CONSOLE-96; FR-INGEST-13) — the parked paper's
mark, as scanned. Rung 3, over HTTP.

**World.** The PS9 physics sheets read in through the real intake (`Ingestor` with the pdfium
rasterizer and the scripted reader, the world `test_quarantine_resolution_b8.py` builds), served
by `serve_console()` on a loopback port. S9-004 is parked on a doubled tick; S9-006 is parked by
the identity check (V3, no name) and has no selection mark kept.

**Asserted.** S9-004's parked entry carries a `crop` URL that is a path on the console's own
origin (`/blobs/…`, no scheme, no host); a GET of it answers 200, `image/png`, and exactly the
bytes of the stored blob the region names. S9-006 carries `crop: null`, no crops, and the
absence stated in `crop_note`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
SAMPLE_SPEC = REPO / "docs" / "live-tests" / "config" / "ps9-forces-01.package.toml"
SAMPLES = REPO / "docs" / "live-tests" / "sample-materials"
DOUBLED = "S9-004-doubled-mark-and-blank"
NO_NAME = "S9-006-no-name"


def _ingest_ps9(store, monkeypatch) -> dict[str, str]:
    """The six PS9 sheets through the real intake; {stem: submission_id}."""
    monkeypatch.syspath_prepend(str(SAMPLES))
    import build_sample_materials as sm
    import verify_sample_materials as v

    from aeh.ingest import Ingestor, PdfiumRasterizer, PypdfSanitizer, ResidencySlot
    from aeh.orch.cohorts import RosterEntry, create_cohort
    from aeh.pipeline.packages import build_package, read_package_spec
    from aeh.pkg import PackageCatalog
    from aeh.prov import SamplingParams

    built = build_package(store, read_package_spec(SAMPLE_SPEC))
    catalog = PackageCatalog(store.package(built.package_id), package_id=built.package_id,
                             blobs=store.blobs())
    create_cohort(store, "class-ps9", "synthetic",
                  [RosterEntry(full_name=s["student"] or "S9-006",
                               student_ref=s["student"] or "S9-006")
                   for s in sm.PHYSICS_SHEETS])
    files, reader, blobs = sm.build_all(), v.ScriptedReader(), store.blobs()
    ingestor = Ingestor(store.cohort("class-ps9"), blobs, reader, v.TRANSCRIBER,
                        SamplingParams(temperature=0.0), PdfiumRasterizer(),
                        residency=ResidencySlot.for_policy(("transcriber",)),
                        sanitizer=PypdfSanitizer())
    paper = blobs.put(files[f"{sm.PHYSICS_ID}/01-test-paper.pdf"])
    reader.stage(paper, [v.assessment_transcript(sm.PHYSICS_ID)])
    ingestor.ingest_document([paper], kind="assessment", order_hint=[paper])
    ids = {}
    for sheet in sm.PHYSICS_SHEETS:
        blob = blobs.put(files[f"{sm.PHYSICS_ID}/answer-sheets/{sheet['stem']}.pdf"])
        reader.stage(blob, [v.sheet_transcript(sheet)])
        ids[sheet["stem"]] = ingestor.ingest_submission(
            [blob], "class-ps9", built.package_version, order_hint=[blob],
            filenames={blob: sheet["stem"] + ".pdf"}, package_catalog=catalog).submission_id
    return ids


def test_tc_console_122_a_parked_mark_carries_a_same_origin_crop(
        tmp_data_dir, monkeypatch, network_guard):
    """TC-CONSOLE-122 (see the module docstring)."""
    pytest.importorskip("pypdfium2")
    from aeh.console import serve_console
    from aeh.store import open_store
    from tests.support.label_identity_world import ServedRun

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    store = open_store(tmp_data_dir)
    server = None
    guard_down = False
    try:
        ids = _ingest_ps9(store, monkeypatch)
        stored_crops = [dict(row) for row in store.cohort("class-ps9").query(
            "SELECT r.crop_ref FROM document_region r JOIN document d "
            "ON d.document_id = r.document_id WHERE d.submission_id = :s "
            "AND r.region_kind = 'selection_mark' AND r.crop_ref IS NOT NULL", s=ids[DOUBLED])]
        assert stored_crops, "fixture: intake kept no crop of S9-004's doubled tick"
        identity = dict(store.cohort("class-ps9").query(
            "SELECT quarantined, v3_identity FROM submission WHERE submission_id = :s",
            s=ids[NO_NAME])[0])
        assert identity["quarantined"] == 1 and identity["v3_identity"] not in (None, "pass"), (
            f"fixture: S9-006 is not parked by the identity check (V3): {identity}")
        network_guard.uninstall()
        guard_down = True
        server = serve_console(store=store)
        port = server.socket.getsockname()[1]
        served = ServedRun(world=None, server=server, port=port, root=Path(tmp_data_dir))

        status, document = served.get("/api/v1/parked")
        assert status == 200, document
        parked = {entry["submission_id"]: entry for entry in document["parked"]}
        assert ids[DOUBLED] in parked and ids[NO_NAME] in parked, sorted(parked)

        doubled = parked[ids[DOUBLED]]
        crop = doubled["crop"]
        assert isinstance(crop, str) and crop.startswith("/blobs/"), crop
        parts = urlsplit(crop)
        assert not parts.scheme and not parts.netloc, f"not a same-origin path: {crop}"
        assert crop in [c["url"] for c in doubled["crops"]] and doubled["crop_note"] is None
        ref = crop[len("/blobs/"):]
        assert ref in {row["crop_ref"] for row in stored_crops}, (ref, stored_crops)

        import http.client

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        try:
            connection.request("GET", crop)
            response = connection.getresponse()
            body = response.read()
        finally:
            connection.close()
        assert response.status == 200, (response.status, body[:200])
        assert response.getheader("Content-Type", "").split(";")[0] == "image/png", (
            response.getheader("Content-Type"))
        assert body == store.blobs().get(ref), "the crop URL does not serve the stored blob"

        nameless = parked[ids[NO_NAME]]
        assert nameless["crop"] is None and nameless["crops"] == [], nameless
        assert isinstance(nameless["crop_note"], str) and nameless["crop_note"].strip(), nameless
    finally:
        try:
            if server is not None:
                server.terminate()
            if guard_down:
                network_guard.install()
        finally:
            store.close()
            for name in ("build_sample_materials", "verify_sample_materials"):
                sys.modules.pop(name, None)
