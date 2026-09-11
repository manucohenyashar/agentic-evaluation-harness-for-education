"""`TC-STATS-01` — agreement is computable only over blind, judged labels.

Test plan §5.16, issue #119 (TS-42). Traces to `FR-STATS-01`, `FR-DET-09`,
`NFR-STATS-04`; RISK-07 (Critical). *"This is the module where returning a
plausible-looking number instead of refusing would be the most damaging
possible failure"* — so the fixture is the plan's exact matrix, the figures are
exact hand-computed references, and every assertion is the refusal or the
number, never a call that returned.

The plan's preconditions, verbatim: one label store holding, for one criterion,
**20 blind judged labels, 40 operational (`accept`/`edit`/`override`,
`saw_system_output = 1`) judged labels, and 15 blind labels on a deterministic
criterion**. The 20's contingency table, and the hand computation every figure
below is checked against (verified term by term in exact fractions):

    table (system band, teacher band) -> count:
        (1,1):6 (1,2):2 (2,2):5 (2,3):2 (3,3):4 (3,4):1        n = 20
    po = 15/20 = 3/4;  marginals sys (8, 7, 5, 0), tea (6, 7, 6, 1)
    pe = (8·6 + 7·7 + 5·6 + 0·1)/400 = 127/400
    kappa = (300/400 − 127/400)/(273/400) = 173/273
    QWK = 1 − (1/36)/(37/225) = 123/148   (weights (i−j)²/9 over ordinals 0..3)
    alpha = 1 − D_o/D_e = 1 − (1/12)/(5/9) = 17/20

The 40 operational labels **disagree** (system band 1, teacher band 4) rather
than agreeing: a filter that admits them changes po, pe *and* n, so the exact
κ and the exact n are both live discriminators — an agreeing contamination
fixture would let a broken filter pass by luck of the arithmetic (the lesson
`TC-STATS-C06`'s review found).

Steps 2 and 3 — the public-API enumeration (no function computes agreement
over any other population) and the single-filter import-graph assertion — are
`TC-STATS-C01`'s surface and source sweeps (`test_admissible_labels_only.py`),
which this file does not duplicate; steps 1, 4, 5 and the variant are below.

Rung 2 (`open_stats` over a real store) for the matrix, rung 0 for the
variant — the variant's label cannot exist in the store (`saw_system_output`
is a `NOT NULL` column and `record_label` validates it to 0/1), which is
exactly why its consumer-side treatment is the open question the variant
registers (`WRITTEN_AHEAD_BLOCKERS`, "#119 null saw_system_output").
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import REVIEW_MODULE, STATS_MODULE, require

pytestmark = pytest.mark.contract

#: The plan's 20 blind judged labels, as a contingency table over
#: (system band, teacher band) — the hand reference's cells.
T1_TABLE: dict[tuple[int, int], int] = {
    (1, 1): 6, (1, 2): 2, (2, 2): 5, (2, 3): 2, (3, 3): 4, (3, 4): 1,
}
T1_KAPPA = Fraction(173, 273)
T1_QWK = Fraction(123, 148)
T1_ALPHA = Fraction(17, 20)

DET_CRITERION = "C-DET"
OPERATIONAL_TYPES = ("accept", "edit", "override")


def _blind_judged() -> list[broken.Label]:
    """The 20, cell by cell, on the matrix's judged criterion."""
    labels = []
    for index, ((system, teacher), count) in enumerate(sorted(T1_TABLE.items())):
        for j in range(count):
            labels.append(
                broken.Label(
                    label_id=f"blind-{index}-{j}",
                    criterion_id="C-01",
                    band=system,
                    teacher_band=teacher,
                )
            )
    return labels


