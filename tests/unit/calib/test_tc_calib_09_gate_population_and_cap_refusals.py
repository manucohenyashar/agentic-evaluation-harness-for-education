"""`TC-CALIB-09` — the gate operates on the full class, or refuses: the population refusals.

Test plan §5.17, `TC-CALIB-09` (NFR-CALIB-02, Integration / rung 2, negative), plus the
class-size cap trio #139's PR carried forward onto this issue.

The contract suite carries the *name* refusal (`TC-CALIB-C07`: `cohort_id == "calibration-set"`
raises `InsufficientPopulation`). What no green test carried before this file is the rest of the
refusal family the precondition "a gate run over the calibration set rather than the full class"
actually describes:

* a roster **flagged** as the calibration set is refused by its flag, not by its name — a cohort
  that arrives under any id at all must refuse the same way, or renaming the calibration set
  would rename the gate's blind spot;
* the gate scores the **full class or refuses**: a deployment's class-size cap
  (`HARNESS_CALIB_CLASS_SIZE_CAP`) refused an oversized class instead of silently scoring a
  subset — a gate over a subset is not the gate the requirement describes, and the refusal
  names the knob that set it;
* at the cap it still runs (the cap is a ceiling, not an off-by-one), a **mis-set** cap value
  falls back to the production default (no cap) rather than stopping the gate, and the same
  refusal guards `run_dual_scoring` — which reads the knob from the process environment, the
  way a real deployment sets it.

The rosters arrive through the module's registration seam (`cohort_with_band_shift`; the flagged
one built directly on `_ClassRoster` — in this build the registration route *is* the test seam,
per the module docstring).
"""

from __future__ import annotations

import pytest

from tests.support.impl import CALIB_MODULE, require

CAP_ENV = "HARNESS_CALIB_CLASS_SIZE_CAP"


def _flagged_cohort(calib):
    """Register a roster flagged as the calibration set, under an ordinary-sounding id.

    The point of the flag: `TC-CALIB-C07` asserts the refusal when the id *is* the name — this
    row gives the same roster a perfectly ordinary id and lets the flag carry the refusal, which
    is the shape a real store export would arrive in."""
    roster = calib._ClassRoster(
        cohort_id="cohort-flagged-as-calibration-set",
        class_size=40,
        criteria=("CRIT-1",),
        scores=(((1, 1),),) * 40,
        is_calibration_set=True,
    )
    calib._CLASS_ROSTERS[roster.cohort_id] = roster
    return roster.cohort_id


# --- the population refusals ---------------------------------------------------------------------


def test_tc_calib_09_a_roster_flagged_as_the_calibration_set_is_refused():
    """The flag refuses the cohort, not its name (`NFR-CALIB-02`, `CT-CALIB-07`).

    The precondition is "over the calibration set rather than the full class" — and a calibration
    set that reaches the gate under a different id is still twenty papers that mean nothing. The
    refusal must be typed (`InsufficientPopulation`) and name the flag, so the caller learns the
    cohort is the wrong *population*, not merely the wrong string.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "non_inferiority", issue="#140")
    cohort = _flagged_cohort(calib)

    with pytest.raises(calib.InsufficientPopulation) as exc:
        calib.non_inferiority(r0="pkg-v1", r1="pkg-v2", cohort_id=cohort, threshold=0.10)

    assert "calibration set" in str(exc.value), (
        f"the refusal does not name the cohort as a calibration set ({exc.value!s}); the "
        "refusal is about what the population *is*, not about a reserved id"
    )
    assert cohort in str(exc.value), (
        "the refusal does not name the cohort that was refused; a caller holding several "
        "cohorts cannot tell which one the gate refused"
    )


def test_tc_calib_09_an_over_cap_class_is_refused_not_scored_as_a_subset():
    """The cap refuses an oversized class — the gate never scores a subset (`NFR-CALIB-02`).

    A gate over a subset returns a number, and the number would look exactly like the gate's
    verdict while covering a class the deployment said must not be scored silently. The refusal
    is `CalibrationError`, names the knob (`HARNESS_CALIB_CLASS_SIZE_CAP`), names the class size
    and the cap, and says the gate scores the FULL class or refuses.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "non_inferiority", issue="#140")

    cohort = calib.cohort_with_band_shift(fraction=0.05, class_size=10)
    with pytest.raises(calib.CalibrationError) as exc:
        calib.non_inferiority(
            r0="pkg-v1", r1="pkg-v2", cohort_id=cohort, threshold=0.10,
            environ={CAP_ENV: "5"},
        )
    message = str(exc.value)
    assert CAP_ENV in message, (
        f"the over-cap refusal does not name {CAP_ENV}; the operator who set the cap must find "
        "it from the message, not from the source"
    )
    assert "10" in message and "5" in message, (
        f"the refusal does not name the class size and the cap ({message!r}); 'too big' alone "
        "does not say what the deployment set"
    )
    assert "FULL" in message, (
        "the refusal does not state the gate scores the full class or refuses — without it, a "
        "reader concludes the gate scored what it could (NFR-CALIB-02)"
    )


