"""Review budgets, sample sizes, ranking weights, and the env-gated calibration knobs."""

from __future__ import annotations

import os
from types import MappingProxyType
from typing import Any, Mapping

from .errors import ReviewError


# --- the four §3.15 configuration knobs (CT-REVIEW-17) ----------------------------------------------
#
# §3.15's Configuration line, transcribed with their declared Assumption values.
# CT-REVIEW-17 makes all four M-STATS's inputs as much as this module's settings,
# so the names are part of the contract — a story cannot rename them without the
# design changing first.

#: Minutes always reserved for the blind sample, subtracted BEFORE any ranking
#: (`FR-REVIEW-02`) — the event order is the contract (`CT-REVIEW-02`).
REVIEW_BLIND_RESERVE_MINUTES = 10


#: Submissions the blind sample draws by default (`FR-REVIEW-12`); the draw
#: itself is #111's ``blind_sample``, range-checked against BLIND_SAMPLE_RANGE.
REVIEW_BLIND_N = 15


#: Complete final grades the whole-grade sample draws by default (`FR-REVIEW-14`;
#: #111's ``whole_grade_sample``, range-checked against WHOLE_GRADE_SAMPLE_RANGE).
REVIEW_WHOLE_GRADE_N = 12


#: The budget `build_queue` assumes when a caller states none. §3.15's
#: Interfaces block declares ``budget_minutes`` required, so nothing reads this
#: today — it is declared because CT-REVIEW-17 asserts its value.
REVIEW_DEFAULT_BUDGET_MINUTES = 30


#: The blind sample's draw range, inclusive at both ends (`FR-REVIEW-12`): a
#: draw outside it is refused, not clamped — a κ over three labels is a number
#: with no business being reported, and a 40-item draw is not what the teacher
#: asked for either. `CT-REVIEW-11` refuses both ends by name.
BLIND_SAMPLE_RANGE = (15, 25)


#: The whole-grade sample's range, inclusive at both ends (`FR-REVIEW-14`),
#: refused the same way.
WHOLE_GRADE_SAMPLE_RANGE = (10, 15)


# --- the calibration constants (Phase 1; FR-REVIEW-16's calibration is Phase 2) ---------------------
#
# §3.15 names the formula's factors and no numbers. These are the Phase 1
# reading, each env-gated at call time (seam 3) so a differently-shaped corpus
# can adjust without a code change, and each injectable through ``config=``
# under its own name.

#: Weight of one unit of panel spread in P(score wrong). Equal weights: the
#: design names four inputs and no weighting.
REVIEW_PANEL_SPREAD_WEIGHT: float = 1.0


#: Weight of one adverse integrity signal, after the cap below.
REVIEW_INTEGRITY_SIGNAL_WEIGHT: float = 1.0


#: Weight of transcription overlap in P(score wrong).
REVIEW_TRANSCRIPTION_OVERLAP_WEIGHT: float = 1.0


#: Weight of the criterion's historical override rate in P(score wrong).
REVIEW_OVERRIDE_RATE_WEIGHT: float = 1.0


#: The count of adverse integrity signals read as "the panel is shouting";
#: the signal is normalized by this cap, not by trust.
REVIEW_INTEGRITY_SIGNAL_CAP: int = 3


#: Boundary proximity ``1/(1 + delta/half_width)`` halves here: a criterion
#: whose band sits this far from a grade boundary is half as boundary-urgent.
REVIEW_BOUNDARY_HALF_WIDTH: float = 10.0


#: P contribution of an override history nobody has measured (`CT-STATS-09`:
#: no data is not a zero; the unmeasured criterion is the risky one).
REVIEW_OVERRIDE_RATE_NO_DATA: float = 0.5


#: The estimate used when a row carries no usable ``est_seconds`` AND the criterion's
#: scoring model is unknown. A KNOWN model takes the two figures below instead.
REVIEW_DEFAULT_EST_SECONDS: float = 60.0


#: `FR-REVIEW-18`'s per-model review estimates, the design's stated `Assumption:` —
#: an atomic criterion is one band judgement, a holistic one re-reads the response.
#: Both are knobs (seam 3) precisely because they are an assumption: the first
#: measurement against a real teacher replaces the number, not the code.
REVIEW_EST_SECONDS_ATOMIC: float = 45.0


