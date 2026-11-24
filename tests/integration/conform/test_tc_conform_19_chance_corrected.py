"""Validity T14 (issue #911): TC-CONFORM-19 (FR-CONFORM-19, CT-CONFORM-18) — chance-corrected
conformance. Statistical-validity test plan §3.13.

| Arm | What is asserted |
|---|---|
| decision report | `run_decision_conformance` over 10 F-JEV J4 cells whose two backends' accepted bands are the 10-pair fixture below: per backend, `decision_band_agreement_by_criterion["J4"]` carries `pairs` 10, exact 0.6, adjacent 0.9, kappa 17/37 and ordinal alpha 0.7; `agreement_note` (row and report) is FR-CONFORM-19's sentence verbatim |
| live-acceptance report | `run_live_acceptance`'s report, its live edges stood down (gates, counting transports, the drive returns a seeded run), over a cohort holding the same 10 pairs as pre-screen probabilities and single-judge LLM verdicts, plus an 11th cell where the engine answers 1 and two judges answer 1 and 2 (median 1.5, adjacent, not exact): exact 6/11 and adjacent 10/11 count it, kappa and alpha do not (`decision_band_chance_corrected_n` 10) and equal the same literals; `LiveAcceptanceReport.agreement_note` is the sentence |

**The 10-pair fixture** (0-based band ordinals, K = 4 bands, side a / side b):

    (0,0) (0,0) (1,1) (1,1) (2,2) (2,3) (3,3) (1,2) (0,1) (3,1)

Hand computation (the formulas of `aeh.conform.agreement`'s docstring; nothing here calls the
code under test to get an expected value):

- exact: 6 of 10 equal → 0.6. adjacent: every pair but (3,1) is within one band → 0.9.
- kappa: side a's marginals 0:3 1:3 2:2 3:2 (of 10); side b's 0:2 1:4 2:2 3:2.
  pe = .3·.2 + .3·.4 + .2·.2 + .2·.2 = .26; kappa = (.6 − .26) / (1 − .26) = .34/.74 = 17/37.
- ordinal alpha (the repo's convention, expected disagreement spread evenly over the declared
  bands): D_o = mean |a − b| / 3 = (1+1+1+2) / 10 / 3 = 1/6; D_e = mean over the 12 ordered
  pairs of distinct bands of |i − j| / 3 = (20/12) / 3 = 5/9; alpha = 1 − (1/6)/(5/9) = 0.7.

kappa and alpha are symmetric in the two sides, so both backends of the decision arm report the
same figures.

**Recordings.** The decision arm records each backend's answer to the cell's own decision request
with `RecordedFixtureProvider.record_decision`, as TC-CONFORM-14's discriminating arm does: the
fixture's probabilities are chosen by the case, every other field is the F-JEV cell's own
recorded cloud answer. The live arm writes the pre-screen and verdict rows the live pipeline
would have written (TS-119's precedent for engine rows); no live reply is replayed or claimed.

Rung 1. **Written ahead: no** (#890 merged).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aeh.conf import DecisionEngine, ModelRef

pytestmark = pytest.mark.integration

#: The 10-pair fixture, (side a, side b), 0-based ordinals on a 4-band criterion.
PAIRS: tuple[tuple[int, int], ...] = (
    (0, 0), (0, 0), (1, 1), (1, 1), (2, 2), (2, 3), (3, 3), (1, 2), (0, 1), (3, 1))
KAPPA = 17 / 37
ALPHA = 0.7
SENTENCE = "agreement between graders is consistency, not agreement with teachers"

BACKENDS = {
    "openrouter-jev": ("openrouter/typesafe/jev-1.13@2026-09-17", None, "cloud-hosted"),
    "openjev": ("/models/openjev-FP8/model.safetensors@sha256:" + "ab" * 32, "fp8", "edge-local"),
}


def _engine(provider: str, build: str, quant: str | None) -> DecisionEngine:
    return DecisionEngine(
        model=ModelRef(role="decision", provider=provider, build_id=build, quantization=quant),
        confidence_threshold=Decimal("0.80"), cite_threshold=Decimal("0.50"),
        max_citation_questions=16, token_bytes_ratio=3)


def _probabilities(top: int, bands: int = 4) -> list[float]:
    """A confident answer on `top`: the F-JEV corpus's own confident shape."""
    rest = 0.023333
    return [0.930001 if i == top else rest for i in range(bands)]


