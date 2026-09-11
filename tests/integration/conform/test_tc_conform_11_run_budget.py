"""`TC-CONFORM-11` — the run is at the declared load, and the budget is per backend.

Case: test plan §5.18, `NFR-CONFORM-02`, R28. Oracle: **metric threshold**.

    | TC-CONFORM-11 | Performance / 4 | A conformance run at 30-50 fixtures | Completes in well
    | under an hour per backend, so it can gate a release rather than being deferred |

**Landed at #134** (unmarked there): the run machinery is `ConformanceSuite.run`'s, and the
per-backend accounting below reads the report it returns.

**Rung 4, read honestly — the threshold is measured only where it can fail for the reason the
case exists.** §4.7 prices the budget at `< 60 min per backend`, which is live-model wall clock:
a recorded-transport run is seconds long, so `duration < 3600` asserted there can never fail for
the reason `NFR-CONFORM-02` exists — a threshold that cannot fail is a tautology wearing the
case's name, not the case's oracle. The threshold test below is therefore `live`-marked and
env-gated on `HARNESS_CONFORM_LIVE_BACKENDS` (the shared gate in `conform_vocabulary.py`, like
`TC-CONFORM-04`/`-08`), and the standing nightly measurement is carried by §4.7's conformance
command — the tier wiring `TC-CONFORM-07` asserts — not by this file on a default box.

**What runs everywhere.** The case's precondition is the load: "at 30-50 fixtures". Both bounds
are asserted against the frozen set itself in both tests — TS-75's `CT-CONFORM-C11` asserts only
the lower bound, and a run below 30 measures something smaller than the requirement describes
while a run above 50 is no longer the frozen set the conformance identity is pinned to
(NFR-CONFORM-01 keeps the two sets disjoint by content hash, `TC-CONFORM-10`). The first test
adds the per-backend accounting on the recorded transport: the report carries a result for every
backend the run declared — the reading "per backend" prices.
"""

from __future__ import annotations

import pytest

from tests.support.conf_builders import EDGE_PANEL_3, HOSTED_PANEL_3, edge_cfg, hosted_cfg
from tests.support.conform_vocabulary import (
    CONFORMANCE_BUDGET_SECONDS,
    CORPUS_MAX,
    CORPUS_MIN,
    live_conformance_backends,
)
from tests.support.impl import CONFORM_MODULE, require

pytestmark = [pytest.mark.integration]

ISSUE = "#134"
CASE = "TC-CONFORM-11"


def _two_backends():
    return [edge_cfg(panel=EDGE_PANEL_3), hosted_cfg(panel=HOSTED_PANEL_3)]


def _synthetic_cohort():
    from aeh.conf import CohortRef

    return CohortRef(cohort_id="c-conform-fixtures", consent_class="synthetic")


def _assert_load_bounds(fixtures):
    count = len(fixtures.fixture_ids)
    assert CORPUS_MIN <= count <= CORPUS_MAX, (
        f"the frozen set holds {count} fixtures; NFR-CONFORM-02's bound is stated at "
        f"{CORPUS_MIN}-{CORPUS_MAX} and the load is part of the claim — a run below it measures "
        f"a smaller corpus, a run above it is no longer the set the suite is pinned to."
    )


def test_tc_conform_11_a_run_at_the_declared_load_accounts_each_backend_it_declares():
    """Both load bounds, then the per-backend accounting — true on any transport.

    **The load bounds.** "A conformance run at 30-50 fixtures" is the precondition that makes
    the measurement mean anything: below 30 the run does not exercise the score range the set
    declares, and above 50 it is no longer the frozen set the suite is pinned to. Both are
    asserted against the frozen set itself, so a trimmed or padded corpus fails before the run
    is even taken.

    **The accounting.** The report carries a result for every backend the run declared. The
    threshold itself is asserted only in the live-marked test below: on this transport a run
    is seconds long and `duration < 3600` could not fail for the reason `NFR-CONFORM-02`
    exists, so asserting it here would be a tautology wearing the case's name.
    """
    # #134 first, deliberately: this test is registered against #134, and `require()` reports
    # whichever blocker it reaches first — a failure naming the wrong issue is how a gate stops
    # being believed.
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    load_fixture_set = require(CONFORM_MODULE, "load_fixture_set", issue="#133")

    fixtures = load_fixture_set("v1")
    _assert_load_bounds(fixtures)

    report = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())
    assert set(report.per_backend) == {cfg["HARNESS_PROFILE"] for cfg in _two_backends()}, (
        f"the run measured {sorted(report.per_backend)}; the budget and every figure this "
        f"suite reads are keyed per backend the run declared"
    )


@pytest.mark.live
@pytest.mark.slow
def test_tc_conform_11_the_live_run_completes_within_the_declared_budget_per_backend():
    """The threshold, measured through the live backends — `< 60 min` per backend, never summed.

    *"Completes in well under an hour per backend, so it can gate a release."* Per backend
    because two backends inside one hour is a different claim from each backend inside one
    hour — summed, a fast edge run subsidises a hosted run that had quietly become unusable.
    The durations are the per-backend result's own, so a report carrying one total duration
    fails here before any comparison is made.

    Env-gated on `HARNESS_CONFORM_LIVE_BACKENDS` (skips naming it when unset): the wall clock
    this case prices is live-model latency through the real pipeline, and measuring it against
    the recorded transport would assert a bound that cannot bind.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    load_fixture_set = require(CONFORM_MODULE, "load_fixture_set", issue="#133")

    fixtures = load_fixture_set("v1")
    _assert_load_bounds(fixtures)

    backends = live_conformance_backends()
    report = build_suite().run("v1", backends, cohort=_synthetic_cohort())
    assert set(report.per_backend) == {cfg["HARNESS_PROFILE"] for cfg in backends}, (
        f"the run measured {sorted(report.per_backend)}; the budget is asserted per backend the "
        f"run declared"
    )
    for profile, result in report.per_backend.items():
        assert result.duration_seconds < CONFORMANCE_BUDGET_SECONDS, (
            f"{profile} took {result.duration_seconds:.0f}s against a budget of "
            f"{CONFORMANCE_BUDGET_SECONDS}s. NFR-CONFORM-02's bound exists so this suite can "
            f"gate a release rather than being deferred to a nightly nobody reads."
        )