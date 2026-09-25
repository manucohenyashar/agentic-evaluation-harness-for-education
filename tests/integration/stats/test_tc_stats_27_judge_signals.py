"""`TS-89` (issue #383) — `TC-STATS-27`: per-(criterion, judge) signals and the concentration
alert (`FR-STATS-20`, `CT-JUDGE-16`, RISK-54).

| Input | Expected |
|---|---|
| C1: J1 10 verdicts (2 uncited, 1 insufficient), J2 10 (0 uncited) | J1 uncited rate 0.2, insufficient rate 0.1 |
| violations J1 = 3, J2 = 3, J3 = 0 (total 6, J1 share 0.5) | alert **absent** — the threshold is a strict `>` |
| violations J1 = 4, J2 = 2 (total 6, share 0.667) | alert **present**, naming J1 |
| violations J1 = 4, J2 = 0 (total 4) | alert **absent** — below the minimum of 5 |
| every cell | fields equal `JUDGE_SIGNAL_FIELDS` |

**The per-judge keying IS the contract.** "Violations concentrated on one judge" is not
locatable from a run-level or a per-criterion figure: a criterion with six violations spread
evenly across three judges is a hard criterion, and the same six on one judge is a broken
judge. Those need different responses, and only the (criterion, judge) cell tells them apart.

**Both boundaries are exact, and each catches a different mistake.** The 0.5 arm pins the
comparison as strictly greater — an even split between two judges is not a concentration, and
a `>=` would alert on every two-judge criterion that ever refused twice. The total-of-4 arm
pins the minimum — without it, one violation against one other is a 100% concentration and
every run would alert on its first pair of refusals.

**The field set is asserted as equality, not containment.** `JUDGE_SIGNAL_FIELDS` is what
`CT-JUDGE-16` makes contract; a cell carrying an extra key is a consumer's future dependency
on something nobody declared, and a missing one is a signal that reads as absent rather than
as zero.

**Isolation: rung 2** — a real store, real `work_unit` and `verdict` rows on the cohort ledger,
and the violation counts on Tier D where `M-JUDGE` records them.
"""

from __future__ import annotations

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
from aeh.stats import (
    JUDGE_SIGNAL_FIELDS,
    JUDGE_VIOLATION_ALERT,
    STATS_VIOLATION_CONCENTRATION,
    STATS_VIOLATION_MINIMUM,
    judge_signals,
)
from aeh.store import Statement, open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

CRITERION = "C1"
J1, J2, J3 = "judge-1", "judge-2", "judge-3"
VERDICTS_PER_JUDGE = 10

#: J1's ten verdicts: two uncited, one with the panel reporting the evidence insufficient.
J1_UNCITED = 2
J1_INSUFFICIENT = 1

CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

_INSERT_UNIT = Statement(
    "INSERT INTO work_unit (work_id, run_id, submission_id, criterion_id, stage, "
    "judge_id, origin, status, attempts) VALUES (:work_id, :run_id, :submission_id, "
    ":criterion_id, 'score', :judge_id, 'base', 'done', 0)"
)
_INSERT_VERDICT = Statement(
    "INSERT INTO verdict (verdict_id, work_id, judge_id, band, uncited, "
    "evidence_sufficient, latency_ms) VALUES (:verdict_id, :work_id, :judge_id, :band, "
    ":uncited, :evidence_sufficient, :latency_ms)"
)
_INSERT_VIOLATIONS = Statement(
    "INSERT INTO run_metrics (run_id, metric, value, criterion_id, judge_id) "
    "VALUES (:run_id, 'judge_contract_violations', :value, :criterion_id, :judge_id)"
)


def _seed_verdicts(store: Any, run_id: str) -> None:
    """Ten verdicts each for J1 and J2, with J1 carrying the uncited and insufficient ones."""
    cohort = store.cohort(ORCH_COHORT_ID)
    with cohort.transaction() as tx:
        for judge in (J1, J2):
            for index in range(VERDICTS_PER_JUDGE):
                work_id = f"w-{judge}-{index:02d}"
                tx.execute(
                    _INSERT_UNIT,
                    work_id=work_id, run_id=run_id, submission_id="S001",
                    criterion_id=CRITERION, judge_id=judge,
                )
                tx.execute(
                    _INSERT_VERDICT,
                    verdict_id=f"v-{judge}-{index:02d}",
                    work_id=work_id,
                    judge_id=judge,
                    band="B3",
                    uncited=1 if (judge == J1 and index < J1_UNCITED) else 0,
                    evidence_sufficient=(
                        0 if (judge == J1 and index < J1_INSUFFICIENT) else 1
                    ),
                    latency_ms=100 + index,
                )


def _seed_violations(store: Any, run_id: str, counts: dict[str, float]) -> None:
    with store.durable().transaction() as tx:
        for judge, value in counts.items():
            tx.execute(
                _INSERT_VIOLATIONS,
                run_id=run_id, value=value, criterion_id=CRITERION, judge_id=judge,
            )


@pytest.fixture
def signal_world(tmp_data_dir):
    """A run with J1's and J2's verdicts seeded; violations are per-arm."""
    store = open_store(tmp_data_dir)
    _orchestrator, run_id, _version = seed_run(
        store, submissions=("S001",), criteria=CRITERIA,
    )
    _seed_verdicts(store, run_id)
    try:
        yield store, run_id
    finally:
        store.close()


def _alerts_for(store: Any, run_id: str) -> tuple[str, ...]:
    return judge_signals(store, run_id).alerts


