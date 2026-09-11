"""`TC-STATS-02` and `TC-STATS-03` — the per-family figures and the weighted signal, in exact fractions.

Test plan §5.16, issue #119 (TS-42). Both cases are Unit / rung 0 and both ask
for *"exact value plus"* a separation assertion, and both separation halves are
already swept over the surface by the contract cases — `TC-STATS-C04` holds the
no-merge refusal and `TC-STATS-C06` holds the κ-invariance under operational
contamination. What was missing is the numbers themselves: this file pins the
exact per-family references and the exact weighted figures, each derived in
its docstring, so a defect in the *formulas* (not just in the surface) has a
hand-computed oracle to fail against.

**TC-STATS-02** (`FR-STATS-03`): one blind population per scoring-model family
— `atomic` (C-AT, 20 labels), `atomic_with_gate` (C-GATE, 30) and `holistic`
(C-HOL, 30) — with three deliberately different band mixes, because the
separation claim is only testable when a merge would *move the number*: the
three κ are pairwise distinct, and the figure over the pooled families (κ =
2929/4289) is not even their n-weighted mean (which is 0.6535, not 0.6829) —
a third number, which is why no figure may be read as spanning families. The
API half: each keyed figure carries its family's declared `scoring_model`, the
caller does not pass one, and the unscoped request's figure carries
`scoring_model = None` — the module never stamps a family on a number that
spans families.

**TC-STATS-03** (`FR-STATS-14`): ten paired labels of each evidence class —
4 override (agreeing), 4 acceptance (disagreeing), 2 blind (agreeing) — under
three weightings:

    default {acceptance: 0.25, override: 0.75, blind: 1.0}:
        (4·0.75·1 + 4·0.25·0 + 2·1.0·1)/(4·0.75 + 4·0.25 + 2·1.0) = 5/6
    caller {acceptance: 0.1, override: 1.0, blind: 1.0}:
        (4·1.0 + 0 + 2·1.0)/(4·1.0 + 4·0.1 + 2·1.0) = 6/6.4 = 15/16
    unweighted {acceptance: 1.0, override: 1.0, blind: 1.0}:
        (4 + 0 + 2)/10 = 3/5

and the separation, asserted on the *same instance*: the agreement figure is
computed over the two blind labels alone (n = 2, 10 excluded), where unanimity
makes κ 0/0 — `None` — and the weighted signal's number is reachable from no
figure. The four disagreeing acceptances contribute a full 1.0 of denominator
to the signal and nothing at all to any validity figure (`FR-STATS-14`'s
"never blurs into a validity claim"; the contamination differential itself is
`TC-STATS-C06`'s, not repeated here).

Isolation: rung 0. Interface: the landed `build_stats`/`agreement`/
`operational_signal` surface (#115/#118) and `stats_vocabulary`'s declared
groups.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import STATS_MODULE, require

pytestmark = pytest.mark.contract


def _labels(table: dict[tuple[int, int], int], *, criterion: str, prefix: str,
            label_type: str = "blind", origin: str = "blind_sample"):
    """The table's labels, `(system band, teacher band) -> count`, for one criterion."""
    labels = []
    for index, ((system, teacher), count) in enumerate(sorted(table.items())):
        for j in range(count):
            labels.append(
                broken.Label(
                    label_id=f"{prefix}-{index}-{j}",
                    label_type=label_type,
                    criterion_id=criterion,
                    band=system,
                    teacher_band=teacher,
                    origin=origin,
                )
            )
    return labels


def _keyed_call(criterion: str) -> dict[str, object]:
    """The agreement call for one criterion, **without** a scoring model — the
    declared model is the figure's default, and the API assertion is that it
    arrives."""
    call = dict(vocab.EMPTY_DATA_CALL["agreement"])
    del call["scoring_model"]
    call["criterion_id"] = criterion
    return call


def _unscoped_call() -> dict[str, object]:
    """The unscoped agreement call: no criterion, no scoring model — the
    figure that spans whatever the instance holds, disclosed as claiming
    neither."""
    call = dict(vocab.EMPTY_DATA_CALL["agreement"])
    del call["scoring_model"]
    call["criterion_id"] = None
    call["scoring_model"] = None
    return call


# --- TC-STATS-02 — the per-family figures -------------------------------------------------------


