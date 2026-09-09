"""`TC-AGG-04` — an even panel is a failed write at the `criterion_score` CHECK
constraint, never a rounded verdict, and the module refuses it independently.

Test plan §5.12 (row form), issue #94 (TS-35). Traces to `FR-AGG-03`; RISK-18's DB
half. `judge_count` swept over 0..5: 0, 1, 3 and 5 accepted; 2 and 4 rejected — as a
failed write, not a rounded verdict. The oracle asserts **both** halves independently:

- **The database constraint** is asserted against the shipped schema. The CHECK
  (`judge_count = 0 OR judge_count % 2 = 1`) landed with M-DET's score-state migration
  (det migration v9, CT-STORE-13: "the odd-judge_count CHECK is actually enforced, which
  is what makes CT-AGG-03 a failed write rather than a convention"), so this half is
  **not written ahead** — it runs in `TEST_CMD` today and stands guard on the constraint
  M-AGG's rows will have to satisfy.
- **The module refusal** landed at #91 (unmarked there; test plan §8.2): `aggregate`
  refuses an even panel before any write is attempted, raising the exact exception the
  vocabulary pinned as `EvenPanelError` — the assumed name shipped as declared.

Isolation: rung 2 — real store, real migrations, real SQLite constraint enforcement; no
doubles. The submission row the FK needs is INSERTed directly (the `orch_run.py`
disclosed-bypass precedent): `M-INGEST` is not under test here.
"""

from __future__ import annotations

import pytest

from aeh.store import open_store
import aeh.det  # noqa: F401 — registers the score-state migration carrying the CHECK
from tests.support.agg_vocabulary import AGG_BLOCKER, band, criterion, favourable_signals, panel
from tests.support.impl import AGG_MODULE, require

_COHORT = "c-agg-04"

#: The full sweep the case names, split by expected outcome.
_ACCEPTED = (0, 1, 3, 5)
_REJECTED = (2, 4)


def _seed_submission(cohort) -> None:
    with cohort.transaction() as tx:
        tx.execute(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES (:c, 'synthetic', '2026-01-01T00:00:00Z')",
            c=_COHORT,
        )
        tx.execute(
            "INSERT INTO submission (submission_id, cohort_id, student_ref) "
            "VALUES ('s-agg-04', :c, 'r-1')",
            c=_COHORT,
        )


def test_tc_agg_04_the_schema_itself_refuses_an_even_panel_as_a_failed_write(tmp_data_dir):
    """`TC-AGG-04` DB half (`FR-AGG-03`, integration / rung 2, negative, P0) — the
    `criterion_score` CHECK admits judge_count 0, 1, 3 and 5 and rejects 2 and 4 with an
    IntegrityError, and the refusal is the odd-judge_count CHECK itself, not some other
    constraint."""
    store = open_store(tmp_data_dir)
    cohort = store.cohort(_COHORT)
    _seed_submission(cohort)

    # The constraint exists, on the shipped table, in the form the design declares —
    # asserted directly so a refusal by some *other* constraint cannot masquerade as
    # this case passing.
    stored_sql = cohort.query(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='criterion_score'"
    )[0]["sql"]
    assert "judge_count = 0 OR judge_count % 2 = 1" in stored_sql, (
        "the criterion_score table does not carry the odd-judge_count CHECK — CT-AGG-03 "
        "makes the even-panel refusal a failed write only if the constraint is actually "
        "enforced (FR-AGG-03, CT-STORE-13)"
    )

    with cohort.transaction() as tx:
        for judge_count in _REJECTED:
            with pytest.raises(Exception) as refused:
                tx.execute(
                    "INSERT INTO criterion_score (submission_id, criterion_id, band, "
                    "points, judge_count, agreement) VALUES ('s-agg-04', :cid, 'B1', "
                    "1.0, :jc, 0.5)",
                    cid=f"C-EVEN-{judge_count}", jc=judge_count,
                )
            assert type(refused.value).__name__ == "IntegrityError", (
                f"judge_count={judge_count} was refused by "
                f"{type(refused.value).__name__!r} — an even panel must be a failed "
                "write at the CHECK constraint, not a rounded verdict (FR-AGG-03)"
            )

        for judge_count in _ACCEPTED:
            tx.execute(
                "INSERT INTO criterion_score (submission_id, criterion_id, band, "
                "points, judge_count, agreement) VALUES ('s-agg-04', :cid, 'B1', "
                "1.0, :jc, NULL)",
                cid=f"C-ODD-{judge_count}", jc=judge_count,
            )

    stored = cohort.query(
        "SELECT judge_count FROM criterion_score ORDER BY judge_count"
    )
    assert [row["judge_count"] for row in stored] == list(_ACCEPTED), (
        "the admitted judge_counts are not exactly the 0-or-odd set — the CHECK must "
        "admit 0, 1, 3 and 5 (FR-AGG-03: 0 is the deterministic criterion's shape)"
    )


def test_tc_agg_04_the_module_refuses_an_even_panel_before_any_write():
    """`TC-AGG-04` module half (`FR-AGG-03`, unit refusal asserted at the integration
    tier's case, landed at #91) — `aggregate` itself refuses an even panel with
    the pinned exact exception; the database never sees an even panel from this module
    because the refusal happens first, in the pure layer."""
    aggregate = require(AGG_MODULE, "aggregate", issue=AGG_BLOCKER)
    even_panel_error = require(AGG_MODULE, "EvenPanelError", issue=AGG_BLOCKER)

    crit = criterion(
        [band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0), band("B3", 3, 6.0)]
    )

    for even in (
        panel(("B0", 0), ("B1", 1)),
        panel(("B0", 0), ("B1", 1), ("B2", 2), ("B3", 3)),
    ):
        with pytest.raises(even_panel_error) as refused:
            aggregate(even, crit, favourable_signals())
        assert type(refused.value).__name__ == "EvenPanelError", (
            f"an even panel of {len(even)} raised {type(refused.value).__name__!r} — "
            "the exact-exception oracle pins EvenPanelError (assumed name, reconciles "
            "at #91; FR-AGG-03)"
        )
