"""`TS-80` (issue #153) — `Requires` pairwise integration into **`M-AGG`**: consumers of the
aggregated score, checked against the real aggregation code over a real store (rung 3).

| Case | Consumer | Assumption checked here |
|---|---|---|
| TC-REQ-17 | `M-ORCH` | the escalation decision is pure, and the escalation commits with its triggering result |
| TC-REQ-45 | `M-SYNTH` | synthesis reads verdicts and writes no `criterion_score` |
| TC-REQ-49 | `M-GRADE` | grading sums the stored points and performs no band→points mapping |
| TC-REQ-54 | `M-REVIEW` | review ranks on the stored confidence, re-derives none, and presents none as a probability |

Markers: `contract` and `integration` (§4.7).
"""

from __future__ import annotations

import re

import pytest

from aeh.store import Tx, open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.contract, pytest.mark.integration]

_OPEN = ({"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},)


def _statements(monkeypatch):
    seen: list[str] = []
    real = Tx.execute

    def spy(tx, statement, **params):
        seen.append(" ".join(str(statement).split()))
        return real(tx, statement, **params)

    monkeypatch.setattr(Tx, "execute", spy)
    return seen


def test_tc_req_17_the_escalation_decision_is_pure_and_commits_with_its_result(
    tmp_data_dir, monkeypatch
):
    """`TC-REQ-17` (`M-ORCH` → `M-AGG`, CT-AGG-08): `should_escalate` returns the same decision for
    the same inputs and writes nothing to the store. Its escalation joins the caller's
    transaction with the triggering score: a failure raised inside that transaction, after both
    writes, leaves neither the score nor the escalation units."""
    from aeh.agg import aggregate, should_escalate
    from aeh.orch import Orchestrator
    from tests.support.agg_vocabulary import (
        agg_config,
        criterion,
        criterion_history,
        expected_distribution,
        panel,
        signals,
    )
    from tests.support.e2e_world import _SCORE_UPSERT

    bands = (("absent", 0, 0.0), ("emerging", 1, 1.0), ("developing", 2, 2.0), ("secure", 3, 3.0))
    crit = criterion([__import__("tests.support.agg_vocabulary", fromlist=["band"]).band(*b)
                      for b in bands], scoring_model="holistic", criterion_id="C01")
    rows = panel(("emerging", 1), ("secure", 3), ("developing", 2))
    score = aggregate(rows, crit, signals(), config=agg_config())
    writes = _statements(monkeypatch)
    decisions = [should_escalate(score=score, criterion=crit, history=criterion_history(),
                                 baseline=expected_distribution(), config=agg_config())
                 for _ in range(2)]
    monkeypatch.undo()
    assert decisions[0] == decisions[1], "should_escalate is not a pure function of its inputs"
    assert decisions[0].escalate, f"fixture: the split panel did not decide to escalate: {decisions[0]}"
    assert not writes, f"should_escalate wrote to the store: {writes}"

    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _v = seed_run(store, submissions=("S001",), criteria=_OPEN)
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)
        cohort = store.cohort(ORCH_COHORT_ID)
        units_before = cohort.query("SELECT COUNT(*) AS n FROM work_unit")[0]["n"]
        inserted = []
        with pytest.raises(RuntimeError, match="induced"):
            with cohort.transaction() as tx:
                tx.execute(_SCORE_UPSERT, sid="S001", cid="C01", band="emerging", points=1.0,
                           judge_count=3, agreement=0.3, state="provisional_unreviewed",
                           routing="queued", confidence=0.3, confidence_base=0.3,
                           spans_verified=1, evidence_present=1, sufficiency_flag=0,
                           ocr_overlap_risk=0)
                inserted = [r.units_inserted for r in Orchestrator(store).enqueue_escalation(tx, ("S001", "C01"))]
                raise RuntimeError("induced failure after the score and the escalation")
        scores = cohort.query("SELECT COUNT(*) AS n FROM criterion_score")[0]["n"]
        units_after = cohort.query("SELECT COUNT(*) AS n FROM work_unit")[0]["n"]
    finally:
        store.close()
    assert sum(inserted) > 0, "fixture: the escalation inserted no units inside the transaction"
    assert (scores, units_after) == (0, units_before), (
        f"an induced failure left the score ({scores}) or escalation units ({units_after - units_before})")


def test_tc_req_45_synthesis_reads_verdicts_and_writes_no_criterion_score(tmp_data_dir, monkeypatch):
    """`TC-REQ-45` (`M-SYNTH` → `M-AGG`, CT-AGG-11): over a real synthesis of a five-question
    submission, M-SYNTH reads verdict rows and writes narratives, and no statement it executes
    writes `criterion_score`. The reciprocal of `TC-AGG-C11`: the write sets are disjoint from this
    side too."""
    from aeh.store import SqliteTierHandle
    from aeh.synth import SynthesisWorker
    from tests.support.synth_vocabulary import (
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
    reads: list[str] = []
    real_query = SqliteTierHandle.query

    def read_spy(handle, statement, **params):
        reads.append(" ".join(str(statement).split()))
        return real_query(handle, statement, **params)

    store = open_store(tmp_data_dir)
    try:
        _orch, run_id, _v = seed_run(store, submissions=("SYN-001",), criteria=FIVE_QUESTION_CRITERIA)
        seed_scored_submission(store, run_id, "SYN-001", complete_questions=set(questions))
        writes = _statements(monkeypatch)
        monkeypatch.setattr(SqliteTierHandle, "query", read_spy)
        SynthesisWorker(store, CaptureProvider(replies), synth_ref()).synthesize_submission(run_id, "SYN-001")
        monkeypatch.undo()
    finally:
        store.close()
    score_writes = [w for w in writes if re.search(r"\b(INSERT|UPDATE|REPLACE|DELETE)\b.*\bcriterion_score\b", w, re.I)]
    assert any("narrative" in w for w in writes), "fixture: synthesis wrote no narrative"
    assert any(re.search(r"\bverdict\b", r) for r in reads + writes), "synthesis read no verdict"
    assert not score_writes, f"M-SYNTH wrote criterion_score: {score_writes}"


def test_tc_req_49_grading_sums_stored_points_and_maps_no_band(tmp_data_dir, monkeypatch):
    """`TC-REQ-49` (`M-GRADE` → `M-AGG`, CT-AGG-02/06/07/11): the stored scores carry points no
    band mapping would produce: 7.25 on `B2` and 3.5 on `B1`, while the catalog maps neither.
    `compute_all` produces a total equal to the stored points summed, and calls no band→points
    mapping (`aeh.pkg.points_for_band` or the catalog's) while doing it."""
    import aeh.grade as grade
    import aeh.pkg as pkg
    from aeh.pkg import GradePolicy, PackageCatalog
    from tests.support.grade_vocabulary import grade_rows, write_criterion_scores

    submissions = ("S001", "S002")
    store = open_store(tmp_data_dir)
    try:
        _orch, run_id, version = seed_run(store, submissions=submissions, criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
            {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"}))
        PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch").set_grade_policy(
            version, GradePolicy(combination="weighted_sum"))
        cohort = store.cohort(ORCH_COHORT_ID)
        write_criterion_scores(cohort, [(s, "C1", "B2", 7.25, "auto") for s in submissions]
                               + [(s, "C2", "B1", 3.5, "auto") for s in submissions])
        mapped: list[tuple] = []
        for owner in (pkg, grade):
            if hasattr(owner, "points_for_band"):
                real = getattr(owner, "points_for_band")
                monkeypatch.setattr(owner, "points_for_band",
                                    lambda *a, _r=real, **k: mapped.append(a) or _r(*a, **k))
        real_catalog = PackageCatalog.points_for_band
        monkeypatch.setattr(PackageCatalog, "points_for_band",
                            lambda self, *a, **k: mapped.append(a) or real_catalog(self, *a, **k))
        grade.open_grade(store).compute_all(run_id)
        monkeypatch.undo()
        rows = grade_rows(cohort)
    finally:
        store.close()
    totals = {row["submission_id"]: row.get("total_points", row.get("total")) for row in rows}
    assert len(rows) == 2, f"fixture: {len(rows)} grade rows"
    assert all(abs(float(t) - 10.75) < 1e-9 for t in totals.values()), f"grade totals {totals}, not 7.25 + 3.5"
    assert not mapped, f"M-GRADE called a band→points mapping {len(mapped)} time(s): {mapped[:2]}"


def test_tc_req_54_review_ranks_on_stored_confidence_and_calls_it_no_probability():
    """`TC-REQ-54` (`M-REVIEW` → `M-AGG`, CT-AGG-05/06/09/10/16): M-REVIEW builds its queue from
    stored rows whose confidence M-AGG already derived. It re-derives none: building the queue calls
    none of M-AGG's confidence functions, and M-REVIEW imports none. It presents none: a queue item
    carries no confidence field at all (CT-REVIEW-07), and the rendered queue page states no
    probability or percentage. Ranking reads its own expected-value inputs, not a confidence."""
    import aeh.agg as agg
    import aeh.console as console
    from aeh.review import build_review
    from tests.support import broken_review_fixtures as broken

    called: list[str] = []
    patch = pytest.MonkeyPatch()
    try:
        for name in [n for n in dir(agg) if "confidence" in n.lower() and callable(getattr(agg, n))]:
            real = getattr(agg, name)
            patch.setattr(agg, name, lambda *a, _n=name, _r=real, **k: called.append(_n) or _r(*a, **k))
        service = build_review(scores=broken.flagged_population(40))
        queue = service.build_queue(run_id="run-1", budget_minutes=30)
        page = console.render_review_queue(service, run_id="run-1", budget_minutes=30).html
    finally:
        patch.undo()
    import aeh.review as review

    confidence_functions = [n for n in dir(agg) if "confidence" in n.lower() and callable(getattr(agg, n))]
    watched = [getattr(agg, f) for f in confidence_functions]
    imported = [n for n in dir(review) if any(getattr(review, n, None) is fn for fn in watched)]
    shown = list(queue.shown)
    assert confidence_functions, "control: M-AGG exposes no confidence function to watch"
    assert not imported, f"M-REVIEW imports M-AGG's confidence derivation: {imported}"
    assert shown, "fixture: the queue shows nothing"
    import dataclasses as _dc

    item_fields = [f.name for f in _dc.fields(type(shown[0]))]
    assert not [f for f in item_fields if "confidence" in f.lower() or "probab" in f.lower()], (
        f"a queue item carries a confidence or probability field: {item_fields}")
    assert not called, f"building the queue re-derived confidence through M-AGG: {called}"
    lowered = re.sub(r"<[^>]+>", " ", page).lower()
    assert "probability" not in lowered, "the queue page presents confidence as a probability"
    assert not re.search(r"confidence[^.<]{0,40}\d+(\.\d+)?\s*%", lowered), (
        "the queue page presents confidence as a percentage")
