"""`TC-CONFORM-12` — self-agreement, reported per backend, with its n stated.

Case: test plan §5.18, `FR-CONFORM-04` (the self-agreement dimension), §6.11.18's figure rules.
Oracle: **statistical with stated n**.

    | TC-CONFORM-12 | Integration / 3 | A conformance run's self-agreement dimension | Each
    | fixture judgment repeated and self-agreement computed; the figure is reported per backend
    | and never merged | Statistical with stated n |

**Written ahead of implementation** (§8.2). Correctly red: the run that produces the repeated
judgments is #134's (`ConformanceSuite.run` stops at `NotImplementedError` naming #134 after the
consent gate). The blocker is #134 and the test is registered there in `WRITTEN_AHEAD_BLOCKERS`;
remove the marker — never the test — when #134 closes. Rung 3, and not `live`: the repetition
the case measures is a run property (the same fixtures judged again), driven through the suite's
own machinery, not a property of a live model's uptime.

**Why the oracle is the `n` and the split, not a value.** A self-agreement number with no stated
`n` is a number nobody can weigh — and `n` below two means nothing was repeated, so the figure
is whatever one judgment says twice. The clause asks for the *measurement*: judgment repeated,
agreement computed, figure per backend. Whether a backend's agreement is *good* is exactly what
the design declines to threshold (that is `FR-CONFORM-06`'s Q-02 gap, recorded in §7.4) — so no
threshold is invented here either. What is required is that the figure exist, per backend, with
the sample size it was computed from attached, and that no single merged figure answers for both
backends.

**How this differs from TS-75's coverage.** `CT-CONFORM-04`'s no-headline sweep exempts the five
declared dimension names wholesale; this case's claim is narrower and needs its own net — the
self-agreement figure specifically must not appear at the report level under any name other than
the declared comparison dimension, because a pooled `self_agreement` is the figure a release
decision reaches for and it describes no single backend.
"""

from __future__ import annotations

import pytest

from tests.support.conf_builders import EDGE_PANEL_3, HOSTED_PANEL_3, edge_cfg, hosted_cfg
from tests.support.conform_vocabulary import (
    MIN_SELF_AGREEMENT_REPEATS,
    PER_BACKEND_FIGURES_FIELD,
    SELF_AGREEMENT_DIMENSION,
    SELF_AGREEMENT_FIELD,
    SELF_AGREEMENT_REPEATS_FIELD,
)
from tests.support.impl import CONFORM_MODULE, require

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#134"
CASE = "TC-CONFORM-12"


def _two_backends():
    return [edge_cfg(panel=EDGE_PANEL_3), hosted_cfg(panel=HOSTED_PANEL_3)]


def _synthetic_cohort():
    from aeh.conf import CohortRef

    return CohortRef(cohort_id="c-conform-fixtures", consent_class="synthetic")


def test_tc_conform_12_each_backend_reports_a_self_agreement_figure_with_its_n_stated():
    """The figure exists per backend, and its `n` is stated and at least two.

    *"Each fixture judgment repeated and self-agreement computed."* The repetition is what the
    `n` states, and the case's oracle — statistical with stated n — makes the `n` part of the
    figure rather than a property of the run: a figure without its `n` is a number nobody can
    weigh, and `n` below two means nothing was repeated, so the "agreement" computed is one
    judgment agreeing with itself.

    Asserted on the figure mapping itself rather than on a separate attribute, so the `n`
    cannot travel apart from the figure it qualifies.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    report = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())

    assert set(report.per_backend) == {cfg["HARNESS_PROFILE"] for cfg in _two_backends()}, (
        f"the run measured {sorted(report.per_backend)}; the figure is reported per backend the "
        f"run declared"
    )
    for profile, result in report.per_backend.items():
        figures = getattr(result, PER_BACKEND_FIGURES_FIELD, None)
        assert figures is not None, (
            f"{profile}'s result carries no {PER_BACKEND_FIGURES_FIELD!r} mapping, so there is "
            f"no per-backend figure to state an n for"
        )
        figure = figures.get(SELF_AGREEMENT_FIELD)
        assert isinstance(figure, dict) and figure, (
            f"{profile}'s self-agreement figure is {type(figure).__name__}, not a mapping. A "
            f"bare number cannot carry the n that qualifies it (TC-CONFORM-12: statistical with "
            f"stated n)."
        )
        n = figure.get(SELF_AGREEMENT_REPEATS_FIELD)
        assert isinstance(n, int) and not isinstance(n, bool), (
            f"{profile}'s self-agreement figure states n={n!r}, which is not an integer count. "
            f"'Stated n' means a count of repeats a reader can weigh the figure against."
        )
        assert n >= MIN_SELF_AGREEMENT_REPEATS, (
            f"{profile}'s self-agreement figure states n={n}; below {MIN_SELF_AGREEMENT_REPEATS} "
            f"nothing was repeated and the 'agreement' is one judgment agreeing with itself."
        )


def test_tc_conform_12_no_report_level_surface_merges_the_backends_self_agreement():
    """*"Reported per backend and never merged"* — the pooled figure has nowhere to live.

    Two halves. First the positive: both backends carry their own figure, so "per backend" is
    about the two of them and not about one lucky profile. Then the negative, swept over the
    report's own surfaces: the only self-agreement-named surface outside the per-backend figures
    is the declared divergence dimension — the *comparison* of the two backends' figures, which
    is required. Any other self-agreement-named attribute at the report or divergence level is a
    single figure answering for both backends, and that is the merge.

    The reason this needs its own net rather than `CT-CONFORM-04`'s headline sweep: that sweep
    exempts the five dimension names wholesale and hunts for a single conformance *score*. A
    pooled self-agreement figure is not a conformance score — it is one backend-shaped number
    standing in for two measurements, and the release decision reaches for it precisely because
    it is not a score.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    report = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())

    per_backend_figures = 0
    for profile, result in report.per_backend.items():
        figures = getattr(result, PER_BACKEND_FIGURES_FIELD, None)
        assert figures is not None and SELF_AGREEMENT_FIELD in figures, (
            f"{profile} carries no self-agreement figure; 'reported per backend' means each "
            f"backend's figure exists, not that one backend's answers for both"
        )
        per_backend_figures += 1
    assert per_backend_figures == 2, (
        f"{per_backend_figures} backend(s) carry a self-agreement figure; a differential runs "
        f"two backends and the figure is per backend"
    )

    for label, surface in (("ConformanceReport", report), ("DivergenceReport", report.divergence)):
        pooled = [
            name
            for name in dir(surface)
            if not name.startswith("_")
            and SELF_AGREEMENT_FIELD in name
            and name != SELF_AGREEMENT_DIMENSION
        ]
        assert not pooled, (
            f"{label} exposes {pooled}: a self-agreement surface outside the declared dimension "
            f"and outside the per-backend figures. A single figure answering for both backends "
            f"is the merge the case forbids — it describes no backend, and the release decision "
            f"reads it as if one existed."
        )