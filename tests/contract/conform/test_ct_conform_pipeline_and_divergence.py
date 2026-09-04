"""`CT-CONFORM-03`, `-04`, `-05`, `-07`, `-13` — the run, the report, and what the report may claim.

Test plan §6.11.18, TS-75 (issue #136). Where the corpus clauses ask *what is measured*, these ask
*how*, and each names a shortcut that would leave the suite green:

* `-03` — a run that stubbed ingestion *"would compare the two backends on the one stage where
  they differ most"*, and identity of the input set is asserted **by content hash rather than by
  construction**, because passing the same object twice proves nothing about what each backend
  consumed.
* `-04` — five dimensions by set equality, and then the prohibition: *"there is no single
  conformance score"*, because *"a headline number would be exactly what a release decision
  reaches for and would hide the one dimension that matters"*.
* `-05` — the gate/finding split, asserted per dimension, with the first gate reported
  **unavailable** rather than silently passing (`CT-CONFORM-14`).
* `-07` — build substitution attributed to the provider, run *"specifically in the configuration
  where `BuildChangedError` does not fire"*.
* `-13` — **resolved** builds, both of them.

Every case here is written ahead of #134 and every one is correctly red. See
`test_ct_conform_corpus.py`'s docstring for why the names are invented, and
`test_ct_conform_vocabulary.py` for what runs green today and why it is not coverage.
"""

from __future__ import annotations

import pytest

from tests.support.conf_builders import EDGE_PANEL_3, HOSTED_PANEL_3, edge_cfg, hosted_cfg
from tests.support.conform_vocabulary import (
    CLASSIFICATION_BLOCKING,
    CLASSIFICATION_INFORMATIONAL,
    CLASSIFICATION_UNAVAILABLE,
    DIVERGENCE_DIMENSIONS,
    EXPECTED_CLASSIFICATION,
    INFORMATIONAL_DIMENSIONS,
    LIVE_GATE_DIMENSION,
    PIPELINE_STAGES,
    REQUESTED_BUILDS_FIELD,
    RESOLVED_BUILDS_FIELD,
    UNAVAILABLE_GATE_DIMENSION,
    UNSTUBBABLE_STAGE,
    combined_figure_names,
)
from tests.support.impl import CONFORM_MODULE, require

pytestmark = pytest.mark.contract


def _two_backends():
    """Two `RunConfig` inputs differing only in backend, with three-judge panels.

    Three judges rather than one because `edge_cfg()` and `hosted_cfg()` default to a single-member
    panel, and a per-backend assertion over `panel[:1]` is indistinguishable from a correct one
    when the panel has one member — the blind spot `conf_builders` documents.
    """
    return [edge_cfg(panel=EDGE_PANEL_3), hosted_cfg(panel=HOSTED_PANEL_3)]


def _synthetic_cohort():
    from aeh.conf import CohortRef

    return CohortRef(cohort_id="c-conform-fixtures", consent_class="synthetic")


# --- CT-CONFORM-03 — the identical set, the full pipeline -------------------------------------------


