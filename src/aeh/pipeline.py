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

Gaps in the design's declared inputs, resolved here and reported on #364 / #365
-------------------------------------------------------------------------------
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

**4. No provider factory exists.** `FR-PIPE-08` has the command resolve its configuration and
drive the run, but nothing says which provider object a backend profile maps to, and `M-PROV`
ships three classes and leaves construction to the caller. `_provider_for` makes the mapping
in the open and refuses an unconfigured profile by name rather than guessing.

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

# The eleven migration contributors FIRST (CLAUDE.md): every one must be registered before the
# first store open in any process, and `aeh/__main__.py` makes this module that process's
# entry point. Ten arrive through the imports below — `aeh.review` arrives through none of
# them, and its absence was not theoretical: `python -m aeh recover` opened Tier D against a
# chain missing versions 6 and 10 and the open refused, which is the guard doing its job.
import aeh.agg  # noqa: F401
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401

import argparse
import dataclasses
import json
import os
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from aeh.agg import aggregate, should_escalate, write_score
from aeh.conf import ModelRef, effective_config
from aeh.det import DeterministicEvaluator
from aeh.extract import ExtractionWorker
from aeh.grade import open_grade
from aeh.integ import IntegrityGate, StoreExtractionView
from aeh.judge import JudgmentError, ScoringWorker, verdicts_for
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

