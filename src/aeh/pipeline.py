"""`M-PIPE` — run composition (issue #364, `FR-PIPE-01…06`, `FR-PIPE-10`).

Turns "a started run" into a completed one by calling each stage module's public door in
§4.2.2's order. It owns no table, no statement and no migration; every row it causes is
written by the module that owns it (`CT-PIPE-05`), and every model call goes through a stage
worker holding the governed provider (`CT-PIPE-06`), so `RecordedFixtureProvider` stays the
single egress point.

**What this module is.** A loop and seven hooks. `Orchestrator.progress` runs one dispatch
pass through the executor bound here; then the cells the orchestrator reports ready get their
integrity and aggregation hooks; then the loop asks whether the run is done. Nothing here
decides what a unit *means* — that is the stage door's — and nothing here leases, orders or
sets escalation policy, which is `M-ORCH`'s.

**Why a separate module.** `aeh.orch` is an ancestor of every stage module in the import
graph (the migration registry's contributor order), so the orchestrator cannot import the
workers at module scope. Composition has to live in a leaf, and this is it (ADR-15).

Three gaps in the design's inputs, resolved here and reported on #364
--------------------------------------------------------------------
Each is a place where the requirement names a call whose arguments the declared inputs cannot
supply. None is papered over: the resolution is stated, and the reason it is safe is stated
with it.

**1. `should_escalate` gets no history and no baseline.** `FR-PIPE-04` step 4 says to evaluate
it; its signature is `should_escalate(score, criterion, history, baseline, *, config)`. Nothing
in `src/aeh/` produces either value — the journeys passed doubles from
`tests/support/agg_vocabulary.py`. Both are passed as `None`, which `agg._row_field` reads as
the absent sentinel, and the module's own rule is that an absent field "is not making the
claim, and the limb is skipped". So the override-history and distributional-anomaly limbs make
no claim, and escalation runs on the limbs whose inputs this module *does* hold: interior band
position, the six integrity signals, and the uncited mark.

That has a consequence worth stating plainly: **the anomaly limb never fires in production**,
and it is precisely the limb that makes every judged cell of `F-DEV-PIPE` escalate under the
journey baseline (`mean=2.0, std=0.5`, calibrated for the reference package's four-band scale).
A production baseline reader is `M-STATS`' territory and is not in `FR-PIPE`'s table.

**2. The extractor ref has no home in `RunConfig`.** `RunConfig`'s twelve fields carry `panel`,
`transcriber` and `off_panel_checker`; `ModelRole` also declares `"extractor"` and
`"synthesizer"`, and neither has a field. `ExtractionWorker` refuses a `model_ref` whose role
is not `"extractor"` (`extract.py:857`), so one must be produced. `extractor=` and
`second_family=` are therefore optional keywords here, and when they are absent the extractor
is the **transcriber's backend identity re-roled**: same provider, build and quantization,
`role="extractor"`. That is a declared default, not a guess dressed as one — a deployment
running one local backend gets the backend it configured, and a deployment running two passes
the second explicitly.

**3. Extension arms are not in the panel.** `M-ORCH` mints `escalation-arm-<k>` identities for
a widened panel (`orch.py:1747`), and those ids are not `RunConfig.panel` members. An arm's
`ModelRef` is derived from the panel's **first** arm with the build id swapped, so a widened
panel runs on the backend the run froze. `judge_refs=` overrides that for a caller who knows
better — which is what a replay against a recorded corpus needs, because the recorded arms
carry whatever identity the capture used.

**Deterministic units are evaluated here, not by the dispatch pass.** `FR-PIPE-02` forbids a
unit reaching `done` without its payload row. The orchestrator's deterministic walk closes
those units directly (`orch.py:5608`, `self.complete(unit.work_id)`) and never calls
`DeterministicEvaluator` — no model call exists for the stage, so the ledger transition *is*
its dispatch. Left alone that would close a deterministic unit with no `criterion_score` row.
So this module runs `DeterministicEvaluator.evaluate_cohort(run_id)` **before** the first
dispatch pass, which is idempotent under redelivery and puts every row in place before any
unit closes over it.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any, Sequence

from aeh.agg import aggregate, should_escalate, write_score
from aeh.conf import ModelRef
from aeh.det import DeterministicEvaluator
from aeh.extract import ExtractionWorker
from aeh.grade import open_grade
from aeh.integ import IntegrityGate, StoreExtractionView
from aeh.judge import ScoringWorker, verdicts_for
from aeh.orch import (
    ESCALATION_ARM_PREFIX,
    STAGE_EXTRACT,
    STAGE_SCORE,
    Orchestrator,
    StageOutcome,
)
from aeh.pkg import PackageCatalog
from aeh.prov import BuildChangedError, ProviderUnavailableError
from aeh.synth import SynthesisWorker

#: Seam 3. Both are read at CALL time and validated before the first pass, because a malformed
#: knob discovered on pass three has already written rows.
MAX_PASSES_ENV = "HARNESS_PIPE_MAX_PASSES"
PASS_SLEEP_MS_ENV = "HARNESS_PIPE_PASS_SLEEP_MS"

#: The stages a `RunResult` can carry a trace for, in §4.2.2 order.
STAGE_NAMES: tuple[str, ...] = (
    "deterministic", "extract", "integrity_pre", "score", "aggregate", "synthesize", "grade",
)


class CompositionFault(RuntimeError):
    """A hook raised something that is not a provider condition.

    Never swallowed and never re-raised past `run_to_completion`: the run is paused with
    `pause_reason="composition fault: <type>: <msg>"` and the fault rides in the stage's
    `detail`, because a composition bug that pauses a run silently is the failure mode seam 4
    exists to prevent.
    """


@dataclass(frozen=True)
class StageTrace:
    """What one stage did on one call (seam 4).

    `detail` is never a bare status: a `status=success` sitting on an empty result is the top
    silent-failure trap, so every entry says what was processed.
    """

    stage: str
    units: int = 0
    done: int = 0
    quarantined: int = 0
    detail: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunResult:
    """The result of driving one run. `status` is the STORED `run.status` (`FR-PIPE-01`)."""

    run_id: str
    status: str
    pause_reason: str | None
    stages: tuple[StageTrace, ...]
    grades_computed: int
    grades_final: int


@dataclass(frozen=True)
class RecoveryReport:
    """What `recover` reclaimed, resumed and regraded (`FR-PIPE-07`).

    Declared here because the design puts it in this module's interface block. `recover()`
    itself is **#365**, which also brings `main` and `aeh/__main__.py`; this type lands with
    #364 so the module's surface is whole and #365 adds the function that fills it.
    """

    leases_reclaimed: int = 0
    runs_resumed: tuple[str, ...] = ()
    runs_regraded: tuple[str, ...] = ()


# --- the knobs ------------------------------------------------------------------------------


def _int_knob(name: str, default: int | None, *, minimum: int) -> int | None:
    """One `HARNESS_PIPE_*` integer, read at call time. Invalid raises before any write."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as error:
        raise ValueError(
            f"{name}={raw!r} is not an integer. The knob is read at call time and validated "
            f"before the first dispatch pass, so a malformed value never half-drives a run."
        ) from error
    if value < minimum:
        raise ValueError(f"{name}={value} is below the minimum of {minimum}.")
    return value


