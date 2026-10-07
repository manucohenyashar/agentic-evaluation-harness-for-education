"""The hooks between stages: integrity verification, then aggregation of each ready cell."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from aeh.agg import (
    EvenPanelError,
    aggregate,
    aggregate_even_panel_after_quarantine,
    should_escalate,
    write_score,
)
from aeh.judge import verdicts_for
from aeh.orch import (
    DECISION_HALTED_BY_BREAKER,
    DECISION_NO_REAL_SEAT,
    REPLACEMENT_INSERTED,
    REPLACEMENT_NOT_APPLICABLE,
    REPLACEMENT_REFUSED,
    STAGE_EXTRACT,
    STAGE_SCORE,
)
from aeh.prov import BuildChangedError, ProviderUnavailableError

from .results import CompositionFault, StageTrace


# --- the cell hooks -------------------------------------------------------------------------


def _criterion_value(catalog: Any, view: Any, version: str, criterion_id: str) -> Any:
    """The criterion value `aggregate` needs, built from the package.

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


def _drain(executor: Any) -> list[StageTrace]:
    """The executor's per-unit records so far, as one trace per stage, and clear them.

    `FR-PIPE-01` wants one entry per stage executed, and extract and score are executed in the
    dispatch pass rather than in a hook — so without this they are the two stages a run never
    reports having run.
    """
    drained: list[StageTrace] = []
    for stage_name in (STAGE_EXTRACT, STAGE_SCORE):
        done = executor.executed.get(stage_name) or []
        if done:
            drained.append(StageTrace(
                stage_name, units=len(done), done=len(done), detail=tuple(done)))
            executor.executed[stage_name] = []
    return drained


