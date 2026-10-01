"""Confidence thresholds, confidence caps and escalation weights."""

from __future__ import annotations

from types import MappingProxyType


# --- #92: the confidence surface's declared constants (§3.12) ---------------------------------------
#
# Production defaults, declared here and injected at the call (`config=`): the
# policy reads no configuration beyond the values passed in (`CT-AGG-01`), so
# these constants are what a `config=None` call uses — never a second reading
# path. The numbers are §3.12's Assumption-numbered cap table and thresholds:
# fixture data in the tests (Q-04), production defaults here.

#: Auto-accept threshold for an atomic criterion (§3.12: auto-accept iff
#: `confidence >= auto_threshold_for(scoring_model)`).
AGG_AUTO_THRESHOLD_ATOMIC: float = 0.80


#: Auto-accept threshold for a holistic criterion — a holistic panel is held to
#: the higher bar §3.12 names.
AGG_AUTO_THRESHOLD_HOLISTIC: float = 0.90


#: §3.12's multiplier applied to the base when any verdict is uncited.
AGG_UNCITED_MULTIPLIER: float = 0.80


#: §3.12's multiplier applied to the base for a holistic criterion.
AGG_HOLISTIC_MULTIPLIER: float = 0.85


#: §3.12's Assumption cap table: the hard ceiling each adverse integrity signal
#: puts on the confidence. ADR-10's whole point lives in how these are applied:
#: a cap is a `min`, never a penalty term, so no amount of panel agreement can
#: lift the figure past the worst adverse signal (R19). A signal reading
#: `None` — "not measured" — is adverse, fail-closed, and binds the same cap.
AGG_CAP_TABLE = MappingProxyType({
    "spans_verified": 0.25,
    "evidence_present": 0.25,
    "sufficiency_flag": 0.25,
    "ocr_overlap_risk": 0.30,
    "described_evidence": 0.50,
    "extractor_disagreement": 0.40,
})


# --- #93: the escalation policy's declared constants (§3.12, §3.8) ----------------------------------
#
# The design pins the SHAPE of the escalation decision — observable signals,
# self-confidence weighted but never authoritative — and records the weights
# themselves as a `TBD`: "whether the escalation policy weights over observable
# signals are fixed constants at Phase 1 or fitted against the accumulated label
# store from Phase 2 ... Phase 1 ships fixed weights" (§3.8). These are those
# fixed Phase-1 weights: production defaults declared here and injected at the
# call (`should_escalate(..., config=...)`), the same shape as the confidence
# surface's — the policy reads no configuration beyond the values passed in
# (`CT-AGG-01`), never the environment. The numbers are Assumption-class, the
# same standing §3.12's cap table has, and R22's whole point lives in their
# RATIOS, not their absolute scale: every observable signal weighs a full
# `AGG_ESCALATION_SIGNAL_WEIGHT`, the decision fires at
# `AGG_ESCALATION_THRESHOLD`, and self-confidence's largest possible
# contribution — its weight times the full sweep of its range — stays strictly
# below that threshold. That inequality is the "never the sole trigger"
# requirement made structural rather than accidental: no value a model reports
# about itself can cross the line alone, under any tuning that keeps the
# inequality.

#: The concern level at which `should_escalate` decides to escalate. Each
#: observable signal carries `AGG_ESCALATION_SIGNAL_WEIGHT` when it fires, so
#: any one of them alone reaches the threshold; self-confidence cannot.
AGG_ESCALATION_THRESHOLD: float = 1.0


#: The weight of one fired observable signal (§3.12/§7.1's enumeration:
#: interior band position, adverse integrity signals, uncited verdict,
#: transcription overlap, criterion override history, distributional anomaly).
AGG_ESCALATION_SIGNAL_WEIGHT: float = 1.0


#: The weight an unmeasured override history contributes (CT-STATS-09: a
#: criterion nobody has reviewed is not a criterion nobody disagrees with —
#: "no data" is not a zero). Deliberately below the threshold: a fresh
#: criterion with no history draws attention in the ranking
#: (`rank_criteria_for_escalation`) but does not escalate on absence alone.
AGG_ESCALATION_NO_DATA_WEIGHT: float = 0.5


#: The weight of model self-confidence — ONE weighted input (FR-AGG-08). It
#: enters as `weight × (1 − self_confidence)`, clamped to the weight's own
#: ceiling: at the most self-doubting report possible it adds the full weight,
#: and `weight < AGG_ESCALATION_THRESHOLD` is what makes it structurally
#: incapable of triggering alone (R22: a model's own certainty is the least
#: reliable signal available).
AGG_ESCALATION_SELF_CONFIDENCE_WEIGHT: float = 0.25


#: How many standard deviations from the package's expected band position
#: counts as a distributional anomaly (§3.12's "distributional anomaly against
#: the package baseline"; the design names no k — declared here, the
#: α-convention precedent).
AGG_ESCALATION_ANOMALY_SIGMA: float = 2.0


#: The override rate above which the criterion's own history counts as an
#: escalation signal — "more than half of its reviewed scores were overridden",
#: the same strict reading the criterion breaker takes (CT-ORCH-16). The design
#: names no rate; declared here so the knob is injectable with the rest
#: (`should_escalate(..., config=...)`), never hard-coded at the call.
AGG_ESCALATION_OVERRIDE_RATE: float = 0.5
