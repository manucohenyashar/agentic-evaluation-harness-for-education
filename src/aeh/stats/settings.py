"""Thresholds, tolerances, evidence weights and alert names, each knob read at call time."""

from __future__ import annotations

import math
import os
from typing import Mapping


#: A criterion's scoring-model values (`FR-STATS-17`). ``atomic`` and
#: ``atomic_with_gate`` are reported together and ``holistic`` separately —
#: the clause's *"reported separately and no function merges them"*.
SCORING_MODELS: tuple[str, ...] = ("atomic", "atomic_with_gate", "holistic")


#: The display-qualifier boundary from §3.16's Configuration block: below this
#: n a figure renders with an explicit "too few to draw conclusions from"
#: qualifier. It is **not** a quality threshold — a figure below it says the
#: claim is wide, not that the system failed (`CT-STATS-20`'s finding keeps
#: the two apart, and `TC-STATS-C20` pins the declared default).
STATS_MIN_N_FOR_HEADLINE = 30


#: The three declared absence reasons (`CT-STATS-03`). Declared here as data
#: so ``NoValidationData``'s constructor validates against the transcription
#: rather than a convention.
# `_NO_DATA_REASONS` is `aeh.pkg.NO_DATA_REASONS` (imported below): one absence type (#512).

#: The normal distribution's two-sided 95% critical value. A named constant
#: rather than an inline 1.96 so the interval's provenance is one line.
_INTERVAL_Z_95 = 1.96


#: The worst-case band variance when no statistic is computable: the binomial
#'s maximum variance at p = 0.5, the widest claim an ``n`` can honestly make.
_WORST_CASE_VARIANCE = 0.25


# --- the #117 constants (FR-STATS-06..09, CT-STATS-10/11/12/18/19) ---------------------------------
#
# The declared values are the defaults; the three detector sensitivities are
# env-gated knobs read at call time (seam 3) — an installation adjusts without
# a code change. ``STATS_SUBGROUP_ANALYSIS_ENABLED`` is the Configuration
# block's own knob and is *not* env-defaulted here: the module constant is the
# declared default (``TC-STATS-C18`` pins it), and the environment override is
# read at call time by the one function that implements the gate.

#: The two populations `FR-STATS-08` compares. The names are the comparison
#: protocol's; the values a label actually carries in its ``routing`` column
#: are the queue's admission routing (`CT-AGG-06`'s closed set), copied onto
#: the label for traceability (`CT-REVIEW-07`) — so ``routing_policy_validity``
#: reads the column through ``ROUTING_POLICY_ARM_SOURCES``, which maps each
#: arm onto the routing values that name it.
ROUTING_POLICY_ARMS: tuple[str, ...] = ("escalated_and_reviewed", "auto_accepted")


#: Which ``routing`` values put a label in which arm. The label's ``routing``
#: column carries the queue's admission routing — `CT-AGG-06`'s closed set
#: ``{auto, queued, provisional, reviewed, triage}`` — recorded on the label
#: for traceability (`CT-REVIEW-07`), and the two arms of `FR-STATS-08`'s
#: comparison are read off it: ``reviewed`` — the one value `aeh.agg` never
#: assigns, because it names a review that has happened — is the
#: escalated-and-reviewed arm; ``auto`` — the confidence met the scoring
#: model's threshold — is the auto-accepted arm. Each arm also accepts its own
#: protocol name, which is what an in-memory construction of the comparison
#: uses. The other three values join **neither** arm on purpose: ``queued`` and
#: ``triage`` are judgments still awaiting review — escalated, but the review
#: the arm names has not happened — and ``provisional`` names a single-judge
#: band or a tripped breaker that was never auto-accepted, so it belongs to no
#: population the policy created. Rows predating the column read ``None`` and
#: join neither arm rather than being guessed into one.
ROUTING_POLICY_ARM_SOURCES: Mapping[str, tuple[str, ...]] = {
    "escalated_and_reviewed": ("escalated_and_reviewed", "reviewed"),
    "auto_accepted": ("auto_accepted", "auto"),
}


