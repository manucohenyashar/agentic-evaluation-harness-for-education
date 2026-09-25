"""`TC-EXTRACT-C16` and `TC-EXTRACT-C17` — the taxonomy safety property and the metric field
set (§6.11.3, `CT-EXTRACT-16/17`).

| Case | Clause | The violation it catches |
|---|---|---|
| `C16` | a taxonomy error consumes no strike | "simplify" the worker to `except ProviderError as e: self._strike(unit, e); raise` |
| `C17` | `extraction_metrics`' key set is the declared five | a key renamed, or `None` replaced by `0.0` for a second family that never ran |

**C16 is a safety property**, and §8.3 names the construction that defeats every other case:
the tidy-up above keeps the exception propagating — so `TC-ORCH-43`'s pause assertion still
passes — and restores the strike. Three of those quarantine a unit whose only problem was a
20-minute provider outage at 02:00, and the morning shows a cohort full of "could not be
scored" instead of a paused run (RISK-44). **The `attempts` assertion is the only thing that
catches it**, which is why this case exists separately from the pause case.

**C17's `None` is the half that rots.** `second_family_disagreement_rate` is `None` where no
second family ran, and a `0.0` there claims agreement nobody measured — a figure a reader
cannot distinguish from a real measurement of perfect agreement. Absence and zero are
different facts, and the metric surface is where they get conflated first.

**Isolation: rung 1 for the taxonomy arms, rung 2 for the metric set.**
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
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
from aeh.extract import ExtractionMetrics, extraction_metrics
from aeh.prov import BuildChangedError, ProviderUnavailableError, RateLimitedError
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_documents, seed_run

pytestmark = [pytest.mark.contract, pytest.mark.integration]

SUBMISSION = "S01"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

#: `CT-EXTRACT-17`'s declared key set, verbatim.
DECLARED_METRIC_FIELDS = {
    "spans_per_unit",
    "empty_result_rate",
    "second_family_disagreement_rate",
    "extraction_latency_p50_ms",
    "extraction_latency_p95_ms",
}

#: The taxonomy conditions that are the PROVIDER's, never the unit's.
TAXONOMY = (
    ProviderUnavailableError("the endpoint is gone"),
    BuildChangedError("answering as a different build"),
    RateLimitedError("retry-after: 0"),
)

_UNITS = Statement(
    "SELECT status, attempts FROM work_unit WHERE run_id = :r AND stage = 'extract'"
)


class _StubProvider:
    def estimate_cost(self, unit: Any) -> None:  # noqa: ARG002 — the seam's shape
        return None

    def complete(self, payload: Any, model_ref: Any = None, params: Any = None) -> Any:
        raise AssertionError("this suite's executor answers without a model call")


# --- TC-EXTRACT-C16 ------------------------------------------------------------------------------


@pytest.mark.parametrize("error", TAXONOMY, ids=lambda e: type(e).__name__)
def test_tc_extract_c16_a_taxonomy_error_consumes_no_strike(tmp_data_dir, error):
    """After a taxonomy error the unit's `attempts` is unchanged and nothing is quarantined.

    All three conditions, because they take different routes through the dispatch loop — two
    pause the run and one requeues at a reduced width — and the clause is the same for all of
    them: a provider's condition is not the unit's failure. An implementation that guarded
    only the pausing pair would still strike on every rate limit, and a throttled afternoon
    would quarantine work that was never attempted.
    """
    from aeh.orch import Orchestrator, StageOutcome

    class _RaisingExecutor:
        def execute(self, unit: Any, governed: Any) -> StageOutcome:  # noqa: ARG002
            raise error

    store = open_store(tmp_data_dir)
    try:
        seeder, run_id, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        seed_documents(store, (SUBMISSION,))
        seeder.enumerate_units(run_id)
        probe = Orchestrator(
            store, executor=_RaisingExecutor(), provider=_StubProvider()
        )
        probe.start(run_id)

        probe.progress(run_id)

        units = [dict(row) for row in store.cohort(ORCH_COHORT_ID).query(_UNITS, r=run_id)]
        assert units, "the run enumerated no extract unit, so the property is untested"
        for unit in units:
            assert unit["attempts"] == 0, (
                f"a {type(error).__name__} charged {unit['attempts']} attempt(s) to the unit. "
                "§8.3's tidy-up — `except ProviderError as e: self._strike(unit, e); raise` — "
                "keeps the pause and restores the strike, so TC-ORCH-43's pause assertion "
                "still passes and only this one goes red (RISK-44)"
            )
            assert unit["status"] != "quarantined", (
                f"a {type(error).__name__} quarantined the unit. A 20-minute outage would "
                "quarantine every unit in flight, and the morning shows 'could not be scored' "
                "for work nobody looked at"
            )
    finally:
        store.close()


def test_tc_extract_c16_a_units_own_failure_does_consume_a_strike(tmp_data_dir):
    """The positive control: a worker that strikes the unit within its own budget does count.

    Without it, "attempts is 0" passes against a ledger that never counts an attempt at all —
    and the strike ladder that quarantines a genuinely broken unit would never fire.
    """
    from aeh.orch import Orchestrator

    store = open_store(tmp_data_dir)
    try:
        seeder, run_id, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        seed_documents(store, (SUBMISSION,))
        seeder.enumerate_units(run_id)
        probe = Orchestrator(store)
        probe.start(run_id)
        claimed = probe.lease("w-strike", "extract", 1)
        assert claimed, "nothing was claimable, so the control proves nothing"

        probe.fail(claimed[0].work_id, "the unit's own failure")

        units = [dict(row) for row in store.cohort(ORCH_COHORT_ID).query(_UNITS, r=run_id)]
        assert any(unit["attempts"] >= 1 for unit in units), (
            f"a unit-level failure counted no attempt: {units}. The strike ladder that "
            "quarantines a genuinely broken unit would then never fire"
        )
    finally:
        store.close()


# --- TC-EXTRACT-C17 ------------------------------------------------------------------------------


def test_tc_extract_c17_the_metric_field_set_is_exactly_the_declared_five():
    """`ExtractionMetrics`' fields equal the five declared names — equality, not containment.

    Asserted on the dataclass rather than on an instance, so an empty run cannot make the set
    look right by carrying nothing. A sixth field is a contract bump; a renamed one is every
    consumer reading `None` for a signal that is still being measured.
    """
    fields = {field.name for field in dataclasses.fields(ExtractionMetrics)}

    assert fields == DECLARED_METRIC_FIELDS, (
        f"ExtractionMetrics carries {sorted(fields)}; the contract names "
        f"{sorted(DECLARED_METRIC_FIELDS)} (CT-EXTRACT-17)"
    )


def test_tc_extract_c17_a_second_family_that_never_ran_reads_none_not_zero(tmp_data_dir):
    """`second_family_disagreement_rate` is `None` where no second family ran.

    The half that rots. A `0.0` there claims perfect agreement — a figure a reader cannot tell
    apart from a real measurement — about a comparison nobody performed. Absence and zero are
    different facts, and a metric surface is where they get conflated first.
    """
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_id, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        metrics = extraction_metrics(store.cohort(ORCH_COHORT_ID), run_id)
    finally:
        store.close()

    rates = metrics.second_family_disagreement_rate
    assert all(value is None for value in rates.values()), (
        f"a run with no second-family extraction reports {rates}. `None` is 'not measured'; "
        "a 0.0 claims agreement nobody measured (FR-EXTRACT-07, CT-EXTRACT-10)"
    )


def test_tc_extract_c17_every_declared_field_is_a_mapping_keyed_by_criterion(tmp_data_dir):
    """Each field is per-criterion, not a run-level scalar.

    The dimensionality is the contract: "extraction is failing" sends an operator nowhere,
    and "extraction is failing on C3" sends them to the criterion. A field collapsed to a
    scalar keeps the name and loses the only thing that makes it actionable.
    """
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_id, _version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        metrics = extraction_metrics(store.cohort(ORCH_COHORT_ID), run_id)
    finally:
        store.close()

    for name in sorted(DECLARED_METRIC_FIELDS):
        value = getattr(metrics, name)
        assert hasattr(value, "keys"), (
            f"{name} is a {type(value).__name__}, not a mapping keyed by criterion. "
            "'extraction is failing' sends an operator nowhere; 'failing on C3' sends them to "
            "the criterion (CT-EXTRACT-17)"
        )
