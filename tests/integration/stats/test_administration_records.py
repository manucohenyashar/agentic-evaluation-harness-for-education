"""`TC-STATS-07`, `TC-STATS-09` and `TC-STATS-26` — the administration records.

Test plan §5.16, issue #119 (TS-42). Three cases over the record surface
`promote` writes and the observability surface the module emits:

- **`TC-STATS-07`** (`FR-STATS-10`, Integration / rung 2, P0) — three
  consecutive administrations over one store. The counters move *separately*:
  an administration's record carries its own `cohorts_used` / `blind_count` /
  `operational_count`, never the accumulated totals, and the record's
  `agreement_kappa` moves only when blind labels arrive. Exact values per
  administration: coh-1's 20 blind judged labels read κ = 173/273 (the plan's
  matrix, shared with `TC-STATS-01`); coh-2's operational-only administration
  reads `NO_NEW_VALIDATION_EVIDENCE` and κ = None; coh-3's 15 blind labels read
  κ = 7/10 — and the store-wide figure moves only across that third
  administration, from n = 20 to n = 35 (κ = 55/83, hand-computed below).

- **`TC-STATS-09`** (`FR-STATS-13`, Integration / rung 2, P1 Phase 3.5) — two
  administrations, each carrying two criteria, so the weakest criterion per
  population is a real choice, not the only criterion: coh-a's weakest is C-2
  (κ = 1/3 against C-1's 18/23), coh-b's is C-4 (3/4 against C-3's 4/5) — and
  the aggregate's population-wide weakest is C-2 at 1/3, disclosed under the
  no-scope key the store's labels can support. Multi-criterion administrations
  carry no blended headline (`agreement_kappa` is None; `CT-STATS-04` keeps
  that claim unrepresentable).

- **`TC-STATS-26`** (`FR-STATS-11` + `FR-STATS-01`, Observability / rung 2,
  P1) — two consecutive administrations with the blind sample skipped, and a
  criterion acquiring a surface-proxy flag. The four counters are emitted with
  their contract names over the real store (label counts by type and by origin,
  blind coverage per administration, recomputation duration ≥ 0), and both
  alerts fire with their exact detail — the blind-skip alert over the
  ``administrations=`` channel the constructor declares (the alert detects
  *declared* skips; `record_label`'s collection writes no administration
  history, so the channel is a declared input by design), the surface-proxy
  alert over the declared correlations channel (`M-STATS` holds the
  interpretation; the correlations arrive measured, `FR-STATS-07`).

**Hand computations** (verified term by term in exact fractions during
authoring):

    T1    (coh-1's 20 blind): κ = 173/273  (TC-STATS-01's table)
    SET7  (coh-3's 15 blind): po = 4/5, sys (6, 6, 3, 0), tea (5, 6, 3, 1);
                              pe = (6·5 + 6·6 + 3·3 + 0·1)/225 = 57/225 = 1/3;
                              κ = (4/5 − 1/3)/(2/3) = 7/10
    store-wide after coh-3 (T1 + SET7 pooled, n = 35):
                              po = 27/35, pe = 79/245, κ = 55/83
    coh-a C-1 {(2,2):6,(2,3):1,(3,3):3}:  po = 9/10, pe = 27/50, κ = 18/23
    coh-a C-2 {(1,2):2,(2,2):3,(2,3):2,(3,3):3}: po = 3/5, pe = 2/5, κ = 1/3
    coh-b C-3 {(1,1):4,(1,2):1,(2,2):5}:  po = 9/10, pe = 1/2, κ = 4/5
    coh-b C-4 {(1,1):3,(1,2):1,(2,2):4}:  po = 7/8, pe = 1/2, κ = 3/4

**Isolation: rung 2** — real store, real label rows, two and three separate
`promote` administrations; `network_guard` is autouse and each store case
asserts it.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import REVIEW_MODULE, STATS_MODULE, require

pytestmark = pytest.mark.integration

CALL = dict(vocab.EMPTY_DATA_CALL["agreement"])

T1_KAPPA = Fraction(173, 273)
SET7_KAPPA = Fraction(7, 10)
STORE_WIDE_KAPPA = Fraction(55, 83)

COHA_C1_KAPPA = Fraction(18, 23)
COHA_C2_KAPPA = Fraction(1, 3)
COHB_C3_KAPPA = Fraction(4, 5)
COHB_C4_KAPPA = Fraction(3, 4)


def _from_table(table: dict[tuple[int, int], int], prefix: str,
                criterion: str) -> list[broken.Label]:
    """The table's blind judged labels, `(system band, teacher band) -> count`."""
    labels = []
    for index, ((system, teacher), count) in enumerate(sorted(table.items())):
        for j in range(count):
            labels.append(
                broken.Label(
                    label_id=f"{prefix}-{index}-{j}",
                    criterion_id=criterion,
                    band=system,
                    teacher_band=teacher,
                )
            )
    return labels


