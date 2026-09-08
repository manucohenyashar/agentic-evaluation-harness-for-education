"""`TC-ORCH-15` — the cost ceiling on a `cloud-hosted` run, **written ahead of #61**
(the pause machine and the ceiling wiring; the pause-lifecycle file's sibling).

FR-ORCH-15: a cost estimate is obtained before dispatch and displayed; at and above the
ceiling the run pauses, the ledger is preserved, and the pause names the spend and the
remaining unit count. The plan's scenario fixes the run's spend at 9.90 and sets the
ceiling to 99%, 100% and 101% of it — `10.00`, `9.90`, `9.80`.

**Interface this file assumes of #61**, listed so it is reconciled deliberately rather
than discovered (the `test_pause_lifecycle.py` precedent):

| Name | Status |
|---|---|
| `Orchestrator.start(run_id)`, `.pause(run_id, cause=...)` | design §3.7 Protocol members #61 ships on the concrete class — the same assumed surface the pause-lifecycle file gates on |
| `Orchestrator(store, provider=...)` | **declared seam**: the orchestrator consults the provider for cost figures. Shipped `Orchestrator(store)` takes no provider; the constructor check below is the line that reconciles. |
| `provider.estimate_cost(unit) -> Decimal` | **declared**: the per-unit estimate. The run estimate displayed before dispatch is the **sum** of the unit estimates; if #61 instead asks the provider for a run-level figure, the displayed-estimate assertion below is where that lands. |
| ceiling semantics | **declared reading** of "a cost estimate is obtained before dispatch": before each dispatch the orchestrator holds the unit's estimate; a dispatch that would land **above** the ceiling is refused and the run pauses (strict `>`, matching the breaker's and budget's strict readings); a dispatch landing exactly **at** the ceiling proceeds, and the run pauses once spend sits at the ceiling — "at and above the ceiling the run pauses" (FR-ORCH-15). The alternative reading — accrue after dispatch, pause on `>=` — differs only in whether the crossing unit runs; the 101% limb's refused dispatch is where the two readings separate, visibly. |
| the pause names spend and remaining | observed by a **name-agnostic scan of the run row** (the pause-lifecycle idiom) for the spend figure and the remaining unit count; the remaining count is cross-checked against the ledger's pending units. |

**Fixture arithmetic, exact.** 15 submissions x 1 judged criterion x 1 judge = 15
extraction + 15 scoring = 30 dispatchable units; the fake provider estimates every unit
at `0.33`, so the run's total is exactly `9.90` — the plan's spend figure. The dispatch
order is the shipped sweep order (extraction then scoring), and each unit costs the same,
so the accrual sequence is `0.33 x k`:

- `10.00` (99%): no dispatch ever lands above — all 30 dispatch, the run never pauses;
- `9.90` (100%): the 30th dispatch lands **exactly at** the ceiling — allowed, and the
  run pauses with all 30 dispatched and 0 pending;
- `9.80` (101%): the 30th dispatch would land `9.90 > 9.80` — refused, the run pauses
  with 29 dispatched, **1 remaining**, and spend `9.57` — a figure distinct from the
  ceiling, so the pause's spend scan cannot be satisfied by the ceiling itself.

The remaining-unit counts (0 and 1) are exact ledger facts, and both pause limbs name
their figures: the operator surface can say why the run stopped and what is left.

Isolation: rung 2 — real store, real Tier P package, real cohort ledger; the provider is
a fake only in the sense every transport double here is: it answers a declared seam with
declared figures, and the ledger observes what the orchestrator did with them.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.store import open_store
from tests.support.conf_builders import hosted_cfg
from tests.support.impl import ORCH_MODULE, require, require_attr
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#61"

_SUBMISSIONS = tuple(f"SYN-{i:03d}" for i in range(1, 16))  # 15 -> 30 dispatchable units
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},)
_UNIT_COST = Decimal("0.33")  # 30 x 0.33 = 9.90, the plan's spend figure
_RUN_ESTIMATE = "9.9"  # the displayed run estimate, rendered permissively (9.9 / 9.90)

#: (ceiling, expected dispatched, expected pending, the spend figure the pause names).
#: The 99% limb names no figure — there is no pause to read one from.
_LIMBS = [
    ("10.00", 30, 0, None),
    ("9.90", 30, 0, "9.9"),
    ("9.80", 29, 1, "9.57"),
]


class _FlatProvider:
    """Estimates every unit at the same declared figure — the seam's answer, nothing else."""

    def __init__(self) -> None:
        self.calls = 0

    def estimate_cost(self, *args: object, **kwargs: object) -> Decimal:
        self.calls += 1
        return _UNIT_COST


def _run_row(store, run_id: str) -> dict:
    rows = store.cohort(ORCH_COHORT_ID).query(
        "SELECT * FROM run WHERE run_id = :r", r=run_id
    )
    assert rows, f"run {run_id} vanished"
    return rows[0]


def _row_shows(row: dict, figure: str) -> bool:
    """Whether the figure is readable anywhere on the row — as text, a numeric string, or
    a numeric column. Name-agnostic on purpose: which column carries the display is #61's."""
    for value in row.values():
        if isinstance(value, str) and figure in value:
            return True
        try:
            if value is not None and float(value) == float(figure):
                return True
        except (TypeError, ValueError):
            continue
    return False


