"""`run_to_completion` and `recover`: drive a run pass by pass until it completes or stalls."""

from __future__ import annotations

import time
from typing import Any, Sequence

from aeh.conf import effective_config
from aeh.det import DeterministicEvaluator
from aeh.grade import open_grade
from aeh.integ import IntegrityGate, StoreExtractionView
from aeh.orch import Orchestrator
from aeh.pkg import PackageCatalog
from aeh.prov import BuildChangedError, ProviderUnavailableError

from .settings import _int_knob, MAX_PASSES_ENV, PASS_SLEEP_MS_ENV, STALL_PASSES
from .results import RecoveryReport, RunResult, StageTrace
from .executor import ProductionStageExecutor
from .decision_engine import (
    _decision_provider_for_run,
    _decision_run_start_checks,
    _decision_summary,
)
from .hooks import _aggregate_hook, _CellFault, _drain, _FAULT_PREFIX, _integrity_pre_hook
from .finishing import _grade, _grades_all_final, _synthesize


def _over_escalation_budget(orch: Any, run_id: str) -> bool:
    """Whether the run's escalation rate is over budget, which makes dispatch hold back its
    escalation pairs.

    That is the one no-progress condition retrying cannot clear: the deferred units stay
    pending until growth returns headroom, and on a cohort too small to grow it never does.
    Every other stall — a rate-limited pass, a peer holding a lease — is worth another pass.
    """
    try:
        return bool(getattr(orch.escalation_budget_state(run_id), "over_budget", False))
    except Exception:  # noqa: BLE001 - a stall decision must not raise
        return False


def _stall_reason(orch: Any, run_id: str) -> str:
    """Why a pass stopped making progress, in M-ORCH's own words.

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
    decision_provider: Any = None,
) -> RunResult:
    """Drive the run pass by pass until M-ORCH says it is complete, or it pauses.

    `FR-PIPE-01`. The returned `status` is the STORED `run.status`, read back through `M-ORCH`
    after the last pass, never this module's own idea of where the run got to.

    The four keyword refs are the design gaps `docs/code-notes/pipeline.md` names: `RunConfig` has no
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

    # FR-PIPE-11/12: the frozen decision engine's provider, and its run-start checks before
    # anything is leased. Both are no-ops with the engine off.
    decision_provider = _decision_provider_for_run(run_config, provider, decision_provider)
    _decision_run_start_checks(run_config, decision_provider)
    executor = ProductionStageExecutor(
        store, provider, run_config,
        high_risk_criteria=high_risk_criteria,
        extractor=extractor, second_family=second_family, judge_refs=judge_refs,
        decision_provider=decision_provider,
    )
    # The provider is bound alongside the executor: `M-ORCH` wraps it in the `GovernedProvider`
    # the stage workers actually call, so the run's counters see every call a worker makes
    # inside its own retry budget (`FR-ORCH-27`, `CT-PROV-11`).
    orch = Orchestrator(store, executor=executor, provider=provider,
                        decision_provider=decision_provider)
    executor.orchestrator = orch
    handle = orch.run_handle(run_id)
    catalog = PackageCatalog(store.package(handle.package_id), package_id=handle.package_id)
    view = StoreExtractionView(handle.cohort, catalog, handle.package_version_id, run_id)
    gate = IntegrityGate(handle.cohort, store.blobs(), view)

    stages: list[StageTrace] = []

    # `FR-PIPE-02`: the deterministic score rows must exist before the dispatch walk closes
    # their units, and that walk closes them directly without calling the evaluator.
    #
    # Inside the same fault discipline as every hook (#594): an exception here pauses the run
    # as a composition fault and returns a `RunResult` (FR-PIPE-01, seam 1), never a traceback.
    try:
        det = DeterministicEvaluator(store).evaluate_cohort(run_id)
    except Exception as error:  # noqa: BLE001 - recorded and paused, never swallowed
        fault = f"{_FAULT_PREFIX}{type(error).__name__}: {error}"
        stages.append(StageTrace("deterministic", detail=(fault,)))
        try:
            orch.pause(run_id, fault)
        except Exception:  # noqa: BLE001 - a terminal run refuses a pause; the status stands
            pass
        handle = orch.run_handle(run_id)
        if decision_provider is not None:
            # CT-PIPE-08: with an engine configured, every result carries its summary.
            stages.append(_decision_summary(handle, run_id))
        return RunResult(
            run_id=run_id,
            status=handle.status,
            pause_reason=fault,
            stages=tuple(stages),
            grades_computed=0,
            grades_final=0,
        )
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
            agg = _aggregate_hook(orch, handle, gate, catalog, view, store)
        except (ProviderUnavailableError, BuildChangedError):
            # Defensive only. `FR-ORCH-30` absorbs both per future inside `_run_model_batch`
            # and pauses the run there, so neither normally reaches this frame; if one ever
            # does, the stored status read below is the authority and this adds nothing to it.
            handle = orch.run_handle(run_id)
            break
        except Exception as error:  # noqa: BLE001 - recorded and paused, never swallowed
            cell = None
            if isinstance(error, _CellFault):
                cell = f"cell {error.submission_id}/{error.criterion_id}"
                error = error.error
            fault = f"{_FAULT_PREFIX}{type(error).__name__}: {error}"
            # Drain first: the pass that faulted may still have extracted and scored, and a
            # trace that dropped that work would under-report what the run actually did.
            stages.extend(_drain(executor))
            stages.append(StageTrace(
                "aggregate", detail=(fault,) if cell is None else (fault, f"{fault} at {cell}")))
            break

        stages.extend(_drain(executor))
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

    if decision_provider is not None:
        stages.append(_decision_summary(handle, run_id))

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
            # Synthesis ran after the last dispatch pass: persist what it accrued (#596).
            orch.flush_metrics(run_id)
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
    """Reclaim expired leases, resume open runs, and settle grades whose review window lapsed while
    the process was down.

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
        # FR-PIPE-16 / CT-PIPE-11 (#526): a complete run holding criterion scores with no
        # current grade (killed between completion and grading) is graded here too. A run
        # with no scores at all is left alone; a second recover finds every grade current.
        if not grading.has_criterion_scores(handle.run_id):
            continue
        if _grades_all_final(grading, handle.run_id) and not grading.has_ungraded_scores(
                handle.run_id):
            continue
        grading.compute_all(handle.run_id)
        regraded.append(handle.run_id)

    return RecoveryReport(
        leases_reclaimed=int(getattr(sweep, "requeued", 0) or 0),
        runs_resumed=tuple(resumed),
        runs_regraded=tuple(regraded),
    )
