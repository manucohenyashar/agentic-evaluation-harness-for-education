"""`TC-EXTRACT-06` — a package containing deterministic criteria generates ZERO
extraction work for them.
Test plan §5.8; `FR-EXTRACT-06`.

Oracle — **exact enumeration**: over a MIXED package (one deterministic criterion, two
open ones, one depending on the other) and two submissions, every unit the enumeration
writes is accounted for per (submission, criterion):

- the deterministic criterion appears under `deterministic` exactly once per submission
  and under `extract` exactly ZERO times — no extract unit, no score arm, nothing;
- each open criterion appears under `extract` exactly once per submission (and its score
  arms are the only other rows it generates);
- the two stages together cover every (submission, criterion) pair in the package
  exactly once — the accounting is exhaustive, so "zero extraction work" cannot be
  satisfied by dropping the criterion from the run altogether.

`TC-ORCH-10` (`tests/integration/orch/test_deterministic_enumeration.py`) already
asserts the whole-package negative (an mcq-only package enumerates no extraction unit
anywhere); this case is the per-criterion complement the plan asks for: the MIXED
package, where the extractor must stay silent for one criterion while working on its
neighbours.

**Disclosed stand-ins.** "Deterministic" is spelled `kind="mcq"` — the shipped
`M-ORCH` enumeration's discriminator (`src/aeh/orch.py`, the `enumerate_units` loop);
no `evaluation_mode` column exists in the shipped package DDL, so this is the concrete
form the bet on #57 takes, same as `TC-ORCH-10`.

**Isolation: rung 2** — real store, real Tier P package, real cohort ledger; no model
boundary is crossed (the case is about what is enumerated, not what is called; the
autouse `network_guard` makes a call a defect).
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.orch import STAGE_DETERMINISTIC, STAGE_EXTRACT, STAGE_SCORE, Orchestrator
from aeh.store import open_store
from tests.support.conf_builders import edge_cfg, edge_panel
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package

pytestmark = pytest.mark.integration

#: The mixed package: the deterministic criterion C1 sits between two open ones, one of
#: which depends on the other, so the extractor works neighbours while staying silent
#: for C1.
_CRITERIA = (
    {"criterion_id": "C1", "kind": "mcq"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C4", "kind": "open", "scoring_model": "holistic",
     "dependencies": ("C2",)},
)

_SUBMISSIONS = ("SYN-001", "SYN-002")


def _units(store: Any, run_id: str) -> list[Any]:
    return store.cohort(ORCH_COHORT_ID).query(
        "SELECT stage, submission_id, criterion_id, judge_id FROM work_unit "
        "WHERE run_id = :r ORDER BY stage, submission_id, criterion_id, judge_id",
        r=run_id,
    )


def _count(rows: list[Any], stage: str, submission_id: str, criterion_id: str) -> int:
    return sum(
        1 for row in rows
        if row["stage"] == stage
        and row["submission_id"] == submission_id
        and row["criterion_id"] == criterion_id
    )


def test_tc_extract_06_zero_extraction_work_for_deterministic_criteria(tmp_data_dir):
    """`TC-EXTRACT-06` — the exact enumeration: zero extract rows for the deterministic
    criterion, one extract row per (submission, open criterion), and a full accounting
    across both stages."""
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, _SUBMISSIONS)
        version = seed_package(store, _CRITERIA)
        orchestrator = Orchestrator(store)
        resolved = resolve_run_config(
            edge_cfg(panel=edge_panel(3)),
            CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
        )
        run_id = orchestrator.create_run(ORCH_COHORT_ID, version, resolved)
        orchestrator.enumerate_units(run_id)
        rows = _units(store, run_id)
        assert rows, "precondition: the enumeration wrote no units"

        for submission_id in _SUBMISSIONS:
            # The deterministic criterion: exactly one deterministic unit, ZERO extract
            # units, and no score arms either.
            assert _count(rows, STAGE_DETERMINISTIC, submission_id, "C1") == 1, (
                f"{submission_id}: the mcq criterion must enumerate exactly one "
                f"deterministic unit"
            )
            assert _count(rows, STAGE_EXTRACT, submission_id, "C1") == 0, (
                f"{submission_id}: the mcq criterion generated extraction work — "
                f"FR-EXTRACT-06 forbids it"
            )
            assert _count(rows, STAGE_SCORE, submission_id, "C1") == 0, (
                f"{submission_id}: the mcq criterion generated scoring arms"
            )
            # The open criteria: exactly one extract unit each.
            for criterion_id in ("C2", "C4"):
                assert _count(rows, STAGE_EXTRACT, submission_id, criterion_id) == 1, (
                    f"{submission_id}/{criterion_id}: exactly one extract unit "
                    f"expected"
                )

        # Exhaustive accounting: across extract + deterministic, every
        # (submission, criterion) pair in the package appears exactly once; the score
        # stage carries the only remainder.
        account: dict[tuple[str, str], int] = {}
        for row in rows:
            if row["stage"] in (STAGE_EXTRACT, STAGE_DETERMINISTIC):
                key = (row["submission_id"], row["criterion_id"])
                account[key] = account.get(key, 0) + 1
        expected = {
            (s, c["criterion_id"]) for s in _SUBMISSIONS for c in _CRITERIA
        }
        assert set(account) == expected, (
            f"the enumeration does not cover the package exactly: extra "
            f"{sorted(set(account) - expected)}, missing {sorted(expected - set(account))}"
        )
        assert all(count == 1 for count in account.values()), (
            f"a (submission, criterion) pair enumerated twice at the work stage: "
            f"{[k for k, v in account.items() if v != 1]}"
        )
    finally:
        store.close()
