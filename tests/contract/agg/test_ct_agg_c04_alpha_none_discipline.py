"""`TC-AGG-C04` — the null discipline of the agreement figure (§6.11.12).

`CT-AGG-04`'s discriminating-value half — the adjacent-vs-distant pair where adjacent-
band and distant-band disagreement have the same *count* but must yield different α
(the pair a nominal-metric implementation fails), the raw-count prohibition, and the
unanimous figure — is the shipped sibling `tests/unit/agg/test_ordinal_alpha.py`
(`TC-AGG-05`/`TC-AGG-19`), and the degenerate two-band reading is TC-AGG-C17's ground.
This case carries the clause's LAST sentence, which no sibling executes: "`ordinal_alpha`
returns **`None` where it is undefined** rather than a substitute number", together with
the consumer limb the clause names: **no consumer coerces it to 0.** A `None` quietly
becoming `0.00` is not a smaller figure — it is a lie with a decimal point in it: the
panel's agreement is *unknown*, and zero reads as *total disagreement*. The module's own
description surface (`describe_agreement`, landed at #91) is the executable consumer
side: over an undefined figure it renders the word *undefined* and never a rendered
number.

Isolation: rung 0 — pure functions; the socket guard is autouse.
"""

from __future__ import annotations

import pytest

from tests.support.agg_vocabulary import verdict
from tests.support.impl import AGG_MODULE, require

pytestmark = [pytest.mark.contract]


def test_tc_agg_c04_alpha_is_none_where_it_is_undefined_never_a_substitute():
    """`TC-AGG-C04` (`CT-AGG-04`, `FR-AGG-04`, unit / rung 0, exact None, P0) —
    every undefined input returns `None`, never a substitute number: no verdicts
    and a single verdict (the degenerate band-shape reading is TC-AGG-C17's
    ground, not this case's)."""
    ordinal_alpha = require(AGG_MODULE, "ordinal_alpha", issue="#91")

    for name, verdicts in (
        ("no verdicts", []),
        ("a single verdict", [verdict("B2", 2)]),
    ):
        figure = ordinal_alpha(verdicts)
        assert figure is None, (
            f"ordinal_alpha over {name} returned {figure!r} — agreement is "
            "**undefined** there, and the clause demands None rather than a "
            "substitute number (CT-AGG-04's null discipline; a 0.0 here reads as "
            "'total disagreement', which is a different claim than none at all)"
        )


def test_tc_agg_c04_the_undefined_figure_is_described_as_undefined_never_zero():
    """`TC-AGG-C04` (`CT-AGG-04`, consumer limb, unit / rung 0, P0) — the module's
    own description of an undefined figure says *undefined* and renders no coerced
    number: the no-consumer-coerces half of the clause, executable on the landed
    description surface (`describe_agreement`, #91). A `0.00` in the rendered text
    is exactly the substitution the clause forbids."""
    ordinal_alpha, describe_agreement = require(
        AGG_MODULE, "ordinal_alpha", "describe_agreement", issue="#91"
    )

    figure = ordinal_alpha([])
    assert figure is None, "precondition: the undefined figure came back a number"

    text = describe_agreement(
        figure={"ordinal_alpha": figure, "band_count": 4,
                "degenerate_band_shape": False},
        population="y9-2026-spring",
    )
    lowered = text.lower()
    assert "undefined" in lowered, (
        f"the description renders {text!r} — an undefined agreement figure must be "
        "described as undefined, not silently re-read (CT-AGG-04's None discipline)"
    )
    assert "0.00" not in text, (
        f"the description renders {text!r} — a None figure coerced to a rendered "
        "0.00 is the substitute number the clause forbids, wearing two decimal "
        "places"
    )
