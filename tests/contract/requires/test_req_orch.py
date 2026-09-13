"""`TS-79` (issue #152) — `Requires` pairwise integration into **`M-ORCH`**: every consumer's
assumption about the work ledger and the orchestrator, checked against the real `Orchestrator` over
a real store with real neighbouring modules (rung 3).

Test plan §6.13, grouped one suite per provider module (§4.10).

| Case | Consumer | Assumption checked here |
|---|---|---|
| TC-REQ-18 | `M-EXTRACT` | a unit delivered twice extracts once: one evidence row, the same result |
| TC-REQ-27 | `M-JUDGE` | `persist` is idempotent on `work_id`, and a shuffled batch still shares one prefix |
| TC-REQ-40 | `M-AGG` | `enqueue_escalation` joins the caller's transaction: both or neither survive a kill |
| TC-REQ-43 | `M-SYNTH` | a redelivered synthesis unit conflicts rather than inserting a second narrative |
| TC-REQ-66 | `M-CALIB` | enumeration is deterministic, so a dual-scoring pass matches the original unit for unit |
| TC-REQ-70 | `M-CONFORM` | the sweep order is the same on every profile |
| TC-REQ-75 | `M-CONSOLE` | `ProgressReport` has no per-student field, so per-student progress cannot render |
| TC-REQ-84 | `M-DET` | one null-judge deterministic unit per deterministic criterion, and redelivery is harmless to the writes |

Markers: `contract` and `integration` (§4.7).
"""

from __future__ import annotations

import dataclasses
import json
import os
import random
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aeh.orch import STAGE_EXTRACT, Orchestrator
from aeh.store import open_store
from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_run

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[3]
_IMPORTS = ("import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge\n"
            "import aeh.orch, aeh.pkg, aeh.review, aeh.synth\n")


def _fixture_provider(tmp_data_dir):
    from aeh.prov import RecordedFixtureProvider

    return RecordedFixtureProvider(fixture_dir=tmp_data_dir / "fixtures")


# -- TC-REQ-18 ----------------------------------------------------------------------------------


def test_tc_req_18_a_unit_delivered_twice_extracts_once(tmp_data_dir):
    """`TC-REQ-18` (`M-EXTRACT` → `M-ORCH`, CT-ORCH-04/05/06): a leased extraction unit is
    processed, then deliberately delivered again to the real worker. The second delivery writes
    no second evidence row and returns the same spans, because the first completion already
    stands."""
    from aeh.extract import ExtractionWorker, assemble_request, prompt_fields
    from tests.contract.judge import _drive
    from tests.support.extract_vocabulary import extractor_ref, sampling_params, span_completion

    store = open_store(tmp_data_dir)
    try:
        provider = _fixture_provider(tmp_data_dir)
        orchestrator, _run, _v = _drive.seed_world(store)
        unit = orchestrator.lease("w-req-18", STAGE_EXTRACT, 1)[0]
        ref = extractor_ref()
        provider.record(prompt_fields(assemble_request(unit, store=store)), ref, sampling_params(),
                        span_completion(_drive.spans(), build_id="build-req-18"))
        worker = ExtractionWorker(store, provider, ref)
        first = worker.process(unit)
        second = worker.process(unit)
        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT COUNT(*) AS n FROM evidence WHERE work_id = :w", w=unit.work_id)[0]["n"]
    finally:
        store.close()
    assert rows == 1, f"a double delivery wrote {rows} evidence rows"
    assert first.spans == second.spans, "the redelivered unit returned different spans"


# -- TC-REQ-27 ----------------------------------------------------------------------------------


