"""`TS-90` (issue #384) — `TC-CONSOLE-48`: a figure below the headline threshold renders with
its qualifier, and the threshold is read at call time (`FR-CONSOLE-38`, GAP-17).

| Input | Expected |
|---|---|
| n = 29 | the text contains `too few to draw conclusions from` |
| n = 30, n = 31 | absent |
| `aeh.stats.STATS_MIN_N_FOR_HEADLINE` patched to 10, n = 12 | absent — the threshold is read at call time |

**What the requirement protects.** The figure is still shown below the threshold — it is what the
labels support — but a reader who takes `kappa 0.41` over eleven papers as *the system's
agreement* has drawn a conclusion the sample cannot carry. `FR-CONSOLE-38` makes the console say
so in the same breath as the number, rather than leaving the caveat to a footnote nobody reads.

**Rung 1, because that is the level the requirement lives at.** `render_agreement_block` is a
pure renderer over a figure object; the threshold rule needs no store, no server and no run. The
goal's steer — run only the level relevant to the issue — points straight here: the three other
cases in `TS-90` need a real socket, and this one would learn nothing from having one.

**The boundary is asserted as a boundary.** 29 / 30 / 31 around a threshold of 30, so the case
separates `<` from `<=`. An implementation using the wrong comparison passes n = 29 and n = 31
and fails only at exactly 30 — which is the value a single-point test is least likely to pick.

**Call time is the half that rots silently.** `console.py` imports `STATS_MIN_N_FOR_HEADLINE`
*inside* the function (`console.py:3467`) precisely so a deployment that lowers the threshold
changes the rendering without a code change, and so this module never keeps a second copy of the
number. A module-scope import would pass every other assertion here and freeze the threshold at
whatever it was when the process started; the patched-threshold case is what catches that.

**`aeh.stats` is patched, not `aeh.console`.** The point is that the console reads *the other
module's* declared constant. Patching a name in `console` would prove only that the renderer
reads something called `STATS_MIN_N_FOR_HEADLINE`, not that it defers to `M-STATS`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import aeh.stats
from aeh.console import TOO_FEW_QUALIFIER, render_agreement_block
from aeh.stats import STATS_MIN_N_FOR_HEADLINE

#: The declared threshold, read once here so the boundary cases stay boundaries if it moves.
THRESHOLD = int(STATS_MIN_N_FOR_HEADLINE)


def _figure(n: int) -> SimpleNamespace:
    """An agreement figure the renderer accepts: a kappa, a sample size, a non-degenerate scale.

    `degenerate=False` and `band_count=4` deliberately — a two-band scale adds its own
    degeneracy sentence, and this case is about the sample-size qualifier alone.
    """
    return SimpleNamespace(kappa=0.41, alpha=None, n=n, degenerate=False, band_count=4)


def _rendered(n: int) -> str:
    return render_agreement_block(figure=_figure(n))


# --- TC-CONSOLE-48 -------------------------------------------------------------------------


def test_tc_console_48_a_sample_below_the_threshold_carries_the_qualifier() -> None:
    """n = 29 against a threshold of 30."""
    rendered = _rendered(THRESHOLD - 1)
    assert TOO_FEW_QUALIFIER in rendered, (
        f"a sample of {THRESHOLD - 1} renders without the qualifier, so a reader takes the "
        f"figure as the system's agreement: {rendered!r}"
    )
    assert f"n = {THRESHOLD - 1}" in rendered, (
        "the qualifier appeared but the sample size did not — the caveat is only actionable "
        f"next to the number it is about: {rendered!r}"
    )


@pytest.mark.parametrize("n", [0, 1], ids=["at-the-threshold", "above-the-threshold"])
def test_tc_console_48_a_sample_at_or_above_the_threshold_does_not(n: int) -> None:
    """n = 30 and n = 31.

    The at-the-threshold row is the one that matters: `<` and `<=` differ only there, and an
    implementation with the wrong operator passes both of its neighbours.
    """
    size = THRESHOLD + n
    rendered = _rendered(size)
    assert TOO_FEW_QUALIFIER not in rendered, (
        f"a sample of {size} is at or above the declared threshold of {THRESHOLD} but still "
        f"renders the too-few qualifier: {rendered!r}"
    )


def test_tc_console_48_the_threshold_is_read_at_call_time(monkeypatch) -> None:
    """The deployment lowers `aeh.stats.STATS_MIN_N_FOR_HEADLINE` to 10; n = 12 loses its
    qualifier without a code change.

    Patched on `aeh.stats`, not on `aeh.console`: the claim is that the console defers to
    `M-STATS`' declared constant rather than keeping its own copy. A renderer that imported the
    name at module scope passes every case above and fails this one — which is the whole reason
    the import sits inside the function (`console.py:3467`).
    """
    assert TOO_FEW_QUALIFIER in _rendered(12), (
        f"precondition: n = 12 is below the declared threshold of {THRESHOLD} and should carry "
        "the qualifier before it is lowered"
    )

    monkeypatch.setattr(aeh.stats, "STATS_MIN_N_FOR_HEADLINE", 10)

    assert TOO_FEW_QUALIFIER not in _rendered(12), (
        "n = 12 still renders the too-few qualifier after the deployment lowered "
        "aeh.stats.STATS_MIN_N_FOR_HEADLINE to 10. The threshold was captured at import time, "
        "so a deployment cannot change the rendering without a code change (seam 3)"
    )
    assert TOO_FEW_QUALIFIER in _rendered(9), (
        "with the threshold at 10, a sample of 9 must still be qualified — the lowered value "
        "is being ignored in both directions rather than read"
    )
