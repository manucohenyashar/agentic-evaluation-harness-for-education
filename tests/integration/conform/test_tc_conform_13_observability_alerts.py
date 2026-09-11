"""`TC-CONFORM-13` — the run emits what a divergence needs to be attributable, and both alerts fire.

Case: test plan §5.18, `FR-CONFORM-06`, `FR-CONFORM-08`. Oracle: **exact signal plus alert**.

    | TC-CONFORM-13 | Observability / 2 | A run with a gate-crossing divergence and a
    | frozen-fixture score shift | Per-dimension divergence, fixture set version and both
    | backends' resolved builds are emitted; both alerts fire |

**Written ahead of implementation** (§8.2). Correctly red: the run machinery, the induced
divergence, the substitution seam and the alert reader are all #134's (`evaluate_conformance_
alerts` is the invented alert-surface name, disclosed in `conform_vocabulary.py` next to the two
shipped alert readers it is named after). The blocker is #134 and the test is registered there
in `WRITTEN_AHEAD_BLOCKERS`; remove the marker — never the test — when #134 closes. Rung 2, and
not `live`: everything this case asserts is a property of what the run *emits*, driven by the
suite's own induced-divergence and substitution seams.

**How this differs from TS-75's `CT-CONFORM-13`.** That case asserts the *resolved, not
requested* distinction — that the report carries the resolved builds and that a substituted
backend's resolved builds differ from what was asked for. This case asserts what §5.18 adds: the
combined precondition (a gate-crossing divergence **and** a score shift, in one run) drives both
alerts, and the alerts are honest — each fires exactly when its own condition holds, and nothing
fires when neither does. An alert that fired unconditionally is the observability failure that
trains the reader to ignore the channel, which is worse than silence.
"""

from __future__ import annotations

import pytest

from tests.support.conf_builders import EDGE_PANEL_3, HOSTED_PANEL_3, edge_cfg, hosted_cfg
from tests.support.conform_vocabulary import (
    ALERT_BUILD_SUBSTITUTION_DETECTED,
    ALERT_DIVERGENCE_GATE_CROSSED,
    CONFORMANCE_ALERT_SURFACE,
    DIVERGENCE_DIMENSIONS,
    LIVE_GATE_DIMENSION,
    OBSERVABILITY_FIELDS,
    RESOLVED_BUILDS_FIELD,
)
from tests.support.impl import CONFORM_MODULE, require

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#134"
CASE = "TC-CONFORM-13"


def _two_backends():
    return [edge_cfg(panel=EDGE_PANEL_3), hosted_cfg(panel=HOSTED_PANEL_3)]


def _synthetic_cohort():
    from aeh.conf import CohortRef

    return CohortRef(cohort_id="c-conform-fixtures", consent_class="synthetic")


def _run(build_suite, induce, substitute):
    """The case's combined precondition, composed: a substitution inside an induced gate crossing.

    `induce` gates the run's divergence measurement; `substitute` changes what one backend's
    provider serves under an unchanged name. They are independent seams, and the case requires
    both conditions in one run — which is why the context managers nest here rather than the
    conditions being asserted on two different reports.
    """
    backends = _two_backends()
    with substitute(backends[0]) as swapped:
        with induce(LIVE_GATE_DIMENSION):
            return build_suite().run("v1", [swapped, backends[1]], cohort=_synthetic_cohort())


