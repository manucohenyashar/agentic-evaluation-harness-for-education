"""The frozen set's score distribution, and what a shift in it means.

Case: `TC-REG-05` (test plan §6.9), `FR-CONFORM-01`, `FR-CONFORM-08`, statistical oracle.

    baseline  Per-criterion score distributions of `F-FROZEN` on each backend
    reviewer  The whole team, at release
    grounds   A shift with an unchanged package is build substitution (`FR-CONFORM-08`), not a
              baseline to update

This is the one row in §6.9 where **accepting the diff is itself the defect**. Everywhere else
a baseline update is a decision someone is allowed to make; here, a distribution that moved
while the package did not is the signal `FR-CONFORM-08` exists to raise — *"detect
provider-side build substitution by re-running the frozen fixtures and reporting a score shift
while nothing in the package changed"*. Updating the baseline would erase the only evidence
that the served model changed underneath the installation.

So the case has two halves and the second is the load-bearing one:

1. the distribution matches the baseline within a **stated** n and threshold, and
2. a re-run that *does* shift, with the package unchanged, is **reported as build
   substitution** rather than returned as a new distribution.

A suite with only the first half passes on a system that silently accepts drift.

**Two tiers, one case.** The fast tier runs against `RecordedFixtureProvider`, where the
distribution is exactly reproducible and the tolerance is zero. The per-backend sweep §6.9
asks for needs real backends, so it carries the `live` marker and runs nightly on E2/E3 — the
same split §4.7's command table applies to every other conformance case.

**Written ahead of implementation** (§8.2). `detect_build_substitution` is #134's. Remove the
marker — never the test — when #134 closes, and record the baseline in that PR.
"""

from __future__ import annotations

import json
import os

import pytest

from tests.support import corpora
from tests.support.baselines import assert_matches_golden, entry_for, load_json_baseline
from tests.support.impl import CONFORM_MODULE, require

pytestmark = pytest.mark.writtenahead

CASE = "TC-REG-05"
GOLDEN = "TC-REG-05/score-distributions.json"

# n, stated rather than implied: `FR-CONFORM-01`'s frozen set is 30-50 submissions and this
# repository's is 36. The figure is read from the corpus so the two cannot disagree.
FIXTURE_SET = "F-FROZEN"

# The threshold, env-gated per this repo's third seam. Zero is the production value for the
# recorded-fixture tier — that provider replays a stored response keyed by request hash, so any
# movement at all is a defect rather than sampling noise. A slower or differently-configured box
# does not change that, which is why the knob exists but the default does not move.
DISTRIBUTION_TOLERANCE = float(os.environ.get("HARNESS_CONFORM_DISTRIBUTION_TOLERANCE", "0.0"))
# The live tier compares two real serving stacks, where a small per-criterion shift is expected
# at temperature 0 (§4.6: model output is not deterministic across builds even at 0).
LIVE_DISTRIBUTION_TOLERANCE = float(
    os.environ.get("HARNESS_CONFORM_LIVE_DISTRIBUTION_TOLERANCE", "0.05")
)


def _distribution_bytes(distribution) -> bytes:
    return (json.dumps(distribution, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _assert_within(baseline, produced, tolerance: float, backend: str) -> None:
    """Per-criterion, per-band share, against the stated threshold."""
    drifted: dict[str, float] = {}
    for criterion_id, bands in baseline.items():
        for band, share in bands.items():
            actual = produced.get(criterion_id, {}).get(band, 0.0)
            if abs(actual - share) > tolerance:
                drifted[f"{criterion_id}/{band}"] = actual - share
    assert not drifted, (
        f"backend {backend}: {len(drifted)} per-criterion band share(s) moved beyond the "
        f"declared tolerance {tolerance}: {dict(list(drifted.items())[:6])}. Per §6.9 this is "
        f"**not** a baseline to update — FR-CONFORM-08 makes a shift under an unchanged package "
        f"build substitution, and updating the baseline erases the only evidence of it."
    )


def test_tc_reg_05_the_frozen_set_distribution_holds_and_a_shift_is_reported_as_substitution():
    """TC-REG-05 — per-criterion score distributions of `F-FROZEN`.

    Oracle: statistical, with n and threshold stated, plus the `FR-CONFORM-08` detection.
    """
    load_fixture_set = require(CONFORM_MODULE, "load_fixture_set", issue="#133")
    detect_build_substitution = require(
        CONFORM_MODULE, "detect_build_substitution", issue="#134"
    )
    entry = entry_for(CASE)

    corpus = corpora.load(FIXTURE_SET)
    n = len(corpus.members)
    assert 30 <= n <= 50, f"FR-CONFORM-01: the frozen set is 30-50 submissions, found {n}"

    suite = load_fixture_set(FIXTURE_SET)
    report = suite.run(backend="recorded-fixture")

    produced = report.per_criterion_distribution
    assert_matches_golden(CASE, GOLDEN, _distribution_bytes(produced))
    _assert_within(load_json_baseline(CASE, GOLDEN), produced, DISTRIBUTION_TOLERANCE, "recorded-fixture")

    # The half that carries `FR-CONFORM-08`. A distribution that shifted while the package
    # version is unchanged must come back as a *detection*, not as a value the caller is free to
    # write over the baseline.
    shifted = suite.run(backend="recorded-fixture", simulate_build_change=True)
    verdict = detect_build_substitution(
        baseline=report, rerun=shifted, package_version=report.package_version
    )
    assert verdict.substitution_detected, (
        f"the frozen set's distribution shifted with the package unchanged and "
        f"detect_build_substitution reported nothing. That is FR-CONFORM-08's whole promise, "
        f"and without it the shift reads as a baseline to refresh.\n\n{entry.governance()}"
    )
    assert verdict.package_version_changed is False, (
        "detect_build_substitution reported the package as changed. The signal is only "
        "meaningful for an *unchanged* package; attributing the shift to the package is how a "
        "substituted build gets explained away."
    )


@pytest.mark.live
def test_tc_reg_05_the_frozen_set_distribution_holds_on_each_live_backend():
    """TC-REG-05, live half — the per-backend sweep §6.9's baseline is stated over.

    Nightly on E2/E3 (§4.7). Separate from the fast-tier half rather than parametrized into it,
    so the fast tier stays free of any live dependency (`FR-CONFORM-07`).
    """
    load_fixture_set = require(CONFORM_MODULE, "load_fixture_set", issue="#133")
    baseline = load_json_baseline(CASE, GOLDEN)

    suite = load_fixture_set(FIXTURE_SET)
    for backend in ("local-server", "openrouter"):
        report = suite.run(backend=backend)
        _assert_within(
            baseline, report.per_criterion_distribution, LIVE_DISTRIBUTION_TOLERANCE, backend
        )
