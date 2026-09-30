"""Per-judge signals for a run, and the alert when violations concentrate on one judge."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .settings import _env_float, _env_int
from .schema import STATS_STATEMENTS


# --- the four comparisons (#117, FR-STATS-06..09) --------------------------------------------------
#
# Four checks over the same admissible population that the agreement figure
# reads, each a comparison rather than a quality number and each carrying its
# fixed interpretation inside its own value. Like ``agreement`` above, each is
# defined at module level and bound into ``ValidationStats``, so the surface
# ``require(STATS_MODULE, ...)`` names and the method the instance carries are
# the same function — and each routes its population through the single
# filter's application (``admissible_labels()``, `NFR-STATS-04`): no figure on
# this surface is computed over any other population.


# --- the judge signals (FR-STATS-20, CT-JUDGE-16) ----------------------------------------------

#: The concentration alert's two Assumption-class knobs (`FR-STATS-20`): a judge holding
#: STRICTLY more than this share of a criterion's contract violations, with at least
#: `STATS_VIOLATION_MINIMUM` of them in the criterion, is named. Read at call time (seam 3).
STATS_VIOLATION_CONCENTRATION: float = 0.5


STATS_VIOLATION_CONCENTRATION_ENV = "HARNESS_STATS_VIOLATION_CONCENTRATION"


STATS_VIOLATION_MINIMUM: int = 5


STATS_VIOLATION_MINIMUM_ENV = "HARNESS_STATS_VIOLATION_MINIMUM"


#: `CT-JUDGE-16`'s six declared signal names, in the clause's order. The names are the
#: contract: a consumer reads a cell by name, so a renamed field is a broken contract.
JUDGE_SIGNAL_FIELDS: tuple[str, ...] = (
    "uncited_verdict_rate",
    "evidence_sufficient_false_rate",
    "band_histogram",
    "contract_violation_rate",
    "latency",
    "prefix_cache_hit_rate",
)


def _percentile(values: Sequence[float], q: float) -> float | None:
    """The `q` percentile of a sample, linearly interpolated between the closest ranks (NumPy's
    default method). None for an empty sample."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    rank = q * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (rank - low) * (ordered[high] - ordered[low])


@dataclass(frozen=True)
class JudgeSignals:
    """One run's signals for each (criterion, judge), and the alert when violations concentrate on
    one judge.

    `cells` maps `(criterion_id, judge_id)` to a mapping carrying exactly
    `JUDGE_SIGNAL_FIELDS`. The object iterates and indexes as that mapping does — `dict(signals)`
    is the cells — so a consumer reading the contract's shape never reaches past it; `alerts`
    rides beside it.

    `latency` is a mapping of `p50_ms`/`p95_ms` over the cell's stored verdict latencies
    (`FR-JUDGE-20`).

    `prefix_cache_hit_rate` is the RUN's recorded `cache_hit_rate` metric (`M-ORCH` accrues the
    provider's `cached_prefix_tokens` and writes the row), repeated in every cell — the figure
    is not dimensioned by judge anywhere in the store, so this is the run-level rate read
    honestly rather than a per-judge one invented. `0.0` only when the run recorded no such
    row. That un-dimensioned half is this emitter's disclosed residual.
    """

    cells: Mapping[tuple[str, str], Mapping[str, Any]]
    alerts: tuple[str, ...] = ()
    #: Jev design delta FR-STATS-25 / CT-STATS-24: the same verdict signals partitioned by the
    #: engine that produced them, keyed `(criterion_id, judge_id, scoring_engine)` —
    #: `scoring_engine` is `llm` or `decision` (a pre-delta NULL reads `llm`). Additive: `cells`
    #: keeps its exact `(criterion, judge)` dimensionality (CT-JUDGE-16). A partition with no
    #: verdicts is absent, never a row of zeros. `contract_violation_rate` lands wholly in the
    #: `llm` partition: an engine's malformed or rejected response is never counted against the
    #: arm judge (FR-JUDGE-31), so every counted violation is an LLM reply's.
    by_engine: Mapping[tuple[str, str, str], Mapping[str, Any]] = field(default_factory=dict)
    #: The run's decision-engine pre-screen outcome mix, read through
    #: `aeh.judge.decision_engine_metrics` (never from `decision_prescreen` directly); `None`
    #: for a run with no pre-screens.
    decision_outcomes: Mapping[str, Any] | None = None

    def __iter__(self):
        return iter(self.cells)

    def __getitem__(self, key: tuple[str, str]) -> Mapping[str, Any]:
        return self.cells[key]

    def __len__(self) -> int:
        return len(self.cells)

    def keys(self):
        return self.cells.keys()

    def items(self):
        return self.cells.items()

    def values(self):
        return self.cells.values()


