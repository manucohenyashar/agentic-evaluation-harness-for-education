"""`run_for_assignment`: runs calibration for one assignment and reports each stage."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .elicitation import apply_answers, elicit, Finding


# --- the headless driver: one run, structured outcome (CT-CALIB-10, CT-CALIB-01) --------------------
#
# run_for_assignment is the module's headless entry point: given an assignment's
# situation it returns what happened and why — which rubric grades the class, whether
# anything was skipped and on what grounds, what was asked, what landed. Never a bare
# status (seam 4), and never on the critical path of grade delivery (CT-CALIB-01):
# every branch either grades against R₀ as given or lands an edit whose going-live is
# the gates' decision, not this module's.

#: The R₀ default the assignment factory pins — the same value the contract suite pins,
#: so "graded against R₀" is checked against a value the caller chose.
_DEFAULT_R0_VERSION = "pkg-v1-r0"


@dataclass(frozen=True)
class Assignment:
    """One assignment's calibration situation: whether the rubric was published to
    students in advance (`FR-CALIB-12` — the case where calibration must default to
    R₀ and say why), whether the teacher skipped calibration (`FR-CALIB-13`'s lower-
    confidence path), which version is R₀ for this assignment, and which criteria the
    discovery round flagged as ambiguous (the ones a skip must mark lower-confidence)."""

    rubric_published_in_advance: bool = False
    skip_elicitation: bool = False
    r0_version: str = _DEFAULT_R0_VERSION
    ambiguous_criteria: tuple[str, ...] = ()


def assignment(
    *,
    rubric_published_in_advance: bool = False,
    skip_elicitation: bool = False,
    r0_version: str = _DEFAULT_R0_VERSION,
    ambiguous_criteria: Sequence[str] = (),
) -> Assignment:
    """Build an `Assignment` — the driver's input value, with the R₀ default pinned."""
    return Assignment(
        rubric_published_in_advance=rubric_published_in_advance,
        skip_elicitation=skip_elicitation,
        r0_version=r0_version,
        ambiguous_criteria=tuple(ambiguous_criteria),
    )


@dataclass(frozen=True)
class CalibrationRunOutcome:
    """What one calibration run did, per stage (seam 4) — never a bare status.

    `active_rubric` is the rubric this run's grades use; `revised_version` is the
    version an edit landed on, when one did. The two are different fields on purpose:
    a revision that landed is not a revision that went live — whether it grades the
    next pass is the gates' decision (#139), and an outcome that quietly promoted its
    own revision would be a revision shipped with a warning by another name."""

    r0_version: str
    active_rubric: str
    fairness_note: str
    skipped: bool
    questions_asked: int = 0
    revised_version: str | None = None
    lower_confidence_criteria: tuple[str, ...] = ()
    revision_shipped: bool = False
    notes: tuple[str, ...] = ()

    @property
    def ambiguous_criteria_lower_confidence(self) -> bool:
        """Whether the ambiguous criteria were actually marked lower-confidence —
        the second half of `FR-CALIB-10`'s terminal state ("grade with the rubric
        as given, be more conservative on the ambiguous criteria"), which a run
        that only reported its rubric would otherwise fail silently."""
        return bool(self.lower_confidence_criteria)

    @property
    def shipped_with_warning(self) -> bool:
        """Structurally False (`CT-CALIB-02`): no code path on this surface ships a
        revision carrying a warning. A warned revision is a revision — it goes live,
        scores the class, and carries construct drift into every accumulated
        validation record (RISK-06) — so the clause forbids the path, not just the
        silent version of it. The property is the checkable statement of that refusal,
        in the same shape as `TriageVerdict`'s `fitted`: a caller asserts it, and a
        code path that could set it True cannot be written without the assertion
        failing."""
        return False


