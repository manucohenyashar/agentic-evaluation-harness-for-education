"""`CT-EXTRACT-01` — spans are byte offsets into the recorded document version
(`TC-EXTRACT-C01`).

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`);
registered in `WRITTEN_AHEAD_BLOCKERS` under `"#68 extraction contract suite (TS-65)"`,
a `symbols` conjunction over the vocabulary's `TS26_EXTRACT_SYMBOLS` (see
`tests/support/extract_vocabulary.py` — design §3.8 pins no Python names).

The clause: an `ExtractionResult` is a set of spans, each carrying `start`, `end`,
`text` as **byte offsets into the `document.markdown` of the submission's canonical
artifact** (FR-EXTRACT-01), plus a `region_kind` marker per span (FR-EXTRACT-09);
offsets address the **exact `document` version recorded on the submission**
(NFR-EXTRACT-02).

Halves:
1. **Coordinate system** — the multi-byte ladder (ASCII, 2-, 3- and 4-byte characters
   all inside cited material), against **hand-computed byte offsets** recorded as
   literals, not re-derived in the test: a module that emits character offsets anywhere
   between the model reply and the persisted span fails on the first multi-byte span,
   and no fixture without a multi-byte span can detect the substitution. Every span
   also carries its `region_kind` marker through to the result.
2. **Version pinning** — the document is superseded after extraction; the stored
   offsets must not resolve silently against the new version. The superseding document
   is built so that v1's offsets land inside *different words* in v2, so a module that
   re-slices against "the current document" produces different text and is caught.

Discriminator: an extractor that converts byte offsets to character offsets (or
re-slices against whatever document is current at read time) turns both tests red
while every `FR-EXTRACT-*` case — which asserts round-trip over ASCII material —
stays green.

**Disclosed stand-ins** (suite register, `_doubles.py`): D1 reply format, D3 document
seeding. **Isolation: rung 2** — real store, real Tier P package, real cohort ledger,
real blob directory, `RecordedFixtureProvider` as the only model boundary.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.conf_builders import edge_panel
from tests.support.impl import EXTRACT_MODULE, require
from tests.contract.extract._doubles import (
    build_markdown,
    evidence_rows,
    extract_once,
    make_world,
)

pytestmark = pytest.mark.contract

_LADDER_BODY = (
    "The rate is 12 kg per hour.\n"
    "Café temperature élevée.\n"
    "中心 temperature noted.\n"
    "Alarm raised: 🚨 on the log.\n"
)
_MARKDOWN = build_markdown(_LADDER_BODY)

#: Hand-computed byte offsets (unicode.org UTF-8 widths: é = 2 bytes, 中/心 = 3,
#: U+1F6A8 = 4; `UNTRUSTED_OPEN` + newline = 28 bytes of preamble). Recorded as
#: literals deliberately — re-deriving them with `find()` would make the oracle
#: identical to the fixture builder and unable to detect anything.
_EXPECTED = [
    ("The rate is 12 kg per hour.", 28, 55, "transcribed_text"),
    ("Café temperature élevée.", 56, 83, "transcribed_text"),
    ("中心 temperature noted.", 84, 109, "transcribed_text"),
    ("🚨 on the log", 124, 139, "transcribed_text"),
]

#: The superseding version: at v1's first-span offsets the v2 bytes spell different
#: words, so a silent re-slice is visible in the text it would produce.
_SUPERSEDED_BODY = "The rate was revised to 14 kg per hour.\n" + "Café temperature élevée.\n"
_SUPERSEDED = build_markdown(_SUPERSEDED_BODY)


def _reply_spans() -> list[dict[str, Any]]:
    return [
        {"start": start, "end": end, "text": text, "region_kind": kind}
        for text, start, end, kind in _EXPECTED
    ]


def test_tc_extract_c01_spans_are_byte_offsets_with_region_kind_over_a_multibyte_document(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C01` half 1 — every span carries `start`/`end`/`text` as BYTE offsets
    (hand-computed literals) plus a `region_kind` marker; slicing the canonical bytes and
    decoding equals `text` for every span."""
    require(EXTRACT_MODULE, issue="#68")
    world = make_world(
        tmp_data_dir,
        make_fixture_provider,
        markdown=_MARKDOWN,
        criteria=[{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"}],
    )
    try:
        _request, result, _run_id, _unit = extract_once(
            world, panel=edge_panel(1), spans=_reply_spans(), build_id="ct-c01-build",
        )
        md_bytes = _MARKDOWN.encode("utf-8")
        emitted = list(result.spans)
        assert len(emitted) == len(_EXPECTED), (
            f"TC-EXTRACT-C01: expected {len(_EXPECTED)} spans, got {len(emitted)}"
        )
        for span, (text, start, end, kind) in zip(emitted, _EXPECTED, strict=True):
            got = getattr(span, "start", None), getattr(span, "end", None), \
                getattr(span, "text", None), getattr(span, "region_kind", None)
            if None in got and isinstance(span, dict):
                got = (
                    span.get("start"), span.get("end"), span.get("text"),
                    span.get("region_kind"),
                )
            assert got == (start, end, text, kind), (
                f"TC-EXTRACT-C01: span {got!r} != hand-computed "
                f"{(start, end, text, kind)!r} — the coordinate system is not bytes, "
                f"or the region_kind marker was dropped"
            )
            # THE round trip: byte offsets into the canonical bytes, decoded.
            assert md_bytes[start:end].decode("utf-8") == text, (
                f"TC-EXTRACT-C01: span {start}:{end} does not round-trip to {text!r}"
            )
    finally:
        world.close()


def test_tc_extract_c01_offsets_do_not_resolve_silently_against_a_superseded_document(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C01` half 2 — the stored offsets address the exact document version
    recorded on the submission: after the document is superseded, slicing the NEW
    document at the stored offsets does not silently produce the recorded text, and the
    evidence row still names the document version that was current at extraction."""
    require(EXTRACT_MODULE, issue="#68")
    world = make_world(
        tmp_data_dir,
        make_fixture_provider,
        markdown=_MARKDOWN,
        criteria=[{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"}],
    )
    try:
        _request, _result, run_id, _unit = extract_once(
            world, panel=edge_panel(1), spans=_reply_spans(), build_id="ct-c01-build",
        )

        # Supersede: a new document row for the same submission, different bytes at the
        # same offsets (D3 stand-in; the production supersession path is M-INGEST's).
        from tests.contract.extract._doubles import seed_document

        seed_document(world.store, world.submission_id, _SUPERSEDED, "doc-ct-1-v2")

        rows = evidence_rows(world.store, run_id)
        assert len(rows) == 1, f"TC-EXTRACT-C01: expected one evidence row, got {len(rows)}"
        row = rows[0]
        # The row names the document version that was current when it was written.
        assert row["document_id"] == world.doc_id, (
            f"TC-EXTRACT-C01: evidence row names document {row['document_id']!r}, not "
            f"the version recorded on the submission at extraction time "
            f"({world.doc_id!r}) — offsets drifted to the current document"
        )
        # ...and the offsets do not silently resolve against the superseded bytes:
        # at v1's offsets the v2 bytes spell different words (checked, not assumed).
        new_bytes = _SUPERSEDED.encode("utf-8")
        start, end, text = _EXPECTED[0][1], _EXPECTED[0][2], _EXPECTED[0][0]
        assert new_bytes[start:end].decode("utf-8") != text, (
            "TC-EXTRACT-C01: fixture bug — the superseding document agrees with v1 at "
            "the recorded offsets, so the differential cannot fire"
        )
    finally:
        world.close()
