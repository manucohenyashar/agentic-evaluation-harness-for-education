"""`TC-JUDGE-C06` — the persisted verdict's shape and its null handling (§6.11.10).

`CT-JUDGE-06` (data): *"Assert a persisted `verdict` carries `band` and
`band_ordinal` and **no points value**, and that the `verdict` table has **no points
column** — a schema assertion, so re-adding one fails the build rather than review.
Assert `evidence_sufficient` and `self_confidence` are **always present**. Then the
null-handling distinction: `cited_spans` may be null, and a null is **persisted as
uncited and marked**, never discarded — assert the row exists and is marked, since
dropping it would erase the uncited-verdict rate that `CT-JUDGE-16` alerts on."*
(plan §6.11.10, verbatim)

The three steps, as implemented here:

1. **the schema assertion** — the live SQLite DDL (`PRAGMA table_info(verdict)` on
   the real cohort file) is set-equal to the nine declared columns, so re-adding a
   points column fails the build rather than review; the three response columns
   #80's migration adds (`judge_vocabulary.VERDICT_RESPONSE_COLUMNS`) are all
   present;
2. **the persisted values** — over a judged drive, every row carries `band` with
   its declared `band_ordinal`, and `evidence_sufficient` and `self_confidence`
   are always present; the ordinal is the band's POSITION and never its points
   value (the fixture's ordinals 0/1 and points 2.0/4.0 differ, so persisting
   points under the ordinal's name is caught);
3. **the null-handling distinction** — an uncited reply persists: the row EXISTS,
   `cited_spans` IS NULL, `uncited` is 1 — persisted as uncited and MARKED, never
   discarded, because dropping it would erase the uncited-verdict rate
   `CT-JUDGE-16` alerts on; while a cited reply's row carries its spans and
   `uncited` = 0.

Cross-references, not duplicates: `TC-STORE-04`'s golden migrates prior versions to
this shape (its concern is the migration path, not the clause's column set);
`TC-AGG-C02` reads these columns as the aggregate consumer — this file is the
producer-side contract the consumer reads through. The rows' band membership is
`TC-JUDGE-C04`'s consumer-right assertion; the ordinal-beside-band shape asserted
here is the row's.

Isolation: rung 0 for the schema half (a fresh store, no drive); rung 2 for the
persisted-state halves (real workers over the recorded fixture provider).
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.contract.judge._drive import (
    PANEL_REFS,
    drive_judged_run,
    spans,
    verdict_rows,
)
from tests.support.extract_vocabulary import verdict_completion
from tests.support.orch_run import ORCH_COHORT_ID
from tests.support.judge_vocabulary import VERDICT_RESPONSE_COLUMNS

pytestmark = [pytest.mark.contract]

#: The story that owns the verdict schema (`M-JUDGE` is complete — #78/#79/#80/#81).
ISSUE = "#78"

#: The verdict table's declared columns, in DDL order — the equality target, read
#: from the live schema and pinned here as the clause's declared shape. A tenth
#: column (a points column among them) fails the build, not review.
DECLARED_VERDICT_COLUMNS: tuple[str, ...] = (
    "verdict_id",
    "work_id",
    "judge_id",
    "band",
    "band_ordinal",
    "self_confidence",
    "cited_spans",
    "evidence_sufficient",
    "uncited",
)


def _table_columns(store: Any, table: str) -> list[str]:
    """The live table's column names, in DDL order, from the real cohort file."""
    handle = store.cohort(ORCH_COHORT_ID)
    return [row["name"] for row in handle.query(f"PRAGMA table_info({table})")]


def test_tc_judge_c06_the_verdict_table_has_exactly_the_declared_columns(
    tmp_data_dir,
):
    """`TC-JUDGE-C06` step 1 (`CT-JUDGE-06`, schema assertion, rung 0, P0) — the live
    `verdict` table's columns are set-equal to the nine declared names: no points
    column exists, and the three response columns #80's migration adds are all
    present. Set equality, not a subset check — an addition fails here, at the
    build, not in review."""
    store = open_store(tmp_data_dir)
    try:
        columns = _table_columns(store, "verdict")
        assert set(columns) == set(DECLARED_VERDICT_COLUMNS), (
            f"the verdict table's columns are {columns}, the declared shape is "
            f"{list(DECLARED_VERDICT_COLUMNS)} — a schema assertion, so re-adding a "
            "column (a points column among them) fails the build rather than review "
            "(CT-JUDGE-06)"
        )
        assert not any("points" in name for name in columns), (
            f"the verdict table carries a points column: "
            f"{[n for n in columns if 'points' in n]} — a verdict carries band and "
            "band_ordinal, and no points value ever persists (CT-JUDGE-06)"
        )
        missing = [name for name in VERDICT_RESPONSE_COLUMNS if name not in columns]
        assert missing == [], (
            f"the response columns {missing} are absent from the live table — #80's "
            "migration did not land where the vocabulary declares it (CT-JUDGE-06)"
        )
    finally:
        store.close()


