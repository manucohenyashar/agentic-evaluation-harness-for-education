"""The fixed vocabulary of M-DET: bands, states, reasons, evaluation modes and the alert knob."""

from __future__ import annotations

import os
from collections.abc import Mapping


# --- vocabulary ------------------------------------------------------------------------------------

BAND_CORRECT = "correct"


BAND_INCORRECT = "incorrect"


#: Marker value written to `criterion_score.band` for a row that was never
#: scored (an unresolved selection). Not a criterion band; no criterion declares
#: it, and the three-way distinction forbids every other value here.
BAND_UNRESOLVED = "unresolved"


STATE_FINAL = "final"


STATE_UNRESOLVED_SELECTION = "unresolved_selection"


ROUTING_AUTO = "auto"


ROUTING_TRIAGE = "triage"


POLICY_ALL_OR_NOTHING = "all_or_nothing"


POLICY_PER_OPTION = "per_option"


PARTIAL_CREDIT_POLICIES = (POLICY_ALL_OR_NOTHING, POLICY_PER_OPTION)


CONTENT_STATES = ("present", "blank", "absent")


SELECTION_STATES = ("resolved", "ambiguous", "multiple_marks")


# Per-situation reasons — the stage-level detail of the result (CLAUDE.md seam
# 4): a score row that just says 'incorrect' hides which §7.8 cell fired, and
# the blank/unresolved distinction is exactly the thing that must stay legible.
REASON_KEY_MATCH = "key_match"


REASON_KEY_MISS = "key_miss"


REASON_BLANK = "blank_legitimate_zero"


REASON_ABSENT_REGION = "absent_region"


REASON_AMBIGUOUS_MARK = "ambiguous_mark"


REASON_MULTIPLE_MARKS = "multiple_marks"


REASON_NO_SELECTION_READ = "no_selection_read"


REASON_SINGLE_SELECT_MULTIPLE = "single_select_multiple_options"


REASON_SELECTION_OUTSIDE_OPTION_SET = "selection_outside_option_set"


#: `CT-DET-13`'s alert threshold as a per-question rate of unresolved marks.
#: The default is a starting point, not a law — a slower scanner or a worse
#: scan batch adjusts it per environment without a code change.
DEFAULT_UNRESOLVED_ALERT_RATE = 0.05


UNRESOLVED_ALERT_RATE_ENV = "HARNESS_DET_UNRESOLVED_ALERT_RATE"


# --- the audit record and the statistical separation (FR-DET-09 / FR-DET-10) -----------------------

EVALUATION_MODE_JUDGED = "judged"


EVALUATION_MODE_DETERMINISTIC = "deterministic"


EVALUATION_MODES = (EVALUATION_MODE_JUDGED, EVALUATION_MODE_DETERMINISTIC)


DECIDED_BY_SYSTEM = "system"


#: `NFR-DET-03` — the statistical-separation filter, defined here EXACTLY ONCE.
#: Every agreement, kappa, alpha and grader-quality figure excludes deterministic
#: results through THIS predicate (`FR-DET-09`, `CT-DET-06`, R53): agreement with
#: an answer key is not agreement between judges, and mixing the two inflates
#: kappa toward whatever share of the assessment is multiple choice. det owns the
#: column (`label.evaluation_mode`); the consumer owns the rest of its admissible-
#: label conjunction (`NFR-STATS-04`'s `label_type = 'blind'`). The qualified form
#: survives a join, because the consumers' queries join.
DETERMINISTIC_EXCLUSION = "label.evaluation_mode <> 'deterministic'"


def unresolved_alert_rate(environ: Mapping[str, str] | None = None) -> float:
    """The unresolved-count alert rate, read from its environment knob at call time.

    `HARNESS_DET_UNRESOLVED_ALERT_RATE` is a fraction of a question's cohort in
    (0, 1]. An unparseable or out-of-range value falls back to the default
    rather than raising: a mis-set knob must not stop grading, but the report
    records which value actually applied so the fallback is visible.
    """
    source = os.environ if environ is None else environ
    raw = source.get(UNRESOLVED_ALERT_RATE_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_UNRESOLVED_ALERT_RATE
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_UNRESOLVED_ALERT_RATE
    if not 0.0 < value <= 1.0:
        return DEFAULT_UNRESOLVED_ALERT_RATE
    return value