def _operational(count: int, prefix: str, *, label_type: str | None = None,
                 origin: str | None = None) -> list[broken.Label]:
    """Operational labels, disagreeing (band 1, teacher band 4) so a filter
    that admits any of them moves the exact κ."""
    types = ("accept", "edit", "override")
    return [
        broken.Label(
            label_id=f"{prefix}-{i}",
            label_type=label_type or types[i % 3],
            origin=origin or (label_type or types[i % 3]),
            criterion_id="C-01",
            saw_system_output=True,
            band=1,
            teacher_band=4,
        )
        for i in range(count)
    ]


def _blind20() -> list[broken.Label]:
    """coh-1's 20 blind judged labels — `TC-STATS-01`'s table, κ = 173/273."""
    return _from_table(
        {(1, 1): 6, (1, 2): 2, (2, 2): 5, (2, 3): 2, (3, 3): 4, (3, 4): 1},
        "b20", "C-01",
    )


def _op40() -> list[broken.Label]:
    """coh-1's 40 operational labels, disagreeing, `CT-REVIEW-07`'s types."""
    return _operational(40, "op")


def _op30() -> list[broken.Label]:
    """coh-2's 30 operational labels — the administration whose blind sample
    is skipped."""
    return _operational(30, "op2", label_type="accept", origin="accept")


def _blind15() -> list[broken.Label]:
    """coh-3's 15 blind judged labels — the SET7 table, κ = 7/10."""
    return _from_table(
        {(1, 1): 5, (1, 2): 1, (2, 2): 5, (2, 3): 1, (3, 3): 2, (3, 4): 1},
        "b15", "C-01",
    )


def _record(record_label, tmp_data_dir, labels: list[broken.Label]) -> None:
    for label in labels:
        record_label(data_dir=tmp_data_dir, label=label)


# --- TC-STATS-07 — three administrations, counters separate, figure blind-only ---