@pytest.mark.parametrize(
    "cap_setting, expect_run",
    [
        ({"CAP_ENV": "10"}, True),   # exactly at the cap: a ceiling, not off-by-one
        ({"CAP_ENV": "50"}, True),   # above the class: no constraint binds
        ({"CAP_ENV": None}, True),   # unset: the production default is no cap (NFR-CALIB-02)
        ({"CAP_ENV": "0"}, True),    # mis-set: falls back to the default rather than refusing
        ({"CAP_ENV": "abc"}, True),  # mis-set: same fallback, the gate never stops on a typo
    ],
    ids=["at-cap", "above-cap", "unset", "mis-set-zero", "mis-set-text"],
)
def test_tc_calib_09_the_cap_is_a_ceiling_and_a_mis_set_one_falls_back(
    cap_setting, expect_run,
):
    """At, above, unset and mis-set — the gate runs, and the full class is scored.

    The mis-set rows are the seam-3 half: `0` would refuse every class and `"abc"` would refuse
    parsing, and a mis-set knob must not stop a calibration — both fall back to the production
    default (no cap), and the run proceeds over the full class. The zero row is the one a
    falsy-value implementation gets wrong: `0` read as *no cap* would silently uncap every
    class, the exact inversion of the knob's meaning.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "non_inferiority", issue="#140")

    raw = cap_setting["CAP_ENV"]
    environ = {} if raw is None else {CAP_ENV: raw}
    cohort = calib.cohort_with_band_shift(fraction=0.05, class_size=10)
    result = calib.non_inferiority(
        r0="pkg-v1", r1="pkg-v2", cohort_id=cohort, threshold=0.10, environ=environ,
    )

    assert expect_run is True and result.outcome in ("pass", "reject"), (
        f"the gate refused a class of 10 under cap {raw!r}; the cap is a ceiling on scoring a "
        "SUBSET, not a veto on the full class, and a mis-set value falls back rather than "
        "raising (NFR-CALIB-02, seam 3)"
    )
    assert result.class_size == 10, (
        f"the gate ran over {result.class_size} submissions, not the full class of 10 — the "
        "cap's whole point is that no subset is ever what runs"
    )


# --- the same refusal at the dual-scoring pass ---------------------------------------------------


def test_tc_calib_09_the_dual_scoring_pass_refuses_an_over_cap_class_too(monkeypatch):
    """`run_dual_scoring` refuses an over-cap class — and the refusal leaves nothing spent.

    The pass reads the knob from the process environment (the way a real deployment sets it),
    and the refusal must name the same knob the gate's refusal names. Seam 4 on the refusal: the
    plan's `executed_at` stays None and the provider shows zero calls — a refusal that spent the
    invoice it refused would be the budget NFR-CALIB-03 protects, incurred.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(
        CALIB_MODULE, "plan_dual_scoring", "authorize", issue="#140"
    )
    provider = calib.counting_provider_for_test()

    cohort = calib.cohort_with_band_shift(fraction=0.05, class_size=10)
    plan = calib.plan_dual_scoring(
        cohort_id=cohort, r0="pkg-v1", r1="pkg-v2", provider=provider
    )
    calib.authorize(plan)

    monkeypatch.setenv(CAP_ENV, "5")
    with pytest.raises(calib.CalibrationError) as exc:
        calib.run_dual_scoring(plan)
    assert CAP_ENV in str(exc.value), (
        f"the over-cap refusal does not name {CAP_ENV}; the operator must be able to find the "
        "knob from the refusal alone"
    )
    assert plan.executed_at is None, (
        "the refused pass recorded an execution timestamp — the refusal executed nothing, and "
        "the record must say so"
    )
    assert provider.calls == 0, (
        f"{provider.calls} provider calls were made by a pass the cap refused; a refused "
        "budget is not a spent one (NFR-CALIB-03)"
    )


def test_tc_calib_09_under_the_cap_the_pass_covers_the_full_class(monkeypatch):
    """Below the cap, the run proceeds — over the full class, exactly as disclosed.

    Paired with the refusal row: the cap constrains nothing it does not have to, and the run it
    permits is still the full class (`NFR-CALIB-02`) — the scores land one row per submission,
    and the executed timestamp is recorded only on the run that happened.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(
        CALIB_MODULE, "plan_dual_scoring", "authorize", issue="#140"
    )
    provider = calib.counting_provider_for_test()

    cohort = calib.cohort_with_band_shift(fraction=0.05, class_size=10)
    plan = calib.plan_dual_scoring(
        cohort_id=cohort, r0="pkg-v1", r1="pkg-v2", provider=provider
    )
    calib.authorize(plan)

    monkeypatch.setenv(CAP_ENV, "50")
    calib.run_dual_scoring(plan)

    assert plan.executed_at is not None
    assert len(plan.scores) == 10, (
        f"the pass returned {len(plan.scores)} score rows for a class of 10; the pass covers "
        "the full class or refuses, never a subset (NFR-CALIB-02)"
    )