"""`TS-101` (issue #395) — `TC-CALIB-20` and `TC-CALIB-C17`: the dual-scored roster is built
from run-scoped R₀ scores, persisted, and survives a restart (`FR-CALIB-15`, `CT-CALIB-17`).

Gap-fix test plan §5 / §6:

| Case | Preconditions | Expected |
|---|---|---|
| `TC-CALIB-20` | R₀ run with run-scoped scores for 12 papers × 2 criteria; `run_dual_scoring` R₁ bands; `register_dual_scored_roster(K, r0_version=v1, r1_version=v2, store)`; then a **new** `Store` object and cleared `_CLASS_ROSTERS` | 24 `calib_roster` rows; `non_inferiority` before and after the restart returns equal results; R₀ bands come from R₀'s run only (a second run R₀′ with different bands does not leak) |
| `TC-CALIB-C17` | `TC-CALIB-20`'s restart arm | **Breaks if** registration writes only the in-memory `_CLASS_ROSTERS` |

**The restart, and why it is the whole point.** `_CLASS_ROSTERS` is a module-level dict, so a
roster registered into it alone survives nothing: the operator who runs the gate on Monday and
again on Tuesday is a *new process*. The restart is simulated the only way one process can — the
module dict is cleared and a **new `Store` object** is opened over the same data directory — so
everything the second `non_inferiority` reads had to come off disk. A registration that wrote only
the dict passes every assertion before the clear and fails the first one after it, which is
exactly `CT-CALIB-17`'s "breaks if".

**Two cases, one world, deliberately.** `TC-CALIB-C17` is `TC-CALIB-20`'s restart arm by the
plan's own words. They are written as two tests over one shared builder rather than one test with
two sections, so a failure report names which property broke: the roster's *content* (20) or its
*survival* (C17).

**The leak arm.** Run R₀′ scores the same 12 papers on the same two criteria in the same cohort
ledger with every band different. Since #359 `criterion_score` is keyed by run, so a registration
that forgot the run filter would read R₀′'s bands for at least some papers and the roster's R₀
half would stop matching what R₀ actually scored. The arm asserts the stored `r0_band` values are
R₀'s, cell by cell — not merely that 24 rows exist.

**The R₁ bands** come from `run_dual_scoring`, the authorized pass, exactly as the plan's
precondition names it: plan → authorize → run, through the module's injected counting provider
(seam 2 — nothing here reaches a network). The provider's band for a paper is deterministic, so
the shifted count the gate reports is hand-checkable: `_R1_PROVIDER` shifts papers 0-2 on C1 and
nothing else, so 3 of 12 papers moved.

**Isolation: rung 2** — a real store over a real durable tier (`tmp_data_dir`), the rung the plan
names. The cohort, run and score rows are seeded directly (the `tests/support/orch_run.py`
precedent) because M-CALIB reads them as stored rows; no pipeline is driven.

**Written ahead of implementation: no longer** — #375 landed `aeh.calib:register_dual_scored_roster`,
so both cases run unmarked against it. `require` stays: it is the probe that named the issue
while the symbol was missing, and it costs nothing now that it resolves.

**Interface assumed** (design delta §3.10 / FR-CALIB-15), for #375 to reconcile deliberately:

| Name | Assumption |
|---|---|
| `register_dual_scored_roster(cohort_id, *, r0_version, r1_version, store)` | builds the roster from the R₀ run's stored `criterion_score` rows and the R₁ bands, persists it, and registers it for `non_inferiority` |
| `calib_roster` | a durable table `(cohort_id, r0, r1, paper_id, criterion_id, r0_band, r1_band, recorded_at)` |
| R₁ bands | taken from the executed `DualScoringPlan.scores`, whose rows are per paper and columns per criterion (`plan_dual_scoring`'s own shape) |
| reaching the roster after a restart | `non_inferiority` populates `_CLASS_ROSTERS` from the persisted table on first use, as FR-CALIB-15 says in those words — so the restart arm calls the gate and nothing else. An implementation that needs an explicit load instead reds here, which is the reconciliation #375 makes deliberately |

**The plan-time circularity, disclosed.** `plan_dual_scoring` budgets an unregistered cohort at the
declared example class (100 × 1, `calib.py:2354`), so the 12 × 2 R₁ pass this case needs cannot be
planned before a roster exists — and the only thing that registers one is the call under test,
which needs the R₁ bands. FR-CALIB-15 does not say how a first-ever registration escapes that, so
the fixture seeds the class's SHAPE into `_CLASS_ROSTERS` before planning (R₀'s own bands on both
halves, which no assertion reads) and the registration under test replaces it from stored rows.
That seeded shape is why the restart arm clears the dict rather than trusting it: nothing here
lets a roster survive except the durable table. The circularity itself is a finding for #375.

The R₀ run is named by `r0_version` — the package version the run scored — so the registration
resolves the run from the cohort's ledger; `TC-CALIB-20`'s leak arm is what pins that resolution
to R₀'s own rows.
"""

