"""Stored score rows as the ranking reads them, and the per-run package facts they need."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from .settings import SCORING_MODEL_EST_SECONDS
from .schema import REVIEW_STATEMENTS


def _newest_run_id(store: Any, cohort_id: str) -> str | None:
    """The run a cohort's score reads are limited to: the newest run, or None for a cohort with no
    runs (CT-AGG-20)."""
    rows = store.cohort(cohort_id).query(REVIEW_STATEMENTS["select_newest_run"])
    return str(_row_mapping(rows[0])["run_id"]) if rows else None


def _store_cohort_ids(store: Any) -> list[str]:
    """The cohort ids a store holds, sorted: one `cohorts/<cohort_id>.sqlite` file per
    administration, the same layout M-DET and M-ORCH use."""
    return sorted(
        path.stem for path in Path(store.data_dir, "cohorts").glob("*.sqlite")
    )


def _given(
    mapping: Mapping[str, Any],
    name: str,
    store_column: str | None = None,
    *,
    default: "Callable[[], Any] | None" = None,
) -> Any:
    """One ranking input: the caller's value if given, else the stored column, else the run's
    package.

    The precedence matters and is not arbitrary. `rank_queue_items` is public and takes
    mappings in the ranking's own vocabulary — a caller that says `grade_boundary_delta`
    means it, and reading only the store's spelling silently discarded it (`CT-GRADE-19`:
    the queue then ranked by arrival order rather than by boundary proximity). A stored
    row carries the store's spelling and none of the caller's, so for the store path this
    resolves to the same value either way; the two vocabularies never collide.
    """
    value = mapping.get(name)
    if value is not None:
        return value
    if store_column is not None:
        value = mapping.get(store_column)
        if value is not None:
            return value
    return default() if default is not None else None


def _adverse_signal_count(mapping: Mapping[str, Any]) -> int:
    """How many integrity signals are adverse, using M-AGG's definition (FR-REVIEW-18).

    Imported at call time: `aeh.agg` and `aeh.review` both own cohort migrations, and a
    module-level import would pin the order in which their chains register."""
    from aeh.agg import adverse_signal_count

    return adverse_signal_count(mapping)


class _ScoreRowContext:
    """Facts from the run's package that a stored score row does not carry itself (FR-REVIEW-18).

    A `criterion_score` row knows what the panel did; it does not know what the criterion
    is WORTH, which model scores it, where the submission's total sits relative to a grade
    boundary, or how often teachers have overridden this criterion before. Those four come
    from the run's package version and from Tier D, are the same for every row in a build,
    and are resolved once here rather than per row (`NFR-PKG-05`: ~23,000 unit reads).

    Every lookup has a declared answer for "not known", and none of them is a silent zero:
    an unknown weight is `1.0` (M-GRADE's own reading of an unweighted sum, `grade.py:474`
    — `weights.get(cid, 1.0)`), an unknown scoring model is `None` so `est_seconds` falls
    back to the model-free default, and an unmeasured override rate is `None` so
    `CT-STATS-09`'s no-data figure applies instead of "nobody disagrees".
    """

    def __init__(
        self,
        *,
        weights: Mapping[str, float] | None = None,
        models: Mapping[str, str] | None = None,
        boundary_deltas: Mapping[str, float | None] | None = None,
        override_rates: Mapping[str, float | None] | None = None,
        knobs: Mapping[str, float] | None = None,
    ) -> None:
        self._weights = dict(weights or {})
        self._models = dict(models or {})
        self._boundary_deltas = dict(boundary_deltas or {})
        self._override_rates = dict(override_rates or {})
        self._knobs = dict(knobs or {})

    def weight(self, criterion_id: Any) -> float:
        """The criterion's weight, read the way M-GRADE reads it, so the ranking's view of a
        criterion's share matches the grade's."""
        return float(self._weights.get(criterion_id, 1.0))

    def declared_models(self) -> "Mapping[str, str]":
        """Every criterion the run's package version declares, with its scoring model; this decides
        whether a criterion exists (FR-REVIEW-19)."""
        return dict(self._models)

    def model_for(self, criterion_id: Any) -> str | None:
        """The criterion's scoring model as the package declares it, or None. It is passed on,
        never guessed."""
        model = self._models.get(criterion_id)
        return str(model) if model else None

    def boundary_delta(self, submission_id: Any) -> float | None:
        return self._boundary_deltas.get(submission_id)

    def override_rate(self, criterion_id: Any) -> float | None:
        return self._override_rates.get(criterion_id)

    def est_seconds(self, model: str | None, default: float) -> float:
        """The review-time estimate for the criterion's scoring model, looked up in the declared
        table; an undeclared model gets the model-free default (FR-REVIEW-18)."""
        declared = SCORING_MODEL_EST_SECONDS.get(model or "")
        if declared is None:
            return float(default)
        knob, fallback = declared
        return float(self._knobs.get(knob.lower(), fallback))


def _run_row_context(
    store: Any, cohort_id: str, run_id: str, knobs: Mapping[str, float]
) -> "_ScoreRowContext":
    """The run's package facts, read once per queue build (FR-REVIEW-18).

    Every lookup here is best-effort by design: this is the RANKING, and a run whose
    package file has been archived, or which has not been graded yet, must still produce
    an ordered queue rather than refuse to show one. What it must never do is invent a
    figure — each failure leaves the corresponding lookup unset, and `_ScoreRowContext`
    turns "unset" into the declared no-data answer rather than into a zero.
    """
    from aeh.pkg import PackageCatalog

    handle = store.cohort(cohort_id)
    rows = handle.query(REVIEW_STATEMENTS["select_run_package"], run_id=run_id)
    if not rows:
        return _ScoreRowContext(knobs=knobs)
    package_id = rows[0]["package_id"]
    version_id = rows[0]["package_version_id"]

    weights: dict[str, float] = {}
    models: dict[str, str] = {}
    boundary_deltas: dict[str, float | None] = {}
    try:
        catalog = PackageCatalog(store.package(package_id), package_id=package_id)
        policy = catalog.grade_policy(version_id)
        # M-GRADE's reading, transcribed: a criterion the policy does not name weighs
        # 1.0, which is what makes an unweighted sum a sum (`grade.py:474`). Reading it
        # as 0.0 would drop exactly the criteria the default policy covers.
        weights = {cid: float(w) for cid, w in (getattr(policy, "weights", None) or ())}
        for entry in catalog.criteria(version_id):
            declared_model = (
                entry["scoring_model"] if "scoring_model" in entry.keys() else None
            )
            if declared_model:
                models[entry["criterion_id"]] = str(declared_model)
        for row in handle.query(
            REVIEW_STATEMENTS["select_run_submission_totals"], run_id=run_id
        ):
            total = row["total"]
            if total is None:
                continue
            # `None` from a version with no boundary table is kept as `None`
            # (`CT-PKG-10`): no invented distance, and no invented proximity either.
            boundary_deltas[row["submission_id"]] = (
                catalog.distance_to_nearest_boundary(version_id, float(total))
            )
    except Exception:
        # An unreadable or archived package ranks on what the rows themselves carry.
        # The queue stays ordered; it is simply ordered by fewer inputs.
        pass

    # FR-REVIEW-18 (amended) / FR-STATS-28 (#433): the eighth input is M-STATS' disagreement
    # rate for the run's package version; M-REVIEW derives no rate of its own. A no-data
    # answer is carried as `None`, which P(error) already treats as no data, never 0.0.
    override_rates: dict[str, float | None] = {}
    try:
        from aeh.stats import CriterionDisagreement, stored_disagreement_rates

        for criterion_id, figure in stored_disagreement_rates(store, version_id).items():
            override_rates[criterion_id] = (
                figure.rate if isinstance(figure, CriterionDisagreement) else None)
    except Exception:
        override_rates = {}

    return _ScoreRowContext(
        weights=weights,
        models=models,
        boundary_deltas=boundary_deltas,
        knobs=knobs,
        override_rates=override_rates,
    )


#: The context for a row built with no package behind it — every lookup takes its
#: declared "not known" answer. `rank_queue_items` over bare mappings uses this.
_EMPTY_ROW_CONTEXT = _ScoreRowContext()


class _StoredScoreRow:
    """One stored criterion-score row as the ranking reads it: store columns mapped to the
    ranking's field names, with the row's own values where the store has them and plain defaults
    where it does not (for example, no override history reads as no data)."""

    def __init__(
        self,
        mapping: Mapping[str, Any],
        default_est_seconds: float,
        context: "_ScoreRowContext | None" = None,
    ) -> None:
        facts = context if context is not None else _EMPTY_ROW_CONTEXT
        submission_id = mapping.get("submission_id")
        criterion_id = mapping.get("criterion_id")
        self.score_id = f"{submission_id}:{criterion_id}"
        self.criterion_id = criterion_id
        self.submission_id = submission_id
        #: The run the stored row belongs to, so a review settles THAT run's row (#517).
        self.run_id = mapping.get("run_id")
        self.routing = mapping.get("routing")
        self.origin = mapping.get("origin", "escalation")
        self.evaluation_mode = mapping.get("evaluation_mode", "judged")
        self.state = mapping.get("state")
        self.proposed_band = mapping.get("band")
        # `FR-REVIEW-18`: every one of these is READ FROM THE ROW or from the run's
        # package, under the name the store actually uses. They were previously fetched
        # under the ranking's own vocabulary — `panel_spread`, `transcription_overlap`,
        # `criterion_weight` — which `select_run_advisory_scores` has never returned, so
        # each resolved `None` and every store-backed row ranked identically at 0.0.
        #
        # The panel's disagreement, as the aggregator recorded it: the ordinal distance
        # between the panel's extreme bands (`agg.band_spread`), not a re-derivation.
        self.panel_spread = _given(mapping, "panel_spread", "band_spread")
        # Counted through M-AGG so the polarity has ONE definition (`agg._AGG_FAVOURABLE`)
        # and the count agrees with the confidence already stored on this row.
        given_signals = mapping.get("adverse_integrity_signals")
        self.adverse_integrity_signals = (
            given_signals if given_signals is not None
            else _adverse_signal_count(mapping)
        )
        # The OCR risk flag is the transcription-overlap input; it is a 0/1 column, which
        # is the 0-1 figure `_p_error` weights.
        self.transcription_overlap = _given(
            mapping, "transcription_overlap", "ocr_overlap_risk"
        )
        # Per (package lineage, criterion), and `None` below the minimum count — NOT a
        # zero (`CT-STATS-09`). `_override_rate_of` turns the `None` into the no-data
        # figure; a zero here would say "nobody ever disagrees with this criterion".
        self.historical_override_rate = _given(
            mapping, "historical_override_rate",
            default=lambda: facts.override_rate(criterion_id),
        )
        # The criterion's share of the grade, from the run's package. This is the input
        # that made the whole ranking constant: `_impact_of` multiplies by it, so a
        # missing weight zeroed the product no matter how loud the other six inputs were.
        self.criterion_weight = _given(
            mapping, "criterion_weight", default=lambda: facts.weight(criterion_id)
        )
        self.grade_boundary_delta = _given(
            mapping, "grade_boundary_delta",
            default=lambda: facts.boundary_delta(submission_id),
        )
        # The package's declaration first, then the row's own — a caller ranking mappings
        # it built itself (`rank_queue_items`) carries the model ON the mapping and has no
        # package behind it. `None` only when neither says: the hard-coded `"atomic"` this
        # replaces answered for both, which is how a holistic criterion came to be
        # budgeted at an atomic criterion's minutes.
        model = _given(
            mapping, "scoring_model", default=lambda: facts.model_for(criterion_id)
        )
        self.scoring_model = model
        est = mapping.get("est_seconds")
        if not est:
            est = facts.est_seconds(model, default_est_seconds)
        self.est_seconds = est
        self.self_confidence = mapping.get("confidence")
        self.spans_verified = mapping.get("spans_verified")
        self.evidence_present = mapping.get("evidence_present")
        self.sufficiency_flag = mapping.get("sufficiency_flag")
        self.ocr_overlap_risk = mapping.get("ocr_overlap_risk")
        self.described_evidence = mapping.get("described_evidence")
        self.extractor_disagreement = mapping.get("extractor_disagreement")
        # The score's version as the store records it: the panel depth. An escalation
        # widens the panel (1 -> 3 -> 5) and re-scores the row, which is exactly the
        # supersession CT-REVIEW-15's stale refusal is about (#398).
        self.version = int(mapping.get("judge_count") or 1)


def _row_mapping(row: Any) -> dict[str, Any]:
    """A store row as a plain mapping, whatever row type the tier returns."""
    try:
        return {key: row[key] for key in row.keys()}
    except AttributeError:
        return dict(row)
