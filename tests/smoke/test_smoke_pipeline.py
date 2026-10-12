"""The smoke suite (TS-50, issue #143) — the run through the assembled pipeline.

`TC-SMOKE-09` (`FR-ORCH-01`) — the three-unit run enumerates, executes and completes
against the fixture provider; fails if any unit is missing, duplicated, or left open.
**Re-based onto the composed pipeline** (TS-98, issue #392; §5.0's re-base column):
"enumerates, executes and completes" means `aeh.pipeline.run_to_completion` returns
`complete`, and every `done` unit has its payload row (`CT-PIPE-02`'s invariant, queried
here per stage) — not merely that a hand-driven set of legs all closed their units.

`TC-SMOKE-10` (`FR-GRADE-01`) — that run produces a `submission_grade` for every
submission; fails if the grade is absent or empty. **Re-based**: the grades come from the
same composed run — `run_to_completion`'s own grade stage (`FR-PIPE-06`), not a caller's
`compute_all` — and the judged criterion's score row is the one the composed aggregation
hook wrote, through the real `write_score` in its own transaction.

The world is the legal minimal three-unit shape: panel sizes 2/4/0 are refused by
`resolve_run_config`, so "exactly three" is one submission, one package carrying an mcq
criterion and an open atomic one, and a one-judge edge panel — one `deterministic` unit
(null judge, `kind='mcq'`'s discriminator), one `extract` unit (null judge), one `score`
unit (the panel's judge at `atomic`'s base depth 1). Everything that runs is real — the
composed pipeline's own driver over the orchestrator's ledger, `M-DET`'s evaluator,
`M-EXTRACT`'s worker, `M-JUDGE`'s worker, `M-AGG`'s hook, `M-GRADE`'s service — with the
shipped `RecordedFixtureProvider` as the only egress, every reply recorded under the exact
request key the real workers assemble (the `judge_world` drive pattern, issue #79's TS-31
precedent).

**The former stand-ins are gone, replaced by the composition's own paths** (the re-base's
honest substitution — §5.0 no longer admits them):
- the judged criterion's `criterion_score` row used to be written through
  `grade_vocabulary.write_criterion_scores` because no shipped module persisted judged
  scores and `aggregate()` is pure (`CT-AGG-01`). The composed hook IS that module: it
  aggregates the cell in-transaction and persists through the real `write_score`, so this
  suite reads the row the pipeline itself wrote.
- the six integrity signals used to arrive favourable via `agg_vocabulary.signals()`.
  The composed hook reads them from `M-INTEG`'s gate over the run's real ledger rows —
  the citation gate already ran inside the scoring worker's dispatch, and the hook's
  signal read is that gate's output, not a caller's.

Disclosed shape (the deltas the composition forces, stated here once):
- the drive is given `extractor=extractor_ref()` — the design's own exact-identity seam
  (pipeline.md gap 2): a replay against a recorded corpus supplies the identity the
  recording carries, here the HLD §9.9 worked example's model the suite has always
  recorded under, rather than the run config's transcriber the default derivation would
  name.
- the corpus declares a second extractor family (`SECOND_FAMILY_REF`, the same
  declaration `pipe_world.corpus_refs` makes for F-DEV-PIPE). The shipped policy is
  fail-closed on an unmeasured extractor disagreement (`integ/signals.py`: the verdict
  is None only when no second family was configured), and an unmeasured signal is an
  adverse one — it escalates the cell and caps its confidence. The minimal corpus
  cannot carry a widened panel, so the second family is declared and its reply is
  composed on first sight under the same rule as the judge reply: the same span set the
  first family read, which is the corpus's own declaration — one document, one true
  span set.
- the extract reply is pre-recorded under the exact request key the real worker
  assembles; the judge reply CANNOT be pre-recorded — its key embeds the extracted
  evidence, which does not exist until the composed drive's own extract leg runs — so it
  is composed on first sight and recorded through the shipped `record()` machinery
  (`_CaptureOnMiss`, `F-DEV-PIPE`'s capture precedent): the reply is the corpus's
  control reply, byte-for-byte what the hand drive used to record. The composed drive
  also runs `M-INTEG`'s second-extraction unit (the integrity pre-hook enqueues it), a
  leg the hand drive never drove — its request replays the extract recordings, and its
  evidence row is one more payload the `CT-PIPE-02` invariant counts.
- the composed drive runs the synthesis leg after completion (`FR-PIPE-06`); over this
  corpus it narrates nothing and calls nothing (the trace reads "0 narratives, 0
  failures") — narratives are F-SYNTH's leg, not the smoke suite's.
- no validation baseline is recorded on the smoke package: the escalation hook reads its
  baseline from the package (`FR-PIPE-15`), finds none, and the no-data concern (weighted
  0.5, `CT-STATS-09`) plus the control reply's self-confidence (weighted 0.25 × 0.38)
  stays under the escalation threshold — no cell escalates, and the one-judge cell
  awaits its panel, which is this suite's oracle, reached through the shipped policy
  rather than a caller's argument.

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

from aeh.det import BAND_CORRECT, ROUTING_AUTO, STATE_FINAL
from aeh.extract import EXTRACT_STATEMENTS
from aeh.orch import (
    EXTRACTOR_VERSION,
    STAGE_DETERMINISTIC,
    STAGE_EXTRACT,
    STAGE_SCORE,
    Orchestrator,
    compute_work_id,
)
from aeh.orch.work_units import WorkUnit
from aeh.pkg import PackageCatalog
from aeh.pipeline import run_to_completion
from aeh.prov import FixtureMissingError
from aeh.store import open_store
from aeh.conf import CohortRef, resolve_run_config
from tests.support.conf_builders import EDGE_JUDGE, edge_cfg, edge_panel
from tests.support.det_vocabulary import seed_answer_region
from tests.support.extract_vocabulary import (
    extractor_ref,
    sampling_params,
    span_completion,
    verdict_completion,
)
from tests.support.grade_vocabulary import grade_rows
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

#: The corpus's second extractor family — the same declaration `pipe_world.corpus_refs`
#: makes for F-DEV-PIPE, under this corpus's own build id. The shipped policy is
#: fail-closed on an unmeasured extractor disagreement, so the second family is part of
#: the replayed corpus's shape, not an option.
SECOND_FAMILY_REF = extractor_ref(
    build_id="vlm@sha256:smoke-extract-b", provider="local")


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


def _ledger_unit(world, stage, judge_id):
    """The unit as the ledger names it, assembled into the `WorkUnit` the workers
    read — WITHOUT leasing it. Recording needs the request key only, and the composed
    drive leases every unit itself; a unit held 'leased' here would be one the drive can
    never claim."""
    row = _one_unit(world, stage)
    return WorkUnit(
        work_id=row["work_id"],
        run_id=world.run_id,
        stage=stage,
        student_ref=f"ref-{SUBMISSION_ID}",
        student_name=None,
        submission_id=SUBMISSION_ID,
        criterion_id=row["criterion_id"],
        submission_text=None,
        judge=judge_id,
    )


def _record_replies(world):
    """Record the extract reply under the exact request key the real worker assembles —
    the `judge_world` pattern. The extract request is assembled from the ledger unit's
    identity (`submission_text` stays None: assembly resolves the head document from the
    store, exactly as the composed worker's own claim does). The judge reply is NOT
    pre-recordable: its request key embeds the extracted evidence (`M-JUDGE` assembles
    the evidence block from the store's evidence rows), which does not exist until the
    composed drive's own extract leg runs — so the judge reply is composed on first
    sight instead (`_CaptureOnMiss`)."""
    extract_unit = _ledger_unit(world, STAGE_EXTRACT, None)
    request = world.warm["extract"][0](extract_unit, store=world.store)
    world.provider.record(
        world.warm["extract_prompt_fields"](request),
        extractor_ref(),
        sampling_params(),
        span_completion(world.spans, build_id=extractor_ref().build_id),
    )


class _CaptureOnMiss:
    """The model boundary's capture shape (`F-DEV-PIPE`'s precedent, the same one
    `tests.support.composed_synth` discloses): the boundary answers a first sight of a
    request by composing the reply from the corpus's own declarations and records it
    through the shipped `record()` machinery, so every later identical request replays
    from the recording. The composition is the disclosure, not a second oracle: the
    judge reply is the corpus's control reply, byte-for-byte what the hand drive
    recorded; the second family's extract reply is the same span set the first family
    read — one document, one true span set."""

    def __init__(self, inner, world):
        self._inner = inner
        self._world = world

    def complete(self, payload, model_ref=None, params=None):
        role = getattr(model_ref, "role", None)
        if role in ("judge", "extractor"):
            try:
                return self._inner.complete(payload, model_ref, params)
            except FixtureMissingError:
                if role == "extractor":
                    reply = span_completion(
                        self._world.spans, build_id=model_ref.build_id)
                else:
                    reply = verdict_completion(
                        CONTROL_BAND,
                        CONTROL_CONFIDENCE,
                        build_id=model_ref.build_id,
                        cited_spans=self._world.spans,
                    )
                self._world.provider.record(payload, model_ref, params, reply)
                return self._inner.complete(payload, model_ref, params)
        return self._inner.complete(payload, model_ref, params)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _drive_composed(world):
    """The composed drive: `run_to_completion` over the started run — the deterministic
    evaluation first, then the dispatch passes with the integrity gate and the
    aggregation hook firing in-transaction, then synthesis and grading on completion.

    `extractor=` is the exact-identity seam (pipeline.md gap 2): this suite replays a
    recorded corpus, and the recording carries the identity it was captured under.
    `second_family=` is the corpus's second extractor reading, declared against the
    judged criterion in `high_risk_criteria` — the flag is what registers the
    second-family pass (`extract/worker.py`: a flagged criterion's SAME prompt runs a
    second time on the different family) — because the shipped policy is fail-closed on
    an unmeasured extractor disagreement."""
    inner = world.provider
    world.provider = _CaptureOnMiss(inner, world)
    try:
        return run_to_completion(
            world.store,
            world.run_id,
            provider=world.provider,
            run_config=world.resolved,
            extractor=extractor_ref(),
            second_family=SECOND_FAMILY_REF,
            high_risk_criteria=(JUDGED_CRITERION,),
        )
    finally:
        world.provider = inner


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
    `FR-ORCH-03`). The composed drive returns `complete`, every unit is `done` and the
    run row is `complete`, `progress` reports `complete` — and every `done` unit has its
    payload row (`CT-PIPE-02`'s invariant, queried per stage): the extract leg's
    `evidence` row naming the build that answered, the score leg's `verdict` row in the
    declared band, the deterministic leg's `criterion_score` row from the real evaluator.
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
    _record_replies(world)
    result = _drive_composed(world)
    assert result.status == "complete", (
        f"TC-SMOKE-09: the composed drive read {result.status!r} "
        f"({result.pause_reason!r}). The re-based oracle: run_to_completion returns "
        "complete — a smoke run that cannot close through the shipped driver is a "
        "composition defect, whatever a hand-driven leg set could force."
    )

    statuses = {row["work_id"]: row["status"] for row in _units_of(world)}
    assert set(statuses.values()) == {"done"}, (
        f"TC-SMOKE-09: the run left units open — {statuses}. FR-ORCH-01: the run "
        "executes to completion; a unit that never closes holds the grade hostage."
    )
    run_after = world.handle.query(
        statement("SELECT status FROM run WHERE run_id = :r"), r=world.run_id
    )[0]
    assert run_after["status"] == "complete"
    assert world.orchestrator.progress(world.run_id).complete is True

    # CT-PIPE-02's invariant, over this run's whole ledger: every done unit has its
    # payload row, per stage. Evidence and verdict are addressed by work_id;
    # criterion_score is addressed by its cell (run, submission, criterion) — the
    # deterministic leg's done unit and its row share the cell, not a work_id.
    for stage, payload, match in (
        (STAGE_EXTRACT, "evidence", "p.work_id = work_unit.work_id"),
        (STAGE_SCORE, "verdict", "p.work_id = work_unit.work_id"),
        (
            STAGE_DETERMINISTIC,
            "criterion_score",
            "p.run_id = work_unit.run_id AND p.submission_id = work_unit.submission_id "
            "AND p.criterion_id = work_unit.criterion_id",
        ),
    ):
        orphans = world.handle.query(
            statement(
                f"SELECT work_id FROM work_unit WHERE run_id = :r AND stage = :st "
                f"AND status = 'done' AND NOT EXISTS (SELECT 1 FROM {payload} p WHERE "
                f"{match})"
            ),
            r=world.run_id,
            st=stage,
        )
        assert not orphans, (
            f"TC-SMOKE-09: stage {stage!r} left done unit(s) {orphans} with no "
            f"{payload} row. CT-PIPE-02: a done unit's payload is the stage's own "
            "output — a ledger that says done over nothing is the silent-failure "
            "shape the invariant exists to refuse."
        )

    # The execution artifacts, one per leg — the payloads the stages own (#68 onward),
    # read directly.
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

    Oracle: **the row, whole, from the same composed run**. The judged cell aggregates
    through the composed hook — the real `aggregate()` over the real gate signals,
    persisted by the real `write_score` in the hook's own transaction — into the declared
    band at the declared points, routed provisional — one judge's word awaits its panel
    (`FR-ORCH-13`), never auto-accepted — and `run_to_completion`'s own grade stage
    (`FR-PIPE-06`, not a caller's `compute_all`) writes the submission's grade row: total
    equal to the sum of its criterion rows under the default policy (unweighted sum, raw
    points), coverage counting what each row is, `criteria_missing` zero, and — the run
    being complete with a null review window — state `final` (`FR-GRADE-10`), with no
    operator row queued behind a fully-scored cohort (`TC-GRADE-01`).
    """
    store = open_store(tmp_data_dir)
    world = _build_world(store, make_fixture_provider())
    world.orchestrator.start(world.run_id)
    _record_replies(world)
    result = _drive_composed(world)
    assert result.status == "complete" and result.grades_computed == 1, (
        f"TC-SMOKE-10: the composed drive read {result.status!r} with "
        f"{result.grades_computed} grade(s) computed. The re-based oracle: the grades "
        "come from the same composed run — the driver's own grade stage — so a smoke "
        "run that needs a caller's compute_all is not the pipeline the design shipped."
    )

    # The judged criterion's score row, as the composed aggregation hook wrote it: the
    # one judge's verdict aggregated through the real `aggregate()` over the real gate
    # signals and persisted in-transaction — no `write_criterion_scores` stand-in, no
    # caller-assembled `signals()`.
    judged_row = world.handle.query(
        statement(
            "SELECT band, points, judge_count, routing, state FROM criterion_score "
            "WHERE submission_id = :s AND criterion_id = :c"
        ),
        s=SUBMISSION_ID,
        c=JUDGED_CRITERION,
    )[0]
    assert judged_row["band"] == CONTROL_BAND and float(judged_row["points"]) == 10.0, (
        "TC-SMOKE-10: the composed hook did not aggregate the verdict to the declared "
        "band at the declared points. FR-AGG-02: the median ordinal maps through "
        "M-PKG's canonical band table, exactly once."
    )
    assert judged_row["judge_count"] == 1, (
        "TC-SMOKE-10: the judged row does not carry the panel's own figure — the "
        "one-judge panel's count is what the row must say."
    )
    assert judged_row["routing"] == "provisional" and judged_row["state"] == (
        "provisional_unreviewed"
    ), (
        "TC-SMOKE-10: a single-judge score routed as settled. FR-ORCH-13: one judge's "
        "word awaits its panel — a routing that auto-accepts a one-judge panel makes "
        "the review queue decorative."
    )

    grade_rows_ = grade_rows(world.handle)
    assert len(grade_rows_) == 1, (
        f"TC-SMOKE-10: {len(grade_rows_)} submission_grade row(s) for a one-submission "
        "run. FR-GRADE-01: every submission of the run is graded — the batch pass with "
        "no teacher action anywhere in the path."
    )
    row = grade_rows_[0]
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