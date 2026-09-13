"""`TS-80` (issue #153) — `Requires` pairwise integration into **`M-EXTRACT`**, **`M-JUDGE`** and
**`M-INTEG`**: the consumers of extracted evidence, judge verdicts and integrity signals, checked
against the real modules over a real run (rung 3).

These three providers' rows share one world, a real run driven through real extraction and
scoring (`tests/contract/judge/_drive.py`), so they share one file. Each test names its provider.

| Case | Consumer → provider | Assumption checked here |
|---|---|---|
| TC-REQ-23 | `M-INTEG` → `M-EXTRACT` | integrity tolerates spans that are unordered, overlapping and repeated; evidence has no judge dimension |
| TC-REQ-29 | `M-JUDGE` → `M-EXTRACT` | a quarantined extraction is distinguishable from an empty one at M-JUDGE's input |
| TC-REQ-46 | `M-SYNTH` → `M-EXTRACT` | the spans synthesis cites are the bytes the panel received |
| TC-REQ-25 | `M-INTEG` → `M-JUDGE` | `evidence_sufficient` is on every verdict, uncited ones included |
| TC-REQ-36 | `M-AGG` → `M-JUDGE` | no verdict carries points; aggregation derives them from the band |
| TC-REQ-37 | `M-AGG` → `M-INTEG` | aggregation treats `None` (not measured) differently from `False`, and a missing signal as adverse |

Markers: `contract` and `integration` (§4.7).
"""

from __future__ import annotations

import json
import random

import pytest

from aeh.store import open_store
from tests.contract.judge import _drive
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = [pytest.mark.contract, pytest.mark.integration]


def _provider(tmp_data_dir):
    from aeh.prov import RecordedFixtureProvider

    return RecordedFixtureProvider(fixture_dir=tmp_data_dir / "fixtures")


def test_tc_req_23_integrity_tolerates_the_span_properties_extraction_disclaims(tmp_data_dir):
    """`TC-REQ-23` (`M-INTEG` → `M-EXTRACT`, CT-EXTRACT-01/03/09/10/15): the spans real extraction
    wrote for a cell are handed to the real `IntegrityGate` three ways: as written, reversed with
    a duplicate, and with an overlapping sub-span added. CT-EXTRACT-15 disclaims ordering and
    non-overlap, and the gate's six signals are identical in all three. The evidence table has no
    judge column, so one verification covers the whole panel."""
    from aeh.integ import IntegrityGate
    from aeh.judge import _evidence_spans
    from tests.support.integ_vocabulary import ExtractionView, PanelFlags, Span

    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _v = _drive.seed_world(store)
        _drive.drive_extract(orchestrator, store, _provider(tmp_data_dir))
        handle = store.cohort(ORCH_COHORT_ID)
        written = [Span(start=s["start"], end=s["end"], text=s["text"])
                   for s in _evidence_spans(handle, run_id, "SYN-001", "C1")]
        first = written[0]
        overlapping = Span(start=first.start + 4, end=first.end,
                           text=first.text[4:] if isinstance(first.text, str) else first.text)
        variants = {
            "as written": written,
            "reversed with a duplicate": list(reversed(written)) + [first],
            "with an overlapping sub-span": written + [overlapping],
        }
        signals = {}
        for name, spans in variants.items():
            gate = IntegrityGate(handle, store.blobs(), ExtractionView(spans=spans, panel=PanelFlags()),
                                 ocr_conf_floor=0.70)
            s = gate.verify(run_id, "SYN-001", "C1")
            signals[name] = (s.spans_verified, s.evidence_present, s.ocr_overlap_risk,
                             s.described_evidence)
        evidence_columns = {r["name"] for r in handle.query("SELECT name FROM pragma_table_info('evidence')")}
    finally:
        store.close()
    assert written, "fixture: extraction wrote no spans"
    assert signals["as written"][0] is True, f"fixture: the written spans did not verify: {signals}"
    assert len(set(signals.values())) == 1, f"the gate's signals depend on span order or overlap: {signals}"
    assert not {c for c in evidence_columns if "judge" in c}, f"evidence carries a judge dimension: {evidence_columns}"


