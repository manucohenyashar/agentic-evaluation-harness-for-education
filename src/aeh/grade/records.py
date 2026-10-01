"""The grades, reports and rollups M-GRADE returns to its callers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .policy import BoundaryRisk, Coverage


# --- the service ------------------------------------------------------------------------------------


class GradeError(Exception):
    """M-GRADE's base error: a run it cannot grade, or an export format it does not support. Not
    retryable."""


@dataclass(frozen=True)
class SubmissionGrade:
    """One stored grade, read back (what `compute_one` returns)."""

    run_id: str
    submission_id: str
    revision: int
    state: str
    grade: str | None
    total: float | None
    policy_version: str
    answer_key_ref: str
    computed_at: str
    finalized_at: str | None
    coverage: Coverage
    boundary: BoundaryRisk
    missing: tuple[str, ...]


@dataclass(frozen=True)
class GradeReport:
    """What one `compute_all` pass did: how many submissions were graded, under which policy
    version, and the class's grade states afterwards."""

    run_id: str
    policy_version: str
    submitted: int
    computed: int
    grades_by_state: Mapping[str, int]


@dataclass(frozen=True)
class CoverageSummary:
    """What `coverage(run_id)` returns: the class's grade counts by state, reported before any
    batch action (FR-GRADE-09). All three states are always present, including zeros."""

    run_id: str
    grades_by_state: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalizationRecord:
    """What `finalize_batch` returns: how many grades it settled and the coverage it reported
    before acting, so the caller can check it did what it said (FR-GRADE-09)."""

    finalized: int
    coverage: Mapping[str, int]
    actor: str
    settled_at: str


@dataclass(frozen=True)
class GradeRevision:
    """What `amend` returns: the new revision the amendment produced (revision n+1)."""

    submission_id: str
    revision: int
    state: str
    grade: str | None
    total: float | None
    actor: str
    reason: str


@dataclass(frozen=True)
class RollupSegment:
    """One rubric version's part of a rollup (CT-CALIB-09). Figures from different versions are
    never averaged together."""

    rubric_version: str
    submission_count: int
    mean_total: float | None


@dataclass(frozen=True)
class ClassRollup:
    """A cohort's or run's rollup, split by rubric version, with a note naming every version the
    figures cover (CT-CALIB-09)."""

    segments: tuple[RollupSegment, ...]
    revision_annotation: str


@dataclass(frozen=True)
class CriterionBandFigure:
    """One criterion's band figures (FR-GRADE-14, TC-GRADE-14). The histogram is always a real
    count. `entropy` and `interior_rate` are None for deterministic criteria, never zero, because
    "no figure" is a different claim from "no variation" (CT-GRADE-13). Entropy is in nats."""

    criterion_id: str
    histogram: Mapping[str, int]
    entropy: float | None
    interior_rate: float | None


@dataclass(frozen=True)
class RollupBlock:
    """One block of the separated rollup: a population and the per-criterion figures over it
    (FR-GRADE-15). Judged and deterministic results each get their own block."""

    submission_count: int
    criteria: tuple[CriterionBandFigure, ...]


@dataclass(frozen=True)
class SeparatedRollup:
    """The run's rollup with deterministic results in a separate block from judged ones, and no
    figure that combines the two (FR-GRADE-15, CT-GRADE-12): they are not comparable."""

    judged: RollupBlock
    deterministic: RollupBlock


@dataclass(frozen=True)
class RollupFinding:
    """One rollup finding (FR-GRADE-16, TC-GRADE-16): a criterion the system could not apply, how
    many students it affected, and what happened."""

    criterion_id: str
    student_count: int
    reason: str


@dataclass(frozen=True)
class GradeArtifacts:
    """The school-facing export's result: the paths of one marks CSV and one PDF per student
    (FR-GRADE-17, TC-REG-03). Nothing here leaves the machine (CT-GRADE-16)."""

    csv_path: Path
    pdf_paths: tuple[Path, ...]