@pytest.mark.writtenahead
def test_tc_conform_c03_every_stage_runs_for_every_fixture_on_every_backend():
    """`CT-CONFORM-03` — *"the **full** pipeline on each backend, with **no stubs for ingestion**"*.

    Asserted as a per-fixture, per-backend, per-stage sweep rather than as a completion flag,
    because a run that skipped ingestion completes: every later stage receives a cached transcript
    and reports success, and the summary is indistinguishable from a real run. Ingestion is where
    the two backends' transcribers differ most, so skipping it measures the half where they agree
    and calls the result conformance.

    `ingest` is asserted separately from the rest even though the sweep already covers it, so a
    failure says *ingestion was stubbed* rather than *some stage was missing on some fixture*.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    report = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())

    assert len(report.per_backend) == 2, "a conformance run compares two backends"

    for profile, result in report.per_backend.items():
        assert result.stages_executed, f"{profile} executed no stages at all"
        for submission_id, stages in result.stages_executed.items():
            missing = set(PIPELINE_STAGES) - set(stages)
            assert not missing, (
                f"{profile}/{submission_id} skipped {sorted(missing)}. CT-CONFORM-03 requires the "
                f"full pipeline on each backend."
            )
            assert UNSTUBBABLE_STAGE in stages, (
                f"{profile}/{submission_id} did not run {UNSTUBBABLE_STAGE!r}. A conformance run "
                f"that stubs ingestion compares the two backends on the one stage where they "
                f"differ most."
            )


@pytest.mark.writtenahead
def test_tc_conform_c03_both_backends_consumed_the_same_input_set_by_content_hash():
    """`CT-CONFORM-03`'s identity claim, asserted over what each backend **consumed**.

    §6.11.18 is specific: *"Assert identity of the input set across backends by content hash
    rather than by construction."* Handing the same fixture object to two runs and then asserting
    the object equals itself is a tautology — it holds no matter what either backend actually read,
    including a backend that silently dropped the fixtures it could not parse.

    So each `BackendResult` carries the hash of the inputs *it* consumed, and the assertion is that
    the two agree with each other **and** with the frozen set's own identity. The third comparison
    is what catches the case where both backends dropped the same fixtures.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    load_fixture_set = require(CONFORM_MODULE, "load_fixture_set", issue="#133")

    fixtures = load_fixture_set("v1")
    report = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())

    hashes = {profile: r.input_set_hash for profile, r in report.per_backend.items()}
    assert len(set(hashes.values())) == 1, (
        f"the two backends consumed different input sets: {hashes}. Everything the report says "
        f"about divergence is then a statement about two different corpora."
    )
    assert set(hashes.values()) == {fixtures.content_hash}, (
        f"both backends agree with each other but not with the frozen set ({fixtures.content_hash}"
        f"): they consumed the same *subset*, which agrees on every dimension by construction"
    )


# --- CT-CONFORM-04 — five dimensions, and no headline ------------------------------------------------


@pytest.mark.writtenahead
def test_tc_conform_c04_the_divergence_report_covers_exactly_the_five_dimensions():
    """`CT-CONFORM-04` — set equality, in both directions.

    Equality rather than containment: a report covering four dimensions is missing a measurement,
    and a report covering six has added one nobody agreed to — the compatibility note calls a new
    dimension *additive*, so it is allowed, but it is allowed by amending the clause rather than by
    a suite that never noticed.

    Each dimension is also asserted **present as a value**, not merely as an attribute name. A
    `DivergenceReport` with five fields all set to `None` has the right shape and has measured
    nothing, which is the silent-failure trap `CLAUDE.md` names first.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    report = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())
    divergence = report.divergence

    assert set(divergence.dimensions) == DIVERGENCE_DIMENSIONS, (
        f"DivergenceReport covers {sorted(divergence.dimensions)}; CT-CONFORM-04 declares "
        f"{sorted(DIVERGENCE_DIMENSIONS)}"
    )
    unmeasured = [d for d in DIVERGENCE_DIMENSIONS if divergence.dimensions[d] is None]
    assert not unmeasured, (
        f"these dimensions are declared and unmeasured: {unmeasured}. The right shape with no "
        f"values is the failure that looks like success."
    )


@pytest.mark.writtenahead
def test_tc_conform_c04_no_surface_carries_a_single_combined_conformance_figure():
    """`CT-CONFORM-04`'s prohibition — *"there is no single conformance score"*.

    The reason the clause states is the reason the case exists: *"a headline number would be
    exactly what a release decision reaches for and would hide the one dimension that matters"*.
    And one of those five dimensions is a gate that **cannot fire** (`CT-CONFORM-14`), so a
    headline that averaged the five would be reporting a number partly composed of a measurement
    nobody can make.

    The net exempts the five declared dimension names, since one of them contains the token
    `score` by construction — its controls run green in `test_ct_conform_vocabulary.py`.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    report = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())

    for label, surface in (("ConformanceReport", report), ("DivergenceReport", report.divergence)):
        names = [n for n in dir(surface) if not n.startswith("_")]
        assert names, f"{label} exposes no public names, so this sweep would pass vacuously"
        offenders = combined_figure_names(names)
        assert not offenders, (
            f"{label} exposes {offenders}, which read as a single combined conformance figure or "
            f"an overall pass/fail. CT-CONFORM-04: each dimension is reported separately."
        )


