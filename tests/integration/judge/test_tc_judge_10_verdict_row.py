"""`TC-JUDGE-10` — the persisted verdict row: a band and its ordinal, and no points
value anywhere (`FR-JUDGE-11`, `CT-JUDGE-06`; issue #83 (TS-31)).

One judged unit through the REAL boundary (rung 2: real store, real package, real
extraction leg, `RecordedFixtureProvider`), then the verdict row is read off the live
schema. The oracle is the schema assertion: the row carries `band` AND `band_ordinal`
AND `self_confidence`, the migration-17 response columns are present, and — the case
table's emphasis — **the `verdict` table has no points column**, asserted against the
live schema (`PRAGMA table_info`), never against a fixture. No points value exists in
any column or in the row's JSON: a band's points never leave the package tier
(`FR-JUDGE-03`), and the verdict's one points mapping happens in M-AGG (`FR-AGG-02`).

The verdict identity is pinned too: `INSERT OR IGNORE` on `verdict_id = work_id` —
one row per judged unit; a double-run's second persist does not double-write.
"""

from __future__ import annotations

import json

import pytest

from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.support.conf_builders import EDGE_JUDGE
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_run import (
    CONTROL_BAND,
    JUDGE_RUN_BANDS,
    judge_world,
    verdict_columns,
    verdict_rows,
    warm_judged_modules,
)
from tests.support.judge_vocabulary import VERDICT_RESPONSE_COLUMNS
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = [pytest.mark.integration]

#: The band points the package tier declares for this world's criterion — figures the
#: judge tier must carry NONE of.
JUDGE_BAND_POINTS = {band: points for band, points, _d in JUDGE_RUN_BANDS}


def _store(tmp_data_dir):
    warm_judged_modules()
    return open_store(tmp_data_dir / "data")


def _declared_ordinals(store, criterion_id: str = "C1") -> dict[str, int]:
    """The declared band set as the package tier holds it — the ordinal's source of
    truth, read through the shipped catalog rather than copied from a fixture."""
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    return {row["band"]: int(row["ordinal"]) for row in catalog.bands(criterion_id)}


def test_tc_judge_10_a_the_persisted_row_carries_band_ordinal_and_confidence(
    tmp_data_dir, make_fixture_provider
):
    """The row a judged unit persists carries the band NAME, the band's position in
    the declared set, and the judge's own confidence — read off the live store, with
    the response columns the same migration adds present on the row."""
    store = _store(tmp_data_dir)
    provider = make_fixture_provider()
    world = judge_world(store, provider, submissions=("s-10a",), panel=1)

    (key,) = list(world["results"])
    work_id = world["score_units"][key].work_id
    rows = verdict_rows(store, work_id)
    assert len(rows) == 1, (
        f"one judged unit persists exactly one verdict row; got {len(rows)}"
    )
    row = rows[0]
    assert key[1] == EDGE_JUDGE.build_id, (
        f"precondition: the unit's judge is the real panel build ({key[1]!r})"
    )
    assert row["band"] == CONTROL_BAND
    assert row["band_ordinal"] == _declared_ordinals(store)[CONTROL_BAND]
    assert row["self_confidence"] == 0.62
    assert row["judge_id"] == EDGE_JUDGE.build_id, (
        f"the row is addressed by the judging build's own id, got "
        f"{row['judge_id']!r} for unit judge {key[1]!r}"
    )


def test_tc_judge_10_b_the_ordinal_is_the_declared_set_s_not_a_fixed_position(
    tmp_data_dir, make_fixture_provider
):
    """`band_ordinal` is the DECLARED set's ordinal (`FR-JUDGE-11`), not a row index
    or a constant: a world whose criterion declares the SAME two bands in the
    REVERSED order persists the ordinal that set gives the band — the row's number
    moves with the declaration, proving it is read from the package, not assumed."""
    store = _store(tmp_data_dir)
    provider = make_fixture_provider()
    # The same two bands renumbered — the control band FIRST this time. Points rise
    # with the new ordinals (the package tier refuses a decreasing mapping), so the
    # renumbering moves names and ordinals together, points following.
    renumbered_bands = (
        (CONTROL_BAND, 0.0, "the criterion is met"),
        ("emerging", 10.0, "the criterion is partly met"),
    )
    world = judge_world(
        store, provider, submissions=("s-10b",), panel=1, bands=renumbered_bands
    )
    declared = _declared_ordinals(store)
    # the reversal is real: the control band's declared ordinal moved to 0
    assert declared[CONTROL_BAND] == 0, (
        f"fixture bug: the reversed set did not renumber: {declared}"
    )
    for key, _result in world["results"].items():
        row = verdict_rows(store, world["score_units"][key].work_id)[0]
        assert row["band"] == CONTROL_BAND
        assert row["band_ordinal"] == declared[CONTROL_BAND], (
            f"band {row['band']!r} persisted ordinal {row['band_ordinal']}, but the "
            f"declared set says {declared[row['band']]!r}"
        )