def test_tc_conform_13_the_run_emits_the_observability_fields_with_both_resolved_builds():
    """The three emitted fields, with the divergence operand-complete and both builds named.

    Design §3.18's Observability line: *"Per run: per-dimension divergence, fixture set version,
    both backends' resolved builds."* The per-dimension divergence must carry **values** for the
    declared dimensions — field names with `None` behind them is the right shape measuring
    nothing. The fixture set version anchors the run to a named corpus. And the resolved builds
    are asserted **both**, here: TS-75's `CT-CONFORM-13` case already asserts they are resolved
    rather than requested (driven with a substitution so the two differ), so this case asserts
    the emission itself — both backends named, neither empty, which is what makes a divergence
    attributable on both sides.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    induce = require(CONFORM_MODULE, "induced_divergence", issue=ISSUE)
    substitute = require(CONFORM_MODULE, "silent_build_substitution", issue=ISSUE)
    load_fixture_set = require(CONFORM_MODULE, "load_fixture_set", issue="#133")

    fixtures = load_fixture_set("v1")
    report = _run(build_suite, induce, substitute)

    assert OBSERVABILITY_FIELDS <= set(report.observability), (
        f"the report emits {sorted(report.observability)}; design §3.18's observability line "
        f"requires {sorted(OBSERVABILITY_FIELDS)}"
    )

    per_dimension = report.observability["per_dimension_divergence"]
    assert set(per_dimension) == set(DIVERGENCE_DIMENSIONS), (
        f"the emitted per-dimension divergence covers {sorted(per_dimension)}; the five declared "
        f"dimensions are what a consumer reads"
    )
    blank = [d for d, value in per_dimension.items() if value is None]
    assert not blank, (
        f"the emitted divergence for {blank} is present and empty — the signal that looks "
        f"emitted and was not"
    )

    assert report.observability["fixture_set_version"] == fixtures.version, (
        f"the run reports fixture set {report.observability['fixture_set_version']!r}; the frozen "
        f"set it was given is {fixtures.version!r}. A divergence without its corpus is a number "
        f"nobody can reproduce."
    )

    resolved = report.observability[RESOLVED_BUILDS_FIELD]
    assert len(resolved) == 2, (
        f"the report names {len(resolved)} backend's resolved builds; the case says **both**, "
        f"and one side named is an attribution with a hole in the middle"
    )
    for profile, builds in resolved.items():
        assert builds, f"{profile}'s resolved builds are empty — named, but saying nothing"


@pytest.mark.parametrize(
    ("drive", "expected"),
    [
        ("clean", frozenset()),
        ("gate_only", frozenset({ALERT_DIVERGENCE_GATE_CROSSED})),
        ("substitution_only", frozenset({ALERT_BUILD_SUBSTITUTION_DETECTED})),
    ],
)
def test_tc_conform_13_each_alert_fires_exactly_when_its_own_condition_holds(drive, expected):
    """The controls that make 'both alerts fire' mean something — each keys on its own condition.

    The case's precondition is the combination, and the combined run is asserted in the next
    test. But 'both fire' is only a finding if the alerts are honest about *why*: a gate-crossing
    alert that also fires without a gate crossing, or a substitution alert that fires on a clean
    rerun, is an alert the reader must ignore — the channel failure, not a noisy signal. So each
    single-condition run is asserted to fire exactly its own alert, and the clean run fires
    nothing.

    Parametrized so a regression names which control broke: the negative control failing is a
    false-positive generator (every nightly pages); a single-condition control failing means one
    alert has lost its condition and is guessing.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    evaluate = require(CONFORM_MODULE, CONFORMANCE_ALERT_SURFACE, issue=ISSUE)
    induce = require(CONFORM_MODULE, "induced_divergence", issue=ISSUE)
    substitute = require(CONFORM_MODULE, "silent_build_substitution", issue=ISSUE)

    backends = _two_backends()
    if drive == "clean":
        report = build_suite().run("v1", backends, cohort=_synthetic_cohort())
    elif drive == "gate_only":
        with induce(LIVE_GATE_DIMENSION):
            report = build_suite().run("v1", backends, cohort=_synthetic_cohort())
    else:  # substitution_only
        with substitute(backends[0]) as swapped:
            report = build_suite().run("v1", [swapped, backends[1]], cohort=_synthetic_cohort())

    fired = {alert.kind for alert in evaluate(report)}
    assert fired == expected, (
        f"the {drive} run fired {sorted(fired)}; expected exactly {sorted(expected)}. The "
        f"alerts key on their own conditions — a fired alert without its condition, or a "
        f"condition without its alert, is an observability channel the reader cannot trust."
    )


def test_tc_conform_13_the_combined_run_fires_both_alerts_and_no_others():
    """*"Both alerts fire"* — the case's own precondition, asserted exactly.

    The gate crossed (the integrity gate, the one computable one) and the frozen fixtures
    shifted under an unchanged package: both conditions hold in one run, both alerts fire, and
    no third alert invents itself. The exact-set assertion is what keeps the alert channel
    additive by amendment only — a new alert is allowed, but by adding it to the declared set,
    not by a suite that never noticed a third kind firing.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    evaluate = require(CONFORM_MODULE, CONFORMANCE_ALERT_SURFACE, issue=ISSUE)
    induce = require(CONFORM_MODULE, "induced_divergence", issue=ISSUE)
    substitute = require(CONFORM_MODULE, "silent_build_substitution", issue=ISSUE)

    report = _run(build_suite, induce, substitute)

    fired = {alert.kind for alert in evaluate(report)}
    assert fired == {ALERT_DIVERGENCE_GATE_CROSSED, ALERT_BUILD_SUBSTITUTION_DETECTED}, (
        f"the combined run fired {sorted(fired)}; exactly both alerts were expected — "
        f"divergence_gate_crossed for the §7.4 gate and build_substitution_detected for the "
        f"frozen-fixture score shift (FR-CONFORM-06 + FR-CONFORM-08)."
    )