def _operational() -> list[broken.Label]:
    """The 40: `CT-REVIEW-07`'s operational label types, `saw_system_output =
    1`, judged — and disagreeing, so admitting any of them moves the exact κ."""
    return [
        broken.Label(
            label_id=f"op-{i}",
            label_type=OPERATIONAL_TYPES[i % 3],
            origin=OPERATIONAL_TYPES[i % 3],
            criterion_id="C-01",
            saw_system_output=True,
            band=1,
            teacher_band=4,
        )
        for i in range(40)
    ]


def _deterministic() -> list[broken.Label]:
    """The 15 blind labels on the deterministic criterion (`CT-DET-06`'s
    mode) — admissible by every condition but the mode, which is the point."""
    return [
        broken.Label(
            label_id=f"det-{i}",
            criterion_id=DET_CRITERION,
            evaluation_mode="deterministic",
            band=1 + (i % 4),
            teacher_band=1 + (i % 4),
        )
        for i in range(15)
    ]


@pytest.mark.integration
def test_tc_stats_01_agreement_over_the_matrix_is_the_blind_judged_population_only(tmp_data_dir):
    """Steps 1, 4 and 5 over the real store: n = 20, the exact hand-computed
    κ, the deterministic criterion unreachable from every reachable path, and
    the three counters exact — with the operational and deterministic volume
    outside `agreement_kappa` entirely."""
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")
    no_validation = require(STATS_MODULE, "NoValidationData", issue="#115")

    for label in _blind_judged() + _operational() + _deterministic():
        record_label(data_dir=tmp_data_dir, label=label)
    stats = open_stats(data_dir=tmp_data_dir)
    update = stats.promote(cohort_id="coh-spring")

    figure = stats.agreement(**vocab.EMPTY_DATA_CALL["agreement"])

    # Step 1 — exact n and the exact hand-computed coefficients.
    assert figure.n == 20, (
        f"the figure's population is {figure.n}; the plan's matrix holds 20 blind "
        "judged labels and the figure is computed over those only (FR-STATS-01)"
    )
    assert figure.kappa == pytest.approx(float(T1_KAPPA)), (
        "kappa = (3/4 − 127/400)/(1 − 127/400) = 173/273 over the 20 blind judged "
        "labels — and it is this exact value only if every operational and "
        "deterministic label stayed out"
    )
    assert figure.qwk == pytest.approx(float(T1_QWK)), (
        "QWK = 1 − (1/36)/(37/225) = 123/148 over the same pairs"
    )
    assert figure.ordinal_alpha == pytest.approx(float(T1_ALPHA)), (
        "alpha = 1 − (1/12)/(5/9) = 17/20 under #91's declared convention"
    )

    # Step 5 — the three counters, exactly, from the same administration.
    actual = {counter: getattr(update, counter) for counter in vocab.PROMOTE_COUNTERS}
    expected = {"cohorts_used": 1, "blind_count": 20, "operational_count": 55}
    assert actual == expected, (
        f"promote reported {actual}, expected {expected}. The 40 operational "
        "labels count as operational — and so do the 15 blind deterministic "
        "ones: inadmissible to a validity claim is operational volume, whatever "
        "the label's type says (FR-STATS-10, RISK-07)"
    )
    assert update.n == 20 and update.agreement_kappa == pytest.approx(float(T1_KAPPA)), (
        "the record's agreement_kappa is the blind population's own figure — no "
        "operational count contributed to it (FR-STATS-10, step 5)"
    )

    # Step 4 — the deterministic criterion is unreachable from every path.
    det_call = dict(vocab.EMPTY_DATA_CALL["agreement"])
    det_call["criterion_id"] = DET_CRITERION
    det_figure = stats.agreement(**det_call)
    assert isinstance(det_figure, no_validation), (
        f"agreement over the deterministic criterion returned {det_figure!r}; "
        "the 15 deterministic blind labels are inadmissible and the figure must "
        "be the absence value, not a number (FR-STATS-01, step 4)"
    )
    assert det_figure.reason == "no_blind_labels"
    assert det_figure.n == 0 and det_figure.excluded_count == 55, (
        "the absence carries what was measured: nothing admissible on C-DET, "
        "and the 55 inadmissible labels named beside it"
    )
    for population, entry in update.weakest_per_population.items():
        assert entry.get("criterion_id") != DET_CRITERION, (
            f"the validation record's weakest-per-population entry for "
            f"{population!r} names the deterministic criterion {entry!r}; a "
            "deterministic criterion has no admissible labels and cannot stand "
            "in any per-criterion figure (step 4, every reachable path)"
        )
    # … and the record's map, exactly: one population keyed by the claimed
    # administration, naming the only criterion with admissible labels, at
    # that population's own hand-computed kappa.
    assert set(update.weakest_per_population) == {"coh-spring"}, (
        f"the record's weakest-per-population map is keyed by the claimed "
        f"administration; it holds {sorted(update.weakest_per_population)!r}"
    )
    assert update.weakest_per_population["coh-spring"] == {
        "criterion_id": "C-01",
        "kappa": pytest.approx(float(T1_KAPPA)),
    }, (
        "the weakest criterion for the administration is C-01 — the only one "
        "with admissible labels — at the population's own kappa (173/273); the "
        "deterministic criterion, with no admissible labels, cannot stand in "
        "any per-criterion figure (step 4, every reachable path)"
    )
    # … and the aggregate's per-scope weakest, the other path a per-criterion
    # figure travels (`aggregate` computes over the admissible population, so
    # the deterministic labels are outside it by the same single filter).
    aggregate = require(STATS_MODULE, "aggregate", issue="#115")
    agg = stats.aggregate()
    for population, entry in agg.weakest_per_population.items():
        assert entry.get("criterion_id") != DET_CRITERION, (
            f"the aggregate's weakest entry for {population!r} names the "
            f"deterministic criterion {entry!r} (step 4, every reachable path)"
        )