#: The verdict vocabulary `CT-STATS-11` fixes. ``failing`` is what similar
#: rates in both arms mean — the policy escalates the wrong judgments, which is
#: a finding about `M-AGG`'s declared constants (R22), not an absence of one;
#: ``uninformative`` is the reading the clause forbids and the module never
#: returns it. ``discriminating`` is the healthy direction (the escalated arm's
#: error rate against blind teachers exceeds the auto-accepted one's by at
#: least the tolerance — the HLD's 8%-versus-1% gap). ``no_data`` is the
#: insufficient-data value (`CT-STATS-16`), not a verdict.
ROUTING_POLICY_FAILING_VERDICT = "failing"


ROUTING_POLICY_DISCRIMINATING_VERDICT = "discriminating"


ROUTING_POLICY_NO_DATA_VERDICT = "no_data"


#: The tolerance below which the two arms' error rates count as "similar" —
#: env-gated at call time under this same name, production default declared
#: here. A detector sensitivity, not a quality threshold: it decides when the
#: comparison cannot tell the arms apart, never whether the system is good.
STATS_ROUTING_POLICY_TOLERANCE = 0.05


#: The ``|r|`` at which a surface feature becomes a surface-proxy flag —
#: env-gated at call time under this same name. A detector sensitivity, not a
#: quality threshold (`CT-STATS-20`'s non-promise is about verdicts on
#: agreement figures; this decides when the alert `CT-STATS-19` declares fires).
STATS_SURFACE_PROXY_CORRELATION_THRESHOLD = 0.7


#: The total-variation distance at which a criterion's sample distribution
#: counts as drifted from the baseline — env-gated at call time. The check is
#: advisory regardless (`CT-STATS-12`); this only decides which distances the
#: report names, and no threshold makes the check binding.
STATS_DRIFT_TOLERANCE = 0.1


#: `NFR-STATS-05`'s gate, as the Configuration block declares it. **False is
#: the contract**: a subgroup analysis running by default is a regulatory
#: exposure nobody chose. The module constant is the declared default; the
#: environment knob of the same name may enable it where an installation has
#: declared the analysis locally lawful — a decision this module cannot make —
#: and even then the breakdown runs only on an explicit ``subgroup=`` request.
STATS_SUBGROUP_ANALYSIS_ENABLED = False


#: `FR-STATS-09`'s declared sample window, inclusive at both ends. A sample
#: below the low end is the absence value (`TC-STATS-C12` asserts both
#: boundaries); above the high end the check takes an even spread of the
#: declared size and reports how many it used.
DRIFT_SAMPLE_RANGE: tuple[int, int] = (20, 30)


#: `FR-STATS-07`'s surface features that *ought to be irrelevant* to a score.
#: ``subgroup`` is deliberately absent here — it is not a regression input on
#: this surface but the gated analysis behind ``surface_proxies(subgroup=)``
#: (`NFR-STATS-05`); ``handwriting_legibility_band`` is reported as captured
#: only where the declared correlations carry it.
SURFACE_FEATURES: tuple[str, ...] = (
    "response_length_tokens",
    "vocabulary_complexity",
    "ocr_quality_score",
    "handwriting_legibility_band",
    "formatting_regularity",
)


#: The alert name `CT-STATS-19` declares contract — the only detector for a
#: criterion with an excellent κ and no validity. A length or OCR correlation
#: means that criterion is measuring something other than what it claims,
#: **whatever its agreement statistic says**.
SURFACE_PROXY_ALERT = "surface_proxy_flag_on_criterion"


#: The stated interpretation `CT-STATS-11` fixes, carried in the report itself
#: (the same discipline as `CT-STATS-10`'s limitation): the verdict vocabulary
#: travels with the reading that justifies it.
_ROUTING_POLICY_INTERPRETATION = (
    "similar error rates in both arms are failing, not uninformative: a policy "
    "whose escalated arm shows no more teacher disagreement than its "
    "auto-accepted arm is escalating the wrong judgments, which is a finding "
    "about the escalation constants, not an absence of one (CT-STATS-11, HLD R22)"
)