def test_tc_stats_07_the_counters_move_separately_and_kappa_only_with_blind_labels(
    tmp_data_dir, network_guard
):
    """`TC-STATS-07` (`FR-STATS-10`, integration / rung 2, P0) — three
    administrations: blind+operational, then operational-only, then blind
    again. Each record counts its own claimed labels; the store-wide figure
    stands still through the operational-only administration and moves only
    when coh-3's blind labels arrive."""
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")
    no_new = require(STATS_MODULE, "NO_NEW_VALIDATION_EVIDENCE", issue="#118")
    stats = open_stats(data_dir=tmp_data_dir)

    # Administration 1 — 20 blind judged + 40 operational, claimed to coh-1.
    _record(record_label, tmp_data_dir, _blind20() + _op40())
    update1 = stats.promote(cohort_id="coh-1")
    actual1 = {counter: getattr(update1, counter) for counter in vocab.PROMOTE_COUNTERS}
    assert actual1 == {"cohorts_used": 1, "blind_count": 20, "operational_count": 40}, (
        f"coh-1's record counted {actual1}; its own claimed labels are 20 blind "
        "and 40 operational — each counter its own, never a merged total "
        "(CT-STATS-06, FR-STATS-10)"
    )
    assert update1.n == 20 and update1.agreement_kappa == pytest.approx(float(T1_KAPPA)), (
        "coh-1's kappa is the blind population's own figure (173/273)"
    )
    assert update1.message == "", (
        f"coh-1's record message is {update1.message!r}; an administration that "
        "ran its blind sample raises no no-new-evidence message"
    )
    assert update1.weakest_per_population == {
        "coh-1": {"criterion_id": "C-01", "kappa": pytest.approx(float(T1_KAPPA))}
    }, (
        f"coh-1's weakest map is {dict(update1.weakest_per_population)!r}; one "
        "population, the single criterion with admissible labels, at its own kappa"
    )

    # Administration 2 — operational volume only, the blind sample skipped.
    _record(record_label, tmp_data_dir, _op30())
    update2 = stats.promote(cohort_id="coh-2")
    actual2 = {counter: getattr(update2, counter) for counter in vocab.PROMOTE_COUNTERS}
    assert actual2 == {"cohorts_used": 1, "blind_count": 0, "operational_count": 30}, (
        f"coh-2's record counted {actual2}; the operational volume is counted, "
        "separately, and the blind count stands at zero (FR-STATS-10)"
    )
    assert update2.n == 0 and update2.agreement_kappa is None, (
        f"coh-2's record reports n={update2.n} kappa={update2.agreement_kappa!r}; "
        "no blind labels means no figure — not the previous one carried forward"
    )
    assert update2.message == no_new, (
        f"coh-2's message is {update2.message!r}; the skipped blind sample is "
        "the first-class absence value, not silence (CT-STATS-05)"
    )
    assert update2.weakest_per_population == {
        "coh-2": {"criterion_id": None, "kappa": None}
    }, (
        f"coh-2's weakest map is {dict(update2.weakest_per_population)!r}; an "
        "empty population discloses that no criterion is computable — the "
        "disclosure, not a zero"
    )

    # The figure did not move: operational-only volume changes nothing.
    figure2 = stats.agreement(**CALL)
    assert figure2.n == 20 and figure2.kappa == pytest.approx(float(T1_KAPPA)), (
        f"after coh-2's operational-only administration the figure is "
        f"(n={figure2.n}, kappa={figure2.kappa!r}); the blind population's own "
        "figure stands (FR-STATS-10: agreement_kappa moves only with blind labels)"
    )

    # Administration 3 — blind labels arrive again.
    _record(record_label, tmp_data_dir, _blind15())
    update3 = stats.promote(cohort_id="coh-3")
    actual3 = {counter: getattr(update3, counter) for counter in vocab.PROMOTE_COUNTERS}
    assert actual3 == {"cohorts_used": 1, "blind_count": 15, "operational_count": 0}, (
        f"coh-3's record counted {actual3}; its own claimed labels are the 15 "
        "blind ones only — the earlier administrations' labels stay theirs"
    )
    assert update3.n == 15 and update3.agreement_kappa == pytest.approx(float(SET7_KAPPA)), (
        "coh-3's kappa is its own population's figure: (4/5 − 1/3)/(2/3) = 7/10"
    )
    assert update3.message == "", "coh-3 ran its blind sample; no absence message"

    # The store-wide figure moved only across the third administration.
    figure3 = stats.agreement(**CALL)
    assert figure3.n == 35, (
        f"the figure's population is {figure3.n}: coh-1's 20 blind plus coh-3's "
        "15 — the operational volume of two administrations moved nothing"
    )
    assert figure3.kappa == pytest.approx(float(STORE_WIDE_KAPPA)), (
        f"the figure over both blind populations is kappa = {figure3.kappa!r}; "
        f"the pooled hand value is {float(STORE_WIDE_KAPPA):.6f} (55/83) — it "
        "moved only when blind labels arrived (TC-STATS-07's oracle)"
    )
    network_guard.assert_no_network()


# --- TC-STATS-09 — the weakest criterion per population, exposed exactly --------


