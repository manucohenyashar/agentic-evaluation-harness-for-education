"""`CT-EXTRACT-15` — the non-promise: spans may overlap, be out of order, be
non-minimal, or be incomplete, and every consumer still behaves (`TC-EXTRACT-C15`).

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`) and
the three rung-3 consumer surfaces it sweeps — #73 (`M-INTEG` verification), #74
(`M-INTEG`'s signals), #78 (`M-JUDGE` assembly), #97 (`M-SYNTH` rendering);
registered in `WRITTEN_AHEAD_BLOCKERS` under `"#73+#74+#78+#97 extraction contract
sweep (TS-65)"` (file-level — every test here needs the same conjunction).

The clause: **not promised** — spans are not guaranteed to be correct, complete,
minimal, non-overlapping, or in document order. Every one of those is checked or
tolerated downstream: verification by `M-INTEG` (CT-INTEG-01), sufficiency by the
panel. A consumer that assumes ordered or non-overlapping spans is outside the
contract. Four disclaimers in one clause, so the case varies all four — this is the
case that keeps a future extractor change legal.

Variations (one test each, the same three-consumer sweep inside every one):
- **overlap** — two spans sharing bytes: `M-INTEG` verifies each span on its own
  bytes (a sibling's overlap is irrelevant to verification), the panel's sufficiency
  verdict stands, the panel's assembled input carries both spans, and `M-SYNTH`
  renders both.
- **out of order** — the span list is reversed relative to the document:
  verification is still per-span, sufficiency still the panel's, and the render
  contains BOTH texts — rendering without assuming order.
- **non-minimal** — a span extended past its sentence (still addressing real bytes):
  verification re-derives True, the consumers take the span as they find it — no
  consumer shrinks or "fixes" it.
- **incomplete** — one sentence covered, two uncovered: sufficiency_flag is STILL
  the panel's verdict (True, the panel said sufficient) — a consumer that derived
  insufficiency from span completeness would be assuming what the clause does not
  promise. The panel judges sufficiency, not coverage.

Discriminator: a consumer that sorts, de-overlaps, minimizes, or infers sufficiency
*by assumption* turns exactly the variation it cannot tolerate red while the
benign `FR-EXTRACT-*` cases stay green; `M-INTEG` trusting an extraction-side
correctness claim (rather than re-deriving per span) turns every variation red.

**Disclosed stand-ins** (suite register, `_doubles.py`): D1 (each variation's reply
is `span_completion`'s stand-in carrying the varied spans), D3, D6 (`verify_span`
under #73, `IntegrityGate` under #74, `assemble` under #78, `synthesize(run_id,
submission_id=...)` under #97 — no new consumer symbol invented; the render's exact
shape is #97's, so the render assertion is substring containment of every span's
text). **Isolation: rung 3** — real store, real ledger, real blob directory, real
panel enumeration, `RecordedFixtureProvider` at the model boundary.
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.orch import STAGE_EXTRACT, Orchestrator
from tests.support.conf_builders import edge_panel
from tests.support.extract_vocabulary import (
    WORKER,
    extractor_ref,
    sampling_params,
    span_completion,
)
from tests.support.impl import (
    EXTRACT_MODULE,
    INTEG_MODULE,
    JUDGE_MODULE,
    SYNTH_MODULE,
    require,
)
from tests.support.integ_vocabulary import ExtractionView, PanelFlags, Span
from tests.support.orch_run import ORCH_COHORT_ID
from tests.contract.extract._doubles import (
    byte_span,
    build_markdown,
    make_world,
    payload_bytes,
    require_extract_surface,
    resolved_config,
)

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

_S1 = "The buffer overflowed because the index was never bounds-checked."
_S2 = "The fix clamps the index before the write."
_S3 = "The tests now cover the boundary case."
_MARKDOWN = build_markdown(_S1 + "\n" + _S2 + "\n" + _S3 + "\n")
_CRITERIA = [{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"}]


def _marked(needle: str) -> dict[str, Any]:
    span = byte_span(_MARKDOWN, needle)
    return {**span, "region_kind": "transcribed_text"}


def _spans_overlap() -> list[dict[str, Any]]:
    """Two spans sharing bytes — the tail of S1 sits inside a span over S1."""
    return [_marked(_S1),
            _marked("because the index was never bounds-checked.")]


def _spans_out_of_order() -> list[dict[str, Any]]:
    """The span list reversed relative to the document order."""
    return [_marked(_S3), _marked(_S1)]


def _spans_non_minimal() -> list[dict[str, Any]]:
    """One span extended past its sentence — still addressing real bytes."""
    doc = _MARKDOWN.encode("utf-8")
    base = byte_span(_MARKDOWN, _S1)
    start = max(0, base["start"] - 5)
    end = min(len(doc), base["end"] + 5)
    return [{"start": start, "end": end,
             "text": doc[start:end].decode("utf-8"),
             "region_kind": "transcribed_text"}]


def _spans_incomplete() -> list[dict[str, Any]]:
    """One sentence covered; the other two are not."""
    return [_marked(_S1)]


_VARIATIONS = (
    ("overlap", _spans_overlap),
    ("out of order", _spans_out_of_order),
    ("non-minimal", _spans_non_minimal),
    ("incomplete", _spans_incomplete),
)


def _sweep(tmp_data_dir: Any, make_fixture_provider: Any, spans: list[dict[str, Any]]):
    """One run, one extract unit recorded the varied span list, one extraction; then
    the three consumers over the result. Returns what the per-variation assertions
    read."""
    VerifySpan = require(INTEG_MODULE, "verify_span", issue="#73")
    IntegrityGate = require(INTEG_MODULE, "IntegrityGate", issue="#74")
    Assemble = require(JUDGE_MODULE, "assemble", issue="#78")
    Synthesize = require(SYNTH_MODULE, "synthesize", issue="#97")
    require_extract_surface()

    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        AssembleRequest = require(EXTRACT_MODULE, "assemble_request", issue="#68")
        PromptFields = require(EXTRACT_MODULE, "prompt_fields", issue="#68")
        Worker = require(EXTRACT_MODULE, WORKER, issue="#68")
        model_ref = extractor_ref()
        orchestrator = Orchestrator(world.store)
        run_id = orchestrator.create_run(
            ORCH_COHORT_ID, world.version, resolved_config(edge_panel(1))
        )
        (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)
        world.provider.record(
            PromptFields(AssembleRequest(unit)), model_ref, sampling_params(),
            span_completion(spans, build_id="ct-c15-build"),
        )
        Worker(world.store, world.provider, model_ref).process(unit)

        # M-INTEG verifies RATHER THAN ASSUMING: every span re-derives True against
        # the canonical bytes, whatever its siblings or its minimality.
        doc = _MARKDOWN.encode("utf-8")
        for span in spans:
            assert VerifySpan(doc, {"start": span["start"], "end": span["end"],
                                    "text": span["text"]}) is True, (
                "TC-EXTRACT-C15: M-INTEG failed to verify a span the extractor "
                "legally emitted — the non-promise was not tolerated"
            )
        # Sufficiency is the PANEL's verdict, never derived from span completeness:
        # the panel said sufficient, so the flag is True under every variation.
        gate = IntegrityGate(
            world.store.cohort(ORCH_COHORT_ID), world.store.blobs(),
            ExtractionView(
                spans=(Span(start=s["start"], end=s["end"], text=s["text"])
                       for s in spans),
                panel=PanelFlags(evidence_sufficient=(True, True, True)),
            ),
        )
        signals = gate.verify(run_id, "SYN-001", "C1")
        assert signals.sufficiency_flag is True, (
            "TC-EXTRACT-C15: sufficiency was derived from the spans rather than "
            "judged by the panel — a consumer assumed completeness, which the "
            "clause does not promise"
        )
        # M-JUDGE assembles the panel's input from the spans as they came.
        arms = world.store.cohort(ORCH_COHORT_ID).query(
            "SELECT work_id, judge_id FROM work_unit WHERE run_id = :r "
            "AND stage = 'score' AND submission_id = :s AND criterion_id = :c",
            r=run_id, s="SYN-001", c="C1",
        )
        assembled = payload_bytes(Assemble(arms[0]))
        for span in spans:
            assert span["text"].encode("utf-8") in assembled, (
                "TC-EXTRACT-C15: the panel's assembled input dropped a legally "
                "emitted span"
            )
        # M-SYNTH renders without assuming order: every span's text renders.
        rendered = Synthesize(run_id, submission_id="SYN-001")
        rendered_text = rendered if isinstance(rendered, str) else str(rendered)
        for span in spans:
            assert span["text"] in rendered_text, (
                "TC-EXTRACT-C15: the render dropped a legally emitted span — a "
                "consumer assumed something about the spans the clause does not "
                "promise"
            )
    finally:
        world.close()


def test_tc_extract_c15_overlapping_spans_are_tolerated_downstream(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C15` variation 1 — two spans sharing bytes; every consumer takes
    them as they came."""
    _sweep(tmp_data_dir, make_fixture_provider, _spans_overlap())


def test_tc_extract_c15_out_of_order_spans_are_tolerated_downstream(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C15` variation 2 — the span list reversed; the render still
    carries every span's text."""
    _sweep(tmp_data_dir, make_fixture_provider, _spans_out_of_order())


def test_tc_extract_c15_non_minimal_spans_are_tolerated_downstream(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C15` variation 3 — a span extended past its sentence; no consumer
    shrinks or rejects it."""
    _sweep(tmp_data_dir, make_fixture_provider, _spans_non_minimal())


def test_tc_extract_c15_incomplete_spans_do_not_flip_sufficiency(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C15` variation 4 — one sentence covered; sufficiency stays the
    panel's verdict."""
    _sweep(tmp_data_dir, make_fixture_provider, _spans_incomplete())