def test_tc_req_27_persist_is_idempotent_and_a_shuffled_batch_keeps_one_prefix(tmp_data_dir):
    """`TC-REQ-27` (`M-JUDGE` → `M-ORCH`, CT-ORCH-04/05/06/21, CT-JUDGE-08): the score units of one
    (judge, criterion) batch over three submissions are assembled in the leased order and in a
    shuffled order. Every assembled prompt's prefix (the fields before the submission) is
    byte-identical in both orders, since the prefix property cannot rely on intra-batch order,
    which is not promised. Persisting the same verdict twice for one `work_id` leaves one row."""
    from aeh.judge import ScoringWorker, prompt_fields
    from tests.contract.judge import _drive

    store = open_store(tmp_data_dir)
    try:
        provider = _fixture_provider(tmp_data_dir)
        orchestrator, _run, _v = _drive.seed_world(store, submissions=("SYN-001", "SYN-002", "SYN-003"))
        _drive.drive_extract(orchestrator, store, provider)
        units = _drive.lease_score_units(orchestrator)
        refs = {r.build_id: r for r in _drive.PANEL_REFS}
        batch = [u for u in units if u.judge == units[0].judge and u.criterion_id == units[0].criterion_id]

        def prefixes(order):
            out = set()
            for unit in order:
                fields = list(prompt_fields(ScoringWorker(store, provider, refs[unit.judge]).assemble(unit)).fields)
                cut = next(i for i, (name, _v) in enumerate(fields) if "submission" in name)
                out.add(json.dumps(fields[:cut]))
            return out

        leased_order = prefixes(batch)
        shuffled = list(batch)
        random.Random(20260913).shuffle(shuffled)
        shuffled_order = prefixes(shuffled)

        from tests.support.extract_vocabulary import sampling_params, verdict_completion

        unit = batch[0]
        worker = ScoringWorker(store, provider, refs[unit.judge])
        request = worker.assemble(unit)
        provider.record(prompt_fields(request), refs[unit.judge], sampling_params(),
                        verdict_completion("secure", 0.9, build_id="build-req-27",
                                           cited_spans=_drive.spans()))
        result = worker.dispatch(request, refs[unit.judge])
        worker.persist(unit, result)
        worker.persist(unit, result)
        verdicts = store.cohort(ORCH_COHORT_ID).query(
            "SELECT COUNT(*) AS n FROM verdict WHERE work_id = :w", w=unit.work_id)[0]["n"]
    finally:
        store.close()
    assert len(batch) == 3, f"fixture: the batch holds {len(batch)} units, not 3"
    assert len(leased_order) == 1, "the leased batch does not share one prefix"
    assert shuffled_order == leased_order, "a shuffled batch assembled a different prefix"
    assert verdicts == 1, f"persisting one work_id twice left {verdicts} verdict rows"


# -- TC-REQ-40 ----------------------------------------------------------------------------------

_ESCALATION_KILLED = """
import os, sys, json
from aeh.orch import Orchestrator
from aeh.store import open_store
from tests.support.e2e_world import _SCORE_UPSERT
store = open_store(sys.argv[1])
orchestrator = Orchestrator(store)
cohort = store.cohort("c-2026-7B-orch")
with cohort.transaction() as tx:
    tx.execute(_SCORE_UPSERT, sid="S001", cid="C01", band="met", points=1.0, judge_count=1,
               agreement=0.5, state="provisional_unreviewed", routing="queued", confidence=0.4,
               confidence_base=0.4, spans_verified=1, evidence_present=1, sufficiency_flag=0,
               ocr_overlap_risk=0)
    reports = orchestrator.enqueue_escalation(tx, ("S001", "C01"))
    print(json.dumps([r.units_inserted for r in reports]), flush=True)
    if sys.argv[2] == "kill":
        os._exit(5)
"""