def test_tc_judge_10_c_the_verdict_table_has_no_points_column(
    tmp_data_dir, make_fixture_provider
):
    """The case table's schema assertion, against the LIVE schema: no column of the
    `verdict` table names or carries points. The declared set's points live in the
    package tier and are looked up there (`FR-JUDGE-02`'s single mapping in M-AGG),
    never persisted onto the verdict."""
    store = _store(tmp_data_dir)
    provider = make_fixture_provider()
    judge_world(store, provider, submissions=("s-10c",), panel=1)
    columns = verdict_columns(store)
    offenders = [
        name for name in columns if "point" in name.lower() or "score_value" in name
    ]
    assert not offenders, (
        f"the verdict table carries points-shaped column(s) {offenders} — a verdict "
        f"persists a band and its ordinal, never a points value (FR-JUDGE-11)"
    )
    assert "band" in columns and "band_ordinal" in columns, (
        f"the columns the case pins are missing: {columns}"
    )


def test_tc_judge_10_d_the_migration_17_response_columns_are_on_the_live_schema(
    tmp_data_dir, make_fixture_provider
):
    """The migration-17 columns the verdict row must carry (`CT-JUDGE-06`), asserted
    against the live schema: `cited_spans`, `evidence_sufficient`, `uncited`."""
    store = _store(tmp_data_dir)
    provider = make_fixture_provider()
    judge_world(store, provider, submissions=("s-10d",), panel=1)
    columns = verdict_columns(store)
    missing = [name for name in VERDICT_RESPONSE_COLUMNS if name not in columns]
    assert not missing, (
        f"the migration-17 response columns {missing} are missing from the live "
        f"verdict table: {columns}"
    )


def test_tc_judge_10_e_no_points_value_in_any_verdict_row_or_its_json(
    tmp_data_dir, make_fixture_provider
):
    """Beyond the schema: the row's full column set carries no points-shaped field,
    and the row's JSON payload (`cited_spans`) names no points value — the spans are
    byte coordinates, the band a name, the numbers an ordinal and a confidence."""
    store = _store(tmp_data_dir)
    provider = make_fixture_provider()
    world = judge_world(store, provider, submissions=("s-10e",), panel=1)
    rows = store.cohort(ORCH_COHORT_ID).query(
        "SELECT * FROM verdict"
    )
    assert rows, "precondition: the world persisted at least one verdict row"
    columns = verdict_columns(store)
    offenders = [name for name in columns if "point" in name.lower()]
    assert not offenders
    for row in rows:
        assert row["band"] in JUDGE_BAND_POINTS, (
            f"the row's band {row['band']!r} is not a declared band name"
        )
        if row["cited_spans"] is not None:
            value = row["cited_spans"]
            spans = json.loads(
                value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else value
            )
            for span in spans:
                assert not any("point" in key for key in span), (
                    f"a points value leaked into the row's span JSON: {span!r}"
                )


def test_tc_judge_10_f_one_row_per_judged_unit_and_the_identity_is_the_work_id(
    tmp_data_dir, make_fixture_provider
):
    """The verdict row's identity is `verdict_id = work_id` (`INSERT OR IGNORE`): a
    second `persist` of the same result does not double-write — the at-least-once
    contract's other half, asserted at the row count."""
    store = _store(tmp_data_dir)
    provider = make_fixture_provider()
    world = judge_world(store, provider, submissions=("s-10f",), panel=1)
    key = next(iter(world["results"]))
    result = world["results"][key]
    unit = world["score_units"][key]
    ScoringWorker = require(JUDGE_MODULE, "ScoringWorker", issue="#78")
    worker = ScoringWorker(store, provider, world["judges"][key[1]])
    worker.persist(unit, result)  # the double-run's write

    rows = verdict_rows(store, unit.work_id)
    assert len(rows) == 1, (
        f"a double persist doubled the verdict rows ({len(rows)}) — the INSERT OR "
        f"IGNORE identity is broken"
    )
    assert rows[0]["verdict_id"] == unit.work_id