#: The advisory statement the drift report carries (`CT-STATS-12`). It is part
#: of the value, like the compression check's limitation: the field answers
#: the reader's next question — what would make this binding — instead of
#: leaving the answer in a docstring.
_DRIFT_ADVISORY_STATEMENT = (
    "advisory, never a gate: no distance, severity or sample size makes this "
    "check binding. A binding threshold would stop a school's grading on an "
    "advisory comparison of at most 30 submissions against a baseline (HLD "
    "R11, CT-STATS-12), and NFR-SYS-08 declares no threshold here — so there "
    "is no binding threshold, by design, and the consumer decides what to do "
    "with the distances; the check only reports them."
)


# --- the #118 constants (FR-STATS-10..14, CT-STATS-05/06/19, NFR-STATS-03) --------------------------
#
# The validation record's constants. ``NO_NEW_VALIDATION_EVIDENCE`` is the
# first-class absence value `CT-STATS-05` declares — a message, not a zero and
# not a stale figure, so an administration that collected no blind labels is
# reported as exactly that. ``BLIND_SAMPLE_SKIPPED_ALERT`` is the alert name
# `CT-STATS-19` declares contract for the record. The evidence weights anchor
# `FR-STATS-14`'s declared ordering: an override is informative, an acceptance
# is weak, and the blind score is the authoritative one — weights for the
# operational signal only, never for the agreement figure, which is what keeps
# the weighting from blurring into a validity claim.

#: The message `CT-STATS-05` fixes: what an administration that collected no
#: blind labels reports, as a first-class value (`FR-STATS-11`). The agreement
#: figures are not advanced by such an administration — the record carries this
#: message beside the counters it did move, and the earlier figure stays where
#: it was (RISK-08: the silent carry-forward is the failure this names).
NO_NEW_VALIDATION_EVIDENCE: str = (
    "no new validation evidence for this administration"
)


#: The alert name `CT-STATS-19` declares contract for the validation record:
#: consecutive administrations whose blind sample was skipped. The detector's
#: threshold — how many consecutive skips provoke it — is the env-gated knob
#: ``STATS_BLIND_SKIP_ALERT_AFTER``, default 2, read at call time by the one
#: function that implements the alert.
BLIND_SAMPLE_SKIPPED_ALERT: str = (
    "blind_sample_skipped_consecutive_administrations"
)


#: `FR-STATS-14`'s evidence ordering, as data: the keys a label's origin maps
#: onto, weakest first. ``override`` — a teacher who overrode the panel — is
#: informative; ``acceptance`` — a teacher who accepted the panel's proposal —
#: is weak evidence, because the panel proposed what the same source confirmed;
#: ``blind`` — the blind score — is the authoritative one. The weights are the
#: operational signal's and only its: the agreement figure is computed
#: unweighted, always, which is the clause's *"never blurs into a validity
#: claim"* held in code.
OPERATIONAL_EVIDENCE_ORDER: tuple[str, ...] = ("acceptance", "override", "blind")


#: The declared default weights, keyed by ``OPERATIONAL_EVIDENCE_ORDER``. A
#: detector calibration rather than a quality threshold: they decide how loudly
#: an operational signal speaks, never whether the system is good. Deliberately
#: **not** an environment knob — the ordering is a contract value (the clause
#: names all three kinds), and re-weighting validation evidence is a policy
#: decision this module will not make configurable.
OPERATIONAL_EVIDENCE_WEIGHTS: Mapping[str, float] = {
    "acceptance": 0.25,
    "override": 0.75,
    "blind": 1.0,
}


#: The label ``origin`` values the collection paths write (`CT-REVIEW-07`'s
#: closed set) mapped onto the evidence order above. ``accept`` — the review
#: accepted the panel's proposal — is the ``acceptance`` spelling; ``override``
#: carries its own name; the blind sample's ``blind_sample`` is the ``blind``
#: one. An origin outside the mapping falls back on the label's type — a blind
#: label reads as ``blind`` evidence, anything else as ``acceptance`` — so the
#: mapping is total rather than guessing an arm for an unrecorded origin.
_ORIGIN_TO_EVIDENCE: Mapping[str, str] = {
    "accept": "acceptance",
    "acceptance": "acceptance",
    "override": "override",
    "blind_sample": "blind",
    "blind": "blind",
}


