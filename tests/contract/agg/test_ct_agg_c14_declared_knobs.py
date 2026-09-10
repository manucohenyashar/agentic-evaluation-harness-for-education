"""`TC-AGG-C14` — declared constants, moved knobs move volume, no empirical costume (§6.11.12).

`CT-AGG-14`: "`AGG_AUTO_THRESHOLD_ATOMIC` (0.80), `AGG_AUTO_THRESHOLD_HOLISTIC`
(0.90), `AGG_UNCITED_MULTIPLIER` (0.80) and the cap table are **declared constants,
not tuned ones**, at Phase 1. They change routing volume, and therefore how much
teacher time is spent and on what; a consumer must not present them as empirically
justified until `FR-STATS-08`'s routing-policy validation says so."

Three limbs:

- **the exact defaults** (rung 0): the four knobs read off the module — the three
  constants and the six-entry cap table — equal §3.12's declared numbers. A drifted
  default IS a routing change nobody agreed to;
- **the routing-volume differential** (rung 0): each knob, moved, flips its
  boundary cell's routing — the discriminating cell for each is built to sit
  exactly on the knob's boundary, so a knob that stopped feeding the routing
  decision (dead or mis-wired) fails. "Moving each changes routing volume" — the
  differential is the case's oracle, not the constants' existence;
- **the honesty text** (rung 3, writtenahead on `aeh.console:render_setup_step`,
  #123): the consumer's rendered text for these knobs must not dress them in
  empirical justification — no "calibrated", no "validated", no "tuned" — because
  nothing has calibrated them at Phase 1 (`FR-STATS-08`'s validation has not run).
  The declared-assumption shape (the `test_random_arm.py` precedent) is reconciled
  at #123's landing.

Isolation: rung 0 for the defaults and the differential; rung 3 for the rendered
text; the socket guard is autouse.
"""

from __future__ import annotations

import pytest

import aeh.agg as agg_module
from tests.support.agg_vocabulary import (
    DESIGN_CAPS,
    band,
    criterion,
    panel,
    signals,
    verdict,
    agg_config,
)
from tests.support.impl import AGG_MODULE, CONSOLE_MODULE, require

pytestmark = [pytest.mark.contract]

_FOUR_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                        band("B3", 3, 6.0)])
_UNANIMOUS_TOP = panel(("B3", 3), ("B3", 3), ("B3", 3))
_ATOMIC = criterion(_FOUR_BAND.bands)
_HOLISTIC = criterion(_FOUR_BAND.bands, scoring_model="holistic")

#: The exact numbers the clause declares — the oracle for the defaults limb.
DECLARED = {
    "AGG_AUTO_THRESHOLD_ATOMIC": 0.80,
    "AGG_AUTO_THRESHOLD_HOLISTIC": 0.90,
    "AGG_UNCITED_MULTIPLIER": 0.80,
}

#: §3.12's cap table, as the clause declares it — the oracle for the fourth knob.
DECLARED_CAPS = dict(DESIGN_CAPS)


def caps_with_entry(name, value):
    """The declared cap table with one entry replaced — fixture data (Q-04: the
    tests inject the table; the assertions are stated against the injection)."""
    caps = dict(DESIGN_CAPS)
    caps[name] = value
    return caps


def test_tc_agg_c14_the_four_knobs_carry_their_declared_defaults():
    """`TC-AGG-C14` (`CT-AGG-14`, config / rung 0, exact defaults, P1) — the three
    constants and the six-entry cap table, read off the module, equal the declared
    numbers. These are §3.12's Assumption-class values: a silent re-tune is a
    routing-policy change that never went through the package, and the honesty
    obligation below presumes the numbers are the declared ones."""
    for name, expected in DECLARED.items():
        actual = getattr(agg_module, name)
        assert actual == expected, (
            f"{name} is {actual!r}, the clause declares {expected!r} — the "
            "auto-accept thresholds and the uncited multiplier are DECLARED "
            "constants (CT-AGG-14); a drifted default is a routing change nobody "
            "agreed to"
        )
    assert dict(agg_module.AGG_CAP_TABLE) == DECLARED_CAPS, (
        f"the cap table is {dict(agg_module.AGG_CAP_TABLE)!r}, the clause declares "
        f"{DECLARED_CAPS!r} — six adverse integrity signals, six hard caps, each "
        "an Assumption number (§3.12); the caps are what keep ADR-10's min a "
        "declared instrument rather than a tunable dial (CT-AGG-14)"
    )


