"""Resolving a parked paper says what it does (TC-CONSOLE-51..52, live-test blocker B8).

Before this, `resolve quarantine item` closed a paper as unresolvable for ANY word but
`matched` (a typo, or none) and still answered `dispatched: true`; and `matched` released a
paper whose student the identity check never matched, to be graded under `unknown`. The papers
here are the sample physics sheets parked by the real intake checks.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aeh.console import build_console
from aeh.pipeline.packages import build_package, read_package_spec
from aeh.store import open_store

REPO = Path(__file__).resolve().parents[3]
SAMPLE_SPEC = REPO / "docs" / "live-tests" / "config" / "ps9-forces-01.package.toml"
SAMPLES = REPO / "docs" / "live-tests" / "sample-materials"


@pytest.fixture
def parked(tmp_data_dir, monkeypatch):
    """A data folder holding the six physics sheets after intake: three released, three parked
    (a doubled mark, the wrong test, no name). Yields (store, {stem: submission_id})."""
    pytest.importorskip("pypdfium2")
    monkeypatch.syspath_prepend(str(SAMPLES))
    import build_sample_materials as sm
    import verify_sample_materials as v

    from aeh.ingest import Ingestor, PdfiumRasterizer, PypdfSanitizer, ResidencySlot
    from aeh.orch.cohorts import create_cohort
    from aeh.pkg import PackageCatalog
    from aeh.prov import SamplingParams

    store = open_store(tmp_data_dir)
    built = build_package(store, read_package_spec(SAMPLE_SPEC))
    catalog = PackageCatalog(store.package(built.package_id), package_id=built.package_id,
                             blobs=store.blobs())
    create_cohort(store, "class-ps9", "synthetic",
                  [s["student"] or "S9-006" for s in sm.PHYSICS_SHEETS])
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
    try:
        yield store, ids
    finally:
        store.close()
        for name in ("build_sample_materials", "verify_sample_materials"):
            sys.modules.pop(name, None)


def _row(store, submission_id):
    return dict(store.cohort("class-ps9").query(
        "SELECT ingest_status, quarantined, student_ref, v3_identity FROM submission "
        "WHERE submission_id = :s", s=submission_id)[0])


# --- the decision is one of two words ----------------------------------------------------------


@pytest.mark.parametrize("params", [{"resolution": "matchd"}, {"resolution": "close"}, {}])
def test_tc_console_51_an_unknown_or_missing_word_is_refused(parked, params):
    store, ids = parked
    target = ids["S9-004-doubled-mark-and-blank"]
    before = _row(store, target)
    outcome = build_console(store=store).perform("resolve quarantine item",
                                                 submission_id=target, **params)
    assert not outcome.dispatched
    assert "'matched'" in outcome.detail and "'unresolvable'" in outcome.detail
    assert target in outcome.detail  # every refusal names the paper it was given
    assert _row(store, target) == before == {**before, "quarantined": 1}


# --- a release needs a student ------------------------------------------------------------------


def test_tc_console_52_a_paper_with_no_matched_student_is_not_released(parked):
    store, ids = parked
    target = ids["S9-006-no-name"]
    before = _row(store, target)
    assert before["student_ref"] == "unknown" and before["v3_identity"] != "pass"
    outcome = build_console(store=store).perform("resolve quarantine item",
                                                 submission_id=target, resolution="matched")
    assert not outcome.dispatched
    assert "graded under nobody" in outcome.detail and "aeh ingest" in outcome.detail
    assert _row(store, target) == before


def test_tc_console_52_a_paper_with_its_student_is_released_and_the_other_closed(parked):
    store, ids = parked
    console = build_console(store=store)
    released = console.perform("resolve quarantine item",
                               submission_id=ids["S9-004-doubled-mark-and-blank"],
                               resolution="matched")
    assert released.dispatched, released.detail
    assert _row(store, ids["S9-004-doubled-mark-and-blank"])["quarantined"] == 0
    assert _row(store, ids["S9-004-doubled-mark-and-blank"])["ingest_status"] == "ok"
    closed = console.perform("resolve quarantine item", submission_id=ids["S9-006-no-name"],
                             resolution="unresolvable")
    assert closed.dispatched, closed.detail
    row = _row(store, ids["S9-006-no-name"])
    assert (row["ingest_status"], row["quarantined"]) == ("incomplete", 0)
