"""`TS-80` (issue #153) — `Requires` pairwise integration into **`M-DET`** and **`M-SYNTH`**: the
consumers of deterministic scores and narratives, checked against the real modules over a real
store (rung 3).

| Case | Consumer → provider | Assumption checked here |
|---|---|---|
| TC-REQ-38 | `M-AGG` → `M-DET` | deterministic scores arrive complete with `judge_count = 0`; unresolved ones route to triage unscored; M-AGG has nothing to aggregate |
| TC-REQ-50 | `M-GRADE` → `M-DET` | the rollup separation follows the declared evaluation mode, not the band names |
| TC-REQ-62 | `M-STATS` → `M-DET` | the admissibility filter reads `label.evaluation_mode`; a deterministic label is excluded end to end |
| TC-REQ-85 | `M-GRADE` → `M-SYNTH` | synthesis has no write path to grades, and grading completes with synthesis wholly absent |
| TC-REQ-86 | `M-REVIEW` → `M-SYNTH` | a narrative carries no numeric field, and review honours the suppression flag without re-checking text |
| TC-REQ-87 | `M-CONSOLE` → `M-SYNTH` | the console honours the flag and applies no score-claim filter of its own |

Markers: `contract` and `integration` (§4.7).
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from aeh.store import open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.contract, pytest.mark.integration]


def _det_world(store, selections=("B", "C", None)):
    from tests.support.det_vocabulary import seed_answer_region, seed_det_world, seed_head_document

    submissions = tuple(f"S{i:03d}" for i in range(1, len(selections) + 1))
    run_id, version, cohort_id = seed_det_world(
        store, submissions=submissions,
        criteria=[{"criterion_id": "M1", "question_id": "Q1", "key": ("B",)}])
    for submission, selection in zip(submissions, selections):
        document_id = seed_head_document(store, cohort_id, submission)
        if selection is None:
            seed_answer_region(store, cohort_id, document_id, "Q1", content_state="present",
                               selection_state="ambiguous")
        else:
            seed_answer_region(store, cohort_id, document_id, "Q1", selection=selection)
    return run_id, version, cohort_id


def test_tc_req_38_deterministic_scores_arrive_complete_and_aggregation_has_nothing_to_do(tmp_data_dir):
    """`TC-REQ-38` (`M-AGG` → `M-DET`, CT-DET-01/02/03): after M-DET's cohort pass, the resolved
    answers are complete `criterion_score` rows with `judge_count = 0` and points set. The ambiguous
    mark is routed to `triage` with no points: it is not scored. Each stored row passed through
    M-AGG's deterministic entry (`aggregate(..., deterministic_score=row)`) comes back with the
    same band, points, judge count and routing: not re-aggregated and not scored. Without a
    deterministic score, an empty panel is refused, and no score unit exists for the criterion."""
    from aeh.agg import EmptyVerdictsError, aggregate
    from aeh.det import DeterministicEvaluator
    from aeh.orch import Orchestrator
    from tests.support.agg_vocabulary import band, criterion, signals
    from tests.support.det_vocabulary import open_det_store

    store = open_det_store(tmp_data_dir)
    try:
        run_id, _v, cohort_id = _det_world(store)
        Orchestrator(store).enumerate_units(run_id)
        DeterministicEvaluator(store).evaluate_cohort(run_id)
        cohort = store.cohort(cohort_id)
        rows = {r["submission_id"]: dict(r) for r in cohort.query(
            "SELECT submission_id, band, points, judge_count, routing FROM criterion_score")}
        score_units = cohort.query("SELECT COUNT(*) AS n FROM work_unit WHERE stage = 'score'")[0]["n"]
    finally:
        store.close()
    assert rows["S001"]["band"] == "correct" and rows["S002"]["band"] == "incorrect"
    assert all(rows[s]["judge_count"] == 0 and rows[s]["points"] is not None for s in ("S001", "S002")), rows
    assert rows["S003"]["routing"] == "triage" and rows["S003"]["points"] is None, rows["S003"]
    assert score_units == 0, f"{score_units} score unit(s) exist for a deterministic criterion"
    crit = criterion([band("incorrect", 0, 0.0), band("correct", 1, 1.0)], criterion_id="M1")
    for submission in ("S001", "S002", "S003"):
        stored = rows[submission]
        row = type("Row", (), {**stored, "criterion_id": "M1"})()
        passed = aggregate([], crit, signals(), deterministic_score=row)
        got = (passed.band, passed.points, passed.judge_count, passed.routing)
        want = (stored["band"], stored["points"], stored["judge_count"], stored["routing"])
        assert got == want, f"M-AGG changed a deterministic score for {submission}: {got} != {want}"
    with pytest.raises(EmptyVerdictsError):
        aggregate([], crit, signals())


def test_tc_req_50_the_rollup_separation_follows_the_declared_mode_not_band_names(tmp_data_dir):
    """`TC-REQ-50` (`M-GRADE` → `M-DET`, CT-DET-02/03/06/07, CT-GRADE-12): a judged criterion whose
    rubric names its bands `correct`/`incorrect` (M-DET's names) is placed in the judged block, and
    the deterministic criterion in the deterministic block. The criterion IDs are neutral, so the
    separation follows the package's declared kind (`kind = 'mcq'`), not band names or ID
    conventions. No field of the separated rollup combines the two.

    Disclosed mismatch: the row asks for a separation "driven by the column" (`evaluation_mode`),
    but `grade.py` records that no shipped schema carries that column on criteria, and classifies
    by `kind`, the declared equivalent. This case asserts that equivalent."""
    from aeh.grade import separated_rollup
    from aeh.pkg import GradePolicy, PackageCatalog
    from tests.support.grade_vocabulary import write_criterion_scores

    submissions = ("S001", "S002")
    store = open_store(tmp_data_dir)
    try:
        _orch, run_id, version = seed_run(store, submissions=submissions, criteria=(
            {"criterion_id": "CA", "kind": "open", "scoring_model": "atomic"},
            {"criterion_id": "CB", "kind": "mcq", "scoring_model": "deterministic"}))
        PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch").set_grade_policy(
            version, GradePolicy(combination="weighted_sum"))
        cohort = store.cohort(ORCH_COHORT_ID)
        write_criterion_scores(cohort, [(s, "CA", "correct", 1.0, "auto") for s in submissions]
                               + [(s, "CB", "incorrect", 0.0, "auto") for s in submissions])
        import aeh.grade as grade

        grade.open_grade(store).compute_all(run_id)
        rollup = separated_rollup(run_id, store)
    finally:
        store.close()
    judged = {c.criterion_id for c in rollup.judged.criteria}
    deterministic = {c.criterion_id for c in rollup.deterministic.criteria}
    assert judged == {"CA"} and deterministic == {"CB"}, (
        f"the separation did not follow the declared kind: judged {judged}, deterministic {deterministic}")
    combined = [f.name for f in dataclasses.fields(rollup) if f.name not in ("judged", "deterministic")
                and re.search(r"total|combined|overall|mean", f.name)]
    assert not combined, f"the separated rollup carries a combined figure: {combined}"


def test_tc_req_62_a_deterministic_label_is_excluded_by_its_evaluation_mode_column(tmp_data_dir):
    """`TC-REQ-62` (`M-STATS` → `M-DET`, CT-DET-06, CT-STATS-01): two blind labels identical except
    for `evaluation_mode` are stored in Tier D and read back through `open_stats`. The judged one is
    admissible and the deterministic one is not. Flipping the deterministic row's column to
    `judged` makes it admissible, so the filter reads the column rather than inferring the mode
    some other way."""
    import sqlite3

    from aeh.stats import open_stats
    from tests.integration.store.test_purge import _promote, _seed_cohort

    cohort_id = "c-req-62"
    store = open_store(tmp_data_dir)
    try:
        _seed_cohort(store, cohort_id, with_sentinel=False)
        _promote(store, cohort_id)
        path = store.durable_path()
    finally:
        store.close()

    def insert(label_id, mode):
        with sqlite3.connect(path) as raw:
            raw.execute("INSERT INTO label (label_id, run_id, student_ref, criterion_id, label_type, band, "
                        "cohort_id, evaluation_mode, saw_system_output) "
                        "VALUES (?, 'run-1', 'ref-1', 'CRIT-1', 'blind', 'b1', ?, ?, 0)",
                        (label_id, cohort_id, mode))

    insert("blind-judged", "judged")
    insert("blind-deterministic", "deterministic")
    ids = lambda: sorted(getattr(l, "label_id", None) for l in open_stats(tmp_data_dir, cohort_id=cohort_id)  # noqa: E731
                         .admissible_labels())
    before = ids()
    with sqlite3.connect(path) as raw:
        raw.execute("UPDATE label SET evaluation_mode = 'judged' WHERE label_id = 'blind-deterministic'")
    after = ids()
    assert before == ["blind-judged"], f"admissible before the flip: {before}"
    assert after == ["blind-deterministic", "blind-judged"], f"admissible after the flip: {after}"


def test_tc_req_85_grading_completes_with_synthesis_wholly_absent(tmp_data_dir):
    """`TC-REQ-85` (`M-GRADE` → `M-SYNTH`, CT-SYNTH-05/07/08, CT-GRADE-01): no statement in M-SYNTH
    writes `submission_grade`. For a run where synthesis never ran (no narrative exists for any
    question, and a synthesis attempt against an unavailable backend failed), `compute_all` grades
    every submission and `finalize` settles them: nothing in grading waits on or fails for
    synthesis. A submission missing a criterion, which also has no narrative, reads `incomplete`
    for the missing input; the fully scored ones do not, so an absent narrative is never read as
    incompleteness."""
    import aeh.synth as synth
    from aeh.grade import open_grade
    from aeh.pkg import GradePolicy, PackageCatalog
    from tests.support.grade_vocabulary import grade_rows, write_criterion_scores

    synth_sql = " ".join(str(v) for v in synth.SYNTH_STATEMENTS.values())
    assert not re.search(r"\b(INSERT|UPDATE|REPLACE|DELETE)\b[^;]*\bsubmission_grade\b", synth_sql, re.I), (
        "M-SYNTH has a write path to submission_grade")
    submissions = ("S001", "S002", "S003")
    store = open_store(tmp_data_dir)
    try:
        _orch, run_id, version = seed_run(store, submissions=submissions, criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        from tests.support.synth_vocabulary import synth_ref

        class Down:
            def complete(self, prompt, model_ref, params):
                from aeh.prov import ProviderUnavailableError

                raise ProviderUnavailableError("synthesis backend down")

        synth_failed = None
        try:
            synth.SynthesisWorker(store, Down(), synth_ref()).synthesize_submission(run_id, "S001")
        except Exception as error:
            synth_failed = error
        PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch").set_grade_policy(
            version, GradePolicy(combination="weighted_sum"))
        cohort = store.cohort(ORCH_COHORT_ID)
        write_criterion_scores(cohort, [(s, "C1", "B2", 2.0, "auto") for s in submissions[:2]])
        narratives = cohort.query("SELECT COUNT(*) AS n FROM narrative")[0]["n"]
        service = open_grade(store)
        report = service.compute_all(run_id)
        finalize = getattr(service, "finalize_batch", None) or getattr(service, "finalize")
        try:
            finalize(run_id, actor="teacher")
        except TypeError:
            finalize(run_id)
        rows = grade_rows(cohort)
    finally:
        store.close()
    assert narratives == 0, "fixture: narratives exist"
    by_sub = {r["submission_id"]: r for r in rows}
    assert report.computed == 3 and len(rows) == 3, f"grading did not complete without synthesis: {report}"
    assert all(r.get("finalized_at") for r in rows if r["state"] != "incomplete"), (
        f"finalization did not settle every complete grade: {rows}")
    assert by_sub["S003"]["state"] == "incomplete", (
        f"a submission with a missing criterion and no narrative reads {by_sub['S003']['state']!r}, "
        f"not incomplete")
    assert all(by_sub[s]["state"] != "incomplete" for s in ("S001", "S002")), (
        "absent narratives made a fully scored submission incomplete")


def test_tc_req_86_review_carries_no_number_from_synthesis_and_honours_the_flag():
    """`TC-REQ-86` (`M-REVIEW` → `M-SYNTH`, CT-SYNTH-01/03): `SynthesisResult` declares no numeric
    field. Two queue rows carry narratives: a benign one flagged by M-SYNTH (`score_claim_flag = 1`)
    and a numeral-bearing one left unflagged. M-REVIEW must withhold the flagged narrative, and must
    show the unflagged one unchanged: it honours the flag and does not re-check the text."""
    from aeh.review import build_review
    from aeh.synth import SynthesisResult
    from tests.support import broken_review_fixtures as broken

    numeric = [f.name for f in dataclasses.fields(SynthesisResult)
               if f.type in (int, float, "int", "float", "int | None", "float | None")]
    base = broken.flagged_population(2, criteria=2)
    flagged_text = "The response explains the mechanism clearly."
    unflagged_text = "The response scored 4 out of 5 on reasoning."
    from aeh.synth import has_score_claim

    assert has_score_claim(unflagged_text), "fixture: the unflagged text must match the score-claim patterns"
    rows = [dataclasses.replace(base[0]), dataclasses.replace(base[1])]
    extended = []
    for row, text, flag in ((rows[0], flagged_text, 1), (rows[1], unflagged_text, 0)):
        payload = {**{f.name: getattr(row, f.name) for f in dataclasses.fields(row)},
                   "narrative": text, "score_claim_flag": flag}
        extended.append(type("Row", (), payload)())
    queue = build_review(scores=extended).build_queue(run_id="run-1", budget_minutes=600)
    by_score = {item.score_id: item for item in queue.shown}
    flagged_item, unflagged_item = by_score[rows[0].score_id], by_score[rows[1].score_id]
    problems = []
    if numeric:
        problems.append(f"SynthesisResult carries numeric fields: {numeric}")
    if flagged_item.narrative == flagged_text:
        problems.append("M-REVIEW shows a narrative M-SYNTH flagged and suppressed. [When written: "
                        "M-REVIEW has no narrative read at all; review.py's item builder copies "
                        "row.narrative verbatim and never reads score_claim_flag. The fix is a read "
                        "of the narrative together with its flag, suppressing on the flag.]")
    if unflagged_item.narrative != unflagged_text:
        problems.append(f"M-REVIEW altered an unflagged narrative (a second check): {unflagged_item.narrative!r}")
    assert not problems, "\n".join(problems)


def test_tc_req_87_the_console_honours_the_flag_and_filters_nothing_itself(tmp_data_dir):
    """`TC-REQ-87` (`M-CONSOLE` → `M-SYNTH`, CT-SYNTH-01/03, CT-CONSOLE-13): the student view (S13)
    renders narratives stored for one submission. A benign narrative flagged by M-SYNTH is
    withheld. A numeral-bearing narrative M-SYNTH left unflagged is rendered verbatim: the console
    applies the flag it was given and runs no score-claim filter of its own."""
    from aeh.console import SCREENS, build_console

    benign = "The response explains the mechanism clearly and in order."
    numeral = "The response scored 4 out of 5 on reasoning."
    store = open_store(tmp_data_dir)
    try:
        _orch, run_id, _v = seed_run(store, submissions=("S001",), criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            for i, (text, flag) in enumerate(((benign, 1), (numeral, 0))):
                tx.execute("INSERT INTO narrative (narrative_id, submission_id, run_id, level, question_id, "
                           "text, score_claim_flag) VALUES (:n, 'S001', :r, 'l1_question', :q, :t, :f)",
                           n=f"n-{i}", r=run_id, q=f"Q{i + 1}", t=text, f=flag)
        page = build_console(store=store).render(SCREENS["S13"], ref="S001").html
    finally:
        store.close()
    assert benign not in page and "withheld" in page, "the console rendered a narrative M-SYNTH flagged"
    assert numeral in page, "the console filtered a narrative M-SYNTH left unflagged (a second filter)"