REVIEW_EST_SECONDS_HOLISTIC: float = 90.0


#: The estimate map, DECLARED — `CT-AGG-09` bans a run-time special case on the scoring
#: model, and `aeh.orch`'s `SCORING_MODEL_BASE_DEPTH` is the sanctioned precedent for the
#: legitimate other half: a difference the DESIGN declares, expressed as a table the code
#: looks up rather than as a branch the code takes. A model absent from this map takes the
#: model-free default; adding a model is a data change here, not a new branch elsewhere.
#: Each entry names the knob that overrides it, so the seam-3 override stays declarative too.
SCORING_MODEL_EST_SECONDS: "Mapping[str, tuple[str, float]]" = MappingProxyType({
    "atomic": ("EST_SECONDS_ATOMIC", REVIEW_EST_SECONDS_ATOMIC),
    "holistic": ("EST_SECONDS_HOLISTIC", REVIEW_EST_SECONDS_HOLISTIC),
})


#: The judgement count below which an override rate is NOT reported (`FR-REVIEW-18`).
#: Four teachers who overrode once are not a 25% override rate; they are four
#: teachers. Below this the rate reads `None` and `_override_rate_of` applies
#: `CT-STATS-09`'s no-data figure, which is deliberately not zero.
REVIEW_OVERRIDE_MIN_N: int = 5


_WEIGHT_LOW, _WEIGHT_HIGH = 0.0, 10.0


#: The views that display a band and can therefore carry a review action
#: (`FR-REVIEW-15`; the teacher routes of the design's console table): the
#: queue itself (S9), the run rollup, the student view (S13 — the case
#: `TC-REVIEW-15` names), and the submission detail. The blind flow and the
#: whole-grade sample are deliberately absent: the blind flow must not display
#: the system's band at all (`FR-REVIEW-11`), and the sample displays grades,
#: not band decisions. `edit_views()` is a method over this constant so a view
#: added later joins `CT-REVIEW-12`'s sweep on the day it appears.
_EDIT_VIEWS: tuple[str, ...] = (
    "review_queue",
    "rollup",
    "student",
    "submission_detail",
)


#: The default band scale the no-package-context points route reads. The
#: *mapping* is `aeh.pkg.points_for_band`'s alone (`NFR-AGG-02`); this constant
#: is only the band *data* the derivation needs when a score row carries no
#: package linkage (none of the store rows do — #108's ranking interpretation
#: records the same absence). The scale is the plan's 0–100 spread over five
#: bands; a criterion's real table supersedes it the moment a catalog is
#: attached.
REVIEW_DEFAULT_BANDS: tuple[dict[str, Any], ...] = (
    {"band": "B1", "points": 0.0},
    {"band": "B2", "points": 25.0},
    {"band": "B3", "points": 50.0},
    {"band": "B4", "points": 75.0},
    {"band": "B5", "points": 100.0},
)


#: The counter names `CT-REVIEW-18`'s surface names. Every one is a key of
#: ``observability_counters``'s result for any run — an unmeasured value is
#: ``None``, never absent, so a missing name is a defect and not a quiet gap.
_OBSERVABILITY_COUNTERS: tuple[str, ...] = (
    "review_minutes_used",
    "review_items_shown",
    "review_items_flagged",
    "override_rate_by_criterion",
    "group_action_usage_share",
    "blind_completion_rate",
    "mean_review_seconds",
    "mean_est_seconds",
)


#: The budget-exhaustion alert and the streak length that fires it
#: (`CT-REVIEW-18`): a criterion that exhausted its budget on two
#: administrations in a row is a pattern, not a coincidence.
REVIEW_BUDGET_EXHAUSTION_ALERT = "criterion_exhausts_budget_across_administrations"


_ALERT_MIN_CONSECUTIVE_ADMINISTRATIONS = 2