def test_tc_stats_09_the_weakest_criterion_per_population_alongside_the_aggregate(
    tmp_data_dir, network_guard
):
    """`TC-STATS-09` (`FR-STATS-13`, integration / rung 2, P1 Phase 3.5) — two
    administrations, each carrying two criteria, so "weakest per population" is
    a real choice: coh-a's weakest is C-2 (1/3, against C-1's 18/23), coh-b's
    is C-4 (3/4, against C-3's 4/5). The aggregate exposes the population-wide
    weakest — C-2 at 1/3 — under the no-scope key the store's labels support."""
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")

    # coh-a: two criteria, deliberately different mixtures.
    coh_a = _from_table({(2, 2): 6, (2, 3): 1, (3, 3): 3}, "ca1", "C-1")
    coh_a += _from_table({(1, 2): 2, (2, 2): 3, (2, 3): 2, (3, 3): 3}, "ca2", "C-2")
    # coh-b: two more criteria, weakest again a real choice.
    coh_b = _from_table({(1, 1): 4, (1, 2): 1, (2, 2): 5}, "cb3", "C-3")
    coh_b += _from_table({(1, 1): 3, (1, 2): 1, (2, 2): 4}, "cb4", "C-4")

    stats = open_stats(data_dir=tmp_data_dir)
    _record(record_label, tmp_data_dir, coh_a)
    update_a = stats.promote(cohort_id="coh-a")
    assert update_a.agreement_kappa is None, (
        f"coh-a's record carries agreement_kappa={update_a.agreement_kappa!r}; a "
        "multi-criterion administration has its per-criterion figures in the "
        "weakest map and no blended headline (CT-STATS-04 keeps that claim "
        "unrepresentable)"
    )
    assert update_a.weakest_per_population == {
        "coh-a": {"criterion_id": "C-2", "kappa": pytest.approx(float(COHA_C2_KAPPA))}
    }, (
        f"coh-a's weakest map is {dict(update_a.weakest_per_population)!r}; the "
        "weakest of C-1 (18/23) and C-2 (1/3) is C-2 — the exact value, not the "
        "only criterion read as the weakest (FR-STATS-13)"
    )

    _record(record_label, tmp_data_dir, coh_b)
    update_b = stats.promote(cohort_id="coh-b")
    assert update_b.agreement_kappa is None, (
        f"coh-b's record carries agreement_kappa={update_b.agreement_kappa!r}; "
        "likewise no blended headline"
    )
    assert update_b.weakest_per_population == {
        "coh-b": {"criterion_id": "C-4", "kappa": pytest.approx(float(COHB_C4_KAPPA))}
    }, (
        f"coh-b's weakest map is {dict(update_b.weakest_per_population)!r}; the "
        "second population's weakest is a different criterion at a different "
        "value — C-4 at 3/4, not coh-a's C-2 carried across populations"
    )

    # The aggregate, exposed alongside: the population-wide weakest, under the
    # no-scope key (the store's labels carry no per-label scope, and the
    # aggregate discloses that rather than inventing a split).
    aggregate = require(STATS_MODULE, "aggregate", issue="#115")
    agg = stats.aggregate()
    assert agg.population_scopes == ("",), (
        f"the aggregate's declared scopes are {agg.population_scopes!r}; the "
        "store's labels carry no per-label scope, and the aggregate says so"
    )
    assert agg.weakest_per_population == {
        "": {"criterion_id": "C-2", "kappa": pytest.approx(float(COHA_C2_KAPPA))}
    }, (
        f"the aggregate's weakest map is {dict(agg.weakest_per_population)!r}; "
        "the population-wide weakest over all four criteria is C-2 at 1/3 — "
        "exposed alongside the aggregate, never instead of the per-population "
        "records (FR-STATS-13)"
    )
    network_guard.assert_no_network()


# --- TC-STATS-26 — the four counters and both alerts ----------------------------