from __future__ import annotations

from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full cohort chain (CLAUDE.md: all eleven contributors)
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
from aeh.store import open_store
from tests.support.impl import CALIB_MODULE, require
from aeh.pkg import PackageCatalog
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

ISSUE = "#375"

PAPERS = 12
CRITERIA = ("C1", "C2")
#: R₀'s bands, per paper and criterion — every paper at B2 on both criteria.
R0_BAND = "B2"
#: R₀′'s bands: a second run of the same cohort, every band different from R₀'s.
R0_PRIME_BAND = "B0"
#: The papers the R₁ pass moves a band on C1 — 3 of 12, the gate's hand-computed shift.
SHIFTED_PAPERS = (0, 1, 2)
SHIFTED_COUNT = len(SHIFTED_PAPERS)
SUBMISSIONS = tuple(f"S{index:02d}" for index in range(PAPERS))
#: The package `seed_run` builds the world under (its own default).
PACKAGE_ID = "pkg-orch"


class _R1Provider:
    """The injected dual-scoring provider (seam 2): deterministic R₁ bands, and a call count.

    `score(paper, criterion)` is `run_dual_scoring`'s own contract. Papers 0-2 move to `B3` on
    C1; every other cell stays at R₀'s band, so exactly three papers shifted and the gate's
    figure is hand-computable rather than read back off the thing under test.
    """

    def __init__(self) -> None:
        self.calls = 0

    def score(self, paper: int, criterion: int) -> str:
        self.calls += 1
        if criterion == 0 and paper in SHIFTED_PAPERS:
            return "B3"
        return R0_BAND


@pytest.fixture(autouse=True)
def _isolated_module_state():
    """`_CLASS_ROSTERS` is module state, and `pytest-randomly` shuffles order: each case starts
    from an empty registry and leaves one, so neither can pass on the other's leftovers."""
    calib = require(CALIB_MODULE, issue=ISSUE)
    calib._CLASS_ROSTERS.clear()
    yield
    calib._CLASS_ROSTERS.clear()


def _seed_plan_shape(calib: Any) -> None:
    """The class's shape at plan time — see "the plan-time circularity" above. R₀'s band on both
    halves, so every figure this case asserts comes from the registration, never from here."""
    calib._CLASS_ROSTERS[ORCH_COHORT_ID] = calib._ClassRoster(
        cohort_id=ORCH_COHORT_ID,
        class_size=PAPERS,
        criteria=CRITERIA,
        scores=tuple(((R0_BAND, R0_BAND),) * len(CRITERIA) for _ in range(PAPERS)),
        is_calibration_set=False,
    )


def _seed_scores(store: Any, run_id: str, band: str) -> None:
    """One run's `criterion_score` rows: every paper, every criterion, at `band`."""
    with store.cohort(ORCH_COHORT_ID).transaction() as tx:
        for submission_id in SUBMISSIONS:
            for criterion_id in CRITERIA:
                tx.execute(
                    "INSERT INTO criterion_score (run_id, submission_id, criterion_id, band, "
                    "modal_band, band_spread, points, judge_count, agreement, routing, state) "
                    "VALUES (:r, :s, :c, :b, :b, 0, 1.0, 3, 1.0, 'auto', 'final')",
                    r=run_id, s=submission_id, c=criterion_id, b=band,
                )


def _r1_bands(calib: Any, cohort_id: str) -> Any:
    """The R₁ bands as the plan's executed pass produced them (plan → authorize → run)."""
    provider = _R1Provider()
    _seed_plan_shape(calib)
    plan = calib.plan_dual_scoring(
        cohort_id=cohort_id, r0="pkg-v1", r1="pkg-v2", provider=provider
    )
    calib.authorize(plan)
    executed = calib.run_dual_scoring(plan)
    assert provider.calls == PAPERS * len(CRITERIA), (
        f"precondition: the authorized pass made {provider.calls} calls; one per "
        f"(paper, criterion) over {PAPERS} papers × {len(CRITERIA)} criteria is "
        f"{PAPERS * len(CRITERIA)}"
    )
    return executed