#: How many consecutive administrations may skip their blind sample before
#: ``BLIND_SAMPLE_SKIPPED_ALERT`` fires. Env-gated at call time under this same
#: name (seam 3): a slower-cadence installation adjusts without a code change.
#: A detector threshold, not a quality one — it decides when the record says
#: the administration ran blind, never whether the system is good.
STATS_BLIND_SKIP_ALERT_AFTER: int = 2


def _env_flag(name: str, default: bool) -> bool:
    """Read one boolean knob from the environment at call time.

    The declared production value is the default; the knob exists so an
    installation adjusts without a code change. An unset or empty variable
    falls through to the default, a recognised boolean spelling is honoured,
    and anything else is refused with the knob's name — a mis-spelled
    ``STATS_SUBGROUP_ANALYSIS_ENABLED=tru`` must fail loudly, not silently run
    the gate closed.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    lowered = raw.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ValueError(
        f"environment knob {name}={raw!r} is not a boolean; use 1/true/yes/on "
        "or 0/false/no/off."
    )


def _env_float(name: str, default: float) -> float:
    """Read one numeric knob from the environment at call time.

    Non-finite values are refused along with unparseable ones: a threshold of
    ``nan`` or ``inf`` would silently disable the detector it calibrates — a
    mis-spelled value must fail loudly, the same refusal ``_env_flag`` makes.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(
            f"environment knob {name}={raw!r} is not a number."
        ) from error
    if not math.isfinite(value):
        raise ValueError(
            f"environment knob {name}={raw!r} is not a finite number; a "
            "non-finite sensitivity would silently disable the detector it "
            "calibrates."
        )
    return value


def _env_int(name: str, default: int) -> int:
    """Read one integer knob from the environment at call time.

    The same loud-failure discipline the other knob readers hold: an
    unparseable or non-integer value raises with the knob's name, so a
    mis-spelled count fails loudly instead of silently changing what a
    detector counts.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as error:
        raise ValueError(
            f"environment knob {name}={raw!r} is not an integer."
        ) from error


def _subgroup_analysis_enabled() -> bool:
    """Whether subgroup analysis is on: the declared default, unless an installation where it is
    lawful turns it on with the environment knob of the same name (NFR-STATS-05)."""
    return _env_flag("STATS_SUBGROUP_ANALYSIS_ENABLED", STATS_SUBGROUP_ANALYSIS_ENABLED)


def _surface_proxy_threshold() -> float:
    return _env_float(
        "STATS_SURFACE_PROXY_CORRELATION_THRESHOLD",
        STATS_SURFACE_PROXY_CORRELATION_THRESHOLD,
    )


def _routing_policy_tolerance() -> float:
    return _env_float(
        "STATS_ROUTING_POLICY_TOLERANCE", STATS_ROUTING_POLICY_TOLERANCE
    )


def _drift_tolerance() -> float:
    return _env_float("STATS_DRIFT_TOLERANCE", STATS_DRIFT_TOLERANCE)


def _blind_skip_alert_after() -> int:
    """How many consecutive administrations without a blind sample trigger the alert (CT-STATS-19):
    the default, or the knob of the same name. At least one, because a lower threshold would alert
    on administrations that did run their blind sample."""
    return max(_env_int("STATS_BLIND_SKIP_ALERT_AFTER", STATS_BLIND_SKIP_ALERT_AFTER), 1)


#: FR-STATS-24 (amended) / FR-STATS-28: below this many labels a rate is no data. Read at call
#: time, so a deployment can move it without a code change (seam 3).
REVIEW_OVERRIDE_MIN_N_ENV = "HARNESS_REVIEW_OVERRIDE_MIN_N"


REVIEW_OVERRIDE_MIN_N_DEFAULT = 5


def _override_min_n() -> int:
    """The minimum number of reviews, read the same way M-REVIEW reads it (a number of at least 1),
    so the two never disagree on the threshold."""
    raw = os.environ.get(REVIEW_OVERRIDE_MIN_N_ENV, "").strip()
    if not raw:
        return REVIEW_OVERRIDE_MIN_N_DEFAULT
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(
            f"{REVIEW_OVERRIDE_MIN_N_ENV}={raw!r} is not a number") from None
    if not value >= 1:
        raise ValueError(f"{REVIEW_OVERRIDE_MIN_N_ENV}={raw!r} must be at least 1")
    return int(value)
