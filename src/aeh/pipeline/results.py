"""What driving a run returns: the result, per-stage traces, and the recovery report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class CompositionFault(RuntimeError):
    """A hook raised an error that is not a provider condition.

    Never swallowed and never re-raised past `run_to_completion`: the run is paused with
    `pause_reason="composition fault: <type>: <msg>"` and the fault rides in the stage's
    `detail`, because a composition bug that pauses a run silently is the failure mode seam 4
    exists to prevent.
    """


@dataclass(frozen=True)
class StageTrace:
    """What one stage did during one call.

    `detail` is never a bare status: a `status=success` sitting on an empty result is the top
    silent-failure trap, so every entry says what was processed.
    """

    stage: str
    units: int = 0
    done: int = 0
    quarantined: int = 0
    detail: tuple[str, ...] = ()
    #: Jev design delta FR-PIPE-13: structured figures a stage reports beside its detail — the
    #: decision-engine summary on the score stage, by CT-JUDGE-28's names. `None` elsewhere.
    metrics: Any = None


@dataclass(frozen=True)
class RunResult:
    """The result of driving one run. `status` is the run's stored status (FR-PIPE-01)."""

    run_id: str
    status: str
    pause_reason: str | None
    stages: tuple[StageTrace, ...]
    grades_computed: int
    grades_final: int


@dataclass(frozen=True)
class RecoveryReport:
    """What `recover` reclaimed, resumed and regraded (FR-PIPE-07).

    `recover()` fills it (`FR-PIPE-07`): what one sweep reclaimed, which paused runs it
    resumed, and which complete runs it re-graded after a review window lapsed.
    """

    leases_reclaimed: int = 0
    runs_resumed: tuple[str, ...] = ()
    runs_regraded: tuple[str, ...] = ()