def _accepting_j4_cells() -> list[str]:
    """F-JEV J4 cells whose recorded cloud answer clears every gate on its own fields: evidence
    sufficient and every cite well above the cite threshold."""
    from tests.support import jev_corpora

    chosen = []
    for cell_id, (cell, _request) in jev_corpora.f_jev_requests().items():
        answer = cell["answers"]["cloud"]
        if (cell["criterion_id"] == "J4" and answer["sufficiency"] >= 0.9
                and answer["cites"] and min(answer["cites"].values()) >= 0.9):
            chosen.append(cell_id)
    return chosen


def test_tc_conform_19_decision_report_carries_kappa_and_alpha_beside_exact_and_adjacent(
        tmp_path) -> None:
    from aeh import conform
    from aeh.conform.decision import load_f_jev_cells
    from aeh.judge import decision_request
    from aeh.prov import RecordedFixtureProvider
    from tests.support import jev_corpora

    cell_ids = _accepting_j4_cells()
    assert len(cell_ids) >= len(PAIRS), (
        f"fixture: F-JEV has {len(cell_ids)} accepting J4 cells, the case needs {len(PAIRS)}")
    cell_ids = cell_ids[: len(PAIRS)]
    requests = jev_corpora.f_jev_requests()
    backends = {}
    for side, (name, (build, quant, profile)) in enumerate(BACKENDS.items()):
        engine = _engine(name, build, quant)
        provider = RecordedFixtureProvider(fixture_dir=tmp_path / name)
        for cell_id, pair in zip(cell_ids, PAIRS):
            cell, scoring = requests[cell_id]
            answer = dict(cell["answers"]["cloud"])
            answer["band_probabilities"] = _probabilities(pair[side])
            request = decision_request(scoring, engine)
            provider.record_decision(request, engine.model,
                                     jev_corpora.answer_document(request, answer, name))
        backends[name] = (provider, engine, profile)
    cells = [cell for cell in load_f_jev_cells() if cell.cell_id in set(cell_ids)]
    assert len(cells) == len(PAIRS)

    report = conform.run_decision_conformance(backends, cells, fixture_set_id="tc-conform-19")

    assert report.agreement_note == SENTENCE
    for name, figures in report.per_backend.items():
        assert figures["decision_outcomes"]["accepted"] == len(PAIRS), (
            f"fixture: {name} did not accept all ten cells: {figures['decision_outcomes']}")
        by_criterion = figures["decision_band_agreement_by_criterion"]
        assert set(by_criterion) == {"J4"}, by_criterion
        j4 = by_criterion["J4"]
        assert j4["pairs"] == 10
        assert j4["decision_band_exact_agreement"] == pytest.approx(0.6)
        assert j4["decision_band_adjacent_agreement"] == pytest.approx(0.9)
        assert j4["decision_band_kappa"] == pytest.approx(KAPPA, abs=1e-12), (
            f"{name}: kappa {j4['decision_band_kappa']} is not the hand-computed 17/37")
        assert j4["decision_band_ordinal_alpha"] == pytest.approx(ALPHA, abs=1e-12), (
            f"{name}: alpha {j4['decision_band_ordinal_alpha']} is not the hand-computed 0.7")
        assert figures["agreement_note"] == SENTENCE
        # Beside the pooled exact/adjacent of the same pairs, not instead of them.
        assert figures["decision_band_exact_agreement"] == pytest.approx(0.6)
        assert figures["decision_band_adjacent_agreement"] == pytest.approx(0.9)


