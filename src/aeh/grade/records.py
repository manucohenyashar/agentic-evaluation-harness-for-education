"""The grades, reports and rollups M-GRADE returns to its callers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .policy import BoundaryRisk, Coverage


# --- the service ------------------------------------------------------------------------------------


class GradeError(Exception):
    """M-GRADE's base error: a run the service cannot grade, or an export format this
    module does not own. Not retryable — the caller asked for something the ledger
    does not hold."""


@dataclass(frozen=True)
class SubmissionGrade:
    """One persisted grade, read back (§3.14's `compute_one` return)."""

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
    """A `compute_all` pass's stage-level summary (CLAUDE.md seam 4): how many
    submissions were graded, under which policy version, and how the class's states
    read after the pass — never a bare success flag over an empty result."""

    run_id: str
    policy_version: str
    submitted: int
    computed: int
    grades_by_state: Mapping[str, int]


@dataclass(frozen=True)
class CoverageSummary:
    """The `coverage(run_id)` return: the class's state counts, named BEFORE any batch
    action is taken (`FR-GRADE-09`: the action names its coverage first). All three
    state keys are always present, zero included — a missing key is not a zero."""

    run_id: str
    grades_by_state: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalizationRecord:
    """The `finalize_batch` return: how many grades it settled, and the coverage it
    was named with — the record echoes the coverage the action was given, so the
    caller can check the action did what it named (`FR-GRADE-09`)."""

    finalized: int
    coverage: Mapping[str, int]
    actor: str
    settled_at: str


@dataclass(frozen=True)
class GradeRevision:
    """The `amend` return: the new revision the edit produced (§3.14: amend finalizes
    at revision n+1)."""

    submission_id: str
    revision: int
    state: str
    grade: str | None
    total: float | None
    actor: str
    reason: str


@dataclass(frozen=True)
class RollupSegment:
    """One rubric version's slice of a rollup (`CT-CALIB-09`): the figures of one
    instrument, never averaged blind across versions."""

    rubric_version: str
    submission_count: int
    mean_total: float | None


@dataclass(frozen=True)
class ClassRollup:
    """A cohort's (or run's) rollup, segmented by rubric version, with the annotation
    that names every version the figures cover — the explicit annotation
    `CT-CALIB-09` requires whenever more than one instrument contributed."""

    segments: tuple[RollupSegment, ...]
    revision_annotation: str


@dataclass(frozen=True)
class CriterionBandFigure:
    """One criterion's band figures (`FR-GRADE-14`, `TC-GRADE-14`): the histogram is
    always a real count; `entropy` and `interior_rate` are **null for deterministic
    criteria** — never zero, because "no figure" is a different claim from "no
    variation" (`CT-GRADE-13` makes the nulls a consumer obligation, so the producer
    emits a real None). Entropy is in nats (natural log) — the base is a convention
    the design leaves open and the committed reference in `TC-GRADE-14` pins."""

    criterion_id: str
    histogram: Mapping[str, int]
    entropy: float | None
    interior_rate: float | None


@dataclass(frozen=True)
class RollupBlock:
    """One block of the separated rollup (`FR-GRADE-15`): a population and the
    per-criterion figures over it. Judged and deterministic results each get their
    own block; nothing on the separated rollup composes across the two."""

    submission_count: int
    criteria: tuple[CriterionBandFigure, ...]


@dataclass(frozen=True)
class SeparatedRollup:
    """The run's rollup with deterministic results in a block separate from judged
    ones (`FR-GRADE-15`, `CT-GRADE-12`), and no combined figure anywhere: the record
    carries exactly these two blocks, each over its own population — a figure across
    judged and deterministic results is the clause's exact refusal (the two are not
    comparable)."""

    judged: RollupBlock
    deterministic: RollupBlock


@dataclass(frozen=True)
class RollupFinding:
    """One rollup finding (`FR-GRADE-16`, `TC-GRADE-16`): a criterion the system
    could not apply, the count of students it touched, and what happened — a finding
    that names a criterion but not its reach leaves the teacher guessing."""

    criterion_id: str
    student_count: int
    reason: str


@dataclass(frozen=True)
class GradeArtifacts:
    """The school-facing export's result (`FR-GRADE-17`, `TC-REG-03`): one CSV of
    marks and one PDF per student, as written paths — the caller hands them to the
    school; nothing here leaves the machine (`CT-GRADE-16`)."""

    csv_path: Path
    pdf_paths: tuple[Path, ...]
