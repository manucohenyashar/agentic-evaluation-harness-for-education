"""`TC-STATS-04` — the F-STATS table, hand-computed agreement references.

Test plan §5.16, issue #119 (TS-42). Traces to `FR-STATS-02`/`-04` and
`NFR-STATS-01`. The plan's row: *"Non-degenerate case: exact agreement values.
Degenerate cases: behaviour is exactly as specified — the absence value, not
zero."* Seven rows of the F-STATS table, each with its population built
cell-by-cell below and every statistic checked against a hand-computed
reference carried in Fractions, term by term.

**The conventions the references are computed under** (declared, as #91's
`ordinal_alpha` hand-oracle convention is declared):

- kappa = (po − pe)/(1 − pe), pe = Σ_c (sys_c/n)(tea_c/n) over the **union**
  of the categories either side used, and `None` at pe = 1.
- QWK = 1 − Σ joint/n·w / Σ (sys_a/n)(tea_b/n)·w with w = (i−j)²/(K−1)² over
  the **declared** band scale, `None` below K = 2 or at a zero denominator.
- ordinal alpha under #91's declared convention: α = 1 − D_o/D_e with
  D_o = Σ|sys − tea|/n/(K−1) and D_e = [Σ_{a≠b}|a−b|]/(K−1)/(K(K−1)) — the
  uniform expectation; the unanimous panel returns the **exact** 1.0 before
  the band-count test. §3.12's Krippendorff-coincidence `TBD` is reconciled
  the way #91 reconciles it at landing; the convention's statement is the
  reconciliation.

Worked reference, row 1's population (the arithmetic every row's test
docstring carries in shorter form; all sums checked term by term):

    table (system band, teacher band) -> count:
        (1,1):8 (1,2):2 (2,1):1 (2,2):10 (2,3):2 (3,3):9 (3,4):2 (4,3):1 (4,4):5
    n = 40; po = 32/40 = 4/5 (8+10+9+5 agreeing)
    marginals  sys = (10, 13, 11, 6)   tea = (9, 12, 12, 7)
    pe = (10·9 + 13·12 + 11·12 + 6·7)/1600 = 420/1600 = 21/80
    kappa = (4/5 − 21/80)/(59/80) = (43/80)/(59/80) = 43/59
    QWK: num = Σ joint/n·w — off-diagonal cells 2,1,2,2,1 at distances
         1,1,1,1,1 over scale 3 → num = 8/(40·9) = 1/45
         den = Σ sys_a·tea_b/n²·w — adjacent marginals 674/1600·(1/9),
         distance-2 marginals 382/1600·(4/9), distance-3 124/1600
         → 3318/14400 = 553/2400
         QWK = 1 − (1/45)/(553/2400) = 1 − 160/1659 = 1499/1659
    alpha: D_o = (2+1+2+2+1)/40/3 = 8/120 = 1/15; D_e = 5/9 (#91's hand value
         for the 4-band scale) → α = 1 − (1/15)/(5/9) = 1 − 3/25 = 22/25

The row-1 population is also the case's **no-raw-percent** witness: its raw
agreement is 4/5 and every figure here carries the chance-corrected number
beside it — the surface sweep that no function emits a bare percent figure is
`TC-STATS-C02`'s (`test_ct_stats_figures_and_keying.py`), and this file pins
the values instead of repeating the sweep.

The two-band rows carry the Q-03 disclosure the issue asks for: the design
doc keeps the confusion matrix as a TBD resolution option for the binary-band
degeneracy, and the landed disclosure vehicle is the figure's
`degenerate_band_shape` field (`CT-STATS-C21`) — this file asserts that field
exactly where the plan's table says the degenerate rows are flagged.

Row 7 has two halves. The figure's own values are green here; the console
*qualifier* half — below `STATS_MIN_N_FOR_HEADLINE` the headline renders with
"too few to draw conclusions from" (HLD §11.5's S12 mock renders it at n = 15)
— is unlanded: `render_agreement_block` today renders no qualifier. That leg
is `writtenahead` and carried in `WRITTEN_AHEAD_BLOCKERS` under "#119".

Isolation: rung 0 — pure functions over in-memory labels. Interface: the
landed `build_stats`/`agreement` surface (#115) and `aeh.console`'s
`render_agreement_block` (#123/#125).
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import CONSOLE_MODULE, STATS_MODULE, require

pytestmark = pytest.mark.contract

CRITERION = "C-01"


def _labels(table: dict[tuple[int, int], int], prefix: str) -> list:
    """The table's labels: `(system band, teacher band) -> count`, expanded."""
    labels = []
    for index, ((system, teacher), count) in enumerate(sorted(table.items())):
        for j in range(count):
            labels.append(
                broken.Label(
                    label_id=f"{prefix}-{index}-{j}",
                    band=system,
                    teacher_band=teacher,
                )
            )
    return labels