def test_tc_req_29_a_quarantined_extraction_is_not_an_empty_one_at_the_judge(tmp_data_dir):
    """`TC-REQ-29` (`M-JUDGE` → `M-EXTRACT`, CT-EXTRACT-01/03/08), the RISK-03 boundary: in one run,
    SYN-001's extraction completes with no spans, and SYN-002's extraction fails until it is
    quarantined. The empty extraction reaches M-JUDGE as score units whose request carries an empty
    evidence set. The quarantined one never reaches M-JUDGE: no score unit for that cell is handed
    out. A failure therefore cannot arrive looking like a blank answer."""
    from aeh.extract import ExtractionWorker, assemble_request, prompt_fields
    from aeh.judge import ScoringWorker
    from aeh.orch import STAGE_EXTRACT, WorkError
    from tests.support.extract_vocabulary import extractor_ref, sampling_params, span_completion

    store = open_store(tmp_data_dir)
    try:
        provider = _provider(tmp_data_dir)
        orchestrator, _run, _v = _drive.seed_world(store, submissions=("SYN-001", "SYN-002"))
        worker = ExtractionWorker(store, provider, extractor_ref())
        for _ in range(8):
            batch = orchestrator.lease("w-req-29", STAGE_EXTRACT, 8)
            if not batch:
                break
            for unit in batch:
                if unit.submission_id == "SYN-001":
                    provider.record(prompt_fields(assemble_request(unit, store=store)), extractor_ref(),
                                    sampling_params(), span_completion([], build_id="build-req-29"))
                    worker.process(unit)
                else:
                    orchestrator.fail(unit.work_id, WorkError(message="injected extraction failure"))
        statuses = {r["submission_id"]: r["status"] for r in store.cohort(ORCH_COHORT_ID).query(
            "SELECT submission_id, status FROM work_unit WHERE stage = 'extract'")}
        score_units = _drive.lease_score_units(orchestrator)
        refs = {r.build_id: r for r in _drive.PANEL_REFS}
        empty_requests = [ScoringWorker(store, provider, refs[u.judge]).assemble(u)
                          for u in score_units if u.submission_id == "SYN-001"]
    finally:
        store.close()
    assert statuses == {"SYN-001": "done", "SYN-002": "quarantined"}, f"fixture: extract statuses {statuses}"
    assert {u.submission_id for u in score_units} == {"SYN-001"}, (
        f"a quarantined extraction's cell reached M-JUDGE: {sorted({u.submission_id for u in score_units})}")
    assert empty_requests, "the empty extraction's cell never reached M-JUDGE"


def test_tc_req_46_synthesis_cites_the_bytes_the_panel_received(tmp_data_dir):
    """`TC-REQ-46` (`M-SYNTH` → `M-EXTRACT`, CT-EXTRACT-01/03): for each scored criterion of a
    five-question submission, the evidence text M-JUDGE reads for the cell (`_evidence_spans`,
    the panel's view) appears byte for byte in the prompt M-SYNTH dispatches for that question.
    A narrative therefore cites what the panel saw."""
    from aeh.synth import SynthesisWorker
    from tests.support.orch_run import seed_run
    from tests.support.synth_vocabulary import (
        COHORT_ID,
        FIVE_QUESTION_CRITERIA,
        CaptureProvider,
        narrative_completion,
        seed_scored_submission,
        synth_ref,
    )

    questions = tuple(f"Q{q}" for q in range(1, 6))
    replies = [narrative_completion(f"Question {q[1:]}: the response states its reasoning.",
                                    (f"{q}C1", f"{q}C2")) for q in questions]
    replies.append(narrative_completion("Overall: each complete question is addressed in turn."))
    store = open_store(tmp_data_dir)
    try:
        _orch, run_id, _v = seed_run(store, submissions=("SYN-001",), criteria=FIVE_QUESTION_CRITERIA)
        seed_scored_submission(store, run_id, "SYN-001", complete_questions=set(questions))
        handle = store.cohort(COHORT_ID)
        # Give each evidence row M-EXTRACT's persisted payload: byte-offset spans into the
        # submission's canonical document, the shape the panel's requests are built from.
        doc = handle.query("SELECT document_id, markdown FROM document WHERE submission_id = 'SYN-001'")[0]
        raw = doc["markdown"].encode("utf-8")
        panel_view = {}
        rows = handle.query("SELECT e.evidence_id, w.criterion_id FROM evidence e "
                            "JOIN work_unit w ON w.work_id = e.work_id WHERE w.run_id = :r", r=run_id)
        with handle.transaction() as tx:
            for row in rows:
                question = row["criterion_id"][:2]
                needle = f"the student's own work for question {question}".encode("utf-8")
                at = raw.find(needle)
                span = {"start": at, "end": at + len(needle), "text": needle.decode("utf-8")}
                tx.execute("UPDATE evidence SET payload = :p WHERE evidence_id = :e",
                           p=json.dumps({"spans": [span]}).encode("utf-8"), e=row["evidence_id"])
                panel_view.setdefault(row["criterion_id"], []).append(span["text"])
        provider = CaptureProvider(replies)
        SynthesisWorker(store, provider, synth_ref()).synthesize_submission(run_id, "SYN-001")
    finally:
        store.close()
    dispatched = [json.dumps(dict(p.fields) if hasattr(p, "fields") else p, default=str) for p in provider.prompts]
    missing = {cid: text for cid, texts in panel_view.items() for text in texts
               if not any(json.dumps(text)[1:-1] in d for d in dispatched)}
    assert any(panel_view.values()), "fixture: the panel view holds no evidence"
    assert not missing, f"evidence the panel received is absent from synthesis prompts: {missing}"
    # Each question's L1 prompt carries its own spans and no other question's: the prompt is
    # built from the persisted spans, not from the whole document (which holds all of them).
    needles = {q: f"the student's own work for question {q}" for q in questions}
    l1 = [d for d in dispatched if sum(n in d for n in needles.values()) >= 1][:len(questions)]
    crossed = [d[:80] for d in l1 if sum(n in d for n in needles.values()) != 1]
    assert len(l1) == len(questions) and not crossed, (
        f"an L1 prompt carries more than its own question's evidence: {crossed}")