def _integrity_pre_hook(orch: Any, handle: Any, gate: Any) -> StageTrace:
    """Verify each cell whose extraction has finished, once, and record the phase (FR-PIPE-03).

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


#: FR-PIPE-15 (#525): each run's escalation inputs, read ONCE and kept for the run's
#: lifetime, so a promotion landing mid-run is not seen until the next run (Q-45).
_ESCALATION_INPUTS: dict[tuple[str, str], dict[str, tuple[Any, Any]]] = {}


def _escalation_inputs(store: Any, handle: Any, catalog: Any, criterion: Any) -> tuple[Any, Any]:
    """`(baseline, history)` for one criterion of the run, read through each owner's public
    interface (no SQL here, CT-PIPE-05). The baseline comes from `PackageCatalog.baselines_for`
    under the run's frozen backend profile and panel build; the history is M-STATS' override figure
    over the package lineage (FR-STATS-24). A `NoValidationData` from either is passed on as it is,
    never as None (CT-PIPE-10)."""
    from aeh.stats import stored_override_histories

    # Keyed by the store's data directory AND the run: two stores in one process (every
    # test world) may reuse a run id, and one must never answer for the other (#525 review).
    cache_key = (str(getattr(store, "data_dir", id(store))), handle.run_id)
    cached = _ESCALATION_INPUTS.get(cache_key)
    if cached is None:
        # Every criterion's pair at once, on the run's first read (Q-45: fixed for the run).
        if len(_ESCALATION_INPUTS) >= 64:
            _ESCALATION_INPUTS.clear()
        histories = stored_override_histories(store, handle.package_version_id)
        baselines = catalog.baselines_for(
            handle.package_version_id, backend_profile=handle.backend_profile,
            panel_build_ref=getattr(handle, "panel_build_ref", ""))
        cached = {criterion_id: (baseline, histories.get(criterion_id))
                  for criterion_id, baseline in baselines.items()}
        _ESCALATION_INPUTS[cache_key] = cached
    baseline, history = cached.get(str(criterion.criterion_id), (None, None))
    from aeh.pkg import NoValidationData

    if baseline is None:
        baseline = NoValidationData()
    if history is None:
        history = NoValidationData(reason="no_blind_labels", n=0)
    return baseline, history


def _aggregate_hook(orch: Any, handle: Any, gate: Any, catalog: Any, view: Any,
                    store: Any = None, seats: int | None = None) -> StageTrace:
    """For each ready cell: verify it, read its verdicts, aggregate them, and write the rest in one
    transaction (FR-PIPE-04).

    The order is the requirement's, and the single transaction is the half that matters: the
    score, the escalation it triggers and the phase recording both commit together or not at
    all. A crash between them is what `NFR-PIPE-01` is about, because a phase recorded beside
    work that rolled back makes a restart skip the work.

    `fallback=True` at exactly two verdicts is `FR-PIPE-05`: a terminal failure left an even
    panel, and an even panel is never aggregated as one.
    """
    ready = orch.ready_cells_with_units(handle.run_id, "aggregate")
    if not ready:
        # Most passes have no cell ready: the run-wide count reads below are only needed for
        # cells this pass aggregates (NFR-PIPE-02, #597).
        return StageTrace("aggregate", units=0, done=0, detail=())
    # One read returns the ready cells AND their score-stage unit figures, so the two
    # run-wide GROUP BY reads this hook used to issue per pass (the same statement, twice —
    # `cell_unit_counts`, then `cell_quarantined_counts` over it) are gone (NFR-PIPE-02,
    # #597). The cells are the read's own, so each lookup below is total.
    cells = [cell.key for cell in ready]
    units_by_key = {cell.key: cell for cell in ready}
    # `FR-PIPE-04` step 3 spells `aggregate(..., breaker_tripped=..., fallback=...)`, and the
    # flag is not cosmetic: a criterion whose breaker latched must score `provisional` /
    # `ungradeable_by_panel` rather than `auto` / `final` (`FR-ORCH-13`, `CT-ORCH-16`). The
    # panel's own figure still stands; what the breaker changes is whether it may be trusted
    # unreviewed.
    #
    # Read ONCE, then kept current from the escalation reports below. `enqueue_escalation`
    # latches the breaker inside the transaction this hook opens, so a stale read would let a
    # later cell of the same criterion aggregate with `False`, be phase-marked, and never
    # re-aggregate — its score staying `auto`/`final` where `CT-ORCH-16` requires
    # `provisional`/`ungradeable_by_panel`.
    #
    # Re-reading per cell fixed that and cost too much: `tripped_breakers` walks the cohort
    # files and queries each one, and `NFR-PIPE-02` budgets composition overhead at under 5%
    # of scheduling at 23,000 units. The report already says when a widening was breaker-
    # halted, so the set is updated from it instead.
    latched = {trip.criterion_id for trip in orch.tripped_breakers(handle.run_id)}
    detail: list[str] = []
    escalated = 0
    current: Any = None
    try:
        for cell in cells:
            current = cell
            signals = gate.verify(handle.run_id, cell.submission_id, cell.criterion_id)
            verdicts = verdicts_for(
                handle.cohort, handle.run_id, cell.submission_id, cell.criterion_id)
            terminal_units = units_by_key[cell].terminal
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
            baseline, history = ((None, None) if store is None
                                 else _escalation_inputs(store, handle, catalog, criterion))
            quarantined = units_by_key[cell].quarantined
            if len(verdicts) % 2 == 0 and len(verdicts) > 2 and quarantined > 0:
                # FR-PIPE-18 / CT-PIPE-12 (#524, ADR-34): quarantine left a widened panel even.
                # Ask M-ORCH for one replacement arm and leave the cell unaggregated; when the
                # arm is refused, the cell is `ungradeable_by_panel` and goes to review. The run
                # does not pause. (An even panel reached any other way still raises below.)
                with handle.cohort.transaction() as tx:
                    if seats is not None and terminal_units + 1 > seats:
                        # No real model for the replacement's seat (see `seats` below): the
                        # arm is refused here, exactly as a refused arm is.
                        replacement = SimpleNamespace(
                            decision=REPLACEMENT_REFUSED, arm=None,
                            reason=f"no real judge for seat {terminal_units + 1}")
                    else:
                        replacement = orch.enqueue_replacement_arm(
                            tx, (handle.run_id, cell.submission_id, cell.criterion_id))
                    if replacement.decision == REPLACEMENT_NOT_APPLICABLE:
                        # By the ledger's own count nothing was quarantined: an even panel
                        # reached another way is a defect, and it pauses the run.
                        raise EvenPanelError(
                            f"cell {cell.submission_id}/{cell.criterion_id} holds an even panel "
                            f"of {len(verdicts)} with no quarantined unit (FR-PIPE-18)")
                    if replacement.decision == REPLACEMENT_INSERTED:
                        detail.append(
                            f"{cell.submission_id}/{cell.criterion_id}: even panel of "
                            f"{len(verdicts)} after {quarantined} quarantined arm(s) -> "
                            f"replacement arm {replacement.arm}")
                        continue
                    score = aggregate_even_panel_after_quarantine(verdicts, criterion, signals)
                    write_score(tx, handle.run_id, cell.submission_id, score, signals)
                    orch.mark_cell_phase(
                        tx, handle.run_id, cell.submission_id, cell.criterion_id,
                        "aggregated", units_consumed=terminal_units,
                    )
                detail.append(
                    f"{cell.submission_id}/{cell.criterion_id}: even panel after quarantine, "
                    f"replacement refused ({replacement.reason}) -> ungradeable_by_panel")
                continue
            score = aggregate(
                verdicts, criterion, signals,
                # `FR-PIPE-05`: exactly two verdicts after a terminal failure. An earlier draft
                # widened this to any even count, which was INERT — `agg.aggregate` reads
                # `fallback and len(verdicts) == 2` and its own docstring says "any other even
                # size still raises `EvenPanelError`". The widened form changed nothing while the
                # comment above it claimed to cover the 4-verdict case, which is the sort of false
                # rationale this file has had to correct twice already.
                #
                # A 4-verdict panel reached through quarantine is handled above (FR-PIPE-18,
                # #524): a replacement arm, or `ungradeable_by_panel`. An even panel reached any
                # other way still raises here, which pauses the run as a composition fault: that
                # is a defect signal, and FR-PIPE-05's "never with an even panel" stands.
                # "after a terminal failure": two verdicts with nothing quarantined is an even
                # panel reached some other way, a defect that must pause (TC-PIPE-23(c)).
                fallback=len(verdicts) == 2 and quarantined > 0,
                breaker_tripped=cell.criterion_id in latched,
            )
            # `should_escalate` is pure (FR-AGG-08); the decision is the unmodified score's.
            decision = should_escalate(
                score=score, criterion=criterion, history=history, baseline=baseline)
            escalates = bool(getattr(decision, "escalate", False))
            seatless = False
            with handle.cohort.transaction() as tx:
                write_score(tx, handle.run_id, cell.submission_id, score, signals)
                if escalates:
                    # `seats`: how many judge models the run can really serve (panel, then the
                    # configured escalation judges); None when any seat can be (a recording).
                    # M-ORCH checks it only where it would write units, so a pair already
                    # widened stays the no-op it is.
                    reports = orch.enqueue_escalation(
                        tx, (handle.run_id, cell.submission_id, cell.criterion_id), seats=seats)
                    # A widening the breaker halted did not escalate anything; counting it would
                    # make the trace claim work that was refused (`FR-ORCH-13`).
                    if any(int(getattr(r, "units_inserted", 0) or 0) for r in reports):
                        escalated += 1
                    if any(getattr(r, "decision", None) == DECISION_HALTED_BY_BREAKER
                           for r in reports):
                        # The breaker latched inside this transaction; every later cell of the
                        # same criterion in this pass must see it.
                        latched.add(cell.criterion_id)
                    seatless = any(getattr(r, "decision", None) == DECISION_NO_REAL_SEAT
                                   for r in reports)
                    if seatless and score.state == "final":
                        # The panel's figure stands, but a wider panel was wanted and could
                        # not be seated: it goes to the teacher rather than being settled.
                        score = replace(
                            score, routing="provisional", state="provisional_unreviewed",
                            notes=score.notes + (
                                "escalation wanted, no real judge model for the next seats: "
                                "provisional, routed to review",))
                        write_score(tx, handle.run_id, cell.submission_id, score, signals)
                orch.mark_cell_phase(
                    tx, handle.run_id, cell.submission_id, cell.criterion_id,
                    "aggregated", units_consumed=terminal_units,
                )
            detail.append(
                f"{cell.submission_id}/{cell.criterion_id}: {score.band} over "
                f"{len(verdicts)} verdicts" + (
                    f" -> escalation wanted, no real judge for seats {terminal_units + 1}-"
                    f"{terminal_units + 2}: {score.state}" if seatless
                    else " -> escalated" if escalates else "")
            )
    except (ProviderUnavailableError, BuildChangedError):
        # Not faults: `run_to_completion` lets these two through to the stored status by type.
        raise
    except Exception as error:
        if current is None:
            raise
        # TC-PIPE-13 (#595): the fault names the cell it was working on, so an operator
        # can tell which (submission, criterion) broke. The exception itself is carried
        # unchanged, and the run's pause reason stays its type and text.
        raise _CellFault(error, current.submission_id, current.criterion_id) from error
    if escalated:
        detail.append(f"{escalated} cell(s) escalated")
    return StageTrace("aggregate", units=len(cells), done=len(cells), detail=tuple(detail))


# --- the command line (issue #365, FR-PIPE-08, FR-PIPE-09) ----------------------------------

#: `FR-PIPE-08`'s exit codes. Changing this mapping is a breaking change to `CT-PIPE-01`.
#: The marker a composition fault carries in `RunResult.pause_reason`.
_FAULT_PREFIX = "composition fault: "


class _CellFault(Exception):
    """An exception raised by the aggregate hook, together with the cell it was working on (#595).

    Internal to this module: `run_to_completion` unwraps it, so the pause reason carries the
    original exception's type and text exactly as before, and only the stage detail gains the
    cell."""

    def __init__(self, error: BaseException, submission_id: str, criterion_id: str) -> None:
        super().__init__(str(error))
        self.error = error
        self.submission_id = submission_id
        self.criterion_id = criterion_id