def run_for_assignment(
    assignment: Assignment,
    *,
    findings: Sequence[Finding] | None = None,
    answers: Mapping[str, str] | None = None,
    catalog: Any | None = None,
    environ: Mapping[str, str] | None = None,
) -> CalibrationRunOutcome:
    """Run calibration for one assignment and return what it did, per stage.

    The published branch is the clause with teeth (`CT-CALIB-10`/`FR-CALIB-12`): where
    the rubric was published to students in advance, calibration defaults to R₀ and
    SAYS WHY — a silent default is correct behaviour nobody can see. The skip branch
    grades the class with R₀ unchanged, marks the ambiguous criteria lower-confidence
    (`FR-CALIB-13`), and applies nothing — the skip is never on the critical path
    (`CT-CALIB-01`). The full branch elicits, applies the answers through the catalog,
    and reports the revision as landed-but-not-live: the gates own that decision."""
    lower_confidence = tuple(assignment.ambiguous_criteria)
    if assignment.rubric_published_in_advance:
        return CalibrationRunOutcome(
            r0_version=assignment.r0_version,
            active_rubric=assignment.r0_version,
            fairness_note=(
                "the rubric was published to students in advance: revising it now would "
                "change the assignment after the students answered it, so calibration "
                f"defaulted to R₀ ({assignment.r0_version}) and the flagged ambiguities "
                "are recorded for the next cohort's rubric"
            ),
            skipped=True,
            lower_confidence_criteria=lower_confidence,
            revision_shipped=False,
            notes=("rubric published in advance: defaulted to R₀, nothing elicited, "
                   "nothing applied",),
        )
    if assignment.skip_elicitation:
        return CalibrationRunOutcome(
            r0_version=assignment.r0_version,
            active_rubric=assignment.r0_version,
            fairness_note=(
                "calibration was skipped for this run: the class is graded against R₀ "
                f"({assignment.r0_version}) unchanged, no edit exists to apply, and the "
                "ambiguous criteria are marked lower-confidence"
            ),
            skipped=True,
            lower_confidence_criteria=lower_confidence,
            revision_shipped=False,
            notes=("skipped by the assignment: no questions asked, no edit applied "
                   "(CT-CALIB-01: never on the critical path)",),
        )
    if not findings or not answers or catalog is None:
        return CalibrationRunOutcome(
            r0_version=assignment.r0_version,
            active_rubric=assignment.r0_version,
            fairness_note=(
                "nothing to calibrate this run (no findings, no answers, or no catalog "
                "to write through): the class is graded against R₀ "
                f"({assignment.r0_version}) unchanged"
            ),
            skipped=True,
            lower_confidence_criteria=lower_confidence,
            revision_shipped=False,
            notes=("no calibration inputs provided; the run degrades to a skip, never "
                   "to a blocked grade",),
        )
    questions = elicit(findings, environ=environ)
    revised = apply_answers(answers, catalog=catalog)
    if revised is None:
        # Every answer kept the rubric as is: no edit exists, so the run degrades to
        # the skip's outcome (R₀ unchanged) with the questions still on the record.
        return CalibrationRunOutcome(
            r0_version=assignment.r0_version,
            active_rubric=assignment.r0_version,
            fairness_note=(
                "the teacher kept every ambiguous descriptor as is: no edit exists to "
                f"apply, and the class is graded against R₀ ({assignment.r0_version}) "
                "unchanged"
            ),
            skipped=True,
            questions_asked=len(questions),
            revised_version=None,
            lower_confidence_criteria=lower_confidence,
            revision_shipped=False,
            notes=("all answers kept the rubric as is: the conversation is in the "
                   "elicitation history, and no revision landed",),
        )
    return CalibrationRunOutcome(
        r0_version=assignment.r0_version,
        active_rubric=assignment.r0_version,
        fairness_note=(
            "the teacher's answers produced a revision through M-PKG; whether it grades "
            "the next pass is the gates' decision (FR-CALIB-08/-09, #139), so this "
            f"run's grades stay on R₀ ({assignment.r0_version})"
        ),
        skipped=False,
        questions_asked=len(questions),
        revised_version=revised,
        lower_confidence_criteria=lower_confidence,
        revision_shipped=False,
        notes=(
            f"the revision landed as version {revised!r}, one new version per edit, "
            "each recorded in the elicitation history; the gates decide whether it goes "
            "live",
        ),
    )
