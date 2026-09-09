"""`CT-EXTRACT-05` — every evidence row carries the RESOLVED build identity
(`TC-EXTRACT-C05`).

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`);
registered in `WRITTEN_AHEAD_BLOCKERS` under `"#68 extraction contract suite (TS-65)"`.

The clause: every `evidence` row carries the extractor's **resolved** build identity
(FR-EXTRACT-05), so evidence produced by two builds is distinguishable in stored data.

Halves:
1. **Resolved, not requested** — the case runs under a build-substitution fixture (the
   requested `ModelRef.build_id` and the provider's `resolved_build` disagree, which is
   exactly what `FR-PROV-04` defines `resolved_build` against: the build that actually
   answered) and asserts the row records what actually ANSWERED. A row that echoed the
   request-time identity is the violation.
2. **Distinguishable from stored data alone** — two runs over the same submission whose
   completions were answered by two builds produce two rows whose build identities
   differ while every other stored dimension is identical. That is what lets `M-STATS`
   scope a validity claim to a build: the build is the discriminating column, from the
   store, with no replay.

Discriminator: echoing the requested build (or omitting the column) turns half 1 red;
folding the build into a run-level constant (or dropping it from the row) turns half 2
red — while every `FR-EXTRACT-*` case, which never substitutes a build, stays green.

**Disclosed stand-ins** (suite register, `_doubles.py`): D1 (the reply's
`resolved_build` is what the fixture provider reports back), D3 (document seeding);
the evidence row's build column is read as `resolved_build`, the TS-26 row bet recorded
in the vocabulary. **Isolation: rung 2** — real store, real package, real blob
directory, `RecordedFixtureProvider` at the model boundary.
"""

from __future__ import annotations

import pytest

from tests.support.impl import EXTRACT_MODULE, require
from tests.contract.extract._doubles import (
    build_markdown,
    evidence_rows,
    extract_once,
    make_world,
    payload_bytes,
    require_extract_surface,
)

pytestmark = pytest.mark.contract

_MARKDOWN = build_markdown(
    "The second trial reproduced the first within tolerance.\n"
)
_SPANS = [
    {"start": 41, "end": 91, "text": "The second trial reproduced the first within "
     "tolerance.", "region_kind": "transcribed_text"},
]
_CRITERIA = [{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"}]


def test_tc_extract_c05_the_row_records_the_build_that_actually_answered(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C05` half 1 — under a build-substitution fixture, the evidence row's
    build identity equals the provider's resolved build, never the requested one."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        requested_build = "/models/qwen3-30b-a3b.gguf@sha256:eeee"  # the vocabulary's default ref
        answered_build = "/models/qwen3-30b-a3b.gguf@sha256:ffff"
        assert requested_build != answered_build, "fixture bug: no substitution"
        _request, result, run_id, _unit = extract_once(
            world, spans=_SPANS, build_id=answered_build,
        )

        # The result reports what answered: the result type's `extractor` member is the
        # RESOLVED build identity (the vocabulary's split — `extractor` on the result,
        # `resolved_build` on the evidence row column; FR-PROV-04's rule).
        assert getattr(result, "extractor", None) == answered_build, (
            "TC-EXTRACT-C05: the result does not report the build that actually "
            "answered — its `extractor` member is not the resolved build"
        )
        rows = evidence_rows(world.store, run_id)
        assert len(rows) == 1, f"TC-EXTRACT-C05: expected one row, got {len(rows)}"
        assert rows[0]["resolved_build"] == answered_build, (
            f"TC-EXTRACT-C05: the row records {rows[0]['resolved_build']!r} but the "
            f"build that actually answered was {answered_build!r} — the requested "
            f"identity was stored, which is the substitution the clause forbids"
        )
    finally:
        world.close()


def test_tc_extract_c05_evidence_from_two_builds_is_distinguishable_from_stored_data(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C05` half 2 — same submission, same spans, two answering builds: the
    two rows differ in build identity and in NOTHING else stored."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        _r1, _res1, run_a, _u1 = extract_once(
            world, spans=_SPANS, build_id="/models/qwen3-30b-a3b.gguf@sha256:aaaa",
        )
        _r2, _res2, run_b, _u2 = extract_once(
            world, spans=_SPANS, build_id="/models/qwen3-30b-a3b.gguf@sha256:bbbb",
        )
        rows_a, rows_b = evidence_rows(world.store, run_a), evidence_rows(world.store, run_b)
        assert len(rows_a) == len(rows_b) == 1, (
            "TC-EXTRACT-C05: expected exactly one row per run"
        )
        assert rows_a[0]["resolved_build"] != rows_b[0]["resolved_build"], (
            "TC-EXTRACT-C05: two runs answered by different builds are not "
            "distinguishable in stored data — M-STATS cannot scope a validity claim "
            "to a build"
        )
        # The build is the ONLY differing stored dimension (same submission, same
        # spans, same document): anything else that differs leaked run context into
        # the payload.
        assert payload_bytes(rows_a[0]["payload"]) == payload_bytes(rows_b[0]["payload"]), (
            "TC-EXTRACT-C05: the payloads differ between two runs over the same "
            "submission — run-level context leaked into the span payload, so the "
            "build is not the only thing distinguishing the rows"
        )
    finally:
        world.close()
