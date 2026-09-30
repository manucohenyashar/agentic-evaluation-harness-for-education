"""The metrics and alerts M-CALIB emits, and the simulator for its eight failure modes."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import _ambiguity_alert_after, AMBIGUITY_ALERT_TEXT, _FIXTURE_CRITERION_ID
from .errors import (
    CalibrationError,
    InsufficientPopulation,
    OffPanelUnavailable,
    TriageCategoryRequired,
)
from .discovery import Disagreement, triage
from .driver import assignment, CalibrationRunOutcome, _DEFAULT_R0_VERSION, run_for_assignment
from .rosters import _CLASS_ROSTERS, _ClassRoster
from .gates import back_translate, CALIBRATION_SET, non_inferiority
from .fixtures import findings_fixture
from .scenarios import cohort_with_band_shift, model_ref_off_panel, _off_panel_model_ref


@dataclass(frozen=True)
class CalibrationMetric:
    """One metric the module emits (seam 4, `CT-CALIB-14`): its name, its label
    dimensions, and whether it is a distribution.

    Dimensionality is the point: findings carry a ``triage_category`` label because the
    three categories mean different remedies; the class shift is a distribution because
    a mean hides whether two students moved a band or forty moved a little."""

    name: str
    labels: tuple[str, ...] = ()
    is_distribution: bool = False
    description: str = ""


def metrics_for_test() -> dict[str, CalibrationMetric]:
    """The metric surface the module's structured records feed (`CT-CALIB-14`).

    The families, names and dimensionality are what the harness scrapes from the
    module's structured records — `DiscoveryReport` (findings by triage category),
    `CalibrationRunOutcome` (questions asked versus answered — the gap is the signal),
    `GateResult` (per-gate outcomes, and the class shift as a distribution). The seam
    pins the surface the contract asserts; the samples flow through the records
    themselves."""
    return {
        "findings": CalibrationMetric(
            "calib_findings_total",
            labels=("triage_category",),
            description="discovered ambiguities, by triage category — a single total "
            "cannot say which kind, and the three kinds need different responses "
            "(CT-CALIB-14)",
        ),
        "questions_asked": CalibrationMetric(
            "calib_questions_asked_total",
            description="elicitation questions asked (CT-CALIB-14: asked versus answered)",
        ),
        "questions_answered": CalibrationMetric(
            "calib_questions_answered_total",
            description="elicitation questions the teacher answered; the gap is the signal",
        ),
        "gate_outcome": CalibrationMetric(
            "calib_gate_outcome_total",
            labels=("gate", "outcome"),
            description="outcomes of the two guardrail gates, per gate (CT-CALIB-14)",
        ),
        "class_shift": CalibrationMetric(
            "calib_class_shift_fractions",
            is_distribution=True,
            description="the full class's shift fractions under dual scoring, as a "
            "distribution — a mean hides whether two students moved a band or forty "
            "moved a little (CT-CALIB-14)",
        ),
    }


@dataclass(frozen=True)
class CalibrationAlert:
    """One alert the module raises (seam 4): its scope, its wording, and the finding
    count that fired it."""

    scope: str
    message: str
    finding_count: int


def alerts_for_test(*, finding_count: int = 0) -> tuple[CalibrationAlert, ...]:
    """The alert surface for a discovery that surfaced ``finding_count`` ambiguities
    (`CT-CALIB-14`).

    More than a handful — the same call-time threshold discovery itself alerts under
    (`_ambiguity_alert_after`) — alerts **once, on the aggregate**: the rubric needs a
    conversation, not twenty questions to answer. The per-finding form buries the signal
    in the workload it describes, which is the shape the clause forbids."""
    if finding_count <= _ambiguity_alert_after():
        return ()
    return (
        CalibrationAlert(
            scope="aggregate",
            message=AMBIGUITY_ALERT_TEXT,
            finding_count=finding_count,
        ),
    )


def simulate_failure(failure_mode: str, *, r0: str = _DEFAULT_R0_VERSION) -> CalibrationRunOutcome:
    """Drive one of `CT-CALIB-02`'s eight failure modes through the module's real paths
    and return the terminal outcome every one of them resolves to (`FR-CALIB-10`).

    The modes and the real path each drives: ``teacher_declines`` — the run's
    no-inputs branch (questions were elicited, the teacher answered nothing);
    ``teacher_abandons_midflow`` — answers arrived with no catalog to apply them
    through; ``gate_fails`` — the gate refuses a population that cannot carry its
    verdict (the calibration set); ``dual_scoring_rejects`` — the comparison rejects
    the revision (a class shifting well past any threshold); ``back_translation_diverges``
    — the off-panel model constructs a divergent response;
    ``triage_unavailable`` — an uncategorized disagreement reaches the triage boundary;
    ``off_panel_model_unavailable`` — the off-panel build has no bound transport;
    ``module_crashes`` — the gate is handed a corrupted roster and the module raises.

    The seam exists because the terminal state is a property of how callers resolve
    these failures, and the contract pins it (`FR-CALIB-10`): R₀ unchanged, the
    ambiguous criteria lower-confidence, no revision shipped, nothing shipped with a
    warning. Errors are caught on purpose — a crash is one of the enumerated modes, and
    the claim under test is that it too ends at R₀."""
    lower_confidence = tuple(f.criterion_id for f in findings_fixture(count=1))

    def _terminal(note: str, *details: str) -> CalibrationRunOutcome:
        return CalibrationRunOutcome(
            r0_version=r0,
            active_rubric=r0,
            fairness_note=note,
            skipped=True,
            revised_version=None,
            lower_confidence_criteria=lower_confidence,
            revision_shipped=False,
            notes=details,
        )

    if failure_mode == "teacher_declines":
        return run_for_assignment(
            assignment(
                r0_version=r0,
                ambiguous_criteria=lower_confidence,
            ),
            findings=findings_fixture(),
            answers=None,
        )
    if failure_mode == "teacher_abandons_midflow":
        return run_for_assignment(
            assignment(
                r0_version=r0,
                ambiguous_criteria=lower_confidence,
            ),
            findings=findings_fixture(),
            answers={"q1": "broaden"},
            catalog=None,
        )
    if failure_mode == "gate_fails":
        try:
            non_inferiority(
                r0=r0, r1="pkg-v2", cohort_id=CALIBRATION_SET, threshold=0.10
            )
        except InsufficientPopulation as error:
            return _terminal(
                _refusal_note(failure_mode, r0, "the gate refused the calibration set"),
                str(error),
            )
        raise CalibrationError(f"the gate_fails path did not refuse: {failure_mode}")
    if failure_mode == "dual_scoring_rejects":
        cohort_id = cohort_with_band_shift(fraction=0.40, class_size=100)
        result = non_inferiority(r0=r0, r1="pkg-v2", cohort_id=cohort_id, threshold=0.10)
        if result.outcome != "reject":
            raise CalibrationError(
                f"the dual_scoring_rejects path did not reject: {result.outcome!r}"
            )
        return _terminal(
            _refusal_note(failure_mode, r0, "dual scoring shifted more of the class than "
                                          "the declared threshold allows"),
            *result.notes,
        )
    if failure_mode == "back_translation_diverges":
        result = back_translate(r0=r0, r1="pkg-v2", off_panel=model_ref_off_panel())
        if result.outcome != "reject":
            raise CalibrationError(
                f"the back_translation_diverges path did not reject: {result.outcome!r}"
            )
        return _terminal(
            _refusal_note(failure_mode, r0,
                          "an off-panel model constructed a response on which R0 and R1 "
                          "differ — evidence the construct changed (FR-CALIB-09)"),
            *result.notes,
        )
    if failure_mode == "triage_unavailable":
        try:
            triage(Disagreement(criterion_id=_FIXTURE_CRITERION_ID))
        except TriageCategoryRequired as error:
            return _terminal(
                _refusal_note(failure_mode, r0,
                              "a disagreement without its required triage category cannot "
                              "reach the editable path"),
                str(error),
            )
        raise CalibrationError(f"the triage_unavailable path did not refuse: {failure_mode}")
    if failure_mode == "off_panel_model_unavailable":
        try:
            back_translate(r0=r0, r1="pkg-v2", off_panel=_off_panel_model_ref(constructs=None))
        except OffPanelUnavailable as error:
            return _terminal(
                _refusal_note(failure_mode, r0,
                              "the off-panel build has no bound construction transport, so "
                              "the gate cannot run and the revision does not ship"),
                str(error),
            )
        raise CalibrationError(f"the off_panel_model_unavailable path did not refuse: {failure_mode}")
    if failure_mode == "module_crashes":
        cohort_id = cohort_with_band_shift(fraction=0.05, class_size=10)
        _CLASS_ROSTERS[cohort_id] = _ClassRoster(
            cohort_id=cohort_id,
            class_size=10,
            criteria=(_FIXTURE_CRITERION_ID,),
            scores=((("corrupted",),),),
            is_calibration_set=False,
        )
        try:
            non_inferiority(r0=r0, r1="pkg-v2", cohort_id=cohort_id, threshold=0.10)
        except Exception as error:  # noqa: BLE001 — the mode IS the crash; it ends at R0 too
            return _terminal(
                _refusal_note(failure_mode, r0,
                              "the module raised on a corrupted roster, and a crash ends "
                              "at R0 like every other failure mode"),
                f"{type(error).__name__}: {error}",
            )
        raise CalibrationError(f"the module_crashes path did not crash: {failure_mode}")
    raise CalibrationError(
        f"unknown failure mode {failure_mode!r}: CT-CALIB-02 enumerates eight"
    )


def _refusal_note(failure_mode: str, r0: str, reason: str) -> str:
    """The terminal-state fairness note every failure mode resolves to (`FR-CALIB-10`)."""
    return (
        f"{failure_mode}: {reason}, so the run ended at R0 ({r0}) — the class is graded "
        "with the rubric as given and the ambiguous criteria are marked lower-confidence "
        "(CT-CALIB-02, FR-CALIB-10)"
    )