def _figure(table: dict[tuple[int, int], int], band_count: int, prefix: str):
    """The agreement figure the table produces, over a declared 4-band (or
    2-band) criterion — the declaration the plan's table rows name."""
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(
        _labels(table, prefix),
        scoring_models={CRITERION: "atomic"},
        band_counts={CRITERION: band_count},
    )
    call = dict(vocab.EMPTY_DATA_CALL["agreement"])
    call["criterion_id"] = CRITERION
    return stats.agreement(**call)


# --- row 1 — the non-degenerate reference -------------------------------------------------------


def test_tc_stats_04_row1_the_40_label_4_band_population_matches_the_hand_computed_fractions():
    """Row 1 — 40 blind judged labels on a 4-band criterion, moderate
    disagreement: κ = 43/59, QWK = 1499/1659, α = 22/25 (`FR-STATS-02`).

    The full derivation is this module's docstring. The raw agreement is
    4/5 — asserted only to show the chance-corrected numbers are not it:
    `FR-STATS-02` allows no percent figure without its chance-corrected
    counterpart, and 0.8 is what a raw-percent implementation would report."""
    figure = _figure(
        {
            (1, 1): 8, (1, 2): 2, (2, 1): 1, (2, 2): 10, (2, 3): 2,
            (3, 3): 9, (3, 4): 2, (4, 3): 1, (4, 4): 5,
        },
        band_count=4,
        prefix="row1",
    )
    assert figure.n == 40
    assert figure.degenerate_band_shape is False
    assert figure.kappa == pytest.approx(float(Fraction(43, 59))), (
        "kappa = (po − pe)/(1 − pe) = (4/5 − 21/80)/(59/80) = 43/59 — the "
        "hand-computed reference; a po-only or mis-marginaled pe fails here"
    )
    assert figure.qwk == pytest.approx(float(Fraction(1499, 1659))), (
        "QWK = 1 − (1/45)/(553/2400) = 1499/1659 — the quadratic-weighted "
        "reference over the declared 4-band scale"
    )
    assert figure.ordinal_alpha == pytest.approx(float(Fraction(22, 25))), (
        "alpha = 1 − D_o/D_e = 1 − (1/15)/(5/9) = 22/25 — #91's convention"
    )


# --- row 2 — the single-label population --------------------------------------------------------


def test_tc_stats_04_row2_a_single_label_is_an_absence_carrying_what_was_measured():
    """Row 2 — one blind judged label: `NoValidationData`, **not** κ = 1 and
    **not** κ = 0. Both would be a finding invented from a sample of one; the
    absence carries the n it did measure and the interval that n can honestly
    buy (`NFR-STATS-01`, `FR-STATS-04`).

    The interval is the worst-case band: ±1.96·√(0.25/n) = ±0.98 at n = 1,
    centred on zero because no coefficient is computable over one pair."""
    figure = _figure({(3, 3): 1}, band_count=4, prefix="row2")
    assert figure.reason == "no_blind_labels"
    assert figure.n == 1
    assert figure.excluded_count == 0
    assert figure.interval_low == pytest.approx(-0.98)
    assert figure.interval_high == pytest.approx(0.98)


# --- rows 3 and 4 — the degenerate cases the plan names by construction -------------------------


def test_tc_stats_04_row3_thirty_unanimous_4_band_labels_score_exact_one_alpha_only():
    """Row 3 — 30 unanimous labels on a 4-band criterion: ordinal α is the
    **exact** 1.0 (#91's unanimous branch, before any band-count test), while
    κ and QWK are `None` — po = pe = 1 is 0/0, and a figure reporting κ = 1
    for a population whose marginals are degenerate would be manufacturing a
    chance-corrected claim from a 0/0 (`NFR-STATS-01`)."""
    figure = _figure({(4, 4): 30}, band_count=4, prefix="row3")
    assert figure.n == 30
    assert figure.kappa is None, "pe = 1: every chance-corrected number is 0/0"
    assert figure.qwk is None, "all mass on the diagonal drives the QWK denominator to 0"
    assert figure.ordinal_alpha == 1.0, "unanimity is exact — the reference, not an approximation"
    assert figure.degenerate_band_shape is False


