"""The smoke suite (TS-50, issue #143) — the run through the assembled pipeline.

`TC-SMOKE-09` (`FR-ORCH-01`) — the three-unit run enumerates, executes and completes
against the fixture provider; fails if any unit is missing, duplicated, or left open.
`TC-SMOKE-10` (`FR-GRADE-01`) — that run produces a `submission_grade` for every
submission; fails if the grade is absent or empty.

The world is the legal minimal three-unit shape: panel sizes 2/4/0 are refused by
`resolve_run_config`, so "exactly three" is one submission, one package carrying an mcq
criterion and an open atomic one, and a one-judge edge panel — one `deterministic` unit
(null judge, `kind='mcq'`'s discriminator), one `extract` unit (null judge), one `score`
unit (the panel's judge at `atomic`'s base depth 1). Everything that runs is real — the
orchestrator's ledger (enumerate → start → lease → complete, with the run-row completion
probe), `M-DET`'s evaluator, `M-EXTRACT`'s worker, `M-JUDGE`'s worker, `M-AGG`'s
aggregator, `M-GRADE`'s service — with the shipped `RecordedFixtureProvider` as the only
egress, every reply recorded under the exact request key the real workers assemble (the
`judge_world` drive pattern, issue #79's TS-31 precedent).

Disclosed stand-ins (the suite's two, both the shared vocabulary's):
- the judged criterion's `criterion_score` row is written through
  `grade_vocabulary.write_criterion_scores` — `aggregate()` is pure (`CT-AGG-01`) and no
  shipped module persists judged scores; the stand-in writes exactly the row M-AGG's
  writer will, from the aggregate's own return values. The mcq row needs no stand-in:
  it is written by the real `M-DET` evaluator in this very run.
- the six integrity signals arrive favourable via `agg_vocabulary.signals()` — the
  citation gate already ran inside the scoring worker's dispatch; `M-INTEG`'s
  second-extraction comparison is not this case's leg.

The document is a disclosed direct write in `seed_head_document`'s column shape (real
blob bytes, real fences) — `M-INGEST` is TC-SMOKE-08's leg, not this one's; the answer
region is `det_vocabulary.seed_answer_region`'s, in the column shape ingest's writer
produces.

`Written ahead of implementation: yes` is stale — every module in the chain landed
(#57-#118); the cases run green by design.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from aeh.agg import aggregate
from aeh.conf import CohortRef, resolve_run_config
from aeh.det import BAND_CORRECT, ROUTING_AUTO, STATE_FINAL, DeterministicEvaluator
from aeh.extract import EXTRACT_STATEMENTS
from aeh.grade import open_grade
from aeh.orch import (
    EXTRACTOR_VERSION,
    STAGE_DETERMINISTIC,
    STAGE_EXTRACT,
    STAGE_SCORE,
    Orchestrator,
    compute_work_id,
)
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.support.agg_vocabulary import criterion as agg_criterion, signals
from tests.support.conf_builders import EDGE_JUDGE, edge_cfg, edge_panel
from tests.support.det_vocabulary import seed_answer_region
from tests.support.extract_vocabulary import (
    extractor_ref,
    sampling_params,
    span_completion,
    verdict_completion,
)
from tests.support.grade_vocabulary import grade_rows, write_criterion_scores
from tests.support.judge_run import (
    CONTROL_BAND,
    CONTROL_CONFIDENCE,
    byte_span,
    canonical_document,
    default_pages,
    warm_judged_modules,
)
from tests.support.orch_run import seed_cohort, seed_package
from tests.support.store_api import statement

ISSUE = "#143"

COHORT_ID = "c-2026-11A-smoke"
SUBMISSION_ID = "s-smoke"
PACKAGE_ID = "pkg-smoke-run"
MCQ_CRITERION = "M1"
JUDGED_CRITERION = "C1"
DOCUMENT_ID = "doc-s-smoke"
_STAMP = "2026-01-01T00:00:00+00:00"


def _build_world(store, provider):
    """The three-unit world: package seeded, cohort and document and answer region in,
    the run created and enumerated. NOT started — the cases assert on the enumeration
    first, then drive."""
    warm = warm_judged_modules()
    version = seed_package(
        store,
        (
            {
                "criterion_id": JUDGED_CRITERION,
                "kind": "open",
                "scoring_model": "atomic",
                "band_count": 2,
            },
        ),
        package_id=PACKAGE_ID,
    )
    catalog = PackageCatalog(store.package(PACKAGE_ID), package_id=PACKAGE_ID)
    # The judged criterion's declared band set — the judge-run vocabulary's two bands,
    # through the real M-PKG writer (`FR-PKG-06`).
    catalog.add_band(
        version, JUDGED_CRITERION, 0, "emerging", 0.0, "the criterion is partly met"
    )
    catalog.add_band(
        version, JUDGED_CRITERION, 1, "secure", 10.0, "the criterion is met"
    )
    # The mcq criterion, exactly as `seed_det_package` seeds one: options, key, the
    # two-band deterministic scale (`FR-SETUP-13`).
    catalog.add_criterion(
        version,
        MCQ_CRITERION,
        question_id="Q1",
        kind="mcq",
        scoring_model="atomic",
        band_count=2,
    )
    catalog.add_band(version, MCQ_CRITERION, 0, "incorrect", 0.0)
    catalog.add_band(version, MCQ_CRITERION, 1, "correct", 1.0)
    catalog.set_mcq_options(
        version, MCQ_CRITERION, [(o, f"Option {o}") for o in ("A", "B", "C", "D")]
    )
    catalog.set_answer_key(version, MCQ_CRITERION, ("B",))

    cohort_id = seed_cohort(store, [SUBMISSION_ID], cohort_id=COHORT_ID)
    handle = store.cohort(cohort_id)
    # The head document: REAL blob bytes behind the content hash, fenced canonically,
    # in `seed_head_document`'s column shape (created_at explicit — det's head query
    # orders by it).
    markdown = canonical_document("\n".join(default_pages(SUBMISSION_ID)))
    content_hash = store.blobs().put(markdown.encode("utf-8"))
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO document (document_id, submission_id, content_hash, created_at) "
            "VALUES (:d, :s, :h, :created)",
            d=DOCUMENT_ID,
            s=SUBMISSION_ID,
            h=content_hash,
            created=_STAMP,
        )
    # The mcq answer: one resolved selection mark, B — the declared key's answer.
    seed_answer_region(store, cohort_id, DOCUMENT_ID, "Q1", selection="B")

    resolved = resolve_run_config(
        edge_cfg(panel=edge_panel(1)),
        CohortRef(cohort_id=cohort_id, consent_class="synthetic"),
    )
    orchestrator = Orchestrator(store)
    run_id = orchestrator.create_run(cohort_id, version, resolved)
    enumeration = orchestrator.enumerate_units(run_id)
    spans = [byte_span(markdown, needle) for needle in default_pages(SUBMISSION_ID)]
    return SimpleNamespace(
        store=store,
        provider=provider,
        warm=warm,
        orchestrator=orchestrator,
        run_id=run_id,
        version=version,
        cohort_id=cohort_id,
        handle=handle,
        enumeration=enumeration,
        markdown=markdown,
        spans=spans,
        resolved=resolved,
    )


def _units_of(world):
    """The run's ledger rows, in stable order — stage, then judge (None sorts first)."""
    return world.handle.query(
        statement(
            "SELECT work_id, stage, criterion_id, judge_id, status FROM work_unit "
            "WHERE run_id = :r ORDER BY stage, judge_id"
        ),
        r=world.run_id,
    )