@pytest.mark.parametrize(
    ("ceiling", "expected_dispatched", "expected_pending", "spend_figure"),
    _LIMBS,
    ids=["99pct-runs", "100pct-pauses-at", "101pct-refuses-and-pauses"],
)
def test_tc_orch_15_the_ceiling_pauses_at_and_above_and_the_estimate_precedes_dispatch(
    tmp_data_dir, ceiling, expected_dispatched, expected_pending, spend_figure
):
    """`TC-ORCH-15` (`FR-ORCH-15`, integration / rung 2, boundary, P0) — the estimate is
    displayed before anything is dispatched; at the ceiling the run pauses with the whole
    run dispatched; above it, the crossing dispatch is refused and the pause names the
    spend and the remaining unit count; below it, the run runs."""
    Orchestrator = require(ORCH_MODULE, "Orchestrator", issue=ISSUE)
    require_attr(Orchestrator, "start", issue=ISSUE)
    require_attr(Orchestrator, "pause", issue=ISSUE)
    assert "provider" in inspect.signature(Orchestrator.__init__).parameters, (
        "Orchestrator's constructor takes no provider — FR-ORCH-15's estimate is "
        "obtained from the transport seam, and a ceiling checked without one is a "
        "ceiling checked against nothing"
    )

    store_dir = tmp_data_dir / f"ceiling-{ceiling.replace('.', '-')}"
    store = open_store(store_dir)
    try:
        seed_cohort(store, _SUBMISSIONS)
        version = seed_package(store, _CRITERIA)
        resolved = resolve_run_config(
            hosted_cfg(HARNESS_COST_CEILING=ceiling),
            CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
        )
        provider = _FlatProvider()
        orch = Orchestrator(store, provider=provider)
        run_id = orch.create_run(ORCH_COHORT_ID, version, resolved)
        orch.enumerate_units(run_id)
        cohort = store.cohort(ORCH_COHORT_ID)

        # The estimate precedes dispatch: start() has obtained and displayed the run's
        # estimated cost before a single unit is leased.
        orch.start(run_id)
        assert _row_shows(_run_row(store, run_id), _RUN_ESTIMATE), (
            f"the run row displays no {_RUN_ESTIMATE} estimate after start() and "
            "before any dispatch — 'a cost estimate is obtained before dispatch and "
            "displayed' means the operator sees the figure before the spend happens "
            "(FR-ORCH-15)"
        )

        # Dispatch one unit at a time in the shipped sweep order, stopping when the run
        # pauses (the claim query refuses a paused run) or the stage empties.
        dispatched = 0
        for stage in ("extract", "score"):
            while _run_row(store, run_id)["status"] != "paused":
                if not orch.lease("worker-a", stage, 1):
                    break
                dispatched += 1

        row = _run_row(store, run_id)
        assert dispatched == expected_dispatched, (
            f"{dispatched} units dispatched under ceiling {ceiling}, expected "
            f"{expected_dispatched} — the boundary is exact: below the ceiling nothing "
            "is refused, at it the final unit lands, above it the crossing unit is "
            "refused"
        )
        if spend_figure is None:
            assert row["status"] == "running", (
                f"a run at 99% of its ceiling is '{row['status']}', not 'running' — "
                "the ceiling rations spend, it does not ration a run still under it"
            )
        else:
            assert row["status"] == "paused", (
                f"a run at spend {spend_figure} against ceiling {ceiling} is "
                f"'{row['status']}', not 'paused' — at and above the ceiling the run "
                "pauses (FR-ORCH-15)"
            )
            # The pause names the spend: the figure is readable on the run row the
            # operator surface reads.
            assert _row_shows(row, spend_figure), (
                f"the pause left no readable spend figure {spend_figure} on the run "
                "row — a pause that says only THAT it stopped cannot be told from a "
                "crash, and the operator cannot judge what the ceiling admitted"
            )
            # ...and the remaining unit count, cross-checked against the ledger.
            pending = cohort.query(
                "SELECT COUNT(*) AS n FROM work_unit "
                "WHERE run_id = :r AND status = 'pending'",
                r=run_id,
            )[0]["n"]
            assert pending == expected_pending, (
                f"the ledger holds {pending} pending units, expected "
                f"{expected_pending} — the remaining count the pause must name is a "
                "ledger fact, and a figure that disagrees with it is a wrong figure"
            )
            assert _row_shows(row, str(expected_pending)), (
                f"the pause names no remaining unit count ({expected_pending}) — the "
                "operator must see how much work the ceiling left undone, not only "
                "that the money stopped"
            )

        # The ledger is preserved: every unit row the run enumerated is still there,
        # none deleted, none rewritten into a result — a pause is a stop, not a purge.
        units = cohort.query(
            "SELECT status, COUNT(*) AS n FROM work_unit WHERE run_id = :r "
            "GROUP BY status",
            r=run_id,
        )
        assert sum(entry["n"] for entry in units) == 30, (
            "the pause changed the ledger's unit count — the ledger is preserved "
            "across a ceiling pause (FR-ORCH-15)"
        )
        assert not cohort.query("SELECT 1 FROM verdict LIMIT 1") and not cohort.query(
            "SELECT 1 FROM criterion_score LIMIT 1"
        ), (
            "the ceiling pause fabricated a verdict or criterion_score row — a pause "
            "writes a stop and a reason, never a result"
        )
    finally:
        store.close()