#: The alert `FR-STATS-20` names, emitted per criterion whose violations concentrate.
JUDGE_VIOLATION_ALERT = "judge_contract_violations_concentrated"


def _cohort_handle_for_run(source: Any, run_id: str, durable: Any) -> tuple[Any, Any]:
    """The cohort handle holding `run_id`, and the durable handle, from a store or a handle.

    `FR-STATS-20` names a handle; `CT-JUDGE-16` drives the emitter with the store. Both are
    accepted — a store resolves its own cohort by walking the tier's files (the no-side-index
    discovery `M-JUDGE` and `M-EXTRACT` use), and a handle is used as given. A handle carries
    no route to Tier D, where the violation counts live, so one must arrive as `durable=`:
    without it the contract-violation rate would read `0.0` for every cell and the
    concentration alert could never fire — a declared signal quietly measuring nothing.

    A run no cohort holds is a refusal, never a new handle: `store.cohort(key)` CREATES the
    tier file, so a miss that fell through to one would leave a stray database in the layout
    every cohort walk in the system then enumerates.
    """
    if not hasattr(source, "cohort"):
        if durable is None:
            raise ValueError(
                "judge_signals needs Tier D to read the judge_contract_violations rows "
                "(FR-JUDGE-21): pass the store, or the durable handle as `durable=`. A "
                "cohort handle alone would report a zero violation rate for every judge."
            )
        return source, durable
    data_dir = getattr(source, "data_dir", None)
    if data_dir is None:
        raise ValueError(
            "judge_signals was handed something that is neither a store (no data_dir) nor a "
            f"tier handle: {type(source).__name__}"
        )
    for path in sorted(Path(data_dir, "cohorts").glob("*.sqlite")):
        handle = source.cohort(path.stem)
        if handle.query(STATS_STATEMENTS["select_run_score_units"], run_id=run_id):
            return handle, (durable if durable is not None else source.durable())
    raise ValueError(
        f"no cohort ledger in {data_dir} holds score units for run {run_id!r} — judge signals "
        "are a run's, and a run the store does not hold has none"
    )


def judge_signals(source: Any, run_id: str, *, durable: Any = None) -> JudgeSignals:
    """One run's judge signals, per (criterion, judge) (FR-STATS-20, CT-JUDGE-16).

    The cells are exactly the (criterion, judge) pairs the run's ledger judged — the
    dimensionality IS the contract, because "violations concentrated on one judge" is
    locatable only from a per-judge keying. Each cell carries all six declared signals, read
    from the verdict rows (`FR-JUDGE-20`) and the `judge_contract_violations` metric rows
    (`FR-JUDGE-21`).

    The alert: a criterion with at least `HARNESS_STATS_VIOLATION_MINIMUM` violations, one of
    whose judges holds strictly more than `HARNESS_STATS_VIOLATION_CONCENTRATION` of them,
    names that judge. Ties (an even split) are not a concentration.
    """
    handle, durable = _cohort_handle_for_run(source, run_id, durable)
    pairs = [
        (str(row["criterion_id"]), str(row["judge_id"]))
        for row in handle.query(STATS_STATEMENTS["select_run_score_units"], run_id=run_id)
    ]
    verdicts: dict[tuple[str, str], list[Any]] = {pair: [] for pair in pairs}
    for row in handle.query(STATS_STATEMENTS["select_run_verdicts"], run_id=run_id):
        verdicts.setdefault((str(row["criterion_id"]), str(row["judge_id"])), []).append(row)

    violations: dict[tuple[str, str], float] = {}
    for row in durable.query(
        STATS_STATEMENTS["select_run_violation_counts"], run_id=run_id
    ):
        key = (str(row["criterion_id"]), str(row["judge_id"]))
        violations[key] = violations.get(key, 0.0) + float(row["value"])
    cache_rows = durable.query(
        STATS_STATEMENTS["select_run_cache_hit_rate"], run_id=run_id
    )
    # The run-level figure, repeated per cell: `M-ORCH` records one `cache_hit_rate` for the
    # run, and no store column dimensions it by judge (see the class docstring).
    cache_hit_rate = float(cache_rows[0]["value"]) if cache_rows else 0.0

    cells: dict[tuple[str, str], Mapping[str, Any]] = {}
    for pair in sorted(set(pairs) | set(verdicts) | set(violations)):
        rows = verdicts.get(pair, [])
        landed = len(rows)
        histogram: dict[str, int] = {}
        for row in rows:
            band_name = str(row["band"])
            histogram[band_name] = histogram.get(band_name, 0) + 1
        uncited = sum(1 for row in rows if row["uncited"])
        insufficient = sum(
            1 for row in rows if row["evidence_sufficient"] is not None
            and not row["evidence_sufficient"]
        )
        latencies = [float(row["latency_ms"]) for row in rows if row["latency_ms"] is not None]
        refused = violations.get(pair, 0.0)
        responses = landed + refused
        cells[pair] = {
            "uncited_verdict_rate": (uncited / landed) if landed else 0.0,
            "evidence_sufficient_false_rate": (insufficient / landed) if landed else 0.0,
            "band_histogram": histogram,
            # Violating responses over every response the judge returned for the cell: the
            # rate a reviewer reads as "how often this judge breaks the contract".
            "contract_violation_rate": (refused / responses) if responses else 0.0,
            "latency": {"p50_ms": _percentile(latencies, 0.50),
                        "p95_ms": _percentile(latencies, 0.95)},
            "prefix_cache_hit_rate": cache_hit_rate,
        }

    concentration = _env_float(
        STATS_VIOLATION_CONCENTRATION_ENV, STATS_VIOLATION_CONCENTRATION
    )
    minimum = _env_int(STATS_VIOLATION_MINIMUM_ENV, STATS_VIOLATION_MINIMUM)
    by_criterion: dict[str, float] = {}
    for (criterion_id, _judge), count in violations.items():
        by_criterion[criterion_id] = by_criterion.get(criterion_id, 0.0) + count
    alerts: list[str] = []
    for (criterion_id, judge_id), count in sorted(violations.items()):
        total = by_criterion.get(criterion_id, 0.0)
        if total >= minimum and count > concentration * total:
            alerts.append(f"{JUDGE_VIOLATION_ALERT}: {criterion_id} / {judge_id}")
    return JudgeSignals(cells=cells, alerts=tuple(alerts),
                        by_engine=_signals_by_engine(verdicts, cache_hit_rate, violations),
                        decision_outcomes=_decision_outcomes(handle, run_id))