def test_tc_agg_c14_moving_each_knob_changes_the_routing_volume():
    """`TC-AGG-C14` (`CT-AGG-14`, config / rung 0, routing-volume differential,
    P1) — each knob, moved, flips its boundary cell: a knob whose movement leaves
    the routing decision untouched is dead or mis-wired, and the teacher time the
    thresholds budget would be spent by a number that does nothing. Every cell is
    a unanimous top-band panel, so its base α is 1.0 and each boundary figure is
    one declared constant read at the shipped `>=`."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")

    # 1. atomic threshold 0.80 → 0.99: a cell ADVERSE on spans_verified with the
    #    injected cap at 0.85 reads min(1.0, 0.85) = 0.85 — auto at 0.80, queued
    #    at 0.99. (A cap binds only on an adverse signal, so the signal is set.)
    cell_default = aggregate(
        _UNANIMOUS_TOP, _ATOMIC, signals(spans_verified=False),
        config=agg_config(caps=caps_with_entry("spans_verified", 0.85)),
    )
    cell_moved = aggregate(
        _UNANIMOUS_TOP, _ATOMIC, signals(spans_verified=False),
        config=agg_config(auto_threshold_atomic=0.99,
                          caps=caps_with_entry("spans_verified", 0.85)),
    )
    assert cell_default.confidence == pytest.approx(0.85), (
        "fixture bug: the threshold cell's confidence left the knob's window"
    )
    assert cell_default.routing == "auto" and cell_moved.routing == "queued", (
        f"moving auto_threshold_atomic 0.80 → 0.99 left the routing at "
        f"{cell_default.routing!r}/{cell_moved.routing!r} — the threshold knob "
        "has stopped feeding the routing decision (CT-AGG-14: a knob with no "
        "externally-visible effect is dead or mis-wired)"
    )

    # 2. holistic threshold 0.90 → 0.80: the holistic cell reads 1.0 × the
    #    holistic multiplier 0.85 = 0.85 — queued at 0.90, auto at 0.80.
    hol_default = aggregate(_UNANIMOUS_TOP, _HOLISTIC, signals(),
                            config=agg_config())
    hol_moved = aggregate(_UNANIMOUS_TOP, _HOLISTIC, signals(),
                          config=agg_config(auto_threshold_holistic=0.80))
    assert hol_default.routing == "queued" and hol_moved.routing == "auto", (
        f"moving auto_threshold_holistic 0.90 → 0.80 left the routing at "
        f"{hol_default.routing!r}/{hol_moved.routing!r} — the holistic ceiling "
        "knob has stopped feeding the routing decision (CT-AGG-14)"
    )

    # 3. uncited multiplier 0.80 → 0.50: the uncited unanimous cell reads
    #    1.0 × 0.80 = 0.80 — auto at the shipped `>=` boundary — then 0.50, queued.
    uncited_verdicts = [verdict("B3", 3, cited=False) for _ in range(3)]
    uncited_default = aggregate(uncited_verdicts, _ATOMIC, signals(),
                                config=agg_config())
    uncited_moved = aggregate(uncited_verdicts, _ATOMIC, signals(),
                              config=agg_config(uncited_multiplier=0.50))
    assert uncited_default.confidence == pytest.approx(0.80), (
        "fixture bug: the uncited cell's confidence moved off the boundary"
    )
    assert uncited_default.routing == "auto" and uncited_moved.routing == "queued", (
        f"moving uncited_multiplier 0.80 → 0.50 left the routing at "
        f"{uncited_default.routing!r}/{uncited_moved.routing!r} — the uncited "
        "multiplier has stopped feeding the routing decision (CT-AGG-14)"
    )

    # 4. the cap table — the fourth knob: spans_verified's cap 0.25 lifted to 1.0
    #    releases the capped cell 0.25 → 1.0, queued → auto.
    capped = aggregate(_UNANIMOUS_TOP, _ATOMIC, signals(spans_verified=False),
                       config=agg_config())
    lifted = aggregate(
        _UNANIMOUS_TOP, _ATOMIC, signals(spans_verified=False),
        config=agg_config(caps=caps_with_entry("spans_verified", 1.0)),
    )
    assert capped.confidence == pytest.approx(0.25), (
        "fixture bug: the capped cell's confidence left the cap's floor"
    )
    assert lifted.confidence == pytest.approx(1.0), (
        "fixture bug: lifting the cap did not release the cell to its base"
    )
    assert capped.routing == "queued" and lifted.routing == "auto", (
        f"lifting the spans_verified cap 0.25 → 1.0 left the routing at "
        f"{capped.routing!r}/{lifted.routing!r} — the cap table has stopped "
        "feeding the routing decision (CT-AGG-14's fourth knob)"
    )


@pytest.mark.writtenahead
def test_tc_agg_c14_no_consumer_presents_the_knobs_as_empirically_justified():
    """`TC-AGG-C14` (`CT-AGG-14` × `FR-STATS-08`, contract / rung 3, consumer text
    assertion, P1, writtenahead on `aeh.console:render_setup_step`, #123) — the
    rendered text presenting these knobs carries no empirical justification: no
    "calibrated", no "validated", no "tuned", no measured-accuracy claim. Until
    FR-STATS-08's routing-policy validation exists, the numbers are declared
    assumptions; a consumer that presents them as measured borrows authority the
    label store has not granted."""
    render = require(CONSOLE_MODULE, "render_setup_step", issue="#123")

    # Declared assumption (the `test_random_arm.py` precedent): the setup
    # renderer takes the step's name and returns its rendered text — reconciled
    # at #123's landing.
    rendered = render("aggregation")
    text = rendered if isinstance(rendered, str) else str(
        getattr(rendered, "text", rendered)
    )

    empirical = ("calibrat", "empirically", "empirical", "tuned", "validated",
                 "measured accuracy", "proven", "evidence-based")
    present = [word for word in empirical if word in text.lower()]
    assert present == [], (
        f"the rendered setup text claims {present} — the aggregation knobs are "
        "DECLARED constants, not tuned ones, at Phase 1 (CT-AGG-14); no consumer "
        "presents them as empirically justified until FR-STATS-08's "
        "routing-policy validation says so"
    )
