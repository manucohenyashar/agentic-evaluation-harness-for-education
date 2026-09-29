"""FUZZ-09 (FR-INGEST-36/37, CT-INGEST-21; TS-99 #393): cluster resolution never stores a resolved
selection mark without a selection.

Random pages of 1–6 regions of mixed kinds, each holding the same unresolved token (so one cluster
reaches them all), resolved with a resolution drawn from the declared option ids, undeclared
strings, `""` and unicode. After `resolve_cluster`, every stored `selection_mark` region satisfies
`selection IS NOT NULL ⇔ selection_state = 'resolved'`, a resolved selection is a declared option,
and nothing but `IngestError` escapes.

The committed Hypothesis database is the suite's (`tests/conftest.py` profiles: 50 by default,
200 under `ci`, more under `nightly`); a failing example becomes a regression case.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aeh.ingest import IngestError, Ingestor
from aeh.prov import SamplingParams
from tests.integration.ingest.test_ingest_gateway import (
    THROUGH_SANITIZER, OnePageRasterizer, _fixture, _model, _region_provider)
from tests.integration.ingest.test_tc_ingest_50_cluster_resolution_per_region_kind import (
    COHORT, OPTIONS, QUESTION, TOKEN, _seed_options)
from tests.support.store_api import statement

pytestmark = [pytest.mark.property, pytest.mark.integration]

KINDS = ("transcribed_text", "selection_mark", "described_graphic")

resolutions = st.one_of(
    st.sampled_from(OPTIONS),
    st.sampled_from(("E", "a", " C", "C ", "option C", "AB")),
    st.just(""),
    st.text(alphabet=st.characters(min_codepoint=0x80, max_codepoint=0x2FFF), min_size=1, max_size=4),
)


def _page(kinds: list[str]) -> str:
    return "\n".join(
        f"<!-- region: kind={kind} question_id={QUESTION if kind == 'selection_mark' else 'Q1'} -->\n"
        f"<unresolved>{TOKEN}</unresolved>\n<!-- /region -->"
        for kind in kinds)


@settings(deadline=None)
@given(kinds=st.lists(st.sampled_from(KINDS), min_size=1, max_size=6), resolution=resolutions)
def test_fuzz_09_a_resolved_selection_mark_always_carries_its_selection(kinds, resolution):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        for sub in ("packages", "cohorts", "blobs"):
            (data / sub).mkdir(parents=True)
        store, blobs, _r, _p, _s, _ = _fixture(data)
        try:
            handle = store.cohort(COHORT)
            ingestor = Ingestor(handle, blobs, _region_provider([_page(kinds)]), _model(),
                                SamplingParams(temperature=0.0), OnePageRasterizer(),
                                sanitizer=THROUGH_SANITIZER)
            source = blobs.put(b"one submission")
            document_id = ingestor.ingest_document([source], kind="submission",
                                                   filenames={source: "scan.md"})
            catalog, version = _seed_options(store)
            clusters = [c for c in ingestor.clusters(COHORT) if c.token == TOKEN]
            if clusters:
                try:
                    ingestor.resolve_cluster(clusters[0].cluster_id, resolution,
                                             package_catalog=catalog, package_version=version)
                except IngestError:
                    pass  # the boundary's declared refusal
            marks = handle.query(statement(
                "SELECT selection, selection_state FROM document_region WHERE document_id = :d "
                "AND region_kind = 'selection_mark'", issue="#393"), d=document_id)
        finally:
            store.close()
    for mark in marks:
        resolved = mark["selection_state"] == "resolved"
        assert (mark["selection"] is not None) == resolved, (
            f"kinds {kinds}, resolution {resolution!r}: stored {dict(mark)} (CT-INGEST-21)")
        if resolved:
            assert mark["selection"] in OPTIONS, dict(mark)