def _signals_by_engine(verdicts: Mapping[tuple[str, str], list[Any]], cache_hit_rate: float,
                       violations: Mapping[tuple[str, str], float]
                       ) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    """Every judge signal per (criterion, judge, scoring engine) (FR-STATS-25)."""
    partitions: dict[tuple[str, str, str], list[Any]] = {}
    for (criterion_id, judge_id), rows in verdicts.items():
        for row in rows:
            engine = (row["scoring_engine"] if "scoring_engine" in row.keys() else None) or "llm"
            partitions.setdefault((criterion_id, judge_id, engine), []).append(row)
    for (criterion_id, judge_id), refused in violations.items():
        if refused:  # a judge that only ever broke the contract still has an llm partition
            partitions.setdefault((criterion_id, judge_id, "llm"), [])
    out: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for key in sorted(partitions):
        rows = partitions[key]
        landed = len(rows)
        refused = violations.get(key[:2], 0.0) if key[2] == "llm" else 0.0
        responses = landed + refused
        histogram: dict[str, int] = {}
        for row in rows:
            histogram[str(row["band"])] = histogram.get(str(row["band"]), 0) + 1
        latencies = [float(row["latency_ms"]) for row in rows if row["latency_ms"] is not None]
        out[key] = {
            "uncited_verdict_rate": (sum(1 for row in rows if row["uncited"]) / landed) if landed else 0.0,
            "evidence_sufficient_false_rate": (sum(
                1 for row in rows if row["evidence_sufficient"] is not None
                and not row["evidence_sufficient"]) / landed) if landed else 0.0,
            "contract_violation_rate": (refused / responses) if responses else 0.0,
            "band_histogram": histogram,
            "latency": {"p50_ms": _percentile(latencies, 0.50),
                        "p95_ms": _percentile(latencies, 0.95)},
            "prefix_cache_hit_rate": cache_hit_rate,
            "verdicts": landed,
        }
    return out


def _decision_outcomes(handle: Any, run_id: str) -> Mapping[str, Any] | None:
    """The run's decision-engine pre-screen outcomes, from M-JUDGE's metrics (CT-JUDGE-28). None
    when the run has no pre-screens."""
    import sqlite3

    from aeh.judge import decision_engine_metrics

    try:
        metrics = decision_engine_metrics(handle, run_id)
    except sqlite3.OperationalError:
        return None  # a store that predates the decision_prescreen table
    if not metrics.decision_prescreens:
        return None
    import dataclasses as _dataclasses

    return _dataclasses.asdict(metrics)  # every CT-JUDGE-28 field, equal to the source