# --- TC-STATS-27, the rates -----------------------------------------------------------------


def test_tc_stats_27_the_per_judge_rates_are_hand_computable(signal_world):
    """J1: uncited 2/10 = 0.2, insufficient 1/10 = 0.1. J2: both 0.0.

    J2 is asserted beside J1 because a rate computed over the whole criterion rather than the
    cell would give both judges 0.1 and 0.05, which is close enough to look right and wrong
    about which judge is uncitedly guessing.
    """
    store, run_id = signal_world
    cells = dict(judge_signals(store, run_id))

    j1 = cells[(CRITERION, J1)]
    assert j1["uncited_verdict_rate"] == pytest.approx(0.2), (
        f"J1's uncited rate is {j1['uncited_verdict_rate']}, not 0.2 (2 of 10)"
    )
    assert j1["evidence_sufficient_false_rate"] == pytest.approx(0.1), (
        f"J1's insufficient rate is {j1['evidence_sufficient_false_rate']}, not 0.1 (1 of 10)"
    )

    j2 = cells[(CRITERION, J2)]
    assert j2["uncited_verdict_rate"] == 0.0, (
        f"J2's uncited rate is {j2['uncited_verdict_rate']}, not 0.0 — the rate is per CELL, "
        "and pooling the criterion's verdicts would blame both judges for J1's two"
    )


def test_tc_stats_27_every_cell_carries_exactly_the_declared_fields(signal_world):
    """Field-set equality against `JUDGE_SIGNAL_FIELDS`, per cell.

    Equality rather than containment: `CT-JUDGE-16` makes the names contract, so an extra key
    is a dependency nobody declared and a missing one is a signal that reads as absent.
    """
    store, run_id = signal_world

    for pair, cell in dict(judge_signals(store, run_id)).items():
        assert set(cell) == set(JUDGE_SIGNAL_FIELDS), (
            f"cell {pair} carries {sorted(cell)}; the declared set is "
            f"{sorted(JUDGE_SIGNAL_FIELDS)}"
        )


# --- TC-STATS-27, the alert's two boundaries ------------------------------------------------


def test_tc_stats_27_an_even_split_is_not_a_concentration(signal_world):
    """J1 = 3, J2 = 3, J3 = 0 — total 6, J1's share exactly 0.5: **no** alert.

    The strict-`>` boundary. A `>=` here alerts on every two-judge criterion that refused
    twice, which is most of them, and the alert stops meaning anything.
    """
    store, run_id = signal_world
    _seed_violations(store, run_id, {J1: 3, J2: 3, J3: 0})

    alerts = _alerts_for(store, run_id)
    assert alerts == (), (
        f"an even 3/3 split raised {alerts}. A share of exactly "
        f"{STATS_VIOLATION_CONCENTRATION} is not concentration — two judges refusing equally "
        "is a hard criterion, not a broken judge"
    )


def test_tc_stats_27_a_clear_majority_names_the_judge(signal_world):
    """J1 = 4, J2 = 2 — total 6, share 0.667: the alert fires and names J1.

    Naming is the point. "This criterion has violations" sends a reviewer to the criterion;
    "J1 holds four of this criterion's six" sends them to the judge, which is where the
    problem is.
    """
    store, run_id = signal_world
    _seed_violations(store, run_id, {J1: 4, J2: 2})

    alerts = _alerts_for(store, run_id)
    assert len(alerts) == 1, f"expected exactly one alert, got {alerts}"
    assert JUDGE_VIOLATION_ALERT in alerts[0], (
        f"the alert is not the declared name: {alerts[0]!r}"
    )
    assert J1 in alerts[0] and CRITERION in alerts[0], (
        f"the alert names neither the judge nor the criterion: {alerts[0]!r}"
    )
    assert J2 not in alerts[0], (
        f"the alert names the judge that did NOT concentrate: {alerts[0]!r}"
    )


def test_tc_stats_27_a_small_total_never_alerts_however_concentrated(signal_world):
    """J1 = 4, J2 = 0 — a 100% share over a total of 4: **no** alert, below the minimum of 5.

    Without the minimum, the first two refusals of any run are a 100% concentration and every
    run alerts on its first bad afternoon.
    """
    store, run_id = signal_world
    _seed_violations(store, run_id, {J1: 4, J2: 0})

    alerts = _alerts_for(store, run_id)
    assert alerts == (), (
        f"a total of 4 violations raised {alerts}; the minimum is "
        f"{STATS_VIOLATION_MINIMUM} and 4 is below it, however concentrated"
    )


def test_tc_stats_27_the_violation_rate_is_over_every_response_the_judge_made(signal_world):
    """`contract_violation_rate` is refusals ÷ (verdicts + refusals), not ÷ verdicts.

    Not a plan row, and the denominator is the thing worth pinning: a refusal produces no
    verdict, so dividing by landed verdicts alone reports a judge that refused four times out
    of fourteen responses as having a 40% violation rate rather than 28.6%. Hand-computed:
    4 / (10 + 4).
    """
    store, run_id = signal_world
    _seed_violations(store, run_id, {J1: 4, J2: 0})

    cell = dict(judge_signals(store, run_id))[(CRITERION, J1)]
    assert cell["contract_violation_rate"] == pytest.approx(4 / 14), (
        f"the violation rate is {cell['contract_violation_rate']}, not {4 / 14:.4f}: four "
        "refusals over fourteen responses, because a refusal is a response that produced no "
        "verdict"
    )