def test_tc_conform_19_live_acceptance_figures_carry_kappa_and_alpha_on_whole_band_cells(
        tmp_data_dir, make_fixture_provider, monkeypatch) -> None:
    import json
    from types import SimpleNamespace

    import aeh.conform.live_acceptance as live
    from tests.integration.judge.test_ts110_decision_dispatch import _world
    from tests.support.orch_run import ORCH_COHORT_ID

    store, _provider, world, _units = _world(
        tmp_data_dir, make_fixture_provider, submissions=tuple(f"S19-{i:02d}" for i in range(11)))
    criterion = "K19"
    # Each cell: the engine's probabilities (argmax = side a) and the LLM judges' ordinals.
    cells = [(a, [b]) for a, b in PAIRS] + [(1, [1, 2])]
    try:
        handle = store.cohort(ORCH_COHORT_ID)
        with handle.transaction() as tx:
            for i, (engine_band, judges) in enumerate(cells):
                submission = f"S19-{i:02d}"
                tx.execute(
                    "INSERT INTO decision_prescreen (work_id, run_id, submission_id, "
                    "criterion_id, engine_build, outcome, reason, threshold, latency_ms, "
                    "argmax_band, band_probabilities) VALUES (:w, :r, :s, :c, 'b', "
                    "'accepted', NULL, 0.8, 100, :band, :probs)",
                    w=f"pre-19-{i}", r=world["run_id"], s=submission, c=criterion,
                    band=str(engine_band), probs=json.dumps(_probabilities(engine_band)))
                for j, ordinal in enumerate(judges):
                    work = f"llm-19-{i}-{j}"
                    tx.execute(
                        "INSERT INTO work_unit (work_id, submission_id, stage, status, run_id, "
                        "criterion_id, attempts, judge_id) VALUES (:w, :s, 'score', 'done', "
                        ":r, :c, 0, :j)",
                        w=work, s=submission, r=world["run_id"], c=criterion, j=f"J{j}")
                    tx.execute(
                        "INSERT INTO verdict (verdict_id, work_id, judge_id, band, band_ordinal, "
                        "self_confidence, cited_spans, evidence_sufficient, uncited, "
                        "evidence_assessment, latency_ms, scoring_engine, engine_build) VALUES "
                        "(:v, :w, :j, :band, :o, 0.9, '[]', 1, 0, 'x', 100, 'llm', 'b')",
                        v=work, w=work, j=f"J{j}", band=str(ordinal), o=ordinal)

    finally:
        store.close()

    # The report is assembled by `run_live_acceptance` itself; only its live edges are stood
    # down — the precondition gates, the counting transports (the seam its docstring names for
    # an offline driver) and the drive, which returns the seeded run instead of grading one.
    monkeypatch.setattr(live, "_refusal_gates", lambda run_config: None)
    monkeypatch.setattr(live, "_counting_providers", lambda run_config: (
        None, None, {leg: live._LegTally() for leg in live.LIVE_LEGS}))
    monkeypatch.setattr(live, "_drive_live_pipeline", lambda *a, **k: world["run_id"])
    run_config = SimpleNamespace(decision_engine=SimpleNamespace(confidence_threshold=Decimal("0.80")))
    report = live.run_live_acceptance(run_config, cohort=SimpleNamespace(cohort_id=ORCH_COHORT_ID),
                                      data_dir=tmp_data_dir)
    figures = report.per_criterion[criterion]

    # Exact and adjacent count every comparable cell, the half-band one too.
    assert figures["decision_band_exact_agreement"] == pytest.approx(6 / 11)
    assert figures["decision_band_adjacent_agreement"] == pytest.approx(10 / 11)
    # kappa and alpha only over cells whose panel median is a band (the 10-pair fixture).
    assert figures["decision_band_chance_corrected_n"] == 10, figures
    assert figures["decision_band_kappa"] == pytest.approx(KAPPA, abs=1e-12), figures
    assert figures["decision_band_ordinal_alpha"] == pytest.approx(ALPHA, abs=1e-12), figures
    assert report.agreement_note == SENTENCE
