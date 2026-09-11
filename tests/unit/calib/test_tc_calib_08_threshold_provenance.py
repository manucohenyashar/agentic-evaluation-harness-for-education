"""`TC-CALIB-08` — the non-inferiority gate resolves its threshold, never defaults it.

Test plan §5.17, `TC-CALIB-08` (FR-CALIB-08 / CT-CALIB-13, Integration / rung 2).

The contract suite carries the boundary (`TC-CALIB-C07`: the strict "more than" sweep,
including exactly-at-threshold), the calibration-set refusal, the event-order oracle over a
**standing declaration** (source `"configuration"`), and the no-channel refusal
(`TC-CALIB-C13`). What no green test carried before this file is the **provenance chain**
itself — which channel wins when several are set, and what each arrival reports:

* **argument > declaration > environment**, asserted with all three channels set, then two,
  then one — a resolution order that silently inverted would run a comparison against a value
  nobody chose, and the result would carry the wrong provenance label while still passing;
* **`threshold_source == "environment"`** — the fallback channel, asserted through `GateResult`
  (the #139 carry-forward gap: only `"configuration"` was green, and the env path could return
  anything at all without a red test);
* a **mis-set** env value (`"1.5"`, `"abc"`, blank) is *unset*, not a parse error — it falls
  through to `ThresholdNotDeclared`, the refusal that names the real problem;
* the standing declaration is **one-shot**: consumed by the run that used it, so the next run
  refuses rather than inheriting it — and a run that passed an explicit **argument** did not
  consume it, because it never used it;
* an out-of-range argument is refused at the gate, naming `[0, 1]`.

Hygiene: the standing declaration is module state, so every case clears it first and injects
its own channels — an observation must read the value it set, not a leftover declaration that
outranks the env (`_clear_institutional_threshold` is the module's own hygiene seam for exactly
this, and the registries are the module's declared test seam).
"""

from __future__ import annotations

import pytest

from tests.support.impl import CALIB_MODULE, require

ENV_THRESHOLD = "HARNESS_CALIB_NONINFERIORITY_THRESHOLD"


def _clean(calib):
    """Clear the standing declaration so an observation reads only injected channels."""
    calib._clear_institutional_threshold()


# --- the resolution order ------------------------------------------------------------------------


def test_tc_calib_08_an_explicit_argument_beats_every_declared_channel():
    """All three channels set → the argument wins, and the standing declaration survives it.

    The argument is the caller's owned decision for *this* comparison; a standing declaration is
    the institution's; the env is the machine's. If the precedence inverted, an env value a
    deployer set for one deployment would silently outrank the number the caller passed — and
    the result would say "argument" while running on something else.
    """
    calib = require(CALIB_MODULE, issue="#140")
    non_inferiority = require(CALIB_MODULE, "non_inferiority", issue="#140")
    calib._clear_institutional_threshold()
    calib.declare_institutional_threshold(0.10)

    cohort = calib.cohort_with_band_shift(fraction=0.05, class_size=100)
    result = non_inferiority(
        r0="pkg-v1", r1="pkg-v2", cohort_id=cohort, threshold=0.25,
        environ={ENV_THRESHOLD: "0.40"},
    )

    assert result.threshold_used == 0.25, (
        f"the gate compared against {result.threshold_used!r} with an explicit argument of "
        "0.25 also present — the caller's number decides, not the declaration or the env"
    )
    assert result.threshold_source == "argument"
    assert "argument" in result.notes[0], (
        "the provenance is not disclosed next to the outcome; a reader of the notes cannot "
        "tell an owned decision from a machine default (seam 4)"
    )

    # The argument branch never touches the standing declaration: it was not used, so it is
    # not consumed — the next argument-less run still finds it.
    result2 = non_inferiority(
        r0="pkg-v1", r1="pkg-v2", cohort_id=cohort, threshold=None,
        environ={ENV_THRESHOLD: "0.40"},
    )
    assert result2.threshold_source == "configuration" and result2.threshold_used == 0.10, (
        f"the standing declaration was consumed by a run that passed an explicit argument "
        f"(second run resolved from {result2.threshold_source!r} at "
        f"{result2.threshold_used!r}); the declaration is one-shot for the run that *uses* "
        "it, and this run did not use it"
    )


def test_tc_calib_08_a_standing_declaration_beats_the_environment():
    """Declaration set, env set, no argument → the declaration wins and the env is not read.

    The env channel exists so a deployment can carry the institution's number, not so a
    machine default can override the institution. An inversion would make the declaration
    ceremony: declared 0.10, env 0.40, gate runs at 0.40 and calls it configuration.
    """
    calib = require(CALIB_MODULE, issue="#140")
    non_inferiority = require(CALIB_MODULE, "non_inferiority", issue="#140")
    calib._clear_institutional_threshold()
    calib.declare_institutional_threshold(0.10)

    cohort = calib.cohort_with_band_shift(fraction=0.05, class_size=100)
    result = non_inferiority(
        r0="pkg-v1", r1="pkg-v2", cohort_id=cohort, threshold=None,
        environ={ENV_THRESHOLD: "0.40"},
    )

    assert result.threshold_used == 0.10, (
        f"the gate compared against {result.threshold_used!r}; the standing declaration is "
        "0.10 and the env fallback is the fallback"
    )
    assert result.threshold_source == "configuration"

    # One-shot consumption, the strictest honest reading of "declared before the comparison":
    # the declaration was consumed by the run that used it, so a second argument-less run
    # refuses rather than inheriting it (the env row alone remains, and is not silently
    # promoted into a decision it was never consulted for — the refusal names the problem).
    with pytest.raises(calib.ThresholdNotDeclared):
        non_inferiority(r0="pkg-v1", r1="pkg-v2", cohort_id=cohort, threshold=None)


