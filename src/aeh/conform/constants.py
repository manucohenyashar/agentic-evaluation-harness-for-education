"""The fixed vocabulary of the conformance suite: corpus names, dimensions, classifications, alerts."""

from __future__ import annotations

from typing import Mapping

from harness.corpora import adv_pdf, conform_set


CORPUS_NAME = conform_set.CORPUS_NAME


#: The pin label the callers use (`load_fixture_set("v1")`). Normalized by stripping a leading
#: `v` before comparing to the manifest's version, so `load_fixture_set("v1")` and a future
#: `load_fixture_set("1")` name the same set rather than two.
DEFAULT_PIN_LABEL = conform_set.VERSION_LABEL


#: Env knob (seam 3): where the corpora live. Production value is the committed `fixtures/`
#: directory; the knob exists for a run that keeps them elsewhere.
FIXTURE_ROOT_ENV = "HARNESS_FIXTURE_ROOT"


#: The cohort the ingest surface writes into — an ephemeral store's whole population, so the
#: name is a label rather than a scope to be careful about.
INGEST_COHORT = "c-conform-fixtures"


#: The declared refusal world's decompressed-bytes ceiling, derived from the corpora's own
#: declaration: one sixty-fourth of the bomb's expansion (`BOMB_DECOMPRESSED_BYTES`, 64 MiB) —
#: 1 MiB today. Below it ADV-PDF-09 crosses the ceiling at V0 and quarantines having reached no
#: model call; above it sit every legitimate fixture with orders of magnitude to spare (the
#: largest figure measured through the sanitizer's own accounting among the committed PDFs is
#: SC-04's 1,338 bytes). M-INGEST's production default (512 MiB) *accepts* the bomb — that
#: default is the production posture; this is the stricter world the F-ADV-PDF rows' declared
#: outcomes (`quarantine_at_v0`) are written against. Deriving from the declaration keeps the
#: wrapper below the bomb if the declaration is ever retuned, and the regression case
#: (`test_regression_..._decompression_bomb_...`) fails if either side drifts.
_DECLARED_REFUSAL_MAX_DECOMPRESSED_BYTES = adv_pdf.BOMB_DECOMPRESSED_BYTES // 64


#: The gate order `IngestReport.gates` is read in when naming the first gate that failed. V3's
#: failing values are its own (the identity gate reports `unmatched`/`ambiguous`, not `fail`),
#: which is why the refusal values come from M-INGEST's table rather than a literal here.
_GATE_ORDER: tuple[str, ...] = ("v0", "v1", "v2", "v3", "v4")


# --- the comparison vocabulary (design §3.18, adopted as declared) -------------------------------
#
# These names are the conformance comparison's declared surface — the same words
# `tests/support/conform_vocabulary.py` declares for the suite that drives them. They are
# re-declared here rather than imported from the tests because a production module does not
# import its tests; the vocabulary file carries the adoption note, and a rename is one edit in
# each place.

#: The five divergence dimensions §7.4 declares, as the report keys them.
SCORE_DISTRIBUTION_DIMENSION = "per_criterion_score_distribution"


AGREEMENT_DIMENSION = "chance_corrected_agreement"


CONFIDENCE_DIMENSION = "confidence_and_escalation_rate"


EVIDENCE_INTEGRITY_DIMENSION = "evidence_integrity_failure_rate"


SELF_AGREEMENT_DIMENSION = "self_agreement_over_repeated_runs"


DIVERGENCE_DIMENSIONS = (
    SCORE_DISTRIBUTION_DIMENSION,
    AGREEMENT_DIMENSION,
    CONFIDENCE_DIMENSION,
    EVIDENCE_INTEGRITY_DIMENSION,
    SELF_AGREEMENT_DIMENSION,
)


#: The three divergence classifications (§7.4). `blocking` gates the release; `informational`
#: is a finding recorded beside the decision; `unavailable` means no gate may fire for the
#: dimension at all — CT-CONFORM-14 declines to declare a statistic for the score-distribution
#: comparison, so its gate *cannot* fire rather than firing loosely.
CLASSIFICATION_BLOCKING = "blocking"


CLASSIFICATION_INFORMATIONAL = "informational"


CLASSIFICATION_UNAVAILABLE = "unavailable"


