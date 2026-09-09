"""`CT-EXTRACT-02` — the result schema has nowhere for a judgment to live
(`TC-EXTRACT-C02`).

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`);
registered in `WRITTEN_AHEAD_BLOCKERS` under `"#68 extraction contract suite (TS-65)"`.

The clause: the result schema contains **no** band, points, score, confidence, or
quality field, and no such field will be added. A consumer cannot obtain a judgment
from this module because there is nowhere for one to live (§7.2, R19).

This is a **schema assertion, not a behavioural one** — the plan's own point is that it
is stronger and cheaper than sampling outputs. Two oracles:

1. **Field-set equality** against the declared schema (`RESULT_FIELDS`, HLD §9.9
   verbatim): an *added* field fails the build, not merely a forbidden-named one. Set
   equality, not subset — "no forbidden field present" would admit a `quality_flags`
   sneaking in beside the declared four. Field ORDER is asserted too: §9.9 declares the
   wire shape in order.
2. **No judgment-capable field anywhere on the exchange surface** — every declared
   field name (result, span element, request) is swept for the judgment vocabulary. The
   span element's schema is resolved through the pure `parse_spans` reply→spans
   conversion the vocabulary declares, fed a reply whose span smuggles judgment fields;
   what comes out may not carry them.

Discriminator: adding a `band` or `quality` field to `ExtractionResult` (or to the
span element type) turns this red while every `FR-EXTRACT-*` behavioural case stays
green — those cases never enumerate the schema.

**Disclosed stand-ins** (suite register, `_doubles.py`): D8 declares the schemas this
asserts against. **Isolation: rung 0** — pure type inspection, no store, no provider,
no doubles beyond the declared vocabulary.
"""

from __future__ import annotations

import dataclasses

import pytest

from tests.support.extract_vocabulary import (
    REQUEST_FIELDS,
    RESULT_FIELDS,
    RESULT_TYPE,
    SPAN_FIELDS,
    SPAN_PARSE,
)
from tests.support.impl import EXTRACT_MODULE, require
from tests.contract.extract._doubles import judgment_fields, require_extract_surface

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]


def test_tc_extract_c02_result_schema_is_exactly_the_declared_fields():
    """`TC-EXTRACT-C02` — `ExtractionResult`'s fields equal the declared schema exactly:
    no band, points, score, confidence or quality field exists, and none can be added
    without failing this build."""
    ExtractionResult = require(EXTRACT_MODULE, RESULT_TYPE, issue="#68")
    require_extract_surface()
    names = [f.name for f in dataclasses.fields(ExtractionResult)]
    assert set(names) == set(RESULT_FIELDS), (
        f"TC-EXTRACT-C02: ExtractionResult fields {sorted(names)} != the declared "
        f"schema {sorted(RESULT_FIELDS)} — an added field is the clause's violation "
        f"even when it looks harmless"
    )
    assert names == list(RESULT_FIELDS), (
        f"TC-EXTRACT-C02: field order moved: {names} vs {list(RESULT_FIELDS)} — "
        f"§9.9 declares the wire shape in order"
    )
    assert judgment_fields(names) == [], (
        f"TC-EXTRACT-C02: judgment vocabulary in the result schema: "
        f"{judgment_fields(names)}"
    )


def test_tc_extract_c02_no_judgment_field_on_the_span_element():
    """`TC-EXTRACT-C02` — the span element carries exactly `start`/`end`/`text`/
    `region_kind` and no judgment-capable field: the marker is the only classification
    the schema permits, one level down."""
    SpanParse = require(EXTRACT_MODULE, SPAN_PARSE, issue="#68")
    require_extract_surface()
    # A reply whose span smuggles judgment fields; the parse is where a bounds violation
    # is refused (NFR-EXTRACT-02), so it is also where a judgment field must be refused
    # or dropped — the parsed span may not expose one.
    reply = (
        '{"spans": [{"start": 0, "end": 4, "text": "abcd", "region_kind": '
        '"transcribed_text", "band": "secure", "confidence": 0.9}]}'
    )
    (span,) = list(SpanParse(reply))
    if dataclasses.is_dataclass(span) and not isinstance(span, type):
        span_names = [f.name for f in dataclasses.fields(span)]
    elif hasattr(span, "keys"):
        span_names = list(span.keys())
    elif hasattr(span, "__dict__"):
        span_names = sorted(vars(span))
    else:
        span_names = [a for a in dir(span) if not a.startswith("_")]
    assert set(span_names) == set(SPAN_FIELDS), (
        f"TC-EXTRACT-C02: span fields {sorted(span_names)} != declared "
        f"{sorted(SPAN_FIELDS)} — a judgment field on the span element is the same "
        f"violation one level down"
    )
    assert judgment_fields(span_names) == [], (
        f"TC-EXTRACT-C02: judgment vocabulary in the span schema: "
        f"{judgment_fields(span_names)}"
    )


def test_tc_extract_c02_no_judgment_field_anywhere_in_the_declared_exchange_schema():
    """`TC-EXTRACT-C02` — the judgment sweep covers the module's whole declared exchange
    surface (result and request together): there is no field a judgment could be
    written into, which is what makes the absence structural rather than inspected."""
    require_extract_surface()
    declared = sorted({*RESULT_FIELDS, *SPAN_FIELDS, *REQUEST_FIELDS})
    assert judgment_fields(declared) == [], (
        f"TC-EXTRACT-C02: judgment vocabulary in the declared exchange schema: "
        f"{judgment_fields(declared)}"
    )
    # Vacuity guard: the sweep must be able to fire at all.
    assert judgment_fields(["band", "self_confidence", "quality_score"]) == [
        "band", "self_confidence", "quality_score",
    ], "TC-EXTRACT-C02: the judgment sweep matches nothing — it is vacuous"
