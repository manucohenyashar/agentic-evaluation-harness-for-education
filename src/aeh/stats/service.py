"""`ValidationStats`, the statistics over one label population, and its constructors."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .admissibility import exclusion_reasons, _is_admissible, _row_mapping, _StoredLabel
from .agreement import agreement
from .schema import STATS_STATEMENTS
from .mvvp import run_mvvp
from .comparisons import (
    alerts,
    compression_check,
    drift_check,
    routing_policy_validity,
    surface_proxies,
)
from .promotion import aggregate, promote, _record_in_memory, _scoped_population
from .history import (
    criterion_disagreement_rate,
    criterion_override_history,
    narrative_quality,
    observability_counters,
    operational_signal,
)


class ValidationStats:
    """The protocol surface §3.16's Interfaces block declares, over one label
    population. ``agreement`` (#115), ``run_mvvp`` (#116), and the four
    comparisons (#117) are the members this file delivers; ``promote``
    (#118) — the validation record's writer — is the one that arrives with
    its story. The constructor holds what the delivered members read and
    nothing else (`TC-STATS-C16` holds every entry point to the
    no-raise-on-little-data discipline).

    Beyond #115/#116's constructor state, #117's members read three more
    declared channels: ``cohort_id``, the cohort ``open_stats`` read the
    labels for (so a report cannot name a cohort the instance does not
    hold); ``evaluation_modes``, the criterion-to-mode declaration whose
    ``deterministic`` entries `CT-DET-02` puts outside a verdict
    distribution; and ``surface_correlations``/``subgroup_correlations``,
    the measured channels #116's precedent fixed — the correlations are
    the pipeline's measurement, and this module owns their interpretation.

    All state is underscore-prefixed: the instance's public surface is the
    methods, which is what the surface scans (`TC-STATS-C04`'s merge refusal)
    read."""

    def __init__(
        self,
        labels: Iterable[Any] = (),
        *,
        scoring_models: Mapping[str, str] | None = None,
        population_scopes: Sequence[str] | None = None,
        backend_profiles: Sequence[str] | None = None,
        band_counts: Mapping[str, int] | None = None,
        administration_id: str | None = None,
        cohort_id: str | None = None,
        evaluation_modes: Mapping[str, str] | None = None,
        surface_correlations: Mapping[str, Mapping[str, float]] | None = None,
        subgroup_correlations: Mapping[str, Mapping[str, float]] | None = None,
        operational_weights: Mapping[str, float] | None = None,
        administrations: Sequence[Mapping[str, Any]] | None = None,
        narrative_metrics: Mapping[str, Any] | None = None,
        data_dir: Path | str | None = None,
    ) -> None:
        self._labels = list(labels)
        self._scoring_models = dict(scoring_models or {})
        self._population_scopes = list(population_scopes or [])
        self._backend_profiles = list(backend_profiles or [])
        self._band_counts = dict(band_counts or {})
        self._administration_id = administration_id
        self._cohort_id = cohort_id
        self._evaluation_modes = dict(evaluation_modes or {})
        self._surface_correlations = {
            criterion: dict(features)
            for criterion, features in (surface_correlations or {}).items()
        }
        self._subgroup_correlations = {
            criterion: dict(features)
            for criterion, features in (subgroup_correlations or {}).items()
        }
        # #118's declared channels: the operational-evidence weighting the
        # signal reads (None = the module's declared defaults), the
        # administrations the alert surface reads, the narrative-quality
        # channel's collected metrics, and the data directory a rung-2
        # instance's promote claims through (None on a rung-0 instance,
        # whose promote writes nothing).
        self._operational_weights = (
            dict(operational_weights) if operational_weights is not None else None
        )
        self._administrations = list(administrations or [])
        self._narrative_metrics = dict(narrative_metrics or {})
        self._data_dir = data_dir
        self._last_recomputation_seconds = 0.0

    def exclusion_reasons(self, backend_profile: str | None = None,
                          criterion_id: str | None = None) -> dict[str, int]:
        """Why this population's excluded labels were excluded, by name (`FR-STATS-22`).

        The figures carry `excluded_count`, a number; this is the same exclusion read as
        causes, so "20 excluded" is actionable. Bound here because `_labels` is private:
        a consumer holding a figure reaches the breakdown through the stats object it came
        from, never by re-filtering a population it cannot see."""
        return exclusion_reasons(self._labels, backend_profile, criterion_id)

    def admissible_labels(self) -> list[Any]:
        """The admissible population — the single filter's application
        (`NFR-STATS-04`). Every figure this module emits routes through this
        call, so R20 and R53 cannot be violated by a new caller: a caller who
        wants a figure asks here, and a caller who adds a second filter adds
        a cardinality defect `TC-STATS-C01` catches on the day it appears."""
        return [label for label in self._labels if _is_admissible(label)]

    #: §3.16's declared member, defined at module level and bound here — see
    #: ``agreement`` above.
    agreement = agreement

    #: The MVVP member (#116), defined at module level and bound here — see
    #: ``run_mvvp`` above.
    run_mvvp = run_mvvp

    #: The four comparisons and the alert surface (#117), defined at module
    #: level and bound here — see each above. The same require-name reaches
    #: the same function whether the caller goes through the module or the
    #: instance, which is what the contract vocabulary's ``require`` binds.
    compression_check = compression_check
    surface_proxies = surface_proxies
    routing_policy_validity = routing_policy_validity
    drift_check = drift_check
    alerts = alerts

    #: The validation-record member and #118's figure surface, defined at
    #: module level and bound here — see each above. The same require-name
    #: reaches the same function through the module or the instance, which is
    #: what the contract vocabulary's ``require`` binds.
    promote = promote
    aggregate = aggregate
    criterion_override_history = criterion_override_history
    criterion_disagreement_rate = criterion_disagreement_rate
    narrative_quality = narrative_quality
    operational_signal = operational_signal
    observability_counters = observability_counters

    #: The population and record helpers those members route through.
    _scoped_population = _scoped_population
    _record_in_memory = _record_in_memory

    def __repr__(self) -> str:
        return f"ValidationStats(labels={len(self._labels)})"


def build_stats(
    labels: Iterable[Any] = (),
    *,
    scoring_models: Mapping[str, str] | None = None,
    population_scopes: Sequence[str] | None = None,
    backend_profiles: Sequence[str] | None = None,
    band_counts: Mapping[str, int] | None = None,
    administration_id: str | None = None,
    cohort_id: str | None = None,
    evaluation_modes: Mapping[str, str] | None = None,
    surface_correlations: Mapping[str, Mapping[str, float]] | None = None,
    subgroup_correlations: Mapping[str, Mapping[str, float]] | None = None,
    operational_weights: Mapping[str, float] | None = None,
    administrations: Sequence[Mapping[str, Any]] | None = None,
    narrative_metrics: Mapping[str, Any] | None = None,
) -> ValidationStats:
    """The rung-0/1 constructor: the protocol over an in-memory label
    population (§3.16's Interfaces block names the members; the constructor is
    this suite's, keyed on #115).

    The declared kwargs arrive as keywords — the scoring-models declaration
    keys criteria to their declared scoring models, ``population_scopes=`` and
    ``backend_profiles=`` declare the populations and backends this
    installation knows (which is what makes ``no_data_for_population`` and
    ``no_data_for_backend`` reachable rather than declarable,
    `TC-STATS-C03`'s step 3), ``band_counts=`` declares the band count a
    criterion's table carries (`TC-STATS-C21`'s disclosure), and
    ``administration_id=`` names the administration the figures speak for
    (`CT-REVIEW-10`'s keying).

    #117's members read three more: ``cohort_id=`` declares the cohort the
    labels belong to (so a report naming a different cohort is refused),
    ``evaluation_modes=`` declares each criterion's mode — the declaration
    `CT-DET-02` makes binding for a verdict distribution — and
    ``surface_correlations=``/``subgroup_correlations=`` are the measured
    channels the proxy interpretation reads, declared by the caller exactly
    as the MVVP's channels are (#116's pattern). #118's members read three
    more: ``operational_weights=`` declares the operational-evidence weights
    the signal reads (``None`` keeps the module's declared defaults),
    ``administrations=`` declares the administration history the blind-skip
    alert reads, and ``narrative_metrics=`` declares the narrative-quality
    channel's collected metrics — the channel is separate from criterion
    agreement (`CT-STATS-14`), and it speaks only where the caller declares
    it."""
    return ValidationStats(
        labels,
        scoring_models=scoring_models,
        population_scopes=population_scopes,
        backend_profiles=backend_profiles,
        band_counts=band_counts,
        administration_id=administration_id,
        cohort_id=cohort_id,
        evaluation_modes=evaluation_modes,
        surface_correlations=surface_correlations,
        subgroup_correlations=subgroup_correlations,
        operational_weights=operational_weights,
        administrations=administrations,
        narrative_metrics=narrative_metrics,
    )


def open_stats(
    data_dir: Path | str | None = None,
    *,
    cohort_id: str | None = None,
) -> ValidationStats:
    """The rung-2 constructor: statistics over a real store's labels.

    Holds the store the way ``open_review`` does (`CT-STORE-01`'s rung-2
    shape), reads the **current cohort's** label rows through the declared
    statement with the cohort bound as a parameter (`CT-STATS-C18` — a second
    cohort's labels are as much a boundary crossing as another tier), and
    writes nothing (`CT-STATS-15`). No cohort named here reads every cohort
    the store carries, which is what the accumulated-scale case
    (`TC-STATS-C17`) times.

    The rows are read at construction — the constructor is where a trace sees
    the query (`TC-STATS-C18` asserts over its actual queries) — and every
    statistic after that is computed over the labels the constructor read."""
    # The store's tier migration chains are concatenated at import time by the
    # modules that own the schema they add (CLAUDE.md): the durable handle this
    # opens must not be the first open in a process that skipped the imports.
    # These ten plus this package's review module — which owns Durable's #110
    # label-store columns this read uses — make the complete chain.
    import aeh.agg  # noqa: F401
    import aeh.det  # noqa: F401
    import aeh.extract  # noqa: F401
    import aeh.grade  # noqa: F401
    import aeh.ingest  # noqa: F401
    import aeh.integ  # noqa: F401
    import aeh.judge  # noqa: F401
    import aeh.orch  # noqa: F401
    import aeh.pkg  # noqa: F401
    import aeh.review  # noqa: F401
    import aeh.synth  # noqa: F401

    from aeh.store import open_store as _open_store

    store = _open_store(data_dir)
    try:
        handle = store.durable()
        read_started = time.perf_counter()
        if cohort_id is not None:
            rows = handle.query(STATS_STATEMENTS["select_labels"], cohort_id=cohort_id)
        else:
            rows = handle.query(STATS_STATEMENTS["select_labels_all"])
        labels = [_StoredLabel(_row_mapping(row)) for row in rows]
        read_seconds = time.perf_counter() - read_started
    except Exception:
        store.close()
        raise
    store.close()
    # The cohort binding travels with the labels: an instance that read one
    # cohort's rows must refuse a report naming any other (CT-STATS-C18's
    # boundary, enforced at the report rather than by convention). Where no
    # cohort was named the instance holds every cohort's rows and binds none.
    # The directory travels too (#118): the instance's promote claims through
    # the durable file this open created, and the read's duration is the
    # initial value of the recomputation counter — the read *is* the
    # recomputation a rung-2 instance was built from.
    instance = ValidationStats(labels, cohort_id=cohort_id, data_dir=store.data_dir)
    instance._last_recomputation_seconds = read_seconds
    return instance