def test_tc_stats_04_row4_a_two_band_unanimous_population_is_degenerate_by_construction():
    """Row 4 — 30 unanimous labels on a **two-band** criterion: the same
    unanimity figures as row 3, and the population is flagged
    `degenerate_band_shape` — the plan's *"α = 1.0 by construction, flagged
    degenerate with a confusion matrix"* row.

    The confusion matrix is the design's TBD resolution option for the
    binary-band degeneracy (Q-03, design doc); what landed is this disclosure
    field, and this row pins it exactly where the plan's table flags one."""
    figure = _figure({(2, 2): 30}, band_count=2, prefix="row4")
    assert figure.n == 30
    assert figure.kappa is None
    assert figure.qwk is None
    assert figure.ordinal_alpha == 1.0
    assert figure.degenerate_band_shape is True, (
        "a two-band scale makes every agreement statistic degenerate — the "
        "figure must say so beside the number (CT-STATS-C21's disclosure)"
    )


def test_tc_stats_04_row5_two_band_with_one_disagreement_pins_the_kappa_paradox():
    """Row 5 — 30 two-band labels at a 95% base rate with one disagreement:
    κ = 0 and QWK = 0 **exactly**, while raw agreement is 29/30 and α = 29/30.

    This is the kappa paradox, hand-computed: the marginals put pe at
    (30/30)·(29/30) = 29/30 = po, so the chance-corrected coefficient is 0 —
    the same figure a coin flip would earn — under a population that agrees
    29 times in 30. The row is the plan's *"κ unstable"* case: the exact
    zero is the pin, and the gap between 0.9667 raw and 0.0 corrected is
    what a raw-percent implementation hides."""
    figure = _figure({(2, 2): 29, (2, 1): 1}, band_count=2, prefix="row5")
    assert figure.n == 30
    assert figure.degenerate_band_shape is True
    assert figure.kappa == pytest.approx(0.0, abs=1e-12), (
        "po = pe = 29/30 exactly: kappa = 0 — the paradox the row exists to pin"
    )
    assert figure.qwk == pytest.approx(0.0, abs=1e-12), (
        "QWK's numerator and denominator are both 1/30 here: 1 − 1 = 0 exactly"
    )
    assert figure.ordinal_alpha == pytest.approx(float(Fraction(29, 30))), (
        "alpha = 1 − D_o/D_e = 1 − (1/30)/1 = 29/30 — D_e for the two-band "
        "scale is 1, and the single adjacent-band disagreement carries D_o = 1/30"
    )


# --- row 6 — the empty population ---------------------------------------------------------------


def test_tc_stats_04_row6_an_empty_population_is_the_named_absence():
    """Row 6 — no labels at all: `NoValidationData(no_blind_labels)` with n = 0
    (`FR-STATS-04`) — never a zero figure, which is a real point on the scale."""
    figure = _figure({}, band_count=4, prefix="row6")
    assert isinstance(figure, require(STATS_MODULE, "NoValidationData", issue="#115"))
    assert figure.reason == "no_blind_labels"
    assert figure.n == 0
    assert figure.excluded_count == 0


def test_tc_stats_05_a_keyed_population_with_no_blind_labels_carries_the_keyed_absence():
    """`TC-STATS-05` extension — the four scope dimensions are conjunctive keys
    (`C03` provokes the three declared absence reasons); this pins the *fourth*
    keying shape: admissible blind labels exist for `C-01`, and the request
    keys a criterion with none. The answer is the same named absence, n = 0 —
    and `excluded_count` counts the **inadmissible** classes only (5
    operational labels), not the other criterion's blind labels: the keying
    narrows the population, the exclusion count reports the admissibility
    filter, and the two are distinct disclosures on the one absence value."""
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    labels = _labels({(2, 2): 10}, "keyed-blind") + [
        broken.Label(
            label_id=f"keyed-op-{i}",
            label_type="operational",
            evaluation_mode="judged",
        )
        for i in range(5)
    ]
    stats = build_stats(
        labels,
        scoring_models={CRITERION: "atomic"},
        band_counts={CRITERION: 4},
    )
    call = dict(vocab.EMPTY_DATA_CALL["agreement"])
    call["criterion_id"] = "C-404"
    figure = stats.agreement(**call)

    assert figure.reason == "no_blind_labels"
    assert figure.n == 0
    assert figure.excluded_count == 5, (
        "excluded_count is the inadmissible count, not the keyed-out count — "
        "the keying is a scope narrowing, and the absence discloses the two "
        "facts separately"
    )


