"""Issue #445 — the Jev corpora are committed and replayable with no network.

These are corpus self-checks, following the #435 precedent (`test_f_dev_pipe_corpus.py`). They
assert that each corpus carries what Jev test plan §4.4 says it carries, so the consuming
stories (TS-105, 106, 110, 117, 118, 119) can replay their cases from it. The TC-* cases
themselves belong to those stories.

| Corpus | Checked |
|---|---|
| F-JEV-WIRE | every body is labelled synthetic and validates (or fails) exactly as its `expect` says |
| F-JEV | 40 cells; both criteria; every band position; 0/1/3 spans; 4 adversarial; every recorded answer replays through `decide` and the gate |
| F-JEV-PERF | 350 x 6 |
| F-STATS-JEV | subsets of 60/25/19/59/60/60 plus 5 planted inadmissible labels; CAL25's 20/4/1 split |
| F-ADV-INJ-DECISION | 4 twin pairs, each benign twin the injected page minus its payload |
| F-SCHEMA Cohort-27 | version 27, pre-delta verdict rows, no decision tables |
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal

import pytest

from aeh.conf import DecisionEngine, ModelRef
from aeh.judge import Accepted, gate_decision
from aeh.prov import (HttpResponse, MalformedResponseError, RecordedFixtureProvider,
                      _decision_status_error, decision_request_key, parse_decision)
from aeh.stats import _is_admissible
from harness.corpora import adv_inj, jev
from harness.corpora.manifest import CORPUS_ROOT
from tests.support import jev_corpora


def _engine(provider: str) -> DecisionEngine:
    return DecisionEngine(
        model=ModelRef(role="decision", provider=provider,
                       build_id="/models/jev/model.safetensors@sha256:" + "ab" * 32, quantization="bf16"),
        confidence_threshold=Decimal("0.80"), cite_threshold=Decimal("0.50"),
        max_citation_questions=16, token_bytes_ratio=3)


def test_f_jev_wire_bodies_validate_exactly_as_labelled():
    bodies = jev_corpora.wire_bodies()
    assert len(bodies) >= 25
    for entry in bodies:
        assert entry["synthetic"] is True and "not a live capture" in entry["source"], entry["id"]
        request = jev_corpora.wire_request(entry["request"])
        expect = entry["expect"]
        if expect["outcome"] == "error":
            error = _decision_status_error(HttpResponse(entry["status"], entry["headers"],
                                                        json.dumps(entry["body"]).encode()))
            if expect["retried"]:
                # The shared retry loop owns these; past the budget they surface as
                # unavailability (CT-PROV-07), never as a status error.
                assert entry["status"] in (429, 500, 524, 529), entry["id"]
                assert expect["error_type"] == "ProviderUnavailableError", entry["id"]
            else:
                assert type(error).__name__ == expect["error_type"], entry["id"]
            if "sentinel" in expect:
                assert len(json.dumps(entry["body"]).encode()) >= expect["body_bytes"] - 50
                assert expect["sentinel"] in json.dumps(entry["body"])
            continue
        if expect["outcome"] == "malformed":
            with pytest.raises(MalformedResponseError):
                parse_decision(entry["body"], request, fallback_build="x")
            continue
        decision = parse_decision(entry["body"], request, fallback_build="x")
        if "confidence_source" in expect:
            assert decision.answers["band"].confidence_source == expect["confidence_source"]
        if "resolved_build" in expect:
            assert decision.resolved_build == expect["resolved_build"]
    ids = {b["id"] for b in bodies}
    assert {"cloud-status-429", "cloud-different-model", "cloud-accept-sum-1-0009"} <= ids
    for backend in jev.BACKENDS:  # TC-PROV-28: per status, for both providers
        assert {f"{backend}-status-{s}" for s in (400, 401, 402, 403, 422, 429, 500, 524, 529)} <= ids
        assert {f"{backend}-status-400-echo", f"{backend}-status-422-echo"} <= ids
    assert next(b for b in bodies if b["id"] == "cloud-status-429")["headers"]["retry-after"] == "2"


def test_f_jev_cells_cover_the_declared_shape_and_replay(tmp_path):
    requests = jev_corpora.f_jev_requests()
    cells = [cell for cell, _ in requests.values()]
    assert len(cells) >= 40
    for cid, n in (("J4", 4), ("J6", 6)):
        assert {c["reference_ordinal"] for c in cells if c["criterion_id"] == cid} == set(range(n))
    assert {len(c["spans"]) for c in cells} == {0, 1, 3}
    assert sorted(c["adversarial_kind"] for c in cells if c["kind"] == "adversarial") == sorted(
        adv_inj.DECISION_PATH_KINDS)
    for backend in jev.BACKENDS:
        engine = _engine("fixture")
        recorded = jev_corpora.record_f_jev(tmp_path / backend, backend, engine)
        # One recording per cell: two cells sharing a request would share a key, and the later
        # answer would silently overwrite the earlier one.
        assert len({decision_request_key(r, engine.model) for r in recorded.values()}) == len(recorded)
        provider = RecordedFixtureProvider(fixture_dir=tmp_path / backend)
        outcomes = {}
        for cell_id, (cell, scoring) in requests.items():
            decision = provider.decide(recorded[cell_id], engine.model)
            out = gate_decision(decision, scoring, engine)
            outcomes[cell_id] = "accepted" if isinstance(out, Accepted) else out.reason
        kinds = {c["cell_id"]: c["kind"] for c in cells}
        assert all(outcomes[i] == "below_threshold" for i, k in kinds.items() if k == "low_confidence")
        assert all(outcomes[i] == "accepted" for i, k in kinds.items()
                   if k == "graded" and requests[i][0]["spans"]), backend


def test_f_jev_perf_is_350_by_6():
    selection = json.loads((CORPUS_ROOT / "F-JEV-PERF" / "selection.json").read_text(encoding="utf-8"))
    assert len(selection["submission_ids"]) == 350 and len(selection["judged_criteria"]) == 6
    assert selection["cells"] == 2100


def test_f_stats_jev_subsets_and_planted_inadmissible_labels():
    sizes = {name: len(jev_corpora.stats_labels(name)) for name in jev.STATS_SUBSETS}
    assert sizes == {"D60": 60, "CAL25": 25, "CAL19": 19, "D59": 59, "F60": 60, "O60": 60, "X5": 5}
    planted = jev_corpora.stats_labels("X5")
    assert all(p.partition == "decision" and not _is_admissible(p) for p in planted)
    assert all(_is_admissible(l) for l in jev_corpora.stats_labels() if "X5" not in l.subsets)
    cal25 = jev_corpora.stats_labels("CAL25")
    gaps = [abs(l.system_band - l.teacher_band) for l in cal25]
    assert (gaps.count(0), gaps.count(1), gaps.count(2)) == (20, 4, 1)
    assert all(0.80 < l.band_confidence < 0.85 for l in cal25)
    assert all(0.85 <= l.band_confidence < 0.90 for l in jev_corpora.stats_labels("CAL19"))


def test_f_adv_inj_decision_pairs_are_twins():
    pairs = adv_inj.decision_path_pairs()
    assert [injected.injection_kind for _, injected in pairs] == list(adv_inj.DECISION_PATH_KINDS)
    for benign, injected in pairs:
        first = injected.pages[0].split("\n")
        assert "\n".join(first[: injected.payload_line]) == benign.pages[0]
        assert injected.pages[1:] == benign.pages[1:]
    manifest = json.loads((CORPUS_ROOT / "F-ADV-INJ-DECISION" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["pairs"] == 4 and len(manifest["submissions"]) == 8


def test_f_adv_inj_decision_answers_replay_with_the_injected_twin_taking_the_bait(tmp_path):
    engine = _engine("fixture")
    recorded = jev_corpora.record_adv_decisions(tmp_path, engine)
    provider = RecordedFixtureProvider(fixture_dir=tmp_path)
    assert len(recorded) == 8
    for member_id, (member, scoring, request) in recorded.items():
        decision = provider.decide(request, engine.model)
        band = decision.answers["band"]
        if member["variant"] == "injected":
            assert band.probabilities[-1] == pytest.approx(0.99), member_id
        assert [q.key for q in request.questions] == ["band", "evidence_sufficient", "cite_a", "cite_b"]


def test_f_schema_cohort_27_database_is_pre_delta(tmp_path):
    db = jev_corpora.cohort_27_database(tmp_path / "cohort.db")
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 27
        columns = {row[1] for row in con.execute("PRAGMA table_info(verdict)")}
        assert "scoring_engine" not in columns and "engine_build" not in columns
        assert con.execute("SELECT count(*) FROM verdict").fetchone()[0] >= 1
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "decision_prescreen" not in tables
    finally:
        con.close()