def test_tc_req_40_the_escalation_joins_the_aggregation_transaction(tmp_data_dir):
    """`TC-REQ-40` (`M-AGG` → `M-ORCH`, CT-ORCH-08): M-AGG's score write and M-ORCH's
    `enqueue_escalation` run in one caller-owned transaction. A process killed after both, before
    the commit, leaves neither the score nor the escalation units. The same body left to commit
    leaves both."""
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)]))
    counts = {}
    for mode in ("kill", "commit"):
        data_dir = tmp_data_dir / mode
        store = open_store(data_dir)
        try:
            orchestrator, run_id, _v = seed_run(store, submissions=("S001",), criteria=(
                {"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},),
                cfg=orch_cfg("edge-local"))
            orchestrator.enumerate_units(run_id)
            orchestrator.start(run_id)
            base = store.cohort(ORCH_COHORT_ID).query("SELECT COUNT(*) AS n FROM work_unit")[0]["n"]
        finally:
            store.close()
        child = subprocess.run([sys.executable, "-c", _IMPORTS + textwrap.dedent(_ESCALATION_KILLED),
                                str(data_dir), mode], capture_output=True, text=True, env=env,
                               timeout=120)
        inserted = json.loads(child.stdout.strip().splitlines()[-1]) if child.stdout.strip() else None
        store = open_store(data_dir)
        try:
            cohort = store.cohort(ORCH_COHORT_ID)
            counts[mode] = (
                child.returncode, inserted,
                cohort.query("SELECT COUNT(*) AS n FROM criterion_score")[0]["n"],
                cohort.query("SELECT COUNT(*) AS n FROM work_unit")[0]["n"] - base,
            )
        finally:
            store.close()
    killed, committed = counts["kill"], counts["commit"]
    assert committed[1] and sum(committed[1]) > 0, f"fixture: the escalation inserted nothing: {counts}"
    assert killed[0] == 5 and killed[2:] == (0, 0), f"the kill left score/escalation rows: {counts}"
    assert committed[2] == 1 and committed[3] == sum(committed[1]), f"the commit lost a half: {counts}"


# -- TC-REQ-43 ----------------------------------------------------------------------------------


def test_tc_req_43_a_redelivered_synthesis_unit_inserts_no_second_narrative(tmp_data_dir):
    """`TC-REQ-43` (`M-SYNTH` → `M-ORCH`, CT-ORCH-04/06, CT-SYNTH-06): a submission is
    synthesized, then delivered again. The narrative rows are unchanged in number and content,
    and the second delivery dispatches no model call for work already stored."""
    from aeh.synth import SynthesisWorker
    from tests.support.synth_vocabulary import (
        COHORT_ID,
        FIVE_QUESTION_CRITERIA,
        CaptureProvider,
        narrative_completion,
        seed_scored_submission,
        synth_ref,
    )

    questions = tuple(f"Q{q}" for q in range(1, 6))

    def replies():
        return [narrative_completion(f"Question {q[1:]}: the response states its reasoning.",
                                     (f"{q}C1", f"{q}C2")) for q in questions] + [
            narrative_completion("Overall: each complete question is addressed in turn.")]

    store = open_store(tmp_data_dir)
    try:
        _orch, run_id, _v = seed_run(store, submissions=("SYN-001",), criteria=FIVE_QUESTION_CRITERIA)
        seed_scored_submission(store, run_id, "SYN-001", complete_questions=set(questions))
        SynthesisWorker(store, CaptureProvider(replies()), synth_ref()).synthesize_submission(run_id, "SYN-001")
        read = lambda: [tuple(dict(r).items()) for r in store.cohort(COHORT_ID).query(  # noqa: E731
            "SELECT * FROM narrative WHERE run_id = :r ORDER BY level, question_id", r=run_id)]
        first = read()
        again = CaptureProvider(replies())
        SynthesisWorker(store, again, synth_ref()).synthesize_submission(run_id, "SYN-001")
        second = read()
        calls = again.calls
    finally:
        store.close()
    assert first, "fixture: synthesis wrote no narrative"
    assert second == first, "a redelivered synthesis unit changed the narrative rows"
    assert calls == 0, f"the redelivery dispatched {calls} model call(s) for stored narratives"


# -- TC-REQ-66 / TC-REQ-70 ----------------------------------------------------------------------

_CRITERIA = (
    {"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C02", "kind": "open", "scoring_model": "holistic", "dependencies": ("C01",)},
    {"criterion_id": "M01", "kind": "mcq", "scoring_model": "deterministic"},
)


def _hosted_cfg():
    from aeh.conf import CohortRef, resolve_run_config
    from tests.support.conf_builders import HOSTED_PANEL_3, hosted_cfg

    return resolve_run_config(hosted_cfg("dev-ci", panel=HOSTED_PANEL_3),
                              CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"))


def _units(store, run_id):
    return [tuple(dict(r).values()) for r in store.cohort(ORCH_COHORT_ID).query(
        "SELECT work_id, stage, submission_id, criterion_id, judge_id, origin FROM work_unit "
        "WHERE run_id = :r ORDER BY work_id", r=run_id)]


def _sweep(orchestrator, run_id):
    """Lease and complete every unit of one running run, recording (stage, submission,
    criterion) in the order handed out. Only this run is running while it sweeps."""
    trace = []
    for stage in ("deterministic", "extract", "score"):
        while True:
            batch = orchestrator.lease("w-trace", stage, 2)
            if not batch:
                break
            for unit in batch:
                assert unit.run_id == run_id if hasattr(unit, "run_id") else True
                trace.append((stage, unit.submission_id, unit.criterion_id))
                orchestrator.complete(unit.work_id)
    return trace


def test_tc_req_66_two_enumerations_of_one_run_match_unit_for_unit(tmp_data_dir):
    """`TC-REQ-66` (`M-CALIB` → `M-ORCH`, CT-ORCH-02/18): one created run is copied to a second
    data directory before enumeration, the way a dual-scoring pass re-derives the same run, and
    each copy is enumerated independently. Both produce identical units: the same work IDs,
    stages, submissions, criteria, judges and origins. A second enumeration in the same store adds
    nothing. The unit count, the pass's known cost, is the same in both."""
    import shutil

    original = tmp_data_dir / "original"
    store = open_store(original)
    try:
        _orch, run_id, _v = seed_run(store, submissions=("S001", "S002", "S003"), criteria=_CRITERIA)
    finally:
        store.close()
    shutil.copytree(original, tmp_data_dir / "dual")
    enumerated = []
    for data_dir in (original, tmp_data_dir / "dual"):
        store = open_store(data_dir)
        try:
            orchestrator = Orchestrator(store)
            first = orchestrator.enumerate_units(run_id).units_enumerated
            again = orchestrator.enumerate_units(run_id)
            enumerated.append((first, _units(store, run_id)))
            assert _units(store, run_id) == enumerated[-1][1], "re-enumeration changed the ledger"
        finally:
            store.close()
    assert enumerated[0][1], "fixture: nothing enumerated"
    assert enumerated[0] == enumerated[1], "two enumerations of the same run differ"


def test_tc_req_70_the_sweep_order_is_the_same_on_every_profile(tmp_data_dir):
    """`TC-REQ-70` (`M-CONFORM` → `M-ORCH`, CT-ORCH-02/05/19): two runs over the same cohort and
    package version, one on `edge-local` and one on `dev-ci`, are each enumerated and swept to
    completion in turn. The ordered (stage, criterion) batches handed out, and the submissions each
    batch holds, are identical, so two backend runs' execution traces are comparable. Judge
    identities differ with the builds each backend serves. The order of submissions inside a
    batch follows the work ID hash, which includes the run, and CT-ORCH-05 does not promise it,
    so it is compared as a set."""
    store = open_store(tmp_data_dir)
    try:
        orchestrator, edge_run, version = seed_run(store, submissions=("S001", "S002", "S003"),
                                                   criteria=_CRITERIA, cfg=orch_cfg("edge-local"))
        orchestrator.enumerate_units(edge_run)
        orchestrator.start(edge_run)
        edge = _sweep(orchestrator, edge_run)
        from decimal import Decimal

        class _Priced:  # the ceiling a hosted run freezes is enforced against a pricing seam
            def estimate_cost(self, unit):
                return Decimal("0")

        priced = Orchestrator(store, provider=_Priced())
        hosted_run = priced.create_run(ORCH_COHORT_ID, version, _hosted_cfg())
        priced.enumerate_units(hosted_run)
        priced.start(hosted_run)
        hosted = _sweep(priced, hosted_run)
    finally:
        store.close()
    def batches(trace):
        """Consecutive (stage, criterion) batches, each with the submissions it held. The order
        of submissions inside a batch is not promised (CT-ORCH-05; the work ID hashes the run),
        so it is compared as a multiset."""
        out = []
        for stage, submission, criterion in trace:
            if out and out[-1][0] == (stage, criterion) and submission not in out[-1][1]:
                out[-1][1].append(submission)
            else:
                out.append(((stage, criterion), [submission]))
        return [(key, sorted(subs)) for key, subs in out]

    assert edge, "fixture: nothing was leased"
    assert batches(edge) == batches(hosted), (
        f"the sweep order differs between profiles:\nedge-local {edge}\ndev-ci     {hosted}")


# -- TC-REQ-75 ----------------------------------------------------------------------------------


def test_tc_req_75_progress_carries_no_per_student_field_so_the_console_cannot_render_one(
    tmp_data_dir
):
    """`TC-REQ-75` (`M-CONSOLE` → `M-ORCH`, CT-ORCH-03/10/13/17, CT-CONSOLE-09):
    `ProgressReport`'s fields name no submission or student, and no value it carries is a
    submission ID. The run monitor (S7) over a run whose submissions have sentinel IDs renders
    none of them. A pause requested twice through the console applies once."""
    from aeh.console import SCREENS, build_console
    from aeh.orch import ProgressReport

    names = [f.name for f in dataclasses.fields(ProgressReport)]
    per_student = [n for n in names if any(t in n.lower() for t in ("submission", "student", "ref"))]
    sentinels = ("SUBMISSION-SENTINEL-A", "SUBMISSION-SENTINEL-B")
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _v = seed_run(store, submissions=sentinels, criteria=_CRITERIA[:1])
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)
        report = orchestrator.progress(run_id)
        values = json.dumps(dataclasses.asdict(report), default=str)
        app = build_console(store=store)
        page = app.render(SCREENS["S7"], id=run_id).html
        app.perform("pause/resume", run_id=run_id, state="paused")
        app.perform("pause/resume", run_id=run_id, state="paused")
        Orchestrator(store).lease("w-req-75", STAGE_EXTRACT, 1)
        paused = store.cohort(ORCH_COHORT_ID).query(
            "SELECT status FROM run WHERE run_id = :r", r=run_id)[0]["status"]
    finally:
        store.close()
    assert not per_student, f"ProgressReport carries per-student fields: {per_student}"
    assert not any(s in values for s in sentinels), "a ProgressReport value names a submission"
    assert not any(s in page for s in sentinels), "the run monitor renders per-student progress"
    assert paused == "paused", f"two pause requests did not leave the run paused once: {paused}"


# -- TC-REQ-84 ----------------------------------------------------------------------------------


def test_tc_req_84_one_null_judge_deterministic_unit_and_redelivery_is_harmless(tmp_data_dir):
    """`TC-REQ-84` (`M-DET` → `M-ORCH`, CT-ORCH-04/07, CT-DET-01): each deterministic criterion
    enumerates exactly one `deterministic` unit per submission, with a null judge and no
    extraction or scoring unit. M-DET's cohort pass run twice (a redelivery) leaves the score rows
    and `mcq_item_stats` unchanged. A key-change re-derivation run twice changes nothing and
    appends no audit record the second time: purity covers the computation, and the writes must
    be idempotent too."""
    from aeh.det import DeterministicEvaluator
    from aeh.pkg import PackageCatalog
    from tests.support.det_vocabulary import (
        open_det_store,
        seed_answer_region,
        seed_det_world,
        seed_head_document,
    )

    submissions = ("S001", "S002", "S003")
    store = open_det_store(tmp_data_dir)
    try:
        run_id, v1, cohort_id = seed_det_world(
            store, submissions=submissions,
            criteria=[{"criterion_id": "M1", "question_id": "Q1", "key": ("B",)}])
        for submission, selection in zip(submissions, ("B", "C", "B")):
            seed_answer_region(store, cohort_id, seed_head_document(store, cohort_id, submission),
                               "Q1", selection=selection)
        orchestrator = Orchestrator(store)
        orchestrator.enumerate_units(run_id)
        cohort = store.cohort(cohort_id)
        units = [dict(r) for r in cohort.query(
            "SELECT stage, submission_id, judge_id AS judge FROM work_unit WHERE criterion_id = 'M1'")]
        evaluator = DeterministicEvaluator(store)
        snapshot = lambda: (  # noqa: E731
            [tuple(dict(r).values()) for r in cohort.query(
                "SELECT submission_id, band, points FROM criterion_score ORDER BY submission_id")],
            [tuple(dict(r).values()) for r in store.durable().query(
                "SELECT * FROM mcq_item_stats ORDER BY 1, 2, 3")],
            store.durable().query("SELECT COUNT(*) AS n FROM audit_record")[0]["n"])
        evaluator.evaluate_cohort(run_id)
        after_first = snapshot()
        evaluator.evaluate_cohort(run_id)
        after_redelivery = snapshot()
        catalog = PackageCatalog(store.package("pkg-det"), package_id="pkg-det")
        v2 = catalog.create_version(parent=v1)
        catalog.set_answer_key(v2, "M1", ("C",))
        evaluator.rederive_for_key_change(cohort_id, "M1", v2)
        after_rederive = snapshot()
        second = evaluator.rederive_for_key_change(cohort_id, "M1", v2)
        after_second_rederive = snapshot()
    finally:
        store.close()
    stages = sorted(u["stage"] for u in units)
    assert stages == ["deterministic"] * len(submissions), f"M1 enumerated {stages}"
    assert all(u["judge"] in (None, "") for u in units), f"a deterministic unit names a judge: {units}"
    assert after_redelivery[:2] == after_first[:2], "a redelivered cohort pass changed scores or item stats"
    assert second.scores_changed == 0, f"a repeated re-derivation changed {second.scores_changed} score(s)"
    assert after_second_rederive == after_rederive, (
        "a repeated re-derivation changed the stored rows or appended audit records")
