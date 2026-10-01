"""Override history, disagreement rates, narrative quality, the operational signal and counters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from collections import Counter
from typing import Any

from aeh.pkg import NoValidationData

from .settings import OPERATIONAL_EVIDENCE_WEIGHTS, _override_min_n
from .admissibility import _is_admissible, _row_mapping, _StoredLabel, _system_side
from .schema import STATS_STATEMENTS
from .records import (
    CriterionDisagreement,
    CriterionOverrideHistory,
    NarrativeQualityReport,
    OperationalSignal,
)
from .comparisons import _refuse_foreign_cohort, _require_str_or_none
from .promotion import _label_evidence_key, _label_pair_agrees

if TYPE_CHECKING:
    from .service import ValidationStats


def criterion_override_history(
    self: "ValidationStats", criterion_id: str
) -> "CriterionOverrideHistory | NoValidationData":
    """One criterion's override history (CT-STATS-09): how many reviews it has, how many overrode
    the panel, and the rate, over admissible labels only (NFR-STATS-04).

    A criterion nobody has reviewed returns `NoValidationData` — the clause's
    own distinction: a zero rate on a reviewed criterion is evidence the
    criterion works, a zero on an unreviewed one is evidence of nothing, and
    the two must not be the same value (they rank oppositely in exactly the
    queue that decides what gets looked at next)."""
    _require_str_or_none("criterion_override_history", criterion_id=criterion_id)
    population = [
        label
        for label in self.admissible_labels()
        if (getattr(label, "criterion_id", "") or "") == criterion_id
    ]
    if not population:
        return NoValidationData(reason="no_blind_labels", n=0)
    n = len(population)
    if n < _override_min_n():
        # FR-STATS-24 (amended, #433): four teachers who overrode once are not a 25% rate.
        return NoValidationData(reason="below_min_n", n=n)
    override_count = sum(
        1 for label in population if getattr(label, "origin", None) == "override"
    )
    return CriterionOverrideHistory(
        criterion_id=criterion_id,
        n=n,
        override_count=override_count,
        override_rate=override_count / n,
    )


def criterion_disagreement_rate(
    self: "ValidationStats", criterion_id: str
) -> "CriterionDisagreement | NoValidationData":
    """The criterion's disagreement rate over every blind or operational label that carries both
    bands, not only admissible blind ones (FR-STATS-28). A disagreement is `system_band !=
    teacher_band`, that is `agreed = 0` (FR-REVIEW-21). Same minimum-n rule and no-data reasons as
    the override history; no data is never reported as 0.0 (CT-STATS-09)."""
    _require_str_or_none("criterion_disagreement_rate", criterion_id=criterion_id)
    # EVERY label carrying both bands: blind labels and the queue's own decisions alike.
    # ("Operational" is a category, not a stored label_type: the review flow stores
    # accept/edit/override, and filtering on the word would leave this figure inert on a
    # real store, the outcome ADR-30 rejected; #433 review.)
    pairs = [
        (_system_side(label), getattr(label, "teacher_band", None))
        for label in self._labels
        if (getattr(label, "criterion_id", "") or "") == criterion_id
    ]
    pairs = [(system, teacher) for system, teacher in pairs
             if system is not None and teacher is not None]
    n = len(pairs)
    if n == 0:
        return NoValidationData(reason="no_blind_labels", n=0)
    if n < _override_min_n():
        return NoValidationData(reason="below_min_n", n=n)
    disagreements = sum(1 for system, teacher in pairs if str(system) != str(teacher))
    return CriterionDisagreement(criterion_id=criterion_id, n=n, disagreements=disagreements,
                                 rate=disagreements / n)


def stored_disagreement_rates(
    store: Any, package_version_id: str
) -> dict[str, "CriterionDisagreement | NoValidationData"]:
    """The stored disagreement rate for each criterion of `package_version_id` (FR-STATS-28), over
    the stored labels of that package's lineage (labels naming any version of the same package,
    plus labels naming no version)."""
    from .service import ValidationStats  # here, not at the top: .service imports this file
    from aeh.pkg import PackageCatalog

    package_id = str(package_version_id).rpartition("@")[0]
    catalog = PackageCatalog(store.package(package_id), package_id=package_id)
    criteria = [str(row["criterion_id"]) for row in catalog.criteria(package_version_id)]
    rows = store.durable().query(STATS_STATEMENTS["select_labels_all"])
    lineage_prefix = f"{package_id}@"
    labels = []
    for row in rows:
        label = _StoredLabel(_row_mapping(row))
        version = label._row.get("package_version_id")
        if version is None or str(version).startswith(lineage_prefix):
            labels.append(label)
    stats = ValidationStats(labels)
    return {criterion: stats.criterion_disagreement_rate(criterion) for criterion in criteria}


def _lineage_stats(store: Any, package_version_id: str) -> tuple["ValidationStats", list[str]]:
    """A `ValidationStats` over one package lineage's stored labels (labels naming a version of the
    same package, or no version), and the version's criteria."""
    from .service import ValidationStats  # here, not at the top: .service imports this file
    from aeh.pkg import PackageCatalog

    package_id = str(package_version_id).rpartition("@")[0]
    catalog = PackageCatalog(store.package(package_id), package_id=package_id)
    criteria = [str(row["criterion_id"]) for row in catalog.criteria(package_version_id)]
    lineage_prefix = f"{package_id}@"
    labels = []
    for row in store.durable().query(STATS_STATEMENTS["select_labels_all"]):
        label = _StoredLabel(_row_mapping(row))
        version = label._row.get("package_version_id")
        if version is None or str(version).startswith(lineage_prefix):
            labels.append(label)
    return ValidationStats(labels), criteria