def _one_unit(world, stage):
    rows = [row for row in _units_of(world) if row["stage"] == stage]
    assert len(rows) == 1, (
        f"fixture bug: stage {stage!r} carries {len(rows)} units, expected exactly one"
    )
    return rows[0]


def _drive_run(world):
    """Start the run and execute all three legs through the real modules.

    The deterministic leg is `M-DET`'s cohort pass (its row is real); the extract and
    score legs lease through the orchestrator and drive the owning workers against the
    fixture provider, recording each reply under the exact request key first. Every
    unit ends `done` on the ledger. The caller has started the run; start() from
    anything but `pending` is refused."""
    det_unit = _one_unit(world, STAGE_DETERMINISTIC)
    DeterministicEvaluator(world.store).evaluate_cohort(world.run_id)
    world.orchestrator.complete(det_unit["work_id"])

    extract_units = list(world.orchestrator.lease("w-extract-smoke", STAGE_EXTRACT, 8))
    assert len(extract_units) == 1, (
        "precondition: the extract stage leased a different unit count than the "
        "enumeration wrote"
    )
    request = world.warm["extract"][0](extract_units[0], store=world.store)
    world.provider.record(
        world.warm["extract_prompt_fields"](request),
        extractor_ref(),
        sampling_params(),
        span_completion(world.spans, build_id=extractor_ref().build_id),
    )
    world.warm["extract"][1](world.store, world.provider, extractor_ref()).process(
        extract_units[0]
    )

    score_units = list(world.orchestrator.lease("w-judge-smoke", STAGE_SCORE, 8))
    assert len(score_units) == 1, (
        "precondition: the score stage leased a unit count other than one — "
        "the one-judge panel at atomic depth must enumerate exactly one arm"
    )
    ref = EDGE_JUDGE
    worker = world.warm["judge"](world.store, world.provider, ref)
    request = worker.assemble(score_units[0])
    world.provider.record(
        world.warm["judge_prompt_fields"](request),
        ref,
        sampling_params(),
        verdict_completion(
            CONTROL_BAND,
            CONTROL_CONFIDENCE,
            build_id=ref.build_id,
            cited_spans=world.spans,
        ),
    )
    result = worker.dispatch(request, ref)
    worker.persist(score_units[0], result)

    # The workers close their own units inside their payload transactions (`persist`'s
    # guarded done-marking), which bypasses the lifecycle probe by design — the probe
    # fires on the orchestrator's lifecycle writes. The sanctioned closer for a run
    # whose last unit closed underneath a worker is the resume pass: "a resume that
    # opens a finished run completes it" (`resume`'s own docstring, `FR-ORCH-25`).
    world.orchestrator.resume(world.run_id)


