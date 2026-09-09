"""`CT-EXTRACT-09` — a `described_graphic` span is marked, and `M-INTEG` routes on
the marker alone (`TC-EXTRACT-C09`).

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`) and
#74 (`M-INTEG`, the rung-3 half); registered in `WRITTEN_AHEAD_BLOCKERS` under
`"#68 extraction contract suite (TS-65)"` (rung-2 test) and `"#74 extraction contract
sweep (TS-65)"` (the routing differential, node ID — the file mixes blockers).

The clause: a span originating in a `described_graphic` region is **marked** as such
(FR-EXTRACT-09), so consumers can tell a student's words from a model's account of a
picture — and `M-INTEG` routes on this marker **alone** (FR-INTEG-05), which makes the
marker load-bearing rather than decorative (RISK-17).

Halves:
1. **The exact marker, rung 2** — the canonical document carries a real
   `described_graphic` region (the shipped `M-INGEST` header shapes) next to a
   transcribed one; the reply's span into the graphic region carries
   `region_kind="described_graphic"` — the exact shipped `REGION_KINDS` value, not a
   new spelling — the span into the student's words `"transcribed_text"`, and the
   persisted evidence payload carries the same marking, because the row is what
   `M-JUDGE` reads. Disclosed: the marking here verifies PRESERVATION through parse
   and persistence, not its derivation from the region headers — that derivation is
   #68's parse (the TS-26 disclosure, reused).
2. **The routing differential, rung 3** — with `M-INTEG` real, evidence lying wholly
   within the region is a routing candidate on the marker alone: two views identical
   in every stored dimension (same span geometry, same bytes, same crop) except the
   region's `region_kind` produce a `described_evidence` signal that is True for
   `described_graphic` and False for `transcribed_text`. Remove the marker and the
   routing changes — proving the marker is load-bearing.

Discriminator: an extractor that drops, renames, or homogenizes the marking turns
half 1 red; a consumer that routes on anything else (geometry alone, a config flag,
the criterion's identity) — so that flipping the marker changes nothing — turns
half 2 red — while every `FR-EXTRACT-*` case, which never compares the two region
kinds, stays green.

**Disclosed stand-ins** (suite register, `_doubles.py`): D1 (the reply's
`region_kind` label is fixture-supplied), D3 (document seeding; the region header
composition is `M-INGEST`'s and only the header shapes are load-bearing), D6
(`IntegrityGate`/`ExtractionView` under #74 — the integ vocabulary's own declared
surface). **Isolation**: rung 2 (half 1) / rung 3 (half 2) — real store, real blob
directory, `RecordedFixtureProvider` at the model boundary.
"""

from __future__ import annotations

import json

import pytest

from aeh.ingest import REGION_KINDS, UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from aeh.orch import Orchestrator, STAGE_EXTRACT
from tests.support.conf_builders import edge_panel
from tests.support.extract_vocabulary import (
    WORKER,
    extractor_ref,
    sampling_params,
    span_completion,
)
from tests.support.impl import EXTRACT_MODULE, INTEG_MODULE, require
from tests.support.integ_vocabulary import CitedRegion, ExtractionView, Span
from tests.support.orch_run import ORCH_COHORT_ID
from tests.contract.extract._doubles import (
    evidence_rows,
    make_world,
    payload_bytes,
    require_extract_surface,
    resolved_config,
)

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

