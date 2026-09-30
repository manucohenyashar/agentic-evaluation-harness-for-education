"""The knob sweep: two contrasting values per knob, and what a caller can observe under each."""

from __future__ import annotations

from typing import Any

from .errors import CalibrationError
from .elicitation import CALIB_MAX_QUESTIONS, CALIB_MAX_QUESTIONS_ENV, elicit
from .off_panel import CALIB_OFF_PANEL_MODEL
from .rosters import CALIB_CLASS_SIZE_CAP, CALIB_CLASS_SIZE_CAP_ENV
from .gates import (
    back_translate,
    CALIB_NONINFERIORITY_THRESHOLD,
    CALIB_NONINFERIORITY_THRESHOLD_ENV,
    _clear_institutional_threshold,
    non_inferiority,
)
from .fixtures import findings_fixture
from .scenarios import cohort_with_band_shift, _off_panel_model_ref


# --- the knobs, and their externally visible effects (CT-CALIB-13, seam 3) --------------------------
#
# `KNOBS` is the module's full knob surface: the three the design declares plus the class-size
# cap, which is env-only. The declared *values* live on the constants above; the gate's refusal
# to default the threshold is what makes 0.10 an example rather than a default.

KNOBS: dict[str, Any] = {
    "CALIB_MAX_QUESTIONS": CALIB_MAX_QUESTIONS,
    "CALIB_NONINFERIORITY_THRESHOLD": CALIB_NONINFERIORITY_THRESHOLD,
    "CALIB_OFF_PANEL_MODEL": CALIB_OFF_PANEL_MODEL,
    "CALIB_CLASS_SIZE_CAP": CALIB_CLASS_SIZE_CAP,
}


def contrasting_values_for(knob: str) -> tuple[Any, Any]:
    """Two values a run can tell apart for ``knob`` (`CT-CALIB-13`'s sweep moves the
    behaviour between them). Chosen per knob for where they land on the behaviour, not
    for contrast's own sake."""
    if knob == "CALIB_MAX_QUESTIONS":
        return (1, 3)
    if knob == "CALIB_NONINFERIORITY_THRESHOLD":
        # A fixed probe cohort shifts 0.20 of the class, between the two values: the
        # applied threshold — not the roster — decides the outcome.
        return (0.05, 0.50)
    if knob == "CALIB_OFF_PANEL_MODEL":
        return (_off_panel_model_ref(constructs=True), _off_panel_model_ref(constructs=False))
    if knob == "CALIB_CLASS_SIZE_CAP":
        return (None, 5)
    raise CalibrationError(
        f"unknown knob {knob!r}; the knobs the module reads are {sorted(KNOBS)}"
    )


#: Cached probe cohorts the knob observations run against, keyed by (fraction, class size).
_PROBE_COHORTS: dict[tuple[float, int], str] = {}


def _probe_cohort_id(fraction: float, class_size: int) -> str:
    key = (float(fraction), class_size)
    if key not in _PROBE_COHORTS:
        _PROBE_COHORTS[key] = cohort_with_band_shift(fraction=fraction, class_size=class_size)
    return _PROBE_COHORTS[key]


def observable_behaviour_with(knob: str, value: Any) -> Any:
    """What a caller outside the module can observe when ``knob`` is set to ``value``
    (`CT-CALIB-13`).

    The knob is **moved and the difference observed**, not reported on: the question
    count elicitation asks, the gate's outcome and applied threshold, the
    back-translation verdict, the gate's refusal of an over-cap class. Values are
    injected through the call-time ``environ`` seam, or for the off-panel knob through
    the checker argument itself (a model reference does not ride an env string) — never
    ``os.environ``, so an
    observation cannot leak into a neighbouring test; the threshold observation clears
    any standing declaration first, because a declaration outranks the env and a
    leftover would make the injected value unread."""
    if knob == "CALIB_MAX_QUESTIONS":
        questions = elicit(
            findings_fixture(count=20), environ={CALIB_MAX_QUESTIONS_ENV: str(value)}
        )
        return ("questions_asked", len(questions))
    if knob == "CALIB_NONINFERIORITY_THRESHOLD":
        _clear_institutional_threshold()
        result = non_inferiority(
            r0="pkg-v1",
            r1="pkg-v2",
            cohort_id=_probe_cohort_id(0.20, 100),
            threshold=None,
            environ={CALIB_NONINFERIORITY_THRESHOLD_ENV: str(value)},
        )
        return (result.outcome, result.threshold_used)
    if knob == "CALIB_OFF_PANEL_MODEL":
        result = back_translate(r0="pkg-v1", r1="pkg-v2", off_panel=value)
        return (result.outcome, result.divergent_response_found)
    if knob == "CALIB_CLASS_SIZE_CAP":
        environ = {} if value is None else {CALIB_CLASS_SIZE_CAP_ENV: str(value)}
        try:
            result = non_inferiority(
                r0="pkg-v1",
                r1="pkg-v2",
                cohort_id=_probe_cohort_id(0.05, 10),
                threshold=0.10,
                environ=environ,
            )
        except CalibrationError:
            return ("refused",)
        return ("ran", result.outcome)
    raise CalibrationError(
        f"unknown knob {knob!r}; the knobs the module reads are {sorted(KNOBS)}"
    )