# --- CT-CONFORM-05 — two gates, three findings --------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_conform_c05_an_evidence_integrity_divergence_blocks_rather_than_being_noted():
    """`CT-CONFORM-05`'s **live** gate — the one that is computable and does fire.

    *"An evidence-integrity failure-rate divergence is a §7.4 gate failure, not a metrics note."*
    Driven rather than asserted over a static report: the case induces a divergence on that one
    dimension and asserts the run **blocks**. A report that merely labels the dimension `blocking`
    while completing has recorded an intention.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    classify = require(CONFORM_MODULE, "classify_divergence", issue="#134")

    outcome = build_suite().run(
        "v1", _two_backends(), cohort=_synthetic_cohort(),
        induced_divergence=LIVE_GATE_DIMENSION,
    )

    assert classify(LIVE_GATE_DIMENSION, outcome.divergence) == CLASSIFICATION_BLOCKING
    assert outcome.blocked, (
        f"a divergence on {LIVE_GATE_DIMENSION} did not block. §7.4 records this half as the one "
        f"that **is** computable and **is** gated; demoting it to a metrics note is the failure "
        f"CT-CONFORM-05 names."
    )
    assert LIVE_GATE_DIMENSION in outcome.blocking_dimensions


@pytest.mark.writtenahead
@pytest.mark.parametrize("dimension", sorted(INFORMATIONAL_DIMENSIONS))
def test_tc_conform_c05_the_three_remaining_dimensions_are_findings_not_failures(dimension):
    """`CT-CONFORM-05`'s default — *"divergence is a **finding, not a failure**"*.

    Parametrized so a regression names which dimension started blocking. The direction matters as
    much as the gates: an implementation that blocked on self-agreement would stop a release on a
    property `CT-JUDGE-17` explicitly does **not** promise — verdicts are not reproducible, which
    is why `M-STATS` *measures* self-agreement rather than assuming it.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    classify = require(CONFORM_MODULE, "classify_divergence", issue="#134")

    outcome = build_suite().run(
        "v1", _two_backends(), cohort=_synthetic_cohort(), induced_divergence=dimension,
    )

    assert classify(dimension, outcome.divergence) == CLASSIFICATION_INFORMATIONAL
    assert not outcome.blocked, (
        f"a divergence on {dimension} blocked the run. Only two dimensions are gates; everything "
        f"else is a finding for human judgement (CT-CONFORM-05)."
    )
    assert dimension in outcome.findings, (
        f"{dimension} diverged and was neither a gate nor a finding — it was silent, which is the "
        f"one outcome the clause does not offer"
    )