def test_tc_judge_c06_every_persisted_row_carries_the_verdict_fields(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C06` step 2 (`CT-JUDGE-06`, exact persisted state, rung 2, P0) — over
    a judged drive across the full panel, every row carries `band` with its declared
    `band_ordinal`, and `evidence_sufficient` and `self_confidence` are always
    present; and the persisted ordinal is the band's POSITION, never its points
    value."""
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        _orchestrator, run_id, version = drive_judged_run(
            store, provider,
            criterion_specs=[{
                "criterion_id": "C1", "kind": "open", "scoring_model": "holistic",
                "band_count": 2,
            }],
        )
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        declared = {
            row["band"]: (int(row["ordinal"]), float(row["points"]))
            for row in catalog.bands("C1")
        }
        rows = verdict_rows(store, run_id, "SYN-001", "C1")
        assert len(rows) == 3, (
            f"fixture bug: the judged drive persisted {len(rows)} rows for the pair "
            "— the three-judge panel's rows are the sweep below"
        )
        for row in rows:
            for field in ("band", "band_ordinal", "self_confidence",
                          "evidence_sufficient"):
                assert row[field] is not None, (
                    f"verdict {row['verdict_id'][:12]} persists {field} = NULL — "
                    "band, band_ordinal, self_confidence and evidence_sufficient "
                    "are always present on a persisted verdict (CT-JUDGE-06)"
                )
            ordinal, points = declared[row["band"]]
            assert row["band_ordinal"] == ordinal, (
                f"verdict {row['verdict_id'][:12]} carries band_ordinal "
                f"{row['band_ordinal']} for band {row['band']!r}, whose declared "
                f"ordinal is {ordinal} — the ordinal rides beside its band "
                "(CT-JUDGE-06, CT-JUDGE-04)"
            )
            assert row["band_ordinal"] != points, (
                f"verdict {row['verdict_id'][:12]} persisted a points value "
                f"({points}) where the ordinal belongs — a persisted verdict "
                "carries band and band_ordinal, and no points value (CT-JUDGE-06, "
                "FR-JUDGE-11)"
            )
    finally:
        store.close()


def test_tc_judge_c06_a_null_citation_is_persisted_as_uncited_and_marked(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C06` step 3 (`CT-JUDGE-06`, the null-handling distinction, rung 2,
    P0) — `cited_spans` may be null, and a null is persisted as uncited and
    MARKED, never discarded: the row exists (dropping it would erase the
    uncited-verdict rate `CT-JUDGE-16` alerts on), with the verdict fields it does
    carry still present; the cited control row carries its spans and `uncited` = 0."""
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()

        def completion_for(unit: Any, judge_ref: Any) -> Any:
            """`C1`'s verdict cites the transcript; `C2`'s reply is uncited — so one
            drive carries both the cited and the null-citation row shapes."""
            from tests.support.extract_vocabulary import verdict_completion as vc

            return vc(
                "secure", 0.9,
                build_id="build-judge-contract",
                cited_spans=spans() if unit.criterion_id == "C1" else None,
            )

        _orchestrator, run_id, _version = drive_judged_run(
            store, provider,
            criterion_specs=[
                {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
                 "band_count": 2},
                {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic",
                 "band_count": 2},
            ],
            completion_for=completion_for,
        )
        cited_rows = verdict_rows(store, run_id, "SYN-001", "C1")
        uncited_rows = verdict_rows(store, run_id, "SYN-001", "C2")
        assert len(cited_rows) == 1 and len(uncited_rows) == 1, (
            "fixture bug: the drive's rows split "
            f"{len(cited_rows)} cited / {len(uncited_rows)} uncited — the "
            "null-handling limb needs both"
        )
        for row in uncited_rows:
            assert row["uncited"] == 1, (
                f"the uncited verdict {row['verdict_id'][:12]} is not marked "
                f"(uncited={row['uncited']}) — a null citation is persisted as "
                "uncited and MARKED (CT-JUDGE-06)"
            )
            assert row["cited_spans"] is None, (
                f"uncited verdict {row['verdict_id'][:12]} carries a non-null "
                "cited_spans — a null citation is persisted AS NULL (CT-JUDGE-06)"
            )
            for field in ("band", "band_ordinal", "self_confidence",
                          "evidence_sufficient"):
                assert row[field] is not None, (
                    f"uncited verdict {row['verdict_id'][:12]} lost {field} — the "
                    "row is persisted as uncited and MARKED, with its verdict "
                    "fields intact, never discarded (CT-JUDGE-06)"
                )
        for row in cited_rows:
            assert row["cited_spans"] is not None and row["uncited"] == 0, (
                f"cited verdict {row['verdict_id'][:12]} does not carry its "
                "spans — the cited control must carry the spans it declared "
                "(CT-JUDGE-06)"
            )
        # Nothing was discarded: every judged score unit's verdict row exists.
        score_units = store.cohort(ORCH_COHORT_ID).query(
            "SELECT work_id, criterion_id FROM work_unit WHERE run_id = :r AND "
            "submission_id = :s AND stage = 'score'",
            r=run_id, s="SYN-001",
        )
        rows_by_criterion = {"C1": cited_rows, "C2": uncited_rows}
        for unit_row in score_units:
            expected = rows_by_criterion[unit_row["criterion_id"]]
            assert any(
                row["work_id"] == unit_row["work_id"] for row in expected
            ), (
                f"score unit {unit_row['work_id'][:12]} "
                f"({unit_row['criterion_id']}) has no verdict row — an uncited "
                "verdict that is discarded instead of marked erases the "
                "uncited-verdict rate CT-JUDGE-16 alerts on (CT-JUDGE-06)"
            )
    finally:
        store.close()