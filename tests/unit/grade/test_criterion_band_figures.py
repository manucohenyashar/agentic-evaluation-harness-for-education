"""`TC-GRADE-14` — the per-criterion band figures: histogram, entropy, interior rate.

Test plan §5.14; `FR-GRADE-14` ("criterion_stats ... band histogram, band entropy, and
interior rate ... entropy and interior rate **null for deterministic criteria**");
Unit / 0; hand-computed reference; P1.

**Written ahead of implementation** (test plan §8.2). The figures have no shipped
surface: `criterion_stats` (store.py's Tier D migration) carries
`(package_version_id, criterion_id, backend_profile, panel_build_ref, n)` and **no**
band-histogram, entropy or interior-rate column, and nothing in `aeh.grade` computes
them. `#104` — *"Class rollup, criterion statistics, rubric findings and export"*, whose
first acceptance criterion is exactly this case — lands them, so this file carries
`@pytest.mark.writtenahead` and its registry entry names the symbol below.

**The invented-and-disclosed key** (the `evaluate_alerts` / `export_grade_artifacts`
precedent — a name no design document declares, that the test calls and #104's landing
reconciles): `aeh.grade:criterion_band_figures`. Deliberately NOT `criterion_figures` —
`M-STATS`' #118 entry already reserves that name for its analytical read (`WRITTEN_AHEAD_BLOCKERS`
"#118 criterion_figures"), and M-GRADE's producer is a different surface from M-STATS's
analytical export (`CT-GRADE-13` names the consumer obligation the other way). The name
is absent from both design documents (checked: zero occurrences). The rung-0 signature
assumed here — `criterion_band_figures(scores, band_order)` over a cohort's criterion
scores, the `apply_policy` shape — reconciles at #104's landing like every other
reserved name in this suite.

**The hand-computed reference**, pinned exactly (the §5.3 oracle row: *"A library's
answer is not a reference; two implementations agreeing on a wrong convention is the
classic failure"*):

- **Histogram** — `{"B1": 1, "B3": 2, "B5": 1}` for the judged criterion `C1` over four
  students banded `B1, B3, B3, B5`.
- **Entropy** — the natural-log convention, disclosed because the design does not pin
  the base and a base is exactly the "two implementations agreeing on a wrong
  convention" the oracle row warns about: `-(0.25·ln 0.25 + 0.5·ln 0.5 + 0.25·ln 0.25)
  = 0.75·ln 4 ≈ 1.0397` nats. A uniform three-band distribution would be base-blind
  only in its ratio; the committed constant pins the convention.
- **Interior rate** — the share of scores in the declared band order's interior (strictly
  between the first and last declared band): `B3` is interior of `(B1..B5)`, so `2/4 =
  0.5`. The band order is an input (the vocabulary's stand-in rows carry free band
  names; the rubric's declared order is the package's), so the figure cannot silently
  read a band name's digits.
- **The null contract** — the deterministic criterion `MCQ` carries a histogram (its
  `correct`/`incorrect` bands are real counts) but its entropy and interior rate are
  **`None`, not 0.0**: a zero would read as "no variation", which is a different claim
  from "the figure does not apply" (#104's own technical note; `CT-GRADE-13`'s data
  clause makes the nulls a consumer obligation — this case pins the producer's side).

**Disclosed stand-ins** (`grade_vocabulary.py`, header): the `score()` value objects —
the same duck type `apply_policy` consumes; the deterministic criterion's rows are
represented by their band names (`correct`/`incorrect`, M-DET's bands), no store, no
doubles. `GRADE_BLOCKER` is unused here — the blocker is `#104`, this file's own.

**Isolation: rung 0** — the pure seam only; no store, no model, no network.
"""

from __future__ import annotations

import math

import pytest

from tests.support.grade_vocabulary import score
from tests.support.impl import GRADE_MODULE, require

pytestmark = pytest.mark.writtenahead

ISSUE = "#104"

#: The declared band order of the fixture's rubric — the interior definition's input.
_BAND_ORDER = ("B1", "B2", "B3", "B4", "B5")

#: The judged cohort: four students on C1 — B1, B3, B3, B5.
_JUDGED_SCORES = (
    score("C1", 1.0, band="B1"),
    score("C1", 5.0, band="B3"),
    score("C1", 5.0, band="B3"),
    score("C1", 9.0, band="B5"),
)

#: The hand-computed reference, committed: the figures #104's accessor must reproduce.
_ENTROPY_C1 = 0.75 * math.log(4.0)  # 0.25/0.5/0.25 distribution, natural log — ≈ 1.0397


def test_tc_grade_14_the_band_figures_match_the_hand_computed_reference():
    """`TC-GRADE-14` — histogram exact, entropy exact under the disclosed natural-log
    convention, interior rate exact against the declared band order."""
    criterion_band_figures = require(GRADE_MODULE, "criterion_band_figures", issue=ISSUE)

    figures = criterion_band_figures(_JUDGED_SCORES, band_order=_BAND_ORDER)
    by_criterion = {figure.criterion_id: figure for figure in figures}

    c1 = by_criterion.get("C1")
    assert c1 is not None, (
        f"the accessor returned figures for {sorted(by_criterion)} — the judged "
        "criterion's own figures are the case's subject"
    )
    assert dict(c1.histogram) == {"B1": 1, "B3": 2, "B5": 1}, (
        f"the band histogram reads {dict(c1.histogram)!r}, expected the hand-computed "
        "{'B1': 1, 'B3': 2, 'B5': 1} — the histogram is the reference the teacher "
        "reads the class's spread from (FR-GRADE-14)"
    )
    assert c1.entropy == pytest.approx(_ENTROPY_C1, rel=1e-3), (
        f"band entropy reads {c1.entropy!r}, expected {_ENTROPY_C1:.4f} nats — the "
        "hand-computed reference (0.25/0.5/0.25 over natural log); a different base "
        "is a convention change and needs one, disclosed"
    )
    assert c1.interior_rate == pytest.approx(0.5), (
        f"the interior rate reads {c1.interior_rate!r}, expected 0.5 — two of four "
        "scores sit in B3, the interior of the declared (B1..B5) order"
    )


def test_tc_grade_14_deterministic_criteria_carry_nulls_not_zeros():
    """`TC-GRADE-14`'s null contract — entropy and interior rate are **null** for
    deterministic criteria, never zero: "no figure" is not "no variation" (#104's own
    technical note; `CT-GRADE-13` makes the nulls a consumer obligation, so the
    producer must emit a real null)."""
    criterion_band_figures = require(GRADE_MODULE, "criterion_band_figures", issue=ISSUE)

    deterministic_scores = (
        score("MCQ", 1.0, band="correct"),
        score("MCQ", 0.0, band="correct"),
        score("MCQ", 0.0, band="incorrect"),
    )
    figures = criterion_band_figures(deterministic_scores, band_order=("incorrect", "correct"))
    entry = {figure.criterion_id: figure for figure in figures}["MCQ"]

    assert entry.histogram == {"correct": 2, "incorrect": 1}, (
        f"the deterministic histogram reads {dict(entry.histogram)!r} — the bands are "
        "real counts and stay carried (only the two derived figures go null)"
    )
    assert entry.entropy is None, (
        f"the deterministic criterion's entropy is {entry.entropy!r} — it must be "
        "null: a zero would read as 'no variation', which is a different claim "
        "(FR-GRADE-14, CT-GRADE-13's consumer obligation)"
    )
    assert entry.interior_rate is None, (
        f"the deterministic criterion's interior rate is {entry.interior_rate!r} — it "
        "must be null, not 0.0 (FR-GRADE-14's null contract)"
    )