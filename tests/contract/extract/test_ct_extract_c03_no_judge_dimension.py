"""`CT-EXTRACT-03` — evidence is keyed with no judge dimension (`TC-EXTRACT-C03`).

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`) and
#78 (`M-JUDGE`, the rung-3 half); registered in `WRITTEN_AHEAD_BLOCKERS` under
`"#68 extraction contract suite (TS-65)"` (rung-2 test) and `"#78 extraction contract
suite (TS-65)"` (rung-3 test, node ID — the file mixes blockers).

The clause: `evidence` is keyed by `(run_id, submission_id, criterion_id)` with **no
judge dimension** (FR-EXTRACT-02). Every judge on a panel therefore reads
byte-identical evidence — this is what makes panel disagreement mean disagreement
about the rubric rather than about the input.

Halves:
1. **Keying, rung 2** — a three-judge panel really enumerates three score arms with
   distinct `judge_id`s, yet exactly ONE evidence row exists for the triple; the
   evidence table carries no judge-named column under any spelling; and a second write
   from another worker instance (the "two judges wrote" construction) does not produce
   a second row — the key is the triple, not the writer.
2. **Byte-identity across the panel, rung 3** — with `M-JUDGE` real, each judge's
   assembled scoring request carries the SAME evidence bytes. A per-judge evidence
   dimension would make disagreement mean disagreement about the *input*, silently
   destroying every agreement statistic the system reports — the byte-identity
   differential is what catches that.

Discriminator: giving `evidence` a judge dimension (a column, or a row per judge)
turns half 1 red; making the evidence bytes judge- or panel-dependent turns half 2
red — while every `FR-EXTRACT-*` case, which drives one judge, stays green.

**Disclosed stand-ins** (suite register, `_doubles.py`): D1, D3, and D6 — half 2
resolves `ScoringWorker` / the store-reading `assemble(unit)` under #78's issue number
(the `JUDGE_MODULE:ScoringWorker` registry precedent; no new symbol invented).
**Isolation**: rung 2 (half 1) / rung 3 (half 2) — real store, real package, real
panel enumeration through the shipped `Orchestrator`, `RecordedFixtureProvider` at the
model boundary.
"""

from __future__ import annotations

import pytest

from tests.support.conf_builders import edge_panel
from tests.support.impl import EXTRACT_MODULE, JUDGE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID
from tests.support.impl import JUDGE_MODULE, require
from tests.contract.extract._doubles import (
    build_markdown,
    evidence_rows,
    extract_once,
    make_world,
    payload_bytes,
    require_extract_surface,
)

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

_MARKDOWN = build_markdown(
    "The apparatus was levelled before the first measurement.\n"
    "Three trials were recorded, the third discarded.\n"
)


def test_tc_extract_c03_one_row_for_the_triple_no_judge_dimension_in_the_schema(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C03` half 1 — three score arms with distinct judge_ids, ONE evidence
    row for the (run, submission, criterion) triple; no judge column under any name;
    and a second writer still leaves one row."""
    require(EXTRACT_MODULE, issue="#68")
    world = make_world(
        tmp_data_dir,
        make_fixture_provider,
        markdown=_MARKDOWN,
        criteria=[{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"}],
    )
    try:
        spans = [
            {"start": 41, "end": 91, "text": "The apparatus was levelled before the first "
             "measurement.", "region_kind": "transcribed_text"},
        ]
        _request, _result, run_id, _unit = extract_once(
            world, panel=edge_panel(3), spans=spans, build_id="ct-c03-build",
        )

        # The panel is real: three score arms, three distinct judge_ids.
        arms = world.store.cohort(ORCH_COHORT_ID).query(
            "SELECT judge_id FROM work_unit WHERE run_id = :r AND stage = 'score' "
            "AND submission_id = :s AND criterion_id = :c ORDER BY judge_id",
            r=run_id, s="SYN-001", c="C1",
        )
        assert len(arms) == 3, (
            f"TC-EXTRACT-C03: precondition — expected 3 score arms, got {len(arms)}"
        )
        assert len({a["judge_id"] for a in arms}) == 3, (
            "TC-EXTRACT-C03: precondition — the panel's judge_ids are not distinct"
        )

        # ...yet the evidence for the triple is ONE row, judgeless.
        rows = evidence_rows(world.store, run_id)
        assert len(rows) == 1, (
            f"TC-EXTRACT-C03: evidence must be one row per (run, submission, "
            f"criterion), got {len(rows)} — a row per judge is the keying this clause "
            f"forbids"
        )
        assert rows[0]["judge_id"] is None, (
            "TC-EXTRACT-C03: the extract unit carries a judge_id — the judge "
            "dimension leaked into extraction"
        )
        columns = [
            r["name"]
            for r in world.store.cohort(ORCH_COHORT_ID).query(
                "PRAGMA table_info(evidence)"
            )
        ]
        assert not [c for c in columns if "judge" in c.lower()], (
            f"TC-EXTRACT-C03: evidence carries a judge dimension: {columns}"
        )

        # A second writer (another worker instance over the same unit) does not create
        # a second row — the key is the triple, not the writer. Whether #68's worker
        # upserts or refuses the second write, the row count may not move.
        Worker = require(EXTRACT_MODULE, "ExtractionWorker", issue="#68")
        from tests.support.extract_vocabulary import extractor_ref

        try:
            Worker(world.store, world.provider, extractor_ref()).process(_unit)
        except Exception:
            pass  # a refusal is as good as an upsert; only a SECOND ROW is the violation
        rows_after = evidence_rows(world.store, run_id)
        assert len(rows_after) == 1, (
            f"TC-EXTRACT-C03: a second write produced {len(rows_after)} rows — the "
            f"keying admits a second row for the same triple"
        )
    finally:
        world.close()


def test_tc_extract_c03_every_judge_on_the_panel_reads_byte_identical_evidence(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C03` half 2, rung 3 — with `M-JUDGE` real, the evidence bytes inside
    each judge's assembled scoring request are identical across the panel: the
    differential that keeps disagreement about the rubric, not about the input."""
    require(JUDGE_MODULE, "ScoringWorker", "assemble", issue="#78")
    require_extract_surface()
    world = make_world(
        tmp_data_dir,
        make_fixture_provider,
        markdown=_MARKDOWN,
        criteria=[{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"}],
    )
    try:
        spans = [
            {"start": 41, "end": 91, "text": "The apparatus was levelled before the first "
             "measurement.", "region_kind": "transcribed_text"},
        ]
        _request, _result, run_id, _unit = extract_once(
            world, panel=edge_panel(3), spans=spans, build_id="ct-c03-build",
        )
        Assemble = require(JUDGE_MODULE, "assemble", issue="#78")
        payloads = []
        arms = world.store.cohort(ORCH_COHORT_ID).query(
            "SELECT work_id, judge_id FROM work_unit WHERE run_id = :r "
            "AND stage = 'score' AND submission_id = :s AND criterion_id = :c "
            "ORDER BY judge_id",
            r=run_id, s="SYN-001", c="C1",
        )
        assert len(arms) == 3, (
            f"TC-EXTRACT-C03: precondition — expected 3 score arms, got {len(arms)}"
        )
        for arm in arms:
            scoring_request = Assemble(arm)
            payloads.append(payload_bytes(scoring_request))
        assert len({p for p in payloads}) == 1, (
            "TC-EXTRACT-C03: the panel's judges were handed DIFFERENT evidence bytes — "
            "a per-judge evidence dimension is the violation, and it destroys every "
            "agreement statistic the system reports"
        )
    finally:
        world.close()