def _roster_rows(store: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in store.durable().query(
        "SELECT * FROM calib_roster ORDER BY paper_id, criterion_id"
    )]


def _registered_world(tmp_data_dir):
    """The shared world: R₀'s scores, R₀′'s different ones, the R₁ pass, and the registration.

    Returns `(calib, store, executed_plan, r0_version)`. The caller closes the store.
    """
    calib = require(CALIB_MODULE, issue=ISSUE)
    register = require(CALIB_MODULE, "register_dual_scored_roster", issue=ISSUE)
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_r0, version_1 = seed_run(
            store, submissions=SUBMISSIONS,
            criteria=tuple({"criterion_id": criterion, "kind": "open",
                            "scoring_model": "atomic"} for criterion in CRITERIA),
        )
        _seed_scores(store, run_r0, R0_BAND)
        # R₀′: a second run over the same papers whose bands must not leak into the roster.
        # It runs under its OWN package version, so `r0_version` names R₀ and only R₀ — two
        # runs of one version would leave the registration no key to tell them apart, and the
        # leak arm would be asserting a discrimination the interface cannot make.
        version_2 = PackageCatalog(
            store.package(PACKAGE_ID), package_id=PACKAGE_ID
        ).create_version(parent=version_1)
        run_r0_prime = aeh.orch.Orchestrator(store).create_run(
            ORCH_COHORT_ID, version_2, _run_config(),
        )
        assert run_r0_prime != run_r0
        _seed_scores(store, run_r0_prime, R0_PRIME_BAND)

        executed = _r1_bands(calib, ORCH_COHORT_ID)
        register(
            ORCH_COHORT_ID, r0_version=version_1, r1_version="pkg-v2", store=store,
        )
        return calib, store, executed, version_1
    except BaseException:
        store.close()
        raise


def _run_config() -> Any:
    """A resolved run configuration for the second R₀ run — the panel the seeded world uses."""
    from aeh.conf import CohortRef, resolve_run_config
    from tests.support.conf_builders import edge_cfg, edge_panel

    return resolve_run_config(
        edge_cfg(panel=edge_panel(3)),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    )


def _gate(calib: Any) -> Any:
    """The gate's result for the registered class, at a threshold the shift clears."""
    return calib.non_inferiority(
        r0="pkg-v1", r1="pkg-v2", cohort_id=ORCH_COHORT_ID, threshold=0.5,
    )


def _comparable(result: Any) -> dict[str, Any]:
    """The gate result's decision-bearing fields — the equality `TC-CALIB-20` asserts.

    `outcome` — the verdict itself — leads, because a restart that changed pass into reject is
    exactly the failure this case exists for. The timestamps are excluded deliberately:
    `first_result_at` records when the gate ran, and two runs an instant apart are not the same
    moment. Everything else a caller acts on is here.
    """
    fields = (
        "outcome", "shifted_papers", "class_size", "shifted_fraction", "threshold_used",
        "threshold_source", "advisory_only", "revert_to",
    )
    missing = [name for name in fields if not hasattr(result, name)]
    assert missing == [], (
        f"GateResult carries no {missing} — the comparison would silently read None on both "
        "sides of the restart and assert nothing"
    )
    return {name: getattr(result, name) for name in fields}


# --- TC-CALIB-20 --------------------------------------------------------------------------------