#: How many consecutive passes may make no headway before the loop gives up.
#:
#: One is too few. A pass in which every unit came back `RateLimitedError` requeues them all
#: (`FR-ORCH-30`), so `done`, `pending` and `in_flight` are unchanged and the next pass looks
#: identical — and `RES-11`'s back-off IS the next pass. Breaking on the first repeat would
#: abandon a rate-limited run as `running` with work outstanding, which `FR-PIPE-01` forbids.
#: Three bounds the retry without turning a genuinely stuck run into a spin.
STALL_PASSES = 3

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

    `recover()` fills it (`FR-PIPE-07`): what one sweep reclaimed, which paused runs it
    resumed, and which complete runs it re-graded after a review window lapsed.
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
        #: What each executed unit did, per stage, drained into the trace once a pass ends.
        #: `FR-PIPE-01` wants one entry per stage EXECUTED, and extract and score are executed
        #: here rather than in a hook, so without this they would be the two stages a run
        #: never reports having run (`#364`'s first acceptance criterion names both).
        self.executed: dict[str, list[str]] = {STAGE_EXTRACT: [], STAGE_SCORE: []}
        #: Bound by `run_to_completion`. The executor asks the ledger whether a worker has
        #: already terminalised a unit; it never writes one.
        self.orchestrator: Any = None

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
            # `M-EXTRACT` quarantines at its strike ceiling and RETURNS the outcome rather
            # than raising (`extract.py`'s "returned rather than raised"). Reporting that unit
            # completed makes the orchestrator call `complete()`, which refuses an already
            # quarantined unit — and the refusal would pause the whole run over one
            # unparseable reply. `completed=False` is the honest answer: the requeue is
            # guarded by `status = 'leased'`, so it is a no-op on a quarantined row and the
            # unit stays quarantined, which is what `CT-PIPE-02` expects to find.
            spans = len(getattr(result, "spans", ()) or ())
            # The ledger read happens only on the strike-out SHAPE — an empty span set. A
            # successful extraction cannot have been quarantined, and `NFR-PIPE-02` budgets
            # composition overhead at under 5% of scheduling at 23,000 units, which a status
            # query per unit would spend on the answer "no" almost every time.
            if spans == 0 and self._quarantined(unit):
                detail = f"{unit.submission_id}/{unit.criterion_id}: quarantined by the worker"
                self.executed[STAGE_EXTRACT].append(detail)
                return StageOutcome(completed=False, detail=detail)
            detail = f"{unit.submission_id}/{unit.criterion_id}: {spans} spans"
            self.executed[STAGE_EXTRACT].append(detail)
            return StageOutcome(completed=True, detail=detail)
        if unit.stage == STAGE_SCORE:
            judge = self.judge_for(unit.judge)
            worker = ScoringWorker(self._store, governed, judge)
            try:
                result = worker.dispatch(worker.assemble(unit), judge)
            except JudgmentError as error:
                # A judge that cannot produce a legal verdict is an expected condition, not a
                # composition fault: `NFR-JUDGE-05` says a broken judge fails visibly rather
                # than grading confidently. `M-JUDGE`'s worker does not report the strike
                # itself, so the strike is recorded here — the same `fail()` M-EXTRACT's
                # worker calls internally — and the unit requeues until the ledger quarantines
                # it at the ceiling. Letting it propagate instead would pause the run and
                # leave the unit leased, swept and retried forever with no attempt counted.
                detail = f"{unit.submission_id}/{unit.criterion_id} by {unit.judge}: {error}"
                self.executed[STAGE_SCORE].append(detail)
                if self.orchestrator is not None:
                    self.orchestrator.fail(unit.work_id, str(error))
                return StageOutcome(completed=False, detail=detail)
            worker.persist(unit, result)
            detail = (f"{unit.submission_id}/{unit.criterion_id} by {unit.judge}: "
                      f"{getattr(result, 'band', '?')}")
            self.executed[STAGE_SCORE].append(detail)
            return StageOutcome(completed=True, detail=detail)
        raise CompositionFault(
            f"unit {unit.work_id[:12]} carries stage {unit.stage!r}; the executor door "
            f"covers {STAGE_EXTRACT!r} and {STAGE_SCORE!r} only"
        )


    def _quarantined(self, unit: Any) -> bool:
        """Whether the WORKER struck this unit out. `quarantined` only, never `done`.

        `ExtractionWorker.process` marks a successful unit `done` in its own transaction
        before returning, so treating `done` as a strike-out misreads every successful
        extraction that legitimately found nothing — `{"spans": []}` is a valid answer meaning
        "no supporting evidence in this document". That misread is expensive and silent: the
        unit joins the requeue list, which halves the run's concurrency cap as though a
        transport condition had occurred, ends the extract walk early for that pass, and puts
        "quarantined by the worker" in the trace about a unit that is `done` with its evidence
        written. `complete()` early-returns on a `done` unit anyway, so `done` bought nothing.
        """
        if self.orchestrator is None:
            return False
        return self.orchestrator.unit_status(unit.work_id) == "quarantined"


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

    **The package row is copied through wholesale rather than field by field, and that is
    `CT-AGG-09`.** The contract's rule is that outside its sanctioned readers no shipped module
    references the criterion's evaluation-mode column at all — because a consumer that can read
    it can branch on it, and a run-time branch is a second source of truth that drifts from the
    package. `M-PIPE` has no business knowing which modes exist. So every column the catalog
    declares is forwarded verbatim to `aggregate`, which is the policy that owns the
    distinction (`CT-SETUP-05`: the distinction comes from the package), and this module names
    none of them.

    `bands` comes from the catalog and `evidence_required` from the gate's own view, which is
    where `criterion_requires_citation` is declared (`FR-PIPE-10`). Built here rather than
    imported from a test vocabulary: the journeys' `agg_vocabulary.criterion` is a double of
    THIS shape, and a production caller reaching for the double would make the double the
    definition.
    """
    row = None
    for candidate in catalog.criteria(version):
        if str(candidate["criterion_id"]) == criterion_id:
            row = candidate
            break
    if row is None:
        raise CompositionFault(
            f"the package version declares no criterion {criterion_id!r}, but the run "
            f"enumerated a cell for it"
        )
    keys = row.keys() if hasattr(row, "keys") else ()
    fields: dict[str, Any] = {str(key): row[key] for key in keys}
    bands = tuple(catalog.bands(criterion_id))
    fields.update(
        criterion_id=criterion_id,
        bands=bands,
        band_count=len(bands),
        evidence_required=bool(view.criterion_requires_citation(criterion_id)),
    )
    return SimpleNamespace(**fields)


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
    # `FR-PIPE-04` step 3 spells `aggregate(..., breaker_tripped=..., fallback=...)`, and the
    # flag is not cosmetic: a criterion whose breaker latched must score `provisional` /
    # `ungradeable_by_panel` rather than `auto` / `final` (`FR-ORCH-13`, `CT-ORCH-16`). The
    # panel's own figure still stands; what the breaker changes is whether it may be trusted
    # unreviewed.
    #
    # Read per CELL rather than once before the loop: `enqueue_escalation` latches the breaker
    # inside the transaction this hook opens, so a later cell of the same criterion in the
    # same pass would otherwise aggregate with a stale `False`, be phase-marked, and never
    # re-aggregate — its score staying `auto`/`final` where `CT-ORCH-16` requires
    # `provisional`/`ungradeable_by_panel`.
    detail: list[str] = []
    escalated = 0
    for cell in cells:
        signals = gate.verify(handle.run_id, cell.submission_id, cell.criterion_id)
        verdicts = verdicts_for(
            handle.cohort, handle.run_id, cell.submission_id, cell.criterion_id)
        terminal_units = counts.get(cell, (len(verdicts), len(verdicts)))[0]
        if not verdicts:
            # Every score unit of this cell is terminal and none produced a verdict — they
            # were all quarantined. `aggregate` refuses an empty panel outright
            # (`EmptyVerdictsError`, `CT-AGG-12`: an empty verdict set is never a zero), and it
            # is right to: there is nothing to average. `CT-PIPE-02` already allows for this
            # cell — "exactly one `criterion_score` row **or** a quarantined extract/score
            # unit" — so the honest outcome is no score at all.
            #
            # The phase is still recorded, and that is the part that matters: without it
            # `ready_cells` reports this cell ready on every later pass and the run would spin
            # until `max_passes`, re-deciding nothing.
            with handle.cohort.transaction() as tx:
                orch.mark_cell_phase(
                    tx, handle.run_id, cell.submission_id, cell.criterion_id,
                    "aggregated", units_consumed=terminal_units,
                )
            detail.append(
                f"{cell.submission_id}/{cell.criterion_id}: no verdicts from "
                f"{terminal_units} terminal unit(s) - all quarantined, no score written"
            )
            continue
        criterion = _criterion_value(
            catalog, view, handle.package_version_id, cell.criterion_id)
        latched = {trip.criterion_id for trip in orch.tripped_breakers(handle.run_id)}
        score = aggregate(
            verdicts, criterion, signals,
            # `FR-PIPE-05` names the two-verdict case, but `aggregate` refuses EVERY even
            # panel, and F3's attempt-counting makes a 4-verdict panel reachable: a widened
            # five-arm panel with one arm quarantined. The rule is "never aggregate an even
            # panel as one", so it is applied to the parity rather than to the number two.
            fallback=len(verdicts) % 2 == 0,
            breaker_tripped=cell.criterion_id in latched,
        )
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
                "aggregated", units_consumed=terminal_units,
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

    The union of both judged stages' cells. **This does not cover every package**: a
    submission whose criteria are ALL deterministic has neither extract nor score units, so it
    is never offered to synthesis at all. An earlier draft of this docstring stated the hole
    and then claimed the union closed it, which it does not. The reference and F-DEV-PIPE
    packages both carry open criteria so the gap is not reachable there; closing it needs a
    per-run submission list `M-ORCH` does not currently expose. Reported rather than hidden.

    `M-ORCH` counts the cells; `CT-PIPE-05` forbids this module counting for itself.
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


def _over_escalation_budget(orch: Any, run_id: str) -> bool:
    """Whether the run's escalation rate is over budget, so dispatch is deferring its pairs.

    That is the one no-progress condition retrying cannot clear: the deferred units stay
    pending until growth returns headroom, and on a cohort too small to grow it never does.
    Every other stall — a rate-limited pass, a peer holding a lease — is worth another pass.
    """
    try:
        return bool(getattr(orch.escalation_budget_state(run_id), "over_budget", False))
    except Exception:  # noqa: BLE001 - a stall decision must not raise
        return False


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
    executor.orchestrator = orch
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
    stalled = 0
    fault: str | None = None
    last_seen: tuple[int, int, int] | None = None
    while True:
        passes += 1
        try:
            report = orch.progress(run_id)
            pre = _integrity_pre_hook(orch, handle, gate)
            agg = _aggregate_hook(orch, handle, gate, catalog, view)
        except (ProviderUnavailableError, BuildChangedError):
            # Defensive only. `FR-ORCH-30` absorbs both per future inside `_run_model_batch`
            # and pauses the run there, so neither normally reaches this frame; if one ever
            # does, the stored status read below is the authority and this adds nothing to it.
            handle = orch.run_handle(run_id)
            break
        except Exception as error:  # noqa: BLE001 - recorded and paused, never swallowed
            fault = f"{_FAULT_PREFIX}{type(error).__name__}: {error}"
            stages.append(StageTrace("aggregate", detail=(fault,)))
            break

        for stage_name in (STAGE_EXTRACT, STAGE_SCORE):
            done = executor.executed[stage_name]
            if done:
                stages.append(StageTrace(
                    stage_name, units=len(done), done=len(done), detail=tuple(done)))
                executor.executed[stage_name] = []
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
        stalled = 0 if moved else stalled + 1

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
            over_budget = _over_escalation_budget(orch, run_id)
            if not over_budget and stalled < STALL_PASSES:
                # No headway, but nothing says the run is stuck. The ordinary cause is a pass
                # whose units all came back rate-limited and were requeued: counts unchanged,
                # nothing in flight, and the back-off is simply the next pass. Retry a bounded
                # number of times before concluding otherwise.
                if pass_sleep_ms:
                    time.sleep(pass_sleep_ms / 1000.0)
                continue
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
                    f"no progress after {passes} pass(es): {report['pending']} unit(s) "
                    f"pending, none in flight, and no cell became ready",
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
        # Inside the same discipline as the loop's hooks: the design's error-handling
        # paragraph says any exception out of a hook is recorded in that stage's `detail` and
        # pauses the run, never swallowed and never raised past this function. Synthesis and
        # grading are hooks too, and an exception here used to propagate out of
        # `run_to_completion` instead.
        try:
            stages.append(
                _synthesize(store, provider, run_config, orch, handle, synthesizer))
            grade_trace, grades_computed, grades_final = _grade(store, handle)
            stages.append(grade_trace)
        except Exception as error:  # noqa: BLE001 - recorded and paused, never swallowed
            fault = f"{_FAULT_PREFIX}{type(error).__name__}: {error}"
            stages.append(StageTrace("grade", detail=(fault,)))
            try:
                orch.pause(run_id, fault)
            except Exception:  # noqa: BLE001 - a terminal run refuses a pause
                pass
            handle = orch.run_handle(run_id)

    return RunResult(
        run_id=run_id,
        status=handle.status,
        pause_reason=fault or handle.pause_reason,
        stages=tuple(stages),
        grades_computed=grades_computed,
        grades_final=grades_final,
    )


# --- recovery (issue #365, FR-PIPE-07) ------------------------------------------------------


def recover(store: Any, *, clock: Any = None) -> RecoveryReport:
    """Reclaim expired leases, resume open runs, and settle grades a window lapse left behind.

    `FR-PIPE-07`, in its stated order: `sweep_expired_leases()` then `resume()`, then
    `compute_all` for every run that is `complete` but whose grades are not all final.

    **Why the third step exists.** A run can complete while its grades are still
    `provisional` because a review window has not lapsed yet (`FR-GRADE-10`). Nothing wakes up
    to settle them when it does — the lapse is a fact about the clock, not an event — so the
    next process start is where it gets noticed. Without this, a run graded under a window
    would sit provisional until somebody re-ran it by hand, which is the defect PR #339 found.

    Idempotent by construction: on a clean store the sweep reclaims nothing, `resume` is the
    documented no-op, and no complete run reports unsettled grades, so the report comes back
    empty and no row is written.
    """
    orchestrator = Orchestrator(store)
    sweep = orchestrator.sweep_expired_leases()

    # The profile this PROCESS is running, resolved the way every entry point resolves it
    # (`FR-CONF-14`): the environment wins. A run froze its own profile at creation
    # (`FR-CONF-07`), and the two can disagree after an operator switches `HARNESS_PROFILE`.
    current_profile = str(effective_config({}).get("HARNESS_PROFILE") or "")

    # **Resume the RUNNING runs, one at a time — not the no-argument form.** `FR-PIPE-07`
    # says `resume()`, and taken literally that is wrong: the no-argument form discovers every
    # open run, `pending` ones included, and resuming re-enumerates — so a run an operator
    # created but never started gets its work units written by a recovery pass nobody asked to
    # start anything. TC-PIPE-07 arm (d) asserts exactly that absence, by row counts rather
    # than by the report's own account of itself. Divergence reported on #365.
    #
    # A `running` run with work left is what a crashed process leaves behind (arm (b)) and is
    # the case recovery exists for; re-enumerating it is a no-op on units that already exist.
    #
    # A `paused` run comes back ONLY if it carries an unapplied resume request — the row a
    # process wrote before it died. `TC-CONF-22`'s variant asserts that it does; but an
    # explicit `resume(run_id)` supersedes the pauses before it, so resuming every paused run
    # would restart work an operator or the cost ceiling deliberately stopped. `M-ORCH`'s own
    # rule is that a stop an operator requested outranks a scheduler's restart, and recovery
    # is a scheduler. Hence the request check rather than the status alone.
    #
    # A `pending` run is never touched: it was created and never started, and re-enumerating
    # it writes work units for a run nobody started (TC-PIPE-07 arm (d), by row counts).
    resumed: list[str] = []
    for handle in orchestrator.runs(("running", "paused")):
        if current_profile and handle.backend_profile and (
            handle.backend_profile != current_profile
        ):
            # `FR-CONF-15`: a resumed run keeps its persisted profile, so a process running
            # under a different one must not pick it up — not even to honour a resume request
            # queued before the switch. It stays paused and the refusal is RECORDED, naming
            # both profiles: an operator who switched and then found a run stopped needs the
            # reason in the row, not in a log nobody kept.
            refusal = (
                f"profile switch: the run froze {handle.backend_profile!r} and this process "
                f"is running {current_profile!r}; recovery will not rebind a run to a backend "
                f"its operator never approved (FR-CONF-15)"
            )
            if handle.status == "paused":
                # Already stopped — annotate, never re-stop. `pause()` on a paused run
                # changes nothing by design, so the refusal would go unrecorded.
                orchestrator.record_pause_reason(handle.run_id, refusal)
            else:
                orchestrator.pause(handle.run_id, refusal)
            continue
        if handle.status == "paused" and not orchestrator.has_queued_resume(handle.run_id):
            continue
        orchestrator.resume(handle.run_id)
        resumed.append(handle.run_id)

    grading = open_grade(store, clock=clock) if clock is not None else open_grade(store)
    regraded: list[str] = []
    for handle in orchestrator.runs(("complete",)):
        if _grades_all_final(grading, handle.run_id):
            continue
        grading.compute_all(handle.run_id)
        regraded.append(handle.run_id)

    return RecoveryReport(
        leases_reclaimed=int(getattr(sweep, "requeued", 0) or 0),
        runs_resumed=tuple(resumed),
        runs_regraded=tuple(regraded),
    )


def _grades_all_final(grading: Any, run_id: str) -> bool:
    """Whether every grade of one run is settled.

    Read through `coverage`, which counts the STORED `state` column (plus a derived
    `incomplete` for a submission with no current row). It does **not** re-evaluate review
    windows — an earlier draft of this docstring claimed it did, and that claim was not only
    false but backwards: if `coverage` settled a lapsed window on read, a lapsed run would
    report as final and `FR-PIPE-07`'s whole third step would never fire. It is precisely
    because the stored state is stale that recovery has to re-grade.

    A run with **no grades at all** reads as settled here, and that is a narrow judgement
    rather than an obvious one: its criterion scores may well exist and grading simply never
    ran, which is the killed-after-completion state `NFR-PIPE-01` is about. It is safe only
    because `run_to_completion`'s own `complete` branch grades such a run; `aeh recover`
    alone would leave it ungraded. Recorded as a known edge rather than defended as correct.
    """
    by_state = dict(getattr(grading.coverage(run_id), "grades_by_state", {}) or {})
    total = sum(int(n) for n in by_state.values())
    if total == 0:
        return True
    return int(by_state.get("final", 0)) == total


# --- the command line (issue #365, FR-PIPE-08, FR-PIPE-09) ----------------------------------

#: `FR-PIPE-08`'s exit codes. Changing this mapping is a breaking change to `CT-PIPE-01`.
#: The marker a composition fault carries in `RunResult.pause_reason`.
_FAULT_PREFIX = "composition fault: "

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_PAUSED = 3


def _open_store(data_dir: str) -> Any:
    """The store. The migration chain is already complete — this module imports all eleven
    contributors at module scope, which is what makes this entry point safe to open from."""
    from aeh.store import open_store

    return open_store(Path(data_dir))


def _provider_for(config: Mapping[str, Any]) -> Any:
    """The provider the run's backend profile names.

    **A declared resolution of a gap, not a shipped factory.** `FR-PIPE-08` says the command
    resolves its configuration and then drives the run, but nothing in the design says which
    provider object a profile maps to, and no factory exists anywhere in `src/aeh/` —
    `M-PROV` ships the three classes and leaves construction to the caller. So the mapping is
    made here, minimally and in the open:

    Reads the RESOLVED `RunConfig.backend_profile` rather than a raw configuration key: the
    profile that matters is the one `resolve_run_config` settled on after the environment won
    (`FR-CONF-14`), and a raw lookup finds nothing when the profile arrives through a
    profile section.

    * `dev-ci` -> `RecordedFixtureProvider` over `HARNESS_FIXTURE_DIR`. The profile's whole
      point is running with no network (`CT-PROV-10`), and this is the shipped transport for
      that.
    * `edge-local` -> `LocalServerProvider`.
    * `cloud-hosted` -> `OpenRouterProvider`.

    Both live providers are constructed with their own defaults; a deployment that needs
    different endpoints sets them through `M-PROV`'s own seams rather than through this
    function, which knows nothing about backends beyond the profile name.
    """
    from aeh.prov import LocalServerProvider, OpenRouterProvider, RecordedFixtureProvider

    profile = str(
        getattr(config, "backend_profile", None)
        or (config.get("backend_profile") if hasattr(config, "get") else None)
        or ""
    )
    if profile == "dev-ci":
        fixture_dir = os.environ.get("HARNESS_FIXTURE_DIR")
        if not fixture_dir:
            raise ValueError(
                "the dev-ci profile records and replays through a fixture directory; set "
                "HARNESS_FIXTURE_DIR so the provider has somewhere to read"
            )
        return RecordedFixtureProvider(fixture_dir=Path(str(fixture_dir)))
    if profile == "edge-local":
        return LocalServerProvider()
    if profile == "cloud-hosted":
        return OpenRouterProvider()
    raise ValueError(
        f"no backend profile is configured ({profile!r}); set HARNESS_BACKEND_PROFILE or "
        f"declare backend_profile in the config file. The declared profiles are "
        f"'edge-local', 'cloud-hosted' and 'dev-ci'."
    )


def _load_config_file(path: str | None) -> dict[str, Any]:
    """The `--config` file, parsed by `M-CONF`'s own reader.

    `parse_config_document` is the declared loader: it handles both formats, turns model
    tables into `ModelRef`s and raises `ConfigurationError` with a sentence an operator can
    act on. Hand-rolling a `json.loads` here — the first draft did — meant a TOML config, the
    format the repo's own fixtures are written in, died with a bare `JSONDecodeError` before
    the configuration was ever composed.

    The format is taken from the suffix, which is what an operator passing `harness.toml`
    expects; anything else is read as TOML, the documented default for the file.
    """
    from aeh.conf import parse_config_document

    if not path:
        return {}
    source = Path(path)
    fmt = "json" if source.suffix.lower() == ".json" else "toml"
    return parse_config_document(source.read_text(encoding="utf-8"), fmt)


def _build_parser() -> Any:
    parser = argparse.ArgumentParser(
        prog="aeh",
        description="Run, recover and serve the agentic evaluation harness.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="drive a cohort's run to completion")
    run_parser.add_argument("--data-dir", required=True)
    run_parser.add_argument("--cohort", required=True)
    run_parser.add_argument("--package-version", required=True)
    run_parser.add_argument("--config", default=None)

    recover_parser = sub.add_parser("recover", help="reclaim leases, resume and settle grades")
    recover_parser.add_argument("--data-dir", required=True)

    console_parser = sub.add_parser("console", help="recover, then serve the operator console")
    console_parser.add_argument("--data-dir", required=True)
    console_parser.add_argument("--config", default=None)
    return parser


def main(argv: "Sequence[str] | None" = None) -> int:
    """`python -m aeh` and the installed `aeh` command (`FR-PIPE-08`, `FR-PIPE-09`).

    Exit codes are the contract (`CT-PIPE-01`): **0** when the run completes, **3** when it
    pauses, **1** on any error. A paused run is not a failure — it is a run waiting for an
    operator — and collapsing the two would make an outage indistinguishable from a bug in
    every script that calls this.

    Returns rather than raising `SystemExit`: `aeh/__main__.py` does the raising, so this
    function stays callable from a test without catching an exception to read an integer.
    """
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "recover":
            store = _open_store(args.data_dir)
            try:
                report = recover(store)
            finally:
                store.close()
            print(json.dumps(_as_json(report), indent=2, sort_keys=True))
            return EXIT_OK

        if args.command == "console":
            from aeh.console import serve_console

            config = effective_config(_load_config_file(args.config))
            store = _open_store(args.data_dir)
            # `FR-PIPE-09`: recovery runs BEFORE the socket accepts, so an expired lease is
            # reclaimed rather than sitting held while an operator watches a stalled queue.
            recover(store)
            server = serve_console(store, cfg=config)
            # `serve_console` BINDS and returns: the accept loop runs on a daemon thread
            # (`console.py`), so returning here would end the process and take the thread with
            # it — the socket would close before anything could connect, and #365's "the
            # expired lease is reclaimed before the socket accepts" would be vacuously true
            # against a console that never accepted. So the command blocks, which is what an
            # operator running `aeh console` expects it to do.
            print(f"console listening on port {getattr(server, 'port', '?')} "
                  f"(pid {getattr(server, 'pid', '?')}); Ctrl-C to stop")
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
            finally:
                terminate = getattr(server, "terminate", None)
                if callable(terminate):
                    terminate()
            return EXIT_OK

        config = effective_config(_load_config_file(args.config))
        store = _open_store(args.data_dir)
        try:
            recover(store)
            result = _run_command(store, args, config)
        finally:
            store.close()
        print(json.dumps(_as_json(result), indent=2, sort_keys=True))
        if str(result.pause_reason or "").startswith(_FAULT_PREFIX):
            # A composition fault that could not pause the run — `pause()` refuses a terminal
            # run — used to leave `status == "complete"` and return 0, reporting success for a
            # run whose hook raised and whose scores may be missing. The fault is on the
            # result either way, so the exit code follows it (`CT-PIPE-01`).
            print(f"aeh run: {result.pause_reason}", file=sys.stderr)
            return EXIT_ERROR
        return EXIT_OK if result.status == "complete" else EXIT_PAUSED
    except Exception as error:  # noqa: BLE001 - the command line reports, never traces back
        print(f"aeh {args.command}: {type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_ERROR


def _run_command(store: Any, args: Any, config: Mapping[str, Any]) -> RunResult:
    """`aeh run`: look the run up or create it, then drive it (`FR-PIPE-08`)."""
    from aeh.conf import resolve_run_config

    orchestrator = Orchestrator(store)
    existing = [
        handle for handle in orchestrator.runs()
        if handle.cohort_id == args.cohort
        and handle.package_version_id == args.package_version
    ]
    # The cohort's DECLARED consent class, read from the store. `CohortRef`'s default is
    # `'real'` and fail-closed, so passing the bare id would refuse every synthetic cohort
    # against a remote backend — the gate firing on an answer nobody looked up.
    run_config = resolve_run_config(dict(config), orchestrator.cohort_ref(args.cohort))
    if existing:
        handle = existing[-1]
        run_id = handle.run_id
        # `FR-CONF-15` / `FR-ORCH-16`: a run resumes on the backend it froze. This command
        # resolves a FRESH `RunConfig` from the current environment, so driving an existing
        # run with it would rebind that run to whatever profile this process happens to carry.
        # Rebuilding the frozen `RunConfig` from the run row is not a surface this module has,
        # so the mismatch is refused rather than papered over: fail closed and say which
        # profile the run expects. Reported on #365 as the narrower gap it is.
        if handle.backend_profile and run_config.backend_profile != handle.backend_profile:
            raise ValueError(
                f"run {run_id} froze backend profile {handle.backend_profile!r} and this "
                f"process resolved {run_config.backend_profile!r}; a run resumes on the "
                f"backend it froze (FR-CONF-15). Set HARNESS_PROFILE to "
                f"{handle.backend_profile!r} to continue it."
            )
    else:
        run_id = orchestrator.create_run(
            args.cohort, args.package_version, run_config)
    # `create_run` leaves the run `pending`, and a pending run never reaches the completion
    # predicate: `_maybe_complete_run` fires only from `running`. Without this the command
    # dispatches every unit, spends every model call, and then returns `pending` with no
    # synthesis and no grades — exit 3 on a run that in fact finished its work. `start` is
    # idempotent enough to be safe on a run this command just created; an existing run that
    # is already running or paused is left to `recover` and the loop.
    if orchestrator.run_handle(run_id).status == "pending":
        orchestrator.start(run_id)
    # `FR-CONF-14`'s composition is only observable if the command says what it resolved, so
    # the profile summary goes to stdout before the run starts — an operator who switched
    # `HARNESS_PROFILE` can see which profile was selected and where it came from
    # (`TC-CONF-23`), rather than inferring it from how the run behaves.
    # Where the profile came from, then what it resolved to. The source is the half an
    # operator cannot infer from the summary: `HARNESS_PROFILE` in the environment beats the
    # file (`FR-CONF-14`), and after a switch the question is always "did it take mine?".
    source = "environment" if os.environ.get("HARNESS_PROFILE") else "config file"
    print(f"HARNESS_PROFILE source: {source}")
    summary = getattr(run_config, "profile_summary", None)
    if callable(summary):
        print(summary())
    provider = _provider_for(run_config)
    return run_to_completion(
        store, run_id, provider=provider, run_config=run_config)


def _as_json(value: Any) -> Any:
    """A `RunResult` or `RecoveryReport` as plain JSON — the shape stdout carries."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _as_json(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, (list, tuple)):
        return [_as_json(item) for item in value]
    if isinstance(value, Mapping):
        return {str(k): _as_json(v) for k, v in value.items()}
    return value