def test_tc_req_25_every_verdict_reports_evidence_sufficiency_uncited_ones_included(tmp_data_dir):
    """`TC-REQ-25` (`M-INTEG` → `M-JUDGE`, CT-JUDGE-06): a run judged with uncited verdicts (the
    replies cite no span). Every stored verdict carries a non-null `evidence_sufficient`, and each
    is marked `uncited`. FR-INTEG-07 therefore has its per-verdict input even when nothing was
    cited."""
    store = open_store(tmp_data_dir)
    try:
        _orch, run_id, _v = _drive.drive_judged_run(store, _provider(tmp_data_dir), cited=False)
        rows = _drive.verdict_rows(store, run_id, "SYN-001", "C1",
                                   columns="v.evidence_sufficient, v.uncited")
    finally:
        store.close()
    assert rows, "fixture: no verdict was stored"
    assert all(r["evidence_sufficient"] is not None for r in rows), f"a verdict lacks the flag: {rows}"
    assert all(r["uncited"] for r in rows), f"fixture: the uncited verdicts are not marked: {rows}"


def test_tc_req_36_no_verdict_carries_points_and_aggregation_derives_them(tmp_data_dir):
    """`TC-REQ-36` (`M-AGG` → `M-JUDGE`, CT-JUDGE-04/06/07/18): the verdict table has no points
    column. Every stored verdict names a declared band with its ordinal. Aggregating the stored
    verdicts gives the points of the catalog's mapping for the aggregated band, and the same
    verdicts with a bogus `points` attribute attached aggregate to the same points: a verdict's
    points are never read."""
    from types import SimpleNamespace

    from aeh.agg import aggregate
    from tests.contract.agg import _drive as agg_drive
    from tests.support.agg_vocabulary import criterion, signals

    store = open_store(tmp_data_dir)
    try:
        _orch, run_id, _v = agg_drive.drive_scored_run(store, _provider(tmp_data_dir))
        handle = store.cohort(ORCH_COHORT_ID)
        columns = {r["name"] for r in handle.query("SELECT name FROM pragma_table_info('verdict')")}
        rows = agg_drive.stored_verdicts(store, run_id, "SYN-001", "C1")
        bands = agg_drive.criterion_bands(store, "C1")
    finally:
        store.close()
    crit = criterion(bands, scoring_model="atomic", criterion_id="C1")
    clean = aggregate(rows, crit, signals())
    poisoned = aggregate([SimpleNamespace(**{**vars(r), "points": 999.0}) if hasattr(r, "__dict__")
                          else r for r in rows], crit, signals())
    declared = {b["band"] if isinstance(b, dict) else getattr(b, "band", None) for b in bands}
    assert "points" not in columns, f"the verdict table carries points: {columns}"
    assert rows and all(getattr(r, "band", None) in declared for r in rows), "a verdict names an undeclared band"
    assert clean.points == poisoned.points != 999.0, (clean.points, poisoned.points)


def test_tc_req_37_aggregation_reads_none_as_not_measured_and_adverse():
    """`TC-REQ-37` (`M-AGG` → `M-INTEG`, CT-INTEG-02/03/11/15): M-INTEG's `None` means not
    measured, and M-AGG must consume it that way. With a unanimous panel, `extractor_disagreement =
    None` gives a different (lower) confidence than `False`, so `None` is not read as `False`.
    `spans_verified = None` and `evidence_present = None` are at least as adverse as their `False`
    values and strictly worse than `True`, so a missing signal is never favourable."""
    from aeh.agg import aggregate
    from tests.support.agg_vocabulary import agg_config, band, criterion, panel, signals

    crit = criterion([band("a", 0, 0.0), band("b", 1, 1.0), band("c", 2, 2.0), band("d", 3, 3.0)],
                     scoring_model="holistic", criterion_id="C1")
    rows = panel(("c", 2), ("c", 2), ("c", 2))
    conf = lambda **o: aggregate(rows, crit, signals(**o), config=agg_config()).confidence  # noqa: E731
    good = conf()
    problems = []
    if conf(extractor_disagreement=None) == conf(extractor_disagreement=False):
        problems.append("extractor_disagreement None is read the same as False")
    for name in ("spans_verified", "evidence_present"):
        missing, false = conf(**{name: None}), conf(**{name: False})
        if not (missing <= false and missing < good):
            problems.append(f"{name}=None is not adverse: None {missing}, False {false}, True {good}")
    assert not problems, "\n".join(problems)