@pytest.mark.writtenahead
def test_tc_conform_c05_the_score_distribution_gate_is_reported_unavailable_not_passing():
    """`CT-CONFORM-05`'s first gate, read together with `CT-CONFORM-14`.

    The clause declares this gate; `CT-CONFORM-14` declares it **not computable as written**,
    because "material" has no statistic and no threshold (design §4.6 item 2). Those two are
    consistent only if the report says so.

    The failure this catches is the comfortable one: a gate that cannot fire reports `pass`, and a
    release decision reads a green gate. *"A consumer must not report backend equivalence on the
    strength of a gate that cannot fire"* — and a gate reporting `pass` is the strength it would
    be read on. `unavailable` is the honest third value, and the partition asserted alongside is
    what stops a fourth appearing.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    classify = require(CONFORM_MODULE, "classify_divergence", issue="#134")

    outcome = build_suite().run(
        "v1", _two_backends(), cohort=_synthetic_cohort(),
        induced_divergence=UNAVAILABLE_GATE_DIMENSION,
    )

    assert classify(UNAVAILABLE_GATE_DIMENSION, outcome.divergence) == CLASSIFICATION_UNAVAILABLE
    assert UNAVAILABLE_GATE_DIMENSION in outcome.unavailable_dimensions, (
        "the score-distribution gate is not reported unavailable, so a reader cannot tell 'did "
        "not fire' from 'cannot fire' (CT-CONFORM-14)"
    )
    assert UNAVAILABLE_GATE_DIMENSION not in outcome.passing_dimensions, (
        "a gate with no declared statistic reported a pass. That is the value a release decision "
        "reads, and there is nothing behind it."
    )

    # The whole partition, so a dimension cannot be quietly dropped from the classification while
    # the three assertions above stay green.
    assert {d: classify(d, outcome.divergence) for d in DIVERGENCE_DIMENSIONS} == (
        EXPECTED_CLASSIFICATION
    )


# --- CT-CONFORM-07 — build substitution ----------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_conform_c07_a_silent_build_substitution_is_attributed_to_the_provider():
    """`CT-CONFORM-07` — *"the detection path for the failure `M-PROV`'s `BuildChangedError` cannot
    see"*.

    Two things make this case what it is, and both are easy to lose.

    **It must run where `BuildChangedError` does not fire.** §6.11.18 says so explicitly. If the
    provider reports a changed build id, `M-PROV` raises and this detection path is never reached —
    the case would be measuring `CT-PROV-05` and passing for the wrong reason. So the induced
    substitution keeps the reported build identical and changes only what the model does, which is
    the shape of a provider swapping a quantization behind an unchanged name (RISK-22).

    **The attribution is the assertion, not the detection.** A score shift on frozen fixtures with
    an unchanged package is going to be noticed by something; reported as a *package* finding it
    sends someone to audit a rubric nobody touched, and the substitution keeps running.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    detect = require(CONFORM_MODULE, "detect_build_substitution", issue="#134")
    substitute = require(CONFORM_MODULE, "silent_build_substitution", issue="#134")

    suite = build_suite()
    baseline = suite.run("v1", _two_backends(), cohort=_synthetic_cohort())

    with substitute(_two_backends()[0]) as swapped:
        rerun = suite.run("v1", [swapped], cohort=_synthetic_cohort())

    assert not rerun.build_changed_error_raised, (
        "M-PROV's BuildChangedError fired, so this run is not the configuration CT-CONFORM-07 "
        "exists for — it is testing CT-PROV-05 and would pass with no detection path at all"
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
    assert not finding.package_changed


# --- CT-CONFORM-13 — resolved, not requested ------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_conform_c13_the_report_names_both_backends_resolved_builds_not_the_requested_ones():
    """`CT-CONFORM-13` — *"the resolved builds are what make a divergence attributable"*.

    Two assertions the clause makes separately and a report can satisfy separately:

    **Resolved, not requested.** A report naming only what was asked for *"would be consistent
    with a silent substitution"* — the exact failure `CT-CONFORM-07` above detects. So the case
    drives a run where the two differ and asserts the report carries the resolved value.

    **Both, not one.** A divergence report naming one backend's builds is an attribution with a
    hole in the middle: the reader knows what one side ran and is guessing about the other.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue="#134")
    substitute = require(CONFORM_MODULE, "silent_build_substitution", issue="#134")

    backends = _two_backends()
    with substitute(backends[0]) as swapped:
        report = build_suite().run("v1", [swapped, backends[1]], cohort=_synthetic_cohort())

    assert set(report.observability) >= {
        "per_dimension_divergence",
        "fixture_set_version",
        RESOLVED_BUILDS_FIELD,
    }

    resolved = report.observability[RESOLVED_BUILDS_FIELD]
    assert len(resolved) == 2, (
        f"the report names {len(resolved)} backend's builds; the clause says **both**, and one "
        f"side named is an attribution with a hole in the middle"
    )
    for profile, builds in resolved.items():
        assert builds, f"{profile}'s resolved builds are empty"

    requested = report.observability.get(REQUESTED_BUILDS_FIELD)
    if requested is not None:
        assert resolved != requested, (
            "a build was substituted under an unchanged name and the report's resolved builds are "
            "identical to the requested ones — so the report is echoing the request, which is "
            "consistent with exactly the substitution CT-CONFORM-07 detects"
        )