def test_tc_smoke_09_three_unit_run_enumerates_executes_completes(
    tmp_data_dir, make_fixture_provider
):
    """`TC-SMOKE-09` — the three-unit run enumerates, executes and completes against
    the fixture provider.

    Oracle: **shape, content address, execution artifacts, completion**. The enumeration
    writes exactly three units — one per stage, the mcq criterion judged by nobody, the
    judged criterion scored by the panel's one judge — and each row's `work_id` equals
    `compute_work_id` over the nine `WORK_ID_INPUTS` recomputed here from the run row
    and the module constant (the content address is the requirement, not an
    implementation detail); a second enumeration is a byte-identical `no-op` (`NFR-ORCH-05`,
    `FR-ORCH-03`). After the drive, every unit is `done` and the run row is `complete`
    (`FR-ORCH-25`'s last-unit probe), `progress` reports `complete`, and each leg
    produced its artifact: a `criterion_score` row from the real evaluator, an
    `evidence` row naming the build that answered, and a `verdict` row in the declared
    band.
    """
    store = open_store(tmp_data_dir)
    world = _build_world(store, make_fixture_provider())
    report = world.enumeration

    units = _units_of(world)
    assert len(units) == 3, (
        f"TC-SMOKE-09: the three-unit run enumerated {len(units)} units. FR-ORCH-01: "
        "one submission, an mcq criterion plus an open atomic one, and a one-judge "
        "panel is exactly one deterministic, one extract and one score unit — a shape "
        "that misses or duplicates a unit mis-schedules the whole pipeline."
    )
    assert sorted(row["stage"] for row in units) == [
        STAGE_DETERMINISTIC,
        STAGE_EXTRACT,
        STAGE_SCORE,
    ]
    det_unit = _one_unit(world, STAGE_DETERMINISTIC)
    extract_unit = _one_unit(world, STAGE_EXTRACT)
    score_unit = _one_unit(world, STAGE_SCORE)
    assert det_unit["criterion_id"] == MCQ_CRITERION and det_unit["judge_id"] is None
    assert (
        extract_unit["criterion_id"] == JUDGED_CRITERION
        and extract_unit["judge_id"] is None
    ), "extraction is judge-independent (§7.2 Rule 2) — the extract unit carries no judge"
    assert score_unit["criterion_id"] == JUDGED_CRITERION
    assert score_unit["judge_id"] == EDGE_JUDGE.build_id

    # The content address, recomputed from the nine inputs' own provenance: run row
    # for the frozen panel and prompt template, the module constant for the extractor
    # version — a hash over anything else addresses a unit nobody computed.
    run_row = world.handle.query(
        statement("SELECT panel_config, prompt_template_v FROM run WHERE run_id = :r"),
        r=world.run_id,
    )[0]
    expected_ids = {
        compute_work_id(
            run_id=world.run_id,
            stage=row["stage"],
            submission_id=SUBMISSION_ID,
            criterion_id=row["criterion_id"],
            judge_id=row["judge_id"],
            package_version_id=world.version,
            panel_config=run_row["panel_config"],
            prompt_template_version=run_row["prompt_template_v"],
            extractor_version=EXTRACTOR_VERSION,
        )
        for row in units
    }
    assert {row["work_id"] for row in units} == expected_ids, (
        "TC-SMOKE-09: a work_id does not match its own nine-input hash. The content "
        "address is what makes invalidation automatic (NFR-EXTRACT-02/03); a ledger "
        "that computes ids it cannot recompute has lost the property the resume and "
        "re-run stories stand on."
    )

    second = world.orchestrator.enumerate_units(world.run_id)
    assert second.status == "no-op" and second.units_inserted == 0, (
        "TC-SMOKE-09: re-enumerating a run's own units wrote rows. INSERT OR IGNORE "
        "is FR-ORCH-03's no-op guarantee — a duplicate-writing enumeration double-scores "
        "every resumed run."
    )
    assert second.work_ids == report.work_ids, (
        "TC-SMOKE-09: the second enumeration's work_id set differs from the first. "
        "NFR-ORCH-05: the same inputs enumerate byte-identical sets."
    )

    assert world.orchestrator.start(world.run_id) == "running"
    _drive_run(world)

    statuses = {row["work_id"]: row["status"] for row in _units_of(world)}
    assert set(statuses.values()) == {"done"}, (
        f"TC-SMOKE-09: the run left units open — {statuses}. FR-ORCH-01: the run "
        "executes to completion; a unit that never closes holds the grade hostage."
    )
    run_after = world.handle.query(
        statement("SELECT status FROM run WHERE run_id = :r"), r=world.run_id
    )[0]
    assert run_after["status"] == "complete", (
        "TC-SMOKE-09: the run row did not reach 'complete' when its last unit closed. "
        "FR-ORCH-25's probe is the lifecycle's closure — a pipeline that finishes its "
        "work but never settles the run leaves the operator reading a run that is "
        "neither running nor done."
    )
    assert world.orchestrator.progress(world.run_id).complete is True

    # The execution artifacts, one per leg — the payloads the stages own (#68 onward).
    evidence = world.store.cohort(world.cohort_id).query(
        EXTRACT_STATEMENTS["select_evidence"], work_id=extract_unit["work_id"]
    )
    assert evidence, (
        "TC-SMOKE-09: the extract leg executed but wrote no evidence row. The payload "
        "is the owning stage's to persist — a completed extract unit with no evidence "
        "is a ledger that says done and a pipeline that has nothing."
    )
    assert evidence[0]["resolved_build"] == extractor_ref().build_id, (
        "TC-SMOKE-09: the evidence row does not name the build that answered "
        "(FR-PROV-04). Provenance is the answer's only identity on an edge box."
    )
    verdicts = world.handle.query(
        statement(
            "SELECT band, band_ordinal FROM verdict WHERE work_id = :w"
        ),
        w=score_unit["work_id"],
    )
    assert [v["band"] for v in verdicts] == [CONTROL_BAND], (
        "TC-SMOKE-09: the score leg's verdict did not land in the declared band. "
        "FR-JUDGE-04: every verdict names a declared band — the panel's word must "
        "arrive exactly as the package declared it."
    )
    det_row = world.handle.query(
        statement(
            "SELECT band, points, state, routing FROM criterion_score "
            "WHERE submission_id = :s AND criterion_id = :c"
        ),
        s=SUBMISSION_ID,
        c=MCQ_CRITERION,
    )[0]
    assert det_row["band"] == BAND_CORRECT and float(det_row["points"]) == 1.0, (
        "TC-SMOKE-09: the deterministic leg scored the key answer other than correct "
        "at the declared band points. FR-DET-01 is exact-match lookup — the one leg "
        "with no model in it must never miss."
    )
    assert det_row["state"] == STATE_FINAL and det_row["routing"] == ROUTING_AUTO


