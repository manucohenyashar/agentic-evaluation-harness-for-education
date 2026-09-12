"""`TC-GRADE-C13` — the criterion figures' null contract, kept distinct from zero end to end (§6.11.14).

`CT-GRADE-13` (data): "Assert `criterion_stats` carries band histogram, band
entropy and interior rate, with entropy and interior rate **null for deterministic
criteria**. Then the consumer obligation: **handle the nulls rather than reading
them as zero** — at rung 3, assert `M-STATS` and `M-CONSOLE` distinguish null from
zero, since an entropy of 0 means perfect agreement and a null means the figure
does not apply, and rendering the first for the second is the §2.1 error repeated."

The limbs, in the row's order:

- **the three figures, exact nulls** (rung 2, green): the producer's own seam
  (`aeh.grade:criterion_band_figures`, the row's `criterion_stats`) carries the
  histogram as a real count under every population, and for a deterministic
  population the derived figures are the exact nulls — entropy `None` and interior
  rate `None`, never zero: "no figure" is a different claim from "no variation".
- **the consumer differential, on the landed chain** (rung 3, green): one rollup
  record carries a judged uniform criterion's REAL 0.0 ("perfect agreement") beside
  a deterministic criterion's `None` ("does not apply") — the null survives the
  producer-to-consumer chain and stays distinct from the kept zero; a chain that
  coerced the null to 0.0 would tell the teacher a criterion in perfect agreement
  when no figure exists at all.
- **the M-STATS half of the obligation** (rung 3, green): the landed analytical
  consumer distinguishes the same two claims on its own figures — a single-band
  population's entropy is a real 0.0 (perfect agreement, measured), an empty
  population's is the explicit `None` (not measured, does not apply).
- **the M-CONSOLE half** (`[m_console]`, writtenahead): the rendered figures must
  present the null as not-applicable, never as a zero reading as perfect
  agreement — the §2.1 error the clause names. The landed console renders no
  criterion figures at all, so this waits on the disclosed
  `aeh.console:render_grade_coverage` (#107), the same render the C04/C05 limbs
  key on.

Isolation: rung 2 for the pure seam; rung 3 for the chain and the M-STATS
differential. The socket guard is autouse; `criterion_score` rows are the
vocabulary's disclosed `M-AGG` stand-in.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from aeh.store import open_store
from tests.contract.grade._drive import graded_run
from tests.support.broken_stats_fixtures import Label
from tests.support.impl import (
    CONSOLE_MODULE,
    GRADE_MODULE,
    STATS_MODULE,
    require,
)

pytestmark = [pytest.mark.contract]

#: The judged rubric's declared band order — three bands, so the interior exists
#: when the order is declared and is empty when only two bands are.
_THREE_BAND_ORDER = ("B1", "B2", "B3")


def _scores(criterion_id: str, bands: list[str]) -> list[SimpleNamespace]:
    """The population `criterion_band_figures` consumes — one row per band, the
    shape the stored `criterion_score` row reads back as."""
    return [
        SimpleNamespace(
            criterion_id=criterion_id, band=band, points=0.0,
            routing="auto", state="final",
        )
        for band in bands
    ]


def test_tc_grade_c13_the_figures_carry_exact_nulls_for_deterministic_criteria():
    """`TC-GRADE-C13` (`CT-GRADE-13`, rung 2) — the producer's exact null contract,
    on hand-computed constants: the histogram is a real count under every
    population; a deterministic population's entropy and interior rate are the
    exact `None`s; a judged population's entropy is the real nats figure; a judged
    UNIFORM population keeps a REAL 0.0 (perfect agreement is a measurement, and
    replacing it with a null would erase the one figure the teacher can read)."""
    criterion_band_figures = require(
        GRADE_MODULE, "criterion_band_figures", issue="#101"
    )

    # Deterministic population: M-DET's own band vocabulary.
    deterministic = criterion_band_figures(
        _scores("C-MCQ", ["correct", "correct", "incorrect"]),
    )
    (figure,) = deterministic
    assert dict(figure.histogram) == {"correct": 2, "incorrect": 1}, (
        f"the histogram reads {figure.histogram!r} — a real count under every "
        "population, deterministic ones included (CT-GRADE-13)"
    )
    assert figure.entropy is None and figure.interior_rate is None, (
        f"the deterministic figure reads ({figure.entropy!r}, "
        f"{figure.interior_rate!r}) — the derived figures are the exact NULLS, "
        "never zero: no figure is a different claim from no variation "
        "(CT-GRADE-13's exact nulls)"
    )

    # Judged, mixed: real entropy in nats, and the declared order's interior rate.
    judged = criterion_band_figures(
        _scores("C-J", ["B1", "B2", "B1"]),
        band_order=_THREE_BAND_ORDER,
    )
    (judged_figure,) = judged
    assert judged_figure.entropy == pytest.approx(0.6365141682948128), (
        f"the judged entropy reads {judged_figure.entropy!r} — the Shannon "
        "entropy of the 2/3-1/3 distribution, in nats (CT-GRADE-13)"
    )
    assert judged_figure.interior_rate == pytest.approx(1 / 3), (
        f"the interior rate reads {judged_figure.interior_rate!r} — one of three "
        "bands sits strictly inside the declared order (CT-GRADE-13)"
    )

    # Judged UNIFORM: the real zero — perfect agreement is a figure.
    uniform = criterion_band_figures(
        _scores("C-U", ["B1", "B1"]),
        band_order=_THREE_BAND_ORDER,
    )
    (uniform_figure,) = uniform
    assert uniform_figure.entropy == 0.0 and uniform_figure.entropy is not None, (
        f"the uniform judged population's entropy reads {uniform_figure.entropy!r} "
        "— a single-band population is genuinely 0.0, PERFECT AGREEMENT, and the "
        "producer keeps the real zero (CT-GRADE-13's null-vs-zero line)"
    )

    # The interior-empty limb: an order of exactly two bands has no interior, and
    # the figure says so with None — a measured-nothing zero would read as a shape.
    two = criterion_band_figures(
        _scores("C-TWO", ["B1", "B2"]),
        band_order=("B1", "B2"),
    )
    (two_figure,) = two
    assert two_figure.entropy is not None and two_figure.interior_rate is None, (
        f"the two-band population reads ({two_figure.entropy!r}, "
        f"{two_figure.interior_rate!r}) — entropy stays real, the interior rate is "
        "None: no interior exists to measure (CT-GRADE-13)"
    )
    # An undeclared band is not interior, and still counts in the denominator —
    # a real score outside the known interior, not a hidden one.
    foreign = criterion_band_figures(
        _scores("C-F", ["B1", "B9", "B9"]),
        band_order=_THREE_BAND_ORDER,
    )
    (foreign_figure,) = foreign
    assert foreign_figure.interior_rate == pytest.approx(0.0), (
        f"the undeclared band's rate reads {foreign_figure.interior_rate!r} — the "
        "B9 rows are real scores outside the known interior and still count in "
        "the denominator (CT-GRADE-13)"
    )
    assert math.isfinite(judged_figure.entropy), "fixture bug: the entropy is finite"


def test_tc_grade_c13_the_chain_keeps_null_and_zero_distinct(tmp_data_dir):
    """`TC-GRADE-C13`'s chain limb (rung 3) — the consumer obligation on the landed
    chain: ONE rollup record carries a judged uniform criterion's REAL 0.0 beside a
    deterministic criterion's `None`, and the record's reader can tell which is
    which. A chain that coerced the null to zero (or the zero to a null) merges
    "perfect agreement" into "does not apply" — the §2.1 error, upstream."""
    separated_rollup = require(GRADE_MODULE, "separated_rollup", issue="#104")
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-A", "S-B"),
            criteria=(
                {"criterion_id": "C-U", "kind": "open", "scoring_model": "atomic"},
                {"criterion_id": "C-M", "kind": "mcq", "scoring_model": "atomic"},
            ),
            rows=(
                ("S-A", "C-U", "B1", 6.0, "auto"),
                ("S-B", "C-U", "B1", 6.0, "auto"),
                ("S-A", "C-M", "correct", 4.0, "auto"),
                ("S-B", "C-M", "incorrect", 1.0, "auto"),
            ),
        )
        rollup = separated_rollup(world.run_id, store)
        judged = {
            figure.criterion_id: figure for figure in rollup.judged.criteria
        }
        deterministic = {
            figure.criterion_id: figure for figure in rollup.deterministic.criteria
        }
        assert judged["C-U"].entropy == 0.0, (
            f"the judged uniform criterion's entropy reaches the consumer as "
            f"{judged['C-U'].entropy!r} — perfect agreement is the REAL zero, and "
            "a chain that nulled it erases the one figure the teacher can read "
            "(CT-GRADE-13's null-vs-zero line)"
        )
        assert deterministic["C-M"].entropy is None, (
            f"the deterministic criterion's entropy reaches the consumer as "
            f"{deterministic['C-M'].entropy!r} — the null survives the chain; a "
            "coerced 0.0 would read as perfect agreement on a criterion that was "
            "never judged (CT-GRADE-13's exact nulls at the consumer)"
        )
        assert deterministic["C-M"].interior_rate is None, (
            "the deterministic criterion's interior rate did not survive the chain "
            "as the exact null (CT-GRADE-13)"
        )
        assert dict(deterministic["C-M"].histogram) == {
            "correct": 1, "incorrect": 1,
        }, (
            f"the deterministic histogram reads {deterministic['C-M'].histogram!r} "
            "— the nulls withhold the derived figures, never the real counts "
            "(CT-GRADE-13)"
        )
    finally:
        store.close()


def test_tc_grade_c13_m_stats_distinguishes_null_from_zero():
    """`TC-GRADE-C13`'s M-STATS limb (`CT-GRADE-13`'s consumer obligation, rung 3) —
    the landed analytical consumer keeps the two claims apart on its own figures: a
    single-band population's entropy is the REAL 0.0 (perfect agreement, measured),
    an empty population's is the explicit `None` (nothing measured). Rendering the
    first for the second is the §2.1 error the clause forbids."""
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    compression_check = require(STATS_MODULE, "compression_check", issue="#117")

    # Perfect agreement: one band, four labels — the REAL zero.
    unanimous = build_stats(labels=[
        Label(label_id=f"u-{i}", band=2, teacher_band=2) for i in range(4)
    ])
    measured = unanimous.compression_check()
    assert measured.gold.band_entropy == 0.0, (
        f"the single-band population's entropy reads {measured.gold.band_entropy!r} "
        "— perfect agreement is a MEASURED 0.0; nulling it would hide agreement "
        "the same way zeroing a null fakes it (CT-GRADE-13's consumer obligation, "
        "M-STATS)"
    )
    assert measured.n == 4, "fixture bug: the single-band population is four pairs"

    # Nothing measured: the explicit null, never a zero.
    empty = build_stats(labels=())
    unmeasured = empty.compression_check()
    assert unmeasured.gold.band_entropy is None and unmeasured.gold.interior_rate is None, (
        f"the empty population's shape reads ({unmeasured.gold.band_entropy!r}, "
        f"{unmeasured.gold.interior_rate!r}) — no distribution, no figure: the "
        "explicit None, never a zero that would read as a measured shape "
        "(CT-GRADE-13's consumer obligation, M-STATS)"
    )
    assert unmeasured.n == 0, "fixture bug: the empty population is zero pairs"


def test_tc_grade_c13_the_console_presents_a_null_figure_as_not_applicable(
    tmp_data_dir,
):
    """`TC-GRADE-C13`'s M-CONSOLE limb (`CT-GRADE-13`, `[m_console]`, rung 3) — the
    rendered criterion figures distinguish null from zero: a deterministic
    criterion's withheld entropy must present as not-applicable, never as a zero
    that reads as perfect agreement.

    Writtenahead on the disclosed `aeh.console:render_grade_coverage` (#107) — the
    same render the C04/C05 limbs key on: the landed console renders no criterion
    figures, so the consumer obligation waits on that landing."""
    require(GRADE_MODULE, "separated_rollup", issue="#104")
    render_grade_coverage = require(
        CONSOLE_MODULE, "render_grade_coverage", issue="#107"
    )
    store = open_store(tmp_data_dir)
    try:
        world = graded_run(
            store,
            submissions=("S-A",),
            criteria=(
                {"criterion_id": "C-M", "kind": "mcq", "scoring_model": "atomic"},
            ),
            rows=(("S-A", "C-M", "correct", 4.0, "auto"),),
        )
        rendered = render_grade_coverage(world.run_id, "S-A", store=store)
        text = rendered if isinstance(rendered, str) else str(rendered)
        assert "does not apply" in text.lower() or "null" in text.lower() or (
            "not measured" in text.lower()
        ), (
            f"the console renders the deterministic criterion's withheld entropy "
            f"as {text[:80]!r}... — the null must present as not-applicable, not "
            "as a figure (CT-GRADE-13's consumer limb, M-CONSOLE)"
        )
        assert "perfect agreement" not in text.lower(), (
            "the console presents a withheld figure as perfect agreement — the "
            "§2.1 error the clause names (CT-GRADE-13, M-CONSOLE)"
        )
    finally:
        store.close()
