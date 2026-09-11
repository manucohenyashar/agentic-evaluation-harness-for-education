"""`TC-CONFORM-08`, the behavioural half — the score shift, detected and attributed.

Case: test plan §5.18, `FR-CONFORM-08`, R22. Oracle: **differential against the prior run**.

    | TC-CONFORM-08 | Integration, live / 4 | Frozen fixtures re-run after a provider-side build
    | substitution, with the package unchanged | A score shift is detected and reported as build
    | substitution rather than as a package change |

**Written ahead of implementation** (§8.2). Correctly red: the run machinery, the substitution
seam and the detector are all #134's (`silent_build_substitution` and
`detect_build_substitution` are the invented names `CT-CONFORM-07` uses; whoever implements #134
adopts or renames them in both places). The blocker is #134 and the test is registered there in
`WRITTEN_AHEAD_BLOCKERS`; remove the marker — never the test — when #134 closes. Marked `live`
because the thing being substituted is the model a real backend serves; the gate skips naming
`HARNESS_CONFORM_LIVE_BACKENDS` when no live backend is declared (the shared gate lives in
`tests/support/conform_vocabulary.py`).

**How this differs from TS-75's `CT-CONFORM-07`.** That case asserts the **attribution**: given a
rerun in the silent configuration, the detector names the provider rather than the package. This
file asserts the **detection itself**, two ways the contract case cannot:

* **The shift is real.** The substituted backend's per-criterion scores are asserted to have
  actually moved between the prior run and the rerun before the detector is asserted to have
  noticed. "A score shift is detected" needs a shift to detect — an attribution asserted without
  one would pass a detector that reports substitution on every rerun.
* **The negative control.** An honest rerun of the same backends under the same package detects
  nothing. A detector that fired there would page on every nightly run — the false positive is
  the defect, and it is exactly the one an implementation keyed on "any difference" would have.
  On live backends an honest repeat may vary naturally; if that variation crosses the detector,
  this case wants to know, because a detector that cannot tolerate an honest rerun is not a
  detector.

The merge of the two is the case's point: detection driven by the differential, attribution that
sends the reader to the provider — not to a rubric nobody changed.
"""

from __future__ import annotations

import pytest

from tests.support.conform_vocabulary import (
    SCORE_DISTRIBUTION_DIMENSION,
    live_conformance_backends,
)
from tests.support.impl import CONFORM_MODULE, require

pytestmark = [pytest.mark.integration, pytest.mark.live, pytest.mark.writtenahead]

ISSUE = "#134"
CASE = "TC-CONFORM-08"


def _synthetic_cohort():
    from aeh.conf import CohortRef

    return CohortRef(cohort_id="c-conform-fixtures", consent_class="synthetic")


def test_tc_conform_08_a_silent_build_substitution_is_detected_from_its_score_shift():
    """The shift happens, the detector sees it, and the attribution is the provider's.

    Three assertions in the order the causal chain runs:

    **The rerun is the silent configuration.** `BuildChangedError` did not fire — otherwise this
    is `CT-PROV-05`'s case and no detection path was ever reached.

    **The shift is real.** The substituted backend's per-criterion score distribution moved
    between the prior run and the rerun, over the same frozen fixture set (the input hash is
    asserted equal first — a shift over a different set is not a shift, it is a different
    measurement). Detection without a shift to detect would be a detector that fires on
    nothing.

    **The report says build substitution, not package change.** The package is unchanged; the
    scores moved because what the provider serves under the unchanged name moved. A package
    finding sends someone to audit a rubric nobody touched while the substitution keeps running.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    detect = require(CONFORM_MODULE, "detect_build_substitution", issue=ISSUE)
    substitute = require(CONFORM_MODULE, "silent_build_substitution", issue=ISSUE)

    backends = live_conformance_backends()
    suite = build_suite()
    baseline = suite.run("v1", backends, cohort=_synthetic_cohort())

    with substitute(backends[0]) as swapped:
        rerun = suite.run("v1", [swapped], cohort=_synthetic_cohort())

    assert not rerun.build_changed_error_raised, (
        "M-PROV's BuildChangedError fired, so this run is not the configuration FR-CONFORM-08 "
        "exists for — the substitution this case detects is the one the provider's own gate "
        "cannot see."
    )

    substituted = backends[0]["HARNESS_PROFILE"]
    assert (
        rerun.input_set_hash == baseline.input_set_hash
    ), (
        f"the rerun consumed a different input set ({rerun.input_set_hash} vs "
        f"{baseline.input_set_hash}). The differential is against the prior run over the same "
        f"frozen fixtures; a shift over a different set is a different measurement."
    )
    shift = (
        rerun.per_backend[substituted].figures[SCORE_DISTRIBUTION_DIMENSION]
        != baseline.per_backend[substituted].figures[SCORE_DISTRIBUTION_DIMENSION]
    )
    assert shift, (
        f"the substituted backend's per-criterion scores did not move between the prior run and "
        f"the rerun, so 'a score shift is detected' would be a detector firing on nothing. The "
        f"case's differential needs the shift in the data before the detector is trusted to "
        f"report it."
    )

    finding = detect(baseline, rerun)
    assert finding is not None, (
        "the frozen fixtures scored differently with the package unchanged and nothing was "
        "reported (FR-CONFORM-08)"
    )
    assert finding.attribution == "provider_side_build_substitution", (
        f"the score shift was attributed to {finding.attribution!r}. A package finding sends "
        f"someone to audit a rubric nobody changed while the substitution keeps running."
    )
    assert not finding.package_changed, (
        "the substitution was reported as a package change. The package is unchanged; the "
        "build the provider serves is what moved."
    )


def test_tc_conform_08_an_honest_rerun_detects_nothing():
    """The negative control — the detector keys on the substitution, not on any rerun.

    A detector that fired on an honest repeat of the same backends would page on every nightly
    run, and an alert nobody can trust is an alert that gets switched off. The control is strict
    (`None`), deliberately: the honest rerun varies only by run noise, so a finding here means
    the detector cannot tell a substitution from run-to-run variance — which is the detection
    being useless in the direction nobody tests for.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    detect = require(CONFORM_MODULE, "detect_build_substitution", issue=ISSUE)

    backends = live_conformance_backends()
    suite = build_suite()
    baseline = suite.run("v1", backends, cohort=_synthetic_cohort())
    repeat = suite.run("v1", backends, cohort=_synthetic_cohort())

    assert repeat.input_set_hash == baseline.input_set_hash, (
        "the honest rerun consumed a different input set, so this is not a repeat and the "
        "negative control proves nothing"
    )
    assert detect(baseline, repeat) is None, (
        "an honest rerun of the same backends raised a build-substitution finding. A detector "
        "that fires on run-to-run variance pages on every nightly and is a false-positive "
        "generator — the one failure that makes FR-CONFORM-08's detection unusable."
    )