@pytest.mark.writtenahead
def test_tc_stats_01_a_null_saw_system_output_is_inadmissible_not_blind(tmp_path):
    """The variant, plan-literal: *"a label whose `saw_system_output` is null —
    must be treated as inadmissible, not as blind."*

    **Written ahead, red by design.** The landed predicate admits a falsy flag
    — `not getattr(label, "saw_system_output", 0)` reads a ``None`` as a 0 —
    with a docstring disclosing why: every shipped producer writes the column
    (`CT-REVIEW-08` step 1 pins no default and no null), so the two are
    "indistinguishable at this predicate" and the enforcement lives at the
    producers. The plan's variant says the *consumer* owes the distinction:
    a null must read as inadmissible, not as blind. The store cannot even hold
    one (`NOT NULL DEFAULT 1`), so this is reachable only at rung 0, over the
    duck-typed shapes the docstring itself names as the accommodation's
    boundary.

    The population is two null-flag labels that disagree — so the current
    behavior produces a *figure* (n = 2, κ = 0.0), which is precisely the
    plausible-looking number the case exists to refuse; plan-literal, the
    population is empty and the answer is the absence value. Registered under
    "#119 null saw_system_output" until the consumer-side treatment lands.
    """
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    no_validation = require(STATS_MODULE, "NoValidationData", issue="#115")

    labels = [
        broken.Label(label_id=f"null-{i}", criterion_id="C-01",
                     saw_system_output=None, band=2, teacher_band=2 + i)
        for i in range(2)
    ]
    stats = build_stats(labels)
    figure = stats.agreement(**vocab.EMPTY_DATA_CALL["agreement"])

    assert isinstance(figure, no_validation), (
        f"a null saw_system_output produced {figure!r}; the plan's variant says "
        "the label is inadmissible — not blind — so the population is empty and "
        "the answer is the absence value, not a figure computed over it"
    )
    assert figure.reason == "no_blind_labels"
    assert figure.n == 0, (
        "the null-flag labels are not blind labels: they are nobody's evidence, "
        "and the figure's n counts none of them"
    )