def _three_family_stats():
    """One instance carrying the three families' blind populations, with each
    criterion's scoring model and band count declared.

    Mixes (checked term by term in exact fractions):
    - C-AT (atomic, 20): (1,1):6 (1,2):2 (2,2):8 (2,3):2 (3,3):1 (3,4):1 —
      po = 15/20 = 3/4; marginals sys (8, 10, 2, 0), tea (6, 10, 3, 1);
      pe = (8·6 + 10·10 + 2·3 + 0·1)/400 = 154/400 = 77/200;
      kappa = (150/200 − 77/200)/(123/200) = 73/123.
    - C-GATE (atomic_with_gate, 30): (1,1):7 (1,2):1 (2,2):9 (2,3):1 (3,3):10 (3,4):2 —
      po = 26/30 = 13/15; marginals sys (8, 10, 12, 0), tea (7, 10, 11, 2);
      pe = (8·7 + 10·10 + 12·11 + 0·2)/900 = 288/900 = 8/25;
      kappa = (65/75 − 24/75)/(51/75) = 41/51.
    - C-HOL (holistic, 30): (2,2):12 (2,3):3 (3,3):10 (3,4):5 —
      po = 22/30 = 11/15; marginals sys (0, 15, 15, 0), tea (0, 12, 13, 5);
      pe = (0·0 + 15·12 + 15·13 + 0·5)/900 = 375/900 = 5/12;
      kappa = (44/60 − 25/60)/(35/60) = 19/35.
    """
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    atomic = _labels({(1, 1): 6, (1, 2): 2, (2, 2): 8, (2, 3): 2, (3, 3): 1, (3, 4): 1},
                     criterion="C-AT", prefix="at")
    gate = _labels({(1, 1): 7, (1, 2): 1, (2, 2): 9, (2, 3): 1, (3, 3): 10, (3, 4): 2},
                   criterion="C-GATE", prefix="gate")
    holistic = _labels({(2, 2): 12, (2, 3): 3, (3, 3): 10, (3, 4): 5},
                       criterion="C-HOL", prefix="hol")
    return build_stats(
        atomic + gate + holistic,
        scoring_models={"C-AT": "atomic", "C-GATE": "atomic_with_gate", "C-HOL": "holistic"},
        band_counts={"C-AT": 4, "C-GATE": 4, "C-HOL": 4},
    )


_AT_KAPPA = Fraction(73, 123)
_GATE_KAPPA = Fraction(41, 51)
_HOL_KAPPA = Fraction(19, 35)


def test_tc_stats_02_each_family_figures_its_own_exact_value_and_names_its_own_model():
    """`TC-STATS-02` (`FR-STATS-03`, unit / rung 0, P0) — three families, three
    exact κ values, and each figure carrying its own declared scoring model
    without the caller passing one."""
    stats = _three_family_stats()
    at = stats.agreement(**_keyed_call("C-AT"))
    gate = stats.agreement(**_keyed_call("C-GATE"))
    hol = stats.agreement(**_keyed_call("C-HOL"))

    assert at.scoring_model == "atomic", "the declared model arrives on the figure"
    assert at.kappa == pytest.approx(float(_AT_KAPPA)), (
        "the atomic family's hand-computed kappa: (3/4 − 77/200)/(1 − 77/200) = 73/123"
    )
    assert gate.scoring_model == "atomic_with_gate"
    assert gate.kappa == pytest.approx(float(_GATE_KAPPA)), (
        "the gate family's hand-computed kappa: (13/15 − 8/25)/(1 − 8/25) = 41/51"
    )
    assert hol.scoring_model == "holistic"
    assert hol.kappa == pytest.approx(float(_HOL_KAPPA)), (
        "the holistic family's hand-computed kappa: (11/15 − 5/12)/(1 − 5/12) = 19/35"
    )
    assert (at.n, gate.n, hol.n) == (20, 30, 30)


def test_tc_stats_02_the_families_figures_differ_so_a_merge_would_move_the_number():
    """The separation the case asks for, at the value level: the three κ are
    pairwise distinct, so any figure spanning the families would be a *third*
    number — and the pooled figure the unscoped request produces is exactly
    that third number, 2929/4289, which is not even the n-weighted mean
    (0.6535) of the three. That is why the module hands it out with
    `scoring_model = None` and no criterion: a number that spans families
    claims no family.

    Pooling the three tables: (1,1):13 (1,2):3 (2,2):29 (2,3):6 (3,3):21
    (3,4):8 over n = 80 — po = 63/80, marginals sys (16, 35, 29, 0), tea
    (13, 32, 27, 8), pe = (16·13 + 35·32 + 29·27 + 0·8)/6400 = 2111/6400,
    kappa = (5040/6400 − 2111/6400)/(4289/6400) = 2929/4289."""
    stats = _three_family_stats()
    at = stats.agreement(**_keyed_call("C-AT"))
    gate = stats.agreement(**_keyed_call("C-GATE"))
    hol = stats.agreement(**_keyed_call("C-HOL"))

    assert at.kappa != pytest.approx(gate.kappa)
    assert gate.kappa != pytest.approx(hol.kappa)
    assert at.kappa != pytest.approx(hol.kappa)

    pooled = stats.agreement(**_unscoped_call())
    assert pooled.kappa == pytest.approx(float(Fraction(2929, 4289))), (
        "the figure over all three families' labels pooled: a third number — "
        "what a merge would have produced, and what no family figure may be read as"
    )
    assert pooled.n == 80
    assert pooled.scoring_model is None, (
        "the unscoped figure carries no family name: the module never stamps "
        "one family's model on a number computed across families"
    )