def test_tc_stats_26_the_four_counters_are_emitted_over_the_real_store(
    tmp_data_dir, network_guard
):
    """`TC-STATS-26` (`FR-STATS-11`, integration / rung 2, P1) — two
    consecutive administrations, coh-2's blind sample skipped: the four
    contract counters are emitted with their exact values, and the
    recomputation duration is a measured non-negative number. The record
    carries the surface-proxy flags it measured — none, no correlations
    channel being declared at rung 2 (the declared-channels leg below)."""
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")
    no_new = require(STATS_MODULE, "NO_NEW_VALIDATION_EVIDENCE", issue="#118")
    stats = open_stats(data_dir=tmp_data_dir)

    _record(record_label, tmp_data_dir, _from_table({(2, 2): 10}, "c26", "C-01"))
    update1 = stats.promote(cohort_id="coh-1")
    assert update1.message == "" and update1.blind_count == 10

    skipped = _operational(8, "c26op", label_type="accept", origin="accept")
    _record(record_label, tmp_data_dir, skipped)
    update2 = stats.promote(cohort_id="coh-2")
    assert update2.blind_count == 0 and update2.message == no_new, (
        "the second administration skipped its blind sample: the record says so "
        "as a first-class value (CT-STATS-05)"
    )

    counters = stats.observability_counters()
    assert counters["label_count_by_type"] == {"blind": 10, "accept": 8}, (
        f"label_count_by_type is {counters['label_count_by_type']!r}; type is "
        "blind versus operational, counted separately (FR-STATS-11) — collapsing "
        "it would make the skipped blind sample invisible in the type counter"
    )
    assert counters["label_count_by_origin"] == {"blind_sample": 10, "accept": 8}, (
        f"label_count_by_origin is {counters['label_count_by_origin']!r}; origin "
        "is `CT-ORCH-15`'s random arm versus the rest, a second counter because "
        "collapsing the two makes the random arm invisible (FR-STATS-11)"
    )
    assert counters["blind_coverage_per_administration"] == {"coh-1": 10}, (
        f"blind_coverage_per_administration is "
        f"{counters['blind_coverage_per_administration']!r}; coh-1's ten blind "
        "labels and nothing for coh-2 — the skipped blind sample reads in the "
        "coverage, not only in the record's message"
    )
    duration = counters["statistics_recomputation_duration"]
    assert isinstance(duration, float) and duration >= 0.0, (
        f"statistics_recomputation_duration is {duration!r}; a measured, "
        "non-negative number — the cost of the recomputation the last "
        "administration ran (FR-STATS-11)"
    )
    assert update2.surface_proxy_flags == (), (
        f"the record carries the surface-proxy flags {update2.surface_proxy_flags!r}; "
        "no correlations channel is declared at rung 2, and the record says so "
        "rather than inventing flags"
    )
    network_guard.assert_no_network()


def test_tc_stats_26_both_alerts_fire_with_their_exact_detail():
    """`TC-STATS-26` (`CT-STATS-19`, rung 0 — the declared channels) — a
    criterion acquiring a surface-proxy flag and two consecutive
    administrations without a blind sample provoke both alerts, each with its
    exact name and detail; the clean control provokes neither."""
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    surface_alert_name = require(STATS_MODULE, "SURFACE_PROXY_ALERT", issue="#115")
    skip_alert_name = require(
        STATS_MODULE, "BLIND_SAMPLE_SKIPPED_ALERT", issue="#115"
    )

    # The correlated case: 0.85 reaches the 0.7 threshold, 0.2 does not — the
    # detail names the flagged feature, at the measured value.
    stats = build_stats(
        administrations=[
            {"cohort_id": "coh-1", "blind_sample": False},
            {"cohort_id": "coh-2", "blind_sample": False},
        ],
        surface_correlations={"C-01": {"answer_length": 0.85, "text_length": 0.2}},
    )
    alerts = stats.alerts()
    assert [(alert.name, alert.detail) for alert in alerts] == [
        (surface_alert_name, "C-01: answer_length r=+0.85"),
        (skip_alert_name, "2 consecutive administrations without a blind sample: coh-1, coh-2"),
    ], (
        f"the alerts are {[(a.name, a.detail) for a in alerts]!r}; both fire, "
        "each with its contract name and exact detail — the flagged criterion "
        "and feature at the measured correlation, and the skip run naming the "
        "administrations that ran blind (CT-STATS-19)"
    )

    # The clean control: the blind sample ran, no correlations reach the
    # threshold — no alert fires at all.
    clean = build_stats(
        administrations=[{"cohort_id": "coh-1", "blind_sample": True}],
        surface_correlations={"C-01": {"answer_length": 0.2}},
    )
    assert clean.alerts() == (), (
        "the clean control fired {clean.alerts()!r}; an administration that ran "
        "its blind sample under an unflagged criterion is alert-free"
    )
