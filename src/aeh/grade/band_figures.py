"""Per-criterion band figures over a population of scores: the histogram and its entropy."""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

from aeh.det import BAND_CORRECT, BAND_INCORRECT, BAND_UNRESOLVED

from .stored_rows import _row_value
from .records import CriterionBandFigure


#: M-DET's result vocabulary — the deterministic-criterion marker the pure accessor
#: reads. A criterion whose every score row carries one of these band values is a
#: multiple-choice result: its histogram is a real count, but entropy and interior
#: rate do not apply to a keyed selection (`FR-GRADE-14`'s null contract). The names
#: are imported, never re-declared: a second copy of the vocabulary is exactly the
#: drift the single-source rule exists to prevent.
_DETERMINISTIC_BANDS = frozenset({BAND_CORRECT, BAND_INCORRECT, BAND_UNRESOLVED})


def _band_population_is_deterministic(bands: Sequence[str]) -> bool:
    """Whether a criterion's bands are deterministic results (M-DET's band names) rather than
    judged bands. An empty population is not deterministic."""
    return bool(bands) and all(band in _DETERMINISTIC_BANDS for band in bands)


def _shannon_entropy(counts: Sequence[int]) -> float:
    """The Shannon entropy, in nats, of the observed band histogram. Empty cells contribute
    nothing. A population in a single band really is 0.0: a judged criterion with no variation, not
    a deterministic one."""
    total = sum(counts)
    if total <= 0:
        return 0.0
    return -math.fsum(
        (count / total) * math.log(count / total)
        for count in counts
        if count > 0
    )


def criterion_band_figures(
    scores: Iterable[Any], band_order: Sequence[str] = ()
) -> tuple[CriterionBandFigure, ...]:
    """The band figures for each criterion over a population of criterion scores (FR-GRADE-14,
    TC-GRADE-14). Pure: scores in, figures out, no store and no model.

    - **Histogram** — every band the criterion's rows carry, as a count; the
      histogram is a real figure even for a deterministic criterion (its
      correct/incorrect bands are real counts).
    - **Entropy** — Shannon entropy of the band distribution in nats. `None` for a
      deterministic criterion (M-DET's result vocabulary, see
      `_DETERMINISTIC_BANDS`): a zero would read as "no variation", which is a
      different claim from "the figure does not apply".
    - **Interior rate** — the share of scores in the declared band order's interior
      (strictly between its first and last band). `None` for a deterministic
      criterion, and `None` when the declared order's interior is empty — fewer
      than two bands leaves no order to be interior of, and exactly two leaves no
      band strictly between them. The order is an input (the
      rubric's declared order is the package's), so the figure cannot silently read
      a band name's digits; a band the order does not declare is not interior, and
      still counts in the denominator — it is a real score outside the known
      interior, not a hidden one.

    Figures are returned per criterion in sorted criterion-id order; the histogram
    is a plain dict in sorted band order, so the record is deterministic end to end.
    """
    by_criterion: dict[str, list[str]] = {}
    for item in scores:
        criterion_id = str(_row_value(item, "criterion_id"))
        band = _row_value(item, "band")
        if band is None:
            # A row with no band carries no figure — the same honesty the score
            # reads apply (a quarantined extraction leaves nothing to count).
            continue
        by_criterion.setdefault(criterion_id, []).append(str(band))

    order = [str(band) for band in band_order]
    interior = set(order[1:-1]) if len(order) >= 2 else set()

    figures = []
    for criterion_id in sorted(by_criterion):
        bands = by_criterion[criterion_id]
        histogram = {band: bands.count(band) for band in sorted(set(bands))}
        if _band_population_is_deterministic(bands):
            figures.append(
                CriterionBandFigure(
                    criterion_id=criterion_id,
                    histogram=histogram,
                    entropy=None,
                    interior_rate=None,
                )
            )
            continue
        entropy = _shannon_entropy(list(histogram.values()))
        rate = (
            sum(1 for band in bands if band in interior) / len(bands)
            if interior
            else None
        )
        figures.append(
            CriterionBandFigure(
                criterion_id=criterion_id,
                histogram=histogram,
                entropy=entropy,
                interior_rate=rate,
            )
        )
    return tuple(figures)