# --- TC-STATS-03 — the weighted signal and its exact values -------------------------------------


def _signal_stats(operational_weights=None):
    """Ten paired labels of each evidence class, the TC-STATS-03 population:
    4 override (agreeing), 4 acceptance (disagreeing), 2 blind (agreeing)."""
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    overrides = _labels({(3, 3): 4}, criterion="C-01", prefix="ov",
                        label_type="operational", origin="override")
    accepts = _labels({(2, 3): 4}, criterion="C-01", prefix="acc",
                      label_type="operational", origin="accept")
    blind = _labels({(2, 2): 2}, criterion="C-01", prefix="bl")
    return build_stats(overrides + accepts + blind, operational_weights=operational_weights)


def test_tc_stats_03_the_declared_weights_produce_the_declared_weighted_mean():
    """`TC-STATS-03` (`FR-STATS-14`, unit / rung 0, P1 Phase 2) — the default
    weighting's exact value: an override is informative, an acceptance weak, a
    blind score authoritative.

    (4·0.75·1 + 4·0.25·0 + 2·1.0·1)/(4·0.75 + 4·0.25 + 2·1.0) = 5/6."""
    stats = _signal_stats()
    signal = stats.operational_signal()

    assert signal.signal == pytest.approx(float(Fraction(5, 6))), (
        "the declared weights' hand-computed mean: 5.0/6.0 — an override counts "
        "for three acceptances, a blind score for four acceptances"
    )
    assert signal.n == 10, "every paired label of every evidence class is in the signal"
    assert signal.weighted is True
    assert signal.weights == dict(require(STATS_MODULE, "OPERATIONAL_EVIDENCE_WEIGHTS", issue="#118")), (
        "the weights ride the value they produced (FR-STATS-14)"
    )


def test_tc_stats_03_the_callers_weights_replace_the_declared_ones():
    """The caller's mapping replaces the defaults (`FR-STATS-14`): with
    {acceptance: 0.1, override: 1.0, blind: 1.0} the same population scores
    (4·1.0 + 0 + 2·1.0)/(4·1.0 + 4·0.1 + 2·1.0) = 6/6.4 = 15/16 — the override
    arm now carries the signal."""
    stats = _signal_stats({"acceptance": 0.1, "override": 1.0, "blind": 1.0})
    signal = stats.operational_signal()
    assert signal.signal == pytest.approx(float(Fraction(15, 16))), (
        "6/6.4 = 15/16 under the caller's weights"
    )
    assert signal.weights == {"acceptance": 0.1, "override": 1.0, "blind": 1.0}, (
        "the caller's mapping is the one the value was computed with"
    )


def test_tc_stats_03_unweighted_the_signal_is_the_raw_rate():
    """All-ones weights are the raw agreement rate of the paired population:
    (4 + 0 + 2)/10 = 3/5 — and the value discloses that nothing was weighted."""
    stats = _signal_stats({"acceptance": 1.0, "override": 1.0, "blind": 1.0})
    signal = stats.operational_signal()
    assert signal.signal == pytest.approx(0.6), "(4 + 0 + 2)/10 = 3/5"
    assert signal.weighted is False, "no non-default weight was applied, and the value says so"


def test_tc_stats_03_the_weighted_number_is_unreachable_from_the_agreement_figure():
    """The separation half, on the same instance: the figure is computed over
    the two blind labels alone — n = 2, the ten operational labels excluded —
    where unanimity makes κ 0/0. The signal's 5/6 is reachable from no figure:
    the four disagreeing acceptances' denominator exists only in the signal."""
    stats = _signal_stats()
    figure = stats.agreement(**_unscoped_call())
    assert figure.n == 2, "only the blind labels are the figure's population"
    assert figure.excluded_count == 8, "every operational label is outside it (10 labels − 2)"
    assert figure.kappa is None, "two unanimous blind labels: 0/0, not 5/6"
    assert figure.ordinal_alpha == 1.0