# --- the stage executor ---------------------------------------------------------------------


class ProductionStageExecutor:
    """`FR-ORCH-27`'s `StageExecutor`, bound to the real stage doors (`FR-PIPE-02`).

    One leased unit in, one `StageOutcome` out. The orchestrator owns the ledger transition —
    this never completes or quarantines a unit — and it owns the pool and the counters. What
    this owns is what a unit *means*: which door runs it, and with which model identity.

    `governed` is the run's provider with the run's counters wrapped around it. Every worker
    built here is handed `governed` rather than the raw provider, so a call a worker makes
    inside its own retry budget still accrues to the run's bill (`CT-PROV-11`).
    """

    def __init__(
        self,
        store: Any,
        provider: Any,
        run_config: Any,
        *,
        catalog: Any = None,
        high_risk_criteria: Sequence[str] = (),
        extractor: Any = None,
        second_family: Any = None,
        judge_refs: Any = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._run_config = run_config
        self._catalog = catalog
        self._high_risk = tuple(high_risk_criteria)
        self._extractor = extractor or _default_extractor(run_config)
        self._second_family = second_family
        self._judge_refs = dict(judge_refs or {})
        self._panel = {ref.build_id: ref for ref in getattr(run_config, "panel", ())}

    # -- model identities ----------------------------------------------------------------

    def judge_for(self, build_id: str) -> Any:
        """The `ModelRef` for one arm: a panel member, an override, or a derived extension arm.

        The derivation is the panel's first arm with the build id swapped — a widened panel
        runs on the backend the run froze (`FR-CONF-07`), not on one this module invented. A
        caller replaying a recorded corpus passes `judge_refs=` instead, because the recording
        carries whatever identity the capture used and a derived ref would miss its key.
        """
        if build_id in self._judge_refs:
            return self._judge_refs[build_id]
        if build_id in self._panel:
            return self._panel[build_id]
        if not self._panel:
            raise CompositionFault(
                f"score unit names judge {build_id!r} and the run config declares no panel, "
                f"so no model identity can be resolved for it"
            )
        if not str(build_id).startswith(ESCALATION_ARM_PREFIX):
            raise CompositionFault(
                f"score unit names judge {build_id!r}, which is neither a panel arm "
                f"({sorted(self._panel)}) nor an {ESCALATION_ARM_PREFIX}-<k> extension arm"
            )
        first = self._panel[next(iter(self._panel))]
        return replace(first, build_id=str(build_id))

    # -- the seam ------------------------------------------------------------------------

    def execute(self, unit: Any, governed: Any) -> StageOutcome:
        """Run ONE leased unit through its stage's shipped door.

        Deterministic units never arrive here — the orchestrator's walk closes them directly
        and `run_to_completion` has already written their score rows (see the module
        docstring). A unit of any other stage is a dispatch defect rather than something to
        improvise a door for, so it raises.
        """
        if unit.stage == STAGE_EXTRACT:
            worker = ExtractionWorker(
                self._store, governed, self._extractor,
                second_family_model=self._second_family,
                high_risk_criteria=self._high_risk,
            )
            result = worker.process(unit)
            return StageOutcome(
                completed=True,
                detail=f"extract {unit.submission_id}/{unit.criterion_id}: "
                       f"{len(getattr(result, 'spans', ()) or ())} spans",
            )
        if unit.stage == STAGE_SCORE:
            judge = self.judge_for(unit.judge)
            worker = ScoringWorker(self._store, governed, judge)
            result = worker.dispatch(worker.assemble(unit), judge)
            worker.persist(unit, result)
            return StageOutcome(
                completed=True,
                detail=f"score {unit.submission_id}/{unit.criterion_id} "
                       f"by {unit.judge}: {getattr(result, 'band', '?')}",
            )
        raise CompositionFault(
            f"unit {unit.work_id[:12]} carries stage {unit.stage!r}; the executor door "
            f"covers {STAGE_EXTRACT!r} and {STAGE_SCORE!r} only"
        )


def _default_extractor(run_config: Any) -> Any:
    """The transcriber's backend identity, re-roled (see the module docstring, gap 2)."""
    transcriber = getattr(run_config, "transcriber", None)
    if transcriber is None:
        raise ValueError(
            "the run config declares no transcriber, so no extractor identity can be derived; "
            "pass extractor= explicitly"
        )
    return ModelRef(
        role="extractor",
        provider=transcriber.provider,
        build_id=transcriber.build_id,
        quantization=transcriber.quantization,
    )


# --- the cell hooks -------------------------------------------------------------------------


def _criterion_value(catalog: Any, view: Any, version: str, criterion_id: str) -> Any:
    """The criterion `aggregate` maps a panel through, assembled from the package.

    `bands` and `scoring_model` come from the catalog; `evidence_required` from the gate's own
    view, which is where `criterion_requires_citation` is declared (`FR-PIPE-10`). Built here
    rather than imported from a test vocabulary: the journeys' `agg_vocabulary.criterion` is a
    double of THIS shape, and a production caller reaching for the double would make the double
    the definition.
    """
    bands = tuple(catalog.bands(criterion_id))
    scoring_model = "atomic"
    for row in catalog.criteria(version):
        if str(row["criterion_id"]) == criterion_id:
            scoring_model = str(row["scoring_model"] or "atomic")
            break
    return SimpleNamespace(
        criterion_id=criterion_id,
        scoring_model=scoring_model,
        bands=bands,
        band_count=len(bands),
        evidence_required=bool(view.criterion_requires_citation(criterion_id)),
    )


def _integrity_pre_hook(orch: Any, handle: Any, gate: Any) -> StageTrace:
    """`FR-PIPE-03`: verify once per cell whose extraction is terminal, and record the phase.

    `units_consumed` is 0 by design here: `ready_cells("integrity_pre")` gates on the phase's
    PRESENCE and never on its count, so a number would be a figure nothing reads. The aggregate
    hook's count IS load-bearing and is recorded honestly there.
    """
    cells = orch.ready_cells(handle.run_id, "integrity_pre")
    detail: list[str] = []
    for cell in cells:
        gate.verify(handle.run_id, cell.submission_id, cell.criterion_id)
        with handle.cohort.transaction() as tx:
            orch.mark_cell_phase(
                tx, handle.run_id, cell.submission_id, cell.criterion_id,
                "integrity_pre", units_consumed=0,
            )
        detail.append(f"{cell.submission_id}/{cell.criterion_id}")
    return StageTrace("integrity_pre", units=len(cells), done=len(cells), detail=tuple(detail))


def _aggregate_hook(orch: Any, handle: Any, gate: Any, catalog: Any, view: Any) -> StageTrace:
    """`FR-PIPE-04`: verify, read verdicts, aggregate, then ONE transaction for the rest.

    The order is the requirement's, and the single transaction is the half that matters: the
    score, the escalation it triggers and the phase recording both commit together or not at
    all. A crash between them is what `NFR-PIPE-01` is about, because a phase recorded beside
    work that rolled back makes a restart skip the work.

    `fallback=True` at exactly two verdicts is `FR-PIPE-05`: a terminal failure left an even
    panel, and an even panel is never aggregated as one.
    """
    cells = orch.ready_cells(handle.run_id, "aggregate")
    counts = orch.cell_unit_counts(handle.run_id, STAGE_SCORE)
    detail: list[str] = []
    escalated = 0
    for cell in cells:
        signals = gate.verify(handle.run_id, cell.submission_id, cell.criterion_id)
        verdicts = verdicts_for(
            handle.cohort, handle.run_id, cell.submission_id, cell.criterion_id)
        criterion = _criterion_value(
            catalog, view, handle.package_version_id, cell.criterion_id)
        score = aggregate(verdicts, criterion, signals, fallback=len(verdicts) == 2)
        terminal = counts.get(cell, (len(verdicts), len(verdicts)))[0]
        with handle.cohort.transaction() as tx:
            write_score(tx, handle.run_id, cell.submission_id, score, signals)
            decision = should_escalate(
                score=score, criterion=criterion, history=None, baseline=None)
            escalates = bool(getattr(decision, "escalate", False))
            if escalates:
                orch.enqueue_escalation(
                    tx, (handle.run_id, cell.submission_id, cell.criterion_id))
                escalated += 1
            orch.mark_cell_phase(
                tx, handle.run_id, cell.submission_id, cell.criterion_id,
                "aggregated", units_consumed=terminal,
            )
        detail.append(
            f"{cell.submission_id}/{cell.criterion_id}: {score.band} over "
            f"{len(verdicts)} verdicts" + (" -> escalated" if escalates else "")
        )
    if escalated:
        detail.append(f"{escalated} cell(s) escalated")
    return StageTrace("aggregate", units=len(cells), done=len(cells), detail=tuple(detail))


# --- completion hooks -----------------------------------------------------------------------


def _submissions_of(orch: Any, run_id: str) -> tuple[str, ...]:
    """Every submission the run enumerated, in ledger order, without reading the ledger.

    The union of both judged stages' cells: a submission with open criteria has extract units,
    one with only deterministic criteria has neither, and the union covers a package that
    carries both. `M-ORCH` counts them; `CT-PIPE-05` forbids this module counting for itself.
    """
    seen: dict[str, None] = {}
    for stage in (STAGE_EXTRACT, STAGE_SCORE):
        for cell in orch.cell_unit_counts(run_id, stage):
            seen.setdefault(cell.submission_id, None)
    return tuple(seen)


def _synthesize(store: Any, provider: Any, run_config: Any, orch: Any, handle: Any,
                synthesizer: Any = None) -> StageTrace:
    """`FR-PIPE-06`: narrate every submission whose criteria are all scored.

    Completeness is `M-SYNTH`'s to judge, not this module's: `CT-SYNTH-05` says a submission
    with incomplete criteria is not synthesized, so every submission is offered and the worker
    declines the ones that are not ready. Reimplementing that test here would be a second
    definition of "complete", and the two would drift.

    **A synthesis failure never prevents grading** (`FR-PIPE-06`, TC-REQ-85). Each submission
    is attempted independently and a failure is recorded in `detail` rather than raised, so one
    missing recording costs one narrative and not the run's grades.
    """
    ref = synthesizer or _default_synthesizer(run_config)
    worker = SynthesisWorker(store, provider, ref)
    detail: list[str] = []
    done = failed = 0
    for submission_id in _submissions_of(orch, handle.run_id):
        try:
            report = worker.synthesize_submission(handle.run_id, submission_id)
        except Exception as error:  # noqa: BLE001 - recorded, never fatal to grading
            failed += 1
            detail.append(f"{submission_id}: {type(error).__name__}: {error}")
            continue
        done += 1
        detail.append(
            f"{submission_id}: {getattr(report, 'narratives', 0)} narratives, "
            f"{getattr(report, 'failures', 0)} failures"
        )
    return StageTrace("synthesize", units=done + failed, done=done, quarantined=failed,
                      detail=tuple(detail))


def _grade(store: Any, handle: Any) -> tuple[StageTrace, int, int]:
    """`FR-PIPE-06`'s second half: `GradingService.compute_all`, and the two grade counts."""
    report = open_grade(store).compute_all(handle.run_id)
    by_state = dict(getattr(report, "grades_by_state", {}) or {})
    computed = int(getattr(report, "computed", 0) or 0)
    final = int(by_state.get("final", 0))
    detail = (
        f"policy {getattr(report, 'policy_version', '?')}: "
        f"{computed} of {getattr(report, 'submitted', 0)} computed",
        ", ".join(f"{state}={n}" for state, n in sorted(by_state.items())) or "no states",
    )
    return StageTrace("grade", units=computed, done=computed, detail=detail), computed, final


def _default_synthesizer(run_config: Any) -> Any:
    """The transcriber's backend identity re-roled, for the same reason the extractor is."""
    transcriber = getattr(run_config, "transcriber", None)
    if transcriber is None:
        raise ValueError(
            "the run config declares no transcriber, so no synthesizer identity can be "
            "derived; pass synthesizer= explicitly"
        )
    return ModelRef(
        role="synthesizer",
        provider=transcriber.provider,
        build_id=transcriber.build_id,
        quantization=transcriber.quantization,
    )


def _stall_reason(orch: Any, run_id: str) -> str:
    """Why a pass stopped moving, in M-ORCH's own words.

    The escalation budget is the expected cause and it already explains itself: the budget
    state carries a `gates` mapping whose `rate` entry says whether dispatch is deferring
    widened pairs and why. Reported verbatim rather than re-worded, so the operator reads the
    same sentence the orchestrator would print.
    """
    try:
        state = orch.escalation_budget_state(run_id)
    except Exception as error:  # noqa: BLE001 - a stall report must not raise
        return f"escalation budget state unavailable: {type(error).__name__}: {error}"
    if getattr(state, "over_budget", False):
        gates = dict(getattr(state, "gates", {}) or {})
        return gates.get(
            "rate",
            f"escalation rate {getattr(state, 'escalation_rate', '?')} over budget "
            f"{getattr(state, 'budget', '?')}",
        )
    return (
        "the escalation budget is within range, so the pending units are blocked by "
        "something else - inspect the ledger"
    )


# --- the driver -----------------------------------------------------------------------------


def run_to_completion(
    store: Any,
    run_id: str,
    *,
    provider: Any,
    run_config: Any,
    clock: Any = None,
    max_passes: int | None = None,
    extractor: Any = None,
    second_family: Any = None,
    judge_refs: Any = None,
    synthesizer: Any = None,
    high_risk_criteria: Sequence[str] = (),
) -> RunResult:
    """Drive `run_id` until `M-ORCH`'s completion predicate holds or the run pauses.

    `FR-PIPE-01`. The returned `status` is the STORED `run.status`, read back through `M-ORCH`
    after the last pass, never this module's own idea of where the run got to.

    The four keyword refs are the design gaps the module docstring names: `RunConfig` has no
    field for an extractor or a synthesizer, and extension arms are not panel members. A caller
    needing exact identities (a replay against a recorded corpus) supplies them; everything
    else takes the declared default.

    `clock` is accepted for the signature the design states and for #365's `recover`. Nothing
    here reads a wall clock: every deadline belongs to `M-ORCH`'s lease clock.
    """
    passes_cap = (
        max_passes if max_passes is not None
        else _int_knob(MAX_PASSES_ENV, None, minimum=1)
    )
    pass_sleep_ms = _int_knob(PASS_SLEEP_MS_ENV, 0, minimum=0) or 0

    executor = ProductionStageExecutor(
        store, provider, run_config,
        high_risk_criteria=high_risk_criteria,
        extractor=extractor, second_family=second_family, judge_refs=judge_refs,
    )
    # The provider is bound alongside the executor: `M-ORCH` wraps it in the `GovernedProvider`
    # the stage workers actually call, so the run's counters see every call a worker makes
    # inside its own retry budget (`FR-ORCH-27`, `CT-PROV-11`).
    orch = Orchestrator(store, executor=executor, provider=provider)
    handle = orch.run_handle(run_id)
    catalog = PackageCatalog(store.package(handle.package_id), package_id=handle.package_id)
    view = StoreExtractionView(handle.cohort, catalog, handle.package_version_id, run_id)
    gate = IntegrityGate(handle.cohort, store.blobs(), view)

    stages: list[StageTrace] = []

    # `FR-PIPE-02`: the deterministic score rows must exist before the dispatch walk closes
    # their units, and that walk closes them directly without calling the evaluator.
    det = DeterministicEvaluator(store).evaluate_cohort(run_id)
    evaluations = int(getattr(det, "evaluations", 0) or 0)
    stages.append(StageTrace(
        "deterministic", units=evaluations, done=evaluations,
        detail=(
            f"evaluate_cohort: {evaluations} evaluations over "
            f"{getattr(det, 'submissions', 0)} submissions",
        ),
    ))

    passes = 0
    fault: str | None = None
    last_seen: tuple[int, int, int] | None = None
    while True:
        passes += 1
        try:
            report = orch.progress(run_id)
            pre = _integrity_pre_hook(orch, handle, gate)
            agg = _aggregate_hook(orch, handle, gate, catalog, view)
        except (ProviderUnavailableError, BuildChangedError):
            # `FR-ORCH-30` already paused the run with its cause. The status read below is the
            # authority and this module adds nothing to it.
            break
        except Exception as error:  # noqa: BLE001 - recorded and paused, never swallowed
            fault = f"composition fault: {type(error).__name__}: {error}"
            stages.append(StageTrace("aggregate", detail=(fault,)))
            break

        if pre.units:
            stages.append(pre)
        if agg.units:
            stages.append(agg)

        handle = orch.run_handle(run_id)
        if handle.status in ("paused", "failed"):
            break

        seen = (int(report["done"]), int(report["pending"]), int(report["in_flight"]))
        moved = bool(pre.units or agg.units) or seen != last_seen
        last_seen = seen

        if report["complete"] and not (pre.units or agg.units):
            # Nothing pending, nothing in flight, no hook fired: let M-ORCH apply its own
            # completion predicate. `resume` is the sanctioned closer, and this module never
            # writes a run status itself.
            orch.resume(run_id)
            handle = orch.run_handle(run_id)
            if handle.status in ("complete", "failed", "paused"):
                break
        if passes_cap is not None and passes >= passes_cap:
            break
        if not moved:
            if report["in_flight"] and pass_sleep_ms:
                time.sleep(pass_sleep_ms / 1000.0)
                continue
            # No progress, and nothing another worker is holding. Spinning changes nothing —
            # but returning a bare `running` would be the silent-failure shape seam 4 exists
            # to refuse, so the reason is named.
            #
            # The ordinary cause is the escalation budget (`FR-ORCH-11`): a run whose
            # escalation rate is over budget has dispatch DEFER its widened pairs and mark
            # them provisional, and those units stay pending until growth returns headroom.
            # On a small cohort that headroom never arrives, so the run genuinely cannot reach
            # a pending count of zero. That is M-ORCH policy working, not a composition fault,
            # and it is reported rather than paused over.
            stages.append(StageTrace(
                "aggregate",
                units=int(report["pending"]),
                detail=(
                    f"no progress with {report['pending']} unit(s) pending and none in "
                    f"flight after {passes} pass(es); the run cannot reach the completion "
                    f"predicate",
                    _stall_reason(orch, run_id),
                ),
            ))
            break

    if fault is not None:
        try:
            orch.pause(run_id, fault)
        except Exception:  # noqa: BLE001 - a terminal run refuses a pause; the status stands
            pass
        handle = orch.run_handle(run_id)

    grades_computed = grades_final = 0
    if handle.status == "complete":
        stages.append(
            _synthesize(store, provider, run_config, orch, handle, synthesizer))
        grade_trace, grades_computed, grades_final = _grade(store, handle)
        stages.append(grade_trace)

    return RunResult(
        run_id=run_id,
        status=handle.status,
        pause_reason=fault or handle.pause_reason,
        stages=tuple(stages),
        grades_computed=grades_computed,
        grades_final=grades_final,
    )