def test_tc_smoke_10_run_produces_submission_grade_for_every_submission(
    tmp_data_dir, make_fixture_provider
):
    """`TC-SMOKE-10` — that run produces a `submission_grade` for every submission.

    Oracle: **the row, whole**. The panel's verdict aggregates through the real
    `aggregate()` into the declared band at the declared points, routed provisional —
    one judge's word awaits its panel (`FR-ORCH-13`), never auto-accepted — and
    `compute_all` over the run's two criterion scores writes the submission's grade
    row: total equal to the sum of its criterion rows under the default policy
    (unweighted sum, raw points), coverage counting what each row is, `criteria_missing`
    zero, and — the run being complete with a null review window — state `final`
    (`FR-GRADE-10`), with no operator row queued behind a fully-scored cohort
    (`TC-GRADE-01`).
    """
    store = open_store(tmp_data_dir)
    world = _build_world(store, make_fixture_provider())
    world.orchestrator.start(world.run_id)
    _drive_run(world)

    score_unit = _one_unit(world, STAGE_SCORE)
    verdicts = world.handle.query(
        statement(
            "SELECT band_ordinal, self_confidence, uncited FROM verdict "
            "WHERE work_id = :w"
        ),
        w=score_unit["work_id"],
    )
    assert verdicts, "precondition: the score leg persisted no verdict"
    panel_verdicts = [
        SimpleNamespace(
            ordinal=int(row["band_ordinal"]),
            cited=not bool(row["uncited"]),
            self_confidence=float(row["self_confidence"]),
        )
        for row in verdicts
    ]
    catalog = PackageCatalog(store.package(PACKAGE_ID), package_id=PACKAGE_ID)
    crit = agg_criterion(
        [
            SimpleNamespace(
                band=row["band"], ordinal=row["ordinal"], points=row["points"]
            )
            for row in catalog.bands(JUDGED_CRITERION)
        ],
        scoring_model="atomic",
        criterion_id=JUDGED_CRITERION,
    )
    score = aggregate(panel_verdicts, crit, signals())
    assert score.band == CONTROL_BAND and float(score.points) == 10.0, (
        "TC-SMOKE-10: the panel's verdict did not aggregate to the declared band at "
        "the declared points. FR-AGG-02: the median ordinal maps through M-PKG's "
        "canonical band table, exactly once."
    )
    assert score.routing == "provisional" and score.state == "provisional_unreviewed", (
        "TC-SMOKE-10: a single-judge score routed as settled. FR-ORCH-13: one judge's "
        "word awaits its panel — a routing that auto-accepts a one-judge panel makes "
        "the review queue decorative."
    )

    # The disclosed M-AGG stand-in: exactly the row the aggregation's own values name.
    write_criterion_scores(
        world.handle,
        [(SUBMISSION_ID, JUDGED_CRITERION, score.band, score.points, score.routing)],
    )

    grade_report = open_grade(store).compute_all(world.run_id)
    assert grade_report.submitted == 1 and grade_report.computed == 1
    rows = grade_rows(world.handle)
    assert len(rows) == 1, (
        f"TC-SMOKE-10: {len(rows)} submission_grade row(s) for a one-submission run. "
        "FR-GRADE-01: every submission of the run is graded — the batch pass with no "
        "teacher action anywhere in the path."
    )
    row = rows[0]
    assert row["submission_id"] == SUBMISSION_ID
    scores = world.handle.query(
        statement(
            "SELECT points FROM criterion_score WHERE submission_id = :s "
            "ORDER BY criterion_id"
        ),
        s=SUBMISSION_ID,
    )
    expected_total = sum(float(r["points"]) for r in scores)
    assert row["total"] == pytest.approx(expected_total), (
        "TC-SMOKE-10: the grade's total is not the sum of its criterion scores. The "
        "default policy is the unweighted sum of raw points — a total that does not "
        "reproduce from its own rows is not a grade anyone can audit."
    )
    assert row["state"] == "final", (
        "TC-SMOKE-10: the grade did not settle after the run completed with a null "
        "review window. FR-GRADE-10: run completion settles the grade — a cohort that "
        "finished its run must not be left reading provisional figures forever."
    )
    assert row["criteria_total"] == 2 and row["criteria_missing"] == 0, (
        "TC-SMOKE-10: the coverage counters do not account for the package's two "
        "criteria. A grade that cannot say what it covered cannot say what it missed."
    )
    assert row["criteria_auto"] == 1 and row["criteria_provisional"] == 1, (
        "TC-SMOKE-10: the coverage split is wrong — one auto-accepted deterministic "
        "row and one provisional single-judge row is the truth this run produced."
    )
    assert world.handle.query(
        statement("SELECT COUNT(*) AS n FROM review_queue WHERE submission_id = :s"),
        s=SUBMISSION_ID,
    )[0]["n"] == 0, (
        "TC-SMOKE-10: a fully-scored submission gained an operator routing row. "
        "TC-GRADE-01: the review queue gains a row only where an input is missing — "
        "a queue entry for a scored submission sends a teacher to do a machine's work."
    )
