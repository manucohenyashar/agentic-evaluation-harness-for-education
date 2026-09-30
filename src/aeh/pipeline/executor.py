"""`ProductionStageExecutor`: the real stage doors (extract, judge, score) that M-ORCH calls."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from aeh.conf import ModelRef
from aeh.extract import ExtractionWorker
from aeh.judge import JudgmentError, ScoringWorker
from aeh.orch import ESCALATION_ARM_PREFIX, STAGE_EXTRACT, STAGE_SCORE, StageOutcome

from .results import CompositionFault
from .decision_engine import _engine_tag


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
        decision_provider: Any = None,
    ) -> None:
        self._store = store
        self._provider = provider
        #: FR-PIPE-11: handed to every `ScoringWorker` with the frozen run config, so the
        #: decision seat is pre-screened by the engine the run froze.
        self._decision_provider = decision_provider
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
            worker = ScoringWorker(self._store, governed, judge,
                                   decision_provider=self._decision_provider,
                                   run_config=self._run_config)
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
                      f"{getattr(result, 'band', '?')}{_engine_tag(self._run_config, result)}")
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