def _calibration_knobs() -> dict[str, float]:
    """The ranking calibration knobs for one build, read from the environment on each call. An
    invalid override is refused rather than ignored, so a typo cannot silently fall back to the
    production value."""
    return {
        "panel_spread_weight": _env_float(
            _knob_name("PANEL_SPREAD_WEIGHT"), REVIEW_PANEL_SPREAD_WEIGHT,
            low=_WEIGHT_LOW, high=_WEIGHT_HIGH,
        ),
        "integrity_signal_weight": _env_float(
            _knob_name("INTEGRITY_SIGNAL_WEIGHT"), REVIEW_INTEGRITY_SIGNAL_WEIGHT,
            low=_WEIGHT_LOW, high=_WEIGHT_HIGH,
        ),
        "transcription_overlap_weight": _env_float(
            _knob_name("TRANSCRIPTION_OVERLAP_WEIGHT"), REVIEW_TRANSCRIPTION_OVERLAP_WEIGHT,
            low=_WEIGHT_LOW, high=_WEIGHT_HIGH,
        ),
        "override_rate_weight": _env_float(
            _knob_name("OVERRIDE_RATE_WEIGHT"), REVIEW_OVERRIDE_RATE_WEIGHT,
            low=_WEIGHT_LOW, high=_WEIGHT_HIGH,
        ),
        "integrity_signal_cap": _env_float(
            _knob_name("INTEGRITY_SIGNAL_CAP"), float(REVIEW_INTEGRITY_SIGNAL_CAP),
            low=1.0, high=100.0,
        ),
        "boundary_half_width": _env_float(
            _knob_name("BOUNDARY_HALF_WIDTH"), REVIEW_BOUNDARY_HALF_WIDTH,
            low=1e-06, high=1e06,
        ),
        "override_rate_no_data": _env_float(
            _knob_name("OVERRIDE_RATE_NO_DATA"), REVIEW_OVERRIDE_RATE_NO_DATA,
            low=0.0, high=1.0,
        ),
        "default_est_seconds": _env_float(
            _knob_name("DEFAULT_EST_SECONDS"), REVIEW_DEFAULT_EST_SECONDS,
            low=1.0, high=3600.0,
        ),
        "est_seconds_atomic": _env_float(
            _knob_name("EST_SECONDS_ATOMIC"), REVIEW_EST_SECONDS_ATOMIC,
            low=1.0, high=3600.0,
        ),
        "est_seconds_holistic": _env_float(
            _knob_name("EST_SECONDS_HOLISTIC"), REVIEW_EST_SECONDS_HOLISTIC,
            low=1.0, high=3600.0,
        ),
        "override_min_n": _env_float(
            _knob_name("OVERRIDE_MIN_N"), float(REVIEW_OVERRIDE_MIN_N),
            low=1.0, high=1e06,
        ),
    }


#: The knob prefix this module reads, and the one it still answers to. The project's
#: knobs are being renamed `AEH_*` -> `HARNESS_*`; a deployment that already sets the old
#: name keeps working for one release rather than silently reverting to the production
#: default, which is the phantom-bug shape seam 3 exists to prevent (`#368`).
_KNOB_PREFIX = "HARNESS_REVIEW_"


_LEGACY_KNOB_PREFIX = "AEH_REVIEW_"


def _knob_name(suffix: str) -> str:
    """Which environment variable a knob is read from: the new name when set, else the old name
    when that is set, else the new name (so a refusal names the new spelling)."""
    new = _KNOB_PREFIX + suffix
    if os.environ.get(new, "").strip():
        return new
    legacy = _LEGACY_KNOB_PREFIX + suffix
    if os.environ.get(legacy, "").strip():
        return legacy
    return new


def _env_float(name: str, default: float, *, low: float, high: float) -> float:
    """Read one float knob from the environment at call time.

    Absent or blank takes the default; an unparseable value or one outside
    ``[low, high]`` raises rather than falling back — a typo'd override silently
    taking the production value is the phantom-bug shape the seam exists to
    prevent, and a clamped misconfiguration would BE the bug.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ReviewError(f"{name}={raw!r} is not a number") from exc
    if value < low or value > high:
        raise ReviewError(f"{name}={raw!r} is outside [{low}, {high}]")
    return value


def _resolve_knob(explicit: Any, config: Any, name: str, default: Any) -> Any:
    """One review setting: the keyword argument if given, else the `config` attribute, else the
    module constant."""
    if explicit is not None:
        return explicit
    if config is not None:
        attr = getattr(config, name, None)
        if attr is not None:
            return attr
    return default