def test_tc_calib_20_the_registered_roster_is_persisted_and_carries_only_r0s_bands(
    tmp_data_dir,
):
    """`TC-CALIB-20` — 24 rows, R₀'s bands (not R₀′'s), and the gate's hand-computed figures."""
    calib, store, executed, _version = _registered_world(tmp_data_dir)
    try:
        rows = _roster_rows(store)
        assert len(rows) == PAPERS * len(CRITERIA), (
            f"the roster holds {len(rows)} rows; 12 papers × 2 criteria is 24 — one per cell"
        )
        assert {row["cohort_id"] for row in rows} == {ORCH_COHORT_ID}
        assert {str(row["criterion_id"]) for row in rows} == set(CRITERIA)
        assert len({str(row["paper_id"]) for row in rows}) == PAPERS, (
            "the roster does not carry twelve distinct papers"
        )

        # The leak arm: every stored R₀ band is R₀'s, never R₀′'s.
        leaked = [row for row in rows if str(row["r0_band"]) != R0_BAND]
        assert leaked == [], (
            f"{len(leaked)} roster row(s) carry an R₀ band that is not R₀'s {R0_BAND!r} — "
            f"run R₀′ scored the same cells {R0_PRIME_BAND!r}, so its rows leaked into the "
            f"roster (FR-CALIB-15 builds from the R₀ run's rows): {leaked[:3]}"
        )
        # The R₁ half is the executed pass's own bands, cell by cell.
        by_cell = {(str(row["paper_id"]), str(row["criterion_id"])): str(row["r1_band"])
                   for row in rows}
        shifted_cells = {cell for cell, band in by_cell.items() if band != R0_BAND}
        assert len(shifted_cells) == SHIFTED_COUNT, (
            f"{len(shifted_cells)} cells moved a band; the R₁ pass moved {SHIFTED_COUNT} "
            f"(papers {SHIFTED_PAPERS} on C1): {sorted(shifted_cells)}"
        )
        assert {criterion for _paper, criterion in shifted_cells} == {"C1"}, (
            "the R₁ pass moved a band on C2, which its provider never does — the roster's R₁ "
            "half is not the executed pass's bands"
        )
        assert executed.executed_at is not None, "precondition: the R₁ pass ran"

        result = _gate(calib)
        assert result.class_size == PAPERS, (
            f"the gate scored {result.class_size} papers; the registered class is {PAPERS}"
        )
        assert result.shifted_papers == SHIFTED_COUNT, (
            f"the gate counted {result.shifted_papers} shifted papers; the R₁ pass moved "
            f"{SHIFTED_COUNT} of {PAPERS} (papers {SHIFTED_PAPERS} on C1)"
        )
        assert result.shifted_fraction == pytest.approx(SHIFTED_COUNT / PAPERS)
    finally:
        store.close()


# --- TC-CALIB-C17 — the restart arm -------------------------------------------------------------


def test_tc_calib_c17_the_roster_survives_a_restart_and_the_gate_agrees(tmp_data_dir):
    """`TC-CALIB-C17` (`CT-CALIB-17`) — a new `Store` and an emptied `_CLASS_ROSTERS` give the
    same gate result: the roster came off disk, not out of the module dict."""
    calib, store, _executed, _version = _registered_world(tmp_data_dir)
    try:
        before = _comparable(_gate(calib))
        assert before["outcome"] == "pass", (
            f"precondition: 3 of 12 shifted against a 0.5 threshold passes; got {before!r}"
        )
        assert before["shifted_papers"] == SHIFTED_COUNT, (
            f"precondition: the pre-restart gate read {before!r}"
        )
    finally:
        store.close()

    # The restart: the process's module state is gone and the store object with it. Anything
    # the gate reads now had to be persisted (CT-CALIB-17's "breaks if" — a registration that
    # wrote only `_CLASS_ROSTERS` has nothing left at this line).
    calib._CLASS_ROSTERS.clear()
    assert not calib._CLASS_ROSTERS, "fixture: the module's roster cache was not cleared"

    reopened = open_store(tmp_data_dir)
    try:
        rows = _roster_rows(reopened)
        assert len(rows) == PAPERS * len(CRITERIA), (
            f"after the restart the durable roster holds {len(rows)} rows, not 24 — the "
            "registration did not persist (CT-CALIB-17)"
        )
        # No load is handed to the implementation and no pass is re-run: FR-CALIB-15 says the
        # registration "populates `_CLASS_ROSTERS` from it on first use" and `non_inferiority`
        # "reads through it", so calling the gate is the whole of the restart. An
        # implementation whose roster lived only in the dict has nothing to answer with, and
        # one that re-bought the R₁ pass would need a provider nobody passed here
        # (`NFR-CALIB-03`: the additional pass is budgeted and incurred once).
        after = _comparable(_gate(calib))
    finally:
        reopened.close()

    assert after == before, (
        f"the gate's result changed across the restart:\nbefore={before}\nafter={after} — "
        "a roster that survives is one whose gate answers the same question the same way "
        "(CT-CALIB-17)"
    )
