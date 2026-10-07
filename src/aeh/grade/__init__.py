"""M-GRADE: turns criterion scores into grades, and keeps them (design §3.14).

For each submission the package's grade policy is applied to the stored criterion scores: the
points are summed and scaled, and the scaled score is resolved to a grade band. A grade is
`provisional` while any of its inputs still waits on review, `incomplete` while an input is
missing, and `final` once settled. Every grade records coverage (how many criteria were
scored, and how) and boundary risk (whether pending criteria could still move it across a
band). Grades are stored append-only: an amendment writes a new revision and an audit record,
never an update in place. M-GRADE also produces rollups and the school-facing export.

Files:
    constants.py     grade states, routings and the export directory knob
    refs.py          timestamps and the content hashes a grade records
    policy.py        the pure policy computation: scores in, grade, coverage and boundary risk out
    band_figures.py  per-criterion band histograms and entropy
    stored_rows.py   reading stored score rows, with amendment overrides applied
    schema.py        migrations, the append-only triggers, and the SQL statements
    records.py       the grades, reports and rollups returned to callers
    pdf.py           one student's feedback document as a PDF
    finalization.py  coverage counts and the batch finalization action
    amendments.py    manual amendments and their audit records
    reporting.py     the run rollup and export methods of the service
    service.py       `GradingService`: computes and stores every grade of a run
    rollups.py       class rollups, the separated rollup and rollup findings
    views.py         the per-criterion view: a composite presented as one line
    exports.py       the school-facing export: one PDF per student and a marks CSV
    results.py       the run's results records and rollup, shared by the console views and the CLI
    signals.py       the grading stage's signals and alerts

Detailed design notes (the full original module description): `docs/code-notes/grade.md`.
"""

from __future__ import annotations

from .constants import (
    export_dir,
    GRADE_EXPORT_DIR_ENV,
    GRADE_STATES,
    HARNESS_EXPORT_DIR_ENV,
    ROUTING_AUTO,
    ROUTING_PROVISIONAL,
    ROUTING_QUEUED,
    ROUTING_REVIEWED,
    ROUTING_TRIAGE,
    STATE_FINAL,
    STATE_INCOMPLETE,
    STATE_PROVISIONAL,
    STATUS_COMPLETE,
)
from .refs import answer_key_ref_of, policy_version_of
from .policy import (
    apply_policy,
    boundary_risk,
    BoundaryRisk,
    Coverage,
    coverage_for,
    CriterionInput,
    GradeComputation,
    resolve_grade,
)
from .band_figures import criterion_band_figures
from . import stored_rows  # noqa: F401  (imported for its registrations)
from .schema import enforce_ledger_append_only, GRADE_STATEMENTS
from .records import (
    ClassRollup,
    CoverageSummary,
    CriterionBandFigure,
    FinalizationRecord,
    GradeArtifacts,
    GradeError,
    GradeReport,
    GradeRevision,
    RollupBlock,
    RollupFinding,
    CriterionLine,
    RollupSegment,
    SeparatedRollup,
    SubmissionGrade,
)
from .rollups import class_rollup, cohort_with_mixed_revisions, rollup_findings, separated_rollup
from . import pdf  # noqa: F401  (imported for its registrations)
from .finalization import FinalizationMixin
from .amendments import AmendmentMixin
from .reporting import ReportingMixin
from .service import GradingService, open_grade
from .exports import export_grade_artifacts
from .results import run_class_view, run_grade_records, run_results
from .signals import evaluate_grade_alerts, GradeAlert, record_grade_signals


__all__ = [
    "BoundaryRisk",
    "ClassRollup",
    "Coverage",
    "CoverageSummary",
    "CriterionBandFigure",
    "CriterionInput",
    "GRADE_EXPORT_DIR_ENV",
    "GRADE_STATEMENTS",
    "GRADE_STATES",
    "GradeAlert",
    "GradeArtifacts",
    "GradeComputation",
    "GradeError",
    "GradeReport",
    "GradeRevision",
    "GradingService",
    "FinalizationRecord",
    "HARNESS_EXPORT_DIR_ENV",
    "RollupBlock",
    "RollupFinding",
    "CriterionLine",
    "RollupSegment",
    "SeparatedRollup",
    "SubmissionGrade",
    "answer_key_ref_of",
    "apply_policy",
    "boundary_risk",
    "class_rollup",
    "criterion_band_figures",
    "cohort_with_mixed_revisions",
    "coverage_for",
    "enforce_ledger_append_only",
    "evaluate_grade_alerts",
    "export_dir",
    "export_grade_artifacts",
    "open_grade",
    "policy_version_of",
    "record_grade_signals",
    "resolve_grade",
    "rollup_findings",
    "run_class_view",
    "run_grade_records",
    "run_results",
    "separated_rollup",
]
