"""The last stages of a run: narrative synthesis and grading."""

from __future__ import annotations

from typing import Any

from aeh.grade import open_grade
from aeh.synth import SynthesisWorker

from .results import StageTrace
from .executor import _default_synthesizer


def _submissions_of(orch: Any, run_id: str) -> tuple[str, ...]:
    """Every submission the run enumerated, in enumeration order, without reading the ledger.

    FR-PIPE-17 / CT-PIPE-13 (#523): `M-ORCH`'s own per-run list (`Orchestrator.submissions`,
    FR-ORCH-42), so a submission whose criteria are all deterministic, which has neither
    extract nor score units, is still offered to synthesis. `CT-PIPE-05` forbids this module
    reading the ledger itself.
    """
    return tuple(orch.submissions(run_id))


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
    # ADR-14 / CT-PIPE-06 (#596): synthesis calls go through the run's governed provider, so
    # they accrue to the run's counters like every stage worker's calls, and each
    # submission's measured cost is charged against the run's frozen ceiling. A caller with
    # no provider keeps the old per-submission failure, so grading still runs (FR-PIPE-06).
    governed = orch.governed_provider(handle.run_id, provider) if provider is not None else None
    worker = SynthesisWorker(store, governed if governed is not None else provider, ref)
    detail: list[str] = []
    done = failed = 0
    for submission_id in _submissions_of(orch, handle.run_id):
        stop = orch.post_dispatch_ceiling_reached(handle.run_id)
        if stop is not None:
            # No more spend: the remaining submissions get no narrative, and grading runs.
            detail.append(f"synthesis stopped before {submission_id}: {stop}")
            break
        before = governed.spent() if governed is not None else None
        try:
            report = worker.synthesize_submission(handle.run_id, submission_id)
        except Exception as error:  # noqa: BLE001 - recorded, never fatal to grading
            failed += 1
            detail.append(f"{submission_id}: {type(error).__name__}: {error}")
            continue
        finally:
            if governed is not None:
                orch.charge_post_dispatch(handle.run_id, governed.spent() - before)
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


def _grades_all_final(grading: Any, run_id: str) -> bool:
    """Whether every grade of one run is settled.

    Read through `coverage`, which counts the STORED `state` column (plus a derived
    `incomplete` for a submission with no current row). It does **not** re-evaluate review
    windows — an earlier draft of this docstring claimed it did, and that claim was not only
    false but backwards: if `coverage` settled a lapsed window on read, a lapsed run would
    report as final and `FR-PIPE-07`'s whole third step would never fire. It is precisely
    because the stored state is stale that recovery has to re-grade.

    A run with **no grades at all** reads as settled here. Its criterion scores may still
    exist with grading never run (the killed-after-completion state `NFR-PIPE-01` names);
    `recover` asks `GradingService.has_ungraded_scores` for that case separately (FR-PIPE-16,
    #526), so this predicate stays about the grades that exist.
    """
    by_state = dict(getattr(grading.coverage(run_id), "grades_by_state", {}) or {})
    total = sum(int(n) for n in by_state.values())
    if total == 0:
        return True
    return int(by_state.get("final", 0)) == total