# --- row 7 — the fifteen-label population and its qualifier -------------------------------------


def test_tc_stats_04_row7_fifteen_labels_match_their_hand_computed_fractions():
    """Row 7, figure half — 15 blind judged labels on a 4-band criterion:
    κ = 7/10, QWK = 6/7, α = 22/25.

    Hand computation (same machinery as row 1, checked term by term):
    table (1,1):5 (1,2):1 (2,2):5 (2,3):1 (3,3):2 (3,4):1, n = 15;
    po = 12/15 = 4/5; marginals sys = (6, 6, 3, 0), tea = (5, 6, 3, 1);
    pe = (6·5 + 6·6 + 3·3)/225 = 75/225 = 1/3 (the system never used band 4,
    so the union's fourth category contributes its teacher-side marginal
    against a zero system side);
    kappa = (4/5 − 1/3)/(2/3) = (7/15)/(2/3) = 7/10;
    QWK: num = 3 cells at distance 1 → 3/(15·9) = 1/45; den = Σ
    sys_a·tea_b/n²·w — the distance-1 marginal products 36+30+18+18+3 = 105
    at w = 1/9, distance-2 18+6+15 = 39 at w = 4/9 (the empty (2,4) cell's
    6·1 included), distance-3 6 at w = 1
    → (105·1 + 39·4 + 6·9)/(9·225) = 315/2025 = 7/45
    → QWK = 1 − (1/45)/(7/45) = 6/7;
    alpha: D_o = (1+1+1)/15/3 = 3/45 = 1/15; D_e = 5/9 → α = 22/25."""
    figure = _figure(
        {(1, 1): 5, (1, 2): 1, (2, 2): 5, (2, 3): 1, (3, 3): 2, (3, 4): 1},
        band_count=4,
        prefix="row7",
    )
    assert figure.n == 15
    assert figure.kappa == pytest.approx(float(Fraction(7, 10))), (
        "kappa = (4/5 − 1/3)/(2/3) = 7/10 — the teacher-side marginal of band 4 "
        "(against a zero system side) is inside pe and outside po"
    )
    assert figure.qwk == pytest.approx(float(Fraction(6, 7))), (
        "QWK = 1 − (1/45)/(7/45) = 6/7 — the empty (2,4) cell still contributes "
        "its marginal product to the denominator"
    )
    assert figure.ordinal_alpha == pytest.approx(float(Fraction(22, 25)))


@pytest.mark.writtenahead
def test_tc_stats_04_row7_the_headline_below_the_declared_n_carries_the_qualifier():
    """Row 7, qualifier half — below `STATS_MIN_N_FOR_HEADLINE` the rendered
    headline carries *"too few to draw conclusions from"* (HLD §11.5's S12
    mock renders exactly this at n = 15).

    **Written ahead**: `render_agreement_block` renders the figure's number,
    size, scope and degeneracy disclosure today, and no qualifier. The
    declared knob exists (`STATS_MIN_N_FOR_HEADLINE = 30`, pinned by
    `TC-STATS-C20`), the vocabulary carries the qualifier string, and the
    rendering is the unlanded half of the row. Red by design until the
    console qualifies the headline; the blocker is recorded under "#119"."""
    render = require(CONSOLE_MODULE, "render_agreement_block", issue="#123")
    figure = _figure(
        {(1, 1): 5, (1, 2): 1, (2, 2): 5, (2, 3): 1, (3, 3): 2, (3, 4): 1},
        band_count=4,
        prefix="row7q",
    )
    rendered = render(figure=figure, population="y9-2026-spring")
    assert vocab.TOO_FEW_QUALIFIER in rendered, (
        f"n = 15 < STATS_MIN_N_FOR_HEADLINE = 30, and the rendered headline "
        f"carries no qualifier: {rendered!r} — HLD §11.5's S12 mock qualifies "
        "the figure with 'too few to draw conclusions from'"
    )