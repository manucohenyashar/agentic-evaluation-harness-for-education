"""`OBS-13` (issue #393, TS-99) — the three signal emitters each carry exactly their declared
literal key sets, over the composed run of `TC-PIPE-01` (`CT-EXTRACT-17`, `CT-AGG-21`,
`CT-STATS-22`).

The names ARE the contract: a consumer reads a signal by name (`extraction_metrics.spans_per_unit`,
`aggregation_signals.caps_fired`, a judge-signal cell's `contract_violation_rate`), so a renamed
field is a broken contract that never raises — the consumer silently reads `None`/misses forever.
Each clause declares its literal list, and the literals are written HERE, not imported from the
emitters, so the test fails when the emitter renames a key even though the emitter and its own
tests agree with each other. The clause is held against the objects the shipped emitters actually
return on a real composed drive — not against the dataclasses in isolation.
"""

import dataclasses

import pytest

from aeh.agg.metrics import AggregationSignals, aggregation_signals
from aeh.agg.settings import AGG_CAP_TABLE
from aeh.extract.metrics import ExtractionMetrics, extraction_metrics
from aeh.stats.judge_signals import (
    JUDGE_SIGNAL_FIELDS,
    JUDGE_VIOLATION_ALERT,
    judge_signals,
)
from aeh.store import open_store
from tests.support import pipe_world
from tests.support.judge_vocabulary import JUDGE_SIGNAL_FIELDS as VOCABULARY_JUDGE_FIELDS

pytestmark = pytest.mark.integration

# The declared literals (detailed-design §FR-EXTRACT-12 / §FR-AGG-17 / §FR-STATS-20). A rename
# on the emitter side fails here, because these names no longer match `dataclasses.fields`.
EXTRACTION_METRIC_NAMES = (
    "spans_per_unit",
    "empty_result_rate",
    "second_family_disagreement_rate",
    "extraction_latency_p50_ms",
    "extraction_latency_p95_ms",
)
AGGREGATION_SIGNAL_NAMES = (
    "band_histogram",
    "band_spread_distribution",
    "agreement_distribution",
    "escalation_rate",
    "auto_accept_rate",
    "caps_fired",
)
JUDGE_SIGNAL_NAMES = (
    "uncited_verdict_rate",
    "evidence_sufficient_false_rate",
    "band_histogram",
    "contract_violation_rate",
    "latency",
    "prefix_cache_hit_rate",
)
JUDGE_CONCENTRATION_ALERT = "judge_contract_violations_concentrated"


@pytest.fixture(scope="module")
def composed_run(tmp_path_factory):
    """One composed F-DEV-PIPE drive — the same shape TC-PIPE-11's `uninterrupted` fixture runs —
    yielding the data directory and run id the emitters are read against."""
    root = tmp_path_factory.mktemp("obs13-composed") / "w"
    mp = pytest.MonkeyPatch()
    try:
        world = pipe_world.replay_world(root, monkeypatch=mp)
        world.build_run()
        world.start_run()
        try:
            result = pipe_world.drive_composed(world)
        finally:
            world.store.close()
        assert result.status == "complete", f"fixture: composed run {result.status}"
        return root, world.run_id
    finally:
        mp.undo()


def test_obs_13_signal_emitters_carry_their_declared_key_sets(composed_run):
    root, run_id = composed_run
    store = open_store(root)
    try:
        handle = store.cohort(pipe_world.PIPE_COHORT_ID)

        extraction = extraction_metrics(handle, run_id)
        assert tuple(f.name for f in dataclasses.fields(ExtractionMetrics)) == (
            EXTRACTION_METRIC_NAMES
        ), "extraction_metrics key set drifted from CT-EXTRACT-17's literal list"
        assert extraction.spans_per_unit, "fixture: no extraction signal was emitted at all"

        aggregation = aggregation_signals(handle, run_id)
        field_names = tuple(f.name for f in dataclasses.fields(AggregationSignals))
        assert field_names == AGGREGATION_SIGNAL_NAMES, (
            f"aggregation_signals key set drifted from CT-AGG-21's literal list: {field_names}"
        )
        assert aggregation.band_histogram, "fixture: no aggregation signal was emitted at all"
        # `caps_fired.<cap>` per criterion (CT-AGG-15): every cap name a run fires is one of
        # M-AGG's registered caps, counted per criterion — never one run-wide total.
        for criterion_id, fired in aggregation.caps_fired.items():
            unknown = set(fired) - set(AGG_CAP_TABLE)
            assert not unknown, (
                f"caps_fired[{criterion_id!r}] names caps outside M-AGG's registry: {sorted(unknown)}"
            )
            for name, count in fired.items():
                assert isinstance(count, int), (
                    f"caps_fired[{criterion_id!r}][{name!r}] is {type(count).__name__}, "
                    "not a per-criterion count"
                )

        # CT-STATS-22: the judge vocabulary and the emitter declare the SAME six names, and
        # every cell the composed run emitted carries exactly that key set.
        assert tuple(JUDGE_SIGNAL_NAMES) == tuple(VOCABULARY_JUDGE_FIELDS), (
            "the declared judge-signal names and tests/support/judge_vocabulary.py disagree"
        )
        assert tuple(JUDGE_SIGNAL_FIELDS) == tuple(JUDGE_SIGNAL_NAMES), (
            "aeh.stats.judge_signals' field list drifted from CT-STATS-22's literal list"
        )
        signals = judge_signals(store, run_id)
        assert len(signals) > 0, "fixture: the composed run emitted no judge-signal cells"
        for cell_key, cell in signals.items():
            assert set(cell) == set(JUDGE_SIGNAL_NAMES), (
                f"judge-signal cell {cell_key!r} carries {sorted(cell)}, not the declared six"
            )
        assert JUDGE_VIOLATION_ALERT == JUDGE_CONCENTRATION_ALERT, (
            f"the concentration alert's name drifted: {JUDGE_VIOLATION_ALERT!r}"
        )
    finally:
        store.close()