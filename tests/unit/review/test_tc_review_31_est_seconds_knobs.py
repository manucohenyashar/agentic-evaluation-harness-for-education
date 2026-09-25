"""`TS-89` (issue #383) — `TC-REVIEW-31`: the knob rename keeps a deployment working
(`FR-REVIEW-18`, seam 3).

| Environment | Expected |
|---|---|
| `HARNESS_REVIEW_EST_SECONDS_ATOMIC=30` | 30 |
| only legacy `AEH_REVIEW_EST_SECONDS_ATOMIC=20` | 20 (fallback) |
| both set | 30 (the new name wins) |
| `"x"` | `ReviewError` at call time |

**Why the fallback exists, and why it is temporary.** The project's knobs are being renamed
`AEH_*` → `HARNESS_*`. A deployment that already exports the old name must keep working for
one release rather than silently reverting to the production default — a knob that stops being
read is not an error anyone sees, it is a box that quietly behaves differently from the one
next to it. That is the phantom-bug shape seam 3 exists to prevent, and it is why the fallback
is asserted rather than assumed.

**"The new name wins" is the half that is easy to get backwards.** Both-set is the state a
deployment passes *through* during a rename, and the resolution has to be the new name — the
operator who added it is the one making the change. A `_knob_name` that checked the legacy
prefix first would pass the fallback case and quietly ignore every new-name override.

**The refusal is at call time, and it refuses rather than clamping.** `_env_float` raises on
an unparseable value or one outside its range instead of falling back, because a typo'd
override silently taking the production value is the same phantom bug from the other
direction, and a clamped misconfiguration would *be* the bug.

**Isolation: rung 1** — the knob reader over a patched environment; no store is involved.
"""

from __future__ import annotations

import pytest

from aeh.review import (
    REVIEW_EST_SECONDS_ATOMIC,
    REVIEW_EST_SECONDS_HOLISTIC,
    ReviewError,
    _calibration_knobs as _knobs,
)

NEW = "HARNESS_REVIEW_EST_SECONDS_ATOMIC"
LEGACY = "AEH_REVIEW_EST_SECONDS_ATOMIC"
KNOB = "est_seconds_atomic"


@pytest.fixture(autouse=True)
def _clear_knobs(monkeypatch):
    """Neither spelling set, whatever the developer's shell holds — the default arm and every
    other arm start from the same place."""
    monkeypatch.delenv(NEW, raising=False)
    monkeypatch.delenv(LEGACY, raising=False)


# --- TC-REVIEW-31 ---------------------------------------------------------------------------


def test_tc_review_31_the_new_knob_name_is_read(monkeypatch):
    """`HARNESS_REVIEW_EST_SECONDS_ATOMIC=30` → 30."""
    monkeypatch.setenv(NEW, "30")

    assert _knobs()[KNOB] == 30.0, (
        f"the new knob name was not read: {_knobs()[KNOB]}"
    )


def test_tc_review_31_the_legacy_knob_name_is_honoured_when_it_is_the_only_one_set(
    monkeypatch,
):
    """Only `AEH_REVIEW_EST_SECONDS_ATOMIC=20` → 20.

    The compatibility arm. A deployment that set the old name before the rename keeps its
    configuration; falling back to the production default here would change a box's behaviour
    on upgrade with nothing in any log to say so.
    """
    monkeypatch.setenv(LEGACY, "20")

    assert _knobs()[KNOB] == 20.0, (
        f"the legacy knob name was ignored and the value resolved to {_knobs()[KNOB]} "
        f"(the production default is {REVIEW_EST_SECONDS_ATOMIC}); a deployment mid-rename "
        "would silently revert"
    )


def test_tc_review_31_the_new_name_wins_when_both_are_set(monkeypatch):
    """Both set → 30, the new name.

    The discriminating arm. A resolver that checked the legacy prefix first passes the
    fallback case above and then ignores every new-name override an operator adds — the
    rename would appear to do nothing.
    """
    monkeypatch.setenv(NEW, "30")
    monkeypatch.setenv(LEGACY, "20")

    assert _knobs()[KNOB] == 30.0, (
        f"with both spellings set the knob resolved to {_knobs()[KNOB]}; the new name is the "
        "one the operator is moving to and it must win"
    )


@pytest.mark.parametrize("spelling", (NEW, LEGACY))
def test_tc_review_31_an_unparseable_value_is_refused_at_call_time(monkeypatch, spelling):
    """`"x"` → `ReviewError`, under either spelling.

    Refused rather than defaulted: a typo'd override that silently took the production value
    is a box behaving differently from its neighbour with nothing to show for it. Both
    spellings, because the legacy path must not be the lenient one — a deployment mid-rename
    is exactly where a typo is most likely.
    """
    monkeypatch.setenv(spelling, "x")

    with pytest.raises(ReviewError) as caught:
        _knobs()

    assert spelling in str(caught.value), (
        f"the refusal does not name the knob that was wrong: {caught.value!r}"
    )


@pytest.mark.parametrize("value", ("0", "-5", "100000"))
def test_tc_review_31_a_value_outside_the_declared_range_is_refused_not_clamped(
    monkeypatch, value
):
    """Out of range refuses too — clamping would *be* the bug.

    `est_seconds_atomic` is declared over `[1.0, 3600.0]`. A zero would let the budget fit
    infinitely many items and a clamp would silently substitute a figure the operator never
    chose, which is the same silent-substitution failure the refusal above prevents.
    """
    monkeypatch.setenv(NEW, value)

    with pytest.raises(ReviewError):
        _knobs()


def test_tc_review_31_the_defaults_stand_when_neither_spelling_is_set():
    """The positive control: unset resolves to the declared production values.

    Without it every arm above would also pass against a reader that raised on everything, and
    the module could not be used at all in its default configuration.
    """
    knobs = _knobs()

    assert knobs[KNOB] == REVIEW_EST_SECONDS_ATOMIC == 45.0
    assert knobs["est_seconds_holistic"] == REVIEW_EST_SECONDS_HOLISTIC == 90.0, (
        "the holistic default is the figure TC-REVIEW-25's sweep reads; a holistic criterion "
        "budgeted at an atomic one's minutes is the defect FR-REVIEW-19 exists to fix"
    )


def test_tc_review_31_a_blank_knob_falls_back_rather_than_refusing(monkeypatch):
    """An exported-but-empty variable takes the default.

    `_knob_name` tests `.strip()`, so a blank new-name export must not shadow a set legacy one
    either. This is the shape an operator produces with `export HARNESS_REVIEW_...=` in a
    script, and refusing it would stop a run over a variable nobody meant to set.
    """
    monkeypatch.setenv(NEW, "   ")
    assert _knobs()[KNOB] == REVIEW_EST_SECONDS_ATOMIC

    monkeypatch.setenv(LEGACY, "20")
    assert _knobs()[KNOB] == 20.0, (
        "a blank new-name export shadowed a legitimately set legacy knob; the deployment's "
        "configuration disappears for a variable nobody meant to set"
    )