def test_tc_calib_08_the_environment_is_the_fallback_and_says_so():
    """No argument, no declaration → the deployment's env, reported as source
    `"environment"`.

    The #139 carry-forward gap: `"configuration"` was the only source any green test named, so
    the env fallback could have returned any value, mis-reported its provenance, or defaulted
    the HLD's 0.10 — and every gate test would still pass. The distinction matters because a
    declaration is an owned decision and a machine default is not, and one reader of the result
    must be able to tell them apart.
    """
    calib = require(CALIB_MODULE, issue="#140")
    non_inferiority = require(CALIB_MODULE, "non_inferiority", issue="#140")
    calib._clear_institutional_threshold()

    cohort = calib.cohort_with_band_shift(fraction=0.05, class_size=100)
    result = non_inferiority(
        r0="pkg-v1", r1="pkg-v2", cohort_id=cohort, threshold=None,
        environ={ENV_THRESHOLD: "0.15"},
    )

    assert result.threshold_used == 0.15, (
        f"the gate compared against {result.threshold_used!r}; the deployment's env channel "
        f"declares 0.15 via {ENV_THRESHOLD}"
    )
    assert result.threshold_source == "environment", (
        f"the env-fallback threshold reported source {result.threshold_source!r}; "
        "'environment' is what distinguishes a machine default from the institution's "
        "declaration ('configuration') and the caller's argument ('argument')"
    )
    assert result.threshold_declared_at < result.first_result_at, (
        "the env-fallback threshold was not recorded before the first result either — the "
        "event-order oracle holds on every path, not only the declaration path"
    )
    assert "environment" in result.notes[0], (
        "the notes do not carry the provenance; the GateResult field and the note are the two "
        "readers of the same fact, and one going quiet is the drift this file exists to catch"
    )


# --- the mis-set channel, and the refusals -------------------------------------------------------


@pytest.mark.parametrize("mis_set", ["1.5", "abc", "", "   "])
def test_tc_calib_08_a_mis_set_env_value_is_unset_not_an_error(mis_set):
    """A mis-set env value falls through to `ThresholdNotDeclared` — the refusal that names the
    real problem.

    `"1.5"` is out of range, `"abc"` is not a float, blank is unset. None of them is a threshold;
    treating any as a parse-error `ValueError` would turn a misconfiguration into a crash that
    hides which knob was mis-set, and treating one as a *default* would be worse. The refusal is
    the gate saying: nothing usable was declared — pass one, declare one, or set the knob right.
    """
    calib = require(CALIB_MODULE, issue="#140")
    non_inferiority = require(CALIB_MODULE, "non_inferiority", issue="#140")
    calib._clear_institutional_threshold()

    cohort = calib.cohort_with_band_shift(fraction=0.05, class_size=100)
    with pytest.raises(calib.ThresholdNotDeclared) as exc:
        non_inferiority(
            r0="pkg-v1", r1="pkg-v2", cohort_id=cohort, threshold=None,
            environ={ENV_THRESHOLD: mis_set},
        )
    assert ENV_THRESHOLD in str(exc.value), (
        f"the refusal does not name {ENV_THRESHOLD}; the operator who set the mis-set value "
        "must be able to find it from the message"
    )


def test_tc_calib_08_an_out_of_range_argument_is_refused_at_the_gate():
    """`threshold=1.5` is not a threshold — the gate refuses, naming the fraction range.

    The declaration path refuses out-of-range at `declare_institutional_threshold`; the
    argument path refuses here. A negative or >1 threshold silently accepted would make
    "more than" either always-false (>=1 means nothing shifts enough) or always-true
    (<0 rejects every revision) — a gate that cannot lose is not a gate.
    """
    calib = require(CALIB_MODULE, issue="#140")
    non_inferiority = require(CALIB_MODULE, "non_inferiority", issue="#140")
    calib._clear_institutional_threshold()

    cohort = calib.cohort_with_band_shift(fraction=0.05, class_size=100)
    for bad in (1.5, -0.1):
        with pytest.raises(calib.CalibrationError) as exc:
            non_inferiority(
                r0="pkg-v1", r1="pkg-v2", cohort_id=cohort, threshold=bad,
            )
        assert "[0, 1]" in str(exc.value), (
            f"the refusal for threshold={bad!r} does not name the range it must fall in"
        )