def stored_override_histories(
    store: Any, package_version_id: str
) -> dict[str, "CriterionOverrideHistory | NoValidationData"]:
    """The override history for each criterion of `package_version_id`, over the package lineage's
    stored labels (FR-STATS-24). M-PIPE uses this as the escalation `history` input (FR-PIPE-15).
    """
    stats, criteria = _lineage_stats(store, package_version_id)
    return {criterion: stats.criterion_override_history(criterion) for criterion in criteria}


def narrative_quality(self: "ValidationStats", cohort_id: str | None = None) -> NarrativeQualityReport:
    """The narrative-quality figures, kept separate from score agreement (FR-STATS-12,
    CT-STATS-14): citation validity rate, hallucinated-claim rate, and the teacher's rating when
    collected. They come from the `narrative_metrics=` input given to the constructor and are never
    merged into an agreement figure. A metric with no input is None, never zero."""
    _require_str_or_none("narrative_quality", cohort_id=cohort_id)
    _refuse_foreign_cohort(self, cohort_id, "narrative_quality")
    channel = self._narrative_metrics
    return NarrativeQualityReport(
        cohort_id=cohort_id if cohort_id is not None else self._cohort_id,
        citation_validity_rate=channel.get("citation_validity_rate"),
        hallucinated_claim_rate=channel.get("hallucinated_claim_rate"),
        teacher_rating=channel.get("teacher_rating"),
        channel_declared=bool(channel),
    )


def operational_signal(
    self: "ValidationStats", cohort_id: str | None = None
) -> OperationalSignal:
    """The weighted operational signal (FR-STATS-14): the weighted mean agreement over the paired
    labels, with the weights that produced it.

    The weights key on the label's evidence class (`OPERATIONAL_EVIDENCE_ORDER`
    through ``_label_evidence_key``): an override informative, an acceptance
    weak, the blind score authoritative. ``operational_weights=None`` — the
    constructor's default — computes with the declared ordering's defaults;
    the caller's mapping replaces them. The value is a signal, not a figure:
    the agreement figure is computed unweighted, always, which is the
    clause's *"never blurs into a validity claim"* — `CT-STATS-06`'s
    κ-invariance case pins exactly that."""
    _require_str_or_none("operational_signal", cohort_id=cohort_id)
    _refuse_foreign_cohort(self, cohort_id, "operational_signal")
    declared = self._operational_weights
    weights = dict(OPERATIONAL_EVIDENCE_WEIGHTS if declared is None else declared)
    population = self._scoped_population(cohort_id)
    numerator = 0.0
    denominator = 0.0
    n = 0
    for label in population:
        agrees = _label_pair_agrees(label)
        if agrees is None:
            continue
        weight = float(weights.get(_label_evidence_key(label), 1.0))
        numerator += weight * (1.0 if agrees else 0.0)
        denominator += weight
        n += 1
    signal = numerator / denominator if denominator > 0.0 else None
    return OperationalSignal(
        signal=signal,
        weights=weights,
        n=n,
        weighted=any(value != 1.0 for value in weights.values()),
    )


def observability_counters(self: "ValidationStats") -> dict[str, Any]:
    """The four counters M-STATS emits (CT-STATS-19): label counts by type (blind or operational),
    label counts by origin (the random arm or the rest; kept separate so the random arm stays
    visible), blind coverage per administration, and how long the last recomputation took.

    Names are the contract: an operator's dashboard binds them, which is why
    the values ride a plain mapping rather than a type a dashboard would have
    to know."""
    by_type = Counter(
        (getattr(label, "label_type", "") or "") or "unrecorded"
        for label in self._labels
    )
    by_origin = Counter(
        (getattr(label, "origin", None) or "") or "unrecorded"
        for label in self._labels
    )
    coverage: dict[str, int] = {}
    for label in self._labels:
        cohort = getattr(label, "cohort_id", None)
        if cohort is not None and _is_admissible(label):
            coverage[cohort] = coverage.get(cohort, 0) + 1
    return {
        "label_count_by_type": dict(by_type),
        "label_count_by_origin": dict(by_origin),
        "blind_coverage_per_administration": coverage,
        # #356 (`FR-STATS-22`, seam 4): WHY the excluded labels were excluded, beside how
        # many. `saw_system_output_unrecorded` is the one a deployment can act on.
        "excluded_by_reason": self.exclusion_reasons(),
        "statistics_recomputation_duration": self._last_recomputation_seconds,
    }