#: The canonical artifact of a submission whose answer is a labelled diagram: the
#: student's words in a transcribed region, the transcriber's account of the picture
#: in a described_graphic one — the shipped header shapes (`aeh.ingest`, #38/#41);
#: the production composition is `M-INGEST`'s and only the shapes are load-bearing.
_GRAPHIC_HEADER = "<!-- region: kind=described_graphic element_kind=free_body_diagram -->"
_DIAGRAM_MARKDOWN = (
    UNTRUSTED_OPEN
    + "\n"
    + "<!-- region: kind=transcribed_text is_untrusted_content=1 -->\n"
    + "The crate sits on a 30 degree incline.\n"
    + "<!-- /region -->\n"
    + _GRAPHIC_HEADER + "\n"
    + "Labelled arrows: weight W down, normal N, friction f up the slope.\n"
    + "<!-- /region -->\n"
    + UNTRUSTED_CLOSE
)
_TRANSCRIBED_TEXT = "The crate sits on a 30 degree incline."
_GRAPHIC_TEXT = "Labelled arrows: weight W down, normal N, friction f up the slope."
_CRITERIA = [{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"}]


def _byte_span(markdown: str, needle: str, region_kind: str) -> dict[str, object]:
    md_bytes = markdown.encode("utf-8")
    start = md_bytes.find(needle.encode("utf-8"))
    assert start >= 0, f"fixture bug: {needle!r} not in the document"
    return {
        "start": start,
        "end": start + len(needle.encode("utf-8")),
        "text": needle,
        "region_kind": region_kind,
    }


def test_tc_extract_c09_described_graphic_spans_carry_the_exact_marker_and_the_row_keeps_it(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C09` half 1 — the graphic-region span is marked with the exact
    shipped `REGION_KINDS` value, the student's words with `transcribed_text`, and the
    persisted evidence payload carries the marking `M-JUDGE` will read."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    assert "described_graphic" in REGION_KINDS and "transcribed_text" in REGION_KINDS, (
        "TC-EXTRACT-C09: vacuity guard — the shipped REGION_KINDS vocabulary no "
        "longer carries the two region kinds this case pins"
    )
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_DIAGRAM_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        transcribed = _byte_span(_DIAGRAM_MARKDOWN, _TRANSCRIBED_TEXT, "transcribed_text")
        graphic = _byte_span(_DIAGRAM_MARKDOWN, _GRAPHIC_TEXT, "described_graphic")
        AssembleRequest = require(EXTRACT_MODULE, "assemble_request", issue="#68")
        PromptFields = require(EXTRACT_MODULE, "prompt_fields", issue="#68")
        Worker = require(EXTRACT_MODULE, WORKER, issue="#68")
        orchestrator = Orchestrator(world.store)
        run_id = orchestrator.create_run(
            ORCH_COHORT_ID, world.version, resolved_config(edge_panel(1))
        )
        (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)
        model_ref = extractor_ref()
        world.provider.record(
            PromptFields(AssembleRequest(unit)), model_ref, sampling_params(),
            span_completion([transcribed, graphic], build_id="ct-c09-build"),
        )
        result = Worker(world.store, world.provider, model_ref).process(unit)

        # The exact marker, on the result the module returns.
        kinds = {
            s["region_kind"] if isinstance(s, dict) else s.region_kind
            for s in result.spans
        }
        assert kinds == {"transcribed_text", "described_graphic"}, (
            f"TC-EXTRACT-C09: the extraction result carries region kinds {kinds} — "
            f"a described_graphic span must be marked with the exact shipped value "
            f"{sorted(REGION_KINDS)}, and the student's words with transcribed_text"
        )
        # The marking survives into the evidence payload — the row is what M-JUDGE
        # reads, so a result-only marking is the violation.
        rows = evidence_rows(world.store, run_id)
        assert len(rows) == 1, f"TC-EXTRACT-C09: expected one row, got {len(rows)}"
        stored = json.loads(payload_bytes(rows[0]["payload"]).decode("utf-8"))
        stored_kinds = {s["region_kind"] for s in stored["spans"]}
        assert stored_kinds == {"transcribed_text", "described_graphic"}, (
            f"TC-EXTRACT-C09: the evidence payload carries region kinds "
            f"{stored_kinds} — the marking did not survive persistence, and "
            f"M-JUDGE reads the row, not the result"
        )
        # Citability is unchanged: the graphic span still addresses the canonical
        # bytes exactly like any other span.
        doc = _DIAGRAM_MARKDOWN.encode("utf-8")
        g = next(s for s in stored["spans"] if s["region_kind"] == "described_graphic")
        assert doc[g["start"]:g["end"]].decode("utf-8") == _GRAPHIC_TEXT, (
            "TC-EXTRACT-C09: the graphic-region span does not round-trip against the "
            "canonical bytes"
        )
    finally:
        world.close()


def test_tc_extract_c09_m_integ_routes_on_the_marker_alone(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C09` half 2, rung 3 — the routing differential: two views identical
    except for the region's `region_kind`, and `M-INTEG`'s `described_evidence` signal
    flips with the marker alone. Remove the marker and the routing changes — the
    marker is load-bearing (FR-INTEG-05, RISK-17)."""
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    require_extract_surface()
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_DIAGRAM_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        doc = _DIAGRAM_MARKDOWN.encode("utf-8")
        start = doc.find(_GRAPHIC_TEXT.encode("utf-8"))
        end = start + len(_GRAPHIC_TEXT.encode("utf-8"))
        assert start >= 0, "fixture bug: graphic text not in the document"
        described = CitedRegion(
            region_id="r-graphic", region_kind="described_graphic",
            start=start, end=end, crop_ref="crops/r-graphic.png",
        )
        transcribed = CitedRegion(
            region_id="r-graphic", region_kind="transcribed_text",
            start=start, end=end, crop_ref="crops/r-graphic.png",
        )
        assert described.start == transcribed.start and described.end == transcribed.end, (
            "fixture bug: the two views differ in geometry, not only in the marker"
        )
        view = lambda region: ExtractionView(
            spans=(Span(start=start, end=end, text=_GRAPHIC_TEXT),),
            regions=(region,),
        )
        gate = IntegrityGate(
            world.store.cohort(ORCH_COHORT_ID), world.store.blobs(), view(described)
        )
        described_signals = gate.verify("r-ct-c09", "SYN-001", "C1")
        gate_unmarked = IntegrityGate(
            world.store.cohort(ORCH_COHORT_ID), world.store.blobs(), view(transcribed)
        )
        unmarked_signals = gate_unmarked.verify("r-ct-c09", "SYN-001", "C1")
        assert described_signals.described_evidence is True, (
            "TC-EXTRACT-C09: evidence wholly within a described_graphic region was "
            "not marked described — M-INTEG did not route on the marker"
        )
        assert unmarked_signals.described_evidence is False, (
            "TC-EXTRACT-C09: with the marker removed (the region relabeled "
            "transcribed_text) the routing signal did not change — M-INTEG routed on "
            "something other than the marker alone, so the marker is decorative and "
            "the student's words are indistinguishable from a model's account of a "
            "picture"
        )
    finally:
        world.close()