#: The static classification per dimension (§7.4's table): the integrity gate blocks, the
#: score distribution is not computable as a gate (CT-CONFORM-14), and the rest are findings.
EXPECTED_CLASSIFICATION: Mapping[str, str] = {
    SCORE_DISTRIBUTION_DIMENSION: CLASSIFICATION_UNAVAILABLE,
    AGREEMENT_DIMENSION: CLASSIFICATION_INFORMATIONAL,
    CONFIDENCE_DIMENSION: CLASSIFICATION_INFORMATIONAL,
    EVIDENCE_INTEGRITY_DIMENSION: CLASSIFICATION_BLOCKING,
    SELF_AGREEMENT_DIMENSION: CLASSIFICATION_INFORMATIONAL,
}


#: The two gated dimensions, as the clause suite names them.
UNAVAILABLE_GATE_DIMENSION = SCORE_DISTRIBUTION_DIMENSION


LIVE_GATE_DIMENSION = EVIDENCE_INTEGRITY_DIMENSION


#: The gates and the findings, partitioned once: every dimension is exactly one of the two.
GATE_DIMENSIONS = (UNAVAILABLE_GATE_DIMENSION, LIVE_GATE_DIMENSION)


INFORMATIONAL_DIMENSIONS = tuple(
    dimension for dimension in DIVERGENCE_DIMENSIONS if dimension not in GATE_DIMENSIONS
)


#: The dispatch value a recorded-transport run reports for its transcription stage, and the
#: result field it is reported under (`TC-CONFORM-04`'s dispatch assertion reads the field).
TRANSCRIPTION_DISPATCH_FIELD = "transcription_dispatch"


RECORDED_FIXTURE_DISPATCH = "recorded_fixture"


#: The self-agreement figure (`TC-CONFORM-12`): reported per backend, keyed under the
#: dimension name in each backend's `figures`, carrying its stated `n`.
SELF_AGREEMENT_FIELD = "self_agreement"


SELF_AGREEMENT_REPEATS_FIELD = "n"


MIN_SELF_AGREEMENT_REPEATS = 2


#: The per-backend figures mapping's field name (`TC-CONFORM-12`'s `figures.get(...)`).
PER_BACKEND_FIGURES_FIELD = "figures"


#: The alert surface (`TC-CONFORM-13`), named after the two shipped alert readers
#: (`aeh.orch:evaluate_alerts`, `aeh.grade:evaluate_grade_alerts`), and the two alert kinds.
CONFORMANCE_ALERT_SURFACE = "evaluate_conformance_alerts"


ALERT_DIVERGENCE_GATE_CROSSED = "divergence_gate_crossed"


ALERT_BUILD_SUBSTITUTION_DETECTED = "build_substitution_detected"


#: Design §3.18's observability line: the three fields a divergence needs to be attributable.
OBSERVABILITY_FIELDS = frozenset({
    "per_dimension_divergence",
    "fixture_set_version",
    "resolved_builds",
})


RESOLVED_BUILDS_FIELD = "resolved_builds"


REQUESTED_BUILDS_FIELD = "requested_builds"


#: The stages a conformance run executes (`TC-CONFORM-03`'s sweep), the stage no recorded
#: transport may stand in for (`CT-CONFORM-03`), the VLM path the real-medium clause names,
#: and the shortcut stage that must appear for none of it.
PIPELINE_STAGES = ("ingest", "transcribe", "extract", "judge", "integrity", "aggregate", "grade")


UNSTUBBABLE_STAGE = "ingest"


VLM_STAGE = "transcribe"


TEXT_SHORTCUT_STAGE = "text_passthrough"


#: §4.7's per-backend conformance budget (the live-tier threshold `TC-CONFORM-11` prices).
CONFORMANCE_BUDGET_SECONDS = 3600


#: The env knob (seam 3) that says this box declares the live backends a live conformance
#: run dispatches through. A profile it names is dispatched through the shipped live
#: providers — the backend's own transport and transcriber ref (`_live_provider_for`) — and
#: the dispatch field reports the build that actually served; every other run uses the
#: recorded derivation.
LIVE_BACKENDS_ENV = "HARNESS_CONFORM_LIVE_BACKENDS"
